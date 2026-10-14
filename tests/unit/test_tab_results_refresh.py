"""Regression tests for Tab 9 Results view refresh handler.

Tests Defect 2 resolution:
- Completed run: all 4 KPIs + performance factor populated with valid values, charts non-empty.
- Automatic ReportDocument assembly when latest_report_doc is None but package exists.
- Empty state: clean message without exceptions or Gradio error badges.
- Output component count matches registered outputs (20 items).
"""

import pytest
import gradio as gr
import plotly.graph_objects as go

from headway.ui.state import session_state
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner
from headway.ui.tab_results import create_results_tab


@pytest.fixture(autouse=True)
def reset_session():
    """Ensure clean session state for each test."""
    session_state.reset()
    yield
    session_state.reset()


def _get_refresh_fn(demo: gr.Blocks):
    """Extracts the refresh_results_view function registered in the Blocks demo."""
    for fn_idx, block_fn in demo.fns.items():
        if block_fn.fn.__name__ == "refresh_results_view":
            return block_fn
    raise ValueError("refresh_results_view handler not found in demo.fns")


class TestTabResultsRefreshHandler:
    """Regression test suite for Tab 9 refresh button callback."""

    def test_refresh_results_completed_run_populates_all_kpis_and_charts(self):
        """Clicking Refresh after simulation populates all 4 KPIs, perf factor, and charts."""
        proj, rep, _ = FileManager.load_example_project("01_single_track")
        pkg, doc = SimulationRunner.run_simulation_pipeline(proj)

        session_state.latest_result_package = pkg
        # Explicitly set latest_report_doc to None to test automatic assembly
        session_state.latest_report_doc = None

        with gr.Blocks() as demo:
            components = create_results_tab()

        block_fn = _get_refresh_fn(demo)
        assert len(block_fn.outputs) == 20, "Tab 9 must register exactly 20 outputs."

        # Execute refresh handler
        result = block_fn.fn()

        # 1. Output length must match exactly to prevent Gradio error badges
        assert len(result) == len(block_fn.outputs) == 20

        # Unpack result elements
        (
            banner, k_hw, k_theo, k_plan, k_perf, k_bot,
            fig_speed, fig_stair, fig_seven, tbl_conf,
            fig_plat, fig_mt, tbl_mt,
            fig_td, fig_tvs,
            fig_sens, fig_stoch,
            fig_cmp, fig_mig, tbl_cmp,
        ) = result

        # 2. Executive KPI cards must be populated with non-'Not Available' values
        assert "Not Available" not in k_hw, f"k_hw should be populated: {k_hw}"
        assert f"{pkg.headway_results['METRO_LEADER->METRO_FOLLOWER'].headway_s:.1f} s" in k_hw
        assert "Not Available" not in k_theo, f"k_theo should be populated: {k_theo}"
        assert "tph" in k_theo
        assert "Not Available" not in k_plan, f"k_plan should be populated: {k_plan}"
        assert "Not Available" not in k_perf, f"k_perf should be populated: {k_perf}"
        assert "100%" in k_perf
        assert "Not Available" not in k_bot, f"k_bot should be populated: {k_bot}"

        # 3. Report document was automatically assembled and saved in session state
        assert session_state.latest_report_doc is not None
        assert session_state.latest_report_doc.executive_kpis.technical_headway_s > 0.0

        # 4. Core chart figures must be non-empty Plotly figures with data
        assert isinstance(fig_speed, go.Figure)
        assert len(fig_speed.data) > 0, "Speed-distance chart must contain traces"
        assert isinstance(fig_stair, go.Figure)
        assert len(fig_stair.data) > 0, "Blocking stairway chart must contain traces"
        assert isinstance(fig_seven, go.Figure)
        assert len(fig_seven.data) > 0, "Seven-component chart must contain traces"

    def test_refresh_results_empty_state_clean_message_no_exceptions(self):
        """When no simulation has run, refresh returns clear guidance with 0 exceptions."""
        session_state.latest_result_package = None
        session_state.latest_report_doc = None

        with gr.Blocks() as demo:
            components = create_results_tab()

        block_fn = _get_refresh_fn(demo)
        result = block_fn.fn()

        # Must return exactly 20 elements to avoid Gradio output length mismatch
        assert len(result) == 20

        k_hw = result[1]
        k_perf = result[4]

        # Assert clear informative guidance message
        expected_msg = "No simulation results available. Run a simulation in Tab 8 first."
        assert expected_msg in k_hw
        assert expected_msg in k_perf

    def test_refresh_results_with_derated_performance_factor(self):
        """Results tab displays derated performance factor and updated headway."""
        proj, rep, _ = FileManager.load_example_project("01_single_track")
        pkg, doc = SimulationRunner.run_simulation_pipeline(
            project=proj,
            performance_factor=0.75,
        )

        session_state.latest_result_package = pkg
        session_state.latest_report_doc = doc

        with gr.Blocks() as demo:
            components = create_results_tab()

        block_fn = _get_refresh_fn(demo)
        result = block_fn.fn()

        k_perf = result[4]
        assert "75%" in k_perf
        assert "analysis" in k_perf
