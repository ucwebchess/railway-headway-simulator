"""Unit tests for the v1.11.1 hotfix (Phase 4c sensitivity & geometry hotfix).

Covers:
- Task 2: residual-rear attribution helper `_compute_residual_rear_durations`
  (windowed overlap + positional guard at block exit boundary).
- Task 7: ERR_BLOCK_LENGTH_MISMATCH loud failure when a block's length disagrees
  with its entry/exit signal chainage span by more than 1.0 m — for ANY chainage
  source — gated by `ReportConfig.validate_block_geometry` (ships OFF in v1.11.1).
- Q2: canonical `metadata["journey_time_s"]` published from the leader trajectory.
- Q4: Task 5 alignment of blocks on links running against increasing chainage.
"""

import dataclasses
from types import SimpleNamespace

import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_assembly import ReportAssembler, ReportingError
from headway.reporting.report_config import VALIDATE_BLOCK_GEOMETRY_DEFAULT, ReportConfig
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner, _compute_residual_rear_durations


def _samples(times, dists):
    return [SimpleNamespace(time_s=t, front_distance_m=d) for t, d in zip(times, dists)]


class TestResidualRearDurations:
    """Task 2: physical residual-rear attribution with positional guard."""

    TRAIN_LEN = 200.0
    BLOCK_END = {"BLK_01": 1000.0}

    def test_standstill_with_tail_inside_block_contributes(self):
        # Front exits at t=100 (front at 1000 m); standstill 110..150 with front held
        # at 900 m -> tail at 700 m still inside block (700 < 1000). Rear clears at 130.
        rec = SimpleNamespace(resource_id="BLK_01", front_exit_s=100.0, rear_clearance_s=130.0)
        raw = _samples([95.0, 100.0, 110.0, 160.0], [900.0, 1000.0, 900.0, 900.0])
        out = _compute_residual_rear_durations(
            [rec], [(110.0, 150.0)], raw, self.TRAIN_LEN, self.BLOCK_END
        )
        assert out.get("BLK_01") == pytest.approx(20.0)  # min(130,150) - max(100,110)

    def test_standstill_after_tail_cleared_contributes_zero(self):
        # Front is at 1300 m at standstill start -> tail at 1100 m >= block end 1000:
        # tail already out of the block; dwell must NOT be credited as residual rear.
        rec = SimpleNamespace(resource_id="BLK_01", front_exit_s=100.0, rear_clearance_s=300.0)
        raw = _samples([95.0, 100.0, 250.0, 400.0], [900.0, 1000.0, 1300.0, 1300.0])
        out = _compute_residual_rear_durations(
            [rec], [(260.0, 290.0)], raw, self.TRAIN_LEN, self.BLOCK_END
        )
        assert "BLK_01" not in out

    def test_no_clearance_window_no_contribution(self):
        # rear_clearance_s <= front_exit_s -> block skipped entirely.
        rec = SimpleNamespace(resource_id="BLK_01", front_exit_s=100.0, rear_clearance_s=99.0)
        raw = _samples([95.0, 110.0], [900.0, 900.0])
        out = _compute_residual_rear_durations(
            [rec], [(100.0, 200.0)], raw, self.TRAIN_LEN, self.BLOCK_END
        )
        assert out == {}

    def test_missing_block_end_geometry_guard_skipped_windowed_overlap_still_applies(self):
        # Without block-end geometry the positional guard cannot run; the pure temporal
        # windowed overlap remains the criterion.
        rec = SimpleNamespace(resource_id="BLK_01", front_exit_s=100.0, rear_clearance_s=150.0)
        raw = _samples([95.0, 120.0], [900.0, 900.0])
        out = _compute_residual_rear_durations(
            [rec], [(110.0, 160.0)], raw, self.TRAIN_LEN, {}
        )
        assert out.get("BLK_01") == pytest.approx(40.0)  # min(150,160) - max(100,110)

    def test_tiny_residual_below_roundoff_threshold_excluded(self):
        rec = SimpleNamespace(resource_id="BLK_01", front_exit_s=100.0, rear_clearance_s=100.04)
        raw = _samples([95.0, 110.0], [900.0, 900.0])
        out = _compute_residual_rear_durations(
            [rec], [(100.0, 200.0)], raw, self.TRAIN_LEN, self.BLOCK_END
        )
        assert "BLK_01" not in out


class TestBlockLengthMismatch:
    """Task 7: ERR_BLOCK_LENGTH_MISMATCH — unconditional on chainage source, feature-flagged."""

    @staticmethod
    def _baseline_package():
        project, report, _ = FileManager.load_example_project("03_station_platform")
        assert report.is_simulation_ready
        pkg, _doc = SimulationRunner.run_simulation_pipeline(
            project, running_direction=RunningDirection.FORWARD, simulation_mode="Full Integrated Suite"
        )
        return project, pkg

    @staticmethod
    def _mutate_first(pkg, **changes):
        provenance = pkg.metadata["provenance_records"]
        assert provenance, "expected provenance records in metadata"
        pkg.metadata["provenance_records"] = [dataclasses.replace(provenance[0], **changes)] + provenance[1:]

    _ON = staticmethod(lambda: ReportConfig(validate_block_geometry=True))

    def test_flag_ships_off_in_v1111(self):
        assert VALIDATE_BLOCK_GEOMETRY_DEFAULT is False
        assert ReportConfig().validate_block_geometry is False

    def test_flag_off_does_not_audit(self):
        project, pkg = self._baseline_package()
        self._mutate_first(pkg, entry_signal_chainage_km=10.0, exit_signal_chainage_km=10.5, resource_length_m=1000.0)
        doc = ReportAssembler.assemble_report(pkg, project=project)  # default config: flag OFF
        assert doc is not None

    def test_flag_on_explicit_long_mismatch_raises(self):
        project, pkg = self._baseline_package()
        self._mutate_first(
            pkg,
            entry_signal_chainage_source="EXPLICIT_INPUT_CHAINAGE",
            exit_signal_chainage_source="EXPLICIT_INPUT_CHAINAGE",
            entry_signal_chainage_km=10.0,
            exit_signal_chainage_km=10.5,  # 500 m span vs 1000 m length
            resource_length_m=1000.0,
        )
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, config=self._ON(), project=project)
        assert excinfo.value.error_code == "ERR_BLOCK_LENGTH_MISMATCH"

    def test_flag_on_derived_mismatch_raises(self):
        # Derived (link-geometry) chainages are audited exactly like explicit ones.
        project, pkg = self._baseline_package()
        self._mutate_first(
            pkg,
            entry_signal_chainage_source="DERIVED_ALIGNMENT",
            exit_signal_chainage_source="DERIVED_ALIGNMENT",
            entry_signal_chainage_km=0.0,
            exit_signal_chainage_km=0.001,  # 1 m span vs 650 m block
        )
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, config=self._ON(), project=project)
        assert excinfo.value.error_code == "ERR_BLOCK_LENGTH_MISMATCH"

    def test_flag_on_short_span_raises(self):
        project, pkg = self._baseline_package()
        self._mutate_first(pkg, entry_signal_chainage_km=5.0, exit_signal_chainage_km=5.2, resource_length_m=1000.0)
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, config=self._ON(), project=project)
        assert excinfo.value.error_code == "ERR_BLOCK_LENGTH_MISMATCH"

    def test_flag_on_tolerance_boundary(self):
        project, pkg = self._baseline_package()
        self._mutate_first(pkg, entry_signal_chainage_km=5.0, exit_signal_chainage_km=5.9991, resource_length_m=1000.0)
        assert ReportAssembler.assemble_report(pkg, config=self._ON(), project=project) is not None  # 0.9 m
        self._mutate_first(pkg, entry_signal_chainage_km=5.0, exit_signal_chainage_km=5.9985, resource_length_m=1000.0)
        with pytest.raises(ReportingError):
            ReportAssembler.assemble_report(pkg, config=self._ON(), project=project)  # 1.5 m

    def test_flag_on_consistent_example_passes(self):
        project, pkg = self._baseline_package()
        assert ReportAssembler.assemble_report(pkg, config=self._ON(), project=project) is not None

    @pytest.mark.parametrize(
        "example, block_id",
        [("01_single_track", "BLK_01"), ("04_tunnel_tvs", "BLK_T01"), ("07_hsr_140km", "BLK_UP_001")],
    )
    def test_flag_on_known_defective_examples_raise(self, example, block_id):
        # Documents the example-data defects corrected in v1.11.2 (PR #64). When that data
        # lands and the flag default flips to True, these cases must be inverted to PASS.
        project, _r, _ = FileManager.load_example_project(example)
        pkg, _doc = SimulationRunner.run_simulation_pipeline(
            project, running_direction=RunningDirection.FORWARD, simulation_mode="Full Integrated Suite"
        )
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, config=self._ON(), project=project)
        assert excinfo.value.error_code == "ERR_BLOCK_LENGTH_MISMATCH"
        assert f"'{block_id}'" in str(excinfo.value)


class TestJourneyTimePublication:
    """Q2: canonical journey duration in package metadata."""

    def test_hsr_forward_full_pf_journey_time_in_range(self):
        project, _r, _ = FileManager.load_example_project("07_hsr_140km")
        pkg, _doc = SimulationRunner.run_simulation_pipeline(
            project,
            running_direction=RunningDirection.FORWARD,
            simulation_mode="Full Integrated Suite",
            performance_factor=1.0,
        )
        jt = pkg.metadata["journey_time_s"]
        assert 2900.0 <= jt <= 3100.0, jt
        assert jt == pytest.approx(pkg.trajectories["TRN_LEADER"].journey_time_s)


class TestReversedLinkAlignment:
    """Q4: blocks on links running against increasing chainage (05 DN line)."""

    @pytest.fixture(scope="class")
    def pkg05(self):
        project, _r, _ = FileManager.load_example_project("05_comprehensive_line")
        pkg, _doc = SimulationRunner.run_simulation_pipeline(
            project, running_direction=RunningDirection.FORWARD, simulation_mode="Full Integrated Suite"
        )
        return pkg

    def test_blk_dn_03_signal_aligned_bounds(self, pkg05):
        prov = {r.resource_id: r for r in pkg05.metadata["provenance_records"]}
        r = prov["BLK_DN_03"]  # LNK_13: ND_09 @ 22.0 km -> ND_08 @ 17.0 km
        assert (r.physical_chainage_km, r.physical_end_chainage_km) == (17.0, 22.0)
        assert r.entry_signal_chainage_km == pytest.approx(21.95)
        assert r.exit_signal_chainage_km == pytest.approx(16.95)
        iv = next(i for i in pkg05.blocking_intervals if i.resource_id == "BLK_DN_03")
        assert (iv.alignment_start_m, iv.alignment_end_m) == (17000.0, 22000.0)

    def test_all_dn_blocks_mirror_up_line(self, pkg05):
        prov = {r.resource_id: r for r in pkg05.metadata["provenance_records"]}
        expected = {
            "BLK_DN_01": (24.0, 25.0), "BLK_DN_02": (22.0, 24.0), "BLK_DN_03": (17.0, 22.0),
            "BLK_DN_04": (14.5, 17.0), "BLK_DN_05": (10.0, 14.5), "BLK_DN_06": (4.0, 10.0),
            "BLK_DN_07": (0.0, 4.0),
        }
        for bid, bounds in expected.items():
            assert (prov[bid].physical_chainage_km, prov[bid].physical_end_chainage_km) == bounds, bid
        for bid in ("BLK_DN_01", "BLK_DN_02", "BLK_DN_03", "BLK_DN_04", "BLK_DN_05", "BLK_DN_06"):
            # Running against chainage: entry signal at the HIGH end of the block.
            assert prov[bid].entry_signal_chainage_km > prov[bid].exit_signal_chainage_km, bid

    def test_forward_links_unchanged(self, pkg05):
        prov = {r.resource_id: r for r in pkg05.metadata["provenance_records"]}
        assert (prov["BLK_UP_03"].physical_chainage_km, prov["BLK_UP_03"].physical_end_chainage_km) == (4.0, 8.0)
        assert prov["BLK_UP_03"].entry_signal_chainage_km == pytest.approx(4.05)
        assert (prov["BLK_SD_01"].physical_chainage_km, prov["BLK_SD_01"].physical_end_chainage_km) == (8.0, 10.0)

    @pytest.mark.parametrize("direction", [RunningDirection.FORWARD, RunningDirection.REVERSE])
    def test_section4_conflict_chainage_zero_is_not_replaced_by_route_location(self, direction):
        # BLK_DN_07 legitimately starts at alignment 0.0 km; Section 4 must not substitute the
        # route-relative location (previously 46.0 km FWD / 2.0 km REV on a 25 km network).
        from headway.reporting.report_models import ReportSectionId

        project, _r, _ = FileManager.load_example_project("05_comprehensive_line")
        _pkg, doc = SimulationRunner.run_simulation_pipeline(
            project, running_direction=direction, simulation_mode="Full Integrated Suite"
        )
        tables = [
            t for s in doc.sections.values() for t in (s.tables or [])
            if t.raw_dataframe is not None and "Alignment Chainage (km)" in t.raw_dataframe.columns
            and "Leader Resource" in t.raw_dataframe.columns
        ]
        assert tables, "expected the Section 4 conflict table"
        df = tables[0].raw_dataframe
        assert df["Alignment Chainage (km)"].between(0.0, 25.0).all(), df["Alignment Chainage (km)"].tolist()
        dn07 = df[df["Leader Resource"] == "BLK_DN_07"]
        if len(dn07):
            assert (dn07["Alignment Chainage (km)"] == 0.0).all()
