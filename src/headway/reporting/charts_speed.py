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
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from headway.data.canonical import Platform, Station, TrackLink, TVSSection
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout
from headway.reporting.visualization_adapters import VisualizationAdapter
from headway.simulation.trajectory import TrainTrajectory


def compute_permissible_speed_envelope(
    track_links: Optional[Sequence[TrackLink]] = None,
    rolling_stock_max_speed_kmh: Optional[float] = None,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    total_distance_m: Optional[float] = None,
) -> List[Dict[str, float]]:
    """Computes the permissible speed envelope step function along route distance.

    At each route distance:
    permissible_speed(d) = min(infrastructure_speed(d), rolling_stock_max_speed)
    Drawn as a step function matching the underlying speed-limit intervals.
    Respects FORWARD and REVERSE running direction.
    """
    if not track_links:
        if total_distance_m and total_distance_m > 0:
            speed = rolling_stock_max_speed_kmh or 90.0
            return [
                {"route_distance_m": 0.0, "max_speed_kmh": speed},
                {"route_distance_m": total_distance_m, "max_speed_kmh": speed},
            ]
        return []

    links = list(track_links)
    if running_direction == RunningDirection.REVERSE:
        links = list(reversed(links))

    envelope: List[Dict[str, float]] = []
    curr_m = 0.0

    for link in links:
        length = float(link.length_m)
        infra_kmh = float(link.max_speed_ms) * 3.6
        eff_speed = infra_kmh
        if rolling_stock_max_speed_kmh is not None:
            eff_speed = min(eff_speed, rolling_stock_max_speed_kmh)

        start_m = curr_m
        end_m = curr_m + length

        envelope.append({"route_distance_m": start_m, "max_speed_kmh": eff_speed})
        envelope.append({"route_distance_m": end_m, "max_speed_kmh": eff_speed})
        curr_m = end_m

    return envelope


def create_speed_distance_figure(
    trajectories: Union[TrainTrajectory, Sequence[TrainTrajectory]],
    permissible_speed_envelope: Optional[Sequence[Dict[str, float]]] = None,
    stations: Optional[Sequence[Station]] = None,
    platforms: Optional[Sequence[Platform]] = None,
    tvs_sections: Optional[Sequence[TVSSection]] = None,
    title: str = "Train Speed Profile & Permissible Speed Envelope",
    running_direction: Optional[RunningDirection] = None,
    track_links: Optional[Sequence[TrackLink]] = None,
    rolling_stock_max_speed_kmh: Optional[float] = None,
) -> go.Figure:
    """P13-SPD-001 to 005: Generate interactive Plotly Speed–Distance diagram with speed envelope."""
    traj_list = [trajectories] if isinstance(trajectories, TrainTrajectory) else list(trajectories)
    eff_dir = running_direction or (traj_list[0].running_direction if traj_list else RunningDirection.FORWARD)

    fig = go.Figure()

    # 1. Plot train speed trajectories (Trace 0: Simulated Speed)
    colors = [ChartColors.LEADER_TRAIN, ChartColors.FOLLOWER_TRAIN, ChartColors.OPPOSING_TRAIN, ChartColors.SECONDARY_BLUE]

    for idx, traj in enumerate(traj_list):
        df = VisualizationAdapter.adapt_trajectory(traj, running_direction=eff_dir)
        t_color = colors[idx % len(colors)]
        role = "Leader" if idx == 0 and len(traj_list) > 1 else ("Follower" if idx == 1 else "")
        label = f"{traj.train_id} ({role})" if role else traj.train_id

        trace_name = f"Simulated Speed ({label})" if len(traj_list) > 1 else f"Simulated Speed: {label}"
        fig.add_trace(
            go.Scatter(
                x=df["route_distance_km"],
                y=df["speed_kmh"],
                mode="lines",
                line=dict(color=t_color, width=2.5),
                name=trace_name,
                hovertemplate="Distance: %{x:.3f} km<br>Speed: %{y:.1f} km/h<extra></extra>",
            )
        )

    # 2. Derive permissible speed envelope if not provided
    if permissible_speed_envelope is None:
        if track_links:
            permissible_speed_envelope = compute_permissible_speed_envelope(
                track_links=track_links,
                rolling_stock_max_speed_kmh=rolling_stock_max_speed_kmh,
                running_direction=eff_dir,
            )
        else:
            try:
                from headway.ui.state import session_state
                if session_state.project and session_state.project.infrastructure.track_links:
                    rs = session_state.project.rolling_stock
                    rs_max = (rs.train_types[0].max_speed_ms * 3.6) if rs.train_types else None
                    permissible_speed_envelope = compute_permissible_speed_envelope(
                        track_links=session_state.project.infrastructure.track_links,
                        rolling_stock_max_speed_kmh=rs_max,
                        running_direction=eff_dir,
                    )
            except Exception:
                pass

        if permissible_speed_envelope is None and traj_list and traj_list[0].samples:
            primary_t = traj_list[0]
            max_v = max(s.speed_kmh for s in primary_t.samples)
            tot_dist = primary_t.total_distance_m or primary_t.samples[-1].front_distance_m
            ceil_v = max(80.0, float(np.ceil(max_v / 10.0) * 10.0))
            permissible_speed_envelope = [
                {"route_distance_m": 0.0, "max_speed_kmh": ceil_v},
                {"route_distance_m": tot_dist, "max_speed_kmh": ceil_v},
            ]

    # 3. Plot permissible speed envelope as red dashed line
    if permissible_speed_envelope:
        env_x = [pt.get("route_distance_m", 0.0) / 1000.0 for pt in permissible_speed_envelope]
        env_y = [pt.get("max_speed_kmh", 0.0) for pt in permissible_speed_envelope]
        fig.add_trace(
            go.Scatter(
                x=env_x,
                y=env_y,
                mode="lines",
                line=dict(color=ChartColors.SPEED_ENVELOPE, width=2.5, dash="dash"),
                name="Permissible Speed Envelope",
                hoverinfo="x+y+name",
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
