"""v1.12.0 — route resolution for the simulation runner (ROUTE_LINK_SEQUENCE scoping)."""

from types import SimpleNamespace

import pytest

from headway.infrastructure.direction import RunningDirection
from headway.ui.simulation_runner import SimulationRunner, SimulationRunnerError
from tests import route_scope_project as rsp


def _pattern(seq):
    return SimpleNamespace(service_pattern_id="SP_T", route_link_sequence=seq)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return rsp.load_route_scope_project(tmp_path_factory.mktemp("rs") / "p")


def test_resolve_returns_route_links_in_sequence_order(project):
    links = SimulationRunner._resolve_route_links(project.infrastructure.track_links, _pattern(rsp.ROUTE))
    assert [lnk.link_id for lnk in links] == rsp.ROUTE


def test_resolve_without_pattern_falls_back_to_full_network(project):
    net = list(project.infrastructure.track_links)
    assert SimulationRunner._resolve_route_links(net, None) == net
    assert SimulationRunner._resolve_route_links(net, _pattern([])) == net


def test_unknown_route_link_raises(project):
    with pytest.raises(SimulationRunnerError) as ei:
        SimulationRunner._resolve_route_links(project.infrastructure.track_links, _pattern(["LNK_046", "LNK_999"]))
    assert ei.value.error_code == "ERR_ROUTE_LINK_UNKNOWN"
    assert "LNK_999" in str(ei.value)


@pytest.mark.parametrize("seq", [["LNK_046", "LNK_048"], ["LNK_047", "LNK_046"]])
def test_non_contiguous_route_raises(project, seq):
    with pytest.raises(SimulationRunnerError) as ei:
        SimulationRunner._resolve_route_links(project.infrastructure.track_links, _pattern(seq))
    assert ei.value.error_code == "ERR_ROUTE_NOT_CONTIGUOUS"
    assert f"{seq[0]}->{seq[1]}" in str(ei.value)


@pytest.mark.parametrize("direction", [RunningDirection.FORWARD, RunningDirection.REVERSE])
def test_stop_off_route_raises_in_pipeline(direction):
    # Shipped 06 (unmodified) with its route trimmed in memory to LNK_02..LNK_03: both stops
    # (PLT_01 on LNK_01, PLT_02 on LNK_04) now lie off the route -> loud failure, no silent
    # simulation of the full corridor.
    from tests.corrected_variants import _load

    project, _, _ = _load("06_multilink_blocks")
    sp = project.operations.service_patterns[0]
    project.operations.service_patterns[0] = sp.model_copy(update={"route_link_sequence": ["LNK_02", "LNK_03"]})
    with pytest.raises(SimulationRunnerError) as ei:
        SimulationRunner.run_simulation_pipeline(project, running_direction=direction)
    assert ei.value.error_code == "ERR_ROUTE_STOP_OFF_ROUTE"
