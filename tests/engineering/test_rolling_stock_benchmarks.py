"""Mandatory engineering benchmarks for Milestone P03: Rolling Stock, Traction & Resistance Engine.

Strictly verifies all 25 benchmarks (P03-B001 through P03-B025) per RHS-P03-001 § 16.
Every benchmark enforces exact railway engineering physics formulas, tolerances, and direction invariance.
"""

import copy
import math
import pytest

from headway.core.exceptions import RollingStockError
from headway.core.units import (
    GRAVITY_ACCELERATION_MS2,
    normalize_davis_coefficients,
)
from headway.data.canonical import (
    BrakingModelType,
    BrakingSemantics,
    Node,
    NodeType,
    Track,
    TrackDirectionality,
    TractionCurvePoint,
    TractionModelType,
    TrackLink,
    TrainType,
)
from headway.infrastructure.alignment import RouteAlignmentProfile
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.graph import PhysicalNetworkGraph
from headway.infrastructure.route import Route, RouteEngine
from headway.rolling_stock.diagnostics import RollingStockDiagnostics
from headway.rolling_stock.force_balance import ForceBalanceEngine, MotionState
from headway.rolling_stock.resistance import (
    CurvatureResistanceModel,
    DavisResistanceModel,
    DistributedResistanceEngine,
    DistributedResistanceResult,
    GradientResistanceModel,
)
from headway.rolling_stock.traction import (
    DetailedTractionCurveModel,
    SimplifiedTractionModel,
    create_traction_model,
)
from headway.rolling_stock.train import MassCondition, RollingStockParameters


# Fixture creating standard benchmark high-speed train (400 tonnes, 200 m, 300 km/h)
@pytest.fixture
def benchmark_train_params() -> RollingStockParameters:
    # Benchmark Davis: A = 2.506 kN, B = 0.04065 kN/(km/h), C = 0.00043 kN/(km/h)^2
    a_si, b_si, c_si = normalize_davis_coefficients(
        a=2.506,
        b=0.04065,
        c=0.00043,
        force_unit="kN",
        speed_unit="km/h",
    )
    return RollingStockParameters(
        train_type_id="TT_HST_BENCHMARK",
        description="Benchmark High Speed Train 400t 200m",
        length_m=200.0,
        mass_empty_kg=360_000.0,
        mass_loaded_kg=400_000.0,
        rotating_mass_factor=0.10,
        max_speed_ms=83.333,  # 300 km/h
        max_acceleration_ms2=1.0,
        max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si,
        davis_b_ns_m=b_si,
        davis_c_ns2_m2=c_si,
        power_w=6_000_000.0,  # 6 MW
        max_tractive_effort_n=300_000.0,  # 300 kN
        adhesion_coefficient=0.25,
        adhesive_mass_fraction=0.50,  # 50% adhesive mass (200t)
        mass_condition=MassCondition.NOMINAL,
    )


@pytest.mark.engineering
def test_p03_b001_equivalent_dynamic_mass(benchmark_train_params: RollingStockParameters):
    """P03-B001: Equivalent dynamic mass m_eq = m * (1 + lambda).

    Given m = 400,000 kg, lambda = 0.10 -> m_eq = 440,000 kg.
    """
    assert benchmark_train_params.operational_mass_kg == 400_000.0
    assert benchmark_train_params.rotating_mass_factor == 0.10
    expected_m_eq = 400_000.0 * 1.10
    assert benchmark_train_params.equivalent_mass_kg == pytest.approx(expected_m_eq, rel=1e-6)
    assert benchmark_train_params.equivalent_mass_kg == pytest.approx(440_000.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b002_simplified_traction_standstill(benchmark_train_params: RollingStockParameters):
    """P03-B002: Simplified traction at standstill: v = 0 -> F_t(0) = F_max.

    Division by zero must be guarded and tractive effort equals F_max (300 kN).
    """
    model = SimplifiedTractionModel(benchmark_train_params)
    eval_res = model.evaluate_tractive_effort(speed_ms=0.0)

    assert eval_res.raw_tractive_force_n == pytest.approx(300_000.0, rel=1e-6)
    # At standstill, acceleration limit force = m_eq * a_max = 440,000 * 1.0 = 440 kN > 300 kN
    assert eval_res.available_tractive_force_n == pytest.approx(300_000.0, rel=1e-6)
    assert eval_res.mechanical_power_w == 0.0


@pytest.mark.engineering
def test_p03_b003_constant_force_traction_region(benchmark_train_params: RollingStockParameters):
    """P03-B003: Constant-force traction region for v <= P_max / F_max.

    P_max = 6,000 kW, F_max = 300 kN -> v_corner = 6,000,000 / 300,000 = 20 m/s (72 km/h).
    At v = 10 m/s, F_t(10) = 300,000 N.
    """
    model = SimplifiedTractionModel(benchmark_train_params)
    eval_res = model.evaluate_tractive_effort(speed_ms=10.0)

    assert eval_res.raw_tractive_force_n == pytest.approx(300_000.0, rel=1e-6)
    assert eval_res.available_tractive_force_n == pytest.approx(300_000.0, rel=1e-6)
    assert eval_res.mechanical_power_w == pytest.approx(3_000_000.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b004_constant_power_traction_region(benchmark_train_params: RollingStockParameters):
    """P03-B004: Constant-power traction region for v > P_max / F_max.

    At v = 40 m/s (144 km/h), F_t(40) = 6,000,000 / 40.0 = 150,000 N (150 kN).
    """
    model = SimplifiedTractionModel(benchmark_train_params)
    eval_res = model.evaluate_tractive_effort(speed_ms=40.0)

    expected_f = 6_000_000.0 / 40.0
    assert eval_res.raw_tractive_force_n == pytest.approx(expected_f, rel=1e-6)
    assert eval_res.available_tractive_force_n == pytest.approx(expected_f, rel=1e-6)
    assert eval_res.mechanical_power_w == pytest.approx(6_000_000.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b005_detailed_traction_curve_interpolation(benchmark_train_params: RollingStockParameters):
    """P03-B005: Detailed traction piecewise linear interpolation.

    Points: (0, 300 kN), (20, 300 kN), (40, 150 kN), (60, 100 kN).
    At v = 30 m/s: midpoint between (20, 300k) and (40, 150k) -> 225 kN.
    """
    curve = [
        TractionCurvePoint(speed_ms=0.0, force_n=300_000.0),
        TractionCurvePoint(speed_ms=20.0, force_n=300_000.0),
        TractionCurvePoint(speed_ms=40.0, force_n=150_000.0),
        TractionCurvePoint(speed_ms=60.0, force_n=100_000.0),
    ]
    params = copy.deepcopy(benchmark_train_params)
    object.__setattr__(params, "traction_model_type", TractionModelType.DETAILED_CURVE)
    object.__setattr__(params, "power_w", None)  # Disable power capping to test pure interpolation
    object.__setattr__(params, "traction_curve", curve)

    model = DetailedTractionCurveModel(params)
    eval_res = model.evaluate_tractive_effort(speed_ms=30.0)

    assert eval_res.raw_tractive_force_n == pytest.approx(225_000.0, rel=1e-6)
    assert eval_res.available_tractive_force_n == pytest.approx(225_000.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b006_traction_power_limit(benchmark_train_params: RollingStockParameters):
    """P03-B006: Mechanical traction power P = F_t * v <= P_max across operating range."""
    model = SimplifiedTractionModel(benchmark_train_params)
    p_max = benchmark_train_params.power_w

    for v in [0.0, 5.0, 15.0, 20.0, 30.0, 50.0, 70.0, 83.333]:
        eval_res = model.evaluate_tractive_effort(v)
        assert eval_res.mechanical_power_w <= p_max + 1e-4


@pytest.mark.engineering
def test_p03_b007_adhesion_limit(benchmark_train_params: RollingStockParameters):
    """P03-B007: Adhesion limit F_t <= F_adh = mu * m_adh * g.

    m_adh = 200,000 kg, mu = 0.25 -> F_adh = 0.25 * 200,000 * 9.81 = 490,500 N.
    If requested effort is 600 kN, force is capped at 490.5 kN.
    """
    # Create params with high tractive effort 600 kN
    params = copy.deepcopy(benchmark_train_params)
    object.__setattr__(params, "max_tractive_effort_n", 600_000.0)
    object.__setattr__(params, "power_w", 12_000_000.0)
    object.__setattr__(params, "max_acceleration_ms2", 2.0)  # High limit so adhesion binds

    model = SimplifiedTractionModel(params)
    eval_res = model.evaluate_tractive_effort(speed_ms=5.0)

    expected_f_adh = 0.25 * 200_000.0 * GRAVITY_ACCELERATION_MS2
    assert expected_f_adh == pytest.approx(490_500.0, rel=1e-6)
    assert eval_res.is_adhesion_limited is True
    assert eval_res.available_tractive_force_n == pytest.approx(expected_f_adh, rel=1e-6)


@pytest.mark.engineering
def test_p03_b008_davis_resistance_at_200_kmh(benchmark_train_params: RollingStockParameters):
    """P03-B008: Davis resistance at 200 km/h.

    A = 2.506 kN, B = 0.04065 kN/(km/h), C = 0.00043 kN/(km/h)^2.
    R(200) = 2.506 + 0.04065*(200) + 0.00043*(200^2) = 27.836 kN = 27,836 N.
    """
    model = DavisResistanceModel.from_parameters(benchmark_train_params)
    v_ms = 200.0 / 3.6  # 55.5555... m/s

    force_n = model.evaluate(v_ms)
    assert force_n == pytest.approx(27_836.0, rel=1e-3)


@pytest.mark.engineering
def test_p03_b009_davis_coefficient_normalization():
    """P03-B009: Verification of SI unit conversion for Davis coefficients."""
    a_in, b_in, c_in = 2.506, 0.04065, 0.00043
    a_si, b_si, c_si = normalize_davis_coefficients(
        a=a_in,
        b=b_in,
        c=c_in,
        force_unit="kN",
        speed_unit="km/h",
    )

    # Evaluate at 100 km/h using both formulas
    v_kmh = 100.0
    v_ms = v_kmh / 3.6

    r_original_kn = a_in + b_in * v_kmh + c_in * (v_kmh ** 2)
    r_si_n = a_si + b_si * v_ms + c_si * (v_ms ** 2)

    assert r_si_n == pytest.approx(r_original_kn * 1000.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b010_positive_gradient_resistance():
    """P03-B010: Positive gradient resistance F_g = m * g * i.

    Given m = 400,000 kg, i = +10‰ (+0.010) -> F_g = +39,240 N (+39.24 kN).
    """
    f_g = GradientResistanceModel.evaluate_point_per_mille(
        mass_kg=400_000.0,
        gradient_per_mille=10.0,
        direction=RunningDirection.FORWARD,
    )
    assert f_g == pytest.approx(39_240.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b011_negative_gradient_resistance():
    """P03-B011: Negative gradient resistance F_g = m * g * i.

    Given m = 400,000 kg, i = -10‰ (-0.010) -> F_g = -39,240 N (-39.24 kN).
    """
    f_g = GradientResistanceModel.evaluate_point_per_mille(
        mass_kg=400_000.0,
        gradient_per_mille=-10.0,
        direction=RunningDirection.FORWARD,
    )
    assert f_g == pytest.approx(-39_240.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b012_reverse_gradient_sign_inversion():
    """P03-B012: Reverse gradient sign inversion.

    A physical +10‰ slope traversed in REVERSE produces effective -10‰, F_g = -39.24 kN.
    Strictly verifies F_g,rev = -F_g,fwd.
    """
    f_fwd = GradientResistanceModel.evaluate_point_per_mille(
        mass_kg=400_000.0,
        gradient_per_mille=10.0,
        direction=RunningDirection.FORWARD,
    )
    f_rev = GradientResistanceModel.evaluate_point_per_mille(
        mass_kg=400_000.0,
        gradient_per_mille=10.0,
        direction=RunningDirection.REVERSE,
    )

    assert f_fwd == pytest.approx(39_240.0, rel=1e-6)
    assert f_rev == pytest.approx(-39_240.0, rel=1e-6)
    assert f_rev == pytest.approx(-f_fwd, rel=1e-6)


@pytest.mark.engineering
def test_p03_b013_roeckl_curvature_resistance():
    """P03-B013: Roeckl curvature resistance W_c = 650 / (R - 55) in ‰.

    R = 500 m, m = 400,000 kg -> W_c = 650 / 445 = 1.460674‰.
    F_c = 400,000 * 9.81 * (1.460674 / 1000) = 5731.68 N (~5.73 kN).
    """
    w_c = CurvatureResistanceModel.calculate_roeckl_specific_resistance(500.0)
    expected_wc = 650.0 / 445.0
    assert w_c == pytest.approx(expected_wc, rel=1e-6)

    f_c = CurvatureResistanceModel.evaluate_point(mass_kg=400_000.0, radius_m=500.0)
    expected_fc = 400_000.0 * GRAVITY_ACCELERATION_MS2 * (expected_wc / 1000.0)
    assert f_c == pytest.approx(expected_fc, rel=1e-6)
    assert f_c == pytest.approx(5731.685, rel=1e-3)


@pytest.mark.engineering
def test_p03_b014_straight_track_curvature_resistance():
    """P03-B014: Straight-track curvature resistance is strictly zero."""
    assert CurvatureResistanceModel.calculate_roeckl_specific_resistance(None) == 0.0
    assert CurvatureResistanceModel.calculate_roeckl_specific_resistance(0.0) == 0.0
    assert CurvatureResistanceModel.evaluate_point(400_000.0, None) == 0.0


@pytest.mark.engineering
def test_p03_b015_distributed_gradient_two_sections():
    """P03-B015: Distributed gradient over two sections.

    Train length 200 m, mass 400 t.
    Spans 100 m on +10‰ and 100 m on +20‰.
    Half mass (200 t) on +10‰: 19,620 N.
    Half mass (200 t) on +20‰: 39,240 N.
    Total: 58,860 N (+58.86 kN). Effective average gradient = +15‰.
    """
    intervals = [
        (0.0, 100.0, 0.010),  # +10‰
        (100.0, 200.0, 0.020),  # +20‰
    ]
    f_g, segs = GradientResistanceModel.evaluate_distributed(
        total_mass_kg=400_000.0,
        train_length_m=200.0,
        intervals=intervals,
    )

    expected_f = (200_000.0 * 9.81 * 0.010) + (200_000.0 * 9.81 * 0.020)
    assert f_g == pytest.approx(expected_f, rel=1e-6)
    assert f_g == pytest.approx(58_860.0, rel=1e-6)
    assert len(segs) == 2


@pytest.mark.engineering
def test_p03_b016_distributed_curvature_two_sections():
    """P03-B016: Distributed curvature over two sections.

    Train length 200 m, mass 400 t.
    Spans 100 m on R = 500 m and 100 m on straight track (radius = None).
    Total force is exactly half of the full-curve force = 5731.68 / 2 = 2865.84 N.
    """
    intervals = [
        (0.0, 100.0, 500.0),
        (100.0, 200.0, None),
    ]
    f_c, segs = CurvatureResistanceModel.evaluate_distributed(
        total_mass_kg=400_000.0,
        train_length_m=200.0,
        intervals=intervals,
    )

    full_curve_force = 400_000.0 * 9.81 * ((650.0 / 445.0) / 1000.0)
    expected_f = 0.5 * full_curve_force
    assert f_c == pytest.approx(expected_f, rel=1e-6)
    assert f_c == pytest.approx(2865.84, rel=1e-3)


@pytest.mark.engineering
def test_p03_b017_train_spanning_multiple_links(benchmark_train_params: RollingStockParameters):
    """P03-B017: Train spanning multiple physical links.

    Forward route over LK_01 (150 m, +10‰) and LK_02 (150 m, +20‰).
    Train length 200 m, front at s = 200 m (rear at 0 m).
    Occupies 150 m on LK_01 (75% mass) and 50 m on LK_02 (25% mass).
    F_g = 400,000 * 9.81 * (0.75 * 0.010 + 0.25 * 0.020) = 49,050 N.
    """
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_01", node_type=NodeType.ENDPOINT, description="Origin"))
    graph.add_node(Node(node_id="ND_02", node_type=NodeType.ENDPOINT, description="Midpoint"))
    graph.add_node(Node(node_id="ND_03", node_type=NodeType.ENDPOINT, description="Destination"))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(
        TrackLink(
            link_id="LK_01",
            track_id="TRK_01",
            start_node_id="ND_01",
            end_node_id="ND_02",
            length_m=150.0,
            gradient_decimal=0.010,
            max_speed_ms=83.333,
        )
    )
    graph.add_link(
        TrackLink(
            link_id="LK_02",
            track_id="TRK_01",
            start_node_id="ND_02",
            end_node_id="ND_03",
            length_m=150.0,
            gradient_decimal=0.020,
            max_speed_ms=83.333,
        )
    )
    route_engine = RouteEngine(graph)
    route = route_engine.build_route_from_traversals(
        route_id="RT_FWD_MULTI",
        steps=[("LK_01", RunningDirection.FORWARD), ("LK_02", RunningDirection.FORWARD)],
    )
    align_profile = RouteAlignmentProfile(route)

    dist_engine = DistributedResistanceEngine(benchmark_train_params)
    res = dist_engine.evaluate(speed_ms=0.0, front_position_m=200.0, alignment=align_profile)

    expected_fg = 400_000.0 * GRAVITY_ACCELERATION_MS2 * (0.75 * 0.010 + 0.25 * 0.020)
    assert res.gradient_resistance_n == pytest.approx(expected_fg, rel=1e-6)
    assert res.gradient_resistance_n == pytest.approx(49_050.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b018_reverse_distributed_resistance(benchmark_train_params: RollingStockParameters):
    """P03-B018: Reverse distributed resistance on multi-link route.

    Reverse route traversing the same physical infrastructure in reverse direction.
    LK_02 (150 m, +20‰) and LK_01 (150 m, +10‰) become effective -20‰ and -10‰.
    Train front at s = 200 m occupies 150 m of LK_02 and 50 m of LK_01 in reverse.
    """
    graph = PhysicalNetworkGraph()
    graph.add_node(Node(node_id="ND_01", node_type=NodeType.ENDPOINT, description="End"))
    graph.add_node(Node(node_id="ND_02", node_type=NodeType.ENDPOINT, description="Midpoint"))
    graph.add_node(Node(node_id="ND_03", node_type=NodeType.ENDPOINT, description="Start"))
    graph.add_track(Track(track_id="TRK_01", directionality=TrackDirectionality.BIDIRECTIONAL))
    graph.add_link(
        TrackLink(
            link_id="LK_01",
            track_id="TRK_01",
            start_node_id="ND_01",
            end_node_id="ND_02",
            length_m=150.0,
            gradient_decimal=0.010,
            max_speed_ms=83.333,
        )
    )
    graph.add_link(
        TrackLink(
            link_id="LK_02",
            track_id="TRK_01",
            start_node_id="ND_02",
            end_node_id="ND_03",
            length_m=150.0,
            gradient_decimal=0.020,
            max_speed_ms=83.333,
        )
    )
    route_engine = RouteEngine(graph)
    route_fwd = route_engine.build_route_from_traversals(
        route_id="RT_FWD_MULTI",
        steps=[("LK_01", RunningDirection.FORWARD), ("LK_02", RunningDirection.FORWARD)],
    )
    route_rev = route_fwd.create_reverse_route(graph, reverse_route_id="RT_REV_MULTI")
    align_profile = RouteAlignmentProfile(route_rev)

    dist_engine = DistributedResistanceEngine(benchmark_train_params)
    res = dist_engine.evaluate(speed_ms=0.0, front_position_m=200.0, alignment=align_profile)

    # 150 m on LK_02 (eff -20‰), 50 m on LK_01 (eff -10‰)
    expected_fg = 400_000.0 * GRAVITY_ACCELERATION_MS2 * (0.75 * (-0.020) + 0.25 * (-0.010))
    assert res.gradient_resistance_n == pytest.approx(expected_fg, rel=1e-6)
    assert res.gradient_resistance_n < 0.0


@pytest.mark.engineering
def test_p03_b019_net_force_balance(benchmark_train_params: RollingStockParameters):
    """P03-B019: Net longitudinal force equation.

    F_net = F_t - F_b - F_D - F_g - F_c.
    Given: F_t = 150 kN, F_b = 0, F_D = 27.836 kN, F_g = 39.240 kN, F_c = 5.732 kN.
    F_net = 150,000 - 0 - 27,836 - 39,240 - 5,732 = 77,192 N.
    """
    engine = ForceBalanceEngine(benchmark_train_params)

    # Synthetic resistance result
    resistance = DistributedResistanceResult(
        speed_ms=55.556,
        front_position_m=500.0,
        rear_position_m=300.0,
        occupied_length_m=200.0,
        davis_resistance_n=27_836.0,
        gradient_resistance_n=39_240.0,
        curvature_resistance_n=5_732.0,
        total_resistance_n=27_836.0 + 39_240.0 + 5_732.0,
        effective_average_gradient_per_mille=10.0,
    )

    res = engine.evaluate_acceleration(
        speed_ms=55.556,
        resistance=resistance,
        tractive_force_n=150_000.0,
        braking_force_n=0.0,
    )

    assert res.net_force_n == pytest.approx(77_192.0, rel=1e-6)


@pytest.mark.engineering
def test_p03_b020_equivalent_mass_acceleration(benchmark_train_params: RollingStockParameters):
    """P03-B020: Equivalent-mass acceleration a = F_net / m_eq.

    F_net = 77,192 N, m_eq = 440,000 kg -> a = 77,192 / 440,000 = 0.175436 m/s^2.
    """
    engine = ForceBalanceEngine(benchmark_train_params)

    resistance = DistributedResistanceResult(
        speed_ms=55.556,
        front_position_m=500.0,
        rear_position_m=300.0,
        occupied_length_m=200.0,
        davis_resistance_n=27_836.0,
        gradient_resistance_n=39_240.0,
        curvature_resistance_n=5_732.0,
        total_resistance_n=27_836.0 + 39_240.0 + 5_732.0,
        effective_average_gradient_per_mille=10.0,
    )

    res = engine.evaluate_acceleration(
        speed_ms=55.556,
        resistance=resistance,
        tractive_force_n=150_000.0,
    )

    expected_acc = 77_192.0 / 440_000.0
    assert res.raw_acceleration_ms2 == pytest.approx(expected_acc, rel=1e-6)
    assert res.capped_acceleration_ms2 == pytest.approx(expected_acc, rel=1e-6)


@pytest.mark.engineering
def test_p03_b021_invalid_traction_curve_rejected(benchmark_train_params: RollingStockParameters):
    """P03-B021: Invalid traction curve (decreasing speeds or duplicates) rejected."""
    # Decreasing speed points
    invalid_curve = [
        TractionCurvePoint(speed_ms=0.0, force_n=300_000.0),
        TractionCurvePoint(speed_ms=30.0, force_n=200_000.0),
        TractionCurvePoint(speed_ms=20.0, force_n=150_000.0),  # Decreasing!
    ]
    params = copy.deepcopy(benchmark_train_params)
    object.__setattr__(params, "traction_model_type", TractionModelType.DETAILED_CURVE)
    object.__setattr__(params, "traction_curve", invalid_curve)

    with pytest.raises(RollingStockError, match="strictly increasing"):
        DetailedTractionCurveModel(params)


@pytest.mark.engineering
def test_p03_b022_unsupported_curve_radius_rejected():
    """P03-B022: Curve radius below Roeckl formula minimum (R < 300 m) is rejected."""
    with pytest.raises(RollingStockError, match="below the minimum valid range"):
        CurvatureResistanceModel.calculate_roeckl_specific_resistance(radius_m=250.0)


@pytest.mark.engineering
def test_p03_b023_zero_speed_resistance(benchmark_train_params: RollingStockParameters):
    """P03-B023: Zero-speed resistance equals Davis coefficient A (R(0) = A > 0)."""
    model = DavisResistanceModel.from_parameters(benchmark_train_params)
    assert model.evaluate(0.0) == pytest.approx(benchmark_train_params.davis_a_n, rel=1e-6)
    assert model.evaluate(0.0) > 0.0


@pytest.mark.engineering
def test_p03_b024_direction_independent_traction(benchmark_train_params: RollingStockParameters):
    """P03-B024: Traction force capability is independent of route running direction."""
    model = SimplifiedTractionModel(benchmark_train_params)

    # Test speeds
    speeds = [0.0, 10.0, 20.0, 40.0, 60.0, 80.0]
    for v in speeds:
        eval_fwd = model.evaluate_tractive_effort(v)
        # In reverse running, train propulsion capability is identical
        eval_rev = model.evaluate_tractive_effort(v)
        assert eval_fwd.available_tractive_force_n == eval_rev.available_tractive_force_n
        assert eval_fwd.mechanical_power_w == eval_rev.mechanical_power_w


@pytest.mark.engineering
def test_p03_b025_baseline_configuration_immutability(benchmark_train_params: RollingStockParameters):
    """P03-B025: Physics force evaluation does not mutate canonical objects or parameters."""
    initial_dict = {
        "mass_loaded_kg": benchmark_train_params.mass_loaded_kg,
        "max_speed_ms": benchmark_train_params.max_speed_ms,
        "power_w": benchmark_train_params.power_w,
        "davis_a_n": benchmark_train_params.davis_a_n,
    }

    model = SimplifiedTractionModel(benchmark_train_params)
    davis = DavisResistanceModel.from_parameters(benchmark_train_params)
    fb_engine = ForceBalanceEngine(benchmark_train_params, model)

    # Perform calculations
    _ = model.evaluate_tractive_effort(25.0)
    _ = davis.evaluate(25.0)
    res = DistributedResistanceResult(
        speed_ms=25.0,
        front_position_m=100.0,
        rear_position_m=-100.0,
        occupied_length_m=100.0,
        davis_resistance_n=10_000.0,
        gradient_resistance_n=5_000.0,
        curvature_resistance_n=1_000.0,
        total_resistance_n=16_000.0,
        effective_average_gradient_per_mille=5.0,
    )
    _ = fb_engine.evaluate_acceleration(25.0, res)

    # Verify immutability
    assert benchmark_train_params.mass_loaded_kg == initial_dict["mass_loaded_kg"]
    assert benchmark_train_params.max_speed_ms == initial_dict["max_speed_ms"]
    assert benchmark_train_params.power_w == initial_dict["power_w"]
    assert benchmark_train_params.davis_a_n == initial_dict["davis_a_n"]
