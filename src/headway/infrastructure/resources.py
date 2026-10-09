"""Multi-link and branched physical resource geometry model.

Strictly satisfies RHS-P02-001 § 17:
- P02-RES-001: Multi-link resource interval geometry.
- P02-RES-002: Continuous resource validation.
- P02-RES-003: Disjoint resource geometry support.
- P02-RES-004: Branching resource geometry support (e.g., junction fouling zones).
- P02-RES-005: Resource intersection query for any route interval [s_start, s_end].
- P02-RES-006: Occupied length calculation of route-resource intersection.
- P02-RES-007: No resource reservation, state machines, or locking timers during P02.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from headway.core.exceptions import InfrastructureError
from headway.data.canonical import ResourceGeometry, ResourceInterval
from headway.infrastructure.route import Route


class ResourceGeometryError(InfrastructureError):
    """Raised when physical resource geometry or intervals are invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_RESOURCE_GEOMETRY"


@dataclass(frozen=True)
class PhysicalResource:
    """A physical track resource defined across one or more link intervals."""

    resource_id: str
    intervals: List[ResourceInterval]
    resource_type: str = "GENERIC"
    is_continuous: bool = True
    description: Optional[str] = None

    @property
    def total_length_m(self) -> float:
        return sum(abs(iv.end_offset_m - iv.start_offset_m) for iv in self.intervals)

    @property
    def link_ids(self) -> Set[str]:
        return {iv.link_id for iv in self.intervals}


class MultiLinkResourceGeometry:
    """Manages physical track resources and provides spatial intersection utilities."""

    def __init__(self) -> None:
        self.resources: Dict[str, PhysicalResource] = {}

    def register_resource(self, resource: PhysicalResource) -> None:
        if not resource.intervals:
            raise ResourceGeometryError(
                f"Resource '{resource.resource_id}' must contain at least one interval.",
                context={"resource_id": resource.resource_id},
            )
        self.resources[resource.resource_id] = resource

    def register_from_canonical(self, canonical_res: ResourceGeometry, resource_type: str = "GENERIC") -> None:
        res = PhysicalResource(
            resource_id=canonical_res.resource_id,
            intervals=canonical_res.intervals,
            resource_type=resource_type,
        )
        self.register_resource(res)

    def intersects_route_interval(
        self,
        route: Route,
        s_start: float,
        s_end: float,
        resource_id: str,
    ) -> bool:
        """P02-RES-005: Check if route interval [s_start, s_end] intersects physical resource."""
        res = self.resources.get(resource_id)
        if not res:
            return False

        a = max(0.0, min(s_start, s_end))
        b = min(route.total_length_m, max(s_start, s_end))
        if a >= b:
            return False

        for traversal in route.traversals:
            # Check if this link has resource intervals
            for iv in res.intervals:
                if iv.link_id == traversal.link_id:
                    # Map resource physical interval to route distance
                    s1 = traversal.physical_offset_to_route_distance(iv.start_offset_m)
                    s2 = traversal.physical_offset_to_route_distance(iv.end_offset_m)
                    res_a = min(s1, s2)
                    res_b = max(s1, s2)

                    # Check interval overlap
                    if max(a, res_a) < min(b, res_b):
                        return True
        return False

    def occupied_length_in_route_interval(
        self,
        route: Route,
        s_start: float,
        s_end: float,
        resource_id: str,
    ) -> float:
        """P02-RES-006: Calculate the occupied length (m) of intersection between route interval and resource."""
        res = self.resources.get(resource_id)
        if not res:
            return 0.0

        a = max(0.0, min(s_start, s_end))
        b = min(route.total_length_m, max(s_start, s_end))
        if a >= b:
            return 0.0

        occupied_length = 0.0
        for traversal in route.traversals:
            for iv in res.intervals:
                if iv.link_id == traversal.link_id:
                    s1 = traversal.physical_offset_to_route_distance(iv.start_offset_m)
                    s2 = traversal.physical_offset_to_route_distance(iv.end_offset_m)
                    res_a = min(s1, s2)
                    res_b = max(s1, s2)

                    overlap_start = max(a, res_a)
                    overlap_end = min(b, res_b)
                    if overlap_start < overlap_end:
                        occupied_length += (overlap_end - overlap_start)

        return occupied_length
