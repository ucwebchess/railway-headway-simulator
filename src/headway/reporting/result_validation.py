"""Simulation result validation and diagnostic reporting engine.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 4 & § 28).
Satisfies:
- P13-RES-007: Result Validation before chart generation.
- Production of structured diagnostics instead of empty or misleading figures.
- Strict verification of time monotonicity, distance progression, finite numbers,
  and directional integrity.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Union

from headway.core.exceptions import DataValidationError
from headway.data.validation import Severity
from headway.infrastructure.direction import RunningDirection
from headway.reporting.result_models import SimulationResultPackage
from headway.simulation.trajectory import TrainTrajectory


class DiagnosticCode(str, Enum):
    """Standardized diagnostic error and warning codes for simulation results."""

    MISSING_IDENTITY = "DIAG_MISSING_IDENTITY"
    INVALID_DIRECTION = "DIAG_INVALID_DIRECTION"
    EMPTY_TRAJECTORY = "DIAG_EMPTY_TRAJECTORY"
    NON_MONOTONIC_TIME = "DIAG_NON_MONOTONIC_TIME"
    NON_MONOTONIC_DISTANCE = "DIAG_NON_MONOTONIC_DISTANCE"
    NON_FINITE_VALUE = "DIAG_NON_FINITE_VALUE"
    INVALID_INTERVAL = "DIAG_INVALID_INTERVAL"
    INVALID_HEADWAY = "DIAG_INVALID_HEADWAY"
    INVALID_MATRIX = "DIAG_INVALID_MATRIX"
    DIRECTION_MISMATCH = "DIAG_DIRECTION_MISMATCH"
    EMPTY_RESOURCE_LIST = "DIAG_EMPTY_RESOURCE_LIST"
    MISSING_DATASET = "DIAG_MISSING_DATASET"


@dataclass(frozen=True)
class ResultDiagnostic:
    """Structured diagnostic finding from result dataset validation."""

    code: DiagnosticCode
    severity: Severity
    message: str
    field_name: Optional[str] = None
    target_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "message": self.message,
            "field_name": self.field_name,
            "target_id": self.target_id,
            "context": self.context,
        }


@dataclass
class ResultValidationReport:
    """Consolidated validation report for simulation results prior to charting."""

    diagnostics: List[ResultDiagnostic] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if no CRITICAL or ERROR diagnostics are present."""
        return not any(d.severity in (Severity.CRITICAL, Severity.ERROR) for d in self.diagnostics)

    @property
    def has_critical(self) -> bool:
        return any(d.severity == Severity.CRITICAL for d in self.diagnostics)

    @property
    def error_messages(self) -> List[str]:
        return [d.message for d in self.diagnostics if d.severity in (Severity.CRITICAL, Severity.ERROR)]

    def add_diagnostic(
        self,
        code: DiagnosticCode,
        severity: Severity,
        message: str,
        field_name: Optional[str] = None,
        target_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.diagnostics.append(
            ResultDiagnostic(
                code=code,
                severity=severity,
                message=message,
                field_name=field_name,
                target_id=target_id,
                context=context or {},
            )
        )


class ResultValidator:
    """Validates simulation result packages and standalone datasets prior to visualization."""

    @classmethod
    def validate_result_package(
        cls,
        package: SimulationResultPackage,
        raise_on_error: bool = False,
    ) -> ResultValidationReport:
        """Validate comprehensive SimulationResultPackage."""
        report = ResultValidationReport()

        # 1. Identity validation
        if not package.run_id or not str(package.run_id).strip():
            report.add_diagnostic(
                code=DiagnosticCode.MISSING_IDENTITY,
                severity=Severity.CRITICAL,
                message="Simulation result package is missing required 'run_id'.",
                field_name="run_id",
            )
        if not package.scenario_id or not str(package.scenario_id).strip():
            report.add_diagnostic(
                code=DiagnosticCode.MISSING_IDENTITY,
                severity=Severity.CRITICAL,
                message="Simulation result package is missing required 'scenario_id'.",
                field_name="scenario_id",
            )
        if not package.effective_config_hash or not str(package.effective_config_hash).strip():
            report.add_diagnostic(
                code=DiagnosticCode.MISSING_IDENTITY,
                severity=Severity.CRITICAL,
                message="Simulation result package is missing required 'effective_config_hash'.",
                field_name="effective_config_hash",
            )

        # 2. Running direction validation
        if not isinstance(package.running_direction, RunningDirection):
            report.add_diagnostic(
                code=DiagnosticCode.INVALID_DIRECTION,
                severity=Severity.CRITICAL,
                message=f"Invalid running direction: expected RunningDirection enum, got {type(package.running_direction).__name__}.",
                field_name="running_direction",
            )

        # 3. Trajectories validation
        for train_id, traj in package.trajectories.items():
            cls.validate_trajectory(traj, report=report)

        # 4. Blocking intervals validation
        for interval in package.blocking_intervals:
            if interval.end_time_s < interval.start_time_s:
                report.add_diagnostic(
                    code=DiagnosticCode.INVALID_INTERVAL,
                    severity=Severity.CRITICAL,
                    message=f"Blocking interval '{interval.interval_id}' has end_time ({interval.end_time_s}) < start_time ({interval.start_time_s}).",
                    target_id=interval.interval_id,
                )

        if raise_on_error and not report.is_valid:
            raise DataValidationError(
                f"Result package validation failed: {'; '.join(report.error_messages)}",
                error_code="ERR_VIS_VALIDATION_FAILED",
                context={"errors": [d.to_dict() for d in report.diagnostics]},
            )

        return report

    @classmethod
    def validate_trajectory(
        cls,
        trajectory: TrainTrajectory,
        report: Optional[ResultValidationReport] = None,
        raise_on_error: bool = False,
    ) -> ResultValidationReport:
        """Validate standalone TrainTrajectory."""
        rep = report or ResultValidationReport()

        if not trajectory.samples:
            rep.add_diagnostic(
                code=DiagnosticCode.EMPTY_TRAJECTORY,
                severity=Severity.CRITICAL,
                message=f"Train trajectory '{trajectory.train_id}' contains zero samples.",
                target_id=trajectory.train_id,
            )
            if raise_on_error and not rep.is_valid:
                raise DataValidationError(
                    f"Trajectory validation failed: {'; '.join(rep.error_messages)}",
                    error_code="ERR_VIS_EMPTY_TRAJECTORY",
                )
            return rep

        prev_time = -1e9
        prev_dist = -1e9

        for idx, sample in enumerate(trajectory.samples):
            # Check numerical finiteness
            for val, name in (
                (sample.time_s, "time_s"),
                (sample.front_distance_m, "front_distance_m"),
                (sample.speed_ms, "speed_ms"),
                (sample.acceleration_ms2, "acceleration_ms2"),
            ):
                if not math.isfinite(val):
                    rep.add_diagnostic(
                        code=DiagnosticCode.NON_FINITE_VALUE,
                        severity=Severity.CRITICAL,
                        message=f"Non-finite {name} ({val}) encountered in trajectory '{trajectory.train_id}' at sample index {idx}.",
                        target_id=trajectory.train_id,
                        context={"sample_index": idx, "field": name},
                    )

            # Monotonic time check
            if sample.time_s < prev_time - 1e-6:
                rep.add_diagnostic(
                    code=DiagnosticCode.NON_MONOTONIC_TIME,
                    severity=Severity.CRITICAL,
                    message=f"Non-monotonic time detected in trajectory '{trajectory.train_id}' at index {idx}: {sample.time_s} < {prev_time}.",
                    target_id=trajectory.train_id,
                    context={"sample_index": idx, "time": sample.time_s, "prev_time": prev_time},
                )
            prev_time = sample.time_s

            # Non-negative speed check
            if sample.speed_ms < -1e-3:
                rep.add_diagnostic(
                    code=DiagnosticCode.NON_FINITE_VALUE,
                    severity=Severity.WARNING,
                    message=f"Negative speed ({sample.speed_ms:.2f} m/s) in trajectory '{trajectory.train_id}' at index {idx}.",
                    target_id=trajectory.train_id,
                )

            # Monotonic distance check based on running direction
            if trajectory.running_direction == RunningDirection.FORWARD:
                if sample.front_distance_m < prev_dist - 1e-3:
                    rep.add_diagnostic(
                        code=DiagnosticCode.NON_MONOTONIC_DISTANCE,
                        severity=Severity.CRITICAL,
                        message=f"Non-monotonic distance in forward trajectory '{trajectory.train_id}' at index {idx}: {sample.front_distance_m:.1f} < {prev_dist:.1f}.",
                        target_id=trajectory.train_id,
                        context={"sample_index": idx, "dist": sample.front_distance_m, "prev_dist": prev_dist},
                    )
            elif trajectory.running_direction == RunningDirection.REVERSE:
                if prev_dist != -1e9 and sample.front_distance_m > prev_dist + 1e-3:
                    rep.add_diagnostic(
                        code=DiagnosticCode.NON_MONOTONIC_DISTANCE,
                        severity=Severity.CRITICAL,
                        message=f"Non-monotonic distance in reverse trajectory '{trajectory.train_id}' at index {idx}: {sample.front_distance_m:.1f} > {prev_dist:.1f}.",
                        target_id=trajectory.train_id,
                        context={"sample_index": idx, "dist": sample.front_distance_m, "prev_dist": prev_dist},
                    )
            prev_dist = sample.front_distance_m

        if raise_on_error and not rep.is_valid:
            raise DataValidationError(
                f"Trajectory validation failed: {'; '.join(rep.error_messages)}",
                error_code="ERR_VIS_TRAJECTORY_INVALID",
                context={"errors": [d.to_dict() for d in rep.diagnostics]},
            )

        return rep
