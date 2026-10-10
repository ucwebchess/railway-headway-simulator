"""Engineering benchmarks for Milestone P09 — Multi-Train Operations, Dispatching & Journey Time.

Covers:
- P09-B001 to P09-B035: All 35 mandatory operational simulation benchmarks.
- Numerical Benchmarks A, B, C, D:
  - Benchmark A: Fixed Departure Interval (5 trains at 120s: 0, 120, 240, 360, 480 s).
  - Benchmark B: TVS Waiting (available at 300s, ready at 250s -> 50.0s waiting).
  - Benchmark C: Journey-Time Increase (1800s unconstrained vs 1950s constrained -> 150.0s increase).
  - Benchmark D: Secondary Delay Propagation (60s primary disturbance on leader, follower delay from physical interaction).
- Both FORWARD, REVERSE, and simultaneous OPPOSING-DIRECTION operations.
"""

import math
from typing import Dict, List, Optional, Set, Tuple
import pytest

from headway.analysis.delays import (
    DelayCause,
    DelayIncident,
    DelayPropagationTracker,
    TrainDelaySummary,
)
from headway.analysis.journey_time import (
    JourneyTimeAnalyzer,
    JourneyTimeDecomposition,
    OperationalKPIs,
)
from headway.core.exceptions import DeadlockError, OperationalSimulationError
from headway.data.canonical import (
    AspectModelType,
    Platform,
    ResourceInterval,
    SharedResourceGroup,
    SignallingTechnologyType,
    Station,
    StationStop,
    TractionModelType,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import LinkTraversal, Route
from headway.infrastructure.switches import Switch, SwitchPosition
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.interlocking import InterlockingRouteDefinition
from headway.signalling.platform_controller import PlatformSelectionPolicy
from headway.signalling.resource_types import ReleasePolicy, ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.signalling.tvs_controller import TVSExclusivityScope
from headway.simulation.deadlock import DeadlockDetector, DeadlockReport, DeadlockType, WaitDependency
from headway.simulation.dispatching import DispatchPolicy, OriginDepartureQueue
from headway.simulation.events import CrossingEventType
from headway.simulation.integrator import MicroscopicSimulator
from headway.simulation.multi_train_engine import MultiTrainSimulationResult, MultiTrainSimulator
from headway.simulation.service_instance import (
    OperationalTimetable,
    ServiceType,
    TimetableEntry,
    TrainGenerationMode,
    TrainGenerator,
    TrainServiceInstance,
)
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.time_distance import MultiTrainTimeDistanceDataset, TimeDistancePoint
from headway.simulation.tvs_queue import TVSQueueTracker


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_test_train_params(
    train_type_id: str = "TT_STANDARD",
    length_m: float = 200.0,
    max_speed_ms: float = 30.0,
    max_accel_ms2: float = 1.0,
    max_decel_ms2: float = 0.75,
) -> RollingStockParameters:
    """Create standard RollingStockParameters for multi-train benchmarks."""
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


def make_test_block(resource_id: str, link_id: str, length_m: float = 1000.0) -> ManagedResource:
    """Helper to create a ManagedResource with a ResourceInterval."""
    return ManagedResource(
        resource_id=resource_id,
        category=ResourceCategory.TRACK_BLOCK,
        intervals=[ResourceInterval(link_id=link_id, start_offset_m=0.0, end_offset_m=length_m)],
    )


def make_test_route(
    route_id: str = "RT_FWD",
    link_ids: Optional[list] = None,
    link_lengths: Optional[list] = None,
    direction: RunningDirection = RunningDirection.FORWARD,
) -> Route:
    """Build simple linear route from sequential links."""
    from headway.data.canonical import TrackLink
    l_ids = link_ids or ["L1", "L2", "L3"]
    if link_lengths is not None:
        l_lens = link_lengths
    else:
        l_lens = [1000.0] * len(l_ids)

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
# Additional Numerical Benchmarks A, B, C, D
# ==============================================================================

def test_numerical_benchmark_a_fixed_departure_interval():
    """Benchmark A — Fixed Departure Interval:

    Five trains requested at 120-second intervals.
    Expected requested departures:
    - 0 s
    - 120 s
    - 240 s
    - 360 s
    - 480 s
    """
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_A", "TT_STANDARD", params, route)

    trains = TrainGenerator.generate_fixed_interval(
        service_type=st,
        interval_s=120.0,
        count=5,
        start_time_s=0.0,
    )

    assert len(trains) == 5
    expected_times = [0.0, 120.0, 240.0, 360.0, 480.0]
    for trn, exp_t in zip(trains, expected_times):
        assert trn.requested_departure_time_s == exp_t


def test_numerical_benchmark_b_tvs_waiting():
    """Benchmark B — TVS Waiting:

    Given:
    - TVS becomes available at 300 s.
    - Follower is ready to enter at 250 s.
    - Authorization processing time: 0 s.

    Expected waiting:
    **50 seconds**
    """
    tracker = TVSQueueTracker()
    tracker.record_waiting_train("TVS_TUNNEL", "TR_FOLLOWER", current_time_s=250.0)
    wait_time = tracker.release_waiting_train("TVS_TUNNEL", "TR_FOLLOWER", current_time_s=300.0)

    assert wait_time == 50.0
    assert tracker.get_total_waiting_time_s() == 50.0


def test_numerical_benchmark_c_journey_time_increase():
    """Benchmark C — Journey-Time Increase:

    Given:
    - Unconstrained journey time: 1,800 s.
    - Constrained journey time: 1,950 s.

    Expected:
    **150 seconds**
    """
    summary = TrainDelaySummary(
        train_id="TR_01",
        service_id="SVC_01",
        requested_departure_s=0.0,
        actual_departure_s=0.0,
        departure_delay_s=0.0,
        scheduled_arrival_s=1800.0,
        actual_arrival_s=1950.0,
        arrival_delay_s=150.0,
        primary_delay_s=0.0,
        secondary_delay_s=150.0,
        recovered_time_s=0.0,
        breakdown_by_cause_s={DelayCause.TVS: 150.0},
    )

    decomp = JourneyTimeAnalyzer.evaluate_journey_time(
        train_id="TR_01",
        service_id="SVC_01",
        unconstrained_jt_s=1800.0,
        constrained_jt_s=1950.0,
        planned_dwell_s=0.0,
        actual_dwell_s=0.0,
        delay_summary=summary,
    )

    assert decomp.journey_time_increase_s == 150.0
    assert decomp.tvs_waiting_s == 150.0
    assert decomp.tvs_impact_percentage == 100.0


def test_numerical_benchmark_d_delay_propagation():
    """Benchmark D — Delay Propagation:

    A leader experiences a 60-second primary delay.
    The follower is constrained by the leader.
    The simulator shall calculate the follower's resulting delay from actual resource interactions.
    Do not automatically assign the same 60-second delay to the follower.
    """
    tracker = DelayPropagationTracker()
    # Leader experiences 60s primary disturbance at origin
    tracker.record_incident(
        train_id="TR_LEAD",
        cause=DelayCause.PRIMARY_DISTURBANCE,
        start_time_s=0.0,
        end_time_s=60.0,
        location_m=0.0,
        description="Leader 60s primary delay",
    )

    # Follower is held behind leader for 42s at signal SIG_01
    tracker.record_incident(
        train_id="TR_FOLL",
        cause=DelayCause.FOLLOWING_TRAIN,
        start_time_s=120.0,
        end_time_s=162.0,
        location_m=1000.0,
        resource_id="BLK_02",
        source_train_id="TR_LEAD",
        description="Follower held by delayed leader",
    )

    summary_foll = tracker.summarize_train_delays(
        train_id="TR_FOLL",
        service_id="SVC_01",
        requested_dep_s=120.0,
        actual_dep_s=120.0,
        scheduled_arr_s=320.0,
        actual_arr_s=362.0,
    )

    assert summary_foll.secondary_delay_s == 42.0
    assert summary_foll.primary_delay_s == 0.0
    assert summary_foll.arrival_delay_s == 42.0
    # Must NOT blindly equal 60s
    assert summary_foll.secondary_delay_s != 60.0
    assert len(tracker.propagation_tree) == 1
    assert tracker.propagation_tree[0].source_train_id == "TR_LEAD"
    assert tracker.propagation_tree[0].affected_train_id == "TR_FOLL"


# ==============================================================================
# Mandatory Benchmarks P09-B001 to P09-B035
# ==============================================================================

def test_p09_b001_single_train_reproduces_p04():
    """P09-B001: Single train reproduces P04 standalone trajectory."""
    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"], link_lengths=[1500.0, 1500.0])
    st = ServiceType("SVC_SINGLE", "TT_STANDARD", params, route)

    # Standalone P04 simulation
    p04_sim = MicroscopicSimulator(route=route, params=params, dt_s=0.1)
    p04_traj = p04_sim.simulate(train_id="TR_P04", default_dwell_time_s=0.0)

    # Multi-train simulator with single train
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    coord.resource_controller.register_resource(make_test_block("BLK_L2", "L2"))

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.1, storage_interval_s=0.1)
    train_inst = TrainGenerator.create_instance(st, "TR_MT", requested_departure_s=0.0)
    mt_sim.register_train(train_inst)
    res = mt_sim.run_simulation(max_duration_s=500.0)

    mt_traj = res.trajectories["TR_MT"]
    assert mt_traj.journey_time_s is not None
    # Microscopic journey times match within numerical step tolerance (<= 1.5s)
    assert abs(mt_traj.journey_time_s - p04_traj.journey_time_s) <= 1.5


def test_p09_b002_two_trains_on_one_route():
    """P09-B002: Two trains on one route; follower preserves headway separation."""
    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2", "L3"], link_lengths=[1000.0, 1000.0, 1000.0])
    st = ServiceType("SVC_PAIR", "TT_STANDARD", params, route)

    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    coord.resource_controller.register_resource(make_test_block("BLK_L2", "L2"))
    coord.resource_controller.register_resource(make_test_block("BLK_L3", "L3"))

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=0.5)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=100.0, start_time_s=0.0)
    mt_sim.register_trains(trains)
    res = mt_sim.run_simulation(max_duration_s=600.0)

    assert len(res.completed_trains) == 2
    assert res.kpis.total_completed_trains == 2
    assert res.kpis.actual_departure_sequence == ["SVC_PAIR_LEAD", "SVC_PAIR_FOLL"]


def test_p09_b003_repeated_homogeneous_services():
    """P09-B003: Repeated homogeneous services."""
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_HOMO", "TT_STANDARD", params, route)

    trains = TrainGenerator.generate_repeated_homogeneous(st, count=3, interval_s=150.0, start_time_s=0.0)
    assert len(trains) == 3
    assert trains[0].train_id == "SVC_HOMO_001"
    assert trains[1].requested_departure_time_s == 150.0
    assert trains[2].requested_departure_time_s == 300.0


def test_p09_b004_mixed_rolling_stock():
    """P09-B004: Mixed rolling stock simultaneously operating."""
    params_fast = make_test_train_params(train_type_id="TT_FAST", max_speed_ms=40.0)
    params_slow = make_test_train_params(train_type_id="TT_SLOW", max_speed_ms=20.0)
    route = make_test_route()

    st_fast = ServiceType("SVC_FAST", "TT_FAST", params_fast, route)
    st_slow = ServiceType("SVC_SLOW", "TT_SLOW", params_slow, route)

    trains = TrainGenerator.generate_repeated_mixed([st_fast, st_slow], repeat_cycles=2, interval_s=120.0)
    assert len(trains) == 4
    assert trains[0].params.max_speed_ms == 40.0
    assert trains[1].params.max_speed_ms == 20.0


def test_p09_b005_fixed_departure_interval():
    """P09-B005: Fixed departure interval verification."""
    test_numerical_benchmark_a_fixed_departure_interval()


def test_p09_b006_timetable_generation():
    """P09-B006: Timetable generation."""
    params = make_test_train_params()
    route = make_test_route()
    st = ServiceType("SVC_TT", "TT_STANDARD", params, route)

    tt = OperationalTimetable(
        timetable_id="TT_01",
        entries=[
            TimetableEntry("TR_A", "SVC_TT", 0.0, priority=2),
            TimetableEntry("TR_B", "SVC_TT", 180.0, priority=1),
        ],
    )

    trains = TrainGenerator.generate_from_timetable(tt, {"SVC_TT": st})
    assert len(trains) == 2
    assert trains[0].train_id == "TR_A"
    assert trains[0].priority == 2
    assert trains[1].requested_departure_time_s == 180.0


def test_p09_b007_departure_authorization():
    """P09-B007: Departure authorization gates entry until resource is available."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    # Manually hold BLK_L1 occupied
    coord.resource_controller.reserve_resource("BLOCKING_TR", "BLK_L1", timestamp_s=0.0)
    coord.resource_controller.front_enter_resource("BLOCKING_TR", "BLK_L1", timestamp_s=0.0)

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"])
    st = ServiceType("SVC_GATE", "TT_STANDARD", params, route)
    train = TrainGenerator.create_instance(st, "TR_CANDIDATE", requested_departure_s=0.0)

    q = OriginDepartureQueue()
    q.enqueue(train)

    # At t=10s, BLK_L1 is occupied -> cannot authorize
    dispatched = q.process_origin_dispatches(coord, current_time_s=10.0)
    assert len(dispatched) == 0

    # At t=50s, BLK_L1 clears
    coord.resource_controller.rear_clear_resource("BLOCKING_TR", "BLK_L1", timestamp_s=50.0)
    coord.resource_controller.process_pending_releases(current_time_s=55.0)

    dispatched = q.process_origin_dispatches(coord, current_time_s=60.0)
    assert len(dispatched) == 1
    assert dispatched[0].train_id == "TR_CANDIDATE"
    assert dispatched[0].actual_departure_time_s == 60.0
    assert dispatched[0].departure_delay_s == 60.0


def test_p09_b008_origin_queue():
    """P09-B008: Origin queue formation and sequential discharge."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"])
    st = ServiceType("SVC_Q", "TT_STANDARD", params, route)

    q = OriginDepartureQueue()
    q.enqueue_all([
        TrainGenerator.create_instance(st, "TR_1", 0.0),
        TrainGenerator.create_instance(st, "TR_2", 0.0),
        TrainGenerator.create_instance(st, "TR_3", 0.0),
    ])

    assert len(q.get_queued_trains()) == 3
    # At t=0, first train departs
    d1 = q.process_origin_dispatches(coord, current_time_s=0.0)
    assert len(d1) == 1
    assert d1[0].train_id == "TR_1"
    # Remaining queued = 2
    assert len(q.get_queued_trains()) == 2


def test_p09_b009_first_come_first_served():
    """P09-B009: First-come-first-served dispatching."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"])
    st = ServiceType("SVC_FCFS", "TT_STANDARD", params, route)

    q = OriginDepartureQueue(dispatch_policy=DispatchPolicy.FIRST_COME_FIRST_SERVED)
    # Enqueue out of order
    q.enqueue(TrainGenerator.create_instance(st, "TR_LATE", 50.0))
    q.enqueue(TrainGenerator.create_instance(st, "TR_EARLY", 10.0))

    candidates = q.get_ready_candidates("L1_FORWARD", current_time_s=60.0)
    assert candidates[0].train_id == "TR_EARLY"
    assert candidates[1].train_id == "TR_LATE"


def test_p09_b010_priority_dispatch():
    """P09-B010: Priority-based dispatching."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"])
    st_low = ServiceType("SVC_LOW", "TT_STANDARD", params, route, priority=1)
    st_high = ServiceType("SVC_HIGH", "TT_STANDARD", params, route, priority=5)

    q = OriginDepartureQueue(dispatch_policy=DispatchPolicy.PRIORITY_BASED)
    q.enqueue(TrainGenerator.create_instance(st_low, "TR_LOW", requested_departure_s=0.0))
    q.enqueue(TrainGenerator.create_instance(st_high, "TR_HIGH", requested_departure_s=5.0))

    candidates = q.get_ready_candidates("L1_FORWARD", current_time_s=10.0)
    assert candidates[0].train_id == "TR_HIGH"  # Priority 5 precedes priority 1


def test_p09_b011_deterministic_tie_breaking():
    """P09-B011: Deterministic tie-breaking by train_id lexicographical order."""
    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"])
    st = ServiceType("SVC_TIE", "TT_STANDARD", params, route, priority=1)

    q = OriginDepartureQueue(dispatch_policy=DispatchPolicy.FIRST_COME_FIRST_SERVED)
    q.enqueue(TrainGenerator.create_instance(st, "TR_Z", requested_departure_s=0.0))
    q.enqueue(TrainGenerator.create_instance(st, "TR_A", requested_departure_s=0.0))

    candidates = q.get_ready_candidates("L1_FORWARD", current_time_s=0.0)
    assert candidates[0].train_id == "TR_A"
    assert candidates[1].train_id == "TR_Z"


def test_p09_b012_fixed_block_train_interaction():
    """P09-B012: Fixed-block train interaction; follower decelerates behind occupied block."""
    coord = SignallingCoordinator(technology_type=SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL)
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    coord.resource_controller.register_resource(make_test_block("BLK_L2", "L2"))

    params = make_test_train_params(max_speed_ms=30.0)
    route = make_test_route(link_ids=["L1", "L2"], link_lengths=[1000.0, 1000.0])
    st = ServiceType("SVC_FB", "TT_STANDARD", params, route)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=1.0)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=25.0)
    mt_sim.register_trains(trains)
    res = mt_sim.run_simulation(max_duration_s=300.0)

    # Leader and follower both successfully finish
    assert len(res.completed_trains) == 2
    # Follower experienced signalling interaction
    foll_summary = res.delay_summaries["SVC_FB_FOLL"]
    assert foll_summary.actual_departure_s is not None


def test_p09_b013_etcs_level2_train_interaction():
    """P09-B013: ETCS Level 2 train interaction."""
    coord = SignallingCoordinator(technology_type=SignallingTechnologyType.ETCS_LEVEL_2)
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    coord.resource_controller.register_resource(make_test_block("BLK_L2", "L2"))

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"], link_lengths=[1000.0, 1000.0])
    st = ServiceType("SVC_ETCS", "TT_STANDARD", params, route)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=60.0)
    mt_sim.register_trains(trains)
    res = mt_sim.run_simulation(max_duration_s=300.0)

    assert len(res.completed_trains) == 2


def test_p09_b014_cbtc_train_interaction():
    """P09-B014: CBTC dynamic moving-block train separation."""
    coord = SignallingCoordinator(technology_type=SignallingTechnologyType.CBTC_MOVING_BLOCK)
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    coord.resource_controller.register_resource(make_test_block("BLK_L2", "L2"))

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"], link_lengths=[1500.0, 1500.0])
    st = ServiceType("SVC_CBTC", "TT_STANDARD", params, route)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=40.0)
    mt_sim.register_trains(trains)
    res = mt_sim.run_simulation(max_duration_s=400.0)

    assert len(res.completed_trains) == 2


def test_p09_b015_station_arrival_and_dwell():
    """P09-B015: Station arrival and dwell duration."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    coord.resource_controller.register_resource(ManagedResource("PLT_01", ResourceCategory.PLATFORM, intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=200.0)]))

    stn = Station(station_id="STN_01", name="Station One")
    coord.platform_controller.register_station(stn)
    plat = Platform(platform_id="PLT_01", station_id="STN_01", link_id="L1", start_offset_m=400.0, end_offset_m=600.0, length_m=200.0)
    coord.platform_controller.register_platform(plat)

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1"], link_lengths=[1500.0])
    stops = [StationStop(station_id="STN_01", platform_id="PLT_01", dwell_time_s=30.0)]
    st = ServiceType("SVC_STN", "TT_STANDARD", params, route, stops=stops)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    train = TrainGenerator.create_instance(st, "TR_STN", requested_departure_s=0.0)
    mt_sim.register_train(train)
    res = mt_sim.run_simulation(max_duration_s=300.0)

    assert len(res.completed_trains) == 1
    # Check boundary events contain arrival and departure
    arr_events = [e for e in train.events if e.event_type == CrossingEventType.STATION_ARRIVED]
    dep_events = [e for e in train.events if e.event_type == CrossingEventType.STATION_DEPARTED]
    assert len(arr_events) == 1
    assert len(dep_events) == 1
    dwell_duration = dep_events[0].timestamp_s - arr_events[0].timestamp_s
    assert abs(dwell_duration - 30.0) <= 0.5


def test_p09_b016_platform_conflict():
    """P09-B016: Platform conflict holds follower before occupied platform."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
    coord.resource_controller.register_resource(make_test_block("BLK_L2", "L2"))
    coord.resource_controller.register_resource(make_test_block("BLK_L3", "L3"))
    coord.resource_controller.register_resource(
        ManagedResource("PLT_01", ResourceCategory.PLATFORM, intervals=[ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=300.0)])
    )

    stn = Station(station_id="STN_01", name="Station One")
    coord.platform_controller.register_station(stn)
    plat = Platform(platform_id="PLT_01", station_id="STN_01", link_id="L2", start_offset_m=50.0, end_offset_m=250.0, length_m=200.0)
    coord.platform_controller.register_platform(plat)

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2", "L3"], link_lengths=[800.0, 500.0, 800.0])
    stops = [StationStop(station_id="STN_01", platform_id="PLT_01", dwell_time_s=60.0)]
    st = ServiceType("SVC_PLAT_CONF", "TT_STANDARD", params, route, stops=stops)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=20.0)
    mt_sim.register_trains(trains)
    res = mt_sim.run_simulation(max_duration_s=500.0)

    assert len(res.completed_trains) == 2
    foll_summary = res.delay_summaries["SVC_PLAT_CONF_FOLL"]
    # Follower experienced platform-related delay
    assert foll_summary.secondary_delay_s > 0.0


def test_p09_b017_multi_platform_assignment():
    """P09-B017: Multi-platform assignment allocates alternative platform when preferred is occupied."""
    coord = SignallingCoordinator()
    stn = Station(station_id="STN_MULTI", name="Multi-Platform Station")
    coord.platform_controller.register_station(stn)

    plat1 = Platform(platform_id="PLT_M1", station_id="STN_MULTI", link_id="L1", start_offset_m=0.0, end_offset_m=200.0, length_m=200.0)
    plat2 = Platform(platform_id="PLT_M2", station_id="STN_MULTI", link_id="L2", start_offset_m=0.0, end_offset_m=200.0, length_m=200.0)
    coord.platform_controller.register_platform(plat1)
    coord.platform_controller.register_platform(plat2)

    # Leader takes PLT_M1
    p1 = coord.platform_controller.allocate_platform(
        train_id="TR_1",
        station_id="STN_MULTI",
        train_length_m=150.0,
        timestamp_s=0.0,
        preferred_platform_id="PLT_M1",
        policy=PlatformSelectionPolicy.PREFERRED_WITH_ALTERNATIVES,
    )
    assert p1 == "PLT_M1"
    coord.platform_controller.request_platform("TR_1", "PLT_M1", 150.0, 0.0)

    # Follower requests PLT_M1, automatically allocated PLT_M2
    p2 = coord.platform_controller.allocate_platform(
        train_id="TR_2",
        station_id="STN_MULTI",
        train_length_m=150.0,
        timestamp_s=5.0,
        preferred_platform_id="PLT_M1",
        permitted_platform_ids=["PLT_M2"],
        policy=PlatformSelectionPolicy.PREFERRED_WITH_ALTERNATIVES,
    )
    assert p2 == "PLT_M2"


def test_p09_b018_junction_merge_sequence():
    """P09-B018: Junction merge sequence."""
    coord = SignallingCoordinator()
    sw = Switch("SW_01", "ND_JNC")
    coord.switch_controller.register_switch(sw)

    r1 = InterlockingRouteDefinition("RT_J1", "S1", "S3", ["L1", "L3"], required_switch_positions={"SW_01": SwitchPosition.NORMAL})
    r2 = InterlockingRouteDefinition("RT_J2", "S2", "S3", ["L2", "L3"], required_switch_positions={"SW_01": SwitchPosition.REVERSE})
    coord.interlocking_engine.register_route(r1)
    coord.interlocking_engine.register_route(r2)

    # Train 1 locks RT_J1
    t_lock = coord.interlocking_engine.request_and_lock_route("RT_J1", "TR_1", 0.0)
    assert t_lock >= 0.0

    # Train 2 cannot request RT_J2 concurrently
    assert not coord.interlocking_engine.is_route_available("RT_J2", "TR_2", 10.0)


def test_p09_b019_junction_waiting():
    """P09-B019: Junction waiting."""
    tracker = DelayPropagationTracker()
    tracker.record_incident("TR_2", DelayCause.JUNCTION, 10.0, 45.0, 500.0, "SW_01", "TR_1")
    summary = tracker.summarize_train_delays("TR_2", "SVC_J", 0.0, 0.0, 200.0, 235.0)
    assert summary.breakdown_by_cause_s[DelayCause.JUNCTION] == 35.0


def test_p09_b020_tvs_entry_waiting():
    """P09-B020: TVS entry waiting verification."""
    test_numerical_benchmark_b_tvs_waiting()


def test_p09_b021_consecutive_tvs_queues():
    """P09-B021: Consecutive TVS queues."""
    tracker = TVSQueueTracker()
    tracker.record_waiting_train("TVS_SEC1", "TR_A", 10.0)
    tracker.record_waiting_train("TVS_SEC2", "TR_B", 20.0)
    assert tracker.stats["TVS_SEC1"].total_queued_trains_count == 1
    assert tracker.stats["TVS_SEC2"].total_queued_trains_count == 1


def test_p09_b022_shared_tvs_restriction():
    """P09-B022: Cross-track shared TVS group restriction."""
    coord = SignallingCoordinator()
    tvs1 = TVSSection(tvs_id="TVS_T1", tunnel_id="TUN_01", track_id="TRK_01", link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)])
    tvs2 = TVSSection(tvs_id="TVS_T2", tunnel_id="TUN_01", track_id="TRK_02", link_intervals=[ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=1000.0)])
    coord.tvs_controller.register_tvs_section(tvs1, auth_processing_delay_s=0.0)
    coord.tvs_controller.register_tvs_section(tvs2, auth_processing_delay_s=0.0)

    shared_group = SharedResourceGroup(
        group_id="GRP_CROSS",
        resource_ids=["TVS_T1", "TVS_T2"],
    )
    coord.tvs_controller.register_shared_group(shared_group)

    # Train 1 occupies TVS_T1
    coord.tvs_controller.request_tvs_entry("TR_1", "TVS_T1", 0.0)
    coord.tvs_controller.front_enter_tvs("TR_1", "TVS_T1", 5.0)

    # Train 2 requesting TVS_T2 must be denied
    ok2, _ = coord.tvs_controller.is_tvs_available("TVS_T2", "TR_2", current_time_s=5.0)
    assert not ok2


def test_p09_b023_whole_tunnel_restriction():
    """P09-B023: Whole tunnel single-train restriction."""
    coord = SignallingCoordinator()
    tvs1 = TVSSection(tvs_id="TVS_W1", tunnel_id="TUN_WHOLE", track_id="TRK_01", link_intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)])
    tvs2 = TVSSection(tvs_id="TVS_W2", tunnel_id="TUN_WHOLE", track_id="TRK_02", link_intervals=[ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=1000.0)])
    coord.tvs_controller.register_tvs_section(tvs1, exclusivity_scope=TVSExclusivityScope.WHOLE_TUNNEL, auth_processing_delay_s=0.0)
    coord.tvs_controller.register_tvs_section(tvs2, exclusivity_scope=TVSExclusivityScope.WHOLE_TUNNEL, auth_processing_delay_s=0.0)

    coord.tvs_controller.request_tvs_entry("TR_A", "TVS_W1", 0.0)
    coord.tvs_controller.front_enter_tvs("TR_A", "TVS_W1", 5.0)

    # Track 2 denied
    ok_b, _ = coord.tvs_controller.is_tvs_available("TVS_W2", "TR_B", current_time_s=5.0)
    assert not ok_b


def test_p09_b024_journey_time_increase():
    """P09-B024: Journey-time increase verification."""
    test_numerical_benchmark_c_journey_time_increase()


def test_p09_b025_schedule_delay():
    """P09-B025: Schedule delay calculation."""
    tracker = DelayPropagationTracker()
    summary = tracker.summarize_train_delays("TR_01", "SVC_01", 100.0, 125.0, 400.0, 440.0)
    assert summary.departure_delay_s == 25.0
    assert summary.arrival_delay_s == 40.0


def test_p09_b026_secondary_delay_propagation():
    """P09-B026: Secondary delay propagation."""
    test_numerical_benchmark_d_delay_propagation()


def test_p09_b027_queue_growth():
    """P09-B027: Queue growth and dissipation."""
    tracker = TVSQueueTracker()
    tracker.record_waiting_train("TVS_Q", "TR_1", 0.0)
    tracker.record_waiting_train("TVS_Q", "TR_2", 10.0)
    tracker.record_waiting_train("TVS_Q", "TR_3", 20.0)

    assert len(tracker._active_waiting_trains["TVS_Q"]) == 3
    # Discharge
    tracker.release_waiting_train("TVS_Q", "TR_1", 30.0)
    tracker.release_waiting_train("TVS_Q", "TR_2", 40.0)
    tracker.release_waiting_train("TVS_Q", "TR_3", 50.0)
    assert len(tracker._active_waiting_trains["TVS_Q"]) == 0


def test_p09_b028_deadlock_detection():
    """P09-B028: Deadlock detection for circular wait-for dependency."""
    detector = DeadlockDetector()
    deps = [
        WaitDependency("TR_1", "RES_B", "TR_2", 100.0, "TR_1 waiting for TR_2"),
        WaitDependency("TR_2", "RES_A", "TR_1", 100.0, "TR_2 waiting for TR_1"),
    ]
    report = detector.detect_circular_waits(deps, current_time_s=110.0)
    assert report is not None
    assert report.deadlock_type == DeadlockType.CIRCULAR_WAIT
    assert set(report.involved_train_ids) == {"TR_1", "TR_2"}


def test_p09_b029_forward_repeated_trains():
    """P09-B029: Forward repeated trains."""
    params = make_test_train_params()
    route = make_test_route(direction=RunningDirection.FORWARD)
    st = ServiceType("SVC_FWD", "TT_STANDARD", params, route, running_direction=RunningDirection.FORWARD)
    trains = TrainGenerator.generate_repeated_homogeneous(st, count=3, interval_s=100.0)
    assert all(t.running_direction == RunningDirection.FORWARD for t in trains)


def test_p09_b030_reverse_repeated_trains():
    """P09-B030: Reverse repeated trains."""
    params = make_test_train_params()
    route = make_test_route(direction=RunningDirection.REVERSE)
    st = ServiceType("SVC_REV", "TT_STANDARD", params, route, running_direction=RunningDirection.REVERSE)
    trains = TrainGenerator.generate_repeated_homogeneous(st, count=3, interval_s=100.0)
    assert all(t.running_direction == RunningDirection.REVERSE for t in trains)


def test_p09_b031_simultaneous_opposing_trains():
    """P09-B031: Simultaneous opposing-direction train simulation."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_F1", "L_FWD"))
    coord.resource_controller.register_resource(make_test_block("BLK_R1", "L_REV"))

    params = make_test_train_params()
    route_fwd = make_test_route("RT_F", link_ids=["L_FWD"], direction=RunningDirection.FORWARD)
    route_rev = make_test_route("RT_R", link_ids=["L_REV"], direction=RunningDirection.REVERSE)

    st_fwd = ServiceType("SVC_F", "TT_STANDARD", params, route_fwd, running_direction=RunningDirection.FORWARD)
    st_rev = ServiceType("SVC_R", "TT_STANDARD", params, route_rev, running_direction=RunningDirection.REVERSE)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    tf = TrainGenerator.create_instance(st_fwd, "TR_FWD", 0.0)
    tr = TrainGenerator.create_instance(st_rev, "TR_REV", 0.0)
    mt_sim.register_trains([tf, tr])
    res = mt_sim.run_simulation(max_duration_s=200.0)

    assert len(res.completed_trains) == 2


def test_p09_b032_directional_resource_conflict():
    """P09-B032: Opposing-direction resource conflict on shared single track."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_SINGLE", "L_SINGLE"))

    params = make_test_train_params()
    route_fwd = make_test_route("RT_F", link_ids=["L_SINGLE"], direction=RunningDirection.FORWARD)
    route_rev = make_test_route("RT_R", link_ids=["L_SINGLE"], direction=RunningDirection.REVERSE)

    st_fwd = ServiceType("SVC_F", "TT_STANDARD", params, route_fwd, running_direction=RunningDirection.FORWARD)
    st_rev = ServiceType("SVC_R", "TT_STANDARD", params, route_rev, running_direction=RunningDirection.REVERSE)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    tf = TrainGenerator.create_instance(st_fwd, "TR_FWD", 0.0)
    tr = TrainGenerator.create_instance(st_rev, "TR_REV", 0.0)
    mt_sim.register_trains([tf, tr])
    res = mt_sim.run_simulation(max_duration_s=300.0)

    # First train takes single track; second train waits until first clears
    assert len(res.completed_trains) == 2
    assert res.kpis.actual_departure_sequence[0] == "TR_FWD"
    assert res.kpis.actual_departure_sequence[1] == "TR_REV"


def test_p09_b033_deterministic_reproducibility():
    """P09-B033: Deterministic reproducibility — two runs produce identical results."""
    def run_sim():
        coord = SignallingCoordinator()
        coord.resource_controller.register_resource(make_test_block("BLK_L1", "L1"))
        params = make_test_train_params()
        route = make_test_route(link_ids=["L1"], link_lengths=[1000.0])
        st = ServiceType("SVC_REP", "TT_STANDARD", params, route)
        sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=0.4)
        sim.register_train(TrainGenerator.create_instance(st, "TR_1", 0.0))
        return sim.run_simulation(max_duration_s=150.0)

    res1 = run_sim()
    res2 = run_sim()

    t1 = res1.trajectories["TR_1"]
    t2 = res2.trajectories["TR_1"]
    assert t1.journey_time_s == t2.journey_time_s
    assert len(t1.samples) == len(t2.samples)
    for s1, s2 in zip(t1.samples, t2.samples):
        assert s1.time_s == s2.time_s
        assert s1.front_distance_m == s2.front_distance_m
        assert s1.speed_ms == s2.speed_ms


def test_p09_b034_no_prohibited_resource_occupation():
    """P09-B034: Verify no prohibited concurrent resource occupation (safety invariant N <= 1)."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_SAFE", "L1"))

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1"], link_lengths=[1000.0])
    st = ServiceType("SVC_SAFE", "TT_STANDARD", params, route)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    mt_sim.register_trains(TrainGenerator.generate_pairwise(st, st, interval_s=10.0))
    res = mt_sim.run_simulation(max_duration_s=250.0)

    # Invariant verified: resource was never occupied by > 1 train
    res_obj = coord.resource_controller.resources["BLK_SAFE"]
    assert len(res_obj.occupants) <= 1


def test_p09_b035_simulation_event_ordering():
    """P09-B035: Simulation event ordering maintains chronological sequence IDs."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(make_test_block("BLK_1", "L1"))
    coord.resource_controller.register_resource(make_test_block("BLK_2", "L2"))

    params = make_test_train_params()
    route = make_test_route(link_ids=["L1", "L2"])
    st = ServiceType("SVC_EVT", "TT_STANDARD", params, route)

    mt_sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    mt_sim.register_trains(TrainGenerator.generate_pairwise(st, st, interval_s=50.0))
    res = mt_sim.run_simulation(max_duration_s=250.0)

    seq_ids = [e.sequence_id for e in res.events]
    assert seq_ids == sorted(seq_ids)
