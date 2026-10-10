"""Integration test suite for Milestone P10 Railway Capacity, UIC 406 & Sensitivity Analysis.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- End-to-end multi-train microscopic simulation with resource tracking
- Resource utilization analysis (physical vs blocking) across blocks, platforms, TVS
- UIC 406 timetable compression and capacity consumption index
- Bidirectional FORWARD and REVERSE capacity assessment on shared infrastructure
- Operational stability evaluation and saturation search
- Sensitivity analysis framework with full physical recalculation and bottleneck migration
"""

import math
from typing import List

import pytest

from headway.analysis.bottleneck_migration import BottleneckAnalyzer
from headway.analysis.capacity import TheoreticalCapacityCalculator
from headway.analysis.capacity_consumption import CapacityConsumptionCalculator
from headway.analysis.capacity_models import (
    BottleneckCategory,
    CapacityType,
    MeasurementWindow,
    OperationalStabilityStatus,
    PlanningMarginMethod,
)
from headway.analysis.resource_utilization import ResourceUtilizationAnalyzer
from headway.analysis.saturation import CapacitySaturationSearch
from headway.analysis.sensitivity import SensitivityAnalyzer
from headway.analysis.stability import OperationalStabilityEvaluator
from headway.analysis.throughput import ThroughputCalculator
from headway.analysis.timetable_compression import TimetableCompressor
from headway.data.canonical import (
    AspectModelType,
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
from headway.simulation.dispatching import DispatchPolicy
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
    max_speed_ms: float = 30.0,
) -> RollingStockParameters:
    return RollingStockParameters(
        train_type_id=train_type_id,
        description=f"Train Type {train_type_id}",
        length_m=length_m,
        mass_empty_kg=200_000.0,
        mass_loaded_kg=250_000.0,
        rotating_mass_factor=0.08,
        max_speed_ms=max_speed_ms,
        max_acceleration_ms2=0.8,
        max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=2000.0,
        davis_b_ns_m=40.0,
        davis_c_ns2_m2=4.0,
        power_w=3_000_000.0,
        max_tractive_effort_n=200_000.0,
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
        tl = TrackLink(
            link_id=lid,
            track_id="TRK_MAIN",
            start_node_id=f"N_{i}" if direction == RunningDirection.FORWARD else f"N_{i+1}",
            end_node_id=f"N_{i+1}" if direction == RunningDirection.FORWARD else f"N_{i}",
            length_m=llen,
            max_speed_ms=35.0,
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


def setup_test_corridor():
    """Sets up a realistic railway corridor with blocks, station, and TVS."""
    coord = SignallingCoordinator(technology_type=SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL)

    link_ids = ["L_ENTRY", "L_STN", "L_TUNNEL", "L_EXIT"]
    link_lengths = [800.0, 500.0, 1000.0, 800.0]

    for lid, llen in zip(link_ids, link_lengths):
        coord.resource_controller.register_resource(
            ManagedResource(
                resource_id=f"BLK_{lid}",
                category=ResourceCategory.TRACK_BLOCK,
                intervals=[ResourceInterval(link_id=lid, start_offset_m=0.0, end_offset_m=llen)],
                release_delay_s=2.0,
            )
        )

    # Station on L_STN
    stn = Station(station_id="STN_ALPHA", name="Alpha Station")
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
        track_id="TRK_MAIN",
        link_intervals=[ResourceInterval(link_id="L_TUNNEL", start_offset_m=0.0, end_offset_m=1000.0)],
        release_delay_s=4.0,
    )
    coord.tvs_controller.register_tvs_section(tvs, auth_processing_delay_s=1.0)

    route_fwd = make_corridor_route("RT_FWD", link_ids, link_lengths, RunningDirection.FORWARD)
    params = make_train_params("TT_COMMUTER", length_m=140.0, max_speed_ms=25.0)

    return coord, route_fwd, params, link_ids, link_lengths


class TestCapacityIntegrationWorkflows:
    """End-to-end integration tests connecting multi-train simulation, capacity, UIC 406, and sensitivity."""

    def test_end_to_end_capacity_utilization_and_bottleneck_detection(self) -> None:
        """Integration: Multi-train simulation -> resource usage records -> utilization -> bottleneck ranking."""
        coord, route_fwd, params, link_ids, link_lengths = setup_test_corridor()

        svc = ServiceType(
            service_id="SVC_COMMUTER",
            train_type_id="TT_COMMUTER",
            params=params,
            route=route_fwd,
            stops=[StationStop(station_id="STN_ALPHA", dwell_time_s=25.0, platform_id="PLT_ALPHA_1")],
        )

        # 3 trains dispatched at 120s interval
        trains = [
            TrainGenerator.create_instance(svc, f"TR_COMM_{i}", requested_departure_s=i * 120.0)
            for i in range(3)
        ]

        sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=1.0)
        sim.register_trains(trains)
        res = sim.run_simulation(max_duration_s=600.0)

        assert len(res.completed_trains) == 3
        assert len(res.resource_usage_records) > 0

        # Analyze resource utilization
        analyzer = ResourceUtilizationAnalyzer(critical_threshold_percent=20.0)
        metrics = analyzer.analyze_simulation_result(res)

        assert len(metrics) >= 4
        # Every traversed block must have non-zero blocking time
        for lid in link_ids:
            blk_id = f"BLK_{lid}"
            assert blk_id in metrics
            m = metrics[blk_id]
            assert m.total_blocking_time_s > 0.0
            assert m.train_occupancy_count == 3
            # Physical occupation time must be strictly <= blocking time
            assert m.total_physical_occupation_time_s <= m.total_blocking_time_s

        # Identify bottlenecks from block headways
        headways = {m.resource_id: m.total_blocking_time_s / 3.0 for m in metrics.values()}
        diagnostics = BottleneckAnalyzer.identify_bottlenecks_from_headways(headways, resource_utilizations=metrics)
        assert len(diagnostics) == len(metrics)
        assert diagnostics[0].rank == 1
        assert diagnostics[0].limiting_headway_s >= diagnostics[1].limiting_headway_s

    def test_end_to_end_timetable_compression_and_uic406_consumption(self) -> None:
        """Integration: Simulation records -> TrainPathStairways -> timetable compression -> UIC 406 consumption."""
        coord, route_fwd, params, _, _ = setup_test_corridor()

        svc = ServiceType(
            service_id="SVC_LOCAL",
            train_type_id="TT_COMMUTER",
            params=params,
            route=route_fwd,
        )
        # Dispatched with wide 300s spacing
        trains = [
            TrainGenerator.create_instance(svc, "TR_LOC_1", requested_departure_s=0.0),
            TrainGenerator.create_instance(svc, "TR_LOC_2", requested_departure_s=300.0),
        ]
        sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=1.0)
        sim.register_trains(trains)
        res = sim.run_simulation(max_duration_s=800.0)

        compressor = TimetableCompressor(buffer_time_s=10.0)
        stairways = compressor.build_stairways_from_usage_records(res.resource_usage_records)
        assert len(stairways) == 2

        comp_res = compressor.compress_stairways(stairways, corridor_id="CORRIDOR_ALPHA")
        assert comp_res.train_count == 2
        # Compressed duration must be strictly less than original span (since trains had 300s interval)
        assert comp_res.compressed_duration_s < comp_res.original_duration_s
        assert comp_res.compression_ratio < 1.0

        # Calculate UIC 406 capacity consumption
        uic_res = CapacityConsumptionCalculator.calculate_from_compression_result(
            compression_result=comp_res,
            analysis_window_s=1200.0,
            supplement_s=150.0,
        )
        assert uic_res.capacity_type == CapacityType.UIC406_CAPACITY_CONSUMPTION
        assert 0.0 < uic_res.capacity_trains_per_hour <= 100.0
        assert "UIC" in uic_res.details["uic_disclaimer"]

    def test_end_to_end_bidirectional_corridor_capacity(self) -> None:
        """Integration: Bidirectional simulation with FORWARD and REVERSE trains sharing single corridor."""
        coord, route_fwd, params, link_ids, link_lengths = setup_test_corridor()
        route_rev = make_corridor_route("RT_REV", list(reversed(link_ids)), list(reversed(link_lengths)), RunningDirection.REVERSE)

        svc_fwd = ServiceType("SVC_FWD", "TT_COMMUTER", params, route_fwd, running_direction=RunningDirection.FORWARD)
        svc_rev = ServiceType("SVC_REV", "TT_COMMUTER", params, route_rev, running_direction=RunningDirection.REVERSE)

        train_fwd = TrainGenerator.create_instance(svc_fwd, "TR_FWD", requested_departure_s=0.0)
        # Reverse train departs after forward train clears tunnel (at t=250s)
        train_rev = TrainGenerator.create_instance(svc_rev, "TR_REV", requested_departure_s=250.0)

        sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=1.0)
        sim.register_trains([train_fwd, train_rev])
        res = sim.run_simulation(max_duration_s=600.0)

        assert len(res.completed_trains) == 2

        # Analyze resource utilization
        analyzer = ResourceUtilizationAnalyzer()
        metrics = analyzer.analyze_simulation_result(res)

        # Tunnel block was used by both FORWARD and REVERSE trains
        m_tunnel = metrics["BLK_L_TUNNEL"]
        assert m_tunnel.forward_blocking_time_s > 0.0
        assert m_tunnel.reverse_blocking_time_s > 0.0
        assert m_tunnel.total_blocking_time_s >= m_tunnel.forward_blocking_time_s + m_tunnel.reverse_blocking_time_s - 1e-6

        # Calculate homogeneous capacity in both directions
        cap_fwd = TheoreticalCapacityCalculator.calculate_homogeneous_capacity(
            headway_s=m_tunnel.forward_blocking_time_s,
            direction=RunningDirection.FORWARD,
        )
        cap_rev = TheoreticalCapacityCalculator.calculate_homogeneous_capacity(
            headway_s=m_tunnel.reverse_blocking_time_s,
            direction=RunningDirection.REVERSE,
        )
        assert cap_fwd.running_direction == RunningDirection.FORWARD
        assert cap_rev.running_direction == RunningDirection.REVERSE
        assert cap_fwd.capacity_trains_per_hour > 0.0
        assert cap_rev.capacity_trains_per_hour > 0.0

    def test_end_to_end_stability_and_saturation_search(self) -> None:
        """Integration: Microscopic simulator in saturation loop finding sustainable operational capacity."""
        evaluator = OperationalStabilityEvaluator(delay_slope_unstable_threshold=1.5)

        # Simulation runner function: dispatch 2 trains at interval 3600 / demand_tph
        def run_sim_at_rate(rate_tph: float):
            coord, route_fwd, params, _, _ = setup_test_corridor()
            svc = ServiceType("SVC_TEST", "TT_COMMUTER", params, route_fwd)
            interval_s = 3600.0 / rate_tph
            trains = [
                TrainGenerator.create_instance(svc, "TR_SAT_1", requested_departure_s=0.0),
                TrainGenerator.create_instance(svc, "TR_SAT_2", requested_departure_s=interval_s),
            ]
            sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2, storage_interval_s=1.0)
            sim.register_trains(trains)
            return sim.run_simulation(max_duration_s=800.0)

        searcher = CapacitySaturationSearch(stability_evaluator=evaluator)
        cap_res, evals = searcher.run_step_scan(
            candidate_demand_rates_tph=[10.0, 15.0, 20.0],
            simulation_runner=run_sim_at_rate,
        )

        assert cap_res.capacity_type == CapacityType.SUSTAINABLE_OPERATIONAL_CAPACITY
        assert cap_res.capacity_trains_per_hour > 0.0
        assert cap_res.stability_evaluation is not None
        assert cap_res.stability_evaluation.is_sustainable is True

    def test_end_to_end_parameter_sensitivity_and_bottleneck_migration(self) -> None:
        """Integration: Full parameter sensitivity study showing bottleneck migration from block to station."""
        analyzer = SensitivityAnalyzer()

        # Dwell sensitivity: at dwell=10s, line block is bottleneck; at dwell=100s, station platform is bottleneck
        study = analyzer.evaluate_station_dwell_sensitivity(
            baseline_dwell_s=15.0,
            candidate_dwells_s=[15.0, 30.0, 60.0, 90.0, 120.0],
            line_headway_s=80.0,
            clearing_time_s=30.0,
        )

        assert len(study.points) == 5
        assert len(study.migration_records) == 5

        # Verify bottleneck migration occurred
        migrated_records = [m for m in study.migration_records if m.bottleneck_migrated]
        assert len(migrated_records) > 0
        mig = migrated_records[0]
        assert "LINE" in mig.baseline_bottleneck_id
        assert "PLATFORM" in mig.modified_bottleneck_id
        assert "migrated from" in mig.diagnostic_commentary
