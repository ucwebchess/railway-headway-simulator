"""Operational throughput calculation engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-TPH-001 to P10-TPH-006: Operational throughput Q = N_counted / (T_meas / 3600)
- Measurement window partitioning: warmup, measurement window, cooldown
- Boundary crossing screenline counts and completed trip counts
- BENCH-P10-005: 25 trains in 2 hours -> Q = 12.5 trains/h
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Union

from headway.analysis.capacity_models import (
    CapacityResult,
    CapacityType,
    MeasurementWindow,
    PlanningMarginMethod,
)
from headway.infrastructure.direction import RunningDirection

if TYPE_CHECKING:
    from headway.simulation.multi_train_engine import MultiTrainSimulationResult


class ThroughputCalculator:
    """Calculates achieved operational throughput across specified measurement windows."""

    @staticmethod
    def calculate_analytical_throughput(
        train_count: int,
        duration_s: float,
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_TPH_ANALYTICAL",
        analysis_id: str = "AN_TPH_001",
    ) -> CapacityResult:
        """P10-TPH-001 & BENCH-P10-005: Analytical throughput Q = N / (T / 3600)."""
        if train_count < 0:
            raise ValueError(f"Train count must be non-negative (got {train_count}).")
        if not math.isfinite(duration_s) or duration_s <= 0.0:
            raise ValueError(f"Duration must be positive and finite (got {duration_s} s).")

        hours = duration_s / 3600.0
        throughput_tph = float(train_count) / hours
        equivalent_headway_s = (3600.0 / throughput_tph) if throughput_tph > 0.0 else float("inf")

        window = MeasurementWindow(
            warm_up_s=0.0,
            measurement_duration_s=duration_s,
            cool_down_s=0.0,
            start_time_s=0.0,
            end_time_s=duration_s,
            screenline_id="ANALYTICAL_WINDOW",
        )

        return CapacityResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.ACHIEVED_OPERATIONAL_THROUGHPUT,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="ANALYTICAL_MEASUREMENT_WINDOW",
            capacity_trains_per_hour=throughput_tph,
            headway_s=equivalent_headway_s,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=0.0,
            measurement_period_s=duration_s,
            requested_trains=train_count,
            completed_trains=train_count,
            counted_trains=train_count,
            measurement_window=window,
            details={
                "counted_trains": train_count,
                "duration_s": duration_s,
                "duration_hours": hours,
                "formula": "Q = N / (T / 3600)",
            },
        )

    @staticmethod
    def calculate_simulation_throughput(
        sim_result: "MultiTrainSimulationResult",
        measurement_window: MeasurementWindow,
        direction: Optional[RunningDirection] = None,
        count_method: str = "completed_trips",  # "completed_trips" or "screenline"
        screenline_chainage_m: Optional[float] = None,
        analysis_section: str = "SIM_SECTION",
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_TPH_SIM",
        analysis_id: str = "AN_TPH_SIM",
    ) -> CapacityResult:
        """P10-TPH-001 to 006: Compute throughput from microscopic multi-train simulation result."""
        t_start = measurement_window.window_start_s
        t_end = measurement_window.window_end_s
        duration_s = measurement_window.measurement_duration_s

        if duration_s <= 0.0:
            raise ValueError(f"Measurement window duration must be strictly positive (got {duration_s} s).")

        counted_train_ids: List[str] = []

        candidate_instances = list(sim_result.train_instances) if hasattr(sim_result, "train_instances") else []
        if direction is not None:
            candidate_instances = [tr for tr in candidate_instances if tr.running_direction == direction]

        if count_method == "completed_trips":
            for tr in candidate_instances:
                comp_t = tr.actual_completion_time_s
                if comp_t is not None and t_start <= comp_t <= t_end:
                    counted_train_ids.append(tr.train_id)
        elif count_method == "screenline":
            if screenline_chainage_m is None:
                raise ValueError("screenline_chainage_m must be provided when count_method is 'screenline'.")

            trajectories = getattr(sim_result, "trajectories", {})
            for tr in candidate_instances:
                traj = trajectories.get(tr.train_id)
                if not traj or not getattr(traj, "samples", []):
                    continue
                samples = traj.samples
                crossing_time: Optional[float] = None
                for i in range(len(samples) - 1):
                    s0 = samples[i].front_distance_m
                    s1 = samples[i + 1].front_distance_m
                    t0 = samples[i].time_s
                    t1 = samples[i + 1].time_s

                    if s0 <= screenline_chainage_m <= s1 and s1 > s0:
                        frac = (screenline_chainage_m - s0) / (s1 - s0)
                        crossing_time = t0 + frac * (t1 - t0)
                        break
                    elif s1 <= screenline_chainage_m <= s0 and s0 > s1:
                        frac = (s0 - screenline_chainage_m) / (s0 - s1)
                        crossing_time = t0 + frac * (t1 - t0)
                        break

                if crossing_time is not None and t_start <= crossing_time <= t_end:
                    counted_train_ids.append(tr.train_id)
        else:
            raise ValueError(f"Unknown count_method: '{count_method}'. Use 'completed_trips' or 'screenline'.")

        n_counted = len(counted_train_ids)
        hours = duration_s / 3600.0
        throughput_tph = float(n_counted) / hours
        equivalent_headway_s = (3600.0 / throughput_tph) if throughput_tph > 0.0 else float("inf")
        effective_dir = direction if direction is not None else RunningDirection.FORWARD

        return CapacityResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.ACHIEVED_OPERATIONAL_THROUGHPUT,
            running_direction=effective_dir,
            analysis_section=analysis_section,
            measurement_reference=f"SIMULATION_{count_method.upper()}",
            capacity_trains_per_hour=throughput_tph,
            headway_s=equivalent_headway_s,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=0.0,
            measurement_period_s=duration_s,
            requested_trains=len(candidate_instances),
            completed_trains=len([tr for tr in candidate_instances if tr.actual_completion_time_s is not None]),
            counted_trains=n_counted,
            measurement_window=measurement_window,
            details={
                "count_method": count_method,
                "counted_train_ids": counted_train_ids,
                "duration_s": duration_s,
                "duration_hours": hours,
            },
        )
