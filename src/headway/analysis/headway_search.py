"""Iterative numerical headway search engine.

Strictly satisfies RHS-P08-001 § 12:
- P08-SRCH-001: Testing candidate leader-follower separations.
- P08-SRCH-002: Feasibility evaluation.
- P08-SRCH-003 & 004: Valid lower and upper bounds.
- P08-SRCH-005: Target search tolerance (default 0.1s).
- P08-SRCH-007: Diagnosed NOT_CONVERGED failure return.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from headway.analysis.headway_results import HeadwayValidationStatus


@dataclass
class SearchIterationStep:
    """Audit record of an individual search step."""

    iteration: int
    candidate_headway_s: float
    is_feasible: bool
    lower_bound_s: float
    upper_bound_s: float
    diagnostic_note: Optional[str] = None


@dataclass
class SearchResult:
    """Result of iterative headway search."""

    optimal_headway_s: float
    iterations_count: int
    validation_status: HeadwayValidationStatus
    history: List[SearchIterationStep]
    diagnostic_message: Optional[str] = None


class IterativeHeadwaySearch:
    """Bisection-based iterative headway search engine."""

    def __init__(
        self,
        tolerance_s: float = 0.1,
        max_iterations: int = 50,
    ) -> None:
        self.tolerance_s = tolerance_s
        self.max_iterations = max_iterations

    def search(
        self,
        feasibility_checker: Callable[[float], Tuple[bool, Optional[str]]],
        lower_bound_s: float,
        upper_bound_s: float,
    ) -> SearchResult:
        """P08-SRCH: Searches for minimum feasible headway in [lower_bound_s, upper_bound_s].

        feasibility_checker(h) returns (is_feasible, note).
        """
        history: List[SearchIterationStep] = []

        # 1. Validate upper bound feasibility
        is_upper_ok, upper_note = feasibility_checker(upper_bound_s)
        if not is_upper_ok:
            return SearchResult(
                optimal_headway_s=upper_bound_s,
                iterations_count=0,
                validation_status=HeadwayValidationStatus.INFEASIBLE,
                history=[],
                diagnostic_message=f"Upper search bound {upper_bound_s:.1f}s is infeasible: {upper_note}",
            )

        # 2. Check if lower bound is already feasible
        is_lower_ok, lower_note = feasibility_checker(lower_bound_s)
        if is_lower_ok:
            return SearchResult(
                optimal_headway_s=lower_bound_s,
                iterations_count=1,
                validation_status=HeadwayValidationStatus.VALID,
                history=[
                    SearchIterationStep(
                        iteration=1,
                        candidate_headway_s=lower_bound_s,
                        is_feasible=True,
                        lower_bound_s=lower_bound_s,
                        upper_bound_s=upper_bound_s,
                        diagnostic_note="Lower bound immediately feasible",
                    )
                ],
            )

        # 3. Bisection loop
        low = lower_bound_s
        high = upper_bound_s

        for it in range(1, self.max_iterations + 1):
            mid = round((low + high) / 2.0, 6)
            is_ok, note = feasibility_checker(mid)

            history.append(
                SearchIterationStep(
                    iteration=it,
                    candidate_headway_s=mid,
                    is_feasible=is_ok,
                    lower_bound_s=low,
                    upper_bound_s=high,
                    diagnostic_note=note,
                )
            )

            if is_ok:
                high = mid
            else:
                low = mid

            if (high - low) <= self.tolerance_s:
                return SearchResult(
                    optimal_headway_s=round(high, 3),
                    iterations_count=it,
                    validation_status=HeadwayValidationStatus.VALID,
                    history=history,
                )

        return SearchResult(
            optimal_headway_s=round(high, 3),
            iterations_count=self.max_iterations,
            validation_status=HeadwayValidationStatus.NOT_CONVERGED,
            history=history,
            diagnostic_message=f"Search did not converge to tolerance {self.tolerance_s}s within {self.max_iterations} iterations",
        )
