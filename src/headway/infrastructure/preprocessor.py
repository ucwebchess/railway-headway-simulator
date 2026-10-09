"""Infrastructure route preprocessing and caching engine.

Strictly satisfies RHS-P02-001 § 20:
- P02-PREP-001: Efficient preprocessed route data structures.
- P02-PREP-002: Direction-aware preprocessing (FORWARD vs REVERSE).
- P02-PREP-003: Baseline immutability preserved (no mutation of input canonical models).
- P02-PREP-004: Deterministic caching keyed by (dataset_hash, route_id, running_direction).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from headway.data.canonical import InfrastructureModel
from headway.infrastructure.alignment import RouteAlignmentProfile
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import Route
from headway.infrastructure.speed import RouteSpeedProfile, SpeedRestriction
from headway.infrastructure.stations import RoutePlatformStop, StationPlatformModel
from headway.infrastructure.tunnels import RouteTVSSection, TunnelTVSModel


@dataclass(frozen=True)
class RouteProfile:
    """Consolidated direction-aware engineering profile along a physical route."""

    route: Route
    running_direction: RunningDirection
    alignment: RouteAlignmentProfile
    speed_profile: RouteSpeedProfile
    stations: List[RoutePlatformStop]
    tvs_sections: List[RouteTVSSection]

    @property
    def total_length_m(self) -> float:
        return self.route.total_length_m

    def get_gradient_at(self, s: float) -> float:
        return self.alignment.get_gradient_at(s)

    def get_curvature_radius_at(self, s: float) -> Optional[float]:
        return self.alignment.get_curvature_radius_at(s)

    def get_max_speed_at(self, s: float) -> float:
        return self.speed_profile.get_max_speed_at(s)


class InfrastructurePreprocessor:
    """Preprocesses physical infrastructure datasets into fast, direction-aware RouteProfiles."""

    def __init__(
        self,
        infrastructure: InfrastructureModel,
        speed_restrictions: Optional[List[SpeedRestriction]] = None,
        dataset_hash: Optional[str] = None,
    ) -> None:
        self.infrastructure: InfrastructureModel = infrastructure
        self.speed_restrictions: List[SpeedRestriction] = list(speed_restrictions) if speed_restrictions else []
        self.dataset_hash: Optional[str] = dataset_hash

        # Initialize subsystem models
        self.graph: PhysicalNetworkGraph = PhysicalNetworkGraph(infrastructure)
        self.station_model: StationPlatformModel = StationPlatformModel(infrastructure)
        self.tunnel_tvs_model: TunnelTVSModel = TunnelTVSModel(infrastructure)

        # Cache keyed by (route_id, direction_str)
        self._cache: Dict[Tuple[str, str], RouteProfile] = {}

    def preprocess_route(
        self,
        route: Route,
        running_direction: RunningDirection = RunningDirection.FORWARD,
        train_category: Optional[str] = None,
    ) -> RouteProfile:
        """P02-PREP-001 & 002: Generate or retrieve preprocessed route profile."""
        cache_key = (route.route_id, running_direction.value)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Invariant: If running_direction is REVERSE and route was built forward, generate reverse route
        active_route = route
        if running_direction.is_reverse:
            # Check if route is already reversed or needs reversal
            if not route.traversals[0].direction.is_reverse:
                active_route = route.create_reverse_route(self.graph)

        alignment = RouteAlignmentProfile(active_route)
        speed = RouteSpeedProfile(
            route=active_route,
            restrictions=self.speed_restrictions,
            train_category=train_category,
        )
        stops = self.station_model.resolve_route_stops(active_route)
        tvs = self.tunnel_tvs_model.resolve_route_tvs_sections(active_route)

        profile = RouteProfile(
            route=active_route,
            running_direction=running_direction,
            alignment=alignment,
            speed_profile=speed,
            stations=stops,
            tvs_sections=tvs,
        )

        self._cache[cache_key] = profile
        return profile
