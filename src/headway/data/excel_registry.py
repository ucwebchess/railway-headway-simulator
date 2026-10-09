"""Authoritative Excel schema registry for Railway Headway Simulator.

Strictly satisfies P01-XLS-007:
One single, authoritative worksheet schema registry from which both the
Excel template generator and the Excel importer obtain their field definitions,
types, units, requirement flags, and allowed enumerations.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FieldType(str, Enum):
    STRING = "string"
    FLOAT = "float"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    STRING_LIST = "string_list"


@dataclass(frozen=True)
class ColumnDef:
    """Definition of a single worksheet column."""

    name: str
    canonical_name: str
    field_type: FieldType
    required: bool = True
    excel_unit: Optional[str] = None
    canonical_unit: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    default_value: Optional[Any] = None
    description: str = ""
    example_value: Optional[Any] = None


@dataclass(frozen=True)
class WorksheetDef:
    """Definition of a worksheet within an Excel workbook."""

    name: str
    description: str
    columns: List[ColumnDef]
    required: bool = True
    min_rows: int = 0


@dataclass(frozen=True)
class WorkbookDef:
    """Definition of an authoritative Excel workbook."""

    workbook_type: str
    default_filename: str
    description: str
    worksheets: List[WorksheetDef]


# ---------------------------------------------------------------------------
# Authoritative Column & Worksheet Registry
# ---------------------------------------------------------------------------

# Common Metadata Worksheet across all workbooks
METADATA_WORKSHEET = WorksheetDef(
    name="METADATA",
    description="Standardized workbook identification and provenance",
    columns=[
        ColumnDef("PROPERTY", "property", FieldType.STRING, required=True, description="Metadata key", example_value="WORKBOOK_TYPE"),
        ColumnDef("VALUE", "value", FieldType.STRING, required=True, description="Metadata value", example_value="INFRASTRUCTURE"),
    ],
    required=True,
    min_rows=4,
)

# 1. INFRASTRUCTURE WORKBOOK
INFRASTRUCTURE_WORKBOOK = WorkbookDef(
    workbook_type="INFRASTRUCTURE",
    default_filename="HEADWAY_INFRASTRUCTURE_v1.0.xlsx",
    description="Physical railway network topology, geometry, stations, and TVS boundaries",
    worksheets=[
        METADATA_WORKSHEET,
        WorksheetDef(
            name="Nodes",
            description="Network vertices representing switches, buffer stops, or boundaries",
            columns=[
                ColumnDef("NODE_ID", "node_id", FieldType.STRING, required=True, description="Unique node identifier", example_value="ND_01"),
                ColumnDef("DESCRIPTION", "description", FieldType.STRING, required=False, description="Node description", example_value="Terminal buffer stop"),
                ColumnDef("NODE_TYPE", "node_type", FieldType.STRING, required=False, allowed_values=["BUFFER_STOP", "SWITCH", "JUNCTION", "ENDPOINT", "STATION_BOUNDARY"], default_value="ENDPOINT", description="Vertex topological role", example_value="BUFFER_STOP"),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="Tracks",
            description="Physical railway track lines",
            columns=[
                ColumnDef("TRACK_ID", "track_id", FieldType.STRING, required=True, description="Unique track line identifier", example_value="TRK_M1"),
                ColumnDef("DESCRIPTION", "description", FieldType.STRING, required=False, description="Track line description", example_value="Main Line 1"),
                ColumnDef("DIRECTIONALITY", "directionality", FieldType.STRING, required=False, allowed_values=["BIDIRECTIONAL", "NOMINAL", "REVERSE"], default_value="BIDIRECTIONAL", description="Allowed running directions", example_value="NOMINAL"),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="TrackLinks",
            description="1D continuous track segments connecting nodes",
            columns=[
                ColumnDef("LINK_ID", "link_id", FieldType.STRING, required=True, description="Unique link identifier", example_value="LNK_01"),
                ColumnDef("TRACK_ID", "track_id", FieldType.STRING, required=True, description="Parent track identifier", example_value="TRK_M1"),
                ColumnDef("START_NODE_ID", "start_node_id", FieldType.STRING, required=True, description="Origin node identifier", example_value="ND_01"),
                ColumnDef("END_NODE_ID", "end_node_id", FieldType.STRING, required=True, description="Destination node identifier", example_value="ND_02"),
                ColumnDef("LENGTH_M", "length_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Physical segment length in meters", example_value=1200.0),
                ColumnDef("MAX_SPEED_KMH", "max_speed_ms", FieldType.FLOAT, required=True, excel_unit="km/h", canonical_unit="m/s", description="Civil speed limit in km/h", example_value=120.0),
                ColumnDef("GRADIENT_PERMIL", "gradient_decimal", FieldType.FLOAT, required=False, excel_unit="‰", canonical_unit="dimensionless", default_value=0.0, description="Gradient in permil (‰)", example_value=0.0),
                ColumnDef("CURVATURE_RADIUS_M", "curvature_radius_m", FieldType.FLOAT, required=False, excel_unit="m", canonical_unit="m", default_value=None, description="Curve radius in meters (blank for tangent)", example_value=None),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="Stations",
            description="Passenger and operational stations",
            columns=[
                ColumnDef("STATION_ID", "station_id", FieldType.STRING, required=True, description="Unique station identifier", example_value="STN_CENTRAL"),
                ColumnDef("NAME", "name", FieldType.STRING, required=True, description="Station official name", example_value="Central Station"),
                ColumnDef("CHAINAGE_KM", "chainage_km", FieldType.FLOAT, required=False, excel_unit="km", canonical_unit="km", description="Reference engineering chainage", example_value=12.5),
            ],
            required=False,
        ),
        WorksheetDef(
            name="Platforms",
            description="Station passenger platforms along track links",
            columns=[
                ColumnDef("PLATFORM_ID", "platform_id", FieldType.STRING, required=True, description="Unique platform identifier", example_value="PLT_01"),
                ColumnDef("STATION_ID", "station_id", FieldType.STRING, required=True, description="Parent station identifier", example_value="STN_CENTRAL"),
                ColumnDef("LINK_ID", "link_id", FieldType.STRING, required=True, description="Track link where platform is located", example_value="LNK_01"),
                ColumnDef("START_OFFSET_M", "start_offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Platform start offset along link", example_value=200.0),
                ColumnDef("END_OFFSET_M", "end_offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Platform end offset along link", example_value=450.0),
                ColumnDef("LENGTH_M", "length_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Usable platform length in meters", example_value=250.0),
            ],
            required=False,
        ),
        WorksheetDef(
            name="StoppingPoints",
            description="Designated stopping points at platforms",
            columns=[
                ColumnDef("STOPPING_POINT_ID", "stopping_point_id", FieldType.STRING, required=True, description="Unique stopping point ID", example_value="STP_01"),
                ColumnDef("PLATFORM_ID", "platform_id", FieldType.STRING, required=True, description="Platform identifier", example_value="PLT_01"),
                ColumnDef("LINK_ID", "link_id", FieldType.STRING, required=True, description="Track link identifier", example_value="LNK_01"),
                ColumnDef("OFFSET_M", "offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Stopping point offset along link", example_value=430.0),
            ],
            required=False,
        ),
        WorksheetDef(
            name="Tunnels",
            description="Tunnel structures encompassing TVS ventilation zones",
            columns=[
                ColumnDef("TUNNEL_ID", "tunnel_id", FieldType.STRING, required=True, description="Unique tunnel identifier", example_value="TNL_01"),
                ColumnDef("NAME", "name", FieldType.STRING, required=True, description="Tunnel official name", example_value="Summit Tunnel"),
                ColumnDef("DESCRIPTION", "description", FieldType.STRING, required=False, description="Tunnel details", example_value="Bored twin tunnel"),
            ],
            required=False,
        ),
        WorksheetDef(
            name="TVSSections",
            description="Tunnel Ventilation Sections (Mandatory single-train rule)",
            columns=[
                ColumnDef("TVS_ID", "tvs_id", FieldType.STRING, required=True, description="Unique TVS identifier", example_value="TVS_01"),
                ColumnDef("TUNNEL_ID", "tunnel_id", FieldType.STRING, required=True, description="Parent tunnel identifier", example_value="TNL_01"),
                ColumnDef("TRACK_ID", "track_id", FieldType.STRING, required=True, description="Track line governed", example_value="TRK_M1"),
                ColumnDef("LINK_ID", "link_id", FieldType.STRING, required=True, description="Link containing TVS section", example_value="LNK_01"),
                ColumnDef("START_OFFSET_M", "start_offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="TVS start boundary offset", example_value=300.0),
                ColumnDef("END_OFFSET_M", "end_offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="TVS end boundary offset", example_value=1100.0),
                ColumnDef("MAX_OCCUPANCY", "max_train_occupancy", FieldType.INTEGER, required=False, default_value=1, description="Maximum simultaneous trains (Default 1)", example_value=1),
                ColumnDef("HOLDING_SIGNAL_ID", "holding_signal_id", FieldType.STRING, required=False, description="Signal holding follower train if TVS occupied", example_value="SIG_01"),
                ColumnDef("RELEASE_DELAY_S", "release_delay_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=0.0, description="Ventilation purge delay after rear exit", example_value=15.0),
            ],
            required=False,
        ),
        WorksheetDef(
            name="SharedResourceGroups",
            description="Mutually exclusive shared conflict resources",
            columns=[
                ColumnDef("GROUP_ID", "group_id", FieldType.STRING, required=True, description="Unique conflict group ID", example_value="GRP_01"),
                ColumnDef("DESCRIPTION", "description", FieldType.STRING, required=False, description="Group description", example_value="Crossover conflict"),
                ColumnDef("RESOURCE_IDS", "resource_ids", FieldType.STRING_LIST, required=True, description="Comma-separated resource IDs", example_value="BLK_01, BLK_02"),
            ],
            required=False,
        ),
    ],
)

# 2. SIGNALLING WORKBOOK
SIGNALLING_WORKBOOK = WorkbookDef(
    workbook_type="SIGNALLING",
    default_filename="HEADWAY_SIGNALLING_v1.0.xlsx",
    description="Signalling system rules, signals, block sections, and interlocking routes",
    worksheets=[
        METADATA_WORKSHEET,
        WorksheetDef(
            name="SignallingSystem",
            description="Global signalling system configuration",
            columns=[
                ColumnDef("TECHNOLOGY_TYPE", "technology_type", FieldType.STRING, required=True, allowed_values=["GENERIC_FIXED_BLOCK_ENGINEERING_MODEL", "ETCS_LEVEL_2", "CBTC_MOVING_BLOCK"], default_value="GENERIC_FIXED_BLOCK_ENGINEERING_MODEL", description="Signalling architecture", example_value="GENERIC_FIXED_BLOCK_ENGINEERING_MODEL"),
                ColumnDef("ASPECT_MODEL", "aspect_model", FieldType.STRING, required=True, allowed_values=["TWO_ASPECT", "THREE_ASPECT", "FOUR_ASPECT"], default_value="THREE_ASPECT", description="Signalling aspect hierarchy", example_value="THREE_ASPECT"),
                ColumnDef("DEFAULT_OVERLAP_M", "default_overlap_m", FieldType.FLOAT, required=False, excel_unit="m", canonical_unit="m", default_value=50.0, description="Safety overlap distance", example_value=50.0),
                ColumnDef("SIGHTING_TIME_S", "sighting_time_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=8.0, description="Driver sighting time in seconds", example_value=8.0),
                ColumnDef("ROUTE_SETUP_TIME_S", "route_setup_time_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=3.0, description="Route formation and locking time", example_value=3.0),
                ColumnDef("RELEASE_DELAY_S", "release_delay_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=4.0, description="Track release delay in seconds", example_value=4.0),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="Signals",
            description="Physical and virtual wayside signals",
            columns=[
                ColumnDef("SIGNAL_ID", "signal_id", FieldType.STRING, required=True, description="Unique signal identifier", example_value="SIG_01"),
                ColumnDef("LINK_ID", "link_id", FieldType.STRING, required=True, description="Track link where signal is mounted", example_value="LNK_01"),
                ColumnDef("OFFSET_M", "offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Position offset along link", example_value=100.0),
                ColumnDef("DIRECTION", "direction", FieldType.STRING, required=False, allowed_values=["BIDIRECTIONAL", "NOMINAL", "REVERSE"], default_value="NOMINAL", description="Governed running direction", example_value="NOMINAL"),
                ColumnDef("SIGNAL_TYPE", "signal_type", FieldType.STRING, required=False, allowed_values=["MAIN", "DISTANT", "HOLDING", "SHUNTING"], default_value="MAIN", description="Signal functional role", example_value="MAIN"),
                ColumnDef("SIGHTING_DISTANCE_M", "sighting_distance_m", FieldType.FLOAT, required=False, excel_unit="m", canonical_unit="m", default_value=200.0, description="Driver sighting distance", example_value=200.0),
            ],
            required=False,
        ),
        WorksheetDef(
            name="Blocks",
            description="Fixed signalling block sections",
            columns=[
                ColumnDef("BLOCK_ID", "block_id", FieldType.STRING, required=True, description="Unique block section identifier", example_value="BLK_01"),
                ColumnDef("ENTRY_SIGNAL_ID", "entry_signal_id", FieldType.STRING, required=False, description="Boundary entry signal", example_value="SIG_01"),
                ColumnDef("EXIT_SIGNAL_ID", "exit_signal_id", FieldType.STRING, required=False, description="Boundary exit signal", example_value="SIG_02"),
                ColumnDef("LINK_ID", "link_id", FieldType.STRING, required=True, description="Track link containing block", example_value="LNK_01"),
                ColumnDef("START_OFFSET_M", "start_offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Block start offset along link", example_value=100.0),
                ColumnDef("END_OFFSET_M", "end_offset_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Block end offset along link", example_value=1100.0),
                ColumnDef("OVERLAP_M", "overlap_m", FieldType.FLOAT, required=False, excel_unit="m", canonical_unit="m", default_value=50.0, description="Safety overlap past exit signal", example_value=50.0),
                ColumnDef("RELEASE_DELAY_S", "release_delay_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=4.0, description="Track circuit release delay", example_value=4.0),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="InterlockingRoutes",
            description="Interlocking train routes and conflicting paths",
            columns=[
                ColumnDef("ROUTE_ID", "route_id", FieldType.STRING, required=True, description="Unique route identifier", example_value="RTE_01"),
                ColumnDef("ENTRY_SIGNAL_ID", "entry_signal_id", FieldType.STRING, required=True, description="Route origin signal", example_value="SIG_01"),
                ColumnDef("EXIT_SIGNAL_ID", "exit_signal_id", FieldType.STRING, required=True, description="Route destination signal", example_value="SIG_02"),
                ColumnDef("LINK_SEQUENCE", "link_sequence", FieldType.STRING_LIST, required=True, description="Comma-separated track link sequence", example_value="LNK_01"),
                ColumnDef("PROTECTED_BLOCKS", "protected_blocks", FieldType.STRING_LIST, required=False, description="Comma-separated locked block IDs", example_value="BLK_01"),
                ColumnDef("CONFLICTING_ROUTES", "conflicting_routes", FieldType.STRING_LIST, required=False, description="Comma-separated conflicting route IDs", example_value=""),
            ],
            required=False,
        ),
    ],
)

# 3. ROLLING STOCK WORKBOOK
ROLLING_STOCK_WORKBOOK = WorkbookDef(
    workbook_type="ROLLING_STOCK",
    default_filename="HEADWAY_ROLLING_STOCK_v1.0.xlsx",
    description="Train types, physical mass, length, Davis resistance, traction, and braking",
    worksheets=[
        METADATA_WORKSHEET,
        WorksheetDef(
            name="TrainTypes",
            description="Rolling stock types and kinematic parameters",
            columns=[
                ColumnDef("TRAIN_TYPE_ID", "train_type_id", FieldType.STRING, required=True, description="Unique train type ID", example_value="TRN_COMMUTER"),
                ColumnDef("DESCRIPTION", "description", FieldType.STRING, required=True, description="Fleet description", example_value="8-Car EMU Commuter"),
                ColumnDef("LENGTH_M", "length_m", FieldType.FLOAT, required=True, excel_unit="m", canonical_unit="m", description="Train length in meters", example_value=160.0),
                ColumnDef("MASS_EMPTY_T", "mass_empty_kg", FieldType.FLOAT, required=True, excel_unit="tonnes", canonical_unit="kg", description="Tare mass in tonnes", example_value=280.0),
                ColumnDef("MASS_LOADED_T", "mass_loaded_kg", FieldType.FLOAT, required=True, excel_unit="tonnes", canonical_unit="kg", description="Gross laden mass in tonnes", example_value=360.0),
                ColumnDef("ROTATING_MASS_FACTOR", "rotating_mass_factor", FieldType.FLOAT, required=False, default_value=0.10, description="Rotating mass factor lambda", example_value=0.10),
                ColumnDef("MAX_SPEED_KMH", "max_speed_ms", FieldType.FLOAT, required=True, excel_unit="km/h", canonical_unit="m/s", description="Maximum speed in km/h", example_value=140.0),
                ColumnDef("MAX_ACCELERATION_MS2", "max_acceleration_ms2", FieldType.FLOAT, required=False, excel_unit="m/s²", canonical_unit="m/s²", default_value=1.0, description="Comfort acceleration limit", example_value=1.0),
                ColumnDef("SERVICE_DECEL_MS2", "max_service_deceleration_ms2", FieldType.FLOAT, required=True, excel_unit="m/s²", canonical_unit="m/s²", description="Service brake deceleration", example_value=0.85),
                ColumnDef("EMERGENCY_DECEL_MS2", "emergency_deceleration_ms2", FieldType.FLOAT, required=True, excel_unit="m/s²", canonical_unit="m/s²", description="Emergency brake deceleration", example_value=1.15),
                ColumnDef("TRACTION_MODEL_TYPE", "traction_model_type", FieldType.STRING, required=False, allowed_values=["SIMPLIFIED_POWER_FORCE", "DETAILED_CURVE"], default_value="SIMPLIFIED_POWER_FORCE", description="Traction model type", example_value="SIMPLIFIED_POWER_FORCE"),
                ColumnDef("POWER_KW", "power_w", FieldType.FLOAT, required=False, excel_unit="kW", canonical_unit="W", description="Installed traction power in kW", example_value=4000.0),
                ColumnDef("MAX_TE_KN", "max_tractive_effort_n", FieldType.FLOAT, required=False, excel_unit="kN", canonical_unit="N", description="Maximum starting tractive effort in kN", example_value=300.0),
                ColumnDef("BRAKING_MODEL_TYPE", "braking_model_type", FieldType.STRING, required=False, allowed_values=["CONSTANT_DECELERATION", "SPEED_DEPENDENT_CURVE"], default_value="CONSTANT_DECELERATION", description="Braking model type", example_value="CONSTANT_DECELERATION"),
                ColumnDef("BRAKING_SEMANTICS", "braking_semantics", FieldType.STRING, required=False, allowed_values=["NET_EFFECTIVE", "BRAKE_GENERATED"], default_value="NET_EFFECTIVE", description="Braking deceleration semantics", example_value="NET_EFFECTIVE"),
                ColumnDef("DAVIS_A_KN", "davis_a_n", FieldType.FLOAT, required=True, excel_unit="kN", canonical_unit="N", description="Davis rolling resistance coefficient A in kN", example_value=3.2),
                ColumnDef("DAVIS_B_KN_PER_KMH", "davis_b_ns_m", FieldType.FLOAT, required=True, excel_unit="kN/(km/h)", canonical_unit="N*s/m", description="Davis linear resistance coefficient B", example_value=0.035),
                ColumnDef("DAVIS_C_KN_PER_KMH2", "davis_c_ns2_m2", FieldType.FLOAT, required=True, excel_unit="kN/(km/h)²", canonical_unit="N*s²/m²", description="Davis quadratic drag coefficient C", example_value=0.00065),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="TractionCurves",
            description="Detailed tractive effort vs speed points (Optional)",
            columns=[
                ColumnDef("TRAIN_TYPE_ID", "train_type_id", FieldType.STRING, required=True, description="Train type identifier", example_value="TRN_COMMUTER"),
                ColumnDef("SPEED_KMH", "speed_ms", FieldType.FLOAT, required=True, excel_unit="km/h", canonical_unit="m/s", description="Train speed in km/h", example_value=0.0),
                ColumnDef("TRACTIVE_FORCE_KN", "force_n", FieldType.FLOAT, required=True, excel_unit="kN", canonical_unit="N", description="Available force in kN", example_value=300.0),
            ],
            required=False,
        ),
        WorksheetDef(
            name="BrakingCurves",
            description="Detailed deceleration vs speed points (Optional)",
            columns=[
                ColumnDef("TRAIN_TYPE_ID", "train_type_id", FieldType.STRING, required=True, description="Train type identifier", example_value="TRN_COMMUTER"),
                ColumnDef("SPEED_KMH", "speed_ms", FieldType.FLOAT, required=True, excel_unit="km/h", canonical_unit="m/s", description="Train speed in km/h", example_value=140.0),
                ColumnDef("DECELERATION_MS2", "deceleration_ms2", FieldType.FLOAT, required=True, excel_unit="m/s²", canonical_unit="m/s²", description="Deceleration rate in m/s²", example_value=0.85),
            ],
            required=False,
        ),
    ],
)

# 4. OPERATIONS WORKBOOK
OPERATIONS_WORKBOOK = WorkbookDef(
    workbook_type="OPERATIONS",
    default_filename="HEADWAY_OPERATIONS_v1.0.xlsx",
    description="Train service patterns, stopping locations, and passenger dwell times",
    worksheets=[
        METADATA_WORKSHEET,
        WorksheetDef(
            name="ServicePatterns",
            description="Operational service specifications",
            columns=[
                ColumnDef("SERVICE_PATTERN_ID", "service_pattern_id", FieldType.STRING, required=True, description="Unique service pattern ID", example_value="SRV_ALL_STOPS"),
                ColumnDef("TRAIN_TYPE_ID", "train_type_id", FieldType.STRING, required=True, description="Assigned rolling stock type", example_value="TRN_COMMUTER"),
                ColumnDef("ROUTE_LINK_SEQUENCE", "route_link_sequence", FieldType.STRING_LIST, required=True, description="Comma-separated link sequence", example_value="LNK_01"),
                ColumnDef("PRIORITY", "priority", FieldType.INTEGER, required=False, default_value=1, description="Dispatch priority (1 = highest)", example_value=1),
                ColumnDef("PLANNED_HEADWAY_MIN", "planned_headway_s", FieldType.FLOAT, required=False, excel_unit="min", canonical_unit="s", default_value=3.0, description="Nominal timetable interval in minutes", example_value=3.0),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="StoppingPatterns",
            description="Sequence of station stops and passenger dwells",
            columns=[
                ColumnDef("SERVICE_PATTERN_ID", "service_pattern_id", FieldType.STRING, required=True, description="Parent service pattern ID", example_value="SRV_ALL_STOPS"),
                ColumnDef("STOP_INDEX", "stop_index", FieldType.INTEGER, required=True, description="Order of stop (1, 2, ...)", example_value=1),
                ColumnDef("STATION_ID", "station_id", FieldType.STRING, required=True, description="Station identifier", example_value="STN_CENTRAL"),
                ColumnDef("PLATFORM_ID", "platform_id", FieldType.STRING, required=True, description="Platform identifier", example_value="PLT_01"),
                ColumnDef("DWELL_TIME_S", "dwell_time_s", FieldType.FLOAT, required=True, excel_unit="s", canonical_unit="s", description="Scheduled passenger dwell in seconds", example_value=30.0),
                ColumnDef("MIN_DWELL_S", "min_dwell_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=0.0, description="Minimum dwell in seconds", example_value=20.0),
                ColumnDef("IS_MANDATORY", "is_mandatory_stop", FieldType.BOOLEAN, required=False, default_value=True, description="Whether stopping is mandatory", example_value=True),
            ],
            required=False,
        ),
    ],
)

# 5. HEADWAY ANALYSIS WORKBOOK
HEADWAY_ANALYSIS_WORKBOOK = WorkbookDef(
    workbook_type="HEADWAY_ANALYSIS",
    default_filename="HEADWAY_ANALYSIS_v1.0.xlsx",
    description="Headway analysis pairs, convergence tolerances, and planning margins",
    worksheets=[
        METADATA_WORKSHEET,
        WorksheetDef(
            name="AnalysisSettings",
            description="Simulation analysis run specifications",
            columns=[
                ColumnDef("ANALYSIS_ID", "analysis_id", FieldType.STRING, required=True, description="Unique analysis identifier", example_value="AN_HDW_01"),
                ColumnDef("ANALYSIS_TYPE", "analysis_type", FieldType.STRING, required=True, allowed_values=["STANDALONE", "PAIRWISE_HEADWAY", "REPEATED_TRAINS", "TVS_COMPARISON"], default_value="PAIRWISE_HEADWAY", description="Analysis mode", example_value="PAIRWISE_HEADWAY"),
                ColumnDef("LEADER_SERVICE_ID", "leader_service_id", FieldType.STRING, required=False, description="Leader train service pattern ID", example_value="SRV_ALL_STOPS"),
                ColumnDef("FOLLOWER_SERVICE_ID", "follower_service_id", FieldType.STRING, required=False, description="Follower train service pattern ID", example_value="SRV_ALL_STOPS"),
                ColumnDef("INTEGRATION_STEP_S", "integration_step_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=0.1, description="Simulation integration step in seconds", example_value=0.1),
                ColumnDef("HEADWAY_TOLERANCE_S", "headway_tolerance_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=0.1, description="Headway search tolerance in seconds", example_value=0.1),
                ColumnDef("SEARCH_WINDOW_S", "search_time_window_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=600.0, description="Max follower search window in seconds", example_value=600.0),
                ColumnDef("PLANNING_MARGIN_S", "planning_margin_s", FieldType.FLOAT, required=False, excel_unit="s", canonical_unit="s", default_value=30.0, description="Planning operational margin buffer in seconds", example_value=30.0),
                ColumnDef("REF_LINK_ID", "reference_link_id", FieldType.STRING, required=False, description="Spatial reference measurement line link ID", example_value="LNK_01"),
                ColumnDef("REF_OFFSET_M", "reference_offset_m", FieldType.FLOAT, required=False, excel_unit="m", canonical_unit="m", description="Spatial reference measurement line offset", example_value=0.0),
            ],
            required=True,
            min_rows=1,
        ),
    ],
)

# 6. SCENARIOS WORKBOOK
SCENARIOS_WORKBOOK = WorkbookDef(
    workbook_type="SCENARIOS",
    default_filename="HEADWAY_SCENARIOS_v1.0.xlsx",
    description="Scenario definitions and targeted parameter overrides",
    worksheets=[
        METADATA_WORKSHEET,
        WorksheetDef(
            name="ScenarioDefinitions",
            description="Alternative scenario branches",
            columns=[
                ColumnDef("SCENARIO_ID", "scenario_id", FieldType.STRING, required=True, description="Unique scenario identifier", example_value="SCN_BASELINE"),
                ColumnDef("DESCRIPTION", "description", FieldType.STRING, required=True, description="Scenario description", example_value="Baseline 3-Aspect signalling"),
                ColumnDef("IS_BASELINE", "is_baseline", FieldType.BOOLEAN, required=False, default_value=False, description="Whether this scenario is the immutable baseline", example_value=True),
            ],
            required=True,
            min_rows=1,
        ),
        WorksheetDef(
            name="Overrides",
            description="Targeted parameter overrides for non-baseline scenarios",
            columns=[
                ColumnDef("SCENARIO_ID", "scenario_id", FieldType.STRING, required=True, description="Target scenario identifier", example_value="SCN_ALT_01"),
                ColumnDef("TARGET_DOMAIN", "target_domain", FieldType.STRING, required=True, allowed_values=["infrastructure", "rolling_stock", "signalling", "operations", "analysis"], description="Target domain", example_value="signalling"),
                ColumnDef("TARGET_OBJECT_ID", "target_object_id", FieldType.STRING, required=True, description="ID of object to modify", example_value="BLK_01"),
                ColumnDef("PARAMETER_NAME", "parameter_name", FieldType.STRING, required=True, description="Attribute name to override", example_value="overlap_m"),
                ColumnDef("OVERRIDE_VALUE", "override_value", FieldType.STRING, required=True, description="New value (string, number, or boolean)", example_value="100.0"),
                ColumnDef("JUSTIFICATION", "justification", FieldType.STRING, required=False, description="Engineering reason for override", example_value="Extend overlap for safety sensitivity"),
            ],
            required=False,
        ),
    ],
)

ALL_WORKBOOK_DEFS: Dict[str, WorkbookDef] = {
    "INFRASTRUCTURE": INFRASTRUCTURE_WORKBOOK,
    "SIGNALLING": SIGNALLING_WORKBOOK,
    "ROLLING_STOCK": ROLLING_STOCK_WORKBOOK,
    "OPERATIONS": OPERATIONS_WORKBOOK,
    "HEADWAY_ANALYSIS": HEADWAY_ANALYSIS_WORKBOOK,
    "SCENARIOS": SCENARIOS_WORKBOOK,
}


def get_workbook_def(wb_type: str) -> Optional[WorkbookDef]:
    """Retrieve authoritative workbook definition by type."""
    return ALL_WORKBOOK_DEFS.get(wb_type.strip().upper())
