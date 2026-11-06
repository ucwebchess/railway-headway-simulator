"""v1.14.0 — every PlatformSpans error code is raised with the offending ID and the guide pointer.

Complements tests/unit/test_v1140_platform_spans.py (the 14 PR acceptance tests) with the
codes not exercised there: ERR_PLATFORM_SPAN_INVALID (each cause), ERR_PLATFORM_SPAN_DUPLICATE,
ERR_PLATFORM_NOMINAL_STOP_INVALID, plus the dataset validator's dry-run findings, the
shipped template and the migrated examples.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import openpyxl
import pytest

from headway.core.exceptions import DataValidationError
from headway.data.importer import RawWorkbookData
from headway.data.platform_spans import (
    ALL_PLATFORM_SPAN_ERROR_CODES,
    ERR_PLATFORM_NOMINAL_STOP_INVALID,
    ERR_PLATFORM_SPAN_DUPLICATE,
    ERR_PLATFORM_SPAN_EXCEEDS_TRACK,
    ERR_PLATFORM_SPAN_INVALID,
    MIGRATION_GUIDE,
    PlatformSpanError,
    segment_all_platform_spans,
)
from headway.data.validation import ValidationReport
from headway.data.validator import DatasetValidator

ROOT = Path(__file__).resolve().parents[2]
LINKS = [
    {"link_id": "LNK_1", "track_id": "TRK_A", "start_node_id": "N1", "end_node_id": "N2", "length_m": 300.0},
    {"link_id": "LNK_2", "track_id": "TRK_A", "start_node_id": "N2", "end_node_id": "N3", "length_m": 200.0},
]
TRACKS = [{"track_id": "TRK_A"}]
STATIONS = [{"station_id": "STN_A"}]


def _span(pid: str = "PLT_1", **kw: Any) -> Dict[str, Any]:
    d = {"platform_id": pid, "station_id": "STN_A", "track_id": "TRK_A",
         "start_chainage_km": 0.1, "end_chainage_km": 0.4, "nominal_stop_offset_m": None}
    d.update(kw)
    return d


def _raises(spans, code: str, oid: str) -> PlatformSpanError:
    with pytest.raises(PlatformSpanError) as exc:
        segment_all_platform_spans(spans, TRACKS, LINKS, STATIONS)
    err = exc.value
    assert err.error_code == code
    assert oid in str(err) and MIGRATION_GUIDE in str(err)
    return err


@pytest.mark.unit
@pytest.mark.parametrize(
    "kw",
    [
        {"start_chainage_km": 0.4, "end_chainage_km": 0.1},       # START >= END
        {"start_chainage_km": 0.2, "end_chainage_km": 0.2},       # zero length
        {"start_chainage_km": 0.200, "end_chainage_km": 0.205},   # 5 m < 10 m minimum
        {"station_id": "STN_NOPE"},                               # unknown station
        {"track_id": "TRK_NOPE"},                                 # unknown track
    ],
)
def test_span_invalid_causes(kw):
    _raises([_span(**kw)], ERR_PLATFORM_SPAN_INVALID, "PLT_1")


@pytest.mark.unit
def test_span_minimum_length_boundary_is_accepted():
    res = segment_all_platform_spans([_span(start_chainage_km=0.2, end_chainage_km=0.21)], TRACKS, LINKS, STATIONS)
    assert [p.length_m for p in res[0].segments] == [pytest.approx(10.0)]


@pytest.mark.unit
def test_span_duplicate():
    _raises([_span("PLT_D"), _span("PLT_D", start_chainage_km=0.3, end_chainage_km=0.45)], ERR_PLATFORM_SPAN_DUPLICATE, "PLT_D")


@pytest.mark.unit
@pytest.mark.parametrize("off", [-1.0, 300.5])
def test_nominal_stop_outside_platform(off):
    _raises([_span(nominal_stop_offset_m=off)], ERR_PLATFORM_NOMINAL_STOP_INVALID, "PLT_1")


@pytest.mark.unit
def test_generated_style_id_rejected():
    from headway.data.canonical import PlatformSpan

    # Canonical model: '@' is not a valid identifier character.
    with pytest.raises(DataValidationError) as exc:
        PlatformSpan(**_span("PLT_1@s1"))
    assert "PLT_1@s1" in str(exc.value)
    # Segmentation path (importer/converter/validator): dedicated code.
    _raises([_span("PLT_1@s1")], ERR_PLATFORM_SPAN_INVALID, "PLT_1@s1")


@pytest.mark.unit
def test_validator_reports_every_bad_span():
    raw = RawWorkbookData("INFRASTRUCTURE", Path("infra.xlsx"), {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"})
    raw.worksheets["Tracks"] = TRACKS
    raw.worksheets["Stations"] = STATIONS
    raw.worksheets["TrackLinks"] = LINKS
    raw.worksheets["PlatformSpans"] = [
        _span("PLT_OK"),
        _span("PLT_LONG", start_chainage_km=0.3, end_chainage_km=0.6),
        _span("PLT_STOP", nominal_stop_offset_m=999.0),
        _span("PLT_OK", start_chainage_km=0.0, end_chainage_km=0.05),
    ]
    report = ValidationReport()
    DatasetValidator(report).validate_all({"INFRASTRUCTURE": raw})
    got = {(f.error_code, f.object_id) for f in report.findings if f.error_code in ALL_PLATFORM_SPAN_ERROR_CODES}
    assert got == {
        (ERR_PLATFORM_SPAN_EXCEEDS_TRACK, "PLT_LONG"),
        (ERR_PLATFORM_NOMINAL_STOP_INVALID, "PLT_STOP"),
        (ERR_PLATFORM_SPAN_DUPLICATE, "PLT_OK"),
    }


@pytest.mark.unit
def test_template_uses_platformspans_and_loads():
    from headway.ui.file_manager import FileManager

    wb = openpyxl.load_workbook(ROOT / "templates" / "HEADWAY_INFRASTRUCTURE_v1.0.xlsx", read_only=True)
    assert "PlatformSpans" in wb.sheetnames
    assert "Platforms" not in wb.sheetnames and "StoppingPoints" not in wb.sheetnames
    proj, report, _ = FileManager.import_excel_files(sorted(str(p) for p in (ROOT / "templates").glob("*.xlsx")))
    assert proj is not None, [f.message for f in report.findings if f.severity.name in ("CRITICAL", "ERROR")]
    assert [s.platform_id for s in proj.infrastructure.platform_spans] == ["PLT_01"]
    assert [(p.platform_id, p.parent_platform_id) for p in proj.infrastructure.platforms] == [("PLT_01@s1", "PLT_01")]


@pytest.mark.unit
@pytest.mark.parametrize("example", sorted(p.name for p in (ROOT / "examples").iterdir() if p.is_dir() and p.name[:2].isdigit()))
def test_examples_migrated(example):
    wb = openpyxl.load_workbook(ROOT / "examples" / example / "01_Infrastructure.xlsx", read_only=True)
    assert "PlatformSpans" in wb.sheetnames
    assert "Platforms" not in wb.sheetnames and "StoppingPoints" not in wb.sheetnames
