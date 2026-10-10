"""Dispatching policies and origin departure management subsystem.

Strictly satisfies RHS-P09-001 § 7 & § 8:
- P09-DEP-001 to 006: Requested departure, authorization, actual departure, departure delay,
  origin queue, and independent forward/reverse handling.
- P09-DSP-001 to 007: First-Come-First-Served, Timetable-Order, Priority-Based, Fixed-Sequence,
  deterministic tie-breaking, safety priority, and fairness / starvation monitoring.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from headway.core.exceptions import OperationalSimulationError
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory
from headway.simulation.service_instance import TrainServiceInstance
from headway.simulation.state import DynamicMode, OperationalState

if TYPE_CHECKING:
    from headway.signalling.coordinator import SignallingCoordinator


class DispatchPolicy(str, Enum):
    """P09-DSP: Configurable deterministic dispatching policies."""

    FIRST_COME_FIRST_SERVED = "FIRST_COME_FIRST_SERVED"  # Process in arrival / requested departure order
    TIMETABLE_ORDER = "TIMETABLE_ORDER"                  # Strict sequence preservation as scheduled
    PRIORITY_BASED = "PRIORITY_BASED"                    # Highest priority first, tie-breaking by time
    FIXED_SEQUENCE = "FIXED_SEQUENCE"                    # Strictly prescribed static train list order


@dataclass
class DepartureQueueStatus:
    """Instantaneous status snapshot of an origin departure queue."""

    origin_id: str
    running_direction: RunningDirection
    queued_train_ids: List[str]
    longest_waiting_time_s: float
    total_waiting_trains: int


class OriginDepartureQueue:
    """P09-DEP & P09-DSP: Manages train waiting queues at network entry points.

    Enforces that trains awaiting dispatch remain in virtual origin queues and do NOT
    create artificial physical overlap on network track links until authorized.
    """

    def __init__(
        self,
        dispatch_policy: DispatchPolicy = DispatchPolicy.FIRST_COME_FIRST_SERVED,
        starvation_threshold_s: float = 600.0,
    ) -> None:
        self.dispatch_policy = dispatch_policy
        self.starvation_threshold_s = starvation_threshold_s
        self._queues: Dict[str, List[TrainServiceInstance]] = {}  # origin_key -> list of instances
        self.dispatched_trains: List[TrainServiceInstance] = []
        self.starvation_warnings: List[Dict[str, any]] = []

    def _make_origin_key(self, train: TrainServiceInstance) -> str:
        """Derive queue bucket key from first link and direction."""
        first_link = train.route.traversals[0].link_id if train.route.traversals else "UNKNOWN"
        return f"{first_link}_{train.running_direction.value}"

    def enqueue(self, train: TrainServiceInstance) -> None:
        """P09-DEP-005: Add a train to the appropriate origin departure queue."""
        key = self._make_origin_key(train)
        if key not in self._queues:
            self._queues[key] = []
        self._queues[key].append(train)

    def enqueue_all(self, trains: List[TrainServiceInstance]) -> None:
        """Enqueue multiple train instances."""
        for trn in trains:
            self.enqueue(trn)

    def get_queued_trains(self) -> List[TrainServiceInstance]:
        """Return flat list of all currently queued trains across all origins."""
        all_trains = []
        for q in self._queues.values():
            all_trains.extend(q)
        return all_trains

    def is_empty(self) -> bool:
        """Check if all origin queues are empty."""
        return all(len(q) == 0 for q in self._queues.values())

    def get_ready_candidates(
        self,
        origin_key: str,
        current_time_s: float,
    ) -> List[TrainServiceInstance]:
        """P09-DSP-001 to 005: Filter and sort trains ready for departure at current_time_s."""
        queue = self._queues.get(origin_key, [])
        # Ready trains: scheduled departure + primary delay <= current_time_s
        ready = [
            t for t in queue
            if (t.requested_departure_time_s + t.primary_delay_s) <= current_time_s + 1e-6
        ]

        if not ready:
            return []

        # Sort according to configured policy with deterministic tie-breaking (P09-DSP-005)
        if self.dispatch_policy == DispatchPolicy.FIRST_COME_FIRST_SERVED:
            # Sort by effective requested departure, then train_id
            ready.sort(key=lambda t: (t.requested_departure_time_s + t.primary_delay_s, t.train_id))
        elif self.dispatch_policy == DispatchPolicy.PRIORITY_BASED:
            # Sort by negative priority (higher priority first), then requested time, then train_id
            ready.sort(key=lambda t: (-t.priority, t.requested_departure_time_s + t.primary_delay_s, t.train_id))
        elif self.dispatch_policy in (DispatchPolicy.TIMETABLE_ORDER, DispatchPolicy.FIXED_SEQUENCE):
            # Preserve original enqueue order within queue
            order_indices = {id(t): idx for idx, t in enumerate(queue)}
            ready.sort(key=lambda t: (order_indices.get(id(t), 0), t.train_id))

        return ready

    def can_authorize_entry(
        self,
        train: TrainServiceInstance,
        coordinator: SignallingCoordinator,
        current_time_s: float,
    ) -> Tuple[bool, Optional[str]]:
        """P09-DEP-002 & P09-DSP-006: Verify if physical entry resource is available.

        Safety Priority: Dispatching priority shall never bypass signalling safety constraints.
        Returns (is_authorized, reason_if_blocked).
        """
        if not train.route.traversals:
            return False, "EMPTY_ROUTE"

        first_traversal = train.route.traversals[0]
        first_link_id = first_traversal.link_id

        # 1. Identify starting signalling block on first link
        entry_blocks = [
            res for res in coordinator.resource_controller.resources.values()
            if res.category == ResourceCategory.TRACK_BLOCK
        ]
        matching_blocks = [
            b for b in entry_blocks
            if any(inv.link_id == first_link_id for inv in b.intervals) or b.resource_id == f"BLK_{first_link_id}"
        ]

        if matching_blocks:
            # First block must be CLEAR or RESERVABLE by this train
            first_block = matching_blocks[0]
            if not coordinator.resource_controller.is_resource_available(first_block.resource_id, train.train_id, current_time_s):
                return False, f"ENTRY_BLOCK_OCCUPIED_{first_block.resource_id}"

        # 2. Check if route starting signal is RED
        first_sig = coordinator.signal_controller.signals.get(f"SIG_{first_link_id}_START")
        if first_sig and first_sig.current_aspect.value == "RED":
            return False, f"ENTRY_SIGNAL_RED_{first_sig.signal_id}"

        # 3. Check starting platform if route starts directly at a platform
        starting_plat_id = train.assigned_platforms.get("ORIGIN") or train.platform_preferences.get("ORIGIN")
        if starting_plat_id:
            plat_res = coordinator.resource_controller.resources.get(starting_plat_id)
            if plat_res and not coordinator.resource_controller.is_resource_available(starting_plat_id, train.train_id, current_time_s):
                return False, f"ORIGIN_PLATFORM_OCCUPIED_{starting_plat_id}"

        return True, None

    def dispatch_candidate(
        self,
        train: TrainServiceInstance,
        coordinator: SignallingCoordinator,
        current_time_s: float,
    ) -> float:
        """P09-DEP-003 & 004: Execute actual departure and transition train state.

        Returns calculated departure delay D_dep = t_actual - t_requested.
        """
        origin_key = self._make_origin_key(train)
        if origin_key in self._queues and train in self._queues[origin_key]:
            self._queues[origin_key].remove(train)

        # Record departure timestamps and delay
        t_effective_req = train.requested_departure_time_s + train.primary_delay_s
        train.actual_departure_time_s = current_time_s
        dep_delay = max(0.0, current_time_s - t_effective_req)

        # Attribute primary and secondary departure delay
        if train.primary_delay_s > 0.0:
            train.record_delay("PRIMARY_DISTURBANCE", train.primary_delay_s)
        if dep_delay > 0.0:
            train.record_delay("DISPATCH_PRIORITY" if self.dispatch_policy == DispatchPolicy.PRIORITY_BASED else "SIGNALLING", dep_delay)

        # Transition operational state
        train.operational_state = OperationalState.RUNNING
        train.dynamic_mode = DynamicMode.ACCELERATING
        train.active_waiting_cause = None
        train.waiting_start_time_s = None

        # Reserve entry block
        if train.route.traversals:
            first_link_id = train.route.traversals[0].link_id
            for res_id, res in coordinator.resource_controller.resources.items():
                if res.category == ResourceCategory.TRACK_BLOCK and (
                    any(inv.link_id == first_link_id for inv in res.intervals) or res_id == f"BLK_{first_link_id}"
                ):
                    coordinator.resource_controller.reserve_resource(
                        train_id=train.train_id,
                        resource_id=res_id,
                        timestamp_s=current_time_s,
                        running_direction=train.running_direction,
                    )
                    break

        self.dispatched_trains.append(train)
        return dep_delay

    def process_origin_dispatches(
        self,
        coordinator: SignallingCoordinator,
        current_time_s: float,
    ) -> List[TrainServiceInstance]:
        """Evaluate all origin queues and dispatch authorized candidates."""
        dispatched_now: List[TrainServiceInstance] = []

        for origin_key in list(self._queues.keys()):
            ready_trains = self.get_ready_candidates(origin_key, current_time_s)
            if not ready_trains:
                continue

            for candidate in ready_trains:
                # Check fairness / starvation
                wait_time = current_time_s - (candidate.requested_departure_time_s + candidate.primary_delay_s)
                if wait_time > self.starvation_threshold_s:
                    self.starvation_warnings.append({
                        "train_id": candidate.train_id,
                        "origin_key": origin_key,
                        "waiting_time_s": wait_time,
                        "current_time_s": current_time_s,
                    })

                authorized, reason = self.can_authorize_entry(candidate, coordinator, current_time_s)
                if authorized:
                    self.dispatch_candidate(candidate, coordinator, current_time_s)
                    dispatched_now.append(candidate)
                    # Only one train can enter this specific origin track at the same instant
                    break
                else:
                    candidate.active_waiting_cause = reason or "ORIGIN_HOLDING"
                    if candidate.waiting_start_time_s is None:
                        candidate.waiting_start_time_s = current_time_s

        return dispatched_now
