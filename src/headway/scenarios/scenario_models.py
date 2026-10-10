"""Core scenario data models, metadata contracts, and override representations.

Milestone P12 — Scenario Management & Engineering Comparisons (RHS-P12-001).
Covers:
- P12-SCN-001 to P12-SCN-007: Scenario identity, metadata, status, provenance, and effective configuration.
- P12-TYPE-001: Supported scenario categories and templates.
- P12-OVR-001 to P12-OVR-007: Explicit override definitions, parameter paths, geometry, and direction overrides.
- P12-DIR-001: Running direction as an explicit overridable scenario parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from headway.core.identifiers import normalize_identifier
from headway.infrastructure.direction import RunningDirection


class ScenarioType(str, Enum):
    """P12 Section 5: Standardized railway scenario categories."""

    BASELINE = "BASELINE"
    SIGNALLING_COMPARISON = "SIGNALLING_COMPARISON"
    BLOCK_SENSITIVITY = "BLOCK_SENSITIVITY"
    MIXED_TRAFFIC = "MIXED_TRAFFIC"
    STATION_OPTIMIZATION = "STATION_OPTIMIZATION"
    TVS_PER_TRACK = "TVS_PER_TRACK"
    TVS_SHARED = "TVS_SHARED"
    WHOLE_TUNNEL = "WHOLE_TUNNEL"
    STOCHASTIC_OPERATION = "STOCHASTIC_OPERATION"
    CAPACITY_SATURATION = "CAPACITY_SATURATION"
    DISRUPTION = "DISRUPTION"
    CUSTOM = "CUSTOM"


class ScenarioStatus(str, Enum):
    """P12-SCN-001: Lifecycle status of a scenario."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    INVALID = "INVALID"


class OverrideAction(str, Enum):
    """P12-OVR-005: Override operation type."""

    REPLACE = "REPLACE"
    ADD = "ADD"
    REMOVE = "REMOVE"


class ExplicitOverride(BaseModel):
    """P12-OVR-001 to P12-OVR-007: Atomic, explicit parameter override record."""

    override_id: str = Field(..., description="Unique override identifier")
    scenario_id: str = Field(..., description="Parent scenario identifier")
    dataset_type: str = Field(
        ...,
        description="Target dataset domain (infrastructure, signalling, rolling_stock, operations, analysis, stochastic)",
    )
    object_type: str = Field(..., description="Target object class/category (e.g., track_link, signal, tvs_section)")
    object_id: str = Field(..., description="Identifier of the specific target object to modify")
    parameter_path: str = Field(..., description="Dot-separated path to target parameter (e.g., max_speed_ms, release_delay_s)")
    new_value: Any = Field(..., description="New value to inject")
    value_type: str = Field(default="float", description="Expected data type name (float, int, str, bool, list, dict)")
    unit: str = Field(default="", description="Physical unit (e.g., m/s, s, W, N, m, kg)")
    action: OverrideAction = Field(default=OverrideAction.REPLACE, description="Modification action")
    reason: Optional[str] = Field(default=None, description="Engineering justification for the override")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Creation or modification timestamp in ISO 8601",
    )

    model_config = ConfigDict(extra="ignore")

    @field_validator("override_id")
    @classmethod
    def validate_override_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="OVERRIDE_ID")

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="SCENARIO_ID")

    @field_validator("dataset_type")
    @classmethod
    def validate_dataset_type(cls, v: str) -> str:
        valid_domains = {"infrastructure", "signalling", "rolling_stock", "operations", "analysis", "stochastic"}
        val = v.strip().lower()
        if val not in valid_domains:
            raise ValueError(f"Invalid dataset_type '{v}'. Must be one of {sorted(valid_domains)}.")
        return val


class ScenarioDefinition(BaseModel):
    """P12-SCN-001 to 004 & P12-DIR-001: Complete scenario specification."""

    scenario_id: str = Field(..., description="Unique scenario identifier")
    scenario_name: str = Field(..., description="Human-readable scenario name")
    description: str = Field(default="", description="Detailed scenario engineering description")
    base_scenario_id: Optional[str] = Field(
        default=None,
        description="Parent scenario identifier for inheritance. None indicates direct inheritance from baseline.",
    )
    scenario_type: ScenarioType = Field(default=ScenarioType.CUSTOM, description="Scenario classification category")
    status: ScenarioStatus = Field(default=ScenarioStatus.ACTIVE, description="Lifecycle status")
    is_baseline: bool = Field(default=False, description="Flag indicating if this represents the immutable baseline")
    running_direction: Optional[RunningDirection] = Field(
        default=None,
        description="Explicit direction parameter (FORWARD or REVERSE). If None, inherits from parent or default.",
    )
    overrides: List[ExplicitOverride] = Field(default_factory=list, description="Explicit overrides defined in this scenario")
    creation_date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Creation timestamp in ISO 8601",
    )
    last_modified_date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Last modified timestamp in ISO 8601",
    )
    tags: List[str] = Field(default_factory=list, description="Categorization and filtering tags")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary scenario engineering metadata")

    model_config = ConfigDict(extra="ignore")

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="SCENARIO_ID")

    @field_validator("base_scenario_id")
    @classmethod
    def validate_base_scenario_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return normalize_identifier(v, id_type="SCENARIO_ID")
        return None

    def add_override(self, override: ExplicitOverride) -> None:
        """Add or update an override in this scenario."""
        # Ensure scenario_id matches
        if override.scenario_id != self.scenario_id:
            override.scenario_id = self.scenario_id

        # Update existing override targeting identical domain, object_id, and parameter_path
        for i, existing in enumerate(self.overrides):
            if (
                existing.dataset_type == override.dataset_type
                and existing.object_id == override.object_id
                and existing.parameter_path == override.parameter_path
            ):
                self.overrides[i] = override
                self.touch()
                return

        self.overrides.append(override)
        self.touch()

    def remove_override(self, override_id: str) -> bool:
        """Remove an override by identifier."""
        norm_id = normalize_identifier(override_id, id_type="OVERRIDE_ID")
        initial_len = len(self.overrides)
        self.overrides = [o for o in self.overrides if o.override_id != norm_id]
        if len(self.overrides) < initial_len:
            self.touch()
            return True
        return False

    def touch(self) -> None:
        """Update last modified date timestamp."""
        self.last_modified_date = datetime.now(timezone.utc).isoformat()


@dataclass
class EffectiveConfiguration:
    """P12-EFF-001 to P12-EFF-005: Generated effective configuration package."""

    scenario_id: str
    effective_hash: str
    project_dict: Dict[str, Any]
    applied_overrides: List[ExplicitOverride] = field(default_factory=list)
    inheritance_chain: List[str] = field(default_factory=list)
    generation_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    running_direction: RunningDirection = RunningDirection.FORWARD
    is_valid: bool = True
    validation_findings: List[Dict[str, Any]] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
