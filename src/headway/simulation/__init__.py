"""Microscopic train movement dynamics and numerical simulation subsystem.

Milestone P04 — Braking, Speed Profiles & Microscopic Train Dynamics (RHS-P04-001).
"""

from headway.simulation.events import (
    BoundaryEvent,
    BoundaryEventDetector,
    CrossingEventType,
)
from headway.simulation.integrator import MicroscopicSimulator
from headway.simulation.speed_profile import (
    SpeedProfileEngine,
    SpeedProfilePoint,
)
from headway.simulation.state import (
    DynamicMode,
    OperationalState,
    TrainDynamicState,
)
from headway.simulation.targets import (
    BrakingTarget,
    BrakingTargetResolver,
    BrakingTargetType,
)
from headway.simulation.trajectory import (
    TrajectorySample,
    TrainTrajectory,
)

__all__ = [
    "DynamicMode",
    "OperationalState",
    "TrainDynamicState",
    "BrakingTargetType",
    "BrakingTarget",
    "BrakingTargetResolver",
    "CrossingEventType",
    "BoundaryEvent",
    "BoundaryEventDetector",
    "SpeedProfilePoint",
    "SpeedProfileEngine",
    "TrajectorySample",
    "TrainTrajectory",
    "MicroscopicSimulator",
]
