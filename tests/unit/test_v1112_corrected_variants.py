"""v1.11.2 — guards for the corrected in-memory example variants (tests/corrected_variants.py).

The v1.11.1 feature tests that used to run shipped 01/04/05/07 now run on these variants
(the shipped files raise by design). These tests pin that the variants are what they claim:

* each variant passes pre-simulation block-geometry validation, while the shipped project
  raises exactly the documented ERR_* (so the variant is a *correction*, not a bypass);
* each variant differs from the shipped project ONLY in ``signalling`` and only in the
  blocks / signals named by the correction (same corridor, stations, rolling stock, TVS and
  service pattern -> same code paths);
* building the variants never writes the shipped example files;
* ``patch_examples_with_corrected_variants`` routes exactly 01/04/05/07, and 02/03/06 load
  the real files;
* the variants run end-to-end in FORWARD and REVERSE.
"""

from __future__ import annotations

import hashlib

import pytest

from headway.infrastructure.direction import RunningDirection
from headway.signalling.block_geometry_validation import validate_block_geometry
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner
from tests.block_geometry_expectations import (
    CLEAN_EXAMPLES,
    EXPECTED_BLOCK_GEOMETRY_ERRORS,
)
from tests.corrected_variants import (
    _REAL_LOAD_EXAMPLE,
    CORRECTED_VARIANTS,
    load_corrected_variant,
    patch_examples_with_corrected_variants,
)

DIRS = pytest.mark.parametrize(
    "direction", [RunningDirection.FORWARD, RunningDirection.REVERSE], ids=["FORWARD", "REVERSE"]
)

# Exactly what each correction is allowed to touch.
EXPECTED_CHANGES = {
    "01_single_track": {"blocks": {"BLK_01"}, "signals": set()},
    "04_tunnel_tvs": {"blocks": {"BLK_T01"}, "signals": set()},
    "05_comprehensive_line": {"blocks": {"BLK_UP_10", "BLK_DN_07"}, "signals": set()},
    # every SIG_001..SIG_091 moved to its block's entry boundary, SIG_092 added as the
    # BLK_UP_091 exit / BLK_UP_092 entry.
    "07_hsr_140km": {
        "blocks": {"BLK_UP_091", "BLK_UP_092"},
        "signals": {f"SIG_{k:03d}" for k in range(1, 93)},
    },
}


# v1.12.0: the simulation honours ROUTE_LINK_SEQUENCE, so the 05 variant also routes the two
# services the runner selects for TRN_HSR over the turnback circuit (keeps the turnaround
# blocks covered). Nothing else in Operations may change.
EXPECTED_ROUTE_CHANGES = {
    "05_comprehensive_line": {
        "SVC_HSR_EXP_UP": [f"LNK_{k:02d}" for k in range(1, 18)],
        "SVC_HSR_EXP_DN": [f"LNK_{k:02d}" for k in range(1, 18)],
    },
}


# v1.12.0 (ERR_ROUTE_DIRECTION_FORBIDDEN): shipped 05 TRK_UP / TRK_DN are NOMINAL (one-way);
# the variant declares them BIDIRECTIONAL so its REVERSE runs stay covered. Nothing else in
# Infrastructure may change.
EXPECTED_DIRECTIONALITY_CHANGES = {
    "05_comprehensive_line": {"TRK_UP": "BIDIRECTIONAL", "TRK_DN": "BIDIRECTIONAL"},
}


def test_variant_registry_covers_exactly_the_defective_examples():
    assert set(CORRECTED_VARIANTS) == set(EXPECTED_BLOCK_GEOMETRY_ERRORS) == set(EXPECTED_CHANGES)
    assert not set(CORRECTED_VARIANTS) & set(CLEAN_EXAMPLES)


@pytest.mark.parametrize("example", sorted(CORRECTED_VARIANTS))
def test_variant_validates_and_shipped_raises_documented_codes(example):
    shipped = validate_block_geometry(_REAL_LOAD_EXAMPLE(example)[0])
    _raised, expected_by_code = EXPECTED_BLOCK_GEOMETRY_ERRORS[example]
    by_code = {}
    for f in shipped.findings:
        by_code.setdefault(f.code, set()).add(f.block_id)
    assert by_code == {code: set(ids) for code, ids in expected_by_code.items()}
    variant = validate_block_geometry(CORRECTED_VARIANTS[example]())
    assert variant.ok, [f.message for f in variant.findings]


@pytest.mark.parametrize("example", sorted(CORRECTED_VARIANTS))
def test_variant_changes_only_the_named_blocks_and_signals(example):
    shipped = _REAL_LOAD_EXAMPLE(example)[0].model_dump()
    variant = CORRECTED_VARIANTS[example]().model_dump()
    route_changes = EXPECTED_ROUTE_CHANGES.get(example, {})
    dir_changes = EXPECTED_DIRECTIONALITY_CHANGES.get(example, {})
    expected_top = sorted(
        ["signalling"] + (["operations"] if route_changes else []) + (["infrastructure"] if dir_changes else [])
    )
    assert sorted(k for k in shipped if shipped[k] != variant[k]) == expected_top
    if dir_changes:
        inf_s, inf_v = shipped["infrastructure"], variant["infrastructure"]
        assert {k for k in inf_s if inf_s[k] != inf_v[k]} == {"tracks"}
        trk_s = {t["track_id"]: t for t in inf_s["tracks"]}
        trk_v = {t["track_id"]: t for t in inf_v["tracks"]}
        assert list(trk_s) == list(trk_v), "no track may be added, removed or reordered"
        assert {k for k in trk_v if trk_s[k] != trk_v[k]} == set(dir_changes)
        for tid, value in dir_changes.items():
            assert trk_s[tid]["directionality"] == "NOMINAL"
            assert {k for k in trk_v[tid] if trk_s[tid][k] != trk_v[tid][k]} == {"directionality"}
            assert trk_v[tid]["directionality"] == value
    if route_changes:
        ops_s, ops_v = shipped["operations"], variant["operations"]
        assert {k for k in ops_s if ops_s[k] != ops_v[k]} == {"service_patterns"}
        sps_s = {sp["service_pattern_id"]: sp for sp in ops_s["service_patterns"]}
        sps_v = {sp["service_pattern_id"]: sp for sp in ops_v["service_patterns"]}
        assert list(sps_s) == list(sps_v), "no service pattern may be added, removed or reordered"
        changed = {k for k in sps_v if sps_s[k] != sps_v[k]}
        assert changed == set(route_changes)
        for sp_id, route in route_changes.items():
            assert {k for k in sps_v[sp_id] if sps_s[sp_id][k] != sps_v[sp_id][k]} == {"route_link_sequence"}
            assert sps_v[sp_id]["route_link_sequence"] == route
    sig_s, sig_v = shipped["signalling"], variant["signalling"]
    assert {k for k in sig_s if sig_s[k] != sig_v[k]} <= {"blocks", "signals"}

    blocks_s = {b["block_id"]: b for b in sig_s["blocks"]}
    blocks_v = {b["block_id"]: b for b in sig_v["blocks"]}
    signals_s = {s["signal_id"]: s for s in sig_s["signals"]}
    signals_v = {s["signal_id"]: s for s in sig_v["signals"]}
    assert set(blocks_s) == set(blocks_v), "no block may be added or removed"
    assert set(signals_s) <= set(signals_v), "no signal may be removed"
    changed_blocks = {k for k in blocks_v if blocks_s[k] != blocks_v[k]}
    changed_signals = {k for k in signals_v if signals_s.get(k) != signals_v[k]}
    assert changed_blocks == EXPECTED_CHANGES[example]["blocks"]
    assert changed_signals == EXPECTED_CHANGES[example]["signals"]


def test_building_variants_never_writes_the_shipped_files():
    files = sorted(
        f for ex in CORRECTED_VARIANTS for f in FileManager.get_example_projects()[ex].glob("*.xlsx")
    )
    assert files

    def digest():
        return {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}

    before = digest()
    for ex in CORRECTED_VARIANTS:
        load_corrected_variant(ex)
    assert digest() == before


def test_patch_routes_only_the_defective_examples(monkeypatch):
    patch_examples_with_corrected_variants(monkeypatch)
    for ex in sorted(CORRECTED_VARIANTS):
        assert validate_block_geometry(FileManager.load_example_project(ex)[0]).ok, ex
    for ex in sorted(CLEAN_EXAMPLES):
        patched = FileManager.load_example_project(ex)[0].model_dump()
        real = _REAL_LOAD_EXAMPLE(ex)[0].model_dump()
        assert patched == real, ex
    monkeypatch.undo()
    assert not validate_block_geometry(FileManager.load_example_project("01_single_track")[0]).ok


@DIRS
@pytest.mark.parametrize("example", ["01_single_track", "04_tunnel_tvs"])
def test_small_variants_run_end_to_end(example, direction):
    # The 05 variant runs end-to-end in FORWARD and REVERSE in TestBidirectionalSymmetry;
    # the 07 variant in test_simulation_runner_e2e.py (hsr_sim_results / hsr_rev_sim_results).
    project, _report, _ = load_corrected_variant(example)
    pkg, doc = SimulationRunner.run_simulation_pipeline(project, running_direction=direction)
    assert doc.executive_kpis.technical_headway_s > 0.0
    prov = [r for r in pkg.metadata["provenance_records"] if r.resource_type == "TRACK_BLOCK"]
    assert prov and all(r.exit_signal_id not in (None, "", "N/A") for r in prov)
