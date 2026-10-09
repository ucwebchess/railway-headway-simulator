"""Unit tests for the structured exception hierarchy."""

import pytest
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


@pytest.mark.unit
def test_base_headway_error_attributes():
    """Verify base exception attributes, to_dict, and formatting."""
    err = HeadwayError(
        message="Test general failure",
        error_code="ERR_TEST_001",
        technical_details="Null pointer reference in mock solver",
        context={"train_id": "TRN-01", "block_id": "BLK-10"},
    )

    assert err.message == "Test general failure"
    assert err.error_code == "ERR_TEST_001"
    assert err.technical_details == "Null pointer reference in mock solver"
    assert err.context == {"train_id": "TRN-01", "block_id": "BLK-10"}

    # User friendly presentation does not expose raw internals
    friendly = err.user_friendly_message()
    assert "[ERR_TEST_001] Test general failure" in friendly
    assert "train_id=TRN-01" in friendly

    d = err.to_dict()
    assert d["error_code"] == "ERR_TEST_001"
    assert d["message"] == "Test general failure"


@pytest.mark.unit
def test_exception_categories_inheritance():
    """Verify that all domain exceptions derive from HeadwayError with default error codes."""
    cases = [
        (ConfigurationError, "ERR_CORE_CONFIG"),
        (EnvironmentError, "ERR_CORE_ENV"),
        (DataValidationError, "ERR_DATA_VALIDATION"),
        (InfrastructureError, "ERR_INFRASTRUCTURE"),
        (RollingStockError, "ERR_ROLLING_STOCK"),
        (SignallingError, "ERR_SIGNALLING"),
        (SimulationError, "ERR_SIMULATION"),
        (HeadwayCalculationError, "ERR_HEADWAY"),
        (ReportingError, "ERR_REPORTING"),
    ]

    for exc_class, default_code in cases:
        instance = exc_class("Sample error message")
        assert isinstance(instance, HeadwayError)
        assert instance.error_code == default_code
        assert "Sample error message" in str(instance)
