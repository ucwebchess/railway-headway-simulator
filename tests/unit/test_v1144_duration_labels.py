"""v1.14.4: time reference-frame labeling of the Total Service Duration KPI.

The KPI measures origin departure -> terminus arrival (absolute simulation time), while the
trajectory runs from the start of the run to the physical end of track. These tests pin the
labels on every surface that shows the KPI:
  * Section 8 (station stopping) table footnote, in HTML, the PDF story and Excel;
  * PDF KPI card subtext (matches the HTML card);
  * Excel KPI note, plus a separate Trajectory Duration row.

The integration cases use the shipped corrected 07_hsr_140km example in both running directions.
"""
from html import escape
from types import SimpleNamespace

import openpyxl
import pytest
from reportlab.platypus import Paragraph, Table

from headway.infrastructure.direction import RunningDirection
from headway.reporting import pdf_renderer
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_models import ReportSectionId
from headway.ui.simulation_runner import SimulationRunner
from tests.corrected_variants import load_corrected_variant

DIRECTIONS = (RunningDirection.FORWARD, RunningDirection.REVERSE)
FRAME = "Times are absolute simulation time from the start of the run."
KPI_SENTENCE = "The Total Service Duration KPI measures from origin departure"
CLEARING = "past the final station arrival to reach the physical end of track"
_CACHE = {}


def _run(direction):
    if direction not in _CACHE:
        project = load_corrected_variant("07_hsr_140km")[0]
        _CACHE[direction] = SimulationRunner.run_simulation_pipeline(project, running_direction=direction)
    return _CACHE[direction]


def _footnote(doc):
    return doc.sections[ReportSectionId.STATION_STOPPING_TABLE].tables[0].metadata["footnote"]


# ---------------------------------------------------------------- footnote builder (stub packages)
def _stop(arr, dep):
    return SimpleNamespace(arrival_time_s=arr, departure_time_s=dep)


def _pkg(stops, t_end, t_start=0.0, direction=RunningDirection.FORWARD):
    samples = [SimpleNamespace(time_s=t_start), SimpleNamespace(time_s=t_end)]
    return SimpleNamespace(
        metadata={"station_stops": stops, "running_direction": direction},
        trajectories={"TRN_LEADER": SimpleNamespace(samples=samples)},
    )


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_footnote_states_origin_departure_and_terminal_clearing(direction):
    fn = ReportAssembler._station_stopping_footnote(_pkg([_stop(53.0, 53.0), _stop(1172.0, 1172.0)], 1260.0, direction=direction))
    assert fn == (
        f"{FRAME} {KPI_SENTENCE} (the origin station's departure time, which is 53 s in this run) to terminus "
        "arrival. The trajectory continues 88 seconds past the final station arrival to reach the physical end "
        "of track. This terminal clearing movement is not included in the Total Service Duration KPI."
    )


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_footnote_formats_fractional_seconds(direction):
    fn = ReportAssembler._station_stopping_footnote(_pkg([_stop(10.0, 12.4), _stop(500.0, 560.0)], 513.25, direction=direction))
    assert "which is 12.4 s in this run" in fn
    assert "continues 13.2 seconds past" in fn


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_footnote_omits_clearing_sentence_when_trajectory_ends_at_terminus(direction):
    fn = ReportAssembler._station_stopping_footnote(_pkg([_stop(0.0, 30.0), _stop(900.0, 900.0)], 900.0, direction=direction))
    assert KPI_SENTENCE in fn and "which is 30 s in this run" in fn
    assert CLEARING not in fn


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("stops", [[], [_stop(5.0, 35.0)]])
def test_footnote_with_fewer_than_two_stops_is_frame_only(direction, stops):
    fn = ReportAssembler._station_stopping_footnote(_pkg(stops, 900.0, direction=direction))
    assert fn == FRAME


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_service_window_drives_kpi_unchanged(direction):
    pkg = _pkg([_stop(53.0, 53.0), _stop(234.0, 294.0), _stop(1172.0, 1172.0)], 1260.0, direction=direction)
    assert ReportAssembler._station_stop_service_window(pkg) == (53.0, 1172.0)
    assert ReportAssembler._compute_total_service_duration(pkg) == 1119.0
    assert ReportAssembler._compute_trajectory_duration(pkg) == 1260.0


# ---------------------------------------------------------------- corrected 07_hsr_140km, FWD + REV
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_kpi_is_terminus_arrival_minus_origin_departure(direction):
    pkg, doc = _run(direction)
    stops = pkg.metadata["station_stops"]
    assert len(stops) >= 2
    assert doc.executive_kpis.total_service_duration_s == pytest.approx(
        round(stops[-1].arrival_time_s - stops[0].departure_time_s, 1)
    )


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_section8_footnote_values_match_run(direction):
    pkg, doc = _run(direction)
    stops = pkg.metadata["station_stops"]
    samples = pkg.trajectories["TRN_LEADER"].samples
    fn = _footnote(doc)
    assert fn.startswith(FRAME + " " + KPI_SENTENCE)
    assert f"which is {ReportAssembler._fmt_s(stops[0].departure_time_s)} s in this run" in fn
    clearing = samples[-1].time_s - stops[-1].arrival_time_s
    assert clearing >= 0.0
    if clearing >= 0.5:
        assert f"The trajectory continues {ReportAssembler._fmt_s(clearing)} seconds {CLEARING}" in fn
    else:
        assert CLEARING not in fn


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_section8_footnote_in_html(direction, tmp_path):
    _, doc = _run(direction)
    html = HtmlReportRenderer.render(doc, output_path=tmp_path / "r.html", embed_interactive_plotly=False)
    assert escape(_footnote(doc)) in html


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_section8_footnote_in_pdf_story(direction, tmp_path, monkeypatch):
    _, doc = _run(direction)
    captured = []
    monkeypatch.setattr(pdf_renderer, "export_figure_headless", lambda *a, **k: None)
    monkeypatch.setattr(pdf_renderer.SimpleDocTemplate, "build", lambda self, story, **k: captured.extend(story))
    PdfReportRenderer.render(doc, output_path=tmp_path / "r.pdf")
    texts = [f.getPlainText() for f in captured if isinstance(f, Paragraph)]
    assert _footnote(doc) in texts


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_pdf_kpi_card_subtext_matches_html(direction, tmp_path):
    _, doc = _run(direction)
    flow = PdfReportRenderer._build_executive_dashboard(doc, PdfReportRenderer._build_styles())
    cards = next(f for f in flow if isinstance(f, Table))._cellvalues[0]
    card = next(c for c in cards if c[0].getPlainText() == "TOTAL SERVICE DURATION")
    assert card[1].getPlainText() == doc.executive_kpis.total_service_duration_str
    assert card[2].getPlainText() == "Origin departure to terminus arrival"
    html = HtmlReportRenderer.render(doc, output_path=tmp_path / "r.html", embed_interactive_plotly=False)
    assert "Origin departure to terminus arrival" in html
    assert "End-to-End Line Traversal" not in html


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_excel_labels_and_trajectory_row(direction, tmp_path):
    pkg, doc = _run(direction)
    k = doc.executive_kpis
    ExcelReportExporter.export(doc, output_path=tmp_path / "r.xlsx")
    wb = openpyxl.load_workbook(tmp_path / "r.xlsx")
    rows = [r for r in wb["Executive_Summary"].iter_rows(values_only=True) if r and r[0]]
    labels = [r[0] for r in rows]

    tsd = rows[labels.index("Total Service Duration (End-to-End)")]
    assert tsd[1] == k.total_service_duration_str
    assert tsd[3] == f"{k.total_service_duration_s:.1f}s service duration (origin departure to terminus arrival)"
    assert "journey time" not in tsd[3]

    samples = pkg.trajectories["TRN_LEADER"].samples
    expected = round(samples[-1].time_s - samples[0].time_s, 1)
    assert k.trajectory_duration_s == pytest.approx(expected)
    traj = rows[labels.index("Trajectory Duration")]
    assert traj[1] == k.trajectory_duration_str
    assert traj[2] == "HH:MM:SS"
    assert traj[3] == f"{expected:.1f}s trajectory duration (start of run to end of track)"
    # Directly below the KPI it is compared with (four-row block, see test_total_track_length_kpi_v1130).
    i = labels.index("Total Service Duration (End-to-End)")
    assert labels[i:i + 4] == [
        "Total Service Duration (End-to-End)",
        "Trajectory Duration",
        "Total Track Length",
        "Controlling Bottleneck Resource",
    ]

    cells = [c for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row if isinstance(c, str)]
    assert _footnote(doc) in cells
