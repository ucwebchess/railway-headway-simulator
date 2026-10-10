"""Engineering benchmark tests P07-B001 through P07-B035 for Milestone P07.

Covers Stations, Platforms, Multi-Platform Allocation, Residual Stationary Rear Occupation,
Junctions, Crossovers, Switch Route Locking, Sectional Release, TVS Control Engine,
Single-Train Rule, MA Clamping, Numerical Benchmarks A, B, C, D, and Reverse Traversal.
"""

import math
import pytest

from headway.data.canonical import (
    Platform,
    ResourceInterval,
    SharedResourceGroup,
    SignallingBlock,
    SignallingTechnologyType,
    Station,
    TrackDirectionality,
    Tunnel,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.switches import Switch, SwitchPosition
from headway.signalling.authority import AuthorityValidity, MovementAuthority
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.interlocking import InterlockingEngine, InterlockingRouteDefinition, RouteLockState
from headway.signalling.junction_controller import JunctionController, JunctionType, JunctionZone
from headway.signalling.platform_controller import (
    ActivePlatformOccupation,
    PlatformAssignmentRecord,
    PlatformController,
    PlatformSelectionPolicy,
)
from headway.signalling.residual_occupation import ResidualOccupationDetector, ResidualOccupationRecord
from headway.signalling.resource_types import (
    JunctionConflictError,
    PlatformCompatibilityError,
    ReleasePolicy,
    ResourceCategory,
    ResourceEventType,
    StationResourceError,
    TVSAuthorizationError,
    TVSInvariantError,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController
from headway.signalling.tvs_controller import (
    TVSAuthorizationState,
    TVSController,
    TVSExclusivityScope,
    TVSPhysicalOccupancyState,
)


# ==============================================================================
# § 5 - § 10: Stations & Platforms (P07-B001 to P07-B011)
# ==============================================================================


def test_p07_b001_canonical_station_registration():
    """P07-B001: Canonical station registration and attribute validation."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    station = Station(
        station_id="STN_CENTRAL",
        name="Central Station",
        chainage_km=15.5,
    )
    pc.register_station(station)

    assert "STN_CENTRAL" in pc.stations
    assert pc.stations["STN_CENTRAL"].name == "Central Station"
    assert pc.stations["STN_CENTRAL"].chainage_km == 15.5


def test_p07_b002_platform_resource_creation():
    """P07-B002: Platform resource registered under ResourceCategory.PLATFORM."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    station = Station(station_id="STN_ALPHA", name="Alpha Station")
    pc.register_station(station)

    plat = Platform(
        platform_id="PLT_ALPHA_1",
        station_id="STN_ALPHA",
        link_id="L_TRK1",
        start_offset_m=0.0,
        end_offset_m=250.0,
        length_m=250.0,
    )
    res = pc.register_platform(plat, release_delay_s=3.0)

    assert res.resource_id == "PLT_ALPHA_1"
    assert res.category == ResourceCategory.PLATFORM
    assert res.capacity == 1
    assert res.release_delay_s == 3.0
    assert "PLT_ALPHA_1" in pc.station_to_platforms["STN_ALPHA"]
    assert rc.get_resource("PLT_ALPHA_1") is not None


def test_p07_b003_usable_platform_length_compatibility():
    """P07-B003: Platform usable length validation (fit vs overflow)."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    plat = Platform(
        platform_id="PLT_01",
        station_id="STN_A",
        link_id="L1",
        start_offset_m=0.0,
        end_offset_m=200.0,
        length_m=200.0,
    )
    pc.register_platform(plat)

    # Fits: 180m <= 200m
    comp = pc.validate_platform_compatibility("PLT_01", train_length_m=180.0)
    assert comp.platform_id == "PLT_01"

    # Exact fit: 200m <= 200m
    comp_exact = pc.validate_platform_compatibility("PLT_01", train_length_m=200.0)
    assert comp_exact.platform_id == "PLT_01"

    # Overflow: 205m > 200m -> PlatformCompatibilityError
    with pytest.raises(PlatformCompatibilityError) as exc_info:
        pc.validate_platform_compatibility("PLT_01", train_length_m=205.0)
    assert "exceeds usable platform length" in str(exc_info.value)


def test_p07_b004_platform_reservation_lifecycle():
    """P07-B004: Platform exclusive reservation lifecycle and mutual exclusion."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    plat = Platform(
        platform_id="PLT_B4",
        station_id="STN_B",
        link_id="L1",
        start_offset_m=0.0,
        end_offset_m=300.0,
        length_m=300.0,
    )
    pc.register_platform(plat)

    # Train 1 reserves platform
    ok1 = pc.request_platform(
        train_id="TR_01",
        platform_id="PLT_B4",
        train_length_m=200.0,
        timestamp_s=10.0,
    )
    assert ok1 is True

    # Train 2 requests same platform while reserved -> rejected
    ok2 = pc.request_platform(
        train_id="TR_02",
        platform_id="PLT_B4",
        train_length_m=200.0,
        timestamp_s=12.0,
    )
    assert ok2 is False

    res = rc.get_resource("PLT_B4")
    assert res.is_reserved
    assert "TR_01" in res.reservations


def test_p07_b005_dwell_lifecycle_events():
    """P07-B005: Dwell lifecycle events chronological sequence."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    plat = Platform(
        platform_id="PLT_MAIN",
        station_id="STN_CITY",
        link_id="L1",
        start_offset_m=0.0,
        end_offset_m=300.0,
        length_m=300.0,
    )
    pc.register_platform(plat)

    # 1. Reserve
    pc.request_platform("TR_10", "PLT_MAIN", train_length_m=150.0, timestamp_s=0.0)
    # 2. Enter
    pc.front_enter_platform("TR_10", "PLT_MAIN", timestamp_s=20.0, dwell_duration_s=60.0)
    # 3. Start dwell
    pc.start_dwell("TR_10", "PLT_MAIN", timestamp_s=25.0)
    # 4. Complete dwell
    pc.complete_dwell("TR_10", "PLT_MAIN", timestamp_s=85.0)

    event_types = [e.event_type for e in pc.event_log]
    assert ResourceEventType.PLATFORM_REQUESTED in event_types
    assert ResourceEventType.PLATFORM_RESERVED in event_types
    assert ResourceEventType.PLATFORM_ENTERED in event_types
    assert ResourceEventType.STATION_ARRIVAL in event_types
    assert ResourceEventType.DWELL_STARTED in event_types
    assert ResourceEventType.DWELL_COMPLETED in event_types
    assert ResourceEventType.STATION_DEPARTURE in event_types


def test_p07_b006_prohibition_on_release_upon_dwell_end_or_front_exit():
    """P07-B006: Strict prohibition on platform release upon dwell end or front exit."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    plat = Platform(
        platform_id="PLT_06",
        station_id="STN_06",
        link_id="L1",
        start_offset_m=0.0,
        end_offset_m=250.0,
        length_m=250.0,
    )
    pc.register_platform(plat)

    pc.request_platform("TR_06", "PLT_06", 200.0, timestamp_s=0.0)
    pc.front_enter_platform("TR_06", "PLT_06", timestamp_s=10.0)
    pc.start_dwell("TR_06", "PLT_06", timestamp_s=15.0)
    pc.complete_dwell("TR_06", "PLT_06", timestamp_s=75.0)

    # At dwell end (t=75s), platform MUST remain occupied!
    res = rc.get_resource("PLT_06")
    assert res.is_occupied, "Platform must not release upon dwell completion!"

    # Front exit at t=80s
    pc.front_exit_platform("TR_06", "PLT_06", timestamp_s=80.0)
    assert res.is_occupied, "Platform must not release upon front exit!"


def test_p07_b007_post_clearance_platform_release_delay():
    """P07-B007: Post-clearance platform release delay timer enforcement."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc, default_release_delay_s=4.0)

    plat = Platform(
        platform_id="PLT_07",
        station_id="STN_07",
        link_id="L1",
        start_offset_m=0.0,
        end_offset_m=200.0,
        length_m=200.0,
    )
    pc.register_platform(plat, release_delay_s=4.0)

    pc.request_platform("TR_07", "PLT_07", 150.0, timestamp_s=0.0)
    pc.front_enter_platform("TR_07", "PLT_07", timestamp_s=10.0)
    pc.complete_dwell("TR_07", "PLT_07", timestamp_s=40.0)
    pc.front_exit_platform("TR_07", "PLT_07", timestamp_s=45.0)

    # Rear clear at t=50.0s
    pc.rear_clear_platform("TR_07", "PLT_07", timestamp_s=50.0)

    # At t=52.0s, release delay (4s) has not expired -> platform still in release delay
    pc.process_platform_releases(current_time_s=52.0)
    res = rc.get_resource("PLT_07")
    assert res.can_reserve("TR_NEW", current_time_s=52.0) is False

    # At t=54.1s, release delay expired -> platform released
    pc.process_platform_releases(current_time_s=54.1)
    assert res.is_occupied is False
    assert res.is_reserved is False
    assert res.can_reserve("TR_NEW", current_time_s=54.1) is True


def test_p07_b008_reverse_direction_platform_dwell():
    """P07-B008: Reverse-direction platform stop and dwell."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    plat = Platform(
        platform_id="PLT_REV",
        station_id="STN_REV",
        link_id="L2",
        start_offset_m=0.0,
        end_offset_m=250.0,
        length_m=250.0,
    )
    pc.register_platform(plat)

    ok = pc.request_platform(
        train_id="TR_REV",
        platform_id="PLT_REV",
        train_length_m=180.0,
        timestamp_s=5.0,
        running_direction=RunningDirection.REVERSE,
    )
    assert ok is True

    pc.front_enter_platform("TR_REV", "PLT_REV", timestamp_s=25.0)
    pc.start_dwell("TR_REV", "PLT_REV", timestamp_s=30.0, dwell_duration_s=45.0)
    pc.complete_dwell("TR_REV", "PLT_REV", timestamp_s=75.0)
    pc.rear_clear_platform("TR_REV", "PLT_REV", timestamp_s=90.0)

    occ = pc.platform_occupations["TR_REV"]
    assert occ.dwell_duration_s == 45.0
    assert occ.rear_clearance_s == 90.0


def test_p07_b009_multi_platform_fixed_assignment():
    """P07-B009: Multi-platform allocation under FIXED_ASSIGNMENT policy."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    stn = Station(station_id="STN_MULTI", name="Multi Platform Stn")
    pc.register_station(stn)
    p1 = Platform(platform_id="P1", station_id="STN_MULTI", link_id="T1", start_offset_m=0, end_offset_m=200, length_m=200.0)
    p2 = Platform(platform_id="P2", station_id="STN_MULTI", link_id="T2", start_offset_m=0, end_offset_m=200, length_m=200.0)
    pc.register_platform(p1)
    pc.register_platform(p2)

    assigned = pc.allocate_platform(
        train_id="TR_FIXED",
        station_id="STN_MULTI",
        train_length_m=150.0,
        timestamp_s=0.0,
        preferred_platform_id="P2",
        policy=PlatformSelectionPolicy.FIXED_ASSIGNMENT,
    )
    assert assigned == "P2"
    assert rc.get_resource("P2").is_reserved
    assert rc.get_resource("P1").is_reserved is False


def test_p07_b010_multi_platform_preferred_with_alternatives():
    """P07-B010: Multi-platform allocation falling back to permitted alternative when preferred is occupied."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    stn = Station(station_id="STN_PA", name="Preferred Alt Stn")
    pc.register_station(stn)
    p1 = Platform(platform_id="PLT_01", station_id="STN_PA", link_id="T1", start_offset_m=0, end_offset_m=200, length_m=200.0)
    p2 = Platform(platform_id="PLT_02", station_id="STN_PA", link_id="T2", start_offset_m=0, end_offset_m=200, length_m=200.0)
    pc.register_platform(p1)
    pc.register_platform(p2)

    # Train 1 occupies PLT_01
    pc.request_platform("TR_01", "PLT_01", 150.0, timestamp_s=0.0)

    # Train 2 prefers PLT_01, but allows PLT_02
    assigned = pc.allocate_platform(
        train_id="TR_02",
        station_id="STN_PA",
        train_length_m=150.0,
        timestamp_s=5.0,
        preferred_platform_id="PLT_01",
        permitted_platform_ids=["PLT_02"],
        policy=PlatformSelectionPolicy.PREFERRED_WITH_ALTERNATIVES,
    )
    assert assigned == "PLT_02"
    assert rc.get_resource("PLT_02").is_reserved


def test_p07_b011_multi_platform_earliest_feasible():
    """P07-B011: Multi-platform allocation under EARLIEST_FEASIBLE policy."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    stn = Station(station_id="STN_EF", name="Earliest Feasible Stn")
    pc.register_station(stn)
    p1 = Platform(platform_id="PLT_A", station_id="STN_EF", link_id="T1", start_offset_m=0, end_offset_m=100, length_m=100.0)  # Too short for 150m train
    p2 = Platform(platform_id="PLT_B", station_id="STN_EF", link_id="T2", start_offset_m=0, end_offset_m=250, length_m=250.0)  # Compatible
    pc.register_platform(p1)
    pc.register_platform(p2)

    assigned = pc.allocate_platform(
        train_id="TR_EF",
        station_id="STN_EF",
        train_length_m=150.0,
        timestamp_s=10.0,
        policy=PlatformSelectionPolicy.EARLIEST_FEASIBLE,
    )
    assert assigned == "PLT_B"


# ==============================================================================
# § 8: Residual Stationary Rear Occupation (P07-B012 to P07-B014)
# ==============================================================================


def test_p07_b012_residual_rear_occupation_benchmark_a():
    """P07-B012: Benchmark A - Numerical verification of residual rear occupation:

    Train front stopped at x_stop = 1000m, train length = 200m -> x_rear = 800m.
    Platform entry boundary x_boundary = 850m.
    Infringement distance = max(0, 850 - 800) = 50.0m.
    Dwell duration = 180.0s during which upstream resource remains occupied.
    Post-departure clearance with acceleration a = 0.5 m/s^2:
    t_clear = sqrt(2 * d / a) = sqrt(100 / 0.5) = sqrt(200) = 14.142s.
    """
    detector = ResidualOccupationDetector()
    rec = detector.detect_residual_rear_infringement(
        train_id="TR_BENCH_A",
        train_length_m=200.0,
        front_stopping_offset_m=1000.0,
        platform_id="PLT_MAIN",
        platform_entry_boundary_offset_m=850.0,
        upstream_resource_id="BLK_UPSTREAM",
        dwell_duration_s=180.0,
        post_departure_accel_ms2=0.5,
        running_direction=RunningDirection.FORWARD,
    )

    assert rec.train_id == "TR_BENCH_A"
    assert rec.rear_stopping_offset_m == 800.0
    assert rec.is_infringing is True
    assert rec.infringement_distance_m == 50.0
    assert rec.stationary_dwell_duration_s == 180.0
    assert math.isclose(rec.moving_clearance_time_s, math.sqrt(200.0), rel_tol=1e-5)
    assert math.isclose(rec.total_upstream_clearance_time_s, 180.0 + math.sqrt(200.0), rel_tol=1e-5)


def test_p07_b013_residual_rear_occupation_non_infringing():
    """P07-B013: Residual rear occupation when train completely clears upstream boundary."""
    detector = ResidualOccupationDetector()
    # Train length = 100m -> rear = 900m > boundary 850m -> no infringement
    rec = detector.detect_residual_rear_infringement(
        train_id="TR_SHORT",
        train_length_m=100.0,
        front_stopping_offset_m=1000.0,
        platform_id="PLT_01",
        platform_entry_boundary_offset_m=850.0,
        upstream_resource_id="BLK_UP",
        dwell_duration_s=120.0,
        post_departure_accel_ms2=0.6,
        running_direction=RunningDirection.FORWARD,
    )

    assert rec.rear_stopping_offset_m == 900.0
    assert rec.is_infringing is False
    assert rec.infringement_distance_m == 0.0
    assert rec.moving_clearance_time_s == 0.0
    assert rec.total_upstream_clearance_time_s == 0.0


def test_p07_b014_reverse_direction_residual_rear_occupation():
    """P07-B014: Residual rear occupation in REVERSE running direction:

    Train front stopped at x_stop = 800m. Moving in REVERSE (decreasing chainage).
    Train length = 200m -> train rear is at x_rear = 1000m.
    Platform upstream entry boundary in reverse is at x_boundary = 950m.
    Infringement into upstream resource: 1000m - 950m = 50.0m!
    """
    detector = ResidualOccupationDetector()
    rec = detector.detect_residual_rear_infringement(
        train_id="TR_REV_INF",
        train_length_m=200.0,
        front_stopping_offset_m=800.0,
        platform_id="PLT_REV",
        platform_entry_boundary_offset_m=950.0,
        upstream_resource_id="BLK_UP_REV",
        dwell_duration_s=150.0,
        post_departure_accel_ms2=0.5,
        running_direction=RunningDirection.REVERSE,
    )

    assert rec.rear_stopping_offset_m == 1000.0
    assert rec.is_infringing is True
    assert rec.infringement_distance_m == 50.0
    assert rec.stationary_dwell_duration_s == 150.0


# ==============================================================================
# § 11 - § 12: Junctions & Crossovers (P07-B015 to P07-B020)
# ==============================================================================


def test_p07_b015_junction_merge_conflict_prevention():
    """P07-B015: Junction merge conflict prevention between converging routes."""
    rc = ResourceController()
    rc.register_resource(ManagedResource(resource_id="BLK_COMMON", category=ResourceCategory.TRACK_BLOCK))
    sc = SwitchController()
    ie = InterlockingEngine(resource_controller=rc, switch_controller=sc)
    jc = JunctionController(interlocking_engine=ie, switch_controller=sc, resource_controller=rc)

    # Define two converging routes merging into common single track
    r1 = InterlockingRouteDefinition(
        route_id="RT_MERGE_1",
        entry_signal_id="SIG_1",
        exit_signal_id="SIG_COMMON",
        link_sequence=["L_IN1", "L_COMMON"],
        protected_block_ids=["BLK_COMMON"],
        conflicting_route_ids=["RT_MERGE_2"],
    )
    r2 = InterlockingRouteDefinition(
        route_id="RT_MERGE_2",
        entry_signal_id="SIG_2",
        exit_signal_id="SIG_COMMON",
        link_sequence=["L_IN2", "L_COMMON"],
        protected_block_ids=["BLK_COMMON"],
        conflicting_route_ids=["RT_MERGE_1"],
    )
    ie.register_route(r1)
    ie.register_route(r2)

    zone = JunctionZone(
        junction_id="JNC_MERGE_01",
        junction_type=JunctionType.MERGE,
        route_ids=["RT_MERGE_1", "RT_MERGE_2"],
        protected_block_ids=["BLK_COMMON"],
    )
    jc.register_junction_zone(zone)

    # Train 1 requests and locks RT_MERGE_1
    lock_time = jc.request_junction_movement(
        train_id="TR_01",
        route_id="RT_MERGE_1",
        timestamp_s=10.0,
    )
    assert lock_time == 13.0
    assert ie.active_states["RT_MERGE_1"].is_locked

    # Train 2 attempts to request conflicting converging route RT_MERGE_2 -> raises JunctionConflictError
    with pytest.raises(JunctionConflictError) as exc_info:
        jc.request_junction_movement(
            train_id="TR_02",
            route_id="RT_MERGE_2",
            timestamp_s=14.0,
        )
    assert "Cannot lock junction route 'RT_MERGE_2'" in str(exc_info.value)


def test_p07_b016_junction_diverge_concurrent_movements():
    """P07-B016: Junction diverge concurrent movements to distinct tracks."""
    rc = ResourceController()
    rc.register_resource(ManagedResource(resource_id="BLK_A", category=ResourceCategory.TRACK_BLOCK))
    rc.register_resource(ManagedResource(resource_id="BLK_B", category=ResourceCategory.TRACK_BLOCK))
    sc = SwitchController()
    ie = InterlockingEngine(resource_controller=rc, switch_controller=sc)
    jc = JunctionController(interlocking_engine=ie, switch_controller=sc, resource_controller=rc)

    # Two parallel diverging routes without shared switches or blocks
    r1 = InterlockingRouteDefinition(
        route_id="RT_DIV_A",
        entry_signal_id="SIG_A",
        exit_signal_id="SIG_OUT_A",
        link_sequence=["L_A1", "L_A2"],
        protected_block_ids=["BLK_A"],
    )
    r2 = InterlockingRouteDefinition(
        route_id="RT_DIV_B",
        entry_signal_id="SIG_B",
        exit_signal_id="SIG_OUT_B",
        link_sequence=["L_B1", "L_B2"],
        protected_block_ids=["BLK_B"],
    )
    ie.register_route(r1)
    ie.register_route(r2)

    zone = JunctionZone(
        junction_id="JNC_DIV_01",
        junction_type=JunctionType.DIVERGE,
        route_ids=["RT_DIV_A", "RT_DIV_B"],
    )
    jc.register_junction_zone(zone)

    # Both routes can be locked concurrently
    t1 = jc.request_junction_movement("TR_A", "RT_DIV_A", timestamp_s=0.0)
    t2 = jc.request_junction_movement("TR_B", "RT_DIV_B", timestamp_s=0.0)

    assert ie.active_states["RT_DIV_A"].is_locked
    assert ie.active_states["RT_DIV_B"].is_locked


def test_p07_b017_diamond_crossing_mutual_exclusion():
    """P07-B017: Diamond crossing mutual exclusion conflict detection."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(resource_controller=rc, switch_controller=sc)
    jc = JunctionController(interlocking_engine=ie, switch_controller=sc, resource_controller=rc)

    r_cross1 = InterlockingRouteDefinition(
        route_id="RT_X1",
        entry_signal_id="S1",
        exit_signal_id="S2",
        link_sequence=["L_TRK1"],
        conflicting_route_ids=["RT_X2"],
    )
    r_cross2 = InterlockingRouteDefinition(
        route_id="RT_X2",
        entry_signal_id="S3",
        exit_signal_id="S4",
        link_sequence=["L_TRK2"],
        conflicting_route_ids=["RT_X1"],
    )
    ie.register_route(r_cross1)
    ie.register_route(r_cross2)

    zone = JunctionZone(
        junction_id="DIAMOND_01",
        junction_type=JunctionType.DIAMOND_CROSSING,
        route_ids=["RT_X1", "RT_X2"],
    )
    jc.register_junction_zone(zone)

    jc.request_junction_movement("TR_1", "RT_X1", timestamp_s=0.0)

    with pytest.raises(JunctionConflictError):
        jc.request_junction_movement("TR_2", "RT_X2", timestamp_s=1.0)


def test_p07_b018_switch_alignment_and_locking():
    """P07-B018: Switch alignment and route locking."""
    rc = ResourceController()
    sc = SwitchController()
    sw = Switch(switch_id="SW_01", node_id="ND_01")
    sc.register_switch(sw, initial_position=SwitchPosition.NORMAL)

    ie = InterlockingEngine(resource_controller=rc, switch_controller=sc)
    jc = JunctionController(interlocking_engine=ie, switch_controller=sc, resource_controller=rc)

    route = InterlockingRouteDefinition(
        route_id="RT_SW_REV",
        entry_signal_id="SIG_ENTRY",
        exit_signal_id="SIG_EXIT",
        link_sequence=["L_IN", "L_REV"],
        required_switch_positions={"SW_01": SwitchPosition.REVERSE},
    )
    ie.register_route(route)

    jc.request_junction_movement("TR_SW", "RT_SW_REV", timestamp_s=0.0)

    # Switch SW_01 must be aligned to REVERSE and locked
    assert sc.states["SW_01"].current_position == SwitchPosition.REVERSE
    assert sc.states["SW_01"].is_locked
    assert "RT_SW_REV" in sc.states["SW_01"].locked_by_routes


def test_p07_b019_sectional_release_of_junction_elements():
    """P07-B019: Sectional release of junction switch and block resources."""
    rc = ResourceController()
    sc = SwitchController()
    sw = Switch(switch_id="SW_J1", node_id="ND_01")
    sc.register_switch(sw, initial_position=SwitchPosition.NORMAL)
    ie = InterlockingEngine(resource_controller=rc, switch_controller=sc)
    jc = JunctionController(interlocking_engine=ie, switch_controller=sc, resource_controller=rc)

    # Register blocks
    rc.register_resource(ManagedResource(resource_id="BLK_SW", category=ResourceCategory.TRACK_BLOCK))
    rc.register_resource(ManagedResource(resource_id="BLK_EXIT", category=ResourceCategory.TRACK_BLOCK))

    route = InterlockingRouteDefinition(
        route_id="RT_SEC_JNC",
        entry_signal_id="SIG_1",
        exit_signal_id="SIG_2",
        link_sequence=["L1", "L2"],
        protected_block_ids=["BLK_SW", "BLK_EXIT"],
        required_switch_positions={"SW_J1": SwitchPosition.NORMAL},
        release_policy=ReleasePolicy.SECTIONAL,
    )
    ie.register_route(route)

    jc.request_junction_movement("TR_SEC", "RT_SEC_JNC", timestamp_s=0.0)
    assert sc.states["SW_J1"].is_locked

    # Train rear clears first block BLK_SW -> triggers sectional release of BLK_SW and SW_J1
    jc.process_sectional_junction_release(
        route_id="RT_SEC_JNC",
        cleared_block_id="BLK_SW",
        cleared_switch_id="SW_J1",
        timestamp_s=20.0,
    )

    # BLK_SW is in released blocks
    assert "BLK_SW" in ie.active_states["RT_SEC_JNC"].released_block_ids
    # Switch SW_J1 is unlocked and available!
    assert sc.states["SW_J1"].is_locked is False


def test_p07_b020_reverse_direction_junction_movement():
    """P07-B020: Reverse-direction junction movement and route locking."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(resource_controller=rc, switch_controller=sc)
    jc = JunctionController(interlocking_engine=ie, switch_controller=sc, resource_controller=rc)

    route_rev = InterlockingRouteDefinition(
        route_id="RT_REV_JNC",
        entry_signal_id="SIG_REV_IN",
        exit_signal_id="SIG_REV_OUT",
        link_sequence=["L_COMMON", "L_IN1"],
        running_direction=RunningDirection.REVERSE,
    )
    ie.register_route(route_rev)

    lock_time = jc.request_junction_movement(
        train_id="TR_REV",
        route_id="RT_REV_JNC",
        timestamp_s=5.0,
        running_direction=RunningDirection.REVERSE,
    )
    assert lock_time == 8.0
    assert ie.active_states["RT_REV_JNC"].is_locked


# ==============================================================================
# § 13 - § 23: TVS Control Engine & Numerical Benchmarks (P07-B021 to P07-B035)
# ==============================================================================


def test_p07_b021_canonical_tvs_independent_boundaries():
    """P07-B021: Canonical TVS section registration and independent chainage boundaries."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs = TVSSection(
        tvs_id="TVS_01",
        tunnel_id="TUN_NORTH",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=500.0, end_offset_m=2500.0)],
        max_train_occupancy=1,
        release_delay_s=5.0,
    )
    res = tc.register_tvs_section(tvs)

    assert res.resource_id == "TVS_01"
    assert res.category == ResourceCategory.TVS_SECTION
    assert tc.configs["TVS_01"].release_delay_s == 5.0
    assert tc.configs["TVS_01"].max_train_occupancy == 1


def test_p07_b022_tvs_single_train_rule():
    """P07-B022: TVS single-train rule enforcement (N_max = 1)."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_auth_delay_s=1.0)

    tvs = TVSSection(
        tvs_id="TVS_RULE",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
        max_train_occupancy=1,
    )
    tc.register_tvs_section(tvs)

    # Train 1 requests entry -> authorized
    ok1, auth_t1 = tc.request_tvs_entry("TR_1", "TVS_RULE", timestamp_s=0.0)
    assert ok1 is True
    assert auth_t1 == 1.0

    # Train 2 requests entry while Train 1 is authorized -> rejected
    ok2, auth_t2 = tc.request_tvs_entry("TR_2", "TVS_RULE", timestamp_s=2.0)
    assert ok2 is False
    assert auth_t2 is None


def test_p07_b023_tvs_entry_authorization_gate_with_delay():
    """P07-B023: TVS entry authorization gate with processing delay."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_auth_delay_s=2.0)

    tvs = TVSSection(
        tvs_id="TVS_GATE",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
    )
    tc.register_tvs_section(tvs, auth_processing_delay_s=2.0)

    ok, eff_t = tc.request_tvs_entry("TR_GATE", "TVS_GATE", timestamp_s=10.0)
    assert ok is True
    assert eff_t == 12.0

    # Before t=12.0s, train is not authorized
    assert tc.is_train_authorized("TR_GATE", "TVS_GATE", current_time_s=11.5) is False
    # At t=12.0s, train is authorized
    assert tc.is_train_authorized("TR_GATE", "TVS_GATE", current_time_s=12.0) is True


def test_p07_b024_tvs_holding_point_movement_authority_clamping():
    """P07-B024: TVS entry holding point and MA clamping when unauthorized."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs = TVSSection(
        tvs_id="TVS_CLAMP",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=5000.0, end_offset_m=8000.0)],
    )
    tc.register_tvs_section(tvs)

    # Train has NOT requested TVS entry (unauthorized)
    # Target unconstrained MA = 6000m (inside TVS). Holding point = 4900m (upstream of TVS entry 5000m).
    clamped_ma, is_clamped = tc.clamp_movement_authority(
        train_id="TR_UNAUTH",
        tvs_id="TVS_CLAMP",
        unconstrained_ma_limit_m=6000.0,
        current_time_s=0.0,
        holding_point_distance_m=4900.0,
    )
    assert is_clamped is True
    assert clamped_ma == 4900.0


def test_p07_b025_tvs_entry_authorization_lifts_ma_clamping():
    """P07-B025: Granting TVS authorization lifts MA clamping past holding point."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_auth_delay_s=1.0)

    tvs = TVSSection(
        tvs_id="TVS_LIFT",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=5000.0, end_offset_m=8000.0)],
    )
    tc.register_tvs_section(tvs)

    tc.request_tvs_entry("TR_AUTH", "TVS_LIFT", timestamp_s=0.0)

    # At t=2.0s, authorization is effective
    clamped_ma, is_clamped = tc.clamp_movement_authority(
        train_id="TR_AUTH",
        tvs_id="TVS_LIFT",
        unconstrained_ma_limit_m=6000.0,
        current_time_s=2.0,
        holding_point_distance_m=4900.0,
    )
    assert is_clamped is False
    assert clamped_ma == 6000.0


def test_p07_b026_tvs_constant_speed_traversal_benchmark_b():
    """P07-B026: Benchmark B - TVS Single-Train Traversal Numerical Verification:

    Train length L = 200m, constant speed v = 25 m/s.
    TVS length = 5,000m (x = 10,000m to 15,000m).
    Entry at t = 0.0s.
    Front exit at x = 15,000m: t = 5000 / 25 = 200.0s.
    Rear clear at x_rear = 15,000m <=> x_front = 15,200m: t = (5000 + 200) / 25 = 208.0s.
    Post-clearance release delay = 5.0s -> TVS released at exactly t = 213.0s.
    """
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_release_delay_s=5.0)

    tvs = TVSSection(
        tvs_id="TVS_BENCH_B",
        tunnel_id="TUN_MAIN",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=10000.0, end_offset_m=15000.0)],
        release_delay_s=5.0,
    )
    tc.register_tvs_section(tvs, release_delay_s=5.0, auth_processing_delay_s=0.0)

    # 1. Authorize and Enter at t = 0.0s
    tc.request_tvs_entry("TR_BENCH_B", "TVS_BENCH_B", timestamp_s=0.0)
    tc.front_enter_tvs("TR_BENCH_B", "TVS_BENCH_B", timestamp_s=0.0)
    assert tc.configs["TVS_BENCH_B"].tvs.link_intervals[0].end_offset_m - tc.configs["TVS_BENCH_B"].tvs.link_intervals[0].start_offset_m == 5000.0

    # 2. Front exit at t = 200.0s
    tc.front_exit_tvs("TR_BENCH_B", "TVS_BENCH_B", timestamp_s=200.0)
    st = tc.train_states[("TR_BENCH_B", "TVS_BENCH_B")]
    assert st.front_exit_time_s == 200.0
    assert rc.get_resource("TVS_BENCH_B").is_occupied is True

    # 3. Rear clear at t = 208.0s
    target_rel = tc.rear_clear_tvs("TR_BENCH_B", "TVS_BENCH_B", timestamp_s=208.0)
    assert st.rear_clear_time_s == 208.0
    assert target_rel == 213.0

    # At t = 210.0s, release delay not expired
    rel_events_210 = tc.process_release_timers(current_time_s=210.0)
    assert len(rel_events_210) == 0
    assert rc.get_resource("TVS_BENCH_B").is_reserved is True

    # At t = 213.0s, release delay expires and TVS is released!
    rel_events_213 = tc.process_release_timers(current_time_s=213.0)
    assert len(rel_events_213) == 1
    assert rel_events_213[0].event_type == ResourceEventType.TVS_RELEASED
    assert rel_events_213[0].timestamp_s == 213.0
    assert rc.get_resource("TVS_BENCH_B").is_reserved is False
    assert rc.get_resource("TVS_BENCH_B").is_occupied is False


def test_p07_b027_prohibition_on_tvs_release_upon_front_exit():
    """P07-B027: Strict prohibition on TVS release upon front exit."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs = TVSSection(
        tvs_id="TVS_NO_EARLY_REL",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=2000.0)],
    )
    tc.register_tvs_section(tvs, auth_processing_delay_s=0.0)

    tc.request_tvs_entry("TR_FRONT", "TVS_NO_EARLY_REL", timestamp_s=0.0)
    tc.front_enter_tvs("TR_FRONT", "TVS_NO_EARLY_REL", timestamp_s=0.0)
    tc.front_exit_tvs("TR_FRONT", "TVS_NO_EARLY_REL", timestamp_s=80.0)

    # Must remain occupied and not released!
    res = rc.get_resource("TVS_NO_EARLY_REL")
    assert res.is_occupied is True
    assert "TR_FRONT" in res.occupants


def test_p07_b028_consecutive_tvs_dual_occupancy_benchmark_c():
    """P07-B028: Benchmark C - Consecutive TVS multi-section traversal and dual occupancy:

    TVS_A: 10,000m to 15,000m.
    TVS_B: 15,000m to 20,000m.
    Train length = 200m, constant speed = 25 m/s.
    At t = 200.0s, front reaches 15,000m -> enters TVS_B while rear is at 14,800m (in TVS_A).
    Dual occupancy: both TVS_A and TVS_B are simultaneously occupied from t = 200.0s to 208.0s!
    At t = 208.0s, rear clears TVS_A -> TVS_A enters release delay, released at 213.0s.
    TVS_B rear cleared at 408.0s, released at 413.0s.
    """
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_release_delay_s=5.0)

    tvs_a = TVSSection(
        tvs_id="TVS_A",
        tunnel_id="TUN_LONG",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=10000.0, end_offset_m=15000.0)],
        release_delay_s=5.0,
    )
    tvs_b = TVSSection(
        tvs_id="TVS_B",
        tunnel_id="TUN_LONG",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=15000.0, end_offset_m=20000.0)],
        release_delay_s=5.0,
    )
    tc.register_tvs_section(tvs_a, release_delay_s=5.0, auth_processing_delay_s=0.0)
    tc.register_tvs_section(tvs_b, release_delay_s=5.0, auth_processing_delay_s=0.0)

    # Train enters TVS_A at t = 0.0s
    tc.request_tvs_entry("TR_DUAL", "TVS_A", timestamp_s=0.0)
    tc.front_enter_tvs("TR_DUAL", "TVS_A", timestamp_s=0.0)

    # Advance to t = 200.0s: Front reaches boundary between TVS_A and TVS_B
    tc.request_tvs_entry("TR_DUAL", "TVS_B", timestamp_s=195.0)
    tc.front_enter_tvs("TR_DUAL", "TVS_B", timestamp_s=200.0)
    tc.front_exit_tvs("TR_DUAL", "TVS_A", timestamp_s=200.0)

    # Verify DUAL OCCUPANCY between t = 200.0s and t = 208.0s
    assert "TR_DUAL" in tc.active_occupants["TVS_A"]
    assert "TR_DUAL" in tc.active_occupants["TVS_B"]
    assert rc.get_resource("TVS_A").is_occupied is True
    assert rc.get_resource("TVS_B").is_occupied is True

    # At t = 208.0s: Train rear clears TVS_A
    tc.rear_clear_tvs("TR_DUAL", "TVS_A", timestamp_s=208.0)
    assert "TR_DUAL" not in tc.active_occupants["TVS_A"]
    assert "TR_DUAL" in tc.active_occupants["TVS_B"]

    # At t = 213.0s: TVS_A releases after 5s release delay
    tc.process_release_timers(current_time_s=213.0)
    assert rc.get_resource("TVS_A").is_occupied is False
    assert rc.get_resource("TVS_A").is_reserved is False
    # TVS_B remains occupied!
    assert rc.get_resource("TVS_B").is_occupied is True

    # At t = 400.0s: Front exits TVS_B
    tc.front_exit_tvs("TR_DUAL", "TVS_B", timestamp_s=400.0)
    # At t = 408.0s: Rear clears TVS_B
    tc.rear_clear_tvs("TR_DUAL", "TVS_B", timestamp_s=408.0)
    # At t = 413.0s: TVS_B releases
    tc.process_release_timers(current_time_s=413.0)
    assert rc.get_resource("TVS_B").is_occupied is False
    assert rc.get_resource("TVS_B").is_reserved is False


def test_p07_b029_cross_track_shared_tvs_group_benchmark_d():
    """P07-B029: Benchmark D - Cross-Track Shared TVS Group Mutual Exclusion:

    Parallel tracks TRK_01 and TRK_02 share single-bore TVS group G_SHARED_01.
    Train 1 enters on TRK_01.
    Train 2 requests TVS on TRK_02 -> denied authorization, MA clamped.
    """
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs_trk1 = TVSSection(
        tvs_id="TVS_SHARED_TRK1",
        tunnel_id="TUN_TWIN",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L_T1", start_offset_m=0.0, end_offset_m=3000.0)],
    )
    tvs_trk2 = TVSSection(
        tvs_id="TVS_SHARED_TRK2",
        tunnel_id="TUN_TWIN",
        track_id="TRK_02",
        link_intervals=[ResourceInterval(link_id="L_T2", start_offset_m=0.0, end_offset_m=3000.0)],
    )
    tc.register_tvs_section(tvs_trk1, auth_processing_delay_s=0.0)
    tc.register_tvs_section(tvs_trk2, auth_processing_delay_s=0.0)

    shared_group = SharedResourceGroup(
        group_id="G_SHARED_01",
        description="Shared single bore TVS group",
        resource_ids=["TVS_SHARED_TRK1", "TVS_SHARED_TRK2"],
    )
    tc.register_shared_group(shared_group)

    # Train 1 enters TVS on Track 1
    tc.request_tvs_entry("TR_1", "TVS_SHARED_TRK1", timestamp_s=0.0)
    tc.front_enter_tvs("TR_1", "TVS_SHARED_TRK1", timestamp_s=0.0)

    # Train 2 requests TVS on Track 2 at t = 20.0s -> REJECTED due to cross-track conflict
    ok2, auth_t2 = tc.request_tvs_entry("TR_2", "TVS_SHARED_TRK2", timestamp_s=20.0)
    assert ok2 is False
    assert auth_t2 is None

    # Train 2 MA is clamped
    clamped, is_cl = tc.clamp_movement_authority("TR_2", "TVS_SHARED_TRK2", 2000.0, 20.0, holding_point_distance_m=0.0)
    assert is_cl is True
    assert clamped == 0.0


def test_p07_b030_whole_tunnel_exclusivity():
    """P07-B030: Whole-tunnel exclusivity scope across all TVS sections of a tunnel."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs_1 = TVSSection(
        tvs_id="TVS_TUN1",
        tunnel_id="TUN_WHOLE",
        track_id="T1",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=2000.0)],
    )
    tvs_2 = TVSSection(
        tvs_id="TVS_TUN2",
        tunnel_id="TUN_WHOLE",
        track_id="T2",
        link_intervals=[ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=2000.0)],
    )
    tc.register_tvs_section(tvs_1, exclusivity_scope=TVSExclusivityScope.WHOLE_TUNNEL, auth_processing_delay_s=0.0)
    tc.register_tvs_section(tvs_2, exclusivity_scope=TVSExclusivityScope.WHOLE_TUNNEL, auth_processing_delay_s=0.0)

    tc.request_tvs_entry("TR_W1", "TVS_TUN1", timestamp_s=0.0)
    tc.front_enter_tvs("TR_W1", "TVS_TUN1", timestamp_s=0.0)

    # Another train requests TVS_TUN2 in same tunnel -> rejected under whole-tunnel exclusivity
    ok, _ = tc.request_tvs_entry("TR_W2", "TVS_TUN2", timestamp_s=10.0)
    assert ok is False


def test_p07_b031_reverse_direction_tvs_traversal():
    """P07-B031: Reverse-direction TVS traversal and boundary resolution."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_release_delay_s=4.0)

    tvs = TVSSection(
        tvs_id="TVS_REV",
        tunnel_id="TUN_REV",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=1000.0, end_offset_m=4000.0)],
        release_delay_s=4.0,
    )
    tc.register_tvs_section(tvs, release_delay_s=4.0, auth_processing_delay_s=1.0)

    # Train traveling in REVERSE
    ok, auth_t = tc.request_tvs_entry("TR_REV", "TVS_REV", timestamp_s=0.0, running_direction=RunningDirection.REVERSE)
    assert ok is True
    assert auth_t == 1.0

    tc.front_enter_tvs("TR_REV", "TVS_REV", timestamp_s=2.0, running_direction=RunningDirection.REVERSE)
    tc.front_exit_tvs("TR_REV", "TVS_REV", timestamp_s=120.0)
    tc.rear_clear_tvs("TR_REV", "TVS_REV", timestamp_s=128.0)
    tc.process_release_timers(current_time_s=132.1)

    assert rc.get_resource("TVS_REV").is_occupied is False


def test_p07_b032_tvs_safety_invariant_unauthorized_entry():
    """P07-B032: Safety invariant violation: unauthorized entry raises TVSInvariantError."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs = TVSSection(
        tvs_id="TVS_INV_1",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
    )
    tc.register_tvs_section(tvs)

    # Train attempts to front enter WITHOUT prior entry authorization
    with pytest.raises(TVSInvariantError) as exc_info:
        tc.front_enter_tvs("TR_BREACH", "TVS_INV_1", timestamp_s=10.0)
    assert "without valid entry authorization" in str(exc_info.value)


def test_p07_b033_tvs_safety_invariant_capacity_overload():
    """P07-B033: Safety invariant violation: exceeding N_max raises TVSInvariantError."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_auth_delay_s=0.0)

    tvs = TVSSection(
        tvs_id="TVS_INV_2",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
        max_train_occupancy=1,
    )
    tc.register_tvs_section(tvs)

    tc.request_tvs_entry("TR_1", "TVS_INV_2", timestamp_s=0.0)
    tc.front_enter_tvs("TR_1", "TVS_INV_2", timestamp_s=0.0)

    # Manually force authorization of second train and attempt entry
    tc.train_states[("TR_2", "TVS_INV_2")] = tc.train_states[("TR_1", "TVS_INV_2")]
    with pytest.raises(TVSInvariantError) as exc_info:
        tc.front_enter_tvs("TR_2", "TVS_INV_2", timestamp_s=5.0)
    assert "capacity 1 exceeded" in str(exc_info.value)


def test_p07_b034_signalling_ma_clamping_cross_technology():
    """P07-B034: Common Movement Authority clamping across Fixed-Block, ETCS L2, and CBTC."""
    sc = SignallingCoordinator(technology_type=SignallingTechnologyType.ETCS_LEVEL_2)

    tvs = TVSSection(
        tvs_id="TVS_ETCS",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=2000.0, end_offset_m=4000.0)],
    )
    sc.tvs_controller.register_tvs_section(tvs)

    # Create unconstrained ETCS MA extending to 3500m
    unconstrained_ma = MovementAuthority(
        ma_id="MA_ETCS_01",
        train_id="TR_ETCS",
        route_id="RT_01",
        start_reference=0.0,
        end_of_authority=3500.0,
        target_speed_ms=40.0,
        issue_time_s=0.0,
        effective_time_s=0.0,
        running_direction=RunningDirection.FORWARD,
    )

    # Holding point before TVS at 1950.0m
    clamped_ma = sc.clamp_ma_for_tvs(
        train_id="TR_ETCS",
        tvs_id="TVS_ETCS",
        ma=unconstrained_ma,
        current_time_s=0.0,
        holding_point_distance_m=1950.0,
    )
    assert clamped_ma.end_of_authority == 1950.0
    assert clamped_ma.target_speed_ms == 0.0

    # Once authorized, MA is unconstrained
    sc.tvs_controller.request_tvs_entry("TR_ETCS", "TVS_ETCS", timestamp_s=5.0)
    unclamped_ma = sc.clamp_ma_for_tvs(
        train_id="TR_ETCS",
        tvs_id="TVS_ETCS",
        ma=unconstrained_ma,
        current_time_s=7.0,
        holding_point_distance_m=1950.0,
    )
    assert unclamped_ma.end_of_authority == 3500.0


def test_p07_b035_complete_multi_train_corridor_traversal():
    """P07-B035: End-to-end corridor traversal integrating Station, Junction Merge, and TVS."""
    sc = SignallingCoordinator()

    # 1. Setup Station
    station = Station(station_id="STN_ORIGIN", name="Origin Terminal")
    sc.platform_controller.register_station(station)
    plat = Platform(
        platform_id="PLT_01",
        station_id="STN_ORIGIN",
        link_id="L_PLT",
        start_offset_m=0.0,
        end_offset_m=250.0,
        length_m=250.0,
    )
    sc.platform_controller.register_platform(plat, release_delay_s=2.0)

    # 2. Setup Junction
    sw = Switch(switch_id="SW_01", node_id="ND_01")
    sc.switch_controller.register_switch(sw)
    r_jnc = InterlockingRouteDefinition(
        route_id="RT_JNC_MAIN",
        entry_signal_id="S_PLT",
        exit_signal_id="S_TUNNEL",
        link_sequence=["L_PLT", "L_MAIN"],
        required_switch_positions={"SW_01": SwitchPosition.NORMAL},
    )
    sc.interlocking_engine.register_route(r_jnc)

    # 3. Setup TVS
    tvs = TVSSection(
        tvs_id="TVS_MAIN",
        tunnel_id="TUN_CORRIDOR",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L_MAIN", start_offset_m=500.0, end_offset_m=1500.0)],
        release_delay_s=3.0,
    )
    sc.tvs_controller.register_tvs_section(tvs, release_delay_s=3.0, auth_processing_delay_s=1.0)

    train_id = "TR_CORRIDOR"
    t = 0.0

    # Step A: Platform reservation and dwell
    sc.platform_controller.request_platform(train_id, "PLT_01", 160.0, timestamp_s=t)
    sc.platform_controller.front_enter_platform(train_id, "PLT_01", timestamp_s=t + 10.0)
    sc.platform_controller.start_dwell(train_id, "PLT_01", timestamp_s=t + 15.0, dwell_duration_s=30.0)
    sc.platform_controller.complete_dwell(train_id, "PLT_01", timestamp_s=t + 45.0)

    # Step B: Request Junction movement while departing platform
    lock_t = sc.junction_controller.request_junction_movement(train_id, "RT_JNC_MAIN", timestamp_s=t + 45.0)
    assert sc.interlocking_engine.active_states["RT_JNC_MAIN"].is_locked

    # Step C: Rear clear platform at t = 55.0s
    sc.platform_controller.rear_clear_platform(train_id, "PLT_01", timestamp_s=t + 55.0)
    sc.platform_controller.process_platform_releases(current_time_s=t + 58.0)
    assert sc.resource_controller.get_resource("PLT_01").is_occupied is False

    # Step D: Request TVS authorization
    ok, auth_eff = sc.tvs_controller.request_tvs_entry(train_id, "TVS_MAIN", timestamp_s=t + 55.0)
    assert ok is True
    assert auth_eff == 56.0

    # Step E: Enter TVS, clear junction, exit and release TVS
    sc.tvs_controller.front_enter_tvs(train_id, "TVS_MAIN", timestamp_s=t + 60.0)
    sc.junction_controller.clear_junction_zone(train_id, "JNC_ZONE", "RT_JNC_MAIN", timestamp_s=t + 65.0)
    sc.junction_controller.release_junction_route("RT_JNC_MAIN", train_id, timestamp_s=t + 65.0)

    sc.tvs_controller.front_exit_tvs(train_id, "TVS_MAIN", timestamp_s=t + 100.0)
    sc.tvs_controller.rear_clear_tvs(train_id, "TVS_MAIN", timestamp_s=t + 106.0)
    sc.tvs_controller.process_release_timers(current_time_s=t + 110.0)

    assert sc.resource_controller.get_resource("TVS_MAIN").is_occupied is False

    all_events = sc.get_all_events()
    assert len(all_events) > 10
