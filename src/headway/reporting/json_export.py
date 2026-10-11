"""JSON results exporter.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 5, § 29).
Serializes ReportDocument into a versioned, machine-readable JSON structure.
"""

import json
from pathlib import Path
from typing import Optional, Union

from headway.reporting.report_models import ReportDocument


class JsonReportExporter:
    """Exports ReportDocument into structured, schema-compliant JSON format."""

    SCHEMA_VERSION = "1.0.0"

    @classmethod
    def export(
        cls,
        document: ReportDocument,
        output_path: Optional[Union[str, Path]] = None,
        indent: int = 2,
    ) -> str:
        """Serializes ReportDocument to JSON string and optionally writes to disk."""
        data = {
            "$schema_version": cls.SCHEMA_VERSION,
            "report_data": document.to_dict(),
        }

        json_str = json.dumps(data, indent=indent, default=str)

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json_str, encoding="utf-8")

        return json_str
