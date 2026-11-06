"""Opt-in route-coordinate overlays shared by the speed and stairway charts.

Event chainages (``tvs_events`` / ``station_events``) are in the simulated *route* frame:
0 = route origin, increasing along the direction of travel, in FORWARD and REVERSE alike.

v1.14.3: a chart whose X data is not in that frame must say so. The REVERSE Speed Profile
plots the trajectory on the forward (physical) axis -- decreasing along travel, with a
reversed axis -- exactly like its permissible-speed envelope, so its overlays are mirrored
onto that axis with ``x = route_length_m - chainage`` (``mirror=True``). The Blocking
Stairway plots route-frame chainage in both directions and therefore never mirrors.
"""
import math

import plotly.graph_objects as go

from headway.core.exceptions import ReportingError

TVS_FILL = "rgba(255, 165, 0, 0.15)"


class ChartOverlayFrameError(ReportingError):
    """Raised when an overlay cannot be mapped onto the chart's coordinate frame."""

    DEFAULT_ERROR_CODE = "ERR_CHART_OVERLAY_FRAME"


def _mirror_length(route_length_m, mirror):
    """Validated route length for mirroring (None when no mirroring is requested)."""
    if not mirror:
        return None
    try:
        length = float(route_length_m)
    except (TypeError, ValueError):
        length = float("nan")
    if not math.isfinite(length) or length <= 0.0:
        raise ChartOverlayFrameError(
            f"route_length_m must be a positive finite number to place overlays on a reversed "
            f"(physical-axis) chart; got {route_length_m!r}.",
            context={"route_length_m": route_length_m},
        )
    return length


def _to_chart(chainage_m, length_m):
    # Mirrored values are rounded to 1 mm so float noise does not leak into the chart JSON.
    return chainage_m if length_m is None else round(length_m - chainage_m, 3)


def _get(event, key, default=None):
    return event.get(key, default) if isinstance(event, dict) else getattr(event, key, default)


def _scale(fig):
    return 1000.0 if "km" in (fig.layout.xaxis.title.text or "").lower() else 1.0


def add_tvs_overlay(fig, tvs_events, route_length_m, mirror=False):
    """Shade each distinct TVS zone over the existing chart's full vertical extent.

    ``mirror=True`` maps route-frame chainage onto a forward-axis REVERSE chart.
    """
    if not tvs_events:
        return fig
    length = _mirror_length(route_length_m, mirror)
    scale = _scale(fig)
    seen = set()
    # A normalized secondary axis prevents overlays changing the data-axis range.
    fig.update_layout(yaxis2=dict(overlaying="y", range=[0, 1], visible=False, fixedrange=True))
    for event in tvs_events or []:
        start = _get(event, "start_chainage_m", _get(event, "entry_chainage_m", _get(event, "entry_chainage")))
        end = _get(event, "end_chainage_m", _get(event, "exit_chainage_m", _get(event, "exit_chainage")))
        if start is None or end is None:
            continue
        lo, hi = sorted((float(start), float(end)))
        zone = str(_get(event, "tvs_id", "TVS"))
        key = (zone, lo, hi)
        if not all(math.isfinite(v) for v in (lo, hi)) or key in seen:
            continue
        seen.add(key)
        lo, hi = sorted((_to_chart(lo, length), _to_chart(hi, length)))
        lo, hi = lo / scale, hi / scale
        fig.add_trace(go.Scatter(x=[lo, lo, hi, hi], y=[0, 1, 1, 0], yaxis="y2",
                                 fill="tozeroy", mode="lines", line=dict(width=0),
                                 fillcolor=TVS_FILL, name=f"TVS zone: {zone}", hoverinfo="name"))
        fig.add_trace(go.Scatter(x=[(lo + hi) / 2], y=[0.96], yaxis="y2", mode="text",
                                 text=[zone], textposition="top center", name=f"TVS label: {zone}",
                                 showlegend=False, hoverinfo="skip"))
    return fig


def add_station_overlay(fig, station_events, route_length_m, mirror=False):
    """Mark station route chainages, deduplicated across trains/platform records.

    ``mirror=True`` maps route-frame chainage onto a forward-axis REVERSE chart.
    """
    if not station_events:
        return fig
    length = _mirror_length(route_length_m, mirror)
    scale = _scale(fig)
    seen = set()
    for event in station_events or []:
        chainage = _get(event, "chainage_m")
        if chainage is None:
            km = _get(event, "route_chainage_km")
            chainage = float(km) * 1000 if km is not None else None
        if chainage is None:
            continue
        station = str(_get(event, "station_id", "Station"))
        x = _to_chart(float(chainage), length) / scale
        if not math.isfinite(x) or (station, x) in seen:
            continue
        seen.add((station, x))
        fig.add_vline(x=x, line_dash="dash", line_color="rgba(0, 128, 0, 0.5)",
                      annotation_text=station, annotation_position="top right")
    return fig


def apply_chart_overlays(fig, metadata, chart, mirror=False):
    """Leave the figure entirely untouched unless an overlay is requested.

    ``mirror`` is set by charts that plot REVERSE runs on the forward (physical) axis.
    """
    meta = metadata or {}
    flags = meta.get("chart_overlays") or {}
    length = meta.get("route_length_m", 0)
    if flags.get(f"show_tvs_{chart}", False):
        add_tvs_overlay(fig, meta.get("tvs_events", []), length, mirror=mirror)
    if flags.get(f"show_stations_{chart}", False):
        add_station_overlay(fig, meta.get("station_events", meta.get("station_stops", [])), length, mirror=mirror)
    return fig
