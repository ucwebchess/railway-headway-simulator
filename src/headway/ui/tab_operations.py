"""Tab 6: Services & Operations for Railway Headway Simulator.

Milestone P15 — UI Integration (P15-TAB-006).
"""

from typing import Any, Dict, List, Optional, Tuple
import gradio as gr
import plotly.graph_objects as go

from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, apply_plotly_theme
from headway.ui.state import session_state


def create_operations_tab() -> Dict[str, Any]:
    """Constructs Tab 6: Services & Operations components and event bindings."""
    components = {}

    with gr.Column():
        gr.Markdown("### Services, Timetables & Operational Stopping Patterns")
        gr.Markdown(
            "Configure and inspect commercial service types, stopping schedules, passenger dwell times, "
            "platform allocation, and directional route traversals."
        )

        with gr.Row():
            components["service_selector"] = gr.Dropdown(
                choices=[],
                value=None,
                label="Select Commercial Service Pattern",
                info="Choose from service patterns defined in the operations model.",
                scale=2,
            )
            components["btn_refresh_ops"] = gr.Button("🔄 Inspect Services & Stopping", variant="primary", scale=1)

        components["service_detail_card"] = gr.HTML("<div style='color: #64748B;'>Select a service pattern to inspect.</div>")

        # Route and Stations schematic
        gr.Markdown("#### Service Traversal Route & Station Stops")
        components["plot_service_route"] = gr.Plot(label="Service Alignment Diagram")

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### Station Stopping & Dwell Pattern")
                components["tbl_stopping_pattern"] = gr.Dataframe(
                    headers=["Station ID", "Platform", "Scheduled Dwell (s)", "Min Dwell (s)", "Door Open/Close (s)"],
                    value=[],
                    interactive=False,
                )
            with gr.Column(scale=1):
                gr.Markdown("#### Operational Dispatch Timetable")
                components["tbl_timetable"] = gr.Dataframe(
                    headers=["Trip ID", "Service ID", "Train Type", "Scheduled Departure (s)", "Priority"],
                    value=[],
                    interactive=False,
                )

    def update_operations_view(selected_svc_id: Optional[str]) -> Tuple[Any, str, go.Figure, List[List[Any]], List[List[Any]]]:
        proj = session_state.current_project
        fig_route = go.Figure()

        if not proj or not proj.operations.service_patterns:
            fig_route.add_annotation(text="No Operations Model Loaded", showarrow=False)
            return gr.update(choices=[]), "<div style='color: #64748B;'>No services defined.</div>", fig_route, [], []

        svc_list = list(proj.operations.service_patterns)
        svc_names = [s.service_pattern_id for s in svc_list]
        cur_svc = next((s for s in svc_list if s.service_pattern_id == selected_svc_id), svc_list[0])
        cur_id = cur_svc.service_pattern_id

        stops_data: List[List[Any]] = []
        for stp in cur_svc.stops:
            dwell_s = stp.dwell_time_s
            min_dwell_s = stp.min_dwell_s
            stops_data.append([
                stp.station_id,
                stp.platform_id or "Auto",
                f"{dwell_s:.1f}",
                f"{min_dwell_s:.1f}",
                "15.0 s",
            ])

        timetable_data: List[List[Any]] = []
        # Generate nominal trips
        for i in range(1, 5):
            timetable_data.append([
                f"TRIP_{cur_id}_{i:02d}",
                cur_id,
                cur_svc.train_type_id,
                f"{(i - 1) * 120.0:.0f} s",
                str(cur_svc.priority),
            ])

        # Service Card (running_direction probed with default FORWARD per Task 2 investigation)
        dir_val = getattr(cur_svc, "running_direction", RunningDirection.FORWARD)
        dir_str = dir_val.value if isinstance(dir_val, RunningDirection) else str(dir_val)
        target_hw = cur_svc.planned_headway_s
        svc_desc = cur_id

        card_html = f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; margin: 8px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-weight: 700; color: #1B365D; font-size: 16px; margin-bottom: 8px;">
                🚆 Service Pattern: {svc_desc}
            </div>
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; font-size: 13px;">
                <div><span style="color: #64748B;">Assigned Train Type:</span> <strong>{cur_svc.train_type_id}</strong></div>
                <div><span style="color: #64748B;">Directionality:</span> <strong>{dir_str}</strong></div>
                <div><span style="color: #64748B;">Station Stops:</span> <strong>{len(cur_svc.stops)}</strong></div>
                <div><span style="color: #64748B;">Target Headway:</span> <strong>{target_hw:.1f} s</strong></div>
            </div>
        </div>
        """

        # Plot route alignment with station markers
        infra = proj.infrastructure
        total_len = sum(lnk.length_m for lnk in infra.track_links)
        fig_route.add_trace(go.Scatter(
            x=[0, total_len],
            y=[0, 0],
            mode="lines",
            line=dict(color=ChartColors.NAVY, width=4),
            name="Route Path",
        ))

        for stp in cur_svc.stops:
            # Locate station
            for plat in infra.platforms:
                if plat.station_id == stp.station_id:
                    mid_x = (plat.start_offset_m + plat.end_offset_m) / 2.0
                    fig_route.add_trace(go.Scatter(
                        x=[mid_x],
                        y=[0],
                        mode="markers+text",
                        marker=dict(size=14, color=ChartColors.AMBER, symbol="diamond"),
                        text=[f"{stp.station_id} ({stp.dwell_time_s}s)"],
                        textposition="top center",
                        name=stp.station_id,
                    ))
                    break

        fig_route.update_layout(
            title=f"Service Route & Platform Dwell Points [{cur_id}]",
            xaxis_title="Route Chainage (m)",
            yaxis_visible=False,
            height=250,
            margin=dict(l=40, r=40, t=40, b=40),
            showlegend=False,
        )
        apply_plotly_theme(fig_route)

        return gr.update(choices=svc_names, value=cur_id), card_html, fig_route, stops_data, timetable_data

    components["btn_refresh_ops"].click(
        fn=update_operations_view,
        inputs=[components["service_selector"]],
        outputs=[
            components["service_selector"],
            components["service_detail_card"],
            components["plot_service_route"],
            components["tbl_stopping_pattern"],
            components["tbl_timetable"],
        ],
    )

    components["service_selector"].change(
        fn=update_operations_view,
        inputs=[components["service_selector"]],
        outputs=[
            components["service_selector"],
            components["service_detail_card"],
            components["plot_service_route"],
            components["tbl_stopping_pattern"],
            components["tbl_timetable"],
        ],
    )

    return components
