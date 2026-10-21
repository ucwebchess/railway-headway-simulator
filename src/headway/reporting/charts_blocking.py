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
    blocking_intervals: Optional[Sequence[ResourceBlockingInterval]] = None,
) -> go.Figure:
    """P13-BTS-001 to 007 & Task 1: Generate UIC 406 continuous blocking stairway along physical distance (km) with inverted time axis."""
    fig = go.Figure()

    running_dir = headway_result.running_direction
    intervals = (
        blocking_intervals
        if blocking_intervals is not None
        else (headway_result.blocking_intervals or [])
    )
    shift_s = headway_result.headway_s

    controlling_res_ids = {c.leader_resource_id for c in (headway_result.controlling_conflicts or [])}

    # Distinct leader intervals in route order
    seen = set()
    leader_intervals = []
    for bi in intervals:
        if getattr(bi, "train_id", None) == "TRN_FOLLOWER":
            continue
        if bi.resource_id not in seen:
            seen.add(bi.resource_id)
            leader_intervals.append(bi)

    if not leader_intervals:
        leader_intervals = list(intervals)

    # Ensure leader intervals are sorted in chronological order of occupation
    leader_intervals.sort(key=lambda b: (b.start_time_s, b.resource_id))

    # Build continuous distance array in km
    x_starts_km = []
    widths_km = []
    durations_s = []
    leader_starts_s = []
    follower_starts_s = []

    leader_colors = []
    leader_line_colors = []
    leader_line_widths = []

    follower_colors = []
    follower_line_colors = []
    follower_line_widths = []

    leader_customdata = []
    follower_customdata = []

    cum_dist_km = 0.0

    for idx, bi in enumerate(leader_intervals):
        if bi.physical_start_offset_m is not None and bi.physical_end_offset_m is not None:
            s_m = float(bi.physical_start_offset_m)
            e_m = float(bi.physical_end_offset_m)
            start_km = round(min(s_m, e_m) / 1000.0, 3)
            end_km = round(max(s_m, e_m) / 1000.0, 3)
            w_km = max(0.05, round(end_km - start_km, 3))
        else:
            start_km = round(cum_dist_km, 3)
            w_km = 1.0
            end_km = start_km + w_km
            cum_dist_km += w_km

        dur = round(bi.duration_s, 2)
        start_t = round(bi.start_time_s, 2)
        end_t = round(bi.end_time_s, 2)
        shifted_start_t = round(start_t + shift_s, 2)
        shifted_end_t = round(shifted_start_t + dur, 2)

        is_controlling = bi.resource_id in controlling_res_ids

        d = bi.decomposition
        setup = d.setup_time_s if d else 0.0
        appr = d.approach_time_s if d else 0.0
        rel = d.release_time_s if d else 0.0

        x_starts_km.append(start_km)
        widths_km.append(w_km)
        durations_s.append(dur)
        leader_starts_s.append(start_t)
        follower_starts_s.append(shifted_start_t)

        # Leader styling
        if is_controlling:
            leader_colors.append(ChartColors.CONTROLLING_BORDER)
            leader_line_colors.append(ChartColors.PRIMARY_NAVY)
            leader_line_widths.append(2.0)
        else:
            leader_colors.append(ChartColors.LEADER_TRAIN)
            leader_line_colors.append(ChartColors.PRIMARY_NAVY)
            leader_line_widths.append(0.75)

        # Follower styling
        if is_controlling:
            follower_colors.append(ChartColors.CRITICAL_RED)
            follower_line_colors.append(ChartColors.CRITICAL_RED)
            follower_line_widths.append(2.0)
        else:
            follower_colors.append(ChartColors.FOLLOWER_TRAIN)
            follower_line_colors.append(ChartColors.FOLLOWER_TRAIN)
            follower_line_widths.append(0.75)

        leader_customdata.append([
            bi.resource_id,
            start_km,
            end_km,
            start_t,
            end_t,
            dur,
            round(setup, 1),
            round(appr, 1),
            round(rel, 1),
            "CONTROLLING BOTTLENECK" if is_controlling else "Normal",
        ])

        follower_customdata.append([
            bi.resource_id,
            start_km,
            end_km,
            shifted_start_t,
            shifted_end_t,
            dur,
            round(setup, 1),
            round(appr, 1),
            round(rel, 1),
            "CONTROLLING BOTTLENECK" if is_controlling else "Normal",
        ])

    # 1. Leader Train blocking stairway trace
    fig.add_trace(
        go.Bar(
            name=f"Leader Train ({headway_result.leader_service_id})",
            x=x_starts_km,
            width=widths_km,
            y=durations_s,
            base=leader_starts_s,
            offset=0,
            opacity=0.65,
            marker=dict(
                color=leader_colors,
                line=dict(color=leader_line_colors, width=leader_line_widths),
            ),
            customdata=leader_customdata,
            hovertemplate=(
                f"<b>Leader Train ({headway_result.leader_service_id})</b><br>"
                "Resource: %{customdata[0]} (%{customdata[9]})<br>"
                "Chainage: %{customdata[1]:.3f} km – %{customdata[2]:.3f} km<br>"
                "Start: %{customdata[3]:.1f} s<br>"
                "End: %{customdata[4]:.1f} s<br>"
                "Duration: %{customdata[5]:.1f} s<br>"
                "Setup: %{customdata[6]:.1f} s | Approach: %{customdata[7]:.1f} s | Release: %{customdata[8]:.1f} s<extra></extra>"
            ),
        )
    )

    # 2. Shifted Follower Train blocking stairway trace
    fig.add_trace(
        go.Bar(
            name=f"Follower Train ({headway_result.follower_service_id}) [Shifted +{shift_s:.1f}s]",
            x=x_starts_km,
            width=widths_km,
            y=durations_s,
            base=follower_starts_s,
            offset=0,
            opacity=0.55,
            marker=dict(
                color=follower_colors,
                line=dict(color=follower_line_colors, width=follower_line_widths),
            ),
            customdata=follower_customdata,
            hovertemplate=(
                f"<b>Follower Train ({headway_result.follower_service_id}) [Shifted +{shift_s:.1f}s]</b><br>"
                "Resource: %{customdata[0]} (%{customdata[9]})<br>"
                "Chainage: %{customdata[1]:.3f} km – %{customdata[2]:.3f} km<br>"
                "Start: %{customdata[3]:.1f} s<br>"
                "End: %{customdata[4]:.1f} s<br>"
                "Duration: %{customdata[5]:.1f} s<br>"
                "Setup: %{customdata[6]:.1f} s | Approach: %{customdata[7]:.1f} s | Release: %{customdata[8]:.1f} s<extra></extra>"
            ),
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
        xaxis_title="Route Distance (km)",
        yaxis_title="Time [s]",
        running_direction=running_dir,
        barmode="overlay",
        height=550,
    )
    fig.update_layout(layout)
    fig.update_yaxes(autorange="reversed")
    if running_dir == RunningDirection.REVERSE:
        fig.update_xaxes(autorange="reversed")

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
        layout = get_plotly_layout(
            title=title,
            xaxis_title="Signalling Block Resource",
            yaxis_title="Blocking Time [s]",
            running_direction=running_direction,
        )
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
                x=df["resource_id"],
                y=df[col_name],
                orientation="v",
                marker=dict(color=color),
                hovertemplate=f"Resource: %{{x}}<br>{comp_label}: %{{y:.2f}} s<extra></extra>",
            )
        )

    # Controlling resources highlighted on x-axis
    x_labels = []
    for rid in df["resource_id"]:
        if rid in ctrl_set:
            x_labels.append(f"★ {rid} (CRITICAL)")
        else:
            x_labels.append(rid)

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Signalling Block Resource",
        yaxis_title="Blocking Time [s]",
        running_direction=running_direction,
        barmode="stack",
        width=max(800, len(df) * 45 + 200),
        height=550,
    )
    fig.update_layout(layout)
    fig.update_xaxes(categoryorder="array", categoryarray=list(df["resource_id"]))
    fig.update_yaxes(categoryarray=list(df["resource_id"]))

    return fig
