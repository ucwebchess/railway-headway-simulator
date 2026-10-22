"""Standardized simulation result object architecture.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 4 & 5).
Satisfies:
- P13-RES-001: Single Source of Results.
- P13-RES-002: No recalculation of engineering quantities.
- P13-RES-003: Explicit result identity (RUN_ID, SCENARIO_ID, configuration hash).
- P13-RES-004: Result immutability.
- P13-RES-005: Canonical schema reuse.
- P13-RES-006: Running direction inclusion on all direction-dependent results.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import pandas as pd

from headway.analysis.blocking_time import ResourceBlockingInterval
from headway.analysis.capacity_models import (
    CapacityResult,
    SensitivityStudyResult,
    TimetableCompressionResult,
)
from headway.analysis.headway_results import (
    HeadwayResult,
    MixedTrafficHeadwayMatrix,
    ResourceConflict,
)
from headway.analysis.monte_carlo import MonteCarloExecutionResult
from headway.infrastructure.direction import RunningDirection
from headway.scenarios.scenario_comparison import ScenarioComparisonReport
from headway.simulation.multi_train_engine import MultiTrainSimulationResult
from headway.simulation.trajectory import TrainTrajectory


@dataclass(frozen=True)
class PlatformOccupationRecord:
    """Record of a train occupying and clearing a platform track (P13-STN-001)."""

    train_id: str
    station_id: str
    station_name: str
    platform_id: str
    track_id: str
    link_id: str
    arrival_time_s: float
    dwell_start_time_s: float
    dwell_end_time_s: float
    departure_time_s: float
    clearance_time_s: float
    running_direction: RunningDirection
    is_residual_rear_active: bool = False
    residual_rear_duration_s: float = 0.0
    upstream_infringing_resource_ids: Tuple[str, ...] = ()
    reservation_start_s: Optional[float] = None
    final_release_s: Optional[float] = None

    @property
    def dwell_duration_s(self) -> float:
        return max(0.0, self.dwell_end_time_s - self.dwell_start_time_s)

    @property
    def total_platform_blocking_s(self) -> float:
        return max(0.0, self.clearance_time_s - self.arrival_time_s)

    @property
    def arrival_approach_s(self) -> float:
        res_s = self.reservation_start_s if self.reservation_start_s is not None else max(0.0, self.arrival_time_s - 15.0)
        return max(0.0, self.arrival_time_s - res_s)

    @property
    def passenger_dwell_s(self) -> float:
        dw = self.departure_time_s - self.arrival_time_s
        if dw <= 0.0:
            dw = self.dwell_duration_s
        return max(0.0, dw)

    @property
    def departure_clearance_s(self) -> float:
        fin_s = self.final_release_s if self.final_release_s is not None else self.clearance_time_s
        clr = fin_s - self.departure_time_s
        if clr <= 0.0:
            clr = self.residual_rear_duration_s if self.residual_rear_duration_s > 0.0 else 15.0
        return max(0.0, clr)

    @property
    def total_platform_occupation_s(self) -> float:
        return round(self.arrival_approach_s + self.passenger_dwell_s + self.departure_clearance_s, 1)


@dataclass(frozen=True)
class StationStopRecord:
    """Detailed record of a scheduled or actual train station stop (P13-STN-006)."""

    train_id: str
    station_id: str
    station_name: str
    platform_id: str
    link_id: str
    running_direction: RunningDirection
    arrival_time_s: float
    dwell_duration_s: float
    departure_time_s: float
    front_stopping_position_m: float
    rear_stopping_position_m: float
    route_chainage_km: float
    physical_chainage_km: Optional[float] = None


@dataclass(frozen=True)
class ConflictRankingRecord:
    """Standardized record for pairwise conflict ranking (P13-TBL-001)."""

    rank: int
    leader_resource_id: str
    follower_resource_id: str
    conflict_type: str
    physical_location_m: float
    route_chainage_km: float
    leader_release_time_s: float
    follower_unshifted_start_time_s: float
    required_headway_s: float
    slack_s: float
    is_controlling: bool
    classification: str = "RESOURCE_CONFLICT"


@dataclass(frozen=True)
class ResourceTimingRecord:
    """Standardized record for detailed resource occupation timings (P13-OCC-001)."""

    resource_index: int
    resource_id: str
    resource_category: str
    route_chainage_km: float
    resource_length_m: float
    entry_speed_kmh: float
    exit_speed_kmh: float
    setup_time_s: float
    approach_time_s: float
    running_time_s: float
    dwell_time_s: float
    geometric_clearance_time_s: float
    residual_rear_time_s: float
    release_time_s: float
    total_blocking_s: float
    is_controlling: bool = False
    reconciliation_difference_s: float = 0.0


@dataclass(frozen=True)
class ResourceProvenanceRecord:
    """Standardized record for resource geometry provenance tracking (P13-PRV-001)."""

    resource_id: str
    resource_type: str
    physical_chainage_km: float
    resource_length_m: float
    geometry_source: str
    dataset_id: str
    dataset_version: str
    is_baseline_geometry: bool = True
    active_scenario_id: Optional[str] = None
    physical_end_chainage_km: Optional[float] = None
    entry_signal_id: str = "N/A"
    entry_signal_chainage_km: Optional[float] = None
    exit_signal_id: str = "N/A"
    exit_signal_chainage_km: Optional[float] = None


@dataclass
class SimulationResultPackage:
    """P13-RES-001 & P13-RES-003: Authoritative canonical container for simulation outputs.

    Consolidated simulation results package consumed by the visualization library
    and the downstream professional report generator (P14).
    """

    run_id: str
    scenario_id: str
    effective_config_hash: str
    running_direction: RunningDirection
    analysis_type: str = "SIMULATION"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Trajectories (P04)
    trajectories: Dict[str, TrainTrajectory] = field(default_factory=dict)

    # Technical Headway & Blocking (P08)
    headway_results: Dict[str, HeadwayResult] = field(default_factory=dict)
    mixed_traffic_matrix: Optional[MixedTrafficHeadwayMatrix] = None
    blocking_intervals: List[ResourceBlockingInterval] = field(default_factory=list)

    # Multi-Train Operations (P09)
    multi_train_result: Optional[MultiTrainSimulationResult] = None

    # Line Capacity & Sensitivity (P10)
    capacity_result: Optional[CapacityResult] = None
    timetable_compression_result: Optional[TimetableCompressionResult] = None
    sensitivity_result: Optional[SensitivityStudyResult] = None

    # Stochastic Simulation & Operational Reliability (P11)
    monte_carlo_result: Optional[MonteCarloExecutionResult] = None

    # Scenario Comparisons (P12)
    scenario_comparison_report: Optional[ScenarioComparisonReport] = None

    # Metadata & Provenance
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_trajectories(self) -> bool:
        return bool(self.trajectories)

    @property
    def has_headway_results(self) -> bool:
        return bool(self.headway_results)

    @property
    def has_blocking_intervals(self) -> bool:
        return bool(self.blocking_intervals)

    @property
    def has_capacity_results(self) -> bool:
        return self.capacity_result is not None

    @property
    def has_stochastic_results(self) -> bool:
        return self.monte_carlo_result is not None

    @property
    def has_comparison_results(self) -> bool:
        return self.scenario_comparison_report is not None

    def get_trajectory(self, train_id: str) -> Optional[TrainTrajectory]:
        """Retrieve single train trajectory by ID."""
        return self.trajectories.get(train_id)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Summarize package contents and identity metadata."""
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "effective_config_hash": self.effective_config_hash,
            "running_direction": self.running_direction.value,
            "analysis_type": self.analysis_type,
            "timestamp": self.timestamp,
            "trajectory_count": len(self.trajectories),
            "headway_pair_count": len(self.headway_results),
            "blocking_interval_count": len(self.blocking_intervals),
            "has_multi_train": self.multi_train_result is not None,
            "has_capacity": self.capacity_result is not None,
            "has_stochastic": self.monte_carlo_result is not None,
            "has_comparison": self.scenario_comparison_report is not None,
        }
