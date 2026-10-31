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

from headway.data.canonical import TrackDirectionality
from headway.data.converter import convert_raw_to_canonical
from headway.data.importer import ExcelImporter
from headway.data.validation import Severity, ValidationReport
from headway.data.validator import DatasetValidator
from headway.infrastructure.direction import DirectionPolicyError, RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import RouteEngine
from headway.ui.file_manager import FileManager
from tests.corrected_variants import load_corrected_variant
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
    # v1.11.2: runs on the corrected in-memory variant (tests/corrected_variants.py); the shipped example raises a named ERR_* (tests/unit/test_v1112_bidirectional_integrity.py).
    project, report, _ = load_corrected_variant("05_comprehensive_line")
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


@pytest.mark.integration
def test_comprehensive_line_track_directionality_matches_permitted_routes():
    """Regression test for RHS-CORRECTION-COMPREHENSIVE-DIR-001.

    Verifies:
    1. For every track in the comprehensive example, declared directionality matches
       actual permitted traversal of at least one reference route.
    2. TRK_DN specifically permits South -> North routing from ND_11 to ND_01.
    3. If TRK_DN directionality were set to REVERSE, South -> North routing fails.
    """
    project, report, _ = FileManager.load_example_project("05_comprehensive_line")
    assert report.is_simulation_ready

    graph = PhysicalNetworkGraph(project.infrastructure)
    engine = RouteEngine(graph)

    # 1. TRK_UP (NOMINAL): permits North -> South traversal ND_01 -> ND_11
    up_links = [f"LNK_{i:02d}" for i in range(1, 11)]
    route_up = engine.build_route_from_traversals("RT_UP_REF", [(l, RunningDirection.FORWARD) for l in up_links])
    assert route_up.start_node_id == "ND_01"
    assert route_up.end_node_id == "ND_11"
    assert route_up.total_length_m == 25000.0

    # 2. TRK_DN (NOMINAL): permits South -> North traversal ND_11 -> ND_01
    track_dn = next(t for t in project.infrastructure.tracks if t.track_id == "TRK_DN")
    assert track_dn.directionality == TrackDirectionality.NOMINAL, "TRK_DN must be NOMINAL to permit ND_11 -> ND_01 traversal"

    dn_links = [f"LNK_{i:02d}" for i in range(11, 18)]
    route_dn = engine.build_route_from_traversals("RT_DN_REF", [(l, RunningDirection.FORWARD) for l in dn_links])
    assert route_dn.start_node_id == "ND_11", f"Expected start at ND_11 (South), got {route_dn.start_node_id}"
    assert route_dn.end_node_id == "ND_01", f"Expected exit at ND_01 (North), got {route_dn.end_node_id}"
    assert route_dn.total_length_m == 25000.0

    # Verify node-sequence routing from ND_11 to ND_01
    node_seq = ["ND_11", "ND_10", "ND_09", "ND_08", "ND_07", "ND_05", "ND_03", "ND_01"]
    route_dn_nodes = engine.build_route_from_nodes("RT_DN_NODES", node_seq)
    assert route_dn_nodes.link_ids == dn_links

    # 3. TRK_SIDING (BIDIRECTIONAL): permits both FORWARD (ND_04 -> ND_05) and REVERSE (ND_05 -> ND_04)
    route_sd_fwd = engine.build_route_from_traversals("RT_SD_FWD", [("LNK_18", RunningDirection.FORWARD)])
    assert route_sd_fwd.start_node_id == "ND_04" and route_sd_fwd.end_node_id == "ND_05"

    route_sd_rev = engine.build_route_from_traversals("RT_SD_REV", [("LNK_18", RunningDirection.REVERSE)])
    assert route_sd_rev.start_node_id == "ND_05" and route_sd_rev.end_node_id == "ND_04"

    # 4. Invariant: If TRK_DN were REVERSE, attempting South -> North routing must fail
    modified_infra = project.infrastructure.model_copy(deep=True)
    for t in modified_infra.tracks:
        if t.track_id == "TRK_DN":
            t.directionality = TrackDirectionality.REVERSE
    bad_graph = PhysicalNetworkGraph(modified_infra)
    bad_engine = RouteEngine(bad_graph)
    with pytest.raises(DirectionPolicyError):
        bad_engine.build_route_from_traversals("RT_BAD_DN", [(l, RunningDirection.FORWARD) for l in dn_links])


@pytest.mark.integration
def test_comprehensive_line_dn_headway_analyses_resolve():
    """Verify that both DN analyses (AN_HSR_HSR_DN and AN_REG_REG_DN) resolve successfully."""
    project, report, _ = FileManager.load_example_project("05_comprehensive_line")
    assert report.is_simulation_ready

    # Check that AN_HSR_HSR_DN and AN_REG_REG_DN are defined in project
    analyses = {a.analysis_id: a for a in project.analysis.analyses}
    assert "AN_HSR_HSR_DN" in analyses
    assert "AN_REG_REG_DN" in analyses

    # Check service patterns route from ND_11 to ND_01
    graph = PhysicalNetworkGraph(project.infrastructure)
    engine = RouteEngine(graph)

    svc_map = {s.service_pattern_id: s for s in project.operations.service_patterns}
    for an_id, svc_id in [("AN_HSR_HSR_DN", "SVC_HSR_EXP_DN"), ("AN_REG_REG_DN", "SVC_REG_ALL_DN")]:
        svc = svc_map[svc_id]
        route = engine.build_route_from_traversals(
            f"RT_{an_id}",
            [(lid, RunningDirection.FORWARD) for lid in svc.route_link_sequence]
        )
        assert route.start_node_id == "ND_11", f"{an_id} should start at ND_11 (South)"
        assert route.end_node_id == "ND_01", f"{an_id} should end at ND_01 (North)"
        assert route.total_length_m == 25000.0
