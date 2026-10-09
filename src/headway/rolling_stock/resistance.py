"""Running, gradient, curvature, and distributed train resistance engine.

Strictly satisfies RHS-P03-001 § 7, § 8, § 9, § 10:
- P03-DAV-001 to 005: Davis resistance R(v) = A + B*v + C*v^2 in SI units, non-negativity, standstill R(0) = A.
- P03-GRD-001 to 005: Small-gradient approximation F_g = m * g * i, reverse sign inversion, distributed gradient.
- P03-CUR-001 to 005: Roeckl curvature W_c = 650 / (R - 55) for R >= 300m, straight track F_c = 0, non-negativity.
- P03-DIST-001 to 008: Distributed resistance over full train length L_train across alignment intervals.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from headway.core.exceptions import RollingStockError
from headway.core.units import GRAVITY_ACCELERATION_MS2
from headway.infrastructure.alignment import RouteAlignmentProfile
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.preprocessor import RouteProfile
from headway.infrastructure.route import Route
from headway.rolling_stock.train import RollingStockParameters


@dataclass(frozen=True)
class ResistanceSegment:
    """Individual segment breakdown for distributed resistance calculations."""

    start_m: float
    end_m: float
    length_m: float
    mass_fraction: float
    segment_mass_kg: float
    parameter_value: Optional[float]  # gradient_decimal or radius_m
    specific_resistance_per_mille: float
    force_n: float


@dataclass(frozen=True)
class DistributedResistanceResult:
    """Structured result of distributed resistance evaluation along track alignment."""

    speed_ms: float
    front_position_m: float
    rear_position_m: float
    occupied_length_m: float
    davis_resistance_n: float
    gradient_resistance_n: float
    curvature_resistance_n: float
    total_resistance_n: float
    effective_average_gradient_per_mille: float
    gradient_segments: List[ResistanceSegment] = field(default_factory=list)
    curvature_segments: List[ResistanceSegment] = field(default_factory=list)


class DavisResistanceModel:
    """Evaluates train running resistance using Davis equation: R(v) = A + B*v + C*v^2."""

    def __init__(self, a_n: float, b_ns_m: float, c_ns2_m2: float) -> None:
        if a_n < 0:
            raise RollingStockError(f"Davis coefficient A must be non-negative (got {a_n} N).")
        if b_ns_m < 0:
            raise RollingStockError(f"Davis coefficient B must be non-negative (got {b_ns_m} N*s/m).")
        if c_ns2_m2 < 0:
            raise RollingStockError(f"Davis coefficient C must be non-negative (got {c_ns2_m2} N*s^2/m^2).")

        self.a_n = float(a_n)
        self.b_ns_m = float(b_ns_m)
        self.c_ns2_m2 = float(c_ns2_m2)

    @classmethod
    def from_parameters(cls, params: RollingStockParameters) -> "DavisResistanceModel":
        return cls(
            a_n=params.davis_a_n,
            b_ns_m=params.davis_b_ns_m,
            c_ns2_m2=params.davis_c_ns2_m2,
        )

    def evaluate(self, speed_ms: float) -> float:
        """Evaluate running resistance force in Newtons for speed v >= 0 m/s.

        P03-DAV-003: Strictly non-negative.
        P03-DAV-004: Standstill R(0) = A.
        """
        if speed_ms < 0:
            raise RollingStockError(f"Speed must be non-negative (got {speed_ms} m/s).")
        return self.a_n + self.b_ns_m * speed_ms + self.c_ns2_m2 * (speed_ms ** 2)


class GradientResistanceModel:
    """Evaluates gravitational resistance from vertical track inclination.

    Formula: F_g = m * g * i (where i is slope in decimal, e.g. 0.010 = 10‰).
    Direction aware: uphill (+i) produces positive force (opposes acceleration);
    downhill (-i) produces negative force (assists acceleration).
    In REVERSE operation: effective gradient is inverted (-i_phys).
    """

    @staticmethod
    def evaluate_point(
        mass_kg: float,
        gradient_decimal: float,
        direction: RunningDirection = RunningDirection.FORWARD,
    ) -> float:
        """P03-GRD-001 & P03-GRD-004: Calculate point gradient force.

        If direction is REVERSE, gradient is inverted relative to physical track.
        """
        if mass_kg <= 0:
            raise RollingStockError(f"Mass must be positive (got {mass_kg} kg).")

        eff_gradient = gradient_decimal if direction.is_forward else -gradient_decimal
        return mass_kg * GRAVITY_ACCELERATION_MS2 * eff_gradient

    @staticmethod
    def evaluate_point_per_mille(
        mass_kg: float,
        gradient_per_mille: float,
        direction: RunningDirection = RunningDirection.FORWARD,
    ) -> float:
        """Point gradient force given gradient in per mille (‰)."""
        return GradientResistanceModel.evaluate_point(
            mass_kg=mass_kg,
            gradient_decimal=gradient_per_mille / 1000.0,
            direction=direction,
        )

    @staticmethod
    def evaluate_distributed(
        total_mass_kg: float,
        train_length_m: float,
        intervals: List[Tuple[float, float, float]],
    ) -> Tuple[float, List[ResistanceSegment]]:
        """P03-GRD-005 & P03-DIST-002: Mass-weighted integration over intersecting intervals.

        Each interval is (start_m, end_m, effective_gradient_decimal).
        Returns (total_force_n, list_of_segments).
        """
        if total_mass_kg <= 0:
            raise RollingStockError(f"Mass must be positive (got {total_mass_kg} kg).")
        if train_length_m <= 0:
            raise RollingStockError(f"Train length must be positive (got {train_length_m} m).")
        if not intervals:
            return 0.0, []

        total_force_n = 0.0
        segments: List[ResistanceSegment] = []

        for s_start, s_end, eff_grad in intervals:
            seg_len = s_end - s_start
            if seg_len <= 0:
                continue
            mass_fraction = seg_len / train_length_m
            seg_mass = total_mass_kg * mass_fraction
            seg_force = seg_mass * GRAVITY_ACCELERATION_MS2 * eff_grad
            total_force_n += seg_force

            segments.append(
                ResistanceSegment(
                    start_m=s_start,
                    end_m=s_end,
                    length_m=seg_len,
                    mass_fraction=mass_fraction,
                    segment_mass_kg=seg_mass,
                    parameter_value=eff_grad,
                    specific_resistance_per_mille=eff_grad * 1000.0,
                    force_n=seg_force,
                )
            )

        return total_force_n, segments


class CurvatureResistanceModel:
    """Evaluates curve resistance using the authoritative Roeckl formula.

    Formula: W_c = 650 / (R - 55) in ‰ for R >= 300 m.
    Force: F_c = m * g * (W_c / 1000) in Newtons.
    Straight track (R is None or R <= 0): F_c = 0.0 N.
    Direction invariant: F_c >= 0 opposes motion in both FORWARD and REVERSE.
    """

    MIN_ROECKL_RADIUS_M = 300.0

    @staticmethod
    def calculate_roeckl_specific_resistance(radius_m: Optional[float]) -> float:
        """P03-CUR-001 & P03-CUR-002: Calculate Roeckl specific resistance in ‰.

        Returns 0.0 for straight/tangent track (radius is None or <= 0).
        Raises RollingStockError for 0 < R < 300 m.
        """
        if radius_m is None or radius_m <= 0 or radius_m >= 1e9:
            return 0.0  # Tangent track

        if radius_m < CurvatureResistanceModel.MIN_ROECKL_RADIUS_M:
            raise RollingStockError(
                f"Curve radius {radius_m} m is below the minimum valid range "
                f"for the Roeckl formula ({CurvatureResistanceModel.MIN_ROECKL_RADIUS_M} m).",
                context={"radius_m": radius_m},
            )

        return 650.0 / (radius_m - 55.0)

    @classmethod
    def evaluate_point(cls, mass_kg: float, radius_m: Optional[float]) -> float:
        """P03-CUR-001 & P03-B013: Point curvature resistance force in Newtons."""
        if mass_kg <= 0:
            raise RollingStockError(f"Mass must be positive (got {mass_kg} kg).")

        w_c = cls.calculate_roeckl_specific_resistance(radius_m)
        return mass_kg * GRAVITY_ACCELERATION_MS2 * (w_c / 1000.0)

    @classmethod
    def evaluate_distributed(
        cls,
        total_mass_kg: float,
        train_length_m: float,
        intervals: List[Tuple[float, float, Optional[float]]],
    ) -> Tuple[float, List[ResistanceSegment]]:
        """P03-CUR-005 & P03-DIST-003: Mass-weighted integration of curvature resistance.

        Each interval is (start_m, end_m, radius_m).
        Returns (total_force_n, list_of_segments).
        """
        if total_mass_kg <= 0:
            raise RollingStockError(f"Mass must be positive (got {total_mass_kg} kg).")
        if train_length_m <= 0:
            raise RollingStockError(f"Train length must be positive (got {train_length_m} m).")
        if not intervals:
            return 0.0, []

        total_force_n = 0.0
        segments: List[ResistanceSegment] = []

        for s_start, s_end, radius in intervals:
            seg_len = s_end - s_start
            if seg_len <= 0:
                continue
            mass_fraction = seg_len / train_length_m
            seg_mass = total_mass_kg * mass_fraction
            w_c = cls.calculate_roeckl_specific_resistance(radius)
            seg_force = seg_mass * GRAVITY_ACCELERATION_MS2 * (w_c / 1000.0)
            total_force_n += seg_force

            segments.append(
                ResistanceSegment(
                    start_m=s_start,
                    end_m=s_end,
                    length_m=seg_len,
                    mass_fraction=mass_fraction,
                    segment_mass_kg=seg_mass,
                    parameter_value=radius,
                    specific_resistance_per_mille=w_c,
                    force_n=seg_force,
                )
            )

        return total_force_n, segments


class DistributedResistanceEngine:
    """Integrates Davis, gradient, and curvature resistance over train length."""

    def __init__(self, params: RollingStockParameters) -> None:
        self.params = params
        self.davis_model = DavisResistanceModel.from_parameters(params)

    def evaluate(
        self,
        speed_ms: float,
        front_position_m: float,
        alignment: Union[RouteAlignmentProfile, RouteProfile, Route],
    ) -> DistributedResistanceResult:
        """P03-DIST-001 to P03-DIST-008: Full distributed resistance calculation."""
        if speed_ms < 0:
            raise RollingStockError(f"Speed must be non-negative (got {speed_ms} m/s).")

        # Resolve alignment profile from argument type
        if isinstance(alignment, RouteProfile):
            align_prof = alignment.alignment
            route_len = alignment.total_length_m
        elif isinstance(alignment, RouteAlignmentProfile):
            align_prof = alignment
            route_len = alignment.route.total_length_m
        elif isinstance(alignment, Route):
            align_prof = RouteAlignmentProfile(alignment)
            route_len = alignment.total_length_m
        else:
            raise RollingStockError(
                f"Unsupported alignment type: {type(alignment).__name__}. "
                "Must be RouteProfile, RouteAlignmentProfile, or Route."
            )

        train_len = self.params.length_m
        mass = self.params.operational_mass_kg

        # Train spans [rear_pos, front_pos]
        rear_pos = front_position_m - train_len

        # Clamp occupied range to available route geometry (P03-DIST-008)
        occ_start = max(0.0, min(route_len, rear_pos))
        occ_end = max(0.0, min(route_len, front_position_m))
        occ_len = occ_end - occ_start

        if occ_len <= 0.0:
            # Train is outside route boundaries
            davis_force = self.davis_model.evaluate(speed_ms)
            return DistributedResistanceResult(
                speed_ms=speed_ms,
                front_position_m=front_position_m,
                rear_position_m=rear_pos,
                occupied_length_m=0.0,
                davis_resistance_n=davis_force,
                gradient_resistance_n=0.0,
                curvature_resistance_n=0.0,
                total_resistance_n=davis_force,
                effective_average_gradient_per_mille=0.0,
                gradient_segments=[],
                curvature_segments=[],
            )

        # Fraction of train inside the route
        train_fraction_on_route = occ_len / train_len
        effective_mass_on_route = mass * train_fraction_on_route

        # Intersect with gradient and curvature intervals
        grad_intervals = align_prof.get_gradient_intervals_intersecting(occ_start, occ_end)
        curv_intervals = align_prof.get_curvature_intervals_intersecting(occ_start, occ_end)

        f_grad, grad_segs = GradientResistanceModel.evaluate_distributed(
            total_mass_kg=effective_mass_on_route,
            train_length_m=occ_len,
            intervals=grad_intervals,
        )

        f_curv, curv_segs = CurvatureResistanceModel.evaluate_distributed(
            total_mass_kg=effective_mass_on_route,
            train_length_m=occ_len,
            intervals=curv_intervals,
        )

        davis_force = self.davis_model.evaluate(speed_ms)
        total_resistance = davis_force + f_grad + f_curv

        # Average effective gradient in ‰
        avg_grad_per_mille = (
            (f_grad / (effective_mass_on_route * GRAVITY_ACCELERATION_MS2)) * 1000.0
            if effective_mass_on_route > 0
            else 0.0
        )

        return DistributedResistanceResult(
            speed_ms=speed_ms,
            front_position_m=front_position_m,
            rear_position_m=rear_pos,
            occupied_length_m=occ_len,
            davis_resistance_n=davis_force,
            gradient_resistance_n=f_grad,
            curvature_resistance_n=f_curv,
            total_resistance_n=total_resistance,
            effective_average_gradient_per_mille=avg_grad_per_mille,
            gradient_segments=grad_segs,
            curvature_segments=curv_segs,
        )
