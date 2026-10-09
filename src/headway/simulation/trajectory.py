"""Trajectory output contracts, samples, and journey metrics.

Strictly satisfies RHS-P04-001 § 18:
- P04-OUT-001: Strict SI internal units.
- P04-OUT-002: Monotonically increasing time ordering.
- P04-OUT-003: Continuous spatial tracking.
- P04-OUT-004: Separate storage of boundary crossing events.
- P04-OUT-005: Decoupled storage resolution and DataFrame export adapters.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd

from headway.infrastructure.direction import RunningDirection
from headway.simulation.events import BoundaryEvent
from headway.simulation.state import DynamicMode, OperationalState


@dataclass(frozen=True)
class TrajectorySample:
    """Detailed physical state snapshot at a specific simulation timestamp."""

    time_s: float
    front_distance_m: float
    rear_distance_m: float
    speed_ms: float
    acceleration_ms2: float
    traction_force_n: float
    braking_force_n: float
    davis_resistance_n: float
    gradient_resistance_n: float
    curvature_resistance_n: float
    net_force_n: float
    dynamic_mode: DynamicMode
    operational_state: OperationalState
    link_id: Optional[str] = None
    physical_coordinate_m: Optional[float] = None

    @property
    def speed_kmh(self) -> float:
        return self.speed_ms * 3.6


@dataclass
class TrainTrajectory:
    """Complete simulated time-history of an individual train along a route."""

    train_id: str
    train_type_id: str
    route_id: str
    running_direction: RunningDirection
    samples: List[TrajectorySample] = field(default_factory=list)
    events: List[BoundaryEvent] = field(default_factory=list)

    @property
    def total_time_s(self) -> float:
        if not self.samples:
            return 0.0
        return self.samples[-1].time_s - self.samples[0].time_s

    @property
    def total_distance_m(self) -> float:
        if not self.samples:
            return 0.0
        return self.samples[-1].front_distance_m - self.samples[0].front_distance_m

    @property
    def moving_time_s(self) -> float:
        """P04-JT-002: Moving time (speed > 0.001 m/s)."""
        if len(self.samples) < 2:
            return 0.0
        m_time = 0.0
        for i in range(len(self.samples) - 1):
            s0 = self.samples[i]
            s1 = self.samples[i + 1]
            if s0.speed_ms > 1e-3 or s1.speed_ms > 1e-3:
                m_time += (s1.time_s - s0.time_s)
        return m_time

    @property
    def dwell_time_s(self) -> float:
        """P04-JT-003: Station dwell time."""
        return max(0.0, self.total_time_s - self.moving_time_s)

    @property
    def max_speed_ms(self) -> float:
        if not self.samples:
            return 0.0
        return max(s.speed_ms for s in self.samples)

    @property
    def average_moving_speed_ms(self) -> float:
        m_time = self.moving_time_s
        if m_time <= 0:
            return 0.0
        return self.total_distance_m / m_time

    def to_dataframe(self) -> pd.DataFrame:
        """Export samples to pandas DataFrame."""
        records = []
        for s in self.samples:
            records.append(
                {
                    "time_s": s.time_s,
                    "front_distance_m": s.front_distance_m,
                    "rear_distance_m": s.rear_distance_m,
                    "speed_ms": s.speed_ms,
                    "speed_kmh": s.speed_kmh,
                    "acceleration_ms2": s.acceleration_ms2,
                    "traction_force_n": s.traction_force_n,
                    "braking_force_n": s.braking_force_n,
                    "davis_resistance_n": s.davis_resistance_n,
                    "gradient_resistance_n": s.gradient_resistance_n,
                    "curvature_resistance_n": s.curvature_resistance_n,
                    "net_force_n": s.net_force_n,
                    "dynamic_mode": s.dynamic_mode.value,
                    "operational_state": s.operational_state.value,
                    "link_id": s.link_id,
                    "physical_coordinate_m": s.physical_coordinate_m,
                }
            )
        return pd.DataFrame(records)

    def to_records(self) -> List[Dict[str, Any]]:
        return self.to_dataframe().to_dict(orient="records")
