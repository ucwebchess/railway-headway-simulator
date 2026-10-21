"""Station and platform occupation diagrams.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 14).
Satisfies:
- P13-STN-001: Platform reservation, occupation, dwell, and release.
- P13-STN-002: Leader and follower platform occupation.
- P13-STN-003: Multi-platform track layout.
- P13-STN-004: Residual rear occupation highlighting upstream blocking.
- P13-STN-005: Station order follows actual running direction.
"""

from typing import Any, Dict, List, Optional, Sequence, Union
import plotly.graph_objects as go

from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors, get_plotly_layout
from headway.reporting.result_models import PlatformOccupationRecord


def create_platform_occupation_figure(
    occupation_records: Sequence[PlatformOccupationRecord],
    running_direction: RunningDirection = RunningDirection.FORWARD,
    title: str = "Platform Track Occupation Duration & Residual Rear Invariant",
) -> go.Figure:
    """P13-STN-001 to 005 / v1.8.1: Stacked Bar Chart of platform occupation duration."""
    fig = go.Figure()

    if not occupation_records:
        layout = get_plotly_layout(
            title=title,
            xaxis_title="Platform ID",
            yaxis_title="Occupation Duration (s)",
            running_direction=running_direction,
            barmode="stack",
        )
        fig.update_layout(layout)
        return fig

    recs = list(occupation_records)
    if running_direction == RunningDirection.REVERSE:
        recs = list(reversed(recs))

    def _get_plt_id(r: Any) -> str:
        stn = getattr(r, "station_id", "") or ""
        plt = getattr(r, "platform_id", "") or ""
        if stn and plt:
            if plt.startswith(stn):
                return plt
            return f"{stn}-{plt}"
        return plt or stn or "PLT"

    platform_ids = [_get_plt_id(r) for r in recs]
    dwell_durations = [float(getattr(r, "dwell_duration_s", 0.0)) for r in recs]
    residual_durations = [float(getattr(r, "residual_rear_duration_s", 0.0)) for r in recs]

    # Trace 1: Passenger Dwell (Purple)
    fig.add_trace(
        go.Bar(
            name="Passenger Dwell",
            x=platform_ids,
            y=dwell_durations,
            orientation="v",
            marker=dict(color=ChartColors.COMPONENT_DWELL),
            hovertemplate="<b>%{x}</b><br>Passenger Dwell: %{y:.1f} s<extra></extra>",
        )
    )

    # Trace 2: Residual Rear Invariant (Orange/Red, hatched)
    fig.add_trace(
        go.Bar(
            name="Residual Rear Invariant",
            x=platform_ids,
            y=residual_durations,
            orientation="v",
            marker=dict(
                color=ChartColors.COMPONENT_RESIDUAL_REAR,
                pattern=dict(shape="/", fgcolor=ChartColors.CRITICAL_RED),
            ),
            hovertemplate="<b>%{x}</b><br>Residual Rear Invariant: %{y:.1f} s<extra></extra>",
        )
    )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Platform ID",
        yaxis_title="Occupation Duration (s)",
        running_direction=running_direction,
        barmode="stack",
        width=max(800, len(platform_ids) * 60 + 200),
        height=550,
    )
    fig.update_layout(layout)
    fig.update_xaxes(categoryorder="array", categoryarray=platform_ids)
    return fig
