"""Scenario engineering comparison and bottleneck migration charts.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 23).
Satisfies:
- P13-CMP-001: KPI comparisons across scenarios.
- P13-CMP-002: Absolute and percentage change display.
- P13-CMP-003 & P13-B030: Bottleneck migration visualization across scenarios.
- P13-CMP-004: Explicit direction handling.
- P13-CMP-005: Incompatible comparison warnings and diagnostics.
"""

from typing import Any, Dict, List, Optional, Sequence, Union
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout
from headway.scenarios.scenario_comparison import ScenarioComparisonReport


def create_scenario_kpi_comparison_figure(
    comparison_report: ScenarioComparisonReport,
    metric_name: str = "headway_s",
    running_direction: Optional[RunningDirection] = None,
    title: Optional[str] = None,
) -> go.Figure:
    """P13-CMP-001 & 002: Grouped bar chart comparing metric values across scenarios."""
    base_id = comparison_report.baseline_scenario_id
    cmp_ids = comparison_report.compared_scenario_ids
    all_scns = [base_id] + list(cmp_ids)

    fig_title = title or f"Engineering Comparison: {metric_name.replace('_', ' ').title()}"

    # Extract metric values
    metric_vals = []
    deltas = []

    # Get baseline value from first available metric difference
    base_val = 0.0
    for s_id in cmp_ids:
        diffs = comparison_report.metric_differences.get(s_id, [])
        m_diff = next((d for d in diffs if d.metric_name == metric_name), None)
        if m_diff and m_diff.baseline_value is not None:
            base_val = m_diff.baseline_value
            break

    metric_vals.append(base_val)
    deltas.append(0.0)

    for s_id in cmp_ids:
        diffs = comparison_report.metric_differences.get(s_id, [])
        m_diff = next((d for d in diffs if d.metric_name == metric_name), None)
        if m_diff and m_diff.scenario_value is not None:
            metric_vals.append(m_diff.scenario_value)
            deltas.append(m_diff.percentage_change or 0.0)
        else:
            metric_vals.append(base_val)
            deltas.append(0.0)

    colors = [ChartColors.PRIMARY_NAVY if i == 0 else ChartColors.SECONDARY_BLUE for i in range(len(all_scns))]

    text_labels = []
    for idx, (v, d) in enumerate(zip(metric_vals, deltas)):
        if idx == 0:
            text_labels.append(f"{v:.1f} (Baseline)")
        else:
            sign = "+" if d > 0 else ""
            text_labels.append(f"{v:.1f} ({sign}{d:.1f}%)")

    fig = go.Figure(
        data=[
            go.Bar(
                x=all_scns,
                y=metric_vals,
                text=text_labels,
                textposition="outside",
                marker=dict(color=colors),
                hovertemplate="Scenario: %{x}<br>Value: %{y:.2f}<extra></extra>",
            )
        ]
    )

    # Incompatible comparison warning (P13-CMP-005)
    annotations = []
    if comparison_report.direction_compatibility_notes:
        notes_str = "<br>".join(comparison_report.direction_compatibility_notes)
        annotations.append(
            dict(
                text=f"<b>Direction Note:</b><br>{notes_str}",
                xref="paper",
                yref="paper",
                x=0.01,
                y=0.98,
                showarrow=False,
                bgcolor="#FFF3CD",
                bordercolor=ChartColors.WARNING_AMBER,
                font=dict(size=11, color=ChartColors.WARNING_AMBER),
            )
        )

    layout = get_plotly_layout(
        title=fig_title,
        xaxis_title="Scenario Identifier",
        yaxis_title=f"{metric_name.replace('_', ' ').title()}",
        running_direction=running_direction,
        height=520,
    )
    if annotations:
        layout.annotations = list(layout.annotations or ()) + annotations
    fig.update_layout(layout)
    return fig


def create_bottleneck_migration_figure(
    comparison_report: ScenarioComparisonReport,
    running_direction: Optional[RunningDirection] = None,
    title: str = "Controlling Bottleneck Shift & Migration Across Scenarios",
) -> go.Figure:
    """P13-CMP-003 & P13-B030: Visualize shift in controlling bottleneck resource."""
    base_id = comparison_report.baseline_scenario_id
    shifts = comparison_report.bottleneck_shifts

    scenarios = [base_id]
    bottlenecks = []

    # Baseline bottleneck
    base_bn = shifts[0].baseline_bottleneck_id if shifts else "Unknown"
    bottlenecks.append(base_bn)

    for s in shifts:
        scenarios.append(s.comparison_scenario_id)
        bottlenecks.append(s.comparison_bottleneck_id or base_bn)

    # Colors: baseline navy, changed bottlenecks in red, unchanged in blue
    bar_colors = [ChartColors.PRIMARY_NAVY]
    for bn in bottlenecks[1:]:
        bar_colors.append(ChartColors.CRITICAL_RED if bn != base_bn else ChartColors.SECONDARY_BLUE)

    fig = go.Figure(
        data=[
            go.Bar(
                x=scenarios,
                y=[1] * len(scenarios),
                text=[f"<b>{bn}</b>" for bn in bottlenecks],
                textposition="inside",
                marker=dict(color=bar_colors),
                hovertemplate="Scenario: %{x}<br>Bottleneck: %{text}<extra></extra>",
            )
        ]
    )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Study Scenario",
        yaxis_title="",
        running_direction=running_direction,
        height=400,
    )
    fig.update_layout(layout)
    fig.update_yaxes(showticklabels=False, showgrid=False)
    return fig
