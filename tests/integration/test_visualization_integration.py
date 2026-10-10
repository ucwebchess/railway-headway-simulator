"""Integration tests for Milestone P13 Visualization & Results Architecture.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001).
Tests complete end-to-end visualization workflows:
- End-to-end SimulationResultPackage assembly, validation, figure and table generation
- Directional reversal visualization workflow (FORWARD vs REVERSE)
- Mixed-traffic multi-train time-distance diagrams and headway heatmaps
- Scenario comparison and bottleneck migration visualization workflow
- Stochastic Monte Carlo distribution and reliability visualization workflow
- Multi-format figure (HTML, JSON, PNG) and table (CSV, Excel OOXML, JSON, HTML) export
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
from headway.analysis.statistics import StatisticalSummary
from headway.data.canonical import Platform, Station, TrackLink, TVSSection, ResourceInterval
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import ChartColors
from headway.reporting.charts_blocking import (
    create_blocking_stairway_figure,
    create_seven_component_figure,
)
from headway.reporting.charts_capacity import (
    create_block_sensitivity_figure,
    create_capacity_saturation_figure,
)
from headway.reporting.charts_headway import (
    create_mixed_traffic_heatmap,
    create_time_distance_figure,
)
from headway.reporting.charts_scenario import (
    create_bottleneck_migration_figure,
    create_scenario_kpi_comparison_figure,
)
from headway.reporting.charts_speed import (
    create_curvature_profile_figure,
    create_gradient_profile_figure,
    create_speed_distance_figure,
    create_track_alignment_combined_figure,
)
from headway.reporting.charts_station import create_platform_occupation_figure
from headway.reporting.charts_stochastic import (
    create_confidence_interval_figure,
    create_stochastic_histogram_figure,
)
from headway.reporting.charts_tvs import (
    create_tvs_comparison_figure,
    create_tvs_occupation_figure,
)
from headway.reporting.export_static import StaticFigureExporter, export_figure_headless
from headway.reporting.result_models import (
    PlatformOccupationRecord,
    ResourceProvenanceRecord,
    ResourceTimingRecord,
    SimulationResultPackage,
    StationStopRecord,
)
from headway.reporting.result_validation import DiagnosticCode, ResultValidator
from headway.reporting.tables import (
    create_conflict_ranking_table,
    create_headway_matrix_table,
    create_longest_occupation_table,
    create_resource_provenance_table,
    create_resource_timing_table,
    create_scenario_comparison_table,
    create_station_stopping_table,
    export_table,
)
from headway.reporting.visualization_adapters import VisualizationAdapter
from headway.scenarios.scenario_comparison import (
    BottleneckShiftReport,
    MetricDifference,
    ScenarioComparisonReport,
)
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory


def build_synthetic_trajectory(
    train_id: str,
    running_direction: RunningDirection = RunningDirection.FORWARD,
    max_speed_kmh: float = 100.0,
) -> TrainTrajectory:
    """Helper to build realistic physical trajectory with cruising and braking."""
    samples = []
    t = 0.0
    dist = 0.0 if running_direction == RunningDirection.FORWARD else 4000.0
    speed_ms = 0.0
    target_speed = max_speed_kmh / 3.6

    for step in range(40):
        if step < 15:
            speed_ms = min(target_speed, speed_ms + 1.0 * 2.0)
            mode = DynamicMode.ACCELERATING
        elif step < 30:
            speed_ms = target_speed
            mode = DynamicMode.CRUISING
        else:
            speed_ms = max(0.0, speed_ms - 1.2 * 2.0)
            mode = DynamicMode.SERVICE_BRAKING

        delta_d = speed_ms * 2.0
        if running_direction == RunningDirection.FORWARD:
            dist += delta_d
        else:
            dist -= delta_d

        t += 2.0
        sample = TrajectorySample(
            time_s=t,
            front_distance_m=dist,
            rear_distance_m=max(0.0, dist - 120.0),
            speed_ms=speed_ms,
            acceleration_ms2=1.0 if mode == DynamicMode.ACCELERATING else (-1.2 if mode == DynamicMode.SERVICE_BRAKING else 0.0),
            traction_force_n=100000.0 if mode == DynamicMode.ACCELERATING else 0.0,
            braking_force_n=120000.0 if mode == DynamicMode.SERVICE_BRAKING else 0.0,
            davis_resistance_n=2000.0,
            gradient_resistance_n=0.0,
            curvature_resistance_n=0.0,
            net_force_n=0.0,
            dynamic_mode=mode,
            operational_state=OperationalState.RUNNING if speed_ms > 0 else OperationalState.STOPPED,
            link_id="TL_01",
            physical_coordinate_m=dist,
        )
        samples.append(sample)

    return TrainTrajectory(
        train_id=train_id,
        train_type_id="TT_EXPRESS",
        route_id="RT_MAIN",
        running_direction=running_direction,
        samples=samples,
    )


def build_synthetic_blocking_intervals(
    running_direction: RunningDirection = RunningDirection.FORWARD,
) -> List[ResourceBlockingInterval]:
    """Helper to build 4 sequenced blocking intervals."""
    intervals = []
    for idx, rid in enumerate(["BLK_01", "BLK_02", "BLK_03", "BLK_04"]):
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
                train_id="TRN_LEADER",
                start_time_s=t_start,
                end_time_s=t_end,
                running_direction=running_direction,
                physical_start_offset_m=idx * 600.0,
                physical_end_offset_m=(idx + 1) * 600.0,
                decomposition=decomp,
            )
        )
    return intervals


class TestVisualizationIntegrationPipeline:
    """End-to-end integration test suite for Milestone P13."""

    def test_end_to_end_simulation_result_package_pipeline(self) -> None:
        """Assembles comprehensive result package, validates it, and generates all views."""
        traj_leader = build_synthetic_trajectory("TRN_LEADER", RunningDirection.FORWARD)
        traj_follower = build_synthetic_trajectory("TRN_FOLLOWER", RunningDirection.FORWARD)
        blocking_intervals = build_synthetic_blocking_intervals(RunningDirection.FORWARD)

        conflict = ResourceConflict(
            conflict_id="CONF_BLK2",
            leader_usage=blocking_intervals[1],
            follower_usage=blocking_intervals[1],
            conflict_type=ConflictType.IDENTICAL_RESOURCE,
            leader_release_time_s=blocking_intervals[1].end_time_s,
            follower_start_time_s=blocking_intervals[1].start_time_s + 10.0,
            required_headway_s=88.0,
            slack_s=0.0,
            bottleneck_type="CRITICAL_BLOCK",
        )

        hw_result = HeadwayResult(
            run_id="RUN_INTEG_01",
            analysis_id="AN_INTEG_01",
            scenario_id="SCEN_BASELINE",
            leader_service_id="METRO_A",
            follower_service_id="METRO_B",
            reference_point_id="BLK_02",
            running_direction=RunningDirection.FORWARD,
            signalling_system="FIXED_BLOCK_3ASPECT",
            headway_definition="TECHNICAL_MINIMUM",
            headway_s=88.0,
            minimum_dispatch_headway_s=88.0,
            controlling_conflicts=[conflict],
            conflict_ranking=[conflict],
            blocking_intervals=blocking_intervals,
        )

        mt_matrix = MixedTrafficHeadwayMatrix(
            matrix_id="MT_INTEG",
            running_direction=RunningDirection.FORWARD,
            service_ids=["METRO_A", "METRO_B"],
            headway_values_s={
                ("METRO_A", "METRO_A"): 88.0,
                ("METRO_A", "METRO_B"): 95.0,
                ("METRO_B", "METRO_A"): 92.0,
                ("METRO_B", "METRO_B"): 88.0,
            },
            controlling_bottlenecks={
                ("METRO_A", "METRO_A"): "BLK_02",
                ("METRO_A", "METRO_B"): "BLK_02",
                ("METRO_B", "METRO_A"): "BLK_03",
                ("METRO_B", "METRO_B"): "BLK_02",
            },
        )

        pkg = SimulationResultPackage(
            run_id="RUN_INTEG_01",
            scenario_id="SCEN_BASELINE",
            effective_config_hash="sha256_abcdef123456",
            running_direction=RunningDirection.FORWARD,
            trajectories={"TRN_LEADER": traj_leader, "TRN_FOLLOWER": traj_follower},
            headway_results={"METRO_A->METRO_B": hw_result},
            mixed_traffic_matrix=mt_matrix,
            blocking_intervals=blocking_intervals,
        )

        # 1. Result Validation
        report = ResultValidator.validate_result_package(pkg)
        assert report.is_valid
        assert len(report.error_messages) == 0

        # 2. Charts Generation
        fig_speed = create_speed_distance_figure(traj_leader)
        assert fig_speed is not None
        assert len(fig_speed.data) >= 1

        fig_stairway = create_blocking_stairway_figure(hw_result)
        assert fig_stairway is not None
        assert len(fig_stairway.data) >= 2

        fig_seven = create_seven_component_figure(blocking_intervals)
        assert fig_seven is not None
        assert len(fig_seven.data) == 7

        fig_td = create_time_distance_figure([traj_leader, traj_follower])
        assert fig_td is not None
        assert len(fig_td.data) == 2

        fig_mt = create_mixed_traffic_heatmap(mt_matrix)
        assert fig_mt is not None
        assert len(fig_mt.data) == 1

        # 3. Engineering Tables Generation
        tbl_conflicts = create_conflict_ranking_table(hw_result)
        assert tbl_conflicts.row_count == 1
        assert "CONTROLLING" in tbl_conflicts.formatted_dataframe["Classification"].iloc[0]

        tbl_longest = create_longest_occupation_table(blocking_intervals)
        assert tbl_longest.row_count == 4

        tbl_timing = create_resource_timing_table(blocking_intervals)
        assert tbl_timing.row_count == 4

        tbl_mt = create_headway_matrix_table(mt_matrix)
        assert tbl_mt.row_count == 2

        # 4. Exporters check
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            html_path = tmp_path / "speed.html"
            json_path = tmp_path / "speed.json"
            png_path = tmp_path / "speed.png"

            StaticFigureExporter.export_plotly_to_html(fig_speed, html_path)
            assert html_path.exists() and html_path.stat().st_size > 0

            StaticFigureExporter.export_plotly_to_json(fig_speed, json_path)
            assert json_path.exists() and json_path.stat().st_size > 0

            export_figure_headless(fig_speed, png_path)
            assert png_path.exists() and png_path.stat().st_size > 0

            # Table exports
            csv_path = tmp_path / "conflicts.csv"
            xlsx_path = tmp_path / "conflicts.xlsx"
            export_table(tbl_conflicts, csv_path)
            export_table(tbl_conflicts, xlsx_path)
            assert csv_path.exists() and csv_path.stat().st_size > 0
            assert xlsx_path.exists() and xlsx_path.stat().st_size > 0

    def test_directional_reversal_workflow(self) -> None:
        """Validates that REVERSE direction inverts gradient sign and updates banner."""
        links = [
            TrackLink(
                link_id="TL_REV_01",
                track_id="TRK_01",
                start_node_id="N_B",
                end_node_id="N_A",
                length_m=1000.0,
                gradient_decimal=0.015,  # +15 permille in forward
                curvature_radius_m=800.0,
                max_speed_ms=33.3,
            )
        ]

        # Reverse gradient adaptation
        grad_fwd = VisualizationAdapter.adapt_gradient_profile(links, RunningDirection.FORWARD)
        grad_rev = VisualizationAdapter.adapt_gradient_profile(links, RunningDirection.REVERSE)

        assert grad_fwd["effective_gradient_per_mille"].iloc[0] == 15.0
        assert grad_rev["effective_gradient_per_mille"].iloc[0] == -15.0

        fig_rev_grad = create_gradient_profile_figure(links, RunningDirection.REVERSE)
        assert any("Running Direction: REVERSE" in (a.text or "") for a in fig_rev_grad.layout.annotations)

    def test_scenario_comparison_and_migration_workflow(self) -> None:
        """Verifies multi-scenario KPI comparison and bottleneck shift diagrams."""
        diff_cbtc = MetricDifference(
            metric_name="headway_s",
            baseline_value=120.0,
            scenario_value=75.0,
            absolute_change=-45.0,
            percentage_change=-37.5,
        )
        diff_short = MetricDifference(
            metric_name="headway_s",
            baseline_value=120.0,
            scenario_value=90.0,
            absolute_change=-30.0,
            percentage_change=-25.0,
        )
        shift_cbtc = BottleneckShiftReport(
            baseline_scenario_id="BASELINE_FIXED",
            comparison_scenario_id="SCN_CBTC",
            bottleneck_migrated=True,
            baseline_bottleneck_id="BLK_02",
            comparison_bottleneck_id="BLK_04",
        )

        report = ScenarioComparisonReport(
            baseline_scenario_id="BASELINE_FIXED",
            compared_scenario_ids=["SCN_CBTC", "SCN_SHORT"],
            metric_differences={
                "SCN_CBTC": [diff_cbtc],
                "SCN_SHORT": [diff_short],
            },
            bottleneck_shifts=[shift_cbtc],
        )

        fig_kpi = create_scenario_kpi_comparison_figure(report, metric_name="headway_s")
        assert len(fig_kpi.data) == 1
        assert len(fig_kpi.data[0].x) == 3  # Baseline, SCN_CBTC, SCN_SHORT

        fig_mig = create_bottleneck_migration_figure(report)
        assert len(fig_mig.data) == 1

        tbl_cmp = create_scenario_comparison_table(report)
        assert tbl_cmp.row_count == 2
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "comparison.csv"
            export_table(tbl_cmp, csv_path)
            assert csv_path.exists() and csv_path.stat().st_size > 0

    def test_stochastic_distribution_workflow(self) -> None:
        """Verifies Monte Carlo stochastic distribution histogram and confidence intervals."""
        sample_headways = [85.0 + (i % 7) * 1.5 for i in range(100)]
        stat = StatisticalSummary(
            metric_name="headway_s",
            sample_count=100,
            mean=89.5,
            median=89.5,
            std_dev=3.2,
            min_value=85.0,
            max_value=94.0,
            p5=85.5,
            p50=89.5,
            p90=93.5,
            p95=94.0,
            p99=94.0,
        )

        fig_hist = create_stochastic_histogram_figure(sample_headways, summary=stat)
        assert len(fig_hist.data) >= 1

        estimates = [
            {"label": "Baseline", "point_estimate": stat.mean, "ci_lower": 87.0, "ci_upper": 92.0}
        ]
        fig_ci = create_confidence_interval_figure(estimates)
        assert len(fig_ci.data) >= 1
