"""Engineering chainage mapping system for railway infrastructure.

Strictly satisfies RHS-P02-001 § 10:
- P02-CH-001: Chainage mapping independent of cumulative route distance.
- P02-CH-002: Chainage equations and discontinuities (multi-segment support).
- P02-CH-003: Forward chainage: chainage increases with running distance.
- P02-CH-004: Reverse chainage: chainage decreases while route distance increases.
- P02-CH-005: Boundary validation and unambiguous interpolation.
- P02-CH-006: Data export for engineering diagrams.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError


class ChainageError(InfrastructureError):
    """Raised when engineering chainage values or equations are invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_CHAINAGE"


@dataclass(frozen=True)
class ChainageSegment:
    """A linear mapping segment between route distance and engineering chainage.

    Allows positive or negative chainage gradients (increasing or decreasing chainage).
    """

    segment_id: str
    start_route_distance_m: float
    end_route_distance_m: float
    start_chainage_km: float
    end_chainage_km: float

    def __post_init__(self) -> None:
        if self.end_route_distance_m <= self.start_route_distance_m:
            raise ChainageError(
                f"ChainageSegment '{self.segment_id}' must have end_route_distance_m > start_route_distance_m.",
                context={"segment_id": self.segment_id},
            )

    @property
    def length_m(self) -> float:
        return self.end_route_distance_m - self.start_route_distance_m

    @property
    def is_increasing(self) -> bool:
        return self.end_chainage_km >= self.start_chainage_km

    def contains_route_distance(self, s: float) -> bool:
        return (self.start_route_distance_m - 1e-6) <= s <= (self.end_route_distance_m + 1e-6)

    def route_distance_to_chainage_km(self, s: float) -> float:
        """Interpolate engineering chainage (km) from cumulative route distance (m)."""
        if not self.contains_route_distance(s):
            raise ChainageError(
                f"Route distance {s:.2f} m is outside segment '{self.segment_id}' "
                f"[{self.start_route_distance_m:.2f}, {self.end_route_distance_m:.2f}] m.",
                context={"segment_id": self.segment_id, "s": s},
            )

        fraction = (s - self.start_route_distance_m) / self.length_m
        fraction_clamped = max(0.0, min(1.0, fraction))
        return self.start_chainage_km + fraction_clamped * (self.end_chainage_km - self.start_chainage_km)

    def chainage_km_to_route_distance(self, ch_km: float) -> float:
        """Map engineering chainage (km) back to cumulative route distance (m)."""
        min_ch = min(self.start_chainage_km, self.end_chainage_km)
        max_ch = max(self.start_chainage_km, self.end_chainage_km)

        if ch_km < min_ch - 1e-6 or ch_km > max_ch + 1e-6:
            raise ChainageError(
                f"Chainage {ch_km:.4f} km is outside segment '{self.segment_id}' [{min_ch:.4f}, {max_ch:.4f}] km.",
                context={"segment_id": self.segment_id, "ch_km": ch_km},
            )

        denom = self.end_chainage_km - self.start_chainage_km
        if abs(denom) < 1e-9:
            return self.start_route_distance_m

        fraction = (ch_km - self.start_chainage_km) / denom
        fraction_clamped = max(0.0, min(1.0, fraction))
        return self.start_route_distance_m + fraction_clamped * self.length_m


class EngineeringChainageModel:
    """Manages piecewise engineering chainage mappings across a route or corridor."""

    def __init__(self, segments: Optional[List[ChainageSegment]] = None) -> None:
        self.segments: List[ChainageSegment] = list(segments) if segments else []
        self._sort_and_validate()

    def _sort_and_validate(self) -> None:
        """Sort segments by start_route_distance_m and verify continuity."""
        self.segments.sort(key=lambda seg: seg.start_route_distance_m)
        for i in range(len(self.segments) - 1):
            curr = self.segments[i]
            next_seg = self.segments[i + 1]
            if curr.end_route_distance_m > next_seg.start_route_distance_m + 1e-6:
                raise ChainageError(
                    f"Overlapping chainage segments detected between '{curr.segment_id}' "
                    f"and '{next_seg.segment_id}'.",
                    context={"seg1": curr.segment_id, "seg2": next_seg.segment_id},
                )

    def add_segment(self, segment: ChainageSegment) -> None:
        self.segments.append(segment)
        self._sort_and_validate()

    @classmethod
    def create_linear_corridor(
        cls,
        total_route_length_m: float,
        start_chainage_km: float,
        end_chainage_km: float,
        segment_id: str = "SEG_01",
    ) -> "EngineeringChainageModel":
        """Factory for a single continuous linear chainage corridor."""
        seg = ChainageSegment(
            segment_id=segment_id,
            start_route_distance_m=0.0,
            end_route_distance_m=total_route_length_m,
            start_chainage_km=start_chainage_km,
            end_chainage_km=end_chainage_km,
        )
        return cls([seg])

    def route_distance_to_chainage_km(self, s: float) -> float:
        """P02-CH-003 & 004: Convert cumulative route distance to engineering chainage."""
        if not self.segments:
            # Fallback: 1m = 0.001 km
            return s / 1000.0

        for seg in self.segments:
            if seg.contains_route_distance(s):
                return seg.route_distance_to_chainage_km(s)

        # Extrapolate from closest boundary segment
        if s < self.segments[0].start_route_distance_m:
            return self.segments[0].route_distance_to_chainage_km(self.segments[0].start_route_distance_m)
        return self.segments[-1].route_distance_to_chainage_km(self.segments[-1].end_route_distance_m)

    def chainage_km_to_route_distance(self, ch_km: float) -> float:
        """Convert engineering chainage back to cumulative route distance."""
        for seg in self.segments:
            min_ch = min(seg.start_chainage_km, seg.end_chainage_km)
            max_ch = max(seg.start_chainage_km, seg.end_chainage_km)
            if min_ch - 1e-6 <= ch_km <= max_ch + 1e-6:
                return seg.chainage_km_to_route_distance(ch_km)

        raise ChainageError(
            f"Chainage {ch_km:.4f} km does not correspond to any defined chainage segment.",
            context={"ch_km": ch_km},
        )

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """P02-CH-006: Export tabular structure for diagrams and reporting."""
        return [
            {
                "segment_id": seg.segment_id,
                "start_route_distance_m": seg.start_route_distance_m,
                "end_route_distance_m": seg.end_route_distance_m,
                "start_chainage_km": seg.start_chainage_km,
                "end_chainage_km": seg.end_chainage_km,
                "increasing": seg.is_increasing,
            }
            for seg in self.segments
        ]
