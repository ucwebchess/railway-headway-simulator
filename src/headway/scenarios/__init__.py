"""Scenario management, parameter override, and engineering comparisons subsystem.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- Scenario definitions, categories, and lifecycle management.
- Baseline immutability and isolated effective configuration generation.
- Explicit atomic overrides with dot-notation path navigation.
- Multi-level recursive inheritance and conflicting override detection.
- Deterministic SHA-256 configuration hashing and caching.
- Scenario validation with critical vs warning findings.
- Pre-configured engineering scenario templates.
- Simulation result association, run registry, and configuration hash matching.
- Multi-scenario comparative analytics (configuration diffs, metric deltas, bottleneck shift).
- Forward, reverse, and opposing-direction operational support.
"""

from headway.scenarios.effective_config import (
    EffectiveConfigGenerator,
    calculate_effective_hash,
)
from headway.scenarios.engine import apply_scenario_overrides
from headway.scenarios.overrides import (
    OverrideNavigator,
    cast_override_value,
    get_nested_target,
)
from headway.scenarios.result_association import (
    RunStatus,
    ScenarioResultRegistry,
    ScenarioRunRecord,
)
from headway.scenarios.scenario_comparison import (
    BottleneckShiftReport,
    MetricDifference,
    ParameterDifference,
    ScenarioComparisonEngine,
    ScenarioComparisonReport,
)
from headway.scenarios.scenario_manager import ScenarioManager
from headway.scenarios.scenario_models import (
    EffectiveConfiguration,
    ExplicitOverride,
    OverrideAction,
    ScenarioDefinition,
    ScenarioStatus,
    ScenarioType,
)
from headway.scenarios.scenario_validation import ScenarioValidator
from headway.scenarios.templates import ScenarioTemplateFactory

__all__ = [
    # Backward compatibility
    "apply_scenario_overrides",
    # P12 Core Models
    "ScenarioType",
    "ScenarioStatus",
    "OverrideAction",
    "ExplicitOverride",
    "ScenarioDefinition",
    "EffectiveConfiguration",
    # P12 Engines & Managers
    "OverrideNavigator",
    "cast_override_value",
    "get_nested_target",
    "EffectiveConfigGenerator",
    "calculate_effective_hash",
    "ScenarioValidator",
    "ScenarioTemplateFactory",
    "RunStatus",
    "ScenarioRunRecord",
    "ScenarioResultRegistry",
    "ParameterDifference",
    "MetricDifference",
    "BottleneckShiftReport",
    "ScenarioComparisonReport",
    "ScenarioComparisonEngine",
    "ScenarioManager",
]
