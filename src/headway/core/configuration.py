"""Centralized application configuration for Railway Headway & Capacity Simulator.

Provides strongly typed configuration models, validation, environment variable
overrides, and runtime directory management suitable for both Google Colab
and standard local execution environments.
"""

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from headway.core.exceptions import ConfigurationError
from headway.core.version import APP_NAME, __version__


class EnvironmentType(str, Enum):
    """Supported execution environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"
    COLAB = "colab"


def is_running_in_colab() -> bool:
    """Detect whether the current process is executing within Google Colab."""
    try:
        import sys
        return "google.colab" in sys.modules
    except Exception:
        return False


class GradioServerConfig:
    """Configuration parameters for the Gradio interface server.

    Strictly enforces non-negotiable security requirements:
    Public sharing is disabled by default (share=False).
    """

    def __init__(
        self,
        server_name: str = "0.0.0.0",
        server_port: int = 7860,
        share: bool = False,
        debug: bool = False,
        show_error: bool = True,
        inbrowser: bool = False,
    ) -> None:
        self.server_name: str = server_name
        self.server_port: int = server_port
        self.share: bool = share
        self.debug: bool = debug
        self.show_error: bool = show_error
        self.inbrowser: bool = inbrowser

    def validate(self) -> None:
        """Validate server configuration parameters."""
        if not (1024 <= self.server_port <= 65535):
            raise ConfigurationError(
                f"Invalid server port {self.server_port}. Must be between 1024 and 65535.",
                error_code="ERR_CORE_CONFIG_PORT",
                context={"server_port": self.server_port},
            )
        if not self.server_name:
            raise ConfigurationError(
                "server_name cannot be empty.",
                error_code="ERR_CORE_CONFIG_SERVER_NAME",
            )


class DirectoryConfig:
    """Manages file storage paths for projects, temp files, results, and logs."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        projects_dir: Optional[Path] = None,
        temp_dir: Optional[Path] = None,
        results_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
        logs_dir: Optional[Path] = None,
    ) -> None:
        default_base = Path(os.environ.get("HEADWAY_STORAGE_DIR", Path.cwd() / "storage"))
        self.base_dir: Path = (base_dir or default_base).resolve()
        self.projects_dir: Path = (projects_dir or self.base_dir / "projects").resolve()
        self.temp_dir: Path = (temp_dir or self.base_dir / "temp").resolve()
        self.results_dir: Path = (results_dir or self.base_dir / "results").resolve()
        self.reports_dir: Path = (reports_dir or self.base_dir / "reports").resolve()
        self.logs_dir: Path = (logs_dir or self.base_dir / "logs").resolve()

    def ensure_directories_exist(self) -> None:
        """Create all managed runtime directories if they do not exist."""
        for path in (
            self.base_dir,
            self.projects_dir,
            self.temp_dir,
            self.results_dir,
            self.reports_dir,
            self.logs_dir,
        ):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as err:
                raise ConfigurationError(
                    f"Failed to create runtime directory '{path}': {err}",
                    error_code="ERR_CORE_CONFIG_DIR_CREATE",
                    technical_details=str(err),
                    context={"path": str(path)},
                ) from err


class AppConfig:
    """Master application configuration for Railway Headway & Capacity Simulator."""

    VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    def __init__(
        self,
        app_name: str = APP_NAME,
        version: str = __version__,
        environment: Optional[EnvironmentType] = None,
        log_level: str = "INFO",
        dev_mode: bool = True,
        directories: Optional[DirectoryConfig] = None,
        server: Optional[GradioServerConfig] = None,
    ) -> None:
        self.app_name: str = app_name
        self.version: str = version

        # Determine environment
        env_str = os.environ.get("HEADWAY_ENV", "").strip().lower()
        if env_str:
            try:
                self.environment: EnvironmentType = EnvironmentType(env_str)
            except ValueError:
                self.environment = EnvironmentType.DEVELOPMENT
        elif environment is not None:
            self.environment = environment
        elif is_running_in_colab():
            self.environment = EnvironmentType.COLAB
        else:
            self.environment = EnvironmentType.DEVELOPMENT

        # Logging level
        env_log = os.environ.get("HEADWAY_LOG_LEVEL", "").strip().upper()
        self.log_level: str = env_log if env_log in self.VALID_LOG_LEVELS else log_level.upper()

        # Dev mode
        env_dev = os.environ.get("HEADWAY_DEV_MODE")
        if env_dev is not None:
            self.dev_mode: bool = env_dev.lower() in {"1", "true", "yes"}
        else:
            self.dev_mode = dev_mode

        # Nested configs
        self.directories: DirectoryConfig = directories or DirectoryConfig()
        self.server: GradioServerConfig = server or GradioServerConfig(
            server_name=os.environ.get("HEADWAY_SERVER_NAME", "0.0.0.0"),
            server_port=int(os.environ.get("HEADWAY_SERVER_PORT", "7860")),
            share=os.environ.get("HEADWAY_SERVER_SHARE", "false").lower() in {"1", "true", "yes"},
            debug=os.environ.get("HEADWAY_SERVER_DEBUG", "false").lower() in {"1", "true", "yes"},
        )

        self.validate()

    def validate(self) -> None:
        """Validate entire application configuration."""
        if not self.app_name:
            raise ConfigurationError("Application name cannot be empty.", error_code="ERR_CORE_CONFIG_NAME")

        if self.log_level not in self.VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"Invalid log level '{self.log_level}'. Must be one of {sorted(self.VALID_LOG_LEVELS)}.",
                error_code="ERR_CORE_CONFIG_LOG_LEVEL",
                context={"log_level": self.log_level},
            )

        self.server.validate()

    def initialize_runtime(self) -> None:
        """Initialize all runtime requirements (directories, logging paths)."""
        self.directories.ensure_directories_exist()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration summary for display or diagnostics."""
        return {
            "app_name": self.app_name,
            "version": self.version,
            "environment": self.environment.value,
            "log_level": self.log_level,
            "dev_mode": self.dev_mode,
            "storage_base": str(self.directories.base_dir),
            "server_name": self.server.server_name,
            "server_port": self.server.server_port,
            "server_share": self.server.share,
        }
