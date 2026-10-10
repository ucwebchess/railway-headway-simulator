"""TVS waiting time, queue formation, and upstream propagation tracking subsystem.

Strictly satisfies RHS-P09-001 § 15 & § 16:
- P09-TVS-010 to 016: TVS waiting time, queue length in trains, maximum queue,
  queue persistence duration, upstream queue propagation, and realistic derivation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from headway.simulation.service_instance import TrainServiceInstance


@dataclass
class TVSQueueSnapshot:
    """Instantaneous snapshot of a TVS section queue."""

    timestamp_s: float
    tvs_id: str
    queue_length: int
    queued_train_ids: List[str]
    upstream_locations: List[str]


@dataclass
class TVSSectionQueueStats:
    """Cumulative queue statistics for an individual TVS section."""

    tvs_id: str
    max_queue_length: int = 0
    total_waiting_time_s: float = 0.0
    queue_start_time_s: Optional[float] = None
    max_queue_duration_s: float = 0.0
    total_queued_trains_count: int = 0
    history: List[TVSQueueSnapshot] = field(default_factory=list)


class TVSQueueTracker:
    """P09-TVS: Tracks waiting queues, persistence durations, and upstream propagation for TVS sections."""

    def __init__(self) -> None:
        self.stats: Dict[str, TVSSectionQueueStats] = {}
        self._active_waiting_trains: Dict[str, Dict[str, float]] = {}  # tvs_id -> {train_id: wait_start_t}

    def _get_or_create_stats(self, tvs_id: str) -> TVSSectionQueueStats:
        if tvs_id not in self.stats:
            self.stats[tvs_id] = TVSSectionQueueStats(tvs_id=tvs_id)
            self._active_waiting_trains[tvs_id] = {}
        return self.stats[tvs_id]

    def record_waiting_train(
        self,
        tvs_id: str,
        train_id: str,
        current_time_s: float,
    ) -> None:
        """P09-TVS-010 & 011: Record a train entering or continuing in a TVS waiting state."""
        st = self._get_or_create_stats(tvs_id)
        waiting_dict = self._active_waiting_trains[tvs_id]

        if train_id not in waiting_dict:
            waiting_dict[train_id] = current_time_s
            st.total_queued_trains_count += 1
            if st.queue_start_time_s is None:
                st.queue_start_time_s = current_time_s

    def release_waiting_train(
        self,
        tvs_id: str,
        train_id: str,
        current_time_s: float,
    ) -> float:
        """Record a train authorized and released from the TVS queue. Returns wait duration."""
        st = self._get_or_create_stats(tvs_id)
        waiting_dict = self._active_waiting_trains.get(tvs_id, {})

        wait_duration = 0.0
        if train_id in waiting_dict:
            start_t = waiting_dict.pop(train_id)
            wait_duration = max(0.0, current_time_s - start_t)
            st.total_waiting_time_s += wait_duration

        if len(waiting_dict) == 0 and st.queue_start_time_s is not None:
            q_dur = current_time_s - st.queue_start_time_s
            if q_dur > st.max_queue_duration_s:
                st.max_queue_duration_s = q_dur
            st.queue_start_time_s = None

        return wait_duration

    def update_snapshot(
        self,
        current_time_s: float,
        active_trains: List[TrainServiceInstance],
    ) -> None:
        """P09-TVS-012 to 015: Update queue lengths, max records, and upstream propagation."""
        train_map = {t.train_id: t for t in active_trains}

        for tvs_id, waiting_dict in self._active_waiting_trains.items():
            st = self.stats[tvs_id]
            q_len = len(waiting_dict)
            if q_len > st.max_queue_length:
                st.max_queue_length = q_len

            if q_len > 0 and st.queue_start_time_s is not None:
                curr_dur = current_time_s - st.queue_start_time_s
                if curr_dur > st.max_queue_duration_s:
                    st.max_queue_duration_s = curr_dur

            # Determine upstream locations of queued trains (P09-TVS-015)
            upstream_locs = []
            for tid in waiting_dict:
                tr = train_map.get(tid)
                if tr:
                    loc = f"dist_{tr.current_position_m:.1f}m"
                    if tr.is_dwelling and tr.dwelling_station_id:
                        loc += f"_station_{tr.dwelling_station_id}"
                    upstream_locs.append(loc)

            st.history.append(
                TVSQueueSnapshot(
                    timestamp_s=current_time_s,
                    tvs_id=tvs_id,
                    queue_length=q_len,
                    queued_train_ids=list(waiting_dict.keys()),
                    upstream_locations=upstream_locs,
                )
            )

    def get_total_waiting_time_s(self) -> float:
        """Aggregate waiting time across all TVS sections."""
        return sum(st.total_waiting_time_s for st in self.stats.values())

    def get_max_observed_queue_length(self) -> int:
        """Global maximum TVS queue length."""
        if not self.stats:
            return 0
        return max(st.max_queue_length for st in self.stats.values())
