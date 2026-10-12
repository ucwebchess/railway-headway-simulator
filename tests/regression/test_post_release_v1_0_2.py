"""Targeted regression tests for Release 1.0.2 Post-Release Fixes (Round 2).

Milestone P15 — Correction Prompt RHS-CORRECTION-V1.0.2-001.
Verifies:
1. DEFECT 01: Report downloads work via embedded base64 data URIs for Google Colab compatibility (share=False).
2. DEFECT 02: Total service duration (HH:MM:SS) is computed and rendered in report summaries.
3. DEFECT 03: Speed & Alignment chart includes the permissible speed envelope as a red dashed line.
"""

import base64
import re
from typing import Any, Dict, List
import gradio as gr
import numpy as np
import pytest

from headway.data.canonical import TrackLink
from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_speed import compute_permissible_speed_envelope, create_speed_distance_figure
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_assembly import ReportAssembler, ReportSectionId, ReportType
from headway.reporting.report_config import ReportConfig
from headway.reporting.report_models import ReportDocument
from headway.simulation.trajectory import DynamicMode, OperationalState, TrajectorySample, TrainTrajectory
from headway.ui.tab_reports import create_reports_tab
from headway.ui.tab_results import create_results_tab
from headway.ui.tab_simulation import create_simulation_tab
from headway.ui.state import session_state
from tests.engineering.test_report_benchmarks import build_benchmark_package


def _make_multi_limit_links() -> List[TrackLink]:
    """Helper to create track links with varying speed limits for envelope testing."""
    return [
        TrackLink(
            link_id="TL_01",
            track_id="TRK_01",
            start_node_id="N_01",
            end_node_id="N_02",
            length_m=1000.0,
            gradient_decimal=0.005,
            max_speed_ms=25.0,  # 90.0 km/h
        ),
        TrackLink(
            link_id="TL_02",
            track_id="TRK_01",
            start_node_id="N_02",
            end_node_id="N_03",
            length_m=1500.0,
            gradient_decimal=-0.008,
            max_speed_ms=33.333,  # 120.0 km/h
        ),
        TrackLink(
            link_id="TL_03",
            track_id="TRK_01",
            start_node_id="N_03",
            end_node_id="N_04",
            length_m=800.0,
            gradient_decimal=0.0,
            max_speed_ms=16.667,  # 60.0 km/h
        ),
    ]


@pytest.mark.regression
def test_defect_01_colab_downloads_return_base64_data_uris():
    """Defect 01: Assert each download handler returns HTML with embedded base64 data URI."""
    session_state.load_example("01_single_track")
    pkg = build_benchmark_package()
    session_state.latest_result_package = pkg

    with gr.Blocks() as app:
        rep_comp = create_reports_tab()
        res_comp = create_results_tab()

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}

    report_download_handlers = [
        ("Complete Package", "download_complete_package", "application/zip", ".zip"),
        ("Formal PDF", "download_pdf", "application/pdf", ".pdf"),
        ("Interactive HTML", "download_html", "text/html;charset=utf-8", ".html"),
        ("Excel Assessment", "download_xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
        ("CSV Archive", "download_csv_zip", "application/zip", ".zip"),
        ("JSON Report", "download_json", "application/json", ".json"),
        ("Project Backup", "backup_project", "application/zip", ".zip"),
    ]

    for label, fn_name, expected_mime, expected_ext in report_download_handlers:
        update_result, status_html = fns[fn_name]()
        val = update_result.get("value") if isinstance(update_result, dict) else getattr(update_result, "value", None)
        assert val is not None, f"{label} returned None value"
        assert isinstance(val, str), f"{label} expected HTML string, got {type(val)}"

        # Verify HTML contains download link with data URI
        assert "<a download=" in val, f"{label} missing <a download= anchor tag"
        assert f"data:{expected_mime};base64," in val, f"{label} expected MIME {expected_mime} in data URI"

        # Extract base64 payload and assert validity
        pattern = rf'href="data:{re.escape(expected_mime)};base64,([A-Za-z0-9+/=]+)"'
        match = re.search(pattern, val)
        assert match is not None, f"{label} failed to extract valid base64 payload"
        b64_str = match.group(1)
        raw_bytes = base64.b64decode(b64_str)
        assert len(raw_bytes) > 0, f"{label} payload decoded to empty 0-byte content"

        # Verify internal Colab hostnames are NOT present in href
        assert ".internal" not in val, f"{label} exposed internal Colab hostname"
        assert "http://" not in val and "https://" not in val, f"{label} contains external server URL"

    # Also test Tab 9 export handlers
    results_export_handlers = [
        ("Export Excel Results", "export_excel_results", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("Export JSON Results", "export_json_results", "application/json"),
    ]
    for label, fn_name, expected_mime in results_export_handlers:
        update_res = fns[fn_name]()
        val = update_res.get("value") if isinstance(update_res, dict) else getattr(update_res, "value", None)
        assert val is not None, f"{label} returned None value"
        assert f"data:{expected_mime};base64," in val, f"{label} expected {expected_mime} data URI"
        match = re.search(r'data:[^;]+;base64,([A-Za-z0-9+/=]+)', val)
        assert match is not None, f"{label} missing valid base64 payload"
        assert len(base64.b64decode(match.group(1))) > 0


@pytest.mark.regression
def test_defect_02_total_service_duration_in_report():
    """Defect 02: Assert report document includes total service duration derived from simulation package."""
    pkg = build_benchmark_package()
    primary_traj = next(iter(pkg.trajectories.values()))
    expected_duration = primary_traj.journey_time_s
    assert expected_duration > 0.0

    doc = ReportAssembler.assemble_report(pkg)

    # 1. Assert field exists on executive_kpis
    assert hasattr(doc.executive_kpis, "total_service_duration_s")
    assert doc.executive_kpis.total_service_duration_s is not None
    assert doc.executive_kpis.total_service_duration_s == pytest.approx(expected_duration, abs=0.5)

    # 2. Assert property on ReportDocument
    assert hasattr(doc, "total_service_duration_s")
    assert doc.total_service_duration_s == pytest.approx(expected_duration, abs=0.5)

    # 3. Assert formatted HH:MM:SS string
    dur_str = doc.total_service_duration_str
    assert re.match(r"^\d{2}:\d{2}:\d{2}$", dur_str) is not None
    tot_s = int(round(expected_duration))
    exp_str = f"{tot_s // 3600:02d}:{(tot_s % 3600) // 60:02d}:{tot_s % 60:02d}"
    assert dur_str == exp_str

    # 4. Assert Section 1 KPIs contains the metric
    sec1 = doc.get_section(ReportSectionId.SPEED_GRADIENT_CURVATURE)
    assert sec1 is not None
    assert "total_service_duration_s" in sec1.kpis
    assert "Total Service Duration (End-to-End)" in sec1.kpis
    assert sec1.kpis["Total Service Duration (End-to-End)"] == dur_str

    # 5. Assert HTML report rendering includes the KPI card and value
    html_content = HtmlReportRenderer.render(doc)
    assert "Total Service Duration (End-to-End)" in html_content
    assert dur_str in html_content

    # 6. Assert serialization dictionary includes total service duration
    d = doc.to_dict()
    assert "total_service_duration_s" in d["executive_kpis"]
    assert "total_service_duration_str" in d["executive_kpis"]
    assert d["executive_kpis"]["total_service_duration_str"] == dur_str


@pytest.mark.regression
def test_defect_03_permissible_speed_envelope_in_speed_chart():
    """Defect 03: Assert speed chart displays permissible speed envelope as a red dashed line."""
    links = _make_multi_limit_links()
    total_len = sum(l.length_m for l in links)

    # Build multi-speed-limit trajectory
    samples = []
    t = 0.0
    for d in np.linspace(0.0, total_len, 40):
        t += 2.0
        # Simulated speed stays below or at 80 km/h (within envelope)
        v = min(22.2, 5.0 + d * 0.005)
        samples.append(
            TrajectorySample(
                time_s=t,
                front_distance_m=d,
                rear_distance_m=max(0.0, d - 100.0),
                speed_ms=v,
                acceleration_ms2=0.0,
                traction_force_n=0.0,
                braking_force_n=0.0,
                davis_resistance_n=0.0,
                gradient_resistance_n=0.0,
                curvature_resistance_n=0.0,
                net_force_n=0.0,
                dynamic_mode=DynamicMode.CRUISING,
                operational_state=OperationalState.RUNNING,
            )
        )
    traj_fwd = TrainTrajectory(
        train_id="TRN_TEST",
        train_type_id="TT_METRO",
        route_id="RT_01",
        running_direction=RunningDirection.FORWARD,
        samples=samples,
    )

    # Test FORWARD direction envelope calculation
    env_fwd = compute_permissible_speed_envelope(
        track_links=links,
        rolling_stock_max_speed_kmh=100.0,  # Caps link 2 (120 km/h) at 100 km/h
        running_direction=RunningDirection.FORWARD,
    )
    assert len(env_fwd) == 6  # 3 links * 2 points per step interval
    assert env_fwd[0]["route_distance_m"] == 0.0
    assert env_fwd[0]["max_speed_kmh"] == pytest.approx(90.0, abs=0.1)  # Link 1: 25 m/s = 90 km/h
    assert env_fwd[2]["max_speed_kmh"] == pytest.approx(100.0, abs=0.1)  # Link 2: capped by train 100 km/h
    assert env_fwd[4]["max_speed_kmh"] == pytest.approx(60.0, abs=0.1)  # Link 3: 16.667 m/s = 60 km/h

    # Test REVERSE direction envelope calculation
    env_rev = compute_permissible_speed_envelope(
        track_links=links,
        rolling_stock_max_speed_kmh=100.0,
        running_direction=RunningDirection.REVERSE,
    )
    assert len(env_rev) == 6
    # In REVERSE, Link 3 is first (60 km/h), then Link 2 (100 km/h), then Link 1 (90 km/h)
    assert env_rev[0]["max_speed_kmh"] == pytest.approx(60.0, abs=0.1)
    assert env_rev[2]["max_speed_kmh"] == pytest.approx(100.0, abs=0.1)
    assert env_rev[4]["max_speed_kmh"] == pytest.approx(90.0, abs=0.1)

    # Test Plotly speed distance figure generation
    fig = create_speed_distance_figure(
        traj_fwd,
        permissible_speed_envelope=env_fwd,
        running_direction=RunningDirection.FORWARD,
    )
    assert len(fig.data) >= 2

    # Simulated speed trace
    sim_trace = next(t for t in fig.data if "Simulated Speed" in t.name or "TRN_TEST" in t.name)
    assert sim_trace is not None
    assert sim_trace.mode == "lines"

    # Permissible speed envelope trace
    env_trace = next(t for t in fig.data if "Permissible Speed" in t.name)
    assert env_trace is not None
    assert env_trace.line.dash == "dash"
    assert env_trace.line.color == "#C62828"
    assert "Permissible Speed Envelope" in env_trace.name

    # Check simulated speed does not exceed the envelope
    max_sim_speed = max(sim_trace.y)
    min_env_speed = min(env_trace.y)
    # The simulated speed in the middle was at most 22.2 m/s = 80 km/h, well within 90/100 km/h
    assert max_sim_speed <= max(env_trace.y) + 1e-3
