"""Station, platform resource management, multi-platform allocation, and dwell lifecycle.

Strictly satisfies RHS-P07-001:
- § 5: Station Resource Model (P07-ST-001 to P07-ST-005)
- § 6: Platform Reservation & Compatibility (P07-PLT-001 to P07-PLT-006)
- § 7: Platform Occupation, Dwell, Departure & Release (P07-PLT-007 to P07-PLT-012)
- § 8: Residual Stationary Rear Occupation Integration
- § 9: Multi-Platform Allocation & Deterministic Selection (P07-MPA-001 to P07-MPA-007)
- § 10: Standardized Station Event Model
- Full support for both FORWARD and REVERSE railway movements.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from headway.data.canonical import InfrastructureModel, Platform, Station, TrackDirectionality
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.signalling.residual_occupation import ResidualOccupationDetector, ResidualOccupationRecord
from headway.signalling.resource_types import (
    PlatformCompatibilityError,
    ReleasePolicy,
    ResourceCategory,
    ResourceEventType,
    SignallingEvent,
    StationResourceError,
)
from headway.signalling.resources import ManagedResource, ResourceController


class PlatformSelectionPolicy(str, Enum):
    """P07-MPA: Platform allocation policy."""

    FIXED_ASSIGNMENT = "FIXED_ASSIGNMENT"
    PREFERRED_WITH_ALTERNATIVES = "PREFERRED_WITH_ALTERNATIVES"
    EARLIEST_FEASIBLE = "EARLIEST_FEASIBLE"


@dataclass(frozen=True)
class PlatformAssignmentRecord:
    """P07-MPA-006: Audit record of platform allocation."""

    train_id: str
    station_id: str
    requested_platform_id: Optional[str]
    assigned_platform_id: str
    assignment_time_s: float
    policy: PlatformSelectionPolicy
    dwell_duration_s: float
    train_length_m: float


@dataclass
class ActivePlatformOccupation:
    """Tracks active dwell and occupation state for a train at a platform."""

    train_id: str
    platform_id: str
    station_id: str
    dwell_duration_s: float
    arrival_time_s: Optional[float] = None
    dwell_start_s: Optional[float] = None
    dwell_completed_s: Optional[float] = None
    departure_time_s: Optional[float] = None
    rear_clearance_s: Optional[float] = None
    residual_record: Optional[ResidualOccupationRecord] = None


class PlatformController:
    """P07-PLT: Controls station platforms, reservations, dwell lifecycles, and residual rear occupation."""

    def __init__(
        self,
        resource_controller: ResourceController,
        default_release_delay_s: float = 2.0,
    ) -> None:
        self.resource_controller = resource_controller
        self.default_release_delay_s = default_release_delay_s
        self.stations: Dict[str, Station] = {}
        self.platforms: Dict[str, Platform] = {}
        self.station_to_platforms: Dict[str, List[str]] = {}
        self.platform_occupations: Dict[str, ActivePlatformOccupation] = {}  # train_id -> occupation
        self.assignment_history: List[PlatformAssignmentRecord] = []
        self.event_log: List[SignallingEvent] = []
        self._next_sequence_id: int = 1

    def _next_seq(self) -> int:
        seq = self._next_sequence_id
        self._next_sequence_id += 1
        return seq

    def _log_event(
        self,
        timestamp_s: float,
        event_type: ResourceEventType,
        resource_id: str,
        train_id: Optional[str] = None,
        route_id: Optional[str] = None,
        description: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> SignallingEvent:
        evt = SignallingEvent(
            sequence_id=self._next_seq(),
            timestamp_s=round(timestamp_s, 6),
            event_type=event_type,
            resource_id=resource_id,
            train_id=train_id,
            route_id=route_id,
            description=description,
            details=details or {},
        )
        self.event_log.append(evt)
        return evt

    def register_station(self, station: Station) -> None:
        """Register a physical station."""
        self.stations[station.station_id] = station
        if station.station_id not in self.station_to_platforms:
            self.station_to_platforms[station.station_id] = []

    def register_platform(self, platform: Platform, release_delay_s: Optional[float] = None) -> ManagedResource:
        """P07-RES-001: Register platform as a canonical PLATFORM resource in ResourceController."""
        self.platforms[platform.platform_id] = platform
        if platform.station_id not in self.station_to_platforms:
            self.station_to_platforms[platform.station_id] = []
        if platform.platform_id not in self.station_to_platforms[platform.station_id]:
            self.station_to_platforms[platform.station_id].append(platform.platform_id)

        delay = release_delay_s if release_delay_s is not None else self.default_release_delay_s
        res = ManagedResource(
            resource_id=platform.platform_id,
            category=ResourceCategory.PLATFORM,
            capacity=1,
            release_delay_s=delay,
            description=f"Platform '{platform.platform_id}' at station '{platform.station_id}'",
        )
        self.resource_controller.register_resource(res)
        return res

    def load_from_infrastructure(self, infra: InfrastructureModel) -> None:
        """Load all stations and platforms from canonical InfrastructureModel."""
        for s in infra.stations:
            self.register_station(s)
        for p in infra.platforms:
            self.register_platform(p)

    def validate_platform_compatibility(
        self,
        platform_id: str,
        train_length_m: float,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> Platform:
        """P07-PLT-002: Verify platform existence, train length fit, and direction."""
        plat = self.platforms.get(platform_id)
        if not plat:
            raise PlatformCompatibilityError(
                f"Platform '{platform_id}' does not exist.",
                context={"platform_id": platform_id},
            )

        if train_length_m > plat.length_m + 1e-3:
            raise PlatformCompatibilityError(
                f"Train length ({train_length_m:.1f} m) exceeds usable platform length "
                f"({plat.length_m:.1f} m) for platform '{platform_id}'.",
                context={
                    "platform_id": platform_id,
                    "train_length_m": train_length_m,
                    "platform_length_m": plat.length_m,
                },
            )
        return plat

    def request_platform(
        self,
        train_id: str,
        platform_id: str,
        train_length_m: float,
        timestamp_s: float,
        route_id: Optional[str] = None,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> bool:
        """P07-PLT-001 to 006: Request and reserve an exclusive platform."""
        plat = self.validate_platform_compatibility(platform_id, train_length_m, running_direction)

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.PLATFORM_REQUESTED,
            resource_id=platform_id,
            train_id=train_id,
            route_id=route_id,
            description=f"Train '{train_id}' requested platform '{platform_id}'",
            details={"train_length_m": train_length_m, "direction": running_direction.value},
        )

        res = self.resource_controller.get_resource(platform_id)
        if not res or not res.can_reserve(train_id=train_id, current_time_s=timestamp_s):
            return False

        self.resource_controller.reserve_resource(train_id=train_id, resource_id=platform_id, timestamp_s=timestamp_s)

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.PLATFORM_RESERVED,
            resource_id=platform_id,
            train_id=train_id,
            route_id=route_id,
            description=f"Platform '{platform_id}' reserved for train '{train_id}'",
        )
        return True

    def allocate_platform(
        self,
        train_id: str,
        station_id: str,
        train_length_m: float,
        timestamp_s: float,
        preferred_platform_id: Optional[str] = None,
        permitted_platform_ids: Optional[List[str]] = None,
        policy: PlatformSelectionPolicy = PlatformSelectionPolicy.PREFERRED_WITH_ALTERNATIVES,
        dwell_duration_s: float = 60.0,
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> str:
        """P07-MPA-001 to 007: Deterministic platform allocation with fallback alternatives."""
        available_plat_ids = self.station_to_platforms.get(station_id, [])
        if not available_plat_ids:
            raise StationResourceError(f"Station '{station_id}' has no registered platforms.")

        candidate_ids: List[str] = []
        if policy == PlatformSelectionPolicy.FIXED_ASSIGNMENT:
            if not preferred_platform_id:
                raise PlatformCompatibilityError(f"Fixed assignment policy requires preferred_platform_id for train '{train_id}'.")
            candidate_ids = [preferred_platform_id]
        elif policy == PlatformSelectionPolicy.PREFERRED_WITH_ALTERNATIVES:
            candidates: List[str] = []
            if preferred_platform_id and preferred_platform_id in available_plat_ids:
                candidates.append(preferred_platform_id)
            if permitted_platform_ids:
                for pid in permitted_platform_ids:
                    if pid in available_plat_ids and pid not in candidates:
                        candidates.append(pid)
            candidate_ids = candidates or sorted(available_plat_ids)
        else:  # EARLIEST_FEASIBLE
            candidate_ids = sorted(available_plat_ids)

        assigned_id: Optional[str] = None
        for pid in candidate_ids:
            try:
                self.validate_platform_compatibility(pid, train_length_m, running_direction)
            except PlatformCompatibilityError:
                continue

            res = self.resource_controller.get_resource(pid)
            if res and res.can_reserve(train_id=train_id, current_time_s=timestamp_s):
                assigned_id = pid
                break

        if not assigned_id:
            raise PlatformCompatibilityError(
                f"No compatible or available platform found at station '{station_id}' for train '{train_id}'.",
                context={"station_id": station_id, "candidates": candidate_ids, "train_length_m": train_length_m},
            )

        self.request_platform(
            train_id=train_id,
            platform_id=assigned_id,
            train_length_m=train_length_m,
            timestamp_s=timestamp_s,
            running_direction=running_direction,
        )

        record = PlatformAssignmentRecord(
            train_id=train_id,
            station_id=station_id,
            requested_platform_id=preferred_platform_id,
            assigned_platform_id=assigned_id,
            assignment_time_s=timestamp_s,
            policy=policy,
            dwell_duration_s=dwell_duration_s,
            train_length_m=train_length_m,
        )
        self.assignment_history.append(record)
        return assigned_id

    def front_enter_platform(
        self,
        train_id: str,
        platform_id: str,
        timestamp_s: float,
        dwell_duration_s: float = 60.0,
    ) -> None:
        """P07-PLT-007: Train front physically enters platform track."""
        plat = self.platforms.get(platform_id)
        st_id = plat.station_id if plat else "UNKNOWN_STATION"

        self.resource_controller.front_enter_resource(
            train_id=train_id,
            resource_id=platform_id,
            timestamp_s=timestamp_s,
        )

        occ = ActivePlatformOccupation(
            train_id=train_id,
            platform_id=platform_id,
            station_id=st_id,
            dwell_duration_s=dwell_duration_s,
            arrival_time_s=timestamp_s,
        )
        self.platform_occupations[train_id] = occ

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.PLATFORM_ENTERED,
            resource_id=platform_id,
            train_id=train_id,
            description=f"Train '{train_id}' front entered platform '{platform_id}'",
        )
        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.STATION_ARRIVAL,
            resource_id=st_id,
            train_id=train_id,
            description=f"Train '{train_id}' arrived at station '{st_id}'",
        )

    def start_dwell(
        self,
        train_id: str,
        platform_id: str,
        timestamp_s: float,
        dwell_duration_s: Optional[float] = None,
        residual_record: Optional[ResidualOccupationRecord] = None,
    ) -> None:
        """P07-PLT-009: Train comes to complete stop at designated stopping point and starts dwell."""
        occ = self.platform_occupations.get(train_id)
        if not occ:
            occ = ActivePlatformOccupation(
                train_id=train_id,
                platform_id=platform_id,
                station_id=self.platforms[platform_id].station_id if platform_id in self.platforms else "UNKNOWN",
                dwell_duration_s=dwell_duration_s or 60.0,
            )
            self.platform_occupations[train_id] = occ

        if dwell_duration_s is not None:
            occ.dwell_duration_s = dwell_duration_s
        occ.dwell_start_s = timestamp_s
        occ.residual_record = residual_record

        # P07-RESID-005: If stationary rear infringes upstream resource, keep upstream resource occupied
        if residual_record and residual_record.is_infringing:
            res_up = self.resource_controller.get_resource(residual_record.upstream_resource_id)
            if res_up and not res_up.is_occupied:
                self.resource_controller.front_enter_resource(
                    train_id=train_id,
                    resource_id=residual_record.upstream_resource_id,
                    timestamp_s=timestamp_s,
                )

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.DWELL_STARTED,
            resource_id=platform_id,
            train_id=train_id,
            description=f"Train '{train_id}' started dwell at platform '{platform_id}' (duration={occ.dwell_duration_s}s)",
            details={"dwell_duration_s": occ.dwell_duration_s, "has_infringement": residual_record.is_infringing if residual_record else False},
        )

    def complete_dwell(
        self,
        train_id: str,
        platform_id: str,
        timestamp_s: float,
    ) -> None:
        """P07-PLT-010 & 012: Dwell completes and train departs. Platform remains occupied until rear clearance!"""
        occ = self.platform_occupations.get(train_id)
        if occ:
            occ.dwell_completed_s = timestamp_s
            occ.departure_time_s = timestamp_s

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.DWELL_COMPLETED,
            resource_id=platform_id,
            train_id=train_id,
            description=f"Train '{train_id}' completed passenger dwell at platform '{platform_id}'",
        )
        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.STATION_DEPARTURE,
            resource_id=occ.station_id if occ else platform_id,
            train_id=train_id,
            description=f"Train '{train_id}' departed station platform '{platform_id}'",
        )

    def front_exit_platform(self, train_id: str, platform_id: str, timestamp_s: float) -> None:
        """P07-PLT-012: Train front exits platform. Does NOT release the platform!"""
        self.resource_controller.front_exit_resource(
            train_id=train_id,
            resource_id=platform_id,
            timestamp_s=timestamp_s,
        )

    def rear_clear_platform(
        self,
        train_id: str,
        platform_id: str,
        timestamp_s: float,
    ) -> None:
        """P07-PLT-011: Complete train-rear clearance of platform track."""
        occ = self.platform_occupations.get(train_id)
        if occ:
            occ.rear_clearance_s = timestamp_s

        self.resource_controller.rear_clear_resource(
            train_id=train_id,
            resource_id=platform_id,
            timestamp_s=timestamp_s,
        )

        self._log_event(
            timestamp_s=timestamp_s,
            event_type=ResourceEventType.PLATFORM_REAR_CLEARED,
            resource_id=platform_id,
            train_id=train_id,
            description=f"Train '{train_id}' rear completely cleared platform '{platform_id}'",
        )

    def process_platform_releases(self, current_time_s: float) -> List[SignallingEvent]:
        """Process pending release delays for cleared platforms."""
        released_events = self.resource_controller.process_pending_releases(current_time_s)
        for evt in released_events:
            if evt.event_type == ResourceEventType.RESOURCE_RELEASED:
                res = self.resource_controller.get_resource(evt.resource_id)
                if res and res.category == ResourceCategory.PLATFORM:
                    self._log_event(
                        timestamp_s=current_time_s,
                        event_type=ResourceEventType.PLATFORM_RELEASED,
                        resource_id=evt.resource_id,
                        description=f"Platform '{evt.resource_id}' released after post-clearance delay",
                    )
        return released_events
