"""v1.11.2 — in-memory CORRECTED variants of the four defective shipped examples.

The shipped example files are never modified (patch release, code fixes only). Shipped
01/04/05/07 fail pre-simulation block-geometry validation by design (see
tests/block_geometry_expectations.py). To keep the ORIGINAL feature coverage of the tests
that used to run them, each builder below applies the minimum physical correction that
removes exactly the documented defect(s) — same corridor, stations, rolling stock, tunnels
and service pattern, therefore the same code paths.

  01_single_track       BLK_01 extended to its exit signal (+100 m gap closed)
  04_tunnel_tvs         BLK_T01 extended to its exit signal (+150 m gap closed)
  05_comprehensive_line turnaround blocks given explicit exit signals
  07_hsr_140km          signals placed on block boundaries; SIG_092 added (BLK_UP_091 exit)

Deliberately free of imports from v1.11.2-only modules so the same fixtures can be replayed
on earlier releases for differential (regression) checks.
"""

from __future__ import annotations

from typing import Callable, Dict

def comprehensive_line_with_explicit_turnaround_exits():
    """In-memory variant of 05_comprehensive_line (shipped files untouched).

    The two 05 blocks that fail ERR_BLOCK_NO_EXIT_SIGNAL are given EXPLICIT exit signals
    on the opposite line — an engineering statement that they are turnaround blocks:

      BLK_UP_10: SIG_UP_10 (LNK_10 @ 50 m, 24.05 km) -> SIG_DN_01 (LNK_11 @ 50 m, 24.95 km)
                 along-track path 950 + 50 = 1000 m == length; chainage delta only 900 m
      BLK_DN_07: SIG_DN_07 (LNK_17 @ 50 m, 3.95 km)  -> SIG_UP_01 (LNK_01 @ 50 m, 0.05 km)
                 along-track path 3950 + 50 = 4000 m == length; chainage delta 3900 m

    With these, every 05 block validates, so the full pipeline runs in both directions.
    """
    project, _, _ = _load("05_comprehensive_line")
    return apply_comprehensive_line_turnaround_exits(project)


def apply_comprehensive_line_turnaround_exits(project):
    """Apply the 05T correction in place to an already-loaded 05 project (for tests that
    import the example workbooks themselves rather than via ``FileManager``)."""
    explicit = {"BLK_UP_10": "SIG_DN_01", "BLK_DN_07": "SIG_UP_01"}
    assert explicit.keys() <= {b.block_id for b in project.signalling.blocks}, "not a 05 project"
    project.signalling.blocks = [
        b.model_copy(update={"exit_signal_id": explicit[b.block_id]}) if b.block_id in explicit else b
        for b in project.signalling.blocks
    ]
    return project


def _real_load_example_project():
    """The unpatched ``FileManager.load_example_project`` (a staticmethod), captured so the
    variant builders always read the real shipped Excel files even while a test has the
    loader patched."""
    from headway.ui.file_manager import FileManager

    return FileManager.__dict__["load_example_project"].__func__


_REAL_LOAD_EXAMPLE = _real_load_example_project()


def _load(example: str):
    import copy

    project, report, extra = _REAL_LOAD_EXAMPLE(example)
    return copy.deepcopy(project), report, extra


def _extend_block_to_exit_signal(project, block_id: str, intervals) -> None:
    blocks = []
    found = False
    for b in project.signalling.blocks:
        if b.block_id == block_id:
            proto = b.link_intervals[0]
            new_ivs = [proto.model_copy(update={"link_id": lk, "start_offset_m": s0, "end_offset_m": s1})
                       for lk, s0, s1 in intervals]
            b = b.model_copy(update={"link_intervals": new_ivs})
            found = True
        blocks.append(b)
    assert found, block_id
    project.signalling.blocks = blocks


def single_track_signal_to_signal():
    """01_single_track with BLK_01 extended to its exit signal (signal-to-signal block).

    Defect: BLK_01 covers LNK_01 50–1950 m but its exit signal SIG_02 is at LNK_02 @ 50 m,
    leaving 100 m (LNK_01 1950–2000, LNK_02 0–50) in no block. Correction: BLK_01 =
    LNK_01 50–2000 + LNK_02 0–50 (2000 m == SIG_01→SIG_02 span). Nothing else changes.
    """
    project, _, _ = _load("01_single_track")
    _extend_block_to_exit_signal(project, "BLK_01", [("LNK_01", 50.0, 2000.0), ("LNK_02", 0.0, 50.0)])
    return project


def tunnel_tvs_signal_to_signal():
    """04_tunnel_tvs with BLK_T01 extended to its exit signal (signal-to-signal block).

    Defect: BLK_T01 covers LNK_T01 100–2400 m but SIG_T02 is at LNK_T02 @ 50 m (150 m gap).
    Correction: BLK_T01 = LNK_T01 100–2500 + LNK_T02 0–50 (2450 m == SIG_T01→SIG_T02 span).
    """
    project, _, _ = _load("04_tunnel_tvs")
    _extend_block_to_exit_signal(project, "BLK_T01", [("LNK_T01", 100.0, 2500.0), ("LNK_T02", 0.0, 50.0)])
    return project


def hsr_corridor_signals_at_block_boundaries():
    """07_hsr_140km with every block signal placed ON its block boundary.

    Defect: the 92 blocks (whole 313 m links) are the reserved resources, but each SIG_k
    sits 50 m into a link roughly one block downstream of BLK_UP_k's entry, so 20 blocks
    are one link (±313 m) off their signal span and BLK_UP_091 has no exit signal.
    Correction (block resources untouched): SIG_k moves to the entry boundary of
    BLK_UP_k (offset 0 of its first link); a new SIG_092 is placed at the entry boundary
    of BLK_UP_092 and becomes BLK_UP_091's exit and BLK_UP_092's entry. BLK_UP_092 ends
    at the ENDPOINT buffer stop ND_0448 (true terminal, no exit signal required).
    """
    project, _, _ = _load("07_hsr_140km")
    sigs = {s.signal_id: s for s in project.signalling.signals}
    blocks = {b.block_id: b for b in project.signalling.blocks}
    moved = []
    for s in project.signalling.signals:
        bid = "BLK_UP_" + s.signal_id.split("_")[1]
        first = blocks[bid].link_intervals[0]
        moved.append(s.model_copy(update={"link_id": first.link_id, "offset_m": float(first.start_offset_m)}))
    first_092 = blocks["BLK_UP_092"].link_intervals[0]
    moved.append(sigs["SIG_091"].model_copy(update={
        "signal_id": "SIG_092", "link_id": first_092.link_id, "offset_m": float(first_092.start_offset_m)}))
    project.signalling.signals = moved
    project.signalling.blocks = [
        b.model_copy(update={"exit_signal_id": "SIG_092"}) if b.block_id == "BLK_UP_091"
        else b.model_copy(update={"entry_signal_id": "SIG_092"}) if b.block_id == "BLK_UP_092"
        else b
        for b in project.signalling.blocks
    ]
    return project


#: shipped example -> builder of its corrected in-memory variant
CORRECTED_VARIANTS: Dict[str, Callable] = {
    "01_single_track": single_track_signal_to_signal,
    "04_tunnel_tvs": tunnel_tvs_signal_to_signal,
    "05_comprehensive_line": comprehensive_line_with_explicit_turnaround_exits,
    "07_hsr_140km": hsr_corridor_signals_at_block_boundaries,
}


def load_corrected_variant(example: str):
    """Drop-in for ``FileManager.load_example_project`` returning the corrected variant
    (same 3-tuple shape; the validation report / file map are those of the real load)."""
    _project, report, extra = _REAL_LOAD_EXAMPLE(example)
    return CORRECTED_VARIANTS[example](), report, extra


def patch_examples_with_corrected_variants(monkeypatch) -> None:
    """Route ``FileManager.load_example_project`` for 01/04/05/07 to their corrected
    variants (02/03/06 load unchanged). For UI-level tests whose handlers load examples by
    name: the whole UI path runs, only the defective geometry is replaced."""
    from headway.ui.file_manager import FileManager

    def _patched(example_name: str):
        if example_name in CORRECTED_VARIANTS:
            return load_corrected_variant(example_name)
        return _REAL_LOAD_EXAMPLE(example_name)

    monkeypatch.setattr(FileManager, "load_example_project", staticmethod(_patched))
