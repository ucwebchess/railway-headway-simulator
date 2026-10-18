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
    """Verify that version matches the required 1.5.0 release string."""
    assert __version__ == "1.5.0"
    assert pkg_version == "1.5.0"
    assert get_version() == "1.5.0"


@pytest.mark.unit
def test_version_info_tuple():
    """Verify VERSION_INFO tuple structure."""
    assert isinstance(VERSION_INFO, tuple)
    assert len(VERSION_INFO) == 3
    assert VERSION_INFO == (1, 5, 0)


@pytest.mark.unit
def test_get_build_info():
    """Verify metadata returned by get_build_info()."""
    info = get_build_info()
    assert isinstance(info, dict)
    assert info["app_name"] == APP_NAME
    assert info["version"] == "1.5.0"
    assert info["version_info"] == (1, 5, 0)
    assert "Release" in info["phase"]
    assert info["status"] == "Released"
