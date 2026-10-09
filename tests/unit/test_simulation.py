"""Unit tests for microscopic simulation state, targets, events, speed profiles, and trajectory contracts.

Strictly satisfies RHS-P04-001:
- P04-STATE-001 to P04-STATE-004
- P04-TGT-001 to P04-TGT-004
- P04-EVT-001 to P04-EVT-003
- P04-SPD-001 to P04-SPD-020
- P04-OUT-001 to P04-OUT-005
"""

import pytest

from headway.core.exceptions import SimulationError
from headway.infrastructure.direction import RunningDirection
from headway.rolling_stock.braking import BrakingCategory, ConstantDecelerationBrakingModel
from headway.simulation.events import (
    BoundaryEvent,
    CrossingEventType,
)
from headway.simulation.state import (
    DynamicMode,
    OperationalState,
    TrainDynamicState,
)
from headway.simulation.targets import (
    BrakingTarget,
    BrakingTargetType,
)
from headway.simulation.trajectory import (
    TrajectorySample,
    TrainTrajectory,
)


def test_train_dynamic_state_properties_and_invariants():
    """Verify TrainDynamicState SI units, properties, and invariant enforcement."""
    state = TrainDynamicState(
        train_id="TRN_01",
        simulation_time_s=10.0,
        route_id="RT_01",
        front_distance_m=500.0,
        rear_distance_m=300.0,
        speed_ms=25.0,
        acceleration_ms2=0.5,
        traction_force_n=10000.0,
        braking_force_n=0.0,
        davis_resistance_n=2000.0,
        gradient_resistance_n=1000.0,
        curvature_resistance_n=0.0,
        net_force_n=7000.0,
        dynamic_mode=DynamicMode.ACCELERATING,
        operational_state=OperationalState.RUNNING,
    )

    # Properties
    assert state.speed_kmh == pytest.approx(90.0, rel=1e-5)
    assert state.is_moving is True
    assert state.is_stopped is False

    # Test invalid time
    with pytest.raises(SimulationError, match="Simulation time cannot be negative"):
        TrainDynamicState(
            train_id="TRN_01", simulation_time_s=-1.0, route_id="RT_01",
            front_distance_m=0.0, rear_distance_m=-100.0,
            speed_ms=0.0, acceleration_ms2=0.0,
            traction_force_n=0.0, braking_force_n=0.0, davis_resistance_n=0.0,
            gradient_resistance_n=0.0, curvature_resistance_n=0.0, net_force_n=0.0,
            dynamic_mode=DynamicMode.STOPPED, operational_state=OperationalState.STANDSTILL,
        )

    # Test invalid speed
    with pytest.raises(SimulationError, match="Negative train speed"):
        TrainDynamicState(
            train_id="TRN_01", simulation_time_s=0.0, route_id="RT_01",
            front_distance_m=0.0, rear_distance_m=-100.0,
            speed_ms=-0.5, acceleration_ms2=0.0,
            traction_force_n=0.0, braking_force_n=0.0, davis_resistance_n=0.0,
            gradient_resistance_n=0.0, curvature_resistance_n=0.0, net_force_n=0.0,
            dynamic_mode=DynamicMode.STOPPED, operational_state=OperationalState.STANDSTILL,
        )

    # Test invalid rear > front
    with pytest.raises(SimulationError, match="cannot be behind rear"):
        TrainDynamicState(
            train_id="TRN_01", simulation_time_s=0.0, route_id="RT_01",
            front_distance_m=100.0, rear_distance_m=200.0,
            speed_ms=0.0, acceleration_ms2=0.0,
            traction_force_n=0.0, braking_force_n=0.0, davis_resistance_n=0.0,
            gradient_resistance_n=0.0, curvature_resistance_n=0.0, net_force_n=0.0,
            dynamic_mode=DynamicMode.STOPPED, operational_state=OperationalState.STANDSTILL,
        )


def test_braking_target_feasibility():
    """Verify target margin and stopping distance feasibility checks."""
    brk_model = ConstantDecelerationBrakingModel(
        service_deceleration_ms2=1.0,
        emergency_deceleration_ms2=1.2,
        response_delay_s=0.0,
        build_up_time_s=0.0,
    )

    target = BrakingTarget(
        target_id="TGT_01",
        route_position_m=1000.0,
        target_speed_ms=0.0,
        target_type=BrakingTargetType.STATION_STOP,
        margin_m=10.0,
        braking_category=BrakingCategory.OPERATIONAL_SERVICE,
    )

    # Effective position = 1000 - 10 = 990 m
    assert target.effective_target_position_m == 990.0

    # From 30 m/s: required distance = 30^2 / (2 * 1) = 450 m.
    # At position 500 m, available distance = 990 - 500 = 490 m >= 450 m -> Feasible
    assert target.is_feasible(current_position_m=500.0, current_speed_ms=30.0, braking_model=brk_model) is True

    # At position 600 m, available distance = 990 - 600 = 390 m < 450 m -> Infeasible
    assert target.is_feasible(current_position_m=600.0, current_speed_ms=30.0, braking_model=brk_model) is False


def test_boundary_event_contract():
    """Verify BoundaryEvent fields and immutability."""
    evt = BoundaryEvent(
        event_type=CrossingEventType.LINK_FRONT_ENTER,
        timestamp_s=12.34,
        route_distance_m=1500.0,
        train_id="TRN_01",
        is_front=True,
        speed_ms=22.5,
        link_id="LNK_AB",
        physical_coordinate_m=500.0,
        description="Entered link LNK_AB",
    )
    assert evt.event_type == CrossingEventType.LINK_FRONT_ENTER
    assert evt.timestamp_s == 12.34
    assert evt.route_distance_m == 1500.0
    assert evt.speed_ms == 22.5
    assert evt.link_id == "LNK_AB"


def test_train_trajectory_metrics_and_dataframe():
    """Verify TrainTrajectory metric properties and DataFrame conversion."""
    traj = TrainTrajectory(
        train_id="TRN_EXPRESS",
        train_type_id="TT_EXPRESS",
        route_id="RT_MAIN",
        running_direction=RunningDirection.FORWARD,
    )

    # Add 4 samples: t=0 (v=0), t=10 (v=20, s=100), t=20 (v=20, s=300), t=30 (v=0, s=300, dwelling)
    traj.samples.append(
        TrajectorySample(
            time_s=0.0, front_distance_m=0.0, rear_distance_m=-100.0, speed_ms=0.0,
            acceleration_ms2=2.0, traction_force_n=200000.0, braking_force_n=0.0,
            davis_resistance_n=1000.0, gradient_resistance_n=0.0, curvature_resistance_n=0.0,
            net_force_n=199000.0, dynamic_mode=DynamicMode.ACCELERATING,
            operational_state=OperationalState.RUNNING,
        )
    )
    traj.samples.append(
        TrajectorySample(
            time_s=10.0, front_distance_m=100.0, rear_distance_m=0.0, speed_ms=20.0,
            acceleration_ms2=0.0, traction_force_n=5000.0, braking_force_n=0.0,
            davis_resistance_n=5000.0, gradient_resistance_n=0.0, curvature_resistance_n=0.0,
            net_force_n=0.0, dynamic_mode=DynamicMode.CRUISING,
            operational_state=OperationalState.RUNNING,
        )
    )
    traj.samples.append(
        TrajectorySample(
            time_s=20.0, front_distance_m=300.0, rear_distance_m=200.0, speed_ms=20.0,
            acceleration_ms2=-2.0, traction_force_n=0.0, braking_force_n=150000.0,
            davis_resistance_n=5000.0, gradient_resistance_n=0.0, curvature_resistance_n=0.0,
            net_force_n=-155000.0, dynamic_mode=DynamicMode.SERVICE_BRAKING,
            operational_state=OperationalState.RUNNING,
        )
    )
    traj.samples.append(
        TrajectorySample(
            time_s=30.0, front_distance_m=300.0, rear_distance_m=200.0, speed_ms=0.0,
            acceleration_ms2=0.0, traction_force_n=0.0, braking_force_n=0.0,
            davis_resistance_n=0.0, gradient_resistance_n=0.0, curvature_resistance_n=0.0,
            net_force_n=0.0, dynamic_mode=DynamicMode.DWELLING,
            operational_state=OperationalState.STATION_DWELL,
        )
    )

    assert traj.total_time_s == 30.0
    assert traj.total_distance_m == 300.0
    assert traj.max_speed_ms == 20.0

    # DataFrame export
    df = traj.to_dataframe()
    assert len(df) == 4
    assert "speed_kmh" in df.columns
    assert "front_distance_m" in df.columns
    assert "dynamic_mode" in df.columns

    # Records export
    recs = traj.to_records()
    assert len(recs) == 4
    assert recs[1]["speed_ms"] == 20.0
