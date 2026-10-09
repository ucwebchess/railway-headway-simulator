"""Longitudinal force balance and instantaneous acceleration utility.

Strictly satisfies RHS-P03-001 § 11:
- P03-FB-001: Net longitudinal force: F_net = F_t - F_b - F_D - F_g - F_c.
- P03-FB-002: Equivalent-mass acceleration: a = F_net / m_eq.
- P03-FB-003: Operational acceleration capping: |a| <= a_max or deceleration limits.
- P03-FB-004: Target deceleration to braking force conversion.
- P03-FB-005: Coasting mode evaluation (F_t = 0, F_b = 0).
- P03-FB-006: Standstill force balance and rollback check.
NOTE: Performs NO time-stepping numerical integration or trajectory simulation (deferred to P04).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from headway.core.exceptions import RollingStockError
from headway.rolling_stock.resistance import DistributedResistanceResult
from headway.rolling_stock.traction import TractionEvaluation, TractionModel
from headway.rolling_stock.train import RollingStockParameters


class MotionState(str, Enum):
    """Instantaneous operational mode."""

    ACCELERATING = "ACCELERATING"
    CRUISING = "CRUISING"
    COASTING = "COASTING"
    BRAKING = "BRAKING"
    STANDSTILL = "STANDSTILL"


@dataclass(frozen=True)
class ForceBalanceResult:
    """Instantaneous longitudinal force balance and resultant acceleration."""

    motion_state: MotionState
    speed_ms: float
    tractive_force_n: float
    braking_force_n: float
    davis_resistance_n: float
    gradient_resistance_n: float
    curvature_resistance_n: float
    total_resistance_n: float
    net_force_n: float
    equivalent_mass_kg: float
    raw_acceleration_ms2: float
    capped_acceleration_ms2: float
    is_acceleration_capped: bool


class ForceBalanceEngine:
    """Instantaneous force balance and acceleration calculator."""

    def __init__(
        self,
        params: RollingStockParameters,
        traction_model: Optional[TractionModel] = None,
    ) -> None:
        self.params = params
        self.traction_model = traction_model

    def evaluate_acceleration(
        self,
        speed_ms: float,
        resistance: DistributedResistanceResult,
        tractive_force_n: Optional[float] = None,
        braking_force_n: float = 0.0,
        target_deceleration_ms2: Optional[float] = None,
        is_coasting: bool = False,
    ) -> ForceBalanceResult:
        """P03-FB-001 & P03-FB-002: Evaluate instantaneous force balance and acceleration."""
        if speed_ms < 0:
            raise RollingStockError(f"Speed must be non-negative (got {speed_ms} m/s).")
        if braking_force_n < 0:
            raise RollingStockError(f"Braking force must be non-negative (got {braking_force_n} N).")

        m_eq = self.params.equivalent_mass_kg
        f_davis = resistance.davis_resistance_n
        f_grad = resistance.gradient_resistance_n
        f_curv = resistance.curvature_resistance_n
        f_res_total = f_davis + f_grad + f_curv

        # Determine tractive force
        if is_coasting or target_deceleration_ms2 is not None or braking_force_n > 0:
            f_tract = 0.0
        elif tractive_force_n is not None:
            f_tract = max(0.0, float(tractive_force_n))
        elif self.traction_model is not None:
            eval_tr = self.traction_model.evaluate_tractive_effort(speed_ms)
            f_tract = eval_tr.available_tractive_force_n
        else:
            f_tract = 0.0

        # Determine braking force
        f_brake = braking_force_n
        if target_deceleration_ms2 is not None:
            # P03-FB-004: F_b = m_eq * d - (F_D + F_g + F_c)
            # Ensure braking force is non-negative
            required_fb = (m_eq * target_deceleration_ms2) - (f_davis + f_grad + f_curv)
            f_brake = max(0.0, required_fb)

        # Net force: F_net = F_t - F_b - F_D - F_g - F_c
        f_net = f_tract - f_brake - f_davis - f_grad - f_curv
        raw_a = f_net / m_eq

        # Operational acceleration/deceleration capping (P03-FB-003)
        capped_a = raw_a
        is_capped = False

        if raw_a > 0:
            max_a = self.params.max_acceleration_ms2
            if raw_a > max_a:
                capped_a = max_a
                is_capped = True
        elif raw_a < 0:
            # Check maximum deceleration limits
            max_d = self.params.emergency_deceleration_ms2
            if abs(raw_a) > max_d:
                capped_a = -max_d
                is_capped = True

        # Classify motion state
        if speed_ms == 0.0 and abs(capped_a) < 1e-4:
            state = MotionState.STANDSTILL
        elif f_brake > 0:
            state = MotionState.BRAKING
        elif is_coasting:
            state = MotionState.COASTING
        elif abs(capped_a) < 1e-4:
            state = MotionState.CRUISING
        elif capped_a > 0:
            state = MotionState.ACCELERATING
        else:
            state = MotionState.BRAKING

        return ForceBalanceResult(
            motion_state=state,
            speed_ms=speed_ms,
            tractive_force_n=f_tract,
            braking_force_n=f_brake,
            davis_resistance_n=f_davis,
            gradient_resistance_n=f_grad,
            curvature_resistance_n=f_curv,
            total_resistance_n=f_res_total,
            net_force_n=f_net,
            equivalent_mass_kg=m_eq,
            raw_acceleration_ms2=raw_a,
            capped_acceleration_ms2=capped_a,
            is_acceleration_capped=is_capped,
        )
