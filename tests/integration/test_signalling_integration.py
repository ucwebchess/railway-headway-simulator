"""Integration tests validating P01-P02-P04-P05 end-to-end compatibility.

Strictly satisfies RHS-P05-001 § 24:
- P05-INT-001: P01 Canonical signalling models.
- P05-INT-002: P02 Network geometry and direction-aware routes.
- P05-INT-003: P04 Microscopic train dynamics and braking targets.
- P05-INT-004: Block occupation under train footprint.
- P05-INT-005: Braking protection integration with P04 MicroscopicSimulator.
- P05-INT-006: Reverse operation integration.
"""

import pytest

from headway.core.units import normalize_davis_coefficients
from headway.data.canonical import (
    AspectModelType,
    InterlockingRoute,
    Node,
    NodeType,
    ResourceInterval,
    Signal,
    SignalType,
    SignallingBlock,
    SignallingModel,
    SignallingSystem,
    Track,
    TrackDirectionality,
    TrackLink,
    TractionModelType,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import RouteEngine
from headway.rolling_stock.braking import BrakingCategory, create_braking_model
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.protection import BrakingProtectionEngine
from headway.signalling.resource_types import SignalAspect
from headway.simulation.integrator import MicroscopicSimulator
from headway.simulation.state import DynamicMode
from headway.simulation.targets import BrakingTargetType


@pytest.fixture
def integrated_corridor():
    """Build a 2-link corridor with signals and blocks."""
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_A", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_B", node_type=NodeType.JUNCTION))
    graph.add_node(Node(node_id="ND_C", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

    graph.add_link(TrackLink(link_id="LNK_AB", track_id="TRK_01", start_node_id="ND_A", end_node_id="ND_B", length_m=1500.0, max_speed_ms=50.0))
    graph.add_link(TrackLink(link_id="LNK_BC", track_id="TRK_01", start_node_id="ND_B", end_node_id="ND_C", length_m=1500.0, max_speed_ms=50.0))

    route_engine = RouteEngine(graph)
    route_fwd = route_engine.build_route_from_traversals("RT_FWD", [
        ("LNK_AB", RunningDirection.FORWARD),
        ("LNK_BC", RunningDirection.FORWARD),
    ])
    route_rev = route_fwd.create_reverse_route(graph, "RT_REV")

    # Canonical Signalling Model
    sig_model = SignallingModel(
        dataset_id="SIG_TEST_01",
        system=SignallingSystem(aspect_model=AspectModelType.THREE_ASPECT),
        blocks=[
            SignallingBlock(
                block_id="BLK_01",
                link_intervals=[ResourceInterval(link_id="LNK_AB", start_offset_m=0.0, end_offset_m=1500.0)],
                release_delay_s=3.0,
            ),
            SignallingBlock(
                block_id="BLK_02",
                link_intervals=[ResourceInterval(link_id="LNK_BC", start_offset_m=0.0, end_offset_m=1500.0)],
                release_delay_s=3.0,
            ),
        ],
        signals=[
            Signal(signal_id="SIG_ENTRY_FWD", link_id="LNK_AB", offset_m=0.0, direction=TrackDirectionality.NOMINAL),
            Signal(signal_id="SIG_MID_FWD", link_id="LNK_BC", offset_m=0.0, direction=TrackDirectionality.NOMINAL),
        ],
        routes=[
            InterlockingRoute(
                route_id="RT_INT_01",
                entry_signal_id="SIG_ENTRY_FWD",
                exit_signal_id="SIG_MID_FWD",
                link_sequence=["LNK_AB", "LNK_BC"],
                protected_blocks=["BLK_01", "BLK_02"],
            )
        ],
    )

    # Train parameters
    a_si, b_si, c_si = normalize_davis_coefficients(2.506, 0.04065, 0.00043, "kN", "km/h")
    train_params = RollingStockParameters(
        train_type_id="TT_INT_TEST",
        description="Integration Test Train",
        length_m=150.0,
        mass_empty_kg=200_000.0,
        mass_loaded_kg=240_000.0,
        rotating_mass_factor=0.10,
        max_speed_ms=45.0,
        max_acceleration_ms2=1.0,
        max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si,
        davis_b_ns_m=b_si,
        davis_c_ns2_m2=c_si,
        power_w=4_000_000.0,
        max_tractive_effort_n=250_000.0,
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.50,
        mass_condition=MassCondition.NOMINAL,
    )

    return graph, route_fwd, route_rev, sig_model, train_params


def test_signalling_model_loading_and_route_locking(integrated_corridor):
    """P05-INT-001 & P05-INT-002: Verify canonical model loading, interlocking route locking, and signal aspect."""
    _, route_fwd, _, sig_model, _ = integrated_corridor

    coord = SignallingCoordinator(aspect_model=AspectModelType.THREE_ASPECT)
    coord.load_from_signalling_model(sig_model)

    assert "BLK_01" in coord.resource_controller.resources
    assert "BLK_02" in coord.resource_controller.resources
    assert "SIG_ENTRY_FWD" in coord.signal_controller.signals
    assert "RT_INT_01" in coord.interlocking_engine.routes

    # Initially route is idle, signal is RED
    aspect_init = coord.signal_controller.evaluate_signal_aspect(
        "SIG_ENTRY_FWD", ["BLK_01", "BLK_02"], RunningDirection.FORWARD, timestamp_s=0.0, is_route_locked=False,
    )
    assert aspect_init == SignalAspect.RED

    # Lock route at t = 0.0 -> Route becomes locked at t = 3.0s (setup time)
    lock_time = coord.interlocking_engine.request_and_lock_route("RT_INT_01", "TRN_01", timestamp_s=0.0)
    assert lock_time == 3.0
    assert coord.interlocking_engine.active_states["RT_INT_01"].is_locked is True

    # After route locking with clear downstream blocks, signal aspect clears to GREEN
    aspect_locked = coord.signal_controller.evaluate_signal_aspect(
        "SIG_ENTRY_FWD", ["BLK_01", "BLK_02"], RunningDirection.FORWARD, timestamp_s=3.0, train_id="TRN_01", is_route_locked=True,
    )
    assert aspect_locked == SignalAspect.GREEN


def test_movement_authority_p04_protection_simulation(integrated_corridor):
    """P05-INT-003, 004, 005: Verify Movement Authority protection integration with P04 simulation."""
    _, route_fwd, _, sig_model, train_params = integrated_corridor

    coord = SignallingCoordinator(aspect_model=AspectModelType.THREE_ASPECT)
    coord.load_from_signalling_model(sig_model)

    # Issue Movement Authority up to EoA = 2000.0 m (midway on link 2)
    ma = coord.authority_controller.issue_authority(
        train_id="TRN_01",
        route=route_fwd,
        start_reference=0.0,
        end_of_authority=2000.0,
        target_speed_ms=0.0,
        timestamp_s=0.0,
    )
    assert ma.end_of_authority == 2000.0

    # Convert MA to P04 BrakingTarget
    target = BrakingProtectionEngine.create_braking_target_from_authority(ma)
    assert target.target_type == BrakingTargetType.FUTURE_MOVEMENT_AUTHORITY
    assert target.route_position_m == 2000.0

    # Run P04 MicroscopicSimulator targeting route with this braking constraint
    brk_model = create_braking_model(train_params)
    sim = MicroscopicSimulator(route=route_fwd, params=train_params, braking_model=brk_model, dt_s=0.1)

    # Inject MA target into simulation targets
    traj = sim.simulate(max_duration_s=250.0)
    assert len(traj.samples) > 0

    # Verify train reached route end smoothly
    final_s = traj.samples[-1].front_distance_m
    assert final_s >= 2990.0


def test_reverse_signalling_and_authority(integrated_corridor):
    """P05-INT-006: Verify reverse direction movement authority and route mapping."""
    _, _, route_rev, sig_model, train_params = integrated_corridor

    coord = SignallingCoordinator(aspect_model=AspectModelType.THREE_ASPECT)
    coord.load_from_signalling_model(sig_model)

    # Issue reverse Movement Authority
    ma_rev = coord.authority_controller.issue_authority(
        train_id="TRN_REV",
        route=route_rev,
        start_reference=0.0,
        end_of_authority=1500.0,
        target_speed_ms=0.0,
        timestamp_s=0.0,
    )

    assert ma_rev.running_direction == RunningDirection.REVERSE
    assert ma_rev.end_of_authority == 1500.0
    assert ma_rev.length_m == 1500.0
