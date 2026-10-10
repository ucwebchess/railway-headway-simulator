"""Engineering benchmarks suite for Milestone P12 Scenario Management & Comparisons.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers all 28 mandatory benchmarks:
- P12-B001: Baseline immutability
- P12-B002: Scenario creation from baseline
- P12-B003: Scenario duplication
- P12-B004: Parent–child inheritance
- P12-B005: Override precedence
- P12-B006: Conflicting override detection
- P12-B007: Circular inheritance rejection
- P12-B008: Effective configuration generation
- P12-B009: Effective hash stability
- P12-B010: Hash change on override
- P12-B011: Scenario validation – invalid target
- P12-B012: Scenario validation – invalid value
- P12-B013: Scenario validation – geometry consistency
- P12-B014: Signalling comparison scenario
- P12-B015: Block-length sensitivity scenario
- P12-B016: TVS per-track scenario
- P12-B017: TVS shared scenario
- P12-B018: Whole-tunnel scenario
- P12-B019: Stochastic operation scenario
- P12-B020: Direction override
- P12-B021: Comparison – configuration differences
- P12-B022: Comparison – metric differences
- P12-B023: Comparison – bottleneck shift
- P12-B024: Result association
- P12-B025: Result invalidation on configuration change
- P12-B026: No cross-scenario state leakage
- P12-B027: Forward/reverse comparison
- P12-B028: Deterministic reproducibility
"""

import copy
import math
import pytest

from headway.core.exceptions import (
    CircularInheritanceError,
    ConflictingOverrideError,
    DataValidationError,
    ScenarioError,
    ScenarioNotFoundError,
)
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
from headway.scenarios.effective_config import calculate_effective_hash
from headway.scenarios.result_association import RunStatus
from headway.scenarios.scenario_manager import ScenarioManager
from headway.scenarios.scenario_models import (
    ExplicitOverride,
    OverrideAction,
    ScenarioDefinition,
    ScenarioStatus,
    ScenarioType,
)
from headway.scenarios.scenario_validation import ScenarioValidator
from headway.scenarios.templates import ScenarioTemplateFactory


def make_benchmark_baseline_project() -> CanonicalProject:
    """Builds a rich, complete canonical project for scenario benchmarking."""
    nodes = [
        Node(node_id="N_01"),
        Node(node_id="N_02"),
        Node(node_id="N_03"),
        Node(node_id="N_04"),
    ]
    tracks = [Track(track_id="TRK_01")]
    links = [
        TrackLink(
            link_id="LNK_01",
            track_id="TRK_01",
            start_node_id="N_01",
            end_node_id="N_02",
            length_m=1000.0,
            max_speed_ms=30.0,
        ),
        TrackLink(
            link_id="LNK_02",
            track_id="TRK_01",
            start_node_id="N_02",
            end_node_id="N_03",
            length_m=800.0,
            max_speed_ms=30.0,
        ),
        TrackLink(
            link_id="LNK_03",
            track_id="TRK_01",
            start_node_id="N_03",
            end_node_id="N_04",
            length_m=1200.0,
            max_speed_ms=30.0,
        ),
    ]
    stations = [Station(station_id="STN_A", name="Alpha Central")]
    platforms = [
        Platform(
            platform_id="PLT_A1",
            station_id="STN_A",
            link_id="LNK_02",
            start_offset_m=50.0,
            end_offset_m=350.0,
            length_m=300.0,
        )
    ]
    tvs_sections = [
        TVSSection(
            tvs_id="TVS_01",
            tunnel_id="TUN_01",
            track_id="TRK_01",
            link_intervals=[ResourceInterval(link_id="LNK_03", start_offset_m=0.0, end_offset_m=1200.0)],
            release_delay_s=5.0,
            max_train_occupancy=1,
        )
    ]
    train_types = [
        TrainType(
            train_type_id="TT_METRO",
            description="Standard Metro Train",
            length_m=150.0,
            mass_empty_kg=180_000.0,
            mass_loaded_kg=220_000.0,
            max_speed_ms=30.0,
            max_acceleration_ms2=0.8,
            max_service_deceleration_ms2=0.8,
            emergency_deceleration_ms2=1.2,
            traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
            power_w=3_000_000.0,
            max_tractive_effort_n=200_000.0,
            davis_a_n=1500.0,
            davis_b_ns_m=25.0,
            davis_c_ns2_m2=4.0,
        )
    ]
    return CanonicalProject(
        project_id="PRJ_BENCHMARK",
        name="Benchmark Railway Project",
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


class TestScenarioManagementBenchmarks:
    """Rigorous verification of benchmarks P12-B001 to P12-B028."""

    def test_p12_b001_baseline_immutability(self) -> None:
        """P12-B001: Modifying any scenario or applying overrides never alters baseline."""
        base_proj = make_benchmark_baseline_project()
        orig_speed = base_proj.infrastructure.track_links[0].max_speed_ms
        mgr = ScenarioManager(base_proj)

        # Create child scenario and apply an override
        scn = mgr.create_scenario("SCN_SPEED", "Higher Speed")
        mgr.add_override(
            "SCN_SPEED",
            ExplicitOverride(
                override_id="OVR_SPD",
                scenario_id="SCN_SPEED",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=45.0,
            ),
        )

        eff = mgr.get_effective_configuration("SCN_SPEED")
        assert eff.project_dict["infrastructure"]["track_links"][0]["max_speed_ms"] == 45.0

        # Baseline must remain completely unchanged
        assert base_proj.infrastructure.track_links[0].max_speed_ms == orig_speed
        assert mgr.baseline_project.infrastructure.track_links[0].max_speed_ms == orig_speed

    def test_p12_b002_scenario_creation_from_baseline(self) -> None:
        """P12-B002: Scenario creation from baseline registers active scenario."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn = mgr.create_scenario(
            scenario_id="SCN_NEW",
            scenario_name="New Scenario",
            description="Testing creation",
            base_scenario_id="BASELINE",
            scenario_type=ScenarioType.SIGNALLING_COMPARISON,
            running_direction=RunningDirection.FORWARD,
            tags=["study"],
        )

        assert scn.scenario_id == "SCN_NEW"
        assert scn.status == ScenarioStatus.ACTIVE
        assert scn.base_scenario_id == "BASELINE"
        assert not scn.is_baseline
        assert "SCN_NEW" in [s.scenario_id for s in mgr.list_scenarios()]

    def test_p12_b003_scenario_duplication(self) -> None:
        """P12-B003: Duplicating a scenario copies all metadata and overrides independently."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn = mgr.create_scenario("SCN_SRC", "Source Scenario")
        mgr.add_override(
            "SCN_SRC",
            ExplicitOverride(
                override_id="OVR_1",
                scenario_id="SCN_SRC",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )

        dup = mgr.duplicate_scenario("SCN_SRC", "SCN_DUP", new_name="Duplicated Scenario")
        assert dup.scenario_id == "SCN_DUP"
        assert len(dup.overrides) == 1
        assert dup.overrides[0].new_value == 40.0
        assert dup.overrides[0].scenario_id == "SCN_DUP"

        # Modify duplicate; original source must not be altered
        mgr.add_override(
            "SCN_DUP",
            ExplicitOverride(
                override_id="OVR_2",
                scenario_id="SCN_DUP",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_02",
                parameter_path="max_speed_ms",
                new_value=35.0,
            ),
        )
        assert len(mgr.get_scenario("SCN_SRC").overrides) == 1
        assert len(mgr.get_scenario("SCN_DUP").overrides) == 2

    def test_p12_b004_parent_child_inheritance(self) -> None:
        """P12-B004: Child scenario inherits overrides from parent scenario."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        # Parent overrides LNK_01
        mgr.create_scenario("SCN_PARENT", "Parent Scenario")
        mgr.add_override(
            "SCN_PARENT",
            ExplicitOverride(
                override_id="OVR_P",
                scenario_id="SCN_PARENT",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )

        # Child inherits from parent and overrides LNK_02
        mgr.create_scenario("SCN_CHILD", "Child Scenario", base_scenario_id="SCN_PARENT")
        mgr.add_override(
            "SCN_CHILD",
            ExplicitOverride(
                override_id="OVR_C",
                scenario_id="SCN_CHILD",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_02",
                parameter_path="max_speed_ms",
                new_value=35.0,
            ),
        )

        eff_child = mgr.get_effective_configuration("SCN_CHILD")
        links = eff_child.project_dict["infrastructure"]["track_links"]
        assert links[0]["max_speed_ms"] == 40.0  # Inherited from parent
        assert links[1]["max_speed_ms"] == 35.0  # Defined on child
        assert len(eff_child.applied_overrides) == 2

    def test_p12_b005_override_precedence(self) -> None:
        """P12-B005: Child overrides take precedence over parent overrides on same parameter."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        mgr.create_scenario("SCN_P", "Parent")
        mgr.add_override(
            "SCN_P",
            ExplicitOverride(
                override_id="OVR_P",
                scenario_id="SCN_P",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )

        mgr.create_scenario("SCN_C", "Child", base_scenario_id="SCN_P")
        mgr.add_override(
            "SCN_C",
            ExplicitOverride(
                override_id="OVR_C",
                scenario_id="SCN_C",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=50.0,  # Precedence over parent's 40.0
            ),
        )

        eff = mgr.get_effective_configuration("SCN_C")
        assert eff.project_dict["infrastructure"]["track_links"][0]["max_speed_ms"] == 50.0

    def test_p12_b006_conflicting_override_detection(self) -> None:
        """P12-B006: Multiple conflicting overrides at same scenario level raise ConflictingOverrideError."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn = mgr.create_scenario("SCN_CONFLICT", "Conflict")
        # Add two conflicting overrides directly to scenario's list
        ovr1 = ExplicitOverride(
            override_id="OVR_1",
            scenario_id="SCN_CONFLICT",
            dataset_type="infrastructure",
            object_type="track_link",
            object_id="LNK_01",
            parameter_path="max_speed_ms",
            new_value=40.0,
        )
        ovr2 = ExplicitOverride(
            override_id="OVR_2",
            scenario_id="SCN_CONFLICT",
            dataset_type="infrastructure",
            object_type="track_link",
            object_id="LNK_01",
            parameter_path="max_speed_ms",
            new_value=45.0,  # Conflicting value at same level
        )
        scn.overrides = [ovr1, ovr2]

        with pytest.raises(ConflictingOverrideError):
            mgr.get_effective_configuration("SCN_CONFLICT")

    def test_p12_b007_circular_inheritance_rejection(self) -> None:
        """P12-B007: Circular scenario inheritance is detected and rejected."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        s_a = mgr.create_scenario("SCN_A", "A", base_scenario_id="BASELINE")
        s_b = mgr.create_scenario("SCN_B", "B", base_scenario_id="SCN_A")
        s_c = mgr.create_scenario("SCN_C", "C", base_scenario_id="SCN_B")

        # Induce circular cycle: A inherits C
        s_a.base_scenario_id = "SCN_C"

        with pytest.raises(CircularInheritanceError):
            mgr.get_effective_configuration("SCN_A")

    def test_p12_b008_effective_configuration_generation(self) -> None:
        """P12-B008: Effective configuration generated cleanly with metadata and isolation."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        mgr.create_scenario("SCN_TEST", "Test")
        mgr.add_override(
            "SCN_TEST",
            ExplicitOverride(
                override_id="OVR_1",
                scenario_id="SCN_TEST",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="length_m",
                new_value=1500.0,
            ),
        )

        eff = mgr.get_effective_configuration("SCN_TEST")
        assert eff.scenario_id == "SCN_TEST"
        assert eff.project_dict["infrastructure"]["track_links"][0]["length_m"] == 1500.0
        assert eff.project_dict["provenance"]["effective_scenario_id"] == "SCN_TEST"
        assert len(eff.effective_hash) == 64

    def test_p12_b009_effective_hash_stability(self) -> None:
        """P12-B009: Identical effective configuration yields identical deterministic SHA-256 hash."""
        base_proj = make_benchmark_baseline_project()
        mgr1 = ScenarioManager(base_proj)
        mgr2 = ScenarioManager(base_proj)

        h1 = mgr1.get_effective_hash("BASELINE")
        h2 = mgr2.get_effective_hash("BASELINE")
        assert h1 == h2
        assert len(h1) == 64

    def test_p12_b010_hash_change_on_override(self) -> None:
        """P12-B010: Adding or modifying an override changes the effective SHA-256 hash."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)
        h_baseline = mgr.get_effective_hash("BASELINE")

        mgr.create_scenario("SCN_VAR", "Variant")
        h_init = mgr.get_effective_hash("SCN_VAR")

        mgr.add_override(
            "SCN_VAR",
            ExplicitOverride(
                override_id="OVR_MOD",
                scenario_id="SCN_VAR",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )
        h_modified = mgr.get_effective_hash("SCN_VAR")

        assert h_modified != h_baseline
        assert h_modified != h_init

    def test_p12_b011_scenario_validation_invalid_target(self) -> None:
        """P12-B011: Override targeting non-existent object ID flags critical validation finding."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn = mgr.create_scenario("SCN_BAD_TGT", "Bad Target")
        mgr.add_override(
            "SCN_BAD_TGT",
            ExplicitOverride(
                override_id="OVR_ERR",
                scenario_id="SCN_BAD_TGT",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="NON_EXISTENT_LINK",
                parameter_path="max_speed_ms",
                new_value=30.0,
            ),
        )

        report = mgr.validate_scenario("SCN_BAD_TGT")
        assert report.has_critical
        assert any("Target object 'NON_EXISTENT_LINK' not found" in f.message for f in report.findings)
        assert report.is_simulation_ready is False

    def test_p12_b012_scenario_validation_invalid_value(self) -> None:
        """P12-B012: Override with out-of-bounds or non-finite value flags critical finding."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn = mgr.create_scenario("SCN_BAD_VAL", "Bad Value")
        mgr.add_override(
            "SCN_BAD_VAL",
            ExplicitOverride(
                override_id="OVR_ERR",
                scenario_id="SCN_BAD_VAL",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=9999.0,  # Exceeds max speed bound of 120 m/s
            ),
        )

        report = ScenarioValidator.validate_scenario(scn, mgr._baseline_dict)
        assert report.has_critical
        assert any("outside engineering bounds" in f.message for f in report.findings)

    def test_p12_b013_scenario_validation_geometry_consistency(self) -> None:
        """P12-B013: Detects invalid geometry offsets exceeding host link."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn = mgr.create_scenario("SCN_BAD_GEOM", "Bad Geometry")
        mgr.add_override(
            "SCN_BAD_GEOM",
            ExplicitOverride(
                override_id="OVR_PLAT",
                scenario_id="SCN_BAD_GEOM",
                dataset_type="infrastructure",
                object_type="platform",
                object_id="PLT_A1",
                parameter_path="end_offset_m",
                new_value=5000.0,  # Exceeds LNK_02 length of 800m
            ),
        )

        eff = mgr.get_effective_configuration("SCN_BAD_GEOM", validate=False)
        report = ScenarioValidator.validate_effective_configuration(eff)
        assert report.has_critical
        assert any("exceed host link length" in f.message for f in report.findings)

    def test_p12_b014_signalling_comparison_scenario(self) -> None:
        """P12-B014: Signalling comparison template switches signalling technology."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn_cbtc = ScenarioTemplateFactory.create_signalling_comparison_scenario(
            scenario_id="SCN_CBTC",
            scenario_name="CBTC Upgrade",
            target_technology=SignallingTechnologyType.CBTC_MOVING_BLOCK,
        )
        mgr._scenarios["SCN_CBTC"] = scn_cbtc

        eff = mgr.get_effective_configuration("SCN_CBTC")
        assert eff.scenario_id == "SCN_CBTC"
        assert eff.project_dict["signalling"]["technology_type"] == "CBTC_MOVING_BLOCK"

    def test_p12_b015_block_length_sensitivity_scenario(self) -> None:
        """P12-B015: Block sensitivity template modifies block lengths."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn_blk = ScenarioTemplateFactory.create_block_sensitivity_scenario(
            scenario_id="SCN_BLK_500",
            scenario_name="Shorter Block",
            target_link_id="LNK_01",
            new_block_length_m=500.0,
        )
        mgr._scenarios["SCN_BLK_500"] = scn_blk

        eff = mgr.get_effective_configuration("SCN_BLK_500")
        assert eff.project_dict["infrastructure"]["track_links"][0]["length_m"] == 500.0

    def test_p12_b016_tvs_per_track_scenario(self) -> None:
        """P12-B016: TVS per-track scenario modifies TVS release parameters."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn_tvs = ScenarioTemplateFactory.create_tvs_policy_scenario(
            scenario_id="SCN_TVS_PER_TRACK",
            scenario_name="TVS Per Track",
            target_tvs_id="TVS_01",
            policy_type=ScenarioType.TVS_PER_TRACK,
            release_delay_s=8.0,
        )
        mgr._scenarios["SCN_TVS_PER_TRACK"] = scn_tvs

        eff = mgr.get_effective_configuration("SCN_TVS_PER_TRACK")
        assert eff.project_dict["infrastructure"]["tvs_sections"][0]["release_delay_s"] == 8.0

    def test_p12_b017_tvs_shared_scenario(self) -> None:
        """P12-B017: TVS shared scenario template created cleanly."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn_shared = ScenarioTemplateFactory.create_tvs_policy_scenario(
            scenario_id="SCN_TVS_SHARED",
            scenario_name="TVS Shared",
            target_tvs_id="TVS_01",
            policy_type=ScenarioType.TVS_SHARED,
            release_delay_s=12.0,
        )
        mgr._scenarios["SCN_TVS_SHARED"] = scn_shared
        assert scn_shared.scenario_type == ScenarioType.TVS_SHARED

    def test_p12_b018_whole_tunnel_scenario(self) -> None:
        """P12-B018: Whole-tunnel single-train occupancy scenario template created cleanly."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn_tun = ScenarioTemplateFactory.create_tvs_policy_scenario(
            scenario_id="SCN_TUN_WHOLE",
            scenario_name="Whole Tunnel Occupancy",
            target_tvs_id="TVS_01",
            policy_type=ScenarioType.WHOLE_TUNNEL,
            release_delay_s=15.0,
        )
        mgr._scenarios["SCN_TUN_WHOLE"] = scn_tun
        assert scn_tun.scenario_type == ScenarioType.WHOLE_TUNNEL

    def test_p12_b019_stochastic_operation_scenario(self) -> None:
        """P12-B019: Stochastic operation scenario injects master seed and replication settings."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        scn_stoch = ScenarioTemplateFactory.create_stochastic_scenario(
            scenario_id="SCN_STOCH_100",
            scenario_name="Monte Carlo Study",
            master_seed=12345,
            replications=50,
        )
        mgr._scenarios["SCN_STOCH_100"] = scn_stoch

        eff = mgr.get_effective_configuration("SCN_STOCH_100")
        assert eff.project_dict["stochastic"]["master_seed"] == 12345

    def test_p12_b020_direction_override(self) -> None:
        """P12-B020: Configuring scenario running direction propagates to effective config and hash."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        h_fwd = mgr.get_effective_hash("BASELINE")
        scn_rev = mgr.create_scenario("SCN_REVERSE", "Reverse Study", running_direction=RunningDirection.REVERSE)
        h_rev = mgr.get_effective_hash("SCN_REVERSE")

        eff_rev = mgr.get_effective_configuration("SCN_REVERSE")
        assert eff_rev.running_direction == RunningDirection.REVERSE
        assert h_rev != h_fwd

    def test_p12_b021_comparison_configuration_differences(self) -> None:
        """P12-B021: Comparison engine accurately tabulates parameter differences."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        mgr.create_scenario("SCN_MOD", "Modified Scenario")
        mgr.add_override(
            "SCN_MOD",
            ExplicitOverride(
                override_id="OVR_SPEED",
                scenario_id="SCN_MOD",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
                unit="m/s",
            ),
        )

        cmp_rep = mgr.compare_scenarios("BASELINE", ["SCN_MOD"])
        assert len(cmp_rep.parameter_differences) == 1
        diff = cmp_rep.parameter_differences[0]
        assert diff.object_id == "LNK_01"
        assert diff.parameter_path == "max_speed_ms"
        assert diff.values_by_scenario["BASELINE"] == 30.0
        assert diff.values_by_scenario["SCN_MOD"] == 40.0

    def test_p12_b022_comparison_metric_differences(self) -> None:
        """P12-B022: Comparison engine computes absolute and percentage metric differences."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        # Register baseline run
        mgr.register_simulation_result(
            scenario_id="BASELINE",
            analysis_type="CAPACITY",
            metrics={"headway_s": 120.0, "capacity_tph": 30.0},
        )

        # Register modified scenario run
        mgr.create_scenario("SCN_IMPROVED", "Improved Capacity")
        mgr.register_simulation_result(
            scenario_id="SCN_IMPROVED",
            analysis_type="CAPACITY",
            metrics={"headway_s": 90.0, "capacity_tph": 40.0},
        )

        cmp_rep = mgr.compare_scenarios("BASELINE", ["SCN_IMPROVED"], analysis_type="CAPACITY")
        diffs = cmp_rep.metric_differences["SCN_IMPROVED"]
        h_diff = next(d for d in diffs if d.metric_name == "headway_s")
        c_diff = next(d for d in diffs if d.metric_name == "capacity_tph")

        assert h_diff.baseline_value == 120.0
        assert h_diff.scenario_value == 90.0
        assert h_diff.absolute_change == -30.0
        assert h_diff.percentage_change == pytest.approx(-25.0)

        assert c_diff.baseline_value == 30.0
        assert c_diff.scenario_value == 40.0
        assert c_diff.absolute_change == 10.0
        assert c_diff.percentage_change == pytest.approx(33.3333, rel=1e-3)

    def test_p12_b023_comparison_bottleneck_shift(self) -> None:
        """P12-B023: Bottleneck shift detected and reported when bottleneck resource migrates."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        mgr.register_simulation_result(
            scenario_id="BASELINE",
            analysis_type="HEADWAY",
            metrics={"bottleneck_resource_id": "BLK_LNK_01", "headway_s": 120.0},
        )

        mgr.create_scenario("SCN_STATION_BN", "Station Bottleneck")
        mgr.register_simulation_result(
            scenario_id="SCN_STATION_BN",
            analysis_type="HEADWAY",
            metrics={"bottleneck_resource_id": "PLT_A1", "headway_s": 135.0},
        )

        cmp_rep = mgr.compare_scenarios("BASELINE", ["SCN_STATION_BN"], analysis_type="HEADWAY")
        assert len(cmp_rep.bottleneck_shifts) == 1
        bn_shift = cmp_rep.bottleneck_shifts[0]
        assert bn_shift.bottleneck_migrated is True
        assert bn_shift.baseline_bottleneck_id == "BLK_LNK_01"
        assert bn_shift.comparison_bottleneck_id == "PLT_A1"

    def test_p12_b024_result_association(self) -> None:
        """P12-B024: Simulation result associated with scenario ID and effective config hash."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        run = mgr.register_simulation_result(
            scenario_id="BASELINE",
            analysis_type="HEADWAY",
            metrics={"headway_s": 115.0},
        )

        eff_hash = mgr.get_effective_hash("BASELINE")
        assert run.scenario_id == "BASELINE"
        assert run.effective_config_hash == eff_hash
        assert run.status == RunStatus.VALID

    def test_p12_b025_result_invalidation_on_configuration_change(self) -> None:
        """P12-B025: Result invalidated (marked STALE) when scenario overrides are modified."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        mgr.create_scenario("SCN_DYN", "Dynamic Scenario")
        run = mgr.register_simulation_result(
            scenario_id="SCN_DYN",
            analysis_type="CAPACITY",
            metrics={"capacity_tph": 30.0},
        )
        assert run.status == RunStatus.VALID

        # Add an override; changes effective hash and marks prior run as STALE
        mgr.add_override(
            "SCN_DYN",
            ExplicitOverride(
                override_id="OVR_SPEED",
                scenario_id="SCN_DYN",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )

        runs = mgr.get_simulation_runs("SCN_DYN")
        assert runs[0].status == RunStatus.STALE

    def test_p12_b026_no_cross_scenario_state_leakage(self) -> None:
        """P12-B026: Modifying scenario B does not alter scenario A or its hash."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        mgr.create_scenario("SCN_ALPHA", "Alpha")
        mgr.add_override(
            "SCN_ALPHA",
            ExplicitOverride(
                override_id="OVR_A",
                scenario_id="SCN_ALPHA",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=35.0,
            ),
        )
        h_alpha_orig = mgr.get_effective_hash("SCN_ALPHA")

        mgr.create_scenario("SCN_BETA", "Beta")
        mgr.add_override(
            "SCN_BETA",
            ExplicitOverride(
                override_id="OVR_B",
                scenario_id="SCN_BETA",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=50.0,
            ),
        )

        h_alpha_after = mgr.get_effective_hash("SCN_ALPHA")
        assert h_alpha_orig == h_alpha_after

    def test_p12_b027_forward_reverse_comparison(self) -> None:
        """P12-B027: Directional comparison between same scenario in FORWARD vs REVERSE."""
        base_proj = make_benchmark_baseline_project()
        mgr = ScenarioManager(base_proj)

        mgr.register_simulation_result(
            scenario_id="BASELINE",
            analysis_type="JOURNEY_TIME",
            metrics={"journey_time_s": 200.0},
        )

        mgr.create_scenario("SCN_REV", "Reverse Route", running_direction=RunningDirection.REVERSE)
        mgr.register_simulation_result(
            scenario_id="SCN_REV",
            analysis_type="JOURNEY_TIME",
            metrics={"journey_time_s": 220.0},
        )

        cmp_rep = mgr.compare_scenarios("BASELINE", ["SCN_REV"], analysis_type="JOURNEY_TIME")
        assert len(cmp_rep.direction_compatibility_notes) == 1
        assert "REVERSE" in cmp_rep.direction_compatibility_notes[0]
        assert cmp_rep.metric_differences["SCN_REV"][0].absolute_change == 20.0

    def test_p12_b028_deterministic_reproducibility(self) -> None:
        """P12-B028: Repeated loading and override application produces identical hash and outputs."""
        base_proj = make_benchmark_baseline_project()

        mgr1 = ScenarioManager(base_proj)
        mgr1.create_scenario("SCN_REP", "Reproducible")
        mgr1.add_override(
            "SCN_REP",
            ExplicitOverride(
                override_id="OVR_1",
                scenario_id="SCN_REP",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )
        h1 = mgr1.get_effective_hash("SCN_REP")

        mgr2 = ScenarioManager(base_proj)
        mgr2.create_scenario("SCN_REP", "Reproducible")
        mgr2.add_override(
            "SCN_REP",
            ExplicitOverride(
                override_id="OVR_1",
                scenario_id="SCN_REP",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=40.0,
            ),
        )
        h2 = mgr2.get_effective_hash("SCN_REP")

        assert h1 == h2
