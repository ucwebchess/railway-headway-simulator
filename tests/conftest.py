"""Pytest shared test fixtures for Railway Headway & Capacity Simulator."""

import dataclasses
import tempfile
from pathlib import Path
from typing import Generator
import pytest

from headway.core.configuration import AppConfig, DirectoryConfig, EnvironmentType, GradioServerConfig


@pytest.fixture
def temp_storage_dir() -> Generator[Path, None, None]:
    """Provide an isolated temporary directory for test file operations."""
    with tempfile.TemporaryDirectory(prefix="headway_test_storage_") as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def test_config(temp_storage_dir: Path) -> AppConfig:
    """Provide a validated test AppConfig pointing to an isolated temporary directory."""
    dirs = DirectoryConfig(
        base_dir=temp_storage_dir,
        projects_dir=temp_storage_dir / "projects",
        temp_dir=temp_storage_dir / "temp",
        results_dir=temp_storage_dir / "results",
        reports_dir=temp_storage_dir / "reports",
        logs_dir=temp_storage_dir / "logs",
    )
    server_cfg = GradioServerConfig(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        debug=False,
    )
    return AppConfig(
        environment=EnvironmentType.TESTING,
        log_level="DEBUG",
        dev_mode=True,
        directories=dirs,
        server=server_cfg,
    )


def _restore_fresh_session_state() -> None:
    """Put every field of the process-wide ``session_state`` singleton back to a fresh ``AppState()``.

    In place, because tests and production code hold references to the singleton. Wider than
    ``AppState.reset()``, which deliberately keeps user settings (report config, numerical parameters,
    logs) across project loads.
    """
    from headway.ui.state import AppState, session_state

    fresh = AppState()
    for f in dataclasses.fields(AppState):
        setattr(session_state, f.name, getattr(fresh, f.name))


@pytest.fixture(autouse=True)
def _isolated_session_state() -> Generator[None, None, None]:
    """v1.15.2 (docs/issues/test_isolation_leak.md): every test starts and ends with a clean session.

    ``ReportAssembler`` falls back to ``session_state.current_project`` when a result package has no
    bound project (deliberate UI behaviour). Without this fixture a project opened by one test leaked
    into every later test, so report contents depended on test order. A test that needs an open
    project must open it itself (``tests/integration/test_v1152_session_isolation.py`` guards this).
    """
    _restore_fresh_session_state()
    yield
    _restore_fresh_session_state()

