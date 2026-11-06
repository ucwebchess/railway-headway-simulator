"""Reporting-only regression coverage; no engine or importer modifications."""
import base64
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd
import plotly.graph_objects as go
import pytest

from headway.reporting.chart_overlays import add_station_overlay, add_tvs_overlay, apply_chart_overlays
from headway.reporting.charts_blocking import create_blocking_stairway_figure
from headway.reporting.charts_speed import create_speed_distance_figure
from headway.reporting.tables import ACCEL_PHASE_COLUMNS, create_accel_phases_csv, create_accel_phases_dataframe
from headway.infrastructure.direction import RunningDirection
from headway.ui.simulation_runner import SimulationRunner
from tests.corrected_variants import load_corrected_variant


@pytest.fixture(scope="module")
def hsr():
    project, _, _ = load_corrected_variant("07_hsr_140km")
    return SimulationRunner.run_simulation_pipeline(project, RunningDirection.FORWARD)


def speed(pkg, metadata=None):
    return create_speed_distance_figure(pkg.trajectories["TRN_LEADER"],
        permissible_speed_envelope=pkg.metadata["permissible_speed_envelope"],
        track_links=pkg.metadata["track_links"], running_direction=pkg.running_direction,
        metadata=metadata)


@pytest.fixture(scope="module")
def tunnel():
    project, _, _ = load_corrected_variant("04_tunnel_tvs")
    return SimulationRunner.run_simulation_pipeline(project, RunningDirection.FORWARD, show_tvs_stairway=True)


def test_tvs_overlay_added_when_flag_true(tunnel):
    pkg, doc = tunnel
    meta = dict(pkg.metadata, chart_overlays={"show_tvs_stairway": True})
    fig = create_blocking_stairway_figure(next(iter(pkg.headway_results.values())), metadata=meta)
    bands = [t for t in fig.data if getattr(t, "fill", None) == "tozeroy"]
    assert len(bands) == len(pkg.metadata["tvs_events"])
    assert bands
    assert any(getattr(t, "fill", None) == "tozeroy" for t in doc.figures_data["fig_blocking_stairway"].data)
    for trace, event in zip(bands, pkg.metadata["tvs_events"]):
        assert min(trace.x) == min(event["start_chainage_m"], event["end_chainage_m"]) / 1000
        assert max(trace.x) == max(event["start_chainage_m"], event["end_chainage_m"]) / 1000
        assert trace.fillcolor == "rgba(255, 165, 0, 0.15)"


def test_tvs_overlay_absent_when_flag_false(hsr):
    pkg, _ = hsr
    hashes = json.loads((Path(__file__).parents[1] / "fixtures/v1141_chart_hashes.json").read_text())
    figures = {"fig_speed_alignment": speed(pkg, pkg.metadata),
               "fig_blocking_stairway": create_blocking_stairway_figure(next(iter(pkg.headway_results.values())), metadata=pkg.metadata)}
    for key, fig in figures.items():
        assert [t.name for t in fig.data] == hashes[key]["names"]
        assert hashlib.sha256(fig.to_json().encode()).hexdigest() == hashes[key]["sha256"]


def test_station_overlay_added_when_flag_true(hsr):
    pkg, _ = hsr
    fig = speed(pkg, dict(pkg.metadata, chart_overlays={"show_stations_speed": True}))
    assert [s.x0 for s in fig.layout.shapes] == [s.route_chainage_km for s in pkg.metadata["station_events"]]
    assert all(s.line.dash == "dash" for s in fig.layout.shapes)


@pytest.mark.parametrize("unit,scale", [("km", 1000), ("m", 1)])
def test_overlay_chainages_match_metadata(unit, scale):
    fig = go.Figure().update_layout(xaxis_title=f"Route Distance ({unit})")
    add_tvs_overlay(fig, [{"tvs_id": "Z", "start_chainage_m": 8000, "end_chainage_m": 3000}], 10000)
    add_station_overlay(fig, [{"station_id": "S", "chainage_m": 5000}], 10000)
    assert list(fig.data[0].x) == [3000/scale, 3000/scale, 8000/scale, 8000/scale]
    assert fig.layout.shapes[0].x0 == 5000/scale
    assert fig.layout.annotations[0].text == "S"


def trajectory(times, speeds):
    return NS(samples=[NS(time_s=t, speed_ms=v, front_distance_m=t*10) for t,v in zip(times,speeds)])


def test_accel_phases_csv_columns():
    csv = create_accel_phases_csv(trajectory(range(4), range(4)))
    assert pd.read_csv(io.StringIO(csv)).columns.tolist() == ACCEL_PHASE_COLUMNS
    assert len(ACCEL_PHASE_COLUMNS) == 12


def test_accel_phases_merge_consecutive_samples():
    # Use a physical acceleration rate above the requested classification threshold.
    df = create_accel_phases_dataframe(trajectory([i/100 for i in range(10001)], [i*320/3.6/10000 for i in range(10001)]))
    assert len(df) == 1
    assert df.iloc[0].phase_type == "accel"
    assert df.iloc[0].end_speed_kmh == pytest.approx(320)


def test_accel_phases_reject_short_phases():
    df = create_accel_phases_dataframe(trajectory([0,1,2,3,4], [0,1,1,1,1]))
    assert df.phase_type.tolist() == ["cruise"]
    assert df.phase_id.tolist() == [1]


def test_accel_phases_irregular_and_invalid_intervals():
    df = create_accel_phases_dataframe(trajectory([0,1,4,4,7], [0,1,7,8,11]))
    assert df.avg_rate_ms2.tolist() == [1.75, 1]
    assert df.distance_m.ge(0).all()
    assert create_accel_phases_dataframe(trajectory([], [])).empty


def test_accel_phases_on_07_hsr(hsr):
    pkg, _ = hsr
    df = create_accel_phases_dataframe(pkg.trajectories["TRN_LEADER"])
    # Current corrected fixture includes origin/terminal manoeuvres and five dwells:
    # 21 phases, rather than the brief's estimated upper bound of 20.
    assert df.phase_type.value_counts().to_dict() == {"cruise": 9, "accel": 6, "decel": 6}
    decel = df[df.phase_type == "decel"]
    assert decel.min_rate_ms2.abs().max() <= 1.15
    assert decel.avg_rate_ms2.between(-0.9, -0.6).all()


def test_report_and_downloads(hsr):
    from headway.reporting.html_renderer import HtmlReportRenderer
    pkg, doc = hsr
    csv = create_accel_phases_csv(pkg.trajectories["TRN_LEADER"])
    rendered = HtmlReportRenderer.render(doc)
    assert base64.b64encode(csv.encode()).decode() in rendered
    assert 'download="acceleration_phases.csv"' in rendered


def test_mid_session_overlays_do_not_leak(hsr):
    pkg, _ = hsr
    before = speed(pkg, pkg.metadata).to_json()
    enabled = speed(pkg, dict(pkg.metadata, chart_overlays={"show_tvs_speed": True, "show_stations_speed": True}))
    assert len(enabled.layout.shapes) == len(pkg.metadata["station_events"])
    assert speed(pkg, pkg.metadata).to_json() == before


def test_ui_checkboxes_default_off_and_wired():
    import gradio as gr
    from headway.ui.tab_simulation import create_simulation_tab
    from headway.ui.tab_results import create_results_tab
    keys = ["show_tvs_stairway", "show_stations_stairway", "show_tvs_speed", "show_stations_speed"]
    with gr.Blocks() as demo:
        components = create_simulation_tab()
        results = create_results_tab()
    for key in keys:
        assert components[key].value is False
    assert results["export_accel_csv_btn"].value == "Export Acceleration Phases CSV (.csv)"
    dependencies = demo.get_config_file()["dependencies"]
    run = next(d for d in dependencies if d["targets"] == [(components["btn_run_simulation"]._id, "click")])
    assert run["inputs"][-4:] == [components[k]._id for k in keys]
