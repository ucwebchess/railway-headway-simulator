"""Braking target models and route target extractors.

Strictly satisfies RHS-P04-001 § 8:
- P04-TGT-001: Target representation (id, position, speed, braking mode, margin, type).
- P04-TGT-002: Target types (SPEED_RESTRICTION, STATION_STOP, ROUTE_END,
  GENERIC_STOPPING_TARGET, FUTURE_MOVEMENT_AUTHORITY).
- P04-TGT-003: Target feasibility calculation.
- P04-TGT-004: Multi-target resolution along route traversals.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from headway.core.exceptions import SimulationError
from headway.infrastructure.route import Route
from headway.infrastructure.speed import RouteSpeedProfile
from headway.infrastructure.stations import RoutePlatformStop
from headway.rolling_stock.braking import BrakingCategory, BrakingModel


class BrakingTargetType(str, Enum):
    """Classification of downstream braking target."""

    SPEED_RESTRICTION = "SPEED_RESTRICTION"
    STATION_STOP = "STATION_STOP"
    ROUTE_END = "ROUTE_END"
    GENERIC_STOPPING_TARGET = "GENERIC_STOPPING_TARGET"
    FUTURE_MOVEMENT_AUTHORITY = "FUTURE_MOVEMENT_AUTHORITY"


@dataclass(frozen=True)
class BrakingTarget:
    """Downstream point constraint requiring train deceleration."""

    target_id: str
    route_position_m: float
    target_speed_ms: float
    target_type: BrakingTargetType
    braking_category: BrakingCategory = BrakingCategory.OPERATIONAL_SERVICE
    margin_m: float = 0.0
    station_id: Optional[str] = None
    stopping_point_id: Optional[str] = None
    dwell_time_s: float = 0.0

    def __post_init__(self) -> None:
        if self.route_position_m < 0:
            raise SimulationError(
                f"Target route position cannot be negative (got {self.route_position_m} m).",
                context={"target_id": self.target_id},
            )
        if self.target_speed_ms < 0:
            raise SimulationError(
                f"Target speed cannot be negative (got {self.target_speed_ms} m/s).",
                context={"target_id": self.target_id},
            )
        if self.dwell_time_s < 0:
            raise SimulationError(
                f"Station dwell time cannot be negative (got {self.dwell_time_s} s).",
                context={"target_id": self.target_id},
            )

    @property
    def effective_target_position_m(self) -> float:
        """Position where target speed must be achieved, taking safety margin into account."""
        return max(0.0, self.route_position_m - self.margin_m)

    def is_feasible(
        self,
        current_speed_ms: float,
        current_position_m: float,
        braking_model: BrakingModel,
    ) -> bool:
        """P04-TGT-003: Check if train can decelerate to target_speed from current state."""
        if current_speed_ms <= self.target_speed_ms:
            return True
        available_distance = self.effective_target_position_m - current_position_m
        if available_distance <= 0:
            return False
        required_distance = braking_model.calculate_stopping_distance(
            initial_speed_ms=current_speed_ms,
            target_speed_ms=self.target_speed_ms,
            category=self.braking_category,
            include_delays=True,
        )
        return available_distance >= required_distance


class BrakingTargetResolver:
    """Extracts and resolves all downstream braking targets along a route."""

    @staticmethod
    def resolve_targets(
        route: Route,
        speed_profile: Optional[RouteSpeedProfile] = None,
        station_views: Optional[List[RoutePlatformStop]] = None,
        mandatory_route_end_stop: bool = True,
        default_dwell_time_s: float = 30.0,
    ) -> List[BrakingTarget]:
        """P04-TGT-004: Collect all speed drops, station stops, and route end targets."""
        targets: List[BrakingTarget] = []

        # 1. Speed restriction drops
        if speed_profile is not None:
            intervals = getattr(speed_profile, "speed_intervals", getattr(speed_profile, "intervals", []))
            for i in range(len(intervals) - 1):
                cur_int = intervals[i]
                next_int = intervals[i + 1]
                cur_spd = getattr(cur_int, "max_speed_ms", getattr(cur_int, "permissible_speed_ms", 0.0))
                next_spd = getattr(next_int, "max_speed_ms", getattr(next_int, "permissible_speed_ms", 0.0))
                # If next speed limit is lower, a braking target is created at interval boundary
                if next_spd < cur_spd:
                    targets.append(
                        BrakingTarget(
                            target_id=f"TGT_SPD_{next_int.start_distance_m:.0f}",
                            route_position_m=next_int.start_distance_m,
                            target_speed_ms=next_spd,
                            target_type=BrakingTargetType.SPEED_RESTRICTION,
                            braking_category=BrakingCategory.OPERATIONAL_SERVICE,
                        )
                    )

        # 2. Station stops
        if station_views:
            for stn in station_views:
                stn_id = stn.station.station_id if hasattr(stn, "station") and hasattr(stn.station, "station_id") else getattr(stn, "station_id", "STN")
                sp_id = stn.stopping_point.stopping_point_id if hasattr(stn, "stopping_point") and hasattr(stn.stopping_point, "stopping_point_id") else getattr(stn, "stopping_point_id", None)
                targets.append(
                    BrakingTarget(
                        target_id=f"TGT_STN_{stn_id}",
                        route_position_m=stn.stopping_position_m,
                        target_speed_ms=0.0,
                        target_type=BrakingTargetType.STATION_STOP,
                        station_id=stn_id,
                        stopping_point_id=sp_id,
                        dwell_time_s=default_dwell_time_s,
                        braking_category=BrakingCategory.OPERATIONAL_SERVICE,
                    )
                )

        # 3. Mandatory route end stop
        if mandatory_route_end_stop:
            targets.append(
                BrakingTarget(
                    target_id=f"TGT_END_{route.route_id}",
                    route_position_m=route.total_length_m,
                    target_speed_ms=0.0,
                    target_type=BrakingTargetType.ROUTE_END,
                    braking_category=BrakingCategory.OPERATIONAL_SERVICE,
                )
            )

        # Sort targets strictly by route distance
        targets.sort(key=lambda t: t.route_position_m)
        return targets
