"""Tab 4: Infrastructure Explorer for Railway Headway Simulator.

Milestone P15 — UI Integration (P15-TAB-004, P15-DIR-008, P15-DIRV-006).
"""

from typing import Any, Dict, List, Optional, Tuple
import gradio as gr
import plotly.graph_objects as go

from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, apply_plotly_theme
from headway.ui.direction_selector import DirectionSelector
from headway.ui.state import session_state


def create_infrastructure_tab() -> Dict[str, Any]:
    """Constructs Tab 4: Infrastructure Explorer components and event bindings."""
    components = {}

    with gr.Column():
        gr.Markdown("### Railway Infrastructure Network & Alignment Explorer")
        gr.Markdown(
            "Inspect track link connectivity, vertical gradients, horizontal curvature, "
            "signalling block boundaries, station platforms, and tunnel ventilation sections (TVS)."
        )

        with gr.Row():
            components["view_direction_toggle"] = DirectionSelector.create_explorer_toggle(
                elem_id="infra_view_direction_toggle"
            )
            components["btn_refresh_infra"] = gr.Button("🔄 Refresh Infrastructure View", variant="primary")

        # Network Schematic Plotly Figure
        gr.Markdown("#### Network Schematic & Track Connectivity")
        components["network_schematic_plot"] = gr.Plot(label="Track Schematic Diagram")

        # Gradient and Curvature Profile
        gr.Markdown("#### Vertical Gradient & Horizontal Curvature Profile")
        components["alignment_profile_plot"] = gr.Plot(label="Track Alignment Profile")

        # Data Tables Accordion
        with gr.Accordion("Infrastructure Object Registers", open=True):
            with gr.Tabs():
                with gr.TabItem("Track Links"):
                    components["tbl_track_links"] = gr.Dataframe(
                        headers=["Link ID", "Track ID", "Start Node", "End Node", "Length (m)", "Speed Limit (km/h)", "Directionality"],
                        value=[],
                        interactive=False,
                    )
                with gr.TabItem("Signalling Blocks"):
                    components["tbl_blocks"] = gr.Dataframe(
                        headers=["Block ID", "Link ID", "Start (m)", "End (m)", "Length (m)", "Associated Signal"],
                        value=[],
                        interactive=False,
                    )
                with gr.TabItem("Stations & Platforms"):
                    components["tbl_stations"] = gr.Dataframe(
                        headers=["Station ID", "Platform ID", "Link ID", "Start Offset (m)", "End Offset (m)", "Length (m)"],
                        value=[],
                        interactive=False,
                    )
                with gr.TabItem("Tunnels & TVS Sections"):
                    components["tbl_tvs"] = gr.Dataframe(
                        headers=["TVS ID", "Tunnel ID", "Track ID", "Length (m)", "Max Occupancy", "Release Delay (s)"],
                        value=[],
                        interactive=False,
                    )

    def update_infra_view(view_dir_str: str) -> Tuple[go.Figure, go.Figure, List[List[Any]], List[List[Any]], List[List[Any]], List[List[Any]]]:
        is_rev = "REVERSE" in (view_dir_str or "").upper()
        proj = session_state.current_project

        # 1. Build schematic figure
        fig_net = go.Figure()
        fig_prof = go.Figure()

        links_data: List[List[Any]] = []
        blocks_data: List[List[Any]] = []
        stations_data: List[List[Any]] = []
        tvs_data: List[List[Any]] = []

        if not proj or not proj.infrastructure.track_links:
            fig_net.add_annotation(text="No Infrastructure Model Loaded", showarrow=False, font=dict(size=16, color="#64748B"))
            fig_prof.add_annotation(text="No Infrastructure Model Loaded", showarrow=False, font=dict(size=16, color="#64748B"))
            return fig_net, fig_prof, links_data, blocks_data, stations_data, tvs_data

        infra = proj.infrastructure
        ordered_links = list(infra.track_links)
        if is_rev:
            ordered_links.reverse()

        cum_dist = 0.0
        x_coords = [0.0]
        y_coords = [0.0]
        grad_x = []
        grad_y = []

        for lnk in ordered_links:
            links_data.append([
                lnk.link_id,
                lnk.track_id,
                lnk.start_node_id,
                lnk.end_node_id,
                lnk.length_m,
                lnk.max_speed_ms * 3.6,
                lnk.directionality.value,
            ])
            start_d = cum_dist
            end_d = cum_dist + lnk.length_m
            cum_dist = end_d

            x_coords.extend([start_d, end_d])
            y_coords.extend([0.0, 0.0])

            effective_grade = -lnk.gradient_permille if is_rev else lnk.gradient_permille
            grad_x.extend([start_d, end_d])
            grad_y.extend([effective_grade, effective_grade])

        # Schematic line
        fig_net.add_trace(go.Scatter(
            x=x_coords,
            y=y_coords,
            mode="lines+markers",
            line=dict(color=ChartColors.NAVY, width=4),
            marker=dict(size=8, color=ChartColors.BLUE),
            name="Track Centerline",
            hovertemplate="Chainage: %{x:.0f} m<extra></extra>",
        ))

        # Station markers
        for stn in infra.stations:
            for plat in infra.platforms:
                if plat.station_id == stn.station_id:
                    stations_data.append([
                        stn.station_id,
                        plat.platform_id,
                        plat.link_id,
                        plat.start_offset_m,
                        plat.end_offset_m,
                        plat.length_m,
                    ])
                    # Place platform on schematic
                    fig_net.add_annotation(
                        x=(plat.start_offset_m + plat.end_offset_m) / 2.0,
                        y=0.0,
                        text=f"🚉 {stn.name or stn.station_id}",
                        showarrow=True,
                        arrowhead=2,
                        arrowcolor=ChartColors.AMBER,
                        arrowsize=1,
                        arrowwidth=2,
                        ay=-40,
                        font=dict(color=ChartColors.NAVY, size=11, family="Arial"),
                        bgcolor="#FEF3C7",
                        bordercolor=ChartColors.AMBER,
                    )

        # Blocks
        for blk in proj.signalling.blocks:
            blocks_data.append([
                blk.block_id,
                blk.link_id,
                blk.start_offset_m,
                blk.end_offset_m,
                blk.length_m,
                blk.associated_signal_id or "-",
            ])

        # TVS
        for tvs in infra.tvs_sections:
            tvs_data.append([
                tvs.tvs_id,
                tvs.tunnel_id,
                tvs.track_id,
                sum(iv.end_offset_m - iv.start_offset_m for iv in tvs.link_intervals),
                tvs.max_occupancy,
                tvs.release_delay_s,
            ])

        # Schematic styling
        orient_txt = "REVERSE (Inverted)" if is_rev else "FORWARD (Default)"
        fig_net.update_layout(
            title=f"Railway Corridor Schematic [{orient_txt}]",
            xaxis_title="Distance along View Orientation (m)",
            yaxis_visible=False,
            height=250,
            margin=dict(l=40, r=40, t=40, b=40),
        )
        apply_plotly_theme(fig_net)

        # Alignment profile styling
        fig_prof.add_trace(go.Bar(
            x=[(grad_x[i] + grad_x[i+1])/2 for i in range(0, len(grad_x)-1, 2)] if len(grad_x) >= 2 else [0],
            y=[grad_y[i] for i in range(0, len(grad_y)-1, 2)] if len(grad_y) >= 2 else [0],
            width=[grad_x[i+1] - grad_x[i] for i in range(0, len(grad_x)-1, 2)] if len(grad_x) >= 2 else [1],
            name="Gradient (‰)",
            marker_color=ChartColors.TEAL,
        ))
        fig_prof.update_layout(
            title=f"Track Gradient Profile [{orient_txt}]",
            xaxis_title="Distance along View Orientation (m)",
            yaxis_title="Effective Gradient (‰)",
            height=280,
            margin=dict(l=50, r=40, t=40, b=40),
        )
        apply_plotly_theme(fig_prof)

        return fig_net, fig_prof, links_data, blocks_data, stations_data, tvs_data

    components["btn_refresh_infra"].click(
        fn=update_infra_view,
        inputs=[components["view_direction_toggle"]],
        outputs=[
            components["network_schematic_plot"],
            components["alignment_profile_plot"],
            components["tbl_track_links"],
            components["tbl_blocks"],
            components["tbl_stations"],
            components["tbl_tvs"],
        ],
    )

    components["view_direction_toggle"].change(
        fn=update_infra_view,
        inputs=[components["view_direction_toggle"]],
        outputs=[
            components["network_schematic_plot"],
            components["alignment_profile_plot"],
            components["tbl_track_links"],
            components["tbl_blocks"],
            components["tbl_stations"],
            components["tbl_tvs"],
        ],
    )

    return components
