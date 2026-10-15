"""Integration tests for schematic station position calculation (RHS-CORRECTION-SCHEMATIC-POS-001).

Validates that station and platform annotations are placed at their cumulative corridor
positions rather than unanchored link-local offsets, preventing visual stacking and occlusion
in both FORWARD and REVERSE view orientations across the Infrastructure and Operations tabs.
"""

from typing import Tuple
import gradio as gr
import pytest

from headway.data.canonical import (
    CanonicalProject,
    InfrastructureModel,
    OperationsModel,
    Platform,
    ServicePattern,
    SignallingModel,
    Station,
    StationStop,
    TrackLink,
)
from headway.infrastructure.direction import RunningDirection
from headway.ui.state import session_state
from headway.ui.tab_infrastructure import create_infrastructure_tab
from headway.ui.tab_operations import create_operations_tab


@pytest.fixture(autouse=True)
def clean_session():
    """Ensure clean session state before and after each test."""
    session_state.reset()
    yield
    session_state.reset()


def build_three_station_project() -> CanonicalProject:
    """Build a canonical project with three stations along a 14 km corridor.

    Corridor layout:
      - LNK_01: length 2,000 m (0 to 2,000 m)
        Platform 1 (STN_01, 0.5 km): start 400 m, end 600 m (midpoint = 500 m = 0.5 km)
      - LNK_02: length 6,000 m (2,000 to 8,000 m)
        Platform 2 (STN_02, 5.0 km): start 2,900 m, end 3,100 m (midpoint = 2,000 + 3,000 = 5,000 m = 5.0 km)
      - LNK_03: length 6,000 m (8,000 to 14,000 m)
        Platform 3 (STN_03, 12.0 km): start 3,900 m, end 4,100 m (midpoint = 8,000 + 4,000 = 12,000 m = 12.0 km)
    Total corridor length = 14,000 m.
    """
    links = [
        TrackLink(
            link_id="LNK_01",
            track_id="TRK_01",
            start_node_id="ND_00",
            end_node_id="ND_01",
            length_m=2000.0,
            max_speed_ms=40.0,
            gradient_decimal=0.0,
        ),
        TrackLink(
            link_id="LNK_02",
            track_id="TRK_01",
            start_node_id="ND_01",
            end_node_id="ND_02",
            length_m=6000.0,
            max_speed_ms=40.0,
            gradient_decimal=0.0,
        ),
        TrackLink(
            link_id="LNK_03",
            track_id="TRK_01",
            start_node_id="ND_02",
            end_node_id="ND_03",
            length_m=6000.0,
            max_speed_ms=40.0,
            gradient_decimal=0.0,
        ),
    ]

    stations = [
        Station(station_id="STN_01", name="Alpha Station", chainage_km=0.5),
        Station(station_id="STN_02", name="Beta Station", chainage_km=5.0),
        Station(station_id="STN_03", name="Gamma Station", chainage_km=12.0),
    ]

    platforms = [
        Platform(
            platform_id="PLT_01",
            station_id="STN_01",
            link_id="LNK_01",
            start_offset_m=400.0,
            end_offset_m=600.0,
            length_m=200.0,
        ),
        Platform(
            platform_id="PLT_02",
            station_id="STN_02",
            link_id="LNK_02",
            start_offset_m=2900.0,
            end_offset_m=3100.0,
            length_m=200.0,
        ),
        Platform(
            platform_id="PLT_03",
            station_id="STN_03",
            link_id="LNK_03",
            start_offset_m=3900.0,
            end_offset_m=4100.0,
            length_m=200.0,
        ),
    ]

    return CanonicalProject(
        project_id="PROJ_TEST_POS",
        name="Schematic Position Test Project",
        infrastructure=InfrastructureModel(
            dataset_id="INFRA_01",
            track_links=links,
            stations=stations,
            platforms=platforms,
        ),
        signalling=SignallingModel(dataset_id="SIG_01"),
        operations=OperationsModel(dataset_id="OPS_01"),
    )


def test_stations_at_correct_x_coordinates_forward():
    """Test 1 — Stations at correct x-coordinates (FORWARD).

    Asserts that annotation x-coordinates match the expected cumulative corridor
    positions (500 m, 5,000 m, and 12,000 m) within ±1 m.
    """
    proj = build_three_station_project()
    session_state.current_project = proj

    with gr.Blocks() as demo:
        create_infrastructure_tab()
    update_infra_view = demo.fns[0].fn

    fig_net, *_ = update_infra_view("FORWARD")
    annotations = fig_net.layout.annotations
    assert len(annotations) == 3, f"Expected 3 station annotations, got {len(annotations)}"

    ann_by_stn = {ann.text: ann.x for ann in annotations}

    assert any("Alpha" in k for k in ann_by_stn)
    assert any("Beta" in k for k in ann_by_stn)
    assert any("Gamma" in k for k in ann_by_stn)

    alpha_x = next(v for k, v in ann_by_stn.items() if "Alpha" in k)
    beta_x = next(v for k, v in ann_by_stn.items() if "Beta" in k)
    gamma_x = next(v for k, v in ann_by_stn.items() if "Gamma" in k)

    assert pytest.approx(500.0, abs=1.0) == alpha_x
    assert pytest.approx(5000.0, abs=1.0) == beta_x
    assert pytest.approx(12000.0, abs=1.0) == gamma_x


def test_stations_at_correct_x_coordinates_reverse():
    """Test 2 — Stations at correct x-coordinates (REVERSE).

    Asserts that in REVERSE view, stations appear in reverse order along the x-axis
    and match their mirrored cumulative positions (14,000 - forward_x) within ±1 m:
      - Gamma (formerly 12,000 m): 2,000 m
      - Beta (formerly 5,000 m): 9,000 m
      - Alpha (formerly 500 m): 13,500 m
    """
    proj = build_three_station_project()
    session_state.current_project = proj

    with gr.Blocks() as demo:
        create_infrastructure_tab()
    update_infra_view = demo.fns[0].fn

    fig_net_rev, *_ = update_infra_view("REVERSE")
    annotations = fig_net_rev.layout.annotations
    assert len(annotations) == 3

    ann_by_stn = {ann.text: ann.x for ann in annotations}
    alpha_x = next(v for k, v in ann_by_stn.items() if "Alpha" in k)
    beta_x = next(v for k, v in ann_by_stn.items() if "Beta" in k)
    gamma_x = next(v for k, v in ann_by_stn.items() if "Gamma" in k)

    # Mirrored positions on 14,000 m corridor
    assert pytest.approx(13500.0, abs=1.0) == alpha_x
    assert pytest.approx(9000.0, abs=1.0) == beta_x
    assert pytest.approx(2000.0, abs=1.0) == gamma_x

    # Verify reverse ordering along the x-axis: Gamma (2000 m) < Beta (9000 m) < Alpha (13500 m)
    sorted_by_x = sorted([(ann.text, ann.x) for ann in annotations], key=lambda t: t[1])
    assert "Gamma" in sorted_by_x[0][0]
    assert "Beta" in sorted_by_x[1][0]
    assert "Alpha" in sorted_by_x[2][0]


def test_no_occlusion_after_fix():
    """Test 3 — No occlusion after the fix.

    With widely-spaced stations, assert that all annotation x-coordinates are distinct
    by more than the platform length (200 m), confirming they do not stack or occlude.
    """
    proj = build_three_station_project()
    session_state.current_project = proj

    with gr.Blocks() as demo:
        create_infrastructure_tab()
    update_infra_view = demo.fns[0].fn

    fig_net, *_ = update_infra_view("FORWARD")
    x_coords = sorted(ann.x for ann in fig_net.layout.annotations)

    for i in range(len(x_coords) - 1):
        spacing = x_coords[i + 1] - x_coords[i]
        assert spacing > 200.0, (
            f"Stations at indices {i} and {i + 1} are spaced by only {spacing:.1f} m, "
            f"less than platform length 200 m (potential occlusion)."
        )


def test_fallback_to_chainage_km():
    """Test 4 — Fallback to chainage_km.

    Construct a station with a platform whose link_id is not present in the project's links.
    Ensure the station receives a valid x-coordinate based on chainage_km * 1000 in FORWARD
    and mirrored (cum_dist - chainage_km * 1000) in REVERSE.
    """
    proj = build_three_station_project()
    proj.infrastructure.stations.append(
        Station(station_id="STN_ORPHAN", name="Orphan Station", chainage_km=8.5)
    )
    proj.infrastructure.platforms.append(
        Platform(
            platform_id="PLT_ORPHAN",
            station_id="STN_ORPHAN",
            link_id="LNK_NONEXISTENT",
            start_offset_m=0.0,
            end_offset_m=200.0,
            length_m=200.0,
        )
    )
    session_state.current_project = proj

    with gr.Blocks() as demo:
        create_infrastructure_tab()
    update_infra_view = demo.fns[0].fn

    # FORWARD fallback: 8.5 km * 1000 = 8,500 m
    fig_fwd, *_ = update_infra_view("FORWARD")
    ann_fwd = next(a for a in fig_fwd.layout.annotations if "Orphan" in a.text)
    assert pytest.approx(8500.0, abs=1.0) == ann_fwd.x

    # REVERSE fallback: 14,000 m - 8,500 m = 5,500 m
    fig_rev, *_ = update_infra_view("REVERSE")
    ann_rev = next(a for a in fig_rev.layout.annotations if "Orphan" in a.text)
    assert pytest.approx(5500.0, abs=1.0) == ann_rev.x


def test_tab_operations_equivalent():
    """Test 5 — tab_operations.py equivalent.

    Constructs a project with two service patterns and stop platforms, invokes
    update_operations_view, and asserts the platform x-coordinates are placed at
    their cumulative corridor positions.
    """
    proj = build_three_station_project()
    proj.operations.service_patterns = [
        ServicePattern(
            service_pattern_id="SP_01",
            train_type_id="TRN_01",
            route_link_sequence=["LNK_01", "LNK_02", "LNK_03"],
            stops=[
                StationStop(station_id="STN_01", platform_id="PLT_01", dwell_time_s=60.0),
                StationStop(station_id="STN_02", platform_id="PLT_02", dwell_time_s=60.0),
            ],
        ),
        ServicePattern(
            service_pattern_id="SP_02",
            train_type_id="TRN_01",
            route_link_sequence=["LNK_01", "LNK_02", "LNK_03"],
            stops=[
                StationStop(station_id="STN_02", platform_id="PLT_02", dwell_time_s=45.0),
                StationStop(station_id="STN_03", platform_id="PLT_03", dwell_time_s=90.0),
            ],
        ),
    ]
    session_state.current_project = proj

    with gr.Blocks() as demo_ops:
        create_operations_tab()
    update_ops_view = demo_ops.fns[0].fn

    # Test SP_01 (STN_01 at 500 m, STN_02 at 5,000 m)
    _, _, fig_ops_1, _, _ = update_ops_view("SP_01")
    marker_traces_1 = [t for t in fig_ops_1.data if t.mode and "markers" in t.mode]
    assert len(marker_traces_1) == 2, f"Expected 2 stop markers for SP_01, got {len(marker_traces_1)}"
    sp1_x = [t.x[0] for t in marker_traces_1]
    assert pytest.approx(500.0, abs=1.0) == sp1_x[0]
    assert pytest.approx(5000.0, abs=1.0) == sp1_x[1]

    # Test SP_02 (STN_02 at 5,000 m, STN_03 at 12,000 m)
    _, _, fig_ops_2, _, _ = update_ops_view("SP_02")
    marker_traces_2 = [t for t in fig_ops_2.data if t.mode and "markers" in t.mode]
    assert len(marker_traces_2) == 2, f"Expected 2 stop markers for SP_02, got {len(marker_traces_2)}"
    sp2_x = [t.x[0] for t in marker_traces_2]
    assert pytest.approx(5000.0, abs=1.0) == sp2_x[0]
    assert pytest.approx(12000.0, abs=1.0) == sp2_x[1]
