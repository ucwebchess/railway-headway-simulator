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
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Set, Tuple
import warnings

from headway.core.exceptions import OperationalSimulationError
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory
from headway.simulation.service_instance import TrainServiceInstance
from headway.simulation.state import DynamicMode, OperationalState

if TYPE_CHECKING:
    from headway.infrastructure.route import Route
    from headway.signalling.coordinator import SignallingCoordinator
    from headway.signalling.resources import ManagedResource


# ==============================================================================
# v1.15.0 (#69): direction-aware origin entry block selection
# ==============================================================================

#: Minimum entry-gap warning threshold [m]; the effective threshold is max(train length, this).
ENTRY_GAP_WARNING_M: float = 100.0
WARNING_ENTRY_GAP: str = "WARNING_ENTRY_GAP"


class EntryGapWarning(UserWarning):
    """v1.15.0 (#69): the selected origin entry block starts further from the train's entry point
    than ``max(train length, ENTRY_GAP_WARNING_M)``."""


@dataclass
class EntryBlockSelection:
    """v1.15.0 (#69): result of :func:`select_entry_block`.

    ``block`` is ``None`` when the first route link carries no TRACK_BLOCK (then ``block_entry_m``
    is ``None``, ``gap_m`` is ``inf`` and ``exceeded_warn_threshold`` is ``False``). Distances are
    route distances [m].
    """

    block: Optional["ManagedResource"]
    entry_point_m: float
    block_entry_m: Optional[float]
    gap_m: float
    exceeded_warn_threshold: bool
    warn_threshold_m: float


def select_entry_block(
    route: "Route",
    resources: Mapping[str, "ManagedResource"],
    entry_point_m: float,
    train_length_m: float,
) -> EntryBlockSelection:
    """v1.15.0 (#69): select the origin entry block on the FIRST route link, direction-aware.

    Candidates are the TRACK_BLOCKs with an interval on the first link, plus a block named
    ``BLK_<first link>`` (name fallback, preserved; such a block without intervals on the link is
    entered at the link entry). A block's entry in the direction of travel is its smallest start
    offset on the link (FORWARD traversal) or its largest end offset (REVERSE traversal), mapped to
    a route distance. The selected block is the one whose entry is at or beyond ``entry_point_m``
    and closest to it (ties broken by resource ID, so the result does not depend on registration
    order). If no entry lies at or beyond the entry point, the block whose span on the link
    contains the entry point is selected (gap 0). No candidate on the first link: ``block=None``
    (no reservation at dispatch; no warning).

    ``gap_m = |block_entry_m - entry_point_m|``; the selection is flagged when
    ``gap_m > max(train_length_m, ENTRY_GAP_WARNING_M)``.
    """
    warn_threshold_m = max(float(train_length_m), ENTRY_GAP_WARNING_M)
    ep = float(entry_point_m)
    none = EntryBlockSelection(
        block=None, entry_point_m=ep, block_entry_m=None, gap_m=math.inf,
        exceeded_warn_threshold=False, warn_threshold_m=warn_threshold_m,
    )
    if not route.traversals:
        return none

    first = route.traversals[0]
    first_link_id = first.link_id
    is_reverse = first.direction.is_reverse
    link_entry_s = float(first.start_distance_m)

    entries: List[Tuple[float, str, "ManagedResource"]] = []   # (route entry, id, block)
    spans: List[Tuple[float, float, str, "ManagedResource"]] = []
    for res_id, res in resources.items():
        if res.category != ResourceCategory.TRACK_BLOCK:
            continue
        on_link = [inv for inv in (res.intervals or []) if inv.link_id == first_link_id]
        if on_link:
            if is_reverse:
                off = max(max(inv.start_offset_m, inv.end_offset_m) for inv in on_link)
                far = min(min(inv.start_offset_m, inv.end_offset_m) for inv in on_link)
            else:
                off = min(min(inv.start_offset_m, inv.end_offset_m) for inv in on_link)
                far = max(max(inv.start_offset_m, inv.end_offset_m) for inv in on_link)
            s_entry = first.physical_offset_to_route_distance(max(0.0, min(first.length_m, off)))
            s_far = first.physical_offset_to_route_distance(max(0.0, min(first.length_m, far)))
        elif res_id == f"BLK_{first_link_id}":
            s_entry, s_far = link_entry_s, float(first.end_distance_m)
        else:
            continue
        entries.append((s_entry, res_id, res))
        spans.append((min(s_entry, s_far), max(s_entry, s_far), res_id, res))

    if not entries:
        return none

    ahead = sorted((e for e in entries if e[0] >= ep - 1e-9), key=lambda e: (e[0], e[1]))
    if ahead:
        block_entry_m, _, block = ahead[0]
        gap_m = abs(block_entry_m - ep)
    else:
        containing = sorted((sp for sp in spans if sp[0] - 1e-9 <= ep <= sp[1] + 1e-9), key=lambda sp: (-sp[0], sp[2]))
        if not containing:
            return none
        block_entry_m, block, gap_m = containing[0][0], containing[0][3], 0.0

    return EntryBlockSelection(
        block=block,
        entry_point_m=ep,
        block_entry_m=float(block_entry_m),
        gap_m=float(gap_m),
        exceeded_warn_threshold=bool(gap_m > warn_threshold_m),
        warn_threshold_m=warn_threshold_m,
    )


def _format_entry_gap_warning(selection: EntryBlockSelection, train: TrainServiceInstance) -> str:
    """v1.15.0 (#69): WARNING_ENTRY_GAP message text."""
    return (
        f"{WARNING_ENTRY_GAP}: Train {train.train_id} in {train.running_direction.value} entered route at "
        f"{selection.entry_point_m:.1f} m; first block {selection.block.resource_id} at "
        f"{selection.block_entry_m:.1f} m; gap {selection.gap_m:.1f} m exceeds threshold "
        f"{selection.warn_threshold_m:.1f} m."
    )


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
        # v1.15.0 (#69): WARNING_ENTRY_GAP records, one per (train_id, block_id, direction)
        self.entry_gap_warnings: List[Dict[str, Any]] = []

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

        # 1. Starting signalling block on the first link (v1.15.0 / #69: direction-aware, shared helper)
        selection = select_entry_block(
            route=train.route,
            resources=coordinator.resource_controller.resources,
            entry_point_m=train.current_position_m,
            train_length_m=train.params.length_m,
        )
        if selection.block is not None:
            # First block must be CLEAR or RESERVABLE by this train
            if not coordinator.resource_controller.is_resource_available(selection.block.resource_id, train.train_id, current_time_s):
                return False, f"ENTRY_BLOCK_OCCUPIED_{selection.block.resource_id}"
        if selection.exceeded_warn_threshold:
            self._warn_entry_gap(selection, train)

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

        v1.15.0 (#69): the entry block is reserved FIRST (direction-aware, shared helper
        ``select_entry_block``). ``reserve_resource`` raises ``ResourceConflictError`` if the block is
        unavailable; nothing has been mutated at that point (the train stays queued, without
        departure time, and not RUNNING).
        """
        selection = select_entry_block(
            route=train.route,
            resources=coordinator.resource_controller.resources,
            entry_point_m=train.current_position_m,
            train_length_m=train.params.length_m,
        )
        if selection.block is not None:
            coordinator.resource_controller.reserve_resource(
                train_id=train.train_id,
                resource_id=selection.block.resource_id,
                timestamp_s=current_time_s,
                running_direction=train.running_direction,
            )

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

        # Transition operational state (after the successful reservation above)
        train.operational_state = OperationalState.RUNNING
        train.dynamic_mode = DynamicMode.ACCELERATING
        train.active_waiting_cause = None
        train.waiting_start_time_s = None
        if selection.exceeded_warn_threshold:
            self._warn_entry_gap(selection, train)

        self.dispatched_trains.append(train)
        return dep_delay

    def _warn_entry_gap(self, selection: EntryBlockSelection, train: TrainServiceInstance) -> None:
        """v1.15.0 (#69): issue WARNING_ENTRY_GAP (EntryGapWarning) and record it once per
        (train_id, block_id, direction) in ``entry_gap_warnings``."""
        message = _format_entry_gap_warning(selection, train)
        warnings.warn(message, EntryGapWarning, stacklevel=3)
        key = (train.train_id, selection.block.resource_id, train.running_direction.value)
        if any((w["train_id"], w["block_id"], w["direction"]) == key for w in self.entry_gap_warnings):
            return
        self.entry_gap_warnings.append({
            "code": WARNING_ENTRY_GAP,
            "train_id": train.train_id,
            "block_id": selection.block.resource_id,
            "direction": train.running_direction.value,
            "entry_point_m": round(selection.entry_point_m, 3),
            "block_entry_m": round(selection.block_entry_m, 3),
            "gap_m": round(selection.gap_m, 3),
            "warn_threshold_m": round(selection.warn_threshold_m, 3),
            "message": message,
        })

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
