"""Speed profile calculation engine: forward traction, backward braking, and combined envelope.

Strictly satisfies RHS-P04-001 § 9, § 10, § 11 & § 12:
- P04-SPD-001 to 006: Permissible speed envelope v_limit(s) = min(v_infra(s), v_train).
- P04-SPD-007 to 011: Forward traction acceleration pass using P03 force balance.
- P04-SPD-012 to 016: Backward braking pass from downstream targets and speed drops.
- P04-SPD-017 to 020: Combined reference speed profile v*(s) without arbitrary delays.
"""

from dataclasses import dataclass
import math
from typing import Callable, List, Optional, Tuple

from headway.core.exceptions import SimulationError
from headway.infrastructure.alignment import RouteAlignmentProfile
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.infrastructure.speed import RouteSpeedProfile
from headway.rolling_stock.braking import BrakingCategory, BrakingModel
from headway.rolling_stock.force_balance import ForceBalanceEngine
from headway.rolling_stock.resistance import DistributedResistanceEngine
from headway.rolling_stock.traction import TractionModel, create_traction_model
from headway.rolling_stock.train import RollingStockParameters
from headway.simulation.targets import BrakingTarget, BrakingTargetType


@dataclass(frozen=True)
class SpeedProfilePoint:
    """Discrete spatial node along the route speed profile."""

    distance_m: float
    permissible_limit_ms: float
    forward_speed_ms: float
    backward_speed_ms: float
    target_speed_ms: float       # Governing combined speed v*(s) = min(fwd, bwd, limit)


class SpeedProfileEngine:
    """Computes spatial speed curves across a route using forward traction and backward braking."""

    def __init__(
        self,
        route: Route,
        params: RollingStockParameters,
        braking_model: BrakingModel,
        speed_profile: Optional[RouteSpeedProfile] = None,
        alignment_profile: Optional[RouteAlignmentProfile] = None,
        traction_model: Optional[TractionModel] = None,
        spatial_step_m: float = 2.0,
    ) -> None:
        self.route = route
        self.params = params
        self.braking_model = braking_model
        self.speed_profile = speed_profile or RouteSpeedProfile(route)
        self.alignment_profile = alignment_profile or RouteAlignmentProfile(route)
        self.traction_model = traction_model or create_traction_model(params)
        self.dist_resistance = DistributedResistanceEngine(params)
        self.force_engine = ForceBalanceEngine(params, self.traction_model)
        self.spatial_step_m = max(0.5, float(spatial_step_m))

    def get_permissible_speed_at(self, s: float) -> float:
        """P04-SPD-003: v_limit(s) = min(v_infra(s), v_train)."""
        if hasattr(self.speed_profile, "get_permissible_speed_at"):
            infra_limit = self.speed_profile.get_permissible_speed_at(s)
        elif hasattr(self.speed_profile, "get_max_speed_at"):
            infra_limit = self.speed_profile.get_max_speed_at(s)
        else:
            infra_limit = self.params.max_speed_ms
        return min(infra_limit, self.params.max_speed_ms)

    def calculate_forward_traction_leg(
        self,
        start_distance_m: float,
        end_distance_m: float,
        initial_speed_ms: float = 0.0,
    ) -> List[Tuple[float, float]]:
        """P04-SPD-007 to 011: Forward acceleration integration from start to end.

        Returns list of (distance_m, achievable_speed_ms).
        Uses kinematic energy relation: v_{i+1}^2 = v_i^2 + 2 * a * ds.
        """
        leg_len = end_distance_m - start_distance_m
        if leg_len <= 0:
            return [(start_distance_m, initial_speed_ms)]

        num_steps = max(2, int(math.ceil(leg_len / self.spatial_step_m)))
        ds = leg_len / num_steps

        results: List[Tuple[float, float]] = []
        cur_s = start_distance_m
        cur_v = initial_speed_ms
        results.append((cur_s, cur_v))

        for _ in range(num_steps):
            # Check maximum permissible limit at current location
            v_cap = self.get_permissible_speed_at(cur_s)
            cur_v = min(cur_v, v_cap)

            # Evaluate tractive and resistance forces
            res_eval = self.dist_resistance.evaluate(
                speed_ms=cur_v,
                front_position_m=cur_s,
                alignment=self.alignment_profile,
            )
            fb_eval = self.force_engine.evaluate_acceleration(
                speed_ms=cur_v,
                resistance=res_eval,
            )
            a = fb_eval.capped_acceleration_ms2

            # Accelerate over ds
            if a > 0:
                v_next_sq = (cur_v ** 2) + 2.0 * a * ds
                v_next = math.sqrt(max(0.0, v_next_sq))
            else:
                # Braking/decelerating due to steep grade
                v_next_sq = (cur_v ** 2) + 2.0 * a * ds
                v_next = math.sqrt(max(0.0, v_next_sq))

            cur_s += ds
            cur_v = min(v_next, self.get_permissible_speed_at(cur_s))
            results.append((cur_s, cur_v))

        return results

    def calculate_backward_braking_curve(
        self,
        target_distance_m: float,
        target_speed_ms: float,
        start_distance_m: float,
    ) -> List[Tuple[float, float]]:
        """P04-SPD-012 to 016: Backward integration from target_distance to start_distance.

        Returns list of (distance_m, max_approaching_speed_ms).
        Equation: v(s) = sqrt(v_target^2 + 2 * b * (s_target - s)).
        """
        leg_len = target_distance_m - start_distance_m
        if leg_len <= 0:
            return [(target_distance_m, target_speed_ms)]

        num_steps = max(2, int(math.ceil(leg_len / self.spatial_step_m)))
        ds = leg_len / num_steps

        # Use nominal service deceleration
        eval_brk = self.braking_model.evaluate_deceleration(target_speed_ms, category=BrakingCategory.OPERATIONAL_SERVICE)
        b = eval_brk.nominal_deceleration_ms2

        results: List[Tuple[float, float]] = []
        cur_s = target_distance_m
        cur_v = target_speed_ms
        results.append((cur_s, cur_v))

        for _ in range(num_steps):
            v_prev_sq = (cur_v ** 2) + 2.0 * b * ds
            cur_v = math.sqrt(v_prev_sq)
            cur_s -= ds
            # Cap by permissible speed
            cur_v = min(cur_v, self.get_permissible_speed_at(cur_s))
            results.append((cur_s, cur_v))

        results.reverse()
        return results

    def generate_combined_profile(
        self,
        targets: List[BrakingTarget],
    ) -> List[SpeedProfilePoint]:
        """P04-SPD-017 to 020: Generate unified spatial speed profile for the entire route."""
        total_len = self.route.total_length_m
        num_nodes = max(10, int(math.ceil(total_len / self.spatial_step_m)))
        ds = total_len / num_nodes

        grid_s = [i * ds for i in range(num_nodes + 1)]
        grid_s[-1] = total_len

        # 1. Permissible envelope
        v_limits = [self.get_permissible_speed_at(s) for s in grid_s]

        # 2. Identify stopping targets (v = 0) that partition the route into journey legs
        stopping_s = [0.0]
        for t in targets:
            if t.target_speed_ms == 0.0:
                pos = min(total_len, t.effective_target_position_m)
                if pos > stopping_s[-1] + 1e-3:
                    stopping_s.append(pos)
        if stopping_s[-1] < total_len - 1e-3:
            stopping_s.append(total_len)

        # 3. Forward pass by legs (departing each stop from v = 0)
        v_fwd = [0.0] * len(grid_s)
        for i in range(len(stopping_s) - 1):
            leg_start = stopping_s[i]
            leg_end = stopping_s[i + 1]
            leg_fwd = self.calculate_forward_traction_leg(leg_start, leg_end, initial_speed_ms=0.0)

            # Sample leg_fwd onto grid_s
            fwd_dict = dict(leg_fwd)
            leg_keys = sorted(fwd_dict.keys())

            def interp_fwd(s_val: float) -> float:
                if s_val <= leg_keys[0]:
                    return fwd_dict[leg_keys[0]]
                if s_val >= leg_keys[-1]:
                    return fwd_dict[leg_keys[-1]]
                for k in range(len(leg_keys) - 1):
                    s0 = leg_keys[k]
                    s1 = leg_keys[k + 1]
                    if s0 <= s_val <= s1:
                        frac = (s_val - s0) / (s1 - s0)
                        return fwd_dict[s0] + frac * (fwd_dict[s1] - fwd_dict[s0])
                return fwd_dict[leg_keys[-1]]

            for idx, s in enumerate(grid_s):
                if leg_start <= s <= leg_end:
                    v_fwd[idx] = interp_fwd(s)

        # 4. Backward passes for all targets
        v_bwd_all = [float("inf")] * len(grid_s)
        for t in targets:
            t_pos = min(total_len, t.effective_target_position_m)
            bwd_curve = self.calculate_backward_braking_curve(
                target_distance_m=t_pos,
                target_speed_ms=t.target_speed_ms,
                start_distance_m=0.0,
            )
            bwd_dict = dict(bwd_curve)
            bwd_keys = sorted(bwd_dict.keys())

            def interp_bwd(s_val: float) -> float:
                if s_val >= bwd_keys[-1]:
                    return bwd_dict[bwd_keys[-1]]
                if s_val <= bwd_keys[0]:
                    return bwd_dict[bwd_keys[0]]
                for k in range(len(bwd_keys) - 1):
                    s0 = bwd_keys[k]
                    s1 = bwd_keys[k + 1]
                    if s0 <= s_val <= s1:
                        frac = (s_val - s0) / (s1 - s0)
                        return bwd_dict[s0] + frac * (bwd_dict[s1] - bwd_dict[s0])
                return bwd_dict[bwd_keys[-1]]

            for idx, s in enumerate(grid_s):
                if s <= t_pos:
                    v_bwd_all[idx] = min(v_bwd_all[idx], interp_bwd(s))

        # 5. Combined speed profile: v*(s) = min(v_fwd, v_bwd, v_limit)
        profile_points: List[SpeedProfilePoint] = []
        for idx in range(len(grid_s)):
            s = grid_s[idx]
            v_lim = v_limits[idx]
            v_f = v_fwd[idx]
            v_b = v_bwd_all[idx] if v_bwd_all[idx] != float("inf") else v_lim
            v_opt = max(0.0, min(v_f, v_b, v_lim))

            profile_points.append(
                SpeedProfilePoint(
                    distance_m=round(s, 2),
                    permissible_limit_ms=round(v_lim, 3),
                    forward_speed_ms=round(v_f, 3),
                    backward_speed_ms=round(v_b, 3),
                    target_speed_ms=round(v_opt, 3),
                )
            )

        return profile_points
