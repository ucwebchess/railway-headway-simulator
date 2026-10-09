"""Unit tests for centralized unit conversions and Davis coefficient normalization."""

import pytest
from headway.core.exceptions import DataValidationError
from headway.core.units import (
    normalize_acceleration,
    normalize_curve_radius,
    normalize_davis_coefficients,
    normalize_distance,
    normalize_energy,
    normalize_force,
    normalize_gradient,
    normalize_mass,
    normalize_power,
    normalize_speed,
    normalize_time,
)


@pytest.mark.unit
def test_distance_normalization():
    assert normalize_distance(1.5, "km") == 1500.0
    assert normalize_distance(750.0, "m") == 750.0
    with pytest.raises(DataValidationError):
        normalize_distance(10.0, "miles")


@pytest.mark.unit
def test_speed_normalization():
    assert pytest.approx(normalize_speed(36.0, "km/h")) == 10.0
    assert pytest.approx(normalize_speed(144.0, "km/h")) == 40.0
    assert normalize_speed(25.0, "m/s") == 25.0
    with pytest.raises(DataValidationError):
        normalize_speed(50.0, "mph")


@pytest.mark.unit
def test_mass_normalization():
    assert normalize_mass(250.0, "tonnes") == 250000.0
    assert normalize_mass(3500.0, "kg") == 3500.0
    with pytest.raises(DataValidationError):
        normalize_mass(100.0, "lbs")


@pytest.mark.unit
def test_force_normalization():
    assert normalize_force(300.0, "kN") == 300000.0
    assert normalize_force(5000.0, "N") == 5000.0


@pytest.mark.unit
def test_power_and_energy_normalization():
    assert normalize_power(4000.0, "kW") == 4000000.0
    assert normalize_power(500.0, "W") == 500.0
    assert normalize_energy(1.0, "kWh") == 3600000.0


@pytest.mark.unit
def test_time_normalization():
    assert normalize_time(3.0, "min") == 180.0
    assert normalize_time(1.5, "h") == 5400.0
    assert normalize_time(45.0, "s") == 45.0


@pytest.mark.unit
def test_gradient_normalization():
    # 10 permil -> 0.010 m/m
    assert pytest.approx(normalize_gradient(10.0, "‰")) == 0.010
    assert pytest.approx(normalize_gradient(0.015, "decimal")) == 0.015
    assert pytest.approx(normalize_gradient(2.0, "%")) == 0.020


@pytest.mark.unit
def test_curve_radius_normalization():
    assert normalize_curve_radius(600.0, "m") == 600.0
    assert normalize_curve_radius(1.2, "km") == 1200.0


@pytest.mark.unit
def test_davis_coefficient_normalization():
    """Verify mathematical transformation of Davis coefficients from kN and km/h into N and m/s.

    R(V_kmh) = A_kN + B_kN*V_kmh + C_kN*V_kmh^2
    At V = 100 km/h:
    R = 4.0 + 0.05*(100) + 0.001*(10000) = 4.0 + 5.0 + 10.0 = 19.0 kN = 19000 N.

    In SI:
    v = 100 / 3.6 = 27.7778 m/s
    R(v) = A_si + B_si*v + C_si*v^2
    """
    a_kn = 4.0
    b_kn = 0.05
    c_kn = 0.001

    a_si, b_si, c_si = normalize_davis_coefficients(
        a=a_kn,
        b=b_kn,
        c=c_kn,
        force_unit="kN",
        speed_unit="km/h",
    )

    # Mathematical checks:
    # A_si = 4.0 * 1000 = 4000 N
    # B_si = 0.05 * 1000 * 3.6 = 180 N*s/m
    # C_si = 0.001 * 1000 * (3.6^2) = 12.96 N*s^2/m^2
    assert a_si == 4000.0
    assert pytest.approx(b_si) == 180.0
    assert pytest.approx(c_si) == 12.96

    # Verify resistance evaluated at 100 km/h matches exactly 19,000 N
    v_ms = 100.0 / 3.6
    r_si = a_si + b_si * v_ms + c_si * (v_ms ** 2)
    assert pytest.approx(r_si) == 19000.0
