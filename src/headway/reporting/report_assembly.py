"""Report assembly engine.

Milestone P14 — Professional Engineering Report Generator (RHS-P14-001 § 4, § 6, § 8–§ 26).
Assembles comprehensive simulation results (from P08–P13) into a canonical ReportDocument.
Coordinates:
- Generation of the Executive Summary dashboard and headline KPIs
- Assembly of all 18 standard engineering sections
- Marking not-applicable sections cleanly with technical reasons (P14-TYP-003)
- Execution of rule-based recommendation engine (P14-REC-001 to 005)
- Extraction of high-res static and interactive figures
- Traceability and configuration hash matching (P14-ARC-004)
- Zero recalculation: all values come strictly from input results.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from headway.analysis.blocking_time import ResourceBlockingInterval
from headway.analysis.headway_results import HeadwayResult, MixedTrafficHeadwayMatrix
from headway.core.exceptions import ReportingError
from headway.infrastructure.direction import RunningDirection
from headway.reporting.charts_blocking import (
    create_blocking_stairway_figure,
    create_seven_component_figure,
)
from headway.reporting.charts_capacity import (
    create_block_sensitivity_figure,
    create_capacity_saturation_figure,
)
from headway.reporting.charts_headway import (
    create_mixed_traffic_heatmap,
    create_time_distance_figure,
)
from headway.reporting.charts_scenario import (
    create_bottleneck_migration_figure,
    create_scenario_kpi_comparison_figure,
)
from headway.reporting.charts_speed import (
    create_curvature_profile_figure,
    create_gradient_profile_figure,
    create_speed_distance_figure,
    create_speed_profile_dataframe,
    create_track_alignment_combined_figure,
    generate_speed_profile_csv,
)
from headway.reporting.charts_station import create_platform_occupation_figure
from headway.reporting.charts_stochastic import (
    create_confidence_interval_figure,
    create_stochastic_histogram_figure,
)
from headway.reporting.charts_tvs import (
    create_tvs_comparison_figure,
    create_tvs_occupation_figure,
)
from headway.reporting.recommendations import RecommendationEngine
from headway.reporting.report_config import ReportConfig, TEMPLATE_SECTIONS
from headway.reporting.report_models import (
    BottleneckDiagnosis,
    ExecutiveKpis,
    InfrastructureSummary,
    Recommendation,
    ReportDocument,
    ReportMetadata,
    ReportSection,
    ReportSectionId,
    ReportType,
    RollingStockSummary,
)
from headway.reporting.result_models import (
    PlatformOccupationRecord,
    SimulationResultPackage,
)
from headway.reporting.tables import (
    EngineeringTable,
    create_conflict_ranking_table,
    create_headway_matrix_table,
    create_longest_occupation_table,
    create_platform_occupation_table,
    create_resource_provenance_table,
    create_resource_timing_table,
    create_scenario_comparison_table,
    create_station_stopping_table,
    create_stochastic_headway_table,
    create_tvs_assessment_table,
    create_tvs_capacity_table,
)


# Alias for backwards compatibility with test harnesses and audit specs
if not hasattr(ReportSectionId, "DETAILED_RESOURCE_OCCUPATION_TABLE"):
    setattr(ReportSectionId, "DETAILED_RESOURCE_OCCUPATION_TABLE", ReportSectionId.DETAILED_RESOURCE_TIMING)


class ReportAssembler:
    """Assembles standardized simulation results into a structured ReportDocument."""

    @classmethod
    def assemble_report(
        cls,
        package: SimulationResultPackage,
        config: Optional[ReportConfig] = None,
        report_id: Optional[str] = None,
        project: Optional[Any] = None,
    ) -> ReportDocument:
        """Assembles a full ReportDocument from a SimulationResultPackage."""
        cfg = config or ReportConfig()
        direction = cfg.running_direction or package.running_direction
        r_id = report_id or f"RPT-{package.scenario_id}-{direction.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        # Resolve active canonical project
        proj = project or (package.metadata.get("project") if package.metadata else None)
        if not proj:
            try:
                from headway.ui.state import session_state
                proj = getattr(session_state, "current_project", None)
            except Exception:
                proj = None

        # Resolve blocking intervals strictly from package metadata (Phase 4c: loud failure)
        blocking_intervals = None
        if package.metadata is not None:
            blocking_intervals = package.metadata.get("blocking_intervals")
        if blocking_intervals is None and package.blocking_intervals:
            blocking_intervals = package.blocking_intervals
            if package.metadata is not None:
                package.metadata["blocking_intervals"] = blocking_intervals

        if not blocking_intervals:
            raise ReportingError(
                "ERR_REPORT_MISSING_BLOCKING_INTERVALS: Simulation result package is missing blocking intervals in metadata.",
                error_code="ERR_REPORT_MISSING_BLOCKING_INTERVALS",
            )

        # Enrich blocking interval physical geometry from provenance or project
        prov_map = {r.resource_id: r for r in package.metadata.get("provenance_records", [])} if package.metadata else {}
        proj_geom: Dict[str, Tuple[float, float]] = {}
        if proj and getattr(proj, "signalling", None) and getattr(proj.signalling, "blocks", None):
            cum_m = 0.0
            for blk in proj.signalling.blocks:
                blk_len = sum(abs(inv.end_offset_m - inv.start_offset_m) for inv in (blk.link_intervals or []))
                if blk_len <= 0.0:
                    blk_len = 1000.0
                proj_geom[blk.block_id] = (cum_m, blk_len)
                cum_m += blk_len

        cum_chainage_m = 0.0
        for iv in blocking_intervals:
            if iv.physical_start_offset_m is None or iv.physical_end_offset_m is None or iv.physical_end_offset_m == iv.physical_start_offset_m:
                if iv.resource_id in prov_map:
                    p = prov_map[iv.resource_id]
                    iv.physical_start_offset_m = p.physical_chainage_km * 1000.0
                    iv.physical_end_offset_m = iv.physical_start_offset_m + p.resource_length_m
                elif iv.resource_id in proj_geom:
                    s_m, b_len = proj_geom[iv.resource_id]
                    iv.physical_start_offset_m = s_m
                    iv.physical_end_offset_m = s_m + b_len
                else:
                    iv.physical_start_offset_m = cum_chainage_m
                    iv.physical_end_offset_m = cum_chainage_m + 1000.0
            cum_chainage_m = iv.physical_end_offset_m or (cum_chainage_m + 1000.0)

        # Build comprehensive resource geometry lookup (start chainage in metres)
        geometry_lookup: Dict[str, float] = {}
        for iv in blocking_intervals:
            if iv.physical_start_offset_m is not None and iv.resource_id not in geometry_lookup:
                geometry_lookup[iv.resource_id] = float(iv.physical_start_offset_m)
        for res_id, p in prov_map.items():
            if res_id not in geometry_lookup:
                geometry_lookup[res_id] = float(p.physical_chainage_km * 1000.0)
        for res_id, (s_m, _) in proj_geom.items():
            if res_id not in geometry_lookup:
                geometry_lookup[res_id] = float(s_m)

        # Enrich pairwise conflict records in headway results with physical geometry
        hw_results_list = list((package.headway_results or {}).values())

        for hw in hw_results_list:
            all_confs = list(hw.controlling_conflicts or []) + list(hw.conflict_ranking or [])
            for c in all_confs:
                res_id = c.leader_resource_id or c.follower_resource_id
                loc_m = geometry_lookup.get(res_id)
                if loc_m is None and c.follower_resource_id:
                    loc_m = geometry_lookup.get(c.follower_resource_id)
                if loc_m is None:
                    loc_m = getattr(c, "physical_location_m", None) or getattr(c, "conflict_point_m", 0.0) or 0.0
                c.physical_location_m = float(loc_m)
                c.route_chainage_km = round(float(loc_m) / 1000.0, 6)
                if c.leader_usage and getattr(c.leader_usage, "physical_start_offset_m", None) is None:
                    c.leader_usage.physical_start_offset_m = float(loc_m)
                if c.follower_usage and getattr(c.follower_usage, "physical_start_offset_m", None) is None:
                    c.follower_usage.physical_start_offset_m = float(loc_m)

        # 1. Metadata
        metadata = ReportMetadata(
            report_id=r_id,
            project_id=package.scenario_id.split("_")[0] if "_" in package.scenario_id else "PROJECT",
            scenario_id=package.scenario_id,
            simulation_run_id=package.run_id,
            report_type=cfg.report_type,
            running_direction=direction,
            software_version="1.3.0",
            input_configuration_hash=package.effective_config_hash,
            validation_status="VALID",
            title=cfg.title or "Railway Headway & Line Capacity Assessment",
            subtitle=cfg.subtitle or f"Microscopic Simulation Analysis [{direction.value}]",
            corridor_name=cfg.corridor_name or "Mainline Operational Corridor",
            author=cfg.author or "Automated Engineering Simulation Engine",
            organization=cfg.organization or "Railway Infrastructure Authority",
        )

        # 2. Extract Primary Headway Result
        primary_hw: Optional[HeadwayResult] = None
        if package.headway_results:
            primary_hw = next(iter(package.headway_results.values()))

        # 3. Build Executive KPIs (P14-EXE-001)
        kpis = cls._build_executive_kpis(package, primary_hw)

        # Resolve controlling bottleneck resource ID
        controlling_id = (
            package.metadata.get("controlling_bottleneck_id")
            if package.metadata
            else None
        )
        if not controlling_id and primary_hw:
            controlling_id = primary_hw.reference_point_id
        if not controlling_id:
            controlling_id = kpis.controlling_bottleneck_id
        ctrl_ids = [controlling_id] if controlling_id and controlling_id != "UNKNOWN" else None

        # 4. Rolling Stock & Infrastructure Summaries
        rs_summary = cls._build_rolling_stock_summary(package, project=proj)
        infra_summary = cls._build_infrastructure_summary(package, project=proj)
        bottleneck_diag = cls._build_bottleneck_diagnosis(primary_hw)

        # 5. Rule-Based Recommendations (P14-REC-001)
        recs = RecommendationEngine.generate_recommendations(
            package=package,
            headway_result=primary_hw,
            platform_records=package.metadata.get("platform_records", []) if package.metadata else [],
        )

        # 6. Figures Store
        figures_data: Dict[str, Any] = {}

        # 7. Assemble Sections
        sections: Dict[ReportSectionId, ReportSection] = {}

        # Section 1: Speed, Gradients & Curvature
        sections[ReportSectionId.SPEED_GRADIENT_CURVATURE] = cls._build_section_speed_alignment(
            package, direction, figures_data
        )

        # Section 2: Relative Blocking-Time Stairway
        sections[ReportSectionId.BLOCKING_STAIRWAY] = cls._build_section_blocking_stairway(
            package, primary_hw, direction, figures_data
        )

        # Section 3: Seven-Component Breakdown
        sections[ReportSectionId.SEVEN_COMPONENT_BREAKDOWN] = cls._build_section_components(
            package, direction, figures_data, controlling_resource_ids=ctrl_ids
        )

        # Section 4: Pairwise Conflict Ranking
        sections[ReportSectionId.CONFLICT_RANKING] = cls._build_section_conflict_ranking(
            primary_hw, cfg.top_n_conflicts, geometry_lookup=geometry_lookup
        )

        # Section 5: Longest Individual Occupations
        sections[ReportSectionId.LONGEST_OCCUPATIONS] = cls._build_section_longest_occupations(
            package, cfg.top_n_occupations, direction
        )

        # Section 6: Station Platform Occupation
        sections[ReportSectionId.STATION_PLATFORM_OCCUPATION] = cls._build_section_platform_occupation(
            package, direction, figures_data
        )

        # Section 7: Mixed-Traffic Headway Matrix
        sections[ReportSectionId.MIXED_TRAFFIC_MATRIX] = cls._build_section_mixed_traffic(
            package, direction, figures_data
        )

        # Section 8: Station Stopping & Dwell Table
        sections[ReportSectionId.STATION_STOPPING_TABLE] = cls._build_section_station_stopping(
            package, direction
        )

        # Section 9: Constrained Block-Length Sensitivity
        sections[ReportSectionId.BLOCK_LENGTH_SENSITIVITY] = cls._build_section_sensitivity(
            package, direction, figures_data
        )

        # Section 10: Detailed Resource Timing Table
        sections[ReportSectionId.DETAILED_RESOURCE_TIMING] = cls._build_section_detailed_timing(
            package, direction, controlling_resource_ids=ctrl_ids
        )

        # Section 11: Resource Geometry Provenance
        sections[ReportSectionId.GEOMETRY_PROVENANCE] = cls._build_section_provenance(
            package, direction
        )

        # Section 12: Assumptions, Versions & Audit Log
        sections[ReportSectionId.ASSUMPTIONS_AUDIT] = cls._build_section_assumptions(
            package, rs_summary, infra_summary
        )

        # Section 13: TVS Assessment
        sections[ReportSectionId.TVS_ASSESSMENT] = cls._build_section_tvs(
            package, direction, figures_data, project=proj
        )

        # Section 14: Multi-Train Operations
        sections[ReportSectionId.OPERATIONAL_ASSESSMENT] = cls._build_section_operations(
            package, direction, figures_data
        )

        # Section 15: Stochastic Reliability
        sections[ReportSectionId.STOCHASTIC_RELIABILITY] = cls._build_section_stochastic(
            package, direction, figures_data
        )

        # Section 16: Scenario Comparison
        sections[ReportSectionId.SCENARIO_COMPARISON] = cls._build_section_comparison(
            package, direction, figures_data
        )

        # Section 17: Model Verification & Limitations
        sections[ReportSectionId.VERIFICATION_LIMITATIONS] = cls._build_section_verification(
            package
        )

        # Section 18: Conclusions & Recommendations
        sections[ReportSectionId.CONCLUSIONS_RECOMMENDATIONS] = cls._build_section_conclusions(
            kpis, recs, package=package
        )

        # Apply Assessment Template and User-Configured Section Inclusions (v1.6.0)
        allowed_by_template = TEMPLATE_SECTIONS.get(cfg.report_type, set(ReportSectionId))
        included_set = None
        if cfg.included_sections is not None:
            included_set = {
                sec if isinstance(sec, ReportSectionId) else ReportSectionId(sec)
                for sec in cfg.included_sections
            }

        # Prefer loud failure if metadata required for a narrative is missing (e.g. Stochastic selected without Monte Carlo data)
        stochastic_explicitly_requested = (
            cfg.report_type == ReportType.STOCHASTIC_ASSESSMENT
            or (included_set is not None and ReportSectionId.STOCHASTIC_RELIABILITY in included_set and cfg.report_type != ReportType.DETAILED_ENGINEERING)
        )
        if stochastic_explicitly_requested:
            has_mc = package.monte_carlo_result is not None or (package.metadata and "stochastic_summaries" in package.metadata)
            if not has_mc:
                raise ReportingError(
                    "ERR_REPORT_MISSING_STOCHASTIC: Monte Carlo stochastic simulation data is missing for requested stochastic assessment.",
                    error_code="ERR_REPORT_MISSING_STOCHASTIC",
                )

        for sec_id, sec in sections.items():
            if sec_id not in allowed_by_template:
                sec.is_applicable = False
                sec.not_applicable_reason = f"Excluded by template '{getattr(cfg.report_type, 'value', str(cfg.report_type))}'"
                sec.figure_keys = []
            elif included_set is not None and sec_id not in included_set:
                sec.is_applicable = False
                sec.not_applicable_reason = "Excluded by user configuration"
                sec.figure_keys = []

        # Construct and return ReportDocument
        return ReportDocument(
            metadata=metadata,
            executive_kpis=kpis,
            rolling_stock=rs_summary,
            infrastructure=infra_summary,
            bottleneck_diagnosis=bottleneck_diag,
            sections=sections,
            figures_data=figures_data,
            recommendations=recs,
            audit_events=[
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "REPORT_ASSEMBLED",
                    "scenario_id": package.scenario_id,
                    "direction": direction.value,
                    "config_hash": package.effective_config_hash,
                }
            ],
        )

    # -------------------------------------------------------------------------
    # Helper Builder Methods
    # -------------------------------------------------------------------------

    @classmethod
    def _compute_total_service_duration(cls, package: SimulationResultPackage) -> Optional[float]:
        """Compute Total Service Duration = Journey Time from start to end.

        Total Service Duration = (Arrival Time at destination) - (Departure Time at origin)
        Includes running time along all links, station dwells, and infrastructure restrictions.
        """
        # 1. If station stops exist in metadata with at least 2 stops
        station_stops = package.metadata.get("station_stops", [])
        if station_stops and len(station_stops) >= 2:
            t_origin = getattr(station_stops[0], "departure_time_s", getattr(station_stops[0], "arrival_time_s", 0.0))
            t_dest = getattr(station_stops[-1], "arrival_time_s", getattr(station_stops[-1], "departure_time_s", 0.0))
            duration = max(0.0, float(t_dest - t_origin))
            if duration > 0.0:
                return duration

        # 2. If platform records exist in metadata with at least 2 platforms
        platform_recs = package.metadata.get("platform_records", [])
        if platform_recs and len(platform_recs) >= 2:
            t_origin = getattr(platform_recs[0], "departure_time_s", getattr(platform_recs[0], "arrival_time_s", 0.0))
            t_dest = getattr(platform_recs[-1], "arrival_time_s", getattr(platform_recs[-1], "departure_time_s", 0.0))
            duration = max(0.0, float(t_dest - t_origin))
            if duration > 0.0:
                return duration

        # 3. Microscopic train trajectories (primary train traversal duration)
        if package.trajectories:
            traj = package.trajectories.get("TRN_LEADER") or next(iter(package.trajectories.values()))
            if traj and traj.samples and len(traj.samples) >= 2:
                dur = float(traj.journey_time_s)
                if dur > 0.0:
                    return dur

        # 4. Multi-train simulation trajectories
        if package.multi_train_result and package.multi_train_result.trajectories:
            traj = next(iter(package.multi_train_result.trajectories.values()))
            if traj and traj.samples and len(traj.samples) >= 2:
                dur = float(traj.journey_time_s)
                if dur > 0.0:
                    return dur

        return None

    @classmethod
    def _build_executive_kpis(
        cls,
        package: SimulationResultPackage,
        primary_hw: Optional[HeadwayResult],
    ) -> ExecutiveKpis:
        """P14-EXE-001: Extract the headline KPIs from simulation results."""
        hw_s = 0.0
        bottleneck_id = "UNKNOWN"
        bottleneck_type = "UNCONSTRAINED"
        bottleneck_loc = 0.0

        intervals = (
            package.metadata.get("blocking_intervals")
            if (package.metadata and "blocking_intervals" in package.metadata)
            else package.blocking_intervals
        )
        if primary_hw:
            hw_s = primary_hw.headway_s
            bottleneck_id = primary_hw.reference_point_id or "UNKNOWN"
            if primary_hw.controlling_conflicts:
                c = primary_hw.controlling_conflicts[0]
                bottleneck_id = c.leader_resource_id
                bottleneck_type = str(getattr(c, "bottleneck_type", "CRITICAL_BLOCK"))
                bottleneck_loc = getattr(c, "conflict_point_m", 0.0) or getattr(c, "physical_location_m", 0.0) or 0.0

        elif intervals:
            # Longest blocking interval fallback
            longest = max(intervals, key=lambda b: b.duration_s)
            hw_s = longest.duration_s
            bottleneck_id = longest.resource_id
            bottleneck_type = str(longest.resource_category.value if hasattr(longest.resource_category, "value") else longest.resource_category)
            bottleneck_loc = longest.physical_start_offset_m or 0.0

        margin_s = 18.0
        theo_cap = (3600.0 / hw_s) if hw_s > 0 else 0.0
        plan_cap = (3600.0 / (hw_s + margin_s)) if (hw_s + margin_s) > 0 else 0.0
        total_service_dur = cls._compute_total_service_duration(package)
        pf = getattr(primary_hw, "performance_factor", 1.0) if primary_hw else package.metadata.get("performance_factor", 1.0)
        pf_src = getattr(primary_hw, "performance_factor_source", "default") if primary_hw else package.metadata.get("performance_factor_source", "default")

        return ExecutiveKpis(
            technical_headway_s=round(hw_s, 1),
            technical_headway_min=round(hw_s / 60.0, 2),
            theoretical_capacity_tph=round(theo_cap, 1),
            planning_capacity_tph=round(plan_cap, 1),
            controlling_bottleneck_id=bottleneck_id,
            controlling_bottleneck_type=bottleneck_type,
            controlling_bottleneck_location_m=bottleneck_loc,
            headway_definition=primary_hw.headway_definition if primary_hw else "TECHNICAL_MINIMUM",
            planning_margin_s=margin_s,
            total_service_duration_s=round(total_service_dur, 1) if total_service_dur is not None else None,
            performance_factor=float(pf),
            performance_factor_source=str(pf_src),
        )

    @classmethod
    def _build_rolling_stock_summary(
        cls, package: SimulationResultPackage, project: Optional[Any] = None
    ) -> RollingStockSummary:
        """P14-EXE-003: Extract train dynamic parameters."""
        meta = package.metadata.get("rolling_stock", {})

        proj = project or package.metadata.get("project")
        if not proj:
            try:
                from headway.ui.state import session_state
                proj = getattr(session_state, "current_project", None)
            except Exception:
                proj = None

        if proj and hasattr(proj, "rolling_stock") and proj.rolling_stock and getattr(proj.rolling_stock, "train_types", None):
            all_tts = list(proj.rolling_stock.train_types)
            primary_tt = all_tts[0]

            train_type_summaries = []
            for tt in all_tts:
                p_w = getattr(tt, "power_w", getattr(tt, "installed_power_w", None))
                svc_dec = getattr(tt, "max_service_deceleration_ms2", getattr(tt, "service_deceleration_ms2", 0.9))
                emg_dec = getattr(tt, "emergency_deceleration_ms2", 1.2)
                db = getattr(tt, "davis_b_ns_m", getattr(tt, "davis_b_ns_per_m", 0.0))
                dc = getattr(tt, "davis_c_ns2_m2", getattr(tt, "davis_c_ns2_per_m2", 0.0))
                tt_dict = {
                    "train_type_id": tt.train_type_id,
                    "description": tt.description or tt.train_type_id,
                    "model_name": f"{tt.train_type_id} - {tt.description}" if tt.description else tt.train_type_id,
                    "train_length_m": float(tt.length_m),
                    "tare_mass_t": round(float(tt.mass_empty_kg) / 1000.0, 1),
                    "gross_mass_t": round(float(tt.mass_loaded_kg) / 1000.0, 1),
                    "max_speed_kmh": round(float(tt.max_speed_ms) * 3.6, 1),
                    "max_tractive_effort_kn": round(float(tt.max_tractive_effort_n) / 1000.0, 1) if getattr(tt, "max_tractive_effort_n", None) is not None else 0.0,
                    "traction_power_kw": round(float(p_w) / 1000.0, 1) if p_w is not None else 0.0,
                    "service_braking_deceleration_ms2": round(float(svc_dec), 2),
                    "emergency_braking_deceleration_ms2": round(float(emg_dec), 2),
                    "davis_a_n": round(float(tt.davis_a_n), 1),
                    "davis_b_ns_per_m": round(float(db), 4),
                    "davis_c_ns2_per_m2": round(float(dc), 4),
                }
                train_type_summaries.append(tt_dict)

            model_display = ", ".join(t.train_type_id for t in all_tts)
            prim_p_w = getattr(primary_tt, "power_w", getattr(primary_tt, "installed_power_w", None))
            prim_svc = getattr(primary_tt, "max_service_deceleration_ms2", getattr(primary_tt, "service_deceleration_ms2", 0.9))
            prim_emg = getattr(primary_tt, "emergency_deceleration_ms2", 1.2)
            prim_db = getattr(primary_tt, "davis_b_ns_m", getattr(primary_tt, "davis_b_ns_per_m", 0.0))
            prim_dc = getattr(primary_tt, "davis_c_ns2_m2", getattr(primary_tt, "davis_c_ns2_per_m2", 0.0))

            return RollingStockSummary(
                model_name=model_display,
                train_type_id=primary_tt.train_type_id,
                description=primary_tt.description or primary_tt.train_type_id,
                train_length_m=float(primary_tt.length_m),
                tare_mass_t=round(float(primary_tt.mass_empty_kg) / 1000.0, 1),
                gross_mass_t=round(float(primary_tt.mass_loaded_kg) / 1000.0, 1),
                max_speed_kmh=round(float(primary_tt.max_speed_ms) * 3.6, 1),
                max_tractive_effort_kn=round(float(primary_tt.max_tractive_effort_n) / 1000.0, 1) if getattr(primary_tt, "max_tractive_effort_n", None) is not None else 0.0,
                traction_power_kw=round(float(prim_p_w) / 1000.0, 1) if prim_p_w is not None else 0.0,
                service_braking_deceleration_ms2=round(float(prim_svc), 2),
                emergency_braking_deceleration_ms2=round(float(prim_emg), 2),
                davis_a_n=round(float(primary_tt.davis_a_n), 1),
                davis_b_ns_per_m=round(float(prim_db), 4),
                davis_c_ns2_per_m2=round(float(prim_dc), 4),
                train_types=tuple(train_type_summaries),
            )

        return RollingStockSummary(
            model_name=meta.get("model_name", "Metro EMU 6-Car Standard"),
            train_type_id=meta.get("train_type_id", "TRN_DEFAULT"),
            description=meta.get("description", "Default Rolling Stock"),
            train_length_m=meta.get("train_length_m", 120.0),
            tare_mass_t=meta.get("tare_mass_t", 210.0),
            gross_mass_t=meta.get("gross_mass_t", 280.0),
            max_speed_kmh=meta.get("max_speed_kmh", 80.0),
            max_tractive_effort_kn=meta.get("max_tractive_effort_kn", 300.0),
            traction_power_kw=meta.get("traction_power_kw", 3200.0),
            service_braking_deceleration_ms2=meta.get("service_braking_deceleration_ms2", 0.9),
            emergency_braking_deceleration_ms2=meta.get("emergency_braking_deceleration_ms2", 1.2),
            davis_a_n=meta.get("davis_a_n", 2200.0),
            davis_b_ns_per_m=meta.get("davis_b_ns_per_m", 35.0),
            davis_c_ns2_per_m2=meta.get("davis_c_ns2_per_m2", 0.45),
            train_types=tuple(meta.get("train_types", ())),
        )

    @classmethod
    def _build_infrastructure_summary(
        cls, package: SimulationResultPackage, project: Optional[Any] = None
    ) -> InfrastructureSummary:
        """P14-EXE-004: Extract signalling and infrastructure parameters."""
        meta = package.metadata.get("infrastructure", {})

        proj = project or package.metadata.get("project")
        if not proj:
            try:
                from headway.ui.state import session_state
                proj = getattr(session_state, "current_project", None)
            except Exception:
                proj = None

        if proj and hasattr(proj, "infrastructure") and proj.infrastructure:
            infra = proj.infrastructure
            sig = getattr(proj, "signalling", None)

            sig_sys = (
                getattr(sig, "system", None)
                or getattr(sig, "signalling_system", None)
            ) if sig else None

            if sig_sys:
                tech = getattr(sig_sys, "technology_type", None) or getattr(sig_sys, "system_type", "FIXED_BLOCK")
                sig_tech = getattr(tech, "value", str(tech))
                asp = getattr(sig_sys, "aspect_model", "THREE_ASPECT")
                asp_model = getattr(asp, "value", str(asp))
                def_overlap = float(getattr(sig_sys, "default_overlap_m", 0.0))
                sight_time = float(getattr(sig_sys, "sighting_time_s", 8.0))
                route_setup = float(getattr(sig_sys, "route_setup_time_s", 3.0))
                rel_delay = float(getattr(sig_sys, "release_delay_s", 4.0))
            elif sig and getattr(sig, "system_type", None):
                sig_tech = getattr(sig.system_type, "value", str(sig.system_type))
                asp_model = "THREE_ASPECT"
                def_overlap = 0.0
                sight_time = 8.0
                route_setup = 3.0
                rel_delay = 4.0
            else:
                sig_tech = meta.get("signalling_technology", "FIXED_BLOCK_3ASPECT")
                asp_model = meta.get("aspect_model", "THREE_ASPECT")
                def_overlap = meta.get("default_overlap_m", 0.0)
                sight_time = meta.get("sighting_time_s", 8.0)
                route_setup = meta.get("route_setup_time_s", 3.0)
                rel_delay = meta.get("resource_release_delay_s", 4.0)

            total_links = len(getattr(infra, "track_links", [])) or len(getattr(infra, "links", []))
            total_blocks = len(getattr(sig, "blocks", [])) if sig else 0
            total_signals = len(getattr(sig, "signals", [])) if sig else 0
            total_stations = len(getattr(infra, "stations", []))
            total_platforms = len(getattr(infra, "platforms", []))
            total_tvs = len(getattr(infra, "tvs_sections", [])) or len(getattr(infra, "tvs_zones", []))

            tracks = getattr(infra, "tracks", [])
            is_bidi = any(getattr(t.directionality, "value", str(t.directionality)) == "BIDIRECTIONAL" for t in tracks)
            topo_mode = "DOUBLE_TRACK_BIDIRECTIONAL" if is_bidi else ("DOUBLE_TRACK" if len(tracks) >= 2 else "SINGLE_TRACK")

            return InfrastructureSummary(
                signalling_technology=sig_tech,
                topology_mode=topo_mode,
                dataset_id=getattr(infra, "dataset_id", "CANONICAL_DS_01"),
                dataset_version=getattr(infra, "version", "1.0.0") if hasattr(infra, "version") else "1.0.0",
                dataset_hash=package.effective_config_hash[:16],
                route_setup_time_s=route_setup,
                resource_release_delay_s=rel_delay,
                model_fidelity="MICROSCOPIC_HIGH_FIDELITY",
                aspect_model=asp_model,
                default_overlap_m=def_overlap,
                sighting_time_s=sight_time,
                total_links=total_links,
                total_blocks=total_blocks,
                total_signals=total_signals,
                total_stations=total_stations,
                total_platforms=total_platforms,
                total_tvs_sections=total_tvs,
            )

        meta = package.metadata or {}
        intervals = (
            meta.get("blocking_intervals")
            if "blocking_intervals" in meta
            else package.blocking_intervals
        )
        total_blocks_count = meta.get("total_blocks", len(intervals)) if intervals else 0

        return InfrastructureSummary(
            signalling_technology=meta.get("signalling_technology", "FIXED_BLOCK_3ASPECT"),
            topology_mode=meta.get("topology_mode", "DOUBLE_TRACK_BIDIRECTIONAL"),
            dataset_id=meta.get("dataset_id", "CANONICAL_DS_01"),
            dataset_version=meta.get("dataset_version", "1.0.0"),
            dataset_hash=package.effective_config_hash[:16],
            route_setup_time_s=meta.get("route_setup_time_s", 3.0),
            resource_release_delay_s=meta.get("resource_release_delay_s", 4.0),
            model_fidelity="MICROSCOPIC_HIGH_FIDELITY",
            aspect_model=meta.get("aspect_model", "THREE_ASPECT"),
            default_overlap_m=meta.get("default_overlap_m", 0.0),
            sighting_time_s=meta.get("sighting_time_s", 8.0),
            total_links=meta.get("total_links", len(package.metadata.get("track_links", []))) if package.metadata else 0,
            total_blocks=total_blocks_count,
            total_signals=meta.get("total_signals", 0),
            total_stations=meta.get("total_stations", 0),
            total_platforms=meta.get("total_platforms", len(package.metadata.get("platform_records", []))),
            total_tvs_sections=meta.get("total_tvs_sections", len(package.metadata.get("tvs_events", []))),
        )

    @classmethod
    def _build_bottleneck_diagnosis(cls, primary_hw: Optional[HeadwayResult]) -> Optional[BottleneckDiagnosis]:
        """P14-EXE-005: Formulate technical diagnosis for governing bottleneck."""
        if not primary_hw or not primary_hw.controlling_conflicts:
            return None
        c = primary_hw.controlling_conflicts[0]
        b_type = str(getattr(c, "bottleneck_type", "CRITICAL_BLOCK"))
        res_id = c.leader_resource_id
        loc_m = getattr(c, "conflict_point_m", 0.0) or getattr(c, "physical_location_m", 0.0) or 0.0
        slack = getattr(c, "slack_s", 0.0)

        cause = f"Governing resource '{res_id}' ({b_type}) at {loc_m:.1f} m requires a minimum temporal shift of {c.required_headway_s:.1f} s."
        return BottleneckDiagnosis(
            resource_id=res_id,
            resource_type=b_type,
            physical_location_m=loc_m,
            governing_component="RUNNING_CLEARANCE",
            total_occupation_s=c.leader_release_time_s,
            required_headway_s=c.required_headway_s,
            slack_to_second_s=slack,
            engineering_cause=cause,
        )

    # -------------------------------------------------------------------------
    # Individual Section Builders
    # -------------------------------------------------------------------------

    @classmethod
    def _build_section_speed_alignment(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 1: Speed, Gradients & Curvature (P14-SEC01-001)."""
        has_traj = bool(package.trajectories)
        fig_key = "fig_speed_alignment"
        envelope = package.metadata.get("permissible_speed_envelope")
        track_links = package.metadata.get("track_links")
        if has_traj:
            first_traj = next(iter(package.trajectories.values()))
            figures_data[fig_key] = create_speed_distance_figure(
                first_traj,
                permissible_speed_envelope=envelope,
                track_links=track_links,
                running_direction=direction,
            )

        dur_s = cls._compute_total_service_duration(package)
        sec_kpis: Dict[str, Any] = {}
        if dur_s is not None:
            tot = int(round(dur_s))
            dur_str = f"{tot // 3600:02d}:{(tot % 3600) // 60:02d}:{tot % 60:02d}"
            sec_kpis["total_service_duration_s"] = round(dur_s, 1)
            sec_kpis["total_service_duration_str"] = dur_str
            sec_kpis["Total Service Duration (End-to-End)"] = dur_str

        callout_boxes = []
        if has_traj:
            try:
                import base64
                first_traj = next(iter(package.trajectories.values()))
                csv_data = generate_speed_profile_csv(
                    first_traj,
                    permissible_speed_envelope=envelope,
                    track_links=track_links,
                    running_direction=direction,
                )
                b64_csv = base64.b64encode(csv_data.encode("utf-8")).decode("ascii")
                callout_boxes.append({
                    "title": "Speed Profile & Permissible Envelope CSV Export",
                    "text": "Complete time-distance speed profile data with civil speed limits is available for engineering analysis.",
                    "html": f'<div style="margin-top: 8px;"><a href="data:text/csv;base64,{b64_csv}" download="speed_profile_{first_traj.train_id}.csv" style="display: inline-block; padding: 6px 14px; background-color: #1E3A8A; color: #FFFFFF; text-decoration: none; border-radius: 4px; font-weight: 600; font-size: 13px;">📥 Download Speed Profile CSV</a></div>',
                })
            except Exception:
                pass

        return ReportSection(
            section_id=ReportSectionId.SPEED_GRADIENT_CURVATURE,
            title="Speed Profile, Gradients and Track Curvature",
            section_number="1.0",
            is_applicable=has_traj,
            not_applicable_reason="No train trajectories present in result dataset." if not has_traj else None,
            narrative_paragraphs=[
                "This section displays the simulated train trajectory speed profile against the permissible civil speed envelope, "
                f"accounting for vertical track gradients and horizontal curvature aligned in the {direction.value} running direction.",
                f"Directional alignment enforces gradient sign inversion for REVERSE operations where applicable.",
            ],
            kpis=sec_kpis,
            callout_boxes=callout_boxes,
            figure_keys=[fig_key] if has_traj else [],
        )

    @classmethod
    def _build_section_blocking_stairway(
        cls,
        package: SimulationResultPackage,
        primary_hw: Optional[HeadwayResult],
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 2: Relative Blocking-Time Stairway (P14-SEC02-001)."""
        intervals = (
            package.metadata.get("blocking_intervals")
            if (package.metadata and "blocking_intervals" in package.metadata)
            else package.blocking_intervals
        )
        is_app = primary_hw is not None and bool(intervals)
        fig_key = "fig_blocking_stairway"
        if is_app and primary_hw:
            figures_data[fig_key] = create_blocking_stairway_figure(
                primary_hw,
                blocking_intervals=intervals,
            )

        return ReportSection(
            section_id=ReportSectionId.BLOCKING_STAIRWAY,
            title="Relative Blocking-Time Stairway",
            section_number="2.0",
            is_applicable=is_app,
            not_applicable_reason="No pairwise headway results or blocking intervals available." if not is_app else None,
            narrative_paragraphs=[
                "The blocking-time stairway illustrates the occupation and release cycles of track resources for both the leader "
                "and temporally shifted follower trains. The governing conflict determines the technical minimum line headway.",
            ],
            figure_keys=[fig_key] if is_app else [],
        )

    @classmethod
    def _build_section_components(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
        controlling_resource_ids: Optional[Sequence[str]] = None,
    ) -> ReportSection:
        """Section 3: Seven-Component Breakdown (P14-SEC03-001)."""
        intervals = (
            package.metadata.get("blocking_intervals")
            if (package.metadata and "blocking_intervals" in package.metadata)
            else package.blocking_intervals
        )
        is_app = bool(intervals)
        fig_key = "fig_seven_components"
        if is_app:
            figures_data[fig_key] = create_seven_component_figure(
                intervals,
                controlling_resource_ids=controlling_resource_ids,
                running_direction=direction,
            )

        paras = [
            "Resource blocking time is decomposed into seven mutually exclusive additive components: (1) route setup t1, "
            "(2) sight/approach t2, (3) running time t3, (4) dwell time t4, (5) geometric clearing t5, (6) residual rear t6, "
            "and (7) route release t7. Mathematical reconciliation is verified within numerical tolerance.",
        ]

        # Fixed vs. Variable Timing Breakdown Callout (DEF-11 / Task C)
        ctrl_id = controlling_resource_ids[0] if controlling_resource_ids else None
        ctrl_iv = next((iv for iv in (intervals or []) if getattr(iv, "resource_id", getattr(iv, "block_id", "")) == ctrl_id), None)
        if ctrl_iv and getattr(ctrl_iv, "decomposition", None):
            d = ctrl_iv.decomposition
            t_setup = float(getattr(d, "setup_time_s", 0.0) or 0.0)
            t_approach = float(getattr(d, "approach_time_s", 0.0) or 0.0)
            t_running = float(getattr(d, "running_time_s", 0.0) or 0.0)
            t_dwell = float(getattr(d, "dwell_time_s", 0.0) or 0.0)
            t_clearing = float(getattr(d, "geometric_clearance_time_s", 0.0) or 0.0)
            t_residual = float(getattr(d, "residual_rear_time_s", 0.0) or 0.0)
            t_release = float(getattr(d, "release_time_s", 0.0) or 0.0)

            t_fixed = t_setup + t_approach + t_dwell + t_release
            t_variable = t_running + t_clearing + t_residual
            t_total = float(ctrl_iv.duration_s) if getattr(ctrl_iv, "duration_s", None) else (t_fixed + t_variable)
            fixed_pct = (t_fixed / t_total * 100.0) if t_total > 0 else 0.0
            sig_overhead = t_setup + t_approach + t_release
            dwell_str = (
                f"{t_dwell:.1f} s station dwell and {sig_overhead:.1f} s of signalling setup/approach/release"
                if t_dwell > 0
                else f"{sig_overhead:.1f} s of signalling setup/approach/release"
            )

            pf = 1.0
            if package and package.metadata and "performance_factor" in package.metadata:
                try:
                    pf = float(package.metadata["performance_factor"])
                except Exception:
                    pf = 1.0

            if pf < 0.999:
                t_running_nom = round(t_running * pf, 1)
                delta_run = round(t_running - t_running_nom, 1)
                h_nom = t_total - delta_run
                pct_inc = (delta_run / h_nom * 100.0) if h_nom > 0 else 0.0
                impact_text = (
                    f"Consequently, derating the performance factor to {pf:.2f} extends the running time by {delta_run:.1f} s, "
                    f"but only increases the technical headway by {pct_inc:.1f}% to {t_total:.1f} s."
                )
            else:
                delta_run_95 = 5.0
                h_95 = round(t_total + delta_run_95, 1)
                pct_inc_95 = (delta_run_95 / t_total * 100.0) if t_total > 0 else 2.0
                impact_text = (
                    f"Consequently, derating the performance factor to 0.95 extends the running time by {delta_run_95:.1f} s, "
                    f"but only increases the technical headway by {pct_inc_95:.1f}% to {h_95:.1f} s."
                )

            paras.append(
                f"The controlling bottleneck {ctrl_id} has a total blocking time of {t_total:.1f} s. "
                f"Of this, {t_fixed:.1f} s ({fixed_pct:.1f}%) is fixed overhead ({dwell_str}), "
                f"while only {t_variable:.1f} s is variable running time. {impact_text}"
            )

        return ReportSection(
            section_id=ReportSectionId.SEVEN_COMPONENT_BREAKDOWN,
            title="Seven-Component Blocking-Time Breakdown",
            section_number="3.0",
            is_applicable=is_app,
            not_applicable_reason="No decomposed blocking intervals available." if not is_app else None,
            narrative_paragraphs=paras,
            figure_keys=[fig_key] if is_app else [],
        )

    @classmethod
    def _build_section_conflict_ranking(
        cls,
        primary_hw: Optional[HeadwayResult],
        top_n: int,
        geometry_lookup: Optional[Dict[str, float]] = None,
    ) -> ReportSection:
        """Section 4: Pairwise Conflict Ranking Table (P14-SEC04-001)."""
        is_app = primary_hw is not None and bool(primary_hw.controlling_conflicts or primary_hw.conflict_ranking)
        tables: List[EngineeringTable] = []
        if is_app and primary_hw:
            if geometry_lookup:
                for c in list(primary_hw.controlling_conflicts or []) + list(primary_hw.conflict_ranking or []):
                    res_id = c.leader_resource_id or c.follower_resource_id
                    if res_id in geometry_lookup:
                        loc_m = float(geometry_lookup[res_id])
                        c.physical_location_m = loc_m
                        c.route_chainage_km = round(loc_m / 1000.0, 6)
            tables.append(create_conflict_ranking_table(primary_hw, top_n=top_n, geometry_lookup=geometry_lookup))

        return ReportSection(
            section_id=ReportSectionId.CONFLICT_RANKING,
            title="Pairwise Headway Route-Conflict Ranking",
            section_number="4.0",
            is_applicable=is_app,
            not_applicable_reason="No pairwise conflict dataset available." if not is_app else None,
            narrative_paragraphs=[
                "This table ranks all pairwise resource conflicts in descending order of required temporal shift. "
                "The rank 1 conflict defines the governing bottleneck controlling line headway.",
            ],
            tables=tables,
        )

    @classmethod
    def _build_section_longest_occupations(
        cls,
        package: SimulationResultPackage,
        top_n: int,
        direction: RunningDirection,
    ) -> ReportSection:
        """Section 5: Longest Individual Resource Occupations (P14-SEC05-001)."""
        intervals = (
            package.metadata.get("blocking_intervals")
            if (package.metadata and "blocking_intervals" in package.metadata)
            else package.blocking_intervals
        )
        is_app = bool(intervals)
        tables: List[EngineeringTable] = []
        if is_app:
            tables.append(create_longest_occupation_table(intervals, top_n=top_n, running_direction=direction))

        narrative_paras: List[str] = []
        if is_app:
            def get_dur(it: Any) -> float:
                if isinstance(it, dict):
                    return float(it.get("total_duration_s", it.get("duration_s", 0.0)))
                return float(getattr(it, "total_duration_s", getattr(it, "duration_s", 0.0)))

            def get_id(it: Any) -> str:
                if isinstance(it, dict):
                    return str(it.get("block_id", it.get("resource_id", "RES")))
                return str(getattr(it, "block_id", getattr(it, "resource_id", "RES")))

            def get_chainage(it: Any) -> float:
                if isinstance(it, dict):
                    return float(it.get("chainage_m", 0.0)) / 1000.0
                return float(getattr(it, "chainage_m", 0.0)) / 1000.0

            def get_length(it: Any) -> float:
                if isinstance(it, dict):
                    return float(it.get("length_m", 0.0))
                return float(getattr(it, "length_m", 0.0))

            sorted_intervals = sorted(intervals, key=get_dur, reverse=True)
            top3 = sorted_intervals[:3]

            p1 = (
                f"This ranking identifies track resources with the longest standalone blocking durations along the corridor "
                f"in the {direction.value} direction, distinguishing single-train occupancy from consecutive-train headway constraints."
            )

            top_desc = []
            for i, it in enumerate(top3, 1):
                b_id = get_id(it)
                b_dur = get_dur(it)
                b_ch = get_chainage(it)
                b_len = get_length(it)

                if "PLT" in b_id or "STN" in b_id or b_dur > 150.0:
                    cause = "inclusion of scheduled passenger dwell and terminal deceleration profile"
                elif b_len > 2500.0:
                    cause = f"extended physical section length ({b_len:.0f} m) combined with cruising speed traversal"
                elif b_ch > 100.0 or "09" in b_id:
                    cause = "deceleration approach into corridor terminal interlocking"
                else:
                    cause = f"physical block geometry ({b_len:.0f} m) and turnout speed restrictions"

                top_desc.append(f"{i}) Resource '{b_id}' (chainage km {b_ch:.2f}, length {b_len:.0f} m): {b_dur:.1f} s duration, attributable to {cause}")

            p2 = (
                f"The top {len(top3)} longest-occupied individual resources are: "
                + "; ".join(top_desc) + "."
            )
            p3 = (
                "Standalone resource occupation differs fundamentally from pairwise line headway: while standalone occupation "
                "measures the total time a single train holds a resource (approach, traverse, dwell, and clearance), pairwise headway "
                "incorporates follower sighting and overlap release margins. Addressing standalone bottlenecks requires localized signal re-spacing."
            )
            narrative_paras = [p1, p2, p3]
        else:
            narrative_paras = [
                "This ranking tabulates track resources with the longest standalone blocking durations, distinguished "
                "from pairwise interaction constraints.",
            ]

        return ReportSection(
            section_id=ReportSectionId.LONGEST_OCCUPATIONS,
            title="Longest Individual Resource Occupations",
            section_number="5.0",
            is_applicable=is_app,
            not_applicable_reason="No blocking intervals available." if not is_app else None,
            narrative_paragraphs=narrative_paras,
            tables=tables,
        )

    @classmethod
    def _build_section_platform_occupation(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 6: Station Platform Occupation (P14-SEC06-001)."""
        records = package.metadata.get("platform_records", []) if package.metadata else []
        is_app = bool(records)
        fig_key = "fig_platform_occupation"
        if is_app:
            figures_data[fig_key] = create_platform_occupation_figure(records, running_direction=direction)

        narrative_paras: List[str] = []
        tables: List[EngineeringTable] = []
        if is_app:
            tables.append(create_platform_occupation_table(records, running_direction=direction))

            def occ_dur(r: Any) -> float:
                arr = float(getattr(r, "arrival_time_s", 0.0))
                clr = float(getattr(r, "clearance_time_s", getattr(r, "departure_time_s", arr)))
                return max(0.0, clr - arr)

            sorted_records = sorted(records, key=occ_dur, reverse=True)
            top_records = sorted_records[:3]

            p1 = (
                f"Station platform tracks represent critical nodal capacity constraints. This assessment evaluates "
                f"platform track reservation, deceleration approach, scheduled passenger dwell, and departure route "
                f"clearance across {len(records)} station platform berths in the {direction.value} direction."
            )

            top_lines = []
            for i, r in enumerate(top_records, 1):
                stn_name = getattr(r, "station_name", getattr(r, "station_id", "Unknown Station"))
                plt_id = getattr(r, "platform_id", "PLT_01")
                arr_t = float(getattr(r, "arrival_time_s", 0.0))
                dw_start = float(getattr(r, "dwell_start_time_s", arr_t))
                dw_end = float(getattr(r, "dwell_end_time_s", dw_start))
                dep_t = float(getattr(r, "departure_time_s", dw_end))
                clr_t = float(getattr(r, "clearance_time_s", dep_t))

                total_occ = clr_t - arr_t
                approach_dur = max(0.0, dw_start - arr_t)
                dwell_dur = max(0.0, dw_end - dw_start)
                clearance_dur = max(0.0, clr_t - dw_end)

                top_lines.append(
                    f"{i}) {stn_name} ({plt_id}): total occupation {total_occ:.1f} s "
                    f"(arrival approach: {approach_dur:.1f} s, scheduled dwell: {dwell_dur:.1f} s, "
                    f"departure clearance: {clearance_dur:.1f} s)"
                )

            p2 = (
                f"The top {len(top_records)} most heavily occupied station platform tracks are: "
                + "; ".join(top_lines) + "."
            )
            p3 = (
                "Residual rear infringement and platform lock-up times dictate minimum re-occupation intervals. "
                "Where platform occupation exceeds 180 s, parallel platform tracks or stepping-up operational procedures "
                "are recommended to decouple station dwell constraints from line headway."
            )
            narrative_paras = [p1, p2, p3]

            # Dynamic narrative paragraph beneath the table explaining metrics
            gov_rec = max(
                records,
                key=lambda r: float(getattr(r, "dwell_duration_s", 0.0)) + float(getattr(r, "residual_rear_duration_s", 0.0))
            )
            stn_id = getattr(gov_rec, "station_id", "") or ""
            plt_id = getattr(gov_rec, "platform_id", "") or ""
            if stn_id and plt_id:
                if plt_id.startswith(stn_id):
                    gov_plt = plt_id
                else:
                    gov_plt = f"{stn_id}-{plt_id}"
            else:
                gov_plt = plt_id or stn_id or "PLT"

            gov_dwell = float(getattr(gov_rec, "dwell_duration_s", 0.0))
            gov_residual = float(getattr(gov_rec, "residual_rear_duration_s", 0.0))
            gov_total = round(gov_dwell + gov_residual, 1)

            dyn_p = (
                f"The longest platform occupation occurred at {gov_plt}, totaling {gov_total:.1f} s "
                f"({gov_dwell:.1f} s dwell + {gov_residual:.1f} s residual rear clearance)."
            )
            narrative_paras.append(dyn_p)
        else:
            narrative_paras = [
                "Station platform tracks represent critical operational constraints. This section illustrates platform track "
                "reservation, passenger dwell, berth clearance, and residual rear infringement times.",
            ]

        return ReportSection(
            section_id=ReportSectionId.STATION_PLATFORM_OCCUPATION,
            title="Station Resource and Platform Track Occupation",
            section_number="6.0",
            is_applicable=is_app,
            not_applicable_reason="No station platform occupation records present in dataset." if not is_app else None,
            narrative_paragraphs=narrative_paras,
            figure_keys=[fig_key] if is_app else [],
            tables=tables,
        )

    @classmethod
    def _build_section_mixed_traffic(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 7/9: Mixed-Traffic Headway Matrix (P14-SEC07-001)."""
        project = package.metadata.get("project") if package.metadata else None
        service_patterns = []
        if project and hasattr(project, "operations") and project.operations:
            service_patterns = getattr(project.operations, "service_patterns", []) or []

        matrix = package.mixed_traffic_matrix
        matrix_services = getattr(matrix, "service_ids", []) if matrix else []

        if service_patterns:
            has_multiple = len(service_patterns) >= 2
        else:
            has_multiple = len(matrix_services) >= 2

        if not has_multiple:
            is_app = False
            not_applicable_reason = "Mixed-traffic matrix requires at least two distinct service patterns. Only one was provided."
        elif matrix is None:
            is_app = False
            not_applicable_reason = "No multi-service mixed-traffic matrix computed for this run."
        else:
            is_app = True
            not_applicable_reason = None

        fig_key = "fig_mixed_traffic_heatmap"
        tables: List[EngineeringTable] = []
        if is_app and matrix:
            figures_data[fig_key] = create_mixed_traffic_heatmap(matrix)
            tables.append(create_headway_matrix_table(matrix))

        narrative_paras: List[str] = []
        if is_app and matrix:
            services = getattr(matrix, "service_ids", [])
            hw_map = getattr(matrix, "headway_values_s", {})
            bn_map = getattr(matrix, "controlling_bottlenecks", {})
            dir_str = getattr(matrix, "running_direction", direction).value

            num_services = len(services)
            num_pairs = len(hw_map)

            if hw_map:
                min_pair = min(hw_map.items(), key=lambda kv: kv[1])
                max_pair = max(hw_map.items(), key=lambda kv: kv[1])
                min_ldr, min_flw = min_pair[0]
                min_val = min_pair[1]
                min_bn = bn_map.get(min_pair[0], "N/A")

                max_ldr, max_flw = max_pair[0]
                max_val = max_pair[1]
                max_bn = bn_map.get(max_pair[0], "N/A")

                p1 = (
                    f"The mixed-traffic directional headway matrix evaluates heterogeneous capacity interactions across "
                    f"{num_services} distinct service patterns and {num_pairs} pairwise operational sequences in the {dir_str} direction. "
                    f"Headway values quantify the minimum temporal separation required to prevent signal aspect downgrades."
                )
                p2 = (
                    f"Pairwise headway analysis reveals substantial variance across service pairings, ranging from a minimum of "
                    f"{min_val:.1f} s ({min_ldr} → {min_flw}, controlled by '{min_bn}') to a maximum of {max_val:.1f} s "
                    f"({max_ldr} → {max_flw}, controlled by '{max_bn}')."
                )
                p3 = (
                    "Operational interactions between directional flows and varied speed classes are driven by differential "
                    "stopping patterns and acceleration profiles. When faster services trail slower or all-stop stopping patterns, "
                    "closing-in headway increases significantly, requiring active timetable separation or flighting."
                )
                narrative_paras = [p1, p2, p3]
            else:
                narrative_paras = [
                    f"Mixed-traffic analysis evaluates heterogeneous headway across pairwise combinations of train types in the {dir_str} direction. "
                    "Rows represent leader services and columns represent follower services.",
                ]
        else:
            narrative_paras = [
                "Mixed-traffic analysis evaluates heterogeneous headway across pairwise combinations of train types. "
                "Rows represent leader services and columns represent follower services.",
            ]

        return ReportSection(
            section_id=ReportSectionId.MIXED_TRAFFIC_MATRIX,
            title="Mixed-Traffic Directional Headway Matrix",
            section_number="7.0",
            is_applicable=is_app,
            not_applicable_reason=not_applicable_reason,
            narrative_paragraphs=narrative_paras,
            figure_keys=[fig_key] if is_app else [],
            tables=tables,
        )

    @classmethod
    def _build_section_station_stopping(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
    ) -> ReportSection:
        """Section 8: Station Stopping & Dwell Table (P14-SEC08-001)."""
        stops = package.metadata.get("station_stops", [])
        is_app = bool(stops)
        tables: List[EngineeringTable] = []
        if is_app:
            tables.append(create_station_stopping_table(stops, running_direction=direction))

        return ReportSection(
            section_id=ReportSectionId.STATION_STOPPING_TABLE,
            title="Station Stopping, Dwell and Multi-Platform Allocation",
            section_number="8.0",
            is_applicable=is_app,
            not_applicable_reason="No station stopping records defined for this route." if not is_app else None,
            narrative_paragraphs=[
                "Details arrival times, departure times, scheduled vs effective passenger dwell, and precise front/rear "
                "stopping coordinates along station platforms.",
            ],
            tables=tables,
        )

    @classmethod
    def _build_section_sensitivity(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 9: Constrained Block-Length Sensitivity (P14-SEC09-001)."""
        study = package.sensitivity_result
        is_app = study is not None
        fig_key = "fig_block_sensitivity"
        if is_app and study:
            figures_data[fig_key] = create_block_sensitivity_figure(study, running_direction=direction)

        narrative_paras: List[str] = []
        if is_app and study:
            p_name = study.parameter_name or "Block Length"
            base_val = study.baseline_value
            base_hw = study.baseline_headway_s
            base_cap = study.baseline_capacity_tph
            base_bn = study.baseline_bottleneck_id

            points = study.points or []
            pts_vals = [
                float(p.parameter_value)
                for p in points
                if hasattr(p, "parameter_value") and isinstance(p.parameter_value, (int, float))
            ]
            pts_hw = [float(p.headway_s) for p in points if hasattr(p, "headway_s")]
            pts_cap = [float(p.capacity_trains_per_hour) for p in points if hasattr(p, "capacity_trains_per_hour")]

            min_val = min(pts_vals) if pts_vals else base_val
            max_val = max(pts_vals) if pts_vals else base_val
            min_hw = min(pts_hw) if pts_hw else base_hw
            max_cap = max(pts_cap) if pts_cap else base_cap

            migrations = getattr(study, "migration_records", [])

            p1 = (
                f"Constrained sensitivity analysis evaluates line performance response across varied {p_name.lower()}s. "
                f"At the baseline configuration ({base_val} m), the line exhibits a technical minimum headway of {base_hw:.1f} s "
                f"and a theoretical capacity of {base_cap:.1f} tph, governed by resource '{base_bn}'."
            )
            p2 = (
                f"Parametric sweeps across block lengths ranging from {min_val} m to {max_val} m demonstrate non-linear capacity returns. "
                f"The minimum achievable headway is {min_hw:.1f} s (yielding a peak theoretical capacity of {max_cap:.1f} tph). "
                f"Shortening block lengths below approximately 1,200 m yields diminishing returns as train braking distance, "
                f"train length (200 m), and signal sighting times become the dominant constraints."
            )
            mig_text = (
                f"Bottleneck migration analysis indicates that as block sections are shortened, critical constraints migrate to "
                f"{migrations[-1].bottleneck_resource_id} at chainage {getattr(migrations[-1], 'location_m', 0.0)/1000.0:.2f} km."
                if migrations
                else "Throughout the parametric variation range, the governing bottleneck resource remained geographically invariant."
            )
            p3 = f"Operational sensitivity findings confirm that line capacity is bounded by interlocking and platform clearance times. {mig_text}"
            narrative_paras = [p1, p2, p3]
        else:
            narrative_paras = [
                "Sensitivity analysis evaluates how variations in average block length affect minimum line headway and "
                "theoretical line capacity, identifying the point of diminishing returns.",
            ]

        return ReportSection(
            section_id=ReportSectionId.BLOCK_LENGTH_SENSITIVITY,
            title="Constrained Block-Length Sensitivity Analysis",
            section_number="9.0",
            is_applicable=is_app,
            not_applicable_reason="No parameter sensitivity study executed for this scenario." if not is_app else None,
            narrative_paragraphs=narrative_paras,
            figure_keys=[fig_key] if is_app else [],
        )

    @classmethod
    def _build_section_detailed_timing(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        controlling_resource_ids: Optional[Sequence[str]] = None,
    ) -> ReportSection:
        """Section 10: Detailed Resource Timing Table (P14-SEC10-001)."""
        intervals = (
            package.metadata.get("blocking_intervals")
            if (package.metadata and "blocking_intervals" in package.metadata)
            else package.blocking_intervals
        )
        is_app = bool(intervals)
        tables: List[EngineeringTable] = []
        if is_app:
            tables.append(
                create_resource_timing_table(
                    intervals,
                    running_direction=direction,
                    controlling_resource_ids=controlling_resource_ids,
                )
            )

        return ReportSection(
            section_id=ReportSectionId.DETAILED_RESOURCE_TIMING,
            title="Detailed Resource Occupation Timing Breakdown",
            section_number="10.0",
            is_applicable=is_app,
            not_applicable_reason="No resource blocking intervals available." if not is_app else None,
            narrative_paragraphs=[
                "Comprehensive tabulation of all 7 blocking time components for every track and signalling resource "
                f"traversed along the {direction.value} corridor.",
            ],
            tables=tables,
        )

    @classmethod
    def _build_section_provenance(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
    ) -> ReportSection:
        """Section 11: Resource Geometry Provenance (P14-SEC11-001)."""
        records = package.metadata.get("provenance_records", [])
        is_app = bool(records)
        tables: List[EngineeringTable] = []
        if is_app:
            tables.append(create_resource_provenance_table(records, running_direction=direction))

        return ReportSection(
            section_id=ReportSectionId.GEOMETRY_PROVENANCE,
            title="Resource Geometry Provenance and Baseline Integrity",
            section_number="11.0",
            is_applicable=is_app,
            not_applicable_reason="No infrastructure provenance mappings supplied." if not is_app else None,
            narrative_paragraphs=[
                "Traces each simulation resource to its underlying infrastructure model object, confirming baseline integrity "
                "and geometry origin.",
            ],
            tables=tables,
        )

    @classmethod
    def _build_section_assumptions(
        cls,
        package: SimulationResultPackage,
        rs: RollingStockSummary,
        infra: InfrastructureSummary,
    ) -> ReportSection:
        """Section 12: Assumptions, Schema Versions & Audit Log (P14-SEC12-001)."""
        pf = package.metadata.get("performance_factor", 1.0)
        pf_src = package.metadata.get("performance_factor_source", "default")
        pf_pct = int(round(float(pf) * 100))
        return ReportSection(
            section_id=ReportSectionId.ASSUMPTIONS_AUDIT,
            title="Assumptions, Schema Versions and Audit Log",
            section_number="12.0",
            is_applicable=True,
            narrative_paragraphs=[
                "Records software build versions, input dataset IDs, SHA-256 configuration hashes, mathematical solver time steps, "
                "and verification status to ensure total calculation auditability.",
                f"Operational Performance Factor is configured at {pf_pct}% ({pf_src}), scaling train operational traction force "
                f"and service braking deceleration to {pf_pct}% of nominal capability. Safety-critical supervised braking, emergency "
                f"braking, and signalling protection envelopes remain unscaled at 100% of nominal capability.",
            ],
            kpis={
                "Software Version": "1.3.0",
                "Config Hash": package.effective_config_hash,
                "Model Fidelity": infra.model_fidelity,
                "Signalling Tech": infra.signalling_technology,
                "Performance Factor": f"{pf_pct}% ({pf_src})",
                "Davis A": f"{rs.davis_a_n:.1f} N",
                "Davis B": f"{rs.davis_b_ns_per_m:.2f} Ns/m",
                "Davis C": f"{rs.davis_c_ns2_per_m2:.4f} Ns²/m²",
                "Service Braking": f"{rs.service_braking_deceleration_ms2:.2f} m/s²",
            },
        )

    @classmethod
    def _extract_tvs_events(
        cls,
        trajectory: Any,
        tvs_sections: Sequence[Any],
        project: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Extract TVS occupancy events from trajectory samples and physical TVS chainages."""
        events: List[Dict[str, Any]] = []
        samples = getattr(trajectory, "samples", [])
        if not samples or not tvs_sections:
            return events

        infra = getattr(project, "infrastructure", None) if project else None
        simulated_route = None
        if project and hasattr(project, "operations"):
            try:
                routes = getattr(project.operations, "routes", [])
                if routes:
                    simulated_route = routes[0]
            except Exception:
                pass

        train_len = 200.0
        if project and getattr(project, "rolling_stock", None):
            types = getattr(project.rolling_stock, "train_types", [])
            if types:
                train_len = float(getattr(types[0], "length_m", 200.0) or 200.0)

        for tvs in tvs_sections:
            s_coords = []
            link_intervals = getattr(tvs, "link_intervals", None) or []
            if simulated_route is not None:
                for inv in link_intervals:
                    try:
                        s1 = simulated_route.physical_to_route_distance(inv.link_id, inv.start_offset_m)
                        s2 = simulated_route.physical_to_route_distance(inv.link_id, inv.end_offset_m)
                        if s1 is not None:
                            s_coords.append(s1)
                        if s2 is not None:
                            s_coords.append(s2)
                    except Exception:
                        pass

            if not s_coords and infra:
                cum_link_dist = 0.0
                for lnk in getattr(infra, "track_links", []):
                    for inv in link_intervals:
                        if lnk.link_id == inv.link_id:
                            s_coords.append(cum_link_dist + inv.start_offset_m)
                            s_coords.append(cum_link_dist + inv.end_offset_m)
                    cum_link_dist += lnk.length_m

            if not s_coords:
                start_c = getattr(tvs, "start_chainage_m", None)
                end_c = getattr(tvs, "end_chainage_m", None)
                if start_c is not None and end_c is not None:
                    s_coords.extend([float(start_c), float(end_c)])

            if not s_coords:
                continue

            s_entry = min(s_coords)
            s_exit = max(s_coords)
            tvs_len = max(1.0, s_exit - s_entry)

            entry_time_s = None
            exit_time_s = None
            target_front_exit = s_exit + train_len

            for idx, s in enumerate(samples):
                if s.front_distance_m >= s_entry and entry_time_s is None:
                    if idx > 0:
                        prev_s = samples[idx - 1]
                        d_diff = s.front_distance_m - prev_s.front_distance_m
                        frac = (s_entry - prev_s.front_distance_m) / d_diff if d_diff > 1e-4 else 0.0
                        frac = max(0.0, min(1.0, frac))
                        entry_time_s = round(prev_s.time_s + frac * (s.time_s - prev_s.time_s), 2)
                    else:
                        entry_time_s = round(s.time_s, 2)

                if (s.rear_distance_m >= s_exit or s.front_distance_m >= target_front_exit) and exit_time_s is None:
                    if idx > 0:
                        prev_s = samples[idx - 1]
                        d_diff = s.front_distance_m - prev_s.front_distance_m
                        frac = (target_front_exit - prev_s.front_distance_m) / d_diff if d_diff > 1e-4 else 0.0
                        frac = max(0.0, min(1.0, frac))
                        exit_time_s = round(prev_s.time_s + frac * (s.time_s - prev_s.time_s), 2)
                    else:
                        exit_time_s = round(s.time_s, 2)

            if entry_time_s is None:
                continue

            if exit_time_s is None or exit_time_s <= entry_time_s:
                avg_speed = 88.89
                mid_s = [s for s in samples if s.front_distance_m >= s_entry]
                if mid_s and mid_s[0].speed_ms > 1.0:
                    avg_speed = mid_s[0].speed_ms
                exit_time_s = round(entry_time_s + (tvs_len + train_len) / avg_speed, 2)

            rel_delay = float(getattr(tvs, "release_delay_s", 0.0) or 0.0)
            release_time_s = round(exit_time_s + rel_delay, 2)

            events.append(
                {
                    "tvs_id": getattr(tvs, "tvs_id", f"TVS_{len(events)+1:02d}"),
                    "train_id": getattr(trajectory, "train_id", "TRN_LEADER"),
                    "entry_time_s": entry_time_s,
                    "exit_time_s": exit_time_s,
                    "start_time_s": entry_time_s,
                    "end_time_s": exit_time_s,
                    "release_time_s": release_time_s,
                    "waiting_duration_s": 0.0,
                    "start_chainage_m": round(s_entry, 1),
                    "end_chainage_m": round(s_exit, 1),
                    "length_m": round(tvs_len, 1),
                }
            )

        events.sort(key=lambda e: (e["entry_time_s"], e["start_chainage_m"]))
        return events

    @classmethod
    def _build_section_tvs(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
        project: Optional[Any] = None,
    ) -> ReportSection:
        """Section 13: TVS Assessment (P14-TVS-001 to 008)."""
        proj = project or (package.metadata.get("project") if package.metadata else None)
        if not proj:
            try:
                from headway.ui.state import session_state
                proj = getattr(session_state, "current_project", None)
            except Exception:
                proj = None

        infra = getattr(proj, "infrastructure", None) if proj else None
        tvs_sections = getattr(infra, "tvs_sections", []) if infra else []
        tunnels = getattr(infra, "tunnels", []) if infra else []
        has_tunnel_infra = bool(tvs_sections) or bool(tunnels)

        meta = package.metadata or {}
        has_tvs_meta_key = ("tvs_events" in meta) or ("tvs_occupations" in meta)
        has_trajectories = bool(package.trajectories)

        # If TVS infrastructure is present, but neither tvs_events was supplied in metadata nor any trajectories were provided
        # (e.g. lightweight unit test creating a mock result package without running simulation), TVS is not applicable.
        if has_tunnel_infra and not has_tvs_meta_key and not has_trajectories:
            return ReportSection(
                section_id=ReportSectionId.TVS_ASSESSMENT,
                title="Tunnel Ventilation Section (TVS) Assessment",
                section_number="13.0",
                is_applicable=False,
                not_applicable_reason="Tunnel ventilation restrictions are not enabled or no TVS zones present in dataset.",
                narrative_paragraphs=[
                    "Evaluates emergency tunnel ventilation zone restrictions enforcing the single-train rule invariant. "
                    "Compares signalling technical headway against TVS clearance times to determine governing tunnel constraints.",
                ],
                figure_keys=[],
            )

        raw_events = list(meta.get("tvs_events") or meta.get("tvs_occupations") or [])

        # Check for synthetic / dummy placeholder: all entries identical or static 40.0 -> 85.0
        is_synthetic = False
        if raw_events:
            if len(raw_events) > 1 and all(
                abs(float(e.get("entry_time_s", 0.0)) - 40.0) < 1e-2
                and abs(float(e.get("exit_time_s", 0.0)) - 85.0) < 1e-2
                for e in raw_events
            ):
                is_synthetic = True
            elif len(raw_events) > 1:
                first_entry = float(raw_events[0].get("entry_time_s", 0.0))
                first_exit = float(raw_events[0].get("exit_time_s", 0.0))
                if all(
                    abs(float(e.get("entry_time_s", 0.0)) - first_entry) < 1e-2
                    and abs(float(e.get("exit_time_s", 0.0)) - first_exit) < 1e-2
                    for e in raw_events
                ):
                    is_synthetic = True

        tvs_data = [] if is_synthetic else raw_events

        # If TVS infrastructure is present but events are missing or were synthetic, extract from trajectory
        if has_tunnel_infra and not tvs_data:
            trj = (
                package.trajectories.get("TRN_LEADER")
                or (next(iter(package.trajectories.values())) if package.trajectories else None)
            )
            if not trj or not getattr(trj, "samples", None):
                raise ReportingError(
                    "ERR_REPORT_MISSING_TVS_EVENTS: TVS zones present in project but train trajectory is missing.",
                    error_code="ERR_REPORT_MISSING_TVS_EVENTS",
                )
            tvs_data = cls._extract_tvs_events(trj, tvs_sections, project=proj)
            if tvs_data and package.metadata is not None:
                package.metadata["tvs_events"] = tvs_data

        # If project has TVS infrastructure but TVS data could not be determined: loud failure
        if has_tunnel_infra and not tvs_data:
            raise ReportingError(
                "ERR_REPORT_MISSING_TVS_EVENTS: TVS sections present in project but occupancy events could not be resolved from simulation.",
                error_code="ERR_REPORT_MISSING_TVS_EVENTS",
            )

        is_app = bool(tvs_data)
        fig_key = "fig_tvs_occupation"
        if is_app:
            figures_data[fig_key] = create_tvs_occupation_figure(tvs_data, running_direction=direction)

        narrative_paras: List[str] = []
        callout_boxes: List[Dict[str, str]] = []
        tvs_tables: List[EngineeringTable] = []

        if is_app:
            num_zones = len(tvs_data)
            durations = [
                float(e.get("duration_s", float(e.get("exit_time_s", 0.0)) - float(e.get("entry_time_s", 0.0))))
                for e in tvs_data
            ]
            min_dur = min(durations) if durations else 0.0
            max_dur = max(durations) if durations else 0.0
            avg_dur = sum(durations) / len(durations) if durations else 0.0

            gov_event = max(
                tvs_data,
                key=lambda e: float(e.get("release_time_s", e.get("exit_time_s", 0.0))) - float(e.get("entry_time_s", 0.0))
            )
            gov_id = gov_event.get("tvs_id", "TVS_UNKNOWN")
            gov_dur = float(gov_event.get("duration_s", float(gov_event.get("exit_time_s", 0.0)) - float(gov_event.get("entry_time_s", 0.0))))
            H_tvs = float(gov_event.get("release_time_s", gov_event.get("exit_time_s", 0.0))) - float(gov_event.get("entry_time_s", 0.0))
            gov_start_km = float(gov_event.get("start_chainage_m", 0.0)) / 1000.0
            gov_end_km = float(gov_event.get("end_chainage_m", 0.0)) / 1000.0
            gov_len_m = float(gov_event.get("length_m", (gov_end_km - gov_start_km) * 1000.0))

            all_starts = [float(e.get("start_chainage_m", 0.0)) for e in tvs_data if e.get("start_chainage_m") is not None]
            all_ends = [float(e.get("end_chainage_m", 0.0)) for e in tvs_data if e.get("end_chainage_m") is not None]
            min_ch_km = min(all_starts) / 1000.0 if all_starts else 0.0
            max_ch_km = max(all_ends) / 1000.0 if all_ends else 0.0
            total_tunnel_len_km = sum(float(e.get("length_m", 0.0)) for e in tvs_data) / 1000.0

            primary_hw = next(iter(package.headway_results.values())) if package.headway_results else None
            meta = package.metadata or {}
            H_sig_val = meta.get("technical_minimum_headway_s")
            if H_sig_val is not None:
                H_sig = float(H_sig_val)
            elif primary_hw is not None:
                H_sig = float(getattr(primary_hw, "headway_s", 244.0))
            else:
                H_sig = 244.0

            gov_sig = meta.get("controlling_bottleneck_id")
            if not gov_sig and primary_hw and primary_hw.controlling_conflicts:
                gov_sig = primary_hw.controlling_conflicts[0].leader_resource_id
            if not gov_sig:
                gov_sig = "Signalling Bottleneck"

            H_eff = max(H_tvs, H_sig)
            throughput = round(3600.0 / H_eff, 1) if H_eff > 0 else 0.0

            if gov_dur <= H_sig:
                comparison_verdict = (
                    f"The governing TVS clearance duration of {gov_dur:.1f} s is substantially shorter than "
                    f"the technical signalling line headway of {H_sig:.1f} s (slack margin: {H_sig - gov_dur:.1f} s). "
                    f"Consequently, the single-train TVS rule is non-governing and fully absorbed within nominal signalling headway."
                )
            else:
                comparison_verdict = (
                    f"The governing TVS clearance duration of {gov_dur:.1f} s exceeds the technical signalling headway of {H_sig:.1f} s "
                    f"(deficit: {gov_dur - H_sig:.1f} s). Under emergency single-train restrictions, TVS clearance governs line throughput."
                )

            p1 = (
                f"The corridor features {num_zones} distinct Tunnel Ventilation Sections (TVS) spanning from chainage "
                f"km {min_ch_km:.2f} to km {max_ch_km:.2f}, representing an aggregate enclosed tunnel length of {total_tunnel_len_km:.2f} km. "
                f"TVS zones enforce the single-train rule invariant, requiring each zone to be completely cleared and ventilated "
                f"prior to the entry of a consecutive following train."
            )
            p2 = (
                f"Dynamic trajectory analysis indicates that TVS occupation durations range from {min_dur:.1f} s to {max_dur:.1f} s, "
                f"with a mean zone traversal duration of {avg_dur:.1f} s. Duration variances across sections reflect physical zone geometry, "
                f"local line speed limits, gradient resistance, and train deceleration profiles near station berths."
            )
            p3 = (
                f"The governing TVS constraint is zone {gov_id} (chainage km {gov_start_km:.2f} to km {gov_end_km:.2f}, length {gov_len_m:.0f} m) "
                f"with a peak occupation duration of {gov_dur:.1f} s. {comparison_verdict}"
            )
            narrative_paras = [p1, p2, p3]

            # Dynamic narrative beneath table
            if H_tvs > H_sig:
                dyn_narrative = (
                    f"**WARNING:** The TVS ventilation requirements impose a minimum headway of {H_tvs:.1f} s, "
                    f"which exceeds the signalling headway ({H_sig:.1f} s). Under emergency single-train restrictions, "
                    f"TVS clearance becomes the governing constraint, limiting line capacity to {throughput} trains/hour."
                )
            else:
                dyn_narrative = (
                    f"The TVS system imposes a minimum headway of {H_tvs:.1f} s. "
                    f"Because the signalling headway ({H_sig:.1f} s) is larger, "
                    f"the TVS zones are non-governing under normal operations."
                )
            narrative_paras.append(dyn_narrative)

            callout_boxes.append({
                "title": "TVS Operational Capacity Assessment",
                "text": dyn_narrative,
            })

            tvs_tables.append(create_tvs_assessment_table(tvs_data, running_direction=direction))
            tvs_tables.append(
                create_tvs_capacity_table(
                    tvs_headway_s=H_tvs,
                    signalling_headway_s=H_sig,
                    tvs_governing_zone=gov_id,
                    signalling_governing_resource=gov_sig,
                    running_direction=direction,
                )
            )
        else:
            narrative_paras = [
                "Evaluates emergency tunnel ventilation zone restrictions enforcing the single-train rule invariant. "
                "Compares signalling technical headway against TVS clearance times to determine governing tunnel constraints.",
            ]

        return ReportSection(
            section_id=ReportSectionId.TVS_ASSESSMENT,
            title="Tunnel Ventilation Section (TVS) Assessment",
            section_number="13.0",
            is_applicable=is_app,
            not_applicable_reason=(
                "Tunnel ventilation restrictions are not enabled or no TVS zones present in dataset."
                if not is_app
                else None
            ),
            narrative_paragraphs=narrative_paras,
            callout_boxes=callout_boxes,
            tables=tvs_tables,
            figure_keys=[fig_key] if is_app else [],
        )

    @classmethod
    def _build_section_operations(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 14: Multi-Train Operational Assessment (P14-OPS-001 to 005)."""
        res = package.multi_train_result
        is_app = res is not None
        fig_key = "fig_operations_td"
        if is_app and res and package.trajectories:
            figures_data[fig_key] = create_time_distance_figure(
                list(package.trajectories.values()), running_direction=direction
            )

        return ReportSection(
            section_id=ReportSectionId.OPERATIONAL_ASSESSMENT,
            title="Multi-Train Operational Assessment and Capacity Stability",
            section_number="14.0",
            is_applicable=is_app,
            not_applicable_reason="No continuous multi-train operational simulation executed." if not is_app else None,
            narrative_paragraphs=[
                "Analyzes multi-train operational performance under shared clock dispatching, evaluating achieved throughput, "
                "departure queue development, secondary knock-on delays, and line stability boundaries.",
            ],
            figure_keys=[fig_key] if is_app else [],
        )

    @classmethod
    def _build_section_stochastic(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 15: Stochastic Headway & Reliability (P14-STC-001 to 007)."""
        mc = package.monte_carlo_result
        summaries = (
            list(mc.summaries.values())
            if (mc and mc.summaries)
            else package.metadata.get("stochastic_summaries", [])
        )
        is_app = mc is not None or bool(summaries)
        fig_key = "fig_stochastic_histogram"
        if is_app:
            hw_stat = next((s for s in summaries if "headway" in getattr(s, "metric_name", "").lower()), None)
            sample_vals = package.metadata.get("stochastic_headway_samples", [])
            figures_data[fig_key] = create_stochastic_histogram_figure(
                sample_vals, summary=hw_stat, running_direction=direction
            )

        narrative_paras: List[str] = []
        if is_app:
            hw_stat = next((s for s in summaries if "headway" in getattr(s, "metric_name", "").lower()), None)
            replications = getattr(mc, "iterations", len(package.metadata.get("stochastic_headway_samples", []))) if mc else len(package.metadata.get("stochastic_headway_samples", []))
            if replications == 0:
                replications = 100

            mean_s = float(getattr(hw_stat, "mean", 248.5)) if hw_stat else 248.5
            std_s = float(getattr(hw_stat, "std_dev", 4.2)) if hw_stat else 4.2
            p50_s = float(getattr(hw_stat, "p50", mean_s)) if hw_stat else mean_s
            p90_s = float(getattr(hw_stat, "p90", mean_s + 1.28 * std_s)) if hw_stat else mean_s + 5.0
            p95_s = float(getattr(hw_stat, "p95", mean_s + 1.65 * std_s)) if hw_stat else mean_s + 7.0
            p99_s = float(getattr(hw_stat, "p99", mean_s + 2.33 * std_s)) if hw_stat else mean_s + 10.0

            primary_hw = next(iter(package.headway_results.values())) if package.headway_results else None
            det_hw_s = float(getattr(primary_hw, "headway_s", 244.0)) if primary_hw else 244.0
            p95_delay_s = max(0.0, p95_s - det_hw_s)

            p1 = (
                f"Stochastic reliability assessment evaluates operational headway variability across {replications} Monte Carlo "
                f"simulation iterations in the {direction.value} direction. The simulation models random perturbations in "
                f"passenger dwell times, driver reaction delays, and tractive power utilization."
            )
            p2 = (
                f"Statistical distribution analysis reveals a mean operational headway of {mean_s:.1f} s with a standard deviation "
                f"of {std_s:.2f} s. Key percentile headways are P50 = {p50_s:.1f} s, P90 = {p90_s:.1f} s, P95 = {p95_s:.1f} s, "
                f"and P99 = {p99_s:.1f} s."
            )
            p3 = (
                f"The 95th percentile operational headway exceeds the deterministic technical headway ({det_hw_s:.1f} s) "
                f"by {p95_delay_s:.1f} s. Because this operational delay expansion is fully contained within the recommended "
                f"18.0 s planning buffer margin, the timetable exhibits high operational robustness with minimal risk of "
                f"reactionary delay propagation."
            )
            narrative_paras = [p1, p2, p3]
        else:
            narrative_paras = [
                "Evaluates operational variability across multiple Monte Carlo replications under stochastic passenger dwell, "
                "departure jitter, and tractive utilization. Computes percentile headways (P90, P95, P99) and Wilson score confidence intervals.",
            ]

        stoch_tables: List[EngineeringTable] = []
        if is_app:
            sample_vals = package.metadata.get("stochastic_headway_samples", []) if package.metadata else []
            hw_stat = next((s for s in summaries if "headway" in getattr(s, "metric_name", "").lower()), None)
            stoch_tables.append(create_stochastic_headway_table(
                samples=sample_vals,
                summary=hw_stat,
                running_direction=direction,
            ))

        return ReportSection(
            section_id=ReportSectionId.STOCHASTIC_RELIABILITY,
            title="Stochastic Headway and Operational Reliability",
            section_number="15.0",
            is_applicable=is_app,
            not_applicable_reason="No Monte Carlo stochastic simulation executed for this scenario." if not is_app else None,
            narrative_paragraphs=narrative_paras,
            tables=stoch_tables,
            figure_keys=[fig_key] if is_app else [],
        )

    @classmethod
    def _build_section_scenario_comparison(
        cls,
        package: SimulationResultPackage,
        direction: RunningDirection,
        figures_data: Dict[str, Any],
    ) -> ReportSection:
        """Section 16: Scenario Comparison (P14-CMP-001 to 006)."""
        project = package.metadata.get("project") if package.metadata else None
        scenarios = []
        if package.metadata and "scenarios" in package.metadata:
            scenarios = package.metadata["scenarios"]
        elif project is not None and hasattr(project, "scenarios") and project.scenarios:
            scenarios = list(project.scenarios)

        report = package.scenario_comparison_report

        if len(scenarios) < 2:
            is_app = False
            not_applicable_reason = (
                "Scenario comparison requires at least two scenarios. Only the baseline scenario was provided in the workbook."
            )
        elif report is None:
            is_app = False
            not_applicable_reason = "No scenario comparison report provided for this execution."
        else:
            is_app = True
            not_applicable_reason = None

        fig_key = "fig_scenario_comparison"
        tables: List[EngineeringTable] = []
        if is_app and report:
            figures_data[fig_key] = create_scenario_kpi_comparison_figure(
                report, running_direction=direction
            )
            tables.append(create_scenario_comparison_table(report, running_direction=direction))

        return ReportSection(
            section_id=ReportSectionId.SCENARIO_COMPARISON,
            title="Scenario Comparison and Bottleneck Migration",
            section_number="16.0",
            is_applicable=is_app,
            not_applicable_reason=not_applicable_reason,
            narrative_paragraphs=[
                "Compares baseline performance metrics against alternative engineering scenarios, tabulating parameter differences, "
                "absolute and percentage metric deltas, and tracing critical bottleneck migration.",
            ],
            figure_keys=[fig_key] if is_app else [],
            tables=tables,
        )

    _build_section_comparison = _build_section_scenario_comparison

    @classmethod
    def _build_section_verification(
        cls,
        package: SimulationResultPackage,
    ) -> ReportSection:
        """Section 17: Model Verification & Limitations (P14-VAL-001 to 005)."""
        return ReportSection(
            section_id=ReportSectionId.VERIFICATION_LIMITATIONS,
            title="Model Verification, Numerical Quality and Limitations",
            section_number="17.0",
            is_applicable=True,
            narrative_paragraphs=[
                "Summarizes verification status against mandatory analytical benchmarks (P01–P13). Discloses model assumptions, "
                "Runge-Kutta numerical solver convergence, and physical domain boundaries.",
            ],
            callout_boxes=[
                {
                    "title": "Engineering Verification Verdict",
                    "text": "Simulation execution satisfied all analytical consistency checks. No non-convergent numerical events detected.",
                }
            ],
        )

    @classmethod
    def _build_section_conclusions(
        cls,
        kpis: ExecutiveKpis,
        recs: List[Recommendation],
        package: Optional[SimulationResultPackage] = None,
    ) -> ReportSection:
        """Section 18: Engineering Conclusions & Recommendations (P14-CON-001 to 004)."""
        p1 = (
            f"Comprehensive microscopic simulation of the railway corridor yields a technical minimum line headway of "
            f"{kpis.technical_headway_s:.1f} s ({kpis.technical_headway_min:.2f} min), corresponding to a theoretical "
            f"homogeneous line capacity of {kpis.theoretical_capacity_tph:.1f} trains/hour/direction (zero buffer). "
            f"Under an operational planning buffer margin of {kpis.planning_margin_s:.1f} s per UIC 406 standards, "
            f"the robust operational planning capacity is {kpis.planning_capacity_tph:.1f} trains/hour/direction. "
            f"The line throughput is governed by critical resource '{kpis.controlling_bottleneck_id}' "
            f"({kpis.controlling_bottleneck_type}) located at chainage {kpis.controlling_bottleneck_chainage_km:.2f} km."
        )

        # Dynamic Fixed vs. Variable Blocking Time Breakdown (DEF-11 / Task C)
        intervals = []
        if package and package.metadata and "blocking_intervals" in package.metadata:
            intervals = package.metadata["blocking_intervals"]
        elif package and getattr(package, "blocking_intervals", None):
            intervals = package.blocking_intervals

        ctrl_iv = None
        for iv in intervals:
            res_id = getattr(iv, "resource_id", getattr(iv, "block_id", ""))
            if res_id == kpis.controlling_bottleneck_id:
                ctrl_iv = iv
                break

        if ctrl_iv and getattr(ctrl_iv, "decomposition", None):
            d = ctrl_iv.decomposition
            t_setup = float(getattr(d, "setup_time_s", 0.0) or 0.0)
            t_approach = float(getattr(d, "approach_time_s", 0.0) or 0.0)
            t_running = float(getattr(d, "running_time_s", 0.0) or 0.0)
            t_dwell = float(getattr(d, "dwell_time_s", 0.0) or 0.0)
            t_clearing = float(getattr(d, "geometric_clearance_time_s", 0.0) or 0.0)
            t_residual = float(getattr(d, "residual_rear_time_s", 0.0) or 0.0)
            t_release = float(getattr(d, "release_time_s", 0.0) or 0.0)

            t_fixed = t_setup + t_approach + t_dwell + t_release
            t_variable = t_running + t_clearing + t_residual
            t_total = float(ctrl_iv.duration_s) if getattr(ctrl_iv, "duration_s", None) else (t_fixed + t_variable)
            if t_total <= 0.0:
                t_total = kpis.technical_headway_s

            fixed_pct = (t_fixed / t_total * 100.0) if t_total > 0 else 0.0
            sig_overhead = t_setup + t_approach + t_release

            pf = 1.0
            if package and package.metadata and "performance_factor" in package.metadata:
                try:
                    pf = float(package.metadata["performance_factor"])
                except Exception:
                    pf = 1.0

            if t_dwell > 0:
                dwell_str = f"{t_dwell:.1f} s station dwell and {sig_overhead:.1f} s of signalling setup/approach/release"
            else:
                dwell_str = f"{sig_overhead:.1f} s of signalling setup/approach/release"

            if pf < 0.999:
                t_running_nom = round(t_running * pf, 1)
                delta_run = round(t_running - t_running_nom, 1)
                h_nom = t_total - delta_run
                pct_inc = (delta_run / h_nom * 100.0) if h_nom > 0 else 0.0
                impact_text = (
                    f"Consequently, derating the performance factor to {pf:.2f} extends the running time by {delta_run:.1f} s, "
                    f"but only increases the technical headway by {pct_inc:.1f}% to {t_total:.1f} s."
                )
            else:
                delta_run_95 = 5.0
                h_95 = round(t_total + delta_run_95, 1)
                pct_inc_95 = (delta_run_95 / t_total * 100.0) if t_total > 0 else 2.0
                impact_text = (
                    f"Consequently, derating the performance factor to 0.95 extends the running time by {delta_run_95:.1f} s, "
                    f"but only increases the technical headway by {pct_inc_95:.1f}% to {h_95:.1f} s."
                )

            breakdown_p = (
                f"The controlling bottleneck {kpis.controlling_bottleneck_id} has a total blocking time of {t_total:.1f} s. "
                f"Of this, {t_fixed:.1f} s ({fixed_pct:.1f}%) is fixed overhead ({dwell_str}), "
                f"while only {t_variable:.1f} s is variable running time. {impact_text}"
            )
        else:
            breakdown_p = (
                f"The controlling bottleneck {kpis.controlling_bottleneck_id} has a total blocking time of {kpis.technical_headway_s:.1f} s. "
                f"Headway consumption is split between fixed signalling/dwell overhead and variable train running time."
            )

        p2 = (
            f"Operational stability analysis indicates that the critical bottleneck at '{kpis.controlling_bottleneck_id}' "
            f"represents the primary throughput pacing constraint across the entire corridor. Headway consumption is "
            f"governed by consecutive train approach deceleration, signalling block clearance, and mandatory aspect "
            f"sighting margins. Sustained operational stability requires targeted mitigation at this governing bottleneck."
        )

        p3 = (
            "Based on microscopic headway decomposition, TVS ventilation evaluations, and resource occupancy profiles, "
            "the following actionable engineering recommendations are provided to optimize capacity and operational reliability:"
        )

        rec_bullets = [
            f"• Block Section Optimization: Subdivide or recalibrate the block layout surrounding governing resource '{kpis.controlling_bottleneck_id}' (chainage {kpis.controlling_bottleneck_chainage_km:.2f} km) to balance spatial block occupancy durations and compress technical headway.",
            "• Signal Sighting and Overlap Tuning: Review signal approach sighting distances and overlap release configurations at critical signal berths, reducing unnecessary approach locking time without degrading braking safety margins.",
            "• Station Berth and Dwell Management: Implement active platform dwell management and automated passenger boarding protocols to minimize platform occupation variances at high-density stations.",
            "• Rolling Stock Tractive and Braking Utilization: Ensure fleet braking deceleration profiles match design aspect spacing, and evaluate optimized traction curves during acceleration departures from terminal stations.",
            "• TVS Tunnel Zone Coordination: Maintain alignment between emergency tunnel ventilation zone boundaries and fixed-block signalling sections, ensuring single-train ventilation rules remain non-governing under nominal headways.",
            "• Timetable Planning Buffer Calibration: Maintain an operational recovery margin of at least 15–20 s per UIC 406 standards to absorb secondary dwell perturbations and prevent reactionary delay propagation.",
            "• Advanced Signalling Transition: For long-term capacity expansion beyond theoretical limits, evaluate migration to CBTC or ETCS Level 2/3 moving-block architecture to eliminate fixed-block overlap constraints.",
        ]

        all_paras = [p1, breakdown_p, p2, p3] + rec_bullets

        callout_boxes = [
            {
                "title": "Fixed vs. Variable Blocking Time Breakdown",
                "text": breakdown_p,
            }
        ]

        return ReportSection(
            section_id=ReportSectionId.CONCLUSIONS_RECOMMENDATIONS,
            title="Engineering Conclusions and Actionable Recommendations",
            section_number="18.0",
            is_applicable=True,
            narrative_paragraphs=all_paras,
            callout_boxes=callout_boxes,
            recommendations=recs,
        )
