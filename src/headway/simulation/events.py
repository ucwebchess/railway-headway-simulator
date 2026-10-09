"""Infrastructure boundary crossing events and localization.

Strictly satisfies RHS-P04-001 § 15:
- P04-EVT-001: Accurate timestamp recording via interval localization.
- P04-EVT-002: Distinct tracking of train-front and train-rear crossing events.
- P04-EVT-003: Pure geometric event detection without resource reservation (P05).
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from headway.infrastructure.route import Route
from headway.infrastructure.tunnels import TunnelTVSModel


class CrossingEventType(str, Enum):
    """Classification of infrastructure boundary crossing events."""

    LINK_FRONT_ENTER = "LINK_FRONT_ENTER"
    LINK_FRONT_EXIT = "LINK_FRONT_EXIT"
    LINK_REAR_ENTER = "LINK_REAR_ENTER"
    LINK_REAR_EXIT = "LINK_REAR_EXIT"
    STATION_ARRIVED = "STATION_ARRIVED"
    STATION_DEPARTED = "STATION_DEPARTED"
    PLATFORM_FRONT_ENTER = "PLATFORM_FRONT_ENTER"
    PLATFORM_REAR_EXIT = "PLATFORM_REAR_EXIT"
    TUNNEL_FRONT_ENTER = "TUNNEL_FRONT_ENTER"
    TUNNEL_REAR_EXIT = "TUNNEL_REAR_EXIT"
    TVS_FRONT_ENTER = "TVS_FRONT_ENTER"
    TVS_REAR_EXIT = "TVS_REAR_EXIT"
    SPEED_RESTRICTION_ENTER = "SPEED_RESTRICTION_ENTER"


@dataclass(frozen=True)
class BoundaryEvent:
    """Exact localized geometric crossing event."""

    event_type: CrossingEventType
    timestamp_s: float
    route_distance_m: float
    train_id: str
    is_front: bool
    speed_ms: float
    link_id: Optional[str] = None
    physical_coordinate_m: Optional[float] = None
    feature_id: Optional[str] = None
    description: Optional[str] = None


class BoundaryEventDetector:
    """Detects and localizes geometric boundary crossings occurring within an integration step."""

    def __init__(
        self,
        route: Route,
        train_id: str,
        train_length_m: float,
        tvs_models: Optional[List[TunnelTVSModel]] = None,
    ) -> None:
        self.route = route
        self.train_id = train_id
        self.train_length_m = train_length_m
        self.tvs_models = tvs_models or []
        self._boundary_positions: List[Tuple[float, CrossingEventType, Optional[str], Optional[str]]] = []
        self._build_static_boundaries()

    def _build_static_boundaries(self) -> None:
        """Pre-extract all geometric boundary points along the route."""
        # 1. Link boundaries
        for t in self.route.traversals:
            # Front enter
            self._boundary_positions.append(
                (t.start_distance_m, CrossingEventType.LINK_FRONT_ENTER, t.link_id, f"Front enter link {t.link_id}")
            )
            # Front exit
            self._boundary_positions.append(
                (t.end_distance_m, CrossingEventType.LINK_FRONT_EXIT, t.link_id, f"Front exit link {t.link_id}")
            )

        # 2. TVS boundaries (using direction-aware entry/exit)
        models_list = self.tvs_models if isinstance(self.tvs_models, list) else [self.tvs_models]
        for tvs_item in models_list:
            if hasattr(tvs_item, "resolve_route_tvs_sections"):
                # TunnelTVSModel instance
                sections = tvs_item.resolve_route_tvs_sections(self.route)
                for s in sections:
                    self._boundary_positions.append(
                        (s.route_entry_distance_m, CrossingEventType.TVS_FRONT_ENTER, s.tvs.tvs_id, f"Front enter TVS {s.tvs.tvs_id}")
                    )
                    self._boundary_positions.append(
                        (s.route_exit_distance_m, CrossingEventType.TVS_FRONT_EXIT, s.tvs.tvs_id, f"Front exit TVS {s.tvs.tvs_id}")
                    )
            elif hasattr(tvs_item, "route_entry_distance_m"):
                # RouteTVSSection instance
                tvs_id = getattr(getattr(tvs_item, "tvs", None), "tvs_id", "TVS")
                self._boundary_positions.append(
                    (tvs_item.route_entry_distance_m, CrossingEventType.TVS_FRONT_ENTER, tvs_id, f"Front enter TVS {tvs_id}")
                )
                self._boundary_positions.append(
                    (tvs_item.route_exit_distance_m, CrossingEventType.TVS_FRONT_EXIT, tvs_id, f"Front exit TVS {tvs_id}")
                )
            elif hasattr(tvs_item, "get_entry_distance"):
                route_dir = self.route.traversals[0].direction if self.route.traversals else RunningDirection.FORWARD
                entry_s = tvs_item.get_entry_distance(route_dir)
                exit_s = tvs_item.get_exit_distance(route_dir)
                tvs_id = getattr(tvs_item, "tvs_id", "TVS")
                self._boundary_positions.append(
                    (entry_s, CrossingEventType.TVS_FRONT_ENTER, tvs_id, f"Front enter TVS {tvs_id}")
                )
                self._boundary_positions.append(
                    (exit_s, CrossingEventType.TVS_FRONT_EXIT, tvs_id, f"Front exit TVS {tvs_id}")
                )

    def _map_coord(self, s: float) -> Tuple[Optional[str], Optional[float]]:
        try:
            traversal = self.route.get_traversal_at_distance(s)
            return (traversal.link_id, traversal.route_distance_to_physical_offset(s))
        except Exception:
            return (None, None)

    def detect_crossings(
        self,
        t0: float,
        t1: float,
        s_front0: float,
        s_front1: float,
        v0: float,
        v1: float,
    ) -> List[BoundaryEvent]:
        """P04-NUM-007 & P04-EVT-001: Localize crossings occurring in time [t0, t1]."""
        events: List[BoundaryEvent] = []
        delta_s_step = s_front1 - s_front0
        if delta_s_step <= 0 or t1 <= t0:
            return events

        s_rear0 = s_front0 - self.train_length_m
        s_rear1 = s_front1 - self.train_length_m

        for b_pos, b_type, feat_id, desc in self._boundary_positions:
            # Check front crossing
            if s_front0 <= b_pos < s_front1:
                frac = (b_pos - s_front0) / delta_s_step
                t_cross = t0 + frac * (t1 - t0)
                v_cross = v0 + frac * (v1 - v0)
                link_id, coord = self._map_coord(b_pos)

                events.append(
                    BoundaryEvent(
                        event_type=b_type,
                        timestamp_s=round(t_cross, 4),
                        route_distance_m=round(b_pos, 2),
                        train_id=self.train_id,
                        is_front=True,
                        speed_ms=round(v_cross, 3),
                        link_id=link_id,
                        physical_coordinate_m=round(coord, 2) if coord is not None else None,
                        feature_id=feat_id,
                        description=desc,
                    )
                )

            # Check rear crossing for link exit / TVS exit
            if s_rear0 <= b_pos < s_rear1:
                frac = (b_pos - s_rear0) / delta_s_step
                t_cross = t0 + frac * (t1 - t0)
                v_cross = v0 + frac * (v1 - v0)
                link_id, coord = self._map_coord(b_pos)

                # Derive rear event type
                rear_type = b_type
                if b_type == CrossingEventType.LINK_FRONT_EXIT:
                    rear_type = CrossingEventType.LINK_REAR_EXIT
                elif b_type == CrossingEventType.LINK_FRONT_ENTER:
                    rear_type = CrossingEventType.LINK_REAR_ENTER
                elif b_type == CrossingEventType.TVS_FRONT_ENTER:
                    rear_type = CrossingEventType.TVS_REAR_EXIT

                events.append(
                    BoundaryEvent(
                        event_type=rear_type,
                        timestamp_s=round(t_cross, 4),
                        route_distance_m=round(b_pos, 2),
                        train_id=self.train_id,
                        is_front=False,
                        speed_ms=round(v_cross, 3),
                        link_id=link_id,
                        physical_coordinate_m=round(coord, 2) if coord is not None else None,
                        feature_id=feat_id,
                        description=f"Rear crossed boundary at {b_pos:.1f}m",
                    )
                )

        events.sort(key=lambda e: e.timestamp_s)
        return events
