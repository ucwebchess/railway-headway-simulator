"""Tab 2: Data Import for Railway Headway Simulator.

Milestone P15 — UI Integration (P15-TAB-002, P15-FILE-001 to P15-FILE-007).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import gradio as gr

from headway.ui.error_handling import create_error_html, create_success_html
from headway.ui.file_manager import FileManager
from headway.ui.state import session_state


def create_data_import_tab() -> Dict[str, Any]:
    """Constructs Tab 2: Data Import components and event bindings."""
    components = {}

    with gr.Column():
        gr.Markdown("### Railway Dataset Ingestion & Project Loading")
        gr.Markdown(
            "Load complete railway simulation projects by choosing an official example project, "
            "uploading an exported project ZIP package, or uploading individual standardized Excel workbooks."
        )

        with gr.Row():
            # Section A: Pre-loaded Examples
            with gr.Column(scale=1):
                gr.Markdown("#### Option A: Load Official Example Project")
                ex_map = FileManager.get_example_projects()
                ex_names = list(ex_map.keys()) if ex_map else ["01_single_track", "02_double_track", "03_station_platform", "04_tunnel_tvs", "05_comprehensive_line"]

                components["example_dropdown"] = gr.Dropdown(
                    choices=ex_names,
                    value=ex_names[0] if ex_names else None,
                    label="Select Verified Example Dataset",
                    info="Standard test datasets covering single/double track, platforms, and TVS.",
                )
                components["btn_load_example"] = gr.Button("📂 Load Selected Example", variant="primary")

                gr.Markdown("---")
                gr.Markdown("#### Option B: Standard Excel Templates")
                gr.Markdown("Download empty standardized workbooks to build custom projects.")
                components["btn_download_templates"] = gr.Button("📥 Download Workbook Templates (.zip)", variant="secondary")
                components["template_file_download"] = gr.File(label="Template Archive Ready", visible=False)

            # Section B: File Uploads
            with gr.Column(scale=1):
                gr.Markdown("#### Option C: Upload Custom Dataset")
                with gr.Tab("Upload Project ZIP"):
                    components["upload_zip"] = gr.File(
                        label="Upload Project ZIP Archive (.zip)",
                        file_types=[".zip"],
                        file_count="single",
                    )
                    components["btn_import_zip"] = gr.Button("📦 Unpack & Load Project ZIP", variant="primary")

                with gr.Tab("Upload Excel Workbooks"):
                    components["upload_excels"] = gr.File(
                        label="Upload Excel Workbooks (.xlsx)",
                        file_types=[".xlsx"],
                        file_count="multiple",
                    )
                    components["btn_import_excels"] = gr.Button("📑 Parse & Ingest Workbooks", variant="primary")

        # Ingestion Status & Feedback Box
        components["import_status_box"] = gr.HTML(
            "<div style='color: #64748B; font-size: 13px; margin: 8px 0;'>Ready for data ingestion.</div>"
        )

        with gr.Accordion("Dataset Ingestion Log", open=False):
            components["import_log_dataframe"] = gr.Dataframe(
                headers=["Dataset Component", "Source File", "Records Loaded", "Ingestion Status"],
                value=[],
                interactive=False,
            )

    # Event handlers
    def handle_load_example(ex_name: str) -> Tuple[str, List[List[str]]]:
        if not ex_name:
            return create_error_html({"category": "Input Error", "message": "No example project selected."}), []

        success, msg = session_state.load_example(ex_name)
        if not success:
            return create_error_html({"category": "Import Failed", "message": msg}), []

        proj = session_state.current_project
        stats = session_state.get_project_statistics()
        status_html = create_success_html(
            f"Successfully Loaded Example: {ex_name}",
            f"Project '{proj.name}' ({proj.project_id}) loaded with {stats['Track Links']} links, "
            f"{stats['Signalling Blocks']} blocks, and {stats['Train Types']} train types.",
        )

        log_data = [
            ["Infrastructure", f"examples/{ex_name}/01_Infrastructure.xlsx", f"{len(proj.infrastructure.track_links)} links", "Loaded (Verified)"],
            ["Signalling", f"examples/{ex_name}/02_Signalling.xlsx", f"{len(proj.signalling.blocks)} blocks", "Loaded (Verified)"],
            ["Rolling Stock", f"examples/{ex_name}/03_RollingStock.xlsx", f"{len(proj.rolling_stock.train_types)} train types", "Loaded (Verified)"],
            ["Operations", f"examples/{ex_name}/04_Operations.xlsx", f"{len(proj.operations.service_patterns)} services", "Loaded (Verified)"],
            ["Headway Analysis", f"examples/{ex_name}/05_HeadwayAnalysis.xlsx", f"{len(proj.analysis.analyses)} configs", "Loaded (Verified)"],
            ["Scenarios", f"examples/{ex_name}/06_Scenarios.xlsx", f"{len(proj.scenarios)} scenarios", "Loaded (Verified)"],
        ]

        return status_html, log_data

    components["btn_load_example"].click(
        fn=handle_load_example,
        inputs=[components["example_dropdown"]],
        outputs=[components["import_status_box"], components["import_log_dataframe"]],
    )

    def handle_import_zip(zip_file: Any) -> Tuple[str, List[List[str]]]:
        if not zip_file:
            return create_error_html({"category": "Input Error", "message": "No ZIP file provided."}), []

        try:
            proj, manifest, files, report = FileManager.import_project_zip(zip_file)
            session_state.set_project(proj, validation_report=report, source_files=files)
            stats = session_state.get_project_statistics()
            status_html = create_success_html(
                f"Successfully Imported ZIP Project: {proj.project_id}",
                f"Project '{proj.name}' restored. Schema version: {manifest.get('schema_version', '1.0.0')}. "
                f"Found {stats['Track Links']} track links.",
            )
            log_data = [[k, str(v.name), "Loaded from ZIP", "Verified"] for k, v in files.items()]
            return status_html, log_data
        except Exception as e:
            return create_error_html({"category": "ZIP Import Failed", "message": str(e)}), []

    components["btn_import_zip"].click(
        fn=handle_import_zip,
        inputs=[components["upload_zip"]],
        outputs=[components["import_status_box"], components["import_log_dataframe"]],
    )

    def handle_import_excels(file_list: List[Any]) -> Tuple[str, List[List[str]]]:
        if not file_list:
            return create_error_html({"category": "Input Error", "message": "No Excel files uploaded."}), []

        try:
            proj, report, files = FileManager.import_excel_files(file_list)
            if proj is None:
                err_msg = "; ".join([f.message for f in report.findings if f.severity.value in ("CRITICAL", "ERROR")])
                return create_error_html({"category": "Excel Ingestion Failed", "message": err_msg or "Failed to parse files."}), []

            session_state.set_project(proj, validation_report=report, source_files=files)
            stats = session_state.get_project_statistics()
            status_html = create_success_html(
                f"Successfully Ingested {len(files)} Workbooks",
                f"Project '{proj.name}' assembled. {stats['Track Links']} track links, {stats['Signalling Blocks']} blocks.",
            )
            log_data = [[k, str(v.name), "Extracted from Excel", "Parsed"] for k, v in files.items()]
            return status_html, log_data
        except Exception as e:
            return create_error_html({"category": "Excel Ingestion Error", "message": str(e)}), []

    components["btn_import_excels"].click(
        fn=handle_import_excels,
        inputs=[components["upload_excels"]],
        outputs=[components["import_status_box"], components["import_log_dataframe"]],
    )

    def handle_download_templates() -> Any:
        zip_path = FileManager.get_or_generate_templates_zip()
        return gr.update(value=str(zip_path), visible=True)

    components["btn_download_templates"].click(
        fn=handle_download_templates,
        inputs=[],
        outputs=[components["template_file_download"]],
    )

    return components
