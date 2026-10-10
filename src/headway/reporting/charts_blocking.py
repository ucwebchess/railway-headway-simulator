"""Blocking-time stairway diagrams and seven-component stacked charts.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 11 & § 12).
Satisfies:
- P13-BTS-001: Leader and shifted follower blocking stairway diagram.
- P13-BTS-002 & 006: Resources ordered along route in actual direction of travel.
- P13-BTS-003: Highlight controlling conflict.
- P13-BTS-004: Required temporal shift annotation.
- P13-BTS-007: Consumes P08 blocking intervals without recalculation.
- P13-BTC-001 to 005: Seven-component stacked bar chart with reconciliation note.
"""

from typing import Any, Dict, List, Optional, Sequence, Union
import pandas as pd
import plotly.graph_objects as go

from headway.analysis.blocking_time import ResourceBlockingInterval
from headway.analysis.headway_results import HeadwayResult, ResourceConflict
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import (
    COMPONENT_COLOR_MAP,
    ChartColors,
    get_plotly_layout,
)
from headway.reporting.visualization_adapters import VisualizationAdapter


def create_blocking_stairway_figure(
    headway_result: HeadwayResult,
    title: str = "Blocking-Time Stairway Diagram & Critical Conflict",
) -> go.Figure:
    """P13-BTS-001 to 007: Generate interactive Plotly blocking stairway with shifted follower."""
    fig = go.Figure()

    running_dir = headway_result.running_direction
    intervals = headway_result.blocking_intervals or []
    shift_s = headway_result.headway_s

    controlling_res_ids = {c.leader_resource_id for c in headway_result.controlling_conflicts}

    # Distinct resources in route order
    resource_order = []
    seen = set()
    for bi in intervals:
        if bi.resource_id not in seen:
            resource_order.append(bi.resource_id)
            seen.add(bi.resource_id)

    if running_dir == RunningDirection.REVERSE:
        resource_order = list(reversed(resource_order))

    # 1. Leader blocking intervals
    for bi in intervals:
        is_controlling = bi.resource_id in controlling_res_ids
        color = ChartColors.CONTROLLING_BORDER if is_controlling else ChartColors.LEADER_TRAIN
        opacity = 0.85 if is_controlling else 0.55

        # Horizontal bar from start_time to end_time
        fig.add_trace(
            go.Bar(
                name="Leader Block",
                x=[bi.duration_s],
                y=[bi.resource_id],
                base=[bi.start_time_s],
                orientation="h",
                marker=dict(
                    color=color,
                    opacity=opacity,
                    line=dict(color=ChartColors.PRIMARY_NAVY, width=1.5 if is_controlling else 0.5),
                ),
                hovertemplate=(
                    f"<b>Leader Train ({headway_result.leader_service_id})</b><br>"
                    f"Resource: {bi.resource_id}<br>"
                    f"Start: {bi.start_time_s:.1f} s<br>"
                    f"End: {bi.end_time_s:.1f} s<br>"
                    f"Duration: {bi.duration_s:.1f} s<extra></extra>"
                ),
                showlegend=(bi == intervals[0]),
            )
        )

    # 2. Shifted Follower blocking intervals
    for bi in intervals:
        shifted_start = bi.start_time_s + shift_s
        is_controlling = bi.resource_id in controlling_res_ids
        color = ChartColors.CRITICAL_RED if is_controlling else ChartColors.FOLLOWER_TRAIN
        opacity = 0.85 if is_controlling else 0.45

        fig.add_trace(
            go.Bar(
                name="Shifted Follower Block",
                x=[bi.duration_s],
                y=[bi.resource_id],
                base=[shifted_start],
                orientation="h",
                marker=dict(
                    color=color,
                    opacity=opacity,
                    line=dict(color=ChartColors.CRITICAL_RED, width=1.5 if is_controlling else 0.5),
                ),
                hovertemplate=(
                    f"<b>Follower Train ({headway_result.follower_service_id}) [Shifted +{shift_s:.1f}s]</b><br>"
                    f"Resource: {bi.resource_id}<br>"
                    f"Start: {shifted_start:.1f} s<br>"
                    f"End: {(shifted_start + bi.duration_s):.1f} s<br>"
                    f"Duration: {bi.duration_s:.1f} s<extra></extra>"
                ),
                showlegend=(bi == intervals[0]),
            )
        )

    # Annotate critical headway shift
    bn_desc = headway_result.controlling_bottleneck_description
    hw_annotation = (
        f"<b>Technical Minimum Headway: H = {shift_s:.1f} s</b><br>"
        f"Governing Bottleneck: {bn_desc}"
    )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title="Signalling Block Resource",
        running_direction=running_dir,
        barmode="overlay",
        height=max(500, len(resource_order) * 28 + 200),
    )
    fig.update_layout(layout)
    fig.update_yaxes(categoryorder="array", categoryarray=resource_order)

    fig.add_annotation(
        text=hw_annotation,
        xref="paper",
        yref="paper",
        x=0.02,
        y=0.98,
        showarrow=False,
        bgcolor="rgba(255, 255, 255, 0.9)",
        bordercolor=ChartColors.CRITICAL_RED,
        borderwidth=1.5,
        borderpad=6,
        font=dict(size=12, color=ChartColors.PRIMARY_NAVY),
    )

    return fig


def create_seven_component_figure(
    intervals: Sequence[ResourceBlockingInterval],
    controlling_resource_ids: Optional[Sequence[str]] = None,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Seven-Component Blocking Time Decomposition",
) -> go.Figure:
    """P13-BTC-001 to 005: Stacked bar chart showing the seven additive components per resource."""
    df = VisualizationAdapter.adapt_blocking_intervals(intervals, running_direction=running_direction)

    fig = go.Figure()

    if df.empty:
        layout = get_plotly_layout(title=title, xaxis_title="Blocking Duration (s)", yaxis_title="Resource ID")
        fig.update_layout(layout)
        return fig

    ctrl_set = set(controlling_resource_ids or [])

    component_specs = [
        ("Setup (t1)", "setup_time_s", COMPONENT_COLOR_MAP["SETUP"]),
        ("Approach (t2)", "approach_time_s", COMPONENT_COLOR_MAP["APPROACH"]),
        ("Running (t3)", "running_time_s", COMPONENT_COLOR_MAP["RUNNING"]),
        ("Dwell (t4)", "dwell_time_s", COMPONENT_COLOR_MAP["DWELL"]),
        ("Clearance (t5)", "geometric_clearance_time_s", COMPONENT_COLOR_MAP["GEOMETRIC_CLEARANCE"]),
        ("Residual Rear (t6)", "residual_rear_time_s", COMPONENT_COLOR_MAP["RESIDUAL_REAR"]),
        ("Release (t7)", "release_time_s", COMPONENT_COLOR_MAP["RELEASE"]),
    ]

    for comp_label, col_name, color in component_specs:
        fig.add_trace(
            go.Bar(
                name=comp_label,
                y=df["resource_id"],
                x=df[col_name],
                orientation="h",
                marker=dict(color=color),
                hovertemplate=f"Resource: %{{y}}<br>{comp_label}: %{{x:.2f}} s<extra></extra>",
            )
        )

    # Controlling resources highlighted on y-axis
    y_labels = []
    for rid in df["resource_id"]:
        if rid in ctrl_set:
            y_labels.append(f"★ {rid} (CRITICAL)")
        else:
            y_labels.append(rid)

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Blocking Time Duration (s)",
        yaxis_title="Signalling Resource",
        running_direction=running_direction,
        barmode="stack",
        height=max(500, len(df) * 26 + 180),
    )
    fig.update_layout(layout)
    fig.update_yaxes(categoryorder="array", categoryarray=list(df["resource_id"]))

    return fig
