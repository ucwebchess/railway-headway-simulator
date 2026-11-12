"""v1.15.0 (#69): dispatcher entry-block selection.

The dispatcher used to reserve the first TRACK_BLOCK registered on the first route link, whatever
the running direction or the block's offset on the link. In REVERSE that is the block the train
reaches LAST on its first link (01c, 02-bidirectional, 04c), so the headway was inflated.

v1.15.0 adds ``select_entry_block(route, resources, entry_point_m, train_length_m)``, shared by the
dispatcher (``can_authorize_entry`` / ``dispatch_candidate``) and the runner's origin block:

- search the FIRST route link only (C1);
- pick the block whose entry in the direction of travel is the nearest one at or beyond the entry
  point;
- no block on the first link -> proceed without reservation and without a warning (C2);
- ``WARNING_ENTRY_GAP`` when the gap to the selected block exceeds ``max(train length, 100 m)``.
"""
from __future__ import annotations

import math
import warnings
from typing import Dict, List, Tuple

import pytest

from headway.data.canonical import ResourceInterval
from headway.infrastructure.direction import RunningDirection
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.resource_types import ResourceCategory, ResourceConflictError
from headway.signalling.resources import ManagedResource
from headway.simulation import dispatching as D
from headway.simulation.dispatching import (
    ENTRY_GAP_WARNING_M,
    WARNING_ENTRY_GAP,
    EntryGapWarning,
    OriginDepartureQueue,
    select_entry_block,
)
from headway.simulation.service_instance import ServiceType, TrainGenerator
from headway.simulation.state import OperationalState
from headway.reporting.report_models import ReportSectionId
from headway.ui.simulation_runner import SimulationRunner

from tests.corrected_variants import _load, double_track_bidirectional_up, load_corrected_variant
from tests.engineering.test_multi_train_benchmarks import make_test_route, make_test_train_params

FWD, REV = RunningDirection.FORWARD, RunningDirection.REVERSE


# ----------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------

def _block(rid: str, *intervals: Tuple[str, float, float]) -> ManagedResource:
    return ManagedResource(
        resource_id=rid,
        category=ResourceCategory.TRACK_BLOCK,
        intervals=[ResourceInterval(link_id=l, start_offset_m=a, end_offset_m=b) for l, a, b in intervals],
    )


def _resources(*blocks: ManagedResource) -> Dict[str, ManagedResource]:
    return {b.resource_id: b for b in blocks}


def _train(direction: RunningDirection, length_m: float = 200.0, link_lengths=(1000.0, 1000.0), train_id="TR_V1150"):
    route = make_test_route(link_ids=["L1", "L2"][: len(link_lengths)], link_lengths=list(link_lengths), direction=direction)
    st = ServiceType("SVC_V1150", "TT_STANDARD", make_test_train_params(length_m=length_m), route, running_direction=direction)
    return TrainGenerator.create_instance(st, train_id, 0.0)


def _synthetic_u8000_like():
    """Example 06 with no block on the first route link in either direction (like u8000).

    FORWARD starts on LNK_01, REVERSE on LNK_04. BLK_01 loses its LNK_01 interval (SIG_01 moves to
    LNK_02@0) and BLK_03 loses its LNK_04 interval (SIG_04 moves to LNK_04@0, the end of BLK_03
    in REVERSE travel). The first link then carries no block in either direction, as on the u8000
    user project, which cannot be committed.
    """
    project = _load("06_multilink_blocks")[0]
    sig = {s.signal_id: s for s in project.signalling.signals}
    blk = {b.block_id: b for b in project.signalling.blocks}
    blk["BLK_01"].link_intervals = [iv for iv in blk["BLK_01"].link_intervals if iv.link_id != "LNK_01"]
    sig["SIG_01"].link_id, sig["SIG_01"].offset_m = "LNK_02", 0.0
    blk["BLK_03"].link_intervals = [iv for iv in blk["BLK_03"].link_intervals if iv.link_id != "LNK_04"]
    sig["SIG_04"].link_id, sig["SIG_04"].offset_m = "LNK_04", 0.0
    return project


DATASETS = {
    "01c": lambda: load_corrected_variant("01_single_track")[0],
    "02_bidirectional": double_track_bidirectional_up,
    "03": lambda: _load("03_station_platform")[0],
    "04c": lambda: load_corrected_variant("04_tunnel_tvs")[0],
    "05c": lambda: load_corrected_variant("05_comprehensive_line")[0],
    "06": lambda: _load("06_multilink_blocks")[0],
    "07c": lambda: load_corrected_variant("07_hsr_140km")[0],
    "synthetic_u8000_like": _synthetic_u8000_like,
}

_RUNS: Dict[Tuple[str, RunningDirection], dict] = {}


def run(name: str, direction: RunningDirection) -> dict:
    """Run the full pipeline once per (dataset, direction). Records the TRACK_BLOCK each
    ``dispatch_candidate`` call reserved (in call order: Pass 1 leader, Pass 2 leader, Pass 2
    follower) and every EntryGapWarning raised."""
    key = (name, direction)
    if key in _RUNS:
        return _RUNS[key]
    dispatch_log: List[Tuple[str, object]] = []
    original = D.OriginDepartureQueue.dispatch_candidate

    def recording_dispatch(self, train, coordinator, current_time_s):
        res = coordinator.resource_controller.resources
        before = {rid for rid, r in res.items() if train.train_id in r.reservations}
        out = original(self, train, coordinator, current_time_s)
        new = sorted(rid for rid, r in res.items()
                     if train.train_id in r.reservations and rid not in before and r.category == ResourceCategory.TRACK_BLOCK)
        assert len(new) <= 1
        dispatch_log.append((train.train_id, new[0] if new else None))
        return out

    mp = pytest.MonkeyPatch()
    mp.setattr(D.OriginDepartureQueue, "dispatch_candidate", recording_dispatch)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            pkg, doc = SimulationRunner.run_simulation_pipeline(DATASETS[name](), running_direction=direction)
    finally:
        mp.undo()
    _RUNS[key] = {
        "pkg": pkg,
        "doc": doc,
        "headway_s": pkg.metadata["technical_minimum_headway_s"],
        "journey_s": pkg.metadata["journey_time_s"],
        "dispatch_log": dispatch_log,
        "raw_entry_gap_warnings": [str(w.message) for w in caught if issubclass(w.category, EntryGapWarning)],
        "warnings": pkg.metadata["warnings"],
        "origin_block_id": pkg.metadata["signalling_timing"]["origin_block_id"],
    }
    return _RUNS[key]


def warnings_section(doc):
    assert list(doc.sections)[0] == ReportSectionId.WARNINGS  # first section
    sec = doc.sections[ReportSectionId.WARNINGS]
    assert sec.section_id == ReportSectionId.WARNINGS
    assert sec.section_number == "0.0" and sec.title == "Warnings" and sec.is_applicable
    return sec


# ----------------------------------------------------------------------------------------------
# 1-2: nearest block, both directions
# ----------------------------------------------------------------------------------------------

def test_nearest_block_forward():
    """FORWARD, entry 0: the block with the smallest start offset on the first link, independent
    of registration order."""
    route = make_test_route(link_ids=["L1", "L2"], link_lengths=[1000.0, 1000.0], direction=FWD)
    res = _resources(_block("BLK_B", ("L1", 600.0, 1000.0), ("L2", 0.0, 500.0)),   # registered first
                     _block("BLK_A", ("L1", 50.0, 600.0)),
                     _block("BLK_C", ("L2", 500.0, 1000.0)))
    sel = select_entry_block(route, res, 0.0, 200.0)
    assert sel.block.resource_id == "BLK_A"
    assert sel.block_entry_m == pytest.approx(50.0) and sel.gap_m == pytest.approx(50.0)
    assert sel.warn_threshold_m == 200.0 and not sel.exceeded_warn_threshold


def test_nearest_block_reverse():
    """REVERSE, entry at the link end (route distance 0): the block with the largest end offset."""
    route = make_test_route(link_ids=["L1", "L2"], link_lengths=[1000.0, 1000.0], direction=REV)
    assert route.traversals[0].physical_offset_to_route_distance(1000.0) == pytest.approx(0.0)
    res = _resources(_block("BLK_LOW", ("L1", 0.0, 400.0)),                         # registered first
                     _block("BLK_HIGH", ("L1", 400.0, 950.0)))
    sel = select_entry_block(route, res, 0.0, 200.0)
    assert sel.block.resource_id == "BLK_HIGH"
    assert sel.block_entry_m == pytest.approx(50.0) and sel.gap_m == pytest.approx(50.0)
    assert not sel.exceeded_warn_threshold
    # Same layout FORWARD: the other block (direction symmetry).
    fwd = select_entry_block(make_test_route(link_ids=["L1", "L2"], link_lengths=[1000.0, 1000.0], direction=FWD), res, 0.0, 200.0)
    assert fwd.block.resource_id == "BLK_LOW" and fwd.gap_m == pytest.approx(0.0)


# ----------------------------------------------------------------------------------------------
# 3-6: the three #69 runs fixed; FORWARD unchanged
# ----------------------------------------------------------------------------------------------

def _assert_fixed(name, expected_block, expected_headway_s, previous_headway_s):
    r = run(name, REV)
    assert r["headway_s"] == pytest.approx(expected_headway_s, abs=0.5), f"{name} REVERSE (was {previous_headway_s})"
    assert [b for _, b in r["dispatch_log"]] == [expected_block] * 3
    assert r["origin_block_id"] == expected_block
    assert r["warnings"] == []


def test_wrong_block_01c_reverse_fixed():
    _assert_fixed("01c", "BLK_02", 159.0, 266.0)


def test_wrong_block_04c_reverse_fixed():
    _assert_fixed("04c", "BLK_T02", 118.0, 220.0)


def test_wrong_block_02_bidirectional_reverse_fixed():
    _assert_fixed("02_bidirectional", "BLK_U2", 87.0, 153.0)


@pytest.mark.parametrize("name, block, headway_s", [("01c", "BLK_01", 163.0), ("04c", "BLK_T01", 121.0), ("02_bidirectional", "BLK_U1", 89.0)])
def test_forward_unchanged(name, block, headway_s):
    r = run(name, FWD)
    assert r["headway_s"] == pytest.approx(headway_s, abs=0.5)
    assert [b for _, b in r["dispatch_log"]] == [block] * 3
    assert r["warnings"] == []


# ----------------------------------------------------------------------------------------------
# 7: no block on the first link (u8000-like layout)
# ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("direction, journey_s", [(FWD, 304.0), (REV, 300.0)], ids=lambda v: getattr(v, "name", str(v)))
def test_synthetic_u8000_first_link_layout(direction, journey_s):
    """No reservation at dispatch, no warning, headway unaffected: 57.0 s, as on main c68878c."""
    r = run("synthetic_u8000_like", direction)
    assert r["dispatch_log"] == [("TRN_LEADER", None), ("TRN_LEADER", None), ("TRN_FOLLOWER", None)]
    assert r["origin_block_id"] is None
    assert r["warnings"] == [] and r["raw_entry_gap_warnings"] == []
    assert r["headway_s"] == pytest.approx(57.0, abs=0.5)
    assert r["journey_s"] == pytest.approx(journey_s, abs=0.5)
    assert warnings_section(r["doc"]).narrative_paragraphs == ["No warnings."]


# ----------------------------------------------------------------------------------------------
# 8-10: WARNING_ENTRY_GAP
# ----------------------------------------------------------------------------------------------

def test_03_reverse_warns_entry_gap():
    """03 REVERSE: BLK_STN_01 is entered 750 m from the origin (> max(160, 100) m). The headway
    stays 179 s (the reservation time is out of scope, docs/issues/entry_offset_aware_reservation.md)."""
    r = run("03", REV)
    assert r["headway_s"] == pytest.approx(179.0, abs=0.5)
    assert [w["train_id"] for w in r["warnings"]] == ["TRN_LEADER", "TRN_FOLLOWER"]
    w = r["warnings"][0]
    assert (w["code"], w["block_id"], w["direction"]) == (WARNING_ENTRY_GAP, "BLK_STN_01", "REVERSE")
    assert (w["entry_point_m"], w["block_entry_m"], w["gap_m"], w["warn_threshold_m"]) == (0.0, 750.0, 750.0, 160.0)
    assert w["message"] == ("WARNING_ENTRY_GAP: Train TRN_LEADER in REVERSE entered route at 0.0 m; first block "
                            "BLK_STN_01 at 750.0 m; gap 750.0 m exceeds threshold 160.0 m.")
    sec = warnings_section(r["doc"])
    assert len(sec.tables) == 1
    df = sec.tables[0].raw_dataframe
    assert list(df.columns) == ["Code", "Train", "Direction", "Message"]
    assert df["Train"].tolist() == ["TRN_LEADER", "TRN_FOLLOWER"]
    assert set(df["Code"]) == {WARNING_ENTRY_GAP}
    # FORWARD: the block starts 100 m ahead (<= 160 m), so no warning.
    f = run("03", FWD)
    assert f["warnings"] == [] and f["headway_s"] == pytest.approx(140.0, abs=0.5)


@pytest.mark.parametrize("direction, headway_s", [(FWD, 160.0), (REV, 158.0)], ids=lambda v: getattr(v, "name", str(v)))
def test_06_no_warning(direction, headway_s):
    r = run("06", direction)
    assert r["warnings"] == [] and r["raw_entry_gap_warnings"] == []
    assert r["headway_s"] == pytest.approx(headway_s, abs=0.5)
    sec = warnings_section(r["doc"])
    assert sec.narrative_paragraphs == ["No warnings."] and sec.tables == []


@pytest.mark.parametrize("direction", [FWD, REV], ids=lambda d: d.name)
def test_train_aware_threshold(direction):
    """500 m train: threshold max(500, 100) = 500 m. A 300 m gap does not warn; a 600 m gap does."""
    route = make_test_route(link_ids=["L1", "L2"], link_lengths=[1000.0, 1000.0], direction=direction)

    def at_gap(gap):  # block whose entry in the direction of travel is `gap` m from the origin
        return _block("BLK_X", ("L1", gap, 1000.0)) if direction == FWD else _block("BLK_X", ("L1", 0.0, 1000.0 - gap))

    near = select_entry_block(route, _resources(at_gap(300.0)), 0.0, 500.0)
    far = select_entry_block(route, _resources(at_gap(600.0)), 0.0, 500.0)
    assert near.warn_threshold_m == far.warn_threshold_m == 500.0
    assert near.gap_m == pytest.approx(300.0) and not near.exceeded_warn_threshold
    assert far.gap_m == pytest.approx(600.0) and far.exceeded_warn_threshold
    # Short train: the 100 m floor applies.
    assert select_entry_block(route, _resources(at_gap(150.0)), 0.0, 50.0).warn_threshold_m == ENTRY_GAP_WARNING_M
    # The dispatcher issues EntryGapWarning for the 600 m case only: once at authorization
    # (can_authorize_entry) and once at dispatch (dispatch_candidate); one recorded entry.
    for gap, expected in ((300.0, 0), (600.0, 1)):
        train = _train(direction, length_m=500.0)
        coord = SignallingCoordinator()
        coord.resource_controller.register_resource(at_gap(gap))
        queue = OriginDepartureQueue()
        queue.enqueue(train)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert queue.process_origin_dispatches(coord, current_time_s=0.0) == [train]
        assert len([w for w in caught if issubclass(w.category, EntryGapWarning)]) == 2 * expected
        assert len(queue.entry_gap_warnings) == expected


# ----------------------------------------------------------------------------------------------
# 11: runner and dispatcher agree
# ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("direction", [FWD, REV], ids=lambda d: d.name)
@pytest.mark.parametrize("name", list(DATASETS))
def test_runner_and_dispatcher_agree_pass1(name, direction):
    """The runner's origin block equals the block the dispatcher reserved for the Pass 1 leader
    (both None when the first link has no block)."""
    r = run(name, direction)
    pass1_leader = r["dispatch_log"][0]
    assert pass1_leader[0] == "TRN_LEADER"
    assert r["origin_block_id"] == pass1_leader[1]


# ----------------------------------------------------------------------------------------------
# 12-13: dispatcher unit behaviour
# ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("direction", [FWD, REV], ids=lambda d: d.name)
def test_no_block_on_first_link_proceeds(direction):
    """C2: no block on the first link -> authorized, dispatched without reservation, no warning,
    no error."""
    train = _train(direction)
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(_block("BLK_ON_L2", ("L2", 0.0, 1000.0)))
    sel = select_entry_block(train.route, coord.resource_controller.resources, 0.0, 200.0)
    assert sel.block is None and sel.block_entry_m is None and math.isinf(sel.gap_m) and not sel.exceeded_warn_threshold
    queue = OriginDepartureQueue()
    queue.enqueue(train)
    assert queue.can_authorize_entry(train, coord, 0.0) == (True, None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert queue.process_origin_dispatches(coord, current_time_s=0.0) == [train]
    assert train.operational_state == OperationalState.RUNNING
    assert all(not r.reservations for r in coord.resource_controller.resources.values())
    assert not [w for w in caught if issubclass(w.category, EntryGapWarning)] and queue.entry_gap_warnings == []


@pytest.mark.parametrize("direction", [FWD, REV], ids=lambda d: d.name)
def test_reserve_before_state_change(direction):
    """An occupied entry block holds the train (ENTRY_BLOCK_OCCUPIED_<id>). A direct
    dispatch_candidate call raises ResourceConflictError before any state change, so the train
    is not RUNNING, still queued and has no departure time."""
    train = _train(direction)
    entry_id = "BLK_FWD_ENTRY" if direction == FWD else "BLK_REV_ENTRY"
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(_block("BLK_FWD_ENTRY", ("L1", 0.0, 500.0)))
    coord.resource_controller.register_resource(_block("BLK_REV_ENTRY", ("L1", 500.0, 1000.0)))
    coord.resource_controller.reserve_resource("BLOCKING_TRAIN", entry_id, 0.0)
    queue = OriginDepartureQueue()
    queue.enqueue(train)
    assert queue.can_authorize_entry(train, coord, 0.0) == (False, f"ENTRY_BLOCK_OCCUPIED_{entry_id}")
    assert queue.process_origin_dispatches(coord, current_time_s=0.0) == []
    with pytest.raises(ResourceConflictError):
        queue.dispatch_candidate(train, coord, 0.0)
    assert train.operational_state != OperationalState.RUNNING
    assert train.actual_departure_time_s is None
    assert train in queue.get_queued_trains()
    assert train not in queue.dispatched_trains
    assert set(coord.resource_controller.resources[entry_id].reservations) == {"BLOCKING_TRAIN"}
    # The other (non-entry) block is free and was not reserved either.
    other = "BLK_REV_ENTRY" if direction == FWD else "BLK_FWD_ENTRY"
    assert not coord.resource_controller.resources[other].reservations


# ----------------------------------------------------------------------------------------------
# 14: dedup across passes
# ----------------------------------------------------------------------------------------------

def test_warning_deduped_across_passes():
    """03 REVERSE raises EntryGapWarning at authorization and at dispatch, for three dispatches
    (Pass 1 leader, Pass 2 leader, Pass 2 follower): 6 raw warnings. metadata["warnings"] and
    Section 0.0 keep one record per (train, block, direction)."""
    r = run("03", REV)
    leader_msg = ("WARNING_ENTRY_GAP: Train TRN_LEADER in REVERSE entered route at 0.0 m; first block "
                  "BLK_STN_01 at 750.0 m; gap 750.0 m exceeds threshold 160.0 m.")
    follower_msg = leader_msg.replace("TRN_LEADER", "TRN_FOLLOWER")
    assert r["raw_entry_gap_warnings"] == [leader_msg] * 4 + [follower_msg] * 2
    keys = [(w["train_id"], w["block_id"], w["direction"]) for w in r["warnings"]]
    assert keys == [("TRN_LEADER", "BLK_STN_01", "REVERSE"), ("TRN_FOLLOWER", "BLK_STN_01", "REVERSE")]
    assert len(set(keys)) == len(keys)
    assert warnings_section(r["doc"]).tables[0].raw_dataframe["Message"].tolist() == [leader_msg, follower_msg]
