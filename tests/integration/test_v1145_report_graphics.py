"""v1.14.5: report graphics and labeling corrections (presentation only).

Datasets: corrected 07_hsr_140km (rolling-stock charts, alignment geometry, all stations served),
corrected 05_comprehensive_line (served and unused stations, TVS zones) and corrected 04_tunnel_tvs
(TVS overlays). Every report-level check runs in FORWARD and REVERSE.
"""
from __future__ import annotations

import re

import openpyxl
import pytest
from reportlab import rl_config

from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_alignment import (
    PLATFORM_COLOR,
    ROUTE_COLOR,
    STOP_COLOR,
    STOP_TRACE,
    TICK_TRACE,
    TVS_FILL,
    UNUSED_COLOR,
    UNUSED_TRACE,
    ChartAlignmentFrameError,
    create_service_alignment_figure,
)
from headway.reporting.charts_rolling_stock import DAVIS_TRACE_NAMES, TRACTIVE_TRACE_NAME
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.html_widgets import CSV_BUTTON_STYLE
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_assembly import ReportAssembler, ReportProjectIdMissingError
from headway.reporting.report_models import REPORT_FOOTER_LABEL, REPORT_SOFTWARE_LABEL, ReportSectionId
from headway.ui.simulation_runner import SimulationRunner
from tests.corrected_variants import load_corrected_variant
from tests.engineering.test_report_benchmarks import build_benchmark_package

FWD, REV = RunningDirection.FORWARD, RunningDirection.REVERSE
DIRECTIONS = (FWD, REV)
TVS_ON = {"show_tvs_stairway": True, "show_tvs_speed": True}

# Corrected 07 TRN_HSR rated data (workbook RollingStock sheet; no tabulated traction curve).
HSR_POWER_W = 8.8e6
HSR_F_MAX_N = 320_000.0
HSR_V_TRANSITION_MS = HSR_POWER_W / HSR_F_MAX_N  # 27.5 m/s = 99 km/h


def _run(example, **flags):
    project = load_corrected_variant(example)[0]
    return project, {d: SimulationRunner.run_simulation_pipeline(project, running_direction=d, **flags) for d in DIRECTIONS}


@pytest.fixture(scope="module")
def hsr():
    return _run("07_hsr_140km")


@pytest.fixture(scope="module")
def mixed():
    return _run("05_comprehensive_line")


@pytest.fixture(scope="module")
def tunnel():
    return _run("04_tunnel_tvs", **TVS_ON)


@pytest.fixture(scope="module")
def hsr_html(hsr):
    _, runs = hsr
    return {d: HtmlReportRenderer.render(runs[d][1], embed_interactive_plotly=True) for d in DIRECTIONS}


@pytest.fixture(scope="module")
def hsr_pdf_bytes(hsr, tmp_path_factory):
    """PDF bytes with page compression off so header/footer strings are searchable."""
    _, runs = hsr
    saved = rl_config.pageCompression
    rl_config.pageCompression = 0
    try:
        out = {}
        for d in DIRECTIONS:
            path = tmp_path_factory.mktemp("pdf") / f"{d.name}.pdf"
            PdfReportRenderer.render(runs[d][1], output_path=path)
            out[d] = path.read_bytes()
        return out
    finally:
        rl_config.pageCompression = saved


def _xlsx_header(doc, tmp_path):
    path = tmp_path / "r.xlsx"
    ExcelReportExporter.export(doc, output_path=path)
    ws = openpyxl.load_workbook(path)["Executive_Summary"]
    return [str(c.value) for row in ws.iter_rows(max_row=6) for c in row if c.value is not None]


def _table(doc, section_id, title_part):
    return next(t for t in doc.sections[section_id].tables if title_part in t.title)


# ----------------------------------------------------------------------------------------------
# Task 1: Software label
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_software_label_in_header_and_section12(hsr, hsr_html, direction):
    _, runs = hsr
    doc = runs[direction][1]
    assert REPORT_SOFTWARE_LABEL == "OpenTrack-2026"
    assert doc.metadata.software_version == "OpenTrack-2026"
    html = hsr_html[direction]
    assert "Software: OpenTrack-2026" in html
    assert "1.3.0" not in html
    audit = doc.sections[ReportSectionId.ASSUMPTIONS_AUDIT]
    assert audit.kpis["Software Version"] == "OpenTrack-2026"  # Section 12 audit table
    assert "1.3.0" not in [str(v) for v in audit.kpis.values()]


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_software_and_project_in_pdf_and_excel(hsr, hsr_pdf_bytes, tmp_path, direction):
    project, runs = hsr
    pdf = hsr_pdf_bytes[direction]
    assert b"Software: OpenTrack-2026" in pdf
    assert b"Project: " in pdf and project.project_id.encode() in pdf
    assert b"1.3.0" not in pdf
    header = _xlsx_header(runs[direction][1], tmp_path)
    assert any(h.startswith(f"Project: {project.project_id} | Scenario: ") for h in header), header


# ----------------------------------------------------------------------------------------------
# Task 2: Project ID from workbook METADATA PROJECT_ID
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_project_header_reads_workbook_project_id(tunnel, direction):
    project, runs = tunnel
    pkg, doc = runs[direction]
    assert project.project_id == "PRJ_EX04_TVS"
    # Not derived from the scenario ID any more.
    assert project.project_id != pkg.scenario_id.split("_")[0]
    assert doc.metadata.project_id == "PRJ_EX04_TVS"
    html = HtmlReportRenderer.render(doc, embed_interactive_plotly=False)
    assert "Project: <b>PRJ_EX04_TVS</b>" in html


@pytest.mark.parametrize("value", [None, "", "   ", "PRJ_DEFAULT"], ids=["missing", "empty", "blank", "converter_default"])
def test_project_id_missing_raises(monkeypatch, value):
    from headway.ui.state import session_state

    monkeypatch.setattr(session_state, "current_project", None, raising=False)
    pkg = build_benchmark_package()
    if value is None:
        pkg.metadata.pop("project_id", None)
    else:
        pkg.metadata["project_id"] = value
    with pytest.raises(ReportProjectIdMissingError) as exc:
        ReportAssembler.assemble_report(pkg)
    assert exc.value.error_code == "ERR_REPORT_PROJECT_ID_MISSING"


def test_project_id_converter_default_on_bound_project_raises(monkeypatch, hsr):
    from headway.ui.state import session_state

    monkeypatch.setattr(session_state, "current_project", None, raising=False)
    project, _ = hsr
    stub = type("BoundProject", (), {"project_id": "PRJ_DEFAULT", "rolling_stock": project.rolling_stock})()
    with pytest.raises(ReportProjectIdMissingError) as exc:
        ReportAssembler.assemble_report(build_benchmark_package(), project=stub)
    assert exc.value.error_code == "ERR_REPORT_PROJECT_ID_MISSING"


# ----------------------------------------------------------------------------------------------
# Task 3: CSV buttons
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_csv_buttons_identical_style_in_one_panel(hsr_html, direction):
    html = hsr_html[direction]
    panels = re.findall(r'<div class="csv-download-panel"[^>]*>(.*?)</div>', html, flags=re.DOTALL)
    assert len(panels) == 1
    buttons = re.findall(r'<a [^>]*class="csv-download-btn" style="([^"]*)">📥 ([^<]+)</a>', panels[0])
    assert [label for _, label in buttons] == ["Download Speed Profile CSV", "Download Acceleration Phases CSV"]
    assert buttons[0][0] == buttons[1][0] == CSV_BUTTON_STYLE
    assert html.count("Download Acceleration Phases CSV") == 1


# ----------------------------------------------------------------------------------------------
# Task 4: stairway annotation box
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_stairway_annotation_top_centre(hsr, direction):
    _, runs = hsr
    fig = runs[direction][1].figures_data["fig_blocking_stairway"]
    boxes = [a for a in fig.layout.annotations if "Technical Minimum Headway" in (a.text or "")]
    assert len(boxes) == 1
    box = boxes[0]
    assert (box.xref, box.yref, box.x, box.y) == ("paper", "paper", 0.5, 0.98)
    assert (box.xanchor, box.yanchor) == ("center", "top")
    assert box.y < 1.0  # inside the plot area, below the title


# ----------------------------------------------------------------------------------------------
# Tasks 5 and 6: TVS labels and legend
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
@pytest.mark.parametrize("chart", ["fig_speed_alignment", "fig_blocking_stairway"])
def test_tvs_labels_at_band_bottom(tunnel, direction, chart):
    _, runs = tunnel
    pkg, doc = runs[direction]
    fig = doc.figures_data[chart]
    zones = [str(ev["tvs_id"]) for ev in pkg.metadata["tvs_events"]]
    labels = [t for t in fig.data if (t.name or "").startswith("TVS label: ")]
    assert [t.text[0] for t in labels] == zones
    assert fig.layout.yaxis2.range == (0, 1)
    for t in labels:
        assert t.yaxis == "y2" and t.y == (0.0,)          # anchored on the x-axis line
        assert t.textposition == "top center"            # text drawn above it, clear of tick labels
        assert t.textfont.size == 11 and t.cliponaxis is False
    bands = [t for t in fig.data if getattr(t, "fill", None) == "tozeroy"]
    assert [b.fillcolor for b in bands] == ["rgba(255, 165, 0, 0.15)"] * len(zones)  # shading unchanged


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
@pytest.mark.parametrize("chart", ["fig_speed_alignment", "fig_blocking_stairway"])
def test_tvs_legend_entries_are_zone_ids(tunnel, direction, chart):
    _, runs = tunnel
    pkg, doc = runs[direction]
    fig = doc.figures_data[chart]
    legend = [t.name for t in fig.data if getattr(t, "fill", None) == "tozeroy" and t.showlegend is not False]
    assert legend == [str(ev["tvs_id"]) for ev in pkg.metadata["tvs_events"]]
    assert sorted(legend) == ["TVS_01", "TVS_02"]
    assert not any("TVS zone" in (t.name or "") for t in fig.data)


# ----------------------------------------------------------------------------------------------
# Tasks 7, 8, 9: removed columns and sentence
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_section5_resource_category_removed(hsr, hsr_html, direction):
    _, runs = hsr
    tbl = _table(runs[direction][1], ReportSectionId.LONGEST_OCCUPATIONS, "Longest Resource Occupation Durations")
    assert "Resource Category" not in tbl.raw_dataframe.columns
    assert "Resource Category" not in tbl.formatted_dataframe.columns
    assert "Resource Category" not in hsr_html[direction]


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_section11_provenance_columns(hsr, hsr_html, direction):
    _, runs = hsr
    sec = runs[direction][1].sections[ReportSectionId.GEOMETRY_PROVENANCE]
    # Heading follows the other section headings (none end in "Register"); no baseline-integrity claim.
    assert sec.title == "Resource Geometry Provenance"
    assert f"{sec.section_number} Resource Geometry Provenance</h2>" in hsr_html[direction]
    assert "Baseline Integrity" not in hsr_html[direction]
    tbl = _table(runs[direction][1], ReportSectionId.GEOMETRY_PROVENANCE, "Resource Geometry Provenance Register")
    assert tbl.title == "Resource Geometry Provenance Register"
    assert list(tbl.raw_dataframe.columns) == [
        "Resource ID", "Type", "Physical Chainage (km)", "Length (m)", "Physical End Chainage (km)",
        "Entry Signal ID", "Entry Signal Ch. (km)", "Exit Signal ID", "Exit Signal Ch. (km)",
    ]
    for col in ("Dataset ID", "Version", "Baseline Invariant"):
        assert f"<th>{col}</th>" not in hsr_html[direction]
    # The Platform Segment Provenance table keeps Geometry Source (how each platform was derived).
    seg = _table(runs[direction][1], ReportSectionId.GEOMETRY_PROVENANCE, "Platform Segment Provenance")
    assert "Geometry Source" in seg.raw_dataframe.columns
    assert set(seg.raw_dataframe["Geometry Source"]) <= {"PLATFORM_SPAN_AUTO_SEGMENTATION", "PLATFORM_CANONICAL"}


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_section12_auditability_sentence_removed(hsr, hsr_html, direction):
    _, runs = hsr
    sec = runs[direction][1].sections[ReportSectionId.ASSUMPTIONS_AUDIT]
    assert sec.kpis["Software Version"] == "OpenTrack-2026"  # heading and audit table kept
    assert f"{sec.section_number} {sec.title}" in hsr_html[direction]
    assert not any("software build versions" in p for p in sec.narrative_paragraphs)
    assert len(sec.narrative_paragraphs) == 1 and sec.narrative_paragraphs[0].startswith("Operational Performance Factor")
    assert "auditability" not in hsr_html[direction]


# ----------------------------------------------------------------------------------------------
# Task 10: footer
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_footer_html_and_pdf(hsr_html, hsr_pdf_bytes, direction):
    assert REPORT_FOOTER_LABEL == "Headway & Capacity Simulation - OpenTrack 2026"
    assert "Headway &amp; Capacity Simulation - OpenTrack 2026" in hsr_html[direction]
    assert b"Headway & Capacity Simulation - OpenTrack 2026" in hsr_pdf_bytes[direction]


# ----------------------------------------------------------------------------------------------
# Task 11: rolling-stock charts (corrected 07, TRN_HSR)
# ----------------------------------------------------------------------------------------------
def _te(hsr, direction=FWD):
    return hsr[1][direction][1].figures_data["fig_tractive_effort"]


def _davis(hsr, direction=FWD):
    return hsr[1][direction][1].figures_data["fig_davis_resistance"]


def _hsr_tt(hsr):
    return next(t for t in hsr[0].rolling_stock.train_types if t.train_type_id == "TRN_HSR")


def test_tractive_effort_curve_rendered(hsr, hsr_html):
    fig = _te(hsr)
    tt = _hsr_tt(hsr)
    assert (tt.power_w, tt.max_tractive_effort_n) == (HSR_POWER_W, HSR_F_MAX_N)
    assert [t.name for t in fig.data] == [TRACTIVE_TRACE_NAME]
    assert fig.layout.title.text == "<b>Tractive Effort Curve — TRN_HSR</b>"
    assert fig.layout.xaxis.range == (0.0, pytest.approx(tt.max_speed_ms * 3.6))
    assert "km/h" in fig.layout.xaxis.title.text and "kN" in fig.layout.yaxis.title.text
    hline = [s for s in fig.layout.shapes if s.y0 == s.y1]
    vline = [s for s in fig.layout.shapes if s.x0 == s.x1]
    assert len(hline) == 1 and hline[0].y0 == pytest.approx(320.0) and hline[0].line.dash == "dot"
    assert len(vline) == 1 and vline[0].x0 == pytest.approx(99.0) and vline[0].line.dash == "dash"
    assert fig.layout.meta["v_transition_ms"] == pytest.approx(27.5)
    assert any("v_transition" in (a.text or "") and "27.5 m/s" in a.text for a in fig.layout.annotations)
    # Direction-independent rated curve, rendered side by side under Rolling Stock Characteristics.
    assert _te(hsr, REV).to_json() == fig.to_json()
    for html in hsr_html.values():
        block = html.split("rolling-stock-charts", 1)[1].split("Governing Bottleneck Diagnosis", 1)[0]
        assert "two-col-grid" in block and block.count("rs-chart") == 2
        assert "Tractive Effort Curve" in block and "Davis Resistance Decomposition" in block


def test_tractive_effort_constant_torque_below_transition(hsr):
    trace = _te(hsr).data[0]
    below = [(v, f) for v, f in zip(trace.x, trace.y) if v / 3.6 < HSR_V_TRANSITION_MS]
    assert len(below) > 10 and below[0][0] == 0.0
    assert all(f == pytest.approx(320.0, abs=1e-9) for _, f in below)


def test_tractive_effort_constant_power_above_transition(hsr):
    trace = _te(hsr).data[0]
    above = [(v / 3.6, f * 1000.0) for v, f in zip(trace.x, trace.y) if v / 3.6 > HSR_V_TRANSITION_MS]
    assert len(above) > 10
    for v_ms, f_n in above:
        assert f_n * v_ms == pytest.approx(HSR_POWER_W, rel=0.01)
    assert above[-1][0] == pytest.approx(_hsr_tt(hsr).max_speed_ms)


def test_davis_resistance_decomposition_rendered(hsr):
    fig = _davis(hsr)
    assert tuple(t.name for t in fig.data) == DAVIS_TRACE_NAMES == (
        "A (rolling)", "B·v (mechanical)", "C·v² (aerodynamic)", "Total R(v)")
    assert [t.line.dash for t in fig.data] == ["dot", "dash", "dashdot", "solid"]
    assert fig.layout.title.text == "<b>Davis Resistance Decomposition — TRN_HSR</b>"
    assert "kN" in fig.layout.yaxis.title.text
    assert _davis(hsr, REV).to_json() == fig.to_json()


def test_davis_resistance_at_max_speed(hsr):
    tt = _hsr_tt(hsr)
    v = tt.max_speed_ms
    expected_kn = (tt.davis_a_n + tt.davis_b_ns_m * v + tt.davis_c_ns2_m2 * v * v) / 1000.0
    fig = _davis(hsr)
    total = fig.data[3]
    assert total.x[-1] == pytest.approx(v * 3.6)
    assert total.y[-1] == pytest.approx(expected_kn, abs=0.1)
    assert fig.layout.meta["r_total_at_max_kn"] == pytest.approx(expected_kn, abs=0.1)
    ann = [a.text for a in fig.layout.annotations if "R_total" in (a.text or "")]
    assert len(ann) == 1 and f"R_total = {expected_kn:.1f} kN" in ann[0]
    pct = [100.0 * x / (expected_kn * 1000.0) for x in (tt.davis_a_n, tt.davis_b_ns_m * v, tt.davis_c_ns2_m2 * v * v)]
    assert f"A {pct[0]:.0f}% · B·v {pct[1]:.0f}% · C·v² {pct[2]:.0f}%" in ann[0]


def test_davis_components_sum_to_total(hsr):
    tt = _hsr_tt(hsr)
    a, b, c, total = _davis(hsr).data
    idx = [round(i * (len(total.x) - 1) / 9) for i in range(10)]
    assert len(set(idx)) == 10
    for i in idx:
        v = total.x[i] / 3.6
        assert a.y[i] + b.y[i] + c.y[i] == pytest.approx(total.y[i], abs=0.01)
        assert total.y[i] == pytest.approx((tt.davis_a_n + tt.davis_b_ns_m * v + tt.davis_c_ns2_m2 * v * v) / 1000.0, abs=0.01)


# ----------------------------------------------------------------------------------------------
# Task 12: Service Alignment Diagram
# ----------------------------------------------------------------------------------------------
def _diag(runs, direction):
    return runs[direction][1].figures_data["fig_service_alignment"]


def _trace(fig, name):
    return next(t for t in fig.data if t.name == name)


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_service_alignment_diagram_rendered(hsr, hsr_html, direction):
    _, runs = hsr
    pkg, doc = runs[direction]
    fig = _diag(runs, direction)
    assert doc.sections[ReportSectionId.STATION_PLATFORM_OCCUPATION].post_table_figure_keys == ["fig_service_alignment"]
    title = fig.layout.title.text
    assert "Service Alignment Diagram — TRN_HSR / " in title
    assert pkg.metadata["active_service_pattern_id"] in title
    assert fig.layout.height == 400
    assert fig.layout.paper_bgcolor == fig.layout.plot_bgcolor == "#FFFFFF"
    route = _trace(fig, "Route")
    L_km = pkg.metadata["route_length_m"] / 1000.0
    assert route.x == (0.0, pytest.approx(L_km)) and route.line.color == ROUTE_COLOR and route.line.width == 2
    ticks = _trace(fig, TICK_TRACE)
    assert ticks.line.color == "#000000" and ticks.line.width == 1
    bars = [t for t in fig.data if (t.name or "").startswith("Platform track: ")]
    assert bars and all(t.line.color == PLATFORM_COLOR for t in bars)
    # HTML placement: after the Section 6 platform tables, before Section 7.
    html = hsr_html[direction]
    s6 = doc.sections[ReportSectionId.STATION_PLATFORM_OCCUPATION]
    s7 = doc.sections[ReportSectionId.MIXED_TRAFFIC_MATRIX]
    i6 = html.index(f"{s6.section_number} {s6.title}")
    i_tbl = html.index(s6.tables[-1].title, i6)
    i_fig = html.index("Service Alignment Diagram", i_tbl)
    i7 = html.index(f"{s7.section_number} {s7.title}")
    assert i6 < i_tbl < i_fig < i7


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_service_alignment_station_positions(hsr, direction):
    _, runs = hsr
    pkg, _ = runs[direction]
    fig = _diag(runs, direction)
    events = pkg.metadata["station_events"]
    expected = [round(float(ev.route_chainage_km), 6) for ev in events]
    stops = _trace(fig, STOP_TRACE)
    assert list(stops.text) == [ev.station_id for ev in events]
    assert list(stops.x) == pytest.approx(expected, abs=1e-6)
    tick_x = sorted({x for x in _trace(fig, TICK_TRACE).x if x is not None})
    assert tick_x == pytest.approx(sorted(expected), abs=1e-6)
    labels = {a.text: a.x for a in fig.layout.annotations if a.text in {ev.station_id for ev in events}}
    assert labels == {ev.station_id: pytest.approx(x, abs=1e-6) for ev, x in zip(events, expected)}
    # Every stop lies on one of its station's platform bars.
    for ev, x in zip(events, expected):
        bars = [t for t in fig.data if (t.name or "").startswith("Platform track: ")]
        spans = [(bar.x[i], bar.x[i + 1]) for bar in bars for i in range(0, len(bar.x), 3)
                 if f"({ev.station_id})" in bar.text[i]]
        assert any(lo - 0.001 <= x <= hi + 0.001 for lo, hi in spans), (ev.station_id, x, spans)


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_service_alignment_used_vs_unused_stops(mixed, hsr, direction):
    _, runs = mixed
    pkg, _ = runs[direction]
    fig = _diag(runs, direction)
    served = [ev.station_id for ev in pkg.metadata["station_events"]]
    assert served == ["STN_BETA"]
    stops, unused = _trace(fig, STOP_TRACE), _trace(fig, UNUSED_TRACE)
    assert list(stops.text) == served
    assert sorted(unused.text) == ["STN_ALPHA", "STN_GAMMA"]
    assert stops.marker.symbol == "circle" and stops.marker.color == STOP_COLOR
    assert unused.marker.symbol == "circle-open" and unused.marker.color == UNUSED_COLOR
    assert fig.layout.meta["served_stations"] == served
    assert sorted(fig.layout.meta["unused_stations"]) == ["STN_ALPHA", "STN_GAMMA"]
    # 07: every station is a stop, so the hollow-marker trace is empty.
    hsr_fig = _diag(hsr[1], direction)
    assert len(_trace(hsr_fig, UNUSED_TRACE).x) == 0
    assert len(_trace(hsr_fig, STOP_TRACE).x) == len(hsr[1][direction][0].metadata["station_events"]) == 5


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_service_alignment_tvs_bands(mixed, hsr, direction):
    _, runs = mixed
    pkg, doc = runs[direction]
    fig = _diag(runs, direction)
    events = pkg.metadata["tvs_events"]
    assert events
    bands = [t for t in fig.data if getattr(t, "fill", None) == "toself"]
    expected = {}
    for ev in events:
        lo, hi = sorted((ev["start_chainage_m"] / 1000.0, ev["end_chainage_m"] / 1000.0))
        expected[(str(ev["tvs_id"]), lo, hi)] = None
    assert [(b.name, min(b.x), max(b.x)) for b in bands] == list(expected)
    for b in bands:
        assert b.fillcolor == TVS_FILL == "rgba(255, 165, 0, 0.3)"
        assert max(b.y) < 0.0  # below the route line
        assert any(a.text == b.name and a.y == min(b.y) and a.yanchor == "top" for a in fig.layout.annotations)
    # Same zones as the Section 13 TVS assessment.
    s13 = doc.sections[ReportSectionId.TVS_ASSESSMENT]
    s13_ids = {str(v) for t in s13.tables if "TVS ID" in t.raw_dataframe.columns for v in t.raw_dataframe["TVS ID"]}
    assert {b.name for b in bands} == s13_ids
    # 07 has no TVS zones, hence no bands.
    assert hsr[1][direction][0].metadata["tvs_events"] == []
    assert not [t for t in _diag(hsr[1], direction).data if getattr(t, "fill", None) == "toself"]


@pytest.mark.parametrize("direction", DIRECTIONS, ids=["FWD", "REV"])
def test_service_alignment_direction_indicator(hsr, direction):
    _, runs = hsr
    pkg, _ = runs[direction]
    fig = _diag(runs, direction)
    L_km = pkg.metadata["route_length_m"] / 1000.0
    text = [a for a in fig.layout.annotations if (a.text or "").startswith("<b>Service direction:")]
    assert len(text) == 1 and text[0].text == f"<b>Service direction: {direction.value}</b>"
    arrows = [a for a in fig.layout.annotations if a.showarrow]
    assert len(arrows) == 1
    assert (arrows[0].ax, arrows[0].x) == (0.0, pytest.approx(L_km))  # run origin -> run end
    assert fig.layout.meta["direction"] == direction.value
    expected_range = (0.0, pytest.approx(L_km)) if direction == FWD else (pytest.approx(L_km), 0.0)
    assert fig.layout.xaxis.range == expected_range


def test_service_alignment_frame_error_raises():
    platforms = [{"platform_id": "PLT_A", "station_id": "STN_A", "track_id": "TRK_1", "start_m": 1000.0, "end_m": 1200.0}]
    stop_off_platform = [{"station_id": "STN_A", "platform_id": "PLT_A@s1", "route_chainage_km": 1.5}]
    with pytest.raises(ChartAlignmentFrameError) as exc:
        create_service_alignment_figure(5000.0, stop_off_platform, platforms)
    assert exc.value.error_code == "ERR_CHART_ALIGNMENT_FRAME"
    with pytest.raises(ChartAlignmentFrameError):
        create_service_alignment_figure(0.0, [], platforms)
    ok = create_service_alignment_figure(5000.0, [{"station_id": "STN_A", "platform_id": "PLT_A", "route_chainage_km": 1.1}], platforms)
    assert list(_trace(ok, STOP_TRACE).x) == [1.1]
