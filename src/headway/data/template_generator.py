"""Excel template generator producing the six standardized workbooks from the authoritative schema registry.

Strictly satisfies P01-XLS-001 through P01-XLS-007:
- Driven exclusively by the authoritative Excel schema registry.
- Generates METADATA and INSTRUCTIONS worksheets.
- Standardizes headers and indicates engineering units.
- Adds openpyxl data validations for enumerated columns.
- Generates clearly identified example rows that importers can distinguish from real data.
"""

from pathlib import Path
from typing import List, Optional
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from headway.data.excel_registry import (
    ALL_WORKBOOK_DEFS,
    WorkbookDef,
    WorksheetDef,
)

# Styling palette
HEADER_FILL = PatternFill(start_color="0F2B48", end_color="0F2B48", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
SUBHEADER_FILL = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
SUBHEADER_FONT = Font(name="Calibri", size=9, italic=True, color="475569")
EXAMPLE_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
EXAMPLE_FONT = Font(name="Calibri", size=10, italic=True, color="64748B")

THIN_BORDER = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1"),
)


def _build_instructions_sheet(wb: openpyxl.Workbook, wb_def: WorkbookDef) -> None:
    """Create the instructional overview worksheet."""
    ws = wb.create_sheet(title="INSTRUCTIONS", index=0)
    ws.views.sheetView[0].showGridLines = True

    title_cell = ws.cell(row=1, column=1, value=f"Railway Headway Simulator — {wb_def.workbook_type} Workbook")
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="0F2B48")

    ws.cell(row=2, column=1, value=f"Purpose: {wb_def.description}").font = Font(size=11, italic=True)
    ws.cell(row=3, column=1, value="Schema Version: 1.0.0").font = Font(size=10, bold=True)

    instructions = [
        "",
        "GENERAL INSTRUCTIONS FOR ENGINEERING DATA ENTRY:",
        "1. Do not modify, remove, or reorder column header names in Row 1 of data worksheets.",
        "2. Review the units specified in Row 2 for each column (e.g. km/h, m, tonnes, kN, ‰).",
        "3. Row 3 contains an illustrative example row (marked with ID 'EXAMPLE_*'). Replace or delete before production use.",
        "4. Identifiers must be unique within each worksheet and must not contain special symbols or spaces.",
        "5. Cross-references (such as Link IDs, Station IDs, Train Type IDs) must match exact casing.",
        "6. Do not save workbook with Excel macros (.xlsm is prohibited).",
        "",
        "WORKSHEET INVENTORY:",
    ]

    for idx, text in enumerate(instructions, start=4):
        ws.cell(row=idx, column=1, value=text).font = Font(size=10, bold=(text.isupper() and len(text) > 5))

    start_row = 4 + len(instructions)
    for ws_def in wb_def.worksheets:
        if ws_def.name in {"METADATA", "INSTRUCTIONS"}:
            continue
        ws.cell(row=start_row, column=1, value=f"• {ws_def.name}: {ws_def.description}").font = Font(size=10)
        start_row += 1

    ws.column_dimensions["A"].width = 85


def _build_metadata_sheet(wb: openpyxl.Workbook, wb_def: WorkbookDef, project_id: str = "PRJ_DEMO") -> None:
    """Create the standardized METADATA worksheet."""
    ws = wb.create_sheet(title="METADATA")
    ws.views.sheetView[0].showGridLines = True

    # Header
    ws.cell(row=1, column=1, value="PROPERTY").font = HEADER_FONT
    ws.cell(row=1, column=1).fill = HEADER_FILL
    ws.cell(row=1, column=2, value="VALUE").font = HEADER_FONT
    ws.cell(row=1, column=2).fill = HEADER_FILL

    metadata_items = [
        ("WORKBOOK_TYPE", wb_def.workbook_type),
        ("SCHEMA_VERSION", "1.0.0"),
        ("PROJECT_ID", project_id),
        ("DATASET_ID", f"{wb_def.workbook_type}_DATASET_01"),
        ("AUTHOR", "Railway Simulation Engineering Team"),
        ("CREATED_DATE", "2026-10-09"),
        ("DESCRIPTION", wb_def.description),
    ]

    for r_idx, (prop, val) in enumerate(metadata_items, start=2):
        ws.cell(row=r_idx, column=1, value=prop).font = Font(name="Calibri", size=10, bold=True)
        ws.cell(row=r_idx, column=2, value=val).font = Font(name="Calibri", size=10)
        ws.cell(row=r_idx, column=1).border = THIN_BORDER
        ws.cell(row=r_idx, column=2).border = THIN_BORDER

    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 50


def _build_domain_worksheet(wb: openpyxl.Workbook, ws_def: WorksheetDef) -> None:
    """Create and format a domain data worksheet."""
    ws = wb.create_sheet(title=ws_def.name)
    ws.views.sheetView[0].showGridLines = True

    # Row 1: Header names
    # Row 2: Units / descriptions
    # Row 3: Example row
    for c_idx, col in enumerate(ws_def.columns, start=1):
        cell_h = ws.cell(row=1, column=c_idx, value=col.name)
        cell_h.font = HEADER_FONT
        cell_h.fill = HEADER_FILL
        cell_h.alignment = Alignment(horizontal="center", vertical="center")
        cell_h.border = THIN_BORDER

        # Subheader with unit
        unit_text = f"[{col.excel_unit}]" if col.excel_unit else ("(Required)" if col.required else "(Optional)")
        cell_sub = ws.cell(row=2, column=c_idx, value=unit_text)
        cell_sub.font = SUBHEADER_FONT
        cell_sub.fill = SUBHEADER_FILL
        cell_sub.alignment = Alignment(horizontal="center", vertical="center")
        cell_sub.border = THIN_BORDER

        # Example row
        ex_val = col.example_value
        if ex_val is None and col.default_value is not None:
            ex_val = col.default_value
        cell_ex = ws.cell(row=3, column=c_idx, value=ex_val)
        cell_ex.font = EXAMPLE_FONT
        cell_ex.fill = EXAMPLE_FILL
        cell_ex.border = THIN_BORDER

        # Data Validation (dropdown) for columns with allowed_values
        if col.allowed_values:
            formula = '"' + ",".join(col.allowed_values) + '"'
            dv = DataValidation(type="list", formula1=formula, allow_blank=not col.required)
            ws.add_data_validation(dv)
            dv.add(f"{openpyxl.utils.get_column_letter(c_idx)}3:{openpyxl.utils.get_column_letter(c_idx)}500")

        # Set column width
        ws.column_dimensions[openpyxl.utils.get_column_letter(c_idx)].width = max(len(col.name) + 5, 16)


def generate_workbook_template(wb_def: WorkbookDef, output_path: Path, project_id: str = "PRJ_DEMO") -> Path:
    """Generate a single standardized Excel template workbook."""
    wb = openpyxl.Workbook()
    # Remove default sheet
    default_sheet = wb.active

    # 1. Instructions
    _build_instructions_sheet(wb, wb_def)

    # 2. Metadata
    _build_metadata_sheet(wb, wb_def, project_id=project_id)

    # 3. Domain worksheets
    for ws_def in wb_def.worksheets:
        if ws_def.name == "METADATA":
            continue
        _build_domain_worksheet(wb, ws_def)

    # Remove the initial default sheet
    if default_sheet is not None and default_sheet.title not in wb.sheetnames:
        wb.remove(default_sheet)
    elif "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def generate_all_templates(output_dir: Path, project_id: str = "PRJ_DEMO") -> List[Path]:
    """Generate all six standardized Excel workbook templates."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = []

    for wb_type, wb_def in ALL_WORKBOOK_DEFS.items():
        file_path = out_dir / wb_def.default_filename
        generate_workbook_template(wb_def, file_path, project_id=project_id)
        generated.append(file_path)

    return generated
