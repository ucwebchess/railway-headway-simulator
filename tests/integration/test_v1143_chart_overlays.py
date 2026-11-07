"""v1.14.3: chart overlays in both running directions, default-off identity with v1.14.2, and
physics checks on the acceleration-phases CSV. Reporting only; no engine or importer changes.

CI uses shipped corrected examples (04_tunnel_tvs: TVS zones; 07_hsr_140km: stations). The
user's Service 8000 corridor is evidence-only (PR body) because its workbooks are never committed.
"""
import hashlib
import json
import math
from pathlib import Path

import plotly.graph_objects as go
import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_overlays import (
    TVS_FILL,
    ChartOverlayFrameError,
    add_station_overlay,
    add_tvs_overlay,
    apply_chart_overlays,
)
from headway.reporting.tables import create_accel_phases_dataframe
from headway.ui.simulation_runner import SimulationRunner
from tests.corrected_variants import load_corrected_variant

DIRECTIONS = (RunningDirection.FORWARD, RunningDirection.REVERSE)
ALL_ON = {"show_tvs_stairway": True, "show_stations_stairway": True, "show_tvs_speed": True, "show_stations_speed": True}
CHARTS = ("fig_speed_alignment", "fig_blocking_stairway")
HASHES = json.loads((Path(__file__).parents[1] / "fixtures" / "v1142_chart_hashes.json").read_text())
_CACHE = {}


def run(example, direction, **flags):
    key = (example, direction, tuple(sorted(flags.items())))
    if key not in _CACHE:
        project = load_corrected_variant(example)[0]
        _CACHE[key] = (project,) + tuple(SimulationRunner.run_simulation_pipeline(project, running_direction=direction, **flags))
    return _CACHE[key]


def bands(fig):
    return [t for t in fig.data if getattr(t, "fill", None) == "tozeroy"]


def vlines(fig):
    return [s for s in (fig.layout.shapes or ()) if s.line.dash == "dash"]


# --- default off: byte-identical to v1.14.2 -------------------------------------------------

@pytest.mark.parametrize("chart", CHARTS)
@pytest.mark.parametrize("direction", DIRECTIONS, ids=lambda d: d.name)
@pytest.mark.parametrize("example", ["04_tunnel_tvs", "07_hsr_140km"])
def test_default_off_byte_identical_to_v1142(example, direction, chart):
    _, pkg, doc = run(example, direction)
    assert pkg.metadata["chart_overlays"] == {k: False for k in ALL_ON}
    fig = doc.figures_data[chart]
    expected = HASHES[example][f"{direction.name}/{chart}"]
    assert [t.name for t in fig.data] == expected["names"]
    assert hashlib.sha256(fig.to_json().encode()).hexdigest() == expected["sha256"]


# --- REVERSE speed profile: overlays live on the chart's own (forward/physical) axis ---------

def test_reverse_speed_tvs_bands_match_forward_physical_zones():
    """TVS zones are fixed in space, so their bands must coincide in FORWARD and REVERSE."""
    def zones(direction):
        _, _, doc = run("04_tunnel_tvs", direction, **ALL_ON)
        fig = doc.figures_data["fig_speed_alignment"]
        assert all(t.fillcolor == TVS_FILL for t in bands(fig))
        return sorted((t.name, round(min(t.x), 3), round(max(t.x), 3)) for t in bands(fig))
    fwd, rev = zones(RunningDirection.FORWARD), zones(RunningDirection.REVERSE)
    assert len(fwd) == 2
    assert rev == fwd


@pytest.mark.parametrize("direction", DIRECTIONS, ids=lambda d: d.name)
def test_speed_station_lines_sit_on_the_trains_standstill(direction):
    """Each station line must be where the plotted speed trace is at rest (both directions)."""
    _, pkg, doc = run("07_hsr_140km", direction, **ALL_ON)
    fig = doc.figures_data["fig_speed_alignment"]
    speed = fig.data[0]
    rest_x = [x for x, v in zip(speed.x, speed.y) if v < 0.5]
    lines = vlines(fig)
    assert len(lines) == len(pkg.metadata["station_events"]) == 5
    for line in lines:
        assert min(abs(line.x0 - x) for x in rest_x) < 0.005, f"station line at {line.x0} km has no standstill"
    if direction is RunningDirection.REVERSE:
        L = pkg.metadata["route_length_m"]
        assert [s.x0 for s in lines] == [round(L - e.route_chainage_km * 1000, 3) / 1000 for e in pkg.metadata["station_events"]]


@pytest.mark.parametrize("direction", DIRECTIONS, ids=lambda d: d.name)
def test_stairway_overlays_stay_in_route_frame(direction):
    """The stairway plots route-frame chainage in both directions, so it never mirrors."""
    _, pkg, doc = run("04_tunnel_tvs", direction, **ALL_ON)
    fig = doc.figures_data["fig_blocking_stairway"]
    got = [(min(t.x), max(t.x)) for t in bands(fig)]
    want = [(min(e["start_chainage_m"], e["end_chainage_m"]) / 1000, max(e["start_chainage_m"], e["end_chainage_m"]) / 1000)
            for e in pkg.metadata["tvs_events"]]
    assert got == want and got


def test_mirror_maps_route_chainage_onto_reversed_axis():
    fig = go.Figure().update_layout(xaxis_title="Route Distance (km)")
    add_tvs_overlay(fig, [{"tvs_id": "Z", "start_chainage_m": 1000, "end_chainage_m": 3000}], 10000, mirror=True)
    add_station_overlay(fig, [{"station_id": "S", "chainage_m": 2500}], 10000, mirror=True)
    assert list(fig.data[0].x) == [7.0, 7.0, 9.0, 9.0]
    assert fig.layout.shapes[0].x0 == 7.5


@pytest.mark.parametrize("bad", [None, 0, -5, float("nan"), "x"])
def test_mirror_without_route_length_raises(bad):
    fig = go.Figure().update_layout(xaxis_title="Route Distance (km)")
    with pytest.raises(ChartOverlayFrameError) as exc:
        add_station_overlay(fig, [{"station_id": "S", "chainage_m": 1}], bad, mirror=True)
    assert exc.value.error_code == "ERR_CHART_OVERLAY_FRAME"
    with pytest.raises(ChartOverlayFrameError):
        add_tvs_overlay(fig, [{"tvs_id": "Z", "start_chainage_m": 0, "end_chainage_m": 1}], bad, mirror=True)


def test_mirror_flag_without_overlays_leaves_figure_untouched():
    fig = go.Figure().update_layout(xaxis_title="Route Distance (km)")
    before = fig.to_json()
    apply_chart_overlays(fig, {"route_length_m": None, "chart_overlays": {}}, "speed", mirror=True)
    assert fig.to_json() == before


# --- acceleration phases: physics-based checks (both directions) -----------------------------

def standstills(samples):
    """Start times of rest episodes after the train has moved (origin start excluded)."""
    starts, moving, resting = [], False, False
    for s in samples:
        if s.speed_ms >= 0.01:
            moving, resting = True, False
        elif moving and not resting:
            starts.append(s.time_s)
            resting = True
    return starts


@pytest.mark.parametrize("direction", DIRECTIONS, ids=lambda d: d.name)
@pytest.mark.parametrize("example", ["07_hsr_140km", "04_tunnel_tvs"])
def test_accel_phases_physics(example, direction):
    project, pkg, _ = run(example, direction)
    train = project.rolling_stock.train_types[0]
    traj = pkg.trajectories["TRN_LEADER"]
    df = create_accel_phases_dataframe(traj)
    decel = df[df.phase_type == "decel"]
    stops = standstills(traj.samples)
    assert {"accel", "decel"} <= set(df.phase_type)
    # 1. every standstill is reached through a decel phase ending at rest
    assert len(decel) >= len(stops) > 0
    for t0 in stops:
        assert ((decel.end_speed_kmh < 1.0) & ((decel.end_time_s - t0).abs() <= 2.0)).any(), f"no decel into rest at t={t0}"
    # 2. braking never exceeds the train's emergency limit
    assert decel.min_rate_ms2.abs().max() <= train.emergency_deceleration_ms2
    # 3. the typical stopping brake rate is the service limit
    stop_rates = sorted(decel[decel.end_speed_kmh < 1.0].avg_rate_ms2.abs())
    typical = stop_rates[len(stop_rates) // 2]
    assert math.isclose(typical, train.max_service_deceleration_ms2, abs_tol=0.05)
    # 4. the run starts by accelerating from rest, within the traction limit
    first = df.iloc[0]
    assert first.phase_type == "accel" and first.start_speed_kmh < 5.0
    assert 0.0 < first.avg_rate_ms2 <= train.max_acceleration_ms2 + 1e-9
