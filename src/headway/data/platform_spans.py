"""v1.14.0 — station-level ``PlatformSpans`` and their auto-segmentation.

The Infrastructure workbook declares **one row per physical platform** (``PlatformSpans``)
by per-track chainage. The tool walks the track's ``TrackLinks`` and generates one internal,
link-level :class:`~headway.data.canonical.Platform` segment per overlapped link, plus one
internal :class:`~headway.data.canonical.StoppingPoint` at the platform's nominal stop point.

Chainage frame (v1.14.0 decision): **per track** — each track starts at 0 km at the start
node of its first link (the track's root node) and runs over its links in topological order;
the track's chainage coverage is ``[0, sum of its link lengths]``.

Segment IDs are deterministic and stable across versions: ``f"{PLATFORM_ID}@s{N}"`` with
``N`` 1-based in link order along the track. The generated stopping point ID is
``f"{PLATFORM_ID}@stop"``. Neither may be typed by users (``@`` is not a legal identifier
character); both are produced only here.

No backward compatibility: the legacy ``Platforms`` and ``StoppingPoints`` sheets are
rejected (``ERR_PLATFORMS_DEPRECATED`` / ``ERR_STOPPINGPOINTS_DEPRECATED``) — users migrate
with ``docs/migrate_platforms.py`` (see ``docs/MIGRATION_v1.14.0.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from headway.core.exceptions import DataValidationError

MIGRATION_GUIDE = "docs/MIGRATION_v1.14.0.md"
MIGRATION_GUIDE_URL = "https://github.com/ucwebchess/railway-headway-simulator/blob/main/docs/MIGRATION_v1.14.0.md"
MIGRATION_HELPER = "docs/migrate_platforms.py"

ERR_PLATFORM_SPAN_INVALID = "ERR_PLATFORM_SPAN_INVALID"
ERR_PLATFORM_SPAN_EXCEEDS_TRACK = "ERR_PLATFORM_SPAN_EXCEEDS_TRACK"
ERR_PLATFORM_SPAN_DUPLICATE = "ERR_PLATFORM_SPAN_DUPLICATE"
ERR_PLATFORMS_DEPRECATED = "ERR_PLATFORMS_DEPRECATED"
ERR_STOPPINGPOINTS_DEPRECATED = "ERR_STOPPINGPOINTS_DEPRECATED"
ERR_STOPPING_PATTERN_REFERENCES_SEGMENT = "ERR_STOPPING_PATTERN_REFERENCES_SEGMENT"
ERR_PLATFORM_NOMINAL_STOP_INVALID = "ERR_PLATFORM_NOMINAL_STOP_INVALID"

ALL_PLATFORM_SPAN_ERROR_CODES = (
    ERR_PLATFORM_SPAN_INVALID,
    ERR_PLATFORM_SPAN_EXCEEDS_TRACK,
    ERR_PLATFORM_SPAN_DUPLICATE,
    ERR_PLATFORMS_DEPRECATED,
    ERR_STOPPINGPOINTS_DEPRECATED,
    ERR_STOPPING_PATTERN_REFERENCES_SEGMENT,
    ERR_PLATFORM_NOMINAL_STOP_INVALID,
)

#: Legacy worksheet name -> rejection code (Infrastructure workbook).
DEPRECATED_INFRA_SHEETS: Dict[str, str] = {
    "Platforms": ERR_PLATFORMS_DEPRECATED,
    "StoppingPoints": ERR_STOPPINGPOINTS_DEPRECATED,
}

MIN_SPAN_LENGTH_M = 10.0
#: Numerical tolerance (m) for chainage comparisons (float round-off of km inputs).
CHAINAGE_TOL_M = 1e-6
#: Bounds tolerance (m) for track coverage and nominal-stop range checks — the dataset
#: validator's geometry tolerance (1 mm, ``headway.data.validator.GEOMETRY_TOLERANCE_M``).
#: Values within tolerance are clamped onto the boundary.
BOUNDS_TOL_M = 1e-3

SEGMENT_SEPARATOR = "@s"
STOP_SUFFIX = "@stop"
_SEGMENT_RE = re.compile(r"^(?P<parent>[A-Za-z0-9_][A-Za-z0-9_\-\.:]*)@s(?P<n>[1-9][0-9]*)$")
_STOP_RE = re.compile(r"^(?P<parent>[A-Za-z0-9_][A-Za-z0-9_\-\.:]*)@stop$")


class PlatformSpanError(DataValidationError):
    """A ``PlatformSpans`` / legacy-platform-schema violation (v1.14.0)."""

    DEFAULT_ERROR_CODE = ERR_PLATFORM_SPAN_INVALID


def _err(code: str, object_id: Optional[str], message: str, **ctx: Any) -> PlatformSpanError:
    oid = f"'{object_id}': " if object_id else ""
    return PlatformSpanError(
        f"{oid}{message} See {MIGRATION_GUIDE}.",
        error_code=code,
        context={"object_id": object_id, "migration_guide": MIGRATION_GUIDE, **ctx},
    )


def deprecated_sheet_message(sheet: str, workbook: str = "") -> str:
    """User-facing rejection text for a legacy Infrastructure sheet."""
    wb = f" in '{workbook}'" if workbook else ""
    if sheet == "Platforms":
        return (
            f"The legacy 'Platforms' worksheet{wb} is no longer supported (v1.14.0 breaking schema "
            f"change). Replace it with a 'PlatformSpans' sheet (one row per physical platform) — run "
            f"docs/migrate_platforms.py and follow {MIGRATION_GUIDE}."
        )
    return (
        f"The legacy 'StoppingPoints' worksheet{wb} is no longer supported (v1.14.0 breaking schema "
        f"change). Its offsets move to PlatformSpans.NOMINAL_STOP_OFFSET_M — run "
        f"docs/migrate_platforms.py and follow {MIGRATION_GUIDE}."
    )


def deprecated_sheet_error(sheet: str, workbook: str = "") -> PlatformSpanError:
    code = DEPRECATED_INFRA_SHEETS[sheet]
    return PlatformSpanError(
        deprecated_sheet_message(sheet, workbook),
        error_code=code,
        context={"worksheet": sheet, "workbook": workbook, "migration_guide": MIGRATION_GUIDE},
    )


# ---------------------------------------------------------------------------
# Identifier helpers
# ---------------------------------------------------------------------------

def segment_id(platform_id: str, n: int) -> str:
    """Deterministic, version-stable segment ID: ``<PLATFORM_ID>@s<N>`` (N is 1-based)."""
    if n < 1:
        raise ValueError("segment index is 1-based")
    return f"{platform_id}{SEGMENT_SEPARATOR}{n}"


def stopping_point_id(platform_id: str) -> str:
    return f"{platform_id}{STOP_SUFFIX}"


def is_segment_id(value: Any) -> bool:
    return isinstance(value, str) and _SEGMENT_RE.match(value.strip()) is not None


def is_generated_platform_id(value: str) -> bool:
    """True for tool-generated IDs (segment or stopping point)."""
    v = value.strip()
    return _SEGMENT_RE.match(v) is not None or _STOP_RE.match(v) is not None


def split_generated_id(value: str) -> Optional[Tuple[str, str]]:
    """``"PLT_A@s2" -> ("PLT_A", "@s2")``; ``None`` for non-generated IDs."""
    v = value.strip()
    m = _SEGMENT_RE.match(v)
    if m:
        return m.group("parent"), f"{SEGMENT_SEPARATOR}{m.group('n')}"
    m = _STOP_RE.match(v)
    if m:
        return m.group("parent"), STOP_SUFFIX
    return None


def parent_of(platform_id: str) -> str:
    """Parent platform ID of a segment ID (identity for any other ID)."""
    m = _SEGMENT_RE.match(str(platform_id).strip())
    return m.group("parent") if m else str(platform_id)


# ---------------------------------------------------------------------------
# Per-track chainage frame
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrackLinkSpan:
    """A TrackLink with its per-track chainage interval [start_m, end_m]."""

    link: Any
    start_m: float
    end_m: float

    @property
    def link_id(self) -> str:
        return _attr(self.link, "link_id")


def _attr(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name)


def track_chainage_frame(track_links: Sequence[Any], track_id: str) -> List[TrackLinkSpan]:
    """Order a track's links from its root node and assign per-track chainage (m).

    The track must be a simple chain (one root, no forks, no loops) — otherwise the
    per-track chainage is undefined and ``ERR_PLATFORM_SPAN_INVALID`` is raised.
    """
    links = [lnk for lnk in track_links if _attr(lnk, "track_id") == track_id]
    if not links:
        return []
    by_start: Dict[str, List[Any]] = {}
    ends = set()
    for lnk in links:
        by_start.setdefault(_attr(lnk, "start_node_id"), []).append(lnk)
        ends.add(_attr(lnk, "end_node_id"))
    roots = sorted(set(by_start) - ends)
    forks = sorted(n for n, ls in by_start.items() if len(ls) > 1)
    if len(roots) != 1 or forks:
        raise _err(
            ERR_PLATFORM_SPAN_INVALID, track_id,
            f"track is not a simple chain of TrackLinks (roots={roots or 'none'}, forks={forks or 'none'}); "
            "per-track chainage is undefined, so platform spans cannot be placed on it.",
            track_id=track_id,
        )
    ordered: List[TrackLinkSpan] = []
    node, pos, seen = roots[0], 0.0, set()
    while node in by_start:
        lnk = by_start[node][0]
        if _attr(lnk, "link_id") in seen:  # pragma: no cover - loops are excluded by roots/forks
            break
        seen.add(_attr(lnk, "link_id"))
        length = float(_attr(lnk, "length_m"))
        ordered.append(TrackLinkSpan(link=lnk, start_m=pos, end_m=pos + length))
        pos += length
        node = _attr(lnk, "end_node_id")
    if len(ordered) != len(links):
        missing = sorted({_attr(lk, "link_id") for lk in links} - seen)
        raise _err(
            ERR_PLATFORM_SPAN_INVALID, track_id,
            f"track links {missing} are not reachable from the track root '{roots[0]}'; per-track "
            "chainage is undefined.",
            track_id=track_id,
        )
    return ordered


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpanSegmentation:
    """Result of segmenting one platform span."""

    platform_id: str
    segments: List[Any]          # canonical Platform objects, in track order
    stopping_point: Any          # canonical StoppingPoint at the nominal stop
    stop_segment_id: str
    nominal_stop_offset_m: float
    nominal_stop_chainage_m: float


def validate_unique_platform_ids(platform_ids: Iterable[str]) -> None:
    seen: Dict[str, int] = {}
    for pid in platform_ids:
        seen[pid] = seen.get(pid, 0) + 1
    dups = sorted(p for p, n in seen.items() if n > 1)
    if dups:
        raise _err(ERR_PLATFORM_SPAN_DUPLICATE, dups[0],
                   f"PLATFORM_ID must be unique across the workbook; duplicated: {dups}.", duplicates=dups)


def segment_platform_span(span: Any, frame: List[TrackLinkSpan], station_ids: Optional[set] = None,
                          track_ids: Optional[set] = None) -> SpanSegmentation:
    """Generate link-level Platform segments and the nominal StoppingPoint for one span."""
    from headway.core.identifiers import normalize_identifier
    from headway.data.canonical import Platform, StoppingPoint

    pid_raw = _attr(span, "platform_id")
    if is_generated_platform_id(str(pid_raw or "")):
        raise _err(ERR_PLATFORM_SPAN_INVALID, str(pid_raw),
                   "PLATFORM_ID must be a plain identifier; '@s<N>' / '@stop' suffixes are reserved for "
                   "tool-generated segments.")
    pid = normalize_identifier(pid_raw, id_type="PLATFORM_ID")
    station_id = _attr(span, "station_id")
    track_id = _attr(span, "track_id")
    if station_ids is not None and station_id not in station_ids:
        raise _err(ERR_PLATFORM_SPAN_INVALID, pid, f"STATION_ID '{station_id}' does not exist in Stations.",
                   station_id=station_id)
    if track_ids is not None and track_id not in track_ids:
        raise _err(ERR_PLATFORM_SPAN_INVALID, pid, f"TRACK_ID '{track_id}' does not exist in Tracks.",
                   track_id=track_id)

    s_km, e_km = _attr(span, "start_chainage_km"), _attr(span, "end_chainage_km")
    if s_km is None or e_km is None:
        raise _err(ERR_PLATFORM_SPAN_INVALID, pid, "START_CHAINAGE_KM and END_CHAINAGE_KM are required.")
    s_m, e_m = float(s_km) * 1000.0, float(e_km) * 1000.0
    if not s_m < e_m:
        raise _err(ERR_PLATFORM_SPAN_INVALID, pid,
                   f"START_CHAINAGE_KM ({float(s_km)}) must be < END_CHAINAGE_KM ({float(e_km)}).")
    length_m = e_m - s_m
    if length_m < MIN_SPAN_LENGTH_M - CHAINAGE_TOL_M:
        raise _err(ERR_PLATFORM_SPAN_INVALID, pid,
                   f"platform span is {length_m:.3f} m long; the minimum is {MIN_SPAN_LENGTH_M:.0f} m.")
    if not frame:
        raise _err(ERR_PLATFORM_SPAN_EXCEEDS_TRACK, pid, f"track '{track_id}' has no TrackLinks.",
                   track_id=track_id)
    cov_start, cov_end = frame[0].start_m, frame[-1].end_m
    if s_m < cov_start - BOUNDS_TOL_M or e_m > cov_end + BOUNDS_TOL_M:
        raise _err(ERR_PLATFORM_SPAN_EXCEEDS_TRACK, pid,
                   f"span [{s_m / 1000:.6g}, {e_m / 1000:.6g}] km lies outside track '{track_id}' chainage "
                   f"coverage [{cov_start / 1000:.6g}, {cov_end / 1000:.6g}] km.",
                   track_id=track_id, coverage_km=(cov_start / 1000.0, cov_end / 1000.0))
    s_m, e_m = max(s_m, cov_start), min(e_m, cov_end)  # within-tolerance overshoot -> boundary
    length_m = e_m - s_m

    raw_off = _attr(span, "nominal_stop_offset_m")
    if raw_off is None or (isinstance(raw_off, str) and not raw_off.strip()):
        stop_off = length_m / 2.0
    else:
        stop_off = float(raw_off)
        if stop_off < -BOUNDS_TOL_M or stop_off > length_m + BOUNDS_TOL_M:
            raise _err(ERR_PLATFORM_NOMINAL_STOP_INVALID, pid,
                       f"NOMINAL_STOP_OFFSET_M ({stop_off}) must lie within the platform [0, {length_m:.3f}] m "
                       "measured from START_CHAINAGE_KM.", nominal_stop_offset_m=stop_off)
        stop_off = min(max(stop_off, 0.0), length_m)
    stop_m = s_m + stop_off

    segments: List[Any] = []
    stop_seg: Optional[Tuple[str, Any, float]] = None
    for tls in frame:
        lo, hi = max(s_m, tls.start_m), min(e_m, tls.end_m)
        if hi - lo <= CHAINAGE_TOL_M:
            continue  # no positive-length overlap with this link
        n = len(segments) + 1
        seg_id = segment_id(pid, n)
        link_len = tls.end_m - tls.start_m
        so = round(min(max(lo - tls.start_m, 0.0), link_len), 6)
        eo = round(min(max(hi - tls.start_m, 0.0), link_len), 6)
        segments.append(Platform(
            platform_id=seg_id,
            station_id=station_id,
            link_id=tls.link_id,
            start_offset_m=so,
            end_offset_m=eo,
            length_m=round(eo - so, 6),
            parent_platform_id=pid,
        ))
        # Nominal stop: the FIRST segment (track order) whose closed interval contains it —
        # on an internal link boundary this is the end of the earlier link.
        if stop_seg is None and lo - CHAINAGE_TOL_M <= stop_m <= hi + CHAINAGE_TOL_M:
            stop_seg = (seg_id, tls, round(min(max(stop_m - tls.start_m, 0.0), link_len), 6))
    if not segments or stop_seg is None:  # pragma: no cover - guarded by coverage + offset checks
        raise _err(ERR_PLATFORM_NOMINAL_STOP_INVALID, pid, "nominal stop point could not be resolved to a segment.")

    seg_id_stop, tls_stop, off_stop = stop_seg
    stp = StoppingPoint(
        stopping_point_id=stopping_point_id(pid),
        platform_id=seg_id_stop,
        link_id=tls_stop.link_id,
        offset_m=off_stop,
    )
    return SpanSegmentation(
        platform_id=pid,
        segments=segments,
        stopping_point=stp,
        stop_segment_id=seg_id_stop,
        nominal_stop_offset_m=stop_off,
        nominal_stop_chainage_m=stop_m,
    )


def segment_all_platform_spans(spans: Sequence[Any], tracks: Sequence[Any], track_links: Sequence[Any],
                               stations: Sequence[Any]) -> List[SpanSegmentation]:
    """Segment every span (deterministic: spans in input order, segments in track order)."""
    validate_unique_platform_ids(str(_attr(s, "platform_id")).strip() for s in spans)
    station_ids = {_attr(s, "station_id") for s in stations}
    track_ids = {_attr(t, "track_id") for t in tracks}
    frames: Dict[str, List[TrackLinkSpan]] = {}
    out = []
    for span in spans:
        tid = _attr(span, "track_id")
        if tid in track_ids and tid not in frames:
            frames[tid] = track_chainage_frame(track_links, tid)
        out.append(segment_platform_span(span, frames.get(tid, []), station_ids, track_ids))
    return out


def stop_segment_map(platforms: Sequence[Any], stopping_points: Sequence[Any]) -> Dict[str, str]:
    """``{parent PLATFORM_ID: stop segment ID}`` from generated platforms + stopping points."""
    seg_parent = {p.platform_id: p.parent_platform_id for p in platforms if getattr(p, "parent_platform_id", None)}
    out: Dict[str, str] = {}
    for sp in stopping_points:
        parent = seg_parent.get(sp.platform_id)
        if parent is not None:
            out[parent] = sp.platform_id
    return out


def check_stop_reference(platform_id: Any, *, service_pattern_id: Optional[str] = None) -> None:
    """StoppingPatterns must reference the user-facing PLATFORM_ID, never a segment ID."""
    if is_segment_id(platform_id):
        raise _err(
            ERR_STOPPING_PATTERN_REFERENCES_SEGMENT, str(platform_id).strip(),
            f"StoppingPatterns{f' ({service_pattern_id})' if service_pattern_id else ''} references the "
            f"generated platform segment '{str(platform_id).strip()}'; reference the platform "
            f"'{parent_of(str(platform_id))}' (PlatformSpans.PLATFORM_ID) instead.",
            service_pattern_id=service_pattern_id,
        )


def project_with_stop_segments(project: Any) -> Any:
    """Simulation view of a project: StoppingPatterns -> stop segments (v1.14.0).

    StoppingPatterns reference the user-facing ``PlatformSpans.PLATFORM_ID``; the simulation
    works on the generated link-level segments. Returns a shallow copy whose service-pattern
    stops reference the segment holding each platform's nominal stop point
    (``<PLATFORM_ID>@s<N>``). Projects without platform spans are returned unchanged; the
    input project is never mutated. Every simulation entry point that feeds stops and
    ``infrastructure.platforms`` to the engine must use this view (the UI pipeline applies it
    in ``SimulationRunner.run_simulation_pipeline``).
    """
    infra = getattr(project, "infrastructure", None)
    ops = getattr(project, "operations", None)
    if not infra or not ops or not getattr(infra, "platform_spans", None):
        return project
    seg_of = stop_segment_map(list(infra.platforms or []), list(infra.stopping_points or []))
    if not seg_of:
        return project
    changed = False
    patterns = []
    for sp in ops.service_patterns or []:
        stops = []
        for st in sp.stops or []:
            seg = seg_of.get(st.platform_id)
            if seg is not None and seg != st.platform_id:
                # model_copy(update=...) skips validators: StationStop refuses segment IDs
                # from user input (ERR_STOPPING_PATTERN_REFERENCES_SEGMENT) by design.
                stops.append(st.model_copy(update={"platform_id": seg}))
                changed = True
            else:
                stops.append(st)
        patterns.append(sp.model_copy(update={"stops": stops}))
    if not changed:
        return project
    return project.model_copy(update={"operations": ops.model_copy(update={"service_patterns": patterns})})
