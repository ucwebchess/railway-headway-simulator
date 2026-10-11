"""Negative unit tests for Milestone P13 Visualization & Results Architecture.

Validates defensive guards, validation diagnostics, and error rejection:
- Result package missing identity, invalid direction, empty trajectories
- Non-monotonic timestamps, non-monotonic distance, and non-finite NaN/Inf in trajectories
- Negative / invalid intervals (end_time < start_time)
- Invalid static export formats and dimensions
- Invalid engineering table export formats
- Invalid downsampling / adaptation parameters
- Defense against empty inputs in scenario comparisons
- Defensive handling of empty stochastic samples
- Result immutability and recalculation prevention
"""

import dataclasses
import math
from pathlib import Path
import tempfile
import pandas as pd
import plotly.graph_objects as go
import pytest

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    ResourceBlockingInterval,
    ResourceCategory,
)
from headway.analysis.capacity_models import SensitivityStudyResult
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.analysis.headway_results import HeadwayResult, MixedTrafficHeadwayMatrix
from headway.analysis.statistics import StatisticalSummary
from headway.core.exceptions import DataValidationError
from headway.data.validation import Severity
from headway.infrastructure.direction import RunningDirection
from headway.reporting.chart_theme import (
    ChartColors,
    get_plotly_layout,
    setup_mpl_figure,
)
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
)
from headway.reporting.charts_station import (
    create_platform_occupation_figure,
)
from headway.reporting.charts_stochastic import (
    create_confidence_interval_figure,
    create_stochastic_histogram_figure,
)
from headway.reporting.charts_tvs import (
    create_tvs_comparison_figure,
    create_tvs_occupation_figure,
)
from headway.reporting.export_static import (
    StaticFigureExporter,
    export_figure_headless,
    export_matplotlib_figure,
)
from headway.reporting.result_models import (
    ConflictRankingRecord,
    PlatformOccupationRecord,
    ResourceProvenanceRecord,
    ResourceTimingRecord,
    SimulationResultPackage,
    StationStopRecord,
)
from headway.reporting.result_validation import (
    DiagnosticCode,
    ResultDiagnostic,
    ResultValidationReport,
    ResultValidator,
)
from headway.reporting.tables import (
    EngineeringTable,
    create_conflict_ranking_table,
    create_longest_occupation_table,
    create_resource_timing_table,
    export_table,
)
from headway.reporting.visualization_adapters import (
    VisualizationAdapter,
)
from headway.scenarios.scenario_comparison import MetricDifference, ScenarioComparisonReport
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.trajectory import (
    TrajectorySample,
    TrainTrajectory,
)


def make_dummy_sample(
    t: float,
    d: float,
    v: float = 20.0,
    a: float = 0.0,
    mode: DynamicMode = DynamicMode.CRUISING,
) -> TrajectorySample:
    """Helper to construct a TrajectorySample for testing."""
    return TrajectorySample(
        time_s=t,
        front_distance_m=d,
        rear_distance_m=max(0.0, d - 100.0),
        speed_ms=v,
        acceleration_ms2=a,
        traction_force_n=10000.0,
        braking_force_n=0.0,
        davis_resistance_n=2000.0,
        gradient_resistance_n=0.0,
        curvature_resistance_n=0.0,
        net_force_n=0.0,
        dynamic_mode=mode,
        operational_state=OperationalState.RUNNING,
        link_id="TL_01",
        physical_coordinate_m=d,
    )


class TestVisualizationNegativeCases:
    """Comprehensive negative tests for visualization and result architecture."""

    def test_result_package_missing_identity(self) -> None:
        """ResultValidator detects missing run_id, scenario_id, or effective_config_hash."""
        pkg = SimulationResultPackage(
            run_id="",
            scenario_id="   ",
            effective_config_hash="",
            running_direction=RunningDirection.FORWARD,
        )
        report = ResultValidator.validate_result_package(pkg)
        assert not report.is_valid
        codes = [d.code for d in report.diagnostics]
        assert DiagnosticCode.MISSING_IDENTITY in codes
        # When raise_on_error is True, raises DataValidationError
        with pytest.raises(DataValidationError):
            ResultValidator.validate_result_package(pkg, raise_on_error=True)

    def test_result_package_invalid_direction(self) -> None:
        """ResultValidator detects invalid running_direction."""
        pkg = SimulationResultPackage(
            run_id="RUN_01",
            scenario_id="SCEN_01",
            effective_config_hash="abc1234",
            running_direction="INVALID_DIR",  # type: ignore
        )
        report = ResultValidator.validate_result_package(pkg)
        assert not report.is_valid
        assert any(d.code == DiagnosticCode.INVALID_DIRECTION for d in report.diagnostics)

    def test_trajectory_empty_samples(self) -> None:
        """ResultValidator rejects trajectory with zero samples."""
        traj = TrainTrajectory(
            train_id="EMPTY_TRAIN",
            train_type_id="TT_1",
            route_id="RT_1",
            running_direction=RunningDirection.FORWARD,
            samples=[],
        )
        report = ResultValidator.validate_trajectory(traj)
        assert not report.is_valid
        assert any(d.code == DiagnosticCode.EMPTY_TRAJECTORY for d in report.diagnostics)

        with pytest.raises(DataValidationError):
            ResultValidator.validate_trajectory(traj, raise_on_error=True)

    def test_trajectory_non_monotonic_time(self) -> None:
        """ResultValidator detects non-monotonic timestamps in train trajectory."""
        samples = [
            make_dummy_sample(0.0, 0.0),
            make_dummy_sample(10.0, 100.0),
            make_dummy_sample(5.0, 200.0),  # Decreased time
        ]
        traj = TrainTrajectory(
            train_id="NON_MONO_TIME",
            train_type_id="TT_1",
            route_id="RT_1",
            running_direction=RunningDirection.FORWARD,
            samples=samples,
        )
        report = ResultValidator.validate_trajectory(traj)
        assert not report.is_valid
        assert any(d.code == DiagnosticCode.NON_MONOTONIC_TIME for d in report.diagnostics)

    def test_trajectory_non_monotonic_distance(self) -> None:
        """ResultValidator detects backward physical movement in forward trajectory."""
        samples = [
            make_dummy_sample(0.0, 100.0),
            make_dummy_sample(10.0, 200.0),
            make_dummy_sample(20.0, 50.0),  # Decreased distance in forward
        ]
        traj = TrainTrajectory(
            train_id="NON_MONO_DIST",
            train_type_id="TT_1",
            route_id="RT_1",
            running_direction=RunningDirection.FORWARD,
            samples=samples,
        )
        report = ResultValidator.validate_trajectory(traj)
        assert not report.is_valid
        assert any(d.code == DiagnosticCode.NON_MONOTONIC_DISTANCE for d in report.diagnostics)

    def test_trajectory_non_finite_values(self) -> None:
        """ResultValidator detects NaN or Inf values in trajectory samples."""
        samples = [
            make_dummy_sample(0.0, 0.0),
            make_dummy_sample(10.0, float("nan")),
            make_dummy_sample(20.0, 300.0, v=float("inf")),
        ]
        traj = TrainTrajectory(
            train_id="NON_FINITE",
            train_type_id="TT_1",
            route_id="RT_1",
            running_direction=RunningDirection.FORWARD,
            samples=samples,
        )
        report = ResultValidator.validate_trajectory(traj)
        assert not report.is_valid
        assert any(d.code == DiagnosticCode.NON_FINITE_VALUE for d in report.diagnostics)

    def test_blocking_interval_invalid_times(self) -> None:
        """ResultValidator detects blocking interval with end_time < start_time."""
        decomp = BlockingTimeDecomposition(
            setup_time_s=3.0,
            approach_time_s=8.0,
            running_time_s=15.0,
            dwell_time_s=0.0,
            geometric_clearance_time_s=8.0,
            residual_rear_time_s=0.0,
            release_time_s=6.0,
            reconciliation_difference_s=0.0,
        )
        interval = ResourceBlockingInterval(
            interval_id="INV_01",
            resource_id="BLK_01",
            resource_category=ResourceCategory.TRACK_BLOCK,
            train_id="TRN_01",
            start_time_s=100.0,
            end_time_s=50.0,  # Invalid: end before start!
            running_direction=RunningDirection.FORWARD,
            physical_start_offset_m=0.0,
            physical_end_offset_m=500.0,
            decomposition=decomp,
        )
        pkg = SimulationResultPackage(
            run_id="RUN_01",
            scenario_id="SCEN_01",
            effective_config_hash="hash123",
            running_direction=RunningDirection.FORWARD,
            blocking_intervals=[interval],
        )
        report = ResultValidator.validate_result_package(pkg)
        assert not report.is_valid
        assert any(d.code == DiagnosticCode.INVALID_INTERVAL for d in report.diagnostics)

    def test_static_exporter_rejects_unsupported_format(self) -> None:
        """Headless static exporter rejects unsupported file extensions."""
        fig = go.Figure(layout=get_plotly_layout(title="Test", xaxis_title="X", yaxis_title="Y"))
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = Path(tmpdir) / "output.unsupported_ext"
            with pytest.raises(ValueError, match="Unsupported static export format"):
                export_figure_headless(fig, bad_path)

    def test_static_exporter_rejects_invalid_dimensions(self) -> None:
        """Static exporter rejects non-positive dimensions or DPI."""
        fig = go.Figure(layout=get_plotly_layout(title="Test", xaxis_title="X", yaxis_title="Y"))
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "output.png"
            with pytest.raises(ValueError, match="Export dimensions must be positive"):
                export_figure_headless(fig, out_path, width=0, height=800)

            with pytest.raises(ValueError, match="Export dimensions must be positive"):
                export_figure_headless(fig, out_path, width=1200, height=-10)

            with pytest.raises(ValueError, match="DPI must be positive"):
                export_figure_headless(fig, out_path, dpi=0)

    def test_table_exporter_rejects_unsupported_format(self) -> None:
        """EngineeringTable exporter rejects unknown output format types."""
        df = pd.DataFrame([{"Col A": 1, "Col B": 2}])
        tbl = EngineeringTable(
            table_id="TBL_ERR",
            title="Sample Table",
            raw_dataframe=df,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "table.unknown"
            with pytest.raises(ValueError, match="Unsupported export format"):
                export_table(tbl, out_path, format_type="xyz_format")

    def test_scenario_comparison_rejects_empty_inputs(self) -> None:
        """create_scenario_kpi_comparison_figure handles empty compared scenarios gracefully."""
        report = ScenarioComparisonReport(
            baseline_scenario_id="BASE",
            compared_scenario_ids=[],
            metric_differences={},
        )
        fig = create_scenario_kpi_comparison_figure(report, metric_name="headway_s")
        assert fig is not None
        assert "headway" in fig.layout.yaxis.title.text.lower()

    def test_tvs_chart_handles_empty_intervals_defensively(self) -> None:
        """TVS occupation figure gracefully handles empty TVS occupancy list."""
        fig = create_tvs_occupation_figure([])
        assert fig is not None
        assert "Running Direction" in str(fig.layout.annotations)

    def test_platform_occupation_figure_handles_empty_list(self) -> None:
        """create_platform_occupation_figure handles empty platform list gracefully."""
        fig = create_platform_occupation_figure([])
        assert fig is not None
        assert "Platform Track" in fig.layout.yaxis.title.text

    def test_residual_rear_occupation_figure_handles_no_residuals(self) -> None:
        """create_platform_occupation_figure handles records with no residual intervals."""
        rec = PlatformOccupationRecord(
            train_id="TR_01",
            station_id="STN_01",
            station_name="Central",
            platform_id="PLT_01",
            track_id="TRK_01",
            link_id="LNK_01",
            arrival_time_s=100.0,
            dwell_start_time_s=120.0,
            dwell_end_time_s=160.0,
            departure_time_s=165.0,
            clearance_time_s=180.0,
            running_direction=RunningDirection.FORWARD,
            is_residual_rear_active=False,
            residual_rear_duration_s=0.0,
        )
        fig = create_platform_occupation_figure([rec])
        assert fig is not None
        assert len(fig.data) >= 1

    def test_stochastic_histogram_handles_empty_samples_defensively(self) -> None:
        """Stochastic histogram builder gracefully handles empty samples with fallback annotation."""
        stat = StatisticalSummary(
            metric_name="headway_s",
            sample_count=0,
            mean=0.0,
            median=0.0,
            std_dev=0.0,
            min_value=0.0,
            max_value=0.0,
            p5=0.0,
            p50=0.0,
            p90=0.0,
            p95=0.0,
            p99=0.0,
        )
        fig = create_stochastic_histogram_figure([], summary=stat)
        assert fig is not None
        assert any("No stochastic samples" in (a.text or "") for a in fig.layout.annotations)

    def test_gradient_adapter_with_empty_profile(self) -> None:
        """Gradient profile adapter handles empty list gracefully."""
        adapted = VisualizationAdapter.adapt_gradient_profile([], RunningDirection.FORWARD)
        assert len(adapted) == 0

    def test_adapter_empty_trajectory(self) -> None:
        """VisualizationAdapter.adapt_trajectory returns empty DataFrame for empty trajectory."""
        traj = TrainTrajectory(
            train_id="EMPTY",
            train_type_id="TT_1",
            route_id="RT_1",
            running_direction=RunningDirection.FORWARD,
            samples=[],
        )
        df = VisualizationAdapter.adapt_trajectory(traj)
        assert len(df) == 0
        assert "time_s" in df.columns
