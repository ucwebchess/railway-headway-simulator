"""Tab 1: Project Dashboard for Railway Headway Simulator.

Milestone P15 — UI Integration (P15-TAB-001).
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
import gradio as gr

from headway.core.configuration import AppConfig
from headway.ui.components import get_runtime_environment_summary
from headway.ui.state import session_state


def create_dashboard_tab(
    app_config: Optional[AppConfig] = None,
    on_switch_tab: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Constructs Tab 1: Project Dashboard components and event bindings."""
    if app_config is None:
        app_config = AppConfig()
    components = {}

    with gr.Column():
        gr.Markdown("### Project Overview & System Status")

        # Row 1: Project Info and Quick Status
        with gr.Row():
            components["project_name_text"] = gr.Textbox(
                label="Active Project Name",
                value=session_state.project_name,
                interactive=False,
                scale=2,
            )
            components["project_id_text"] = gr.Textbox(
                label="Project ID",
                value=session_state.project_id,
                interactive=False,
                scale=1,
            )
            components["validation_status_text"] = gr.Textbox(
                label="Validation Status",
                value="No Data Loaded",
                interactive=False,
                scale=1,
            )
            components["btn_refresh_dashboard_top"] = gr.Button("🔄 Refresh Dashboard", variant="secondary", scale=1)

        # Row 2: Headline KPIs (Microscopic Simulation)
        gr.Markdown("#### Key Performance Indicators (Microscopic Simulation)")
        with gr.Row():
            components["kpi_headway"] = gr.HTML(
                """
                <div class="kpi-card">
                    <div class="kpi-title">Technical Min Headway</div>
                    <div id="val_headway" style="font-size: 20px; font-weight: 700; color: #1B365D;">Not Run Yet</div>
                    <div style="font-size: 11px; color: #94a3b8;">Unimpeded leader-follower time</div>
                </div>
                """
            )
            components["kpi_theo_cap"] = gr.HTML(
                """
                <div class="kpi-card">
                    <div class="kpi-title">Theoretical Line Capacity</div>
                    <div id="val_theo_cap" style="font-size: 20px; font-weight: 700; color: #1B365D;">Not Run Yet</div>
                    <div style="font-size: 11px; color: #94a3b8;">Ideal homogeneous (C = 3600 / H)</div>
                </div>
                """
            )
            components["kpi_plan_cap"] = gr.HTML(
                """
                <div class="kpi-card">
                    <div class="kpi-title">Planning Operational Capacity</div>
                    <div id="val_plan_cap" style="font-size: 20px; font-weight: 700; color: #1B365D;">Not Run Yet</div>
                    <div style="font-size: 11px; color: #94a3b8;">With timetable planning margin</div>
                </div>
                """
            )
            components["kpi_bottleneck"] = gr.HTML(
                """
                <div class="kpi-card">
                    <div class="kpi-title">Controlling Bottleneck</div>
                    <div id="val_bottleneck" style="font-size: 20px; font-weight: 700; color: #1B365D;">Not Run Yet</div>
                    <div style="font-size: 11px; color: #94a3b8;">Critical headway governing point</div>
                </div>
                """
            )

        gr.Markdown("---")

        # Row 3: Statistics and Dataset Status
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### Project Model Statistics")
                stats = session_state.get_project_statistics()
                components["stats_dataframe"] = gr.Dataframe(
                    headers=["Metric", "Count / Value"],
                    value=[[k, v] for k, v in stats.items()],
                    interactive=False,
                    label="Infrastructure & Rolling Stock Quantities",
                )

            with gr.Column(scale=1):
                gr.Markdown("#### Dataset Ingestion & Readiness Status")
                ds_status = session_state.get_dataset_status()
                components["dataset_dataframe"] = gr.Dataframe(
                    headers=["Dataset Component", "Ingestion Status"],
                    value=[[k, v] for k, v in ds_status.items()],
                    interactive=False,
                    label="Workbook Ingestion Status",
                )

        gr.Markdown("---")

        # Row 4: Runtime Environment
        gr.Markdown("#### Runtime Environment & Architecture Diagnostic")
        with gr.Row():
            with gr.Column(scale=2):
                env_data = get_runtime_environment_summary(app_config)
                components["env_dataframe"] = gr.Dataframe(
                    headers=["System Property", "Current Configuration / Status"],
                    value=[[k, v] for k, v in env_data.items()],
                    interactive=False,
                    label="Host Execution Environment",
                )
            with gr.Column(scale=1):
                gr.Markdown("#### Quick Navigation & Actions")
                components["btn_refresh_dashboard"] = gr.Button("🔄 Refresh Dashboard", variant="secondary")
                components["btn_load_example_quick"] = gr.Button("📁 Load Example 01 (Single Track)", variant="primary")
                components["btn_reset_session"] = gr.Button("🗑️ Reset Session State", variant="stop")
                components["action_status_html"] = gr.HTML("")

    # Internal update handler
    def refresh_dashboard() -> Tuple[str, str, str, str, str, str, str, List[List[str]], List[List[str]]]:
        p_name = session_state.project_name
        p_id = session_state.project_id
        ds_status = session_state.get_dataset_status()
        v_status = ds_status.get("Validation Status", "No Data Loaded")

        kpis = session_state.get_latest_kpis()
        h_hw = f"""
        <div class="kpi-card">
            <div class="kpi-title">Technical Min Headway</div>
            <div style="font-size: 20px; font-weight: 700; color: #1B365D;">{kpis.get('Technical Headway', 'Not Run Yet')}</div>
            <div style="font-size: 11px; color: #94a3b8;">Direction: {kpis.get('Running Direction', 'FORWARD')}</div>
        </div>
        """
        h_theo = f"""
        <div class="kpi-card">
            <div class="kpi-title">Theoretical Line Capacity</div>
            <div style="font-size: 20px; font-weight: 700; color: #1B365D;">{kpis.get('Theoretical Capacity', 'Not Run Yet')}</div>
            <div style="font-size: 11px; color: #94a3b8;">Ideal homogeneous (C = 3600 / H)</div>
        </div>
        """
        h_plan = f"""
        <div class="kpi-card">
            <div class="kpi-title">Planning Operational Capacity</div>
            <div style="font-size: 20px; font-weight: 700; color: #1B365D;">{kpis.get('Planning Capacity', 'Not Run Yet')}</div>
            <div style="font-size: 11px; color: #94a3b8;">With timetable planning margin</div>
        </div>
        """
        h_bot = f"""
        <div class="kpi-card">
            <div class="kpi-title">Controlling Bottleneck</div>
            <div style="font-size: 18px; font-weight: 700; color: #DC2626;">{kpis.get('Controlling Bottleneck', 'Not Run Yet')}</div>
            <div style="font-size: 11px; color: #94a3b8;">Critical headway governing point</div>
        </div>
        """

        stats_rows = [[k, v] for k, v in session_state.get_project_statistics().items()]
        ds_rows = [[k, v] for k, v in ds_status.items()]

        return p_name, p_id, v_status, h_hw, h_theo, h_plan, h_bot, stats_rows, ds_rows

    components["btn_refresh_dashboard"].click(
        fn=refresh_dashboard,
        inputs=[],
        outputs=[
            components["project_name_text"],
            components["project_id_text"],
            components["validation_status_text"],
            components["kpi_headway"],
            components["kpi_theo_cap"],
            components["kpi_plan_cap"],
            components["kpi_bottleneck"],
            components["stats_dataframe"],
            components["dataset_dataframe"],
        ],
    )

    components["btn_refresh_dashboard_top"].click(
        fn=refresh_dashboard,
        inputs=[],
        outputs=[
            components["project_name_text"],
            components["project_id_text"],
            components["validation_status_text"],
            components["kpi_headway"],
            components["kpi_theo_cap"],
            components["kpi_plan_cap"],
            components["kpi_bottleneck"],
            components["stats_dataframe"],
            components["dataset_dataframe"],
        ],
    )

    def load_quick_example() -> Tuple[str, str, str, str, str, str, str, List[List[str]], List[List[str]], str]:
        success, msg = session_state.load_example("01_single_track")
        p_name, p_id, v_status, h_hw, h_theo, h_plan, h_bot, stats_rows, ds_rows = refresh_dashboard()
        banner = f"<div style='color: #16A34A; font-weight: bold; margin-top: 6px;'>✓ {msg}</div>" if success else f"<div style='color: #DC2626; font-weight: bold; margin-top: 6px;'>⚠️ {msg}</div>"
        return p_name, p_id, v_status, h_hw, h_theo, h_plan, h_bot, stats_rows, ds_rows, banner

    components["btn_load_example_quick"].click(
        fn=load_quick_example,
        inputs=[],
        outputs=[
            components["project_name_text"],
            components["project_id_text"],
            components["validation_status_text"],
            components["kpi_headway"],
            components["kpi_theo_cap"],
            components["kpi_plan_cap"],
            components["kpi_bottleneck"],
            components["stats_dataframe"],
            components["dataset_dataframe"],
            components["action_status_html"],
        ],
    )

    def reset_app() -> Tuple[str, str, str, str, str, str, str, List[List[str]], List[List[str]], str]:
        session_state.reset()
        p_name, p_id, v_status, h_hw, h_theo, h_plan, h_bot, stats_rows, ds_rows = refresh_dashboard()
        banner = "<div style='color: #475569; font-weight: bold; margin-top: 6px;'>Session state cleared.</div>"
        return p_name, p_id, v_status, h_hw, h_theo, h_plan, h_bot, stats_rows, ds_rows, banner

    components["btn_reset_session"].click(
        fn=reset_app,
        inputs=[],
        outputs=[
            components["project_name_text"],
            components["project_id_text"],
            components["validation_status_text"],
            components["kpi_headway"],
            components["kpi_theo_cap"],
            components["kpi_plan_cap"],
            components["kpi_bottleneck"],
            components["stats_dataframe"],
            components["dataset_dataframe"],
            components["action_status_html"],
        ],
    )

    return components
