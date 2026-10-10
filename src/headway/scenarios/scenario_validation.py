"""Validation engine for scenario definitions, overrides, and effective configurations.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-VAL-001 to P12-VAL-004: Validation scope (target existence, parameter paths, ranges,
  units, geometry continuity, signalling and TVS compatibility, direction validation),
  critical vs warning severity, and pre-simulation verification.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set

from headway.data.validation import Severity, ValidationFinding, ValidationReport
from headway.infrastructure.direction import RunningDirection
from headway.scenarios.effective_config import EffectiveConfiguration
from headway.scenarios.overrides import PRIMARY_ID_MAP, OverrideNavigator, get_nested_target
from headway.scenarios.scenario_models import ExplicitOverride, ScenarioDefinition


# Physical range boundaries for engineering parameters
PARAMETER_BOUNDS: Dict[str, Tuple[float, float]] = {
    "length_m": (0.1, 100_000.0),
    "max_speed_ms": (0.5, 120.0),
    "gradient_per_mille": (-120.0, 120.0),
    "curve_radius_m": (50.0, 50_000.0),
    "dwell_time_s": (0.0, 7200.0),
    "release_delay_s": (0.0, 600.0),
    "auth_processing_delay_s": (0.0, 300.0),
    "max_acceleration_ms2": (0.1, 4.0),
    "max_service_deceleration_ms2": (0.1, 4.0),
    "emergency_deceleration_ms2": (0.1, 5.0),
    "max_train_occupancy": (1.0, 1.0),
    "mass_empty_kg": (5_000.0, 10_000_000.0),
    "mass_loaded_kg": (5_000.0, 15_000_000.0),
    "power_w": (50_000.0, 50_000_000.0),
    "max_tractive_effort_n": (5_000.0, 2_000_000.0),
}


class ScenarioValidator:
    """Validates scenario definitions, atomic overrides, and generated effective projects."""

    @classmethod
    def validate_scenario(
        cls,
        scenario: ScenarioDefinition,
        baseline_project: Dict[str, Any],
    ) -> ValidationReport:
        """P12-VAL-001 & P12-VAL-002: Validate scenario metadata and explicit overrides."""
        report = ValidationReport(project_id=scenario.scenario_id)

        # 1. Validate scenario identity
        if not scenario.scenario_id.strip():
            report.add_finding(
                error_code="ERR_SCN_EMPTY_ID",
                severity=Severity.CRITICAL,
                message="Scenario identifier cannot be empty.",
                object_id=scenario.scenario_id,
            )

        # 2. Validate individual overrides
        for ovr in scenario.overrides:
            cls._validate_single_override(ovr, baseline_project, report)

        return report

    @classmethod
    def _validate_single_override(
        cls,
        override: ExplicitOverride,
        baseline_project: Dict[str, Any],
        report: ValidationReport,
    ) -> None:
        """Validate target domain, object existence, parameter path, and value boundaries."""
        domain = override.dataset_type.strip().lower()
        obj_id = override.object_id.strip()
        path = override.parameter_path.strip()

        # Check domain existence
        if domain not in baseline_project and domain not in ("global", "project", "root", "stochastic"):
            report.add_finding(
                error_code="ERR_SCN_INVALID_DOMAIN",
                severity=Severity.CRITICAL,
                message=f"Target dataset domain '{domain}' does not exist in project model.",
                object_id=override.override_id,
                recommendation="Target one of: infrastructure, signalling, rolling_stock, operations, analysis, stochastic.",
            )
            return

        # Special global target
        if obj_id in ("GLOBAL", "PROJECT", "ROOT"):
            return

        domain_data = baseline_project[domain]
        target_obj = OverrideNavigator._find_object_by_id(domain_data, obj_id)

        # Target object existence (P12-VAL-001)
        if target_obj is None:
            report.add_finding(
                error_code="ERR_SCN_TARGET_NOT_FOUND",
                severity=Severity.CRITICAL,
                message=f"Target object '{obj_id}' not found in domain '{domain}'.",
                object_id=override.override_id,
                recommendation=f"Ensure target object '{obj_id}' is defined in baseline or parent scenario.",
            )
            return

        # Parameter path navigation check
        segments = path.split(".")
        try:
            parent, key = get_nested_target(target_obj, segments)
            param_name = segments[-1]
            if isinstance(parent, dict) and key not in parent:
                raise KeyError(f"Attribute '{key}' not found on target object '{obj_id}'.")
            elif isinstance(parent, list):
                if not isinstance(key, int) or key < 0 or key >= len(parent):
                    raise KeyError(f"List index '{key}' out of range.")
        except KeyError as err:
            report.add_finding(
                error_code="ERR_SCN_INVALID_PARAM_PATH",
                severity=Severity.CRITICAL,
                message=f"Parameter path '{path}' does not exist on target '{obj_id}': {err}",
                object_id=override.override_id,
            )
            return

        # Range and physical boundary check
        val = override.new_value
        param_base_name = segments[-1]
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if not math.isfinite(val):
                report.add_finding(
                    error_code="ERR_SCN_NON_FINITE_VALUE",
                    severity=Severity.CRITICAL,
                    message=f"Override value for '{path}' must be a finite number (got non-finite {val}).",
                    object_id=override.override_id,
                )
            elif param_base_name in PARAMETER_BOUNDS:
                low, high = PARAMETER_BOUNDS[param_base_name]
                if val < low or val > high:
                    report.add_finding(
                        error_code="ERR_SCN_VALUE_OUT_OF_BOUNDS",
                        severity=Severity.CRITICAL,
                        message=f"Override value {val} for '{param_base_name}' is outside engineering bounds [{low}, {high}].",
                        object_id=override.override_id,
                    )

        # TVS Single Occupancy Rule Invariant (P12-VAL-001)
        if param_base_name == "max_train_occupancy" and val != 1:
            report.add_finding(
                error_code="ERR_SCN_TVS_OCCUPANCY_RULE",
                severity=Severity.CRITICAL,
                message=f"TVS section '{obj_id}' has max_train_occupancy = {val}; single-train occupancy invariant requires exactly 1.",
                object_id=override.override_id,
            )

    @classmethod
    def validate_effective_configuration(
        cls,
        eff_config: EffectiveConfiguration,
    ) -> ValidationReport:
        """P12-VAL-001 to P12-VAL-004: Validate overall network consistency of effective configuration."""
        report = ValidationReport(project_id=eff_config.scenario_id)
        proj = eff_config.project_dict
        infra = proj.get("infrastructure", {})

        # 1. Track link and node consistency
        nodes = infra.get("nodes", [])
        node_ids = {n.get("node_id") for n in nodes if isinstance(n, dict) and "node_id" in n}
        links = infra.get("track_links", [])
        link_map: Dict[str, Dict[str, Any]] = {}
        for l in links:
            lid = l.get("link_id")
            if lid:
                link_map[lid] = l
                # Verify positive length
                length = l.get("length_m", 0.0)
                if length <= 0.0 or not math.isfinite(length):
                    report.add_finding(
                        error_code="ERR_SCN_INVALID_LINK_LENGTH",
                        severity=Severity.CRITICAL,
                        message=f"Track link '{lid}' has non-positive or non-finite length {length} m.",
                        object_id=lid,
                    )
                sn = l.get("start_node_id")
                en = l.get("end_node_id")
                if sn and node_ids and sn not in node_ids:
                    report.add_finding(
                        error_code="ERR_SCN_UNDEFINED_NODE",
                        severity=Severity.CRITICAL,
                        message=f"Track link '{lid}' references undefined start_node_id '{sn}'.",
                        object_id=lid,
                    )
                if en and node_ids and en not in node_ids:
                    report.add_finding(
                        error_code="ERR_SCN_UNDEFINED_NODE",
                        severity=Severity.CRITICAL,
                        message=f"Track link '{lid}' references undefined end_node_id '{en}'.",
                        object_id=lid,
                    )

        # 2. Platform boundary consistency
        platforms = infra.get("platforms", [])
        for p in platforms:
            pid = p.get("platform_id")
            host_link_id = p.get("link_id")
            p_start = p.get("start_offset_m", 0.0)
            p_end = p.get("end_offset_m", 0.0)
            host_link = link_map.get(host_link_id)

            if not host_link:
                report.add_finding(
                    error_code="ERR_SCN_PLATFORM_ORPHAN",
                    severity=Severity.CRITICAL,
                    message=f"Platform '{pid}' references non-existent link '{host_link_id}'.",
                    object_id=pid,
                )
            else:
                link_len = host_link.get("length_m", 0.0)
                if p_start < 0.0 or p_end > link_len or p_start >= p_end:
                    report.add_finding(
                        error_code="ERR_SCN_PLATFORM_GEOMETRY_INVALID",
                        severity=Severity.CRITICAL,
                        message=f"Platform '{pid}' offsets [{p_start}, {p_end}] exceed host link length {link_len} m.",
                        object_id=pid,
                    )

        # 3. TVS Section validity
        tvs_sections = infra.get("tvs_sections", [])
        for tvs in tvs_sections:
            tvs_id = tvs.get("tvs_id")
            max_occ = tvs.get("max_train_occupancy", 1)
            if max_occ < 1:
                report.add_finding(
                    error_code="ERR_SCN_TVS_INVALID_OCCUPANCY",
                    severity=Severity.CRITICAL,
                    message=f"TVS section '{tvs_id}' capacity {max_occ} must be at least 1.",
                    object_id=tvs_id,
                )

        # 4. Route node continuity
        ops = proj.get("operations", {})
        routes = ops.get("routes", [])
        for r in routes:
            rid = r.get("route_id")
            traversals = r.get("traversals", [])
            for i in range(len(traversals) - 1):
                t1 = traversals[i]
                t2 = traversals[i + 1]
                t1_link = link_map.get(t1.get("link_id"))
                t2_link = link_map.get(t2.get("link_id"))
                if t1_link and t2_link:
                    t1_dir = t1.get("direction", "FORWARD")
                    t2_dir = t2.get("direction", "FORWARD")
                    exit_node = t1_link.get("end_node_id") if t1_dir == "FORWARD" else t1_link.get("start_node_id")
                    entry_node = t2_link.get("start_node_id") if t2_dir == "FORWARD" else t2_link.get("end_node_id")
                    if exit_node != entry_node:
                        report.add_finding(
                            error_code="ERR_SCN_ROUTE_DISCONTINUOUS",
                            severity=Severity.CRITICAL,
                            message=f"Route '{rid}' broken continuity between step {i} (exits {exit_node}) and step {i+1} (enters {entry_node}).",
                            object_id=rid,
                        )

        # Update effective configuration validity flag
        eff_config.is_valid = report.is_simulation_ready
        eff_config.validation_findings = [f.to_dict() for f in report.findings]
        return report
