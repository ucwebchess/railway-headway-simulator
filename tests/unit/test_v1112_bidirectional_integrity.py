"""v1.11.2 — Bidirectional Simulation & Reporting Integrity Fix.

Every task is verified in FORWARD and REVERSE. Shipped example files are never
modified; synthetic variants are built in memory.
"""

from __future__ import annotations

import copy
import re
from types import SimpleNamespace

import pytest

from headway.core.exceptions import SimulationError
from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_assembly import MC_REACTIONARY_DISCLAIMER, _largest_remainder_percentages
from headway.reporting.report_models import ReportSectionId as S
from headway.signalling.block_geometry_validation import (
    ERR_BLOCK_GEOMETRY_MISMATCH,
    ERR_BLOCK_NO_EXIT_SIGNAL,
    ERR_BLOCK_OVERLAP,
    EXIT_SRC_BUFFER_STOP_EDGE,
    EXIT_SRC_EXPLICIT,
    EXIT_SRC_FALLBACK_SAME_TRACK,
    ENTRY_SRC_BLOCK_ENTRY_END,
    ENTRY_SRC_EXPLICIT,
    ENTRY_SRC_FALLBACK_SAME_TRACK,
    BlockGeometryValidationError,
    build_alignment_frame,
    validate_block_geometry,
)
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import (
    SimulationRunner,
    _compute_residual_rear_durations,
    _speed_at_route_position,
)
from tests.block_geometry_expectations import (
    BOTH_DIRECTIONS,
    assert_block_geometry_error,
    comprehensive_line_with_explicit_turnaround_exits,
    load_and_assert_pipeline_raises,
)

FWD, REV = RunningDirection.FORWARD, RunningDirection.REVERSE
DIRS = pytest.mark.parametrize("direction", BOTH_DIRECTIONS, ids=["FORWARD", "REVERSE"])


def _load(example: str):
    project, _r, _ = FileManager.load_example_project(example)
    return copy.deepcopy(project)


def _run(project, direction):
    return SimulationRunner.run_simulation_pipeline(
        project, running_direction=direction, simulation_mode="Full Integrated Suite"
    )


def _replace_block(project, block_id, **changes):
    project.signalling.blocks = [
        b.model_copy(update=changes) if b.block_id == block_id else b for b in project.signalling.blocks
    ]


def _interval(project, block_id, link_id, start, end):
    blk = next(b for b in project.signalling.blocks if b.block_id == block_id)
    iv = blk.link_intervals[0].model_copy(update={"link_id": link_id, "start_offset_m": start, "end_offset_m": end})
    return [iv]


def _add_signal(project, signal_id, link_id, offset_m):
    proto = project.signalling.signals[0]
    project.signalling.signals = list(project.signalling.signals) + [
        proto.model_copy(update={"signal_id": signal_id, "link_id": link_id, "offset_m": offset_m})
    ]


@pytest.fixture(scope="module")
def runs():
    """Clean example 06 and the in-memory 05 turnaround variant, run once per direction."""
    out = {}
    for d in BOTH_DIRECTIONS:
        out[("06", d)] = _run(_load("06_multilink_blocks"), d)
        out[("05T", d)] = _run(comprehensive_line_with_explicit_turnaround_exits(), d)
    return out


def _text(doc, sid):
    sec = doc.sections.get(sid)
    return " ".join(sec.narrative_paragraphs) if sec else ""


# ---------------------------------------------------------------------------
# Task 1 — ERR_BLOCK_GEOMETRY_MISMATCH
# ---------------------------------------------------------------------------

class TestTask1GeometryMismatch:
    @DIRS
    @pytest.mark.parametrize(
        "example, block, length, span, diff",
        [("01_single_track", "BLK_01", 1900.0, 2000.0, +100.0), ("04_tunnel_tvs", "BLK_T01", 2300.0, 2450.0, +150.0)],
    )
    def test_shipped_mismatch_raises_with_full_details(self, direction, example, block, length, span, diff):
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            _run(_load(example), direction)
        err = excinfo.value
        assert_block_geometry_error(err, example)
        msg = str(err)
        assert f"block '{block}'" in msg
        assert f"reported length {length:.1f} m" in msg
        assert f"span {span:.1f} m" in msg
        assert f"difference {diff:+.1f} m" in msg
        f = err.findings[0]
        assert (f.details["length_m"], f.details["path_span_m"], f.details["difference_m"]) == (length, span, diff)

    def test_hsr_mismatches_are_one_link_each(self):
        report = validate_block_geometry(_load("07_hsr_140km"))
        diffs = {f.details["difference_m"] for f in report.findings if f.code == ERR_BLOCK_GEOMETRY_MISMATCH}
        assert diffs == {313.0, -313.0}

    @DIRS
    def test_tolerance_is_one_metre_and_never_autocorrected(self, direction):
        # 03 BLK_STN_01: SIG_ENTRY @100 m -> SIG_DEPART @750 m (650 m span).
        ok = _load("03_station_platform")
        _replace_block(ok, "BLK_STN_01", link_intervals=_interval(ok, "BLK_STN_01", "LNK_STN_01", 100.0, 749.1))
        assert validate_block_geometry(ok).ok  # 0.9 m: within tolerance
        _run(ok, direction)

        bad = _load("03_station_platform")
        _replace_block(bad, "BLK_STN_01", link_intervals=_interval(bad, "BLK_STN_01", "LNK_STN_01", 100.0, 748.5))
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            _run(bad, direction)
        assert excinfo.value.error_code == ERR_BLOCK_GEOMETRY_MISMATCH
        assert "difference +1.5 m" in str(excinfo.value)
        # the input model is untouched (no auto-correction)
        blk = bad.signalling.blocks[0]
        assert blk.link_intervals[0].end_offset_m == 748.5


# ---------------------------------------------------------------------------
# Task 2 — track-aware exit-signal fallback / ERR_BLOCK_NO_EXIT_SIGNAL
# ---------------------------------------------------------------------------

class TestTask2ExitFallback:
    @DIRS
    def test_05_never_borrows_a_signal_from_the_other_line(self, direction):
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            _run(_load("05_comprehensive_line"), direction)
        err = excinfo.value
        assert_block_geometry_error(err, "05_comprehensive_line")
        msgs = {f.block_id: f.message for f in err.findings}
        assert "track(s) ['TRK_UP']" in msgs["BLK_UP_10"] and "SIG_DN_01" not in msgs["BLK_UP_10"]
        assert "track(s) ['TRK_DN']" in msgs["BLK_DN_07"] and "SIG_UP_03" not in msgs["BLK_DN_07"]
        assert all("never used as a fallback" in m for m in msgs.values())

    def test_07_terminal_block_resolves_to_buffer_stop_and_091_raises(self):
        report = validate_block_geometry(_load("07_hsr_140km"))
        ex = report.exit_boundaries["BLK_UP_092"]
        assert (ex.boundary_id, ex.source, ex.alignment_km) == ("ND_0448", EXIT_SRC_BUFFER_STOP_EDGE, pytest.approx(140.0))
        assert {f.block_id for f in report.findings if f.code == ERR_BLOCK_NO_EXIT_SIGNAL} == {"BLK_UP_091"}

    @DIRS
    def test_same_track_fallback_is_used_and_published(self, direction):
        p = _load("02_double_track")
        _replace_block(p, "BLK_U2", exit_signal_id=None)
        report = validate_block_geometry(p)
        assert report.ok
        assert (report.exit_boundaries["BLK_U2"].boundary_id, report.exit_boundaries["BLK_U2"].source) == (
            "SIG_U3", EXIT_SRC_FALLBACK_SAME_TRACK)
        pkg, _doc = _run(p, direction)
        prov = {r.resource_id: r for r in pkg.metadata["provenance_records"]}
        assert prov["BLK_U2"].exit_signal_id == "SIG_U3"

    @DIRS
    def test_other_track_signal_at_exit_raises(self, direction):
        # Only candidate near BLK_U2's exit is on TRK_DN: v1.11.1 would have used it.
        p = _load("02_double_track")
        _replace_block(p, "BLK_U2", exit_signal_id=None)
        p.signalling.signals = [s for s in p.signalling.signals if s.signal_id != "SIG_U3"]
        _add_signal(p, "SIG_DX", "LNK_DN_01", 2900.0)
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            _run(p, direction)
        assert excinfo.value.error_code == ERR_BLOCK_NO_EXIT_SIGNAL
        assert [f.block_id for f in excinfo.value.findings] == ["BLK_U2"]
        assert "SIG_DX" not in str(excinfo.value)

    @DIRS
    def test_true_terminal_resolves_to_buffer_stop_edge(self, direction):
        p = _load("02_double_track")
        p.signalling.signals = [s for s in p.signalling.signals if s.signal_id != "SIG_U3"]
        _replace_block(p, "BLK_U2", exit_signal_id=None,
                       link_intervals=_interval(p, "BLK_U2", "LNK_UP_01", 1500.0, 3000.0))
        report = validate_block_geometry(p)
        assert report.ok
        assert (report.exit_boundaries["BLK_U2"].boundary_id, report.exit_boundaries["BLK_U2"].source) == (
            "ND_U2", EXIT_SRC_BUFFER_STOP_EDGE)
        pkg, _doc = _run(p, direction)
        prov = {r.resource_id: r for r in pkg.metadata["provenance_records"]}
        assert (prov["BLK_U2"].exit_signal_id, prov["BLK_U2"].exit_signal_chainage_source) == ("ND_U2", "BUFFER_STOP_EDGE")

    @DIRS
    def test_unknown_explicit_exit_id_raises(self, direction):
        p = _load("03_station_platform")
        _replace_block(p, "BLK_STN_01", exit_signal_id="SIG_DOES_NOT_EXIST")
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            _run(p, direction)
        assert excinfo.value.error_code == ERR_BLOCK_NO_EXIT_SIGNAL
        assert "'SIG_DOES_NOT_EXIST' does not exist" in str(excinfo.value)


class TestEntryFallbackTrackAware:
    """Missing entry signals: validation and Section 11 provenance share ONE track-aware
    resolver (explicit -> nearest same-track signal within 0.5 km of the block's entry end in
    its direction of travel -> the block's own entry end). v1.11.2-pre: validation measured
    from the block entry end while provenance borrowed the nearest signal on ANY track at the
    block's LOW-chainage end, so a signal-less 05 gave 15 false +50 m mismatches and DN blocks
    were resolved at the wrong end."""

    @staticmethod
    def _prov(pkg):
        return {r.resource_id: r for r in pkg.metadata["provenance_records"]}

    @DIRS
    def test_same_track_entry_fallback_used_and_published(self, direction):
        p = _load("02_double_track")
        _replace_block(p, "BLK_U2", entry_signal_id=None)
        # An other-track signal at distance 0 that wins the id tie-break if tracks were ignored.
        _add_signal(p, "SIG_DX", "LNK_DN_01", 1500.0)
        report = validate_block_geometry(p)
        assert report.ok
        e = report.entry_boundaries["BLK_U2"]
        assert (e.boundary_id, e.source, e.alignment_km) == ("SIG_U2", ENTRY_SRC_FALLBACK_SAME_TRACK, pytest.approx(1.5))
        pkg, _doc = _run(p, direction)
        r = self._prov(pkg)["BLK_U2"]
        assert (r.entry_signal_id, r.entry_signal_chainage_km) == ("SIG_U2", pytest.approx(1.5))

    @DIRS
    def test_other_track_signal_is_never_borrowed_for_entry(self, direction):
        p = _load("02_double_track")
        _replace_block(p, "BLK_U1", entry_signal_id=None)
        p.signalling.signals = [s for s in p.signalling.signals if s.signal_id != "SIG_U1"]
        _add_signal(p, "SIG_DX", "LNK_DN_01", 100.0)
        report = validate_block_geometry(p)
        assert report.ok  # measured from the block's own entry end: 0.1 -> 1.5 km = 1400 m
        e = report.entry_boundaries["BLK_U1"]
        assert (e.boundary_id, e.source, e.alignment_km) == (None, ENTRY_SRC_BLOCK_ENTRY_END, pytest.approx(0.1))
        pkg, _doc = _run(p, direction)
        r = self._prov(pkg)["BLK_U1"]
        assert (r.entry_signal_id, r.entry_signal_chainage_km, r.entry_signal_chainage_source) == (
            "N/A", pytest.approx(0.1), "BLOCK_ENTRY_END")

    @DIRS
    def test_block_against_chainage_resolves_entry_at_its_high_end(self, direction):
        # BLK_DN_03 runs 22.0 -> 17.0 km. Its entry is SIG_DN_03 @ 21.95, not the low-end
        # candidates SIG_DN_04 @ 16.95 / SIG_UP_08 @ 17.05 that v1.11.1 provenance looked at.
        p = comprehensive_line_with_explicit_turnaround_exits()
        _replace_block(p, "BLK_DN_03", entry_signal_id=None, exit_signal_id=None)
        report = validate_block_geometry(p)
        assert report.ok
        e, x = report.entry_boundaries["BLK_DN_03"], report.exit_boundaries["BLK_DN_03"]
        assert (e.boundary_id, e.source, e.alignment_km) == ("SIG_DN_03", ENTRY_SRC_FALLBACK_SAME_TRACK, pytest.approx(21.95))
        assert (x.boundary_id, x.source) == ("SIG_DN_04", EXIT_SRC_FALLBACK_SAME_TRACK)
        pkg, _doc = _run(p, direction)
        r = self._prov(pkg)["BLK_DN_03"]
        assert (r.entry_signal_id, r.exit_signal_id) == ("SIG_DN_03", "SIG_DN_04")
        assert abs(r.entry_signal_chainage_km - r.exit_signal_chainage_km) * 1000.0 == pytest.approx(r.resource_length_m, abs=1.0)

    def test_block_against_chainage_without_entry_signal_uses_its_high_end(self):
        # Validation is a property of the input model (direction-independent by construction).
        p = comprehensive_line_with_explicit_turnaround_exits()
        _replace_block(p, "BLK_DN_03", entry_signal_id=None)
        p.signalling.signals = [s for s in p.signalling.signals if s.signal_id != "SIG_DN_03"]
        report = validate_block_geometry(p)
        e = report.entry_boundaries["BLK_DN_03"]
        # No same-track signal within 0.5 km of the entry end -> the block's own entry end,
        # which for a block running against chainage is its HIGH end (22.0 km, not 17.0).
        assert (e.boundary_id, e.source, e.alignment_km) == (None, ENTRY_SRC_BLOCK_ENTRY_END, pytest.approx(22.0))
        span = report.spans["BLK_DN_03"]
        assert span["entry_point"] == ("LNK_13", 0.0) and span["exit_boundary"] == "SIG_DN_04"
        # 05 places every signal 50 m past its block boundary, so block-entry-end -> exit
        # signal is 22.0 -> 16.95 km = 5050 m vs 5000 m: reported, never auto-corrected.
        # (Measured from the low end, v1.11.2-pre would have produced 50 m.)
        codes = {(f.code, f.block_id) for f in report.findings}
        assert span["path_span_m"] == pytest.approx(5050.0)
        assert codes == {(ERR_BLOCK_GEOMETRY_MISMATCH, "BLK_DN_03"),
                         # BLK_DN_02's explicit exit SIG_DN_03 no longer exists -> loud.
                         (ERR_BLOCK_NO_EXIT_SIGNAL, "BLK_DN_02")}

    @DIRS
    def test_all_signal_ids_stripped_05_raises_only_the_three_unresolvable_exits(self, direction):
        # Identical outcome on the shipped file and on the turnaround variant: only the blocks
        # whose exit lies on another track (2 turnarounds + the siding) raise; no span
        # mismatch is produced by the entry fallback.
        for p in (_load("05_comprehensive_line"), comprehensive_line_with_explicit_turnaround_exits()):
            for b in p.signalling.blocks:
                _replace_block(p, b.block_id, entry_signal_id=None, exit_signal_id=None)
            with pytest.raises(BlockGeometryValidationError) as excinfo:
                _run(p, direction)
            assert excinfo.value.error_code == ERR_BLOCK_NO_EXIT_SIGNAL
            assert sorted((f.code, f.block_id) for f in excinfo.value.findings) == [
                (ERR_BLOCK_NO_EXIT_SIGNAL, "BLK_DN_07"),
                (ERR_BLOCK_NO_EXIT_SIGNAL, "BLK_SD_01"),
                (ERR_BLOCK_NO_EXIT_SIGNAL, "BLK_UP_10"),
            ]

    @DIRS
    def test_unknown_explicit_entry_id_raises(self, direction):
        p = _load("03_station_platform")
        _replace_block(p, "BLK_STN_01", entry_signal_id="SIG_DOES_NOT_EXIST")
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            _run(p, direction)
        assert excinfo.value.error_code == ERR_BLOCK_GEOMETRY_MISMATCH
        assert "explicit entry signal 'SIG_DOES_NOT_EXIST' does not exist" in str(excinfo.value)

    def test_explicit_entries_unchanged_on_clean_examples(self):
        for ex in ("02_double_track", "03_station_platform", "06_multilink_blocks"):
            p = _load(ex)
            report = validate_block_geometry(p)
            assert report.ok
            for b in p.signalling.blocks:
                if b.entry_signal_id:
                    e = report.entry_boundaries[b.block_id]
                    assert (e.boundary_id, e.source) == (b.entry_signal_id, ENTRY_SRC_EXPLICIT)


# ---------------------------------------------------------------------------
# Task 3 — turnaround validator uses along-track path distance
# ---------------------------------------------------------------------------

class TestTask3Turnaround:
    def test_turnaround_spans_are_path_not_chainage(self):
        report = validate_block_geometry(comprehensive_line_with_explicit_turnaround_exits())
        assert report.ok, [f.message for f in report.findings]
        up10, dn07 = report.spans["BLK_UP_10"], report.spans["BLK_DN_07"]
        assert (up10["path_span_m"], up10["chainage_delta_m"], up10["length_m"], up10["turnaround"]) == (
            1000.0, 900.0, 1000.0, True)
        assert up10["path_links"] == ["LNK_10", "LNK_11"]
        assert (dn07["path_span_m"], dn07["chainage_delta_m"], dn07["length_m"], dn07["turnaround"]) == (
            4000.0, 3900.0, 4000.0, True)
        assert report.exit_boundaries["BLK_UP_10"].source == EXIT_SRC_EXPLICIT

    @DIRS
    def test_turnaround_blocks_pass_in_full_runs(self, runs, direction):
        pkg, _doc = runs[("05T", direction)]
        prov = {r.resource_id: r for r in pkg.metadata["provenance_records"]}
        assert prov["BLK_UP_10"].exit_signal_id == "SIG_DN_01"
        assert prov["BLK_DN_07"].exit_signal_id == "SIG_UP_01"
        ids = {i.resource_id for i in pkg.blocking_intervals}
        assert {"BLK_UP_10", "BLK_DN_07"} <= ids

    def test_chainage_only_check_would_have_failed(self):
        # Guard: the same block judged by chainage delta would be a 100 m mismatch.
        report = validate_block_geometry(comprehensive_line_with_explicit_turnaround_exits())
        up10 = report.spans["BLK_UP_10"]
        assert abs(up10["chainage_delta_m"] - up10["length_m"]) == 100.0


# ---------------------------------------------------------------------------
# Task 4 — boundary speed continuity
# ---------------------------------------------------------------------------

class TestTask4SpeedContinuity:
    def test_speed_sampled_by_position_first_crossing(self):
        d = [0.0, 10.0, 20.0, 20.0, 30.0]
        v = [0.0, 36.0, 72.0, 0.0, 36.0]
        assert _speed_at_route_position(15.0, d, v) == pytest.approx(54.0)
        assert _speed_at_route_position(20.0, d, v) == pytest.approx(72.0)  # first crossing, not the later stop
        assert _speed_at_route_position(0.0, d, v) == 0.0
        assert _speed_at_route_position(31.0, d, v) is None
        assert _speed_at_route_position(None, d, v) is None

    @DIRS
    @pytest.mark.parametrize("case", ["06", "05T"])
    def test_no_discontinuity_at_any_contiguous_boundary(self, runs, case, direction):
        pkg, _doc = runs[(case, direction)]
        ivs = sorted(pkg.blocking_intervals, key=lambda i: i.physical_start_offset_m)
        pairs = [(a, b) for a, b in zip(ivs, ivs[1:]) if abs(a.physical_end_offset_m - b.physical_start_offset_m) < 1e-6]
        assert len(pairs) == len(ivs) - 1  # all blocks contiguous
        bad = [(a.resource_id, b.resource_id, a.decomposition.v_out_kmh, b.decomposition.v_in_kmh)
               for a, b in pairs if abs(a.decomposition.v_out_kmh - b.decomposition.v_in_kmh) > 0.1]
        assert bad == []

    @DIRS
    def test_01_gap_defect_is_now_caught_before_sampling(self, direction):
        # v1.11.1's only discontinuity (01 BLK_01->BLK_02, 1.27 km/h) came from the 100 m
        # gap that Task 1 now rejects.
        load_and_assert_pipeline_raises("01_single_track", directions=(direction,))


# ---------------------------------------------------------------------------
# Task 5 — ERR_BLOCK_OVERLAP
# ---------------------------------------------------------------------------

class TestTask5Overlap:
    @staticmethod
    def _overlapping_02():
        # BLK_U1 [100, 1500]; BLK_U2 re-signalled to start at an in-memory signal at
        # 1300 m -> [1300, 2900]: both blocks are self-consistent, 200 m overlap.
        p = _load("02_double_track")
        _add_signal(p, "SIG_UX", "LNK_UP_01", 1300.0)
        _replace_block(p, "BLK_U2", entry_signal_id="SIG_UX",
                       link_intervals=_interval(p, "BLK_U2", "LNK_UP_01", 1300.0, 2900.0))
        return p

    @DIRS
    def test_overlap_raises_with_distance_and_both_ids(self, direction):
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            _run(self._overlapping_02(), direction)
        err = excinfo.value
        assert err.error_code == ERR_BLOCK_OVERLAP
        assert len(err.findings) == 1
        f = err.findings[0]
        assert f.details["block_ids"] == ["BLK_U1", "BLK_U2"]
        assert f.details["overlap_m"] == 200.0
        assert "blocks 'BLK_U1' and 'BLK_U2' overlap by 200.0 m" in str(err)

    def test_overlap_findings_identical_in_both_directions(self):
        msgs = {}
        for d in BOTH_DIRECTIONS:
            with pytest.raises(BlockGeometryValidationError) as excinfo:
                _run(self._overlapping_02(), d)
            msgs[d] = [x.message for x in excinfo.value.findings]
        assert msgs[FWD] == msgs[REV]

    def test_no_shipped_example_overlaps(self):
        for ex in ("01_single_track", "02_double_track", "03_station_platform", "04_tunnel_tvs",
                   "05_comprehensive_line", "06_multilink_blocks", "07_hsr_140km"):
            assert not [f for f in validate_block_geometry(_load(ex)).findings if f.code == ERR_BLOCK_OVERLAP], ex


# ---------------------------------------------------------------------------
# Task 6 — residual-rear attribution by physical footprint (FWD + REV)
# ---------------------------------------------------------------------------

def _samples(points):
    return [SimpleNamespace(time_s=t, front_distance_m=d, speed_ms=v) for t, d, v in points]


def _straddle_case(direction):
    """Train L=200 m stops with its front 100 m past the A|B boundary (tail 100 m in A).

    FORWARD geometry (forward axis): A = [0, 1000], B = [1000, 2000].
    REVERSE geometry (forward axis): A = [1000, 2000], B = [0, 1000]; the train travels
    towards decreasing chainage, so A is the upstream block. The helper receives
    run-origin coordinates (s_run = 2000 − s_fwd), exactly as the runner provides them.
    """
    L = 200.0
    if direction == FWD:
        a_end_run = 1000.0
        stop_run = 1100.0
    else:
        a_fwd = (1000.0, 2000.0)
        a_end_run = 2000.0 - a_fwd[0]     # 1000: A ends where B starts, in run coordinates
        stop_fwd = 900.0                  # front 100 m into B in the forward axis
        stop_run = 2000.0 - stop_fwd      # 1100
    traj = _samples([
        (0.0, 0.0, 20.0), (50.0, a_end_run, 20.0), (55.0, stop_run, 0.0),
        (115.0, stop_run, 0.0), (125.0, stop_run + 150.0, 15.0), (130.0, 2000.0, 20.0),
    ])
    recs = [
        SimpleNamespace(resource_id="A", front_exit_s=50.0, rear_clearance_s=118.0),
        SimpleNamespace(resource_id="B", front_exit_s=130.0, rear_clearance_s=140.0),
    ]
    return traj, recs, {"A": a_end_run, "B": 2000.0}, L


class TestTask6ResidualRear:
    @DIRS
    def test_straddling_stop_attributed_to_upstream_block_only(self, direction):
        traj, recs, ends, L = _straddle_case(direction)
        out = _compute_residual_rear_durations(recs, [(55.0, 115.0)], traj, L, ends)
        assert out == {"A": 60.0}  # tail inside A for the full 60 s dwell; nothing to B

    @DIRS
    def test_tail_already_clear_contributes_zero(self, direction):
        traj, recs, ends, L = _straddle_case(direction)
        far = [SimpleNamespace(time_s=s.time_s, front_distance_m=s.front_distance_m + 300.0 if 55 <= s.time_s <= 115 else s.front_distance_m,
                               speed_ms=s.speed_ms) for s in traj]
        out = _compute_residual_rear_durations(recs, [(55.0, 115.0)], far, L, ends)
        assert "A" not in out

    def test_forward_axis_reverse_samples_are_rejected(self):
        traj = _samples([(0.0, 2000.0, 20.0), (10.0, 1800.0, 20.0)])
        recs = [SimpleNamespace(resource_id="A", front_exit_s=1.0, rear_clearance_s=5.0)]
        with pytest.raises(SimulationError) as excinfo:
            _compute_residual_rear_durations(recs, [(2.0, 4.0)], traj, 200.0, {"A": 1000.0})
        assert excinfo.value.error_code == "ERR_RESIDUAL_COORDINATE_FRAME"

    @DIRS
    def test_exported_trajectory_tail_is_behind_the_train(self, runs, direction):
        pkg, _doc = runs[("06", direction)]
        L = 160.0
        for s in pkg.trajectories["TRN_LEADER"].samples:
            gap = (s.front_distance_m - s.rear_distance_m) if direction == FWD else (s.rear_distance_m - s.front_distance_m)
            assert gap == pytest.approx(L, abs=0.05)

    @DIRS
    def test_station_stop_footprint_is_route_relative_and_inside_the_route(self, runs, direction):
        pkg, _doc = runs[("06", direction)]
        total = 4700.0
        for rec in pkg.metadata["station_stops"]:
            assert rec.front_stopping_position_m - rec.rear_stopping_position_m == pytest.approx(160.0, abs=0.05)
            assert 0.0 <= rec.rear_stopping_position_m < rec.front_stopping_position_m <= total
            assert rec.route_chainage_km == pytest.approx(rec.front_stopping_position_m / 1000.0, abs=1e-3)
        if direction == REV:
            stn02 = next(r for r in pkg.metadata["station_stops"] if r.station_id == "STN_02")
            assert (stn02.rear_stopping_position_m, stn02.front_stopping_position_m) == (200.0, 360.0)  # v1.11.1: (−20, 140)

    @DIRS
    @pytest.mark.parametrize("case", ["06", "05T"])
    def test_residual_rear_matches_physical_footprint(self, runs, case, direction):
        """Every stop footprint lies within one block in these models -> zero residual rear."""
        pkg, _doc = runs[(case, direction)]
        ivs = list(pkg.blocking_intervals)
        for rec in pkg.metadata["station_stops"]:
            foot = (rec.rear_stopping_position_m, rec.front_stopping_position_m)
            owners = [i.resource_id for i in ivs
                      if min(foot[1], i.physical_end_offset_m) - max(foot[0], i.physical_start_offset_m) > 0.5]
            assert len(owners) == 1, (rec.station_id, foot, owners)
        assert all((i.decomposition.residual_rear_time_s or 0.0) == 0.0 for i in ivs)


# ---------------------------------------------------------------------------
# Tasks 7–11 — reporting
# ---------------------------------------------------------------------------

class TestTask7Section3:
    def test_largest_remainder_sums_to_exactly_100(self):
        for vals in ([1, 1, 1], [3.0, 10.0, 47.0, 0.0], [17.0, 120.0, 13.0, 90.0], [0.0, 0.0, 0.0, 0.0], [250.0]):
            pcts = _largest_remainder_percentages(vals, decimals=1)
            assert round(sum(pcts), 6) in (100.0, 0.0)
            assert all(round(p * 10) == p * 10 for p in pcts)

    @DIRS
    def test_no_baseline_claim_and_shares_sum_to_100(self, runs, direction):
        _pkg, doc = runs[("06", direction)]
        t3 = _text(doc, S.SEVEN_COMPONENT_BREAKDOWN)
        assert "baseline headway" not in t3
        m = re.search(r"Fixed Overhead ([\d.]+)%, Position-Dependent Running ([\d.]+)%, "
                      r"Geometric Clearance ([\d.]+)%, Passenger Dwell ([\d.]+)% \(Σ = 100\.0%\)", t3)
        assert m, t3
        assert round(sum(float(x) for x in m.groups()), 6) == 100.0
        t18 = _text(doc, S.CONCLUSIONS_RECOMMENDATIONS)
        assert f"({m.group(1)}%)" in t18 and f"({m.group(2)}%)" in t18  # Section 18 publishes the same shares


class TestTask8Section4:
    @DIRS
    def test_conflict_columns(self, runs, direction):
        _pkg, doc = runs[("06", direction)]
        cols = list(doc.sections[S.CONFLICT_RANKING].tables[0].raw_dataframe.columns)
        assert "Route-Relative Location (m)" in cols and "Alignment Chainage (km)" in cols
        assert "Physical Location (m)" not in cols


class TestTask9Section5:
    @DIRS
    @pytest.mark.parametrize("case", ["06", "05T"])
    def test_section5_and_section10_lengths_identical(self, runs, case, direction):
        _pkg, doc = runs[(case, direction)]
        df5 = doc.sections[S.LONGEST_OCCUPATIONS].tables[0].raw_dataframe
        df10 = doc.sections[S.DETAILED_RESOURCE_TIMING].tables[0].raw_dataframe
        len10 = dict(zip(df10["Resource ID"], df10["Length (m)"]))
        for rid, km in zip(df5["Resource ID"], df5["Block Length (km)"]):
            assert km * 1000.0 == pytest.approx(len10[rid], abs=0.1), rid
        for rid, lm in re.findall(r"Resource '([^']+)' \(chainage km [-\d.]+, length (\d+) m\)",
                                  _text(doc, S.LONGEST_OCCUPATIONS)):
            assert float(lm) == pytest.approx(len10[rid], abs=0.5), rid

    def test_turnaround_block_length_is_path_length(self, runs):
        for d in BOTH_DIRECTIONS:
            _pkg, doc = runs[("05T", d)]
            df10 = doc.sections[S.DETAILED_RESOURCE_TIMING].tables[0].raw_dataframe
            assert dict(zip(df10["Resource ID"], df10["Length (m)"]))["BLK_UP_10"] == pytest.approx(1000.0)


class TestTask10Conventions:
    @DIRS
    def test_section10_defines_both_conventions_and_reverse_footnote(self, runs, direction):
        _pkg, doc = runs[("06", direction)]
        t10 = _text(doc, S.DETAILED_RESOURCE_TIMING)
        assert "'Route-Relative Chainage'" in t10 and "'Alignment Chainage'" in t10
        if direction == REV:
            assert "Note (REVERSE run): route-relative distance is measured from the REVERSE route origin" in t10
            assert "alignment chainage decreases in the direction of travel" in t10
        else:
            assert "Note (FORWARD run)" in t10 and "REVERSE route origin" not in t10

    @DIRS
    def test_section18_location_is_labelled(self, runs, direction):
        _pkg, doc = runs[("05T", direction)]
        t18 = _text(doc, S.CONCLUSIONS_RECOMMENDATIONS)
        assert "located at chainage" not in t18
        m = re.search(r"located at alignment chainage ([\d.]+) km \(route-relative ([\d.]+) km\)", t18)
        assert m, t18
        if direction == REV:
            # 05 REV bottleneck BLK_DN_05: alignment 10.0 km, route-relative 12.00 km
            assert (float(m.group(1)), float(m.group(2))) == (10.0, 12.0)


class TestTask11MonteCarlo:
    @DIRS
    def test_stats_only_with_exact_disclaimer(self, runs, direction):
        _pkg, doc = runs[("06", direction)]
        t15 = _text(doc, S.STOCHASTIC_RELIABILITY)
        assert MC_REACTIONARY_DISCLAIMER == (
            "Reactionary delay propagation under mixed traffic is not evaluated and requires a multi-train simulation."
        )
        assert MC_REACTIONARY_DISCLAIMER in t15
        assert "robust" not in t15.lower()
        assert "minimal risk" not in t15.lower()
        t18 = _text(doc, S.CONCLUSIONS_RECOMMENDATIONS)
        assert "robust" not in t18.lower()
        recs = doc.sections[S.CONCLUSIONS_RECOMMENDATIONS]
        all_text = " ".join(recs.narrative_paragraphs + [str(b) for b in (recs.callout_boxes or [])])
        assert "prevent reactionary delay propagation" not in all_text


class TestAlignmentFrameShared:
    def test_reversed_dn_links_detected(self):
        # v1.11.1 / Q4 coverage retained at the frame level (05 cannot run end to end).
        p = _load("05_comprehensive_line")
        frame = build_alignment_frame(p.infrastructure.track_links)
        assert frame.link_align_dir["LNK_13"] == -1.0  # ND_09 @ 22.0 km -> ND_08 @ 17.0 km
        assert frame.align_m("LNK_13", 0.0) == 22000.0 and frame.align_m("LNK_13", 5000.0) == 17000.0
        assert frame.link_align_dir["LNK_03"] == 1.0
