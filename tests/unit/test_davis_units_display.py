"""DEF-04 Regression tests: Complete physical units and variable declaration for Davis resistance."""

from pathlib import Path
import tempfile
import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_models import (
    ExecutiveKpis,
    InfrastructureSummary,
    ReportDocument,
    ReportMetadata,
    ReportType,
    RollingStockSummary,
)
from reportlab.platypus import Table


@pytest.fixture
def base_kpis():
    return ExecutiveKpis(
        technical_headway_s=60.0,
        technical_headway_min=1.0,
        theoretical_capacity_tph=60.0,
        planning_capacity_tph=45.0,
        controlling_bottleneck_id="BLK_01",
        controlling_bottleneck_type="BLOCK",
        controlling_bottleneck_location_m=0.0,
    )


@pytest.fixture
def base_metadata():
    return ReportMetadata(
        report_id="RPT_TEST_DAVIS",
        project_id="PRJ_TEST",
        scenario_id="BASELINE",
        simulation_run_id="RUN_TEST",
        report_type=ReportType.DETAILED_ENGINEERING,
        running_direction=RunningDirection.FORWARD,
    )


def test_html_executive_summary_has_davis_units_single_train(base_kpis, base_metadata, tmp_path):
    """DEF-04: HTML executive summary renders complete Davis units for single train."""
    rs = RollingStockSummary(
        model_name="High Speed Test Consist",
        train_length_m=200.0,
        tare_mass_t=400.0,
        gross_mass_t=450.0,
        max_speed_kmh=300.0,
        traction_power_kw=8000.0,
        service_braking_deceleration_ms2=0.9,
        emergency_braking_deceleration_ms2=1.2,
        davis_a_n=2506.0,
        davis_b_ns_per_m=146.34,
        davis_c_ns2_per_m2=5.5728,
        train_types=(),
    )
    doc = ReportDocument(
        metadata=base_metadata,
        executive_kpis=base_kpis,
        rolling_stock=rs,
        sections={},
    )
    html_out = tmp_path / "single_train_report.html"
    HtmlReportRenderer.render(doc, html_out)

    content = html_out.read_text(encoding="utf-8")

    # Assert complete physical unit tokens
    assert "Ns/m" in content or "N·s/m" in content
    assert "Ns²/m²" in content or "N·s²/m²" in content
    assert "(v in m/s)" in content or "[v in m/s]" in content

    # Assert actual coefficient digits
    assert "2506" in content
    assert "146.34" in content
    assert "5.57" in content


def test_html_executive_summary_has_davis_units_multi_train(base_kpis, base_metadata, tmp_path):
    """DEF-04: HTML executive summary renders complete Davis units for multi-train tables."""
    rs = RollingStockSummary(
        model_name="Multi-Consist Fleet",
        train_length_m=200.0,
        tare_mass_t=400.0,
        gross_mass_t=450.0,
        max_speed_kmh=300.0,
        traction_power_kw=8000.0,
        service_braking_deceleration_ms2=0.9,
        emergency_braking_deceleration_ms2=1.2,
        davis_a_n=2506.0,
        davis_b_ns_per_m=146.34,
        davis_c_ns2_per_m2=5.5728,
        train_types=(
            {
                "train_type_id": "TRN_HSR",
                "description": "High Speed Service",
                "train_length_m": 200.0,
                "tare_mass_t": 400.0,
                "gross_mass_t": 450.0,
                "max_speed_kmh": 300.0,
                "traction_power_kw": 8000.0,
                "max_tractive_effort_kn": 300.0,
                "service_braking_deceleration_ms2": 0.9,
                "emergency_braking_deceleration_ms2": 1.2,
                "davis_a_n": 2506.0,
                "davis_b_ns_per_m": 146.34,
                "davis_c_ns2_per_m2": 5.5728,
            },
            {
                "train_type_id": "TRN_REG",
                "description": "Regional Stopping Service",
                "train_length_m": 160.0,
                "tare_mass_t": 280.0,
                "gross_mass_t": 320.0,
                "max_speed_kmh": 160.0,
                "traction_power_kw": 4000.0,
                "max_tractive_effort_kn": 220.0,
                "service_braking_deceleration_ms2": 0.8,
                "emergency_braking_deceleration_ms2": 1.1,
                "davis_a_n": 1800.0,
                "davis_b_ns_per_m": 90.0,
                "davis_c_ns2_per_m2": 3.6,
            },
        ),
    )
    doc = ReportDocument(
        metadata=base_metadata,
        executive_kpis=base_kpis,
        rolling_stock=rs,
        sections={},
    )
    html_out = tmp_path / "multi_train_report.html"
    HtmlReportRenderer.render(doc, html_out)

    content = html_out.read_text(encoding="utf-8")

    # Assert complete physical unit tokens
    assert "Ns/m" in content or "N·s/m" in content
    assert "Ns²/m²" in content or "N·s²/m²" in content
    assert "(v in m/s)" in content or "[v in m/s]" in content

    # Assert actual coefficient digits for both trains
    assert "2506" in content
    assert "146.34" in content
    assert "5.57" in content
    assert "1800" in content
    assert "90.00" in content
    assert "3.60" in content


def test_pdf_executive_summary_has_davis_units(base_kpis, base_metadata, tmp_path):
    """DEF-04: PDF executive summary renders complete Davis units in KPI section."""
    rs = RollingStockSummary(
        model_name="High Speed Test Consist",
        train_length_m=200.0,
        tare_mass_t=400.0,
        gross_mass_t=450.0,
        max_speed_kmh=300.0,
        traction_power_kw=8000.0,
        service_braking_deceleration_ms2=0.9,
        emergency_braking_deceleration_ms2=1.2,
        davis_a_n=2506.0,
        davis_b_ns_per_m=146.34,
        davis_c_ns2_per_m2=5.5728,
        train_types=(),
    )
    infra = InfrastructureSummary(
        signalling_technology="ETCS_LEVEL_2",
        topology_mode="LINE",
        dataset_id="TEST_CORRIDOR",
        dataset_version="1.0",
        dataset_hash="hash_123",
        total_links=10,
        total_blocks=10,
        total_signals=10,
        total_stations=2,
        total_platforms=2,
        total_tvs_sections=0,
        aspect_model="FOUR_ASPECT",
        default_overlap_m=50.0,
        sighting_time_s=8.0,
        route_setup_time_s=3.0,
        resource_release_delay_s=4.0,
    )
    doc = ReportDocument(
        metadata=base_metadata,
        executive_kpis=base_kpis,
        rolling_stock=rs,
        infrastructure=infra,
        sections={},
    )

    # 1. Render actual PDF to ensure pipeline builds without errors
    pdf_out = tmp_path / "test_report.pdf"
    PdfReportRenderer.render(doc, pdf_out)
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 0

    # 2. Inspect constructed Paragraph objects directly via _build_kpi_section
    styles = PdfReportRenderer._build_styles()
    flowables = PdfReportRenderer._build_kpi_section(doc, styles)

    davis_cell_text = None
    for f in flowables:
        if isinstance(f, Table):
            for row in f._cellvalues:
                for cell in row:
                    if isinstance(cell, Table):
                        for sub_row in cell._cellvalues:
                            if len(sub_row) >= 2 and hasattr(sub_row[0], "text") and "Davis" in sub_row[0].text:
                                davis_cell_text = sub_row[1].text
                                break

    assert davis_cell_text is not None, "Davis resistance cell not found in PDF flowables"

    # Assert complete physical unit tokens
    assert "Ns/m" in davis_cell_text or "N·s/m" in davis_cell_text
    assert "Ns²/m²" in davis_cell_text or "N·s²/m²" in davis_cell_text
    assert "(v in m/s)" in davis_cell_text or "[v in m/s]" in davis_cell_text

    # Assert actual coefficient digits
    assert "2506" in davis_cell_text
    assert "146.34" in davis_cell_text
    assert "5.57" in davis_cell_text
