"""File upload, template download, example project discovery, and ZIP packaging helpers.

Milestone P15 — File Management (P15-FILE-001 to P15-FILE-007).
"""

from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from headway.data.canonical import CanonicalProject
from headway.data.converter import convert_raw_to_canonical
from headway.data.importer import ExcelImporter, RawWorkbookData
from headway.data.package import ProjectPackage
from headway.data.template_generator import generate_all_templates
from headway.data.validation import ValidationReport
from headway.data.validator import DatasetValidator


class FileManager:
    """Provides high-level file operations for the Gradio interface."""

    @staticmethod
    def get_example_projects() -> Dict[str, Path]:
        """Discover available official example datasets."""
        examples_dir = Path("examples")
        if not examples_dir.exists():
            return {}

        found = {}
        for sub in sorted(examples_dir.iterdir()):
            if sub.is_dir() and list(sub.glob("*.xlsx")):
                found[sub.name] = sub
        return found

    @staticmethod
    def load_example_project(
        example_name: str,
    ) -> Tuple[CanonicalProject, ValidationReport, Dict[str, Path]]:
        """Load an official example project into canonical representation."""
        ex_map = FileManager.get_example_projects()
        if example_name not in ex_map:
            raise FileNotFoundError(f"Example project '{example_name}' not found. Available: {list(ex_map.keys())}")

        ex_dir = ex_map[example_name]
        importer = ExcelImporter()
        report = ValidationReport(project_id=example_name)
        raw_wbs: Dict[str, RawWorkbookData] = {}
        file_map: Dict[str, Path] = {}

        for f in sorted(ex_dir.glob("*.xlsx")):
            raw_wb = importer.load_workbook(f, report)
            if raw_wb:
                raw_wbs[raw_wb.workbook_type] = raw_wb
                file_map[raw_wb.workbook_type] = f

        validator = DatasetValidator(report)
        validator.validate_all(raw_wbs)

        project = convert_raw_to_canonical(raw_wbs)
        return project, report, file_map

    @staticmethod
    def import_excel_files(
        uploaded_files: List[Any],
    ) -> Tuple[Optional[CanonicalProject], ValidationReport, Dict[str, Path]]:
        """Load and validate an arbitrary set of uploaded Excel workbooks."""
        importer = ExcelImporter()
        report = ValidationReport(project_id="UPLOADED_PROJECT")
        raw_wbs: Dict[str, RawWorkbookData] = {}
        file_map: Dict[str, Path] = {}

        for item in uploaded_files:
            # Gradio may pass a file path str or file object
            f_path = Path(getattr(item, "name", str(item)))
            if not f_path.exists():
                continue

            raw_wb = importer.load_workbook(f_path, report)
            if raw_wb:
                raw_wbs[raw_wb.workbook_type] = raw_wb
                file_map[raw_wb.workbook_type] = f_path

        if raw_wbs:
            validator = DatasetValidator(report)
            validator.validate_all(raw_wbs)
            try:
                project = convert_raw_to_canonical(raw_wbs)
                return project, report, file_map
            except Exception as e:
                report.add_finding(
                    error_code="ERR_CONVERSION_FAILED",
                    severity=Severity.CRITICAL,
                    message=f"Failed to convert raw data to canonical model: {e}",
                )
                return None, report, file_map

        return None, report, file_map

    @staticmethod
    def import_project_zip(
        zip_file_path: Any,
    ) -> Tuple[CanonicalProject, Dict[str, Any], Dict[str, Path], ValidationReport]:
        """Safely import a project ZIP package."""
        if isinstance(zip_file_path, Path):
            p = zip_file_path
        elif hasattr(zip_file_path, "name"):
            p = Path(zip_file_path.name)
        else:
            p = Path(str(zip_file_path))

        temp_dest = Path(tempfile.mkdtemp(prefix="headway_imported_zip_"))
        project, manifest, excel_files = ProjectPackage.import_package(p, temp_dest)

        report = ValidationReport(project_id=project.project_id)
        return project, manifest, excel_files, report

    @staticmethod
    def export_project_zip(
        project: CanonicalProject,
        excel_workbooks: Optional[Dict[str, Path]] = None,
        validation_report: Optional[ValidationReport] = None,
    ) -> Path:
        """Create a complete downloadable project ZIP package."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="headway_export_"))
        out_zip = tmp_dir / f"Project_{project.project_id}.zip"
        return ProjectPackage.export_package(
            project=project,
            output_zip_path=out_zip,
            excel_workbooks=excel_workbooks,
            validation_report=validation_report,
        )

    @staticmethod
    def get_or_generate_templates_zip() -> Path:
        """Create or locate standard Excel templates ZIP package."""
        templates_dir = Path("templates")
        if templates_dir.exists() and list(templates_dir.glob("*.xlsx")):
            tmp_zip = Path(tempfile.gettempdir()) / "Railway_Headway_Templates.zip"
            shutil.make_archive(str(tmp_zip.with_suffix("")), "zip", templates_dir)
            return tmp_zip

        # Otherwise generate freshly
        out_dir = Path(tempfile.mkdtemp(prefix="headway_templates_"))
        generate_all_templates(out_dir)
        tmp_zip = Path(tempfile.gettempdir()) / "Railway_Headway_Templates.zip"
        shutil.make_archive(str(tmp_zip.with_suffix("")), "zip", out_dir)
        return tmp_zip


ProjectFileManager = FileManager

