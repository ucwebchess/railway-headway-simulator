"""Unit tests for the v1.11.1 hotfix (Phase 4c sensitivity & geometry hotfix).

Covers:
- Task 2: residual-rear attribution helper `_compute_residual_rear_durations`
  (windowed overlap + positional guard at block exit boundary).
- Task 7: ERR_BLOCK_LENGTH_MISMATCH loud failure when a block's length disagrees
  with its entry/exit signal chainage span by more than 1.0 m — for ANY chainage
  source — gated by `ReportConfig.validate_block_geometry` in v1.11.1 (shipped OFF); the
  audit is mandatory since v1.11.2 and the flag was removed.
- Q2: canonical `metadata["journey_time_s"]` published from the leader trajectory.
- Q4: Task 5 alignment of blocks on links running against increasing chainage.
"""

import dataclasses
from types import SimpleNamespace

import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_assembly import ReportAssembler, ReportingError
from headway.reporting.report_config import ReportConfig
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner, _compute_residual_rear_durations
from tests.block_geometry_expectations import (
    comprehensive_line_with_explicit_turnaround_exits,
    load_and_assert_pipeline_raises,
)
from tests.corrected_variants import load_corrected_variant


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

    _ON = staticmethod(lambda: ReportConfig())  # v1.11.2: the audit is mandatory

    def test_audit_is_mandatory_flag_removed_in_v1112(self):
        """v1.11.2 (literal strict): the v1.11.1 opt-in flag is gone — no config can disable
        the report-level audit, and the old keyword fails loudly instead of being ignored."""
        import headway.reporting.report_config as rc

        assert "validate_block_geometry" not in ReportConfig.__dataclass_fields__
        assert not hasattr(rc, "VALIDATE_BLOCK_GEOMETRY_DEFAULT")
        with pytest.raises(TypeError):
            ReportConfig(validate_block_geometry=False)

    def test_default_config_audits_and_raises(self):
        """Default config (no flag passed) raises on a mismatching package."""
        project, pkg = self._baseline_package()
        self._mutate_first(pkg, entry_signal_chainage_km=10.0, exit_signal_chainage_km=10.5, resource_length_m=1000.0)
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, project=project)
        assert excinfo.value.error_code == "ERR_BLOCK_LENGTH_MISMATCH"

    def test_stray_opt_out_attribute_raises_named_error(self):
        """Setting the removed attribute after construction must not silently disable (or be
        silently ignored by) the audit."""
        project, pkg = self._baseline_package()
        cfg = ReportConfig()
        cfg.validate_block_geometry = False
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, config=cfg, project=project)
        assert excinfo.value.error_code == "ERR_REPORT_GEOMETRY_AUDIT_MANDATORY"

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
        """Known example-data block-length defects are caught.

        v1.11.2 (literal strict): these defects are now caught BEFORE simulation by the
        always-on runner validation (ERR_BLOCK_GEOMETRY_MISMATCH / ERR_BLOCK_NO_EXIT_SIGNAL),
        so the report-level flag is never reached for these examples. The test asserts the
        documented error (tests/block_geometry_expectations.py) in FORWARD and REVERSE and
        that the same defective block is reported as a geometry mismatch.
        """
        from headway.ui.file_manager import FileManager as _FM
        from headway.signalling.block_geometry_validation import validate_block_geometry

        load_and_assert_pipeline_raises(example)
        project, _r, _ = _FM.load_example_project(example)
        mismatched = {f.block_id for f in validate_block_geometry(project).findings
                      if f.code == "ERR_BLOCK_GEOMETRY_MISMATCH"}
        assert block_id in mismatched


class TestJourneyTimePublication:
    """Q2: canonical journey duration in package metadata."""

    def test_hsr_forward_full_pf_journey_time_in_range(self):
        # v1.11.2: runs on the corrected in-memory variant (tests/corrected_variants.py); the shipped example raises a named ERR_* (tests/unit/test_v1112_bidirectional_integrity.py).
        project, _r, _ = load_corrected_variant("07_hsr_140km")
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

    def test_blk_dn_03_signal_aligned_bounds(self):
        """05 BLK_DN_03 (reversed link LNK_13): bounds and signal chainages align to the network.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_all_dn_blocks_mirror_up_line(self):
        """05 DN-line blocks mirror the UP line, entry signal at the high-chainage end.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    def test_forward_links_unchanged(self):
        """05 forward-running links (BLK_UP_03, BLK_SD_01) keep their stationing.

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line")

    @pytest.mark.parametrize("direction", [RunningDirection.FORWARD, RunningDirection.REVERSE])
    def test_section4_conflict_chainage_zero_is_not_replaced_by_route_location(self, direction):
        """Section 4 must not replace a legitimate 0.0 km alignment chainage (05 BLK_DN_07).

        v1.11.2 (literal strict): 05_comprehensive_line fails pre-simulation block-geometry
        validation, so the original scenario cannot run on the unmodified shipped example.
        The test now asserts the documented error (tests/block_geometry_expectations.py)
        in FORWARD and REVERSE.
        """
        load_and_assert_pipeline_raises("05_comprehensive_line", directions=(direction,))


_VARIANT_RUNS = {}


def _turnaround_variant_run(direction):
    """Run (and cache) the 05 turnaround variant: shipped 05 with ONLY the two
    turnaround exit signals made explicit (BLK_UP_10 -> SIG_DN_01, BLK_DN_07 -> SIG_UP_01)."""
    if direction not in _VARIANT_RUNS:
        _VARIANT_RUNS[direction] = SimulationRunner.run_simulation_pipeline(
            comprehensive_line_with_explicit_turnaround_exits(),
            running_direction=direction,
            simulation_mode="Full Integrated Suite",
        )
    return _VARIANT_RUNS[direction]


@pytest.mark.parametrize("direction", [RunningDirection.FORWARD, RunningDirection.REVERSE])
class TestReversedLinkAlignmentTurnaroundVariant:
    """v1.11.2: the Q4 reversed-link assertions of ``TestReversedLinkAlignment``, unchanged,
    executed on the 05 turnaround variant in BOTH directions.

    Shipped 05 now fails pre-simulation validation (ERR_BLOCK_NO_EXIT_SIGNAL, asserted
    above). The variant differs only in the two turnaround exit signals, none of which feed
    the values checked here, so the reversed-link coverage is preserved without modifying
    example data.
    """

    def test_blk_dn_03_signal_aligned_bounds(self, direction):
        pkg05, _doc = _turnaround_variant_run(direction)
        prov = {r.resource_id: r for r in pkg05.metadata["provenance_records"]}
        r = prov["BLK_DN_03"]  # LNK_13: ND_09 @ 22.0 km -> ND_08 @ 17.0 km
        assert (r.physical_chainage_km, r.physical_end_chainage_km) == (17.0, 22.0)
        assert r.entry_signal_chainage_km == pytest.approx(21.95)
        assert r.exit_signal_chainage_km == pytest.approx(16.95)
        iv = next(i for i in pkg05.blocking_intervals if i.resource_id == "BLK_DN_03")
        assert (iv.alignment_start_m, iv.alignment_end_m) == (17000.0, 22000.0)

    def test_all_dn_blocks_mirror_up_line(self, direction):
        pkg05, _doc = _turnaround_variant_run(direction)
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

    def test_forward_links_unchanged(self, direction):
        pkg05, _doc = _turnaround_variant_run(direction)
        prov = {r.resource_id: r for r in pkg05.metadata["provenance_records"]}
        assert (prov["BLK_UP_03"].physical_chainage_km, prov["BLK_UP_03"].physical_end_chainage_km) == (4.0, 8.0)
        assert prov["BLK_UP_03"].entry_signal_chainage_km == pytest.approx(4.05)
        assert (prov["BLK_SD_01"].physical_chainage_km, prov["BLK_SD_01"].physical_end_chainage_km) == (8.0, 10.0)

    def test_section4_conflict_chainage_zero_is_not_replaced_by_route_location(self, direction):
        # BLK_DN_07 legitimately starts at alignment 0.0 km; Section 4 must not substitute the
        # route-relative location (previously 46.0 km FWD / 2.0 km REV on a 25 km network).
        _pkg, doc = _turnaround_variant_run(direction)
        tables = [
            t for s in doc.sections.values() for t in (s.tables or [])
            if t.raw_dataframe is not None and "Alignment Chainage (km)" in t.raw_dataframe.columns
            and "Leader Resource" in t.raw_dataframe.columns
        ]
        assert tables, "expected the Section 4 conflict table"
        df = tables[0].raw_dataframe
        assert df["Alignment Chainage (km)"].between(0.0, 25.0).all(), df["Alignment Chainage (km)"].tolist()
        dn07 = df[df["Leader Resource"] == "BLK_DN_07"]
        # Strengthened vs. v1.11.1 (which tolerated absence): the variant must surface BLK_DN_07.
        assert len(dn07), "expected BLK_DN_07 as a Section 4 leader resource"
        assert (dn07["Alignment Chainage (km)"] == 0.0).all()
