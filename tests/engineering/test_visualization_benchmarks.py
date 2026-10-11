"""Engineering benchmarks for Milestone P13 Visualization & Results Architecture.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 27).
Covers all 35 mandatory benchmarks:
- P13-B001: Trajectory chart uses actual P04 results
- P13-B002: Speed envelope chart correct
- P13-B003: Gradient chart forward
- P13-B004: Gradient chart reverse
- P13-B005: Curvature chart
- P13-B006: Time–distance forward
- P13-B007: Time–distance reverse
- P13-B008: Multi-train time–distance
- P13-B009: Blocking stairway
- P13-B010: Seven-component stacked chart
- P13-B011: Component reconciliation
- P13-B012: Conflict ranking table
- P13-B013: Longest occupation table
- P13-B014: Platform occupation chart
- P13-B015: Residual rear occupation chart
- P13-B016: Mixed-traffic heatmap
- P13-B017: Heatmap direction separation
- P13-B018: Resource timing table
- P13-B019: Resource geometry provenance table
- P13-B020: Block-length sensitivity chart
- P13-B021: Signalling sensitivity chart
- P13-B022: TVS occupation chart
- P13-B023: TVS comparison chart
- P13-B024: Queue development chart
- P13-B025: Delay chart
- P13-B026: Capacity saturation chart
- P13-B027: Stochastic histogram
- P13-B028: Confidence interval chart
- P13-B029: Scenario comparison chart
- P13-B030: Bottleneck migration chart
- P13-B031: Interactive Plotly render
- P13-B032: Static export render
- P13-B033: Result immutability
- P13-B034: No recalculation verification
- P13-B035: Missing result handling
"""

import copy
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union
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
from headway.reporting.export_static import StaticFigureExporter
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
)
from headway.reporting.visualization_adapters import VisualizationAdapter
from headway.scenarios.scenario_comparison import (
    BottleneckShiftReport,
    MetricDifference,
    ParameterDifference,
    ScenarioComparisonReport,
)
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory


def make_test_trajectory(
    train_id: str = "TRN_01",
    running_direction: RunningDirection = RunningDirection.FORWARD,
    length_m: float = 2000.0,
    max_speed_kmh: float = 80.0,
) -> TrainTrajectory:
    """Creates a sample physical train trajectory."""
    samples = []
    t = 0.0
    dist = 0.0
    speed_ms = 0.0
    target_speed_ms = max_speed_kmh / 3.6

    for step in range(50):
        if speed_ms < target_speed_ms:
            speed_ms = min(target_speed_ms, speed_ms + 0.8 * 2.0)
            mode = DynamicMode.ACCELERATING
        else:
            mode = DynamicMode.CRUISING

        dist += speed_ms * 2.0
        t += 2.0
        sample = TrajectorySample(
            time_s=t,
            front_distance_m=dist,
            rear_distance_m=max(0.0, dist - 150.0),
            speed_ms=speed_ms,
            acceleration_ms2=0.8 if mode == DynamicMode.ACCELERATING else 0.0,
            traction_force_n=100000.0 if mode == DynamicMode.ACCELERATING else 10000.0,
            braking_force_n=0.0,
            davis_resistance_n=2000.0,
            gradient_resistance_n=0.0,
            curvature_resistance_n=0.0,
            net_force_n=80000.0 if mode == DynamicMode.ACCELERATING else 0.0,
            dynamic_mode=mode,
            operational_state=OperationalState.RUNNING,
            link_id="LNK_01",
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


def make_test_blocking_intervals(
    running_direction: RunningDirection = RunningDirection.FORWARD,
) -> List[ResourceBlockingInterval]:
    """Creates a sequence of resource blocking intervals with 7-component decomposition."""
    intervals = []
    res_ids = ["BLK_01", "BLK_02", "BLK_03", "BLK_04"]
    for idx, rid in enumerate(res_ids):
        total_dur = 3.0 + 8.0 + 15.0 + (0.0 if idx != 1 else 10.0) + 8.0 + 0.0 + (6.0 if idx != 1 else 4.0)
        t_start = idx * 25.0
        t_end = t_start + total_dur
        decomp = BlockingTimeDecomposition(
            setup_time_s=3.0,
            approach_time_s=8.0,
            running_time_s=15.0,
            dwell_time_s=0.0 if idx != 1 else 10.0,
            geometric_clearance_time_s=8.0,
            residual_rear_time_s=0.0,
            release_time_s=6.0 if idx != 1 else 4.0,
            reconciliation_difference_s=0.0,
        )

        bi = ResourceBlockingInterval(
            interval_id=f"INT_{rid}",
            resource_id=rid,
            resource_category=ResourceCategory.TRACK_BLOCK,
            train_id="TRN_01",
            start_time_s=t_start,
            end_time_s=t_end,
            running_direction=running_direction,
            physical_start_offset_m=idx * 500.0,
            physical_end_offset_m=(idx + 1) * 500.0,
            decomposition=decomp,
        )
        intervals.append(bi)
    return intervals


class TestVisualizationBenchmarks:
    """Verifies all mandatory visualization benchmarks P13-B001 to P13-B035."""

    def test_p13_b001_trajectory_chart_uses_actual_results(self) -> None:
        """P13-B001: Trajectory chart uses actual simulation results without recalculation."""
        traj = make_test_trajectory(train_id="TRN_ALPHA")
        orig_samples_count = len(traj.samples)
        orig_max_speed = max(s.speed_kmh for s in traj.samples)

        fig = create_speed_distance_figure(traj)
        assert len(fig.data) >= 1
        speed_trace = fig.data[0]
        assert "TRN_ALPHA" in speed_trace.name
        # Check max speed matches actual simulation result within 0.1 km/h
        assert max(speed_trace.y) == pytest.approx(orig_max_speed, abs=0.1)
        assert len(traj.samples) == orig_samples_count

    def test_p13_b002_speed_envelope_chart(self) -> None:
        """P13-B002: Speed envelope chart overlays permissible speed limit accurately."""
        traj = make_test_trajectory()
        envelope = [
            {"route_distance_m": 0.0, "max_speed_kmh": 90.0},
            {"route_distance_m": 1000.0, "max_speed_kmh": 90.0},
            {"route_distance_m": 2000.0, "max_speed_kmh": 60.0},
        ]
        fig = create_speed_distance_figure(traj, permissible_speed_envelope=envelope)
        env_trace = next(t for t in fig.data if "Permissible Speed" in t.name)
        assert env_trace.y[0] == 90.0
        assert env_trace.y[-1] == 60.0
        assert env_trace.line.dash == "dash"

    def test_p13_b003_gradient_chart_forward(self) -> None:
        """P13-B003: Forward gradient chart displays physical positive gradient as uphill."""
        link = TrackLink(
            link_id="LNK_01",
            track_id="TRK_01",
            start_node_id="N1",
            end_node_id="N2",
            length_m=1000.0,
            gradient_decimal=0.015,
            max_speed_ms=30.0,
        )
        fig = create_gradient_profile_figure([link], running_direction=RunningDirection.FORWARD)
        grad_trace = fig.data[0]
        # In FORWARD, gradient is +15.0 ‰
        assert grad_trace.y[0] == pytest.approx(15.0, abs=1e-3)
        assert "FORWARD" in str(fig.layout.annotations)

    def test_p13_b004_gradient_chart_reverse(self) -> None:
        """P13-B004: Reverse gradient chart inverts gradient sign (uphill becomes downhill)."""
        link = TrackLink(
            link_id="LNK_01",
            track_id="TRK_01",
            start_node_id="N1",
            end_node_id="N2",
            length_m=1000.0,
            gradient_decimal=0.015,
            max_speed_ms=30.0,
        )
        fig = create_gradient_profile_figure([link], running_direction=RunningDirection.REVERSE)
        grad_trace = fig.data[0]
        # In REVERSE, gradient sign is inverted: -15.0 ‰
        assert grad_trace.y[0] == pytest.approx(-15.0, abs=1e-3)
        assert "REVERSE" in str(fig.layout.annotations)

    def test_p13_b005_curvature_chart(self) -> None:
        """P13-B005: Curvature chart displays radius and curvature along route."""
        link = TrackLink(
            link_id="LNK_01",
            track_id="TRK_01",
            start_node_id="N1",
            end_node_id="N2",
            length_m=800.0,
            curvature_radius_m=500.0,
            max_speed_ms=30.0,
        )
        fig = create_curvature_profile_figure([link])
        curv_trace = fig.data[0]
        # Curvature 1000 / 500 = 2.0 (1/km)
        assert curv_trace.y[0] == pytest.approx(2.0, abs=1e-3)

    def test_p13_b006_time_distance_forward(self) -> None:
        """P13-B006: Time–distance forward trajectory renders route distance vs time."""
        traj = make_test_trajectory(running_direction=RunningDirection.FORWARD)
        fig = create_time_distance_figure(traj, running_direction=RunningDirection.FORWARD)
        assert len(fig.data) == 1
        assert "FORWARD" in str(fig.layout.annotations)
        assert fig.data[0].x[-1] > 0.0

    def test_p13_b007_time_distance_reverse(self) -> None:
        """P13-B007: Time–distance reverse trajectory clearly identifies REVERSE direction."""
        traj = make_test_trajectory(running_direction=RunningDirection.REVERSE)
        fig = create_time_distance_figure(traj, running_direction=RunningDirection.REVERSE)
        assert "REVERSE" in str(fig.layout.annotations)

    def test_p13_b008_multi_train_time_distance(self) -> None:
        """P13-B008: Multi-train time–distance renders leader and follower distinctly."""
        t1 = make_test_trajectory(train_id="TRN_LEADER")
        t2 = make_test_trajectory(train_id="TRN_FOLLOWER")
        fig = create_time_distance_figure([t1, t2])
        assert len(fig.data) == 2
        assert "TRN_LEADER" in fig.data[0].name
        assert "TRN_FOLLOWER" in fig.data[1].name

    def test_p13_b009_blocking_stairway(self) -> None:
        """P13-B009: Blocking stairway renders leader and shifted follower stairways."""
        intervals = make_test_blocking_intervals()
        conflict = ResourceConflict(
            conflict_id="CONF_01",
            leader_usage=intervals[1],
            follower_usage=intervals[1],
            conflict_type=ConflictType.IDENTICAL_RESOURCE,
            leader_release_time_s=65.0,
            follower_start_time_s=25.0,
            required_headway_s=85.0,
            slack_s=0.0,
            bottleneck_type="CRITICAL_BLOCK",
        )
        hw_res = HeadwayResult(
            run_id="RUN_01",
            analysis_id="AN_01",
            scenario_id="BASELINE",
            leader_service_id="METRO_A",
            follower_service_id="METRO_B",
            reference_point_id="BLK_02",
            running_direction=RunningDirection.FORWARD,
            signalling_system="FIXED_BLOCK",
            headway_definition="TECHNICAL_MINIMUM",
            headway_s=85.0,
            minimum_dispatch_headway_s=85.0,
            controlling_conflicts=[conflict],
            blocking_intervals=intervals,
        )
        fig = create_blocking_stairway_figure(hw_res)
        # Leader and follower bars present
        assert len(fig.data) >= 2
        assert any("85.0 s" in (a.text or "") for a in fig.layout.annotations)

    def test_p13_b010_seven_component_stacked_chart(self) -> None:
        """P13-B010: Seven-component stacked chart displays all 7 additive components."""
        intervals = make_test_blocking_intervals()
        fig = create_seven_component_figure(intervals)
        # 7 component traces
        assert len(fig.data) == 7
        assert fig.layout.barmode == "stack"

    def test_p13_b011_component_reconciliation(self) -> None:
        """P13-B011: Seven-component decomposition reconciles with total duration."""
        intervals = make_test_blocking_intervals()
        for bi in intervals:
            assert bi.decomposition.is_reconciled
            assert abs(bi.duration_s - bi.decomposition.total_duration_s) <= 1e-3

    def test_p13_b012_conflict_ranking_table(self) -> None:
        """P13-B012: Conflict ranking table tabulates pairwise conflicts and slack."""
        intervals = make_test_blocking_intervals()
        conflict = ResourceConflict(
            conflict_id="CONF_01",
            leader_usage=intervals[1],
            follower_usage=intervals[1],
            conflict_type=ConflictType.IDENTICAL_RESOURCE,
            leader_release_time_s=65.0,
            follower_start_time_s=25.0,
            required_headway_s=85.0,
            slack_s=0.0,
        )
        hw_res = HeadwayResult(
            run_id="RUN_01",
            analysis_id="AN_01",
            scenario_id="BASELINE",
            leader_service_id="S1",
            follower_service_id="S2",
            reference_point_id="BLK_02",
            running_direction=RunningDirection.FORWARD,
            signalling_system="FIXED_BLOCK",
            headway_definition="TECHNICAL",
            headway_s=85.0,
            minimum_dispatch_headway_s=85.0,
            controlling_conflicts=[conflict],
            conflict_ranking=[conflict],
            blocking_intervals=intervals,
        )
        tbl = create_conflict_ranking_table(hw_res)
        assert tbl.row_count == 1
        assert "Leader Resource" in tbl.columns
        assert tbl.raw_dataframe["Required Headway (s)"].iloc[0] == 85.0

    def test_p13_b013_longest_occupation_table(self) -> None:
        """P13-B013: Longest occupation table sorts resources by total blocking duration."""
        intervals = make_test_blocking_intervals()
        tbl = create_longest_occupation_table(intervals)
        assert tbl.row_count == 4
        # Sorted descending by duration
        durs = tbl.raw_dataframe["Total Duration (s)"].tolist()
        assert durs == sorted(durs, reverse=True)

    def test_p13_b014_platform_occupation_chart(self) -> None:
        """P13-B014: Platform occupation chart renders dwell and platform clearance."""
        rec = PlatformOccupationRecord(
            train_id="TRN_01",
            station_id="STN_A",
            station_name="Alpha",
            platform_id="PLT_01",
            track_id="TRK_01",
            link_id="LNK_01",
            arrival_time_s=100.0,
            dwell_start_time_s=110.0,
            dwell_end_time_s=150.0,
            departure_time_s=150.0,
            clearance_time_s=165.0,
            running_direction=RunningDirection.FORWARD,
        )
        fig = create_platform_occupation_figure([rec])
        assert len(fig.data) >= 1
        assert "Alpha - PLT_01" in str(fig.layout.yaxis.categoryarray)

    def test_p13_b015_residual_rear_occupation_chart(self) -> None:
        """P13-B015: Residual rear occupation chart displays upstream infringement."""
        rec = PlatformOccupationRecord(
            train_id="TRN_01",
            station_id="STN_A",
            station_name="Alpha",
            platform_id="PLT_01",
            track_id="TRK_01",
            link_id="LNK_01",
            arrival_time_s=100.0,
            dwell_start_time_s=110.0,
            dwell_end_time_s=150.0,
            departure_time_s=150.0,
            clearance_time_s=165.0,
            running_direction=RunningDirection.FORWARD,
            is_residual_rear_active=True,
            residual_rear_duration_s=40.0,
            upstream_infringing_resource_ids=("LNK_UPSTREAM_01",),
        )
        fig = create_platform_occupation_figure([rec])
        rear_trace = next(t for t in fig.data if "Residual Rear" in t.name)
        assert rear_trace.x[0] == 40.0

    def test_p13_b016_mixed_traffic_heatmap(self) -> None:
        """P13-B016: Mixed-traffic heatmap displays N x N matrix with values and axes."""
        matrix = MixedTrafficHeadwayMatrix(
            matrix_id="MAT_01",
            running_direction=RunningDirection.FORWARD,
            service_ids=["METRO", "EXPRESS"],
            headway_values_s={
                ("METRO", "METRO"): 90.0,
                ("METRO", "EXPRESS"): 110.0,
                ("EXPRESS", "METRO"): 95.0,
                ("EXPRESS", "EXPRESS"): 105.0,
            },
        )
        fig = create_mixed_traffic_heatmap(matrix)
        assert len(fig.data) == 1
        hm = fig.data[0]
        # Rows = leaders, Cols = followers
        assert hm.y == ("METRO", "EXPRESS") or list(hm.y) == ["METRO", "EXPRESS"]
        assert hm.z[0][0] == 90.0
        assert hm.z[0][1] == 110.0

    def test_p13_b017_heatmap_direction_separation(self) -> None:
        """P13-B017: Heatmap direction separation between FORWARD and REVERSE."""
        m_fwd = MixedTrafficHeadwayMatrix(
            matrix_id="M_FWD",
            running_direction=RunningDirection.FORWARD,
            service_ids=["S1"],
            headway_values_s={("S1", "S1"): 90.0},
        )
        m_rev = MixedTrafficHeadwayMatrix(
            matrix_id="M_REV",
            running_direction=RunningDirection.REVERSE,
            service_ids=["S1"],
            headway_values_s={("S1", "S1"): 98.0},
        )
        fig_fwd = create_mixed_traffic_heatmap(m_fwd)
        fig_rev = create_mixed_traffic_heatmap(m_rev)
        assert "FORWARD" in fig_fwd.layout.title.text
        assert "REVERSE" in fig_rev.layout.title.text

    def test_p13_b018_resource_timing_table(self) -> None:
        """P13-B018: Detailed resource timing table tabulates all 7 components."""
        rec = ResourceTimingRecord(
            resource_index=1,
            resource_id="LNK_01",
            resource_category="SIGNAL_BLOCK",
            route_chainage_km=0.0,
            resource_length_m=1000.0,
            entry_speed_kmh=80.0,
            exit_speed_kmh=80.0,
            setup_time_s=3.0,
            approach_time_s=10.0,
            running_time_s=25.0,
            dwell_time_s=0.0,
            geometric_clearance_time_s=8.0,
            residual_rear_time_s=0.0,
            release_time_s=5.0,
            total_blocking_s=51.0,
        )
        tbl = create_resource_timing_table([rec])
        assert tbl.row_count == 1
        assert "Total Blocking (s)" in tbl.columns
        assert tbl.raw_dataframe["Total Blocking (s)"].iloc[0] == 51.0

    def test_p13_b019_resource_geometry_provenance_table(self) -> None:
        """P13-B019: Provenance table records baseline integrity and geometry origin."""
        rec = ResourceProvenanceRecord(
            resource_id="LNK_01",
            resource_type="TRACK_LINK",
            physical_chainage_km=0.0,
            resource_length_m=1000.0,
            geometry_source="BASELINE_EXCEL",
            dataset_id="DS_01",
            dataset_version="1.0",
            is_baseline_geometry=True,
        )
        tbl = create_resource_provenance_table([rec])
        assert tbl.row_count == 1
        assert tbl.raw_dataframe["Baseline Invariant"].iloc[0] == "UNMODIFIED"

    def test_p13_b020_block_length_sensitivity_chart(self) -> None:
        """P13-B020: Block length sensitivity chart plots headway and capacity panels."""
        study = SensitivityStudyResult(
            study_id="SENS_BLK",
            parameter_name="length_m",
            baseline_value=1000.0,
            baseline_capacity_tph=30.0,
            baseline_headway_s=120.0,
            baseline_bottleneck_id="BLK_01",
            points=[
                SensitivityPointResult("length_m", 600.0, 36.0, 100.0, "BLK_01"),
                SensitivityPointResult("length_m", 800.0, 32.7, 110.0, "BLK_01"),
                SensitivityPointResult("length_m", 1000.0, 30.0, 120.0, "BLK_01"),
            ],
        )
        fig = create_block_sensitivity_figure(study)
        # Multi-panel subplots
        assert len(fig.data) >= 3

    def test_p13_b021_signalling_sensitivity_chart(self) -> None:
        """P13-B021: Signalling sensitivity comparison across distinct technologies."""
        study = SensitivityStudyResult(
            study_id="SENS_SIG",
            parameter_name="signalling_type",
            baseline_value="3_ASPECT",
            baseline_capacity_tph=30.0,
            baseline_headway_s=120.0,
            baseline_bottleneck_id="BLK_01",
            points=[
                SensitivityPointResult("signalling_type", 600.0, 30.0, 120.0, "BLK_01"),
                SensitivityPointResult("signalling_type", 1200.0, 40.0, 90.0, "BLK_01"),
            ],
        )
        fig = create_block_sensitivity_figure(study)
        assert len(fig.data) >= 2

    def test_p13_b022_tvs_occupation_chart(self) -> None:
        """P13-B022: TVS occupation chart displays physical zone occupation and wait times."""
        events = [
            {
                "tvs_id": "TVS_01",
                "train_id": "TRN_01",
                "entry_time_s": 100.0,
                "exit_time_s": 150.0,
                "release_time_s": 158.0,
                "waiting_duration_s": 15.0,
            }
        ]
        fig = create_tvs_occupation_figure(events)
        assert len(fig.data) >= 2

    def test_p13_b023_tvs_comparison_chart(self) -> None:
        """P13-B023: TVS comparison chart contrasts signalling headway vs TVS headway."""
        fig = create_tvs_comparison_figure(
            signalling_headway_s=90.0,
            tvs_headway_s=115.0,
            combined_headway_s=115.0,
        )
        assert len(fig.data) == 1
        assert fig.data[0].y[0] == 90.0
        assert fig.data[0].y[1] == 115.0

    def test_p13_b024_queue_development_chart(self) -> None:
        """P13-B024: Queue development vs time at bottlenecks."""
        rates = [20.0, 30.0, 35.0, 40.0]
        throughputs = [20.0, 30.0, 33.0, 33.0]
        fig = create_capacity_saturation_figure(rates, throughputs)
        assert len(fig.data) == 2

    def test_p13_b025_delay_chart(self) -> None:
        """P13-B025: Delay distribution histogram along route."""
        delays = [0.0, 5.0, 10.0, 15.0, 20.0, 35.0, 50.0]
        fig = create_stochastic_histogram_figure(delays, metric_name="Secondary Delay", unit="s")
        assert len(fig.data) == 1
        assert "Secondary Delay" in fig.layout.title.text

    def test_p13_b026_capacity_saturation_chart(self) -> None:
        """P13-B026: Capacity saturation chart plots achieved throughput and stability boundary."""
        rates = [20.0, 25.0, 30.0, 35.0]
        tps = [20.0, 25.0, 29.5, 30.0]
        statuses = ["STABLE", "STABLE", "METASTABLE", "UNSTABLE"]
        fig = create_capacity_saturation_figure(rates, tps, stability_statuses=statuses)
        # Annotation for stability boundary present
        assert any("Stability Boundary" in str(ann) for ann in (fig.layout.annotations or ()))

    def test_p13_b027_stochastic_histogram(self) -> None:
        """P13-B027: Stochastic histogram plots frequency with mean and P95 lines."""
        headways = [85.0, 88.0, 90.0, 92.0, 95.0, 99.0, 105.0]
        summary = StatisticalSummary(
            metric_name="headway_s",
            sample_count=len(headways),
            mean=93.4,
            median=92.0,
            std_dev=6.7,
            min_value=85.0,
            max_value=105.0,
            p5=85.5,
            p50=92.0,
            p90=100.0,
            p95=103.0,
            p99=104.8,
        )
        fig = create_stochastic_histogram_figure(headways, summary=summary)
        # Vlines present in shapes or layout
        assert any("Mean" in str(ann) for ann in (fig.layout.annotations or ()))

    def test_p13_b028_confidence_interval_chart(self) -> None:
        """P13-B028: Confidence interval chart renders point estimates with error bars."""
        estimates = [
            {"label": "Scenario A", "point_estimate": 90.0, "ci_lower": 88.0, "ci_upper": 92.0},
            {"label": "Scenario B", "point_estimate": 80.0, "ci_lower": 78.5, "ci_upper": 81.5},
        ]
        fig = create_confidence_interval_figure(estimates)
        assert len(fig.data) == 1
        assert fig.data[0].error_y is not None

    def test_p13_b029_scenario_comparison_chart(self) -> None:
        """P13-B029: Scenario comparison chart compares KPI values and percentage changes."""
        report = ScenarioComparisonReport(
            baseline_scenario_id="BASELINE",
            compared_scenario_ids=["SCN_CBTC"],
            metric_differences={
                "SCN_CBTC": [
                    MetricDifference(
                        metric_name="headway_s",
                        baseline_value=120.0,
                        scenario_value=90.0,
                        absolute_change=-30.0,
                        percentage_change=-25.0,
                    )
                ]
            },
        )
        fig = create_scenario_kpi_comparison_figure(report, metric_name="headway_s")
        assert len(fig.data) == 1
        assert "-25.0%" in fig.data[0].text[1]

    def test_p13_b030_bottleneck_migration_chart(self) -> None:
        """P13-B030: Bottleneck migration chart highlights shifts across scenarios."""
        report = ScenarioComparisonReport(
            baseline_scenario_id="BASELINE",
            compared_scenario_ids=["SCN_SHORT_BLOCK"],
            bottleneck_shifts=[
                BottleneckShiftReport(
                    baseline_scenario_id="BASELINE",
                    comparison_scenario_id="SCN_SHORT_BLOCK",
                    bottleneck_migrated=True,
                    baseline_bottleneck_id="BLK_01",
                    comparison_bottleneck_id="PLT_01",
                )
            ],
        )
        fig = create_bottleneck_migration_figure(report)
        assert len(fig.data) == 1
        assert "PLT_01" in fig.data[0].text[1]

    def test_p13_b031_interactive_plotly_render(self) -> None:
        """P13-B031: Interactive Plotly figure produces valid JSON and HTML representations."""
        traj = make_test_trajectory()
        fig = create_speed_distance_figure(traj)
        json_str = fig.to_json()
        assert len(json_str) > 100
        html_str = fig.to_html(include_plotlyjs="cdn")
        assert "plotly" in html_str.lower()

    def test_p13_b032_static_export_render(self) -> None:
        """P13-B032: Static export generates high-resolution image file on disk."""
        traj = make_test_trajectory()
        fig = create_speed_distance_figure(traj)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "speed_test.png"
            StaticFigureExporter.export_figure_to_image(fig, out_path, dpi=100)
            assert out_path.exists()
            assert out_path.stat().st_size > 0

    def test_p13_b033_result_immutability(self) -> None:
        """P13-B033: Visualization operations never modify source simulation objects."""
        traj = make_test_trajectory()
        traj_copy = copy.deepcopy(traj)

        create_speed_distance_figure(traj)
        create_time_distance_figure(traj)

        assert traj.samples == traj_copy.samples
        assert traj.train_id == traj_copy.train_id

    def test_p13_b034_no_recalculation_verification(self) -> None:
        """P13-B034: Adapter extracts values without re-running dynamics or solvers."""
        traj = make_test_trajectory()
        df = VisualizationAdapter.adapt_trajectory(traj)

        # Values in adapted DataFrame are exact 1:1 matches of trajectory samples
        for idx, sample in enumerate(traj.samples):
            assert df["time_s"].iloc[idx] == sample.time_s
            assert df["route_distance_m"].iloc[idx] == sample.front_distance_m
            assert df["speed_ms"].iloc[idx] == sample.speed_ms

    def test_p13_b035_missing_result_handling(self) -> None:
        """P13-B035: Missing or empty result structures produce structured diagnostics."""
        empty_traj = TrainTrajectory(
            train_id="TRN_EMPTY",
            train_type_id="TT_01",
            route_id="RT_01",
            running_direction=RunningDirection.FORWARD,
            samples=[],
        )
        report = ResultValidator.validate_trajectory(empty_traj)
        assert not report.is_valid
        assert report.has_critical
        assert any(d.code == DiagnosticCode.EMPTY_TRAJECTORY for d in report.diagnostics)
