"""Negative unit tests for Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- Edge cases, invalid parameters, and exception contract enforcement
- Negative, zero, NaN, Inf headways
- Out-of-bounds utilization ratios
- Invalid measurement windows and screenlines
- Empty sequences and incomplete matrix lookups
- Inverted bisection search bounds
- Invariant enforcement: Baseline configuration immutability during sensitivity sweeps
"""

import copy
import math
import pytest

from headway.analysis.bottleneck_migration import BottleneckAnalyzer
from headway.analysis.capacity import TheoreticalCapacityCalculator
from headway.analysis.capacity_consumption import CapacityConsumptionCalculator
from headway.analysis.capacity_models import (
    BottleneckCategory,
    BottleneckDiagnostic,
    CapacityResult,
    CapacityType,
    MeasurementWindow,
    OperationalStabilityStatus,
)
from headway.analysis.resource_utilization import ResourceUtilizationAnalyzer
from headway.analysis.saturation import CapacitySaturationSearch
from headway.analysis.sensitivity import SensitivityAnalyzer
from headway.analysis.stability import OperationalStabilityEvaluator
from headway.analysis.throughput import ThroughputCalculator
from headway.core.exceptions import OperationalSimulationError
from headway.infrastructure.direction import RunningDirection


class TestCapacityNegativeCases:
    """Comprehensive negative tests for capacity calculation engines."""

    @pytest.mark.parametrize("invalid_h", [0.0, -10.0, float("nan"), float("inf"), float("-inf")])
    def test_homogeneous_capacity_invalid_headway(self, invalid_h: float) -> None:
        """P10-HOM: Headway must be strictly positive and finite."""
        with pytest.raises(ValueError):
            TheoreticalCapacityCalculator.calculate_homogeneous_capacity(headway_s=invalid_h)

    @pytest.mark.parametrize("invalid_m", [-1.0, -50.0, float("nan"), float("inf")])
    def test_additive_planning_capacity_invalid_margin(self, invalid_m: float) -> None:
        """P10-PLN: Planning margin must be non-negative and finite."""
        with pytest.raises(ValueError):
            TheoreticalCapacityCalculator.calculate_planning_capacity_additive(
                headway_s=120.0,
                planning_margin_s=invalid_m,
            )

    @pytest.mark.parametrize("invalid_u", [0.0, -0.5, 1.05, 2.0, float("nan"), float("inf")])
    def test_utilization_planning_capacity_invalid_ratio(self, invalid_u: float) -> None:
        """P10-PLN: Target utilization must be in range (0.0, 1.0]."""
        with pytest.raises(ValueError):
            TheoreticalCapacityCalculator.calculate_planning_capacity_utilization(
                theoretical_capacity_tph=30.0,
                target_utilization=invalid_u,
            )

    def test_mixed_pattern_empty_sequence(self) -> None:
        """P10-MIX: Empty service sequence is strictly rejected."""
        with pytest.raises(ValueError, match="Service sequence cannot be empty"):
            TheoreticalCapacityCalculator.calculate_mixed_pattern_capacity(
                service_sequence=[],
                headway_matrix={("A", "A"): 120.0},
            )

    def test_mixed_pattern_missing_pairwise_headway(self) -> None:
        """P10-MIX: Missing pairwise headway in matrix raises OperationalSimulationError."""
        with pytest.raises(OperationalSimulationError, match="Headway matrix missing pair"):
            TheoreticalCapacityCalculator.calculate_mixed_pattern_capacity(
                service_sequence=["SVC_A", "SVC_B"],
                headway_matrix={("SVC_A", "SVC_B"): 120.0},  # missing wrap-around ("SVC_B", "SVC_A")
            )

    def test_mixed_pattern_negative_pairwise_headway(self) -> None:
        """P10-MIX: Non-positive pairwise headway raises OperationalSimulationError."""
        with pytest.raises(OperationalSimulationError, match="Infeasible or non-positive headway"):
            TheoreticalCapacityCalculator.calculate_mixed_pattern_capacity(
                service_sequence=["SVC_A", "SVC_B"],
                headway_matrix={("SVC_A", "SVC_B"): 120.0, ("SVC_B", "SVC_A"): -50.0},
            )

    @pytest.mark.parametrize("invalid_n", [-1, -10])
    def test_analytical_throughput_negative_trains(self, invalid_n: int) -> None:
        """P10-TPH: Negative train count is rejected."""
        with pytest.raises(ValueError, match="Train count must be non-negative"):
            ThroughputCalculator.calculate_analytical_throughput(
                train_count=invalid_n,
                duration_s=3600.0,
            )

    @pytest.mark.parametrize("invalid_t", [0.0, -100.0, float("nan"), float("inf")])
    def test_analytical_throughput_invalid_duration(self, invalid_t: float) -> None:
        """P10-TPH: Duration must be strictly positive and finite."""
        with pytest.raises(ValueError, match="Duration must be positive and finite"):
            ThroughputCalculator.calculate_analytical_throughput(
                train_count=10,
                duration_s=invalid_t,
            )

    def test_simulation_throughput_screenline_without_chainage(self) -> None:
        """P10-TPH: Screenline counting requires screenline_chainage_m."""
        class MockSim:
            train_instances = []
        window = MeasurementWindow(warm_up_s=0.0, measurement_duration_s=3600.0)
        with pytest.raises(ValueError, match="screenline_chainage_m must be provided"):
            ThroughputCalculator.calculate_simulation_throughput(
                sim_result=MockSim(),
                measurement_window=window,
                count_method="screenline",
                screenline_chainage_m=None,
            )

    def test_simulation_throughput_invalid_count_method(self) -> None:
        """P10-TPH: Invalid counting method is rejected."""
        class MockSim:
            train_instances = []
        window = MeasurementWindow(warm_up_s=0.0, measurement_duration_s=3600.0)
        with pytest.raises(ValueError, match="Unknown count_method"):
            ThroughputCalculator.calculate_simulation_throughput(
                sim_result=MockSim(),
                measurement_window=window,
                count_method="invalid_mode",
            )

    def test_resource_utilization_invalid_window(self) -> None:
        """P10-RES: Resource utilization window duration must be strictly positive."""
        analyzer = ResourceUtilizationAnalyzer()
        with pytest.raises(ValueError, match="Window duration must be positive"):
            analyzer.analyze_usage_records([], window_duration_s=0.0)
        with pytest.raises(ValueError, match="Window duration must be positive"):
            analyzer.analyze_usage_records([], window_duration_s=-500.0)

    @pytest.mark.parametrize("invalid_comp,invalid_supp,invalid_win", [
        (-100.0, 600.0, 7200.0),
        (3000.0, -50.0, 7200.0),
        (3000.0, 600.0, 0.0),
        (3000.0, 600.0, -100.0),
    ])
    def test_capacity_consumption_invalid_parameters(
        self,
        invalid_comp: float,
        invalid_supp: float,
        invalid_win: float,
    ) -> None:
        """P10-UIC: Rejects invalid or negative compression times or windows."""
        with pytest.raises(ValueError):
            CapacityConsumptionCalculator.calculate_analytical_consumption(
                compressed_duration_s=invalid_comp,
                supplement_s=invalid_supp,
                analysis_window_s=invalid_win,
            )

    def test_saturation_bisection_invalid_bounds(self) -> None:
        """P10-SAT: Bisection bounds must have min > 0 and max > min."""
        searcher = CapacitySaturationSearch()
        with pytest.raises(ValueError, match="Invalid bisection bounds"):
            searcher.run_bisection_search(min_demand_tph=30.0, max_demand_tph=10.0, simulation_runner=lambda r: None)
        with pytest.raises(ValueError, match="Invalid bisection bounds"):
            searcher.run_bisection_search(min_demand_tph=-5.0, max_demand_tph=10.0, simulation_runner=lambda r: None)

    def test_saturation_step_scan_empty_rates(self) -> None:
        """P10-SAT: Step scan requires non-empty candidate demand rates."""
        searcher = CapacitySaturationSearch()
        with pytest.raises(ValueError, match="Candidate demand rates list cannot be empty"):
            searcher.run_step_scan(candidate_demand_rates_tph=[], simulation_runner=lambda r: None)

    def test_platform_sensitivity_invalid_platform_count(self) -> None:
        """P10-SEN: Platform count must be at least 1."""
        analyzer = SensitivityAnalyzer()
        with pytest.raises(ValueError, match="Platform count must be at least 1"):
            analyzer.evaluate_platform_assignment_sensitivity(
                baseline_platforms=1,
                candidate_platforms=[0, 1, 2],
                single_platform_occupation_s=120.0,
            )

    def test_sensitivity_baseline_immutability(self) -> None:
        """P10-SEN-001: Strict verification that baseline configuration is immutable across sensitivity sweeps."""
        baseline_block_length = 1000.0
        candidate_blocks = [500.0, 750.0, 1000.0, 1500.0]
        original_blocks_copy = list(candidate_blocks)

        analyzer = SensitivityAnalyzer()
        study = analyzer.evaluate_block_length_sensitivity(
            baseline_block_length_m=baseline_block_length,
            candidate_block_lengths_m=candidate_blocks,
            train_speed_mps=25.0,
            train_length_m=150.0,
        )

        # Invariance checks
        assert baseline_block_length == 1000.0
        assert candidate_blocks == original_blocks_copy
        assert study.baseline_value == 1000.0
        assert study.baseline_capacity_tph > 0.0
