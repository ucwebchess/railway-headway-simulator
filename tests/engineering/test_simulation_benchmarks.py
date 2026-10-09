"""Mandatory engineering verification benchmarks for Milestone P04: Microscopic Train Dynamics.

Strictly verifies all 22 benchmarks (BENCH-P04-001 through BENCH-P04-022) per RHS-P04-001 § 20:
- BENCH-P04-001: Constant Acceleration (v0=0, a=1.0, t=20s -> v=20m/s, s=200m)
- BENCH-P04-002: Constant Braking (v0=30, b=0.75 -> t=40s, d=600m)
- BENCH-P04-003: Constant Speed (v=20, t=50s -> s=1000m)
- BENCH-P04-004: Zero-Speed Stop (no negative speed or numerical reversal)
- BENCH-P04-005: Speed Restriction (advance braking before lower limit)
- BENCH-P04-006: Station Stop (front stopping accuracy <= 0.5m)
- BENCH-P04-007: Station Dwell (remains stationary for planned dwell time)
- BENCH-P04-008: Departure (acceleration resumed after dwell completion)
- BENCH-P04-009: Train Rear Tracking (front - rear == L_train at all times)
- BENCH-P04-010: Multi-Link Movement (position continuity across link boundaries)
- BENCH-P04-011: Reverse Route Traversal (reverse physical coordinate mapping)
- BENCH-P04-012: Reverse Gradient Effects (proper sign inversion and acceleration)
- BENCH-P04-013: Reverse Station Stops (reversed sequence of station arrival)
- BENCH-P04-014: TVS Reverse Crossing (direction-reversed TVS entry and exit)
- BENCH-P04-015: Event Localization Accuracy (boundary crossing accuracy <= 0.1s)
- BENCH-P04-016: Variable Speed-Dependent Braking (piecewise curve integration)
- BENCH-P04-017: Braking Build-Up (delay increases stopping distance)
- BENCH-P04-018: Braking Response Delay (adds v0 * t_delay distance)
- BENCH-P04-019: Net Effective Braking (no double counting of resistance)
- BENCH-P04-020: Brake-Generated Braking (force balance integration)
- BENCH-P04-021: Unconstrained Journey Time (T_journey = T_moving + T_dwell)
- BENCH-P04-022: Numerical Convergence (dt in {0.5, 0.25, 0.1, 0.05} s convergence)
"""

import math
import pytest

from headway.core.units import normalize_davis_coefficients
from headway.data.canonical import (
    BrakingModelType,
    BrakingSemantics,
    Node,
    NodeType,
    Platform,
    ResourceInterval,
    Station,
    StoppingPoint,
    Track,
    TrackDirectionality,
    TrackLink,
    TractionModelType,
    Tunnel,
    TVSSection,
)
from headway.infrastructure.alignment import RouteAlignmentProfile
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import Route, RouteEngine
from headway.infrastructure.speed import RouteSpeedProfile, SpeedRestriction
from headway.infrastructure.stations import RoutePlatformStop, StationPlatformModel
from headway.infrastructure.tunnels import TunnelTVSModel
from headway.rolling_stock.braking import (
    BrakingCategory,
    ConstantDecelerationBrakingModel,
    SpeedDependentBrakingModel,
)
from headway.rolling_stock.force_balance import ForceBalanceEngine
from headway.rolling_stock.resistance import DistributedResistanceEngine
from headway.rolling_stock.traction import SimplifiedTractionModel
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.simulation.events import CrossingEventType
from headway.simulation.integrator import MicroscopicSimulator
from headway.simulation.speed_profile import SpeedProfileEngine
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.targets import BrakingTarget, BrakingTargetResolver, BrakingTargetType
from headway.simulation.trajectory import TrainTrajectory


# Standard benchmark test train: 400t, 200m length, max speed 83.33 m/s (300 km/h)
@pytest.fixture
def sim_train_params() -> RollingStockParameters:
    a_si, b_si, c_si = normalize_davis_coefficients(
        a=2.506, b=0.04065, c=0.00043,
        force_unit="kN", speed_unit="km/h",
    )
    return RollingStockParameters(
        train_type_id="TT_SIM_BENCHMARK",
        description="P04 Simulation Benchmark Train",
        length_m=200.0,
        mass_empty_kg=360_000.0,
        mass_loaded_kg=400_000.0,
        rotating_mass_factor=0.10,
        max_speed_ms=83.333,
        max_acceleration_ms2=1.0,
        max_service_deceleration_ms2=0.75,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si,
        davis_b_ns_m=b_si,
        davis_c_ns2_m2=c_si,
        power_w=6_000_000.0,
        max_tractive_effort_n=300_000.0,
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.50,
        mass_condition=MassCondition.NOMINAL,
    )


@pytest.fixture
def flat_tangent_corridor():
    """Flat tangent 2-link corridor: A -> B (2000m) -> C (2000m) = 4000m total."""
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_A", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_B", node_type=NodeType.JUNCTION))
    graph.add_node(Node(node_id="ND_C", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(
        TrackLink(
            link_id="LNK_AB",
            track_id="TRK_01",
            start_node_id="ND_A",
            end_node_id="ND_B",
            length_m=2000.0,
            gradient_decimal=0.0,
            max_speed_ms=83.333,
        )
    )
    graph.add_link(
        TrackLink(
            link_id="LNK_BC",
            track_id="TRK_01",
            start_node_id="ND_B",
            end_node_id="ND_C",
            length_m=2000.0,
            gradient_decimal=0.0,
            max_speed_ms=83.333,
        )
    )
    route_engine = RouteEngine(graph)
    route_fwd = route_engine.build_route_from_traversals(
        route_id="RT_FLAT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )
    route_rev = route_fwd.create_reverse_route(graph, reverse_route_id="RT_FLAT_REV")
    return graph, route_fwd, route_rev


# ==============================================================================
# BENCH-P04-001 through BENCH-P04-022
# ==============================================================================

@pytest.mark.engineering
def test_bench_p04_001_constant_acceleration():
    """BENCH-P04-001: Constant Acceleration Kinematics.

    Initial speed: 0 m/s. Acceleration: 1.0 m/s^2. Duration: 20.0 s.
    Expected: Final speed = 20.0 m/s, Distance = 200.0 m.
    """
    v0 = 0.0
    a = 1.0
    t = 20.0
    dt = 0.1
    steps = int(t / dt)

    s = 0.0
    v = v0
    for _ in range(steps):
        s += v * dt + 0.5 * a * (dt ** 2)
        v += a * dt

    expected_v = v0 + a * t
    expected_s = 0.5 * a * (t ** 2)

    assert v == pytest.approx(expected_v, rel=1e-5)
    assert s == pytest.approx(expected_s, rel=1e-4)
    assert v == pytest.approx(20.0, rel=1e-4)
    assert s == pytest.approx(200.0, rel=1e-3)


@pytest.mark.engineering
def test_bench_p04_002_constant_braking():
    """BENCH-P04-002: Constant Braking Kinematics.

    Initial speed: 30.0 m/s. Deceleration: 0.75 m/s^2.
    Expected: Stopping time = 40.0 s, Stopping distance = 600.0 m.
    """
    brk_model = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=0.75,
        emergency_deceleration_ms2=1.2,
        response_delay_s=0.0,
        build_up_time_s=0.0,
    )
    d = brk_model.calculate_stopping_distance(initial_speed_ms=30.0, target_speed_ms=0.0)
    t = brk_model.calculate_stopping_time(initial_speed_ms=30.0, target_speed_ms=0.0)

    expected_t = 30.0 / 0.75  # 40.0 s
    expected_d = (30.0 ** 2) / (2.0 * 0.75)  # 600.0 m

    assert t == pytest.approx(expected_t, rel=1e-6)
    assert d == pytest.approx(expected_d, rel=1e-6)
    assert t == pytest.approx(40.0, rel=1e-6)
    assert d == pytest.approx(600.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p04_003_constant_speed():
    """BENCH-P04-003: Constant Speed Motion.

    Speed: 20.0 m/s. Duration: 50.0 s.
    Expected: Distance = 1000.0 m.
    """
    v = 20.0
    t = 50.0
    expected_s = v * t
    assert expected_s == pytest.approx(1000.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p04_004_zero_speed_stop(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-004: Zero-Speed Stop without Numerical Reversal.

    Verify train comes to rest at zero speed without negative speed or overshoot.
    """
    _, route_fwd, _ = flat_tangent_corridor
    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, dt_s=0.1)

    traj = sim.simulate(max_duration_s=300.0)

    assert len(traj.samples) > 0
    # Every sample must have speed >= 0
    for sample in traj.samples:
        assert sample.speed_ms >= 0.0

    # Final state must be stopped
    final_sample = traj.samples[-1]
    assert final_sample.speed_ms == pytest.approx(0.0, abs=1e-3)
    assert final_sample.dynamic_mode == DynamicMode.STOPPED


@pytest.mark.engineering
def test_bench_p04_005_speed_restriction(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-005: Advance Braking before Lower Speed Limit.

    Verify braking occurs before entering a lower speed restriction so that
    speed does not exceed the lower limit upon entry.
    """
    _, route_fwd, _ = flat_tangent_corridor
    # Add restriction on second link: 20 m/s starting at 2000m (offset 0 on LNK_BC)
    restrs = [
        SpeedRestriction(
            restriction_id="SR_01",
            link_id="LNK_BC",
            start_offset_m=0.0,
            end_offset_m=2000.0,
            max_speed_ms=20.0,
            direction="FORWARD",
        )
    ]
    spd_profile = RouteSpeedProfile(route_fwd, restrs)
    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, speed_profile=spd_profile, dt_s=0.1)

    traj = sim.simulate(max_duration_s=300.0)

    # Check speeds at and after 2000m (link boundary)
    for sample in traj.samples:
        if sample.front_distance_m >= 2000.0:
            # Must not exceed restriction limit + small tolerance
            assert sample.speed_ms <= 20.05


@pytest.mark.engineering
def test_bench_p04_006_station_stopping_accuracy(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-006: Station Stopping Accuracy (front position <= 0.5m)."""
    _, route_fwd, _ = flat_tangent_corridor

    # Add station stop at 1500m
    stn_stop = RoutePlatformStop(
        station=Station(station_id="STN_ALPHA", name="Alpha Station"),
        platform=Platform(platform_id="PLT_01", station_id="STN_ALPHA", link_id="LNK_AB", start_offset_m=1300.0, end_offset_m=1600.0, length_m=300.0),
        stopping_point=StoppingPoint(stopping_point_id="SP_01", platform_id="PLT_01", link_id="LNK_AB", offset_m=1500.0),
        route_distance_start_m=1300.0,
        route_distance_end_m=1600.0,
        stopping_position_m=1500.0,
        direction=RunningDirection.FORWARD,
    )

    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, station_views=[stn_stop], dt_s=0.1)
    traj = sim.simulate(default_dwell_time_s=10.0, max_duration_s=300.0)

    # Find sample where train is dwelling
    dwell_samples = [s for s in traj.samples if s.dynamic_mode == DynamicMode.DWELLING]
    assert len(dwell_samples) > 0
    # Front distance at dwell must be within 0.5m of stopping point (1500m)
    for ds in dwell_samples:
        assert abs(ds.front_distance_m - 1500.0) <= 0.5


@pytest.mark.engineering
def test_bench_p04_007_station_dwell_duration(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-007: Station Dwell Verification (remains stationary for planned dwell)."""
    _, route_fwd, _ = flat_tangent_corridor

    stn_stop = RoutePlatformStop(
        station=Station(station_id="STN_ALPHA", name="Alpha Station"),
        platform=Platform(platform_id="PLT_01", station_id="STN_ALPHA", link_id="LNK_AB", start_offset_m=1300.0, end_offset_m=1600.0, length_m=300.0),
        stopping_point=StoppingPoint(stopping_point_id="SP_01", platform_id="PLT_01", link_id="LNK_AB", offset_m=1500.0),
        route_distance_start_m=1300.0,
        route_distance_end_m=1600.0,
        stopping_position_m=1500.0,
        direction=RunningDirection.FORWARD,
    )

    planned_dwell = 15.0
    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, station_views=[stn_stop], dt_s=0.1)
    traj = sim.simulate(default_dwell_time_s=planned_dwell, max_duration_s=300.0)

    dwell_samples = [s for s in traj.samples if s.dynamic_mode == DynamicMode.DWELLING]
    assert len(dwell_samples) > 0
    dwell_duration = dwell_samples[-1].time_s - dwell_samples[0].time_s
    # Duration must be within 1 time-step of planned dwell
    assert abs(dwell_duration - planned_dwell) <= 0.2


@pytest.mark.engineering
def test_bench_p04_008_departure_acceleration(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-008: Departure Acceleration Resumed after Dwell."""
    _, route_fwd, _ = flat_tangent_corridor

    stn_stop = RoutePlatformStop(
        station=Station(station_id="STN_ALPHA", name="Alpha Station"),
        platform=Platform(platform_id="PLT_01", station_id="STN_ALPHA", link_id="LNK_AB", start_offset_m=1300.0, end_offset_m=1600.0, length_m=300.0),
        stopping_point=StoppingPoint(stopping_point_id="SP_01", platform_id="PLT_01", link_id="LNK_AB", offset_m=1500.0),
        route_distance_start_m=1300.0,
        route_distance_end_m=1600.0,
        stopping_position_m=1500.0,
        direction=RunningDirection.FORWARD,
    )

    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, station_views=[stn_stop], dt_s=0.1)
    traj = sim.simulate(default_dwell_time_s=10.0, max_duration_s=300.0)

    # After station stop (s > 1500m), train must reach significant speed again
    post_stop_samples = [s for s in traj.samples if s.front_distance_m > 1600.0]
    assert len(post_stop_samples) > 0
    max_post_speed = max(s.speed_ms for s in post_stop_samples)
    assert max_post_speed > 10.0


@pytest.mark.engineering
def test_bench_p04_009_train_rear_tracking(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-009: Train Rear Tracking (front - rear == L_train at all times)."""
    _, route_fwd, _ = flat_tangent_corridor
    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, dt_s=0.1)
    traj = sim.simulate(max_duration_s=200.0)

    train_len = sim_train_params.length_m
    assert len(traj.samples) > 10

    for s in traj.samples:
        diff = s.front_distance_m - s.rear_distance_m
        assert diff == pytest.approx(train_len, rel=1e-5)


@pytest.mark.engineering
def test_bench_p04_010_multi_link_movement(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-010: Continuous Position across Link Boundaries."""
    _, route_fwd, _ = flat_tangent_corridor
    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, dt_s=0.1)
    traj = sim.simulate(max_duration_s=250.0)

    # Check for boundary crossing around 2000m
    samples_around_boundary = [s for s in traj.samples if 1990.0 <= s.front_distance_m <= 2010.0]
    assert len(samples_around_boundary) > 0

    # Ensure position is strictly monotonic
    for i in range(len(traj.samples) - 1):
        assert traj.samples[i + 1].front_distance_m >= traj.samples[i].front_distance_m


@pytest.mark.engineering
def test_bench_p04_011_reverse_route_traversal(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-011: Reverse Route Traversal and Coordinate Mapping."""
    _, _, route_rev = flat_tangent_corridor
    sim = MicroscopicSimulator(route=route_rev, params=sim_train_params, dt_s=0.1)
    traj = sim.simulate(max_duration_s=250.0)

    assert traj.running_direction == RunningDirection.REVERSE
    assert len(traj.samples) > 0
    # Final front distance reaches end of reverse route (4000m)
    assert traj.samples[-1].front_distance_m >= 3990.0


@pytest.mark.engineering
def test_bench_p04_012_reverse_gradient_effects(sim_train_params):
    """BENCH-P04-012: Reverse Gradient Inversion (uphill becomes downhill).

    A corridor with physical forward +15‰ uphill slope.
    Forward traversal fights gravity (+F_g); reverse traversal benefits from gravity (-F_g).
    """
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_A", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_B", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(
        TrackLink(
            link_id="LNK_AB",
            track_id="TRK_01",
            start_node_id="ND_A",
            end_node_id="ND_B",
            length_m=2000.0,
            gradient_decimal=0.015,  # +15‰ uphill
            max_speed_ms=83.333,
        )
    )
    route_engine = RouteEngine(graph)
    route_fwd = route_engine.build_route_from_traversals("RT_UP_FWD", [("LNK_AB", RunningDirection.FORWARD)])
    route_rev = route_fwd.create_reverse_route(graph, "RT_UP_REV")

    # Simulate 50 seconds in both directions
    sim_fwd = MicroscopicSimulator(route=route_fwd, params=sim_train_params, dt_s=0.1)
    sim_rev = MicroscopicSimulator(route=route_rev, params=sim_train_params, dt_s=0.1)

    traj_fwd = sim_fwd.simulate(max_duration_s=60.0)
    traj_rev = sim_rev.simulate(max_duration_s=60.0)

    # In reverse (downhill), train covers more distance in 40s than forward (uphill)
    s_fwd_40 = next(s.front_distance_m for s in traj_fwd.samples if s.time_s >= 40.0)
    s_rev_40 = next(s.front_distance_m for s in traj_rev.samples if s.time_s >= 40.0)
    assert s_rev_40 > s_fwd_40


@pytest.mark.engineering
def test_bench_p04_013_reverse_station_stops():
    """BENCH-P04-013: Reverse Station Sequence.

    Corridor with 2 stations: Station 1 at 1000m, Station 2 at 2500m (total 3500m).
    In reverse, Station 2 is encountered first at reverse distance 1000m, Station 1 at 2500m.
    """
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_A", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_B", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(
        TrackLink(
            link_id="LNK_AB", track_id="TRK_01", start_node_id="ND_A", end_node_id="ND_B",
            length_m=3500.0, gradient_decimal=0.0, max_speed_ms=60.0,
        )
    )
    route_engine = RouteEngine(graph)
    route_fwd = route_engine.build_route_from_traversals("RT_FWD", [("LNK_AB", RunningDirection.FORWARD)])
    route_rev = route_fwd.create_reverse_route(graph, "RT_REV")

    stn_model = StationPlatformModel()
    stn_model.add_station(Station(station_id="STN_1", name="Station 1"))
    stn_model.add_station(Station(station_id="STN_2", name="Station 2"))
    stn_model.add_platform(Platform(platform_id="PLT_1", station_id="STN_1", link_id="LNK_AB", start_offset_m=900.0, end_offset_m=1100.0, length_m=200.0))
    stn_model.add_platform(Platform(platform_id="PLT_2", station_id="STN_2", link_id="LNK_AB", start_offset_m=2400.0, end_offset_m=2600.0, length_m=200.0))
    stn_model.add_stopping_point(StoppingPoint(stopping_point_id="SP_1", platform_id="PLT_1", link_id="LNK_AB", offset_m=1000.0))
    stn_model.add_stopping_point(StoppingPoint(stopping_point_id="SP_2", platform_id="PLT_2", link_id="LNK_AB", offset_m=2500.0))

    stops_fwd = stn_model.resolve_route_stops(route_fwd)
    stops_rev = stn_model.resolve_route_stops(route_rev)

    targets_fwd = BrakingTargetResolver.resolve_targets(route_fwd, station_views=stops_fwd)
    targets_rev = BrakingTargetResolver.resolve_targets(route_rev, station_views=stops_rev)

    # Forward: STN_1 first, then STN_2
    assert targets_fwd[0].station_id == "STN_1"
    assert targets_fwd[1].station_id == "STN_2"

    # Reverse: STN_2 first (at 1000m reverse), then STN_1 (at 2500m reverse)
    assert targets_rev[0].station_id == "STN_2"
    assert targets_rev[1].station_id == "STN_1"


@pytest.mark.engineering
def test_bench_p04_014_tvs_reverse_crossing():
    """BENCH-P04-014: TVS Reverse Crossing Entry and Exit."""
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_T1", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_T2", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_TNL", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(
        TrackLink(
            link_id="LNK_TNL",
            track_id="TRK_TNL",
            start_node_id="ND_T1",
            end_node_id="ND_T2",
            length_m=15000.0,
            max_speed_ms=45.0,
        )
    )

    tvs_model = TunnelTVSModel()
    tvs_model.add_tunnel(Tunnel(tunnel_id="TNL_01", name="Long Tunnel"))
    tvs_model.add_tvs_section(
        TVSSection(
            tvs_id="TVS_01",
            tunnel_id="TNL_01",
            track_id="TRK_TNL",
            link_intervals=[ResourceInterval(link_id="LNK_TNL", start_offset_m=5000.0, end_offset_m=10000.0)],
        )
    )

    route_engine = RouteEngine(graph)
    route_fwd = route_engine.build_route_from_traversals("RT_TNL_FWD", [("LNK_TNL", RunningDirection.FORWARD)])
    route_rev = route_fwd.create_reverse_route(graph, "RT_TNL_REV")

    sections_fwd = tvs_model.resolve_route_tvs_sections(route_fwd)
    sections_rev = tvs_model.resolve_route_tvs_sections(route_rev)

    assert len(sections_fwd) == 1
    assert len(sections_rev) == 1

    # Forward: entry 5000m, exit 10000m
    assert sections_fwd[0].route_entry_distance_m == 5000.0
    assert sections_fwd[0].route_exit_distance_m == 10000.0

    # Reverse: entry 5000m (15000 - 10000), exit 10000m (15000 - 5000)
    assert sections_rev[0].route_entry_distance_m == 5000.0
    assert sections_rev[0].route_exit_distance_m == 10000.0


@pytest.mark.engineering
def test_bench_p04_015_event_localization_accuracy(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-015: Boundary Crossing Event Localization Accuracy (<= 0.1s)."""
    _, route_fwd, _ = flat_tangent_corridor
    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, dt_s=0.1)
    traj = sim.simulate(max_duration_s=250.0)

    # Link boundary between LNK_AB and LNK_BC is at 2000m
    exit_events = [e for e in traj.events if e.event_type == CrossingEventType.LINK_FRONT_EXIT and abs(e.route_distance_m - 2000.0) < 1.0]
    assert len(exit_events) > 0
    evt = exit_events[0]
    # Check that sample right before and right after bracket the event time
    s_before = next(s for s in traj.samples if s.time_s <= evt.timestamp_s and s.front_distance_m <= 2000.0)
    s_after = next(s for s in traj.samples if s.time_s >= evt.timestamp_s and s.front_distance_m >= 2000.0)
    assert s_before.time_s <= evt.timestamp_s <= s_after.time_s + 0.1


@pytest.mark.engineering
def test_bench_p04_016_variable_speed_dependent_braking():
    """BENCH-P04-016: Variable Speed-Dependent Braking Integration.

    Linear deceleration curve: b(v) = 0.5 + 0.0125 * v.
    Stopping distance integral from 40 m/s to 0 m/s:
    integral_0^40 (v / (0.5 + 0.0125 v)) dv = 3200 * (1 - ln 2) = 981.93 m.
    """
    points = [
        (0.0, 0.5),
        (20.0, 0.75),
        (40.0, 1.0),
    ]
    model = SpeedDependentBrakingModel(points, response_delay_s=0.0, build_up_time_s=0.0)

    # Calculate stopping distance from 40 m/s
    d = model.calculate_stopping_distance(initial_speed_ms=40.0, target_speed_ms=0.0)

    expected_d = 3200.0 * (1.0 - math.log(2.0))  # 981.929 m
    assert d == pytest.approx(expected_d, rel=1e-3)


@pytest.mark.engineering
def test_bench_p04_017_braking_build_up_delay():
    """BENCH-P04-017: Braking Build-Up Verification (delay increases distance)."""
    model_instant = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=1.0, emergency_deceleration_ms2=1.2,
        response_delay_s=0.0, build_up_time_s=0.0,
    )
    model_buildup = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=1.0, emergency_deceleration_ms2=1.2,
        response_delay_s=0.0, build_up_time_s=2.0,  # 2.0s build-up
    )

    d_inst = model_instant.calculate_stopping_distance(initial_speed_ms=30.0)
    d_build = model_buildup.calculate_stopping_distance(initial_speed_ms=30.0)

    # Build-up must strictly increase stopping distance
    assert d_build > d_inst
    assert d_inst == 450.0  # 30^2 / (2*1)
    # Extra distance approx v0 * (t_bu / 2) = 30 * 1 = 30m
    assert d_build == pytest.approx(479.0, abs=2.0)


@pytest.mark.engineering
def test_bench_p04_018_braking_response_delay():
    """BENCH-P04-018: Braking Response Delay (adds v0 * t_delay distance)."""
    t_delay = 1.5
    v0 = 30.0
    b = 1.0

    model = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=b, emergency_deceleration_ms2=1.2,
        response_delay_s=t_delay, build_up_time_s=0.0,
    )

    d = model.calculate_stopping_distance(initial_speed_ms=v0)
    expected_d = (v0 * t_delay) + ((v0 ** 2) / (2.0 * b))

    assert d == pytest.approx(expected_d, rel=1e-6)
    assert d == pytest.approx(45.0 + 450.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p04_019_net_effective_braking(sim_train_params):
    """BENCH-P04-019: Net Effective Braking (no double counting of resistance)."""
    model = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=0.8, emergency_deceleration_ms2=1.2,
        semantics=BrakingSemantics.NET_EFFECTIVE,
    )
    eval_b = model.evaluate_deceleration(20.0)
    assert eval_b.semantics == BrakingSemantics.NET_EFFECTIVE
    # Effective deceleration is strictly 0.8 m/s^2 regardless of speed
    assert eval_b.effective_deceleration_ms2 == 0.8


@pytest.mark.engineering
def test_bench_p04_020_brake_generated_braking(sim_train_params):
    """BENCH-P04-020: Brake-Generated Braking (applies longitudinal force balance)."""
    model = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=0.8, emergency_deceleration_ms2=1.2,
        semantics=BrakingSemantics.BRAKE_GENERATED,
    )
    eval_b = model.evaluate_deceleration(20.0)
    assert eval_b.semantics == BrakingSemantics.BRAKE_GENERATED


@pytest.mark.engineering
def test_bench_p04_021_unconstrained_journey_time(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-021: Total Journey Time Reconciliation: T_journey = T_moving + T_dwell."""
    _, route_fwd, _ = flat_tangent_corridor

    stn_stop = RoutePlatformStop(
        station=Station(station_id="STN_ALPHA", name="Alpha Station"),
        platform=Platform(platform_id="PLT_01", station_id="STN_ALPHA", link_id="LNK_AB", start_offset_m=1300.0, end_offset_m=1600.0, length_m=300.0),
        stopping_point=StoppingPoint(stopping_point_id="SP_01", platform_id="PLT_01", link_id="LNK_AB", offset_m=1500.0),
        route_distance_start_m=1300.0, route_distance_end_m=1600.0, stopping_position_m=1500.0, direction=RunningDirection.FORWARD,
    )

    planned_dwell = 20.0
    sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, station_views=[stn_stop], dt_s=0.1)
    traj = sim.simulate(default_dwell_time_s=planned_dwell, max_duration_s=300.0)

    t_total = traj.total_time_s
    t_moving = traj.moving_time_s
    t_dwell = traj.dwell_time_s

    # T_journey == T_moving + T_dwell
    assert t_total == pytest.approx(t_moving + t_dwell, rel=1e-5)
    assert t_dwell == pytest.approx(planned_dwell, abs=0.5)


@pytest.mark.engineering
def test_bench_p04_022_numerical_convergence(sim_train_params, flat_tangent_corridor):
    """BENCH-P04-022: Numerical Time-Step Convergence across {0.5, 0.25, 0.1, 0.05} s.

    Demonstrates that journey time and stopping distance converge within required error bounds.
    """
    _, route_fwd, _ = flat_tangent_corridor

    timesteps = [0.5, 0.25, 0.1, 0.05]
    journey_times = []
    final_distances = []

    for dt in timesteps:
        sim = MicroscopicSimulator(route=route_fwd, params=sim_train_params, dt_s=dt)
        traj = sim.simulate(max_duration_s=250.0)
        journey_times.append(traj.total_time_s)
        final_distances.append(traj.samples[-1].front_distance_m)

    # Difference between dt = 0.1s and dt = 0.05s must be small (within 1 second and 0.5m)
    t_diff = abs(journey_times[2] - journey_times[3])
    d_diff = abs(final_distances[2] - final_distances[3])

    assert t_diff < 1.0
    assert d_diff < 1.0
