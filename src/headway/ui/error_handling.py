"""Error handling and user feedback helpers for the Railway Headway Simulator UI.

Milestone P15 — UI Integration & Verification (P15-ERR-001 to P15-ERR-006).
Provides professional, understandable railway engineering error messages without exposing
raw Python tracebacks to end users.
"""

from dataclasses import dataclass
import logging
import traceback
from typing import Any, Dict, Optional, Union

from headway.core.exceptions import (
    ConfigurationError,
    DataValidationError,
    HeadwayCalculationError,
    InfrastructureError,
    OperationalSimulationError,
    RollingStockError,
    ScenarioError,
    SignallingError,
    SimulationError,
)

logger = logging.getLogger("headway.ui.error_handling")


@dataclass
class EngineeringError:
    """Structured representation of an engineering error formatted for the UI."""
    category: str
    error_type: str
    error_code: str
    user_message: str
    recommendation: str
    technical_details: str
    traceback: str

    def to_html(self) -> str:
        return f"""
        <div style="background-color: #FEF2F2; border: 1px solid #F87171; border-left: 5px solid #DC2626; padding: 14px 18px; border-radius: 6px; margin: 10px 0;">
            <div style="font-weight: 700; color: #991B1B; font-size: 14px; margin-bottom: 4px;">
                ⚠️ {self.category}: {self.error_code}
            </div>
            <div style="color: #7F1D1D; font-size: 13px; margin-bottom: 8px;">
                {self.user_message}
            </div>
            <div style="font-size: 12px; color: #4B5563; background: #FFFFFF; padding: 8px 12px; border-radius: 4px; border: 1px solid #E5E7EB;">
                <strong>Recommended Action:</strong> {self.recommendation}
            </div>
        </div>
        """


def format_exception_for_ui(
    error: Exception,
    context: str = "Simulation Operation",
) -> EngineeringError:
    """Format an exception into a user-facing engineering diagnostic message.

    P15-ERR-001 & P15-ERR-002: Replaces raw tracebacks with understandable
    engineering explanations and recommended corrective actions.
    """
    tb_str = traceback.format_exc()
    logger.error("Error during %s: %s\n%s", context, error, tb_str)

    error_type = type(error).__name__
    message = str(error)
    category = "General Operational Error"
    recommendation = "Review input parameters and retry."
    code = getattr(error, "error_code", "ERR_SIM_FAIL")

    if isinstance(error, DataValidationError):
        category = "Data Validation Error"
        code = getattr(error, "error_code", "ERR_DATA_VALIDATION")
        recommendation = "Check the uploaded dataset against the schema requirements in the Data Validation tab."
    elif isinstance(error, InfrastructureError):
        category = "Infrastructure Network Error"
        code = getattr(error, "error_code", "ERR_INFRASTRUCTURE")
        recommendation = "Verify track link connectivity, node definitions, and route directionality."
    elif isinstance(error, RollingStockError):
        category = "Rolling Stock Definition Error"
        code = getattr(error, "error_code", "ERR_ROLLING_STOCK")
        recommendation = "Check train mass, length, traction curves, and braking rates."
    elif isinstance(error, SignallingError):
        category = "Signalling & Interlocking Error"
        code = getattr(error, "error_code", "ERR_SIGNALLING")
        recommendation = "Verify signal aspect sequences, block assignments, and route interlocking parameters."
    elif isinstance(error, ScenarioError):
        category = "Scenario Configuration Error"
        code = getattr(error, "error_code", "ERR_SCENARIO")
        recommendation = "Check scenario parameter overrides, inheritance chains, and baseline integrity."
    elif isinstance(error, (HeadwayCalculationError, SimulationError, OperationalSimulationError)):
        category = "Headway Simulation Calculation Error"
        code = getattr(error, "error_code", "ERR_SIMULATION")
        recommendation = "Check running direction, alignment connectivity, and headway convergence parameters."
    elif isinstance(error, ConfigurationError):
        category = "System Configuration Error"
        code = getattr(error, "error_code", "ERR_CONFIGURATION")
        recommendation = "Verify system settings, directories, and server configuration."
    elif isinstance(error, FileNotFoundError):
        category = "Missing File Error"
        code = "ERR_FILE_NOT_FOUND"
        recommendation = "Ensure the specified file or project directory exists on the system."
    elif isinstance(error, ValueError):
        category = "Invalid Parameter Value"
        code = "ERR_INVALID_VALUE"
        recommendation = "Ensure all numeric and textual inputs fall within acceptable engineering ranges."

    return EngineeringError(
        category=category,
        error_type=error_type,
        error_code=code,
        user_message=f"[{context}] {message}",
        recommendation=recommendation,
        technical_details=f"{error_type}: {message}",
        traceback=tb_str,
    )


def format_engineering_error(
    error: Exception,
    operation_context: str = "Simulation Operation",
) -> Dict[str, Any]:
    """Format an exception into an engineering dictionary (for backward compatibility)."""
    eng = format_exception_for_ui(error, operation_context)
    return {
        "is_error": True,
        "category": eng.category,
        "error_type": eng.error_type,
        "error_code": eng.error_code,
        "message": str(error),
        "user_message": eng.user_message,
        "recommendation": eng.recommendation,
        "traceback": eng.traceback,
    }


def create_error_html(
    error_or_title: Union[Dict[str, Any], str, EngineeringError],
    message: Optional[str] = None,
) -> str:
    """Render a styled error banner matching the dark navy & red engineering palette."""
    if isinstance(error_or_title, EngineeringError):
        return error_or_title.to_html()
    elif isinstance(error_or_title, dict):
        cat = error_or_title.get("category", "Engineering Error")
        code = error_or_title.get("error_code", "ERR_SIM_FAIL")
        msg = error_or_title.get("message", "An error occurred during execution.")
        rec = error_or_title.get("recommendation", "Inspect parameters and try again.")
        return f"""
        <div style="background-color: #FEF2F2; border: 1px solid #F87171; border-left: 5px solid #DC2626; padding: 14px 18px; border-radius: 6px; margin: 10px 0;">
            <div style="font-weight: 700; color: #991B1B; font-size: 14px; margin-bottom: 4px;">
                ⚠️ {cat}: {code}
            </div>
            <div style="color: #7F1D1D; font-size: 13px; margin-bottom: 8px;">
                {msg}
            </div>
            <div style="font-size: 12px; color: #4B5563; background: #FFFFFF; padding: 8px 12px; border-radius: 4px; border: 1px solid #E5E7EB;">
                <strong>Recommended Action:</strong> {rec}
            </div>
        </div>
        """
    else:
        title = str(error_or_title)
        msg = message or ""
        return f"""
        <div style="background-color: #FEF2F2; border: 1px solid #F87171; border-left: 5px solid #DC2626; padding: 14px 18px; border-radius: 6px; margin: 10px 0;">
            <div style="font-weight: 700; color: #991B1B; font-size: 14px; margin-bottom: 4px;">
                ⚠️ {title}
            </div>
            <div style="color: #7F1D1D; font-size: 13px;">
                {msg}
            </div>
        </div>
        """


def create_success_html(
    title: str,
    message: str,
) -> str:
    """Render a styled success banner matching the dark navy & green engineering palette."""
    return f"""
    <div style="background-color: #F0FDF4; border: 1px solid #86EFAC; border-left: 5px solid #16A34A; padding: 14px 18px; border-radius: 6px; margin: 10px 0;">
        <div style="font-weight: 700; color: #166534; font-size: 14px; margin-bottom: 4px;">
            ✓ {title}
        </div>
        <div style="color: #15803D; font-size: 13px;">
            {message}
        </div>
    </div>
    """


def create_warning_html(
    title: str,
    message: str,
) -> str:
    """Render a styled warning banner."""
    return f"""
    <div style="background-color: #FFFBEB; border: 1px solid #FCD34D; border-left: 5px solid #D97706; padding: 14px 18px; border-radius: 6px; margin: 10px 0;">
        <div style="font-weight: 700; color: #92400E; font-size: 14px; margin-bottom: 4px;">
            ⚠️ {title}
        </div>
        <div style="color: #B45309; font-size: 13px;">
            {message}
        </div>
    </div>
    """
