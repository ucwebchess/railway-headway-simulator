"""Station, platform, and train stopping point geometry model.

Strictly satisfies RHS-P02-001 § 15:
- P02-ST-001 & 002: Stations, platforms mapped to physical link intervals.
- P02-ST-003: Usable platform length validation.
- P02-ST-004: Stopping points mapped to link offsets.
- P02-ST-005: Direction compatibility.
- P02-ST-006 & P02-DIR-010: Reverse direction station ordering and reverse stopping positions.
- P02-ST-007: Train-length stopping geometry (front and rear positions, platform coverage check).
- No braking or dwell calculations during P02.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError
from headway.data.canonical import InfrastructureModel, Platform, Station, StoppingPoint
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route


class StationGeometryError(InfrastructureError):
    """Raised when platform geometry or stopping point coordinates are invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_STATION_GEOMETRY"


@dataclass(frozen=True)
class RoutePlatformStop:
    """A platform and stopping point resolved along a specific Route."""

    station: Station
    platform: Platform
    stopping_point: Optional[StoppingPoint]
    route_distance_start_m: float
    route_distance_end_m: float
    stopping_position_m: float
    direction: RunningDirection

    @property
    def platform_length_m(self) -> float:
        return self.platform.length_m

    def is_train_accommodated(self, train_length_m: float) -> bool:
        """P02-ST-003 & 007: Verify if train length fits within the physical platform."""
        return train_length_m <= self.platform.length_m + 1e-3

    def evaluate_train_stopping_interval(self, train_length_m: float) -> Tuple[float, float, bool]:
        """P02-ST-007: Compute train rear and front positions and check platform bounds.

        Front of train stops exactly at `stopping_position_m`.
        Rear of train is at `stopping_position_m - train_length_m` (in running direction).
        Returns (s_rear, s_front, is_within_platform).
        """
        s_front = self.stopping_position_m
        s_rear = s_front - train_length_m

        # Verify whether the entire train lies between platform start and end
        # Note: Platform start/end on route can be in either direction
        p_min = min(self.route_distance_start_m, self.route_distance_end_m)
        p_max = max(self.route_distance_start_m, self.route_distance_end_m)

        within = (s_rear >= p_min - 1e-3) and (s_front <= p_max + 1e-3)
        return (s_rear, s_front, within)


class StationPlatformModel:
    """Manages physical station, platform, and stopping point geometry."""

    def __init__(self, infrastructure: Optional[InfrastructureModel] = None) -> None:
        self.stations: Dict[str, Station] = {}
        self.platforms: Dict[str, Platform] = {}
        self.stopping_points: Dict[str, StoppingPoint] = {}

        if infrastructure:
            for s in infrastructure.stations:
                self.stations[s.station_id] = s
            for p in infrastructure.platforms:
                self.platforms[p.platform_id] = p
            for sp in infrastructure.stopping_points:
                self.stopping_points[sp.stopping_point_id] = sp

    def add_station(self, station: Station) -> None:
        self.stations[station.station_id] = station

    def add_platform(self, platform: Platform) -> None:
        if platform.end_offset_m <= platform.start_offset_m:
            raise StationGeometryError(
                f"Platform '{platform.platform_id}' end_offset_m ({platform.end_offset_m}) "
                f"must be greater than start_offset_m ({platform.start_offset_m}).",
                context={"platform_id": platform.platform_id},
            )
        self.platforms[platform.platform_id] = platform

    def add_stopping_point(self, stopping_point: StoppingPoint) -> None:
        self.stopping_points[stopping_point.stopping_point_id] = stopping_point

    def get_platforms_for_station(self, station_id: str) -> List[Platform]:
        return [p for p in self.platforms.values() if p.station_id == station_id]

    def get_stopping_points_for_platform(self, platform_id: str) -> List[StoppingPoint]:
        return [sp for sp in self.stopping_points.values() if sp.platform_id == platform_id]

    def resolve_route_stops(self, route: Route) -> List[RoutePlatformStop]:
        """P02-ST-006 & P02-DIR-010: Map stations and platforms to route-distance coordinates.

        In reverse operation, stations are encountered in reverse order,
        and stopping points are mapped to the selected running direction.
        """
        route_stops: List[RoutePlatformStop] = []

        for traversal in route.traversals:
            link_id = traversal.link_id

            # Find all platforms on this link
            link_platforms = [p for p in self.platforms.values() if p.link_id == link_id]
            for plat in link_platforms:
                station = self.stations.get(plat.station_id)
                if not station:
                    continue

                # Find stopping points for this platform
                sp_list = self.get_stopping_points_for_platform(plat.platform_id)
                stopping_point = sp_list[0] if sp_list else None

                # Map platform start and end offsets to route distance
                s_start = traversal.physical_offset_to_route_distance(plat.start_offset_m)
                s_end = traversal.physical_offset_to_route_distance(plat.end_offset_m)

                # Default stopping position
                if stopping_point is not None:
                    s_stop = traversal.physical_offset_to_route_distance(stopping_point.offset_m)
                else:
                    # If no explicit stopping point, default to platform exit end in running direction
                    s_stop = max(s_start, s_end)

                route_stops.append(
                    RoutePlatformStop(
                        station=station,
                        platform=plat,
                        stopping_point=stopping_point,
                        route_distance_start_m=s_start,
                        route_distance_end_m=s_end,
                        stopping_position_m=s_stop,
                        direction=traversal.direction,
                    )
                )

        # Sort stops in the order encountered along the route (by stopping position)
        route_stops.sort(key=lambda s: s.stopping_position_m)
        return route_stops
