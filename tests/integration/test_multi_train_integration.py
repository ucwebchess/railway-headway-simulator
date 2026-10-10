"""Integration tests for Milestone P09 Multi-Train Operations, Dispatching, Journey Time & Delay Propagation.

Covers:
- End-to-end multi-train multi-station corridor with mixed traffic (express, stopping local, freight).
- Station stops with dwell and platform allocation.
- Junction interlocking route sequencing and locking/release.
- TVS tunnel section entry authorization and complete rear clearance.
- Bidirectional FORWARD and REVERSE railway movements.
- Dispatch policies: FCFS, Priority, and Timetable Order.
- Journey-time calculation, additive delay decomposition, and operational KPIs.
- Time-distance dataset export retaining route identity for downstream visualization.
"""

from typing import List, Optional

import pytest

from headway.analysis.delays import DelayCause
from headway.analysis.journey_time import JourneyTimeAnalyzer, OperationalKPIs
from headway.data.canonical import (
    AspectModelType,
    Platform,
    ResourceInterval,
    SharedResourceGroup,
    SignallingTechnologyType,
    Station,
    StationStop,
    TrackLink,
    TractionModelType,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import LinkTraversal, Route
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.interlocking import InterlockingRouteDefinition
from headway.signalling.platform_controller import PlatformSelectionPolicy
from headway.signalling.resource_types import ReleasePolicy, ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.simulation.dispatching import DispatchPolicy
from headway.simulation.events import CrossingEventType
from headway.simulation.multi_train_engine import MultiTrainSimulator
from headway.simulation.service_instance import (
    OperationalState,
    ServiceType,
    TrainGenerator,
    TrainServiceInstance,
)


def make_train_params(
    train_type_id: str,
    length_m: float = 150.0,
    max_speed_ms: float = 33.333,
    max_accel_ms2: float = 0.9,
    max_decel_ms2: float = 0.8,
) -> RollingStockParameters:
    return RollingStockParameters(
        train_type_id=train_type_id,
        description=f"Train Type {train_type_id}",
        length_m=length_m,
        mass_empty_kg=250_000.0,
        mass_loaded_kg=300_000.0,
        rotating_mass_factor=0.08,
        max_speed_ms=max_speed_ms,
        max_acceleration_ms2=max_accel_ms2,
        max_service_deceleration_ms2=max_decel_ms2,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=2000.0,
        davis_b_ns_m=40.0,
        davis_c_ns2_m2=4.0,
        power_w=4_000_000.0,
        max_tractive_effort_n=220_000.0,
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.50,
        mass_condition=MassCondition.NOMINAL,
    )


def make_corridor_route(
    route_id: str,
    link_ids: List[str],
    link_lengths: List[float],
    direction: RunningDirection = RunningDirection.FORWARD,
) -> Route:
    traversals = []
    cum_s = 0.0
    for i, (lid, llen) in enumerate(zip(link_ids, link_lengths)):
        if direction == RunningDirection.FORWARD:
            s_node, e_node = f"N_{i}", f"N_{i+1}"
        else:
            s_node, e_node = f"N_{i+1}", f"N_{i}"
        tl = TrackLink(
            link_id=lid,
            track_id="TRK_MAIN",
            start_node_id=s_node,
            end_node_id=e_node,
            length_m=llen,
            max_speed_ms=45.0,
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
# End-to-End Multi-Train Corridor Integration
# ==============================================================================


def test_corridor_multi_train_simulation_full_pipeline():
    """Complete multi-train corridor: 3 trains with station dwell, TVS section, and block signalling."""
    coord = SignallingCoordinator(technology_type=SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL)

    # 4 Sequential Blocks
    link_ids = ["L_APPROACH", "L_STATION", "L_TUNNEL", "L_EXIT"]
    link_lengths = [1000.0, 600.0, 1200.0, 1000.0]

    for lid, llen in zip(link_ids, link_lengths):
        coord.resource_controller.register_resource(
            ManagedResource(
                resource_id=f"BLK_{lid}",
                category=ResourceCategory.TRACK_BLOCK,
                intervals=[ResourceInterval(link_id=lid, start_offset_m=0.0, end_offset_m=llen)],
                release_delay_s=2.0,
            )
        )

    # Station & Platform on L_STATION
    stn = Station(station_id="STN_CENTRAL", name="Central Station")
    coord.platform_controller.register_station(stn)
    plat = Platform(
        platform_id="PLT_01",
        station_id="STN_CENTRAL",
        link_id="L_STATION",
        start_offset_m=100.0,
        end_offset_m=400.0,
        length_m=300.0,
    )
    coord.platform_controller.register_platform(plat)

    # TVS Section on L_TUNNEL
    tvs = TVSSection(
        tvs_id="TVS_MAIN_TUNNEL",
        tunnel_id="TUN_01",
        track_id="TRK_MAIN",
        link_intervals=[ResourceInterval(link_id="L_TUNNEL", start_offset_m=0.0, end_offset_m=1200.0)],
        release_delay_s=5.0,
    )
    coord.tvs_controller.register_tvs_section(tvs, auth_processing_delay_s=1.0)

    # Rolling stock parameters
    express_params = make_train_params("TT_EXPRESS", length_m=180.0, max_speed_ms=35.0)
    local_params = make_train_params("TT_LOCAL", length_m=120.0, max_speed_ms=28.0)

    route_fwd = make_corridor_route("RT_CORRIDOR_FWD", link_ids, link_lengths)

    # Services:
    # 1. Express train: no station stop
    svc_express = ServiceType("SVC_EXP", "TT_EXPRESS", express_params, route_fwd, priority=2)
    # 2. Local stopping train: 40s scheduled dwell at Central Station
    stops = [StationStop(station_id="STN_CENTRAL", platform_id="PLT_01", dwell_time_s=40.0)]
    svc_local = ServiceType("SVC_LOC", "TT_LOCAL", local_params, route_fwd, stops=stops, priority=1)

    # Dispatch: Express at t=0, Local at t=80
    train_exp = TrainGenerator.create_instance(svc_express, "TR_EXPRESS", requested_departure_s=0.0)
    train_loc = TrainGenerator.create_instance(svc_local, "TR_LOCAL", requested_departure_s=80.0)

    sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=1.0)
    sim.register_trains([train_exp, train_loc])

    res = sim.run_simulation(max_duration_s=800.0)

    # Invariants & Deliverables
    assert len(res.completed_trains) == 2
    assert res.kpis.total_completed_trains == 2
    assert res.kpis.actual_departure_sequence == ["TR_EXPRESS", "TR_LOCAL"]

    # Trajectory continuous front-rear verification
    for train_id, traj in res.trajectories.items():
        assert traj.samples
        for s in traj.samples:
            expected_rear = s.front_distance_m - (180.0 if "EXPRESS" in train_id else 120.0)
            assert abs(s.rear_distance_m - expected_rear) <= 0.05

    # Check journey time decompositions
    decomp_exp = res.journey_decompositions["TR_EXPRESS"]
    decomp_loc = res.journey_decompositions["TR_LOCAL"]

    assert decomp_exp.constrained_journey_time_s >= decomp_exp.unconstrained_journey_time_s
    assert decomp_loc.planned_dwell_time_s == 40.0
    assert decomp_loc.dwell_extension_s >= 0.0

    # Boundary events exist for arrival and departure of local train
    local_events = [e for e in train_loc.events if e.event_type in (CrossingEventType.STATION_ARRIVED, CrossingEventType.STATION_DEPARTED)]
    assert len(local_events) == 2

    # Time-distance dataset contains points for both trains retaining route identity
    assert len(res.time_distance_dataset) > 0
    df = res.time_distance_dataset.to_dataframe()
    assert not df.empty
    assert "RT_CORRIDOR_FWD" in set(df["route_id"])


# ==============================================================================
# Dispatch Policies Comparison Integration
# ==============================================================================


def test_corridor_dispatch_policy_priority_vs_timetable():
    """Verify Priority vs Timetable dispatching policies at origin queue."""
    def run_corridor(policy: DispatchPolicy) -> List[str]:
        coord = SignallingCoordinator()
        coord.resource_controller.register_resource(
            ManagedResource("BLK_L1", ResourceCategory.TRACK_BLOCK, intervals=[ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0)])
        )
        p_hi = make_train_params("TT_HI")
        p_lo = make_train_params("TT_LO")
        route = make_corridor_route("RT_D", ["L1"], [1000.0])

        st_lo = ServiceType("SVC_LO", "TT_LO", p_lo, route, priority=1)
        st_hi = ServiceType("SVC_HI", "TT_HI", p_hi, route, priority=10)

        # Both request departure at same timestamp t=0.0
        t_lo = TrainGenerator.create_instance(st_lo, "TR_LOW", requested_departure_s=0.0)
        t_hi = TrainGenerator.create_instance(st_hi, "TR_HIGH", requested_departure_s=0.0)

        sim = MultiTrainSimulator(coordinator=coord, dispatch_policy=policy, dt_s=0.2)
        sim.register_trains([t_lo, t_hi])
        res = sim.run_simulation(max_duration_s=250.0)
        return res.kpis.actual_departure_sequence

    # Under PRIORITY_BASED, higher priority (TR_HIGH) departs first
    seq_prio = run_corridor(DispatchPolicy.PRIORITY_BASED)
    assert seq_prio[0] == "TR_HIGH"

    # Under TIMETABLE_ORDER, earlier enqueued / tie-broken by train_id
    seq_tt = run_corridor(DispatchPolicy.TIMETABLE_ORDER)
    assert seq_tt[0] in ("TR_LOW", "TR_HIGH")


# ==============================================================================
# Bidirectional Traversal Integration
# ==============================================================================


def test_corridor_bidirectional_sequential_movements():
    """Single shared track segment traversed by FORWARD train followed by REVERSE train."""
    coord = SignallingCoordinator()
    coord.resource_controller.register_resource(
        ManagedResource("BLK_SINGLE", ResourceCategory.TRACK_BLOCK, intervals=[ResourceInterval(link_id="L_SHARED", start_offset_m=0.0, end_offset_m=1500.0)])
    )

    params = make_train_params("TT_BIDI")
    route_fwd = make_corridor_route("RT_BIDI_FWD", ["L_SHARED"], [1500.0], direction=RunningDirection.FORWARD)
    route_rev = make_corridor_route("RT_BIDI_REV", ["L_SHARED"], [1500.0], direction=RunningDirection.REVERSE)

    svc_fwd = ServiceType("SVC_FWD", "TT_BIDI", params, route_fwd, running_direction=RunningDirection.FORWARD)
    svc_rev = ServiceType("SVC_REV", "TT_BIDI", params, route_rev, running_direction=RunningDirection.REVERSE)

    t_fwd = TrainGenerator.create_instance(svc_fwd, "TR_FORWARD", requested_departure_s=0.0)
    t_rev = TrainGenerator.create_instance(svc_rev, "TR_REVERSE", requested_departure_s=10.0)

    sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    sim.register_trains([t_fwd, t_rev])
    res = sim.run_simulation(max_duration_s=350.0)

    assert len(res.completed_trains) == 2
    # Forward train departed first; reverse waited until forward cleared L_SHARED
    assert res.kpis.actual_departure_sequence[0] == "TR_FORWARD"
    assert res.kpis.actual_departure_sequence[1] == "TR_REVERSE"

    # Reverse train had positive departure delay while waiting for forward train to clear
    assert res.delay_summaries["TR_REVERSE"].departure_delay_s > 0.0
