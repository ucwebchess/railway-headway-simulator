"""Unit test suite for negative cases and error handling in Stochastic Simulation & Reliability (P11).

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- Invalid distribution parameters (std <= 0, scale <= 0, a >= b, mode outside [a, b], etc.)
- Empirical distribution errors (size mismatch, non-monotonicity, non-stochastic probabilities)
- Correlated variable and Cholesky validation failures (non-PSD, dimension mismatch, asymmetric)
- MasterSeedManager and CommonRandomNumbersManager edge cases
- Statistical summary edge cases (empty sequences, invalid confidence levels, Wilson interval bounds)
- Reliability criterion validation errors
- Monte Carlo simulation edge cases and failure resilience
"""

import math
import numpy as np
import pytest

from headway.analysis.distributions import (
    EmpiricalContinuousDistribution,
    EmpiricalDiscreteDistribution,
    ExponentialDistribution,
    LognormalDistribution,
    NormalDistribution,
    TriangularDistribution,
    TruncatedNormalDistribution,
    UniformDistribution,
    create_distribution,
)
from headway.analysis.random_variables import (
    DistributionType,
    SamplingScope,
    StochasticVariableDefinition,
    TargetObjectType,
)
from headway.analysis.stochastic import (
    CommonRandomNumbersManager,
    CorrelationGroup,
    MasterSeedManager,
    StochasticParameterSampler,
)
from headway.analysis.statistics import (
    StatisticalSummary,
    compute_mean_confidence_interval,
    compute_statistical_summary,
    compute_wilson_score_interval,
)
from headway.analysis.reliability import (
    CriterionEvaluationResult,
    ReliabilityCriterion,
    ReliabilityEvaluator,
)


class TestDistributionNegativeCases:
    """Test parameter validation and boundary errors for probability distributions."""

    def test_normal_distribution_negative_or_zero_std(self) -> None:
        with pytest.raises(ValueError, match="strictly positive and finite"):
            NormalDistribution(mean=10.0, std_dev=0.0)
        with pytest.raises(ValueError, match="strictly positive and finite"):
            NormalDistribution(mean=10.0, std_dev=-1.5)

    def test_truncated_normal_invalid_bounds(self) -> None:
        with pytest.raises(ValueError, match="must be strictly less than"):
            TruncatedNormalDistribution(mean=10.0, std_dev=2.0, lower_bound=15.0, upper_bound=10.0)
        with pytest.raises(ValueError, match="strictly positive and finite"):
            TruncatedNormalDistribution(mean=10.0, std_dev=0.0, lower_bound=5.0, upper_bound=15.0)

    def test_lognormal_invalid_parameters(self) -> None:
        with pytest.raises(ValueError, match="strictly positive and finite"):
            LognormalDistribution(mean_log=0.0, std_log=0.0)
        with pytest.raises(ValueError, match="strictly positive and finite"):
            LognormalDistribution(mean_log=0.0, std_log=-0.5)

    def test_uniform_invalid_bounds(self) -> None:
        with pytest.raises(ValueError, match="must be strictly less than"):
            UniformDistribution(min_val=10.0, max_val=10.0)
        with pytest.raises(ValueError, match="must be strictly less than"):
            UniformDistribution(min_val=20.0, max_val=10.0)

    def test_triangular_invalid_parameters(self) -> None:
        with pytest.raises(ValueError, match="must be strictly less than"):
            TriangularDistribution(min_val=10.0, mode_val=10.0, max_val=10.0)
        with pytest.raises(ValueError, match="must be within"):
            TriangularDistribution(min_val=10.0, mode_val=5.0, max_val=20.0)
        with pytest.raises(ValueError, match="must be within"):
            TriangularDistribution(min_val=10.0, mode_val=25.0, max_val=20.0)

    def test_exponential_invalid_rate(self) -> None:
        with pytest.raises(ValueError, match="Rate must be strictly positive"):
            ExponentialDistribution(rate=0.0)
        with pytest.raises(ValueError, match="Rate must be strictly positive"):
            ExponentialDistribution(rate=-1.0)

    def test_empirical_discrete_invalid_inputs(self) -> None:
        # Mismatched lengths
        with pytest.raises(ValueError, match="Lengths mismatch"):
            EmpiricalDiscreteDistribution(values=[1.0, 2.0], probabilities=[1.0])
        # Empty inputs
        with pytest.raises(ValueError, match="must not be empty"):
            EmpiricalDiscreteDistribution(values=[], probabilities=[])
        # Negative probability
        with pytest.raises(ValueError, match="Probabilities must be non-negative and finite"):
            EmpiricalDiscreteDistribution(values=[1.0, 2.0], probabilities=[-0.1, 1.1])
        # Probabilities not summing to 1
        with pytest.raises(ValueError, match="Probabilities must sum to 1.0"):
            EmpiricalDiscreteDistribution(values=[1.0, 2.0], probabilities=[0.3, 0.3])

    def test_empirical_continuous_invalid_inputs(self) -> None:
        # Too few points
        with pytest.raises(ValueError, match="requires at least 2 distinct sample values"):
            EmpiricalContinuousDistribution(sample_values=[10.0])
        # Mismatched lengths
        with pytest.raises(ValueError, match="must have equal lengths"):
            EmpiricalContinuousDistribution(sample_values=[10.0, 20.0], cumulative_probabilities=[0.0])
        # Non-monotonic CDF
        with pytest.raises(ValueError, match="monotonically non-decreasing"):
            EmpiricalContinuousDistribution(sample_values=[10.0, 20.0], cumulative_probabilities=[0.8, 0.2])
        # CDF outside bounds
        with pytest.raises(ValueError, match="monotonically non-decreasing"):
            EmpiricalContinuousDistribution(sample_values=[10.0, 20.0], cumulative_probabilities=[-0.1, 1.0])

    def test_create_distribution_missing_parameters(self) -> None:
        with pytest.raises(ValueError, match="Missing required parameter"):
            create_distribution(DistributionType.NORMAL, {"mean": 10.0})
        with pytest.raises(ValueError, match="Missing required parameter"):
            create_distribution(DistributionType.UNIFORM, {"min_val": 10.0})


class TestCorrelationNegativeCases:
    """Test validation errors in correlation matrices and Gaussian copula."""

    def test_correlation_dimension_mismatch(self) -> None:
        mat = np.array([[1.0, 0.5], [0.5, 1.0]])
        with pytest.raises(ValueError, match="must match variable count"):
            CorrelationGroup(
                group_id="GRP_ERR",
                variable_ids=["V1", "V2", "V3"],  # 3 variables, 2x2 matrix
                correlation_matrix=mat,
            )

    def test_correlation_non_symmetric_matrix(self) -> None:
        mat = np.array([[1.0, 0.6], [0.4, 1.0]])  # asymmetric
        with pytest.raises(ValueError, match="must be symmetric"):
            CorrelationGroup(
                group_id="GRP_ASYM",
                variable_ids=["V1", "V2"],
                correlation_matrix=mat,
            )

    def test_correlation_invalid_diagonal(self) -> None:
        mat = np.array([[0.9, 0.5], [0.5, 1.0]])  # diagonal not 1.0
        with pytest.raises(ValueError, match="must be exactly 1.0"):
            CorrelationGroup(
                group_id="GRP_DIAG",
                variable_ids=["V1", "V2"],
                correlation_matrix=mat,
            )

    def test_correlation_non_positive_semi_definite(self) -> None:
        # A 3x3 matrix that is symmetric with 1 on diag, but not PSD (min eigenvalue < -0.1)
        mat = np.array([
            [1.0, 0.9, 0.9],
            [0.9, 1.0, -0.9],
            [0.9, -0.9, 1.0],
        ])
        with pytest.raises(ValueError, match="positive semi-definite"):
            CorrelationGroup(
                group_id="GRP_NOT_PSD",
                variable_ids=["V1", "V2", "V3"],
                correlation_matrix=mat,
            )


class TestRNGAndSeedNegativeCases:
    """Test MasterSeedManager and CommonRandomNumbersManager error handling."""

    def test_negative_master_seed(self) -> None:
        with pytest.raises(ValueError, match="Master seed must be non-negative"):
            MasterSeedManager(master_seed=-42)

    def test_invalid_replication_index(self) -> None:
        mgr = MasterSeedManager(master_seed=42)
        with pytest.raises(ValueError, match="Replication index must be non-negative"):
            mgr.get_replication_generator(replication_index=-1)

    def test_sampler_undefined_variable(self) -> None:
        sampler = StochasticParameterSampler([])
        rng = np.random.default_rng(42)
        with pytest.raises(KeyError, match="not found or disabled"):
            sampler.sample_variable("NON_EXISTENT", "ENTITY_1", rng)


class TestStatisticalSummaryNegativeCases:
    """Test StatisticalSummary and confidence interval calculations under boundary conditions."""

    def test_empty_sample_sequence(self) -> None:
        summary = compute_statistical_summary([], metric_name="EMPTY")
        assert summary.sample_count == 0
        assert summary.details.get("warning") == "INSUFFICIENT_DATA"

    def test_all_nan_sample_sequence(self) -> None:
        summary = compute_statistical_summary([float("nan"), float("inf"), -float("inf")], metric_name="ALL_NAN")
        assert summary.sample_count == 0
        assert summary.details.get("warning") == "INSUFFICIENT_DATA"

    def test_single_sample_confidence_interval(self) -> None:
        # Single sample has std_dev = 0
        summary = compute_statistical_summary([42.0], metric_name="SINGLE")
        assert summary.sample_count == 1
        assert summary.mean == 42.0
        assert summary.std_dev == 0.0

    def test_invalid_confidence_level(self) -> None:
        with pytest.raises(ValueError, match="Confidence level must be strictly between 0 and 1"):
            compute_mean_confidence_interval([1.0, 2.0, 3.0], confidence_level=0.0)
        with pytest.raises(ValueError, match="Confidence level must be strictly between 0 and 1"):
            compute_mean_confidence_interval([1.0, 2.0, 3.0], confidence_level=1.0)
        with pytest.raises(ValueError, match="Confidence level must be strictly between 0 and 1"):
            compute_wilson_score_interval(success_count=5, total_count=10, confidence_level=1.5)

    def test_wilson_score_invalid_inputs(self) -> None:
        with pytest.raises(ValueError, match="Total trials must be non-negative"):
            compute_wilson_score_interval(success_count=0, total_count=-5)
        with pytest.raises(ValueError, match="Invalid success_count"):
            compute_wilson_score_interval(success_count=-1, total_count=10)
        with pytest.raises(ValueError, match="Invalid success_count"):
            compute_wilson_score_interval(success_count=15, total_count=10)


class TestReliabilityEvaluatorNegativeCases:
    """Test validation errors for operational reliability criteria and evaluator."""

    def test_invalid_comparison_operator(self) -> None:
        with pytest.raises(ValueError, match="Unsupported comparison operator"):
            ReliabilityCriterion(
                criterion_id="C_ERR",
                metric_name="PUNCTUALITY_PERCENT",
                comparison_operator="==",
                threshold_value=90.0,
            )

    def test_unsupported_metric_name(self) -> None:
        crit = ReliabilityCriterion(
            criterion_id="C_UNSUPP",
            metric_name="UNSUPPORTED_METRIC_XYZ",
            comparison_operator=">=",
            threshold_value=100.0,
        )
        res = ReliabilityEvaluator.evaluate_replications(
            criteria=[crit],
            arrival_delays_s=[10.0, 20.0],
            tvs_waitings_s=[0.0, 0.0],
            max_queues=[0, 0],
            throughputs_tph=[24.0, 24.0],
        )
        assert not res.all_criteria_passed
        assert not res.criterion_results["C_UNSUPP"].passed
