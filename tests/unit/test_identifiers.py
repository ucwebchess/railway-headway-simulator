"""Unit tests for identifier syntax normalization and registry cross-referencing."""

import pytest
from headway.core.exceptions import DataValidationError
from headway.core.identifiers import IdentifierRegistry, normalize_identifier


@pytest.mark.unit
def test_normalize_identifier_whitespace():
    assert normalize_identifier("  LNK_01  ") == "LNK_01"
    assert normalize_identifier("TRK-MAIN:01") == "TRK-MAIN:01"


@pytest.mark.unit
def test_normalize_identifier_preserves_case():
    assert normalize_identifier("Lnk_East") == "Lnk_East"
    assert normalize_identifier("trk_01") == "trk_01"


@pytest.mark.unit
def test_normalize_identifier_invalid_syntax():
    with pytest.raises(DataValidationError) as exc:
        normalize_identifier("LNK 01")  # Space inside
    assert exc.value.error_code == "ERR_ID_INVALID_SYNTAX"

    with pytest.raises(DataValidationError):
        normalize_identifier("")  # Empty

    with pytest.raises(DataValidationError):
        normalize_identifier("LNK@#01")  # Disallowed characters


@pytest.mark.unit
def test_identifier_registry_duplicate_detection():
    registry = IdentifierRegistry()
    registry.register("LINK", "LNK_01")
    registry.register("LINK", "LNK_02")

    # Duplicate in same namespace
    with pytest.raises(DataValidationError) as exc:
        registry.register("LINK", "LNK_01")
    assert exc.value.error_code == "ERR_ID_DUPLICATE"

    # Same ID in different namespace is permitted
    registry.register("TRACK", "LNK_01")
    assert registry.exists("TRACK", "LNK_01")


@pytest.mark.unit
def test_identifier_registry_reference_verification():
    registry = IdentifierRegistry()
    registry.register("TRACK", "TRK_01")

    # Valid reference
    ref = registry.verify_reference("TRACK", "TRK_01", referencing_object="TrackLink LNK_01")
    assert ref == "TRK_01"

    # Missing reference
    with pytest.raises(DataValidationError) as exc:
        registry.verify_reference("TRACK", "TRK_NONEXISTENT", referencing_object="TrackLink LNK_02")
    assert exc.value.error_code == "ERR_ID_MISSING_REF"
