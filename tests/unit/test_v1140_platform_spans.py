"""v1.14.0 — Platform schema replacement (Platforms -> PlatformSpans).

The 14 acceptance tests of PR A:
 1. single-link span            2. two-link span              3. three-link span
 4. span at track start         5. span at track end          6. exceeds-track raise
 7. legacy Platforms raise      8. StoppingPoints raise       9. StoppingPatterns parent resolution
10. segment-reference raise    11. report aggregation        12. footnote listing
13. deterministic IDs          14. migration helper roundtrip
"""

from __future__ import annotations

import importlib.util
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

import openpyxl
import pytest

from headway.data.platform_spans import (
    ERR_PLATFORM_SPAN_EXCEEDS_TRACK,
    ERR_PLATFORMS_DEPRECATED,
    ERR_STOPPING_PATTERN_REFERENCES_SEGMENT,
    ERR_STOPPINGPOINTS_DEPRECATED,
    MIGRATION_GUIDE,
    PlatformSpanError,
    segment_all_platform_spans,
    segment_platform_span,
    track_chainage_frame,
)
from headway.infrastructure.direction import RunningDirection
from headway.reporting.result_models import PlatformOccupationRecord
from headway.reporting.tables import create_platform_occupation_table
from headway.ui.file_manager import FileManager

ROOT = Path(__file__).resolve().parents[2]
EX03 = ROOT / "examples" / "03_station_platform"
EX06 = ROOT / "examples" / "06_multilink_blocks"

# Track TRK_A: LNK_A1 (0–500 m), LNK_A2 (500–580 m), LNK_A3 (580–700 m), LNK_A4 (700–1000 m).
# TrackLinks rows deliberately out of order: the frame follows the node chain, not row order.
LINKS = [
    {"link_id": "LNK_A3", "track_id": "TRK_A", "start_node_id": "N3", "end_node_id": "N4", "length_m": 120.0},
    {"link_id": "LNK_A1", "track_id": "TRK_A", "start_node_id": "N1", "end_node_id": "N2", "length_m": 500.0},
    {"link_id": "LNK_A4", "track_id": "TRK_A", "start_node_id": "N4", "end_node_id": "N5", "length_m": 300.0},
    {"link_id": "LNK_A2", "track_id": "TRK_A", "start_node_id": "N2", "end_node_id": "N3", "length_m": 80.0},
]
STATIONS = {"STN_A"}
TRACKS = {"TRK_A"}


def _span(pid: str, s_km: float, e_km: float, off: Any = None) -> Dict[str, Any]:
    return {"platform_id": pid, "station_id": "STN_A", "track_id": "TRK_A",
            "start_chainage_km": s_km, "end_chainage_km": e_km, "segment_hint_offset_m": off}


def _seg(pid: str, s_km: float, e_km: float, off: Any = None):
    return segment_platform_span(_span(pid, s_km, e_km, off), track_chainage_frame(LINKS, "TRK_A"), STATIONS, TRACKS)


def _geom(res) -> List[tuple]:
    return [(p.platform_id, p.link_id, p.start_offset_m, p.end_offset_m, p.parent_platform_id) for p in res.segments]


def _copy_example(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("README*", "*.md"))
    return dst


def _import(folder: Path):
    return FileManager.import_excel_files(sorted(str(p) for p in folder.glob("*.xlsx")))


def _load_helper():
    spec = importlib.util.spec_from_file_location("migrate_platforms", ROOT / "docs" / "migrate_platforms.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module via sys.modules
    spec.loader.exec_module(mod)
    return mod


def _rec(seg: str, parent: str, *, occupied: bool, res: float = 0.0, arr: float = 0.0,
         dep: float = 0.0, fin: float = 0.0) -> PlatformOccupationRecord:
    return PlatformOccupationRecord(
        train_id="TRN_LEADER", station_id="STN_A", station_name="Station A", platform_id=seg,
        track_id="TRK_A", link_id="LNK_A1", arrival_time_s=arr, dwell_start_time_s=arr,
        dwell_end_time_s=dep, departure_time_s=dep, clearance_time_s=fin if occupied else 0.0,
        running_direction=RunningDirection.FORWARD,
        reservation_start_s=res if occupied else None, final_release_s=fin if occupied else None,
        never_occupied=not occupied, parent_platform_id=parent,
    )


# ---------------------------------------------------------------------------
# 1–6: auto-segmentation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_01_single_link_span():
    res = _seg("PLT_1", 0.100, 0.400)
    assert _geom(res) == [("PLT_1@s1", "LNK_A1", 100.0, 400.0, "PLT_1")]
    # SEGMENT_HINT_OFFSET_M blank -> mid-platform
    assert res.segment_hint_offset_m == pytest.approx(150.0)
    assert (res.stopping_point.platform_id, res.stopping_point.link_id, res.stopping_point.offset_m) == ("PLT_1@s1", "LNK_A1", 250.0)
    assert res.stopping_point.stopping_point_id == "PLT_1@stop"


@pytest.mark.unit
def test_02_two_link_span():
    res = _seg("PLT_2", 0.380, 0.560, off=150.0)  # stop at 530 m -> LNK_A2 + 30
    assert _geom(res) == [
        ("PLT_2@s1", "LNK_A1", 380.0, 500.0, "PLT_2"),
        ("PLT_2@s2", "LNK_A2", 0.0, 60.0, "PLT_2"),
    ]
    assert [p.length_m for p in res.segments] == [120.0, 60.0]
    assert res.stop_segment_id == "PLT_2@s2"
    assert (res.stopping_point.link_id, res.stopping_point.offset_m) == ("LNK_A2", 30.0)


@pytest.mark.unit
def test_03_three_link_span():
    res = _seg("PLT_3", 0.450, 0.650, off=60.0)  # stop at 510 m -> LNK_A2 + 10
    assert _geom(res) == [
        ("PLT_3@s1", "LNK_A1", 450.0, 500.0, "PLT_3"),
        ("PLT_3@s2", "LNK_A2", 0.0, 80.0, "PLT_3"),
        ("PLT_3@s3", "LNK_A3", 0.0, 70.0, "PLT_3"),
    ]
    assert sum(p.length_m for p in res.segments) == pytest.approx(200.0)
    assert res.stop_segment_id == "PLT_3@s2"
    # Stop exactly on an internal boundary (500 m): the first (earlier) segment wins.
    assert _seg("PLT_3", 0.450, 0.650, off=50.0).stop_segment_id == "PLT_3@s1"


@pytest.mark.unit
def test_04_span_at_track_start():
    res = _seg("PLT_S", 0.0, 0.020, off=0.0)
    assert _geom(res) == [("PLT_S@s1", "LNK_A1", 0.0, 20.0, "PLT_S")]
    assert (res.stopping_point.link_id, res.stopping_point.offset_m) == ("LNK_A1", 0.0)


@pytest.mark.unit
def test_05_span_at_track_end():
    res = _seg("PLT_E", 0.650, 1.000, off=350.0)  # ends exactly at track coverage end
    assert _geom(res) == [
        ("PLT_E@s1", "LNK_A3", 70.0, 120.0, "PLT_E"),
        ("PLT_E@s2", "LNK_A4", 0.0, 300.0, "PLT_E"),
    ]
    assert (res.stop_segment_id, res.stopping_point.offset_m) == ("PLT_E@s2", 300.0)


@pytest.mark.unit
def test_06_exceeds_track_raise():
    with pytest.raises(PlatformSpanError) as exc:
        _seg("PLT_X", 0.900, 1.050)
    err = exc.value
    assert err.error_code == ERR_PLATFORM_SPAN_EXCEEDS_TRACK
    assert "PLT_X" in str(err) and "TRK_A" in str(err) and MIGRATION_GUIDE in str(err)
    with pytest.raises(PlatformSpanError) as exc_neg:
        _seg("PLT_N", -0.010, 0.100)
    assert exc_neg.value.error_code == ERR_PLATFORM_SPAN_EXCEEDS_TRACK


# ---------------------------------------------------------------------------
# 7–10: cross-workbook rules (real workbooks through the import pipeline)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_07_legacy_platforms_raise(tmp_path):
    from headway.ui.error_handling import create_platform_schema_error_html

    folder = _copy_example(EX03, tmp_path / "ex03")
    wb = openpyxl.load_workbook(folder / "01_Infrastructure.xlsx")
    ws = wb.create_sheet("Platforms")
    ws.append(["PLATFORM_ID", "STATION_ID", "LINK_ID", "START_OFFSET_M", "END_OFFSET_M", "LENGTH_M"])
    ws.append(["PLT_01", "STN_CENTRAL", "LNK_STN_01", 400, 700, 300])
    wb.save(folder / "01_Infrastructure.xlsx")

    proj, report, _ = _import(folder)
    assert proj is None, "a workbook with a legacy Platforms sheet must be refused"
    hits = [f for f in report.findings if f.error_code == ERR_PLATFORMS_DEPRECATED]
    assert len(hits) == 1
    assert hits[0].worksheet == "Platforms" and hits[0].severity.name == "CRITICAL"
    assert "Platforms" in hits[0].message and MIGRATION_GUIDE in hits[0].message
    banner = create_platform_schema_error_html(report.findings)
    assert banner and ERR_PLATFORMS_DEPRECATED in banner and "MIGRATION_v1.14.0.md" in banner


@pytest.mark.unit
def test_08_stoppingpoints_raise(tmp_path):
    folder = _copy_example(EX03, tmp_path / "ex03")
    wb = openpyxl.load_workbook(folder / "01_Infrastructure.xlsx")
    ws = wb.create_sheet("StoppingPoints")
    ws.append(["STOPPING_POINT_ID", "PLATFORM_ID", "LINK_ID", "OFFSET_M"])
    ws.append(["STP_01", "PLT_01", "LNK_STN_01", 680])
    wb.save(folder / "01_Infrastructure.xlsx")

    proj, report, _ = _import(folder)
    assert proj is None
    hits = [f for f in report.findings if f.error_code == ERR_STOPPINGPOINTS_DEPRECATED]
    assert len(hits) == 1
    assert "StoppingPoints" in hits[0].message and "SEGMENT_HINT_OFFSET_M" in hits[0].message
    assert MIGRATION_GUIDE in hits[0].message
    assert not [f for f in report.findings if f.error_code == ERR_PLATFORMS_DEPRECATED]


@pytest.mark.unit
def test_09_stopping_pattern_parent_resolution(tmp_path):
    """StoppingPatterns reference PLATFORM_ID; the simulation stops on the segment holding
    the segment hint point. Example 06 with PLT_02 extended back across the LNK_03/LNK_04
    boundary (segment hint 4.4 km = LNK_04 + 1200 m) -> 2 segments, stop on @s2.

    The engine berthing rule (unchanged) applies to the stop segment: FORWARD, the train
    rear berths at the segment start -> rear at 3200 m (start of LNK_04 = PLT_02@s2)."""
    from headway.reporting.report_models import ReportSectionId
    from headway.ui.simulation_runner import SimulationRunner

    folder = _copy_example(EX06, tmp_path / "ex06")
    wb = openpyxl.load_workbook(folder / "01_Infrastructure.xlsx")
    ws = wb["PlatformSpans"]
    for row in ws.iter_rows(min_row=3):
        if row[0].value == "PLT_02":
            row[3].value, row[4].value, row[5].value = 3.1, 4.5, 1300.0
    wb.save(folder / "01_Infrastructure.xlsx")

    proj, report, _ = _import(folder)
    assert proj is not None, [f.message for f in report.findings if f.severity.name in ("CRITICAL", "ERROR")]
    segs = {p.platform_id: (p.link_id, p.start_offset_m, p.end_offset_m) for p in proj.infrastructure.platforms}
    assert segs["PLT_02@s1"] == ("LNK_03", 900.0, 1000.0)
    assert segs["PLT_02@s2"] == ("LNK_04", 0.0, 1300.0)
    stop_ids = [st.platform_id for sp in proj.operations.service_patterns for st in sp.stops]
    assert "PLT_02" in stop_ids and not any("@" in s for s in stop_ids)

    view = SimulationRunner._project_with_stop_segments(proj)
    assert [st.platform_id for sp in view.operations.service_patterns for st in sp.stops] == [
        {"PLT_01": "PLT_01@s1", "PLT_02": "PLT_02@s2"}[s] for s in stop_ids
    ]
    assert [st.platform_id for sp in proj.operations.service_patterns for st in sp.stops] == stop_ids  # not mutated

    pkg, doc = SimulationRunner.run_simulation_pipeline(proj, running_direction=RunningDirection.FORWARD)
    stops = {r.station_id: r for r in pkg.metadata["station_stops"]}
    assert stops["STN_02"].platform_id == "PLT_02"  # reports show the parent ID
    assert stops["STN_02"].link_id == "LNK_04"
    assert stops["STN_02"].rear_stopping_position_m == pytest.approx(3200.0, abs=0.5)
    recs = {r.platform_id: r for r in pkg.metadata["platform_records"]}
    assert recs["PLT_02@s1"].never_occupied and not recs["PLT_02@s2"].never_occupied
    tbl = doc.get_section(ReportSectionId.STATION_PLATFORM_OCCUPATION).tables[0].raw_dataframe
    assert list(tbl["Platform ID"]) == ["PLT_01", "PLT_02"]  # FORWARD arrival order, not segment order
    row = tbl[tbl["Platform ID"] == "PLT_02"].iloc[0]
    assert row["Segments"] == "PLT_02@s1, PLT_02@s2"
    assert row["Passenger Dwell (s)"] > 0.0


@pytest.mark.unit
def test_10_segment_reference_raise(tmp_path):
    from headway.data.canonical import StationStop

    folder = _copy_example(EX03, tmp_path / "ex03")
    wb = openpyxl.load_workbook(folder / "04_Operations.xlsx")
    ws = wb["StoppingPatterns"]
    hdr = [c.value for c in ws[1]]
    ws.cell(3, hdr.index("PLATFORM_ID") + 1).value = "PLT_01@s1"
    wb.save(folder / "04_Operations.xlsx")

    proj, report, _ = _import(folder)
    assert proj is None
    hits = [f for f in report.findings if f.error_code == ERR_STOPPING_PATTERN_REFERENCES_SEGMENT]
    assert hits and hits[0].object_id == "PLT_01@s1"
    assert "'PLT_01'" in hits[0].message and MIGRATION_GUIDE in hits[0].message

    with pytest.raises(PlatformSpanError) as exc:
        StationStop(station_id="STN_CENTRAL", platform_id="PLT_01@s1", dwell_time_s=30.0)
    assert exc.value.error_code == ERR_STOPPING_PATTERN_REFERENCES_SEGMENT


# ---------------------------------------------------------------------------
# 11–12: reports
# ---------------------------------------------------------------------------

def _records() -> List[PlatformOccupationRecord]:
    return [
        _rec("PLT_X@s1", "PLT_X", occupied=False),
        _rec("PLT_X@s2", "PLT_X", occupied=True, res=80.0, arr=100.0, dep=160.0, fin=190.0),
        _rec("PLT_X@s3", "PLT_X", occupied=False),
        _rec("PLT_Y@s1", "PLT_Y", occupied=True, res=300.0, arr=310.0, dep=355.0, fin=380.0),
    ]


@pytest.mark.unit
def test_11_report_aggregation():
    df = create_platform_occupation_table(_records()).raw_dataframe
    assert list(df.columns) == [
        "Platform ID", "Station", "Total Occupation (s)", "Arrival Approach (s)",
        "Passenger Dwell (s)", "Departure Clearance (s)", "Segments",
    ]
    assert list(df["Platform ID"]) == ["PLT_X", "PLT_Y"]  # one row per parent, no segment rows
    x = df.iloc[0]
    assert (x["Arrival Approach (s)"], x["Passenger Dwell (s)"], x["Departure Clearance (s)"]) == (20.0, 60.0, 30.0)
    assert x["Total Occupation (s)"] == 110.0
    assert x["Station"] == "Station A"
    assert x["Segments"] == "PLT_X@s1, PLT_X@s2, PLT_X@s3"
    y = df.iloc[1]
    assert (y["Total Occupation (s)"], y["Segments"]) == (80.0, "PLT_Y@s1")


@pytest.mark.unit
def test_12_footnote_listing():
    from headway.reporting.excel_export import ExcelReportExporter

    tbl = create_platform_occupation_table(_records())
    note = tbl.metadata["footnote"]
    assert "PLT_X = PLT_X@s1, PLT_X@s2, PLT_X@s3 (occupied: PLT_X@s2)" in note
    assert "PLT_Y = PLT_Y@s1 (occupied: PLT_Y@s1)" in note
    # Excel export carries the footnote below the table (HTML/PDF render metadata["footnote"]).
    wb = openpyxl.Workbook()
    ExcelReportExporter._populate_table_sheet(wb.active, tbl)
    assert any(isinstance(c.value, str) and "PLT_X@s2" in c.value and c.value.startswith("Segments:")
               for row in wb.active.iter_rows() for c in row)


# ---------------------------------------------------------------------------
# 13–14: stability and migration
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_13_deterministic_ids():
    spans = [_span("PLT_B", 0.450, 0.650, 60.0), _span("PLT_A", 0.100, 0.400)]
    tracks = [{"track_id": "TRK_A"}]
    stations = [{"station_id": "STN_A"}]

    def run(links):
        return [(_geom(r), r.stop_segment_id, r.stopping_point.stopping_point_id)
                for r in segment_all_platform_spans(spans, tracks, links, stations)]

    first = run(LINKS)
    rng = random.Random(1140)
    for _ in range(5):
        shuffled = LINKS[:]
        rng.shuffle(shuffled)
        assert run(shuffled) == first  # row order of TrackLinks does not matter
    assert [g[0] for g, _, _ in first] == [("PLT_B@s1", "LNK_A1", 450.0, 500.0, "PLT_B"), ("PLT_A@s1", "LNK_A1", 100.0, 400.0, "PLT_A")]
    assert [p[0] for p in first[0][0]] == ["PLT_B@s1", "PLT_B@s2", "PLT_B@s3"]


@pytest.mark.unit
def test_14_migration_helper_roundtrip(tmp_path):
    """Worked example of docs/MIGRATION_v1.14.0.md: 4 legacy rows -> 1 span -> same 4 segments."""
    mig = _load_helper()
    lengths = {"LNK_09": 1000, "LNK_10": 500, "LNK_11": 80, "LNK_12": 120, "LNK_13": 300}
    legacy_plats = [("PLT_CEN_1_1", "LNK_10", 380, 500), ("PLT_CEN_1_2", "LNK_11", 0, 80),
                    ("PLT_CEN_1_3", "LNK_12", 0, 120), ("PLT_CEN_1_4", "LNK_13", 0, 80)]

    src = tmp_path / "HEADWAY_INFRASTRUCTURE_T.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Tracks"
    wb["Tracks"].append(["TRACK_ID"]); wb["Tracks"].append(["TRK_UP"])
    ws = wb.create_sheet("TrackLinks")
    ws.append(["LINK_ID", "TRACK_ID", "START_NODE_ID", "END_NODE_ID", "LENGTH_M"])
    ws.append(["(Required)", "(Required)", "(Required)", "(Required)", "[m]"])
    for i, (lid, ln) in enumerate(lengths.items()):
        ws.append([lid, "TRK_UP", f"N{i}", f"N{i + 1}", ln])
    ws = wb.create_sheet("Platforms")
    ws.append(["PLATFORM_ID", "STATION_ID", "LINK_ID", "START_OFFSET_M", "END_OFFSET_M", "LENGTH_M"])
    for pid, lid, so, eo in legacy_plats:
        ws.append([pid, "STN_CEN", lid, so, eo, eo - so])
    ws = wb.create_sheet("StoppingPoints")
    ws.append(["STOPPING_POINT_ID", "PLATFORM_ID", "LINK_ID", "OFFSET_M"])
    ws.append(["SP_CEN_1", "PLT_CEN_1_4", "LNK_13", 70])
    wb.save(src)
    ops = tmp_path / "HEADWAY_OPERATIONS_T.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "StoppingPatterns"
    wb.active.append(["SERVICE_PATTERN_ID", "STOP_INDEX", "STATION_ID", "PLATFORM_ID", "DWELL_TIME_S"])
    wb.active.append(["SRV_1", 1, "STN_CEN", "PLT_CEN_1_4", 30])
    wb.save(ops)
    before = src.read_bytes()

    result = mig.migrate_workbooks(src, ops, out_dir=tmp_path / "out")
    assert src.read_bytes() == before  # original untouched
    assert [(s.platform_id, round(s.start_m, 6), round(s.end_m, 6), s.segment_hint_offset_m) for s in result.spans] == [
        ("PLT_CEN_1", 1380.0, 1780.0, 390.0)
    ]
    assert result.id_map == {p[0]: "PLT_CEN_1" for p in legacy_plats}

    out = openpyxl.load_workbook(tmp_path / "out" / src.name, data_only=True)
    assert "Platforms" not in out.sheetnames and "StoppingPoints" not in out.sheetnames
    rows = list(out["PlatformSpans"].iter_rows(values_only=True))
    assert rows[0][:6] == ("PLATFORM_ID", "STATION_ID", "TRACK_ID", "START_CHAINAGE_KM", "END_CHAINAGE_KM", "SEGMENT_HINT_OFFSET_M")
    span_row = dict(zip([h.lower() for h in rows[0]], rows[2]))
    assert (span_row["start_chainage_km"], span_row["end_chainage_km"], span_row["segment_hint_offset_m"]) == (1.38, 1.78, 390)
    ops_out = openpyxl.load_workbook(tmp_path / "out" / ops.name, data_only=True)
    assert ops_out["StoppingPatterns"].cell(2, 4).value == "PLT_CEN_1"

    # Roundtrip: the importer's segmentation of the migrated span reproduces the legacy rows.
    links = [{"link_id": lid, "track_id": "TRK_UP", "start_node_id": f"N{i}", "end_node_id": f"N{i + 1}", "length_m": float(ln)}
             for i, (lid, ln) in enumerate(lengths.items())]
    seg = segment_platform_span(span_row, track_chainage_frame(links, "TRK_UP"), {"STN_CEN"}, {"TRK_UP"})
    assert [(p.link_id, p.start_offset_m, p.end_offset_m) for p in seg.segments] == [(l, float(s), float(e)) for _, l, s, e in legacy_plats]
    assert [p.platform_id for p in seg.segments] == ["PLT_CEN_1@s1", "PLT_CEN_1@s2", "PLT_CEN_1@s3", "PLT_CEN_1@s4"]
    assert (seg.stop_segment_id, seg.stopping_point.link_id, seg.stopping_point.offset_m) == ("PLT_CEN_1@s4", "LNK_13", 70.0)
