"""Constrained Block-Length Sensitivity Analysis.

Milestone P10 / RHS-P10-001 & v1.9.1:
Evaluates line headway and capacity response across 16 discrete cases:
['AS-BUILT', '25m', '50m', '75m', '100m', '150m', '200m', '400m', '600m', '800m', '1000m', '1200m', '1400m', '1600m', '1800m', '2000m'],
pinned to the measured AS-BUILT baseline.
Handles block lengths shorter than train length (202m) gracefully via multi-block occupancy.
"""

import math
from typing import List, Optional, Sequence

from headway.analysis.capacity_models import (
    SensitivityPointResult,
    SensitivityStudyResult,
)

CONSTRAINED_LENGTHS_M: List[int] = [
    25,
    50,
    75,
    100,
    150,
    200,
    400,
    600,
    800,
    1000,
    1200,
    1400,
    1600,
    1800,
    2000,
]


def calculate_block_length_sensitivity(
    baseline_headway_s: float,
    baseline_bottleneck_id: str = "AS-BUILT",
    train_speed_kmh: float = 300.0,
    train_length_m: float = 202.0,
    braking_deceleration_mps2: float = 0.8,
    sighting_time_s: float = 8.0,
    release_delay_s: float = 4.0,
    baseline_block_length_m: float = 1500.0,
    study_id: str = "SENS_BLOCK_LENGTH",
    min_headway_floor_s: Optional[float] = None,
    candidate_lengths_m: Optional[Sequence[int]] = None,
) -> SensitivityStudyResult:
    """Calculate constrained block length sensitivity, residual-pinned to the as-built baseline.

    X-Axis cases:
    ['AS-BUILT', '25m', '50m', '75m', '100m', '150m', '200m', '400m', '600m', '800m', '1000m', '1200m', '1400m', '1600m', '1800m', '2000m'] (exactly 16 cases).
    """
    if baseline_headway_s <= 0.0:
        baseline_headway_s = 180.0
    if train_speed_kmh <= 0.0:
        train_speed_kmh = 250.0
    if train_length_m <= 0.0:
        train_length_m = 202.0

    v = max(5.0, train_speed_kmh / 3.6)
    candidate_lengths = list(candidate_lengths_m) if candidate_lengths_m is not None else list(CONSTRAINED_LENGTHS_M)

    base_cap = round(3600.0 / baseline_headway_s, 1)

    # v1.11.0 / Task 3: residual-pinned decomposition.
    #   hw(bl) = R0_dir + K_kin(bl),  where
    #     K_kin(bl) = kinematic kernel (approach sighting + block traversal + release)
    #     R0_dir    = direction-specific residual overhead preserved from the measured
    #                 as-built baseline: R0_dir = H_base_dir − K_kin(bl_base).
    #   This replaces the direction-independent pinned-delta form
    #   hw(bl) = H_base + (K(bl) − K(bl_base)) — algebraically identical, but the
    #   explicit residual term keeps every candidate trace anchored to the MEASURED
    #   as-built operating point of the analysed running direction, so FWD/REV studies
    #   cannot silently share a fabricated delta structure.
    def _kinematic_kernel_s(bl: float) -> float:
        # Graceful handling for bl < train_length_m: train spans multiple contiguous blocks
        n_blocks_train = max(1, math.ceil(train_length_m / bl))
        effective_occupancy_len = max(bl + train_length_m, n_blocks_train * bl)
        # 3-aspect approach distance: 1 block warning + sighting
        t_approach = (bl + v * sighting_time_s) / v
        t_traversal = effective_occupancy_len / v
        return t_approach + t_traversal + release_delay_s

    k_base_kernel = _kinematic_kernel_s(float(baseline_block_length_m))
    residual_r0_s = max(0.0, baseline_headway_s - k_base_kernel)

    floor_hw = min_headway_floor_s if min_headway_floor_s is not None else max(45.0, baseline_headway_s * 0.5)

    points: List[SensitivityPointResult] = []

    # Point 0: AS-BUILT (residual-pinned: R0 + K(bl_base) == measured baseline exactly)
    points.append(
        SensitivityPointResult(
            parameter_name="block_length_m",
            parameter_value="AS-BUILT",
            capacity_trains_per_hour=base_cap,
            headway_s=round(baseline_headway_s, 1),
            limiting_bottleneck_id=baseline_bottleneck_id,
            delta_capacity_vs_baseline=0.0,
            percentage_gain_vs_baseline=0.0,
            notes=f"AS-BUILT Baseline (residual-pinned, R0={residual_r0_s:.1f} s)",
            details={"kinematic_kernel_s": round(k_base_kernel, 2), "residual_overhead_s": round(residual_r0_s, 2)},
        )
    )

    # Candidate lengths (e.g. 25m to 2000m)
    for bl in candidate_lengths:
        n_blocks_train = max(1, math.ceil(train_length_m / bl))
        k_cand = _kinematic_kernel_s(float(bl))

        hw = max(floor_hw, round(residual_r0_s + k_cand, 1))
        cap = round(3600.0 / hw, 1)
        delta_cap = round(cap - base_cap, 1)
        pct_gain = round((delta_cap / max(1.0, base_cap)) * 100.0, 1)

        points.append(
            SensitivityPointResult(
                parameter_name="block_length_m",
                parameter_value=f"{bl}m",
                capacity_trains_per_hour=cap,
                headway_s=hw,
                limiting_bottleneck_id=f"BLK_{bl}M",
                delta_capacity_vs_baseline=delta_cap,
                percentage_gain_vs_baseline=pct_gain,
                notes=f"Recalculated block={bl}m, spanning={n_blocks_train} blocks; R0 residual preserved from as-built",
                details={"kinematic_kernel_s": round(k_cand, 2), "residual_overhead_s": round(residual_r0_s, 2)},
            )
        )

    return SensitivityStudyResult(
        study_id=study_id,
        parameter_name="block_length_m",
        baseline_value="AS-BUILT",
        baseline_capacity_tph=base_cap,
        baseline_headway_s=round(baseline_headway_s, 1),
        baseline_bottleneck_id=baseline_bottleneck_id,
        points=points,
    )
