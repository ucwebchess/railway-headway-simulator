"""Bottleneck identification and migration tracking engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-BOT-001: Multi-criteria bottleneck identification (headway, utilization, delay)
- P10-BOT-002: Bottleneck migration tracking across scenario modifications
- Diminishing returns quantification and diagnostic commentary
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

from headway.analysis.capacity_models import (
    BottleneckCategory,
    BottleneckDiagnostic,
    BottleneckMigrationRecord,
    ResourceUtilizationMetric,
)


class BottleneckAnalyzer:
    """Identifies primary bottlenecks and tracks bottleneck migration across sensitivity variants."""

    @staticmethod
    def identify_bottlenecks_from_headways(
        block_headways: Dict[str, float],
        resource_categories: Optional[Dict[str, BottleneckCategory]] = None,
        resource_utilizations: Optional[Dict[str, ResourceUtilizationMetric]] = None,
        accumulated_delays: Optional[Dict[str, float]] = None,
    ) -> List[BottleneckDiagnostic]:
        """Rank and diagnose bottlenecks based on block headways and optional utilization/delay."""
        if not block_headways:
            return []

        # Sort by headway descending (largest headway = tightest bottleneck)
        sorted_by_headway = sorted(block_headways.items(), key=lambda kv: kv[1], reverse=True)

        diagnostics: List[BottleneckDiagnostic] = []
        for rank, (res_id, h_s) in enumerate(sorted_by_headway, start=1):
            category = BottleneckCategory.SIGNALLING_BLOCK
            if resource_categories and res_id in resource_categories:
                category = resource_categories[res_id]
            elif "PLATFORM" in res_id.upper() or "STN" in res_id.upper():
                category = BottleneckCategory.STATION_PLATFORM
            elif "TVS" in res_id.upper() or "TUNNEL" in res_id.upper():
                category = BottleneckCategory.TVS_RESTRICTION
            elif "JUNC" in res_id.upper() or "SW" in res_id.upper():
                category = BottleneckCategory.JUNCTION_CONFLICT

            util_pct = 0.0
            if resource_utilizations and res_id in resource_utilizations:
                util_pct = resource_utilizations[res_id].blocking_utilization_percent

            acc_delay = 0.0
            if accumulated_delays and res_id in accumulated_delays:
                acc_delay = accumulated_delays[res_id]

            explanation = (
                f"Rank {rank} bottleneck: resource '{res_id}' enforces a minimum headway of {h_s:.1f} s "
                f"({3600.0/h_s:.1f} trains/h max theoretical capacity). "
            )
            if util_pct > 0.0:
                explanation += f"Blocking utilization is {util_pct:.1f}%. "
            if acc_delay > 0.0:
                explanation += f"Accumulated train delay is {acc_delay:.1f} s."

            mitigation = None
            if category == BottleneckCategory.SIGNALLING_BLOCK:
                mitigation = "Subdivide block into shorter sections or upgrade signalling to ETCS L2 / CBTC."
            elif category == BottleneckCategory.STATION_PLATFORM:
                mitigation = "Add a parallel platform track or optimize passenger dwell time."
            elif category == BottleneckCategory.TVS_RESTRICTION:
                mitigation = "Optimize tunnel ventilation section length or reduce evacuation release timer."
            elif category == BottleneckCategory.JUNCTION_CONFLICT:
                mitigation = "Grade-separate junction or optimize route reservation timings."

            diagnostics.append(
                BottleneckDiagnostic(
                    resource_id=res_id,
                    category=category,
                    limiting_headway_s=h_s,
                    blocking_utilization_percent=util_pct,
                    accumulated_delay_s=acc_delay,
                    rank=rank,
                    diagnostic_explanation=explanation,
                    recommended_mitigation=mitigation,
                )
            )

        return diagnostics

    @staticmethod
    def track_migration(
        baseline_scenario_id: str,
        modified_scenario_id: str,
        parameter_modified: str,
        baseline_bottleneck: BottleneckDiagnostic,
        modified_bottleneck: BottleneckDiagnostic,
        baseline_capacity_tph: float,
        modified_capacity_tph: float,
        theoretical_unconstrained_gain_tph: Optional[float] = None,
    ) -> BottleneckMigrationRecord:
        """P10-BOT-002: Track bottleneck migration and evaluate diminishing returns."""
        if baseline_capacity_tph <= 0.0:
            raise ValueError(f"Baseline capacity must be strictly positive (got {baseline_capacity_tph}).")

        migrated = baseline_bottleneck.resource_id != modified_bottleneck.resource_id
        delta_cap = modified_capacity_tph - baseline_capacity_tph
        pct_gain = (delta_cap / baseline_capacity_tph) * 100.0

        # Diminishing returns ratio: actual gain vs ideal unconstrained gain
        diminishing_ratio = 1.0
        if theoretical_unconstrained_gain_tph is not None and theoretical_unconstrained_gain_tph > 0.0:
            diminishing_ratio = delta_cap / theoretical_unconstrained_gain_tph

        if migrated:
            commentary = (
                f"Bottleneck migrated from '{baseline_bottleneck.resource_id}' ({baseline_bottleneck.category.value}) "
                f"to '{modified_bottleneck.resource_id}' ({modified_bottleneck.category.value}) following modification "
                f"of '{parameter_modified}'. Capacity increased by {delta_cap:+.2f} trains/h ({pct_gain:+.1f}%). "
            )
            if diminishing_ratio < 0.95:
                commentary += (
                    f"Observed diminishing returns (ratio {diminishing_ratio:.2f}); secondary bottleneck "
                    f"'{modified_bottleneck.resource_id}' now constrains further throughput gains."
                )
            else:
                commentary += "Gains scaled effectively with minimal secondary bottleneck dampening."
        else:
            commentary = (
                f"Bottleneck remained at '{baseline_bottleneck.resource_id}' after modifying '{parameter_modified}'. "
                f"Capacity changed by {delta_cap:+.2f} trains/h ({pct_gain:+.1f}%)."
            )

        return BottleneckMigrationRecord(
            baseline_scenario_id=baseline_scenario_id,
            modified_scenario_id=modified_scenario_id,
            parameter_modified=parameter_modified,
            baseline_bottleneck_id=baseline_bottleneck.resource_id,
            modified_bottleneck_id=modified_bottleneck.resource_id,
            bottleneck_migrated=migrated,
            baseline_capacity_tph=baseline_capacity_tph,
            modified_capacity_tph=modified_capacity_tph,
            delta_capacity_tph=delta_cap,
            percentage_gain=pct_gain,
            diminishing_returns_ratio=diminishing_ratio,
            diagnostic_commentary=commentary,
        )
