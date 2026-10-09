"""Integration tests for package architecture and importability."""

import importlib
import pytest


@pytest.mark.integration
def test_package_and_subpackages_import():
    """Verify that all required package modules import cleanly without circular dependencies."""
    modules_to_test = [
        "headway",
        "headway.core",
        "headway.core.version",
        "headway.core.configuration",
        "headway.core.exceptions",
        "headway.core.logging_config",
        "headway.data",
        "headway.infrastructure",
        "headway.rolling_stock",
        "headway.signalling",
        "headway.simulation",
        "headway.analysis",
        "headway.scenarios",
        "headway.reporting",
        "headway.ui",
        "headway.ui.theme",
        "headway.ui.components",
        "headway.ui.app",
        "headway.__main__",
    ]

    for mod_name in modules_to_test:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Module {mod_name} failed to import."


@pytest.mark.integration
def test_no_gradio_import_in_core():
    """Verify that core modules remain completely independent of Gradio (P00-ARCH-003)."""
    import sys
    import headway.core.configuration as cfg
    import headway.core.exceptions as exc
    import headway.core.logging_config as log
    import headway.core.version as ver

    for mod in (cfg, exc, log, ver):
        mod_dict = mod.__dict__
        for obj in mod_dict.values():
            if hasattr(obj, "__module__") and obj.__module__:
                assert "gradio" not in obj.__module__, f"Gradio dependency found in core: {obj}"
