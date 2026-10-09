"""ETCS Level 2 engineering model with Radio Block Centre (RBC) and supervision curves.

Strictly satisfies RHS-P06-001:
- P06-ETCS: Fixed train detection with Radio Block Centre movement authority.
- P06-RBC: Radio communication, position reports, MA generation and extension.
- P06-COM: Uplink, downlink, processing delays, and communication timeout handling.
- P06-ETCS-BRK: Braking supervision curves (Indication, Permitted, Warning, Intervention).
- P06-ETCS-TGT: Direct P04 BrakingTarget integration and Danger Point / Overlap protection.
- P06-ETCS-INT: Feasibility validation and automatic emergency intervention.
- Controlled Benchmark A: Stopping distance d = 600.0 m (v0 = 30 m/s, b = 0.75 m/s^2).
- Controlled Benchmark C: Effective MA time t_effective = 101.0 s (t_issue = 100.0 s, t_comm = 1.0 s).
- Full support for both FORWARD and REVERSE railway operations.
"""

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Tuple

from headway.data.canonical import SignallingTechnologyType
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.rolling_stock.braking import BrakingCategory, BrakingModel, ConstantDecelerationBrakingModel
from headway.signalling.advanced_types import (
    AdvancedSignallingEngine,
    RadioCommunicationConfig,
    SignallingModelFidelity,
    SupervisionProfile,
    SupervisionState,
    TrainIntegrityStatus,
    TrainPositionReport,
)
from headway.signalling.authority import AuthorityValidity, MovementAuthority
from headway.signalling.interlocking import InterlockingEngine
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import (
    BrakingFeasibilityError,
    CommunicationTimeoutError,
    MovementAuthorityError,
    PositionReportError,
    ResourceEventType,
    SignallingEvent,
    SupervisionInterventionError,
)
from headway.signalling.resources import ResourceController
from headway.signalling.switches import SwitchController
from headway.simulation.targets import BrakingTarget, BrakingTargetType


@dataclass
class ETCSLevel2Config:
    """Configuration parameters for ETCS Level 2 signalling model."""

    fidelity: SignallingModelFidelity = SignallingModelFidelity.DETAILED
    communication_config: RadioCommunicationConfig = field(default_factory=RadioCommunicationConfig)
    default_overlap_m: float = 50.0
    service_deceleration_ms2: float = 0.75
    emergency_deceleration_ms2: float = 1.0
    warning_margin_speed_ms: float = 1.38889  # 5.0 km/h
    intervention_margin_speed_ms: float = 2.77778  # 10.0 km/h
    indication_time_s: float = 4.0
    communication_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if self.default_overlap_m < 0:
            raise MovementAuthorityError("Default overlap distance must be non-negative.")
        if self.service_deceleration_ms2 <= 0 or self.emergency_deceleration_ms2 <= 0:
            raise MovementAuthorityError("Deceleration capabilities must be strictly positive.")


class RadioBlockCentre:
    """Radio Block Centre (RBC) responsible for ETCS Level 2 train supervision and MAs."""

    def __init__(
        self,
        config: ETCSLevel2Config,
        resource_controller: ResourceController,
        interlocking_engine: InterlockingEngine,
    ) -> None:
        self.config = config
        self.resource_controller = resource_controller
        self.interlocking_engine = interlocking_engine
        self.train_lengths: Dict[str, float] = {}
        self.last_reports: Dict[str, TrainPositionReport] = {}
        self.last_report_times: Dict[str, float] = {}
        self.active_authorities: Dict[str, MovementAuthority] = {}
        self.authority_history: List[MovementAuthority] = []
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
        details: Optional[Dict] = None,
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

    def register_train(self, train_id: str, train_length_m: float) -> None:
        self.train_lengths[train_id] = train_length_m

    def receive_position_report(
        self,
        report: TrainPositionReport,
        current_time_s: float,
    ) -> bool:
        """Process train position update via Euroradio communication."""
        tid = report.train_id
        last_t = self.last_report_times.get(tid)

        if last_t is not None:
            dt = current_time_s - last_t
            if dt > self.config.communication_timeout_s:
                self._log_event(
                    timestamp_s=current_time_s,
                    event_type=ResourceEventType.COMMUNICATION_TIMEOUT,
                    resource_id=f"RBC_LINK_{tid}",
                    train_id=tid,
                    description=f"Euroradio communication timed out for train '{tid}' (elapsed {dt:.2f}s > {self.config.communication_timeout_s:.2f}s).",
                    details={"elapsed_s": dt, "timeout_s": self.config.communication_timeout_s},
                )
                raise CommunicationTimeoutError(
                    f"RBC communication timed out for train '{tid}': {dt:.2f} s elapsed.",
                    context={"train_id": tid, "elapsed_s": dt, "timeout_s": self.config.communication_timeout_s},
                )

        self.last_reports[tid] = report
        self.last_report_times[tid] = current_time_s

        self._log_event(
            timestamp_s=current_time_s,
            event_type=ResourceEventType.RADIO_MESSAGE_RECEIVED,
            resource_id=f"RBC_LINK_{tid}",
            train_id=tid,
            description=f"RBC received position report from train '{tid}' at s={report.front_position_m:.1f}m",
            details={"speed_ms": report.speed_ms, "front_m": report.front_position_m},
        )
        self._log_event(
            timestamp_s=current_time_s,
            event_type=ResourceEventType.POSITION_REPORT_RECEIVED,
            resource_id=report.link_id,
            train_id=tid,
            description=f"Train position recorded on link '{report.link_id}' at s={report.front_position_m:.1f}m",
            details={"uncertainty_m": report.localization_uncertainty_m, "integrity": report.integrity_status.value},
        )
        return True

    def check_communication_timeout(self, train_id: str, current_time_s: float) -> bool:
        """Check if communication with train has expired."""
        last_t = self.last_report_times.get(train_id)
        if last_t is None:
            return False
        dt = current_time_s - last_t
        if dt > self.config.communication_timeout_s:
            self._log_event(
                timestamp_s=current_time_s,
                event_type=ResourceEventType.COMMUNICATION_TIMEOUT,
                resource_id=f"RBC_LINK_{train_id}",
                train_id=train_id,
                description=f"Euroradio communication timed out for train '{train_id}' (elapsed {dt:.2f}s)",
                details={"elapsed_s": dt, "timeout_s": self.config.communication_timeout_s},
            )
            return True
        return False

    def compute_movement_authority(
        self,
        train_id: str,
        route: Route,
        current_time_s: float,
        start_position_m: Optional[float] = None,
        target_speed_ms: float = 0.0,
    ) -> MovementAuthority:
        """P06-RBC: Issue Movement Authority based on interlocking route and fixed blocks."""
        last_rep = self.last_reports.get(train_id)
        start_pos = start_position_m if start_position_m is not None else (
            last_rep.front_position_m if last_rep is not None else 0.0
        )

        running_dir = route.traversals[0].direction if route.traversals else RunningDirection.FORWARD

        # Determine End of Authority (EoA) along route
        # In ETCS L2, train authority extends through locked, unoccupied blocks up to the first obstacle
        route_len = route.total_length_m
        eoa_m = route_len

        # Check interlocking route definition if registered
        route_def = self.interlocking_engine.routes.get(route.route_id)
        if route_def:
            # Check route blocks sequentially
            cum_dist = 0.0
            for blk_id in route_def.protected_block_ids:
                res = self.resource_controller.get_resource(blk_id)
                blk_len = res.length_m if (res and res.length_m > 0) else 1000.0
                if res and res.is_occupied and (train_id not in res.occupants):
                    # Block is occupied by another train: EoA is at start of this block
                    eoa_m = min(eoa_m, cum_dist)
                    break
                cum_dist += blk_len

        if eoa_m < start_pos:
            eoa_m = start_pos

        effective_time = self.config.communication_config.calculate_effective_time(
            issue_time_s=current_time_s,
            fidelity=self.config.fidelity,
        )

        # Danger point / Overlap protection
        danger_point_m = round(eoa_m + self.config.default_overlap_m, 3)

        ma = MovementAuthority(
            ma_id=f"ETCS_MA_{train_id}_{self._next_seq()}",
            train_id=train_id,
            route_id=route.route_id,
            start_reference=round(start_pos, 3),
            end_of_authority=round(eoa_m, 3),
            target_speed_ms=round(target_speed_ms, 3),
            issue_time_s=current_time_s,
            effective_time_s=effective_time,
            validity_status=AuthorityValidity.ACTIVE,
            running_direction=running_dir,
            description=f"ETCS L2 MA to EoA={eoa_m:.1f}m (SvL={danger_point_m:.1f}m, effective t={effective_time:.1f}s)",
        )

        self.active_authorities[train_id] = ma
        self.authority_history.append(ma)

        self._log_event(
            timestamp_s=current_time_s,
            event_type=ResourceEventType.RADIO_MESSAGE_SENT,
            resource_id=f"RBC_LINK_{train_id}",
            train_id=train_id,
            route_id=route.route_id,
            description=f"RBC transmitted MA message to train '{train_id}' (effective_t={effective_time:.1f}s)",
            details={"eoa_m": eoa_m, "effective_time_s": effective_time},
        )
        self._log_event(
            timestamp_s=current_time_s,
            event_type=ResourceEventType.MA_ISSUED,
            resource_id=route.route_id,
            train_id=train_id,
            route_id=route.route_id,
            description=f"ETCS L2 MA issued: EoA={eoa_m:.1f}m, v_target={target_speed_ms:.1f}m/s",
            details={"start_m": start_pos, "eoa_m": eoa_m, "danger_point_m": danger_point_m},
        )
        return ma

    def extend_movement_authority(
        self,
        train_id: str,
        new_end_of_authority: float,
        current_time_s: float,
        target_speed_ms: float = 0.0,
    ) -> MovementAuthority:
        """P06-MA: Extend Movement Authority downstream as subsequent blocks clear."""
        curr_ma = self.active_authorities.get(train_id)
        if not curr_ma:
            raise MovementAuthorityError(f"No active ETCS L2 Movement Authority for train '{train_id}'.")

        if new_end_of_authority < curr_ma.end_of_authority:
            raise MovementAuthorityError(
                f"MA extension cannot retract EoA from {curr_ma.end_of_authority:.1f}m to {new_end_of_authority:.1f}m.",
                context={"train_id": train_id, "current_eoa": curr_ma.end_of_authority, "new_eoa": new_end_of_authority},
            )

        effective_time = self.config.communication_config.calculate_effective_time(
            issue_time_s=current_time_s,
            fidelity=self.config.fidelity,
        )
        danger_point_m = round(new_end_of_authority + self.config.default_overlap_m, 3)

        updated_ma = MovementAuthority(
            ma_id=f"ETCS_MA_{train_id}_{self._next_seq()}",
            train_id=train_id,
            route_id=curr_ma.route_id,
            start_reference=curr_ma.start_reference,
            end_of_authority=round(new_end_of_authority, 3),
            target_speed_ms=round(target_speed_ms, 3),
            issue_time_s=current_time_s,
            effective_time_s=effective_time,
            validity_status=AuthorityValidity.ACTIVE,
            running_direction=curr_ma.running_direction,
            description=f"ETCS L2 MA extended to EoA={new_end_of_authority:.1f}m (effective t={effective_time:.1f}s)",
        )

        self.active_authorities[train_id] = updated_ma
        self.authority_history.append(updated_ma)

        self._log_event(
            timestamp_s=current_time_s,
            event_type=ResourceEventType.MA_EXTENDED,
            resource_id=curr_ma.route_id,
            train_id=train_id,
            route_id=curr_ma.route_id,
            description=f"ETCS L2 MA extended for train '{train_id}' to EoA={new_end_of_authority:.1f}m",
            details={"old_eoa_m": curr_ma.end_of_authority, "new_eoa_m": new_end_of_authority},
        )
        return updated_ma


class ETCSLevel2Engine(AdvancedSignallingEngine):
    """P06-ETCS: Complete ETCS Level 2 signalling engine implementing AdvancedSignallingEngine."""

    def __init__(
        self,
        config: Optional[ETCSLevel2Config] = None,
        resource_controller: Optional[ResourceController] = None,
        interlocking_engine: Optional[InterlockingEngine] = None,
    ) -> None:
        cfg = config or ETCSLevel2Config()
        super().__init__(
            technology_type=SignallingTechnologyType.ETCS_LEVEL_2,
            fidelity=cfg.fidelity,
            communication_config=cfg.communication_config,
        )
        self.config = cfg
        self.resource_controller = resource_controller or ResourceController()
        self.interlocking_engine = interlocking_engine or InterlockingEngine(
            resource_controller=self.resource_controller,
            switch_controller=SwitchController(),
        )
        self.rbc = RadioBlockCentre(
            config=self.config,
            resource_controller=self.resource_controller,
            interlocking_engine=self.interlocking_engine,
        )

    def register_train(
        self,
        train_id: str,
        train_length_m: float,
        initial_route: Optional[Route] = None,
    ) -> None:
        self.rbc.register_train(train_id=train_id, train_length_m=train_length_m)

    def receive_position_report(
        self,
        report: TrainPositionReport,
        current_time_s: float,
    ) -> bool:
        return self.rbc.receive_position_report(report=report, current_time_s=current_time_s)

    def compute_movement_authority(
        self,
        train_id: str,
        route: Route,
        current_time_s: float,
        start_position_m: Optional[float] = None,
        target_speed_ms: float = 0.0,
    ) -> MovementAuthority:
        return self.rbc.compute_movement_authority(
            train_id=train_id,
            route=route,
            current_time_s=current_time_s,
            start_position_m=start_position_m,
            target_speed_ms=target_speed_ms,
        )

    def get_active_authority(self, train_id: str) -> Optional[MovementAuthority]:
        return self.rbc.active_authorities.get(train_id)

    def evaluate_supervision(
        self,
        train_id: str,
        current_speed_ms: float,
        current_position_m: float,
        braking_model: Optional[BrakingModel] = None,
    ) -> SupervisionProfile:
        """P06-ETCS-BRK / Benchmark A: Multi-curve braking supervision.

        v_perm = sqrt(v_target^2 + 2 * b_service * d)
        Benchmark A verification: v0=30 m/s, b=0.75 m/s^2, target=0 => d = 600.0 m.
        """
        ma = self.get_active_authority(train_id)
        if not ma:
            raise MovementAuthorityError(f"Cannot evaluate supervision: train '{train_id}' has no active MA.")

        dist_to_eoa = max(0.0, ma.end_of_authority - current_position_m)
        vt = ma.target_speed_ms

        b_srv = self.config.service_deceleration_ms2
        b_emg = self.config.emergency_deceleration_ms2
        overlap = self.config.default_overlap_m

        # Permitted curve
        v_perm = math.sqrt(max(0.0, (vt ** 2) + 2.0 * b_srv * dist_to_eoa))

        if self.config.fidelity == SignallingModelFidelity.BASIC:
            v_warn = v_perm
            v_int = v_perm
            v_ind = v_perm
        else:
            # INTERMEDIATE / DETAILED multi-stage curves
            v_warn = v_perm + self.config.warning_margin_speed_ms
            # Intervention allows braking into overlap (Danger Point = EoA + overlap)
            dist_to_svl = dist_to_eoa + overlap
            v_int_calc = math.sqrt(max(0.0, (vt ** 2) + 2.0 * b_emg * dist_to_svl))
            v_int = max(v_warn + 0.5, v_int_calc)

            # Indication curve gives reaction time before reaching permitted curve
            t_ind = self.config.indication_time_s
            dist_ind = max(0.0, dist_to_eoa - current_speed_ms * t_ind)
            v_ind = math.sqrt(max(0.0, (vt ** 2) + 2.0 * b_srv * dist_ind))

        # Determine state
        if current_speed_ms > v_int and dist_to_eoa > 0:
            state = SupervisionState.INTERVENTION
            self._log_event(
                timestamp_s=ma.issue_time_s,
                event_type=ResourceEventType.SUPERVISION_INTERVENTION,
                resource_id=ma.route_id,
                train_id=train_id,
                description=f"Supervision INTERVENTION triggered: v={current_speed_ms:.1f} m/s exceeds v_int={v_int:.1f} m/s",
                details={"speed_ms": current_speed_ms, "v_int": v_int, "dist_m": dist_to_eoa},
            )
        elif current_speed_ms > v_warn and dist_to_eoa > 0:
            state = SupervisionState.WARNING
            self._log_event(
                timestamp_s=ma.issue_time_s,
                event_type=ResourceEventType.SUPERVISION_WARNING,
                resource_id=ma.route_id,
                train_id=train_id,
                description=f"Supervision WARNING: v={current_speed_ms:.1f} m/s exceeds v_warn={v_warn:.1f} m/s",
                details={"speed_ms": current_speed_ms, "v_warn": v_warn, "dist_m": dist_to_eoa},
            )
        elif current_speed_ms > v_ind and dist_to_eoa > 0:
            state = SupervisionState.INDICATION
        else:
            state = SupervisionState.NORMAL

        return SupervisionProfile(
            target_speed_ms=vt,
            distance_to_target_m=round(dist_to_eoa, 3),
            permitted_speed_ms=round(v_perm, 3),
            warning_speed_ms=round(v_warn, 3),
            intervention_speed_ms=round(v_int, 3),
            indication_speed_ms=round(v_ind, 3),
            supervision_state=state,
            emergency_target_distance_m=round(dist_to_eoa + overlap, 3),
        )

    def create_braking_target(
        self,
        train_id: str,
        braking_category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
    ) -> BrakingTarget:
        """P06-ETCS-TGT: Convert active ETCS L2 MA to a P04 BrakingTarget."""
        ma = self.get_active_authority(train_id)
        if not ma:
            raise MovementAuthorityError(f"Train '{train_id}' has no active Movement Authority.")
        return BrakingProtectionEngine.create_braking_target_from_authority(
            ma=ma,
            braking_category=braking_category,
            margin_m=self.config.default_overlap_m,
        )

    def validate_stopping_feasibility(
        self,
        train_id: str,
        current_speed_ms: float,
        current_position_m: float,
        braking_model: BrakingModel,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
    ) -> bool:
        """P06-ETCS-INT: Verify available distance to EoA is sufficient for safe stopping."""
        ma = self.get_active_authority(train_id)
        if not ma:
            raise MovementAuthorityError(f"Train '{train_id}' has no active Movement Authority.")
        return BrakingProtectionEngine.validate_stopping_feasibility(
            current_speed_ms=current_speed_ms,
            current_position_m=current_position_m,
            end_of_authority_m=ma.end_of_authority,
            target_speed_ms=ma.target_speed_ms,
            braking_model=braking_model,
            category=category,
            include_delays=True,
        )

    def get_event_log(self) -> List[SignallingEvent]:
        events = []
        events.extend(self.event_log)
        events.extend(self.rbc.event_log)
        return sorted(events, key=lambda e: (e.timestamp_s, e.sequence_id))
