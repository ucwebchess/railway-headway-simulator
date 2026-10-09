"""Unit tests for canonical Pydantic engineering models."""

import pytest
from pydantic import ValidationError
from headway.data.canonical import (
    Node,
    NodeType,
    Platform,
    ResourceInterval,
    TrackLink,
    TrainType,
    TVSSection,
)


@pytest.mark.unit
def test_track_link_valid():
    link = TrackLink(
        link_id="LNK_01",
        track_id="TRK_01",
        start_node_id="ND_01",
        end_node_id="ND_02",
        length_m=1500.0,
        max_speed_ms=33.333,
        gradient_decimal=0.005,
    )
    assert link.link_id == "LNK_01"
    assert link.length_m == 1500.0


@pytest.mark.unit
def test_track_link_extra_field_rejected():
    with pytest.raises(ValidationError):
        TrackLink(
            link_id="LNK_01",
            track_id="TRK_01",
            start_node_id="ND_01",
            end_node_id="ND_02",
            length_m=1500.0,
            max_speed_ms=33.333,
            unknown_parameter=123,  # Strict extra forbidden
        )


@pytest.mark.unit
def test_resource_interval_bounds():
    with pytest.raises(ValidationError):
        # end_offset_m <= start_offset_m
        ResourceInterval(link_id="LNK_01", start_offset_m=500.0, end_offset_m=400.0)


@pytest.mark.unit
def test_tvs_section_single_occupancy_default():
    tvs = TVSSection(
        tvs_id="TVS_01",
        tunnel_id="TNL_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="LNK_01", start_offset_m=0.0, end_offset_m=1000.0)],
    )
    assert tvs.max_train_occupancy == 1  # Invariant default
