"""End-to-end integration tests for Milestone P06: Advanced Signalling (ETCS Level 2 & CBTC).

Integrates physical topology (P02), train dynamics (P04), resource management & interlocking (P05),
and advanced train control (P06).
"""

import pytest

from headway.data.canonical import (
    Node,
    NodeType,
    ResourceInterval,
    SignallingBlock,
    SignallingTechnologyType,
    Track,
    TrackDirectionality,
    TrackLink,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import RouteEngine
from headway.rolling_stock.braking import BrakingCategory, ConstantDecelerationBrakingModel
from headway.signalling.advanced_types import (
    RadioCommunicationConfig,
    SignallingModelFidelity,
    TrainIntegrityStatus,
    TrainPositionReport,
)
from headway.signalling.cbtc import CBTCConfig, CBTCMovingBlockEngine
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.etcs import ETCSLevel2Config, ETCSLevel2Engine
from headway.signalling.interlocking import InterlockingEngine, InterlockingRouteDefinition
from headway.signalling.resource_types import ResourceCategory, ResourceEventType
from headway.signalling.resources import ResourceController
from headway.signalling.switches import SwitchController


@pytest.fixture
def integrated_corridor():
    """Build a 4-link, 4000m corridor with 4 fixed blocks and bidirectional capabilities."""
    graph = PhysicalNetworkGraph()
    for n in ["ND_1", "ND_2", "ND_3", "ND_4", "ND_5"]:
        graph.add_node(Node(node_id=n, node_type=NodeType.ENDPOINT if "1" in n or "5" in n else NodeType.JUNCTION))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

    for i in range(1, 5):
        graph.add_link(
            TrackLink(
                link_id=f"LK_0{i}",
                track_id="TRK_01",
                start_node_id=f"ND_{i}",
                end_node_id=f"ND_{i+1}",
                length_m=1000.0,
                max_speed_ms=40.0,
            )
        )

    route_engine = RouteEngine(graph)
    forward_route = route_engine.build_route_from_traversals(
        "RT_CORRIDOR_FWD",
        [(f"LK_0{i}", RunningDirection.FORWARD) for i in range(1, 5)],
    )
    reverse_route = forward_route.create_reverse_route(graph, "RT_CORRIDOR_REV")

    res_ctrl = ResourceController()
    for i in range(1, 5):
        blk = SignallingBlock(
            block_id=f"BLK_0{i}",
            link_intervals=[ResourceInterval(link_id=f"LK_0{i}", start_offset_m=0.0, end_offset_m=1000.0)],
            release_delay_s=2.0,
        )
        res_ctrl.register_signalling_block(blk)

    sw_ctrl = SwitchController()
    interlocking = InterlockingEngine(resource_controller=res_ctrl, switch_controller=sw_ctrl)
    interlocking.register_route(
        InterlockingRouteDefinition(
            route_id="RT_CORRIDOR_FWD",
            entry_signal_id="SIG_01",
            exit_signal_id="SIG_05",
            link_sequence=[f"LK_0{i}" for i in range(1, 5)],
            protected_block_ids=[f"BLK_0{i}" for i in range(1, 5)],
        )
    )

    return {
        "graph": graph,
        "forward_route": forward_route,
        "reverse_route": reverse_route,
        "resource_controller": res_ctrl,
        "interlocking": interlocking,
        "switch_controller": sw_ctrl,
    }


def test_etcs_level2_multi_train_end_to_end(integrated_corridor):
    """End-to-end ETCS Level 2 flow: 2 trains, fixed-block occupancy, MA extension on block clearance."""
    res_ctrl = integrated_corridor["resource_controller"]
    interlocking = integrated_corridor["interlocking"]
    rt = integrated_corridor["forward_route"]

    engine = ETCSLevel2Engine(
        config=ETCSLevel2Config(
            fidelity=SignallingModelFidelity.DETAILED,
            communication_config=RadioCommunicationConfig(uplink_latency_s=0.4, processing_delay_s=0.2, downlink_latency_s=0.4),
            default_overlap_m=50.0,
            service_deceleration_ms2=0.75,
            emergency_deceleration_ms2=1.0,
        ),
        resource_controller=res_ctrl,
        interlocking_engine=interlocking,
    )

    engine.register_train("TR_LEAD", 200.0)
    engine.register_train("TR_TRAIL", 200.0)

    # 1. TR_LEAD is occupying BLK_02 (1000m to 2000m)
    res_ctrl.front_enter_resource("TR_LEAD", "BLK_02", timestamp_s=0.0)

    # 2. TR_TRAIL at standstill at origin (s=0m) requests MA
    ma_trail_1 = engine.compute_movement_authority("TR_TRAIL", rt, current_time_s=10.0, start_position_m=0.0)

    # Authority should be limited to start of BLK_02 (1000m)
    assert ma_trail_1.end_of_authority == 1000.0
    assert ma_trail_1.effective_time_s == pytest.approx(11.0, abs=1e-6)

    # 3. TR_LEAD moves to BLK_03 and completely clears BLK_02
    res_ctrl.front_enter_resource("TR_LEAD", "BLK_03", timestamp_s=20.0)
    res_ctrl.front_exit_resource("TR_LEAD", "BLK_02", timestamp_s=25.0)
    res_ctrl.rear_clear_resource("TR_LEAD", "BLK_02", timestamp_s=30.0)

    # Release timer passes (release delay = 2.0s)
    res_ctrl.process_pending_releases(current_time_s=33.0)
    assert res_ctrl.get_resource("BLK_02").is_occupied is False

    # 4. RBC extends TR_TRAIL authority into BLK_02 (up to BLK_03 entrance at 2000m)
    ma_trail_2 = engine.rbc.extend_movement_authority("TR_TRAIL", new_end_of_authority=2000.0, current_time_s=35.0)
    assert ma_trail_2.end_of_authority == 2000.0
    assert ma_trail_2.effective_time_s == pytest.approx(36.0, abs=1e-6)

    # 5. Braking supervision check at s=1400m (600m to EoA=2000m)
    profile = engine.evaluate_supervision("TR_TRAIL", current_speed_ms=25.0, current_position_m=1400.0)
    assert profile.permitted_speed_ms == pytest.approx(30.0, abs=1e-3)

    # 6. Safety target created for P04 dynamics
    target = engine.create_braking_target("TR_TRAIL", braking_category=BrakingCategory.OPERATIONAL_SERVICE)
    assert target.route_position_m == 2000.0


def test_cbtc_moving_block_multi_train_end_to_end(integrated_corridor):
    """End-to-end CBTC moving-block flow: Follower tracking Leader with continuous dynamic MA updates."""
    rt = integrated_corridor["forward_route"]
    engine = CBTCMovingBlockEngine(
        config=CBTCConfig(
            fidelity=SignallingModelFidelity.DETAILED,
            base_localization_uncertainty_m=20.0,
            safety_margin_m=10.0,
            service_deceleration_ms2=0.75,
            emergency_deceleration_ms2=1.0,
        ),
        resource_controller=integrated_corridor["resource_controller"],
        interlocking_engine=integrated_corridor["interlocking"],
        switch_controller=integrated_corridor["switch_controller"],
    )

    engine.register_train("TR_LEAD", 200.0)
    engine.register_train("TR_FOLLOW", 200.0)

    # Timestep 1: Leader reports front at 2500m
    # Nominal rear = 2300m => Protected rear = 2300 - 20 - 10 = 2270m
    rep1 = TrainPositionReport(train_id="TR_LEAD", timestamp_s=0.0, link_id="LK_03", front_position_m=2500.0, speed_ms=15.0, train_length_m=200.0)
    engine.receive_position_report(rep1, current_time_s=0.0)

    ma1 = engine.compute_movement_authority("TR_FOLLOW", rt, current_time_s=0.0, start_position_m=1000.0)
    assert ma1.end_of_authority == 2270.0

    # Timestep 2: Leader advances 200m to 2700m at t=1.0s
    # Nominal rear = 2500m => Protected rear = 2500 - 20 - 10 = 2470m
    rep2 = TrainPositionReport(train_id="TR_LEAD", timestamp_s=1.0, link_id="LK_03", front_position_m=2700.0, speed_ms=15.0, train_length_m=200.0)
    engine.receive_position_report(rep2, current_time_s=1.0)

    ma2 = engine.compute_movement_authority("TR_FOLLOW", rt, current_time_s=1.0, start_position_m=1200.0)
    assert ma2.end_of_authority == 2470.0

    # Timestep 3: Follower evaluates supervision approaching EoA
    # Follower at 1870m (d = 600m to EoA=2470m)
    profile = engine.evaluate_supervision("TR_FOLLOW", current_speed_ms=28.0, current_position_m=1870.0)
    assert profile.distance_to_target_m == pytest.approx(600.0, abs=1e-3)
    assert profile.permitted_speed_ms == pytest.approx(30.0, abs=1e-3)


def test_signalling_coordinator_advanced_integration(integrated_corridor):
    """Verify SignallingCoordinator integrates ETCS L2 and CBTC moving-block models seamlessly."""
    # 1. Coordinator with ETCS L2
    coord_etcs = SignallingCoordinator(
        technology_type=SignallingTechnologyType.ETCS_LEVEL_2,
        fidelity=SignallingModelFidelity.DETAILED,
    )
    assert coord_etcs.etcs_engine is not None
    assert coord_etcs.cbtc_engine is None

    # 2. Coordinator with CBTC
    coord_cbtc = SignallingCoordinator(
        technology_type=SignallingTechnologyType.CBTC_MOVING_BLOCK,
        fidelity=SignallingModelFidelity.DETAILED,
    )
    assert coord_cbtc.cbtc_engine is not None
    assert coord_etcs.etcs_engine is not None

    # 3. Deterministic event logging integration
    events = coord_etcs.get_all_events()
    assert isinstance(events, list)
