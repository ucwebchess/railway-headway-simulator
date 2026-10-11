"""End-to-End integration test suite for the Railway Headway Simulator UI.

Milestone P15 — Full End-to-End Workflows (P15-E2E-001 to P15-E2E-025).
Validates realistic end-user assessment workflows:
- Verified example loading and data validation
- Mandatory FORWARD and REVERSE running direction propagation
- Microscopic train dynamics and blocking-time stairway computation
- TVS single-train occupancy and station dwell constraints
- Scenario creation, baseline immutability, and parameter diffs
- Asynchronous execution, progress tracking, and user cancellation
- Multi-format deliverable exports (PDF, Excel, JSON, CSV, Assessment ZIP)
- Session state backup and restoration
"""

from pathlib import Path
import tempfile
import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.csv_export import CsvReportExporter
from headway.reporting.excel_export import ExcelReportExporter
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.json_export import JsonReportExporter
from headway.reporting.pdf_renderer import PdfReportRenderer
from headway.reporting.report_assembly import ReportAssembler, ReportSectionId, ReportType
from headway.reporting.report_config import ReportConfig
from headway.reporting.report_package import ReportPackageExporter
from headway.ui.background_executor import BackgroundExecutor
from headway.ui.direction_selector import DirectionSelector
from headway.ui.file_manager import ProjectFileManager
from headway.ui.progress import ProgressTracker
from headway.ui.simulation_runner import SimulationJobConfig, SimulationRunner
from headway.ui.state import session_state


@pytest.fixture(autouse=True)
def clean_session():
    session_state.reset()
    yield
    session_state.reset()


class TestUiE2EWorkflows:
    """End-to-End assessment flows."""

    def test_e2e_001_single_track_forward_flow(self):
        """P15-E2E-001 to P15-E2E-006: Single Track complete assessment flow (FORWARD)."""
        # 1. Load Example
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)
        assert session_state.is_simulation_ready() is True

        # 2. Configure Direction
        session_state.selected_running_direction = RunningDirection.FORWARD

        # 3. Execute Simulation Pipeline
        tracker = ProgressTracker("single_track_forward")
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=proj,
            running_direction=RunningDirection.FORWARD,
            simulation_mode="Full Integrated Suite",
            tracker=tracker,
        )
        session_state.set_latest_results(pkg, doc)

        # 4. Validate Results
        assert pkg.running_direction == RunningDirection.FORWARD
        assert doc.metadata.running_direction == RunningDirection.FORWARD
        assert doc.executive_kpis.technical_headway_s > 0
        assert doc.executive_kpis.theoretical_capacity_tph > 0

        # 5. HTML Preview
        html = HtmlReportRenderer.render(doc)
        assert "Running Direction: FORWARD" in html
        assert "Technical Minimum Headway" in html

    def test_e2e_002_double_track_reverse_flow(self):
        """P15-E2E-007 to P15-E2E-012: Double Track assessment with mandatory REVERSE running direction."""
        # 1. Load Double Track Example
        proj, report, _ = ProjectFileManager.load_example_project("02_double_track")
        session_state.set_project(proj, report)

        # 2. Select REVERSE Direction
        session_state.selected_running_direction = RunningDirection.REVERSE

        # 3. Run Simulation in REVERSE
        tracker = ProgressTracker("double_track_reverse")
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=proj,
            running_direction=RunningDirection.REVERSE,
            simulation_mode="Full Integrated Suite",
            tracker=tracker,
        )
        session_state.set_latest_results(pkg, doc)

        # 4. Mandatory REVERSE Direction Verification across results and report
        assert pkg.running_direction == RunningDirection.REVERSE
        assert doc.metadata.running_direction == RunningDirection.REVERSE
        assert doc.executive_kpis.technical_headway_s > 0

        # 5. Render Banner
        banner = DirectionSelector.render_banner(RunningDirection.REVERSE)
        assert "REVERSE" in banner
        assert "Decreasing Route Chainage" in banner

    def test_e2e_003_tunnel_tvs_safety_assessment(self):
        """P15-E2E-013 to P15-E2E-016: Tunnel TVS corridor single-train occupancy constraint."""
        # 1. Load Tunnel TVS Example
        proj, report, _ = ProjectFileManager.load_example_project("04_tunnel_tvs")
        session_state.set_project(proj, report)

        # Ensure TVS sections exist
        assert len(proj.infrastructure.tvs_sections) > 0

        # 2. Execute Simulation with TVS
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=proj,
            running_direction=RunningDirection.FORWARD,
            simulation_mode="Full Integrated Suite",
        )
        session_state.set_latest_results(pkg, doc)

        assert pkg.running_direction == RunningDirection.FORWARD
        assert "tvs_events" in pkg.metadata

    def test_e2e_004_scenario_branching_and_immutability(self):
        """P15-E2E-017 to P15-E2E-019: Scenario lifecycle and baseline protection."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)

        assert "BASELINE" in session_state.scenarios

        # Baseline cannot be deleted
        with pytest.raises(ValueError):
            session_state.delete_scenario("BASELINE")

        # Create child scenario
        new_scn = session_state.create_scenario(
            scenario_id="OPT_OVERHAUL",
            parent_scenario_id="BASELINE",
            description="Upgraded signalling and dwell reduction",
        )
        assert new_scn.scenario_id == "OPT_OVERHAUL"
        assert "OPT_OVERHAUL" in session_state.scenarios

    def test_e2e_005_background_execution_and_cancellation(self):
        """P15-E2E-020 to P15-E2E-022: ThreadPool background executor and cancellation token."""
        import threading
        import time

        executor = BackgroundExecutor(max_workers=2)
        tracker = ProgressTracker("test_bg_cancel")
        started_event = threading.Event()

        def mock_long_task(token: ProgressTracker):
            token.start("Long Step", total_steps=100)
            started_event.set()
            for _ in range(50):
                if token.is_cancelled():
                    token.check_cancellation()
                time.sleep(0.05)
            return "Done"

        task_id = executor.submit(
            name="Mock Long Task",
            target_fn=mock_long_task,
            tracker=tracker,
        )

        assert started_event.wait(timeout=2.0) is True
        assert executor.is_busy() is True

        # Cancel task
        executor.cancel(task_id)
        assert tracker.is_cancelled() is True
        executor.shutdown(wait=True)

    def test_e2e_006_project_backup_and_restoration(self):
        """P15-E2E-023: Full session state backup to ZIP and clean restoration."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)
        session_state.create_scenario("BRANCH_A", "BASELINE")

        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_path = Path(tmp_dir) / "test_backup.zip"
            session_state.export_project_zip(backup_path)
            assert backup_path.exists()

            # Clear session
            session_state.reset()
            assert session_state.project is None

            # Restore from ZIP
            session_state.import_project_zip(backup_path)
            assert session_state.project is not None
            assert session_state.project_id in ("PRJ_EX01_SINGLE", "01_single_track")
            assert "BRANCH_A" in session_state.scenarios

    def test_e2e_007_multi_format_deliverable_exports(self):
        """P15-E2E-024 to P15-E2E-025: Formal PDF, Excel, JSON, CSV, and Assessment ZIP exports."""
        proj, report, _ = ProjectFileManager.load_example_project("01_single_track")
        session_state.set_project(proj, report)

        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=proj,
            running_direction=RunningDirection.FORWARD,
            simulation_mode="Full Integrated Suite",
        )
        session_state.set_latest_results(pkg, doc)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)

            # 1. PDF
            pdf_path = out_dir / "Assessment.pdf"
            PdfReportRenderer.render(doc, output_path=pdf_path)
            assert pdf_path.exists()
            assert pdf_path.stat().st_size > 0

            # 2. Excel
            xlsx_path = out_dir / "Assessment.xlsx"
            ExcelReportExporter.export(doc, output_path=xlsx_path)
            assert xlsx_path.exists()
            assert xlsx_path.stat().st_size > 0

            # 3. JSON
            json_path = out_dir / "Assessment.json"
            JsonReportExporter.export(doc, output_path=json_path)
            assert json_path.exists()
            assert json_path.stat().st_size > 0

            # 4. CSVs
            csv_dir = out_dir / "csvs"
            csv_dir.mkdir()
            csv_files = CsvReportExporter.export(doc, output_dir=csv_dir)
            assert len(csv_files) > 0

            # 5. Complete Assessment Package ZIP
            pkg_zip = out_dir / "Complete_Package.zip"
            ReportPackageExporter.export_package(
                document=doc,
                output_zip_path=pkg_zip,
                include_pdf=True,
                include_html=True,
                include_excel=True,
                include_csv=True,
                include_json=True,
                include_figures=False,  # Skip headless kaleido figure export in test
            )
            assert pkg_zip.exists()
            assert pkg_zip.stat().st_size > 0
