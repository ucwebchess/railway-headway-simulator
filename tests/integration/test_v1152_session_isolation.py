"""v1.15.2: guard against the session_state test-isolation leak (docs/issues/test_isolation_leak.md).

``headway.ui.state.session_state`` is a process-wide singleton, and ``ReportAssembler`` falls back to
``session_state.current_project`` when a result package carries no bound project. Before v1.15.2 a
project opened by one test stayed open for every later test. The autouse fixture
``_isolated_session_state`` in ``tests/conftest.py`` now restores a fresh session before and after
every test.

``test_no_session_state_leak`` runs the 22 tests of ``test_report_integration.py`` that read
``session_state.current_project`` (found by instrumenting every read during the v1.15.2 pre-flight)
in a separate pytest process, in two seeded random orders, then once with a foreign project (example
01) open at the start of every test. All must pass every time.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILE = "tests/integration/test_report_integration.py"

# The 22 tests in test_report_integration.py that read session_state.current_project: 20 assemble a
# report from a package without a bound project; the two session-fallback tests set it on purpose
# (monkeypatch).
_GEOMETRY = "TestReportLevelBlockGeometryAuditV1112"
SESSION_READERS = [
    f"{FILE}::TestReportIntegration::test_e2e_full_reporting_pipeline_forward",
    f"{FILE}::TestReportIntegration::test_e2e_reverse_direction_pipeline",
    f"{FILE}::TestReportIntegration::test_e2e_scenario_comparison_integrity",
    f"{FILE}::TestReportIntegration::test_reporting_blocking_intervals_decomposition_and_geometry_synthetic",
    f"{FILE}::TestReportIntegration::test_reporting_missing_blocking_intervals_raises_loud_error",
    *(
        f"{FILE}::{_GEOMETRY}::{name}[{d}]"
        for name in (
            "test_valid_synthetic_package_assembles",
            "test_length_mismatch_raises",
            "test_tolerance_is_one_metre",
            "test_missing_exit_boundary_raises",
            "test_missing_entry_signal_uses_recorded_entry_end",
            "test_no_entry_information_uses_block_end_opposite_the_exit",
            "test_turnaround_block_is_checked_against_path_span",
            "test_session_fallback_project_is_not_audited_but_bound_project_is",
        )
        for d in ("FORWARD", "REVERSE")
    ),
    f"{FILE}::TestSignallingParameterReconciliationV1113::test_package_without_signalling_timing_has_no_footnotes",
]
SEEDS = (1152, 2026)


def _run(node_ids, *extra):
    env = dict(os.environ, PYTHONHASHSEED="0")
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "addopts=", "-v", "-W", "ignore",
           *extra, *node_ids]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
    executed = re.findall(r"^(tests/\S+::\S+) (?:PASSED|FAILED|ERROR)", proc.stdout, flags=re.M)
    return proc, executed


def test_session_state_is_clean_at_test_start():
    """The conftest fixture is active: nothing an earlier test opened is visible here."""
    from headway.ui.state import AppState, session_state

    fresh = AppState()
    assert session_state.current_project is None
    assert session_state.latest_result_package is None
    assert session_state.latest_report_doc is None
    assert session_state.simulation_packages == {}
    assert session_state.report_config is None
    assert (session_state.project_id, session_state.dt_s) == (fresh.project_id, fresh.dt_s)


def test_restore_fresh_session_state_clears_everything():
    from headway.ui.state import session_state
    from tests.conftest import _restore_fresh_session_state

    ok, msg = session_state.load_example("01_single_track")
    assert ok, msg
    session_state.dt_s = 0.25
    session_state.report_config = object()
    assert session_state.current_project is not None
    _restore_fresh_session_state()
    assert session_state.current_project is None
    assert session_state.project_id == "NONE"
    assert session_state.dt_s == 1.0
    assert session_state.report_config is None


def test_no_session_state_leak():
    assert len(SESSION_READERS) == 22
    runs = []
    for seed in SEEDS:
        order = list(SESSION_READERS)
        random.Random(seed).shuffle(order)
        runs.append((f"random order, seed {seed}", order, ()))
    runs.append(("foreign project open (example 01)", list(SESSION_READERS), ("-p", "tests.session_pollution_plugin")))
    for label, order, extra in runs:
        proc, executed = _run(order, *extra)
        tail = proc.stdout[-3000:] + proc.stderr[-2000:]
        assert proc.returncode == 0, f"{label}: pytest exit {proc.returncode}\n{tail}"
        assert re.search(r"\b22 passed\b", proc.stdout), f"{label}\n{tail}"
        assert executed == order, f"{label}: execution order differs from the requested order"
