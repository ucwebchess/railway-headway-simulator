"""Tunnel Ventilation Section (TVS) Control Engine.

Strictly satisfies RHS-P07-001:
- § 13: TVS Architecture & Canonical Model (P07-TVS-001 to P07-TVS-005)
- § 14: Single-Train Rule & Occupancy Policy (N_max = 1) (P07-TVS-006 to P07-TVS-010)
- § 15: TVS Request, Holding Point & Authorization Gate (P07-TVS-011 to P07-TVS-016)
- § 16: TVS Physical Entry & Clearance (P07-TVS-017 to P07-TVS-021)
- § 17: Post-Clearance Release Delay Timer (P07-TVS-022 to P07-TVS-025)
- § 18: Consecutive TVS Multi-Section Operations (P07-TVS-026 to P07-TVS-029)
- § 19: Cross-Track Shared TVS Groups (P07-TVS-030 to P07-TVS-033)
- § 20: TVS Events (P07-TVS-034 to P07-TVS-037)
- § 21: TVS Safety Invariants & Enforcement (P07-TVS-038 to P07-TVS-042)
- § 22: Signalling & Movement Authority Clamping Interface (P07-TVS-043 to P07-TVS-046)
- Full support for both FORWARD and REVERSE railway movements.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from headway.data.canonical import InfrastructureModel, SharedResourceGroup, Tunnel, TVSSection
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.tunnels import RouteTVSSection, TunnelTVSModel
from headway.signalling.resource_types import (
    ReleasePolicy,
    ResourceCategory,
    ResourceEventType,
    SignallingEvent,
    TVSAuthorizationError,
    TVSInvariantError,
)
from headway.signalling.resources import ManagedResource, ResourceController


class TVSExclusivityScope(str, Enum):
    """Scope of exclusivity for single-train rule enforcement."""

    PER_TRACK = "PER_TRACK"
    CROSS_TRACK_SHARED_TVS = "CROSS_TRACK_SHARED_TVS"
    WHOLE_TUNNEL = "WHOLE_TUNNEL"


class TVSAuthorizationState(str, Enum):
    """Authorization lifecycle states for a train at a TVS section."""

    UNAUTHORIZED = "UNAUTHORIZED"
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"


class TVSPhysicalOccupancyState(str, Enum):
    """Physical occupation state of a train relative to a TVS section."""

    NOT_ENTERED = "NOT_ENTERED"
    FRONT_ENTERED = "FRONT_ENTERED"
    FULLY_INSIDE = "FULLY_INSIDE"
    FRONT_EXITED = "FRONT_EXITED"
    REAR_CLEARED = "REAR_CLEARED"


@dataclass
class TVSTrainState:
    """Dynamic operational state of a train regarding a TVS section."""

    train_id: str
    tvs_id: str
    auth_state: TVSAuthorizationState = TVSAuthorizationState.UNAUTHORIZED
    phys_state: TVSPhysicalOccupancyState = TVSPhysicalOccupancyState.NOT_ENTERED
    running_direction: RunningDirection = RunningDirection.FORWARD
    request_time_s: Optional[float] = None
    authorized_time_s: Optional[float] = None
    front_entry_time_s: Optional[float] = None
    front_exit_time_s: Optional[float] = None
    rear_clear_time_s: Optional[float] = None
    release_time_s: Optional[float] = None


@dataclass
class TVSSectionConfig:
    """Runtime configuration of a TVS section."""

    tvs: TVSSection
    max_train_occupancy: int = 1
    release_delay_s: float = 5.0
    auth_processing_delay_s: float = 1.0
    exclusivity_scope: TVSExclusivityScope = TVSExclusivityScope.PER_TRACK
    holding_point_offset_m: Optional[float] = None
    shared_group_id: Optional[str] = None


class TVSController:
    """Manages TVS sections, entry authorization, single-train rule, release timers, and MA clamping."""

    def __init__(
        self,
        resource_controller: ResourceController,
        default_release_delay_s: float = 5.0,
        default_auth_delay_s: float = 1.0,
    ) -> None:
        self.resource_controller = resource_controller
        self.default_release_delay_s = default_release_delay_s
        self.default_auth_delay_s = default_auth_delay_s

        self.configs: Dict[str, TVSSectionConfig] = {}
        self.tunnel_to_tvs: Dict[str, Set[str]] = {}
        self.shared_groups: Dict[str, Set[str]] = {}  # group_id -> set of tvs_ids
        self.train_states: Dict[Tuple[str, str], TVSTrainState] = {}  # (train_id, tvs_id) -> state
        self.active_occupants: Dict[str, Set[str]] = {}  # tvs_id -> set of train_ids physically inside
        self.active_authorizations: Dict[str, Set[str]] = {}  # tvs_id -> set of train_ids authorized
        self.pending_releases: Dict[str, Tuple[str, float]] = {}  # tvs_id -> (train_id, target_release_time_s)

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

    def register_tvs_section(
        self,
        tvs: TVSSection,
        max_train_occupancy: int = 1,
        release_delay_s: Optional[float] = None,
        auth_processing_delay_s: Optional[float] = None,
        exclusivity_scope: TVSExclusivityScope = TVSExclusivityScope.PER_TRACK,
        holding_point_offset_m: Optional[float] = None,
        shared_group_id: Optional[str] = None,
    ) -> ManagedResource:
        """P07-TVS-001 & P07-RES-001: Register TVS section and create canonical TVS_SECTION resource."""
        rel_delay = release_delay_s if release_delay_s is not None else (
            tvs.release_delay_s if tvs.release_delay_s > 0 else self.default_release_delay_s
        )
        auth_delay = auth_processing_delay_s if auth_processing_delay_s is not None else self.default_auth_delay_s

        cfg = TVSSectionConfig(
            tvs=tvs,
            max_train_occupancy=max_train_occupancy,
            release_delay_s=rel_delay,
            auth_processing_delay_s=auth_delay,
            exclusivity_scope=exclusivity_scope,
            holding_point_offset_m=holding_point_offset_m,
            shared_group_id=shared_group_id,
        )
        self.configs[tvs.tvs_id] = cfg
        self.active_occupants[tvs.tvs_id] = set()
        self.active_authorizations[tvs.tvs_id] = set()

        if tvs.tunnel_id not in self.tunnel_to_tvs:
            self.tunnel_to_tvs[tvs.tunnel_id] = set()
        self.tunnel_to_tvs[tvs.tunnel_id].add(tvs.tvs_id)

        if shared_group_id:
            if shared_group_id not in self.shared_groups:
                self.shared_groups[shared_group_id] = set()
            self.shared_groups[shared_group_id].add(tvs.tvs_id)

        # Register in common ResourceController
        res = ManagedResource(
            resource_id=tvs.tvs_id,
            category=ResourceCategory.TVS_SECTION,
            capacity=max_train_occupancy,
            release_delay_s=rel_delay,
            description=f"Tunnel Ventilation Section '{tvs.tvs_id}' in tunnel '{tvs.tunnel_id}'",
        )
        self.resource_controller.register_resource(res)
        return res

    def register_shared_group(self, group: SharedResourceGroup) -> None:
        """P07-TVS-030: Register cross-track shared TVS group in both TVSController and ResourceController."""
        self.shared_groups[group.group_id] = set(group.resource_ids)
        for r_id in group.resource_ids:
            if r_id in self.configs:
                self.configs[r_id].exclusivity_scope = TVSExclusivityScope.CROSS_TRACK_SHARED_TVS
                self.configs[r_id].shared_group_id = group.group_id
        self.resource_controller.register_conflict_group(group)

    def load_from_infrastructure(self, infra: InfrastructureModel) -> None:
        """Load all TVS sections and shared groups from canonical InfrastructureModel."""
        for tvs in infra.tvs_sections:
            self.register_tvs_section(tvs)
        for grp in infra.shared_resource_groups:
            self.register_shared_group(grp)

    def is_tvs_available(self, tvs_id: str, train_id: str, current_time_s: float) -> Tuple[bool, Optional[str]]:
        """P07-TVS-006 to 010: Check whether TVS section can accept another authorization."""
        cfg = self.configs.get(tvs_id)
        if not cfg:
            return False, f"TVS section '{tvs_id}' is not registered."

        # Check pending release timer
        if tvs_id in self.pending_releases:
            target_rel_s = self.pending_releases[tvs_id][1]
            if current_time_s < target_rel_s:
                return False, f"TVS '{tvs_id}' is in post-clearance release delay until t={target_rel_s:.1f}s."

        # Check self occupancy and authorization count
        active_trains = self.active_occupants.get(tvs_id, set()).union(self.active_authorizations.get(tvs_id, set()))
        if train_id in active_trains:
            return True, None

        if len(active_trains) >= cfg.max_train_occupancy:
            return False, f"TVS '{tvs_id}' reached capacity ({len(active_trains)}/{cfg.max_train_occupancy})."

        # Check scope exclusivity
        if cfg.exclusivity_scope == TVSExclusivityScope.CROSS_TRACK_SHARED_TVS and cfg.shared_group_id:
            peer_ids = self.shared_groups.get(cfg.shared_group_id, set())
            for pid in peer_ids:
                if pid != tvs_id:
                    peer_trains = self.active_occupants.get(pid, set()).union(self.active_authorizations.get(pid, set()))
                    if peer_trains and train_id not in peer_trains:
                        return False, f"Cross-track shared TVS '{pid}' in group '{cfg.shared_group_id}' is occupied by {peer_trains}."

        elif cfg.exclusivity_scope == TVSExclusivityScope.WHOLE_TUNNEL:
            tunnel_tvss = self.tunnel_to_tvs.get(cfg.tvs.tunnel_id, set())
            for tid in tunnel_tvss:
                if tid != tvs_id:
                    tun_trains = self.active_occupants.get(tid, set()).union(self.active_authorizations.get(tid, set()))
                    if tun_trains and train_id not in tun_trains:
                        return False, f"Whole-tunnel exclusivity: TVS '{tid}' is occupied by {tun_trains}."

        return True, None

    def request_tvs_entry(
        self,
        train_id: str,
        tvs_id: str,
        timestamp_s: float,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> Tuple[bool, Optional[float]]:
        """P07-TVS-011 to 016: Request entry authorization for TVS section.

        Returns (is_authorized, authorized_effective_time_s).
        """
        cfg = self.configs.get(tvs_id)
        if not cfg:
            raise TVSAuthorizationError(f"TVS section '{tvs_id}' not found.", context={"tvs_id": tvs_id})

        state_key = (train_id, tvs_id)
        st = self.train_states.get(state_key)
        if not st:
            st = TVSTrainState(
                train_id=train_id,
                tvs_id=tvs_id,
                running_direction=running_direction,
            )
            self.train_states[state_key] = st

        st.auth_state = TVSAuthorizationState.REQUESTED
        st.request_time_s = timestamp_s

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.TVS_ENTRY_REQUESTED,
            resource_id=tvs_id,
            train_id=train_id,
            description=f"Train '{train_id}' requested TVS '{tvs_id}' entry ({running_direction.value})",
            details={"direction": running_direction.value},
        )

        available, reason = self.is_tvs_available(tvs_id, train_id, timestamp_s)
        if not available:
            st.auth_state = TVSAuthorizationState.REJECTED
            self._log_event(
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.TVS_ENTRY_REJECTED,
                resource_id=tvs_id,
                train_id=train_id,
                description=f"TVS '{tvs_id}' entry rejected for train '{train_id}': {reason}",
                details={"reason": reason},
            )
            return False, None

        # Authorize with processing delay
        auth_effective_time = timestamp_s + cfg.auth_processing_delay_s
        st.auth_state = TVSAuthorizationState.AUTHORIZED
        st.authorized_time_s = auth_effective_time
        self.active_authorizations[tvs_id].add(train_id)

        # Reserve in resource controller
        self.resource_controller.reserve_resource(
            train_id=train_id,
            resource_id=tvs_id,
            timestamp_s=timestamp_s,
            running_direction=running_direction,
        )

        self._log_event(
            timestamp_s=auth_effective_time,
            event_type=ResourceEventType.TVS_ENTRY_AUTHORIZED,
            resource_id=tvs_id,
            train_id=train_id,
            description=f"Train '{train_id}' authorized for TVS '{tvs_id}' effective at t={auth_effective_time:.1f}s",
            details={"auth_effective_time_s": auth_effective_time},
        )
        return True, auth_effective_time

    def is_train_authorized(self, train_id: str, tvs_id: str, current_time_s: float) -> bool:
        """Check if train has a valid authorization in effect at current_time_s."""
        st = self.train_states.get((train_id, tvs_id))
        if not st or st.auth_state != TVSAuthorizationState.AUTHORIZED:
            return False
        if st.authorized_time_s is None or current_time_s < st.authorized_time_s:
            return False
        return True

    def front_enter_tvs(
        self,
        train_id: str,
        tvs_id: str,
        timestamp_s: float,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> None:
        """P07-TVS-017 & P07-TVS-038: Train front physically enters TVS boundary."""
        cfg = self.configs.get(tvs_id)
        if not cfg:
            raise TVSAuthorizationError(f"TVS section '{tvs_id}' not found.", context={"tvs_id": tvs_id})

        # Check authorization gate
        if not self.is_train_authorized(train_id, tvs_id, timestamp_s):
            self._log_event(
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.TVS_INVARIANT_VIOLATION,
                resource_id=tvs_id,
                train_id=train_id,
                description=f"SAFETY INVARIANT VIOLATION: Unauthorized train '{train_id}' entered TVS '{tvs_id}'!",
            )
            raise TVSInvariantError(
                f"Unauthorized train '{train_id}' breached TVS section '{tvs_id}' without valid entry authorization!",
                context={"train_id": train_id, "tvs_id": tvs_id, "timestamp_s": timestamp_s},
            )

        # Check capacity invariant
        current_occ = self.active_occupants.get(tvs_id, set())
        if train_id not in current_occ and len(current_occ) >= cfg.max_train_occupancy:
            self._log_event(
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.TVS_INVARIANT_VIOLATION,
                resource_id=tvs_id,
                train_id=train_id,
                description=f"SAFETY INVARIANT VIOLATION: TVS '{tvs_id}' capacity exceeded ({len(current_occ)} >= {cfg.max_train_occupancy})!",
            )
            raise TVSInvariantError(
                f"Single-train rule violated: TVS section '{tvs_id}' capacity {cfg.max_train_occupancy} "
                f"exceeded by train '{train_id}'! Current occupants: {current_occ}",
                context={"tvs_id": tvs_id, "train_id": train_id, "current_occupants": list(current_occ)},
            )

        # Transition physical state
        st = self.train_states[(train_id, tvs_id)]
        st.phys_state = TVSPhysicalOccupancyState.FRONT_ENTERED
        st.front_entry_time_s = timestamp_s
        self.active_occupants[tvs_id].add(train_id)

        # Notify resource controller
        self.resource_controller.front_enter_resource(
            train_id=train_id,
            resource_id=tvs_id,
            timestamp_s=timestamp_s,
        )

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.TVS_FRONT_ENTERED,
            resource_id=tvs_id,
            train_id=train_id,
            description=f"Train '{train_id}' front entered TVS '{tvs_id}' ({running_direction.value})",
            details={"direction": running_direction.value},
        )

    def front_exit_tvs(
        self,
        train_id: str,
        tvs_id: str,
        timestamp_s: float,
    ) -> None:
        """P07-TVS-018 & P07-TVS-021: Train front exits TVS exit boundary.

        Strictly prohibits release! TVS section remains occupied until train rear clears.
        """
        st = self.train_states.get((train_id, tvs_id))
        if st:
            st.phys_state = TVSPhysicalOccupancyState.FRONT_EXITED
            st.front_exit_time_s = timestamp_s

        self.resource_controller.front_exit_resource(
            train_id=train_id,
            resource_id=tvs_id,
            timestamp_s=timestamp_s,
        )

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.TVS_FRONT_EXITED,
            resource_id=tvs_id,
            train_id=train_id,
            description=f"Train '{train_id}' front exited TVS '{tvs_id}'. Resource REMAINS OCCUPIED until rear clears.",
        )

    def rear_clear_tvs(
        self,
        train_id: str,
        tvs_id: str,
        timestamp_s: float,
    ) -> float:
        """P07-TVS-019 & P07-TVS-022: Train rear completely clears TVS section.

        Starts post-clearance release delay timer.
        Returns scheduled release timestamp.
        """
        cfg = self.configs.get(tvs_id)
        if not cfg:
            raise TVSAuthorizationError(f"TVS section '{tvs_id}' not found.")

        st = self.train_states.get((train_id, tvs_id))
        if st:
            st.phys_state = TVSPhysicalOccupancyState.REAR_CLEARED
            st.rear_clear_time_s = timestamp_s

        self.resource_controller.rear_clear_resource(
            train_id=train_id,
            resource_id=tvs_id,
            timestamp_s=timestamp_s,
        )

        if tvs_id in self.active_occupants:
            self.active_occupants[tvs_id].discard(train_id)

        target_release_s = timestamp_s + cfg.release_delay_s
        self.pending_releases[tvs_id] = (train_id, target_release_s)

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.TVS_REAR_CLEARED,
            resource_id=tvs_id,
            train_id=train_id,
            description=f"Train '{train_id}' rear cleared TVS '{tvs_id}'",
        )
        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.TVS_RELEASE_TIMER_STARTED,
            resource_id=tvs_id,
            train_id=train_id,
            description=f"TVS '{tvs_id}' post-clearance release timer started ({cfg.release_delay_s}s delay; target={target_release_s:.1f}s)",
            details={"release_delay_s": cfg.release_delay_s, "target_release_s": target_release_s},
        )
        return target_release_s

    def process_release_timers(self, current_time_s: float) -> List[SignallingEvent]:
        """P07-TVS-024: Process release timers and release TVS sections once delay has elapsed."""
        released_events: List[SignallingEvent] = []
        due_tvs_ids = [
            tid for tid, (tr_id, rel_time) in self.pending_releases.items() if current_time_s >= rel_time - 1e-4
        ]

        for tvs_id in due_tvs_ids:
            tr_id, rel_time = self.pending_releases.pop(tvs_id)
            if tvs_id in self.active_authorizations:
                self.active_authorizations[tvs_id].discard(tr_id)

            st = self.train_states.get((tr_id, tvs_id))
            if st:
                st.release_time_s = current_time_s

            self.resource_controller.release_resource(
                train_id=tr_id,
                resource_id=tvs_id,
                timestamp_s=current_time_s,
            )

            evt = self._log_event(
                timestamp_s=current_time_s,
                event_type=ResourceEventType.TVS_RELEASED,
                resource_id=tvs_id,
                train_id=tr_id,
                description=f"TVS '{tvs_id}' released and available after post-clearance delay",
            )
            released_events.append(evt)

        return released_events

    def clamp_movement_authority(
        self,
        train_id: str,
        tvs_id: str,
        unconstrained_ma_limit_m: float,
        current_time_s: float,
        holding_point_distance_m: float,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> Tuple[float, bool]:
        """P07-TVS-043 to 046: Clamps MA at TVS entry holding point if TVS is unauthorized.

        Returns (clamped_ma_distance_m, is_clamped).
        """
        if self.is_train_authorized(train_id, tvs_id, current_time_s):
            # Authorized: MA is unconstrained by TVS gate
            return unconstrained_ma_limit_m, False

        # Unauthorized: MA MUST be clamped at or before holding point
        if running_direction == RunningDirection.FORWARD:
            if unconstrained_ma_limit_m > holding_point_distance_m:
                return holding_point_distance_m, True
        else:
            if unconstrained_ma_limit_m < holding_point_distance_m:
                return holding_point_distance_m, True

        return unconstrained_ma_limit_m, False

    def verify_safety_invariants(self, current_time_s: float) -> None:
        """P07-TVS-038 to 042: Verify all TVS single-train and physical clearance safety invariants."""
        for tvs_id, cfg in self.configs.items():
            occupants = self.active_occupants.get(tvs_id, set())
            if len(occupants) > cfg.max_train_occupancy:
                raise TVSInvariantError(
                    f"INVARIANT VIOLATION: TVS '{tvs_id}' has {len(occupants)} occupants, exceeding limit {cfg.max_train_occupancy}!",
                    context={"tvs_id": tvs_id, "occupants": list(occupants), "limit": cfg.max_train_occupancy},
                )

            # Check unauthorized occupancy
            for tr_id in occupants:
                st = self.train_states.get((tr_id, tvs_id))
                if not st or st.auth_state != TVSAuthorizationState.AUTHORIZED:
                    raise TVSInvariantError(
                        f"INVARIANT VIOLATION: Train '{tr_id}' is physically occupying TVS '{tvs_id}' without authorization!",
                        context={"train_id": tr_id, "tvs_id": tvs_id},
                    )

            # Check shared group cross-track exclusivity
            if cfg.exclusivity_scope == TVSExclusivityScope.CROSS_TRACK_SHARED_TVS and cfg.shared_group_id:
                peer_ids = self.shared_groups.get(cfg.shared_group_id, set())
                active_group_trains: Set[str] = set()
                for pid in peer_ids:
                    active_group_trains.update(self.active_occupants.get(pid, set()))
                if len(active_group_trains) > 1:
                    raise TVSInvariantError(
                        f"INVARIANT VIOLATION: Shared TVS group '{cfg.shared_group_id}' occupied by multiple trains: {active_group_trains}!",
                        context={"shared_group_id": cfg.shared_group_id, "trains": list(active_group_trains)},
                    )
