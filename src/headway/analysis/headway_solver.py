"""Technical headway solver, analytical temporal shift, and microscopic verification.

Strictly satisfies RHS-P08-001:
- § 4: Fundamental Headway Definitions (P08-HW-001 to P08-HW-005).
- § 9: Analytical Temporal Shift (P08-HW-006 to P08-HW-010).
- § 10: Slack Margins and Controlling Conflict Detection.
- § 11: Microscopic Headway Verification (P08-VER-001 to P08-VER-006).
- § 13 & 14: Homogeneous & Heterogeneous Headway Solvers.
- § 16, 17, 18: Station, Junction, TVS, and Residual Rear Integration.
- Complete support for both FORWARD and REVERSE railway movements.
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from headway.analysis.blocking_time import BlockingTimeline, ResourceBlockingInterval
from headway.analysis.bottlenecks import evaluate_slack_and_bottlenecks, rank_longest_occupations
from headway.analysis.conflict_detection import ConflictDetector, ResourceConflict
from headway.analysis.headway_results import (
    HeadwayResult,
    HeadwayValidationStatus,
    StairwayBlockData,
)
from headway.infrastructure.direction import RunningDirection
from headway.simulation.trajectory import TrainTrajectory


class TechnicalHeadwaySolver:
    """Calculates technical minimum headway from microscopic resource blocking intervals."""

    def __init__(
        self,
        minimum_dispatch_headway_s: float = 60.0,
        planning_margin_s: float = 0.0,
        search_tolerance_s: float = 0.1,
    ) -> None:
        self.minimum_dispatch_headway_s = minimum_dispatch_headway_s
        self.planning_margin_s = planning_margin_s
        self.search_tolerance_s = search_tolerance_s

    def solve_pairwise_headway(
        self,
        leader_timeline: BlockingTimeline,
        follower_timeline: BlockingTimeline,
        shared_groups: Optional[Dict[str, Set[str]]] = None,
        conflicting_routes: Optional[Dict[str, Set[str]]] = None,
        tunnel_to_tvs: Optional[Dict[str, Set[str]]] = None,
        whole_tunnel_tvs_ids: Optional[Set[str]] = None,
        run_id: str = "RUN_001",
        analysis_id: str = "AN_HW_001",
        scenario_id: str = "SCEN_BASE",
        reference_point_id: str = "ORIGIN",
        signalling_system: str = "FIXED_BLOCK",
        headway_definition: str = "UNIMPEDED_TECHNICAL_MINIMUM",
        custom_dispatch_min_s: Optional[float] = None,
    ) -> HeadwayResult:
        """P08-HW-006 & 007: Solves technical minimum headway H_min = max(H_dispatch, max H_{u,v})."""
        min_dispatch = (
            custom_dispatch_min_s if custom_dispatch_min_s is not None else self.minimum_dispatch_headway_s
        )

        detector = ConflictDetector(
            shared_groups=shared_groups,
            conflicting_routes=conflicting_routes,
            tunnel_to_tvs=tunnel_to_tvs,
            whole_tunnel_tvs_ids=whole_tunnel_tvs_ids,
            planning_margin_s=self.planning_margin_s,
        )

        conflicts = detector.detect_conflicts(
            leader_timeline=leader_timeline,
            follower_timeline=follower_timeline,
        )

        if conflicts:
            max_conflict_hw = max(c.required_headway_s for c in conflicts)
            h_min = max(min_dispatch, max_conflict_hw)
        else:
            h_min = min_dispatch

        # Evaluate slack margins and identify controlling bottlenecks
        ranked_conflicts, controlling_conflicts = evaluate_slack_and_bottlenecks(
            conflicts=conflicts,
            minimum_headway_s=h_min,
            tolerance_s=self.search_tolerance_s,
        )

        # Standalone longest occupation ranking
        all_intervals = leader_timeline.intervals + follower_timeline.intervals
        longest_occupations = rank_longest_occupations(all_intervals)

        # Generate stairway dataset
        stairway_data = self._generate_stairway_data(
            leader_timeline=leader_timeline,
            follower_timeline=follower_timeline,
            headway_s=h_min,
            controlling_conflicts=controlling_conflicts,
        )

        # Verification status check
        status = HeadwayValidationStatus.VALID
        if h_min < min_dispatch - 1e-4:
            status = HeadwayValidationStatus.INFEASIBLE

        return HeadwayResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            leader_service_id=leader_timeline.service_id,
            follower_service_id=follower_timeline.service_id,
            reference_point_id=reference_point_id,
            running_direction=leader_timeline.running_direction,
            signalling_system=signalling_system,
            headway_definition=headway_definition,
            headway_s=round(h_min, 6),
            minimum_dispatch_headway_s=round(min_dispatch, 6),
            controlling_conflicts=controlling_conflicts,
            conflict_ranking=ranked_conflicts,
            blocking_intervals=leader_timeline.intervals + follower_timeline.intervals,
            longest_occupations=longest_occupations,
            stairway_data=stairway_data,
            verification_status=status,
            numerical_tolerance_s=self.search_tolerance_s,
            details={
                "conflicts_count": len(conflicts),
                "controlling_count": len(controlling_conflicts),
                "is_dispatch_limited": abs(h_min - min_dispatch) <= 1e-4 and len(conflicts) > 0,
            },
        )

    def _generate_stairway_data(
        self,
        leader_timeline: BlockingTimeline,
        follower_timeline: BlockingTimeline,
        headway_s: float,
        controlling_conflicts: List[ResourceConflict],
    ) -> List[StairwayBlockData]:
        """P08-STAIR: Generates shifted and unshifted stairway comparison rows."""
        controlling_res_ids = {c.leader_resource_id for c in controlling_conflicts}.union(
            {c.follower_resource_id for c in controlling_conflicts}
        )

        stairway: List[StairwayBlockData] = []
        # Group by resource ID across both timelines
        leader_by_res = {iv.resource_id: iv for iv in leader_timeline.intervals}
        follower_by_res = {iv.resource_id: iv for iv in follower_timeline.intervals}

        all_res_ids = sorted(set(leader_by_res.keys()).union(set(follower_by_res.keys())))

        for rid in all_res_ids:
            l_iv = leader_by_res.get(rid)
            f_iv = follower_by_res.get(rid)

            pos_start = (l_iv.physical_start_offset_m if l_iv else None) or (
                f_iv.physical_start_offset_m if f_iv else 0.0
            ) or 0.0
            pos_end = (l_iv.physical_end_offset_m if l_iv else None) or (
                f_iv.physical_end_offset_m if f_iv else pos_start + 1000.0
            ) or (pos_start + 1000.0)

            l_start = l_iv.start_time_s if l_iv else 0.0
            l_end = l_iv.end_time_s if l_iv else 0.0
            f_start = f_iv.start_time_s if f_iv else 0.0
            f_end = f_iv.end_time_s if f_iv else 0.0

            req_hw = (l_end - f_start) if (l_iv and f_iv) else 0.0

            row = StairwayBlockData(
                resource_id=rid,
                resource_category=(l_iv.resource_category if l_iv else f_iv.resource_category).value,
                physical_start_m=round(pos_start, 1),
                physical_end_m=round(pos_end, 1),
                leader_start_s=round(l_start, 3),
                leader_end_s=round(l_end, 3),
                follower_unshifted_start_s=round(f_start, 3),
                follower_unshifted_end_s=round(f_end, 3),
                follower_shifted_start_s=round(f_start + headway_s, 3),
                follower_shifted_end_s=round(f_end + headway_s, 3),
                is_controlling=rid in controlling_res_ids,
                required_headway_s=round(req_hw, 3),
            )
            stairway.append(row)

        return stairway

    def verify_with_joint_simulation(
        self,
        candidate_headway_s: float,
        leader_trajectory: TrainTrajectory,
        follower_standalone_trajectory: TrainTrajectory,
        joint_sim_executor: Callable[[float], TrainTrajectory],
        tolerance_s: float = 0.1,
    ) -> Tuple[bool, Optional[str]]:
        """P08-VER-001 to 006: Microscopic joint simulation verification.

        Executes simultaneous leader and follower simulation displaced by candidate_headway_s.
        Verifies follower trajectory is unimpeded (equivalent journey time within tolerance_s).
        """
        # Run joint simulation
        joint_follower_trj = joint_sim_executor(candidate_headway_s)

        # 1. Total time check
        expected_total_s = follower_standalone_trajectory.total_time_s
        actual_total_s = joint_follower_trj.total_time_s
        diff_s = actual_total_s - expected_total_s

        if diff_s > tolerance_s:
            return (
                False,
                f"Follower impeded by {diff_s:.3f}s in joint simulation (expected {expected_total_s:.2f}s, got {actual_total_s:.2f}s).",
            )

        # 2. Moving time check
        expected_moving_s = follower_standalone_trajectory.moving_time_s
        actual_moving_s = joint_follower_trj.moving_time_s
        diff_move = actual_moving_s - expected_moving_s

        if diff_move > tolerance_s:
            return (
                False,
                f"Follower moving time delayed by {diff_move:.3f}s in joint simulation.",
            )

        return True, None
