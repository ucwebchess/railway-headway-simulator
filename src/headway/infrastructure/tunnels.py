"""Tunnel and Tunnel Ventilation Section (TVS) physical geometry models.

Strictly satisfies RHS-P02-001 § 16:
- P02-TVS-001 & 002: Tunnel and TVS physical geometry independent of signalling blocks.
- P02-TVS-003 & 004: Multiple TVS sections and multi-track tunnel support.
- P02-TVS-005: Preserves shared resource group definitions.
- P02-TVS-006 & BENCH-P02-009: Reverse TVS mapping (physical boundaries invariant; entry/exit reverse).
- P02-TVS-007: TVS physical length calculation from geometry.
- P02-TVS-008: No TVS occupancy authorization or state engine in P02.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError
from headway.data.canonical import InfrastructureModel, ResourceInterval, Tunnel, TVSSection
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route


class TVSGeometryError(InfrastructureError):
    """Raised when tunnel or TVS section geometry is invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_TVS_GEOMETRY"


@dataclass(frozen=True)
class RouteTVSSection:
    """A TVS section mapped along a specific Route."""

    tvs: TVSSection
    route_entry_distance_m: float
    route_exit_distance_m: float
    physical_length_m: float
    running_direction: RunningDirection
    tunnel_name: Optional[str] = None

    @property
    def tvs_id(self) -> str:
        return self.tvs.tvs_id

    @property
    def holding_signal_id(self) -> Optional[str]:
        return self.tvs.holding_signal_id

    @property
    def max_train_occupancy(self) -> int:
        return self.tvs.max_train_occupancy

    def contains_route_distance(self, s: float) -> bool:
        """Check if cumulative route distance s is inside this TVS section."""
        min_s = min(self.route_entry_distance_m, self.route_exit_distance_m)
        max_s = max(self.route_entry_distance_m, self.route_exit_distance_m)
        return (min_s - 1e-4) <= s <= (max_s + 1e-4)


class TunnelTVSModel:
    """Manages physical tunnels, TVS section geometry, and direction-dependent boundary resolution."""

    def __init__(self, infrastructure: Optional[InfrastructureModel] = None) -> None:
        self.tunnels: Dict[str, Tunnel] = {}
        self.tvs_sections: Dict[str, TVSSection] = {}

        if infrastructure:
            for t in infrastructure.tunnels:
                self.tunnels[t.tunnel_id] = t
            for tvs in infrastructure.tvs_sections:
                self.tvs_sections[tvs.tvs_id] = tvs

    def add_tunnel(self, tunnel: Tunnel) -> None:
        self.tunnels[tunnel.tunnel_id] = tunnel

    def add_tvs_section(self, tvs: TVSSection) -> None:
        if not tvs.link_intervals:
            raise TVSGeometryError(
                f"TVS section '{tvs.tvs_id}' must have at least one link interval.",
                context={"tvs_id": tvs.tvs_id},
            )
        self.tvs_sections[tvs.tvs_id] = tvs

    def calculate_tvs_length_m(self, tvs_id: str) -> float:
        """P02-TVS-007: Calculate TVS physical length from interval geometry."""
        tvs = self.tvs_sections.get(tvs_id)
        if not tvs:
            raise TVSGeometryError(f"TVS section '{tvs_id}' not found.", context={"tvs_id": tvs_id})
        return sum(abs(interval.end_offset_m - interval.start_offset_m) for interval in tvs.link_intervals)

    def resolve_route_tvs_sections(self, route: Route) -> List[RouteTVSSection]:
        """P02-TVS-006 & P02-DIR-011: Map TVS sections intersecting the route.

        Determines correct entry and exit boundaries according to running direction.
        Physical boundaries remain invariant.
        """
        resolved: List[RouteTVSSection] = []

        for tvs_id, tvs in self.tvs_sections.items():
            # Check which TVS intervals intersect the route
            tvs_link_ids = {iv.link_id for iv in tvs.link_intervals}
            route_link_ids = set(route.link_ids)

            intersecting_links = tvs_link_ids.intersection(route_link_ids)
            if not intersecting_links:
                continue

            entry_distances: List[float] = []
            exit_distances: List[float] = []

            for traversal in route.traversals:
                for iv in tvs.link_intervals:
                    if iv.link_id == traversal.link_id:
                        # Physical boundaries on this link
                        x_start = iv.start_offset_m
                        x_end = iv.end_offset_m

                        if traversal.direction.is_forward:
                            # Forward: entry is at x_start, exit is at x_end
                            s_in = traversal.physical_offset_to_route_distance(x_start)
                            s_out = traversal.physical_offset_to_route_distance(x_end)
                        else:
                            # Reverse: entry is at x_end, exit is at x_start
                            # BENCH-P02-009: Entry and exit reverse
                            s_in = traversal.physical_offset_to_route_distance(x_end)
                            s_out = traversal.physical_offset_to_route_distance(x_start)

                        entry_distances.append(s_in)
                        exit_distances.append(s_out)

            if entry_distances and exit_distances:
                route_entry = min(entry_distances)
                route_exit = max(exit_distances)
                tunnel = self.tunnels.get(tvs.tunnel_id)
                t_name = tunnel.name if tunnel else None

                # Primary direction of traversal
                first_traversal = route.traversals[0]

                resolved.append(
                    RouteTVSSection(
                        tvs=tvs,
                        route_entry_distance_m=route_entry,
                        route_exit_distance_m=route_exit,
                        physical_length_m=self.calculate_tvs_length_m(tvs_id),
                        running_direction=first_traversal.direction,
                        tunnel_name=t_name,
                    )
                )

        resolved.sort(key=lambda s: s.route_entry_distance_m)
        return resolved
