"""Deterministic SHA-256 cryptographic hashing for original files, canonical data, and scenarios.

Strictly satisfies RHS-P01-001 § 18:
- Source file hash: SHA-256 over raw file bytes.
- Canonical hash: SHA-256 over deterministic canonical JSON representation.
- Scenario hash: SHA-256 over effective scenario configuration.
- Guarantees hash stability: identical data yields identical hashes.
"""

import hashlib
import json
from pathlib import Path
from typing import Union
from headway.data.canonical import CanonicalProject


def calculate_file_hash(file_path: Union[str, Path]) -> str:
    """Compute SHA-256 hex digest of a file's raw bytes."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File '{path}' does not exist.")

    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def calculate_canonical_hash(project: CanonicalProject) -> str:
    """Compute deterministic SHA-256 hex digest of a CanonicalProject."""
    # Exclude volatile provenance / timestamps before hashing canonical content
    data = project.model_dump(mode="json")
    data.pop("provenance", None)

    # Deterministic JSON serialization
    canon_bytes = json.dumps(data, indent=None, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canon_bytes).hexdigest()


def calculate_scenario_hash(effective_project: CanonicalProject, scenario_id: str) -> str:
    """Compute deterministic SHA-256 hex digest of an effective scenario configuration."""
    data = effective_project.model_dump(mode="json")
    data.pop("provenance", None)
    data["_effective_scenario_id"] = scenario_id

    canon_bytes = json.dumps(data, indent=None, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canon_bytes).hexdigest()
