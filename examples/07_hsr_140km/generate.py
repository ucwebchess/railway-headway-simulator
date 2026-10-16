#!/usr/bin/env python3
"""Generator script for 07_hsr_140km reference dataset.

High-Speed Rail 140 km Corridor:
- 447 links, 448 nodes, TRK_UP (140,000 m total length, 320 km/h operational limit)
- 5 stations (STN_ADR at 0.47 km -> STN_DJD at 139.25 km)
- 92 signalling blocks, 91 signals, ETCS Level 2 signalling
- Rolling stock: TRN_HSR (8-car consist, 202 m, 465 t tare / 485 t loaded, 320 km/h)
  Davis equation: A = 2.506 kN, B = 0.04065 kN/(km/h), C = 0.00043 kN/(km/h)²
- Service: SRV_6000 calling at all 5 stations (120 s dwell)
- Analyses: AN_HSR_HSR_UP (factor 1.00) and AN_HSR_HSR_UP_95 (factor 0.95)
"""

from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

repo_root = Path(__file__).resolve().parents[2]
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from headway.data.excel_registry import ALL_WORKBOOK_DEFS, WorksheetDef

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

    ws.cell(row=5, column=1, value="Worksheets in this workbook:").font = Font(bold=True)
    for idx, (s_name, s_desc) in enumerate(sheets_info, start=6):
        ws.cell(row=idx, column=1, value=s_name).font = Font(bold=True)
        ws.cell(row=idx, column=2, value=s_desc)

    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 60


def _build_metadata_sheet(wb: openpyxl.Workbook, meta_rows: List[Tuple[str, Any]]) -> None:
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
    _build_instructions_sheet(wb, "INFRASTRUCTURE DATASET — 140 KM HSR CORRIDOR", "140 km 447-link corridor with 5 passenger stations", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "07_hsr_140km"),
        ("DATASET_ID", "EXP_07_INFRA"),
        ("WORKBOOK_TYPE", "INFRASTRUCTURE"),
        ("SCHEMA_VERSION", "1.0.0"),
        ("DESCRIPTION", "140 km High-Speed Rail Corridor Dataset"),
    ])

    n_links = 447
    n_nodes = 448

    nodes_data = [
        {"NODE_ID": f"ND_{i:04d}", "DESCRIPTION": f"Node {i}", "NODE_TYPE": "ENDPOINT" if i in (1, n_nodes) else "JUNCTION"}
        for i in range(1, n_nodes + 1)
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Nodes"), nodes_data)

    tracks_data = [
        {"TRACK_ID": "TRK_UP", "DESCRIPTION": "High-Speed Up Main Track", "DIRECTIONALITY": "NOMINAL"},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Tracks"), tracks_data)

    links_data = []
    # 446 links of 313.0m + 1 link of 402.0m = 140,000.0 m exactly
    for i in range(1, n_links + 1):
        l_len = 402.0 if i == n_links else 313.0
        links_data.append({
            "LINK_ID": f"LNK_{i:04d}",
            "TRACK_ID": "TRK_UP",
            "START_NODE_ID": f"ND_{i:04d}",
            "END_NODE_ID": f"ND_{i+1:04d}",
            "LENGTH_M": l_len,
            "MAX_SPEED_KMH": 320.0,
            "GRADIENT_PERMIL": 0.0,
            "CURVATURE_RADIUS_M": 0.0,
        })
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TrackLinks"), links_data)

    stations_data = [
        {"STATION_ID": "STN_ADR", "NAME": "Al-Dar Station", "CHAINAGE_KM": 0.47},
        {"STATION_ID": "STN_02", "NAME": "Station Two", "CHAINAGE_KM": 35.0},
        {"STATION_ID": "STN_03", "NAME": "Station Three", "CHAINAGE_KM": 70.0},
        {"STATION_ID": "STN_04", "NAME": "Station Four", "CHAINAGE_KM": 105.0},
        {"STATION_ID": "STN_DJD", "NAME": "Al-Djeddah Station", "CHAINAGE_KM": 139.25},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Stations"), stations_data)

    platforms_data = [
        {"PLATFORM_ID": "PLT_ADR", "STATION_ID": "STN_ADR", "LINK_ID": "LNK_0002", "START_OFFSET_M": 50.0, "END_OFFSET_M": 300.0, "LENGTH_M": 250.0},
        {"PLATFORM_ID": "PLT_02", "STATION_ID": "STN_02", "LINK_ID": "LNK_0112", "START_OFFSET_M": 50.0, "END_OFFSET_M": 300.0, "LENGTH_M": 250.0},
        {"PLATFORM_ID": "PLT_03", "STATION_ID": "STN_03", "LINK_ID": "LNK_0224", "START_OFFSET_M": 50.0, "END_OFFSET_M": 300.0, "LENGTH_M": 250.0},
        {"PLATFORM_ID": "PLT_04", "STATION_ID": "STN_04", "LINK_ID": "LNK_0336", "START_OFFSET_M": 50.0, "END_OFFSET_M": 300.0, "LENGTH_M": 250.0},
        {"PLATFORM_ID": "PLT_DJD", "STATION_ID": "STN_DJD", "LINK_ID": "LNK_0445", "START_OFFSET_M": 50.0, "END_OFFSET_M": 300.0, "LENGTH_M": 250.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Platforms"), platforms_data)

    sp_data = [
        {"STOPPING_POINT_ID": "SP_ADR", "PLATFORM_ID": "PLT_ADR", "LINK_ID": "LNK_0002", "OFFSET_M": 250.0},
        {"STOPPING_POINT_ID": "SP_02", "PLATFORM_ID": "PLT_02", "LINK_ID": "LNK_0112", "OFFSET_M": 250.0},
        {"STOPPING_POINT_ID": "SP_03", "PLATFORM_ID": "PLT_03", "LINK_ID": "LNK_0224", "OFFSET_M": 250.0},
        {"STOPPING_POINT_ID": "SP_04", "PLATFORM_ID": "PLT_04", "LINK_ID": "LNK_0336", "OFFSET_M": 250.0},
        {"STOPPING_POINT_ID": "SP_DJD", "PLATFORM_ID": "PLT_DJD", "LINK_ID": "LNK_0445", "OFFSET_M": 250.0},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "StoppingPoints"), sp_data)

    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Tunnels"), [])
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TVSSections"), [])
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "SharedResourceGroups"), [])

    wb.save(out_path)


def generate_signalling(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["SIGNALLING"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "SIGNALLING DATASET — 140 KM ETCS LEVEL 2", "ETCS L2 fixed-block architecture with 92 blocks", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "07_hsr_140km"),
        ("DATASET_ID", "EXP_07_SIG"),
        ("WORKBOOK_TYPE", "SIGNALLING"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    sig_sys_data = [
        {
            "TECHNOLOGY_TYPE": "ETCS_LEVEL_2",
            "ASPECT_MODEL": "THREE_ASPECT",
            "DEFAULT_OVERLAP_M": 100.0,
            "SIGHTING_TIME_S": 6.0,
            "ROUTE_SETUP_TIME_S": 3.0,
            "RELEASE_DELAY_S": 4.0,
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "SignallingSystem"), sig_sys_data)

    # 91 signals spaced across the 447 links (~every 4.9 links, so index min(i*4.9, 447))
    n_links = 447
    signals_data = []
    for i in range(1, 92):
        sig_id = f"SIG_{i:03d}"
        lnk_idx = min(int(i * 4.9), n_links)
        signals_data.append({
            "SIGNAL_ID": sig_id,
            "LINK_ID": f"LNK_{lnk_idx:04d}",
            "OFFSET_M": 50.0,
            "DIRECTION": "NOMINAL",
            "SIGNAL_TYPE": "MAIN",
            "SIGHTING_DISTANCE_M": 500.0,
        })
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Signals"), signals_data)

    # 92 blocks: BLK_UP_001 to BLK_UP_092
    blocks_data = []
    block_geom_data = []

    for i in range(1, 93):
        blk_id = f"BLK_UP_{i:03d}"
        entry_sig = f"SIG_{i:03d}" if i <= 91 else None
        exit_sig = f"SIG_{i+1:03d}" if i < 91 else None

        start_lnk = int((i - 1) * 447 / 92) + 1
        end_lnk = min(int(i * 447 / 92), 447)
        if end_lnk < start_lnk:
            end_lnk = start_lnk

        blocks_data.append({
            "BLOCK_ID": blk_id,
            "ENTRY_SIGNAL_ID": entry_sig,
            "EXIT_SIGNAL_ID": exit_sig,
            "OVERLAP_M": 100.0,
            "RELEASE_DELAY_S": 4.0,
        })

        seq = 1
        for l_idx in range(start_lnk, end_lnk + 1):
            l_len = 402.0 if l_idx == 447 else 313.0
            block_geom_data.append({
                "BLOCK_ID": blk_id,
                "SEQUENCE": seq,
                "LINK_ID": f"LNK_{l_idx:04d}",
                "START_OFFSET_M": 0.0,
                "END_OFFSET_M": l_len,
            })
            seq += 1

    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "Blocks"), blocks_data, omit_deprecated=True)
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "BlockGeometry"), block_geom_data)
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "TVSGeometry"), [])

    all_links_str = ", ".join(f"LNK_{i:04d}" for i in range(1, n_links + 1))
    all_blocks_str = ", ".join(f"BLK_UP_{i:03d}" for i in range(1, 93))
    routes_data = [
        {
            "ROUTE_ID": "RTE_UP_MAIN",
            "ENTRY_SIGNAL_ID": "SIG_001",
            "EXIT_SIGNAL_ID": "SIG_091",
            "LINK_SEQUENCE": all_links_str,
            "PROTECTED_BLOCKS": all_blocks_str,
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
    _build_instructions_sheet(wb, "ROLLING STOCK DATASET — TRN_HSR HIGH SPEED CONSIST", "320 km/h 8-car consist dynamics", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "07_hsr_140km"),
        ("DATASET_ID", "EXP_07_RS"),
        ("WORKBOOK_TYPE", "ROLLING_STOCK"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    trn_data = [
        {
            "TRAIN_TYPE_ID": "TRN_HSR",
            "DESCRIPTION": "High Speed Train 8-Car 320 km/h Consist",
            "LENGTH_M": 202.0,
            "MASS_EMPTY_T": 465.0,
            "MASS_LOADED_T": 485.0,
            "ROTATING_MASS_FACTOR": 0.08,
            "MAX_SPEED_KMH": 320.0,
            "MAX_ACCELERATION_MS2": 0.80,
            "SERVICE_DECEL_MS2": 0.80,
            "EMERGENCY_DECEL_MS2": 1.20,
            "TRACTION_MODEL_TYPE": "SIMPLIFIED_POWER_FORCE",
            "POWER_KW": 8800.0,
            "MAX_TE_KN": 320.0,
            "BRAKING_MODEL_TYPE": "CONSTANT_DECELERATION",
            "BRAKING_SEMANTICS": "NET_EFFECTIVE",
            "DAVIS_A_KN": 2.506,
            "DAVIS_B_KN_PER_KMH": 0.04065,
            "DAVIS_C_KN_PER_KMH2": 0.00043,
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
    _build_instructions_sheet(wb, "OPERATIONS DATASET — 140 KM HSR SERVICE", "SRV_6000 stopping at all 5 stations", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "07_hsr_140km"),
        ("DATASET_ID", "EXP_07_OPS"),
        ("WORKBOOK_TYPE", "OPERATIONS"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    all_links_str = ", ".join(f"LNK_{i:04d}" for i in range(1, 448))
    sp_data = [
        {
            "SERVICE_PATTERN_ID": "SRV_6000",
            "TRAIN_TYPE_ID": "TRN_HSR",
            "ROUTE_LINK_SEQUENCE": all_links_str,
            "PRIORITY": 1,
            "PLANNED_HEADWAY_S": 300.0,
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "ServicePatterns"), sp_data)

    stops_data = [
        {"SERVICE_PATTERN_ID": "SRV_6000", "STOP_INDEX": 1, "STATION_ID": "STN_ADR", "PLATFORM_ID": "PLT_ADR", "DWELL_TIME_S": 120.0, "MIN_DWELL_S": 60.0, "IS_MANDATORY": True},
        {"SERVICE_PATTERN_ID": "SRV_6000", "STOP_INDEX": 2, "STATION_ID": "STN_02", "PLATFORM_ID": "PLT_02", "DWELL_TIME_S": 120.0, "MIN_DWELL_S": 60.0, "IS_MANDATORY": True},
        {"SERVICE_PATTERN_ID": "SRV_6000", "STOP_INDEX": 3, "STATION_ID": "STN_03", "PLATFORM_ID": "PLT_03", "DWELL_TIME_S": 120.0, "MIN_DWELL_S": 60.0, "IS_MANDATORY": True},
        {"SERVICE_PATTERN_ID": "SRV_6000", "STOP_INDEX": 4, "STATION_ID": "STN_04", "PLATFORM_ID": "PLT_04", "DWELL_TIME_S": 120.0, "MIN_DWELL_S": 60.0, "IS_MANDATORY": True},
        {"SERVICE_PATTERN_ID": "SRV_6000", "STOP_INDEX": 5, "STATION_ID": "STN_DJD", "PLATFORM_ID": "PLT_DJD", "DWELL_TIME_S": 120.0, "MIN_DWELL_S": 60.0, "IS_MANDATORY": True},
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "StoppingPatterns"), stops_data)

    wb.save(out_path)


def generate_headway_analysis(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["HEADWAY_ANALYSIS"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "HEADWAY ANALYSIS DATASET — 140 KM HSR CORRIDOR", "Baseline and 95% performance factor analyses", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "07_hsr_140km"),
        ("DATASET_ID", "EXP_07_AN"),
        ("WORKBOOK_TYPE", "HEADWAY_ANALYSIS"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    an_data = [
        {
            "ANALYSIS_ID": "AN_HSR_HSR_UP",
            "SCENARIO_ID": "SCEN_BASELINE",
            "LEADER_SERVICE_ID": "SRV_6000",
            "FOLLOWER_SERVICE_ID": "SRV_6000",
            "RUNNING_DIRECTION": "FORWARD",
            "SIGNALLING_SYSTEM": "ETCS_LEVEL_2",
            "HEADWAY_DEFINITION": "TECHNICAL_MINIMUM",
            "PERFORMANCE_FACTOR": 1.00,
        },
        {
            "ANALYSIS_ID": "AN_HSR_HSR_UP_95",
            "SCENARIO_ID": "SCEN_BASELINE",
            "LEADER_SERVICE_ID": "SRV_6000",
            "FOLLOWER_SERVICE_ID": "SRV_6000",
            "RUNNING_DIRECTION": "FORWARD",
            "SIGNALLING_SYSTEM": "ETCS_LEVEL_2",
            "HEADWAY_DEFINITION": "TECHNICAL_MINIMUM",
            "PERFORMANCE_FACTOR": 0.95,
        },
    ]
    _build_dict_worksheet(wb, next(w for w in wb_def.worksheets if w.name == "AnalysisSettings"), an_data)

    wb.save(out_path)


def generate_scenarios(out_path: Path) -> None:
    wb_def = ALL_WORKBOOK_DEFS["SCENARIOS"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheets_info = [(ws.name, ws.description) for ws in wb_def.worksheets if ws.name != "METADATA"]
    _build_instructions_sheet(wb, "SCENARIOS DATASET — 140 KM HSR CORRIDOR", "Baseline scenario definition", sheets_info)
    _build_metadata_sheet(wb, [
        ("PROJECT_ID", "07_hsr_140km"),
        ("DATASET_ID", "EXP_07_SCN"),
        ("WORKBOOK_TYPE", "SCENARIOS"),
        ("SCHEMA_VERSION", "1.0.0"),
    ])

    sc_data = [
        {"SCENARIO_ID": "SCEN_BASELINE", "DESCRIPTION": "Baseline 140 km HSR Corridor", "IS_BASELINE": True, "DEFAULT_PERFORMANCE_FACTOR": 1.00},
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
    print(f"Generated 07_hsr_140km reference dataset in {out}")
