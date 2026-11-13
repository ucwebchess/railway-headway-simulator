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
    """Verify that version matches the required 1.15.2 release string."""
    assert __version__ == "1.15.2"
    assert pkg_version == "1.15.2"
    assert get_version() == "1.15.2"


@pytest.mark.unit
def test_version_info_tuple():
    """VERSION_INFO is derived from __version__ (v1.15.2; was pinned to the stale (1, 11, 3))."""
    assert isinstance(VERSION_INFO, tuple)
    assert VERSION_INFO == tuple(int(p) for p in __version__.split("."))
    assert VERSION_INFO == (1, 15, 2)


@pytest.mark.unit
def test_get_build_info():
    """Verify metadata returned by get_build_info()."""
    info = get_build_info()
    assert isinstance(info, dict)
    assert info["app_name"] == APP_NAME
    assert info["version"] == "1.15.2"
    assert info["version_info"] == VERSION_INFO == tuple(int(p) for p in __version__.split("."))
    assert info["phase"] == f"Release {__version__}"
    assert info["status"] == "Released"
