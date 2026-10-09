"""Basic scenario management and isolated parameter override engine.

Strictly satisfies RHS-P01-001 § 19:
- Preserves baseline scenario immutability.
- Applies scalar parameter overrides deterministically to an isolated copy.
- Validates target domain, object ID, and parameter name.
- Generates an isolated effective CanonicalProject.
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from headway.core.exceptions import ConfigurationError, DataValidationError
from headway.data.canonical import (
    CanonicalProject,
    Scenario,
    ScenarioOverride,
)


def apply_scenario_overrides(
    baseline_project: CanonicalProject,
    scenario: Scenario,
) -> CanonicalProject:
    """Create an isolated effective CanonicalProject with scenario overrides applied.

    The baseline_project instance remains strictly immutable and unmodified.
    """
    if scenario.is_baseline:
        # Return deep copy of baseline without modifications
        return CanonicalProject.model_validate(baseline_project.model_dump())

    # Deep copy project dictionary
    project_dict = baseline_project.model_dump()

    # Apply overrides in sequence
    for override in scenario.overrides:
        _apply_single_override(project_dict, override, scenario.scenario_id)

    # Re-instantiate and validate resulting canonical model
    try:
        effective_project = CanonicalProject.model_validate(project_dict)
    except ValidationError as err:
        raise DataValidationError(
            f"Applying overrides for scenario '{scenario.scenario_id}' resulted in an invalid project model: {err}",
            error_code="ERR_SCN_INVALID_EFFECTIVE_MODEL",
            technical_details=str(err),
            context={"scenario_id": scenario.scenario_id},
        ) from err

    # Record scenario provenance
    effective_project.provenance["effective_scenario_id"] = scenario.scenario_id
    effective_project.provenance["parent_baseline_project_id"] = baseline_project.project_id

    return effective_project


def _apply_single_override(
    project_dict: Dict[str, Any],
    override: ScenarioOverride,
    scenario_id: str,
) -> None:
    """Apply a single scalar override to the project dictionary in place."""
    domain = override.target_domain.strip().lower()
    obj_id = override.target_object_id.strip()
    param = override.parameter_name.strip()
    new_val = override.override_value

    if domain not in project_dict:
        raise ConfigurationError(
            f"Scenario '{scenario_id}' references unknown target domain '{domain}'.",
            error_code="ERR_SCN_UNKNOWN_DOMAIN",
            context={"scenario_id": scenario_id, "domain": domain},
        )

    domain_data = project_dict[domain]
    found = False

    # Find list or object containing the target object ID
    if isinstance(domain_data, dict):
        for key, value in domain_data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item_id = _extract_object_id(item, collection_name=key)
                        if item_id == obj_id:
                            if param not in item:
                                raise ConfigurationError(
                                    f"Parameter '{param}' does not exist on object '{obj_id}' in domain '{domain}'.",
                                    error_code="ERR_SCN_UNKNOWN_PARAM",
                                    context={"object_id": obj_id, "param": param},
                                )
                            # Convert scalar value if necessary
                            item[param] = _cast_override_value(item[param], new_val)
                            found = True
                            break
            elif isinstance(value, dict) and _extract_object_id(value, collection_name=key) == obj_id:
                if param not in value:
                    raise ConfigurationError(
                        f"Parameter '{param}' does not exist on object '{obj_id}'.",
                        error_code="ERR_SCN_UNKNOWN_PARAM",
                    )
                value[param] = _cast_override_value(value[param], new_val)
                found = True
                break

    if not found:
        raise ConfigurationError(
            f"Target object '{obj_id}' not found in domain '{domain}' for scenario '{scenario_id}'.",
            error_code="ERR_SCN_TARGET_NOT_FOUND",
            context={"scenario_id": scenario_id, "domain": domain, "object_id": obj_id},
        )


PRIMARY_ID_MAP = {
    "nodes": "node_id",
    "tracks": "track_id",
    "track_links": "link_id",
    "stations": "station_id",
    "platforms": "platform_id",
    "stopping_points": "stopping_point_id",
    "tunnels": "tunnel_id",
    "tvs_sections": "tvs_id",
    "shared_resource_groups": "group_id",
    "signals": "signal_id",
    "blocks": "block_id",
    "routes": "route_id",
    "train_types": "train_type_id",
    "service_patterns": "service_pattern_id",
    "analyses": "analysis_id",
    "scenarios": "scenario_id",
}


def _extract_object_id(item: Dict[str, Any], collection_name: Optional[str] = None) -> Optional[str]:
    """Find primary identifier in dictionary, respecting collection context."""
    if collection_name and collection_name in PRIMARY_ID_MAP:
        primary_key = PRIMARY_ID_MAP[collection_name]
        if primary_key in item and item[primary_key] is not None:
            return str(item[primary_key])

    for key in ("id", "node_id", "link_id", "track_id", "station_id", "platform_id",
                "stopping_point_id", "tunnel_id", "tvs_id", "group_id", "signal_id",
                "block_id", "route_id", "train_type_id", "service_pattern_id", "analysis_id", "scenario_id"):
        if key in item and item[key] is not None:
            return str(item[key])
    return None


def _cast_override_value(original_val: Any, new_val: Any) -> Any:
    """Cast new_val to match the type of original_val."""
    if original_val is None:
        return new_val
    target_type = type(original_val)
    if isinstance(original_val, bool):
        if isinstance(new_val, bool):
            return new_val
        return str(new_val).strip().lower() in {"true", "1", "yes"}
    try:
        return target_type(new_val)
    except (ValueError, TypeError):
        return new_val
