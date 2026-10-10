"""Data models, enums, and result contracts for Railway Capacity and UIC 406-Inspired Assessment.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Union

from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory


class CapacityType(str, Enum):
    """P10-TYP-001 to P10-TYP-005: Theoretical, planning, and operational capacity definitions."""

    THEORETICAL_HOMOGENEOUS = "THEORETICAL_HOMOGENEOUS"
    THEORETICAL_MIXED_PATTERN = "THEORETICAL_MIXED_PATTERN"
    PLANNING_ADDITIVE_MARGIN = "PLANNING_ADDITIVE_MARGIN"
    PLANNING_UTILIZATION = "PLANNING_UTILIZATION"
    ACHIEVED_OPERATIONAL_THROUGHPUT = "ACHIEVED_OPERATIONAL_THROUGHPUT"
    SUSTAINABLE_OPERATIONAL_CAPACITY = "SUSTAINABLE_OPERATIONAL_CAPACITY"
    UIC406_CAPACITY_CONSUMPTION = "UIC406_CAPACITY_CONSUMPTION"


class PlanningMarginMethod(str, Enum):
    """P10-PLN-001: Authorized planning margin calculation methods."""

    NONE = "NONE"
    ADDITIVE_HEADWAY_MARGIN = "ADDITIVE_HEADWAY_MARGIN"
    TARGET_UTILIZATION = "TARGET_UTILIZATION"
    BUFFER_TIME_RATIO = "BUFFER_TIME_RATIO"


class OperationalStabilityStatus(str, Enum):
    """P10-SUS-001: Classification of operational stability and queue sustainability."""

    STABLE = "STABLE"
    METASTABLE = "METASTABLE"
    UNSTABLE = "UNSTABLE"
    COLLAPSED = "COLLAPSED"


class BottleneckCategory(str, Enum):
    """P10-BNK-002: Controlling resource category identifying operational bottlenecks."""

    SIGNALLING_BLOCK = "SIGNALLING_BLOCK"
    STATION_PLATFORM = "STATION_PLATFORM"
    RESIDUAL_REAR_OCCUPATION = "RESIDUAL_REAR_OCCUPATION"
    JUNCTION_MERGE = "JUNCTION_MERGE"
    JUNCTION_CROSSOVER = "JUNCTION_CROSSOVER"
    JUNCTION_CONFLICT = "JUNCTION_CONFLICT"
    INTERLOCKING_ROUTE = "INTERLOCKING_ROUTE"
    TVS_SECTION = "TVS_SECTION"
    TVS_RESTRICTION = "TVS_RESTRICTION"
    SHARED_TVS_GROUP = "SHARED_TVS_GROUP"
    WHOLE_TUNNEL = "WHOLE_TUNNEL"
    DISPATCH_ORIGIN = "DISPATCH_ORIGIN"
    GRADIENT_SPEED = "GRADIENT_SPEED"


@dataclass(frozen=True)
class MeasurementWindow:
    """P10-PER-001 to P10-PER-005: Observation window for operational throughput."""

    warm_up_s: float = 0.0
    measurement_duration_s: float = 3600.0
    cool_down_s: float = 0.0
    screenline_id: Optional[str] = None
    start_time_s: Optional[float] = None
    end_time_s: Optional[float] = None
    warmup_duration_s: Optional[float] = None
    cooldown_duration_s: Optional[float] = None

    @property
    def window_start_s(self) -> float:
        """Start of measurement observation period excluding warm-up."""
        if self.start_time_s is not None:
            return self.start_time_s
        return self.warm_up_s

    @property
    def window_end_s(self) -> float:
        """End of measurement observation period."""
        if self.end_time_s is not None:
            return self.end_time_s
        return self.window_start_s + self.measurement_duration_s

    @property
    def duration_s(self) -> float:
        return self.window_end_s - self.window_start_s

    @property
    def total_simulation_duration_s(self) -> float:
        """Total required simulation duration including warm-up, measurement, and cool-down."""
        cd = self.cooldown_duration_s if self.cooldown_duration_s is not None else self.cool_down_s
        return self.window_end_s + cd

    def is_in_measurement_window(self, timestamp_s: float) -> bool:
        """Determine if a timestamp falls within the measurement observation period [start, end)."""
        return self.window_start_s <= timestamp_s < self.window_end_s


@dataclass
class StabilityEvaluation:
    """P10-SUS-002 to P10-SUS-006: Diagnostic metrics for operational stability."""

    run_id: str = "RUN_001"
    status: OperationalStabilityStatus = OperationalStabilityStatus.STABLE
    is_sustainable: bool = True
    tested_demand_rate_tph: float = 0.0
    tested_interval_s: float = 0.0
    total_requested: int = 0
    total_completed: int = 0
    completion_ratio: float = 1.0
    max_observed_queue: int = 0
    max_queue_length: int = 0
    final_queue_length: int = 0
    queue_growth_rate: float = 0.0
    average_delay_s: float = 0.0
    max_delay_s: float = 0.0
    delay_growth_slope: float = 0.0
    delay_growth_slope_s_per_train: float = 0.0
    secondary_to_primary_ratio: float = 0.0
    deadlock_detected: bool = False
    description: str = ""
    diagnostic_reasons: List[str] = field(default_factory=list)


@dataclass
class CapacityResult:
    """P10 Section 23: Authoritative canonical capacity result contract."""

    run_id: str
    analysis_id: str
    scenario_id: str
    capacity_type: CapacityType
    running_direction: RunningDirection
    analysis_section: str
    measurement_reference: str
    capacity_trains_per_hour: float
    headway_s: Optional[float] = None
    planning_margin_method: PlanningMarginMethod = PlanningMarginMethod.NONE
    planning_margin_value: float = 0.0
    measurement_period_s: float = 3600.0
    requested_trains: int = 0
    completed_trains: int = 0
    counted_trains: int = 0
    queue_stability: OperationalStabilityStatus = OperationalStabilityStatus.STABLE
    validation_status: str = "VALID"
    input_configuration_hash: str = ""
    measurement_window: Optional[MeasurementWindow] = None
    stability_evaluation: Optional[StabilityEvaluation] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize capacity result to dictionary representation."""
        return {
            "run_id": self.run_id,
            "analysis_id": self.analysis_id,
            "scenario_id": self.scenario_id,
            "capacity_type": self.capacity_type.value,
            "running_direction": self.running_direction.value,
            "analysis_section": self.analysis_section,
            "measurement_reference": self.measurement_reference,
            "capacity_trains_per_hour": round(self.capacity_trains_per_hour, 4),
            "headway_s": round(self.headway_s, 2) if self.headway_s is not None else None,
            "planning_margin_method": self.planning_margin_method.value,
            "planning_margin_value": round(self.planning_margin_value, 2),
            "measurement_period_s": round(self.measurement_period_s, 2),
            "requested_trains": self.requested_trains,
            "completed_trains": self.completed_trains,
            "counted_trains": self.counted_trains,
            "queue_stability": self.queue_stability.value,
            "validation_status": self.validation_status,
            "input_configuration_hash": self.input_configuration_hash,
            "details": self.details,
        }


@dataclass
class ResourceUtilizationMetric:
    """P10-UTIL-001 to P10-UTIL-007: Comprehensive resource utilization measurement."""

    resource_id: str
    resource_category: str = "TRACK_BLOCK"
    category: Union[ResourceCategory, str] = ResourceCategory.TRACK_BLOCK
    capacity: int = 1
    measurement_period_s: float = 3600.0
    measurement_duration_s: float = 3600.0
    physical_occupation_time_s: float = 0.0
    total_physical_occupation_time_s: float = 0.0
    physical_utilization_ratio: float = 0.0
    physical_utilization_percent: float = 0.0
    blocking_time_s: float = 0.0
    total_blocking_time_s: float = 0.0
    blocking_utilization_ratio: float = 0.0
    blocking_utilization_percent: float = 0.0
    forward_blocking_time_s: float = 0.0
    reverse_blocking_time_s: float = 0.0
    occupancy_count: int = 0
    train_occupancy_count: int = 0
    running_direction: Optional[RunningDirection] = None
    is_shared_group: bool = False
    is_critical: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BottleneckDiagnostic:
    """P10-BNK-001 to P10-BNK-006: Bottleneck identification and ranking."""

    resource_id: str
    category: BottleneckCategory = BottleneckCategory.SIGNALLING_BLOCK
    running_direction: RunningDirection = RunningDirection.FORWARD
    controlling_headway_s: float = 0.0
    limiting_headway_s: float = 0.0
    utilization_ratio: float = 0.0
    blocking_utilization_percent: float = 0.0
    average_queue_length: float = 0.0
    total_delay_caused_s: float = 0.0
    accumulated_delay_s: float = 0.0
    rank: int = 1
    is_tvs_constrained: bool = False
    description: str = ""
    diagnostic_explanation: str = ""
    recommended_mitigation: Optional[str] = None


@dataclass
class BottleneckMigrationRecord:
    """P10-MIG-001 to P10-MIG-005: Comparison of controlling bottleneck migration across scenarios."""

    baseline_scenario_id: str
    modified_scenario_id: str
    parameter_name: str = ""
    parameter_modified: str = ""
    parameter_baseline_value: Any = None
    parameter_modified_value: Any = None
    baseline_bottleneck_id: str = ""
    baseline_headway_s: float = 0.0
    modified_bottleneck_id: str = ""
    modified_headway_s: float = 0.0
    is_migrated: bool = False
    bottleneck_migrated: bool = False
    headway_improvement_s: float = 0.0
    baseline_capacity_tph: float = 0.0
    modified_capacity_tph: float = 0.0
    delta_capacity_tph: float = 0.0
    capacity_gain_tph: float = 0.0
    percentage_gain: float = 0.0
    diminishing_returns_reached: bool = False
    diminishing_returns_ratio: float = 1.0
    diagnostic_commentary: str = ""


@dataclass
class TimetableCompressionResult:
    """P10-UIC-008 to P10-UIC-016: Compressed timetable metrics and capacity consumption."""

    analysis_section: str = "DEFAULT_SECTION"
    corridor_id: str = "DEFAULT_CORRIDOR"
    running_direction: RunningDirection = RunningDirection.FORWARD
    analysis_duration_s: float = 3600.0
    train_count: int = 0
    original_span_s: float = 0.0
    original_duration_s: float = 0.0
    compressed_occupation_time_s: float = 0.0
    compressed_duration_s: float = 0.0
    supplementary_time_s: float = 0.0
    total_consumed_time_s: float = 0.0
    compression_ratio: float = 1.0
    capacity_consumption_ratio: float = 0.0
    train_order_preserved: bool = True
    minimum_dwells_preserved: bool = True
    headways_preserved: bool = True
    compressed_departure_times: Dict[str, float] = field(default_factory=dict)
    compressed_train_departures: Dict[str, float] = field(default_factory=dict)
    compressed_arrival_times: Dict[str, float] = field(default_factory=dict)
    uic_disclaimer: str = ""
    methodology_disclosure: str = (
        "UIC 406-inspired timetable compression removing permissible buffer times while "
        "preserving minimum headways, running times, station dwells, and interlocking constraints."
    )
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SensitivityPointResult:
    """A single evaluation point in a parameter sensitivity study."""

    parameter_name: str
    parameter_value: Any
    capacity_trains_per_hour: float
    headway_s: float
    limiting_bottleneck_id: str
    delta_capacity_vs_baseline: float = 0.0
    percentage_gain_vs_baseline: float = 0.0
    notes: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SensitivityStudyResult:
    """Full sensitivity study result across a parameter variation sweep."""

    study_id: str
    parameter_name: str
    baseline_value: Any
    baseline_capacity_tph: float
    baseline_headway_s: float
    baseline_bottleneck_id: str
    points: List[SensitivityPointResult] = field(default_factory=list)
    migration_records: List[BottleneckMigrationRecord] = field(default_factory=list)
    summary_commentary: str = ""
