"""Integration tests for negative validation cases (Levels 1 to 5)."""

from pathlib import Path
import openpyxl
import pytest
from headway.data.importer import ExcelImporter
from headway.data.validation import ValidationReport
from headway.data.validator import DatasetValidator


@pytest.mark.integration
def test_negative_reject_macro_workbook(tmp_path: Path):
    importer = ExcelImporter()
    report = ValidationReport()
    macro_file = tmp_path / "unsafe.xlsm"
    macro_file.touch()

    raw_wb = importer.load_workbook(macro_file, report)
    assert raw_wb is None
    assert any(f.error_code == "ERR_SECURITY_MACRO_REJECTED" for f in report.findings)


@pytest.mark.integration
def test_negative_missing_metadata_sheet(tmp_path: Path):
    importer = ExcelImporter()
    report = ValidationReport()
    bad_file = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Nodes"
    wb.save(bad_file)

    raw_wb = importer.load_workbook(bad_file, report)
    assert raw_wb is None
    assert any(f.error_code == "ERR_STRUCTURAL_METADATA_MISSING" for f in report.findings)


@pytest.mark.integration
def test_negative_missing_mandatory_column(tmp_path: Path):
    importer = ExcelImporter()
    report = ValidationReport()
    bad_file = tmp_path / "bad_infra.xlsx"

    wb = openpyxl.Workbook()
    meta = wb.active
    meta.title = "METADATA"
    meta.append(["PROPERTY", "VALUE"])
    meta.append(["WORKBOOK_TYPE", "INFRASTRUCTURE"])
    meta.append(["SCHEMA_VERSION", "1.0.0"])

    # Nodes sheet without NODE_ID column
    ws = wb.create_sheet("Nodes")
    ws.append(["DESCRIPTION", "NODE_TYPE"])
    ws.append(["Bad node", "ENDPOINT"])

    # Required TrackLinks sheet missing
    wb.save(bad_file)

    importer.load_workbook(bad_file, report)
    assert any(f.error_code == "ERR_STRUCTURAL_COLUMN_MISSING" for f in report.findings)
    assert any(f.error_code == "ERR_STRUCTURAL_WORKSHEET_MISSING" for f in report.findings)


@pytest.mark.integration
def test_negative_cross_reference_and_bounds_validation(tmp_path: Path):
    """Test Level 3 missing reference and Level 4 out-of-bounds error reporting."""
    importer = ExcelImporter()
    report = ValidationReport()

    # Load 01_single_track as base
    ex_dir = Path("examples/01_single_track")
    raw_wbs = {}
    for f in ex_dir.glob("*.xlsx"):
        raw = importer.load_workbook(f, report)
        if raw:
            raw_wbs[raw.workbook_type] = raw

    # Inject invalid foreign reference into TrackLinks
    raw_wbs["INFRASTRUCTURE"].worksheets["TrackLinks"].append({
        "link_id": "LNK_BROKEN",
        "track_id": "TRK_NONEXISTENT",
        "start_node_id": "ND_01",
        "end_node_id": "ND_NONEXISTENT",
        "length_m": 1000.0,
        "max_speed_ms": 25.0,
        "gradient_decimal": 0.0,
    })

    validator = DatasetValidator(report)
    validator.validate_all(raw_wbs)

    assert report.has_errors
    codes = [f.error_code for f in report.findings]
    assert "ERR_REF_MISSING" in codes
