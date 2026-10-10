"""Signalling, interlocking, resource control, and movement authority subsystem.

Milestone P05 — Resource Management, Interlocking & Fixed-Block Signalling (RHS-P05-001).
Milestone P06 — ETCS Level 2 & CBTC Moving-Block Signalling (RHS-P06-001).
"""

from headway.signalling.advanced_types import (
    AdvancedSignallingEngine,
    ProtectedTrainEnvelope,
    RadioCommunicationConfig,
    SignallingModelFidelity,
    SupervisionProfile,
    SupervisionState,
    TrainIntegrityStatus,
    TrainPositionReport,
)
from headway.signalling.aspects import SignalAspectController
from headway.signalling.authority import (
    AuthorityValidity,
    MovementAuthority,
    MovementAuthorityController,
)
from headway.signalling.cbtc import (
    CBTCConfig,
    CBTCMovingBlockEngine,
    ProtectedTrainEnvelopeCalculator,
)
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.etcs import (
    ETCSLevel2Config,
    ETCSLevel2Engine,
    RadioBlockCentre,
)
from headway.signalling.interlocking import (
    ActiveRouteState,
    InterlockingEngine,
    InterlockingRouteDefinition,
    RouteLockState,
)
from headway.signalling.junction_controller import (
    JunctionController,
    JunctionType,
    JunctionZone,
)
from headway.signalling.platform_controller import (
    ActivePlatformOccupation,
    PlatformAssignmentRecord,
    PlatformController,
    PlatformSelectionPolicy,
)
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.residual_occupation import (
    ResidualOccupationDetector,
    ResidualOccupationRecord,
)
from headway.signalling.resource_types import (
    AdvancedSignallingError,
    BrakingFeasibilityError,
    CommunicationTimeoutError,
    InterlockingRouteError,
    JunctionConflictError,
    MovementAuthorityError,
    PlatformCompatibilityError,
    PositionReportError,
    ProtectedEnvelopeError,
    ReleasePolicy,
    ResourceCategory,
    ResourceConflictError,
    ResourceEventType,
    ResourceUsageRecord,
    SignalAspect,
    SignallingEvent,
    StationResourceError,
    SupervisionInterventionError,
    SwitchLockError,
    TVSAuthorizationError,
    TVSInvariantError,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController, SwitchState
from headway.signalling.tvs_controller import (
    TVSAuthorizationState,
    TVSController,
    TVSExclusivityScope,
    TVSPhysicalOccupancyState,
    TVSSectionConfig,
    TVSTrainState,
)

__all__ = [
    # Resource categories & events
    "ResourceCategory",
    "ResourceEventType",
    "ReleasePolicy",
    "SignalAspect",
    "SignallingEvent",
    "ResourceUsageRecord",
    "ResourceConflictError",
    "InterlockingRouteError",
    "SwitchLockError",
    "MovementAuthorityError",
    "BrakingFeasibilityError",
    "AdvancedSignallingError",
    "CommunicationTimeoutError",
    "PositionReportError",
    "SupervisionInterventionError",
    "ProtectedEnvelopeError",
    "StationResourceError",
    "PlatformCompatibilityError",
    "JunctionConflictError",
    "TVSAuthorizationError",
    "TVSInvariantError",
    # Resources
    "ManagedResource",
    "ResourceController",
    # Switches
    "SwitchState",
    "SwitchController",
    # Interlocking
    "RouteLockState",
    "InterlockingRouteDefinition",
    "ActiveRouteState",
    "InterlockingEngine",
    # Signals
    "SignalAspectController",
    # Movement Authority
    "AuthorityValidity",
    "MovementAuthority",
    "MovementAuthorityController",
    # Protection
    "BrakingProtectionEngine",
    # Coordinator
    "SignallingCoordinator",
    # P06 Advanced Architecture
    "SignallingModelFidelity",
    "TrainIntegrityStatus",
    "SupervisionState",
    "RadioCommunicationConfig",
    "TrainPositionReport",
    "SupervisionProfile",
    "ProtectedTrainEnvelope",
    "AdvancedSignallingEngine",
    # P06 ETCS Level 2
    "ETCSLevel2Config",
    "RadioBlockCentre",
    "ETCSLevel2Engine",
    # P06 CBTC Moving-Block
    "CBTCConfig",
    "ProtectedTrainEnvelopeCalculator",
    "CBTCMovingBlockEngine",
    # P07 Stations, Junctions & TVS
    "PlatformSelectionPolicy",
    "PlatformAssignmentRecord",
    "ActivePlatformOccupation",
    "PlatformController",
    "ResidualOccupationDetector",
    "ResidualOccupationRecord",
    "JunctionType",
    "JunctionZone",
    "JunctionController",
    "TVSExclusivityScope",
    "TVSAuthorizationState",
    "TVSPhysicalOccupancyState",
    "TVSTrainState",
    "TVSSectionConfig",
    "TVSController",
]
