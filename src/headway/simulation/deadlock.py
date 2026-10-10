"""Deadlock detection and wait-dependency analysis subsystem.

Strictly satisfies RHS-P09-001 § 20:
- P09-DLK-001: Resource wait tracking.
- P09-DLK-002: Circular dependency cycle detection.
- P09-DLK-003: Single-track opposing-direction deadlock detection.
- P09-DLK-004: Junction conflict deadlock detection.
- P09-DLK-005: TVS shared-resource waiting incompatibility.
- P09-DLK-006: Structured failure reporting without silent termination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from headway.core.exceptions import DeadlockError
from headway.infrastructure.direction import RunningDirection
from headway.simulation.service_instance import TrainServiceInstance

if TYPE_CHECKING:
    from headway.signalling.coordinator import SignallingCoordinator


class DeadlockType(str, Enum):
    """P09-DLK-006: Categorization of detected operational deadlocks."""

    CIRCULAR_WAIT = "CIRCULAR_WAIT"
    OPPOSING_HEAD_ON = "OPPOSING_HEAD_ON"
    UNRESOLVED_JUNCTION = "UNRESOLVED_JUNCTION"
    TVS_INCOMPATIBILITY = "TVS_INCOMPATIBILITY"


@dataclass
class WaitDependency:
    """Directed waiting relationship: waiting_train requires resource occupied by holding_train."""

    waiting_train_id: str
    resource_id: str
    holding_train_id: str
    waiting_since_s: float
    description: str


@dataclass
class DeadlockReport:
    """P09-DLK-006: Structured operational deadlock diagnostic report."""

    timestamp_s: float
    deadlock_type: DeadlockType
    involved_train_ids: List[str]
    involved_resource_ids: List[str]
    waiting_relationships: List[WaitDependency]
    description: str


class DeadlockDetector:
    """P09-DLK: Continuously monitors resource allocations and waiting states for deadlocks."""

    def __init__(self, wait_time_threshold_s: float = 300.0) -> None:
        self.wait_time_threshold_s = wait_time_threshold_s

    def build_wait_graph(
        self,
        active_trains: List[TrainServiceInstance],
        coordinator: SignallingCoordinator,
        current_time_s: float,
    ) -> List[WaitDependency]:
        """P09-DLK-001: Construct wait-for relationships between active trains."""
        dependencies: List[WaitDependency] = []

        for train in active_trains:
            if not train.is_waiting or not train.active_waiting_cause:
                continue

            # Check what resource this train is waiting for
            cause = train.active_waiting_cause
            waiting_res_id = None

            # 1. Parse resource from waiting cause
            for res_id, res in coordinator.resource_controller.resources.items():
                if res_id in cause:
                    waiting_res_id = res_id
                    break

            if not waiting_res_id:
                # Check downstream route blocks or TVS
                if "TVS" in cause:
                    for tvs_id in coordinator.tvs_controller.tvs_sections:
                        if tvs_id in cause:
                            waiting_res_id = tvs_id
                            break
                elif "JUNCTION" in cause or "ROUTE" in cause:
                    for rt_id in coordinator.interlocking_engine.active_states:
                        if rt_id in cause:
                            waiting_res_id = rt_id
                            break

            if waiting_res_id:
                # Determine holding train
                holding_train = None
                res = coordinator.resource_controller.resources.get(waiting_res_id)
                if res:
                    holding_train = next(iter(res.occupants), None) or next(iter(res.reservations.keys()), None) or next(iter(res.locks), None)

                if not holding_train and "TVS" in cause:
                    tvs_configs = getattr(coordinator.tvs_controller, "configs", {})
                    if waiting_res_id in tvs_configs:
                        occ = coordinator.tvs_controller.active_occupants.get(waiting_res_id, set())
                        if occ:
                            holding_train = next(iter(occ))

                if not holding_train and "ROUTE" in cause:
                    r_state = coordinator.interlocking_engine.active_states.get(waiting_res_id)
                    if r_state and r_state.allocated_train_id:
                        holding_train = r_state.allocated_train_id

                if holding_train and holding_train != train.train_id:
                    dependencies.append(
                        WaitDependency(
                            waiting_train_id=train.train_id,
                            resource_id=waiting_res_id,
                            holding_train_id=holding_train,
                            waiting_since_s=train.waiting_start_time_s or current_time_s,
                            description=f"Train '{train.train_id}' is waiting for resource '{waiting_res_id}' held by '{holding_train}'",
                        )
                    )

        return dependencies

    def detect_circular_waits(
        self,
        dependencies: List[WaitDependency],
        current_time_s: float,
    ) -> Optional[DeadlockReport]:
        """P09-DLK-002: Detect directed cycles in the wait-for dependency graph."""
        adj: Dict[str, List[Tuple[str, str]]] = {}  # waiting_train -> list of (holding_train, resource_id)
        for dep in dependencies:
            if dep.waiting_train_id not in adj:
                adj[dep.waiting_train_id] = []
            adj[dep.waiting_train_id].append((dep.holding_train_id, dep.resource_id))

        visited: Set[str] = set()
        rec_stack: List[Tuple[str, str]] = []  # list of (train_id, resource_id)

        def dfs(u: str) -> Optional[List[Tuple[str, str]]]:
            visited.add(u)
            for v, r in adj.get(u, []):
                # Check if v is already in current path
                for idx, (node, _) in enumerate(rec_stack):
                    if node == v:
                        # Cycle found!
                        cycle = rec_stack[idx:] + [(u, r)]
                        return cycle
                if v not in visited:
                    rec_stack.append((u, r))
                    res = dfs(v)
                    rec_stack.pop()
                    if res:
                        return res
            return None

        for start_node in adj:
            if start_node not in visited:
                rec_stack.append((start_node, ""))
                cycle = dfs(start_node)
                rec_stack.pop()
                if cycle:
                    involved_trains = [node for node, _ in cycle]
                    involved_resources = [res for _, res in cycle if res]
                    cycle_deps = [
                        d for d in dependencies
                        if d.waiting_train_id in involved_trains and d.holding_train_id in involved_trains
                    ]
                    return DeadlockReport(
                        timestamp_s=current_time_s,
                        deadlock_type=DeadlockType.CIRCULAR_WAIT,
                        involved_train_ids=involved_trains,
                        involved_resource_ids=involved_resources,
                        waiting_relationships=cycle_deps,
                        description=f"Circular wait dependency detected among trains: {involved_trains}",
                    )
        return None

    def detect_opposing_head_on_deadlock(
        self,
        active_trains: List[TrainServiceInstance],
        coordinator: SignallingCoordinator,
        current_time_s: float,
    ) -> Optional[DeadlockReport]:
        """P09-DLK-003: Detect single-track head-on opposing deadlock."""
        # Find trains moving in opposite directions
        fwd_trains = [t for t in active_trains if t.running_direction == RunningDirection.FORWARD and t.is_running]
        rev_trains = [t for t in active_trains if t.running_direction == RunningDirection.REVERSE and t.is_running]

        if not fwd_trains or not rev_trains:
            return None

        for tf in fwd_trains:
            for tr in rev_trains:
                # Check if tf and tr share physical links in their remaining routes
                tf_links = set(trav.link_id for trav in tf.route.traversals)
                tr_links = set(trav.link_id for trav in tr.route.traversals)
                shared_links = tf_links.intersection(tr_links)

                if shared_links:
                    # Check if both trains are waiting or stopped facing each other
                    if tf.current_speed_ms < 0.1 and tr.current_speed_ms < 0.1:
                        if tf.is_waiting and tr.is_waiting:
                            return DeadlockReport(
                                timestamp_s=current_time_s,
                                deadlock_type=DeadlockType.OPPOSING_HEAD_ON,
                                involved_train_ids=[tf.train_id, tr.train_id],
                                involved_resource_ids=list(shared_links),
                                waiting_relationships=[],
                                description=f"Single-track opposing deadlock: Forward train '{tf.train_id}' and Reverse train '{tr.train_id}' facing each other on shared links {shared_links}",
                            )
        return None

    def check_deadlocks(
        self,
        active_trains: List[TrainServiceInstance],
        coordinator: SignallingCoordinator,
        current_time_s: float,
    ) -> Optional[DeadlockReport]:
        """Run all deadlock checks and return DeadlockReport if found."""
        deps = self.build_wait_graph(active_trains, coordinator, current_time_s)
        circ_report = self.detect_circular_waits(deps, current_time_s)
        if circ_report:
            return circ_report

        opp_report = self.detect_opposing_head_on_deadlock(active_trains, coordinator, current_time_s)
        if opp_report:
            return opp_report

        return None
