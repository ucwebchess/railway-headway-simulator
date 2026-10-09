"""Comprehensive unit test suite for Milestone P02 railway infrastructure engine."""

import pytest
import pandas as pd

from headway.data.canonical import (
    InfrastructureModel,
    Node,
    NodeType,
    Platform,
    ResourceGeometry,
    ResourceInterval,
    Station,
    StoppingPoint,
    Track,
    TrackDirectionality,
    TrackLink,
    Tunnel,
    TVSSection,
)
from headway.data.validation import ValidationReport
from headway.infrastructure import (
    AlignmentError,
    ChainageError,
    ChainageSegment,
    DirectionPolicy,
    DirectionPolicyError,
    EngineeringChainageModel,
    InfrastructurePreprocessor,
    InfrastructureValidator,
    InfrastructureVisualizerAdapter,
    JunctionTopology,
    MultiLinkResourceGeometry,
    NetworkTopologyError,
    PhysicalNetworkGraph,
    PhysicalResource,
    PositionMappingError,
    ResourceGeometryError,
    Route,
    RouteAlignmentProfile,
    RouteContinuityError,
    RouteEngine,
    RouteSpeedProfile,
    RunningDirection,
    SpeedProfileError,
    SpeedRestriction,
    StationGeometryError,
    StationPlatformModel,
    Switch,
    SwitchMovement,
    SwitchPosition,
    TrainGeometry,
    TrainGeometryError,
    TunnelTVSModel,
    TVSGeometryError,
)


@pytest.mark.unit
class TestNetworkGraphAndDirectionPolicy:
    """Test physical graph topology, parallel links, and direction policies."""

    def test_direction_policy_permissions(self):
        assert DirectionPolicy.is_traversal_permitted(TrackDirectionality.BIDIRECTIONAL, RunningDirection.FORWARD)
        assert DirectionPolicy.is_traversal_permitted(TrackDirectionality.BIDIRECTIONAL, RunningDirection.REVERSE)

        assert DirectionPolicy.is_traversal_permitted(TrackDirectionality.NOMINAL, RunningDirection.FORWARD)
        assert not DirectionPolicy.is_traversal_permitted(TrackDirectionality.NOMINAL, RunningDirection.REVERSE)

        assert not DirectionPolicy.is_traversal_permitted(TrackDirectionality.REVERSE, RunningDirection.FORWARD)
        assert DirectionPolicy.is_traversal_permitted(TrackDirectionality.REVERSE, RunningDirection.REVERSE)

    def test_duplicate_nodes_rejected(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_01", node_type=NodeType.ENDPOINT))
        with pytest.raises(NetworkTopologyError):
            graph.add_node(Node(node_id="ND_01", node_type=NodeType.ENDPOINT))

    def test_nonpositive_link_length_rejected(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_01", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_02", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

        # Test both pydantic validation and graph add_link guard
        bad_link = TrackLink.model_construct(
            link_id="LNK_BAD",
            track_id="TRK_01",
            start_node_id="ND_01",
            end_node_id="ND_02",
            length_m=0.0,
            max_speed_ms=25.0,
        )
        with pytest.raises(NetworkTopologyError):
            graph.add_link(bad_link)

    def test_missing_node_reference_rejected(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_01", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

        with pytest.raises(NetworkTopologyError):
            graph.add_link(
                TrackLink(
                    link_id="LNK_BAD",
                    track_id="TRK_01",
                    start_node_id="ND_01",
                    end_node_id="ND_NONEXISTENT",
                    length_m=500.0,
                    max_speed_ms=25.0,
                )
            )

    def test_parallel_links_supported(self):
        """P02-INF-002: Parallel physical links connecting the same pair of nodes."""
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_X", node_type=NodeType.JUNCTION))
        graph.add_node(Node(node_id="ND_Y", node_type=NodeType.JUNCTION))
        graph.add_track(Track(track_id="TRK_FAST", directionality=TrackDirectionality.BIDIRECTIONAL))
        graph.add_track(Track(track_id="TRK_SLOW", directionality=TrackDirectionality.BIDIRECTIONAL))

        graph.add_link(
            TrackLink(
                link_id="LNK_PARALLEL_FAST",
                track_id="TRK_FAST",
                start_node_id="ND_X",
                end_node_id="ND_Y",
                length_m=1000.0,
                max_speed_ms=50.0,
            )
        )
        graph.add_link(
            TrackLink(
                link_id="LNK_PARALLEL_SLOW",
                track_id="TRK_SLOW",
                start_node_id="ND_X",
                end_node_id="ND_Y",
                length_m=1100.0,
                max_speed_ms=30.0,
            )
        )

        links_between = graph.get_links_between("ND_X", "ND_Y")
        assert len(links_between) == 2
        link_ids = {l.link_id for l, d in links_between}
        assert link_ids == {"LNK_PARALLEL_FAST", "LNK_PARALLEL_SLOW"}


@pytest.mark.unit
class TestRouteEngineAndContinuity:
    """Test route construction, continuity, distance calculation, and position lookups."""

    def test_route_continuity_break_detected(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_A", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_B", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_C", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_D", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

        graph.add_link(TrackLink(link_id="LNK_1", track_id="TRK_01", start_node_id="ND_A", end_node_id="ND_B", length_m=500.0, max_speed_ms=25.0))
        graph.add_link(TrackLink(link_id="LNK_2", track_id="TRK_01", start_node_id="ND_C", end_node_id="ND_D", length_m=500.0, max_speed_ms=25.0))

        engine = RouteEngine(graph)
        # LNK_1 exits at ND_B, but LNK_2 enters at ND_C (disconnected)
        with pytest.raises(RouteContinuityError) as exc_info:
            engine.build_route_from_traversals("RT_DISCONNECTED", [("LNK_1", RunningDirection.FORWARD), ("LNK_2", RunningDirection.FORWARD)])
        assert "continuity break" in str(exc_info.value)

    def test_out_of_bounds_position_lookups_raise_error(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_1", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_2", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
        graph.add_link(TrackLink(link_id="LNK_1", track_id="TRK_01", start_node_id="ND_1", end_node_id="ND_2", length_m=1000.0, max_speed_ms=25.0))

        engine = RouteEngine(graph)
        route = engine.build_route_from_traversals("RT_1", [("LNK_1", RunningDirection.FORWARD)])

        with pytest.raises(PositionMappingError):
            route.route_distance_to_physical(-10.0)

        with pytest.raises(PositionMappingError):
            route.route_distance_to_physical(1050.0)

        with pytest.raises(PositionMappingError):
            route.physical_to_route_distance("UNKNOWN_LINK", 100.0)

        with pytest.raises(PositionMappingError):
            route.physical_to_route_distance("LNK_1", 1200.0)


@pytest.mark.unit
class TestChainageModel:
    """Test engineering chainage model with equations, reverse gradients, and interpolation."""

    def test_discontinuous_chainage_segments(self):
        """P02-CH-002: Chainage equations / multi-segment with discontinuity."""
        # Segment 1: route 0 - 5000m, chainage 100.0 - 105.0 km
        # Segment 2: route 5000 - 8000m, chainage 200.0 - 203.0 km (chainage equation jump)
        model = EngineeringChainageModel([
            ChainageSegment("SEG_A", 0.0, 5000.0, 100.0, 105.0),
            ChainageSegment("SEG_B", 5000.0, 8000.0, 200.0, 203.0),
        ])

        assert model.route_distance_to_chainage_km(2500.0) == pytest.approx(102.5, rel=1e-6)
        assert model.route_distance_to_chainage_km(6500.0) == pytest.approx(201.5, rel=1e-6)

        # Reverse lookups
        assert model.chainage_km_to_route_distance(102.5) == pytest.approx(2500.0, rel=1e-6)
        assert model.chainage_km_to_route_distance(201.5) == pytest.approx(6500.0, rel=1e-6)

    def test_overlapping_segments_rejected(self):
        with pytest.raises(ChainageError):
            EngineeringChainageModel([
                ChainageSegment("SEG_1", 0.0, 3000.0, 0.0, 3.0),
                ChainageSegment("SEG_2", 2000.0, 5000.0, 2.0, 5.0),
            ])


@pytest.mark.unit
class TestAlignmentGradientsAndCurves:
    """Test multi-section gradient and curve queries."""

    def test_gradient_and_curve_intersection_queries(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_1", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_2", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_3", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))

        graph.add_link(TrackLink(link_id="L1", track_id="TRK_01", start_node_id="ND_1", end_node_id="ND_2", length_m=500.0, max_speed_ms=25.0, gradient_decimal=0.015, curvature_radius_m=1200.0))
        graph.add_link(TrackLink(link_id="L2", track_id="TRK_01", start_node_id="ND_2", end_node_id="ND_3", length_m=500.0, max_speed_ms=25.0, gradient_decimal=-0.010, curvature_radius_m=None))

        engine = RouteEngine(graph)
        route = engine.build_route_from_traversals("RT_ALIGN", [("L1", RunningDirection.FORWARD), ("L2", RunningDirection.FORWARD)])
        profile = RouteAlignmentProfile(route)

        # Query interval [400m, 700m] spanning both links
        grad_intervals = profile.get_gradient_intervals_intersecting(400.0, 700.0)
        assert len(grad_intervals) == 2
        # First overlap is [400, 500] with grad 0.015
        assert grad_intervals[0] == pytest.approx((400.0, 500.0, 0.015), rel=1e-6)
        # Second overlap is [500, 700] with grad -0.010
        assert grad_intervals[1] == pytest.approx((500.0, 700.0, -0.010), rel=1e-6)

        # Curvature query [400m, 700m]
        curve_intervals = profile.get_curvature_intervals_intersecting(400.0, 700.0)
        assert len(curve_intervals) == 2
        assert curve_intervals[0] == (400.0, 500.0, 1200.0)
        assert curve_intervals[1] == (500.0, 700.0, None)


@pytest.mark.unit
class TestSpeedRestrictionsAndProfiles:
    """Test speed restriction validation, category filtering, and overlapping governing speed."""

    def test_overlapping_restrictions_minimum_speed_governs(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_1", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_2", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
        graph.add_link(TrackLink(link_id="L1", track_id="TRK_01", start_node_id="ND_1", end_node_id="ND_2", length_m=1000.0, max_speed_ms=40.0))

        engine = RouteEngine(graph)
        route = engine.build_route_from_traversals("RT_SPD", [("L1", RunningDirection.FORWARD)])

        restrictions = [
            SpeedRestriction("TSR_1", "L1", 200.0, 800.0, max_speed_ms=30.0, direction="BOTH"),
            SpeedRestriction("TSR_2", "L1", 400.0, 600.0, max_speed_ms=20.0, direction="BOTH"),
        ]

        profile = RouteSpeedProfile(route, restrictions)

        # Outside both restrictions: baseline 40 m/s
        assert profile.get_max_speed_at(100.0) == pytest.approx(40.0, rel=1e-6)
        # Inside TSR_1 only: 30 m/s
        assert profile.get_max_speed_at(300.0) == pytest.approx(30.0, rel=1e-6)
        # Inside both TSR_1 and TSR_2: lowest governs (20 m/s)
        assert profile.get_max_speed_at(500.0) == pytest.approx(20.0, rel=1e-6)
        # Inside TSR_1 only: 30 m/s
        assert profile.get_max_speed_at(700.0) == pytest.approx(30.0, rel=1e-6)
        # Outside: baseline 40 m/s
        assert profile.get_max_speed_at(900.0) == pytest.approx(40.0, rel=1e-6)


@pytest.mark.unit
class TestSwitchesAndJunctions:
    """Test switch movements, junction topology, and directional route verification."""

    def test_switch_unauthorized_movement_detected(self):
        junction = JunctionTopology()
        switch = Switch(switch_id="SW_01", node_id="ND_JUNCTION")
        # Permits movement from LNK_IN to LNK_OUT_1 only
        switch.add_movement(SwitchMovement("LNK_IN", "LNK_OUT_1", SwitchPosition.NORMAL))
        junction.register_switch(switch)

        # Valid movement
        assert junction.validate_route_movements(["LNK_IN", "LNK_OUT_1"]) == []

        # Unauthorized movement
        errors = junction.validate_route_movements(["LNK_IN", "LNK_OUT_2"])
        assert len(errors) == 1
        assert "does not permit movement" in errors[0]


@pytest.mark.unit
class TestStationsAndPlatforms:
    """Test platform geometry, stopping positions, and train length coverage."""

    def test_train_stopping_geometry_and_platform_bounds(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="ND_1", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="ND_2", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
        graph.add_link(TrackLink(link_id="LNK_STN", track_id="TRK_01", start_node_id="ND_1", end_node_id="ND_2", length_m=2000.0, max_speed_ms=30.0))

        stn_model = StationPlatformModel()
        stn_model.add_station(Station(station_id="STN_01", name="Alpha Station"))
        stn_model.add_platform(
            Platform(
                platform_id="PLT_01",
                station_id="STN_01",
                link_id="LNK_STN",
                start_offset_m=500.0,
                end_offset_m=900.0,
                length_m=400.0,
            )
        )
        stn_model.add_stopping_point(
            StoppingPoint(
                stopping_point_id="SP_01",
                platform_id="PLT_01",
                link_id="LNK_STN",
                offset_m=850.0,  # Front stops at 850m
            )
        )

        engine = RouteEngine(graph)
        route_fwd = engine.build_route_from_traversals("RT_STN", [("LNK_STN", RunningDirection.FORWARD)])
        stops = stn_model.resolve_route_stops(route_fwd)

        assert len(stops) == 1
        stop = stops[0]
        assert stop.stopping_position_m == 850.0

        # Train of length 200m stops at 850m -> rear is at 650m (both inside platform [500, 900])
        s_rear, s_front, fits = stop.evaluate_train_stopping_interval(train_length_m=200.0)
        assert s_front == 850.0
        assert s_rear == 650.0
        assert fits is True

        # Train of length 400m stops at 850m -> rear is at 450m (protrudes before platform start 500m)
        s_rear, s_front, fits = stop.evaluate_train_stopping_interval(train_length_m=400.0)
        assert s_rear == 450.0
        assert fits is False


@pytest.mark.unit
class TestMultiLinkResourcesAndIntersections:
    """Test multi-link resource geometry and spatial intersection calculations."""

    def test_multi_link_resource_intersection_and_occupied_length(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="N1", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="N2", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="N3", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
        graph.add_link(TrackLink(link_id="LK1", track_id="TRK_01", start_node_id="N1", end_node_id="N2", length_m=1000.0, max_speed_ms=30.0))
        graph.add_link(TrackLink(link_id="LK2", track_id="TRK_01", start_node_id="N2", end_node_id="N3", length_m=1000.0, max_speed_ms=30.0))

        engine = RouteEngine(graph)
        route = engine.build_route_from_traversals("RT_RES", [("LK1", RunningDirection.FORWARD), ("LK2", RunningDirection.FORWARD)])

        res_model = MultiLinkResourceGeometry()
        # Resource spanning from LK1:800m to LK2:300m (total physical length 500m)
        res_model.register_resource(
            PhysicalResource(
                resource_id="RES_CROSSOVER",
                intervals=[
                    ResourceInterval(link_id="LK1", start_offset_m=800.0, end_offset_m=1000.0),
                    ResourceInterval(link_id="LK2", start_offset_m=0.0, end_offset_m=300.0),
                ],
            )
        )

        # Route interval [900m, 1100m] intersects the resource
        assert res_model.intersects_route_interval(route, 900.0, 1100.0, "RES_CROSSOVER") is True
        # Occupied length in [900m, 1100m] is 200m (100m on LK1 + 100m on LK2)
        occ_len = res_model.occupied_length_in_route_interval(route, 900.0, 1100.0, "RES_CROSSOVER")
        assert occ_len == pytest.approx(200.0, rel=1e-6)

        # Non-intersecting interval [0m, 500m]
        assert res_model.intersects_route_interval(route, 0.0, 500.0, "RES_CROSSOVER") is False
        assert res_model.occupied_length_in_route_interval(route, 0.0, 500.0, "RES_CROSSOVER") == 0.0


@pytest.mark.unit
class TestTrainGeometryBoundaries:
    """Test train footprint and boundary conditions (protrusion before origin or after terminus)."""

    def test_train_extending_before_route_origin(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="N1", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="N2", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
        graph.add_link(TrackLink(link_id="L1", track_id="TRK_01", start_node_id="N1", end_node_id="N2", length_m=1000.0, max_speed_ms=30.0))

        engine = RouteEngine(graph)
        route = engine.build_route_from_traversals("RT_BND", [("L1", RunningDirection.FORWARD)])

        # Train of length 200m with front at 50m (rear is at -150m, outside route)
        footprint = TrainGeometry.compute_footprint(route, front_distance_m=50.0, train_length_m=200.0)

        assert footprint.extends_before_origin is True
        assert footprint.uncovered_length_before_origin_m == pytest.approx(150.0, rel=1e-6)
        assert footprint.total_occupied_length_on_route_m == pytest.approx(50.0, rel=1e-6)
        # Invariant: total physical length remains 200m (P02-LEN-005)
        assert footprint.total_physical_length_m == pytest.approx(200.0, rel=1e-6)


@pytest.mark.unit
class TestPreprocessorAndVisualizationAdapters:
    """Test RouteProfile caching, baseline immutability, and visualization dataframes."""

    def test_preprocessor_and_adapter_export(self):
        graph = PhysicalNetworkGraph()
        graph.add_node(Node(node_id="A", node_type=NodeType.ENDPOINT))
        graph.add_node(Node(node_id="B", node_type=NodeType.ENDPOINT))
        graph.add_track(Track(track_id="T1", directionality=TrackDirectionality.BIDIRECTIONAL))
        link = TrackLink(link_id="LK_1", track_id="T1", start_node_id="A", end_node_id="B", length_m=1000.0, max_speed_ms=25.0, gradient_decimal=0.005)
        graph.add_link(link)

        infra = InfrastructureModel(
            nodes=[Node(node_id="A", node_type=NodeType.ENDPOINT), Node(node_id="B", node_type=NodeType.ENDPOINT)],
            tracks=[Track(track_id="T1", directionality=TrackDirectionality.BIDIRECTIONAL)],
            track_links=[link],
            stations=[Station(station_id="STN_A", name="Station A")],
            platforms=[Platform(platform_id="PLT_A", station_id="STN_A", link_id="LK_1", start_offset_m=100.0, end_offset_m=300.0, length_m=200.0)],
            stopping_points=[StoppingPoint(stopping_point_id="SP_A", platform_id="PLT_A", link_id="LK_1", offset_m=280.0)],
            tunnels=[],
            tvs_sections=[],
            shared_resource_groups=[],
        )

        preprocessor = InfrastructurePreprocessor(infra)
        engine = RouteEngine(graph)
        route_fwd = engine.build_route_from_traversals("RT_TEST", [("LK_1", RunningDirection.FORWARD)])

        profile_fwd = preprocessor.preprocess_route(route_fwd, RunningDirection.FORWARD)
        profile_rev = preprocessor.preprocess_route(route_fwd, RunningDirection.REVERSE)

        # Baseline immutability: original canonical link was not modified
        assert link.gradient_decimal == 0.005

        # Forward profile has +0.005, reverse profile has -0.005
        assert profile_fwd.get_gradient_at(500.0) == pytest.approx(0.005, rel=1e-6)
        assert profile_rev.get_gradient_at(500.0) == pytest.approx(-0.005, rel=1e-6)

        # Visualization Dataframe Exports
        adapter = InfrastructureVisualizerAdapter()
        df_nodes = adapter.get_nodes_dataframe(profile_fwd)
        assert isinstance(df_nodes, pd.DataFrame)
        assert len(df_nodes) == 2

        df_trav = adapter.get_traversals_dataframe(profile_fwd)
        assert len(df_trav) == 1

        df_grad = adapter.get_gradients_dataframe(profile_fwd)
        assert len(df_grad) == 1

        df_curv = adapter.get_curvature_dataframe(profile_fwd)
        assert len(df_curv) == 1

        df_spd = adapter.get_speed_profile_dataframe(profile_fwd)
        assert len(df_spd) >= 1

        df_stn = adapter.get_stations_dataframe(profile_fwd)
        assert len(df_stn) == 1
        assert df_stn.iloc[0]["station_id"] == "STN_A"
