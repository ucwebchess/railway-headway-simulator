"""Canonical data architecture and strongly typed engineering models for Railway Headway Simulator.

Strictly conforms to RHS-P01-001 § 4, § 7–§ 12 and RHS-DATA-001.
All internal engineering quantities strictly use SI units:
- Distance: meters (m)
- Speed: meters per second (m/s)
- Mass: kilograms (kg)
- Force: Newtons (N)
- Power: Watts (W)
- Energy: Joules (J)
- Time: seconds (s)
- Acceleration: m/s²
- Gradient: dimensionless (m/m)
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from headway.core.identifiers import normalize_identifier


class BaseCanonicalModel(BaseModel):
    """Base class for all canonical models with strict extra-field rejection."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Infrastructure Canonical Domain
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    BUFFER_STOP = "BUFFER_STOP"
    SWITCH = "SWITCH"
    JUNCTION = "JUNCTION"
    ENDPOINT = "ENDPOINT"
    STATION_BOUNDARY = "STATION_BOUNDARY"


class TrackDirectionality(str, Enum):
    BIDIRECTIONAL = "BIDIRECTIONAL"
    NOMINAL = "NOMINAL"
    REVERSE = "REVERSE"


class NetworkPosition(BaseCanonicalModel):
    """Precise location on 1D track network: LINK_ID + OFFSET_M."""

    link_id: str = Field(..., description="Physical track link identifier")
    offset_m: float = Field(..., ge=0.0, description="Offset in meters from link start node")

    @field_validator("link_id")
    @classmethod
    def validate_link_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="LINK_ID")


class ResourceInterval(BaseCanonicalModel):
    """Physical track link interval occupied by an infrastructure resource."""

    link_id: str = Field(..., description="Track link identifier")
    start_offset_m: float = Field(..., ge=0.0, description="Start offset along link")
    end_offset_m: float = Field(..., ge=0.0, description="End offset along link")

    @field_validator("link_id")
    @classmethod
    def validate_link_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="LINK_ID")

    @field_validator("end_offset_m")
    @classmethod
    def validate_interval_order(cls, v: float, info) -> float:
        start = info.data.get("start_offset_m")
        if start is not None and v <= start:
            raise ValueError(f"end_offset_m ({v}) must be strictly greater than start_offset_m ({start})")
        return v


class ResourceGeometry(BaseCanonicalModel):
    """Spatial definition of an infrastructure resource composed of link intervals."""

    resource_id: str = Field(..., description="Unique resource identifier")
    intervals: List[ResourceInterval] = Field(..., min_length=1, description="Contiguous or linked track intervals")

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="RESOURCE_ID")


class Node(BaseCanonicalModel):
    """Network vertex representing physical boundaries, switches, or endpoints."""

    node_id: str = Field(..., description="Unique node identifier")
    description: Optional[str] = Field(default=None, description="Human readable description")
    node_type: NodeType = Field(default=NodeType.ENDPOINT, description="Topology vertex classification")

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="NODE_ID")


class Track(BaseCanonicalModel):
    """Physical railway track line."""

    track_id: str = Field(..., description="Unique track line identifier")
    description: Optional[str] = Field(default=None, description="Human readable description")
    directionality: TrackDirectionality = Field(
        default=TrackDirectionality.BIDIRECTIONAL,
        description="Permitted running directions",
    )

    @field_validator("track_id")
    @classmethod
    def validate_track_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TRACK_ID")


class TrackLink(BaseCanonicalModel):
    """Directed or bidirectional 1D physical track link."""

    link_id: str = Field(..., description="Unique track link identifier")
    track_id: str = Field(..., description="Parent track line identifier")
    start_node_id: str = Field(..., description="Starting node identifier")
    end_node_id: str = Field(..., description="Ending node identifier")
    length_m: float = Field(..., gt=0.0, description="Physical length in meters")
    max_speed_ms: float = Field(..., gt=0.0, description="Civil maximum permissible speed in m/s")
    gradient_decimal: float = Field(default=0.0, description="Normalized track gradient (m/m)")
    curvature_radius_m: Optional[float] = Field(default=None, gt=0.0, description="Curve radius in meters (None = tangent)")

    @field_validator("link_id")
    @classmethod
    def validate_link_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="LINK_ID")

    @field_validator("track_id")
    @classmethod
    def validate_track_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TRACK_ID")

    @field_validator("start_node_id", "end_node_id")
    @classmethod
    def validate_nodes(cls, v: str) -> str:
        return normalize_identifier(v, id_type="NODE_ID")


class Station(BaseCanonicalModel):
    """Passenger or freight station facility."""

    station_id: str = Field(..., description="Unique station identifier")
    name: str = Field(..., description="Station official name")
    chainage_km: Optional[float] = Field(default=None, description="Informational engineering chainage")

    @field_validator("station_id")
    @classmethod
    def validate_station_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="STATION_ID")


class Platform(BaseCanonicalModel):
    """Passenger boarding platform along a track link."""

    platform_id: str = Field(..., description="Unique platform identifier")
    station_id: str = Field(..., description="Parent station identifier")
    link_id: str = Field(..., description="Track link where platform is located")
    start_offset_m: float = Field(..., ge=0.0, description="Platform start offset along link")
    end_offset_m: float = Field(..., ge=0.0, description="Platform end offset along link")
    length_m: float = Field(..., gt=0.0, description="Usable platform stopping length in meters")

    @field_validator("platform_id")
    @classmethod
    def validate_platform_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="PLATFORM_ID")

    @field_validator("station_id")
    @classmethod
    def validate_station_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="STATION_ID")

    @field_validator("link_id")
    @classmethod
    def validate_link_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="LINK_ID")


class StoppingPoint(BaseCanonicalModel):
    """Specific designated train stopping location at a platform."""

    stopping_point_id: str = Field(..., description="Unique stopping point identifier")
    platform_id: str = Field(..., description="Associated platform identifier")
    link_id: str = Field(..., description="Track link identifier")
    offset_m: float = Field(..., ge=0.0, description="Offset in meters along track link")

    @field_validator("stopping_point_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="STOPPING_POINT_ID")


class Tunnel(BaseCanonicalModel):
    """Tunnel structure encompassing one or more TVS sections."""

    tunnel_id: str = Field(..., description="Unique tunnel identifier")
    name: str = Field(..., description="Tunnel name")
    description: Optional[str] = Field(default=None, description="Tunnel details")

    @field_validator("tunnel_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TUNNEL_ID")


class TVSSection(BaseCanonicalModel):
    """Tunnel Ventilation Section enforcing the mandatory single-train occupancy rule."""

    tvs_id: str = Field(..., description="Unique TVS identifier")
    tunnel_id: str = Field(..., description="Parent tunnel identifier")
    track_id: str = Field(..., description="Track line governed by this TVS")
    link_intervals: List[ResourceInterval] = Field(..., min_length=1, description="Track intervals comprising this TVS")
    max_train_occupancy: int = Field(default=1, ge=1, description="Strict maximum train count (Default: 1)")
    holding_signal_id: Optional[str] = Field(default=None, description="Signal holding follower prior to TVS entry")
    release_delay_s: float = Field(default=0.0, ge=0.0, description="Post-clearance ventilation delay in seconds")

    @field_validator("tvs_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TVS_ID")

    @field_validator("tunnel_id")
    @classmethod
    def validate_tunnel(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TUNNEL_ID")

    @field_validator("track_id")
    @classmethod
    def validate_track(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TRACK_ID")


class SharedResourceGroup(BaseCanonicalModel):
    """Shared conflict group linking multiple mutually exclusive resources."""

    group_id: str = Field(..., description="Unique shared resource group identifier")
    description: Optional[str] = Field(default=None, description="Conflict group description")
    resource_ids: List[str] = Field(..., min_length=1, description="Resource identifiers belonging to this group")

    @field_validator("group_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="RESOURCE_GROUP_ID")


class InfrastructureModel(BaseCanonicalModel):
    """Complete physical railway infrastructure canonical model."""

    dataset_id: str = Field(default="INFRA_DATASET_01", description="Infrastructure dataset identifier")
    nodes: List[Node] = Field(default_factory=list, description="Network topology vertices")
    tracks: List[Track] = Field(default_factory=list, description="Track lines")
    track_links: List[TrackLink] = Field(default_factory=list, description="1D physical track links")
    stations: List[Station] = Field(default_factory=list, description="Stations")
    platforms: List[Platform] = Field(default_factory=list, description="Platforms")
    stopping_points: List[StoppingPoint] = Field(default_factory=list, description="Designated stopping points")
    tunnels: List[Tunnel] = Field(default_factory=list, description="Tunnels")
    tvs_sections: List[TVSSection] = Field(default_factory=list, description="Tunnel ventilation sections")
    shared_resource_groups: List[SharedResourceGroup] = Field(default_factory=list, description="Conflict groups")


# ---------------------------------------------------------------------------
# Rolling Stock Canonical Domain
# ---------------------------------------------------------------------------

class TractionModelType(str, Enum):
    SIMPLIFIED_POWER_FORCE = "SIMPLIFIED_POWER_FORCE"
    DETAILED_CURVE = "DETAILED_CURVE"


class BrakingModelType(str, Enum):
    CONSTANT_DECELERATION = "CONSTANT_DECELERATION"
    SPEED_DEPENDENT_CURVE = "SPEED_DEPENDENT_CURVE"


class BrakingSemantics(str, Enum):
    NET_EFFECTIVE = "NET_EFFECTIVE"
    BRAKE_GENERATED = "BRAKE_GENERATED"


class TractionCurvePoint(BaseCanonicalModel):
    """Point on tractive effort vs speed curve: (speed_ms, tractive_force_n)."""

    speed_ms: float = Field(..., ge=0.0, description="Train speed in m/s")
    force_n: float = Field(..., ge=0.0, description="Available tractive effort in Newtons")


class BrakingCurvePoint(BaseCanonicalModel):
    """Point on braking deceleration vs speed curve: (speed_ms, deceleration_ms2)."""

    speed_ms: float = Field(..., ge=0.0, description="Train speed in m/s")
    deceleration_ms2: float = Field(..., gt=0.0, description="Braking deceleration in m/s²")


class TrainType(BaseCanonicalModel):
    """Rolling stock physical characteristics and dynamics coefficients."""

    train_type_id: str = Field(..., description="Unique rolling stock identifier")
    description: str = Field(..., description="Train type description")
    length_m: float = Field(..., gt=0.0, description="Physical train length in meters")
    mass_empty_kg: float = Field(..., gt=0.0, description="Tare mass in kilograms")
    mass_loaded_kg: float = Field(..., gt=0.0, description="Gross laden mass in kilograms")
    rotating_mass_factor: float = Field(default=0.10, ge=0.0, le=0.50, description="Rotating mass allowance lambda (m_eq = m*(1+lambda))")
    max_speed_ms: float = Field(..., gt=0.0, description="Maximum operational train speed in m/s")
    max_acceleration_ms2: float = Field(default=1.0, gt=0.0, description="Comfort acceleration limit in m/s²")
    max_service_deceleration_ms2: float = Field(..., gt=0.0, description="Operational service braking deceleration in m/s²")
    emergency_deceleration_ms2: float = Field(..., gt=0.0, description="Emergency protection braking deceleration in m/s²")
    traction_model_type: TractionModelType = Field(default=TractionModelType.SIMPLIFIED_POWER_FORCE)
    power_w: Optional[float] = Field(default=None, gt=0.0, description="Installed continuous traction power in Watts")
    max_tractive_effort_n: Optional[float] = Field(default=None, gt=0.0, description="Maximum starting tractive effort in Newtons")
    traction_curve: List[TractionCurvePoint] = Field(default_factory=list, description="Tractive effort curve points")
    braking_model_type: BrakingModelType = Field(default=BrakingModelType.CONSTANT_DECELERATION)
    braking_semantics: BrakingSemantics = Field(default=BrakingSemantics.NET_EFFECTIVE)
    braking_curve: List[BrakingCurvePoint] = Field(default_factory=list, description="Braking curve points")
    davis_a_n: float = Field(..., ge=0.0, description="Davis rolling resistance coefficient A in Newtons (N)")
    davis_b_ns_m: float = Field(..., ge=0.0, description="Davis mechanical resistance coefficient B in N*s/m")
    davis_c_ns2_m2: float = Field(..., ge=0.0, description="Davis aerodynamic resistance coefficient C in N*s²/m²")

    @field_validator("train_type_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TRAIN_TYPE_ID")


class RollingStockModel(BaseCanonicalModel):
    """Complete rolling stock fleet canonical model."""

    dataset_id: str = Field(default="RS_DATASET_01", description="Rolling stock dataset identifier")
    train_types: List[TrainType] = Field(default_factory=list, description="Fleet rolling stock types")


# ---------------------------------------------------------------------------
# Signalling Canonical Domain
# ---------------------------------------------------------------------------

class SignallingTechnologyType(str, Enum):
    GENERIC_FIXED_BLOCK_ENGINEERING_MODEL = "GENERIC_FIXED_BLOCK_ENGINEERING_MODEL"
    ETCS_LEVEL_2 = "ETCS_LEVEL_2"
    ETCS_LEVEL_2_ENGINEERING_MODEL = "ETCS_LEVEL_2_ENGINEERING_MODEL"
    CBTC_MOVING_BLOCK = "CBTC_MOVING_BLOCK"
    CBTC_MOVING_BLOCK_ENGINEERING_MODEL = "CBTC_MOVING_BLOCK_ENGINEERING_MODEL"


class AspectModelType(str, Enum):
    TWO_ASPECT = "TWO_ASPECT"
    THREE_ASPECT = "THREE_ASPECT"
    FOUR_ASPECT = "FOUR_ASPECT"


class SignalType(str, Enum):
    MAIN = "MAIN"
    DISTANT = "DISTANT"
    HOLDING = "HOLDING"
    SHUNTING = "SHUNTING"


class Signal(BaseCanonicalModel):
    """Wayside signal or virtual marker board."""

    signal_id: str = Field(..., description="Unique signal identifier")
    link_id: str = Field(..., description="Track link where signal is mounted")
    offset_m: float = Field(..., ge=0.0, description="Position offset along track link")
    direction: TrackDirectionality = Field(default=TrackDirectionality.NOMINAL, description="Governed running direction")
    signal_type: SignalType = Field(default=SignalType.MAIN, description="Functional signal category")
    sighting_distance_m: float = Field(default=200.0, ge=0.0, description="Driver sighting distance in meters")

    @field_validator("signal_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="SIGNAL_ID")

    @field_validator("link_id")
    @classmethod
    def validate_link(cls, v: str) -> str:
        return normalize_identifier(v, id_type="LINK_ID")


class SignallingBlock(BaseCanonicalModel):
    """Signalling block resource with entry signal, exit signal, and safety overlap."""

    block_id: str = Field(..., description="Unique block identifier")
    entry_signal_id: Optional[str] = Field(default=None, description="Boundary entry signal")
    exit_signal_id: Optional[str] = Field(default=None, description="Boundary exit signal")
    link_intervals: List[ResourceInterval] = Field(..., min_length=1, description="Track intervals comprising block")
    overlap_m: float = Field(default=50.0, ge=0.0, description="Safety overlap distance beyond exit signal in meters")
    release_delay_s: float = Field(default=4.0, ge=0.0, description="Track circuit/axle counter release delay in seconds")

    @field_validator("block_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="BLOCK_ID")


class InterlockingRoute(BaseCanonicalModel):
    """Locked route protecting a train path across switches and blocks."""

    route_id: str = Field(..., description="Unique interlocking route identifier")
    entry_signal_id: str = Field(..., description="Route start signal")
    exit_signal_id: str = Field(..., description="Route destination signal")
    link_sequence: List[str] = Field(..., min_length=1, description="Ordered sequence of track links traversed")
    protected_blocks: List[str] = Field(default_factory=list, description="Blocks locked by this route")
    conflicting_route_ids: List[str] = Field(default_factory=list, description="Conflicting incompatible route identifiers")

    @field_validator("route_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="ROUTE_ID")


class SignallingSystem(BaseCanonicalModel):
    """Global signalling rules and technology parameters."""

    technology_type: SignallingTechnologyType = Field(
        default=SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL,
        description="Signalling technology architecture",
    )
    aspect_model: AspectModelType = Field(
        default=AspectModelType.THREE_ASPECT,
        description="Fixed block aspect hierarchy",
    )
    default_overlap_m: float = Field(default=50.0, ge=0.0, description="Default safety overlap distance in meters")
    sighting_time_s: float = Field(default=8.0, ge=0.0, description="Driver sighting time in seconds")
    route_setup_time_s: float = Field(default=3.0, ge=0.0, description="Interlocking route formation & locking time")
    release_delay_s: float = Field(default=4.0, ge=0.0, description="Route unlock and track release delay")


class SignallingModel(BaseCanonicalModel):
    """Complete signalling and interlocking canonical model."""

    dataset_id: str = Field(default="SIG_DATASET_01", description="Signalling dataset identifier")
    system: SignallingSystem = Field(default_factory=SignallingSystem, description="Global signalling configuration")
    signals: List[Signal] = Field(default_factory=list, description="Wayside signals")
    blocks: List[SignallingBlock] = Field(default_factory=list, description="Fixed block resources")
    routes: List[InterlockingRoute] = Field(default_factory=list, description="Interlocking routes")


# ---------------------------------------------------------------------------
# Operations & Services Canonical Domain
# ---------------------------------------------------------------------------

class StationStop(BaseCanonicalModel):
    """Scheduled passenger dwell or operational stop."""

    station_id: str = Field(..., description="Station identifier")
    platform_id: str = Field(..., description="Platform identifier")
    dwell_time_s: float = Field(..., ge=0.0, description="Nominal dwell duration in seconds")
    min_dwell_s: float = Field(default=0.0, ge=0.0, description="Minimum allowable dwell duration in seconds")
    is_mandatory_stop: bool = Field(default=True, description="Whether stopping is mandatory")

    @field_validator("station_id")
    @classmethod
    def validate_station(cls, v: str) -> str:
        return normalize_identifier(v, id_type="STATION_ID")

    @field_validator("platform_id")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        return normalize_identifier(v, id_type="PLATFORM_ID")


class ServicePattern(BaseCanonicalModel):
    """Train service specification linking a train type, traversed links, and stopping pattern."""

    service_pattern_id: str = Field(..., description="Unique service pattern identifier")
    train_type_id: str = Field(..., description="Rolling stock type assigned")
    route_link_sequence: List[str] = Field(..., min_length=1, description="Traversed track link sequence")
    priority: int = Field(default=1, ge=1, description="Operational priority (1 = highest)")
    planned_headway_s: float = Field(default=180.0, gt=0.0, description="Nominal timetable headway interval")
    stops: List[StationStop] = Field(default_factory=list, description="Sequence of station stops")

    @field_validator("service_pattern_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="SERVICE_PATTERN_ID")

    @field_validator("train_type_id")
    @classmethod
    def validate_train(cls, v: str) -> str:
        return normalize_identifier(v, id_type="TRAIN_TYPE_ID")


class OperationsModel(BaseCanonicalModel):
    """Complete operations, service patterns, and timetabling canonical model."""

    dataset_id: str = Field(default="OPS_DATASET_01", description="Operations dataset identifier")
    service_patterns: List[ServicePattern] = Field(default_factory=list, description="Configured train service patterns")


# ---------------------------------------------------------------------------
# Analysis Configuration Domain
# ---------------------------------------------------------------------------

class AnalysisType(str, Enum):
    STANDALONE = "STANDALONE"
    PAIRWISE_HEADWAY = "PAIRWISE_HEADWAY"
    REPEATED_TRAINS = "REPEATED_TRAINS"
    TVS_COMPARISON = "TVS_COMPARISON"


class AnalysisConfig(BaseCanonicalModel):
    """Specification of an engineering simulation analysis run."""

    analysis_id: str = Field(..., description="Unique analysis run identifier")
    analysis_type: AnalysisType = Field(default=AnalysisType.PAIRWISE_HEADWAY, description="Analysis mode")
    leader_service_id: Optional[str] = Field(default=None, description="Leader train service pattern ID")
    follower_service_id: Optional[str] = Field(default=None, description="Follower train service pattern ID")
    integration_step_s: float = Field(default=0.1, gt=0.0, le=1.0, description="Numerical simulation time-step in seconds")
    headway_tolerance_s: float = Field(default=0.1, gt=0.0, description="Headway convergence search tolerance")
    search_time_window_s: float = Field(default=600.0, gt=0.0, description="Maximum follower search interval")
    planning_margin_s: float = Field(default=30.0, ge=0.0, description="Operational planning margin buffer seconds")
    reference_link_id: Optional[str] = Field(default=None, description="Spatial reference measurement line link ID")
    reference_offset_m: Optional[float] = Field(default=None, ge=0.0, description="Spatial reference offset in meters")

    @field_validator("analysis_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="ANALYSIS_ID")


class AnalysisModel(BaseCanonicalModel):
    """Container for configured simulation analyses."""

    dataset_id: str = Field(default="AN_DATASET_01", description="Analysis dataset identifier")
    analyses: List[AnalysisConfig] = Field(default_factory=list, description="Analysis configurations")


# ---------------------------------------------------------------------------
# Scenario & Overrides Domain
# ---------------------------------------------------------------------------

class ScenarioOverride(BaseCanonicalModel):
    """Targeted scalar parameter override applied to an isolated scenario."""

    target_domain: str = Field(..., description="Target domain: infrastructure, rolling_stock, signalling, operations, analysis")
    target_object_id: str = Field(..., description="Target object identifier to modify")
    parameter_name: str = Field(..., description="Attribute or field name to override")
    override_value: Any = Field(..., description="New parameter value")
    justification: Optional[str] = Field(default=None, description="Engineering reason for override")


class Scenario(BaseCanonicalModel):
    """Alternative scenario definition based on an immutable baseline."""

    scenario_id: str = Field(..., description="Unique scenario identifier")
    description: str = Field(..., description="Scenario description")
    is_baseline: bool = Field(default=False, description="Whether this scenario represents the baseline")
    overrides: List[ScenarioOverride] = Field(default_factory=list, description="Scalar parameter overrides")

    @field_validator("scenario_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="SCENARIO_ID")


# ---------------------------------------------------------------------------
# Master Canonical Project Container
# ---------------------------------------------------------------------------

class CanonicalProject(BaseCanonicalModel):
    """Complete, self-contained, canonical railway headway simulation project."""

    project_id: str = Field(..., description="Unique project identifier")
    name: str = Field(..., description="Project human-readable title")
    schema_version: str = Field(default="1.0.0", description="Canonical schema specification version")
    infrastructure: InfrastructureModel = Field(default_factory=InfrastructureModel)
    rolling_stock: RollingStockModel = Field(default_factory=RollingStockModel)
    signalling: SignallingModel = Field(default_factory=SignallingModel)
    operations: OperationsModel = Field(default_factory=OperationsModel)
    analysis: AnalysisModel = Field(default_factory=AnalysisModel)
    scenarios: List[Scenario] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Metadata audit trail")

    @field_validator("project_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return normalize_identifier(v, id_type="PROJECT_ID")
