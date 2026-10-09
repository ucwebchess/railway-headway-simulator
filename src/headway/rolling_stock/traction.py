"""Traction and adhesion models for rolling stock.

Strictly satisfies RHS-P03-001 § 5 & § 6:
- P03-TR-001: Simplified traction: F_t(v) = min(F_max, P_max / v), F_t(0) = F_max.
- P03-TR-002: Detailed traction curves: piecewise linear interpolation.
- P03-TR-003: Validation of traction curves: strictly increasing non-negative speeds, non-negative forces.
- P03-TR-004: Traction curve range checking with explicit boundary policy (clamp to zero above v_max).
- P03-TR-005: Operational acceleration limitation: F_t <= m_eq * a_max.
- P03-TR-006: Traction efficiency: F_t * eta.
- P03-TR-007: Mechanical traction power verification: P = F_t * v <= P_max.
- P03-ADH-001: Adhesion limit: F_adh = mu * m_adh * g.
- P03-ADH-002: Explicit adhesive mass: m_adh = alpha_adh * m.
- P03-ADH-003: Configurable adhesion limitation: reports when adhesion limit is active/evaluated.
- P03-ADH-004: Direction invariance: identical in forward and reverse.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

from headway.core.exceptions import RollingStockError
from headway.core.units import GRAVITY_ACCELERATION_MS2
from headway.data.canonical import TractionCurvePoint, TractionModelType
from headway.rolling_stock.train import RollingStockParameters


@dataclass(frozen=True)
class TractionEvaluation:
    """Detailed result of traction force evaluation."""

    speed_ms: float
    raw_tractive_force_n: float       # Model-computed tractive effort before limits
    acceleration_limit_force_n: float # m_eq * a_max
    adhesion_limit_force_n: Optional[float]  # mu * m_adh * g (if adhesion evaluated)
    available_tractive_force_n: float # Final available force after applying all limits
    mechanical_power_w: float         # F_avail * v
    adhesion_evaluated: bool
    is_acceleration_limited: bool
    is_adhesion_limited: bool


class TractionModel(ABC):
    """Abstract base class for rolling stock traction models."""

    @abstractmethod
    def evaluate_tractive_effort(
        self,
        speed_ms: float,
        apply_acceleration_limit: bool = True,
        apply_adhesion_limit: bool = True,
    ) -> TractionEvaluation:
        """Evaluate available tractive effort at a given non-negative speed."""
        pass


class SimplifiedTractionModel(TractionModel):
    """Simplified hyperbolic traction model: F_t(v) = min(F_max, P_max / v).

    At standstill (v = 0), F_t(0) = F_max without division by zero.
    """

    def __init__(
        self,
        params: RollingStockParameters,
        efficiency: float = 1.0,
    ) -> None:
        if params.max_tractive_effort_n is None or params.max_tractive_effort_n <= 0:
            raise RollingStockError(
                f"Simplified traction model requires positive max_tractive_effort_n "
                f"(got {params.max_tractive_effort_n}).",
                context={"train_type_id": params.train_type_id},
            )
        if params.power_w is None or params.power_w <= 0:
            raise RollingStockError(
                f"Simplified traction model requires positive power_w (got {params.power_w}).",
                context={"train_type_id": params.train_type_id},
            )
        if not (0.0 < efficiency <= 1.0):
            raise RollingStockError(
                f"Traction efficiency must be in (0, 1] (got {efficiency}).",
                context={"train_type_id": params.train_type_id},
            )

        self.params = params
        self.max_tractive_effort_n = float(params.max_tractive_effort_n)
        self.power_w = float(params.power_w)
        self.efficiency = float(efficiency)

    def evaluate_tractive_effort(
        self,
        speed_ms: float,
        apply_acceleration_limit: bool = True,
        apply_adhesion_limit: bool = True,
    ) -> TractionEvaluation:
        if speed_ms < 0:
            raise RollingStockError(
                f"Traction evaluation requires non-negative speed (got {speed_ms} m/s)."
            )

        # Raw tractive force computation
        if speed_ms == 0.0:
            raw_force = self.max_tractive_effort_n * self.efficiency
        else:
            hyperbolic_force = (self.power_w / speed_ms) * self.efficiency
            raw_force = min(self.max_tractive_effort_n * self.efficiency, hyperbolic_force)

        # Operational acceleration limit: F_acc = m_eq * a_max
        acc_limit_force = self.params.equivalent_mass_kg * self.params.max_acceleration_ms2
        effective_force = raw_force
        is_acc_limited = False
        if apply_acceleration_limit and effective_force > acc_limit_force:
            effective_force = acc_limit_force
            is_acc_limited = True

        # Adhesion limit: F_adh = mu * m_adh * g
        adhesion_evaluated = False
        adh_limit_force = None
        is_adh_limited = False
        if apply_adhesion_limit and self.params.adhesion_coefficient is not None:
            adhesion_evaluated = True
            adh_limit_force = (
                self.params.adhesion_coefficient
                * self.params.adhesive_mass_kg
                * GRAVITY_ACCELERATION_MS2
            )
            if effective_force > adh_limit_force:
                effective_force = adh_limit_force
                is_adh_limited = True

        mechanical_power = effective_force * speed_ms

        return TractionEvaluation(
            speed_ms=speed_ms,
            raw_tractive_force_n=raw_force,
            acceleration_limit_force_n=acc_limit_force,
            adhesion_limit_force_n=adh_limit_force,
            available_tractive_force_n=effective_force,
            mechanical_power_w=mechanical_power,
            adhesion_evaluated=adhesion_evaluated,
            is_acceleration_limited=is_acc_limited,
            is_adhesion_limited=is_adh_limited,
        )


class DetailedTractionCurveModel(TractionModel):
    """Piecewise linear interpolated traction curve model.

    Strictly validates monotonicity, positive speeds, non-negative forces.
    Extrapolation policy:
      - If speed is below first curve point: clamps to first curve point force.
      - If speed is above last curve point: clamps force to 0.0 N.
    """

    def __init__(
        self,
        params: RollingStockParameters,
        efficiency: float = 1.0,
    ) -> None:
        if not params.traction_curve:
            raise RollingStockError(
                "Detailed traction curve model requires a non-empty traction_curve list.",
                context={"train_type_id": params.train_type_id},
            )
        if not (0.0 < efficiency <= 1.0):
            raise RollingStockError(
                f"Traction efficiency must be in (0, 1] (got {efficiency}).",
                context={"train_type_id": params.train_type_id},
            )

        self.params = params
        self.efficiency = float(efficiency)
        self.points: List[Tuple[float, float]] = []

        # P03-TR-003 & P03-B021: Strict validation of points
        prev_speed = -1.0
        for i, pt in enumerate(params.traction_curve):
            pt_force = getattr(pt, "force_n", getattr(pt, "tractive_effort_n", 0.0))
            if pt.speed_ms < 0:
                raise RollingStockError(
                    f"Traction curve point {i} has negative speed: {pt.speed_ms} m/s.",
                    context={"train_type_id": params.train_type_id},
                )
            if pt_force < 0:
                raise RollingStockError(
                    f"Traction curve point {i} has negative tractive effort: {pt_force} N.",
                    context={"train_type_id": params.train_type_id},
                )
            if i > 0 and pt.speed_ms <= prev_speed:
                raise RollingStockError(
                    f"Traction curve speeds must be strictly increasing. "
                    f"Point {i} has speed {pt.speed_ms} <= previous speed {prev_speed}.",
                    context={"train_type_id": params.train_type_id},
                )
            prev_speed = pt.speed_ms
            self.points.append((float(pt.speed_ms), float(pt_force)))

        if len(self.points) < 2:
            raise RollingStockError(
                "Traction curve must have at least two points for interpolation.",
                context={"train_type_id": params.train_type_id},
            )

    def _interpolate_raw_force(self, speed_ms: float) -> float:
        """Piecewise linear interpolation with documented boundary policy."""
        # Standstill / below lower bound: hold first point force
        if speed_ms <= self.points[0][0]:
            return self.points[0][1]

        # Beyond upper bound: clamp to 0.0 N (no traction above max curve speed)
        if speed_ms >= self.points[-1][0]:
            if speed_ms == self.points[-1][0]:
                return self.points[-1][1]
            return 0.0

        # Linear interpolation between adjacent points
        for i in range(len(self.points) - 1):
            v0, f0 = self.points[i]
            v1, f1 = self.points[i + 1]
            if v0 <= speed_ms <= v1:
                fraction = (speed_ms - v0) / (v1 - v0)
                return f0 + fraction * (f1 - f0)

        return 0.0

    def evaluate_tractive_effort(
        self,
        speed_ms: float,
        apply_acceleration_limit: bool = True,
        apply_adhesion_limit: bool = True,
    ) -> TractionEvaluation:
        if speed_ms < 0:
            raise RollingStockError(
                f"Traction evaluation requires non-negative speed (got {speed_ms} m/s)."
            )

        raw_force = self._interpolate_raw_force(speed_ms) * self.efficiency

        # Check declared power limit if provided
        if self.params.power_w is not None and self.params.power_w > 0:
            if speed_ms > 0:
                power_limited_force = (self.params.power_w / speed_ms) * self.efficiency
                raw_force = min(raw_force, power_limited_force)

        # Operational acceleration limit
        acc_limit_force = self.params.equivalent_mass_kg * self.params.max_acceleration_ms2
        effective_force = raw_force
        is_acc_limited = False
        if apply_acceleration_limit and effective_force > acc_limit_force:
            effective_force = acc_limit_force
            is_acc_limited = True

        # Adhesion limit
        adhesion_evaluated = False
        adh_limit_force = None
        is_adh_limited = False
        if apply_adhesion_limit and self.params.adhesion_coefficient is not None:
            adhesion_evaluated = True
            adh_limit_force = (
                self.params.adhesion_coefficient
                * self.params.adhesive_mass_kg
                * GRAVITY_ACCELERATION_MS2
            )
            if effective_force > adh_limit_force:
                effective_force = adh_limit_force
                is_adh_limited = True

        mechanical_power = effective_force * speed_ms

        return TractionEvaluation(
            speed_ms=speed_ms,
            raw_tractive_force_n=raw_force,
            acceleration_limit_force_n=acc_limit_force,
            adhesion_limit_force_n=adh_limit_force,
            available_tractive_force_n=effective_force,
            mechanical_power_w=mechanical_power,
            adhesion_evaluated=adhesion_evaluated,
            is_acceleration_limited=is_acc_limited,
            is_adhesion_limited=is_adh_limited,
        )


def create_traction_model(
    params: RollingStockParameters,
    efficiency: float = 1.0,
) -> TractionModel:
    """Factory creating appropriate traction model based on params configuration."""
    if params.traction_model_type == TractionModelType.DETAILED_CURVE:
        return DetailedTractionCurveModel(params, efficiency=efficiency)
    else:
        return SimplifiedTractionModel(params, efficiency=efficiency)
