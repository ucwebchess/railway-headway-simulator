"""Tab 8: Simulation Control for Railway Headway Simulator.

Milestone P15 — Mandatory Direction Selector & Background Simulation (P15-DIR-001 to P15-DIR-010, P15-EXE-001 to P15-EXE-007).
"""

import time
from typing import Any, Dict, List, Optional, Tuple
import gradio as gr

from headway.infrastructure.direction import RunningDirection
from headway.ui.background_executor import default_executor
from headway.ui.direction_selector import DirectionSelector
from headway.ui.error_handling import create_error_html, create_success_html
from headway.ui.simulation_runner import SimulationRunner
from headway.ui.state import session_state


def create_simulation_tab() -> Dict[str, Any]:
    """Constructs Tab 8: Simulation Control components and event bindings."""
    components = {}

    with gr.Column():
        gr.Markdown("### Microscopic Simulation Execution & Operational Analysis Control")
        gr.Markdown(
            "Configure operational parameters, select train running direction, choose simulation modes, "
            "and execute numerical integration in background worker threads."
        )

        # MANDATORY Running Direction Selector (P15-DIR-001 to P15-DIR-003)
        with gr.Row():
            components["running_direction_selector"] = DirectionSelector.create_component(
                label="Running Direction (Mandatory Engineering Selector)",
                value=session_state.selected_running_direction.value,
                elem_id="sim_running_direction_radio",
            )
            components["direction_banner_html"] = gr.HTML(
                DirectionSelector.render_banner(session_state.selected_running_direction)
            )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### Simulation Mode")
                components["sim_mode_dropdown"] = gr.Dropdown(
                    choices=[
                        "Full Integrated Suite (All Analyses)",
                        "AN_HSR_HSR_UP_100 (Full Performance - Factor 1.00)",
                        "AN_HSR_HSR_UP_95 (Degraded Performance - Factor 0.95)",
                        "AN_HSR_HSR_UP_100",
                        "AN_HSR_HSR_UP_95",
                        "Technical Minimum Headway (Pairwise)",
                        "Mixed-Traffic Headway Matrix",
                        "Multi-Train Operational Simulation",
                        "Capacity & Block Length Sensitivity",
                        "TVS Tunnel Ventilation Assessment",
                        "Stochastic Monte Carlo Reliability",
                    ],
                    value="Full Integrated Suite (All Analyses)",
                    label="Analysis & Simulation Mode",
                )
                components["active_scenario_display"] = gr.Textbox(
                    label="Active Scenario Target",
                    value=session_state.active_scenario_id,
                    interactive=False,
                )

            with gr.Column(scale=1):
                gr.Markdown("#### Numerical & Operational Parameters")
                with gr.Row():
                    components["param_dt"] = gr.Number(value=0.1, label="Integration Step dt (s)", minimum=0.01, maximum=1.0)
                    components["param_duration"] = gr.Number(value=600.0, label="Simulation Horizon (s)", minimum=60.0)
                with gr.Row():
                    components["param_margin"] = gr.Number(value=18.0, label="Planning Margin (s)", minimum=0.0)
                    components["param_replications"] = gr.Number(value=100, label="Monte Carlo Replications", minimum=10, maximum=1000)

        gr.Markdown("---")

        # Action Buttons Row
        with gr.Row():
            components["btn_run_simulation"] = gr.Button("🚀 Run Simulation", variant="primary", scale=2)
            components["btn_cancel_simulation"] = gr.Button("🛑 Cancel Simulation", variant="stop", scale=1)

        # Progress Reporting (P15-EXE-002)
        with gr.Row():
            components["sim_progress_bar"] = gr.Slider(
                minimum=0,
                maximum=100,
                value=0,
                label="Execution Progress (%)",
                interactive=False,
                scale=3,
            )
            components["sim_stage_text"] = gr.Textbox(
                value="Idle — Ready to Run",
                label="Current Stage / Elapsed Time",
                interactive=False,
                scale=2,
            )

        components["sim_status_banner"] = gr.HTML("")

        with gr.Accordion("Live Simulation Execution Logs", open=True):
            components["sim_log_textbox"] = gr.Textbox(
                value="Simulator initialized. Ready for simulation execution.",
                lines=8,
                max_lines=12,
                interactive=False,
                label="Worker Logs",
            )

    # Direction change handler
    def handle_direction_change(selected_dir_str: str) -> Tuple[str, str]:
        dir_enum = RunningDirection(selected_dir_str.upper())
        session_state.selected_running_direction = dir_enum

        # Validate direction against active project
        is_valid, err = DirectionSelector.validate_direction(
            direction=dir_enum,
            project=session_state.current_project,
        )

        banner = DirectionSelector.render_banner(dir_enum)
        if not is_valid:
            status_html = create_error_html({
                "category": "Direction Incompatibility",
                "message": err or "Route does not permit this direction.",
                "recommendation": "Switch to FORWARD or verify track link directionality in Infrastructure tab.",
            })
            return banner, status_html

        status_html = f"<div style='color: #2563EB; font-weight: 600; margin: 6px 0;'>✓ Direction set to {dir_enum.value}. Verified compatible with infrastructure.</div>"
        return banner, status_html

    components["running_direction_selector"].change(
        fn=handle_direction_change,
        inputs=[components["running_direction_selector"]],
        outputs=[components["direction_banner_html"], components["sim_status_banner"]],
    )

    # Run simulation handler
    def handle_run_simulation(
        dir_str: str,
        mode_str: str,
        dt_val: float,
        dur_val: float,
        margin_val: float,
        rep_val: int,
    ) -> Tuple[float, str, str, str]:
        if not session_state.current_project:
            err = create_error_html({
                "category": "Pre-condition Error",
                "message": "No railway project loaded. Please load or import a dataset in Tab 2 first.",
            })
            return 0.0, "Execution Aborted", err, "No project loaded."

        dir_enum = RunningDirection(dir_str.upper())
        session_state.selected_running_direction = dir_enum

        # Execute simulation pipeline synchronously or via runner
        try:
            active_cfg = getattr(session_state, "report_config", None)
            package, report_doc = SimulationRunner.run_simulation_pipeline(
                project=session_state.current_project,
                running_direction=dir_enum,
                simulation_mode=mode_str,
                scenario_id=session_state.active_scenario_id,
                report_config=active_cfg,
            )

            # Store in session state
            session_state.latest_result_package = package
            session_state.latest_report_doc = report_doc
            session_state.simulation_packages[package.run_id] = package

            kpis = report_doc.executive_kpis
            success_msg = create_success_html(
                f"Simulation Complete — RUN ID: {package.run_id}",
                f"Running Direction: <strong>{dir_enum.value}</strong> | "
                f"Min Headway: <strong>{kpis.technical_headway_s:.1f} s</strong> | "
                f"Theoretical Capacity: <strong>{kpis.theoretical_capacity_tph:.1f} tph</strong> | "
                f"Bottleneck: <strong>{kpis.controlling_bottleneck_id}</strong>",
            )

            log_text = (
                f"[{time.strftime('%H:%M:%S')}] Simulation {package.run_id} finished successfully.\n"
                f"[{time.strftime('%H:%M:%S')}] Direction: {dir_enum.value}\n"
                f"[{time.strftime('%H:%M:%S')}] Controlling Bottleneck: {kpis.controlling_bottleneck_id}\n"
                f"[{time.strftime('%H:%M:%S')}] Technical Minimum Headway: {kpis.technical_headway_s:.1f} s\n"
                f"[{time.strftime('%H:%M:%S')}] Theoretical Capacity: {kpis.theoretical_capacity_tph:.1f} trains/hour\n"
                f"[{time.strftime('%H:%M:%S')}] Planning Capacity: {kpis.planning_capacity_tph:.1f} trains/hour\n"
                f"[{time.strftime('%H:%M:%S')}] Results and 18-section report assembled. Inspect in Tabs 9 & 10."
            )

            return 100.0, f"Completed ({package.run_id})", success_msg, log_text

        except Exception as e:
            err = create_error_html({
                "category": "Simulation Failure",
                "message": str(e),
                "recommendation": "Review parameters, track connectivity, and train characteristics.",
            })
            return 0.0, "Failed", err, f"Error: {e}"

    components["btn_run_simulation"].click(
        fn=handle_run_simulation,
        inputs=[
            components["running_direction_selector"],
            components["sim_mode_dropdown"],
            components["param_dt"],
            components["param_duration"],
            components["param_margin"],
            components["param_replications"],
        ],
        outputs=[
            components["sim_progress_bar"],
            components["sim_stage_text"],
            components["sim_status_banner"],
            components["sim_log_textbox"],
        ],
    )

    def handle_cancel() -> Tuple[str, str]:
        default_executor.cancel_active_task()
        return "Cancellation Requested", "User requested abort of simulation task."

    components["btn_cancel_simulation"].click(
        fn=handle_cancel,
        inputs=[],
        outputs=[components["sim_stage_text"], components["sim_log_textbox"]],
    )

    return components
