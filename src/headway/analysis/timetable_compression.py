"""UIC 406-inspired timetable compression engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-UIC-001: Compression of train paths up to minimum safety buffer without altering running times or dwells
- P10-UIC-004: Explicit disclaimer that this is a UIC 406-inspired model and not a formal UIC certification
- P10-UIC-005: Directional and bidirectional compression
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from headway.analysis.capacity_models import TimetableCompressionResult
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceUsageRecord


class TrainPathStairway:
    """Represents the blocking time stairway of a single train across ordered resources."""

    def __init__(
        self,
        train_id: str,
        departure_time_s: float,
        resource_intervals: List[Tuple[str, float, float]],  # (resource_id, start_s, end_s)
        direction: RunningDirection = RunningDirection.FORWARD,
    ) -> None:
        self.train_id = train_id
        self.departure_time_s = departure_time_s
        self.resource_intervals = resource_intervals
        self.direction = direction

        # Relative timings from departure time
        self.relative_intervals: List[Tuple[str, float, float]] = []
        for res_id, start_s, end_s in resource_intervals:
            self.relative_intervals.append((res_id, start_s - departure_time_s, end_s - departure_time_s))

    @property
    def total_run_duration_s(self) -> float:
        if not self.resource_intervals:
            return 0.0
        return max(e for _, _, e in self.resource_intervals) - min(s for _, s, _ in self.resource_intervals)


class TimetableCompressor:
    """Compresses train paths in chronological sequence to calculate compressed timetable duration."""

    UIC_DISCLAIMER = (
        "This timetable compression and capacity consumption evaluation is an analytical engineering "
        "model inspired by UIC 406 principles and methodology. It is developed independently for railway "
        "headway and capacity simulation and does not claim or constitute formal certification, verification, "
        "or endorsement by the International Union of Railways (UIC)."
    )

    def __init__(self, buffer_time_s: float = 0.0) -> None:
        """buffer_time_s: Minimum buffer time between compressed paths (default 0.0 for pure compression)."""
        self.buffer_time_s = max(0.0, float(buffer_time_s))

    def compress_stairways(
        self,
        stairways: Sequence[TrainPathStairway],
        corridor_id: str = "CORRIDOR_MAIN",
    ) -> TimetableCompressionResult:
        """Compress a sequence of train paths along a corridor."""
        if not stairways:
            return TimetableCompressionResult(
                corridor_id=corridor_id,
                train_count=0,
                original_duration_s=0.0,
                compressed_duration_s=0.0,
                compression_ratio=1.0,
                compressed_train_departures={},
                uic_disclaimer=self.UIC_DISCLAIMER,
            )

        # Sort trains by scheduled departure time
        sorted_stairways = sorted(stairways, key=lambda s: s.departure_time_s)

        # Compute original timetable span
        orig_start = min(s.departure_time_s for s in sorted_stairways)
        orig_end = max(max(e for _, _, e in s.resource_intervals) if s.resource_intervals else s.departure_time_s for s in sorted_stairways)
        orig_duration = max(0.0, orig_end - orig_start)

        # Compressed simulation: track latest release time of each resource
        # resource_id -> latest release time
        resource_busy_until: Dict[str, float] = {}
        compressed_departures: Dict[str, float] = {}

        compressed_min_time: Optional[float] = None
        compressed_max_time: Optional[float] = None

        for idx, train in enumerate(sorted_stairways):
            if idx == 0:
                t_dep = 0.0
            else:
                # Find earliest departure t_dep >= previous train departure
                # such that for all resources train occupies, t_dep + rel_start >= resource_busy_until[res] + buffer
                prev_dep = compressed_departures[sorted_stairways[idx - 1].train_id]
                t_dep = prev_dep

                for res_id, rel_start, _ in train.relative_intervals:
                    if res_id in resource_busy_until:
                        req_earliest = resource_busy_until[res_id] + self.buffer_time_s - rel_start
                        if req_earliest > t_dep:
                            t_dep = req_earliest

            compressed_departures[train.train_id] = t_dep

            # Update resource busy until times and overall span
            for res_id, rel_start, rel_end in train.relative_intervals:
                abs_start = t_dep + rel_start
                abs_end = t_dep + rel_end
                resource_busy_until[res_id] = max(resource_busy_until.get(res_id, 0.0), abs_end)

                if compressed_min_time is None or abs_start < compressed_min_time:
                    compressed_min_time = abs_start
                if compressed_max_time is None or abs_end > compressed_max_time:
                    compressed_max_time = abs_end

        if compressed_min_time is None:
            compressed_min_time = 0.0
        if compressed_max_time is None:
            compressed_max_time = 0.0

        compressed_duration = max(0.0, compressed_max_time - compressed_min_time)
        comp_ratio = (compressed_duration / orig_duration) if orig_duration > 0.0 else 1.0

        return TimetableCompressionResult(
            corridor_id=corridor_id,
            train_count=len(sorted_stairways),
            original_duration_s=orig_duration,
            compressed_duration_s=compressed_duration,
            compression_ratio=comp_ratio,
            compressed_train_departures=compressed_departures,
            uic_disclaimer=self.UIC_DISCLAIMER,
            details={
                "buffer_time_s": self.buffer_time_s,
                "compressed_start_s": compressed_min_time,
                "compressed_end_s": compressed_max_time,
            },
        )

    def build_stairways_from_usage_records(
        self,
        records: Sequence[ResourceUsageRecord],
    ) -> List[TrainPathStairway]:
        """Convert ResourceUsageRecord items from a multi-train simulation into TrainPathStairway objects."""
        # Group records by train_id
        grouped: Dict[str, List[ResourceUsageRecord]] = {}
        for r in records:
            grouped.setdefault(r.train_id, []).append(r)

        stairways: List[TrainPathStairway] = []
        for train_id, r_list in grouped.items():
            if not r_list:
                continue
            dep_time = min(r.reservation_start_s for r in r_list)
            direction = r_list[0].running_direction

            ivs: List[Tuple[str, float, float]] = []
            for r in r_list:
                b_start = r.reservation_start_s
                b_end = r.final_release_s if r.final_release_s is not None else (r.release_eligibility_s or (b_start + 60.0))
                ivs.append((r.resource_id, b_start, b_end))

            stairways.append(TrainPathStairway(
                train_id=train_id,
                departure_time_s=dep_time,
                resource_intervals=ivs,
                direction=direction,
            ))

        return stairways
