"""UIC 406-inspired capacity consumption calculation engine.

Milestone P10 — Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis (RHS-P10-001).
Covers:
- P10-UIC-002: UIC 406 capacity consumption K = (T_compressed + T_supplement) / T_analysis
- BENCH-P10-006: 4500s compressed + 900s supplement / 7200s window -> K = 75.0%
- UIC disclaimer enforcement
- Directional attribution
"""

import math
from typing import Dict, Optional, Sequence, Union

from headway.analysis.capacity_models import (
    CapacityResult,
    CapacityType,
    PlanningMarginMethod,
    TimetableCompressionResult,
)
from headway.analysis.timetable_compression import TimetableCompressor
from headway.infrastructure.direction import RunningDirection


class CapacityConsumptionCalculator:
    """Calculates capacity consumption index K based on UIC 406 compression principles."""

    UIC_DISCLAIMER = TimetableCompressor.UIC_DISCLAIMER

    @staticmethod
    def calculate_analytical_consumption(
        compressed_duration_s: float,
        supplement_s: float,
        analysis_window_s: float,
        direction: RunningDirection = RunningDirection.FORWARD,
        corridor_id: str = "DEFAULT_CORRIDOR",
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_UIC406_ANALYTICAL",
        analysis_id: str = "AN_UIC_001",
    ) -> CapacityResult:
        """P10-UIC-002 & BENCH-P10-006: K = (T_compressed + T_supplement) / T_analysis."""
        if not math.isfinite(compressed_duration_s) or compressed_duration_s < 0.0:
            raise ValueError(f"Compressed duration must be non-negative and finite (got {compressed_duration_s} s).")
        if not math.isfinite(supplement_s) or supplement_s < 0.0:
            raise ValueError(f"Supplement duration must be non-negative and finite (got {supplement_s} s).")
        if not math.isfinite(analysis_window_s) or analysis_window_s <= 0.0:
            raise ValueError(f"Analysis window duration must be strictly positive (got {analysis_window_s} s).")

        total_consumed_s = compressed_duration_s + supplement_s
        consumption_ratio = total_consumed_s / analysis_window_s
        consumption_percent = consumption_ratio * 100.0

        # Equivalent throughput and headway over the window
        # For reporting consistency in CapacityResult
        return CapacityResult(
            run_id=run_id,
            analysis_id=analysis_id,
            scenario_id=scenario_id,
            capacity_type=CapacityType.UIC406_CAPACITY_CONSUMPTION,
            running_direction=direction,
            analysis_section=corridor_id,
            measurement_reference="UIC_406_COMPRESSION",
            capacity_trains_per_hour=consumption_percent,  # percentage reported in capacity value for consumption type
            headway_s=0.0,
            planning_margin_method=PlanningMarginMethod.NONE,
            planning_margin_value=supplement_s,
            details={
                "compressed_duration_s": compressed_duration_s,
                "supplement_duration_s": supplement_s,
                "analysis_window_s": analysis_window_s,
                "total_consumed_s": total_consumed_s,
                "consumption_ratio": consumption_ratio,
                "consumption_percent": consumption_percent,
                "formula": "K = (T_compressed + T_supplement) / T_analysis",
                "uic_disclaimer": CapacityConsumptionCalculator.UIC_DISCLAIMER,
            },
        )

    @classmethod
    def calculate_from_compression_result(
        cls,
        compression_result: TimetableCompressionResult,
        analysis_window_s: float,
        supplement_s: float = 0.0,
        direction: RunningDirection = RunningDirection.FORWARD,
        scenario_id: str = "BASELINE",
        run_id: str = "RUN_UIC406_FROM_COMPRESSION",
        analysis_id: str = "AN_UIC_002",
    ) -> CapacityResult:
        """Calculate capacity consumption directly from a TimetableCompressionResult."""
        return cls.calculate_analytical_consumption(
            compressed_duration_s=compression_result.compressed_duration_s,
            supplement_s=supplement_s,
            analysis_window_s=analysis_window_s,
            direction=direction,
            corridor_id=compression_result.corridor_id,
            scenario_id=scenario_id,
            run_id=run_id,
            analysis_id=analysis_id,
        )
