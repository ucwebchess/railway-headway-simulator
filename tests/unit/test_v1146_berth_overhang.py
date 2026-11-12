"""v1.14.6 — reverse berth rear overhang (central berth rule ``berth_front_offset``).

A train longer than its stop segment (the segment selected by ``SEGMENT_HINT_OFFSET_M``) used to
berth one segment length past the segment entry, so its rear hung off the platform by up to
``L - segment`` (u8000 AUH REVERSE: 63.08 m). v1.14.6 berths it against the parent platform end
in the direction of travel (Policy A); trains that fit keep the old rule bit-for-bit.

Geometry of tests 1-8 mirrors u8000 ``PLT_AUH`` (TRK_UP 35.509-35.709 km, 200 m):
``PLT_AUH@s1`` = LNK_1 23.92-85.00 m (61.08 m), ``PLT_AUH@s2`` = LNK_2 0-138.92 m (138.92 m),
no segment hint (mid-platform 35,609 m -> stop segment ``@s2``), train TRN_HSR 202 m.
Positions are asserted as physical track chainage (m) in BOTH running directions.

 1. FWD AUH: front 35,709, rear 35,507, overhang 2 m
 2. REV AUH: front 35,509, rear 35,711 (Policy A)
 3. overhang equals L - P in both directions
 4. a footprint outside the envelope raises ERR_PLATFORM_BERTH_OVERHANG
 5. the chart check catches a rear beyond parent end + unavoidable overhang + 1.0 m
 6. 100 m train, s2 138.92 m, FWD: front 35,670.08 (unchanged)
 7. 100 m train, s2 138.92 m, REV: front 35,609 (unchanged)
 8. L > segment: BerthFallbackWarning issued, berth at the parent end
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path
from typing import List, Tuple

import openpyxl
import pytest

from headway.data.canonical import (
    InfrastructureModel,
    Node,
    NodeType,
    PlatformSpan,
    Station,
    Track,
    TrackDirectionality,
    TrackLink,
)
from headway.data.platform_spans import segment_all_platform_spans
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.preprocessor import InfrastructurePreprocessor
from headway.infrastructure.route import RouteEngine
from headway.infrastructure.stations import (
    BerthFallbackWarning,
    BerthPosition,
    PlatformBerthOverhangError,
    RouteStopsNoTrainLengthError,
    StationPlatformModel,
    berth_front_offset,
    check_berth_containment,
    parent_platform_segments,
)
from headway.reporting.charts_alignment import (
    ChartAlignmentFrameError,
    _check_stops_on_platforms,
    chart_containment_tolerance_m,
)

FWD, REV = RunningDirection.FORWARD, RunningDirection.REVERSE
BOTH = pytest.mark.parametrize("direction", [FWD, REV], ids=["FORWARD", "REVERSE"])

# Track TRK_UP: LNK_0 0-35,485.08 m, LNK_1 35,485.08-35,570.08 m, LNK_2 35,570.08-35,809.00 m.
L0, L1, L2 = 35_485.08, 85.0, 238.92
TRACK_END_M = L0 + L1 + L2
P_START, P_END = 35_509.0, 35_709.0
P_LEN = P_END - P_START
S1_END = 35_570.08  # boundary of PLT_AUH@s1 / PLT_AUH@s2
HSR_M = 202.0


def _infra() -> InfrastructureModel:
    nodes = [Node(node_id=n, node_type=NodeType.ENDPOINT) for n in ("N0", "N1", "N2", "N3")]
    tracks = [Track(track_id="TRK_UP", directionality=TrackDirectionality.BIDIRECTIONAL)]
    links = [
        TrackLink(link_id="LNK_0", track_id="TRK_UP", start_node_id="N0", end_node_id="N1", length_m=L0, max_speed_ms=80.0),
        TrackLink(link_id="LNK_1", track_id="TRK_UP", start_node_id="N1", end_node_id="N2", length_m=L1, max_speed_ms=80.0),
        TrackLink(link_id="LNK_2", track_id="TRK_UP", start_node_id="N2", end_node_id="N3", length_m=L2, max_speed_ms=80.0),
    ]
    stations = [Station(station_id="STN_AUH", name="Abu Dhabi")]
    span = PlatformSpan(platform_id="PLT_AUH", station_id="STN_AUH", track_id="TRK_UP",
                        start_chainage_km=P_START / 1000.0, end_chainage_km=P_END / 1000.0,
                        segment_hint_offset_m=None)
    seg = segment_all_platform_spans([span], tracks, links, stations)
    return InfrastructureModel(
        nodes=nodes, tracks=tracks, track_links=links, stations=stations, platform_spans=[span],
        platforms=[p for s in seg for p in s.segments], stopping_points=[s.stopping_point for s in seg],
    )


def _route(infra: InfrastructureModel, direction: RunningDirection):
    graph = PhysicalNetworkGraph(infra)
    trav = ([("LNK_0", FWD), ("LNK_1", FWD), ("LNK_2", FWD)] if direction is FWD
            else [("LNK_2", REV), ("LNK_1", REV), ("LNK_0", REV)])
    return RouteEngine(graph).build_route_from_traversals(f"RT_{direction.value}", trav)


def _to_chainage(route_m: float, direction: RunningDirection) -> float:
    return route_m if direction is FWD else TRACK_END_M - route_m


def _auh_front_rear(direction: RunningDirection, train_m: float) -> Tuple[float, float]:
    """(front, rear) physical chainage of the AUH stop resolved by ``resolve_route_stops`` (site #3)."""
    infra = _infra()
    stops = StationPlatformModel(infra).resolve_route_stops(_route(infra, direction), train_length_m=train_m)
    stop = next(s for s in stops if s.platform.platform_id == "PLT_AUH@s2")
    s_rear, s_front, _ = stop.evaluate_train_stopping_interval(train_m)
    return _to_chainage(s_front, direction), _to_chainage(s_rear, direction)


def _berth_chainage(direction: RunningDirection, train_m: float) -> Tuple[BerthPosition, float]:
    """The central berth rule for the AUH stop segment and its physical chainage."""
    infra = _infra()
    seg = next(p for p in infra.platforms if p.platform_id == "PLT_AUH@s2")
    berth = berth_front_offset(seg, parent_platform_segments(seg, infra.platforms), train_m, direction)
    link_start = {"LNK_0": 0.0, "LNK_1": L0, "LNK_2": L0 + L1}[berth.link_id]
    return berth, link_start + berth.offset_m


def test_auh_geometry_matches_u8000():
    """Guard: the synthetic geometry reproduces u8000 PLT_AUH segmentation."""
    segs = {p.platform_id: p for p in _infra().platforms}
    assert (segs["PLT_AUH@s1"].link_id, segs["PLT_AUH@s2"].link_id) == ("LNK_1", "LNK_2")
    assert segs["PLT_AUH@s1"].start_offset_m == pytest.approx(23.92)
    assert segs["PLT_AUH@s1"].length_m == pytest.approx(61.08)
    assert segs["PLT_AUH@s2"].length_m == pytest.approx(138.92)


# ---------------------------------------------------------------------------
# 1-3: train longer than its stop segment (Policy A)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.filterwarnings("ignore::headway.infrastructure.stations.BerthFallbackWarning")
def test_01_forward_auh_front_35709_rear_35507():
    front, rear = _auh_front_rear(FWD, HSR_M)
    assert front == pytest.approx(35_709.0, abs=1e-6)
    assert rear == pytest.approx(35_507.0, abs=1e-6)
    assert P_START - rear == pytest.approx(2.0, abs=1e-6)  # overhang before the platform start
    berth, ch = _berth_chainage(FWD, HSR_M)
    assert (berth.link_id, ch) == ("LNK_2", pytest.approx(35_709.0, abs=1e-6))


@pytest.mark.unit
@pytest.mark.filterwarnings("ignore::headway.infrastructure.stations.BerthFallbackWarning")
def test_02_reverse_auh_front_35509_rear_35711_policy_a():
    front, rear = _auh_front_rear(REV, HSR_M)
    assert front == pytest.approx(35_509.0, abs=1e-6)  # was 35,570.08 (s1/s2 boundary) before v1.14.6
    assert rear == pytest.approx(35_711.0, abs=1e-6)   # was 35,772.08 (63.08 m overhang)
    # The berth lies on the s1 link (LNK_1, offset 23.92 m), not on the stop segment's link:
    # a float offset on LNK_2 would be -61.08 m and the engine clamp would snap it back to 35,570.08.
    berth, ch = _berth_chainage(REV, HSR_M)
    assert berth.link_id == "LNK_1"
    assert berth.offset_m == pytest.approx(23.92, abs=1e-6)
    assert ch == pytest.approx(35_509.0, abs=1e-6)
    assert berth.fits_segment is False


@pytest.mark.unit
@BOTH
@pytest.mark.parametrize("train_m", [HSR_M, 230.0, 260.0])
@pytest.mark.filterwarnings("ignore::headway.infrastructure.stations.BerthFallbackWarning")
def test_03_overhang_equals_L_minus_P_both_directions(direction, train_m):
    front, rear = _auh_front_rear(direction, train_m)
    lo, hi = sorted((front, rear))
    overhang = max(0.0, P_START - lo) + max(0.0, hi - P_END)
    assert overhang == pytest.approx(train_m - P_LEN, abs=1e-6)
    # ... and all of it on the entry side; the front is exactly at the exit end.
    assert front == pytest.approx(P_END if direction is FWD else P_START, abs=1e-6)


# ---------------------------------------------------------------------------
# 4-5: loud failures
# ---------------------------------------------------------------------------

@pytest.mark.unit
@BOTH
def test_04_footprint_outside_envelope_raises(direction):
    """Containment tolerance is max(0, L - P) + 1 mm (decision Q1 = a)."""
    tol = HSR_M - P_LEN + 1e-3
    check_berth_containment("PLT_AUH", P_LEN, HSR_M, P_LEN, direction)  # Policy A berth: inside
    # The allowance applies per end: a front up to `tol` past the exit end is accepted ...
    check_berth_containment("PLT_AUH", P_LEN + tol - 1e-6, HSR_M, P_LEN, direction)
    # ... beyond it the berth is rejected.
    with pytest.raises(PlatformBerthOverhangError) as exc:
        check_berth_containment("PLT_AUH", P_LEN + tol + 0.01, HSR_M, P_LEN, direction)
    assert exc.value.error_code == "ERR_PLATFORM_BERTH_OVERHANG"
    assert exc.value.context["end"] == "front"
    assert exc.value.context["direction"] == direction.value
    # Rear beyond the entry end by more than the allowance (front 1 m short of the exit end).
    with pytest.raises(PlatformBerthOverhangError) as exc:
        check_berth_containment("PLT_AUH", P_LEN - 1.0, HSR_M, P_LEN, direction)
    assert exc.value.context["end"] == "rear"
    assert exc.value.context["allowed_overhang_m"] == pytest.approx(tol)
    # A train that fits gets only the 1 mm numerical allowance.
    with pytest.raises(PlatformBerthOverhangError):
        check_berth_containment("PLT_AUH", 99.99, 100.0, P_LEN, direction)


@pytest.mark.unit
@BOTH
def test_05_chart_check_catches_rear_beyond_allowance(direction):
    """Diagram check: front AND rear against the parent extent, allowance max(0, L - P) + 1.0 m.

    Route frame: the platform covers [lo, hi] and the train front is the larger value (route
    distance increases in the direction of travel in both running directions).
    """
    lo = P_START if direction is FWD else TRACK_END_M - P_END
    hi = lo + P_LEN
    plats = [{"platform_id": "PLT_AUH", "start_m": lo, "end_m": hi}]
    tol = chart_containment_tolerance_m(HSR_M, P_LEN)
    assert tol == pytest.approx(3.0)

    def ev(front: float) -> dict:
        return {"station_id": "STN_AUH", "platform_id": "PLT_AUH", "route_chainage_km": round(front / 1000, 3),
                "front_stopping_position_m": round(front, 2), "rear_stopping_position_m": round(front - HSR_M, 2)}

    _check_stops_on_platforms(plats, [ev(hi)])          # v1.14.6 berth: rear 2 m off -> accepted
    _check_stops_on_platforms(plats, [ev(hi - 0.99)])   # rear 2.99 m off -> accepted
    with pytest.raises(ChartAlignmentFrameError) as exc:
        _check_stops_on_platforms(plats, [ev(hi - 1.02)])  # rear 3.02 m off, front inside
    assert exc.value.error_code == "ERR_CHART_ALIGNMENT_FRAME"
    assert exc.value.context["end"] == "rear"
    # The pre-v1.14.6 AUH REVERSE berth (rear 63.08 m off the platform) is now caught; the old
    # front-only check let it through because the front was on the platform.
    with pytest.raises(ChartAlignmentFrameError) as exc:
        _check_stops_on_platforms(plats, [ev(hi - 61.08)])
    assert exc.value.context["end"] == "rear"


# ---------------------------------------------------------------------------
# 6-7: trains that fit their stop segment keep the old rule (decision C4)
# ---------------------------------------------------------------------------

def _assert_no_fallback_for_stop_segment(caught) -> None:
    """No fallback for the stop segment @s2 (138.92 m >= 100 m).

    ``resolve_route_stops`` resolves every platform segment on the route, so the 61.08 m sibling
    ``@s1`` (shorter than 100 m) legitimately reports its own fallback.
    """
    msgs = [str(w.message) for w in caught if issubclass(w.category, BerthFallbackWarning)]
    assert not [m for m in msgs if "segment 2 " in m], msgs

@pytest.mark.unit
def test_06_short_train_forward_unchanged():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        front, rear = _auh_front_rear(FWD, 100.0)
        berth, ch = _berth_chainage(FWD, 100.0)
    _assert_no_fallback_for_stop_segment(caught)
    assert front == pytest.approx(35_670.08, abs=1e-6)  # s2 start + 100 m
    assert rear == pytest.approx(S1_END, abs=1e-6)
    assert (berth.link_id, berth.fits_segment) == ("LNK_2", True)
    assert ch == pytest.approx(35_670.08, abs=1e-6)


@pytest.mark.unit
def test_07_short_train_reverse_unchanged():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        front, rear = _auh_front_rear(REV, 100.0)
        berth, ch = _berth_chainage(REV, 100.0)
    _assert_no_fallback_for_stop_segment(caught)
    assert front == pytest.approx(35_609.0, abs=1e-6)  # s2 end - 100 m
    assert rear == pytest.approx(35_709.0, abs=1e-6)
    assert (berth.link_id, berth.fits_segment) == ("LNK_2", True)
    assert ch == pytest.approx(35_609.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 8: fallback warning
# ---------------------------------------------------------------------------

@pytest.mark.unit
@BOTH
def test_08_longer_than_segment_warns_and_berths_at_parent_end(direction):
    with pytest.warns(BerthFallbackWarning,
                      match=r"^Train 202\.0m exceeds segment 2 \(138\.9m\); berthing against parent platform$"):
        berth, ch = _berth_chainage(direction, HSR_M)
    assert ch == pytest.approx(P_END if direction is FWD else P_START, abs=1e-6)
    assert berth.fits_segment is False


# ---------------------------------------------------------------------------
# Supporting checks: required train length (Q4), cache key, end-to-end (sites #1, #2, #5, G2)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("bad", [None, 0.0, -5.0])
def test_train_length_required(bad):
    infra = _infra()
    route = _route(infra, FWD)
    with pytest.raises(RouteStopsNoTrainLengthError) as exc:
        StationPlatformModel(infra).resolve_route_stops(route, train_length_m=bad)
    assert exc.value.error_code == "ERR_ROUTE_STOPS_NO_TRAIN_LENGTH"
    with pytest.raises(RouteStopsNoTrainLengthError):
        InfrastructurePreprocessor(infra).preprocess_route(route, FWD, train_length_m=bad)
    with pytest.raises(RouteStopsNoTrainLengthError):
        InfrastructurePreprocessor(infra).preprocess_route(route, FWD)  # no silent default
    seg = next(p for p in infra.platforms if p.platform_id == "PLT_AUH@s2")
    with pytest.raises(RouteStopsNoTrainLengthError):
        berth_front_offset(seg, [seg], bad, FWD)


@pytest.mark.unit
@pytest.mark.filterwarnings("ignore::headway.infrastructure.stations.BerthFallbackWarning")
def test_preprocess_cache_is_keyed_by_train_length():
    infra = _infra()
    route = _route(infra, REV)
    pre = InfrastructurePreprocessor(infra)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", BerthFallbackWarning)
        long_ = pre.preprocess_route(route, REV, train_length_m=HSR_M)
    short = pre.preprocess_route(route, REV, train_length_m=100.0)
    assert long_ is not short

    def pos(prof):
        return next(s for s in prof.stations if s.platform.platform_id == "PLT_AUH@s2").stopping_position_m

    assert _to_chainage(pos(long_), REV) == pytest.approx(35_509.0, abs=1e-6)
    assert _to_chainage(pos(short), REV) == pytest.approx(35_609.0, abs=1e-6)
    assert pre.preprocess_route(route, REV, train_length_m=100.0) is short


EX06 = Path(__file__).resolve().parents[2] / "examples" / "06_multilink_blocks"


@pytest.mark.unit
@BOTH
@pytest.mark.filterwarnings("ignore::headway.infrastructure.stations.BerthFallbackWarning")
def test_end_to_end_engine_berth_occupation_and_report(direction, tmp_path):
    """Example 06, PLT_02 moved to 3.1-3.3 km (PLT_02@s1 = LNK_03 900-1000 m, PLT_02@s2 = LNK_04 0-100 m).

    The 160 m train is longer than either 100 m segment. The hint selects the segment at the
    platform ENTRY in the running direction (FWD @s1, REV @s2) — the case that used to overhang
    by 60 m. Checks the engine berth (site #1), the station stop record (site #5), the platform
    occupation window against the parent extent (site #2, G2), Section 11 parent attribution,
    and that the diagram containment check accepts the berth.
    """
    from headway.reporting.report_models import ReportSectionId
    from headway.ui.file_manager import FileManager
    from headway.ui.simulation_runner import SimulationRunner

    folder = tmp_path / "ex06"
    shutil.copytree(EX06, folder, ignore=shutil.ignore_patterns("README*", "*.md"))
    wb = openpyxl.load_workbook(folder / "01_Infrastructure.xlsx")
    for row in wb["PlatformSpans"].iter_rows(min_row=3):
        if row[0].value == "PLT_02":
            row[3].value, row[4].value = 3.1, 3.3
            row[5].value = 50.0 if direction is FWD else 150.0
    wb.save(folder / "01_Infrastructure.xlsx")
    proj, report, _ = FileManager.import_excel_files(sorted(str(p) for p in folder.glob("*.xlsx")))
    assert proj is not None, [f.message for f in report.findings if f.severity.name in ("CRITICAL", "ERROR")]
    stop_seg = "PLT_02@s1" if direction is FWD else "PLT_02@s2"
    view = SimulationRunner._project_with_stop_segments(proj)
    assert stop_seg in [st.platform_id for sp in view.operations.service_patterns for st in sp.stops]

    pkg, doc = SimulationRunner.run_simulation_pipeline(proj, running_direction=direction)
    total = 4700.0
    stop = {r.station_id: r for r in pkg.metadata["station_stops"]}["STN_02"]
    front = stop.front_stopping_position_m if direction is FWD else total - stop.front_stopping_position_m
    rear = stop.rear_stopping_position_m if direction is FWD else total - stop.rear_stopping_position_m
    # Parent platform 3,100-3,300 m; train 160 m <= 200 m: the whole train is on the platform.
    assert front == pytest.approx(3300.0 if direction is FWD else 3100.0, abs=1.0)
    assert rear == pytest.approx(3140.0 if direction is FWD else 3260.0, abs=1.0)
    assert 3100.0 - 1.0 <= min(front, rear) and max(front, rear) <= 3300.0 + 1.0

    # G2: occupation credited to the stop segment, attributed to the parent platform.
    recs = {r.platform_id: r for r in pkg.metadata["platform_records"]}
    assert not recs[stop_seg].never_occupied
    assert recs[stop_seg].parent_platform_id == "PLT_02"
    assert recs[stop_seg].dwell_end_time_s - recs[stop_seg].dwell_start_time_s == pytest.approx(30.0, abs=0.01)
    sec6 = doc.get_section(ReportSectionId.STATION_PLATFORM_OCCUPATION).tables[0].raw_dataframe
    assert sec6[sec6["Platform ID"] == "PLT_02"].iloc[0]["Passenger Dwell (s)"] > 0.0
    sec11 = doc.get_section(ReportSectionId.GEOMETRY_PROVENANCE)
    seg_tbl = next(t for t in sec11.tables if t.table_id == "TBL_PLATFORM_SEGMENT_PROVENANCE").raw_dataframe
    row = seg_tbl[seg_tbl["Segment ID"] == stop_seg].iloc[0]
    assert (row["Parent Platform"], row["Stop Segment"]) == ("PLT_02", "Yes")
