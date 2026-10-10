"""Reliability-based railway capacity calculation engine.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- P11-RCAP-001 to P11-RCAP-007: Integration of P10 capacity search with Monte Carlo operational reliability
- Tests candidate demand rates under operational variability
- Acceptance requires satisfaction of all configured reliability criteria
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from headway.analysis.capacity_models import (
    CapacityResult,
    CapacityType,
    OperationalStabilityStatus,
    PlanningMarginMethod,
)
from headway.analysis.monte_carlo import MonteCarloExecutionResult
from headway.analysis.reliability import ReliabilityCriterion, ReliabilityEvaluationResult
from headway.infrastructure.direction import RunningDirection


class ReliabilityBasedCapacityCalculator:
    """Calculates maximum sustainable railway capacity meeting operational reliability criteria."""

    @staticmethod
    def evaluate_demand_rate_sweep(
        candidate_demand_rates_tph: Sequence[float],
        mc_runner_factory: Callable[[float], MonteCarloExecutionResult],
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        analysis_id: str = "RCAP_SWEEP_001",
    ) -> Tuple[CapacityResult, List[Tuple[float, MonteCarloExecutionResult, bool]]]:
        """P11-RCAP-002 & 003: Evaluates candidate demand rates and determines highest reliable capacity."""
        if not candidate_demand_rates_tph:
            raise ValueError("Candidate demand rates list cannot be empty.")

        sorted_rates = sorted(candidate_demand_rates_tph)
        results_per_rate: List[Tuple[float, MonteCarloExecutionResult, bool]] = []

        highest_reliable_rate = 0.0
        best_mc_result: Optional[MonteCarloExecutionResult] = None

        for rate in sorted_rates:
            if rate <= 0.0:
                continue

            mc_res = mc_runner_factory(rate)
            rel_eval = mc_res.reliability_evaluation

            # Demand rate is acceptable if all criteria passed and simulation had valid runs
            is_acceptable = (
                mc_res.valid_replications > 0
                and mc_res.failed_replications == 0
                and rel_eval is not None
                and rel_eval.all_criteria_passed
            )

            results_per_rate.append((rate, mc_res, is_acceptable))

            if is_acceptable:
                highest_reliable_rate = rate
                best_mc_result = mc_res
            else:
                # Instability or reliability failure detected: stop ascending scan
                break

        headway_s = (3600.0 / highest_reliable_rate) if highest_reliable_rate > 0.0 else float("inf")

        cap_result = CapacityResult(
            run_id=f"RCAP_OPT_{highest_reliable_rate:.1f}TPH",
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.SUSTAINABLE_OPERATIONAL_CAPACITY,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="MONTE_CARLO_RELIABILITY_CAPACITY",
            capacity_trains_per_hour=highest_reliable_rate,
            headway_s=headway_s,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=0.0,
            details={
                "methodology": "Monte Carlo reliability-based capacity testing",
                "evaluated_rates_tph": [r for r, _, _ in results_per_rate],
                "acceptance_per_rate": [acc for _, _, acc in results_per_rate],
                "certified_reliable_capacity_tph": highest_reliable_rate,
            },
        )

        return cap_result, results_per_rate
