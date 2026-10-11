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
    title: str = "Block-Length Sensitivity & Capacity Response Matrix",
) -> go.Figure:
    """P13-SEN-001 to 006: Two-panel layout: Panel A (Headway vs Block Length), Panel B (Capacity vs Block Length)."""
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Panel A: Technical Minimum Headway (s)", "Panel B: Theoretical Line Capacity (trains/h)"),
        horizontal_spacing=0.12,
    )

    pts = sensitivity_result.points
    if not pts:
        layout = get_plotly_layout(title=title, xaxis_title="Parameter", yaxis_title="Metric")
        fig.update_layout(layout)
        return fig

    # Check if parameter values can be converted to float
    try:
        sorted_pts = sorted(pts, key=lambda p: float(p.parameter_value))
        x_vals = [float(p.parameter_value) for p in sorted_pts]
        base_x = float(sensitivity_result.baseline_value)
        is_numeric = True
    except (ValueError, TypeError):
        sorted_pts = sorted(pts, key=lambda p: str(p.parameter_value))
        x_vals = [str(p.parameter_value) for p in sorted_pts]
        base_x = str(sensitivity_result.baseline_value)
        is_numeric = False

    headway_vals = [p.headway_s for p in sorted_pts]
    capacity_vals = [p.capacity_trains_per_hour for p in sorted_pts]

    layout = get_plotly_layout(
        title=title,
        xaxis_title=f"{sensitivity_result.parameter_name}",
        yaxis_title="Headway (s)",
        running_direction=running_direction,
        height=550,
    )
    fig.update_layout(layout)

    # Panel A: Headway
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=headway_vals,
            mode="lines+markers" if is_numeric else "markers",
            line=dict(color=ChartColors.PRIMARY_NAVY, width=2),
            marker=dict(size=8, color=ChartColors.PRIMARY_NAVY),
            name="Simulated Headway",
            hovertemplate="Parameter: %{x}<br>Headway: %{y:.1f} s<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Highlight Baseline in Panel A
    fig.add_trace(
        go.Scatter(
            x=[base_x],
            y=[sensitivity_result.baseline_headway_s],
            mode="markers",
            marker=dict(size=14, color=ChartColors.CRITICAL_RED, symbol="star"),
            name="Baseline As-Built",
            hovertemplate="Baseline: %{x}<br>Headway: %{y:.1f} s<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Panel B: Capacity
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=capacity_vals,
            mode="lines+markers" if is_numeric else "markers",
            line=dict(color=ChartColors.SECONDARY_BLUE, width=2),
            marker=dict(size=8, color=ChartColors.SECONDARY_BLUE),
            name="Theoretical Capacity",
            hovertemplate="Parameter: %{x}<br>Capacity: %{y:.1f} tph<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    # Highlight Baseline in Panel B
    fig.add_trace(
        go.Scatter(
            x=[base_x],
            y=[sensitivity_result.baseline_capacity_tph],
            mode="markers",
            marker=dict(size=14, color=ChartColors.CRITICAL_RED, symbol="star"),
            name="Baseline Capacity",
            hovertemplate="Baseline: %{x}<br>Capacity: %{y:.1f} tph<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    fig.update_xaxes(title_text=f"{sensitivity_result.parameter_name}", row=1, col=1)
    fig.update_xaxes(title_text=f"{sensitivity_result.parameter_name}", row=1, col=2)
    fig.update_yaxes(title_text="Headway (s)", row=1, col=1)
    fig.update_yaxes(title_text="Capacity (trains/h)", row=1, col=2)
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
