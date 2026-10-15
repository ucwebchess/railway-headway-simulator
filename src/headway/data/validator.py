"""Cross-reference (Level 3), engineering configuration (Level 4), and simulation readiness (Level 5) validation.

Strictly satisfies RHS-P01-001 § 15 and § 16.
Enforces physical and relational integrity without executing microscopic train dynamics.
"""

from typing import Any, Dict, List, Optional, Tuple
from headway.core.identifiers import IdentifierRegistry, normalize_identifier
from headway.data.importer import RawWorkbookData, _parse_list_cell
from headway.data.validation import Severity, ValidationReport

# Tolerance for geometric continuity checks.
# Real railway geometry is not accurate below the millimetre scale.
GEOMETRY_TOLERANCE_M: float = 0.001  # 1 mm


def _within_tolerance(a: float, b: float) -> bool:
    """Return True if |a - b| <= GEOMETRY_TOLERANCE_M."""
    return abs(a - b) <= GEOMETRY_TOLERANCE_M


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

            for row in infra.get_rows("SharedResourceGroups"):
                gid = row.get("group_id")
                if gid:
                    self._safe_register("RESOURCE_GROUP", gid, "INFRASTRUCTURE", "SharedResourceGroups", row.get("_row"))

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

            # TVS sections
            infra_tvs_geom = infra.get_rows("TVSGeometry")
            sig_wb = raw_workbooks.get("SIGNALLING")
            sig_tvs_geom = sig_wb.get_rows("TVSGeometry") if sig_wb else []
            has_tvs_geom = bool(infra_tvs_geom or sig_tvs_geom)

            for row in infra.get_rows("TVSSections"):
                tvs_id = row.get("tvs_id")
                self._check_ref("TRACK", row.get("track_id"), "TVSSections.track_id", "INFRASTRUCTURE", "TVSSections", tvs_id)
                if row.get("link_id") is not None or not has_tvs_geom:
                    self._check_ref("LINK", row.get("link_id"), "TVSSections.link_id", "INFRASTRUCTURE", "TVSSections", tvs_id)
                if row.get("tunnel_id") and self.registry.get_all("TUNNEL"):
                    self._check_ref("TUNNEL", row.get("tunnel_id"), "TVSSections.tunnel_id", "INFRASTRUCTURE", "TVSSections", tvs_id)
                if row.get("holding_signal_id"):
                    self._check_ref("SIGNAL", row.get("holding_signal_id"), "TVSSections.holding_signal_id", "INFRASTRUCTURE", "TVSSections", tvs_id)

            for row in infra_tvs_geom:
                tvs_id = row.get("tvs_id")
                self._check_ref("TVS", tvs_id, "TVSGeometry.tvs_id", "INFRASTRUCTURE", "TVSGeometry", tvs_id)
                self._check_ref("LINK", row.get("link_id"), "TVSGeometry.link_id", "INFRASTRUCTURE", "TVSGeometry", tvs_id)

            for row in infra.get_rows("SharedResourceGroups"):
                gid = row.get("group_id")
                raw_res = row.get("resource_ids")
                res_list = _parse_list_cell(raw_res)
                for res_id in res_list:
                    if not res_id:
                        continue
                    clean_res = str(res_id).strip()
                    if not (self.registry.exists("BLOCK", clean_res) or self.registry.exists("TVS", clean_res)):
                        self.report.add_finding(
                            error_code="ERR_REF_MISSING",
                            severity=Severity.ERROR,
                            message=f"SharedResourceGroups.resource_ids references non-existent BLOCK or TVS resource '{clean_res}'.",
                            workbook="INFRASTRUCTURE",
                            worksheet="SharedResourceGroups",
                            object_id=gid,
                            column="RESOURCE_IDS",
                            recommendation=f"Ensure resource '{clean_res}' is defined in SIGNALLING Blocks or INFRASTRUCTURE TVSSections.",
                        )

        sig = raw_workbooks.get("SIGNALLING")
        if sig:
            for row in sig.get_rows("Signals"):
                sid = row.get("signal_id")
                self._check_ref("LINK", row.get("link_id"), "Signals.link_id", "SIGNALLING", "Signals", sid)

            block_geom_rows = sig.get_rows("BlockGeometry")
            has_block_geom = bool(block_geom_rows)

            for row in sig.get_rows("Blocks"):
                bid = row.get("block_id")
                if row.get("link_id") is not None or not has_block_geom:
                    self._check_ref("LINK", row.get("link_id"), "Blocks.link_id", "SIGNALLING", "Blocks", bid)
                if row.get("entry_signal_id"):
                    self._check_ref("SIGNAL", row.get("entry_signal_id"), "Blocks.entry_signal_id", "SIGNALLING", "Blocks", bid)
                if row.get("exit_signal_id"):
                    self._check_ref("SIGNAL", row.get("exit_signal_id"), "Blocks.exit_signal_id", "SIGNALLING", "Blocks", bid)

            for row in block_geom_rows:
                bid = row.get("block_id")
                self._check_ref("BLOCK", bid, "BlockGeometry.block_id", "SIGNALLING", "BlockGeometry", bid)
                self._check_ref("LINK", row.get("link_id"), "BlockGeometry.link_id", "SIGNALLING", "BlockGeometry", bid)

            for row in sig.get_rows("TVSGeometry"):
                tvs_id = row.get("tvs_id")
                self._check_ref("TVS", tvs_id, "TVSGeometry.tvs_id", "SIGNALLING", "TVSGeometry", tvs_id)
                self._check_ref("LINK", row.get("link_id"), "TVSGeometry.link_id", "SIGNALLING", "TVSGeometry", tvs_id)

            for row in sig.get_rows("InterlockingRoutes"):
                rid = row.get("route_id")
                self._check_ref("SIGNAL", row.get("entry_signal_id"), "InterlockingRoutes.entry_signal_id", "SIGNALLING", "InterlockingRoutes", rid)
                self._check_ref("SIGNAL", row.get("exit_signal_id"), "InterlockingRoutes.exit_signal_id", "SIGNALLING", "InterlockingRoutes", rid)
                for l in _parse_list_cell(row.get("link_sequence")):
                    self._check_ref("LINK", l, f"InterlockingRoutes.link_sequence[{l}]", "SIGNALLING", "InterlockingRoutes", rid)
                for b in _parse_list_cell(row.get("protected_blocks")):
                    self._check_ref("BLOCK", b, f"InterlockingRoutes.protected_blocks[{b}]", "SIGNALLING", "InterlockingRoutes", rid)

        ops = raw_workbooks.get("OPERATIONS")
        if ops:
            for row in ops.get_rows("ServicePatterns"):
                spid = row.get("service_pattern_id")
                self._check_ref("TRAIN_TYPE", row.get("train_type_id"), "ServicePatterns.train_type_id", "OPERATIONS", "ServicePatterns", spid)
                for l in _parse_list_cell(row.get("route_link_sequence")):
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

    def _validate_resource_geometry(
        self,
        resource_type: str,
        master_rows: List[Dict[str, Any]],
        geom_rows: List[Dict[str, Any]],
        link_lengths: Dict[str, float],
        link_nodes: Dict[str, Tuple[Optional[str], Optional[str]]],
        workbook: str,
        master_ws: str,
        geom_ws: str,
        id_field: str,
    ) -> None:
        """Validate multi-link resource intervals, sequence continuity, link continuity, and physical continuity."""
        has_geom = len(geom_rows) > 0
        has_legacy = any(r.get("link_id") is not None for r in master_rows)

        # Dual geometry warning (Task 3)
        if has_geom and has_legacy:
            self.report.add_finding(
                error_code="WARN_DUAL_GEOMETRY_SPECIFIED",
                severity=Severity.WARNING,
                message=f"Both '{geom_ws}' worksheet and legacy geometry columns in '{master_ws}' are present. '{geom_ws}' will take precedence.",
                workbook=workbook,
                worksheet=master_ws,
                recommendation=f"Remove deprecated geometry columns (LINK_ID, START_OFFSET_M, END_OFFSET_M) from '{master_ws}'.",
            )

        err_bounds_code = "ERR_ENG_BLOCK_BOUNDS_INVALID" if id_field == "block_id" else "ERR_ENG_TVS_BOUNDS_INVALID"

        geom_by_id: Dict[str, List[Dict[str, Any]]] = {}
        for r in geom_rows:
            rid = r.get(id_field)
            if rid:
                geom_by_id.setdefault(rid, []).append(r)

        for master_row in master_rows:
            rid = master_row.get(id_field)
            if not rid:
                continue

            if has_geom and rid in geom_by_id:
                res_geom = geom_by_id[rid]

                # 1. Sequence continuity starting at 1
                try:
                    sorted_geom = sorted(res_geom, key=lambda x: int(x.get("sequence", 0)))
                    actual_seqs = [int(x.get("sequence", 0)) for x in sorted_geom]
                except (ValueError, TypeError):
                    actual_seqs = []
                    sorted_geom = res_geom

                expected_seqs = list(range(1, len(sorted_geom) + 1))
                if actual_seqs != expected_seqs:
                    self.report.add_finding(
                        error_code="ERR_GEOMETRY_SEQUENCE_DISCONTINUITY",
                        severity=Severity.ERROR,
                        message=f"{resource_type} '{rid}' sequence must start at 1 and be strictly contiguous without gaps (got {actual_seqs}).",
                        workbook=workbook,
                        worksheet=geom_ws,
                        object_id=rid,
                        column="SEQUENCE",
                        recommendation=f"Renumber intervals for '{rid}' consecutively starting at 1.",
                    )

                # 2. Link bounds clamping/validation for each interval
                for g_row in sorted_geom:
                    seq = g_row.get("sequence")
                    lid = g_row.get("link_id")
                    start = g_row.get("start_offset_m")
                    end = g_row.get("end_offset_m")

                    if start is None or end is None:
                        continue

                    if start < -GEOMETRY_TOLERANCE_M or start >= end:
                        self.report.add_finding(
                            error_code=err_bounds_code,
                            severity=Severity.ERROR,
                            message=f"{resource_type} '{rid}' sequence {seq} interval [{start}, {end}] on link '{lid}' is inverted or negative.",
                            workbook=workbook,
                            worksheet=geom_ws,
                            object_id=rid,
                        )

                    if lid in link_lengths:
                        max_len = link_lengths[lid]
                        if end > max_len + GEOMETRY_TOLERANCE_M:
                            self.report.add_finding(
                                error_code=err_bounds_code,
                                severity=Severity.ERROR,
                                message=f"{resource_type} '{rid}' sequence {seq} end offset {end} m exceeds link '{lid}' length ({max_len} m).",
                                workbook=workbook,
                                worksheet=geom_ws,
                                object_id=rid,
                            )

                # 3. Link continuity across intervals & physical continuity
                for i in range(len(sorted_geom) - 1):
                    curr = sorted_geom[i]
                    nxt = sorted_geom[i + 1]
                    curr_seq = curr.get("sequence")
                    nxt_seq = nxt.get("sequence")
                    curr_lid = curr.get("link_id")
                    nxt_lid = nxt.get("link_id")
                    curr_end = curr.get("end_offset_m")
                    nxt_start = nxt.get("start_offset_m")

                    if curr_lid == nxt_lid:
                        # Same link: offsets must be contiguous
                        if curr_end is not None and nxt_start is not None and not _within_tolerance(curr_end, nxt_start):
                            self.report.add_finding(
                                error_code="ERR_ENG_PHYSICAL_DISCONTINUITY",
                                severity=Severity.ERROR,
                                message=f"{resource_type} '{rid}' physical discontinuity on link '{curr_lid}' between sequence {curr_seq} (end {curr_end} m) and sequence {nxt_seq} (start {nxt_start} m).",
                                workbook=workbook,
                                worksheet=geom_ws,
                                object_id=rid,
                            )
                    else:
                        # Different links:
                        # A. Link continuity in network graph
                        curr_nodes = link_nodes.get(curr_lid)
                        nxt_nodes = link_nodes.get(nxt_lid)
                        if curr_nodes and nxt_nodes:
                            curr_s_node, curr_e_node = curr_nodes
                            nxt_s_node, nxt_e_node = nxt_nodes
                            shared = {curr_s_node, curr_e_node} & {nxt_s_node, nxt_e_node}
                            if not shared:
                                self.report.add_finding(
                                    error_code="ERR_ENG_LINK_DISCONTINUITY",
                                    severity=Severity.ERROR,
                                    message=f"{resource_type} '{rid}' consecutive intervals on links '{curr_lid}' and '{nxt_lid}' do not connect at a common node.",
                                    workbook=workbook,
                                    worksheet=geom_ws,
                                    object_id=rid,
                                )
                            else:
                                # B. Physical continuity across boundary
                                curr_len = link_lengths.get(curr_lid)
                                nxt_len = link_lengths.get(nxt_lid)
                                is_continuous = False

                                if curr_e_node == nxt_s_node:
                                    if curr_len is not None and _within_tolerance(curr_end, curr_len) and _within_tolerance(nxt_start, 0.0):
                                        is_continuous = True
                                elif curr_e_node == nxt_e_node:
                                    if curr_len is not None and nxt_len is not None and _within_tolerance(curr_end, curr_len) and _within_tolerance(nxt_start, nxt_len):
                                        is_continuous = True
                                elif curr_s_node == nxt_s_node:
                                    if _within_tolerance(curr_end, 0.0) and _within_tolerance(nxt_start, 0.0):
                                        is_continuous = True
                                elif curr_s_node == nxt_e_node:
                                    if nxt_len is not None and _within_tolerance(curr_end, 0.0) and _within_tolerance(nxt_start, nxt_len):
                                        is_continuous = True

                                if not is_continuous:
                                    self.report.add_finding(
                                        error_code="ERR_ENG_PHYSICAL_DISCONTINUITY",
                                        severity=Severity.ERROR,
                                        message=f"{resource_type} '{rid}' physical discontinuity across boundary between link '{curr_lid}' (end {curr_end} m, length {curr_len} m) and link '{nxt_lid}' (start {nxt_start} m).",
                                        workbook=workbook,
                                        worksheet=geom_ws,
                                        object_id=rid,
                                    )
            else:
                # Fallback to legacy columns on master row
                lid = master_row.get("link_id")
                start = master_row.get("start_offset_m")
                end = master_row.get("end_offset_m")
                if not lid or start is None or end is None:
                    self.report.add_finding(
                        error_code="ERR_GEOMETRY_MISSING",
                        severity=Severity.ERROR,
                        message=f"{resource_type} '{rid}' has no geometry intervals defined in '{geom_ws}' and missing legacy columns in '{master_ws}'.",
                        workbook=workbook,
                        worksheet=master_ws,
                        object_id=rid,
                    )
                else:
                    if lid in link_lengths:
                        max_len = link_lengths[lid]
                        if (
                            start < -GEOMETRY_TOLERANCE_M
                            or start > max_len + GEOMETRY_TOLERANCE_M
                            or end < -GEOMETRY_TOLERANCE_M
                            or end > max_len + GEOMETRY_TOLERANCE_M
                            or start >= end
                        ):
                            self.report.add_finding(
                                error_code=err_bounds_code,
                                severity=Severity.ERROR,
                                message=f"{resource_type} '{rid}' interval [{start}, {end}] exceeds link '{lid}' length ({max_len} m) or is inverted.",
                                workbook=workbook,
                                worksheet=master_ws,
                                object_id=rid,
                            )

    def _validate_engineering_configuration(self, raw_workbooks: Dict[str, RawWorkbookData]) -> None:
        """Validate engineering boundaries, spatial offset limits, and physical parameters (Level 4)."""
        # Map link_id -> length_m and link_id -> (start_node_id, end_node_id)
        link_lengths: Dict[str, float] = {}
        link_nodes: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        infra = raw_workbooks.get("INFRASTRUCTURE")
        if infra:
            for row in infra.get_rows("TrackLinks"):
                lid = row.get("link_id")
                length = row.get("length_m")
                s_node = row.get("start_node_id")
                e_node = row.get("end_node_id")
                if lid:
                    link_nodes[lid] = (s_node, e_node)
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
                    if (
                        start < -GEOMETRY_TOLERANCE_M
                        or start > max_len + GEOMETRY_TOLERANCE_M
                        or end < -GEOMETRY_TOLERANCE_M
                        or end > max_len + GEOMETRY_TOLERANCE_M
                        or start >= end
                    ):
                        self.report.add_finding(
                            error_code="ERR_ENG_OFFSET_OUT_OF_BOUNDS",
                            severity=Severity.ERROR,
                            message=f"Platform '{pid}' interval [{start}, {end}] exceeds link '{lid}' length ({max_len} m) or is inverted.",
                            workbook="INFRASTRUCTURE",
                            worksheet="Platforms",
                            object_id=pid,
                        )

            # TVS sections positive occupancy
            for row in infra.get_rows("TVSSections"):
                tvs_id = row.get("tvs_id")
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

            # TVS geometry validation
            sig = raw_workbooks.get("SIGNALLING")
            tvs_geom_rows = infra.get_rows("TVSGeometry")
            tvs_wb_name = "INFRASTRUCTURE"
            if not tvs_geom_rows and sig:
                tvs_geom_rows = sig.get_rows("TVSGeometry")
                if tvs_geom_rows:
                    tvs_wb_name = "SIGNALLING"

            self._validate_resource_geometry(
                resource_type="TVS section",
                master_rows=infra.get_rows("TVSSections"),
                geom_rows=tvs_geom_rows,
                link_lengths=link_lengths,
                link_nodes=link_nodes,
                workbook=tvs_wb_name,
                master_ws="TVSSections",
                geom_ws="TVSGeometry",
                id_field="tvs_id",
            )

        # Performance Factor validation [0.5, 1.0]
        an = raw_workbooks.get("HEADWAY_ANALYSIS")
        if an:
            for row in an.get_rows("AnalysisSettings"):
                pf = row.get("performance_factor")
                if pf is not None:
                    try:
                        v = float(pf)
                        if v < 0.5 or v > 1.0:
                            self.report.add_finding(
                                error_code="ERR_FIELD_RANGE",
                                severity=Severity.ERROR,
                                message=f"Analysis '{row.get('analysis_id')}' performance_factor {v} is outside allowed range [0.5, 1.0].",
                                workbook="HEADWAY_ANALYSIS",
                                worksheet="AnalysisSettings",
                                column="PERFORMANCE_FACTOR",
                                row=row.get("_row"),
                            )
                    except (ValueError, TypeError):
                        pass

        scn = raw_workbooks.get("SCENARIOS")
        if scn:
            for row in scn.get_rows("ScenarioDefinitions"):
                dpf = row.get("default_performance_factor")
                if dpf is not None:
                    try:
                        v = float(dpf)
                        if v < 0.5 or v > 1.0:
                            self.report.add_finding(
                                error_code="ERR_FIELD_RANGE",
                                severity=Severity.ERROR,
                                message=f"Scenario '{row.get('scenario_id')}' default_performance_factor {v} is outside allowed range [0.5, 1.0].",
                                workbook="SCENARIOS",
                                worksheet="ScenarioDefinitions",
                                column="DEFAULT_PERFORMANCE_FACTOR",
                                row=row.get("_row"),
                            )
                    except (ValueError, TypeError):
                        pass

        # Signalling blocks
        sig = raw_workbooks.get("SIGNALLING")
        if sig:
            self._validate_resource_geometry(
                resource_type="Signalling block",
                master_rows=sig.get_rows("Blocks"),
                geom_rows=sig.get_rows("BlockGeometry"),
                link_lengths=link_lengths,
                link_nodes=link_nodes,
                workbook="SIGNALLING",
                master_ws="Blocks",
                geom_ws="BlockGeometry",
                id_field="block_id",
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
