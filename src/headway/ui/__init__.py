"""Headway UI package for Railway Headway Simulator.

Milestone P15 — UI Application & Integration.
"""

from headway.ui.app import create_app, launch_app
from headway.ui.background_executor import BackgroundExecutor, default_executor
from headway.ui.direction_selector import DirectionSelector
from headway.ui.error_handling import EngineeringError, create_error_html, create_success_html, format_exception_for_ui
from headway.ui.file_manager import ProjectFileManager
from headway.ui.progress import ProgressToken, ProgressTracker
from headway.ui.simulation_runner import SimulationJobConfig, SimulationRunner
from headway.ui.state import AppState, session_state

__all__ = [
    "create_app",
    "launch_app",
    "AppState",
    "session_state",
    "DirectionSelector",
    "EngineeringError",
    "create_error_html",
    "create_success_html",
    "format_exception_for_ui",
    "ProjectFileManager",
    "ProgressToken",
    "ProgressTracker",
    "BackgroundExecutor",
    "default_executor",
    "SimulationJobConfig",
    "SimulationRunner",
]
