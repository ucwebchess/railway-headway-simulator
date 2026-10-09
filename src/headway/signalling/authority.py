"""Movement authority generation, lifecycle, and endpoint contracts.

Strictly satisfies RHS-P05-001 § 16:
- P05-MA-001: Authority fields and contracts.
- P05-MA-002: Authority generation for fixed-block systems.
- P05-MA-003: Authority endpoint enforcement (EoA).
- P05-MA-004: Monotonic route-distance coordinate representation.
- P05-MA-005: Future ETCS Level 2 and CBTC architectural compatibility.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.signalling.resource_types import (
    MovementAuthorityError,
    ResourceEventType,
    SignalAspect,
    SignallingEvent,
)


class AuthorityValidity(str, Enum):
    """Lifecycle validity status of a movement authority."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class MovementAuthority:
    """P05-MA-001: Standardized Movement Authority contract."""

    ma_id: str
    train_id: str
    route_id: str
    start_reference: float
    end_of_authority: float
    target_speed_ms: float
    issue_time_s: float
    effective_time_s: float
    validity_status: AuthorityValidity = AuthorityValidity.ACTIVE
    running_direction: RunningDirection = RunningDirection.FORWARD
    description: Optional[str] = None

    @property
    def length_m(self) -> float:
        """Usable distance authorized under this MA."""
        return max(0.0, self.end_of_authority - self.start_reference)

    def is_valid_at(self, time_s: float) -> bool:
        return self.validity_status == AuthorityValidity.ACTIVE and time_s >= self.effective_time_s


class MovementAuthorityController:
    """Issues and tracks movement authorities along interlocking routes."""

    def __init__(self) -> None:
        self.active_authorities: Dict[str, MovementAuthority] = {}  # train_id -> MA
        self.authority_history: List[MovementAuthority] = []
        self.event_log: List[SignallingEvent] = []
        self._next_sequence_id: int = 1

    def _next_seq(self) -> int:
        seq = self._next_sequence_id
        self._next_sequence_id += 1
        return seq

    def issue_authority(
        self,
        train_id: str,
        route: Route,
        start_reference: float,
        end_of_authority: float,
        target_speed_ms: float,
        timestamp_s: float,
        effective_time_s: Optional[float] = None,
        description: Optional[str] = None,
    ) -> MovementAuthority:
        """P05-MA-002 to 004: Issue a new movement authority along the route."""
        if end_of_authority < start_reference:
            raise MovementAuthorityError(
                f"Invalid Movement Authority: End of Authority ({end_of_authority:.2f} m) "
                f"cannot be before start reference ({start_reference:.2f} m).",
                context={"train_id": train_id, "start": start_reference, "eoa": end_of_authority},
            )

        eff_t = effective_time_s if effective_time_s is not None else timestamp_s
        primary_dir = route.traversals[0].direction if route.traversals else RunningDirection.FORWARD

        ma = MovementAuthority(
            ma_id=f"MA_{train_id}_{self._next_seq()}",
            train_id=train_id,
            route_id=route.route_id,
            start_reference=round(start_reference, 3),
            end_of_authority=round(end_of_authority, 3),
            target_speed_ms=round(target_speed_ms, 3),
            issue_time_s=timestamp_s,
            effective_time_s=eff_t,
            validity_status=AuthorityValidity.ACTIVE,
            running_direction=primary_dir,
            description=description or f"MA for train '{train_id}' along route '{route.route_id}' to {end_of_authority:.1f}m",
        )

        self.active_authorities[train_id] = ma
        self.authority_history.append(ma)

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.MA_ISSUED,
                resource_id=route.route_id,
                train_id=train_id,
                route_id=route.route_id,
                description=f"Movement Authority issued to train '{train_id}' (EoA={end_of_authority:.1f}m, v_target={target_speed_ms:.1f}m/s)",
                details={"eoa_m": end_of_authority, "target_speed_ms": target_speed_ms},
            )
        )
        return ma

    def update_authority_endpoint(
        self,
        train_id: str,
        new_end_of_authority: float,
        new_target_speed_ms: float,
        timestamp_s: float,
    ) -> MovementAuthority:
        """P05-MA-003: Update existing movement authority endpoint."""
        curr_ma = self.active_authorities.get(train_id)
        if not curr_ma:
            raise MovementAuthorityError(f"No active Movement Authority found for train '{train_id}'.")

        updated_ma = MovementAuthority(
            ma_id=f"MA_{train_id}_{self._next_seq()}",
            train_id=train_id,
            route_id=curr_ma.route_id,
            start_reference=curr_ma.start_reference,
            end_of_authority=round(new_end_of_authority, 3),
            target_speed_ms=round(new_target_speed_ms, 3),
            issue_time_s=timestamp_s,
            effective_time_s=timestamp_s,
            validity_status=AuthorityValidity.ACTIVE,
            running_direction=curr_ma.running_direction,
            description=f"Updated MA for train '{train_id}' to {new_end_of_authority:.1f}m",
        )

        self.active_authorities[train_id] = updated_ma
        self.authority_history.append(updated_ma)

        self.event_log.append(
            SignallingEvent(
                sequence_id=self._next_seq(),
                timestamp_s=timestamp_s,
                event_type=ResourceEventType.MA_UPDATED,
                resource_id=curr_ma.route_id,
                train_id=train_id,
                route_id=curr_ma.route_id,
                description=f"Movement Authority updated for train '{train_id}' to EoA={new_end_of_authority:.1f}m",
            )
        )
        return updated_ma

    def get_active_authority(self, train_id: str) -> Optional[MovementAuthority]:
        return self.active_authorities.get(train_id)
