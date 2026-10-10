"""Headway calculation, blocking-time analysis, TVS constraints, capacity, and stochastic simulation subsystem.

Milestone P08 — Blocking-Time Analysis & Technical Headway Solver.
Milestone P09 — Multi-Train Dispatching & Operations.
Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis.
Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
"""

from headway.analysis.blocking_time import (
    BlockingTimeComponent,
    BlockingTimeDecomposition,
    BlockingTimeline,
    ResourceBlockingInterval,
    decompose_blocking_interval,
    extract_blocking_intervals_from_records,
)
from headway.analysis.bottleneck_migration import BottleneckAnalyzer
from headway.analysis.bottlenecks import (
    BottleneckClassification,
    classify_bottleneck,
    evaluate_slack_and_bottlenecks,
    rank_longest_occupations,
)
from headway.analysis.capacity import TheoreticalCapacityCalculator
from headway.analysis.capacity_consumption import CapacityConsumptionCalculator
from headway.analysis.capacity_models import (
    BottleneckCategory,
    BottleneckDiagnostic,
    BottleneckMigrationRecord,
    CapacityResult,
    CapacityType,
    MeasurementWindow,
    OperationalStabilityStatus,
    PlanningMarginMethod,
    ResourceUtilizationMetric,
    SensitivityPointResult,
    SensitivityStudyResult,
    StabilityEvaluation,
    TimetableCompressionResult,
)
from headway.analysis.conflict_detection import (
    ConflictDetector,
    ConflictType,
    ResourceConflict,
)
from headway.analysis.delays import (
    DelayCause,
    DelayIncident,
    DelayPropagationTracker,
    SecondaryPropagationNode,
    TrainDelaySummary,
)
from headway.analysis.distributions import (
    EmpiricalContinuousDistribution,
    EmpiricalDiscreteDistribution,
    ExponentialDistribution,
    LognormalDistribution,
    NormalDistribution,
    ProbabilityDistribution,
    TriangularDistribution,
    TruncatedNormalDistribution,
    UniformDistribution,
    create_distribution,
)
from headway.analysis.headway_results import (
    HeadwayResult,
    HeadwayValidationStatus,
    MixedTrafficHeadwayMatrix,
    StairwayBlockData,
)
from headway.analysis.headway_search import (
    IterativeHeadwaySearch,
    SearchIterationStep,
    SearchResult,
)
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.analysis.journey_time import (
    JourneyTimeAnalyzer,
    JourneyTimeDecomposition,
    OperationalKPIs,
)
from headway.analysis.mixed_traffic import MixedTrafficAnalyzer
from headway.analysis.monte_carlo import (
    MonteCarloExecutionResult,
    MonteCarloSimulationManager,
    ReplicationResult,
)
from headway.analysis.random_variables import (
    DisruptionType,
    DistributionType,
    OperationalDisruption,
    SamplingScope,
    StochasticVariableDefinition,
    TargetObjectType,
)
from headway.analysis.reliability import (
    CriterionEvaluationResult,
    ReliabilityCriterion,
    ReliabilityEvaluationResult,
    ReliabilityEvaluator,
)
from headway.analysis.resource_utilization import (
    ResourceUtilizationAnalyzer,
    merge_time_intervals,
    total_interval_duration,
)
from headway.analysis.saturation import CapacitySaturationSearch
from headway.analysis.sensitivity import SensitivityAnalyzer
from headway.analysis.stability import OperationalStabilityEvaluator
from headway.analysis.statistics import (
    StatisticalSummary,
    compute_mean_confidence_interval,
    compute_statistical_summary,
    compute_wilson_score_interval,
)
from headway.analysis.stochastic import (
    CommonRandomNumbersManager,
    CorrelationGroup,
    MasterSeedManager,
    StochasticParameterSampler,
)
from headway.analysis.stochastic_capacity import ReliabilityBasedCapacityCalculator
from headway.analysis.throughput import ThroughputCalculator
from headway.analysis.timetable_compression import TimetableCompressor, TrainPathStairway

__all__ = [
    # Blocking intervals & 7-component decomposition
    "BlockingTimeComponent",
    "BlockingTimeDecomposition",
    "ResourceBlockingInterval",
    "BlockingTimeline",
    "decompose_blocking_interval",
    "extract_blocking_intervals_from_records",
    # Conflict detection
    "ConflictType",
    "ResourceConflict",
    "ConflictDetector",
    # Bottleneck analysis & slack
    "BottleneckClassification",
    "classify_bottleneck",
    "evaluate_slack_and_bottlenecks",
    "rank_longest_occupations",
    # Results & Stairway
    "HeadwayValidationStatus",
    "StairwayBlockData",
    "HeadwayResult",
    "MixedTrafficHeadwayMatrix",
    # Solvers & Search
    "TechnicalHeadwaySolver",
    "IterativeHeadwaySearch",
    "SearchIterationStep",
    "SearchResult",
    "MixedTrafficAnalyzer",
    # P09 Delays & Journey Time
    "DelayCause",
    "DelayIncident",
    "SecondaryPropagationNode",
    "TrainDelaySummary",
    "DelayPropagationTracker",
    "JourneyTimeDecomposition",
    "OperationalKPIs",
    "JourneyTimeAnalyzer",
    # P10 Capacity Data Models & Enums
    "CapacityType",
    "PlanningMarginMethod",
    "OperationalStabilityStatus",
    "BottleneckCategory",
    "MeasurementWindow",
    "CapacityResult",
    "StabilityEvaluation",
    "ResourceUtilizationMetric",
    "BottleneckDiagnostic",
    "BottleneckMigrationRecord",
    "TimetableCompressionResult",
    "SensitivityPointResult",
    "SensitivityStudyResult",
    # P10 Engines & Analyzers
    "TheoreticalCapacityCalculator",
    "ThroughputCalculator",
    "OperationalStabilityEvaluator",
    "CapacitySaturationSearch",
    "ResourceUtilizationAnalyzer",
    "merge_time_intervals",
    "total_interval_duration",
    "TimetableCompressor",
    "TrainPathStairway",
    "CapacityConsumptionCalculator",
    "BottleneckAnalyzer",
    "SensitivityAnalyzer",
    # P11 Stochastic & Monte Carlo
    "TargetObjectType",
    "SamplingScope",
    "DistributionType",
    "DisruptionType",
    "StochasticVariableDefinition",
    "OperationalDisruption",
    "ProbabilityDistribution",
    "NormalDistribution",
    "TruncatedNormalDistribution",
    "LognormalDistribution",
    "UniformDistribution",
    "TriangularDistribution",
    "ExponentialDistribution",
    "EmpiricalDiscreteDistribution",
    "EmpiricalContinuousDistribution",
    "create_distribution",
    "MasterSeedManager",
    "CorrelationGroup",
    "CommonRandomNumbersManager",
    "StochasticParameterSampler",
    "StatisticalSummary",
    "compute_statistical_summary",
    "compute_mean_confidence_interval",
    "compute_wilson_score_interval",
    "ReliabilityCriterion",
    "CriterionEvaluationResult",
    "ReliabilityEvaluationResult",
    "ReliabilityEvaluator",
    "ReplicationResult",
    "MonteCarloExecutionResult",
    "MonteCarloSimulationManager",
    "ReliabilityBasedCapacityCalculator",
]
