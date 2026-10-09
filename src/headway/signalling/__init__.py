"""Signalling, interlocking, resource control, and movement authority subsystem.

Milestone P05 — Resource Management, Interlocking & Fixed-Block Signalling (RHS-P05-001).
"""

from headway.signalling.aspects import SignalAspectController
from headway.signalling.authority import (
    AuthorityValidity,
    MovementAuthority,
    MovementAuthorityController,
)
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.interlocking import (
    ActiveRouteState,
    InterlockingEngine,
    InterlockingRouteDefinition,
    RouteLockState,
)
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import (
    BrakingFeasibilityError,
    InterlockingRouteError,
    MovementAuthorityError,
    ReleasePolicy,
    ResourceCategory,
    ResourceConflictError,
    ResourceEventType,
    ResourceUsageRecord,
    SignalAspect,
    SignallingEvent,
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
]
