"""Comprehensive negative test suite for Milestone P06: ETCS Level 2 & CBTC Moving-Block Signalling.

Verifies strict rejection of invalid configurations, non-physical states, communication timeouts,
non-monotonic extensions, and braking feasibility violations.
"""

import pytest

from headway.data.canonical import (
    Node,
    NodeType,
    Track,
    TrackDirectionality,
    TrackLink,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import RouteEngine
from headway.rolling_stock.braking import ConstantDecelerationBrakingModel
from headway.signalling.advanced_types import (
    RadioCommunicationConfig,
    SignallingModelFidelity,
    TrainIntegrityStatus,
    TrainPositionReport,
)
from headway.signalling.cbtc import CBTCConfig, CBTCMovingBlockEngine
from headway.signalling.etcs import ETCSLevel2Config, ETCSLevel2Engine
from headway.signalling.interlocking import InterlockingEngine
from headway.signalling.resource_types import (
    AdvancedSignallingError,
    BrakingFeasibilityError,
    CommunicationTimeoutError,
    MovementAuthorityError,
    PositionReportError,
    ProtectedEnvelopeError,
)
from headway.signalling.resources import ResourceController
from headway.signalling.switches import SwitchController


@pytest.fixture
def test_route():
    """Minimal single-link route for negative testing."""
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="N1", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="N2", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(TrackLink(link_id="LK_01", track_id="TRK_01", start_node_id="N1", end_node_id="N2", length_m=2000.0, max_speed_ms=40.0))
    route_engine = RouteEngine(graph)
    return route_engine.build_route_from_traversals("RT_01", [("LK_01", RunningDirection.FORWARD)])


# ===========================================================================
# 1. Configuration Validation Negative Tests
# ===========================================================================

def test_negative_communication_config_latencies():
    """Reject negative communication latencies and invalid timeouts."""
    with pytest.raises(AdvancedSignallingError, match="non-negative"):
        RadioCommunicationConfig(uplink_latency_s=-0.1)

    with pytest.raises(AdvancedSignallingError, match="non-negative"):
        RadioCommunicationConfig(processing_delay_s=-0.5)

    with pytest.raises(AdvancedSignallingError, match="non-negative"):
        RadioCommunicationConfig(downlink_latency_s=-0.2)

    with pytest.raises(AdvancedSignallingError, match="positive"):
        RadioCommunicationConfig(timeout_s=0.0)

    with pytest.raises(AdvancedSignallingError, match="positive"):
        RadioCommunicationConfig(timeout_s=-2.0)


def test_negative_etcs_config():
    """Reject non-physical ETCS L2 configuration parameters."""
    with pytest.raises(MovementAuthorityError, match="non-negative"):
        ETCSLevel2Config(default_overlap_m=-10.0)

    with pytest.raises(MovementAuthorityError, match="strictly positive"):
        ETCSLevel2Config(service_deceleration_ms2=0.0)

    with pytest.raises(MovementAuthorityError, match="strictly positive"):
        ETCSLevel2Config(emergency_deceleration_ms2=-1.0)


def test_negative_cbtc_config():
    """Reject non-physical CBTC configuration parameters."""
    with pytest.raises(ProtectedEnvelopeError, match="non-negative"):
        CBTCConfig(base_localization_uncertainty_m=-5.0)

    with pytest.raises(ProtectedEnvelopeError, match="non-negative"):
        CBTCConfig(safety_margin_m=-1.0)

    with pytest.raises(MovementAuthorityError, match="strictly positive"):
        CBTCConfig(service_deceleration_ms2=-0.5)


# ===========================================================================
# 2. Train Position Report Negative Tests
# ===========================================================================

def test_negative_position_report_front_position():
    """Reject negative train front coordinate."""
    with pytest.raises(PositionReportError, match="Front position must be non-negative"):
        TrainPositionReport(
            train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=-10.0, speed_ms=10.0
        )


def test_negative_position_report_speed():
    """Reject negative train speed."""
    with pytest.raises(PositionReportError, match="speed must be non-negative"):
        TrainPositionReport(
            train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=100.0, speed_ms=-5.0
        )


def test_negative_position_report_train_length():
    """Reject zero or negative train length."""
    with pytest.raises(PositionReportError, match="length must be positive"):
        TrainPositionReport(
            train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=100.0, speed_ms=10.0, train_length_m=0.0
        )

    with pytest.raises(PositionReportError, match="length must be positive"):
        TrainPositionReport(
            train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=100.0, speed_ms=10.0, train_length_m=-150.0
        )


def test_negative_position_report_uncertainty():
    """Reject negative localization uncertainty."""
    with pytest.raises(PositionReportError, match="uncertainty must be non-negative"):
        TrainPositionReport(
            train_id="TR_01", timestamp_s=0.0, link_id="LK_01", front_position_m=100.0, speed_ms=10.0, localization_uncertainty_m=-2.0
        )


def test_negative_position_report_age_time_travel():
    """Reject simulation time preceding report timestamp."""
    rep = TrainPositionReport(
        train_id="TR_01", timestamp_s=50.0, link_id="LK_01", front_position_m=500.0, speed_ms=20.0
    )
    with pytest.raises(PositionReportError, match="cannot precede report timestamp"):
        rep.get_age_s(current_time_s=45.0)


# ===========================================================================
# 3. ETCS Level 2 Operational Negative Tests
# ===========================================================================

def test_etcs_supervision_without_active_ma():
    """Reject supervision evaluation when no MA exists for train."""
    engine = ETCSLevel2Engine()
    engine.register_train("TR_01", 200.0)

    with pytest.raises(MovementAuthorityError, match="no active MA"):
        engine.evaluate_supervision("TR_01", current_speed_ms=20.0, current_position_m=500.0)


def test_etcs_create_target_without_active_ma():
    """Reject braking target conversion when no MA exists."""
    engine = ETCSLevel2Engine()
    engine.register_train("TR_01", 200.0)

    with pytest.raises(MovementAuthorityError, match="no active Movement Authority"):
        engine.create_braking_target("TR_01")


def test_etcs_stopping_feasibility_without_active_ma():
    """Reject feasibility check when train has no active MA."""
    engine = ETCSLevel2Engine()
    engine.register_train("TR_01", 200.0)
    model = ConstantDecelerationBrakingModel(service_deceleration_ms2=0.75, emergency_deceleration_ms2=1.0)

    with pytest.raises(MovementAuthorityError, match="no active Movement Authority"):
        engine.validate_stopping_feasibility("TR_01", current_speed_ms=20.0, current_position_m=500.0, braking_model=model)


def test_etcs_ma_extension_without_active_ma():
    """Reject MA extension if train has never been issued an initial MA."""
    engine = ETCSLevel2Engine()
    engine.register_train("TR_01", 200.0)

    with pytest.raises(MovementAuthorityError, match="No active ETCS L2 Movement Authority"):
        engine.rbc.extend_movement_authority("TR_01", new_end_of_authority=1500.0, current_time_s=10.0)


def test_etcs_ma_extension_cannot_retract_eoa(test_route):
    """Reject MA extension that attempts to decrease the End of Authority."""
    engine = ETCSLevel2Engine()
    engine.register_train("TR_01", 200.0)
    engine.compute_movement_authority("TR_01", test_route, current_time_s=10.0)

    # Initial EoA is 2000m. Trying to extend to 1500m must raise error.
    with pytest.raises(MovementAuthorityError, match="cannot retract EoA"):
        engine.rbc.extend_movement_authority("TR_01", new_end_of_authority=1500.0, current_time_s=12.0)


def test_etcs_insufficient_stopping_distance(test_route):
    """Reject operation where train speed exceeds stopping capability before EoA."""
    engine = ETCSLevel2Engine()
    engine.register_train("TR_01", 200.0)
    engine.compute_movement_authority("TR_01", test_route, current_time_s=10.0)

    model = ConstantDecelerationBrakingModel(service_deceleration_ms2=0.75, emergency_deceleration_ms2=1.0)

    # Train at 1950m travelling at 30 m/s (needs 600m to stop, only 50m available)
    with pytest.raises(BrakingFeasibilityError, match="Insufficient braking distance"):
        engine.validate_stopping_feasibility("TR_01", current_speed_ms=30.0, current_position_m=1950.0, braking_model=model)


# ===========================================================================
# 4. CBTC Moving-Block Operational Negative Tests
# ===========================================================================

def test_cbtc_envelope_without_report():
    """Reject envelope calculation for train with no position reports."""
    engine = CBTCMovingBlockEngine()
    engine.register_train("TR_01", 200.0)

    with pytest.raises(ProtectedEnvelopeError, match="No position report available"):
        engine.compute_protected_envelope("TR_01", current_time_s=1.0)


def test_cbtc_supervision_without_active_ma():
    """Reject CBTC supervision evaluation when no MA exists."""
    engine = CBTCMovingBlockEngine()
    engine.register_train("TR_01", 200.0)

    with pytest.raises(MovementAuthorityError, match="no active CBTC MA"):
        engine.evaluate_supervision("TR_01", current_speed_ms=20.0, current_position_m=500.0)


def test_cbtc_feasibility_without_active_ma():
    """Reject CBTC feasibility check when train has no active MA."""
    engine = CBTCMovingBlockEngine()
    engine.register_train("TR_01", 200.0)
    model = ConstantDecelerationBrakingModel(service_deceleration_ms2=0.75, emergency_deceleration_ms2=1.0)

    with pytest.raises(MovementAuthorityError, match="no active CBTC Movement Authority"):
        engine.validate_stopping_feasibility("TR_01", current_speed_ms=20.0, current_position_m=500.0, braking_model=model)


def test_cbtc_follower_insufficient_stopping_distance(test_route):
    """Reject follower operation when follower is too close to leader's protected envelope at speed."""
    engine = CBTCMovingBlockEngine()
    engine.register_train("TR_L", 200.0)
    engine.register_train("TR_F", 200.0)

    # Leader at 1000m => protected rear at 770m
    rep_leader = TrainPositionReport(train_id="TR_L", timestamp_s=0.0, link_id="LK_01", front_position_m=1000.0, speed_ms=0.0, train_length_m=200.0)
    engine.receive_position_report(rep_leader, current_time_s=0.0)
    engine.compute_movement_authority("TR_F", test_route, current_time_s=0.0, start_position_m=700.0)

    model = ConstantDecelerationBrakingModel(service_deceleration_ms2=0.75, emergency_deceleration_ms2=1.0)

    # Follower at 720m (only 50m to EoA=770m), but running at 25 m/s (needs > 400m to stop)
    with pytest.raises(BrakingFeasibilityError, match="Insufficient braking distance to dynamic EoA"):
        engine.validate_stopping_feasibility("TR_F", current_speed_ms=25.0, current_position_m=720.0, braking_model=model)
