"""Targeted regression test suite for Post-Release 1.0.1 fixes.

Covers:
- Defect 01: Action buttons audit, visibility, positioning, and click handler bindings.
- Defect 02: Interactive HTML report preview figure embedding.
- Defect 03: Report deliverables download workflow (PDF, HTML, Excel, CSV, JSON, ZIP package).
- Defect 04: ScenarioManager get_all_scenarios method and Excel workbook ingestion.
- Audits 1-4: Data import, Reports/Export, Cross-tab integration, Direction selector.
"""

from pathlib import Path
import re
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
from tests.corrected_variants import patch_examples_with_corrected_variants
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
    assert "Plotly" in preview_html


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
        if "base64," in str(file_val):
            # Verify base64 data URI structure
            assert "data:" in file_val and ";base64," in file_val, f"{label} missing data URI"
            m = re.search(r'download="([^"]+)"', str(file_val))
            assert m is not None, f"{label} HTML missing download attribute"
            p = Path(session_state.reports_dir) / m.group(1)
        else:
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
    val = update_res["value"] if isinstance(update_res, dict) else update_res.value
    if "base64," in str(val):
        m = re.search(r'download="([^"]+)"', str(val))
        zip_path = Path(session_state.reports_dir) / m.group(1) if m else Path(val)
    else:
        zip_path = Path(val)

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

    # v1.11.2 (literal strict): 01_single_track fails pre-simulation block-geometry
    # validation (BLK_01: length 1900 m vs entry->exit span 2000 m). The simulation tab
    # must surface the named error for BOTH directions instead of producing results.
    for direction in ("REVERSE", "FORWARD"):
        session_state.latest_result_package = None
        sim_res = fns["handle_run_simulation"](direction, "DETERMINISTIC", 0.1, 1800.0, 180.0, 10)
        assert sim_res[0] == 0.0
        assert sim_res[1] == "Failed"
        assert "ERR_BLOCK_GEOMETRY_MISMATCH" in sim_res[3]
        assert "BLK_01" in sim_res[3]
        assert session_state.latest_result_package is None



@pytest.mark.regression
@pytest.mark.parametrize("direction", ["REVERSE", "FORWARD"])
def test_audit_03_and_04_cross_tab_and_direction_propagation_on_corrected_variant(direction, monkeypatch):
    """Audit 03 & 04 (v1.11.1 body): direction selector propagation and the Results-tab
    XLSX / JSON export handlers with real results, in BOTH directions.

    v1.11.2: the UI loads example 01 by name, so the loader is routed to the corrected
    in-memory 01 variant (BLK_01 extended to its exit signal; tests/corrected_variants.py).
    The shipped 01 raising ERR_BLOCK_GEOMETRY_MISMATCH in the UI is asserted by
    test_audit_03_and_04_cross_tab_and_direction_propagation above.
    """
    patch_examples_with_corrected_variants(monkeypatch)
    ok, msg = session_state.load_example("01_single_track")
    assert ok, msg  # load_example swallows exceptions; never let a failed load pass silently
    session_state.latest_result_package = None

    with gr.Blocks() as app:
        sim_comp = create_simulation_tab()  # noqa: F841
        res_comp = create_results_tab()  # noqa: F841

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}

    sim_res = fns["handle_run_simulation"](direction, "DETERMINISTIC", 0.1, 1800.0, 180.0, 10)
    assert sim_res[0] == 100.0, sim_res
    assert session_state.latest_result_package is not None
    assert session_state.latest_result_package.running_direction == RunningDirection[direction]

    # Results tab export handlers work with latest results
    xlsx_res = fns["export_excel_results"]()
    x_val = xlsx_res["value"] if isinstance(xlsx_res, dict) else xlsx_res.value
    if "base64," in str(x_val):
        m_x = re.search(r'download="([^"]+)"', str(x_val))
        xlsx_path = Path(session_state.reports_dir) / m_x.group(1) if m_x else Path(x_val)
    else:
        xlsx_path = Path(x_val)
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 0

    json_res = fns["export_json_results"]()
    j_val = json_res["value"] if isinstance(json_res, dict) else json_res.value
    if "base64," in str(j_val):
        m_j = re.search(r'download="([^"]+)"', str(j_val))
        json_path = Path(session_state.reports_dir) / m_j.group(1) if m_j else Path(j_val)
    else:
        json_path = Path(j_val)
    assert json_path.exists() and json_path.stat().st_size > 0


@pytest.mark.regression
def test_canonical_models_static_field_verification():
    """Verify that canonical Pydantic models contain the exact field names expected by UI callbacks."""
    from headway.data.canonical import AnalysisModel, TVSSection, TrackLink

    # Verify AnalysisModel.analyses exists and configs does not
    assert "analyses" in AnalysisModel.model_fields
    assert "configs" not in AnalysisModel.model_fields

    # Verify TVSSection.max_train_occupancy exists and max_occupancy does not
    assert "max_train_occupancy" in TVSSection.model_fields
    assert "max_occupancy" not in TVSSection.model_fields

    # Verify TrackLink.track_id exists and route_id does not
    assert "track_id" in TrackLink.model_fields
    assert "route_id" not in TrackLink.model_fields


@pytest.mark.regression
def test_static_ast_audit_zero_mismatches_in_ui_callbacks():
    """Statically verify every canonical attribute access across all src/headway/ui/ files."""
    import ast
    import inspect
    import headway.data.canonical as cm

    canonical_classes = {}
    for name, obj in inspect.getmembers(cm, inspect.isclass):
        if hasattr(obj, "model_fields"):
            canonical_classes[name] = set(obj.model_fields.keys()) | set(a for a in dir(obj) if not a.startswith("_"))

    ui_dir = Path("src/headway/ui")
    mismatches = []

    class ScopeVisitor(ast.NodeVisitor):
        def __init__(self, filename: str):
            self.filename = filename
            self.type_env = {
                "current_project": "CanonicalProject",
                "project": "CanonicalProject",
                "proj": "CanonicalProject",
                "infra": "InfrastructureModel",
                "infrastructure": "InfrastructureModel",
                "rs": "RollingStockModel",
                "rolling_stock": "RollingStockModel",
                "sig": "SignallingModel",
                "signalling": "SignallingModel",
                "sig_sys": "SignallingSystem",
                "ops": "OperationsModel",
                "operations": "OperationsModel",
                "cur_tt": "TrainType",
                "train_type": "TrainType",
                "cur_svc": "ServicePattern",
                "service_pattern": "ServicePattern",
            }

        def visit_Assign(self, node):
            rhs_type = None
            if isinstance(node.value, ast.Attribute):
                if isinstance(node.value.value, ast.Name):
                    base_var = node.value.value.id
                    attr = node.value.attr
                    base_type = self.type_env.get(base_var)
                    if base_type == "CanonicalProject":
                        if attr == "infrastructure": rhs_type = "InfrastructureModel"
                        elif attr == "rolling_stock": rhs_type = "RollingStockModel"
                        elif attr == "signalling": rhs_type = "SignallingModel"
                        elif attr == "operations": rhs_type = "OperationsModel"
                        elif attr == "analysis": rhs_type = "AnalysisModel"
                    elif base_type == "SignallingModel" and attr == "system":
                        rhs_type = "SignallingSystem"
                elif isinstance(node.value.value, ast.Attribute):
                    if node.value.value.attr in ("current_project", "project"):
                        if node.value.attr == "infrastructure": rhs_type = "InfrastructureModel"
                        elif node.value.attr == "rolling_stock": rhs_type = "RollingStockModel"
                        elif node.value.attr == "signalling": rhs_type = "SignallingModel"
                        elif node.value.attr == "operations": rhs_type = "OperationsModel"
            elif isinstance(node.value, ast.Name):
                rhs_type = self.type_env.get(node.value.id)

            for target in node.targets:
                if isinstance(target, ast.Name) and rhs_type:
                    self.type_env[target.id] = rhs_type
            self.generic_visit(node)

        def visit_For(self, node):
            elem_type = None
            iter_node = node.iter
            if isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name) and iter_node.func.id == "list":
                if iter_node.args:
                    iter_node = iter_node.args[0]

            if isinstance(iter_node, ast.Attribute):
                attr = iter_node.attr
                if attr == "tracks": elem_type = "Track"
                elif attr == "track_links": elem_type = "TrackLink"
                elif attr == "stations": elem_type = "Station"
                elif attr == "platforms": elem_type = "Platform"
                elif attr == "tunnels": elem_type = "Tunnel"
                elif attr == "tvs_sections": elem_type = "TVSSection"
                elif attr == "train_types": elem_type = "TrainType"
                elif attr == "signals": elem_type = "Signal"
                elif attr == "blocks": elem_type = "SignallingBlock"
                elif attr == "service_patterns": elem_type = "ServicePattern"
                elif attr == "stops": elem_type = "StationStop"
                elif attr == "link_intervals": elem_type = "ResourceInterval"
            elif isinstance(iter_node, ast.Name):
                if iter_node.id in ("ordered_links", "links"): elem_type = "TrackLink"
                elif iter_node.id in ("tt_names", "train_types"): elem_type = "TrainType"
                elif iter_node.id in ("svc_list", "service_patterns"): elem_type = "ServicePattern"

            if isinstance(node.target, ast.Name) and elem_type:
                self.type_env[node.target.id] = elem_type
            self.generic_visit(node)

        def visit_Attribute(self, node):
            obj_type = None
            if isinstance(node.value, ast.Name):
                obj_name = node.value.id
                obj_type = self.type_env.get(obj_name)
            elif isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name):
                p_type = self.type_env.get(node.value.value.id)
                if p_type == "CanonicalProject":
                    if node.value.attr == "infrastructure": obj_type = "InfrastructureModel"
                    elif node.value.attr == "rolling_stock": obj_type = "RollingStockModel"
                    elif node.value.attr == "signalling": obj_type = "SignallingModel"
                    elif node.value.attr == "operations": obj_type = "OperationsModel"
                    elif node.value.attr == "analysis": obj_type = "AnalysisModel"

            if obj_type and obj_type in canonical_classes:
                attr_name = node.attr
                if attr_name not in canonical_classes[obj_type]:
                    mismatches.append(f"{self.filename}:{node.lineno} {obj_type}.{attr_name}")
            self.generic_visit(node)

    for p in sorted(ui_dir.glob("*.py")):
        tree = ast.parse(p.read_text(), filename=str(p))
        visitor = ScopeVisitor(p.name)
        visitor.visit(tree)

    assert len(mismatches) == 0, f"Found attribute mismatches: {mismatches}"


@pytest.mark.regression
def test_affected_ui_handlers_execute_without_attribute_error():
    """Verify runtime execution of handlers affected by the 3 fatal fixes."""
    from headway.data.canonical import ResourceInterval, TVSSection
    from headway.ui.direction_selector import DirectionSelector

    session_state.load_example("01_single_track")
    assert session_state.current_project is not None

    with gr.Blocks() as app:
        create_data_import_tab()
        create_infrastructure_tab()

    fns = {fn_obj.fn.__name__: fn_obj.fn for fn_obj in app.fns.values() if hasattr(fn_obj.fn, "__name__")}

    # Fix A1 verification: validate_direction with route_id (checks TrackLink.track_id)
    is_valid, err_msg = DirectionSelector.validate_direction(
        direction="FORWARD",
        project=session_state.current_project,
        route_id="TRK_01",
    )
    assert is_valid is True
    assert err_msg is None

    # Fix A2 verification: handle_load_example (exercises AnalysisModel.analyses)
    status_html, log_rows = fns["handle_load_example"]("01_single_track")
    assert "Successfully" in status_html
    assert any("Headway Analysis" in row[0] for row in log_rows)

    # Fix A3 verification: update_infra_view on project with TVS sections (exercises TVSSection.max_train_occupancy)
    tvs = TVSSection(
        tvs_id="TVS_REGRESSION_01",
        tunnel_id="TUN_01",
        track_id="TRK_01",
        link_intervals=[ResourceInterval(link_id="TL_01", start_offset_m=0.0, end_offset_m=500.0)],
        max_train_occupancy=2,
        release_delay_s=25.0,
    )
    session_state.current_project.infrastructure.tvs_sections.append(tvs)
    infra_res = fns["update_infra_view"]("FORWARD")
    tvs_table = infra_res[5]
    assert len(tvs_table) == 1
    assert tvs_table[0][0] == "TVS_REGRESSION_01"
    assert tvs_table[0][4] == 2  # max_train_occupancy value correctly read

