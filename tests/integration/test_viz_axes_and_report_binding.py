"""Regression tests for visualization axis layouts and report data binding.

RHS-CORRECTION-VIZ-REPORT-001:
  - Part 1: Swap X-Y axes for 7-component, blocking stairway, and platform reservation charts.
  - Part 2: Bind Rolling Stock and Infrastructure report sections to loaded project data.
"""

import pytest

from headway.analysis.blocking_time import BlockingTimeDecomposition
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_blocking import (
    create_blocking_stairway_figure,
    create_seven_component_figure,
)
from headway.reporting.charts_station import create_platform_occupation_figure
from headway.reporting.result_models import (
    HeadwayResult,
    PlatformOccupationRecord,
    ResourceBlockingInterval,
)
from headway.signalling.resource_types import ResourceCategory


def test_axis_layout_seven_component():
    """Test 1a: Seven-component chart has Block Resource on X and Blocking Time [s] on Y."""
    decomp1 = BlockingTimeDecomposition(1.0, 5.0, 10.0, 0.0, 2.0, 0.0, 1.0)
    decomp2 = BlockingTimeDecomposition(1.0, 4.0, 12.0, 0.0, 2.0, 0.0, 1.0)
    bi1 = ResourceBlockingInterval("INT_01", "BLK_01", ResourceCategory.TRACK_BLOCK, "TRN_01", 0.0, 19.0, decomposition=decomp1)
    bi2 = ResourceBlockingInterval("INT_02", "BLK_02", ResourceCategory.TRACK_BLOCK, "TRN_01", 10.0, 30.0, decomposition=decomp2)

    fig = create_seven_component_figure([bi1, bi2])

    assert fig.layout.xaxis.title.text == "Signalling Block Resource"
    assert fig.layout.yaxis.title.text == "Blocking Time [s]"
    assert len(fig.layout.xaxis.categoryarray) == 2
    assert "BLK_01" in fig.layout.xaxis.categoryarray
    assert "BLK_02" in fig.layout.xaxis.categoryarray


def test_axis_layout_stairway():
    """Test 1b: Blocking stairway chart has Block Resource on X and Time [s] on Y."""
    decomp1 = BlockingTimeDecomposition(1.0, 5.0, 10.0, 0.0, 2.0, 0.0, 1.0)
    decomp2 = BlockingTimeDecomposition(1.0, 4.0, 12.0, 0.0, 2.0, 0.0, 1.0)
    bi1 = ResourceBlockingInterval("INT_01", "BLK_01", ResourceCategory.TRACK_BLOCK, "TRN_01", 0.0, 19.0, decomposition=decomp1)
    bi2 = ResourceBlockingInterval("INT_02", "BLK_02", ResourceCategory.TRACK_BLOCK, "TRN_01", 10.0, 30.0, decomposition=decomp2)
    conf = ResourceConflict("C1", bi1, bi1, ConflictType.IDENTICAL_RESOURCE, 19.0, 0.0, 19.0, 0.0)

    hw_res = HeadwayResult(
        run_id="RUN_01",
        analysis_id="AN_01",
        scenario_id="BASELINE",
        running_direction=RunningDirection.FORWARD,
        headway_s=45.0,
        leader_service_id="SVC_01",
        follower_service_id="SVC_02",
        reference_point_id="REF_01",
        signalling_system="FIXED_BLOCK",
        headway_definition="TECHNICAL_MINIMUM",
        minimum_dispatch_headway_s=45.0,
        controlling_conflicts=[conf],
        blocking_intervals=[bi1, bi2],
    )

    fig = create_blocking_stairway_figure(hw_res)

    assert fig.layout.xaxis.title.text == "Signalling Block Resource"
    assert fig.layout.yaxis.title.text == "Time [s]"
    assert len(fig.layout.xaxis.categoryarray) == 2
    assert "BLK_01" in fig.layout.xaxis.categoryarray
    assert "BLK_02" in fig.layout.xaxis.categoryarray


def test_axis_layout_platform_occupation():
    """Test 1c: Platform reservation timeline has Platform Track on X and Simulation Time [s] on Y."""
    p1 = PlatformOccupationRecord(
        train_id="TRN_01",
        station_id="STN_A",
        station_name="Alpha",
        platform_id="PLT_A1",
        track_id="TRK_01",
        link_id="LNK_01",
        arrival_time_s=10.0,
        dwell_start_time_s=20.0,
        dwell_end_time_s=50.0,
        departure_time_s=50.0,
        clearance_time_s=60.0,
        running_direction=RunningDirection.FORWARD,
    )
    p2 = PlatformOccupationRecord(
        train_id="TRN_01",
        station_id="STN_B",
        station_name="Beta",
        platform_id="PLT_B1",
        track_id="TRK_01",
        link_id="LNK_02",
        arrival_time_s=70.0,
        dwell_start_time_s=80.0,
        dwell_end_time_s=110.0,
        departure_time_s=110.0,
        clearance_time_s=120.0,
        running_direction=RunningDirection.FORWARD,
    )

    fig = create_platform_occupation_figure([p1, p2])

    assert fig.layout.xaxis.title.text == "Station Platform Track"
    assert fig.layout.yaxis.title.text == "Simulation Time [s]"
    assert len(fig.layout.xaxis.categoryarray) == 2
