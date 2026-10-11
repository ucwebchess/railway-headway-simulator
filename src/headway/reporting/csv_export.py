"""CSV result tables exporter.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 5, § 28).
Exports all individual result tables from a ReportDocument as standard CSV files.
"""

from pathlib import Path
from typing import List, Union

from headway.reporting.report_models import ReportDocument


class CsvReportExporter:
    """Exports all EngineeringTables from a ReportDocument into individual CSV files."""

    @classmethod
    def export(
        cls,
        document: ReportDocument,
        output_dir: Union[str, Path],
        formatted: bool = False,
    ) -> List[Path]:
        """Writes CSV files for all applicable tables into output_dir."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        created_files: List[Path] = []

        for s_id, s in document.sections.items():
            if not s.is_applicable or not s.tables:
                continue

            for idx, tbl in enumerate(s.tables, start=1):
                clean_name = tbl.table_id.lower().replace(" ", "_").replace("-", "_")
                filename = f"{clean_name}.csv" if len(s.tables) == 1 else f"{clean_name}_{idx}.csv"
                file_path = target_dir / filename

                tbl.to_csv(filepath=file_path, formatted=formatted)
                created_files.append(file_path)

        return created_files

    export_all = export
