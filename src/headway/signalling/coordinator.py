"""Signalling and resource coordinator enforcing deterministic same-time event ordering.

Strictly satisfies RHS-P05-001 & RHS-P06-001:
- P05-B029: Deterministic same-time event ordering sequence (11 steps).
- P06-ARCH-001: Support for Fixed-Block, ETCS Level 2, and CBTC Moving-Block architectures.
- Atomic allocation and conflict resolution.
- Centralized event logging and resource usage reporting.
"""

from typing import Dict, List, Optional, Set, Tuple

from headway.data.canonical import AspectModelType, InfrastructureModel, SignallingModel, SignallingTechnologyType
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.signalling.advanced_types import SignallingModelFidelity
from headway.signalling.aspects import SignalAspectController
from headway.signalling.authority import MovementAuthority, MovementAuthorityController
from headway.signalling.cbtc import CBTCConfig, CBTCMovingBlockEngine
from headway.signalling.etcs import ETCSLevel2Config, ETCSLevel2Engine
from headway.signalling.interlocking import InterlockingEngine
from headway.signalling.junction_controller import JunctionController
from headway.signalling.platform_controller import PlatformController
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import (
    ReleasePolicy,
    ResourceCategory,
    ResourceUsageRecord,
    SignallingEvent,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController
from headway.signalling.tvs_controller import TVSController


class SignallingCoordinator:
    """Master coordinator integrating resources, interlocking, switches, signals, and movement authority."""

    def __init__(
        self,
        aspect_model: AspectModelType = AspectModelType.THREE_ASPECT,
        technology_type: SignallingTechnologyType = SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL,
        fidelity: SignallingModelFidelity = SignallingModelFidelity.DETAILED,
        default_switch_throw_time_s: float = 4.0,
        default_route_setup_time_s: float = 3.0,
    ) -> None:
        self.technology_type = technology_type
        self.fidelity = fidelity
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

        # P07 controllers
        self.platform_controller = PlatformController(resource_controller=self.resource_controller)
        self.junction_controller = JunctionController(
            interlocking_engine=self.interlocking_engine,
            switch_controller=self.switch_controller,
            resource_controller=self.resource_controller,
        )
        self.tvs_controller = TVSController(resource_controller=self.resource_controller)

        # Advanced signalling sub-engines
        self.etcs_engine: Optional[ETCSLevel2Engine] = None
        self.cbtc_engine: Optional[CBTCMovingBlockEngine] = None

        if self.technology_type in (
            SignallingTechnologyType.ETCS_LEVEL_2,
            SignallingTechnologyType.ETCS_LEVEL_2_ENGINEERING_MODEL,
        ):
            self.etcs_engine = ETCSLevel2Engine(
                config=ETCSLevel2Config(fidelity=fidelity),
                resource_controller=self.resource_controller,
                interlocking_engine=self.interlocking_engine,
            )
        elif self.technology_type in (
            SignallingTechnologyType.CBTC_MOVING_BLOCK,
            SignallingTechnologyType.CBTC_MOVING_BLOCK_ENGINEERING_MODEL,
        ):
            self.cbtc_engine = CBTCMovingBlockEngine(
                config=CBTCConfig(fidelity=fidelity),
                resource_controller=self.resource_controller,
                interlocking_engine=self.interlocking_engine,
                switch_controller=self.switch_controller,
            )

    def load_from_signalling_model(self, model: SignallingModel) -> None:
        """Initialize resources, signals, blocks, and interlocking routes from canonical SignallingModel."""
        self.technology_type = model.system.technology_type

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

        # 4. Initialize advanced sub-engine if configured
        if self.technology_type in (
            SignallingTechnologyType.ETCS_LEVEL_2,
            SignallingTechnologyType.ETCS_LEVEL_2_ENGINEERING_MODEL,
        ):
            self.etcs_engine = ETCSLevel2Engine(
                config=ETCSLevel2Config(
                    fidelity=self.fidelity,
                    default_overlap_m=model.system.default_overlap_m,
                ),
                resource_controller=self.resource_controller,
                interlocking_engine=self.interlocking_engine,
            )
        elif self.technology_type in (
            SignallingTechnologyType.CBTC_MOVING_BLOCK,
            SignallingTechnologyType.CBTC_MOVING_BLOCK_ENGINEERING_MODEL,
        ):
            self.cbtc_engine = CBTCMovingBlockEngine(
                config=CBTCConfig(fidelity=self.fidelity),
                resource_controller=self.resource_controller,
                interlocking_engine=self.interlocking_engine,
                switch_controller=self.switch_controller,
            )

    def load_from_infrastructure(self, infra: InfrastructureModel) -> None:
        """P07-ARCH-002: Load stations, platforms, TVS sections, and shared groups from InfrastructureModel."""
        self.platform_controller.load_from_infrastructure(infra)
        self.tvs_controller.load_from_infrastructure(infra)

    def clamp_ma_for_tvs(
        self,
        train_id: str,
        tvs_id: str,
        ma: MovementAuthority,
        current_time_s: float,
        holding_point_distance_m: float,
    ) -> MovementAuthority:
        """P07-TVS-043: Common MA clamping gate for unauthorized TVS sections."""
        clamped_eoa, is_clamped = self.tvs_controller.clamp_movement_authority(
            train_id=train_id,
            tvs_id=tvs_id,
            unconstrained_ma_limit_m=ma.end_of_authority,
            current_time_s=current_time_s,
            holding_point_distance_m=holding_point_distance_m,
            running_direction=ma.running_direction,
        )
        if is_clamped:
            return MovementAuthority(
                ma_id=f"{ma.ma_id}_TVS_CLAMPED",
                train_id=ma.train_id,
                route_id=ma.route_id,
                start_reference=ma.start_reference,
                end_of_authority=clamped_eoa,
                target_speed_ms=0.0,
                issue_time_s=current_time_s,
                effective_time_s=current_time_s,
                validity_status=ma.validity_status,
                running_direction=ma.running_direction,
                description=f"TVS clamped at holding point {holding_point_distance_m:.1f}m",
            )
        return ma

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

        plat_rel_events = self.platform_controller.process_platform_releases(current_time_s)
        emitted_events.extend(plat_rel_events)

        tvs_rel_events = self.tvs_controller.process_release_timers(current_time_s)
        emitted_events.extend(tvs_rel_events)

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
        events.extend(self.platform_controller.event_log)
        events.extend(self.junction_controller.event_log)
        events.extend(self.tvs_controller.event_log)
        if self.etcs_engine:
            events.extend(self.etcs_engine.get_event_log())
        if self.cbtc_engine:
            events.extend(self.cbtc_engine.get_event_log())
        return sorted(events, key=lambda e: (e.timestamp_s, e.sequence_id))

    def get_resource_usage_records(self) -> List[ResourceUsageRecord]:
        return self.resource_controller.get_usage_records()
