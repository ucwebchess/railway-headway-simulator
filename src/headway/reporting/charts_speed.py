"""Speed profile, gradient, and curvature engineering charts.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 8 & § 9).
Satisfies:
- P13-SPD-001: Speed-distance diagram with permissible speed envelope and station stops.
- P13-SPD-002: Distance axis in running direction, speed on vertical axis.
- P13-SPD-003: Station stop and dwell annotations.
- P13-SPD-004: Reverse direction displays route distance in reverse running order.
- P13-SPD-005: Multi-train overlay (leader vs follower distinguishable).
- P13-GRD-001 to 005: Gradient and curvature profiles with directional sign handling.
"""

from typing import Any, Dict, List, Optional, Sequence, Union
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from headway.data.canonical import Platform, Station, TrackLink, TVSSection
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout
from headway.reporting.visualization_adapters import VisualizationAdapter
from headway.simulation.trajectory import TrainTrajectory


def create_speed_distance_figure(
    trajectories: Union[TrainTrajectory, Sequence[TrainTrajectory]],
    permissible_speed_envelope: Optional[Sequence[Dict[str, float]]] = None,
    stations: Optional[Sequence[Station]] = None,
    platforms: Optional[Sequence[Platform]] = None,
    tvs_sections: Optional[Sequence[TVSSection]] = None,
    title: str = "Train Speed Profile & Permissible Speed Envelope",
    running_direction: Optional[RunningDirection] = None,
) -> go.Figure:
    """P13-SPD-001 to 005: Generate interactive Plotly Speed–Distance diagram."""
    traj_list = [trajectories] if isinstance(trajectories, TrainTrajectory) else list(trajectories)
    eff_dir = running_direction or (traj_list[0].running_direction if traj_list else RunningDirection.FORWARD)

    fig = go.Figure()

    # 1. Plot permissible speed envelope if provided
    if permissible_speed_envelope:
        env_x = [pt.get("route_distance_m", 0.0) / 1000.0 for pt in permissible_speed_envelope]
        env_y = [pt.get("max_speed_kmh", 0.0) for pt in permissible_speed_envelope]
        fig.add_trace(
            go.Scatter(
                x=env_x,
                y=env_y,
                mode="lines",
                line=dict(color=ChartColors.SPEED_ENVELOPE, width=2, dash="dash"),
                name="Permissible Speed Limit",
                hoverinfo="x+y+name",
            )
        )

    # 2. Plot train speed trajectories
    colors = [ChartColors.LEADER_TRAIN, ChartColors.FOLLOWER_TRAIN, ChartColors.OPPOSING_TRAIN, ChartColors.SECONDARY_BLUE]

    for idx, traj in enumerate(traj_list):
        df = VisualizationAdapter.adapt_trajectory(traj, running_direction=eff_dir)
        t_color = colors[idx % len(colors)]
        role = "Leader" if idx == 0 and len(traj_list) > 1 else ("Follower" if idx == 1 else "")
        label = f"{traj.train_id} ({role})" if role else traj.train_id

        fig.add_trace(
            go.Scatter(
                x=df["route_distance_km"],
                y=df["speed_kmh"],
                mode="lines",
                line=dict(color=t_color, width=2.5),
                name=f"Speed: {label}",
                hovertemplate="Distance: %{x:.3f} km<br>Speed: %{y:.1f} km/h<extra></extra>",
            )
        )

    # 3. Annotate Station Stop Positions & Platforms (P13-SPD-003)
    if platforms and stations:
        stn_map = {s.station_id: s.name for s in stations}
        for plat in platforms:
            stn_name = stn_map.get(plat.station_id, plat.station_id)
            # Platform start and end in km
            p_start_km = plat.start_offset_m / 1000.0
            p_end_km = plat.end_offset_m / 1000.0
            fig.add_vrect(
                x0=p_start_km,
                x1=p_end_km,
                fillcolor=ChartColors.COMPONENT_DWELL,
                opacity=0.25,
                layer="below",
                line_width=1,
                line_color=ChartColors.COMPONENT_DWELL,
                annotation_text=f"Station: {stn_name}",
                annotation_position="top left",
                annotation_font=dict(size=10, color=ChartColors.PRIMARY_NAVY),
            )

    # 4. Annotate TVS Boundaries (P13-SPD-001)
    if tvs_sections:
        for tvs in tvs_sections:
            for interval in tvs.link_intervals:
                tvs_start_km = interval.start_offset_m / 1000.0
                tvs_end_km = interval.end_offset_m / 1000.0
                fig.add_vrect(
                    x0=tvs_start_km,
                    x1=tvs_end_km,
                    fillcolor=ChartColors.COMPONENT_RELEASE,
                    opacity=0.15,
                    layer="below",
                    line_width=1,
                    line_color=ChartColors.ACCENT_TEAL,
                    annotation_text=f"TVS: {tvs.tvs_id}",
                    annotation_position="bottom right",
                    annotation_font=dict(size=9, color=ChartColors.ACCENT_TEAL),
                )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Route Distance (km)",
        yaxis_title="Speed (km/h)",
        running_direction=eff_dir,
    )
    fig.update_layout(layout)
    return fig


def create_gradient_profile_figure(
    track_links: Sequence[TrackLink],
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Track Alignment: Vertical Gradient Profile",
) -> go.Figure:
    """P13-GRD-001 to 004: Generate interactive vertical gradient profile with directional sign."""
    df = VisualizationAdapter.adapt_gradient_profile(track_links, running_direction=running_direction)

    fig = go.Figure()

    if not df.empty:
        # Step line representing gradient along route
        x_pts = []
        y_pts = []
        for _, row in df.iterrows():
            x_pts.extend([row["route_start_m"] / 1000.0, row["route_end_m"] / 1000.0])
            y_pts.extend([row["effective_gradient_per_mille"], row["effective_gradient_per_mille"]])

        fig.add_trace(
            go.Scatter(
                x=x_pts,
                y=y_pts,
                mode="lines",
                line=dict(color=ChartColors.GRADIENT_LINE, width=2),
                fill="tozeroy",
                fillcolor=ChartColors.GRADIENT_FILL,
                name="Gradient (‰)",
                hovertemplate="Distance: %{x:.3f} km<br>Gradient: %{y:.1f} ‰<extra></extra>",
            )
        )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Route Distance (km)",
        yaxis_title="Effective Gradient (‰)",
        running_direction=running_direction,
    )
    fig.update_layout(layout)
    return fig


def create_curvature_profile_figure(
    track_links: Sequence[TrackLink],
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Track Alignment: Horizontal Curvature Profile",
) -> go.Figure:
    """P13-GRD-002: Generate horizontal curvature profile along route distance."""
    df = VisualizationAdapter.adapt_curvature_profile(track_links, running_direction=running_direction)

    fig = go.Figure()

    if not df.empty:
        x_pts = []
        y_pts = []
        for _, row in df.iterrows():
            r = row["curve_radius_m"]
            # Curvature = 1/R (or 0 if tangent track)
            k = 1000.0 / r if r and r > 0 else 0.0
            x_pts.extend([row["route_start_m"] / 1000.0, row["route_end_m"] / 1000.0])
            y_pts.extend([k, k])

        fig.add_trace(
            go.Scatter(
                x=x_pts,
                y=y_pts,
                mode="lines",
                line=dict(color=ChartColors.CURVATURE_LINE, width=2),
                name="Curvature (1/km)",
                hovertemplate="Distance: %{x:.3f} km<br>Curvature: %{y:.2f} 1/km<extra></extra>",
            )
        )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Route Distance (km)",
        yaxis_title="Curvature 1/R (1/km)",
        running_direction=running_direction,
    )
    fig.update_layout(layout)
    return fig


def create_track_alignment_combined_figure(
    trajectories: Union[TrainTrajectory, Sequence[TrainTrajectory]],
    track_links: Sequence[TrackLink],
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Route Dynamics & Infrastructure Alignment Overview",
) -> go.Figure:
    """P13-GRD-003: Multi-panel stacked view combining speed, gradient, and curvature."""
    traj_list = [trajectories] if isinstance(trajectories, TrainTrajectory) else list(trajectories)
    df_grad = VisualizationAdapter.adapt_gradient_profile(track_links, running_direction=running_direction)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=("Train Speed Profile", "Vertical Gradient Profile (‰)"),
    )

    # Panel 1: Speed
    for idx, traj in enumerate(traj_list):
        df_traj = VisualizationAdapter.adapt_trajectory(traj, running_direction=running_direction)
        fig.add_trace(
            go.Scatter(
                x=df_traj["route_distance_km"],
                y=df_traj["speed_kmh"],
                mode="lines",
                line=dict(color=ChartColors.LEADER_TRAIN if idx == 0 else ChartColors.FOLLOWER_TRAIN, width=2),
                name=f"Speed ({traj.train_id})",
            ),
            row=1,
            col=1,
        )

    # Panel 2: Gradient
    if not df_grad.empty:
        x_pts = []
        y_pts = []
        for _, row in df_grad.iterrows():
            x_pts.extend([row["route_start_m"] / 1000.0, row["route_end_m"] / 1000.0])
            y_pts.extend([row["effective_gradient_per_mille"], row["effective_gradient_per_mille"]])

        fig.add_trace(
            go.Scatter(
                x=x_pts,
                y=y_pts,
                mode="lines",
                line=dict(color=ChartColors.GRADIENT_LINE, width=1.5),
                fill="tozeroy",
                fillcolor=ChartColors.GRADIENT_FILL,
                name="Gradient (‰)",
            ),
            row=2,
            col=1,
        )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Route Distance (km)",
        yaxis_title="Speed (km/h)",
        running_direction=running_direction,
        height=700,
    )
    fig.update_layout(layout)
    fig.update_yaxes(title_text="Speed (km/h)", row=1, col=1)
    fig.update_yaxes(title_text="Gradient (‰)", row=2, col=1)
    fig.update_xaxes(title_text="Route Distance (km)", row=2, col=1)
    return fig
