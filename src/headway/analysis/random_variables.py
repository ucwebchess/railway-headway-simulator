"""Stochastic variable contracts, sampling scopes, and disruption definitions.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- P11-VAR-001 to P11-VAR-005: Stochastic variable contracts, bounds, SI units, and validation
- P11-SCOPE-001 to P11-SCOPE-003: Sampling scopes (per replication, train, stop, event, window)
- P11-DIS-001 to P11-DIS-003: Temporary operational disruptions definition
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Union


class TargetObjectType(str, Enum):
    """P11-VAR-001: Authorized engineering target object categories for stochastic variability."""

    STATION_DWELL = "STATION_DWELL"
    DEPARTURE_READINESS = "DEPARTURE_READINESS"
    TRACTION_UTILIZATION = "TRACTION_UTILIZATION"
    BRAKING_UTILIZATION = "BRAKING_UTILIZATION"
    DRIVER_REACTION_TIME = "DRIVER_REACTION_TIME"
    TARGET_SPEED_ADHERENCE = "TARGET_SPEED_ADHERENCE"
    ROUTE_SETUP_TIME = "ROUTE_SETUP_TIME"
    DETECTION_PROCESSING_TIME = "DETECTION_PROCESSING_TIME"
    RBC_COMMUNICATION_LATENCY = "RBC_COMMUNICATION_LATENCY"
    CBTC_COMMUNICATION_LATENCY = "CBTC_COMMUNICATION_LATENCY"
    TVS_ENTRY_AUTHORIZATION_DELAY = "TVS_ENTRY_AUTHORIZATION_DELAY"
    TVS_RELEASE_DELAY = "TVS_RELEASE_DELAY"
    TEMPORARY_SPEED_RESTRICTION = "TEMPORARY_SPEED_RESTRICTION"


class SamplingScope(str, Enum):
    """P11-SCOPE: Granularity at which stochastic variables are sampled."""

    PER_REPLICATION = "PER_REPLICATION"
    PER_TRAIN = "PER_TRAIN"
    PER_STATION_STOP = "PER_STATION_STOP"
    PER_RESOURCE_EVENT = "PER_RESOURCE_EVENT"
    PER_COMMUNICATION_EVENT = "PER_COMMUNICATION_EVENT"
    PER_TIME_WINDOW = "PER_TIME_WINDOW"


class DistributionType(str, Enum):
    """P11-DIST: Supported probability distributions for parameter sampling."""

    NORMAL = "NORMAL"
    TRUNCATED_NORMAL = "TRUNCATED_NORMAL"
    LOGNORMAL = "LOGNORMAL"
    UNIFORM = "UNIFORM"
    TRIANGULAR = "TRIANGULAR"
    EXPONENTIAL = "EXPONENTIAL"
    EMPIRICAL_DISCRETE = "EMPIRICAL_DISCRETE"
    EMPIRICAL_CONTINUOUS = "EMPIRICAL_CONTINUOUS"


class DisruptionType(str, Enum):
    """P11-DIS-001: Supported operational disruption event categories."""

    TEMPORARY_SPEED_RESTRICTION = "TEMPORARY_SPEED_RESTRICTION"
    EXTENDED_STATION_DWELL = "EXTENDED_STATION_DWELL"
    DELAYED_ROUTE_SETTING = "DELAYED_ROUTE_SETTING"
    TEMPORARY_PLATFORM_UNAVAILABILITY = "TEMPORARY_PLATFORM_UNAVAILABILITY"
    TVS_AUTHORIZATION_DELAY = "TVS_AUTHORIZATION_DELAY"
    COMMUNICATION_DELAY = "COMMUNICATION_DELAY"
    REDUCED_TRACTION = "REDUCED_TRACTION"


@dataclass
class StochasticVariableDefinition:
    """P11 Section 5: Standard contract for a configurable stochastic parameter."""

    variable_id: str
    target_object_type: TargetObjectType
    target_object_id: Optional[str] = None
    target_parameter: str = ""
    distribution_type: DistributionType = DistributionType.UNIFORM
    distribution_parameters: Dict[str, Any] = field(default_factory=dict)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = "s"
    sampling_scope: SamplingScope = SamplingScope.PER_TRAIN
    correlation_group: Optional[str] = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.variable_id:
            raise ValueError("Stochastic variable_id must not be empty.")
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError(
                    f"min_value ({self.min_value}) cannot exceed max_value ({self.max_value}) for variable '{self.variable_id}'."
                )

    def clamp(self, value: float) -> float:
        """P11-VAR-003: Enforces configured min and max bounding limits on sampled values."""
        clamped = value
        if self.min_value is not None and clamped < self.min_value:
            clamped = self.min_value
        if self.max_value is not None and clamped > self.max_value:
            clamped = self.max_value
        return clamped


@dataclass
class OperationalDisruption:
    """P11-DIS: Scenario-defined temporary operational disruption."""

    disruption_id: str
    disruption_type: DisruptionType
    start_time_s: float
    duration_s: float
    affected_resources: List[str] = field(default_factory=list)
    severity: float = 1.0
    operational_effect: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if self.start_time_s < 0.0:
            raise ValueError(f"Disruption start time must be non-negative (got {self.start_time_s} s).")
        if self.duration_s <= 0.0 or not math.isfinite(self.duration_s):
            raise ValueError(f"Disruption duration must be positive and finite (got {self.duration_s} s).")

    @property
    def end_time_s(self) -> float:
        return self.start_time_s + self.duration_s

    def is_active_at(self, timestamp_s: float) -> bool:
        """Check if disruption is active at timestamp_s [start_time, start_time + duration)."""
        return self.start_time_s <= timestamp_s < self.end_time_s
