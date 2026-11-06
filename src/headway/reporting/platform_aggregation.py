"""v1.14.0: aggregation of link-level platform segment records to user-facing platforms.

Platforms are entered as ``PlatformSpans`` (one row per physical platform) and segmented
by the importer into link-level ``<PLATFORM_ID>@s<N>`` segments. The simulation records
occupation per segment; reports show one row per parent platform.

Aggregation rule (per parent platform, segments in link order):
- Occupation is recorded only on the segment holding the platform's segment hint point
  (v1.11.1 rule: a platform reports occupation only if the assigned stop lies within it);
  every other segment is ``never_occupied`` (all components 0.0 s).
- Arrival Approach / Passenger Dwell / Departure Clearance of the platform are the
  component values of its occupied segment. Should several segments ever be occupied,
  each component is the maximum over the occupied segments (the platform track is one
  resource — the components describe the same train movement, so they are not summed).
- Total Occupation = Arrival Approach + Passenger Dwell + Departure Clearance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


def record_parent_id(r: Any) -> str:
    """User-facing platform ID of a record (parent for generated segments)."""
    return str(getattr(r, "parent_platform_id", None) or getattr(r, "platform_id", "") or "")


def record_components(r: Any) -> Tuple[float, float, float]:
    """(arrival approach, passenger dwell, departure clearance) of one record — the
    UIC 406 / P14-SEC06 3-component decomposition (unchanged from v1.9.0)."""
    arr_t = float(getattr(r, "arrival_time_s", 0.0))
    dep_t = float(getattr(r, "departure_time_s", arr_t))
    res_start_t = getattr(r, "reservation_start_s", None)
    fin_rel_t = getattr(r, "final_release_s", None)

    if res_start_t is not None:
        approach_s = max(0.0, arr_t - float(res_start_t))
    elif hasattr(r, "arrival_approach_s"):
        approach_s = float(r.arrival_approach_s)
    else:
        approach_s = 15.0

    dwell_s = max(0.0, dep_t - arr_t)
    if dwell_s == 0.0 and hasattr(r, "dwell_duration_s"):
        dwell_s = float(r.dwell_duration_s)

    if fin_rel_t is not None:
        clearance_s = max(0.0, float(fin_rel_t) - dep_t)
    elif hasattr(r, "departure_clearance_s"):
        clearance_s = float(r.departure_clearance_s)
    else:
        clr_t = float(getattr(r, "clearance_time_s", dep_t))
        clearance_s = max(0.0, clr_t - dep_t)
        if clearance_s == 0.0:
            clearance_s = float(getattr(r, "residual_rear_duration_s", 15.0))
    return approach_s, dwell_s, clearance_s


@dataclass
class PlatformAggregate:
    platform_id: str
    station_id: str
    station_name: str
    segment_ids: List[str] = field(default_factory=list)
    occupied_segment_ids: List[str] = field(default_factory=list)
    arrival_approach_s: float = 0.0
    passenger_dwell_s: float = 0.0
    departure_clearance_s: float = 0.0
    is_span: bool = False  # True when generated from a PlatformSpans row
    records: List[Any] = field(default_factory=list)

    @property
    def total_occupation_s(self) -> float:
        return round(self.arrival_approach_s + self.passenger_dwell_s + self.departure_clearance_s, 1)

    @property
    def segments_label(self) -> str:
        return ", ".join(self.segment_ids)


def aggregate_platform_records(records: Optional[Sequence[Any]]) -> List[PlatformAggregate]:
    """Group segment records by parent platform (ordered like the runner's records)."""
    groups: Dict[str, PlatformAggregate] = {}
    for r in records or []:
        pid = record_parent_id(r)
        agg = groups.get(pid)
        if agg is None:
            stn = str(getattr(r, "station_id", "") or "")
            agg = PlatformAggregate(
                platform_id=pid,
                station_id=stn,
                station_name=str(getattr(r, "station_name", "") or stn),
                is_span=bool(getattr(r, "parent_platform_id", None)),
            )
            groups[pid] = agg
        seg = str(getattr(r, "platform_id", "") or "")
        if seg not in agg.segment_ids:
            agg.segment_ids.append(seg)
        agg.records.append(r)
        if getattr(r, "never_occupied", False):
            continue
        a, d, c = record_components(r)
        if seg not in agg.occupied_segment_ids:
            agg.occupied_segment_ids.append(seg)
        agg.arrival_approach_s = max(agg.arrival_approach_s, a)
        agg.passenger_dwell_s = max(agg.passenger_dwell_s, d)
        agg.departure_clearance_s = max(agg.departure_clearance_s, c)
    # Row order = the runner's record order (arrival, dwell end, ID) evaluated per platform on
    # its occupied segment(s): never-occupied platforms (all 0.0 s) first, then by arrival.
    # Without this, a never-occupied @s1 segment (arrival 0) would pull its platform forward.
    return sorted(groups.values(), key=_platform_sort_key)


def _platform_sort_key(agg: PlatformAggregate) -> Tuple[float, float, str]:
    occ = [r for r in agg.records if not getattr(r, "never_occupied", False)]
    if not occ:
        return (0.0, 0.0, agg.platform_id)
    first = min(occ, key=lambda r: (float(getattr(r, "arrival_time_s", 0.0)), float(getattr(r, "dwell_end_time_s", 0.0))))
    return (float(getattr(first, "arrival_time_s", 0.0)), float(getattr(first, "dwell_end_time_s", 0.0)), agg.platform_id)


def segment_footnote(aggregates: Sequence[PlatformAggregate]) -> Optional[str]:
    """Footnote listing the auto-generated segment IDs of every span platform."""
    parts = []
    for agg in aggregates:
        if not agg.is_span:
            continue
        occ = f" (occupied: {', '.join(agg.occupied_segment_ids)})" if agg.occupied_segment_ids else ""
        parts.append(f"{agg.platform_id} = {', '.join(agg.segment_ids)}{occ}")
    if not parts:
        return None
    return (
        "Segments: platforms are aggregated from link-level segments auto-generated from PlatformSpans "
        "(<PLATFORM_ID>@s<N>, link order); occupation is recorded on the stop segment selected by SEGMENT_HINT_OFFSET_M. "
        + "; ".join(parts) + "."
    )


def build_platform_segment_provenance(infra: Any) -> List[Any]:
    """Section 11 provenance rows: one per platform segment, in PlatformSpans / link order."""
    from headway.data.platform_spans import stop_segment_map, track_chainage_frame
    from headway.reporting.result_models import PlatformSegmentProvenanceRecord

    if infra is None:
        return []
    platforms = list(getattr(infra, "platforms", None) or [])
    if not platforms:
        return []
    links = list(getattr(infra, "track_links", None) or [])
    link_track = {lk.link_id: lk.track_id for lk in links}
    stop_segs = set(stop_segment_map(platforms, list(getattr(infra, "stopping_points", None) or [])).values())
    frames: Dict[str, Dict[str, float]] = {}
    out = []
    for p in platforms:
        tid = link_track.get(p.link_id, "")
        if tid and tid not in frames:
            try:
                frames[tid] = {t.link_id: t.start_m for t in track_chainage_frame(links, tid)}
            except Exception:  # noqa: BLE001 - non-chain track (canonical-built projects): chainage unknown
                frames[tid] = {}
        l0 = frames.get(tid, {}).get(p.link_id)
        lo, hi = min(p.start_offset_m, p.end_offset_m), max(p.start_offset_m, p.end_offset_m)
        parent = getattr(p, "parent_platform_id", None)
        out.append(
            PlatformSegmentProvenanceRecord(
                segment_id=p.platform_id,
                parent_platform_id=parent,
                station_id=p.station_id,
                track_id=tid,
                link_id=p.link_id,
                start_offset_m=float(p.start_offset_m),
                end_offset_m=float(p.end_offset_m),
                track_start_chainage_km=None if l0 is None else round((l0 + lo) / 1000.0, 6),
                track_end_chainage_km=None if l0 is None else round((l0 + hi) / 1000.0, 6),
                is_stop_segment=p.platform_id in stop_segs,
                geometry_source="PLATFORM_SPAN_AUTO_SEGMENTATION" if parent else "PLATFORM_CANONICAL",
            )
        )
    return out
