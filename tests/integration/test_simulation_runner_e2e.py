"""End-to-end integration tests for microscopic MultiTrainSimulator wiring into SimulationRunner.

v1.11.2: block geometry is validated before simulation (literal strict). Examples 01, 04,
05 and 07 carry documented block-model defects and now raise in BOTH directions; the
tests that previously ran them assert that error instead (tests/block_geometry_expectations.py).
Error-path and sensitivity behaviour is additionally exercised on the clean example
06_multilink_blocks (TestCleanExampleErrorPaths), and TestBidirectionalSymmetry
(v1.11.2 / Task 12) runs all 7 examples (+ an in-memory 05 turnaround variant) in
FORWARD and REVERSE.
"""

import copy

import pytest

from headway.infrastructure.direction import RunningDirection
from headway.signalling.block_geometry_validation import BlockGeometryValidationError
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import (
    HeadwayInfeasibleError,
    HeadwayNoIntervalsError,
    LeaderTrajectoryEmptyError,
    ServicePatternAmbiguousError,
    SimulationRunner,
    SimulationRunnerError,
    StationStopFieldMissingError,
)
from tests.block_geometry_expectations import (
    BOTH_DIRECTIONS,
    CLEAN_EXAMPLES,
    EXPECTED_BLOCK_GEOMETRY_ERRORS,
    assert_block_geometry_error,
    comprehensive_line_with_explicit_turnaround_exits,
    findings_by_code,
    load_and_assert_pipeline_raises,
)

ALL_EXAMPLES = sorted(set(EXPECTED_BLOCK_GEOMETRY_ERRORS) | set(CLEAN_EXAMPLES))
assert len(ALL_EXAMPLES) == 7
CLEAN_EXAMPLE = "06_multilink_blocks"


class TestSimulationRunnerE2E:
    """Comprehensive end-to-end validation suite for SimulationRunner microscopic engine."""

    def test_e2e_forward_simulation_dynamics_and_duration_bounds(self):
        """Verify forward simulation runs with microscopic engine and produces realistic duration.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_e2e_140km_corridor_simulation_duration_bounds(self):
        """Verify that a 140 km corridor simulation yields total service duration within 1500s-3600s."""
        traj = SimulationRunner._build_microscopic_trajectory(
            train_id="TRN_140KM",
            corridor_length_m=140000.0,
            train_length_m=200.0,
            max_speed_ms=55.55,
            running_direction=RunningDirection.FORWARD,
        )
        assert len(traj.samples) > 1000
        assert 1500.0 <= traj.journey_time_s <= 3600.0, (
            f"Expected 140 km journey duration between 1500s and 3600s, got {traj.journey_time_s:.1f}s"
        )

    def test_e2e_07_hsr_140km_corridor_pipeline(self):
        """Verify full pipeline execution on 140 km HSR corridor (447 links, 92 blocks, 5 stations).

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_e2e_reverse_simulation_monotonicity_and_equivalence(self):
        """Verify reverse simulation completes with monotonically decreasing corridor distance.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_e2e_platform_occupation_chronological_ordering(self):
        """Verify platform occupation records are ordered chronologically with realistic timestamps.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_e2e_html_report_zero_cdn_dependencies(self):
        """Verify generated HTML report embeds Plotly offline and has zero references to cdn.plot.ly.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_station_stops_populated_from_service_pattern(self):
        """DEF-03: Assert package.metadata['station_stops'] is populated from service pattern.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_section_station_stopping_is_applicable(self):
        """DEF-03: Assert ReportSectionId.STATION_STOPPING_TABLE is applicable with engineering table.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_permissible_speed_envelope_is_piecewise(self):
        """P13-SPD-001: Assert speed envelope is piecewise, monotonic, and bounds the corridor.

        v1.11.2 (literal strict): 05_comprehensive_line, 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_envelope_matches_track_link_limits(self):
        """P13-SPD-001: Assert envelope contains at least one point within each link matching its limit.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_station_stops_and_envelope_reverse_direction(self):
        """Assert reverse direction reverses station stop order and mirrors envelope.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_service_pattern_ambiguous_raises_error(self):
        """Assert ERR_SERVICE_PATTERN_AMBIGUOUS raised when multiple patterns cannot be resolved.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_station_stop_field_missing_raises_error(self):
        """Assert ERR_STATION_STOP_FIELD_MISSING raised when station/platform cannot be resolved.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_headway_responds_to_dwell(self):
        """DEF-05: Technical minimum headway responds monotonically to dwell duration changes.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_headway_responds_to_performance_factor(self):
        """DEF-05: Technical minimum headway responds to rolling stock performance factor.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_headway_is_not_fudged(self):
        """DEF-05: Headway equals microscopic controlling block duration with NO +15.0 constant.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_headway_dwell_appears_in_controlling_resource(self):
        """DEF-05/DEF-06: Station dwell appears in the controlling resource's decomposition.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_setup_approach_release_nonzero_on_hsr_corridor(self):
        """DEF-06: Setup, approach, and release are non-zero on non-origin corridor blocks.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_origin_block_has_zero_approach(self):
        """DEF-06: Origin block has zero approach time because train is already stationary at platform.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_decomposition_components_sum_to_duration(self):
        """DEF-06: Seven additive decomposition components reconcile with interval duration for every block.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_controlling_resource_switches_to_terminal_after_enrichment(self):
        """DEF-06: Controlling bottleneck switches from origin BLK_UP_001 to terminal BLK_UP_092.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_origin_block_undetermined_raises_error(self):
        """DEF-06: ERR_ORIGIN_BLOCK_UNDETERMINED raised when origin block cannot be mapped from route.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_headway_responds_to_dwell_on_multilink_corridor(self):
        """DEF-05: Technical minimum headway responds to dwell duration on 140 km corridor.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_headway_responds_to_performance_factor_on_multilink_corridor(self):
        """DEF-05: Technical minimum headway responds to performance factor on 140 km corridor.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_headway_no_intervals_raises_error(self):
        """DEF-05: ERR_HEADWAY_NO_INTERVALS raised when no usage records are extracted.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_leader_trajectory_empty_raises_error(self):
        """DEF-05: ERR_LEADER_TRAJECTORY_EMPTY raised when leader trajectory contains no samples.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_headway_infeasible_raises_error(self):
        """DEF-05: ERR_HEADWAY_INFEASIBLE raised when headway solution is infeasible or non-positive.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_def14_forward_trajectory_has_exactly_five_dwells(self):
        """DEF-14 Task 1/4: Assert Forward simulation on 140 km corridor has exactly 5 dwell periods.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_def14_reverse_trajectory_has_five_dwells_and_mirrored_chainage(self):
        """DEF-14 Task 2/4: Assert Reverse simulation on 140 km corridor has 5 dwells, monotonic decrease 140k -> 0m.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_def14_reverse_stairway_chart_y_axis_and_x_axis(self):
        """DEF-14 Task 3/4: Assert Reverse Stairway chart has time increasing from 0 to max, 0 at top.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_def14_user_corridor_with_stn_ads_five_dwells_forward_and_reverse(self):
        """DEF-14 Task 1/2: Verify user corridor with STN_ADS (4.4km), STN_YAS (24.21km), STN_MKT (101.79km).

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")

    def test_simulated_speed_never_exceeds_permissible(self):
        """DEF-16 / v1.9.3: Simulated speed strictly conforms to permissible speed envelope.

        v1.11.2 (literal strict): 07_hsr_140km fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("07_hsr_140km")




def _run_both_directions(project_factory):
    """Run the pipeline FORWARD and REVERSE; returns {direction: (pkg, doc) | exception}."""
    out = {}
    for d in BOTH_DIRECTIONS:
        try:
            out[d] = SimulationRunner.run_simulation_pipeline(
                project_factory(), running_direction=d, simulation_mode="Full Integrated Suite"
            )
        except BlockGeometryValidationError as exc:
            out[d] = exc
    return out


def _route_ordered(pkg):
    return sorted(pkg.blocking_intervals, key=lambda i: (i.physical_start_offset_m, i.physical_end_offset_m))


def _speed_discontinuities(pkg, tol_kmh=0.1):
    """Contiguous blocks (shared boundary position) whose v_out / v_in differ by > tol."""
    ivs = _route_ordered(pkg)
    return [
        (a.resource_id, b.resource_id, a.decomposition.v_out_kmh, b.decomposition.v_in_kmh)
        for a, b in zip(ivs, ivs[1:])
        if abs(a.physical_end_offset_m - b.physical_start_offset_m) < 1e-6
        and abs(a.decomposition.v_out_kmh - b.decomposition.v_in_kmh) > tol_kmh
    ]


_SYMMETRY_CASES = [pytest.param(ex, id=ex) for ex in ALL_EXAMPLES] + [
    pytest.param("05_comprehensive_line+explicit_turnaround_exits", id="05_turnaround_variant")
]


class TestBidirectionalSymmetry:
    """v1.11.2 / Task 12: every example behaves identically in FORWARD and REVERSE.

    * an example that fails validation must fail in BOTH directions with the same
      error_code and the same findings (and exactly the documented ones);
    * an example that runs must produce the same block count and the same resource IDs
      in both directions (REVERSE visits them in exactly the reverse order), with zero
      boundary-speed discontinuities > 0.1 km/h between contiguous blocks in either
      direction.
    """

    @pytest.mark.parametrize("case", _SYMMETRY_CASES)
    def test_forward_reverse_symmetry(self, case):
        if case.endswith("+explicit_turnaround_exits"):
            factory = comprehensive_line_with_explicit_turnaround_exits
        else:
            factory = lambda: FileManager.load_example_project(case)[0]  # noqa: E731

        res = _run_both_directions(factory)
        fwd, rev = res[RunningDirection.FORWARD], res[RunningDirection.REVERSE]

        if isinstance(fwd, Exception) or isinstance(rev, Exception):
            assert isinstance(fwd, BlockGeometryValidationError), f"FORWARD ran but REVERSE raised: {rev}"
            assert isinstance(rev, BlockGeometryValidationError), f"REVERSE ran but FORWARD raised: {fwd}"
            assert fwd.error_code == rev.error_code
            assert findings_by_code(fwd) == findings_by_code(rev)
            assert [f.message for f in fwd.findings] == [f.message for f in rev.findings]
            assert_block_geometry_error(fwd, case)
            return

        assert case not in EXPECTED_BLOCK_GEOMETRY_ERRORS, f"{case} was expected to raise"
        (pkg_f, _doc_f), (pkg_r, _doc_r) = fwd, rev
        ids_f = [i.resource_id for i in _route_ordered(pkg_f)]
        ids_r = [i.resource_id for i in _route_ordered(pkg_r)]
        assert len(ids_f) == len(ids_r)
        assert set(ids_f) == set(ids_r)
        assert ids_r == list(reversed(ids_f))
        assert _speed_discontinuities(pkg_f) == []
        assert _speed_discontinuities(pkg_r) == []


class TestCleanExampleErrorPaths:
    """Error paths and sensitivities formerly exercised on 05 / 07 (which now stop at
    pre-simulation validation), re-exercised on the clean example 06_multilink_blocks."""

    @pytest.fixture()
    def clean_project(self):
        project, report, _ = FileManager.load_example_project(CLEAN_EXAMPLE)
        assert report.is_simulation_ready
        return copy.deepcopy(project)

    def test_service_pattern_ambiguous_raises_error(self, clean_project):
        p = clean_project
        p.operations.service_patterns = [
            p.operations.service_patterns[0].model_copy(update={"service_pattern_id": "AMBIG_1"}),
            p.operations.service_patterns[0].model_copy(update={"service_pattern_id": "AMBIG_2"}),
        ]
        with pytest.raises(ServicePatternAmbiguousError) as exc_info:
            SimulationRunner.run_simulation_pipeline(
                project=p, running_direction=RunningDirection.FORWARD, scenario_id="UNKNOWN_SCENARIO"
            )
        assert "ERR_SERVICE_PATTERN_AMBIGUOUS" in str(exc_info.value)

    def test_station_stop_field_missing_raises_error(self, clean_project):
        clean_project.operations.service_patterns[0].stops[0].platform_id = "PLT_NON_EXISTENT"
        with pytest.raises(StationStopFieldMissingError) as exc_info:
            SimulationRunner.run_simulation_pipeline(project=clean_project, running_direction=RunningDirection.FORWARD)
        assert "ERR_STATION_STOP_FIELD_MISSING" in str(exc_info.value)

    def test_headway_responds_to_dwell(self, clean_project):
        p2 = copy.deepcopy(clean_project)
        _pkg1, doc1 = SimulationRunner.run_simulation_pipeline(clean_project, RunningDirection.FORWARD)
        for st_stop in p2.operations.service_patterns[0].stops:
            st_stop.dwell_time_s = float(st_stop.dwell_time_s) + 60.0
        pkg2, doc2 = SimulationRunner.run_simulation_pipeline(p2, RunningDirection.FORWARD)
        hw1, hw2 = doc1.executive_kpis.technical_headway_s, doc2.executive_kpis.technical_headway_s
        assert hw2 > hw1, f"Expected headway to increase with dwell: {hw1:.1f}s vs {hw2:.1f}s"
        assert pkg2.metadata["technical_minimum_headway_s"] == hw2

    def test_headway_responds_to_performance_factor(self, clean_project):
        _p1, doc1 = SimulationRunner.run_simulation_pipeline(clean_project, RunningDirection.FORWARD, performance_factor=1.0)
        pkg8, doc8 = SimulationRunner.run_simulation_pipeline(clean_project, RunningDirection.FORWARD, performance_factor=0.8)
        assert doc8.executive_kpis.technical_headway_s > doc1.executive_kpis.technical_headway_s
        assert pkg8.metadata["performance_factor"] == 0.8

    def test_origin_block_undetermined_raises_error(self, clean_project, monkeypatch):
        from headway.infrastructure.route import Route

        monkeypatch.setattr(Route, "physical_to_route_distance", lambda self, link_id, offset: None)
        with pytest.raises(SimulationRunnerError) as exc_info:
            SimulationRunner.run_simulation_pipeline(clean_project, RunningDirection.FORWARD)
        assert "ERR_ORIGIN_BLOCK_UNDETERMINED" in str(exc_info.value)

    def test_headway_no_intervals_raises_error(self, clean_project, monkeypatch):
        from headway.signalling.coordinator import SignallingCoordinator

        monkeypatch.setattr(SignallingCoordinator, "get_resource_usage_records", lambda self: [])
        with pytest.raises(HeadwayNoIntervalsError) as exc_info:
            SimulationRunner.run_simulation_pipeline(project=clean_project, running_direction=RunningDirection.FORWARD)
        assert "ERR_HEADWAY_NO_INTERVALS" in str(exc_info.value)

    def test_leader_trajectory_empty_raises_error(self, clean_project, monkeypatch):
        from headway.simulation.trajectory import TrainTrajectory

        empty = TrainTrajectory(
            train_id="TRN_LEADER", train_type_id="TT_01", route_id="RT_01",
            running_direction=RunningDirection.FORWARD, samples=[],
        )
        monkeypatch.setattr(SimulationRunner, "_extract_trajectory", lambda train: empty)
        with pytest.raises(LeaderTrajectoryEmptyError) as exc_info:
            SimulationRunner.run_simulation_pipeline(project=clean_project, running_direction=RunningDirection.FORWARD)
        assert "ERR_LEADER_TRAJECTORY_EMPTY" in str(exc_info.value)

    def test_headway_infeasible_raises_error(self, clean_project, monkeypatch):
        from headway.analysis.headway_results import HeadwayResult, HeadwayValidationStatus
        from headway.analysis.headway_solver import TechnicalHeadwaySolver

        orig_solve = TechnicalHeadwaySolver.solve_pairwise_headway

        def mock_infeasible(self, *args, **kwargs):
            res = orig_solve(self, *args, **kwargs)
            return HeadwayResult(
                run_id=res.run_id, analysis_id=res.analysis_id, scenario_id=res.scenario_id,
                leader_service_id=res.leader_service_id, follower_service_id=res.follower_service_id,
                reference_point_id=res.reference_point_id, running_direction=res.running_direction,
                signalling_system=res.signalling_system, headway_definition=res.headway_definition,
                headway_s=0.0, minimum_dispatch_headway_s=0.0,
                verification_status=HeadwayValidationStatus.INFEASIBLE,
            )

        monkeypatch.setattr(TechnicalHeadwaySolver, "solve_pairwise_headway", mock_infeasible)
        with pytest.raises(HeadwayInfeasibleError) as exc_info:
            SimulationRunner.run_simulation_pipeline(project=clean_project, running_direction=RunningDirection.FORWARD)
        assert "ERR_HEADWAY_INFEASIBLE" in str(exc_info.value)
