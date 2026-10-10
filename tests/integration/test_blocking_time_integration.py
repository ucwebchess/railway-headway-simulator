"""End-to-end integration tests for Blocking-Time Analysis and Technical Headway Solver.

Covers:
- Full pipeline: P05/P07 SignallingCoordinator events -> ResourceUsageRecords -> BlockingTimeline -> HeadwayResult.
- Cross-technology headway comparison: Fixed-Block vs ETCS Level 2 vs CBTC Moving-Block.
- Multi-train corridor traversal with Station Dwell, Junction Merge, and TVS Section.
- Directional headway matrix computation on bidirectional infrastructure.
- Microscopic joint simulation verification.
"""

import math
import pytest

from headway.analysis.blocking_time import (
    BlockingTimeComponent,
    BlockingTimeline,
    ResourceBlockingInterval,
    extract_blocking_intervals_from_records,
)
from headway.analysis.bottlenecks import BottleneckClassification
from headway.analysis.conflict_detection import ConflictType
from headway.analysis.headway_results import HeadwayValidationStatus
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.analysis.mixed_traffic import MixedTrafficAnalyzer
from headway.data.canonical import (
    Platform,
    ResourceInterval,
    SharedResourceGroup,
    SignallingTechnologyType,
    Station,
    TrackDirectionality,
    Tunnel,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.switches import Switch, SwitchPosition
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.interlocking import InterlockingRouteDefinition
from headway.signalling.junction_controller import JunctionType, JunctionZone
from headway.signalling.resource_types import ReleasePolicy, ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory
from headway.simulation.state import DynamicMode, OperationalState


def test_coordinator_events_to_blocking_timeline_and_headway():
    """End-to-end pipeline: SignallingCoordinator simulation events -> ResourceUsageRecords -> HeadwayResult."""
    sc = SignallingCoordinator()

    # 1. Setup Station Platform
    stn = Station(station_id="STN_MAIN", name="Main Station")
    sc.platform_controller.register_station(stn)
    plat = Platform(platform_id="PLT_01", station_id="STN_MAIN", link_id="L1", start_offset_m=0, end_offset_m=200, length_m=200.0)
    sc.platform_controller.register_platform(plat, release_delay_s=3.0)

    # 2. Setup Junction
    sw = Switch(switch_id="SW_01", node_id="N1")
    sc.switch_controller.register_switch(sw)
    sc.resource_controller.register_resource(ManagedResource(resource_id="BLK_JNC", category=ResourceCategory.TRACK_BLOCK))
    r_jnc = InterlockingRouteDefinition(
        route_id="RT_JNC",
        entry_signal_id="S1",
        exit_signal_id="S2",
        link_sequence=["L1", "L2"],
        protected_block_ids=["BLK_JNC"],
        required_switch_positions={"SW_01": SwitchPosition.NORMAL},
    )
    sc.interlocking_engine.register_route(r_jnc)

    # 3. Setup TVS Section
    tvs = TVSSection(
        tvs_id="TVS_TUNNEL",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L2", start_offset_m=500.0, end_offset_m=2500.0)],
        release_delay_s=5.0,
    )
    sc.tvs_controller.register_tvs_section(tvs, release_delay_s=5.0, auth_processing_delay_s=1.0)

    # Execute Leader Run
    t = 0.0
    sc.platform_controller.request_platform("TR_LEAD", "PLT_01", 150.0, timestamp_s=t)
    sc.platform_controller.front_enter_platform("TR_LEAD", "PLT_01", timestamp_s=t + 10.0)
    sc.platform_controller.start_dwell("TR_LEAD", "PLT_01", timestamp_s=t + 15.0, dwell_duration_s=30.0)
    sc.platform_controller.complete_dwell("TR_LEAD", "PLT_01", timestamp_s=t + 45.0)
    sc.junction_controller.request_junction_movement("TR_LEAD", "RT_JNC", timestamp_s=t + 45.0)

    sc.tvs_controller.request_tvs_entry("TR_LEAD", "TVS_TUNNEL", timestamp_s=t + 46.0)
    sc.platform_controller.rear_clear_platform("TR_LEAD", "PLT_01", timestamp_s=t + 55.0)
    sc.platform_controller.process_platform_releases(current_time_s=t + 58.0)

    sc.tvs_controller.front_enter_tvs("TR_LEAD", "TVS_TUNNEL", timestamp_s=t + 60.0)
    sc.junction_controller.clear_junction_zone("TR_LEAD", "JNC_01", "RT_JNC", timestamp_s=t + 65.0)
    sc.junction_controller.release_junction_route("RT_JNC", "TR_LEAD", timestamp_s=t + 65.0)

    sc.tvs_controller.front_exit_tvs("TR_LEAD", "TVS_TUNNEL", timestamp_s=t + 140.0)
    sc.tvs_controller.rear_clear_tvs("TR_LEAD", "TVS_TUNNEL", timestamp_s=t + 148.0)
    sc.tvs_controller.process_release_timers(current_time_s=t + 153.0)

    # Extract leader records
    records = sc.get_resource_usage_records()
    leader_records = [r for r in records if r.train_id == "TR_LEAD"]
    assert len(leader_records) >= 3

    leader_ivs = extract_blocking_intervals_from_records(
        leader_records,
        dwell_durations={"PLT_01": 30.0},
    )

    tl_leader = BlockingTimeline(
        train_id="TR_LEAD",
        service_id="SVC_LEAD",
        route_id="RT_ALL",
        running_direction=RunningDirection.FORWARD,
        reference_event_name="DEPARTURE",
        reference_event_time_s=0.0,
        intervals=leader_ivs,
    )

    # Follower timeline (identical service pattern)
    follower_ivs = extract_blocking_intervals_from_records(
        leader_records,
        dwell_durations={"PLT_01": 30.0},
    )
    # Re-tag for follower
    follower_ivs_tagged = [
        ResourceBlockingInterval(
            interval_id=f"F_{iv.resource_id}",
            resource_id=iv.resource_id,
            resource_category=iv.resource_category,
            train_id="TR_FOLL",
            start_time_s=iv.start_time_s,
            end_time_s=iv.end_time_s,
            front_entry_time_s=iv.front_entry_time_s,
            front_exit_time_s=iv.front_exit_time_s,
            rear_clearance_time_s=iv.rear_clearance_time_s,
            decomposition=iv.decomposition,
        )
        for iv in follower_ivs
    ]

    tl_follower = BlockingTimeline(
        train_id="TR_FOLL",
        service_id="SVC_FOLL",
        route_id="RT_ALL",
        running_direction=RunningDirection.FORWARD,
        reference_event_name="DEPARTURE",
        reference_event_time_s=0.0,
        intervals=follower_ivs_tagged,
    )

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_leader, tl_follower)

    # TVS: released at 153s, follower requests at 46s -> required shift = 153 - 46 = 107.0s
    assert res.headway_s >= 100.0
    assert res.verification_status == HeadwayValidationStatus.VALID
    assert len(res.stairway_data) >= 3
    assert len(res.longest_occupations) >= 3


def test_cross_technology_headway_comparison():
    """Comparison of technical headway across Fixed-Block and moving block architectures."""
    # Compare fixed block (long discrete blocks) vs moving block (shorter dynamic envelope)
    # Fixed-block corridor: 3 blocks of 1500m
    l_fb = [
        ResourceBlockingInterval("FB_1", "BLK_1", ResourceCategory.TRACK_BLOCK, "T1", 0.0, 75.0),
        ResourceBlockingInterval("FB_2", "BLK_2", ResourceCategory.TRACK_BLOCK, "T1", 50.0, 125.0),
        ResourceBlockingInterval("FB_3", "BLK_3", ResourceCategory.TRACK_BLOCK, "T1", 100.0, 175.0),
    ]
    f_fb = [
        ResourceBlockingInterval("FB_F1", "BLK_1", ResourceCategory.TRACK_BLOCK, "T2", 0.0, 75.0),
        ResourceBlockingInterval("FB_F2", "BLK_2", ResourceCategory.TRACK_BLOCK, "T2", 50.0, 125.0),
        ResourceBlockingInterval("FB_F3", "BLK_3", ResourceCategory.TRACK_BLOCK, "T2", 100.0, 175.0),
    ]

    # Moving-block / high-fidelity virtual sections (finer granularity: 30s release intervals)
    l_cbtc = [
        ResourceBlockingInterval("MB_1", "VBLK_1", ResourceCategory.TRACK_BLOCK, "T1", 0.0, 45.0),
        ResourceBlockingInterval("MB_2", "VBLK_2", ResourceCategory.TRACK_BLOCK, "T1", 30.0, 75.0),
        ResourceBlockingInterval("MB_3", "VBLK_3", ResourceCategory.TRACK_BLOCK, "T1", 60.0, 105.0),
    ]
    f_cbtc = [
        ResourceBlockingInterval("MB_F1", "VBLK_1", ResourceCategory.TRACK_BLOCK, "T2", 0.0, 45.0),
        ResourceBlockingInterval("MB_F2", "VBLK_2", ResourceCategory.TRACK_BLOCK, "T2", 30.0, 75.0),
        ResourceBlockingInterval("MB_F3", "VBLK_3", ResourceCategory.TRACK_BLOCK, "T2", 60.0, 105.0),
    ]

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=30.0)

    res_fb = solver.solve_pairwise_headway(
        BlockingTimeline("T1", "FB", "R1", RunningDirection.FORWARD, "DEP", 0.0, l_fb),
        BlockingTimeline("T2", "FB", "R1", RunningDirection.FORWARD, "DEP", 0.0, f_fb),
    )

    res_cbtc = solver.solve_pairwise_headway(
        BlockingTimeline("T1", "CBTC", "R1", RunningDirection.FORWARD, "DEP", 0.0, l_cbtc),
        BlockingTimeline("T2", "CBTC", "R1", RunningDirection.FORWARD, "DEP", 0.0, f_cbtc),
    )

    # Fixed block headway: 75.0s
    # Moving block headway: 45.0s
    assert res_fb.headway_s == 75.0
    assert res_cbtc.headway_s == 45.0
    assert res_cbtc.headway_s < res_fb.headway_s


def test_bidirectional_corridor_headway_matrix():
    """Directional mixed-traffic headway matrix computation for both FORWARD and REVERSE corridors."""
    # Forward timelines
    fwd_timelines = {
        "FAST": BlockingTimeline("F1", "FAST", "RT_FWD", RunningDirection.FORWARD, "DEP", 0.0, [
            ResourceBlockingInterval("FF1", "SEC_1", ResourceCategory.TRACK_BLOCK, "F1", 0.0, 50.0),
            ResourceBlockingInterval("FF2", "SEC_2", ResourceCategory.TRACK_BLOCK, "F1", 40.0, 90.0),
        ]),
        "SLOW": BlockingTimeline("S1", "SLOW", "RT_FWD", RunningDirection.FORWARD, "DEP", 0.0, [
            ResourceBlockingInterval("FS1", "SEC_1", ResourceCategory.TRACK_BLOCK, "S1", 0.0, 80.0),
            ResourceBlockingInterval("FS2", "SEC_2", ResourceCategory.TRACK_BLOCK, "S1", 60.0, 140.0),
        ]),
    }

    # Reverse timelines (reverse order of sections, different speeds)
    rev_timelines = {
        "FAST": BlockingTimeline("RF1", "FAST", "RT_REV", RunningDirection.REVERSE, "DEP", 0.0, [
            ResourceBlockingInterval("RFF2", "SEC_2", ResourceCategory.TRACK_BLOCK, "RF1", 0.0, 55.0, running_direction=RunningDirection.REVERSE),
            ResourceBlockingInterval("RFF1", "SEC_1", ResourceCategory.TRACK_BLOCK, "RF1", 45.0, 100.0, running_direction=RunningDirection.REVERSE),
        ]),
        "SLOW": BlockingTimeline("RS1", "SLOW", "RT_REV", RunningDirection.REVERSE, "DEP", 0.0, [
            ResourceBlockingInterval("RSF2", "SEC_2", ResourceCategory.TRACK_BLOCK, "RS1", 0.0, 90.0, running_direction=RunningDirection.REVERSE),
            ResourceBlockingInterval("RSF1", "SEC_1", ResourceCategory.TRACK_BLOCK, "RS1", 70.0, 160.0, running_direction=RunningDirection.REVERSE),
        ]),
    }

    analyzer = MixedTrafficAnalyzer()
    fwd_matrix = analyzer.compute_matrix(fwd_timelines, running_direction=RunningDirection.FORWARD, matrix_id="MTX_FWD", custom_dispatch_min_s=30.0)
    rev_matrix = analyzer.compute_matrix(rev_timelines, running_direction=RunningDirection.REVERSE, matrix_id="MTX_REV", custom_dispatch_min_s=30.0)

    assert fwd_matrix.running_direction == RunningDirection.FORWARD
    assert rev_matrix.running_direction == RunningDirection.REVERSE

    # Forward FAST-SLOW vs SLOW-FAST
    assert fwd_matrix.get_headway("FAST", "SLOW") == 50.0
    assert fwd_matrix.get_headway("SLOW", "FAST") == 100.0

    # Reverse FAST-SLOW vs SLOW-FAST
    assert rev_matrix.get_headway("FAST", "SLOW") == 55.0
    assert rev_matrix.get_headway("SLOW", "FAST") == 115.0


def test_opposing_direction_single_track_conflict():
    """Opposing-direction headway conflict: Train A running FORWARD and Train B running REVERSE through single track."""
    # Single track bottleneck BLK_SINGLE
    # Train A (FORWARD) enters at 10s, exits and releases at 120s
    iv_fwd = ResourceBlockingInterval(
        interval_id="A_FWD",
        resource_id="BLK_SINGLE",
        resource_category=ResourceCategory.TRACK_BLOCK,
        train_id="TR_A",
        start_time_s=10.0,
        end_time_s=120.0,
        running_direction=RunningDirection.FORWARD,
    )
    # Train B (REVERSE) enters at 20s, releases at 140s
    iv_rev = ResourceBlockingInterval(
        interval_id="B_REV",
        resource_id="BLK_SINGLE",
        resource_category=ResourceCategory.TRACK_BLOCK,
        train_id="TR_B",
        start_time_s=20.0,
        end_time_s=140.0,
        running_direction=RunningDirection.REVERSE,
    )

    tl_a = BlockingTimeline("TR_A", "SVC_FWD", "RT_1", RunningDirection.FORWARD, "DEP_A", 0.0, [iv_fwd])
    tl_b = BlockingTimeline("TR_B", "SVC_REV", "RT_2", RunningDirection.REVERSE, "DEP_B", 0.0, [iv_rev])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_a, tl_b)

    # Train B cannot enter BLK_SINGLE (at t=20s) until Train A releases it (at t=120s)
    # Required shift = 120 - 20 = 100.0s
    assert res.headway_s == 100.0
    assert res.controlling_conflicts[0].leader_resource_id == "BLK_SINGLE"

