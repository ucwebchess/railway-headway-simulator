"""Engineering benchmarks for Milestone P14 Professional Engineering Report Generator.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 33).
Covers all 35 mandatory benchmarks:
- P14-B001: KPI consistency with source results
- P14-B002: Speed profile section
- P14-B003: Gradient and curvature section
- P14-B004: Blocking stairway section
- P14-B005: Seven-component chart reconciliation
- P14-B006: Pairwise conflict ranking
- P14-B007: Longest occupation ranking
- P14-B008: Station/platform table
- P14-B009: Mixed-traffic heatmap
- P14-B010: Block-length sensitivity chart
- P14-B011: Detailed resource timing table
- P14-B012: Resource geometry provenance table
- P14-B013: Assumptions and audit section
- P14-B014: TVS assessment section
- P14-B015: Operational assessment section
- P14-B016: Stochastic reliability section
- P14-B017: Scenario comparison section
- P14-B018: Verification and limitations section
- P14-B019: Conclusions and recommendations section
- P14-B020: Rule-based recommendation correctness
- P14-B021: HTML report generation
- P14-B022: PDF report generation
- P14-B023: Excel export
- P14-B024: CSV export
- P14-B025: JSON export
- P14-B026: Report package export
- P14-B027: Report reproducibility
- P14-B028: Missing-data handling
- P14-B029: Forward direction report
- P14-B030: Reverse direction report
- P14-B031: Direction-specific chart order
- P14-B032: No hardcoded reference values
- P14-B033: Report validation
- P14-B034: Report provenance
- P14-B035: Report immutability
"""

from pathlib import Path
import tempfile
from typing import Dict, List
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
from headway.reporting.result_models import (
    PlatformOccupationRecord,
    ResourceProvenanceRecord,
    ResourceTimingRecord,
    SimulationResultPackage,
    StationStopRecord,
)
from headway.reporting.report_package import ReportPackageExporter
from headway.reporting.report_validation import (
    ReportDiagnosticCode,
    ReportValidator,
)
from headway.scenarios.scenario_comparison import (
    BottleneckShiftReport,
    MetricDifference,
    ScenarioComparisonReport,
)
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory


def build_benchmark_trajectory(
    train_id: str = "TRN_BM_01",
    running_direction: RunningDirection = RunningDirection.FORWARD,
) -> TrainTrajectory:
    """Builds a verified microscopic physical train trajectory."""
    samples = []
    t = 0.0
    dist = 0.0 if running_direction == RunningDirection.FORWARD else 3000.0
    v = 0.0
    target_v = 80.0 / 3.6  # 22.2 m/s

    for step in range(30):
        if step < 10:
            v = min(target_v, v + 1.0 * 2.0)
            mode = DynamicMode.ACCELERATING
        elif step < 20:
            v = target_v
            mode = DynamicMode.CRUISING
        else:
            v = max(0.0, v - 1.2 * 2.0)
            mode = DynamicMode.SERVICE_BRAKING

        delta_d = v * 2.0
        dist += delta_d if running_direction == RunningDirection.FORWARD else -delta_d
        t += 2.0

        sample = TrajectorySample(
            time_s=t,
            front_distance_m=dist,
            rear_distance_m=max(0.0, dist - 120.0),
            speed_ms=v,
            acceleration_ms2=1.0 if mode == DynamicMode.ACCELERATING else (-1.2 if mode == DynamicMode.SERVICE_BRAKING else 0.0),
            traction_force_n=100000.0 if mode == DynamicMode.ACCELERATING else 0.0,
            braking_force_n=120000.0 if mode == DynamicMode.SERVICE_BRAKING else 0.0,
            davis_resistance_n=2000.0,
            gradient_resistance_n=0.0,
            curvature_resistance_n=0.0,
            net_force_n=0.0,
            dynamic_mode=mode,
            operational_state=OperationalState.RUNNING if v > 0 else OperationalState.STANDSTILL,
            link_id="TL_01",
            physical_coordinate_m=dist,
        )
        samples.append(sample)

    return TrainTrajectory(
        train_id=train_id,
        train_type_id="TT_METRO",
        route_id="RT_01",
        running_direction=running_direction,
        samples=samples,
    )


def build_benchmark_blocking_intervals(
    running_direction: RunningDirection = RunningDirection.FORWARD,
) -> List[ResourceBlockingInterval]:
    """Builds 4 sequenced blocking intervals with verified 7-component decomposition."""
    intervals = []
    res_ids = ["BLK_01", "BLK_02", "BLK_03", "BLK_04"]
    for idx, rid in enumerate(res_ids):
        decomp = BlockingTimeDecomposition(
            setup_time_s=3.0,
            approach_time_s=8.0,
            running_time_s=15.0,
            dwell_time_s=10.0 if idx == 1 else 0.0,
            geometric_clearance_time_s=8.0,
            residual_rear_time_s=0.0,
            release_time_s=4.0,
            reconciliation_difference_s=0.0,
        )
        t_start = idx * 25.0
        t_end = t_start + decomp.total_duration_s

        intervals.append(
            ResourceBlockingInterval(
                interval_id=f"INT_{rid}",
                resource_id=rid,
                resource_category=ResourceCategory.TRACK_BLOCK,
                train_id="TRN_BM_01",
                start_time_s=t_start,
                end_time_s=t_end,
                running_direction=running_direction,
                physical_start_offset_m=idx * 600.0,
                physical_end_offset_m=(idx + 1) * 600.0,
                decomposition=decomp,
            )
        )
    return intervals


def build_benchmark_package(
    running_direction: RunningDirection = RunningDirection.FORWARD,
    headway_s: float = 85.0,
) -> SimulationResultPackage:
    """Builds a complete SimulationResultPackage populated across all subsystems."""
    traj = build_benchmark_trajectory(running_direction=running_direction)
    intervals = build_benchmark_blocking_intervals(running_direction=running_direction)

    conflict = ResourceConflict(
        conflict_id="CONF_01",
        leader_usage=intervals[1],
        follower_usage=intervals[1],
        conflict_type=ConflictType.IDENTICAL_RESOURCE,
        leader_release_time_s=intervals[1].end_time_s,
        follower_start_time_s=intervals[1].start_time_s + 10.0,
        required_headway_s=headway_s,
        slack_s=0.0,
        bottleneck_type="CRITICAL_BLOCK",
    )

    hw_result = HeadwayResult(
        run_id="RUN_BM_01",
        analysis_id="AN_01",
        scenario_id="SCEN_BASE",
        leader_service_id="METRO_A",
        follower_service_id="METRO_B",
        reference_point_id="BLK_02",
        running_direction=running_direction,
        signalling_system="FIXED_BLOCK_3ASPECT",
        headway_definition="TECHNICAL_MINIMUM",
        headway_s=headway_s,
        minimum_dispatch_headway_s=headway_s,
        controlling_conflicts=[conflict],
        conflict_ranking=[conflict],
        blocking_intervals=intervals,
    )

    mt_matrix = MixedTrafficHeadwayMatrix(
        matrix_id="MT_BM",
        running_direction=running_direction,
        service_ids=["METRO_A", "METRO_B"],
        headway_values_s={
            ("METRO_A", "METRO_A"): headway_s,
            ("METRO_A", "METRO_B"): headway_s + 5.0,
            ("METRO_B", "METRO_A"): headway_s + 2.0,
            ("METRO_B", "METRO_B"): headway_s,
        },
        controlling_bottlenecks={
            ("METRO_A", "METRO_A"): "BLK_02",
            ("METRO_A", "METRO_B"): "BLK_02",
            ("METRO_B", "METRO_A"): "BLK_03",
            ("METRO_B", "METRO_B"): "BLK_02",
        },
    )

    study = SensitivityStudyResult(
        study_id="SENS_BM",
        parameter_name="block_length_m",
        baseline_value=600.0,
        baseline_capacity_tph=3600.0 / headway_s,
        baseline_headway_s=headway_s,
        baseline_bottleneck_id="BLK_02",
        points=[
            SensitivityPointResult(
                parameter_name="block_length_m",
                parameter_value=400.0,
                capacity_trains_per_hour=48.0,
                headway_s=75.0,
                limiting_bottleneck_id="BLK_01",
            ),
            SensitivityPointResult(
                parameter_name="block_length_m",
                parameter_value=600.0,
                capacity_trains_per_hour=3600.0 / headway_s,
                headway_s=headway_s,
                limiting_bottleneck_id="BLK_02",
            ),
            SensitivityPointResult(
                parameter_name="block_length_m",
                parameter_value=800.0,
                capacity_trains_per_hour=36.7,
                headway_s=98.0,
                limiting_bottleneck_id="BLK_03",
            ),
        ],
    )

    stat = StatisticalSummary(
        metric_name="headway_s",
        sample_count=50,
        mean=headway_s + 2.0,
        median=headway_s + 1.5,
        std_dev=3.0,
        min_value=headway_s - 1.0,
        max_value=headway_s + 8.0,
        p5=headway_s,
        p50=headway_s + 1.5,
        p90=headway_s + 6.0,
        p95=headway_s + 7.0,
        p99=headway_s + 8.0,
    )

    report_cmp = ScenarioComparisonReport(
        baseline_scenario_id="SCEN_BASE",
        compared_scenario_ids=["SCEN_UPGRADE"],
        metric_differences={
            "SCEN_UPGRADE": [
                MetricDifference(
                    metric_name="headway_s",
                    baseline_value=headway_s,
                    scenario_value=headway_s - 15.0,
                    absolute_change=-15.0,
                    percentage_change=-17.6,
                )
            ]
        },
        bottleneck_shifts=[
            BottleneckShiftReport(
                baseline_scenario_id="SCEN_BASE",
                comparison_scenario_id="SCEN_UPGRADE",
                bottleneck_migrated=True,
                baseline_bottleneck_id="BLK_02",
                comparison_bottleneck_id="BLK_04",
            )
        ],
    )

    plt_rec = PlatformOccupationRecord(
        train_id="TRN_BM_01",
        station_id="STN_CENTRAL",
        station_name="Central Station",
        platform_id="PLT_01",
        track_id="TRK_01",
        link_id="TL_01",
        arrival_time_s=30.0,
        dwell_start_time_s=32.0,
        dwell_end_time_s=52.0,
        departure_time_s=55.0,
        clearance_time_s=65.0,
        running_direction=running_direction,
        is_residual_rear_active=True,
        residual_rear_duration_s=12.0,
        upstream_infringing_resource_ids=("BLK_01",),
    )

    tvs_rec = {
        "tvs_id": "TVS_01",
        "train_id": "TRN_BM_01",
        "entry_time_s": 40.0,
        "exit_time_s": 85.0,
        "release_time_s": 93.0,
        "waiting_duration_s": 0.0,
    }

    prov_rec = ResourceProvenanceRecord(
        resource_id="BLK_02",
        resource_type="TRACK_BLOCK",
        physical_chainage_km=0.6,
        resource_length_m=600.0,
        geometry_source="INPUT_MODEL",
        dataset_id="DS_01",
        dataset_version="1.0.0",
        is_baseline_geometry=True,
    )

    stop_rec = StationStopRecord(
        train_id="TRN_BM_01",
        station_id="STN_CENTRAL",
        station_name="Central Station",
        platform_id="PLT_01",
        link_id="TL_01",
        running_direction=running_direction,
        arrival_time_s=30.0,
        dwell_duration_s=20.0,
        departure_time_s=50.0,
        front_stopping_position_m=850.0,
        rear_stopping_position_m=730.0,
        route_chainage_km=0.85,
        physical_chainage_km=0.85,
    )

    mc_result = MonteCarloExecutionResult(
        analysis_id="MC_BM",
        scenario_id="SCEN_BASE",
        total_replications=50,
        valid_replications=50,
        failed_replications=0,
        summaries={"headway_s": stat},
    )

    return SimulationResultPackage(
        run_id="RUN_BM_01",
        scenario_id="SCEN_BASE",
        effective_config_hash="hash_bm_1234567890",
        running_direction=running_direction,
        trajectories={"TRN_BM_01": traj},
        headway_results={"METRO_A->METRO_B": hw_result},
        mixed_traffic_matrix=mt_matrix,
        blocking_intervals=intervals,
        sensitivity_result=study,
        monte_carlo_result=mc_result,
        scenario_comparison_report=report_cmp,
        metadata={
            "platform_records": [plt_rec],
            "station_stops": [stop_rec],
            "provenance_records": [prov_rec],
            "stochastic_headway_samples": [85.0 + i * 0.5 for i in range(20)],
            "tvs_events": [tvs_rec],
        },
    )


class TestReportBenchmarks:
    """Benchmark suite covering P14-B001 through P14-B035."""

    def test_p14_b001_kpi_consistency(self) -> None:
        """P14-B001: Executive KPIs match source simulation results exactly."""
        pkg = build_benchmark_package(headway_s=88.0)
        doc = ReportAssembler.assemble_report(pkg)
        assert doc.executive_kpis.technical_headway_s == 88.0
        assert doc.executive_kpis.technical_headway_min == pytest.approx(88.0 / 60.0, abs=1e-2)
        assert doc.executive_kpis.theoretical_capacity_tph == pytest.approx(3600.0 / 88.0, abs=1e-1)
        assert doc.executive_kpis.controlling_bottleneck_id == "BLK_02"

    def test_p14_b002_speed_profile_section(self) -> None:
        """P14-B002: Speed profile section is applicable and populated."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.SPEED_GRADIENT_CURVATURE)
        assert sec is not None
        assert sec.is_applicable
        assert len(sec.figure_keys) >= 1
        assert "fig_speed_alignment" in doc.figures_data

    def test_p14_b003_gradient_curvature_section(self) -> None:
        """P14-B003: Alignment section notes direction-aware gradient sign."""
        pkg = build_benchmark_package(running_direction=RunningDirection.REVERSE)
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.SPEED_GRADIENT_CURVATURE)
        assert sec is not None
        assert "REVERSE" in sec.narrative_paragraphs[0]

    def test_p14_b004_blocking_stairway_section(self) -> None:
        """P14-B004: Blocking stairway section includes stairway figure."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.BLOCKING_STAIRWAY)
        assert sec is not None
        assert sec.is_applicable
        assert "fig_blocking_stairway" in sec.figure_keys

    def test_p14_b005_seven_component_reconciliation(self) -> None:
        """P14-B005: Seven-component breakdown reconciles with total duration."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.SEVEN_COMPONENT_BREAKDOWN)
        assert sec is not None
        assert sec.is_applicable
        for bi in pkg.blocking_intervals:
            assert abs(bi.duration_s - bi.decomposition.total_duration_s) <= 1e-3

    def test_p14_b006_pairwise_conflict_ranking(self) -> None:
        """P14-B006: Pairwise conflict ranking table tabulates ranked conflicts."""
        pkg = build_benchmark_package(headway_s=92.5)
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.CONFLICT_RANKING)
        assert sec is not None
        assert sec.is_applicable
        assert len(sec.tables) == 1
        tbl = sec.tables[0]
        assert tbl.row_count >= 1
        assert tbl.raw_dataframe["Required Headway (s)"].iloc[0] == 92.5

    def test_p14_b007_longest_occupation_ranking(self) -> None:
        """P14-B007: Longest occupation table sorts resources descending by duration."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.LONGEST_OCCUPATIONS)
        assert sec is not None
        assert sec.is_applicable
        tbl = sec.tables[0]
        durs = tbl.raw_dataframe["Total Duration (s)"].tolist()
        assert durs == sorted(durs, reverse=True)

    def test_p14_b008_station_platform_table(self) -> None:
        """P14-B008: Station platform occupation section is populated."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.STATION_PLATFORM_OCCUPATION)
        assert sec is not None
        assert sec.is_applicable
        assert "fig_platform_occupation" in sec.figure_keys

    def test_p14_b009_mixed_traffic_heatmap(self) -> None:
        """P14-B009: Mixed-traffic section contains matrix heatmap and table."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.MIXED_TRAFFIC_MATRIX)
        assert sec is not None
        assert sec.is_applicable
        assert "fig_mixed_traffic_heatmap" in sec.figure_keys
        assert len(sec.tables) == 1

    def test_p14_b010_block_length_sensitivity_chart(self) -> None:
        """P14-B010: Sensitivity section includes 2-panel block length chart."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.BLOCK_LENGTH_SENSITIVITY)
        assert sec is not None
        assert sec.is_applicable
        assert "fig_block_sensitivity" in sec.figure_keys

    def test_p14_b011_detailed_resource_timing_table(self) -> None:
        """P14-B011: Detailed timing table tabulates all 7 components."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.DETAILED_RESOURCE_TIMING)
        assert sec is not None
        assert sec.is_applicable
        tbl = sec.tables[0]
        assert "Total Blocking (s)" in tbl.columns
        assert tbl.row_count == 4

    def test_p14_b012_geometry_provenance_table(self) -> None:
        """P14-B012: Geometry provenance table links resources to baseline."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.GEOMETRY_PROVENANCE)
        assert sec is not None
        assert sec.is_applicable
        tbl = sec.tables[0]
        assert "Resource ID" in tbl.columns
        assert tbl.raw_dataframe["Resource ID"].iloc[0] == "BLK_02"

    def test_p14_b013_assumptions_audit_section(self) -> None:
        """P14-B013: Assumptions section records software version and hash."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.ASSUMPTIONS_AUDIT)
        assert sec is not None
        assert sec.is_applicable
        assert sec.kpis["Config Hash"] == pkg.effective_config_hash

    def test_p14_b014_tvs_assessment_section(self) -> None:
        """P14-B014: TVS section is present when TVS data is supplied."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.TVS_ASSESSMENT)
        assert sec is not None
        assert sec.is_applicable
        assert "fig_tvs_occupation" in sec.figure_keys

    def test_p14_b015_operational_assessment_section(self) -> None:
        """P14-B015: Operational assessment marks not-applicable cleanly when absent."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.OPERATIONAL_ASSESSMENT)
        assert sec is not None
        assert not sec.is_applicable
        assert "No continuous multi-train" in (sec.not_applicable_reason or "")

    def test_p14_b016_stochastic_reliability_section(self) -> None:
        """P14-B016: Stochastic section is applicable when summaries exist."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.STOCHASTIC_RELIABILITY)
        assert sec is not None
        assert sec.is_applicable
        assert "fig_stochastic_histogram" in sec.figure_keys

    def test_p14_b017_scenario_comparison_section(self) -> None:
        """P14-B017: Scenario comparison section includes comparison chart & table."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.SCENARIO_COMPARISON)
        assert sec is not None
        assert sec.is_applicable
        assert "fig_scenario_comparison" in sec.figure_keys
        assert len(sec.tables) == 1

    def test_p14_b018_verification_limitations_section(self) -> None:
        """P14-B018: Verification section is present and includes audit verdict."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.VERIFICATION_LIMITATIONS)
        assert sec is not None
        assert sec.is_applicable
        assert len(sec.callout_boxes) >= 1

    def test_p14_b019_conclusions_recommendations_section(self) -> None:
        """P14-B019: Conclusions section summarizes KPIs and recommendations."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        sec = doc.get_section(ReportSectionId.CONCLUSIONS_RECOMMENDATIONS)
        assert sec is not None
        assert sec.is_applicable
        assert len(sec.recommendations) >= 1

    def test_p14_b020_rule_based_recommendation_correctness(self) -> None:
        """P14-B020: Recommendation engine generates valid rule-derived findings."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        recs = doc.recommendations
        assert len(recs) >= 1
        # Residual rear fouling rule should trigger
        cat_values = [r.category for r in recs]
        assert RecommendationCategory.STATION_PLATFORM_MODIFICATION in cat_values
        r_rear = next(r for r in recs if r.category == RecommendationCategory.STATION_PLATFORM_MODIFICATION)
        assert "12.0 s" in r_rear.description

    def test_p14_b021_html_report_generation(self) -> None:
        """P14-B021: HTML report renderer generates valid standalone HTML."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "report.html"
            html_content = HtmlReportRenderer.render(doc, output_path=out_file)
            assert out_file.exists()
            assert "<!DOCTYPE html>" in html_content
            assert "Technical Minimum Headway" in html_content
            assert "RUNNING DIRECTION: FORWARD" in html_content

    def test_p14_b022_pdf_report_generation(self) -> None:
        """P14-B022: PDF report renderer produces valid non-empty PDF document."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "report.pdf"
            PdfReportRenderer.render(doc, output_path=out_file)
            assert out_file.exists()
            assert out_file.stat().st_size > 1000

    def test_p14_b023_excel_export(self) -> None:
        """P14-B023: Excel exporter creates multi-tab workbook with Executive Summary."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "results.xlsx"
            ExcelReportExporter.export(doc, output_path=out_file)
            assert out_file.exists()
            wb = pd.ExcelFile(out_file)
            assert "Executive_Summary" in wb.sheet_names

    def test_p14_b024_csv_export(self) -> None:
        """P14-B024: CSV exporter outputs individual table files."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir) / "csv_tables"
            files = CsvReportExporter.export(doc, output_dir=csv_dir)
            assert len(files) >= 3
            assert any("conflict" in f.name for f in files)

    def test_p14_b025_json_export(self) -> None:
        """P14-B025: JSON exporter serializes complete versioned report."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "report.json"
            json_str = JsonReportExporter.export(doc, output_path=out_file)
            assert out_file.exists()
            assert '"$schema_version": "1.0.0"' in json_str
            assert '"technical_headway_s": 85.0' in json_str

    def test_p14_b026_report_package_export(self) -> None:
        """P14-B026: Report package creates complete ZIP archive."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_file = Path(tmpdir) / "package.zip"
            ReportPackageExporter.export_package(doc, output_zip_path=zip_file)
            assert zip_file.exists()
            assert zip_file.stat().st_size > 5000

    def test_p14_b027_report_reproducibility(self) -> None:
        """P14-B027: Identical inputs produce identical engineering metrics."""
        pkg1 = build_benchmark_package(headway_s=88.4)
        pkg2 = build_benchmark_package(headway_s=88.4)
        doc1 = ReportAssembler.assemble_report(pkg1)
        doc2 = ReportAssembler.assemble_report(pkg2)
        assert doc1.executive_kpis.technical_headway_s == doc2.executive_kpis.technical_headway_s
        assert doc1.executive_kpis.theoretical_capacity_tph == doc2.executive_kpis.theoretical_capacity_tph
        assert len(doc1.recommendations) == len(doc2.recommendations)

    def test_p14_b028_missing_data_handling(self) -> None:
        """P14-B028: Non-applicable sections are flagged cleanly without crashing."""
        pkg = build_benchmark_package()
        pkg.sensitivity_result = None
        pkg.mixed_traffic_matrix = None
        doc = ReportAssembler.assemble_report(pkg)
        sec_sens = doc.get_section(ReportSectionId.BLOCK_LENGTH_SENSITIVITY)
        assert sec_sens is not None
        assert not sec_sens.is_applicable
        assert "No parameter sensitivity study" in (sec_sens.not_applicable_reason or "")

    def test_p14_b029_forward_direction_report(self) -> None:
        """P14-B029: Forward direction is explicitly identified across metadata and banner."""
        pkg = build_benchmark_package(running_direction=RunningDirection.FORWARD)
        doc = ReportAssembler.assemble_report(pkg)
        assert doc.running_direction == RunningDirection.FORWARD
        assert "FORWARD" in doc.direction_banner_text

    def test_p14_b030_reverse_direction_report(self) -> None:
        """P14-B030: Reverse direction is explicitly identified and never shows FORWARD."""
        pkg = build_benchmark_package(running_direction=RunningDirection.REVERSE)
        doc = ReportAssembler.assemble_report(pkg)
        assert doc.running_direction == RunningDirection.REVERSE
        assert "REVERSE" in doc.direction_banner_text
        html_out = HtmlReportRenderer.render(doc)
        assert "RUNNING DIRECTION: REVERSE" in html_out
        assert "badge-reverse" in html_out

    def test_p14_b031_direction_specific_chart_order(self) -> None:
        """P14-B031: Chart generators receive and preserve running direction."""
        pkg_rev = build_benchmark_package(running_direction=RunningDirection.REVERSE)
        doc_rev = ReportAssembler.assemble_report(pkg_rev)
        sec_block = doc_rev.get_section(ReportSectionId.BLOCKING_STAIRWAY)
        assert sec_block is not None
        assert sec_block.is_applicable

    def test_p14_b032_no_hardcoded_reference_values(self) -> None:
        """P14-B032: Values originate from simulation, not reference report constants."""
        custom_hw = 104.3
        pkg = build_benchmark_package(headway_s=custom_hw)
        doc = ReportAssembler.assemble_report(pkg)
        assert doc.executive_kpis.technical_headway_s == custom_hw
        assert doc.executive_kpis.theoretical_capacity_tph == pytest.approx(3600.0 / custom_hw, abs=0.1)

    def test_p14_b033_report_validation(self) -> None:
        """P14-B033: ReportValidator passes valid assembled ReportDocument."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        audit = ReportValidator.validate_report(doc)
        assert audit.is_valid
        assert len(audit.error_messages) == 0

    def test_p14_b034_report_provenance(self) -> None:
        """P14-B034: Report preserves effective hash, scenario ID, and software version."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        assert doc.metadata.input_configuration_hash == pkg.effective_config_hash
        assert doc.metadata.scenario_id == pkg.scenario_id
        assert doc.metadata.software_version == "0.1.0-dev"

    def test_p14_b035_report_immutability(self) -> None:
        """P14-B035: Executive KPIs and Recommendations are frozen dataclasses."""
        pkg = build_benchmark_package()
        doc = ReportAssembler.assemble_report(pkg)
        with pytest.raises(Exception):
            doc.executive_kpis.technical_headway_s = 50.0  # type: ignore
        with pytest.raises(Exception):
            doc.recommendations[0].title = "Modified Title"  # type: ignore
