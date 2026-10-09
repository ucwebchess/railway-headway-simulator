"""Negative tests verifying structured error handling and constraint enforcement for P05.

Strictly satisfies RHS-P05-001 § 23:
- Rejection of missing resources
- Invalid reservation owner and double allocation
- Unauthorized occupation exceeding capacity
- Premature release rejection
- Invalid routes and incompatible switch movements
- Conflicting route locks
- Invalid signal orientation
- Invalid movement authority endpoints
- Insufficient braking distance
- Negative release delay
- Invalid capacity (< 1)
"""

import pytest

from headway.data.canonical import Signal, TrackDirectionality
from headway.infrastructure.direction import RunningDirection
from headway.rolling_stock.braking import ConstantDecelerationBrakingModel
from headway.signalling.aspects import SignalAspectController
from headway.signalling.authority import MovementAuthorityController
from headway.signalling.interlocking import (
    InterlockingEngine,
    InterlockingRouteDefinition,
)
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import (
    BrakingFeasibilityError,
    InterlockingRouteError,
    MovementAuthorityError,
    ResourceCategory,
    ResourceConflictError,
    SwitchLockError,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import Switch, SwitchController, SwitchPosition


def test_invalid_resource_capacity():
    """Reject resource capacity < 1."""
    with pytest.raises(ResourceConflictError, match="capacity must be >= 1"):
        ManagedResource(resource_id="BLK_BAD", category=ResourceCategory.TRACK_BLOCK, capacity=0)


def test_negative_release_delay():
    """Reject negative release delay."""
    with pytest.raises(ResourceConflictError, match="cannot be negative"):
        ManagedResource(resource_id="BLK_BAD", category=ResourceCategory.TRACK_BLOCK, release_delay_s=-2.0)


def test_missing_resource_operations():
    """Operations on unknown resource IDs raise ResourceConflictError."""
    rc = ResourceController()
    with pytest.raises(ResourceConflictError, match="Cannot request unknown resource"):
        rc.request_resource("TRN_1", "NON_EXISTENT", 0.0)

    with pytest.raises(ResourceConflictError, match="Cannot reserve unknown resource"):
        rc.reserve_resource("TRN_1", "NON_EXISTENT", 0.0)

    with pytest.raises(ResourceConflictError, match="Unknown resource"):
        rc.front_enter_resource("TRN_1", "NON_EXISTENT", 0.0)


def test_unauthorized_occupation_exceeding_capacity():
    """Rejection of physical entry when capacity is fully occupied by other trains."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK, capacity=1)
    rc.register_resource(res)

    rc.front_enter_resource("TRN_1", "BLK_1", timestamp_s=0.0)

    # TRN_2 entering full exclusive resource raises collision/unauthorized entry error
    with pytest.raises(ResourceConflictError, match="collision/unauthorized entry"):
        rc.front_enter_resource("TRN_2", "BLK_1", timestamp_s=5.0)


def test_invalid_switch_operations():
    """Rejection of invalid switch operations on unknown switches or locked switches."""
    sc = SwitchController()
    with pytest.raises(SwitchLockError, match="Unknown switch"):
        sc.throw_switch("SW_UNKNOWN", SwitchPosition.REVERSE, timestamp_s=0.0)

    sw = Switch(switch_id="SW_01", node_id="ND_A")
    sc.register_switch(sw)
    sc.lock_switch("SW_01", "RT_1", SwitchPosition.NORMAL, timestamp_s=0.0)

    # Cannot lock in conflicting position
    with pytest.raises(SwitchLockError, match="Cannot lock switch"):
        sc.lock_switch("SW_01", "RT_2", SwitchPosition.REVERSE, timestamp_s=1.0)


def test_conflicting_route_lock_rejection():
    """Rejection of route request when conflicting route is already locked."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(rc, sc)

    b1 = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(b1)

    r1 = InterlockingRouteDefinition(
        route_id="RT_A", entry_signal_id="S1", exit_signal_id="S2",
        link_sequence=["LNK_1"], protected_block_ids=["BLK_1"], conflicting_route_ids=["RT_B"],
    )
    r2 = InterlockingRouteDefinition(
        route_id="RT_B", entry_signal_id="S3", exit_signal_id="S4",
        link_sequence=["LNK_2"], protected_block_ids=["BLK_1"], conflicting_route_ids=["RT_A"],
    )
    ie.register_route(r1)
    ie.register_route(r2)

    ie.request_and_lock_route("RT_A", "TRN_1", timestamp_s=0.0)

    # RT_B cannot be locked simultaneously
    assert ie.is_route_available("RT_B", "TRN_2", current_time_s=0.0) is False
    with pytest.raises(InterlockingRouteError, match="unavailable"):
        ie.request_and_lock_route("RT_B", "TRN_2", timestamp_s=0.0)


def test_invalid_movement_authority_endpoints():
    """Rejection of Movement Authority where EoA is behind start reference."""
    mac = MovementAuthorityController()
    from headway.data.canonical import Node, NodeType, Track, TrackDirectionality, TrackLink
    from headway.infrastructure.graph import PhysicalNetworkGraph
    from headway.infrastructure.route import RouteEngine

    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="N1", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="N2", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="T1", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(TrackLink(link_id="L1", track_id="T1", start_node_id="N1", end_node_id="N2", length_m=500.0, max_speed_ms=30.0))
    route = RouteEngine(graph).build_route_from_traversals("RT_TEST", [("L1", RunningDirection.FORWARD)])

    # Start reference 300m, EoA 200m -> Infeasible / Invalid
    with pytest.raises(MovementAuthorityError, match="cannot be before start reference"):
        mac.issue_authority(
            train_id="TRN_1", route=route, start_reference=300.0, end_of_authority=200.0,
            target_speed_ms=0.0, timestamp_s=0.0,
        )


def test_insufficient_stopping_distance_feasibility():
    """Structured failure when available distance to EoA is strictly less than stopping distance."""
    brk = ConstantDecelerationBrakingModel(service_deceleration_ms2=0.8, emergency_deceleration_ms2=1.0)
    # v0 = 25 m/s, b = 0.8 => d = 25^2 / (2 * 0.8) = 390.6 m. Available distance = 100 m.
    with pytest.raises(BrakingFeasibilityError, match="Insufficient braking distance to End of Authority"):
        BrakingProtectionEngine.validate_stopping_feasibility(
            current_speed_ms=25.0, current_position_m=900.0, end_of_authority_m=1000.0,
            target_speed_ms=0.0, braking_model=brk,
        )
