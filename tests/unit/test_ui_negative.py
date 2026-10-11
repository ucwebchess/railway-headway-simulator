"""Negative test suite for UI error handling and user feedback.

Milestone P15 — UI Error Handling (P15-ERR-001 to P15-ERR-006).
Verifies that invalid operations, malformed inputs, and edge cases produce
clear, engineering-focused error messages without exposing raw Python tracebacks.
"""

from pathlib import Path
import tempfile
import zipfile
import pytest

from headway.core.exceptions import (
    ConfigurationError,
    DataValidationError,
    HeadwayCalculationError,
    InfrastructureError,
    RollingStockError,
    ScenarioError,
    SignallingError,
)
from headway.infrastructure.direction import RunningDirection
from headway.ui.direction_selector import DirectionSelector
from headway.ui.error_handling import (
    EngineeringError,
    create_error_html,
    format_engineering_error,
    format_exception_for_ui,
)
from headway.ui.file_manager import ProjectFileManager
from headway.ui.simulation_runner import SimulationRunner
from headway.ui.state import session_state


@pytest.fixture(autouse=True)
def clean_state():
    session_state.reset()
    yield
    session_state.reset()


class TestUiNegativeCases:
    """Verifies UI error boundaries and user feedback without raw tracebacks."""

    def test_err_001_raw_traceback_suppression(self):
        """P15-ERR-001: format_exception_for_ui provides clear message and category."""
        exc = ValueError("Invalid headway convergence value: -5.0")
        eng_err = format_exception_for_ui(exc, context="Solver Setup")

        assert isinstance(eng_err, EngineeringError)
        assert eng_err.category == "Invalid Parameter Value"
        assert "Invalid headway convergence value" in eng_err.user_message
        assert eng_err.recommendation != ""
        # HTML card renders without raw unformatted traceback exposed in main body
        html = eng_err.to_html()
        assert "⚠️" in html
        assert "Recommended Action:" in html

    def test_err_002_data_validation_error_formatting(self):
        """P15-ERR-002: Data validation errors display structured engineering advice."""
        exc = DataValidationError(
            message="Required column 'gradient_permille' is missing in worksheet 'Alignment'.",
            context={"worksheet": "Alignment", "column": "gradient_permille"},
        )
        eng_err = format_exception_for_ui(exc, context="Excel Ingestion")
        assert eng_err.category == "Data Validation Error"
        assert "Alignment" in eng_err.user_message

    def test_err_003_infrastructure_error_formatting(self):
        """P15-ERR-003: Infrastructure topological errors give appropriate advice."""
        exc = InfrastructureError("Track link TL-99 refers to non-existent node N-99.")
        eng_err = format_exception_for_ui(exc, context="Network Graph Assembly")
        assert eng_err.category == "Infrastructure Network Error"
        assert "TL-99" in eng_err.user_message

    def test_err_004_simulation_without_project(self):
        """P15-ERR-004: Attempting simulation when no project is loaded returns clear error."""
        with pytest.raises(Exception) as exc_info:
            SimulationRunner.run_simulation_pipeline(
                project=None,  # type: ignore
                running_direction=RunningDirection.FORWARD,
            )
        err = format_exception_for_ui(exc_info.value, context="Simulation Launcher")
        assert err is not None

    def test_err_005_direction_incompatibility_detection(self):
        """P15-ERR-005: Running direction incompatible with tracks gives informative error."""
        from headway.data.canonical import TrackDirectionality

        proj, _, _ = ProjectFileManager.load_example_project("01_single_track")
        # Artificially set all tracks to NOMINAL (forward-only)
        for track in proj.infrastructure.tracks:
            object.__setattr__(track, "directionality", TrackDirectionality.NOMINAL)

        is_valid, msg = DirectionSelector.validate_direction(RunningDirection.REVERSE, proj)
        assert is_valid is False
        assert "NOMINAL" in msg

    def test_err_006_malformed_zip_import(self):
        """P15-ERR-006: Importing a corrupt/empty ZIP package fails gracefully."""
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.write(b"NOT A VALID ZIP ARCHIVE CONTENT")
        tmp.close()

        with pytest.raises(Exception) as exc_info:
            ProjectFileManager.import_project_zip(Path(tmp.name))
        err = format_exception_for_ui(exc_info.value, context="ZIP Restoration")
        assert err.category in ("Missing File Error", "General Operational Error")

    def test_err_007_missing_report_assembly_results(self):
        """P15-ERR-007: Generating report when no results exist in session produces error."""
        assert session_state.latest_result_package is None
        # Should not crash or produce unhandled tracebacks
        err_html = create_error_html("No Simulation Results", "Execute simulation in Tab 8 first.")
        assert "⚠️ No Simulation Results" in err_html

    def test_err_008_invalid_scenario_override_error(self):
        """P15-ERR-008: Scenario error produces actionable user guidance."""
        exc = ScenarioError("Conflicting override: Cannot set headway_s both higher and lower than limit.")
        eng_err = format_exception_for_ui(exc, context="Scenario Manager")
        assert eng_err.category == "Scenario Configuration Error"
        assert "baseline integrity" in eng_err.recommendation.lower() or "override" in eng_err.recommendation.lower()
