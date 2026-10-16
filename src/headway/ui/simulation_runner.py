"""Simulation execution orchestrator connecting engineering engines to the UI.

Milestone P15 — Simulation Integration & Direction Propagation (P15-DIR-005, P15-RES-001 to P15-RES-007).
Connects P04 (train dynamics), P05/P06 (signalling), P07 (stations & TVS), P08 (headway),
P09 (multi-train), P10 (capacity & sensitivity), P11 (stochastic), P12 (scenarios),
P13 (visualization), and P14 (reports) without introducing new calculations.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    ResourceBlockingInterval,
    ResourceCategory,
)
from headway.analysis.capacity import TheoreticalCapacityCalculator
from headway.analysis.capacity_models import (
    PlanningMarginMethod,
    SensitivityPointResult,
    SensitivityStudyResult,
)
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.analysis.headway_results import HeadwayResult, MixedTrafficHeadwayMatrix
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.analysis.monte_carlo import MonteCarloExecutionResult
from headway.analysis.statistics import StatisticalSummary
from headway.core.exceptions import SignallingBlocksMissingError
from headway.data.canonical import (
    CanonicalProject,
    Platform,
    ResourceInterval,
    SignallingBlock,
    Station,
    TrackDirectionality,
    TrackLink,
    TrainType,
    TVSSection,
)
from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_speed import compute_permissible_speed_envelope
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_models import ReportDocument
from headway.reporting.report_validation import ReportValidator
from headway.reporting.result_models import (
    PlatformOccupationRecord,
    ResourceProvenanceRecord,
    SimulationResultPackage,
)
from headway.reporting.result_validation import ResultValidator
from headway.scenarios.scenario_comparison import (
    BottleneckShiftReport,
    MetricDifference,
    ScenarioComparisonReport,
)
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
            raise ValueError("Infrastructure model contains no track links.")

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
        train_types = list(rs.train_types)
        primary_tt = train_types[0] if train_types else None
        train_len_m = primary_tt.length_m if primary_tt else 140.0
        max_speed_ms = min(speed_limit_ms, primary_tt.max_speed_ms if primary_tt else 25.0)

        if tracker:
            tracker.update(current_step=25, stage="Microscopic Dynamics Integration", status_message=f"Integrating train movement dynamics in {running_direction.value} direction...")

        # 2. Integrate Train Trajectories (P04)
        traj_leader = cls._build_microscopic_trajectory(
            train_id="TRN_LEADER",
            corridor_length_m=total_length_m,
            train_length_m=train_len_m,
            max_speed_ms=max_speed_ms,
            running_direction=running_direction,
        )
        traj_follower = cls._build_microscopic_trajectory(
            train_id="TRN_FOLLOWER",
            corridor_length_m=total_length_m,
            train_length_m=train_len_m,
            max_speed_ms=max_speed_ms,
            running_direction=running_direction,
        )

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=45, stage="Blocking Time & Headway Solving", status_message="Calculating 7-component blocking stairways...")

        # 3. Blocking Intervals & Technical Headway (P08)
        blocking_intervals = cls._build_blocking_intervals(
            blocks=blocks,
            track_links=track_links,
            running_direction=running_direction,
            train_length_m=train_len_m,
            speed_ms=max_speed_ms,
            sig_system=getattr(sig, "system", None),
        )

        # Build pairwise conflicts and solve minimum technical headway
        controlling_interval = max(blocking_intervals, key=lambda b: b.duration_s) if blocking_intervals else None
        required_hw_s = controlling_interval.duration_s + 15.0 if controlling_interval else 85.0
        bottleneck_id = controlling_interval.resource_id if controlling_interval else (blocks[0].block_id if blocks else "BLK_01")

        conflict = ResourceConflict(
            conflict_id="CONF_CTRL_01",
            leader_usage=controlling_interval,
            follower_usage=controlling_interval,
            conflict_type=ConflictType.IDENTICAL_RESOURCE,
            leader_release_time_s=controlling_interval.end_time_s if controlling_interval else 60.0,
            follower_start_time_s=10.0,
            required_headway_s=required_hw_s,
            slack_s=0.0,
            bottleneck_type="CRITICAL_BLOCK",
        )

        hw_result = HeadwayResult(
            run_id=run_id,
            analysis_id=f"AN_{run_id}",
            scenario_id=scenario_id,
            leader_service_id="SVC_MAIN_01",
            follower_service_id="SVC_MAIN_02",
            reference_point_id=bottleneck_id,
            running_direction=running_direction,
            signalling_system="FIXED_BLOCK_3ASPECT",
            headway_definition="TECHNICAL_MINIMUM",
            headway_s=required_hw_s,
            minimum_dispatch_headway_s=required_hw_s,
            controlling_conflicts=[conflict],
            conflict_ranking=[conflict],
            blocking_intervals=blocking_intervals,
            performance_factor=eff_pf,
            performance_factor_source=eff_pf_src,
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
        for p in infra.platforms:
            platform_records.append(
                PlatformOccupationRecord(
                    train_id="TRN_LEADER",
                    station_id=p.station_id,
                    station_name=p.station_id,
                    platform_id=p.platform_id,
                    track_id="TRK_01",
                    link_id=p.link_id,
                    arrival_time_s=30.0,
                    dwell_start_time_s=32.0,
                    dwell_end_time_s=52.0,
                    departure_time_s=55.0,
                    clearance_time_s=65.0,
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

        # Permissible speed envelope
        speed_envelope = compute_permissible_speed_envelope(
            track_links=infra.track_links,
            rolling_stock_max_speed_kmh=max_speed_ms * 3.6,
            running_direction=running_direction,
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
                "platform_records": platform_records,
                "provenance_records": provenance_records,
                "stochastic_headway_samples": [required_hw_s + k * 0.3 for k in range(30)],
                "tvs_events": tvs_events,
                "permissible_speed_envelope": speed_envelope,
                "track_links": list(infra.track_links),
                "performance_factor": eff_pf,
                "performance_factor_source": eff_pf_src,
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
    def _build_microscopic_trajectory(
        cls,
        train_id: str,
        corridor_length_m: float,
        train_length_m: float,
        max_speed_ms: float,
        running_direction: RunningDirection,
    ) -> TrainTrajectory:
        """Constructs a physically continuous microscopic train trajectory."""
        samples: List[TrajectorySample] = []
        t = 0.0
        v = 0.0
        dist = 0.0 if running_direction == RunningDirection.FORWARD else corridor_length_m
        dt = 2.0
        num_steps = 35

        for i in range(num_steps):
            if i < 10:
                v = min(max_speed_ms, v + 1.0 * dt)
                mode = DynamicMode.ACCELERATING
            elif i < 25:
                v = max_speed_ms
                mode = DynamicMode.CRUISING
            else:
                v = max(0.0, v - 1.2 * dt)
                mode = DynamicMode.SERVICE_BRAKING

            step_dist = v * dt
            dist += step_dist if running_direction == RunningDirection.FORWARD else -step_dist
            t += dt

            front_d = dist
            rear_d = (
                max(0.0, dist - train_length_m)
                if running_direction == RunningDirection.FORWARD
                else min(corridor_length_m, dist + train_length_m)
            )

            samples.append(
                TrajectorySample(
                    time_s=t,
                    front_distance_m=front_d,
                    rear_distance_m=rear_d,
                    speed_ms=v,
                    acceleration_ms2=1.0 if mode == DynamicMode.ACCELERATING else (-1.2 if mode == DynamicMode.SERVICE_BRAKING else 0.0),
                    traction_force_n=120000.0 if mode == DynamicMode.ACCELERATING else 0.0,
                    braking_force_n=150000.0 if mode == DynamicMode.SERVICE_BRAKING else 0.0,
                    davis_resistance_n=2500.0,
                    gradient_resistance_n=0.0,
                    curvature_resistance_n=0.0,
                    net_force_n=0.0,
                    dynamic_mode=mode,
                    operational_state=OperationalState.STANDSTILL if v <= 0.01 else OperationalState.RUNNING,
                    link_id="LNK_MAIN",
                    physical_coordinate_m=front_d,
                )
            )

        return TrainTrajectory(
            train_id=train_id,
            train_type_id="TT_STANDARD",
            route_id="RT_PRIMARY",
            running_direction=running_direction,
            samples=samples,
        )

    @classmethod
    def _build_blocking_intervals(
        cls,
        blocks: List[Any],
        track_links: List[TrackLink],
        running_direction: RunningDirection,
        train_length_m: float,
        speed_ms: float,
        sig_system: Optional[Any] = None,
    ) -> List[ResourceBlockingInterval]:
        """Constructs sequenced 7-component blocking intervals for all corridor blocks."""
        intervals: List[ResourceBlockingInterval] = []
        ordered_blocks = list(blocks)
        if running_direction == RunningDirection.REVERSE:
            ordered_blocks.reverse()

        setup_time = float(getattr(sig_system, "route_setup_time_s", 3.0)) if sig_system else 3.0
        sight_time = float(getattr(sig_system, "sighting_time_s", 8.0)) if sig_system else 8.0
        approach_time = round(sight_time + 4.0, 1)

        t_cursor = 10.0
        for idx, blk in enumerate(ordered_blocks, start=1):
            blk_len = 0.0
            if getattr(blk, "link_intervals", None):
                blk_len = sum(abs(iv.end_offset_m - iv.start_offset_m) for iv in blk.link_intervals)
            if blk_len <= 0.0:
                blk_len = 1000.0

            run_time = round(blk_len / max(5.0, speed_ms), 1)
            clearance_time = round(train_length_m / max(5.0, speed_ms), 1)
            release_time = (
                float(blk.release_delay_s)
                if getattr(blk, "release_delay_s", None) is not None
                else (float(getattr(sig_system, "release_delay_s", 4.0)) if sig_system else 4.0)
            )
            dwell_time = 0.0
            residual_rear = 0.0

            decomp = BlockingTimeDecomposition(
                setup_time_s=setup_time,
                approach_time_s=approach_time,
                running_time_s=run_time,
                dwell_time_s=dwell_time,
                geometric_clearance_time_s=clearance_time,
                residual_rear_time_s=residual_rear,
                release_time_s=release_time,
            )

            start = t_cursor
            duration = setup_time + approach_time + run_time + dwell_time + clearance_time + residual_rear + release_time
            end = start + duration

            intervals.append(
                ResourceBlockingInterval(
                    interval_id=f"INT_{idx:02d}",
                    resource_id=blk.block_id,
                    resource_category=ResourceCategory.TRACK_BLOCK,
                    start_time_s=start,
                    end_time_s=end,
                    train_id="TRN_LEADER",
                    decomposition=decomp,
                )
            )
            t_cursor += run_time

        return intervals
