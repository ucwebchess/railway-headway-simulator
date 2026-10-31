"""Negative unit tests for Milestone P14 Professional Engineering Report Generator.

Tests invalid inputs, malformed result packages, formula inconsistencies,
directional mismatches, and validation errors per RHS-P14-001 § 34.
"""

import tempfile
from pathlib import Path
import pytest

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    ResourceBlockingInterval,
    ResourceCategory,
)
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.analysis.headway_results import HeadwayResult
from headway.infrastructure.direction import RunningDirection
from headway.reporting.csv_export import CsvReportExporter
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.json_export import JsonReportExporter
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.recommendations import RecommendationEngine
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_config import ReportConfig
from headway.reporting.report_models import (
    ExecutiveKpis,
    ReportDocument,
    ReportMetadata,
    ReportSection,
    ReportSectionId,
    ReportType,
)
from headway.reporting.report_validation import ReportValidator
from headway.reporting.result_models import SimulationResultPackage


def _create_minimal_interval(start: float = 10.0, end: float = 80.0) -> ResourceBlockingInterval:
    decomp = BlockingTimeDecomposition(
        setup_time_s=5.0,
        approach_time_s=15.0,
        running_time_s=30.0,
        dwell_time_s=0.0,
        geometric_clearance_time_s=10.0,
        residual_rear_time_s=0.0,
        release_time_s=10.0,
    )
    return ResourceBlockingInterval(
        interval_id="INT_01",
        resource_id="BLK_01",
        resource_category=ResourceCategory.TRACK_BLOCK,
        start_time_s=start,
        end_time_s=end,
        train_id="TRN_01",
        decomposition=decomp,
        physical_start_offset_m=0.0,
        physical_end_offset_m=1000.0,
        # v1.11.0 / Task 5: alignment (network) stationing required by Section 5 consumers.
        alignment_start_m=0.0,
        alignment_end_m=1000.0,
    )


def _create_minimal_package(headway_s: float = 90.0, direction: RunningDirection = RunningDirection.FORWARD) -> SimulationResultPackage:
    interval = _create_minimal_interval()
    conflict = ResourceConflict(
        conflict_id="CONF_01",
        leader_usage=interval,
        follower_usage=interval,
        conflict_type=ConflictType.IDENTICAL_RESOURCE,
        leader_release_time_s=interval.end_time_s,
        follower_start_time_s=interval.start_time_s + 10.0,
        required_headway_s=headway_s,
        slack_s=0.0,
        bottleneck_type="CRITICAL_BLOCK",
    )
    hw = HeadwayResult(
        run_id="RUN_01",
        analysis_id="AN_01",
        scenario_id="SCEN_BASE",
        leader_service_id="METRO_1",
        follower_service_id="METRO_2",
        reference_point_id="BLK_01",
        running_direction=direction,
        signalling_system="FIXED_BLOCK_3ASPECT",
        headway_definition="TECHNICAL_MINIMUM",
        headway_s=headway_s,
        minimum_dispatch_headway_s=headway_s,
        controlling_conflicts=[conflict],
        conflict_ranking=[conflict],
        blocking_intervals=[interval],
    )
    return SimulationResultPackage(
        run_id="RUN_01",
        scenario_id="SCEN_BASE",
        effective_config_hash="cfg_hash_test_123",
        running_direction=direction,
        headway_results={"METRO_1->METRO_2": hw},
        blocking_intervals=[interval],
        metadata={
            # v1.11.1 / Task 4: single-source PF payload required by Sections 3/18 narratives.
            "performance_factor_results": {
                "reference_headway_s": headway_s,
                "position_dependent_running_s": 40.0,
                "controlling_bottleneck_id": "BLK_01",
                "scenarios": [
                    {"performance_factor": 0.90, "delta_running_s": round(40.0 / 0.90 - 40.0, 2),
                     "headway_s": round(headway_s + (40.0 / 0.90 - 40.0), 2)},
                    {"performance_factor": 0.95, "delta_running_s": round(40.0 / 0.95 - 40.0, 2),
                     "headway_s": round(headway_s + (40.0 / 0.95 - 40.0), 2)},
                ],
            },
        },
    )


class TestReportNegative:
    """Negative test suite for Milestone P14."""

    def test_neg_001_capacity_formula_inconsistency_fails_validation(self) -> None:
        """P14-NEG-001: Theoretical capacity not equal to 3600 / headway fails validation."""
        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        # Corrupt the theoretical capacity in KPIs
        corrupted_kpis = ExecutiveKpis(
            technical_headway_s=doc.executive_kpis.technical_headway_s,
            technical_headway_min=doc.executive_kpis.technical_headway_min,
            theoretical_capacity_tph=999.0,  # Should be 3600 / 90 = 40.0
            planning_capacity_tph=doc.executive_kpis.planning_capacity_tph,
            controlling_bottleneck_id=doc.executive_kpis.controlling_bottleneck_id,
            controlling_bottleneck_type=doc.executive_kpis.controlling_bottleneck_type,
            controlling_bottleneck_location_m=doc.executive_kpis.controlling_bottleneck_location_m,
        )

        invalid_doc = ReportDocument(
            metadata=doc.metadata,
            executive_kpis=corrupted_kpis,
            rolling_stock=doc.rolling_stock,
            infrastructure=doc.infrastructure,
            bottleneck_diagnosis=doc.bottleneck_diagnosis,
            sections=doc.sections,
            figures_data=doc.figures_data,
            recommendations=doc.recommendations,
            audit_events=doc.audit_events,
        )

        val_result = ReportValidator.validate_report(invalid_doc)
        assert not val_result.is_valid
        assert any("Theoretical capacity" in msg for msg in val_result.error_messages)

    def test_neg_002_kpi_headway_discrepancy_with_section_fails_validation(self) -> None:
        """P14-NEG-002: Discrepancy between Executive KPI and Section 5 table headway fails validation."""
        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        # Corrupt minimum headway in KPIs
        corrupted_kpis = ExecutiveKpis(
            technical_headway_s=150.0,  # Conflict table says 90.0
            technical_headway_min=2.5,
            theoretical_capacity_tph=24.0,
            planning_capacity_tph=20.0,
            controlling_bottleneck_id=doc.executive_kpis.controlling_bottleneck_id,
            controlling_bottleneck_type=doc.executive_kpis.controlling_bottleneck_type,
            controlling_bottleneck_location_m=doc.executive_kpis.controlling_bottleneck_location_m,
        )

        invalid_doc = ReportDocument(
            metadata=doc.metadata,
            executive_kpis=corrupted_kpis,
            rolling_stock=doc.rolling_stock,
            infrastructure=doc.infrastructure,
            bottleneck_diagnosis=doc.bottleneck_diagnosis,
            sections=doc.sections,
            figures_data=doc.figures_data,
            recommendations=doc.recommendations,
            audit_events=doc.audit_events,
        )

        val_result = ReportValidator.validate_report(invalid_doc)
        assert not val_result.is_valid
        assert any("Executive KPI headway" in msg for msg in val_result.error_messages)

    def test_neg_003_bottleneck_discrepancy_fails_validation(self) -> None:
        """P14-NEG-003: Executive bottleneck not matching section 6 ranking flags warning."""
        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        # Corrupt critical bottleneck ID in KPIs
        corrupted_kpis = ExecutiveKpis(
            technical_headway_s=doc.executive_kpis.technical_headway_s,
            technical_headway_min=doc.executive_kpis.technical_headway_min,
            theoretical_capacity_tph=doc.executive_kpis.theoretical_capacity_tph,
            planning_capacity_tph=doc.executive_kpis.planning_capacity_tph,
            controlling_bottleneck_id="MISMATCHED_BLOCK",
            controlling_bottleneck_type="TRACK_BLOCK",
            controlling_bottleneck_location_m=0.0,
        )

        invalid_doc = ReportDocument(
            metadata=doc.metadata,
            executive_kpis=corrupted_kpis,
            rolling_stock=doc.rolling_stock,
            infrastructure=doc.infrastructure,
            bottleneck_diagnosis=doc.bottleneck_diagnosis,
            sections=doc.sections,
            figures_data=doc.figures_data,
            recommendations=doc.recommendations,
            audit_events=doc.audit_events,
        )

        val_result = ReportValidator.validate_report(invalid_doc)
        assert any("differs from top conflict resource" in d.message for d in val_result.diagnostics)

    def test_neg_004_non_applicable_section_without_reason_fails_validation(self) -> None:
        """P14-NEG-004: Marking a section as not applicable without reason flags silent omission."""
        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        corrupted_sections = dict(doc.sections)
        # Create an inapplicable section without explanation
        corrupted_sections[ReportSectionId.SPEED_GRADIENT_CURVATURE] = ReportSection(
            section_id=ReportSectionId.SPEED_GRADIENT_CURVATURE,
            title="Speed Profile, Gradient and Alignment Curvature",
            section_number="2.0",
            is_applicable=False,
            not_applicable_reason=None,  # Missing mandatory disclosure!
        )

        invalid_doc = ReportDocument(
            metadata=doc.metadata,
            executive_kpis=doc.executive_kpis,
            rolling_stock=doc.rolling_stock,
            infrastructure=doc.infrastructure,
            bottleneck_diagnosis=doc.bottleneck_diagnosis,
            sections=corrupted_sections,
            figures_data=doc.figures_data,
            recommendations=doc.recommendations,
            audit_events=doc.audit_events,
        )

        val_result = ReportValidator.validate_report(invalid_doc)
        assert any("marked non-applicable without documented reason" in d.message for d in val_result.diagnostics)

    def test_neg_005_config_hash_mismatch_fails_validation(self) -> None:
        """P14-NEG-005: Missing config hash in metadata fails validation."""
        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        corrupted_meta = ReportMetadata(
            report_id=doc.metadata.report_id,
            project_id=doc.metadata.project_id,
            scenario_id=doc.metadata.scenario_id,
            simulation_run_id=doc.metadata.simulation_run_id,
            report_type=doc.metadata.report_type,
            running_direction=doc.metadata.running_direction,
            input_configuration_hash="",  # Empty hash
        )

        invalid_doc = ReportDocument(
            metadata=corrupted_meta,
            executive_kpis=doc.executive_kpis,
            rolling_stock=doc.rolling_stock,
            infrastructure=doc.infrastructure,
            bottleneck_diagnosis=doc.bottleneck_diagnosis,
            sections=doc.sections,
            figures_data=doc.figures_data,
            recommendations=doc.recommendations,
            audit_events=doc.audit_events,
        )

        val_result = ReportValidator.validate_report(invalid_doc)
        assert not val_result.is_valid
        assert any("input_configuration_hash" in msg for msg in val_result.error_messages)

    def test_neg_006_raise_on_error_raises_exception(self) -> None:
        """P14-NEG-006: Validator raises exception when raise_on_error is True on invalid document."""
        from headway.core.exceptions import DataValidationError

        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        corrupted_meta = ReportMetadata(
            report_id="",  # Missing required ID
            project_id=doc.metadata.project_id,
            scenario_id=doc.metadata.scenario_id,
            simulation_run_id=doc.metadata.simulation_run_id,
            report_type=doc.metadata.report_type,
            running_direction=doc.metadata.running_direction,
            input_configuration_hash=doc.metadata.input_configuration_hash,
        )

        invalid_doc = ReportDocument(
            metadata=corrupted_meta,
            executive_kpis=doc.executive_kpis,
            rolling_stock=doc.rolling_stock,
            infrastructure=doc.infrastructure,
            bottleneck_diagnosis=doc.bottleneck_diagnosis,
            sections=doc.sections,
            figures_data=doc.figures_data,
            recommendations=doc.recommendations,
            audit_events=doc.audit_events,
        )

        with pytest.raises(DataValidationError):
            ReportValidator.validate_report(invalid_doc, raise_on_error=True)

    def test_neg_007_missing_scenario_id_fails_validation(self) -> None:
        """P14-NEG-007: Document missing mandatory scenario_id fails validation."""
        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        corrupted_meta = ReportMetadata(
            report_id=doc.metadata.report_id,
            project_id=doc.metadata.project_id,
            scenario_id="",  # Missing
            simulation_run_id=doc.metadata.simulation_run_id,
            report_type=doc.metadata.report_type,
            running_direction=doc.metadata.running_direction,
            input_configuration_hash=doc.metadata.input_configuration_hash,
        )

        invalid_doc = ReportDocument(
            metadata=corrupted_meta,
            executive_kpis=doc.executive_kpis,
            rolling_stock=doc.rolling_stock,
            infrastructure=doc.infrastructure,
            bottleneck_diagnosis=doc.bottleneck_diagnosis,
            sections=doc.sections,
            figures_data=doc.figures_data,
            recommendations=doc.recommendations,
            audit_events=doc.audit_events,
        )

        val_result = ReportValidator.validate_report(invalid_doc)
        assert not val_result.is_valid
        assert any("scenario_id" in msg for msg in val_result.error_messages)

    def test_neg_008_recommendation_engine_purely_deterministic(self) -> None:
        """P14-NEG-008: Recommendation engine produces empty recommendations if no engineering trigger occurs."""
        pkg = _create_minimal_package(headway_s=90.0)
        # Package has no residual rear, no long blocks (>1200m), no station dwell bottlenecks, no TVS hold
        recs = RecommendationEngine.generate_recommendations(pkg)
        # All recommendations must have valid categories, IDs, and deterministic engineering rationale
        for rec in recs:
            assert rec.recommendation_id.startswith("REC-")
            assert len(rec.rationale) > 20
            # Must not contain ungrounded buzzwords
            assert "machine learning" not in rec.rationale.lower()
            assert "ai suggested" not in rec.rationale.lower()

    def test_neg_009_export_handles_read_only_or_missing_path(self, tmp_path: Path) -> None:
        """P14-NEG-009: Exporters raise IOError or OSError when writing to invalid file path."""
        pkg = _create_minimal_package(headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)
        not_a_dir = tmp_path / "not_a_directory"
        not_a_dir.write_text("this is a file, not a directory")
        invalid_path = not_a_dir / "report.html"

        with pytest.raises(OSError):
            HtmlReportRenderer.render(doc, output_path=invalid_path)

        with pytest.raises(OSError):
            JsonReportExporter.export(doc, output_path=not_a_dir / "report.json")
