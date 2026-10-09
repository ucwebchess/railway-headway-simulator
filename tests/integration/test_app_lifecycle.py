"""Integration test for launching Gradio app and shutting down cleanly."""

import time
import pytest
import gradio as gr
from headway.core.configuration import AppConfig, DirectoryConfig, EnvironmentType, GradioServerConfig
from headway.ui.app import create_app


@pytest.mark.integration
def test_gradio_app_lifecycle_startup(temp_storage_dir):
    """Verify that Gradio Blocks app can launch locally on a test port and close cleanly."""
    dirs = DirectoryConfig(base_dir=temp_storage_dir)
    server_cfg = GradioServerConfig(
        server_name="127.0.0.1",
        server_port=7869,  # Distinct test port
        share=False,
    )
    config = AppConfig(
        environment=EnvironmentType.TESTING,
        directories=dirs,
        server=server_cfg,
    )

    demo = create_app(config)
    # Launch in background thread without blocking
    _, local_url, _ = demo.launch(
        server_name=config.server.server_name,
        server_port=config.server.server_port,
        prevent_thread_lock=True,
        share=False,
    )

    try:
        assert local_url is not None
        assert "7869" in local_url
    finally:
        demo.close()
        gr.close_all()
