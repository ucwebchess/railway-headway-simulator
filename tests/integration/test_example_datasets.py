"""Integration tests verifying that all four official example datasets pass validation."""

from pathlib import Path
import pytest
from headway.data.converter import convert_raw_to_canonical
from headway.data.importer import ExcelImporter
from headway.data.validation import ValidationReport
from headway.data.validator import DatasetValidator


@pytest.mark.integration
@pytest.mark.parametrize(
    "example_dirname",
    [
        "01_single_track",
        "02_double_track",
        "03_station_platform",
        "04_tunnel_tvs",
    ],
)
def test_example_project_passes_validation(example_dirname: str):
    ex_path = Path("examples") / example_dirname
    assert ex_path.exists()

    importer = ExcelImporter()
    report = ValidationReport(project_id=example_dirname)
    raw_wbs = {}

    excel_files = list(ex_path.glob("*.xlsx"))
    assert len(excel_files) == 6, f"Example {example_dirname} should contain all 6 workbooks."

    for f in excel_files:
        raw_wb = importer.load_workbook(f, report)
        assert raw_wb is not None
        raw_wbs[raw_wb.workbook_type] = raw_wb

    validator = DatasetValidator(report)
    validator.validate_all(raw_wbs)

    # Invariant: No critical errors or blocking errors
    if report.has_errors:
        error_msgs = [f"[{f.error_code}] {f.message}" for f in report.findings if f.severity.value in ("CRITICAL", "ERROR")]
        pytest.fail(f"Example {example_dirname} has validation errors: {error_msgs}")

    assert report.is_simulation_ready

    # Verify canonical conversion succeeds
    project = convert_raw_to_canonical(raw_wbs)
    assert project.project_id is not None
    assert len(project.infrastructure.track_links) > 0
    assert len(project.rolling_stock.train_types) > 0
