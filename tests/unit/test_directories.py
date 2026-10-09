"""Unit tests for runtime directory initialization."""

from pathlib import Path
import pytest

from headway.core.configuration import DirectoryConfig


@pytest.mark.unit
def test_directory_creation(temp_storage_dir: Path):
    """Verify DirectoryConfig correctly creates all managed storage paths."""
    dirs = DirectoryConfig(base_dir=temp_storage_dir)
    dirs.ensure_directories_exist()

    assert dirs.base_dir.is_dir()
    assert dirs.projects_dir.is_dir()
    assert dirs.temp_dir.is_dir()
    assert dirs.results_dir.is_dir()
    assert dirs.reports_dir.is_dir()
    assert dirs.logs_dir.is_dir()
