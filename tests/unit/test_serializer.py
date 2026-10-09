"""Unit tests for JSON serialization, schema validation, and NaN rejection."""

import pytest
from headway.core.exceptions import DataValidationError
from headway.data.canonical import (
    CanonicalProject,
    InfrastructureModel,
    Node,
    NodeType,
    Track,
    TrackLink,
)
from headway.data.serializer import (
    deserialize_canonical_project,
    serialize_canonical_project,
)


@pytest.fixture
def minimal_project() -> CanonicalProject:
    return CanonicalProject(
        project_id="PRJ_MINIMAL",
        name="Minimal Test Project",
        schema_version="1.0.0",
        infrastructure=InfrastructureModel(
            dataset_id="INFRA_01",
            nodes=[Node(node_id="N1"), Node(node_id="N2")],
            tracks=[Track(track_id="T1")],
            track_links=[
                TrackLink(
                    link_id="L1",
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
def test_serialize_and_deserialize_round_trip(minimal_project: CanonicalProject):
    json_str = serialize_canonical_project(minimal_project, validate_schema=True)
    assert "PRJ_MINIMAL" in json_str

    reloaded = deserialize_canonical_project(json_str)
    assert reloaded.project_id == minimal_project.project_id
    assert len(reloaded.infrastructure.track_links) == 1
    assert reloaded.infrastructure.track_links[0].length_m == 1000.0


@pytest.mark.unit
def test_reject_nan_in_project(minimal_project: CanonicalProject):
    minimal_project.infrastructure.track_links[0].gradient_decimal = float("nan")
    with pytest.raises(DataValidationError) as exc:
        serialize_canonical_project(minimal_project, validate_schema=False)
    assert exc.value.error_code == "ERR_SER_NON_FINITE"


@pytest.mark.unit
def test_reject_inf_in_project(minimal_project: CanonicalProject):
    minimal_project.infrastructure.track_links[0].gradient_decimal = float("inf")
    with pytest.raises(DataValidationError) as exc:
        serialize_canonical_project(minimal_project, validate_schema=False)
    assert exc.value.error_code == "ERR_SER_NON_FINITE"
