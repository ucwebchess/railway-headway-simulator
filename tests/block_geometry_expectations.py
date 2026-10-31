"""v1.11.2 — single source of truth for the shipped-example block-geometry outcomes.

v1.11.2 validates block geometry before any simulation (literal strict: always raises,
no opt-out). Four shipped examples carry genuine block-model defects and are NOT
modified (patch release, code fixes only), so every test that runs them through
``SimulationRunner.run_simulation_pipeline`` now asserts the exact error and findings
listed here — identically for FORWARD and REVERSE.

  01_single_track        BLK_01   length 1900 m vs entry→exit span 2000 m (+100 m)
  04_tunnel_tvs          BLK_T01  length 2300 m vs span 2450 m (+150 m)
  05_comprehensive_line  BLK_UP_10 / BLK_DN_07 have no exit signal on their own track
                         (v1.11.1 silently used SIG_DN_01 / SIG_UP_03 from the other line)
  07_hsr_140km           BLK_UP_091 has no exit signal (v1.11.1: "N/A"); 20 blocks are
                         ±313 m (one link) off their signal spacing

02_double_track, 03_station_platform and 06_multilink_blocks validate cleanly.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, Optional, Tuple

import pytest

from headway.infrastructure.direction import RunningDirection
from headway.signalling.block_geometry_validation import (
    ERR_BLOCK_GEOMETRY_MISMATCH,
    ERR_BLOCK_NO_EXIT_SIGNAL,
    BlockGeometryValidationError,
)

_HSR_MISMATCH = frozenset({
    "BLK_UP_001", "BLK_UP_008", "BLK_UP_010", "BLK_UP_015", "BLK_UP_020",
    "BLK_UP_022", "BLK_UP_029", "BLK_UP_030", "BLK_UP_036", "BLK_UP_040",
    "BLK_UP_043", "BLK_UP_057", "BLK_UP_060", "BLK_UP_064", "BLK_UP_070",
    "BLK_UP_071", "BLK_UP_078", "BLK_UP_080", "BLK_UP_085", "BLK_UP_090",
})

#: example -> (raised error_code, {finding code: frozenset(block ids)})
EXPECTED_BLOCK_GEOMETRY_ERRORS: Dict[str, Tuple[str, Dict[str, FrozenSet[str]]]] = {
    "01_single_track": (
        ERR_BLOCK_GEOMETRY_MISMATCH,
        {ERR_BLOCK_GEOMETRY_MISMATCH: frozenset({"BLK_01"})},
    ),
    "04_tunnel_tvs": (
        ERR_BLOCK_GEOMETRY_MISMATCH,
        {ERR_BLOCK_GEOMETRY_MISMATCH: frozenset({"BLK_T01"})},
    ),
    "05_comprehensive_line": (
        ERR_BLOCK_NO_EXIT_SIGNAL,
        {ERR_BLOCK_NO_EXIT_SIGNAL: frozenset({"BLK_UP_10", "BLK_DN_07"})},
    ),
    "07_hsr_140km": (
        ERR_BLOCK_NO_EXIT_SIGNAL,
        {
            ERR_BLOCK_NO_EXIT_SIGNAL: frozenset({"BLK_UP_091"}),
            ERR_BLOCK_GEOMETRY_MISMATCH: _HSR_MISMATCH,
        },
    ),
}

CLEAN_EXAMPLES: Tuple[str, ...] = ("02_double_track", "03_station_platform", "06_multilink_blocks")

BOTH_DIRECTIONS: Tuple[RunningDirection, ...] = (RunningDirection.FORWARD, RunningDirection.REVERSE)


def findings_by_code(exc: BlockGeometryValidationError) -> Dict[str, FrozenSet[str]]:
    out: Dict[str, set] = {}
    for f in exc.findings:
        out.setdefault(f.code, set()).add(f.block_id)
    return {k: frozenset(v) for k, v in out.items()}


def assert_block_geometry_error(exc: BaseException, example: str) -> None:
    """``exc`` is exactly the documented v1.11.2 outcome for ``example``."""
    assert isinstance(exc, BlockGeometryValidationError), f"{example}: unexpected {type(exc).__name__}: {exc}"
    code, findings = EXPECTED_BLOCK_GEOMETRY_ERRORS[example]
    assert exc.error_code == code
    assert findings_by_code(exc) == findings
    assert code in str(exc)


def assert_pipeline_raises_block_geometry(
    project,
    example: str,
    directions: Iterable[RunningDirection] = BOTH_DIRECTIONS,
    **pipeline_kwargs,
) -> None:
    """Run the pipeline for ``example`` in each direction and assert the documented
    pre-simulation error (same code and same findings in FORWARD and REVERSE)."""
    from headway.ui.simulation_runner import SimulationRunner

    for d in directions:
        with pytest.raises(BlockGeometryValidationError) as excinfo:
            SimulationRunner.run_simulation_pipeline(project, running_direction=d, **pipeline_kwargs)
        assert_block_geometry_error(excinfo.value, example)


def load_and_assert_pipeline_raises(example: str, directions: Optional[Iterable[RunningDirection]] = None, **kw) -> None:
    from headway.ui.file_manager import FileManager

    project, _, _ = FileManager.load_example_project(example)
    assert_pipeline_raises_block_geometry(project, example, directions or BOTH_DIRECTIONS, **kw)


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
    import copy

    from headway.ui.file_manager import FileManager

    project, _, _ = FileManager.load_example_project("05_comprehensive_line")
    project = copy.deepcopy(project)
    explicit = {"BLK_UP_10": "SIG_DN_01", "BLK_DN_07": "SIG_UP_01"}
    project.signalling.blocks = [
        b.model_copy(update={"exit_signal_id": explicit[b.block_id]}) if b.block_id in explicit else b
        for b in project.signalling.blocks
    ]
    return project
