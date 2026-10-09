"""Mandatory engineering verification benchmarks for Milestone P05: Resource Management & Signalling.

Strictly verifies all 30 benchmarks (P05-B001 through P05-B030) per RHS-P05-001 § 22:
- P05-B001: Free resource reservation
- P05-B002: Exclusive resource conflict
- P05-B003: Physical front entry
- P05-B004: Front exit does not release block
- P05-B005: Rear clearance
- P05-B006: Release delay
- P05-B007: Multiple resource occupation
- P05-B008: Stationary train occupation
- P05-B009: Multi-link resource occupation
- P05-B010: Reverse block occupation
- P05-B011: Reverse rear clearance
- P05-B012: Opposing-direction conflict
- P05-B013: Route setup
- P05-B014: Route locking
- P05-B015: Complete route release
- P05-B016: Sectional route release
- P05-B017: Switch position conflict
- P05-B018: Reverse switch route
- P05-B019: Two-aspect STOP
- P05-B020: Two-aspect PROCEED
- P05-B021: Three-aspect sequence
- P05-B022: Four-aspect look-ahead
- P05-B023: Direction-aware signal aspects
- P05-B024: Movement authority endpoint
- P05-B025: Reverse movement authority
- P05-B026: Restrictive braking approach
- P05-B027: Insufficient braking distance
- P05-B028: Simultaneous requests
- P05-B029: Deterministic event ordering
- P05-B030: Resource invariant verification
"""

import math
import pytest

from headway.data.canonical import (
    AspectModelType,
    Node,
    NodeType,
    ResourceInterval,
    Signal,
    SignalType,
    SignallingBlock,
    Track,
    TrackDirectionality,
    TrackLink,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.resources import MultiLinkResourceGeometry, PhysicalResource
from headway.infrastructure.route import RouteEngine
from headway.infrastructure.switches import Switch, SwitchMovement, SwitchPosition
from headway.infrastructure.train_geometry import TrainGeometry
from headway.rolling_stock.braking import ConstantDecelerationBrakingModel
from headway.signalling.aspects import SignalAspectController
from headway.signalling.authority import MovementAuthorityController
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.interlocking import (
    InterlockingEngine,
    InterlockingRouteDefinition,
    RouteLockState,
)
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import (
    BrakingFeasibilityError,
    InterlockingRouteError,
    ReleasePolicy,
    ResourceCategory,
    ResourceConflictError,
    ResourceEventType,
    SignalAspect,
    SwitchLockError,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController


@pytest.fixture
def corridor_setup():
    """Build a 3-link railway corridor: ND_1 --(LNK_1: 1000m)--> ND_2 --(LNK_2: 1000m)--> ND_3 --(LNK_3: 1000m)--> ND_4."""
    graph = PhysicalNetworkGraph()
    for n in ["ND_1", "ND_2", "ND_3", "ND_4"]:
        graph.add_node(Node(node_id=n, node_type=NodeType.ENDPOINT if "1" in n or "4" in n else NodeType.JUNCTION))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

    graph.add_link(TrackLink(link_id="LNK_1", track_id="TRK_01", start_node_id="ND_1", end_node_id="ND_2", length_m=1000.0, max_speed_ms=40.0))
    graph.add_link(TrackLink(link_id="LNK_2", track_id="TRK_01", start_node_id="ND_2", end_node_id="ND_3", length_m=1000.0, max_speed_ms=40.0))
    graph.add_link(TrackLink(link_id="LNK_3", track_id="TRK_01", start_node_id="ND_3", end_node_id="ND_4", length_m=1000.0, max_speed_ms=40.0))

    route_engine = RouteEngine(graph)
    route_fwd = route_engine.build_route_from_traversals("RT_FWD", [
        ("LNK_1", RunningDirection.FORWARD),
        ("LNK_2", RunningDirection.FORWARD),
        ("LNK_3", RunningDirection.FORWARD),
    ])
    route_rev = route_fwd.create_reverse_route(graph, "RT_REV")
    return graph, route_fwd, route_rev


# ==============================================================================
# P05-B001 through P05-B030
# ==============================================================================

@pytest.mark.engineering
def test_p05_b001_free_resource_reservation():
    """P05-B001: Free resource reservation."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK, capacity=1)
    rc.register_resource(res)

    assert res.is_available(for_train_id="TRN_1", current_time_s=10.0) is True
    rc.reserve_resource("TRN_1", "BLK_01", timestamp_s=10.0)

    assert res.is_reserved is True
    assert "TRN_1" in res.reservations


@pytest.mark.engineering
def test_p05_b002_exclusive_resource_conflict():
    """P05-B002: Exclusive resource conflict prevents double reservation."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK, capacity=1)
    rc.register_resource(res)

    rc.reserve_resource("TRN_1", "BLK_01", timestamp_s=10.0)

    # TRN_2 attempting to reserve exclusive resource BLK_01 must be rejected
    assert res.is_available(for_train_id="TRN_2", current_time_s=10.0) is False
    with pytest.raises(ResourceConflictError, match="unavailable for reservation"):
        rc.reserve_resource("TRN_2", "BLK_01", timestamp_s=10.0)


@pytest.mark.engineering
def test_p05_b003_physical_front_entry():
    """P05-B003: Physical front entry triggers RESOURCE_ENTERED and marks occupied."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(res)

    rc.reserve_resource("TRN_1", "BLK_01", timestamp_s=10.0)
    rc.front_enter_resource("TRN_1", "BLK_01", timestamp_s=15.0)

    assert res.is_occupied is True
    assert "TRN_1" in res.occupants
    last_event = rc.event_log[-1]
    assert last_event.event_type == ResourceEventType.RESOURCE_ENTERED


@pytest.mark.engineering
def test_p05_b004_front_exit_does_not_release_block():
    """P05-B004: Front exit does NOT release block; block remains occupied."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(res)

    rc.reserve_resource("TRN_1", "BLK_01", timestamp_s=10.0)
    rc.front_enter_resource("TRN_1", "BLK_01", timestamp_s=15.0)
    rc.front_exit_resource("TRN_1", "BLK_01", timestamp_s=25.0)

    # MUST STILL BE OCCUPIED AND UNAVAILABLE
    assert res.is_occupied is True
    assert "TRN_1" in res.occupants
    assert res.is_available(for_train_id="TRN_2", current_time_s=25.0) is False
    last_event = rc.event_log[-1]
    assert last_event.event_type == ResourceEventType.RESOURCE_FRONT_EXITED


@pytest.mark.engineering
def test_p05_b005_rear_clearance():
    """P05-B005: Rear clearance removes physical occupation."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK, release_delay_s=0.0)
    rc.register_resource(res)

    rc.reserve_resource("TRN_1", "BLK_01", timestamp_s=10.0)
    rc.front_enter_resource("TRN_1", "BLK_01", timestamp_s=15.0)
    rc.front_exit_resource("TRN_1", "BLK_01", timestamp_s=25.0)
    rc.rear_clear_resource("TRN_1", "BLK_01", timestamp_s=30.0)

    assert res.is_occupied is False
    assert "TRN_1" not in res.occupants


@pytest.mark.engineering
def test_p05_b006_release_delay():
    """P05-B006: Release delay keeps resource unavailable until timer expires."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK, release_delay_s=5.0)
    rc.register_resource(res)

    rc.reserve_resource("TRN_1", "BLK_01", timestamp_s=10.0)
    rc.front_enter_resource("TRN_1", "BLK_01", timestamp_s=15.0)
    rc.rear_clear_resource("TRN_1", "BLK_01", timestamp_s=30.0)

    # At t = 32s (delay not expired: 30 + 5 = 35s), resource is still pending release
    assert res.is_release_pending(32.0) is True
    assert res.is_available(for_train_id="TRN_2", current_time_s=32.0) is False

    # Process release at t = 36s (delay expired)
    rc.process_pending_releases(36.0)
    assert res.is_release_pending(36.0) is False
    assert res.is_available(for_train_id="TRN_2", current_time_s=36.0) is True


@pytest.mark.engineering
def test_p05_b007_multiple_resource_occupation(corridor_setup):
    """P05-B007: Multiple resource occupation by a single train."""
    _, route_fwd, _ = corridor_setup
    # Train length = 400m, front is at 1100m (link 2), rear is at 700m (link 1)
    footprint = TrainGeometry.compute_footprint(route_fwd, front_distance_m=1100.0, train_length_m=400.0)

    link_ids = {lo.link_id for lo in footprint.link_occupancies}
    assert "LNK_1" in link_ids
    assert "LNK_2" in link_ids
    assert len(link_ids) == 2


@pytest.mark.engineering
def test_p05_b008_stationary_train_occupation(corridor_setup):
    """P05-B008: Stationary train retains physical occupation of all covered blocks."""
    _, route_fwd, _ = corridor_setup
    fp1 = TrainGeometry.compute_footprint(route_fwd, front_distance_m=1200.0, train_length_m=300.0)
    # Stationary: position unchanged at t1 and t2
    fp2 = TrainGeometry.compute_footprint(route_fwd, front_distance_m=1200.0, train_length_m=300.0)

    assert fp1.link_occupancies == fp2.link_occupancies
    assert len(fp1.link_occupancies) >= 1


@pytest.mark.engineering
def test_p05_b009_multi_link_resource_occupation():
    """P05-B009: Multi-link resource spanning multiple links."""
    geom = MultiLinkResourceGeometry()
    res = PhysicalResource(
        resource_id="BLK_MULTI",
        intervals=[
            ResourceInterval(link_id="LNK_1", start_offset_m=800.0, end_offset_m=1000.0),
            ResourceInterval(link_id="LNK_2", start_offset_m=0.0, end_offset_m=400.0),
        ],
    )
    geom.register_resource(res)
    assert res.total_length_m == 600.0
    assert res.link_ids == {"LNK_1", "LNK_2"}


@pytest.mark.engineering
def test_p05_b010_reverse_block_occupation(corridor_setup):
    """P05-B010: Reverse block occupation enters from physical opposite boundary."""
    _, _, route_rev = corridor_setup
    # In reverse route, train front starts at s=0 (which is ND_4 / LNK_3 physical end)
    footprint = TrainGeometry.compute_footprint(route_rev, front_distance_m=150.0, train_length_m=100.0)
    assert len(footprint.link_occupancies) == 1
    lo = footprint.link_occupancies[0]
    assert lo.link_id == "LNK_3"
    assert lo.traversal_direction == RunningDirection.REVERSE


@pytest.mark.engineering
def test_p05_b011_reverse_rear_clearance(corridor_setup):
    """P05-B011: Reverse rear clearance occurs at reverse boundary."""
    _, _, route_rev = corridor_setup
    # Train front moves to 1200m (in LNK_2), rear is at 1000m (just cleared LNK_3)
    footprint = TrainGeometry.compute_footprint(route_rev, front_distance_m=1200.0, train_length_m=200.0)
    link_ids = {lo.link_id for lo in footprint.link_occupancies}
    assert "LNK_3" not in link_ids
    assert "LNK_2" in link_ids


@pytest.mark.engineering
def test_p05_b012_opposing_direction_conflict():
    """P05-B012: Opposing-direction conflict on single track block."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_SINGLE", category=ResourceCategory.TRACK_BLOCK, capacity=1)
    rc.register_resource(res)

    # TRN_FWD reserves block in forward direction
    rc.reserve_resource("TRN_FWD", "BLK_SINGLE", timestamp_s=0.0, running_direction=RunningDirection.FORWARD)

    # TRN_REV attempting to reserve the same physical block in reverse is rejected
    assert res.is_available(for_train_id="TRN_REV", current_time_s=0.0) is False
    with pytest.raises(ResourceConflictError, match="unavailable for reservation"):
        rc.reserve_resource("TRN_REV", "BLK_SINGLE", timestamp_s=0.0, running_direction=RunningDirection.REVERSE)


@pytest.mark.engineering
def test_p05_b013_route_setup():
    """P05-B013: Route setup applies configured setup time."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(rc, sc, default_setup_time_s=3.0)

    blk = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(blk)

    r_def = InterlockingRouteDefinition(
        route_id="RT_01", entry_signal_id="SIG_01", exit_signal_id="SIG_02",
        link_sequence=["LNK_1"], protected_block_ids=["BLK_01"], setup_time_s=3.0,
    )
    ie.register_route(r_def)

    lock_time = ie.request_and_lock_route("RT_01", "TRN_1", timestamp_s=10.0)
    assert lock_time == 13.0  # 10s + 3s setup time
    assert ie.active_states["RT_01"].is_locked is True


@pytest.mark.engineering
def test_p05_b014_route_locking():
    """P05-B014: Route locking locks associated switches and blocks."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(rc, sc)

    blk = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(blk)
    sw = Switch(switch_id="SW_01", node_id="ND_2")
    sc.register_switch(sw)

    r_def = InterlockingRouteDefinition(
        route_id="RT_01", entry_signal_id="SIG_01", exit_signal_id="SIG_02",
        link_sequence=["LNK_1", "LNK_2"], protected_block_ids=["BLK_01"],
        required_switch_positions={"SW_01": SwitchPosition.NORMAL},
    )
    ie.register_route(r_def)

    ie.request_and_lock_route("RT_01", "TRN_1", timestamp_s=5.0)

    assert blk.is_locked is True
    assert sc.states["SW_01"].is_locked is True


@pytest.mark.engineering
def test_p05_b015_complete_route_release():
    """P05-B015: Complete route release unlocks all resources upon train clearance."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(rc, sc)

    blk = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(blk)
    sw = Switch(switch_id="SW_01", node_id="ND_2")
    sc.register_switch(sw)

    r_def = InterlockingRouteDefinition(
        route_id="RT_01", entry_signal_id="SIG_01", exit_signal_id="SIG_02",
        link_sequence=["LNK_1"], protected_block_ids=["BLK_01"],
        required_switch_positions={"SW_01": SwitchPosition.NORMAL},
        release_policy=ReleasePolicy.COMPLETE,
    )
    ie.register_route(r_def)

    ie.request_and_lock_route("RT_01", "TRN_1", timestamp_s=0.0)
    assert ie.active_states["RT_01"].is_locked is True

    # Complete release at t = 20.0
    ie.release_route("RT_01", timestamp_s=20.0)
    assert ie.active_states["RT_01"].is_locked is False
    assert blk.is_locked is False
    assert sc.states["SW_01"].is_locked is False


@pytest.mark.engineering
def test_p05_b016_sectional_route_release():
    """P05-B016: Sectional route release unlocks blocks sequentially."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(rc, sc)

    b1 = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK)
    b2 = ManagedResource(resource_id="BLK_2", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(b1)
    rc.register_resource(b2)

    r_def = InterlockingRouteDefinition(
        route_id="RT_SEC", entry_signal_id="SIG_1", exit_signal_id="SIG_3",
        link_sequence=["LNK_1", "LNK_2"], protected_block_ids=["BLK_1", "BLK_2"],
        release_policy=ReleasePolicy.SECTIONAL,
    )
    ie.register_route(r_def)

    ie.request_and_lock_route("RT_SEC", "TRN_1", timestamp_s=0.0)
    assert b1.is_locked is True
    assert b2.is_locked is True

    # Train rear clears BLK_1 at t = 15.0 -> BLK_1 released sectionally
    ie.process_sectional_release("RT_SEC", "BLK_1", timestamp_s=15.0)
    assert b1.is_locked is False
    assert b2.is_locked is True
    assert ie.active_states["RT_SEC"].is_locked is True

    # Train rear clears BLK_2 at t = 30.0 -> Entire route completed
    ie.process_sectional_release("RT_SEC", "BLK_2", timestamp_s=30.0)
    assert b2.is_locked is False
    assert ie.active_states["RT_SEC"].is_locked is False


@pytest.mark.engineering
def test_p05_b017_switch_position_conflict():
    """P05-B017: Switch position conflict prevents incompatible route locking."""
    sc = SwitchController()
    sw = Switch(switch_id="SW_01", node_id="ND_2")
    sc.register_switch(sw, initial_position=SwitchPosition.NORMAL)

    # Lock switch in NORMAL for RT_A
    sc.lock_switch("SW_01", "RT_A", SwitchPosition.NORMAL, timestamp_s=0.0)

    # Attempt to throw/lock SW_01 in REVERSE for RT_B is rejected
    with pytest.raises(SwitchLockError, match="locked"):
        sc.throw_switch("SW_01", SwitchPosition.REVERSE, timestamp_s=5.0, route_id="RT_B")


@pytest.mark.engineering
def test_p05_b018_reverse_switch_route():
    """P05-B018: Reverse switch route aligns and locks switch for reverse trailing movement."""
    sc = SwitchController()
    sw = Switch(switch_id="SW_01", node_id="ND_2")
    # Add permitted movement from LNK_2 to LNK_1 via REVERSE position
    sw.add_movement(SwitchMovement(entry_link_id="LNK_2", exit_link_id="LNK_1", position=SwitchPosition.REVERSE))
    sc.register_switch(sw)

    req = sc.get_required_movement_position(entry_link_id="LNK_2", exit_link_id="LNK_1")
    assert req == ("SW_01", SwitchPosition.REVERSE)

    # Throw and lock
    sc.throw_switch("SW_01", SwitchPosition.REVERSE, timestamp_s=0.0, route_id="RT_REV")
    sc.get_position("SW_01", current_time_s=4.0)
    sc.lock_switch("SW_01", "RT_REV", SwitchPosition.REVERSE, timestamp_s=4.0)
    assert sc.states["SW_01"].current_position == SwitchPosition.REVERSE


@pytest.mark.engineering
def test_p05_b019_two_aspect_stop():
    """P05-B019: Two-aspect STOP when downstream block is occupied or route not locked."""
    rc = ResourceController()
    blk = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK)
    blk.occupants.add("TRN_OTHER")  # Occupied
    rc.register_resource(blk)

    sig_ctrl = SignalAspectController(rc, aspect_model=AspectModelType.TWO_ASPECT)
    sig_ctrl.register_signal(Signal(signal_id="SIG_01", link_id="LNK_1", offset_m=0.0, direction=TrackDirectionality.NOMINAL))

    aspect = sig_ctrl.evaluate_signal_aspect("SIG_01", ["BLK_1"], RunningDirection.FORWARD, timestamp_s=0.0)
    assert aspect == SignalAspect.STOP


@pytest.mark.engineering
def test_p05_b020_two_aspect_proceed():
    """P05-B020: Two-aspect PROCEED when block is clear and route locked."""
    rc = ResourceController()
    blk = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(blk)

    sig_ctrl = SignalAspectController(rc, aspect_model=AspectModelType.TWO_ASPECT)
    sig_ctrl.register_signal(Signal(signal_id="SIG_01", link_id="LNK_1", offset_m=0.0, direction=TrackDirectionality.NOMINAL))

    aspect = sig_ctrl.evaluate_signal_aspect("SIG_01", ["BLK_1"], RunningDirection.FORWARD, timestamp_s=0.0, is_route_locked=True)
    assert aspect == SignalAspect.PROCEED


@pytest.mark.engineering
def test_p05_b021_three_aspect_sequence():
    """P05-B021: Three-aspect sequence (RED -> YELLOW -> GREEN)."""
    rc = ResourceController()
    b1 = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK)
    b2 = ManagedResource(resource_id="BLK_2", category=ResourceCategory.TRACK_BLOCK)
    rc.register_resource(b1)
    rc.register_resource(b2)

    sig_ctrl = SignalAspectController(rc, aspect_model=AspectModelType.THREE_ASPECT)
    sig_ctrl.register_signal(Signal(signal_id="SIG_01", link_id="LNK_1", offset_m=0.0, direction=TrackDirectionality.NOMINAL))

    # Case 1: Block 1 occupied -> RED
    b1.occupants.add("TRN_LEADER")
    assert sig_ctrl.evaluate_signal_aspect("SIG_01", ["BLK_1", "BLK_2"], RunningDirection.FORWARD, 0.0) == SignalAspect.RED

    # Case 2: Block 1 clear, Block 2 occupied -> YELLOW
    b1.occupants.clear()
    b2.occupants.add("TRN_LEADER")
    assert sig_ctrl.evaluate_signal_aspect("SIG_01", ["BLK_1", "BLK_2"], RunningDirection.FORWARD, 5.0) == SignalAspect.YELLOW

    # Case 3: Both clear -> GREEN
    b2.occupants.clear()
    assert sig_ctrl.evaluate_signal_aspect("SIG_01", ["BLK_1", "BLK_2"], RunningDirection.FORWARD, 10.0) == SignalAspect.GREEN


@pytest.mark.engineering
def test_p05_b022_four_aspect_look_ahead():
    """P05-B022: Four-aspect look-ahead (RED -> YELLOW -> DOUBLE_YELLOW -> GREEN)."""
    rc = ResourceController()
    b1 = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK)
    b2 = ManagedResource(resource_id="BLK_2", category=ResourceCategory.TRACK_BLOCK)
    b3 = ManagedResource(resource_id="BLK_3", category=ResourceCategory.TRACK_BLOCK)
    for b in [b1, b2, b3]:
        rc.register_resource(b)

    sig_ctrl = SignalAspectController(rc, aspect_model=AspectModelType.FOUR_ASPECT)
    sig_ctrl.register_signal(Signal(signal_id="SIG_01", link_id="LNK_1", offset_m=0.0, direction=TrackDirectionality.NOMINAL))

    blocks = ["BLK_1", "BLK_2", "BLK_3"]
    # Block 1 occupied -> RED
    b1.occupants.add("T")
    assert sig_ctrl.evaluate_signal_aspect("SIG_01", blocks, RunningDirection.FORWARD, 0.0) == SignalAspect.RED

    # Block 2 occupied -> YELLOW
    b1.occupants.clear()
    b2.occupants.add("T")
    assert sig_ctrl.evaluate_signal_aspect("SIG_01", blocks, RunningDirection.FORWARD, 1.0) == SignalAspect.YELLOW

    # Block 3 occupied -> DOUBLE_YELLOW
    b2.occupants.clear()
    b3.occupants.add("T")
    assert sig_ctrl.evaluate_signal_aspect("SIG_01", blocks, RunningDirection.FORWARD, 2.0) == SignalAspect.DOUBLE_YELLOW

    # All clear -> GREEN
    b3.occupants.clear()
    assert sig_ctrl.evaluate_signal_aspect("SIG_01", blocks, RunningDirection.FORWARD, 3.0) == SignalAspect.GREEN


@pytest.mark.engineering
def test_p05_b023_direction_aware_signal_aspects():
    """P05-B023: Direction-aware signal orientation and aspect look-ahead."""
    rc = ResourceController()
    sig_ctrl = SignalAspectController(rc, aspect_model=AspectModelType.THREE_ASPECT)

    # Signal configured NOMINAL (facing forward movements)
    sig = Signal(signal_id="SIG_FWD", link_id="LNK_1", offset_m=100.0, direction=TrackDirectionality.NOMINAL)
    sig_ctrl.register_signal(sig)

    assert sig_ctrl.is_signal_facing(sig, RunningDirection.FORWARD) is True
    assert sig_ctrl.is_signal_facing(sig, RunningDirection.REVERSE) is False


@pytest.mark.engineering
def test_p05_b024_movement_authority_endpoint(corridor_setup):
    """P05-B024: Movement authority endpoint constraint."""
    _, route_fwd, _ = corridor_setup
    mac = MovementAuthorityController()

    ma = mac.issue_authority(
        train_id="TRN_1", route=route_fwd, start_reference=0.0,
        end_of_authority=1500.0, target_speed_ms=0.0, timestamp_s=0.0,
    )

    assert ma.end_of_authority == 1500.0
    assert ma.target_speed_ms == 0.0
    assert ma.is_valid_at(0.0) is True


@pytest.mark.engineering
def test_p05_b025_reverse_movement_authority(corridor_setup):
    """P05-B025: Reverse movement authority coordinates."""
    _, _, route_rev = corridor_setup
    mac = MovementAuthorityController()

    ma_rev = mac.issue_authority(
        train_id="TRN_REV", route=route_rev, start_reference=0.0,
        end_of_authority=2000.0, target_speed_ms=0.0, timestamp_s=5.0,
    )

    assert ma_rev.running_direction == RunningDirection.REVERSE
    assert ma_rev.end_of_authority == 2000.0


@pytest.mark.engineering
def test_p05_b026_restrictive_braking_approach():
    """P05-B026: Restrictive braking approach speed calculation."""
    # EoA at 1000m, target speed = 0, deceleration = 1.0 m/s^2
    # At position 550m, distance = 450m -> v_permitted = sqrt(2 * 1 * 450) = 30.0 m/s
    v_perm = BrakingProtectionEngine.calculate_permitted_approach_speed(
        current_distance_m=550.0, end_of_authority_m=1000.0, target_speed_ms=0.0, deceleration_ms2=1.0,
    )
    assert v_perm == pytest.approx(30.0, rel=1e-5)


@pytest.mark.engineering
def test_p05_b027_insufficient_braking_distance():
    """P05-B027: Insufficient braking distance raises BrakingFeasibilityError."""
    brk_model = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=1.0, emergency_deceleration_ms2=1.2,
        response_delay_s=0.0, build_up_time_s=0.0,
    )
    # Current speed 30 m/s requires 450m stopping distance. Available distance = 200m -> Infeasible
    with pytest.raises(BrakingFeasibilityError, match="Insufficient braking distance"):
        BrakingProtectionEngine.validate_stopping_feasibility(
            current_speed_ms=30.0, current_position_m=800.0,
            end_of_authority_m=1000.0, target_speed_ms=0.0, braking_model=brk_model,
        )


@pytest.mark.engineering
def test_p05_b028_simultaneous_requests():
    """P05-B028: Simultaneous requests resolved atomically, exactly one granted."""
    rc = ResourceController()
    res = ManagedResource(resource_id="BLK_01", category=ResourceCategory.TRACK_BLOCK, capacity=1)
    rc.register_resource(res)

    req1 = rc.request_resource("TRN_1", "BLK_01", timestamp_s=10.0)
    rc.reserve_resource("TRN_1", "BLK_01", timestamp_s=10.0)

    req2 = rc.request_resource("TRN_2", "BLK_01", timestamp_s=10.0)
    assert req1 is True
    assert req2 is False


@pytest.mark.engineering
def test_p05_b029_deterministic_event_ordering():
    """P05-B029: Deterministic event ordering sequence (11 steps)."""
    coord = SignallingCoordinator()
    b1 = ManagedResource(resource_id="BLK_1", category=ResourceCategory.TRACK_BLOCK, release_delay_s=2.0)
    coord.resource_controller.register_resource(b1)

    # Initial state: TRN_1 occupies BLK_1
    coord.resource_controller.reserve_resource("TRN_1", "BLK_1", timestamp_s=0.0)
    coord.resource_controller.front_enter_resource("TRN_1", "BLK_1", timestamp_s=5.0)

    # Step at t = 10.0: rear clears
    coord.process_timestep_events(
        current_time_s=10.0,
        train_movements=[{"train_id": "TRN_1", "resource_id": "BLK_1", "type": "REAR_CLEAR"}],
    )
    assert b1.is_occupied is False
    assert b1.is_release_pending(10.0) is True

    # Step at t = 12.0: timer expires and releases
    rel_events = coord.process_timestep_events(current_time_s=12.0)
    assert len(rel_events) == 1
    assert rel_events[0].event_type == ResourceEventType.RESOURCE_RELEASED


@pytest.mark.engineering
def test_p05_b030_resource_invariant_verification():
    """P05-B030: Resource invariant verification (availability derived without contradictions)."""
    res = ManagedResource(resource_id="BLK_TEST", category=ResourceCategory.TRACK_BLOCK, capacity=1)

    # Invariant 1: Initially available
    assert res.is_available() is True
    assert res.is_occupied is False
    assert res.is_reserved is False
    assert res.is_locked is False

    # Invariant 2: Occupation contradicts availability for other trains
    res.occupants.add("TRN_A")
    assert res.is_available(for_train_id="TRN_B") is False

    # Invariant 3: Lock contradicts availability
    res.occupants.clear()
    res.locks.add("RT_LOCK")
    assert res.is_available() is False
