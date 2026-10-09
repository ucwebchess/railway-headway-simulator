"""Physical railway network graph implementation using NetworkX.

Strictly satisfies:
- P02-INF-001: Physical railway graph with nodes, links, and track characteristics.
- P02-INF-002: NetworkX MultiDiGraph supporting parallel physical links.
- P02-INF-003: No artificial link duplication; single physical identity for both directions.
- P02-INF-004: Validates physical connectivity between nodes and links.
"""

from typing import Dict, Iterator, List, Optional, Set, Tuple
import networkx as nx

from headway.core.exceptions import InfrastructureError
from headway.data.canonical import (
    InfrastructureModel,
    Node,
    NodeType,
    Track,
    TrackDirectionality,
    TrackLink,
)
from headway.infrastructure.direction import DirectionPolicy, RunningDirection


class NetworkTopologyError(InfrastructureError):
    """Raised when railway network graph topology or connectivity is invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_TOPOLOGY"


class PhysicalNetworkGraph:
    """Directed multi-graph representing the physical railway track network.

    Nodes represent physical connection points, buffer stops, or junctions.
    Edges represent physical track links with positive length, gradient, and curvature.
    Reverse traversal views are provided without duplicating physical links.
    """

    def __init__(self, infrastructure: Optional[InfrastructureModel] = None) -> None:
        self._nodes: Dict[str, Node] = {}
        self._tracks: Dict[str, Track] = {}
        self._links: Dict[str, TrackLink] = {}
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()

        if infrastructure:
            self.load_from_canonical(infrastructure)

    def load_from_canonical(self, infrastructure: InfrastructureModel) -> None:
        """Populate the network graph from a canonical InfrastructureModel."""
        for node in infrastructure.nodes:
            self.add_node(node)

        for track in infrastructure.tracks:
            self.add_track(track)

        for link in infrastructure.track_links:
            self.add_link(link)

    def add_node(self, node: Node) -> None:
        """Register a physical node in the network."""
        if node.node_id in self._nodes:
            raise NetworkTopologyError(
                f"Duplicate node ID detected: '{node.node_id}'.",
                context={"node_id": node.node_id},
            )
        self._nodes[node.node_id] = node
        self._graph.add_node(
            node.node_id,
            node_type=node.node_type.value,
            description=node.description,
        )

    def add_track(self, track: Track) -> None:
        """Register a track line definition."""
        self._tracks[track.track_id] = track

    def add_link(self, link: TrackLink) -> None:
        """Register a physical track link and create directed traversal views.

        Invariant: Link length must be strictly positive.
        Invariant: Both nodes must exist.
        Invariant: Physical link is stored once; reverse directed edge is added if permitted.
        """
        if link.link_id in self._links:
            raise NetworkTopologyError(
                f"Duplicate link ID detected: '{link.link_id}'.",
                context={"link_id": link.link_id},
            )

        if link.length_m <= 0:
            raise NetworkTopologyError(
                f"Link '{link.link_id}' length must be strictly positive (got {link.length_m} m).",
                context={"link_id": link.link_id, "length_m": link.length_m},
            )

        if link.start_node_id not in self._nodes:
            raise NetworkTopologyError(
                f"Link '{link.link_id}' references nonexistent start node '{link.start_node_id}'.",
                context={"link_id": link.link_id, "start_node_id": link.start_node_id},
            )

        if link.end_node_id not in self._nodes:
            raise NetworkTopologyError(
                f"Link '{link.link_id}' references nonexistent end node '{link.end_node_id}'.",
                context={"link_id": link.link_id, "end_node_id": link.end_node_id},
            )

        track = self._tracks.get(link.track_id)
        directionality = track.directionality if track else TrackDirectionality.BIDIRECTIONAL

        self._links[link.link_id] = link

        # Add forward traversal edge if allowed
        if DirectionPolicy.is_traversal_permitted(directionality, RunningDirection.FORWARD):
            self._graph.add_edge(
                link.start_node_id,
                link.end_node_id,
                key=f"{link.link_id}_FWD",
                link_id=link.link_id,
                direction=RunningDirection.FORWARD,
                length_m=link.length_m,
                link=link,
            )

        # Add reverse traversal edge if allowed (pointing end_node -> start_node)
        if DirectionPolicy.is_traversal_permitted(directionality, RunningDirection.REVERSE):
            self._graph.add_edge(
                link.end_node_id,
                link.start_node_id,
                key=f"{link.link_id}_REV",
                link_id=link.link_id,
                direction=RunningDirection.REVERSE,
                length_m=link.length_m,
                link=link,
            )

    @property
    def nodes(self) -> Dict[str, Node]:
        return dict(self._nodes)

    @property
    def tracks(self) -> Dict[str, Track]:
        return dict(self._tracks)

    @property
    def links(self) -> Dict[str, TrackLink]:
        return dict(self._links)

    @property
    def graph(self) -> nx.MultiDiGraph:
        return self._graph

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def get_track(self, track_id: str) -> Optional[Track]:
        return self._tracks.get(track_id)

    def get_link(self, link_id: str) -> Optional[TrackLink]:
        return self._links.get(link_id)

    def get_track_directionality(self, track_id: str) -> TrackDirectionality:
        track = self._tracks.get(track_id)
        return track.directionality if track else TrackDirectionality.BIDIRECTIONAL

    def get_links_between(
        self, u: str, v: str, direction: Optional[RunningDirection] = None
    ) -> List[Tuple[TrackLink, RunningDirection]]:
        """Return all links permitting traversal directly from node u to node v."""
        results: List[Tuple[TrackLink, RunningDirection]] = []
        if not self._graph.has_edge(u, v):
            return results

        edge_data = self._graph.get_edge_data(u, v)
        for key, attrs in edge_data.items():
            dir_attr = attrs.get("direction")
            if direction is None or dir_attr == direction:
                results.append((attrs["link"], dir_attr))
        return results

    def get_outgoing_traversals(
        self, node_id: str, direction: Optional[RunningDirection] = None
    ) -> List[Tuple[TrackLink, RunningDirection, str]]:
        """Return all outgoing traversals from node_id: (link, direction, target_node)."""
        if node_id not in self._graph:
            return []
        results = []
        for _, target, key, attrs in self._graph.out_edges(node_id, keys=True, data=True):
            dir_attr = attrs.get("direction")
            if direction is None or dir_attr == direction:
                results.append((attrs["link"], dir_attr, target))
        return results

    def get_incoming_traversals(
        self, node_id: str, direction: Optional[RunningDirection] = None
    ) -> List[Tuple[TrackLink, RunningDirection, str]]:
        """Return all incoming traversals into node_id: (link, direction, source_node)."""
        if node_id not in self._graph:
            return []
        results = []
        for source, _, key, attrs in self._graph.in_edges(node_id, keys=True, data=True):
            dir_attr = attrs.get("direction")
            if direction is None or dir_attr == direction:
                results.append((attrs["link"], dir_attr, source))
        return results
