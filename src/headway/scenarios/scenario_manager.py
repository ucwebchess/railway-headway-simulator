"""Scenario Manager central facade, lifecycle management, and execution coordinator.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-SCN-001 to P12-SCN-007: Scenario registry, baseline immutability, isolation, and provenance.
- P12-CRE-001 to P12-CRE-005: Creation, duplication, renaming, deletion, and archiving.
- P12-INH-001 to P12-INH-005: Inheritance resolution, override precedence, and conflict detection.
- P12-DIR-001 to P12-DIR-005: Direction parameter management (FORWARD, REVERSE, opposing).
- P12-RES-001 to P12-RES-006: Associated simulation results and invalidation on configuration change.
- P12-CMP-001 to P12-CMP-008: Multi-scenario comparative analytics.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from headway.core.exceptions import (
    ConfigurationError,
    DataValidationError,
    ScenarioError,
    ScenarioNotFoundError,
)
from headway.core.identifiers import normalize_identifier
from headway.data.canonical import CanonicalProject
from headway.infrastructure.direction import RunningDirection
from headway.scenarios.effective_config import EffectiveConfigGenerator, calculate_effective_hash
from headway.scenarios.result_association import ScenarioResultRegistry, ScenarioRunRecord
from headway.scenarios.scenario_comparison import ScenarioComparisonEngine, ScenarioComparisonReport
from headway.scenarios.scenario_models import (
    EffectiveConfiguration,
    ExplicitOverride,
    OverrideAction,
    ScenarioDefinition,
    ScenarioStatus,
    ScenarioType,
)
from headway.scenarios.scenario_validation import ScenarioValidator


class ScenarioManager:
    """P12 Central API: Manages the lifecycle of scenarios and enforces baseline immutability."""

    def __init__(self, baseline_project: CanonicalProject) -> None:
        # Strictly preserve baseline as an immutable deep copy (P12-SCN-002)
        self._baseline_project: CanonicalProject = CanonicalProject.model_validate(
            baseline_project.model_dump()
        )
        self._baseline_dict: Dict[str, Any] = self._baseline_project.model_dump(mode="json")

        self._scenarios: Dict[str, ScenarioDefinition] = {}
        self._config_generator = EffectiveConfigGenerator()
        self._result_registry = ScenarioResultRegistry()

        # Initialize default BASELINE scenario
        base_scn = ScenarioDefinition(
            scenario_id="BASELINE",
            scenario_name="Baseline Configuration",
            description="Authoritative reference configuration imported from baseline project",
            scenario_type=ScenarioType.BASELINE,
            is_baseline=True,
            running_direction=RunningDirection.FORWARD,
            tags=["baseline", "reference"],
        )
        self._scenarios["BASELINE"] = base_scn

    @property
    def baseline_project(self) -> CanonicalProject:
        """P12-SCN-002 & P12-B001: Returns a protected copy of the baseline project."""
        return CanonicalProject.model_validate(self._baseline_dict)

    def get_scenario(self, scenario_id: str) -> ScenarioDefinition:
        """Retrieve a scenario definition by identifier."""
        norm_id = normalize_identifier(scenario_id, id_type="SCENARIO_ID")
        if norm_id not in self._scenarios:
            raise ScenarioNotFoundError(
                f"Scenario '{scenario_id}' does not exist.",
                error_code="ERR_SCN_NOT_FOUND",
                context={"scenario_id": scenario_id},
            )
        return self._scenarios[norm_id]

    def list_scenarios(self, include_archived: bool = False) -> List[ScenarioDefinition]:
        """List registered scenarios, optionally including archived ones."""
        return [
            s for s in self._scenarios.values()
            if include_archived or s.status != ScenarioStatus.ARCHIVED
        ]

    def create_scenario(
        self,
        scenario_id: str,
        scenario_name: str,
        description: str = "",
        base_scenario_id: Optional[str] = "BASELINE",
        scenario_type: ScenarioType = ScenarioType.CUSTOM,
        running_direction: Optional[RunningDirection] = None,
        tags: Optional[List[str]] = None,
    ) -> ScenarioDefinition:
        """P12-CRE-001 & P12-B002: Create a new scenario inheriting from baseline or parent."""
        norm_id = normalize_identifier(scenario_id, id_type="SCENARIO_ID")
        if norm_id in self._scenarios:
            raise ScenarioError(
                f"Scenario '{norm_id}' already exists.",
                error_code="ERR_SCN_DUPLICATE_ID",
                context={"scenario_id": norm_id},
            )

        norm_parent = normalize_identifier(base_scenario_id, id_type="SCENARIO_ID") if base_scenario_id else None
        if norm_parent and norm_parent not in self._scenarios:
            raise ScenarioNotFoundError(
                f"Parent scenario '{base_scenario_id}' not found.",
                error_code="ERR_SCN_NOT_FOUND",
                context={"parent_id": base_scenario_id},
            )

        scn = ScenarioDefinition(
            scenario_id=norm_id,
            scenario_name=scenario_name,
            description=description,
            base_scenario_id=norm_parent,
            scenario_type=scenario_type,
            status=ScenarioStatus.ACTIVE,
            running_direction=running_direction,
            tags=tags or [],
        )
        self._scenarios[norm_id] = scn
        return scn

    def duplicate_scenario(
        self,
        source_scenario_id: str,
        new_scenario_id: str,
        new_name: Optional[str] = None,
        new_description: Optional[str] = None,
    ) -> ScenarioDefinition:
        """P12-CRE-002 & P12-B003: Duplicate an existing scenario with all its overrides."""
        source = self.get_scenario(source_scenario_id)
        norm_new_id = normalize_identifier(new_scenario_id, id_type="SCENARIO_ID")

        if norm_new_id in self._scenarios:
            raise ScenarioError(
                f"Scenario '{norm_new_id}' already exists.",
                error_code="ERR_SCN_DUPLICATE_ID",
            )

        # Deep copy all overrides with updated scenario_id
        cloned_overrides = []
        for ovr in source.overrides:
            ovr_copy = ovr.model_copy(deep=True)
            ovr_copy.scenario_id = norm_new_id
            cloned_overrides.append(ovr_copy)

        new_scn = ScenarioDefinition(
            scenario_id=norm_new_id,
            scenario_name=new_name or f"Copy of {source.scenario_name}",
            description=new_description or source.description,
            base_scenario_id=source.base_scenario_id,
            scenario_type=source.scenario_type,
            status=ScenarioStatus.ACTIVE,
            is_baseline=False,
            running_direction=source.running_direction,
            overrides=cloned_overrides,
            tags=list(source.tags),
            metadata=copy.deepcopy(source.metadata),
        )
        self._scenarios[norm_new_id] = new_scn
        return new_scn

    def rename_scenario(self, scenario_id: str, new_name: str) -> ScenarioDefinition:
        """P12-CRE-003: Rename a scenario without altering identity or overrides."""
        norm_id = normalize_identifier(scenario_id, id_type="SCENARIO_ID")
        scn = self.get_scenario(norm_id)
        if scn.is_baseline or norm_id == "BASELINE":
            raise ScenarioError(
                "Cannot rename the immutable baseline scenario.",
                error_code="ERR_SCN_BASELINE_PROTECTED",
            )
        scn.scenario_name = new_name.strip()
        scn.touch()
        return scn

    def delete_scenario(self, scenario_id: str) -> bool:
        """P12-CRE-004: Delete a scenario with protection against deleting baseline."""
        norm_id = normalize_identifier(scenario_id, id_type="SCENARIO_ID")
        scn = self.get_scenario(norm_id)
        if scn.is_baseline or norm_id == "BASELINE":
            raise ScenarioError(
                "Cannot delete the immutable baseline scenario.",
                error_code="ERR_SCN_BASELINE_PROTECTED",
            )

        # Check if other scenarios inherit from this scenario
        dependents = [s.scenario_id for s in self._scenarios.values() if s.base_scenario_id == norm_id]
        if dependents:
            raise ScenarioError(
                f"Cannot delete scenario '{norm_id}' because child scenarios inherit from it: {dependents}.",
                error_code="ERR_SCN_HAS_DEPENDENTS",
                context={"scenario_id": norm_id, "dependents": dependents},
            )

        del self._scenarios[norm_id]
        self._config_generator.clear_cache()
        return True

    def archive_scenario(self, scenario_id: str) -> ScenarioDefinition:
        """P12-CRE-005: Archive scenario to reduce active clutter."""
        norm_id = normalize_identifier(scenario_id, id_type="SCENARIO_ID")
        scn = self.get_scenario(norm_id)
        if scn.is_baseline:
            raise ScenarioError(
                "Cannot archive the baseline scenario.",
                error_code="ERR_SCN_BASELINE_PROTECTED",
            )
        scn.status = ScenarioStatus.ARCHIVED
        scn.touch()
        return scn

    def add_override(self, scenario_id: str, override: ExplicitOverride) -> None:
        """P12-OVR-001 & P12-B025: Add an override and invalidate prior stale results."""
        norm_id = normalize_identifier(scenario_id, id_type="SCENARIO_ID")
        scn = self.get_scenario(norm_id)
        if scn.is_baseline:
            raise ScenarioError(
                "Cannot add overrides to the immutable baseline scenario.",
                error_code="ERR_SCN_BASELINE_PROTECTED",
            )

        scn.add_override(override)
        # Clear cache for this branch
        self._config_generator.clear_cache()
        # Invalidate results whose effective hash has now changed (P12-RES-002 & P12-B025)
        try:
            new_hash = self.get_effective_hash(norm_id)
            self._result_registry.update_validity_for_scenario(norm_id, new_hash)
        except Exception:
            pass

    def validate_scenario(self, scenario_id: str) -> ValidationReport:
        """P12-VAL-001: Validate scenario definition and overrides against baseline."""
        norm_id = normalize_identifier(scenario_id, id_type="SCENARIO_ID")
        scn = self.get_scenario(norm_id)
        return ScenarioValidator.validate_scenario(scn, self._baseline_dict)

    def remove_override(self, scenario_id: str, override_id: str) -> bool:
        """Remove an override and update configuration hash."""
        scn = self.get_scenario(scenario_id)
        removed = scn.remove_override(override_id)
        if removed:
            self._config_generator.clear_cache()
            new_hash = self.get_effective_hash(scenario_id)
            self._result_registry.update_validity_for_scenario(scenario_id, new_hash)
        return removed

    def set_scenario_direction(self, scenario_id: str, direction: RunningDirection) -> None:
        """P12-DIR-001 & P12-B020: Explicitly configure scenario running direction."""
        scn = self.get_scenario(scenario_id)
        scn.running_direction = direction
        scn.touch()
        self._config_generator.clear_cache()
        new_hash = self.get_effective_hash(scenario_id)
        self._result_registry.update_validity_for_scenario(scenario_id, new_hash)

    def get_effective_configuration(
        self,
        scenario_id: str,
        validate: bool = True,
    ) -> EffectiveConfiguration:
        """P12-EFF-001 to 005 & P12-VAL-004: Generate and validate effective configuration."""
        scn = self.get_scenario(scenario_id)

        if validate:
            from headway.data.validation import Severity
            scn_report = ScenarioValidator.validate_scenario(scn, self._baseline_dict)
            if not scn_report.is_simulation_ready:
                critical_errors = [f.message for f in scn_report.findings if f.severity in (Severity.CRITICAL, Severity.ERROR)]
                raise DataValidationError(
                    f"Scenario '{scenario_id}' failed pre-execution validation: {'; '.join(critical_errors)}",
                    error_code="ERR_SCN_VALIDATION_FAILED",
                    context={"scenario_id": scenario_id, "errors": critical_errors},
                )

        eff_config = self._config_generator.generate_effective_configuration(
            baseline_project=self._baseline_dict,
            scenario=scn,
            scenarios=self._scenarios,
        )

        if validate:
            from headway.data.validation import Severity
            report = ScenarioValidator.validate_effective_configuration(eff_config)
            if not report.is_simulation_ready:
                critical_errors = [f.message for f in report.findings if f.severity in (Severity.CRITICAL, Severity.ERROR)]
                raise DataValidationError(
                    f"Effective configuration for scenario '{scenario_id}' failed validation: {'; '.join(critical_errors)}",
                    error_code="ERR_SCN_INVALID_EFFECTIVE_CONFIG",
                    context={"scenario_id": scenario_id, "errors": critical_errors},
                )

        return eff_config

    def get_effective_hash(self, scenario_id: str) -> str:
        """P12-EFF-004, P12-B009 & P12-B010: Return deterministic SHA-256 hash of effective configuration."""
        eff_config = self.get_effective_configuration(scenario_id, validate=False)
        return eff_config.effective_hash

    def register_simulation_result(
        self,
        scenario_id: str,
        analysis_type: str,
        metrics: Dict[str, Any],
        raw_result: Any = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScenarioRunRecord:
        """P12-RES-001 & P12-B024: Associate simulation results with current effective configuration hash."""
        eff_config = self.get_effective_configuration(scenario_id, validate=True)
        return self._result_registry.register_run(
            scenario_id=scenario_id,
            effective_config_hash=eff_config.effective_hash,
            analysis_type=analysis_type,
            running_direction=eff_config.running_direction,
            metrics=metrics,
            raw_result=raw_result,
            run_id=run_id,
            metadata=metadata,
        )

    def get_simulation_runs(self, scenario_id: str) -> List[ScenarioRunRecord]:
        """P12-RES-003: Retrieve all associated simulation runs."""
        return self._result_registry.get_runs(scenario_id)

    def compare_scenarios(
        self,
        baseline_scenario_id: str,
        compared_scenario_ids: Sequence[str],
        analysis_type: Optional[str] = None,
    ) -> ScenarioComparisonReport:
        """P12-CMP-001 to 008, P12-B021 to B023 & P12-B027: Compare configurations and outputs."""
        all_ids = [baseline_scenario_id] + list(compared_scenario_ids)
        eff_map: Dict[str, EffectiveConfiguration] = {}
        runs_map: Dict[str, ScenarioRunRecord] = {}

        for s_id in all_ids:
            eff_map[s_id] = self.get_effective_configuration(s_id, validate=False)
            latest_run = self._result_registry.get_latest_run(s_id, analysis_type=analysis_type)
            if latest_run:
                runs_map[s_id] = latest_run

        return ScenarioComparisonEngine.compare_scenarios(
            baseline_scenario_id=baseline_scenario_id,
            compared_scenario_ids=compared_scenario_ids,
            effective_configs=eff_map,
            runs_by_scenario=runs_map,
        )

    def export_all_scenarios(self) -> Dict[str, Any]:
        """P12-RES-006: Export complete scenario registry and execution history."""
        results_export = self._result_registry.export_results()
        flat_runs = []
        for runs in results_export.values():
            flat_runs.extend(runs)

        return {
            "baseline_id": "BASELINE",
            "baseline_project_id": self._baseline_project.project_id,
            "scenarios": {s_id: s.model_dump(mode="json") for s_id, s in self._scenarios.items()},
            "results": results_export,
            "simulation_runs": flat_runs,
        }
