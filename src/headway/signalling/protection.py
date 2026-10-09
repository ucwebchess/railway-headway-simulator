"""Braking protection integration, permitted approach speed curve, and feasibility checks.

Strictly satisfies RHS-P05-001 § 17:
- P05-BRK-001: Protection envelope calculation v_permitted = sqrt(vt^2 + 2bd).
- P05-BRK-002: Braking delays accounted for.
- P05-BRK-003: Direct integration with P04 BrakingTarget contract.
- P05-BRK-004: No duplicate physics (uses P04 BrakingModel directly).
- P05-BRK-005: Infeasible condition detection (insufficient stopping distance).
"""

import math
from typing import Optional

from headway.rolling_stock.braking import BrakingCategory, BrakingModel
from headway.signalling.authority import MovementAuthority
from headway.signalling.resource_types import BrakingFeasibilityError
from headway.simulation.targets import BrakingTarget, BrakingTargetType


class BrakingProtectionEngine:
    """Calculates braking protection curves and creates P04 BrakingTarget constraints for Movement Authorities."""

    @staticmethod
    def calculate_permitted_approach_speed(
        current_distance_m: float,
        end_of_authority_m: float,
        target_speed_ms: float,
        deceleration_ms2: float,
    ) -> float:
        """P05-BRK-001: v_permitted = sqrt(v_t^2 + 2 * b * d)."""
        dist_to_eoa = end_of_authority_m - current_distance_m
        if dist_to_eoa <= 0:
            return target_speed_ms
        v_sq = (target_speed_ms ** 2) + 2.0 * deceleration_ms2 * dist_to_eoa
        return math.sqrt(max(0.0, v_sq))

    @staticmethod
    def create_braking_target_from_authority(
        ma: MovementAuthority,
        braking_category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        margin_m: float = 0.0,
    ) -> BrakingTarget:
        """P05-BRK-003: Convert Movement Authority endpoint into a P04 BrakingTarget."""
        return BrakingTarget(
            target_id=f"TGT_{ma.ma_id}",
            route_position_m=ma.end_of_authority,
            target_speed_ms=ma.target_speed_ms,
            target_type=BrakingTargetType.FUTURE_MOVEMENT_AUTHORITY,
            braking_category=braking_category,
            margin_m=margin_m,
        )

    @staticmethod
    def validate_stopping_feasibility(
        current_speed_ms: float,
        current_position_m: float,
        end_of_authority_m: float,
        target_speed_ms: float,
        braking_model: BrakingModel,
        category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE,
        include_delays: bool = True,
    ) -> bool:
        """P05-BRK-005: Validate that available distance to EoA is sufficient for safe stopping.

        Raises BrakingFeasibilityError if stopping cannot be achieved safely.
        """
        available_distance = end_of_authority_m - current_position_m
        if current_speed_ms <= target_speed_ms:
            return True

        required_distance = braking_model.calculate_stopping_distance(
            initial_speed_ms=current_speed_ms,
            target_speed_ms=target_speed_ms,
            category=category,
            include_delays=include_delays,
        )

        if available_distance < required_distance:
            raise BrakingFeasibilityError(
                f"Insufficient braking distance to End of Authority: Available {available_distance:.1f} m, "
                f"Required {required_distance:.1f} m from speed {current_speed_ms:.1f} m/s to {target_speed_ms:.1f} m/s.",
                context={
                    "available_distance_m": available_distance,
                    "required_distance_m": required_distance,
                    "current_speed_ms": current_speed_ms,
                    "target_speed_ms": target_speed_ms,
                },
            )
        return True
