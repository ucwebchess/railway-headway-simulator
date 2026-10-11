"""Progress tracking and cancellation management for long-running operations.

Milestone P15 — Background Execution & Progress Reporting (P15-EXE-002, P15-EXE-003).
"""

from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Dict, List, Optional


class OperationCancelledException(Exception):
    """Raised when an operation was cancelled by the user."""
    pass


@dataclass
class ProgressState:
    """Snapshot of current execution progress."""

    task_id: str
    stage: str = "Initialized"
    percent: float = 0.0
    current_step: int = 0
    total_steps: int = 100
    status_message: str = "Pending"
    elapsed_time_s: float = 0.0
    estimated_remaining_s: Optional[float] = None
    is_running: bool = False
    is_completed: bool = False
    is_cancelled: bool = False
    is_failed: bool = False
    error_message: Optional[str] = None
    logs: List[str] = field(default_factory=list)


class ProgressTracker:
    """Thread-safe progress tracking and cancellation controller."""

    def __init__(self, task_id: str = "default_task") -> None:
        self.task_id = task_id
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._start_time: float = time.time()
        self._state = ProgressState(task_id=task_id)

    def start(self, stage: str = "Starting", total_steps: int = 100) -> None:
        with self._lock:
            self._cancel_event.clear()
            self._start_time = time.time()
            self._state = ProgressState(
                task_id=self.task_id,
                stage=stage,
                percent=0.0,
                current_step=0,
                total_steps=total_steps,
                status_message=stage,
                is_running=True,
                logs=[f"[{time.strftime('%H:%M:%S')}] Task '{self.task_id}' started."],
            )

    def update(
        self,
        current_step: int,
        stage: Optional[str] = None,
        status_message: Optional[str] = None,
        total_steps: Optional[int] = None,
    ) -> None:
        with self._lock:
            if self._cancel_event.is_set():
                raise OperationCancelledException(f"Task '{self.task_id}' was cancelled by user.")

            now = time.time()
            elapsed = now - self._start_time
            if total_steps is not None:
                self._state.total_steps = max(1, total_steps)

            tot = self._state.total_steps
            curr = min(tot, max(0, current_step))
            pct = round((curr / tot) * 100.0, 1)

            est_remaining: Optional[float] = None
            if curr > 0 and pct > 0:
                rate = elapsed / curr
                est_remaining = max(0.0, rate * (tot - curr))

            if stage:
                self._state.stage = stage
            if status_message:
                self._state.status_message = status_message
                self._state.logs.append(f"[{time.strftime('%H:%M:%S')}] {status_message}")

            self._state.current_step = curr
            self._state.percent = pct
            self._state.elapsed_time_s = round(elapsed, 1)
            self._state.estimated_remaining_s = round(est_remaining, 1) if est_remaining else None

    def request_cancellation(self) -> None:
        with self._lock:
            self._cancel_event.set()
            self._state.is_cancelled = True
            self._state.is_running = False
            self._state.status_message = "Cancellation requested by user..."
            self._state.logs.append(f"[{time.strftime('%H:%M:%S')}] Cancellation requested.")

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def check_cancellation(self) -> None:
        if self._cancel_event.is_set():
            raise OperationCancelledException(f"Task '{self.task_id}' was cancelled by user.")

    def complete(self, message: str = "Completed successfully") -> None:
        with self._lock:
            elapsed = time.time() - self._start_time
            self._state.is_running = False
            self._state.is_completed = True
            self._state.percent = 100.0
            self._state.current_step = self._state.total_steps
            self._state.status_message = message
            self._state.elapsed_time_s = round(elapsed, 1)
            self._state.estimated_remaining_s = 0.0
            self._state.logs.append(f"[{time.strftime('%H:%M:%S')}] Task completed in {elapsed:.1f} s.")

    def fail(self, error: str) -> None:
        with self._lock:
            elapsed = time.time() - self._start_time
            self._state.is_running = False
            self._state.is_failed = True
            self._state.error_message = error
            self._state.status_message = f"Failed: {error}"
            self._state.elapsed_time_s = round(elapsed, 1)
            self._state.logs.append(f"[{time.strftime('%H:%M:%S')}] Task FAILED: {error}")

    def get_snapshot(self) -> ProgressState:
        with self._lock:
            return ProgressState(
                task_id=self._state.task_id,
                stage=self._state.stage,
                percent=self._state.percent,
                current_step=self._state.current_step,
                total_steps=self._state.total_steps,
                status_message=self._state.status_message,
                elapsed_time_s=self._state.elapsed_time_s,
                estimated_remaining_s=self._state.estimated_remaining_s,
                is_running=self._state.is_running,
                is_completed=self._state.is_completed,
                is_cancelled=self._state.is_cancelled,
                is_failed=self._state.is_failed,
                error_message=self._state.error_message,
                logs=list(self._state.logs),
            )


ProgressToken = ProgressTracker

