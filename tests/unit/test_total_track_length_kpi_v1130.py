"""v1.13.0 — Total Track Length (km) executive KPI.

The KPI is the length of the SIMULATED ROUTE (the active service pattern's
ROUTE_LINK_SEQUENCE, i.e. ``metadata["route_length_m"]``). When the route is a subset of
the network, the whole-network track length is disclosed in the KPI subtext.

Placement (all renderers): ... Total Service Duration (End-to-End) -> Total Track Length ->
Controlling Bottleneck.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import openpyxl
import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_models import ExecutiveKpis
from headway.ui.simulation_runner import SimulationRunner
from tests import route_scope_project as rsp


def _kpis(**kw) -> ExecutiveKpis:
    base = {
        "technical_headway_s": 90.0,
        "technical_headway_min": 1.5,
        "theoretical_capacity_tph": 40.0,
        "planning_capacity_tph": 33.0,
        "controlling_bottleneck_id": "BLK_X",
        "controlling_bottleneck_type": "OPEN_LINE_BLOCK",
        "controlling_bottleneck_location_m": 1000.0,
    }
    base.update(kw)
    return ExecutiveKpis(**base)


# --------------------------------------------------------------------------- model
def test_model_formats_km_and_subtext():
    k = _kpis(total_track_length_m=36251.84, route_link_count=178, network_track_length_m=36251.84)
    assert k.total_track_length_km == pytest.approx(36.25184)
    assert k.total_track_length_str == "36.25 km"
    # Route == network: no network disclosure.
    assert k.total_track_length_subtext == "Simulated route • 178 links • 36,251.8 m"
    d = k.to_dict()
    assert d["total_track_length_m"] == 36251.84
    assert d["total_track_length_str"] == "36.25 km"
    assert d["route_link_count"] == 178


def test_model_discloses_network_when_route_is_subset():
    k = _kpis(total_track_length_m=9050.0, route_link_count=10, network_track_length_m=90500.0)
    assert k.total_track_length_str == "9.05 km"
    assert k.total_track_length_subtext.endswith("(network 90.50 km)")


def test_model_unavailable_is_na():
    k = _kpis()
    assert k.total_track_length_km is None
    assert k.total_track_length_str == "N/A"


# --------------------------------------------------------------------------- source
def test_source_prefers_route_length_metadata():
    pkg = SimpleNamespace(metadata={
        "route_length_m": 9050.0,
        "route_link_ids": [f"L{i}" for i in range(10)],
        "track_links": [SimpleNamespace(length_m=1.0)] * 3,  # ignored: route_length_m wins
        "network_track_length_m": 90500.0,
    })
    assert ReportAssembler._compute_total_track_length(pkg) == (9050.0, 10, 90500.0)


def test_source_falls_back_to_sum_of_route_links():
    pkg = SimpleNamespace(metadata={"track_links": [SimpleNamespace(length_m=v) for v in (100.0, 250.5, 49.5)]})
    assert ReportAssembler._compute_total_track_length(pkg) == (400.0, 3, None)


@pytest.mark.parametrize("meta", [{}, None, {"route_length_m": 0.0}, {"track_links": [SimpleNamespace(length_m=None)]}])
def test_source_unavailable_returns_none(meta):
    assert ReportAssembler._compute_total_track_length(SimpleNamespace(metadata=meta)) == (None, None, None)


# --------------------------------------------------------------------------- pipeline + renderers
@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return rsp.load_route_scope_project(tmp_path_factory.mktemp("trk") / "p")


def _between(seq, a, b, c):
    ia, ib, ic = seq.index(a), seq.index(b), seq.index(c)
    return ia < ib < ic and ib == ia + 1 and ic == ib + 1


def _consecutive(seq, *items):
    """True when all items are present and appear back-to-back in the given order."""
    start = seq.index(items[0])
    return list(seq[start:start + len(items)]) == list(items)


@pytest.mark.parametrize("direction", [RunningDirection.FORWARD, RunningDirection.REVERSE])
def test_kpi_value_and_placement_in_all_renderers(project, direction, tmp_path):
    pkg, doc = SimulationRunner.run_simulation_pipeline(project, running_direction=direction)
    k = doc.executive_kpis

    # Value = simulated route (10 links, 9,050 m), NOT the 100-link / 90.5 km network.
    assert pkg.metadata["route_length_m"] == pytest.approx(rsp.ROUTE_LENGTH_M)
    assert pkg.metadata["network_track_length_m"] == pytest.approx(rsp.NETWORK_LENGTH_M)
    assert k.total_track_length_m == pytest.approx(rsp.ROUTE_LENGTH_M)
    assert k.route_link_count == len(rsp.ROUTE)
    assert k.network_track_length_m == pytest.approx(rsp.NETWORK_LENGTH_M)
    assert k.total_track_length_str == "9.05 km"
    assert "(network 90.50 km)" in k.total_track_length_subtext

    # Section 1 KPI dict carries it right after Total Service Duration.
    sec_keys = next(list(s.kpis) for s in doc.sections.values() if "Total Track Length (km)" in (s.kpis or {}))
    assert sec_keys.index("Total Track Length (km)") == sec_keys.index("Total Service Duration (End-to-End)") + 2

    # HTML card order.
    html = HtmlReportRenderer.render(doc, output_path=tmp_path / "r.html", embed_interactive_plotly=False)
    labels = re.findall(r"<div class='kpi-label'>([^<]+)</div>", html)
    assert _between(labels, "Total Service Duration (End-to-End)", "Total Track Length", "Controlling Bottleneck")
    assert "9.05 <span class='kpi-unit'>km</span>" in html

    # Excel Executive_Summary row order and value.
    xp = tmp_path / "r.xlsx"
    ExcelReportExporter.export(doc, output_path=xp)
    rows = [r for r in openpyxl.load_workbook(xp)["Executive_Summary"].iter_rows(values_only=True) if r and r[0]]
    names = [str(r[0]) for r in rows]
    # v1.14.4: Trajectory Duration sits directly below the KPI it is compared with.
    assert _consecutive(
        names,
        "Total Service Duration (End-to-End)",
        "Trajectory Duration",
        "Total Track Length",
        "Controlling Bottleneck Resource",
    )
    trk = rows[names.index("Total Track Length")]
    assert trk[1] == pytest.approx(9.05) and trk[2] == "km"

    # PDF: the executive KPI table row (cards are [label, value, subtext] Paragraph cells),
    # and the full PDF still renders.
    from reportlab.platypus import Table

    flow = PdfReportRenderer._build_executive_dashboard(doc, PdfReportRenderer._build_styles())
    kpi_table = next(f for f in flow if isinstance(f, Table))
    cards = kpi_table._cellvalues[0]
    pdf_labels = [c[0].getPlainText() for c in cards]
    assert _between(pdf_labels, "TOTAL SERVICE DURATION", "TOTAL TRACK LENGTH", "CONTROLLING BOTTLENECK")
    trk_card = cards[pdf_labels.index("TOTAL TRACK LENGTH")]
    assert trk_card[1].getPlainText() == "9.05 km"
    assert pdf_labels[-1] == "CONTROLLING BOTTLENECK"  # critical (red) card stays last
    pp = tmp_path / "r.pdf"
    PdfReportRenderer.render(doc, output_path=pp)
    assert pp.stat().st_size > 0
