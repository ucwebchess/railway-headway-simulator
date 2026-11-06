"""Opt-in route-coordinate overlays shared by the speed and stairway charts.

Event chainages are already in the simulated route frame (not alignment stationing).
No direction transform or subtraction of a network origin is appropriate here.
"""
import math
import plotly.graph_objects as go

TVS_FILL = "rgba(255, 165, 0, 0.15)"


def _get(event, key, default=None):
    return event.get(key, default) if isinstance(event, dict) else getattr(event, key, default)


def _scale(fig):
    return 1000.0 if "km" in (fig.layout.xaxis.title.text or "").lower() else 1.0


def add_tvs_overlay(fig, tvs_events, route_length_m):
    """Shade each distinct TVS zone over the existing chart's full vertical extent."""
    if not tvs_events:
        return fig
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
        lo, hi = lo / scale, hi / scale
        fig.add_trace(go.Scatter(x=[lo, lo, hi, hi], y=[0, 1, 1, 0], yaxis="y2",
                                 fill="tozeroy", mode="lines", line=dict(width=0),
                                 fillcolor=TVS_FILL, name=f"TVS zone: {zone}", hoverinfo="name"))
        fig.add_trace(go.Scatter(x=[(lo + hi) / 2], y=[0.96], yaxis="y2", mode="text",
                                 text=[zone], textposition="top center", name=f"TVS label: {zone}",
                                 showlegend=False, hoverinfo="skip"))
    return fig


def add_station_overlay(fig, station_events, route_length_m):
    """Mark station route chainages, deduplicated across trains/platform records."""
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
        x = float(chainage) / scale
        if not math.isfinite(x) or (station, x) in seen:
            continue
        seen.add((station, x))
        fig.add_vline(x=x, line_dash="dash", line_color="rgba(0, 128, 0, 0.5)",
                      annotation_text=station, annotation_position="top right")
    return fig


def apply_chart_overlays(fig, metadata, chart):
    """Leave the figure entirely untouched unless an overlay is requested."""
    meta = metadata or {}
    flags = meta.get("chart_overlays") or {}
    length = meta.get("route_length_m", 0)
    if flags.get(f"show_tvs_{chart}", False):
        add_tvs_overlay(fig, meta.get("tvs_events", []), length)
    if flags.get(f"show_stations_{chart}", False):
        add_station_overlay(fig, meta.get("station_events", meta.get("station_stops", [])), length)
    return fig
