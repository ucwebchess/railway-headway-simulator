"""Pytest shared test fixtures for Railway Headway & Capacity Simulator."""

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
