"""v1.15.1: fit-check wiring, Option B (named warning, simulation continues).

The v1.14.1 rule (``RoutePlatformStop.check_train_fit``: a train fits iff
``L <= parent_platform_length_m + FIT_TOLERANCE_M``) now runs in ``run_simulation_pipeline`` for every
scheduled stop, before Pass 1. ``ERR_TRAIN_OVERHANG`` is caught and converted into a
``WARNING_TRAIN_OVERHANG`` record (``package.metadata["warnings"]``, Section 0.0) plus the Section 6
"Overhang (m)" and Section 11 "Train Fits" columns. Results are not altered.

u8000 stand-in: the user project's workbooks must never be committed, so the u8000 tests use shipped
example 06 with its train set to 202 m (u8000 TRN_HSR length). PLT_01 (200 m) then overhangs by 2.0 m
and PLT_02 (300 m) fits: exactly one warning per direction. The real u8000 evidence (headway 130/130 s,
journey unchanged, 3 warnings per direction: PLT_ADS, PLT_YAS, PLT_AUH) is in the v1.15.1 completion
report.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import pytest

import headway.reporting.report_config as report_config
from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_models import ReportSectionId
from headway.ui.simulation_runner import WARNING_TRAIN_OVERHANG, SimulationRunner, TrainOverhangWarning
from tests.corrected_variants import _load, double_track_bidirectional_up, load_corrected_variant

FWD, REV = RunningDirection.FORWARD, RunningDirection.REVERSE
BOTH = pytest.mark.parametrize("direction", [FWD, REV], ids=["FORWARD", "REVERSE"])

pytestmark = [
    pytest.mark.filterwarnings("ignore::headway.infrastructure.stations.BerthFallbackWarning"),
    pytest.mark.filterwarnings("ignore::headway.simulation.dispatching.EntryGapWarning"),
]


# ----------------------------------------------------------------------------------------------
# Helper-level fixtures: the pipeline's fit check on synthetic parent platforms
# ----------------------------------------------------------------------------------------------

_BASE: dict = {}


def _base():
    if not _BASE:
        proj = SimulationRunner._project_with_stop_segments(_load("06_multilink_blocks")[0])
        _BASE["plat"] = next(p for p in proj.infrastructure.platforms if p.platform_id == "PLT_01@s1")
        _BASE["stations"] = list(proj.infrastructure.stations)
    return _BASE


def _parent(segment_lengths, pid="PLT_X"):
    base = _base()["plat"]
    return [
        base.model_copy(update={"platform_id": f"{pid}@s{i}", "parent_platform_id": pid, "length_m": float(length)})
        for i, length in enumerate(segment_lengths, start=1)
    ]


def _check(train_m, segment_lengths=(200.0,), direction=FWD, repeat=1):
    """Run the pipeline fit check for one stop on the last segment of PLT_X (stop given ``repeat`` times)."""
    plats = _parent(segment_lengths)
    stops = [SimpleNamespace(platform_id=plats[-1].platform_id)] * repeat
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        records, fit = SimulationRunner._fit_check_service_stops(
            service_stops=stops,
            platforms=plats,
            stations=_base()["stations"],
            train_type_id="TRN_TEST",
            train_length_m=train_m,
            running_direction=direction,
        )
    return records, fit, [w for w in caught if issubclass(w.category, TrainOverhangWarning)]


# ----------------------------------------------------------------------------------------------
# End-to-end fixtures: u8000 stand-in (example 06, 202 m train)
# ----------------------------------------------------------------------------------------------

_RUNS: dict = {}


def _with_train_length(project, length_m):
    rs = project.rolling_stock
    tts = [rs.train_types[0].model_copy(update={"length_m": float(length_m)}), *rs.train_types[1:]]
    return project.model_copy(update={"rolling_stock": rs.model_copy(update={"train_types": tts})})


def _standin(direction, fit_check=True):
    """Example 06 with a 202 m train. ``fit_check=False`` replaces the fit check with a no-op (reference
    run without v1.15.1) so results can be compared one-to-one."""
    key = (direction, fit_check)
    if key not in _RUNS:
        proj = _with_train_length(_load("06_multilink_blocks")[0], 202.0)
        if fit_check:
            _RUNS[key] = SimulationRunner.run_simulation_pipeline(proj, running_direction=direction)
        else:
            mp = pytest.MonkeyPatch()
            mp.setattr(SimulationRunner, "_fit_check_service_stops", staticmethod(lambda **kw: ([], {})))
            try:
                _RUNS[key] = SimulationRunner.run_simulation_pipeline(proj, running_direction=direction)
            finally:
                mp.undo()
    return _RUNS[key]


def _table(doc, section_id, table_id):
    return next(t for t in doc.get_section(section_id).tables if t.table_id == table_id)


def _overhangs(pkg):
    return [w for w in pkg.metadata["warnings"] if w["code"] == WARNING_TRAIN_OVERHANG]


# ----------------------------------------------------------------------------------------------
# 1-4. The fit check in the pipeline
# ----------------------------------------------------------------------------------------------

@BOTH
def test_train_fits_exactly(direction):
    """200 m train on a 200 m platform: fits, no warning, overhang 0.0."""
    records, fit, caught = _check(200.0, (200.0,), direction)
    assert records == [] and caught == []
    assert fit == {"PLT_X": {"parent_platform_length_m": 200.0, "train_length_m": 200.0, "overhang_m": 0.0, "fits": True}}


@BOTH
def test_train_fits_within_tolerance(direction):
    """200.0005 m on 200 m is within FIT_TOLERANCE_M (1 mm): fits, no warning, overhang exactly 0.0 (D4)."""
    records, fit, caught = _check(200.0005, (200.0,), direction)
    assert records == [] and caught == []
    assert fit["PLT_X"]["fits"] is True
    assert fit["PLT_X"]["overhang_m"] == 0.0


@BOTH
def test_train_overhangs_2m_warns(direction):
    """202 m on a 200 m two-segment parent (u8000 PLT_AUH geometry: 61.08 + 138.92 m): one
    WARNING_TRAIN_OVERHANG with 2.0 m; a stop seen twice is recorded once."""
    records, fit, caught = _check(202.0, (61.08, 138.92), direction, repeat=2)
    assert len(records) == 1 and len(caught) == 1
    w = records[0]
    assert w["code"] == "WARNING_TRAIN_OVERHANG"
    assert (w["train_id"], w["platform_id"], w["segment_id"], w["direction"]) == ("TRN_TEST", "PLT_X", "PLT_X@s2", direction.value)
    assert w["train_length_m"] == 202.0
    assert w["platform_length_m"] == pytest.approx(200.0)
    assert w["overhang_m"] == pytest.approx(2.0)
    assert w["message"] == (
        "WARNING_TRAIN_OVERHANG: Train TRN_TEST (202.0 m) exceeds platform PLT_X (200.0 m) by 2.0 m."
    )  # v1.15.2: trailing "Simulation continues; overhang disclosed in Sections 6 and 11." removed
    assert str(caught[0].message) == w["message"]
    assert fit["PLT_X"]["fits"] is False and fit["PLT_X"]["overhang_m"] == pytest.approx(2.0)


@BOTH
def test_train_overhangs_50m_warns(direction):
    """250 m on 200 m: warning with 50.0 m and no error (Option B: ERR_TRAIN_OVERHANG is never raised)."""
    records, fit, caught = _check(250.0, (200.0,), direction)
    assert len(records) == 1 and len(caught) == 1
    assert records[0]["overhang_m"] == pytest.approx(50.0)
    assert "by 50.0 m" in records[0]["message"]
    assert fit["PLT_X"]["overhang_m"] == pytest.approx(50.0)


# ----------------------------------------------------------------------------------------------
# 5-7. Report disclosure (u8000 stand-in)
# ----------------------------------------------------------------------------------------------

@BOTH
def test_overhang_in_section6(direction):
    pkg, doc = _standin(direction)
    tbl = _table(doc, ReportSectionId.STATION_PLATFORM_OCCUPATION, "TBL_PLATFORM_OCCUPATION")
    raw = tbl.raw_dataframe.set_index("Platform ID")
    fmt = tbl.formatted_dataframe.set_index("Platform ID")
    assert list(tbl.raw_dataframe.columns)[-1] == "Overhang (m)"
    assert raw.loc["PLT_01", "Overhang (m)"] == pytest.approx(2.0)
    assert raw.loc["PLT_02", "Overhang (m)"] == 0.0
    assert (fmt.loc["PLT_01", "Overhang (m)"], fmt.loc["PLT_02", "Overhang (m)"]) == ("2.0", "0.0")


@BOTH
def test_overhang_in_section11(direction):
    pkg, doc = _standin(direction)
    seg = _table(doc, ReportSectionId.GEOMETRY_PROVENANCE, "TBL_PLATFORM_SEGMENT_PROVENANCE")
    fits = dict(zip(seg.raw_dataframe["Segment ID"], seg.raw_dataframe["Train Fits"]))
    assert fits == {"PLT_01@s1": "No — overhang 2.0 m", "PLT_02@s1": "Yes"}
    assert list(seg.formatted_dataframe["Train Fits"]) == list(seg.raw_dataframe["Train Fits"])
    # D3-A: the column is on the platform segment table only, not on the resource register.
    reg = _table(doc, ReportSectionId.GEOMETRY_PROVENANCE, "TBL_RESOURCE_PROVENANCE")
    assert "Train Fits" not in reg.raw_dataframe.columns


@pytest.mark.parametrize(
    "case", ["06_FORWARD", "06_REVERSE", "03_REVERSE_with_entry_gap"],
)
def test_warnings_section_lists_overhang(case):
    """Section 0.0 lists WARNING_TRAIN_OVERHANG in the shared Code | Train | Direction | Message table.
    03 REVERSE with a 302 m train (PLT_01 300 m) shows it next to the v1.15.0 WARNING_ENTRY_GAP rows."""
    if case.startswith("06"):
        direction = FWD if case.endswith("FORWARD") else REV
        pkg, doc = _standin(direction)
        expected_platform = "PLT_01"
    else:
        direction = REV
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            _with_train_length(_load("03_station_platform")[0], 302.0), running_direction=REV
        )
        expected_platform = "PLT_01"
    sec = doc.get_section(ReportSectionId.WARNINGS)
    assert sec.section_number == "0.0"
    df = next(t for t in sec.tables if t.table_id == "TBL_WARNINGS").raw_dataframe
    assert list(df.columns) == ["Code", "Train", "Direction", "Message"]
    rows = df[df["Code"] == "WARNING_TRAIN_OVERHANG"]
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["Train"] == "TRN_COMMUTER"
    assert row["Direction"] == direction.value
    assert f"exceeds platform {expected_platform}" in row["Message"] and "by 2.0 m" in row["Message"]
    assert sec.narrative_paragraphs == [f"{len(df)} warning(s) were raised during this analysis."]
    if case == "03_REVERSE_with_entry_gap":
        assert set(df["Code"]) == {"WARNING_TRAIN_OVERHANG", "WARNING_ENTRY_GAP"}
        assert list(df["Code"]).count("WARNING_ENTRY_GAP") == 2  # leader and follower (v1.15.0)


# ----------------------------------------------------------------------------------------------
# 8-9. u8000 stand-in: the simulation continues and is not altered
# ----------------------------------------------------------------------------------------------

@BOTH
def test_u8000_standin_continues(direction):
    """No ERR_TRAIN_OVERHANG; headway, journey time, station stops and blocking intervals are identical
    to the same run with the fit check disabled (disclosure only)."""
    pkg, doc = _standin(direction, fit_check=True)
    ref_pkg, _ = _standin(direction, fit_check=False)
    m, r = pkg.metadata, ref_pkg.metadata
    assert m["technical_minimum_headway_s"] == r["technical_minimum_headway_s"]
    assert m.get("journey_time_s") == r.get("journey_time_s")
    assert [(s.station_id, s.front_stopping_position_m, s.rear_stopping_position_m) for s in m["station_stops"]] == [
        (s.station_id, s.front_stopping_position_m, s.rear_stopping_position_m) for s in r["station_stops"]
    ]
    assert [(b.resource_id, b.start_time_s, b.end_time_s) for b in m["blocking_intervals"]] == [
        (b.resource_id, b.start_time_s, b.end_time_s) for b in r["blocking_intervals"]
    ]
    assert _overhangs(ref_pkg) == []


@BOTH
def test_u8000_standin_one_warning_per_direction(direction):
    pkg, _ = _standin(direction)
    overhangs = _overhangs(pkg)
    assert len(overhangs) == 1
    w = overhangs[0]
    assert (w["train_id"], w["platform_id"], w["segment_id"], w["direction"]) == (
        "TRN_COMMUTER", "PLT_01", "PLT_01@s1", direction.value
    )
    assert w["overhang_m"] == pytest.approx(2.0)
    assert pkg.metadata["platform_fit"]["PLT_02"]["fits"] is True


# ----------------------------------------------------------------------------------------------
# 10. Shipped examples: unchanged, no new warnings
# ----------------------------------------------------------------------------------------------

_SHIPPED = {
    "01c": lambda: load_corrected_variant("01_single_track")[0],
    "02_bidirectional": double_track_bidirectional_up,
    "03": lambda: _load("03_station_platform")[0],
    "04c": lambda: load_corrected_variant("04_tunnel_tvs")[0],
    "05c": lambda: load_corrected_variant("05_comprehensive_line")[0],
    "06": lambda: _load("06_multilink_blocks")[0],
    "07c": lambda: load_corrected_variant("07_hsr_140km")[0],
}
# v1.15.0.1 baseline (headway s, journey s, existing warning codes).
_BASELINE = {
    ("01c", "FORWARD"): (163.0, 247.0, []), ("01c", "REVERSE"): (159.0, 247.0, []),
    ("02_bidirectional", "FORWARD"): (89.0, 136.0, []), ("02_bidirectional", "REVERSE"): (87.0, 134.0, []),
    ("03", "FORWARD"): (140.0, 171.0, []), ("03", "REVERSE"): (179.0, 172.0, ["WARNING_ENTRY_GAP"] * 2),
    ("04c", "FORWARD"): (121.0, 201.0, []), ("04c", "REVERSE"): (118.0, 201.0, []),
    ("05c", "FORWARD"): (192.0, 1559.0, []), ("05c", "REVERSE"): (271.0, 1579.0, []),
    ("06", "FORWARD"): (160.0, 304.0, []), ("06", "REVERSE"): (158.0, 300.0, []),
    ("07c", "FORWARD"): (251.0, 2969.0, []), ("07c", "REVERSE"): (257.0, 2969.0, []),
}


@pytest.mark.parametrize("dataset,direction", list(_BASELINE), ids=[f"{d}-{r}" for d, r in _BASELINE])
def test_all_shipped_examples_no_new_warnings(dataset, direction):
    headway_s, journey_s, codes = _BASELINE[(dataset, direction)]
    pkg, doc = SimulationRunner.run_simulation_pipeline(_SHIPPED[dataset](), running_direction=RunningDirection[direction])
    m = pkg.metadata
    assert m["technical_minimum_headway_s"] == headway_s
    assert m.get("journey_time_s") == journey_s
    assert [w["code"] for w in m["warnings"]] == codes
    assert all(f["fits"] and f["overhang_m"] == 0.0 for f in m["platform_fit"].values())
    sec6 = doc.get_section(ReportSectionId.STATION_PLATFORM_OCCUPATION)
    if sec6.is_applicable:
        # Stop platforms: 0.0 (the train fits). Platforms passed without a stop: "—" (raw None/NaN).
        tbl = sec6.tables[0]
        for pid, raw, fmt in zip(tbl.raw_dataframe["Platform ID"], tbl.raw_dataframe["Overhang (m)"],
                                 tbl.formatted_dataframe["Overhang (m)"]):
            if pid in m["platform_fit"]:
                assert (raw, fmt) == (0.0, "0.0")
            else:
                assert raw is None or raw != raw  # None / NaN
                assert fmt == "—"


# ----------------------------------------------------------------------------------------------
# 11. TRAIN_OVERHANG_ERROR_LIMIT_M is reserved (v1.15.2), not enforced
# ----------------------------------------------------------------------------------------------

@BOTH
def test_overhang_error_limit_not_enforced(direction, monkeypatch):
    assert report_config.TRAIN_OVERHANG_ERROR_LIMIT_M is None  # Option B default
    monkeypatch.setattr(report_config, "TRAIN_OVERHANG_ERROR_LIMIT_M", 5.0)
    records, fit, caught = _check(250.0, (200.0,), direction)  # 50 m > 5 m limit: still only a warning
    assert len(records) == 1 and len(caught) == 1
    assert records[0]["overhang_m"] == pytest.approx(50.0)
