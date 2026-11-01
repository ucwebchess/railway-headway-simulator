"""Canonical engineering report models and data structures.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 4, § 6, § 7, § 8).
Defines:
- ReportType and ReportSectionId enums
- ReportMetadata and ExecutiveKpis
- RollingStockSummary, InfrastructureSummary, BottleneckDiagnosis
- Recommendation data model
- ReportSection container and ReportDocument canonical representation
- Invariant: Zero recalculation; all data originates from simulation result packages.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from headway.infrastructure.direction import RunningDirection
from headway.reporting.tables import EngineeringTable


class ReportType(str, Enum):
    """P14-TYP-001: Standardized report classification categories."""

    DETAILED_ENGINEERING = "DETAILED_ENGINEERING"
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    HEADWAY_ASSESSMENT = "HEADWAY_ASSESSMENT"
    MIXED_TRAFFIC = "MIXED_TRAFFIC"
    CAPACITY_ASSESSMENT = "CAPACITY_ASSESSMENT"
    TVS_ASSESSMENT = "TVS_ASSESSMENT"
    STOCHASTIC_ASSESSMENT = "STOCHASTIC_ASSESSMENT"
    SCENARIO_COMPARISON = "SCENARIO_COMPARISON"
    VALIDATION_REPORT = "VALIDATION_REPORT"


class ReportSectionId(str, Enum):
    """Enumeration of all supported report sections."""

    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    SPEED_GRADIENT_CURVATURE = "SPEED_GRADIENT_CURVATURE"
    BLOCKING_STAIRWAY = "BLOCKING_STAIRWAY"
    SEVEN_COMPONENT_BREAKDOWN = "SEVEN_COMPONENT_BREAKDOWN"
    CONFLICT_RANKING = "CONFLICT_RANKING"
    LONGEST_OCCUPATIONS = "LONGEST_OCCUPATIONS"
    STATION_PLATFORM_OCCUPATION = "STATION_PLATFORM_OCCUPATION"
    MIXED_TRAFFIC_MATRIX = "MIXED_TRAFFIC_MATRIX"
    STATION_STOPPING_TABLE = "STATION_STOPPING_TABLE"
    BLOCK_LENGTH_SENSITIVITY = "BLOCK_LENGTH_SENSITIVITY"
    DETAILED_RESOURCE_TIMING = "DETAILED_RESOURCE_TIMING"
    GEOMETRY_PROVENANCE = "GEOMETRY_PROVENANCE"
    ASSUMPTIONS_AUDIT = "ASSUMPTIONS_AUDIT"
    TVS_ASSESSMENT = "TVS_ASSESSMENT"
    OPERATIONAL_ASSESSMENT = "OPERATIONAL_ASSESSMENT"
    STOCHASTIC_RELIABILITY = "STOCHASTIC_RELIABILITY"
    SCENARIO_COMPARISON = "SCENARIO_COMPARISON"
    VERIFICATION_LIMITATIONS = "VERIFICATION_LIMITATIONS"
    CONCLUSIONS_RECOMMENDATIONS = "CONCLUSIONS_RECOMMENDATIONS"


class RecommendationCategory(str, Enum):
    """P14-CON-003: Categorization of engineering recommendations."""

    INFRASTRUCTURE_MODIFICATION = "INFRASTRUCTURE_MODIFICATION"
    SIGNALLING_MODIFICATION = "SIGNALLING_MODIFICATION"
    OPERATIONAL_MODIFICATION = "OPERATIONAL_MODIFICATION"
    STATION_PLATFORM_MODIFICATION = "STATION_PLATFORM_MODIFICATION"
    TVS_OPERATIONAL_STRATEGY = "TVS_OPERATIONAL_STRATEGY"
    FURTHER_INVESTIGATION = "FURTHER_INVESTIGATION"


@dataclass(frozen=True)
class Recommendation:
    """P14-REC-001 to 004: Formally structured, rule-derived recommendation."""

    recommendation_id: str
    category: RecommendationCategory
    title: str
    description: str
    rationale: str
    expected_benefit: str
    governing_resource_id: Optional[str] = None
    simulated_improvement_s: Optional[float] = None
    requires_further_simulation: bool = True
    assumptions_and_limitations: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "expected_benefit": self.expected_benefit,
            "governing_resource_id": self.governing_resource_id,
            "simulated_improvement_s": self.simulated_improvement_s,
            "requires_further_simulation": self.requires_further_simulation,
            "assumptions_and_limitations": self.assumptions_and_limitations,
        }


@dataclass(frozen=True)
class ExecutiveKpis:
    """P14-EXE-001: The principal headline KPIs."""

    technical_headway_s: float
    technical_headway_min: float
    theoretical_capacity_tph: float
    planning_capacity_tph: float
    controlling_bottleneck_id: str
    controlling_bottleneck_type: str
    controlling_bottleneck_location_m: float
    headway_definition: str = "TECHNICAL_MINIMUM"
    planning_margin_s: float = 18.0
    total_service_duration_s: Optional[float] = None
    performance_factor: float = 1.0
    performance_factor_source: str = "default"

    @property
    def performance_factor_str(self) -> str:
        """Formatted performance factor percentage (e.g. 95%)."""
        return f"{int(round(self.performance_factor * 100))}%"

    @property
    def controlling_bottleneck_chainage_km(self) -> float:
        return self.controlling_bottleneck_location_m / 1000.0

    @property
    def planning_margin_str(self) -> str:
        """Formatted planning margin label (e.g. Margin: 18 s)."""
        return f"Margin: {self.planning_margin_s:.0f} s"

    @property
    def total_service_duration_str(self) -> str:
        """Formatted total service duration in HH:MM:SS."""
        if self.total_service_duration_s is None:
            return "N/A"
        tot = int(round(self.total_service_duration_s))
        hh = tot // 3600
        mm = (tot % 3600) // 60
        ss = tot % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "technical_headway_s": self.technical_headway_s,
            "technical_headway_min": self.technical_headway_min,
            "theoretical_capacity_tph": self.theoretical_capacity_tph,
            "planning_capacity_tph": self.planning_capacity_tph,
            "controlling_bottleneck_id": self.controlling_bottleneck_id,
            "controlling_bottleneck_type": self.controlling_bottleneck_type,
            "controlling_bottleneck_location_m": self.controlling_bottleneck_location_m,
            "controlling_bottleneck_chainage_km": self.controlling_bottleneck_chainage_km,
            "headway_definition": self.headway_definition,
            "planning_margin_s": self.planning_margin_s,
            "planning_margin_str": self.planning_margin_str,
            "total_service_duration_s": self.total_service_duration_s,
            "total_service_duration_str": self.total_service_duration_str,
            "performance_factor": self.performance_factor,
            "performance_factor_str": self.performance_factor_str,
            "performance_factor_source": self.performance_factor_source,
        }


@dataclass(frozen=True)
class RollingStockSummary:
    """P14-EXE-003: Technical summary of train dynamic parameters."""

    model_name: str
    train_length_m: float
    tare_mass_t: float
    gross_mass_t: float
    max_speed_kmh: float
    traction_power_kw: float
    service_braking_deceleration_ms2: float
    emergency_braking_deceleration_ms2: float
    davis_a_n: float
    davis_b_ns_per_m: float
    davis_c_ns2_per_m2: float
    train_type_id: str = ""
    description: str = ""
    max_tractive_effort_kn: float = 0.0
    train_types: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "train_type_id": self.train_type_id,
            "description": self.description,
            "train_length_m": self.train_length_m,
            "tare_mass_t": self.tare_mass_t,
            "gross_mass_t": self.gross_mass_t,
            "max_speed_kmh": self.max_speed_kmh,
            "traction_power_kw": self.traction_power_kw,
            "max_tractive_effort_kn": self.max_tractive_effort_kn,
            "service_braking_deceleration_ms2": self.service_braking_deceleration_ms2,
            "emergency_braking_deceleration_ms2": self.emergency_braking_deceleration_ms2,
            "davis_a_n": self.davis_a_n,
            "davis_b_ns_per_m": self.davis_b_ns_per_m,
            "davis_c_ns2_per_m2": self.davis_c_ns2_per_m2,
            "train_types": list(self.train_types),
        }


@dataclass(frozen=True)
class InfrastructureSummary:
    """P14-EXE-004: Signalling and infrastructure topology summary."""

    signalling_technology: str
    topology_mode: str
    dataset_id: str
    dataset_version: str
    dataset_hash: str
    route_setup_time_s: float
    resource_release_delay_s: float
    model_fidelity: str = "MICROSCOPIC_HIGH_FIDELITY"
    aspect_model: str = "THREE_ASPECT"
    default_overlap_m: float = 0.0
    sighting_time_s: float = 8.0
    total_links: int = 0
    total_blocks: int = 0
    total_signals: int = 0
    total_stations: int = 0
    total_platforms: int = 0
    total_tvs_sections: int = 0
    # v1.11.3: signalling timing actually applied to the blocking-time decomposition
    # (SimulationResultPackage.metadata["signalling_timing"]). resource_release_delay_s
    # remains the SignallingSystem (workbook) value; per-block overrides are disclosed.
    driver_reaction_time_s: Optional[float] = None
    block_release_overrides: Tuple[Tuple[float, int], ...] = ()  # (release_s, block count) != system
    timed_block_count: int = 0

    @property
    def approach_time_s(self) -> Optional[float]:
        """Approach allowance applied to every non-origin block: Sighting + Driver Reaction."""
        if self.driver_reaction_time_s is None:
            return None
        return round(self.sighting_time_s + self.driver_reaction_time_s, 6)

    @property
    def approach_footnote(self) -> Optional[str]:
        """Executive Summary footnote explaining the Approach column of the detailed tables."""
        if self.driver_reaction_time_s is None:
            return None
        return (
            f"Approach time in detailed tables = Sighting + {self.driver_reaction_time_s:.1f}s reaction "
            f"({self.sighting_time_s:.1f} s + {self.driver_reaction_time_s:.1f} s = {self.approach_time_s:.1f} s "
            "per non-origin block)."
        )

    @property
    def release_override_note(self) -> Optional[str]:
        """Disclosure of per-block RELEASE_DELAY_S values that differ from the system value."""
        if not self.block_release_overrides:
            return None
        parts = ", ".join(
            f"{val:.1f} s on {cnt} of {self.timed_block_count} blocks" for val, cnt in self.block_release_overrides
        )
        n_override = sum(cnt for _, cnt in self.block_release_overrides)
        n_default = max(0, self.timed_block_count - n_override)
        default_txt = (
            f"no block uses the system default ({self.resource_release_delay_s:.1f} s)"
            if n_default == 0
            else f"the system default ({self.resource_release_delay_s:.1f} s) applies to the remaining {n_default} blocks"
        )
        return (
            f"Release delay overridden per block (Blocks.RELEASE_DELAY_S): {parts}. Detailed tables and headway use "
            f"the per-block value; {default_txt}."
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signalling_technology": self.signalling_technology,
            "topology_mode": self.topology_mode,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "route_setup_time_s": self.route_setup_time_s,
            "resource_release_delay_s": self.resource_release_delay_s,
            "model_fidelity": self.model_fidelity,
            "aspect_model": self.aspect_model,
            "default_overlap_m": self.default_overlap_m,
            "sighting_time_s": self.sighting_time_s,
            "total_links": self.total_links,
            "total_blocks": self.total_blocks,
            "total_signals": self.total_signals,
            "total_stations": self.total_stations,
            "total_platforms": self.total_platforms,
            "total_tvs_sections": self.total_tvs_sections,
            "driver_reaction_time_s": self.driver_reaction_time_s,
            "approach_time_s": self.approach_time_s,
            "block_release_overrides": [list(x) for x in self.block_release_overrides],
            "timed_block_count": self.timed_block_count,
        }


@dataclass(frozen=True)
class BottleneckDiagnosis:
    """P14-EXE-005: Engineering diagnosis of the controlling constraint."""

    resource_id: str
    resource_type: str
    physical_location_m: float
    governing_component: str
    total_occupation_s: float
    required_headway_s: float
    slack_to_second_s: float
    engineering_cause: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "physical_location_m": self.physical_location_m,
            "governing_component": self.governing_component,
            "total_occupation_s": self.total_occupation_s,
            "required_headway_s": self.required_headway_s,
            "slack_to_second_s": self.slack_to_second_s,
            "engineering_cause": self.engineering_cause,
        }


@dataclass
class ReportMetadata:
    """P14-ARC-004 & P14-DES-004: Header, tracking and audit metadata."""

    report_id: str
    project_id: str
    scenario_id: str
    simulation_run_id: str
    report_type: ReportType
    running_direction: RunningDirection
    generation_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    software_version: str = "1.3.0"
    input_configuration_hash: str = ""
    validation_status: str = "VALID"
    title: str = "Railway Headway & Line Capacity Assessment"
    subtitle: str = "Engineering Simulation Report"
    corridor_name: str = "Main Operational Corridor"
    author: str = "Automated Railway Headway Simulation Subsystem"
    organization: str = "Railway Infrastructure Authority"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "project_id": self.project_id,
            "scenario_id": self.scenario_id,
            "simulation_run_id": self.simulation_run_id,
            "report_type": self.report_type.value,
            "running_direction": self.running_direction.value,
            "generation_time": self.generation_time,
            "software_version": self.software_version,
            "input_configuration_hash": self.input_configuration_hash,
            "validation_status": self.validation_status,
            "title": self.title,
            "subtitle": self.subtitle,
            "corridor_name": self.corridor_name,
            "author": self.author,
            "organization": self.organization,
        }


@dataclass
class ReportSection:
    """A distinct structural section of the formal report."""

    section_id: ReportSectionId
    title: str
    section_number: str
    is_applicable: bool = True
    not_applicable_reason: Optional[str] = None
    narrative_paragraphs: List[str] = field(default_factory=list)
    kpis: Dict[str, Any] = field(default_factory=dict)
    tables: List[EngineeringTable] = field(default_factory=list)
    figure_keys: List[str] = field(default_factory=list)
    callout_boxes: List[Dict[str, str]] = field(default_factory=list)
    recommendations: List[Recommendation] = field(default_factory=list)


@dataclass
class ReportDocument:
    """P14-ARC-004: Comprehensive canonical representation of an assembled report."""

    metadata: ReportMetadata
    executive_kpis: ExecutiveKpis
    rolling_stock: Optional[RollingStockSummary] = None
    infrastructure: Optional[InfrastructureSummary] = None
    bottleneck_diagnosis: Optional[BottleneckDiagnosis] = None
    sections: Dict[ReportSectionId, ReportSection] = field(default_factory=dict)
    figures_data: Dict[str, Any] = field(default_factory=dict)  # Plotly figures or static paths
    recommendations: List[Recommendation] = field(default_factory=list)
    audit_events: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def running_direction(self) -> RunningDirection:
        return self.metadata.running_direction

    @property
    def direction_banner_text(self) -> str:
        """P14-DIR-008: Mandatory textual direction statement."""
        return f"Running Direction: {self.running_direction.value}"

    @property
    def total_service_duration_s(self) -> Optional[float]:
        """Total service duration in seconds across complete line."""
        return self.executive_kpis.total_service_duration_s

    @property
    def total_service_duration_str(self) -> str:
        """Formatted total service duration in HH:MM:SS."""
        return self.executive_kpis.total_service_duration_str

    def get_section(self, section_id: ReportSectionId) -> Optional[ReportSection]:
        return self.sections.get(section_id)

    def to_dict(self) -> Dict[str, Any]:
        """Convert canonical report document to JSON-serializable dictionary."""
        return {
            "metadata": self.metadata.to_dict(),
            "executive_kpis": self.executive_kpis.to_dict(),
            "rolling_stock": self.rolling_stock.to_dict() if self.rolling_stock else None,
            "infrastructure": self.infrastructure.to_dict() if self.infrastructure else None,
            "bottleneck_diagnosis": self.bottleneck_diagnosis.to_dict() if self.bottleneck_diagnosis else None,
            "sections": {
                sid.value: {
                    "section_id": s.section_id.value,
                    "title": s.title,
                    "section_number": s.section_number,
                    "is_applicable": s.is_applicable,
                    "not_applicable_reason": s.not_applicable_reason,
                    "narrative_paragraphs": s.narrative_paragraphs,
                    "kpis": s.kpis,
                    "tables": [t.table_id for t in s.tables],
                    "figure_keys": s.figure_keys,
                    "callout_boxes": s.callout_boxes,
                    "recommendations": [r.to_dict() for r in s.recommendations],
                }
                for sid, s in self.sections.items()
            },
            "recommendations": [r.to_dict() for r in self.recommendations],
            "audit_events": self.audit_events,
        }
