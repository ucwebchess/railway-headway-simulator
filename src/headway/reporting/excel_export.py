"""Multi-tab Excel results export workbook.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 5, § 27).
Exports comprehensive simulation and reporting results to a multi-sheet Microsoft Excel OOXML (.xlsx) workbook:
- 'Executive_Summary' sheet with KPIs, rolling stock, infrastructure, and recommendations
- Separate sheets for each engineering table (Conflicts, Longest Occupations, Station Stopping, Detailed Timing, Provenance, Mixed Traffic)
- Professional styling: dark navy headers (#1B365D), white bold text, alternating row fills, freeze panes, auto-column widths.
"""

from pathlib import Path
from typing import Any, List, Optional, Union

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from headway.reporting.report_models import ReportDocument, ReportSectionId


class ExcelReportExporter:
    """Exports ReportDocument tables and summary to a multi-tab Excel workbook."""

    HEADER_FILL = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    HEADER_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    TITLE_FONT = Font(name="Arial", size=12, bold=True, color="1B365D")
    BOLD_FONT = Font(name="Arial", size=9, bold=True)
    NORMAL_FONT = Font(name="Arial", size=9)
    ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    CRITICAL_FILL = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")

    THIN_BORDER = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    @classmethod
    def export(
        cls,
        document: ReportDocument,
        output_path: Union[str, Path],
    ) -> str:
        """Constructs and saves the multi-tab Excel workbook."""
        wb = openpyxl.Workbook()
        # Remove default sheet
        default_sheet = wb.active

        # 1. Executive Summary Sheet
        ws_exec = wb.create_sheet(title="Executive_Summary")
        cls._populate_executive_sheet(ws_exec, document)

        # 2. Recommendations Sheet
        if document.recommendations:
            ws_rec = wb.create_sheet(title="RECOMMENDATIONS")
            cls._populate_recommendations_sheet(ws_rec, document.recommendations)

        # 3. Iterate through sections and add table sheets
        for s_id, s in document.sections.items():
            if not s.is_applicable or not s.tables:
                continue

            for idx, tbl in enumerate(s.tables):
                sheet_title = cls._clean_sheet_title(f"{s_id.value[:20]}_{idx+1}" if len(s.tables) > 1 else s_id.value[:30])
                ws = wb.create_sheet(title=sheet_title)
                cls._populate_table_sheet(ws, tbl)

        # Remove default empty sheet if other sheets were created
        if len(wb.sheetnames) > 1 and default_sheet in wb.worksheets:
            wb.remove(default_sheet)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(out))
        return str(out)

    @classmethod
    def _clean_sheet_title(cls, title: str) -> str:
        """Sanitizes title to comply with Excel 31-character limit and character restrictions."""
        cleaned = "".join(c for c in title if c.isalnum() or c in ("_", "-"))
        return cleaned[:31]

    @classmethod
    def _populate_executive_sheet(cls, ws: openpyxl.worksheet.worksheet.Worksheet, doc: ReportDocument) -> None:
        """Builds the Executive Summary overview sheet."""
        meta = doc.metadata
        kpis = doc.executive_kpis
        rs = doc.rolling_stock
        infra = doc.infrastructure

        ws.append([meta.title])
        ws.cell(row=1, column=1).font = Font(name="Arial", size=14, bold=True, color="1B365D")
        ws.append([f"Scenario: {meta.scenario_id} | Running Direction: {doc.running_direction.value} | Run ID: {meta.simulation_run_id}"])
        ws.append([])

        # KPI Block
        ws.append(["EXECUTIVE HEADLINE KPIS"])
        ws.cell(row=4, column=1).font = cls.BOLD_FONT
        ws.append(["Metric", "Value", "Unit", "Definition / Reference"])
        for col in range(1, 5):
            ws.cell(row=5, column=col).fill = cls.HEADER_FILL
            ws.cell(row=5, column=col).font = cls.HEADER_FONT

        ws.append(["Technical Minimum Headway", kpis.technical_headway_s, "s", kpis.headway_definition])
        ws.append(["Technical Headway (minutes)", kpis.technical_headway_min, "min", ""])
        ws.append(["Theoretical Capacity", kpis.theoretical_capacity_tph, "tph", "trains/hour/direction (zero buffer)"])
        ws.append(["Planning Operational Capacity", kpis.planning_capacity_tph, "tph", f"under {kpis.planning_margin_s}s planning margin"])
        ws.append(["Operational Performance Factor", kpis.performance_factor_str, "%", f"Source: {kpis.performance_factor_source} (Traction & Service Braking scaled)"])
        if kpis.total_service_duration_s is not None:
            ws.append(["Total Service Duration (End-to-End)", kpis.total_service_duration_str, "HH:MM:SS", f"{kpis.total_service_duration_s:.1f}s journey time"])
        ws.append(["Controlling Bottleneck Resource", kpis.controlling_bottleneck_id, "ID", f"{kpis.controlling_bottleneck_type} at km {kpis.controlling_bottleneck_chainage_km:.2f}"])
        ws.append([])

        # Rolling Stock Block
        if rs:
            r_start = ws.max_row + 1
            ws.append(["ROLLING STOCK CHARACTERISTICS"])
            ws.cell(row=r_start, column=1).font = cls.BOLD_FONT
            ws.append(["Parameter", "Value", "Unit"])
            for col in range(1, 4):
                ws.cell(row=r_start + 1, column=col).fill = cls.HEADER_FILL
                ws.cell(row=r_start + 1, column=col).font = cls.HEADER_FONT

            ws.append(["Train Model Name", rs.model_name, ""])
            ws.append(["Train Length", rs.train_length_m, "m"])
            ws.append(["Tare Mass", rs.tare_mass_t, "t"])
            ws.append(["Gross Mass", rs.gross_mass_t, "t"])
            ws.append(["Maximum Speed", rs.max_speed_kmh, "km/h"])
            ws.append(["Traction Power", rs.traction_power_kw, "kW"])
            ws.append(["Service Deceleration", rs.service_braking_deceleration_ms2, "m/s²"])
            ws.append(["Emergency Deceleration", rs.emergency_braking_deceleration_ms2, "m/s²"])
            ws.append([])

        # Infrastructure Block
        if infra:
            r_start = ws.max_row + 1
            ws.append(["INFRASTRUCTURE & SIGNALLING"])
            ws.cell(row=r_start, column=1).font = cls.BOLD_FONT
            ws.append(["Parameter", "Value", "Unit"])
            for col in range(1, 4):
                ws.cell(row=r_start + 1, column=col).fill = cls.HEADER_FILL
                ws.cell(row=r_start + 1, column=col).font = cls.HEADER_FONT

            ws.append(["Signalling Technology", infra.signalling_technology, ""])
            ws.append(["Aspect Model", getattr(infra, "aspect_model", "THREE_ASPECT"), ""])
            ws.append(["Default Overlap", getattr(infra, "default_overlap_m", 0.0), "m"])
            ws.append(["Sighting Time", getattr(infra, "sighting_time_s", 8.0), "s"])
            ws.append(["Route Setup Time", infra.route_setup_time_s, "s"])
            ws.append(["Release Delay", infra.resource_release_delay_s, "s"])
            ws.append(["Total Links", getattr(infra, "total_links", 0), "links"])
            ws.append(["Total Blocks", getattr(infra, "total_blocks", 0), "blocks"])
            ws.append(["Total Signals", getattr(infra, "total_signals", 0), "signals"])
            ws.append(["Total Stations", getattr(infra, "total_stations", 0), "stations"])
            ws.append(["Total Platforms", getattr(infra, "total_platforms", 0), "platforms"])
            ws.append(["Total TVS Sections", getattr(infra, "total_tvs_sections", 0), "sections"])
            ws.append(["Topology Mode", infra.topology_mode, ""])
            ws.append(["Dataset ID", infra.dataset_id, ""])
            ws.append(["Dataset Version", infra.dataset_version, ""])
            ws.append(["Model Fidelity", infra.model_fidelity, ""])
            ws.append([])

        cls._auto_fit_columns(ws)

    @classmethod
    def _populate_table_sheet(cls, ws: openpyxl.worksheet.worksheet.Worksheet, table: Any) -> None:
        """Fills a worksheet with an EngineeringTable's raw data."""
        ws.append([table.title])
        ws.cell(row=1, column=1).font = cls.TITLE_FONT
        ws.append([])

        df = table.raw_dataframe
        cols = list(df.columns)
        ws.append(cols)

        header_row = 3
        for col_idx in range(1, len(cols) + 1):
            cell = ws.cell(row=header_row, column=col_idx)
            cell.fill = cls.HEADER_FILL
            cell.font = cls.HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center")

        ws.freeze_panes = f"A{header_row + 1}"

        for row_counter, (_, row) in enumerate(df.iterrows()):
            row_vals = [row[c] for c in cols]
            ws.append(row_vals)
            curr_row = ws.max_row

            is_controlling = any("CONTROLLING" in str(v).upper() for v in row_vals)
            fill_to_use = cls.CRITICAL_FILL if is_controlling else (cls.ZEBRA_FILL if row_counter % 2 == 1 else None)

            for col_idx in range(1, len(cols) + 1):
                c = ws.cell(row=curr_row, column=col_idx)
                c.font = cls.NORMAL_FONT
                c.border = cls.THIN_BORDER
                if fill_to_use:
                    c.fill = fill_to_use

        cls._auto_fit_columns(ws)

    @classmethod
    def _populate_recommendations_sheet(cls, ws: openpyxl.worksheet.worksheet.Worksheet, recommendations: List[Any]) -> None:
        """Fills a worksheet with engineering recommendations."""
        ws.append(["Engineering Recommendations and Capacity Interventions"])
        ws.cell(row=1, column=1).font = cls.TITLE_FONT
        ws.append([])

        cols = ["ID", "Category", "Title", "Governing Resource", "Expected Benefit", "Rationale"]
        ws.append(cols)
        header_row = 3
        for col_idx in range(1, len(cols) + 1):
            cell = ws.cell(row=header_row, column=col_idx)
            cell.fill = cls.HEADER_FILL
            cell.font = cls.HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center")

        ws.freeze_panes = f"A{header_row + 1}"

        for row_counter, rec in enumerate(recommendations):
            row_vals = [
                rec.recommendation_id,
                getattr(rec.category, "value", str(rec.category)),
                rec.title,
                rec.governing_resource_id or "General",
                rec.expected_benefit,
                rec.rationale,
            ]
            ws.append(row_vals)
            curr_row = ws.max_row
            fill_to_use = cls.ZEBRA_FILL if row_counter % 2 == 1 else None

            for col_idx in range(1, len(cols) + 1):
                c = ws.cell(row=curr_row, column=col_idx)
                c.font = cls.NORMAL_FONT
                c.border = cls.THIN_BORDER
                if fill_to_use:
                    c.fill = fill_to_use

        cls._auto_fit_columns(ws)

    @classmethod
    def _auto_fit_columns(cls, ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
        """Adjusts column widths based on cell text lengths."""
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                if "\n" in val:
                    val = max(val.split("\n"), key=len)
                max_len = max(max_len, len(val))
            ws.column_dimensions[col_letter].width = min(50, max(max_len + 3, 10))
