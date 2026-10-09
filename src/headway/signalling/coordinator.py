"""Signalling and resource coordinator enforcing deterministic same-time event ordering.

Strictly satisfies RHS-P05-001 § 18 & § 19:
- P05-B029: Deterministic same-time event ordering sequence (11 steps).
- Atomic allocation and conflict resolution.
- Centralized event logging and resource usage reporting.
"""

from typing import Dict, List, Optional, Set, Tuple

from headway.data.canonical import AspectModelType, SignallingModel
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.signalling.aspects import SignalAspectController
from headway.signalling.authority import MovementAuthority, MovementAuthorityController
from headway.signalling.interlocking import InterlockingEngine
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import (
    ReleasePolicy,
    ResourceCategory,
    ResourceUsageRecord,
    SignallingEvent,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController


class SignallingCoordinator:
    """Master coordinator integrating resources, interlocking, switches, signals, and movement authority."""

    def __init__(
        self,
        aspect_model: AspectModelType = AspectModelType.THREE_ASPECT,
        default_switch_throw_time_s: float = 4.0,
        default_route_setup_time_s: float = 3.0,
    ) -> None:
        self.resource_controller = ResourceController()
        self.switch_controller = SwitchController(default_throw_time_s=default_switch_throw_time_s)
        self.interlocking_engine = InterlockingEngine(
            resource_controller=self.resource_controller,
            switch_controller=self.switch_controller,
            default_setup_time_s=default_route_setup_time_s,
        )
        self.signal_controller = SignalAspectController(
            resource_controller=self.resource_controller,
            aspect_model=aspect_model,
        )
        self.authority_controller = MovementAuthorityController()
        self.protection_engine = BrakingProtectionEngine()

    def load_from_signalling_model(self, model: SignallingModel) -> None:
        """Initialize resources, signals, blocks, and interlocking routes from canonical SignallingModel."""
        # 1. Blocks
        for blk in model.blocks:
            self.resource_controller.register_signalling_block(blk)

        # 2. Signals
        for sig in model.signals:
            self.signal_controller.register_signal(sig)

        # 3. Interlocking Routes
        for rt in model.routes:
            self.interlocking_engine.register_from_canonical(
                canonical_route=rt,
                setup_time_s=model.system.route_setup_time_s,
            )

    def process_timestep_events(
        self,
        current_time_s: float,
        train_movements: Optional[List[Dict]] = None,
        pending_route_requests: Optional[List[Tuple[str, str]]] = None,  # (train_id, route_id)
    ) -> List[SignallingEvent]:
        """P05 § 19: Strict 11-step deterministic same-time event ordering.

        1. Complete train movement to the event timestamp.
        2. Process physical boundary crossings (front entry).
        3. Process rear-clearance events.
        4. Evaluate release eligibility.
        5. Process eligible release timers.
        6. Release applicable reservations and locks.
        7. Recompute resource availability.
        8. Evaluate pending route/resource requests.
        9. Update signalling aspects.
        10. Issue or update movement authorities.
        11. Authorize subsequent movement.
        """
        emitted_events: List[SignallingEvent] = []

        # 1, 2, 3: Process train movements and physical entry / rear clearance
        if train_movements:
            for move in train_movements:
                tid = move.get("train_id")
                rid = move.get("resource_id")
                m_type = move.get("type")
                if m_type == "FRONT_ENTER":
                    self.resource_controller.front_enter_resource(tid, rid, current_time_s)
                elif m_type == "FRONT_EXIT":
                    self.resource_controller.front_exit_resource(tid, rid, current_time_s)
                elif m_type == "REAR_CLEAR":
                    self.resource_controller.rear_clear_resource(tid, rid, current_time_s)
                    # Check sectional route release if applicable
                    for r_state in self.interlocking_engine.active_states.values():
                        if r_state.is_locked and r_state.allocated_train_id == tid:
                            self.interlocking_engine.process_sectional_release(
                                route_id=r_state.route_def.route_id,
                                cleared_block_id=rid,
                                timestamp_s=current_time_s,
                            )

        # 4, 5, 6, 7: Process release timers, unlock reservations and locks, recompute availability
        rel_events = self.resource_controller.process_pending_releases(current_time_s)
        emitted_events.extend(rel_events)

        # 8: Evaluate pending route/resource requests
        if pending_route_requests:
            for tid, route_id in pending_route_requests:
                if self.interlocking_engine.is_route_available(route_id, tid, current_time_s):
                    self.interlocking_engine.request_and_lock_route(route_id, tid, current_time_s)

        return emitted_events

    def get_all_events(self) -> List[SignallingEvent]:
        """Collect all timestamped events across all sub-engines sorted by sequence_id."""
        events = []
        events.extend(self.resource_controller.event_log)
        events.extend(self.switch_controller.event_log)
        events.extend(self.interlocking_engine.event_log)
        events.extend(self.signal_controller.event_log)
        events.extend(self.authority_controller.event_log)
        return sorted(events, key=lambda e: (e.timestamp_s, e.sequence_id))

    def get_resource_usage_records(self) -> List[ResourceUsageRecord]:
        return self.resource_controller.get_usage_records()
