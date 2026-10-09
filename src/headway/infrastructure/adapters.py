"""Visualization data adapters for railway infrastructure.

Strictly satisfies RHS-P02-001 § 21:
- P02-VIS-001: Forward display data in forward running order.
- P02-VIS-002: Reverse display data in reverse running order (route-distance and chainage in running order).
- P02-VIS-003: Structured data adapters for future UI (P13 / P15) without embedding interactive widgets.
"""

from typing import Any, Dict, List, Optional
import pandas as pd

from headway.infrastructure.chainage import EngineeringChainageModel
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.preprocessor import RouteProfile


class InfrastructureVisualizerAdapter:
    """Exports structured data frames and dictionaries for infrastructure visualization."""

    @staticmethod
    def get_nodes_dataframe(profile: RouteProfile) -> pd.DataFrame:
        """Export node positions along the route."""
        rows = []
        for t in profile.route.traversals:
            rows.append({
                "node_id": t.entry_node_id,
                "route_distance_m": t.start_distance_m,
                "role": "ENTRY",
                "link_id": t.link_id,
            })
        # Add final terminus node
        final_t = profile.route.traversals[-1]
        rows.append({
            "node_id": final_t.exit_node_id,
            "route_distance_m": final_t.end_distance_m,
            "role": "EXIT",
            "link_id": final_t.link_id,
        })
        return pd.DataFrame(rows)

    @staticmethod
    def get_traversals_dataframe(profile: RouteProfile) -> pd.DataFrame:
        """Export link traversals in running order."""
        rows = []
        for t in profile.route.traversals:
            rows.append({
                "sequence_index": t.sequence_index,
                "link_id": t.link_id,
                "direction": t.direction.value,
                "start_distance_m": t.start_distance_m,
                "end_distance_m": t.end_distance_m,
                "length_m": t.length_m,
                "entry_node": t.entry_node_id,
                "exit_node": t.exit_node_id,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def get_gradients_dataframe(profile: RouteProfile) -> pd.DataFrame:
        """Export effective gradient intervals in running order."""
        rows = []
        for g in profile.alignment.gradient_intervals:
            rows.append({
                "start_distance_m": g.start_distance_m,
                "end_distance_m": g.end_distance_m,
                "length_m": g.length_m,
                "effective_gradient_decimal": g.effective_gradient_decimal,
                "gradient_per_mille": g.gradient_per_mille,
                "link_id": g.link_id,
                "physical_gradient_decimal": g.physical_gradient_decimal,
                "direction": g.direction.value,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def get_curvature_dataframe(profile: RouteProfile) -> pd.DataFrame:
        """Export curvature intervals in running order."""
        rows = []
        for c in profile.alignment.curvature_intervals:
            rows.append({
                "start_distance_m": c.start_distance_m,
                "end_distance_m": c.end_distance_m,
                "length_m": c.length_m,
                "radius_m": c.radius_m if c.radius_m is not None else 0.0,
                "curvature_1_per_m": c.curvature_1_per_m,
                "is_curve": c.is_curve,
                "link_id": c.link_id,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def get_speed_profile_dataframe(profile: RouteProfile) -> pd.DataFrame:
        """Export permissible speed intervals in running order."""
        rows = []
        for s in profile.speed_profile.speed_intervals:
            rows.append({
                "start_distance_m": s.start_distance_m,
                "end_distance_m": s.end_distance_m,
                "length_m": s.length_m,
                "max_speed_ms": s.max_speed_ms,
                "max_speed_kmh": s.max_speed_kmh,
                "link_id": s.link_id,
                "governing_source": s.governing_source,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def get_stations_dataframe(profile: RouteProfile) -> pd.DataFrame:
        """Export station and platform stops in running order."""
        rows = []
        for st in profile.stations:
            rows.append({
                "station_id": st.station.station_id,
                "station_name": st.station.name,
                "platform_id": st.platform.platform_id,
                "stopping_position_m": st.stopping_position_m,
                "platform_start_m": st.route_distance_start_m,
                "platform_end_m": st.route_distance_end_m,
                "platform_length_m": st.platform_length_m,
                "direction": st.direction.value,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def get_tvs_dataframe(profile: RouteProfile) -> pd.DataFrame:
        """Export TVS sections in running order."""
        rows = []
        for tvs in profile.tvs_sections:
            rows.append({
                "tvs_id": tvs.tvs_id,
                "tunnel_name": tvs.tunnel_name or "",
                "route_entry_m": tvs.route_entry_distance_m,
                "route_exit_m": tvs.route_exit_distance_m,
                "physical_length_m": tvs.physical_length_m,
                "max_train_occupancy": tvs.max_train_occupancy,
                "holding_signal_id": tvs.holding_signal_id or "",
                "direction": tvs.running_direction.value,
            })
        return pd.DataFrame(rows)
