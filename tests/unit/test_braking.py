"""Unit tests for rolling stock braking models and kinematics.

Strictly satisfies RHS-P04-001 § 10 & § 11:
- P04-BRK-001 to P04-BRK-015.
"""

import math
import pytest

from headway.core.exceptions import RollingStockError
from headway.data.canonical import (
    BrakingModelType,
    BrakingSemantics,
    TractionModelType,
)
from headway.rolling_stock.braking import (
    BrakingCategory,
    BrakingEvaluation,
    ConstantDecelerationBrakingModel,
    SpeedDependentBrakingModel,
    create_braking_model,
)
from headway.rolling_stock.train import MassCondition, RollingStockParameters


def test_constant_deceleration_braking_model_basic():
    """Verify constant deceleration evaluation and kinematics."""
    model = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=0.8,
        emergency_deceleration_ms2=1.2,
        semantics=BrakingSemantics.NET_EFFECTIVE,
        response_delay_s=0.5,
        build_up_time_s=1.0,
    )

    # Evaluation
    res_svc = model.evaluate_deceleration(25.0, category=BrakingCategory.OPERATIONAL_SERVICE)
    assert res_svc.effective_deceleration_ms2 == 0.8
    assert res_svc.semantics == BrakingSemantics.NET_EFFECTIVE

    res_emg = model.evaluate_deceleration(25.0, category=BrakingCategory.EMERGENCY)
    assert res_emg.effective_deceleration_ms2 == 1.2

    # Stopping distance without delays
    # v0 = 20 m/s, b = 0.8 => d = 400 / 1.6 = 250 m
    d_no_delay = model.calculate_stopping_distance(20.0, 0.0, include_delays=False)
    assert d_no_delay == pytest.approx(250.0, rel=1e-6)

    # Stopping distance with delays: delay = 0.5s (20*0.5 = 10m), buildup = 1.0s (approx 10m)
    d_with_delay = model.calculate_stopping_distance(20.0, 0.0, include_delays=True)
    assert d_with_delay > d_no_delay
    assert d_with_delay == pytest.approx(268.0, abs=2.0)

    # Stopping time
    t_stop = model.calculate_stopping_time(20.0, 0.0, include_delays=False)
    assert t_stop == pytest.approx(25.0, rel=1e-6)


def test_constant_deceleration_invalid_construction():
    """Verify validation of invalid deceleration rates and delays."""
    with pytest.raises(RollingStockError, match="positive"):
        ConstantDecelerationBrakingModel(service_deceleration_ms2=-0.5, emergency_deceleration_ms2=1.0)

    with pytest.raises(RollingStockError, match="positive"):
        ConstantDecelerationBrakingModel(service_deceleration_ms2=0.8, emergency_deceleration_ms2=0.0)

    with pytest.raises(RollingStockError, match="non-negative"):
        ConstantDecelerationBrakingModel(service_deceleration_ms2=0.8, emergency_deceleration_ms2=1.0, response_delay_s=-0.1)

    with pytest.raises(RollingStockError, match="non-negative"):
        ConstantDecelerationBrakingModel(service_deceleration_ms2=0.8, emergency_deceleration_ms2=1.0, build_up_time_s=-0.5)


def test_speed_dependent_braking_model():
    """Verify speed-dependent braking piecewise curve evaluation and integration."""
    points = [
        (0.0, 0.6),
        (25.0, 0.9),
        (50.0, 1.2),
    ]
    model = SpeedDependentBrakingModel(
        curve_points=points,
        response_delay_s=0.2,
        build_up_time_s=0.4,
    )

    # Test interpolation at midpoint 12.5 m/s
    # b(12.5) = 0.6 + (0.9 - 0.6) * 0.5 = 0.75
    b_mid = model.evaluate_deceleration(12.5, category=BrakingCategory.OPERATIONAL_SERVICE)
    assert b_mid.effective_deceleration_ms2 == pytest.approx(0.75, rel=1e-5)

    # Test extrapolation clamping
    b_above = model.evaluate_deceleration(70.0, category=BrakingCategory.OPERATIONAL_SERVICE)
    assert b_above.effective_deceleration_ms2 == pytest.approx(1.2, rel=1e-5)

    # Test stopping distance from 25 m/s
    d = model.calculate_stopping_distance(25.0, 0.0, include_delays=False)
    # Average b is between 0.6 and 0.9 = 0.75, d approx 25^2 / (2 * 0.75) = 416.7
    assert 300.0 < d < 600.0


def test_speed_dependent_invalid_points():
    """Verify validation of speed-dependent curve points."""
    with pytest.raises(RollingStockError, match="requires at least 2 curve points"):
        SpeedDependentBrakingModel(curve_points=[(0.0, 0.8)])

    with pytest.raises(RollingStockError, match="negative speed"):
        SpeedDependentBrakingModel(curve_points=[(-5.0, 0.8), (20.0, 0.8)])

    with pytest.raises(RollingStockError, match="positive"):
        SpeedDependentBrakingModel(curve_points=[(0.0, 0.0), (20.0, 0.8)])

    with pytest.raises(RollingStockError, match="strictly increasing"):
        SpeedDependentBrakingModel(curve_points=[(20.0, 0.8), (10.0, 0.9)])


def test_create_braking_model_factory():
    """Verify braking model instantiation via factory function."""
    params = RollingStockParameters(
        train_type_id="TT_TEST",
        description="Test",
        length_m=100.0,
        mass_empty_kg=100000.0,
        mass_loaded_kg=120000.0,
        rotating_mass_factor=0.1,
        max_speed_ms=50.0,
        max_acceleration_ms2=1.0,
        max_service_deceleration_ms2=0.7,
        emergency_deceleration_ms2=1.1,
        traction_model_type=TractionModelType.SIMPLIFIED_POWER_FORCE,
        davis_a_n=1000.0,
        davis_b_ns_m=20.0,
        davis_c_ns2_m2=0.5,
        power_w=3000000.0,
        max_tractive_effort_n=200000.0,
    )
    model = create_braking_model(
        params,
        semantics=BrakingSemantics.NET_EFFECTIVE,
        response_delay_s=0.4,
        build_up_time_s=0.8,
    )
    assert isinstance(model, ConstantDecelerationBrakingModel)
    assert model.service_deceleration_ms2 == 0.7
    assert model.emergency_deceleration_ms2 == 1.1
    assert model.response_delay_s == 0.4
    assert model.build_up_time_s == 0.8
