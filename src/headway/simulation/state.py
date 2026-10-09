"""Microscopic train dynamic state and operational modes.

Strictly satisfies RHS-P04-001 § 4:
- P04-STATE-001: Comprehensive dynamic state parameters in SI units.
- P04-STATE-002: Dynamic modes (STOPPED, ACCELERATING, CRUISING, COASTING,
  SERVICE_BRAKING, EMERGENCY_BRAKING, DWELLING).
- P04-STATE-003: State consistency enforcement (non-negative speed, position continuity).
- P04-STATE-004: Decoupling of state from immutable rolling stock and infrastructure configurations.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from headway.core.exceptions import SimulationError


class DynamicMode(str, Enum):
    """Instantaneous microscopic physical motion mode."""

    STOPPED = "STOPPED"                      # Standstill at zero speed without braking or traction
    ACCELERATING = "ACCELERATING"            # Propelling under tractive effort
    CRUISING = "CRUISING"                    # Maintaining steady speed against track resistances
    COASTING = "COASTING"                    # Zero traction and zero braking (free rolling)
    SERVICE_BRAKING = "SERVICE_BRAKING"      # Normal operational service brake application
    EMERGENCY_BRAKING = "EMERGENCY_BRAKING"  # Maximum emergency brake application
    DWELLING = "DWELLING"                    # Stationary at a station platform performing passenger dwell


class OperationalState(str, Enum):
    """Macro-level journey progression state."""

    STANDSTILL = "STANDSTILL"          # Before departure
    RUNNING = "RUNNING"                # In transit along route
    STATION_DWELL = "STATION_DWELL"    # Active scheduled dwell at a platform
    COMPLETED = "COMPLETED"            # Arrived at destination/route end


@dataclass(frozen=True)
class TrainDynamicState:
    """Instantaneous microscopic state of an individual train along a route.

    P04-STATE-001: All physical values strictly in authoritative SI units.
    """

    train_id: str
    simulation_time_s: float
    route_id: str
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
    current_link_id: Optional[str] = None
    link_front_coordinate_m: Optional[float] = None
    link_rear_coordinate_m: Optional[float] = None

    def __post_init__(self) -> None:
        """P04-STATE-003: Invariant validation."""
        if self.speed_ms < -1e-6:
            raise SimulationError(
                f"Negative train speed is physically prohibited (got {self.speed_ms} m/s).",
                context={"train_id": self.train_id, "speed_ms": self.speed_ms},
            )
        if self.simulation_time_s < 0:
            raise SimulationError(
                f"Simulation time cannot be negative (got {self.simulation_time_s} s).",
                context={"train_id": self.train_id},
            )
        if self.front_distance_m < self.rear_distance_m - 1e-4:
            raise SimulationError(
                f"Train front ({self.front_distance_m} m) cannot be behind rear ({self.rear_distance_m} m).",
                context={"train_id": self.train_id},
            )

    @property
    def speed_kmh(self) -> float:
        """Convenience property for speed in km/h."""
        return self.speed_ms * 3.6

    @property
    def is_stopped(self) -> bool:
        """True if train speed is essentially zero."""
        return abs(self.speed_ms) < 1e-4

    @property
    def is_moving(self) -> bool:
        """True if train speed exceeds zero standstill threshold."""
        return not self.is_stopped
