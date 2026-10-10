"""Leader–follower resource conflict detection and temporal requirement evaluation.

Strictly satisfies RHS-P08-001:
- § 8: Resource Conflict Model (P08-CON-001 to P08-CON-005).
- § 9: Analytical Temporal Shift Calculation (P08-HW-006 to P08-HW-010).
- Supports identical exclusive resources, shared conflict groups, interlocking routes,
  cross-track shared TVS groups, whole-tunnel restrictions, and residual rear occupation.
- Support for both FORWARD and REVERSE railway movements.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from headway.analysis.blocking_time import BlockingTimeline, ResourceBlockingInterval
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory


class ConflictType(str, Enum):
    """P08-CON: Classification of pairwise resource conflicts."""

    IDENTICAL_RESOURCE = "IDENTICAL_RESOURCE"
    SHARED_CONFLICT_GROUP = "SHARED_CONFLICT_GROUP"
    INTERLOCKING_CONFLICT = "INTERLOCKING_CONFLICT"
    STATION_PLATFORM_CONFLICT = "STATION_PLATFORM_CONFLICT"
    RESIDUAL_REAR_CONFLICT = "RESIDUAL_REAR_CONFLICT"
    WHOLE_TUNNEL_CONFLICT = "WHOLE_TUNNEL_CONFLICT"
    OTHER_CONFLICT = "OTHER_CONFLICT"


@dataclass
class ResourceConflict:
    """P08-CON-003 & P08-HW-006: Ordered conflict requirement between leader and follower."""

    conflict_id: str
    leader_usage: ResourceBlockingInterval
    follower_usage: ResourceBlockingInterval
    conflict_type: ConflictType
    leader_release_time_s: float
    follower_start_time_s: float
    required_headway_s: float
    margin_s: float = 0.0
    slack_s: float = 0.0
    is_controlling: bool = False
    physical_location_m: Optional[float] = None
    bottleneck_type: Optional[str] = None
    description: Optional[str] = None

    @property
    def leader_resource_id(self) -> str:
        return self.leader_usage.resource_id

    @property
    def follower_resource_id(self) -> str:
        return self.follower_usage.resource_id


class ConflictDetector:
    """Evaluates standalone leader and follower timelines to detect all incompatible resource pairs."""

    def __init__(
        self,
        shared_groups: Optional[Dict[str, Set[str]]] = None,
        conflicting_routes: Optional[Dict[str, Set[str]]] = None,
        tunnel_to_tvs: Optional[Dict[str, Set[str]]] = None,
        whole_tunnel_tvs_ids: Optional[Set[str]] = None,
        planning_margin_s: float = 0.0,
    ) -> None:
        self.shared_groups = shared_groups or {}
        self.conflicting_routes = conflicting_routes or {}
        self.tunnel_to_tvs = tunnel_to_tvs or {}
        self.whole_tunnel_tvs_ids = whole_tunnel_tvs_ids or set()
        self.planning_margin_s = planning_margin_s

        # Invert shared groups for fast lookup: resource_id -> set of peer resource_ids
        self.resource_to_peer_resources: Dict[str, Set[str]] = {}
        for grp_id, r_ids in self.shared_groups.items():
            for r in r_ids:
                if r not in self.resource_to_peer_resources:
                    self.resource_to_peer_resources[r] = set()
                self.resource_to_peer_resources[r].update(r_ids - {r})

    def detect_conflicts(
        self,
        leader_timeline: BlockingTimeline,
        follower_timeline: BlockingTimeline,
        reference_point_offset_m: Optional[float] = None,
    ) -> List[ResourceConflict]:
        """P08-CON: Identifies all ordered conflict pairs and computes H_{u,v}."""
        conflicts: List[ResourceConflict] = []
        seq = 1

        leader_intervals = leader_timeline.sorted_by_start()
        follower_intervals = follower_timeline.sorted_by_start()

        for l_iv in leader_intervals:
            for f_iv in follower_intervals:
                c_type: Optional[ConflictType] = None
                desc: Optional[str] = None

                # 1. Residual rear occupation conflict
                if (
                    l_iv.resource_id == f_iv.resource_id
                    and l_iv.decomposition
                    and l_iv.decomposition.residual_rear_time_s > 0
                ):
                    c_type = ConflictType.RESIDUAL_REAR_CONFLICT
                    desc = f"Residual stationary rear occupation of upstream resource '{l_iv.resource_id}'"

                # 2. Identical exclusive resource
                elif l_iv.resource_id == f_iv.resource_id:
                    c_type = ConflictType.IDENTICAL_RESOURCE
                    desc = f"Direct exclusive occupancy of resource '{l_iv.resource_id}'"

                # 2. Shared conflict group (e.g. cross-track shared TVS)
                elif l_iv.resource_id in self.resource_to_peer_resources.get(f_iv.resource_id, set()):
                    c_type = ConflictType.SHARED_CONFLICT_GROUP
                    desc = f"Shared conflict group between '{l_iv.resource_id}' and '{f_iv.resource_id}'"

                # 3. Interlocking route conflict
                elif (
                    l_iv.resource_id in self.conflicting_routes.get(f_iv.resource_id, set())
                    or f_iv.resource_id in self.conflicting_routes.get(l_iv.resource_id, set())
                ):
                    c_type = ConflictType.INTERLOCKING_CONFLICT
                    desc = f"Interlocking route conflict between '{l_iv.resource_id}' and '{f_iv.resource_id}'"

                # 4. Whole-tunnel exclusivity
                elif (
                    l_iv.resource_id in self.whole_tunnel_tvs_ids
                    and f_iv.resource_id in self.whole_tunnel_tvs_ids
                ):
                    # Check if they share the same tunnel
                    for tun_id, tvs_set in self.tunnel_to_tvs.items():
                        if l_iv.resource_id in tvs_set and f_iv.resource_id in tvs_set:
                            c_type = ConflictType.WHOLE_TUNNEL_CONFLICT
                            desc = f"Whole-tunnel exclusivity in tunnel '{tun_id}' ('{l_iv.resource_id}' vs '{f_iv.resource_id}')"
                            break

                # 5. Residual rear occupation conflict
                elif (
                    l_iv.decomposition
                    and l_iv.decomposition.residual_rear_time_s > 0
                    and l_iv.resource_id == f_iv.resource_id
                ):
                    c_type = ConflictType.RESIDUAL_REAR_CONFLICT
                    desc = f"Residual stationary rear occupation of upstream resource '{l_iv.resource_id}'"

                if c_type is not None:
                    # P08-HW-006: H_{u,v} = t_{leader-release, u} - t_{follower-start, v}
                    req_hw = (l_iv.end_time_s - f_iv.start_time_s) + self.planning_margin_s

                    conf = ResourceConflict(
                        conflict_id=f"CONF_{seq:04d}",
                        leader_usage=l_iv,
                        follower_usage=f_iv,
                        conflict_type=c_type,
                        leader_release_time_s=round(l_iv.end_time_s, 6),
                        follower_start_time_s=round(f_iv.start_time_s, 6),
                        required_headway_s=round(req_hw, 6),
                        margin_s=self.planning_margin_s,
                        physical_location_m=l_iv.physical_start_offset_m or reference_point_offset_m,
                        description=desc,
                    )
                    conflicts.append(conf)
                    seq += 1

        return conflicts
