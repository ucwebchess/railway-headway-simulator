"""Standard result contracts, validation statuses, and stairway datasets.

Strictly satisfies RHS-P08-001:
- § 15: Directional Mixed-Traffic Headway Matrix (P08-MIX-001 to P08-MIX-007).
- § 21: Blocking-Time Stairway Datasets for P13 visualization.
- § 23: Standard Result Contract (P08-RES-001).
- § 28: Result Validation Classification (VALID, VALID_WITH_WARNINGS, etc.).
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from headway.analysis.blocking_time import ResourceBlockingInterval
from headway.analysis.conflict_detection import ResourceConflict
from headway.infrastructure.direction import RunningDirection


class HeadwayValidationStatus(str, Enum):
    """P08-VAL: Rigorous validation classification for headway results."""

    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    NOT_CONVERGED = "NOT_CONVERGED"
    INFEASIBLE = "INFEASIBLE"
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_CONFIGURATION = "UNSUPPORTED_CONFIGURATION"
    SIMULATION_FAILED = "SIMULATION_FAILED"


@dataclass
class StairwayBlockData:
    """P08-STAIR: Structured blocking time stairway data suitable for P13 Plotly charts."""

    resource_id: str
    resource_category: str
    physical_start_m: float
    physical_end_m: float
    leader_start_s: float
    leader_end_s: float
    follower_unshifted_start_s: float
    follower_unshifted_end_s: float
    follower_shifted_start_s: float
    follower_shifted_end_s: float
    is_controlling: bool
    required_headway_s: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HeadwayResult:
    """P08-RES-001 & § 23: Complete standard contract for a pairwise technical headway result."""

    run_id: str
    analysis_id: str
    scenario_id: str
    leader_service_id: str
    follower_service_id: str
    reference_point_id: str
    running_direction: RunningDirection
    signalling_system: str
    headway_definition: str
    headway_s: float
    minimum_dispatch_headway_s: float
    controlling_conflicts: List[ResourceConflict] = field(default_factory=list)
    conflict_ranking: List[ResourceConflict] = field(default_factory=list)
    blocking_intervals: List[ResourceBlockingInterval] = field(default_factory=list)
    longest_occupations: List[ResourceBlockingInterval] = field(default_factory=list)
    stairway_data: List[StairwayBlockData] = field(default_factory=list)
    verification_status: HeadwayValidationStatus = HeadwayValidationStatus.VALID
    numerical_tolerance_s: float = 0.1
    input_configuration_hash: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def controlling_bottleneck_description(self) -> str:
        """Formatted description of the primary governing bottleneck."""
        if not self.controlling_conflicts:
            return "MINIMUM_DISPATCH_LIMIT"
        c = self.controlling_conflicts[0]
        return f"{c.bottleneck_type or 'RESOURCE'} ({c.leader_resource_id})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "analysis_id": self.analysis_id,
            "scenario_id": self.scenario_id,
            "leader_service_id": self.leader_service_id,
            "follower_service_id": self.follower_service_id,
            "reference_point_id": self.reference_point_id,
            "running_direction": self.running_direction.value,
            "signalling_system": self.signalling_system,
            "headway_definition": self.headway_definition,
            "headway_s": round(self.headway_s, 3),
            "minimum_dispatch_headway_s": round(self.minimum_dispatch_headway_s, 3),
            "verification_status": self.verification_status.value,
            "controlling_bottleneck": self.controlling_bottleneck_description,
            "controlling_conflicts_count": len(self.controlling_conflicts),
            "total_conflicts_count": len(self.conflict_ranking),
        }


@dataclass
class MixedTrafficHeadwayMatrix:
    """P08-MIX-001 to 007: Directional mixed-traffic headway matrix across N service types."""

    matrix_id: str
    running_direction: RunningDirection
    service_ids: List[str]
    headway_values_s: Dict[Tuple[str, str], float] = field(default_factory=dict)
    controlling_bottlenecks: Dict[Tuple[str, str], str] = field(default_factory=dict)
    results: Dict[Tuple[str, str], HeadwayResult] = field(default_factory=dict)

    def get_headway(self, leader_id: str, follower_id: str) -> Optional[float]:
        return self.headway_values_s.get((leader_id, follower_id))

    def to_dataframe(self) -> pd.DataFrame:
        """P08-MIX-002: Matrix orientation: rows = leader services, columns = follower services."""
        data: Dict[str, List[Optional[float]]] = {}
        for col_follower in self.service_ids:
            col_vals = []
            for row_leader in self.service_ids:
                hw = self.headway_values_s.get((row_leader, col_follower))
                col_vals.append(round(hw, 2) if hw is not None else None)
            data[col_follower] = col_vals
        return pd.DataFrame(data, index=self.service_ids)
