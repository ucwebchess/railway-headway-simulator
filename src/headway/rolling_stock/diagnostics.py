"""Rolling stock performance diagnostics and tabular data adapters.

Strictly satisfies RHS-P03-001 § 13:
- P03-DIAG-001: Traction curve diagnostic evaluation: speed, force, power.
- P03-DIAG-002: Resistance curve diagnostic evaluation: speed, Davis resistance, total resistance.
- P03-DIAG-003: Acceleration capability evaluation: speed vs net available acceleration.
- P03-DIAG-004: Balancing speed determination: speed where F_t(v) = R_tot(v).
- P03-DIAG-005: Tabular export adapters (list of dicts / records for pandas / reporting).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from headway.core.exceptions import RollingStockError
from headway.rolling_stock.resistance import (
    CurvatureResistanceModel,
    DavisResistanceModel,
    GradientResistanceModel,
)
from headway.rolling_stock.traction import TractionModel, create_traction_model
from headway.rolling_stock.train import RollingStockParameters


@dataclass(frozen=True)
class PerformancePoint:
    """Diagnostic evaluation at a single speed point."""

    speed_kmh: float
    speed_ms: float
    tractive_force_kn: float
    mechanical_power_kw: float
    davis_resistance_kn: float
    gradient_resistance_kn: float
    curvature_resistance_kn: float
    total_resistance_kn: float
    net_force_kn: float
    available_acceleration_ms2: float


class RollingStockDiagnostics:
    """Generates analytical performance sweeps across operating speed ranges."""

    def __init__(
        self,
        params: RollingStockParameters,
        traction_model: Optional[TractionModel] = None,
    ) -> None:
        self.params = params
        self.traction_model = traction_model or create_traction_model(params)
        self.davis_model = DavisResistanceModel.from_parameters(params)

    def evaluate_performance_sweep(
        self,
        step_kmh: float = 5.0,
        gradient_per_mille: float = 0.0,
        curvature_radius_m: Optional[float] = None,
    ) -> List[PerformancePoint]:
        """P03-DIAG-001 to 003: Generate performance data points across [0, v_max]."""
        if step_kmh <= 0:
            raise RollingStockError(f"Speed step must be positive (got {step_kmh} km/h).")

        max_speed_kmh = self.params.max_speed_ms * 3.6
        m_phys = self.params.operational_mass_kg
        m_eq = self.params.equivalent_mass_kg

        # Constant resistances from track geometry
        f_grad_n = GradientResistanceModel.evaluate_point_per_mille(
            mass_kg=m_phys, gradient_per_mille=gradient_per_mille
        )
        f_curv_n = CurvatureResistanceModel.evaluate_point(
            mass_kg=m_phys, radius_m=curvature_radius_m
        )

        speeds_kmh: List[float] = []
        cur_v = 0.0
        while cur_v < max_speed_kmh - 1e-6:
            speeds_kmh.append(cur_v)
            cur_v += step_kmh
        speeds_kmh.append(max_speed_kmh)

        results: List[PerformancePoint] = []
        for v_kmh in speeds_kmh:
            v_ms = v_kmh / 3.6
            tr_eval = self.traction_model.evaluate_tractive_effort(v_ms)
            f_tract_n = tr_eval.available_tractive_force_n
            p_mech_w = tr_eval.mechanical_power_w

            f_davis_n = self.davis_model.evaluate(v_ms)
            f_tot_res_n = f_davis_n + f_grad_n + f_curv_n
            f_net_n = f_tract_n - f_tot_res_n
            raw_acc = f_net_n / m_eq
            capped_acc = min(self.params.max_acceleration_ms2, raw_acc)

            results.append(
                PerformancePoint(
                    speed_kmh=round(v_kmh, 2),
                    speed_ms=round(v_ms, 3),
                    tractive_force_kn=round(f_tract_n / 1000.0, 3),
                    mechanical_power_kw=round(p_mech_w / 1000.0, 3),
                    davis_resistance_kn=round(f_davis_n / 1000.0, 3),
                    gradient_resistance_kn=round(f_grad_n / 1000.0, 3),
                    curvature_resistance_kn=round(f_curv_n / 1000.0, 3),
                    total_resistance_kn=round(f_tot_res_n / 1000.0, 3),
                    net_force_kn=round(f_net_n / 1000.0, 3),
                    available_acceleration_ms2=round(capped_acc, 4),
                )
            )

        return results

    def find_balancing_speed_ms(
        self,
        gradient_per_mille: float = 0.0,
        curvature_radius_m: Optional[float] = None,
        tolerance_n: float = 10.0,
    ) -> Optional[float]:
        """P03-DIAG-004: Find steady-state balancing speed where F_t(v) == R_tot(v).

        Uses bisection search over [0, v_max]. Returns None if tractive effort
        always exceeds resistance up to v_max or if train cannot move from standstill.
        """
        v_low = 0.0
        v_high = self.params.max_speed_ms
        m_phys = self.params.operational_mass_kg

        f_grad_n = GradientResistanceModel.evaluate_point_per_mille(
            mass_kg=m_phys, gradient_per_mille=gradient_per_mille
        )
        f_curv_n = CurvatureResistanceModel.evaluate_point(
            mass_kg=m_phys, radius_m=curvature_radius_m
        )

        def net_force_at(v: float) -> float:
            tr = self.traction_model.evaluate_tractive_effort(v)
            davis = self.davis_model.evaluate(v)
            return tr.available_tractive_force_n - (davis + f_grad_n + f_curv_n)

        f_low = net_force_at(v_low)
        f_high = net_force_at(v_high)

        # Train cannot overcome standstill resistance
        if f_low < 0:
            return 0.0

        # Tractive effort exceeds resistance even at max speed
        if f_high > 0:
            return None  # Balancing speed exceeds max speed

        # Bisection
        for _ in range(60):
            v_mid = (v_low + v_high) / 2.0
            f_mid = net_force_at(v_mid)
            if abs(f_mid) <= tolerance_n:
                return v_mid
            if f_mid > 0:
                v_low = v_mid
            else:
                v_high = v_mid

        return (v_low + v_high) / 2.0

    def to_records(
        self,
        sweep: List[PerformancePoint],
    ) -> List[Dict[str, Any]]:
        """P03-DIAG-005: Convert diagnostic points to tabular records."""
        return [
            {
                "speed_kmh": p.speed_kmh,
                "speed_ms": p.speed_ms,
                "tractive_force_kn": p.tractive_force_kn,
                "mechanical_power_kw": p.mechanical_power_kw,
                "davis_resistance_kn": p.davis_resistance_kn,
                "gradient_resistance_kn": p.gradient_resistance_kn,
                "curvature_resistance_kn": p.curvature_resistance_kn,
                "total_resistance_kn": p.total_resistance_kn,
                "net_force_kn": p.net_force_kn,
                "available_acceleration_ms2": p.available_acceleration_ms2,
            }
            for p in sweep
        ]
