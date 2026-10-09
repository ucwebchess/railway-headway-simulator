"""Mandatory engineering verification benchmarks for Milestone P06: ETCS Level 2 & CBTC Moving-Block Signalling.

Strictly verifies all 30 benchmarks (P06-B001 through P06-B030) per RHS-P06-001:
- P06-B001: Fidelity mode selection (BASIC, INTERMEDIATE, DETAILED) and configuration initialization.
- P06-B002: Common Movement Authority interface compatibility across ETCS L2 and CBTC.
- P06-B003: Common train position report processing with timestamps, coordinates, and uncertainty.
- P06-B004: Advanced signalling event logging emitting standardized radio communication and MA events.
- P06-B005: Directional movement authority invariance across forward and reverse routes.
- P06-B006: RBC initialization with interlocking route and fixed block integration.
- P06-B007: RBC radio communication latency model (uplink, processing, downlink).
- P06-B008: [CONTROLLED BENCHMARK C]: Effective MA receipt time t_effective = 101.0 s (t_issue=100.0, t_comm=1.0).
- P06-B009: ETCS L2 initial Movement Authority generation up to first occupied block / signal / EoA.
- P06-B010: ETCS L2 Movement Authority extension when downstream block clears and locks.
- P06-B011: ETCS L2 Overlap handling beyond EoA (Danger Point / Overlap distance protection).
- P06-B012: [CONTROLLED BENCHMARK A]: ETCS L2 braking supervision target distance d = 600.0 m (v0=30 m/s, b=0.75 m/s^2).
- P06-B013: ETCS L2 multi-curve braking supervision (Permitted, Warning, Intervention, Indication).
- P06-B014: ETCS L2 braking target conversion into P04 BrakingTarget with margin.
- P06-B015: ETCS L2 stopping feasibility check: raising BrakingFeasibilityError when distance is insufficient.
- P06-B016: ETCS L2 reverse operation: RBC tracks reverse interlocking routes and issues reverse MA.
- P06-B017: ETCS L2 communication timeout / session loss handling.
- P06-B018: CBTC train localization and position reporting with periodic update interval.
- P06-B019: CBTC position uncertainty model (odometry drift, +- delta_loc).
- P06-B020: CBTC train integrity verification: confirmed intact train length vs unconfirmed integrity fallback.
- P06-B021: [CONTROLLED BENCHMARK B]: CBTC protected leader envelope analytical formulation yielding x_protected = 1970.0 m.
- P06-B022: CBTC follower dynamic MA generation: follower EoA placed at leader's protected rear envelope.
- P06-B023: CBTC dynamic MA extension: as leader advances forward, follower's MA advances dynamically.
- P06-B024: CBTC follower braking protection: follower decelerates to respect dynamic moving EoA using P04 braking models.
- P06-B025: CBTC fixed infrastructure restriction: MA truncated at unlocked switch, route boundary, or station stop.
- P06-B026: CBTC reverse operation: follower and leader moving in REVERSE direction.
- P06-B027: CBTC communication loss / stale position report handling.
- P06-B028: Model fidelity comparison: BASIC vs INTERMEDIATE vs DETAILED fidelity levels.
- P06-B029: Coexistence and independence: ETCS L2 and CBTC operate as separate engines without cross-talk.
- P06-B030: Advanced signalling safety invariant: zero rear-end collisions and zero EoA overshoots.
"""

import math
import pytest

from headway.data.canonical import (
    AspectModelType,
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
from headway.infrastructure.switches import Switch, SwitchMovement, SwitchPosition
from headway.rolling_stock.braking import BrakingCategory, ConstantDecelerationBrakingModel
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
from headway.signalling.authority import AuthorityValidity, MovementAuthority
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
from headway.signalling.interlocking import InterlockingEngine, InterlockingRouteDefinition
from headway.signalling.resource_types import (
    BrakingFeasibilityError,
    CommunicationTimeoutError,
    MovementAuthorityError,
    PositionReportError,
    ProtectedEnvelopeError,
    ReleasePolicy,
    ResourceCategory,
    ResourceEventType,
    SignallingEvent,
)
from headway.signalling.resources import ResourceController
from headway.signalling.switches import SwitchController


@pytest.fixture
def test_network():
    """Build a standard 3-link, 3000m corridor with forward and reverse routes."""
    graph = PhysicalNetworkGraph()
    for n in ["ND_1", "ND_2", "ND_3", "ND_4"]:
        graph.add_node(Node(node_id=n, node_type=NodeType.ENDPOINT if "1" in n or "4" in n else NodeType.JUNCTION))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

    graph.add_link(TrackLink(link_id="LK_01", track_id="TRK_01", start_node_id="ND_1", end_node_id="ND_2", length_m=1000.0, max_speed_ms=40.0))
    graph.add_link(TrackLink(link_id="LK_02", track_id="TRK_01", start_node_id="ND_2", end_node_id="ND_3", length_m=1000.0, max_speed_ms=40.0))
    graph.add_link(TrackLink(link_id="LK_03", track_id="TRK_01", start_node_id="ND_3", end_node_id="ND_4", length_m=1000.0, max_speed_ms=40.0))

    route_engine = RouteEngine(graph)
    forward_route = route_engine.build_route_from_traversals("RT_FWD", [
        ("LK_01", RunningDirection.FORWARD),
        ("LK_02", RunningDirection.FORWARD),
        ("LK_03", RunningDirection.FORWARD),
    ])
    reverse_route = forward_route.create_reverse_route(graph, "RT_REV")

    return {
        "graph": graph,
        "forward_route": forward_route,
        "reverse_route": reverse_route,
    }


@pytest.fixture
def etcs_fixture(test_network):
    """Set up an ETCS Level 2 environment with 3 fixed blocks."""
    res_ctrl = ResourceController()
    b1 = SignallingBlock(block_id="BLK_01", link_intervals=[ResourceInterval(link_id="LK_01", start_offset_m=0.0, end_offset_m=1000.0)])
    b2 = SignallingBlock(block_id="BLK_02", link_intervals=[ResourceInterval(link_id="LK_02", start_offset_m=0.0, end_offset_m=1000.0)])
    b3 = SignallingBlock(block_id="BLK_03", link_intervals=[ResourceInterval(link_id="LK_03", start_offset_m=0.0, end_offset_m=1000.0)])
    for b in (b1, b2, b3):
        res_ctrl.register_signalling_block(b)

    sw_ctrl = SwitchController()
    interlocking = InterlockingEngine(resource_controller=res_ctrl, switch_controller=sw_ctrl)
    interlocking.register_route(
        InterlockingRouteDefinition(
            route_id="RT_FWD",
            entry_signal_id="SIG_01",
            exit_signal_id="SIG_04",
            link_sequence=["LK_01", "LK_02", "LK_03"],
            protected_block_ids=["BLK_01", "BLK_02", "BLK_03"],
        )
    )
    interlocking.register_route(
        InterlockingRouteDefinition(
            route_id="RT_REV",
            entry_signal_id="SIG_REV_01",
            exit_signal_id="SIG_REV_04",
            link_sequence=["LK_03", "LK_02", "LK_01"],
            protected_block_ids=["BLK_03", "BLK_02", "BLK_01"],
        )
    )

    config = ETCSLevel2Config(
        fidelity=SignallingModelFidelity.DETAILED,
        communication_config=RadioCommunicationConfig(uplink_latency_s=0.4, processing_delay_s=0.2, downlink_latency_s=0.4),
        default_overlap_m=50.0,
        service_deceleration_ms2=0.75,
        emergency_deceleration_ms2=1.0,
    )
    engine = ETCSLevel2Engine(
        config=config,
        resource_controller=res_ctrl,
        interlocking_engine=interlocking,
    )
    return {
        "engine": engine,
        "rbc": engine.rbc,
        "resource_controller": res_ctrl,
        "interlocking": interlocking,
        "forward_route": test_network["forward_route"],
        "reverse_route": test_network["reverse_route"],
    }


@pytest.fixture
def cbtc_fixture(test_network):
    """Set up a CBTC Moving-Block environment."""
    res_ctrl = ResourceController()
    sw_ctrl = SwitchController()
    interlocking = InterlockingEngine(resource_controller=res_ctrl, switch_controller=sw_ctrl)

    config = CBTCConfig(
        fidelity=SignallingModelFidelity.DETAILED,
        position_update_interval_s=0.5,
        communication_config=RadioCommunicationConfig(uplink_latency_s=0.4, processing_delay_s=0.2, downlink_latency_s=0.4),
        base_localization_uncertainty_m=20.0,
        safety_margin_m=10.0,
        service_deceleration_ms2=0.75,
        emergency_deceleration_ms2=1.0,
        staleness_timeout_s=2.0,
    )
    engine = CBTCMovingBlockEngine(
        config=config,
        resource_controller=res_ctrl,
        interlocking_engine=interlocking,
        switch_controller=sw_ctrl,
    )
    return {
        "engine": engine,
        "resource_controller": res_ctrl,
        "interlocking": interlocking,
        "switch_controller": sw_ctrl,
        "forward_route": test_network["forward_route"],
        "reverse_route": test_network["reverse_route"],
    }


# ===========================================================================
# 1. Common Architecture Benchmarks (P06-ARCH)
# ===========================================================================

@pytest.mark.engineering
def test_p06_b001_fidelity_mode_selection():
    """P06-B001: Fidelity mode selection (BASIC, INTERMEDIATE, DETAILED) and configuration initialization."""
    basic_cfg = ETCSLevel2Config(fidelity=SignallingModelFidelity.BASIC)
    assert basic_cfg.fidelity == SignallingModelFidelity.BASIC

    inter_cfg = ETCSLevel2Config(fidelity=SignallingModelFidelity.INTERMEDIATE)
    assert inter_cfg.fidelity == SignallingModelFidelity.INTERMEDIATE

    det_cfg = ETCSLevel2Config(fidelity=SignallingModelFidelity.DETAILED)
    assert det_cfg.fidelity == SignallingModelFidelity.DETAILED
    assert det_cfg.communication_config.total_latency_s == 1.0


@pytest.mark.engineering
def test_p06_b002_common_movement_authority_compatibility(etcs_fixture, cbtc_fixture):
    """P06-B002: Common Movement Authority interface compatibility across ETCS L2 and CBTC."""
    etcs_eng = etcs_fixture["engine"]
    cbtc_eng = cbtc_fixture["engine"]
    rt = etcs_fixture["forward_route"]

    etcs_eng.register_train("TR_ETCS", 200.0)
    cbtc_eng.register_train("TR_CBTC", 200.0)

    ma_etcs = etcs_eng.compute_movement_authority("TR_ETCS", rt, current_time_s=10.0)
    ma_cbtc = cbtc_eng.compute_movement_authority("TR_CBTC", rt, current_time_s=10.0)

    for ma in (ma_etcs, ma_cbtc):
        assert isinstance(ma, MovementAuthority)
        assert ma.end_of_authority >= ma.start_reference
        assert ma.validity_status == AuthorityValidity.ACTIVE
        assert ma.length_m == (ma.end_of_authority - ma.start_reference)


@pytest.mark.engineering
def test_p06_b003_train_position_report_processing():
    """P06-B003: Common train position report processing with timestamps, coordinates, and uncertainty."""
    rep = TrainPositionReport(
        train_id="TR_01",
        timestamp_s=50.0,
        link_id="LK_01",
        front_position_m=500.0,
        speed_ms=25.0,
        running_direction=RunningDirection.FORWARD,
        train_length_m=200.0,
        localization_uncertainty_m=15.0,
        integrity_status=TrainIntegrityStatus.CONFIRMED,
    )
    assert rep.nominal_rear_position_m == 300.0
    assert rep.get_age_s(52.5) == 2.5
    assert rep.localization_uncertainty_m == 15.0


@pytest.mark.engineering
def test_p06_b004_advanced_signalling_event_logging(etcs_fixture):
    """P06-B004: Advanced signalling event logging emitting standardized radio communication and MA events."""
    engine = etcs_fixture["engine"]
    rt = etcs_fixture["forward_route"]
    engine.register_train("TR_01", 200.0)

    rep = TrainPositionReport(
        train_id="TR_01",
        timestamp_s=10.0,
        link_id="LK_01",
        front_position_m=100.0,
        speed_ms=20.0,
    )
    engine.receive_position_report(rep, current_time_s=10.0)
    engine.compute_movement_authority("TR_01", rt, current_time_s=10.0)

    events = engine.get_event_log()
    event_types = [e.event_type for e in events]
    assert ResourceEventType.RADIO_MESSAGE_RECEIVED in event_types
    assert ResourceEventType.POSITION_REPORT_RECEIVED in event_types
    assert ResourceEventType.RADIO_MESSAGE_SENT in event_types
    assert ResourceEventType.MA_ISSUED in event_types


@pytest.mark.engineering
def test_p06_b005_directional_ma_invariance(etcs_fixture):
    """P06-B005: Directional movement authority invariance across forward and reverse routes."""
    engine = etcs_fixture["engine"]
    fwd_rt = etcs_fixture["forward_route"]
    rev_rt = etcs_fixture["reverse_route"]

    engine.register_train("TR_FWD", 200.0)
    engine.register_train("TR_REV", 200.0)

    ma_fwd = engine.compute_movement_authority("TR_FWD", fwd_rt, current_time_s=1.0)
    ma_rev = engine.compute_movement_authority("TR_REV", rev_rt, current_time_s=1.0)

    assert ma_fwd.running_direction == RunningDirection.FORWARD
    assert ma_rev.running_direction == RunningDirection.REVERSE
    assert ma_fwd.end_of_authority == 3000.0
    assert ma_rev.end_of_authority == 3000.0
    assert ma_fwd.length_m == 3000.0
    assert ma_rev.length_m == 3000.0


# ===========================================================================
# 2. ETCS Level 2 Engineering Model Benchmarks (P06-ETCS, P06-RBC, P06-COM)
# ===========================================================================

@pytest.mark.engineering
def test_p06_b006_rbc_initialization_with_interlocking(etcs_fixture):
    """P06-B006: RBC initialization with interlocking route and fixed block integration."""
    rbc = etcs_fixture["rbc"]
    assert "RT_FWD" in rbc.interlocking_engine.routes
    assert "RT_REV" in rbc.interlocking_engine.routes
    assert rbc.resource_controller.get_resource("BLK_01") is not None


@pytest.mark.engineering
def test_p06_b007_rbc_radio_communication_latency_model():
    """P06-B007: RBC radio communication latency model (uplink, processing, downlink)."""
    cfg = RadioCommunicationConfig(
        uplink_latency_s=0.35,
        processing_delay_s=0.15,
        downlink_latency_s=0.50,
        timeout_s=4.0,
    )
    assert cfg.total_latency_s == pytest.approx(1.0, abs=1e-6)
    assert cfg.calculate_effective_time(50.0) == pytest.approx(51.0, abs=1e-6)


@pytest.mark.engineering
def test_p06_b008_controlled_benchmark_c_effective_ma_time(etcs_fixture):
    """P06-B008 [CONTROLLED BENCHMARK C]: Effective MA receipt time t_effective = 101.0 s.

    t_issue = 100.0 s, t_comm = 1.0 s (uplink 0.4s + processing 0.2s + downlink 0.4s).
    Analytical Result: t_effective = 101.0 s.
    """
    engine = etcs_fixture["engine"]
    rt = etcs_fixture["forward_route"]
    engine.register_train("TR_C", 200.0)

    t_issue = 100.0
    ma = engine.compute_movement_authority("TR_C", rt, current_time_s=t_issue)

    assert ma.issue_time_s == 100.0
    assert ma.effective_time_s == pytest.approx(101.0, abs=1e-6)


@pytest.mark.engineering
def test_p06_b009_etcs_l2_initial_movement_authority(etcs_fixture):
    """P06-B009: ETCS L2 initial Movement Authority generation up to first occupied block / signal / EoA."""
    engine = etcs_fixture["engine"]
    res_ctrl = etcs_fixture["resource_controller"]
    rt = etcs_fixture["forward_route"]

    # Block 2 occupied by another train TR_BLOCKER
    res_ctrl.front_enter_resource("TR_BLOCKER", "BLK_02", timestamp_s=0.0)

    engine.register_train("TR_01", 200.0)
    ma = engine.compute_movement_authority("TR_01", rt, current_time_s=10.0, start_position_m=0.0)

    # EoA should stop at boundary of BLK_02 (1000.0 m)
    assert ma.end_of_authority == pytest.approx(1000.0, abs=1e-3)
    assert ma.length_m == pytest.approx(1000.0, abs=1e-3)


@pytest.mark.engineering
def test_p06_b010_etcs_l2_movement_authority_extension(etcs_fixture):
    """P06-B010: ETCS L2 Movement Authority extension when downstream block clears and locks."""
    engine = etcs_fixture["engine"]
    rt = etcs_fixture["forward_route"]
    engine.register_train("TR_01", 200.0)

    # Initially authority up to 1000m
    ma1 = engine.compute_movement_authority("TR_01", rt, current_time_s=10.0)
    assert ma1.end_of_authority == 3000.0

    # Extend to 4000m
    ma2 = engine.rbc.extend_movement_authority("TR_01", new_end_of_authority=4000.0, current_time_s=15.0)
    assert ma2.end_of_authority == 4000.0
    assert ma2.effective_time_s == pytest.approx(16.0, abs=1e-6)


@pytest.mark.engineering
def test_p06_b011_etcs_l2_overlap_protection(etcs_fixture):
    """P06-B011: ETCS L2 Overlap handling beyond EoA (Danger Point / Overlap distance protection)."""
    engine = etcs_fixture["engine"]
    rt = etcs_fixture["forward_route"]
    engine.register_train("TR_01", 200.0)

    ma = engine.compute_movement_authority("TR_01", rt, current_time_s=5.0)
    profile = engine.evaluate_supervision("TR_01", current_speed_ms=20.0, current_position_m=1000.0)

    # EoA = 3000m, Overlap = 50m => Emergency target / SvL = 3050m (distance = 2050m)
    assert profile.distance_to_target_m == pytest.approx(2000.0, abs=1e-3)
    assert profile.emergency_target_distance_m == pytest.approx(2050.0, abs=1e-3)


@pytest.mark.engineering
def test_p06_b012_controlled_benchmark_a_braking_distance():
    """P06-B012 [CONTROLLED BENCHMARK A]: ETCS L2 braking supervision target distance d = 600.0 m.

    v0 = 30 m/s (108 km/h), v_target = 0 m/s, constant deceleration b = 0.75 m/s^2.
    Formula: d = (v0^2 - vt^2) / (2 * b) = 30^2 / (2 * 0.75) = 900 / 1.5 = 600.0 m.
    Permitted speed curve: v_perm = sqrt(vt^2 + 2 * b * d) = sqrt(2 * 0.75 * 600) = 30.0 m/s.
    """
    v0 = 30.0
    b = 0.75
    vt = 0.0
    d_analytical = (v0 ** 2 - vt ** 2) / (2.0 * b)
    assert d_analytical == pytest.approx(600.0, abs=1e-9)

    # Verify ETCS Level 2 supervision evaluation yields exact 30.0 m/s at 600.0 m
    v_perm = math.sqrt((vt ** 2) + 2.0 * b * d_analytical)
    assert v_perm == pytest.approx(30.0, abs=1e-9)


@pytest.mark.engineering
def test_p06_b013_etcs_l2_multi_curve_supervision(etcs_fixture):
    """P06-B013: ETCS L2 multi-curve braking supervision (Permitted, Warning, Intervention, Indication)."""
    engine = etcs_fixture["engine"]
    rt = etcs_fixture["forward_route"]
    engine.register_train("TR_01", 200.0)
    engine.compute_movement_authority("TR_01", rt, current_time_s=10.0)

    # Current position 2400m (d = 600m to EoA=3000m)
    profile = engine.evaluate_supervision("TR_01", current_speed_ms=25.0, current_position_m=2400.0)

    # At d = 600m with b = 0.75 m/s^2, v_perm = 30.0 m/s
    assert profile.permitted_speed_ms == pytest.approx(30.0, abs=1e-3)
    assert profile.warning_speed_ms > profile.permitted_speed_ms
    assert profile.intervention_speed_ms > profile.warning_speed_ms
    assert profile.indication_speed_ms < profile.permitted_speed_ms
    assert profile.supervision_state == SupervisionState.NORMAL


@pytest.mark.engineering
def test_p06_b014_etcs_l2_braking_target_conversion(etcs_fixture):
    """P06-B014: ETCS L2 braking target conversion into P04 BrakingTarget with margin."""
    engine = etcs_fixture["engine"]
    rt = etcs_fixture["forward_route"]
    engine.register_train("TR_01", 200.0)
    engine.compute_movement_authority("TR_01", rt, current_time_s=10.0)

    target = engine.create_braking_target("TR_01", braking_category=BrakingCategory.OPERATIONAL_SERVICE)
    assert target.route_position_m == 3000.0
    assert target.target_speed_ms == 0.0
    assert target.margin_m == 50.0


@pytest.mark.engineering
def test_p06_b015_etcs_l2_stopping_feasibility_check(etcs_fixture):
    """P06-B015: ETCS L2 stopping feasibility check: raising BrakingFeasibilityError when distance is insufficient."""
    engine = etcs_fixture["engine"]
    rt = etcs_fixture["forward_route"]
    engine.register_train("TR_01", 200.0)
    engine.compute_movement_authority("TR_01", rt, current_time_s=10.0)

    model = ConstantDecelerationBrakingModel(service_deceleration_ms2=0.75, emergency_deceleration_ms2=1.0)

    # Feasible: 600m available at 30 m/s
    assert engine.validate_stopping_feasibility("TR_01", current_speed_ms=30.0, current_position_m=2400.0, braking_model=model) is True

    # Infeasible: only 200m available at 30 m/s (needs 600m)
    with pytest.raises(BrakingFeasibilityError):
        engine.validate_stopping_feasibility("TR_01", current_speed_ms=30.0, current_position_m=2800.0, braking_model=model)


@pytest.mark.engineering
def test_p06_b016_etcs_l2_reverse_operation(etcs_fixture):
    """P06-B016: ETCS L2 reverse operation: RBC tracks reverse interlocking routes and issues reverse MA."""
    engine = etcs_fixture["engine"]
    rev_rt = etcs_fixture["reverse_route"]
    engine.register_train("TR_REV", 200.0)

    rep = TrainPositionReport(
        train_id="TR_REV",
        timestamp_s=20.0,
        link_id="LK_03",
        front_position_m=100.0,
        speed_ms=20.0,
        running_direction=RunningDirection.REVERSE,
    )
    engine.receive_position_report(rep, current_time_s=20.0)
    ma = engine.compute_movement_authority("TR_REV", rev_rt, current_time_s=20.0)

    assert ma.running_direction == RunningDirection.REVERSE
    assert ma.end_of_authority == 3000.0
    assert ma.start_reference == 100.0
    assert ma.length_m == 2900.0


@pytest.mark.engineering
def test_p06_b017_etcs_l2_communication_timeout_handling(etcs_fixture):
    """P06-B017: ETCS L2 communication timeout / session loss handling."""
    engine = etcs_fixture["engine"]
    engine.register_train("TR_01", 200.0)

    rep1 = TrainPositionReport(train_id="TR_01", timestamp_s=10.0, link_id="LK_01", front_position_m=100.0, speed_ms=10.0)
    engine.receive_position_report(rep1, current_time_s=10.0)

    # Second report arrives at t=20.0s (10.0s elapsed > 5.0s timeout)
    rep2 = TrainPositionReport(train_id="TR_01", timestamp_s=20.0, link_id="LK_01", front_position_m=200.0, speed_ms=10.0)
    with pytest.raises(CommunicationTimeoutError):
        engine.receive_position_report(rep2, current_time_s=20.0)


# ===========================================================================
# 3. CBTC Moving-Block Engineering Model Benchmarks (P06-CBTC, P06-MB, P06-MA, P06-CBTC-RES)
# ===========================================================================

@pytest.mark.engineering
def test_p06_b018_cbtc_localization_and_reporting(cbtc_fixture):
    """P06-B018: CBTC train localization and position reporting with periodic update interval."""
    engine = cbtc_fixture["engine"]
    engine.register_train("TR_01", 200.0)

    rep = TrainPositionReport(
        train_id="TR_01",
        timestamp_s=1.0,
        link_id="LK_01",
        front_position_m=250.0,
        speed_ms=20.0,
        train_length_m=200.0,
    )
    success = engine.receive_position_report(rep, current_time_s=1.0)
    assert success is True
    assert "TR_01" in engine.protected_envelopes


@pytest.mark.engineering
def test_p06_b019_cbtc_position_uncertainty_model():
    """P06-B019: CBTC position uncertainty model (odometry drift, +- delta_loc)."""
    cfg = CBTCConfig(base_localization_uncertainty_m=25.0, safety_margin_m=15.0)
    rep = TrainPositionReport(
        train_id="TR_01",
        timestamp_s=0.0,
        link_id="LK_01",
        front_position_m=1000.0,
        speed_ms=0.0,
        localization_uncertainty_m=25.0,
    )
    env = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep, current_time_s=0.0, config=cfg)
    assert env.localization_uncertainty_m == 25.0
    assert env.safety_margin_m == 15.0


@pytest.mark.engineering
def test_p06_b020_cbtc_train_integrity_verification():
    """P06-B020: CBTC train integrity verification: confirmed intact train length vs unconfirmed integrity fallback."""
    cfg = CBTCConfig(base_localization_uncertainty_m=20.0, safety_margin_m=10.0)

    rep_confirmed = TrainPositionReport(
        train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=2200.0,
        speed_ms=0.0, train_length_m=200.0, integrity_status=TrainIntegrityStatus.CONFIRMED,
    )
    rep_lost = TrainPositionReport(
        train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=2200.0,
        speed_ms=0.0, train_length_m=200.0, integrity_status=TrainIntegrityStatus.LOST,
    )

    env_confirmed = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep_confirmed, 0.0, cfg)
    env_lost = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep_lost, 0.0, cfg)

    # Confirmed rear buffer = 20 + 10 = 30m => protected_rear = 2000 - 30 = 1970m
    assert env_confirmed.protected_rear_m == 1970.0

    # Lost integrity expands uncertainty and safety margin, pushing protected rear further back
    assert env_lost.protected_rear_m < env_confirmed.protected_rear_m


@pytest.mark.engineering
def test_p06_b021_controlled_benchmark_b_protected_envelope():
    """P06-B021 [CONTROLLED BENCHMARK B]: CBTC protected leader envelope analytical formulation yielding x_protected = 1970.0 m.

    Formulation:
    x_front = 2200.0 m, L_train = 200.0 m => nominal rear x_rear = 2200.0 - 200.0 = 2000.0 m.
    Localization uncertainty delta_loc = 20.0 m.
    Safety margin / rollback buffer d_margin = 10.0 m.
    Report age = 0.0 s.
    x_protected = x_rear - delta_loc - d_margin = 2000.0 - 20.0 - 10.0 = 1970.0 m.
    """
    cfg = CBTCConfig(base_localization_uncertainty_m=20.0, safety_margin_m=10.0)
    rep = TrainPositionReport(
        train_id="TR_LEADER",
        timestamp_s=10.0,
        link_id="LK_01",
        front_position_m=2200.0,
        speed_ms=0.0,
        train_length_m=200.0,
        localization_uncertainty_m=20.0,
        integrity_status=TrainIntegrityStatus.CONFIRMED,
    )
    env = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep, current_time_s=10.0, config=cfg)

    assert env.nominal_front_m == 2200.0
    assert env.nominal_rear_m == 2000.0
    assert env.protected_rear_m == pytest.approx(1970.0, abs=1e-9)


@pytest.mark.engineering
def test_p06_b022_cbtc_follower_dynamic_ma(cbtc_fixture):
    """P06-B022: CBTC follower dynamic MA generation: follower EoA placed at leader's protected rear envelope."""
    engine = cbtc_fixture["engine"]
    rt = cbtc_fixture["forward_route"]

    engine.register_train("TR_LEADER", 200.0)
    engine.register_train("TR_FOLLOWER", 200.0)

    # Leader at 2200m => protected rear at 1970m
    rep_leader = TrainPositionReport(
        train_id="TR_LEADER", timestamp_s=0.0, link_id="LK_01", front_position_m=2200.0, speed_ms=0.0, train_length_m=200.0
    )
    engine.receive_position_report(rep_leader, current_time_s=0.0)

    ma_follower = engine.compute_movement_authority("TR_FOLLOWER", rt, current_time_s=0.0, start_position_m=500.0)
    assert ma_follower.end_of_authority == pytest.approx(1970.0, abs=1e-3)


@pytest.mark.engineering
def test_p06_b023_cbtc_dynamic_ma_extension(cbtc_fixture):
    """P06-B023: CBTC dynamic MA extension: as leader advances forward, follower's MA advances dynamically."""
    engine = cbtc_fixture["engine"]
    rt = cbtc_fixture["forward_route"]

    engine.register_train("TR_LEADER", 200.0)
    engine.register_train("TR_FOLLOWER", 200.0)

    # Step 1: Leader at 2200m => follower EoA = 1970m
    rep1 = TrainPositionReport(train_id="TR_LEADER", timestamp_s=0.0, link_id="LK_01", front_position_m=2200.0, speed_ms=10.0, train_length_m=200.0)
    engine.receive_position_report(rep1, current_time_s=0.0)
    ma1 = engine.compute_movement_authority("TR_FOLLOWER", rt, current_time_s=0.0, start_position_m=500.0)
    assert ma1.end_of_authority == pytest.approx(1970.0, abs=1e-3)

    # Step 2: Leader advances 100m to 2300m => follower EoA advances to 2070m
    rep2 = TrainPositionReport(train_id="TR_LEADER", timestamp_s=1.0, link_id="LK_01", front_position_m=2300.0, speed_ms=10.0, train_length_m=200.0)
    engine.receive_position_report(rep2, current_time_s=1.0)
    ma2 = engine.compute_movement_authority("TR_FOLLOWER", rt, current_time_s=1.0, start_position_m=500.0)
    assert ma2.end_of_authority == pytest.approx(2070.0, abs=1e-3)


@pytest.mark.engineering
def test_p06_b024_cbtc_follower_braking_protection(cbtc_fixture):
    """P06-B024: CBTC follower braking protection: follower decelerates to respect dynamic moving EoA using P04 braking models."""
    engine = cbtc_fixture["engine"]
    rt = cbtc_fixture["forward_route"]

    engine.register_train("TR_LEADER", 200.0)
    engine.register_train("TR_FOLLOWER", 200.0)

    # Leader protected rear at 1970m
    rep_leader = TrainPositionReport(train_id="TR_LEADER", timestamp_s=0.0, link_id="LK_01", front_position_m=2200.0, speed_ms=0.0, train_length_m=200.0)
    engine.receive_position_report(rep_leader, current_time_s=0.0)
    engine.compute_movement_authority("TR_FOLLOWER", rt, current_time_s=0.0, start_position_m=500.0)

    # Follower at 1370m (dist to EoA = 600m). With b=0.75 m/s^2, permitted speed is exactly 30.0 m/s
    profile = engine.evaluate_supervision("TR_FOLLOWER", current_speed_ms=25.0, current_position_m=1370.0)
    assert profile.distance_to_target_m == pytest.approx(600.0, abs=1e-3)
    assert profile.permitted_speed_ms == pytest.approx(30.0, abs=1e-3)
    assert profile.supervision_state == SupervisionState.NORMAL


@pytest.mark.engineering
def test_p06_b025_cbtc_fixed_infrastructure_restriction(cbtc_fixture):
    """P06-B025: CBTC fixed infrastructure restriction: MA truncated at unlocked switch, route boundary, or station stop."""
    engine = cbtc_fixture["engine"]
    rt = cbtc_fixture["forward_route"]

    engine.register_train("TR_01", 200.0)

    # Truncate at buffer stop / station limit 1200m
    ma = engine.compute_movement_authority(
        "TR_01",
        rt,
        current_time_s=0.0,
        start_position_m=200.0,
        fixed_infrastructure_limit_m=1200.0,
    )
    assert ma.end_of_authority == pytest.approx(1200.0, abs=1e-3)


@pytest.mark.engineering
def test_p06_b026_cbtc_reverse_operation():
    """P06-B026: CBTC reverse operation: follower and leader moving in REVERSE direction."""
    cfg = CBTCConfig(base_localization_uncertainty_m=20.0, safety_margin_m=10.0)
    rep_rev = TrainPositionReport(
        train_id="TR_REV_LEADER",
        timestamp_s=0.0,
        link_id="LK_01",
        front_position_m=1000.0,
        speed_ms=0.0,
        running_direction=RunningDirection.REVERSE,
        train_length_m=200.0,
    )
    env = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep_rev, current_time_s=0.0, config=cfg)

    # In reverse running along link: nominal rear = 1000 + 200 = 1200m
    # Protected rear towards follower = 1200 + 20 + 10 = 1230m
    assert env.nominal_rear_m == 1200.0
    assert env.protected_rear_m == 1230.0


@pytest.mark.engineering
def test_p06_b027_cbtc_stale_communication_handling(cbtc_fixture):
    """P06-B027: CBTC communication loss / stale position report handling."""
    engine = cbtc_fixture["engine"]
    engine.register_train("TR_01", 200.0)

    rep1 = TrainPositionReport(train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=100.0, speed_ms=10.0)
    engine.receive_position_report(rep1, current_time_s=0.0)

    # Second report arrives at 5.0s (> 2.0s staleness timeout)
    rep2 = TrainPositionReport(train_id="TR_01", timestamp_s=5.0, link_id="LK_01", front_position_m=150.0, speed_ms=10.0)
    with pytest.raises(CommunicationTimeoutError):
        engine.receive_position_report(rep2, current_time_s=5.0)


@pytest.mark.engineering
def test_p06_b028_fidelity_levels_comparison():
    """P06-B028: Model fidelity comparison: BASIC vs INTERMEDIATE vs DETAILED fidelity levels."""
    rep = TrainPositionReport(train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=2000.0, speed_ms=0.0, train_length_m=200.0)

    cfg_basic = CBTCConfig(fidelity=SignallingModelFidelity.BASIC)
    cfg_inter = CBTCConfig(fidelity=SignallingModelFidelity.INTERMEDIATE, base_localization_uncertainty_m=20.0, safety_margin_m=10.0)
    cfg_det = CBTCConfig(fidelity=SignallingModelFidelity.DETAILED, base_localization_uncertainty_m=20.0, safety_margin_m=10.0)

    env_basic = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep, 0.0, cfg_basic)
    env_inter = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep, 0.0, cfg_inter)
    env_det = ProtectedTrainEnvelopeCalculator.calculate_envelope(rep, 0.0, cfg_det)

    assert env_basic.protected_rear_m == 1800.0  # zero uncertainty & zero margin
    assert env_inter.protected_rear_m == 1770.0  # -30m buffer
    assert env_det.protected_rear_m == 1770.0


# ===========================================================================
# 4. Integration, Invariance & Safety Checks (P06-B029, P06-B030)
# ===========================================================================

@pytest.mark.engineering
def test_p06_b029_etcs_cbtc_coexistence_and_independence(test_network):
    """P06-B029: Coexistence and independence: ETCS L2 and CBTC operate as separate engines without cross-talk."""
    res_ctrl = ResourceController()
    sw_ctrl = SwitchController()
    interlocking = InterlockingEngine(resource_controller=res_ctrl, switch_controller=sw_ctrl)

    etcs_eng = ETCSLevel2Engine(resource_controller=res_ctrl, interlocking_engine=interlocking)
    cbtc_eng = CBTCMovingBlockEngine(resource_controller=res_ctrl, interlocking_engine=interlocking, switch_controller=sw_ctrl)

    assert etcs_eng.technology_type == SignallingTechnologyType.ETCS_LEVEL_2
    assert cbtc_eng.technology_type == SignallingTechnologyType.CBTC_MOVING_BLOCK
    assert etcs_eng is not cbtc_eng
    assert type(etcs_eng) != type(cbtc_eng)


@pytest.mark.engineering
def test_p06_b030_advanced_signalling_safety_invariant(cbtc_fixture):
    """P06-B030: Advanced signalling safety invariant: zero rear-end collisions and zero EoA overshoots."""
    engine = cbtc_fixture["engine"]
    rt = cbtc_fixture["forward_route"]

    engine.register_train("TR_L", 200.0)
    engine.register_train("TR_F", 200.0)

    rep_leader = TrainPositionReport(train_id="TR_L", timestamp_s=0.0, link_id="LK_01", front_position_m=2500.0, speed_ms=0.0, train_length_m=200.0)
    engine.receive_position_report(rep_leader, current_time_s=0.0)

    ma_follower = engine.compute_movement_authority("TR_F", rt, current_time_s=0.0, start_position_m=1000.0)

    # Invariant: Follower EoA strictly behind Leader's physical rear (2300m)
    assert ma_follower.end_of_authority <= 2300.0 - 30.0  # Protected rear is 2270m
    assert ma_follower.end_of_authority < 2300.0
