"""Advanced signalling architecture, interfaces, and shared data contracts.

Strictly satisfies RHS-P06-001:
- P06-ARCH-001: Advanced signalling base interface.
- P06-ARCH-002: Common Movement Authority contract.
- P06-ARCH-003: Train Position Report contract with odometry uncertainty and integrity.
- P06-ARCH-004: Model fidelity classification (BASIC, INTERMEDIATE, DETAILED).
- P06-ARCH-005: Standardized advanced signalling event logging.
- P06-ARCH-006: Bidirectional invariance across FORWARD and REVERSE running.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional

from headway.data.canonical import SignallingTechnologyType
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.signalling.authority import MovementAuthority
from headway.signalling.resource_types import (
    AdvancedSignallingError,
    PositionReportError,
    ResourceEventType,
    SignallingEvent,
)


class SignallingModelFidelity(str, Enum):
    """P06-ARCH-004: Engineering model fidelity classification."""

    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    DETAILED = "DETAILED"


class TrainIntegrityStatus(str, Enum):
    """P06-ARCH-003: On-board train integrity monitoring status."""

    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"
    LOST = "LOST"


class SupervisionState(str, Enum):
    """Braking curve supervision operational state."""

    NORMAL = "NORMAL"
    INDICATION = "INDICATION"
    WARNING = "WARNING"
    INTERVENTION = "INTERVENTION"


@dataclass(frozen=True)
class RadioCommunicationConfig:
    """P06-COM: Radio communication latency and timeout configuration."""

    uplink_latency_s: float = 0.4
    processing_delay_s: float = 0.2
    downlink_latency_s: float = 0.4
    timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if self.uplink_latency_s < 0 or self.processing_delay_s < 0 or self.downlink_latency_s < 0:
            raise AdvancedSignallingError("Communication latencies must be non-negative.")
        if self.timeout_s <= 0:
            raise AdvancedSignallingError("Communication timeout must be positive.")

    @property
    def total_latency_s(self) -> float:
        """Total round-trip / end-to-end communication latency: t_comm = t_up + t_proc + t_down."""
        return round(self.uplink_latency_s + self.processing_delay_s + self.downlink_latency_s, 6)

    def calculate_effective_time(
        self,
        issue_time_s: float,
        fidelity: SignallingModelFidelity = SignallingModelFidelity.DETAILED,
    ) -> float:
        """P06-B008 / Benchmark C: t_effective = t_issue + t_comm (or t_issue in BASIC)."""
        if fidelity == SignallingModelFidelity.BASIC:
            return round(issue_time_s, 3)
        return round(issue_time_s + self.total_latency_s, 3)


@dataclass(frozen=True)
class TrainPositionReport:
    """P06-ARCH-003: Periodic train odometry and position report."""

    train_id: str
    timestamp_s: float
    link_id: str
    front_position_m: float
    speed_ms: float
    running_direction: RunningDirection = RunningDirection.FORWARD
    train_length_m: float = 200.0
    route_id: Optional[str] = None
    route_offset_m: Optional[float] = None
    localization_uncertainty_m: float = 0.0
    integrity_status: TrainIntegrityStatus = TrainIntegrityStatus.CONFIRMED

    def __post_init__(self) -> None:
        if self.front_position_m < 0:
            raise PositionReportError(
                f"Front position must be non-negative (got {self.front_position_m} m).",
                context={"train_id": self.train_id, "front_m": self.front_position_m},
            )
        if self.speed_ms < 0:
            raise PositionReportError(
                f"Train speed must be non-negative (got {self.speed_ms} m/s).",
                context={"train_id": self.train_id, "speed_ms": self.speed_ms},
            )
        if self.train_length_m <= 0:
            raise PositionReportError(
                f"Train length must be positive (got {self.train_length_m} m).",
                context={"train_id": self.train_id, "length_m": self.train_length_m},
            )
        if self.localization_uncertainty_m < 0:
            raise PositionReportError(
                f"Localization uncertainty must be non-negative (got {self.localization_uncertainty_m} m).",
                context={"train_id": self.train_id, "uncertainty_m": self.localization_uncertainty_m},
            )

    @property
    def nominal_rear_position_m(self) -> float:
        """Nominal rear position in local link or route coordinate."""
        if self.route_offset_m is not None:
            # Route coordinates strictly increase along the direction of travel
            return max(0.0, round(self.route_offset_m - self.train_length_m, 3))
        if self.running_direction == RunningDirection.FORWARD:
            return max(0.0, round(self.front_position_m - self.train_length_m, 3))
        else:
            return round(self.front_position_m + self.train_length_m, 3)

    def get_age_s(self, current_time_s: float) -> float:
        """Calculate report age in seconds."""
        if current_time_s < self.timestamp_s:
            raise PositionReportError(
                f"Current simulation time ({current_time_s:.2f} s) cannot precede report timestamp ({self.timestamp_s:.2f} s)."
            )
        return round(current_time_s - self.timestamp_s, 6)


@dataclass(frozen=True)
class SupervisionProfile:
    """Instantaneous supervision curves and state."""

    target_speed_ms: float
    distance_to_target_m: float
    permitted_speed_ms: float
    warning_speed_ms: float
    intervention_speed_ms: float
    indication_speed_ms: float
    supervision_state: SupervisionState
    emergency_target_distance_m: float


@dataclass(frozen=True)
class ProtectedTrainEnvelope:
    """P06-MB: Conservative moving-block train spatial envelope."""

    train_id: str
    timestamp_s: float
    running_direction: RunningDirection
    nominal_front_m: float
    nominal_rear_m: float
    protected_front_m: float
    protected_rear_m: float
    localization_uncertainty_m: float
    safety_margin_m: float
    report_age_s: float
    integrity_status: TrainIntegrityStatus

    @property
    def total_protected_length_m(self) -> float:
        """Full length of the conservative safety envelope."""
        return round(abs(self.protected_front_m - self.protected_rear_m), 3)


class AdvancedSignallingEngine(ABC):
    """P06-ARCH-001: Abstract foundation for advanced signalling technologies."""

    def __init__(
        self,
        technology_type: SignallingTechnologyType,
        fidelity: SignallingModelFidelity = SignallingModelFidelity.DETAILED,
        communication_config: Optional[RadioCommunicationConfig] = None,
    ) -> None:
        self.technology_type = technology_type
        self.fidelity = fidelity
        self.communication_config = communication_config or RadioCommunicationConfig()
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

    @abstractmethod
    def register_train(
        self,
        train_id: str,
        train_length_m: float,
        initial_route: Optional[Route] = None,
    ) -> None:
        """Register a train with the signalling system."""
        pass

    @abstractmethod
    def receive_position_report(
        self,
        report: TrainPositionReport,
        current_time_s: float,
    ) -> bool:
        """Process train position update and verify communication health."""
        pass

    @abstractmethod
    def compute_movement_authority(
        self,
        train_id: str,
        route: Route,
        current_time_s: float,
        start_position_m: Optional[float] = None,
        target_speed_ms: float = 0.0,
    ) -> MovementAuthority:
        """Compute the updated Movement Authority for a train."""
        pass

    @abstractmethod
    def evaluate_supervision(
        self,
        train_id: str,
        current_speed_ms: float,
        current_position_m: float,
    ) -> SupervisionProfile:
        """Evaluate braking curves and supervision state."""
        pass

    @abstractmethod
    def get_active_authority(self, train_id: str) -> Optional[MovementAuthority]:
        """Retrieve current active movement authority for a train."""
        pass
