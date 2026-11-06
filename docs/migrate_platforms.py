#!/usr/bin/env python3
"""v1.14.0 migration helper: legacy ``Platforms`` + ``StoppingPoints`` -> ``PlatformSpans``.

Usage
-----
    python docs/migrate_platforms.py INFRASTRUCTURE.xlsx [--operations OPERATIONS.xlsx]
                                     [--out-dir DIR | --in-place] [--dry-run]

What it does
------------
1. Reads ``Tracks``, ``TrackLinks``, the legacy ``Platforms`` and ``StoppingPoints`` sheets.
2. Places every legacy (link-level) platform row on its track's **per-track chainage**
   (each track starts at 0 km at the start node of its first link; links in topological
   order — exactly the frame the importer uses).
3. Groups rows into physical platforms: same ``STATION_ID`` + same track + same ID stem
   (the ID without a trailing ``_<n>`` / ``-<n>``) **and** contiguous along the track.
   A single-row group keeps its ID unchanged; a multi-row group is named by the stem
   (e.g. ``PLT_ADR_A1_1 .. PLT_ADR_A1_6`` -> ``PLT_ADR_A1``).
4. Converts each ``StoppingPoints`` row (link + offset) into the span's
   ``SEGMENT_HINT_OFFSET_M`` (metres from ``START_CHAINAGE_KM``).
5. Writes a copy of the Infrastructure workbook with ``Platforms`` / ``StoppingPoints``
   removed and a ``PlatformSpans`` sheet added; with ``--operations`` also a copy of the
   Operations workbook whose ``StoppingPatterns.PLATFORM_ID`` values are rewritten to the
   new platform IDs.

Originals are never modified unless ``--in-place`` is given. The importer performs **no**
auto-migration — run this script, review the printed table, then load the migrated files.
See ``docs/MIGRATION_v1.14.0.md``.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import openpyxl

try:  # single source of truth for the chainage frame and segmentation
    from headway.data.platform_spans import MIN_SPAN_LENGTH_M, track_chainage_frame
except ImportError:  # pragma: no cover - running from a checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from headway.data.platform_spans import MIN_SPAN_LENGTH_M, track_chainage_frame

#: In-workbook description of SEGMENT_HINT_OFFSET_M (INSTRUCTIONS sheet).
HINT_DESCRIPTION = "Selects which platform segment the train berths on (not the exact stop position)"

SPAN_COLUMNS = [
    "PLATFORM_ID", "STATION_ID", "TRACK_ID", "START_CHAINAGE_KM", "END_CHAINAGE_KM",
    "SEGMENT_HINT_OFFSET_M", "DESCRIPTION",
]
SPAN_SUBHEADER = ["(Required)", "(Required)", "(Required)", "[km]", "[km]", "[m]", "(Optional)"]
CONTIGUITY_TOL_M = 0.01
_STEM_RE = re.compile(r"[_\-]\d+$")


class MigrationError(RuntimeError):
    pass


@dataclass
class LegacyPlatform:
    platform_id: str
    station_id: str
    link_id: str
    track_id: str
    start_m: float  # per-track chainage
    end_m: float


@dataclass
class MigratedSpan:
    platform_id: str
    station_id: str
    track_id: str
    start_m: float
    end_m: float
    segment_hint_offset_m: Optional[float]
    source_ids: List[str] = field(default_factory=list)
    stopping_point_ids: List[str] = field(default_factory=list)

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m

    def as_row(self) -> List[Any]:
        desc = "Migrated from Platforms: " + ", ".join(self.source_ids)
        if self.stopping_point_ids:
            desc += "; StoppingPoints: " + ", ".join(self.stopping_point_ids)
        return [
            self.platform_id, self.station_id, self.track_id,
            round(self.start_m / 1000.0, 6), round(self.end_m / 1000.0, 6),
            None if self.segment_hint_offset_m is None else round(self.segment_hint_offset_m, 3),
            desc,
        ]


@dataclass
class MigrationResult:
    spans: List[MigratedSpan]
    id_map: Dict[str, str]          # legacy platform ID -> new PLATFORM_ID
    warnings: List[str]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _is_subheader(row: Sequence[Any]) -> bool:
    return any(isinstance(c, str) and c.startswith(("(", "[")) for c in row if c is not None) and not any(
        isinstance(c, (int, float)) and not isinstance(c, bool) for c in row
    )


def read_sheet(wb: Any, name: str) -> List[Dict[str, Any]]:
    if name not in wb.sheetnames:
        return []
    rows = list(wb[name].iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h).strip().upper() if h is not None else None for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not r or not any(c is not None and str(c).strip() for c in r):
            continue
        if _is_subheader(r):
            continue
        out.append({h: v for h, v in zip(header, r) if h})
    return out


def _links_as_rows(link_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"link_id": str(r["LINK_ID"]).strip(), "track_id": str(r["TRACK_ID"]).strip(),
         "start_node_id": str(r["START_NODE_ID"]).strip(), "end_node_id": str(r["END_NODE_ID"]).strip(),
         "length_m": float(r["LENGTH_M"])}
        for r in link_rows if r.get("LINK_ID")
    ]


# ---------------------------------------------------------------------------
# Migration core (pure; used by the CLI and the tests)
# ---------------------------------------------------------------------------

def stem_of(platform_id: str) -> str:
    stem = _STEM_RE.sub("", platform_id)
    return stem or platform_id


def migrate_rows(platform_rows: List[Dict[str, Any]], stopping_point_rows: List[Dict[str, Any]],
                 track_link_rows: List[Dict[str, Any]]) -> MigrationResult:
    """Convert legacy Platforms + StoppingPoints rows (upper-case column keys) into spans."""
    links = _links_as_rows(track_link_rows)
    link_track = {lk["link_id"]: lk["track_id"] for lk in links}
    frames: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for tid in sorted({lk["track_id"] for lk in links}):
        try:
            frames[tid] = {t.link_id: (t.start_m, t.end_m) for t in track_chainage_frame(links, tid)}
        except Exception:  # noqa: BLE001 - non-chain track: only an error if a platform sits on it
            frames[tid] = {}

    warnings: List[str] = []
    legacy: List[LegacyPlatform] = []
    for r in platform_rows:
        pid = str(r["PLATFORM_ID"]).strip()
        lid = str(r["LINK_ID"]).strip()
        if lid not in link_track:
            raise MigrationError(f"Platform '{pid}': LINK_ID '{lid}' not found in TrackLinks.")
        tid = link_track[lid]
        if lid not in frames.get(tid, {}):
            raise MigrationError(f"Platform '{pid}': track '{tid}' is not a simple chain; per-track chainage undefined.")
        l0, _l1 = frames[tid][lid]
        so, eo = float(r["START_OFFSET_M"]), float(r["END_OFFSET_M"])
        lo, hi = min(so, eo), max(so, eo)
        legacy.append(LegacyPlatform(pid, str(r["STATION_ID"]).strip(), lid, tid, l0 + lo, l0 + hi))

    # Group: station + track + ID stem, then split into contiguous runs along the track.
    groups: Dict[Tuple[str, str, str], List[LegacyPlatform]] = {}
    for lp in legacy:
        groups.setdefault((lp.station_id, lp.track_id, stem_of(lp.platform_id)), []).append(lp)

    spans: List[MigratedSpan] = []
    id_map: Dict[str, str] = {}
    order = {lp.platform_id: i for i, lp in enumerate(legacy)}
    for (stn, tid, stem), members in sorted(groups.items(), key=lambda kv: min(order[m.platform_id] for m in kv[1])):
        members = sorted(members, key=lambda m: (m.start_m, m.end_m))
        runs: List[List[LegacyPlatform]] = [[members[0]]]
        for m in members[1:]:
            if abs(m.start_m - runs[-1][-1].end_m) <= CONTIGUITY_TOL_M:
                runs[-1].append(m)
            else:
                runs.append([m])
        for k, run in enumerate(runs, start=1):
            if len(run) == 1 and len(members) == 1:
                new_id = run[0].platform_id
            elif len(runs) == 1:
                new_id = stem
            else:
                new_id = run[0].platform_id if len(run) == 1 else f"{stem}_R{k}"
                warnings.append(
                    f"Platforms with stem '{stem}' at {stn}/{tid} are not contiguous; created separate span "
                    f"'{new_id}' from {[m.platform_id for m in run]} — please review."
                )
            spans.append(MigratedSpan(new_id, stn, tid, run[0].start_m, run[-1].end_m, None,
                                      source_ids=[m.platform_id for m in run]))
            for m in run:
                id_map[m.platform_id] = new_id

    # Unique IDs (a stem may collide with an unrelated single-row platform).
    seen: Dict[str, int] = {}
    for sp in spans:
        seen[sp.platform_id] = seen.get(sp.platform_id, 0) + 1
    for sp in spans:
        if seen[sp.platform_id] > 1 and len(sp.source_ids) > 1:
            old = sp.platform_id
            sp.platform_id = f"{old}_SPAN"
            for sid in sp.source_ids:
                id_map[sid] = sp.platform_id
            warnings.append(f"Span ID '{old}' collides with another platform; renamed to '{sp.platform_id}'.")

    short = [sp.platform_id for sp in spans if sp.length_m < MIN_SPAN_LENGTH_M]
    if short:
        warnings.append(f"Spans shorter than {MIN_SPAN_LENGTH_M:.0f} m will be rejected by the validator: {short}")

    # Stopping points -> segment hint offsets.
    by_id = {sp.platform_id: sp for sp in spans}
    for r in stopping_point_rows:
        spid = str(r.get("STOPPING_POINT_ID") or "").strip()
        legacy_pid = str(r["PLATFORM_ID"]).strip()
        lid = str(r["LINK_ID"]).strip()
        if legacy_pid not in id_map:
            raise MigrationError(f"StoppingPoint '{spid}': PLATFORM_ID '{legacy_pid}' not found in Platforms.")
        span = by_id[id_map[legacy_pid]]
        if lid not in frames.get(span.track_id, {}):
            raise MigrationError(f"StoppingPoint '{spid}': LINK_ID '{lid}' is not on track '{span.track_id}'.")
        stop_m = frames[span.track_id][lid][0] + float(r["OFFSET_M"])
        offset = stop_m - span.start_m
        if offset < -CONTIGUITY_TOL_M or offset > span.length_m + CONTIGUITY_TOL_M:
            raise MigrationError(
                f"StoppingPoint '{spid}' lies {offset:.3f} m from the start of platform '{span.platform_id}' "
                f"(length {span.length_m:.3f} m) — outside the platform."
            )
        if span.segment_hint_offset_m is not None:
            warnings.append(
                f"Platform '{span.platform_id}' has several stopping points; kept the first "
                f"({span.stopping_point_ids[0]}), ignored '{spid}'."
            )
            continue
        span.segment_hint_offset_m = min(max(offset, 0.0), span.length_m)
        span.stopping_point_ids.append(spid)
    for sp in spans:
        if sp.segment_hint_offset_m is None:
            warnings.append(f"Platform '{sp.platform_id}' had no stopping point; SEGMENT_HINT_OFFSET_M left blank (mid-platform).")
    return MigrationResult(spans=spans, id_map=id_map, warnings=warnings)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _copy_style(src_cell: Any, dst_cell: Any) -> None:
    if src_cell is not None and src_cell.has_style:
        dst_cell.font = copy(src_cell.font)
        dst_cell.fill = copy(src_cell.fill)
        dst_cell.border = copy(src_cell.border)
        dst_cell.alignment = copy(src_cell.alignment)


def write_infrastructure(src: Path, dst: Path, result: MigrationResult) -> None:
    wb = openpyxl.load_workbook(src)
    pos = wb.sheetnames.index("Platforms") if "Platforms" in wb.sheetnames else len(wb.sheetnames)
    hdr_style = wb["Platforms"].cell(1, 1) if "Platforms" in wb.sheetnames else None
    sub_style = wb["Platforms"].cell(2, 1) if "Platforms" in wb.sheetnames else None
    for legacy in ("Platforms", "StoppingPoints"):
        if legacy in wb.sheetnames:
            del wb[legacy]
    if "PlatformSpans" in wb.sheetnames:
        del wb["PlatformSpans"]
    ws = wb.create_sheet("PlatformSpans", pos)
    ws.append(SPAN_COLUMNS)
    ws.append(SPAN_SUBHEADER)
    for c in range(1, len(SPAN_COLUMNS) + 1):
        _copy_style(hdr_style, ws.cell(1, c))
        _copy_style(sub_style, ws.cell(2, c))
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 24 if c < 7 else 60
    for sp in result.spans:
        ws.append(sp.as_row())
    if "INSTRUCTIONS" in wb.sheetnames:  # keep the in-workbook sheet guide accurate
        for row in wb["INSTRUCTIONS"].iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and ("StoppingPoints" in cell.value or "Platforms" in cell.value):
                    cell.value = (cell.value.replace("StoppingPoints", "PlatformSpans.SEGMENT_HINT_OFFSET_M")
                                  .replace("Platforms", "PlatformSpans")
                                  .replace("Designated stopping points at platforms", HINT_DESCRIPTION))
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)


def write_operations(src: Path, dst: Path, id_map: Dict[str, str]) -> int:
    wb = openpyxl.load_workbook(src)
    changed = 0
    if "StoppingPatterns" in wb.sheetnames:
        ws = wb["StoppingPatterns"]
        header = [str(c.value).strip().upper() if c.value is not None else "" for c in ws[1]]
        if "PLATFORM_ID" in header:
            col = header.index("PLATFORM_ID") + 1
            for r in range(2, ws.max_row + 1):
                v = ws.cell(r, col).value
                if isinstance(v, str) and v.strip() in id_map and id_map[v.strip()] != v.strip():
                    ws.cell(r, col).value = id_map[v.strip()]
                    changed += 1
    if changed or Path(dst).resolve() != Path(src).resolve():  # never re-save an unchanged file in place
        dst.parent.mkdir(parents=True, exist_ok=True)
        wb.save(dst)
    return changed


def format_table(result: MigrationResult) -> str:
    lines = [f"{'PLATFORM_ID':<16} {'STATION':<12} {'TRACK':<10} {'START_KM':>10} {'END_KM':>10} {'LEN_M':>9} {'STOP_OFF_M':>10}  SOURCE ROWS"]
    for sp in result.spans:
        off = "" if sp.segment_hint_offset_m is None else f"{sp.segment_hint_offset_m:.3f}"
        lines.append(f"{sp.platform_id:<16} {sp.station_id:<12} {sp.track_id:<10} {sp.start_m / 1000:>10.6f} "
                     f"{sp.end_m / 1000:>10.6f} {sp.length_m:>9.3f} {off:>10}  {', '.join(sp.source_ids)}")
    return "\n".join(lines)


def migrate_workbooks(infra: Path, operations: Optional[Path] = None, out_dir: Optional[Path] = None,
                      in_place: bool = False, dry_run: bool = False) -> MigrationResult:
    wb = openpyxl.load_workbook(infra, read_only=True, data_only=True)
    if "Platforms" not in wb.sheetnames and "StoppingPoints" not in wb.sheetnames:
        raise MigrationError(f"'{infra.name}' has no legacy 'Platforms' / 'StoppingPoints' sheet — nothing to migrate.")
    result = migrate_rows(read_sheet(wb, "Platforms"), read_sheet(wb, "StoppingPoints"), read_sheet(wb, "TrackLinks"))
    wb.close()
    if dry_run:
        return result
    if in_place:
        dst_infra, dst_ops = infra, operations
    else:
        target = out_dir or (infra.parent / "migrated_v1.14")
        dst_infra = target / infra.name
        dst_ops = target / operations.name if operations else None
    write_infrastructure(infra, dst_infra, result)
    if operations and dst_ops:
        write_operations(operations, dst_ops, result.id_map)
    if not in_place:  # copy the untouched sibling workbooks so the folder is a complete project
        for sib in infra.parent.glob("*.xlsx"):
            if sib not in (infra, operations) and not (dst_infra.parent / sib.name).exists():
                shutil.copy2(sib, dst_infra.parent / sib.name)
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Migrate legacy Platforms + StoppingPoints to PlatformSpans (v1.14.0).")
    ap.add_argument("infrastructure", type=Path, help="Infrastructure workbook (.xlsx) with Platforms/StoppingPoints")
    ap.add_argument("--operations", type=Path, help="Operations workbook; StoppingPatterns.PLATFORM_ID is rewritten")
    ap.add_argument("--out-dir", type=Path, help="Output folder (default: <input folder>/migrated_v1.14)")
    ap.add_argument("--in-place", action="store_true", help="Overwrite the input workbooks")
    ap.add_argument("--dry-run", action="store_true", help="Only print the migration table")
    a = ap.parse_args(argv)
    try:
        res = migrate_workbooks(a.infrastructure, a.operations, a.out_dir, a.in_place, a.dry_run)
    except MigrationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(format_table(res))
    renamed = {k: v for k, v in res.id_map.items() if k != v}
    if renamed:
        print("\nStoppingPatterns PLATFORM_ID mapping (legacy -> new):")
        for k, v in renamed.items():
            print(f"  {k} -> {v}")
    for w in res.warnings:
        print(f"WARNING: {w}")
    if not a.dry_run:
        where = "in place" if a.in_place else str(a.out_dir or (a.infrastructure.parent / "migrated_v1.14"))
        print(f"\nWrote migrated workbook(s) {where}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
