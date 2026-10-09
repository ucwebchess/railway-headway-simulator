"""Integration tests verifying physical infrastructure engine across all 4 official example datasets."""

from pathlib import Path
import pytest

from headway.data.converter import convert_raw_to_canonical
from headway.data.importer import ExcelImporter
from headway.data.validation import ValidationReport
from headway.data.validator import DatasetValidator
from headway.infrastructure import (
    DirectionPolicyError,
    InfrastructurePreprocessor,
    InfrastructureValidator,
    PhysicalNetworkGraph,
    RouteEngine,
    RunningDirection,
)


def load_example_canonical(example_dirname: str):
    ex_path = Path("examples") / example_dirname
    importer = ExcelImporter()
    report = ValidationReport(project_id=example_dirname)
    raw_wbs = {}
    for f in ex_path.glob("*.xlsx"):
        raw_wb = importer.load_workbook(f, report)
        raw_wbs[raw_wb.workbook_type] = raw_wb
    validator = DatasetValidator(report)
    validator.validate_all(raw_wbs)
    assert not report.has_errors
    return convert_raw_to_canonical(raw_wbs)


@pytest.mark.integration
def test_01_single_track_bidirectional_routes():
    """Verify 01_single_track: single track allows both forward and reverse operations."""
    project = load_example_canonical("01_single_track")
    infra = project.infrastructure

    # Validate infrastructure model
    validator = InfrastructureValidator()
    report = validator.validate_infrastructure_model(infra)
    assert not report.has_errors

    # Build graph
    graph = PhysicalNetworkGraph(infra)
    assert len(graph.nodes) == 3
    assert len(graph.links) == 2

    engine = RouteEngine(graph)

    # Build forward route across entire corridor: ND_01 -> ND_02 -> ND_03
    route_fwd = engine.build_route_from_nodes("RT_SINGLE_FWD", ["ND_01", "ND_02", "ND_03"])
    assert route_fwd.total_length_m == 4000.0
    assert route_fwd.start_node_id == "ND_01"
    assert route_fwd.end_node_id == "ND_03"

    # Forward route position lookup
    link_id, offset, direction = route_fwd.route_distance_to_physical(2500.0)
    assert link_id == "LNK_02"
    assert offset == 500.0
    assert direction == RunningDirection.FORWARD

    # Build reverse route: ND_03 -> ND_02 -> ND_01
    route_rev = route_fwd.create_reverse_route(graph, "RT_SINGLE_REV")
    assert route_rev.total_length_m == 4000.0
    assert route_rev.start_node_id == "ND_03"
    assert route_rev.end_node_id == "ND_01"

    # Reverse route position lookup (s=2500m is 500m into second link LNK_01 from ND_02 toward ND_01)
    link_id_rev, offset_rev, dir_rev = route_rev.route_distance_to_physical(2500.0)
    assert link_id_rev == "LNK_01"
    assert dir_rev == RunningDirection.REVERSE
    # Physical offset = L - local_s = 2000 - 500 = 1500m
    assert offset_rev == 1500.0

    # Route feasibility
    fwd_ok, rev_ok, _ = validator.validate_route_feasibility(route_fwd, graph)
    assert fwd_ok is True
    assert rev_ok is True


@pytest.mark.integration
def test_02_double_track_directional_enforcement():
    """Verify 02_double_track: UP track permits FORWARD only, DN track permits REVERSE only."""
    project = load_example_canonical("02_double_track")
    infra = project.infrastructure

    graph = PhysicalNetworkGraph(infra)
    engine = RouteEngine(graph)
    validator = InfrastructureValidator()

    # UP line route: ND_U1 -> ND_U2 (LNK_UP_01)
    route_up = engine.build_route_from_traversals("RT_UP", [("LNK_UP_01", RunningDirection.FORWARD)])
    assert route_up.total_length_m == 3000.0

    # Feasibility: UP line is feasible forward, but NOT feasible reverse
    fwd_ok, rev_ok, msgs = validator.validate_route_feasibility(route_up, graph)
    assert fwd_ok is True
    assert rev_ok is False

    # Attempting to reverse UP line route must raise DirectionPolicyError
    with pytest.raises(DirectionPolicyError):
        route_up.create_reverse_route(graph)

    # DN line route: ND_D1 -> ND_D2 (LNK_DN_01) is REVERSE only
    route_dn = engine.build_route_from_traversals("RT_DN", [("LNK_DN_01", RunningDirection.REVERSE)])
    assert route_dn.total_length_m == 3000.0

    # Attempting to run DN line in FORWARD must fail
    with pytest.raises(DirectionPolicyError):
        engine.build_route_from_traversals("RT_DN_FWD", [("LNK_DN_01", RunningDirection.FORWARD)])


@pytest.mark.integration
def test_03_station_platform_geometry():
    """Verify 03_station_platform: station and platform stops, usable length, reverse arrival."""
    project = load_example_canonical("03_station_platform")
    infra = project.infrastructure

    graph = PhysicalNetworkGraph(infra)
    engine = RouteEngine(graph)

    route_fwd = engine.build_route_from_traversals("RT_STN_FWD", [("LNK_STN_01", RunningDirection.FORWARD)])
    route_rev = route_fwd.create_reverse_route(graph, "RT_STN_REV")

    preprocessor = InfrastructurePreprocessor(infra)
    profile_fwd = preprocessor.preprocess_route(route_fwd, RunningDirection.FORWARD)
    profile_rev = preprocessor.preprocess_route(route_rev, RunningDirection.REVERSE)

    assert len(profile_fwd.stations) == 1
    assert len(profile_rev.stations) == 1

    stop_fwd = profile_fwd.stations[0]
    stop_rev = profile_rev.stations[0]

    assert stop_fwd.station.station_id == "STN_CENTRAL"
    assert stop_rev.station.station_id == "STN_CENTRAL"

    # Check stopping point and train accommodation (platform length is 300m: 400m to 700m)
    assert stop_fwd.is_train_accommodated(200.0) is True  # 200m train <= 300m platform
    assert stop_fwd.is_train_accommodated(350.0) is False  # 350m train > 300m platform


@pytest.mark.integration
def test_04_tunnel_tvs_boundary_reversal():
    """Verify 04_tunnel_tvs: TVS sections with forward and reverse entry/exit resolution."""
    project = load_example_canonical("04_tunnel_tvs")
    infra = project.infrastructure

    graph = PhysicalNetworkGraph(infra)
    engine = RouteEngine(graph)

    route_fwd = engine.build_route_from_traversals(
        "RT_TNL_FWD",
        [("LNK_T01", RunningDirection.FORWARD), ("LNK_T02", RunningDirection.FORWARD)],
    )
    route_rev = route_fwd.create_reverse_route(graph, "RT_TNL_REV")

    preprocessor = InfrastructurePreprocessor(infra)
    profile_fwd = preprocessor.preprocess_route(route_fwd, RunningDirection.FORWARD)
    profile_rev = preprocessor.preprocess_route(route_rev, RunningDirection.REVERSE)

    assert len(profile_fwd.tvs_sections) == 2
    assert len(profile_rev.tvs_sections) == 2

    # In forward: TVS_01 is encountered first, then TVS_02
    assert profile_fwd.tvs_sections[0].tvs_id == "TVS_01"
    assert profile_fwd.tvs_sections[1].tvs_id == "TVS_02"

    # In reverse: TVS_02 is encountered first, then TVS_01!
    assert profile_rev.tvs_sections[0].tvs_id == "TVS_02"
    assert profile_rev.tvs_sections[1].tvs_id == "TVS_01"
