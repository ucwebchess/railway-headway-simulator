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

import re
import warnings
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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


class PlatformBerthOverhangError(StationGeometryError):
    """v1.14.6: a computed berth footprint leaves the parent platform by more than the unavoidable overhang."""

    DEFAULT_ERROR_CODE = "ERR_PLATFORM_BERTH_OVERHANG"


class RouteStopsNoTrainLengthError(StationGeometryError):
    """v1.14.6: a berth / route-stop position was requested without a positive train length."""

    DEFAULT_ERROR_CODE = "ERR_ROUTE_STOPS_NO_TRAIN_LENGTH"


class BerthFallbackWarning(UserWarning):
    """v1.14.6: the train is longer than its stop segment and berths against the parent platform."""


#: Numerical noise allowed on top of the unavoidable overhang in the berth containment check (m).
BERTH_NUMERIC_TOLERANCE_M = 1e-3

_SEGMENT_NUMBER_RE = re.compile(r"@s(\d+)$")


@dataclass(frozen=True)
class BerthPosition:
    """v1.14.6: train-front berth position at a platform stop, as a physical link offset.

    The front can lie on a different link from the stop segment (a train longer than its stop
    segment berths against the parent platform end, which may be on a sibling segment's link).
    ``fits_segment`` is True when the train fits its stop segment (segment-scoped rule kept).
    """

    link_id: str
    offset_m: float
    fits_segment: bool = True


def parent_platform_segments(platform: Platform, platforms: Iterable[Platform]) -> List[Platform]:
    """The link-level segments of ``platform``'s parent platform, in track order (``@s1`` first).

    Platforms without a parent (no ``PlatformSpans`` segmentation) are their own single segment.
    """
    parent = getattr(platform, "parent_platform_id", None)
    if not parent:
        return [platform]
    sibs: Dict[str, Platform] = {
        p.platform_id: p for p in platforms if getattr(p, "parent_platform_id", None) == parent
    }
    sibs.setdefault(platform.platform_id, platform)

    def _order(item: Tuple[int, Platform]) -> Tuple[int, int]:
        idx, p = item
        m = _SEGMENT_NUMBER_RE.search(p.platform_id)
        return (int(m.group(1)) if m else 10**9, idx)

    return [p for _, p in sorted(enumerate(sibs.values()), key=_order)]


def berth_containment_tolerance_m(train_length_m: float, parent_platform_length_m: float) -> float:
    """v1.14.6: allowed overhang = the unavoidable overhang ``max(0, L - P)`` + 1 mm numerical noise."""
    return max(0.0, float(train_length_m) - float(parent_platform_length_m)) + BERTH_NUMERIC_TOLERANCE_M


def check_berth_containment(
    platform_id: str,
    front_m: float,
    train_length_m: float,
    parent_platform_length_m: float,
    direction: RunningDirection,
) -> None:
    """v1.14.6: raise ``ERR_PLATFORM_BERTH_OVERHANG`` if a berth footprint leaves the parent platform.

    Positions are in the parent platform's *travel frame*: 0 = the platform end the train enters,
    ``parent_platform_length_m`` = the platform end in the direction of travel. The front is at
    ``front_m`` and the rear at ``front_m - train_length_m`` in both running directions.
    """
    tol = berth_containment_tolerance_m(train_length_m, parent_platform_length_m)
    rear_m = float(front_m) - float(train_length_m)
    for end_name, excess in (("rear", -rear_m), ("front", float(front_m) - float(parent_platform_length_m))):
        if excess > tol:
            raise PlatformBerthOverhangError(
                f"Berth at platform '{platform_id}' ({direction.value}): the train {end_name} lies "
                f"{excess:.3f} m outside the platform; the allowed overhang is {tol:.3f} m "
                f"(train {float(train_length_m):.2f} m, platform {float(parent_platform_length_m):.2f} m).",
                context={
                    "platform_id": platform_id,
                    "end": end_name,
                    "overhang_m": round(excess, 6),
                    "allowed_overhang_m": round(tol, 6),
                    "train_length_m": float(train_length_m),
                    "parent_platform_length_m": float(parent_platform_length_m),
                    "direction": direction.value,
                },
            )


def berth_front_offset(
    segment: Platform,
    parent_extent: Optional[Sequence[Platform]],
    train_length_m: Optional[float],
    direction: RunningDirection,
) -> BerthPosition:
    """v1.14.6: the single berth rule — where the train front stops at a platform stop.

    ``segment`` is the stop segment (selected by ``SEGMENT_HINT_OFFSET_M``); ``parent_extent`` is
    the parent platform's link-level segments in track order (see ``parent_platform_segments``).
    FORWARD runs along increasing link offsets, REVERSE along decreasing offsets.

    * Train fits its stop segment (``L <= segment length``): unchanged pre-v1.14.6 rule — the
      front stops one train length past the segment's entry end in the direction of travel.
    * Train longer than its stop segment: the front pulls up to the **parent platform end** in
      the direction of travel (the hint stays the stop segment for reporting), a
      ``BerthFallbackWarning`` is issued, and the footprint is checked against the parent
      platform (``ERR_PLATFORM_BERTH_OVERHANG`` beyond the unavoidable overhang).
    """
    if train_length_m is None or not float(train_length_m) > 0.0:
        raise RouteStopsNoTrainLengthError(
            f"A berth position at platform '{segment.platform_id}' needs a positive train length "
            f"(got {train_length_m!r}).",
            context={"platform_id": segment.platform_id, "train_length_m": train_length_m},
        )
    L = float(train_length_m)
    segs = list(parent_extent or [])
    if not any(p.platform_id == segment.platform_id for p in segs):
        segs = [segment]
    reverse = direction == RunningDirection.REVERSE
    parent_id = getattr(segment, "parent_platform_id", None) or segment.platform_id
    parent_len = float(sum(float(p.length_m) for p in segs))
    seg_len = float(segment.length_m)
    start, end = float(segment.start_offset_m), float(segment.end_offset_m)

    # Travel-frame entry of the stop segment (0 = parent end the train enters).
    travel = list(reversed(segs)) if reverse else segs
    entry_t = 0.0
    for p in travel:
        if p.platform_id == segment.platform_id:
            break
        entry_t += float(p.length_m)

    if L <= seg_len + FIT_TOLERANCE_M:
        # Segment-scoped rule kept bit-for-bit for trains that fit (v1.14.6 decision C4).
        if reverse:
            off = max(start, end - min(seg_len, L))
        else:
            off = min(end, start + min(seg_len, L))
        check_berth_containment(parent_id, entry_t + abs(off - (end if reverse else start)), L, parent_len, direction)
        return BerthPosition(link_id=segment.link_id, offset_m=off, fits_segment=True)

    # Train longer than its stop segment: berth against the parent platform end (Policy A).
    check_berth_containment(parent_id, parent_len, L, parent_len, direction)
    m = _SEGMENT_NUMBER_RE.search(segment.platform_id)
    seg_label = m.group(1) if m else segment.platform_id
    warnings.warn(
        f"Train {L:.1f}m exceeds segment {seg_label} ({seg_len:.1f}m); berthing against parent platform",
        BerthFallbackWarning,
        stacklevel=2,
    )
    exit_seg = segs[0] if reverse else segs[-1]
    off = float(exit_seg.start_offset_m) if reverse else float(exit_seg.end_offset_m)
    return BerthPosition(link_id=exit_seg.link_id, offset_m=off, fits_segment=False)


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

    def resolve_route_stops(self, route: Route, train_length_m: Optional[float] = None) -> List[RoutePlatformStop]:
        """P02-ST-006 & P02-DIR-010: Map stations and platforms to route-distance coordinates.

        In reverse operation, stations are encountered in reverse order,
        and stopping points are mapped to the selected running direction.

        v1.14.6: ``train_length_m`` is required (``ERR_ROUTE_STOPS_NO_TRAIN_LENGTH`` when missing
        or non-positive, no silent default). The stopping position is the train-front berth from
        the central rule ``berth_front_offset`` — the same rule the multi-train engine uses — so
        the single-train and multi-train paths agree.
        """
        if train_length_m is None or not float(train_length_m) > 0.0:
            raise RouteStopsNoTrainLengthError(
                f"resolve_route_stops needs a positive train_length_m (got {train_length_m!r}); "
                "the stopping position depends on the train length.",
                context={"route_id": getattr(route, "route_id", None), "train_length_m": train_length_m},
            )
        trav_by_link = {t.link_id: t for t in route.traversals}
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

                # v1.14.6: stopping position = central berth rule (train front), not the hint point.
                berth = berth_front_offset(
                    plat, self.parent_platform_segments(plat.platform_id), train_length_m, traversal.direction
                )
                berth_trav = trav_by_link.get(berth.link_id)
                if berth_trav is None:
                    raise StationGeometryError(
                        f"Berth of platform '{plat.platform_id}' lies on link '{berth.link_id}', which is "
                        f"not on route '{getattr(route, 'route_id', '')}'.",
                        context={"platform_id": plat.platform_id, "berth_link_id": berth.link_id},
                    )
                s_stop = berth_trav.physical_offset_to_route_distance(berth.offset_m)

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

    def parent_platform_segments(self, platform_id: str) -> List[Platform]:
        """v1.14.6: segments of the platform that segment ``platform_id`` belongs to, in track order."""
        return parent_platform_segments(self.platforms[platform_id], self.platforms.values())
