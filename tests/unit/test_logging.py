"""Unit tests for centralized logging framework."""

import logging
from pathlib import Path
import pytest

from headway.core.logging_config import (
    RailwayLogFormatter,
    get_logger,
    setup_logging,
)


@pytest.mark.unit
def test_setup_logging_console_and_file(temp_storage_dir: Path):
    """Verify logger configuration and handlers attachment."""
    log_dir = temp_storage_dir / "logs"
    logger = setup_logging(level="DEBUG", log_dir=log_dir, log_to_file=True)

    assert logger.name == "headway"
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) >= 2  # Stream and File

    # Verify log output file is created
    logger.info("Test logging message for verification")
    log_file = log_dir / "headway.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test logging message for verification" in content


@pytest.mark.unit
def test_railway_log_formatter_context():
    """Verify custom formatter includes simulation context fields."""
    formatter = RailwayLogFormatter(include_context=True)
    record = logging.LogRecord(
        name="headway.simulation",
        level=logging.INFO,
        pathname="mock.py",
        lineno=42,
        msg="Train advanced to signal",
        args=(),
        exc_info=None,
    )
    record.train_id = "EXP-101"
    record.resource_id = "SIG-S04"

    formatted = formatter.format(record)
    assert "Train advanced to signal" in formatted
    assert "train_id=EXP-101" in formatted
    assert "resource_id=SIG-S04" in formatted


@pytest.mark.unit
def test_get_child_logger():
    """Verify get_logger returns logger in 'headway' hierarchy."""
    child = get_logger("ui.app")
    assert child.name == "headway.ui.app"

    root = get_logger("headway")
    assert root.name == "headway"
