"""Integration tests for project ZIP export, restoration, and safety guards."""

from pathlib import Path
import pytest
from headway.core.exceptions import DataValidationError
from headway.data.converter import convert_raw_to_canonical
from headway.data.importer import ExcelImporter
from headway.data.package import ProjectPackage
from headway.data.validation import ValidationReport


@pytest.mark.integration
def test_project_package_export_and_import_roundtrip(tmp_path: Path):
    ex_dir = Path("examples/01_single_track")
    importer = ExcelImporter()
    report = ValidationReport()

    raw_wbs = {}
    wb_files = {}
    for f in ex_dir.glob("*.xlsx"):
        raw = importer.load_workbook(f, report)
        if raw:
            raw_wbs[raw.workbook_type] = raw
            wb_files[f.name] = f

    project = convert_raw_to_canonical(raw_wbs)

    zip_file = tmp_path / "test_project.zip"
    ProjectPackage.export_package(
        project=project,
        output_zip_path=zip_file,
        excel_workbooks=wb_files,
        validation_report=report,
    )
    assert zip_file.exists()

    # Re-import from zip
    extract_dir = tmp_path / "unpacked"
    reloaded_project, manifest, extracted_excel = ProjectPackage.import_package(zip_file, extract_dir)

    assert reloaded_project.project_id == project.project_id
    assert len(reloaded_project.infrastructure.track_links) == len(project.infrastructure.track_links)
    assert len(extracted_excel) == len(wb_files)
    assert manifest["project_id"] == project.project_id


@pytest.mark.integration
def test_project_package_rejects_unsafe_traversal(tmp_path: Path):
    import zipfile
    unsafe_zip = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe_zip, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:")
        zf.writestr("canonical_project.json", "{}")

    extract_dir = tmp_path / "unsafe_extracted"
    with pytest.raises(DataValidationError) as exc:
        ProjectPackage.import_package(unsafe_zip, extract_dir)
    assert exc.value.error_code == "ERR_SECURITY_ZIP_PATH_TRAVERSAL"
