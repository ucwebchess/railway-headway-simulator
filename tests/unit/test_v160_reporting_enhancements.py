"""Unit tests for v1.6.0 reporting enhancements.

Covers:
- Task 1: UI Configuration & Simulation Mode Wiring
- Task 2: PDF Rendering & Layout Engine (A3 landscape)
- Task 3: Extended Dynamic Engineering Narratives
"""

from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List

import pytest

from headway.data.canonical import CanonicalProject
from headway.infrastructure.direction import RunningDirection
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_config import (
    PageOrientation,
    PaperSize,
    ReportConfig,
    TEMPLATE_FRIENDLY_NAMES,
    TEMPLATE_SECTIONS,
)
from headway.core.exceptions import ReportingError
from headway.reporting.report_models import ReportDocument, ReportSectionId, ReportType
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner
from tests.engineering.test_report_benchmarks import build_benchmark_package


@pytest.mark.unit
class TestV160ReportConfiguration:
    """Task 1 tests: UI Configuration, Templates, and Simulation Mode Wiring."""

    def test_report_config_template_friendly_names(self) -> None:
        """Verify friendly template names parse into correct ReportType enum."""
        cfg_std = ReportConfig(report_type="Standard")
        assert cfg_std.report_type == ReportType.DETAILED_ENGINEERING

        cfg_exec = ReportConfig(report_type="Executive Summary Only")
        assert cfg_exec.report_type == ReportType.EXECUTIVE_SUMMARY

        cfg_cap = ReportConfig(report_type="Capacity Focus")
        assert cfg_cap.report_type == ReportType.CAPACITY_ASSESSMENT

    def test_user_section_exclusions_marked_not_applicable(self) -> None:
        """Verify user unchecked sections are marked is_applicable=False with explicit reason."""
        pkg = build_benchmark_package()
        cfg = ReportConfig(
            included_sections=[
                ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
                ReportSectionId.ASSUMPTIONS_AUDIT,
            ]
        )
        doc = ReportAssembler.assemble_report(pkg, config=cfg)

        # Included section
        sec_concl = doc.get_section(ReportSectionId.CONCLUSIONS_RECOMMENDATIONS)
        assert sec_concl is not None
        assert sec_concl.is_applicable is True

        # Excluded section
        sec_stairway = doc.get_section(ReportSectionId.BLOCKING_STAIRWAY)
        assert sec_stairway is not None
        assert sec_stairway.is_applicable is False
        assert sec_stairway.not_applicable_reason == "Excluded by user configuration"
        assert len(sec_stairway.figure_keys) == 0

    def test_assessment_template_filtering(self) -> None:
        """Verify assessment template restricts report sections."""
        pkg = build_benchmark_package()
        cfg = ReportConfig(report_type="Executive Summary Only")
        doc = ReportAssembler.assemble_report(pkg, config=cfg)

        sec_concl = doc.get_section(ReportSectionId.CONCLUSIONS_RECOMMENDATIONS)
        assert sec_concl is not None
        assert sec_concl.is_applicable is True

        sec_speed = doc.get_section(ReportSectionId.SPEED_GRADIENT_CURVATURE)
        assert sec_speed is not None
        assert sec_speed.is_applicable is False
        assert "Excluded by template" in sec_speed.not_applicable_reason

    def test_stochastic_missing_data_loud_failure(self) -> None:
        """Verify loud failure when Stochastic assessment is explicitly requested without MC data."""
        pkg = build_benchmark_package()
        pkg.monte_carlo_result = None
        if pkg.metadata and "stochastic_summaries" in pkg.metadata:
            del pkg.metadata["stochastic_summaries"]

        cfg = ReportConfig(report_type=ReportType.STOCHASTIC_ASSESSMENT)
        with pytest.raises(ReportingError) as exc_info:
            ReportAssembler.assemble_report(pkg, config=cfg)
        assert "ERR_REPORT_MISSING_STOCHASTIC" in str(exc_info.value)

    def test_simulation_mode_wiring_to_effective_performance_factor(self) -> None:
        """Verify simulation mode tokens (100 vs 95) map to eff_pf."""
        project, report, _ = FileManager.load_example_project("05_comprehensive_line")
        assert report.is_simulation_ready

        # Mode with 95
        pkg_95, doc_95 = SimulationRunner.run_simulation_pipeline(
            project=project,
            simulation_mode="AN_HSR_HSR_UP_95 (Degraded Performance - Factor 0.95)",
        )
        assert abs(doc_95.executive_kpis.performance_factor - 0.95) < 1e-4

        # Mode with 100
        pkg_100, doc_100 = SimulationRunner.run_simulation_pipeline(
            project=project,
            simulation_mode="AN_HSR_HSR_UP_100 (Full Performance - Factor 1.00)",
        )
        assert abs(doc_100.executive_kpis.performance_factor - 1.0) < 1e-4


@pytest.mark.unit
class TestV160PdfLayoutEngine:
    """Task 2 tests: PDF Rendering & Layout Engine (A3 landscape)."""

    def test_pdf_mediabox_is_landscape_a3(self, tmp_path: Path) -> None:
        """Verify generated PDF has MediaBox dimensions corresponding to landscape A3."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        pdf_file = tmp_path / "a3_test_report.pdf"

        PdfReportRenderer.render(doc, output_path=pdf_file)
        assert pdf_file.exists()
        assert pdf_file.stat().st_size > 5000

        content = pdf_file.read_bytes()
        # ReportLab landscape(A3) MediaBox: [0 0 1190.551 841.8898]
        boxes = re.findall(rb'/MediaBox\s*\[\s*([0-9\.\s]+)\s*\]', content)
        assert len(boxes) > 0, "No /MediaBox found in generated PDF"
        for box_bytes in boxes:
            dims = [float(v) for v in box_bytes.decode("ascii").split()]
            assert len(dims) == 4
            # Width ~1190.55 pt, Height ~841.89 pt
            assert abs(dims[2] - 1190.55) < 1.0, f"Expected width ~1190.55 pt, got {dims[2]}"
            assert abs(dims[3] - 841.89) < 1.0, f"Expected height ~841.89 pt, got {dims[3]}"

    def test_pdf_renderer_layout_constants(self) -> None:
        """Verify PDF renderer layout constants match landscape A3 with 36 pt margins."""
        assert abs(PdfReportRenderer.PAGE_WIDTH - 1190.55) < 1.0
        assert abs(PdfReportRenderer.PAGE_HEIGHT - 841.89) < 1.0
        assert PdfReportRenderer.PAGE_MARGIN == 36.0
        assert abs(PdfReportRenderer.CONTENT_WIDTH - 1118.55) < 1.0


@pytest.mark.unit
class TestV160ExtendedDynamicNarratives:
    """Task 3 tests: Extended Dynamic Engineering Narratives across 7 sections."""

    def test_section_18_conclusions_and_recommendations_narrative(self) -> None:
        """Verify Section 18 generates rich narrative with 5-8 bulleted recommendations."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.CONCLUSIONS_RECOMMENDATIONS)
        assert sec is not None
        assert sec.is_applicable is True

        paras = sec.narrative_paragraphs
        assert len(paras) >= 4, "Expected executive synthesis and bulleted recommendations"

        bullets = [p for p in paras if p.startswith("•")]
        assert 5 <= len(bullets) <= 8, f"Expected 5 to 8 bulleted recommendations, got {len(bullets)}"

        combined = " ".join(paras)
        assert str(doc.executive_kpis.technical_headway_s) in combined or f"{doc.executive_kpis.technical_headway_s:.1f}" in combined
        assert doc.executive_kpis.controlling_bottleneck_id in combined

    def test_section_13_tvs_narrative(self) -> None:
        """Verify Section 13 generates dynamic narrative with geometry, range, and governing comparison."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.TVS_ASSESSMENT)
        assert sec is not None
        assert sec.is_applicable is True

        paras = sec.narrative_paragraphs
        assert len(paras) >= 3

        combined = " ".join(paras)
        assert "Tunnel Ventilation Section" in combined or "TVS" in combined
        assert "chainage" in combined.lower()
        assert "duration" in combined.lower()
        assert "governing" in combined.lower()

    def test_section_09_block_sensitivity_narrative(self) -> None:
        """Verify Section 9 generates dynamic sensitivity narrative."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.BLOCK_LENGTH_SENSITIVITY)
        assert sec is not None
        assert sec.is_applicable is True

        paras = sec.narrative_paragraphs
        assert len(paras) >= 2
        combined = " ".join(paras)
        assert "Block Length" in combined or "block length" in combined
        assert "baseline" in combined.lower()

    def test_section_07_mixed_traffic_narrative(self) -> None:
        """Verify Section 7 generates dynamic mixed traffic matrix narrative."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.MIXED_TRAFFIC_MATRIX)
        assert sec is not None
        assert sec.is_applicable is True

        paras = sec.narrative_paragraphs
        assert len(paras) >= 2
        combined = " ".join(paras)
        assert "mixed-traffic" in combined.lower()
        assert "service" in combined.lower()

    def test_section_06_platform_occupation_narrative(self) -> None:
        """Verify Section 6 generates dynamic platform occupation narrative with top platforms."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.STATION_PLATFORM_OCCUPATION)
        assert sec is not None
        assert sec.is_applicable is True

        paras = sec.narrative_paragraphs
        assert len(paras) >= 2
        combined = " ".join(paras)
        assert "platform" in combined.lower()
        assert "dwell" in combined.lower()

    def test_section_05_longest_occupations_narrative(self) -> None:
        """Verify Section 5 generates dynamic narrative explaining top 3 longest-occupied resources."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.LONGEST_OCCUPATIONS)
        assert sec is not None
        assert sec.is_applicable is True

        paras = sec.narrative_paragraphs
        assert len(paras) >= 2
        combined = " ".join(paras)
        assert "standalone" in combined.lower()
        assert "occupied" in combined.lower()

    def test_section_15_stochastic_reliability_narrative(self) -> None:
        """Verify Section 15 generates dynamic narrative with MC stats and percentiles."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.STOCHASTIC_RELIABILITY)
        assert sec is not None
        assert sec.is_applicable is True

        paras = sec.narrative_paragraphs
        assert len(paras) >= 2
        combined = " ".join(paras)
        assert "Monte Carlo" in combined
        assert "P95" in combined
        assert "standard deviation" in combined.lower()

    def test_explicit_performance_factor_overrides_dropdown_and_analysis(self) -> None:
        """Verify that passing explicit performance_factor overrides dropdown and analysis configuration (DEF-11)."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner
        from headway.infrastructure.direction import RunningDirection

        project, _, _ = FileManager.load_example_project("07_hsr_140km")

        # Pass dropdown selection with nominal 1.00 label, but override with explicit slider value 0.85
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=project,
            running_direction=RunningDirection.FORWARD,
            simulation_mode="AN_HSR_HSR_UP (PF: 1.00)",
            performance_factor=0.85,
        )

        assert doc.executive_kpis.performance_factor == 0.85
        assert doc.executive_kpis.performance_factor_str == "85%"
        assert pkg.metadata.get("performance_factor") == 0.85

    def test_section_18_fixed_vs_variable_blocking_breakdown(self) -> None:
        """Verify Section 18 properly calculates and displays the fixed vs variable percentage breakdown (DEF-11 / Task C)."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner
        from headway.infrastructure.direction import RunningDirection

        project, _, _ = FileManager.load_example_project("07_hsr_140km")
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=project,
            running_direction=RunningDirection.FORWARD,
            performance_factor=1.00,
        )

        sec18 = doc.get_section(ReportSectionId.CONCLUSIONS_RECOMMENDATIONS)
        assert sec18 is not None
        assert sec18.is_applicable is True

        combined_text = " ".join(sec18.narrative_paragraphs)
        assert "controlling bottleneck BLK_UP_092" in combined_text
        # v1.11.0 / Task 8: mandated category mapping — Fixed Overhead excludes dwell;
        # variable share = geometric clearance + passenger dwell + residual rear.
        assert "total blocking time of 251.0 s" in combined_text
        assert "Fixed Overhead (signalling setup + approach + release) = 17.0 s (6.8%)" in combined_text
        assert "Position-Dependent Running Time (performance-factor sensitive) = 110.0 s (43.8%)" in combined_text
        assert "Geometric Clearance (clearing + residual rear, vehicle-length dependent) + Passenger Dwell = 124.0 s (49.4%)" in combined_text
        assert "derating the performance factor to 0.95" in combined_text
        assert "extends the position-dependent running time by 5.5 s" in combined_text
        assert "increases the technical headway by 2.2% to 256.5 s" in combined_text
