"""Unit and regression tests for v1.7.0 reporting polish and physics constraints.

Covers:
- Task 1: Relative blocking-time stairway graphic with continuous distance (km) and inverted Y-axis.
- Task 2: Speed profile permissible envelope enforcement and CSV export.
- Task 3: Section 13 TVS assessment table with DEF-09 data.
- Task 4: Section 15 Stochastic headway & operational reliability summary table.
"""

import io
import pandas as pd
import pytest

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    ResourceBlockingInterval,
    ResourceCategory,
)
from headway.analysis.headway_results import HeadwayResult, ResourceConflict
from headway.simulation.state import DynamicMode, OperationalState
from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_blocking import create_blocking_stairway_figure
from headway.reporting.charts_speed import (
    create_speed_profile_dataframe,
    generate_speed_profile_csv,
)
from headway.reporting.report_models import ReportSectionId
from headway.reporting.tables import (
    create_stochastic_headway_table,
    create_tvs_assessment_table,
)
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner


class TestV170ReportingPolish:
    """Tests covering all Tasks 1-4 for v1.7.0."""

    def test_task1_blocking_stairway_continuous_distance_and_inverted_yaxis(self):
        """Task 1: Stairway X-axis uses physical distance (km) and Y-axis has inverted autorange."""
        bi1 = ResourceBlockingInterval(
            interval_id="INT_01",
            resource_id="BLK_01",
            resource_category=ResourceCategory.TRACK_BLOCK,
            train_id="TRN_LEADER",
            start_time_s=10.0,
            end_time_s=50.0,
            physical_start_offset_m=0.0,
            physical_end_offset_m=1500.0,
        )
        bi2 = ResourceBlockingInterval(
            interval_id="INT_02",
            resource_id="BLK_02",
            resource_category=ResourceCategory.TRACK_BLOCK,
            train_id="TRN_LEADER",
            start_time_s=45.0,
            end_time_s=90.0,
            physical_start_offset_m=1500.0,
            physical_end_offset_m=3200.0,
        )
        hw_res = HeadwayResult(
            run_id="RUN_TEST",
            analysis_id="AN_TEST",
            scenario_id="SCEN_TEST",
            running_direction=RunningDirection.FORWARD,
            headway_s=60.0,
            leader_service_id="SVC_01",
            follower_service_id="SVC_02",
            reference_point_id="REF_01",
            signalling_system="FIXED_BLOCK",
            headway_definition="TECHNICAL_MINIMUM",
            minimum_dispatch_headway_s=60.0,
            blocking_intervals=[bi1, bi2],
        )

        fig = create_blocking_stairway_figure(hw_res)

        assert "Route Distance" in fig.layout.xaxis.title.text
        assert "(km)" in fig.layout.xaxis.title.text
        assert "Time [s]" in fig.layout.yaxis.title.text
        assert fig.layout.yaxis.autorange == "reversed"

        assert len(fig.data) >= 2
        leader_trace = fig.data[0]
        follower_trace = fig.data[1]

        # Raw X-axis array is distance in km
        assert list(leader_trace.x) == [0.0, 1.5]
        assert list(leader_trace.width) == [1.5, 1.7]
        assert list(leader_trace.y) == [40.0, 45.0]  # durations
        assert list(leader_trace.base) == [10.0, 45.0]  # start times

        # Follower trace shifted by headway_s = 60.0
        assert list(follower_trace.x) == [0.0, 1.5]
        assert list(follower_trace.base) == [70.0, 105.0]

    def test_task2_speed_profile_dataframe_and_csv_generation(self):
        """Task 2: Speed profile CSV export with required columns and hard speed clamping."""
        def _make_sample(t, d, v):
            return TrajectorySample(
                time_s=t,
                front_distance_m=d,
                rear_distance_m=max(0.0, d - 100.0),
                speed_ms=v,
                acceleration_ms2=0.0,
                traction_force_n=0.0,
                braking_force_n=0.0,
                davis_resistance_n=0.0,
                gradient_resistance_n=0.0,
                curvature_resistance_n=0.0,
                net_force_n=0.0,
                dynamic_mode=DynamicMode.CRUISING,
                operational_state=OperationalState.RUNNING,
            )

        samples = [
            _make_sample(0.0, 0.0, 0.0),
            _make_sample(10.0, 100.0, 20.0),
            _make_sample(20.0, 400.0, 45.0),
        ]
        traj = TrainTrajectory(
            train_id="TRN_01",
            train_type_id="TT_01",
            route_id="RT_01",
            running_direction=RunningDirection.FORWARD,
            samples=samples,
        )
        env = [
            {"route_distance_m": 0.0, "max_speed_kmh": 120.0},
            {"route_distance_m": 1000.0, "max_speed_kmh": 120.0},
        ]

        df = create_speed_profile_dataframe(traj, permissible_speed_envelope=env)
        expected_cols = ["time_s", "front_distance_m", "speed_kmh", "permissible_speed_kmh"]
        assert list(df.columns) == expected_cols
        assert len(df) == 3

        # Sample at 20.0s had speed_ms=45.0 (162 km/h) but envelope is 120.0 km/h
        # Must be hard clamped to 120.0 km/h
        assert df["speed_kmh"].iloc[2] <= 120.0

        # CSV string generation
        csv_str = generate_speed_profile_csv(traj, permissible_speed_envelope=env)
        assert isinstance(csv_str, str)
        df_roundtrip = pd.read_csv(io.StringIO(csv_str))
        assert list(df_roundtrip.columns) == expected_cols
        assert len(df_roundtrip) == 3

    def test_task3_tvs_assessment_table_def09(self):
        """Task 3: Section 13 TVS assessment table with exact DEF-09 columns."""
        tvs_events = [
            {
                "tvs_id": "TVS_01",
                "train_id": "TRN_LEADER",
                "entry_time_s": 26.81,
                "exit_time_s": 109.16,
                "release_time_s": 129.16,
            },
            {
                "tvs_id": "TVS_02",
                "train_id": "TRN_LEADER",
                "entry_time_s": 109.16,
                "exit_time_s": 195.50,
                "release_time_s": 215.50,
            },
        ]

        tbl = create_tvs_assessment_table(tvs_events)
        assert tbl.table_id == "TBL_TVS_ASSESSMENT"
        expected_cols = [
            "TVS ID",
            "Entry Time (s)",
            "Exit Time (s)",
            "Physical Occupation (s)",
            "Post-Clearance Delay (s)",
            "Total Blocking (s)",
        ]
        assert list(tbl.raw_dataframe.columns) == expected_cols
        assert list(tbl.formatted_dataframe.columns) == expected_cols
        assert len(tbl.raw_dataframe) == 2

        row0 = tbl.raw_dataframe.iloc[0].to_dict()
        assert row0["TVS ID"] == "TVS_01"
        assert row0["Entry Time (s)"] == 26.81
        assert row0["Exit Time (s)"] == 109.16
        assert row0["Physical Occupation (s)"] == round(109.16 - 26.81, 2)
        assert row0["Post-Clearance Delay (s)"] == round(129.16 - 109.16, 2)
        assert row0["Total Blocking (s)"] == round(129.16 - 26.81, 2)

    def test_task4_stochastic_headway_table(self):
        """Task 4: Stochastic headway & operational reliability summary table."""
        samples = [240.0 + i * 0.5 for i in range(20)]
        tbl = create_stochastic_headway_table(samples=samples)

        assert tbl.table_id == "TBL_STOCHASTIC_HEADWAY"
        expected_cols = ["Metric", "Value (s)", "Value (min)", "Operational Impact"]
        assert list(tbl.raw_dataframe.columns) == expected_cols
        assert len(tbl.raw_dataframe) == 4

        metrics = list(tbl.raw_dataframe["Metric"])
        assert metrics == ["Mean Headway", "Std Dev", "5th Percentile", "95th Percentile"]

        # Check values are populated and positive
        for _, row in tbl.raw_dataframe.iterrows():
            assert row["Value (s)"] > 0
            assert row["Value (min)"] == round(row["Value (s)"] / 60.0, 2)
            assert len(row["Operational Impact"]) > 0

    def test_e2e_report_sections_include_new_tables(self):
        """E2E verification that ReportDocument contains both TVS and Stochastic tables."""
        project, _, _ = FileManager.load_example_project("04_tunnel_tvs")
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=project,
            running_direction=RunningDirection.FORWARD,
            performance_factor=1.0,
        )

        # Section 13 (TVS Assessment)
        sec_tvs = doc.get_section(ReportSectionId.TVS_ASSESSMENT)
        assert sec_tvs.is_applicable
        assert len(sec_tvs.tables) == 1
        assert sec_tvs.tables[0].table_id == "TBL_TVS_ASSESSMENT"

        # Section 15 (Stochastic Reliability)
        sec_stoch = doc.get_section(ReportSectionId.STOCHASTIC_RELIABILITY)
        assert sec_stoch.is_applicable
        assert len(sec_stoch.tables) == 1
        assert sec_stoch.tables[0].table_id == "TBL_STOCHASTIC_HEADWAY"
