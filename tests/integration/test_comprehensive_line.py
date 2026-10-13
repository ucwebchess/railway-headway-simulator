"""Integration tests for 05_comprehensive_line reference dataset.

Satisfies RHS-EXPAND-EXAMPLES-001 § 7.6:
- Asserts that all six workbooks load with zero validation errors.
- Asserts that the canonical project contains the exact expected counts:
  11 nodes, 3 tracks, 18 links, 3 stations, 8 platforms, 8 stopping points,
  1 tunnel, 4 TVS sections, 1 shared resource group, 18 signals, 18 blocks,
  6 routes, 3 train types, 6 service patterns, 10 analyses, and 5 scenarios.
- Asserts that both FORWARD and REVERSE simulation analyses resolve cleanly.
- Asserts that FileManager discovers and loads 05_comprehensive_line.
"""

from pathlib import Path
import pytest

from headway.data.converter import convert_raw_to_canonical
from headway.data.importer import ExcelImporter
from headway.data.validation import Severity, ValidationReport
from headway.data.validator import DatasetValidator
from headway.infrastructure.direction import RunningDirection
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner


EXAMPLE_DIR = Path("examples") / "05_comprehensive_line"
EXPECTED_WORKBOOKS = [
    "01_Infrastructure.xlsx",
    "02_Signalling.xlsx",
    "03_RollingStock.xlsx",
    "04_Operations.xlsx",
    "05_HeadwayAnalysis.xlsx",
    "06_Scenarios.xlsx",
]


@pytest.mark.integration
def test_comprehensive_line_workbooks_exist():
    """Verify that all six standardized workbooks and generator exist."""
    assert EXAMPLE_DIR.exists(), f"Directory {EXAMPLE_DIR} does not exist."
    for wb_name in EXPECTED_WORKBOOKS:
        wb_path = EXAMPLE_DIR / wb_name
        assert wb_path.exists(), f"Workbook {wb_name} is missing in {EXAMPLE_DIR}."
    assert (EXAMPLE_DIR / "generate.py").exists(), "generate.py missing."
    assert (EXAMPLE_DIR / "README.md").exists(), "README.md missing."


@pytest.mark.integration
def test_comprehensive_line_loads_with_zero_errors():
    """Assert that loading all six workbooks produces zero validation errors and simulation readiness."""
    importer = ExcelImporter()
    report = ValidationReport(project_id="05_comprehensive_line")
    raw_wbs = {}

    for wb_name in EXPECTED_WORKBOOKS:
        wb_path = EXAMPLE_DIR / wb_name
        raw_wb = importer.load_workbook(wb_path, report)
        assert raw_wb is not None, f"Failed to load raw workbook {wb_name}"
        raw_wbs[raw_wb.workbook_type] = raw_wb

    assert len(raw_wbs) == 6, f"Expected 6 raw workbooks, got {len(raw_wbs)}"

    validator = DatasetValidator(report)
    validator.validate_all(raw_wbs)

    error_findings = [
        f"[{f.error_code}] {f.message}"
        for f in report.findings
        if f.severity in (Severity.CRITICAL, Severity.ERROR)
    ]
    assert not error_findings, f"Validation errors found in 05_comprehensive_line: {error_findings}"
    assert not report.has_errors
    assert report.is_simulation_ready


@pytest.mark.integration
def test_comprehensive_line_canonical_entity_counts():
    """Assert that canonical conversion yields exact entity counts across all domains."""
    importer = ExcelImporter()
    report = ValidationReport(project_id="05_comprehensive_line")
    raw_wbs = {}
    for wb_name in EXPECTED_WORKBOOKS:
        raw_wb = importer.load_workbook(EXAMPLE_DIR / wb_name, report)
        raw_wbs[raw_wb.workbook_type] = raw_wb

    project = convert_raw_to_canonical(raw_wbs)

    # Infrastructure counts
    assert len(project.infrastructure.nodes) == 11, "Expected 11 nodes"
    assert len(project.infrastructure.tracks) == 3, "Expected 3 tracks (UP, DN, SIDING)"
    assert len(project.infrastructure.track_links) == 18, "Expected 18 track links"
    assert len(project.infrastructure.stations) == 3, "Expected 3 stations (Alpha, Beta, Gamma)"
    assert len(project.infrastructure.platforms) == 8, "Expected 8 platforms"
    assert len(project.infrastructure.stopping_points) == 8, "Expected 8 stopping points"
    assert len(project.infrastructure.tunnels) == 1, "Expected 1 tunnel"
    assert len(project.infrastructure.tvs_sections) == 4, "Expected 4 TVS sections"
    assert len(project.infrastructure.shared_resource_groups) == 1, "Expected 1 shared resource group"

    # Signalling counts
    assert len(project.signalling.signals) == 18, "Expected 18 signals"
    assert len(project.signalling.blocks) == 18, "Expected 18 signalling blocks"
    assert len(project.signalling.routes) == 6, "Expected 6 interlocking routes"

    # Rolling stock counts
    assert len(project.rolling_stock.train_types) == 3, "Expected 3 train types (HSR, REG, FRT)"

    # Operations counts
    assert len(project.operations.service_patterns) == 6, "Expected 6 service patterns"

    # Analysis counts
    assert len(project.analysis.analyses) == 10, "Expected 10 headway analysis configurations"

    # Scenario counts
    assert len(project.scenarios) == 5, "Expected 5 scenarios"


@pytest.mark.integration
def test_comprehensive_line_file_manager_discovery_and_loading():
    """Verify that FileManager discovers and loads 05_comprehensive_line through the standard UI path."""
    examples = FileManager.get_example_projects()
    assert "05_comprehensive_line" in examples, "05_comprehensive_line not discovered by FileManager."

    project, report, file_map = FileManager.load_example_project("05_comprehensive_line")
    assert project is not None
    assert not report.has_errors
    assert report.is_simulation_ready
    assert len(file_map) == 6


@pytest.mark.integration
def test_comprehensive_line_forward_and_reverse_analyses_resolve():
    """Verify that microscopic simulation and headway resolution succeed in both FORWARD and REVERSE directions."""
    project, report, _ = FileManager.load_example_project("05_comprehensive_line")
    assert report.is_simulation_ready

    # 1. Forward Direction Run
    pkg_fwd, doc_fwd = SimulationRunner.run_simulation_pipeline(
        project=project,
        running_direction=RunningDirection.FORWARD,
    )
    assert pkg_fwd.running_direction == RunningDirection.FORWARD
    assert doc_fwd.metadata.running_direction == RunningDirection.FORWARD
    assert doc_fwd.executive_kpis.technical_headway_s > 0.0

    # 2. Reverse Direction Run
    pkg_rev, doc_rev = SimulationRunner.run_simulation_pipeline(
        project=project,
        running_direction=RunningDirection.REVERSE,
    )
    assert pkg_rev.running_direction == RunningDirection.REVERSE
    assert doc_rev.metadata.running_direction == RunningDirection.REVERSE
    assert doc_rev.executive_kpis.technical_headway_s > 0.0
