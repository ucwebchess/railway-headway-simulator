"""Version definitions for Railway Headway & Capacity Simulator.

This module provides the single authoritative source of truth for the application version.
"""

from typing import Any, Dict, Tuple

__version__: str = "1.9.3"

VERSION_INFO: Tuple[int, int, int] = (1, 9, 3)

APP_NAME: str = "Railway Headway & Capacity Simulator"
APP_DESCRIPTION: str = (
    "Microscopic railway headway, signalling blocking-time, TVS constraint, "
    "and line capacity simulation application."
)


def get_version() -> str:
    """Return the authoritative application version string."""
    return __version__


def get_build_info() -> Dict[str, Any]:
    """Return structured metadata regarding the current application version."""
    return {
        "app_name": APP_NAME,
        "version": __version__,
        "version_info": VERSION_INFO,
        "phase": "Release 1.9.3",
        "status": "Released",
    }
