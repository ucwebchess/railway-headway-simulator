"""Excel to Canonical Project conversion and unit normalization.

Strictly satisfies RHS-P01-001 § 4, § 5, and § 11:
- Normalizes all engineering-friendly input units into pure internal SI units.
- Transforms raw worksheet dictionaries into validated Pydantic CanonicalProject models.
"""

from typing import Any, Dict, List, Optional
from headway.core.units import (
    normalize_davis_coefficients,
    normalize_force,
    normalize_gradient,
    normalize_mass,
    normalize_power,
    normalize_speed,
    normalize_time,
)
from headway.data.canonical import (
    AnalysisConfig,
    AnalysisModel,
    AnalysisType,
    AspectModelType,
    BrakingCurvePoint,
    BrakingModelType,
    BrakingSemantics,
    CanonicalProject,
    InfrastructureModel,
    InterlockingRoute,
    Node,
    NodeType,
    OperationsModel,
    Platform,
    ResourceInterval,
    RollingStockModel,
    Scenario,
    ScenarioOverride,
    ServicePattern,
    SharedResourceGroup,
    Signal,
    SignallingBlock,
    SignallingModel,
    SignallingSystem,
    SignallingTechnologyType,
    SignalType,
    Station,
    StationStop,
    StoppingPoint,
    Track,
    TrackDirectionality,
    TrackLink,
    TractionCurvePoint,
    TractionModelType,
    TrainType,
    Tunnel,
    TVSSection,
)
from headway.data.importer import RawWorkbookData


def convert_raw_to_canonical(
    raw_workbooks: Dict[str, RawWorkbookData],
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
) -> CanonicalProject:
    """Convert parsed raw Excel workbooks into a CanonicalProject with SI units."""
    # Project metadata
    prj_id = project_id or "PRJ_DEFAULT"
    prj_name = project_name or "Railway Headway Simulation Project"

    # Extract metadata from any available workbook
    for wb in raw_workbooks.values():
        if "PROJECT_ID" in wb.metadata and not project_id:
            prj_id = wb.metadata["PROJECT_ID"]
        if "DESCRIPTION" in wb.metadata and not project_name:
            prj_name = wb.metadata["DESCRIPTION"]

    # 1. Convert Infrastructure
    infra_model = _build_infrastructure_model(raw_workbooks.get("INFRASTRUCTURE"))

    # 2. Convert Rolling Stock
    rs_model = _build_rolling_stock_model(raw_workbooks.get("ROLLING_STOCK"))

    # 3. Convert Signalling
    sig_model = _build_signalling_model(raw_workbooks.get("SIGNALLING"))

    # 4. Convert Operations
    ops_model = _build_operations_model(raw_workbooks.get("OPERATIONS"))

    # 5. Convert Analysis
    an_model = _build_analysis_model(raw_workbooks.get("HEADWAY_ANALYSIS"))

    # 6. Convert Scenarios
    scenarios = _build_scenarios(raw_workbooks.get("SCENARIOS"))

    return CanonicalProject(
        project_id=prj_id,
        name=prj_name,
        schema_version="1.0.0",
        infrastructure=infra_model,
        rolling_stock=rs_model,
        signalling=sig_model,
        operations=ops_model,
        analysis=an_model,
        scenarios=scenarios,
        provenance={"converted_from_excel": True},
    )


def _build_infrastructure_model(infra_wb: Optional[RawWorkbookData]) -> InfrastructureModel:
    if not infra_wb:
        return InfrastructureModel()

    nodes = [
        Node(
            node_id=r["node_id"],
            description=r.get("description"),
            node_type=NodeType(r.get("node_type", "ENDPOINT")),
        )
        for r in infra_wb.get_rows("Nodes")
    ]

    tracks = [
        Track(
            track_id=r["track_id"],
            description=r.get("description"),
            directionality=TrackDirectionality(r.get("directionality", "BIDIRECTIONAL")),
        )
        for r in infra_wb.get_rows("Tracks")
    ]

    track_links = [
        TrackLink(
            link_id=r["link_id"],
            track_id=r["track_id"],
            start_node_id=r["start_node_id"],
            end_node_id=r["end_node_id"],
            length_m=float(r["length_m"]),
            max_speed_ms=normalize_speed(r["max_speed_ms"], "km/h"),
            gradient_decimal=normalize_gradient(r.get("gradient_decimal", 0.0), "‰"),
            curvature_radius_m=float(r["curvature_radius_m"]) if r.get("curvature_radius_m") else None,
        )
        for r in infra_wb.get_rows("TrackLinks")
    ]

    stations = [
        Station(
            station_id=r["station_id"],
            name=r["name"],
            chainage_km=float(r["chainage_km"]) if r.get("chainage_km") is not None else None,
        )
        for r in infra_wb.get_rows("Stations")
    ]

    platforms = [
        Platform(
            platform_id=r["platform_id"],
            station_id=r["station_id"],
            link_id=r["link_id"],
            start_offset_m=float(r["start_offset_m"]),
            end_offset_m=float(r["end_offset_m"]),
            length_m=float(r["length_m"]),
        )
        for r in infra_wb.get_rows("Platforms")
    ]

    stopping_points = [
        StoppingPoint(
            stopping_point_id=r["stopping_point_id"],
            platform_id=r["platform_id"],
            link_id=r["link_id"],
            offset_m=float(r["offset_m"]),
        )
        for r in infra_wb.get_rows("StoppingPoints")
    ]

    tunnels = [
        Tunnel(
            tunnel_id=r["tunnel_id"],
            name=r["name"],
            description=r.get("description"),
        )
        for r in infra_wb.get_rows("Tunnels")
    ]

    tvs_sections = [
        TVSSection(
            tvs_id=r["tvs_id"],
            tunnel_id=r["tunnel_id"],
            track_id=r["track_id"],
            link_intervals=[
                ResourceInterval(
                    link_id=r["link_id"],
                    start_offset_m=float(r["start_offset_m"]),
                    end_offset_m=float(r["end_offset_m"]),
                )
            ],
            max_train_occupancy=int(r.get("max_train_occupancy", 1)),
            holding_signal_id=r.get("holding_signal_id"),
            release_delay_s=float(r.get("release_delay_s", 0.0)),
        )
        for r in infra_wb.get_rows("TVSSections")
    ]

    shared_groups = [
        SharedResourceGroup(
            group_id=r["group_id"],
            description=r.get("description"),
            resource_ids=r["resource_ids"] if isinstance(r["resource_ids"], list) else [r["resource_ids"]],
        )
        for r in infra_wb.get_rows("SharedResourceGroups")
    ]

    return InfrastructureModel(
        dataset_id=infra_wb.metadata.get("DATASET_ID", "INFRA_DATASET_01"),
        nodes=nodes,
        tracks=tracks,
        track_links=track_links,
        stations=stations,
        platforms=platforms,
        stopping_points=stopping_points,
        tunnels=tunnels,
        tvs_sections=tvs_sections,
        shared_resource_groups=shared_groups,
    )


def _build_rolling_stock_model(rs_wb: Optional[RawWorkbookData]) -> RollingStockModel:
    if not rs_wb:
        return RollingStockModel()

    # Build curves maps
    traction_curves_map: Dict[str, List[TractionCurvePoint]] = {}
    for r in rs_wb.get_rows("TractionCurves"):
        tid = r["train_type_id"]
        pt = TractionCurvePoint(
            speed_ms=normalize_speed(r["speed_ms"], "km/h"),
            force_n=normalize_force(r["force_n"], "kN"),
        )
        traction_curves_map.setdefault(tid, []).append(pt)

    braking_curves_map: Dict[str, List[BrakingCurvePoint]] = {}
    for r in rs_wb.get_rows("BrakingCurves"):
        tid = r["train_type_id"]
        pt = BrakingCurvePoint(
            speed_ms=normalize_speed(r["speed_ms"], "km/h"),
            deceleration_ms2=float(r["deceleration_ms2"]),
        )
        braking_curves_map.setdefault(tid, []).append(pt)

    train_types = []
    for r in rs_wb.get_rows("TrainTypes"):
        tid = r["train_type_id"]
        # Normalize Davis coefficients: input is kN, kN/(km/h), kN/(km/h)² -> N, N*s/m, N*s²/m²
        d_a, d_b, d_c = normalize_davis_coefficients(
            a=float(r["davis_a_n"]),
            b=float(r["davis_b_ns_m"]),
            c=float(r["davis_c_ns2_m2"]),
            force_unit="kN",
            speed_unit="km/h",
        )

        tt = TrainType(
            train_type_id=tid,
            description=r["description"],
            length_m=float(r["length_m"]),
            mass_empty_kg=normalize_mass(r["mass_empty_kg"], "tonnes"),
            mass_loaded_kg=normalize_mass(r["mass_loaded_kg"], "tonnes"),
            rotating_mass_factor=float(r.get("rotating_mass_factor", 0.10)),
            max_speed_ms=normalize_speed(r["max_speed_ms"], "km/h"),
            max_acceleration_ms2=float(r.get("max_acceleration_ms2", 1.0)),
            max_service_deceleration_ms2=float(r["max_service_deceleration_ms2"]),
            emergency_deceleration_ms2=float(r["emergency_deceleration_ms2"]),
            traction_model_type=TractionModelType(r.get("traction_model_type", "SIMPLIFIED_POWER_FORCE")),
            power_w=normalize_power(r["power_w"], "kW") if r.get("power_w") is not None else None,
            max_tractive_effort_n=normalize_force(r["max_tractive_effort_n"], "kN") if r.get("max_tractive_effort_n") is not None else None,
            traction_curve=traction_curves_map.get(tid, []),
            braking_model_type=BrakingModelType(r.get("braking_model_type", "CONSTANT_DECELERATION")),
            braking_semantics=BrakingSemantics(r.get("braking_semantics", "NET_EFFECTIVE")),
            braking_curve=braking_curves_map.get(tid, []),
            davis_a_n=d_a,
            davis_b_ns_m=d_b,
            davis_c_ns2_m2=d_c,
        )
        train_types.append(tt)

    return RollingStockModel(
        dataset_id=rs_wb.metadata.get("DATASET_ID", "RS_DATASET_01"),
        train_types=train_types,
    )


def _build_signalling_model(sig_wb: Optional[RawWorkbookData]) -> SignallingModel:
    if not sig_wb:
        return SignallingModel()

    # System parameters
    sys_rows = sig_wb.get_rows("SignallingSystem")
    if sys_rows:
        sr = sys_rows[0]
        sig_sys = SignallingSystem(
            technology_type=SignallingTechnologyType(sr.get("technology_type", "GENERIC_FIXED_BLOCK_ENGINEERING_MODEL")),
            aspect_model=AspectModelType(sr.get("aspect_model", "THREE_ASPECT")),
            default_overlap_m=float(sr.get("default_overlap_m", 50.0)),
            sighting_time_s=float(sr.get("sighting_time_s", 8.0)),
            route_setup_time_s=float(sr.get("route_setup_time_s", 3.0)),
            release_delay_s=float(sr.get("release_delay_s", 4.0)),
        )
    else:
        sig_sys = SignallingSystem()

    signals = [
        Signal(
            signal_id=r["signal_id"],
            link_id=r["link_id"],
            offset_m=float(r["offset_m"]),
            direction=TrackDirectionality(r.get("direction", "NOMINAL")),
            signal_type=SignalType(r.get("signal_type", "MAIN")),
            sighting_distance_m=float(r.get("sighting_distance_m", 200.0)),
        )
        for r in sig_wb.get_rows("Signals")
    ]

    blocks = [
        SignallingBlock(
            block_id=r["block_id"],
            entry_signal_id=r.get("entry_signal_id"),
            exit_signal_id=r.get("exit_signal_id"),
            link_intervals=[
                ResourceInterval(
                    link_id=r["link_id"],
                    start_offset_m=float(r["start_offset_m"]),
                    end_offset_m=float(r["end_offset_m"]),
                )
            ],
            overlap_m=float(r.get("overlap_m", 50.0)),
            release_delay_s=float(r.get("release_delay_s", 4.0)),
        )
        for r in sig_wb.get_rows("Blocks")
    ]

    routes = [
        InterlockingRoute(
            route_id=r["route_id"],
            entry_signal_id=r["entry_signal_id"],
            exit_signal_id=r["exit_signal_id"],
            link_sequence=r["link_sequence"] if isinstance(r["link_sequence"], list) else [r["link_sequence"]],
            protected_blocks=r.get("protected_blocks", []) if isinstance(r.get("protected_blocks"), list) else ([r["protected_blocks"]] if r.get("protected_blocks") else []),
            conflicting_route_ids=r.get("conflicting_routes", []) if isinstance(r.get("conflicting_routes"), list) else ([r["conflicting_routes"]] if r.get("conflicting_routes") else []),
        )
        for r in sig_wb.get_rows("InterlockingRoutes")
    ]

    return SignallingModel(
        dataset_id=sig_wb.metadata.get("DATASET_ID", "SIG_DATASET_01"),
        system=sig_sys,
        signals=signals,
        blocks=blocks,
        routes=routes,
    )


def _build_operations_model(ops_wb: Optional[RawWorkbookData]) -> OperationsModel:
    if not ops_wb:
        return OperationsModel()

    # Group stops by service pattern
    stops_map: Dict[str, List[StationStop]] = {}
    for r in sorted(ops_wb.get_rows("StoppingPatterns"), key=lambda x: x.get("stop_index", 0)):
        spid = r["service_pattern_id"]
        st = StationStop(
            station_id=r["station_id"],
            platform_id=r["platform_id"],
            dwell_time_s=float(r["dwell_time_s"]),
            min_dwell_s=float(r.get("min_dwell_s", 0.0)),
            is_mandatory_stop=bool(r.get("is_mandatory_stop", True)),
        )
        stops_map.setdefault(spid, []).append(st)

    service_patterns = [
        ServicePattern(
            service_pattern_id=r["service_pattern_id"],
            train_type_id=r["train_type_id"],
            route_link_sequence=r["route_link_sequence"] if isinstance(r["route_link_sequence"], list) else [r["route_link_sequence"]],
            priority=int(r.get("priority", 1)),
            planned_headway_s=normalize_time(r.get("planned_headway_s", 3.0), "min"),
            stops=stops_map.get(r["service_pattern_id"], []),
        )
        for r in ops_wb.get_rows("ServicePatterns")
    ]

    return OperationsModel(
        dataset_id=ops_wb.metadata.get("DATASET_ID", "OPS_DATASET_01"),
        service_patterns=service_patterns,
    )


def _build_analysis_model(an_wb: Optional[RawWorkbookData]) -> AnalysisModel:
    if not an_wb:
        return AnalysisModel()

    analyses = [
        AnalysisConfig(
            analysis_id=r["analysis_id"],
            analysis_type=AnalysisType(r.get("analysis_type", "PAIRWISE_HEADWAY")),
            leader_service_id=r.get("leader_service_id"),
            follower_service_id=r.get("follower_service_id"),
            integration_step_s=float(r.get("integration_step_s", 0.1)),
            headway_tolerance_s=float(r.get("headway_tolerance_s", 0.1)),
            search_time_window_s=float(r.get("search_time_window_s", 600.0)),
            planning_margin_s=float(r.get("planning_margin_s", 30.0)),
            reference_link_id=r.get("reference_link_id"),
            reference_offset_m=float(r["reference_offset_m"]) if r.get("reference_offset_m") is not None else None,
        )
        for r in an_wb.get_rows("AnalysisSettings")
    ]

    return AnalysisModel(
        dataset_id=an_wb.metadata.get("DATASET_ID", "AN_DATASET_01"),
        analyses=analyses,
    )


def _build_scenarios(scn_wb: Optional[RawWorkbookData]) -> List[Scenario]:
    if not scn_wb:
        # Provide default baseline scenario
        return [Scenario(scenario_id="SCN_BASELINE", description="Default Baseline Scenario", is_baseline=True)]

    overrides_map: Dict[str, List[ScenarioOverride]] = {}
    for r in scn_wb.get_rows("Overrides"):
        sid = r["scenario_id"]
        ov = ScenarioOverride(
            target_domain=r["target_domain"],
            target_object_id=r["target_object_id"],
            parameter_name=r["parameter_name"],
            override_value=r["override_value"],
            justification=r.get("justification"),
        )
        overrides_map.setdefault(sid, []).append(ov)

    scenarios = []
    for r in scn_wb.get_rows("ScenarioDefinitions"):
        sid = r["scenario_id"]
        scn = Scenario(
            scenario_id=sid,
            description=r["description"],
            is_baseline=bool(r.get("is_baseline", False)),
            overrides=overrides_map.get(sid, []),
        )
        scenarios.append(scn)

    if not scenarios:
        scenarios.append(Scenario(scenario_id="SCN_BASELINE", description="Default Baseline Scenario", is_baseline=True))

    return scenarios
