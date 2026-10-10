"""Engineering benchmarks for Milestone P08 Blocking-Time Analysis & Technical Headway Solver.

Covers:
- Benchmarks P08-B001 through P08-B005.
- Seven-component decomposition reconciliation.
- Controlling bottleneck identification and slack margins.
- Homogeneous and heterogeneous service headways.
- Directional mixed-traffic headway matrices (asymmetry preserved).
- Station dwell, residual rear occupation, junction, and TVS-constrained headways.
- Microscopic joint simulation verification.
- Forward and Reverse running directions throughout.
"""

import math
import pytest

from headway.analysis.blocking_time import (
    BlockingTimeComponent,
    BlockingTimeDecomposition,
    BlockingTimeline,
    ResourceBlockingInterval,
    decompose_blocking_interval,
)
from headway.analysis.bottlenecks import (
    BottleneckClassification,
    classify_bottleneck,
    evaluate_slack_and_bottlenecks,
    rank_longest_occupations,
)
from headway.analysis.conflict_detection import (
    ConflictDetector,
    ConflictType,
    ResourceConflict,
)
from headway.analysis.headway_results import (
    HeadwayResult,
    HeadwayValidationStatus,
    MixedTrafficHeadwayMatrix,
    StairwayBlockData,
)
from headway.analysis.headway_search import IterativeHeadwaySearch
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.analysis.mixed_traffic import MixedTrafficAnalyzer
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory
from headway.simulation.state import DynamicMode, OperationalState


# ==============================================================================
# Mandatory Benchmarks P08-B001 to P08-B005
# ==============================================================================


def test_p08_b001_simple_pairwise_headway():
    """Benchmark P08-B001 — Simple Pairwise Headway:

    Given conflict requirements:
    - BLK-A: 90 s.
    - BLK-B: 115 s.
    - BLK-C: 105 s.

    Expected:
    - Minimum headway = 115 s.
    - Controlling resource = BLK-B.
    - Slack:
      - BLK-A: 25 s.
      - BLK-B: 0 s.
      - BLK-C: 10 s.
    """
    # Create leader and follower timelines where relative release and entry times yield 90s, 115s, 105s
    # H = t_leader_release - t_follower_start
    # Let follower start at t = 0 for all three blocks.
    # BLK-A: leader releases at 90s -> H = 90 - 0 = 90s
    # BLK-B: leader releases at 115s -> H = 115 - 0 = 115s
    # BLK-C: leader releases at 105s -> H = 105 - 0 = 105s

    l_ivs = [
        ResourceBlockingInterval("L_A", "BLK-A", ResourceCategory.TRACK_BLOCK, "TR_L", 0.0, 90.0),
        ResourceBlockingInterval("L_B", "BLK-B", ResourceCategory.TRACK_BLOCK, "TR_L", 10.0, 115.0),
        ResourceBlockingInterval("L_C", "BLK-C", ResourceCategory.TRACK_BLOCK, "TR_L", 20.0, 105.0),
    ]
    f_ivs = [
        ResourceBlockingInterval("F_A", "BLK-A", ResourceCategory.TRACK_BLOCK, "TR_F", 0.0, 50.0),
        ResourceBlockingInterval("F_B", "BLK-B", ResourceCategory.TRACK_BLOCK, "TR_F", 0.0, 50.0),
        ResourceBlockingInterval("F_C", "BLK-C", ResourceCategory.TRACK_BLOCK, "TR_F", 0.0, 50.0),
    ]

    tl_leader = BlockingTimeline("TR_L", "SVC_L", "RT_01", RunningDirection.FORWARD, "DEPARTURE", 0.0, l_ivs)
    tl_follower = BlockingTimeline("TR_F", "SVC_F", "RT_01", RunningDirection.FORWARD, "DEPARTURE", 0.0, f_ivs)

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    result = solver.solve_pairwise_headway(tl_leader, tl_follower)

    # 1. Minimum headway must be exactly 115.0s
    assert result.headway_s == 115.0

    # 2. Controlling bottleneck must be BLK-B
    assert len(result.controlling_conflicts) == 1
    ctrl = result.controlling_conflicts[0]
    assert ctrl.leader_resource_id == "BLK-B"
    assert ctrl.slack_s == 0.0

    # 3. Slacks: BLK-A = 25s, BLK-B = 0s, BLK-C = 10s
    slack_by_res = {c.leader_resource_id: c.slack_s for c in result.conflict_ranking}
    assert slack_by_res["BLK-A"] == 25.0
    assert slack_by_res["BLK-B"] == 0.0
    assert slack_by_res["BLK-C"] == 10.0


def test_p08_b002_resource_blocking_duration():
    """Benchmark P08-B002 — Resource Blocking Duration:

    Given:
    - Blocking start: 100 s.
    - Final release: 184 s.

    Expected:
    - Duration = 184 - 100 = 84 s.
    """
    iv = ResourceBlockingInterval(
        interval_id="BI_001",
        resource_id="BLK_01",
        resource_category=ResourceCategory.TRACK_BLOCK,
        train_id="TR_1",
        start_time_s=100.0,
        end_time_s=184.0,
    )
    assert iv.duration_s == 84.0


def test_p08_b003_seven_component_breakdown():
    """Benchmark P08-B003 — Seven-Component Breakdown:

    Given:
    - Setup: 5 s
    - Approach: 15 s
    - Running: 50 s
    - Dwell: 0 s
    - Geometric clearance: 10 s
    - Residual rear: 0 s
    - Release: 4 s

    Expected:
    - Total duration = 84 s.
    - Additive reconciliation verified.
    """
    decomp = BlockingTimeDecomposition(
        setup_time_s=5.0,
        approach_time_s=15.0,
        running_time_s=50.0,
        dwell_time_s=0.0,
        geometric_clearance_time_s=10.0,
        residual_rear_time_s=0.0,
        release_time_s=4.0,
    )

    assert decomp.total_duration_s == 84.0
    assert decomp.is_reconciled is True
    assert decomp.reconciliation_difference_s == 0.0

    # Also test decompose_blocking_interval derivation matching these exact values
    # t_start = 100.0
    # t_entry = 120.0 (setup 5s + approach 15s)
    # t_exit = 170.0 (running 50s, dwell 0s)
    # t_clear = 180.0 (geometric clearance 10s, residual rear 0s)
    # t_end = 184.0 (release 4s)
    derived = decompose_blocking_interval(
        start_time_s=100.0,
        end_time_s=184.0,
        front_entry_time_s=120.0,
        front_exit_time_s=170.0,
        rear_clearance_time_s=180.0,
        dwell_duration_s=0.0,
        setup_duration_s=5.0,
        residual_rear_duration_s=0.0,
    )

    assert derived.setup_time_s == 5.0
    assert derived.approach_time_s == 15.0
    assert derived.running_time_s == 50.0
    assert derived.dwell_time_s == 0.0
    assert derived.geometric_clearance_time_s == 10.0
    assert derived.residual_rear_time_s == 0.0
    assert derived.release_time_s == 4.0
    assert derived.total_duration_s == 84.0
    assert derived.is_reconciled is True


def test_p08_b004_directional_headway_asymmetry():
    """Benchmark P08-B004 — Directional Headway:

    Given:
    - H(A, B) = 150 s.
    - H(B, A) = 110 s.

    Expected:
    - Matrix preserves the different values and does not symmetrize them.
    """
    matrix = MixedTrafficHeadwayMatrix(
        matrix_id="MTX_BENCH_04",
        running_direction=RunningDirection.FORWARD,
        service_ids=["SVC_A", "SVC_B"],
        headway_values_s={
            ("SVC_A", "SVC_A"): 120.0,
            ("SVC_A", "SVC_B"): 150.0,
            ("SVC_B", "SVC_A"): 110.0,
            ("SVC_B", "SVC_B"): 95.0,
        },
    )

    assert matrix.get_headway("SVC_A", "SVC_B") == 150.0
    assert matrix.get_headway("SVC_B", "SVC_A") == 110.0
    assert matrix.get_headway("SVC_A", "SVC_B") != matrix.get_headway("SVC_B", "SVC_A")

    df = matrix.to_dataframe()
    assert df.loc["SVC_A", "SVC_B"] == 150.0
    assert df.loc["SVC_B", "SVC_A"] == 110.0


def test_p08_b005_tvs_constant_speed_constraint():
    """Benchmark P08-B005 — TVS Constant-Speed Constraint:

    Given:
    - TVS length: 5,000 m.
    - Train length: 200 m.
    - Speed: 25 m/s.
    - Release delay: 5 s.
    - Identical leader and follower trajectories.
    - Zero additional reservation approach time.

    Expected:
    - Front exit: 5000 / 25 = 200 s.
    - Rear clear: (5000 + 200) / 25 = 208 s.
    - Resource release: 208 + 5 = 213 s.
    - Minimum TVS technical headway = 213 s.
    """
    # Leader: front entry at t = 0s, releases at 213s
    l_iv = ResourceBlockingInterval(
        interval_id="TVS_L",
        resource_id="TVS_01",
        resource_category=ResourceCategory.TVS,
        train_id="TR_LEAD",
        start_time_s=0.0,
        end_time_s=213.0,
        front_entry_time_s=0.0,
        front_exit_time_s=200.0,
        rear_clearance_time_s=208.0,
    )

    # Follower: front entry at t = 0s
    f_iv = ResourceBlockingInterval(
        interval_id="TVS_F",
        resource_id="TVS_01",
        resource_category=ResourceCategory.TVS,
        train_id="TR_FOLL",
        start_time_s=0.0,
        end_time_s=213.0,
        front_entry_time_s=0.0,
        front_exit_time_s=200.0,
        rear_clearance_time_s=208.0,
    )

    tl_leader = BlockingTimeline("TR_LEAD", "SVC_EXP", "RT_01", RunningDirection.FORWARD, "TVS_ENTRY", 0.0, [l_iv])
    tl_follower = BlockingTimeline("TR_FOLL", "SVC_EXP", "RT_01", RunningDirection.FORWARD, "TVS_ENTRY", 0.0, [f_iv])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    result = solver.solve_pairwise_headway(tl_leader, tl_follower)

    assert result.headway_s == 213.0
    assert result.controlling_conflicts[0].leader_resource_id == "TVS_01"
    assert result.controlling_conflicts[0].slack_s == 0.0


# ==============================================================================
# Additional Engineering Benchmarks (§ 26)
# ==============================================================================


def test_station_dwell_and_platform_headway():
    """P08-STH: Station dwell and platform release delay impact on technical headway."""
    # Leader stops at platform PLT_01:
    # front enters at 50s, dwells 40s (55s to 95s), departs at 95s, rear clears at 105s, released at 110s (5s release delay)
    l_plt = ResourceBlockingInterval(
        interval_id="L_PLT",
        resource_id="PLT_01",
        resource_category=ResourceCategory.PLATFORM,
        train_id="TR_1",
        start_time_s=30.0,
        end_time_s=110.0,
        front_entry_time_s=50.0,
        front_exit_time_s=98.0,
        rear_clearance_time_s=105.0,
        dwell_start_time_s=55.0,
        dwell_end_time_s=95.0,
    )

    # Follower arrives at platform: front enters at 50s, start reservation at 30s
    f_plt = ResourceBlockingInterval(
        interval_id="F_PLT",
        resource_id="PLT_01",
        resource_category=ResourceCategory.PLATFORM,
        train_id="TR_2",
        start_time_s=30.0,
        end_time_s=110.0,
        front_entry_time_s=50.0,
    )

    tl_l = BlockingTimeline("TR_1", "SVC_STOP", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_plt])
    tl_f = BlockingTimeline("TR_2", "SVC_STOP", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [f_plt])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    # Required headway: t_l_release (110) - t_f_start (30) = 80.0s
    assert res.headway_s == 80.0
    assert res.controlling_conflicts[0].bottleneck_type == BottleneckClassification.PLATFORM.value


def test_residual_rear_occupation_headway():
    """P08-STH-004: Residual stationary rear occupation extending headway on upstream resource."""
    # Leader stops at station stopping point, but its rear infringes upstream block BLK_UPSTREAM
    # Dwell = 180s, post-departure moving clearance = 14.142s -> upstream blocked until t = 224.142s
    l_up = ResourceBlockingInterval(
        interval_id="L_UP",
        resource_id="BLK_UPSTREAM",
        resource_category=ResourceCategory.TRACK_BLOCK,
        train_id="TR_LONG",
        start_time_s=10.0,
        end_time_s=224.142,
        front_entry_time_s=20.0,
        front_exit_time_s=30.0,
        rear_clearance_time_s=224.142,
        decomposition=BlockingTimeDecomposition(residual_rear_time_s=180.0),
    )

    # Follower needs BLK_UPSTREAM starting at t = 10.0s
    f_up = ResourceBlockingInterval(
        interval_id="F_UP",
        resource_id="BLK_UPSTREAM",
        resource_category=ResourceCategory.TRACK_BLOCK,
        train_id="TR_2",
        start_time_s=10.0,
        end_time_s=80.0,
    )

    tl_l = BlockingTimeline("TR_LONG", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_up])
    tl_f = BlockingTimeline("TR_2", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [f_up])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    # Required shift = 224.142 - 10.0 = 214.142s
    assert math.isclose(res.headway_s, 214.142, rel_tol=1e-4)
    assert res.controlling_conflicts[0].bottleneck_type == BottleneckClassification.RESIDUAL_REAR_OCCUPATION.value


def test_junction_merge_conflicting_routes():
    """P08-JNH: Converging junction route conflict requirement between different route IDs."""
    # Leader uses RT_MERGE_1 (releases at 85s)
    # Follower uses RT_MERGE_2 (requests start at 15s)
    l_rt = ResourceBlockingInterval(
        interval_id="L_RT1",
        resource_id="RT_MERGE_1",
        resource_category=ResourceCategory.INTERLOCKING_ROUTE,
        train_id="TR_1",
        start_time_s=10.0,
        end_time_s=85.0,
        description="Merge route from Track 1",
    )
    f_rt = ResourceBlockingInterval(
        interval_id="F_RT2",
        resource_id="RT_MERGE_2",
        resource_category=ResourceCategory.INTERLOCKING_ROUTE,
        train_id="TR_2",
        start_time_s=15.0,
        end_time_s=90.0,
        description="Converging merge route from Track 2",
    )

    tl_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_rt])
    tl_f = BlockingTimeline("TR_2", "SVC_2", "RT_2", RunningDirection.FORWARD, "DEP", 0.0, [f_rt])

    conflicting_routes = {
        "RT_MERGE_1": {"RT_MERGE_2"},
        "RT_MERGE_2": {"RT_MERGE_1"},
    }

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=50.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f, conflicting_routes=conflicting_routes)

    # Shift: 85 - 15 = 70.0s
    assert res.headway_s == 70.0
    assert res.controlling_conflicts[0].conflict_type == ConflictType.INTERLOCKING_CONFLICT
    assert res.controlling_conflicts[0].bottleneck_type == BottleneckClassification.JUNCTION_MERGE.value


def test_cross_track_shared_tvs_group_headway():
    """P08-TVS-003: Headway enforcement across parallel tracks sharing a TVS group."""
    # Track 1 TVS: TVS_T1 (releases at 190s)
    # Track 2 TVS: TVS_T2 (follower enters at 30s)
    l_tvs = ResourceBlockingInterval(
        interval_id="L_TVS1",
        resource_id="TVS_T1",
        resource_category=ResourceCategory.TVS,
        train_id="TR_1",
        start_time_s=0.0,
        end_time_s=190.0,
    )
    f_tvs = ResourceBlockingInterval(
        interval_id="F_TVS2",
        resource_id="TVS_T2",
        resource_category=ResourceCategory.TVS,
        train_id="TR_2",
        start_time_s=30.0,
        end_time_s=220.0,
    )

    tl_l = BlockingTimeline("TR_1", "SVC_T1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_tvs])
    tl_f = BlockingTimeline("TR_2", "SVC_T2", "RT_2", RunningDirection.FORWARD, "DEP", 0.0, [f_tvs])

    shared_groups = {
        "GRP_TVS_SHARED": {"TVS_T1", "TVS_T2"}
    }

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f, shared_groups=shared_groups)

    # Shift: 190 - 30 = 160.0s
    assert res.headway_s == 160.0
    assert res.controlling_conflicts[0].conflict_type == ConflictType.SHARED_CONFLICT_GROUP
    assert res.controlling_conflicts[0].bottleneck_type == BottleneckClassification.SHARED_TVS_GROUP.value


def test_whole_tunnel_exclusivity_headway():
    """P08-TVS-004: Whole-tunnel exclusivity scope across distinct TVS sections."""
    l_tvs = ResourceBlockingInterval("L_TVS_A", "TVS_A", ResourceCategory.TVS, "TR_1", 0.0, 140.0)
    f_tvs = ResourceBlockingInterval("F_TVS_B", "TVS_B", ResourceCategory.TVS, "TR_2", 20.0, 160.0)

    tl_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_tvs])
    tl_f = BlockingTimeline("TR_2", "SVC_2", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [f_tvs])

    tunnel_to_tvs = {"TUN_WHOLE": {"TVS_A", "TVS_B"}}
    whole_tunnel_ids = {"TVS_A", "TVS_B"}

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(
        tl_l, tl_f, tunnel_to_tvs=tunnel_to_tvs, whole_tunnel_tvs_ids=whole_tunnel_ids
    )

    # Shift: 140 - 20 = 120.0s
    assert res.headway_s == 120.0
    assert res.controlling_conflicts[0].conflict_type == ConflictType.WHOLE_TUNNEL_CONFLICT
    assert res.controlling_conflicts[0].bottleneck_type == BottleneckClassification.WHOLE_TUNNEL.value


def test_reverse_direction_homogeneous_headway():
    """P08-DIR-002: Technical minimum headway calculated in REVERSE running direction."""
    # In REVERSE, blocks are encountered in reverse order: BLK_3, BLK_2, BLK_1
    l_ivs = [
        ResourceBlockingInterval("L_3", "BLK_3", ResourceCategory.TRACK_BLOCK, "TR_REV1", 0.0, 80.0, running_direction=RunningDirection.REVERSE),
        ResourceBlockingInterval("L_2", "BLK_2", ResourceCategory.TRACK_BLOCK, "TR_REV1", 60.0, 145.0, running_direction=RunningDirection.REVERSE),
        ResourceBlockingInterval("L_1", "BLK_1", ResourceCategory.TRACK_BLOCK, "TR_REV1", 120.0, 200.0, running_direction=RunningDirection.REVERSE),
    ]
    f_ivs = [
        ResourceBlockingInterval("F_3", "BLK_3", ResourceCategory.TRACK_BLOCK, "TR_REV2", 0.0, 80.0, running_direction=RunningDirection.REVERSE),
        ResourceBlockingInterval("F_2", "BLK_2", ResourceCategory.TRACK_BLOCK, "TR_REV2", 60.0, 145.0, running_direction=RunningDirection.REVERSE),
        ResourceBlockingInterval("F_1", "BLK_1", ResourceCategory.TRACK_BLOCK, "TR_REV2", 120.0, 200.0, running_direction=RunningDirection.REVERSE),
    ]

    tl_l = BlockingTimeline("TR_REV1", "SVC_REV", "RT_REV", RunningDirection.REVERSE, "DEP_REV", 0.0, l_ivs)
    tl_f = BlockingTimeline("TR_REV2", "SVC_REV", "RT_REV", RunningDirection.REVERSE, "DEP_REV", 0.0, f_ivs)

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    # BLK_2 requirement: 145 - 60 = 85.0s
    # BLK_1 requirement: 200 - 120 = 80.0s
    # BLK_3 requirement: 80 - 0 = 80.0s
    assert res.headway_s == 85.0
    assert res.controlling_conflicts[0].leader_resource_id == "BLK_2"
    assert res.running_direction == RunningDirection.REVERSE


def test_multiple_jointly_controlling_bottlenecks():
    """P08-BNK-002: Identification of multiple jointly controlling bottlenecks with zero slack."""
    l_ivs = [
        ResourceBlockingInterval("L_1", "BLK_X", ResourceCategory.TRACK_BLOCK, "TR_1", 0.0, 100.0),
        ResourceBlockingInterval("L_2", "BLK_Y", ResourceCategory.TRACK_BLOCK, "TR_1", 20.0, 120.0),  # 120 - 20 = 100s
        ResourceBlockingInterval("L_3", "BLK_Z", ResourceCategory.TRACK_BLOCK, "TR_1", 50.0, 130.0),  # 130 - 50 = 80s
    ]
    f_ivs = [
        ResourceBlockingInterval("F_1", "BLK_X", ResourceCategory.TRACK_BLOCK, "TR_2", 0.0, 40.0),
        ResourceBlockingInterval("F_2", "BLK_Y", ResourceCategory.TRACK_BLOCK, "TR_2", 20.0, 60.0),
        ResourceBlockingInterval("F_3", "BLK_Z", ResourceCategory.TRACK_BLOCK, "TR_2", 50.0, 90.0),
    ]

    tl_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, l_ivs)
    tl_f = BlockingTimeline("TR_2", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, f_ivs)

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    assert res.headway_s == 100.0
    assert len(res.controlling_conflicts) == 2
    ctrl_ids = {c.leader_resource_id for c in res.controlling_conflicts}
    assert ctrl_ids == {"BLK_X", "BLK_Y"}


def test_iterative_headway_search_convergence():
    """P08-SRCH-005 & 007: Iterative headway search converges within target tolerance (0.1s)."""
    searcher = IterativeHeadwaySearch(tolerance_s=0.1, max_iterations=20)

    # True required headway is 95.34 seconds
    true_threshold = 95.34

    def checker(candidate_h: float):
        if candidate_h >= true_threshold:
            return True, "Feasible"
        return False, f"Conflict at {candidate_h:.2f}s"

    res = searcher.search(feasibility_checker=checker, lower_bound_s=50.0, upper_bound_s=150.0)

    assert res.validation_status == HeadwayValidationStatus.VALID
    assert math.isclose(res.optimal_headway_s, true_threshold, abs_tol=0.15)
    assert res.iterations_count <= 15


def test_longest_standalone_occupation_vs_controlling_headway():
    """P08-OCC-004: Explicit distinction between longest individual occupation and controlling headway."""
    # Consider:
    # BLK_LONG: Train is inside for 200s (e.g. slow traversal or dwell).
    # Leader starts at 0s, releases at 200s.
    # Follower starts at 150s (traverses much later).
    # Pairwise headway for BLK_LONG = 200 - 150 = 50s.
    #
    # BLK_SHORT: Train is inside for only 60s.
    # Leader starts at 210s, releases at 270s.
    # Follower reaches BLK_SHORT at 160s.
    # Pairwise headway for BLK_SHORT = 270 - 160 = 110s!
    #
    # Therefore, BLK_LONG has the longest standalone occupation (200s),
    # but BLK_SHORT is the controlling headway bottleneck (110s)!

    l_ivs = [
        ResourceBlockingInterval("L_1", "BLK_LONG", ResourceCategory.TRACK_BLOCK, "TR_1", 0.0, 200.0),
        ResourceBlockingInterval("L_2", "BLK_SHORT", ResourceCategory.TRACK_BLOCK, "TR_1", 210.0, 270.0),
    ]
    f_ivs = [
        ResourceBlockingInterval("F_1", "BLK_LONG", ResourceCategory.TRACK_BLOCK, "TR_2", 150.0, 350.0),
        ResourceBlockingInterval("F_2", "BLK_SHORT", ResourceCategory.TRACK_BLOCK, "TR_2", 160.0, 220.0),
    ]

    tl_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, l_ivs)
    tl_f = BlockingTimeline("TR_2", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, f_ivs)

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=30.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    # Controlling bottleneck must be BLK_SHORT (110s)
    assert res.headway_s == 110.0
    assert res.controlling_conflicts[0].leader_resource_id == "BLK_SHORT"

    # Standalone longest occupation must be BLK_LONG (200s)
    assert len(res.longest_occupations) > 0
    assert res.longest_occupations[0].resource_id == "BLK_LONG"
    assert res.longest_occupations[0].duration_s == 200.0


def test_heterogeneous_train_pair_headway():
    """P08-HET: Heterogeneous headway between high-speed Express and slower Regional train."""
    # Leader is Express (fast running through corridor, 40 m/s)
    # Follower is Regional (slower running, stopping at platform)
    l_ivs = [
        ResourceBlockingInterval("L_1", "BLK_A", ResourceCategory.TRACK_BLOCK, "TR_EXP", 0.0, 45.0),
        ResourceBlockingInterval("L_2", "BLK_B", ResourceCategory.TRACK_BLOCK, "TR_EXP", 30.0, 75.0),
        ResourceBlockingInterval("L_3", "BLK_C", ResourceCategory.TRACK_BLOCK, "TR_EXP", 60.0, 105.0),
    ]
    # Slower Regional follower arrives at blocks later
    f_ivs = [
        ResourceBlockingInterval("F_1", "BLK_A", ResourceCategory.TRACK_BLOCK, "TR_REG", 0.0, 60.0),
        ResourceBlockingInterval("F_2", "BLK_B", ResourceCategory.TRACK_BLOCK, "TR_REG", 40.0, 110.0),
        ResourceBlockingInterval("F_3", "BLK_C", ResourceCategory.TRACK_BLOCK, "TR_REG", 90.0, 170.0),
    ]

    tl_exp = BlockingTimeline("TR_EXP", "EXP", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, l_ivs)
    tl_reg = BlockingTimeline("TR_REG", "REG", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, f_ivs)

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=30.0)

    # 1. Express followed by Regional:
    # BLK_A: 45 - 0 = 45s
    # BLK_B: 75 - 40 = 35s
    # BLK_C: 105 - 90 = 15s
    # -> Controlling is BLK_A (45s)
    res_exp_reg = solver.solve_pairwise_headway(tl_exp, tl_reg)
    assert res_exp_reg.headway_s == 45.0
    assert res_exp_reg.controlling_conflicts[0].leader_resource_id == "BLK_A"

    # 2. Regional followed by Express (order reversed!):
    # Regional leader:
    # BLK_A: releases at 60s -> Express follower starts at 0s -> 60s
    # BLK_B: releases at 110s -> Express follower starts at 30s -> 80s!
    # BLK_C: releases at 170s -> Express follower starts at 60s -> 110s!
    # -> Controlling is BLK_C (110s)!
    res_reg_exp = solver.solve_pairwise_headway(tl_reg, tl_exp)
    assert res_reg_exp.headway_s == 110.0
    assert res_reg_exp.controlling_conflicts[0].leader_resource_id == "BLK_C"

    # Asymmetry: H(Exp, Reg) = 45s != H(Reg, Exp) = 110s!
    assert res_exp_reg.headway_s != res_reg_exp.headway_s


def test_directional_mixed_traffic_matrix_computation():
    """P08-MIX: Directional 3x3 mixed-traffic headway matrix computation."""
    # 3 services: Express (EXP), Commuter (COM), Freight (FRT)
    t_exp = BlockingTimeline("T_E", "EXP", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [
        ResourceBlockingInterval("E1", "B1", ResourceCategory.TRACK_BLOCK, "T_E", 0.0, 40.0),
        ResourceBlockingInterval("E2", "B2", ResourceCategory.TRACK_BLOCK, "T_E", 30.0, 70.0),
    ])
    t_com = BlockingTimeline("T_C", "COM", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [
        ResourceBlockingInterval("C1", "B1", ResourceCategory.TRACK_BLOCK, "T_C", 0.0, 60.0),
        ResourceBlockingInterval("C2", "B2", ResourceCategory.TRACK_BLOCK, "T_C", 40.0, 110.0),
    ])
    t_frt = BlockingTimeline("T_F", "FRT", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [
        ResourceBlockingInterval("F1", "B1", ResourceCategory.TRACK_BLOCK, "T_F", 0.0, 90.0),
        ResourceBlockingInterval("F2", "B2", ResourceCategory.TRACK_BLOCK, "T_F", 70.0, 180.0),
    ])

    timelines = {"EXP": t_exp, "COM": t_com, "FRT": t_frt}
    analyzer = MixedTrafficAnalyzer()
    matrix = analyzer.compute_matrix(timelines, custom_dispatch_min_s=30.0)

    assert len(matrix.service_ids) == 3
    # Check diagonal (homogeneous)
    assert matrix.get_headway("EXP", "EXP") == 40.0
    assert matrix.get_headway("COM", "COM") == 70.0
    assert matrix.get_headway("FRT", "FRT") == 110.0

    # Check asymmetry
    assert matrix.get_headway("EXP", "FRT") < matrix.get_headway("FRT", "EXP")

    # DataFrame validation
    df = matrix.to_dataframe()
    assert df.shape == (3, 3)
    assert list(df.index) == ["COM", "EXP", "FRT"]


def test_consecutive_tvs_multi_section_headway():
    """P08-TVS: Consecutive TVS multi-section traversal headway impact."""
    # Leader traverses TVS_A (0-213s) and TVS_B (200-413s)
    l_a = ResourceBlockingInterval("L_A", "TVS_A", ResourceCategory.TVS, "TR_1", 0.0, 213.0)
    l_b = ResourceBlockingInterval("L_B", "TVS_B", ResourceCategory.TVS, "TR_1", 200.0, 413.0)

    # Follower starts at t = 0 for TVS_A and t = 200 for TVS_B
    f_a = ResourceBlockingInterval("F_A", "TVS_A", ResourceCategory.TVS, "TR_2", 0.0, 213.0)
    f_b = ResourceBlockingInterval("F_B", "TVS_B", ResourceCategory.TVS, "TR_2", 200.0, 413.0)

    tl_l = BlockingTimeline("TR_1", "SVC_TVS", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_a, l_b])
    tl_f = BlockingTimeline("TR_2", "SVC_TVS", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [f_a, f_b])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    # TVS_A requires 213 - 0 = 213s
    # TVS_B requires 413 - 200 = 213s
    # Both are jointly controlling!
    assert res.headway_s == 213.0
    assert len(res.controlling_conflicts) == 2
    ctrl_res_ids = {c.leader_resource_id for c in res.controlling_conflicts}
    assert ctrl_res_ids == {"TVS_A", "TVS_B"}


def test_negative_conflict_shift_clamped_to_dispatch_min():
    """P08-HW-009: Negative conflict requirements must not reduce headway below minimum dispatch separation."""
    # Suppose leader clears resource very early, so t_release - t_start < 0
    l_iv = ResourceBlockingInterval("L_1", "BLK_FAR", ResourceCategory.TRACK_BLOCK, "TR_1", 0.0, 30.0)
    f_iv = ResourceBlockingInterval("F_1", "BLK_FAR", ResourceCategory.TRACK_BLOCK, "TR_2", 100.0, 140.0)

    tl_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_iv])
    tl_f = BlockingTimeline("TR_2", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [f_iv])

    # Conflict requirement: 30 - 100 = -70s
    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    # Headway MUST be clamped to minimum_dispatch_headway_s (60s)
    assert res.headway_s == 60.0
    assert res.minimum_dispatch_headway_s == 60.0


def test_resource_reuse_multiple_usages():
    """P08-BT-005: Train uses the same resource multiple times (e.g. loop or reversal)."""
    # Leader traverses BLK_LOOP twice:
    # 1st passage: 10s to 50s
    # 2nd passage: 120s to 160s
    l_u1 = ResourceBlockingInterval("L_U1", "BLK_LOOP", ResourceCategory.TRACK_BLOCK, "TR_1", 10.0, 50.0, usage_index=1)
    l_u2 = ResourceBlockingInterval("L_U2", "BLK_LOOP", ResourceCategory.TRACK_BLOCK, "TR_1", 120.0, 160.0, usage_index=2)

    # Follower traverses BLK_LOOP:
    # 1st passage: 10s to 50s
    f_u1 = ResourceBlockingInterval("F_U1", "BLK_LOOP", ResourceCategory.TRACK_BLOCK, "TR_2", 10.0, 50.0, usage_index=1)

    tl_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_u1, l_u2])
    tl_f = BlockingTimeline("TR_2", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [f_u1])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=30.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    # Conflicts:
    # Pair 1: l_u1 vs f_u1 -> 50 - 10 = 40s
    # Pair 2: l_u2 vs f_u1 -> 160 - 10 = 150s!
    # Because leader re-enters the loop at 120s and releases at 160s, follower cannot enter at 10s without 150s separation!
    assert res.headway_s == 150.0
    assert len(res.conflict_ranking) == 2


def test_microscopic_joint_simulation_verification():
    """P08-VER-001 to 004: Joint microscopic simulation verification of calculated headway."""
    samples = [
        TrajectorySample(
            time_s=t,
            front_distance_m=t * 20.0,
            rear_distance_m=(t * 20.0) - 100.0,
            speed_ms=20.0,
            acceleration_ms2=0.0,
            traction_force_n=5000.0,
            braking_force_n=0.0,
            davis_resistance_n=5000.0,
            gradient_resistance_n=0.0,
            curvature_resistance_n=0.0,
            net_force_n=0.0,
            dynamic_mode=DynamicMode.CRUISING,
            operational_state=OperationalState.RUNNING,
        )
        for t in range(0, 121)
    ]
    standalone_follower = TrainTrajectory(
        train_id="TR_FOLL_STANDALONE",
        train_type_id="TYPE_A",
        route_id="RT_1",
        running_direction=RunningDirection.FORWARD,
        samples=samples,
    )

    solver = TechnicalHeadwaySolver()

    def mock_joint_executor(candidate_h: float) -> TrainTrajectory:
        return standalone_follower

    ok, msg = solver.verify_with_joint_simulation(
        candidate_headway_s=90.0,
        leader_trajectory=standalone_follower,
        follower_standalone_trajectory=standalone_follower,
        joint_sim_executor=mock_joint_executor,
    )
    assert ok is True
    assert msg is None

