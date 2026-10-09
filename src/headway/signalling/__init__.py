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
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import (
    AdvancedSignallingError,
    BrakingFeasibilityError,
    CommunicationTimeoutError,
    InterlockingRouteError,
    MovementAuthorityError,
    PositionReportError,
    ProtectedEnvelopeError,
    ReleasePolicy,
    ResourceCategory,
    ResourceConflictError,
    ResourceEventType,
    ResourceUsageRecord,
    SignalAspect,
    SignallingEvent,
    SupervisionInterventionError,
    SwitchLockError,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController, SwitchState

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
]
