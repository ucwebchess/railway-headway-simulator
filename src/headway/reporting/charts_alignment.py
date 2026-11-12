"""v1.14.5: Service Alignment Diagram (Section 6, below the platform occupation table).

A horizontal schematic of the simulated route in route-frame chainage (0 km = run origin, the
same frame as ``metadata["station_events"]`` and ``metadata["tvs_events"]``):

* route line from 0 to the route length;
* station ticks at each served station's stop chainage (``station_events.route_chainage_km``) and,
  for platforms the service does not stop at, at the platform centre;
* platform bars spanning each platform's route-frame extent, one row per track;
* filled circles where the train stops, hollow circles at platforms it does not use;
* TVS zone bands below the route line;
* a direction arrow labelled ``Service direction: FORWARD|REVERSE``.

As on the blocking stairway, REVERSE runs keep route-frame values and reverse the x-axis, so the
picture keeps its physical orientation and the arrow points right-to-left.
"""
from __future__ import annotations

import itertools
import math
from typing import Any, Dict, List, Optional, Sequence

import plotly.graph_objects as go

from headway.core.exceptions import ReportingError
from headway.infrastructure.direction import RunningDirection

ROUTE_COLOR = "#4A4A4A"        # dark grey
TICK_COLOR = "#000000"         # black
PLATFORM_COLOR = "#9DC3E6"     # light blue
STOP_COLOR = "#1B5E20"         # dark green
UNUSED_COLOR = "#9E9E9E"       # grey
TVS_FILL = "rgba(255, 165, 0, 0.3)"  # orange, 30 % opacity

ROUTE_TRACE = "Route"
TICK_TRACE = "Stations"
STOP_TRACE = "Service stop"
UNUSED_TRACE = "Platform not used by this service"
PLATFORM_TRACE_PREFIX = "Platform track: "

_Y_TVS = (-0.55, -0.40)
_Y_TICK = (-0.18, 0.18)
_Y_PLATFORM0, _Y_PLATFORM_STEP = 0.45, 0.22
_TRACK_SPACING_FRACTION = 0.06   # labels closer than 6 % of the route are rotated 45 deg


class ChartAlignmentFrameError(ReportingError):
    """Raised when platform geometry cannot be placed consistently on the route frame."""

    DEFAULT_ERROR_CODE = "ERR_CHART_ALIGNMENT_FRAME"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def platform_route_extents(
    platform_provenance: Sequence[Any],
    track_links: Sequence[Any],
    route_link_ids: Sequence[str],
    route_length_m: float,
    direction: RunningDirection,
) -> List[Dict[str, Any]]:
    """Route-frame extent (m) of every parent platform whose segments lie on the route.

    Forward position = cumulative length of the preceding route links + segment offset. REVERSE route
    chainage is ``route_length_m - forward``. Segments of one parent platform are merged.
    """
    lengths = {str(_get(l, "link_id")): float(_get(l, "length_m")) for l in track_links or []}
    start_of: Dict[str, float] = {}
    pos = 0.0
    for lid in route_link_ids or []:
        start_of[str(lid)] = pos
        pos += lengths.get(str(lid), 0.0)
    merged: Dict[str, Dict[str, Any]] = {}
    for seg in platform_provenance or []:
        lid = str(_get(seg, "link_id"))
        if lid not in start_of:
            continue
        a = start_of[lid] + float(_get(seg, "start_offset_m"))
        b = start_of[lid] + float(_get(seg, "end_offset_m"))
        if direction == RunningDirection.REVERSE:
            a, b = route_length_m - a, route_length_m - b
        lo, hi = sorted((a, b))
        pid = str(_get(seg, "parent_platform_id") or _get(seg, "segment_id"))
        rec = merged.setdefault(pid, {"platform_id": pid, "station_id": str(_get(seg, "station_id")),
                                      "track_id": str(_get(seg, "track_id")), "start_m": lo, "end_m": hi})
        rec["start_m"], rec["end_m"] = min(rec["start_m"], lo), max(rec["end_m"], hi)
    return sorted(merged.values(), key=lambda r: r["start_m"])


#: v1.14.6: observed-position allowance of the diagram containment check (m) — the engine accepts
#: arrival within ±1.0 m of the berth target (``ARRIVAL_POSITION_TOL_M``).
CHART_POSITION_TOLERANCE_M = 1.0


def chart_containment_tolerance_m(train_length_m: float, platform_length_m: float) -> float:
    """v1.14.6: unavoidable overhang ``max(0, L - P)`` + the 1.0 m observed-position allowance."""
    return max(0.0, float(train_length_m) - float(platform_length_m)) + CHART_POSITION_TOLERANCE_M


def _check_stops_on_platforms(platforms: Sequence[Dict[str, Any]], station_events: Sequence[Any]) -> None:
    """Every stop's train footprint must lie on its parent platform's route-frame extent.

    v1.14.6: both the front and the rear are checked, using the recorded front/rear stopping
    positions (0.01 m precision, route frame) rather than the 1 m-rounded ``route_chainage_km``.
    The allowance is the unavoidable overhang ``max(0, L - P)`` + 1.0 m. Records without recorded
    positions fall back to a front-only check on ``route_chainage_km`` with the 1.0 m allowance.
    """
    by_id = {p["platform_id"]: p for p in platforms}
    for ev in station_events or []:
        pid = str(_get(ev, "platform_id", "") or "").split("@")[0]
        plat = by_id.get(pid)
        if plat is None:
            continue
        lo, hi = float(plat["start_m"]), float(plat["end_m"])
        front = _get(ev, "front_stopping_position_m")
        rear = _get(ev, "rear_stopping_position_m")
        if front is not None and rear is not None:
            front, rear = float(front), float(rear)
            tol = chart_containment_tolerance_m(abs(front - rear), hi - lo)
            checks = (("front", front), ("rear", rear))
        else:
            km = _get(ev, "route_chainage_km")
            if km is None:
                continue
            tol = CHART_POSITION_TOLERANCE_M
            checks = (("front", float(km) * 1000.0),)
        for end_name, x in checks:
            if not (lo - tol <= x <= hi + tol):
                raise ChartAlignmentFrameError(
                    f"Stop of {_get(ev, 'station_id')}: train {end_name} at route chainage {x:.2f} m lies "
                    f"outside platform {pid} ({lo:.2f}-{hi:.2f} m, allowed overhang {tol:.3f} m) on the "
                    f"Service Alignment Diagram.",
                    context={"station_id": _get(ev, "station_id"), "platform_id": pid, "end": end_name,
                             "position_m": round(x, 3), "allowed_overhang_m": round(tol, 6)},
                )


def create_service_alignment_figure(
    route_length_m: float,
    station_events: Sequence[Any],
    platforms: Sequence[Dict[str, Any]],
    tvs_events: Optional[Sequence[Any]] = None,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    train_type_id: str = "",
    service_pattern_id: str = "",
) -> go.Figure:
    """Build the Service Alignment Diagram (all chainages in metres, route frame)."""
    length_m = float(route_length_m)
    if not math.isfinite(length_m) or length_m <= 0:
        raise ChartAlignmentFrameError(
            f"Service Alignment Diagram needs a positive route length (got {route_length_m!r}).",
            context={"route_length_m": route_length_m},
        )
    _check_stops_on_platforms(platforms, station_events)
    L_km = length_m / 1000.0
    fig = go.Figure()

    # Route line.
    fig.add_trace(go.Scatter(x=[0.0, L_km], y=[0.0, 0.0], mode="lines", name=ROUTE_TRACE,
                             line=dict(color=ROUTE_COLOR, width=2), hoverinfo="skip"))

    # Station positions: served stops at the stop chainage, other stations at their platform centre.
    served: Dict[str, float] = {}
    for ev in station_events or []:
        sid, km = str(_get(ev, "station_id")), _get(ev, "route_chainage_km")
        if km is not None and sid not in served:
            served[sid] = round(float(km), 6)
    unused: Dict[str, float] = {}
    for p in platforms:
        if p["station_id"] not in served and p["station_id"] not in unused:
            unused[p["station_id"]] = round((p["start_m"] + p["end_m"]) / 2000.0, 6)
    stations = sorted({**unused, **served}.items(), key=lambda kv: kv[1])

    tx, ty = [], []
    for _, x in stations:
        tx += [x, x, None]
        ty += [_Y_TICK[0], _Y_TICK[1], None]
    fig.add_trace(go.Scatter(x=tx, y=ty, mode="lines", name=TICK_TRACE,
                             line=dict(color=TICK_COLOR, width=1), hoverinfo="skip"))

    # Platform bars, one row per track (order of first appearance along the route).
    tracks: List[str] = []
    for p in platforms:
        if p["track_id"] not in tracks:
            tracks.append(p["track_id"])
    for row, trk in enumerate(tracks):
        y = _Y_PLATFORM0 + row * _Y_PLATFORM_STEP
        bx, by, text = [], [], []
        for p in (p for p in platforms if p["track_id"] == trk):
            bx += [p["start_m"] / 1000.0, p["end_m"] / 1000.0, None]
            by += [y, y, None]
            label = f"{p['platform_id']} ({p['station_id']}) {p['start_m'] / 1000.0:.3f}-{p['end_m'] / 1000.0:.3f} km"
            text += [label, label, None]
        fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", name=f"{PLATFORM_TRACE_PREFIX}{trk}",
                                 line=dict(color=PLATFORM_COLOR, width=9), text=text, hoverinfo="text"))

    # Service stops (filled) and platforms not used by this service (hollow).
    fig.add_trace(go.Scatter(
        x=list(served.values()), y=[0.0] * len(served), mode="markers", name=STOP_TRACE,
        marker=dict(symbol="circle", size=11, color=STOP_COLOR, line=dict(color=STOP_COLOR, width=1.5)),
        text=list(served), hovertemplate="%{text}: stop at %{x:.3f} km<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=list(unused.values()), y=[0.0] * len(unused), mode="markers", name=UNUSED_TRACE,
        marker=dict(symbol="circle-open", size=11, color=UNUSED_COLOR, line=dict(color=UNUSED_COLOR, width=2)),
        text=list(unused), hovertemplate="%{text}: not served (%{x:.3f} km)<extra></extra>"))

    # TVS zone bands below the route line.
    seen = set()
    for ev in tvs_events or []:
        a = _get(ev, "start_chainage_m", _get(ev, "entry_chainage_m"))
        b = _get(ev, "end_chainage_m", _get(ev, "exit_chainage_m"))
        if a is None or b is None:
            continue
        lo, hi = sorted((float(a) / 1000.0, float(b) / 1000.0))
        zone = str(_get(ev, "tvs_id", "TVS"))
        if (zone, lo, hi) in seen:
            continue
        seen.add((zone, lo, hi))
        y0, y1 = _Y_TVS
        fig.add_trace(go.Scatter(x=[lo, hi, hi, lo, lo], y=[y0, y0, y1, y1, y0], mode="lines", fill="toself",
                                 fillcolor=TVS_FILL, line=dict(width=0), name=zone,
                                 hovertemplate=f"{zone}: {lo:.3f}-{hi:.3f} km<extra></extra>"))
        fig.add_annotation(x=(lo + hi) / 2, y=y0, yanchor="top", text=zone, showarrow=False,
                           font=dict(size=10, color="#8A4B00"))

    # Station labels (rotated when neighbours are close).
    xs = [x for _, x in stations]
    crowded = any(b - a < _TRACK_SPACING_FRACTION * L_km for a, b in itertools.pairwise(xs))
    top_row = _Y_PLATFORM0 + max(len(tracks) - 1, 0) * _Y_PLATFORM_STEP
    for sid, x in stations:
        fig.add_annotation(x=x, y=top_row + 0.12, yanchor="bottom", text=sid, showarrow=False,
                           textangle=-45 if crowded else 0, font=dict(size=11, color=TICK_COLOR))

    # Direction arrow: tail at route 0, head at the route end (route frame); the REVERSE axis is reversed.
    arrow_y = top_row + (0.75 if crowded else 0.5)
    fig.add_annotation(x=L_km, y=arrow_y, ax=0.0, ay=arrow_y, xref="x", yref="y", axref="x", ayref="y",
                       showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=2, arrowcolor=ROUTE_COLOR, text="")
    fig.add_annotation(x=L_km / 2, y=arrow_y, yanchor="bottom", showarrow=False,
                       text=f"<b>Service direction: {running_direction.value}</b>",
                       font=dict(size=12, color=ROUTE_COLOR))

    title = "Service Alignment Diagram"
    if train_type_id or service_pattern_id:
        title += f" — {train_type_id} / {service_pattern_id}"
    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", x=0.01, xanchor="left", font=dict(size=16, color="#1B365D")),
        height=400, paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        margin=dict(l=40, r=40, t=60, b=50),
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.0),
        meta={"direction": running_direction.value, "route_length_km": L_km,
              "served_stations": list(served), "unused_stations": list(unused)},
    )
    fig.update_xaxes(title_text="Route Chainage (km)", range=[0.0, L_km], showgrid=False,
                     zeroline=False, showline=True, linecolor=ROUTE_COLOR)
    if running_direction == RunningDirection.REVERSE:
        fig.update_xaxes(range=[L_km, 0.0])
    fig.update_yaxes(visible=False, range=[-0.8, arrow_y + 0.35], fixedrange=True)
    return fig
