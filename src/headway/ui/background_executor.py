"""Background simulation executor and task management.

Milestone P15 — Background Execution & Progress Reporting (P15-EXE-001 to P15-EXE-007).
Executes long-running simulation operations in worker threads to prevent UI freezing.
"""

from concurrent.futures import Future, ThreadPoolExecutor
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from headway.data.canonical import CanonicalProject
from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_models import ReportDocument
from headway.reporting.result_models import SimulationResultPackage
from headway.ui.progress import ProgressState, ProgressTracker
from headway.ui.simulation_runner import SimulationRunner

logger = logging.getLogger("headway.ui.background_executor")


class BackgroundExecutor:
    """Manages asynchronous simulation tasks, progress monitoring, and cancellation."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="HeadwaySim")
        self._lock = threading.Lock()
        self._active_future: Optional[Future] = None
        self._active_tracker: Optional[ProgressTracker] = None
        self._active_task_id: Optional[str] = None
        self._last_result: Optional[Tuple[SimulationResultPackage, ReportDocument]] = None

    def start_simulation(
        self,
        project: CanonicalProject,
        running_direction: RunningDirection = RunningDirection.FORWARD,
        simulation_mode: str = "Full Integrated Suite",
        scenario_id: str = "BASELINE",
    ) -> str:
        """Starts a simulation task in the background worker thread."""
        with self._lock:
            if self._active_future and not self._active_future.done():
                raise RuntimeError("A simulation is already in progress. Please wait or cancel the running task.")

            task_id = f"task_{scenario_id}_{running_direction.value}"
            tracker = ProgressTracker(task_id=task_id)
            self._active_task_id = task_id
            self._active_tracker = tracker

            def _worker() -> Tuple[SimulationResultPackage, ReportDocument]:
                try:
                    res = SimulationRunner.run_simulation_pipeline(
                        project=project,
                        running_direction=running_direction,
                        simulation_mode=simulation_mode,
                        scenario_id=scenario_id,
                        tracker=tracker,
                    )
                    with self._lock:
                        self._last_result = res
                    return res
                except Exception as e:
                    logger.error("Simulation background task failed: %s", e)
                    tracker.fail(str(e))
                    raise

            future = self._executor.submit(_worker)
            self._active_future = future
            return task_id

    def submit(
        self,
        name: str,
        target_fn: Callable[..., Any],
        *args: Any,
        tracker: Optional[ProgressTracker] = None,
        **kwargs: Any,
    ) -> str:
        """Submits a custom background task to the executor."""
        with self._lock:
            task_id = f"task_{name}_{int(time.time() * 1000)}"
            self._active_task_id = task_id
            if tracker:
                self._active_tracker = tracker

            def _runner() -> Any:
                try:
                    if tracker:
                        return target_fn(tracker, *args, **kwargs)
                    return target_fn(*args, **kwargs)
                except Exception as exc:
                    if tracker:
                        tracker.fail(str(exc))
                    raise

            self._active_future = self._executor.submit(_runner)
            return task_id

    def cancel_active_task(self) -> bool:
        """Request cancellation of the currently running simulation."""
        with self._lock:
            if self._active_tracker and self._active_future and not self._active_future.done():
                self._active_tracker.request_cancellation()
                return True
            return False

    def cancel(self, task_id: Optional[str] = None) -> bool:
        """Alias for cancel_active_task."""
        return self.cancel_active_task()

    def is_running(self) -> bool:
        """True if a background task is currently active."""
        with self._lock:
            return bool(self._active_future and not self._active_future.done())

    def is_busy(self) -> bool:
        """Alias for is_running."""
        return self.is_running()

    def get_task(self, task_id: str) -> Any:
        """Retrieve task handle by task ID."""
        with self._lock:
            if self._active_task_id == task_id:
                return self._active_future
            return None

    def get_progress(self) -> Optional[ProgressState]:
        """Retrieve latest progress snapshot for the active or last task."""
        with self._lock:
            if self._active_tracker:
                return self._active_tracker.get_snapshot()
            return None

    def get_last_result(self) -> Optional[Tuple[SimulationResultPackage, ReportDocument]]:
        """Retrieve completed simulation result."""
        with self._lock:
            return self._last_result

    def shutdown(self, wait: bool = True) -> None:
        """Shuts down the thread pool."""
        self._executor.shutdown(wait=wait)


# Singleton executor instance for the UI session
default_executor = BackgroundExecutor()
