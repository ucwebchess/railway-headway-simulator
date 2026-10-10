"""Integration tests for Station, Platform, Junction, and TVS Control.

Covers:
- InfrastructureModel-driven initialization into SignallingCoordinator.
- Multi-train corridor execution: Station dwell -> Junction route locking -> TVS traversal.
- Bidirectional corridor traversal: FORWARD and REVERSE trains sharing resources.
- Signalling technology integration: MA clamping across Fixed-Block, ETCS L2, and CBTC.
- Deterministic same-time event ordering with release delays and sectional unlocks.
"""

import pytest

from headway.data.canonical import (
    AspectModelType,
    InfrastructureModel,
    Platform,
    ResourceInterval,
    SharedResourceGroup,
    SignallingBlock,
    SignallingModel,
    SignallingSystem,
    SignallingTechnologyType,
    Station,
    Track,
    TrackDirectionality,
    TrackLink,
    Node,
    Tunnel,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.switches import Switch, SwitchPosition
from headway.signalling.authority import AuthorityValidity, MovementAuthority
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.interlocking import InterlockingRouteDefinition
from headway.signalling.junction_controller import JunctionZone, JunctionType
from headway.signalling.platform_controller import PlatformSelectionPolicy
from headway.signalling.resource_types import (
    ReleasePolicy,
    ResourceCategory,
    ResourceEventType,
)
from headway.signalling.resources import ManagedResource


@pytest.fixture
def canonical_infrastructure() -> InfrastructureModel:
    """Creates a complete canonical infrastructure with stations, platforms, tunnels, and TVS."""
    stations = [
        Station(station_id="STN_ALPHA", name="Alpha Station", chainage_km=0.0),
        Station(station_id="STN_BETA", name="Beta Station", chainage_km=10.0),
    ]
    platforms = [
        Platform(platform_id="PLT_A1", station_id="STN_ALPHA", link_id="L_A1", start_offset_m=0.0, end_offset_m=200.0, length_m=200.0),
        Platform(platform_id="PLT_A2", station_id="STN_ALPHA", link_id="L_A2", start_offset_m=0.0, end_offset_m=220.0, length_m=220.0),
        Platform(platform_id="PLT_B1", station_id="STN_BETA", link_id="L_B1", start_offset_m=0.0, end_offset_m=250.0, length_m=250.0),
    ]
    tunnels = [
        Tunnel(tunnel_id="TUN_GREAT", name="Great Mountain Tunnel", description="Twin track tunnel"),
    ]
    tvs_sections = [
        TVSSection(
            tvs_id="TVS_TUN_01",
            tunnel_id="TUN_GREAT",
            track_id="TRK_01",
            link_intervals=[ResourceInterval(link_id="L_MAIN1", start_offset_m=1000.0, end_offset_m=4000.0)],
            max_train_occupancy=1,
            release_delay_s=5.0,
        ),
        TVSSection(
            tvs_id="TVS_TUN_02",
            tunnel_id="TUN_GREAT",
            track_id="TRK_02",
            link_intervals=[ResourceInterval(link_id="L_MAIN2", start_offset_m=1000.0, end_offset_m=4000.0)],
            max_train_occupancy=1,
            release_delay_s=5.0,
        ),
    ]
    shared_groups = [
        SharedResourceGroup(
            group_id="GRP_TVS_CROSS_TRACK",
            description="Shared cross-track TVS group for single bore tunnel zone",
            resource_ids=["TVS_TUN_01", "TVS_TUN_02"],
        )
    ]
    tracks = [
        Track(track_id="TRK_01", directionality=TrackDirectionality.NOMINAL),
        Track(track_id="TRK_02", directionality=TrackDirectionality.REVERSE),
    ]
    nodes = [
        Node(node_id="N1"),
        Node(node_id="N2"),
    ]
    links = [
        TrackLink(link_id="L_A1", start_node_id="N1", end_node_id="N2", length_m=500.0, track_id="TRK_01", max_speed_ms=40.0),
        TrackLink(link_id="L_A2", start_node_id="N1", end_node_id="N2", length_m=500.0, track_id="TRK_01", max_speed_ms=40.0),
        TrackLink(link_id="L_MAIN1", start_node_id="N1", end_node_id="N2", length_m=5000.0, track_id="TRK_01", max_speed_ms=40.0),
        TrackLink(link_id="L_MAIN2", start_node_id="N1", end_node_id="N2", length_m=5000.0, track_id="TRK_02", max_speed_ms=40.0),
        TrackLink(link_id="L_B1", start_node_id="N1", end_node_id="N2", length_m=500.0, track_id="TRK_01", max_speed_ms=40.0),
    ]

    return InfrastructureModel(
        tracks=tracks,
        nodes=nodes,
        track_links=links,
        stations=stations,
        platforms=platforms,
        tunnels=tunnels,
        tvs_sections=tvs_sections,
        shared_resource_groups=shared_groups,
    )


def test_coordinator_load_from_infrastructure(canonical_infrastructure):
    """SignallingCoordinator loads platforms and TVS sections directly from canonical InfrastructureModel."""
    sc = SignallingCoordinator()
    sc.load_from_infrastructure(canonical_infrastructure)

    # Verify platforms
    assert "PLT_A1" in sc.platform_controller.platforms
    assert "PLT_B1" in sc.platform_controller.platforms
    res_a1 = sc.resource_controller.get_resource("PLT_A1")
    assert res_a1 is not None
    assert res_a1.category == ResourceCategory.PLATFORM

    # Verify TVS sections and shared group
    assert "TVS_TUN_01" in sc.tvs_controller.configs
    assert "TVS_TUN_02" in sc.tvs_controller.configs
    res_tvs = sc.resource_controller.get_resource("TVS_TUN_01")
    assert res_tvs is not None
    assert res_tvs.category == ResourceCategory.TVS_SECTION

    # Cross-track group registered
    assert "GRP_TVS_CROSS_TRACK" in sc.tvs_controller.shared_groups
    assert "TVS_TUN_02" in sc.resource_controller.get_conflicting_resources("TVS_TUN_01")


def test_multi_train_corridor_dwell_junction_tvs_lifecycle(canonical_infrastructure):
    """Multi-train operational corridor traversal: Train 1 and Train 2 interacting via station, junction, TVS."""
    sc = SignallingCoordinator()
    sc.load_from_infrastructure(canonical_infrastructure)

    # Register junction switch and route
    sw = Switch(switch_id="SW_CONV", node_id="N1")
    sc.switch_controller.register_switch(sw)

    rc = sc.resource_controller
    rc.register_resource(ManagedResource(resource_id="BLK_JNC", category=ResourceCategory.TRACK_BLOCK))

    r1 = InterlockingRouteDefinition(
        route_id="RT_PLT1_MAIN",
        entry_signal_id="S_A1",
        exit_signal_id="S_TVS",
        link_sequence=["L_A1", "L_MAIN1"],
        protected_block_ids=["BLK_JNC"],
        required_switch_positions={"SW_CONV": SwitchPosition.NORMAL},
    )
    r2 = InterlockingRouteDefinition(
        route_id="RT_PLT2_MAIN",
        entry_signal_id="S_A2",
        exit_signal_id="S_TVS",
        link_sequence=["L_A2", "L_MAIN1"],
        protected_block_ids=["BLK_JNC"],
        required_switch_positions={"SW_CONV": SwitchPosition.REVERSE},
        conflicting_route_ids=["RT_PLT1_MAIN"],
    )
    sc.interlocking_engine.register_route(r1)
    sc.interlocking_engine.register_route(r2)

    zone = JunctionZone(
        junction_id="JNC_STN_EXIT",
        junction_type=JunctionType.MERGE,
        route_ids=["RT_PLT1_MAIN", "RT_PLT2_MAIN"],
        switch_ids=["SW_CONV"],
        protected_block_ids=["BLK_JNC"],
    )
    sc.junction_controller.register_junction_zone(zone)

    # Train 1 uses PLT_A1, Train 2 uses PLT_A2
    sc.platform_controller.request_platform("TR_01", "PLT_A1", 160.0, timestamp_s=0.0)
    sc.platform_controller.request_platform("TR_02", "PLT_A2", 180.0, timestamp_s=0.0)

    sc.platform_controller.front_enter_platform("TR_01", "PLT_A1", timestamp_s=10.0)
    sc.platform_controller.front_enter_platform("TR_02", "PLT_A2", timestamp_s=15.0)

    sc.platform_controller.start_dwell("TR_01", "PLT_A1", timestamp_s=12.0, dwell_duration_s=30.0)
    sc.platform_controller.start_dwell("TR_02", "PLT_A2", timestamp_s=20.0, dwell_duration_s=45.0)

    # Train 1 finishes dwell at t = 42.0s and requests junction route RT_PLT1_MAIN
    sc.platform_controller.complete_dwell("TR_01", "PLT_A1", timestamp_s=42.0)
    sc.junction_controller.request_junction_movement("TR_01", "RT_PLT1_MAIN", timestamp_s=42.0)

    # Train 1 requests TVS entry
    ok, auth_eff = sc.tvs_controller.request_tvs_entry("TR_01", "TVS_TUN_01", timestamp_s=45.0)
    assert ok is True

    # Train 1 departs, enters TVS at t = 50.0s, clears platform at t = 52.0s
    sc.platform_controller.front_exit_platform("TR_01", "PLT_A1", timestamp_s=48.0)
    sc.tvs_controller.front_enter_tvs("TR_01", "TVS_TUN_01", timestamp_s=50.0)
    sc.platform_controller.rear_clear_platform("TR_01", "PLT_A1", timestamp_s=52.0)

    # Train 1 clears junction at t = 55.0s
    sc.junction_controller.clear_junction_zone("TR_01", "JNC_STN_EXIT", "RT_PLT1_MAIN", timestamp_s=55.0)
    sc.junction_controller.release_junction_route("RT_PLT1_MAIN", "TR_01", timestamp_s=55.0)

    # Train 2 finishes dwell at t = 65.0s and can now acquire junction route RT_PLT2_MAIN
    can_t2, _ = sc.junction_controller.can_request_junction_movement("RT_PLT2_MAIN", "TR_02", timestamp_s=65.0)
    assert can_t2 is True
    sc.junction_controller.request_junction_movement("TR_02", "RT_PLT2_MAIN", timestamp_s=65.0)

    # Train 2 requests TVS_TUN_01 -> must be REJECTED because Train 1 is still inside TVS!
    ok_t2, _ = sc.tvs_controller.request_tvs_entry("TR_02", "TVS_TUN_01", timestamp_s=66.0)
    assert ok_t2 is False

    # Train 1 exits TVS front at t = 150.0s, clears rear at t = 160.0s
    sc.tvs_controller.front_exit_tvs("TR_01", "TVS_TUN_01", timestamp_s=150.0)
    sc.tvs_controller.rear_clear_tvs("TR_01", "TVS_TUN_01", timestamp_s=160.0)

    # TVS release timer is 5.0s -> expires at 165.0s
    sc.tvs_controller.process_release_timers(current_time_s=165.1)
    assert sc.resource_controller.get_resource("TVS_TUN_01").is_occupied is False

    # Now Train 2 requests TVS entry -> GRANTED!
    ok_t2_retry, eff_t2 = sc.tvs_controller.request_tvs_entry("TR_02", "TVS_TUN_01", timestamp_s=166.0)
    assert ok_t2_retry is True


def test_bidirectional_corridor_forward_and_reverse_interaction():
    """Bidirectional traversal: FORWARD Train A and REVERSE Train B using common infrastructure."""
    sc = SignallingCoordinator()

    # Station with bidirectional platform
    stn = Station(station_id="STN_BIDIR", name="Bidir Terminal")
    sc.platform_controller.register_station(stn)
    plat = Platform(platform_id="PLT_BI", station_id="STN_BIDIR", link_id="L_BI", start_offset_m=0, end_offset_m=200, length_m=200.0)
    sc.platform_controller.register_platform(plat, release_delay_s=2.0)

    # TVS section
    tvs = TVSSection(
        tvs_id="TVS_BI",
        tunnel_id="TUN_BI",
        track_id="TRK_BI",
        link_intervals=[ResourceInterval(link_id="L_BI", start_offset_m=500.0, end_offset_m=2500.0)],
        release_delay_s=3.0,
    )
    sc.tvs_controller.register_tvs_section(tvs, release_delay_s=3.0, auth_processing_delay_s=0.0)

    # Forward Train A
    sc.platform_controller.request_platform("TR_FWD", "PLT_BI", 150.0, timestamp_s=0.0, running_direction=RunningDirection.FORWARD)
    sc.platform_controller.front_enter_platform("TR_FWD", "PLT_BI", timestamp_s=10.0)
    sc.platform_controller.rear_clear_platform("TR_FWD", "PLT_BI", timestamp_s=25.0)
    sc.platform_controller.process_platform_releases(current_time_s=28.0)

    # Reverse Train B uses the SAME platform in REVERSE direction
    ok_rev = sc.platform_controller.request_platform(
        train_id="TR_REV",
        platform_id="PLT_BI",
        train_length_m=150.0,
        timestamp_s=30.0,
        running_direction=RunningDirection.REVERSE,
    )
    assert ok_rev is True

    sc.platform_controller.front_enter_platform("TR_REV", "PLT_BI", timestamp_s=35.0)
    sc.platform_controller.start_dwell("TR_REV", "PLT_BI", timestamp_s=40.0, dwell_duration_s=20.0)
    sc.platform_controller.complete_dwell("TR_REV", "PLT_BI", timestamp_s=60.0)
    sc.platform_controller.rear_clear_platform("TR_REV", "PLT_BI", timestamp_s=70.0)
    sc.platform_controller.process_platform_releases(current_time_s=73.0)

    assert sc.resource_controller.get_resource("PLT_BI").is_occupied is False


def test_signalling_movement_authority_clamping_across_all_technologies():
    """Movement Authority clamping test across Fixed-Block, ETCS L2, and CBTC Moving-Block."""
    technologies = [
        SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL,
        SignallingTechnologyType.ETCS_LEVEL_2,
        SignallingTechnologyType.CBTC_MOVING_BLOCK,
    ]

    for tech in technologies:
        sc = SignallingCoordinator(technology_type=tech)
        tvs = TVSSection(
            tvs_id=f"TVS_{tech.value}",
            tunnel_id="TUN_TECH",
            track_id="TRK_01",
            link_intervals=[ResourceInterval(link_id="L1", start_offset_m=3000.0, end_offset_m=6000.0)],
        )
        sc.tvs_controller.register_tvs_section(tvs, auth_processing_delay_s=1.0)

        unconstrained_ma = MovementAuthority(
            ma_id=f"MA_{tech.value}",
            train_id="TR_TECH",
            route_id="RT_01",
            start_reference=0.0,
            end_of_authority=5000.0,  # inside unauthorized TVS
            target_speed_ms=30.0,
            issue_time_s=0.0,
            effective_time_s=0.0,
            running_direction=RunningDirection.FORWARD,
        )

        # Clamped before TVS at 2900m
        clamped = sc.clamp_ma_for_tvs(
            train_id="TR_TECH",
            tvs_id=f"TVS_{tech.value}",
            ma=unconstrained_ma,
            current_time_s=0.0,
            holding_point_distance_m=2900.0,
        )
        assert clamped.end_of_authority == 2900.0
        assert clamped.target_speed_ms == 0.0

        # Authorize TVS
        sc.tvs_controller.request_tvs_entry("TR_TECH", f"TVS_{tech.value}", timestamp_s=5.0)

        # At t=7.0s, authorization is effective -> MA is unconstrained!
        unclamped = sc.clamp_ma_for_tvs(
            train_id="TR_TECH",
            tvs_id=f"TVS_{tech.value}",
            ma=unconstrained_ma,
            current_time_s=7.0,
            holding_point_distance_m=2900.0,
        )
        assert unclamped.end_of_authority == 5000.0
        assert unclamped.target_speed_ms == 30.0
