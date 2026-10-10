"""Operational reliability evaluation and acceptance criteria engine.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- P11-REL-001 to P11-REL-005: Configurable reliability criteria evaluation
- Multi-criteria assessment (punctuality, mean delay, P95 delay, TVS waiting, queue stability)
- Benchmark B: 95/100 completed journeys satisfying delay threshold -> R = 0.95 (95%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np

from headway.analysis.statistics import StatisticalSummary, compute_wilson_score_interval


@dataclass
class ReliabilityCriterion:
    """P11 Section 25: User-defined reliability performance threshold."""

    criterion_id: str
    metric_name: str  # e.g., "PUNCTUALITY_PERCENT", "MEAN_DELAY_S", "P95_DELAY_S", "MAX_QUEUE", "TVS_WAITING_S"
    comparison_operator: str  # "<=", ">=", "<", ">"
    threshold_value: float
    delay_tolerance_s: Optional[float] = 180.0
    confidence_level: float = 0.95
    description: str = ""

    def __post_init__(self) -> None:
        op = self.comparison_operator.strip()
        if op not in ("<=", "<", ">=", ">"):
            raise ValueError(f"Unsupported comparison operator: '{self.comparison_operator}'. Must be one of <=, <, >=, >.")

    def evaluate(self, observed_val: float) -> bool:
        """Evaluate whether observed_val satisfies the criterion."""
        op = self.comparison_operator.strip()
        if op == "<=":
            return observed_val <= self.threshold_value + 1e-9
        elif op == "<":
            return observed_val < self.threshold_value
        elif op == ">=":
            return observed_val >= self.threshold_value - 1e-9
        elif op == ">":
            return observed_val > self.threshold_value
        else:
            raise ValueError(f"Unknown comparison operator: '{self.comparison_operator}'")


@dataclass
class CriterionEvaluationResult:
    """Evaluation result for an individual reliability criterion."""

    criterion_id: str
    metric_name: str
    passed: bool
    observed_value: float
    threshold_value: float
    comparison_operator: str
    confidence_interval: Optional[Tuple[float, float]] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReliabilityEvaluationResult:
    """P11 Section 27: Comprehensive reliability deliverable across a Monte Carlo replication set."""

    scenario_id: str
    total_replications: int
    valid_replications: int
    all_criteria_passed: bool
    criterion_results: Dict[str, CriterionEvaluationResult] = field(default_factory=dict)
    observed_punctuality_ratio: float = 1.0
    confidence_interval_punctuality: Optional[Tuple[float, float]] = None
    diagnostic_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "total_replications": self.total_replications,
            "valid_replications": self.valid_replications,
            "all_criteria_passed": self.all_criteria_passed,
            "observed_punctuality_ratio": round(self.observed_punctuality_ratio, 4),
            "confidence_interval_punctuality": self.confidence_interval_punctuality,
            "criterion_results": {
                k: {
                    "passed": v.passed,
                    "observed_value": round(v.observed_value, 4),
                    "threshold_value": round(v.threshold_value, 4),
                    "comparison": v.comparison_operator,
                }
                for k, v in self.criterion_results.items()
            },
            "diagnostic_summary": self.diagnostic_summary,
        }


class ReliabilityEvaluator:
    """Evaluates Monte Carlo replication metrics against operational reliability criteria."""

    @staticmethod
    def evaluate_punctuality_benchmark(
        satisfying_journeys: int,
        total_journeys: int,
    ) -> Tuple[float, Tuple[float, float]]:
        """P11 BENCHMARK B: R = satisfying_journeys / total_journeys (e.g. 95/100 = 0.95)."""
        return compute_wilson_score_interval(satisfying_journeys, total_journeys)

    @classmethod
    def evaluate_replications(
        cls,
        criteria: Sequence[ReliabilityCriterion],
        arrival_delays_s: Sequence[float],
        tvs_waitings_s: Sequence[float],
        max_queues: Sequence[int],
        throughputs_tph: Sequence[float],
        scenario_id: str = "BASELINE",
        total_replications: int = 1,
        valid_replications: int = 1,
    ) -> ReliabilityEvaluationResult:
        """Evaluate a comprehensive set of operational criteria across all simulated replications."""
        criterion_results: Dict[str, CriterionEvaluationResult] = {}
        all_passed = True

        # Extract basic delay metrics
        clean_delays = [d for d in arrival_delays_s if math.isfinite(d)]
        clean_tvs = [t for t in tvs_waitings_s if math.isfinite(t)]
        clean_queues = [q for q in max_queues if math.isfinite(q)]
        clean_tph = [q for q in throughputs_tph if math.isfinite(q)]

        # Benchmark B punctuality evaluation
        delay_tol = 180.0
        for crit in criteria:
            if "PUNCTUALITY" in crit.metric_name.upper():
                delay_tol = crit.delay_tolerance_s or 180.0

        n_trains = len(clean_delays)
        punctual_trains = sum(1 for d in clean_delays if d <= delay_tol)
        punc_ratio, punc_ci = compute_wilson_score_interval(punctual_trains, n_trains) if n_trains > 0 else (1.0, (1.0, 1.0))

        for crit in criteria:
            u_name = crit.metric_name.upper()
            obs_val = 0.0
            ci_val = None

            if "PUNCTUALITY" in u_name:
                obs_val = punc_ratio * 100.0  # percentage
                ci_val = (punc_ci[0] * 100.0, punc_ci[1] * 100.0)
            elif "MEAN_DELAY" in u_name:
                obs_val = float(np.mean(clean_delays)) if clean_delays else 0.0
            elif "P95_DELAY" in u_name:
                obs_val = float(np.percentile(clean_delays, 95)) if clean_delays else 0.0
            elif "MAX_DELAY" in u_name:
                obs_val = float(np.max(clean_delays)) if clean_delays else 0.0
            elif "TVS" in u_name:
                obs_val = float(np.mean(clean_tvs)) if clean_tvs else 0.0
            elif "QUEUE" in u_name:
                obs_val = float(np.max(clean_queues)) if clean_queues else 0.0
            elif "THROUGHPUT" in u_name:
                obs_val = float(np.mean(clean_tph)) if clean_tph else 0.0

            passed = crit.evaluate(obs_val)
            if not passed:
                all_passed = False

            criterion_results[crit.criterion_id] = CriterionEvaluationResult(
                criterion_id=crit.criterion_id,
                metric_name=crit.metric_name,
                passed=passed,
                observed_value=obs_val,
                threshold_value=crit.threshold_value,
                comparison_operator=crit.comparison_operator,
                confidence_interval=ci_val,
                details={"delay_tolerance_s": delay_tol},
            )

        summary = (
            f"Evaluated {len(criteria)} reliability criteria across {valid_replications} valid replications. "
            f"Overall Status: {'PASSED' if all_passed else 'FAILED'}. "
            f"Observed Punctuality: {punc_ratio:.1%} (delay <= {delay_tol:.0f}s)."
        )

        return ReliabilityEvaluationResult(
            scenario_id=scenario_id,
            total_replications=total_replications,
            valid_replications=valid_replications,
            all_criteria_passed=all_passed,
            criterion_results=criterion_results,
            observed_punctuality_ratio=punc_ratio,
            confidence_interval_punctuality=punc_ci,
            diagnostic_summary=summary,
        )
