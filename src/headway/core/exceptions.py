"""Structured application exception hierarchy for Railway Headway & Capacity Simulator.

All custom errors derive from HeadwayError to ensure consistent error codes,
technical diagnostics, and user-friendly error formatting for the Gradio UI.
"""

from typing import Any, Dict, Optional


class HeadwayError(Exception):
    """Base exception for all Railway Headway & Capacity Simulator errors.

    Attributes:
        message: Human-readable description of the error.
        error_code: Standardized error code string (e.g. 'ERR_CORE_CONFIG').
        technical_details: Optional low-level diagnostic details for logs.
        context: Optional dictionary containing runtime variables or identifiers.
    """

    DEFAULT_ERROR_CODE: str = "ERR_HEADWAY_GENERAL"

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        technical_details: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.error_code: str = error_code or self.DEFAULT_ERROR_CODE
        self.technical_details: Optional[str] = technical_details
        self.context: Dict[str, Any] = context or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception metadata to a dictionary for structured logging or JSON."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "technical_details": self.technical_details,
            "context": self.context,
        }

    def user_friendly_message(self) -> str:
        """Format an informative, user-facing error message suitable for Gradio display.

        Excludes low-level stack traces or internal implementation artifacts.
        """
        base = f"[{self.error_code}] {self.message}"
        if self.context:
            context_summary = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{base} (Context: {context_summary})"
        return base

    def __str__(self) -> str:
        msg = f"[{self.error_code}] {self.message}"
        if self.technical_details:
            msg += f" | Details: {self.technical_details}"
        return msg


class ConfigurationError(HeadwayError):
    """Raised when application configuration or environment settings are invalid."""

    DEFAULT_ERROR_CODE = "ERR_CORE_CONFIG"


class EnvironmentError(HeadwayError):
    """Raised when the execution environment (Python version, Colab runtime, storage) is invalid."""

    DEFAULT_ERROR_CODE = "ERR_CORE_ENV"


class DataValidationError(HeadwayError):
    """Raised when input datasets (Excel, JSON) violate data contracts or schema requirements."""

    DEFAULT_ERROR_CODE = "ERR_DATA_VALIDATION"


class InfrastructureError(HeadwayError):
    """Raised when physical infrastructure network topology or attributes are invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRASTRUCTURE"


class RollingStockError(HeadwayError):
    """Raised when train characteristics, traction, or mass parameters are invalid."""

    DEFAULT_ERROR_CODE = "ERR_ROLLING_STOCK"


class SignallingError(HeadwayError):
    """Raised when signalling layout, aspects, or movement authorities are invalid."""

    DEFAULT_ERROR_CODE = "ERR_SIGNALLING"


class SimulationError(HeadwayError):
    """Raised during microscopic numerical integration or discrete-event simulation failures."""

    DEFAULT_ERROR_CODE = "ERR_SIMULATION"


class DeadlockError(SimulationError):
    """Raised when an unresolvable operational deadlock is detected."""

    DEFAULT_ERROR_CODE = "ERR_SIM_DEADLOCK"


class OperationalSimulationError(SimulationError):
    """Raised when operational constraints or invalid service configurations occur."""

    DEFAULT_ERROR_CODE = "ERR_SIM_OPERATIONAL"


class HeadwayCalculationError(HeadwayError):
    """Raised during headway conflict analysis or technical headway resolution failures."""

    DEFAULT_ERROR_CODE = "ERR_HEADWAY"


class ReportingError(HeadwayError):
    """Raised when generating engineering reports, charts, or export deliverables fails."""

    DEFAULT_ERROR_CODE = "ERR_REPORTING"


class ScenarioError(HeadwayError):
    """Base exception for scenario management and override operations."""

    DEFAULT_ERROR_CODE = "ERR_SCN"


class CircularInheritanceError(ScenarioError):
    """Raised when a circular parent-child dependency is detected in scenario inheritance."""

    DEFAULT_ERROR_CODE = "ERR_SCN_CIRCULAR_INHERITANCE"


class ConflictingOverrideError(ScenarioError):
    """Raised when conflicting overrides targeting the same parameter exist at the same level."""

    DEFAULT_ERROR_CODE = "ERR_SCN_CONFLICTING_OVERRIDE"


class ScenarioNotFoundError(ScenarioError):
    """Raised when a requested scenario ID does not exist."""

    DEFAULT_ERROR_CODE = "ERR_SCN_NOT_FOUND"
