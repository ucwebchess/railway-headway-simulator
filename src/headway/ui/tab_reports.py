"""Tab 10: Reports & Export Hub for Railway Headway Simulator.

Milestone P15 — Multi-Format Generation & Deliverable Packaging (P15-TAB-010, P15-REP-001 to P15-REP-008).
Consumes P14 reporting subsystem directly without modifying core engineering data.
"""

from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import zipfile
import gradio as gr

from headway.reporting.csv_export import CsvReportExporter
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.json_export import JsonReportExporter
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_assembly import ReportAssembler, ReportSectionId, ReportType
from headway.reporting.report_config import ReportConfig
from headway.reporting.report_package import ReportPackageExporter
from headway.ui.error_handling import create_error_html, create_success_html, format_exception_for_ui
from headway.ui.state import session_state


ALL_SECTIONS = [s.value for s in ReportSectionId]


def create_reports_tab() -> Dict[str, Any]:
    """Constructs Tab 10: Reports & Export Hub components and event bindings."""
    components = {}

    with gr.Column():
        gr.Markdown("### Engineering Reports, Audit Packages & State Archival")
        gr.Markdown(
            "Configure, preview, and download formal multi-format engineering assessments. "
            "P15-REP-001: End users can generate and download comprehensive deliverables without code execution."
        )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### Report Configuration")
                components["rep_type_dropdown"] = gr.Dropdown(
                    label="Assessment Template / Type",
                    choices=[t.value for t in ReportType],
                    value=ReportType.DETAILED_ENGINEERING.value,
                )
                components["rep_title_input"] = gr.Textbox(
                    label="Report Title",
                    value="Railway Headway & Line Capacity Assessment",
                )
                components["rep_author_input"] = gr.Textbox(
                    label="Lead Engineer / Author",
                    value="Lead Operations Planning Engineer",
                )
                components["rep_sections_checkboxes"] = gr.CheckboxGroup(
                    label="Included Report Sections",
                    choices=ALL_SECTIONS,
                    value=[
                        ReportSectionId.EXECUTIVE_SUMMARY.value,
                        ReportSectionId.SPEED_GRADIENT_CURVATURE.value,
                        ReportSectionId.BLOCKING_STAIRWAY.value,
                        ReportSectionId.SEVEN_COMPONENT_BREAKDOWN.value,
                        ReportSectionId.CONFLICT_RANKING.value,
                        ReportSectionId.LONGEST_OCCUPATIONS.value,
                        ReportSectionId.STATION_PLATFORM_OCCUPATION.value,
                        ReportSectionId.MIXED_TRAFFIC_MATRIX.value,
                        ReportSectionId.TVS_ASSESSMENT.value,
                        ReportSectionId.BLOCK_LENGTH_SENSITIVITY.value,
                        ReportSectionId.STOCHASTIC_RELIABILITY.value,
                        ReportSectionId.SCENARIO_COMPARISON.value,
                        ReportSectionId.CONCLUSIONS_RECOMMENDATIONS.value,
                    ],
                )
                components["btn_generate_report"] = gr.Button("📑 Assemble & Preview Report", variant="primary")

            with gr.Column(scale=1):
                gr.Markdown("#### Download Deliverables")
                with gr.Row():
                    components["btn_download_pkg"] = gr.Button("📦 Complete Assessment ZIP Package", variant="primary")
                with gr.Row():
                    components["btn_download_pdf"] = gr.Button("📄 Formal PDF Report", variant="secondary")
                    components["btn_download_xlsx"] = gr.Button("📊 Excel Assessment (.xlsx)", variant="secondary")
                with gr.Row():
                    components["btn_download_csv"] = gr.Button("📁 CSV Tables (.zip)", variant="secondary")
                    components["btn_download_json"] = gr.Button("📑 JSON Report (.json)", variant="secondary")

                components["download_file_output"] = gr.File(label="Generated Deliverable File", visible=False)
                components["rep_status_msg"] = gr.HTML()

                gr.Markdown("---")
                gr.Markdown("#### Project State Backup & Restoration")
                with gr.Row():
                    components["btn_backup_project"] = gr.Button("💾 Backup Entire Project (.zip)", variant="secondary")
                components["project_backup_file"] = gr.File(label="Project Backup Ready", visible=False)

                components["restore_project_file"] = gr.File(
                    label="Restore Project from ZIP (.zip)",
                    file_types=[".zip"],
                    file_count="single",
                )
                components["restore_status_msg"] = gr.HTML()

        gr.Markdown("---")
        gr.Markdown("#### Report Interactive HTML Preview")
        components["html_preview_frame"] = gr.HTML(
            value="<div style='padding: 24px; text-align: center; color: #64748b; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px;'>Click 'Assemble & Preview Report' above after running simulation.</div>"
        )

    # Event Handlers
    def assemble_and_preview(
        report_type_str: str,
        title: str,
        author: str,
        selected_sections: List[str],
    ) -> Tuple[str, str]:
        pkg = session_state.latest_result_package
        if not pkg:
            msg = create_error_html(
                "No Simulation Results",
                "Execute simulation in Tab 8 before assembling reports.",
            )
            return msg, "<div style='padding: 20px; color: #DC2626;'>No active simulation results to preview.</div>"

        try:
            sec_enums = [ReportSectionId(s) for s in selected_sections if s in ALL_SECTIONS]
            cfg = ReportConfig(
                report_type=ReportType(report_type_str),
                running_direction=pkg.running_direction,
                included_sections=sec_enums,
                title=title or "Railway Headway & Line Capacity Assessment",
                author=author or "Lead Operations Planning Engineer",
                project_name=session_state.project_id or "Railway Corridors",
            )

            doc = ReportAssembler.assemble_report(package=pkg, config=cfg)
            session_state.latest_report_doc = doc

            html_content = HtmlReportRenderer.render(doc, embed_interactive_plotly=True)
            # Wrap in scrollable container for Gradio preview
            preview_html = f"""
                <div style="max-height: 800px; overflow-y: auto; border: 1px solid #cbd5e1; border-radius: 8px; padding: 16px; background: #ffffff;">
                    {html_content}
                </div>
            """
            success_msg = create_success_html(
                "Report Assembled Successfully",
                f"Generated report '{doc.metadata.report_id}' with {len(doc.sections)} sections in direction {pkg.running_direction.value}.",
            )
            return success_msg, preview_html
        except Exception as exc:
            err = format_exception_for_ui(exc, context="Report Assembly")
            return err.to_html(), f"<div style='padding: 20px; color: #DC2626;'>Error: {err.user_message}</div>"

    components["btn_generate_report"].click(
        fn=assemble_and_preview,
        inputs=[
            components["rep_type_dropdown"],
            components["rep_title_input"],
            components["rep_author_input"],
            components["rep_sections_checkboxes"],
        ],
        outputs=[components["rep_status_msg"], components["html_preview_frame"]],
    )

    def download_complete_package() -> Tuple[Any, str]:
        doc = session_state.latest_report_doc
        if not doc:
            return gr.update(visible=False), create_error_html(
                "No Report Document", "Assemble or preview a report first."
            )
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="headway_pkg_"))
            pkg_path = tmp_dir / f"Assessment_Package_{doc.metadata.report_id}.zip"
            ReportPackageExporter.export_package(
                document=doc,
                output_zip_path=pkg_path,
                include_pdf=True,
                include_html=True,
                include_excel=True,
                include_csv=True,
                include_json=True,
                include_figures=True,
            )
            return gr.update(value=str(pkg_path), visible=True), create_success_html(
                "Complete Package Generated", f"ZIP archive created at {pkg_path.name}"
            )
        except Exception as exc:
            err = format_exception_for_ui(exc, context="ZIP Package Export")
            return gr.update(visible=False), err.to_html()

    components["btn_download_pkg"].click(
        fn=download_complete_package,
        inputs=[],
        outputs=[components["download_file_output"], components["rep_status_msg"]],
    )

    def download_pdf() -> Tuple[Any, str]:
        doc = session_state.latest_report_doc
        if not doc:
            return gr.update(visible=False), create_error_html(
                "No Report Document", "Assemble or preview a report first."
            )
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="headway_pdf_"))
            pdf_path = tmp_dir / f"Report_{doc.metadata.report_id}.pdf"
            PdfReportRenderer.render(doc, output_path=pdf_path)
            return gr.update(value=str(pdf_path), visible=True), create_success_html(
                "PDF Rendered", f"Exported formal PDF: {pdf_path.name}"
            )
        except Exception as exc:
            err = format_exception_for_ui(exc, context="PDF Rendering")
            return gr.update(visible=False), err.to_html()

    components["btn_download_pdf"].click(
        fn=download_pdf,
        inputs=[],
        outputs=[components["download_file_output"], components["rep_status_msg"]],
    )

    def download_xlsx() -> Tuple[Any, str]:
        doc = session_state.latest_report_doc
        if not doc:
            return gr.update(visible=False), create_error_html(
                "No Report Document", "Assemble or preview a report first."
            )
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="headway_xlsx_"))
            xlsx_path = tmp_dir / f"Report_{doc.metadata.report_id}.xlsx"
            ExcelReportExporter.export(doc, output_path=xlsx_path)
            return gr.update(value=str(xlsx_path), visible=True), create_success_html(
                "Excel Exported", f"Exported engineering workbook: {xlsx_path.name}"
            )
        except Exception as exc:
            err = format_exception_for_ui(exc, context="Excel Export")
            return gr.update(visible=False), err.to_html()

    components["btn_download_xlsx"].click(
        fn=download_xlsx,
        inputs=[],
        outputs=[components["download_file_output"], components["rep_status_msg"]],
    )

    def download_csv_zip() -> Tuple[Any, str]:
        doc = session_state.latest_report_doc
        if not doc:
            return gr.update(visible=False), create_error_html(
                "No Report Document", "Assemble or preview a report first."
            )
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="headway_csv_"))
            csv_dir = tmp_dir / "csvs"
            csv_dir.mkdir(parents=True, exist_ok=True)
            CsvReportExporter.export(doc, output_dir=csv_dir)
            zip_path = tmp_dir / f"CSV_Tables_{doc.metadata.report_id}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in csv_dir.glob("*.csv"):
                    zf.write(f, arcname=f.name)
            return gr.update(value=str(zip_path), visible=True), create_success_html(
                "CSV Archive Created", f"Packaged CSV tables into {zip_path.name}"
            )
        except Exception as exc:
            err = format_exception_for_ui(exc, context="CSV Export")
            return gr.update(visible=False), err.to_html()

    components["btn_download_csv"].click(
        fn=download_csv_zip,
        inputs=[],
        outputs=[components["download_file_output"], components["rep_status_msg"]],
    )

    def download_json() -> Tuple[Any, str]:
        doc = session_state.latest_report_doc
        if not doc:
            return gr.update(visible=False), create_error_html(
                "No Report Document", "Assemble or preview a report first."
            )
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="headway_json_"))
            json_path = tmp_dir / f"Report_{doc.metadata.report_id}.json"
            JsonReportExporter.export(doc, output_path=json_path)
            return gr.update(value=str(json_path), visible=True), create_success_html(
                "JSON Generated", f"Exported structured JSON: {json_path.name}"
            )
        except Exception as exc:
            err = format_exception_for_ui(exc, context="JSON Export")
            return gr.update(visible=False), err.to_html()

    components["btn_download_json"].click(
        fn=download_json,
        inputs=[],
        outputs=[components["download_file_output"], components["rep_status_msg"]],
    )

    def backup_project() -> Tuple[Any, str]:
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="headway_backup_"))
            pid = session_state.project_id or "Headway_Project"
            backup_path = tmp_dir / f"{pid}_backup.zip"
            session_state.export_project_zip(backup_path)
            return gr.update(value=str(backup_path), visible=True), create_success_html(
                "Project Backed Up", f"Complete session archive exported to {backup_path.name}"
            )
        except Exception as exc:
            err = format_exception_for_ui(exc, context="Project Backup")
            return gr.update(visible=False), err.to_html()

    components["btn_backup_project"].click(
        fn=backup_project,
        inputs=[],
        outputs=[components["project_backup_file"], components["rep_status_msg"]],
    )

    def restore_project(file_obj: Any) -> str:
        if not file_obj:
            return create_error_html("No File Provided", "Upload a project ZIP archive to restore.")
        try:
            path = Path(file_obj.name if hasattr(file_obj, "name") else str(file_obj))
            session_state.import_project_zip(path)
            return create_success_html(
                "Project Restored Successfully",
                f"Project '{session_state.project_id}' restored from archive with {len(session_state.scenarios)} scenarios.",
            )
        except Exception as exc:
            err = format_exception_for_ui(exc, context="Project Restoration")
            return err.to_html()

    components["restore_project_file"].upload(
        fn=restore_project,
        inputs=[components["restore_project_file"]],
        outputs=[components["restore_status_msg"]],
    )

    return components
