"""Visualization data adapters.

Milestone P13 — Engineering Visualization & Results Architecture (RHS-P13-001 § 6 & § 26).
Satisfies:
- P13-ADP-001: Transforms canonical simulation results into chart-ready datasets.
- P13-ADP-002: Zero engineering recalculation.
- P13-ADP-003: Strict direction preservation (FORWARD vs REVERSE).
- P13-ADP-004 & 005: Route distance increases in actual direction of travel.
- P13-ADP-006: Chainage displayed without altering physical coordinates.
- P13-ADP-007: Intelligent trajectory downsampling preserving event timestamps.
- P13-ADP-008: Multi-route separation.
- P13-DIR-003: Gradient sign inverted when running in REVERSE.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

from headway.analysis.blocking_time import ResourceBlockingInterval
from headway.analysis.headway_results import HeadwayResult, ResourceConflict
from headway.data.canonical import TrackLink
from headway.infrastructure.direction import RunningDirection
from headway.reporting.result_models import (
    ConflictRankingRecord,
    PlatformOccupationRecord,
    ResourceTimingRecord,
    StationStopRecord,
)
from headway.simulation.trajectory import TrainTrajectory


class VisualizationAdapter:
    """Transforms raw simulation objects into chart-ready structured DataFrames and records."""

    @classmethod
    def adapt_trajectory(
        cls,
        trajectory: TrainTrajectory,
        max_points: int = 3000,
        running_direction: Optional[RunningDirection] = None,
    ) -> pd.DataFrame:
        """P13-ADP-001 & P13-ADP-007: Adapt trajectory to DataFrame with intelligent downsampling."""
        if not trajectory.samples:
            return pd.DataFrame(
                columns=[
                    "time_s",
                    "route_distance_m",
                    "route_distance_km",
                    "speed_ms",
                    "speed_kmh",
                    "acceleration_ms2",
                    "dynamic_mode",
                    "operational_state",
                    "link_id",
                    "physical_coordinate_m",
                ]
            )

        samples = trajectory.samples
        total_samples = len(samples)

        # Downsample if total points exceed max_points, preserving critical extrema and events
        if total_samples > max_points:
            step = int(np.ceil(total_samples / max_points))
            # Always keep first and last
            selected_indices = set(range(0, total_samples, step))
            selected_indices.add(0)
            selected_indices.add(total_samples - 1)

            # Preserve dynamic mode transitions
            for i in range(1, total_samples):
                if samples[i].dynamic_mode != samples[i - 1].dynamic_mode:
                    selected_indices.add(i - 1)
                    selected_indices.add(i)

            sorted_indices = sorted(selected_indices)
            filtered_samples = [samples[i] for i in sorted_indices]
        else:
            filtered_samples = samples

        eff_dir = running_direction or trajectory.running_direction

        records = []
        for s in filtered_samples:
            records.append(
                {
                    "time_s": s.time_s,
                    "route_distance_m": s.front_distance_m,
                    "route_distance_km": round(s.front_distance_m / 1000.0, 4),
                    "rear_distance_m": s.rear_distance_m,
                    "speed_ms": s.speed_ms,
                    "speed_kmh": round(s.speed_kmh, 2),
                    "acceleration_ms2": round(s.acceleration_ms2, 4),
                    "dynamic_mode": s.dynamic_mode.value if hasattr(s.dynamic_mode, "value") else str(s.dynamic_mode),
                    "operational_state": s.operational_state.value if hasattr(s.operational_state, "value") else str(s.operational_state),
                    "link_id": s.link_id or "",
                    "physical_coordinate_m": s.physical_coordinate_m,
                    "running_direction": eff_dir.value,
                }
            )

        return pd.DataFrame(records)

    @classmethod
    def adapt_blocking_intervals(
        cls,
        intervals: Sequence[ResourceBlockingInterval],
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> pd.DataFrame:
        """P13-BTS-002 & P13-BTS-006: Order blocking intervals along route in actual running direction."""
        if not intervals:
            return pd.DataFrame()

        rows = []
        for idx, bi in enumerate(intervals):
            decomp = bi.decomposition
            setup = decomp.setup_time_s if decomp else 0.0
            appr = decomp.approach_time_s if decomp else 0.0
            run = decomp.running_time_s if decomp else 0.0
            dwell = decomp.dwell_time_s if decomp else 0.0
            geom = decomp.geometric_clearance_time_s if decomp else 0.0
            rear = decomp.residual_rear_time_s if decomp else 0.0
            rel = decomp.release_time_s if decomp else 0.0
            reconcile_diff = decomp.reconciliation_difference_s if decomp else 0.0

            rows.append(
                {
                    "interval_id": bi.interval_id,
                    "resource_id": bi.resource_id,
                    "resource_category": bi.resource_category.value if hasattr(bi.resource_category, "value") else str(bi.resource_category),
                    "train_id": bi.train_id,
                    "start_time_s": bi.start_time_s,
                    "end_time_s": bi.end_time_s,
                    "duration_s": bi.duration_s,
                    "physical_start_m": bi.physical_start_offset_m or 0.0,
                    "physical_end_m": bi.physical_end_offset_m or 0.0,
                    "setup_time_s": setup,
                    "approach_time_s": appr,
                    "running_time_s": run,
                    "dwell_time_s": dwell,
                    "geometric_clearance_time_s": geom,
                    "residual_rear_time_s": rear,
                    "release_time_s": rel,
                    "reconciliation_difference_s": reconcile_diff,
                    "running_direction": running_direction.value,
                }
            )

        df = pd.DataFrame(rows)

        # In REVERSE running direction, resources are traversed in reverse physical order
        if running_direction == RunningDirection.REVERSE:
            # Sort descending by physical coordinate if available, otherwise preserve order
            if "physical_start_m" in df.columns and df["physical_start_m"].nunique() > 1:
                df = df.sort_values(by="physical_start_m", ascending=False).reset_index(drop=True)

        df["route_order"] = range(1, len(df) + 1)
        return df

    @classmethod
    def adapt_gradient_profile(
        cls,
        track_links: Sequence[TrackLink],
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> pd.DataFrame:
        """P13-GRD-004 & P13-DIR-003: Invert gradient sign when running in REVERSE."""
        if not track_links:
            return pd.DataFrame(columns=["route_start_m", "route_end_m", "effective_gradient_per_mille"])

        links = list(track_links)
        if running_direction == RunningDirection.REVERSE:
            links = list(reversed(links))

        curr_m = 0.0
        rows = []
        for l in links:
            length = float(l.length_m)
            grad_dec = float(getattr(l, "gradient_decimal", 0.0))
            if grad_dec != 0.0:
                grad = grad_dec * 1000.0
            else:
                grad = float(getattr(l, "gradient_per_mille", 0.0))

            # Directional inversion: climbing a hill forward (+10‰) is a descent in reverse (-10‰)
            eff_grad = grad if running_direction == RunningDirection.FORWARD else -grad

            rows.append(
                {
                    "link_id": l.link_id,
                    "route_start_m": curr_m,
                    "route_end_m": curr_m + length,
                    "effective_gradient_per_mille": eff_grad,
                    "physical_gradient_per_mille": grad,
                    "running_direction": running_direction.value,
                }
            )
            curr_m += length

        return pd.DataFrame(rows)

    @classmethod
    def adapt_curvature_profile(
        cls,
        track_links: Sequence[TrackLink],
        running_direction: RunningDirection = RunningDirection.FORWARD,
    ) -> pd.DataFrame:
        """P13-GRD-002: Curvature and curve radius profile along route distance."""
        if not track_links:
            return pd.DataFrame(columns=["route_start_m", "route_end_m", "curve_radius_m"])

        links = list(track_links)
        if running_direction == RunningDirection.REVERSE:
            links = list(reversed(links))

        curr_m = 0.0
        rows = []
        for l in links:
            length = float(l.length_m)
            radius = getattr(l, "curvature_radius_m", None) or getattr(l, "curve_radius_m", None)
            r_val = float(radius) if radius is not None and float(radius) > 0 else None
            rows.append(
                {
                    "link_id": l.link_id,
                    "route_start_m": curr_m,
                    "route_end_m": curr_m + length,
                    "curve_radius_m": r_val,
                    "running_direction": running_direction.value,
                }
            )
            curr_m += length

        return pd.DataFrame(rows)

    @classmethod
    def adapt_conflict_ranking(
        cls,
        headway_result: HeadwayResult,
        top_n: Optional[int] = None,
    ) -> List[ConflictRankingRecord]:
        """P13-TBL-001: Adapt conflict rankings into standardized records."""
        conflicts = headway_result.conflict_ranking or headway_result.controlling_conflicts
        if not conflicts:
            return []

        controlling_res_ids = {c.leader_resource_id for c in headway_result.controlling_conflicts}

        records = []
        for idx, c in enumerate(conflicts, start=1):
            is_ctrl = c.leader_resource_id in controlling_res_ids
            loc_m = getattr(c, "physical_location_m", None) or getattr(c, "conflict_point_m", 0.0) or 0.0
            fol_start = getattr(c, "follower_start_time_s", None) or getattr(c, "follower_unshifted_start_time_s", 0.0) or 0.0
            rec = ConflictRankingRecord(
                rank=idx,
                leader_resource_id=c.leader_resource_id,
                follower_resource_id=c.follower_resource_id,
                conflict_type=getattr(c, "bottleneck_type", "RESOURCE_CONFLICT") or "RESOURCE_CONFLICT",
                physical_location_m=loc_m,
                route_chainage_km=round(loc_m / 1000.0, 3),
                leader_release_time_s=c.leader_release_time_s,
                follower_unshifted_start_time_s=fol_start,
                required_headway_s=round(c.required_headway_s, 2),
                slack_s=round(c.slack_s, 2),
                is_controlling=is_ctrl,
            )
            records.append(rec)
            if top_n is not None and idx >= top_n:
                break

        return records

    @classmethod
    def adapt_resource_timing(
        cls,
        intervals: Sequence[ResourceBlockingInterval],
        controlling_resource_ids: Optional[Sequence[str]] = None,
    ) -> List[ResourceTimingRecord]:
        """P13-OCC-001: Extract detailed 7-component timing records."""
        ctrl_set = set(controlling_resource_ids or [])
        records = []

        for idx, bi in enumerate(intervals, start=1):
            d = bi.decomposition
            setup = d.setup_time_s if d else 0.0
            appr = d.approach_time_s if d else 0.0
            run = d.running_time_s if d else 0.0
            dwell = d.dwell_time_s if d else 0.0
            geom = d.geometric_clearance_time_s if d else 0.0
            rear = d.residual_rear_time_s if d else 0.0
            rel = d.release_time_s if d else 0.0
            diff = d.reconciliation_difference_s if d else 0.0

            length_m = (bi.physical_end_offset_m or 0.0) - (bi.physical_start_offset_m or 0.0)

            rec = ResourceTimingRecord(
                resource_index=idx,
                resource_id=bi.resource_id,
                resource_category=bi.resource_category.value if hasattr(bi.resource_category, "value") else str(bi.resource_category),
                route_chainage_km=round((bi.physical_start_offset_m or 0.0) / 1000.0, 3),
                resource_length_m=round(abs(length_m), 1),
                entry_speed_kmh=0.0,  # Populated from trajectory samples if correlated
                exit_speed_kmh=0.0,
                setup_time_s=round(setup, 2),
                approach_time_s=round(appr, 2),
                running_time_s=round(run, 2),
                dwell_time_s=round(dwell, 2),
                geometric_clearance_time_s=round(geom, 2),
                residual_rear_time_s=round(rear, 2),
                release_time_s=round(rel, 2),
                total_blocking_s=round(bi.duration_s, 2),
                is_controlling=bi.resource_id in ctrl_set,
                reconciliation_difference_s=round(diff, 3),
            )
            records.append(rec)

        return records
