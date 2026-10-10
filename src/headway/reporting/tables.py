"""Standardized engineering tables and export library.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 13, § 16, § 17 & § 24).
Satisfies:
- P13-TAB-001: Standard table formatting (dark navy header, alternating shading, right-aligned numbers).
- P13-TAB-002: Specified precision defaults (Headway 0.1s, Speed 1 km/h, Chainage 0.01 km, etc.).
- P13-TAB-003: Full unrounded precision preserved internally.
- P13-TAB-005: Export to CSV, Excel (.xlsx), and JSON.
- P13-TAB-006: Resources and stations listed in actual running order.
- P13-TBL-001 to 005: Pairwise conflict ranking and longest occupation tables.
- P13-OCC-001 to 004: Resource occupation timing tables.
- P13-PRV-001 to 003: Resource geometry provenance tables.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union
import numpy as np
import pandas as pd

from headway.analysis.blocking_time import ResourceBlockingInterval
from headway.analysis.headway_results import HeadwayResult, MixedTrafficHeadwayMatrix
from headway.infrastructure.direction import RunningDirection
from headway.reporting.result_models import (
    ConflictRankingRecord,
    ResourceProvenanceRecord,
    ResourceTimingRecord,
    StationStopRecord,
)
from headway.scenarios.scenario_comparison import ScenarioComparisonReport


class EngineeringTable:
    """Standardized engineering table container with precision formatting and multi-format export."""

    def __init__(
        self,
        table_id: str,
        title: str,
        raw_dataframe: pd.DataFrame,
        formatted_dataframe: Optional[pd.DataFrame] = None,
        running_direction: Optional[RunningDirection] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.table_id = table_id
        self.title = title
        self.raw_dataframe = raw_dataframe.copy()
        self.formatted_dataframe = formatted_dataframe.copy() if formatted_dataframe is not None else raw_dataframe.copy()
        self.running_direction = running_direction
        self.metadata = metadata or {}

    @property
    def row_count(self) -> int:
        return len(self.raw_dataframe)

    @property
    def columns(self) -> List[str]:
        return list(self.raw_dataframe.columns)

    def to_dataframe(self, formatted: bool = False) -> pd.DataFrame:
        """Return raw (unrounded) or formatted DataFrame."""
        return self.formatted_dataframe if formatted else self.raw_dataframe

    def to_csv(self, filepath: Optional[Union[str, Path]] = None, formatted: bool = False) -> str:
        """Export table to CSV format using unrounded values by default (P13-TAB-005)."""
        df = self.to_dataframe(formatted=formatted)
        csv_str = df.to_csv(index=False)
        if filepath:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_str, encoding="utf-8")
        return csv_str

    def to_excel(self, filepath: Union[str, Path], sheet_name: Optional[str] = None) -> None:
        """Export table to Excel OOXML (.xlsx) workbook (P13-TAB-005)."""
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        sn = sheet_name or self.table_id[:31]

        with pd.ExcelWriter(p, engine="openpyxl") as writer:
            self.raw_dataframe.to_excel(writer, sheet_name=sn, index=False)

    def to_json(self, filepath: Optional[Union[str, Path]] = None) -> str:
        """Export table structure and raw values to JSON (P13-TAB-005)."""
        out_dict = {
            "table_id": self.table_id,
            "title": self.title,
            "running_direction": self.running_direction.value if self.running_direction else None,
            "row_count": self.row_count,
            "columns": self.columns,
            "data": self.raw_dataframe.to_dict(orient="records"),
            "metadata": self.metadata,
        }
        json_str = json.dumps(out_dict, indent=2, default=str)
        if filepath:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json_str, encoding="utf-8")
        return json_str

    def to_html(self, formatted: bool = True) -> str:
        """Export HTML representation with dark navy header and alternating rows (P13-TAB-001)."""
        df = self.to_dataframe(formatted=formatted)

        header_html = "".join(f"<th style='background-color:#1B365D; color:#FFFFFF; padding:8px; text-align:left;'>{col}</th>" for col in df.columns)
        rows_html = []
        for i, row in df.iterrows():
            bg = "#FFFFFF" if i % 2 == 0 else "#F8F9FA"
            cells = "".join(f"<td style='padding:6px; border-bottom:1px solid #E2E8F0; text-align:right;'>{val}</td>" for val in row)
            rows_html.append(f"<tr style='background-color:{bg};'>{cells}</tr>")

        dir_tag = f"<div style='font-size:12px; color:#1B365D; font-weight:bold; margin-bottom:6px;'>Running Direction: {self.running_direction.value}</div>" if self.running_direction else ""

        return (
            f"<div style='font-family:Arial,sans-serif; margin:16px 0;'>"
            f"<h3 style='color:#1B365D; margin-bottom:4px;'>{self.title}</h3>"
            f"{dir_tag}"
            f"<table style='border-collapse:collapse; width:100%; font-size:13px; border:1px solid #CBD5E1;'>"
            f"<thead><tr>{header_html}</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody>"
            f"</table>"
            f"</div>"
        )


def create_conflict_ranking_table(
    headway_result: HeadwayResult,
    top_n: Optional[int] = None,
) -> EngineeringTable:
    """P13-TBL-001: Pairwise conflict ranking table."""
    conflicts = headway_result.conflict_ranking or headway_result.controlling_conflicts
    controlling_res_ids = {c.leader_resource_id for c in headway_result.controlling_conflicts}

    raw_rows = []
    formatted_rows = []

    for idx, c in enumerate(conflicts, start=1):
        is_ctrl = c.leader_resource_id in controlling_res_ids
        loc_m = getattr(c, "physical_location_m", None) or getattr(c, "conflict_point_m", 0.0) or 0.0
        fol_start = getattr(c, "follower_start_time_s", None) or getattr(c, "follower_unshifted_start_time_s", 0.0) or 0.0

        raw_rows.append(
            {
                "Rank": idx,
                "Leader Resource": c.leader_resource_id,
                "Follower Resource": c.follower_resource_id,
                "Conflict Type": getattr(c, "bottleneck_type", "RESOURCE_CONFLICT") or "RESOURCE_CONFLICT",
                "Physical Location (m)": loc_m,
                "Route Chainage (km)": loc_m / 1000.0,
                "Leader Release (s)": c.leader_release_time_s,
                "Follower Start (s)": fol_start,
                "Required Headway (s)": c.required_headway_s,
                "Slack (s)": c.slack_s,
                "Classification": "CONTROLLING" if is_ctrl else "NON_CONTROLLING",
            }
        )

        formatted_rows.append(
            {
                "Rank": idx,
                "Leader Resource": c.leader_resource_id,
                "Follower Resource": c.follower_resource_id,
                "Conflict Type": getattr(c, "bottleneck_type", "RESOURCE_CONFLICT") or "RESOURCE_CONFLICT",
                "Physical Location (m)": f"{loc_m:.1f}",
                "Route Chainage (km)": f"{(loc_m / 1000.0):.2f}",
                "Leader Release (s)": f"{c.leader_release_time_s:.1f}",
                "Follower Start (s)": f"{fol_start:.1f}",
                "Required Headway (s)": f"{c.required_headway_s:.1f}",
                "Slack (s)": f"{c.slack_s:.1f}",
                "Classification": "★ CONTROLLING" if is_ctrl else "NON_CONTROLLING",
            }
        )

        if top_n is not None and idx >= top_n:
            break

    df_raw = pd.DataFrame(raw_rows)
    df_fmt = pd.DataFrame(formatted_rows)

    return EngineeringTable(
        table_id="TBL_CONFLICT_RANKING",
        title="Pairwise Critical Conflict Ranking",
        raw_dataframe=df_raw,
        formatted_dataframe=df_fmt,
        running_direction=headway_result.running_direction,
    )


def create_longest_occupation_table(
    intervals: Sequence[ResourceBlockingInterval],
    top_n: Optional[int] = None,
    running_direction: RunningDirection = RunningDirection.FORWARD,
) -> EngineeringTable:
    """P13-TBL-002: Standalone longest resource blocking durations table."""
    sorted_intervals = sorted(intervals, key=lambda bi: bi.duration_s, reverse=True)

    raw_rows = []
    formatted_rows = []

    for idx, bi in enumerate(sorted_intervals, start=1):
        decomp = bi.decomposition
        setup = decomp.setup_time_s if decomp else 0.0
        run = decomp.running_time_s if decomp else 0.0
        dwell = decomp.dwell_time_s if decomp else 0.0
        rel = decomp.release_time_s if decomp else 0.0

        raw_rows.append(
            {
                "Rank": idx,
                "Resource ID": bi.resource_id,
                "Resource Category": str(bi.resource_category),
                "Total Duration (s)": bi.duration_s,
                "Setup Time (s)": setup,
                "Running Time (s)": run,
                "Dwell Time (s)": dwell,
                "Release Time (s)": rel,
            }
        )

        formatted_rows.append(
            {
                "Rank": idx,
                "Resource ID": bi.resource_id,
                "Resource Category": str(bi.resource_category),
                "Total Duration (s)": f"{bi.duration_s:.1f}",
                "Setup Time (s)": f"{setup:.1f}",
                "Running Time (s)": f"{run:.1f}",
                "Dwell Time (s)": f"{dwell:.1f}",
                "Release Time (s)": f"{rel:.1f}",
            }
        )

        if top_n is not None and idx >= top_n:
            break

    return EngineeringTable(
        table_id="TBL_LONGEST_OCCUPATION",
        title="Longest Resource Occupation Durations",
        raw_dataframe=pd.DataFrame(raw_rows),
        formatted_dataframe=pd.DataFrame(formatted_rows),
        running_direction=running_direction,
    )


def create_station_stopping_table(
    records: Sequence[StationStopRecord],
    running_direction: RunningDirection = RunningDirection.FORWARD,
) -> EngineeringTable:
    """P13-STN-006: Station stopping and dwell schedule table."""
    raw_rows = []
    formatted_rows = []

    for r in records:
        raw_rows.append(
            {
                "Train ID": r.train_id,
                "Station Name": r.station_name,
                "Platform": r.platform_id,
                "Route Chainage (km)": r.route_chainage_km,
                "Front Stop (m)": r.front_stopping_position_m,
                "Rear Stop (m)": r.rear_stopping_position_m,
                "Arrival Time (s)": r.arrival_time_s,
                "Dwell (s)": r.dwell_duration_s,
                "Departure Time (s)": r.departure_time_s,
            }
        )

        formatted_rows.append(
            {
                "Train ID": r.train_id,
                "Station Name": r.station_name,
                "Platform": r.platform_id,
                "Route Chainage (km)": f"{r.route_chainage_km:.2f}",
                "Front Stop (m)": f"{r.front_stopping_position_m:.1f}",
                "Rear Stop (m)": f"{r.rear_stopping_position_m:.1f}",
                "Arrival Time (s)": f"{r.arrival_time_s:.1f}",
                "Dwell (s)": f"{r.dwell_duration_s:.1f}",
                "Departure Time (s)": f"{r.departure_time_s:.1f}",
            }
        )

    return EngineeringTable(
        table_id="TBL_STATION_STOPPING",
        title="Station Stopping Positions & Passenger Dwell Timings",
        raw_dataframe=pd.DataFrame(raw_rows),
        formatted_dataframe=pd.DataFrame(formatted_rows),
        running_direction=running_direction,
    )


def create_resource_timing_table(
    records: Union[Sequence[ResourceTimingRecord], Sequence[ResourceBlockingInterval]],
    running_direction: RunningDirection = RunningDirection.FORWARD,
    controlling_resource_ids: Optional[Sequence[str]] = None,
) -> EngineeringTable:
    """P13-OCC-001: Detailed resource blocking breakdown table."""
    if records and isinstance(records[0], ResourceBlockingInterval):
        from headway.reporting.visualization_adapters import VisualizationAdapter
        records = VisualizationAdapter.adapt_resource_timing(records, controlling_resource_ids)

    raw_rows = []
    formatted_rows = []

    for r in records:
        raw_rows.append(
            {
                "Index": r.resource_index,
                "Resource ID": r.resource_id,
                "Category": r.resource_category,
                "Chainage (km)": r.route_chainage_km,
                "Length (m)": r.resource_length_m,
                "Setup (s)": r.setup_time_s,
                "Approach (s)": r.approach_time_s,
                "Running (s)": r.running_time_s,
                "Dwell (s)": r.dwell_time_s,
                "Clearance (s)": r.geometric_clearance_time_s,
                "Residual Rear (s)": r.residual_rear_time_s,
                "Release (s)": r.release_time_s,
                "Total Blocking (s)": r.total_blocking_s,
                "Controlling": r.is_controlling,
            }
        )

        formatted_rows.append(
            {
                "Index": r.resource_index,
                "Resource ID": f"★ {r.resource_id}" if r.is_controlling else r.resource_id,
                "Category": r.resource_category,
                "Chainage (km)": f"{r.route_chainage_km:.2f}",
                "Length (m)": f"{r.resource_length_m:.1f}",
                "Setup (s)": f"{r.setup_time_s:.1f}",
                "Approach (s)": f"{r.approach_time_s:.1f}",
                "Running (s)": f"{r.running_time_s:.1f}",
                "Dwell (s)": f"{r.dwell_time_s:.1f}",
                "Clearance (s)": f"{r.geometric_clearance_time_s:.1f}",
                "Residual Rear (s)": f"{r.residual_rear_time_s:.1f}",
                "Release (s)": f"{r.release_time_s:.1f}",
                "Total Blocking (s)": f"{r.total_blocking_s:.1f}",
                "Controlling": "YES" if r.is_controlling else "NO",
            }
        )

    return EngineeringTable(
        table_id="TBL_RESOURCE_TIMING",
        title="Detailed Resource Blocking Durations & 7-Component Breakdown",
        raw_dataframe=pd.DataFrame(raw_rows),
        formatted_dataframe=pd.DataFrame(formatted_rows),
        running_direction=running_direction,
    )


def create_resource_provenance_table(
    records: Sequence[ResourceProvenanceRecord],
    running_direction: RunningDirection = RunningDirection.FORWARD,
) -> EngineeringTable:
    """P13-PRV-001: Resource geometry provenance and baseline integrity table."""
    raw_rows = []
    formatted_rows = []

    for r in records:
        raw_rows.append(
            {
                "Resource ID": r.resource_id,
                "Type": r.resource_type,
                "Physical Chainage (km)": r.physical_chainage_km,
                "Length (m)": r.resource_length_m,
                "Geometry Source": r.geometry_source,
                "Dataset ID": r.dataset_id,
                "Version": r.dataset_version,
                "Baseline Invariant": "UNMODIFIED" if r.is_baseline_geometry else "OVERRIDDEN",
            }
        )

        formatted_rows.append(
            {
                "Resource ID": r.resource_id,
                "Type": r.resource_type,
                "Physical Chainage (km)": f"{r.physical_chainage_km:.2f}",
                "Length (m)": f"{r.resource_length_m:.1f}",
                "Geometry Source": r.geometry_source,
                "Dataset ID": r.dataset_id,
                "Version": r.dataset_version,
                "Baseline Invariant": "UNMODIFIED" if r.is_baseline_geometry else "OVERRIDDEN",
            }
        )

    return EngineeringTable(
        table_id="TBL_RESOURCE_PROVENANCE",
        title="Resource Geometry Provenance & Baseline Integrity Register",
        raw_dataframe=pd.DataFrame(raw_rows),
        formatted_dataframe=pd.DataFrame(formatted_rows),
        running_direction=running_direction,
    )


def create_headway_matrix_table(
    matrix: MixedTrafficHeadwayMatrix,
) -> EngineeringTable:
    """P13-MIX-001 & P13-TAB-005: Directional mixed-traffic headway matrix table."""
    df_raw = matrix.to_dataframe()
    # Support both map (pandas >= 2.1) and applymap (older pandas)
    mapper = getattr(df_raw, "map", getattr(df_raw, "applymap", None))
    df_fmt = mapper(lambda v: f"{v:.1f} s" if pd.notnull(v) and v > 0 else "INFEASIBLE")

    return EngineeringTable(
        table_id=f"TBL_HEADWAY_MATRIX_{matrix.running_direction.value}",
        title=f"Mixed-Traffic Minimum Headway Matrix [{matrix.running_direction.value}]",
        raw_dataframe=df_raw,
        formatted_dataframe=df_fmt,
        running_direction=matrix.running_direction,
    )


def create_scenario_comparison_table(
    comparison_report: ScenarioComparisonReport,
    running_direction: Optional[RunningDirection] = None,
) -> EngineeringTable:
    """P13-CMP-001 & P13-TAB-005: Multi-scenario comparative analytics table."""
    base_id = comparison_report.baseline_scenario_id
    cmp_ids = comparison_report.compared_scenario_ids

    raw_rows = []
    formatted_rows = []

    for s_id in cmp_ids:
        diffs = comparison_report.metric_differences.get(s_id, [])
        for d in diffs:
            raw_rows.append(
                {
                    "Comparison Scenario": s_id,
                    "Metric": d.metric_name,
                    "Baseline Value": d.baseline_value,
                    "Scenario Value": d.scenario_value,
                    "Absolute Delta": d.absolute_change,
                    "Percentage Delta (%)": d.percentage_change,
                    "Unit": d.unit,
                }
            )

            sign = "+" if d.percentage_change and d.percentage_change > 0 else ""
            pct_str = f"{sign}{d.percentage_change:.1f}%" if d.percentage_change is not None else "-"
            formatted_rows.append(
                {
                    "Comparison Scenario": s_id,
                    "Metric": d.metric_name.replace("_", " ").title(),
                    "Baseline Value": f"{d.baseline_value:.2f}" if d.baseline_value is not None else "-",
                    "Scenario Value": f"{d.scenario_value:.2f}" if d.scenario_value is not None else "-",
                    "Absolute Delta": f"{d.absolute_change:.2f}" if d.absolute_change is not None else "-",
                    "Percentage Delta (%)": pct_str,
                    "Unit": d.unit,
                }
            )

    return EngineeringTable(
        table_id="TBL_SCENARIO_COMPARISON",
        title="Multi-Scenario Metric Differences & Engineering Assessment",
        raw_dataframe=pd.DataFrame(raw_rows),
        formatted_dataframe=pd.DataFrame(formatted_rows),
        running_direction=running_direction,
    )


def export_table(
    table: EngineeringTable,
    filepath: Union[str, Path],
    format_type: Optional[str] = None,
) -> str:
    """Universal exporter for EngineeringTable supporting csv, xlsx, json, html."""
    p = Path(filepath)
    fmt = (format_type or p.suffix.lstrip(".")).lower()
    if fmt == "csv":
        return table.to_csv(filepath=p)
    elif fmt in ("xlsx", "excel"):
        table.to_excel(filepath=p)
        return str(p)
    elif fmt == "json":
        return table.to_json(filepath=p)
    elif fmt in ("html", "htm"):
        html_str = table.to_html()
        p.write_text(html_str, encoding="utf-8")
        return str(p)
    else:
        raise ValueError(
            f"Unsupported export format '{fmt}'. Supported formats: csv, xlsx, json, html."
        )
