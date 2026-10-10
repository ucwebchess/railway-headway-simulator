"""Time-distance trajectory dataset structures for multi-train visualization.

Strictly satisfies RHS-P09-001 § 22:
- Retention of Train ID, service type, running direction, time, route distance,
  physical chainage, speed, operational state, and delay.
- Route-specific isolation to prevent branch distortion.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from headway.infrastructure.direction import RunningDirection
from headway.simulation.state import OperationalState


@dataclass
class TimeDistancePoint:
    """Instantaneous time-distance sample for an individual train."""

    train_id: str
    service_id: str
    route_id: str
    running_direction: RunningDirection
    time_s: float
    route_distance_m: float
    physical_chainage_m: Optional[float]
    speed_ms: float
    speed_kmh: float
    operational_state: OperationalState
    accumulated_delay_s: float
    current_link_id: Optional[str] = None


@dataclass
class MultiTrainTimeDistanceDataset:
    """Collection of time-distance trajectories across all simulated trains."""

    points_by_train: Dict[str, List[TimeDistancePoint]] = field(default_factory=dict)

    def __len__(self) -> int:
        return sum(len(pts) for pts in self.points_by_train.values())

    def add_point(self, point: TimeDistancePoint) -> None:
        """Append sample point for train."""
        if point.train_id not in self.points_by_train:
            self.points_by_train[point.train_id] = []
        self.points_by_train[point.train_id].append(point)

    def to_dataframe(self, route_id: Optional[str] = None) -> pd.DataFrame:
        """Export samples to pandas DataFrame, optionally filtering by route_id."""
        records = []
        for tid, points in self.points_by_train.items():
            for p in points:
                if route_id and p.route_id != route_id:
                    continue
                records.append({
                    "train_id": p.train_id,
                    "service_id": p.service_id,
                    "route_id": p.route_id,
                    "running_direction": p.running_direction.value,
                    "time_s": p.time_s,
                    "route_distance_m": p.route_distance_m,
                    "physical_chainage_m": p.physical_chainage_m,
                    "speed_ms": p.speed_ms,
                    "speed_kmh": p.speed_kmh,
                    "operational_state": p.operational_state.value,
                    "accumulated_delay_s": p.accumulated_delay_s,
                    "current_link_id": p.current_link_id,
                })
        return pd.DataFrame(records)
