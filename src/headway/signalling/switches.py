"""Switch controller, alignment states, throwing time, and switch locking.

Strictly satisfies RHS-P05-001 § 11:
- P05-SW-001: Switch position maintenance.
- P05-SW-002: Requested position validation.
- P05-SW-003: Configured switch throw time.
- P05-SW-004: Switch locking while required by established route.
- P05-SW-005: Rejection of incompatible requests for locked switches.
- P05-SW-006: Bidirectional evaluation using actual entry and exit links.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from headway.infrastructure.switches import Switch, SwitchMovement, SwitchPosition
from headway.signalling.resource_types import (
    ResourceEventType,
    SignallingEvent,
    SwitchLockError,
)


@dataclass
class SwitchState:
    """Operational state of an interlocking switch."""

    switch_id: str
    node_id: str
    current_position: SwitchPosition = SwitchPosition.NORMAL
    target_position: SwitchPosition = SwitchPosition.NORMAL
    throw_start_time_s: Optional[float] = None
    throw_time_s: float = 4.0
    locked_by_routes: Set[str] = field(default_factory=set)

    @property
    def is_locked(self) -> bool:
        return len(self.locked_by_routes) > 0

    @property
    def is_in_motion(self) -> bool:
        return self.throw_start_time_s is not None


class SwitchController:
    """Controls railway switches, throws, and interlocking switch locking."""

    def __init__(self, default_throw_time_s: float = 4.0) -> None:
        self.default_throw_time_s = default_throw_time_s
        self.switches: Dict[str, Switch] = {}
        self.states: Dict[str, SwitchState] = {}
        self.event_log: List[SignallingEvent] = []
        self._next_sequence_id: int = 1

    def _next_seq(self) -> int:
        seq = self._next_sequence_id
        self._next_sequence_id += 1
        return seq

    def register_switch(self, switch: Switch, initial_position: SwitchPosition = SwitchPosition.NORMAL) -> None:
        """Register physical switch and initialize its operational state."""
        self.switches[switch.switch_id] = switch
        self.states[switch.switch_id] = SwitchState(
            switch_id=switch.switch_id,
            node_id=switch.node_id,
            current_position=initial_position,
            target_position=initial_position,
            throw_time_s=self.default_throw_time_s,
        )

    def get_position(self, switch_id: str, current_time_s: float) -> SwitchPosition:
        """Return the current switch position, completing any in-progress throw if time expired."""
        state = self.states.get(switch_id)
        if not state:
            raise SwitchLockError(f"Unknown switch '{switch_id}'.")

        if state.throw_start_time_s is not None:
            if current_time_s >= state.throw_start_time_s + state.throw_time_s:
                # Throw completed
                state.current_position = state.target_position
                state.throw_start_time_s = None
        return state.current_position

    def throw_switch(
        self,
        switch_id: str,
        desired_position: SwitchPosition,
        timestamp_s: float,
        route_id: Optional[str] = None,
    ) -> float:
        """P05-SW-002, 003, 005: Command a switch throw. Returns timestamp when throw will complete."""
        state = self.states.get(switch_id)
        if not state:
            raise SwitchLockError(f"Unknown switch '{switch_id}'.")

        # P05-SW-005: Cannot throw locked switch for conflicting position
        if state.is_locked:
            if route_id not in state.locked_by_routes or desired_position != state.current_position:
                raise SwitchLockError(
                    f"Switch '{switch_id}' is locked by routes {state.locked_by_routes} and cannot be thrown to '{desired_position.value}'.",
                    context={"switch_id": switch_id, "locked_by": list(state.locked_by_routes)},
                )

        cur_pos = self.get_position(switch_id, timestamp_s)
        if cur_pos == desired_position:
            return timestamp_s

        # Begin throw
        state.target_position = desired_position
        state.throw_start_time_s = timestamp_s
        completion_time = timestamp_s + state.throw_time_s

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.SWITCH_THROWN,
                resource_id=switch_id,
                route_id=route_id,
                description=f"Switch '{switch_id}' throw initiated to {desired_position.value} (completion at {completion_time:.1f}s)",
                details={"target_position": desired_position.value, "completion_time_s": completion_time},
            )
        )
        return completion_time

    def lock_switch(
        self,
        switch_id: str,
        route_id: str,
        required_position: SwitchPosition,
        timestamp_s: float,
    ) -> None:
        """P05-SW-004: Lock switch in required position for route."""
        state = self.states.get(switch_id)
        if not state:
            raise SwitchLockError(f"Unknown switch '{switch_id}'.")

        cur_pos = self.get_position(switch_id, timestamp_s)
        if cur_pos != required_position:
            raise SwitchLockError(
                f"Cannot lock switch '{switch_id}' in position '{required_position.value}' "
                f"because current position is '{cur_pos.value}'.",
                context={"switch_id": switch_id, "required": required_position.value, "current": cur_pos.value},
            )

        state.locked_by_routes.add(route_id)
        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.SWITCH_LOCKED,
                resource_id=switch_id,
                route_id=route_id,
                description=f"Switch '{switch_id}' locked in {required_position.value} by route '{route_id}'",
            )
        )

    def unlock_switch(self, switch_id: str, route_id: str, timestamp_s: float) -> None:
        """Unlock switch previously locked by route."""
        state = self.states.get(switch_id)
        if state:
            state.locked_by_routes.discard(route_id)
            self.event_log.append(
                SignallingEvent(
                    sequence_id=self._next_seq(),
                    timestamp_s=timestamp_s,
                    event_type=ResourceEventType.SWITCH_UNLOCKED,
                    resource_id=switch_id,
                    route_id=route_id,
                    description=f"Switch '{switch_id}' unlocked by route '{route_id}'",
                )
            )

    def get_required_movement_position(
        self,
        entry_link_id: str,
        exit_link_id: str,
    ) -> Optional[Tuple[str, SwitchPosition]]:
        """P05-SW-006: Identify which switch and position are required for a transition between two links."""
        for sw in self.switches.values():
            m = sw.get_movement(entry_link_id, exit_link_id)
            if m is not None:
                return (sw.switch_id, m.position)
        return None
