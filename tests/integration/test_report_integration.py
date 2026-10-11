"""Integration tests for Milestone P14 Professional Engineering Report Generator.

Tests end-to-end assembly, cross-format rendering, ZIP package generation,
and directional integrity using full simulation packages per RHS-P14-001 § 35.
"""

from io import BytesIO
from pathlib import Path
import tempfile
import zipfile
import json
import openpyxl
import pandas as pd
import pytest

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    ResourceBlockingInterval,
    ResourceCategory,
)
from headway.analysis.capacity_models import (
    SensitivityPointResult,
    SensitivityStudyResult,
)
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.analysis.headway_results import HeadwayResult, MixedTrafficHeadwayMatrix
from headway.analysis.monte_carlo import MonteCarloExecutionResult
from headway.analysis.statistics import StatisticalSummary
from headway.data.canonical import Platform, Station, TrackLink, TVSSection
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
    RecommendationCategory,
    ReportDocument,
    ReportSectionId,
    ReportType,
)
from headway.reporting.report_package import ReportPackageExporter
from headway.reporting.report_validation import ReportValidator
from headway.reporting.result_models import (
    PlatformOccupationRecord,
    ResourceProvenanceRecord,
    SimulationResultPackage,
)
from headway.scenarios.scenario_comparison import (
    BottleneckShiftReport,
    MetricDifference,
    ScenarioComparisonReport,
)
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory


def _create_synthetic_full_package(
    direction: RunningDirection = RunningDirection.FORWARD,
    headway_s: float = 90.0,
) -> SimulationResultPackage:
    """Builds a rich, fully populated SimulationResultPackage for integration tests."""
    samples = []
    for i in range(30):
        t = float(i * 2)
        d = t * 15.0 if direction == RunningDirection.FORWARD else 2000.0 - t * 15.0
        v = 15.0 if i > 0 else 0.0
        samples.append(
            TrajectorySample(
                time_s=t,
                front_distance_m=d,
                rear_distance_m=max(0.0, d - 120.0),
                speed_ms=v,
                acceleration_ms2=0.0,
                traction_force_n=0.0,
                braking_force_n=0.0,
                davis_resistance_n=1500.0,
                gradient_resistance_n=0.0,
                curvature_resistance_n=0.0,
                net_force_n=0.0,
                dynamic_mode=DynamicMode.CRUISING if i > 0 else DynamicMode.COASTING,
                operational_state=OperationalState.STANDSTILL if i == 0 else OperationalState.RUNNING,
                link_id="TL_01",
                physical_coordinate_m=d,
            )
        )
    traj = TrainTrajectory(
        train_id="TRN_INTEG_01",
        train_type_id="TT_METRO",
        route_id="RT_01",
        running_direction=direction,
        samples=samples,
    )

    intervals = []
    for idx in range(1, 6):
        start = (idx - 1) * 30.0
        end = start + 55.0
        decomp = BlockingTimeDecomposition(
            setup_time_s=3.0,
            approach_time_s=10.0,
            running_time_s=30.0,
            dwell_time_s=0.0,
            geometric_clearance_time_s=8.0,
            residual_rear_time_s=0.0,
            release_time_s=4.0,
        )
        intervals.append(
            ResourceBlockingInterval(
                interval_id=f"INT_{idx:02d}",
                resource_id=f"BLK_{idx:02d}",
                resource_category=ResourceCategory.TRACK_BLOCK,
                start_time_s=start,
                end_time_s=end,
                train_id="TRN_INTEG_01",
                decomposition=decomp,
            )
        )

    conflict = ResourceConflict(
        conflict_id="CONF_INTEG_01",
        leader_usage=intervals[2],
        follower_usage=intervals[2],
        conflict_type=ConflictType.IDENTICAL_RESOURCE,
        leader_release_time_s=intervals[2].end_time_s,
        follower_start_time_s=intervals[2].start_time_s + 10.0,
        required_headway_s=headway_s,
        slack_s=0.0,
        bottleneck_type="CRITICAL_BLOCK",
    )

    hw = HeadwayResult(
        run_id="RUN_INTEG_01",
        analysis_id="AN_INTEG_01",
        scenario_id="SCEN_INTEG_BASE",
        leader_service_id="METRO_1",
        follower_service_id="METRO_2",
        reference_point_id="BLK_03",
        running_direction=direction,
        signalling_system="FIXED_BLOCK_3ASPECT",
        headway_definition="TECHNICAL_MINIMUM",
        headway_s=headway_s,
        minimum_dispatch_headway_s=headway_s,
        controlling_conflicts=[conflict],
        conflict_ranking=[conflict],
        blocking_intervals=intervals,
    )

    mt_matrix = MixedTrafficHeadwayMatrix(
        matrix_id="MT_INTEG",
        running_direction=direction,
        service_ids=["METRO_1", "METRO_2"],
        headway_values_s={
            ("METRO_1", "METRO_1"): headway_s,
            ("METRO_1", "METRO_2"): headway_s + 6.0,
            ("METRO_2", "METRO_1"): headway_s + 4.0,
            ("METRO_2", "METRO_2"): headway_s,
        },
        controlling_bottlenecks={
            ("METRO_1", "METRO_1"): "BLK_03",
            ("METRO_1", "METRO_2"): "BLK_03",
            ("METRO_2", "METRO_1"): "BLK_04",
            ("METRO_2", "METRO_2"): "BLK_03",
        },
    )

    study = SensitivityStudyResult(
        study_id="SENS_INTEG",
        parameter_name="block_length_m",
        baseline_value=600.0,
        baseline_capacity_tph=3600.0 / headway_s,
        baseline_headway_s=headway_s,
        baseline_bottleneck_id="BLK_03",
        points=[
            SensitivityPointResult(
                parameter_name="block_length_m",
                parameter_value=400.0,
                capacity_trains_per_hour=45.0,
                headway_s=80.0,
                limiting_bottleneck_id="BLK_02",
            ),
            SensitivityPointResult(
                parameter_name="block_length_m",
                parameter_value=600.0,
                capacity_trains_per_hour=3600.0 / headway_s,
                headway_s=headway_s,
                limiting_bottleneck_id="BLK_03",
            ),
        ],
    )

    stat = StatisticalSummary(
        metric_name="headway_s",
        sample_count=100,
        mean=headway_s + 1.8,
        median=headway_s + 1.2,
        std_dev=2.5,
        min_value=headway_s - 1.0,
        max_value=headway_s + 10.0,
        p5=headway_s,
        p50=headway_s + 1.2,
        p90=headway_s + 5.0,
        p95=headway_s + 6.5,
        p99=headway_s + 8.5,
    )

    mc = MonteCarloExecutionResult(
        analysis_id="MC_INTEG",
        scenario_id="SCEN_INTEG_BASE",
        total_replications=100,
        valid_replications=100,
        failed_replications=0,
        summaries={"headway_s": stat},
    )

    report_cmp = ScenarioComparisonReport(
        baseline_scenario_id="SCEN_INTEG_BASE",
        compared_scenario_ids=["SCEN_INTEG_CBTC"],
        metric_differences={
            "SCEN_INTEG_CBTC": [
                MetricDifference(
                    metric_name="headway_s",
                    baseline_value=headway_s,
                    scenario_value=headway_s - 20.0,
                    absolute_change=-20.0,
                    percentage_change=-22.2,
                )
            ]
        },
        bottleneck_shifts=[
            BottleneckShiftReport(
                baseline_scenario_id="SCEN_INTEG_BASE",
                comparison_scenario_id="SCEN_INTEG_CBTC",
                bottleneck_migrated=True,
                baseline_bottleneck_id="BLK_03",
                comparison_bottleneck_id="BLK_05",
            )
        ],
    )

    plt = PlatformOccupationRecord(
        train_id="TRN_INTEG_01",
        station_id="STN_AIRPORT",
        station_name="Airport Central",
        platform_id="PLT_01",
        track_id="TRK_01",
        link_id="TL_01",
        arrival_time_s=40.0,
        dwell_start_time_s=42.0,
        dwell_end_time_s=72.0,
        departure_time_s=75.0,
        clearance_time_s=90.0,
        running_direction=direction,
        is_residual_rear_active=True,
        residual_rear_duration_s=15.0,
        upstream_infringing_resource_ids=("BLK_02",),
    )

    tvs_ev = {
        "tvs_id": "TVS_INTEG_01",
        "train_id": "TRN_INTEG_01",
        "entry_time_s": 50.0,
        "exit_time_s": 95.0,
        "release_time_s": 105.0,
        "waiting_duration_s": 0.0,
    }

    prov = ResourceProvenanceRecord(
        resource_id="BLK_03",
        resource_type="TRACK_BLOCK",
        physical_chainage_km=0.9,
        resource_length_m=600.0,
        geometry_source="INTEG_MODEL",
        dataset_id="DS_INTEG_01",
        dataset_version="2.1.0",
        is_baseline_geometry=True,
    )

    return SimulationResultPackage(
        run_id="RUN_INTEG_01",
        scenario_id="SCEN_INTEG_BASE",
        effective_config_hash="cfg_hash_integ_9876543210",
        running_direction=direction,
        trajectories={"TRN_INTEG_01": traj},
        headway_results={"METRO_1->METRO_2": hw},
        mixed_traffic_matrix=mt_matrix,
        blocking_intervals=intervals,
        sensitivity_result=study,
        monte_carlo_result=mc,
        scenario_comparison_report=report_cmp,
        metadata={
            "platform_records": [plt],
            "provenance_records": [prov],
            "stochastic_headway_samples": [90.0 + k * 0.4 for k in range(30)],
            "tvs_events": [tvs_ev],
        },
    )


class TestReportIntegration:
    """End-to-end integration test suite for Milestone P14."""

    def test_e2e_full_reporting_pipeline_forward(self) -> None:
        """P14-INT-001: End-to-end reporting pipeline in FORWARD direction across all export formats."""
        pkg = _create_synthetic_full_package(direction=RunningDirection.FORWARD, headway_s=90.0)

        # 1. Assembly
        config = ReportConfig()
        doc = ReportAssembler.assemble_report(pkg, config=config)
        assert isinstance(doc, ReportDocument)
        assert doc.running_direction == RunningDirection.FORWARD
        assert doc.executive_kpis.technical_headway_s == 90.0
        assert doc.executive_kpis.theoretical_capacity_tph == 40.0
        assert doc.executive_kpis.controlling_bottleneck_id == "BLK_03"
        assert len(doc.sections) == 18

        # 2. Validation
        audit = ReportValidator.validate_report(doc, raise_on_error=True)
        assert audit.is_valid

        # 3. Recommendations
        assert len(doc.recommendations) > 0
        assert any(r.category == RecommendationCategory.STATION_PLATFORM_MODIFICATION for r in doc.recommendations)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # 4. HTML Generation
            html_path = tmp_path / "report.html"
            html_text = HtmlReportRenderer.render(doc, output_path=html_path)
            assert html_path.exists()
            assert "#1B365D" in html_text
            assert "Running Direction: FORWARD" in html_text
            assert "Airport Central" in html_text
            assert "90.0 s" in html_text

            # 5. PDF Generation
            pdf_path = tmp_path / "report.pdf"
            PdfReportRenderer.render(doc, output_path=pdf_path)
            assert pdf_path.exists()
            assert pdf_path.stat().st_size > 5000
            with open(pdf_path, "rb") as f:
                header = f.read(5)
                assert header == b"%PDF-"

            # 6. Excel Generation
            xlsx_path = tmp_path / "report.xlsx"
            ExcelReportExporter.export(doc, output_path=xlsx_path)
            assert xlsx_path.exists()
            wb = openpyxl.load_workbook(xlsx_path)
            assert any("EXECUTIVE" in s.upper() for s in wb.sheetnames)
            assert "RECOMMENDATIONS" in wb.sheetnames
            assert "CONFLICT_RANKING" in wb.sheetnames or "CONFLICT_RANKINGS" in wb.sheetnames
            assert "MIXED_TRAFFIC_MATRIX" in wb.sheetnames

            # 7. CSV Generation
            csv_dir = tmp_path / "csv_out"
            written_csvs = CsvReportExporter.export_all(doc, output_dir=csv_dir)
            assert len(written_csvs) >= 4
            for c_path in written_csvs:
                assert c_path.exists()
                df = pd.read_csv(c_path)
                assert len(df.columns) > 0

            # 8. JSON Generation
            json_path = tmp_path / "report.json"
            json_text = JsonReportExporter.export(doc, output_path=json_path)
            assert json_path.exists()
            data = json.loads(json_text)
            report_dict = data.get("report_data", data)
            assert report_dict["metadata"]["scenario_id"] == "SCEN_INTEG_BASE"
            assert report_dict["executive_kpis"]["technical_headway_s"] == 90.0
            assert len(report_dict["sections"]) == 18

            # 9. ZIP Package Export
            zip_path = tmp_path / "report_package.zip"
            created_zip = ReportPackageExporter.export_package(doc, output_zip_path=zip_path)
            assert created_zip.exists()
            assert zipfile.is_zipfile(created_zip)

            with zipfile.ZipFile(created_zip, "r") as zf:
                namelist = zf.namelist()
                assert "manifest.json" in namelist
                assert "report.html" in namelist
                assert "report.pdf" in namelist
                assert "report.xlsx" in namelist
                assert "report.json" in namelist
                assert any("csv/" in n for n in namelist)

                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                assert manifest["effective_config_hash"] == "cfg_hash_integ_9876543210"
                assert manifest["running_direction"] == "FORWARD"
                assert len(manifest["files"]) >= 5

    def test_e2e_reverse_direction_pipeline(self) -> None:
        """P14-INT-002: End-to-end pipeline in REVERSE direction strictly preserves directionality."""
        pkg = _create_synthetic_full_package(direction=RunningDirection.REVERSE, headway_s=95.0)

        doc = ReportAssembler.assemble_report(pkg)
        assert doc.running_direction == RunningDirection.REVERSE
        assert "REVERSE" in doc.direction_banner_text

        audit = ReportValidator.validate_report(doc)
        assert audit.is_valid

        html_out = HtmlReportRenderer.render(doc)
        assert "Running Direction: REVERSE" in html_out
        assert "Running Direction: FORWARD" not in html_out

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "package_reverse.zip"
            ReportPackageExporter.export_package(doc, output_zip_path=zip_path)
            with zipfile.ZipFile(zip_path, "r") as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                assert manifest["running_direction"] == "REVERSE"

    def test_e2e_scenario_comparison_integrity(self) -> None:
        """P14-INT-003: Scenario comparison section properly reconciles comparison deltas."""
        pkg = _create_synthetic_full_package(direction=RunningDirection.FORWARD, headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        cmp_sec = doc.get_section(ReportSectionId.SCENARIO_COMPARISON)
        assert cmp_sec is not None
        assert cmp_sec.is_applicable
        assert len(cmp_sec.tables) > 0
        cmp_tbl = cmp_sec.tables[0]
        assert "SCEN_INTEG_CBTC" in cmp_tbl.to_html()
        assert "-20.0" in cmp_tbl.to_html() or "-22.2" in cmp_tbl.to_html()
