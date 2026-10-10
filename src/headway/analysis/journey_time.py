"""Journey time analysis, component decomposition, and operational KPIs subsystem.

Strictly satisfies RHS-P09-001 § 17 & § 21:
- P09-JT-001 to 006: Standalone reference journey time, constrained multi-train journey time,
  journey-time increase Delta T = T_constrained - T_unconstrained, component decomposition,
  and TVS specific impact.
- Section 21: Operational performance indicators (KPIs) across multiple trains.
"""

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional

from headway.analysis.delays import DelayCause, TrainDelaySummary
from headway.infrastructure.direction import RunningDirection


@dataclass
class JourneyTimeDecomposition:
    """P09-JT-003 & 004: Additive decomposition of multi-train journey time."""

    train_id: str
    service_id: str
    unconstrained_journey_time_s: float
    constrained_journey_time_s: float
    journey_time_increase_s: float

    # Additive Components
    moving_time_s: float = 0.0
    planned_dwell_time_s: float = 0.0
    dwell_extension_s: float = 0.0
    operational_waiting_s: float = 0.0
    tvs_waiting_s: float = 0.0
    junction_waiting_s: float = 0.0
    platform_waiting_s: float = 0.0
    signalling_waiting_s: float = 0.0
    braking_reacceleration_loss_s: float = 0.0

    @property
    def tvs_impact_percentage(self) -> float:
        """P09-JT-005: Proportion of journey time increase attributable to TVS."""
        if self.journey_time_increase_s <= 1e-6:
            return 0.0
        return min(100.0, (self.tvs_waiting_s / self.journey_time_increase_s) * 100.0)


@dataclass
class OperationalKPIs:
    """Section 21: Comprehensive macro-level operational performance indicators."""

    total_requested_trains: int = 0
    total_dispatched_trains: int = 0
    total_completed_trains: int = 0

    mean_departure_delay_s: float = 0.0
    max_departure_delay_s: float = 0.0
    mean_arrival_delay_s: float = 0.0
    max_arrival_delay_s: float = 0.0
    max_overall_delay_s: float = 0.0

    mean_journey_time_s: float = 0.0
    max_journey_time_s: float = 0.0
    mean_journey_time_increase_s: float = 0.0

    total_station_waiting_time_s: float = 0.0
    total_junction_waiting_time_s: float = 0.0
    total_tvs_waiting_time_s: float = 0.0
    max_observed_queue_length: int = 0

    actual_departure_sequence: List[str] = field(default_factory=list)
    actual_arrival_sequence: List[str] = field(default_factory=list)


class JourneyTimeAnalyzer:
    """P09-JT: Computes journey-time expansions and operational KPIs for simulated services."""

    @staticmethod
    def evaluate_journey_time(
        train_id: str,
        service_id: str,
        unconstrained_jt_s: float,
        constrained_jt_s: float,
        planned_dwell_s: float,
        actual_dwell_s: float,
        delay_summary: TrainDelaySummary,
    ) -> JourneyTimeDecomposition:
        """P09-JT-003 & 004: Decompose journey time and isolate TVS / operational waiting."""
        delta_t = max(0.0, constrained_jt_s - unconstrained_jt_s)
        dwell_ext = max(0.0, actual_dwell_s - planned_dwell_s)

        tvs_wait = delay_summary.breakdown_by_cause_s.get(DelayCause.TVS, 0.0)
        jnc_wait = delay_summary.breakdown_by_cause_s.get(DelayCause.JUNCTION, 0.0)
        plat_wait = delay_summary.breakdown_by_cause_s.get(DelayCause.PLATFORM, 0.0)
        sig_wait = delay_summary.breakdown_by_cause_s.get(DelayCause.SIGNALLING, 0.0)

        total_wait = tvs_wait + jnc_wait + plat_wait + sig_wait
        # Additional speed loss due to deceleration and reacceleration
        residual_loss = max(0.0, delta_t - (dwell_ext + total_wait))

        return JourneyTimeDecomposition(
            train_id=train_id,
            service_id=service_id,
            unconstrained_journey_time_s=unconstrained_jt_s,
            constrained_journey_time_s=constrained_jt_s,
            journey_time_increase_s=delta_t,
            moving_time_s=max(0.0, constrained_jt_s - (actual_dwell_s + total_wait)),
            planned_dwell_time_s=planned_dwell_s,
            dwell_extension_s=dwell_ext,
            operational_waiting_s=total_wait,
            tvs_waiting_s=tvs_wait,
            junction_waiting_s=jnc_wait,
            platform_waiting_s=plat_wait,
            signalling_waiting_s=sig_wait,
            braking_reacceleration_loss_s=residual_loss,
        )

    @staticmethod
    def compute_kpis(
        requested_count: int,
        dispatched_trains: List[str],
        completed_trains: List[str],
        delay_summaries: List[TrainDelaySummary],
        journey_decompositions: List[JourneyTimeDecomposition],
        total_tvs_wait_s: float,
        max_tvs_queue: int,
    ) -> OperationalKPIs:
        """Section 21: Aggregate multi-train operational KPIs."""
        dep_delays = [d.departure_delay_s for d in delay_summaries]
        arr_delays = [d.arrival_delay_s for d in delay_summaries if d.actual_arrival_s is not None]
        j_times = [j.constrained_journey_time_s for j in journey_decompositions]
        j_increases = [j.journey_time_increase_s for j in journey_decompositions]

        mean_dep = sum(dep_delays) / len(dep_delays) if dep_delays else 0.0
        max_dep = max(dep_delays) if dep_delays else 0.0
        mean_arr = sum(arr_delays) / len(arr_delays) if arr_delays else 0.0
        max_arr = max(arr_delays) if arr_delays else 0.0
        max_overall = max(max_dep, max_arr)

        mean_jt = sum(j_times) / len(j_times) if j_times else 0.0
        max_jt = max(j_times) if j_times else 0.0
        mean_jt_inc = sum(j_increases) / len(j_increases) if j_increases else 0.0

        station_wait = sum(j.dwell_extension_s + j.platform_waiting_s for j in journey_decompositions)
        junction_wait = sum(j.junction_waiting_s for j in journey_decompositions)

        return OperationalKPIs(
            total_requested_trains=requested_count,
            total_dispatched_trains=len(dispatched_trains),
            total_completed_trains=len(completed_trains),
            mean_departure_delay_s=mean_dep,
            max_departure_delay_s=max_dep,
            mean_arrival_delay_s=mean_arr,
            max_arrival_delay_s=max_arr,
            max_overall_delay_s=max_overall,
            mean_journey_time_s=mean_jt,
            max_journey_time_s=max_jt,
            mean_journey_time_increase_s=mean_jt_inc,
            total_station_waiting_time_s=station_wait,
            total_junction_waiting_time_s=junction_wait,
            total_tvs_waiting_time_s=total_tvs_wait_s,
            max_observed_queue_length=max_tvs_queue,
            actual_departure_sequence=list(dispatched_trains),
            actual_arrival_sequence=list(completed_trains),
        )
