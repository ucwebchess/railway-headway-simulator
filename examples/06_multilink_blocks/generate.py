#!/usr/bin/env python3
"""Generator script for 06_multilink_blocks reference dataset.

Demonstrates Schema Version 1.2.0 multi-link signalling blocks and multi-link
Tunnel Ventilation Sections (TVS) using dedicated BlockGeometry and TVSGeometry worksheets.
"""

from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# Ensure src/ is importable
repo_root = Path(__file__).resolve().parents[2]
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from headway.data.excel_registry import (
    ALL_WORKBOOK_DEFS,
    WorksheetDef,
)

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
    ws = wb.create_sheet(title="INSTRUCTIONS", index=0)
    ws.views.sheetView[0].showGridLines = True
    ws.cell(row=1, column=1, value=title_str).font = Font(name="Calibri", size=14, bold=True, color="0F2B48")
    ws.cell(row=2, column=1, value=f"Purpose: {purpose_str}").font = Font(size=11, italic=True)
    ws.cell(row=3, column=1, value="Schema Version: 1.0.0").font = Font(size=10, bold=True)

    instructions = [
        "",
        "GENERAL INSTRUCTIONS FOR ENGINEERING DATA ENTRY:",
        "1. Do not modify, remove, or reorder column header names in Row 1 of data worksheets.",
        "2. Review the units specified in Row 2 for each column (e.g. km/h, m, tonnes, kN, ‰).",
        "3. Row 3 contains a minimal valid baseline network for demonstration purposes. You may modify or replace it with your own railway data. The example is designed to load without validation errors.",
        "4. Identifiers must be unique within each worksheet and must not contain special symbols or spaces.",
        "5. Cross-references (such as Link IDs, Station IDs, Train Type IDs) must match exact casing.",
        "6. Do not save workbook with Excel macros (.xlsm is prohibited).",
        "7. For multi-link signalling blocks or TVS sections, define spatial geometry intervals in 'BlockGeometry' or 'TVSGeometry'.",
        "",
        "WORKSHEET INVENTORY:",
    ]
    for idx, line in enumerate(instructions, start=4):
        ws.cell(row=idx, column=1, value=line).font = Font(name="Calibri", size=10)

    start_r = 4 + len(instructions)
    for offset, (s_name, s_desc) in enumerate(sheets_info):
        r = start_r + offset
        ws.cell(row=r, column=1, value=f"• {s_name}:").font = Font(name="Calibri", size=10, bold=True)
        ws.cell(row=r, column=2, value=s_desc).font = Font(name="Calibri", size=10)

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 65


def _build_metadata_sheet(wb: openpyxl.Workbook, meta_rows: List[Tuple[str, str]]) -> None:
    ws = wb.create_sheet(title="METADATA")
    ws.views.sheetView[0].showGridLines = True
    ws.cell(row=1, column=1, value="PROPERTY").font = HEADER_FONT
    ws.cell(row=1, column=1).fill = HEADER_FILL
    ws.cell(row=1, column=2, value="VALUE").font = HEADER_FONT
    ws.cell(row=1, column=2).fill = HEADER_FILL

    for r_idx, (k, v) in enumerate(meta_rows, start=2):
        c1 = ws.cell(row=r_idx, column=1, value=k)
        c2 = ws.cell(row=r_idx, column=2, value=v)
        c1.font = DATA_FONT
        c2.font = DATA_FONT
        c1.border = THIN_BORDER
        c2.border = THIN_BORDER

    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 40


def _build_dict_worksheet(
    wb: openpyxl.Workbook,
    ws_def: WorksheetDef,
    rows_data: List[Dict[str, Any]],
    omit_deprecated: bool = True,
) -> None:
    ws = wb.create_sheet(title=ws_def.name)
    ws.views.sheetView[0].showGridLines = True

    active_cols = [c for c in ws_def.columns if not (omit_deprecated and getattr(c, "deprecated", False))]

    for c_idx, col in enumerate(active_cols, start=1):
        cell_h = ws.cell(row=1, column=c_idx, value=col.name)
        cell_h.font = HEADER_FONT
        cell_h.fill = HEADER_FILL
        cell_h.alignment = Alignment(horizontal="center", vertical="center")
        cell_h.border = THIN_BORDER

        unit_str = f"[{col.excel_unit}]" if col.excel_unit else ("(Required)" if col.required else "(Optional)")
        cell_sub = ws.cell(row=2, column=c_idx, value=unit_str)
        cell_sub.font = SUBHEADER_FONT
        cell_sub.fill = SUBHEADER_FILL
        cell_sub.alignment = Alignment(horizontal="center", vertical="center")
        cell_sub.border = THIN_BORDER

        ws.column_dimensions[openpyxl.utils.get_column_letter(c_idx)].width = max(len(col.name) + 4, 16)

    for r_offset, row_dict in enumerate(rows_data):
        r_idx = 3 + r_offset
        for c_idx, col in enumerate(active_cols, start=1):
            val = row_dict.get(col.name)
            if val is None:
                val = row_dict.get(col.canonical_name, col.default_value)
            cell_d = ws.cell(row=r_idx, column=c_idx, value=val)
            cell_d.font = DATA_FONT
            cell_d.border = THIN_BORDER
            if isinstance(val, (int, float)):
                cell_d.alignment = Alignment(horizontal="right")
            else:
                cell_d.alignment = Alignment(horizontal="left")


def generate_infrastructure(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["INFRASTRUCTURE"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "INFRASTRUCTURE DATASET — MULTI-LINK DEMONSTRATION", "Corridor topology and multi-link TVS sections", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "06_multilink_blocks"),
        ("DATASET_ID", "EXP_06_INFRA"),
        ("WORKBOOK_TYPE", "INFRASTRUCTURE"),
        ("SCHEMA_VERSION", "1.0.0"),
        ("DESCRIPTION", "Multi-link blocks and multi-link TVS demonstration"),
    ])

    nodes_data = [
        {"NODE_ID": "ND_01", "DESCRIPTION": "Origin endpoint", "NODE_TYPE": "ENDPOINT"},
        {"NODE_ID": "ND_02", "DESCRIPTION": "Junction Alpha", "NODE_TYPE": "JUNCTION"},
        {"NODE_ID": "ND_03", "DESCRIPTION": "Tunnel North Portal", "NODE_TYPE": "JUNCTION"},
        {"NODE_ID": "ND_04", "DESCRIPTION": "Tunnel South Portal", "NODE_TYPE": "JUNCTION"},
        {"NODE_ID": "ND_05", "DESCRIPTION": "Destination endpoint", "NODE_TYPE": "ENDPOINT"},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Nodes"), nodes_data)

    tracks_data = [
        {"TRACK_ID": "TRK_M1", "DESCRIPTION": "Main Corridor", "DIRECTIONALITY": "BIDIRECTIONAL"},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Tracks"), tracks_data)

    links_data = [
        {"LINK_ID": "LNK_01", "TRACK_ID": "TRK_M1", "START_NODE_ID": "ND_01", "END_NODE_ID": "ND_02", "LENGTH_M": 1000.0, "MAX_SPEED_KMH": 120.0, "GRADIENT_PERMIL": 0.0, "CURVATURE_RADIUS_M": 0.0},
        {"LINK_ID": "LNK_02", "TRACK_ID": "TRK_M1", "START_NODE_ID": "ND_02", "END_NODE_ID": "ND_03", "LENGTH_M": 1200.0, "MAX_SPEED_KMH": 120.0, "GRADIENT_PERMIL": 0.0, "CURVATURE_RADIUS_M": 0.0},
        {"LINK_ID": "LNK_03", "TRACK_ID": "TRK_M1", "START_NODE_ID": "ND_03", "END_NODE_ID": "ND_04", "LENGTH_M": 1000.0, "MAX_SPEED_KMH": 120.0, "GRADIENT_PERMIL": 0.0, "CURVATURE_RADIUS_M": 0.0},
        {"LINK_ID": "LNK_04", "TRACK_ID": "TRK_M1", "START_NODE_ID": "ND_04", "END_NODE_ID": "ND_05", "LENGTH_M": 1500.0, "MAX_SPEED_KMH": 120.0, "GRADIENT_PERMIL": 0.0, "CURVATURE_RADIUS_M": 0.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TrackLinks"), links_data)

    stations_data = [
        {"STATION_ID": "STN_01", "NAME": "Station Alpha", "CHAINAGE_KM": 0.2},
        {"STATION_ID": "STN_02", "NAME": "Station Beta", "CHAINAGE_KM": 4.2},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Stations"), stations_data)

    platforms_data = [
        {"PLATFORM_ID": "PLT_01", "STATION_ID": "STN_01", "LINK_ID": "LNK_01", "START_OFFSET_M": 100.0, "END_OFFSET_M": 300.0, "LENGTH_M": 200.0},
        {"PLATFORM_ID": "PLT_02", "STATION_ID": "STN_02", "LINK_ID": "LNK_04", "START_OFFSET_M": 1000.0, "END_OFFSET_M": 1300.0, "LENGTH_M": 300.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Platforms"), platforms_data)

    sp_data = [
        {"STOPPING_POINT_ID": "SP_01", "PLATFORM_ID": "PLT_01", "LINK_ID": "LNK_01", "OFFSET_M": 250.0},
        {"STOPPING_POINT_ID": "SP_02", "PLATFORM_ID": "PLT_02", "LINK_ID": "LNK_04", "OFFSET_M": 1200.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "StoppingPoints"), sp_data)

    tunnels_data = [
        {"TUNNEL_ID": "TNL_01", "NAME": "Summit Mountain Tunnel", "DESCRIPTION": "Bored single-tube tunnel"},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Tunnels"), tunnels_data)

    # TVSSections: deprecated geometry columns omitted
    tvs_data = [
        {"TVS_ID": "TVS_01", "TUNNEL_ID": "TNL_01", "TRACK_ID": "TRK_M1", "MAX_OCCUPANCY": 1, "HOLDING_SIGNAL_ID": "SIG_02", "RELEASE_DELAY_S": 15.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TVSSections"), tvs_data, omit_deprecated=True)

    # TVSGeometry: multi-link TVS spanning LNK_02 and LNK_03
    tvs_geom_data = [
        {"TVS_ID": "TVS_01", "SEQUENCE": 1, "LINK_ID": "LNK_02", "START_OFFSET_M": 600.0, "END_OFFSET_M": 1200.0},
        {"TVS_ID": "TVS_01", "SEQUENCE": 2, "LINK_ID": "LNK_03", "START_OFFSET_M": 0.0, "END_OFFSET_M": 500.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TVSGeometry"), tvs_geom_data)

    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "SharedResourceGroups"), [])

    wb.save(out_path)


def generate_signalling(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["SIGNALLING"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "SIGNALLING DATASET — MULTI-LINK DEMONSTRATION", "Signalling system and multi-link BlockGeometry", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "06_multilink_blocks"),
        ("DATASET_ID", "EXP_06_SIG"),
        ("WORKBOOK_TYPE", "SIGNALLING"),
        ("SCHEMA_VERSION", "1.0.0"),
        ("DESCRIPTION", "Multi-link blocks signalling model"),
    ])

    sig_sys_data = [
        {
            "TECHNOLOGY_TYPE": "GENERIC_FIXED_BLOCK_ENGINEERING_MODEL",
            "ASPECT_MODEL": "THREE_ASPECT",
            "DEFAULT_OVERLAP_M": 50.0,
            "SIGHTING_TIME_S": 8.0,
            "ROUTE_SETUP_TIME_S": 3.0,
            "RELEASE_DELAY_S": 4.0,
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "SignallingSystem"), sig_sys_data)

    signals_data = [
        {"SIGNAL_ID": "SIG_01", "LINK_ID": "LNK_01", "OFFSET_M": 100.0, "DIRECTION": "NOMINAL", "SIGNAL_TYPE": "MAIN", "SIGHTING_DISTANCE_M": 200.0},
        {"SIGNAL_ID": "SIG_02", "LINK_ID": "LNK_02", "OFFSET_M": 600.0, "DIRECTION": "NOMINAL", "SIGNAL_TYPE": "MAIN", "SIGHTING_DISTANCE_M": 200.0},
        {"SIGNAL_ID": "SIG_03", "LINK_ID": "LNK_03", "OFFSET_M": 500.0, "DIRECTION": "NOMINAL", "SIGNAL_TYPE": "MAIN", "SIGHTING_DISTANCE_M": 200.0},
        {"SIGNAL_ID": "SIG_04", "LINK_ID": "LNK_04", "OFFSET_M": 1400.0, "DIRECTION": "NOMINAL", "SIGNAL_TYPE": "MAIN", "SIGHTING_DISTANCE_M": 200.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Signals"), signals_data)

    # Blocks: deprecated geometry columns omitted
    blocks_data = [
        {"BLOCK_ID": "BLK_01", "ENTRY_SIGNAL_ID": "SIG_01", "EXIT_SIGNAL_ID": "SIG_02", "OVERLAP_M": 50.0, "RELEASE_DELAY_S": 4.0},
        {"BLOCK_ID": "BLK_02", "ENTRY_SIGNAL_ID": "SIG_02", "EXIT_SIGNAL_ID": "SIG_03", "OVERLAP_M": 50.0, "RELEASE_DELAY_S": 4.0},
        {"BLOCK_ID": "BLK_03", "ENTRY_SIGNAL_ID": "SIG_03", "EXIT_SIGNAL_ID": "SIG_04", "OVERLAP_M": 50.0, "RELEASE_DELAY_S": 4.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Blocks"), blocks_data, omit_deprecated=True)

    # BlockGeometry: each block spans consecutive links
    block_geom_data = [
        {"BLOCK_ID": "BLK_01", "SEQUENCE": 1, "LINK_ID": "LNK_01", "START_OFFSET_M": 100.0, "END_OFFSET_M": 1000.0},
        {"BLOCK_ID": "BLK_01", "SEQUENCE": 2, "LINK_ID": "LNK_02", "START_OFFSET_M": 0.0, "END_OFFSET_M": 600.0},
        {"BLOCK_ID": "BLK_02", "SEQUENCE": 1, "LINK_ID": "LNK_02", "START_OFFSET_M": 600.0, "END_OFFSET_M": 1200.0},
        {"BLOCK_ID": "BLK_02", "SEQUENCE": 2, "LINK_ID": "LNK_03", "START_OFFSET_M": 0.0, "END_OFFSET_M": 500.0},
        {"BLOCK_ID": "BLK_03", "SEQUENCE": 1, "LINK_ID": "LNK_03", "START_OFFSET_M": 500.0, "END_OFFSET_M": 1000.0},
        {"BLOCK_ID": "BLK_03", "SEQUENCE": 2, "LINK_ID": "LNK_04", "START_OFFSET_M": 0.0, "END_OFFSET_M": 1400.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "BlockGeometry"), block_geom_data)
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TVSGeometry"), [])

    routes_data = [
        {
            "ROUTE_ID": "RTE_01",
            "ENTRY_SIGNAL_ID": "SIG_01",
            "EXIT_SIGNAL_ID": "SIG_04",
            "LINK_SEQUENCE": "LNK_01,LNK_02,LNK_03,LNK_04",
            "PROTECTED_BLOCKS": "BLK_01,BLK_02,BLK_03",
            "CONFLICTING_ROUTES": "",
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "InterlockingRoutes"), routes_data)

    wb.save(out_path)


def generate_rolling_stock(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["ROLLING_STOCK"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "ROLLING STOCK DATASET — MULTI-LINK DEMONSTRATION", "Commuter fleet dynamics", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "06_multilink_blocks"),
        ("DATASET_ID", "EXP_06_RS"),
        ("WORKBOOK_TYPE", "ROLLING_STOCK"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    trn_data = [
        {
            "TRAIN_TYPE_ID": "TRN_COMMUTER",
            "DESCRIPTION": "Standard 8-car commuter EMU",
            "LENGTH_M": 160.0,
            "MASS_EMPTY_T": 240.0,
            "MASS_LOADED_T": 320.0,
            "ROTATING_MASS_FACTOR": 0.10,
            "MAX_SPEED_KMH": 120.0,
            "MAX_ACCELERATION_MS2": 1.0,
            "SERVICE_DECEL_MS2": 0.85,
            "EMERGENCY_DECEL_MS2": 1.15,
            "TRACTION_MODEL_TYPE": "SIMPLIFIED_POWER_FORCE",
            "POWER_KW": 4000.0,
            "MAX_TE_KN": 300.0,
            "BRAKING_MODEL_TYPE": "CONSTANT_DECELERATION",
            "BRAKING_SEMANTICS": "NET_EFFECTIVE",
            "DAVIS_A_KN": 3.5,
            "DAVIS_B_KN_PER_KMH": 0.05,
            "DAVIS_C_KN_PER_KMH2": 0.002,
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TrainTypes"), trn_data)
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TractionCurves"), [])
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "BrakingCurves"), [])

    wb.save(out_path)


def generate_operations(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["OPERATIONS"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "OPERATIONS DATASET — MULTI-LINK DEMONSTRATION", "Timetable and service pattern", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "06_multilink_blocks"),
        ("DATASET_ID", "EXP_06_OPS"),
        ("WORKBOOK_TYPE", "OPERATIONS"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    sp_data = [
        {
            "SERVICE_PATTERN_ID": "SP_COMMUTER",
            "TRAIN_TYPE_ID": "TRN_COMMUTER",
            "ROUTE_LINK_SEQUENCE": "LNK_01,LNK_02,LNK_03,LNK_04",
            "PRIORITY": 1,
            "PLANNED_HEADWAY_MIN": 3.0,
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "ServicePatterns"), sp_data)

    stp_data = [
        {"SERVICE_PATTERN_ID": "SP_COMMUTER", "STOP_INDEX": 1, "STATION_ID": "STN_01", "PLATFORM_ID": "PLT_01", "DWELL_TIME_S": 30.0, "MIN_DWELL_S": 20.0, "IS_MANDATORY": True},
        {"SERVICE_PATTERN_ID": "SP_COMMUTER", "STOP_INDEX": 2, "STATION_ID": "STN_02", "PLATFORM_ID": "PLT_02", "DWELL_TIME_S": 30.0, "MIN_DWELL_S": 20.0, "IS_MANDATORY": True},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "StoppingPatterns"), stp_data)

    wb.save(out_path)


def generate_headway_analysis(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["HEADWAY_ANALYSIS"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "HEADWAY ANALYSIS DATASET — MULTI-LINK DEMONSTRATION", "Pairwise headway settings", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "06_multilink_blocks"),
        ("DATASET_ID", "EXP_06_HA"),
        ("WORKBOOK_TYPE", "HEADWAY_ANALYSIS"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    an_data = [
        {
            "ANALYSIS_ID": "AN_COMMUTER",
            "ANALYSIS_TYPE": "PAIRWISE_HEADWAY",
            "LEADER_SERVICE_ID": "SP_COMMUTER",
            "FOLLOWER_SERVICE_ID": "SP_COMMUTER",
            "INTEGRATION_STEP_S": 0.1,
            "HEADWAY_TOLERANCE_S": 0.05,
            "SEARCH_WINDOW_S": 300.0,
            "PLANNING_MARGIN_S": 18.0,
            "REF_LINK_ID": "LNK_01",
            "REF_OFFSET_M": 100.0,
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "AnalysisSettings"), an_data)

    wb.save(out_path)


def generate_scenarios(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["SCENARIOS"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "SCENARIOS DATASET — MULTI-LINK DEMONSTRATION", "Baseline scenario definition", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "06_multilink_blocks"),
        ("DATASET_ID", "EXP_06_SCN"),
        ("WORKBOOK_TYPE", "SCENARIOS"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    sc_data = [
        {"SCENARIO_ID": "SCN_BASELINE", "DESCRIPTION": "Baseline Multi-Link Block Network", "IS_BASELINE": True},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "ScenarioDefinitions"), sc_data)
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Overrides"), [])

    wb.save(out_path)


def generate_all(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    generate_infrastructure(target_dir / "01_Infrastructure.xlsx")
    generate_signalling(target_dir / "02_Signalling.xlsx")
    generate_rolling_stock(target_dir / "03_RollingStock.xlsx")
    generate_operations(target_dir / "04_Operations.xlsx")
    generate_headway_analysis(target_dir / "05_HeadwayAnalysis.xlsx")
    generate_scenarios(target_dir / "06_Scenarios.xlsx")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent
    generate_all(out)
    print(f"Generated 06_multilink_blocks reference dataset in {out}")
