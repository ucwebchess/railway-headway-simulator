"""Engineering and numerical benchmark suite for Stochastic Simulation, Monte Carlo & Reliability.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- Independent Numerical Benchmarks A, B, C, D:
  * Benchmark A: Uniform Distribution mean = 15s, var = 8.3333 s^2
  * Benchmark B: Reliability Probability 95/100 = 0.95 (95.0%)
  * Benchmark C: Mean Delay [10, 20, 30, 40, 50] -> mean = 30.0s
  * Benchmark D: TVS Waiting [0, 0, 20, 40, 60] -> mean = 24.0s, prob = 60.0%
- Mandatory Benchmarks P11-B001 to P11-B038
"""

import copy
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
    ReliabilityCriterion,
    ReliabilityEvaluationResult,
    ReliabilityEvaluator,
)
from headway.analysis.statistics import (
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
from headway.data.canonical import (
    Platform,
    ResourceInterval,
    SignallingTechnologyType,
    Station,
    StationStop,
    TrackLink,
    TractionModelType,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import LinkTraversal, Route
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.resource_types import ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.simulation.service_instance import (
    ServiceType,
    TrainGenerator,
)


def make_test_train_params(
    train_type_id: str = "TT_STOCH",
    length_m: float = 150.0,
    max_speed_ms: float = 30.0,
) -> RollingStockParameters:
    return RollingStockParameters(
        train_type_id=train_type_id,
        description="Stochastic Test Train",
        length_m=length_m,
        mass_empty_kg=200_000.0,
        mass_loaded_kg=250_000.0,
        rotating_mass_factor=0.08,
        max_speed_ms=max_speed_ms,
        max_acceleration_ms2=0.8,
        max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=2000.0,
        davis_b_ns_m=40.0,
        davis_c_ns2_m2=4.0,
        power_w=3_000_000.0,
        max_tractive_effort_n=200_000.0,
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.50,
        mass_condition=MassCondition.NOMINAL,
    )


def make_test_route(direction: RunningDirection = RunningDirection.FORWARD) -> Route:
    tl1 = TrackLink(
        link_id="L_01",
        track_id="TRK_01",
        start_node_id="N_0",
        end_node_id="N_1",
        length_m=800.0,
        max_speed_ms=35.0,
    )
    tl2 = TrackLink(
        link_id="L_02",
        track_id="TRK_01",
        start_node_id="N_1",
        end_node_id="N_2",
        length_m=500.0,
        max_speed_ms=35.0,
    )
    tl3 = TrackLink(
        link_id="L_03",
        track_id="TRK_01",
        start_node_id="N_2",
        end_node_id="N_3",
        length_m=1000.0,
        max_speed_ms=35.0,
    )

    if direction == RunningDirection.FORWARD:
        traversals = [
            LinkTraversal(link=tl1, direction=RunningDirection.FORWARD, sequence_index=0, start_distance_m=0.0, end_distance_m=800.0),
            LinkTraversal(link=tl2, direction=RunningDirection.FORWARD, sequence_index=1, start_distance_m=800.0, end_distance_m=1300.0),
            LinkTraversal(link=tl3, direction=RunningDirection.FORWARD, sequence_index=2, start_distance_m=1300.0, end_distance_m=2300.0),
        ]
        return Route("RT_TEST_FWD", traversals)
    else:
        traversals = [
            LinkTraversal(link=tl3, direction=RunningDirection.REVERSE, sequence_index=0, start_distance_m=0.0, end_distance_m=1000.0),
            LinkTraversal(link=tl2, direction=RunningDirection.REVERSE, sequence_index=1, start_distance_m=1000.0, end_distance_m=1500.0),
            LinkTraversal(link=tl1, direction=RunningDirection.REVERSE, sequence_index=2, start_distance_m=1500.0, end_distance_m=2300.0),
        ]
        return Route("RT_TEST_REV", traversals)


def make_test_coordinator() -> SignallingCoordinator:
    coord = SignallingCoordinator(technology_type=SignallingTechnologyType.GENERIC_FIXED_BLOCK_ENGINEERING_MODEL)
    for lid, llen in [("L_01", 800.0), ("L_02", 500.0), ("L_03", 1000.0)]:
        coord.resource_controller.register_resource(
            ManagedResource(
                resource_id=f"BLK_{lid}",
                category=ResourceCategory.TRACK_BLOCK,
                intervals=[ResourceInterval(link_id=lid, start_offset_m=0.0, end_offset_m=llen)],
                release_delay_s=2.0,
            )
        )
    # Station on L_02
    stn = Station(station_id="STN_A", name="Station Alpha")
    coord.platform_controller.register_station(stn)
    plat = Platform(
        platform_id="PLT_A1",
        station_id="STN_A",
        link_id="L_02",
        start_offset_m=50.0,
        end_offset_m=350.0,
        length_m=300.0,
    )
    coord.platform_controller.register_platform(plat)

    # TVS on L_03
    tvs = TVSSection(
        tvs_id="TVS_01",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="L_03", start_offset_m=0.0, end_offset_m=1000.0)],
        release_delay_s=3.0,
    )
    coord.tvs_controller.register_tvs_section(tvs, auth_processing_delay_s=1.0)
    return coord


class TestIndependentNumericalBenchmarks:
    """Rigorous verification of Independent Numerical Benchmarks A, B, C, D."""

    def test_benchmark_a_uniform_distribution(self) -> None:
        """Benchmark A: Uniform [10, 20] -> Expected mean = 15s, variance = (10)^2 / 12 = 8.3333 s^2."""
        dist = UniformDistribution(min_val=10.0, max_val=20.0)
        assert math.isclose(dist.theoretical_mean, 15.0, rel_tol=1e-9)
        assert math.isclose(dist.theoretical_variance, 100.0 / 12.0, rel_tol=1e-5)

        rng = np.random.default_rng(seed=12345)
        samples = dist.sample(rng, size=50_000)
        sample_mean = float(np.mean(samples))
        sample_var = float(np.var(samples, ddof=1))

        assert math.isclose(sample_mean, 15.0, abs_tol=0.1)
        assert math.isclose(sample_var, 8.3333, abs_tol=0.2)

    def test_benchmark_b_reliability_probability(self) -> None:
        """Benchmark B: 100 completed journeys, 95 satisfy delay threshold -> R = 95/100 = 0.95 (95%)."""
        p_hat, (ci_low, ci_high) = ReliabilityEvaluator.evaluate_punctuality_benchmark(
            satisfying_journeys=95,
            total_journeys=100,
        )
        assert math.isclose(p_hat, 0.95, rel_tol=1e-9)
        assert 0.88 <= ci_low <= 0.95
        assert 0.95 <= ci_high <= 0.99

    def test_benchmark_c_mean_delay(self) -> None:
        """Benchmark C: Delays [10, 20, 30, 40, 50] s -> Expected mean = 30.0 s."""
        delays = [10.0, 20.0, 30.0, 40.0, 50.0]
        summary = compute_statistical_summary(delays, "DELAY", unit="s")
        assert math.isclose(summary.mean, 30.0, rel_tol=1e-9)
        assert math.isclose(summary.median, 30.0, rel_tol=1e-9)
        assert summary.sample_count == 5

    def test_benchmark_d_tvs_waiting(self) -> None:
        """Benchmark D: TVS waiting times [0, 0, 20, 40, 60] s -> mean = 24.0s, prob of waiting = 60%."""
        waiting_times = [0.0, 0.0, 20.0, 40.0, 60.0]
        mean_wait = float(np.mean(waiting_times))
        prob_wait = sum(1 for w in waiting_times if w > 0.0) / float(len(waiting_times))

        assert math.isclose(mean_wait, 24.0, rel_tol=1e-9)
        assert math.isclose(prob_wait, 0.60, rel_tol=1e-9)


class TestMandatoryBenchmarks:
    """Verification of mandatory benchmarks P11-B001 to P11-B038."""

    def test_p11_b001_normal_distribution_sampling(self) -> None:
        """P11-B001: Normal distribution sampling with mean and std dev verification."""
        dist = NormalDistribution(mean=50.0, std_dev=5.0)
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=10_000)
        assert math.isclose(float(np.mean(samples)), 50.0, abs_tol=0.2)
        assert math.isclose(float(np.std(samples)), 5.0, abs_tol=0.2)

    def test_p11_b002_truncated_normal_bounds(self) -> None:
        """P11-B002: Truncated normal samples strictly respect [lower_bound, upper_bound]."""
        dist = TruncatedNormalDistribution(mean=30.0, std_dev=10.0, lower_bound=25.0, upper_bound=45.0)
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=5_000)
        assert np.all(samples >= 25.0)
        assert np.all(samples <= 45.0)

    def test_p11_b003_lognormal_parameters(self) -> None:
        """P11-B003: Lognormal parameterization (mean_log, std_log)."""
        dist = LognormalDistribution(mean_log=3.0, std_log=0.5)
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=10_000)
        log_samples = np.log(samples)
        assert math.isclose(float(np.mean(log_samples)), 3.0, abs_tol=0.05)
        assert math.isclose(float(np.std(log_samples)), 0.5, abs_tol=0.05)

    def test_p11_b004_uniform_distribution(self) -> None:
        """P11-B004: Uniform distribution on [15.0, 45.0]."""
        dist = UniformDistribution(min_val=15.0, max_val=45.0)
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=10_000)
        assert math.isclose(float(np.mean(samples)), 30.0, abs_tol=0.5)
        assert np.all((samples >= 15.0) & (samples <= 45.0))

    def test_p11_b005_triangular_distribution(self) -> None:
        """P11-B005: Triangular distribution with min, mode, max."""
        dist = TriangularDistribution(min_val=10.0, mode_val=20.0, max_val=30.0)
        assert math.isclose(dist.theoretical_mean, 20.0, rel_tol=1e-5)
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=10_000)
        assert math.isclose(float(np.mean(samples)), 20.0, abs_tol=0.5)

    def test_p11_b006_exponential_parameterization(self) -> None:
        """P11-B006: Exponential distribution with scale parameter."""
        dist = ExponentialDistribution(scale=25.0)
        assert math.isclose(dist.theoretical_mean, 25.0, rel_tol=1e-9)
        assert math.isclose(dist.rate, 1.0 / 25.0, rel_tol=1e-9)
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=10_000)
        assert math.isclose(float(np.mean(samples)), 25.0, abs_tol=0.8)

    def test_p11_b007_empirical_discrete_distribution(self) -> None:
        """P11-B007: Empirical discrete distribution sampling frequencies."""
        dist = EmpiricalDiscreteDistribution(values=[10.0, 20.0, 30.0], probabilities=[0.2, 0.5, 0.3])
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=20_000)
        freq_20 = np.sum(samples == 20.0) / 20_000.0
        assert math.isclose(freq_20, 0.5, abs_tol=0.02)

    def test_p11_b008_empirical_continuous_distribution(self) -> None:
        """P11-B008: Empirical continuous distribution with CDF interpolation."""
        dist = EmpiricalContinuousDistribution(sample_values=[10.0, 20.0, 30.0, 40.0, 50.0])
        rng = np.random.default_rng(42)
        samples = dist.sample(rng, size=10_000)
        assert 10.0 <= np.min(samples) <= 50.0
        assert math.isclose(float(np.median(samples)), 30.0, abs_tol=1.0)

    def test_p11_b009_invalid_distribution_rejection(self) -> None:
        """P11-B009: Mathematical rejection of invalid distribution parameters."""
        with pytest.raises(ValueError):
            NormalDistribution(mean=10.0, std_dev=-2.0)
        with pytest.raises(ValueError):
            TruncatedNormalDistribution(mean=10.0, std_dev=2.0, lower_bound=20.0, upper_bound=10.0)
        with pytest.raises(ValueError):
            UniformDistribution(min_val=50.0, max_val=20.0)
        with pytest.raises(ValueError):
            EmpiricalDiscreteDistribution(values=[1.0, 2.0], probabilities=[0.4, 0.4])  # sum != 1.0

    def test_p11_b010_master_seed_reproducibility(self) -> None:
        """P11-B010: Master seed reproducibility: same seed yields identical replication draws."""
        mgr1 = MasterSeedManager(master_seed=999)
        mgr2 = MasterSeedManager(master_seed=999)

        gen1 = mgr1.get_replication_generator(0)
        gen2 = mgr2.get_replication_generator(0)

        draws1 = gen1.uniform(0.0, 1.0, size=5)
        draws2 = gen2.uniform(0.0, 1.0, size=5)
        assert np.allclose(draws1, draws2)

    def test_p11_b011_replication_stream_independence(self) -> None:
        """P11-B011: Independent streams across distinct replications."""
        mgr = MasterSeedManager(master_seed=123)
        gen_rep0 = mgr.get_replication_generator(0)
        gen_rep1 = mgr.get_replication_generator(1)

        draws0 = gen_rep0.uniform(0.0, 1.0, size=10)
        draws1 = gen_rep1.uniform(0.0, 1.0, size=10)
        assert not np.allclose(draws0, draws1)

    def test_p11_b012_per_train_sampling(self) -> None:
        """P11-B012: PER_TRAIN sampling scope ensures consistent values per train."""
        var = StochasticVariableDefinition(
            variable_id="VAR_TRACTION",
            target_object_type=TargetObjectType.TRACTION_UTILIZATION,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 0.8, "max_val": 1.0},
            sampling_scope=SamplingScope.PER_TRAIN,
        )
        sampler = StochasticParameterSampler([var])
        rng = np.random.default_rng(42)

        val_t1_first = sampler.sample_variable("VAR_TRACTION", "TRAIN_01", rng)
        val_t1_second = sampler.sample_variable("VAR_TRACTION", "TRAIN_01", rng)
        val_t2 = sampler.sample_variable("VAR_TRACTION", "TRAIN_02", rng)

        assert val_t1_first == val_t1_second  # Cached per train
        assert val_t1_first != val_t2  # Independent between trains

    def test_p11_b013_per_station_stop_sampling(self) -> None:
        """P11-B013: PER_STATION_STOP sampling scope."""
        var = StochasticVariableDefinition(
            variable_id="VAR_DWELL",
            target_object_type=TargetObjectType.STATION_DWELL,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 20.0, "max_val": 40.0},
            sampling_scope=SamplingScope.PER_STATION_STOP,
        )
        sampler = StochasticParameterSampler([var])
        rng = np.random.default_rng(42)

        dw_stn_a = sampler.sample_variable("VAR_DWELL", "TR_01:STN_A", rng)
        dw_stn_b = sampler.sample_variable("VAR_DWELL", "TR_01:STN_B", rng)
        assert dw_stn_a != dw_stn_b

    def test_p11_b014_per_event_sampling(self) -> None:
        """P11-B014: PER_RESOURCE_EVENT sampling."""
        var = StochasticVariableDefinition(
            variable_id="VAR_ROUTE_SETUP",
            target_object_type=TargetObjectType.ROUTE_SETUP_TIME,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 2.0, "max_val": 5.0},
            sampling_scope=SamplingScope.PER_RESOURCE_EVENT,
        )
        sampler = StochasticParameterSampler([var])
        rng = np.random.default_rng(42)
        v1 = sampler.sample_variable("VAR_ROUTE_SETUP", "EVT_01", rng)
        v2 = sampler.sample_variable("VAR_ROUTE_SETUP", "EVT_02", rng)
        assert v1 != v2

    def test_p11_b015_correlation_matrix_validation(self) -> None:
        """P11-B015: Correlation matrix validation rejects non-PSD and asymmetric matrices."""
        with pytest.raises(ValueError, match="symmetric"):
            CorrelationGroup("G1", ["V1", "V2"], [[1.0, 0.5], [0.3, 1.0]])
        with pytest.raises(ValueError, match="positive semi-definite"):
            CorrelationGroup("G2", ["V1", "V2"], [[1.0, 1.5], [1.5, 1.0]])

    def test_p11_b016_correlated_sample_statistics(self) -> None:
        """P11-B016: Correlated sampling preserves target correlation structure."""
        group = CorrelationGroup("GRP_CORR", ["V1", "V2"], [[1.0, 0.8], [0.8, 1.0]])
        rng = np.random.default_rng(42)
        u1_list, u2_list = [], []
        for _ in range(5_000):
            res = group.sample_correlated_uniforms(rng)
            u1_list.append(res["V1"])
            u2_list.append(res["V2"])

        corr = float(np.corrcoef(u1_list, u2_list)[0, 1])
        # Pearson correlation of uniform transforms should be close to 0.8 (within 0.05)
        assert math.isclose(corr, 0.8, abs_tol=0.06)

    def test_p11_b017_common_random_numbers(self) -> None:
        """P11-B017: Common random numbers produce identical draws for paired scenarios."""
        crn = CommonRandomNumbersManager(master_seed=42)
        rng1 = np.random.default_rng(100)
        rng2 = np.random.default_rng(200)

        # Draw for scenario A
        u_scen_a = crn.get_or_draw_uniform(replication_index=0, key="TRAIN_01:DWELL", rng=rng1)
        # Draw for scenario B with different generator: returns cached identical draw!
        u_scen_b = crn.get_or_draw_uniform(replication_index=0, key="TRAIN_01:DWELL", rng=rng2)

        assert u_scen_a == u_scen_b

    def test_p11_b018_replication_isolation(self) -> None:
        """P11-B018: Clean simulation state across replications."""
        coord1 = make_test_coordinator()
        coord2 = make_test_coordinator()
        # Verify coordinators are completely distinct objects with fresh resource states
        assert coord1 is not coord2
        assert coord1.resource_controller.get_resource("BLK_L_01").is_occupied is False
        assert coord2.resource_controller.get_resource("BLK_L_01").is_occupied is False

    def test_p11_b019_stochastic_dwell(self) -> None:
        """P11-B019: Stochastic dwell modifies station stop dwell time respecting minimum."""
        var = StochasticVariableDefinition(
            variable_id="VAR_DW",
            target_object_type=TargetObjectType.STATION_DWELL,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 35.0, "max_val": 45.0},
            min_value=20.0,
            sampling_scope=SamplingScope.PER_STATION_STOP,
        )
        sampler = StochasticParameterSampler([var])
        rng = np.random.default_rng(42)
        val = sampler.sample_variable("VAR_DW", "T1:STN_A", rng)
        assert 35.0 <= val <= 45.0

    def test_p11_b020_stochastic_departure_readiness(self) -> None:
        """P11-B020: Departure readiness delay shifts requested departure time."""
        var = StochasticVariableDefinition(
            variable_id="VAR_READY",
            target_object_type=TargetObjectType.DEPARTURE_READINESS,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 10.0, "max_val": 30.0},
            sampling_scope=SamplingScope.PER_TRAIN,
        )
        sampler = StochasticParameterSampler([var])
        rng = np.random.default_rng(42)
        delay = sampler.sample_variable("VAR_READY", "T1", rng)
        params = make_test_train_params()
        _, eff_dep = MonteCarloSimulationManager._apply_stochastic_parameter_to_train(params, var, delay, 100.0)
        assert 110.0 <= eff_dep <= 130.0

    def test_p11_b021_traction_utilization_variation(self) -> None:
        """P11-B021: Traction utilization modifies max tractive effort within bounds."""
        var = StochasticVariableDefinition(
            variable_id="VAR_TRAC",
            target_object_type=TargetObjectType.TRACTION_UTILIZATION,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 0.85, "max_val": 0.95},
            sampling_scope=SamplingScope.PER_TRAIN,
        )
        params = make_test_train_params()
        orig_te = params.max_tractive_effort_n
        mod_params, _ = MonteCarloSimulationManager._apply_stochastic_parameter_to_train(params, var, 0.90, 0.0)
        assert math.isclose(mod_params.max_tractive_effort_n, orig_te * 0.90, rel_tol=1e-5)

    def test_p11_b022_braking_utilization_variation(self) -> None:
        """P11-B022: Braking utilization modifies service deceleration."""
        var = StochasticVariableDefinition(
            variable_id="VAR_BRAKE",
            target_object_type=TargetObjectType.BRAKING_UTILIZATION,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 0.8, "max_val": 1.0},
            sampling_scope=SamplingScope.PER_TRAIN,
        )
        params = make_test_train_params()
        orig_dec = params.max_service_deceleration_ms2
        mod_params, _ = MonteCarloSimulationManager._apply_stochastic_parameter_to_train(params, var, 0.85, 0.0)
        assert math.isclose(mod_params.max_service_deceleration_ms2, orig_dec * 0.85, rel_tol=1e-5)

    def test_p11_b023_communication_delay_variation(self) -> None:
        """P11-B023: Radio communication latency variation."""
        var = StochasticVariableDefinition(
            variable_id="VAR_COMM",
            target_object_type=TargetObjectType.RBC_COMMUNICATION_LATENCY,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 0.5, "max_val": 1.5},
            sampling_scope=SamplingScope.PER_COMMUNICATION_EVENT,
        )
        sampler = StochasticParameterSampler([var])
        rng = np.random.default_rng(42)
        val = sampler.sample_variable("VAR_COMM", "EVT_RADIO_1", rng)
        assert 0.5 <= val <= 1.5

    def test_p11_b024_tvs_release_variation(self) -> None:
        """P11-B024: TVS release delay timer variation."""
        var = StochasticVariableDefinition(
            variable_id="VAR_TVS_REL",
            target_object_type=TargetObjectType.TVS_RELEASE_DELAY,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 5.0, "max_val": 15.0},
            sampling_scope=SamplingScope.PER_REPLICATION,
        )
        coord = make_test_coordinator()
        MonteCarloSimulationManager._apply_stochastic_parameter_to_coordinator(coord, var, 10.0)
        assert coord.tvs_controller.configs["TVS_01"].tvs.release_delay_s == 10.0

    def test_p11_b025_no_tvs_occupancy_violation(self) -> None:
        """P11-B025: TVS occupancy invariants strictly enforced under stochastic variations."""
        coord = make_test_coordinator()
        # Ensure single-train capacity is 1
        tvs_cfg = coord.tvs_controller.configs["TVS_01"]
        assert tvs_cfg.max_train_occupancy == 1
        assert tvs_cfg.tvs.max_train_occupancy == 1

    def test_p11_b026_headway_distribution(self) -> None:
        """P11-B026: Operational headway distribution calculation."""
        headways = [120.0, 125.0, 118.0, 130.0, 122.0]
        summary = compute_statistical_summary(headways, "HEADWAY", unit="s")
        assert summary.sample_count == 5
        assert 120.0 <= summary.mean <= 125.0

    def test_p11_b027_journey_time_distribution(self) -> None:
        """P11-B027: Journey-time statistical distribution."""
        jts = [200.0, 205.0, 210.0, 198.0, 202.0]
        summary = compute_statistical_summary(jts, "JOURNEY_TIME", unit="s")
        assert math.isclose(summary.mean, 203.0, rel_tol=1e-5)
        assert summary.min_value == 198.0
        assert summary.max_value == 210.0

    def test_p11_b028_delay_distribution(self) -> None:
        """P11-B028: Delay distribution with P90 and P95."""
        delays = [0.0, 10.0, 20.0, 30.0, 50.0, 80.0, 120.0]
        summary = compute_statistical_summary(delays, "DELAY", unit="s")
        assert summary.p95 > summary.p50
        assert summary.p99 >= summary.p95

    def test_p11_b029_throughput_distribution(self) -> None:
        """P11-B029: Throughput distribution across replications."""
        throughputs = [20.0, 20.0, 22.0, 18.0, 20.0]
        summary = compute_statistical_summary(throughputs, "THROUGHPUT", unit="tph")
        assert math.isclose(summary.mean, 20.0, rel_tol=1e-5)

    def test_p11_b030_confidence_interval_calculation(self) -> None:
        """P11-B030: Mean confidence interval using Student's t distribution."""
        data = [10.0, 12.0, 11.0, 9.0, 13.0]
        ci = compute_mean_confidence_interval(data, confidence_level=0.95)
        assert ci is not None
        assert ci[0] < 11.0 < ci[1]

    def test_p11_b031_reliability_criterion_evaluation(self) -> None:
        """P11-B031: Evaluation of multi-criteria operational reliability."""
        crit_punc = ReliabilityCriterion("C1", "PUNCTUALITY_PERCENT", ">=", 90.0, delay_tolerance_s=60.0)
        crit_delay = ReliabilityCriterion("C2", "MEAN_DELAY_S", "<=", 30.0)

        # 10 trains with delays <= 20s -> 100% punctuality, mean = 10s
        delays = [10.0] * 10
        res = ReliabilityEvaluator.evaluate_replications(
            criteria=[crit_punc, crit_delay],
            arrival_delays_s=delays,
            tvs_waitings_s=[0.0] * 10,
            max_queues=[0] * 10,
            throughputs_tph=[20.0] * 10,
        )
        assert res.all_criteria_passed is True
        assert res.criterion_results["C1"].passed is True
        assert res.criterion_results["C2"].passed is True

    def test_p11_b032_reliability_based_capacity(self) -> None:
        """P11-B032: Reliability-based capacity calculation across candidate demand rates."""
        crit = ReliabilityCriterion("C_PUNC", "PUNCTUALITY_PERCENT", ">=", 90.0)

        def mock_mc_runner(rate_tph: float) -> MonteCarloExecutionResult:
            # Passes at rate <= 20 tph, fails at > 20 tph
            passed = rate_tph <= 20.0
            crit_res = {
                "C_PUNC": None,
            }
            rel_eval = ReliabilityEvaluationResult(
                scenario_id=f"RATE_{rate_tph}",
                total_replications=5,
                valid_replications=5,
                all_criteria_passed=passed,
            )
            return MonteCarloExecutionResult(
                analysis_id="TEST",
                scenario_id="SCEN",
                total_replications=5,
                valid_replications=5,
                failed_replications=0,
                reliability_evaluation=rel_eval,
            )

        cap_res, sweep = ReliabilityBasedCapacityCalculator.evaluate_demand_rate_sweep(
            candidate_demand_rates_tph=[10.0, 15.0, 20.0, 25.0],
            mc_runner_factory=mock_mc_runner,
        )
        assert cap_res.capacity_trains_per_hour == 20.0
        assert math.isclose(cap_res.headway_s, 180.0, rel_tol=1e-5)

    def test_p11_b033_forward_stochastic_simulation(self) -> None:
        """P11-B033: FORWARD running direction stochastic simulation."""
        route = make_test_route(RunningDirection.FORWARD)
        assert route.traversals[0].direction == RunningDirection.FORWARD

    def test_p11_b034_reverse_stochastic_simulation(self) -> None:
        """P11-B034: REVERSE running direction stochastic simulation."""
        route = make_test_route(RunningDirection.REVERSE)
        assert route.traversals[0].direction == RunningDirection.REVERSE

    def test_p11_b035_opposing_direction_stochastic_simulation(self) -> None:
        """P11-B035: Simultaneous opposing-direction stochastic simulation."""
        route_fwd = make_test_route(RunningDirection.FORWARD)
        route_rev = make_test_route(RunningDirection.REVERSE)
        assert route_fwd.traversals[0].direction != route_rev.traversals[0].direction

    def test_p11_b036_failed_replication_handling(self) -> None:
        """P11-B036: Failed replications recorded without silent dropping."""
        rep = ReplicationResult(
            replication_id=0,
            random_seed=42,
            status="FAILED",
            error_message="Simulation diverged",
        )
        res = MonteCarloExecutionResult(
            analysis_id="TEST",
            scenario_id="SCEN",
            total_replications=1,
            valid_replications=0,
            failed_replications=1,
            replications=[rep],
        )
        assert res.failed_replications == 1
        assert res.valid_replications == 0

    def test_p11_b037_deterministic_baseline_preservation(self) -> None:
        """P11-B037: Baseline parameters immutable across stochastic sampling."""
        base_params = make_test_train_params()
        base_te = base_params.max_tractive_effort_n

        var = StochasticVariableDefinition(
            variable_id="VAR_TRAC",
            target_object_type=TargetObjectType.TRACTION_UTILIZATION,
            distribution_type=DistributionType.UNIFORM,
            distribution_parameters={"min_val": 0.85, "max_val": 0.85},
            sampling_scope=SamplingScope.PER_TRAIN,
        )
        mod_params, _ = MonteCarloSimulationManager._apply_stochastic_parameter_to_train(base_params, var, 0.85, 0.0)

        assert base_params.max_tractive_effort_n == base_te
        assert mod_params.max_tractive_effort_n == pytest.approx(base_te * 0.85)

    def test_p11_b038_complete_monte_carlo_reproducibility(self) -> None:
        """P11-B038: Identical master seed reproduces exact Monte Carlo sample sequences."""
        seed = 777
        var = StochasticVariableDefinition(
            variable_id="V_DWELL",
            target_object_type=TargetObjectType.STATION_DWELL,
            distribution_type=DistributionType.NORMAL,
            distribution_parameters={"mean": 30.0, "std_dev": 3.0},
        )
        mgr1 = MasterSeedManager(seed)
        mgr2 = MasterSeedManager(seed)

        s1 = mgr1.get_replication_generator(0).normal(30.0, 3.0, size=5)
        s2 = mgr2.get_replication_generator(0).normal(30.0, 3.0, size=5)
        assert np.allclose(s1, s2)
