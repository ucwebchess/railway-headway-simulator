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


def create_platform_schema_error_html(findings: Any) -> Optional[str]:
    """v1.14.0: prominent upload-panel banner for platform-schema errors.

    Returns None when no finding carries one of the PlatformSpans / legacy-schema codes
    (``ERR_PLATFORMS_DEPRECATED``, ``ERR_STOPPINGPOINTS_DEPRECATED``, ``ERR_PLATFORM_SPAN_*``,
    ``ERR_STOPPING_PATTERN_REFERENCES_SEGMENT``, ``ERR_PLATFORM_NOMINAL_STOP_INVALID``).
    """
    import html as _html

    from headway.data.platform_spans import (
        ALL_PLATFORM_SPAN_ERROR_CODES,
        ERR_PLATFORMS_DEPRECATED,
        ERR_STOPPINGPOINTS_DEPRECATED,
        MIGRATION_GUIDE,
        MIGRATION_GUIDE_URL,
        MIGRATION_HELPER,
    )

    hits = [f for f in (findings or []) if getattr(f, "error_code", None) in ALL_PLATFORM_SPAN_ERROR_CODES]
    if not hits:
        return None
    legacy = any(f.error_code in (ERR_PLATFORMS_DEPRECATED, ERR_STOPPINGPOINTS_DEPRECATED) for f in hits)
    title = "Legacy platform schema rejected (v1.14.0)" if legacy else "Invalid PlatformSpans data"
    items = "".join(
        f"<li style='margin: 4px 0;'><code style='font-weight: 700; color: #991B1B;'>{_html.escape(f.error_code)}</code>"
        f"{' &mdash; ' + _html.escape(str(f.worksheet)) if getattr(f, 'worksheet', None) else ''}"
        f"{' / <code>' + _html.escape(str(f.object_id)) + '</code>' if getattr(f, 'object_id', None) else ''}: "
        f"{_html.escape(str(f.message))}</li>"
        for f in hits
    )
    how = (
        "Replace the <code>Platforms</code> and <code>StoppingPoints</code> sheets with one <code>PlatformSpans</code> "
        "sheet (one row per physical platform). Convert automatically with "
        f"<code>python {MIGRATION_HELPER} INFRASTRUCTURE.xlsx --operations OPERATIONS.xlsx</code>, review the printed "
        "table, then upload the migrated workbooks."
        if legacy
        else "Correct the listed PlatformSpans rows / StoppingPatterns references and upload again."
    )
    return f"""
    <div id="platform-schema-error" style="background-color: #FEF2F2; border: 2px solid #DC2626; border-left: 8px solid #DC2626; padding: 16px 20px; border-radius: 6px; margin: 10px 0;">
        <div style="font-weight: 800; color: #991B1B; font-size: 16px; margin-bottom: 8px;">⛔ {_html.escape(title)}</div>
        <ul style="color: #7F1D1D; font-size: 13px; margin: 0 0 10px 18px; padding: 0;">{items}</ul>
        <div style="font-size: 13px; color: #1F2937; background: #FFFFFF; padding: 10px 12px; border-radius: 4px; border: 1px solid #E5E7EB;">
            <strong>How to fix:</strong> {how}<br/>
            <strong>Migration guide:</strong> <a href="{MIGRATION_GUIDE_URL}" target="_blank" rel="noopener">{_html.escape(MIGRATION_GUIDE)}</a>
        </div>
    </div>
    """
