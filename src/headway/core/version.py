"""Version definitions for Railway Headway & Capacity Simulator.

This module provides the single authoritative source of truth for the application version.
"""

from typing import Any, Dict, Tuple

__version__: str = "0.1.0-dev"

VERSION_INFO: Tuple[int, int, int, str] = (0, 1, 0, "dev")

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
        "phase": "P00 — Project Foundation",
        "status": "Development",
    }
