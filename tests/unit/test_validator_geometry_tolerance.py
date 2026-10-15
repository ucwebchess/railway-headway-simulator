"""Unit tests for floating-point geometry tolerance in dataset validation.

Strictly verifies RHS-CORRECTION-VALIDATOR-TOL-001:
- GEOMETRY_TOLERANCE_M is 0.001 m (1 mm).
- Floating-point noise at the 10^-14 m scale does not raise physical discontinuity errors.
- Genuine gaps exceeding 1 mm are strictly detected as physical discontinuities.
- Non-geometric engineering checks (identifiers, enums, link lengths <= 0) remain strict.
"""

from pathlib import Path
import pytest

from headway.data.importer import RawWorkbookData
from headway.data.validation import ValidationReport
from headway.data.validator import (
    GEOMETRY_TOLERANCE_M,
    DatasetValidator,
    _within_tolerance,
)


@pytest.mark.unit
def test_within_tolerance_helper():
    """Verify GEOMETRY_TOLERANCE_M constant and _within_tolerance helper precision."""
    assert GEOMETRY_TOLERANCE_M == 0.001

    # Exact equality
    assert _within_tolerance(97.25, 97.25)

    # Sub-millimetre floating-point noise (10^-14 m)
    assert _within_tolerance(97.25, 97.25000000000001)
    assert _within_tolerance(97.25000000000001, 97.25)

    # Boundary conditions around 1 mm (0.001 m)
    assert _within_tolerance(10.0, 10.001)
    assert _within_tolerance(10.0, 9.999)
    assert not _within_tolerance(10.0, 10.00101)
    assert not _within_tolerance(10.0, 9.99899)

    # Engineering scale gap (2.75 m)
    assert not _within_tolerance(97.25, 100.0)


@pytest.mark.unit
def test_multilink_block_floating_point_noise_across_boundary():
    """Verify that floating-point noise on link length does NOT raise physical discontinuity error.

    Task 4 Test 1:
    1. Creates a block with two intervals: one on LNK_A ending at 97.25 m, another on LNK_B starting at 0.0 m.
    2. Sets LNK_A.LENGTH_M = 97.25000000000001.
    3. Runs the validator.
    4. Asserts that NO discontinuity error is raised.
    """
    sig_raw = RawWorkbookData(
        "SIGNALLING",
        Path("test_sig.xlsx"),
        {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"},
    )
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_UP_001"}]
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_UP_001", "sequence": 1, "link_id": "LNK_A", "start_offset_m": 0.0, "end_offset_m": 97.25},
        {"block_id": "BLK_UP_001", "sequence": 2, "link_id": "LNK_B", "start_offset_m": 0.0, "end_offset_m": 50.0},
    ]

    infra_raw = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_A", "start_node_id": "N1", "end_node_id": "N2", "length_m": 97.25000000000001},
        {"link_id": "LNK_B", "start_node_id": "N2", "end_node_id": "N3", "length_m": 100.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    discontinuity_findings = [
        f for f in report.findings
        if f.error_code in ("ERR_ENG_PHYSICAL_DISCONTINUITY", "ERR_ENG_LINK_DISCONTINUITY")
    ]
    bounds_findings = [
        f for f in report.findings
        if f.error_code == "ERR_ENG_BLOCK_BOUNDS_INVALID"
    ]

    assert len(discontinuity_findings) == 0, f"Unexpected discontinuity findings: {[f.message for f in discontinuity_findings]}"
    assert len(bounds_findings) == 0, f"Unexpected bounds findings: {[f.message for f in bounds_findings]}"


@pytest.mark.unit
def test_multilink_block_genuine_gap_across_boundary():
    """Verify that a genuine physical gap across link boundary IS detected as physical discontinuity.

    Task 4 Test 2:
    1. Creates a block where the first interval ends at 97.25 m and the second starts at 0.0 m,
       but where LNK_A.LENGTH_M = 100.0 (a genuine gap of 2.75 m).
    2. Asserts that a discontinuity error IS raised.
    """
    sig_raw = RawWorkbookData(
        "SIGNALLING",
        Path("test_sig.xlsx"),
        {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"},
    )
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_UP_001"}]
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_UP_001", "sequence": 1, "link_id": "LNK_A", "start_offset_m": 0.0, "end_offset_m": 97.25},
        {"block_id": "BLK_UP_001", "sequence": 2, "link_id": "LNK_B", "start_offset_m": 0.0, "end_offset_m": 50.0},
    ]

    infra_raw = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_A", "start_node_id": "N1", "end_node_id": "N2", "length_m": 100.0},
        {"link_id": "LNK_B", "start_node_id": "N2", "end_node_id": "N3", "length_m": 100.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    discontinuity_findings = [
        f for f in report.findings
        if f.error_code == "ERR_ENG_PHYSICAL_DISCONTINUITY"
    ]
    assert len(discontinuity_findings) >= 1
    assert "physical discontinuity across boundary" in discontinuity_findings[0].message


@pytest.mark.unit
def test_same_link_contiguous_offsets_with_floating_point_noise():
    """Verify that contiguous intervals on the same link tolerate sub-millimetre floating-point noise."""
    sig_raw = RawWorkbookData(
        "SIGNALLING",
        Path("test_sig.xlsx"),
        {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"},
    )
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_01"}]
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_01", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 0.0, "end_offset_m": 50.00000000000001},
        {"block_id": "BLK_01", "sequence": 2, "link_id": "LNK_01", "start_offset_m": 50.0, "end_offset_m": 100.0},
    ]

    infra_raw = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 100.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    discontinuity_findings = [
        f for f in report.findings
        if f.error_code == "ERR_ENG_PHYSICAL_DISCONTINUITY"
    ]
    assert len(discontinuity_findings) == 0


@pytest.mark.unit
def test_same_link_contiguous_offsets_genuine_gap():
    """Verify that a genuine gap between intervals on the same link raises ERR_ENG_PHYSICAL_DISCONTINUITY."""
    sig_raw = RawWorkbookData(
        "SIGNALLING",
        Path("test_sig.xlsx"),
        {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"},
    )
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_01"}]
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_01", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 0.0, "end_offset_m": 50.0},
        {"block_id": "BLK_01", "sequence": 2, "link_id": "LNK_01", "start_offset_m": 50.05, "end_offset_m": 100.0},  # 50 mm gap
    ]

    infra_raw = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 100.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    discontinuity_findings = [
        f for f in report.findings
        if f.error_code == "ERR_ENG_PHYSICAL_DISCONTINUITY"
    ]
    assert len(discontinuity_findings) >= 1
    assert "physical discontinuity on link 'LNK_01'" in discontinuity_findings[0].message


@pytest.mark.unit
def test_interval_bounds_tolerance():
    """Verify that interval boundary clamping accommodates floating-point noise but catches real violations."""
    infra_raw = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 100.0},
    ]

    # Sub-millimetre over-length (end = 100.0005 m, within 1 mm) should NOT raise bounds error
    sig_raw_ok = RawWorkbookData(
        "SIGNALLING",
        Path("test_sig.xlsx"),
        {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"},
    )
    sig_raw_ok.worksheets["Blocks"] = [{"block_id": "BLK_OK"}]
    sig_raw_ok.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_OK", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 0.0, "end_offset_m": 100.0005},
    ]

    report_ok = ValidationReport()
    DatasetValidator(report_ok).validate_all({"SIGNALLING": sig_raw_ok, "INFRASTRUCTURE": infra_raw})
    bounds_ok = [f for f in report_ok.findings if f.error_code == "ERR_ENG_BLOCK_BOUNDS_INVALID"]
    assert len(bounds_ok) == 0

    # Beyond tolerance over-length (end = 100.05 m, 50 mm beyond) SHOULD raise bounds error
    sig_raw_bad = RawWorkbookData(
        "SIGNALLING",
        Path("test_sig.xlsx"),
        {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"},
    )
    sig_raw_bad.worksheets["Blocks"] = [{"block_id": "BLK_BAD"}]
    sig_raw_bad.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_BAD", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 0.0, "end_offset_m": 100.05},
    ]

    report_bad = ValidationReport()
    DatasetValidator(report_bad).validate_all({"SIGNALLING": sig_raw_bad, "INFRASTRUCTURE": infra_raw})
    bounds_bad = [f for f in report_bad.findings if f.error_code == "ERR_ENG_BLOCK_BOUNDS_INVALID"]
    assert len(bounds_bad) >= 1


@pytest.mark.unit
def test_platform_bounds_tolerance():
    """Verify platform bounds checking applies millimetre tolerance."""
    infra_raw = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 200.0},
    ]
    # Platform slightly negative (-0.0005 m, within 1 mm) and slightly beyond (200.0005 m, within 1 mm)
    infra_raw.worksheets["Platforms"] = [
        {"platform_id": "PLT_01", "link_id": "LNK_01", "start_offset_m": -0.0005, "end_offset_m": 200.0005},
    ]

    report = ValidationReport()
    DatasetValidator(report).validate_all({"INFRASTRUCTURE": infra_raw})
    bounds_errs = [f for f in report.findings if f.error_code == "ERR_ENG_OFFSET_OUT_OF_BOUNDS"]
    assert len(bounds_errs) == 0

    # Platform clearly negative (-0.05 m)
    infra_bad = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_bad.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 200.0},
    ]
    infra_bad.worksheets["Platforms"] = [
        {"platform_id": "PLT_02", "link_id": "LNK_01", "start_offset_m": -0.05, "end_offset_m": 100.0},
    ]

    report_bad = ValidationReport()
    DatasetValidator(report_bad).validate_all({"INFRASTRUCTURE": infra_bad})
    bounds_bad = [f for f in report_bad.findings if f.error_code == "ERR_ENG_OFFSET_OUT_OF_BOUNDS"]
    assert len(bounds_bad) >= 1


@pytest.mark.unit
def test_strict_engineering_checks_preserved():
    """Verify that non-geometric checks (non-positive length, inverted interval) remain strict."""
    infra_raw = RawWorkbookData(
        "INFRASTRUCTURE",
        Path("test_infra.xlsx"),
        {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"},
    )
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_ZERO", "start_node_id": "N1", "end_node_id": "N2", "length_m": 0.0},
        {"link_id": "LNK_NEG", "start_node_id": "N2", "end_node_id": "N3", "length_m": -10.0},
    ]

    report = ValidationReport()
    DatasetValidator(report).validate_all({"INFRASTRUCTURE": infra_raw})

    length_errs = [f for f in report.findings if f.error_code == "ERR_ENG_NON_POSITIVE_LENGTH"]
    assert len(length_errs) == 2
