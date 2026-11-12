"""v1.14.1 — train fit is checked against the physical (parent) platform, not one segment.

A ``PlatformSpans`` row is auto-segmented into link-level platforms ``<PLATFORM_ID>@s<N>``.
The train berths on one of them (the stop segment selected by ``SEGMENT_HINT_OFFSET_M``),
but whether it *fits* is decided by ``parent_platform_length_m`` — the sum of all segment
lengths of the parent platform (``headway.infrastructure.stations``). Every check runs in
both running directions.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from headway.data.canonical import (
    CanonicalProject,
    InfrastructureModel,
    Node,
    NodeType,
    OperationsModel,
    PlatformSpan,
    ServicePattern,
    Station,
    StationStop,
    Track,
    TrackDirectionality,
    TrackLink,
)
from headway.data.platform_spans import (
    project_with_stop_segments,
    segment_all_platform_spans,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import RouteEngine
from headway.infrastructure.stations import (
    RoutePlatformStop,
    StationPlatformModel,
    TrainOverhangError,
)
from headway.signalling.platform_controller import PlatformController
from headway.signalling.resource_types import PlatformCompatibilityError
from headway.signalling.resources import ResourceController

FWD, REV = RunningDirection.FORWARD, RunningDirection.REVERSE
BOTH = pytest.mark.parametrize("direction", [FWD, REV], ids=["FORWARD", "REVERSE"])


def _project(platform_m: float, segment_m: float, hint_m: Optional[float]) -> CanonicalProject:
    """One track of two ``segment_m`` links; one physical platform covering both of them.

    The service pattern stops at the user-facing ``PLATFORM_ID`` (``PLT_P``) — as in a real
    Operations workbook; the simulation view maps it to the stop segment.
    """
    assert platform_m == pytest.approx(2 * segment_m)
    nodes = [Node(node_id=n, node_type=NodeType.ENDPOINT) for n in ("N1", "N2", "N3")]
    tracks = [Track(track_id="TRK_P", directionality=TrackDirectionality.BIDIRECTIONAL)]
    links = [
        TrackLink(link_id="L1", track_id="TRK_P", start_node_id="N1", end_node_id="N2",
                  length_m=segment_m, max_speed_ms=20.0),
        TrackLink(link_id="L2", track_id="TRK_P", start_node_id="N2", end_node_id="N3",
                  length_m=segment_m, max_speed_ms=20.0),
    ]
    stations = [Station(station_id="STN_P", name="Platform Fit Station")]
    span = PlatformSpan(platform_id="PLT_P", station_id="STN_P", track_id="TRK_P",
                        start_chainage_km=0.0, end_chainage_km=platform_m / 1000.0,
                        segment_hint_offset_m=hint_m)
    segmentation = segment_all_platform_spans([span], tracks, links, stations)
    infra = InfrastructureModel(
        nodes=nodes, tracks=tracks, track_links=links, stations=stations, platform_spans=[span],
        platforms=[p for s in segmentation for p in s.segments],
        stopping_points=[s.stopping_point for s in segmentation],
    )
    ops = OperationsModel(service_patterns=[ServicePattern(
        service_pattern_id="SP_FIT", train_type_id="TT_FIT", route_link_sequence=["L1", "L2"],
        stops=[StationStop(station_id="STN_P", platform_id="PLT_P", dwell_time_s=30.0)],
    )])
    return CanonicalProject(project_id="PRJ_FIT", name="Platform fit", infrastructure=infra, operations=ops)


def _stop_on_segment(project: CanonicalProject, direction: RunningDirection, train_length_m: float) -> RoutePlatformStop:
    """Resolve the stop the train makes, along a route in ``direction``, on its stop segment.

    v1.14.6: ``resolve_route_stops`` needs the train length (berth rule ``berth_front_offset``).
    """
    sim = project_with_stop_segments(project)
    stop_segment = sim.operations.service_patterns[0].stops[0].platform_id
    graph = PhysicalNetworkGraph(sim.infrastructure)
    traversals: List[tuple] = [("L1", FWD), ("L2", FWD)] if direction is FWD else [("L2", REV), ("L1", REV)]
    route = RouteEngine(graph).build_route_from_traversals(f"RT_{direction.value}", traversals)
    stops = StationPlatformModel(sim.infrastructure).resolve_route_stops(route, train_length_m=train_length_m)
    matches = [s for s in stops if s.platform.platform_id == stop_segment]
    assert len(matches) == 1, [s.platform.platform_id for s in stops]
    return matches[0]


def _controller(project: CanonicalProject) -> PlatformController:
    pc = PlatformController(resource_controller=ResourceController())
    pc.load_from_infrastructure(project_with_stop_segments(project).infrastructure)
    return pc


@pytest.mark.unit
@BOTH
def test_train_fits_on_parent_platform_not_just_segment(direction):
    """A 202 m train stopping on a 200 m segment of a 400 m physical platform fits."""
    project = _project(platform_m=400.0, segment_m=200.0, hint_m=300.0)
    stop = _stop_on_segment(project, direction, train_length_m=202.0)

    # The train stops on ONE segment, which alone is shorter than the train ...
    assert stop.platform.platform_id == "PLT_P@s2"
    assert stop.parent_platform_id == "PLT_P"
    assert stop.platform_length_m == pytest.approx(200.0)
    assert 202.0 > stop.platform_length_m
    # ... but the fit check uses the physical platform: sum of the parent's segment lengths.
    assert stop.parent_platform_length_m == pytest.approx(400.0)
    assert stop.is_train_accommodated(202.0) is True
    stop.check_train_fit(202.0)  # must not raise ERR_TRAIN_OVERHANG

    # The platform resource controller applies the same rule to the same segment.
    assert _controller(project).validate_platform_compatibility(
        "PLT_P@s2", train_length_m=202.0, running_direction=direction).platform_id == "PLT_P@s2"


@pytest.mark.unit
@BOTH
def test_train_does_not_fit_on_parent_platform(direction):
    """A 310 m train on a 300 m physical platform (two 150 m segments) overhangs: ERR_TRAIN_OVERHANG.

    (User decision 2026-11-06: length rule only — fit iff train length <= sum of the parent's
    segment lengths; independent of the stop segment and the running direction.)
    """
    project = _project(platform_m=300.0, segment_m=150.0, hint_m=None)  # mid-platform hint
    stop = _stop_on_segment(project, direction, train_length_m=310.0)
    assert stop.parent_platform_length_m == pytest.approx(300.0)
    assert stop.platform_length_m == pytest.approx(150.0)
    assert stop.is_train_accommodated(310.0) is False

    with pytest.raises(TrainOverhangError) as exc:
        stop.check_train_fit(310.0)
    assert exc.value.error_code == "ERR_TRAIN_OVERHANG"
    assert exc.value.context["platform_id"] == "PLT_P"
    assert exc.value.context["segment_id"] == stop.platform.platform_id
    assert exc.value.context["parent_platform_length_m"] == pytest.approx(300.0)
    assert "PLT_P" in exc.value.message and "310.0 m" in exc.value.message

    # Same verdict on every segment of the platform (not only the stop segment) ...
    for seg_id in ("PLT_P@s1", "PLT_P@s2"):
        with pytest.raises(PlatformCompatibilityError):
            _controller(project).validate_platform_compatibility(
                seg_id, train_length_m=310.0, running_direction=direction)
    # ... and a train of exactly the platform length still fits.
    stop.check_train_fit(300.0)


@pytest.mark.unit
@BOTH
def test_stopping_interval_uses_parent_platform_bounds(direction):
    """The berthed train may extend from its stop segment onto the sibling segment.

    Mirrored geometry per direction: the hint selects the segment at the platform's far end in
    the running direction; the 202 m train is longer than that 200 m segment, so (v1.14.6) it
    berths against the parent platform end and its rear lies on the other segment.
    """
    hint = 300.0 if direction is FWD else 100.0
    stop = _stop_on_segment(_project(platform_m=400.0, segment_m=200.0, hint_m=hint), direction, train_length_m=202.0)
    assert stop.platform.platform_id == ("PLT_P@s2" if direction is FWD else "PLT_P@s1")
    assert (stop.parent_route_distance_start_m, stop.parent_route_distance_end_m) == (
        pytest.approx(0.0), pytest.approx(400.0))

    s_rear, s_front, within = stop.evaluate_train_stopping_interval(202.0)
    # v1.14.6: front at the parent platform end (was 300.0 = the hint point), rear 198.0 (was 98.0)
    assert s_front == pytest.approx(400.0)
    assert s_rear == pytest.approx(198.0)
    seg_lo = min(stop.route_distance_start_m, stop.route_distance_end_m)
    assert s_rear < seg_lo  # rear is outside the stop segment, on the sibling segment
    assert within is True

    # rear before platform start (v1.14.6: 401 m with the front at 400 m; was 301 m with the front at 300 m)
    _, _, within = stop.evaluate_train_stopping_interval(401.0)
    assert within is False


@pytest.mark.unit
def test_platform_without_parent_keeps_own_length():
    """Platforms built without a PlatformSpans parent are their own physical platform."""
    from headway.data.canonical import Platform
    from headway.infrastructure.stations import parent_platform_length_m

    plat = Platform(platform_id="PLT_X", station_id="STN_P", link_id="L1",
                    start_offset_m=0.0, end_offset_m=150.0, length_m=150.0)
    assert parent_platform_length_m(plat, [plat]) == pytest.approx(150.0)
