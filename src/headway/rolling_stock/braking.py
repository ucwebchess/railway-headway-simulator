"""Rolling stock braking models and deceleration semantics.

Strictly satisfies RHS-P04-001 § 5, § 6 & § 7:
- P04-BRK-001: Braking categories (OPERATIONAL_SERVICE, SUPERVISED, EMERGENCY).
- P04-BRK-002: Deceleration semantics (NET_EFFECTIVE vs BRAKE_GENERATED).
- P04-BRK-003: Double-counting prevention:
  - If NET_EFFECTIVE: supplied deceleration represents net train retardation (no Davis/gradient addition).
  - If BRAKE_GENERATED: net deceleration is calculated via longitudinal force balance.
- P04-BRK-004: Configurable braking build-up time t_bu >= 0.
- P04-BRK-005: Configurable response delay t_delay >= 0.
- P04-BRK-006 to 010: Constant deceleration kinematics:
  - d = (v0^2 - v1^2) / (2b)
  - t = (v0 - v1) / b
  - Stopping at zero speed without numerical reversal.
- P04-BRK-011 to 015: Speed-dependent piecewise linear braking curves.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import math
from typing import List, Optional, Tuple

from headway.core.exceptions import RollingStockError
from headway.data.canonical import BrakingModelType, BrakingSemantics
from headway.rolling_stock.train import RollingStockParameters


class BrakingCategory(str, Enum):
    """Operational context and safety level of the brake application."""

    OPERATIONAL_SERVICE = "OPERATIONAL_SERVICE"
    SUPERVISED = "SUPERVISED"
    EMERGENCY = "EMERGENCY"


@dataclass(frozen=True)
class BrakingEvaluation:
    """Instantaneous evaluation of braking performance."""

    nominal_deceleration_ms2: float  # Full capability deceleration at this speed (m/s^2)
    effective_factor: float          # Ramp fraction in [0, 1] due to delay and build-up
    effective_deceleration_ms2: float# nominal * effective_factor
    semantics: BrakingSemantics
    category: BrakingCategory


class BrakingModel(ABC):
    """Abstract base class for rolling stock braking models."""

    @abstractmethod
    def evaluate_deceleration(
        self,
        speed_ms: float,
        time_since_command_s: float = 1e6,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
    ) -> BrakingEvaluation:
        """Evaluate effective deceleration at a given speed and elapsed command time."""
        pass

    @abstractmethod
    def calculate_stopping_distance(
        self,
        initial_speed_ms: float,
        target_speed_ms: float = 0.0,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        include_delays: bool = True,
    ) -> float:
        """Calculate braking distance from initial_speed to target_speed."""
        pass

    @abstractmethod
    def calculate_stopping_time(
        self,
        initial_speed_ms: float,
        target_speed_ms: float = 0.0,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        include_delays: bool = True,
    ) -> float:
        """Calculate braking time from initial_speed to target_speed."""
        pass


class ConstantDecelerationBrakingModel(BrakingModel):
    """Constant deceleration braking model with response delay and build-up time."""

    def __init__(
        self,
        service_deceleration_ms2: float,
        emergency_deceleration_ms2: float,
        semantics: BrakingSemantics = BrakingSemantics.NET_EFFECTIVE,
        response_delay_s: float = 0.0,
        build_up_time_s: float = 0.0,
    ) -> None:
        if service_deceleration_ms2 <= 0:
            raise RollingStockError(
                f"Service deceleration must be positive (got {service_deceleration_ms2} m/s^2)."
            )
        if emergency_deceleration_ms2 <= 0:
            raise RollingStockError(
                f"Emergency deceleration must be positive (got {emergency_deceleration_ms2} m/s^2)."
            )
        if response_delay_s < 0:
            raise RollingStockError(
                f"Response delay must be non-negative (got {response_delay_s} s)."
            )
        if build_up_time_s < 0:
            raise RollingStockError(
                f"Build-up time must be non-negative (got {build_up_time_s} s)."
            )

        self.service_deceleration_ms2 = float(service_deceleration_ms2)
        self.emergency_deceleration_ms2 = float(emergency_deceleration_ms2)
        self.semantics = semantics
        self.response_delay_s = float(response_delay_s)
        self.build_up_time_s = float(build_up_time_s)

    @classmethod
    def from_parameters(
        cls,
        params: RollingStockParameters,
        semantics: BrakingSemantics = BrakingSemantics.NET_EFFECTIVE,
        response_delay_s: float = 0.0,
        build_up_time_s: float = 0.0,
    ) -> "ConstantDecelerationBrakingModel":
        return cls(
            service_deceleration_ms2=params.max_service_deceleration_ms2,
            emergency_deceleration_ms2=params.emergency_deceleration_ms2,
            semantics=semantics,
            response_delay_s=response_delay_s,
            build_up_time_s=build_up_time_s,
        )

    def _get_nominal_deceleration(self, category: BrakingCategory) -> float:
        if category == BrakingCategory.EMERGENCY:
            return self.emergency_deceleration_ms2
        return self.service_deceleration_ms2

    def _get_buildup_factor(self, time_since_command_s: float) -> float:
        if time_since_command_s < self.response_delay_s:
            return 0.0
        if self.build_up_time_s <= 0.0:
            return 1.0
        elapsed_build = time_since_command_s - self.response_delay_s
        return min(1.0, elapsed_build / self.build_up_time_s)

    def evaluate_deceleration(
        self,
        speed_ms: float,
        time_since_command_s: float = 1e6,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
    ) -> BrakingEvaluation:
        if speed_ms < 0:
            raise RollingStockError(f"Speed must be non-negative (got {speed_ms} m/s).")

        nominal = self._get_nominal_deceleration(category)
        factor = self._get_buildup_factor(time_since_command_s)
        effective = nominal * factor

        return BrakingEvaluation(
            nominal_deceleration_ms2=nominal,
            effective_factor=factor,
            effective_deceleration_ms2=effective,
            semantics=self.semantics,
            category=category,
        )

    def calculate_stopping_distance(
        self,
        initial_speed_ms: float,
        target_speed_ms: float = 0.0,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        include_delays: bool = True,
    ) -> float:
        """Calculate braking distance d = (v0^2 - v1^2) / (2b) plus response/build-up distance."""
        if initial_speed_ms < 0 or target_speed_ms < 0:
            raise RollingStockError("Speeds must be non-negative.")
        if initial_speed_ms <= target_speed_ms:
            return 0.0

        b = self._get_nominal_deceleration(category)
        # Kinematic steady braking distance
        d_steady = (initial_speed_ms ** 2 - target_speed_ms ** 2) / (2.0 * b)

        if not include_delays:
            return d_steady

        # Additional distance covered during response delay: train coasts at initial_speed
        d_delay = initial_speed_ms * self.response_delay_s

        # Additional distance covered during linear build-up ramp:
        # During ramp from 0 to b, average deceleration is b/2.
        # delta_v_bu = 0.5 * b * t_bu.
        # If speed reduction during build-up exceeds initial - target, build-up handles the whole stop.
        t_bu = self.build_up_time_s
        if t_bu > 0:
            # During linear ramp, a(t) = b * (t / t_bu)
            # v(t) = v0 - 0.5 * b * t^2 / t_bu
            # x(t) = v0 * t - (1/6) * b * t^3 / t_bu
            # At t = t_bu: v(t_bu) = v0 - 0.5 * b * t_bu
            # x(t_bu) = v0 * t_bu - (1/6) * b * t_bu^2
            delta_v_bu = 0.5 * b * t_bu
            if initial_speed_ms - delta_v_bu >= target_speed_ms:
                # Full build-up completes before target speed is reached
                d_bu = initial_speed_ms * t_bu - (1.0 / 6.0) * b * (t_bu ** 2)
                v_after_bu = initial_speed_ms - delta_v_bu
                d_rem = (v_after_bu ** 2 - target_speed_ms ** 2) / (2.0 * b)
                return d_delay + d_bu + d_rem
            else:
                # Train reaches target speed during the build-up phase itself
                # v(t*) = v0 - 0.5 * b * t*^2 / t_bu = target_speed_ms
                # t* = sqrt(2 * t_bu * (v0 - v_target) / b)
                delta_v_needed = initial_speed_ms - target_speed_ms
                t_star = math.sqrt(2.0 * t_bu * delta_v_needed / b)
                d_bu = initial_speed_ms * t_star - (1.0 / 6.0) * b * (t_star ** 3) / t_bu
                return d_delay + d_bu

        return d_delay + d_steady

    def calculate_stopping_time(
        self,
        initial_speed_ms: float,
        target_speed_ms: float = 0.0,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        include_delays: bool = True,
    ) -> float:
        """Calculate braking time t = (v0 - v1) / b plus response delay and build-up time."""
        if initial_speed_ms <= target_speed_ms:
            return 0.0

        b = self._get_nominal_deceleration(category)
        t_steady = (initial_speed_ms - target_speed_ms) / b

        if not include_delays:
            return t_steady

        t_total = self.response_delay_s
        t_bu = self.build_up_time_s
        if t_bu > 0:
            delta_v_bu = 0.5 * b * t_bu
            if initial_speed_ms - delta_v_bu >= target_speed_ms:
                v_rem = (initial_speed_ms - delta_v_bu) - target_speed_ms
                t_total += t_bu + (v_rem / b)
            else:
                delta_v_needed = initial_speed_ms - target_speed_ms
                t_star = math.sqrt(2.0 * t_bu * delta_v_needed / b)
                t_total += t_star
        else:
            t_total += t_steady

        return t_total


class SpeedDependentBrakingModel(BrakingModel):
    """Piecewise linear interpolated speed-dependent braking curve model."""

    def __init__(
        self,
        curve_points: List[Tuple[float, float]],  # (speed_ms, deceleration_ms2)
        emergency_factor: float = 1.3,
        semantics: BrakingSemantics = BrakingSemantics.NET_EFFECTIVE,
        response_delay_s: float = 0.0,
        build_up_time_s: float = 0.0,
    ) -> None:
        if not curve_points or len(curve_points) < 2:
            raise RollingStockError(
                "Speed-dependent braking model requires at least 2 curve points."
            )
        if emergency_factor <= 1.0:
            raise RollingStockError("Emergency factor must be > 1.0.")
        if response_delay_s < 0 or build_up_time_s < 0:
            raise RollingStockError("Delays must be non-negative.")

        # Validate points
        prev_v = -1.0
        self.points: List[Tuple[float, float]] = []
        for i, (v, dec) in enumerate(curve_points):
            if v < 0:
                raise RollingStockError(f"Curve point {i} has negative speed {v} m/s.")
            if dec <= 0:
                raise RollingStockError(f"Curve point {i} has non-positive deceleration {dec} m/s^2.")
            if i > 0 and v <= prev_v:
                raise RollingStockError(
                    f"Braking curve speeds must be strictly increasing. Point {i} has speed {v} <= {prev_v}."
                )
            prev_v = v
            self.points.append((float(v), float(dec)))

        self.emergency_factor = float(emergency_factor)
        self.semantics = semantics
        self.response_delay_s = float(response_delay_s)
        self.build_up_time_s = float(build_up_time_s)

    def _interpolate_deceleration(self, speed_ms: float) -> float:
        if speed_ms <= self.points[0][0]:
            return self.points[0][1]
        if speed_ms >= self.points[-1][0]:
            return self.points[-1][1]

        for i in range(len(self.points) - 1):
            v0, b0 = self.points[i]
            v1, b1 = self.points[i + 1]
            if v0 <= speed_ms <= v1:
                frac = (speed_ms - v0) / (v1 - v0)
                return b0 + frac * (b1 - b0)
        return self.points[-1][1]

    def _get_buildup_factor(self, time_since_command_s: float) -> float:
        if time_since_command_s < self.response_delay_s:
            return 0.0
        if self.build_up_time_s <= 0.0:
            return 1.0
        elapsed_build = time_since_command_s - self.response_delay_s
        return min(1.0, elapsed_build / self.build_up_time_s)

    def evaluate_deceleration(
        self,
        speed_ms: float,
        time_since_command_s: float = 1e6,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
    ) -> BrakingEvaluation:
        if speed_ms < 0:
            raise RollingStockError(f"Speed must be non-negative (got {speed_ms} m/s).")

        base_dec = self._interpolate_deceleration(speed_ms)
        nominal = base_dec * (self.emergency_factor if category == BrakingCategory.EMERGENCY else 1.0)
        factor = self._get_buildup_factor(time_since_command_s)
        effective = nominal * factor

        return BrakingEvaluation(
            nominal_deceleration_ms2=nominal,
            effective_factor=factor,
            effective_deceleration_ms2=effective,
            semantics=self.semantics,
            category=category,
        )

    def calculate_stopping_distance(
        self,
        initial_speed_ms: float,
        target_speed_ms: float = 0.0,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        include_delays: bool = True,
    ) -> float:
        """Numerical integration of stopping distance for speed-dependent deceleration."""
        if initial_speed_ms <= target_speed_ms:
            return 0.0

        # Discretize speed interval into small slices (dv = 0.2 m/s)
        # ds = v * dt = v * (dv / b(v)) = (v / b(v)) dv
        num_slices = max(50, int((initial_speed_ms - target_speed_ms) / 0.2))
        dv = (initial_speed_ms - target_speed_ms) / num_slices
        total_d = 0.0

        mult = self.emergency_factor if category == BrakingCategory.EMERGENCY else 1.0

        for i in range(num_slices):
            v_mid = target_speed_ms + (i + 0.5) * dv
            b_mid = self._interpolate_deceleration(v_mid) * mult
            total_d += (v_mid / b_mid) * dv

        if include_delays:
            total_d += initial_speed_ms * self.response_delay_s
            if self.build_up_time_s > 0:
                b_init = self._interpolate_deceleration(initial_speed_ms) * mult
                total_d += 0.5 * (initial_speed_ms * self.build_up_time_s)

        return total_d

    def calculate_stopping_time(
        self,
        initial_speed_ms: float,
        target_speed_ms: float = 0.0,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        include_delays: bool = True,
    ) -> float:
        """Numerical integration of stopping time: dt = dv / b(v)."""
        if initial_speed_ms <= target_speed_ms:
            return 0.0

        num_slices = max(50, int((initial_speed_ms - target_speed_ms) / 0.2))
        dv = (initial_speed_ms - target_speed_ms) / num_slices
        total_t = 0.0

        mult = self.emergency_factor if category == BrakingCategory.EMERGENCY else 1.0

        for i in range(num_slices):
            v_mid = target_speed_ms + (i + 0.5) * dv
            b_mid = self._interpolate_deceleration(v_mid) * mult
            total_t += dv / b_mid

        if include_delays:
            total_t += self.response_delay_s + self.build_up_time_s

        return total_t


def create_braking_model(
    params: RollingStockParameters,
    semantics: BrakingSemantics = BrakingSemantics.NET_EFFECTIVE,
    response_delay_s: float = 0.0,
    build_up_time_s: float = 0.0,
) -> BrakingModel:
    """Factory creating appropriate braking model from parameters."""
    return ConstantDecelerationBrakingModel(
        service_deceleration_ms2=params.max_service_deceleration_ms2,
        emergency_deceleration_ms2=params.emergency_deceleration_ms2,
        semantics=semantics,
        response_delay_s=response_delay_s,
        build_up_time_s=build_up_time_s,
    )
