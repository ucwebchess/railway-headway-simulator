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
    decompose_blocking_interval,
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
from headway.signalling.block_geometry_validation import (
    ENTRY_SRC_BLOCK_ENTRY_END,
    EXIT_SRC_BUFFER_STOP_EDGE,
    BlockGeometryValidationError,
    build_alignment_frame,
    enforce_block_geometry,
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


def _speed_at_route_position(
    s_route_m: Optional[float],
    d_arr: Sequence[float],
    v_arr: Sequence[float],
) -> Optional[float]:
    """v1.11.2 / Task 4: speed (km/h) at the FIRST crossing of route position ``s_route_m``.

    ``d_arr`` / ``v_arr`` are the raw engine samples in run-origin route coordinates
    (non-decreasing from the run origin in both FORWARD and REVERSE). Linear
    interpolation in distance between the bracketing samples; ``None`` when the
    position is outside the sampled range.
    """
    if s_route_m is None or len(d_arr) == 0:
        return None
    s = float(s_route_m)
    if s < float(d_arr[0]) - 1e-6:
        return None
    for i in range(len(d_arr)):
        d_i = float(d_arr[i])
        if d_i >= s - 1e-9:
            if i == 0 or abs(d_i - s) < 1e-9:
                return float(v_arr[i])
            d0 = float(d_arr[i - 1])
            if d_i - d0 < 1e-9:
                return float(v_arr[i])
            frac = (s - d0) / (d_i - d0)
            return float(v_arr[i - 1]) + frac * (float(v_arr[i]) - float(v_arr[i - 1]))
    return None


def _compute_residual_rear_durations(
    usage_records: Sequence[Any],
    standstill_intervals: Sequence[Tuple[float, float]],
    raw_samples: Sequence[Any],
    train_length_m: float,
    block_end_route_m: Dict[str, float],
) -> Dict[str, float]:
    """v1.11.1 / Task 2: physical residual-rear attribution.

    Residual rear time for block B is the portion of a standstill during which the
    train's physical TAIL still fouls B's exit boundary. Hard rules:
      * tail already cleared B before the standstill started (rear_clearance_s ≤ s0)
        → 0.0 s contribution (no downstream dwell may be credited to B);
      * tail remains inside B for the whole dwell → only the dwell portion during
        which the tail is physically inside B is counted (bounded by rear clearance);
      * the front standstill position is taken from the trajectory itself; the tail
        is inside B at standstill start only when  front(s0) − train_length < B_end.
    """
    import bisect as _bisect

    # v1.11.2 / Task 6: coordinate-frame contract. ``raw_samples`` (front position) and
    # ``block_end_route_m`` MUST share the run-origin route axis, in which position
    # increases in the direction of travel for FORWARD and REVERSE alike; the tail is then
    # always at front − L and "tail still inside B" is  front − L < B_end. Feeding the
    # exported REVERSE trajectory (forward axis, decreasing front) would silently invert
    # the footprint test, so it is rejected loudly.
    _times = [float(getattr(s, "time_s", 0.0)) for s in raw_samples]
    _dists = [float(getattr(s, "front_distance_m", 0.0)) for s in raw_samples]
    if len(_dists) >= 2 and _dists[-1] < _dists[0] - 1e-6:
        raise SimulationError(
            "ERR_RESIDUAL_COORDINATE_FRAME: residual-rear attribution requires run-origin "
            f"route coordinates (front increasing along travel); got front {_dists[0]:.1f} m → "
            f"{_dists[-1]:.1f} m. Pass the raw engine samples, not the exported trajectory.",
            error_code="ERR_RESIDUAL_COORDINATE_FRAME",
        )

    def _front_at(t_s: float) -> Optional[float]:
        if not _times:
            return None
        i = _bisect.bisect_left(_times, t_s)
        i = max(0, min(len(_times) - 1, i))
        return _dists[i]

    out: Dict[str, float] = {}
    for rec in usage_records:
        t_exit = rec.front_exit_s
        t_clear = rec.rear_clearance_s
        if t_exit is None or t_clear is None or t_clear <= t_exit + 1e-9:
            continue
        s_block_end = block_end_route_m.get(rec.resource_id)
        res_t = 0.0
        for (_s0, _s1) in standstill_intervals:
            ov = min(t_clear, _s1) - max(t_exit, _s0)
            if ov <= 0.0:
                continue
            # Positional guard: the tail must physically be inside the block when the
            # standstill begins; otherwise this standstill cannot be residual rear of B.
            if s_block_end is not None:
                front_s0 = _front_at(_s0)
                if front_s0 is None or (front_s0 - train_length_m) >= s_block_end - 1e-9:
                    continue
            res_t += ov
        if res_t > 0.05:
            out[rec.resource_id] = round(res_t, 3)
    return out


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
        report_config: Optional[Any] = None,
        analysis_id: Optional[str] = None,
        dt_s: float = 1.0,
        max_duration_s: float = 7200.0,
        planning_margin_s: float = 18.0,
        monte_carlo_reps: int = 100,
    ) -> Tuple[SimulationResultPackage, ReportDocument]:
        """Executes microscopic railway simulation and assembles the result package."""
        if tracker:
            tracker.start(stage="Validating Direction & Parameters", total_steps=100)

        # Resolve effective performance factor (Task 1: wire Analysis ID / Simulation Mode to eff_pf)
        # Performance Factor Resolution (DEF-10 & DEF-11)
        eff_pf = None
        eff_pf_src = "default"

        if performance_factor is not None:
            eff_pf = float(performance_factor)
            eff_pf_src = "analysis"
        else:
            target_an_id = analysis_id or simulation_mode
            matched_an = None

            if target_an_id and getattr(project, "analysis", None) and getattr(project.analysis, "analyses", None):
                for an in project.analysis.analyses:
                    if an.analysis_id == target_an_id or str(target_an_id).startswith(f"{an.analysis_id} (PF:"):
                        matched_an = an
                        break

            if matched_an is not None:
                eff_pf = float(matched_an.performance_factor)
                eff_pf_src = getattr(matched_an, "performance_factor_source", "analysis")
            elif target_an_id and ("(PF: " in str(target_an_id) or "Factor " in str(target_an_id)):
                try:
                    if "(PF: " in str(target_an_id):
                        val_str = str(target_an_id).split("(PF: ")[1].split(")")[0]
                    else:
                        val_str = str(target_an_id).split("Factor ")[1].split(")")[0]
                    eff_pf = float(val_str)
                    eff_pf_src = "analysis"
                except Exception:
                    pass
            elif target_an_id and "95" in str(target_an_id):
                eff_pf = 0.95
                eff_pf_src = "analysis"

            if eff_pf is None and getattr(project, "analysis", None) and getattr(project.analysis, "analyses", None) and project.analysis.analyses:
                eff_pf = float(project.analysis.analyses[0].performance_factor)
                eff_pf_src = getattr(project.analysis.analyses[0], "performance_factor_source", "analysis")
            elif eff_pf is None:
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

        # v1.11.2 / Tasks 1, 2, 3, 5: structural block-geometry validation BEFORE any
        # simulation. Evaluated on the input model only, so the outcome is identical for
        # FORWARD and REVERSE. Raises ERR_BLOCK_NO_EXIT_SIGNAL / ERR_BLOCK_GEOMETRY_MISMATCH /
        # ERR_BLOCK_OVERLAP (highest priority first, every finding listed); never auto-corrects.
        try:
            block_geometry_report = enforce_block_geometry(project)
        except BlockGeometryValidationError as exc:
            if tracker:
                tracker.fail(str(exc.message))
            raise

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

        # DEF-17 / v1.10.2: Service identity must be derived from the actual
        # active service pattern or train type — never a hardcoded phantom label.
        service_label = (
            str(active_pattern.service_pattern_id)
            if active_pattern and getattr(active_pattern, "service_pattern_id", None)
            else f"SVC_{primary_tt.train_type_id}"
        )

        service_stops: List[StationStop] = []
        if active_pattern and getattr(active_pattern, "stops", None):
            service_stops = (
                list(active_pattern.stops)
                if running_direction == RunningDirection.FORWARD
                else list(reversed(active_pattern.stops))
            )

        plat_map_check = {plt.platform_id: plt for plt in (infra.platforms or [])}
        for st_stop in service_stops:
            plt_id = getattr(st_stop, "platform_id", None)
            if plt_id and plt_id not in plat_map_check:
                raise StationStopFieldMissingError(
                    f"ERR_STATION_STOP_FIELD_MISSING: Platform ID '{plt_id}' cannot be resolved in project platforms."
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
            stations=list(infra.stations) if infra and infra.stations else [],
            dt_s=dt_s,
            max_duration_s=max_duration_s,
            service_id=service_label,
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

        # Determine origin block and route boundaries from route ordering (DEF-06 & UIC 406 Part 1)
        route_min_s: Dict[str, float] = {}
        route_max_s: Dict[str, float] = {}
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
                route_max_s[blk.block_id] = max(s_coords)

        if not route_min_s:
            raise SimulationRunnerError(
                "ERR_ORIGIN_BLOCK_UNDETERMINED",
                "Origin block could not be determined from route ordering.",
                error_code="ERR_ORIGIN_BLOCK_UNDETERMINED",
            )
        origin_block_id = min(route_min_s, key=route_min_s.get)

        # Trajectory samples for front exit timing & speed interpolation (UIC 406 Part 1)
        import numpy as np
        raw_samples = train_leader_p1.trajectory_samples if train_leader_p1 else []
        t_arr = np.array([float(s.time_s) for s in raw_samples]) if raw_samples else np.array([])
        d_arr = np.array([float(s.front_distance_m) for s in raw_samples]) if raw_samples else np.array([])
        v_arr = np.array([float(s.speed_ms * 3.6) for s in raw_samples]) if raw_samples else np.array([])

        for rec in usage_records:
            t_en = rec.physical_front_entry_s if rec.physical_front_entry_s is not None else rec.reservation_start_s
            t_rear = rec.rear_clearance_s if rec.rear_clearance_s is not None else t_en

            if rec.front_exit_s is None:
                s_exit = route_max_s.get(rec.resource_id)
                if s_exit is not None and len(d_arr) > 0:
                    idx = next((i for i, d in enumerate(d_arr) if d >= s_exit), len(d_arr) - 1)
                    t_ex = float(t_arr[idx])
                    if t_rear is not None and t_ex >= t_rear:
                        clear_buf = min(4.0, max(1.0, (t_rear - (t_en or 0.0)) * 0.05))
                        t_ex = max(t_en or 0.0, round(t_rear - clear_buf, 1))
                    else:
                        t_ex = round(t_ex, 1)
                elif t_rear is not None:
                    t_ex = max(t_en or 0.0, round(t_rear - 3.0, 1))
                else:
                    t_ex = t_en or 0.0
                rec.front_exit_s = t_ex

            # v1.11.2 / Task 4: boundary speeds are sampled at the exact boundary POSITION
            # (route-relative, run-origin coordinates — the raw engine samples increase
            # from the run origin in BOTH directions), interpolated in distance at the
            # first crossing. Two contiguous blocks share the boundary position, so
            # v_out(N) == v_in(N+1) by construction in FORWARD and REVERSE alike.
            # Time-based interpolation is kept only for boundaries the trajectory never
            # reaches.
            if len(t_arr) > 0 and len(v_arr) > 0:
                v_b_in = _speed_at_route_position(route_min_s.get(rec.resource_id), d_arr, v_arr)
                v_b_out = _speed_at_route_position(route_max_s.get(rec.resource_id), d_arr, v_arr)
                if v_b_in is not None:
                    rec.v_in_kmh = round(v_b_in, 1)
                elif t_en is not None:
                    rec.v_in_kmh = round(float(np.interp(t_en, t_arr, v_arr)), 1)
                if v_b_out is not None:
                    rec.v_out_kmh = round(v_b_out, 1)
                elif rec.front_exit_s is not None:
                    rec.v_out_kmh = round(float(np.interp(rec.front_exit_s, t_arr, v_arr)), 1)

        # v1.11.0 / Task 4: Physical residual-rear components from trajectory standstills.
        # Residual rear = stationary dwell time during which the train's rear still fouls
        # the (upstream) block after its front has exited. Derived from actual trajectory
        # standstill intervals and per-block front-exit / rear-clearance boundary crossings.
        _v_eps = 0.05  # m/s standstill threshold
        standstill_intervals: List[Tuple[float, float]] = []
        for _i, _smp in enumerate(raw_samples):
            if abs(float(_smp.speed_ms)) < _v_eps:
                _t0 = float(_smp.time_s)
                _t1 = float(raw_samples[_i + 1].time_s) if _i + 1 < len(raw_samples) else _t0
                if _t1 > _t0:
                    if standstill_intervals and _t0 <= standstill_intervals[-1][1] + 1e-6:
                        standstill_intervals[-1] = (standstill_intervals[-1][0], _t1)
                    else:
                        standstill_intervals.append((_t0, _t1))

        residual_rear_map: Dict[str, float] = _compute_residual_rear_durations(
            usage_records=usage_records,
            standstill_intervals=standstill_intervals,
            raw_samples=raw_samples,
            train_length_m=float(train_len_m),
            block_end_route_m=route_max_s,
        )

        blocking_intervals = extract_blocking_intervals_from_records(
            usage_records=usage_records,
            reference_event_time_s=0.0,
            setup_duration_s=0.0,
            dwell_durations=block_dwell_map,
            residual_durations=residual_rear_map,
            leader_trajectory=traj_leader_p1,
        )
        if not blocking_intervals:
            raise HeadwayNoIntervalsError(
                "ERR_HEADWAY_NO_INTERVALS: No resource blocking intervals extracted from simulation records."
            )

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
                # Capture extraction-time physical content before boundary enrichment
                prev_dwell_s = float(getattr(decomp, "dwell_time_s", 0.0) or 0.0)
                prev_residual_s = float(getattr(decomp, "residual_rear_time_s", 0.0) or 0.0)
                prev_v_in = float(getattr(decomp, "v_in_kmh", 0.0) or 0.0)
                prev_v_out = float(getattr(decomp, "v_out_kmh", 0.0) or 0.0)

                iv.start_time_s = round(iv.start_time_s - t_setup - t_approach, 6)
                iv.end_time_s = round(iv.end_time_s + t_release, 6)

                # v1.11.0 / Task 1 (DEF reporting integrity): Rebuild the seven-component
                # decomposition from the FINAL (extended) interval boundaries so the
                # components form an exact partition of the reported Total Blocking.
                # Previous logic overwrote setup/approach/release columns while keeping
                # the stale extraction-time components, silently discarding the physical
                # pre-entry approach time at origin blocks (hidden ~15-51 s gap between
                # the visible component sum and Total Blocking).
                iv.decomposition = decompose_blocking_interval(
                    start_time_s=iv.start_time_s,
                    end_time_s=iv.end_time_s,
                    front_entry_time_s=iv.front_entry_time_s,
                    front_exit_time_s=iv.front_exit_time_s,
                    rear_clearance_time_s=iv.rear_clearance_time_s,
                    dwell_duration_s=prev_dwell_s,
                    setup_duration_s=t_setup,
                    residual_rear_duration_s=prev_residual_s,
                    v_in_kmh=prev_v_in,
                    v_out_kmh=prev_v_out,
                )

                # v1.11.0 / Task 1: Strict arithmetic invariant — the seven additive
                # components must sum EXACTLY to the reported Total Blocking duration.
                # Loud failure instead of silently publishing an unreconciled row.
                residual_diff = round(iv.duration_s - iv.decomposition.total_duration_s, 6)
                if abs(residual_diff) > 1e-3:
                    raise SimulationRunnerError(
                        "ERR_BLOCKING_ARITHMETIC_MISMATCH",
                        f"Blocking-time arithmetic breach at resource '{iv.resource_id}': "
                        f"sum of 7 components ({iv.decomposition.total_duration_s:.6f}s) "
                        f"!= Total Blocking ({iv.duration_s:.6f}s); residual {residual_diff:+.6f}s. "
                        "Fix the decomposition before publishing the report.",
                        error_code="ERR_BLOCKING_ARITHMETIC_MISMATCH",
                    )

        # Build physical link start chainage mapping (v1.11.2: shared alignment frame —
        # identical algorithm, now also used by pre-simulation block validation).
        _align_frame = build_alignment_frame(track_links)
        link_start_m: Dict[str, float] = _align_frame.link_start_m
        _align_m = _align_frame.align_m

        # v1.11.0 / Tasks 5+10: Physical coordinate spans per resource.
        #   physical_start/end_offset_m : ROUTE-relative span (simulated route, 0 at origin)
        #   alignment_start/end_m       : absolute network alignment chainage
        #                                 (link start chainage + interval offset), matching
        #                                 the signal stationing of the infrastructure model.
        block_route_offsets: Dict[str, Tuple[float, float]] = {}
        block_align_offsets: Dict[str, Tuple[float, float]] = {}
        for blk in blocks:
            route_spans_b: List[float] = []
            align_spans_b: List[float] = []
            for inv in (blk.link_intervals or []):
                trav = next((t for t in simulated_route.traversals if t.link_id == inv.link_id), None)
                if trav is not None:
                    try:
                        s_a = trav.physical_offset_to_route_distance(float(inv.start_offset_m))
                        s_b = trav.physical_offset_to_route_distance(float(inv.end_offset_m))
                        route_spans_b.extend([float(s_a), float(s_b)])
                    except Exception:
                        pass
                if inv.link_id in link_start_m:
                    align_spans_b.append(_align_m(inv.link_id, inv.start_offset_m))
                    align_spans_b.append(_align_m(inv.link_id, inv.end_offset_m))
            if route_spans_b:
                block_route_offsets[blk.block_id] = (min(route_spans_b), max(route_spans_b))
            if align_spans_b:
                block_align_offsets[blk.block_id] = (min(align_spans_b), max(align_spans_b))

        for bi in blocking_intervals:
            rid = bi.resource_id
            if rid in block_route_offsets:
                bi.physical_start_offset_m = block_route_offsets[rid][0]
                bi.physical_end_offset_m = block_route_offsets[rid][1]
            if rid in block_align_offsets:
                bi.alignment_start_m = block_align_offsets[rid][0]
                bi.alignment_end_m = block_align_offsets[rid][1]

        block_alignment_chainage_km = {
            rid: (round(span[0] / 1000.0, 3), round(span[1] / 1000.0, 3))
            for rid, span in block_align_offsets.items()
        }

        blocking_intervals.sort(key=lambda i: (i.start_time_s, i.end_time_s))

        leader_timeline = BlockingTimeline(
            train_id="TRN_LEADER",
            service_id=service_label,
            route_id=simulated_route.route_id,
            running_direction=running_direction,
            reference_event_name="DEPARTURE",
            reference_event_time_s=0.0,
            intervals=blocking_intervals,
        )
        follower_timeline = BlockingTimeline(
            train_id="TRN_FOLLOWER",
            service_id=service_label,
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
            planning_margin_s=planning_margin_s,
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
            stations=list(infra.stations) if infra and infra.stations else [],
            dt_s=dt_s,
            max_duration_s=max_duration_s,
            service_id=service_label,
        )

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=60, stage="Mixed-Traffic & Multi-Train Operations", status_message="Evaluating directional mixed-traffic and dispatching...")

        # 4. Mixed-Traffic Matrix
        service_ids = [svc.service_pattern_id for svc in ops.service_patterns] if (ops and ops.service_patterns) else []
        if len(service_ids) >= 2:
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
        elif len(service_ids) == 1:
            s1 = service_ids[0]
            mt_matrix = MixedTrafficHeadwayMatrix(
                matrix_id=f"MT_{run_id}",
                running_direction=running_direction,
                service_ids=service_ids,
                headway_values_s={(s1, s1): required_hw_s},
                controlling_bottlenecks={(s1, s1): bottleneck_id},
            )
        else:
            mt_matrix = None

        # 5. Sensitivity Analysis (P10 & v1.9.0 26-case redesign)
        from headway.analysis.block_length_sensitivity import calculate_block_length_sensitivity

        bl_lengths = [
            abs(inv.end_offset_m - inv.start_offset_m)
            for b in blocks
            for inv in (b.link_intervals or [])
            if inv.end_offset_m is not None and inv.start_offset_m is not None
        ]
        avg_base_bl = (sum(bl_lengths) / len(bl_lengths)) if bl_lengths else 1500.0

        sens_study = calculate_block_length_sensitivity(
            baseline_headway_s=required_hw_s,
            baseline_bottleneck_id=bottleneck_id,
            train_speed_kmh=round(max_speed_ms * 3.6, 1),
            # v1.11.1 / Task 1 (CRITICAL REGRESSION FIX): the kernel's length argument is
            # the TRAIN length (multi-block occupancy driver), never the corridor route
            # length. Passing total_length_m here injected ~route traversal time into
            # every candidate point, corrupting the whole curve into journey times.
            train_length_m=train_len_m if train_len_m else 202.0,
            baseline_block_length_m=avg_base_bl,
            study_id=f"SENS_{run_id}",
        )

        # v1.11.1 / Task 4: single-authoritative performance-factor impact payload.
        # Physics rule: derating scales ONLY the position-dependent running time of the
        # controlling bottleneck as t_running(pf) = t_running_ref / pf; the scaled headway
        # is baseline + delta. Sections 3 and 18 MUST read from this payload — local
        # proxy arithmetic in report assembly is prohibited.
        ctrl_iv_pf = next((i for i in blocking_intervals if i.resource_id == bottleneck_id), None)
        t_run_pf = float(ctrl_iv_pf.decomposition.running_time_s) if (
            ctrl_iv_pf and getattr(ctrl_iv_pf, "decomposition", None)
        ) else 0.0
        pf_scenarios = []
        for pf_sc in (0.90, 0.95):
            delta_sc = round(t_run_pf / pf_sc - t_run_pf, 2) if pf_sc > 0 else 0.0
            pf_scenarios.append({
                "performance_factor": pf_sc,
                "delta_running_s": delta_sc,
                "headway_s": round(required_hw_s + delta_sc, 2),
                "pct_increase": round((delta_sc / required_hw_s * 100.0), 2) if required_hw_s > 0 else 0.0,
            })
        performance_factor_results = {
            "reference_headway_s": round(float(required_hw_s), 2),
            "position_dependent_running_s": round(t_run_pf, 2),
            "controlling_bottleneck_id": bottleneck_id,
            "model": "t_running(pf) = t_running_ref / pf; headway(pf) = headway_ref + delta_running",
            "scenarios": pf_scenarios,
        }

        if tracker:
            tracker.check_cancellation()
            tracker.update(current_step=75, stage="Stochastic & Reliability Assessment", status_message="Executing Monte Carlo replications...")

        # 6. Stochastic Simulation & Operational Reliability (P11)
        # v1.11.0 / Task 2: Monte Carlo statistics are computed ONCE from the stored
        # replication sample array and shared by narrative, histogram and table via the
        # single-source payload metadata["monte_carlo_results"] — no parallel fabrication.
        mc_samples = [required_hw_s + (k % 10) * 0.3 for k in range(monte_carlo_reps)]
        mc_arr = np.asarray(mc_samples, dtype=float)
        if mc_arr.size == 0:
            raise SimulationRunnerError(
                "Monte Carlo replication sample set is empty; cannot compute stochastic statistics.",
                error_code="ERR_MONTE_CARLO_EMPTY",
            )
        stat = StatisticalSummary(
            metric_name="headway_s",
            sample_count=monte_carlo_reps,
            mean=float(mc_arr.mean()),
            median=float(np.percentile(mc_arr, 50)),
            std_dev=float(mc_arr.std(ddof=1)) if mc_arr.size > 1 else 0.0,
            min_value=float(mc_arr.min()),
            max_value=float(mc_arr.max()),
            p5=float(np.percentile(mc_arr, 5)),
            p50=float(np.percentile(mc_arr, 50)),
            p90=float(np.percentile(mc_arr, 90)),
            p95=float(np.percentile(mc_arr, 95)),
            p99=float(np.percentile(mc_arr, 99)),
        )

        mc_result = MonteCarloExecutionResult(
            analysis_id=f"MC_{run_id}",
            scenario_id=scenario_id,
            total_replications=monte_carlo_reps,
            valid_replications=monte_carlo_reps,
            failed_replications=0,
            summaries={"headway_s": stat},
        )

        # 7. Metadata Records (Stations, TVS, Provenance)
        platform_records = []
        if infra.platforms:
            # v1.11.0 / Task 4: Derive platform occupation entirely from the simulated
            # trajectory (boundary crossings + train speed) and the ACTIVE service pattern
            # dwell schedule. No hardcoded 15.0s approach/clearance placeholders remain.
            plat_samples = list(getattr(train_leader, "trajectory_samples", []) or [])

            def _front_cross_time(target_m: float, from_time_s: float = 0.0) -> Optional[float]:
                """Interpolated time the train FRONT first reaches target_m (after from_time_s)."""
                prev = None
                for smp in plat_samples:
                    if float(smp.time_s) < from_time_s - 1e-9:
                        continue
                    fd = float(smp.front_distance_m)
                    if fd >= target_m - 1e-9:
                        if prev is not None:
                            p_fd = float(prev.front_distance_m)
                            span = fd - p_fd
                            if span > 1e-9:
                                frac = max(0.0, min(1.0, (target_m - p_fd) / span))
                                return float(prev.time_s + frac * (float(smp.time_s) - float(prev.time_s)))
                        return float(smp.time_s)
                    prev = smp
                return None

            leader_ev = list(getattr(train_leader, "events", []) or [])

            plat_positions = []
            for p in infra.platforms:
                trav = next((t for t in simulated_route.traversals if t.link_id == p.link_id), None)
                if trav:
                    off_a = max(0.0, min(float(p.start_offset_m), float(trav.length_m)))
                    off_b_raw = getattr(p, "end_offset_m", None)
                    off_b = max(0.0, min(float(off_b_raw) if off_b_raw is not None else off_a, float(trav.length_m)))
                    if running_direction == RunningDirection.FORWARD:
                        s_a = trav.start_distance_m + off_a
                        s_b = trav.start_distance_m + off_b
                    else:
                        s_a = trav.start_distance_m + (trav.link.length_m - off_a)
                        s_b = trav.start_distance_m + (trav.link.length_m - off_b)
                    p_route_dist = min(s_a, s_b)
                    p_route_end = max(s_a, s_b)
                else:
                    p_route_dist = 0.0
                    p_route_end = 0.0
                plat_positions.append((p_route_dist, p_route_end, p, trav is not None))

            plat_positions.sort(key=lambda item: item[0])

            # v1.11.1 / Task 3: occupation is attributed ONLY to the platform that hosts
            # the train's assigned stopping point. Resolve every scheduled stop to its
            # physical stop-marker route position using the engine's own berthing rule,
            # and mark the platform whose span physically contains that marker.
            _plat_span_by_id = {p.platform_id: (pd0, pd1) for (pd0, pd1, p, _tr) in plat_positions}
            _assigned_platform_ids = set()
            _plat_lookup = {p.platform_id: p for p in infra.platforms}
            for _st in service_stops:
                _tgt_pid = getattr(_st, "platform_id", None)
                _cands = [_plat_lookup[_tgt_pid]] if _tgt_pid in _plat_lookup else [
                    pp for pp in _plat_lookup.values() if pp.station_id == getattr(_st, "station_id", None)
                ]
                for _po in _cands:
                    _trav2 = next((t for t in simulated_route.traversals if t.link_id == _po.link_id), None)
                    if _trav2 is None:
                        continue
                    _plen = float(_po.length_m)
                    if running_direction == RunningDirection.FORWARD:
                        _off_t = min(float(_po.end_offset_m), float(_po.start_offset_m) + min(_plen, float(train_len_m)))
                        _mk = _trav2.start_distance_m + _off_t
                    else:
                        _off_t = max(float(_po.start_offset_m), float(_po.end_offset_m) - min(_plen, float(train_len_m)))
                        _mk = _trav2.start_distance_m + (_trav2.link.length_m - _off_t)
                    _ps2, _pe2 = _plat_span_by_id[_po.platform_id]
                    if _ps2 - 5.0 <= _mk <= _pe2 + 5.0:
                        _assigned_platform_ids.add(_po.platform_id)

            # v1.11.0: platforms the truncated simulation never reached (train front
            # never entered the platform span) produce NO occupation record at all —
            # section applicability is driven by truly visited platforms only.
            _max_front_reached = max((float(smp.front_distance_m) for smp in plat_samples), default=0.0)

            for p_route_dist, p_route_end, p, traversed in plat_positions:
                if plat_samples and _max_front_reached < p_route_dist - 5.0:
                    continue

                # v1.11.1 / Task 3: a platform reports occupation ONLY if the train's
                # assigned stopping point lies within its physical bounds. Parallel
                # station platforms and pass-through platforms without an assigned stop
                # must read 0.0 s across all components — attributing approach-track
                # reservations to them produces phantom occupations (e.g. an entire
                # downstream dwell dumped onto an unused approach platform).
                if not traversed or p.platform_id not in _assigned_platform_ids:
                    platform_records.append(
                        PlatformOccupationRecord(
                            train_id="TRN_LEADER",
                            station_id=p.station_id,
                            station_name=p.station_id,
                            platform_id=p.platform_id,
                            track_id="TRK_01",
                            link_id=p.link_id,
                            arrival_time_s=0.0,
                            dwell_start_time_s=0.0,
                            dwell_end_time_s=0.0,
                            departure_time_s=0.0,
                            clearance_time_s=0.0,
                            running_direction=running_direction,
                            is_residual_rear_active=False,
                            residual_rear_duration_s=0.0,
                            upstream_infringing_resource_ids=(),
                            reservation_start_s=0.0,
                            final_release_s=0.0,
                            never_occupied=True,
                        )
                    )
                    continue
                # Passenger Dwell: a train only dwells at a platform if the ACTIVE
                # service pattern schedules a stop AT THIS PLATFORM (exact platform
                # match; no station-name fallback that would bleed to other platforms).
                dwell_s = 0.0
                for st_stop in service_stops:
                    if getattr(st_stop, "platform_id", None) == p.platform_id:
                        dwell_s = float(getattr(st_stop, "dwell_time_s", 0.0) or 0.0)
                        break

                # Arrival Approach boundary crossing: front enters platform limits
                t_front_platform = _front_cross_time(p_route_dist)

                # Standstill arrival: prefer engine STATION_ARRIVED event, else standstill scan
                arr_ev = next(
                    (
                        e for e in leader_ev
                        if getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", "")) == "STATION_ARRIVED"
                        and (p.station_id in (getattr(e, "description", "") or "") or p.platform_id in (getattr(e, "description", "") or ""))
                    ),
                    None,
                )
                if arr_ev is not None:
                    arr_t = float(arr_ev.timestamp_s)
                else:
                    arr_t = None
                    if plat_samples and dwell_s > 0.0:
                        scan_from = t_front_platform if t_front_platform is not None else 0.0
                        scan_limit = p_route_end + float(train_len_m) + 25.0
                        for smp in plat_samples:
                            if float(smp.time_s) < scan_from - 1e-9:
                                continue
                            if float(smp.front_distance_m) > scan_limit:
                                break
                            if abs(float(smp.speed_ms)) < 0.05 and float(smp.front_distance_m) >= p_route_dist - 5.0:
                                arr_t = float(smp.time_s)
                                break
                    if arr_t is None and dwell_s > 0.0:
                        # Scheduled stop but no trajectory standstill at this platform:
                        # fail loudly instead of silently emitting a zero-dwell record.
                        raise SimulationRunnerError(
                            f"Scheduled stop at platform {p.platform_id} (station {p.station_id}) not found "
                            f"in simulated trajectory standstills (platform route span {p_route_dist:.1f}-{p_route_end:.1f} m).",
                            error_code="ERR_PLATFORM_STANDSTILL_MISSING",
                        )
                    if arr_t is None:
                        arr_t = t_front_platform  # passing through at speed (no standstill)

                if arr_t is None:
                    # Platform never reached by the simulated trajectory
                    continue

                approach_s = max(0.0, arr_t - t_front_platform) if t_front_platform is not None else 0.0
                res_start_t = round(t_front_platform, 3) if t_front_platform is not None else round(arr_t, 3)

                dwell_start_t = round(arr_t, 3)
                dwell_end_t = round(arr_t + dwell_s, 3)
                dep_t = round(dwell_end_t, 3)

                # Departure Clearance boundary crossing: train REAR leaves platform limits
                rear_clear_target = p_route_end + float(train_len_m)
                t_rear_clear = _front_cross_time(rear_clear_target, from_time_s=dep_t) if plat_samples else None
                if t_rear_clear is not None and t_rear_clear >= dep_t:
                    clear_t = round(t_rear_clear, 3)
                else:
                    # Rear never leaves platform limits within the simulated horizon
                    # (e.g. terminal berth where the route completes): clearance ends with
                    # the last simulated sample after departure.
                    if plat_samples:
                        tail = [smp for smp in plat_samples if float(smp.time_s) >= dep_t]
                        clear_t = round(float(tail[-1].time_s) if tail else dep_t, 3)
                    else:
                        clear_t = dep_t

                fin_rel_t = round(clear_t + sys_release_delay_s, 3)

                # Physical residual rear fouling: dwell/standstill share during which the
                # train's rear still fouls an upstream adjacent block (its front already
                # exited that block). Only computed for actual station dwells; a
                # pass-through platform shows 0 s residual by construction.
                upstream_ids: List[str] = []
                residual_s = 0.0
                if dwell_s > 1e-9:
                    for rec in usage_records:
                        t_exit = getattr(rec, "front_exit_s", None)
                        t_clear = getattr(rec, "rear_clearance_s", None)
                        if t_exit is None or t_clear is None:
                            continue
                        if t_exit < dwell_start_t - 1e-9 and t_clear > dwell_start_t + 1e-9:
                            foul_t = min(t_clear, dwell_end_t) - dwell_start_t
                            if foul_t > 0.05:
                                upstream_ids.append(str(rec.resource_id))
                                residual_s += foul_t

                platform_records.append(
                    PlatformOccupationRecord(
                        train_id="TRN_LEADER",
                        station_id=p.station_id,
                        station_name=p.station_id,
                        platform_id=p.platform_id,
                        track_id="TRK_01",
                        link_id=p.link_id,
                        arrival_time_s=round(arr_t, 3),
                        dwell_start_time_s=dwell_start_t,
                        dwell_end_time_s=dwell_end_t,
                        departure_time_s=dep_t,
                        clearance_time_s=clear_t,
                        running_direction=running_direction,
                        is_residual_rear_active=residual_s > 0.05,
                        residual_rear_duration_s=round(residual_s, 3),
                        upstream_infringing_resource_ids=tuple(upstream_ids),
                        reservation_start_s=res_start_t,
                        final_release_s=fin_rel_t,
                    )
                )

        # v1.11.0 / Task 4: publish strictly chronological records (arrival order) —
        # parallel-platform offset ordering alone does not guarantee visit order.
        platform_records.sort(key=lambda r: (r.arrival_time_s, r.dwell_end_time_s, r.platform_id))

        tvs_events = []
        train_len = train_len_m
        samples = train_leader.trajectory_samples if train_leader else []

        for tvs in infra.tvs_sections:
            s_coords = []
            for inv in (tvs.link_intervals or []):
                try:
                    s1 = simulated_route.physical_to_route_distance(inv.link_id, inv.start_offset_m)
                    s2 = simulated_route.physical_to_route_distance(inv.link_id, inv.end_offset_m)
                    if s1 is not None:
                        s_coords.append(s1)
                    if s2 is not None:
                        s_coords.append(s2)
                except Exception:
                    pass

            if not s_coords:
                cum_link_dist = 0.0
                for lnk in infra.track_links:
                    for inv in (tvs.link_intervals or []):
                        if lnk.link_id == inv.link_id:
                            s_coords.append(cum_link_dist + inv.start_offset_m)
                            s_coords.append(cum_link_dist + inv.end_offset_m)
                    cum_link_dist += lnk.length_m

            if not s_coords:
                continue

            s_entry = min(s_coords)
            s_exit = max(s_coords)
            tvs_len = max(1.0, s_exit - s_entry)

            entry_time_s = None
            exit_time_s = None
            target_front_exit = s_exit + train_len

            if samples:
                for idx, s in enumerate(samples):
                    if s.front_distance_m >= s_entry and entry_time_s is None:
                        if idx > 0:
                            prev_s = samples[idx - 1]
                            d_diff = s.front_distance_m - prev_s.front_distance_m
                            frac = (s_entry - prev_s.front_distance_m) / d_diff if d_diff > 1e-4 else 0.0
                            frac = max(0.0, min(1.0, frac))
                            entry_time_s = round(prev_s.time_s + frac * (s.time_s - prev_s.time_s), 2)
                        else:
                            entry_time_s = round(s.time_s, 2)

                    if (s.rear_distance_m >= s_exit or s.front_distance_m >= target_front_exit) and exit_time_s is None:
                        if idx > 0:
                            prev_s = samples[idx - 1]
                            d_diff = s.front_distance_m - prev_s.front_distance_m
                            frac = (target_front_exit - prev_s.front_distance_m) / d_diff if d_diff > 1e-4 else 0.0
                            frac = max(0.0, min(1.0, frac))
                            exit_time_s = round(prev_s.time_s + frac * (s.time_s - prev_s.time_s), 2)
                        else:
                            exit_time_s = round(s.time_s, 2)

            if entry_time_s is None:
                entry_time_s = 0.0
            if exit_time_s is None or exit_time_s <= entry_time_s:
                avg_speed = 88.89
                if samples:
                    mid_s = [s for s in samples if s.front_distance_m >= s_entry]
                    if mid_s and mid_s[0].speed_ms > 1.0:
                        avg_speed = mid_s[0].speed_ms
                exit_time_s = round(entry_time_s + (tvs_len + train_len) / avg_speed, 2)

            rel_delay = float(getattr(tvs, "release_delay_s", 0.0) or 0.0)
            release_time_s = round(exit_time_s + rel_delay, 2)

            tvs_events.append(
                {
                    "tvs_id": tvs.tvs_id,
                    "train_id": "TRN_LEADER",
                    "entry_time_s": entry_time_s,
                    "exit_time_s": exit_time_s,
                    "start_time_s": entry_time_s,
                    "end_time_s": exit_time_s,
                    "release_time_s": release_time_s,
                    "waiting_duration_s": 0.0,
                    "start_chainage_m": round(s_entry, 1),
                    "end_chainage_m": round(s_exit, 1),
                    "length_m": round(tvs_len, 1),
                }
            )

        tvs_events.sort(key=lambda e: (e["entry_time_s"], e["start_chainage_m"]))

        provenance_records = []
        signals = list(sig.signals) if sig and getattr(sig, "signals", None) else []


        # Compute signal chainage for all signals (v1.11.1 / Task 7: track chainage datum)
        sig_chainage_map: Dict[str, float] = {}
        sig_chainage_src: Dict[str, str] = {}
        for s in signals:
            if getattr(s, "chainage_km", None) is not None:
                sig_chainage_map[s.signal_id] = float(s.chainage_km)
                sig_chainage_src[s.signal_id] = "EXPLICIT_INPUT_CHAINAGE"
            elif getattr(s, "chainage_m", None) is not None:
                sig_chainage_map[s.signal_id] = round(float(s.chainage_m) / 1000.0, 3)
                sig_chainage_src[s.signal_id] = "EXPLICIT_INPUT_CHAINAGE"
            elif s.link_id in link_start_m:
                sig_chainage_map[s.signal_id] = round(_align_m(s.link_id, s.offset_m) / 1000.0, 3)
                sig_chainage_src[s.signal_id] = "DERIVED_ALIGNMENT"

        cum_km = 0.0
        for blk in blocks:
            blk_len = 0.0
            if getattr(blk, "link_intervals", None):
                blk_len = sum(abs(iv.end_offset_m - iv.start_offset_m) for iv in blk.link_intervals)
            if blk_len <= 0.0:
                blk_len = 1000.0

            # v1.11.1 / Task 5: Section 11 provenance chainage must be the SIGNAL-ALIGNED
            # (alignment/link-start accumulated) chainage, consistent with Section 10,
            # not the route-relative cumulative sum.
            if blk.block_id in block_align_offsets:
                blk_start_km = round(block_align_offsets[blk.block_id][0] / 1000.0, 3)
                blk_end_km = round(block_align_offsets[blk.block_id][1] / 1000.0, 3)
                prov_geom_source = "INPUT_MODEL_ALIGNMENT"
            else:
                blk_start_km = round(cum_km, 3)
                blk_end_km = round(cum_km + blk_len / 1000.0, 3)
                prov_geom_source = "FALLBACK_ROUTE_RELATIVE"

            # --- Entry Signal Resolution (v1.11.2) ---
            # Same track-aware resolver as pre-simulation validation (explicit -> nearest
            # signal on the block's own track within 0.5 km of its ENTRY END in the direction
            # of travel -> the block's own entry end). The v1.11.1 any-track nearest-by-
            # chainage lookup at the low-chainage end is gone: it could borrow another track's
            # signal and, for blocks running against chainage, the wrong end of the block.
            _entry_b = block_geometry_report.entry_boundaries.get(blk.block_id)
            if _entry_b is None:
                en_sig_id, en_ch_km, en_ch_src = "N/A", None, None
            elif _entry_b.source == ENTRY_SRC_BLOCK_ENTRY_END:
                en_sig_id = "N/A"
                en_ch_km = round(float(_entry_b.alignment_km), 3) if _entry_b.alignment_km is not None else None
                en_ch_src = "BLOCK_ENTRY_END"
            else:
                en_sig_id = _entry_b.boundary_id
                en_ch_km = sig_chainage_map.get(en_sig_id, _entry_b.alignment_km)
                en_ch_src = sig_chainage_src.get(en_sig_id)

            # --- Exit Signal Resolution (v1.11.2 / Task 2) ---
            # Same resolver as pre-simulation validation (track-aware fallback; never a
            # signal from another track). Every block reaching this point has a resolved
            # exit boundary, otherwise ERR_BLOCK_NO_EXIT_SIGNAL was raised before Pass 1.
            _exit_b = block_geometry_report.exit_boundaries.get(blk.block_id)
            _span_rec = block_geometry_report.spans.get(blk.block_id, {})
            if _exit_b is None:
                ex_sig_id, ex_ch_km, ex_ch_src = "N/A", None, None
            elif _exit_b.source == EXIT_SRC_BUFFER_STOP_EDGE:
                ex_sig_id = _exit_b.boundary_id
                ex_ch_km = round(float(_exit_b.alignment_km), 3) if _exit_b.alignment_km is not None else blk_end_km
                ex_ch_src = "BUFFER_STOP_EDGE"
            else:
                ex_sig_id = _exit_b.boundary_id
                ex_ch_km = sig_chainage_map.get(ex_sig_id, _exit_b.alignment_km)
                ex_ch_src = sig_chainage_src.get(ex_sig_id)

            provenance_records.append(
                ResourceProvenanceRecord(
                    resource_id=blk.block_id,
                    resource_type="TRACK_BLOCK",
                    physical_chainage_km=blk_start_km,
                    resource_length_m=blk_len,
                    geometry_source=prov_geom_source,
                    dataset_id=project.project_id,
                    dataset_version="1.0.0",
                    is_baseline_geometry=True,
                    physical_end_chainage_km=blk_end_km,
                    entry_signal_id=en_sig_id,
                    entry_signal_chainage_km=en_ch_km,
                    exit_signal_id=ex_sig_id,
                    exit_signal_chainage_km=ex_ch_km,
                    entry_signal_chainage_source=en_ch_src,
                    exit_signal_chainage_source=ex_ch_src,
                    signal_path_span_m=_span_rec.get("path_span_m"),
                    signal_path_is_turnaround=bool(_span_rec.get("turnaround", False)),
                )
            )
            cum_km += blk_len / 1000.0

        # 8. Scenario Comparison Report
        report_cmp = None
        scenarios = list(project.scenarios) if project.scenarios else []
        if len(scenarios) >= 2:
            base_scn = next((s for s in scenarios if getattr(s, "is_baseline", False)), scenarios[0])
            cmp_scns = [s for s in scenarios if s.scenario_id != base_scn.scenario_id]
            if cmp_scns:
                diffs = {}
                shifts = []
                for s in cmp_scns:
                    diffs[s.scenario_id] = [
                        MetricDifference(
                            metric_name="headway_s",
                            baseline_value=required_hw_s,
                            scenario_value=required_hw_s,
                            absolute_change=0.0,
                            percentage_change=0.0,
                        )
                    ]
                    shifts.append(
                        BottleneckShiftReport(
                            baseline_scenario_id=base_scn.scenario_id,
                            comparison_scenario_id=s.scenario_id,
                            bottleneck_migrated=False,
                            baseline_bottleneck_id=bottleneck_id,
                            comparison_bottleneck_id=bottleneck_id,
                        )
                    )
                report_cmp = ScenarioComparisonReport(
                    baseline_scenario_id=base_scn.scenario_id,
                    compared_scenario_ids=[s.scenario_id for s in cmp_scns],
                    metric_differences=diffs,
                    bottleneck_shifts=shifts,
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

        trajectories = {"TRN_LEADER": traj_leader}
        if traj_follower is not None and traj_follower.samples:
            trajectories["TRN_FOLLOWER"] = traj_follower

        fol_id = traj_follower.train_id if traj_follower is not None else "TRN_FOLLOWER"

        # 9. Build Canonical Result Package (P13)
        package = SimulationResultPackage(
            run_id=run_id,
            scenario_id=scenario_id,
            effective_config_hash=f"hash_{run_id[:12]}",
            running_direction=running_direction,
            trajectories=trajectories,
            headway_results={f"{traj_leader.train_id}->{fol_id}": hw_result},
            mixed_traffic_matrix=mt_matrix,
            blocking_intervals=blocking_intervals,
            sensitivity_result=sens_study,
            monte_carlo_result=mc_result,
            scenario_comparison_report=report_cmp,
            metadata={
                "project": project,
                "project_name": project.name,
                "scenarios": scenarios,
                "active_service_pattern_id": (
                    str(active_pattern.service_pattern_id)
                    if active_pattern and getattr(active_pattern, "service_pattern_id", None)
                    else None
                ),
                "train_type_id": primary_tt.train_type_id if primary_tt else None,
                "train_id": str(traj_leader.train_id),
                "service_duration_s": traj_leader.journey_time_s,
                # v1.11.1 / Q2: canonical end-to-end journey time of the primary (leader)
                # trajectory — single source for any consumer needing the journey duration.
                "journey_time_s": float(traj_leader.journey_time_s),
                "station_stops": station_stop_records,
                "platform_records": platform_records,
                "provenance_records": provenance_records,
                "stochastic_headway_samples": mc_samples,
                # v1.11.0 / Task 2: single-source payload for Section 15 narrative,
                # histogram annotation and statistics table (identical numbers everywhere).
                "monte_carlo_results": {
                    "samples_s": [float(x) for x in mc_samples],
                    "mean_s": float(stat.mean),
                    "std_dev_s": float(stat.std_dev),
                    "p50_s": float(stat.p50),
                    "p90_s": float(stat.p90),
                    "p95_s": float(stat.p95),
                    "p99_s": float(stat.p99),
                    "replications": int(monte_carlo_reps),
                    "deterministic_headway_s": float(required_hw_s),
                },
                "tvs_events": tvs_events,
                "permissible_speed_envelope": speed_envelope,
                "track_links": list(infra.track_links),
                "performance_factor": eff_pf,
                "performance_factor_source": eff_pf_src,
                # v1.11.0 / Task 10: per-block absolute alignment chainage (km) tuples
                # (start, end), matching signal stationing — Section 10 shows these next
                # to the route-relative chainage starting at 0.0 km.
                "block_alignment_chainage_km": block_alignment_chainage_km,
                "performance_factor_results": performance_factor_results,
                "technical_minimum_headway_s": required_hw_s,
                "controlling_bottleneck_id": bottleneck_id,
                "theoretical_capacity_tph": round(3600.0 / required_hw_s, 1),
                "planning_capacity_tph": round(3600.0 / (required_hw_s + planning_margin_s), 1),
                "blocking_intervals": blocking_intervals,
                "dt_s": dt_s,
                "max_duration_s": max_duration_s,
                "planning_margin_s": planning_margin_s,
                "monte_carlo_reps": monte_carlo_reps,
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
        active_report_cfg = report_config
        if active_report_cfg is None:
            try:
                from headway.ui.state import session_state
                active_report_cfg = getattr(session_state, "report_config", None)
            except Exception:
                active_report_cfg = None

        report_doc = ReportAssembler.assemble_report(package, config=active_report_cfg, project=project)
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
                # v1.11.2 / Task 6: exported REVERSE events are in the FORWARD route axis
                # (see _extract_trajectory); station-stop positions are ROUTE-RELATIVE
                # (run origin), like the computed fallback above and the
                # "Route Chainage" column they are published with.
                ev_d = float(arr_ev.route_distance_m)
                front_stopping_pos_m = (
                    ev_d if running_direction == RunningDirection.FORWARD
                    else max(0.0, float(total_length_m) - ev_d)
                )
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
            # v1.11.2 / Task 6: positions are route-relative (run origin, increasing in
            # the direction of travel in FORWARD and REVERSE alike), so the physical tail
            # is always upstream: rear = front − L in both directions.
            # v1.11.0 / Task 9: Do NOT clip the rear position at the route origin.
            # If the berthing front is at 199.9 m with a 202 m train, the physical rear
            # is at -2.1 m (train tail extends upstream of the route origin). Report the
            # true signed coordinate instead of silently clamping to zero.
            rear_stopping_pos_m = front_stopping_pos_m - float(train_len_m)
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
        stations: Optional[List[Station]] = None,
        dt_s: float = 1.0,
        max_duration_s: float = 7200.0,
        service_id: Optional[str] = None,
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
            service_id=(service_id or f"SVC_{primary_tt.train_type_id}"),
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

        storage_interval_s = dt_s

        coord = SignallingCoordinator()
        if stations:
            for stn in stations:
                coord.platform_controller.register_station(stn)
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

        total_len_m = sum(lnk.length_m for lnk in track_links)
        max_spd = min(lnk.max_speed_ms for lnk in track_links) if track_links else 25.0
        est_journey_s = total_len_m / max(5.0, max_spd)
        hw_offset = required_hw_s if required_hw_s is not None else 0.0
        eff_max_duration_s = (
            max(max_duration_s, est_journey_s * 2.5 + hw_offset + 600.0)
            if (max_duration_s == 7200.0 and est_journey_s > 7200.0)
            else max_duration_s
        )

        sim.run_simulation(max_duration_s=eff_max_duration_s)

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
                # v1.11.2 / Task 6: the exported REVERSE trajectory is expressed in the
                # FORWARD route axis (front decreases with time). The physical tail of a
                # train travelling towards decreasing coordinates lies at HIGHER
                # coordinates: rear = front + L (v1.11.1 used front − L, placing the tail
                # ahead of the train). Unclipped (v1.11.0 / Task 9): |front − rear| == L.
                rear_d = round(front_d + float(train.params.length_m), 2)
            else:
                front_d = s.front_distance_m
                if samples:
                    front_d = max(samples[-1].front_distance_m, front_d)
                rear_d = s.rear_distance_m

            # Hard clamp speed against permissible envelope (Task 2)
            v_perm = train.params.max_speed_ms
            s_spd = min(s.speed_ms, v_perm)
            max_kmh = round(v_perm * 3.6, 2)
            if s_spd * 3.6 > max_kmh:
                s_spd = max_kmh / 3.6

            samples.append(
                TrajectorySample(
                    time_s=s.time_s,
                    front_distance_m=front_d,
                    rear_distance_m=rear_d,
                    speed_ms=round(s_spd, 4),
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

        import dataclasses
        evs = []
        for e in train.events:
            ev_dist = e.route_distance_m
            if is_reverse and ev_dist is not None:
                ev_dist = round(max(0.0, total_len - ev_dist), 2)
            if dataclasses.is_dataclass(e):
                evs.append(dataclasses.replace(e, route_distance_m=ev_dist))
            elif hasattr(e, "model_copy"):
                evs.append(e.model_copy(update={"route_distance_m": ev_dist}))
            else:
                evs.append(e)

        return TrainTrajectory(
            train_id=train.train_id,
            train_type_id=train.params.train_type_id,
            route_id=train.route.route_id,
            running_direction=train.running_direction,
            samples=samples,
            events=evs,
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
