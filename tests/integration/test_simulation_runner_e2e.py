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
    ServicePatternAmbiguousError,
    SimulationRunner,
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

        # Verify journey duration bounds for 52 km corridor (900s - 1500s) replacing 68s stub
        journey_time_s = traj_leader.journey_time_s
        assert 900.0 <= journey_time_s <= 1500.0, (
            f"Expected journey time between 900s and 1500s, got {journey_time_s:.1f}s"
        )

        # Executive KPI total service duration (from origin platform departure to destination arrival)
        total_duration = doc.executive_kpis.total_service_duration_s
        assert total_duration is not None
        assert 600.0 <= total_duration <= 1500.0, (
            f"Expected total service duration between 600s and 1500s, got {total_duration:.1f}s"
        )

        # Physical corridor traversal (0m to total_corridor_m)
        total_corridor_m = sum(lnk.length_m for lnk in comprehensive_project.infrastructure.track_links)
        assert traj_leader.samples[0].front_distance_m <= 1.0
        assert abs(traj_leader.samples[-1].front_distance_m - total_corridor_m) < 100.0

        # Max speed achieved should exceed 50 m/s (180 km/h) along the 200 km/h corridor
        max_v = max(s.speed_ms for s in traj_leader.samples)
        assert max_v > 50.0, f"Expected train to reach >50 m/s, reached {max_v:.1f} m/s"

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
        assert 2000.0 <= doc.executive_kpis.total_service_duration_s <= 3000.0
        assert doc.executive_kpis.controlling_bottleneck_id == "BLK_UP_092"
        assert doc.executive_kpis.technical_headway_s == 52.9

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

        prev_arr = 0.0
        for rec in platform_records:
            # Chronological arrival progression across corridor
            assert rec.arrival_time_s >= prev_arr, (
                f"Non-chronological arrival at {rec.station_id}: {rec.arrival_time_s} < {prev_arr}"
            )
            # Station stop internal event chronology
            assert rec.arrival_time_s <= rec.dwell_start_time_s
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

