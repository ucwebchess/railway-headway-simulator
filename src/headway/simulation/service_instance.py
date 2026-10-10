"""Train service instance models and train generation subsystem.

Strictly satisfies RHS-P09-001 § 5 & § 6:
- P09-SVC-001 to P09-SVC-005: Service type configuration, unique TRAIN_ID, independent state,
  multiple train types, and independent running directions (FORWARD / REVERSE).
- P09-GEN-001 to P09-GEN-008: Generation modes (SINGLE, PAIRWISE, FIXED_INTERVAL,
  REPEATED_HOMOGENEOUS, REPEATED_MIXED, TIMETABLE), validation, and prevention of artificial physical overlap.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence

from headway.core.exceptions import OperationalSimulationError
from headway.data.canonical import StationStop
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.rolling_stock.braking import BrakingModel, create_braking_model
from headway.rolling_stock.force_balance import ForceBalanceEngine
from headway.rolling_stock.resistance import DistributedResistanceEngine
from headway.rolling_stock.traction import TractionModel, create_traction_model
from headway.rolling_stock.train import RollingStockParameters
from headway.simulation.events import BoundaryEvent
from headway.simulation.state import DynamicMode, OperationalState, TrainDynamicState
from headway.simulation.targets import BrakingTarget
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory


class TrainGenerationMode(str, Enum):
    """P09-GEN: Authorized train generation modes."""

    SINGLE = "SINGLE"
    PAIRWISE = "PAIRWISE"
    FIXED_INTERVAL = "FIXED_INTERVAL"
    REPEATED_HOMOGENEOUS = "REPEATED_HOMOGENEOUS"
    REPEATED_MIXED = "REPEATED_MIXED"
    TIMETABLE = "TIMETABLE"


@dataclass
class ServiceType:
    """P09-SVC-001: Operational service template referencing route and rolling stock."""

    service_id: str
    train_type_id: str
    params: RollingStockParameters
    route: Route
    stops: List[StationStop] = field(default_factory=list)
    priority: int = 1
    running_direction: RunningDirection = RunningDirection.FORWARD
    platform_preferences: Dict[str, str] = field(default_factory=dict)
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.priority < 1:
            raise OperationalSimulationError(
                f"Service priority must be >= 1 (got {self.priority}).",
                context={"service_id": self.service_id, "priority": self.priority},
            )
        if not self.route.traversals:
            raise OperationalSimulationError(
                f"Service '{self.service_id}' route contains no traversals.",
                context={"service_id": self.service_id},
            )


@dataclass
class TimetableEntry:
    """P09-GEN-006: Scheduled entry within a timetable."""

    train_id: str
    service_id: str
    scheduled_departure_s: float
    priority: int = 1
    primary_delay_s: float = 0.0
    platform_preferences: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.train_id:
            raise OperationalSimulationError("TimetableEntry requires non-empty train_id.")
        if self.scheduled_departure_s < 0.0 or not math.isfinite(self.scheduled_departure_s):
            raise OperationalSimulationError(
                f"Scheduled departure time must be finite and non-negative (got {self.scheduled_departure_s}).",
                context={"train_id": self.train_id, "scheduled_departure_s": self.scheduled_departure_s},
            )


@dataclass
class OperationalTimetable:
    """Timetable holding multiple ordered train departures."""

    timetable_id: str
    entries: List[TimetableEntry] = field(default_factory=list)


@dataclass
class TrainServiceInstance:
    """P09-SVC-002 & 003: Active microscopic train service instance.

    Maintains independent dynamic state, signalling targets, station stopping,
    and accumulated operational delay.
    """

    train_id: str
    service_id: str
    params: RollingStockParameters
    route: Route
    running_direction: RunningDirection
    requested_departure_time_s: float
    priority: int = 1
    stops: List[StationStop] = field(default_factory=list)
    platform_preferences: Dict[str, str] = field(default_factory=dict)
    primary_delay_s: float = 0.0

    # Operational Lifecycle Timestamps
    actual_departure_time_s: Optional[float] = None
    actual_completion_time_s: Optional[float] = None

    # Instantaneous Dynamic State
    current_position_m: float = 0.0
    current_speed_ms: float = 0.0
    current_acceleration_ms2: float = 0.0
    dynamic_mode: DynamicMode = DynamicMode.STOPPED
    operational_state: OperationalState = OperationalState.STANDSTILL

    # Station & Dwell State
    current_stop_index: int = 0
    is_dwelling: bool = False
    remaining_dwell_s: float = 0.0
    dwelling_station_id: Optional[str] = None
    assigned_platforms: Dict[str, str] = field(default_factory=dict)

    # Downstream Authority Limits
    current_eoa_m: float = 0.0
    active_target: Optional[BrakingTarget] = None

    # Waiting & Delay Attribution
    active_waiting_cause: Optional[str] = None
    waiting_start_time_s: Optional[float] = None
    accumulated_delay_by_cause: Dict[str, float] = field(default_factory=dict)
    secondary_delay_s: float = 0.0

    # Physical engines (instantiated on init)
    braking_model: BrakingModel = field(init=False)
    traction_model: TractionModel = field(init=False)
    resistance_engine: DistributedResistanceEngine = field(init=False)
    force_engine: ForceBalanceEngine = field(init=False)

    # Trajectory History & Audit Events
    trajectory_samples: List[TrajectorySample] = field(default_factory=list)
    events: List[BoundaryEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.train_id:
            raise OperationalSimulationError("TrainServiceInstance requires a non-empty train_id.")
        self.braking_model = create_braking_model(self.params)
        self.traction_model = create_traction_model(self.params)
        self.resistance_engine = DistributedResistanceEngine(self.params)
        self.force_engine = ForceBalanceEngine(self.params, self.traction_model)
        self.current_eoa_m = self.route.total_length_m

    @property
    def rear_position_m(self) -> float:
        """P09-MIC-005: Physical train-rear position along route."""
        return self.current_position_m - self.params.length_m

    @property
    def total_journey_time_s(self) -> Optional[float]:
        """P09-JT-002: Actual total journey duration if completed."""
        if self.actual_departure_time_s is not None and self.actual_completion_time_s is not None:
            return max(0.0, self.actual_completion_time_s - self.actual_departure_time_s)
        return None

    @property
    def departure_delay_s(self) -> Optional[float]:
        """P09-DEP-004: Departure delay (actual - requested)."""
        if self.actual_departure_time_s is not None:
            return max(0.0, self.actual_departure_time_s - self.requested_departure_time_s)
        return None

    @property
    def is_completed(self) -> bool:
        return self.operational_state == OperationalState.COMPLETED

    @property
    def is_running(self) -> bool:
        return self.operational_state in (OperationalState.RUNNING, OperationalState.STATION_DWELL)

    @property
    def is_waiting(self) -> bool:
        return self.active_waiting_cause is not None

    def record_delay(self, cause: str, duration_s: float) -> None:
        """P09-DLY-004: Accumulate delay duration under specified cause."""
        if duration_s <= 0.0:
            return
        self.accumulated_delay_by_cause[cause] = self.accumulated_delay_by_cause.get(cause, 0.0) + duration_s
        if cause != "PRIMARY_DISTURBANCE":
            self.secondary_delay_s += duration_s

    def build_trajectory(self) -> TrainTrajectory:
        """Package recorded samples and events into canonical TrainTrajectory."""
        traj = TrainTrajectory(
            train_id=self.train_id,
            train_type_id=self.params.train_type_id,
            route_id=self.route.route_id,
            running_direction=self.running_direction,
        )
        traj.samples = list(self.trajectory_samples)
        traj.events = list(self.events)
        return traj


class TrainGenerator:
    """P09-GEN: Generates validated train instances across all operational modes."""

    @staticmethod
    def create_instance(
        service_type: ServiceType,
        train_id: str,
        requested_departure_s: float,
        priority: Optional[int] = None,
        primary_delay_s: float = 0.0,
        platform_preferences: Optional[Dict[str, str]] = None,
    ) -> TrainServiceInstance:
        """Build a single validated TrainServiceInstance from ServiceType."""
        prio = priority if priority is not None else service_type.priority
        prefs = dict(service_type.platform_preferences)
        if platform_preferences:
            prefs.update(platform_preferences)

        return TrainServiceInstance(
            train_id=train_id,
            service_id=service_type.service_id,
            params=service_type.params,
            route=service_type.route,
            running_direction=service_type.running_direction,
            requested_departure_time_s=requested_departure_s,
            priority=prio,
            stops=list(service_type.stops),
            platform_preferences=prefs,
            primary_delay_s=primary_delay_s,
        )

    @classmethod
    def generate_single(
        cls,
        service_type: ServiceType,
        requested_departure_s: float = 0.0,
        train_id: Optional[str] = None,
        primary_delay_s: float = 0.0,
    ) -> List[TrainServiceInstance]:
        """P09-GEN-001: Generate single train instance."""
        tid = train_id or f"{service_type.service_id}_001"
        return [cls.create_instance(service_type, tid, requested_departure_s, primary_delay_s=primary_delay_s)]

    @classmethod
    def generate_pairwise(
        cls,
        leader_service: ServiceType,
        follower_service: ServiceType,
        interval_s: float,
        start_time_s: float = 0.0,
        leader_primary_delay_s: float = 0.0,
        follower_primary_delay_s: float = 0.0,
    ) -> List[TrainServiceInstance]:
        """P09-GEN-002: Generate leader-follower pair."""
        if interval_s <= 0.0:
            raise OperationalSimulationError("Pairwise generation requires interval_s > 0.")
        leader = cls.create_instance(
            leader_service,
            train_id=f"{leader_service.service_id}_LEAD",
            requested_departure_s=start_time_s,
            primary_delay_s=leader_primary_delay_s,
        )
        follower = cls.create_instance(
            follower_service,
            train_id=f"{follower_service.service_id}_FOLL",
            requested_departure_s=start_time_s + interval_s,
            primary_delay_s=follower_primary_delay_s,
        )
        return [leader, follower]

    @classmethod
    def generate_fixed_interval(
        cls,
        service_type: ServiceType,
        interval_s: float,
        count: int,
        start_time_s: float = 0.0,
        train_id_prefix: Optional[str] = None,
    ) -> List[TrainServiceInstance]:
        """P09-GEN-003 & Benchmark A: Generate N trains at constant scheduled departure interval t_n = t_0 + n*H."""
        if count < 1:
            raise OperationalSimulationError("Fixed interval train generation requires count >= 1.")
        if interval_s <= 0.0:
            raise OperationalSimulationError("Fixed interval must be positive.")

        pfx = train_id_prefix or service_type.service_id
        instances = []
        for n in range(count):
            t_dep = start_time_s + n * interval_s
            tid = f"{pfx}_{n + 1:03d}"
            instances.append(cls.create_instance(service_type, tid, t_dep))
        return instances

    @classmethod
    def generate_repeated_homogeneous(
        cls,
        service_type: ServiceType,
        count: int,
        interval_s: float,
        start_time_s: float = 0.0,
    ) -> List[TrainServiceInstance]:
        """P09-GEN-004: Repeated identical train services."""
        return cls.generate_fixed_interval(service_type, interval_s, count, start_time_s)

    @classmethod
    def generate_repeated_mixed(
        cls,
        service_sequence: Sequence[ServiceType],
        repeat_cycles: int,
        interval_s: float,
        start_time_s: float = 0.0,
    ) -> List[TrainServiceInstance]:
        """P09-GEN-005: Repeated cycle of heterogeneous service types."""
        if not service_sequence:
            raise OperationalSimulationError("Mixed pattern requires at least one service type.")
        if repeat_cycles < 1:
            raise OperationalSimulationError("repeat_cycles must be >= 1.")

        instances = []
        curr_t = start_time_s
        train_num = 1
        for _ in range(repeat_cycles):
            for st in service_sequence:
                tid = f"{st.service_id}_{train_num:03d}"
                instances.append(cls.create_instance(st, tid, curr_t))
                curr_t += interval_s
                train_num += 1
        return instances

    @classmethod
    def generate_from_timetable(
        cls,
        timetable: OperationalTimetable,
        service_catalog: Dict[str, ServiceType],
    ) -> List[TrainServiceInstance]:
        """P09-GEN-006: Generate train instances from timetable."""
        instances = []
        for entry in timetable.entries:
            st = service_catalog.get(entry.service_id)
            if not st:
                raise OperationalSimulationError(
                    f"Unknown service_id '{entry.service_id}' in timetable entry '{entry.train_id}'.",
                    context={"service_id": entry.service_id, "train_id": entry.train_id},
                )
            instances.append(
                cls.create_instance(
                    service_type=st,
                    train_id=entry.train_id,
                    requested_departure_s=entry.scheduled_departure_s,
                    priority=entry.priority,
                    primary_delay_s=entry.primary_delay_s,
                    platform_preferences=entry.platform_preferences,
                )
            )
        return instances
