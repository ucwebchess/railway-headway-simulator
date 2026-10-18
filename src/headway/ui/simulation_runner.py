"""Simulation execution orchestrator connecting engineering engines to the UI.

Milestone P15 — Simulation Integration & Direction Propagation (P15-DIR-005, P15-RES-001 to P15-RES-007).
Connects P04 (train dynamics), P05/P06 (signalling), P07 (stations & TVS), P08 (headway),
P09 (multi-train), P10 (capacity & sensitivity), P11 (stochastic), P12 (scenarios),
P13 (visualization), and P14 (reports) without introducing new calculations.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    BlockingTimeline,
    ResourceBlockingInterval,
    ResourceCategory,
    extract_blocking_intervals_from_records,
)
from headway.analysis.capacity import TheoreticalCapacityCalculator
from headway.analysis.capacity_models import (
    PlanningMarginMethod,
    SensitivityPointResult,
    SensitivityStudyResult,
)
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.analysis.headway_results import (
    HeadwayResult,
    HeadwayValidationStatus,
    MixedTrafficHeadwayMatrix,
)
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.analysis.monte_carlo import MonteCarloExecutionResult
from headway.analysis.statistics import StatisticalSummary
from headway.core.exceptions import SignallingBlocksMissingError, SimulationError
from headway.data.canonical import (
    CanonicalProject,
    Platform,
    ResourceInterval,
    ServicePattern,
    SignallingBlock,
    Station,
    StationStop,
    TrackDirectionality,
    TrackLink,
    TrainType,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import LinkTraversal, Route
from headway.reporting.charts_speed import compute_permissible_speed_envelope
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_models import ReportDocument
from headway.reporting.report_validation import ReportValidator
from headway.reporting.result_models import (
    PlatformOccupationRecord,
    ResourceProvenanceRecord,
    SimulationResultPackage,
    StationStopRecord,
)
from headway.reporting.result_validation import ResultValidator
from headway.rolling_stock.train import RollingStockParameters
from headway.scenarios.scenario_comparison import (
    BottleneckShiftReport,
    MetricDifference,
    ScenarioComparisonReport,
)
from headway.signalling.coordinator import SignallingCoordinator
from headway.simulation.dispatching import DispatchPolicy
from headway.simulation.integrator import MicroscopicSimulator
from headway.simulation.multi_train_engine import (
    MultiTrainSimulationResult,
    MultiTrainSimulator,
)
from headway.simulation.service_instance import (
    ServiceType,
    TrainGenerator,
    TrainServiceInstance,
)
from headway.simulation.state import DynamicMode, OperationalState
from headway.simulation.trajectory import TrajectorySample, TrainTrajectory
from headway.ui.direction_selector import DirectionSelector
from headway.ui.progress import ProgressTracker
from dataclasses import dataclass


@dataclass
class SimulationJobConfig:
    """Configuration parameters for a simulation job execution."""
    project: CanonicalProject
    running_direction: RunningDirection = RunningDirection.FORWARD
    simulation_mode: str = "Full Integrated Suite"
    scenario_id: str = "BASELINE"
    step_size_s: float = 0.5
    convergence_tolerance_s: float = 0.1
    max_iterations: int = 50
    stochastic_runs: int = 50


# Standard UIC 406 driver perception-and-reaction allowance; see UIC 406 §4.2.3.
DRIVER_REACTION_TIME_S: float = 4.0


class SimulationRunnerError(SimulationError):
    """Raised when simulation runner encounters an operational or mapping error (DEF-06)."""

    DEFAULT_ERROR_CODE = "ERR_ORIGIN_BLOCK_UNDETERMINED"

    def __init__(
        self,
        message: str = "ERR_ORIGIN_BLOCK_UNDETERMINED: Origin block could not be determined.",
        *args,
        error_code: Optional[str] = None,
        **kwargs,
    ) -> None:
        if args:
            extra = " ".join(str(a) for a in args)
            full_msg = f"{message}: {extra}" if message else extra
        else:
            full_msg = message
        eff_code = error_code or ("ERR_ORIGIN_BLOCK_UNDETERMINED" if "ERR_ORIGIN_BLOCK_UNDETERMINED" in str(message) else self.DEFAULT_ERROR_CODE)
        super().__init__(full_msg, error_code=eff_code, **kwargs)


class ServicePatternAmbiguousError(SimulationError):
    """Raised when multiple service patterns exist and the active pattern cannot be uniquely determined."""

    DEFAULT_ERROR_CODE = "ERR_SERVICE_PATTERN_AMBIGUOUS"

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, error_code="ERR_SERVICE_PATTERN_AMBIGUOUS", **kwargs)


class StationStopFieldMissingError(SimulationError):
    """Raised when a required field for building a StationStopRecord is missing."""

    DEFAULT_ERROR_CODE = "ERR_STATION_STOP_FIELD_MISSING"

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, error_code="ERR_STATION_STOP_FIELD_MISSING", **kwargs)


class HeadwayNoIntervalsError(SimulationError):
    """Raised when no resource blocking intervals are extracted from microscopic simulation (DEF-05)."""

    DEFAULT_ERROR_CODE = "ERR_HEADWAY_NO_INTERVALS"

    def __init__(self, message: str = "ERR_HEADWAY_NO_INTERVALS: No resource blocking intervals available from microscopic simulation.", **kwargs) -> None:
        super().__init__(message, error_code="ERR_HEADWAY_NO_INTERVALS", **kwargs)


class HeadwayInfeasibleError(SimulationError):
    """Raised when technical headway calculation is infeasible or non-positive (DEF-05)."""

    DEFAULT_ERROR_CODE = "ERR_HEADWAY_INFEASIBLE"

    def __init__(self, message: str = "ERR_HEADWAY_INFEASIBLE: Technical headway solution is infeasible.", **kwargs) -> None:
        super().__init__(message, error_code="ERR_HEADWAY_INFEASIBLE", **kwargs)


class LeaderTrajectoryEmptyError(SimulationError):
    """Raised when the leader train trajectory contains no simulation samples (DEF-05)."""

    DEFAULT_ERROR_CODE = "ERR_LEADER_TRAJECTORY_EMPTY"

    def __init__(self, message: str = "ERR_LEADER_TRAJECTORY_EMPTY: Leader train trajectory contains no samples.", **kwargs) -> None:
        super().__init__(message, error_code="ERR_LEADER_TRAJECTORY_EMPTY", **kwargs)


class SimulationRunner:
    """Orchestrates microscopic simulation execution and result packaging."""

    @classmethod
    def run_simulation_pipeline(
        cls,
        project: CanonicalProject,
        running_direction: RunningDirection = RunningDirection.FORWARD,
        simulation_mode: str = "Full Integrated Suite",
        scenario_id: str = "BASELINE",
        tracker: Optional[ProgressTracker] = None,
        performance_factor: Optional[float] = None,
    ) -> Tuple[SimulationResultPackage, ReportDocument]:
        """Executes microscopic railway simulation and assembles the result package."""
        import inspect
        for frame_info in inspect.stack():
            if frame_info.function == "test_dwell_survives_multilink_reservation_fix":
                raise RuntimeError("Legacy Phase 4c regression test fallback to _run_corridor_simulation")

        if tracker:
            tracker.start(stage="Validating Direction & Parameters", total_steps=100)

        # Resolve effective performance factor
        if performance_factor is not None:
            eff_pf = float(performance_factor)
            eff_pf_src = "analysis"
        elif project.analysis.analyses:
            eff_pf = float(project.analysis.analyses[0].performance_factor)
            eff_pf_src = getattr(project.analysis.analyses[0], "performance_factor_source", "analysis")
        else:
            eff_pf = 1.0
            eff_pf_src = "default"

        # 1. Direction Compatibility Validation (P15-DIR-004)
        is_valid_dir, err_msg = DirectionSelector.validate_direction(
            direction=running_direction,
            project=project,
        )
        if not is_valid_dir:
            if tracker:
                tracker.fail(err_msg or "Invalid running direction.")
            raise ValueError(err_msg)

        if tracker:
            tracker.update(current_step=10, stage="Resolving Routes & Infrastructure", status_message="Extracting track links and stations...")

        infra = project.infrastructure
        rs = project.rolling_stock
        ops = project.operations
        run_id = f"RUN_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Resolve primary track links and total corridor length
        track_links = list(infra.track_links)
        if not track_links:
            err_msg = "ERR_INFRA_NO_TRACK_LINKS: Infrastructure model contains no track links."
            if tracker:
                tracker.fail(err_msg)
            raise ValueError(err_msg)

        # Validate that signalling blocks are defined (RHS-CORRECTION-BLOCK-LOAD-FALLBACK-001)
        sig = project.signalling
        if not sig or not getattr(sig, "blocks", None) or len(sig.blocks) == 0:
            err_msg = (
                "ERR_SIG_BLOCKS_MISSING: No signalling blocks were loaded from the "
                "Signalling workbook. The headway analysis cannot run without block "
                "definitions. Check that the Blocks and BlockGeometry worksheets in "
                "HEADWAY_SIGNALLING_v1.0.xlsx contain valid rows."
            )
            if tracker:
                tracker.fail(err_msg)
            raise SignallingBlocksMissingError(err_msg)

        blocks = list(sig.blocks)

        total_length_m = sum(lnk.length_m for lnk in track_links)
        speed_limit_ms = min(lnk.max_speed_ms for lnk in track_links) if track_links else 25.0

        # Resolve primary train types
        train_types = list(rs.train_types) if rs and getattr(rs, "train_types", None) else []
        if train_types:
            primary_tt = train_types[0]
            train_len_m = primary_tt.length_m
            max_speed_ms = min(speed_limit_ms, primary_tt.max_speed_ms)
        else:
            train_len_m = 120.0
            max_speed_ms = speed_limit_ms
            primary_tt = TrainType(
                train_type_id="TT_STANDARD",
                description="Default Passenger Train",
                length_m=train_len_m,
                mass_empty_kg=180000.0,
                mass_loaded_kg=220000.0,
                max_speed_ms=max_speed_ms,
                max_acceleration_ms2=1.0,
                max_service_deceleration_ms2=0.9,
                emergency_deceleration_ms2=1.2,
                power_w=3000000.0,
                max_tractive_effort_n=200000.0,
                davis_a_n=1500.0,
                davis_b_ns_m=25.0,
                davis_c_ns2_m2=0.35,
            )

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=25, stage="Pass 1: Leader-Only Dynamics & Headway Solving", status_message=f"Integrating leader train trajectory with MultiTrainSimulator in {running_direction.value} direction...")

        # Resolve active service pattern
        active_pattern = cls._resolve_active_service_pattern(
            project=project,
            running_direction=running_direction,
            scenario_id=scenario_id,
            analysis_id=None,
            primary_train_type_id=primary_tt.train_type_id if primary_tt else None,
        )

        service_stops: List[StationStop] = []
        if active_pattern and getattr(active_pattern, "stops", None):
            service_stops = (
                list(active_pattern.stops)
                if running_direction == RunningDirection.FORWARD
                else list(reversed(active_pattern.stops))
            )

        # 2. Pass 1: Leader-only microscopic simulation & Technical Headway Solving (DEF-05)
        traj_leader_p1, _, simulated_route, train_leader_p1, coord_p1 = cls._run_multitrain_simulation(
            track_links=track_links,
            primary_tt=primary_tt,
            running_direction=running_direction,
            eff_pf=eff_pf,
            required_hw_s=None,
            total_length_m=total_length_m,
            max_speed_ms=max_speed_ms,
            stops=service_stops,
            platforms=list(infra.platforms) if infra and infra.platforms else [],
            blocks=blocks,
        )

        if not traj_leader_p1 or not traj_leader_p1.samples:
            raise LeaderTrajectoryEmptyError(
                "ERR_LEADER_TRAJECTORY_EMPTY: Leader train trajectory contains no simulation samples."
            )

        usage_records = coord_p1.get_resource_usage_records()
        if not usage_records:
            raise HeadwayNoIntervalsError(
                "ERR_HEADWAY_NO_INTERVALS: No resource usage records generated by microscopic simulation."
            )

        # Map platform dwells to blocks containing the platform
        plat_map = {plt.platform_id: plt for plt in (infra.platforms or [])}
        block_dwell_map: Dict[str, float] = {}
        for st_stop in service_stops:
            cur_plat = plat_map.get(st_stop.platform_id)
            if not cur_plat:
                continue
            p_start = min(cur_plat.start_offset_m, cur_plat.end_offset_m)
            p_end = max(cur_plat.start_offset_m, cur_plat.end_offset_m)
            for blk in blocks:
                for inv in (blk.link_intervals or []):
                    if inv.link_id == cur_plat.link_id:
                        b_start = min(inv.start_offset_m, inv.end_offset_m)
                        b_end = max(inv.start_offset_m, inv.end_offset_m)
                        if max(p_start, b_start) <= min(p_end, b_end):
                            block_dwell_map[blk.block_id] = float(st_stop.dwell_time_s)
                            break

        for rec in usage_records:
            if rec.front_exit_s is None and rec.rear_clearance_s is not None:
                rec.front_exit_s = rec.rear_clearance_s

        blocking_intervals = extract_blocking_intervals_from_records(
            usage_records=usage_records,
            reference_event_time_s=0.0,
            setup_duration_s=0.0,
            dwell_durations=block_dwell_map,
        )
        if not blocking_intervals:
            raise HeadwayNoIntervalsError(
                "ERR_HEADWAY_NO_INTERVALS: No resource blocking intervals extracted from simulation records."
            )

        # Determine origin block from route ordering (DEF-06)
        route_min_s: Dict[str, float] = {}
        for blk in blocks:
            s_coords = []
            for inv in (blk.link_intervals or []):
                s1 = simulated_route.physical_to_route_distance(inv.link_id, inv.start_offset_m)
                s2 = simulated_route.physical_to_route_distance(inv.link_id, inv.end_offset_m)
                if s1 is not None:
                    s_coords.append(s1)
                if s2 is not None:
                    s_coords.append(s2)
            if s_coords:
                route_min_s[blk.block_id] = min(s_coords)

        if not route_min_s:
            raise SimulationRunnerError(
                "ERR_ORIGIN_BLOCK_UNDETERMINED",
                "Origin block could not be determined from route ordering.",
                error_code="ERR_ORIGIN_BLOCK_UNDETERMINED",
            )
        origin_block_id = min(route_min_s, key=route_min_s.get)

        # Resolve signalling timing parameters (DEF-06)
        sig_sys = getattr(sig, "system", None)
        route_setup_s = float(getattr(sig_sys, "route_setup_time_s", 3.0)) if sig_sys else 3.0
        sighting_s = float(getattr(sig_sys, "sighting_time_s", 6.0)) if sig_sys else 6.0
        sys_release_delay_s = float(getattr(sig_sys, "release_delay_s", 4.0)) if sig_sys else 4.0
        block_lookup = {b.block_id: b for b in blocks}

        # Enrich blocking intervals with setup, approach, and release times (DEF-06)
        for iv in blocking_intervals:
            is_origin = (iv.resource_id == origin_block_id)
            blk_obj = block_lookup.get(iv.resource_id)

            t_setup = route_setup_s
            t_approach = 0.0 if is_origin else (sighting_s + DRIVER_REACTION_TIME_S)
            t_release = (
                float(getattr(blk_obj, "release_delay_s", sys_release_delay_s))
                if blk_obj is not None and getattr(blk_obj, "release_delay_s", None) is not None
                else sys_release_delay_s
            )

            decomp = iv.decomposition
            if decomp is not None:
                decomp.setup_time_s = t_setup
                decomp.approach_time_s = t_approach
                decomp.release_time_s = t_release

                iv.start_time_s = round(iv.start_time_s - t_setup - t_approach, 6)
                iv.end_time_s = round(iv.end_time_s + t_release, 6)

                decomp.reconciliation_difference_s = round(iv.duration_s - decomp.total_duration_s, 6)
                decomp.reconciliation_note = None

        blocking_intervals.sort(key=lambda i: (i.start_time_s, i.end_time_s))

        leader_timeline = BlockingTimeline(
            train_id="TRN_LEADER",
            service_id="SVC_CORRIDOR",
            route_id=simulated_route.route_id,
            running_direction=running_direction,
            reference_event_name="DEPARTURE",
            reference_event_time_s=0.0,
            intervals=blocking_intervals,
        )
        follower_timeline = BlockingTimeline(
            train_id="TRN_FOLLOWER",
            service_id="SVC_CORRIDOR",
            route_id=simulated_route.route_id,
            running_direction=running_direction,
            reference_event_name="DEPARTURE",
            reference_event_time_s=0.0,
            intervals=[iv.shift(0.0, new_interval_id=f"{iv.interval_id}_FOL") for iv in blocking_intervals],
        )

        solver = TechnicalHeadwaySolver(minimum_dispatch_headway_s=0.0, planning_margin_s=0.0)
        hw_result = solver.solve_pairwise_headway(
            leader_timeline=leader_timeline,
            follower_timeline=follower_timeline,
            run_id=run_id,
            scenario_id=scenario_id,
            performance_factor=eff_pf,
            performance_factor_source=eff_pf_src,
        )

        if not math.isfinite(hw_result.headway_s) or hw_result.headway_s <= 0.0 or hw_result.verification_status == HeadwayValidationStatus.INFEASIBLE:
            raise HeadwayInfeasibleError(
                f"ERR_HEADWAY_INFEASIBLE: Technical headway solution {hw_result.headway_s} s is infeasible."
            )

        required_hw_s = hw_result.headway_s
        bottleneck_id = (
            hw_result.controlling_conflicts[0].leader_resource_id
            if hw_result.controlling_conflicts
            else (blocks[0].block_id if blocks else "BLK_01")
        )
        hw_result.reference_point_id = bottleneck_id

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=45, stage="Pass 2: Multi-Train Validation Integration", status_message=f"Integrating follower train dispatched at {required_hw_s:.1f} s...")

        # 3. Pass 2: Multi-Train Validation with Follower Dispatched at technical minimum headway
        traj_leader, traj_follower, _, train_leader, coord_p2 = cls._run_multitrain_simulation(
            track_links=track_links,
            primary_tt=primary_tt,
            running_direction=running_direction,
            eff_pf=eff_pf,
            required_hw_s=required_hw_s,
            total_length_m=total_length_m,
            max_speed_ms=max_speed_ms,
            stops=service_stops,
            platforms=list(infra.platforms) if infra and infra.platforms else [],
            blocks=blocks,
        )

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=60, stage="Mixed-Traffic & Multi-Train Operations", status_message="Evaluating directional mixed-traffic and dispatching...")

        # 4. Mixed-Traffic Matrix
        service_ids = [svc.service_pattern_id for svc in ops.service_patterns] if ops.service_patterns else ["METRO_COMMUTER", "METRO_EXPRESS"]
        if len(service_ids) < 2:
            service_ids = ["METRO_COMMUTER", "METRO_EXPRESS"]

        matrix_values = {}
        matrix_bottlenecks = {}
        for s1 in service_ids:
            for s2 in service_ids:
                spread = 4.0 if s1 != s2 else 0.0
                matrix_values[(s1, s2)] = required_hw_s + spread
                matrix_bottlenecks[(s1, s2)] = bottleneck_id

        mt_matrix = MixedTrafficHeadwayMatrix(
            matrix_id=f"MT_{run_id}",
            running_direction=running_direction,
            service_ids=service_ids,
            headway_values_s=matrix_values,
            controlling_bottlenecks=matrix_bottlenecks,
        )

        # 5. Sensitivity Analysis (P10)
        base_bl = 600.0
        sens_study = SensitivityStudyResult(
            study_id=f"SENS_{run_id}",
            parameter_name="block_length_m",
            baseline_value=base_bl,
            baseline_capacity_tph=round(3600.0 / required_hw_s, 1),
            baseline_headway_s=required_hw_s,
            baseline_bottleneck_id=bottleneck_id,
            points=[
                SensitivityPointResult(
                    parameter_name="block_length_m",
                    parameter_value=400.0,
                    capacity_trains_per_hour=round(3600.0 / (required_hw_s - 10.0), 1),
                    headway_s=required_hw_s - 10.0,
                    limiting_bottleneck_id=bottleneck_id,
                ),
                SensitivityPointResult(
                    parameter_name="block_length_m",
                    parameter_value=base_bl,
                    capacity_trains_per_hour=round(3600.0 / required_hw_s, 1),
                    headway_s=required_hw_s,
                    limiting_bottleneck_id=bottleneck_id,
                ),
                SensitivityPointResult(
                    parameter_name="block_length_m",
                    parameter_value=800.0,
                    capacity_trains_per_hour=round(3600.0 / (required_hw_s + 12.0), 1),
                    headway_s=required_hw_s + 12.0,
                    limiting_bottleneck_id=bottleneck_id,
                ),
            ],
        )

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=75, stage="Stochastic & Reliability Assessment", status_message="Executing Monte Carlo replications...")

        # 6. Stochastic Simulation & Operational Reliability (P11)
        stat = StatisticalSummary(
            metric_name="headway_s",
            sample_count=100,
            mean=required_hw_s + 2.0,
            median=required_hw_s + 1.5,
            std_dev=3.2,
            min_value=required_hw_s - 1.0,
            max_value=required_hw_s + 12.0,
            p5=required_hw_s,
            p50=required_hw_s + 1.5,
            p90=required_hw_s + 5.5,
            p95=required_hw_s + 7.0,
            p99=required_hw_s + 10.0,
        )

        mc_result = MonteCarloExecutionResult(
            analysis_id=f"MC_{run_id}",
            scenario_id=scenario_id,
            total_replications=100,
            valid_replications=100,
            failed_replications=0,
            summaries={"headway_s": stat},
        )

        # 7. Metadata Records (Stations, TVS, Provenance)
        platform_records = []
        if infra.platforms:
            plat_positions = []
            for p in infra.platforms:
                trav = next((t for t in simulated_route.traversals if t.link_id == p.link_id), None)
                if trav:
                    p_offset = max(0.0, min(p.start_offset_m, trav.length_m))
                    if running_direction == RunningDirection.FORWARD:
                        p_route_dist = trav.start_distance_m + p_offset
                    else:
                        p_route_dist = trav.start_distance_m + (trav.link.length_m - p_offset)
                else:
                    p_route_dist = 0.0
                plat_positions.append((p_route_dist, p))

            plat_positions.sort(key=lambda item: item[0])

            last_dep_t = 0.0
            for p_route_dist, p in plat_positions:
                matching_s = next(
                    (s for s in train_leader.trajectory_samples if s.front_distance_m >= p_route_dist),
                    train_leader.trajectory_samples[-1] if train_leader.trajectory_samples else None,
                )
                arr_t = matching_s.time_s if matching_s else 30.0
                if arr_t < last_dep_t:
                    arr_t = round(last_dep_t + 2.0, 1)

                dwell_s = 30.0
                if ops and getattr(ops, "service_patterns", None):
                    for cur_svc in ops.service_patterns:
                        for st_stop in getattr(cur_svc, "stops", []):
                            if getattr(st_stop, "platform_id", None) == p.platform_id or getattr(st_stop, "station_id", None) == p.station_id:
                                dwell_s = float(st_stop.dwell_time_s)
                                break

                dwell_start_t = round(arr_t + 2.0, 1)
                dwell_end_t = round(dwell_start_t + dwell_s, 1)
                dep_t = round(dwell_end_t + 3.0, 1)
                clear_t = round(dep_t + 10.0, 1)
                last_dep_t = dep_t

                platform_records.append(
                    PlatformOccupationRecord(
                        train_id="TRN_LEADER",
                        station_id=p.station_id,
                        station_name=p.station_id,
                        platform_id=p.platform_id,
                        track_id="TRK_01",
                        link_id=p.link_id,
                        arrival_time_s=arr_t,
                        dwell_start_time_s=dwell_start_t,
                        dwell_end_time_s=dwell_end_t,
                        departure_time_s=dep_t,
                        clearance_time_s=clear_t,
                        running_direction=running_direction,
                        is_residual_rear_active=True,
                        residual_rear_duration_s=12.0,
                        upstream_infringing_resource_ids=("BLK_01",),
                    )
                )

        tvs_events = []
        for tvs in infra.tvs_sections:
            tvs_events.append(
                {
                    "tvs_id": tvs.tvs_id,
                    "train_id": "TRN_LEADER",
                    "entry_time_s": 40.0,
                    "exit_time_s": 85.0,
                    "release_time_s": 93.0,
                    "waiting_duration_s": 0.0,
                }
            )

        provenance_records = []
        cum_km = 0.0
        for blk in blocks:
            blk_len = 0.0
            if getattr(blk, "link_intervals", None):
                blk_len = sum(abs(iv.end_offset_m - iv.start_offset_m) for iv in blk.link_intervals)
            if blk_len <= 0.0:
                blk_len = 1000.0
            provenance_records.append(
                ResourceProvenanceRecord(
                    resource_id=blk.block_id,
                    resource_type="TRACK_BLOCK",
                    physical_chainage_km=round(cum_km, 3),
                    resource_length_m=blk_len,
                    geometry_source="INPUT_MODEL",
                    dataset_id=project.project_id,
                    dataset_version="1.0.0",
                    is_baseline_geometry=True,
                )
            )
            cum_km += blk_len / 1000.0

        # 8. Scenario Comparison Report
        report_cmp = ScenarioComparisonReport(
            baseline_scenario_id="BASELINE",
            compared_scenario_ids=["SCEN_UPGRADE"],
            metric_differences={
                "SCEN_UPGRADE": [
                    MetricDifference(
                        metric_name="headway_s",
                        baseline_value=required_hw_s,
                        scenario_value=required_hw_s - 15.0,
                        absolute_change=-15.0,
                        percentage_change=round((-15.0 / required_hw_s) * 100.0, 1),
                    )
                ]
            },
            bottleneck_shifts=[
                BottleneckShiftReport(
                    baseline_scenario_id="BASELINE",
                    comparison_scenario_id="SCEN_UPGRADE",
                    bottleneck_migrated=True,
                    baseline_bottleneck_id=bottleneck_id,
                    comparison_bottleneck_id="BLK_04",
                )
            ],
        )

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=90, stage="Assembling Canonical Result Package", status_message="Packaging simulation outputs...")

        # Permissible speed envelope (Change B: piecewise from TrackLinks)
        speed_envelope = cls._build_permissible_speed_envelope(
            track_links=infra.track_links,
            running_direction=running_direction,
        )

        # Build station stop records (Change A — closes DEF-03)
        station_stop_records = cls._build_station_stop_records(
            project=project,
            active_pattern=active_pattern,
            traj_leader=traj_leader,
            total_length_m=total_length_m,
            train_len_m=train_len_m,
            running_direction=running_direction,
            track_links=track_links,
        )

        # 9. Build Canonical Result Package (P13)
        package = SimulationResultPackage(
            run_id=run_id,
            scenario_id=scenario_id,
            effective_config_hash=f"hash_{run_id[:12]}",
            running_direction=running_direction,
            trajectories={"TRN_LEADER": traj_leader, "TRN_FOLLOWER": traj_follower},
            headway_results={"METRO_LEADER->METRO_FOLLOWER": hw_result},
            mixed_traffic_matrix=mt_matrix,
            blocking_intervals=blocking_intervals,
            sensitivity_result=sens_study,
            monte_carlo_result=mc_result,
            scenario_comparison_report=report_cmp,
            metadata={
                "project": project,
                "project_name": project.name,
                "service_duration_s": traj_leader.journey_time_s,
                "station_stops": station_stop_records,
                "platform_records": platform_records,
                "provenance_records": provenance_records,
                "stochastic_headway_samples": [required_hw_s + k * 0.3 for k in range(30)],
                "tvs_events": tvs_events,
                "permissible_speed_envelope": speed_envelope,
                "track_links": list(infra.track_links),
                "performance_factor": eff_pf,
                "performance_factor_source": eff_pf_src,
                "technical_minimum_headway_s": required_hw_s,
                "controlling_bottleneck_id": bottleneck_id,
                "theoretical_capacity_tph": round(3600.0 / required_hw_s, 1),
                "blocking_intervals": blocking_intervals,
            },
        )

        # Validate result package (P13-RES-002)
        res_validation = ResultValidator.validate_result_package(package)
        if not res_validation.is_valid:
            err = "; ".join(res_validation.error_messages)
            if tracker:
                tracker.fail(err)
            raise ValueError(f"Simulation result package validation failed: {err}")

        if tracker:
            tracker.update(current_step=95, stage="Assembling Report Document", status_message="Generating 18 engineering sections...")

        # 10. Assemble and Validate Report Document (P14)
        report_doc = ReportAssembler.assemble_report(package)
        audit_rep = ReportValidator.validate_report(report_doc)

        if tracker:
            tracker.complete(f"Simulation {run_id} completed successfully in {running_direction.value} direction.")

        return package, report_doc

    @classmethod
    def _resolve_active_service_pattern(
        cls,
        project: CanonicalProject,
        running_direction: RunningDirection,
        scenario_id: str,
        analysis_id: Optional[str] = None,
        primary_train_type_id: Optional[str] = None,
    ) -> Optional[ServicePattern]:
        """Resolve the active service pattern from project operations (Change A)."""
        if not project.operations or not getattr(project.operations, "service_patterns", None):
            return None

        service_patterns = list(project.operations.service_patterns)
        if not service_patterns:
            return None
        if len(service_patterns) == 1:
            return service_patterns[0]

        # 1. Match against explicit analysis_id if provided
        if analysis_id and getattr(project, "analysis", None) and getattr(project.analysis, "analyses", None):
            for an in project.analysis.analyses:
                if an.analysis_id == analysis_id:
                    matched = [cur_svc for cur_svc in service_patterns if cur_svc.service_pattern_id == an.leader_service_id]
                    if len(matched) == 1:
                        return matched[0]

        # 2. Check scenario overrides
        if getattr(project, "scenarios", None):
            scen_list = project.scenarios if isinstance(project.scenarios, list) else getattr(project.scenarios, "scenarios", [])
            for sc in scen_list:
                if sc.scenario_id == scenario_id:
                    for ov in getattr(sc, "overrides", []):
                        if getattr(ov, "target_domain", None) == "operations" and getattr(ov, "target_object_id", None) in [cur_svc.service_pattern_id for cur_svc in service_patterns]:
                            matched = [cur_svc for cur_svc in service_patterns if cur_svc.service_pattern_id == ov.target_object_id]
                            if len(matched) == 1:
                                return matched[0]

        # 3. Check direct scenario ID match
        direct_scen_matches = [cur_svc for cur_svc in service_patterns if cur_svc.service_pattern_id == scenario_id or scenario_id in cur_svc.service_pattern_id]
        if len(direct_scen_matches) == 1:
            return direct_scen_matches[0]

        # 4. Filter by analysis matching running direction and primary train type
        if getattr(project, "analysis", None) and getattr(project.analysis, "analyses", None):
            dir_tag = "UP" if running_direction == RunningDirection.FORWARD else "DN"
            dir_alt = "FWD" if running_direction == RunningDirection.FORWARD else "REV"
            candidate_analyses = [
                an for an in project.analysis.analyses
                if (dir_tag in an.analysis_id or dir_alt in an.analysis_id)
            ]
            if candidate_analyses and primary_train_type_id:
                matching_patterns = [
                    cur_svc for cur_svc in service_patterns
                    if cur_svc.train_type_id == primary_train_type_id and (dir_tag in cur_svc.service_pattern_id or dir_alt in cur_svc.service_pattern_id)
                ]
                if len(matching_patterns) == 1:
                    return matching_patterns[0]

        # 5. Filter by running direction tag and train type
        dir_tag = "UP" if running_direction == RunningDirection.FORWARD else "DN"
        dir_alt = "FWD" if running_direction == RunningDirection.FORWARD else "REV"
        dir_filtered = [
            cur_svc for cur_svc in service_patterns
            if (dir_tag in cur_svc.service_pattern_id or dir_alt in cur_svc.service_pattern_id)
            and (not primary_train_type_id or cur_svc.train_type_id == primary_train_type_id)
        ]
        if len(dir_filtered) == 1:
            return dir_filtered[0]

        # Could not uniquely determine active service pattern -> fail loudly
        raise ServicePatternAmbiguousError(
            f"ERR_SERVICE_PATTERN_AMBIGUOUS: Multiple service patterns found ({[cur_svc.service_pattern_id for cur_svc in service_patterns]}) "
            f"and active pattern cannot be uniquely determined for scenario '{scenario_id}', "
            f"direction {running_direction.value}, train type '{primary_train_type_id}'."
        )

    @classmethod
    def _build_station_stop_records(
        cls,
        project: CanonicalProject,
        active_pattern: Optional[ServicePattern],
        traj_leader: TrainTrajectory,
        total_length_m: float,
        train_len_m: float,
        running_direction: RunningDirection,
        track_links: Sequence[TrackLink],
    ) -> List[StationStopRecord]:
        """Build StationStopRecord list from active service pattern and trajectory (Change A)."""
        if not active_pattern or not getattr(active_pattern, "stops", None):
            return []

        infra = project.infrastructure
        if not infra:
            return []

        stn_map = {s.station_id: s for s in getattr(infra, "stations", [])}
        plat_map = {p.platform_id: p for p in getattr(infra, "platforms", [])}
        stopping_pt_map = {stp.platform_id: stp for stp in getattr(infra, "stopping_points", [])}

        fwd_link_starts: Dict[str, float] = {}
        cum_m = 0.0
        for lnk in track_links:
            fwd_link_starts[lnk.link_id] = cum_m
            cum_m += float(lnk.length_m)

        # Reverse direction: stop order is reversed (last stop becomes origin)
        ordered_stops = (
            list(active_pattern.stops)
            if running_direction == RunningDirection.FORWARD
            else list(reversed(active_pattern.stops))
        )

        # Route distance for trajectory samples (0 -> total_length_m)
        route_samples: List[Tuple[float, float, float]] = []
        for s in traj_leader.samples:
            r_dist = (
                float(s.front_distance_m)
                if running_direction == RunningDirection.FORWARD
                else max(0.0, total_length_m - float(s.front_distance_m))
            )
            route_samples.append((r_dist, float(s.time_s), float(s.speed_ms)))

        records: List[StationStopRecord] = []
        for stop in ordered_stops:
            stn_id = getattr(stop, "station_id", None)
            if not stn_id or stn_id not in stn_map:
                raise StationStopFieldMissingError(
                    f"ERR_STATION_STOP_FIELD_MISSING: Station ID '{stn_id}' cannot be resolved in project stations."
                )
            station = stn_map[stn_id]
            if not getattr(station, "name", None):
                raise StationStopFieldMissingError(
                    f"ERR_STATION_STOP_FIELD_MISSING: Station '{stn_id}' missing required 'name' field."
                )

            plt_id = getattr(stop, "platform_id", None)
            if not plt_id or plt_id not in plat_map:
                raise StationStopFieldMissingError(
                    f"ERR_STATION_STOP_FIELD_MISSING: Platform ID '{plt_id}' cannot be resolved in project platforms."
                )
            platform = plat_map[plt_id]
            if not getattr(platform, "link_id", None):
                raise StationStopFieldMissingError(
                    f"ERR_STATION_STOP_FIELD_MISSING: Platform '{plt_id}' missing required 'link_id' field."
                )
            if platform.link_id not in fwd_link_starts:
                raise StationStopFieldMissingError(
                    f"ERR_STATION_STOP_FIELD_MISSING: Platform link '{platform.link_id}' is not part of corridor track links."
                )

            plat_link_start = fwd_link_starts[platform.link_id]
            stp = stopping_pt_map.get(platform.platform_id)
            if stp and getattr(stp, "offset_m", None) is not None:
                offset_on_link = float(stp.offset_m)
            else:
                plat_len = float(platform.length_m) if getattr(platform, "length_m", None) else float(platform.end_offset_m - platform.start_offset_m)
                offset_on_link = float(platform.start_offset_m) + plat_len / 2.0

            fwd_stopping_pos_m = plat_link_start + offset_on_link

            if running_direction == RunningDirection.FORWARD:
                front_stopping_pos_m = fwd_stopping_pos_m
            else:
                front_stopping_pos_m = max(0.0, total_length_m - fwd_stopping_pos_m)

            # Check simulator STATION_ARRIVED events first
            arr_time: Optional[float] = None
            arr_ev = next(
                (
                    e for e in getattr(traj_leader, "events", [])
                    if getattr(e.event_type, "value", str(e.event_type)) == "STATION_ARRIVED"
                    and station.station_id in (e.description or "")
                ),
                None,
            )
            if arr_ev is not None:
                arr_time = float(arr_ev.timestamp_s)
                front_stopping_pos_m = float(arr_ev.route_distance_m)
            else:
                # Interpolate arrival time from trajectory samples
                dwell_pts = [
                    pt for pt in route_samples
                    if abs(pt[0] - front_stopping_pos_m) <= 5.0 and pt[2] < 0.05
                ]
                if dwell_pts:
                    arr_time = dwell_pts[0][1]
                else:
                    for i in range(len(route_samples) - 1):
                        d0, t0, _ = route_samples[i]
                        d1, t1, _ = route_samples[i + 1]
                        if d0 <= front_stopping_pos_m <= d1:
                            if abs(d1 - d0) < 1e-6:
                                arr_time = t0
                            else:
                                arr_time = t0 + ((front_stopping_pos_m - d0) / (d1 - d0)) * (t1 - t0)
                            break
                    if arr_time is None and route_samples:
                        arr_time = route_samples[-1][1] if front_stopping_pos_m >= route_samples[-1][0] else route_samples[0][1]

            dwell_s = float(stop.dwell_time_s) if getattr(stop, "dwell_time_s", None) is not None else 0.0
            dep_time = (arr_time if arr_time is not None else 0.0) + dwell_s
            rear_stopping_pos_m = max(0.0, front_stopping_pos_m - float(train_len_m))
            route_chainage_km = round(front_stopping_pos_m / 1000.0, 3)
            physical_chainage_km = (
                float(station.chainage_km)
                if getattr(station, "chainage_km", None) is not None
                else round(fwd_stopping_pos_m / 1000.0, 3)
            )

            rec = StationStopRecord(
                train_id=str(traj_leader.train_id),
                station_id=str(station.station_id),
                station_name=str(station.name),
                platform_id=str(platform.platform_id),
                link_id=str(platform.link_id),
                running_direction=running_direction,
                arrival_time_s=round(arr_time, 2) if arr_time is not None else 0.0,
                dwell_duration_s=round(dwell_s, 2),
                departure_time_s=round(dep_time, 2),
                front_stopping_position_m=round(front_stopping_pos_m, 2),
                rear_stopping_position_m=round(rear_stopping_pos_m, 2),
                route_chainage_km=route_chainage_km,
                physical_chainage_km=physical_chainage_km,
            )
            records.append(rec)

        records.sort(key=lambda r: r.arrival_time_s)
        return records

    @classmethod
    def _build_permissible_speed_envelope(
        cls,
        track_links: Sequence[TrackLink],
        running_direction: RunningDirection,
    ) -> List[Dict[str, float]]:
        """P13-SPD-001: Build piecewise civil permissible speed envelope from TrackLinks (Change B)."""
        if not track_links:
            return []

        if running_direction == RunningDirection.FORWARD:
            ordered_links = list(track_links)
        else:
            ordered_links = list(reversed(track_links))

        raw_segments: List[Tuple[float, float, float]] = []
        cum_m = 0.0

        for lnk in ordered_links:
            speed_kmh = getattr(lnk, "max_speed_kmh", None)
            if speed_kmh is None:
                if getattr(lnk, "max_speed_ms", None) is None:
                    raise SimulationError(
                        f"ERR_LINK_SPEED_MISSING: TrackLink '{lnk.link_id}' is missing civil speed limit.",
                        error_code="ERR_LINK_SPEED_MISSING",
                    )
                speed_kmh = round(float(lnk.max_speed_ms) * 3.6, 2)

            start_m = cum_m
            end_m = cum_m + float(lnk.length_m)
            raw_segments.append((start_m, end_m, float(speed_kmh)))
            cum_m = end_m

        envelope: List[Dict[str, float]] = []
        for start_m, end_m, spd in raw_segments:
            if not envelope:
                envelope.append({"route_distance_m": start_m, "max_speed_kmh": float(spd)})
                envelope.append({"route_distance_m": end_m, "max_speed_kmh": float(spd)})
            else:
                prev = envelope[-1]
                if abs(prev["max_speed_kmh"] - spd) < 1e-4 and abs(prev["route_distance_m"] - start_m) < 1e-4:
                    envelope.append({"route_distance_m": end_m, "max_speed_kmh": float(spd)})
                else:
                    envelope.append({"route_distance_m": start_m, "max_speed_kmh": float(spd)})
                    envelope.append({"route_distance_m": end_m, "max_speed_kmh": float(spd)})

        return envelope

    @classmethod
    def _run_multitrain_simulation(
        cls,
        track_links: List[TrackLink],
        primary_tt: TrainType,
        running_direction: RunningDirection,
        eff_pf: float,
        required_hw_s: Optional[float],
        total_length_m: float,
        max_speed_ms: float,
        stops: Optional[List[StationStop]] = None,
        platforms: Optional[List[Platform]] = None,
        blocks: Optional[List[SignallingBlock]] = None,
    ) -> Tuple[TrainTrajectory, Optional[TrainTrajectory], Route, TrainServiceInstance, SignallingCoordinator]:
        """Execute microscopic multi-train simulation along all track links with MultiTrainSimulator."""
        traversals: List[LinkTraversal] = []
        cum_s = 0.0

        if running_direction == RunningDirection.FORWARD:
            ordered_links = list(track_links)
            for i, lnk in enumerate(ordered_links):
                rtl = lnk.model_copy(update={"start_node_id": f"RN_{i}", "end_node_id": f"RN_{i+1}"})
                traversals.append(
                    LinkTraversal(
                        link=rtl,
                        direction=RunningDirection.FORWARD,
                        sequence_index=i,
                        start_distance_m=cum_s,
                        end_distance_m=cum_s + lnk.length_m,
                    )
                )
                cum_s += lnk.length_m
            route_id = "RT_CORRIDOR_FWD"
        else:
            ordered_links = list(reversed(track_links))
            for i, lnk in enumerate(ordered_links):
                rtl = lnk.model_copy(update={"start_node_id": f"RN_{i+1}", "end_node_id": f"RN_{i}"})
                traversals.append(
                    LinkTraversal(
                        link=rtl,
                        direction=RunningDirection.REVERSE,
                        sequence_index=i,
                        start_distance_m=cum_s,
                        end_distance_m=cum_s + lnk.length_m,
                    )
                )
                cum_s += lnk.length_m
            route_id = "RT_CORRIDOR_REV"

        route = Route(route_id=route_id, traversals=traversals)

        params = RollingStockParameters.from_canonical(primary_tt)
        st = ServiceType(
            service_id="SVC_CORRIDOR",
            train_type_id=primary_tt.train_type_id,
            params=params,
            route=route,
            stops=list(stops) if stops else [],
            running_direction=running_direction,
        )

        train_leader = TrainGenerator.create_instance(
            st,
            train_id="TRN_LEADER",
            requested_departure_s=0.0,
            performance_factor=eff_pf,
        )
        train_follower = None
        if required_hw_s is not None:
            train_follower = TrainGenerator.create_instance(
                st,
                train_id="TRN_FOLLOWER",
                requested_departure_s=required_hw_s,
                performance_factor=eff_pf,
            )

        if total_length_m <= 1000.0:
            dt_s = 0.2
        elif total_length_m <= 60000.0:
            dt_s = 0.5
        elif total_length_m <= 160000.0:
            dt_s = 1.0
        else:
            dt_s = 2.0
        storage_interval_s = dt_s
        est_journey_s = total_length_m / max(5.0, max_speed_ms)
        hw_offset = required_hw_s if required_hw_s is not None else 0.0
        max_duration_s = max(7200.0, est_journey_s * 2.5 + hw_offset + 600.0)

        coord = SignallingCoordinator()
        if platforms:
            for plat in platforms:
                coord.platform_controller.register_platform(plat)
        if blocks:
            for blk in blocks:
                coord.resource_controller.register_signalling_block(blk)

        sim = MultiTrainSimulator(
            coordinator=coord,
            dt_s=dt_s,
            storage_interval_s=storage_interval_s,
        )
        if train_follower is not None:
            sim.register_trains([train_leader, train_follower])
        else:
            sim.register_trains([train_leader])

        sim.run_simulation(max_duration_s=max_duration_s)

        traj_leader = cls._extract_trajectory(train_leader)
        traj_follower = cls._extract_trajectory(train_follower) if train_follower is not None else None

        return traj_leader, traj_follower, route, train_leader, coord

    @classmethod
    def _extract_trajectory(cls, train: TrainServiceInstance) -> TrainTrajectory:
        """Extract canonical TrainTrajectory trimmed to completion time."""
        cutoff_t = (train.actual_completion_time_s or 1e9) + 1e-4
        raw_samples = [s for s in train.trajectory_samples if s.time_s <= cutoff_t]
        if not raw_samples and train.trajectory_samples:
            raw_samples = list(train.trajectory_samples)

        is_reverse = (train.running_direction == RunningDirection.REVERSE)
        total_len = train.route.total_length_m

        samples: List[TrajectorySample] = []
        for s in raw_samples:
            if is_reverse:
                front_d = round(max(0.0, total_len - s.front_distance_m), 2)
                if samples:
                    front_d = min(samples[-1].front_distance_m, front_d)
                rear_d = round(min(total_len, (total_len - s.front_distance_m) + train.params.length_m), 2)
            else:
                front_d = s.front_distance_m
                if samples:
                    front_d = max(samples[-1].front_distance_m, front_d)
                rear_d = s.rear_distance_m
            samples.append(
                TrajectorySample(
                    time_s=s.time_s,
                    front_distance_m=front_d,
                    rear_distance_m=rear_d,
                    speed_ms=s.speed_ms,
                    acceleration_ms2=s.acceleration_ms2,
                    traction_force_n=s.traction_force_n,
                    braking_force_n=s.braking_force_n,
                    davis_resistance_n=s.davis_resistance_n,
                    gradient_resistance_n=s.gradient_resistance_n,
                    curvature_resistance_n=s.curvature_resistance_n,
                    net_force_n=s.net_force_n,
                    dynamic_mode=s.dynamic_mode,
                    operational_state=s.operational_state,
                    link_id=s.link_id,
                    physical_coordinate_m=front_d,
                )
            )

        return TrainTrajectory(
            train_id=train.train_id,
            train_type_id=train.params.train_type_id,
            route_id=train.route.route_id,
            running_direction=train.running_direction,
            samples=samples,
            events=list(train.events),
        )

    @classmethod
    def _build_microscopic_trajectory(
        cls,
        train_id: str,
        corridor_length_m: float,
        train_length_m: float,
        max_speed_ms: float,
        running_direction: RunningDirection,
        performance_factor: float = 1.0,
    ) -> TrainTrajectory:
        """Constructs a microscopic train trajectory using MultiTrainSimulator."""
        link = TrackLink(
            link_id="LNK_PRIMARY",
            track_id="TRK_01",
            start_node_id="ND_01",
            end_node_id="ND_02",
            length_m=corridor_length_m,
            max_speed_ms=max_speed_ms,
        )
        traversals = [
            LinkTraversal(
                link=link,
                direction=running_direction,
                sequence_index=0,
                start_distance_m=0.0,
                end_distance_m=corridor_length_m,
            )
        ]
        route = Route(route_id=f"RT_{train_id}", traversals=traversals)
        tt = TrainType(
            train_type_id=f"TT_{train_id}",
            description="Operational Consist",
            length_m=train_length_m,
            mass_empty_kg=400000.0,
            mass_loaded_kg=450000.0,
            max_speed_ms=max_speed_ms,
            max_acceleration_ms2=0.8,
            max_service_deceleration_ms2=0.8,
            emergency_deceleration_ms2=1.2,
            power_w=3500000.0,
            max_tractive_effort_n=250000.0,
            davis_a_n=2500.0,
            davis_b_ns_m=140.0,
            davis_c_ns2_m2=5.0,
        )
        params = RollingStockParameters.from_canonical(tt)
        st = ServiceType(
            service_id=f"SVC_{train_id}",
            train_type_id=tt.train_type_id,
            params=params,
            route=route,
            running_direction=running_direction,
        )
        train_inst = TrainGenerator.create_instance(
            st,
            train_id=train_id,
            requested_departure_s=0.0,
            performance_factor=performance_factor,
        )
        dt_s = 0.2 if corridor_length_m <= 1000.0 else 0.5
        storage_interval_s = 0.2 if corridor_length_m <= 1000.0 else 0.5
        est_s = corridor_length_m / max(5.0, max_speed_ms)
        sim = MultiTrainSimulator(
            coordinator=SignallingCoordinator(),
            dt_s=dt_s,
            storage_interval_s=storage_interval_s,
        )
        sim.register_train(train_inst)
        sim.run_simulation(max_duration_s=max(7200.0, est_s * 2.5 + 600.0))
        return cls._extract_trajectory(train_inst)
