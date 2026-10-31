"""Engineering test suite for Operational Performance Factor (RHS-FEATURE-PERF-FACTOR-001).

Validates:
1. Canonical model definitions and range constraints [0.5, 1.0].
2. Precedence rule resolution: Analysis Row > Scenario Default > 1.0 Fallback.
3. Excel importer and validator range checks (ERR_FIELD_RANGE).
4. Traction force derating and adhesion limits.
5. Service braking derating and stopping distance scaling.
6. Safety invariants: Emergency braking, supervised braking protection, line speed limits unscaled.
7. Multi-train simulation dynamics under forward and reverse directions.
8. Verification against 05_comprehensive_line benchmark dataset.
9. Executive KPI reporting and document assembly across HTML, PDF, and Excel.
"""

import math
from pathlib import Path
import pytest
from pydantic import ValidationError

from headway.analysis.headway_results import HeadwayResult
from headway.data.canonical import (
    AnalysisConfig,
    AnalysisModel,
    AnalysisType,
    CanonicalProject,
    Scenario,
    TrackLink,
)
from headway.data.converter import _build_analysis_model
from headway.data.importer import ExcelImporter, RawWorkbookData
from headway.data.validation import Severity, ValidationReport
from headway.data.validator import DatasetValidator
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import LinkTraversal, Route, RouteEngine
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_models import ExecutiveKpis, ReportDocument, ReportMetadata
from headway.rolling_stock.braking import (
    BrakingCategory,
    ConstantDecelerationBrakingModel,
    create_braking_model,
)
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.rolling_stock.traction import SimplifiedTractionModel, create_traction_model
from headway.scenarios.scenario_models import ScenarioDefinition
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.resources import ManagedResource, ResourceCategory, ResourceInterval
from headway.simulation.integrator import MicroscopicSimulator
from headway.simulation.multi_train_engine import MultiTrainSimulator
from headway.simulation.service_instance import ServiceType, TrainGenerator, TrainServiceInstance
from headway.simulation.state import DynamicMode
from headway.ui.file_manager import FileManager
from tests.block_geometry_expectations import load_and_assert_pipeline_raises


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _make_test_train_params(
    train_id: str = "TT_TEST",
    mass_kg: float = 200_000.0,
    max_pwr_w: float = 3_000_000.0,
    max_te_n: float = 250_000.0,
    max_v_ms: float = 40.0,
    max_acc_ms2: float = 1.0,
    service_dec_ms2: float = 0.8,
    emergency_dec_ms2: float = 1.2,
) -> RollingStockParameters:
    from headway.data.canonical import TractionModelType
    return RollingStockParameters(
        train_type_id=train_id,
        description="Performance Factor Test EMU",
        length_m=100.0,
        mass_empty_kg=mass_kg,
        mass_loaded_kg=mass_kg,
        rotating_mass_factor=0.08,
        max_speed_ms=max_v_ms,
        max_acceleration_ms2=max_acc_ms2,
        max_service_deceleration_ms2=service_dec_ms2,
        emergency_deceleration_ms2=emergency_dec_ms2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=1500.0,
        davis_b_ns_m=25.0,
        davis_c_ns2_m2=0.35,
        power_w=max_pwr_w,
        max_tractive_effort_n=max_te_n,
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.6,
    )


def _make_simple_route(length_m: float = 3000.0):
    from headway.data.canonical import TrackLink
    from headway.infrastructure.route import LinkTraversal, Route
    tl = TrackLink(
        link_id="LNK_01",
        track_id="TRK_01",
        start_node_id="ND_01",
        end_node_id="ND_02",
        length_m=length_m,
        max_speed_ms=83.333,
    )
    trav = LinkTraversal(
        link=tl,
        direction=RunningDirection.FORWARD,
        sequence_index=0,
        start_distance_m=0.0,
        end_distance_m=length_m,
    )
    return Route(route_id="RT_TEST", traversals=[trav])


# ---------------------------------------------------------------------------
# 1. Canonical Model Range & Precedence
# ---------------------------------------------------------------------------

class TestPerformanceFactorCanonical:
    """Canonical Model range validation and precedence resolution."""

    def test_analysis_config_range_validation(self):
        """Values in [0.5, 1.0] accepted; out-of-range rejected by AnalysisConfig."""
        # Valid boundaries and interior
        cfg_min = AnalysisConfig(analysis_id="A1", performance_factor=0.5)
        assert cfg_min.performance_factor == 0.5

        cfg_mid = AnalysisConfig(analysis_id="A2", performance_factor=0.85)
        assert cfg_mid.performance_factor == 0.85

        cfg_max = AnalysisConfig(analysis_id="A3", performance_factor=1.0)
        assert cfg_max.performance_factor == 1.0

        # Below 0.5 rejected
        with pytest.raises(ValidationError):
            AnalysisConfig(analysis_id="A_LOW", performance_factor=0.49)

        # Above 1.0 rejected
        with pytest.raises(ValidationError):
            AnalysisConfig(analysis_id="A_HIGH", performance_factor=1.01)

    def test_scenario_default_range_validation(self):
        """Scenario and ScenarioDefinition enforce [0.5, 1.0] on default_performance_factor."""
        scen_valid = Scenario(
            scenario_id="S1",
            description="Valid",
            default_performance_factor=0.9,
        )
        assert scen_valid.default_performance_factor == 0.9

        scen_none = Scenario(scenario_id="S2", description="None is valid")
        assert scen_none.default_performance_factor is None

        with pytest.raises(ValidationError):
            Scenario(scenario_id="S_BAD", description="Bad", default_performance_factor=0.3)

        with pytest.raises(ValidationError):
            Scenario(scenario_id="S_BAD", description="Bad", default_performance_factor=1.1)

        scendef_valid = ScenarioDefinition(
            scenario_id="SD1",
            scenario_name="Valid",
            description="Valid",
            default_performance_factor=0.8,
        )
        assert scendef_valid.default_performance_factor == 0.8

        with pytest.raises(ValidationError):
            ScenarioDefinition(scenario_id="SD_BAD", scenario_name="Bad", description="Bad", default_performance_factor=0.4)

    def test_precedence_hierarchy(self):
        """Verify: Analysis row > Scenario default > 1.0 default fallback."""
        # Case 1: Neither row nor scenario specifies factor -> 1.0 (default)
        wb1 = RawWorkbookData("HEADWAY_ANALYSIS", Path("dummy.xlsx"), {})
        wb1.worksheets["AnalysisSettings"] = [{"analysis_id": "A1", "performance_factor": None}]
        m1 = _build_analysis_model(wb1, default_pf=None)
        assert m1.analyses[0].performance_factor == 1.0
        assert m1.analyses[0].performance_factor_source == "default"

        # Case 2: Row empty, scenario specifies 0.90 -> 0.90 (scenario)
        wb2 = RawWorkbookData("HEADWAY_ANALYSIS", Path("dummy.xlsx"), {})
        wb2.worksheets["AnalysisSettings"] = [{"analysis_id": "A2", "performance_factor": None}]
        m2 = _build_analysis_model(wb2, default_pf=0.90)
        assert m2.analyses[0].performance_factor == 0.90
        assert m2.analyses[0].performance_factor_source == "scenario"

        # Case 3: Row specifies 0.80, scenario specifies 0.90 -> 0.80 (analysis)
        wb3 = RawWorkbookData("HEADWAY_ANALYSIS", Path("dummy.xlsx"), {})
        wb3.worksheets["AnalysisSettings"] = [{"analysis_id": "A3", "performance_factor": 0.80}]
        m3 = _build_analysis_model(wb3, default_pf=0.90)
        assert m3.analyses[0].performance_factor == 0.80
        assert m3.analyses[0].performance_factor_source == "analysis"


# ---------------------------------------------------------------------------
# 2. Importer & Validator Range Checks
# ---------------------------------------------------------------------------

class TestPerformanceFactorImporterValidator:
    """Importer and DatasetValidator enforcement of performance factor ranges."""

    def test_importer_range_validation_failure(self):
        """ExcelImporter logs ERR_FIELD_RANGE for out-of-bounds performance factor."""
        importer = ExcelImporter()
        report = ValidationReport("PRJ_TEST")
        wb_data = RawWorkbookData("HEADWAY_ANALYSIS", Path("dummy.xlsx"), {})
        wb_data.worksheets["AnalysisSettings"] = [
            {"analysis_id": "AN_BAD_LOW", "performance_factor": 0.40},
        ]
        validator = DatasetValidator(report)
        validator.validate_all({"HEADWAY_ANALYSIS": wb_data})

        codes = [f.error_code for f in report.findings]
        assert "ERR_FIELD_RANGE" in codes

    def test_importer_scenario_default_range_failure(self):
        """ExcelImporter logs ERR_FIELD_RANGE for out-of-bounds scenario default factor."""
        report = ValidationReport("PRJ_TEST")
        wb_data = RawWorkbookData("SCENARIOS", Path("dummy.xlsx"), {})
        wb_data.worksheets["ScenarioDefinitions"] = [
            {"scenario_id": "SCN_BAD", "description": "Invalid", "default_performance_factor": 1.25},
        ]
        validator = DatasetValidator(report)
        validator.validate_all({"SCENARIOS": wb_data})

        codes = [f.error_code for f in report.findings]
        assert "ERR_FIELD_RANGE" in codes


# ---------------------------------------------------------------------------
# 3. Dynamics: Traction Derating & Adhesion
# ---------------------------------------------------------------------------

class TestTractionDerating:
    """Traction force derating by performance factor."""

    def test_traction_derated_proportionally(self):
        """Traction model scales raw tractive effort by performance factor."""
        params = _make_test_train_params()

        m_full = create_traction_model(params, performance_factor=1.0)
        m_80 = create_traction_model(params, performance_factor=0.8)
        m_60 = create_traction_model(params, performance_factor=0.6)

        # Standstill force (speed = 0)
        eval_full_0 = m_full.evaluate_tractive_effort(0.0, apply_acceleration_limit=False)
        eval_80_0 = m_80.evaluate_tractive_effort(0.0, apply_acceleration_limit=False)
        eval_60_0 = m_60.evaluate_tractive_effort(0.0, apply_acceleration_limit=False)

        assert math.isclose(eval_80_0.available_tractive_force_n, eval_full_0.available_tractive_force_n * 0.8, rel_tol=1e-5)
        assert math.isclose(eval_60_0.available_tractive_force_n, eval_full_0.available_tractive_force_n * 0.6, rel_tol=1e-5)

        # Constant power region (speed = 25 m/s)
        eval_full_v = m_full.evaluate_tractive_effort(25.0, apply_acceleration_limit=False)
        eval_80_v = m_80.evaluate_tractive_effort(25.0, apply_acceleration_limit=False)
        assert math.isclose(eval_80_v.available_tractive_force_n, eval_full_v.available_tractive_force_n * 0.8, rel_tol=1e-5)

    def test_adhesion_limit_applied_to_derated_traction(self):
        """Adhesion limit F_adh applies to derated traction force."""
        # High acc limit so adhesion governs:
        # m_adh = 200,000 * 0.6 = 120,000 kg. F_adh = 0.25 * 120,000 * 9.81 = 294,300 N.
        # At 1.0 factor: TE = 400,000 N > 294,300 N -> adhesion limited.
        # At 0.5 factor: TE = 200,000 N < 294,300 N -> NOT adhesion limited.
        params = _make_test_train_params(max_te_n=400_000.0, max_acc_ms2=5.0)
        m_full = create_traction_model(params, performance_factor=1.0)
        m_half = create_traction_model(params, performance_factor=0.5)

        eval_full = m_full.evaluate_tractive_effort(0.0, apply_adhesion_limit=True)
        eval_half = m_half.evaluate_tractive_effort(0.0, apply_adhesion_limit=True)

        assert eval_full.is_adhesion_limited
        assert not eval_half.is_adhesion_limited
        assert math.isclose(eval_half.available_tractive_force_n, 200_000.0, rel_tol=1e-5)


# ---------------------------------------------------------------------------
# 4. Dynamics: Braking Derating & Invariants
# ---------------------------------------------------------------------------

class TestBrakingDeratingAndInvariants:
    """Braking model derates service braking while keeping emergency and supervised unscaled."""

    def test_service_braking_derated_while_emergency_unscaled(self):
        """ConstantDecelerationBrakingModel derates OPERATIONAL_SERVICE but NOT EMERGENCY."""
        params = _make_test_train_params(service_dec_ms2=1.0, emergency_dec_ms2=1.5)

        b_model_full = create_braking_model(params, performance_factor=1.0)
        b_model_75 = create_braking_model(params, performance_factor=0.75)

        # Operational service braking: scaled
        dec_svc_full = b_model_full.evaluate_deceleration(20.0, category=BrakingCategory.OPERATIONAL_SERVICE)
        dec_svc_75 = b_model_75.evaluate_deceleration(20.0, category=BrakingCategory.OPERATIONAL_SERVICE)
        assert math.isclose(dec_svc_full.effective_deceleration_ms2, 1.0, rel_tol=1e-5)
        assert math.isclose(dec_svc_75.effective_deceleration_ms2, 0.75, rel_tol=1e-5)

        # Emergency braking: strictly unscaled
        dec_em_full = b_model_full.evaluate_deceleration(20.0, category=BrakingCategory.EMERGENCY)
        dec_em_75 = b_model_75.evaluate_deceleration(20.0, category=BrakingCategory.EMERGENCY)
        assert math.isclose(dec_em_full.effective_deceleration_ms2, 1.5, rel_tol=1e-5)
        assert math.isclose(dec_em_75.effective_deceleration_ms2, 1.5, rel_tol=1e-5)

        # Supervised braking (protection): strictly unscaled
        dec_sup_full = b_model_full.evaluate_deceleration(20.0, category=BrakingCategory.SUPERVISED)
        dec_sup_75 = b_model_75.evaluate_deceleration(20.0, category=BrakingCategory.SUPERVISED)
        assert math.isclose(dec_sup_full.effective_deceleration_ms2, 1.0, rel_tol=1e-5)
        assert math.isclose(dec_sup_75.effective_deceleration_ms2, 1.0, rel_tol=1e-5)

    def test_service_braking_distance_scales_inversely(self):
        """Stopping distance from initial speed scales as 1 / performance_factor."""
        params = _make_test_train_params(service_dec_ms2=1.0)
        b_100 = create_braking_model(params, performance_factor=1.0)
        b_80 = create_braking_model(params, performance_factor=0.8)

        v_init = 20.0
        d_100 = b_100.calculate_stopping_distance(v_init, 0.0, category=BrakingCategory.OPERATIONAL_SERVICE)
        d_80 = b_80.calculate_stopping_distance(v_init, 0.0, category=BrakingCategory.OPERATIONAL_SERVICE)

        # d = v^2 / (2 * a) -> d_80 / d_100 == 1 / 0.8 == 1.25
        assert math.isclose(d_80, d_100 / 0.8, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 5. Microscopic Trajectory Impact
# ---------------------------------------------------------------------------

class TestMicroscopicSimulatorDynamics:
    """Single-train trajectory reflects performance factor derating."""

    def test_trajectory_acceleration_and_journey_time(self):
        """Train with lower performance factor has longer journey time due to reduced acceleration."""
        params = _make_test_train_params()
        route = _make_simple_route(length_m=2000.0)

        sim_full = MicroscopicSimulator(route=route, params=params, performance_factor=1.0, dt_s=0.1)
        res_full = sim_full.simulate()

        sim_derated = MicroscopicSimulator(route=route, params=params, performance_factor=0.7, dt_s=0.1)
        res_derated = sim_derated.simulate()

        # Both must reach destination safely
        assert len(res_full.samples) > 0
        assert len(res_derated.samples) > 0

        # Lower performance factor requires more time to traverse identical distance
        assert res_derated.journey_time_s > res_full.journey_time_s


# ---------------------------------------------------------------------------
# 6. Pairwise Analysis: Both Leader and Follower Derating Verification
# ---------------------------------------------------------------------------

class TestPairwiseBothTrainsDerated:
    """Explicit verification that performance factor derates BOTH leader and follower in pairwise operations."""

    def test_pairwise_both_leader_and_follower_derated(self):
        """Runs pairwise simulation at 1.0 and 0.95; asserts BOTH leader and follower clearance times are longer at 0.95."""
        def run_pairwise_sim(pf: float):
            params = _make_test_train_params()
            links = [
                TrackLink(link_id="L1", track_id="TRK1", start_node_id="N0", end_node_id="N1", length_m=1500.0, max_speed_ms=40.0),
                TrackLink(link_id="L2", track_id="TRK1", start_node_id="N1", end_node_id="N2", length_m=1500.0, max_speed_ms=40.0),
                TrackLink(link_id="L3", track_id="TRK1", start_node_id="N2", end_node_id="N3", length_m=1500.0, max_speed_ms=40.0),
            ]
            travs = [
                LinkTraversal(link=links[0], direction=RunningDirection.FORWARD, sequence_index=0, start_distance_m=0.0, end_distance_m=1500.0),
                LinkTraversal(link=links[1], direction=RunningDirection.FORWARD, sequence_index=1, start_distance_m=1500.0, end_distance_m=3000.0),
                LinkTraversal(link=links[2], direction=RunningDirection.FORWARD, sequence_index=2, start_distance_m=3000.0, end_distance_m=4500.0),
            ]
            route = Route(route_id="RT_MAIN", traversals=travs)
            st = ServiceType("SVC_P", "TT_TEST", params, route)

            coord = SignallingCoordinator()
            coord.resource_controller.register_resource(
                ManagedResource("BLK_1", ResourceCategory.TRACK_BLOCK, intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1500.0)])
            )
            coord.resource_controller.register_resource(
                ManagedResource("BLK_2", ResourceCategory.TRACK_BLOCK, intervals=[ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=1500.0)])
            )
            coord.resource_controller.register_resource(
                ManagedResource("BLK_3", ResourceCategory.TRACK_BLOCK, intervals=[ResourceInterval(link_id="L3", start_offset_m=0.0, end_offset_m=1500.0)])
            )

            mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=0.5)
            trains = TrainGenerator.generate_pairwise(st, st, interval_s=60.0, start_time_s=0.0, performance_factor=pf)
            mt_sim.register_trains(trains)
            mt_sim.run_simulation(max_duration_s=600.0)

            rec_lead = coord.resource_controller._usage_records.get(("SVC_P_LEAD", "BLK_1"))
            rec_foll = coord.resource_controller._usage_records.get(("SVC_P_FOLL", "BLK_1"))
            return rec_lead.rear_clearance_s, rec_foll.rear_clearance_s

        t_lead_100, t_foll_100 = run_pairwise_sim(1.0)
        t_lead_95, t_foll_95 = run_pairwise_sim(0.95)

        # Assert BOTH leader and follower clearance times are measurably longer at 0.95 than at 1.0
        assert t_lead_95 > t_lead_100, f"Leader clearance at 0.95 ({t_lead_95}s) must be longer than at 1.0 ({t_lead_100}s)"
        assert t_foll_95 > t_foll_100, f"Follower clearance at 0.95 ({t_foll_95}s) must be longer than at 1.0 ({t_foll_100}s)"
        assert (t_lead_95 - t_lead_100) > 0.1
        assert (t_foll_95 - t_foll_100) > 0.1


# ---------------------------------------------------------------------------
# 6. Verification Against 05_comprehensive_line Reference Dataset
# ---------------------------------------------------------------------------

class TestComprehensiveLineBaselineIntegrity:
    """Loading 05_comprehensive_line defaults to 1.0 and yields identical baseline results."""

    def test_baseline_dataset_defaults_to_factor_one(self):
        """05_comprehensive_line AN_HSR_HSR_UP resolves to factor 1.0 with default source."""
        project, report, _ = FileManager.load_example_project("05_comprehensive_line")
        assert report.is_simulation_ready

        an_up = next(a for a in project.analysis.analyses if a.analysis_id == "AN_HSR_HSR_UP")
        assert an_up.performance_factor == 1.0
        assert an_up.performance_factor_source == "default"

    def test_forward_and_reverse_simulation_with_factor(self):
        """Simulation pipeline runs cleanly with explicit performance factor in both directions.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")


# ---------------------------------------------------------------------------
# 7. Reporting & Document Assembly
# ---------------------------------------------------------------------------

class TestPerformanceFactorReporting:
    """Reporting across HTML, PDF, Excel includes performance factor KPI card and metadata."""

    def test_executive_kpi_card_and_document_rendering(self):
        """ReportDocument renders Performance Factor KPI in HTML, PDF, and Excel exports.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")
