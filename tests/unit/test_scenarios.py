"""Unit tests for scenario overrides and baseline immutability."""

import pytest
from headway.core.exceptions import ConfigurationError
from headway.data.canonical import (
    CanonicalProject,
    InfrastructureModel,
    Node,
    Scenario,
    ScenarioOverride,
    Track,
    TrackLink,
)
from headway.scenarios.engine import apply_scenario_overrides


@pytest.fixture
def baseline_project() -> CanonicalProject:
    return CanonicalProject(
        project_id="PRJ_SCN_TEST",
        name="Scenario Test Project",
        schema_version="1.0.0",
        infrastructure=InfrastructureModel(
            nodes=[Node(node_id="N1"), Node(node_id="N2")],
            tracks=[Track(track_id="T1")],
            track_links=[
                TrackLink(
                    link_id="LNK_01",
                    track_id="T1",
                    start_node_id="N1",
                    end_node_id="N2",
                    length_m=1000.0,
                    max_speed_ms=30.0,
                )
            ],
        ),
    )


@pytest.mark.unit
def test_scenario_override_preserves_baseline_immutability(baseline_project: CanonicalProject):
    scenario = Scenario(
        scenario_id="SCN_SPEED_UP",
        description="Increase speed limit",
        is_baseline=False,
        overrides=[
            ScenarioOverride(
                target_domain="infrastructure",
                target_object_id="LNK_01",
                parameter_name="max_speed_ms",
                override_value=45.0,
            )
        ],
    )

    effective = apply_scenario_overrides(baseline_project, scenario)

    # Invariant: baseline is completely unchanged
    assert baseline_project.infrastructure.track_links[0].max_speed_ms == 30.0
    # Effective config reflects override
    assert effective.infrastructure.track_links[0].max_speed_ms == 45.0


@pytest.mark.unit
def test_scenario_override_invalid_target(baseline_project: CanonicalProject):
    scenario = Scenario(
        scenario_id="SCN_BAD",
        description="Target does not exist",
        is_baseline=False,
        overrides=[
            ScenarioOverride(
                target_domain="infrastructure",
                target_object_id="NON_EXISTENT_LINK",
                parameter_name="length_m",
                override_value=2000.0,
            )
        ],
    )
    with pytest.raises(ConfigurationError):
        apply_scenario_overrides(baseline_project, scenario)
