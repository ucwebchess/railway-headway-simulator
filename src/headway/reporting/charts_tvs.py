"""TVS ventilation section occupation and comparison diagrams.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 19).
Satisfies:
- P13-TVS-001: Train occupation of TVS resources over time.
- P13-TVS-002: Consecutive TVS section representation.
- P13-TVS-003: Shared TVS group exclusivity visualization.
- P13-TVS-004: Waiting trains for TVS entry.
- P13-TVS-005: Signalling-only vs TVS-constrained headway comparison.
- P13-TVS-006: TVS journey-time impact display.
- P13-TVS-007: Reverse direction boundaries correctly displayed.
"""

from typing import Any, Dict, List, Optional, Sequence, Union
import plotly.graph_objects as go

from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout


def create_tvs_occupation_figure(
    tvs_events: Sequence[Dict[str, Any]],
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Tunnel Ventilation Section (TVS) Exclusivity & Occupations",
) -> go.Figure:
    """P13-TVS-001 to 004: Generate interactive TVS section occupation timeline."""
    fig = go.Figure()

    if not tvs_events:
        layout = get_plotly_layout(
            title=title,
            xaxis_title="Time (s)",
            yaxis_title="TVS Section",
            running_direction=running_direction,
        )
        fig.update_layout(layout)
        return fig

    tvs_sections = sorted({e.get("tvs_id", "TVS") for e in tvs_events})

    for event in tvs_events:
        tvs_id = event.get("tvs_id", "TVS")
        train_id = event.get("train_id", "Train")
        entry_s = event.get("entry_time_s", 0.0)
        exit_s = event.get("exit_time_s", 0.0)
        release_s = event.get("release_time_s", exit_s)
        wait_s = event.get("waiting_duration_s", 0.0)

        # 1. Waiting at holding signal before TVS entry (if any)
        if wait_s > 0:
            fig.add_trace(
                go.Bar(
                    name="TVS Queue Wait",
                    x=[wait_s],
                    y=[tvs_id],
                    base=[entry_s - wait_s],
                    orientation="h",
                    marker=dict(color=ChartColors.WARNING_AMBER),
                    hovertemplate=f"Train: {train_id}<br>TVS Holding Wait: {wait_s:.1f} s<extra></extra>",
                    showlegend=False,
                )
            )

        # 2. In-Tunnel Occupancy
        occ_dur = max(0.0, exit_s - entry_s)
        fig.add_trace(
            go.Bar(
                name="TVS In-Tunnel Physical Occupation",
                x=[occ_dur],
                y=[tvs_id],
                base=[entry_s],
                orientation="h",
                marker=dict(color=ChartColors.SECONDARY_BLUE),
                hovertemplate=(
                    f"<b>Train: {train_id}</b><br>"
                    f"TVS: {tvs_id}<br>"
                    f"Entry: {entry_s:.1f} s<br>"
                    f"Exit: {exit_s:.1f} s<br>"
                    f"Duration: {occ_dur:.1f} s<extra></extra>"
                ),
                showlegend=(event == tvs_events[0]),
            )
        )

        # 3. Post-Clearance TVS Release Delay Timer
        rel_dur = max(0.0, release_s - exit_s)
        if rel_dur > 0:
            fig.add_trace(
                go.Bar(
                    name="TVS Post-Clearance Release Delay",
                    x=[rel_dur],
                    y=[tvs_id],
                    base=[exit_s],
                    orientation="h",
                    marker=dict(color=ChartColors.COMPONENT_RELEASE),
                    hovertemplate=f"TVS Release Timer: {rel_dur:.1f} s<br>Full Release: {release_s:.1f} s<extra></extra>",
                    showlegend=(event == tvs_events[0]),
                )
            )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Simulation Time (s)",
        yaxis_title="Tunnel Ventilation Section (TVS)",
        running_direction=running_direction,
        barmode="overlay",
        height=max(450, len(tvs_sections) * 45 + 180),
    )
    fig.update_layout(layout)
    fig.update_yaxes(categoryorder="array", categoryarray=tvs_sections)
    return fig


def create_tvs_comparison_figure(
    signalling_headway_s: float,
    tvs_headway_s: float,
    combined_headway_s: float,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Headway Constraint Comparison: Signalling vs TVS Safety Policy",
) -> go.Figure:
    """P13-TVS-005 & 006: Generate comparison bar chart between signalling and TVS constraints."""
    categories = [
        "Signalling Minimum Headway",
        "TVS Single-Train Headway",
        "Combined Operational Headway",
    ]
    values = [signalling_headway_s, tvs_headway_s, combined_headway_s]
    colors = [ChartColors.SECONDARY_BLUE, ChartColors.ACCENT_TEAL, ChartColors.CRITICAL_RED]

    fig = go.Figure(
        data=[
            go.Bar(
                x=categories,
                y=values,
                text=[f"{v:.1f} s" for v in values],
                textposition="outside",
                marker=dict(color=colors),
                hovertemplate="%{x}: %{y:.1f} s<extra></extra>",
            )
        ]
    )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Safety & Control Subsystem",
        yaxis_title="Minimum Headway (s)",
        running_direction=running_direction,
        showlegend=False,
        height=500,
    )
    fig.update_layout(layout)
    fig.update_yaxes(range=[0, max(values) * 1.25])
    return fig
