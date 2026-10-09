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
    assert "0.1.0-dev" in demo.title


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
