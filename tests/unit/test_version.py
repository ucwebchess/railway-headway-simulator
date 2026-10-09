"""Unit tests for version specification and metadata."""

import pytest
from headway import __version__ as pkg_version
from headway.core.version import (
    APP_NAME,
    VERSION_INFO,
    __version__,
    get_build_info,
    get_version,
)


@pytest.mark.unit
def test_authoritative_version_value():
    """Verify that version matches the required P00 baseline string."""
    assert __version__ == "0.1.0-dev"
    assert pkg_version == "0.1.0-dev"
    assert get_version() == "0.1.0-dev"


@pytest.mark.unit
def test_version_info_tuple():
    """Verify VERSION_INFO tuple structure."""
    assert isinstance(VERSION_INFO, tuple)
    assert len(VERSION_INFO) == 4
    assert VERSION_INFO[:3] == (0, 1, 0)
    assert VERSION_INFO[3] == "dev"


@pytest.mark.unit
def test_get_build_info():
    """Verify metadata returned by get_build_info()."""
    info = get_build_info()
    assert isinstance(info, dict)
    assert info["app_name"] == APP_NAME
    assert info["version"] == "0.1.0-dev"
    assert info["version_info"] == (0, 1, 0, "dev")
    assert "P00" in info["phase"]
