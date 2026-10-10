"""Residual stationary rear occupation detection and clearance time calculations.

Strictly satisfies RHS-P07-001 § 8:
- P07-RESID-001: P04 actual train-front stopping position.
- P07-RESID-002: Actual train-rear position s_rear = s_front - L_train.
- P07-RESID-003: Upstream resource intersection detection.
- P07-RESID-004: Infringement distance d_infringement = max(0, x_boundary - x_rear).
- P07-RESID-005: Upstream resource remains physically occupied during dwell.
- P07-RESID-006: Actual stationary occupation duration recorded.
- P07-RESID-007: Departure clearance moving time calculation.
- P07-RESID-008: No full dwell assumption unless physical intersection exists throughout.
- P07-RESID-009: Direction-dependent calculation for both FORWARD and REVERSE running.
- Numerical Benchmark A: Train L=200m, Front=1000m, Rear=800m, Boundary=850m, Dwell=180s
  => Infringement = 50.0 m, Stationary occupation = 180.0 s.
"""

from dataclasses import dataclass
import math
from typing import Optional

from headway.infrastructure.direction import RunningDirection


@dataclass
class ResidualOccupationRecord:
    """Detailed record of residual rear occupation at a station stopping position."""

    train_id: str
    upstream_resource_id: str
    front_stopping_position_m: float
    train_length_m: float
    rear_stopping_position_m: float
    clearance_boundary_m: float
    infringement_distance_m: float
    dwell_duration_s: float
    stationary_occupation_s: float
    running_direction: RunningDirection = RunningDirection.FORWARD

    @property
    def is_infringing(self) -> bool:
        """True if the stationary rear protrudes into the upstream resource."""
        return self.infringement_distance_m > 1e-4

    @property
    def rear_stopping_offset_m(self) -> float:
        """Alias for rear stopping position."""
        return self.rear_stopping_position_m

    @property
    def stationary_dwell_duration_s(self) -> float:
        """Alias for stationary dwell duration."""
        return self.stationary_occupation_s

    @property
    def moving_clearance_time_s(self) -> float:
        """Moving clearance time under default or recorded acceleration."""
        if hasattr(self, "_moving_clearance_time_s"):
            return self._moving_clearance_time_s
        return self.calculate_departure_clearance_time_s(acceleration_ms2=0.5)

    @property
    def total_upstream_clearance_time_s(self) -> float:
        """Total time upstream resource remains occupied (stationary dwell + moving clearance)."""
        if not self.is_infringing:
            return 0.0
        return self.stationary_dwell_duration_s + self.moving_clearance_time_s

    def calculate_departure_clearance_time_s(
        self,
        acceleration_ms2: float = 0.5,
        target_speed_ms: Optional[float] = None,
    ) -> float:
        """P07-RESID-007: Calculate moving time after departure for rear to clear boundary.

        d = 0.5 * a * t^2 => t = sqrt(2 * d / a).
        If max speed is reached before clearance, computes two-phase acceleration + cruise time.
        """
        if not self.is_infringing or acceleration_ms2 <= 0:
            return 0.0

        d = self.infringement_distance_m
        if target_speed_ms is None or target_speed_ms <= 0:
            # Pure acceleration phase
            return round(math.sqrt(2.0 * d / acceleration_ms2), 3)

        # Distance to reach target speed
        t_acc = target_speed_ms / acceleration_ms2
        d_acc = 0.5 * acceleration_ms2 * (t_acc ** 2)

        if d <= d_acc:
            return round(math.sqrt(2.0 * d / acceleration_ms2), 3)
        else:
            d_cruise = d - d_acc
            t_cruise = d_cruise / target_speed_ms
            return round(t_acc + t_cruise, 3)


class ResidualOccupationDetector:
    """P07-RESID: Evaluates geometric residual rear infringement of stationary trains."""

    @staticmethod
    def evaluate_residual_occupation(
        train_id: str,
        front_stopping_position_m: float,
        train_length_m: float,
        clearance_boundary_m: float,
        upstream_resource_id: str,
        dwell_duration_s: float,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> ResidualOccupationRecord:
        """Evaluate rear infringement and residual occupation duration.

        Route-distance coordinate formulation (Benchmark A):
        s_front = 1000.0 m, L = 200.0 m => s_rear = 800.0 m.
        clearance_boundary = 850.0 m.
        d_infringement = max(0, 850.0 - 800.0) = 50.0 m.
        stationary_occupation = 180.0 s (dwell).
        """
        # Route coordinates always increase in direction of travel
        rear_pos = round(front_stopping_position_m - train_length_m, 3)

        # If train rear is behind the clearance boundary, it infringes upstream
        if rear_pos < clearance_boundary_m:
            infringement_d = round(clearance_boundary_m - rear_pos, 3)
            stat_time = dwell_duration_s
        else:
            infringement_d = 0.0
            stat_time = 0.0

        return ResidualOccupationRecord(
            train_id=train_id,
            upstream_resource_id=upstream_resource_id,
            front_stopping_position_m=round(front_stopping_position_m, 3),
            train_length_m=round(train_length_m, 3),
            rear_stopping_position_m=rear_pos,
            clearance_boundary_m=round(clearance_boundary_m, 3),
            infringement_distance_m=infringement_d,
            dwell_duration_s=round(dwell_duration_s, 3),
            stationary_occupation_s=round(stat_time, 3),
            running_direction=running_direction,
        )

    @staticmethod
    def evaluate_reverse_physical_infringement(
        train_id: str,
        front_physical_chainage_m: float,
        train_length_m: float,
        clearance_boundary_chainage_m: float,
        upstream_resource_id: str,
        dwell_duration_s: float,
    ) -> ResidualOccupationRecord:
        """P07-RESID-009: Reverse running in decreasing physical chainage coordinates.

        In reverse, train moves from higher chainage to lower chainage:
        front is at x_front, rear is at x_rear = x_front + L_train.
        Upstream clearance boundary is at higher chainage x_boundary.
        Infringement occurs if x_rear > x_boundary (train hasn't cleared below boundary).
        d_infringement = max(0, x_rear - x_boundary).
        """
        rear_pos = round(front_physical_chainage_m + train_length_m, 3)

        if rear_pos > clearance_boundary_chainage_m:
            infringement_d = round(rear_pos - clearance_boundary_chainage_m, 3)
            stat_time = dwell_duration_s
        else:
            infringement_d = 0.0
            stat_time = 0.0

        return ResidualOccupationRecord(
            train_id=train_id,
            upstream_resource_id=upstream_resource_id,
            front_stopping_position_m=round(front_physical_chainage_m, 3),
            train_length_m=round(train_length_m, 3),
            rear_stopping_position_m=rear_pos,
            clearance_boundary_m=round(clearance_boundary_chainage_m, 3),
            infringement_distance_m=infringement_d,
            dwell_duration_s=round(dwell_duration_s, 3),
            stationary_occupation_s=round(stat_time, 3),
            running_direction=RunningDirection.REVERSE,
        )

    @classmethod
    def detect_residual_rear_infringement(
        cls,
        train_id: str,
        train_length_m: float,
        front_stopping_offset_m: float,
        platform_id: str,
        platform_entry_boundary_offset_m: float,
        upstream_resource_id: str,
        dwell_duration_s: float,
        post_departure_accel_ms2: float = 0.5,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> ResidualOccupationRecord:
        """P07-B012 & Benchmark A: Detect and compute residual rear occupation."""
        if running_direction == RunningDirection.FORWARD:
            rec = cls.evaluate_residual_occupation(
                train_id=train_id,
                front_stopping_position_m=front_stopping_offset_m,
                train_length_m=train_length_m,
                clearance_boundary_m=platform_entry_boundary_offset_m,
                upstream_resource_id=upstream_resource_id,
                dwell_duration_s=dwell_duration_s,
                running_direction=running_direction,
            )
        else:
            rec = cls.evaluate_reverse_physical_infringement(
                train_id=train_id,
                front_physical_chainage_m=front_stopping_offset_m,
                train_length_m=train_length_m,
                clearance_boundary_chainage_m=platform_entry_boundary_offset_m,
                upstream_resource_id=upstream_resource_id,
                dwell_duration_s=dwell_duration_s,
            )
        # Store calculated moving clearance time based on provided acceleration
        rec._moving_clearance_time_s = rec.calculate_departure_clearance_time_s(
            acceleration_ms2=post_departure_accel_ms2
        )
        return rec
