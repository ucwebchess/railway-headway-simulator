"""Centralized engineering unit conversions and normalization for Railway Headway Simulator.

Strictly enforces internal SI units per RHS-MASTER-001 § 5 and RHS-P01-001 § 5.
Never mixes units without explicit, centralized conversion.
"""

from typing import Any, Dict, Optional, Tuple
from headway.core.exceptions import DataValidationError


# Conversion constants
KM_TO_M = 1000.0
M_TO_KM = 0.001

KMH_TO_MS = 1.0 / 3.6
MS_TO_KMH = 3.6

TONNES_TO_KG = 1000.0
KG_TO_TONNES = 0.001

KN_TO_N = 1000.0
N_TO_KN = 0.001

KW_TO_W = 1000.0
W_TO_KW = 0.001

KWH_TO_J = 3.6e6
J_TO_KWH = 1.0 / 3.6e6

MIN_TO_S = 60.0
HOUR_TO_S = 3600.0

PERMIL_TO_DECIMAL = 0.001
DECIMAL_TO_PERMIL = 1000.0

STANDARD_GRAVITY_MS2 = 9.81
GRAVITY_ACCELERATION_MS2 = 9.81


def normalize_distance(value: float, unit: str) -> float:
    """Normalize distance to meters (m)."""
    u = unit.strip().lower()
    if u in {"m", "meter", "meters"}:
        return float(value)
    if u in {"km", "kilometer", "kilometres"}:
        return float(value) * KM_TO_M
    raise DataValidationError(
        f"Unsupported distance unit '{unit}'. Supported units: 'm', 'km'.",
        error_code="ERR_UNIT_DISTANCE",
        context={"unit": unit, "value": value},
    )


def normalize_speed(value: float, unit: str) -> float:
    """Normalize speed/velocity to meters per second (m/s)."""
    u = unit.strip().lower()
    if u in {"m/s", "ms", "mps"}:
        return float(value)
    if u in {"km/h", "kmh", "kph"}:
        return float(value) * KMH_TO_MS
    raise DataValidationError(
        f"Unsupported speed unit '{unit}'. Supported units: 'km/h', 'm/s'.",
        error_code="ERR_UNIT_SPEED",
        context={"unit": unit, "value": value},
    )


def normalize_mass(value: float, unit: str) -> float:
    """Normalize mass to kilograms (kg)."""
    u = unit.strip().lower()
    if u in {"kg", "kilogram", "kilograms"}:
        return float(value)
    if u in {"t", "tonne", "tonnes", "tons"}:
        return float(value) * TONNES_TO_KG
    raise DataValidationError(
        f"Unsupported mass unit '{unit}'. Supported units: 'tonnes', 'kg'.",
        error_code="ERR_UNIT_MASS",
        context={"unit": unit, "value": value},
    )


def normalize_force(value: float, unit: str) -> float:
    """Normalize force to Newtons (N)."""
    u = unit.strip().lower()
    if u in {"n", "newton", "newtons"}:
        return float(value)
    if u in {"kn", "kilonewton", "kilonewtons"}:
        return float(value) * KN_TO_N
    raise DataValidationError(
        f"Unsupported force unit '{unit}'. Supported units: 'kN', 'N'.",
        error_code="ERR_UNIT_FORCE",
        context={"unit": unit, "value": value},
    )


def normalize_power(value: float, unit: str) -> float:
    """Normalize power to Watts (W)."""
    u = unit.strip().lower()
    if u in {"w", "watt", "watts"}:
        return float(value)
    if u in {"kw", "kilowatt", "kilowatts"}:
        return float(value) * KW_TO_W
    raise DataValidationError(
        f"Unsupported power unit '{unit}'. Supported units: 'kW', 'W'.",
        error_code="ERR_UNIT_POWER",
        context={"unit": unit, "value": value},
    )


def normalize_energy(value: float, unit: str) -> float:
    """Normalize energy to Joules (J)."""
    u = unit.strip().lower()
    if u in {"j", "joule", "joules"}:
        return float(value)
    if u in {"kwh", "kilowatt-hour", "kilowatt-hours"}:
        return float(value) * KWH_TO_J
    raise DataValidationError(
        f"Unsupported energy unit '{unit}'. Supported units: 'kWh', 'J'.",
        error_code="ERR_UNIT_ENERGY",
        context={"unit": unit, "value": value},
    )


def normalize_time(value: float, unit: str) -> float:
    """Normalize time duration to seconds (s)."""
    u = unit.strip().lower()
    if u in {"s", "sec", "second", "seconds"}:
        return float(value)
    if u in {"min", "minute", "minutes"}:
        return float(value) * MIN_TO_S
    if u in {"h", "hr", "hour", "hours"}:
        return float(value) * HOUR_TO_S
    raise DataValidationError(
        f"Unsupported time unit '{unit}'. Supported units: 's', 'min', 'h'.",
        error_code="ERR_UNIT_TIME",
        context={"unit": unit, "value": value},
    )


def normalize_acceleration(value: float, unit: str) -> float:
    """Normalize acceleration/deceleration to m/s²."""
    u = unit.strip().lower()
    if u in {"m/s²", "m/s2", "m/s^2", "ms-2"}:
        return float(value)
    raise DataValidationError(
        f"Unsupported acceleration unit '{unit}'. Supported unit: 'm/s²'.",
        error_code="ERR_UNIT_ACCEL",
        context={"unit": unit, "value": value},
    )


def normalize_gradient(value: float, unit: str) -> float:
    """Normalize track gradient to dimensionless decimal (m/m).

    Example: 10‰ (10 permil) -> 0.010 m/m.
    """
    u = unit.strip().lower()
    if u in {"‰", "permil", "permille", "o/oo", "promille"}:
        return float(value) * PERMIL_TO_DECIMAL
    if u in {"decimal", "dimensionless", "m/m", ""}:
        return float(value)
    if u in {"%", "percent"}:
        return float(value) * 0.01
    raise DataValidationError(
        f"Unsupported gradient unit '{unit}'. Supported units: '‰', 'decimal', '%'.",
        error_code="ERR_UNIT_GRADIENT",
        context={"unit": unit, "value": value},
    )


def normalize_curve_radius(value: float, unit: str) -> float:
    """Normalize curve radius to meters (m)."""
    u = unit.strip().lower()
    if u in {"m", "meter", "meters"}:
        return float(value)
    if u in {"km", "kilometer"}:
        return float(value) * KM_TO_M
    raise DataValidationError(
        f"Unsupported curve radius unit '{unit}'. Supported units: 'm', 'km'.",
        error_code="ERR_UNIT_CURVE",
        context={"unit": unit, "value": value},
    )


def normalize_davis_coefficients(
    a: float,
    b: float,
    c: float,
    force_unit: str = "N",
    speed_unit: str = "m/s",
) -> Tuple[float, float, float]:
    """Normalize Davis resistance equation coefficients to SI units:

        R(v) = A + B*v + C*v^2
        Canonical units: R in Newtons (N), v in meters/second (m/s).

    Args:
        a: Constant rolling resistance coefficient.
        b: Linear mechanical/flange resistance coefficient.
        c: Quadratic aerodynamic drag coefficient.
        force_unit: Declared resistance unit (e.g. 'N', 'kN').
        speed_unit: Declared speed unit (e.g. 'm/s', 'km/h').

    Returns:
        Tuple of (A_si, B_si, C_si) normalized to N, N*s/m, N*s^2/m^2.
    """
    fu = force_unit.strip().lower()
    if fu in {"n", "newton", "newtons"}:
        k_force = 1.0
    elif fu in {"kn", "kilonewton", "kilonewtons"}:
        k_force = KN_TO_N
    else:
        raise DataValidationError(
            f"Unsupported Davis force unit '{force_unit}'. Supported: 'N', 'kN'.",
            error_code="ERR_UNIT_DAVIS_FORCE",
            context={"force_unit": force_unit},
        )

    su = speed_unit.strip().lower()
    if su in {"m/s", "ms", "mps"}:
        k_speed = 1.0  # V_input = 1.0 * v_ms
    elif su in {"km/h", "kmh", "kph"}:
        k_speed = 3.6  # V_input = 3.6 * v_ms
    else:
        raise DataValidationError(
            f"Unsupported Davis speed unit '{speed_unit}'. Supported: 'm/s', 'km/h'.",
            error_code="ERR_UNIT_DAVIS_SPEED",
            context={"speed_unit": speed_unit},
        )

    a_si = float(a) * k_force
    b_si = float(b) * k_force * k_speed
    c_si = float(c) * k_force * (k_speed ** 2)

    return a_si, b_si, c_si
