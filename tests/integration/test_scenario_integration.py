"""Integration test suite for Milestone P12 Scenario Management & Engineering Comparisons.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Tests complete end-to-end workflows:
- Multi-level scenario inheritance (Baseline -> Parent -> Child -> Grandchild >= 3 levels)
- Signalling upgrade study (Fixed Block to CBTC Moving Block)
- Block length sensitivity matrix with bottleneck migration
- Directional analysis (FORWARD vs REVERSE)
- Result association and invalidation on parameter modification
- Export and import consistency
"""

import copy
import pytest

from headway.data.canonical import (
    CanonicalProject,
    InfrastructureModel,
    Node,
    Platform,
    ResourceInterval,
    RollingStockModel,
    SignallingModel,
    SignallingTechnologyType,
    Station,
    Track,
    TrackLink,
    TractionModelType,
    TrainType,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.scenarios.result_association import RunStatus
from headway.scenarios.scenario_manager import ScenarioManager
from headway.scenarios.scenario_models import (
    ExplicitOverride,
    OverrideAction,
    ScenarioDefinition,
    ScenarioStatus,
    ScenarioType,
)
from headway.scenarios.templates import ScenarioTemplateFactory


@pytest.fixture
def railway_network_project() -> CanonicalProject:
    """Creates a comprehensive railway project with multi-aspect signalling, TVS, and stations."""
    nodes = [
        Node(node_id="N_A"),
        Node(node_id="N_B"),
        Node(node_id="N_C"),
        Node(node_id="N_D"),
    ]
    tracks = [Track(track_id="TRK_MAIN")]
    links = [
        TrackLink(
            link_id="LNK_A_B",
            track_id="TRK_MAIN",
            start_node_id="N_A",
            end_node_id="N_B",
            length_m=1200.0,
            max_speed_ms=30.0,
        ),
        TrackLink(
            link_id="LNK_B_C",
            track_id="TRK_MAIN",
            start_node_id="N_B",
            end_node_id="N_C",
            length_m=900.0,
            max_speed_ms=25.0,
        ),
        TrackLink(
            link_id="LNK_C_D",
            track_id="TRK_MAIN",
            start_node_id="N_C",
            end_node_id="N_D",
            length_m=1500.0,
            max_speed_ms=35.0,
        ),
    ]
    stations = [
        Station(station_id="STN_B", name="Station Bravo"),
        Station(station_id="STN_C", name="Station Charlie"),
    ]
    platforms = [
        Platform(
            platform_id="PLT_B1",
            station_id="STN_B",
            link_id="LNK_B_C",
            start_offset_m=50.0,
            end_offset_m=350.0,
            length_m=300.0,
        )
    ]
    tvs_sections = [
        TVSSection(
            tvs_id="TVS_CD",
            tunnel_id="TUNNEL_01",
            track_id="TRK_MAIN",
            link_intervals=[ResourceInterval(link_id="LNK_C_D", start_offset_m=0.0, end_offset_m=1500.0)],
            release_delay_s=6.0,
            max_train_occupancy=1,
        )
    ]
    train_types = [
        TrainType(
            train_type_id="METRO_8CAR",
            description="8-Car Metro Train",
            length_m=160.0,
            mass_empty_kg=190_000.0,
            mass_loaded_kg=240_000.0,
            max_speed_ms=35.0,
            max_acceleration_ms2=0.9,
            max_service_deceleration_ms2=0.9,
            emergency_deceleration_ms2=1.3,
            traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
            power_w=3_200_000.0,
            max_tractive_effort_n=220_000.0,
            davis_a_n=1600.0,
            davis_b_ns_m=28.0,
            davis_c_ns2_m2=4.2,
        )
    ]
    return CanonicalProject(
        project_id="PRJ_INTEGRATION_01",
        name="Integration Benchmark Network",
        schema_version="1.0.0",
        infrastructure=InfrastructureModel(
            nodes=nodes,
            tracks=tracks,
            track_links=links,
            stations=stations,
            platforms=platforms,
            tvs_sections=tvs_sections,
        ),
        rolling_stock=RollingStockModel(train_types=train_types),
        signalling=SignallingModel(),
    )


class TestScenarioIntegration:
    """Comprehensive multi-scenario integration testing."""

    def test_multi_level_inheritance_chain(self, railway_network_project: CanonicalProject) -> None:
        """P12-INH-001 & P12-INH-002: Test >= 3 level inheritance chain with parameter cascade."""
        mgr = ScenarioManager(railway_network_project)

        # Level 1: Parent scenario modifies LNK_A_B speed to 35.0 m/s
        s1 = mgr.create_scenario("SCN_L1_SPEED", "Level 1 Speed Upgrade", base_scenario_id="BASELINE")
        mgr.add_override(
            "SCN_L1_SPEED",
            ExplicitOverride(
                override_id="OVR_L1",
                scenario_id="SCN_L1_SPEED",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_A_B",
                parameter_path="max_speed_ms",
                new_value=35.0,
            ),
        )

        # Level 2: Child scenario inherits L1, modifies LNK_B_C speed to 30.0 m/s
        s2 = mgr.create_scenario("SCN_L2_SPEED", "Level 2 Speed Upgrade", base_scenario_id="SCN_L1_SPEED")
        mgr.add_override(
            "SCN_L2_SPEED",
            ExplicitOverride(
                override_id="OVR_L2",
                scenario_id="SCN_L2_SPEED",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_B_C",
                parameter_path="max_speed_ms",
                new_value=30.0,
            ),
        )

        # Level 3: Grandchild scenario inherits L2, overrides LNK_A_B speed to 40.0 m/s (precedence over L1)
        s3 = mgr.create_scenario("SCN_L3_SPEED", "Level 3 Speed Upgrade", base_scenario_id="SCN_L2_SPEED")
        mgr.add_override(
            "SCN_L3_SPEED",
            ExplicitOverride(
                override_id="OVR_L3",
                scenario_id="SCN_L3_SPEED",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_A_B",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )

        eff1 = mgr.get_effective_configuration("SCN_L1_SPEED")
        eff2 = mgr.get_effective_configuration("SCN_L2_SPEED")
        eff3 = mgr.get_effective_configuration("SCN_L3_SPEED")

        # L1: LNK_A_B is 35.0, LNK_B_C is 25.0
        assert eff1.project_dict["infrastructure"]["track_links"][0]["max_speed_ms"] == 35.0
        assert eff1.project_dict["infrastructure"]["track_links"][1]["max_speed_ms"] == 25.0

        # L2: LNK_A_B is 35.0 (inherited), LNK_B_C is 30.0 (child)
        assert eff2.project_dict["infrastructure"]["track_links"][0]["max_speed_ms"] == 35.0
        assert eff2.project_dict["infrastructure"]["track_links"][1]["max_speed_ms"] == 30.0

        # L3: LNK_A_B is 40.0 (overridden), LNK_B_C is 30.0 (inherited from L2)
        assert eff3.project_dict["infrastructure"]["track_links"][0]["max_speed_ms"] == 40.0
        assert eff3.project_dict["infrastructure"]["track_links"][1]["max_speed_ms"] == 30.0

        # All three effective hashes must be distinct
        h1 = mgr.get_effective_hash("SCN_L1_SPEED")
        h2 = mgr.get_effective_hash("SCN_L2_SPEED")
        h3 = mgr.get_effective_hash("SCN_L3_SPEED")
        assert len({h1, h2, h3}) == 3

    def test_signalling_technology_upgrade_comparison(self, railway_network_project: CanonicalProject) -> None:
        """P12-CMP-001 to 008: Signalling comparison study (Fixed Block vs CBTC)."""
        mgr = ScenarioManager(railway_network_project)

        # Baseline: Fixed Block
        mgr.register_simulation_result(
            scenario_id="BASELINE",
            analysis_type="HEADWAY",
            metrics={
                "minimum_headway_s": 120.0,
                "capacity_trains_per_hour": 30.0,
                "bottleneck_resource_id": "LNK_B_C",
            },
        )

        # Scenario 1: ETCS Level 2
        scn_etcs = ScenarioTemplateFactory.create_signalling_comparison_scenario(
            scenario_id="SCN_ETCS_L2",
            scenario_name="ETCS Level 2 Upgrade",
            target_technology=SignallingTechnologyType.ETCS_LEVEL_2,
        )
        mgr._scenarios["SCN_ETCS_L2"] = scn_etcs
        mgr.register_simulation_result(
            scenario_id="SCN_ETCS_L2",
            analysis_type="HEADWAY",
            metrics={
                "minimum_headway_s": 95.0,
                "capacity_trains_per_hour": 37.89,
                "bottleneck_resource_id": "LNK_B_C",
            },
        )

        # Scenario 2: CBTC Moving Block
        scn_cbtc = ScenarioTemplateFactory.create_signalling_comparison_scenario(
            scenario_id="SCN_CBTC",
            scenario_name="CBTC Moving Block Upgrade",
            target_technology=SignallingTechnologyType.CBTC_MOVING_BLOCK,
        )
        mgr._scenarios["SCN_CBTC"] = scn_cbtc
        mgr.register_simulation_result(
            scenario_id="SCN_CBTC",
            analysis_type="HEADWAY",
            metrics={
                "minimum_headway_s": 75.0,
                "capacity_trains_per_hour": 48.0,
                "bottleneck_resource_id": "PLT_B1",
            },
        )

        cmp_rep = mgr.compare_scenarios("BASELINE", ["SCN_ETCS_L2", "SCN_CBTC"], analysis_type="HEADWAY")

        # Verify CBTC metrics comparison
        cbtc_diffs = cmp_rep.metric_differences["SCN_CBTC"]
        h_diff = next(d for d in cbtc_diffs if d.metric_name == "minimum_headway_s")
        assert h_diff.baseline_value == 120.0
        assert h_diff.scenario_value == 75.0
        assert h_diff.absolute_change == -45.0
        assert h_diff.percentage_change == -37.5
        assert h_diff.is_improvement is True

        c_diff = next(d for d in cbtc_diffs if d.metric_name == "capacity_trains_per_hour")
        assert c_diff.baseline_value == 30.0
        assert c_diff.scenario_value == 48.0
        assert c_diff.absolute_change == 18.0
        assert c_diff.percentage_change == 60.0
        assert c_diff.is_improvement is True

        # Verify bottleneck migration in CBTC
        cbtc_shift = next(s for s in cmp_rep.bottleneck_shifts if s.comparison_scenario_id == "SCN_CBTC")
        assert cbtc_shift.bottleneck_migrated is True
        assert cbtc_shift.baseline_bottleneck_id == "LNK_B_C"
        assert cbtc_shift.comparison_bottleneck_id == "PLT_B1"

    def test_block_sensitivity_matrix(self, railway_network_project: CanonicalProject) -> None:
        """P12-CMP-004 & P12-B015: Parameter sweep with block length sensitivity."""
        mgr = ScenarioManager(railway_network_project)

        block_lengths = [1000.0, 800.0, 600.0, 400.0]
        scenario_ids = []

        for bl in block_lengths:
            sid = f"SCN_BLK_{int(bl)}"
            scenario_ids.append(sid)
            scn = ScenarioTemplateFactory.create_block_sensitivity_scenario(
                scenario_id=sid,
                scenario_name=f"Block {int(bl)}m",
                target_link_id="LNK_A_B",
                new_block_length_m=bl,
            )
            mgr._scenarios[sid] = scn
            mgr.register_simulation_result(
                scenario_id=sid,
                analysis_type="CAPACITY",
                metrics={
                    "headway_s": 60.0 + (bl / 20.0),
                    "capacity_tph": 3600.0 / (60.0 + (bl / 20.0)),
                },
            )

        mgr.register_simulation_result(
            scenario_id="BASELINE",
            analysis_type="CAPACITY",
            metrics={"headway_s": 120.0, "capacity_tph": 30.0},
        )

        cmp_rep = mgr.compare_scenarios("BASELINE", scenario_ids, analysis_type="CAPACITY")
        assert len(cmp_rep.comparison_scenario_ids) == 4

        # Verify parameter differences recorded for all 4 scenarios
        assert len(cmp_rep.parameter_differences) == 1
        param_diff = cmp_rep.parameter_differences[0]
        assert param_diff.object_id == "LNK_A_B"
        for bl in block_lengths:
            assert param_diff.values_by_scenario[f"SCN_BLK_{int(bl)}"] == bl

    def test_directional_comparison_and_invalidation(self, railway_network_project: CanonicalProject) -> None:
        """P12-DIR-001 to 005 & P12-RES-002: Direction changes invalidate results and report differences."""
        mgr = ScenarioManager(railway_network_project)

        mgr.create_scenario("SCN_DIRECTIONAL", "Directional Study", running_direction=RunningDirection.FORWARD)
        run_fwd = mgr.register_simulation_result(
            scenario_id="SCN_DIRECTIONAL",
            analysis_type="JOURNEY_TIME",
            metrics={"journey_time_s": 150.0},
        )
        assert run_fwd.status == RunStatus.VALID

        # Switch direction to REVERSE; prior run must be marked STALE
        mgr.set_scenario_direction("SCN_DIRECTIONAL", RunningDirection.REVERSE)
        runs = mgr.get_simulation_runs("SCN_DIRECTIONAL")
        assert runs[0].status == RunStatus.STALE

        # Register new run under REVERSE
        run_rev = mgr.register_simulation_result(
            scenario_id="SCN_DIRECTIONAL",
            analysis_type="JOURNEY_TIME",
            metrics={"journey_time_s": 165.0},
        )
        assert run_rev.status == RunStatus.VALID

        # Compare with baseline
        mgr.register_simulation_result(
            scenario_id="BASELINE",
            analysis_type="JOURNEY_TIME",
            metrics={"journey_time_s": 150.0},
        )

        cmp_rep = mgr.compare_scenarios("BASELINE", ["SCN_DIRECTIONAL"], analysis_type="JOURNEY_TIME")
        assert any("REVERSE" in note for note in cmp_rep.direction_compatibility_notes)

    def test_export_and_metadata_serialization(self, railway_network_project: CanonicalProject) -> None:
        """P12-SCN-007 & P12-RES-006: Scenario export contains all scenarios, overrides, and runs."""
        mgr = ScenarioManager(railway_network_project)

        mgr.create_scenario("SCN_EXPORT_1", "Exportable Scenario 1")
        mgr.add_override(
            "SCN_EXPORT_1",
            ExplicitOverride(
                override_id="OVR_EXP",
                scenario_id="SCN_EXPORT_1",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_A_B",
                parameter_path="max_speed_ms",
                new_value=32.0,
            ),
        )
        mgr.register_simulation_result(
            scenario_id="SCN_EXPORT_1",
            analysis_type="HEADWAY",
            metrics={"headway_s": 100.0},
        )

        exported = mgr.export_all_scenarios()
        assert exported["baseline_id"] == "BASELINE"
        assert len(exported["scenarios"]) == 2  # BASELINE + SCN_EXPORT_1
        assert len(exported["simulation_runs"]) == 1
        assert exported["simulation_runs"][0]["scenario_id"] == "SCN_EXPORT_1"
        assert exported["simulation_runs"][0]["metrics"]["headway_s"] == 100.0
