"""Railway infrastructure & network topology engine package.

Strictly satisfies RHS-P02-001 (Milestone P02):
- Forward and reverse railway operations support across all components.
- Physical railway graph and node/link models with NetworkX.
- Route traversal engine with distance and physical position mapping.
- Engineering chainage mapping with reverse and multi-segment support.
- Gradient profiles with reverse sign inversion (+10‰ -> -10‰).
- Curvature profiles with non-negative radius invariance.
- Direction-aware speed restrictions and profiles.
- Switch and junction topology models.
- Station, platform, and stopping point geometry.
- Tunnel and TVS physical geometry with reverse entry/exit resolution.
- Multi-link and branching resource geometry utilities.
- Train-length geometry and footprint distribution utilities.
- Structured infrastructure validation using P01 findings.
- Preprocessing engine with direction-aware RouteProfiles.
- Visualization data adapters for both directions.
"""

from headway.infrastructure.adapters import InfrastructureVisualizerAdapter
from headway.infrastructure.alignment import (
    AlignmentError,
    CurvatureInterval,
    GradientInterval,
    RouteAlignmentProfile,
)
from headway.infrastructure.chainage import (
    ChainageError,
    ChainageSegment,
    EngineeringChainageModel,
)
from headway.infrastructure.direction import (
    DirectionPolicy,
    DirectionPolicyError,
    RunningDirection,
)
from headway.infrastructure.graph import (
    NetworkTopologyError,
    PhysicalNetworkGraph,
)
from headway.infrastructure.preprocessor import (
    InfrastructurePreprocessor,
    RouteProfile,
)
from headway.infrastructure.resources import (
    MultiLinkResourceGeometry,
    PhysicalResource,
    ResourceGeometryError,
)
from headway.infrastructure.route import (
    LinkTraversal,
    PositionMappingError,
    Route,
    RouteContinuityError,
    RouteEngine,
)
from headway.infrastructure.speed import (
    RouteSpeedProfile,
    SpeedInterval,
    SpeedProfileError,
    SpeedRestriction,
)
from headway.infrastructure.stations import (
    RoutePlatformStop,
    StationGeometryError,
    StationPlatformModel,
)
from headway.infrastructure.switches import (
    JunctionTopology,
    Switch,
    SwitchError,
    SwitchMovement,
    SwitchPosition,
)
from headway.infrastructure.train_geometry import (
    LinkOccupancy,
    TrainFootprint,
    TrainGeometry,
    TrainGeometryError,
)
from headway.infrastructure.tunnels import (
    RouteTVSSection,
    TunnelTVSModel,
    TVSGeometryError,
)
from headway.infrastructure.validator import (
    InfrastructureValidator,
)

__all__ = [
    # Direction
    "RunningDirection",
    "DirectionPolicy",
    "DirectionPolicyError",
    # Graph
    "PhysicalNetworkGraph",
    "NetworkTopologyError",
    # Route
    "Route",
    "LinkTraversal",
    "RouteEngine",
    "RouteContinuityError",
    "PositionMappingError",
    # Chainage
    "EngineeringChainageModel",
    "ChainageSegment",
    "ChainageError",
    # Alignment
    "RouteAlignmentProfile",
    "GradientInterval",
    "CurvatureInterval",
    "AlignmentError",
    # Speed
    "RouteSpeedProfile",
    "SpeedRestriction",
    "SpeedInterval",
    "SpeedProfileError",
    # Switches
    "Switch",
    "SwitchMovement",
    "SwitchPosition",
    "JunctionTopology",
    "SwitchError",
    # Stations
    "StationPlatformModel",
    "RoutePlatformStop",
    "StationGeometryError",
    # Tunnels & TVS
    "TunnelTVSModel",
    "RouteTVSSection",
    "TVSGeometryError",
    # Resources
    "MultiLinkResourceGeometry",
    "PhysicalResource",
    "ResourceGeometryError",
    # Train Geometry
    "TrainGeometry",
    "TrainFootprint",
    "LinkOccupancy",
    "TrainGeometryError",
    # Validation
    "InfrastructureValidator",
    # Preprocessor
    "InfrastructurePreprocessor",
    "RouteProfile",
    # Adapters
    "InfrastructureVisualizerAdapter",
]
