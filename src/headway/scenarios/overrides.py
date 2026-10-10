"""Parameter override navigation, type casting, geometry handling, and in-place application.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-OVR-001 to P12-OVR-007: Explicit parameter overrides, dot-separated path navigation,
  value type validation, geometry replacement, and list manipulation.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from headway.core.exceptions import ConfigurationError, DataValidationError
from headway.scenarios.scenario_models import ExplicitOverride, OverrideAction


PRIMARY_ID_MAP: Dict[str, str] = {
    "nodes": "node_id",
    "tracks": "track_id",
    "track_links": "link_id",
    "speed_restrictions": "restriction_id",
    "gradients": "gradient_id",
    "curves": "curve_id",
    "switches": "switch_id",
    "stations": "station_id",
    "platforms": "platform_id",
    "tunnels": "tunnel_id",
    "tvs_sections": "tvs_id",
    "interlockings": "interlocking_id",
    "train_types": "train_type_id",
    "signals": "signal_id",
    "resources": "resource_id",
    "routes": "route_id",
    "services": "service_id",
    "timetables": "timetable_id",
    "stochastic_variables": "variable_id",
    "correlation_groups": "group_id",
    "disruptions": "disruption_id",
}


def _extract_object_id(item: Dict[str, Any], collection_name: str) -> Optional[str]:
    """Extract primary identifier from an item dict using PRIMARY_ID_MAP or standard keys."""
    primary_key = PRIMARY_ID_MAP.get(collection_name)
    if primary_key and primary_key in item:
        return str(item[primary_key])

    for candidate in ("id", "identifier", "name", "code"):
        if candidate in item:
            return str(item[candidate])
    return None


def cast_override_value(expected_example: Any, new_value: Any, value_type: str = "") -> Any:
    """Validate and cast new_value to match expected data type."""
    if expected_example is None and value_type:
        vt = value_type.strip().lower()
        if vt in ("float", "double", "number"):
            return float(new_value)
        elif vt in ("int", "integer"):
            return int(new_value)
        elif vt in ("bool", "boolean"):
            if isinstance(new_value, str):
                return new_value.strip().lower() in ("true", "1", "yes")
            return bool(new_value)
        elif vt == "str":
            return str(new_value)
        return new_value

    if isinstance(expected_example, bool):
        if isinstance(new_value, str):
            return new_value.strip().lower() in ("true", "1", "yes")
        return bool(new_value)
    elif isinstance(expected_example, int) and not isinstance(expected_example, bool):
        return int(new_value)
    elif isinstance(expected_example, float):
        return float(new_value)
    elif isinstance(expected_example, str):
        return str(new_value)
    elif isinstance(expected_example, list):
        if isinstance(new_value, list):
            return new_value
        return [new_value]
    elif isinstance(expected_example, dict):
        if isinstance(new_value, dict):
            return new_value
        raise ValueError(f"Expected dict value but got {type(new_value).__name__}.")
    return new_value


def get_nested_target(
    container: Any,
    path_segments: List[str],
) -> Tuple[Any, Union[str, int]]:
    """Traverse container along path_segments, returning (parent, final_key)."""
    curr = container
    for seg in path_segments[:-1]:
        if isinstance(curr, dict):
            if seg not in curr:
                raise KeyError(f"Key '{seg}' not found in dictionary.")
            curr = curr[seg]
        elif isinstance(curr, list):
            try:
                idx = int(seg)
                curr = curr[idx]
            except (ValueError, IndexError) as err:
                raise KeyError(f"Invalid list index '{seg}': {err}") from err
        else:
            raise KeyError(f"Cannot navigate segment '{seg}' on primitive type {type(curr).__name__}.")

    final_key: Union[str, int] = path_segments[-1]
    if isinstance(curr, list):
        try:
            final_key = int(final_key)
        except ValueError as err:
            raise KeyError(f"Expected integer list index for '{final_key}': {err}") from err

    return curr, final_key


class OverrideNavigator:
    """Navigates canonical project structures and applies targeted overrides."""

    @classmethod
    def apply_override(
        cls,
        project_dict: Dict[str, Any],
        override: ExplicitOverride,
    ) -> None:
        """P12-OVR-001 to 007: Apply a single explicit override to project_dict in place."""
        domain = override.dataset_type.strip().lower()
        obj_id = override.object_id.strip()
        path = override.parameter_path.strip()

        # Handle top-level or domain-level direct parameters (e.g. running_direction, stochastic)
        if obj_id in ("GLOBAL", "PROJECT", "ROOT"):
            if domain in ("global", "project", "root", ""):
                target_container = project_dict
            else:
                if domain not in project_dict or not isinstance(project_dict[domain], dict):
                    project_dict[domain] = {}
                target_container = project_dict[domain]
            cls._apply_to_path(target_container, path, override)
            return

        if domain not in project_dict:
            raise ConfigurationError(
                f"Unknown dataset domain '{domain}' in override '{override.override_id}'.",
                error_code="ERR_SCN_UNKNOWN_DOMAIN",
                context={"domain": domain, "override_id": override.override_id},
            )

        domain_data = project_dict[domain]
        target_obj = cls._find_object_by_id(domain_data, obj_id)

        if target_obj is None:
            raise ConfigurationError(
                f"Target object '{obj_id}' not found in domain '{domain}' for override '{override.override_id}'.",
                error_code="ERR_SCN_TARGET_NOT_FOUND",
                context={"domain": domain, "object_id": obj_id, "override_id": override.override_id},
            )

        cls._apply_to_path(target_obj, path, override)

    @classmethod
    def _find_object_by_id(cls, domain_data: Any, target_id: str) -> Optional[Dict[str, Any]]:
        """Search collections inside domain_data for an object matching target_id."""
        if isinstance(domain_data, dict):
            for coll_name, coll_val in domain_data.items():
                if isinstance(coll_val, list):
                    for item in coll_val:
                        if isinstance(item, dict) and _extract_object_id(item, coll_name) == target_id:
                            return item
                elif isinstance(coll_val, dict):
                    if _extract_object_id(coll_val, coll_name) == target_id:
                        return coll_val
                    # Sub-collections
                    found = cls._find_object_by_id(coll_val, target_id)
                    if found is not None:
                        return found
        return None

    @classmethod
    def _apply_to_path(
        cls,
        target: Any,
        parameter_path: str,
        override: ExplicitOverride,
    ) -> None:
        """Apply new value at parameter_path respecting action (REPLACE, ADD, REMOVE)."""
        segments = parameter_path.split(".")
        try:
            parent, key = get_nested_target(target, segments)
        except KeyError as err:
            raise ConfigurationError(
                f"Parameter path '{parameter_path}' invalid on object '{override.object_id}': {err}",
                error_code="ERR_SCN_UNKNOWN_PARAM",
                context={"object_id": override.object_id, "path": parameter_path},
            ) from err

        action = override.action
        new_val = override.new_value

        if action == OverrideAction.REPLACE:
            if isinstance(parent, dict):
                expected = parent.get(key)
                parent[key] = cast_override_value(expected, new_val, override.value_type)
            elif isinstance(parent, list) and isinstance(key, int):
                expected = parent[key] if 0 <= key < len(parent) else None
                parent[key] = cast_override_value(expected, new_val, override.value_type)
        elif action == OverrideAction.ADD:
            # Add to list or update dict
            target_coll = parent[key] if isinstance(parent, dict) and key in parent else parent
            if isinstance(target_coll, list):
                target_coll.append(new_val)
            elif isinstance(target_coll, dict) and isinstance(new_val, dict):
                target_coll.update(new_val)
            else:
                raise ConfigurationError(
                    f"ADD action requires target to be list or dict (got {type(target_coll).__name__}).",
                    error_code="ERR_SCN_ACTION_MISMATCH",
                )
        elif action == OverrideAction.REMOVE:
            if isinstance(parent, dict):
                if key in parent:
                    del parent[key]
            elif isinstance(parent, list) and isinstance(key, int):
                if 0 <= key < len(parent):
                    parent.pop(key)
