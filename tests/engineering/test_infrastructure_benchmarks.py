"""Mandatory engineering benchmarks for Milestone P02.

Strictly satisfies RHS-P02-001 § 22:
- BENCH-P02-001: Simple Forward Route (A -> B: 1000m, B -> C: 2000m => L_route = 3000m)
- BENCH-P02-002: Reverse Route (C -> B -> A => L_route = 3000m, identical physical links)
- BENCH-P02-003: Reverse Position Mapping (L = 1000m, s_local = 200m => x_physical = 800m)
- BENCH-P02-004: Reverse Gradient (Forward +10‰ => Reverse -10‰)
- BENCH-P02-005: Reverse Speed Restriction (Forward-only does not apply in reverse; BOTH applies in both)
- BENCH-P02-006: Reverse Chainage (Route chainage 0-10 km: reverse s=0 is 10 km, s=10 is 0 km)
- BENCH-P02-007: Train Length Across Links (L_train = 200m, front 50m into 2nd link => 50m in 2nd, 150m in 1st)
- BENCH-P02-008: Reverse Train Length (Repeat BENCH-P02-007 in reverse, total physical occupied length remains 200m)
- BENCH-P02-009: TVS Reverse Entry (Physical TVS 5-10 km => Forward entry 5 km, Reverse entry 10 km)
- BENCH-P02-010: Direction Policy (FORWARD_ONLY track rejects unauthorized reverse traversal)
"""

import pytest

from headway.data.canonical import (
    Node,
    NodeType,
    ResourceInterval,
    Track,
    TrackDirectionality,
    TrackLink,
    Tunnel,
    TVSSection,
)
from headway.infrastructure.alignment import RouteAlignmentProfile
from headway.infrastructure.chainage import ChainageSegment, EngineeringChainageModel
from headway.infrastructure.direction import (
    DirectionPolicy,
    DirectionPolicyError,
    RunningDirection,
)
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import Route, RouteEngine
from headway.infrastructure.speed import RouteSpeedProfile, SpeedRestriction
from headway.infrastructure.train_geometry import TrainGeometry
from headway.infrastructure.tunnels import TunnelTVSModel


@pytest.fixture
def corridor_graph():
    """Build a standard 3-node physical corridor:

    Node A ---Link 1 (1000m)--- Node B ---Link 2 (2000m)--- Node C
    Track TRK_01 is BIDIRECTIONAL.
    Link 1: length = 1000m, gradient = +0.010 (+10‰), max_speed = 30 m/s
    Link 2: length = 2000m, gradient = -0.005 (-5‰), max_speed = 40 m/s
    """
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_A", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_B", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_C", node_type=NodeType.ENDPOINT))

    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

    graph.add_link(
        TrackLink(
            link_id="LNK_AB",
            track_id="TRK_01",
            start_node_id="ND_A",
            end_node_id="ND_B",
            length_m=1000.0,
            max_speed_ms=30.0,
            gradient_decimal=0.010,  # +10‰
            curvature_radius_m=None,
        )
    )
    graph.add_link(
        TrackLink(
            link_id="LNK_BC",
            track_id="TRK_01",
            start_node_id="ND_B",
            end_node_id="ND_C",
            length_m=2000.0,
            max_speed_ms=40.0,
            gradient_decimal=-0.005,  # -5‰
            curvature_radius_m=1500.0,
        )
    )
    return graph


@pytest.mark.engineering
def test_bench_p02_001_simple_forward_route(corridor_graph):
    """BENCH-P02-001: Simple Forward Route:

    A -> B: 1,000 m; B -> C: 2,000 m => Expected total route length: 3,000 m.
    """
    engine = RouteEngine(corridor_graph)
    route_fwd = engine.build_route_from_traversals(
        route_id="RT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )

    assert route_fwd.total_length_m == pytest.approx(3000.0, rel=1e-6)
    assert len(route_fwd.traversals) == 2
    assert route_fwd.traversals[0].start_distance_m == 0.0
    assert route_fwd.traversals[0].end_distance_m == 1000.0
    assert route_fwd.traversals[1].start_distance_m == 1000.0
    assert route_fwd.traversals[1].end_distance_m == 3000.0


@pytest.mark.engineering
def test_bench_p02_002_reverse_route(corridor_graph):
    """BENCH-P02-002: Reverse Route:

    C -> B -> A => Expected total route length: 3,000 m.
    The identical physical links shall be used without duplication.
    """
    engine = RouteEngine(corridor_graph)
    route_fwd = engine.build_route_from_traversals(
        route_id="RT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )

    route_rev = route_fwd.create_reverse_route(corridor_graph, reverse_route_id="RT_REV")

    assert route_rev.total_length_m == pytest.approx(3000.0, rel=1e-6)
    assert len(route_rev.traversals) == 2

    # Traversal 0 is LNK_BC in REVERSE
    t0 = route_rev.traversals[0]
    assert t0.link_id == "LNK_BC"
    assert t0.direction == RunningDirection.REVERSE
    assert t0.entry_node_id == "ND_C"
    assert t0.exit_node_id == "ND_B"
    assert t0.start_distance_m == 0.0
    assert t0.end_distance_m == 2000.0

    # Traversal 1 is LNK_AB in REVERSE
    t1 = route_rev.traversals[1]
    assert t1.link_id == "LNK_AB"
    assert t1.direction == RunningDirection.REVERSE
    assert t1.entry_node_id == "ND_B"
    assert t1.exit_node_id == "ND_A"
    assert t1.start_distance_m == 2000.0
    assert t1.end_distance_m == 3000.0


@pytest.mark.engineering
def test_bench_p02_003_reverse_position_mapping(corridor_graph):
    """BENCH-P02-003: Reverse Position Mapping:

    Physical link length: 1,000 m.
    Reverse route-local distance: 200 m.
    Expected physical offset: 800 m (x_physical = L - s = 1000 - 200 = 800 m).
    """
    engine = RouteEngine(corridor_graph)
    route_fwd = engine.build_route_from_traversals(
        route_id="RT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )
    route_rev = route_fwd.create_reverse_route(corridor_graph)

    # In route_rev, LNK_AB is the second traversal (from 2000m to 3000m).
    # 200m into LNK_AB in route_rev corresponds to s = 2200m.
    s = 2200.0
    link_id, phys_offset, direction = route_rev.route_distance_to_physical(s)

    assert link_id == "LNK_AB"
    assert direction == RunningDirection.REVERSE
    assert phys_offset == pytest.approx(800.0, rel=1e-6)

    # Reverse lookup: given physical offset 800m on LNK_AB, route distance must return 2200m
    s_recovered = route_rev.physical_to_route_distance(link_id="LNK_AB", offset_m=800.0)
    assert s_recovered == pytest.approx(2200.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p02_004_reverse_gradient(corridor_graph):
    """BENCH-P02-004: Reverse Gradient:

    Physical forward gradient on LNK_AB: +10‰ (+0.010 decimal).
    Expected reverse effective gradient: -10‰ (-0.010 decimal).
    """
    engine = RouteEngine(corridor_graph)
    route_fwd = engine.build_route_from_traversals(
        route_id="RT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )
    route_rev = route_fwd.create_reverse_route(corridor_graph)

    fwd_profile = RouteAlignmentProfile(route_fwd)
    rev_profile = RouteAlignmentProfile(route_rev)

    # On LNK_AB in forward (s=500m): +10‰ (+0.010)
    assert fwd_profile.get_gradient_at(500.0) == pytest.approx(0.010, rel=1e-6)

    # On LNK_AB in reverse (s=2500m): -10‰ (-0.010)
    assert rev_profile.get_gradient_at(2500.0) == pytest.approx(-0.010, rel=1e-6)


@pytest.mark.engineering
def test_bench_p02_005_reverse_speed_restriction(corridor_graph):
    """BENCH-P02-005: Reverse Speed Restriction:

    A forward-only speed restriction shall not apply during reverse traversal.
    A BOTH-direction restriction shall apply in both directions.
    """
    engine = RouteEngine(corridor_graph)
    route_fwd = engine.build_route_from_traversals(
        route_id="RT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )
    route_rev = route_fwd.create_reverse_route(corridor_graph)

    restrictions = [
        SpeedRestriction(
            restriction_id="TSR_FWD_ONLY",
            link_id="LNK_AB",
            start_offset_m=100.0,
            end_offset_m=500.0,
            max_speed_ms=15.0,  # Restricted from baseline 30 m/s
            direction="FORWARD",
        ),
        SpeedRestriction(
            restriction_id="TSR_BOTH",
            link_id="LNK_BC",
            start_offset_m=500.0,
            end_offset_m=1000.0,
            max_speed_ms=20.0,  # Restricted from baseline 40 m/s
            direction="BOTH",
        ),
    ]

    fwd_speed = RouteSpeedProfile(route_fwd, restrictions)
    rev_speed = RouteSpeedProfile(route_rev, restrictions)

    # FORWARD checks:
    # On LNK_AB at physical offset 300m (s=300m): TSR_FWD_ONLY applies (15 m/s)
    assert fwd_speed.get_max_speed_at(300.0) == pytest.approx(15.0, rel=1e-6)
    # On LNK_BC at physical offset 700m (s=1700m): TSR_BOTH applies (20 m/s)
    assert fwd_speed.get_max_speed_at(1700.0) == pytest.approx(20.0, rel=1e-6)

    # REVERSE checks:
    # On LNK_AB (physical offset 300m is s = 2000 + (1000 - 300) = 2700m):
    # TSR_FWD_ONLY must NOT apply in reverse! Baseline speed 30 m/s applies.
    assert rev_speed.get_max_speed_at(2700.0) == pytest.approx(30.0, rel=1e-6)

    # On LNK_BC (physical offset 700m is s = 0 + (2000 - 700) = 1300m):
    # TSR_BOTH MUST apply in reverse (20 m/s).
    assert rev_speed.get_max_speed_at(1300.0) == pytest.approx(20.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p02_006_reverse_chainage():
    """BENCH-P02-006: Reverse Chainage:

    Physical route chainage: 0–10 km (total length 10,000 m).
    When travelling in reverse:
    - Route distance 0 km corresponds to chainage 10 km.
    - Route distance 10 km corresponds to chainage 0 km.
    """
    chainage_model = EngineeringChainageModel([
        ChainageSegment(
            segment_id="REV_CORRIDOR",
            start_route_distance_m=0.0,
            end_route_distance_m=10000.0,
            start_chainage_km=10.0,
            end_chainage_km=0.0,
        )
    ])

    assert chainage_model.route_distance_to_chainage_km(0.0) == pytest.approx(10.0, rel=1e-6)
    assert chainage_model.route_distance_to_chainage_km(5000.0) == pytest.approx(5.0, rel=1e-6)
    assert chainage_model.route_distance_to_chainage_km(10000.0) == pytest.approx(0.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p02_007_train_length_across_links(corridor_graph):
    """BENCH-P02-007: Train Length Across Links:

    Given:
    - Train length: 200 m.
    - Front located 50 m into the second link (LNK_BC), so s_front = 1050 m.
    Expected:
    - 50 m of train occupies LNK_BC.
    - 150 m occupies preceding link (LNK_AB).
    - Total occupied length: 200 m.
    """
    engine = RouteEngine(corridor_graph)
    route_fwd = engine.build_route_from_traversals(
        route_id="RT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )

    footprint = TrainGeometry.compute_footprint(
        route=route_fwd,
        front_distance_m=1050.0,
        train_length_m=200.0,
    )

    assert footprint.train_length_m == 200.0
    assert footprint.front_distance_m == 1050.0
    assert footprint.rear_distance_m == 850.0
    assert len(footprint.link_occupancies) == 2

    occ_by_link = {lo.link_id: lo.occupied_length_m for lo in footprint.link_occupancies}
    assert occ_by_link["LNK_AB"] == pytest.approx(150.0, rel=1e-6)
    assert occ_by_link["LNK_BC"] == pytest.approx(50.0, rel=1e-6)
    assert footprint.total_occupied_length_on_route_m == pytest.approx(200.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p02_008_reverse_train_length(corridor_graph):
    """BENCH-P02-008: Reverse Train Length:

    Repeat BENCH-P02-007 in reverse operation.
    In reverse route (C -> B -> A):
    LNK_BC is 0-2000m, LNK_AB is 2000-3000m.
    Front located 50 m into the second link (LNK_AB), so s_front = 2050 m.
    Expected:
    - 50 m of train occupies LNK_AB.
    - 150 m occupies LNK_BC.
    - Total physical occupied length remains 200 m.
    """
    engine = RouteEngine(corridor_graph)
    route_fwd = engine.build_route_from_traversals(
        route_id="RT_FWD",
        steps=[("LNK_AB", RunningDirection.FORWARD), ("LNK_BC", RunningDirection.FORWARD)],
    )
    route_rev = route_fwd.create_reverse_route(corridor_graph)

    footprint = TrainGeometry.compute_footprint(
        route=route_rev,
        front_distance_m=2050.0,
        train_length_m=200.0,
    )

    assert footprint.train_length_m == 200.0
    assert footprint.front_distance_m == 2050.0
    assert footprint.rear_distance_m == 1850.0
    assert len(footprint.link_occupancies) == 2

    occ_by_link = {lo.link_id: lo.occupied_length_m for lo in footprint.link_occupancies}
    assert occ_by_link["LNK_BC"] == pytest.approx(150.0, rel=1e-6)
    assert occ_by_link["LNK_AB"] == pytest.approx(50.0, rel=1e-6)
    assert footprint.total_occupied_length_on_route_m == pytest.approx(200.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p02_009_tvs_reverse_entry():
    """BENCH-P02-009: TVS Reverse Entry:

    A single track of 15,000 m length (LNK_TNL).
    A TVS section extends physically from physical offset 5,000 m to 10,000 m.
    Forward entry: 5,000 m.
    Reverse entry: 10,000 m (physical). Along reverse route: enters at 5,000 m (15,000 - 10,000).
    The physical TVS geometry remains unchanged.
    """
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_T1", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_T2", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_TNL", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(
        TrackLink(
            link_id="LNK_TNL",
            track_id="TRK_TNL",
            start_node_id="ND_T1",
            end_node_id="ND_T2",
            length_m=15000.0,
            max_speed_ms=45.0,
        )
    )

    tvs_model = TunnelTVSModel()
    tvs_model.add_tunnel(Tunnel(tunnel_id="TNL_01", name="Long Tunnel"))
    tvs_model.add_tvs_section(
        TVSSection(
            tvs_id="TVS_SEC_01",
            tunnel_id="TNL_01",
            track_id="TRK_TNL",
            link_intervals=[
                ResourceInterval(
                    link_id="LNK_TNL",
                    start_offset_m=5000.0,
                    end_offset_m=10000.0,
                )
            ],
            max_train_occupancy=1,
        )
    )

    engine = RouteEngine(graph)
    route_fwd = engine.build_route_from_traversals("RT_FWD", [("LNK_TNL", RunningDirection.FORWARD)])
    route_rev = route_fwd.create_reverse_route(graph, "RT_REV")

    fwd_tvs = tvs_model.resolve_route_tvs_sections(route_fwd)
    rev_tvs = tvs_model.resolve_route_tvs_sections(route_rev)

    assert len(fwd_tvs) == 1
    assert len(rev_tvs) == 1

    # In forward: physical offset 5000m maps to route s = 5000m; physical offset 10000m maps to s = 10000m
    assert fwd_tvs[0].route_entry_distance_m == pytest.approx(5000.0, rel=1e-6)
    assert fwd_tvs[0].route_exit_distance_m == pytest.approx(10000.0, rel=1e-6)
    assert fwd_tvs[0].physical_length_m == pytest.approx(5000.0, rel=1e-6)

    # In reverse: train enters from physical 10000m end.
    # On reverse route of length 15000m: physical 10000m is s = 15000 - 10000 = 5000m!
    # Physical 5000m exit is s = 15000 - 5000 = 10000m!
    assert rev_tvs[0].route_entry_distance_m == pytest.approx(5000.0, rel=1e-6)
    assert rev_tvs[0].route_exit_distance_m == pytest.approx(10000.0, rel=1e-6)
    assert rev_tvs[0].physical_length_m == pytest.approx(5000.0, rel=1e-6)


@pytest.mark.engineering
def test_bench_p02_010_direction_policy():
    """BENCH-P02-010: Direction Policy:

    A FORWARD_ONLY (NOMINAL) track shall reject an unauthorized reverse traversal.
    """
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_UP1", node_type=NodeType.ENDPOINT))
    graph.add_node(Node(node_id="ND_UP2", node_type=NodeType.ENDPOINT))
    graph.add_track(Track(track_id="TRK_UP", directionality=TrackDirectionality.NOMINAL))
    graph.add_link(
        TrackLink(
            link_id="LNK_UP",
            track_id="TRK_UP",
            start_node_id="ND_UP1",
            end_node_id="ND_UP2",
            length_m=2000.0,
            max_speed_ms=35.0,
        )
    )

    engine = RouteEngine(graph)

    # FORWARD traversal must succeed
    route_fwd = engine.build_route_from_traversals("RT_UP_FWD", [("LNK_UP", RunningDirection.FORWARD)])
    assert route_fwd.total_length_m == 2000.0

    # REVERSE traversal must be rejected with DirectionPolicyError
    with pytest.raises(DirectionPolicyError) as exc_info:
        route_fwd.create_reverse_route(graph, "RT_UP_REV")

    assert "prohibits 'REVERSE' traversal" in str(exc_info.value)

    # Direct reverse construction must also fail
    with pytest.raises(DirectionPolicyError):
        engine.build_route_from_traversals("RT_DIRECT_REV", [("LNK_UP", RunningDirection.REVERSE)])
