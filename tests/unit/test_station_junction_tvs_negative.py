"""Negative and fault injection tests for Station, Platform, Junction, and TVS Control.

Covers:
- Unknown station/platform identity rejection.
- Platform length overflow and incompatibility errors.
- Allocation failures when no compatible platform is free.
- Conflicting junction moves raising JunctionConflictError.
- Unauthorized TVS section breach raising TVSInvariantError.
- Over-capacity TVS entry breach raising TVSInvariantError.
- Shared TVS group and whole-tunnel exclusivity violations.
- Post-clearance delay timer boundary rejections.
"""

import pytest

from headway.data.canonical import (
    Platform,
    ResourceInterval,
    SharedResourceGroup,
    Station,
    TrackDirectionality,
    Tunnel,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.switches import Switch, SwitchPosition
from headway.signalling.interlocking import InterlockingEngine, InterlockingRouteDefinition
from headway.signalling.junction_controller import JunctionController, JunctionType, JunctionZone
from headway.signalling.platform_controller import (
    PlatformController,
    PlatformSelectionPolicy,
)
from headway.signalling.residual_occupation import ResidualOccupationDetector
from headway.signalling.resource_types import (
    JunctionConflictError,
    PlatformCompatibilityError,
    ReleasePolicy,
    ResourceCategory,
    StationResourceError,
    TVSAuthorizationError,
    TVSInvariantError,
)
from headway.signalling.resources import ManagedResource, ResourceController
from headway.signalling.switches import SwitchController
from headway.signalling.tvs_controller import (
    TVSController,
    TVSExclusivityScope,
)


# ==============================================================================
# Station & Platform Negative Tests
# ==============================================================================


def test_request_unknown_platform_raises_compatibility_error():
    """Requesting or validating an unregistered platform raises PlatformCompatibilityError."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    with pytest.raises(PlatformCompatibilityError) as exc_info:
        pc.validate_platform_compatibility("NON_EXISTENT_PLT", train_length_m=100.0)
    assert "does not exist" in str(exc_info.value)


def test_platform_length_overflow_raises_compatibility_error():
    """Train longer than platform usable length raises PlatformCompatibilityError."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    plat = Platform(
        platform_id="PLT_SHORT",
        station_id="STN_A",
        link_id="L1",
        start_offset_m=0.0,
        end_offset_m=150.0,
        length_m=150.0,
    )
    pc.register_platform(plat)

    with pytest.raises(PlatformCompatibilityError) as exc_info:
        pc.validate_platform_compatibility("PLT_SHORT", train_length_m=200.0)
    assert "exceeds usable platform length" in str(exc_info.value)
    assert exc_info.value.context["train_length_m"] == 200.0
    assert exc_info.value.context["platform_length_m"] == 150.0


def test_platform_allocation_empty_station_raises_error():
    """Attempting platform allocation on a station with no platforms raises StationResourceError."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    with pytest.raises(StationResourceError) as exc_info:
        pc.allocate_platform("TR_01", "STN_EMPTY", train_length_m=100.0, timestamp_s=0.0)
    assert "has no registered platforms" in str(exc_info.value)


def test_platform_fixed_allocation_without_preferred_raises_error():
    """FIXED_ASSIGNMENT policy without preferred_platform_id raises PlatformCompatibilityError."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    stn = Station(station_id="STN_01", name="Stn 01")
    pc.register_station(stn)
    p = Platform(platform_id="P1", station_id="STN_01", link_id="L1", start_offset_m=0, end_offset_m=200, length_m=200.0)
    pc.register_platform(p)

    with pytest.raises(PlatformCompatibilityError) as exc_info:
        pc.allocate_platform(
            "TR_01",
            "STN_01",
            train_length_m=100.0,
            timestamp_s=0.0,
            preferred_platform_id=None,
            policy=PlatformSelectionPolicy.FIXED_ASSIGNMENT,
        )
    assert "Fixed assignment policy requires preferred_platform_id" in str(exc_info.value)


def test_platform_allocation_all_occupied_raises_error():
    """When all compatible platforms are occupied, allocation raises PlatformCompatibilityError."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc)

    stn = Station(station_id="STN_FULL", name="Full Stn")
    pc.register_station(stn)
    p1 = Platform(platform_id="P1", station_id="STN_FULL", link_id="L1", start_offset_m=0, end_offset_m=200, length_m=200.0)
    pc.register_platform(p1)

    # Train 1 reserves P1
    pc.request_platform("TR_1", "P1", 100.0, timestamp_s=0.0)

    # Train 2 attempts allocation
    with pytest.raises(PlatformCompatibilityError) as exc_info:
        pc.allocate_platform(
            train_id="TR_2",
            station_id="STN_FULL",
            train_length_m=100.0,
            timestamp_s=5.0,
            policy=PlatformSelectionPolicy.EARLIEST_FEASIBLE,
        )
    assert "No compatible or available platform found" in str(exc_info.value)


def test_platform_cannot_reserve_during_release_delay():
    """Platform cannot be reserved while still under post-clearance release delay."""
    rc = ResourceController()
    pc = PlatformController(resource_controller=rc, default_release_delay_s=5.0)

    plat = Platform(platform_id="PLT_DEL", station_id="STN_1", link_id="L1", start_offset_m=0, end_offset_m=200, length_m=200.0)
    pc.register_platform(plat, release_delay_s=5.0)

    pc.request_platform("TR_1", "PLT_DEL", 100.0, timestamp_s=0.0)
    pc.front_enter_platform("TR_1", "PLT_DEL", timestamp_s=10.0)
    pc.rear_clear_platform("TR_1", "PLT_DEL", timestamp_s=30.0)

    # At t=32.0s (delay = 5s, release target = 35s), reservation by Train 2 must be rejected
    ok = pc.request_platform("TR_2", "PLT_DEL", 100.0, timestamp_s=32.0)
    assert ok is False


# ==============================================================================
# Residual Rear Occupation Negative Tests
# ==============================================================================


def test_residual_rear_occupation_non_positive_acceleration():
    """Non-positive acceleration in departure clearance returns 0.0 moving clearance time."""
    detector = ResidualOccupationDetector()
    rec = detector.detect_residual_rear_infringement(
        train_id="TR_01",
        train_length_m=200.0,
        front_stopping_offset_m=1000.0,
        platform_id="PLT_01",
        platform_entry_boundary_offset_m=850.0,
        upstream_resource_id="BLK_01",
        dwell_duration_s=60.0,
        post_departure_accel_ms2=0.0,
    )
    assert rec.is_infringing is True
    assert rec.calculate_departure_clearance_time_s(acceleration_ms2=0.0) == 0.0
    assert rec.calculate_departure_clearance_time_s(acceleration_ms2=-0.5) == 0.0


# ==============================================================================
# Junction Negative Tests
# ==============================================================================


def test_junction_conflicting_route_lock_rejection():
    """Attempting to lock a junction route when a conflicting route is active raises JunctionConflictError."""
    rc = ResourceController()
    sc = SwitchController()
    ie = InterlockingEngine(resource_controller=rc, switch_controller=sc)
    jc = JunctionController(interlocking_engine=ie, switch_controller=sc, resource_controller=rc)

    r1 = InterlockingRouteDefinition(
        route_id="RT_A", entry_signal_id="S1", exit_signal_id="S2", link_sequence=["L1"], conflicting_route_ids=["RT_B"]
    )
    r2 = InterlockingRouteDefinition(
        route_id="RT_B", entry_signal_id="S3", exit_signal_id="S4", link_sequence=["L2"], conflicting_route_ids=["RT_A"]
    )
    ie.register_route(r1)
    ie.register_route(r2)

    jc.request_junction_movement("TR_1", "RT_A", timestamp_s=0.0)

    with pytest.raises(JunctionConflictError) as exc_info:
        jc.request_junction_movement("TR_2", "RT_B", timestamp_s=2.0)
    assert "Cannot lock junction route 'RT_B'" in str(exc_info.value)
    assert exc_info.value.context["train_id"] == "TR_2"
    assert exc_info.value.context["route_id"] == "RT_B"


# ==============================================================================
# TVS Negative & Safety Invariant Tests
# ==============================================================================


def test_tvs_request_unknown_section_raises_error():
    """Requesting entry for unregistered TVS section raises TVSAuthorizationError."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    with pytest.raises(TVSAuthorizationError) as exc_info:
        tc.request_tvs_entry("TR_01", "NON_EXISTENT_TVS", timestamp_s=0.0)
    assert "not found" in str(exc_info.value)


def test_tvs_unauthorized_physical_entry_raises_invariant_error():
    """Train breaching TVS boundary without prior entry authorization raises TVSInvariantError."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs = TVSSection(
        tvs_id="TVS_SECURE",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
    )
    tc.register_tvs_section(tvs)

    with pytest.raises(TVSInvariantError) as exc_info:
        tc.front_enter_tvs("TR_INTRUDER", "TVS_SECURE", timestamp_s=5.0)
    assert "without valid entry authorization" in str(exc_info.value)
    assert exc_info.value.context["train_id"] == "TR_INTRUDER"


def test_tvs_capacity_exceeded_raises_invariant_error():
    """Forcing a second train into TVS section when N_max=1 raises TVSInvariantError."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_auth_delay_s=0.0)

    tvs = TVSSection(
        tvs_id="TVS_CAP_1",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
        max_train_occupancy=1,
    )
    tc.register_tvs_section(tvs)

    tc.request_tvs_entry("TR_A", "TVS_CAP_1", timestamp_s=0.0)
    tc.front_enter_tvs("TR_A", "TVS_CAP_1", timestamp_s=0.0)

    # Force artificial authorization state for second train
    tc.train_states[("TR_B", "TVS_CAP_1")] = tc.train_states[("TR_A", "TVS_CAP_1")]

    with pytest.raises(TVSInvariantError) as exc_info:
        tc.front_enter_tvs("TR_B", "TVS_CAP_1", timestamp_s=10.0)
    assert "capacity 1 exceeded" in str(exc_info.value)


def test_tvs_cannot_authorize_during_release_delay():
    """TVS section under post-clearance release delay rejects new authorization requests."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc, default_release_delay_s=5.0)

    tvs = TVSSection(
        tvs_id="TVS_REL_DLY",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
        release_delay_s=5.0,
    )
    tc.register_tvs_section(tvs, release_delay_s=5.0, auth_processing_delay_s=0.0)

    tc.request_tvs_entry("TR_1", "TVS_REL_DLY", timestamp_s=0.0)
    tc.front_enter_tvs("TR_1", "TVS_REL_DLY", timestamp_s=0.0)
    tc.front_exit_tvs("TR_1", "TVS_REL_DLY", timestamp_s=50.0)
    tc.rear_clear_tvs("TR_1", "TVS_REL_DLY", timestamp_s=60.0)

    # At t=62.0s, release timer (target=65.0s) has not expired -> Train 2 rejected
    ok, auth_t = tc.request_tvs_entry("TR_2", "TVS_REL_DLY", timestamp_s=62.0)
    assert ok is False
    assert auth_t is None


def test_tvs_shared_group_cross_track_rejection():
    """Shared TVS group across tracks rejects simultaneous entry requests."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    t1 = TVSSection(tvs_id="TVS_T1", tunnel_id="TUN_1", track_id="T1", link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0, end_offset_m=1000)])
    t2 = TVSSection(tvs_id="TVS_T2", tunnel_id="TUN_1", track_id="T2", link_intervals=[ResourceInterval(link_id="L2", start_offset_m=0, end_offset_m=1000)])
    tc.register_tvs_section(t1, auth_processing_delay_s=0.0)
    tc.register_tvs_section(t2, auth_processing_delay_s=0.0)

    grp = SharedResourceGroup(group_id="GRP_SHARED", resource_ids=["TVS_T1", "TVS_T2"])
    tc.register_shared_group(grp)

    # Train 1 occupies Track 1
    tc.request_tvs_entry("TR_1", "TVS_T1", timestamp_s=0.0)
    tc.front_enter_tvs("TR_1", "TVS_T1", timestamp_s=0.0)

    # Train 2 on Track 2 rejected
    ok, _ = tc.request_tvs_entry("TR_2", "TVS_T2", timestamp_s=10.0)
    assert ok is False


def test_tvs_safety_invariants_verification_method():
    """TVSController.verify_safety_invariants detects and raises on illegal states."""
    rc = ResourceController()
    tc = TVSController(resource_controller=rc)

    tvs = TVSSection(
        tvs_id="TVS_VERIFY",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)],
        max_train_occupancy=1,
    )
    tc.register_tvs_section(tvs)

    # Valid empty state passes
    tc.verify_safety_invariants(current_time_s=0.0)

    # Invalidate by inserting unauthorized occupant
    tc.active_occupants["TVS_VERIFY"].add("TR_GHOST")
    with pytest.raises(TVSInvariantError) as exc_info:
        tc.verify_safety_invariants(current_time_s=1.0)
    assert "occupying TVS 'TVS_VERIFY' without authorization" in str(exc_info.value)
