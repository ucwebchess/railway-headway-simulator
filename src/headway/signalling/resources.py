"""Common resource management framework and lifecycle controller.

Strictly satisfies RHS-P05-001:
- § 4: Common Resource Model (P05-RES-001 to P05-RES-004)
- § 5: Decoupled Resource State Model (P05-STATE-001 to P05-STATE-006)
- § 6: Resource Request & Reservation (P05-REQ-001 to P05-REQ-006)
- § 7: Physical Resource Occupation (P05-OCC-001 to P05-OCC-007)
- § 8: Resource Release & Delays (P05-REL-001 to P05-REL-007)
- § 9: Capacity & Conflicts (P05-CON-001 to P05-CON-005)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from headway.data.canonical import ResourceInterval, SharedResourceGroup, SignallingBlock
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.resources import PhysicalResource
from headway.signalling.resource_types import (
    ReleasePolicy,
    ResourceCategory,
    ResourceConflictError,
    ResourceEventType,
    ResourceUsageRecord,
    SignallingEvent,
)


@dataclass
class ManagedResource:
    """A managed railway resource maintaining decoupled occupation, reservation, and lock states."""

    resource_id: str
    category: ResourceCategory
    capacity: int = 1
    release_delay_s: float = 0.0
    intervals: List[ResourceInterval] = field(default_factory=list)
    description: Optional[str] = None

    # P05-STATE: Separately tracked operational states (NOT a single exclusive enum)
    occupants: Set[str] = field(default_factory=set)
    front_exited_occupants: Set[str] = field(default_factory=set)
    reservations: Dict[str, float] = field(default_factory=dict)  # train_id -> timestamp
    locks: Set[str] = field(default_factory=set)  # route_ids or lock holder IDs
    release_pending_until: Optional[float] = None
    release_eligible_at: Optional[float] = None
    pending_requests: List[Tuple[str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ResourceConflictError(
                f"Resource '{self.resource_id}' capacity must be >= 1 (got {self.capacity}).",
                context={"resource_id": self.resource_id},
            )
        if self.release_delay_s < 0:
            raise ResourceConflictError(
                f"Resource '{self.resource_id}' release delay cannot be negative (got {self.release_delay_s} s).",
                context={"resource_id": self.resource_id},
            )

    @property
    def is_occupied(self) -> bool:
        """P05-STATE-003: True if one or more trains physically occupy the resource."""
        return len(self.occupants) > 0

    @property
    def is_reserved(self) -> bool:
        """P05-STATE-002: True if currently reserved by any train or route."""
        return len(self.reservations) > 0

    @property
    def is_locked(self) -> bool:
        """P05-STATE-004: True if locked by an active interlocking route or protection."""
        return len(self.locks) > 0

    @property
    def length_m(self) -> float:
        """Total physical length in meters across all intervals."""
        if not self.intervals:
            return 0.0
        return sum(abs(inv.end_offset_m - inv.start_offset_m) for inv in self.intervals)

    def is_release_pending(self, current_time_s: float) -> bool:
        """P05-STATE-005: True if release conditions are pending expiration."""
        if self.release_pending_until is None:
            return False
        return current_time_s < self.release_pending_until

    def is_available(
        self,
        for_train_id: Optional[str] = None,
        current_time_s: float = 0.0,
    ) -> bool:
        """P05-STATE-006: Derived availability evaluated from active physical and logical constraints."""
        # Check active locks: if locked, only available if requested by the holding route/train
        if self.is_locked:
            return False

        # Check pending release delay timer
        if self.is_release_pending(current_time_s):
            return False

        # Check physical occupation
        if self.is_occupied:
            if for_train_id is not None and for_train_id in self.occupants:
                pass  # Train is already occupying this resource
            elif len(self.occupants) >= self.capacity:
                return False

        # Check reservations
        if self.is_reserved:
            if for_train_id is not None and for_train_id in self.reservations:
                return True
            if len(self.reservations) >= self.capacity:
                return False

        return True

    def can_reserve(self, train_id: str, current_time_s: float = 0.0) -> bool:
        """Check if train_id can obtain a new reservation."""
        if train_id in self.reservations:
            return True
        return self.is_available(for_train_id=train_id, current_time_s=current_time_s)


class ResourceController:
    """Manages common infrastructure resources, reservations, physical occupations, and conflicts."""

    def __init__(self) -> None:
        self.resources: Dict[str, ManagedResource] = {}
        self.conflict_groups: Dict[str, Set[str]] = {}  # group_id -> set of resource_ids
        self.resource_to_groups: Dict[str, Set[str]] = {}  # resource_id -> set of group_ids
        self.event_log: List[SignallingEvent] = []
        self._usage_records: Dict[Tuple[str, str], ResourceUsageRecord] = {}
        self._next_sequence_id: int = 1

    def _next_seq(self) -> int:
        seq = self._next_sequence_id
        self._next_sequence_id += 1
        return seq

    def register_resource(self, resource: ManagedResource) -> None:
        """P05-RES-002: Register canonical resource."""
        self.resources[resource.resource_id] = resource

    def get_resource(self, resource_id: str) -> Optional[ManagedResource]:
        """Retrieve managed resource by identifier."""
        return self.resources.get(resource_id)

    def register_signalling_block(self, block: SignallingBlock) -> ManagedResource:
        """Register a SignallingBlock as a TRACK_BLOCK managed resource."""
        res = ManagedResource(
            resource_id=block.block_id,
            category=ResourceCategory.TRACK_BLOCK,
            capacity=1,
            release_delay_s=block.release_delay_s,
            intervals=block.link_intervals,
            description=f"Fixed block {block.block_id}",
        )
        self.register_resource(res)
        return res

    def register_conflict_group(self, group: SharedResourceGroup) -> None:
        """P05-CON-003: Register shared conflict group."""
        r_set = set(group.resource_ids)
        self.conflict_groups[group.group_id] = r_set
        for rid in r_set:
            if rid not in self.resource_to_groups:
                self.resource_to_groups[rid] = set()
            self.resource_to_groups[rid].add(group.group_id)

    def get_conflicting_resources(self, resource_id: str) -> Set[str]:
        """P05-CON-004: Return all peer resources belonging to the same conflict groups."""
        conflicts = set()
        group_ids = self.resource_to_groups.get(resource_id, set())
        for gid in group_ids:
            for peer_rid in self.conflict_groups.get(gid, set()):
                if peer_rid != resource_id:
                    conflicts.add(peer_rid)
        return conflicts

    def request_resource(
        self,
        train_id: str,
        resource_id: str,
        timestamp_s: float,
        route_id: Optional[str] = None,
    ) -> bool:
        """P05-REQ-001: Request a resource for a train."""
        res = self.resources.get(resource_id)
        if not res:
            raise ResourceConflictError(
                f"Cannot request unknown resource '{resource_id}'.",
                context={"resource_id": resource_id, "train_id": train_id},
            )

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.RESOURCE_REQUESTED,
                resource_id=resource_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Train '{train_id}' requested resource '{resource_id}'",
            )
        )

        if res.can_reserve(train_id, timestamp_s):
            return True
        else:
            res.pending_requests.append((train_id, timestamp_s))
            return False

    def reserve_resource(
        self,
        train_id: str,
        resource_id: str,
        timestamp_s: float,
        route_id: Optional[str] = None,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> None:
        """P05-REQ-003 & P05-CON-005: Atomically allocate exclusive or capacity reservation."""
        res = self.resources.get(resource_id)
        if not res:
            raise ResourceConflictError(
                f"Cannot reserve unknown resource '{resource_id}'.",
                context={"resource_id": resource_id, "train_id": train_id},
            )

        # Check conflicts across shared groups
        for peer_id in self.get_conflicting_resources(resource_id):
            peer_res = self.resources.get(peer_id)
            if peer_res and (peer_res.is_occupied or peer_res.is_reserved or peer_res.is_locked):
                # If occupied or reserved by a different train, conflict!
                if not (train_id in peer_res.occupants or train_id in peer_res.reservations):
                    raise ResourceConflictError(
                        f"Conflict: Resource '{resource_id}' cannot be reserved due to active peer resource '{peer_id}'.",
                        context={"resource_id": resource_id, "peer_id": peer_id, "train_id": train_id},
                    )

        # Validate resource availability
        if not res.can_reserve(train_id, timestamp_s):
            raise ResourceConflictError(
                f"Resource '{resource_id}' is unavailable for reservation by train '{train_id}'.",
                context={
                    "resource_id": resource_id,
                    "train_id": train_id,
                    "is_occupied": res.is_occupied,
                    "is_reserved": res.is_reserved,
                    "is_locked": res.is_locked,
                },
            )

        # Grant reservation
        res.reservations[train_id] = timestamp_s

        # Initialize usage record
        usage_key = (train_id, resource_id)
        self._usage_records[usage_key] = ResourceUsageRecord(
            usage_id=f"USG_{train_id}_{resource_id}",
            train_id=train_id,
            resource_id=resource_id,
            resource_type=res.category,
            reservation_start_s=timestamp_s,
            running_direction=running_direction,
        )

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.RESOURCE_RESERVED,
                resource_id=resource_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Train '{train_id}' reserved resource '{resource_id}'",
            )
        )

    def front_enter_resource(
        self,
        train_id: str,
        resource_id: str,
        timestamp_s: float,
        route_id: Optional[str] = None,
    ) -> None:
        """P05-OCC-001: Train front enters physical resource geometry."""
        res = self.resources.get(resource_id)
        if not res:
            raise ResourceConflictError(
                f"Unknown resource '{resource_id}'.",
                context={"resource_id": resource_id, "train_id": train_id},
            )

        # Invariant check: cannot enter if occupied at full capacity by other trains
        if len(res.occupants) >= res.capacity and train_id not in res.occupants:
            raise ResourceConflictError(
                f"Physical collision/unauthorized entry: Train '{train_id}' entered resource '{resource_id}' "
                f"which is already at full capacity ({res.capacity}) with occupants {res.occupants}.",
                context={"resource_id": resource_id, "train_id": train_id},
            )

        res.occupants.add(train_id)

        # Update usage record
        usage = self._usage_records.get((train_id, resource_id))
        if usage and usage.physical_front_entry_s is None:
            usage.physical_front_entry_s = timestamp_s

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.RESOURCE_ENTERED,
                resource_id=resource_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Train '{train_id}' front entered resource '{resource_id}'",
            )
        )

    def front_exit_resource(
        self,
        train_id: str,
        resource_id: str,
        timestamp_s: float,
        route_id: Optional[str] = None,
    ) -> None:
        """P05-OCC-003 & P05-REL-006: Train front exits resource. MUST NOT RELEASE RESOURCE."""
        res = self.resources.get(resource_id)
        if not res:
            return

        res.front_exited_occupants.add(train_id)

        usage = self._usage_records.get((train_id, resource_id))
        if usage and usage.front_exit_s is None:
            usage.front_exit_s = timestamp_s

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.RESOURCE_FRONT_EXITED,
                resource_id=resource_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Train '{train_id}' front exited resource '{resource_id}' (rear still occupying)",
            )
        )

    def rear_clear_resource(
        self,
        train_id: str,
        resource_id: str,
        timestamp_s: float,
        route_id: Optional[str] = None,
    ) -> None:
        """P05-OCC-004 & P05-REL-001: Train rear clears resource completely."""
        res = self.resources.get(resource_id)
        if not res:
            return

        res.occupants.discard(train_id)
        res.front_exited_occupants.discard(train_id)

        # Mark release eligibility and timer
        res.release_eligible_at = timestamp_s
        res.release_pending_until = timestamp_s + res.release_delay_s

        usage = self._usage_records.get((train_id, resource_id))
        if usage:
            usage.rear_clearance_s = timestamp_s
            usage.release_eligibility_s = timestamp_s

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.RESOURCE_REAR_CLEARED,
                resource_id=resource_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Train '{train_id}' rear cleared resource '{resource_id}'",
            )
        )

        # If release delay is 0.0 and no active locks, release immediately
        if res.release_delay_s == 0.0 and not res.is_locked:
            self.release_resource(train_id, resource_id, timestamp_s, route_id=route_id)

    def release_resource(
        self,
        train_id: str,
        resource_id: str,
        timestamp_s: float,
        route_id: Optional[str] = None,
    ) -> None:
        """P05-REL-005: Final release of resource."""
        res = self.resources.get(resource_id)
        if not res:
            return

        res.reservations.pop(train_id, None)
        res.release_pending_until = None
        res.release_eligible_at = None

        usage = self._usage_records.get((train_id, resource_id))
        if usage and usage.final_release_s is None:
            usage.final_release_s = timestamp_s

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.RESOURCE_RELEASED,
                resource_id=resource_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Resource '{resource_id}' released by train '{train_id}'",
            )
        )

    def process_pending_releases(self, current_time_s: float) -> List[SignallingEvent]:
        """P05 § 19: Step 5 & 6: Process eligible release timers and release available resources."""
        released_events: List[SignallingEvent] = []
        for rid, res in self.resources.items():
            if res.release_pending_until is not None and current_time_s >= res.release_pending_until:
                if not res.is_occupied and not res.is_locked:
                    res.release_pending_until = None
                    res.release_eligible_at = None
                    res.reservations.clear()

                    evt = SignallingEvent(
                        sequence_id=self._next_seq(),
                        timestamp_s=current_time_s,
                        event_type=ResourceEventType.RESOURCE_RELEASED,
                        resource_id=rid,
                        description=f"Resource '{rid}' released after delay timer",
                    )
                    self.event_log.append(evt)
                    released_events.append(evt)
        return released_events

    def lock_resource(self, resource_id: str, lock_holder_id: str, timestamp_s: float) -> None:
        """P05-STATE-004: Apply interlocking lock to resource."""
        res = self.resources.get(resource_id)
        if not res:
            raise ResourceConflictError(f"Cannot lock unknown resource '{resource_id}'.")
        res.locks.add(lock_holder_id)

    def unlock_resource(self, resource_id: str, lock_holder_id: str, timestamp_s: float) -> None:
        """Release interlocking lock on resource."""
        res = self.resources.get(resource_id)
        if res:
            res.locks.discard(lock_holder_id)

    def get_usage_records(self) -> List[ResourceUsageRecord]:
        """P05 § 21: Get all underlying resource usage records."""
        return list(self._usage_records.values())
