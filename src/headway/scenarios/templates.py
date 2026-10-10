"""Pre-configured scenario templates for standard railway engineering studies.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-TYPE-001: Template support for standard scenario categories:
  * BASELINE
  * SIGNALLING_COMPARISON
  * BLOCK_SENSITIVITY
  * MIXED_TRAFFIC
  * STATION_OPTIMIZATION
  * TVS_PER_TRACK, TVS_SHARED, WHOLE_TUNNEL
  * STOCHASTIC_OPERATION
  * CAPACITY_SATURATION
  * DISRUPTION
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from headway.data.canonical import SignallingTechnologyType
from headway.infrastructure.direction import RunningDirection
from headway.scenarios.scenario_models import (
    ExplicitOverride,
    OverrideAction,
    ScenarioDefinition,
    ScenarioType,
)


class ScenarioTemplateFactory:
    """Creates structured scenario definitions populated with standard engineering overrides."""

    @staticmethod
    def create_baseline_scenario(
        scenario_id: str = "SCN_BASELINE",
        scenario_name: str = "Baseline Configuration",
        description: str = "Immutable baseline project reference configuration",
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> ScenarioDefinition:
        """Create baseline reference scenario."""
        return ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=description,
            scenario_type=ScenarioType.BASELINE,
            is_baseline=True,
            running_direction=running_direction,
            tags=["baseline", "reference"],
        )

    @staticmethod
    def create_signalling_comparison_scenario(
        scenario_id: str,
        scenario_name: str,
        target_technology: SignallingTechnologyType,
        base_scenario_id: Optional[str] = None,
        running_direction: Optional[RunningDirection] = None,
    ) -> ScenarioDefinition:
        """P12-B014: Alternative signalling system scenario."""
        scn = ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=f"Signalling technology upgrade study: {target_technology.value}",
            base_scenario_id=base_scenario_id,
            scenario_type=ScenarioType.SIGNALLING_COMPARISON,
            running_direction=running_direction,
            tags=["signalling", target_technology.value.lower()],
        )
        scn.add_override(
            ExplicitOverride(
                override_id=f"OVR_SIG_{scenario_id}",
                scenario_id=scenario_id,
                dataset_type="signalling",
                object_type="technology",
                object_id="GLOBAL",
                parameter_path="technology_type",
                new_value=target_technology.value,
                value_type="str",
                reason=f"Transition signalling architecture to {target_technology.value}",
            )
        )
        return scn

    @staticmethod
    def create_block_sensitivity_scenario(
        scenario_id: str,
        scenario_name: str,
        target_link_id: str,
        new_block_length_m: float,
        base_scenario_id: Optional[str] = None,
        running_direction: Optional[RunningDirection] = None,
    ) -> ScenarioDefinition:
        """P12-B015: Block boundary / block length sensitivity scenario."""
        scn = ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=f"Block sensitivity on link {target_link_id}: length {new_block_length_m:.1f} m",
            base_scenario_id=base_scenario_id,
            scenario_type=ScenarioType.BLOCK_SENSITIVITY,
            running_direction=running_direction,
            tags=["blocks", "sensitivity"],
        )
        scn.add_override(
            ExplicitOverride(
                override_id=f"OVR_BLK_{scenario_id}",
                scenario_id=scenario_id,
                dataset_type="infrastructure",
                object_type="track_link",
                object_id=target_link_id,
                parameter_path="length_m",
                new_value=new_block_length_m,
                value_type="float",
                unit="m",
                reason=f"Modify block length of {target_link_id} to {new_block_length_m} m",
            )
        )
        return scn

    @staticmethod
    def create_station_optimization_scenario(
        scenario_id: str,
        scenario_name: str,
        target_station_id: str,
        optimized_dwell_s: float,
        base_scenario_id: Optional[str] = None,
        running_direction: Optional[RunningDirection] = None,
    ) -> ScenarioDefinition:
        """Platform dwell and station stop optimization scenario."""
        scn = ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=f"Station dwell optimization at {target_station_id}: {optimized_dwell_s:.1f} s",
            base_scenario_id=base_scenario_id,
            scenario_type=ScenarioType.STATION_OPTIMIZATION,
            running_direction=running_direction,
            tags=["station", "dwell"],
        )
        scn.add_override(
            ExplicitOverride(
                override_id=f"OVR_DWL_{scenario_id}",
                scenario_id=scenario_id,
                dataset_type="operations",
                object_type="station_stop",
                object_id=target_station_id,
                parameter_path="dwell_time_s",
                new_value=optimized_dwell_s,
                value_type="float",
                unit="s",
                reason=f"Optimize station dwell to {optimized_dwell_s} s",
            )
        )
        return scn

    @staticmethod
    def create_tvs_policy_scenario(
        scenario_id: str,
        scenario_name: str,
        target_tvs_id: str,
        policy_type: ScenarioType,  # TVS_PER_TRACK, TVS_SHARED, or WHOLE_TUNNEL
        release_delay_s: float = 5.0,
        base_scenario_id: Optional[str] = None,
        running_direction: Optional[RunningDirection] = None,
    ) -> ScenarioDefinition:
        """P12-B016 to P12-B018: TVS operational policy scenario."""
        scn = ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=f"TVS ventilation and occupancy policy: {policy_type.value}",
            base_scenario_id=base_scenario_id,
            scenario_type=policy_type,
            running_direction=running_direction,
            tags=["tvs", policy_type.value.lower()],
        )
        scn.add_override(
            ExplicitOverride(
                override_id=f"OVR_TVS_{scenario_id}",
                scenario_id=scenario_id,
                dataset_type="infrastructure",
                object_type="tvs_section",
                object_id=target_tvs_id,
                parameter_path="release_delay_s",
                new_value=release_delay_s,
                value_type="float",
                unit="s",
                reason=f"Configure TVS release timer to {release_delay_s} s under {policy_type.value}",
            )
        )
        return scn

    @staticmethod
    def create_stochastic_scenario(
        scenario_id: str,
        scenario_name: str,
        master_seed: int = 42,
        replications: int = 10,
        base_scenario_id: Optional[str] = None,
        running_direction: Optional[RunningDirection] = None,
    ) -> ScenarioDefinition:
        """P12-B019: Stochastic operation scenario with seed configuration."""
        scn = ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=f"Monte Carlo stochastic simulation (Seed: {master_seed}, Replications: {replications})",
            base_scenario_id=base_scenario_id,
            scenario_type=ScenarioType.STOCHASTIC_OPERATION,
            running_direction=running_direction,
            tags=["stochastic", "monte_carlo"],
            metadata={"master_seed": master_seed, "replications": replications},
        )
        scn.add_override(
            ExplicitOverride(
                override_id=f"OVR_STOCH_SEED_{scenario_id}",
                scenario_id=scenario_id,
                dataset_type="stochastic",
                object_type="stochastic_settings",
                object_id="GLOBAL",
                parameter_path="master_seed",
                new_value=master_seed,
                value_type="int",
                reason="Set master random seed",
            )
        )
        return scn

    @staticmethod
    def create_disruption_scenario(
        scenario_id: str,
        scenario_name: str,
        target_link_id: str,
        restricted_speed_ms: float,
        duration_s: float = 600.0,
        base_scenario_id: Optional[str] = None,
        running_direction: Optional[RunningDirection] = None,
    ) -> ScenarioDefinition:
        """Temporary speed restriction or operational disruption scenario."""
        scn = ScenarioDefinition(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            description=f"TSR Disruption on {target_link_id}: {restricted_speed_ms:.1f} m/s for {duration_s:.0f} s",
            base_scenario_id=base_scenario_id,
            scenario_type=ScenarioType.DISRUPTION,
            running_direction=running_direction,
            tags=["disruption", "tsr"],
        )
        scn.add_override(
            ExplicitOverride(
                override_id=f"OVR_TSR_{scenario_id}",
                scenario_id=scenario_id,
                dataset_type="infrastructure",
                object_type="track_link",
                object_id=target_link_id,
                parameter_path="max_speed_ms",
                new_value=restricted_speed_ms,
                value_type="float",
                unit="m/s",
                reason=f"Apply temporary speed restriction of {restricted_speed_ms} m/s",
            )
        )
        return scn
