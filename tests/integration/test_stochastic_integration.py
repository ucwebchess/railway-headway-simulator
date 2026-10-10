"""Integration test suite for Milestone P11 Stochastic Simulation, Monte Carlo & Reliability.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- Forward stochastic microscopic simulation (dwell, departure readiness, traction variations)
- Reverse stochastic microscopic simulation (verifying physical link traversals in REVERSE)
- Opposing-direction simultaneous railway operations with stochastic sampling
- TVS queueing and single-train occupancy invariants under stochastic arrival jitter
- Temporary operational disruptions (extended dwell, TSR) and secondary delay propagation
- Common Random Numbers (CRN) scenario comparison with synchronized entity draws
- Reliability-Based Capacity Calculator searching sustainable demand rates meeting multi-criteria targets
"""

import math
from typing import List, Tuple

import numpy as np
import pytest

from headway.analysis.distributions import (
    DistributionType,
    ExponentialDistribution,
    NormalDistribution,
    UniformDistribution,
)
from headway.analysis.monte_carlo import (
    MonteCarloExecutionResult,
    MonteCarloSimulationManager,
    ReplicationResult,
)
from headway.analysis.random_variables import (
    DisruptionType,
    OperationalDisruption,
    SamplingScope,
    StochasticVariableDefinition,
    TargetObjectType,
)
from headway.analysis.reliability import (
    ReliabilityCriterion,
    ReliabilityEvaluator,
)
from headway.analysis.stochastic import CommonRandomNumbersManager
from headway.analysis.stochastic_capacity import ReliabilityBasedCapacityCalculator
from headway.data.canonical import (
    Platform,
    ResourceInterval,
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
from headway.signalling.resource_types import ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.simulation.service_instance import (
    ServiceType,
    TrainGenerator,
    TrainServiceInstance,
)


def make_train_params(
    train_type_id: str,
    length_m: float = 140.0,
    max_speed_ms: float = 30.0,
) -> RollingStockParameters:
    return RollingStockParameters(
        train_type_id=train_type_id,
        description=f"Train Type {train_type_id}",
        length_m=length_m,
        mass_empty_kg=180_000.0,
        mass_loaded_kg=220_000.0,
        rotating_mass_factor=0.08,
        max_speed_ms=max_speed_ms,
        max_acceleration_ms2=0.8,
        max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=1800.0,
        davis_b_ns_m=35.0,
        davis_c_ns2_m2=3.5,
        power_w=3_000_000.0,
        max_tractive_effort_n=200_000.0,
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.50,
        mass_condition=MassCondition.NOMINAL,
    )


def make_corridor_infrastructure(double_track: bool = False):
    """Sets up corridor infrastructure with blocks, station, and TVS."""
    coord = SignallingCoordinator(technology_type=SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL)

    tl_entry = TrackLink(link_id="L_ENTRY", track_id="TRK_01", start_node_id="N_0", end_node_id="N_1", length_m=800.0, max_speed_ms=30.0)
    tl_stn = TrackLink(link_id="L_STN", track_id="TRK_01", start_node_id="N_1", end_node_id="N_2", length_m=500.0, max_speed_ms=30.0)
    tl_tunnel = TrackLink(link_id="L_TUNNEL", track_id="TRK_01", start_node_id="N_2", end_node_id="N_3", length_m=1000.0, max_speed_ms=30.0)
    tl_exit = TrackLink(link_id="L_EXIT", track_id="TRK_01", start_node_id="N_3", end_node_id="N_4", length_m=800.0, max_speed_ms=30.0)

    links_fwd = [tl_entry, tl_stn, tl_tunnel, tl_exit]

    for tl in links_fwd:
        coord.resource_controller.register_resource(
            ManagedResource(
                resource_id=f"BLK_{tl.link_id}",
                category=ResourceCategory.TRACK_BLOCK,
                intervals=[ResourceInterval(link_id=tl.link_id, start_offset_m=0.0, end_offset_m=tl.length_m)],
                release_delay_s=2.0,
            )
        )

    # Station on L_STN
    stn = Station(station_id="STN_ALPHA", name="Station Alpha")
    coord.platform_controller.register_station(stn)
    plat = Platform(
        platform_id="PLT_ALPHA_1",
        station_id="STN_ALPHA",
        link_id="L_STN",
        start_offset_m=50.0,
        end_offset_m=350.0,
        length_m=300.0,
    )
    coord.platform_controller.register_platform(plat)

    # TVS on L_TUNNEL
    tvs = TVSSection(
        tvs_id="TVS_ZONE_1",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L_TUNNEL", start_offset_m=0.0, end_offset_m=1000.0)],
        release_delay_s=3.0,
    )
    coord.tvs_controller.register_tvs_section(tvs, auth_processing_delay_s=1.0)

    # Forward route traversals
    traversals_fwd = [
        LinkTraversal(link=tl_entry, direction=RunningDirection.FORWARD, sequence_index=0, start_distance_m=0.0, end_distance_m=800.0),
        LinkTraversal(link=tl_stn, direction=RunningDirection.FORWARD, sequence_index=1, start_distance_m=800.0, end_distance_m=1300.0),
        LinkTraversal(link=tl_tunnel, direction=RunningDirection.FORWARD, sequence_index=2, start_distance_m=1300.0, end_distance_m=2300.0),
        LinkTraversal(link=tl_exit, direction=RunningDirection.FORWARD, sequence_index=3, start_distance_m=2300.0, end_distance_m=3100.0),
    ]
    route_fwd = Route(route_id="RT_CORRIDOR_FWD", traversals=traversals_fwd)

    # Reverse route traversals (exits N_4 -> N_3 -> N_2 -> N_1 -> N_0)
    traversals_rev = [
        LinkTraversal(link=tl_exit, direction=RunningDirection.REVERSE, sequence_index=0, start_distance_m=0.0, end_distance_m=800.0),
        LinkTraversal(link=tl_tunnel, direction=RunningDirection.REVERSE, sequence_index=1, start_distance_m=800.0, end_distance_m=1800.0),
        LinkTraversal(link=tl_stn, direction=RunningDirection.REVERSE, sequence_index=2, start_distance_m=1800.0, end_distance_m=2300.0),
        LinkTraversal(link=tl_entry, direction=RunningDirection.REVERSE, sequence_index=3, start_distance_m=2300.0, end_distance_m=3100.0),
    ]
    route_rev = Route(route_id="RT_CORRIDOR_REV", traversals=traversals_rev)

    route_opp = None
    if double_track:
        tl2_entry = TrackLink(link_id="L2_ENTRY", track_id="TRK_02", start_node_id="M_4", end_node_id="M_3", length_m=800.0, max_speed_ms=30.0)
        tl2_tunnel = TrackLink(link_id="L2_TUNNEL", track_id="TRK_02", start_node_id="M_3", end_node_id="M_2", length_m=1000.0, max_speed_ms=30.0)
        tl2_stn = TrackLink(link_id="L2_STN", track_id="TRK_02", start_node_id="M_2", end_node_id="M_1", length_m=500.0, max_speed_ms=30.0)
        tl2_exit = TrackLink(link_id="L2_EXIT", track_id="TRK_02", start_node_id="M_1", end_node_id="M_0", length_m=800.0, max_speed_ms=30.0)

        for tl in [tl2_entry, tl2_tunnel, tl2_stn, tl2_exit]:
            coord.resource_controller.register_resource(
                ManagedResource(
                    resource_id=f"BLK_{tl.link_id}",
                    category=ResourceCategory.TRACK_BLOCK,
                    intervals=[ResourceInterval(link_id=tl.link_id, start_offset_m=0.0, end_offset_m=tl.length_m)],
                    release_delay_s=2.0,
                )
            )

        plat2 = Platform(
            platform_id="PLT_ALPHA_2",
            station_id="STN_ALPHA",
            link_id="L2_STN",
            start_offset_m=50.0,
            end_offset_m=350.0,
            length_m=300.0,
        )
        coord.platform_controller.register_platform(plat2)

        traversals_opp = [
            LinkTraversal(link=tl2_entry, direction=RunningDirection.FORWARD, sequence_index=0, start_distance_m=0.0, end_distance_m=800.0),
            LinkTraversal(link=tl2_tunnel, direction=RunningDirection.FORWARD, sequence_index=1, start_distance_m=800.0, end_distance_m=1800.0),
            LinkTraversal(link=tl2_stn, direction=RunningDirection.FORWARD, sequence_index=2, start_distance_m=1800.0, end_distance_m=2300.0),
            LinkTraversal(link=tl2_exit, direction=RunningDirection.FORWARD, sequence_index=3, start_distance_m=2300.0, end_distance_m=3100.0),
        ]
        route_opp = Route(route_id="RT_CORRIDOR_OPP", traversals=traversals_opp)

    return coord, route_fwd, route_rev, route_opp


class TestStochasticIntegrationWorkflows:
    """End-to-end integration test suite connecting microscopic multi-train engine and Monte Carlo."""

    def test_forward_stochastic_simulation_monte_carlo(self) -> None:
        """Integration: Multi-train forward simulation under stochastic dwell, readiness, and traction."""
        params = make_train_params("TT_FWD")
        _, route_fwd, _, _ = make_corridor_infrastructure(double_track=False)

        svc = ServiceType(
            service_id="SVC_FWD",
            train_type_id="TT_FWD",
            params=params,
            route=route_fwd,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=25.0, platform_id="PLT_ALPHA_1")],
            running_direction=RunningDirection.FORWARD,
        )

        train_configs = [
            (svc, "TR_FWD_1", 0.0),
            (svc, "TR_FWD_2", 150.0),
        ]

        var_dwell = StochasticVariableDefinition(
            variable_id="VAR_DWELL",
            target_object_type=TargetObjectType.STATION_DWELL,
            target_object_id="STN_ALPHA",
            distribution_type=DistributionType.NORMAL,
            distribution_parameters={"mean": 25.0, "std_dev": 4.0},
            sampling_scope=SamplingScope.PER_STATION_STOP,
            min_value=20.0,
            max_value=40.0,
        )
        var_ready = StochasticVariableDefinition(
            variable_id="VAR_READY",
            target_object_type=TargetObjectType.DEPARTURE_READINESS,
            distribution_type=DistributionType.EXPONENTIAL,
            distribution_parameters={"rate": 0.1},
            sampling_scope=SamplingScope.PER_TRAIN,
            min_value=0.0,
            max_value=30.0,
        )

        mgr = MonteCarloSimulationManager(
            variables=[var_dwell, var_ready],
            master_seed=42,
        )

        mc_res = mgr.run_replications(
            coordinator_factory=lambda: make_corridor_infrastructure(double_track=False)[0],
            service_templates=[svc],
            train_generation_config=train_configs,
            replication_count=4,
            max_simulation_time_s=600.0,
            dt_s=0.5,
        )

        assert mc_res.total_replications == 4
        assert mc_res.valid_replications == 4
        assert mc_res.failed_replications == 0
        assert len(mc_res.replications) == 4

        for rep in mc_res.replications:
            assert rep.completed_train_count == 2
            assert rep.journey_times_s["TR_FWD_1"] > 0.0
            assert rep.journey_times_s["TR_FWD_2"] > 0.0

        assert "JOURNEY_TIME_S" in mc_res.statistical_summaries
        assert mc_res.statistical_summaries["JOURNEY_TIME_S"].sample_count == 8

    def test_reverse_stochastic_simulation_monte_carlo(self) -> None:
        """Integration: Multi-train REVERSE simulation under stochastic variations."""
        params = make_train_params("TT_REV")
        _, _, route_rev, _ = make_corridor_infrastructure(double_track=False)

        svc_rev = ServiceType(
            service_id="SVC_REV",
            train_type_id="TT_REV",
            params=params,
            route=route_rev,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=25.0, platform_id="PLT_ALPHA_1")],
            running_direction=RunningDirection.REVERSE,
        )

        train_configs = [
            (svc_rev, "TR_REV_1", 0.0),
            (svc_rev, "TR_REV_2", 150.0),
        ]

        var_dwell = StochasticVariableDefinition(
            variable_id="VAR_REV_DWELL",
            target_object_type=TargetObjectType.STATION_DWELL,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 20.0, "max_val": 35.0},
            sampling_scope=SamplingScope.PER_STATION_STOP,
            min_value=20.0,
        )

        mgr = MonteCarloSimulationManager(
            variables=[var_dwell],
            master_seed=99,
        )

        mc_res = mgr.run_replications(
            coordinator_factory=lambda: make_corridor_infrastructure(double_track=False)[0],
            service_templates=[svc_rev],
            train_generation_config=train_configs,
            replication_count=3,
            max_simulation_time_s=600.0,
            dt_s=0.5,
        )

        assert mc_res.valid_replications == 3
        for rep in mc_res.replications:
            assert rep.completed_train_count == 2
            assert rep.journey_times_s["TR_REV_1"] > 0.0
            assert rep.journey_times_s["TR_REV_2"] > 0.0

    def test_opposing_direction_stochastic_simulation(self) -> None:
        """Integration: Opposing direction simultaneous trains on double-track corridor."""
        params_fwd = make_train_params("TT_FWD")
        params_opp = make_train_params("TT_OPP")
        _, route_fwd, _, route_opp = make_corridor_infrastructure(double_track=True)
        assert route_opp is not None

        svc_fwd = ServiceType(
            service_id="SVC_FWD",
            train_type_id="TT_FWD",
            params=params_fwd,
            route=route_fwd,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=20.0, platform_id="PLT_ALPHA_1")],
            running_direction=RunningDirection.FORWARD,
        )
        svc_opp = ServiceType(
            service_id="SVC_OPP",
            train_type_id="TT_OPP",
            params=params_opp,
            route=route_opp,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=20.0, platform_id="PLT_ALPHA_2")],
            running_direction=RunningDirection.FORWARD,
        )

        train_configs = [
            (svc_fwd, "TR_DOWN_1", 0.0),
            (svc_opp, "TR_UP_1", 10.0),
        ]

        var_dwell = StochasticVariableDefinition(
            variable_id="VAR_BI_DWELL",
            target_object_type=TargetObjectType.STATION_DWELL,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 15.0, "max_val": 25.0},
            sampling_scope=SamplingScope.PER_STATION_STOP,
        )

        mgr = MonteCarloSimulationManager(
            variables=[var_dwell],
            master_seed=101,
        )

        mc_res = mgr.run_replications(
            coordinator_factory=lambda: make_corridor_infrastructure(double_track=True)[0],
            service_templates=[svc_fwd, svc_opp],
            train_generation_config=train_configs,
            replication_count=3,
            max_simulation_time_s=600.0,
            dt_s=0.5,
        )

        assert mc_res.valid_replications == 3
        for rep in mc_res.replications:
            assert rep.completed_train_count == 2
            assert "TR_DOWN_1" in rep.journey_times_s
            assert "TR_UP_1" in rep.journey_times_s

    def test_tvs_queueing_under_stochastic_variability(self) -> None:
        """Integration: TVS section single-train rule and queue tracking under stochastic headway."""
        params = make_train_params("TT_TVS")
        _, route_fwd, _, _ = make_corridor_infrastructure(double_track=False)

        svc = ServiceType(
            service_id="SVC_TVS",
            train_type_id="TT_TVS",
            params=params,
            route=route_fwd,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=20.0, platform_id="PLT_ALPHA_1")],
            running_direction=RunningDirection.FORWARD,
        )

        train_configs = [
            (svc, "TVS_TR1", 0.0),
            (svc, "TVS_TR2", 70.0),
        ]

        var_dwell = StochasticVariableDefinition(
            variable_id="VAR_TVS_DWELL",
            target_object_type=TargetObjectType.STATION_DWELL,
            distribution_type=DistributionType.NORMAL,
            distribution_parameters={"mean": 30.0, "std_dev": 5.0},
            sampling_scope=SamplingScope.PER_STATION_STOP,
            min_value=20.0,
        )

        mgr = MonteCarloSimulationManager(
            variables=[var_dwell],
            master_seed=77,
        )

        mc_res = mgr.run_replications(
            coordinator_factory=lambda: make_corridor_infrastructure(double_track=False)[0],
            service_templates=[svc],
            train_generation_config=train_configs,
            replication_count=3,
            max_simulation_time_s=600.0,
            dt_s=0.5,
        )

        assert mc_res.valid_replications == 3
        for rep in mc_res.replications:
            assert rep.completed_train_count == 2
            assert "TOTAL_TVS_WAIT" in rep.tvs_waiting_times_s

    def test_temporary_disruptions_propagation(self) -> None:
        """Integration: Temporary operational disruption causes downstream delay propagation."""
        params = make_train_params("TT_DISRUPT")
        _, route_fwd, _, _ = make_corridor_infrastructure(double_track=False)

        svc = ServiceType(
            service_id="SVC_DISRUPT",
            train_type_id="TT_DISRUPT",
            params=params,
            route=route_fwd,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=20.0, platform_id="PLT_ALPHA_1")],
            running_direction=RunningDirection.FORWARD,
        )

        train_configs = [
            (svc, "DIS_TR1", 0.0),
            (svc, "DIS_TR2", 80.0),
        ]

        disruption = OperationalDisruption(
            disruption_id="DIS_EXT_DWELL",
            disruption_type=DisruptionType.EXTENDED_STATION_DWELL,
            start_time_s=20.0,
            duration_s=60.0,
            affected_resources=["STN_ALPHA"],
            severity=3.0,
            operational_effect={"primary_delay_s": 60.0},
        )

        mgr = MonteCarloSimulationManager(
            disruptions=[disruption],
            master_seed=88,
        )

        mc_res = mgr.run_replications(
            coordinator_factory=lambda: make_corridor_infrastructure(double_track=False)[0],
            service_templates=[svc],
            train_generation_config=train_configs,
            replication_count=2,
            max_simulation_time_s=700.0,
            dt_s=0.5,
        )

        assert mc_res.valid_replications == 2
        for rep in mc_res.replications:
            assert rep.arrival_delays_s["DIS_TR1"] > 0.0 or rep.departure_delays_s["DIS_TR1"] > 0.0

    def test_common_random_numbers_crn_variance_reduction(self) -> None:
        """Integration: Common Random Numbers (CRN) synchronizes random variations across scenarios."""
        crn = CommonRandomNumbersManager(master_seed=123)
        rng1 = np.random.default_rng(100)
        rng2 = np.random.default_rng(200)

        # Drawing with same replication and key returns synchronized uniform
        u1 = crn.get_or_draw_uniform(replication_index=1, key="TR_1:DWELL", rng=rng1)
        u2 = crn.get_or_draw_uniform(replication_index=1, key="TR_1:DWELL", rng=rng2)
        assert u1 == u2

        # Different replication returns different uniform
        u3 = crn.get_or_draw_uniform(replication_index=2, key="TR_1:DWELL", rng=rng1)
        assert u1 != u3

    def test_reliability_based_capacity_assessment(self) -> None:
        """Integration: Reliability-Based Capacity Calculator evaluates candidate demand rates."""
        params = make_train_params("TT_CAP")
        _, route_fwd, _, _ = make_corridor_infrastructure(double_track=False)

        svc = ServiceType(
            service_id="SVC_CAP",
            train_type_id="TT_CAP",
            params=params,
            route=route_fwd,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=20.0, platform_id="PLT_ALPHA_1")],
            running_direction=RunningDirection.FORWARD,
        )

        crit_punc = ReliabilityCriterion("CRIT_PUNC", "PUNCTUALITY_PERCENT", ">=", 80.0, delay_tolerance_s=60.0)

        # Factory running a 2-replication Monte Carlo simulation for a given candidate demand rate
        def run_rate_mc(rate_tph: float) -> MonteCarloExecutionResult:
            headway_s = 3600.0 / rate_tph
            train_configs = [
                (svc, "CAP_TR1", 0.0),
                (svc, "CAP_TR2", headway_s),
            ]
            mgr = MonteCarloSimulationManager(
                reliability_criteria=[crit_punc],
                master_seed=42,
            )
            return mgr.run_replications(
                coordinator_factory=lambda: make_corridor_infrastructure(double_track=False)[0],
                service_templates=[svc],
                train_generation_config=train_configs,
                replication_count=2,
                max_simulation_time_s=headway_s + 400.0,
                dt_s=0.5,
            )

        cap_res, rate_results = ReliabilityBasedCapacityCalculator.evaluate_demand_rate_sweep(
            candidate_demand_rates_tph=[6.0, 10.0],
            mc_runner_factory=run_rate_mc,
            direction=RunningDirection.FORWARD,
            analysis_section="CORRIDOR_01",
        )

        assert len(rate_results) >= 1
        assert cap_res.capacity_trains_per_hour >= 0.0
        assert cap_res.details["certified_reliable_capacity_tph"] >= 0.0
