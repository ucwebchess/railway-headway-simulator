"""Engineering and analytical benchmark suite for Railway Capacity and Sensitivity Analysis.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- Analytical Benchmarks BENCH-P10-001 to BENCH-P10-006:
  * BENCH-P10-001: Theoretical homogeneous capacity (H = 120s -> C = 30.0 tph)
  * BENCH-P10-002: Additive planning margin (H = 120s, M = 60s -> C = 20.0 tph)
  * BENCH-P10-003: Target utilization (C = 30 tph, U = 0.8 -> C_plan = 24.0 tph)
  * BENCH-P10-004: Mixed-pattern repeated cycle (H(A,B)=120s, H(B,A)=180s -> C = 24.0 tph)
  * BENCH-P10-005: Operational throughput (N = 25 in 2 hours -> Q = 12.5 tph)
  * BENCH-P10-006: UIC 406 capacity consumption (4500s + 900s / 7200s -> K = 75.0%)
- Operational Benchmarks P10-B007 to P10-B032:
  * P10-B007: FORWARD Homogeneous Capacity
  * P10-B008: REVERSE Homogeneous Capacity
  * P10-B009: Additive margin sensitivity (Controlled example H=255.6s, M=90s -> C=10.4 tph)
  * P10-B010: Target utilization capacity (U = 0.60, 0.75, 0.85)
  * P10-B011: 3-service mixed pattern cycle capacity with wrap-around
  * P10-B012: Operational throughput with warmup/cooldown window filtering
  * P10-B013: Operational throughput via screenline counting
  * P10-B014: Stability evaluation - STABLE
  * P10-B015: Stability evaluation - METASTABLE
  * P10-B016: Stability evaluation - UNSTABLE
  * P10-B017: Stability evaluation - COLLAPSED
  * P10-B018: Capacity saturation search via step-wise demand rate scanning
  * P10-B019: Capacity saturation search via bisection search
  * P10-B020: Physical occupation time vs blocking time differentiation
  * P10-B021: Overlapping resource interval merging preventing > 100% false utilization
  * P10-B022: Directional resource utilization attribution (FORWARD % vs REVERSE %)
  * P10-B023: TVS group resource utilization and single-train occupancy rule constraint
  * P10-B024: Bottleneck identification and ranking
  * P10-B025: Bottleneck migration tracking and diminishing returns quantification
  * P10-B026: UIC 406 timetable compression preserving train speeds and dwells
  * P10-B027: UIC 406 capacity consumption index with buffer supplement and UIC disclaimer
  * P10-B028: Block length sensitivity analysis with full physical recalculation (no proportional scaling shortcut)
  * P10-B029: Signalling technology sensitivity comparing 2/3/4 aspect, ETCS L2, CBTC
  * P10-B030: Station dwell sensitivity identifying line vs station crossover
  * P10-B031: Platform assignment sensitivity demonstrating switch throat limit
  * P10-B032: Opposing-direction / REVERSE capacity sensitivity and stability evaluation
"""

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
    PlanningMarginMethod,
    ResourceUtilizationMetric,
    StabilityEvaluation,
    TimetableCompressionResult,
)
from headway.analysis.delays import TrainDelaySummary
from headway.analysis.resource_utilization import (
    ResourceUtilizationAnalyzer,
    merge_time_intervals,
    total_interval_duration,
)
from headway.analysis.saturation import CapacitySaturationSearch
from headway.analysis.sensitivity import SensitivityAnalyzer
from headway.analysis.stability import OperationalStabilityEvaluator
from headway.analysis.throughput import ThroughputCalculator
from headway.analysis.timetable_compression import TimetableCompressor, TrainPathStairway
from headway.infrastructure.direction import RunningDirection
from headway.signalling.resource_types import ResourceCategory, ResourceUsageRecord
from headway.simulation.multi_train_engine import MultiTrainSimulationResult
from headway.simulation.service_instance import TrainServiceInstance
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory


class TestAnalyticalBenchmarks:
    """Rigorous verification of BENCH-P10-001 through BENCH-P10-006."""

    def test_bench_p10_001_theoretical_homogeneous_capacity(self) -> None:
        """BENCH-P10-001: H = 120.0s -> C = 30.0 trains/hour."""
        res = TheoreticalCapacityCalculator.calculate_homogeneous_capacity(
            headway_s=120.0,
            direction=RunningDirection.FORWARD,
            analysis_section="LINE_CORRIDOR_1",
        )
        assert res.capacity_type == CapacityType.THEORETICAL_HOMOGENEOUS
        assert math.isclose(res.capacity_trains_per_hour, 30.0, rel_tol=1e-6)
        assert math.isclose(res.headway_s, 120.0, rel_tol=1e-6)
        assert res.running_direction == RunningDirection.FORWARD

    def test_bench_p10_002_additive_planning_margin(self) -> None:
        """BENCH-P10-002: H = 120.0s, M = 60.0s -> C = 20.0 trains/hour."""
        res = TheoreticalCapacityCalculator.calculate_planning_capacity_additive(
            headway_s=120.0,
            planning_margin_s=60.0,
            direction=RunningDirection.FORWARD,
        )
        assert res.capacity_type == CapacityType.PLANNING_ADDITIVE_MARGIN
        assert res.planning_margin_method == PlanningMarginMethod.ADDITIVE_HEADWAY_MARGIN
        assert math.isclose(res.headway_s, 180.0, rel_tol=1e-6)
        assert math.isclose(res.capacity_trains_per_hour, 20.0, rel_tol=1e-6)

    def test_bench_p10_003_target_utilization(self) -> None:
        """BENCH-P10-003: C_theo = 30.0 tph, U = 0.8 -> C_plan = 24.0 trains/hour."""
        res = TheoreticalCapacityCalculator.calculate_planning_capacity_utilization(
            theoretical_capacity_tph=30.0,
            target_utilization=0.8,
            direction=RunningDirection.FORWARD,
        )
        assert res.capacity_type == CapacityType.PLANNING_UTILIZATION
        assert res.planning_margin_method == PlanningMarginMethod.TARGET_UTILIZATION
        assert math.isclose(res.capacity_trains_per_hour, 24.0, rel_tol=1e-6)
        assert math.isclose(res.headway_s, 150.0, rel_tol=1e-6)

    def test_bench_p10_004_mixed_pattern_repeated_cycle(self) -> None:
        """BENCH-P10-004: H(A,B) = 120s, H(B,A) = 180s -> T_cycle = 300s, C = 24.0 trains/hour."""
        headway_matrix = {
            ("SVC_A", "SVC_B"): 120.0,
            ("SVC_B", "SVC_A"): 180.0,
        }
        res = TheoreticalCapacityCalculator.calculate_mixed_pattern_capacity(
            service_sequence=["SVC_A", "SVC_B"],
            headway_matrix=headway_matrix,
            direction=RunningDirection.FORWARD,
        )
        assert res.capacity_type == CapacityType.THEORETICAL_MIXED_PATTERN
        assert math.isclose(res.capacity_trains_per_hour, 24.0, rel_tol=1e-6)
        assert math.isclose(res.headway_s, 150.0, rel_tol=1e-6)
        assert res.details["cycle_duration_s"] == 300.0

    def test_bench_p10_005_operational_throughput(self) -> None:
        """BENCH-P10-005: N = 25 trains, T = 7200s (2 hours) -> Q = 12.5 trains/hour."""
        res = ThroughputCalculator.calculate_analytical_throughput(
            train_count=25,
            duration_s=7200.0,
            direction=RunningDirection.FORWARD,
        )
        assert res.capacity_type == CapacityType.ACHIEVED_OPERATIONAL_THROUGHPUT
        assert math.isclose(res.capacity_trains_per_hour, 12.5, rel_tol=1e-6)
        assert math.isclose(res.headway_s, 288.0, rel_tol=1e-6)
        assert res.counted_trains == 25

    def test_bench_p10_006_uic_406_capacity_consumption(self) -> None:
        """BENCH-P10-006: T_comp = 4500s, T_supp = 900s, T_anal = 7200s -> K = 75.0%."""
        res = CapacityConsumptionCalculator.calculate_analytical_consumption(
            compressed_duration_s=4500.0,
            supplement_s=900.0,
            analysis_window_s=7200.0,
            direction=RunningDirection.FORWARD,
        )
        assert res.capacity_type == CapacityType.UIC406_CAPACITY_CONSUMPTION
        assert math.isclose(res.capacity_trains_per_hour, 75.0, rel_tol=1e-6)
        assert math.isclose(res.details["consumption_ratio"], 0.75, rel_tol=1e-6)
        assert math.isclose(res.details["consumption_percent"], 75.0, rel_tol=1e-6)
        assert "UIC" in res.details["uic_disclaimer"]


class TestOperationalBenchmarks:
    """Operational benchmarks P10-B007 through P10-B032."""

    def test_p10_b007_forward_homogeneous_capacity(self) -> None:
        """P10-B007: FORWARD direction calculation with positive finite headway."""
        res = TheoreticalCapacityCalculator.calculate_homogeneous_capacity(
            headway_s=150.0,
            direction=RunningDirection.FORWARD,
        )
        assert res.running_direction == RunningDirection.FORWARD
        assert math.isclose(res.capacity_trains_per_hour, 24.0, rel_tol=1e-6)

    def test_p10_b008_reverse_homogeneous_capacity(self) -> None:
        """P10-B008: REVERSE direction calculation referencing identical physical infrastructure."""
        res = TheoreticalCapacityCalculator.calculate_homogeneous_capacity(
            headway_s=200.0,
            direction=RunningDirection.REVERSE,
            analysis_section="CORRIDOR_REV",
        )
        assert res.running_direction == RunningDirection.REVERSE
        assert math.isclose(res.capacity_trains_per_hour, 18.0, rel_tol=1e-6)

    def test_p10_b009_additive_margin_sensitivity_controlled_example(self) -> None:
        """P10-B009: Controlled engineering example: H = 255.6s, M = 90.0s -> C = 10.4 tph."""
        res = TheoreticalCapacityCalculator.calculate_planning_capacity_additive(
            headway_s=255.6,
            planning_margin_s=90.0,
        )
        # H_plan = 345.6s -> C = 3600 / 345.6 = 10.41666... tph -> rounds to 10.4 tph
        assert math.isclose(res.headway_s, 345.6, rel_tol=1e-5)
        assert math.isclose(res.capacity_trains_per_hour, 10.416667, rel_tol=1e-4)
        assert round(res.capacity_trains_per_hour, 1) == 10.4

    def test_p10_b010_target_utilization_sweep(self) -> None:
        """P10-B010: Target utilization across U = 0.60, 0.75, 0.85 on C = 40.0 tph."""
        c_theo = 40.0
        for u, expected_c in [(0.60, 24.0), (0.75, 30.0), (0.85, 34.0)]:
            res = TheoreticalCapacityCalculator.calculate_planning_capacity_utilization(
                theoretical_capacity_tph=c_theo,
                target_utilization=u,
            )
            assert math.isclose(res.capacity_trains_per_hour, expected_c, rel_tol=1e-6)

    def test_p10_b011_three_service_mixed_pattern_with_wrap_around(self) -> None:
        """P10-B011: Cycle of 3 services: A -> B -> C -> A."""
        # Headways: A->B: 100s, B->C: 140s, C->A: 120s -> Total cycle = 360s
        matrix = {
            ("A", "B"): 100.0,
            ("B", "C"): 140.0,
            ("C", "A"): 120.0,
        }
        res = TheoreticalCapacityCalculator.calculate_mixed_pattern_capacity(
            service_sequence=["A", "B", "C"],
            headway_matrix=matrix,
        )
        # 3 trains in 360s -> 3600 * 3 / 360 = 30 trains/h
        assert math.isclose(res.capacity_trains_per_hour, 30.0, rel_tol=1e-6)
        assert res.details["cycle_duration_s"] == 360.0

    def test_p10_b012_operational_throughput_with_window_filtering(self) -> None:
        """P10-B012: Simulation throughput with warmup/cooldown window filtering."""
        # Mock simulation result with 5 trains:
        # Train 1: completed at t=300 (warmup)
        # Train 2: completed at t=1200 (measurement window [600, 4200])
        # Train 3: completed at t=2400 (measurement window)
        # Train 4: completed at t=3600 (measurement window)
        # Train 5: completed at t=4500 (cooldown)
        class MockTrain:
            def __init__(self, tid: str, comp_t: float, r_dir: RunningDirection = RunningDirection.FORWARD):
                self.train_id = tid
                self.actual_completion_time_s = comp_t
                self.running_direction = r_dir

        trains = [
            MockTrain("T1", 300.0),
            MockTrain("T2", 1200.0),
            MockTrain("T3", 2400.0),
            MockTrain("T4", 3600.0),
            MockTrain("T5", 4500.0),
        ]
        class MockSim:
            train_instances = trains

        window = MeasurementWindow(
            warm_up_s=600.0,
            measurement_duration_s=3600.0,  # [600, 4200]
            cool_down_s=600.0,
            start_time_s=600.0,
            end_time_s=4200.0,
        )

        res = ThroughputCalculator.calculate_simulation_throughput(
            sim_result=MockSim(),
            measurement_window=window,
        )
        # Exactly T2, T3, T4 completed in [600, 4200] -> 3 trains in 1 hour = 3.0 tph
        assert res.counted_trains == 3
        assert math.isclose(res.capacity_trains_per_hour, 3.0, rel_tol=1e-6)
        assert "T1" not in res.details["counted_train_ids"]
        assert "T5" not in res.details["counted_train_ids"]

    def test_p10_b013_operational_throughput_screenline_counting(self) -> None:
        """P10-B013: Boundary screenline crossing count."""
        class MockTraj:
            def __init__(self, samples):
                self.samples = samples

        class MockTrain:
            def __init__(self, tid: str):
                self.train_id = tid
                self.running_direction = RunningDirection.FORWARD
                self.actual_completion_time_s = 2000.0

        # T1 crosses chainage 5000m at t=1000s
        # T2 crosses chainage 5000m at t=2000s
        # T3 does not reach 5000m
        t1_samples = [
            TrajectorySample(0.0, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, DynamicMode.CRUISING, OperationalState.RUNNING),
            TrajectorySample(1000.0, 5000.0, 4800.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, DynamicMode.CRUISING, OperationalState.RUNNING),
        ]
        t2_samples = [
            TrajectorySample(0.0, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, DynamicMode.CRUISING, OperationalState.RUNNING),
            TrajectorySample(2000.0, 5000.0, 4800.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, DynamicMode.CRUISING, OperationalState.RUNNING),
        ]
        t3_samples = [
            TrajectorySample(0.0, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, DynamicMode.CRUISING, OperationalState.RUNNING),
            TrajectorySample(1500.0, 3000.0, 2800.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, DynamicMode.CRUISING, OperationalState.RUNNING),
        ]

        class MockSim:
            train_instances = [MockTrain("T1"), MockTrain("T2"), MockTrain("T3")]
            trajectories = {
                "T1": MockTraj(t1_samples),
                "T2": MockTraj(t2_samples),
                "T3": MockTraj(t3_samples),
            }

        window = MeasurementWindow(
            warm_up_s=0.0,
            measurement_duration_s=3600.0,
            start_time_s=0.0,
            end_time_s=3600.0,
        )

        res = ThroughputCalculator.calculate_simulation_throughput(
            sim_result=MockSim(),
            measurement_window=window,
            count_method="screenline",
            screenline_chainage_m=5000.0,
        )
        assert res.counted_trains == 2
        assert res.details["counted_train_ids"] == ["T1", "T2"]
        assert math.isclose(res.capacity_trains_per_hour, 2.0, rel_tol=1e-6)

    def test_p10_b014_stability_stable(self) -> None:
        """P10-B014: Stability evaluation - STABLE (flat delays, zero deadlock, 100% completion)."""
        evaluator = OperationalStabilityEvaluator()
        class MockTrain:
            def __init__(self, tid: str, req_t: float, comp_t: float):
                self.train_id = tid
                self.requested_departure_time_s = req_t
                self.actual_departure_time_s = req_t
                self.actual_completion_time_s = comp_t

        class MockDelay:
            def __init__(self, arr_d: float):
                self.arrival_delay_s = arr_d
                self.departure_delay_s = 0.0
                self.primary_delay_s = 0.0
                self.secondary_delay_s = 0.0

        trains = [MockTrain(f"T{i}", i * 300.0, i * 300.0 + 500.0) for i in range(10)]
        delays = {f"T{i}": MockDelay(10.0) for i in range(10)}

        class MockSim:
            train_instances = trains
            delay_summaries = delays
            deadlock_report = None

        stab = evaluator.evaluate_simulation(MockSim())
        assert stab.status == OperationalStabilityStatus.STABLE
        assert stab.is_sustainable is True
        assert stab.deadlock_detected is False
        assert math.isclose(stab.delay_growth_slope, 0.0, abs_tol=1e-6)

    def test_p10_b015_stability_metastable(self) -> None:
        """P10-B015: Stability evaluation - METASTABLE (moderate delay growth <= 2.0 s/train)."""
        evaluator = OperationalStabilityEvaluator(delay_slope_unstable_threshold=2.0, delay_slope_metastable_threshold=0.5)
        class MockTrain:
            def __init__(self, tid: str, req_t: float):
                self.train_id = tid
                self.requested_departure_time_s = req_t
                self.actual_departure_time_s = req_t
                self.actual_completion_time_s = req_t + 500.0

        class MockDelay:
            def __init__(self, arr_d: float):
                self.arrival_delay_s = arr_d
                self.departure_delay_s = 0.0
                self.primary_delay_s = 10.0
                self.secondary_delay_s = arr_d - 10.0

        # Sloping delays: 10 + i * 1.0 s -> slope = 1.0 s/train (> 0.5 metastable, < 2.0 unstable)
        trains = [MockTrain(f"T{i}", i * 300.0) for i in range(10)]
        delays = {f"T{i}": MockDelay(10.0 + i * 1.0) for i in range(10)}

        class MockSim:
            train_instances = trains
            delay_summaries = delays
            deadlock_report = None

        stab = evaluator.evaluate_simulation(MockSim())
        assert stab.status == OperationalStabilityStatus.METASTABLE
        assert stab.is_sustainable is False  # Only STABLE is certified sustainable

    def test_p10_b016_stability_unstable(self) -> None:
        """P10-B016: Stability evaluation - UNSTABLE (growing delays > threshold)."""
        evaluator = OperationalStabilityEvaluator(delay_slope_unstable_threshold=2.0)
        class MockTrain:
            def __init__(self, tid: str, req_t: float):
                self.train_id = tid
                self.requested_departure_time_s = req_t
                self.actual_departure_time_s = req_t
                self.actual_completion_time_s = req_t + 500.0

        class MockDelay:
            def __init__(self, arr_d: float):
                self.arrival_delay_s = arr_d
                self.departure_delay_s = 0.0
                self.primary_delay_s = 5.0
                self.secondary_delay_s = arr_d - 5.0

        # Slope = 5.0 s/train (> 2.0 s/train threshold)
        trains = [MockTrain(f"T{i}", i * 300.0) for i in range(10)]
        delays = {f"T{i}": MockDelay(5.0 * i) for i in range(10)}

        class MockSim:
            train_instances = trains
            delay_summaries = delays
            deadlock_report = None

        stab = evaluator.evaluate_simulation(MockSim())
        assert stab.status == OperationalStabilityStatus.UNSTABLE
        assert stab.is_sustainable is False

    def test_p10_b017_stability_collapsed(self) -> None:
        """P10-B017: Stability evaluation - COLLAPSED (deadlock detected)."""
        evaluator = OperationalStabilityEvaluator()
        class MockDeadlock:
            deadlock_detected = True

        class MockTrain:
            def __init__(self, tid: str):
                self.train_id = tid
                self.requested_departure_time_s = 0.0
                self.actual_departure_time_s = 0.0
                self.actual_completion_time_s = None  # Stalled

        class MockSim:
            train_instances = [MockTrain("T1"), MockTrain("T2")]
            delay_summaries = {}
            deadlock_report = MockDeadlock()

        stab = evaluator.evaluate_simulation(MockSim())
        assert stab.status == OperationalStabilityStatus.COLLAPSED
        assert stab.deadlock_detected is True
        assert stab.is_sustainable is False

    def test_p10_b018_saturation_search_step_scan(self) -> None:
        """P10-B018: Capacity saturation search via discrete step scan."""
        # Mock runner: stable up to 20 tph, unstable at 25 tph
        def mock_runner(rate_tph: float):
            class MockTrain:
                def __init__(self, tid: str):
                    self.train_id = tid
                    self.requested_departure_time_s = 0.0
                    self.actual_departure_time_s = 0.0
                    self.actual_completion_time_s = 100.0
            class MockDelay:
                def __init__(self, d: float):
                    self.arrival_delay_s = d
                    self.departure_delay_s = 0.0
                    self.primary_delay_s = 0.0
                    self.secondary_delay_s = 0.0
            slope = 0.1 if rate_tph <= 20.0 else 5.0
            class MockSim:
                train_instances = [MockTrain(f"T{i}") for i in range(5)]
                delay_summaries = {f"T{i}": MockDelay(i * slope) for i in range(5)}
                deadlock_report = None
            return MockSim()

        searcher = CapacitySaturationSearch()
        cap_res, evals = searcher.run_step_scan(
            candidate_demand_rates_tph=[10.0, 15.0, 20.0, 25.0, 30.0],
            simulation_runner=mock_runner,
        )
        assert cap_res.capacity_type == CapacityType.SUSTAINABLE_OPERATIONAL_CAPACITY
        assert cap_res.capacity_trains_per_hour == 20.0
        assert math.isclose(cap_res.headway_s, 180.0, rel_tol=1e-6)

    def test_p10_b019_saturation_search_bisection(self) -> None:
        """P10-B019: Capacity saturation search via binary bisection."""
        # Stable below 22.0 tph, unstable at >= 22.0 tph
        def mock_runner(rate_tph: float):
            class MockTrain:
                def __init__(self, tid: str):
                    self.train_id = tid
                    self.requested_departure_time_s = 0.0
                    self.actual_departure_time_s = 0.0
                    self.actual_completion_time_s = 100.0
            class MockDelay:
                def __init__(self, d: float):
                    self.arrival_delay_s = d
                    self.departure_delay_s = 0.0
                    self.primary_delay_s = 0.0
                    self.secondary_delay_s = 0.0
            slope = 0.0 if rate_tph < 22.0 else 10.0
            class MockSim:
                train_instances = [MockTrain(f"T{i}") for i in range(5)]
                delay_summaries = {f"T{i}": MockDelay(i * slope) for i in range(5)}
                deadlock_report = None
            return MockSim()

        searcher = CapacitySaturationSearch()
        cap_res, evals = searcher.run_bisection_search(
            min_demand_tph=10.0,
            max_demand_tph=30.0,
            simulation_runner=mock_runner,
            tolerance_tph=0.5,
        )
        # Should converge close to 22.0 tph
        assert 21.0 <= cap_res.capacity_trains_per_hour < 22.5
        assert cap_res.stability_evaluation.is_sustainable is True

    def test_p10_b020_physical_vs_blocking_time_differentiation(self) -> None:
        """P10-B020: Differentiates physical occupation time from blocking time."""
        # Resource BLOCK_01:
        # Reservation: [100.0, 250.0] -> 150s blocking time
        # Physical entry to exit: [140.0, 220.0] -> 80s physical occupation
        record = ResourceUsageRecord(
            usage_id="U1",
            train_id="T1",
            resource_id="BLOCK_01",
            resource_type=ResourceCategory.TRACK_BLOCK,
            reservation_start_s=100.0,
            physical_front_entry_s=140.0,
            front_exit_s=200.0,
            rear_clearance_s=220.0,
            release_eligibility_s=240.0,
            final_release_s=250.0,
            running_direction=RunningDirection.FORWARD,
        )
        analyzer = ResourceUtilizationAnalyzer()
        metrics = analyzer.analyze_usage_records([record], window_duration_s=1000.0)
        m = metrics["BLOCK_01"]

        assert math.isclose(m.total_blocking_time_s, 150.0, rel_tol=1e-6)
        assert math.isclose(m.total_physical_occupation_time_s, 80.0, rel_tol=1e-6)
        assert math.isclose(m.blocking_utilization_percent, 15.0, rel_tol=1e-6)
        assert math.isclose(m.physical_utilization_percent, 8.0, rel_tol=1e-6)

    def test_p10_b021_overlapping_interval_merging(self) -> None:
        """P10-B021: Interval merging prevents > 100% false utilization for overlapping reservations."""
        # Two trains concurrently reservation locked on resource: [100, 300] and [200, 400]
        # Merged span: [100, 400] -> 300s (not 200 + 200 = 400s)
        r1 = ResourceUsageRecord(
            usage_id="U1", train_id="T1", resource_id="PLATFORM_1",
            resource_type=ResourceCategory.PLATFORM, reservation_start_s=100.0, final_release_s=300.0,
        )
        r2 = ResourceUsageRecord(
            usage_id="U2", train_id="T2", resource_id="PLATFORM_1",
            resource_type=ResourceCategory.PLATFORM, reservation_start_s=200.0, final_release_s=400.0,
        )
        analyzer = ResourceUtilizationAnalyzer()
        metrics = analyzer.analyze_usage_records([r1, r2], window_duration_s=1000.0)
        m = metrics["PLATFORM_1"]

        assert math.isclose(m.total_blocking_time_s, 300.0, rel_tol=1e-6)
        assert math.isclose(m.blocking_utilization_percent, 30.0, rel_tol=1e-6)

    def test_p10_b022_directional_resource_utilization(self) -> None:
        """P10-B022: Directional attribution: FORWARD vs REVERSE blocking time."""
        r_fwd = ResourceUsageRecord(
            usage_id="U1", train_id="T1", resource_id="SINGLE_TRACK_SEC",
            resource_type=ResourceCategory.TRACK_BLOCK, reservation_start_s=0.0, final_release_s=200.0,
            running_direction=RunningDirection.FORWARD,
        )
        r_rev = ResourceUsageRecord(
            usage_id="U2", train_id="T2", resource_id="SINGLE_TRACK_SEC",
            resource_type=ResourceCategory.TRACK_BLOCK, reservation_start_s=300.0, final_release_s=500.0,
            running_direction=RunningDirection.REVERSE,
        )
        analyzer = ResourceUtilizationAnalyzer()
        metrics = analyzer.analyze_usage_records([r_fwd, r_rev], window_duration_s=1000.0)
        m = metrics["SINGLE_TRACK_SEC"]

        assert math.isclose(m.forward_blocking_time_s, 200.0, rel_tol=1e-6)
        assert math.isclose(m.reverse_blocking_time_s, 200.0, rel_tol=1e-6)
        assert math.isclose(m.total_blocking_time_s, 400.0, rel_tol=1e-6)
        assert math.isclose(m.blocking_utilization_percent, 40.0, rel_tol=1e-6)

    def test_p10_b023_tvs_group_resource_utilization(self) -> None:
        """P10-B023: TVS group resource utilization and critical threshold flagging."""
        # 850 seconds locked out of 1000s window -> 85% utilization >= 75% critical threshold
        r_tvs = ResourceUsageRecord(
            usage_id="U_TVS", train_id="T_TUNNEL", resource_id="TVS_ZONE_1",
            resource_type=ResourceCategory.TVS, reservation_start_s=50.0, final_release_s=900.0,
        )
        analyzer = ResourceUtilizationAnalyzer(critical_threshold_percent=75.0)
        metrics = analyzer.analyze_usage_records([r_tvs], window_duration_s=1000.0)
        m = metrics["TVS_ZONE_1"]

        assert m.is_critical is True
        assert math.isclose(m.blocking_utilization_percent, 85.0, rel_tol=1e-6)

    def test_p10_b024_bottleneck_identification_and_ranking(self) -> None:
        """P10-B024: Bottleneck ranking by limiting headway."""
        headways = {
            "BLOCK_01": 90.0,
            "PLATFORM_STN_A": 160.0,
            "TVS_ZONE_SOUTH": 120.0,
        }
        diagnostics = BottleneckAnalyzer.identify_bottlenecks_from_headways(headways)

        assert len(diagnostics) == 3
        # Rank 1: PLATFORM_STN_A (160s)
        assert diagnostics[0].resource_id == "PLATFORM_STN_A"
        assert diagnostics[0].rank == 1
        assert diagnostics[0].category == BottleneckCategory.STATION_PLATFORM
        # Rank 2: TVS_ZONE_SOUTH (120s)
        assert diagnostics[1].resource_id == "TVS_ZONE_SOUTH"
        assert diagnostics[1].rank == 2
        # Rank 3: BLOCK_01 (90s)
        assert diagnostics[2].resource_id == "BLOCK_01"
        assert diagnostics[2].rank == 3

    def test_p10_b025_bottleneck_migration_tracking(self) -> None:
        """P10-B025: Bottleneck migration tracking and diminishing returns."""
        base_diag = BottleneckDiagnostic(
            resource_id="LONG_BLOCK_4",
            category=BottleneckCategory.SIGNALLING_BLOCK,
            limiting_headway_s=240.0,
            rank=1,
        )
        mod_diag = BottleneckDiagnostic(
            resource_id="PLATFORM_STN_2",
            category=BottleneckCategory.STATION_PLATFORM,
            limiting_headway_s=180.0,
            rank=1,
        )
        # Baseline capacity: 3600 / 240 = 15.0 tph
        # Modified capacity: 3600 / 180 = 20.0 tph
        # Ideal unconstrained gain if block halved (to 120s -> 30 tph): gain = 15 tph
        record = BottleneckAnalyzer.track_migration(
            baseline_scenario_id="SCEN_BASE",
            modified_scenario_id="SCEN_SPLIT_BLOCK",
            parameter_modified="block_4_subdivided",
            baseline_bottleneck=base_diag,
            modified_bottleneck=mod_diag,
            baseline_capacity_tph=15.0,
            modified_capacity_tph=20.0,
            theoretical_unconstrained_gain_tph=15.0,
        )
        assert record.bottleneck_migrated is True
        assert record.baseline_bottleneck_id == "LONG_BLOCK_4"
        assert record.modified_bottleneck_id == "PLATFORM_STN_2"
        assert math.isclose(record.delta_capacity_tph, 5.0, rel_tol=1e-6)
        assert math.isclose(record.percentage_gain, 33.333333, rel_tol=1e-4)
        assert math.isclose(record.diminishing_returns_ratio, 5.0 / 15.0, rel_tol=1e-4)

    def test_p10_b026_uic406_timetable_compression(self) -> None:
        """P10-B026: UIC 406 timetable compression shifts paths without altering running times."""
        # Train 1 uses B1 [0, 60], B2 [60, 120]
        # Train 2 originally planned at dep=600s: uses B1 [600, 660], B2 [660, 720]
        # Pure compression (buffer = 0) shifts Train 2 to depart at t=60s!
        t1 = TrainPathStairway(
            train_id="T1", departure_time_s=0.0,
            resource_intervals=[("B1", 0.0, 60.0), ("B2", 60.0, 120.0)],
        )
        t2 = TrainPathStairway(
            train_id="T2", departure_time_s=600.0,
            resource_intervals=[("B1", 600.0, 660.0), ("B2", 660.0, 720.0)],
        )
        compressor = TimetableCompressor(buffer_time_s=0.0)
        res = compressor.compress_stairways([t1, t2])

        assert res.train_count == 2
        assert res.original_duration_s == 720.0
        # T1 occupies B1 [0, 60], T2 can enter B1 as soon as T1 clears at 60s
        # T2 departs at 60s, occupies B1 [60, 120], B2 [120, 180]
        # Compressed duration = 180s - 0s = 180s
        assert math.isclose(res.compressed_duration_s, 180.0, rel_tol=1e-6)
        assert math.isclose(res.compression_ratio, 180.0 / 720.0, rel_tol=1e-6)
        assert math.isclose(res.compressed_train_departures["T2"], 60.0, rel_tol=1e-6)

    def test_p10_b027_uic406_consumption_with_disclaimer(self) -> None:
        """P10-B027: UIC 406 capacity consumption index with mandatory disclaimer."""
        res = CapacityConsumptionCalculator.calculate_analytical_consumption(
            compressed_duration_s=3000.0,
            supplement_s=600.0,
            analysis_window_s=7200.0,
        )
        # K = 3600 / 7200 = 50.0%
        assert math.isclose(res.capacity_trains_per_hour, 50.0, rel_tol=1e-6)
        assert "not claim or constitute formal certification" in res.details["uic_disclaimer"]

    def test_p10_b028_block_length_sensitivity_recalculation(self) -> None:
        """P10-B028: Block length sensitivity recalculates full physics (no proportional scaling shortcut)."""
        analyzer = SensitivityAnalyzer()
        study = analyzer.evaluate_block_length_sensitivity(
            baseline_block_length_m=1000.0,
            candidate_block_lengths_m=[500.0, 750.0, 1000.0, 1500.0],
            train_speed_mps=30.0,
            train_length_m=200.0,
            braking_deceleration_mps2=1.0,
            aspect_count=3,
        )
        assert len(study.points) == 4
        # At 500m block, capacity must be higher than at 1500m block
        cap_500 = next(p.capacity_trains_per_hour for p in study.points if p.parameter_value == 500.0)
        cap_1500 = next(p.capacity_trains_per_hour for p in study.points if p.parameter_value == 1500.0)
        assert cap_500 > cap_1500
        # Verify that doubling block length from 500m to 1000m does NOT halve capacity (proportional scaling violation)
        # Because headway has fixed components (sighting, train length, release delay)
        cap_1000 = next(p.capacity_trains_per_hour for p in study.points if p.parameter_value == 1000.0)
        ratio = cap_500 / cap_1000
        assert ratio < 1.9  # Strictly proves full physical recalculation, not proportional scaling!

    def test_p10_b029_signalling_system_sensitivity(self) -> None:
        """P10-B029: Signalling technology comparison (2/3/4 aspect, ETCS L2, CBTC)."""
        analyzer = SensitivityAnalyzer()
        systems = ["2_ASPECT", "3_ASPECT", "4_ASPECT", "ETCS_L2", "CBTC"]
        study = analyzer.evaluate_signalling_system_sensitivity(
            baseline_system="3_ASPECT",
            candidate_systems=systems,
            block_length_m=1000.0,
            train_speed_mps=25.0,
            train_length_m=150.0,
        )
        assert len(study.points) == 5
        c_by_sys = {p.parameter_value: p.capacity_trains_per_hour for p in study.points}
        # CBTC moving block yields highest capacity, followed by ETCS L2, 4-aspect, 3-aspect, and 2-aspect
        assert c_by_sys["CBTC"] > c_by_sys["ETCS_L2"] > c_by_sys["4_ASPECT"] > c_by_sys["3_ASPECT"] > c_by_sys["2_ASPECT"]

    def test_p10_b030_station_dwell_sensitivity(self) -> None:
        """P10-B030: Station dwell sweep identifying line vs station crossover."""
        analyzer = SensitivityAnalyzer()
        # Line headway is 120s
        # At dwell 30s: platform headway = 30 + 35 = 65s < 120s -> Line is bottleneck
        # At dwell 120s: platform headway = 120 + 35 = 155s > 120s -> Platform is bottleneck!
        study = analyzer.evaluate_station_dwell_sensitivity(
            baseline_dwell_s=30.0,
            candidate_dwells_s=[30.0, 60.0, 90.0, 120.0],
            line_headway_s=120.0,
            clearing_time_s=35.0,
        )
        b_30 = next(p.limiting_bottleneck_id for p in study.points if p.parameter_value == 30.0)
        b_120 = next(p.limiting_bottleneck_id for p in study.points if p.parameter_value == 120.0)
        assert "LINE" in b_30
        assert "PLATFORM" in b_120

    def test_p10_b031_platform_assignment_sensitivity(self) -> None:
        """P10-B031: Parallel platform assignment showing diminishing returns at throat limit."""
        analyzer = SensitivityAnalyzer()
        # Single platform dwell occupation = 180s
        # Throat switch limit = 50s
        # 1 platform: 180s (20 tph)
        # 2 platforms: 90s (40 tph)
        # 3 platforms: 60s (60 tph)
        # 4 platforms: would be 45s, but bounded by throat limit 50s (72 tph)!
        study = analyzer.evaluate_platform_assignment_sensitivity(
            baseline_platforms=1,
            candidate_platforms=[1, 2, 3, 4],
            single_platform_occupation_s=180.0,
            throat_switch_locking_s=50.0,
        )
        h_4 = next(p.headway_s for p in study.points if p.parameter_value == 4)
        b_4 = next(p.limiting_bottleneck_id for p in study.points if p.parameter_value == 4)
        assert math.isclose(h_4, 50.0, rel_tol=1e-6)
        assert "THROAT" in b_4

    def test_p10_b032_opposing_reverse_capacity_evaluation(self) -> None:
        """P10-B032: Opposing direction and REVERSE capacity evaluation."""
        analyzer = SensitivityAnalyzer(direction=RunningDirection.REVERSE)
        study = analyzer.evaluate_tvs_sensitivity(
            baseline_tvs_length_m=1000.0,
            candidate_tvs_lengths_m=[800.0, 1000.0, 1200.0],
            train_speed_mps=20.0,
            train_length_m=200.0,
            clearance_timer_s=30.0,
        )
        assert len(study.points) == 3
        # Traversing 1000m TVS + 200m train at 20 m/s takes 60s + 30s timer = 90s -> 40 tph
        h_1000 = next(p.headway_s for p in study.points if p.parameter_value == 1000.0)
        cap_1000 = next(p.capacity_trains_per_hour for p in study.points if p.parameter_value == 1000.0)
        assert math.isclose(h_1000, 90.0, rel_tol=1e-6)
        assert math.isclose(cap_1000, 40.0, rel_tol=1e-6)
