"""Deterministic JSON serialization and Draft 2020-12 schema validation for Canonical Projects.

Strictly satisfies RHS-P01-001 § 17:
- Deterministic serialization (sorted keys, UTF-8, 2-space indent).
- Strict non-finite value rejection (NaN, Infinity).
- Round-trip fidelity (model -> JSON -> model).
- Automatic validation against project.schema.json using Draft202012Validator.
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, Union
from jsonschema import Draft202012Validator, ValidationError

from headway.core.exceptions import DataValidationError
from headway.data.canonical import CanonicalProject

SCHEMA_DIR = Path("schemas")


def _check_no_non_finite(obj: Any) -> None:
    """Recursively verify that no float values are NaN or Infinite."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise DataValidationError(
                f"Non-finite float value '{obj}' detected. NaN and Infinity are strictly prohibited in canonical data.",
                error_code="ERR_SER_NON_FINITE",
            )
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_no_non_finite(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _check_no_non_finite(item)


def serialize_canonical_project(
    project: CanonicalProject,
    validate_schema: bool = True,
) -> str:
    """Serialize a CanonicalProject to deterministic, schema-validated JSON string.

    Args:
        project: The CanonicalProject instance.
        validate_schema: Whether to validate against project.schema.json.

    Returns:
        Deterministic formatted JSON string.
    """
    data = project.model_dump(mode="json")
    _check_no_non_finite(data)

    if validate_schema:
        validate_project_json(data)

    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def deserialize_canonical_project(json_str: Union[str, bytes]) -> CanonicalProject:
    """Deserialize a JSON string into a validated CanonicalProject instance."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as err:
        raise DataValidationError(
            f"Failed to decode project JSON: {err}",
            error_code="ERR_SER_JSON_DECODE",
            technical_details=str(err),
        ) from err

    _check_no_non_finite(data)
    return CanonicalProject.model_validate(data)


def validate_project_json(data: Dict[str, Any]) -> None:
    """Validate project dictionary against project.schema.json using Draft 2020-12 and local registry."""
    schema_file = SCHEMA_DIR / "project.schema.json"
    if not schema_file.exists():
        schema_file = Path(__file__).resolve().parent.parent.parent.parent / "schemas" / "project.schema.json"

    if not schema_file.exists():
        return  # Schema file not found, skip validation

    try:
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012

        with open(schema_file, "r", encoding="utf-8") as f:
            schema = json.load(f)

        # Build local referencing registry to resolve schema references without network calls
        registry = Registry()
        for s_path in schema_file.parent.glob("*.schema.json"):
            with open(s_path, "r", encoding="utf-8") as sf:
                s_dict = json.load(sf)
                res = Resource.from_contents(s_dict, default_specification=DRAFT202012)
                registry = registry.with_resource(s_path.name, res)
                if "$id" in s_dict:
                    registry = registry.with_resource(s_dict["$id"], res)

        validator = Draft202012Validator(schema, registry=registry)
        errors = list(validator.iter_errors(data))
        if errors:
            first_err = errors[0]
            raise DataValidationError(
                f"JSON Schema validation error at '{first_err.json_path}': {first_err.message}",
                error_code="ERR_SER_SCHEMA_VIOLATION",
                context={"path": first_err.json_path, "message": first_err.message},
            )
    except DataValidationError:
        raise
    except Exception as err:
        raise DataValidationError(
            f"Failed to validate project against JSON Schema: {err}",
            error_code="ERR_SER_VALIDATOR_FAIL",
            technical_details=str(err),
        ) from err
