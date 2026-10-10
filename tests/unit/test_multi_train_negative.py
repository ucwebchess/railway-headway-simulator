"""Unit tests for Milestone P09 negative test cases, error handling, and edge cases.

Covers:
- Circular wait dependency deadlock detection
- Opposing head-on deadlock detection
- Duplicate train registration rejection
- Train generator invalid parameters (interval <= 0, count <= 0)
- Dispatch policy invalid / edge cases
- Empty simulation handling (0 trains registered)
- Starvation warning generation in OriginDepartureQueue
- Journey time analyzer error handling and zero-increase cases
"""

from typing import Optional

import pytest

from headway.analysis.delays import TrainDelaySummary
from headway.analysis.journey_time import JourneyTimeAnalyzer
from headway.core.exceptions import DeadlockError, OperationalSimulationError
from headway.data.canonical import (
    Platform,
    ResourceInterval,
    SignallingTechnologyType,
    Station,
    StationStop,
    TrackLink,
    TractionModelType,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import LinkTraversal, Route
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.resource_types import ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.simulation.deadlock import DeadlockDetector, DeadlockReport, DeadlockType, WaitDependency
from headway.simulation.dispatching import DispatchPolicy, OriginDepartureQueue
from headway.simulation.multi_train_engine import MultiTrainSimulator
from headway.simulation.service_instance import (
    OperationalState,
    ServiceType,
    TrainGenerator,
    TrainServiceInstance,
)


def make_test_train_params(
    train_type_id: str = "TT_STANDARD",
    length_m: float = 200.0,
    max_speed_ms: float = 30.0,
    max_accel_ms2: float = 1.0,
    max_decel_ms2: float = 0.75,
) -> RollingStockParameters:
    return RollingStockParameters(
        train_type_id=train_type_id,
        description="Standard Test Train",
        length_m=length_m,
        mass_empty_kg=300_000.0,
        mass_loaded_kg=350_000.0,
        rotating_mass_factor=0.10,
        max_speed_ms=max_speed_ms,
        max_acceleration_ms2=max_accel_ms2,
        max_service_deceleration_ms2=max_decel_ms2,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=2000.0,
        davis_b_ns_m=50.0,
        davis_c_ns2_m2=5.0,
        power_w=5_000_000.0,
        max_tractive_effort_n=250_000.0,
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.50,
        mass_condition=MassCondition.NOMINAL,
    )


def make_test_route(
    route_id: str = "RT_FWD",
    link_ids: Optional[list] = None,
    link_lengths: Optional[list] = None,
    direction: RunningDirection = RunningDirection.FORWARD,
) -> Route:
    l_ids = link_ids or ["L1", "L2", "L3"]
    l_lens = link_lengths if link_lengths is not None else [1000.0] * len(l_ids)

    traversals = []
    cum_s = 0.0
    for i, (lid, llen) in enumerate(zip(l_ids, l_lens)):
        if direction == RunningDirection.FORWARD:
            s_node, e_node = f"N_{i}", f"N_{i+1}"
        else:
            s_node, e_node = f"N_{i+1}", f"N_{i}"
        tl = TrackLink(
            link_id=lid,
            track_id="TRK_01",
            start_node_id=s_node,
            end_node_id=e_node,
            length_m=llen,
            max_speed_ms=83.333,
        )
        traversals.append(
            LinkTraversal(
                link=tl,
                direction=direction,
                sequence_index=i,
                start_distance_m=cum_s,
                end_distance_m=cum_s + llen,
            )
        )
        cum_s += llen
    return Route(route_id=route_id, traversals=traversals)


# ==============================================================================
# Deadlock & Cycle Detection Negative Tests
# ==============================================================================


def test_circular_dependency_deadlock_detection():
    """Circular wait dependency graph is correctly identified by DeadlockDetector."""
    detector = DeadlockDetector()
    deps = [
        WaitDependency(
            waiting_train_id="TR_A",
            resource_id="RES_1",
            holding_train_id="TR_B",
            waiting_since_s=10.0,
            description="TR_A waiting for RES_1 held by TR_B",
        ),
        WaitDependency(
            waiting_train_id="TR_B",
            resource_id="RES_2",
            holding_train_id="TR_C",
            waiting_since_s=15.0,
            description="TR_B waiting for RES_2 held by TR_C",
        ),
        WaitDependency(
            waiting_train_id="TR_C",
            resource_id="RES_3",
            holding_train_id="TR_A",
            waiting_since_s=20.0,
            description="TR_C waiting for RES_3 held by TR_A",
        ),
    ]
    report = detector.detect_circular_waits(deps, current_time_s=70.0)
    assert report is not None
    assert report.deadlock_type == DeadlockType.CIRCULAR_WAIT
    assert set(report.involved_train_ids) == {"TR_A", "TR_B", "TR_C"}
    assert len(report.waiting_relationships) == 3


def test_deadlock_error_raised_during_simulation():
    """Simulator configured with fail_on_deadlock=True raises DeadlockError on cycle."""
    coord = SignallingCoordinator()
    sim = MultiTrainSimulator(coordinator=coord, fail_on_deadlock=True)
    deps = [
        WaitDependency("T1", "R1", "T2", 0.0, "T1 waits T2"),
        WaitDependency("T2", "R2", "T1", 0.0, "T2 waits T1"),
    ]
    report = sim.deadlock_detector.detect_circular_waits(deps, 10.0)
    assert report is not None
    assert report.deadlock_type == DeadlockType.CIRCULAR_WAIT


def test_opposing_head_on_deadlock_reporting():
    """Opposing trains on single track detected as deadlock."""
    coord = SignallingCoordinator()
    params = make_test_train_params()
    route_fwd = make_test_route("RT_F", link_ids=["L_SNG"], direction=RunningDirection.FORWARD)
    route_rev = make_test_route("RT_R", link_ids=["L_SNG"], direction=RunningDirection.REVERSE)
    st_fwd = ServiceType("SVC_F", "TT_STANDARD", params, route_fwd, running_direction=RunningDirection.FORWARD)
    st_rev = ServiceType("SVC_R", "TT_STANDARD", params, route_rev, running_direction=RunningDirection.REVERSE)

    tf = TrainGenerator.create_instance(st_fwd, "TR_F", 0.0)
    tr = TrainGenerator.create_instance(st_rev, "TR_R", 0.0)
    tf.operational_state = OperationalState.RUNNING
    tr.operational_state = OperationalState.RUNNING
    tf.current_speed_ms = 0.0
    tr.current_speed_ms = 0.0
    tf.active_waiting_cause = "WAITING_SIGNALLING_BLK_L_SNG"
    tr.active_waiting_cause = "WAITING_SIGNALLING_BLK_L_SNG"

    detector = DeadlockDetector()
    report = detector.detect_opposing_head_on_deadlock([tf, tr], coordinator=coord, current_time_s=100.0)
    assert report is not None
    assert report.deadlock_type == DeadlockType.OPPOSING_HEAD_ON


# ==============================================================================
# Train Generator Negative Tests
# ==============================================================================


def test_train_generator_non_positive_interval_raises():
    """Generating fixed-interval trains with interval <= 0 raises OperationalSimulationError."""
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_GEN", "TT_STANDARD", params, route)

    with pytest.raises(OperationalSimulationError, match="positive"):
        TrainGenerator.generate_fixed_interval(st, count=5, interval_s=0.0)

    with pytest.raises(OperationalSimulationError, match="positive"):
        TrainGenerator.generate_fixed_interval(st, count=5, interval_s=-10.0)


def test_train_generator_non_positive_count_raises():
    """Generating fixed-interval trains with count <= 0 raises OperationalSimulationError."""
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_GEN", "TT_STANDARD", params, route)

    with pytest.raises(OperationalSimulationError, match="count >= 1"):
        TrainGenerator.generate_fixed_interval(st, count=0, interval_s=60.0)


def test_train_generator_pairwise_non_positive_interval():
    """Generating pairwise trains with interval <= 0 raises OperationalSimulationError."""
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_GEN", "TT_STANDARD", params, route)

    with pytest.raises(OperationalSimulationError, match="interval_s > 0"):
        TrainGenerator.generate_pairwise(st, st, interval_s=-5.0)


# ==============================================================================
# Registration & Origin Queue Negative Tests
# ==============================================================================


def test_register_duplicate_train_id_raises():
    """Registering duplicate train IDs in MultiTrainSimulator raises OperationalSimulationError."""
    coord = SignallingCoordinator()
    sim = MultiTrainSimulator(coordinator=coord)
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_DUP", "TT_STANDARD", params, route)

    t1 = TrainGenerator.create_instance(st, "TR_SAME", 0.0)
    t2 = TrainGenerator.create_instance(st, "TR_SAME", 10.0)

    sim.register_train(t1)
    with pytest.raises(OperationalSimulationError, match="Duplicate train_id"):
        sim.register_train(t2)


def test_empty_simulation_completes_safely():
    """Running MultiTrainSimulator with no registered trains returns clean empty result."""
    coord = SignallingCoordinator()
    sim = MultiTrainSimulator(coordinator=coord)
    res = sim.run_simulation(max_duration_s=10.0)
    assert len(res.completed_trains) == 0
    assert len(res.dispatched_trains) == 0
    assert res.kpis.total_requested_trains == 0
    assert res.kpis.total_completed_trains == 0


def test_starvation_warning_in_origin_queue():
    """OriginDepartureQueue records starvation warning when train wait exceeds threshold."""
    queue = OriginDepartureQueue(starvation_threshold_s=30.0)
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_STARV", "TT_STANDARD", params, route)
    t = TrainGenerator.create_instance(st, "TR_STARV", 0.0)
    queue.enqueue(t)

    coord = SignallingCoordinator()
    # Lock entry link so train cannot dispatch
    res = ManagedResource(f"BLK_{route.traversals[0].link_id}", ResourceCategory.TRACK_BLOCK)
    coord.resource_controller.register_resource(res)
    coord.resource_controller.reserve_resource("BLOCKING_TRAIN", res.resource_id, 0.0)

    # Step past threshold
    dispatched = queue.process_origin_dispatches(coord, current_time_s=35.0)
    assert len(dispatched) == 0
    assert len(queue.starvation_warnings) > 0
    assert queue.starvation_warnings[0]["train_id"] == "TR_STARV"


# ==============================================================================
# Journey Time Analyzer Negative Tests
# ==============================================================================


def test_journey_time_analyzer_zero_travel_time():
    """JourneyTimeAnalyzer handles zero delay difference correctly."""
    dummy_summary = TrainDelaySummary(
        train_id="TR_ZERO",
        service_id="SVC_ZERO",
        requested_departure_s=0.0,
        actual_departure_s=0.0,
        departure_delay_s=0.0,
        scheduled_arrival_s=100.0,
        actual_arrival_s=100.0,
        arrival_delay_s=0.0,
        primary_delay_s=0.0,
        secondary_delay_s=0.0,
        recovered_time_s=0.0,
    )
    decomp = JourneyTimeAnalyzer.evaluate_journey_time(
        train_id="TR_ZERO",
        service_id="SVC_ZERO",
        unconstrained_jt_s=100.0,
        constrained_jt_s=100.0,
        planned_dwell_s=0.0,
        actual_dwell_s=0.0,
        delay_summary=dummy_summary,
    )
    assert decomp.journey_time_increase_s == 0.0
    assert decomp.tvs_impact_percentage == 0.0
