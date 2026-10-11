"""Complete engineering report assessment package exporter.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 5, § 31).
Assembles a complete, auditable engineering package ZIP archive containing:
- PDF report (formal printable deliverable)
- HTML report (interactive browser document)
- Excel workbook (multi-sheet OOXML results)
- CSV tables directory (raw data tables)
- JSON results file (machine-readable schema)
- Metadata & provenance descriptor
- Static figure PNG images
"""

import json
from pathlib import Path
import tempfile
from typing import Optional, Union
import zipfile

from headway.reporting.csv_export import CsvReportExporter
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.export_static import export_figure_headless
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.json_export import JsonReportExporter
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_models import ReportDocument


class ReportPackageExporter:
    """Assembles and exports complete multi-format assessment ZIP archive."""

    @classmethod
    def export_package(
        cls,
        document: ReportDocument,
        output_zip_path: Union[str, Path],
        include_pdf: bool = True,
        include_html: bool = True,
        include_excel: bool = True,
        include_csv: bool = True,
        include_json: bool = True,
        include_figures: bool = True,
    ) -> Path:
        """Constructs the comprehensive assessment ZIP package."""
        target_zip = Path(output_zip_path)
        target_zip.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as staging_dir:
            stage_path = Path(staging_dir)

            # 1. HTML Report
            if include_html:
                html_path = stage_path / f"Report_{document.metadata.report_id}.html"
                HtmlReportRenderer.render(document, output_path=html_path)
                # Also write canonical report.html
                (stage_path / "report.html").write_text(html_path.read_text(encoding="utf-8"), encoding="utf-8")

            # 2. PDF Report
            if include_pdf:
                pdf_path = stage_path / f"Report_{document.metadata.report_id}.pdf"
                PdfReportRenderer.render(document, output_path=pdf_path)
                (stage_path / "report.pdf").write_bytes(pdf_path.read_bytes())

            # 3. Excel Workbook
            if include_excel:
                excel_path = stage_path / f"Results_{document.metadata.report_id}.xlsx"
                ExcelReportExporter.export(document, output_path=excel_path)
                (stage_path / "report.xlsx").write_bytes(excel_path.read_bytes())

            # 4. CSV Tables
            if include_csv:
                csv_dir = stage_path / "Tables_CSV"
                CsvReportExporter.export(document, output_dir=csv_dir)
                # Also provide canonical csv/ directory
                canon_csv_dir = stage_path / "csv"
                canon_csv_dir.mkdir(parents=True, exist_ok=True)
                for f in csv_dir.glob("*.csv"):
                    (canon_csv_dir / f.name).write_bytes(f.read_bytes())

            # 5. JSON Machine-Readable Results
            if include_json:
                json_path = stage_path / f"Results_{document.metadata.report_id}.json"
                JsonReportExporter.export(document, output_path=json_path)
                (stage_path / "report.json").write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")

            # 6. Static Figures
            if include_figures and document.figures_data:
                figs_dir = stage_path / "Figures"
                figs_dir.mkdir(parents=True, exist_ok=True)
                for f_key, fig_obj in document.figures_data.items():
                    if fig_obj is not None:
                        f_img_path = figs_dir / f"{f_key}.png"
                        try:
                            export_figure_headless(fig_obj, f_img_path, width=1200, height=600, dpi=200)
                        except Exception:
                            pass

            # 7. Metadata Manifest
            collected_files = [str(p.relative_to(stage_path)) for p in stage_path.rglob("*") if p.is_file()]
            manifest = {
                "package_id": document.metadata.report_id,
                "project_id": document.metadata.project_id,
                "scenario_id": document.metadata.scenario_id,
                "run_id": document.metadata.simulation_run_id,
                "running_direction": document.running_direction.value,
                "software_version": document.metadata.software_version,
                "config_hash": document.metadata.input_configuration_hash,
                "effective_config_hash": document.metadata.input_configuration_hash,
                "generation_timestamp": document.metadata.generation_time,
                "files": collected_files,
            }
            meta_json = json.dumps(manifest, indent=2)
            (stage_path / "Package_Manifest.json").write_text(meta_json, encoding="utf-8")
            (stage_path / "manifest.json").write_text(meta_json, encoding="utf-8")

            # Create ZIP Archive
            with zipfile.ZipFile(target_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for file_path in stage_path.rglob("*"):
                    if file_path.is_file():
                        rel_path = file_path.relative_to(stage_path)
                        zf.write(file_path, arcname=str(rel_path))

        return target_zip
