#!/usr/bin/env python3
"""Generator script for 05_comprehensive_line reference dataset.

Creates the six standardized Excel workbooks conforming to the schema registry:
- 01_Infrastructure.xlsx
- 02_Signalling.xlsx
- 03_RollingStock.xlsx
- 04_Operations.xlsx
- 05_HeadwayAnalysis.xlsx
- 06_Scenarios.xlsx
"""

from pathlib import Path
import sys
from typing import Any, List, Optional, Tuple
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

# Ensure src/ is importable
repo_root = Path(__file__).resolve().parents[2]
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from headway.data.excel_registry import ALL_WORKBOOK_DEFS, WorkbookDef, WorksheetDef

# Styling palette conforming to templates
HEADER_FILL = PatternFill(start_color="0F2B48", end_color="0F2B48", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
SUBHEADER_FILL = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
SUBHEADER_FONT = Font(name="Calibri", size=9, italic=True, color="475569")
DATA_FONT = Font(name="Calibri", size=10, color="000000")

THIN_BORDER = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1"),
)


def _build_instructions_sheet(
    wb: openpyxl.Workbook,
    title_str: str,
    purpose_str: str,
    sheets_info: List[Tuple[str, str]],
) -> None:
    """Create the standardized INSTRUCTIONS worksheet."""
    ws = wb.create_sheet(title="INSTRUCTIONS", index=0)
    ws.views.sheetView[0].showGridLines = True
    ws.cell(row=1, column=1, value=title_str).font = Font(
        name="Calibri", size=14, bold=True, color="0F2B48"
    )
    ws.cell(row=2, column=1, value=f"Purpose: {purpose_str}").font = Font(
        size=11, italic=True
    )
    ws.cell(row=3, column=1, value="Schema Version: 1.0.0").font = Font(
        size=10, bold=True
    )

    instructions = [
        "",
        "GENERAL INSTRUCTIONS FOR ENGINEERING DATA ENTRY:",
        "1. Do not modify, remove, or reorder column header names in Row 1 of data worksheets.",
        "2. Review the units specified in Row 2 for each column (e.g. km/h, m, tonnes, kN, ‰).",
        "3. Row 3 contains a minimal valid baseline network for demonstration purposes. You may modify or replace it with your own railway data. The example is designed to load without validation errors.",
        "4. Identifiers must be unique within each worksheet and must not contain special symbols or spaces.",
        "5. Cross-references (such as Link IDs, Station IDs, Train Type IDs) must match exact casing.",
        "6. Do not save workbook with Excel macros (.xlsm is prohibited).",
        "",
        "WORKSHEET INVENTORY:",
    ]
    for idx, text in enumerate(instructions, start=4):
        ws.cell(row=idx, column=1, value=text).font = Font(
            size=10, bold=(text.isupper() and len(text) > 5)
        )

    start_row = 4 + len(instructions)
    for s_name, s_desc in sheets_info:
        ws.cell(row=start_row, column=1, value=f"• {s_name}: {s_desc}").font = Font(
            size=10
        )
        start_row += 1
    ws.column_dimensions["A"].width = 85


def _build_metadata_sheet(
    wb: openpyxl.Workbook,
    wb_type: str,
    dataset_id: str,
    description: str,
    project_id: str = "PRJ_EX05_COMPREHENSIVE",
) -> None:
    """Create the standardized METADATA worksheet."""
    ws = wb.create_sheet(title="METADATA")
    ws.views.sheetView[0].showGridLines = True
    ws.cell(row=1, column=1, value="PROPERTY").font = HEADER_FONT
    ws.cell(row=1, column=1).fill = HEADER_FILL
    ws.cell(row=1, column=2, value="VALUE").font = HEADER_FONT
    ws.cell(row=1, column=2).fill = HEADER_FILL

    items = [
        ("WORKBOOK_TYPE", wb_type),
        ("SCHEMA_VERSION", "1.0.0"),
        ("PROJECT_ID", project_id),
        ("DATASET_ID", dataset_id),
        ("AUTHOR", "Railway Headway Simulator Engineering Team"),
        ("CREATED_DATE", "2026-10-13"),
        ("DESCRIPTION", description),
    ]
    for r_idx, (prop, val) in enumerate(items, start=2):
        ws.cell(row=r_idx, column=1, value=prop).font = Font(
            name="Calibri", size=10, bold=True
        )
        ws.cell(row=r_idx, column=2, value=val).font = Font(name="Calibri", size=10)
        ws.cell(row=r_idx, column=1).border = THIN_BORDER
        ws.cell(row=r_idx, column=2).border = THIN_BORDER
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 65


def _build_data_worksheet(
    wb: openpyxl.Workbook,
    ws_def: WorksheetDef,
    rows_data: List[List[Any]],
) -> None:
    """Create and format a domain data worksheet."""
    ws = wb.create_sheet(title=ws_def.name)
    ws.views.sheetView[0].showGridLines = True

    for c_idx, col in enumerate(ws_def.columns, start=1):
        cell_h = ws.cell(row=1, column=c_idx, value=col.name)
        cell_h.font = HEADER_FONT
        cell_h.fill = HEADER_FILL
        cell_h.alignment = Alignment(horizontal="center", vertical="center")
        cell_h.border = THIN_BORDER

        unit_text = (
            f"[{col.excel_unit}]"
            if col.excel_unit
            else ("(Required)" if col.required else "(Optional)")
        )
        cell_sub = ws.cell(row=2, column=c_idx, value=unit_text)
        cell_sub.font = SUBHEADER_FONT
        cell_sub.fill = SUBHEADER_FILL
        cell_sub.alignment = Alignment(horizontal="center", vertical="center")
        cell_sub.border = THIN_BORDER

        if col.allowed_values:
            formula = '"' + ",".join(col.allowed_values) + '"'
            dv = DataValidation(
                type="list", formula1=formula, allow_blank=not col.required
            )
            ws.add_data_validation(dv)
            col_letter = openpyxl.utils.get_column_letter(c_idx)
            dv.add(f"{col_letter}3:{col_letter}500")

        max_len = max(len(col.name) + 4, 16)
        for r_val in rows_data:
            if c_idx - 1 < len(r_val):
                v_str = str(r_val[c_idx - 1] if r_val[c_idx - 1] is not None else "")
                max_len = max(max_len, len(v_str) + 4)
        ws.column_dimensions[openpyxl.utils.get_column_letter(c_idx)].width = min(
            max_len, 50
        )

    for r_idx, row_vals in enumerate(rows_data, start=3):
        for c_idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = DATA_FONT
            cell.border = THIN_BORDER


def generate_comprehensive_workbooks(output_directory: Optional[Path] = None) -> List[Path]:
    """Generate all six Excel workbooks for the 05_comprehensive_line dataset."""
    out_dir = (
        Path(output_directory)
        if output_directory
        else Path(__file__).resolve().parent
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_files = []

    # 1. 01_Infrastructure.xlsx
    wb_infra = openpyxl.Workbook()
    wb_infra.remove(wb_infra.active)
    infra_def = ALL_WORKBOOK_DEFS["INFRASTRUCTURE"]
    _build_instructions_sheet(
        wb_infra,
        "Railway Headway Simulator — INFRASTRUCTURE Workbook",
        "Comprehensive Demonstration Line physical railway network topology, geometry, stations, and TVS boundaries",
        [
            (w.name, w.description)
            for w in infra_def.worksheets
            if w.name not in ("METADATA", "INSTRUCTIONS")
        ],
    )
    _build_metadata_sheet(
        wb_infra,
        "INFRASTRUCTURE",
        "INFRA_EX05",
        "Comprehensive Demonstration Line Infrastructure Dataset",
    )

    nodes_data = [
        ["ND_01", "Terminal North", "JUNCTION"],
        ["ND_02", "Station Alpha North", "ENDPOINT"],
        ["ND_03", "Station Alpha South", "JUNCTION"],
        ["ND_04", "Mid-Junction North", "JUNCTION"],
        ["ND_05", "Mid-Junction South", "JUNCTION"],
        ["ND_06", "Station Beta North", "ENDPOINT"],
        ["ND_07", "Station Beta South", "JUNCTION"],
        ["ND_08", "Tunnel Portal North", "ENDPOINT"],
        ["ND_09", "Tunnel Portal South", "ENDPOINT"],
        ["ND_10", "Station Gamma North", "ENDPOINT"],
        ["ND_11", "Terminal South", "ENDPOINT"],
    ]

    tracks_data = [
        ["TRK_UP", "Main Line Up (North to South)", "NOMINAL"],
        ["TRK_DN", "Main Line Down (South to North)", "REVERSE"],
        ["TRK_SIDING", "Overtaking Loop / Freight Siding Track", "BIDIRECTIONAL"],
    ]

    links_data = [
        ["LNK_01", "TRK_UP", "ND_01", "ND_02", 3000.0, 160.0, 0.0, None],
        ["LNK_02", "TRK_UP", "ND_02", "ND_03", 1000.0, 100.0, 2.0, None],
        ["LNK_03", "TRK_UP", "ND_03", "ND_04", 4000.0, 160.0, -3.0, None],
        ["LNK_04", "TRK_UP", "ND_04", "ND_05", 2000.0, 140.0, 0.0, None],
        ["LNK_05", "TRK_UP", "ND_05", "ND_06", 3500.0, 160.0, 5.0, None],
        ["LNK_06", "TRK_UP", "ND_06", "ND_07", 1000.0, 100.0, 0.0, None],
        ["LNK_07", "TRK_UP", "ND_07", "ND_08", 2500.0, 140.0, -2.0, None],
        ["LNK_08", "TRK_UP", "ND_08", "ND_09", 5000.0, 120.0, 0.0, None],
        ["LNK_09", "TRK_UP", "ND_09", "ND_10", 2000.0, 120.0, 1.0, None],
        ["LNK_10", "TRK_UP", "ND_10", "ND_11", 1000.0, 80.0, 0.0, None],
        ["LNK_11", "TRK_DN", "ND_11", "ND_10", 1000.0, 80.0, 0.0, None],
        ["LNK_12", "TRK_DN", "ND_10", "ND_09", 2000.0, 120.0, -1.0, None],
        ["LNK_13", "TRK_DN", "ND_09", "ND_08", 5000.0, 120.0, 0.0, None],
        ["LNK_14", "TRK_DN", "ND_08", "ND_07", 2500.0, 140.0, 2.0, None],
        ["LNK_15", "TRK_DN", "ND_07", "ND_05", 4500.0, 160.0, 0.0, None],
        ["LNK_16", "TRK_DN", "ND_05", "ND_03", 6000.0, 160.0, 0.0, None],
        ["LNK_17", "TRK_DN", "ND_03", "ND_01", 4000.0, 160.0, 0.0, None],
        ["LNK_18", "TRK_SIDING", "ND_04", "ND_05", 2000.0, 80.0, 0.0, None],
    ]

    stations_data = [
        ["STN_ALPHA", "Station Alpha", 3.5],
        ["STN_BETA", "Station Beta", 14.0],
        ["STN_GAMMA", "Station Gamma", 23.5],
    ]

    platforms_data = [
        ["PLT_A1", "STN_ALPHA", "LNK_02", 100.0, 500.0, 400.0],
        ["PLT_A2", "STN_ALPHA", "LNK_02", 550.0, 950.0, 400.0],
        ["PLT_A3", "STN_ALPHA", "LNK_17", 100.0, 500.0, 400.0],
        ["PLT_B1", "STN_BETA", "LNK_06", 100.0, 500.0, 400.0],
        ["PLT_B2", "STN_BETA", "LNK_06", 550.0, 950.0, 400.0],
        ["PLT_B3", "STN_BETA", "LNK_15", 100.0, 500.0, 400.0],
        ["PLT_G1", "STN_GAMMA", "LNK_10", 100.0, 500.0, 400.0],
        ["PLT_G2", "STN_GAMMA", "LNK_11", 100.0, 500.0, 400.0],
    ]

    stopping_points_data = [
        ["SP_A1", "PLT_A1", "LNK_02", 450.0],
        ["SP_A2", "PLT_A2", "LNK_02", 900.0],
        ["SP_A3", "PLT_A3", "LNK_17", 450.0],
        ["SP_B1", "PLT_B1", "LNK_06", 450.0],
        ["SP_B2", "PLT_B2", "LNK_06", 900.0],
        ["SP_B3", "PLT_B3", "LNK_15", 450.0],
        ["SP_G1", "PLT_G1", "LNK_10", 450.0],
        ["SP_G2", "PLT_G2", "LNK_11", 450.0],
    ]

    tunnels_data = [
        ["TNL_01", "Comprehensive Model Tunnel", "Gotthard-style 5 km bored rock tunnel"],
    ]

    tvs_sections_data = [
        ["TVS_01", "TNL_01", "TRK_UP", "LNK_08", 0.0, 1250.0, 1, "SIG_UP_08", 4.0],
        ["TVS_02", "TNL_01", "TRK_UP", "LNK_08", 1250.0, 2500.0, 1, None, 4.0],
        ["TVS_03", "TNL_01", "TRK_UP", "LNK_08", 2500.0, 3750.0, 1, None, 4.0],
        ["TVS_04", "TNL_01", "TRK_UP", "LNK_08", 3750.0, 5000.0, 1, None, 4.0],
    ]

    srg_data = [
        [
            "SRG_TUNNEL",
            "Single-train tunnel safety constraint across all TVS sections",
            "TVS_01, TVS_02, TVS_03, TVS_04",
        ],
    ]

    for ws_def in infra_def.worksheets:
        if ws_def.name == "METADATA":
            continue
        if ws_def.name == "Nodes":
            _build_data_worksheet(wb_infra, ws_def, nodes_data)
        elif ws_def.name == "Tracks":
            _build_data_worksheet(wb_infra, ws_def, tracks_data)
        elif ws_def.name == "TrackLinks":
            _build_data_worksheet(wb_infra, ws_def, links_data)
        elif ws_def.name == "Stations":
            _build_data_worksheet(wb_infra, ws_def, stations_data)
        elif ws_def.name == "Platforms":
            _build_data_worksheet(wb_infra, ws_def, platforms_data)
        elif ws_def.name == "StoppingPoints":
            _build_data_worksheet(wb_infra, ws_def, stopping_points_data)
        elif ws_def.name == "Tunnels":
            _build_data_worksheet(wb_infra, ws_def, tunnels_data)
        elif ws_def.name == "TVSSections":
            _build_data_worksheet(wb_infra, ws_def, tvs_sections_data)
        elif ws_def.name == "SharedResourceGroups":
            _build_data_worksheet(wb_infra, ws_def, srg_data)

    p1 = out_dir / "01_Infrastructure.xlsx"
    wb_infra.save(p1)
    generated_files.append(p1)

    # 2. 02_Signalling.xlsx
    wb_sig = openpyxl.Workbook()
    wb_sig.remove(wb_sig.active)
    sig_def = ALL_WORKBOOK_DEFS["SIGNALLING"]
    _build_instructions_sheet(
        wb_sig,
        "Railway Headway Simulator — SIGNALLING Workbook",
        "Signalling systems, signals, block sections, and interlocking route definitions",
        [
            (w.name, w.description)
            for w in sig_def.worksheets
            if w.name not in ("METADATA", "INSTRUCTIONS")
        ],
    )
    _build_metadata_sheet(
        wb_sig,
        "SIGNALLING",
        "SIG_EX05",
        "Comprehensive Demonstration Line Signalling Dataset",
    )

    sig_sys_data = [
        ["GENERIC_FIXED_BLOCK_ENGINEERING_MODEL", "THREE_ASPECT", 50.0, 8.0, 3.0, 4.0]
    ]

    signals_data = [
        ["SIG_UP_01", "LNK_01", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_02", "LNK_02", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_03", "LNK_03", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_04", "LNK_04", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_05", "LNK_05", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_06", "LNK_06", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_07", "LNK_07", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_08", "LNK_08", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_09", "LNK_09", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_UP_10", "LNK_10", 50.0, "NOMINAL", "MAIN", 200.0],
        ["SIG_DN_01", "LNK_11", 50.0, "REVERSE", "MAIN", 200.0],
        ["SIG_DN_02", "LNK_12", 50.0, "REVERSE", "MAIN", 200.0],
        ["SIG_DN_03", "LNK_13", 50.0, "REVERSE", "MAIN", 200.0],
        ["SIG_DN_04", "LNK_14", 50.0, "REVERSE", "MAIN", 200.0],
        ["SIG_DN_05", "LNK_15", 50.0, "REVERSE", "MAIN", 200.0],
        ["SIG_DN_06", "LNK_16", 50.0, "REVERSE", "MAIN", 200.0],
        ["SIG_DN_07", "LNK_17", 50.0, "REVERSE", "MAIN", 200.0],
        ["SIG_SD_01", "LNK_18", 50.0, "BIDIRECTIONAL", "MAIN", 200.0],
    ]

    blocks_data = [
        ["BLK_UP_01", "SIG_UP_01", "SIG_UP_02", "LNK_01", 0.0, 3000.0, 50.0, 4.0],
        ["BLK_UP_02", "SIG_UP_02", "SIG_UP_03", "LNK_02", 0.0, 1000.0, 50.0, 4.0],
        ["BLK_UP_03", "SIG_UP_03", "SIG_UP_04", "LNK_03", 0.0, 4000.0, 50.0, 4.0],
        ["BLK_UP_04", "SIG_UP_04", "SIG_UP_05", "LNK_04", 0.0, 2000.0, 50.0, 4.0],
        ["BLK_UP_05", "SIG_UP_05", "SIG_UP_06", "LNK_05", 0.0, 3500.0, 50.0, 4.0],
        ["BLK_UP_06", "SIG_UP_06", "SIG_UP_07", "LNK_06", 0.0, 1000.0, 50.0, 4.0],
        ["BLK_UP_07", "SIG_UP_07", "SIG_UP_08", "LNK_07", 0.0, 2500.0, 50.0, 4.0],
        ["BLK_UP_08", "SIG_UP_08", "SIG_UP_09", "LNK_08", 0.0, 5000.0, 50.0, 4.0],
        ["BLK_UP_09", "SIG_UP_09", "SIG_UP_10", "LNK_09", 0.0, 2000.0, 50.0, 4.0],
        ["BLK_UP_10", "SIG_UP_10", None, "LNK_10", 0.0, 1000.0, 50.0, 4.0],
        ["BLK_DN_01", "SIG_DN_01", "SIG_DN_02", "LNK_11", 0.0, 1000.0, 50.0, 4.0],
        ["BLK_DN_02", "SIG_DN_02", "SIG_DN_03", "LNK_12", 0.0, 2000.0, 50.0, 4.0],
        ["BLK_DN_03", "SIG_DN_03", "SIG_DN_04", "LNK_13", 0.0, 5000.0, 50.0, 4.0],
        ["BLK_DN_04", "SIG_DN_04", "SIG_DN_05", "LNK_14", 0.0, 2500.0, 50.0, 4.0],
        ["BLK_DN_05", "SIG_DN_05", "SIG_DN_06", "LNK_15", 0.0, 4500.0, 50.0, 4.0],
        ["BLK_DN_06", "SIG_DN_06", "SIG_DN_07", "LNK_16", 0.0, 6000.0, 50.0, 4.0],
        ["BLK_DN_07", "SIG_DN_07", None, "LNK_17", 0.0, 4000.0, 50.0, 4.0],
        ["BLK_SD_01", "SIG_SD_01", "SIG_UP_05", "LNK_18", 0.0, 2000.0, 50.0, 4.0],
    ]

    routes_data = [
        [
            "RT_UP_MAIN",
            "SIG_UP_01",
            "SIG_UP_10",
            "LNK_01, LNK_02, LNK_03, LNK_04, LNK_05, LNK_06, LNK_07, LNK_08, LNK_09, LNK_10",
            "BLK_UP_01, BLK_UP_02, BLK_UP_03, BLK_UP_04, BLK_UP_05, BLK_UP_06, BLK_UP_07, BLK_UP_08, BLK_UP_09, BLK_UP_10",
            "RT_UP_SIDING",
        ],
        [
            "RT_UP_SIDING",
            "SIG_UP_01",
            "SIG_UP_10",
            "LNK_01, LNK_02, LNK_03, LNK_18, LNK_05, LNK_06, LNK_07, LNK_08, LNK_09, LNK_10",
            "BLK_UP_01, BLK_UP_02, BLK_UP_03, BLK_SD_01, BLK_UP_05, BLK_UP_06, BLK_UP_07, BLK_UP_08, BLK_UP_09, BLK_UP_10",
            "RT_UP_MAIN",
        ],
        [
            "RT_DN_MAIN",
            "SIG_DN_01",
            "SIG_DN_07",
            "LNK_11, LNK_12, LNK_13, LNK_14, LNK_15, LNK_16, LNK_17",
            "BLK_DN_01, BLK_DN_02, BLK_DN_03, BLK_DN_04, BLK_DN_05, BLK_DN_06, BLK_DN_07",
            None,
        ],
        [
            "RT_UP_SHORT",
            "SIG_UP_01",
            "SIG_UP_07",
            "LNK_01, LNK_02, LNK_03, LNK_04, LNK_05, LNK_06",
            "BLK_UP_01, BLK_UP_02, BLK_UP_03, BLK_UP_04, BLK_UP_05, BLK_UP_06",
            None,
        ],
        [
            "RT_DN_SHORT",
            "SIG_DN_04",
            "SIG_DN_07",
            "LNK_14, LNK_15, LNK_16, LNK_17",
            "BLK_DN_04, BLK_DN_05, BLK_DN_06, BLK_DN_07",
            None,
        ],
        [
            "RT_TVS_SEG",
            "SIG_UP_07",
            "SIG_UP_10",
            "LNK_07, LNK_08, LNK_09",
            "BLK_UP_07, BLK_UP_08, BLK_UP_09",
            None,
        ],
    ]

    for ws_def in sig_def.worksheets:
        if ws_def.name == "METADATA":
            continue
        if ws_def.name == "SignallingSystem":
            _build_data_worksheet(wb_sig, ws_def, sig_sys_data)
        elif ws_def.name == "Signals":
            _build_data_worksheet(wb_sig, ws_def, signals_data)
        elif ws_def.name == "Blocks":
            _build_data_worksheet(wb_sig, ws_def, blocks_data)
        elif ws_def.name == "InterlockingRoutes":
            _build_data_worksheet(wb_sig, ws_def, routes_data)

    p2 = out_dir / "02_Signalling.xlsx"
    wb_sig.save(p2)
    generated_files.append(p2)

    # 3. 03_RollingStock.xlsx
    wb_rs = openpyxl.Workbook()
    wb_rs.remove(wb_rs.active)
    rs_def = ALL_WORKBOOK_DEFS["ROLLING_STOCK"]
    _build_instructions_sheet(
        wb_rs,
        "Railway Headway Simulator — ROLLING_STOCK Workbook",
        "Rolling stock physical characteristics, traction, and braking curves",
        [
            (w.name, w.description)
            for w in rs_def.worksheets
            if w.name not in ("METADATA", "INSTRUCTIONS")
        ],
    )
    _build_metadata_sheet(
        wb_rs,
        "ROLLING_STOCK",
        "RS_EX05",
        "Comprehensive Demonstration Line Rolling Stock Dataset",
    )

    train_types_data = [
        [
            "TRN_HSR",
            "High Speed Passenger Train",
            200.0,
            400.0,
            450.0,
            0.08,
            200.0,
            0.8,
            0.9,
            1.2,
            "DETAILED_CURVE",
            8000.0,
            300.0,
            "SPEED_DEPENDENT_CURVE",
            "NET_EFFECTIVE",
            3.5,
            0.04,
            0.0006,
        ],
        [
            "TRN_REG",
            "Regional Passenger Train",
            150.0,
            160.0,
            200.0,
            0.10,
            160.0,
            1.0,
            1.0,
            1.3,
            "DETAILED_CURVE",
            3000.0,
            220.0,
            "SPEED_DEPENDENT_CURVE",
            "NET_EFFECTIVE",
            2.2,
            0.03,
            0.0004,
        ],
        [
            "TRN_FRT",
            "Heavy Freight Train",
            500.0,
            800.0,
            2000.0,
            0.12,
            100.0,
            0.4,
            0.5,
            0.7,
            "DETAILED_CURVE",
            4500.0,
            400.0,
            "SPEED_DEPENDENT_CURVE",
            "NET_EFFECTIVE",
            8.0,
            0.08,
            0.0010,
        ],
    ]

    traction_curves_data = [
        ["TRN_HSR", 0.0, 300.0],
        ["TRN_HSR", 50.0, 300.0],
        ["TRN_HSR", 100.0, 200.0],
        ["TRN_HSR", 160.0, 120.0],
        ["TRN_HSR", 200.0, 80.0],
        ["TRN_REG", 0.0, 220.0],
        ["TRN_REG", 40.0, 220.0],
        ["TRN_REG", 80.0, 150.0],
        ["TRN_REG", 120.0, 90.0],
        ["TRN_REG", 160.0, 50.0],
        ["TRN_FRT", 0.0, 400.0],
        ["TRN_FRT", 20.0, 400.0],
        ["TRN_FRT", 50.0, 250.0],
        ["TRN_FRT", 80.0, 150.0],
        ["TRN_FRT", 100.0, 100.0],
    ]

    braking_curves_data = [
        ["TRN_HSR", 0.0, 0.9],
        ["TRN_HSR", 50.0, 0.9],
        ["TRN_HSR", 100.0, 0.9],
        ["TRN_HSR", 160.0, 0.85],
        ["TRN_HSR", 200.0, 0.8],
        ["TRN_REG", 0.0, 1.0],
        ["TRN_REG", 40.0, 1.0],
        ["TRN_REG", 80.0, 1.0],
        ["TRN_REG", 120.0, 0.95],
        ["TRN_REG", 160.0, 0.9],
        ["TRN_FRT", 0.0, 0.5],
        ["TRN_FRT", 20.0, 0.5],
        ["TRN_FRT", 50.0, 0.48],
        ["TRN_FRT", 80.0, 0.45],
        ["TRN_FRT", 100.0, 0.4],
    ]

    for ws_def in rs_def.worksheets:
        if ws_def.name == "METADATA":
            continue
        if ws_def.name == "TrainTypes":
            _build_data_worksheet(wb_rs, ws_def, train_types_data)
        elif ws_def.name == "TractionCurves":
            _build_data_worksheet(wb_rs, ws_def, traction_curves_data)
        elif ws_def.name == "BrakingCurves":
            _build_data_worksheet(wb_rs, ws_def, braking_curves_data)

    p3 = out_dir / "03_RollingStock.xlsx"
    wb_rs.save(p3)
    generated_files.append(p3)

    # 4. 04_Operations.xlsx
    wb_ops = openpyxl.Workbook()
    wb_ops.remove(wb_ops.active)
    ops_def = ALL_WORKBOOK_DEFS["OPERATIONS"]
    _build_instructions_sheet(
        wb_ops,
        "Railway Headway Simulator — OPERATIONS Workbook",
        "Operational service patterns and station stopping profiles",
        [
            (w.name, w.description)
            for w in ops_def.worksheets
            if w.name not in ("METADATA", "INSTRUCTIONS")
        ],
    )
    _build_metadata_sheet(
        wb_ops,
        "OPERATIONS",
        "OPS_EX05",
        "Comprehensive Demonstration Line Operations Dataset",
    )

    service_patterns_data = [
        [
            "SVC_HSR_EXP_UP",
            "TRN_HSR",
            "LNK_01, LNK_02, LNK_03, LNK_04, LNK_05, LNK_06, LNK_07, LNK_08, LNK_09, LNK_10",
            1,
            15.0,
        ],
        [
            "SVC_REG_ALL_UP",
            "TRN_REG",
            "LNK_01, LNK_02, LNK_03, LNK_04, LNK_05, LNK_06, LNK_07, LNK_08, LNK_09, LNK_10",
            2,
            10.0,
        ],
        [
            "SVC_FRT_THRU_UP",
            "TRN_FRT",
            "LNK_01, LNK_02, LNK_03, LNK_04, LNK_05, LNK_06, LNK_07, LNK_08, LNK_09, LNK_10",
            3,
            30.0,
        ],
        [
            "SVC_HSR_EXP_DN",
            "TRN_HSR",
            "LNK_11, LNK_12, LNK_13, LNK_14, LNK_15, LNK_16, LNK_17",
            1,
            15.0,
        ],
        [
            "SVC_REG_ALL_DN",
            "TRN_REG",
            "LNK_11, LNK_12, LNK_13, LNK_14, LNK_15, LNK_16, LNK_17",
            2,
            10.0,
        ],
        [
            "SVC_FRT_LOOP_UP",
            "TRN_FRT",
            "LNK_01, LNK_02, LNK_03, LNK_18, LNK_05, LNK_06, LNK_07, LNK_08, LNK_09, LNK_10",
            3,
            30.0,
        ],
    ]

    stopping_patterns_data = [
        ["SVC_HSR_EXP_UP", 1, "STN_BETA", "PLT_B1", 90.0, 60.0, True],
        ["SVC_REG_ALL_UP", 1, "STN_ALPHA", "PLT_A1", 60.0, 45.0, True],
        ["SVC_REG_ALL_UP", 2, "STN_BETA", "PLT_B1", 75.0, 50.0, True],
        ["SVC_REG_ALL_UP", 3, "STN_GAMMA", "PLT_G1", 60.0, 45.0, True],
        ["SVC_HSR_EXP_DN", 1, "STN_BETA", "PLT_B3", 90.0, 60.0, True],
        ["SVC_REG_ALL_DN", 1, "STN_GAMMA", "PLT_G2", 60.0, 45.0, True],
        ["SVC_REG_ALL_DN", 2, "STN_BETA", "PLT_B3", 75.0, 50.0, True],
        ["SVC_REG_ALL_DN", 3, "STN_ALPHA", "PLT_A3", 60.0, 45.0, True],
    ]

    for ws_def in ops_def.worksheets:
        if ws_def.name == "METADATA":
            continue
        if ws_def.name == "ServicePatterns":
            _build_data_worksheet(wb_ops, ws_def, service_patterns_data)
        elif ws_def.name == "StoppingPatterns":
            _build_data_worksheet(wb_ops, ws_def, stopping_patterns_data)

    p4 = out_dir / "04_Operations.xlsx"
    wb_ops.save(p4)
    generated_files.append(p4)

    # 5. 05_HeadwayAnalysis.xlsx
    wb_an = openpyxl.Workbook()
    wb_an.remove(wb_an.active)
    an_def = ALL_WORKBOOK_DEFS["HEADWAY_ANALYSIS"]
    _build_instructions_sheet(
        wb_an,
        "Railway Headway Simulator — HEADWAY_ANALYSIS Workbook",
        "Headway analysis job settings, resolution tolerance, and evaluation parameters",
        [
            (w.name, w.description)
            for w in an_def.worksheets
            if w.name not in ("METADATA", "INSTRUCTIONS")
        ],
    )
    _build_metadata_sheet(
        wb_an,
        "HEADWAY_ANALYSIS",
        "AN_EX05",
        "Comprehensive Demonstration Line Headway Analysis Dataset",
    )

    analysis_settings_data = [
        [
            "AN_HSR_HSR_UP",
            "PAIRWISE_HEADWAY",
            "SVC_HSR_EXP_UP",
            "SVC_HSR_EXP_UP",
            0.1,
            0.1,
            600.0,
            30.0,
            "LNK_01",
            0.0,
        ],
        [
            "AN_REG_REG_UP",
            "PAIRWISE_HEADWAY",
            "SVC_REG_ALL_UP",
            "SVC_REG_ALL_UP",
            0.1,
            0.1,
            600.0,
            30.0,
            "LNK_01",
            0.0,
        ],
        [
            "AN_FRT_FRT_UP",
            "PAIRWISE_HEADWAY",
            "SVC_FRT_THRU_UP",
            "SVC_FRT_THRU_UP",
            0.1,
            0.1,
            900.0,
            45.0,
            "LNK_01",
            0.0,
        ],
        [
            "AN_HSR_REG_UP",
            "PAIRWISE_HEADWAY",
            "SVC_HSR_EXP_UP",
            "SVC_REG_ALL_UP",
            0.1,
            0.1,
            600.0,
            30.0,
            "LNK_01",
            0.0,
        ],
        [
            "AN_REG_HSR_UP",
            "PAIRWISE_HEADWAY",
            "SVC_REG_ALL_UP",
            "SVC_HSR_EXP_UP",
            0.1,
            0.1,
            600.0,
            30.0,
            "LNK_01",
            0.0,
        ],
        [
            "AN_FRT_HSR_UP",
            "PAIRWISE_HEADWAY",
            "SVC_FRT_THRU_UP",
            "SVC_HSR_EXP_UP",
            0.1,
            0.1,
            900.0,
            45.0,
            "LNK_01",
            0.0,
        ],
        [
            "AN_HSR_HSR_DN",
            "PAIRWISE_HEADWAY",
            "SVC_HSR_EXP_DN",
            "SVC_HSR_EXP_DN",
            0.1,
            0.1,
            600.0,
            30.0,
            "LNK_11",
            0.0,
        ],
        [
            "AN_REG_REG_DN",
            "PAIRWISE_HEADWAY",
            "SVC_REG_ALL_DN",
            "SVC_REG_ALL_DN",
            0.1,
            0.1,
            600.0,
            30.0,
            "LNK_11",
            0.0,
        ],
        [
            "AN_TVS_UP",
            "TVS_COMPARISON",
            "SVC_HSR_EXP_UP",
            "SVC_REG_ALL_UP",
            0.1,
            0.1,
            600.0,
            30.0,
            "LNK_08",
            0.0,
        ],
        [
            "AN_HIGHRES_UP",
            "PAIRWISE_HEADWAY",
            "SVC_HSR_EXP_UP",
            "SVC_HSR_EXP_UP",
            0.05,
            0.01,
            600.0,
            20.0,
            "LNK_01",
            0.0,
        ],
    ]

    for ws_def in an_def.worksheets:
        if ws_def.name == "METADATA":
            continue
        if ws_def.name == "AnalysisSettings":
            _build_data_worksheet(wb_an, ws_def, analysis_settings_data)

    p5 = out_dir / "05_HeadwayAnalysis.xlsx"
    wb_an.save(p5)
    generated_files.append(p5)

    # 6. 06_Scenarios.xlsx
    wb_scn = openpyxl.Workbook()
    wb_scn.remove(wb_scn.active)
    scn_def = ALL_WORKBOOK_DEFS["SCENARIOS"]
    _build_instructions_sheet(
        wb_scn,
        "Railway Headway Simulator — SCENARIOS Workbook",
        "Scenario definition registry and parameter overrides",
        [
            (w.name, w.description)
            for w in scn_def.worksheets
            if w.name not in ("METADATA", "INSTRUCTIONS")
        ],
    )
    _build_metadata_sheet(
        wb_scn,
        "SCENARIOS",
        "SCN_EX05",
        "Comprehensive Demonstration Line Scenarios Dataset",
    )

    scenario_definitions_data = [
        [
            "SCN_BASELINE",
            "Baseline full corridor operation with nominal limits and block layout",
            True,
        ],
        [
            "SCN_BLOCK_LENGTH",
            "Signalling sensitivity: subdivided block section",
            False,
        ],
        [
            "SCN_SPEED_UPGRADE",
            "Infrastructure upgrade: 200 km/h line speed enhancement",
            False,
        ],
        [
            "SCN_STATION_DWELL",
            "Operations sensitivity: extended peak dwell time",
            False,
        ],
        [
            "SCN_TUNNEL_SAFETY",
            "Safety rules comparison: multi-train TVS section capacity",
            False,
        ],
    ]

    overrides_data = [
        [
            "SCN_BLOCK_LENGTH",
            "signalling",
            "BLK_UP_01",
            "end_offset_m",
            "1500.0",
            "Block length reduction for headway optimization",
        ],
        [
            "SCN_SPEED_UPGRADE",
            "infrastructure",
            "LNK_01",
            "max_speed_kmh",
            "200.0",
            "Track geometry upgraded to 200 km/h",
        ],
        [
            "SCN_STATION_DWELL",
            "operations",
            "SVC_REG_ALL_UP",
            "dwell_time_s",
            "120.0",
            "Peak passenger boarding delay",
        ],
        [
            "SCN_TUNNEL_SAFETY",
            "infrastructure",
            "TVS_01",
            "max_train_occupancy",
            "2",
            "Allow dual train occupancy under enhanced ventilation",
        ],
    ]

    for ws_def in scn_def.worksheets:
        if ws_def.name == "METADATA":
            continue
        if ws_def.name == "ScenarioDefinitions":
            _build_data_worksheet(wb_scn, ws_def, scenario_definitions_data)
        elif ws_def.name == "Overrides":
            _build_data_worksheet(wb_scn, ws_def, overrides_data)

    p6 = out_dir / "06_Scenarios.xlsx"
    wb_scn.save(p6)
    generated_files.append(p6)

    return generated_files


if __name__ == "__main__":
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    files = generate_comprehensive_workbooks(target_dir)
    print(f"Successfully generated {len(files)} workbooks in {target_dir}")
