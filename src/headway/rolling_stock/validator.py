"""Rolling stock engineering parameter validation.

Strictly satisfies RHS-P03-001 § 14:
- P03-VAL-001: Structural & physical dimension validations.
- P03-VAL-002: Mass consistency (empty, nominal, max, rotating factor).
- P03-VAL-003: Traction model consistency and curve monotonicity.
- P03-VAL-004: Davis resistance coefficient positivity.
- P03-VAL-005: Adhesion parameter validation.
- P03-VAL-006: Integration with P01 ValidationReport / ValidationFinding.
"""

from typing import List, Optional

from headway.data.canonical import TractionModelType, TrainType
from headway.data.validation import Severity, ValidationFinding, ValidationReport
from headway.rolling_stock.train import RollingStockParameters


class RollingStockValidator:
    """Validates rolling stock parameters against railway engineering rules."""

    def __init__(self) -> None:
        pass

    def validate_canonical_train_type(self, train_type: TrainType) -> ValidationReport:
        """Validate canonical TrainType domain object."""
        report = ValidationReport()

        # Dimension checks
        if train_type.length_m <= 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_LENGTH",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=f"Train length must be positive (got {train_type.length_m} m).",
                )
            )

        # Mass checks
        if train_type.mass_empty_kg <= 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_EMPTY_MASS",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=f"Empty mass must be positive (got {train_type.mass_empty_kg} kg).",
                )
            )
        if train_type.mass_loaded_kg <= 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_LOADED_MASS",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=f"Loaded mass must be positive (got {train_type.mass_loaded_kg} kg).",
                )
            )
        if (
            train_type.mass_empty_kg > 0
            and train_type.mass_loaded_kg > 0
            and train_type.mass_loaded_kg < train_type.mass_empty_kg
        ):
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_MASS_INCONSISTENCY",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=(
                        f"Loaded mass ({train_type.mass_loaded_kg} kg) must be >= "
                        f"empty mass ({train_type.mass_empty_kg} kg)."
                    ),
                )
            )

        if train_type.rotating_mass_factor < 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_ROTATING_MASS",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=(
                        f"Rotating mass factor must be non-negative "
                        f"(got {train_type.rotating_mass_factor}).",
                    ),
                )
            )

        # Kinematic limits
        if train_type.max_speed_ms <= 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_MAX_SPEED",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=f"Max speed must be positive (got {train_type.max_speed_ms} m/s).",
                )
            )
        if train_type.max_acceleration_ms2 <= 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_MAX_ACCEL",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=(
                        f"Max acceleration must be positive "
                        f"(got {train_type.max_acceleration_ms2} m/s^2)."
                    ),
                )
            )

        # Davis coefficients
        if train_type.davis_a_n < 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_DAVIS_A_NEGATIVE",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=f"Davis A coefficient must be non-negative (got {train_type.davis_a_n} N).",
                )
            )
        if train_type.davis_b_ns_m < 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_DAVIS_B_NEGATIVE",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=f"Davis B coefficient must be non-negative (got {train_type.davis_b_ns_m} N*s/m).",
                )
            )
        if train_type.davis_c_ns2_m2 < 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_DAVIS_C_NEGATIVE",
                    severity=Severity.ERROR,
                    object_id=train_type.train_type_id,
                    message=f"Davis C coefficient must be non-negative (got {train_type.davis_c_ns2_m2} N*s^2/m^2).",
                )
            )

        # Traction model specific checks
        if train_type.traction_model_type == TractionModelType.SIMPLIFIED_POWER_FORCE:
            if train_type.power_w is None or train_type.power_w <= 0:
                report.add(
                    ValidationFinding(
                        error_code="ERR_RS_MISSING_POWER",
                        severity=Severity.ERROR,
                        object_id=train_type.train_type_id,
                        message="Simplified traction model requires positive power_w.",
                    )
                )
            if train_type.max_tractive_effort_n is None or train_type.max_tractive_effort_n <= 0:
                report.add(
                    ValidationFinding(
                        error_code="ERR_RS_MISSING_TRACTIVE_EFFORT",
                        severity=Severity.ERROR,
                        object_id=train_type.train_type_id,
                        message="Simplified traction model requires positive max_tractive_effort_n.",
                    )
                )
        elif train_type.traction_model_type == TractionModelType.DETAILED_CURVE:
            if not train_type.traction_curve or len(train_type.traction_curve) < 2:
                report.add(
                    ValidationFinding(
                        error_code="ERR_RS_INSUFFICIENT_CURVE_POINTS",
                        severity=Severity.ERROR,
                        object_id=train_type.train_type_id,
                        message="Curve traction model requires at least 2 traction_curve points.",
                    )
                )
            else:
                prev_speed = -1.0
                for idx, pt in enumerate(train_type.traction_curve):
                    if pt.speed_ms < 0:
                        report.add(
                            ValidationFinding(
                                error_code="ERR_RS_CURVE_NEGATIVE_SPEED",
                                severity=Severity.ERROR,
                                object_id=train_type.train_type_id,
                                message=f"Curve point {idx} has negative speed {pt.speed_ms} m/s.",
                            )
                        )
                    force_val = getattr(pt, "force_n", getattr(pt, "tractive_effort_n", 0.0))
                    if force_val < 0:
                        report.add(
                            ValidationFinding(
                                error_code="ERR_RS_CURVE_NEGATIVE_FORCE",
                                severity=Severity.ERROR,
                                object_id=train_type.train_type_id,
                                message=f"Curve point {idx} has negative tractive effort {force_val} N.",
                            )
                        )
                    if idx > 0 and pt.speed_ms <= prev_speed:
                        report.add(
                            ValidationFinding(
                                error_code="ERR_RS_CURVE_NON_MONOTONIC",
                                severity=Severity.ERROR,
                                object_id=train_type.train_type_id,
                                message=(
                                    f"Curve points must have strictly increasing speeds. "
                                    f"Point {idx} speed {pt.speed_ms} <= previous {prev_speed}."
                                ),
                            )
                        )
                    prev_speed = pt.speed_ms

        return report

    def validate_parameters(self, params: RollingStockParameters) -> ValidationReport:
        """Validate RollingStockParameters instance."""
        report = ValidationReport()

        if params.adhesive_mass_fraction <= 0.0 or params.adhesive_mass_fraction > 1.0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_ADHESIVE_FRACTION",
                    severity=Severity.ERROR,
                    object_id=params.train_type_id,
                    message=f"Adhesive mass fraction must be in (0, 1] (got {params.adhesive_mass_fraction}).",
                )
            )

        if params.adhesion_coefficient is not None and params.adhesion_coefficient <= 0:
            report.add(
                ValidationFinding(
                    error_code="ERR_RS_INVALID_ADHESION_COEFF",
                    severity=Severity.ERROR,
                    object_id=params.train_type_id,
                    message=f"Adhesion coefficient must be positive (got {params.adhesion_coefficient}).",
                )
            )

        return report
