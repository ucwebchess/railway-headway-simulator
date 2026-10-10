"""Theoretical and planning capacity calculation engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-HOM-001 to P10-HOM-005: Theoretical homogeneous capacity (C = 3600 / H)
- P10-PLN-001 to P10-PLN-006: Additive planning margin and utilization methods
- P10-MIX-001 to P10-MIX-006: Mixed-pattern repeated cycle capacity with wrap-around
- P10-DIR-001 to P10-DIR-004: Explicit FORWARD and REVERSE calculation
"""

import math
from typing import Dict, List, Optional, Tuple, Union

from headway.analysis.capacity_models import (
    CapacityResult,
    CapacityType,
    PlanningMarginMethod,
)
from headway.analysis.headway_results import HeadwayResult, MixedTrafficHeadwayMatrix
from headway.core.exceptions import OperationalSimulationError
from headway.infrastructure.direction import RunningDirection


class TheoreticalCapacityCalculator:
    """Calculates theoretical homogeneous, planning, and mixed-pattern railway capacity."""

    @staticmethod
    def calculate_homogeneous_capacity(
        headway_s: float,
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_HOMOGENEOUS",
        analysis_id: str = "AN_HOM_001",
    ) -> CapacityResult:
        """P10-HOM-001 to 005 & BENCH-P10-001: Ideal homogeneous theoretical capacity C = 3600 / H."""
        if not math.isfinite(headway_s):
            raise ValueError(f"Technical headway must be finite (got {headway_s}).")
        if headway_s <= 0.0:
            raise ValueError(f"Technical headway must be strictly positive (got {headway_s} s).")

        capacity_tph = 3600.0 / headway_s

        return CapacityResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.THEORETICAL_HOMOGENEOUS,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="CRITICAL_BLOCK_HEADWAY",
            capacity_trains_per_hour=capacity_tph,
            headway_s=headway_s,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=0.0,
            details={
                "formula": "C = 3600 / H",
                "interpretation": "Ideal theoretical capacity based on minimum technical headway; operational sustainability requires multi-train simulation verification.",
            },
        )

    @staticmethod
    def calculate_planning_capacity_additive(
        headway_s: float,
        planning_margin_s: float,
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_PLANNING_ADD",
        analysis_id: str = "AN_PLN_001",
    ) -> CapacityResult:
        """P10-PLN-001 to 003 & BENCH-P10-002: Planning capacity via additive margin H_plan = H + M."""
        if not math.isfinite(headway_s) or headway_s <= 0.0:
            raise ValueError(f"Technical headway must be positive and finite (got {headway_s} s).")
        if not math.isfinite(planning_margin_s) or planning_margin_s < 0.0:
            raise ValueError(f"Planning margin must be non-negative and finite (got {planning_margin_s} s).")

        planning_headway_s = headway_s + planning_margin_s
        capacity_tph = 3600.0 / planning_headway_s

        return CapacityResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.PLANNING_ADDITIVE_MARGIN,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="PLANNING_HEADWAY",
            capacity_trains_per_hour=capacity_tph,
            headway_s=planning_headway_s,
            planning_margin_method=PlanningMarginMethod.ADDITIVE_HEADWAY_MARGIN,
            planning_margin_value=planning_margin_s,
            details={
                "technical_headway_s": headway_s,
                "planning_margin_s": planning_margin_s,
                "planning_headway_s": planning_headway_s,
                "formula": "C_planning = 3600 / (H_technical + M)",
            },
        )

    @staticmethod
    def calculate_planning_capacity_utilization(
        theoretical_capacity_tph: float,
        target_utilization: float,
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_PLANNING_UTIL",
        analysis_id: str = "AN_PLN_002",
    ) -> CapacityResult:
        """P10-PLN-004 & BENCH-P10-003: Planning capacity via target utilization C_plan = U * C_theoretical."""
        if not math.isfinite(theoretical_capacity_tph) or theoretical_capacity_tph <= 0.0:
            raise ValueError(f"Theoretical capacity must be positive and finite (got {theoretical_capacity_tph} tph).")
        if not math.isfinite(target_utilization) or target_utilization <= 0.0 or target_utilization > 1.0:
            raise ValueError(f"Target utilization must be in range (0.0, 1.0] (got {target_utilization}).")

        planning_capacity_tph = target_utilization * theoretical_capacity_tph
        equivalent_headway_s = 3600.0 / planning_capacity_tph

        return CapacityResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.PLANNING_UTILIZATION,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="TARGET_UTILIZATION",
            capacity_trains_per_hour=planning_capacity_tph,
            headway_s=equivalent_headway_s,
            planning_margin_method=PlanningMarginMethod.TARGET_UTILIZATION,
            planning_margin_value=target_utilization,
            details={
                "theoretical_capacity_tph": theoretical_capacity_tph,
                "target_utilization": target_utilization,
                "formula": "C_planning = U * C_theoretical",
            },
        )

    @staticmethod
    def calculate_mixed_pattern_capacity(
        service_sequence: List[str],
        headway_matrix: Union[MixedTrafficHeadwayMatrix, Dict[Tuple[str, str], float]],
        direction: RunningDirection = RunningDirection.FORWARD,
        analysis_section: str = "DEFAULT_SECTION",
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_MIXED_PATTERN",
        analysis_id: str = "AN_MIX_001",
    ) -> CapacityResult:
        """P10-MIX-001 to 005 & BENCH-P10-004: Capacity for repeating service sequence with wrap-around pair.

        T_cycle = sum_{k=1}^{N-1} H(s_k, s_{k+1}) + H(s_N, s_1)
        C_pattern = (3600 * N) / T_cycle
        """
        if not service_sequence:
            raise ValueError("Service sequence cannot be empty.")
        if len(service_sequence) < 1:
            raise ValueError("Service sequence requires at least one service.")

        n = len(service_sequence)

        # Helper to lookup pairwise headway
        def get_headway(lead: str, foll: str) -> float:
            if isinstance(headway_matrix, MixedTrafficHeadwayMatrix):
                val = headway_matrix.get_headway(lead, foll)
                if val is None:
                    raise OperationalSimulationError(f"MixedTrafficHeadwayMatrix missing pair ({lead}, {foll}).")
                return val
            elif isinstance(headway_matrix, dict):
                val = headway_matrix.get((lead, foll))
                if val is None:
                    raise OperationalSimulationError(f"Headway matrix missing pair ({lead}, {foll}).")
                return val
            else:
                raise TypeError(f"Unsupported headway_matrix type: {type(headway_matrix)}.")

        pairwise_headways: List[Tuple[str, str, float]] = []
        cycle_time_s = 0.0

        for k in range(n):
            lead = service_sequence[k]
            foll = service_sequence[(k + 1) % n]  # wrap-around on last element (P10-MIX-004)
            h = get_headway(lead, foll)
            if not math.isfinite(h) or h <= 0.0:
                raise OperationalSimulationError(
                    f"Infeasible or non-positive headway {h} s between pair ('{lead}', '{foll}').",
                    context={"lead": lead, "foll": foll, "h": h},
                )
            pairwise_headways.append((lead, foll, h))
            cycle_time_s += h

        if cycle_time_s <= 0.0:
            raise OperationalSimulationError(f"Total cycle time must be strictly positive (got {cycle_time_s} s).")

        capacity_tph = (3600.0 * n) / cycle_time_s
        avg_headway_s = cycle_time_s / n

        return CapacityResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.THEORETICAL_MIXED_PATTERN,
            running_direction=direction,
            analysis_section=analysis_section,
            measurement_reference="REPEATED_PATTERN_CYCLE",
            capacity_trains_per_hour=capacity_tph,
            headway_s=avg_headway_s,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=0.0,
            details={
                "service_sequence": service_sequence,
                "train_count_in_cycle": n,
                "cycle_duration_s": cycle_time_s,
                "pairwise_headways": [{"lead": p[0], "foll": p[1], "h_s": p[2]} for p in pairwise_headways],
                "formula": "C_pattern = (3600 * N) / T_cycle",
            },
        )
