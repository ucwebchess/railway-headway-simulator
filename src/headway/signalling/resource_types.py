"""Resource categories, signalling event types, and output contracts.

Strictly satisfies RHS-P05-001:
- § 4: Common Resource Categories (P05-RES-001 to P05-RES-004)
- § 6: Resource Request & Reservation (P05-REQ-001 to P05-REQ-006)
- § 7 & § 8: Physical Occupation & Release Events (P05-OCC-001 to P05-REL-007)
- § 18 & § 21: Signalling Event Logging and Resource Output Contracts.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from headway.core.exceptions import SignallingError
from headway.infrastructure.direction import RunningDirection


class ResourceCategory(str, Enum):
    """P05-RES-001: Canonical resource categories across all signalling technologies."""

    TRACK_BLOCK = "TRACK_BLOCK"
    INTERLOCKING_ROUTE = "INTERLOCKING_ROUTE"
    SWITCH = "SWITCH"
    JUNCTION_CONFLICT = "JUNCTION_CONFLICT"
    OVERLAP = "OVERLAP"
    PLATFORM = "PLATFORM"
    TVS = "TVS"
    SHARED_RESOURCE_GROUP = "SHARED_RESOURCE_GROUP"


class ResourceEventType(str, Enum):
    """Event types emitted during resource, route, and signalling lifecycle."""

    RESOURCE_REQUESTED = "RESOURCE_REQUESTED"
    RESOURCE_RESERVED = "RESOURCE_RESERVED"
    RESOURCE_ENTERED = "RESOURCE_ENTERED"
    RESOURCE_FRONT_EXITED = "RESOURCE_FRONT_EXITED"
    RESOURCE_REAR_CLEARED = "RESOURCE_REAR_CLEARED"
    RESOURCE_RELEASE_ELIGIBLE = "RESOURCE_RELEASE_ELIGIBLE"
    RESOURCE_RELEASED = "RESOURCE_RELEASED"

    ROUTE_REQUESTED = "ROUTE_REQUESTED"
    ROUTE_LOCKED = "ROUTE_LOCKED"
    ROUTE_RELEASED = "ROUTE_RELEASED"

    SWITCH_THROWN = "SWITCH_THROWN"
    SWITCH_LOCKED = "SWITCH_LOCKED"
    SWITCH_UNLOCKED = "SWITCH_UNLOCKED"

    SIGNAL_ASPECT_CHANGED = "SIGNAL_ASPECT_CHANGED"
    MA_ISSUED = "MA_ISSUED"
    MA_UPDATED = "MA_UPDATED"
    MA_EXPIRED = "MA_EXPIRED"


class ReleasePolicy(str, Enum):
    """Interlocking route release behavior."""

    COMPLETE = "COMPLETE"
    SECTIONAL = "SECTIONAL"


class SignalAspect(str, Enum):
    """Unified signal aspect states across 2-, 3-, and 4-aspect systems."""

    STOP = "STOP"
    PROCEED = "PROCEED"
    RED = "RED"
    YELLOW = "YELLOW"
    DOUBLE_YELLOW = "DOUBLE_YELLOW"
    GREEN = "GREEN"


class ResourceConflictError(SignallingError):
    """Raised when an exclusive resource or conflict group cannot be allocated."""

    DEFAULT_ERROR_CODE = "ERR_RESOURCE_CONFLICT"


class InterlockingRouteError(SignallingError):
    """Raised when interlocking route establishment, locking, or release fails."""

    DEFAULT_ERROR_CODE = "ERR_INTERLOCKING_ROUTE"


class SwitchLockError(SignallingError):
    """Raised when switch throw or locking violates interlocking safety."""

    DEFAULT_ERROR_CODE = "ERR_SWITCH_LOCK"


class MovementAuthorityError(SignallingError):
    """Raised when movement authority generation or validation fails."""

    DEFAULT_ERROR_CODE = "ERR_MOVEMENT_AUTHORITY"


class BrakingFeasibilityError(SignallingError):
    """Raised when stopping distance to End of Authority is insufficient."""

    DEFAULT_ERROR_CODE = "ERR_BRAKING_INFEASIBLE"


@dataclass(frozen=True)
class SignallingEvent:
    """P05-EVT: Timestamped signalling, route, and resource lifecycle event."""

    sequence_id: int
    timestamp_s: float
    event_type: ResourceEventType
    resource_id: str
    train_id: Optional[str] = None
    route_id: Optional[str] = None
    description: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceUsageRecord:
    """P05 § 21: Standardized underlying resource usage record for future blocking-time analysis."""

    usage_id: str
    train_id: str
    resource_id: str
    resource_type: ResourceCategory
    reservation_start_s: float
    physical_front_entry_s: Optional[float] = None
    front_exit_s: Optional[float] = None
    rear_clearance_s: Optional[float] = None
    release_eligibility_s: Optional[float] = None
    final_release_s: Optional[float] = None
    running_direction: RunningDirection = RunningDirection.FORWARD
