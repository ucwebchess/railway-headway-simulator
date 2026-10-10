"""Operational stability evaluation engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-STA-001 to P10-STA-006: Operational stability classification (STABLE, METASTABLE, UNSTABLE, COLLAPSED)
- Criteria: queue growth, delay growth/propagation, deadlock, completion rate
- Delay slope calculation (delay growth per dispatched train)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from headway.analysis.capacity_models import (
    OperationalStabilityStatus,
    StabilityEvaluation,
)

if TYPE_CHECKING:
    from headway.simulation.multi_train_engine import MultiTrainSimulationResult


class OperationalStabilityEvaluator:
    """Evaluates multi-train simulation operational stability against queue, delay, and deadlock criteria."""

    def __init__(
        self,
        delay_slope_unstable_threshold: float = 2.0,  # s delay increase per consecutive train
        delay_slope_metastable_threshold: float = 0.5,
        max_acceptable_delay_s: float = 300.0,
        min_completion_ratio: float = 0.95,
    ) -> None:
        self.delay_slope_unstable_threshold = delay_slope_unstable_threshold
        self.delay_slope_metastable_threshold = delay_slope_metastable_threshold
        self.max_acceptable_delay_s = max_acceptable_delay_s
        self.min_completion_ratio = min_completion_ratio

    def evaluate_simulation(
        self,
        sim_result: "MultiTrainSimulationResult",
        run_id: str = "RUN_STABILITY",
    ) -> StabilityEvaluation:
        """Evaluate operational stability of a multi-train simulation run."""
        instances = getattr(sim_result, "train_instances", [])
        total_trains = len(instances)

        if total_trains == 0:
            return StabilityEvaluation(
                run_id=run_id,
                status=OperationalStabilityStatus.STABLE,
                is_sustainable=True,
                max_queue_length=0,
                final_queue_length=0,
                average_delay_s=0.0,
                max_delay_s=0.0,
                delay_growth_slope=0.0,
                delay_growth_slope_s_per_train=0.0,
                secondary_to_primary_ratio=0.0,
                completion_ratio=1.0,
                deadlock_detected=False,
                diagnostic_reasons=["No trains simulated in run."],
            )

        # 1. Deadlock detection
        deadlock = False
        deadlock_report = getattr(sim_result, "deadlock_report", None)
        if deadlock_report is not None and getattr(deadlock_report, "deadlock_detected", False):
            deadlock = True

        completed_instances = [tr for tr in instances if tr.actual_completion_time_s is not None]
        uncompleted_instances = [tr for tr in instances if tr.actual_completion_time_s is None]
        completion_ratio = len(completed_instances) / float(total_trains)

        # 2. Delay statistics and slope
        delay_summaries = getattr(sim_result, "delay_summaries", {})
        delays: List[float] = []
        total_primary = 0.0
        total_secondary = 0.0

        # Sort instances by requested departure time
        sorted_instances = sorted(instances, key=lambda tr: tr.requested_departure_time_s)

        for tr in sorted_instances:
            ds = delay_summaries.get(tr.train_id)
            if ds is not None:
                d = max(0.0, ds.arrival_delay_s if ds.arrival_delay_s is not None else ds.departure_delay_s)
                delays.append(d)
                total_primary += getattr(ds, "primary_delay_s", 0.0)
                total_secondary += getattr(ds, "secondary_delay_s", 0.0)
            else:
                dep_delay = 0.0
                if tr.actual_departure_time_s is not None:
                    dep_delay = max(0.0, tr.actual_departure_time_s - tr.requested_departure_time_s)
                delays.append(dep_delay)

        avg_delay_s = sum(delays) / float(len(delays)) if delays else 0.0
        max_delay_s = max(delays) if delays else 0.0

        # Linear regression slope: delay vs train index
        slope = 0.0
        if len(delays) >= 2:
            n = len(delays)
            x = list(range(n))
            mean_x = sum(x) / float(n)
            mean_y = sum(delays) / float(n)
            num = sum((x[i] - mean_x) * (delays[i] - mean_y) for i in range(n))
            den = sum((x[i] - mean_x) ** 2 for i in range(n))
            slope = (num / den) if den > 0.0 else 0.0

        # 3. Queue estimation
        waiting_at_end = len(uncompleted_instances)
        entry_delayed = sum(1 for tr in instances if tr.actual_departure_time_s is not None and (tr.actual_departure_time_s - tr.requested_departure_time_s) > 30.0)
        max_queue = max(waiting_at_end, entry_delayed)
        final_queue = waiting_at_end

        sec_to_prim_ratio = (total_secondary / total_primary) if total_primary > 0.0 else 0.0

        # 4. Status determination
        reasons: List[str] = []
        if deadlock:
            status = OperationalStabilityStatus.COLLAPSED
            reasons.append("Deadlock detected in simulation network.")
        elif completion_ratio < self.min_completion_ratio and waiting_at_end > 1:
            status = OperationalStabilityStatus.COLLAPSED
            reasons.append(f"Severe completion failure: {len(completed_instances)}/{total_trains} completed ({completion_ratio:.1%}).")
        elif slope > self.delay_slope_unstable_threshold:
            status = OperationalStabilityStatus.UNSTABLE
            reasons.append(f"Monotonically growing delays: slope {slope:.2f} s/train exceeds threshold {self.delay_slope_unstable_threshold:.2f} s/train.")
        elif max_delay_s > self.max_acceptable_delay_s:
            status = OperationalStabilityStatus.UNSTABLE
            reasons.append(f"Maximum train delay {max_delay_s:.1f} s exceeds tolerance {self.max_acceptable_delay_s:.1f} s.")
        elif slope > self.delay_slope_metastable_threshold or completion_ratio < 1.0:
            status = OperationalStabilityStatus.METASTABLE
            reasons.append(f"Moderate delay growth: slope {slope:.2f} s/train or incomplete runs ({completion_ratio:.1%}).")
        else:
            status = OperationalStabilityStatus.STABLE
            reasons.append("Delays bounded, queues cleared, and full completion achieved.")

        is_sustainable = (status == OperationalStabilityStatus.STABLE)

        return StabilityEvaluation(
            run_id=run_id,
            status=status,
            is_sustainable=is_sustainable,
            total_requested=total_trains,
            total_completed=len(completed_instances),
            completion_ratio=completion_ratio,
            max_observed_queue=max_queue,
            max_queue_length=max_queue,
            final_queue_length=final_queue,
            average_delay_s=avg_delay_s,
            max_delay_s=max_delay_s,
            delay_growth_slope=slope,
            delay_growth_slope_s_per_train=slope,
            secondary_to_primary_ratio=sec_to_prim_ratio,
            deadlock_detected=deadlock,
            description="; ".join(reasons),
            diagnostic_reasons=reasons,
        )
