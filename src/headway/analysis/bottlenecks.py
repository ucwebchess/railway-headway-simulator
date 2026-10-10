"""Controlling bottleneck identification, classification, and conflict ranking.

Strictly satisfies RHS-P08-001:
- § 10: Slack Margins (P08-SLK-001 to P08-SLK-004).
- § 19: Controlling Bottleneck Identification (P08-BNK-001 to P08-BNK-006).
- § 20: Complete Conflict Ranking (descending order).
- § 22: Standalone Resource Longest Occupation Ranking.
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple

from headway.analysis.blocking_time import ResourceBlockingInterval
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.signalling.resource_types import ResourceCategory


class BottleneckClassification(str, Enum):
    """P08-BNK-003: Classification of bottleneck resources."""

    OPEN_LINE_BLOCK = "OPEN_LINE_BLOCK"
    STATION_APPROACH = "STATION_APPROACH"
    PLATFORM = "PLATFORM"
    RESIDUAL_REAR_OCCUPATION = "RESIDUAL_REAR_OCCUPATION"
    JUNCTION_MERGE = "JUNCTION_MERGE"
    JUNCTION_CROSSOVER = "JUNCTION_CROSSOVER"
    INTERLOCKING_ROUTE = "INTERLOCKING_ROUTE"
    MOVEMENT_AUTHORITY = "MOVEMENT_AUTHORITY"
    TVS_SECTION = "TVS_SECTION"
    SHARED_TVS_GROUP = "SHARED_TVS_GROUP"
    WHOLE_TUNNEL = "WHOLE_TUNNEL"
    OTHER_RESOURCE = "OTHER_RESOURCE"


def classify_bottleneck(conflict: ResourceConflict) -> BottleneckClassification:
    """Classify bottleneck resource according to conflict type, resource category, and topology."""
    c_type = conflict.conflict_type
    l_res = conflict.leader_usage

    if (
        c_type == ConflictType.RESIDUAL_REAR_CONFLICT
        or (l_res.decomposition and l_res.decomposition.residual_rear_time_s > 0)
    ):
        return BottleneckClassification.RESIDUAL_REAR_OCCUPATION

    if c_type == ConflictType.WHOLE_TUNNEL_CONFLICT:
        return BottleneckClassification.WHOLE_TUNNEL

    if c_type == ConflictType.SHARED_CONFLICT_GROUP:
        if l_res.resource_category in (ResourceCategory.TVS, ResourceCategory.TVS_SECTION):
            return BottleneckClassification.SHARED_TVS_GROUP
        return BottleneckClassification.INTERLOCKING_ROUTE

    if l_res.resource_category == ResourceCategory.PLATFORM:
        return BottleneckClassification.PLATFORM

    if l_res.resource_category in (ResourceCategory.TVS, ResourceCategory.TVS_SECTION):
        return BottleneckClassification.TVS_SECTION

    if l_res.resource_category in (ResourceCategory.INTERLOCKING_ROUTE, ResourceCategory.SWITCH):
        desc = (l_res.description or "").lower()
        if "merge" in desc or "converge" in desc:
            return BottleneckClassification.JUNCTION_MERGE
        if "crossover" in desc or "diamond" in desc:
            return BottleneckClassification.JUNCTION_CROSSOVER
        return BottleneckClassification.INTERLOCKING_ROUTE

    if l_res.resource_category == ResourceCategory.TRACK_BLOCK:
        desc = (l_res.description or "").lower()
        if "station" in desc or "approach" in desc or "throat" in desc:
            return BottleneckClassification.STATION_APPROACH
        return BottleneckClassification.OPEN_LINE_BLOCK

    return BottleneckClassification.OTHER_RESOURCE


def evaluate_slack_and_bottlenecks(
    conflicts: List[ResourceConflict],
    minimum_headway_s: float,
    tolerance_s: float = 0.1,
) -> Tuple[List[ResourceConflict], List[ResourceConflict]]:
    """P08-SLK-001 to 004 & P08-BNK-001 to 006:

    Calculates slack S_k = H_min - H_k for each conflict.
    Marks controlling bottlenecks (S_k <= tolerance).
    Returns (ranked_conflicts, controlling_conflicts).
    """
    ranked = sorted(conflicts, key=lambda c: c.required_headway_s, reverse=True)
    controlling: List[ResourceConflict] = []

    for c in ranked:
        slack = max(0.0, minimum_headway_s - c.required_headway_s)
        c.slack_s = round(slack, 6)
        c.is_controlling = slack <= tolerance_s
        c.bottleneck_type = classify_bottleneck(c).value
        if c.is_controlling:
            controlling.append(c)

    return ranked, controlling


def rank_longest_occupations(intervals: List[ResourceBlockingInterval]) -> List[ResourceBlockingInterval]:
    """P08-OCC-001 to 004: Rank standalone resource usages by duration T_blocking."""
    return sorted(intervals, key=lambda iv: iv.duration_s, reverse=True)
