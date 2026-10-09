"""Fixed-block signalling architecture, signal aspect calculation, and direction look-ahead.

Strictly satisfies RHS-P05-001:
- § 12: Generic Fixed-Block Architecture (P05-FB-001 to P05-FB-005)
- § 13: Two-Aspect Signalling (P05-ASP2-001 to P05-ASP2-005)
- § 14: Three-Aspect Signalling (P05-ASP3-001 to P05-ASP3-005)
- § 15: Four-Aspect Signalling (P05-ASP4-001 to P05-ASP4-005)
- § 20: Direction-Aware Signal Orientation & Look-Ahead (P05-DIR-004 to P05-DIR-005)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from headway.data.canonical import AspectModelType, Signal, TrackDirectionality
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route
from headway.signalling.resource_types import (
    ResourceEventType,
    SignalAspect,
    SignallingError,
    SignallingEvent,
)
from headway.signalling.resources import ResourceController


class SignalAspectController:
    """Calculates directional signal aspects based on fixed-block look-ahead and route state."""

    def __init__(
        self,
        resource_controller: ResourceController,
        aspect_model: AspectModelType = AspectModelType.THREE_ASPECT,
    ) -> None:
        self.resource_controller = resource_controller
        self.aspect_model = aspect_model
        self.signals: Dict[str, Signal] = {}
        self.signal_aspects: Dict[str, SignalAspect] = {}
        self.event_log: List[SignallingEvent] = []
        self._next_sequence_id: int = 1

    def _next_seq(self) -> int:
        seq = self._next_sequence_id
        self._next_sequence_id += 1
        return seq

    def register_signal(self, signal: Signal) -> None:
        """Register wayside signal."""
        self.signals[signal.signal_id] = signal
        # Default restrictive aspect
        default_aspect = SignalAspect.STOP if self.aspect_model == AspectModelType.TWO_ASPECT else SignalAspect.RED
        self.signal_aspects[signal.signal_id] = default_aspect

    def is_signal_facing(self, signal: Signal, train_direction: RunningDirection) -> bool:
        """P05-DIR-004: Validate whether a signal faces the train's running direction."""
        sig_dir = signal.direction
        if sig_dir == TrackDirectionality.BIDIRECTIONAL:
            return True
        if sig_dir == TrackDirectionality.NOMINAL:
            return train_direction == RunningDirection.FORWARD
        if sig_dir == TrackDirectionality.REVERSE:
            return train_direction == RunningDirection.REVERSE
        return False

    def evaluate_signal_aspect(
        self,
        signal_id: str,
        downstream_block_ids: List[str],
        train_direction: RunningDirection,
        timestamp_s: float,
        train_id: Optional[str] = None,
        is_route_locked: bool = True,
    ) -> SignalAspect:
        """P05-FB & P05-DIR-005: Compute signal aspect looking ahead along train direction."""
        signal = self.signals.get(signal_id)
        if not signal:
            raise SignallingError(f"Cannot evaluate unknown signal '{signal_id}'.")

        # P05-DIR-004: Signal orientation check
        if not self.is_signal_facing(signal, train_direction):
            # Non-facing signal does not govern this direction
            return SignalAspect.STOP if self.aspect_model == AspectModelType.TWO_ASPECT else SignalAspect.RED

        # If interlocking route is not locked, signal remains at default restrictive aspect
        if not is_route_locked or not downstream_block_ids:
            new_aspect = SignalAspect.STOP if self.aspect_model == AspectModelType.TWO_ASPECT else SignalAspect.RED
            self._update_aspect(signal_id, new_aspect, timestamp_s, train_id)
            return new_aspect

        # Check availability of downstream blocks
        block_free: List[bool] = []
        for bid in downstream_block_ids:
            res = self.resource_controller.resources.get(bid)
            if not res:
                block_free.append(False)
            else:
                # Block is considered free if not occupied and either not reserved, reserved for this train, or route is locked
                is_free = (not res.is_occupied) and (
                    not res.is_reserved or (train_id is not None and train_id in res.reservations) or (train_id is None and is_route_locked)
                )
                block_free.append(is_free)

        # 1. Two-Aspect Signalling (STOP / PROCEED)
        if self.aspect_model == AspectModelType.TWO_ASPECT:
            if block_free and block_free[0]:
                new_aspect = SignalAspect.PROCEED
            else:
                new_aspect = SignalAspect.STOP

        # 2. Three-Aspect Signalling (RED / YELLOW / GREEN)
        elif self.aspect_model == AspectModelType.THREE_ASPECT:
            if not block_free or not block_free[0]:
                new_aspect = SignalAspect.RED
            elif len(block_free) >= 2 and not block_free[1]:
                new_aspect = SignalAspect.YELLOW  # Expect stop at next signal
            else:
                new_aspect = SignalAspect.GREEN

        # 3. Four-Aspect Signalling (RED / YELLOW / DOUBLE_YELLOW / GREEN)
        elif self.aspect_model == AspectModelType.FOUR_ASPECT:
            if not block_free or not block_free[0]:
                new_aspect = SignalAspect.RED
            elif len(block_free) >= 2 and not block_free[1]:
                new_aspect = SignalAspect.YELLOW
            elif len(block_free) >= 3 and not block_free[2]:
                new_aspect = SignalAspect.DOUBLE_YELLOW  # Preliminary warning
            else:
                new_aspect = SignalAspect.GREEN
        else:
            new_aspect = SignalAspect.RED

        self._update_aspect(signal_id, new_aspect, timestamp_s, train_id)
        return new_aspect

    def _update_aspect(
        self,
        signal_id: str,
        new_aspect: SignalAspect,
        timestamp_s: float,
        train_id: Optional[str] = None,
    ) -> None:
        old_aspect = self.signal_aspects.get(signal_id)
        if old_aspect != new_aspect:
            self.signal_aspects[signal_id] = new_aspect
            self.event_log.append(
                SignallingEvent(
                    sequence_id=self._next_seq(),
                    timestamp_s=timestamp_s,
                    event_type=ResourceEventType.SIGNAL_ASPECT_CHANGED,
                    resource_id=signal_id,
                    train_id=train_id,
                    description=f"Signal '{signal_id}' changed aspect: {old_aspect} -> {new_aspect}",
                    details={"old_aspect": old_aspect.value if old_aspect else None, "new_aspect": new_aspect.value},
                )
            )
