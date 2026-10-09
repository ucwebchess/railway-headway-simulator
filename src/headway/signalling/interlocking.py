"""Interlocking engine, route establishment, switch locking, and sectional release.

Strictly satisfies RHS-P05-001 § 10:
- P05-INT-001: Route definitions and attributes.
- P05-INT-002: Route request event (ROUTE_REQUESTED).
- P05-INT-003: Route availability verification.
- P05-INT-004: Switch alignment.
- P05-INT-005: Route setup time.
- P05-INT-006: Route locking (ROUTE_LOCKED).
- P05-INT-007: Route authorization gate.
- P05-INT-008: Incompatible route conflict prevention.
- P05-INT-009: Complete route release.
- P05-INT-010: Sectional route release.
- P05-INT-011: Reverse route support.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from headway.data.canonical import InterlockingRoute
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.switches import SwitchPosition
from headway.signalling.resource_types import (
    InterlockingRouteError,
    ReleasePolicy,
    ResourceCategory,
    ResourceEventType,
    SignallingEvent,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController


class RouteLockState(str, Enum):
    """Lifecycle state of an interlocking route."""

    IDLE = "IDLE"
    REQUESTED = "REQUESTED"
    SETTING_UP = "SETTING_UP"
    LOCKED = "LOCKED"
    RELEASING = "RELEASING"


@dataclass
class InterlockingRouteDefinition:
    """Complete engineering definition of an interlocking route."""

    route_id: str
    entry_signal_id: str
    exit_signal_id: str
    link_sequence: List[str]
    protected_block_ids: List[str] = field(default_factory=list)
    conflicting_route_ids: List[str] = field(default_factory=list)
    required_switch_positions: Dict[str, SwitchPosition] = field(default_factory=dict)
    setup_time_s: float = 3.0
    release_policy: ReleasePolicy = ReleasePolicy.COMPLETE
    running_direction: RunningDirection = RunningDirection.FORWARD
    description: Optional[str] = None


@dataclass
class ActiveRouteState:
    """Dynamic operational state of an interlocking route during simulation."""

    route_def: InterlockingRouteDefinition
    state: RouteLockState = RouteLockState.IDLE
    allocated_train_id: Optional[str] = None
    request_time_s: Optional[float] = None
    lock_time_s: Optional[float] = None
    setup_completion_time_s: Optional[float] = None
    released_block_ids: Set[str] = field(default_factory=set)

    @property
    def is_locked(self) -> bool:
        return self.state == RouteLockState.LOCKED


class InterlockingEngine:
    """Interlocking coordinator for route requests, conflicts, locking, and release."""

    def __init__(
        self,
        resource_controller: ResourceController,
        switch_controller: SwitchController,
        default_setup_time_s: float = 3.0,
    ) -> None:
        self.resource_controller = resource_controller
        self.switch_controller = switch_controller
        self.default_setup_time_s = default_setup_time_s

        self.routes: Dict[str, InterlockingRouteDefinition] = {}
        self.active_states: Dict[str, ActiveRouteState] = {}
        self.event_log: List[SignallingEvent] = []
        self._next_sequence_id: int = 1

    def _next_seq(self) -> int:
        seq = self._next_sequence_id
        self._next_sequence_id += 1
        return seq

    def register_route(self, route_def: InterlockingRouteDefinition) -> None:
        """Register an interlocking route definition."""
        self.routes[route_def.route_id] = route_def
        self.active_states[route_def.route_id] = ActiveRouteState(route_def=route_def)

        # Register interlocking route as a managed resource
        res = ManagedResource(
            resource_id=f"RES_RT_{route_def.route_id}",
            category=ResourceCategory.INTERLOCKING_ROUTE,
            capacity=1,
            release_delay_s=0.0,
            description=f"Interlocking route {route_def.route_id}",
        )
        self.resource_controller.register_resource(res)

    def register_from_canonical(
        self,
        canonical_route: InterlockingRoute,
        release_policy: ReleasePolicy = ReleasePolicy.COMPLETE,
        setup_time_s: Optional[float] = None,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> InterlockingRouteDefinition:
        """Register route from canonical InterlockingRoute model and infer required switch positions."""
        # Infer required switch positions from consecutive links
        sw_positions: Dict[str, SwitchPosition] = {}
        for i in range(len(canonical_route.link_sequence) - 1):
            e_link = canonical_route.link_sequence[i]
            x_link = canonical_route.link_sequence[i + 1]
            sw_req = self.switch_controller.get_required_movement_position(e_link, x_link)
            if sw_req:
                sw_positions[sw_req[0]] = sw_req[1]

        r_def = InterlockingRouteDefinition(
            route_id=canonical_route.route_id,
            entry_signal_id=canonical_route.entry_signal_id,
            exit_signal_id=canonical_route.exit_signal_id,
            link_sequence=list(canonical_route.link_sequence),
            protected_block_ids=list(canonical_route.protected_blocks),
            conflicting_route_ids=list(canonical_route.conflicting_route_ids),
            required_switch_positions=sw_positions,
            setup_time_s=setup_time_s if setup_time_s is not None else self.default_setup_time_s,
            release_policy=release_policy,
            running_direction=running_direction,
        )
        self.register_route(r_def)
        return r_def

    def is_route_available(self, route_id: str, for_train_id: str, current_time_s: float) -> bool:
        """P05-INT-003 & 008: Check if route and all dependent resources are free of conflicts."""
        r_state = self.active_states.get(route_id)
        if not r_state:
            return False

        if r_state.state in (RouteLockState.LOCKED, RouteLockState.SETTING_UP):
            return r_state.allocated_train_id == for_train_id

        r_def = r_state.route_def

        # 1. Check conflicting routes
        for conf_id in r_def.conflicting_route_ids:
            conf_state = self.active_states.get(conf_id)
            if conf_state and conf_state.state in (RouteLockState.LOCKED, RouteLockState.SETTING_UP):
                return False

        # 2. Check protected blocks availability
        for bid in r_def.protected_block_ids:
            res = self.resource_controller.resources.get(bid)
            if res and not res.can_reserve(for_train_id, current_time_s):
                return False

        # 3. Check switch locking availability
        for sw_id, req_pos in r_def.required_switch_positions.items():
            sw_state = self.switch_controller.states.get(sw_id)
            if sw_state and sw_state.is_locked:
                if route_id not in sw_state.locked_by_routes or sw_state.current_position != req_pos:
                    return False

        return True

    def request_and_lock_route(
        self,
        route_id: str,
        train_id: str,
        timestamp_s: float,
    ) -> float:
        """P05-INT-002 to 006: Request, align switches, apply setup time, and lock route.

        Returns timestamp when route is fully established and locked.
        """
        r_state = self.active_states.get(route_id)
        if not r_state:
            raise InterlockingRouteError(
                f"Cannot request unknown interlocking route '{route_id}'.",
                context={"route_id": route_id, "train_id": train_id},
            )

        if not self.is_route_available(route_id, train_id, timestamp_s):
            raise InterlockingRouteError(
                f"Interlocking route '{route_id}' is unavailable due to conflicting lock or occupied resource.",
                context={"route_id": route_id, "train_id": train_id},
            )

        r_def = r_state.route_def
        r_state.state = RouteLockState.REQUESTED
        r_state.allocated_train_id = train_id
        r_state.request_time_s = timestamp_s

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.ROUTE_REQUESTED,
                resource_id=route_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Route '{route_id}' requested for train '{train_id}'",
            )
        )

        # 1. Throw switches to required positions if needed
        max_throw_completion = timestamp_s
        for sw_id, req_pos in r_def.required_switch_positions.items():
            t_comp = self.switch_controller.throw_switch(
                switch_id=sw_id,
                desired_position=req_pos,
                timestamp_s=timestamp_s,
                route_id=route_id,
            )
            if t_comp > max_throw_completion:
                max_throw_completion = t_comp

        # Setup completion time (switch throw time + route setup time)
        lock_time = max(max_throw_completion, timestamp_s) + r_def.setup_time_s
        r_state.setup_completion_time_s = lock_time
        r_state.lock_time_s = lock_time
        r_state.state = RouteLockState.SETTING_UP

        # Lock switches in required positions
        for sw_id, req_pos in r_def.required_switch_positions.items():
            # Update switch position to target if throw has completed by lock time
            self.switch_controller.get_position(sw_id, lock_time)
            self.switch_controller.lock_switch(sw_id, route_id, req_pos, lock_time)

        # Reserve and lock protected blocks
        for bid in r_def.protected_block_ids:
            self.resource_controller.reserve_resource(
                train_id=train_id,
                resource_id=bid,
                timestamp_s=lock_time,
                route_id=route_id,
                running_direction=r_def.running_direction,
            )
            self.resource_controller.lock_resource(bid, route_id, lock_time)

        # Route is now locked
        r_state.state = RouteLockState.LOCKED
        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=lock_time,
                event_type=ResourceEventType.ROUTE_LOCKED,
                resource_id=route_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Route '{route_id}' locked for train '{train_id}'",
            )
        )
        return lock_time

    def release_route(self, route_id: str, timestamp_s: float) -> None:
        """P05-INT-009: Complete release of interlocking route and all associated locks."""
        r_state = self.active_states.get(route_id)
        if not r_state or r_state.state == RouteLockState.IDLE:
            return

        r_def = r_state.route_def
        train_id = r_state.allocated_train_id or "UNKNOWN"

        # Unlock all switches
        for sw_id in r_def.required_switch_positions.keys():
            self.switch_controller.unlock_switch(sw_id, route_id, timestamp_s)

        # Unlock and release all blocks
        for bid in r_def.protected_block_ids:
            self.resource_controller.unlock_resource(bid, route_id, timestamp_s)
            self.resource_controller.release_resource(train_id, bid, timestamp_s, route_id=route_id)

        r_state.state = RouteLockState.IDLE
        r_state.allocated_train_id = None
        r_state.released_block_ids.clear()

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.ROUTE_RELEASED,
                resource_id=route_id,
                train_id=train_id,
                route_id=route_id,
                description=f"Route '{route_id}' completely released",
            )
        )

    def process_sectional_release(
        self,
        route_id: str,
        cleared_block_id: str,
        timestamp_s: float,
    ) -> bool:
        """P05-INT-010: Sectional release of an individual block as train clears it."""
        r_state = self.active_states.get(route_id)
        if not r_state or not r_state.is_locked:
            return False

        if r_state.route_def.release_policy != ReleasePolicy.SECTIONAL:
            return False

        r_def = r_state.route_def
        if cleared_block_id in r_def.protected_block_ids and cleared_block_id not in r_state.released_block_ids:
            train_id = r_state.allocated_train_id or "UNKNOWN"
            # Unlock and release this specific block
            self.resource_controller.unlock_resource(cleared_block_id, route_id, timestamp_s)
            self.resource_controller.release_resource(train_id, cleared_block_id, timestamp_s, route_id=route_id)
            r_state.released_block_ids.add(cleared_block_id)

            # Check if all blocks are now released
            if set(r_def.protected_block_ids).issubset(r_state.released_block_ids):
                self.release_route(route_id, timestamp_s)
                return True
        return False
