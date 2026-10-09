"""Microscopic numerical integration and trajectory simulator.

Strictly satisfies RHS-P04-001 § 13, § 14, § 16 & § 17:
- P04-NUM-001 to 007: Deterministic fixed-step numerical integration (dt = 0.1s standard),
  step subdivision, zero-speed non-reversal, boundary event localization.
- P04-POS-001 to 006: Continuous train-front and train-rear position tracking.
- P04-STP-001 to 007: Accurate station stopping, dwell, and departure acceleration.
- P04-JT-001 to 005: Unconstrained moving time, dwell time, and total journey time.
"""

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Tuple

from headway.core.exceptions import SimulationError
from headway.infrastructure.alignment import RouteAlignmentProfile
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.infrastructure.speed import RouteSpeedProfile
from headway.infrastructure.stations import RoutePlatformStop
from headway.infrastructure.tunnels import TunnelTVSModel
from headway.rolling_stock.braking import BrakingCategory, BrakingModel, create_braking_model
from headway.rolling_stock.force_balance import ForceBalanceEngine, MotionState
from headway.rolling_stock.resistance import DistributedResistanceEngine
from headway.rolling_stock.traction import TractionModel, create_traction_model
from headway.rolling_stock.train import RollingStockParameters
from headway.simulation.events import BoundaryEvent, BoundaryEventDetector, CrossingEventType
from headway.simulation.speed_profile import SpeedProfileEngine, SpeedProfilePoint
from headway.simulation.state import DynamicMode, OperationalState, TrainDynamicState
from headway.simulation.targets import BrakingTarget, BrakingTargetResolver, BrakingTargetType
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory


class MicroscopicSimulator:
    """Executes deterministic microscopic train dynamics simulation along a route."""

    def __init__(
        self,
        route: Route,
        params: RollingStockParameters,
        braking_model: Optional[BrakingModel] = None,
        traction_model: Optional[TractionModel] = None,
        speed_profile: Optional[RouteSpeedProfile] = None,
        alignment_profile: Optional[RouteAlignmentProfile] = None,
        station_views: Optional[List[RoutePlatformStop]] = None,
        tvs_models: Optional[List[TunnelTVSModel]] = None,
        dt_s: float = 0.1,
    ) -> None:
        self.route = route
        self.params = params
        self.braking_model = braking_model or create_braking_model(params)
        self.traction_model = traction_model or create_traction_model(params)
        self.speed_profile = speed_profile or RouteSpeedProfile(route)
        self.alignment_profile = alignment_profile or RouteAlignmentProfile(route)
        self.station_views = station_views or []
        self.tvs_models = tvs_models or []
        self.dt_s = max(0.01, float(dt_s))

        self.dist_resistance = DistributedResistanceEngine(params)
        self.force_engine = ForceBalanceEngine(params, self.traction_model)
        self.speed_profile_engine = SpeedProfileEngine(
            route=route,
            params=params,
            braking_model=self.braking_model,
            speed_profile=self.speed_profile,
            alignment_profile=self.alignment_profile,
            traction_model=self.traction_model,
            spatial_step_m=2.0,
        )
        self.event_detector = BoundaryEventDetector(
            route=route,
            train_id=params.train_type_id,
            train_length_m=params.length_m,
            tvs_models=self.tvs_models,
        )

    def simulate(
        self,
        train_id: Optional[str] = None,
        initial_speed_ms: float = 0.0,
        initial_position_m: float = 0.0,
        max_duration_s: float = 3600.0,
        default_dwell_time_s: float = 30.0,
        storage_interval_s: Optional[float] = None,
    ) -> TrainTrajectory:
        """P04-NUM-001 to P04-NUM-007: Microscopic time-stepping simulation."""
        tid = train_id or f"TRN_{self.params.train_type_id}"
        route_len = self.route.total_length_m
        dt = self.dt_s
        sample_step = storage_interval_s if storage_interval_s and storage_interval_s >= dt else dt

        # 1. Resolve all downstream braking targets (stations, speed drops, route end)
        targets = BrakingTargetResolver.resolve_targets(
            route=self.route,
            speed_profile=self.speed_profile,
            station_views=self.station_views,
            mandatory_route_end_stop=True,
            default_dwell_time_s=default_dwell_time_s,
        )

        primary_dir = self.route.traversals[0].direction if self.route.traversals else RunningDirection.FORWARD
        trajectory = TrainTrajectory(
            train_id=tid,
            train_type_id=self.params.train_type_id,
            route_id=self.route.route_id,
            running_direction=primary_dir,
        )

        # Active targets queue
        active_targets = list(sorted(targets, key=lambda t: t.effective_target_position_m))

        def get_permissible_speed(s_pos: float) -> float:
            if hasattr(self.speed_profile, "get_permissible_speed_at"):
                infra_limit = self.speed_profile.get_permissible_speed_at(s_pos)
            elif hasattr(self.speed_profile, "get_max_speed_at"):
                infra_limit = self.speed_profile.get_max_speed_at(s_pos)
            else:
                infra_limit = self.params.max_speed_ms
            return min(infra_limit, self.params.max_speed_ms)

        def record_sample(t_sim: float, s_pos: float, v_spd: float, a_acc: float, fb_res, mode: DynamicMode, op: OperationalState):
            try:
                traversal = self.route.get_traversal_at_distance(min(route_len, max(0.0, s_pos)))
                lid = traversal.link_id
                coord = traversal.route_distance_to_physical_offset(min(route_len, max(0.0, s_pos)))
            except Exception:
                lid = None
                coord = None
            s_rear = s_pos - self.params.length_m

            trajectory.samples.append(
                TrajectorySample(
                    time_s=round(t_sim, 4),
                    front_distance_m=round(s_pos, 3),
                    rear_distance_m=round(s_rear, 3),
                    speed_ms=round(v_spd, 4),
                    acceleration_ms2=round(a_acc, 4),
                    traction_force_n=round(fb_res.tractive_force_n, 1) if fb_res else 0.0,
                    braking_force_n=round(fb_res.braking_force_n, 1) if fb_res else 0.0,
                    davis_resistance_n=round(fb_res.davis_resistance_n, 1) if fb_res else 0.0,
                    gradient_resistance_n=round(fb_res.gradient_resistance_n, 1) if fb_res else 0.0,
                    curvature_resistance_n=round(fb_res.curvature_resistance_n, 1) if fb_res else 0.0,
                    net_force_n=round(fb_res.net_force_n, 1) if fb_res else 0.0,
                    dynamic_mode=mode,
                    operational_state=op,
                    link_id=lid,
                    physical_coordinate_m=round(coord, 2) if coord is not None else None,
                )
            )

        cur_t = 0.0
        cur_s = initial_position_m
        cur_v = initial_speed_ms
        cur_mode = DynamicMode.STOPPED if cur_v == 0.0 else DynamicMode.ACCELERATING
        cur_op = OperationalState.STANDSTILL if cur_v == 0.0 else OperationalState.RUNNING

        # Station dwell state
        dwelling_target: Optional[BrakingTarget] = None
        remaining_dwell_s: float = 0.0
        last_sample_t = -1e9

        while cur_t <= max_duration_s + 1e-6:
            # 1. Handle station dwell state machine
            if dwelling_target is not None:
                cur_mode = DynamicMode.DWELLING
                cur_op = OperationalState.STATION_DWELL
                cur_v = 0.0
                cur_a = 0.0

                if remaining_dwell_s > 0:
                    step_dt = min(dt, remaining_dwell_s)
                    if cur_t - last_sample_t >= sample_step - 1e-6:
                        record_sample(cur_t, cur_s, 0.0, 0.0, None, cur_mode, cur_op)
                        last_sample_t = cur_t
                    cur_t += step_dt
                    remaining_dwell_s -= step_dt
                    continue
                else:
                    # Dwell complete, emit departure event and resume
                    stn_id = dwelling_target.station_id or "STN"
                    trajectory.events.append(
                        BoundaryEvent(
                            event_type=CrossingEventType.STATION_DEPARTED,
                            timestamp_s=round(cur_t, 4),
                            route_distance_m=round(cur_s, 2),
                            train_id=tid,
                            is_front=True,
                            speed_ms=0.0,
                            description=f"Departed station {stn_id} at {cur_s:.1f}m",
                        )
                    )
                    # Remove from active targets
                    if dwelling_target in active_targets:
                        active_targets.remove(dwelling_target)
                    dwelling_target = None
                    cur_mode = DynamicMode.ACCELERATING
                    cur_op = OperationalState.RUNNING

            # 2. Check route completion
            if cur_s >= route_len - 0.2 and cur_v < 0.05:
                cur_mode = DynamicMode.STOPPED
                cur_op = OperationalState.COMPLETED
                record_sample(cur_t, route_len, 0.0, 0.0, None, cur_mode, cur_op)
                break

            # 3. Clean up past targets
            active_targets = [t for t in active_targets if t.effective_target_position_m > cur_s - 0.2]

            # 4. Check if arriving at a stop target (station or route end)
            arrived_at_stop = False
            for t in list(active_targets):
                if t.target_speed_ms == 0.0 and abs(cur_s - t.effective_target_position_m) <= 0.5 and cur_v < 0.5:
                    cur_s = t.effective_target_position_m
                    cur_v = 0.0
                    cur_a = 0.0
                    if t.target_type == BrakingTargetType.STATION_STOP and t.dwell_time_s > 0:
                        dwelling_target = t
                        remaining_dwell_s = t.dwell_time_s
                        cur_mode = DynamicMode.DWELLING
                        cur_op = OperationalState.STATION_DWELL
                        stn_id = t.station_id or "STN"
                        trajectory.events.append(
                            BoundaryEvent(
                                event_type=CrossingEventType.STATION_ARRIVED,
                                timestamp_s=round(cur_t, 4),
                                route_distance_m=round(cur_s, 2),
                                train_id=tid,
                                is_front=True,
                                speed_ms=0.0,
                                description=f"Arrived at station {stn_id} at {cur_s:.1f}m",
                            )
                        )
                    else:
                        cur_mode = DynamicMode.STOPPED
                        cur_op = OperationalState.COMPLETED
                        active_targets.remove(t)
                    arrived_at_stop = True
                    break

            if arrived_at_stop:
                record_sample(cur_t, cur_s, 0.0, 0.0, None, cur_mode, cur_op)
                last_sample_t = cur_t
                if dwelling_target is None and cur_s >= route_len - 0.5:
                    break
                continue

            # 5. Evaluate speed limits and braking constraints
            v_limit = get_permissible_speed(cur_s)

            # Find governing braking curve speed among active targets
            v_brake_limit = float("inf")
            for t in active_targets:
                dist_to_target = t.effective_target_position_m - cur_s
                if dist_to_target > 0:
                    req_b = self.params.max_service_deceleration_ms2
                    max_allowed_sq = (t.target_speed_ms ** 2) + 2.0 * req_b * dist_to_target
                    max_allowed = math.sqrt(max(0.0, max_allowed_sq))
                    if max_allowed < v_brake_limit:
                        v_brake_limit = max_allowed

            # Resistances at current position
            res_eval = self.dist_resistance.evaluate(
                speed_ms=cur_v,
                front_position_m=cur_s,
                alignment=self.alignment_profile,
            )

            # Determine dynamic mode
            target_dec = None
            is_coast = False
            tract_n = None

            if cur_v >= v_brake_limit - 0.05:
                # Braking needed for downstream target
                cur_mode = DynamicMode.SERVICE_BRAKING
                cur_op = OperationalState.RUNNING
                target_dec = self.params.max_service_deceleration_ms2
            elif cur_v >= v_limit - 0.05:
                # Cruising at permissible speed limit
                cur_mode = DynamicMode.CRUISING
                cur_op = OperationalState.RUNNING
                tract_n = max(0.0, res_eval.total_resistance_n)
            else:
                # Accelerating
                cur_mode = DynamicMode.ACCELERATING
                cur_op = OperationalState.RUNNING

            fb_res = self.force_engine.evaluate_acceleration(
                speed_ms=cur_v,
                resistance=res_eval,
                tractive_force_n=tract_n,
                target_deceleration_ms2=target_dec,
                is_coasting=is_coast,
            )
            a = fb_res.capped_acceleration_ms2

            # Numerical integration step
            step_dt = dt
            if a < 0 and cur_v + a * dt < 0:
                t_stop = -cur_v / a if abs(a) > 1e-6 else 0.0
                step_dt = max(1e-4, t_stop)
                s_next = cur_s + cur_v * step_dt + 0.5 * a * (step_dt ** 2)
                v_next = 0.0
            else:
                s_next = cur_s + cur_v * step_dt + 0.5 * a * (step_dt ** 2)
                v_next = max(0.0, cur_v + a * step_dt)

            # P04-NUM-006: Step subdivision for stop targets (stations or route end)
            for t in active_targets:
                if t.target_speed_ms == 0.0 and cur_s < t.effective_target_position_m:
                    if s_next >= t.effective_target_position_m:
                        ds = t.effective_target_position_m - cur_s
                        if cur_v > 1e-4:
                            step_dt = (2.0 * ds) / cur_v
                            a = - (cur_v ** 2) / (2.0 * ds)
                        else:
                            step_dt = 1e-4
                            a = 0.0
                        s_next = t.effective_target_position_m
                        v_next = 0.0
                        break

            if s_next > route_len:
                s_next = route_len
                v_next = 0.0

            # Detect geometric boundary events during this step
            cross_events = self.event_detector.detect_crossings(
                t0=cur_t,
                t1=cur_t + step_dt,
                s_front0=cur_s,
                s_front1=s_next,
                v0=cur_v,
                v1=v_next,
            )
            trajectory.events.extend(cross_events)

            # Record sample
            if cur_t - last_sample_t >= sample_step - 1e-6:
                record_sample(cur_t, cur_s, cur_v, a, fb_res, cur_mode, cur_op)
                last_sample_t = cur_t

            # Advance
            cur_t += step_dt
            cur_s = s_next
            cur_v = v_next

        return trajectory
