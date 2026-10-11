"""Targeted regression test suite for Post-Release 1.0.1 fixes.

Covers:
- Defect 01: Action buttons audit, visibility, positioning, and click handler bindings.
- Defect 02: Interactive HTML report preview figure embedding.
- Defect 03: Report deliverables download workflow (PDF, HTML, Excel, CSV, JSON, ZIP package).
- Defect 04: ScenarioManager get_all_scenarios method and Excel workbook ingestion.
- Audits 1-4: Data import, Reports/Export, Cross-tab integration, Direction selector.
"""

from pathlib import Path
import tempfile
import zipfile
import gradio as gr
import pytest

from headway.core.configuration import AppConfig
from headway.infrastructure.direction import RunningDirection
from headway.reporting.html_renderer import HtmlReportRenderer
from headway.reporting.report_assembly import ReportAssembler, ReportSectionId, ReportType
from headway.reporting.report_config import ReportConfig
from headway.scenarios.scenario_manager import ScenarioManager
from headway.ui.app import create_app
from headway.ui.file_manager import FileManager
from headway.ui.state import AppState, session_state
from headway.ui.tab_dashboard import create_dashboard_tab
from headway.ui.tab_data_import import create_data_import_tab
from headway.ui.tab_infrastructure import create_infrastructure_tab
from headway.ui.tab_operations import create_operations_tab
from headway.ui.tab_reports import create_reports_tab
from headway.ui.tab_results import create_results_tab
from headway.ui.tab_rolling_stock_signalling import create_rolling_stock_signalling_tab
from headway.ui.tab_scenarios import create_scenarios_tab
from headway.ui.tab_simulation import create_simulation_tab
from tests.engineering.test_report_benchmarks import build_benchmark_package


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean session state before and after each test."""
    session_state.reset()
    yield
    session_state.reset()


@pytest.mark.regression
def test_defect_01_all_buttons_bound_and_no_unwired_buttons():
    """Defect 01: Verify all buttons across all tabs are visible and have click event handlers."""
    config = AppConfig()
    app = create_app(config)

    all_btns = []

    def walk(b):
        for c in getattr(b, "children", []):
            if isinstance(c, gr.Button):
                all_btns.append(c)
            walk(c)

    walk(app)

    assert len(all_btns) >= 29, f"Expected at least 29 buttons, found {len(all_btns)}"

    targets_clicked = set()
    for fn_obj in app.fns.values():
        for target_id, evt in fn_obj.targets:
            if evt == "click":
                targets_clicked.add(target_id)

    unbound = []
    for b in all_btns:
        b_id = getattr(b, "_id", None)
        if b_id not in targets_clicked:
            unbound.append(getattr(b, "value", "unnamed"))

    assert len(unbound) == 0, f"Found unwired buttons without click handlers: {unbound}"


@pytest.mark.regression
def test_defect_01_button_callbacks_execute_cleanly():
    """Defect 01: Verify that button callbacks run without raising schema/attribute errors."""
    session_state.load_example("01_single_track")
    assert session_state.current_project is not None

    with gr.Blocks() as app:
        create_dashboard_tab()
        create_infrastructure_tab()
        create_rolling_stock_signalling_tab()
        create_operations_tab()
        create_scenarios_tab()

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}

    # Dashboard refresh
    dash_res = fns["refresh_dashboard"]()
    assert dash_res[0] == session_state.project_name

    # Infrastructure refresh
    infra_res = fns["update_infra_view"]("FORWARD")
    assert len(infra_res[2]) > 0  # links table non-empty

    # Rolling stock refresh
    rs_res = fns["update_rs_view"]("TT_COMMUTER")
    assert rs_res[0] is not None

    # Operations refresh
    ops_res = fns["update_operations_view"](None)
    assert ops_res[0] is not None

    # Duplicate scenario
    dup_res = fns["handle_duplicate_scenario"]("BASELINE")
    assert "Duplicated" in dup_res[1]

    # Archive scenario
    arch_res = fns["handle_archive_scenario"]("BASELINE_COPY")
    assert "Archived" in arch_res[1]


@pytest.mark.regression
def test_defect_02_html_report_preview_figures_embedded():
    """Defect 02: Verify that HTML preview uses iframe srcdoc and embeds Plotly figure markup."""
    pkg = build_benchmark_package()
    session_state.latest_result_package = pkg

    with gr.Blocks() as app:
        create_reports_tab()

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}

    status_html, preview_html = fns["assemble_and_preview"](
        ReportType.DETAILED_ENGINEERING.value,
        "Regression Test Report",
        "Test Engineer",
        [ReportSectionId.SPEED_GRADIENT_CURVATURE.value, ReportSectionId.BLOCKING_STAIRWAY.value],
    )

    assert "Report Assembled" in status_html or "Success" in status_html
    assert "<iframe srcdoc=" in preview_html
    assert "sandbox=\"allow-scripts allow-same-origin\"" in preview_html
    assert "plotly-graph-div" in preview_html
    assert "cdn.plot.ly" in preview_html


@pytest.mark.regression
def test_defect_03_all_report_downloads_return_existing_nonempty_files():
    """Defect 03: Verify PDF, HTML, Excel, CSV ZIP, JSON, and Package ZIP return real files."""
    pkg = build_benchmark_package()
    session_state.latest_result_package = pkg

    with gr.Blocks() as app:
        create_reports_tab()

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}

    download_targets = [
        ("Complete Package", "download_complete_package", ".zip"),
        ("Formal PDF", "download_pdf", ".pdf"),
        ("Interactive HTML", "download_html", ".html"),
        ("Excel Assessment", "download_xlsx", ".xlsx"),
        ("CSV Archive", "download_csv_zip", ".zip"),
        ("JSON Results", "download_json", ".json"),
    ]

    for label, fn_name, ext in download_targets:
        update_result, status = fns[fn_name]()
        file_val = update_result.get("value") if isinstance(update_result, dict) else getattr(update_result, "value", None)
        assert file_val is not None, f"{label} returned None path"
        p = Path(file_val)
        assert p.exists(), f"{label} output file does not exist: {p}"
        assert p.suffix.lower() == ext, f"{label} expected {ext}, got {p.suffix}"
        assert p.stat().st_size > 0, f"{label} file is empty (0 bytes)"


@pytest.mark.regression
def test_defect_04_scenariomanager_get_all_scenarios_and_excel_ingestion():
    """Defect 04: Verify get_all_scenarios alias and clean Excel workbook ingestion."""
    session_state.load_example("01_single_track")
    mgr = session_state.scenario_manager
    assert mgr is not None
    assert hasattr(mgr, "get_all_scenarios")
    all_scns = mgr.get_all_scenarios()
    assert len(all_scns) == 1
    assert all_scns[0].scenario_id == "BASELINE"

    # Test template workbooks ingestion via tab_data_import
    zip_p = FileManager.get_or_generate_templates_zip()
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(zip_p) as zf:
            zf.extractall(td)
        excel_paths = [str(p) for p in Path(td).glob("*.xlsx")]
        assert len(excel_paths) == 6

        with gr.Blocks() as app:
            create_data_import_tab()

        fn_import = [fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__") and fn_obj.fn.__name__ == "handle_import_excels"][0]
        status_html, logs = fn_import(excel_paths)

        assert "Successfully" in status_html or "assembled" in status_html
        assert "ERR_SIM_FAIL" not in status_html
        assert "'ScenarioManager' object has no attribute 'get_all_scenarios'" not in status_html


@pytest.mark.regression
def test_audit_02_report_package_zip_manifest_and_members():
    """Audit 02: Verify that report package ZIP contains all expected deliverable members."""
    pkg = build_benchmark_package()
    session_state.latest_result_package = pkg

    with gr.Blocks() as app:
        create_reports_tab()

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}
    update_res, _ = fns["download_complete_package"]()
    zip_path = Path(update_res["value"] if isinstance(update_res, dict) else update_res.value)

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        assert any(m.endswith(".html") for m in members)
        assert any(m.endswith(".pdf") for m in members)
        assert any(m.endswith(".xlsx") for m in members)
        assert any(m.endswith(".json") for m in members)
        assert any("manifest.json" in m.lower() for m in members)


@pytest.mark.regression
def test_audit_03_and_04_cross_tab_and_direction_propagation():
    """Audit 03 & 04: Verify direction selector and cross-tab data flow."""
    session_state.load_example("01_single_track")

    with gr.Blocks() as app:
        sim_comp = create_simulation_tab()
        res_comp = create_results_tab()

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}

    # Test reverse running direction
    sim_res = fns["handle_run_simulation"]("REVERSE", "DETERMINISTIC", 0.1, 1800.0, 180.0, 10)
    assert sim_res[0] == 100.0
    assert session_state.latest_result_package is not None
    assert session_state.latest_result_package.running_direction == RunningDirection.REVERSE

    # Results tab export handlers work with latest results
    xlsx_res = fns["export_excel_results"]()
    xlsx_path = Path(xlsx_res["value"] if isinstance(xlsx_res, dict) else xlsx_res.value)
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 0

    json_res = fns["export_json_results"]()
    json_path = Path(json_res["value"] if isinstance(json_res, dict) else json_res.value)
    assert json_path.exists() and json_path.stat().st_size > 0
