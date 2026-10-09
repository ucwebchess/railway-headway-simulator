"""Integration tests for template generation, Excel import, and canonical conversion."""

from pathlib import Path
import pytest
from headway.data.converter import convert_raw_to_canonical
from headway.data.excel_registry import ALL_WORKBOOK_DEFS
from headway.data.importer import ExcelImporter
from headway.data.template_generator import generate_all_templates
from headway.data.validation import ValidationReport
from headway.data.validator import DatasetValidator


@pytest.mark.integration
def test_template_generation_and_load(tmp_path: Path):
    templates = generate_all_templates(tmp_path)
    assert len(templates) == 6

    importer = ExcelImporter()
    for t_path in templates:
        report = ValidationReport()
        raw_wb = importer.load_workbook(t_path, report)
        assert raw_wb is not None
        assert raw_wb.workbook_type in ALL_WORKBOOK_DEFS
        # Template itself should not contain critical structural errors
        assert not report.has_critical
