"""Stochastic simulation, quantile distribution, and reliability charts.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 22).
Satisfies:
- P13-STC-001: Histograms of headway, journey time, delay, and TVS queue times.
- P13-STC-002: Empirical cumulative distribution functions (CDF).
- P13-STC-003: Box plots for key operational metrics.
- P13-STC-004: Confidence intervals for sample means (Student's t) and punctuality (Wilson score).
- P13-STC-005: Operational reliability vs demand rate curves with threshold lines.
- P13-STC-006: Directional distribution support (FORWARD vs REVERSE).
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
import plotly.graph_objects as go

from headway.analysis.monte_carlo import MonteCarloExecutionResult
from headway.analysis.statistics import StatisticalSummary
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout


def create_stochastic_histogram_figure(
    values: Sequence[float],
    metric_name: str = "Headway",
    unit: str = "s",
    summary: Optional[StatisticalSummary] = None,
    nbins: int = 30,
    running_direction: Optional[RunningDirection] = None,
    title: Optional[str] = None,
) -> go.Figure:
    """P13-STC-001: Generate stochastic metric frequency histogram with percentile lines."""
    clean_vals = [v for v in values if v is not None and np.isfinite(v)]
    fig_title = title or f"Stochastic Distribution of Simulated {metric_name}"

    fig = go.Figure()

    layout = get_plotly_layout(
        title=fig_title,
        xaxis_title=f"{metric_name} ({unit})",
        yaxis_title="Simulation Replication Frequency",
        running_direction=running_direction,
        height=500,
    )
    fig.update_layout(layout)

    if clean_vals:
        fig.add_trace(
            go.Histogram(
                x=clean_vals,
                nbinsx=nbins,
                marker=dict(color=ChartColors.SECONDARY_BLUE, line=dict(color=ChartColors.PRIMARY_NAVY, width=1)),
                opacity=0.75,
                name=metric_name,
                hovertemplate=f"{metric_name}: %{{x:.2f}} {unit}<br>Count: %{{y}}<extra></extra>",
            )
        )

        mean_val = summary.mean if summary else float(np.mean(clean_vals))
        p50_val = summary.p50 if summary else float(np.percentile(clean_vals, 50))
        p95_val = summary.p95 if summary else float(np.percentile(clean_vals, 95))

        # Mean vertical line
        fig.add_vline(
            x=mean_val,
            line_dash="dash",
            line_color=ChartColors.PRIMARY_NAVY,
            annotation_text=f"Mean: {mean_val:.1f} {unit}",
            annotation_position="top left",
        )

        # P95 vertical line
        fig.add_vline(
            x=p95_val,
            line_dash="dot",
            line_color=ChartColors.CRITICAL_RED,
            annotation_text=f"P95: {p95_val:.1f} {unit}",
            annotation_position="top right",
        )
    else:
        fig.add_annotation(
            text="No stochastic samples available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color=ChartColors.TEXT_MUTED),
        )

    return fig


def create_stochastic_cdf_figure(
    values: Sequence[float],
    metric_name: str = "Journey Time",
    unit: str = "s",
    running_direction: Optional[RunningDirection] = None,
    title: Optional[str] = None,
) -> go.Figure:
    """P13-STC-002: Empirical cumulative distribution function (CDF) curve."""
    clean_vals = sorted([v for v in values if v is not None and np.isfinite(v)])
    fig_title = title or f"Empirical Cumulative Distribution Function (CDF): {metric_name}"

    fig = go.Figure()

    if clean_vals:
        n = len(clean_vals)
        cdf_probs = np.arange(1, n + 1) / n

        fig.add_trace(
            go.Scatter(
                x=clean_vals,
                y=cdf_probs,
                mode="lines",
                line=dict(color=ChartColors.PRIMARY_NAVY, width=2.5),
                name=f"CDF({metric_name})",
                hovertemplate=f"{metric_name}: %{{x:.1f}} {unit}<br>P(X <= x): %{{y:.3f}}<extra></extra>",
            )
        )

        # Highlight P90 and P95
        p90_x = float(np.percentile(clean_vals, 90))
        fig.add_hline(
            y=0.90,
            line_dash="dot",
            line_color=ChartColors.WARNING_AMBER,
            annotation_text=f"P90: {p90_x:.1f} {unit}",
        )

    layout = get_plotly_layout(
        title=fig_title,
        xaxis_title=f"{metric_name} ({unit})",
        yaxis_title="Cumulative Probability P(X <= x)",
        running_direction=running_direction,
        height=500,
    )
    fig.update_layout(layout)
    fig.update_yaxes(range=[0, 1.05])
    return fig


def create_stochastic_box_plot(
    data_by_group: Dict[str, Sequence[float]],
    metric_name: str = "Headway",
    unit: str = "s",
    running_direction: Optional[RunningDirection] = None,
    title: Optional[str] = None,
) -> go.Figure:
    """P13-STC-003: Box plots for key metrics across scenarios or services."""
    fig_title = title or f"Statistical Variability Dispersion: {metric_name}"
    fig = go.Figure()

    colors = [ChartColors.PRIMARY_NAVY, ChartColors.SECONDARY_BLUE, ChartColors.ACCENT_TEAL, ChartColors.WARNING_AMBER]

    for idx, (group_name, vals) in enumerate(data_by_group.items()):
        clean_vals = [v for v in vals if v is not None and np.isfinite(v)]
        c = colors[idx % len(colors)]
        fig.add_trace(
            go.Box(
                y=clean_vals,
                name=group_name,
                marker=dict(color=c),
                boxpoints="outliers",
                hovertemplate=f"Group: {group_name}<br>{metric_name}: %{{y:.2f}} {unit}<extra></extra>",
            )
        )

    layout = get_plotly_layout(
        title=fig_title,
        xaxis_title="Group / Scenario",
        yaxis_title=f"{metric_name} ({unit})",
        running_direction=running_direction,
        height=500,
    )
    fig.update_layout(layout)
    return fig


def create_confidence_interval_figure(
    estimates: Sequence[Dict[str, Any]],
    metric_name: str = "Mean Headway",
    unit: str = "s",
    running_direction: Optional[RunningDirection] = None,
    title: Optional[str] = None,
) -> go.Figure:
    """P13-STC-004: Point estimates with confidence interval error bars (Student's t or Wilson score)."""
    fig_title = title or f"Confidence Intervals for {metric_name}"
    fig = go.Figure()

    labels = [e["label"] for e in estimates]
    points = [e["point_estimate"] for e in estimates]
    ci_lower = [e["ci_lower"] for e in estimates]
    ci_upper = [e["ci_upper"] for e in estimates]

    error_y_plus = [up - pt for pt, up in zip(points, ci_upper)]
    error_y_minus = [pt - low for pt, low in zip(points, ci_lower)]

    fig.add_trace(
        go.Scatter(
            x=labels,
            y=points,
            mode="markers",
            marker=dict(size=10, color=ChartColors.PRIMARY_NAVY),
            error_y=dict(
                type="data",
                symmetric=False,
                array=error_y_plus,
                arrayminus=error_y_minus,
                color=ChartColors.PRIMARY_NAVY,
                thickness=2,
                width=8,
            ),
            name="Point Estimate ± 95% CI",
            hovertemplate="<b>%{x}</b><br>Estimate: %{y:.2f} " + unit + "<extra></extra>",
        )
    )

    layout = get_plotly_layout(
        title=fig_title,
        xaxis_title="Scenario / Condition",
        yaxis_title=f"{metric_name} ({unit})",
        running_direction=running_direction,
        height=500,
    )
    fig.update_layout(layout)
    return fig


def create_reliability_curve_figure(
    demand_rates: Sequence[float],
    reliability_percentages: Sequence[float],
    threshold_percentage: float = 95.0,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Operational Reliability Compliance vs Demand Rate",
) -> go.Figure:
    """P13-STC-005: Operational reliability percentage vs demand rate curve."""
    fig = go.Figure()

    rates = list(demand_rates)
    rel = list(reliability_percentages)

    fig.add_trace(
        go.Scatter(
            x=rates,
            y=rel,
            mode="lines+markers",
            line=dict(color=ChartColors.PRIMARY_NAVY, width=2.5),
            marker=dict(size=8, color=ChartColors.PRIMARY_NAVY),
            name="Simulated Reliability %",
            hovertemplate="Demand: %{x:.1f} tph<br>Reliability: %{y:.1f}%<extra></extra>",
        )
    )

    # Threshold horizontal line
    fig.add_hline(
        y=threshold_percentage,
        line_dash="dash",
        line_color=ChartColors.CRITICAL_RED,
        annotation_text=f"Compliance Threshold: {threshold_percentage:.1f}%",
        annotation_position="bottom left",
    )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Demand Rate (trains/hour)",
        yaxis_title="Operational Reliability Compliance (%)",
        running_direction=running_direction,
        height=500,
    )
    fig.update_layout(layout)
    fig.update_yaxes(range=[0, 105])
    return fig
