"""Headway calculation, blocking-time analysis, TVS constraints, and capacity subsystem.

Milestone P08 — Blocking-Time Analysis & Technical Headway Solver (RHS-P08-001).
"""

from headway.analysis.blocking_time import (
    BlockingTimeComponent,
    BlockingTimeDecomposition,
    BlockingTimeline,
    ResourceBlockingInterval,
    decompose_blocking_interval,
    extract_blocking_intervals_from_records,
)
from headway.analysis.bottlenecks import (
    BottleneckClassification,
    classify_bottleneck,
    evaluate_slack_and_bottlenecks,
    rank_longest_occupations,
)
from headway.analysis.conflict_detection import (
    ConflictDetector,
    ConflictType,
    ResourceConflict,
)
from headway.analysis.headway_results import (
    HeadwayResult,
    HeadwayValidationStatus,
    MixedTrafficHeadwayMatrix,
    StairwayBlockData,
)
from headway.analysis.headway_search import (
    IterativeHeadwaySearch,
    SearchIterationStep,
    SearchResult,
)
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.analysis.mixed_traffic import MixedTrafficAnalyzer

__all__ = [
    # Blocking intervals & 7-component decomposition
    "BlockingTimeComponent",
    "BlockingTimeDecomposition",
    "ResourceBlockingInterval",
    "BlockingTimeline",
    "decompose_blocking_interval",
    "extract_blocking_intervals_from_records",
    # Conflict detection
    "ConflictType",
    "ResourceConflict",
    "ConflictDetector",
    # Bottleneck analysis & slack
    "BottleneckClassification",
    "classify_bottleneck",
    "evaluate_slack_and_bottlenecks",
    "rank_longest_occupations",
    # Results & Stairway
    "HeadwayValidationStatus",
    "StairwayBlockData",
    "HeadwayResult",
    "MixedTrafficHeadwayMatrix",
    # Solvers & Search
    "TechnicalHeadwaySolver",
    "IterativeHeadwaySearch",
    "SearchIterationStep",
    "SearchResult",
    "MixedTrafficAnalyzer",
]
