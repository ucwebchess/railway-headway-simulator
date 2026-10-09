"""Switch and junction topology representation.

Strictly satisfies RHS-P02-001 § 14:
- P02-SW-001: Switch identity, physical node location, and permitted movements.
- P02-SW-002: Explicitly defined entry/exit link combinations and positions.
- P02-SW-003: Directional validation (forward permission does not imply reverse permission).
- P02-SW-004: Physical route continuity validation through junctions.
- P02-SW-005: Preserves junction conflict references for P05 interlocking without interlocking logic.
- P02-SW-006: No interlocking state transitions or route locking during P02.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from headway.core.exceptions import InfrastructureError


class SwitchError(InfrastructureError):
    """Raised when switch movement or junction connectivity is invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_SWITCH"


class SwitchPosition(str, Enum):
    """Mechanical switch position state."""

    NORMAL = "NORMAL"
    REVERSE = "REVERSE"


@dataclass(frozen=True)
class SwitchMovement:
    """A permitted movement across a switch between an incoming link and an outgoing link."""

    entry_link_id: str
    exit_link_id: str
    position: SwitchPosition
    max_speed_ms: Optional[float] = None  # Diverging speed restriction if applicable
    description: Optional[str] = None


@dataclass
class Switch:
    """Physical railway switch located at a node."""

    switch_id: str
    node_id: str
    movements: List[SwitchMovement] = field(default_factory=list)
    conflicting_switch_ids: List[str] = field(default_factory=list)
    description: Optional[str] = None

    def add_movement(self, movement: SwitchMovement) -> None:
        self.movements.append(movement)

    def is_movement_permitted(self, entry_link_id: str, exit_link_id: str) -> bool:
        """P02-SW-002 & 003: Check if a movement is explicitly permitted."""
        return any(
            m.entry_link_id == entry_link_id and m.exit_link_id == exit_link_id
            for m in self.movements
        )

    def get_movement(self, entry_link_id: str, exit_link_id: str) -> Optional[SwitchMovement]:
        for m in self.movements:
            if m.entry_link_id == entry_link_id and m.exit_link_id == exit_link_id:
                return m
        return None


class JunctionTopology:
    """Maintains network switches, permitted movements, and conflict definitions."""

    def __init__(self) -> None:
        self._switches: Dict[str, Switch] = {}
        self._node_to_switch: Dict[str, str] = {}

    def register_switch(self, switch: Switch) -> None:
        self._switches[switch.switch_id] = switch
        self._node_to_switch[switch.node_id] = switch.switch_id

    def get_switch(self, switch_id: str) -> Optional[Switch]:
        return self._switches.get(switch_id)

    def get_switch_at_node(self, node_id: str) -> Optional[Switch]:
        switch_id = self._node_to_switch.get(node_id)
        return self._switches.get(switch_id) if switch_id else None

    def validate_route_movements(self, link_sequence: List[str]) -> List[str]:
        """Validate whether consecutive link transitions conform to permitted switch movements.

        Returns list of error messages for any unauthorized switch movements.
        """
        violations: List[str] = []
        for i in range(len(link_sequence) - 1):
            entry_link = link_sequence[i]
            exit_link = link_sequence[i + 1]

            # Check if any switch governs this pair
            governing_switches = [
                sw for sw in self._switches.values()
                if any(m.entry_link_id == entry_link for m in sw.movements)
            ]

            for sw in governing_switches:
                if not sw.is_movement_permitted(entry_link, exit_link):
                    violations.append(
                        f"Switch '{sw.switch_id}' at node '{sw.node_id}' does not permit movement "
                        f"from link '{entry_link}' to link '{exit_link}'."
                    )
        return violations
