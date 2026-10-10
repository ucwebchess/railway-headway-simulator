"""Scenario comparison engine, configuration parameter diffing, and metric delta calculations.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-CMP-001 to P12-CMP-008: Comparison scope, configuration differences, metric deltas (absolute and %),
  direction compatibility checking, bottleneck shift detection, and result association.
- P12-DIR-003: Forward vs reverse direction scenario comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from headway.infrastructure.direction import RunningDirection
from headway.scenarios.effective_config import EffectiveConfiguration
from headway.scenarios.result_association import ScenarioRunRecord


@dataclass
class ParameterDifference:
    """P12-CMP-002: Difference in a single configuration parameter across compared scenarios."""

    dataset_type: str
    object_id: str
    parameter_path: str
    values_by_scenario: Dict[str, Any]
    unit: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_type": self.dataset_type,
            "object_id": self.object_id,
            "parameter_path": self.parameter_path,
            "values_by_scenario": self.values_by_scenario,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass
class MetricDifference:
    """P12-CMP-003 & P12-CMP-006: Numerical metric comparison between a baseline and a scenario."""

    metric_name: str
    baseline_value: Optional[float]
    scenario_value: Optional[float]
    absolute_change: Optional[float]
    percentage_change: Optional[float]
    unit: str = ""
    direction_context: str = ""

    @property
    def is_improvement(self) -> Optional[bool]:
        """Determine if change represents an operational improvement."""
        if self.absolute_change is None:
            return None
        lower_is_better = any(term in self.metric_name.lower() for term in ("headway", "delay", "journey_time", "wait", "run_time"))
        higher_is_better = any(term in self.metric_name.lower() for term in ("capacity", "throughput", "reliability", "punctuality"))
        if lower_is_better:
            return self.absolute_change < 0
        if higher_is_better:
            return self.absolute_change > 0
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "baseline_value": self.baseline_value,
            "scenario_value": self.scenario_value,
            "absolute_change": self.absolute_change,
            "percentage_change": self.percentage_change,
            "unit": self.unit,
            "direction_context": self.direction_context,
        }


@dataclass
class BottleneckShiftReport:
    """P12-CMP-007: Diagnostics on whether the controlling bottleneck migrated."""

    baseline_scenario_id: str
    comparison_scenario_id: str
    baseline_bottleneck_id: str
    comparison_bottleneck_id: str
    bottleneck_migrated: bool
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_scenario_id": self.baseline_scenario_id,
            "comparison_scenario_id": self.comparison_scenario_id,
            "baseline_bottleneck_id": self.baseline_bottleneck_id,
            "comparison_bottleneck_id": self.comparison_bottleneck_id,
            "bottleneck_migrated": self.bottleneck_migrated,
            "description": self.description,
        }


@dataclass
class ScenarioComparisonReport:
    """P12-CMP-001 to P12-CMP-008: Comprehensive engineering comparison deliverable."""

    baseline_scenario_id: str
    compared_scenario_ids: List[str]
    parameter_differences: List[ParameterDifference] = field(default_factory=list)
    metric_differences: Dict[str, List[MetricDifference]] = field(default_factory=dict)
    bottleneck_shifts: List[BottleneckShiftReport] = field(default_factory=list)
    direction_compatibility_notes: List[str] = field(default_factory=list)
    summary_notes: List[str] = field(default_factory=list)

    @property
    def comparison_scenario_ids(self) -> List[str]:
        return list(self.compared_scenario_ids)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_scenario_id": self.baseline_scenario_id,
            "compared_scenario_ids": self.compared_scenario_ids,
            "parameter_differences": [p.to_dict() for p in self.parameter_differences],
            "metric_differences": {
                scn: [m.to_dict() for m in m_list]
                for scn, m_list in self.metric_differences.items()
            },
            "bottleneck_shifts": [b.to_dict() for b in self.bottleneck_shifts],
            "direction_compatibility_notes": self.direction_compatibility_notes,
            "summary_notes": self.summary_notes,
        }


class ScenarioComparisonEngine:
    """P12 Section 11: Compares configurations, simulation outputs, and bottlenecks."""

    @classmethod
    def compare_configurations(
        cls,
        scenarios_effective: Dict[str, EffectiveConfiguration],
    ) -> List[ParameterDifference]:
        """P12-CMP-002: Extract all parameter differences between effective configurations."""
        differences: List[ParameterDifference] = []
        scn_ids = list(scenarios_effective.keys())
        if len(scn_ids) < 2:
            return differences

        # Collect all applied overrides across all compared scenarios
        all_override_targets: Dict[Tuple[str, str, str], str] = {}
        for scn_id, eff in scenarios_effective.items():
            for ovr in eff.applied_overrides:
                key = (ovr.dataset_type.lower(), ovr.object_id, ovr.parameter_path)
                all_override_targets[key] = ovr.unit

        # Check values in each effective configuration for each target
        for (domain, obj_id, path), unit in sorted(all_override_targets.items()):
            val_map: Dict[str, Any] = {}
            for scn_id, eff in scenarios_effective.items():
                val = cls._lookup_value_in_dict(eff.project_dict, domain, obj_id, path)
                val_map[scn_id] = val

            # Check if there is any difference between scenarios
            distinct_values = set(str(v) for v in val_map.values())
            if len(distinct_values) > 1:
                differences.append(
                    ParameterDifference(
                        dataset_type=domain,
                        object_id=obj_id,
                        parameter_path=path,
                        values_by_scenario=val_map,
                        unit=unit,
                    )
                )

        return differences

    @classmethod
    def _lookup_value_in_dict(
        cls,
        project_dict: Dict[str, Any],
        domain: str,
        object_id: str,
        path: str,
    ) -> Any:
        """Helper to find current value in project_dict."""
        from headway.scenarios.overrides import OverrideNavigator, get_nested_target
        if object_id in ("GLOBAL", "PROJECT", "ROOT"):
            target_container = project_dict.get(domain, project_dict)
            try:
                parent, key = get_nested_target(target_container, path.split("."))
                return parent[key]
            except Exception:
                return None

        domain_data = project_dict.get(domain, {})
        target_obj = OverrideNavigator._find_object_by_id(domain_data, object_id)
        if target_obj is None:
            return None

        try:
            parent, key = get_nested_target(target_obj, path.split("."))
            return parent[key]
        except Exception:
            return None

    @classmethod
    def compare_metrics(
        cls,
        base_run: ScenarioRunRecord,
        alt_run: ScenarioRunRecord,
    ) -> List[MetricDifference]:
        """P12-CMP-003 & P12-CMP-006: Compute absolute and percentage changes between run metrics."""
        metric_diffs: List[MetricDifference] = []
        base_metrics = base_run.metrics
        alt_metrics = alt_run.metrics

        # Union of all metric keys
        all_keys = sorted(set(base_metrics.keys()) | set(alt_metrics.keys()))

        dir_context = f"{base_run.running_direction.value} vs {alt_run.running_direction.value}"

        for k in all_keys:
            val_a = base_metrics.get(k)
            val_b = alt_metrics.get(k)

            # If both are numeric, compute delta and percent change
            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                f_a = float(val_a)
                f_b = float(val_b)
                delta = f_b - f_a
                pct = ((f_b - f_a) / abs(f_a) * 100.0) if abs(f_a) > 1e-9 else None

                metric_diffs.append(
                    MetricDifference(
                        metric_name=k,
                        baseline_value=f_a,
                        scenario_value=f_b,
                        absolute_change=delta,
                        percentage_change=pct,
                        direction_context=dir_context,
                    )
                )

        return metric_diffs

    @classmethod
    def compare_scenarios(
        cls,
        baseline_scenario_id: str,
        compared_scenario_ids: Sequence[str],
        effective_configs: Dict[str, EffectiveConfiguration],
        runs_by_scenario: Dict[str, ScenarioRunRecord],
    ) -> ScenarioComparisonReport:
        """P12-CMP-001 to P12-CMP-008: Generate comprehensive multi-scenario comparison."""
        report = ScenarioComparisonReport(
            baseline_scenario_id=baseline_scenario_id,
            compared_scenario_ids=list(compared_scenario_ids),
        )

        # 1. Parameter differences
        all_eff = {s_id: effective_configs[s_id] for s_id in [baseline_scenario_id] + list(compared_scenario_ids) if s_id in effective_configs}
        report.parameter_differences = cls.compare_configurations(all_eff)

        # 2. Metric comparisons
        base_run = runs_by_scenario.get(baseline_scenario_id)
        if base_run:
            for s_id in compared_scenario_ids:
                alt_run = runs_by_scenario.get(s_id)
                if alt_run:
                    # Direction compatibility check (P12-CMP-004)
                    if base_run.running_direction != alt_run.running_direction:
                        report.direction_compatibility_notes.append(
                            f"Scenario '{s_id}' run in {alt_run.running_direction.value} direction while baseline '{baseline_scenario_id}' "
                            f"run in {base_run.running_direction.value}. Comparing directional performance."
                        )

                    diffs = cls.compare_metrics(base_run, alt_run)
                    report.metric_differences[s_id] = diffs

                    # Bottleneck shift check (P12-CMP-007)
                    base_bn = str(base_run.metrics.get("bottleneck_resource_id", "UNKNOWN"))
                    alt_bn = str(alt_run.metrics.get("bottleneck_resource_id", "UNKNOWN"))
                    migrated = base_bn != "UNKNOWN" and alt_bn != "UNKNOWN" and base_bn != alt_bn

                    report.bottleneck_shifts.append(
                        BottleneckShiftReport(
                            baseline_scenario_id=baseline_scenario_id,
                            comparison_scenario_id=s_id,
                            baseline_bottleneck_id=base_bn,
                            comparison_bottleneck_id=alt_bn,
                            bottleneck_migrated=migrated,
                            description=(
                                f"Bottleneck shifted from '{base_bn}' to '{alt_bn}'."
                                if migrated
                                else f"Bottleneck remained at '{base_bn}'."
                            ),
                        )
                    )

        report.summary_notes.append(
            f"Compared {len(compared_scenario_ids)} alternative scenarios against baseline '{baseline_scenario_id}'. "
            f"Found {len(report.parameter_differences)} distinct configuration differences."
        )
        return report
