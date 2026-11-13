"""pytest plugin (v1.15.2, used only by tests/integration/test_v1152_session_isolation.py via ``-p``).

Simulates the pre-v1.15.2 leak: after the conftest clean-session fixture has run, open shipped example
01 in ``session_state`` so every test starts with a foreign project open.
"""
import pytest


@pytest.fixture(autouse=True)
def _foreign_project_open(_isolated_session_state):
    from headway.ui.state import session_state

    ok, msg = session_state.load_example("01_single_track")
    assert ok, msg
    assert session_state.current_project is not None
    yield
