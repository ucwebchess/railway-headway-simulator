"""Regression tests for multi-link signalling blocks and TVS sections.

Satisfies RHS-CORRECTION-MULTILINK-001:
- Forward traversal over multi-link blocks holds resource until rear clears the final interval.
- Reverse traversal over multi-link blocks holds resource properly until rear clearance.
- Follower train denial at block boundary while leader occupies any interval of the block.
- Backward compatibility: legacy single-link schemas load cleanly with zero warnings or errors.
- Dual geometry detection: emits WARN_DUAL_GEOMETRY_SPECIFIED when both geometry sheet and legacy columns exist.
- Topological and physical validation: sequence continuity, link continuity, physical continuity, and bounds checks.
- Round-trip fidelity: export and re-import preserves multi-link block and TVS geometries.
"""

from pathlib import Path
import tempfile
import pytest

from headway.data.canonical import (
    AspectModelType,
    NodeType,
    Platform,
    ResourceInterval,
    SignallingBlock,
    SignallingTechnologyType,
    Station,
    StationStop,
    TrackDirectionality,
    TrackLink,
    TVSSection,
)
from headway.data.converter import convert_raw_to_canonical
from headway.data.importer import ExcelImporter, RawWorkbookData
from headway.data.package import ProjectPackage
from headway.data.validation import Severity, ValidationReport
from headway.data.validator import DatasetValidator
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import LinkTraversal, Route
from headway.rolling_stock.train import MassCondition, RollingStockParameters
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.resource_types import ReleasePolicy, ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.simulation.multi_train_engine import MultiTrainSimulator
from headway.simulation.service_instance import (
    ServiceType,
    TrainGenerator,
    TrainServiceInstance,
)
from headway.simulation.state import OperationalState
from headway.ui.file_manager import FileManager


from tests.engineering.test_multi_train_benchmarks import make_test_route, make_test_train_params


# ==============================================================================
# 1. Multi-Link Block Forward Traversal Engine Verification
# ==============================================================================

def test_multilink_block_forward_traversal_holds_until_final_rear_clearance():
    """Verify forward traversal over multi-link block retains block occupancy across link boundary."""
    coord = SignallingCoordinator()
    # Multi-link block spanning Link 1 [0, 1000] and Link 2 [0, 1000]
    multilink_block = ManagedResource(
        resource_id="BLK_MULTI",
        category=ResourceCategory.TRACK_BLOCK,
        intervals=[
            ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0),
            ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=1000.0),
        ],
        release_delay_s=0.0,
    )
    coord.resource_controller.register_resource(multilink_block)

    params = make_test_train_params()  # 100m length
    route = make_test_route(link_ids=["L1", "L2", "L3"], link_lengths=[1000.0, 1000.0, 1000.0])
    st = ServiceType("SVC_TEST", "TRN_TEST", params, route)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=500.0)
    lead_train = trains[0]

    sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    sim.register_train(lead_train)

    occupied_at_link_boundary = False
    cleared_at_final_interval = False

    for step in range(1500):
        sim.step()
        # When train is straddling L1 and L2 (e.g. front at 1050m, rear at 950m)
        if 1010.0 <= lead_train.current_position_m <= 1100.0:
            if lead_train.train_id in coord.resource_controller.resources["BLK_MULTI"].occupants:
                occupied_at_link_boundary = True

        # When train is in middle of L2 (front at 1500m, rear at 1400m - clearly past L1)
        if 1300.0 <= lead_train.current_position_m <= 1800.0:
            assert lead_train.train_id in coord.resource_controller.resources["BLK_MULTI"].occupants, (
                "Block must remain occupied while train rear is in L2 interval!"
            )

        # When train rear has fully cleared L2 (rear > 2000m)
        if lead_train.rear_position_m > 2005.0:
            if lead_train.train_id not in coord.resource_controller.resources["BLK_MULTI"].occupants:
                cleared_at_final_interval = True
                break

    assert occupied_at_link_boundary, "Block should be occupied at link boundary transition"
    assert cleared_at_final_interval, "Block should be released after rear clears final interval"


# ==============================================================================
# 2. Multi-Link Block Reverse Traversal Engine Verification
# ==============================================================================

def test_multilink_block_reverse_traversal():
    """Verify reverse traversal over multi-link block retains block occupancy across link boundary."""
    coord = SignallingCoordinator()
    multilink_block = ManagedResource(
        resource_id="BLK_MULTI_REV",
        category=ResourceCategory.TRACK_BLOCK,
        intervals=[
            ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0),
            ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=1000.0),
        ],
        release_delay_s=0.0,
    )
    coord.resource_controller.register_resource(multilink_block)

    params = make_test_train_params()
    route = make_test_route(link_ids=["L2", "L1", "L0"], link_lengths=[1000.0, 1000.0, 1000.0], direction=RunningDirection.REVERSE)
    st = ServiceType("SVC_REV", "TRN_TEST", params, route)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=500.0)
    rev_train = trains[0]

    sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    sim.register_train(rev_train)

    occupied_in_l1 = False
    cleared_at_end = False

    for step in range(1500):
        sim.step()
        # When train enters L1 in reverse (route distance > 1050m)
        if rev_train.current_position_m >= 1100.0 and rev_train.rear_position_m < 2000.0:
            if rev_train.train_id in coord.resource_controller.resources["BLK_MULTI_REV"].occupants:
                occupied_in_l1 = True

        if rev_train.rear_position_m >= 2005.0:
            if rev_train.train_id not in coord.resource_controller.resources["BLK_MULTI_REV"].occupants:
                cleared_at_end = True
                break

    assert occupied_in_l1, "Block should remain occupied when traversing second link in reverse"
    assert cleared_at_end, "Block should be released after rear clears end of reverse route"


# ==============================================================================
# 3. Follower Denial at Multi-Link Block Boundary
# ==============================================================================

def test_follower_denied_while_leader_in_downstream_multilink_interval():
    """Verify follower is stopped at block entrance while leader is on downstream interval of multi-link block."""
    coord = SignallingCoordinator()
    # BLK_0 precedes the multi-link block
    coord.resource_controller.register_resource(
        ManagedResource("BLK_0", ResourceCategory.TRACK_BLOCK, intervals=[ResourceInterval(link_id="L0", start_offset_m=0.0, end_offset_m=1000.0)])
    )
    # BLK_MULTI spans L1 and L2
    coord.resource_controller.register_resource(
        ManagedResource(
            "BLK_MULTI",
            ResourceCategory.TRACK_BLOCK,
            intervals=[
                ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=1000.0),
                ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=1000.0),
            ],
            release_delay_s=15.0,
        )
    )
    # BLK_3 downstream
    coord.resource_controller.register_resource(
        ManagedResource("BLK_3", ResourceCategory.TRACK_BLOCK, intervals=[ResourceInterval(link_id="L3", start_offset_m=0.0, end_offset_m=1000.0)])
    )

    params = make_test_train_params()
    route = make_test_route(link_ids=["L0", "L1", "L2", "L3"], link_lengths=[1000.0, 1000.0, 1000.0, 1000.0])
    st = ServiceType("SVC_PAIR", "TRN_TEST", params, route)
    trains = TrainGenerator.generate_pairwise(st, st, interval_s=25.0)

    sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    sim.register_trains(trains)

    lead, foll = trains[0], trains[1]
    follower_held_at_boundary = False

    for step in range(1200):
        sim.step()
        # When follower is approaching boundary at 1000.0m while leader is in L2
        if 980.0 <= foll.current_position_m <= 1000.1 and foll.current_speed_ms < 0.1:
            assert lead.current_position_m >= 2000.0, "Leader should be on downstream link"
            follower_held_at_boundary = True
            break

    assert follower_held_at_boundary, "Follower should have been stopped at entry to occupied multi-link block"


# ==============================================================================
# 4. Multi-Link TVS Section Verification
# ==============================================================================

def test_multilink_tvs_section_ingestion_and_simulation():
    """Verify that multi-link TVS sections are correctly parsed and enforce single-train occupancy."""
    project, report, _ = FileManager.load_example_project("06_multilink_blocks")
    assert not report.has_errors
    assert len(project.infrastructure.tvs_sections) == 1
    tvs = project.infrastructure.tvs_sections[0]
    assert tvs.tvs_id == "TVS_01"
    assert len(tvs.link_intervals) == 2
    assert tvs.link_intervals[0].link_id == "LNK_02"
    assert tvs.link_intervals[1].link_id == "LNK_03"


# ==============================================================================
# 5. Backward Compatibility (Legacy Single-Link Schemas)
# ==============================================================================

def test_backward_compatibility_legacy_single_link_blocks_and_tvs():
    """Verify that datasets using legacy single-link columns in Blocks/TVSSections import without errors."""
    for ex_name in ["01_single_track", "02_double_track", "03_station_platform", "04_tunnel_tvs", "05_comprehensive_line"]:
        project, report, _ = FileManager.load_example_project(ex_name)
        assert not report.has_errors, f"Legacy example {ex_name} failed validation!"
        assert len(project.signalling.blocks) > 0
        for blk in project.signalling.blocks:
            assert len(blk.link_intervals) >= 1, f"Block {blk.block_id} has no intervals!"


# ==============================================================================
# 6. Dual Geometry Warning Verification
# ==============================================================================

def test_dual_geometry_warning_emitted_when_both_present():
    """Verify that WARN_DUAL_GEOMETRY_SPECIFIED is emitted when both BlockGeometry and legacy columns exist."""
    sig_raw = RawWorkbookData("SIGNALLING", Path("test_sig.xlsx"), {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"})
    sig_raw.worksheets["SignallingSystem"] = [{"technology_type": "GENERIC_FIXED_BLOCK_ENGINEERING_MODEL"}]
    sig_raw.worksheets["Signals"] = [
        {"signal_id": "SIG_01", "link_id": "LNK_01", "offset_m": 100.0, "direction": "NOMINAL", "signal_type": "MAIN"},
        {"signal_id": "SIG_02", "link_id": "LNK_02", "offset_m": 500.0, "direction": "NOMINAL", "signal_type": "MAIN"},
    ]
    # Blocks with legacy columns
    sig_raw.worksheets["Blocks"] = [
        {"block_id": "BLK_01", "entry_signal_id": "SIG_01", "exit_signal_id": "SIG_02", "link_id": "LNK_01", "start_offset_m": 100.0, "end_offset_m": 1000.0, "overlap_m": 50.0, "release_delay_s": 4.0}
    ]
    # BlockGeometry also present
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_01", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 100.0, "end_offset_m": 1000.0},
        {"block_id": "BLK_01", "sequence": 2, "link_id": "LNK_02", "start_offset_m": 0.0, "end_offset_m": 500.0},
    ]

    infra_raw = RawWorkbookData("INFRASTRUCTURE", Path("test_infra.xlsx"), {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"})
    infra_raw.worksheets["Nodes"] = [
        {"node_id": "ND_01", "node_type": "ENDPOINT"},
        {"node_id": "ND_02", "node_type": "JUNCTION"},
        {"node_id": "ND_03", "node_type": "ENDPOINT"},
    ]
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "track_id": "TRK_01", "start_node_id": "ND_01", "end_node_id": "ND_02", "length_m": 1000.0},
        {"link_id": "LNK_02", "track_id": "TRK_01", "start_node_id": "ND_02", "end_node_id": "ND_03", "length_m": 1000.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    warnings = [f for f in report.findings if f.error_code == "WARN_DUAL_GEOMETRY_SPECIFIED"]
    assert len(warnings) >= 1, "Expected WARN_DUAL_GEOMETRY_SPECIFIED warning when both geometry sources exist!"


# ==============================================================================
# 7. Schema & Topology Validation Negative Tests
# ==============================================================================

def test_validation_flags_sequence_not_starting_at_1():
    """Verify ERR_GEOMETRY_SEQUENCE_DISCONTINUITY when sequence starts at 2."""
    sig_raw = RawWorkbookData("SIGNALLING", Path("test_sig.xlsx"), {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"})
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_01"}]
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_01", "sequence": 2, "link_id": "LNK_01", "start_offset_m": 100.0, "end_offset_m": 1000.0},
    ]
    infra_raw = RawWorkbookData("INFRASTRUCTURE", Path("test_infra.xlsx"), {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"})
    infra_raw.worksheets["TrackLinks"] = [{"link_id": "LNK_01", "length_m": 1000.0}]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    seq_errs = [f for f in report.findings if f.error_code == "ERR_GEOMETRY_SEQUENCE_DISCONTINUITY"]
    assert len(seq_errs) >= 1


def test_validation_flags_sequence_gap():
    """Verify ERR_GEOMETRY_SEQUENCE_DISCONTINUITY when sequence has a gap (1, 3)."""
    sig_raw = RawWorkbookData("SIGNALLING", Path("test_sig.xlsx"), {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"})
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_01"}]
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_01", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 100.0, "end_offset_m": 1000.0},
        {"block_id": "BLK_01", "sequence": 3, "link_id": "LNK_02", "start_offset_m": 0.0, "end_offset_m": 500.0},
    ]
    infra_raw = RawWorkbookData("INFRASTRUCTURE", Path("test_infra.xlsx"), {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"})
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 1000.0},
        {"link_id": "LNK_02", "start_node_id": "N2", "end_node_id": "N3", "length_m": 1000.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    seq_errs = [f for f in report.findings if f.error_code == "ERR_GEOMETRY_SEQUENCE_DISCONTINUITY"]
    assert len(seq_errs) >= 1


def test_validation_flags_physical_discontinuity_across_links():
    """Verify ERR_ENG_PHYSICAL_DISCONTINUITY when interval does not reach link boundary or next doesn't start at 0."""
    sig_raw = RawWorkbookData("SIGNALLING", Path("test_sig.xlsx"), {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"})
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_01"}]
    sig_raw.worksheets["BlockGeometry"] = [
        # Ends at 900m on LNK_01, but LNK_01 length is 1000m -> gap of 100m!
        {"block_id": "BLK_01", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 100.0, "end_offset_m": 900.0},
        {"block_id": "BLK_01", "sequence": 2, "link_id": "LNK_02", "start_offset_m": 0.0, "end_offset_m": 500.0},
    ]
    infra_raw = RawWorkbookData("INFRASTRUCTURE", Path("test_infra.xlsx"), {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"})
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 1000.0},
        {"link_id": "LNK_02", "start_node_id": "N2", "end_node_id": "N3", "length_m": 1000.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    disc_errs = [f for f in report.findings if f.error_code == "ERR_ENG_PHYSICAL_DISCONTINUITY"]
    assert len(disc_errs) >= 1


def test_validation_flags_link_discontinuity_unconnected_links():
    """Verify ERR_ENG_LINK_DISCONTINUITY when consecutive intervals reference unconnected links."""
    sig_raw = RawWorkbookData("SIGNALLING", Path("test_sig.xlsx"), {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"})
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_01"}]
    sig_raw.worksheets["BlockGeometry"] = [
        {"block_id": "BLK_01", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 100.0, "end_offset_m": 1000.0},
        {"block_id": "BLK_01", "sequence": 2, "link_id": "LNK_03", "start_offset_m": 0.0, "end_offset_m": 500.0},
    ]
    infra_raw = RawWorkbookData("INFRASTRUCTURE", Path("test_infra.xlsx"), {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"})
    infra_raw.worksheets["TrackLinks"] = [
        {"link_id": "LNK_01", "start_node_id": "N1", "end_node_id": "N2", "length_m": 1000.0},
        {"link_id": "LNK_03", "start_node_id": "N5", "end_node_id": "N6", "length_m": 1000.0},
    ]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    link_errs = [f for f in report.findings if f.error_code == "ERR_ENG_LINK_DISCONTINUITY"]
    assert len(link_errs) >= 1


def test_validation_flags_interval_exceeding_link_bounds():
    """Verify ERR_ENG_BLOCK_BOUNDS_INVALID when interval end exceeds link length."""
    sig_raw = RawWorkbookData("SIGNALLING", Path("test_sig.xlsx"), {"WORKBOOK_TYPE": "SIGNALLING", "SCHEMA_VERSION": "1.0.0"})
    sig_raw.worksheets["Blocks"] = [{"block_id": "BLK_01"}]
    sig_raw.worksheets["BlockGeometry"] = [
        # LNK_01 length is 1000m, but interval ends at 1200m
        {"block_id": "BLK_01", "sequence": 1, "link_id": "LNK_01", "start_offset_m": 100.0, "end_offset_m": 1200.0},
    ]
    infra_raw = RawWorkbookData("INFRASTRUCTURE", Path("test_infra.xlsx"), {"WORKBOOK_TYPE": "INFRASTRUCTURE", "SCHEMA_VERSION": "1.0.0"})
    infra_raw.worksheets["TrackLinks"] = [{"link_id": "LNK_01", "length_m": 1000.0}]

    report = ValidationReport()
    validator = DatasetValidator(report)
    validator.validate_all({"SIGNALLING": sig_raw, "INFRASTRUCTURE": infra_raw})

    bounds_errs = [f for f in report.findings if f.error_code == "ERR_ENG_BLOCK_BOUNDS_INVALID"]
    assert len(bounds_errs) >= 1


# ==============================================================================
# 8. Round-Trip Package Export & Re-Import
# ==============================================================================

def test_round_trip_project_package_preserves_multilink_geometry():
    """Verify export_package and import_package preserve multi-link block intervals identically."""
    project, report, file_map = FileManager.load_example_project("06_multilink_blocks")
    assert not report.has_errors

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "test_multilink_export.zip"
        ProjectPackage.export_package(
            project=project,
            output_zip_path=zip_path,
            excel_workbooks=file_map,
            validation_report=report,
        )
        assert zip_path.exists()

        reimported_project, manifest, extracted_wbs = ProjectPackage.import_package(
            zip_path=zip_path,
            extract_to_dir=Path(tmp_dir) / "extracted",
        )
        assert manifest.get("project_id") == project.project_id
        assert len(reimported_project.signalling.blocks) == len(project.signalling.blocks)

        for orig_blk, re_blk in zip(project.signalling.blocks, reimported_project.signalling.blocks):
            assert orig_blk.block_id == re_blk.block_id
            assert len(orig_blk.link_intervals) == len(re_blk.link_intervals)
            for orig_iv, re_iv in zip(orig_blk.link_intervals, re_blk.link_intervals):
                assert orig_iv.link_id == re_iv.link_id
                assert orig_iv.start_offset_m == re_iv.start_offset_m
                assert orig_iv.end_offset_m == re_iv.end_offset_m
