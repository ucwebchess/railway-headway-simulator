"""Regression tests for visualization axis layouts and report data binding.

RHS-CORRECTION-VIZ-REPORT-001:
  - Part 1: Swap X-Y axes for 7-component, blocking stairway, and platform reservation charts.
  - Part 2: Bind Rolling Stock and Infrastructure report sections to loaded project data.
"""

import pytest

from headway.analysis.blocking_time import BlockingTimeDecomposition
from headway.analysis.conflict_detection import ConflictType, ResourceConflict
from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_blocking import (
    create_blocking_stairway_figure,
    create_seven_component_figure,
)
from headway.reporting.charts_station import create_platform_occupation_figure
from headway.reporting.result_models import (
    HeadwayResult,
    PlatformOccupationRecord,
    ResourceBlockingInterval,
)
from headway.signalling.resource_types import ResourceCategory


def test_axis_layout_seven_component():
    """Test 1a: Seven-component chart has Block Resource on X and Blocking Time [s] on Y."""
    decomp1 = BlockingTimeDecomposition(1.0, 5.0, 10.0, 0.0, 2.0, 0.0, 1.0)
    decomp2 = BlockingTimeDecomposition(1.0, 4.0, 12.0, 0.0, 2.0, 0.0, 1.0)
    bi1 = ResourceBlockingInterval("INT_01", "BLK_01", ResourceCategory.TRACK_BLOCK, "TRN_01", 0.0, 19.0, decomposition=decomp1)
    bi2 = ResourceBlockingInterval("INT_02", "BLK_02", ResourceCategory.TRACK_BLOCK, "TRN_01", 10.0, 30.0, decomposition=decomp2)

    fig = create_seven_component_figure([bi1, bi2])

    assert fig.layout.xaxis.title.text == "Signalling Block Resource"
    assert fig.layout.yaxis.title.text == "Blocking Time [s]"
    assert len(fig.layout.xaxis.categoryarray) == 2
    assert "BLK_01" in fig.layout.xaxis.categoryarray
    assert "BLK_02" in fig.layout.xaxis.categoryarray


def test_axis_layout_stairway():
    """Test 1b: Blocking stairway chart has Block Resource on X and Time [s] on Y."""
    decomp1 = BlockingTimeDecomposition(1.0, 5.0, 10.0, 0.0, 2.0, 0.0, 1.0)
    decomp2 = BlockingTimeDecomposition(1.0, 4.0, 12.0, 0.0, 2.0, 0.0, 1.0)
    bi1 = ResourceBlockingInterval("INT_01", "BLK_01", ResourceCategory.TRACK_BLOCK, "TRN_01", 0.0, 19.0, decomposition=decomp1)
    bi2 = ResourceBlockingInterval("INT_02", "BLK_02", ResourceCategory.TRACK_BLOCK, "TRN_01", 10.0, 30.0, decomposition=decomp2)
    conf = ResourceConflict("C1", bi1, bi1, ConflictType.IDENTICAL_RESOURCE, 19.0, 0.0, 19.0, 0.0)

    hw_res = HeadwayResult(
        run_id="RUN_01",
        analysis_id="AN_01",
        scenario_id="BASELINE",
        running_direction=RunningDirection.FORWARD,
        headway_s=45.0,
        leader_service_id="SVC_01",
        follower_service_id="SVC_02",
        reference_point_id="REF_01",
        signalling_system="FIXED_BLOCK",
        headway_definition="TECHNICAL_MINIMUM",
        minimum_dispatch_headway_s=45.0,
        controlling_conflicts=[conf],
        blocking_intervals=[bi1, bi2],
    )

    fig = create_blocking_stairway_figure(hw_res)

    assert "Route Distance" in fig.layout.xaxis.title.text
    assert fig.layout.yaxis.title.text == "Time [s]"
    assert fig.layout.yaxis.autorange == "reversed"
    assert len(fig.data) >= 2
    assert len(fig.data[0].x) == 2


def test_axis_layout_platform_occupation():
    """Test 1c: Platform reservation timeline has Platform Track on X and Simulation Time [s] on Y."""
    p1 = PlatformOccupationRecord(
        train_id="TRN_01",
        station_id="STN_A",
        station_name="Alpha",
        platform_id="PLT_A1",
        track_id="TRK_01",
        link_id="LNK_01",
        arrival_time_s=10.0,
        dwell_start_time_s=20.0,
        dwell_end_time_s=50.0,
        departure_time_s=50.0,
        clearance_time_s=60.0,
        running_direction=RunningDirection.FORWARD,
    )
    p2 = PlatformOccupationRecord(
        train_id="TRN_01",
        station_id="STN_B",
        station_name="Beta",
        platform_id="PLT_B1",
        track_id="TRK_01",
        link_id="LNK_02",
        arrival_time_s=70.0,
        dwell_start_time_s=80.0,
        dwell_end_time_s=110.0,
        departure_time_s=110.0,
        clearance_time_s=120.0,
        running_direction=RunningDirection.FORWARD,
    )

    fig = create_platform_occupation_figure([p1, p2])

    assert fig.layout.xaxis.title.text == "Platform ID"
    assert fig.layout.yaxis.title.text == "Occupation Duration (s)"
    assert len(fig.layout.xaxis.categoryarray) == 2


def test_report_binding_from_loaded_excel_project():
    """Test 2a: Report data binding loads Rolling Stock and Infrastructure parameters from Project."""
    from pathlib import Path
    from headway.data.importer import ExcelImporter
    from headway.data.converter import convert_raw_to_canonical
    from headway.data.validation import ValidationReport
    from headway.reporting.report_assembly import ReportAssembler
    from headway.reporting.html_renderer import HtmlReportRenderer
    from headway.reporting.result_models import SimulationResultPackage

    ex_dir = Path("examples/05_comprehensive_line")
    importer = ExcelImporter()
    report = ValidationReport()

    raw_wbs = {}
    for f in sorted(ex_dir.glob("*.xlsx")):
        raw = importer.load_workbook(f, report)
        if raw:
            raw_wbs[raw.workbook_type] = raw

    project = convert_raw_to_canonical(raw_wbs)

    decomp = BlockingTimeDecomposition(1.0, 5.0, 10.0, 0.0, 2.0, 0.0, 1.0)
    bi = ResourceBlockingInterval("INT_01", "BLK_01", ResourceCategory.TRACK_BLOCK, "TRN_01", 0.0, 19.0, decomposition=decomp)
    hw = HeadwayResult(
        run_id="RUN_01",
        analysis_id="AN_01",
        scenario_id="SC_01",
        running_direction=RunningDirection.FORWARD,
        headway_s=60.0,
        leader_service_id="SVC_01",
        follower_service_id="SVC_02",
        reference_point_id="BLK_01",
        signalling_system="FIXED_BLOCK",
        headway_definition="TECHNICAL_MINIMUM",
        minimum_dispatch_headway_s=60.0,
        controlling_conflicts=[],
        blocking_intervals=[bi],
    )

    pkg = SimulationResultPackage(
        run_id="RUN_01",
        scenario_id="SC_01",
        running_direction=RunningDirection.FORWARD,
        headway_results={"PAIR_01": hw},
        blocking_intervals=[bi],
        trajectories={},
        effective_config_hash="hash1234567890",
        metadata={"project": project},
    )

    doc = ReportAssembler.assemble_report(pkg, project=project)

    # 1. Verify Rolling Stock Parameters match loaded Excel workbook
    rs = doc.rolling_stock
    assert rs is not None
    assert rs.train_type_id == "TRN_HSR"
    assert rs.description == "High Speed Passenger Train"
    assert rs.train_length_m == 200.0
    assert rs.tare_mass_t == 400.0
    assert rs.gross_mass_t == 450.0
    assert rs.max_speed_kmh == 200.0
    assert rs.max_tractive_effort_kn == 300.0
    assert rs.traction_power_kw == 8000.0
    assert rs.service_braking_deceleration_ms2 == 0.9
    assert rs.emergency_braking_deceleration_ms2 == 1.2
    assert rs.davis_a_n == 3500.0
    assert rs.davis_b_ns_per_m == 144.0
    assert rs.davis_c_ns2_per_m2 == 7.776
    assert len(rs.train_types) == 3

    # 2. Verify Infrastructure & Signalling Parameters match loaded Excel workbook
    infra = doc.infrastructure
    assert infra is not None
    assert infra.signalling_technology == "GENERIC_FIXED_BLOCK_ENGINEERING_MODEL"
    assert infra.aspect_model == "THREE_ASPECT"
    assert infra.default_overlap_m == 50.0
    assert infra.sighting_time_s == 8.0
    assert infra.route_setup_time_s == 3.0
    assert infra.resource_release_delay_s == 4.0
    assert infra.total_links == 18
    assert infra.total_blocks == 18
    assert infra.total_signals == 18
    assert infra.total_stations == 3
    assert infra.total_platforms == 8
    assert infra.total_tvs_sections == 4

    # 3. Verify HTML rendering contains actual loaded data, not fallback defaults
    html = HtmlReportRenderer.render(doc)
    assert "TRN_HSR" in html
    assert "High Speed Passenger Train" in html
    assert "GENERIC_FIXED_BLOCK_ENGINEERING_MODEL" in html
    assert "THREE_ASPECT" in html
    assert "Metro EMU 6-Car Standard" not in html


def test_report_binding_via_session_state_fallback(monkeypatch):
    """Test 2b: Report data binding falls back to session_state.current_project when metadata lacks it."""
    from pathlib import Path
    from headway.data.importer import ExcelImporter
    from headway.data.converter import convert_raw_to_canonical
    from headway.data.validation import ValidationReport
    from headway.reporting.report_assembly import ReportAssembler
    from headway.reporting.result_models import SimulationResultPackage
    from headway.ui.state import session_state

    ex_dir = Path("examples/05_comprehensive_line")
    importer = ExcelImporter()
    report = ValidationReport()

    raw_wbs = {}
    for f in sorted(ex_dir.glob("*.xlsx")):
        raw = importer.load_workbook(f, report)
        if raw:
            raw_wbs[raw.workbook_type] = raw

    project = convert_raw_to_canonical(raw_wbs)
    monkeypatch.setattr(session_state, "current_project", project)

    decomp = BlockingTimeDecomposition(1.0, 5.0, 10.0, 0.0, 2.0, 0.0, 1.0)
    bi = ResourceBlockingInterval("INT_01", "BLK_01", ResourceCategory.TRACK_BLOCK, "TRN_01", 0.0, 19.0, decomposition=decomp)
    hw = HeadwayResult(
        run_id="RUN_01",
        analysis_id="AN_01",
        scenario_id="SC_01",
        running_direction=RunningDirection.FORWARD,
        headway_s=60.0,
        leader_service_id="SVC_01",
        follower_service_id="SVC_02",
        reference_point_id="BLK_01",
        signalling_system="FIXED_BLOCK",
        headway_definition="TECHNICAL_MINIMUM",
        minimum_dispatch_headway_s=60.0,
        controlling_conflicts=[],
        blocking_intervals=[bi],
    )

    # Note: metadata has no "project" and project is not passed directly
    pkg = SimulationResultPackage(
        run_id="RUN_01",
        scenario_id="SC_01",
        running_direction=RunningDirection.FORWARD,
        headway_results={"PAIR_01": hw},
        blocking_intervals=[bi],
        trajectories={},
        effective_config_hash="hash1234567890",
        metadata={},
    )

    doc = ReportAssembler.assemble_report(pkg)

    assert doc.rolling_stock.train_type_id == "TRN_HSR"
    assert doc.infrastructure.signalling_technology == "GENERIC_FIXED_BLOCK_ENGINEERING_MODEL"
    assert doc.infrastructure.total_blocks == 18

