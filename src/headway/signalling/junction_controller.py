"""Junction and Crossover Control engine.

Strictly satisfies RHS-P07-001:
- § 11: Junction and Crossover Control (P07-JNC-001 to P07-JNC-006)
- § 12: Sectional Release & Directionality of Junctions
- Mutual exclusion of converging (merge), crossover, and diamond crossing movements.
- Support for concurrent diverging movements to distinct tracks.
- Sectional release of switch and crossover zones upon train-rear clearance.
- Directional awareness: FORWARD and REVERSE railway movements.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from headway.data.canonical import InfrastructureModel, InterlockingRoute
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.switches import SwitchPosition
from headway.signalling.interlocking import InterlockingEngine, InterlockingRouteDefinition, RouteLockState
from headway.signalling.resource_types import (
    JunctionConflictError,
    ReleasePolicy,
    ResourceCategory,
    ResourceEventType,
    SignallingEvent,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController


class JunctionType(str, Enum):
    """P07-JNC-001: Classification of junction topology."""

    MERGE = "MERGE"
    DIVERGE = "DIVERGE"
    CROSSOVER = "CROSSOVER"
    DIAMOND_CROSSING = "DIAMOND_CROSSING"


@dataclass
class JunctionZone:
    """Canonical junction zone representation."""

    junction_id: str
    junction_type: JunctionType
    switch_ids: List[str] = field(default_factory=list)
    protected_block_ids: List[str] = field(default_factory=list)
    route_ids: List[str] = field(default_factory=list)
    conflicting_route_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    description: Optional[str] = None


class JunctionController:
    """Controls junction route requests, conflict detection, switch alignment, and sectional release."""

    def __init__(
        self,
        interlocking_engine: InterlockingEngine,
        switch_controller: SwitchController,
        resource_controller: ResourceController,
    ) -> None:
        self.interlocking_engine = interlocking_engine
        self.switch_controller = switch_controller
        self.resource_controller = resource_controller

        self.junctions: Dict[str, JunctionZone] = {}
        self.route_to_junction: Dict[str, str] = {}
        self.active_train_junctions: Dict[str, Set[str]] = {}  # train_id -> set of junction_ids
        self.event_log: List[SignallingEvent] = []
        self._next_sequence_id: int = 1

    def _next_seq(self) -> int:
        seq = self._next_sequence_id
        self._next_sequence_id += 1
        return seq

    def _log_event(
        self,
        timestamp_s: float,
        event_type: ResourceEventType,
        resource_id: str,
        train_id: Optional[str] = None,
        route_id: Optional[str] = None,
        description: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> SignallingEvent:
        evt = SignallingEvent(
            sequence_id=self._next_seq(),
            timestamp_s=round(timestamp_s, 6),
            event_type=event_type,
            resource_id=resource_id,
            train_id=train_id,
            route_id=route_id,
            description=description,
            details=details or {},
        )
        self.event_log.append(evt)
        return evt

    def register_junction_zone(self, zone: JunctionZone) -> None:
        """Register a junction zone and index its routes."""
        self.junctions[zone.junction_id] = zone
        for r_id in zone.route_ids:
            self.route_to_junction[r_id] = zone.junction_id

        # Register junction as a managed resource
        res = ManagedResource(
            resource_id=f"JUNCTION_{zone.junction_id}",
            category=ResourceCategory.INTERLOCKING_ROUTE,
            capacity=1,
            release_delay_s=1.0,
            description=f"Junction zone {zone.junction_id} ({zone.junction_type.value})",
        )
        self.resource_controller.register_resource(res)

    def can_request_junction_movement(
        self,
        route_id: str,
        train_id: str,
        timestamp_s: float,
    ) -> Tuple[bool, Optional[str]]:
        """Check if junction route can be safely requested without conflict."""
        if not self.interlocking_engine.is_route_available(route_id, train_id, timestamp_s):
            # Find conflicting route
            j_id = self.route_to_junction.get(route_id)
            conflict_reason = f"Interlocking route '{route_id}' or switch resources are currently locked."
            if j_id and j_id in self.junctions:
                zone = self.junctions[j_id]
                for other_r in zone.route_ids:
                    if other_r != route_id:
                        r_state = self.interlocking_engine.active_states.get(other_r)
                        if r_state and r_state.is_locked and r_state.allocated_train_id != train_id:
                            conflict_reason = (
                                f"Conflicting movement '{other_r}' is locked for train '{r_state.allocated_train_id}'."
                            )
                            break
            return False, conflict_reason
        return True, None

    def request_junction_movement(
        self,
        train_id: str,
        route_id: str,
        timestamp_s: float,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> float:
        """P07-JNC-001 to 003: Request route through junction.

        Aligns switches, validates conflict exclusivity, and locks the route.
        Raises JunctionConflictError if a conflicting movement prevents locking.
        Returns lock completion timestamp.
        """
        j_id = self.route_to_junction.get(route_id)
        res_id = f"JUNCTION_{j_id}" if j_id else route_id

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.JUNCTION_ROUTE_REQUESTED,
            resource_id=res_id,
            train_id=train_id,
            route_id=route_id,
            description=f"Train '{train_id}' requested junction route '{route_id}' ({running_direction.value})",
            details={"direction": running_direction.value, "junction_id": j_id},
        )

        can_req, reason = self.can_request_junction_movement(route_id, train_id, timestamp_s)
        if not can_req:
            self._log_event(
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.JUNCTION_CONFLICT_DETECTED,
                resource_id=res_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Junction conflict on route '{route_id}': {reason}",
                details={"reason": reason},
            )
            raise JunctionConflictError(
                f"Cannot lock junction route '{route_id}' for train '{train_id}': {reason}",
                context={"train_id": train_id, "route_id": route_id, "junction_id": j_id, "reason": reason},
            )

        # Lock route through InterlockingEngine
        lock_time = self.interlocking_engine.request_and_lock_route(
            route_id=route_id,
            train_id=train_id,
            timestamp_s=timestamp_s,
        )

        self._log_event(
            timestamp_s=lock_time,
            event_type=ResourceEventType.JUNCTION_ROUTE_LOCKED,
            resource_id=res_id,
            train_id=train_id,
            route_id=route_id,
            description=f"Junction route '{route_id}' successfully locked for train '{train_id}' at {lock_time:.1f}s",
        )
        return lock_time

    def enter_junction_zone(
        self,
        train_id: str,
        junction_id: str,
        timestamp_s: float,
    ) -> None:
        """P07-JNC-004: Train front enters junction zone."""
        if train_id not in self.active_train_junctions:
            self.active_train_junctions[train_id] = set()
        self.active_train_junctions[train_id].add(junction_id)

        res_id = f"JUNCTION_{junction_id}"
        self.resource_controller.front_enter_resource(
            train_id=train_id,
            resource_id=res_id,
            timestamp_s=timestamp_s,
        )

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.JUNCTION_ZONE_ENTERED,
            resource_id=res_id,
            train_id=train_id,
            description=f"Train '{train_id}' entered junction zone '{junction_id}'",
        )

    def clear_junction_zone(
        self,
        train_id: str,
        junction_id: str,
        route_id: str,
        timestamp_s: float,
        cleared_switch_ids: Optional[List[str]] = None,
    ) -> None:
        """P07-JNC-004: Train rear completely clears junction zone. Triggers sectional or complete release."""
        res_id = f"JUNCTION_{junction_id}"
        self.resource_controller.rear_clear_resource(
            train_id=train_id,
            resource_id=res_id,
            timestamp_s=timestamp_s,
        )

        if train_id in self.active_train_junctions:
            self.active_train_junctions[train_id].discard(junction_id)

        j_zone = self.junctions.get(junction_id)
        sw_to_unlock = cleared_switch_ids or (j_zone.switch_ids if j_zone else [])
        for sw_id in sw_to_unlock:
            if sw_id in self.switch_controller.states:
                self.switch_controller.unlock_switch(sw_id, route_id, timestamp_s)

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.JUNCTION_ZONE_CLEARED,
            resource_id=res_id,
            train_id=train_id,
            route_id=route_id,
            description=f"Train '{train_id}' rear cleared junction zone '{junction_id}'",
        )

    def process_sectional_junction_release(
        self,
        route_id: str,
        cleared_block_id: str,
        timestamp_s: float,
        cleared_switch_id: Optional[str] = None,
    ) -> bool:
        """P07-JNC-004: Sectional release of cleared block and cleared switch in junction zone."""
        res = self.interlocking_engine.process_sectional_release(route_id, cleared_block_id, timestamp_s)
        if cleared_switch_id and cleared_switch_id in self.switch_controller.states:
            self.switch_controller.unlock_switch(cleared_switch_id, route_id, timestamp_s)
        return res

    def release_junction_route(
        self,
        route_id: str,
        train_id: str,
        timestamp_s: float,
    ) -> None:
        """Release junction route and unlock switches."""
        j_id = self.route_to_junction.get(route_id)
        res_id = f"JUNCTION_{j_id}" if j_id else route_id

        self.interlocking_engine.release_route(
            route_id=route_id,
            timestamp_s=timestamp_s,
        )

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.JUNCTION_ROUTE_RELEASED,
            resource_id=res_id,
            train_id=train_id,
            route_id=route_id,
            description=f"Junction route '{route_id}' released for train '{train_id}'",
        )
