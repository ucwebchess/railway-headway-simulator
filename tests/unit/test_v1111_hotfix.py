"""Unit tests for the v1.11.1 hotfix (Phase 4c sensitivity & geometry hotfix).

Covers:
- Task 2: residual-rear attribution helper `_compute_residual_rear_durations`
  (windowed overlap + positional guard at block exit boundary).
- Task 7: ERR_BLOCK_LENGTH_MISMATCH loud failure when a block's length disagrees
  with the explicit entry/exit signal chainage span by more than 1.0 m.
"""

import dataclasses
from types import SimpleNamespace

import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.report_assembly import ReportAssembler, ReportingError
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
    """Task 7: ERR_BLOCK_LENGTH_MISMATCH loud failure in report assembly."""

    @staticmethod
    def _baseline_package():
        project, report, _ = FileManager.load_example_project("03_station_platform")
        assert report.is_simulation_ready
        pkg, _doc = SimulationRunner.run_simulation_pipeline(
            project, running_direction=RunningDirection.FORWARD, simulation_mode="Full Integrated Suite"
        )
        return project, pkg

    def test_mutated_explicit_signal_span_raises(self):
        project, pkg = self._baseline_package()
        provenance = pkg.metadata["provenance_records"]
        assert provenance, "expected provenance records in metadata"
        victim = dataclasses.replace(
            provenance[0],
            entry_signal_chainage_source="EXPLICIT_INPUT_CHAINAGE",
            exit_signal_chainage_source="EXPLICIT_INPUT_CHAINAGE",
            entry_signal_chainage_km=10.0,
            exit_signal_chainage_km=10.5,  # 500 m span
            resource_length_m=1000.0,      # genuine 500 m contradiction
        )
        pkg.metadata["provenance_records"] = [victim] + provenance[1:]
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, project=project)
        assert "ERR_BLOCK_LENGTH_MISMATCH" in str(excinfo.value)

    def test_legitimate_derived_geometry_does_not_raise(self):
        project, pkg = self._baseline_package()
        # Unmodified provenance must assemble cleanly (no false positive).
        doc = ReportAssembler.assemble_report(pkg, project=project)
        assert doc is not None

    def test_derived_signal_chainage_skipped_even_if_inconsistent(self):
        # Derived (link-geometry) signal chainages are NOT audited — synthetic datasets may
        # place signals with legitimate advances/insets relative to interval coverage.
        project, pkg = self._baseline_package()
        provenance = pkg.metadata["provenance_records"]
        victim = dataclasses.replace(
            provenance[0],
            entry_signal_chainage_source="DERIVED_ALIGNMENT",
            exit_signal_chainage_source="DERIVED_ALIGNMENT",
            entry_signal_chainage_km=0.0,
            exit_signal_chainage_km=0.001,  # 1 m span, far from any block length
        )
        pkg.metadata["provenance_records"] = [victim] + provenance[1:]
        doc = ReportAssembler.assemble_report(pkg, project=project)
        assert doc is not None

    def test_short_span_only(self):
        # A span SHORTER than the block raises (intervals poke past boundary signals).
        project, pkg = self._baseline_package()
        provenance = pkg.metadata["provenance_records"]
        victim = dataclasses.replace(
            provenance[0],
            entry_signal_chainage_source="EXPLICIT_INPUT_CHAINAGE",
            exit_signal_chainage_source="EXPLICIT_INPUT_CHAINAGE",
            entry_signal_chainage_km=5.0,
            exit_signal_chainage_km=5.2,  # 200 m span vs 1000 m length
            resource_length_m=1000.0,
        )
        pkg.metadata["provenance_records"] = [victim] + provenance[1:]
        with pytest.raises(ReportingError) as excinfo:
            ReportAssembler.assemble_report(pkg, project=project)
        assert "ERR_BLOCK_LENGTH_MISMATCH" in str(excinfo.value)
