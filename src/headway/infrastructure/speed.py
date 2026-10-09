"""Direction-aware infrastructure speed restrictions and route speed profiles.

Strictly satisfies RHS-P02-001 § 13:
- P02-SPD-001: Speed limit lookup along links and route distances.
- P02-SPD-002 & BENCH-P02-005: Direction filtering (FORWARD, REVERSE, BOTH).
- P02-SPD-003: Lowest speed governs under overlapping restrictions.
- P02-SPD-004: Train category-specific speed limits.
- P02-SPD-005 & 006: Route speed profile generation in running order without mutating infrastructure.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route


class SpeedProfileError(InfrastructureError):
    """Raised when speed restriction bounds or limits are invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_SPEED_PROFILE"


@dataclass(frozen=True)
class SpeedRestriction:
    """A physical speed restriction applied to a link interval.

    direction: "FORWARD", "REVERSE", or "BOTH".
    max_speed_ms: Maximum permitted speed in meters per second (SI).
    """

    restriction_id: str
    link_id: str
    start_offset_m: float
    end_offset_m: float
    max_speed_ms: float
    direction: str = "BOTH"
    train_category: Optional[str] = None
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.max_speed_ms <= 0:
            raise SpeedProfileError(
                f"Speed restriction '{self.restriction_id}' must have max_speed_ms > 0 (got {self.max_speed_ms}).",
                context={"restriction_id": self.restriction_id},
            )
        if self.end_offset_m <= self.start_offset_m:
            raise SpeedProfileError(
                f"Speed restriction '{self.restriction_id}' must have end_offset_m > start_offset_m.",
                context={"restriction_id": self.restriction_id},
            )
        norm_dir = self.direction.upper()
        if norm_dir not in ("FORWARD", "REVERSE", "BOTH"):
            raise SpeedProfileError(
                f"Invalid speed restriction direction '{self.direction}'. Must be FORWARD, REVERSE, or BOTH.",
                context={"restriction_id": self.restriction_id},
            )

    def applies_to_direction(self, traversal_dir: RunningDirection) -> bool:
        """P02-SPD-002: Evaluate direction compatibility."""
        norm_dir = self.direction.upper()
        if norm_dir == "BOTH":
            return True
        if norm_dir == "FORWARD":
            return traversal_dir == RunningDirection.FORWARD
        if norm_dir == "REVERSE":
            return traversal_dir == RunningDirection.REVERSE
        return False

    def applies_to_category(self, category: Optional[str]) -> bool:
        """P02-SPD-004: Evaluate train category compatibility."""
        if self.train_category is None:
            return True
        if category is None:
            return True
        return self.train_category.upper() == category.upper()


@dataclass(frozen=True)
class SpeedInterval:
    """A continuous route-distance interval with a constant maximum permissible speed."""

    start_distance_m: float
    end_distance_m: float
    max_speed_ms: float
    link_id: str
    governing_source: str  # e.g. "LINK_MAX" or restriction_id

    @property
    def length_m(self) -> float:
        return self.end_distance_m - self.start_distance_m

    @property
    def max_speed_kmh(self) -> float:
        return self.max_speed_ms * 3.6


class RouteSpeedProfile:
    """Computes the continuous permissible infrastructure speed profile along a Route.

    Evaluates baseline link speed limits combined with all active directional speed restrictions.
    P02-SPD-003: Where multiple restrictions overlap, the minimum speed governs.
    """

    def __init__(
        self,
        route: Route,
        restrictions: Optional[List[SpeedRestriction]] = None,
        train_category: Optional[str] = None,
    ) -> None:
        self.route: Route = route
        self.restrictions: List[SpeedRestriction] = list(restrictions) if restrictions else []
        self.train_category: Optional[str] = train_category
        self.speed_intervals: List[SpeedInterval] = []
        self._build_profile()

    def _build_profile(self) -> None:
        """Build piecewise speed profile along route distance."""
        # Gather all critical distance breakpoints
        breakpoints: set[float] = {0.0, self.route.total_length_m}

        for t in self.route.traversals:
            breakpoints.add(t.start_distance_m)
            breakpoints.add(t.end_distance_m)

            # Map applicable restrictions to route distance breakpoints
            for r in self.restrictions:
                if r.link_id == t.link_id and r.applies_to_direction(t.direction) and r.applies_to_category(self.train_category):
                    # Clamp physical restriction bounds to link length
                    r_start = max(0.0, min(t.length_m, r.start_offset_m))
                    r_end = max(0.0, min(t.length_m, r.end_offset_m))
                    if r_start < r_end:
                        if t.direction.is_forward:
                            s1 = t.start_distance_m + r_start
                            s2 = t.start_distance_m + r_end
                        else:
                            # P02-SPD-006: Reverse mapping
                            s1 = t.start_distance_m + (t.length_m - r_end)
                            s2 = t.start_distance_m + (t.length_m - r_start)
                        breakpoints.add(max(0.0, min(self.route.total_length_m, s1)))
                        breakpoints.add(max(0.0, min(self.route.total_length_m, s2)))

        sorted_bps = sorted(breakpoints)

        for i in range(len(sorted_bps) - 1):
            s_a = sorted_bps[i]
            s_b = sorted_bps[i + 1]
            if s_b - s_a < 1e-4:
                continue

            mid_s = 0.5 * (s_a + s_b)
            traversal = self.route.get_traversal_at_distance(mid_s)
            phys_offset = traversal.route_distance_to_physical_offset(mid_s)

            # Start with link maximum permissible speed
            gov_speed = traversal.link.max_speed_ms
            gov_source = f"LINK_{traversal.link_id}"

            # Check all restrictions covering mid_s
            for r in self.restrictions:
                if (
                    r.link_id == traversal.link_id
                    and r.applies_to_direction(traversal.direction)
                    and r.applies_to_category(self.train_category)
                ):
                    if r.start_offset_m <= phys_offset <= r.end_offset_m:
                        if r.max_speed_ms < gov_speed:
                            gov_speed = r.max_speed_ms
                            gov_source = r.restriction_id

            self.speed_intervals.append(
                SpeedInterval(
                    start_distance_m=s_a,
                    end_distance_m=s_b,
                    max_speed_ms=gov_speed,
                    link_id=traversal.link_id,
                    governing_source=gov_source,
                )
            )

    def get_max_speed_at(self, s: float) -> float:
        """P02-SPD-001: Return maximum permissible speed (m/s) at cumulative route distance s."""
        s_clamped = max(0.0, min(self.route.total_length_m, s))
        for interval in self.speed_intervals:
            if interval.start_distance_m <= s_clamped <= interval.end_distance_m:
                return interval.max_speed_ms
        return self.speed_intervals[-1].max_speed_ms

    def get_max_speed_kmh_at(self, s: float) -> float:
        return self.get_max_speed_at(s) * 3.6
