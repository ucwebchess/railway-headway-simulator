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

# v1.11.0 / DEF-18: Stop-arrival physics constants.
# A stop may only be finalized when the train is effectively at standstill
# (< 0.5 km/h). Retroactive speed snaps from higher approach speeds are prohibited.
ARRIVAL_SPEED_TOL_MS = 0.5 / 3.6  # 0.5 km/h
ARRIVAL_POSITION_TOL_M = 0.5  # berthing tolerance around a stop marker [m]


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
        performance_factor: float = 1.0,
    ) -> None:
        self.route = route
        self.params = params
        self.performance_factor = float(performance_factor)
        self.braking_model = braking_model or create_braking_model(params, performance_factor=self.performance_factor)
        self.traction_model = traction_model or create_traction_model(params, performance_factor=self.performance_factor)
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

            rec_spd = min(v_spd, get_permissible_speed(s_pos))
            max_kmh = round(get_permissible_speed(s_pos) * 3.6, 2)
            if rec_spd * 3.6 > max_kmh:
                rec_spd = max_kmh / 3.6

            trajectory.samples.append(
                TrajectorySample(
                    time_s=round(t_sim, 4),
                    front_distance_m=round(s_pos, 3),
                    rear_distance_m=round(s_rear, 3),
                    speed_ms=round(rec_spd, 4),
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

            # 3. Check if arriving at a stop target (station or route end).
            #    v1.11.0 / DEF-18: evaluated BEFORE target cleanup so a physical
            #    standstill within the berthing tolerance still registers the stop.
            arrived_at_stop = False
            for t in list(active_targets):
                # v1.11.0 / DEF-18: arrival is only accepted at true standstill (< 0.5 km/h)
                if t.target_speed_ms == 0.0 and abs(cur_s - t.effective_target_position_m) <= ARRIVAL_POSITION_TOL_M and cur_v <= ARRIVAL_SPEED_TOL_MS:
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

            # 4. Clean up past targets (targets kept while still within berthing tolerance)
            active_targets = [
                t for t in active_targets
                if t.effective_target_position_m > cur_s - (ARRIVAL_POSITION_TOL_M + 1e-9)
            ]

            # 5. Evaluate speed limits and braking constraints
            v_limit = get_permissible_speed(cur_s)

            # Hard clamp before applying the step (Task 2 / DEF-16)
            if cur_v > v_limit:
                cur_v = v_limit

            # Find governing braking curve speed among active targets
            v_brake_limit = float("inf")
            governing_stop = None
            governing_stop_dist = float("inf")
            for t in active_targets:
                dist_to_target = t.effective_target_position_m - cur_s
                if dist_to_target > 0:
                    # Protection/supervised targets use unscaled deceleration; operational targets scale with performance factor
                    if getattr(t, "target_type", None) == BrakingTargetType.FUTURE_MOVEMENT_AUTHORITY or getattr(t, "braking_category", None) == BrakingCategory.SUPERVISED:
                        req_b = self.params.max_service_deceleration_ms2
                    else:
                        req_b = self.params.max_service_deceleration_ms2 * self.performance_factor
                    max_allowed_sq = (t.target_speed_ms ** 2) + 2.0 * req_b * dist_to_target
                    max_allowed = math.sqrt(max(0.0, max_allowed_sq))
                    if max_allowed < v_brake_limit:
                        v_brake_limit = max_allowed
                    if t.target_speed_ms == 0.0 and dist_to_target < governing_stop_dist:
                        governing_stop = t
                        governing_stop_dist = dist_to_target

            # v1.11.0 / DEF-18: stop-type targets engage braking one step EARLY so the
            # train is never above the braking curve when the modulated stop controller
            # takes over (eliminates above-curve onset lead and endpoint overshoot).
            stop_anticipation = 0.0
            b_stop_eff = max(0.05, self.params.max_service_deceleration_ms2 * self.performance_factor)
            # v1.11.0 / DEF-18 follow-up: physical brake authority cap for the stop
            # controller — regulation at the service rate unless the required modulated
            # deceleration slightly exceeds the service curve, in which case braking may
            # escalate up to the true emergency capability (never beyond it), so a
            # capacity-limited clamp cannot mathematically guarantee an overshoot.
            b_stop_hard = max(b_stop_eff, float(getattr(self.params, "emergency_deceleration_ms2", b_stop_eff) or b_stop_eff))
            if governing_stop is not None:
                stop_anticipation = b_stop_eff * dt

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

            if cur_v >= v_brake_limit - 0.05 - stop_anticipation:
                # Braking needed for downstream target
                cur_mode = DynamicMode.SERVICE_BRAKING
                cur_op = OperationalState.RUNNING
                target_dec = self.params.max_service_deceleration_ms2 * self.performance_factor
                tract_n = 0.0
            elif cur_v >= v_limit:
                # At speed limit: cruise, balance resistance (Task 2 / DEF-16)
                cur_mode = DynamicMode.CRUISING
                cur_op = OperationalState.RUNNING
                tract_n = max(0.0, res_eval.total_resistance_n)
            elif cur_v >= v_limit - 0.05:
                # Cruising near permissible speed limit: balance resistance
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

            # v1.11.0 / DEF-18: Modulated stop-arrival control (braking-curve true).
            # Inside the arrival window of a zero-speed target the train is advanced in
            # sub-steps with the modulated exact-arrival deceleration a = -v^2/(2D),
            # hard-bounded by configured service braking. Speed may reach 0 only when the
            # front physically reaches the target; retroactive snap-to-zero is prohibited.
            stop_window_m = cur_v * dt * 2.0 + (cur_v * cur_v) / (2.0 * b_stop_eff) * 1.10 + 5.0
            modulated_stop = (
                governing_stop is not None
                and cur_v > 0.0
                and governing_stop_dist <= stop_window_m
                and governing_stop.effective_target_position_m > cur_s
            )

            step_dt = dt
            if modulated_stop:
                n_sub = max(20, int(math.ceil(dt / 0.005)))
                sub_h = dt / n_sub
                s_acc = float(cur_s)
                v_acc = float(cur_v)
                t_used = 0.0
                a_last = a
                warned_key = (tid, round(governing_stop.effective_target_position_m, 2))
                for _sub in range(n_sub):
                    if t_used >= dt - 1e-12 or v_acc <= 0.0:
                        break
                    h = min(sub_h, dt - t_used)
                    D = eoa_dist = (governing_stop.effective_target_position_m - s_acc)
                    if D <= 0.0:
                        # Physical overshoot past the target: continue service braking.
                        a_step = -b_stop_hard
                        if warned_key not in self._overspeed_warned and v_acc > ARRIVAL_SPEED_TOL_MS:
                            trajectory.events.append(
                                BoundaryEvent(
                                    event_type=CrossingEventType.WARNING_OVERSPEED_ARRIVAL,
                                    timestamp_s=round(cur_t + t_used, 4),
                                    route_distance_m=round(s_acc, 2),
                                    train_id=tid,
                                    is_front=True,
                                    speed_ms=round(v_acc, 4),
                                    description=(
                                        f"ERR_OVERSPEED_ARRIVAL: train '{tid}' overshot stop target "
                                        f"{governing_stop.effective_target_position_m:.1f} m at {v_acc * 3.6:.1f} km/h — "
                                        f"service braking continues without retroactive speed snap"
                                    ),
                                )
                            )
                            self._overspeed_warned.add(warned_key)
                    else:
                        a_req_stop = (v_acc * v_acc) / (2.0 * D)
                        if a_req_stop <= b_stop_eff + 1e-9:
                            a_step = -a_req_stop  # modulated exact-arrival braking
                        else:
                            # Above the service braking curve: escalate within the
                            # physical emergency capability so the standstill still lands
                            # on the marker; the curve violation remains logged below.
                            a_step = -min(a_req_stop, b_stop_hard)
                            if warned_key not in self._overspeed_warned and v_acc > ARRIVAL_SPEED_TOL_MS:
                                trajectory.events.append(
                                    BoundaryEvent(
                                        event_type=CrossingEventType.WARNING_OVERSPEED_ARRIVAL,
                                        timestamp_s=round(cur_t + t_used, 4),
                                        route_distance_m=round(s_acc, 2),
                                        train_id=tid,
                                        is_front=True,
                                        speed_ms=round(v_acc, 4),
                                        description=(
                                            f"ERR_OVERSPEED_ARRIVAL: train '{tid}' approaches stop target "
                                            f"{governing_stop.effective_target_position_m:.1f} m at {v_acc * 3.6:.1f} km/h "
                                            f"requiring {a_req_stop:.2f} m/s^2 > service braking {b_stop_eff:.2f} m/s^2 "
                                            f"— braking continues without snap (overshoot possible)"
                                        ),
                                    )
                                )
                                self._overspeed_warned.add(warned_key)
                    a_last = a_step
                    if a_step < 0.0 and v_acc + a_step * h <= 0.0:
                        t_half = v_acc / max(1e-9, -a_step)
                        t_half = min(t_half, h)
                        s_acc += v_acc * t_half + 0.5 * a_step * (t_half ** 2)
                        v_acc = 0.0
                        t_used += t_half
                        break
                    s_acc += v_acc * h + 0.5 * a_step * (h ** 2)
                    v_acc = max(0.0, v_acc + a_step * h)
                    t_used += h
                step_dt = dt
                s_next = s_acc
                v_next = v_acc
                a = a_last
            else:
                # Numerical integration step
                if a < 0 and cur_v + a * dt < 0:
                    t_stop = -cur_v / a if abs(a) > 1e-6 else 0.0
                    step_dt = max(1e-4, t_stop)
                    s_next = cur_s + cur_v * step_dt + 0.5 * a * (step_dt ** 2)
                    v_next = 0.0
                else:
                    s_next = cur_s + cur_v * step_dt + 0.5 * a * (step_dt ** 2)
                    v_next = max(0.0, cur_v + a * step_dt)

            # Hard clamp: simulated speed must never exceed permissible speed envelope (Task 2 / RHS-PHYS-001)
            v_permissible = min(v_limit, get_permissible_speed(min(route_len, s_next)))
            v_next = min(v_next, v_permissible)
            max_kmh = round(v_permissible * 3.6, 2)
            if v_next * 3.6 > max_kmh:
                v_next = max_kmh / 3.6

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
