"""Effective configuration generation, inheritance resolution, conflict detection, and SHA-256 hashing.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-INH-001 to P12-INH-005: Parent-child inheritance, override precedence, circular inheritance rejection,
  and conflicting override detection.
- P12-EFF-001 to P12-EFF-005: Application order, isolated copy, hash calculation, and configuration caching.
- P12-DIR-001: Direction parameter resolution.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from headway.core.exceptions import (
    CircularInheritanceError,
    ConflictingOverrideError,
    ScenarioNotFoundError,
)
from headway.data.canonical import CanonicalProject
from headway.infrastructure.direction import RunningDirection
from headway.scenarios.overrides import OverrideNavigator
from headway.scenarios.scenario_models import (
    EffectiveConfiguration,
    ExplicitOverride,
    ScenarioDefinition,
)


def calculate_effective_hash(
    project_dict: Dict[str, Any],
    scenario_id: str,
    running_direction: Optional[RunningDirection] = None,
) -> str:
    """P12-EFF-004: Compute a deterministic SHA-256 hex digest of the canonical effective configuration."""
    clean_data = copy.deepcopy(project_dict)
    clean_data.pop("provenance", None)
    clean_data["_effective_scenario_id"] = scenario_id
    if running_direction is not None:
        clean_data["_running_direction"] = str(running_direction.value if hasattr(running_direction, "value") else running_direction)

    canon_bytes = json.dumps(
        clean_data,
        indent=None,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canon_bytes).hexdigest()


class EffectiveConfigGenerator:
    """Generates isolated effective configurations from baseline and scenario hierarchy."""

    def __init__(self) -> None:
        self._cache: Dict[str, EffectiveConfiguration] = {}

    def clear_cache(self) -> None:
        """Clear cached effective configurations."""
        self._cache.clear()

    @staticmethod
    def resolve_inheritance_chain(
        target_scenario_id: str,
        scenarios: Dict[str, ScenarioDefinition],
    ) -> List[str]:
        """P12-INH-001, P12-INH-004 & P12-INH-005: Trace inheritance from root down to target scenario."""
        chain: List[str] = []
        visited: Set[str] = set()
        curr_id: Optional[str] = target_scenario_id

        while curr_id is not None:
            if curr_id in visited:
                cycle_path = " -> ".join(chain + [curr_id])
                raise CircularInheritanceError(
                    f"Circular scenario inheritance detected: {cycle_path}.",
                    error_code="ERR_SCN_CIRCULAR_INHERITANCE",
                    context={"cycle_path": cycle_path, "scenario_id": curr_id},
                )

            visited.add(curr_id)
            chain.append(curr_id)

            scn = scenarios.get(curr_id)
            if scn is None:
                raise ScenarioNotFoundError(
                    f"Parent scenario '{curr_id}' not found in registry.",
                    error_code="ERR_SCN_NOT_FOUND",
                    context={"scenario_id": curr_id},
                )

            curr_id = scn.base_scenario_id

        # Reverse so root / ancestor comes first, target child last
        chain.reverse()
        return chain

    @staticmethod
    def check_conflicting_overrides(overrides: List[ExplicitOverride], scenario_id: str) -> None:
        """P12-INH-003: Detect conflicting overrides targeting the exact same parameter at the same scenario level."""
        seen_targets: Dict[Tuple[str, str, str], ExplicitOverride] = {}

        for ovr in overrides:
            key = (ovr.dataset_type.strip().lower(), ovr.object_id.strip(), ovr.parameter_path.strip())
            if key in seen_targets:
                prior = seen_targets[key]
                # If values or actions differ, this is an unresolved conflict
                if prior.new_value != ovr.new_value or prior.action != ovr.action:
                    raise ConflictingOverrideError(
                        f"Conflicting overrides at same level in scenario '{scenario_id}' "
                        f"targeting domain '{key[0]}', object '{key[1]}', parameter '{key[2]}': "
                        f"value '{prior.new_value}' vs '{ovr.new_value}'.",
                        error_code="ERR_SCN_CONFLICTING_OVERRIDE",
                        context={
                            "scenario_id": scenario_id,
                            "target_domain": key[0],
                            "object_id": key[1],
                            "parameter_path": key[2],
                            "override_1": prior.override_id,
                            "override_2": ovr.override_id,
                        },
                    )
            seen_targets[key] = ovr

    def generate_effective_configuration(
        self,
        baseline_project: Union[CanonicalProject, Dict[str, Any]],
        scenario: ScenarioDefinition,
        scenarios: Dict[str, ScenarioDefinition],
        force_recompute: bool = False,
    ) -> EffectiveConfiguration:
        """P12-EFF-001 to P12-EFF-005: Create isolated effective configuration with applied overrides."""
        # 1. Resolve inheritance chain
        chain = self.resolve_inheritance_chain(scenario.scenario_id, scenarios)

        # 2. Check for conflicting overrides within each scenario along the chain
        for scn_id in chain:
            scn_obj = scenarios.get(scn_id)
            if scn_obj:
                self.check_conflicting_overrides(scn_obj.overrides, scn_id)

        # 3. Deep copy baseline to ensure complete state isolation (P12-EFF-002)
        if isinstance(baseline_project, CanonicalProject):
            project_dict = baseline_project.model_dump(mode="json")
        else:
            project_dict = copy.deepcopy(baseline_project)

        # 4. Resolve running direction: inherit down chain, child overrides parent
        effective_direction: RunningDirection = RunningDirection.FORWARD
        for scn_id in chain:
            scn_obj = scenarios.get(scn_id)
            if scn_obj and scn_obj.running_direction is not None:
                effective_direction = scn_obj.running_direction

        # 5. Apply overrides in strict precedence order: Parent -> Child (P12-EFF-001)
        applied_overrides: List[ExplicitOverride] = []
        for scn_id in chain:
            scn_obj = scenarios.get(scn_id)
            if not scn_obj:
                continue
            for ovr in scn_obj.overrides:
                OverrideNavigator.apply_override(project_dict, ovr)
                applied_overrides.append(ovr)

        # 6. Compute deterministic SHA-256 hash (P12-EFF-004)
        eff_hash = calculate_effective_hash(
            project_dict=project_dict,
            scenario_id=scenario.scenario_id,
            running_direction=effective_direction,
        )

        # Check cache if not force recompute
        if not force_recompute and eff_hash in self._cache:
            return self._cache[eff_hash]

        # 7. Record provenance in project dict
        if "provenance" not in project_dict or not isinstance(project_dict["provenance"], dict):
            project_dict["provenance"] = {}

        project_dict["provenance"]["effective_scenario_id"] = scenario.scenario_id
        project_dict["provenance"]["effective_configuration_hash"] = eff_hash
        project_dict["provenance"]["inheritance_chain"] = chain
        project_dict["provenance"]["applied_overrides_count"] = len(applied_overrides)
        project_dict["provenance"]["effective_running_direction"] = str(
            effective_direction.value if hasattr(effective_direction, "value") else effective_direction
        )

        eff_config = EffectiveConfiguration(
            scenario_id=scenario.scenario_id,
            effective_hash=eff_hash,
            project_dict=project_dict,
            applied_overrides=applied_overrides,
            inheritance_chain=chain,
            running_direction=effective_direction,
            is_valid=True,
            details={
                "chain_length": len(chain),
                "overrides_count": len(applied_overrides),
            },
        )

        # Cache by hash (P12-EFF-005)
        self._cache[eff_hash] = eff_config
        return eff_config
