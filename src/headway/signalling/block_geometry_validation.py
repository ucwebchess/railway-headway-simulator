"""v1.11.2 — Pre-simulation block geometry validation (direction-symmetric).

This module is the single source of truth for

* the network **alignment frame** (absolute alignment chainage of every link start,
  orientation of every link relative to increasing chainage, chainage of every node);
* **exit-signal resolution** for a block (explicit → track-aware fallback →
  true terminal buffer stop → ``ERR_BLOCK_NO_EXIT_SIGNAL``);
* the **along-track path distance** between two points on the directed link graph
  (turnaround-aware: the span of a block that reverses through a loop is its path
  length, not its chainage delta);
* the three structural block checks that must hold before any simulation runs:

  ``ERR_BLOCK_NO_EXIT_SIGNAL``     a block whose exit cannot be resolved to a signal on
                                   the block's own track (or a genuine terminal);
  ``ERR_BLOCK_GEOMETRY_MISMATCH``  |entry→exit path distance − reported block length|
                                   > ``GEOMETRY_TOLERANCE_M``;
  ``ERR_BLOCK_OVERLAP``            two blocks claim the same metres of the same link.

Every check is a property of the *input model* and is evaluated before Pass 1, so its
outcome is identical for FORWARD and REVERSE runs by construction. Nothing is
auto-corrected: findings are collected, and the highest-priority code is raised with
every finding listed in the message and attached as ``.findings``.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from headway.core.exceptions import SignallingError
from headway.data.canonical import NodeType

ERR_BLOCK_NO_EXIT_SIGNAL = "ERR_BLOCK_NO_EXIT_SIGNAL"
ERR_BLOCK_GEOMETRY_MISMATCH = "ERR_BLOCK_GEOMETRY_MISMATCH"
ERR_BLOCK_OVERLAP = "ERR_BLOCK_OVERLAP"

#: Raise priority: an unresolvable exit makes the span undefined, so it outranks a
#: span mismatch; overlaps are reported last.
ERROR_PRIORITY: Tuple[str, ...] = (
    ERR_BLOCK_NO_EXIT_SIGNAL,
    ERR_BLOCK_GEOMETRY_MISMATCH,
    ERR_BLOCK_OVERLAP,
)

#: |span − reported length| above this is a geometry mismatch (brief: 1.0 m).
GEOMETRY_TOLERANCE_M: float = 1.0
#: Search radius for the track-aware exit-signal fallback (unchanged from v1.11.1).
EXIT_FALLBACK_TOLERANCE_KM: float = 0.5
#: Two blocks sharing more than this many metres of one link overlap.
OVERLAP_TOLERANCE_M: float = 1e-6

_NULL_IDS = ("", "NONE", "N/A", "NULL")

# Exit-boundary resolution sources (also published as provenance chainage sources).
EXIT_SRC_EXPLICIT = "EXPLICIT"
EXIT_SRC_FALLBACK_SAME_TRACK = "FALLBACK_SAME_TRACK"
EXIT_SRC_BUFFER_STOP_EDGE = "BUFFER_STOP_EDGE"


class BlockGeometryValidationError(SignallingError):
    """Raised when the block model is structurally inconsistent (v1.11.2).

    ``error_code`` is one of ``ERR_BLOCK_NO_EXIT_SIGNAL``, ``ERR_BLOCK_GEOMETRY_MISMATCH``
    or ``ERR_BLOCK_OVERLAP`` (highest priority present). ``findings`` holds *every*
    finding, including lower-priority ones.
    """

    DEFAULT_ERROR_CODE = ERR_BLOCK_GEOMETRY_MISMATCH

    def __init__(self, message: str, error_code: str, findings: Sequence["BlockGeometryFinding"]) -> None:
        super().__init__(
            message,
            error_code=error_code,
            context={"finding_count": len(findings), "codes": sorted({f.code for f in findings})},
        )
        self.findings: List[BlockGeometryFinding] = list(findings)


# ---------------------------------------------------------------------------
# Alignment frame
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AlignmentFrame:
    """Absolute alignment chainage of the network (shared by runner + validator)."""

    link_start_m: Dict[str, float]
    link_align_dir: Dict[str, float]
    node_pos_m: Dict[str, float]
    links: Dict[str, Any]
    next_links: Dict[str, List[Any]]

    def align_m(self, link_id: str, offset_m: float) -> float:
        """Absolute alignment chainage (m) of a point at ``offset_m`` along ``link_id``."""
        return self.link_start_m[link_id] + self.link_align_dir.get(link_id, 1.0) * float(offset_m)


def build_alignment_frame(track_links: Sequence[Any]) -> AlignmentFrame:
    """Breadth-first alignment chainage from the network root(s).

    Behaviour is identical to the v1.11.1 inline implementation in
    ``SimulationRunner.run_simulation_pipeline`` (moved here so that provenance,
    Section 10 coordinates and validation share one frame).
    """
    link_start_m: Dict[str, float] = {}
    next_links: Dict[str, List[Any]] = {}
    for lnk in track_links:
        next_links.setdefault(lnk.start_node_id, []).append(lnk)

    all_starts = {lnk.start_node_id for lnk in track_links}
    all_ends = {lnk.end_node_id for lnk in track_links}
    roots = all_starts - all_ends
    if not roots and track_links:
        roots = {track_links[0].start_node_id}

    node_pos_m: Dict[str, float] = {}
    for root in sorted(roots):
        node_pos_m.setdefault(root, 0.0)
        queue = [(root, 0.0)]
        while queue:
            curr_node, curr_m = queue.pop(0)
            for lnk in next_links.get(curr_node, []):
                if lnk.link_id not in link_start_m:
                    link_start_m[lnk.link_id] = curr_m
                    node_pos_m.setdefault(lnk.end_node_id, curr_m + lnk.length_m)
                    queue.append((lnk.end_node_id, curr_m + lnk.length_m))

    cum_m = 0.0
    for lnk in track_links:
        if lnk.link_id not in link_start_m:
            link_start_m[lnk.link_id] = cum_m
        cum_m = max(cum_m, link_start_m[lnk.link_id] + lnk.length_m)

    link_align_dir: Dict[str, float] = {}
    for lnk in track_links:
        s_pos = node_pos_m.get(lnk.start_node_id)
        e_pos = node_pos_m.get(lnk.end_node_id)
        reversed_link = (
            s_pos is not None
            and e_pos is not None
            and abs(link_start_m[lnk.link_id] - s_pos) < 1e-6
            and e_pos < s_pos - 1e-6
        )
        link_align_dir[lnk.link_id] = -1.0 if reversed_link else 1.0

    return AlignmentFrame(
        link_start_m=link_start_m,
        link_align_dir=link_align_dir,
        node_pos_m=node_pos_m,
        links={lnk.link_id: lnk for lnk in track_links},
        next_links=next_links,
    )


# ---------------------------------------------------------------------------
# Along-track path distance (directed link graph)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PathResult:
    distance_m: float
    link_ids: Tuple[str, ...]
    reversed_search: bool  # True when only the b→a direction had a path

    def is_turnaround(self, frame: AlignmentFrame) -> bool:
        """Path changes orientation relative to alignment chainage (reverses via a loop)."""
        dirs = {frame.link_align_dir.get(lid, 1.0) for lid in self.link_ids}
        return len(dirs) > 1


def _directed_path(frame: AlignmentFrame, a: Tuple[str, float], b: Tuple[str, float]) -> Optional[PathResult]:
    link_a, off_a = a
    link_b, off_b = b
    if link_a not in frame.links or link_b not in frame.links:
        return None
    if link_a == link_b and off_b >= off_a - 1e-9:
        return PathResult(round(off_b - off_a, 6), (link_a,), False)

    la = frame.links[link_a]
    start_cost = float(la.length_m) - float(off_a)
    # Dijkstra over links; cost(link) = metres travelled to reach that link's START node.
    best: Dict[str, float] = {}
    heap: List[Tuple[float, str, Tuple[str, ...]]] = [(start_cost, la.end_node_id, (link_a,))]
    while heap:
        cost, node, trail = heapq.heappop(heap)
        if best.get(node, float("inf")) <= cost - 1e-9:
            continue
        best[node] = cost
        for nxt in frame.next_links.get(node, []):
            if nxt.link_id == link_b:
                return PathResult(round(cost + float(off_b), 6), trail + (link_b,), False)
            if nxt.link_id in trail:
                continue
            heapq.heappush(heap, (cost + float(nxt.length_m), nxt.end_node_id, trail + (nxt.link_id,)))
    return None


def along_track_distance(frame: AlignmentFrame, a: Tuple[str, float], b: Tuple[str, float]) -> Optional[PathResult]:
    """Shortest directed along-track distance a→b; falls back to b→a for blocks whose
    signals are stationed against the link direction. ``None`` if neither exists."""
    fwd = _directed_path(frame, a, b)
    if fwd is not None:
        return fwd
    rev = _directed_path(frame, b, a)
    if rev is not None:
        return PathResult(rev.distance_m, tuple(reversed(rev.link_ids)), True)
    return None


# ---------------------------------------------------------------------------
# Findings / boundaries
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlockGeometryFinding:
    code: str
    block_id: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExitBoundary:
    """Resolved exit boundary of a block."""

    boundary_id: str               # signal id, or node id for BUFFER_STOP_EDGE
    source: str                    # EXIT_SRC_*
    link_id: str
    offset_m: float
    alignment_km: Optional[float]


@dataclass
class BlockGeometryReport:
    findings: List[BlockGeometryFinding] = field(default_factory=list)
    exit_boundaries: Dict[str, ExitBoundary] = field(default_factory=dict)
    spans: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.findings

    def codes(self) -> List[str]:
        return sorted({f.code for f in self.findings}, key=ERROR_PRIORITY.index)

    def raise_if_findings(self) -> None:
        if not self.findings:
            return
        top = self.codes()[0]
        lines = [f"  [{f.code}] {f.message}" for f in sorted(
            self.findings, key=lambda f: (ERROR_PRIORITY.index(f.code), f.block_id)
        )]
        message = (
            f"{top}: block geometry validation failed with {len(self.findings)} finding(s); "
            "no simulation was run and nothing was auto-corrected:\n" + "\n".join(lines)
        )
        raise BlockGeometryValidationError(message, error_code=top, findings=self.findings)


def _clean_id(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    sid = str(raw).strip()
    return None if sid.upper() in _NULL_IDS else sid


def block_length_m(block: Any) -> float:
    """Reported block length = Σ |interval length| (the value Section 5 publishes)."""
    return float(sum(abs(float(iv.end_offset_m) - float(iv.start_offset_m)) for iv in (block.link_intervals or [])))


def _block_tracks(block: Any, frame: AlignmentFrame) -> set:
    return {
        getattr(frame.links[iv.link_id], "track_id", None)
        for iv in (block.link_intervals or [])
        if iv.link_id in frame.links
    }


def _signal_alignment_km(sig: Any, frame: AlignmentFrame) -> Optional[float]:
    if getattr(sig, "chainage_km", None) is not None:
        return float(sig.chainage_km)
    if getattr(sig, "chainage_m", None) is not None:
        return float(sig.chainage_m) / 1000.0
    if getattr(sig, "link_id", None) in frame.link_start_m:
        return frame.align_m(sig.link_id, float(sig.offset_m)) / 1000.0
    return None


def resolve_exit_boundary(
    block: Any,
    signals_by_id: Dict[str, Any],
    frame: AlignmentFrame,
    nodes_by_id: Dict[str, Any],
) -> Tuple[Optional[ExitBoundary], Optional[BlockGeometryFinding]]:
    """Track-aware exit resolution (v1.11.2 / Task 2).

    1. explicit ``exit_signal_id`` that exists → used as-is (any track: an explicit
       exit is an engineering statement, e.g. a turnaround block);
       explicit id that does not exist → ``ERR_BLOCK_NO_EXIT_SIGNAL``;
    2. otherwise the nearest signal **on one of the block's own tracks** within
       ``EXIT_FALLBACK_TOLERANCE_KM`` of the block's exit end, excluding the block's
       own entry signal;
    3. otherwise, if the exit end is a genuine terminal (node typed ENDPOINT /
       BUFFER_STOP **with no onward link**) → ``BUFFER_STOP_EDGE``;
    4. otherwise → ``ERR_BLOCK_NO_EXIT_SIGNAL`` (never a signal from another track).
    """
    bid = block.block_id
    ivs = list(block.link_intervals or [])
    if not ivs or ivs[-1].link_id not in frame.links:
        return None, BlockGeometryFinding(
            ERR_BLOCK_NO_EXIT_SIGNAL, bid,
            f"block '{bid}': exit end cannot be located (no link intervals on the network).",
        )
    last = ivs[-1]
    exit_link = frame.links[last.link_id]
    exit_off = float(last.end_offset_m)
    exit_km = frame.align_m(last.link_id, exit_off) / 1000.0

    raw_exit = _clean_id(getattr(block, "exit_signal_id", None))
    if raw_exit is not None:
        sig = signals_by_id.get(raw_exit)
        if sig is None or getattr(sig, "link_id", None) not in frame.links:
            return None, BlockGeometryFinding(
                ERR_BLOCK_NO_EXIT_SIGNAL, bid,
                f"block '{bid}': explicit exit signal '{raw_exit}' does not exist on the network.",
                {"explicit_exit_signal_id": raw_exit},
            )
        return ExitBoundary(raw_exit, EXIT_SRC_EXPLICIT, sig.link_id, float(sig.offset_m),
                            _signal_alignment_km(sig, frame)), None

    entry_id = _clean_id(getattr(block, "entry_signal_id", None))
    tracks = _block_tracks(block, frame)
    candidates: List[Tuple[float, str, Any, float]] = []
    for sid, sig in signals_by_id.items():
        if sid == entry_id or getattr(sig, "link_id", None) not in frame.links:
            continue
        if getattr(frame.links[sig.link_id], "track_id", None) not in tracks:
            continue
        s_km = _signal_alignment_km(sig, frame)
        if s_km is None:
            continue
        dist = abs(s_km - exit_km)
        if dist <= EXIT_FALLBACK_TOLERANCE_KM + 1e-9:
            candidates.append((dist, sid, sig, s_km))
    if candidates:
        _, sid, sig, s_km = min(candidates, key=lambda c: (c[0], c[1]))
        return ExitBoundary(sid, EXIT_SRC_FALLBACK_SAME_TRACK, sig.link_id, float(sig.offset_m), s_km), None

    end_node_id = exit_link.end_node_id if exit_off >= float(exit_link.length_m) - 1e-6 else None
    end_node = nodes_by_id.get(end_node_id) if end_node_id else None
    is_terminal = (
        end_node is not None
        and getattr(end_node, "node_type", None) in (NodeType.ENDPOINT, NodeType.BUFFER_STOP)
        and not frame.next_links.get(end_node_id)
    )
    if is_terminal:
        return ExitBoundary(end_node_id, EXIT_SRC_BUFFER_STOP_EDGE, last.link_id, exit_off, round(exit_km, 6)), None

    onward = [l.link_id for l in frame.next_links.get(end_node_id or "", [])]
    return None, BlockGeometryFinding(
        ERR_BLOCK_NO_EXIT_SIGNAL, bid,
        f"block '{bid}': no exit signal on track(s) {sorted(t for t in tracks if t)} within "
        f"{EXIT_FALLBACK_TOLERANCE_KM} km of its exit end ({last.link_id}@{exit_off:.1f} m, "
        f"alignment {exit_km:.3f} km), and the exit end is not a terminal buffer stop"
        + (f" (node '{end_node_id}' continues onto {onward})" if end_node_id else "")
        + ". Signals on other tracks are never used as a fallback.",
        {"exit_end_link_id": last.link_id, "exit_end_offset_m": exit_off,
         "exit_end_alignment_km": round(exit_km, 6), "block_tracks": sorted(t for t in tracks if t)},
    )


def _overlap_findings(blocks: Sequence[Any]) -> List[BlockGeometryFinding]:
    """``ERR_BLOCK_OVERLAP`` — two blocks claiming the same metres of the same link.

    Evaluated on physical link intervals, so it is independent of traversal direction:
    in FORWARD it is "block N's exit lies beyond block N+1's entry", in REVERSE the
    mirror image — the shared metres are the same either way.
    """
    per_link: Dict[str, List[Tuple[float, float, str]]] = {}
    for blk in blocks:
        for iv in (blk.link_intervals or []):
            lo, hi = sorted((float(iv.start_offset_m), float(iv.end_offset_m)))
            per_link.setdefault(iv.link_id, []).append((lo, hi, blk.block_id))

    acc: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for link_id, spans in per_link.items():
        for i in range(len(spans)):
            for j in range(i + 1, len(spans)):
                a, b = spans[i], spans[j]
                if a[2] == b[2]:
                    continue
                ov = min(a[1], b[1]) - max(a[0], b[0])
                if ov > OVERLAP_TOLERANCE_M:
                    key = tuple(sorted((a[2], b[2])))
                    rec = acc.setdefault(key, {"overlap_m": 0.0, "links": []})
                    rec["overlap_m"] += ov
                    rec["links"].append(f"{link_id}[{max(a[0], b[0]):.1f}–{min(a[1], b[1]):.1f} m]")
    out = []
    for (b1, b2), rec in sorted(acc.items()):
        out.append(BlockGeometryFinding(
            ERR_BLOCK_OVERLAP, b1,
            f"blocks '{b1}' and '{b2}' overlap by {rec['overlap_m']:.1f} m on {', '.join(rec['links'])}.",
            {"block_ids": [b1, b2], "overlap_m": round(rec["overlap_m"], 3), "links": rec["links"]},
        ))
    return out


def validate_block_geometry(project: Any) -> BlockGeometryReport:
    """Collect every structural block finding for ``project`` (never raises)."""
    infra = project.infrastructure
    sig = project.signalling
    track_links = list(infra.track_links or [])
    blocks = list(getattr(sig, "blocks", None) or [])
    frame = build_alignment_frame(track_links)
    signals_by_id = {s.signal_id: s for s in (getattr(sig, "signals", None) or [])}
    nodes_by_id = {n.node_id: n for n in (getattr(infra, "nodes", None) or [])}

    report = BlockGeometryReport()
    for blk in blocks:
        bid = blk.block_id
        ivs = list(blk.link_intervals or [])
        if not ivs:
            continue
        exit_b, finding = resolve_exit_boundary(blk, signals_by_id, frame, nodes_by_id)
        if finding is not None:
            report.findings.append(finding)
            continue
        report.exit_boundaries[bid] = exit_b

        # Entry point: explicit entry signal if it exists, else the block's own entry end.
        entry_id = _clean_id(getattr(blk, "entry_signal_id", None))
        entry_sig = signals_by_id.get(entry_id) if entry_id else None
        if entry_sig is not None and getattr(entry_sig, "link_id", None) in frame.links:
            entry_pt = (entry_sig.link_id, float(entry_sig.offset_m))
            entry_src = "ENTRY_SIGNAL"
        else:
            entry_pt = (ivs[0].link_id, float(ivs[0].start_offset_m))
            entry_src = "BLOCK_ENTRY_END"
        exit_pt = (exit_b.link_id, exit_b.offset_m)

        length = block_length_m(blk)
        path = along_track_distance(frame, entry_pt, exit_pt)
        chain_delta = None
        if entry_pt[0] in frame.link_start_m and exit_pt[0] in frame.link_start_m:
            chain_delta = abs(frame.align_m(*exit_pt) - frame.align_m(*entry_pt))
        span_rec = {
            "length_m": round(length, 3),
            "path_span_m": round(path.distance_m, 3) if path else None,
            "chainage_delta_m": round(chain_delta, 3) if chain_delta is not None else None,
            "turnaround": bool(path and path.is_turnaround(frame)),
            "path_links": list(path.link_ids) if path else [],
            "entry_point": entry_pt, "entry_source": entry_src,
            "exit_point": exit_pt, "exit_boundary": exit_b.boundary_id, "exit_source": exit_b.source,
        }
        report.spans[bid] = span_rec

        if path is None:
            report.findings.append(BlockGeometryFinding(
                ERR_BLOCK_GEOMETRY_MISMATCH, bid,
                f"block '{bid}': no along-track path between entry {entry_pt} and exit "
                f"'{exit_b.boundary_id}' {exit_pt}; reported length {length:.1f} m cannot be verified.",
                dict(span_rec),
            ))
            continue
        diff = path.distance_m - length
        if abs(diff) > GEOMETRY_TOLERANCE_M:
            chain_txt = (
                f", alignment-chainage delta {chain_delta:.1f} m" if chain_delta is not None else ""
            )
            report.findings.append(BlockGeometryFinding(
                ERR_BLOCK_GEOMETRY_MISMATCH, bid,
                f"block '{bid}': reported length {length:.1f} m, entry→exit span "
                f"{path.distance_m:.1f} m (along-track path{chain_txt}), difference {diff:+.1f} m "
                f"(tolerance {GEOMETRY_TOLERANCE_M:.1f} m).",
                {**span_rec, "difference_m": round(diff, 3)},
            ))

    report.findings.extend(_overlap_findings(blocks))
    return report


def enforce_block_geometry(project: Any) -> BlockGeometryReport:
    """Validate and raise ``BlockGeometryValidationError`` on any finding."""
    report = validate_block_geometry(project)
    report.raise_if_findings()
    return report
