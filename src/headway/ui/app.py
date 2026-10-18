"""Master Gradio Application Factory for Railway Headway Simulator.

Milestone P15 — Complete Gradio UI (P15-UI-001 to P15-UI-005, P15-TAB-001 to P15-TAB-010).
Assembles all ten engineering workflow tabs into a responsive, themed interface.
"""

from typing import Any, Dict, Optional
import gradio as gr

from headway.ui.tab_dashboard import create_dashboard_tab
from headway.ui.tab_data_import import create_data_import_tab
from headway.ui.tab_infrastructure import create_infrastructure_tab
from headway.ui.tab_operations import create_operations_tab
from headway.ui.tab_reports import create_reports_tab
from headway.ui.tab_results import create_results_tab
from headway.ui.tab_rolling_stock_signalling import create_rolling_stock_tab
from headway.ui.tab_scenarios import create_scenarios_tab
from headway.ui.tab_simulation import create_simulation_tab
from headway.ui.tab_validation import create_validation_tab
from headway.ui.theme import APP_CSS, ENGINEERING_THEME


def create_app(app_config: Optional[Any] = None) -> gr.Blocks:
    """Builds and returns the master 10-tab Gradio Blocks application.

    Args:
        app_config: Optional configuration for application runtime.

    Returns:
        gr.Blocks instance configured with custom theme, CSS, and tabs.
    """
    with gr.Blocks(
        title="Railway Headway & Capacity Simulator — Professional Assessment Platform (1.5.0)",
    ) as app:
        # Header banner
        with gr.Row(elem_classes=["app-header"]):
            with gr.Column(scale=3):
                gr.Markdown(
                    """
                    # 🚆 Railway Headway & Capacity Simulator
                    **Microscopic Physics, Signalling Timing & Multi-Train Headway Analysis Platform**
                    *Fully integrated simulation engine per UIC 405 / 406 standards*
                    """
                )
            with gr.Column(scale=1):
                gr.Markdown(
                    """
                    <div style="text-align: right; font-size: 12px; color: #64748b; padding-top: 8px;">
                        <div><strong>Engine:</strong> Microscopic ODE (Euler/RK4)</div>
                        <div><strong>Status:</strong> Ready</div>
                        <div><strong>Version:</strong> 1.5.0 (Release)</div>
                    </div>
                    """
                )

        gr.Markdown("---")

        # 10 Top-Level Navigation Tabs
        with gr.Tabs(elem_id="main_navigation_tabs") as main_tabs:
            with gr.TabItem("1. Project Dashboard", id="tab_dashboard"):
                create_dashboard_tab()

            with gr.TabItem("2. Data Import", id="tab_import"):
                create_data_import_tab()

            with gr.TabItem("3. Data Validation", id="tab_validation"):
                create_validation_tab()

            with gr.TabItem("4. Infrastructure Explorer", id="tab_infrastructure"):
                create_infrastructure_tab()

            with gr.TabItem("5. Rolling Stock & Signalling", id="tab_rolling_stock"):
                create_rolling_stock_tab()

            with gr.TabItem("6. Services & Operations", id="tab_operations"):
                create_operations_tab()

            with gr.TabItem("7. Scenario Manager", id="tab_scenarios"):
                create_scenarios_tab()

            with gr.TabItem("8. Simulation Control", id="tab_simulation"):
                create_simulation_tab()

            with gr.TabItem("9. Results & Comparison", id="tab_results"):
                create_results_tab()

            with gr.TabItem("10. Reports & Export", id="tab_reports"):
                create_reports_tab()

    return app


def launch_app(
    share: bool = False,
    server_port: int = 7860,
    server_name: str = "0.0.0.0",
    inbrowser: bool = False,
    quiet: bool = False,
    **kwargs: Any,
) -> Any:
    """Launches the Railway Headway Simulator application.

    Note on share parameter:
        Default is share=False per security and deployment constraints.

    Args:
        share: Whether to generate a public Gradio share link (default: False).
        server_port: Port to bind local server (default: 7860).
        server_name: Hostname to bind server (default: '0.0.0.0').
        inbrowser: Whether to open browser automatically (default: False).
        quiet: Suppress banner output.
        **kwargs: Extra parameters passed to gr.Blocks.launch.

    Returns:
        The running Gradio app instance.
    """
    app = create_app()
    return app.launch(
        share=share,
        server_name=server_name,
        server_port=server_port,
        inbrowser=inbrowser,
        quiet=quiet,
        theme=ENGINEERING_THEME,
        css=APP_CSS,
        **kwargs,
    )


if __name__ == "__main__":
    launch_app()
