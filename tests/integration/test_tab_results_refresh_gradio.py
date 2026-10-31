"""Integration tests for Tab 9 Results view refresh handler in a real Gradio Blocks context.

Satisfies RHS-CORRECTION-V1.3.0-005 (Tasks 6.1, 6.2, 6.3):
- Exercises the Tab 9 refresh callback through Gradio Blocks event binding.
- Asserts that no exception is raised and return tuple matches registered outputs (20).
- Verifies executive KPI card contents after completed simulation.
- Verifies clean guidance message on empty session state.
- Verifies derated performance factor display (e.g. 50%).
"""

import asyncio
import pytest
import gradio as gr

from headway.ui.state import session_state
from headway.ui.tab_results import create_results_tab
from tests.block_geometry_expectations import load_and_assert_pipeline_raises
from tests.corrected_variants import load_corrected_variant
from headway.ui.simulation_runner import SimulationRunner


@pytest.fixture(autouse=True)
def reset_session():
    """Ensure clean session state before and after each test."""
    session_state.reset()
    yield
    session_state.reset()


def _find_refresh_block_fn(demo: gr.Blocks):
    """Locate the registered BlockFunction for refresh_results_view in the Gradio demo."""
    for fn_idx, block_fn in demo.fns.items():
        if block_fn.fn.__name__ == "refresh_results_view":
            return fn_idx, block_fn
    raise ValueError("refresh_results_view block function not found in demo.fns")


def test_tab_results_refresh_completed_run_gradio_blocks():
    """Task 6.1: Run refresh callback through real Gradio Blocks context with completed simulation.

    v1.11.2 (literal strict): 01_single_track fails pre-simulation block-geometry
    validation, so the original scenario cannot run on the unmodified shipped example.
    The test now asserts the documented error (tests/block_geometry_expectations.py)
    in FORWARD and REVERSE.
    """
    load_and_assert_pipeline_raises("01_single_track")

def test_tab_results_refresh_completed_run_gradio_blocks_on_corrected_variant():
    """Task 6.1: Run refresh callback through real Gradio Blocks context with completed simulation."""
    # v1.11.2: runs on the corrected in-memory variant (tests/corrected_variants.py); the shipped example raises a named ERR_* (tests/unit/test_v1112_bidirectional_integrity.py).
    # 1. Populate session state with completed simulation
    proj, report, _ = load_corrected_variant("01_single_track")
    assert report.is_simulation_ready

    pkg, doc = SimulationRunner.run_simulation_pipeline(proj)
    session_state.latest_result_package = pkg
    # Set latest_report_doc to None to test dynamic assembly fallback
    session_state.latest_report_doc = None

    # 2. Build Tab 9 component tree inside a real Gradio Blocks context
    with gr.Blocks() as demo:
        components = create_results_tab()

    btn = components["btn_refresh_results"]
    assert btn is not None

    fn_idx, block_fn = _find_refresh_block_fn(demo)
    expected_outputs_count = len(block_fn.outputs)
    assert expected_outputs_count == 20, f"Expected 20 outputs, got {expected_outputs_count}"

    # 3. Invoke handler directly through registered event binding
    result = block_fn.fn()

    # 4. Assert returned tuple length matches registered outputs
    assert len(result) == expected_outputs_count, (
        f"Returned tuple length {len(result)} does not match outputs count {expected_outputs_count}"
    )

    (
        banner, k_hw, k_theo, k_plan, k_perf, k_bot,
        fig_speed, fig_stair, fig_seven, tbl_conf,
        fig_plat, fig_mt, tbl_mt,
        fig_td, fig_tvs,
        fig_sens, fig_stoch,
        fig_cmp, fig_mig, tbl_cmp,
    ) = result

    # 5. Assert all KPI cards contain non-placeholder values
    assert "Not Available" not in k_hw, f"Technical Min Headway is placeholder: {k_hw}"
    assert "s" in k_hw
    assert "Not Available" not in k_theo, f"Theoretical capacity is placeholder: {k_theo}"
    assert "tph" in k_theo
    assert "Not Available" not in k_plan, f"Planning capacity is placeholder: {k_plan}"
    assert "Not Available" not in k_perf, f"Performance factor is placeholder: {k_perf}"
    assert "100%" in k_perf
    assert "Not Available" not in k_bot, f"Controlling bottleneck is placeholder: {k_bot}"

    # 6. Verify dynamic report assembly saved doc in session state
    assert session_state.latest_report_doc is not None

    # 7. Exercise Gradio's actual event processing pipeline (process_api)
    api_res = asyncio.run(demo.process_api(block_fn=fn_idx, inputs=[]))
    assert "data" in api_res
    assert len(api_res["data"]) == expected_outputs_count


def test_tab_results_refresh_empty_session_state_gradio_blocks():
    """Task 6.2: Run refresh callback through real Gradio Blocks context with empty session state."""
    session_state.latest_result_package = None
    session_state.latest_report_doc = None

    with gr.Blocks() as demo:
        components = create_results_tab()

    fn_idx, block_fn = _find_refresh_block_fn(demo)
    expected_outputs_count = len(block_fn.outputs)
    assert expected_outputs_count == 20

    # Invoke handler through registered event binding
    result = block_fn.fn()

    assert len(result) == expected_outputs_count
    guidance_msg = "No simulation results available. Run a simulation in Tab 8 first."
    k_hw = result[1]
    k_perf = result[4]

    assert guidance_msg in k_hw, f"Expected guidance message in k_hw, got {k_hw}"
    assert guidance_msg in k_perf, f"Expected guidance message in k_perf, got {k_perf}"

    # Also verify through process_api
    api_res = asyncio.run(demo.process_api(block_fn=fn_idx, inputs=[]))
    assert "data" in api_res
    assert len(api_res["data"]) == expected_outputs_count


def test_tab_results_refresh_derated_performance_factor_gradio_blocks():
    """Task 6.3: Run refresh callback with derated factor = 0.50 and assert KPI displays '50%'.

    v1.11.2 (literal strict): 01_single_track fails pre-simulation block-geometry
    validation, so the original scenario cannot run on the unmodified shipped example.
    The test now asserts the documented error (tests/block_geometry_expectations.py)
    in FORWARD and REVERSE.
    """
    load_and_assert_pipeline_raises("01_single_track")

def test_tab_results_refresh_derated_performance_factor_gradio_blocks_on_corrected_variant():
    """Task 6.3: Run refresh callback with derated factor = 0.50 and assert KPI displays '50%'."""
    # v1.11.2: runs on the corrected in-memory variant (tests/corrected_variants.py); the shipped example raises a named ERR_* (tests/unit/test_v1112_bidirectional_integrity.py).
    proj, report, _ = load_corrected_variant("01_single_track")
    pkg, doc = SimulationRunner.run_simulation_pipeline(
        project=proj,
        performance_factor=0.50,
    )

    session_state.latest_result_package = pkg
    session_state.latest_report_doc = doc

    with gr.Blocks() as demo:
        components = create_results_tab()

    fn_idx, block_fn = _find_refresh_block_fn(demo)
    result = block_fn.fn()

    assert len(result) == len(block_fn.outputs) == 20
    k_perf = result[4]
    assert "50%" in k_perf, f"Expected '50%' in Performance Factor KPI, got {k_perf}"
    assert "analysis" in k_perf

    # Also verify via process_api
    api_res = asyncio.run(demo.process_api(block_fn=fn_idx, inputs=[]))
    assert "50%" in api_res["data"][4]
