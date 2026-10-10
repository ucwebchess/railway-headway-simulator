"""Simulation result association, provenance tracking, run registry, and invalidation engine.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-RES-001 to P12-RES-006: Result association, validity checking, multiple runs history,
  run identifiers, no-overwrite protection, and export deliverables.
- P12-B024 & P12-B025: Association verification and invalidation on configuration hash changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union

from headway.infrastructure.direction import RunningDirection


class RunStatus(str, Enum):
    """P12-RES-002: Status of an associated simulation run."""

    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"


@dataclass
class ScenarioRunRecord:
    """P12-RES-001 & P12-RES-004: Execution record binding simulation outputs to a scenario configuration."""

    run_id: str
    scenario_id: str
    effective_config_hash: str
    analysis_type: str  # e.g., "HEADWAY", "CAPACITY", "MULTI_TRAIN", "MONTE_CARLO"
    running_direction: RunningDirection
    execution_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: RunStatus = RunStatus.VALID
    metrics: Dict[str, Any] = field(default_factory=dict)
    raw_result: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert run record to serializable dictionary."""
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "effective_config_hash": self.effective_config_hash,
            "analysis_type": self.analysis_type,
            "running_direction": self.running_direction.value if hasattr(self.running_direction, "value") else str(self.running_direction),
            "execution_timestamp": self.execution_timestamp,
            "status": self.status.value,
            "metrics": self.metrics,
            "metadata": self.metadata,
        }


class ScenarioResultRegistry:
    """P12-RES-001 to P12-RES-006: Manages run histories and validates configuration hash matching."""

    def __init__(self) -> None:
        # Maps scenario_id -> list of ScenarioRunRecord
        self._runs_by_scenario: Dict[str, List[ScenarioRunRecord]] = {}

    def register_run(
        self,
        scenario_id: str,
        effective_config_hash: str,
        analysis_type: str,
        running_direction: RunningDirection,
        metrics: Dict[str, Any],
        raw_result: Any = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScenarioRunRecord:
        """P12-RES-001, P12-RES-004 & P12-RES-005: Add a new simulation run without overwriting prior runs."""
        if scenario_id not in self._runs_by_scenario:
            self._runs_by_scenario[scenario_id] = []

        actual_run_id = run_id or f"RUN_{scenario_id}_{analysis_type}_{len(self._runs_by_scenario[scenario_id]) + 1}"
        record = ScenarioRunRecord(
            run_id=actual_run_id,
            scenario_id=scenario_id,
            effective_config_hash=effective_config_hash,
            analysis_type=analysis_type,
            running_direction=running_direction,
            metrics=metrics,
            raw_result=raw_result,
            metadata=metadata or {},
        )
        self._runs_by_scenario[scenario_id].append(record)
        return record

    def get_runs(self, scenario_id: str) -> List[ScenarioRunRecord]:
        """P12-RES-003: Retrieve all runs for a scenario in chronological order."""
        return list(self._runs_by_scenario.get(scenario_id, []))

    def get_latest_run(
        self,
        scenario_id: str,
        analysis_type: Optional[str] = None,
    ) -> Optional[ScenarioRunRecord]:
        """Retrieve most recent run matching scenario and optional analysis type."""
        runs = self._runs_by_scenario.get(scenario_id, [])
        if analysis_type is not None:
            runs = [r for r in runs if r.analysis_type == analysis_type]
        return runs[-1] if runs else None

    def update_validity_for_scenario(
        self,
        scenario_id: str,
        current_effective_hash: str,
    ) -> int:
        """P12-RES-002 & P12-B025: Invalidate runs whose recorded configuration hash no longer matches current."""
        invalidated_count = 0
        runs = self._runs_by_scenario.get(scenario_id, [])
        for run in runs:
            if run.effective_config_hash != current_effective_hash:
                if run.status != RunStatus.STALE:
                    run.status = RunStatus.STALE
                    invalidated_count += 1
            else:
                run.status = RunStatus.VALID
        return invalidated_count

    def export_results(self, scenario_id: Optional[str] = None) -> Dict[str, Any]:
        """P12-RES-006: Export run records to dictionary format."""
        if scenario_id is not None:
            return {scenario_id: [r.to_dict() for r in self._runs_by_scenario.get(scenario_id, [])]}
        return {
            s_id: [r.to_dict() for r in runs]
            for s_id, runs in self._runs_by_scenario.items()
        }
