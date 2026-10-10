"""Negative unit tests for Milestone P12 Scenario Management & Comparisons.

Validates error detection and rejection:
- Baseline immutability and protection (cannot delete, archive, rename, or directly mutate baseline)
- Circular inheritance detection (direct, multi-level, self-referential)
- Conflicting overrides detection at same scenario level
- Target object not found
- Parameter path not found / invalid dot-notation
- Out of bounds / non-finite numerical values
- Inconsistent geometry and network topology
- TVS occupancy constraint violations (> 1)
- Non-existent scenario lookup
- Scenario deletion with dependent children
"""

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
    Station,
    Track,
    TrackLink,
    TractionModelType,
    TrainType,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.scenarios.effective_config import EffectiveConfigGenerator
from headway.scenarios.scenario_manager import ScenarioManager
from headway.scenarios.scenario_models import (
    ExplicitOverride,
    OverrideAction,
    ScenarioDefinition,
    ScenarioStatus,
    ScenarioType,
)
from headway.scenarios.scenario_validation import ScenarioValidator


@pytest.fixture
def test_project() -> CanonicalProject:
    """Fixture returning a standard canonical project."""
    return CanonicalProject(
        project_id="PRJ_NEG_TEST",
        name="Negative Testing Project",
        schema_version="1.0.0",
        infrastructure=InfrastructureModel(
            nodes=[
                Node(node_id="N_01"),
                Node(node_id="N_02"),
                Node(node_id="N_03"),
            ],
            tracks=[Track(track_id="TRK_01")],
            track_links=[
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
            ],
            stations=[Station(station_id="STN_A", name="Central")],
            platforms=[
                Platform(
                    platform_id="PLT_01",
                    station_id="STN_A",
                    link_id="LNK_01",
                    start_offset_m=100.0,
                    end_offset_m=300.0,
                    length_m=200.0,
                )
            ],
            tvs_sections=[
                TVSSection(
                    tvs_id="TVS_01",
                    tunnel_id="TUN_01",
                    track_id="TRK_01",
                    link_intervals=[ResourceInterval(link_id="LNK_02", start_offset_m=0.0, end_offset_m=800.0)],
                    release_delay_s=5.0,
                    max_train_occupancy=1,
                )
            ],
        ),
        rolling_stock=RollingStockModel(
            train_types=[
                TrainType(
                    train_type_id="TT_01",
                    description="Standard Metro",
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
        ),
        signalling=SignallingModel(),
    )


class TestScenarioNegativeCases:
    """Rigorous negative unit testing suite."""

    def test_baseline_cannot_be_deleted(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        with pytest.raises(ScenarioError, match="Cannot delete the immutable baseline scenario"):
            mgr.delete_scenario("BASELINE")

    def test_baseline_cannot_be_archived(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        with pytest.raises(ScenarioError, match="Cannot archive the baseline scenario"):
            mgr.archive_scenario("BASELINE")

    def test_baseline_cannot_be_renamed(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        with pytest.raises(ScenarioError, match="Cannot rename the immutable baseline scenario"):
            mgr.rename_scenario("BASELINE", "NEW_BASELINE_NAME")

    def test_baseline_cannot_accept_overrides(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        ovr = ExplicitOverride(
            override_id="OVR_FAIL",
            scenario_id="BASELINE",
            dataset_type="infrastructure",
            object_type="track_link",
            object_id="LNK_01",
            parameter_path="max_speed_ms",
            new_value=40.0,
        )
        with pytest.raises(ScenarioError, match="Cannot add overrides to the immutable baseline scenario"):
            mgr.add_override("BASELINE", ovr)

    def test_duplicate_scenario_id_rejected(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        mgr.create_scenario("SCN_EXISTING", "Existing Scenario")
        with pytest.raises(ScenarioError, match="already exists"):
            mgr.create_scenario("SCN_EXISTING", "Duplicate Scenario")

    def test_nonexistent_scenario_lookup_raises(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        with pytest.raises(ScenarioNotFoundError, match="does not exist"):
            mgr.get_scenario("SCN_MISSING")

    def test_delete_scenario_with_dependent_children_rejected(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        mgr.create_scenario("SCN_PARENT", "Parent Scenario")
        mgr.create_scenario("SCN_CHILD", "Child Scenario", base_scenario_id="SCN_PARENT")

        with pytest.raises(ScenarioError, match="because child scenarios inherit from it"):
            mgr.delete_scenario("SCN_PARENT")

    def test_self_circular_inheritance_rejected(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_SELF", "Self Inheritance")
        scn.base_scenario_id = "SCN_SELF"

        with pytest.raises(CircularInheritanceError, match="Circular scenario inheritance detected"):
            mgr.get_effective_configuration("SCN_SELF")

    def test_direct_two_level_circular_inheritance(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        s1 = mgr.create_scenario("SCN_1", "Scenario 1")
        s2 = mgr.create_scenario("SCN_2", "Scenario 2", base_scenario_id="SCN_1")
        # Close cycle
        s1.base_scenario_id = "SCN_2"

        with pytest.raises(CircularInheritanceError, match="Circular scenario inheritance detected"):
            mgr.get_effective_configuration("SCN_1")

    def test_deep_multi_level_circular_inheritance(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        mgr.create_scenario("SCN_A", "A")
        mgr.create_scenario("SCN_B", "B", base_scenario_id="SCN_A")
        mgr.create_scenario("SCN_C", "C", base_scenario_id="SCN_B")
        mgr.create_scenario("SCN_D", "D", base_scenario_id="SCN_C")

        # Close cycle D -> A
        s_a = mgr.get_scenario("SCN_A")
        s_a.base_scenario_id = "SCN_D"

        with pytest.raises(CircularInheritanceError, match="Circular scenario inheritance detected"):
            mgr.get_effective_configuration("SCN_D")

    def test_conflicting_overrides_at_same_scenario_level(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_CONFLICT", "Conflict Level")
        ovr1 = ExplicitOverride(
            override_id="OVR_A",
            scenario_id="SCN_CONFLICT",
            dataset_type="infrastructure",
            object_type="track_link",
            object_id="LNK_01",
            parameter_path="length_m",
            new_value=1200.0,
        )
        ovr2 = ExplicitOverride(
            override_id="OVR_B",
            scenario_id="SCN_CONFLICT",
            dataset_type="infrastructure",
            object_type="track_link",
            object_id="LNK_01",
            parameter_path="length_m",
            new_value=1500.0,
        )
        scn.overrides = [ovr1, ovr2]

        with pytest.raises(ConflictingOverrideError, match="Conflicting overrides at same level"):
            mgr.get_effective_configuration("SCN_CONFLICT")

    def test_validation_reports_non_existent_target_object(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_BAD_TARGET", "Bad Target Object")
        mgr.add_override(
            "SCN_BAD_TARGET",
            ExplicitOverride(
                override_id="OVR_MISS",
                scenario_id="SCN_BAD_TARGET",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_DOES_NOT_EXIST",
                parameter_path="max_speed_ms",
                new_value=25.0,
            ),
        )

        report = mgr.validate_scenario("SCN_BAD_TARGET")
        assert report.has_critical
        assert any("Target object 'LNK_DOES_NOT_EXIST' not found" in f.message for f in report.findings)
        assert report.is_simulation_ready is False

    def test_validation_reports_non_existent_parameter_path(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_BAD_PATH", "Bad Path")
        mgr.add_override(
            "SCN_BAD_PATH",
            ExplicitOverride(
                override_id="OVR_PATH",
                scenario_id="SCN_BAD_PATH",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="non_existent_field",
                new_value=10.0,
            ),
        )

        report = mgr.validate_scenario("SCN_BAD_PATH")
        assert report.has_critical
        assert any("Parameter path 'non_existent_field' does not exist" in f.message for f in report.findings)

    def test_validation_reports_non_finite_values(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_NAN", "NaN value")
        mgr.add_override(
            "SCN_NAN",
            ExplicitOverride(
                override_id="OVR_NAN",
                scenario_id="SCN_NAN",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="length_m",
                new_value=math.nan,
            ),
        )

        report = mgr.validate_scenario("SCN_NAN")
        assert report.has_critical
        assert any("finite number" in f.message for f in report.findings)

    def test_validation_reports_out_of_bounds_values(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_BOUNDS", "Out of bounds")
        mgr.add_override(
            "SCN_BOUNDS",
            ExplicitOverride(
                override_id="OVR_SPEED_HIGH",
                scenario_id="SCN_BOUNDS",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="max_speed_ms",
                new_value=250.0,  # Exceeds max limit 120.0
            ),
        )

        report = mgr.validate_scenario("SCN_BOUNDS")
        assert report.has_critical
        assert any("outside engineering bounds" in f.message for f in report.findings)

    def test_validation_reports_negative_link_length(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_NEG_LEN", "Negative link length")
        mgr.add_override(
            "SCN_NEG_LEN",
            ExplicitOverride(
                override_id="OVR_LEN",
                scenario_id="SCN_NEG_LEN",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_01",
                parameter_path="length_m",
                new_value=-500.0,
            ),
        )

        report = mgr.validate_scenario("SCN_NEG_LEN")
        assert report.has_critical
        assert any("outside engineering bounds" in f.message for f in report.findings)

    def test_validation_reports_tvs_max_occupancy_violation(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_TVS_OCC", "TVS Max Occupancy > 1")
        mgr.add_override(
            "SCN_TVS_OCC",
            ExplicitOverride(
                override_id="OVR_OCC",
                scenario_id="SCN_TVS_OCC",
                dataset_type="infrastructure",
                object_type="tvs_section",
                object_id="TVS_01",
                parameter_path="max_train_occupancy",
                new_value=2,  # TVS single occupancy rule violation
            ),
        )

        report = mgr.validate_scenario("SCN_TVS_OCC")
        assert report.has_critical
        assert any("single-train occupancy" in f.message for f in report.findings)

    def test_validation_reports_broken_network_continuity(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_BROKEN_NET", "Broken Network")
        mgr.add_override(
            "SCN_BROKEN_NET",
            ExplicitOverride(
                override_id="OVR_START_NODE",
                scenario_id="SCN_BROKEN_NET",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="LNK_02",
                parameter_path="start_node_id",
                new_value="UNKNOWN_NODE",
            ),
        )

        eff = mgr.get_effective_configuration("SCN_BROKEN_NET", validate=False)
        report = ScenarioValidator.validate_effective_configuration(eff)
        assert report.has_critical
        assert any("references undefined start_node_id 'UNKNOWN_NODE'" in f.message for f in report.findings)

    def test_simulation_blocked_when_scenario_has_critical_findings(self, test_project: CanonicalProject) -> None:
        mgr = ScenarioManager(test_project)
        scn = mgr.create_scenario("SCN_BLOCK_EXEC", "Blocked Scenario")
        mgr.add_override(
            "SCN_BLOCK_EXEC",
            ExplicitOverride(
                override_id="OVR_ERR",
                scenario_id="SCN_BLOCK_EXEC",
                dataset_type="infrastructure",
                object_type="track_link",
                object_id="NON_EXISTENT",
                parameter_path="max_speed_ms",
                new_value=25.0,
            ),
        )

        with pytest.raises(DataValidationError, match="Target object 'NON_EXISTENT' not found"):
            mgr.get_effective_configuration("SCN_BLOCK_EXEC", validate=True)
