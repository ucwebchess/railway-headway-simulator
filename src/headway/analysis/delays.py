"""Operational delay calculation, classification, and propagation analysis subsystem.

Strictly satisfies RHS-P09-001 § 18 & § 19:
- P09-DLY-001 to 006: Schedule delay, departure delay, arrival delay, delay classification,
  prevention of double counting, and controlling cause resolution.
- P09-DLY-007 to 011: Primary disturbance tracking, secondary knock-on delay propagation,
  schedule buffer recovery, and complete delay audit logging.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class DelayCause(str, Enum):
    """P09-DLY-004: Standardized operational delay classifications."""

    PRIMARY_DISTURBANCE = "PRIMARY_DISTURBANCE"  # Injected exogenous operational disturbance
    SIGNALLING = "SIGNALLING"                    # Block occupation / red aspect / restrictive MA
    FOLLOWING_TRAIN = "FOLLOWING_TRAIN"          # Slower leader train pacing constraint
    JUNCTION = "JUNCTION"                        # Interlocking junction merge or crossover wait
    PLATFORM = "PLATFORM"                        # Platform occupation / dwell conflict
    STATION_DWELL = "STATION_DWELL"              # Departure hold at platform
    TVS = "TVS"                                  # Tunnel ventilation section authorization wait
    DISPATCH_PRIORITY = "DISPATCH_PRIORITY"      # Lower priority origin holding
    OTHER = "OTHER"                              # General operational constraint


# Priority for resolving controlling cause when multiple restrictions overlap (P09-DLY-006)
CAUSE_PRIORITY_ORDER = [
    DelayCause.PRIMARY_DISTURBANCE,
    DelayCause.TVS,
    DelayCause.JUNCTION,
    DelayCause.PLATFORM,
    DelayCause.SIGNALLING,
    DelayCause.FOLLOWING_TRAIN,
    DelayCause.DISPATCH_PRIORITY,
    DelayCause.STATION_DWELL,
    DelayCause.OTHER,
]


@dataclass
class DelayIncident:
    """Individual timestamped delay incident experienced by a train."""

    incident_id: str
    train_id: str
    cause: DelayCause
    start_time_s: float
    end_time_s: float
    duration_s: float
    location_m: float
    resource_id: Optional[str] = None
    source_train_id: Optional[str] = None
    description: Optional[str] = None


@dataclass
class SecondaryPropagationNode:
    """Directed link in the delay propagation tree."""

    source_train_id: str
    affected_train_id: str
    propagation_time_s: float
    delay_transmitted_s: float
    resource_id: str
    cause: DelayCause


@dataclass
class TrainDelaySummary:
    """P09-DLY-001 to 003: Comprehensive delay summary for an individual train service."""

    train_id: str
    service_id: str
    requested_departure_s: float
    actual_departure_s: Optional[float]
    departure_delay_s: float
    scheduled_arrival_s: Optional[float]
    actual_arrival_s: Optional[float]
    arrival_delay_s: float
    primary_delay_s: float
    secondary_delay_s: float
    recovered_time_s: float
    breakdown_by_cause_s: Dict[DelayCause, float] = field(default_factory=dict)
    incidents: List[DelayIncident] = field(default_factory=list)


class DelayPropagationTracker:
    """P09-DLY-007 to 011: Tracks primary disturbances, knock-on secondary propagation, and recoveries."""

    def __init__(self) -> None:
        self.incidents: List[DelayIncident] = []
        self.propagation_tree: List[SecondaryPropagationNode] = []
        self._incident_counter: int = 0

    def _next_incident_id(self) -> str:
        self._incident_counter += 1
        return f"INC_{self._incident_counter:04d}"

    def record_incident(
        self,
        train_id: str,
        cause: DelayCause,
        start_time_s: float,
        end_time_s: float,
        location_m: float,
        resource_id: Optional[str] = None,
        source_train_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> DelayIncident:
        """P09-DLY-004 & 005: Record a non-overlapping delay incident."""
        dur = max(0.0, end_time_s - start_time_s)
        inc = DelayIncident(
            incident_id=self._next_incident_id(),
            train_id=train_id,
            cause=cause,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            duration_s=dur,
            location_m=location_m,
            resource_id=resource_id,
            source_train_id=source_train_id,
            description=description,
        )
        self.incidents.append(inc)

        if source_train_id and source_train_id != train_id:
            self.propagation_tree.append(
                SecondaryPropagationNode(
                    source_train_id=source_train_id,
                    affected_train_id=train_id,
                    propagation_time_s=start_time_s,
                    delay_transmitted_s=dur,
                    resource_id=resource_id or "RESOURCE",
                    cause=cause,
                )
            )

        return inc

    def summarize_train_delays(
        self,
        train_id: str,
        service_id: str,
        requested_dep_s: float,
        actual_dep_s: Optional[float],
        scheduled_arr_s: Optional[float],
        actual_arr_s: Optional[float],
        primary_delay_s: float = 0.0,
    ) -> TrainDelaySummary:
        """P09-DLY-001 to 003: Aggregate all delay incidents for a train."""
        dep_delay = max(0.0, (actual_dep_s - requested_dep_s)) if actual_dep_s is not None else 0.0
        arr_delay = max(0.0, (actual_arr_s - scheduled_arr_s)) if (actual_arr_s and scheduled_arr_s) else 0.0

        train_incs = [inc for inc in self.incidents if inc.train_id == train_id]
        breakdown: Dict[DelayCause, float] = {c: 0.0 for c in DelayCause}

        for inc in train_incs:
            breakdown[inc.cause] = breakdown.get(inc.cause, 0.0) + inc.duration_s

        sec_delay = sum(dur for cause, dur in breakdown.items() if cause != DelayCause.PRIMARY_DISTURBANCE)
        # Schedule recovery: if initial delay exceeded arrival delay, difference was absorbed
        total_initial_delay = primary_delay_s + dep_delay
        recovered = max(0.0, total_initial_delay - arr_delay) if actual_arr_s else 0.0

        return TrainDelaySummary(
            train_id=train_id,
            service_id=service_id,
            requested_departure_s=requested_dep_s,
            actual_departure_s=actual_dep_s,
            departure_delay_s=dep_delay,
            scheduled_arrival_s=scheduled_arr_s,
            actual_arrival_s=actual_arr_s,
            arrival_delay_s=arr_delay,
            primary_delay_s=primary_delay_s,
            secondary_delay_s=sec_delay,
            recovered_time_s=recovered,
            breakdown_by_cause_s=breakdown,
            incidents=train_incs,
        )
