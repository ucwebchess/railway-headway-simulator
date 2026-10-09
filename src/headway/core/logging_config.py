"""Centralized logging framework for Railway Headway & Capacity Simulator.

Provides structured formatting, stream handlers for Colab and terminal execution,
optional file logging, and support for railway simulation contextual fields
(project_id, scenario_id, simulation_id, train_id, resource_id).
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Contextual attributes supported by the railway logging format
HEADWAY_LOG_CONTEXT_FIELDS = (
    "project_id",
    "scenario_id",
    "simulation_id",
    "train_id",
    "resource_id",
)


class RailwayLogFormatter(logging.Formatter):
    """Custom formatter providing clean console logs and optional simulation context."""

    def __init__(self, include_context: bool = True) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.include_context: bool = include_context

    def format(self, record: logging.LogRecord) -> str:
        # Standard format
        base_formatted = super().format(record)

        if not self.include_context:
            return base_formatted

        # Append non-empty simulation context if present
        context_parts = []
        for field in HEADWAY_LOG_CONTEXT_FIELDS:
            val = getattr(record, field, None)
            if val is not None:
                context_parts.append(f"{field}={val}")

        if context_parts:
            return f"{base_formatted} | {{{', '.join(context_parts)}}}"

        return base_formatted


def setup_logging(
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    log_to_file: bool = True,
    root_logger_name: str = "headway",
) -> logging.Logger:
    """Configure centralized application logging.

    Args:
        level: Log level string ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
        log_dir: Optional directory to store log files.
        log_to_file: Whether to attach a file handler.
        root_logger_name: Root package logger name.

    Returns:
        Configured logger instance.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger(root_logger_name)
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if logger.handlers:
        logger.handlers.clear()

    # Console / Colab Stream Handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(numeric_level)
    stream_handler.setFormatter(RailwayLogFormatter(include_context=True))
    logger.addHandler(stream_handler)

    # Optional file handler
    if log_to_file and log_dir is not None:
        try:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            file_path = log_dir / "headway.log"
            file_handler = logging.FileHandler(file_path, encoding="utf-8")
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(RailwayLogFormatter(include_context=True))
            logger.addHandler(file_handler)
        except Exception as err:
            logger.warning("Could not initialize file logger in %s: %s", log_dir, err)

    # Prevent propagation to standard root logger to avoid duplicated lines in Colab
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the 'headway' namespace."""
    if name.startswith("headway."):
        return logging.getLogger(name)
    if name == "headway":
        return logging.getLogger("headway")
    return logging.getLogger(f"headway.{name}")
