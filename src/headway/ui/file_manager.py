"""File upload, template download, example project discovery, and ZIP packaging helpers.

Milestone P15 — File Management (P15-FILE-001 to P15-FILE-007).
"""

import base64
import mimetypes
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

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
            alt_dir = Path(__file__).resolve().parent.parent.parent.parent / "examples"
            if alt_dir.exists():
                examples_dir = alt_dir
            elif Path("/content/railway-headway-simulator/examples").exists():
                examples_dir = Path("/content/railway-headway-simulator/examples")
            else:
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

    @staticmethod
    def create_base64_download_link(
        file_path: Union[str, Path],
        label: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> str:
        """Create a self-contained HTML download card with embedded base64 data URI.

        Bypasses Gradio internal host URLs to work reliably in Google Colab with share=False.
        """
        p = Path(file_path)
        if not p.exists():
            return f"<div style='color: #dc2626;'>File not found: {p.name}</div>"

        data = p.read_bytes()
        b64_str = base64.b64encode(data).decode("utf-8")

        # Determine MIME type
        if mime_type is None:
            ext = p.suffix.lower()
            mime_map = {
                ".zip": "application/zip",
                ".pdf": "application/pdf",
                ".html": "text/html;charset=utf-8",
                ".htm": "text/html;charset=utf-8",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".json": "application/json",
                ".csv": "text/csv;charset=utf-8",
            }
            mime_type = mime_map.get(ext) or mimetypes.guess_type(str(p))[0] or "application/octet-stream"

        filename = p.name
        btn_label = label or f"Download {filename}"
        size_kb = len(data) / 1024.0
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{(size_kb / 1024.0):.2f} MB"

        return (
            f'<div class="headway-download-card" style="margin: 10px 0; padding: 12px 16px; '
            f'background: #F0FDF4; border: 1px solid #86EFAC; border-radius: 8px; display: inline-block;">'
            f'<div style="font-size: 13px; font-weight: 600; color: #166534; margin-bottom: 6px;">'
            f'✅ Ready for Download ({size_str})</div>'
            f'<a download="{filename}" href="data:{mime_type};base64,{b64_str}" '
            f'style="display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; '
            f'background: #1B365D; color: #FFFFFF; font-weight: 600; font-size: 14px; text-decoration: none; '
            f'border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); cursor: pointer;" '
            f'target="_blank">'
            f'📥 {btn_label}'
            f'</a>'
            f'</div>'
        )


ProjectFileManager = FileManager

