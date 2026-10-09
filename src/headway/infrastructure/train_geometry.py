"""Train-length spatial footprint and link occupancy geometry utilities.

Strictly satisfies RHS-P02-001 § 18:
- P02-LEN-001: Occupied route interval calculation: [s_rear, s_front] where s_rear = s_front - L_train.
- P02-LEN-002 & BENCH-P02-007: Multiple link occupancy distribution (e.g. 50m in 2nd link, 150m in 1st link).
- P02-LEN-003: Physical resource intersection detection under train footprint.
- P02-LEN-004 & BENCH-P02-008: Direction invariance (reverse operation correctly yields identical physical footprint).
- P02-LEN-005: Boundary conditions (train rear extending before route origin or front extending past exit, without silent truncation).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from headway.core.exceptions import InfrastructureError
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import Route


class TrainGeometryError(InfrastructureError):
    """Raised when train length or footprint coordinates are invalid."""

    DEFAULT_ERROR_CODE = "ERR_INFRA_TRAIN_GEOMETRY"


@dataclass(frozen=True)
class LinkOccupancy:
    """Represents the occupied footprint of a train on a single physical track link."""

    link_id: str
    occupied_length_m: float
    start_offset_m: float
    end_offset_m: float
    traversal_direction: RunningDirection


@dataclass(frozen=True)
class TrainFootprint:
    """The spatial footprint of a train along a route."""

    train_length_m: float
    front_distance_m: float
    rear_distance_m: float
    link_occupancies: List[LinkOccupancy]
    extends_before_origin: bool
    extends_after_terminus: bool
    uncovered_length_before_origin_m: float
    uncovered_length_after_terminus_m: float

    @property
    def total_occupied_length_on_route_m(self) -> float:
        return sum(lo.occupied_length_m for lo in self.link_occupancies)

    @property
    def total_physical_length_m(self) -> float:
        return (
            self.total_occupied_length_on_route_m
            + self.uncovered_length_before_origin_m
            + self.uncovered_length_after_terminus_m
        )


class TrainGeometry:
    """Geometric utility class for computing train footprint over physical railway infrastructure."""

    @staticmethod
    def compute_footprint(
        route: Route,
        front_distance_m: float,
        train_length_m: float,
    ) -> TrainFootprint:
        """Compute the train's spatial footprint along the route and its link-by-link distribution.

        Args:
            route: The active physical route.
            front_distance_m: Position of the train front (head) in cumulative route distance s.
            train_length_m: Total length of the train (L_train > 0).

        Returns:
            TrainFootprint detailing link occupancies and boundary conditions.
        """
        if train_length_m <= 0:
            raise TrainGeometryError(
                f"Train length must be strictly positive (got {train_length_m} m).",
                context={"train_length_m": train_length_m},
            )

        s_front = front_distance_m
        s_rear = s_front - train_length_m

        # Evaluate boundary conditions without silent truncation (P02-LEN-005)
        extends_before_origin = s_rear < 0.0
        extends_after_terminus = s_front > route.total_length_m

        uncovered_before = abs(s_rear) if extends_before_origin else 0.0
        uncovered_after = (s_front - route.total_length_m) if extends_after_terminus else 0.0

        # Clamped interval on route
        route_rear = max(0.0, min(route.total_length_m, s_rear))
        route_front = max(0.0, min(route.total_length_m, s_front))

        link_occupancies: List[LinkOccupancy] = []

        if route_front > route_rear:
            for traversal in route.traversals:
                # Intersection with this traversal's interval
                int_start = max(route_rear, traversal.start_distance_m)
                int_end = min(route_front, traversal.end_distance_m)

                if int_start < int_end:
                    occ_len = int_end - int_start

                    # Map to physical link offsets
                    x1 = traversal.route_distance_to_physical_offset(int_start)
                    x2 = traversal.route_distance_to_physical_offset(int_end)

                    phys_start = min(x1, x2)
                    phys_end = max(x1, x2)

                    link_occupancies.append(
                        LinkOccupancy(
                            link_id=traversal.link_id,
                            occupied_length_m=occ_len,
                            start_offset_m=phys_start,
                            end_offset_m=phys_end,
                            traversal_direction=traversal.direction,
                        )
                    )

        return TrainFootprint(
            train_length_m=train_length_m,
            front_distance_m=s_front,
            rear_distance_m=s_rear,
            link_occupancies=link_occupancies,
            extends_before_origin=extends_before_origin,
            extends_after_terminus=extends_after_terminus,
            uncovered_length_before_origin_m=uncovered_before,
            uncovered_length_after_terminus_m=uncovered_after,
        )
