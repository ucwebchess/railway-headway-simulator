"""Core subsystem of the Railway Headway & Capacity Simulator.

Provides application configuration, structured exceptions, centralized logging,
and version metadata.
"""

from headway.core.configuration import AppConfig, EnvironmentType, GradioServerConfig
from headway.core.exceptions import (
    ConfigurationError,
    DataValidationError,
    EnvironmentError,
    HeadwayCalculationError,
    HeadwayError,
    InfrastructureError,
    ReportingError,
    RollingStockError,
    SignallingError,
    SimulationError,
)
from headway.core.identifiers import (
    IdentifierRegistry,
    normalize_identifier,
)
from headway.core.logging_config import get_logger, setup_logging
from headway.core.units import (
    normalize_acceleration,
    normalize_curve_radius,
    normalize_davis_coefficients,
    normalize_distance,
    normalize_energy,
    normalize_force,
    normalize_gradient,
    normalize_mass,
    normalize_power,
    normalize_speed,
    normalize_time,
)
from headway.core.version import APP_NAME, VERSION_INFO, __version__, get_build_info, get_version

__all__ = [
    "APP_NAME",
    "VERSION_INFO",
    "__version__",
    "get_version",
    "get_build_info",
    "AppConfig",
    "EnvironmentType",
    "GradioServerConfig",
    "HeadwayError",
    "ConfigurationError",
    "EnvironmentError",
    "DataValidationError",
    "InfrastructureError",
    "RollingStockError",
    "SignallingError",
    "SimulationError",
    "HeadwayCalculationError",
    "ReportingError",
    "setup_logging",
    "get_logger",
    "normalize_identifier",
    "IdentifierRegistry",
    "normalize_distance",
    "normalize_speed",
    "normalize_mass",
    "normalize_force",
    "normalize_power",
    "normalize_energy",
    "normalize_time",
    "normalize_acceleration",
    "normalize_gradient",
    "normalize_curve_radius",
    "normalize_davis_coefficients",
]
