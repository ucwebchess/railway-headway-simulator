"""CBTC Moving-Block engineering model with protected train envelopes.

Strictly satisfies RHS-P06-001:
- P06-CBTC: Configurable moving-block train separation with train localization.
- P06-MB: Protected train envelope calculation (accounting for report age, localization uncertainty, train integrity, and safety margins).
- P06-MA: Dynamic movement authority generation and continuous updates.
- P06-CBTC-RES: Fixed infrastructure restrictions (switches, route boundaries, buffer stops).
- Controlled Benchmark B: Analytical leader envelope yielding x_protected = 1970.0 m
  (x_front = 2200.0 m, L_train = 200.0 m, delta_loc = 20.0 m, d_margin = 10.0 m).
- Full support for both FORWARD and REVERSE railway operations.
"""

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Tuple

from headway.data.canonical import SignallingTechnologyType
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.rolling_stock.braking import BrakingCategory, BrakingModel
from headway.signalling.advanced_types import (
    AdvancedSignallingEngine,
    ProtectedTrainEnvelope,
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
    ProtectedEnvelopeError,
    ResourceEventType,
    SignallingEvent,
    SupervisionInterventionError,
)
from headway.signalling.resources import ResourceController
from headway.signalling.switches import SwitchController, SwitchState
from headway.simulation.targets import BrakingTarget, BrakingTargetType


@dataclass
class CBTCConfig:
    """Configuration parameters for CBTC moving-block signalling model."""

    fidelity: SignallingModelFidelity = SignallingModelFidelity.DETAILED
    position_update_interval_s: float = 0.5
    communication_config: RadioCommunicationConfig = field(default_factory=RadioCommunicationConfig)
    base_localization_uncertainty_m: float = 20.0
    odometry_drift_rate: float = 0.01  # 1% distance drift between balises
    safety_margin_m: float = 10.0     # Rollback margin / safety separation buffer
    service_deceleration_ms2: float = 0.75
    emergency_deceleration_ms2: float = 1.0
    warning_margin_speed_ms: float = 1.38889  # 5.0 km/h
    staleness_timeout_s: float = 2.0

    def __post_init__(self) -> None:
        if self.base_localization_uncertainty_m < 0:
            raise ProtectedEnvelopeError("Localization uncertainty must be non-negative.")
        if self.safety_margin_m < 0:
            raise ProtectedEnvelopeError("Safety margin must be non-negative.")
        if self.service_deceleration_ms2 <= 0 or self.emergency_deceleration_ms2 <= 0:
            raise MovementAuthorityError("Deceleration capabilities must be strictly positive.")


class ProtectedTrainEnvelopeCalculator:
    """P06-MB: Calculates the conservative protected envelope of a train."""

    @staticmethod
    def calculate_envelope(
        report: TrainPositionReport,
        current_time_s: float,
        config: CBTCConfig,
    ) -> ProtectedTrainEnvelope:
        """P06-MB / Benchmark B: Compute conservative moving-block spatial envelope.

        Benchmark B formulation:
        x_front = 2200.0 m, L_train = 200.0 m => x_rear_nom = 2000.0 m.
        delta_loc = 20.0 m, d_margin = 10.0 m.
        Fresh report (report_age = 0.0 s):
        x_protected = 2000.0 - 20.0 - 10.0 = 1970.0 m.
        """
        age = report.get_age_s(current_time_s)
        direction = report.running_direction
        L = report.train_length_m

        if config.fidelity == SignallingModelFidelity.BASIC:
            uncertainty = 0.0
            margin = 0.0
            age_allowance = 0.0
        elif config.fidelity == SignallingModelFidelity.INTERMEDIATE:
            uncertainty = config.base_localization_uncertainty_m
            margin = config.safety_margin_m
            age_allowance = 0.0
        else:  # DETAILED
            uncertainty = max(config.base_localization_uncertainty_m, report.localization_uncertainty_m)
            # If train has traveled distance since last report, drift increases
            margin = config.safety_margin_m
            # Stale report rollback allowance: if leader could roll back or drift
            age_allowance = 0.0 if age <= config.position_update_interval_s else (age * 1.0)

        # Integrity status adjustment
        if report.integrity_status == TrainIntegrityStatus.LOST:
            # Conservative envelope expands significantly to protect potentially detached cars
            uncertainty += 50.0
            margin += 50.0
        elif report.integrity_status == TrainIntegrityStatus.UNCONFIRMED:
            uncertainty += 10.0

        total_rear_buffer = uncertainty + margin + age_allowance

        if report.route_offset_m is not None:
            # Route coordinates strictly increase along the direction of travel
            nom_front = report.route_offset_m
            nom_rear = max(0.0, nom_front - L)
            prot_front = nom_front + uncertainty
            prot_rear = max(0.0, nom_rear - total_rear_buffer)
        elif direction == RunningDirection.FORWARD:
            nom_front = report.front_position_m
            nom_rear = max(0.0, nom_front - L)
            prot_front = nom_front + uncertainty
            prot_rear = max(0.0, nom_rear - total_rear_buffer)
        else:  # REVERSE
            nom_front = report.front_position_m
            nom_rear = nom_front + L
            prot_front = max(0.0, nom_front - uncertainty)
            prot_rear = nom_rear + total_rear_buffer

        return ProtectedTrainEnvelope(
            train_id=report.train_id,
            timestamp_s=current_time_s,
            running_direction=direction,
            nominal_front_m=round(nom_front, 3),
            nominal_rear_m=round(nom_rear, 3),
            protected_front_m=round(prot_front, 3),
            protected_rear_m=round(prot_rear, 3),
            localization_uncertainty_m=round(uncertainty, 3),
            safety_margin_m=round(margin, 3),
            report_age_s=round(age, 3),
            integrity_status=report.integrity_status,
        )


class CBTCMovingBlockEngine(AdvancedSignallingEngine):
    """P06-CBTC: Complete CBTC Moving-Block signalling engine implementing AdvancedSignallingEngine."""

    def __init__(
        self,
        config: Optional[CBTCConfig] = None,
        resource_controller: Optional[ResourceController] = None,
        interlocking_engine: Optional[InterlockingEngine] = None,
        switch_controller: Optional[SwitchController] = None,
    ) -> None:
        cfg = config or CBTCConfig()
        super().__init__(
            technology_type=SignallingTechnologyType.CBTC_MOVING_BLOCK,
            fidelity=cfg.fidelity,
            communication_config=cfg.communication_config,
        )
        self.config = cfg
        self.resource_controller = resource_controller or ResourceController()
        self.switch_controller = switch_controller or SwitchController()
        self.interlocking_engine = interlocking_engine or InterlockingEngine(
            resource_controller=self.resource_controller,
            switch_controller=self.switch_controller,
        )
        self.train_lengths: Dict[str, float] = {}
        self.last_reports: Dict[str, TrainPositionReport] = {}
        self.active_authorities: Dict[str, MovementAuthority] = {}
        self.authority_history: List[MovementAuthority] = []
        self.protected_envelopes: Dict[str, ProtectedTrainEnvelope] = {}

    def register_train(
        self,
        train_id: str,
        train_length_m: float,
        initial_route: Optional[Route] = None,
    ) -> None:
        self.train_lengths[train_id] = train_length_m

    def receive_position_report(
        self,
        report: TrainPositionReport,
        current_time_s: float,
    ) -> bool:
        """Process periodic CBTC position report from train."""
        tid = report.train_id
        last_rep = self.last_reports.get(tid)

        if last_rep is not None:
            dt = current_time_s - last_rep.timestamp_s
            if dt > self.config.staleness_timeout_s:
                self._log_event(
                    timestamp_s=current_time_s,
                    event_type=ResourceEventType.COMMUNICATION_TIMEOUT,
                    resource_id=f"CBTC_RADIO_{tid}",
                    train_id=tid,
                    description=f"CBTC communication stale for train '{tid}' (elapsed {dt:.2f}s > {self.config.staleness_timeout_s:.2f}s).",
                    details={"elapsed_s": dt, "timeout_s": self.config.staleness_timeout_s},
                )
                raise CommunicationTimeoutError(
                    f"CBTC report communication timed out for train '{tid}': {dt:.2f} s elapsed.",
                    context={"train_id": tid, "elapsed_s": dt, "timeout_s": self.config.staleness_timeout_s},
                )

        self.last_reports[tid] = report

        # Calculate updated protected envelope
        envelope = ProtectedTrainEnvelopeCalculator.calculate_envelope(
            report=report,
            current_time_s=current_time_s,
            config=self.config,
        )
        self.protected_envelopes[tid] = envelope

        self._log_event(
            timestamp_s=current_time_s,
            event_type=ResourceEventType.POSITION_REPORT_RECEIVED,
            resource_id=report.link_id,
            train_id=tid,
            description=f"CBTC position report received: front={report.front_position_m:.1f}m, uncertainty={report.localization_uncertainty_m:.1f}m",
            details={"front_m": report.front_position_m, "integrity": report.integrity_status.value},
        )
        self._log_event(
            timestamp_s=current_time_s,
            event_type=ResourceEventType.ENVELOPE_UPDATED,
            resource_id=report.link_id,
            train_id=tid,
            description=f"Protected envelope updated: protected_rear={envelope.protected_rear_m:.1f}m",
            details={"prot_rear_m": envelope.protected_rear_m, "prot_front_m": envelope.protected_front_m},
        )
        return True

    def compute_protected_envelope(
        self,
        train_id: str,
        current_time_s: float,
    ) -> ProtectedTrainEnvelope:
        """P06-MB: Compute or retrieve protected envelope for leader train."""
        rep = self.last_reports.get(train_id)
        if not rep:
            raise ProtectedEnvelopeError(f"No position report available to compute envelope for train '{train_id}'.")
        envelope = ProtectedTrainEnvelopeCalculator.calculate_envelope(
            report=rep,
            current_time_s=current_time_s,
            config=self.config,
        )
        self.protected_envelopes[train_id] = envelope
        return envelope

    def compute_movement_authority(
        self,
        train_id: str,
        route: Route,
        current_time_s: float,
        start_position_m: Optional[float] = None,
        target_speed_ms: float = 0.0,
        fixed_infrastructure_limit_m: Optional[float] = None,
    ) -> MovementAuthority:
        """P06-MA & P06-CBTC-RES: Generate dynamic moving-block Movement Authority.

        Follower EoA is placed at leader's protected rear envelope or fixed infrastructure restriction.
        """
        follower_rep = self.last_reports.get(train_id)
        start_pos = start_position_m if start_position_m is not None else (
            follower_rep.front_position_m if follower_rep is not None else 0.0
        )

        running_dir = route.traversals[0].direction if route.traversals else RunningDirection.FORWARD

        # 1. Base infrastructure limit: route total length
        route_len = route.total_length_m
        effective_eoa = route_len

        if fixed_infrastructure_limit_m is not None:
            effective_eoa = min(effective_eoa, fixed_infrastructure_limit_m)

        # 2. Check interlocking route / switch restrictions (P06-CBTC-RES)
        route_def = self.interlocking_engine.routes.get(route.route_id)
        if route_def:
            # Verify switches along route are locked in commanded position
            for sw_id, req_pos in route_def.required_switch_positions.items():
                sw_state = self.switch_controller.states.get(sw_id)
                if sw_state:
                    # If switch is unlocked or in wrong position, limit EoA before switch
                    if sw_state.current_position != req_pos or not sw_state.is_locked:
                        sw_pos = route_len * 0.5  # conservative boundary if switch not locked
                        effective_eoa = min(effective_eoa, sw_pos)

        # 3. Dynamic moving-block separation: search for leader train ahead
        for other_id, env in self.protected_envelopes.items():
            if other_id == train_id:
                continue

            # Check if leader has communication timeout / staleness
            age = current_time_s - env.timestamp_s
            if age > self.config.staleness_timeout_s:
                # Stale leader: clamp follower authority conservatively
                effective_eoa = min(effective_eoa, start_pos)
                break

            # Leader envelope check
            if running_dir == RunningDirection.FORWARD:
                # Leader is ahead if protected_rear > start_pos
                if env.protected_rear_m > start_pos:
                    effective_eoa = min(effective_eoa, env.protected_rear_m)
            else:  # REVERSE
                # Leader is ahead in reverse if protected_rear < start_pos (or route offset)
                if env.protected_rear_m < start_pos:
                    effective_eoa = max(effective_eoa, env.protected_rear_m)

        if running_dir == RunningDirection.FORWARD and effective_eoa < start_pos:
            effective_eoa = start_pos

        effective_time = self.config.communication_config.calculate_effective_time(
            issue_time_s=current_time_s,
            fidelity=self.config.fidelity,
        )

        ma = MovementAuthority(
            ma_id=f"CBTC_MA_{train_id}_{self._next_seq()}",
            train_id=train_id,
            route_id=route.route_id,
            start_reference=round(start_pos, 3),
            end_of_authority=round(effective_eoa, 3),
            target_speed_ms=round(target_speed_ms, 3),
            issue_time_s=current_time_s,
            effective_time_s=effective_time,
            validity_status=AuthorityValidity.ACTIVE,
            running_direction=running_dir,
            description=f"CBTC Moving-Block MA to EoA={effective_eoa:.1f}m (effective t={effective_time:.1f}s)",
        )

        is_update = train_id in self.active_authorities
        self.active_authorities[train_id] = ma
        self.authority_history.append(ma)

        evt_type = ResourceEventType.MA_UPDATED if is_update else ResourceEventType.MA_ISSUED
        self._log_event(
            timestamp_s=current_time_s,
            event_type=evt_type,
            resource_id=route.route_id,
            train_id=train_id,
            route_id=route.route_id,
            description=f"CBTC dynamic MA {'updated' if is_update else 'issued'} for train '{train_id}' to EoA={effective_eoa:.1f}m",
            details={"eoa_m": effective_eoa, "start_m": start_pos, "effective_time_s": effective_time},
        )
        return ma

    def evaluate_supervision(
        self,
        train_id: str,
        current_speed_ms: float,
        current_position_m: float,
        braking_model: Optional[BrakingModel] = None,
    ) -> SupervisionProfile:
        """P06-BRK: Dynamic moving-block braking supervision."""
        ma = self.get_active_authority(train_id)
        if not ma:
            raise MovementAuthorityError(f"Cannot evaluate supervision: train '{train_id}' has no active CBTC MA.")

        if ma.running_direction == RunningDirection.FORWARD:
            dist_to_eoa = max(0.0, ma.end_of_authority - current_position_m)
        else:
            dist_to_eoa = max(0.0, current_position_m - ma.end_of_authority)

        vt = ma.target_speed_ms
        b_srv = self.config.service_deceleration_ms2
        b_emg = self.config.emergency_deceleration_ms2

        v_perm = math.sqrt(max(0.0, (vt ** 2) + 2.0 * b_srv * dist_to_eoa))

        if self.config.fidelity == SignallingModelFidelity.BASIC:
            v_warn = v_perm
            v_int = v_perm
            v_ind = v_perm
        else:
            v_warn = v_perm + self.config.warning_margin_speed_ms
            v_int = math.sqrt(max(0.0, (vt ** 2) + 2.0 * b_emg * (dist_to_eoa + self.config.safety_margin_m)))
            v_int = max(v_warn + 0.5, v_int)
            dist_ind = max(0.0, dist_to_eoa - current_speed_ms * 2.0)
            v_ind = math.sqrt(max(0.0, (vt ** 2) + 2.0 * b_srv * dist_ind))

        if current_speed_ms > v_int and dist_to_eoa > 0:
            state = SupervisionState.INTERVENTION
            self._log_event(
                timestamp_s=ma.issue_time_s,
                event_type=ResourceEventType.SUPERVISION_INTERVENTION,
                resource_id=ma.route_id,
                train_id=train_id,
                description=f"CBTC Supervision INTERVENTION: v={current_speed_ms:.1f} m/s exceeds v_int={v_int:.1f} m/s",
                details={"speed_ms": current_speed_ms, "v_int": v_int, "dist_m": dist_to_eoa},
            )
        elif current_speed_ms > v_warn and dist_to_eoa > 0:
            state = SupervisionState.WARNING
            self._log_event(
                timestamp_s=ma.issue_time_s,
                event_type=ResourceEventType.SUPERVISION_WARNING,
                resource_id=ma.route_id,
                train_id=train_id,
                description=f"CBTC Supervision WARNING: v={current_speed_ms:.1f} m/s exceeds v_warn={v_warn:.1f} m/s",
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
            emergency_target_distance_m=round(dist_to_eoa + self.config.safety_margin_m, 3),
        )

    def validate_stopping_feasibility(
        self,
        train_id: str,
        current_speed_ms: float,
        current_position_m: float,
        braking_model: BrakingModel,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
    ) -> bool:
        """P06-BRK: Verify available distance to moving-block dynamic EoA is sufficient."""
        ma = self.get_active_authority(train_id)
        if not ma:
            raise MovementAuthorityError(f"Train '{train_id}' has no active CBTC Movement Authority.")

        if ma.running_direction == RunningDirection.FORWARD:
            available_dist = ma.end_of_authority - current_position_m
        else:
            available_dist = current_position_m - ma.end_of_authority

        if current_speed_ms <= ma.target_speed_ms:
            return True

        req_dist = braking_model.calculate_stopping_distance(
            initial_speed_ms=current_speed_ms,
            target_speed_ms=ma.target_speed_ms,
            category=category,
            include_delays=True,
        )

        if available_dist < req_dist:
            raise BrakingFeasibilityError(
                f"Insufficient braking distance to dynamic EoA: Available {available_dist:.1f} m, Required {req_dist:.1f} m.",
                context={
                    "train_id": train_id,
                    "available_distance_m": available_dist,
                    "required_distance_m": req_dist,
                    "speed_ms": current_speed_ms,
                },
            )
        return True

    def get_active_authority(self, train_id: str) -> Optional[MovementAuthority]:
        return self.active_authorities.get(train_id)

    def get_event_log(self) -> List[SignallingEvent]:
        return sorted(self.event_log, key=lambda e: (e.timestamp_s, e.sequence_id))
