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


# ─────────────────────────────────────────────────────────────────────────────
# ERR_ROUTE_DIRECTION_FORBIDDEN — run direction vs. track DIRECTIONALITY (route level)
# ─────────────────────────────────────────────────────────────────────────────
def _links_tracks(directionality):
    from headway.data.canonical import TrackDirectionality

    links = [SimpleNamespace(link_id=f"LNK_{k}", track_id="TRK_A") for k in (1, 2, 3)]
    tracks = [SimpleNamespace(track_id="TRK_A", directionality=TrackDirectionality(directionality))]
    return links, tracks


@pytest.mark.parametrize(
    "directionality, direction, forbidden",
    [
        ("NOMINAL", RunningDirection.REVERSE, True),
        ("NOMINAL", RunningDirection.FORWARD, False),
        ("REVERSE", RunningDirection.FORWARD, True),
        ("REVERSE", RunningDirection.REVERSE, False),
        ("BIDIRECTIONAL", RunningDirection.FORWARD, False),
        ("BIDIRECTIONAL", RunningDirection.REVERSE, False),
    ],
)
def test_route_direction_matrix(directionality, direction, forbidden):
    links, tracks = _links_tracks(directionality)
    if not forbidden:
        SimulationRunner._validate_route_direction(links, tracks, direction, _pattern(["LNK_1"]))
        return
    with pytest.raises(SimulationRunnerError) as ei:
        SimulationRunner._validate_route_direction(links, tracks, direction, _pattern(["LNK_1"]))
    assert ei.value.error_code == "ERR_ROUTE_DIRECTION_FORBIDDEN"
    msg = str(ei.value)
    assert f"{direction.value} run is not permitted" in msg
    assert "TRK_A (3 link(s): LNK_1..LNK_3)" in msg
    assert "BIDIRECTIONAL" in msg


def test_route_direction_only_checks_route_tracks():
    # A one-way track OFF the route does not block the run (route scope, not network scope).
    from headway.data.canonical import TrackDirectionality

    links = [SimpleNamespace(link_id="LNK_1", track_id="TRK_BI")]
    tracks = [
        SimpleNamespace(track_id="TRK_BI", directionality=TrackDirectionality.BIDIRECTIONAL),
        SimpleNamespace(track_id="TRK_ONEWAY", directionality=TrackDirectionality.NOMINAL),
    ]
    SimulationRunner._validate_route_direction(links, tracks, RunningDirection.REVERSE, _pattern(["LNK_1"]))


def test_example_02_reverse_raises_direction_forbidden():
    # Shipped 02 (unmodified): the only service SRV_EXP_01 runs on TRK_UP = NOMINAL (one-way).
    from tests.corrected_variants import _load

    project, _, _ = _load("02_double_track")
    with pytest.raises(SimulationRunnerError) as ei:
        SimulationRunner.run_simulation_pipeline(project, running_direction=RunningDirection.REVERSE)
    assert ei.value.error_code == "ERR_ROUTE_DIRECTION_FORBIDDEN"
    assert "TRK_UP (1 link(s): LNK_UP_01)" in str(ei.value)
    # FORWARD is permitted and simulates the 3000 m route.
    pkg, _doc = SimulationRunner.run_simulation_pipeline(project, running_direction=RunningDirection.FORWARD)
    assert pkg.metadata["route_length_m"] == pytest.approx(3000.0)


def test_example_05_shipped_data_forbids_reverse():
    # Shipped 05 data (unmodified): every service route lies on NOMINAL (one-way) tracks
    # (TRK_UP / TRK_DN; the FRT loop also uses the BIDIRECTIONAL siding) -> REVERSE forbidden.
    from tests.corrected_variants import _load

    project, _, _ = _load("05_comprehensive_line")
    net = list(project.infrastructure.track_links)
    for sp in project.operations.service_patterns:
        route = SimulationRunner._resolve_route_links(net, sp)
        with pytest.raises(SimulationRunnerError) as ei:
            SimulationRunner._validate_route_direction(route, project.infrastructure.tracks, RunningDirection.REVERSE, sp)
        assert ei.value.error_code == "ERR_ROUTE_DIRECTION_FORBIDDEN", sp.service_pattern_id
        SimulationRunner._validate_route_direction(route, project.infrastructure.tracks, RunningDirection.FORWARD, sp)


def test_example_05_reverse_pipeline_raises_direction_forbidden():
    # Shipped 05 first fails v1.11.2 block-geometry validation (identical in both directions,
    # checked before any route resolution). With ONLY that geometry correction applied —
    # shipped routes and shipped NOMINAL tracks unchanged — REVERSE raises the direction error.
    from headway.signalling.block_geometry_validation import BlockGeometryValidationError
    from tests.corrected_variants import _load, apply_comprehensive_line_turnaround_exits

    shipped, _, _ = _load("05_comprehensive_line")
    with pytest.raises(BlockGeometryValidationError):
        SimulationRunner.run_simulation_pipeline(shipped, running_direction=RunningDirection.REVERSE)

    project = apply_comprehensive_line_turnaround_exits(_load("05_comprehensive_line")[0])
    with pytest.raises(SimulationRunnerError) as ei:
        SimulationRunner.run_simulation_pipeline(project, running_direction=RunningDirection.REVERSE)
    assert ei.value.error_code == "ERR_ROUTE_DIRECTION_FORBIDDEN"
    assert "SVC_HSR_EXP_DN" in str(ei.value) and "TRK_DN (7 link(s): LNK_11..LNK_17)" in str(ei.value)
    pkg, _doc = SimulationRunner.run_simulation_pipeline(project, running_direction=RunningDirection.FORWARD)
    assert pkg.metadata["route_length_m"] == pytest.approx(25000.0)
