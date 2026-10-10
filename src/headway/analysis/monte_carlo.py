"""Monte Carlo simulation execution manager and replication aggregator.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- P11-MC-001 to P11-MC-009: Monte Carlo execution loop, replication isolation, failure handling, progress callbacks
- P11-HW-001 to P11-HW-005: Stochastic headway assessment
- P11-JT-001 to P11-JT-005: Journey-time statistics across service types and directions
- P11-DLY-001 to P11-DLY-003: Delay statistics and primary vs secondary separation
- P11-TVS-001 to P11-TVS-007: TVS waiting times and queue distributions
- P11-THR-001 to P11-THR-005: Throughput distributions and stability checks
"""

from __future__ import annotations

import copy
import math
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

from headway.analysis.capacity_models import (
    CapacityResult,
    CapacityType,
    MeasurementWindow,
    OperationalStabilityStatus,
)
from headway.analysis.random_variables import (
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
from headway.analysis.stability import OperationalStabilityEvaluator
from headway.analysis.statistics import (
    StatisticalSummary,
    compute_statistical_summary,
)
from headway.analysis.stochastic import (
    CommonRandomNumbersManager,
    CorrelationGroup,
    MasterSeedManager,
    StochasticParameterSampler,
)
from headway.analysis.throughput import ThroughputCalculator
from headway.data.canonical import StationStop
from headway.infrastructure.direction import RunningDirection
from headway.rolling_stock.train import RollingStockParameters
from headway.simulation.dispatching import DispatchPolicy
from headway.simulation.service_instance import (
    ServiceType,
    TrainGenerator,
    TrainServiceInstance,
)

if TYPE_CHECKING:
    from headway.signalling.coordinator import SignallingCoordinator
    from headway.simulation.multi_train_engine import MultiTrainSimulationResult, MultiTrainSimulator


@dataclass
class ReplicationResult:
    """P11 Section 27: Result package for a single Monte Carlo replication."""

    replication_id: int
    random_seed: int
    status: str  # "SUCCESS", "FAILED"
    error_message: Optional[str] = None
    headway_results_s: List[float] = field(default_factory=list)
    journey_times_s: Dict[str, float] = field(default_factory=dict)
    arrival_delays_s: Dict[str, float] = field(default_factory=dict)
    departure_delays_s: Dict[str, float] = field(default_factory=dict)
    tvs_waiting_times_s: Dict[str, float] = field(default_factory=dict)
    max_queue_length: int = 0
    operational_throughput_tph: float = 0.0
    stability_status: OperationalStabilityStatus = OperationalStabilityStatus.STABLE
    is_sustainable: bool = True
    completed_train_count: int = 0
    total_train_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MonteCarloExecutionResult:
    """P11 Section 27: Comprehensive deliverable package from a Monte Carlo simulation study."""

    analysis_id: str
    scenario_id: str
    total_replications: int
    valid_replications: int
    failed_replications: int
    replications: List[ReplicationResult] = field(default_factory=list)
    summaries: Dict[str, StatisticalSummary] = field(default_factory=dict)
    reliability_evaluation: Optional[ReliabilityEvaluationResult] = None
    model_warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def statistical_summaries(self) -> Dict[str, StatisticalSummary]:
        return self.summaries

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "scenario_id": self.scenario_id,
            "total_replications": self.total_replications,
            "valid_replications": self.valid_replications,
            "failed_replications": self.failed_replications,
            "summaries": {k: v.to_dict() for k, v in self.summaries.items()},
            "reliability": self.reliability_evaluation.to_dict() if self.reliability_evaluation else None,
            "model_warnings": self.model_warnings,
        }


class MonteCarloSimulationManager:
    """Orchestrates multi-train microscopic simulation across Monte Carlo replications."""

    def __init__(
        self,
        master_seed: int = 42,
        variables: Optional[Sequence[StochasticVariableDefinition]] = None,
        correlation_groups: Optional[Sequence[CorrelationGroup]] = None,
        disruptions: Optional[Sequence[OperationalDisruption]] = None,
        reliability_criteria: Optional[Sequence[ReliabilityCriterion]] = None,
        use_common_random_numbers: bool = False,
        stability_evaluator: Optional[OperationalStabilityEvaluator] = None,
    ) -> None:
        self.master_seed = master_seed
        self.seed_manager = MasterSeedManager(master_seed=master_seed)
        self.variables = list(variables or [])
        self.correlation_groups = list(correlation_groups or [])
        self.disruptions = list(disruptions or [])
        self.reliability_criteria = list(reliability_criteria or [])
        self.use_crn = use_common_random_numbers
        self.crn_manager = CommonRandomNumbersManager(master_seed=master_seed) if use_common_random_numbers else None
        self.stability_evaluator = stability_evaluator or OperationalStabilityEvaluator()

    def run_replications(
        self,
        coordinator_factory: Callable[[], SignallingCoordinator],
        service_templates: List[ServiceType],
        train_generation_config: List[Tuple[ServiceType, str, float]],  # (service, train_id, planned_dep_s)
        replication_count: int = 10,
        max_simulation_time_s: float = 1200.0,
        dt_s: float = 0.2,
        measurement_window: Optional[MeasurementWindow] = None,
        scenario_id: str = "BASELINE",
        analysis_id: str = "MC_STUDY_001",
        on_progress: Optional[Callable[[int, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> MonteCarloExecutionResult:
        """P11-MC-001 to 009: Executes isolated Monte Carlo simulation replications and aggregates statistics."""
        if replication_count < 1:
            raise ValueError(f"Replication count must be at least 1 (got {replication_count}).")

        replications: List[ReplicationResult] = []
        warnings: List[str] = []

        sampler = StochasticParameterSampler(
            variables=self.variables,
            correlation_groups=self.correlation_groups,
            use_common_random_numbers=self.use_crn,
            crn_manager=self.crn_manager,
        )

        effective_window = measurement_window or MeasurementWindow(
            warm_up_s=0.0,
            measurement_duration_s=max_simulation_time_s,
            cool_down_s=0.0,
        )

        for rep_idx in range(replication_count):
            if is_cancelled is not None and is_cancelled():
                warnings.append(f"Monte Carlo execution cancelled by user after {rep_idx} replications.")
                break

            rng = self.seed_manager.get_replication_generator(rep_idx, replication_count)
            sampler.reset_for_replication()

            rep_res = self._execute_single_replication(
                rep_idx=rep_idx,
                rng=rng,
                sampler=sampler,
                coordinator_factory=coordinator_factory,
                service_templates=service_templates,
                train_generation_config=train_generation_config,
                max_simulation_time_s=max_simulation_time_s,
                dt_s=dt_s,
                measurement_window=effective_window,
            )
            replications.append(rep_res)

            if on_progress is not None:
                on_progress(rep_idx + 1, replication_count)

        # Aggregate distributions and statistics across valid replications
        valid_reps = [r for r in replications if r.status == "SUCCESS"]
        failed_count = len(replications) - len(valid_reps)

        all_journey_times: List[float] = []
        all_arrival_delays: List[float] = []
        all_departure_delays: List[float] = []
        all_tvs_waitings: List[float] = []
        all_headways: List[float] = []
        all_throughputs: List[float] = []
        all_max_queues: List[int] = []

        for r in valid_reps:
            all_journey_times.extend(r.journey_times_s.values())
            all_arrival_delays.extend(r.arrival_delays_s.values())
            all_departure_delays.extend(r.departure_delays_s.values())
            all_tvs_waitings.extend(r.tvs_waiting_times_s.values())
            all_headways.extend(r.headway_results_s)
            all_throughputs.append(r.operational_throughput_tph)
            all_max_queues.append(r.max_queue_length)

        summaries: Dict[str, StatisticalSummary] = {
            "JOURNEY_TIME_S": compute_statistical_summary(all_journey_times, "JOURNEY_TIME", unit="s"),
            "ARRIVAL_DELAY_S": compute_statistical_summary(all_arrival_delays, "ARRIVAL_DELAY", unit="s"),
            "DEPARTURE_DELAY_S": compute_statistical_summary(all_departure_delays, "DEPARTURE_DELAY", unit="s"),
            "TVS_WAITING_TIME_S": compute_statistical_summary(all_tvs_waitings, "TVS_WAITING_TIME", unit="s"),
            "OPERATIONAL_HEADWAY_S": compute_statistical_summary(all_headways, "OPERATIONAL_HEADWAY", unit="s"),
            "OPERATIONAL_THROUGHPUT_TPH": compute_statistical_summary(all_throughputs, "OPERATIONAL_THROUGHPUT", unit="trains/h"),
            "MAX_QUEUE_LENGTH": compute_statistical_summary([float(q) for q in all_max_queues], "MAX_QUEUE_LENGTH", unit="trains"),
        }

        # Evaluate reliability criteria if defined
        rel_eval = None
        if self.reliability_criteria and valid_reps:
            rel_eval = ReliabilityEvaluator.evaluate_replications(
                criteria=self.reliability_criteria,
                arrival_delays_s=all_arrival_delays,
                tvs_waitings_s=all_tvs_waitings,
                max_queues=all_max_queues,
                throughputs_tph=all_throughputs,
                scenario_id=scenario_id,
                total_replications=len(replications),
                valid_replications=len(valid_reps),
            )

        return MonteCarloExecutionResult(
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            total_replications=len(replications),
            valid_replications=len(valid_reps),
            failed_replications=failed_count,
            replications=replications,
            summaries=summaries,
            reliability_evaluation=rel_eval,
            model_warnings=warnings,
        )

    def _execute_single_replication(
        self,
        rep_idx: int,
        rng: np.random.Generator,
        sampler: StochasticParameterSampler,
        coordinator_factory: Callable[[], SignallingCoordinator],
        service_templates: List[ServiceType],
        train_generation_config: List[Tuple[ServiceType, str, float]],
        max_simulation_time_s: float,
        dt_s: float,
        measurement_window: MeasurementWindow,
    ) -> ReplicationResult:
        """P11-STC-004: Execute a single microscopic replication in complete isolation."""
        coord = coordinator_factory()

        # Apply PER_REPLICATION stochastic variables to coordinator or global parameters
        for var_id, var in sampler.variables.items():
            if var.sampling_scope == SamplingScope.PER_REPLICATION:
                sampled_val = sampler.sample_variable(var_id, f"REP_{rep_idx}", rng, rep_idx)
                self._apply_stochastic_parameter_to_coordinator(coord, var, sampled_val)

        # Build modified train instances with PER_TRAIN and PER_STATION_STOP samples
        instances: List[TrainServiceInstance] = []

        for svc_tmpl, train_id, planned_dep_s in train_generation_config:
            # Deepcopy parameters and stops for isolated modification
            mod_params = copy.deepcopy(svc_tmpl.params)
            mod_stops = copy.deepcopy(svc_tmpl.stops)
            eff_dep_s = planned_dep_s

            # PER_TRAIN variables
            for var_id, var in sampler.variables.items():
                if var.sampling_scope == SamplingScope.PER_TRAIN:
                    # Check if target matches this train or service
                    if var.target_object_id is None or var.target_object_id in (train_id, svc_tmpl.service_id, svc_tmpl.train_type_id):
                        val = sampler.sample_variable(var_id, train_id, rng, rep_idx)
                        mod_params, eff_dep_s = self._apply_stochastic_parameter_to_train(mod_params, var, val, eff_dep_s)

            # PER_STATION_STOP variables (e.g. stochastic dwell)
            for stop in mod_stops:
                for var_id, var in sampler.variables.items():
                    if var.sampling_scope == SamplingScope.PER_STATION_STOP:
                        if var.target_object_id is None or var.target_object_id == stop.station_id:
                            val = sampler.sample_variable(var_id, f"{train_id}:{stop.station_id}", rng, rep_idx)
                            if var.target_object_type == TargetObjectType.STATION_DWELL:
                                # Dwell must never fall below minimum configured dwell
                                min_dw = var.min_value if var.min_value is not None else 10.0
                                stop.dwell_time_s = max(min_dw, float(val))

            # Create service variant and instance
            mod_svc = ServiceType(
                service_id=f"{svc_tmpl.service_id}_REP_{rep_idx}",
                train_type_id=svc_tmpl.train_type_id,
                params=mod_params,
                route=svc_tmpl.route,
                stops=mod_stops,
                priority=svc_tmpl.priority,
                running_direction=svc_tmpl.running_direction,
                platform_preferences=copy.deepcopy(svc_tmpl.platform_preferences),
            )
            train_inst = TrainGenerator.create_instance(
                service_type=mod_svc,
                train_id=train_id,
                requested_departure_s=eff_dep_s,
            )
            instances.append(train_inst)

        # Run microscopic multi-train simulation
        try:
            from headway.simulation.multi_train_engine import MultiTrainSimulator
            sim = MultiTrainSimulator(coordinator=coord, dt_s=dt_s, storage_interval_s=1.0)
            sim.register_trains(instances)
            sim_res = sim.run_simulation(max_duration_s=max_simulation_time_s)

            # Extract metrics
            journey_times: Dict[str, float] = {}
            arrival_delays: Dict[str, float] = {}
            departure_delays: Dict[str, float] = {}
            tvs_waitings: Dict[str, float] = {}

            completed_count = len(sim_res.completed_trains)

            for t in sim_res.train_instances:
                # Journey time
                if t.actual_completion_time_s is not None and t.actual_departure_time_s is not None:
                    journey_times[t.train_id] = t.actual_completion_time_s - t.actual_departure_time_s

                # Delays from delay summaries
                ds = sim_res.delay_summaries.get(t.train_id)
                if ds:
                    departure_delays[t.train_id] = ds.departure_delay_s
                    arrival_delays[t.train_id] = ds.arrival_delay_s
                else:
                    if t.actual_departure_time_s is not None:
                        departure_delays[t.train_id] = max(0.0, t.actual_departure_time_s - t.requested_departure_time_s)
                    arrival_delays[t.train_id] = 0.0

            # TVS waiting time from TVS queue tracker
            tvs_wait_s = sim.tvs_queue_tracker.get_total_waiting_time_s()
            tvs_waitings["TOTAL_TVS_WAIT"] = tvs_wait_s
            max_queue = sim.tvs_queue_tracker.get_max_observed_queue_length()

            # Stability evaluation
            stab_eval = self.stability_evaluator.evaluate_simulation(sim_res, run_id=f"REP_{rep_idx}")

            # Operational throughput over measurement window
            tph_res = ThroughputCalculator.calculate_simulation_throughput(
                sim_result=sim_res,
                measurement_window=measurement_window,
            )

            # Operational headways between consecutive departures
            sorted_deps = sorted([t.actual_departure_time_s for t in sim_res.train_instances if t.actual_departure_time_s is not None])
            headways = [sorted_deps[i + 1] - sorted_deps[i] for i in range(len(sorted_deps) - 1)]

            return ReplicationResult(
                replication_id=rep_idx,
                random_seed=int(rng.bit_generator.state["state"]["key"][0]) if "key" in getattr(rng.bit_generator, "state", {}) else rep_idx,
                status="SUCCESS",
                headway_results_s=headways,
                journey_times_s=journey_times,
                arrival_delays_s=arrival_delays,
                departure_delays_s=departure_delays,
                tvs_waiting_times_s=tvs_waitings,
                max_queue_length=max_queue,
                operational_throughput_tph=tph_res.capacity_trains_per_hour,
                stability_status=stab_eval.status,
                is_sustainable=stab_eval.is_sustainable,
                completed_train_count=completed_count,
                total_train_count=len(instances),
            )
        except Exception as e:
            return ReplicationResult(
                replication_id=rep_idx,
                random_seed=rep_idx,
                status="FAILED",
                error_message=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
                completed_train_count=0,
                total_train_count=len(instances),
            )

    @staticmethod
    def _apply_stochastic_parameter_to_train(
        params: RollingStockParameters,
        var: StochasticVariableDefinition,
        val: float,
        current_dep_s: float,
    ) -> Tuple[RollingStockParameters, float]:
        """Apply sampled parameter to rolling stock or departure readiness."""
        import dataclasses
        eff_dep = current_dep_s
        new_params = params
        if var.target_object_type == TargetObjectType.DEPARTURE_READINESS:
            eff_dep += max(0.0, float(val))
        elif var.target_object_type == TargetObjectType.TRACTION_UTILIZATION:
            # Factor in (0, 1]
            factor = max(0.1, min(1.0, float(val)))
            new_params = dataclasses.replace(params, max_tractive_effort_n=params.max_tractive_effort_n * factor)
        elif var.target_object_type == TargetObjectType.BRAKING_UTILIZATION:
            factor = max(0.2, min(1.0, float(val)))
            new_params = dataclasses.replace(params, max_service_deceleration_ms2=params.max_service_deceleration_ms2 * factor)
        return new_params, eff_dep

    @staticmethod
    def _apply_stochastic_parameter_to_coordinator(
        coord: SignallingCoordinator,
        var: StochasticVariableDefinition,
        val: float,
    ) -> None:
        """Apply sampled parameter to coordinator TVS or signalling timings."""
        if var.target_object_type == TargetObjectType.TVS_ENTRY_AUTHORIZATION_DELAY:
            if hasattr(coord, "tvs_controller"):
                for cfg in coord.tvs_controller.configs.values():
                    cfg.auth_processing_delay_s = max(0.1, float(val))
        elif var.target_object_type == TargetObjectType.TVS_RELEASE_DELAY:
            if hasattr(coord, "tvs_controller"):
                for cfg in coord.tvs_controller.configs.values():
                    cfg.tvs.release_delay_s = max(0.0, float(val))
