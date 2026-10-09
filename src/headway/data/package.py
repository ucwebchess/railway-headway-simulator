"""Project ZIP package import and export with security checks.

Strictly satisfies RHS-P01-001 § 20:
- Packages original Excel workbooks, canonical JSON, project manifest, dataset hashes, and validation report.
- Safe ZIP handling prevents path traversal, absolute paths, and decompression bombs.
- Round-trip fidelity: exporting and reimporting preserves exact canonical project state.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
import zipfile

from headway.core.exceptions import DataValidationError, EnvironmentError
from headway.data.canonical import CanonicalProject
from headway.data.hashing import calculate_canonical_hash, calculate_file_hash
from headway.data.serializer import deserialize_canonical_project, serialize_canonical_project
from headway.data.validation import ValidationReport

MAX_ZIP_ENTRIES = 100
MAX_UNCOMPRESSED_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB safety limit
ALLOWED_EXTENSIONS = {".xlsx", ".json", ".txt", ".md", ".csv"}


class ProjectPackage:
    """Manages ZIP archive packaging and safe unpackaging for simulation projects."""

    @staticmethod
    def export_package(
        project: CanonicalProject,
        output_zip_path: Union[str, Path],
        excel_workbooks: Optional[Dict[str, Path]] = None,
        validation_report: Optional[ValidationReport] = None,
    ) -> Path:
        """Create a self-contained, secure project ZIP package."""
        zip_path = Path(output_zip_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        canon_json = serialize_canonical_project(project)
        canon_hash = calculate_canonical_hash(project)

        file_hashes: Dict[str, str] = {}
        wb_paths = excel_workbooks or {}

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. Write canonical project JSON
            zf.writestr("canonical_project.json", canon_json)

            # 2. Write original Excel workbooks
            for wb_type, wb_path in wb_paths.items():
                p = Path(wb_path)
                if p.exists():
                    f_hash = calculate_file_hash(p)
                    file_hashes[p.name] = f_hash
                    zf.write(p, arcname=f"excel/{p.name}")

            # 3. Write validation report if provided
            if validation_report:
                report_dict = {
                    "has_errors": validation_report.has_errors,
                    "is_simulation_ready": validation_report.is_simulation_ready,
                    "summary": validation_report.summary(),
                    "findings": validation_report.to_list(),
                }
                zf.writestr("validation_report.json", json.dumps(report_dict, indent=2))

            # 4. Write manifest
            manifest = {
                "project_id": project.project_id,
                "project_name": project.name,
                "schema_version": project.schema_version,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "canonical_hash_sha256": canon_hash,
                "source_file_hashes_sha256": file_hashes,
                "scenarios": [s.scenario_id for s in project.scenarios],
                "datasets": {
                    "infrastructure": project.infrastructure.dataset_id,
                    "rolling_stock": project.rolling_stock.dataset_id,
                    "signalling": project.signalling.dataset_id,
                    "operations": project.operations.dataset_id,
                    "analysis": project.analysis.dataset_id,
                },
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        return zip_path

    @staticmethod
    def import_package(
        zip_path: Union[str, Path],
        extract_to_dir: Union[str, Path],
    ) -> Tuple[CanonicalProject, Dict[str, Any], Dict[str, Path]]:
        """Safely unpackage and load a project archive.

        Returns:
            Tuple of (CanonicalProject, manifest_dict, extracted_excel_files_map).
        """
        path = Path(zip_path)
        dest_dir = Path(extract_to_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            raise FileNotFoundError(f"Project package '{path}' does not exist.")

        # Inspect and validate ZIP contents against safety constraints
        with zipfile.ZipFile(path, "r") as zf:
            infolist = zf.infolist()
            if len(infolist) > MAX_ZIP_ENTRIES:
                raise DataValidationError(
                    f"ZIP package exceeds entry count limit ({len(infolist)} > {MAX_ZIP_ENTRIES}).",
                    error_code="ERR_SECURITY_ZIP_TOO_MANY_FILES",
                )

            total_uncompressed = 0
            for info in infolist:
                # Path traversal check (P01-PKG-003)
                p = Path(info.filename)
                if p.is_absolute() or ".." in p.parts:
                    raise DataValidationError(
                        f"Unsafe file path '{info.filename}' detected in project ZIP package.",
                        error_code="ERR_SECURITY_ZIP_PATH_TRAVERSAL",
                        context={"filename": info.filename},
                    )

                if p.suffix.lower() and p.suffix.lower() not in ALLOWED_EXTENSIONS:
                    raise DataValidationError(
                        f"Unsupported file extension '{p.suffix}' in ZIP package: {info.filename}",
                        error_code="ERR_SECURITY_ZIP_BAD_EXTENSION",
                    )

                total_uncompressed += info.file_size
                if total_uncompressed > MAX_UNCOMPRESSED_SIZE_BYTES:
                    raise DataValidationError(
                        f"ZIP package exceeds maximum allowable uncompressed size ({MAX_UNCOMPRESSED_SIZE_BYTES} bytes).",
                        error_code="ERR_SECURITY_ZIP_BOMB",
                    )

            # Safe extraction
            zf.extractall(dest_dir)

        # Read manifest
        manifest_file = dest_dir / "manifest.json"
        manifest = {}
        if manifest_file.exists():
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)

        # Read canonical project
        canon_file = dest_dir / "canonical_project.json"
        if not canon_file.exists():
            raise DataValidationError(
                "Missing required 'canonical_project.json' in project package.",
                error_code="ERR_PKG_MISSING_CANONICAL_JSON",
            )

        with open(canon_file, "r", encoding="utf-8") as f:
            project = deserialize_canonical_project(f.read())

        # Collect extracted Excel files
        excel_dir = dest_dir / "excel"
        excel_files: Dict[str, Path] = {}
        if excel_dir.exists():
            for f in excel_dir.glob("*.xlsx"):
                excel_files[f.name] = f

        return project, manifest, excel_files
