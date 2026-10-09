"""Canonical identifier normalization, syntax verification, and cross-reference validation.

Strictly adheres to RHS-P01-001 § 6:
- Normalizes whitespace without silently modifying case.
- Detects duplicate identifiers within appropriate namespaces.
- Validates cross-references across datasets and workbooks.
"""

import re
from typing import Any, Dict, List, Optional, Set
from headway.core.exceptions import DataValidationError

# Canonical Identifier regex: Alphanumeric start, followed by alphanumeric, hyphen, underscore, colon, period
IDENTIFIER_REGEX = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-\.:]*$")
MAX_IDENTIFIER_LENGTH = 64


def normalize_identifier(raw_id: Any, id_type: str = "ID") -> str:
    """Normalize and validate an engineering identifier string.

    Rules:
    - Strips leading and trailing whitespace.
    - Preserves exact character casing (does NOT convert to lower/upper).
    - Ensures non-empty string within length bounds.
    - Enforces valid character set.
    """
    if raw_id is None:
        raise DataValidationError(
            f"Identifier of type '{id_type}' cannot be null or empty.",
            error_code="ERR_ID_NULL",
            context={"id_type": id_type},
        )

    clean_id = str(raw_id).strip()
    if not clean_id:
        raise DataValidationError(
            f"Identifier of type '{id_type}' cannot be blank.",
            error_code="ERR_ID_EMPTY",
            context={"id_type": id_type},
        )

    if len(clean_id) > MAX_IDENTIFIER_LENGTH:
        raise DataValidationError(
            f"Identifier '{clean_id}' exceeds maximum length of {MAX_IDENTIFIER_LENGTH} characters.",
            error_code="ERR_ID_TOO_LONG",
            context={"id_type": id_type, "identifier": clean_id, "length": len(clean_id)},
        )

    if not IDENTIFIER_REGEX.match(clean_id):
        raise DataValidationError(
            f"Identifier '{clean_id}' contains invalid characters. Must start with alphanumeric/underscore "
            f"and contain only alphanumeric, '_', '-', '.', or ':'.",
            error_code="ERR_ID_INVALID_SYNTAX",
            context={"id_type": id_type, "identifier": clean_id},
        )

    return clean_id


class IdentifierRegistry:
    """Maintains declared identifiers across distinct namespaces to detect duplicates and verify references."""

    def __init__(self) -> None:
        self._namespaces: Dict[str, Set[str]] = {}

    def register(self, namespace: str, identifier: str, source_info: Optional[str] = None) -> str:
        """Register an identifier within a namespace. Raises DataValidationError if duplicate."""
        clean_id = normalize_identifier(identifier, id_type=namespace)
        if namespace not in self._namespaces:
            self._namespaces[namespace] = set()

        if clean_id in self._namespaces[namespace]:
            info_suffix = f" in {source_info}" if source_info else ""
            raise DataValidationError(
                f"Duplicate identifier '{clean_id}' detected in namespace '{namespace}'{info_suffix}.",
                error_code="ERR_ID_DUPLICATE",
                context={"namespace": namespace, "identifier": clean_id, "source": source_info},
            )

        self._namespaces[namespace].add(clean_id)
        return clean_id

    def exists(self, namespace: str, identifier: str) -> bool:
        """Check whether an identifier is registered in a given namespace."""
        clean_id = str(identifier).strip()
        return namespace in self._namespaces and clean_id in self._namespaces[namespace]

    def verify_reference(
        self,
        target_namespace: str,
        ref_identifier: str,
        referencing_object: str,
        source_info: Optional[str] = None,
    ) -> str:
        """Verify that a referenced foreign identifier exists in target namespace."""
        clean_id = normalize_identifier(ref_identifier, id_type=f"{target_namespace}_REF")
        if not self.exists(target_namespace, clean_id):
            info_suffix = f" (Source: {source_info})" if source_info else ""
            raise DataValidationError(
                f"Reference error: {referencing_object} references non-existent "
                f"{target_namespace} '{clean_id}'{info_suffix}.",
                error_code="ERR_ID_MISSING_REF",
                context={
                    "target_namespace": target_namespace,
                    "referenced_id": clean_id,
                    "referencing_object": referencing_object,
                    "source": source_info,
                },
            )
        return clean_id

    def get_all(self, namespace: str) -> Set[str]:
        """Return a copy of all identifiers in a namespace."""
        return set(self._namespaces.get(namespace, set()))

    def clear(self) -> None:
        """Clear all namespaces in the registry."""
        self._namespaces.clear()
