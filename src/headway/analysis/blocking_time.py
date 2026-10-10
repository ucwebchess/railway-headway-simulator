"""Resource blocking intervals, timeline construction, and seven-component decomposition.

Strictly satisfies RHS-P08-001:
- § 6: Resource Blocking Intervals (P08-BT-001 to P08-BT-006).
- § 7: Seven-Component Blocking-Time Decomposition (P08-BT-007 to P08-BT-016).
- § 22: Standalone Resource Blocking Durations & Longest Occupation (P08-OCC-001 to P08-OCC-004).
- Half-open interval convention: B = [t_blocking_start, t_release).
- Full support for both FORWARD and REVERSE railway movements.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import (
    ResourceCategory,
    ResourceEventType,
    ResourceUsageRecord,
    SignallingEvent,
)


class BlockingTimeComponent(str, Enum):
    """P08-BT-007 to 013: Seven canonical blocking-time decomposition components."""

    SETUP = "SETUP"                               # t1: route locking, switch movement, aspect progression
    APPROACH = "APPROACH"                         # t2: sighting and approach running time prior to block entry
    RUNNING = "RUNNING"                           # t3: train-front running time across block length
    DWELL = "DWELL"                               # t4: scheduled/simulated passenger dwell while front inside block
    GEOMETRIC_CLEARANCE = "GEOMETRIC_CLEARANCE"   # t5: moving time after front exit until rear clears block
    RESIDUAL_REAR = "RESIDUAL_REAR"               # t6: stationary occupation after front exit while rear inside upstream
    RELEASE = "RELEASE"                           # t7: track circuit debounce, release delay timer, route unlock


@dataclass
class BlockingTimeDecomposition:
    """Additive seven-component decomposition of a resource blocking interval."""

    setup_time_s: float = 0.0
    approach_time_s: float = 0.0
    running_time_s: float = 0.0
    dwell_time_s: float = 0.0
    geometric_clearance_time_s: float = 0.0
    residual_rear_time_s: float = 0.0
    release_time_s: float = 0.0
    reconciliation_difference_s: float = 0.0
    reconciliation_note: Optional[str] = None

    @property
    def total_duration_s(self) -> float:
        """P08-BT-015: Sum of the seven non-overlapping additive components."""
        return (
            self.setup_time_s
            + self.approach_time_s
            + self.running_time_s
            + self.dwell_time_s
            + self.geometric_clearance_time_s
            + self.residual_rear_time_s
            + self.release_time_s
        )

    @property
    def is_reconciled(self) -> bool:
        """True if sum of components matches total blocking duration within numerical tolerance."""
        return abs(self.reconciliation_difference_s) <= 1e-3

    def to_dict(self) -> Dict[str, float]:
        return {
            "setup_time_s": round(self.setup_time_s, 3),
            "approach_time_s": round(self.approach_time_s, 3),
            "running_time_s": round(self.running_time_s, 3),
            "dwell_time_s": round(self.dwell_time_s, 3),
            "geometric_clearance_time_s": round(self.geometric_clearance_time_s, 3),
            "residual_rear_time_s": round(self.residual_rear_time_s, 3),
            "release_time_s": round(self.release_time_s, 3),
            "total_duration_s": round(self.total_duration_s, 3),
            "reconciliation_difference_s": round(self.reconciliation_difference_s, 3),
        }


@dataclass
class ResourceBlockingInterval:
    """P08-BT-001: Half-open resource blocking interval B = [t_start, t_end)."""

    interval_id: str
    resource_id: str
    resource_category: ResourceCategory
    train_id: str
    start_time_s: float
    end_time_s: float
    route_id: Optional[str] = None
    running_direction: RunningDirection = RunningDirection.FORWARD
    front_entry_time_s: Optional[float] = None
    front_exit_time_s: Optional[float] = None
    rear_clearance_time_s: Optional[float] = None
    dwell_start_time_s: Optional[float] = None
    dwell_end_time_s: Optional[float] = None
    decomposition: Optional[BlockingTimeDecomposition] = None
    physical_start_offset_m: Optional[float] = None
    physical_end_offset_m: Optional[float] = None
    capacity: int = 1
    usage_index: int = 1
    description: Optional[str] = None

    @property
    def duration_s(self) -> float:
        """P08-OCC-001: Total blocking duration T_blocking = t_release - t_start."""
        return max(0.0, self.end_time_s - self.start_time_s)

    def contains_time(self, t: float) -> bool:
        """Half-open interval membership: t_start <= t < t_end."""
        return (self.start_time_s - 1e-6) <= t < (self.end_time_s - 1e-6)

    def overlaps(self, other: "ResourceBlockingInterval") -> bool:
        """Half-open interval overlap check."""
        return max(self.start_time_s, other.start_time_s) < min(self.end_time_s, other.end_time_s) - 1e-6

    def shift(self, dt_s: float, new_interval_id: Optional[str] = None) -> "ResourceBlockingInterval":
        """Returns a copy of this interval shifted by dt_s seconds."""
        decomp = None
        if self.decomposition:
            decomp = BlockingTimeDecomposition(
                setup_time_s=self.decomposition.setup_time_s,
                approach_time_s=self.decomposition.approach_time_s,
                running_time_s=self.decomposition.running_time_s,
                dwell_time_s=self.decomposition.dwell_time_s,
                geometric_clearance_time_s=self.decomposition.geometric_clearance_time_s,
                residual_rear_time_s=self.decomposition.residual_rear_time_s,
                release_time_s=self.decomposition.release_time_s,
                reconciliation_difference_s=self.decomposition.reconciliation_difference_s,
                reconciliation_note=self.decomposition.reconciliation_note,
            )

        return ResourceBlockingInterval(
            interval_id=new_interval_id or f"{self.interval_id}_SHIFTED_{dt_s:.1f}",
            resource_id=self.resource_id,
            resource_category=self.resource_category,
            train_id=self.train_id,
            start_time_s=self.start_time_s + dt_s,
            end_time_s=self.end_time_s + dt_s,
            route_id=self.route_id,
            running_direction=self.running_direction,
            front_entry_time_s=(self.front_entry_time_s + dt_s) if self.front_entry_time_s is not None else None,
            front_exit_time_s=(self.front_exit_time_s + dt_s) if self.front_exit_time_s is not None else None,
            rear_clearance_time_s=(self.rear_clearance_time_s + dt_s) if self.rear_clearance_time_s is not None else None,
            dwell_start_time_s=(self.dwell_start_time_s + dt_s) if self.dwell_start_time_s is not None else None,
            dwell_end_time_s=(self.dwell_end_time_s + dt_s) if self.dwell_end_time_s is not None else None,
            decomposition=decomp,
            physical_start_offset_m=self.physical_start_offset_m,
            physical_end_offset_m=self.physical_end_offset_m,
            capacity=self.capacity,
            usage_index=self.usage_index,
            description=self.description,
        )


@dataclass
class BlockingTimeline:
    """P08-TRJ-003: Complete sequence of resource blocking intervals for an individual train."""

    train_id: str
    service_id: str
    route_id: str
    running_direction: RunningDirection
    reference_event_name: str
    reference_event_time_s: float
    intervals: List[ResourceBlockingInterval] = field(default_factory=list)

    def get_intervals_for_resource(self, resource_id: str) -> List[ResourceBlockingInterval]:
        """Returns all usages of a specific resource."""
        return [iv for iv in self.intervals if iv.resource_id == resource_id]

    def longest_blocking_interval(self) -> Optional[ResourceBlockingInterval]:
        """P08-OCC: Identifies the resource with the longest standalone blocking duration."""
        if not self.intervals:
            return None
        return max(self.intervals, key=lambda iv: iv.duration_s)

    def sorted_by_start(self) -> List[ResourceBlockingInterval]:
        """Returns intervals ordered chronologically by blocking start."""
        return sorted(self.intervals, key=lambda iv: (iv.start_time_s, iv.end_time_s))

    def shift(self, dt_s: float) -> "BlockingTimeline":
        """Returns a new timeline shifted by dt_s relative to its reference event."""
        shifted_intervals = [iv.shift(dt_s) for iv in self.intervals]
        return BlockingTimeline(
            train_id=self.train_id,
            service_id=self.service_id,
            route_id=self.route_id,
            running_direction=self.running_direction,
            reference_event_name=self.reference_event_name,
            reference_event_time_s=self.reference_event_time_s + dt_s,
            intervals=shifted_intervals,
        )


def decompose_blocking_interval(
    start_time_s: float,
    end_time_s: float,
    front_entry_time_s: Optional[float] = None,
    front_exit_time_s: Optional[float] = None,
    rear_clearance_time_s: Optional[float] = None,
    dwell_duration_s: float = 0.0,
    setup_duration_s: Optional[float] = None,
    residual_rear_duration_s: float = 0.0,
) -> BlockingTimeDecomposition:
    """P08-BT-007 to 016: Calculates seven non-overlapping blocking time components.

    Component hierarchy:
    1. Setup: Route locking / switch throw / gate delay.
    2. Approach: Time after setup until physical front entry.
    3. Running: Time front traverses block (excluding dwell).
    4. Dwell: Stationary dwell time while train is inside block.
    5. Geometric clearance: Moving time after front exits until rear clears (excluding stationary residual).
    6. Residual rear: Stationary dwell time while rear remains in upstream block.
    7. Release: Time from rear clearance to final resource release (release delay timer).
    """
    total_duration = max(0.0, end_time_s - start_time_s)

    # 1. Setup & 2. Approach
    t_entry = front_entry_time_s if front_entry_time_s is not None else start_time_s
    t_pre_entry = max(0.0, t_entry - start_time_s)

    if setup_duration_s is not None:
        t_setup = min(setup_duration_s, t_pre_entry)
        t_approach = max(0.0, t_pre_entry - t_setup)
    else:
        # Default: if setup not explicitly provided, treat pre-entry as approach
        t_setup = 0.0
        t_approach = t_pre_entry

    # 3. Running & 4. Dwell
    t_exit = front_exit_time_s if front_exit_time_s is not None else t_entry
    front_traversal = max(0.0, t_exit - t_entry)
    t_dwell = min(dwell_duration_s, front_traversal)
    t_running = max(0.0, front_traversal - t_dwell)

    # 5. Geometric Clearance & 6. Residual Rear
    t_clear = rear_clearance_time_s if rear_clearance_time_s is not None else t_exit
    rear_traversal = max(0.0, t_clear - t_exit)
    t_residual = min(residual_rear_duration_s, rear_traversal)
    t_geom_clear = max(0.0, rear_traversal - t_residual)

    # 7. Release
    t_release = max(0.0, end_time_s - t_clear)

    decomp_sum = t_setup + t_approach + t_running + t_dwell + t_geom_clear + t_residual + t_release
    diff = total_duration - decomp_sum
    note = None
    if abs(diff) > 1e-3:
        note = f"Reconciliation discrepancy {diff:.3f}s due to unmapped intermediate holds or event gaps"

    return BlockingTimeDecomposition(
        setup_time_s=round(t_setup, 6),
        approach_time_s=round(t_approach, 6),
        running_time_s=round(t_running, 6),
        dwell_time_s=round(t_dwell, 6),
        geometric_clearance_time_s=round(t_geom_clear, 6),
        residual_rear_time_s=round(t_residual, 6),
        release_time_s=round(t_release, 6),
        reconciliation_difference_s=round(diff, 6),
        reconciliation_note=note,
    )


def extract_blocking_intervals_from_records(
    usage_records: List[ResourceUsageRecord],
    reference_event_time_s: float = 0.0,
    setup_duration_s: float = 0.0,
    dwell_durations: Optional[Dict[str, float]] = None,
    residual_durations: Optional[Dict[str, float]] = None,
) -> List[ResourceBlockingInterval]:
    """P08-BT-002: Build ResourceBlockingIntervals directly from P05-P07 ResourceUsageRecords."""
    intervals: List[ResourceBlockingInterval] = []
    dwells = dwell_durations or {}
    residuals = residual_durations or {}

    usage_counter: Dict[Tuple[str, str], int] = {}

    for rec in usage_records:
        entry_s = getattr(rec, "physical_front_entry_s", getattr(rec, "front_entry_s", None))
        rel_complete = getattr(rec, "final_release_s", getattr(rec, "release_complete_s", None))

        t_start = rec.reservation_start_s if rec.reservation_start_s is not None else (entry_s or 0.0)
        t_end = rel_complete if rel_complete is not None else (rec.rear_clearance_s or t_start)

        # Normalize relative to reference event
        rel_start = t_start - reference_event_time_s
        rel_end = t_end - reference_event_time_s
        rel_entry = (entry_s - reference_event_time_s) if entry_s is not None else None
        rel_exit = (rec.front_exit_s - reference_event_time_s) if rec.front_exit_s is not None else None
        rel_clear = (rec.rear_clearance_s - reference_event_time_s) if rec.rear_clearance_s is not None else None

        dwell_s = dwells.get(rec.resource_id, 0.0)
        residual_s = residuals.get(rec.resource_id, 0.0)

        decomp = decompose_blocking_interval(
            start_time_s=rel_start,
            end_time_s=rel_end,
            front_entry_time_s=rel_entry,
            front_exit_time_s=rel_exit,
            rear_clearance_time_s=rel_clear,
            dwell_duration_s=dwell_s,
            setup_duration_s=setup_duration_s,
            residual_rear_duration_s=residual_s,
        )

        key = (rec.train_id, rec.resource_id)
        idx = usage_counter.get(key, 0) + 1
        usage_counter[key] = idx

        iv = ResourceBlockingInterval(
            interval_id=f"BI_{rec.train_id}_{rec.resource_id}_{idx}",
            resource_id=rec.resource_id,
            resource_category=rec.resource_type,
            train_id=rec.train_id,
            start_time_s=round(rel_start, 6),
            end_time_s=round(rel_end, 6),
            running_direction=rec.running_direction,
            front_entry_time_s=rel_entry,
            front_exit_time_s=rel_exit,
            rear_clearance_time_s=rel_clear,
            decomposition=decomp,
            usage_index=idx,
        )
        intervals.append(iv)

    return sorted(intervals, key=lambda i: (i.start_time_s, i.end_time_s))
