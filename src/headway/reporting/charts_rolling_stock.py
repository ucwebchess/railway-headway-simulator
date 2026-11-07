"""v1.14.5: Rolling-stock characteristic charts for the Executive Summary.

* Tractive Effort Curve: the train type's nominal (rated) tractive effort characteristic.
  A tabulated curve (``traction_curve``) is plotted directly; otherwise the standard
  constant-torque / constant-power model is used:

      F(v) = F_max            for v <= v_transition
      F(v) = P / v            for v >  v_transition,   v_transition = P / F_max

  Operational derating (performance factor), the acceleration limit and adhesion are run-time
  limits applied by the simulation; they are not part of the rated characteristic shown here.

* Davis Resistance Decomposition: R(v) = A + B*v + C*v^2 (v in m/s), with each component.

Both charts depend only on the train type, so they are identical in FORWARD and REVERSE.
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

import plotly.graph_objects as go

from headway.reporting.chart_theme import ChartColors, get_plotly_layout

KMH_PER_MS = 3.6
TRACTIVE_TRACE_NAME = "Tractive Effort F(v)"
DAVIS_TRACE_NAMES = ("A (rolling)", "B·v (mechanical)", "C·v² (aerodynamic)", "Total R(v)")
_SAMPLES = 200


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _speed_grid_kmh(max_speed_kmh: float, extra: Sequence[float] = ()) -> List[float]:
    """Uniform 0..max grid plus exact break-points (e.g. v_transition) so knees are not smeared."""
    grid = {round(max_speed_kmh * i / _SAMPLES, 9) for i in range(_SAMPLES + 1)}
    grid.update(round(float(v), 9) for v in extra if 0.0 <= float(v) <= max_speed_kmh)
    return sorted(grid)


def max_speed_kmh_of(train_type: Any) -> float:
    v_ms = _get(train_type, "max_speed_ms")
    if v_ms is not None:
        return float(v_ms) * KMH_PER_MS
    return float(_get(train_type, "max_speed_kmh"))


def transition_speed_ms(train_type: Any) -> Optional[float]:
    """v_transition = P / F_max (m/s), or None when power or F_max is not defined."""
    p_w = _get(train_type, "power_w")
    f_n = _get(train_type, "max_tractive_effort_n")
    if not p_w or not f_n or float(p_w) <= 0 or float(f_n) <= 0:
        return None
    return float(p_w) / float(f_n)


def nominal_tractive_effort_n(train_type: Any, speed_ms: float) -> float:
    """Rated tractive effort at ``speed_ms``: min(F_max, P / v); F(0) = F_max."""
    f_max = float(_get(train_type, "max_tractive_effort_n"))
    p_w = float(_get(train_type, "power_w"))
    return f_max if speed_ms <= 0.0 else min(f_max, p_w / speed_ms)


def create_tractive_effort_figure(train_type: Any) -> go.Figure:
    """Tractive Effort Curve: one main trace, dotted F_max line, dashed v_transition line."""
    tt_id = str(_get(train_type, "train_type_id", "TRAIN"))
    v_max_kmh = max_speed_kmh_of(train_type)
    curve = list(_get(train_type, "traction_curve", None) or [])
    v_t_ms = transition_speed_ms(train_type)

    if curve:
        pts = sorted((float(_get(p, "speed_ms")) * KMH_PER_MS, float(_get(p, "force_n")) / 1000.0) for p in curve)
        x_kmh = [v for v, _ in pts]
        y_kn = [f for _, f in pts]
        f_max_kn = max(y_kn)
        source = "tabulated traction curve"
    else:
        f_max_kn = float(_get(train_type, "max_tractive_effort_n")) / 1000.0
        extra = [v_t_ms * KMH_PER_MS] if v_t_ms is not None else []
        x_kmh = _speed_grid_kmh(v_max_kmh, extra)
        y_kn = [nominal_tractive_effort_n(train_type, v / KMH_PER_MS) / 1000.0 for v in x_kmh]
        source = "F(v) = min(F_max, P / v)"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_kmh, y=y_kn, mode="lines", name=TRACTIVE_TRACE_NAME,
        line=dict(color=ChartColors.SPEED_PROFILE, width=2.5),
        hovertemplate="Speed: %{x:.1f} km/h<br>Tractive effort: %{y:.1f} kN<extra></extra>",
    ))
    fig.update_layout(get_plotly_layout(
        title=f"Tractive Effort Curve — {tt_id}",
        xaxis_title="Speed (km/h)",
        yaxis_title="Tractive Effort (kN)",
        height=400,
    ))
    fig.update_xaxes(range=[0.0, v_max_kmh])
    fig.update_yaxes(range=[0.0, f_max_kn * 1.15])
    fig.add_hline(y=f_max_kn, line_dash="dot", line_color=ChartColors.TEXT_MUTED, line_width=1.5,
                  annotation_text=f"F_max = {f_max_kn:.0f} kN", annotation_position="top right")
    if v_t_ms is not None and v_t_ms * KMH_PER_MS <= v_max_kmh:
        v_t_kmh = v_t_ms * KMH_PER_MS
        fig.add_vline(x=v_t_kmh, line_dash="dash", line_color=ChartColors.WARNING_AMBER, line_width=1.5,
                      annotation_text=f"v_transition = P / F_max = {v_t_ms:.1f} m/s ({v_t_kmh:.0f} km/h)",
                      annotation_position="top right")
    fig.update_layout(meta={"source": source, "f_max_kn": f_max_kn,
                            "v_transition_ms": v_t_ms, "max_speed_kmh": v_max_kmh})
    return fig


def davis_components_kn(train_type: Any, speed_kmh: float) -> tuple:
    """(A, B*v, C*v^2, total) in kN at ``speed_kmh`` (v = speed_kmh / 3.6 m/s)."""
    v = float(speed_kmh) / KMH_PER_MS
    a = float(_get(train_type, "davis_a_n", 0.0) or 0.0)
    b = float(_get(train_type, "davis_b_ns_m", _get(train_type, "davis_b_ns_per_m", 0.0)) or 0.0)
    c = float(_get(train_type, "davis_c_ns2_m2", _get(train_type, "davis_c_ns2_per_m2", 0.0)) or 0.0)
    ra, rb, rc = a / 1000.0, b * v / 1000.0, c * v * v / 1000.0
    return ra, rb, rc, ra + rb + rc


def create_davis_resistance_figure(train_type: Any) -> go.Figure:
    """Davis Resistance Decomposition: three component traces plus the total."""
    tt_id = str(_get(train_type, "train_type_id", "TRAIN"))
    v_max_kmh = max_speed_kmh_of(train_type)
    x_kmh = _speed_grid_kmh(v_max_kmh)
    comps = [davis_components_kn(train_type, v) for v in x_kmh]
    styles = (
        dict(dash="dot", color=ChartColors.TEXT_MUTED, width=1.8),
        dict(dash="dash", color=ChartColors.ACCENT_TEAL, width=1.8),
        dict(dash="dashdot", color=ChartColors.WARNING_AMBER, width=1.8),
        dict(dash="solid", color=ChartColors.PRIMARY_NAVY, width=2.8),
    )
    fig = go.Figure()
    for i, (name, line) in enumerate(zip(DAVIS_TRACE_NAMES, styles)):
        fig.add_trace(go.Scatter(
            x=x_kmh, y=[c[i] for c in comps], mode="lines", name=name, line=line,
            hovertemplate=f"{name}<br>Speed: %{{x:.1f}} km/h<br>R: %{{y:.2f}} kN<extra></extra>",
        ))
    fig.update_layout(get_plotly_layout(
        title=f"Davis Resistance Decomposition — {tt_id}",
        xaxis_title="Speed (km/h)",
        yaxis_title="Resistance (kN)",
        height=400,
    ))
    fig.update_xaxes(range=[0.0, v_max_kmh])
    ra, rb, rc, rt = davis_components_kn(train_type, v_max_kmh)
    pct = [(100.0 * r / rt) if rt > 0 else 0.0 for r in (ra, rb, rc)]
    fig.add_annotation(
        x=v_max_kmh, y=rt, xref="x", yref="y", xanchor="right", yanchor="bottom", ax=-40, ay=-30,
        text=(f"<b>R_total = {rt:.1f} kN</b> at {v_max_kmh:.0f} km/h<br>"
              f"A {pct[0]:.0f}% · B·v {pct[1]:.0f}% · C·v² {pct[2]:.0f}%"),
        showarrow=True, arrowhead=2, bgcolor="rgba(255, 255, 255, 0.9)",
        bordercolor=ChartColors.PRIMARY_NAVY, borderwidth=1, font=dict(size=11, color=ChartColors.TEXT_DARK),
    )
    fig.update_layout(meta={"max_speed_kmh": v_max_kmh, "r_total_at_max_kn": rt,
                            "pct_a": pct[0], "pct_b": pct[1], "pct_c": pct[2]})
    return fig


def primary_train_type(package_metadata: dict) -> Optional[Any]:
    """The run's train type (metadata ``train_type_id``) from the project, else its first train type."""
    project = (package_metadata or {}).get("project")
    types = list(getattr(getattr(project, "rolling_stock", None), "train_types", None) or [])
    if not types:
        return None
    wanted = (package_metadata or {}).get("train_type_id")
    return next((t for t in types if _get(t, "train_type_id") == wanted), types[0])
