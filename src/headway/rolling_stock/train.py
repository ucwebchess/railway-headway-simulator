"""Rolling stock physical parameters, mass conditions, and train formation models.

Strictly satisfies RHS-P03-001 § 3 & § 4:
- P03-RS-001: Multiple rolling stock types support with canonical identifiers.
- P03-RS-002: Physical dimensions, mass, max speed, acceleration, rotating mass factor.
- P03-RS-003: Operational mass conditions (empty, nominal, maximum).
- P03-RS-004: Train formation support (length, mass, performance aggregation).
- P03-MASS-001: Equivalent dynamic mass: m_eq = m * (1 + lambda).
- P03-MASS-002: Physical mass for gravity/normal forces; equivalent mass for acceleration.
- P03-MASS-003: Strict validation: m > 0, lambda >= 0.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from headway.core.exceptions import RollingStockError
from headway.data.canonical import (
    BrakingModelType,
    BrakingSemantics,
    TractionCurvePoint,
    TractionModelType,
    TrainType,
)


class MassCondition(str, Enum):
    """Operational mass state of the train."""

    EMPTY = "EMPTY"        # Tare mass (no passengers / freight)
    NOMINAL = "NOMINAL"    # Standard design operating load (nominal payload)
    MAXIMUM = "MAXIMUM"    # Crush load / maximum gross design weight


@dataclass(frozen=True)
class RollingStockParameters:
    """Validated physical parameters for an individual train type or formation."""

    train_type_id: str
    description: str
    length_m: float
    mass_empty_kg: float
    mass_loaded_kg: float
    rotating_mass_factor: float
    max_speed_ms: float
    max_acceleration_ms2: float
    max_service_deceleration_ms2: float
    emergency_deceleration_ms2: float
    traction_model_type: TractionModelType
    davis_a_n: float
    davis_b_ns_m: float
    davis_c_ns2_m2: float
    power_w: Optional[float] = None
    max_tractive_effort_n: Optional[float] = None
    traction_curve: Optional[List[TractionCurvePoint]] = None
    adhesion_coefficient: Optional[float] = None
    adhesive_mass_fraction: float = 1.0  # Fraction of mass on driven axles (0 < fraction <= 1)
    mass_condition: MassCondition = MassCondition.NOMINAL

    def __post_init__(self) -> None:
        """P03-MASS-003 & P03-RS-002: Invariant validations."""
        if self.length_m <= 0:
            raise RollingStockError(
                f"Train length must be positive (got {self.length_m} m).",
                context={"train_type_id": self.train_type_id},
            )
        if self.mass_empty_kg <= 0:
            raise RollingStockError(
                f"Empty mass must be positive (got {self.mass_empty_kg} kg).",
                context={"train_type_id": self.train_type_id},
            )
        if self.mass_loaded_kg <= 0:
            raise RollingStockError(
                f"Loaded mass must be positive (got {self.mass_loaded_kg} kg).",
                context={"train_type_id": self.train_type_id},
            )
        if self.mass_loaded_kg < self.mass_empty_kg:
            raise RollingStockError(
                f"Loaded mass ({self.mass_loaded_kg} kg) cannot be less than empty mass ({self.mass_empty_kg} kg).",
                context={"train_type_id": self.train_type_id},
            )
        if self.rotating_mass_factor < 0:
            raise RollingStockError(
                f"Rotating mass factor must be non-negative (got {self.rotating_mass_factor}).",
                context={"train_type_id": self.train_type_id},
            )
        if self.max_speed_ms <= 0:
            raise RollingStockError(
                f"Maximum speed must be positive (got {self.max_speed_ms} m/s).",
                context={"train_type_id": self.train_type_id},
            )
        if self.max_acceleration_ms2 <= 0:
            raise RollingStockError(
                f"Maximum acceleration must be positive (got {self.max_acceleration_ms2} m/s^2).",
                context={"train_type_id": self.train_type_id},
            )
        if not (0.0 < self.adhesive_mass_fraction <= 1.0):
            raise RollingStockError(
                f"Adhesive mass fraction must be in (0, 1] (got {self.adhesive_mass_fraction}).",
                context={"train_type_id": self.train_type_id},
            )

    @property
    def operational_mass_kg(self) -> float:
        """P03-RS-003: Physical mass corresponding to the active mass condition."""
        if self.mass_condition == MassCondition.EMPTY:
            return self.mass_empty_kg
        elif self.mass_condition == MassCondition.MAXIMUM:
            return self.mass_loaded_kg
        else:  # NOMINAL
            return self.mass_loaded_kg

    @property
    def adhesive_mass_kg(self) -> float:
        """P03-ADH-002: Mass supported by powered axles."""
        return self.operational_mass_kg * self.adhesive_mass_fraction

    @property
    def equivalent_mass_kg(self) -> float:
        """P03-MASS-001 & P03-B001: Equivalent dynamic mass m_eq = m * (1 + lambda)."""
        return self.operational_mass_kg * (1.0 + self.rotating_mass_factor)

    @classmethod
    def from_canonical(
        cls,
        train_type: TrainType,
        mass_condition: MassCondition = MassCondition.NOMINAL,
        adhesion_coefficient: Optional[float] = None,
        adhesive_mass_fraction: float = 1.0,
    ) -> "RollingStockParameters":
        """Factory creating RollingStockParameters from canonical TrainType."""
        return cls(
            train_type_id=train_type.train_type_id,
            description=train_type.description,
            length_m=train_type.length_m,
            mass_empty_kg=train_type.mass_empty_kg,
            mass_loaded_kg=train_type.mass_loaded_kg,
            rotating_mass_factor=train_type.rotating_mass_factor,
            max_speed_ms=train_type.max_speed_ms,
            max_acceleration_ms2=train_type.max_acceleration_ms2,
            max_service_deceleration_ms2=train_type.max_service_deceleration_ms2,
            emergency_deceleration_ms2=train_type.emergency_deceleration_ms2,
            traction_model_type=train_type.traction_model_type,
            davis_a_n=train_type.davis_a_n,
            davis_b_ns_m=train_type.davis_b_ns_m,
            davis_c_ns2_m2=train_type.davis_c_ns2_m2,
            power_w=train_type.power_w,
            max_tractive_effort_n=train_type.max_tractive_effort_n,
            traction_curve=train_type.traction_curve,
            adhesion_coefficient=adhesion_coefficient,
            adhesive_mass_fraction=adhesive_mass_fraction,
            mass_condition=mass_condition,
        )


@dataclass(frozen=True)
class TrainFormation:
    """Represents a consist / formation of one or more rolling stock units.

    P03-RS-004: Supports multi-vehicle configurations aggregating mass, length, and performance.
    """

    formation_id: str
    units: List[RollingStockParameters]

    def __post_init__(self) -> None:
        if not self.units:
            raise RollingStockError("Train formation must contain at least one rolling stock unit.")

    @property
    def total_length_m(self) -> float:
        return sum(u.length_m for u in self.units)

    @property
    def total_operational_mass_kg(self) -> float:
        return sum(u.operational_mass_kg for u in self.units)

    @property
    def total_equivalent_mass_kg(self) -> float:
        return sum(u.equivalent_mass_kg for u in self.units)

    @property
    def max_speed_ms(self) -> float:
        """Formation max speed is governed by the lowest unit speed limit."""
        return min(u.max_speed_ms for u in self.units)
