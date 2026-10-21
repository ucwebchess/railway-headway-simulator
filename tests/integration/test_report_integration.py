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
from headway.core.exceptions import ReportingError
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
                physical_start_offset_m=idx * 600.0,
                physical_end_offset_m=(idx + 1) * 600.0,
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

    prov_records = [
        ResourceProvenanceRecord(
            resource_id=f"BLK_{idx:02d}",
            resource_type="TRACK_BLOCK",
            physical_chainage_km=round(idx * 0.6, 3),
            resource_length_m=600.0,
            geometry_source="INTEG_MODEL",
            dataset_id="DS_INTEG_01",
            dataset_version="2.1.0",
            is_baseline_geometry=True,
        )
        for idx in range(1, 6)
    ]

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
            "provenance_records": prov_records,
            "blocking_intervals": intervals,
            "controlling_bottleneck_id": "BLK_03",
            "stochastic_headway_samples": [90.0 + k * 0.4 for k in range(30)],
            "tvs_events": [tvs_ev],
            "scenarios": ["SCEN_INTEG_BASE", "SCEN_INTEG_CBTC"],
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

    def test_reporting_blocking_intervals_decomposition_and_geometry_synthetic(self) -> None:
        """Phase 4c: Assert reporting layer consumes package.metadata['blocking_intervals'] with non-zero values."""
        pkg = _create_synthetic_full_package(direction=RunningDirection.FORWARD, headway_s=90.0)
        doc = ReportAssembler.assemble_report(pkg)

        # 1. Section 4 / 3 (Chart): Check Seven-Component Breakdown chart (or Stairway equivalent)
        chart_sec = (
            doc.sections.get(ReportSectionId.SEVEN_COMPONENT_BREAKDOWN)
            or doc.sections.get(ReportSectionId.BLOCKING_STAIRWAY)
        )
        assert chart_sec is not None
        assert chart_sec.is_applicable

        fig_seven = doc.figures_data.get("fig_seven_components")
        assert fig_seven is not None
        traces_by_name = {t.name: t for t in fig_seven.data}

        assert "Setup (t1)" in traces_by_name
        assert "Approach (t2)" in traces_by_name
        assert "Release (t7)" in traces_by_name

        setup_vals = [float(y) for y in traces_by_name["Setup (t1)"].y]
        approach_vals = [float(y) for y in traces_by_name["Approach (t2)"].y]
        release_vals = [float(y) for y in traces_by_name["Release (t7)"].y]

        assert any(v > 0.0 for v in setup_vals), "Setup times in chart data must be non-zero"
        assert any(v > 0.0 for v in approach_vals), "Approach times in chart data must be non-zero"
        assert any(v > 0.0 for v in release_vals), "Release times in chart data must be non-zero"

        # Also verify stairway chart data exists and has intervals
        stair_sec = doc.sections.get(ReportSectionId.BLOCKING_STAIRWAY)
        assert stair_sec is not None
        assert stair_sec.is_applicable
        fig_stair = doc.figures_data.get("fig_blocking_stairway")
        assert fig_stair is not None
        assert len(fig_stair.data) >= 2

        # 2. Section 10 (Table): Detailed Resource Occupation Timing Breakdown Table
        table_sec = (
            doc.sections.get(getattr(ReportSectionId, "DETAILED_RESOURCE_OCCUPATION_TABLE", None))
            or doc.sections.get(ReportSectionId.DETAILED_RESOURCE_TIMING)
        )
        assert table_sec is not None
        assert table_sec.is_applicable
        assert len(table_sec.tables) > 0

        timing_table = table_sec.tables[0]
        raw_df = timing_table.raw_dataframe
        formatted_df = timing_table.formatted_dataframe

        # Ensure rows contain non-zero values for Setup, Approach, Release, Chainage, and Length
        assert (raw_df["Setup (s)"] > 0.0).any(), "Table Setup (s) must contain non-zero values"
        assert (raw_df["Approach (s)"] > 0.0).any(), "Table Approach (s) must contain non-zero values"
        assert (raw_df["Release (s)"] > 0.0).any(), "Table Release (s) must contain non-zero values"
        assert (raw_df["Chainage (km)"] > 0.0).any(), "Table Chainage (km) must contain non-zero values"
        assert (raw_df["Length (m)"] > 0.0).all(), "Table Length (m) must be non-zero for all rows"

        # In formatted dataframe as well
        assert any(float(v) > 0.0 for v in formatted_df["Setup (s)"])
        assert any(float(v) > 0.0 for v in formatted_df["Approach (s)"])
        assert any(float(v) > 0.0 for v in formatted_df["Release (s)"])
        assert any(float(v) > 0.0 for v in formatted_df["Chainage (km)"])
        assert all(float(v) > 0.0 for v in formatted_df["Length (m)"])

        # 3. Sum of 7 components in the table equals Total Blocking time
        comp_cols = [
            "Setup (s)",
            "Approach (s)",
            "Running (s)",
            "Dwell (s)",
            "Clearance (s)",
            "Residual Rear (s)",
            "Release (s)",
        ]
        sums = raw_df[comp_cols].sum(axis=1)
        diffs = (sums - raw_df["Total Blocking (s)"]).abs()
        assert (diffs < 1e-3).all(), f"Component sum mismatch found: max diff = {diffs.max()}"

    def test_reporting_blocking_intervals_hsr_corridor(self) -> None:
        """Phase 4c: Assert full 140 km HSR corridor report consumes metadata blocking intervals."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        # 1. Section 4 / 3 (Chart)
        sec_chart = doc.get_section(ReportSectionId.SEVEN_COMPONENT_BREAKDOWN)
        assert sec_chart is not None
        assert sec_chart.is_applicable
        fig_seven = doc.figures_data[sec_chart.figure_keys[0]]
        traces_by_name = {t.name: t for t in fig_seven.data}

        assert "Setup (t1)" in traces_by_name
        assert "Approach (t2)" in traces_by_name
        assert "Release (t7)" in traces_by_name

        setup_vals = [float(y) for y in traces_by_name["Setup (t1)"].y]
        approach_vals = [float(y) for y in traces_by_name["Approach (t2)"].y]
        release_vals = [float(y) for y in traces_by_name["Release (t7)"].y]

        assert any(v > 0.0 for v in setup_vals)
        assert any(v > 0.0 for v in approach_vals)
        assert any(v > 0.0 for v in release_vals)

        # 2. Section 10 (Table)
        sec_table = doc.get_section(ReportSectionId.DETAILED_RESOURCE_TIMING)
        assert sec_table is not None
        assert sec_table.is_applicable
        timing_table = sec_table.tables[0]
        raw_df = timing_table.raw_dataframe

        assert len(raw_df) == 92
        assert (raw_df["Length (m)"] > 0.0).all()
        assert (raw_df["Setup (s)"] > 0.0).all()
        assert (raw_df["Approach (s)"] > 0.0).any()
        assert (raw_df["Release (s)"] > 0.0).all()
        assert (raw_df["Chainage (km)"] > 0.0).any()

        # Controlling bottleneck BLK_UP_092
        controlling_rows = raw_df[raw_df["Resource ID"] == "BLK_UP_092"]
        assert len(controlling_rows) == 1
        assert bool(controlling_rows.iloc[0]["Controlling"]) is True
        formatted_df = timing_table.formatted_dataframe
        fmt_ctrl = formatted_df[formatted_df["Resource ID"].str.contains("BLK_UP_092")]
        assert len(fmt_ctrl) == 1
        assert fmt_ctrl.iloc[0]["Controlling"] == "YES"

        # Sum of 7 components equals Total Blocking (s) for every row
        comp_cols = [
            "Setup (s)",
            "Approach (s)",
            "Running (s)",
            "Dwell (s)",
            "Clearance (s)",
            "Residual Rear (s)",
            "Release (s)",
        ]
        sums = raw_df[comp_cols].sum(axis=1)
        diffs = (sums - raw_df["Total Blocking (s)"]).abs()
        assert (diffs < 1e-3).all(), f"Component sum mismatch found: max diff = {diffs.max()}"

    def test_reporting_missing_blocking_intervals_raises_loud_error(self) -> None:
        """Phase 4c: Assert assemble_report raises ERR_REPORT_MISSING_BLOCKING_INTERVALS when missing."""
        pkg = _create_synthetic_full_package()
        pkg.metadata["blocking_intervals"] = []
        pkg.blocking_intervals = []

        with pytest.raises(ReportingError) as exc_info:
            ReportAssembler.assemble_report(pkg)

        assert "ERR_REPORT_MISSING_BLOCKING_INTERVALS" in str(exc_info.value.error_code)

    def test_reporting_pairwise_conflict_geometry_hsr_corridor(self) -> None:
        """DEF-08: Assert Pairwise Critical Conflict Ranking rows contain non-zero geometry on 07_hsr_140km."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        sec_conflict = doc.get_section(ReportSectionId.CONFLICT_RANKING)
        assert sec_conflict is not None
        assert sec_conflict.is_applicable
        conflict_table = sec_conflict.tables[0]
        assert "Conflict" in conflict_table.title or "CONFLICT" in conflict_table.table_id

        raw_df = conflict_table.raw_dataframe
        assert len(raw_df) > 0
        assert "Physical Location (m)" in raw_df.columns
        assert "Route Chainage (km)" in raw_df.columns
        assert "Time Gap (s)" in raw_df.columns

        # Rank 1 conflict is the controlling bottleneck BLK_UP_092
        r1 = raw_df.iloc[0]
        assert r1["Leader Resource"] == "BLK_UP_092"
        assert r1["Physical Location (m)"] > 100_000.0
        assert r1["Route Chainage (km)"] > 100.0
        assert pytest.approx(138.346, abs=0.1) == r1["Route Chainage (km)"]
        assert pytest.approx(138346.0, abs=100.0) == r1["Physical Location (m)"]
        assert r1["Classification"] == "CONTROLLING"

        # Assert non-zero physical location and route chainage exist across table rows
        assert (raw_df["Physical Location (m)"] > 0.0).any()
        assert (raw_df["Route Chainage (km)"] > 0.0).any()

        # Chainage km equals Location m / 1000 within tolerance
        chainage_check = (raw_df["Route Chainage (km)"] - (raw_df["Physical Location (m)"] / 1000.0)).abs()
        assert (chainage_check < 1e-4).all()

        # Time gap equals Leader Release minus Follower Start
        time_gap_check = (raw_df["Time Gap (s)"] - (raw_df["Leader Release (s)"] - raw_df["Follower Start (s)"])).abs()
        assert (time_gap_check < 1e-3).all()

        # Formatted dataframe checks
        fmt_df = conflict_table.formatted_dataframe
        fmt_r1 = fmt_df.iloc[0]
        assert fmt_r1["Leader Resource"] == "BLK_UP_092"
        assert fmt_r1["Physical Location (m)"] == "138346.0"
        assert fmt_r1["Route Chainage (km)"] == "138.35"
        assert "CONTROLLING" in fmt_r1["Classification"]

    def test_reporting_tvs_assessment_hsr_corridor(self) -> None:
        """DEF-09: Assert Section 13 TVS chart contains 14 distinct sequential TVS traces on 07_hsr_140km."""
        from headway.data.canonical import ResourceInterval, TVSSection
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        # In 07_hsr_140km, links LNK_0180 to LNK_0221 (42 links of 313m each = 13,146m) form the 14 TVS zones (3 links each)
        proj.infrastructure.tvs_sections = [
            TVSSection(
                tvs_id=f"TVS_{i+1:02d}",
                tunnel_id="TUNNEL_01",
                track_id="TRK_01",
                link_intervals=[
                    ResourceInterval(
                        link_id=f"LNK_{180 + i * 3 + k:04d}",
                        start_offset_m=0.0,
                        end_offset_m=313.0,
                    )
                    for k in range(3)
                ],
                release_delay_s=15.0,
            )
            for i in range(14)
        ]

        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        sec_tvs = doc.get_section(ReportSectionId.TVS_ASSESSMENT)
        assert sec_tvs is not None
        assert sec_tvs.is_applicable

        fig_tvs = doc.figures_data[sec_tvs.figure_keys[0]]

        # The Section 13 TVS chart data contains 14 distinct TVS section traces
        occ_traces = [t for t in fig_tvs.data if "Physical Occupation" in (t.name or "")]
        assert len(occ_traces) == 14

        # Distinct sections count on Y-axis
        tvs_ids = [str(t.y[0]) for t in occ_traces]
        assert len(set(tvs_ids)) == 14
        assert tvs_ids[0] == "TVS_01"
        assert tvs_ids[-1] == "TVS_14"

        # Start times are strictly increasing along route
        start_times = [float(t.base[0]) for t in occ_traces]
        for i in range(len(start_times) - 1):
            assert start_times[i] < start_times[i + 1], f"start_times[{i}] ({start_times[i]}) not < start_times[{i+1}] ({start_times[i+1]})"

        # End time > start time and duration > 0
        durations = [float(t.x[0]) for t in occ_traces]
        for i, dur in enumerate(durations):
            assert dur > 0.0
            end_t = start_times[i] + dur
            assert end_t > start_times[i]

        # Duration scales correctly with TVS length and train speed (train decelerates near STN_03)
        assert durations[-1] > durations[0]

        # Y-axis ordering check
        categoryarray = list(fig_tvs.layout.yaxis.categoryarray)
        expected_sections = [f"TVS_{i+1:02d}" for i in range(14)]
        assert categoryarray == expected_sections
        assert fig_tvs.layout.yaxis.autorange == "reversed"

        # v1.8.0 Task 1: TVS chart trace text annotation check
        annotated_traces = [t for t in fig_tvs.data if getattr(t, "text", None)]
        assert len(annotated_traces) == 14
        annotated_tvs_ids = [str(t.text[0]) for t in annotated_traces]
        assert annotated_tvs_ids == [f"TVS_{i+1:02d}" for i in range(14)]

    def test_tvs_capacity_impact_table(self) -> None:
        """v1.8.0 Task 2/3: Assert TVS capacity impact table exists and calculates throughput correctly."""
        from headway.data.canonical import ResourceInterval, TVSSection
        from headway.reporting.report_models import ReportSectionId
        from headway.reporting.tables import create_tvs_capacity_table
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        # 1. Integration check on corridor pipeline
        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        proj.infrastructure.tvs_sections = [
            TVSSection(
                tvs_id=f"TVS_{i+1:02d}",
                tunnel_id="TUNNEL_01",
                track_id="TRK_01",
                link_intervals=[
                    ResourceInterval(
                        link_id=f"LNK_{180 + i * 3 + k:04d}",
                        start_offset_m=0.0,
                        end_offset_m=313.0,
                    )
                    for k in range(3)
                ],
                release_delay_s=15.0,
            )
            for i in range(14)
        ]

        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)
        sec_tvs = doc.get_section(ReportSectionId.TVS_ASSESSMENT)
        assert sec_tvs is not None
        assert sec_tvs.is_applicable

        # Verify capacity table exists in Section 13
        cap_tbls = [t for t in sec_tvs.tables if t.table_id == "TBL_TVS_CAPACITY"]
        assert len(cap_tbls) == 1
        tbl = cap_tbls[0]
        df = tbl.raw_dataframe

        # Check required columns
        expected_cols = ["Constraint Type", "Governing Zone/Resource", "Minimum Headway (s)", "Theoretical Throughput (tph)", "Status"]
        assert list(df.columns) == expected_cols

        # Check row count (at least 2, 3 with combined)
        assert len(df) >= 2
        tvs_row = df[df["Constraint Type"] == "TVS Ventilation"].iloc[0]
        sig_row = df[df["Constraint Type"] == "Signalling"].iloc[0]

        # Verify TVS row metrics
        h_tvs = float(tvs_row["Minimum Headway (s)"])
        assert h_tvs > 0.0
        expected_tph_tvs = round(3600.0 / h_tvs, 1)
        assert float(tvs_row["Theoretical Throughput (tph)"]) == expected_tph_tvs

        # Verify Signalling row metrics
        h_sig = float(sig_row["Minimum Headway (s)"])
        assert h_sig > 0.0
        expected_tph_sig = round(3600.0 / h_sig, 1)
        assert float(sig_row["Theoretical Throughput (tph)"]) == expected_tph_sig

        # Signalling headway (244.0s) > TVS headway (41.3s), so Signalling governs
        assert h_sig > h_tvs
        assert sig_row["Status"] == "GOVERNING CONSTRAINT"
        assert tvs_row["Status"] == "Non-Governing"

        # Verify dynamic narrative in Section 13
        narrative_text = " ".join(sec_tvs.narrative_paragraphs)
        assert "The TVS system imposes a minimum headway of" in narrative_text
        assert "Because the signalling headway" in narrative_text
        assert "non-governing under normal operations" in narrative_text

        # 2. Synthetic verification of TVS-governing scenario
        synth_tbl = create_tvs_capacity_table(
            tvs_headway_s=300.0,
            signalling_headway_s=180.0,
            tvs_governing_zone="TVS_CRITICAL",
            signalling_governing_resource="SIG_BLK_01",
        )
        synth_df = synth_tbl.raw_dataframe
        synth_tvs = synth_df[synth_df["Constraint Type"] == "TVS Ventilation"].iloc[0]
        synth_sig = synth_df[synth_df["Constraint Type"] == "Signalling"].iloc[0]

        assert synth_tvs["Status"] == "GOVERNING CONSTRAINT"
        assert synth_sig["Status"] == "Non-Governing"
        assert float(synth_tvs["Theoretical Throughput (tph)"]) == 12.0
        assert float(synth_sig["Theoretical Throughput (tph)"]) == 20.0

    def test_reporting_tvs_not_applicable_when_no_tunnels(self) -> None:
        """DEF-09: Assert Section 13 is marked not applicable when project has no tunnels or TVS sections."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        proj.infrastructure.tvs_sections = []
        proj.infrastructure.tunnels = []

        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        sec_tvs = doc.get_section(ReportSectionId.TVS_ASSESSMENT)
        assert sec_tvs is not None
        assert sec_tvs.is_applicable is False
        assert sec_tvs.not_applicable_reason is not None

    def test_reporting_tvs_loud_failure_when_infra_exists_but_trajectory_missing(self) -> None:
        """DEF-09: Assert loud error is raised when TVS infrastructure is present but simulation trajectory is missing."""
        from headway.data.canonical import ResourceInterval, TVSSection
        from headway.ui.file_manager import FileManager

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        proj.infrastructure.tvs_sections = [
            TVSSection(
                tvs_id="TVS_01",
                tunnel_id="TUNNEL_01",
                track_id="TRK_01",
                link_intervals=[ResourceInterval(link_id="LNK_03", start_offset_m=56000.0, end_offset_m=57000.0)],
            )
        ]

        pkg = _create_synthetic_full_package()
        pkg.metadata["tvs_events"] = []
        pkg.metadata["project"] = proj
        pkg.trajectories = {}

        with pytest.raises(ReportingError) as exc_info:
            ReportAssembler.assemble_report(pkg, project=proj)

        assert "ERR_REPORT_MISSING_TVS_EVENTS" in str(exc_info.value.error_code)

    def test_report_integrity_no_phantom_data_single_service_baseline(self) -> None:
        """v1.8.1 DEF-12/13: Assert that when a project with only SCN_BASELINE and SRV_6000 is processed,
        Section 16 (Scenario Comparison) and Section 7/9 (Mixed-Traffic Matrix) are is_applicable = False,
        and phantom data strings (SCEN_UPGRADE, METRO_COMMUTER, METRO_EXPRESS) do not exist in ReportDocument.
        """
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        assert len(proj.scenarios) == 1
        assert proj.scenarios[0].scenario_id == "SCEN_BASELINE"
        assert len(proj.operations.service_patterns) == 1
        assert proj.operations.service_patterns[0].service_pattern_id == "SRV_6000"

        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        # Section 16 (Scenario Comparison) must be NOT applicable
        sec_cmp = doc.get_section(ReportSectionId.SCENARIO_COMPARISON)
        assert sec_cmp is not None
        assert sec_cmp.is_applicable is False
        assert "Scenario comparison requires at least two scenarios" in (sec_cmp.not_applicable_reason or "")
        assert len(sec_cmp.tables) == 0

        # Section 7/9 (Mixed-Traffic Matrix) must be NOT applicable
        sec_mt = doc.get_section(ReportSectionId.MIXED_TRAFFIC_MATRIX)
        assert sec_mt is not None
        assert sec_mt.is_applicable is False
        assert "Mixed-traffic matrix requires at least two distinct service patterns" in (sec_mt.not_applicable_reason or "")
        assert len(sec_mt.tables) == 0

        # Entire ReportDocument must not contain phantom data strings
        from headway.reporting.json_export import JsonReportExporter
        doc_json = JsonReportExporter.export(doc)
        assert "SCEN_UPGRADE" not in doc_json
        assert "METRO_COMMUTER" not in doc_json
        assert "METRO_EXPRESS" not in doc_json

    def test_platform_occupation_chart_and_table_enhancements(self) -> None:
        """v1.9.0 Part 3: Assert platform occupation chart has 3 traces and platform table has new 6-column format."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        sec_plt = doc.get_section(ReportSectionId.STATION_PLATFORM_OCCUPATION)
        assert sec_plt is not None
        assert sec_plt.is_applicable

        # 1. Assert platform table exists
        plt_tbls = [t for t in sec_plt.tables if t.table_id == "TBL_PLATFORM_OCCUPATION"]
        assert len(plt_tbls) == 1
        tbl = plt_tbls[0]
        df = tbl.raw_dataframe

        expected_cols = [
            "Platform ID",
            "Train ID",
            "Arrival Approach (s)",
            "Passenger Dwell (s)",
            "Departure Clearance (s)",
            "Total Occupation (s)",
        ]
        assert list(df.columns) == expected_cols
        assert len(df) == 5

        # Check metrics calculation (Total = Approach + Dwell + Clearance)
        for _, row in df.iterrows():
            app = float(row["Arrival Approach (s)"])
            dwell = float(row["Passenger Dwell (s)"])
            clr = float(row["Departure Clearance (s)"])
            tot = float(row["Total Occupation (s)"])
            assert tot == pytest.approx(app + dwell + clr, abs=0.1)

        # 2. Assert chart traces use 3 stacked components
        fig_key = sec_plt.figure_keys[0]
        fig_plt = doc.figures_data[fig_key]
        assert fig_plt.layout.barmode == "stack"
        assert fig_plt.layout.yaxis.title.text == "Occupation Duration (s)"
        assert fig_plt.layout.xaxis.title.text == "Platform ID"

        trace_names = [t.name for t in fig_plt.data]
        assert trace_names == ["Arrival Approach", "Passenger Dwell", "Departure Clearance"]

        app_trace = next(t for t in fig_plt.data if t.name == "Arrival Approach")
        assert getattr(app_trace, "base", None) is None
        assert list(app_trace.y) == [15.0, 15.0, 15.0, 15.0, 15.0]

        dwell_trace = next(t for t in fig_plt.data if t.name == "Passenger Dwell")
        assert getattr(dwell_trace, "base", None) is None
        assert list(dwell_trace.y) == [120.0, 120.0, 120.0, 120.0, 120.0]

        clr_trace = next(t for t in fig_plt.data if t.name == "Departure Clearance")
        assert getattr(clr_trace, "base", None) is None
        assert list(clr_trace.y) == [15.0, 15.0, 15.0, 15.0, 15.0]

        # 3. Assert dynamic narrative contains calculated max occupation time
        max_tot = df["Total Occupation (s)"].max()
        gov_row = df.loc[df["Total Occupation (s)"].idxmax()]
        gov_plt = gov_row["Platform ID"]
        narrative_text = " ".join(sec_plt.narrative_paragraphs)
        assert f"The longest platform occupation occurred at {gov_plt}" in narrative_text
        assert f"totaling {max_tot:.1f} s" in narrative_text

    def test_uic406_track_clearance_split_and_speeds(self) -> None:
        """v1.9.0 Part 1: Assert clearance_time_s > 0.0 for track blocks and v_in_kmh, v_out_kmh populated."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        # Blocking intervals assertion
        assert len(pkg.blocking_intervals) > 0
        for bi in pkg.blocking_intervals:
            d = bi.decomposition
            assert d is not None
            assert d.geometric_clearance_time_s > 0.0, f"Block {bi.resource_id} has zero clearance time"
            assert hasattr(d, "v_in_kmh")
            assert hasattr(d, "v_out_kmh")
            assert d.v_out_kmh > 0.0, f"Block {bi.resource_id} has zero exit speed"

        # Table assertion
        sec10 = doc.get_section(ReportSectionId.DETAILED_RESOURCE_TIMING)
        assert sec10 is not None
        assert sec10.is_applicable
        tbl10 = sec10.tables[0]
        df10 = tbl10.raw_dataframe
        assert "V_in (km/h)" in df10.columns
        assert "V_out (km/h)" in df10.columns
        assert "Clearance (s)" in df10.columns
        assert (df10["Clearance (s)"] > 0.0).all()

    def test_constrained_block_length_sensitivity_26_cases(self) -> None:
        """v1.9.0 Part 2: Assert sensitivity chart data contains exactly 26 cases with AS-BUILT pinned."""
        from headway.ui.file_manager import FileManager
        from headway.ui.simulation_runner import SimulationRunner

        proj, _, _ = FileManager.load_example_project("07_hsr_140km")
        pkg, doc = SimulationRunner.run_simulation_pipeline(proj, RunningDirection.FORWARD)

        study = pkg.sensitivity_result
        assert study is not None
        assert len(study.points) == 26

        expected_x = ["AS-BUILT"] + [f"{l * 200}m" for l in range(1, 26)]
        actual_x = [str(p.parameter_value) for p in study.points]
        assert actual_x == expected_x

        # Assert AS-BUILT matches baseline
        assert study.points[0].headway_s == study.baseline_headway_s
        assert study.points[0].capacity_trains_per_hour == study.baseline_capacity_tph

        # Assert figure data
        sec9 = doc.get_section(ReportSectionId.BLOCK_LENGTH_SENSITIVITY)
        assert sec9 is not None
        assert sec9.is_applicable
        fig_key = sec9.figure_keys[0]
        fig = doc.figures_data[fig_key]
        assert "Constrained Sensitivity Analysis (AS-BUILT Baseline Pinned)" in fig.layout.title.text

        hw_trace = next(t for t in fig.data if t.name == "Minimum Technical Headway [s]")
        cap_trace = next(t for t in fig.data if t.name == "Theoretical Capacity [tph]")
        assert len(hw_trace.x) == 26
        assert len(cap_trace.x) == 26
        assert list(hw_trace.x) == expected_x



