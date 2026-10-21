"""Constrained Block-Length Sensitivity Analysis.

Milestone P10 / RHS-P10-001 & v1.9.0:
Evaluates line headway and capacity response across 26 discrete cases:
['AS-BUILT', '200m', '400m', ..., '5000m'], pinned to the measured AS-BUILT baseline.
Handles block lengths shorter than train length (202m) gracefully.
"""

import math
from typing import List, Optional

from headway.analysis.capacity_models import (
    SensitivityPointResult,
    SensitivityStudyResult,
)


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
) -> SensitivityStudyResult:
    """Calculate 26-case constrained block length sensitivity pinned to AS-BUILT baseline.

    X-Axis cases:
    ['AS-BUILT', '200m', '400m', '600m', ..., '5000m'] (exactly 26 cases).
    """
    if baseline_headway_s <= 0.0:
        baseline_headway_s = 180.0
    if train_speed_kmh <= 0.0:
        train_speed_kmh = 250.0
    if train_length_m <= 0.0:
        train_length_m = 202.0

    v = max(5.0, train_speed_kmh / 3.6)
    candidate_lengths = [l * 200 for l in range(1, 26)]  # 200m to 5000m (25 values)

    base_cap = round(3600.0 / baseline_headway_s, 1)

    # Base block traversal time reference
    t_base = (2.0 * baseline_block_length_m + train_length_m) / v + sighting_time_s + release_delay_s

    floor_hw = min_headway_floor_s if min_headway_floor_s is not None else max(45.0, baseline_headway_s * 0.5)

    points: List[SensitivityPointResult] = []

    # Point 0: AS-BUILT (Baseline pinned)
    points.append(
        SensitivityPointResult(
            parameter_name="block_length_m",
            parameter_value="AS-BUILT",
            capacity_trains_per_hour=base_cap,
            headway_s=round(baseline_headway_s, 1),
            limiting_bottleneck_id=baseline_bottleneck_id,
            delta_capacity_vs_baseline=0.0,
            percentage_gain_vs_baseline=0.0,
            notes="AS-BUILT Baseline (Pinned)",
        )
    )

    # Points 1 to 25: 200m to 5000m
    for bl in candidate_lengths:
        # Graceful handling for bl < train_length_m (202m):
        # When bl < train_length_m, train spans multiple contiguous blocks
        n_blocks_train = max(1, math.ceil(train_length_m / bl))
        effective_occupancy_len = max(bl + train_length_m, n_blocks_train * bl)

        # 3-aspect approach distance: 1 block warning + sighting
        t_approach = (bl + v * sighting_time_s) / v
        t_traversal = effective_occupancy_len / v
        t_cand = t_approach + t_traversal + release_delay_s

        delta_t = t_cand - t_base
        hw = max(floor_hw, round(baseline_headway_s + delta_t, 1))
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
                notes=f"Recalculated block={bl}m, spanning={n_blocks_train} blocks",
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
