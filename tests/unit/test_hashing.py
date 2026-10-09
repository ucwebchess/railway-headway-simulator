"""Unit tests for SHA-256 cryptographic hashing stability."""

from pathlib import Path
import pytest
from headway.data.canonical import (
    CanonicalProject,
    InfrastructureModel,
    Node,
    Track,
    TrackLink,
)
from headway.data.hashing import (
    calculate_canonical_hash,
    calculate_file_hash,
    calculate_scenario_hash,
)


@pytest.fixture
def sample_project() -> CanonicalProject:
    return CanonicalProject(
        project_id="PRJ_HASH_TEST",
        name="Hash Test Project",
        schema_version="1.0.0",
        infrastructure=InfrastructureModel(
            nodes=[Node(node_id="N1"), Node(node_id="N2")],
            tracks=[Track(track_id="T1")],
            track_links=[
                TrackLink(
                    link_id="L1",
                    track_id="T1",
                    start_node_id="N1",
                    end_node_id="N2",
                    length_m=1200.0,
                    max_speed_ms=35.0,
                )
            ],
        ),
    )


@pytest.mark.unit
def test_canonical_hash_stability(sample_project: CanonicalProject):
    hash_1 = calculate_canonical_hash(sample_project)
    hash_2 = calculate_canonical_hash(sample_project)
    assert hash_1 == hash_2
    assert len(hash_1) == 64  # SHA-256 hex length


@pytest.mark.unit
def test_canonical_hash_changes_on_modification(sample_project: CanonicalProject):
    hash_orig = calculate_canonical_hash(sample_project)
    sample_project.infrastructure.track_links[0].length_m = 1500.0
    hash_mod = calculate_canonical_hash(sample_project)
    assert hash_orig != hash_mod


@pytest.mark.unit
def test_scenario_hash_difference(sample_project: CanonicalProject):
    hash_sc1 = calculate_scenario_hash(sample_project, "SCN_01")
    hash_sc2 = calculate_scenario_hash(sample_project, "SCN_02")
    assert hash_sc1 != hash_sc2
