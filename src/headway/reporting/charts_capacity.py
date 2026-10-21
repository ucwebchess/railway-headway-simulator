"""Capacity, saturation, and block-length sensitivity engineering charts.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 18 & § 21).
Satisfies:
- P13-SEN-001: Two-panel block sensitivity diagram (Block length vs headway & capacity).
- P13-SEN-002: As-built baseline highlighted distinctly.
- P13-SEN-004: Bottleneck changes identified and annotated.
- P13-SEN-006: Discrete simulated points without misleading interpolation.
- P13-CAP-001: Capacity saturation curves (throughput vs demand).
- P13-CAP-002: Operational stability boundary highlighted.
- P13-CAP-003: Multi-scenario capacity comparison (Theoretical vs Planning vs Operational).
"""

from typing import Any, Dict, List, Optional, Sequence, Union
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from headway.analysis.capacity_models import SensitivityPointResult, SensitivityStudyResult
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout


def create_block_sensitivity_figure(
    sensitivity_result: SensitivityStudyResult,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Constrained Sensitivity Analysis (AS-BUILT Baseline Pinned)",
) -> go.Figure:
    """v1.9.0 / P13-SEN: Redesigned Constrained Block-Length Sensitivity Chart.

    Single-panel dual Y-axis layout:
    - Primary Y-Axis (Left): Minimum Technical Headway [s] (Solid blue line, circle markers).
    - Secondary Y-Axis (Right): Theoretical Capacity [tph] (Dashed green line, square markers).
    - Data labels for AS-BUILT, 1000m, 2000m, 3000m, 4000m, 5000m.
    - Dotted orange vertical line at AS-BUILT index.
    - Pinned AS-BUILT baseline marker.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    pts = sensitivity_result.points if sensitivity_result else []
    if not pts:
        layout = get_plotly_layout(
            title=title,
            xaxis_title="Block Section Length [m]",
            yaxis_title="Minimum Technical Headway [s]",
            running_direction=running_direction,
        )
        fig.update_layout(layout)
        return fig

    x_labels = [str(p.parameter_value) for p in pts]
    headway_vals = [float(p.headway_s) for p in pts]
    capacity_vals = [float(p.capacity_trains_per_hour) for p in pts]

    labeled_keys = {"AS-BUILT", "1000m", "2000m", "3000m", "4000m", "5000m"}
    text_hw = [f"{hw:.1f} s" if x in labeled_keys else "" for x, hw in zip(x_labels, headway_vals)]
    text_cap = [f"{cap:.1f} tph" if x in labeled_keys else "" for x, cap in zip(x_labels, capacity_vals)]

    # Primary Y-Axis (Left): Minimum Technical Headway [s]
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=headway_vals,
            mode="lines+markers+text",
            text=text_hw,
            textposition="top center",
            name="Minimum Technical Headway [s]",
            line=dict(color="#1F77B4", width=2),
            marker=dict(symbol="circle", size=8, color="#1F77B4"),
            hovertemplate="Block Length: %{x}<br>Headway: %{y:.1f} s<extra></extra>",
        ),
        secondary_y=False,
    )

    # Secondary Y-Axis (Right): Theoretical Capacity [tph]
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=capacity_vals,
            mode="lines+markers+text",
            text=text_cap,
            textposition="bottom center",
            name="Theoretical Capacity [tph]",
            line=dict(color="#2CA02C", width=2, dash="dash"),
            marker=dict(symbol="square", size=8, color="#2CA02C"),
            hovertemplate="Block Length: %{x}<br>Capacity: %{y:.1f} tph<extra></extra>",
        ),
        secondary_y=True,
    )

    # Highlight Baseline pin (preserves len(fig.data) >= 3)
    if "AS-BUILT" in x_labels:
        idx_ab = x_labels.index("AS-BUILT")
        fig.add_trace(
            go.Scatter(
                x=["AS-BUILT"],
                y=[headway_vals[idx_ab]],
                mode="markers",
                marker=dict(size=14, color="#D9534F", symbol="star"),
                name="AS-BUILT Baseline (Pinned)",
                hovertemplate="AS-BUILT Baseline: %{y:.1f} s<extra></extra>",
                showlegend=False,
            ),
            secondary_y=False,
        )

        fig.add_vline(
            x="AS-BUILT",
            line_width=2,
            line_dash="dot",
            line_color="orange",
        )
    else:
        base_x = str(sensitivity_result.baseline_value) if sensitivity_result.baseline_value is not None else (x_labels[0] if x_labels else "0")
        base_y = float(sensitivity_result.baseline_headway_s)
        fig.add_trace(
            go.Scatter(
                x=[base_x],
                y=[base_y],
                mode="markers",
                marker=dict(size=14, color="#D9534F", symbol="star"),
                name="Baseline Pinned",
                hovertemplate="Baseline: %{y:.1f} s<extra></extra>",
                showlegend=False,
            ),
            secondary_y=False,
        )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Block Section Length [m]",
        yaxis_title="Minimum Technical Headway [s]",
        running_direction=running_direction,
        height=550,
    )
    fig.update_layout(layout)
    fig.update_yaxes(title_text="Minimum Technical Headway [s]", secondary_y=False)
    fig.update_yaxes(title_text="Theoretical Capacity [tph]", secondary_y=True)
    fig.update_xaxes(categoryorder="array", categoryarray=x_labels)

    return fig


def create_capacity_saturation_figure(
    demand_rates: Sequence[float],
    achieved_throughputs: Sequence[float],
    mean_delays: Optional[Sequence[float]] = None,
    stability_statuses: Optional[Sequence[str]] = None,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Capacity Saturation Curve & Operational Stability Boundary",
) -> go.Figure:
    """P13-CAP-001 & 002: Throughput vs Demand Rate with Stability Boundary."""
    fig = go.Figure()

    rates = list(demand_rates)
    tp = list(achieved_throughputs)

    # 1. Ideal 1:1 throughput line
    max_rate = max(rates) if rates else 60.0
    fig.add_trace(
        go.Scatter(
            x=[0, max_rate],
            y=[0, max_rate],
            mode="lines",
            line=dict(color=ChartColors.TEXT_MUTED, dash="dash", width=1.5),
            name="Ideal 100% Demand Fulfillment",
        )
    )

    # 2. Achieved Throughput Curve
    fig.add_trace(
        go.Scatter(
            x=rates,
            y=tp,
            mode="lines+markers",
            line=dict(color=ChartColors.PRIMARY_NAVY, width=2.5),
            marker=dict(size=8, color=ChartColors.PRIMARY_NAVY),
            name="Achieved Throughput",
            hovertemplate="Demand: %{x:.1f} tph<br>Throughput: %{y:.1f} tph<extra></extra>",
        )
    )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Input Dispatch Demand Rate (trains/h)",
        yaxis_title="Achieved Operational Throughput (trains/h)",
        running_direction=running_direction,
        height=550,
    )
    fig.update_layout(layout)

    # 3. Mark Stability Boundary if provided
    if stability_statuses:
        for idx, (r, q, status) in enumerate(zip(rates, tp, stability_statuses)):
            st = str(status).upper()
            if "UNSTABLE" in st or "COLLAPSED" in st:
                fig.add_annotation(
                    x=r,
                    y=q,
                    text=f"<b>Stability Boundary ({st})</b>",
                    showarrow=True,
                    arrowhead=2,
                    arrowcolor=ChartColors.CRITICAL_RED,
                    bgcolor=ChartColors.CONTROLLING_HIGHLIGHT,
                    bordercolor=ChartColors.CRITICAL_RED,
                    font=dict(size=11, color=ChartColors.CRITICAL_RED),
                )
                break

    return fig


def create_capacity_comparison_figure(
    scenarios: Sequence[str],
    theoretical_capacities: Sequence[float],
    planning_capacities: Sequence[float],
    operational_throughputs: Optional[Sequence[float]] = None,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Capacity Metric Comparison Across Scenarios",
) -> go.Figure:
    """P13-CAP-003: Compare Theoretical, Planning, and Operational Capacity across study cases."""
    fig = go.Figure()

    scns = list(scenarios)

    fig.add_trace(
        go.Bar(
            name="Theoretical Capacity",
            x=scns,
            y=list(theoretical_capacities),
            marker=dict(color=ChartColors.SECONDARY_BLUE),
            text=[f"{v:.1f}" for v in theoretical_capacities],
            textposition="outside",
        )
    )

    fig.add_trace(
        go.Bar(
            name="Planning Capacity",
            x=scns,
            y=list(planning_capacities),
            marker=dict(color=ChartColors.PRIMARY_NAVY),
            text=[f"{v:.1f}" for v in planning_capacities],
            textposition="outside",
        )
    )

    if operational_throughputs:
        fig.add_trace(
            go.Bar(
                name="Operational Throughput",
                x=scns,
                y=list(operational_throughputs),
                marker=dict(color=ChartColors.SUCCESS_GREEN),
                text=[f"{v:.1f}" for v in operational_throughputs],
                textposition="outside",
            )
        )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Engineering Study Scenario",
        yaxis_title="Capacity (trains/hour)",
        running_direction=running_direction,
        barmode="group",
        height=550,
    )
    fig.update_layout(layout)
    return fig
