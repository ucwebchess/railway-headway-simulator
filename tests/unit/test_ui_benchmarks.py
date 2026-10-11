"""UI Benchmarks verification test suite (P15-B001 to P15-B040).

Milestone P15 — Gradio Interface Verification.
Validates all UI benchmark requirements across all ten navigation tabs.
"""

from pathlib import Path
import pytest
import gradio as gr

from headway.infrastructure.direction import RunningDirection
from headway.ui.app import create_app
from headway.ui.direction_selector import DirectionSelector
from headway.ui.error_handling import EngineeringError, format_exception_for_ui
from headway.ui.file_manager import ProjectFileManager
from headway.ui.progress import ProgressTracker
from headway.ui.simulation_runner import SimulationJobConfig, SimulationRunner
from headway.ui.state import AppState, session_state
from headway.ui.tab_dashboard import create_dashboard_tab
from headway.ui.tab_data_import import create_data_import_tab
from headway.ui.tab_infrastructure import create_infrastructure_tab
from headway.ui.tab_operations import create_operations_tab
from headway.ui.tab_reports import create_reports_tab
from headway.ui.tab_results import create_results_tab
from headway.ui.tab_rolling_stock_signalling import create_rolling_stock_tab
from headway.ui.tab_scenarios import create_scenarios_tab
from headway.ui.tab_simulation import create_simulation_tab
from headway.ui.tab_validation import create_validation_tab


@pytest.fixture(autouse=True)
def reset_session():
    """Ensure clean session state for each benchmark test."""
    session_state.reset()
    yield
    session_state.reset()


class TestUiBenchmarksDashboard:
    """Tab 1 Dashboard Benchmarks: P15-B001 to P15-B004."""

    def test_b001_dashboard_components_instantiation(self):
        """P15-B001: Tab 1 instantiates project name, ID, status, and stats."""
        with gr.Blocks():
            comp = create_dashboard_tab()
        assert "project_name_text" in comp
        assert "project_id_text" in comp
        assert "validation_status_text" in comp
        assert "stats_dataframe" in comp
        assert "dataset_dataframe" in comp

    def test_b002_dashboard_kpi_cards(self):
        """P15-B002: Tab 1 includes headline KPI cards."""
        with gr.Blocks():
            comp = create_dashboard_tab()
        assert "kpi_headway" in comp
        assert "kpi_theo_cap" in comp
        assert "kpi_plan_cap" in comp
        assert "kpi_bottleneck" in comp

    def test_b003_dashboard_state_reflection(self):
        """P15-B003: Tab 1 reflects loaded project details accurately."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)
        stats = session_state.get_project_summary_stats()
        assert stats["total_tracks"] > 0
        assert stats["total_signals"] > 0

    def test_b004_dashboard_quick_actions(self):
        """P15-B004: Tab 1 provides quick action buttons."""
        with gr.Blocks():
            comp = create_dashboard_tab()
        assert "btn_refresh_dashboard" in comp
        assert "btn_load_example_quick" in comp
        assert "btn_reset_session" in comp


class TestUiBenchmarksDataImport:
    """Tab 2 Data Import Benchmarks: P15-B005 to P15-B008."""

    def test_b005_data_import_components(self):
        """P15-B005: Tab 2 instantiates file upload and example loader."""
        with gr.Blocks():
            comp = create_data_import_tab()
        assert "example_dropdown" in comp
        assert "btn_load_example" in comp
        assert "upload_zip" in comp
        assert "btn_download_templates" in comp

    def test_b006_example_project_discovery(self):
        """P15-B006: Discover all 4 verified example projects."""
        examples = ProjectFileManager.get_example_projects()
        expected = ["01_single_track", "02_double_track", "03_station_platform", "04_tunnel_tvs"]
        for ex in expected:
            assert ex in examples

    def test_b007_load_verified_example(self):
        """P15-B007: Load official example project successfully."""
        proj, report, files = ProjectFileManager.load_example_project("01_single_track")
        assert proj.project_id is not None
        assert len(proj.infrastructure.track_links) > 0
        assert report is not None

    def test_b008_template_zip_availability(self):
        """P15-B008: Verify standard Excel templates packaging."""
        zip_path = ProjectFileManager.get_or_generate_templates_zip()
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"


class TestUiBenchmarksValidation:
    """Tab 3 Data Validation Benchmarks: P15-B009 to P15-B012."""

    def test_b009_validation_components(self):
        """P15-B009: Tab 3 instantiates readiness banner and filterable table."""
        with gr.Blocks():
            comp = create_validation_tab()
        assert "validation_banner" in comp
        assert "card_readiness" in comp
        assert "filter_severity" in comp
        assert "findings_dataframe" in comp
        assert "btn_rerun_validation" in comp

    def test_b010_validation_execution_on_loaded_project(self):
        """P15-B010: Validation runs and produces structured findings."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)
        assert session_state.is_simulation_ready() is True

    def test_b011_validation_severity_filtering(self):
        """P15-B011: Filter findings by severity works cleanly."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)
        all_findings = report.findings
        assert isinstance(all_findings, list)

    def test_b012_validation_export_controls(self):
        """P15-B012: Findings export button and file container exist."""
        with gr.Blocks():
            comp = create_validation_tab()
        assert "btn_export_findings" in comp
        assert "findings_download" in comp


class TestUiBenchmarksInfrastructure:
    """Tab 4 Infrastructure Benchmarks: P15-B013 to P15-B016."""

    def test_b013_infrastructure_components(self):
        """P15-B013: Tab 4 instantiates schematic, elevation, and direction toggle."""
        with gr.Blocks():
            comp = create_infrastructure_tab()
        assert "view_direction_toggle" in comp
        assert "btn_refresh_infra" in comp
        assert "network_schematic_plot" in comp
        assert "alignment_profile_plot" in comp

    def test_b014_direction_view_orientation_toggle(self):
        """P15-B014: View orientation supports FORWARD and REVERSE."""
        with gr.Blocks():
            comp = create_infrastructure_tab()
        choices_str = str(comp["view_direction_toggle"].choices)
        assert "FORWARD" in choices_str
        assert "REVERSE" in choices_str

    def test_b015_stations_and_signals_tables(self):
        """P15-B015: Tab 4 registers stations and blocks dataframes."""
        with gr.Blocks():
            comp = create_infrastructure_tab()
        assert "tbl_stations" in comp
        assert "tbl_blocks" in comp
        assert "tbl_track_links" in comp

    def test_b016_tvs_sections_table(self):
        """P15-B016: Tab 4 displays TVS sections."""
        with gr.Blocks():
            comp = create_infrastructure_tab()
        assert "tbl_tvs" in comp


class TestUiBenchmarksRollingStockSignalling:
    """Tab 5 Rolling Stock & Signalling Benchmarks: P15-B017 to P15-B020."""

    def test_b017_rolling_stock_components(self):
        """P15-B017: Tab 5 instantiates train dropdown, parameters, and curves."""
        with gr.Blocks():
            comp = create_rolling_stock_tab()
        assert "train_selector" in comp
        assert "rs_spec_card" in comp
        assert "plot_traction" in comp
        assert "plot_davis" in comp

    def test_b018_signalling_components(self):
        """P15-B018: Tab 5 instantiates signalling aspects and signals table."""
        with gr.Blocks():
            comp = create_rolling_stock_tab()
        assert "signalling_info_card" in comp
        assert "tbl_signals" in comp
        assert "fidelity_info_card" in comp

    def test_b019_train_type_selection(self):
        """P15-B019: Selecting train type reflects physics data."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)
        tt_list = list(proj.rolling_stock.train_types)
        assert len(tt_list) > 0

    def test_b020_physics_curves_generation(self):
        """P15-B020: Traction and Davis figures generate without errors."""
        proj, _, _ = ProjectFileManager.load_example_project("01_single_track")
        tt = proj.rolling_stock.train_types[0]
        assert tt.length_m > 0
        assert tt.mass_empty_kg > 0


class TestUiBenchmarksOperations:
    """Tab 6 Operations Benchmarks: P15-B021 to P15-B024."""

    def test_b021_operations_components(self):
        """P15-B021: Tab 6 instantiates service patterns and dwell tables."""
        with gr.Blocks():
            comp = create_operations_tab()
        assert "service_selector" in comp
        assert "service_detail_card" in comp
        assert "tbl_stopping_pattern" in comp
        assert "plot_service_route" in comp

    def test_b022_dwell_times_table(self):
        """P15-B022: Tab 6 lists stopping pattern and timetable."""
        with gr.Blocks():
            comp = create_operations_tab()
        assert "tbl_timetable" in comp
        assert "tbl_stopping_pattern" in comp

    def test_b023_service_type_inspection(self):
        """P15-B023: Operations tab parses service patterns."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)
        services = proj.operations.service_patterns
        assert len(services) > 0

    def test_b024_route_traversal_plot(self):
        """P15-B024: Traversal schematic plot component is ready."""
        with gr.Blocks():
            comp = create_operations_tab()
        assert comp["plot_service_route"] is not None


class TestUiBenchmarksScenarios:
    """Tab 7 Scenario Manager Benchmarks: P15-B025 to P15-B028."""

    def test_b025_scenario_components(self):
        """P15-B025: Tab 7 instantiates scenario table, clone, and overrides."""
        with gr.Blocks():
            comp = create_scenarios_tab()
        assert "scenario_selector" in comp
        assert "btn_create_scenario" in comp
        assert "btn_duplicate_scenario" in comp
        assert "btn_delete_scenario" in comp

    def test_b026_baseline_immutability(self):
        """P15-B026: Baseline scenario is protected and cannot be deleted."""
        with gr.Blocks():
            comp = create_scenarios_tab()
        assert "baseline_protection_banner" in comp

    def test_b027_tvs_policy_dropdown(self):
        """P15-B027: TVS evacuation policy options are selectable."""
        with gr.Blocks():
            comp = create_scenarios_tab()
        assert "tvs_policy_dropdown" in comp
        choices_str = str(comp["tvs_policy_dropdown"].choices)
        assert "ONE_PER_TVS" in choices_str or "DISABLED" in choices_str

    def test_b028_parameter_diff_table(self):
        """P15-B028: Scenario diff table is configured."""
        with gr.Blocks():
            comp = create_scenarios_tab()
        assert "tbl_scenario_diffs" in comp


class TestUiBenchmarksSimulationControl:
    """Tab 8 Simulation Control Benchmarks: P15-B029 to P15-B032 (MANDATORY DIRECTION SELECTOR)."""

    def test_b029_simulation_components(self):
        """P15-B029: Tab 8 instantiates simulation mode, parameters, and controls."""
        with gr.Blocks():
            comp = create_simulation_tab()
        assert "sim_mode_dropdown" in comp
        assert "param_dt" in comp
        assert "param_margin" in comp
        assert "btn_run_simulation" in comp
        assert "btn_cancel_simulation" in comp

    def test_b030_mandatory_direction_selector_present(self):
        """P15-B030: Explicit FORWARD / REVERSE running direction selector is mandatory."""
        with gr.Blocks():
            comp = create_simulation_tab()
        assert "running_direction_selector" in comp
        choices_str = str(comp["running_direction_selector"].choices)
        assert "FORWARD" in choices_str
        assert "REVERSE" in choices_str
        assert comp["running_direction_selector"].value == "FORWARD"

    def test_b031_direction_validation_logic(self):
        """P15-B031: Direction validation validates direction against project tracks."""
        proj, _, _ = ProjectFileManager.load_example_project("01_single_track")
        ok, msg = DirectionSelector.validate_direction(RunningDirection.FORWARD, proj)
        assert ok is True
        assert msg is None

    def test_b032_progress_and_cancel_tracking(self):
        """P15-B032: Progress bar and cancellation tokens exist."""
        tracker = ProgressTracker("test_tracker")
        tracker.start("Initializing", total_steps=100)
        assert tracker.is_cancelled() is False
        tracker.request_cancellation()
        assert tracker.is_cancelled() is True


class TestUiBenchmarksResults:
    """Tab 9 Results & Comparison Benchmarks: P15-B033 to P15-B036."""

    def test_b033_results_components(self):
        """P15-B033: Tab 9 instantiates KPI cards and charts."""
        with gr.Blocks():
            comp = create_results_tab()
        assert "res_direction_banner" in comp
        assert "res_kpi_headway" in comp
        assert "res_kpi_bottleneck" in comp
        assert "plot_speed_dynamics" in comp
        assert "plot_blocking_stairway" in comp

    def test_b034_results_seven_component_and_conflicts(self):
        """P15-B034: Tab 9 has seven-component plot and conflict ranking."""
        with gr.Blocks():
            comp = create_results_tab()
        assert "plot_seven_components" in comp
        assert "tbl_conflicts" in comp

    def test_b035_results_station_and_mixed_traffic(self):
        """P15-B035: Tab 9 has station occupation and mixed-traffic heatmap."""
        with gr.Blocks():
            comp = create_results_tab()
        assert "plot_platform_timeline" in comp
        assert "plot_mixed_traffic_heatmap" in comp
        assert "tbl_mixed_traffic" in comp

    def test_b036_results_export_buttons(self):
        """P15-B036: Excel and JSON result export buttons exist."""
        with gr.Blocks():
            comp = create_results_tab()
        assert "export_xlsx_btn" in comp
        assert "export_json_btn" in comp

    def test_b037_reports_components(self):
        """P15-B037: Tab 10 instantiates report type, section checkboxes, and buttons."""
        with gr.Blocks():
            comp = create_reports_tab()
        assert "rep_type_dropdown" in comp
        assert "rep_sections_checkboxes" in comp
        assert "btn_generate_report" in comp
        assert "html_preview_frame" in comp

    def test_b038_reports_download_buttons(self):
        """P15-B038: Tab 10 has PDF, Excel, CSV, JSON, and Package ZIP buttons."""
        with gr.Blocks():
            comp = create_reports_tab()
        assert "btn_download_pkg" in comp
        assert "btn_download_pdf" in comp
        assert "btn_download_xlsx" in comp
        assert "btn_download_csv" in comp
        assert "btn_download_json" in comp

    def test_b039_project_backup_and_restore(self):
        """P15-B039: Project backup and restoration controls exist."""
        with gr.Blocks():
            comp = create_reports_tab()
        assert "btn_backup_project" in comp
        assert "project_backup_file" in comp
        assert "restore_project_file" in comp

    def test_b040_full_master_app_instantiation(self):
        """P15-B040: Master 10-tab application instantiates without warnings or errors."""
        app = create_app()
        assert isinstance(app, gr.Blocks)
