"""v1.15.0.1: the package's running direction is authoritative for its report and exports.

Before v1.15.0.1 the UI kept one ``session_state.report_config`` whose ``running_direction`` was
written by Tab 10 (template / section handlers with the radio direction, "Generate report" with the
package direction). Every later simulation run passed it to ``ReportAssembler.assemble_report``,
which used ``cfg.running_direction or package.running_direction``. A run in the other direction was
therefore assembled in the previous run's frame. On 07c that raised ``ERR_CHART_ALIGNMENT_FRAME``
(platform extents mapped FORWARD, stop positions REVERSE); elsewhere it silently labelled REVERSE
results as FORWARD. The Tab 9 speed-profile CSV export used the radio direction instead of the
exported package's direction.

The handlers are exercised through real Gradio Blocks (as in test_tab_results_refresh_gradio.py).
"""
from __future__ import annotations

import gradio as gr
import pytest

from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_speed import generate_speed_profile_csv
from headway.reporting.report_assembly import ReportAssembler, ReportDirectionMismatchError
from headway.reporting.report_config import ReportConfig, ReportType
from headway.ui import tab_results
from headway.ui.simulation_runner import SimulationRunner
from headway.ui.state import session_state
from headway.ui.tab_reports import create_reports_tab
from headway.ui.tab_results import create_results_tab
from headway.ui.tab_simulation import create_simulation_tab

from tests.corrected_variants import load_corrected_variant

FWD, REV = RunningDirection.FORWARD, RunningDirection.REVERSE
ORDERS = [(FWD, REV), (REV, FWD)]
_IDS = lambda o: f"{o[0].name}_then_{o[1].name}" if isinstance(o, tuple) else getattr(o, "name", str(o))


@pytest.fixture(autouse=True)
def reset_session(tmp_path):
    session_state.reset()
    session_state.reports_dir = tmp_path / "reports"
    yield
    session_state.reset()


def _fn(demo: gr.Blocks, name: str):
    for block_fn in demo.fns.values():
        if block_fn.fn.__name__ == name:
            return block_fn.fn
    raise ValueError(f"{name} not registered in demo.fns")


_PKG = {}


def _package(example: str, direction: RunningDirection):
    key = (example, direction)
    if key not in _PKG:
        _PKG[key] = SimulationRunner.run_simulation_pipeline(load_corrected_variant(example)[0], running_direction=direction)
    return _PKG[key]


# ----------------------------------------------------------------------------------------------
# 1. Emulated UI session, both orders
# ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("order", ORDERS, ids=_IDS)
def test_ui_session_direction_pair_both_orders(order):
    """Tab 8 run -> Tab 10 template + sections + "Generate report" (all three session-config
    writers) -> radio change -> Tab 8 run in the other direction, on the same loaded project (07c,
    whose stops expose a frame mismatch on the Service Alignment Diagram). Both runs complete, the
    alignment figure is present and every report's direction equals its package's."""
    first, second = order
    session_state.current_project = load_corrected_variant("07_hsr_140km")[0]
    with gr.Blocks() as demo:
        sim = create_simulation_tab()
        rep = create_reports_tab()
    run = _fn(demo, "handle_run_simulation")
    radio = _fn(demo, "handle_direction_change")
    template_change = _fn(demo, "handle_template_change")
    sections_change = _fn(demo, "handle_sections_change")
    generate = _fn(demo, "assemble_and_preview")
    sim_args = lambda d: (d.value, sim["sim_mode_dropdown"].value, 1.0, 7200.0, 18.0, 100,
                          sim["param_performance_factor"].value)

    reports = []
    for i, direction in enumerate((first, second)):
        radio(direction.value)
        _, status, _, log = run(*sim_args(direction))
        assert status.startswith("Completed"), f"run {i + 1} ({direction.name}) failed: {log}"
        pkg, doc = session_state.latest_result_package, session_state.latest_report_doc
        assert pkg.running_direction == direction
        assert doc.running_direction == pkg.running_direction
        assert "fig_service_alignment" in doc.figures_data
        assert f"-{direction.value}-" in doc.metadata.report_id
        reports.append(doc)
        if i == 0:
            # Tab 10: every writer of session_state.report_config, then "Generate report".
            template = "Detailed Engineering (All Sections)"
            selected = template_change(template)
            assert session_state.report_config.running_direction is None
            sections_change(selected, template)
            assert session_state.report_config.running_direction is None
            msg, _ = generate(template, "T", "A", selected)
            assert session_state.report_config.running_direction == first   # unchanged writer (:214-222)
            assert session_state.latest_report_doc.running_direction == first
    # The stale FORWARD/REVERSE session config was present for run 2 and did not leak into it.
    assert session_state.report_config.running_direction == first
    assert [d.running_direction for d in reports] == [first, second]
    # Re-generating the report for run 2 from Tab 10 uses run 2's direction.
    generate("Detailed Engineering (All Sections)", "T", "A", template_change("Detailed Engineering (All Sections)"))
    assert session_state.latest_report_doc.running_direction == second


# ----------------------------------------------------------------------------------------------
# 2-3. ReportAssembler direction rule
# ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("direction", [FWD, REV], ids=_IDS)
def test_report_assembly_direction_mismatch_raises(direction):
    pkg, _ = _package("04_tunnel_tvs", direction)
    other = REV if direction == FWD else FWD
    with pytest.raises(ReportDirectionMismatchError) as exc:
        ReportAssembler.assemble_report(pkg, config=ReportConfig(running_direction=other))
    err = exc.value
    assert err.error_code == "ERR_REPORT_DIRECTION_MISMATCH"
    assert err.context["config_running_direction"] == other.value
    assert err.context["package_running_direction"] == direction.value
    assert "package.running_direction is authoritative" in err.context["rule"]
    assert f"ReportConfig.running_direction is {other.value}" in str(err)
    assert f"was simulated in {direction.value}" in str(err)


@pytest.mark.parametrize("direction", [FWD, REV], ids=_IDS)
def test_report_assembly_no_direction_unchanged(direction):
    """No direction (or the package's own) -> no error; the package direction is used, and the
    sections are identical to the runner's own report."""
    pkg, runner_doc = _package("04_tunnel_tvs", direction)
    for cfg in (None, ReportConfig(), ReportConfig(running_direction=direction),
                ReportConfig(report_type=ReportType.DETAILED_ENGINEERING, running_direction=None)):
        doc = ReportAssembler.assemble_report(pkg, config=cfg)
        assert doc.running_direction == direction
        assert f"-{direction.value}-" in doc.metadata.report_id
        assert list(doc.sections) == list(runner_doc.sections)
        assert [s.narrative_paragraphs for s in doc.sections.values()] == [s.narrative_paragraphs for s in runner_doc.sections.values()]


# ----------------------------------------------------------------------------------------------
# 4. Tab 9 speed-profile CSV export
# ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("direction", [FWD, REV], ids=_IDS)
def test_tab_results_speed_csv_uses_package_direction(direction, monkeypatch):
    """Radio switched to the other direction without re-running: the exported CSV is built with the
    package's direction and is byte-identical to generate_speed_profile_csv(..., package direction)."""
    pkg, doc = _package("04_tunnel_tvs", direction)
    other = REV if direction == FWD else FWD
    session_state.latest_result_package, session_state.latest_report_doc = pkg, doc
    session_state.selected_running_direction = other            # radio changed, no re-run

    seen = []
    real = tab_results.generate_speed_profile_csv

    def spy(*args, **kwargs):
        seen.append(kwargs.get("running_direction"))
        return real(*args, **kwargs)

    monkeypatch.setattr(tab_results, "generate_speed_profile_csv", spy)
    with gr.Blocks() as demo:
        create_results_tab()
    out = _fn(demo, "export_speed_csv_results")()
    assert "Download Speed Profile CSV" in str(out)
    assert seen == [direction]

    traj = next(iter(pkg.trajectories.values()))
    path = session_state.reports_dir / f"Speed_Profile_{pkg.run_id}_{traj.train_id}.csv"
    expected = generate_speed_profile_csv(
        traj,
        permissible_speed_envelope=pkg.metadata.get("permissible_speed_envelope"),
        track_links=pkg.metadata.get("track_links"),
        running_direction=pkg.running_direction,
    )
    assert path.read_text(encoding="utf-8") == expected
