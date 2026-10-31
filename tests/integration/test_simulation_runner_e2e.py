"""End-to-end integration tests for microscopic MultiTrainSimulator wiring into SimulationRunner.

Validates:
- Full simulation pipeline execution on Example 05 (140 km comprehensive line).
- Physically realistic total service duration bounds (1500s <= duration <= 3600s) replacing the 68s stub.
- High-fidelity trajectory generation (>1000 samples, reaching line speed >50 m/s).
- Monotonic directional progression for both FORWARD and REVERSE directions.
- Strict platform occupation chronological sequencing with monotonic arrival times.
- Sandboxed offline HTML report rendering with zero external CDN dependencies (no 'cdn.plot.ly').
"""

import copy
from pathlib import Path
import pytest

from headway.data.canonical import TrackDirectionality
from headway.infrastructure.direction import RunningDirection
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.report_assembly import ReportAssembler
from headway.reporting.report_models import ReportSectionId
from headway.reporting.result_models import StationStopRecord
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


@pytest.fixture(scope="module")
def comprehensive_project():
    """Load canonical project for Example 05 (Comprehensive Demonstration Line)."""
    project, report, _ = FileManager.load_example_project("05_comprehensive_line")
    assert report.is_simulation_ready, f"Project not simulation ready: {report.error_messages}"
    return project


@pytest.fixture(scope="module")
def hsr_project():
    """Load canonical project for Example 07 (140 km HSR Corridor)."""
    project, report, _ = FileManager.load_example_project("07_hsr_140km")
    assert report.is_simulation_ready, f"Project not simulation ready: {report.error_messages}"
    return project


@pytest.fixture(scope="module")
def hsr_sim_results(hsr_project):
    """Run full simulation pipeline once on Example 07 for module tests."""
    return SimulationRunner.run_simulation_pipeline(
        project=hsr_project,
        running_direction=RunningDirection.FORWARD,
    )


@pytest.fixture(scope="module")
def hsr_rev_sim_results(hsr_project):
    """Run full simulation pipeline once on Example 07 in REVERSE direction."""
    return SimulationRunner.run_simulation_pipeline(
        project=hsr_project,
        running_direction=RunningDirection.REVERSE,
    )


class TestSimulationRunnerE2E:
    """Comprehensive end-to-end validation suite for SimulationRunner microscopic engine."""

    def test_e2e_forward_simulation_dynamics_and_duration_bounds(self, comprehensive_project):
        """Verify forward simulation runs with microscopic engine and produces realistic duration."""
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=comprehensive_project,
            running_direction=RunningDirection.FORWARD,
        )

        assert pkg is not None
        assert doc is not None

        # Verify trajectory presence and microscopic fidelity
        assert "TRN_LEADER" in pkg.trajectories
        assert "TRN_FOLLOWER" in pkg.trajectories
        traj_leader = pkg.trajectories["TRN_LEADER"]
        traj_follower = pkg.trajectories["TRN_FOLLOWER"]

        # Replaced 35-sample stub with full microscopic trajectory (>1000 samples)
        assert len(traj_leader.samples) > 1000, f"Expected >1000 samples, got {len(traj_leader.samples)}"
        assert len(traj_follower.samples) > 1000, f"Expected >1000 samples, got {len(traj_follower.samples)}"

        # Verify journey duration bounds for 52 km corridor (900s - 1800s) replacing 68s stub
        journey_time_s = traj_leader.journey_time_s
        assert 900.0 <= journey_time_s <= 1800.0, (
            f"Expected journey time between 900s and 1800s, got {journey_time_s:.1f}s"
        )

        # Executive KPI total service duration (from origin platform departure to destination arrival)
        total_duration = doc.executive_kpis.total_service_duration_s
        assert total_duration is not None
        assert 600.0 <= total_duration <= 1800.0, (
            f"Expected total service duration between 600s and 1800s, got {total_duration:.1f}s"
        )

        # Physical corridor traversal (0m to total_corridor_m)
        total_corridor_m = sum(lnk.length_m for lnk in comprehensive_project.infrastructure.track_links)
        assert traj_leader.samples[0].front_distance_m <= 1.0
        assert abs(traj_leader.samples[-1].front_distance_m - total_corridor_m) < 100.0

        # Max speed achieved reaches civil line limit of corridor (160 km/h = 44.4 m/s)
        max_v = max(s.speed_ms for s in traj_leader.samples)
        assert max_v >= 40.0, f"Expected train to reach >=40 m/s, reached {max_v:.1f} m/s"

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
        """Verify full pipeline execution on 140 km HSR corridor (447 links, 92 blocks, 5 stations)."""
        project, report, _ = FileManager.load_example_project("07_hsr_140km")
        assert report.is_simulation_ready
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=project,
            running_direction=RunningDirection.FORWARD,
            performance_factor=1.0,
        )
        assert pkg is not None
        assert doc is not None
        assert len(pkg.trajectories["TRN_LEADER"].samples) > 2500
        assert 2000.0 <= doc.executive_kpis.total_service_duration_s <= 3600.0  # v1.11.0/DEF-18: 3001 s with exact station stopping
        assert doc.executive_kpis.controlling_bottleneck_id == "BLK_UP_092"
        technical_headway_s = doc.executive_kpis.technical_headway_s
        assert 235.0 < technical_headway_s < 265.0
        assert technical_headway_s == pytest.approx(254.0, abs=6.0)  # v1.11.0/DEF-18 new physics baseline

    def test_e2e_reverse_simulation_monotonicity_and_equivalence(self, comprehensive_project):
        """Verify reverse simulation completes with monotonically decreasing corridor distance."""
        pkg_fwd, doc_fwd = SimulationRunner.run_simulation_pipeline(
            project=comprehensive_project,
            running_direction=RunningDirection.FORWARD,
        )
        pkg_rev, doc_rev = SimulationRunner.run_simulation_pipeline(
            project=comprehensive_project,
            running_direction=RunningDirection.REVERSE,
        )

        traj_fwd = pkg_fwd.trajectories["TRN_LEADER"]
        traj_rev = pkg_rev.trajectories["TRN_LEADER"]

        # Trajectory lengths should be comparable (within 5% difference)
        t_fwd = traj_fwd.journey_time_s
        t_rev = traj_rev.journey_time_s
        assert abs(t_fwd - t_rev) / t_fwd < 0.05, (
            f"Directional asymmetry: FWD {t_fwd:.1f}s vs REV {t_rev:.1f}s"
        )

        # Monotonicity check: REVERSE trajectory distances must decrease from corridor end to 0
        total_corridor_m = sum(lnk.length_m for lnk in comprehensive_project.infrastructure.track_links)
        assert abs(traj_rev.samples[0].front_distance_m - total_corridor_m) < 100.0
        assert traj_rev.samples[-1].front_distance_m == 0.0

        prev_d = float("inf")
        for s in traj_rev.samples:
            assert s.front_distance_m <= prev_d + 1e-3, (
                f"Non-monotonic reverse sample: {s.front_distance_m} > {prev_d}"
            )
            prev_d = s.front_distance_m

    def test_e2e_platform_occupation_chronological_ordering(self, comprehensive_project):
        """Verify platform occupation records are ordered chronologically with realistic timestamps."""
        pkg, _ = SimulationRunner.run_simulation_pipeline(
            project=comprehensive_project,
            running_direction=RunningDirection.FORWARD,
        )

        platform_records = pkg.metadata.get("platform_records", [])
        assert len(platform_records) > 0, "Expected non-empty platform records"

        # v1.11.1 / Task 3: zeroed `never_occupied` placeholder rows (platforms neither
        # traversed nor assigned) carry no chronology and are excluded from the ordering audit.
        occupied_records = [r for r in platform_records if not getattr(r, "never_occupied", False)]
        assert len(occupied_records) > 0, "Expected at least one genuinely occupied platform record"

        prev_arr = 0.0
        for rec in occupied_records:
            # Chronological arrival progression across corridor
            assert rec.arrival_time_s >= prev_arr, (
                f"Non-chronological arrival at {rec.station_id}: {rec.arrival_time_s} < {prev_arr}"
            )
            # Station stop internal event chronology
            assert rec.arrival_time_s <= rec.dwell_start_time_s
            # v1.11.0 / Task 4: records are now trajectory-derived. A train only dwells
            # at platforms its ACTIVE service pattern stops at; pass-through platforms
            # have a physical zero-length dwell window (dwell_start == dwell_end).
            if rec.dwell_start_time_s == rec.dwell_end_time_s:
                assert rec.arrival_time_s == rec.dwell_start_time_s  # pass-through: no standstill
            else:
                assert rec.dwell_start_time_s < rec.dwell_end_time_s
            assert rec.dwell_end_time_s <= rec.departure_time_s
            assert rec.departure_time_s < rec.clearance_time_s

            prev_arr = rec.departure_time_s

    def test_e2e_html_report_zero_cdn_dependencies(self, comprehensive_project, tmp_path):
        """Verify generated HTML report embeds Plotly offline and has zero references to cdn.plot.ly."""
        _, doc = SimulationRunner.run_simulation_pipeline(
            project=comprehensive_project,
            running_direction=RunningDirection.FORWARD,
        )

        renderer = HtmlReportRenderer()
        html_out = tmp_path / "report_e2e.html"
        renderer.render(doc, html_out)

        assert html_out.exists()
        content = html_out.read_text(encoding="utf-8")

        # Must not contain external cdn.plot.ly references
        assert "cdn.plot.ly" not in content, "HTML report contains un-inlined external CDN URL cdn.plot.ly"
        assert "https://cdn.plot.ly" not in content

        # Must contain embedded interactive Plotly chart structure and JS bundle
        assert "plotly-graph-div" in content
        assert "Plotly" in content

    def test_station_stops_populated_from_service_pattern(self, hsr_project, hsr_sim_results):
        """DEF-03: Assert package.metadata['station_stops'] is populated from service pattern."""
        pkg, _ = hsr_sim_results
        station_stops = pkg.metadata.get("station_stops")
        assert station_stops is not None
        assert len(station_stops) > 0

        active_pattern = hsr_project.operations.service_patterns[0]
        assert len(station_stops) == len(active_pattern.stops)

        prev_arr = -1.0
        for rec in station_stops:
            assert isinstance(rec, StationStopRecord)
            assert rec.arrival_time_s is not None
            assert rec.departure_time_s is not None
            assert rec.front_stopping_position_m is not None
            assert rec.rear_stopping_position_m is not None
            assert rec.station_name is not None and len(rec.station_name) > 0
            assert rec.arrival_time_s > prev_arr
            assert rec.departure_time_s == pytest.approx(rec.arrival_time_s + rec.dwell_duration_s, abs=0.01)
            prev_arr = rec.arrival_time_s

    def test_section_station_stopping_is_applicable(self, hsr_sim_results):
        """DEF-03: Assert ReportSectionId.STATION_STOPPING_TABLE is applicable with engineering table."""
        pkg, _ = hsr_sim_results
        doc = ReportAssembler.assemble_report(pkg)
        assert ReportSectionId.STATION_STOPPING_TABLE in doc.sections
        section = doc.sections[ReportSectionId.STATION_STOPPING_TABLE]
        assert section.is_applicable is True
        assert len(section.tables) >= 1
        assert section.tables[0].row_count == len(pkg.metadata["station_stops"])

    def test_permissible_speed_envelope_is_piecewise(self, comprehensive_project, hsr_project, hsr_sim_results):
        """P13-SPD-001: Assert speed envelope is piecewise, monotonic, and bounds the corridor."""
        # 1. Multi-speed corridor (05_comprehensive_line)
        pkg_comp, _ = SimulationRunner.run_simulation_pipeline(
            project=comprehensive_project,
            running_direction=RunningDirection.FORWARD,
        )
        env_comp = pkg_comp.metadata.get("permissible_speed_envelope")
        assert isinstance(env_comp, list) and len(env_comp) > 0
        for pt in env_comp:
            assert "route_distance_m" in pt
            assert "max_speed_kmh" in pt

        # Monotonically non-decreasing in route_distance_m
        for i in range(len(env_comp) - 1):
            assert env_comp[i + 1]["route_distance_m"] >= env_comp[i]["route_distance_m"]

        total_route_comp = sum(lnk.length_m for lnk in comprehensive_project.infrastructure.track_links)
        assert env_comp[-1]["route_distance_m"] == pytest.approx(total_route_comp, abs=1.0)

        # Multi-speed corridor must reflect at least two distinct speed limits
        speeds_comp = {pt["max_speed_kmh"] for pt in env_comp}
        assert len(speeds_comp) >= 2

        # 2. HSR corridor (07_hsr_140km) reflecting 320 km/h limit
        pkg_hsr, _ = hsr_sim_results
        env_hsr = pkg_hsr.metadata.get("permissible_speed_envelope")
        assert isinstance(env_hsr, list) and len(env_hsr) > 0
        speeds_hsr = {pt["max_speed_kmh"] for pt in env_hsr}
        assert speeds_hsr == {320.0}
        total_route_hsr = sum(lnk.length_m for lnk in hsr_project.infrastructure.track_links)
        assert env_hsr[-1]["route_distance_m"] == pytest.approx(total_route_hsr, abs=1.0)

    def test_envelope_matches_track_link_limits(self, comprehensive_project):
        """P13-SPD-001: Assert envelope contains at least one point within each link matching its limit."""
        pkg, _ = SimulationRunner.run_simulation_pipeline(
            project=comprehensive_project,
            running_direction=RunningDirection.FORWARD,
        )
        envelope = pkg.metadata.get("permissible_speed_envelope", [])
        cum_m = 0.0
        for lnk in comprehensive_project.infrastructure.track_links:
            lnk_start = cum_m
            lnk_end = cum_m + float(lnk.length_m)
            cum_m = lnk_end
            expected_spd = getattr(lnk, "max_speed_kmh", round(lnk.max_speed_ms * 3.6, 2))

            matching_pts = [
                pt for pt in envelope
                if lnk_start - 1e-3 <= pt["route_distance_m"] <= lnk_end + 1e-3
                and abs(pt["max_speed_kmh"] - expected_spd) < 0.1
            ]
            assert len(matching_pts) >= 1, (
                f"Link {lnk.link_id} [{lnk_start}, {lnk_end}] speed {expected_spd} km/h not matched in envelope"
            )

    def test_station_stops_and_envelope_reverse_direction(self, hsr_project, hsr_sim_results):
        """Assert reverse direction reverses station stop order and mirrors envelope."""
        pkg_fwd, _ = hsr_sim_results
        fwd_stops = [s.station_id for s in pkg_fwd.metadata["station_stops"]]

        # Adjust directionality of 07_hsr_140km to BIDIRECTIONAL to allow REVERSE simulation
        p_rev = copy.deepcopy(hsr_project)
        for t in p_rev.infrastructure.tracks:
            t.directionality = TrackDirectionality.BIDIRECTIONAL

        pkg_rev, _ = SimulationRunner.run_simulation_pipeline(
            project=p_rev,
            running_direction=RunningDirection.REVERSE,
            scenario_id="BASELINE",
        )

        rev_stops = [s.station_id for s in pkg_rev.metadata["station_stops"]]
        assert rev_stops == list(reversed(fwd_stops)), (
            f"Expected reverse stop sequence {list(reversed(fwd_stops))}, got {rev_stops}"
        )

        env_rev = pkg_rev.metadata["permissible_speed_envelope"]
        assert len(env_rev) > 0
        fwd_last_link = p_rev.infrastructure.track_links[-1]
        fwd_last_speed = getattr(fwd_last_link, "max_speed_kmh", round(fwd_last_link.max_speed_ms * 3.6, 2))
        assert env_rev[0]["max_speed_kmh"] == pytest.approx(fwd_last_speed, abs=0.1)

    def test_service_pattern_ambiguous_raises_error(self, comprehensive_project):
        """Assert ERR_SERVICE_PATTERN_AMBIGUOUS raised when multiple patterns cannot be resolved."""
        p = copy.deepcopy(comprehensive_project)
        # Duplicate active pattern with ambiguous IDs
        p.operations.service_patterns = [
            p.operations.service_patterns[0].model_copy(update={"service_pattern_id": "AMBIG_1"}),
            p.operations.service_patterns[0].model_copy(update={"service_pattern_id": "AMBIG_2"}),
        ]
        with pytest.raises(ServicePatternAmbiguousError) as exc_info:
            SimulationRunner.run_simulation_pipeline(
                project=p,
                running_direction=RunningDirection.FORWARD,
                scenario_id="UNKNOWN_SCENARIO",
            )
        assert "ERR_SERVICE_PATTERN_AMBIGUOUS" in str(exc_info.value)

    def test_station_stop_field_missing_raises_error(self, comprehensive_project):
        """Assert ERR_STATION_STOP_FIELD_MISSING raised when station/platform cannot be resolved."""
        p = copy.deepcopy(comprehensive_project)
        # Point stop to non-existent platform
        p.operations.service_patterns[0].stops[0].platform_id = "PLT_NON_EXISTENT"
        with pytest.raises(StationStopFieldMissingError) as exc_info:
            SimulationRunner.run_simulation_pipeline(
                project=p,
                running_direction=RunningDirection.FORWARD,
            )
        assert "ERR_STATION_STOP_FIELD_MISSING" in str(exc_info.value)

    def test_headway_responds_to_dwell(self, comprehensive_project):
        """DEF-05: Technical minimum headway responds monotonically to dwell duration changes."""
        p1 = copy.deepcopy(comprehensive_project)
        p2 = copy.deepcopy(comprehensive_project)

        # Baseline run
        pkg1, doc1 = SimulationRunner.run_simulation_pipeline(p1, RunningDirection.FORWARD)
        hw1 = doc1.executive_kpis.technical_headway_s

        # Increase all stop dwell times by 60 seconds
        for st_stop in p2.operations.service_patterns[0].stops:
            st_stop.dwell_time_s = float(st_stop.dwell_time_s) + 60.0

        pkg2, doc2 = SimulationRunner.run_simulation_pipeline(p2, RunningDirection.FORWARD)
        hw2 = doc2.executive_kpis.technical_headway_s

        assert hw2 > hw1, f"Expected headway to increase with dwell: hw1={hw1:.1f}s vs hw2={hw2:.1f}s"
        assert pkg2.metadata["technical_minimum_headway_s"] == hw2

    def test_headway_responds_to_performance_factor(self, comprehensive_project):
        """DEF-05: Technical minimum headway responds to rolling stock performance factor."""
        p = copy.deepcopy(comprehensive_project)

        pkg_pf1, doc_pf1 = SimulationRunner.run_simulation_pipeline(
            p, RunningDirection.FORWARD, performance_factor=1.0
        )
        pkg_pf8, doc_pf8 = SimulationRunner.run_simulation_pipeline(
            p, RunningDirection.FORWARD, performance_factor=0.8
        )

        hw1 = doc_pf1.executive_kpis.technical_headway_s
        hw8 = doc_pf8.executive_kpis.technical_headway_s

        # Reduced performance factor (0.8) lowers acceleration/speed, extending block clearance times
        assert hw8 > hw1, f"Lower performance factor must increase headway: {hw8:.1f}s > {hw1:.1f}s"
        assert pkg_pf8.metadata["performance_factor"] == 0.8

    def test_headway_is_not_fudged(self, hsr_sim_results):
        """DEF-05: Headway equals microscopic controlling block duration with NO +15.0 constant."""
        pkg, doc = hsr_sim_results
        controlling_iv = max(pkg.blocking_intervals, key=lambda b: b.duration_s)
        controlling_dur = controlling_iv.duration_s

        # Technical headway must match controlling duration exactly, NOT +15.0
        assert doc.executive_kpis.technical_headway_s == pytest.approx(controlling_dur, abs=0.01)
        assert doc.executive_kpis.technical_headway_s != pytest.approx(controlling_dur + 15.0, abs=0.01)
        # Verify metadata propagation
        assert pkg.metadata["technical_minimum_headway_s"] == doc.executive_kpis.technical_headway_s

    def test_headway_dwell_appears_in_controlling_resource(self, hsr_sim_results):
        """DEF-05/DEF-06: Station dwell appears in the controlling resource's decomposition."""
        pkg, doc = hsr_sim_results
        ctrl_id = doc.executive_kpis.controlling_bottleneck_id
        assert ctrl_id == "BLK_UP_092", f"Expected BLK_UP_092, got {ctrl_id}"
        ctrl_iv = next(iv for iv in pkg.blocking_intervals if iv.resource_id == ctrl_id)

        assert ctrl_iv.decomposition is not None
        assert ctrl_iv.decomposition.dwell_time_s == pytest.approx(120.0, abs=1.0)
        assert ctrl_iv.duration_s >= 120.0

    def test_setup_approach_release_nonzero_on_hsr_corridor(self, hsr_sim_results):
        """DEF-06: Setup, approach, and release are non-zero on non-origin corridor blocks."""
        pkg, _ = hsr_sim_results
        blk92 = next(b for b in pkg.blocking_intervals if b.resource_id == "BLK_UP_092")

        assert blk92.decomposition.setup_time_s == pytest.approx(3.0, abs=0.1)
        assert blk92.decomposition.approach_time_s == pytest.approx(10.0, abs=0.1)
        assert blk92.decomposition.release_time_s == pytest.approx(4.0, abs=0.1)
        # v1.11.0 / DEF-18: smooth braking-curve arrival extends terminal running time
        assert blk92.decomposition.running_time_s == pytest.approx(109.0, abs=5.0)
        assert blk92.decomposition.geometric_clearance_time_s > 0.0
        assert blk92.decomposition.dwell_time_s == pytest.approx(120.0, abs=1.0)
        assert blk92.duration_s == pytest.approx(254.0, abs=6.0)

    def test_origin_block_has_zero_approach(self, hsr_sim_results):
        """DEF-06: Origin block has zero approach time because train is already stationary at platform."""
        pkg, _ = hsr_sim_results
        blk01 = next(b for b in pkg.blocking_intervals if b.resource_id == "BLK_UP_001")

        assert blk01.decomposition.setup_time_s == pytest.approx(3.0, abs=0.1)
        assert blk01.decomposition.approach_time_s == 0.0
        assert blk01.decomposition.release_time_s == pytest.approx(4.0, abs=0.1)
        assert blk01.duration_s == pytest.approx(240.0, abs=6.0)

    def test_decomposition_components_sum_to_duration(self, hsr_sim_results):
        """DEF-06: Seven additive decomposition components reconcile with interval duration for every block."""
        pkg, _ = hsr_sim_results
        for iv in pkg.blocking_intervals:
            d = iv.decomposition
            comp_sum = (
                d.setup_time_s
                + d.approach_time_s
                + d.running_time_s
                + d.dwell_time_s
                + d.geometric_clearance_time_s
                + d.residual_rear_time_s
                + d.release_time_s
            )
            assert abs(comp_sum - iv.duration_s) < 0.1, (
                f"Block {iv.resource_id} decomposition {comp_sum:.3f}s does not reconcile with duration {iv.duration_s:.3f}s"
            )

    def test_controlling_resource_switches_to_terminal_after_enrichment(self, hsr_sim_results):
        """DEF-06: Controlling bottleneck switches from origin BLK_UP_001 to terminal BLK_UP_092."""
        pkg, doc = hsr_sim_results
        assert pkg.metadata["controlling_bottleneck_id"] == "BLK_UP_092"
        assert doc.executive_kpis.controlling_bottleneck_id == "BLK_UP_092"
        assert doc.executive_kpis.technical_headway_s == pytest.approx(254.0, abs=6.0)
        assert pkg.metadata["technical_minimum_headway_s"] == pytest.approx(254.0, abs=6.0)

    def test_origin_block_undetermined_raises_error(self, hsr_project, monkeypatch):
        """DEF-06: ERR_ORIGIN_BLOCK_UNDETERMINED raised when origin block cannot be mapped from route."""
        from headway.infrastructure.route import Route
        monkeypatch.setattr(Route, "physical_to_route_distance", lambda self, link_id, offset: None)
        with pytest.raises(SimulationRunnerError) as exc_info:
            SimulationRunner.run_simulation_pipeline(hsr_project, RunningDirection.FORWARD)
        assert "ERR_ORIGIN_BLOCK_UNDETERMINED" in str(exc_info.value)

    def test_headway_responds_to_dwell_on_multilink_corridor(self, hsr_project):
        """DEF-05: Technical minimum headway responds to dwell duration on 140 km corridor."""
        p1 = copy.deepcopy(hsr_project)
        p2 = copy.deepcopy(hsr_project)

        pkg1, doc1 = SimulationRunner.run_simulation_pipeline(p1, RunningDirection.FORWARD)
        hw1 = doc1.executive_kpis.technical_headway_s

        for st_stop in p2.operations.service_patterns[0].stops:
            st_stop.dwell_time_s = float(st_stop.dwell_time_s) + 60.0
            st_stop.min_dwell_s = float(st_stop.min_dwell_s) + 60.0

        pkg2, doc2 = SimulationRunner.run_simulation_pipeline(p2, RunningDirection.FORWARD)
        hw2 = doc2.executive_kpis.technical_headway_s

        assert hw2 > hw1, f"Expected headway to increase with dwell: hw1={hw1:.1f}s vs hw2={hw2:.1f}s"
        assert hw2 - hw1 == pytest.approx(60.0, abs=5.0)
        assert pkg2.metadata["technical_minimum_headway_s"] == hw2

    def test_headway_responds_to_performance_factor_on_multilink_corridor(self, hsr_project):
        """DEF-05: Technical minimum headway responds to performance factor on 140 km corridor."""
        p = copy.deepcopy(hsr_project)

        pkg_pf1, doc_pf1 = SimulationRunner.run_simulation_pipeline(
            p, RunningDirection.FORWARD, performance_factor=1.0
        )
        pkg_pf8, doc_pf8 = SimulationRunner.run_simulation_pipeline(
            p, RunningDirection.FORWARD, performance_factor=0.8
        )

        hw1 = doc_pf1.executive_kpis.technical_headway_s
        hw8 = doc_pf8.executive_kpis.technical_headway_s

        assert hw8 > hw1, f"Lower performance factor must increase headway: {hw8:.1f}s > {hw1:.1f}s"
        assert pkg_pf8.metadata["performance_factor"] == 0.8

    def test_headway_no_intervals_raises_error(self, comprehensive_project, monkeypatch):
        """DEF-05: ERR_HEADWAY_NO_INTERVALS raised when no usage records are extracted."""
        from headway.signalling.coordinator import SignallingCoordinator
        monkeypatch.setattr(
            SignallingCoordinator,
            "get_resource_usage_records",
            lambda self: [],
        )
        with pytest.raises(HeadwayNoIntervalsError) as exc_info:
            SimulationRunner.run_simulation_pipeline(
                project=comprehensive_project,
                running_direction=RunningDirection.FORWARD,
            )
        assert "ERR_HEADWAY_NO_INTERVALS" in str(exc_info.value)

    def test_leader_trajectory_empty_raises_error(self, comprehensive_project, monkeypatch):
        """DEF-05: ERR_LEADER_TRAJECTORY_EMPTY raised when leader trajectory contains no samples."""
        from headway.simulation.trajectory import TrainTrajectory
        empty_traj = TrainTrajectory(
            train_id="TRN_LEADER",
            train_type_id="TT_01",
            route_id="RT_01",
            running_direction=RunningDirection.FORWARD,
            samples=[],
        )
        monkeypatch.setattr(
            SimulationRunner,
            "_extract_trajectory",
            lambda train: empty_traj,
        )
        with pytest.raises(LeaderTrajectoryEmptyError) as exc_info:
            SimulationRunner.run_simulation_pipeline(
                project=comprehensive_project,
                running_direction=RunningDirection.FORWARD,
            )
        assert "ERR_LEADER_TRAJECTORY_EMPTY" in str(exc_info.value)

    def test_headway_infeasible_raises_error(self, comprehensive_project, monkeypatch):
        """DEF-05: ERR_HEADWAY_INFEASIBLE raised when headway solution is infeasible or non-positive."""
        from headway.analysis.headway_solver import TechnicalHeadwaySolver
        from headway.analysis.headway_results import HeadwayResult, HeadwayValidationStatus

        orig_solve = TechnicalHeadwaySolver.solve_pairwise_headway

        def mock_infeasible(self, *args, **kwargs):
            res = orig_solve(self, *args, **kwargs)
            return HeadwayResult(
                run_id=res.run_id,
                analysis_id=res.analysis_id,
                scenario_id=res.scenario_id,
                leader_service_id=res.leader_service_id,
                follower_service_id=res.follower_service_id,
                reference_point_id=res.reference_point_id,
                running_direction=res.running_direction,
                signalling_system=res.signalling_system,
                headway_definition=res.headway_definition,
                headway_s=0.0,
                minimum_dispatch_headway_s=0.0,
                verification_status=HeadwayValidationStatus.INFEASIBLE,
            )

        monkeypatch.setattr(TechnicalHeadwaySolver, "solve_pairwise_headway", mock_infeasible)
        with pytest.raises(HeadwayInfeasibleError) as exc_info:
            SimulationRunner.run_simulation_pipeline(
                project=comprehensive_project,
                running_direction=RunningDirection.FORWARD,
            )
        assert "ERR_HEADWAY_INFEASIBLE" in str(exc_info.value)

    def test_def14_forward_trajectory_has_exactly_five_dwells(self, hsr_sim_results):
        """DEF-14 Task 1/4: Assert Forward simulation on 140 km corridor has exactly 5 dwell periods."""
        pkg, doc = hsr_sim_results
        traj = pkg.trajectories["TRN_LEADER"]
        assert traj is not None
        assert len(traj.samples) > 0

        dwell_events = [
            e for e in getattr(traj, "events", [])
            if "STATION_ARRIVED" in str(getattr(e.event_type, "value", e.event_type))
        ]
        assert len(dwell_events) == 5, f"Expected 5 station arrived events, got {len(dwell_events)}"

        zero_samples = [s for s in traj.samples if s.speed_ms == 0.0]
        clusters = []
        for s in zero_samples:
            if s.front_distance_m >= 139999.0 or s.time_s == 0.0:
                continue
            if not clusters or abs(s.front_distance_m - clusters[-1][-1].front_distance_m) > 50.0:
                clusters.append([s])
            else:
                clusters[-1].append(s)

        assert len(clusters) == 5, f"Expected exactly 5 distinct station dwell clusters in forward run, got {len(clusters)}"
        for c in clusters:
            dwell_duration = c[-1].time_s - c[0].time_s
            assert dwell_duration >= 60.0, f"Dwell cluster at {c[0].front_distance_m}m lasted {dwell_duration}s < 60s"

    def test_def14_reverse_trajectory_has_five_dwells_and_mirrored_chainage(self, hsr_rev_sim_results):
        """DEF-14 Task 2/4: Assert Reverse simulation on 140 km corridor has 5 dwells, monotonic decrease 140k -> 0m."""
        pkg, doc = hsr_rev_sim_results
        traj = pkg.trajectories["TRN_LEADER"]
        assert traj is not None
        assert len(traj.samples) > 0

        # 1. Assert distance begins at physical end (140,000m) and ends at physical start (0m)
        assert traj.samples[0].front_distance_m == pytest.approx(140000.0, abs=100.0)
        assert traj.samples[-1].front_distance_m == pytest.approx(0.0, abs=50.0)

        # 2. Assert monotonic distance decrease
        for i in range(len(traj.samples) - 1):
            assert traj.samples[i].front_distance_m >= traj.samples[i + 1].front_distance_m, (
                f"Non-monotonic decrease at index {i}: {traj.samples[i].front_distance_m} < {traj.samples[i+1].front_distance_m}"
            )

        # 3. Assert exactly 5 dwell periods
        dwell_events = [
            e for e in getattr(traj, "events", [])
            if "STATION_ARRIVED" in str(getattr(e.event_type, "value", e.event_type))
        ]
        assert len(dwell_events) == 5, f"Expected 5 station arrived events in reverse, got {len(dwell_events)}"

        zero_samples = [s for s in traj.samples if s.speed_ms == 0.0]
        clusters = []
        for s in zero_samples:
            if s.front_distance_m <= 1.0 or s.time_s == 0.0:
                continue
            if not clusters or abs(s.front_distance_m - clusters[-1][-1].front_distance_m) > 50.0:
                clusters.append([s])
            else:
                clusters[-1].append(s)

        assert len(clusters) == 5, f"Expected exactly 5 distinct station dwell clusters in reverse run, got {len(clusters)}"
        for c in clusters:
            dwell_duration = c[-1].time_s - c[0].time_s
            assert dwell_duration >= 60.0, f"Dwell cluster at {c[0].front_distance_m}m lasted {dwell_duration}s < 60s"

    def test_def14_reverse_stairway_chart_y_axis_and_x_axis(self, hsr_rev_sim_results):
        """DEF-14 Task 3/4: Assert Reverse Stairway chart has time increasing from 0 to max, 0 at top."""
        from headway.reporting.charts_blocking import create_blocking_stairway_figure

        pkg, doc = hsr_rev_sim_results
        hw = next(iter(pkg.headway_results.values()))
        fig = create_blocking_stairway_figure(hw)

        assert fig.layout.yaxis.autorange == "reversed"
        assert fig.layout.xaxis.autorange == "reversed"

        leader_trace = next(t for t in fig.data if "Leader" in t.name)
        assert len(leader_trace.base) > 0
        start_times = [float(b) for b in leader_trace.base]
        assert start_times[0] <= 10.0
        assert start_times[-1] > 2000.0
        for i in range(len(start_times) - 1):
            assert start_times[i] <= start_times[i + 1]

    def test_def14_user_corridor_with_stn_ads_five_dwells_forward_and_reverse(self, hsr_project):
        """DEF-14 Task 1/2: Verify user corridor with STN_ADS (4.4km), STN_YAS (24.21km), STN_MKT (101.79km)."""
        from headway.data.canonical import Station, Platform, StationStop

        p = copy.deepcopy(hsr_project)
        p.infrastructure.stations = [
            Station(station_id="STN_ADR", name="Al-Dar Station", chainage_km=0.47),
            Station(station_id="STN_ADS", name="Al-Dar South Station", chainage_km=4.4),
            Station(station_id="STN_YAS", name="Yas Station", chainage_km=24.21),
            Station(station_id="STN_MKT", name="Makkah Terminus", chainage_km=101.79),
            Station(station_id="STN_DJD", name="Al-Djeddah Station", chainage_km=139.25),
        ]
        p.infrastructure.platforms = [
            Platform(platform_id="PLT_ADR", station_id="STN_ADR", link_id="LNK_0002", start_offset_m=50.0, end_offset_m=300.0, length_m=250.0),
            Platform(platform_id="PLT_ADS", station_id="STN_ADS", link_id="LNK_0015", start_offset_m=15.0, end_offset_m=265.0, length_m=250.0),
            Platform(platform_id="PLT_YAS", station_id="STN_YAS", link_id="LNK_0078", start_offset_m=10.0, end_offset_m=260.0, length_m=250.0),
            Platform(platform_id="PLT_MKT", station_id="STN_MKT", link_id="LNK_0326", start_offset_m=10.0, end_offset_m=260.0, length_m=250.0),
            Platform(platform_id="PLT_DJD", station_id="STN_DJD", link_id="LNK_0445", start_offset_m=50.0, end_offset_m=300.0, length_m=250.0),
        ]
        p.operations.service_patterns[0].stops = [
            StationStop(station_id="STN_ADR", platform_id="PLT_ADR", dwell_time_s=120.0, min_dwell_s=60.0),
            StationStop(station_id="STN_ADS", platform_id="PLT_ADS", dwell_time_s=120.0, min_dwell_s=60.0),
            StationStop(station_id="STN_YAS", platform_id="PLT_YAS", dwell_time_s=120.0, min_dwell_s=60.0),
            StationStop(station_id="STN_MKT", platform_id="PLT_MKT", dwell_time_s=120.0, min_dwell_s=60.0),
            StationStop(station_id="STN_DJD", platform_id="PLT_DJD", dwell_time_s=120.0, min_dwell_s=60.0),
        ]

        # 1. Forward run
        pkg_fwd, _ = SimulationRunner.run_simulation_pipeline(p, RunningDirection.FORWARD)
        traj_fwd = pkg_fwd.trajectories["TRN_LEADER"]
        fwd_stops = [
            e.description for e in getattr(traj_fwd, "events", [])
            if "STATION_ARRIVED" in str(getattr(e.event_type, "value", e.event_type))
        ]
        assert len(fwd_stops) == 5
        assert any("STN_ADS" in s for s in fwd_stops), f"STN_ADS not found in forward stops: {fwd_stops}"

        # 2. Reverse run
        pkg_rev, _ = SimulationRunner.run_simulation_pipeline(p, RunningDirection.REVERSE)
        traj_rev = pkg_rev.trajectories["TRN_LEADER"]
        rev_stops = [
            e.description for e in getattr(traj_rev, "events", [])
            if "STATION_ARRIVED" in str(getattr(e.event_type, "value", e.event_type))
        ]
        assert len(rev_stops) == 5
        assert any("STN_ADS" in s for s in rev_stops), f"STN_ADS not found in reverse stops: {rev_stops}"

    def test_simulated_speed_never_exceeds_permissible(self, hsr_project):
        """DEF-16 / v1.9.3: Simulated speed strictly conforms to permissible speed envelope."""
        p = copy.deepcopy(hsr_project)

        # Apply sharp speed drops between 20 km and 45 km matching user Excel scenario
        # Zone 1: 20 km to 35 km -> drops from 320 km/h to 204 km/h
        # Zone 2: 35 km to 45 km -> increases to 230 km/h
        # Zone 3: 45 km onwards -> returns to 320 km/h
        cum_d = 0.0
        for lnk in p.infrastructure.track_links:
            mid = cum_d + lnk.length_m / 2.0
            if 20000.0 <= mid < 35000.0:
                lnk.max_speed_ms = 204.0 / 3.6
            elif 35000.0 <= mid < 45000.0:
                lnk.max_speed_ms = 230.0 / 3.6
            cum_d += lnk.length_m

        # 1. Forward direction test
        pkg_fwd, _ = SimulationRunner.run_simulation_pipeline(p, RunningDirection.FORWARD)
        traj_fwd = pkg_fwd.trajectories["TRN_LEADER"]
        env_fwd = pkg_fwd.metadata["permissible_speed_envelope"]

        for s in traj_fwd.samples:
            d = s.front_distance_m
            perm_kmh = 320.0
            for pt in env_fwd:
                if pt["route_distance_m"] >= d:
                    perm_kmh = pt["max_speed_kmh"]
                    break
            assert s.speed_kmh <= perm_kmh + 0.1, (
                f"Forward speed overshoot at {d:.1f}m: {s.speed_kmh:.2f} km/h > {perm_kmh:.2f} km/h"
            )

        # Assert train brakes in advance before the 204 km/h zone
        braking_samples = [
            s for s in traj_fwd.samples
            if 17000.0 <= s.front_distance_m < 20032.0 and s.dynamic_mode.value in ("SERVICE_BRAKING", "BRAKING")
        ]
        assert len(braking_samples) > 0, "Train did not brake in advance of speed drop at 20 km"

        zone_20_35 = [s for s in traj_fwd.samples if 20032.0 <= s.front_distance_m <= 35000.0]
        assert len(zone_20_35) > 0
        assert max(s.speed_kmh for s in zone_20_35) <= 204.0 + 0.1

        zone_35_45 = [s for s in traj_fwd.samples if 35032.0 <= s.front_distance_m <= 45000.0]
        assert len(zone_35_45) > 0
        assert max(s.speed_kmh for s in zone_35_45) <= 230.0 + 0.1

        # 2. Reverse direction test
        pkg_rev, _ = SimulationRunner.run_simulation_pipeline(p, RunningDirection.REVERSE)
        traj_rev = pkg_rev.trajectories["TRN_LEADER"]
        env_rev = pkg_rev.metadata["permissible_speed_envelope"]
        tot_d = sum(lnk.length_m for lnk in p.infrastructure.track_links)

        for s in traj_rev.samples:
            # In reverse, s.front_distance_m is physical chainage; route distance is tot_d - s.front_distance_m
            route_dist = tot_d - s.front_distance_m
            perm_kmh = env_rev[-1]["max_speed_kmh"]
            for pt in env_rev:
                if pt["route_distance_m"] >= route_dist:
                    perm_kmh = pt["max_speed_kmh"]
                    break
            assert s.speed_kmh <= perm_kmh + 0.1, (
                f"Reverse speed overshoot at chainage {s.front_distance_m:.1f}m: {s.speed_kmh:.2f} km/h > {perm_kmh:.2f} km/h"
            )


