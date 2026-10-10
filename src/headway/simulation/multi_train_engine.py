"""Microscopic multi-train operational simulation engine.

Strictly satisfies RHS-P09-001:
- P09-MTR-001 to 007: Single shared simulation clock, shared resource manager and signalling,
  independent P04 microscopic dynamics, atomic state updates, no trajectory shifting, and determinism.
- P09-MIC-001 to 007: Microscopic integration, dynamic target braking, train length tracking,
  zero teleportation, and physical stopping behavior.
- P09-SIG-001 to 006: Fixed-block, ETCS Level 2, and CBTC moving-block multi-train interactions.
- P09-ST-001 to 008: Station arrival, deterministic dwell, departure authorization, residual rear.
- P09-PLT-001 to 006: Platform allocation (FIXED, PREFERRED, EARLIEST_FEASIBLE).
- P09-JNC-001 to 006: Junction and merge sequencing, waiting, and route locking.
- P09-TVS-001 to 009: TVS single-train rule, entry waiting, holding points, and release.
- P09-DIR-001 to 009: FORWARD, REVERSE, and simultaneous opposing-direction operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

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
from headway.core.exceptions import DeadlockError, OperationalSimulationError, SimulationError
from headway.data.canonical import (
    AspectModelType,
    InfrastructureModel,
    SignallingModel,
    SignallingTechnologyType,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.infrastructure.stations import RoutePlatformStop
from headway.rolling_stock.train import RollingStockParameters
from headway.signalling.platform_controller import PlatformSelectionPolicy
from headway.signalling.resource_types import ResourceCategory, SignallingEvent
from headway.simulation.deadlock import DeadlockDetector, DeadlockReport
from headway.simulation.dispatching import DispatchPolicy, OriginDepartureQueue
from headway.simulation.events import BoundaryEvent, CrossingEventType
from headway.simulation.integrator import MicroscopicSimulator
from headway.simulation.service_instance import (
    ServiceType,
    TrainGenerator,
    TrainServiceInstance,
)
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.targets import BrakingTarget, BrakingTargetType
from headway.simulation.time_distance import MultiTrainTimeDistanceDataset, TimeDistancePoint
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory
from headway.simulation.tvs_queue import TVSQueueTracker

if TYPE_CHECKING:
    from headway.signalling.coordinator import SignallingCoordinator


@dataclass
class MultiTrainSimulationResult:
    """Comprehensive deliverable result package from multi-train operational simulation."""

    train_instances: List[TrainServiceInstance]
    trajectories: Dict[str, TrainTrajectory]
    time_distance_dataset: MultiTrainTimeDistanceDataset
    events: List[SignallingEvent]
    boundary_events: List[BoundaryEvent]
    delay_summaries: Dict[str, TrainDelaySummary]
    journey_decompositions: Dict[str, JourneyTimeDecomposition]
    kpis: OperationalKPIs
    deadlock_report: Optional[DeadlockReport] = None
    starvation_warnings: List[Dict[str, any]] = field(default_factory=list)
    completed_trains: List[TrainServiceInstance] = field(default_factory=list)
    dispatched_trains: List[TrainServiceInstance] = field(default_factory=list)


class MultiTrainSimulator:
    """Deterministic microscopic multi-train operational simulation engine."""

    def __init__(
        self,
        coordinator: Optional["SignallingCoordinator"] = None,
        dispatch_policy: DispatchPolicy = DispatchPolicy.FIRST_COME_FIRST_SERVED,
        dt_s: float = 0.1,
        storage_interval_s: Optional[float] = 1.0,
        enable_deadlock_detection: bool = True,
        fail_on_deadlock: bool = False,
    ) -> None:
        if coordinator is None:
            from headway.signalling.coordinator import SignallingCoordinator
            self.coordinator = SignallingCoordinator()
        else:
            self.coordinator = coordinator
        self.dispatch_policy = dispatch_policy
        self.dt_s = max(0.01, float(dt_s))
        self.storage_interval_s = storage_interval_s if storage_interval_s and storage_interval_s >= self.dt_s else self.dt_s
        self.enable_deadlock_detection = enable_deadlock_detection
        self.fail_on_deadlock = fail_on_deadlock

        # Internal Subsystems
        self.origin_queue = OriginDepartureQueue(dispatch_policy=dispatch_policy)
        self.deadlock_detector = DeadlockDetector()
        self.tvs_queue_tracker = TVSQueueTracker()
        self.delay_tracker = DelayPropagationTracker()

        # Operational State
        self.current_time_s: float = 0.0
        self.active_trains: List[TrainServiceInstance] = []
        self.dispatched_trains: List[TrainServiceInstance] = []
        self.completed_trains: List[TrainServiceInstance] = []
        self.all_trains: List[TrainServiceInstance] = []
        self.time_distance_dataset = MultiTrainTimeDistanceDataset()

        # Cached unconstrained journey times: service_id -> (unconstrained_jt, planned_dwell)
        self._unconstrained_cache: Dict[str, Tuple[float, float]] = {}
        # Track occupied resources by train: train_id -> set of resource_ids
        self._train_occupied_resources: Dict[str, Set[str]] = {}
        self._train_entered_resources: Dict[str, Set[Tuple[int, str]]] = {}

    def register_train(self, train: TrainServiceInstance) -> None:
        """Register a single train instance for simulation."""
        if any(t.train_id == train.train_id for t in self.all_trains):
            raise OperationalSimulationError(
                f"Duplicate train_id '{train.train_id}' is prohibited.",
                context={"train_id": train.train_id},
            )
        self.all_trains.append(train)
        self.origin_queue.enqueue(train)
        self._train_occupied_resources[train.train_id] = set()
        self._train_entered_resources[train.train_id] = set()

    def register_trains(self, trains: List[TrainServiceInstance]) -> None:
        """Register multiple train instances."""
        for t in trains:
            self.register_train(t)

    def _get_unconstrained_journey_time(self, service: ServiceType) -> Tuple[float, float]:
        """Compute and cache standalone unconstrained journey time for a service type."""
        if service.service_id in self._unconstrained_cache:
            return self._unconstrained_cache[service.service_id]

        sim = MicroscopicSimulator(
            route=service.route,
            params=service.params,
            station_views=[],
            dt_s=self.dt_s,
        )
        traj = sim.simulate(
            train_id=f"REF_{service.service_id}",
            max_duration_s=7200.0,
            default_dwell_time_s=30.0,
        )
        jt = traj.journey_time_s
        # Calculate planned dwell time
        planned_dwell = sum(st.dwell_time_s for st in service.stops)
        self._unconstrained_cache[service.service_id] = (jt, planned_dwell)
        return jt, planned_dwell

    def _find_downstream_eoa(
        self,
        train: TrainServiceInstance,
    ) -> Tuple[float, Optional[str], Optional[str]]:
        """P09-MIC-003 & P09-SIG: Determine movement authority limit along route.

        Returns (eoa_distance_m, governing_cause, holding_resource_id).
        """
        route_len = train.route.total_length_m
        curr_pos = train.current_position_m

        # Default limit is route end
        min_eoa = route_len
        governing_cause = None
        holding_res = None

        # 1. Signalling / Block Constraints
        # Check downstream blocks on this route
        for trav in train.route.traversals:
            dist_along = train.route.physical_to_route_distance(trav.link_id, 0.0)
            if dist_along is None:
                continue

            # Look up blocks on this link
            for res_id, res in self.coordinator.resource_controller.resources.items():
                res_links = [inv.link_id for inv in res.intervals] if res.intervals else []
                if trav.link_id in res_links or getattr(res, "link_id", None) == trav.link_id or res_id == f"BLK_{trav.link_id}":
                    if res.category == ResourceCategory.TRACK_BLOCK:
                        # Check if block is ahead of train front
                        if dist_along > curr_pos:
                            # Is block available for this train?
                            if not self.coordinator.resource_controller.is_resource_available(res_id, train.train_id, self.current_time_s):
                                if dist_along < min_eoa:
                                    min_eoa = dist_along
                                    governing_cause = "SIGNALLING"
                                    holding_res = res_id

        # 2. CBTC Moving-Block Separation (P09-SIG-003 & P09-B014)
        if self.coordinator.technology_type in (
            SignallingTechnologyType.CBTC_MOVING_BLOCK,
            SignallingTechnologyType.CBTC_MOVING_BLOCK_ENGINEERING_MODEL,
        ):
            # Find closest leader train ahead on the same route
            for leader in self.active_trains:
                if leader.train_id != train.train_id and not leader.is_completed and leader.route.route_id == train.route.route_id:
                    if leader.current_position_m > curr_pos:
                        safe_eoa = max(0.0, leader.rear_position_m - 50.0)  # 50m safety margin
                        if safe_eoa < min_eoa:
                            min_eoa = safe_eoa
                            governing_cause = "FOLLOWING_TRAIN"
                            holding_res = leader.train_id

        # 3. TVS Sections Constraint (P09-TVS-002 & 003)
        tvs_configs = getattr(self.coordinator.tvs_controller, "configs", {})
        for tvs_id, cfg in tvs_configs.items():
            tvs_sec = cfg.tvs
            # Check if TVS intersects train route
            for interval in tvs_sec.link_intervals:
                tvs_route_pos = train.route.physical_to_route_distance(interval.link_id, interval.start_offset_m)
                if tvs_route_pos is not None and tvs_route_pos > curr_pos:
                    # TVS entry holding point is 20m before boundary
                    holding_pt = max(0.0, tvs_route_pos - 20.0)
                    if tvs_route_pos - curr_pos < 500.0:
                        # Near TVS: request entry authorization once
                        t_st = self.coordinator.tvs_controller.train_states.get((train.train_id, tvs_id))
                        if not t_st:
                            self.coordinator.tvs_controller.request_tvs_entry(train.train_id, tvs_id, self.current_time_s)
                        if not self.coordinator.tvs_controller.is_train_authorized(train.train_id, tvs_id, self.current_time_s):
                            if holding_pt < min_eoa:
                                min_eoa = holding_pt
                                governing_cause = "TVS"
                                holding_res = tvs_id
                                self.tvs_queue_tracker.record_waiting_train(tvs_id, train.train_id, self.current_time_s)

        # 4. Junction Interlocking Routes (P09-JNC-001 & 004)
        for r_id, r_state in self.coordinator.interlocking_engine.active_states.items():
            r_def = r_state.route_def
            if r_def.link_sequence:
                first_link = r_def.link_sequence[0]
                jnc_route_pos = train.route.physical_to_route_distance(first_link, 0.0)
                if jnc_route_pos is not None and jnc_route_pos > curr_pos:
                    holding_pt = max(0.0, jnc_route_pos - 15.0)
                    if jnc_route_pos - curr_pos < 300.0:
                        # Request junction route
                        if self.coordinator.interlocking_engine.is_route_available(r_id, train.train_id, self.current_time_s):
                            self.coordinator.interlocking_engine.request_and_lock_route(r_id, train.train_id, self.current_time_s)
                        else:
                            if holding_pt < min_eoa:
                                min_eoa = holding_pt
                                governing_cause = "JUNCTION"
                                holding_res = r_id

        # 5. Scheduled Station Stop (P09-ST-001)
        if train.stops and train.current_stop_index < len(train.stops) and not train.is_dwelling:
            stop = train.stops[train.current_stop_index]
            plat_obj = self.coordinator.platform_controller.platforms.get(stop.platform_id)
            plat_link = None
            plat_offset = 0.0
            if plat_obj:
                plat_link = plat_obj.link_id
                plat_offset = plat_obj.start_offset_m + min(plat_obj.length_m, train.params.length_m)
            else:
                plat_res = self.coordinator.resource_controller.resources.get(stop.platform_id)
                if plat_res:
                    plat_link = getattr(plat_res, "link_id", None) or (plat_res.intervals[0].link_id if plat_res.intervals else None)
                    plat_offset = plat_res.intervals[0].start_offset_m if plat_res.intervals else 0.0

            if plat_link:
                plat_pos = train.route.physical_to_route_distance(plat_link, plat_offset)
                if plat_pos is not None and plat_pos > curr_pos - 1.0:
                    # Check platform availability
                    if not self.coordinator.resource_controller.is_resource_available(stop.platform_id, train.train_id, self.current_time_s):
                        # Platform is occupied by another train (P09-B016)
                        holding_pt = max(0.0, plat_pos - 50.0)
                        if holding_pt < min_eoa:
                            min_eoa = holding_pt
                            governing_cause = "PLATFORM"
                            holding_res = stop.platform_id
                    else:
                        # Target is station stopping point
                        if plat_pos < min_eoa:
                            min_eoa = plat_pos
                            governing_cause = "STATION_STOP"
                            holding_res = stop.station_id

        return min_eoa, governing_cause, holding_res

    def _step_train(self, train: TrainServiceInstance, dt: float) -> None:
        """P04-NUM & P09-MIC: Step microscopic dynamics for one active train."""
        curr_s = train.current_position_m
        curr_v = train.current_speed_ms
        route_len = train.route.total_length_m

        # 1. Handle Active Station Dwell (P09-ST-003)
        if train.is_dwelling:
            train.dynamic_mode = DynamicMode.DWELLING
            train.operational_state = OperationalState.STATION_DWELL
            train.current_speed_ms = 0.0
            train.current_acceleration_ms2 = 0.0

            if train.remaining_dwell_s > 0.0:
                train.remaining_dwell_s = max(0.0, train.remaining_dwell_s - dt)
                return
            else:
                # Dwell complete, check departure authorization (P09-ST-006)
                stn_id = train.dwelling_station_id or "STN"
                train.events.append(
                    BoundaryEvent(
                        event_type=CrossingEventType.STATION_DEPARTED,
                        timestamp_s=round(self.current_time_s, 3),
                        route_distance_m=round(curr_s, 2),
                        train_id=train.train_id,
                        is_front=True,
                        speed_ms=0.0,
                        description=f"Train '{train.train_id}' departed station '{stn_id}'",
                    )
                )
                train.is_dwelling = False
                train.dwelling_station_id = None
                train.current_stop_index += 1
                train.dynamic_mode = DynamicMode.ACCELERATING
                train.operational_state = OperationalState.RUNNING
                train.active_waiting_cause = None

        # 2. Determine Governing Downstream Target (P09-MIC-004)
        eoa_m, cause, res_id = self._find_downstream_eoa(train)
        dist_to_eoa = max(0.0, eoa_m - curr_s)

        # Braking curve speed limit to stop at eoa_m
        b_service = train.params.max_service_deceleration_ms2
        v_brake_sq = 2.0 * b_service * dist_to_eoa
        v_brake_limit = math.sqrt(max(0.0, v_brake_sq))

        # Permissible line speed
        v_line_limit = train.params.max_speed_ms
        v_target = min(v_line_limit, v_brake_limit)

        # 3. Dynamic Mode & Acceleration Selection
        if cause == "STATION_STOP" and ((dist_to_eoa <= 2.0 and curr_v < 3.0) or (curr_s >= eoa_m - 0.5 and curr_v < 3.0)):
            # Arrived at scheduled station stop
            stop = train.stops[train.current_stop_index]
            train.current_position_m = round(eoa_m, 3)
            train.current_speed_ms = 0.0
            train.current_acceleration_ms2 = 0.0
            train.is_dwelling = True
            train.remaining_dwell_s = stop.dwell_time_s
            train.dwelling_station_id = stop.station_id
            train.operational_state = OperationalState.STATION_DWELL
            train.dynamic_mode = DynamicMode.DWELLING
            train.events.append(
                BoundaryEvent(
                    event_type=CrossingEventType.STATION_ARRIVED,
                    timestamp_s=round(self.current_time_s, 3),
                    route_distance_m=round(train.current_position_m, 2),
                    train_id=train.train_id,
                    is_front=True,
                    speed_ms=0.0,
                    description=f"Train '{train.train_id}' arrived at station '{stop.station_id}'",
                )
            )
            self.coordinator.platform_controller.front_enter_platform(train.train_id, stop.platform_id, self.current_time_s)
            self._train_occupied_resources.setdefault(train.train_id, set()).add(stop.platform_id)
            return

        if (dist_to_eoa <= 1.0 and curr_v < 1.0) or (curr_v == 0.0 and dist_to_eoa <= 2.0):
            # Stopped at target
            if eoa_m < route_len:
                train.current_position_m = round(max(0.0, eoa_m - 0.1), 3)
            train.current_speed_ms = 0.0
            train.current_acceleration_ms2 = 0.0
            train.dynamic_mode = DynamicMode.STOPPED
            if dist_to_eoa <= 1.0 and curr_s >= route_len - 1.0:
                # Arrived at end of route
                train.operational_state = OperationalState.COMPLETED
                train.actual_completion_time_s = self.current_time_s
                return
            else:
                # Stopped due to operational restriction
                delay_cause = cause or "SIGNALLING"
                train.record_delay(delay_cause, dt)
                train.active_waiting_cause = f"WAITING_{delay_cause}_{res_id}"
                if train.waiting_start_time_s is None:
                    train.waiting_start_time_s = self.current_time_s
                return
        else:
            # Train is moving
            train.active_waiting_cause = None
            train.waiting_start_time_s = None

            # Resistances at current position (P04 physics)
            res_eval = train.resistance_engine.evaluate(
                speed_ms=curr_v,
                front_position_m=curr_s,
                alignment=train.route,
            )

            target_dec = None
            is_coast = False
            tract_n = None

            if curr_v >= v_brake_limit - 0.05:
                train.dynamic_mode = DynamicMode.SERVICE_BRAKING
                train.operational_state = OperationalState.RUNNING
                target_dec = train.params.max_service_deceleration_ms2
            elif curr_v >= v_line_limit - 0.05:
                train.dynamic_mode = DynamicMode.CRUISING
                train.operational_state = OperationalState.RUNNING
                tract_n = max(0.0, res_eval.total_resistance_n)
            else:
                train.dynamic_mode = DynamicMode.ACCELERATING
                train.operational_state = OperationalState.RUNNING

            fb_res = train.force_engine.evaluate_acceleration(
                speed_ms=curr_v,
                resistance=res_eval,
                tractive_force_n=tract_n,
                target_deceleration_ms2=target_dec,
                is_coasting=is_coast,
            )
            a_req = fb_res.capped_acceleration_ms2

            # Numerical integration step
            if a_req < 0 and curr_v + a_req * dt < 0:
                t_stop = -curr_v / a_req if abs(a_req) > 1e-6 else 0.0
                step_dt = max(1e-4, t_stop)
                new_s = curr_s + curr_v * step_dt + 0.5 * a_req * (step_dt ** 2)
                new_v = 0.0
            else:
                new_s = curr_s + curr_v * dt + 0.5 * a_req * (dt ** 2)
                new_v = max(0.0, curr_v + a_req * dt)

            if eoa_m < route_len and new_s >= eoa_m:
                new_s = max(0.0, eoa_m - 0.1)
                new_v = 0.0
                a_req = 0.0

            train.current_speed_ms = round(new_v, 4)
            train.current_acceleration_ms2 = round(a_req, 4)
            train.current_position_m = round(min(route_len, new_s), 3)

            if new_s >= route_len - 0.2 and new_v < 0.2:
                train.current_position_m = route_len
                train.current_speed_ms = 0.0
                train.current_acceleration_ms2 = 0.0
                train.dynamic_mode = DynamicMode.STOPPED
                train.operational_state = OperationalState.COMPLETED
                train.actual_completion_time_s = self.current_time_s

    def _update_resource_occupations(self, current_time_s: float) -> None:
        """P09-MIC-005 & P05: Track train-front entry and train-rear clearance through resources."""
        for train in list(self.active_trains):
            if train.is_completed:
                continue

            curr_front = train.current_position_m
            curr_rear = train.rear_position_m
            held_res = self._train_occupied_resources.setdefault(train.train_id, set())
            entered = self._train_entered_resources.setdefault(train.train_id, set())

            # Check all route traversals
            for i, trav in enumerate(train.route.traversals):
                link_start = train.route.physical_to_route_distance(trav.link_id, 0.0)
                link_end = train.route.physical_to_route_distance(trav.link_id, trav.length_m)
                if link_start is None or link_end is None:
                    continue

                r_start = min(link_start, link_end)
                r_end = max(link_start, link_end)

                # Find resources associated with this link
                for res_id, res in self.coordinator.resource_controller.resources.items():
                    res_links = [inv.link_id for inv in res.intervals] if res.intervals else []
                    if trav.link_id in res_links or getattr(res, "link_id", None) == trav.link_id or res_id == f"BLK_{trav.link_id}":
                        key = (i, res_id)
                        # Front entry
                        if key not in entered and curr_front >= r_start and curr_rear < r_end:
                            if res_id not in res.reservations:
                                self.coordinator.resource_controller.reserve_resource(
                                    train_id=train.train_id,
                                    resource_id=res_id,
                                    timestamp_s=current_time_s,
                                    running_direction=train.running_direction,
                                )
                            self.coordinator.resource_controller.front_enter_resource(
                                train_id=train.train_id,
                                resource_id=res_id,
                                timestamp_s=current_time_s,
                            )
                            entered.add(key)
                            held_res.add(res_id)

                        # Rear clearance
                        if res_id in held_res and curr_rear >= r_end:
                            self.coordinator.resource_controller.rear_clear_resource(
                                train_id=train.train_id,
                                resource_id=res_id,
                                timestamp_s=current_time_s,
                            )
                            held_res.discard(res_id)

            # Check occupied platforms for rear clearance (P07 & P09-ST-007)
            for plat_id, plat_obj in self.coordinator.platform_controller.platforms.items():
                if plat_id in held_res and not train.is_dwelling:
                    p_end = train.route.physical_to_route_distance(plat_obj.link_id, max(plat_obj.start_offset_m, plat_obj.end_offset_m))
                    if p_end is not None and curr_rear >= p_end:
                        self.coordinator.platform_controller.rear_clear_platform(train.train_id, plat_id, current_time_s)
                        held_res.discard(plat_id)

            # Check TVS sections for front entry and rear clearance (P07 & P09-TVS-003)
            for tvs_id, cfg in getattr(self.coordinator.tvs_controller, "configs", {}).items():
                for interval in cfg.tvs.link_intervals:
                    tvs_start = train.route.physical_to_route_distance(interval.link_id, interval.start_offset_m)
                    tvs_end = train.route.physical_to_route_distance(interval.link_id, interval.end_offset_m)
                    if tvs_start is not None and tvs_end is not None:
                        t_start = min(tvs_start, tvs_end)
                        t_end = max(tvs_start, tvs_end)
                        tvs_key = f"TVS_{tvs_id}"
                        if tvs_key not in entered and curr_front >= t_start and curr_rear < t_end:
                            self.coordinator.tvs_controller.front_enter_tvs(train.train_id, tvs_id, current_time_s)
                            entered.add(tvs_key)
                            held_res.add(tvs_key)
                        if tvs_key in held_res and curr_rear >= t_end:
                            self.coordinator.tvs_controller.rear_clear_tvs(train.train_id, tvs_id, current_time_s)
                            held_res.discard(tvs_key)

    def _record_trajectory_samples(self) -> None:
        """Record trajectory samples and time-distance dataset points at storage intervals."""
        for train in self.all_trains:
            if train.operational_state == OperationalState.STANDSTILL and train.actual_departure_time_s is None:
                continue

            # Record TrajectorySample
            train.trajectory_samples.append(
                TrajectorySample(
                    time_s=round(self.current_time_s, 3),
                    front_distance_m=round(train.current_position_m, 2),
                    rear_distance_m=round(train.rear_position_m, 2),
                    speed_ms=round(train.current_speed_ms, 3),
                    acceleration_ms2=round(train.current_acceleration_ms2, 3),
                    traction_force_n=0.0,
                    braking_force_n=0.0,
                    davis_resistance_n=0.0,
                    gradient_resistance_n=0.0,
                    curvature_resistance_n=0.0,
                    net_force_n=0.0,
                    dynamic_mode=train.dynamic_mode,
                    operational_state=train.operational_state,
                )
            )

            # Record TimeDistancePoint (P09-TDP)
            self.time_distance_dataset.add_point(
                TimeDistancePoint(
                    train_id=train.train_id,
                    service_id=train.service_id,
                    route_id=train.route.route_id,
                    running_direction=train.running_direction,
                    time_s=round(self.current_time_s, 3),
                    route_distance_m=round(train.current_position_m, 2),
                    physical_chainage_m=None,
                    speed_ms=round(train.current_speed_ms, 3),
                    speed_kmh=round(train.current_speed_ms * 3.6, 2),
                    operational_state=train.operational_state,
                    accumulated_delay_s=round(sum(train.accumulated_delay_by_cause.values()), 2),
                )
            )

    def run_simulation(
        self,
        max_duration_s: float = 3600.0,
    ) -> MultiTrainSimulationResult:
        """Execute full deterministic simultaneous multi-train simulation."""
        self.current_time_s = 0.0
        dt = self.dt_s
        last_storage_t = -1e9
        deadlock_report: Optional[DeadlockReport] = None

        while self.current_time_s <= max_duration_s + 1e-6:
            # 1. Process Origin Queue Dispatches (P09-DEP & P09-DSP)
            newly_dispatched = self.origin_queue.process_origin_dispatches(
                coordinator=self.coordinator,
                current_time_s=self.current_time_s,
            )
            for t in newly_dispatched:
                self.active_trains.append(t)
                self.dispatched_trains.append(t)

            # 2. Step Dynamics for All Active Trains (P09-MIC)
            for train in list(self.active_trains):
                if not train.is_completed:
                    self._step_train(train, dt)
                    if train.is_completed and train not in self.completed_trains:
                        self.completed_trains.append(train)
                        self.active_trains.remove(train)
                        # Release remaining occupied resources
                        held = self._train_occupied_resources.get(train.train_id, set())
                        for r_id in list(held):
                            if r_id in self.coordinator.platform_controller.platforms:
                                self.coordinator.platform_controller.rear_clear_platform(train.train_id, r_id, self.current_time_s)
                            else:
                                self.coordinator.resource_controller.rear_clear_resource(train.train_id, r_id, self.current_time_s)
                        held.clear()
                        for tvs_id in list(getattr(self.coordinator.tvs_controller, "configs", {}).keys()):
                            if train.train_id in self.coordinator.tvs_controller.active_occupants.get(tvs_id, set()):
                                self.coordinator.tvs_controller.rear_clear_tvs(train.train_id, tvs_id, self.current_time_s)

            # 3. Process Resource Crossings & Coordinator Event Ordering (P05 & P09-MTR)
            self._update_resource_occupations(self.current_time_s)
            self.coordinator.process_timestep_events(self.current_time_s)

            # 4. TVS Queue Tracking (P09-TVS)
            self.tvs_queue_tracker.update_snapshot(self.current_time_s, self.active_trains)

            # 5. Deadlock Detection (P09-DLK)
            if self.enable_deadlock_detection:
                deadlock_report = self.deadlock_detector.check_deadlocks(
                    active_trains=self.active_trains,
                    coordinator=self.coordinator,
                    current_time_s=self.current_time_s,
                )
                if deadlock_report:
                    if self.fail_on_deadlock:
                        raise DeadlockError(
                            deadlock_report.description,
                            context={"trains": deadlock_report.involved_train_ids, "time_s": self.current_time_s},
                        )
                    break

            # 6. Record Trajectory Samples
            if self.current_time_s - last_storage_t >= self.storage_interval_s - 1e-6:
                self._record_trajectory_samples()
                last_storage_t = self.current_time_s

            # Check Termination Condition: All trains completed
            if self.origin_queue.is_empty() and all(t.is_completed for t in self.active_trains):
                # Final storage sample
                self._record_trajectory_samples()
                break

            self.current_time_s = round(self.current_time_s + dt, 4)

        # 7. Post-Simulation Analysis (Journey Time & Delay Attribution)
        trajectories: Dict[str, TrainTrajectory] = {}
        delay_summaries: Dict[str, TrainDelaySummary] = {}
        journey_decompositions: Dict[str, JourneyTimeDecomposition] = {}

        for train in self.all_trains:
            trajectories[train.train_id] = train.build_trajectory()

            # Delay Summary (P09-DLY)
            st = ServiceType(
                service_id=train.service_id,
                train_type_id=train.params.train_type_id,
                params=train.params,
                route=train.route,
                stops=train.stops,
                priority=train.priority,
                running_direction=train.running_direction,
            )
            unconstrained_jt, planned_dwell = self._get_unconstrained_journey_time(st)
            scheduled_arr = train.requested_departure_time_s + unconstrained_jt

            delays_by_cause = {DelayCause[c] if c in DelayCause.__members__ else DelayCause.OTHER: dur for c, dur in train.accumulated_delay_by_cause.items()}
            dep_delay = train.departure_delay_s or 0.0
            arr_delay = max(0.0, (train.actual_completion_time_s - scheduled_arr)) if train.actual_completion_time_s else 0.0

            d_summary = TrainDelaySummary(
                train_id=train.train_id,
                service_id=train.service_id,
                requested_departure_s=train.requested_departure_time_s,
                actual_departure_s=train.actual_departure_time_s,
                departure_delay_s=dep_delay,
                scheduled_arrival_s=scheduled_arr,
                actual_arrival_s=train.actual_completion_time_s,
                arrival_delay_s=arr_delay,
                primary_delay_s=train.primary_delay_s,
                secondary_delay_s=train.secondary_delay_s,
                recovered_time_s=max(0.0, (train.primary_delay_s + dep_delay) - arr_delay) if train.actual_completion_time_s else 0.0,
                breakdown_by_cause_s=delays_by_cause,
            )
            delay_summaries[train.train_id] = d_summary

            # Journey Time Decomposition (P09-JT)
            actual_jt = train.total_journey_time_s or unconstrained_jt
            actual_dwell = sum(st.dwell_time_s for st in train.stops) + train.accumulated_delay_by_cause.get("STATION_DWELL", 0.0)
            j_decomp = JourneyTimeAnalyzer.evaluate_journey_time(
                train_id=train.train_id,
                service_id=train.service_id,
                unconstrained_jt_s=unconstrained_jt,
                constrained_jt_s=actual_jt,
                planned_dwell_s=planned_dwell,
                actual_dwell_s=actual_dwell,
                delay_summary=d_summary,
            )
            journey_decompositions[train.train_id] = j_decomp

        # Compute Global Operational KPIs
        kpis = JourneyTimeAnalyzer.compute_kpis(
            requested_count=len(self.all_trains),
            dispatched_trains=[t.train_id for t in self.dispatched_trains],
            completed_trains=[t.train_id for t in self.completed_trains],
            delay_summaries=list(delay_summaries.values()),
            journey_decompositions=list(journey_decompositions.values()),
            total_tvs_wait_s=self.tvs_queue_tracker.get_total_waiting_time_s(),
            max_tvs_queue=self.tvs_queue_tracker.get_max_observed_queue_length(),
        )

        all_events = self.coordinator.get_all_events()
        all_boundary_events = []
        for t in self.all_trains:
            all_boundary_events.extend(t.events)

        return MultiTrainSimulationResult(
            train_instances=self.all_trains,
            trajectories=trajectories,
            time_distance_dataset=self.time_distance_dataset,
            events=all_events,
            boundary_events=all_boundary_events,
            delay_summaries=delay_summaries,
            journey_decompositions=journey_decompositions,
            kpis=kpis,
            deadlock_report=deadlock_report,
            starvation_warnings=self.origin_queue.starvation_warnings,
            completed_trains=list(self.completed_trains),
            dispatched_trains=list(self.dispatched_trains),
        )
