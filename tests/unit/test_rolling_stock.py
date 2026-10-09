"""Comprehensive unit tests for rolling stock physics engine (Milestone P03).

Covers all modules:
- train.py: RollingStockParameters, MassCondition, TrainFormation
- traction.py: SimplifiedTractionModel, DetailedTractionCurveModel, create_traction_model
- resistance.py: DavisResistanceModel, GradientResistanceModel, CurvatureResistanceModel, DistributedResistanceEngine
- force_balance.py: ForceBalanceEngine, MotionState, acceleration capping, target deceleration
- diagnostics.py: RollingStockDiagnostics, balancing speed, performance sweeps
- validator.py: RollingStockValidator
"""

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
    TrackLink,
    TractionCurvePoint,
    TractionModelType,
    TrainType,
)
from headway.data.validation import Severity
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
from headway.rolling_stock.train import (
    MassCondition,
    RollingStockParameters,
    TrainFormation,
)
from headway.rolling_stock.validator import RollingStockValidator


# ==============================================================================
# Train and Mass Parameters Tests
# ==============================================================================

@pytest.mark.unit
def test_rolling_stock_parameters_validation():
    """Verify parameter validations in RollingStockParameters."""
    a_si, b_si, c_si = normalize_davis_coefficients(2.5, 0.04, 0.0004, force_unit="kN", speed_unit="km/h")

    # Negative length
    with pytest.raises(RollingStockError, match="length must be positive"):
        RollingStockParameters(
            train_type_id="TT_01", description="Test", length_m=-10.0,
            mass_empty_kg=100_000, mass_loaded_kg=120_000, rotating_mass_factor=0.1,
            max_speed_ms=40.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
            emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
            davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        )

    # Empty mass non-positive
    with pytest.raises(RollingStockError, match="Empty mass must be positive"):
        RollingStockParameters(
            train_type_id="TT_01", description="Test", length_m=100.0,
            mass_empty_kg=0, mass_loaded_kg=120_000, rotating_mass_factor=0.1,
            max_speed_ms=40.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
            emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
            davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        )

    # Loaded mass < empty mass
    with pytest.raises(RollingStockError, match="Loaded mass .* cannot be less than empty mass"):
        RollingStockParameters(
            train_type_id="TT_01", description="Test", length_m=100.0,
            mass_empty_kg=120_000, mass_loaded_kg=100_000, rotating_mass_factor=0.1,
            max_speed_ms=40.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
            emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
            davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        )

    # Negative rotating mass factor
    with pytest.raises(RollingStockError, match="Rotating mass factor must be non-negative"):
        RollingStockParameters(
            train_type_id="TT_01", description="Test", length_m=100.0,
            mass_empty_kg=100_000, mass_loaded_kg=120_000, rotating_mass_factor=-0.05,
            max_speed_ms=40.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
            emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
            davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        )

    # Invalid adhesive fraction
    with pytest.raises(RollingStockError, match="Adhesive mass fraction must be in"):
        RollingStockParameters(
            train_type_id="TT_01", description="Test", length_m=100.0,
            mass_empty_kg=100_000, mass_loaded_kg=120_000, rotating_mass_factor=0.1,
            max_speed_ms=40.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
            emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
            davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
            adhesive_mass_fraction=1.5,
        )


@pytest.mark.unit
def test_mass_conditions_and_formation():
    """Verify mass condition switches and train consist aggregation."""
    a_si, b_si, c_si = normalize_davis_coefficients(2.0, 0.03, 0.0003, force_unit="kN", speed_unit="km/h")
    p1 = RollingStockParameters(
        train_type_id="TT_UNIT_A", description="Unit A", length_m=100.0,
        mass_empty_kg=100_000.0, mass_loaded_kg=150_000.0, rotating_mass_factor=0.10,
        max_speed_ms=50.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        adhesive_mass_fraction=0.6,
        mass_condition=MassCondition.EMPTY,
    )
    assert p1.operational_mass_kg == 100_000.0
    assert p1.adhesive_mass_kg == 60_000.0
    assert p1.equivalent_mass_kg == pytest.approx(110_000.0)

    p2 = RollingStockParameters(
        train_type_id="TT_UNIT_B", description="Unit B", length_m=150.0,
        mass_empty_kg=150_000.0, mass_loaded_kg=200_000.0, rotating_mass_factor=0.10,
        max_speed_ms=45.0, max_acceleration_ms2=0.9, max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        mass_condition=MassCondition.NOMINAL,
    )
    assert p2.operational_mass_kg == 200_000.0
    assert p2.equivalent_mass_kg == pytest.approx(220_000.0)

    # Formation aggregation
    formation = TrainFormation(formation_id="FORM_01", units=[p1, p2])
    assert formation.total_length_m == 250.0
    assert formation.total_operational_mass_kg == 300_000.0
    assert formation.total_equivalent_mass_kg == pytest.approx(330_000.0)
    assert formation.max_speed_ms == 45.0  # Governed by lower unit limit


# ==============================================================================
# Traction Models Tests
# ==============================================================================

@pytest.mark.unit
def test_simplified_traction_model_edge_cases():
    """Verify validation and edge cases of SimplifiedTractionModel."""
    a_si, b_si, c_si = normalize_davis_coefficients(2.0, 0.03, 0.0003, force_unit="kN", speed_unit="km/h")
    params = RollingStockParameters(
        train_type_id="TT_01", description="Test", length_m=100.0,
        mass_empty_kg=100_000.0, mass_loaded_kg=150_000.0, rotating_mass_factor=0.10,
        max_speed_ms=50.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        power_w=3_000_000.0, max_tractive_effort_n=200_000.0,
    )

    # Negative efficiency error
    with pytest.raises(RollingStockError, match="efficiency must be in"):
        SimplifiedTractionModel(params, efficiency=0.0)

    model = SimplifiedTractionModel(params, efficiency=0.90)

    # Negative speed error
    with pytest.raises(RollingStockError, match="non-negative speed"):
        model.evaluate_tractive_effort(-1.0)

    # Standstill evaluation with efficiency 90%: 200 kN * 0.9 = 180 kN
    res = model.evaluate_tractive_effort(0.0)
    assert res.raw_tractive_force_n == pytest.approx(180_000.0)


@pytest.mark.unit
def test_detailed_traction_curve_model():
    """Verify DetailedTractionCurveModel interpolation, bounds, and validations."""
    a_si, b_si, c_si = normalize_davis_coefficients(2.0, 0.03, 0.0003, force_unit="kN", speed_unit="km/h")

    # Insufficient points error (< 2 points)
    curve_single = [TractionCurvePoint(speed_ms=0.0, force_n=200_000.0)]
    p_err = RollingStockParameters(
        train_type_id="TT_01", description="Test", length_m=100.0,
        mass_empty_kg=100_000.0, mass_loaded_kg=150_000.0, rotating_mass_factor=0.10,
        max_speed_ms=50.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.DETAILED_CURVE,
        davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        traction_curve=curve_single,
    )
    with pytest.raises(RollingStockError, match="at least two points"):
        DetailedTractionCurveModel(p_err)

    curve_valid = [
        TractionCurvePoint(speed_ms=0.0, force_n=250_000.0),
        TractionCurvePoint(speed_ms=10.0, force_n=250_000.0),
        TractionCurvePoint(speed_ms=30.0, force_n=150_000.0),
        TractionCurvePoint(speed_ms=50.0, force_n=80_000.0),
    ]
    p_valid = RollingStockParameters(
        train_type_id="TT_01", description="Test", length_m=100.0,
        mass_empty_kg=100_000.0, mass_loaded_kg=150_000.0, rotating_mass_factor=0.10,
        max_speed_ms=50.0, max_acceleration_ms2=2.0, max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.DETAILED_CURVE,
        davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        traction_curve=curve_valid,
    )
    model = DetailedTractionCurveModel(p_valid)

    # Standstill (0 m/s): 250 kN
    assert model.evaluate_tractive_effort(0.0).available_tractive_force_n == pytest.approx(250_000.0)

    # Interpolation at 20 m/s: halfway between (10, 250k) and (30, 150k) -> 200 kN
    assert model.evaluate_tractive_effort(20.0).available_tractive_force_n == pytest.approx(200_000.0)

    # Beyond upper curve bound (60 m/s > 50 m/s): clamps to 0 N
    assert model.evaluate_tractive_effort(60.0).available_tractive_force_n == 0.0


# ==============================================================================
# Resistance Models Tests
# ==============================================================================

@pytest.mark.unit
def test_davis_resistance_model_validations():
    """Verify DavisResistanceModel validations."""
    with pytest.raises(RollingStockError, match="Davis coefficient A must be non-negative"):
        DavisResistanceModel(a_n=-1.0, b_ns_m=10.0, c_ns2_m2=1.0)
    with pytest.raises(RollingStockError, match="Davis coefficient B must be non-negative"):
        DavisResistanceModel(a_n=1000.0, b_ns_m=-1.0, c_ns2_m2=1.0)
    with pytest.raises(RollingStockError, match="Davis coefficient C must be non-negative"):
        DavisResistanceModel(a_n=1000.0, b_ns_m=10.0, c_ns2_m2=-0.5)

    model = DavisResistanceModel(a_n=2000.0, b_ns_m=50.0, c_ns2_m2=3.0)
    with pytest.raises(RollingStockError, match="Speed must be non-negative"):
        model.evaluate(-5.0)

    assert model.evaluate(0.0) == 2000.0
    assert model.evaluate(10.0) == pytest.approx(2000.0 + 50.0 * 10.0 + 3.0 * 100.0)


@pytest.mark.unit
def test_curvature_resistance_model():
    """Verify CurvatureResistanceModel handling of straight track and invalid radii."""
    # Tangent / straight track
    assert CurvatureResistanceModel.calculate_roeckl_specific_resistance(None) == 0.0
    assert CurvatureResistanceModel.calculate_roeckl_specific_resistance(0.0) == 0.0
    assert CurvatureResistanceModel.calculate_roeckl_specific_resistance(-500.0) == 0.0
    assert CurvatureResistanceModel.calculate_roeckl_specific_resistance(1e10) == 0.0

    # Curve below 300 m minimum validity
    with pytest.raises(RollingStockError, match="below the minimum valid range"):
        CurvatureResistanceModel.calculate_roeckl_specific_resistance(299.0)

    # Valid curve R = 1000 m
    # W_c = 650 / (1000 - 55) = 650 / 945 = 0.68783‰
    w_c = CurvatureResistanceModel.calculate_roeckl_specific_resistance(1000.0)
    assert w_c == pytest.approx(650.0 / 945.0, rel=1e-6)

    # Force for 200 t mass: 200,000 * 9.81 * (0.68783 / 1000) = 1349.52 N
    fc = CurvatureResistanceModel.evaluate_point(200_000.0, 1000.0)
    assert fc == pytest.approx(200_000.0 * GRAVITY_ACCELERATION_MS2 * (w_c / 1000.0), rel=1e-6)


# ==============================================================================
# Force Balance & Acceleration Tests
# ==============================================================================

@pytest.mark.unit
def test_force_balance_coasting_and_braking():
    """Verify coasting and braking force calculations."""
    a_si, b_si, c_si = normalize_davis_coefficients(2.0, 0.03, 0.0003, force_unit="kN", speed_unit="km/h")
    params = RollingStockParameters(
        train_type_id="TT_01", description="Test", length_m=100.0,
        mass_empty_kg=100_000.0, mass_loaded_kg=200_000.0, rotating_mass_factor=0.10,
        max_speed_ms=50.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        power_w=3_000_000.0, max_tractive_effort_n=200_000.0,
    )
    engine = ForceBalanceEngine(params)

    # 1. Coasting on flat track
    res_flat = DistributedResistanceResult(
        speed_ms=20.0, front_position_m=500.0, rear_position_m=400.0, occupied_length_m=100.0,
        davis_resistance_n=10_000.0, gradient_resistance_n=0.0, curvature_resistance_n=0.0,
        total_resistance_n=10_000.0, effective_average_gradient_per_mille=0.0,
    )
    coast_res = engine.evaluate_acceleration(20.0, res_flat, is_coasting=True)
    assert coast_res.motion_state == MotionState.COASTING
    assert coast_res.tractive_force_n == 0.0
    assert coast_res.braking_force_n == 0.0
    assert coast_res.net_force_n == -10_000.0
    assert coast_res.capped_acceleration_ms2 == pytest.approx(-10_000.0 / (200_000.0 * 1.10))

    # 2. Target service deceleration 0.5 m/s^2
    brake_res = engine.evaluate_acceleration(20.0, res_flat, target_deceleration_ms2=0.5)
    assert brake_res.motion_state == MotionState.BRAKING
    # F_b = m_eq * 0.5 - F_res = 220,000 * 0.5 - 10,000 = 100,000 N
    assert brake_res.braking_force_n == pytest.approx(100_000.0)
    assert brake_res.capped_acceleration_ms2 == pytest.approx(-0.5)


# ==============================================================================
# Diagnostics Tests
# ==============================================================================

@pytest.mark.unit
def test_rolling_stock_diagnostics_sweep_and_balancing_speed():
    """Verify performance sweeps and balancing speed solver in RollingStockDiagnostics."""
    a_si, b_si, c_si = normalize_davis_coefficients(2.0, 0.03, 0.0003, force_unit="kN", speed_unit="km/h")
    params = RollingStockParameters(
        train_type_id="TT_01", description="Test", length_m=100.0,
        mass_empty_kg=100_000.0, mass_loaded_kg=200_000.0, rotating_mass_factor=0.10,
        max_speed_ms=50.0, max_acceleration_ms2=1.0, max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2, traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=a_si, davis_b_ns_m=b_si, davis_c_ns2_m2=c_si,
        power_w=2_000_000.0, max_tractive_effort_n=150_000.0,
    )
    diag = RollingStockDiagnostics(params)

    # Performance sweep
    sweep = diag.evaluate_performance_sweep(step_kmh=20.0)
    assert len(sweep) > 2
    assert sweep[0].speed_kmh == 0.0
    assert sweep[-1].speed_ms == pytest.approx(50.0, rel=1e-3)

    records = diag.to_records(sweep)
    assert len(records) == len(sweep)
    assert "tractive_force_kn" in records[0]

    # Balancing speed on steep +50‰ uphill
    # At +50‰: F_g = 200,000 * 9.81 * 0.050 = 98.1 kN
    # Standstill tractive effort = 150 kN > 98.1 kN -> can move
    # High speed traction F_t(v) drops as 2MW / v -> will balance below 50 m/s
    v_bal = diag.find_balancing_speed_ms(gradient_per_mille=50.0)
    assert v_bal is not None
    assert 0.0 < v_bal < 50.0


# ==============================================================================
# RollingStockValidator Tests
# ==============================================================================

@pytest.mark.unit
def test_rolling_stock_validator():
    """Verify error detection in canonical train types and parameters."""
    validator = RollingStockValidator()

    tt_bad = TrainType.model_construct(
        train_type_id="TT_INVALID",
        description="Invalid train",
        length_m=-50.0,
        mass_empty_kg=200_000.0,
        mass_loaded_kg=150_000.0,  # Loaded < Empty
        rotating_mass_factor=-0.1,
        max_speed_ms=-10.0,
        max_acceleration_ms2=-1.0,
        max_service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=-5.0,
        davis_b_ns_m=10.0,
        davis_c_ns2_m2=1.0,
        power_w=None,  # Missing required power for simplified
        max_tractive_effort_n=None,  # Missing tractive effort
        braking_model_type=BrakingModelType.CONSTANT_DECELERATION,
        braking_semantics=BrakingSemantics.NET_EFFECTIVE,
    )

    report = validator.validate_canonical_train_type(tt_bad)
    assert report.has_errors
    assert not report.is_simulation_ready
    error_codes = [f.error_code for f in report.findings]

    assert "ERR_RS_INVALID_LENGTH" in error_codes
    assert "ERR_RS_MASS_INCONSISTENCY" in error_codes
    assert "ERR_RS_INVALID_ROTATING_MASS" in error_codes
    assert "ERR_RS_INVALID_MAX_SPEED" in error_codes
    assert "ERR_RS_DAVIS_A_NEGATIVE" in error_codes
    assert "ERR_RS_MISSING_POWER" in error_codes
    assert "ERR_RS_MISSING_TRACTIVE_EFFORT" in error_codes
