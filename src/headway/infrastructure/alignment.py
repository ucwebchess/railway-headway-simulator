"""Vertical and horizontal track alignment profiles (gradients and curvature).

Strictly satisfies RHS-P02-001 § 11 & § 12:
- P02-GRD-001 to 005: Link-based gradient intervals, reverse gradient sign inversion (+10‰ -> -10‰),
  and multi-section intersection queries for distributed train length in P03.
- P02-CUR-001 to 005: Curvature radius intervals, non-negative radius invariance in reverse,
  straight track handling, and multi-section train length intersection queries.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route


class AlignmentError(InfrastructureError):
    """Raised when track alignment data (gradients or curvature) is invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_ALIGNMENT"


@dataclass(frozen=True)
class GradientInterval:
    """A constant gradient section mapped along cumulative route distance.

    effective_gradient_decimal: In the direction of travel (+0.010 = +10‰ uphill, -0.010 = -10‰ downhill).
    """

    start_distance_m: float
    end_distance_m: float
    effective_gradient_decimal: float
    link_id: str
    physical_gradient_decimal: float
    direction: RunningDirection

    @property
    def length_m(self) -> float:
        return self.end_distance_m - self.start_distance_m

    @property
    def gradient_per_mille(self) -> float:
        """Gradient in standard engineering parts per thousand (‰)."""
        return self.effective_gradient_decimal * 1000.0


@dataclass(frozen=True)
class CurvatureInterval:
    """A constant horizontal curvature section mapped along cumulative route distance.

    radius_m: Radius of curvature in meters (None or inf denotes tangent/straight track).
    """

    start_distance_m: float
    end_distance_m: float
    radius_m: Optional[float]
    link_id: str

    @property
    def length_m(self) -> float:
        return self.end_distance_m - self.start_distance_m

    @property
    def is_curve(self) -> bool:
        return self.radius_m is not None and self.radius_m > 0 and self.radius_m < 1e9

    @property
    def curvature_1_per_m(self) -> float:
        """Curvature kappa = 1 / R."""
        if not self.is_curve or self.radius_m is None or self.radius_m == 0:
            return 0.0
        return 1.0 / abs(self.radius_m)


class RouteAlignmentProfile:
    """Combines vertical (gradient) and horizontal (curvature) profiles along a route.

    Supports both FORWARD and REVERSE routes, correctly inverting gradient signs
    while preserving non-negative curve radii.
    """

    def __init__(self, route: Route) -> None:
        self.route: Route = route
        self.gradient_intervals: List[GradientInterval] = []
        self.curvature_intervals: List[CurvatureInterval] = []
        self._build_profiles()

    def _build_profiles(self) -> None:
        """Derive direction-aware gradient and curvature intervals from route traversals."""
        for t in self.route.traversals:
            link = t.link
            phys_grad = link.gradient_decimal

            # P02-GRD-003 & BENCH-P02-004: Reverse traversal inverts gradient sign
            if t.direction.is_forward:
                eff_grad = phys_grad
            else:
                eff_grad = -phys_grad

            self.gradient_intervals.append(
                GradientInterval(
                    start_distance_m=t.start_distance_m,
                    end_distance_m=t.end_distance_m,
                    effective_gradient_decimal=eff_grad,
                    link_id=t.link_id,
                    physical_gradient_decimal=phys_grad,
                    direction=t.direction,
                )
            )

            # P02-CUR-003: Radius magnitude remains unchanged and non-negative
            radius = link.curvature_radius_m
            if radius is not None and radius <= 0:
                radius = None  # Non-positive radius indicates tangent track

            self.curvature_intervals.append(
                CurvatureInterval(
                    start_distance_m=t.start_distance_m,
                    end_distance_m=t.end_distance_m,
                    radius_m=radius,
                    link_id=t.link_id,
                )
            )

    def get_gradient_at(self, s: float) -> float:
        """Return the effective gradient (decimal) at cumulative route distance s."""
        s_clamped = max(0.0, min(self.route.total_length_m, s))
        for interval in self.gradient_intervals:
            if interval.start_distance_m <= s_clamped <= interval.end_distance_m:
                return interval.effective_gradient_decimal
        return self.gradient_intervals[-1].effective_gradient_decimal

    def get_curvature_radius_at(self, s: float) -> Optional[float]:
        """Return the curvature radius (m) at cumulative route distance s (None for tangent)."""
        s_clamped = max(0.0, min(self.route.total_length_m, s))
        for interval in self.curvature_intervals:
            if interval.start_distance_m <= s_clamped <= interval.end_distance_m:
                return interval.radius_m
        return self.curvature_intervals[-1].radius_m

    def get_gradient_intervals_intersecting(
        self, s_start: float, s_end: float
    ) -> List[Tuple[float, float, float]]:
        """P02-GRD-005: Return all gradient intervals intersecting [s_start, s_end].

        Returns list of (overlap_start_s, overlap_end_s, effective_gradient_decimal).
        Crucial for calculating distributed train length resistance in Milestone P03.
        """
        a = max(0.0, min(s_start, s_end))
        b = min(self.route.total_length_m, max(s_start, s_end))
        results: List[Tuple[float, float, float]] = []

        if a >= b:
            return [(a, a, self.get_gradient_at(a))]

        for interval in self.gradient_intervals:
            # Check intersection
            int_a = max(a, interval.start_distance_m)
            int_b = min(b, interval.end_distance_m)
            if int_a < int_b:
                results.append((int_a, int_b, interval.effective_gradient_decimal))

        return results

    def get_curvature_intervals_intersecting(
        self, s_start: float, s_end: float
    ) -> List[Tuple[float, float, Optional[float]]]:
        """P02-CUR-005: Return all curvature intervals intersecting [s_start, s_end].

        Returns list of (overlap_start_s, overlap_end_s, radius_m).
        """
        a = max(0.0, min(s_start, s_end))
        b = min(self.route.total_length_m, max(s_start, s_end))
        results: List[Tuple[float, float, Optional[float]]] = []

        if a >= b:
            return [(a, a, self.get_curvature_radius_at(a))]

        for interval in self.curvature_intervals:
            int_a = max(a, interval.start_distance_m)
            int_b = min(b, interval.end_distance_m)
            if int_a < int_b:
                results.append((int_a, int_b, interval.radius_m))

        return results
