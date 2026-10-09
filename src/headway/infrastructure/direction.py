"""Running direction and track directionality policies for railway infrastructure.

Mandatory Project Requirement (RHS-P02-001 § 5 & § 28):
The complete infrastructure architecture must support both FORWARD and REVERSE
railway operations from the beginning.
"""

from enum import Enum
from typing import Optional
from headway.core.exceptions import InfrastructureError
from headway.data.canonical import TrackDirectionality


class RunningDirection(str, Enum):
    """Running direction for route traversal, train movement, and simulation.

    FORWARD: Traversal follows the link reference orientation (start_node -> end_node).
    REVERSE: Traversal is opposite the link reference orientation (end_node -> start_node).
    """

    FORWARD = "FORWARD"
    REVERSE = "REVERSE"

    def opposite(self) -> "RunningDirection":
        """Return the inverted running direction."""
        return RunningDirection.REVERSE if self == RunningDirection.FORWARD else RunningDirection.FORWARD

    @property
    def is_forward(self) -> bool:
        return self == RunningDirection.FORWARD

    @property
    def is_reverse(self) -> bool:
        return self == RunningDirection.REVERSE

    @classmethod
    def from_string(cls, val: str) -> "RunningDirection":
        """Safely parse a string into RunningDirection."""
        normalized = val.strip().upper()
        if normalized in ("FORWARD", "NOMINAL", "FWD", "UP"):
            return cls.FORWARD
        if normalized in ("REVERSE", "REV", "DN", "DOWN", "BACKWARD"):
            return cls.REVERSE
        raise ValueError(f"Unknown running direction '{val}'. Expected 'FORWARD' or 'REVERSE'.")


class DirectionPolicyError(InfrastructureError):
    """Raised when a route traversal violates a track directionality policy."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_DIRECTION_POLICY"


class DirectionPolicy:
    """Evaluates whether physical track directionality permits a traversal direction."""

    @staticmethod
    def is_traversal_permitted(
        track_directionality: TrackDirectionality,
        traversal_direction: RunningDirection,
    ) -> bool:
        """Determine whether a track link allows movement in the specified running direction.

        - BIDIRECTIONAL: Allows both FORWARD and REVERSE.
        - NOMINAL: Allows FORWARD only (unauthorized in REVERSE).
        - REVERSE: Allows REVERSE only (unauthorized in FORWARD).
        """
        if track_directionality == TrackDirectionality.BIDIRECTIONAL:
            return True
        if track_directionality == TrackDirectionality.NOMINAL:
            return traversal_direction == RunningDirection.FORWARD
        if track_directionality == TrackDirectionality.REVERSE:
            return traversal_direction == RunningDirection.REVERSE
        return False

    @classmethod
    def validate_traversal(
        cls,
        track_id: str,
        link_id: str,
        track_directionality: TrackDirectionality,
        traversal_direction: RunningDirection,
    ) -> None:
        """Validate traversal against policy and raise DirectionPolicyError if prohibited."""
        if not cls.is_traversal_permitted(track_directionality, traversal_direction):
            raise DirectionPolicyError(
                f"Link '{link_id}' on track '{track_id}' with directionality '{track_directionality.value}' "
                f"prohibits '{traversal_direction.value}' traversal.",
                context={
                    "track_id": track_id,
                    "link_id": link_id,
                    "track_directionality": track_directionality.value,
                    "traversal_direction": traversal_direction.value,
                },
            )
