"""Railway route traversal, continuity validation, and position mapping engine.

Strictly satisfies RHS-P02-001 § 5 & § 9:
- P02-DIR-005: Cumulative route distance s strictly increases in running direction (s_start=0, s_end=L_route).
- P02-DIR-006: Reverse position mapping: x_physical = L - s_local for reverse, x_physical = s_local for forward.
- P02-ROUTE-001: Ordered link traversals with link_id, direction, sequence number.
- P02-ROUTE-002: Route continuity validation (exit node of k matches entry node of k+1).
- P02-ROUTE-003 & 004: Cumulative distance intervals and total route length calculation.
- P02-ROUTE-005: Route distance to physical link offset lookup.
- P02-ROUTE-006: Physical position to route distance lookup with occurrence indexing.
- P02-ROUTE-007: Reverse route generation with direction policy enforcement.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError
from headway.data.canonical import TrackLink
from headway.infrastructure.direction import DirectionPolicy, DirectionPolicyError, RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph


class RouteContinuityError(InfrastructureError):
    """Raised when consecutive links in a route are physically disconnected."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_ROUTE_CONTINUITY"


class PositionMappingError(InfrastructureError):
    """Raised when mapping between route distance and physical position fails."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_POSITION_MAPPING"


@dataclass(frozen=True)
class LinkTraversal:
    """Represents the traversal of a single physical track link along a route.

    The physical link itself remains immutable and singular.
    This structure defines how that physical link is traversed.
    """

    link: TrackLink
    direction: RunningDirection
    sequence_index: int
    start_distance_m: float
    end_distance_m: float

    @property
    def link_id(self) -> str:
        return self.link.link_id

    @property
    def length_m(self) -> float:
        return self.link.length_m

    @property
    def entry_node_id(self) -> str:
        """Physical node entered during this traversal."""
        return self.link.start_node_id if self.direction.is_forward else self.link.end_node_id

    @property
    def exit_node_id(self) -> str:
        """Physical node exited during this traversal."""
        return self.link.end_node_id if self.direction.is_forward else self.link.start_node_id

    def route_distance_to_physical_offset(self, s: float) -> float:
        """Map cumulative route distance s to physical offset along this link."""
        if s < self.start_distance_m - 1e-6 or s > self.end_distance_m + 1e-6:
            raise PositionMappingError(
                f"Route distance {s:.2f} m is outside traversal interval "
                f"[{self.start_distance_m:.2f}, {self.end_distance_m:.2f}] m for link '{self.link_id}'.",
                context={"link_id": self.link_id, "s": s},
            )

        # Clamp slightly to handle floating point precision at boundaries
        s_clamped = max(self.start_distance_m, min(self.end_distance_m, s))
        local_s = s_clamped - self.start_distance_m

        if self.direction.is_forward:
            return local_s
        else:
            # P02-DIR-006: Reverse position mapping: x_physical = L - local_s
            return max(0.0, min(self.length_m, self.length_m - local_s))

    def physical_offset_to_route_distance(self, offset_m: float) -> float:
        """Map physical offset along this link to cumulative route distance s."""
        if offset_m < -1e-6 or offset_m > self.length_m + 1e-6:
            raise PositionMappingError(
                f"Physical offset {offset_m:.2f} m is outside link '{self.link_id}' length {self.length_m:.2f} m.",
                context={"link_id": self.link_id, "offset_m": offset_m},
            )

        offset_clamped = max(0.0, min(self.length_m, offset_m))
        if self.direction.is_forward:
            local_s = offset_clamped
        else:
            # P02-DIR-006: Reverse mapping: local_s = L - x_physical
            local_s = self.length_m - offset_clamped

        return self.start_distance_m + local_s


class Route:
    """An ordered physical route comprising consecutive link traversals.

    Cumulative route distance s strictly starts at 0 and ends at total route length L_route.
    """

    def __init__(
        self,
        route_id: str,
        traversals: List[LinkTraversal],
        description: Optional[str] = None,
    ) -> None:
        if not traversals:
            raise RouteContinuityError(
                f"Route '{route_id}' must contain at least one link traversal.",
                context={"route_id": route_id},
            )

        self.route_id: str = route_id
        self.traversals: List[LinkTraversal] = list(traversals)
        self.description: Optional[str] = description

        self._validate_continuity()

    def _validate_continuity(self) -> None:
        """Enforce strict physical node continuity between consecutive traversals."""
        for i in range(len(self.traversals) - 1):
            curr_exit = self.traversals[i].exit_node_id
            next_entry = self.traversals[i + 1].entry_node_id
            if curr_exit != next_entry:
                raise RouteContinuityError(
                    f"Route '{self.route_id}' continuity break between traversal {i} (link '{self.traversals[i].link_id}' "
                    f"exits at '{curr_exit}') and traversal {i + 1} (link '{self.traversals[i + 1].link_id}' enters at '{next_entry}').",
                    context={
                        "route_id": self.route_id,
                        "step": i,
                        "exit_node": curr_exit,
                        "next_entry_node": next_entry,
                    },
                )

    @property
    def total_length_m(self) -> float:
        """P02-ROUTE-003: L_route = sum(L_k)."""
        return self.traversals[-1].end_distance_m

    @property
    def start_node_id(self) -> str:
        """Initial entry node of the entire route."""
        return self.traversals[0].entry_node_id

    @property
    def end_node_id(self) -> str:
        """Final exit node of the entire route."""
        return self.traversals[-1].exit_node_id

    @property
    def link_ids(self) -> List[str]:
        return [t.link_id for t in self.traversals]

    def get_traversal_at_distance(self, s: float) -> LinkTraversal:
        """Identify which link traversal covers cumulative route distance s."""
        if s < -1e-6 or s > self.total_length_m + 1e-6:
            raise PositionMappingError(
                f"Route distance {s:.2f} m is out of bounds for route '{self.route_id}' [0, {self.total_length_m:.2f}] m.",
                context={"route_id": self.route_id, "s": s},
            )

        s_clamped = max(0.0, min(self.total_length_m, s))

        for t in self.traversals:
            if t.start_distance_m <= s_clamped <= t.end_distance_m:
                return t

        # Edge case: floating point boundary at end of route
        return self.traversals[-1]

    def route_distance_to_physical(self, s: float) -> Tuple[str, float, RunningDirection]:
        """P02-ROUTE-005: Map cumulative route distance to physical (link_id, physical_offset_m, direction)."""
        traversal = self.get_traversal_at_distance(s)
        offset_m = traversal.route_distance_to_physical_offset(s)
        return (traversal.link_id, offset_m, traversal.direction)

    def physical_to_route_distance(
        self, link_id: str, offset_m: float, occurrence_index: int = 0
    ) -> float:
        """P02-ROUTE-006: Map physical position and occurrence index to cumulative route distance."""
        matching = [t for t in self.traversals if t.link_id == link_id]
        if not matching:
            raise PositionMappingError(
                f"Link '{link_id}' is not part of route '{self.route_id}'.",
                context={"route_id": self.route_id, "link_id": link_id},
            )

        if occurrence_index < 0 or occurrence_index >= len(matching):
            raise PositionMappingError(
                f"Occurrence index {occurrence_index} out of range for link '{link_id}' in route '{self.route_id}' "
                f"(found {len(matching)} occurrences).",
                context={"link_id": link_id, "occurrence_index": occurrence_index},
            )

        traversal = matching[occurrence_index]
        return traversal.physical_offset_to_route_distance(offset_m)

    def find_all_occurrences(self, link_id: str) -> List[Tuple[int, LinkTraversal]]:
        """Find all traversals of link_id along this route: list of (occurrence_index, LinkTraversal)."""
        return [(idx, t) for idx, t in enumerate(self.traversals) if t.link_id == link_id]

    def create_reverse_route(
        self,
        graph: PhysicalNetworkGraph,
        reverse_route_id: Optional[str] = None,
    ) -> "Route":
        """P02-ROUTE-007: Construct the reverse route over the identical physical infrastructure.

        Validates that every physical track link's directionality permits reverse traversal.
        Calculates cumulative distances starting from 0 to total route length.
        """
        rev_id = reverse_route_id or f"{self.route_id}_REV"
        rev_traversals: List[LinkTraversal] = []

        cumulative_s = 0.0

        # Traverse backward through traversals list
        for i, fwd_t in enumerate(reversed(self.traversals)):
            rev_dir = fwd_t.direction.opposite()

            # P02-DIR-004: Enforce track direction policy permission
            track_dir = graph.get_track_directionality(fwd_t.link.track_id)
            DirectionPolicy.validate_traversal(
                track_id=fwd_t.link.track_id,
                link_id=fwd_t.link_id,
                track_directionality=track_dir,
                traversal_direction=rev_dir,
            )

            start_s = cumulative_s
            end_s = start_s + fwd_t.length_m
            cumulative_s = end_s

            rev_traversal = LinkTraversal(
                link=fwd_t.link,
                direction=rev_dir,
                sequence_index=i,
                start_distance_m=start_s,
                end_distance_m=end_s,
            )
            rev_traversals.append(rev_traversal)

        return Route(
            route_id=rev_id,
            traversals=rev_traversals,
            description=f"Reverse route of {self.route_id}",
        )


class RouteEngine:
    """Factory and pathfinding engine for creating and managing physical railway routes."""

    def __init__(self, graph: PhysicalNetworkGraph) -> None:
        self.graph: PhysicalNetworkGraph = graph

    def build_route_from_traversals(
        self,
        route_id: str,
        steps: List[Tuple[str, RunningDirection]],
        description: Optional[str] = None,
    ) -> Route:
        """Construct a validated route from an explicit list of (link_id, RunningDirection)."""
        if not steps:
            raise RouteContinuityError("Cannot construct route from empty traversal steps.")

        traversals: List[LinkTraversal] = []
        cumulative_s = 0.0

        for seq, (link_id, direction) in enumerate(steps):
            link = self.graph.get_link(link_id)
            if not link:
                raise RouteContinuityError(
                    f"Link '{link_id}' does not exist in network graph.",
                    context={"link_id": link_id},
                )

            # Validate direction policy
            track_dir = self.graph.get_track_directionality(link.track_id)
            DirectionPolicy.validate_traversal(
                track_id=link.track_id,
                link_id=link.link_id,
                track_directionality=track_dir,
                traversal_direction=direction,
            )

            start_s = cumulative_s
            end_s = start_s + link.length_m
            cumulative_s = end_s

            traversals.append(
                LinkTraversal(
                    link=link,
                    direction=direction,
                    sequence_index=seq,
                    start_distance_m=start_s,
                    end_distance_m=end_s,
                )
            )

        return Route(route_id=route_id, traversals=traversals, description=description)

    def build_route_from_nodes(
        self,
        route_id: str,
        node_sequence: List[str],
        description: Optional[str] = None,
    ) -> Route:
        """Construct a route following an ordered sequence of physical nodes."""
        if len(node_sequence) < 2:
            raise RouteContinuityError("Node sequence must contain at least 2 nodes.")

        steps: List[Tuple[str, RunningDirection]] = []
        for i in range(len(node_sequence) - 1):
            u = node_sequence[i]
            v = node_sequence[i + 1]
            links = self.graph.get_links_between(u, v)
            if not links:
                raise RouteContinuityError(
                    f"No permissible track link connects node '{u}' to node '{v}'.",
                    context={"from_node": u, "to_node": v},
                )
            # Pick first available link
            link, direction = links[0]
            steps.append((link.link_id, direction))

        return self.build_route_from_traversals(route_id, steps, description=description)
