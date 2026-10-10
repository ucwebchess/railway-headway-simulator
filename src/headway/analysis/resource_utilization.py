"""Resource utilization analysis engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-RES-001 to P10-RES-006: Physical occupation vs blocking time analysis
- Differentiates TRACK_BLOCK, PLATFORM, SWITCH, JUNCTION, TVS
- Directional attribution (FORWARD vs REVERSE)
- Interval merging for overlapping allocations to compute true occupancy ratio
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

from headway.analysis.capacity_models import (
    BottleneckCategory,
    ResourceUtilizationMetric,
)
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory, ResourceUsageRecord

if TYPE_CHECKING:
    from headway.simulation.multi_train_engine import MultiTrainSimulationResult


def merge_time_intervals(intervals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Merge overlapping or adjacent closed intervals [start, end]."""
    valid = [(s, e) for s, e in intervals if math.isfinite(s) and math.isfinite(e) and e > s]
    if not valid:
        return []

    sorted_ivs = sorted(valid, key=lambda x: x[0])
    merged: List[Tuple[float, float]] = [sorted_ivs[0]]

    for current in sorted_ivs[1:]:
        prev_start, prev_end = merged[-1]
        if current[0] <= prev_end:
            # Overlapping or contiguous
            merged[-1] = (prev_start, max(prev_end, current[1]))
        else:
            merged.append(current)

    return merged


def total_interval_duration(intervals: Sequence[Tuple[float, float]], window_start: float = 0.0, window_end: Optional[float] = None) -> float:
    """Compute union duration of intervals clipped within [window_start, window_end]."""
    clipped: List[Tuple[float, float]] = []
    for s, e in intervals:
        c_s = max(s, window_start)
        c_e = min(e, window_end) if window_end is not None else e
        if c_e > c_s:
            clipped.append((c_s, c_e))

    merged = merge_time_intervals(clipped)
    return sum(e - s for s, e in merged)


class ResourceUtilizationAnalyzer:
    """Computes physical and blocking resource utilization metrics across simulation records."""

    def __init__(self, critical_threshold_percent: float = 75.0) -> None:
        self.critical_threshold_percent = critical_threshold_percent

    def analyze_usage_records(
        self,
        records: Sequence[ResourceUsageRecord],
        window_duration_s: float,
        window_start_s: float = 0.0,
    ) -> Dict[str, ResourceUtilizationMetric]:
        """Analyze a collection of ResourceUsageRecord items across a measurement window."""
        if window_duration_s <= 0.0 or not math.isfinite(window_duration_s):
            raise ValueError(f"Window duration must be positive and finite (got {window_duration_s} s).")

        window_end_s = window_start_s + window_duration_s

        # Group records by resource_id
        grouped: Dict[str, List[ResourceUsageRecord]] = {}
        for rec in records:
            grouped.setdefault(rec.resource_id, []).append(rec)

        results: Dict[str, ResourceUtilizationMetric] = {}

        for res_id, res_records in grouped.items():
            category = res_records[0].resource_type.value if hasattr(res_records[0].resource_type, "value") else str(res_records[0].resource_type)

            blocking_ivs_all: List[Tuple[float, float]] = []
            blocking_ivs_fwd: List[Tuple[float, float]] = []
            blocking_ivs_rev: List[Tuple[float, float]] = []
            physical_ivs_all: List[Tuple[float, float]] = []

            for r in res_records:
                # Blocking interval
                b_start = r.reservation_start_s
                b_end = r.final_release_s if r.final_release_s is not None else (r.release_eligibility_s or window_end_s)
                if b_end > b_start:
                    blocking_ivs_all.append((b_start, b_end))
                    if r.running_direction == RunningDirection.FORWARD:
                        blocking_ivs_fwd.append((b_start, b_end))
                    else:
                        blocking_ivs_rev.append((b_start, b_end))

                # Physical interval
                p_start = r.physical_front_entry_s
                p_end = r.rear_clearance_s if r.rear_clearance_s is not None else (r.front_exit_s or b_end)
                if p_start is not None and p_end is not None and p_end > p_start:
                    physical_ivs_all.append((p_start, p_end))

            total_blocking_s = total_interval_duration(blocking_ivs_all, window_start_s, window_end_s)
            fwd_blocking_s = total_interval_duration(blocking_ivs_fwd, window_start_s, window_end_s)
            rev_blocking_s = total_interval_duration(blocking_ivs_rev, window_start_s, window_end_s)
            total_physical_s = total_interval_duration(physical_ivs_all, window_start_s, window_end_s)

            blocking_pct = min(100.0, (total_blocking_s / window_duration_s) * 100.0)
            physical_pct = min(100.0, (total_physical_s / window_duration_s) * 100.0)
            is_crit = blocking_pct >= self.critical_threshold_percent

            metric = ResourceUtilizationMetric(
                resource_id=res_id,
                resource_category=category,
                total_blocking_time_s=total_blocking_s,
                total_physical_occupation_time_s=total_physical_s,
                blocking_utilization_percent=blocking_pct,
                physical_utilization_percent=physical_pct,
                forward_blocking_time_s=fwd_blocking_s,
                reverse_blocking_time_s=rev_blocking_s,
                train_occupancy_count=len(res_records),
                measurement_duration_s=window_duration_s,
                is_critical=is_crit,
                details={
                    "critical_threshold_percent": self.critical_threshold_percent,
                    "merged_blocking_intervals_count": len(merge_time_intervals(blocking_ivs_all)),
                },
            )
            results[res_id] = metric

        return results

    def analyze_simulation_result(
        self,
        sim_result: "MultiTrainSimulationResult",
        window_duration_s: Optional[float] = None,
        window_start_s: float = 0.0,
    ) -> Dict[str, ResourceUtilizationMetric]:
        """Analyze resources from MultiTrainSimulationResult coordinator usage records."""
        # Find usage records from simulation result
        records: List[ResourceUsageRecord] = []
        if hasattr(sim_result, "resource_usage_records") and sim_result.resource_usage_records:
            records = sim_result.resource_usage_records
        elif hasattr(sim_result, "usage_records") and sim_result.usage_records:
            records = sim_result.usage_records

        effective_duration = window_duration_s
        if effective_duration is None:
            max_t = 0.0
            trajectories = getattr(sim_result, "trajectories", {})
            for traj in trajectories.values():
                if traj and getattr(traj, "samples", []):
                    max_t = max(max_t, traj.samples[-1].time_s)
            effective_duration = max(1.0, max_t)

        return self.analyze_usage_records(records, effective_duration, window_start_s)
