"""Cross-reference (Level 3), engineering configuration (Level 4), and simulation readiness (Level 5) validation.

Strictly satisfies RHS-P01-001 § 15 and § 16.
Enforces physical and relational integrity without executing microscopic train dynamics.
"""

from typing import Dict, List, Optional
from headway.core.identifiers import IdentifierRegistry, normalize_identifier
from headway.data.importer import RawWorkbookData
from headway.data.validation import Severity, ValidationReport


class DatasetValidator:
    """Multi-level validator verifying relational, geometric, and configuration consistency."""

    def __init__(self, report: Optional[ValidationReport] = None) -> None:
        self.report: ValidationReport = report or ValidationReport()
        self.registry: IdentifierRegistry = IdentifierRegistry()

    def validate_all(self, raw_workbooks: Dict[str, RawWorkbookData]) -> ValidationReport:
        """Execute Level 3, Level 4, and Level 5 validations across loaded workbooks."""
        self.registry.clear()

        # Step 1: Register all primary identifiers and detect duplicates (Level 3)
        self._register_identifiers(raw_workbooks)

        # Step 2: Validate foreign key cross-references (Level 3)
        self._validate_cross_references(raw_workbooks)

        # Step 3: Validate engineering geometry and configuration bounds (Level 4)
        self._validate_engineering_configuration(raw_workbooks)

        # Step 4: Verify simulation readiness (Level 5)
        self._validate_simulation_readiness(raw_workbooks)

        return self.report

    def _register_identifiers(self, raw_workbooks: Dict[str, RawWorkbookData]) -> None:
        """Register all entity IDs across workbooks and detect namespace collisions."""
        # 1. Infrastructure
        infra = raw_workbooks.get("INFRASTRUCTURE")
        if infra:
            for row in infra.get_rows("Nodes"):
                nid = row.get("node_id")
                if nid:
                    self._safe_register("NODE", nid, "INFRASTRUCTURE", "Nodes", row.get("_row"))

            for row in infra.get_rows("Tracks"):
                tid = row.get("track_id")
                if tid:
                    self._safe_register("TRACK", tid, "INFRASTRUCTURE", "Tracks", row.get("_row"))

            for row in infra.get_rows("TrackLinks"):
                lid = row.get("link_id")
                if lid:
                    self._safe_register("LINK", lid, "INFRASTRUCTURE", "TrackLinks", row.get("_row"))

            for row in infra.get_rows("Stations"):
                sid = row.get("station_id")
                if sid:
                    self._safe_register("STATION", sid, "INFRASTRUCTURE", "Stations", row.get("_row"))

            for row in infra.get_rows("Platforms"):
                pid = row.get("platform_id")
                if pid:
                    self._safe_register("PLATFORM", pid, "INFRASTRUCTURE", "Platforms", row.get("_row"))

            for row in infra.get_rows("StoppingPoints"):
                spid = row.get("stopping_point_id")
                if spid:
                    self._safe_register("STOPPING_POINT", spid, "INFRASTRUCTURE", "StoppingPoints", row.get("_row"))

            for row in infra.get_rows("Tunnels"):
                tnl_id = row.get("tunnel_id")
                if tnl_id:
                    self._safe_register("TUNNEL", tnl_id, "INFRASTRUCTURE", "Tunnels", row.get("_row"))

            for row in infra.get_rows("TVSSections"):
                tvs_id = row.get("tvs_id")
                if tvs_id:
                    self._safe_register("TVS", tvs_id, "INFRASTRUCTURE", "TVSSections", row.get("_row"))

        # 2. Signalling
        sig = raw_workbooks.get("SIGNALLING")
        if sig:
            for row in sig.get_rows("Signals"):
                sig_id = row.get("signal_id")
                if sig_id:
                    self._safe_register("SIGNAL", sig_id, "SIGNALLING", "Signals", row.get("_row"))

            for row in sig.get_rows("Blocks"):
                bid = row.get("block_id")
                if bid:
                    self._safe_register("BLOCK", bid, "SIGNALLING", "Blocks", row.get("_row"))

            for row in sig.get_rows("InterlockingRoutes"):
                rid = row.get("route_id")
                if rid:
                    self._safe_register("ROUTE", rid, "SIGNALLING", "InterlockingRoutes", row.get("_row"))

        # 3. Rolling Stock
        rs = raw_workbooks.get("ROLLING_STOCK")
        if rs:
            for row in rs.get_rows("TrainTypes"):
                ttid = row.get("train_type_id")
                if ttid:
                    self._safe_register("TRAIN_TYPE", ttid, "ROLLING_STOCK", "TrainTypes", row.get("_row"))

        # 4. Operations
        ops = raw_workbooks.get("OPERATIONS")
        if ops:
            for row in ops.get_rows("ServicePatterns"):
                spid = row.get("service_pattern_id")
                if spid:
                    self._safe_register("SERVICE_PATTERN", spid, "OPERATIONS", "ServicePatterns", row.get("_row"))

        # 5. Analysis
        an = raw_workbooks.get("HEADWAY_ANALYSIS")
        if an:
            for row in an.get_rows("AnalysisSettings"):
                aid = row.get("analysis_id")
                if aid:
                    self._safe_register("ANALYSIS", aid, "HEADWAY_ANALYSIS", "AnalysisSettings", row.get("_row"))

        # 6. Scenarios
        scn = raw_workbooks.get("SCENARIOS")
        if scn:
            for row in scn.get_rows("ScenarioDefinitions"):
                scid = row.get("scenario_id")
                if scid:
                    self._safe_register("SCENARIO", scid, "SCENARIOS", "ScenarioDefinitions", row.get("_row"))

    def _safe_register(self, namespace: str, raw_id: str, wb: str, ws: str, row: Optional[int]) -> None:
        """Register identifier and log duplicate finding if collision occurs."""
        try:
            self.registry.register(namespace, raw_id, source_info=f"{wb}.{ws}")
        except Exception as err:
            self.report.add_finding(
                error_code="ERR_ID_DUPLICATE",
                severity=Severity.ERROR,
                message=str(err),
                workbook=wb,
                worksheet=ws,
                row=row,
                object_id=str(raw_id),
                recommendation=f"Ensure identifier '{raw_id}' is unique within namespace '{namespace}'.",
            )

    def _validate_cross_references(self, raw_workbooks: Dict[str, RawWorkbookData]) -> None:
        """Validate foreign key relationships across all loaded worksheets."""
        infra = raw_workbooks.get("INFRASTRUCTURE")
        if infra:
            for row in infra.get_rows("TrackLinks"):
                lid = row.get("link_id")
                self._check_ref("TRACK", row.get("track_id"), "TrackLinks.track_id", "INFRASTRUCTURE", "TrackLinks", lid)
                self._check_ref("NODE", row.get("start_node_id"), "TrackLinks.start_node_id", "INFRASTRUCTURE", "TrackLinks", lid)
                self._check_ref("NODE", row.get("end_node_id"), "TrackLinks.end_node_id", "INFRASTRUCTURE", "TrackLinks", lid)

            for row in infra.get_rows("Platforms"):
                pid = row.get("platform_id")
                self._check_ref("STATION", row.get("station_id"), "Platforms.station_id", "INFRASTRUCTURE", "Platforms", pid)
                self._check_ref("LINK", row.get("link_id"), "Platforms.link_id", "INFRASTRUCTURE", "Platforms", pid)

            for row in infra.get_rows("StoppingPoints"):
                spid = row.get("stopping_point_id")
                self._check_ref("PLATFORM", row.get("platform_id"), "StoppingPoints.platform_id", "INFRASTRUCTURE", "StoppingPoints", spid)
                self._check_ref("LINK", row.get("link_id"), "StoppingPoints.link_id", "INFRASTRUCTURE", "StoppingPoints", spid)

            for row in infra.get_rows("TVSSections"):
                tvs_id = row.get("tvs_id")
                self._check_ref("TRACK", row.get("track_id"), "TVSSections.track_id", "INFRASTRUCTURE", "TVSSections", tvs_id)
                self._check_ref("LINK", row.get("link_id"), "TVSSections.link_id", "INFRASTRUCTURE", "TVSSections", tvs_id)
                if row.get("tunnel_id") and self.registry.get_all("TUNNEL"):
                    self._check_ref("TUNNEL", row.get("tunnel_id"), "TVSSections.tunnel_id", "INFRASTRUCTURE", "TVSSections", tvs_id)
                if row.get("holding_signal_id"):
                    self._check_ref("SIGNAL", row.get("holding_signal_id"), "TVSSections.holding_signal_id", "INFRASTRUCTURE", "TVSSections", tvs_id)

        sig = raw_workbooks.get("SIGNALLING")
        if sig:
            for row in sig.get_rows("Signals"):
                sid = row.get("signal_id")
                self._check_ref("LINK", row.get("link_id"), "Signals.link_id", "SIGNALLING", "Signals", sid)

            for row in sig.get_rows("Blocks"):
                bid = row.get("block_id")
                self._check_ref("LINK", row.get("link_id"), "Blocks.link_id", "SIGNALLING", "Blocks", bid)
                if row.get("entry_signal_id"):
                    self._check_ref("SIGNAL", row.get("entry_signal_id"), "Blocks.entry_signal_id", "SIGNALLING", "Blocks", bid)
                if row.get("exit_signal_id"):
                    self._check_ref("SIGNAL", row.get("exit_signal_id"), "Blocks.exit_signal_id", "SIGNALLING", "Blocks", bid)

            for row in sig.get_rows("InterlockingRoutes"):
                rid = row.get("route_id")
                self._check_ref("SIGNAL", row.get("entry_signal_id"), "InterlockingRoutes.entry_signal_id", "SIGNALLING", "InterlockingRoutes", rid)
                self._check_ref("SIGNAL", row.get("exit_signal_id"), "InterlockingRoutes.exit_signal_id", "SIGNALLING", "InterlockingRoutes", rid)
                for l in row.get("link_sequence", []):
                    self._check_ref("LINK", l, f"InterlockingRoutes.link_sequence[{l}]", "SIGNALLING", "InterlockingRoutes", rid)
                for b in row.get("protected_blocks", []):
                    self._check_ref("BLOCK", b, f"InterlockingRoutes.protected_blocks[{b}]", "SIGNALLING", "InterlockingRoutes", rid)

        ops = raw_workbooks.get("OPERATIONS")
        if ops:
            for row in ops.get_rows("ServicePatterns"):
                spid = row.get("service_pattern_id")
                self._check_ref("TRAIN_TYPE", row.get("train_type_id"), "ServicePatterns.train_type_id", "OPERATIONS", "ServicePatterns", spid)
                for l in row.get("route_link_sequence", []):
                    self._check_ref("LINK", l, f"ServicePatterns.route_link_sequence[{l}]", "OPERATIONS", "ServicePatterns", spid)

            for row in ops.get_rows("StoppingPatterns"):
                spid = row.get("service_pattern_id")
                self._check_ref("SERVICE_PATTERN", spid, "StoppingPatterns.service_pattern_id", "OPERATIONS", "StoppingPatterns", spid)
                self._check_ref("STATION", row.get("station_id"), "StoppingPatterns.station_id", "OPERATIONS", "StoppingPatterns", spid)
                self._check_ref("PLATFORM", row.get("platform_id"), "StoppingPatterns.platform_id", "OPERATIONS", "StoppingPatterns", spid)

        an = raw_workbooks.get("HEADWAY_ANALYSIS")
        if an:
            for row in an.get_rows("AnalysisSettings"):
                aid = row.get("analysis_id")
                if row.get("leader_service_id"):
                    self._check_ref("SERVICE_PATTERN", row.get("leader_service_id"), "AnalysisSettings.leader_service_id", "HEADWAY_ANALYSIS", "AnalysisSettings", aid)
                if row.get("follower_service_id"):
                    self._check_ref("SERVICE_PATTERN", row.get("follower_service_id"), "AnalysisSettings.follower_service_id", "HEADWAY_ANALYSIS", "AnalysisSettings", aid)
                if row.get("reference_link_id"):
                    self._check_ref("LINK", row.get("reference_link_id"), "AnalysisSettings.reference_link_id", "HEADWAY_ANALYSIS", "AnalysisSettings", aid)

        scn = raw_workbooks.get("SCENARIOS")
        if scn:
            for row in scn.get_rows("Overrides"):
                sid = row.get("scenario_id")
                self._check_ref("SCENARIO", sid, "Overrides.scenario_id", "SCENARIOS", "Overrides", sid)

    def _check_ref(
        self,
        target_ns: str,
        ref_id: Optional[str],
        field_desc: str,
        wb: str,
        ws: str,
        obj_id: Optional[str],
    ) -> None:
        """Check reference existence in registered namespace."""
        if not ref_id:
            return
        clean_ref = str(ref_id).strip()
        if not self.registry.exists(target_ns, clean_ref):
            self.report.add_finding(
                error_code="ERR_REF_MISSING",
                severity=Severity.ERROR,
                message=f"{field_desc} references non-existent {target_ns} '{clean_ref}'.",
                workbook=wb,
                worksheet=ws,
                object_id=obj_id,
                column=field_desc.split(".")[-1],
                recommendation=f"Ensure {target_ns} '{clean_ref}' is defined in corresponding worksheet.",
            )

    def _validate_engineering_configuration(self, raw_workbooks: Dict[str, RawWorkbookData]) -> None:
        """Validate engineering boundaries, spatial offset limits, and physical parameters (Level 4)."""
        # Map link_id -> length_m
        link_lengths: Dict[str, float] = {}
        infra = raw_workbooks.get("INFRASTRUCTURE")
        if infra:
            for row in infra.get_rows("TrackLinks"):
                lid = row.get("link_id")
                length = row.get("length_m")
                if lid and length is not None:
                    try:
                        f_len = float(length)
                        if f_len <= 0.0:
                            self.report.add_finding(
                                error_code="ERR_ENG_NON_POSITIVE_LENGTH",
                                severity=Severity.ERROR,
                                message=f"Track link '{lid}' has non-positive length: {f_len} m.",
                                workbook="INFRASTRUCTURE",
                                worksheet="TrackLinks",
                                object_id=lid,
                                column="LENGTH_M",
                            )
                        link_lengths[lid] = f_len
                    except ValueError:
                        pass

            # Platforms within link bounds
            for row in infra.get_rows("Platforms"):
                pid = row.get("platform_id")
                lid = row.get("link_id")
                start = row.get("start_offset_m")
                end = row.get("end_offset_m")
                if lid in link_lengths and start is not None and end is not None:
                    max_len = link_lengths[lid]
                    if start < 0.0 or start > max_len or end < 0.0 or end > max_len or start >= end:
                        self.report.add_finding(
                            error_code="ERR_ENG_OFFSET_OUT_OF_BOUNDS",
                            severity=Severity.ERROR,
                            message=f"Platform '{pid}' interval [{start}, {end}] exceeds link '{lid}' length ({max_len} m) or is inverted.",
                            workbook="INFRASTRUCTURE",
                            worksheet="Platforms",
                            object_id=pid,
                        )

            # TVS sections within link bounds & positive occupancy
            for row in infra.get_rows("TVSSections"):
                tvs_id = row.get("tvs_id")
                lid = row.get("link_id")
                start = row.get("start_offset_m")
                end = row.get("end_offset_m")
                occ = row.get("max_train_occupancy", 1)
                if occ is not None and occ < 1:
                    self.report.add_finding(
                        error_code="ERR_ENG_TVS_OCCUPANCY_INVALID",
                        severity=Severity.ERROR,
                        message=f"TVS Section '{tvs_id}' max_train_occupancy must be >= 1 (got {occ}).",
                        workbook="INFRASTRUCTURE",
                        worksheet="TVSSections",
                        object_id=tvs_id,
                    )
                if lid in link_lengths and start is not None and end is not None:
                    max_len = link_lengths[lid]
                    if start < 0.0 or end > max_len or start >= end:
                        self.report.add_finding(
                            error_code="ERR_ENG_TVS_BOUNDS_INVALID",
                            severity=Severity.ERROR,
                            message=f"TVS '{tvs_id}' interval [{start}, {end}] exceeds link '{lid}' length ({max_len} m).",
                            workbook="INFRASTRUCTURE",
                            worksheet="TVSSections",
                            object_id=tvs_id,
                        )

        # Signalling blocks within link bounds
        sig = raw_workbooks.get("SIGNALLING")
        if sig:
            for row in sig.get_rows("Blocks"):
                bid = row.get("block_id")
                lid = row.get("link_id")
                start = row.get("start_offset_m")
                end = row.get("end_offset_m")
                if lid in link_lengths and start is not None and end is not None:
                    max_len = link_lengths[lid]
                    if start < 0.0 or end > max_len or start >= end:
                        self.report.add_finding(
                            error_code="ERR_ENG_BLOCK_BOUNDS_INVALID",
                            severity=Severity.ERROR,
                            message=f"Signalling block '{bid}' interval [{start}, {end}] exceeds link '{lid}' length ({max_len} m).",
                            workbook="SIGNALLING",
                            worksheet="Blocks",
                            object_id=bid,
                        )

        # Rolling stock mass and deceleration consistency
        rs = raw_workbooks.get("ROLLING_STOCK")
        if rs:
            for row in rs.get_rows("TrainTypes"):
                ttid = row.get("train_type_id")
                m_empty = row.get("mass_empty_kg")
                m_loaded = row.get("mass_loaded_kg")
                d_serv = row.get("max_service_deceleration_ms2")
                d_emerg = row.get("emergency_deceleration_ms2")

                if m_empty and m_loaded and m_loaded < m_empty:
                    self.report.add_finding(
                        error_code="ERR_ENG_MASS_INCONSISTENCY",
                        severity=Severity.ERROR,
                        message=f"TrainType '{ttid}' loaded mass ({m_loaded}) cannot be less than tare mass ({m_empty}).",
                        workbook="ROLLING_STOCK",
                        worksheet="TrainTypes",
                        object_id=ttid,
                    )

                if d_serv and d_emerg and d_emerg < d_serv:
                    self.report.add_finding(
                        error_code="ERR_ENG_BRAKING_INCONSISTENCY",
                        severity=Severity.ERROR,
                        message=f"TrainType '{ttid}' emergency deceleration ({d_emerg} m/s²) should be >= service deceleration ({d_serv} m/s²).",
                        workbook="ROLLING_STOCK",
                        worksheet="TrainTypes",
                        object_id=ttid,
                    )

    def _validate_simulation_readiness(self, raw_workbooks: Dict[str, RawWorkbookData]) -> None:
        """Evaluate Level 5 simulation readiness."""
        required_wbs = ["INFRASTRUCTURE", "ROLLING_STOCK", "SIGNALLING", "OPERATIONS"]
        missing = [wb for wb in required_wbs if wb not in raw_workbooks]

        if missing:
            self.report.add_finding(
                error_code="ERR_SIMULATION_READINESS_INCOMPLETE",
                severity=Severity.CRITICAL,
                message=f"Simulation readiness check failed. Missing mandatory workbooks: {missing}.",
                recommendation="Upload all four core engineering workbooks (Infrastructure, Rolling Stock, Signalling, Operations).",
            )
        elif not self.report.has_errors:
            self.report.add_finding(
                error_code="INFO_SIMULATION_READY",
                severity=Severity.INFO,
                message="All data contracts and engineering configuration checks passed. Simulation readiness confirmed.",
            )
