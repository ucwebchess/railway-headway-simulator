"""Time–distance operational diagrams and mixed-traffic headway heatmaps.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 10 & § 15).
Satisfies:
- P13-TDD-001 to 005: Multi-train time-distance operational diagram.
- P13-MIX-001 to 007: Directional mixed-traffic headway matrix heatmap (Rows = Leaders, Cols = Followers).
- Support for opposing-direction train visualization.
"""

from typing import Any, Dict, List, Optional, Sequence, Union
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from headway.analysis.headway_results import MixedTrafficHeadwayMatrix
from headway.data.canonical import Platform, Station
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout
from headway.reporting.visualization_adapters import VisualizationAdapter
from headway.simulation.trajectory import TrainTrajectory


def create_time_distance_figure(
    trajectories: Union[TrainTrajectory, Sequence[TrainTrajectory]],
    stations: Optional[Sequence[Station]] = None,
    platforms: Optional[Sequence[Platform]] = None,
    title: str = "Time–Distance Operational Trajectory Diagram",
    running_direction: Optional[RunningDirection] = None,
) -> go.Figure:
    """P13-TDD-001 to 005: Generate interactive Plotly Time–Distance diagram."""
    traj_list = [trajectories] if isinstance(trajectories, TrainTrajectory) else list(trajectories)
    eff_dir = running_direction or (traj_list[0].running_direction if traj_list else RunningDirection.FORWARD)

    fig = go.Figure()

    # 1. Station horizontal lines
    if stations and platforms:
        stn_map = {s.station_id: s.name for s in stations}
        for plat in platforms:
            stn_name = stn_map.get(plat.station_id, plat.station_id)
            pos_km = plat.start_offset_m / 1000.0
            fig.add_hline(
                y=pos_km,
                line_dash="dot",
                line_color=ChartColors.GRID_LIGHT,
                annotation_text=f"Stn: {stn_name}",
                annotation_position="bottom right",
                annotation_font=dict(size=10, color=ChartColors.TEXT_MUTED),
            )

    # 2. Plot train trajectories
    colors = [ChartColors.LEADER_TRAIN, ChartColors.FOLLOWER_TRAIN, ChartColors.OPPOSING_TRAIN, ChartColors.SECONDARY_BLUE]

    for idx, traj in enumerate(traj_list):
        df = VisualizationAdapter.adapt_trajectory(traj)
        is_opposing = (traj.running_direction != eff_dir)
        t_color = ChartColors.OPPOSING_TRAIN if is_opposing else colors[idx % len(colors)]
        line_style = "dash" if is_opposing else "solid"

        dir_tag = f"[{traj.running_direction.value}]"
        label = f"{traj.train_id} {dir_tag}"

        fig.add_trace(
            go.Scatter(
                x=df["time_s"],
                y=df["route_distance_km"],
                mode="lines",
                line=dict(color=t_color, width=2.5, dash=line_style),
                name=label,
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    "Time: %{x:.1f} s<br>"
                    "Distance: %{y:.3f} km<extra></extra>"
                ),
            )
        )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title="Route Distance (km)",
        running_direction=eff_dir,
    )
    fig.update_layout(layout)
    return fig


def create_mixed_traffic_heatmap(
    headway_matrix: MixedTrafficHeadwayMatrix,
    title: Optional[str] = None,
) -> go.Figure:
    """P13-MIX-001 to 007: Directional mixed-traffic headway matrix heatmap."""
    dir_val = headway_matrix.running_direction.value
    fig_title = title or f"Mixed-Traffic Technical Headway Matrix [{dir_val}]"

    service_ids = headway_matrix.service_ids
    n = len(service_ids)

    # Build 2D grid: rows = leaders, cols = followers (P13-MIX-002)
    z_values: List[List[Optional[float]]] = []
    text_labels: List[List[str]] = []

    for leader in service_ids:
        row_z = []
        row_text = []
        for follower in service_ids:
            hw = headway_matrix.get_headway(leader, follower)
            if hw is not None and math.isfinite(hw) and hw > 0:
                row_z.append(round(hw, 1))
                row_text.append(f"{hw:.1f} s")
            else:
                row_z.append(None)
                row_text.append("INFEASIBLE")
        z_values.append(row_z)
        text_labels.append(row_text)

    fig = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=service_ids,  # Columns = follower services
            y=service_ids,  # Rows = leader services
            text=text_labels,
            texttemplate="%{text}",
            textfont={"size": 13, "color": "black"},
            colorscale="Blues",
            colorbar=dict(title=dict(text="Headway (s)", font=dict(size=12))),
            hoverongaps=False,
            hovertemplate=(
                "Leader: %{y}<br>"
                "Follower: %{x}<br>"
                "Headway: %{text}<extra></extra>"
            ),
        )
    )

    layout = get_plotly_layout(
        title=fig_title,
        xaxis_title="Follower Service",
        yaxis_title="Leader Service",
        running_direction=headway_matrix.running_direction,
        height=max(450, n * 50 + 200),
        width=max(550, n * 70 + 200),
    )
    fig.update_layout(layout)
    fig.update_yaxes(autorange="reversed")  # First leader at top
    return fig

import math
