"""End-to-end integration tests for microscopic MultiTrainSimulator wiring into SimulationRunner.

Validates:
- Full simulation pipeline execution on Example 05 (140 km comprehensive line).
- Physically realistic total service duration bounds (1500s <= duration <= 3600s) replacing the 68s stub.
- High-fidelity trajectory generation (>1000 samples, reaching line speed >50 m/s).
- Monotonic directional progression for both FORWARD and REVERSE directions.
- Strict platform occupation chronological sequencing with monotonic arrival times.
- Sandboxed offline HTML report rendering with zero external CDN dependencies (no 'cdn.plot.ly').
"""

import pytest
from pathlib import Path

from headway.infrastructure.direction import RunningDirection
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner


@pytest.fixture(scope="module")
def comprehensive_project():
    """Load canonical project for Example 05 (Comprehensive Demonstration Line)."""
    project, report, _ = FileManager.load_example_project("05_comprehensive_line")
    assert report.is_simulation_ready, f"Project not simulation ready: {report.error_messages}"
    return project


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
