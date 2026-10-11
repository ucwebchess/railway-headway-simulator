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
    title: str = "Platform Track Reservation, Dwell & Residual Rear Occupation",
) -> go.Figure:
    """P13-STN-001 to 005: Generate interactive platform track occupation timeline."""
    fig = go.Figure()

    if not occupation_records:
        layout = get_plotly_layout(
            title=title,
            xaxis_title="Simulation Time (s)",
            yaxis_title="Platform Track",
            running_direction=running_direction,
        )
        fig.update_layout(layout)
        return fig

    # Group records by platform
    platforms_seen = []
    for r in occupation_records:
        label = f"{r.station_name} - {r.platform_id}"
        if label not in platforms_seen:
            platforms_seen.append(label)

    if running_direction == RunningDirection.REVERSE:
        platforms_seen = list(reversed(platforms_seen))

    for rec in occupation_records:
        plt_label = f"{rec.station_name} - {rec.platform_id}"

        # 1. Approach / Ingress (Arrival to Dwell start)
        ingress_dur = max(0.0, rec.dwell_start_time_s - rec.arrival_time_s)
        if ingress_dur > 0:
            fig.add_trace(
                go.Bar(
                    name="Ingress",
                    x=[ingress_dur],
                    y=[plt_label],
                    base=[rec.arrival_time_s],
                    orientation="h",
                    marker=dict(color=ChartColors.COMPONENT_APPROACH),
                    hovertemplate=f"Train: {rec.train_id}<br>Ingress: {ingress_dur:.1f} s<extra></extra>",
                    showlegend=False,
                )
            )

        # 2. Dwell Period (Stationary platform occupation)
        fig.add_trace(
            go.Bar(
                name="Passenger Dwell",
                x=[rec.dwell_duration_s],
                y=[plt_label],
                base=[rec.dwell_start_time_s],
                orientation="h",
                marker=dict(color=ChartColors.COMPONENT_DWELL),
                hovertemplate=(
                    f"<b>Train: {rec.train_id}</b><br>"
                    f"Platform: {rec.platform_id}<br>"
                    f"Dwell Start: {rec.dwell_start_time_s:.1f} s<br>"
                    f"Dwell End: {rec.dwell_end_time_s:.1f} s<br>"
                    f"Duration: {rec.dwell_duration_s:.1f} s<extra></extra>"
                ),
                showlegend=(rec == occupation_records[0]),
            )
        )

        # 3. Egress / Clearance (Departure to Clearance)
        egress_dur = max(0.0, rec.clearance_time_s - rec.departure_time_s)
        if egress_dur > 0:
            fig.add_trace(
                go.Bar(
                    name="Egress / Clearance",
                    x=[egress_dur],
                    y=[plt_label],
                    base=[rec.departure_time_s],
                    orientation="h",
                    marker=dict(color=ChartColors.COMPONENT_GEOMETRIC_CLEARANCE),
                    hovertemplate=f"Train: {rec.train_id}<br>Clearance: {egress_dur:.1f} s<extra></extra>",
                    showlegend=False,
                )
            )

        # 4. Residual Rear Occupation Highlight (P13-STN-004)
        if rec.is_residual_rear_active and rec.residual_rear_duration_s > 0:
            rear_label = f"{plt_label} [Upstream Infringement]"
            fig.add_trace(
                go.Bar(
                    name="Residual Rear Invariant",
                    x=[rec.residual_rear_duration_s],
                    y=[plt_label],
                    base=[rec.dwell_start_time_s],
                    orientation="h",
                    marker=dict(
                        color=ChartColors.COMPONENT_RESIDUAL_REAR,
                        pattern=dict(shape="/", fgcolor=ChartColors.CRITICAL_RED),
                    ),
                    hovertemplate=(
                        f"<b>Upstream Infringement ({rec.train_id})</b><br>"
                        f"Resources: {', '.join(rec.upstream_infringing_resource_ids)}<br>"
                        f"Duration: {rec.residual_rear_duration_s:.1f} s<extra></extra>"
                    ),
                    showlegend=(rec == occupation_records[0]),
                )
            )

    layout = get_plotly_layout(
        title=title,
        xaxis_title="Simulation Time (s)",
        yaxis_title="Station Platform Track",
        running_direction=running_direction,
        barmode="overlay",
        height=max(450, len(platforms_seen) * 45 + 180),
    )
    fig.update_layout(layout)
    fig.update_yaxes(categoryorder="array", categoryarray=platforms_seen)
    return fig
