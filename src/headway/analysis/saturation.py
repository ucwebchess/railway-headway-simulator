"""Capacity saturation search engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-SAT-001 to P10-SAT-005: Systematic saturation search for sustainable operational capacity
- Bisection search and discrete step-scan search algorithms
- Integrates with OperationalStabilityEvaluator
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple, Union

from headway.analysis.capacity_models import (
    CapacityResult,
    CapacityType,
    OperationalStabilityStatus,
    PlanningMarginMethod,
    StabilityEvaluation,
)
from headway.analysis.stability import OperationalStabilityEvaluator
from headway.infrastructure.direction import RunningDirection

if TYPE_CHECKING:
    from headway.simulation.multi_train_engine import MultiTrainSimulationResult


class CapacitySaturationSearch:
    """Finds maximum sustainable operational capacity by searching candidate demand rates."""

    def __init__(
        self,
        stability_evaluator: Optional[OperationalStabilityEvaluator] = None,
    ) -> None:
        self.stability_evaluator = stability_evaluator or OperationalStabilityEvaluator()

    def run_step_scan(
        self,
        candidate_demand_rates_tph: List[float],
        simulation_runner: Callable[[float], MultiTrainSimulationResult],
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        analysis_id: str = "AN_SAT_SCAN",
    ) -> Tuple[CapacityResult, List[Tuple[float, StabilityEvaluation]]]:
        """Scans candidate demand rates in ascending order until instability is detected."""
        if not candidate_demand_rates_tph:
            raise ValueError("Candidate demand rates list cannot be empty.")

        sorted_rates = sorted(candidate_demand_rates_tph)
        evaluations: List[Tuple[float, StabilityEvaluation]] = []

        highest_stable_rate = 0.0
        best_stability: Optional[StabilityEvaluation] = None

        for rate in sorted_rates:
            if rate <= 0.0:
                continue
            sim_res = simulation_runner(rate)
            eval_res = self.stability_evaluator.evaluate_simulation(sim_res, run_id=f"SCAN_{rate:.1f}TPH")
            evaluations.append((rate, eval_res))

            if eval_res.is_sustainable:
                highest_stable_rate = rate
                best_stability = eval_res
            else:
                # Instability encountered, stop search
                break

        headway_s = (3600.0 / highest_stable_rate) if highest_stable_rate > 0.0 else float("inf")

        cap_result = CapacityResult(
            run_id=best_stability.run_id if best_stability else "NO_STABLE_RUN",
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.SUSTAINABLE_OPERATIONAL_CAPACITY,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="STEP_SCAN_SATURATION",
            capacity_trains_per_hour=highest_stable_rate,
            headway_s=headway_s,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=0.0,
            stability_evaluation=best_stability,
            details={
                "search_method": "step_scan",
                "evaluated_rates_tph": [r for r, _ in evaluations],
                "statuses": [e.status.value for _, e in evaluations],
            },
        )

        return cap_result, evaluations

    def run_bisection_search(
        self,
        min_demand_tph: float,
        max_demand_tph: float,
        simulation_runner: Callable[[float], MultiTrainSimulationResult],
        tolerance_tph: float = 0.5,
        max_iterations: int = 10,
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        analysis_id: str = "AN_SAT_BISECT",
    ) -> Tuple[CapacityResult, List[Tuple[float, StabilityEvaluation]]]:
        """Binary bisection search between min_demand_tph (assumed stable) and max_demand_tph."""
        if min_demand_tph <= 0.0 or max_demand_tph <= min_demand_tph:
            raise ValueError(f"Invalid bisection bounds: [{min_demand_tph}, {max_demand_tph}].")

        evaluations: List[Tuple[float, StabilityEvaluation]] = []

        # Check lower bound
        sim_low = simulation_runner(min_demand_tph)
        eval_low = self.stability_evaluator.evaluate_simulation(sim_low, run_id=f"BISECT_LOW_{min_demand_tph:.1f}")
        evaluations.append((min_demand_tph, eval_low))

        if not eval_low.is_sustainable:
            # Even minimum demand is unstable
            headway_s = 3600.0 / min_demand_tph
            cap_result = CapacityResult(
                run_id=eval_low.run_id,
                analysis_id=analysis_id,
                scenario_id=scenario_id,
                capacity_type=CapacityType.SUSTAINABLE_OPERATIONAL_CAPACITY,
                running_direction=direction,
                analysis_section=analysis_section,
                measurement_reference="BISECTION_SATURATION",
                capacity_trains_per_hour=0.0,
                headway_s=float("inf"),
                planning_margin_method=PlanningMarginMethod.NONE,
                planning_margin_value=0.0,
                stability_evaluation=eval_low,
                details={"search_method": "bisection", "note": "Min demand is already unstable."},
            )
            return cap_result, evaluations

        # Check upper bound
        sim_high = simulation_runner(max_demand_tph)
        eval_high = self.stability_evaluator.evaluate_simulation(sim_high, run_id=f"BISECT_HIGH_{max_demand_tph:.1f}")
        evaluations.append((max_demand_tph, eval_high))

        if eval_high.is_sustainable:
            # Even maximum demand is stable
            headway_s = 3600.0 / max_demand_tph
            cap_result = CapacityResult(
                run_id=eval_high.run_id,
                analysis_id=analysis_id,
                scenario_id=scenario_id,
                capacity_type=CapacityType.SUSTAINABLE_OPERATIONAL_CAPACITY,
                running_direction=direction,
                analysis_section=analysis_section,
                measurement_reference="BISECTION_SATURATION",
                capacity_trains_per_hour=max_demand_tph,
                headway_s=headway_s,
                planning_margin_method=PlanningMarginMethod.NONE,
                planning_margin_value=0.0,
                stability_evaluation=eval_high,
                details={"search_method": "bisection", "note": "Max demand is stable."},
            )
            return cap_result, evaluations

        low = min_demand_tph
        high = max_demand_tph
        best_stable_rate = low
        best_eval = eval_low

        iteration = 0
        while (high - low) > tolerance_tph and iteration < max_iterations:
            iteration += 1
            mid = (low + high) / 2.0
            sim_mid = simulation_runner(mid)
            eval_mid = self.stability_evaluator.evaluate_simulation(sim_mid, run_id=f"BISECT_ITER_{iteration}_{mid:.1f}")
            evaluations.append((mid, eval_mid))

            if eval_mid.is_sustainable:
                low = mid
                best_stable_rate = mid
                best_eval = eval_mid
            else:
                high = mid

        headway_s = 3600.0 / best_stable_rate if best_stable_rate > 0.0 else float("inf")
        cap_result = CapacityResult(
            run_id=best_eval.run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.SUSTAINABLE_OPERATIONAL_CAPACITY,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="BISECTION_SATURATION",
            capacity_trains_per_hour=best_stable_rate,
            headway_s=headway_s,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=0.0,
            stability_evaluation=best_eval,
            details={
                "search_method": "bisection",
                "iterations": iteration,
                "tolerance_tph": tolerance_tph,
                "converged_bound_low": low,
                "converged_bound_high": high,
            },
        )

        return cap_result, evaluations
