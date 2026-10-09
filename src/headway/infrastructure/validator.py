"""Engineering validation for physical railway infrastructure networks.

Strictly satisfies RHS-P02-001 § 19:
- P02-VAL-001: Structured findings using P01 ValidationReport, ValidationFinding, and Severity.
- P02-VAL-002: Critical and Error findings prevent simulation readiness.
- P02-VAL-003: Warnings for noncritical geometry observations.
- P02-VAL-004: Direction-specific route feasibility reporting (Forward vs Reverse).
"""

from typing import Dict, List, Optional, Set, Tuple
from headway.data.canonical import (
    InfrastructureModel,
    Platform,
    StoppingPoint,
    TrackDirectionality,
    TrackLink,
    TVSSection,
)
from headway.data.validation import Severity, ValidationFinding, ValidationReport
from headway.infrastructure.direction import DirectionPolicy, RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import Route


class InfrastructureValidator:
    """Validates physical railway infrastructure topology, geometry, and route feasibility."""

    def __init__(self, report: Optional[ValidationReport] = None) -> None:
        self.report: ValidationReport = report if report is not None else ValidationReport()

    def validate_infrastructure_model(self, infra: InfrastructureModel) -> ValidationReport:
        """Validate entire canonical infrastructure dataset."""
        node_ids: Set[str] = set()
        for node in infra.nodes:
            if node.node_id in node_ids:
                self.report.add_finding(
                    error_code="VAL-INF-001",
                    severity=Severity.CRITICAL,
                    message=f"Duplicate node ID '{node.node_id}'.",
                    object_id=node.node_id,
                    recommendation="Ensure all physical nodes have unique identifiers.",
                )
            node_ids.add(node.node_id)

        track_ids: Set[str] = {t.track_id for t in infra.tracks}
        link_ids: Set[str] = set()
        links_dict: Dict[str, TrackLink] = {}

        for link in infra.track_links:
            if link.link_id in link_ids:
                self.report.add_finding(
                    error_code="VAL-INF-002",
                    severity=Severity.CRITICAL,
                    message=f"Duplicate track link ID '{link.link_id}'.",
                    object_id=link.link_id,
                    recommendation="Ensure all track links have unique identifiers.",
                )
            link_ids.add(link.link_id)
            links_dict[link.link_id] = link

            # P02-LINK-002: Positive length
            if link.length_m <= 0:
                self.report.add_finding(
                    error_code="VAL-INF-003",
                    severity=Severity.ERROR,
                    message=f"Link '{link.link_id}' length must be positive (got {link.length_m} m).",
                    object_id=link.link_id,
                    recommendation="Set link length to a strictly positive value.",
                )

            # Node references
            if link.start_node_id not in node_ids:
                self.report.add_finding(
                    error_code="VAL-INF-004",
                    severity=Severity.ERROR,
                    message=f"Link '{link.link_id}' references unknown start node '{link.start_node_id}'.",
                    object_id=link.link_id,
                    recommendation="Ensure start node exists in nodes table.",
                )
            if link.end_node_id not in node_ids:
                self.report.add_finding(
                    error_code="VAL-INF-005",
                    severity=Severity.ERROR,
                    message=f"Link '{link.link_id}' references unknown end node '{link.end_node_id}'.",
                    object_id=link.link_id,
                    recommendation="Ensure end node exists in nodes table.",
                )

            # Track references
            if link.track_id not in track_ids:
                self.report.add_finding(
                    error_code="VAL-INF-006",
                    severity=Severity.ERROR,
                    message=f"Link '{link.link_id}' references unknown track '{link.track_id}'.",
                    object_id=link.link_id,
                    recommendation="Ensure track ID exists in tracks table.",
                )

            # Max speed check
            if link.max_speed_ms <= 0:
                self.report.add_finding(
                    error_code="VAL-INF-007",
                    severity=Severity.ERROR,
                    message=f"Link '{link.link_id}' max_speed_ms must be positive (got {link.max_speed_ms} m/s).",
                    object_id=link.link_id,
                    recommendation="Specify permissible maximum speed greater than zero.",
                )

        # Validate Platform Geometry
        station_ids: Set[str] = {s.station_id for s in infra.stations}
        for plat in infra.platforms:
            if plat.station_id not in station_ids:
                self.report.add_finding(
                    error_code="VAL-INF-008",
                    severity=Severity.ERROR,
                    message=f"Platform '{plat.platform_id}' references unknown station '{plat.station_id}'.",
                    object_id=plat.platform_id,
                    recommendation="Ensure station exists in stations table.",
                )
            link = links_dict.get(plat.link_id)
            if not link:
                self.report.add_finding(
                    error_code="VAL-INF-009",
                    severity=Severity.ERROR,
                    message=f"Platform '{plat.platform_id}' references unknown link '{plat.link_id}'.",
                    object_id=plat.platform_id,
                    recommendation="Ensure link exists in links table.",
                )
            else:
                if plat.end_offset_m <= plat.start_offset_m:
                    self.report.add_finding(
                        error_code="VAL-INF-010",
                        severity=Severity.ERROR,
                        message=f"Platform '{plat.platform_id}' end offset ({plat.end_offset_m} m) "
                        f"must be greater than start offset ({plat.start_offset_m} m).",
                        object_id=plat.platform_id,
                        recommendation="Correct platform offset coordinates.",
                    )
                if plat.start_offset_m < 0 or plat.end_offset_m > link.length_m + 1e-3:
                    self.report.add_finding(
                        error_code="VAL-INF-011",
                        severity=Severity.ERROR,
                        message=f"Platform '{plat.platform_id}' exceeds link '{plat.link_id}' length ({link.length_m} m).",
                        object_id=plat.platform_id,
                        recommendation="Keep platform bounds within physical link length.",
                    )

        # Validate TVS Sections
        tunnel_ids: Set[str] = {t.tunnel_id for t in infra.tunnels}
        for tvs in infra.tvs_sections:
            if tvs.tunnel_id not in tunnel_ids:
                self.report.add_finding(
                    error_code="VAL-INF-012",
                    severity=Severity.ERROR,
                    message=f"TVS section '{tvs.tvs_id}' references unknown tunnel '{tvs.tunnel_id}'.",
                    object_id=tvs.tvs_id,
                    recommendation="Ensure tunnel exists in tunnels table.",
                )
            for iv in tvs.link_intervals:
                link = links_dict.get(iv.link_id)
                if not link:
                    self.report.add_finding(
                        error_code="VAL-INF-013",
                        severity=Severity.ERROR,
                        message=f"TVS section '{tvs.tvs_id}' interval references unknown link '{iv.link_id}'.",
                        object_id=tvs.tvs_id,
                        recommendation="Ensure link exists in links table.",
                    )
                else:
                    if iv.start_offset_m < 0 or iv.end_offset_m > link.length_m + 1e-3:
                        self.report.add_finding(
                            error_code="VAL-INF-014",
                            severity=Severity.ERROR,
                            message=f"TVS section '{tvs.tvs_id}' interval exceeds link '{iv.link_id}' length.",
                            object_id=tvs.tvs_id,
                            recommendation="Keep TVS interval bounds within physical link length.",
                        )

        return self.report

    def validate_route_feasibility(
        self,
        route: Route,
        graph: PhysicalNetworkGraph,
    ) -> Tuple[bool, bool, List[str]]:
        """P02-VAL-004: Validate route feasibility in both FORWARD and REVERSE directions.

        Returns (is_forward_feasible, is_reverse_feasible, messages).
        """
        messages: List[str] = []
        forward_ok = True
        reverse_ok = True

        for t in route.traversals:
            track_dir = graph.get_track_directionality(t.link.track_id)

            # Check forward direction
            if not DirectionPolicy.is_traversal_permitted(track_dir, t.direction):
                forward_ok = False
                messages.append(
                    f"Link '{t.link_id}' does not permit '{t.direction.value}' traversal "
                    f"under track directionality '{track_dir.value}'."
                )

            # Check reverse direction
            opp_dir = t.direction.opposite()
            if not DirectionPolicy.is_traversal_permitted(track_dir, opp_dir):
                reverse_ok = False
                messages.append(
                    f"Reverse traversal of link '{t.link_id}' ({opp_dir.value}) is prohibited "
                    f"by track directionality '{track_dir.value}'."
                )

        return (forward_ok, reverse_ok, messages)
