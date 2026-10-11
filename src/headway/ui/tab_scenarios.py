"""Tab 7: Scenario Manager for Railway Headway Simulator.

Milestone P15 — UI Integration (P15-TAB-007, P15-SCN-001 to P15-SCN-005, P15-TVS-001, P15-STC-001).
"""

from typing import Any, Dict, List, Optional, Tuple
import gradio as gr

from headway.infrastructure.direction import RunningDirection
from headway.scenarios.scenario_models import (
    ExplicitOverride,
    OverrideAction,
    ScenarioDefinition,
    ScenarioStatus,
    ScenarioType,
)
from headway.ui.error_handling import create_error_html, create_success_html
from headway.ui.state import session_state


def create_scenarios_tab() -> Dict[str, Any]:
    """Constructs Tab 7: Scenario Manager components and event bindings."""
    components = {}

    with gr.Column():
        gr.Markdown("### Scenario Lifecycle, Parameter Overrides & Engineering Alternatives")
        gr.Markdown(
            "Manage immutable baseline configurations, branch alternative scenarios (signalling upgrades, "
            "block length modifications, TVS policies), and audit parameter differences."
        )

        with gr.Row():
            components["scenario_selector"] = gr.Dropdown(
                choices=["BASELINE"],
                value="BASELINE",
                label="Active Engineering Scenario",
                info="Select scenario to edit, validate, or execute in simulation.",
                scale=2,
            )
            components["btn_refresh_scenarios"] = gr.Button("🔄 Refresh Scenarios", variant="secondary", scale=1)

        # Baseline Protection Indicator
        components["baseline_protection_banner"] = gr.HTML(
            """
            <div style="background-color: #EFF6FF; border: 1px solid #93C5FD; border-left: 5px solid #2563EB; padding: 10px 16px; border-radius: 6px; margin: 8px 0;">
                <strong style="color: #1E40AF;">🛡️ Baseline Immutability Protection:</strong>
                <span style="color: #1E3A8A; font-size: 13px;">The BASELINE scenario is permanently protected against direct in-place mutation (P12-SCN-002).</span>
            </div>
            """
        )

        # Actions Row
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### Branch New Scenario")
                components["new_scenario_id"] = gr.Textbox(label="New Scenario ID", placeholder="SCEN_CBTC_UPGRADE")
                components["new_scenario_name"] = gr.Textbox(label="Scenario Name", placeholder="CBTC Moving Block Upgrade")
                components["new_scenario_type"] = gr.Dropdown(
                    choices=["ALTERNATIVE", "SENSITIVITY", "DISRUPTION", "STOCHASTIC"],
                    value="ALTERNATIVE",
                    label="Scenario Category",
                )
                components["btn_create_scenario"] = gr.Button("➕ Branch from Active Scenario", variant="primary")

            with gr.Column(scale=1):
                gr.Markdown("#### Scenario Operations")
                components["btn_duplicate_scenario"] = gr.Button("📋 Duplicate Scenario", variant="secondary")
                components["btn_archive_scenario"] = gr.Button("📦 Archive Scenario", variant="secondary")
                components["btn_delete_scenario"] = gr.Button("🗑️ Delete Scenario", variant="stop")

        gr.Markdown("---")
        gr.Markdown("#### Parameter Overrides & Subsystem Configurations")

        with gr.Row():
            with gr.Column(scale=1):
                components["tvs_policy_dropdown"] = gr.Dropdown(
                    choices=[
                        "DISABLED (Signalling Only)",
                        "ONE_PER_TVS_PER_TRACK (Standard)",
                        "SHARED_TVS_ACROSS_TRACKS",
                        "WHOLE_TUNNEL_PER_TRACK",
                        "WHOLE_TUNNEL_SHARED",
                    ],
                    value="ONE_PER_TVS_PER_TRACK (Standard)",
                    label="Tunnel Ventilation System (TVS) Policy (P15-TVS-001)",
                    info="Operating constraint: rules governing train presence in tunnel ventilation sections.",
                )
            with gr.Column(scale=1):
                components["stochastic_mode_dropdown"] = gr.Dropdown(
                    choices=[
                        "DETERMINISTIC_ONLY",
                        "STOCHASTIC_DWELL_PASSENGERS",
                        "STOCHASTIC_DISPATCH_JITTER",
                        "FULL_MONTE_CARLO_RELIABILITY",
                    ],
                    value="DETERMINISTIC_ONLY",
                    label="Operational Variability / Stochastic Mode (P15-STC-001)",
                    info="Sampling scope for passenger dwell, departure readiness, and tractive utilization.",
                )

        # Differences table relative to baseline
        gr.Markdown("#### Scenario Parameter Differences vs Baseline")
        components["tbl_scenario_diffs"] = gr.Dataframe(
            headers=["Target Parameter Path", "Baseline Value", "Scenario Value", "Delta / Action"],
            value=[["-", "-", "-", "Identical to Baseline"]],
            interactive=False,
        )

        components["scenario_feedback_box"] = gr.HTML("")

    def refresh_scenarios_list() -> Tuple[Any, str, List[List[str]]]:
        mgr = session_state.scenario_manager
        if not mgr:
            return gr.update(choices=["BASELINE"], value="BASELINE"), "", [["-", "-", "-", "No scenario manager loaded"]]

        scns = mgr.get_all_scenarios()
        scn_ids = [s.scenario_id for s in scns]
        cur = session_state.active_scenario_id if session_state.active_scenario_id in scn_ids else "BASELINE"

        diff_rows: List[List[str]] = []
        if cur != "BASELINE":
            scn_obj = mgr.get_scenario(cur)
            for ov in scn_obj.overrides:
                diff_rows.append([ov.target_path, "Baseline Default", str(ov.new_value), ov.action.value])
        if not diff_rows:
            diff_rows.append(["(Entire Model)", "Baseline Reference", "No Overrides", "IDENTICAL"])

        return gr.update(choices=scn_ids, value=cur), "", diff_rows

    components["btn_refresh_scenarios"].click(
        fn=refresh_scenarios_list,
        inputs=[],
        outputs=[components["scenario_selector"], components["scenario_feedback_box"], components["tbl_scenario_diffs"]],
    )

    def handle_create_scenario(new_id: str, new_name: str, new_type: str) -> Tuple[Any, str, List[List[str]]]:
        mgr = session_state.scenario_manager
        if not mgr:
            return gr.update(), create_error_html({"category": "Error", "message": "No project loaded."}), []

        if not new_id or not new_id.strip():
            return gr.update(), create_error_html({"category": "Validation Error", "message": "Scenario ID cannot be empty."}), []

        try:
            mgr.create_scenario(
                scenario_id=new_id.strip(),
                scenario_name=new_name.strip() or new_id.strip(),
                parent_scenario_id=session_state.active_scenario_id,
                scenario_type=ScenarioType(new_type),
            )
            session_state.active_scenario_id = new_id.strip()
            scns, _, diffs = refresh_scenarios_list()
            msg = create_success_html(f"Scenario Created: {new_id}", f"Successfully branched '{new_id}' from parent '{session_state.active_scenario_id}'.")
            return scns, msg, diffs
        except Exception as e:
            return gr.update(), create_error_html({"category": "Scenario Creation Failed", "message": str(e)}), []

    components["btn_create_scenario"].click(
        fn=handle_create_scenario,
        inputs=[components["new_scenario_id"], components["new_scenario_name"], components["new_scenario_type"]],
        outputs=[components["scenario_selector"], components["scenario_feedback_box"], components["tbl_scenario_diffs"]],
    )

    def handle_duplicate_scenario(active_scn: str) -> Tuple[Any, str, List[List[str]]]:
        mgr = session_state.scenario_manager
        if not mgr:
            return gr.update(), create_error_html({"category": "Error", "message": "No project loaded."}), []

        target_scn = active_scn or session_state.active_scenario_id or "BASELINE"
        new_id = f"{target_scn}_COPY"
        existing_ids = [s.scenario_id for s in mgr.list_scenarios(include_archived=True)]
        count = 1
        while new_id in existing_ids:
            new_id = f"{target_scn}_COPY_{count}"
            count += 1

        try:
            mgr.duplicate_scenario(source_scenario_id=target_scn, new_scenario_id=new_id)
            session_state.active_scenario_id = new_id
            scns, _, diffs = refresh_scenarios_list()
            msg = create_success_html("Scenario Duplicated", f"Duplicated '{target_scn}' as '{new_id}'.")
            return scns, msg, diffs
        except Exception as e:
            return gr.update(), create_error_html({"category": "Duplication Failed", "message": str(e)}), []

    components["btn_duplicate_scenario"].click(
        fn=handle_duplicate_scenario,
        inputs=[components["scenario_selector"]],
        outputs=[components["scenario_selector"], components["scenario_feedback_box"], components["tbl_scenario_diffs"]],
    )

    def handle_archive_scenario(active_scn: str) -> Tuple[Any, str, List[List[str]]]:
        mgr = session_state.scenario_manager
        if not mgr:
            return gr.update(), create_error_html({"category": "Error", "message": "No project loaded."}), []

        if active_scn == "BASELINE":
            return gr.update(), create_error_html({"category": "Protection Error", "message": "Cannot archive BASELINE scenario (protected baseline)."}), []

        try:
            mgr.archive_scenario(active_scn)
            session_state.active_scenario_id = "BASELINE"
            scns, _, diffs = refresh_scenarios_list()
            msg = create_success_html("Scenario Archived", f"Scenario '{active_scn}' was archived.")
            return scns, msg, diffs
        except Exception as e:
            return gr.update(), create_error_html({"category": "Archive Failed", "message": str(e)}), []

    components["btn_archive_scenario"].click(
        fn=handle_archive_scenario,
        inputs=[components["scenario_selector"]],
        outputs=[components["scenario_selector"], components["scenario_feedback_box"], components["tbl_scenario_diffs"]],
    )

    def handle_delete_scenario(active_scn: str) -> Tuple[Any, str, List[List[str]]]:
        mgr = session_state.scenario_manager
        if not mgr:
            return gr.update(), create_error_html({"category": "Error", "message": "No project loaded."}), []

        if active_scn == "BASELINE":
            return gr.update(), create_error_html({"category": "Protection Error", "message": "Cannot delete BASELINE scenario (protected baseline)."}), []

        try:
            mgr.delete_scenario(active_scn)
            session_state.active_scenario_id = "BASELINE"
            scns, _, diffs = refresh_scenarios_list()
            msg = create_success_html(f"Scenario Deleted", f"Scenario '{active_scn}' was deleted.")
            return scns, msg, diffs
        except Exception as e:
            return gr.update(), create_error_html({"category": "Delete Failed", "message": str(e)}), []

    components["btn_delete_scenario"].click(
        fn=handle_delete_scenario,
        inputs=[components["scenario_selector"]],
        outputs=[components["scenario_selector"], components["scenario_feedback_box"], components["tbl_scenario_diffs"]],
    )

    def handle_scenario_change(selected_scn: str) -> Tuple[str, List[List[str]]]:
        session_state.active_scenario_id = selected_scn
        mgr = session_state.scenario_manager
        diff_rows: List[List[str]] = []
        if mgr and selected_scn != "BASELINE":
            scn_obj = mgr.get_scenario(selected_scn)
            for ov in scn_obj.overrides:
                diff_rows.append([ov.target_path, "Baseline Default", str(ov.new_value), ov.action.value])
        if not diff_rows:
            diff_rows.append(["(Entire Model)", "Baseline Reference", "No Overrides", "IDENTICAL"])
        return f"<div style='color: #2563EB; font-weight: 600; margin: 6px 0;'>Active scenario switched to: {selected_scn}</div>", diff_rows

    components["scenario_selector"].change(
        fn=handle_scenario_change,
        inputs=[components["scenario_selector"]],
        outputs=[components["scenario_feedback_box"], components["tbl_scenario_diffs"]],
    )

    return components
