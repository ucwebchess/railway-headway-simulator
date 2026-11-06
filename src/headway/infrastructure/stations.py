"""Station, platform, and train stopping point geometry model.

Strictly satisfies RHS-P02-001 § 15:
- P02-ST-001 & 002: Stations, platforms mapped to physical link intervals.
- P02-ST-003: Usable platform length validation.
- P02-ST-004: Stopping points mapped to link offsets.
- P02-ST-005: Direction compatibility.
- P02-ST-006 & P02-DIR-010: Reverse direction station ordering and reverse stopping positions.
- P02-ST-007: Train-length stopping geometry (front and rear positions, platform coverage check).
- v1.14.1: platform fit is checked against the **physical (parent) platform** — the sum of the
  lengths of all link-level segments generated from one ``PlatformSpans`` row
  (``parent_platform_length_m``) — not against the single segment the train berths on.
  A train longer than the whole platform raises ``ERR_TRAIN_OVERHANG``.
- No braking or dwell calculations during P02.
"""

from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError
from headway.data.canonical import InfrastructureModel, Platform, Station, StoppingPoint
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route


class StationGeometryError(InfrastructureError):
    """Raised when platform geometry or stopping point coordinates are invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_STATION_GEOMETRY"


class TrainOverhangError(StationGeometryError):
    """Raised when a train is longer than the physical (parent) platform it stops at."""

    DEFAULT_ERROR_CODE = "ERR_TRAIN_OVERHANG"


#: Length comparison tolerance (m) for the platform fit check.
FIT_TOLERANCE_M = 1e-3


def parent_platform_length_m(platform: Platform, platforms: Iterable[Platform]) -> float:
    """Physical platform length: the sum of the segment lengths of ``platform``'s parent.

    A v1.14.0 ``PlatformSpans`` row is split into link-level segments (``<PLATFORM_ID>@s<N>``)
    that share ``parent_platform_id``. Platforms without a parent (no segmentation) are their
    own physical platform.
    """
    parent = getattr(platform, "parent_platform_id", None)
    if not parent:
        return float(platform.length_m)
    siblings = {p.platform_id: p for p in platforms if getattr(p, "parent_platform_id", None) == parent}
    siblings.setdefault(platform.platform_id, platform)
    return float(sum(p.length_m for p in siblings.values()))


@dataclass(frozen=True)
class RoutePlatformStop:
    """A platform and stopping point resolved along a specific Route.

    ``platform`` is the link-level segment the train berths on. ``parent_platform_length_m``
    and ``parent_route_distance_start_m`` / ``parent_route_distance_end_m`` describe the
    physical platform it belongs to (all of its segments); they default to the segment's own
    values for platforms without a parent.
    """

    station: Station
    platform: Platform
    stopping_point: Optional[StoppingPoint]
    route_distance_start_m: float
    route_distance_end_m: float
    stopping_position_m: float
    direction: RunningDirection
    parent_platform_length_m: Optional[float] = None
    parent_route_distance_start_m: Optional[float] = None
    parent_route_distance_end_m: Optional[float] = None

    def __post_init__(self) -> None:
        if self.parent_platform_length_m is None:
            object.__setattr__(self, "parent_platform_length_m", float(self.platform.length_m))
        if self.parent_route_distance_start_m is None or self.parent_route_distance_end_m is None:
            object.__setattr__(self, "parent_route_distance_start_m", min(self.route_distance_start_m, self.route_distance_end_m))
            object.__setattr__(self, "parent_route_distance_end_m", max(self.route_distance_start_m, self.route_distance_end_m))

    @property
    def platform_length_m(self) -> float:
        """Length of the link-level segment the train berths on (not the physical platform)."""
        return self.platform.length_m

    @property
    def parent_platform_id(self) -> str:
        return getattr(self.platform, "parent_platform_id", None) or self.platform.platform_id

    def is_train_accommodated(self, train_length_m: float) -> bool:
        """P02-ST-003 & 007: Verify if train length fits within the physical platform.

        v1.14.1: compared with ``parent_platform_length_m`` (sum of the parent platform's
        segment lengths) — a 202 m train on a 200 m segment of a 400 m platform fits.
        """
        return train_length_m <= self.parent_platform_length_m + FIT_TOLERANCE_M

    def check_train_fit(self, train_length_m: float) -> None:
        """P02-ST-003 & 007: Raise ``ERR_TRAIN_OVERHANG`` if the train overhangs the physical platform."""
        if not self.is_train_accommodated(train_length_m):
            raise TrainOverhangError(
                f"Train length ({train_length_m:.1f} m) exceeds the physical length "
                f"({self.parent_platform_length_m:.1f} m) of platform '{self.parent_platform_id}' "
                f"(stop segment '{self.platform.platform_id}', {self.platform.length_m:.1f} m) at "
                f"station '{self.station.station_id}'; the train would overhang the platform.",
                context={
                    "platform_id": self.parent_platform_id,
                    "segment_id": self.platform.platform_id,
                    "station_id": self.station.station_id,
                    "train_length_m": train_length_m,
                    "parent_platform_length_m": self.parent_platform_length_m,
                    "segment_length_m": self.platform.length_m,
                },
            )

    def evaluate_train_stopping_interval(self, train_length_m: float) -> Tuple[float, float, bool]:
        """P02-ST-007: Compute train rear and front positions and check platform bounds.

        Front of train stops exactly at `stopping_position_m`.
        Rear of train is at `stopping_position_m - train_length_m` (in running direction).
        Returns (s_rear, s_front, is_within_platform).

        v1.14.1: "within platform" means within the physical (parent) platform on this route
        — the train may extend from its stop segment onto sibling segments.
        """
        s_front = self.stopping_position_m
        s_rear = s_front - train_length_m

        # Verify whether the entire train lies between physical platform start and end
        p_min = self.parent_route_distance_start_m
        p_max = self.parent_route_distance_end_m

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
                        parent_platform_length_m=self.parent_platform_length_m(plat.platform_id),
                    )
                )

        # v1.14.1: physical (parent) platform extent on this route = union of its segments.
        parent_bounds: Dict[str, Tuple[float, float]] = {}
        for st in route_stops:
            lo = min(st.route_distance_start_m, st.route_distance_end_m)
            hi = max(st.route_distance_start_m, st.route_distance_end_m)
            cur = parent_bounds.get(st.parent_platform_id)
            parent_bounds[st.parent_platform_id] = (lo, hi) if cur is None else (min(cur[0], lo), max(cur[1], hi))
        route_stops = [
            replace(
                st,
                parent_route_distance_start_m=parent_bounds[st.parent_platform_id][0],
                parent_route_distance_end_m=parent_bounds[st.parent_platform_id][1],
            )
            for st in route_stops
        ]

        # Sort stops in the order encountered along the route (by stopping position)
        route_stops.sort(key=lambda s: s.stopping_position_m)
        return route_stops

    def parent_platform_length_m(self, platform_id: str) -> float:
        """Physical length of the platform that segment ``platform_id`` belongs to."""
        return parent_platform_length_m(self.platforms[platform_id], self.platforms.values())
