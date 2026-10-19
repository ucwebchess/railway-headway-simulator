"""Integration tests for Gradio UI construction and navigation tabs."""

import gradio as gr
import pytest

from headway.core.configuration import AppConfig
from headway.ui.app import create_app


@pytest.mark.integration
def test_gradio_app_construction(test_config: AppConfig):
    """Verify that create_app builds a valid Gradio Blocks instance without server launch."""
    demo = create_app(test_config)
    assert isinstance(demo, gr.Blocks)
    assert demo.title is not None
    assert "Railway Headway & Capacity Simulator" in demo.title
    assert "1.6.1" in demo.title


@pytest.mark.integration
def test_all_ten_tabs_exist(test_config: AppConfig):
    """Verify that all ten required navigation tabs exist in the Gradio Blocks hierarchy."""
    demo = create_app(test_config)

    expected_tab_names = [
        "1. Project Dashboard",
        "2. Data Import",
        "3. Data Validation",
        "4. Infrastructure Explorer",
        "5. Rolling Stock & Signalling",
        "6. Services & Operations",
        "7. Scenario Manager",
        "8. Simulation Control",
        "9. Results & Comparison",
        "10. Reports & Export",
    ]

    # Inspect rendered blocks / children
    found_tabs = []
    for block in demo.blocks.values():
        if isinstance(block, gr.TabItem):
            found_tabs.append(block.label)

    for expected in expected_tab_names:
        assert expected in found_tabs, f"Required tab '{expected}' not found in Gradio interface."


@pytest.mark.integration
def test_no_fake_engineering_results_in_ui(test_config: AppConfig):
    """Verify that UI contains no invented headway, capacity, or speed values (P00-UI-006)."""
    demo = create_app(test_config)

    # Check HTML blocks for the strict placeholder string
    html_contents = []
    for block in demo.blocks.values():
        if isinstance(block, gr.HTML):
            html_contents.append(block.value)

    combined_html = " ".join(str(c) for c in html_contents)

    # Verify placeholder presence
    assert "Not available — simulation engine not implemented" in combined_html
    # Verify no fake numbers like "120 s" or "30 trains/h" in KPI cards
    assert "120 s" not in combined_html
    assert "30 tph" not in combined_html


@pytest.mark.integration
def test_simulation_dropdown_dynamically_populates_from_analyses():
    """Verify simulation mode dropdown dynamically populates from project.analysis.analyses (DEF-10)."""
    from headway.ui.file_manager import FileManager
    from headway.ui.state import session_state
    from headway.ui.tab_simulation import update_simulation_analyses, create_simulation_tab

    project, _, _ = FileManager.load_example_project("07_hsr_140km")
    session_state.set_project(project)

    dropdown_update, pf_map, init_pf = update_simulation_analyses(project)

    # Assert dropdown choices match project analyses
    assert len(project.analysis.analyses) >= 2
    choice_labels = [c[0] if isinstance(c, tuple) else c for c in dropdown_update.choices]
    for an in project.analysis.analyses:
        expected_label = f"{an.analysis_id} (PF: {float(an.performance_factor):.2f})"
        assert expected_label in pf_map
        assert pf_map[expected_label] == float(an.performance_factor)
        assert expected_label in choice_labels

    # Also assert UI component instantiation reflects loaded project
    with gr.Blocks():
        comps = create_simulation_tab()
    assert "sim_mode_dropdown" in comps
    assert "param_performance_factor" in comps
    dropdown_inst_choices = [c[0] if isinstance(c, tuple) else c for c in comps["sim_mode_dropdown"].choices]
    assert "AN_HSR_HSR_UP (PF: 1.00)" in dropdown_inst_choices
    assert "AN_HSR_HSR_UP_95 (PF: 0.95)" in dropdown_inst_choices
    assert comps["param_performance_factor"].value == 1.00
