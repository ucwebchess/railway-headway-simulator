"""Directional mixed-traffic headway matrix builder across N service types.

Strictly satisfies RHS-P08-001 § 15:
- P08-MIX-001: Matrix calculation across all ordered combinations of service types.
- P08-MIX-002: Matrix orientation: rows = leader services, columns = follower services.
- P08-MIX-003: Diagonal represents homogeneous service pairs.
- P08-MIX-004: Asymmetry preserved (H(i,j) != H(j,i)).
- P08-MIX-005: Explicit infeasible pair representation.
- P08-MIX-006: Independent FORWARD and REVERSE matrices.
"""

from typing import Dict, List, Optional, Set, Tuple

from headway.analysis.blocking_time import BlockingTimeline
from headway.analysis.headway_results import HeadwayResult, MixedTrafficHeadwayMatrix
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.infrastructure.direction import RunningDirection


class MixedTrafficAnalyzer:
    """Computes directional mixed-traffic headway matrices."""

    def __init__(
        self,
        solver: Optional[TechnicalHeadwaySolver] = None,
    ) -> None:
        self.solver = solver or TechnicalHeadwaySolver()

    def compute_matrix(
        self,
        timelines: Dict[str, BlockingTimeline],  # service_id -> timeline
        running_direction: RunningDirection = RunningDirection.FORWARD,
        matrix_id: str = "MTX_001",
        shared_groups: Optional[Dict[str, Set[str]]] = None,
        conflicting_routes: Optional[Dict[str, Set[str]]] = None,
        tunnel_to_tvs: Optional[Dict[str, Set[str]]] = None,
        whole_tunnel_tvs_ids: Optional[Set[str]] = None,
        custom_dispatch_min_s: Optional[float] = None,
    ) -> MixedTrafficHeadwayMatrix:
        """P08-MIX: Computes N x N directional headway matrix for specified service timelines."""
        service_ids = sorted(timelines.keys())
        headway_values: Dict[Tuple[str, str], float] = {}
        controlling_bottlenecks: Dict[Tuple[str, str], str] = {}
        results: Dict[Tuple[str, str], HeadwayResult] = {}

        for l_id in service_ids:
            l_tl = timelines[l_id]
            for f_id in service_ids:
                f_tl = timelines[f_id]

                res = self.solver.solve_pairwise_headway(
                    leader_timeline=l_tl,
                    follower_timeline=f_tl,
                    shared_groups=shared_groups,
                    conflicting_routes=conflicting_routes,
                    tunnel_to_tvs=tunnel_to_tvs,
                    whole_tunnel_tvs_ids=whole_tunnel_tvs_ids,
                    run_id=f"RUN_{l_id}_{f_id}",
                    analysis_id=f"AN_{l_id}_{f_id}",
                    custom_dispatch_min_s=custom_dispatch_min_s,
                )

                pair_key = (l_id, f_id)
                headway_values[pair_key] = res.headway_s
                controlling_bottlenecks[pair_key] = res.controlling_bottleneck_description
                results[pair_key] = res

        return MixedTrafficHeadwayMatrix(
            matrix_id=matrix_id,
            running_direction=running_direction,
            service_ids=service_ids,
            headway_values_s=headway_values,
            controlling_bottlenecks=controlling_bottlenecks,
            results=results,
        )
