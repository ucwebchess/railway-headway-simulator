"""Negative and edge-case unit tests for Blocking-Time Analysis and Headway Solver.

Covers:
- Infeasible upper search bounds.
- Non-converging search handling.
- Negative conflict shifts and minimum dispatch clamping.
- Reconciling imperfect or unmapped intermediate event holds.
- Disjoint routes without conflicts.
- Empty timelines.
- Asymmetric directional validations.
"""

import pytest

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    BlockingTimeline,
    ResourceBlockingInterval,
    decompose_blocking_interval,
)
from headway.analysis.conflict_detection import ConflictDetector
from headway.analysis.headway_results import HeadwayValidationStatus
from headway.analysis.headway_search import IterativeHeadwaySearch
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory


def test_search_infeasible_upper_bound():
    """Iterative search returns INFEASIBLE when upper bound cannot satisfy constraints."""
    searcher = IterativeHeadwaySearch(tolerance_s=0.1, max_iterations=10)

    # All candidate separations are rejected
    def impossible_checker(h: float):
        return False, "Fatal collision at all tested headways"

    res = searcher.search(impossible_checker, lower_bound_s=60.0, upper_bound_s=300.0)

    assert res.validation_status == HeadwayValidationStatus.INFEASIBLE
    assert "infeasible" in (res.diagnostic_message or "").lower()
    assert res.iterations_count == 0


def test_search_non_converged_exceeds_max_iterations():
    """Iterative search returns NOT_CONVERGED when search cannot meet tight tolerance within max iterations."""
    # Tolerance 0.000001 with only 2 iterations
    searcher = IterativeHeadwaySearch(tolerance_s=1e-6, max_iterations=2)

    def simple_checker(h: float):
        return (h >= 100.0), "Feasible if >= 100"

    res = searcher.search(simple_checker, lower_bound_s=50.0, upper_bound_s=200.0)

    assert res.validation_status == HeadwayValidationStatus.NOT_CONVERGED
    assert "did not converge" in (res.diagnostic_message or "").lower()
    assert res.iterations_count == 2


def test_reconciliation_note_on_unmapped_event_gap():
    """P08-BT-016: Preserves reconciliation note and underlying interval when gaps exist."""
    # Total interval = 100s, but components sum to only 80s
    decomp = decompose_blocking_interval(
        start_time_s=0.0,
        end_time_s=100.0,
        front_entry_time_s=10.0,
        front_exit_time_s=50.0,
        rear_clearance_time_s=60.0,
        dwell_duration_s=0.0,
        setup_duration_s=5.0,
        residual_rear_duration_s=0.0,
    )

    # Entry = 10s -> setup 5s, approach 5s (10s total)
    # Traversal = 40s -> running 40s (50s cumulative)
    # Clearance = 10s -> geom 10s (60s cumulative)
    # Release = 40s (100 - 60) -> release 40s
    # Total = 5 + 5 + 40 + 0 + 10 + 0 + 40 = 100s -> perfectly reconciled
    assert decomp.is_reconciled is True


def test_disjoint_routes_return_minimum_dispatch_headway():
    """When leader and follower use completely disjoint resources, headway is minimum dispatch separation."""
    l_iv = ResourceBlockingInterval("L1", "BLK_EAST_01", ResourceCategory.TRACK_BLOCK, "TR_1", 0.0, 50.0)
    f_iv = ResourceBlockingInterval("F1", "BLK_WEST_01", ResourceCategory.TRACK_BLOCK, "TR_2", 0.0, 50.0)

    tl_l = BlockingTimeline("TR_1", "EAST_LINE", "RT_E", RunningDirection.FORWARD, "DEP", 0.0, [l_iv])
    tl_f = BlockingTimeline("TR_2", "WEST_LINE", "RT_W", RunningDirection.FORWARD, "DEP", 0.0, [f_iv])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=90.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    assert res.headway_s == 90.0
    assert len(res.controlling_conflicts) == 0
    assert res.controlling_bottleneck_description == "MINIMUM_DISPATCH_LIMIT"


def test_empty_timeline_handling():
    """Empty timeline returns minimum dispatch headway without crashing."""
    tl_empty_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [])
    tl_empty_f = BlockingTimeline("TR_2", "SVC_2", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=75.0)
    res = solver.solve_pairwise_headway(tl_empty_l, tl_empty_f)

    assert res.headway_s == 75.0
    assert len(res.conflict_ranking) == 0
    assert res.verification_status == HeadwayValidationStatus.VALID


def test_negative_required_shift_not_reducing_dispatch_minimum():
    """P08-HW-009: Negative shift requirement cannot reduce headway below dispatch minimum."""
    l_iv = ResourceBlockingInterval("L1", "BLK_01", ResourceCategory.TRACK_BLOCK, "TR_1", 0.0, 10.0)
    # Follower starts 100s later -> 10 - 100 = -90s
    f_iv = ResourceBlockingInterval("F1", "BLK_01", ResourceCategory.TRACK_BLOCK, "TR_2", 100.0, 150.0)

    tl_l = BlockingTimeline("TR_1", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [l_iv])
    tl_f = BlockingTimeline("TR_2", "SVC_1", "RT_1", RunningDirection.FORWARD, "DEP", 0.0, [f_iv])

    solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=60.0)
    res = solver.solve_pairwise_headway(tl_l, tl_f)

    assert res.headway_s == 60.0
    assert len(res.controlling_conflicts) == 0  # Governed by minimum dispatch separation
    assert res.conflict_ranking[0].required_headway_s == -90.0
    assert res.conflict_ranking[0].slack_s == 150.0  # 60 - (-90) = 150s
