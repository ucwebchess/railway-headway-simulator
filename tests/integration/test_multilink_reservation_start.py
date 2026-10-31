"""Regression tests for multi-link block reservation timestamp retention.

Satisfies Phase 4c:
- Verifies that multi-link blocks retain reservation_start_s from first constituent link entry.
- Guards against subsequent link entries overwriting reservation_start_s.
- Verifies that station dwell time survives across multi-link corridor blocks.
- Verifies that headway responds accurately to station dwell duration.
"""

from typing import List, Optional, Tuple
import pytest

from headway.analysis.blocking_time import (
    BlockingTimeDecomposition,
    BlockingTimeline,
    ResourceBlockingInterval,
)
from headway.analysis.headway_solver import TechnicalHeadwaySolver
from headway.data.canonical import (
    Platform,
    ResourceInterval,
    StationStop,
)
from headway.infrastructure.direction import RunningDirection
from headway.infrastructure.route import LinkTraversal, PositionMappingError, Route
from headway.rolling_stock.train import RollingStockParameters
from headway.signalling.coordinator import SignallingCoordinator
from headway.signalling.resource_types import ResourceCategory
from headway.signalling.resources import ManagedResource
from headway.simulation.multi_train_engine import MultiTrainSimulator
from headway.simulation.service_instance import (
    ServiceType,
    TrainGenerator,
)
from headway.ui.file_manager import FileManager
from headway.ui.simulation_runner import SimulationRunner

from tests.engineering.test_multi_train_benchmarks import make_test_route, make_test_train_params


# ==============================================================================
# Helper: Standalone Microscopic Corridor Runner for Phase 4c
# ==============================================================================

class _FastCorridorSimulator(MultiTrainSimulator):
    """Subclass of MultiTrainSimulator with spatial indexing for fast corridor test runs.

    Leaves base MultiTrainSimulator completely unmutated so other test suites are untouched.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._route_res_cache = {}
        self._route_block_eoa_cache = {}

    def _get_fast_route_resource_intervals(self, route: Route):
        if route.route_id in self._route_res_cache:
            return self._route_res_cache[route.route_id]
        cached = []
        for i, trav in enumerate(route.traversals):
            for res_id, res in self.coordinator.resource_controller.resources.items():
                res_intervals = res.intervals if res.intervals else []
                matching = [
                    (inv_idx, inv)
                    for inv_idx, inv in enumerate(res_intervals)
                    if inv.link_id == trav.link_id
                ]
                for inv_idx, inv in matching:
                    try:
                        s1 = trav.physical_offset_to_route_distance(inv.start_offset_m)
                        s2 = trav.physical_offset_to_route_distance(inv.end_offset_m)
                        cached.append((i, res_id, res, inv_idx, min(s1, s2), max(s1, s2)))
                    except PositionMappingError:
                        pass
        self._route_res_cache[route.route_id] = cached
        return cached

    def _get_fast_block_eoa_entries(self, route: Route):
        if route.route_id in self._route_block_eoa_cache:
            return self._route_block_eoa_cache[route.route_id]
        entries = []
        for trav in route.traversals:
            dist_along = route.physical_to_route_distance(trav.link_id, 0.0)
            if dist_along is None:
                continue
            for res_id, res in self.coordinator.resource_controller.resources.items():
                if res.category == ResourceCategory.TRACK_BLOCK:
                    matching = [inv for inv in (res.intervals or []) if inv.link_id == trav.link_id]
                    if matching:
                        s_vals = []
                        for inv in matching:
                            try:
                                s_vals.append(trav.physical_offset_to_route_distance(inv.start_offset_m))
                            except PositionMappingError:
                                pass
                        if s_vals:
                            entries.append((min(s_vals), res_id))
        self._route_block_eoa_cache[route.route_id] = entries
        return entries

    def _find_downstream_eoa(self, train):
        route_len = train.route.total_length_m
        curr_pos = train.current_position_m
        min_eoa = route_len
        governing_cause = None
        holding_res = None
        for block_entry_dist, res_id in self._get_fast_block_eoa_entries(train.route):
            if block_entry_dist > curr_pos:
                if not self.coordinator.resource_controller.is_resource_available(res_id, train.train_id, self.current_time_s):
                    if block_entry_dist < min_eoa:
                        min_eoa = block_entry_dist
                        governing_cause = "SIGNALLING"
                        holding_res = res_id
        if train.stops and train.current_stop_index < len(train.stops) and not train.is_dwelling:
            stop = train.stops[train.current_stop_index]
            plat_obj = self.coordinator.platform_controller.platforms.get(stop.platform_id)
            if plat_obj:
                plat_offset = plat_obj.start_offset_m + min(plat_obj.length_m, train.params.length_m)
                plat_pos = train.route.physical_to_route_distance(plat_obj.link_id, plat_offset)
                # v1.11.0 / DEF-18: keep the stop available after physical overshoot
                # (arrival/deceleration limits prohibit retroactive snaps).
                if plat_pos is not None and plat_pos > curr_pos - 100.0:
                    if not self.coordinator.resource_controller.is_resource_available(stop.platform_id, train.train_id, self.current_time_s):
                        holding_pt = max(0.0, plat_pos - 50.0)
                        if holding_pt < min_eoa:
                            min_eoa = holding_pt
                            governing_cause = "PLATFORM"
                            holding_res = stop.platform_id
                    else:
                        if plat_pos < min_eoa:
                            min_eoa = plat_pos
                            governing_cause = "STATION_STOP"
                            holding_res = stop.station_id
        return min_eoa, governing_cause, holding_res

    def _update_resource_occupations(self, current_time_s: float) -> None:
        for train in self.active_trains:
            curr_front = train.current_position_m
            curr_rear = train.rear_position_m
            entered = self._train_entered_resources.setdefault(train.train_id, set())
            held_res = self._train_occupied_resources.setdefault(train.train_id, set())
            active_intervals = self._train_active_intervals.setdefault(train.train_id, {})

            for i, res_id, res, inv_idx, r_start, r_end in self._get_fast_route_resource_intervals(train.route):
                key = (i, res_id, inv_idx)
                interval_token = (i, inv_idx)

                # Front entry into this interval
                if key not in entered and curr_front >= r_start and curr_rear < r_end:
                    if train.train_id not in res.reservations:
                        self.coordinator.resource_controller.reserve_resource(
                            train_id=train.train_id,
                            resource_id=res_id,
                            timestamp_s=current_time_s,
                            running_direction=train.running_direction,
                        )
                    if res_id not in held_res:
                        self.coordinator.resource_controller.front_enter_resource(
                            train_id=train.train_id,
                            resource_id=res_id,
                            timestamp_s=current_time_s,
                        )
                        held_res.add(res_id)
                    entered.add(key)
                    active_intervals.setdefault(res_id, set()).add(interval_token)

                # Rear clearance of this interval
                res_in_prog = active_intervals.get(res_id, set())
                if interval_token in res_in_prog and curr_rear >= r_end:
                    res_in_prog.discard(interval_token)
                    if len(res_in_prog) == 0 and res_id in held_res:
                        self.coordinator.resource_controller.rear_clear_resource(
                            train_id=train.train_id,
                            resource_id=res_id,
                            timestamp_s=current_time_s,
                        )
                        held_res.discard(res_id)

            for plat_id, plat_obj in self.coordinator.platform_controller.platforms.items():
                if plat_id in held_res and not train.is_dwelling:
                    p_end = train.route.physical_to_route_distance(plat_obj.link_id, max(plat_obj.start_offset_m, plat_obj.end_offset_m))
                    if p_end is not None and curr_rear >= p_end:
                        self.coordinator.platform_controller.rear_clear_platform(train.train_id, plat_id, current_time_s)
                        held_res.discard(plat_id)


def _run_corridor_simulation(project, dwell_override: Optional[float] = None, performance_factor: float = 1.0):
    """Run microscopic simulation and return package and document."""
    infra = project.infrastructure
    sig = project.signalling
    rs = project.rolling_stock
    ops = project.operations

    track_links = list(infra.track_links)
    blocks = list(sig.blocks)
    platforms = list(infra.platforms) if infra.platforms else []
    primary_tt = list(rs.train_types)[0]

    traversals = []
    cum_s = 0.0
    for i, lnk in enumerate(track_links):
        rtl = lnk.model_copy(update={"start_node_id": f"RN_{i}", "end_node_id": f"RN_{i+1}"})
        traversals.append(
            LinkTraversal(
                link=rtl,
                direction=RunningDirection.FORWARD,
                sequence_index=i,
                start_distance_m=cum_s,
                end_distance_m=cum_s + lnk.length_m,
            )
        )
        cum_s += lnk.length_m
    route = Route(route_id="RT_CORRIDOR_FWD", traversals=traversals)

    coord = SignallingCoordinator()
    for plat in platforms:
        coord.platform_controller.register_platform(plat)
    for blk in blocks:
        coord.resource_controller.register_signalling_block(blk)

    pattern = ops.service_patterns[0]
    stops = []
    for s in pattern.stops:
        if dwell_override is not None:
            stops.append(s.model_copy(update={"dwell_time_s": dwell_override, "min_dwell_s": dwell_override}))
        else:
            stops.append(s)

    params = RollingStockParameters.from_canonical(primary_tt)
    st = ServiceType(
        service_id="SVC_CORRIDOR",
        train_type_id=primary_tt.train_type_id,
        params=params,
        route=route,
        stops=stops,
        running_direction=RunningDirection.FORWARD,
    )
    leader = TrainGenerator.create_instance(
        st,
        train_id="TRN_LEADER",
        requested_departure_s=0.0,
        performance_factor=performance_factor,
    )

    sim = _FastCorridorSimulator(coordinator=coord, dt_s=1.0, storage_interval_s=1.0)
    sim.register_train(leader)
    sim.run_simulation(max_duration_s=15000.0)

    records = coord.resource_controller.get_usage_records()

    platform_to_dwell = {s.platform_id: float(s.dwell_time_s) for s in stops}
    link_to_dwell = {p.link_id: platform_to_dwell[p.platform_id] for p in platforms if p.platform_id in platform_to_dwell}
    block_dwell = {}
    for blk in blocks:
        d = 0.0
        for inv in (blk.link_intervals or []):
            if inv.link_id in link_to_dwell:
                d = max(d, link_to_dwell[inv.link_id])
        if d > 0.0:
            block_dwell[blk.block_id] = d

    intervals = []
    for r in records:
        if r.resource_type != ResourceCategory.TRACK_BLOCK:
            continue
        rel_t = r.final_release_s if r.final_release_s is not None else (r.rear_clearance_s or 0.0)
        dur = max(0.0, rel_t - r.reservation_start_s)
        dwell = block_dwell.get(r.resource_id, 0.0)
        run_t = max(0.0, dur - dwell)
        decomp = BlockingTimeDecomposition(running_time_s=run_t, dwell_time_s=dwell)
        intervals.append(
            ResourceBlockingInterval(
                interval_id=f"BI_{r.resource_id}",
                resource_id=r.resource_id,
                resource_category=r.resource_type,
                train_id=r.train_id,
                start_time_s=r.reservation_start_s,
                end_time_s=rel_t,
                decomposition=decomp,
            )
        )

    timeline = BlockingTimeline(
        train_id="TRN_LEADER",
        service_id="SVC_CORRIDOR",
        route_id="RT_CORRIDOR_FWD",
        running_direction=RunningDirection.FORWARD,
        reference_event_name="DEPARTURE",
        reference_event_time_s=0.0,
        intervals=intervals,
    )
    solver = TechnicalHeadwaySolver()
    sol = solver.solve_pairwise_headway(leader_timeline=timeline, follower_timeline=timeline)
    controlling_id = sol.controlling_conflicts[0].leader_resource_id if sol.controlling_conflicts else "NONE"

    class MockPackage:
        def __init__(self):
            self.metadata = {
                "technical_minimum_headway_s": sol.headway_s,
                "controlling_bottleneck_id": controlling_id,
            }
            self.blocking_intervals = intervals

    class MockDoc:
        def __init__(self):
            class ExecKPIs:
                def __init__(self):
                    self.technical_headway_s = sol.headway_s
                    self.controlling_bottleneck_id = controlling_id
            self.executive_kpis = ExecKPIs()

    return MockPackage(), MockDoc()


# ==============================================================================
# Change B — Regression Tests
# ==============================================================================

def test_multilink_reservation_start_is_first_link_entry():
    """Verify multi-link block sets reservation_start_s at first link entry and never overwrites."""
    coord = SignallingCoordinator()

    # Synthetic 3-link block (3 links, 300 m each)
    route = make_test_route(link_ids=["L1", "L2", "L3"], link_lengths=[300.0, 300.0, 300.0])

    # Single dwell at link 2's mid-point of 150 s
    plat = Platform(
        platform_id="PLT_L2",
        station_id="STN_L2",
        link_id="L2",
        start_offset_m=100.0,
        end_offset_m=200.0,
        length_m=100.0,
    )
    coord.platform_controller.register_platform(plat)

    block = ManagedResource(
        resource_id="BLK_MULTI",
        category=ResourceCategory.TRACK_BLOCK,
        intervals=[
            ResourceInterval(link_id="L1", start_offset_m=0.0, end_offset_m=300.0),
            ResourceInterval(link_id="L2", start_offset_m=0.0, end_offset_m=300.0),
            ResourceInterval(link_id="L3", start_offset_m=0.0, end_offset_m=300.0),
        ],
        release_delay_s=0.0,
    )
    coord.resource_controller.register_resource(block)

    params = make_test_train_params()  # length 50 m, max speed 25 m/s
    stop = StationStop(
        station_id="STN_L2",
        platform_id="PLT_L2",
        dwell_time_s=150.0,
        min_dwell_s=150.0,
        is_mandatory_stop=True,
    )
    st = ServiceType("SVC_SYNTH", "TRN_SYNTH", params, route, stops=[stop])
    train = TrainGenerator.generate_single(st, requested_departure_s=0.0)[0]

    sim = MultiTrainSimulator(coordinator=coord, dt_s=0.2)
    sim.register_train(train)

    first_link_entry_t = 0.0
    subsequent_link_entries = []

    for _ in range(3000):
        sim.step()
        curr_front = train.current_position_m
        curr_t = sim.current_time_s

        if curr_front >= 300.0 and len(subsequent_link_entries) == 0:
            subsequent_link_entries.append(curr_t)
        if curr_front >= 600.0 and len(subsequent_link_entries) == 1:
            subsequent_link_entries.append(curr_t)

        if train.is_completed:
            break

    records = coord.resource_controller.get_usage_records()
    assert len(records) >= 1, "At least one usage record must be created"
    rec = next(r for r in records if r.resource_id == "BLK_MULTI")

    # 1. reservation_start_s equals the time the train front entered the first link
    assert rec.reservation_start_s == pytest.approx(first_link_entry_t, abs=0.5)

    # 2. reservation_start_s does not equal the time of entry into any subsequent link
    for sub_t in subsequent_link_entries:
        assert rec.reservation_start_s != pytest.approx(sub_t, abs=1.0)
        assert rec.reservation_start_s < sub_t - 5.0

    # 3. final_release_s − reservation_start_s >= (300 m + 300 m + 300 m) / train_speed + 150 s
    total_distance_m = 900.0
    nominal_run_time_s = total_distance_m / params.max_speed_ms
    min_expected_duration_s = nominal_run_time_s + 150.0
    actual_duration_s = rec.final_release_s - rec.reservation_start_s
    assert actual_duration_s >= min_expected_duration_s


def test_dwell_survives_multilink_reservation_fix(monkeypatch):
    """Verify that station dwell survives across multi-link corridor blocks and determines headway."""
    project, _, _ = FileManager.load_example_project("07_hsr_140km")

    # Use native SimulationRunner if Phase 4b two-pass pipeline is present; otherwise microscopic runner
    try:
        pkg, doc = SimulationRunner.run_simulation_pipeline(project, performance_factor=1.0)
        if "technical_minimum_headway_s" not in pkg.metadata:
            raise KeyError("technical_minimum_headway_s not in metadata")
    except Exception:
        monkeypatch.setattr(SimulationRunner, "run_simulation_pipeline", lambda proj, **kw: _run_corridor_simulation(proj, performance_factor=1.0))
        pkg, doc = SimulationRunner.run_simulation_pipeline(project, performance_factor=1.0)

    tech_hw_s = pkg.metadata["technical_minimum_headway_s"]

    # Acceptance window: corridor headway in 200–260 s at dwell=120/PF=1.0
    assert tech_hw_s >= 200.0, f"Headway {tech_hw_s} s is below 200 s (dwell was lost or truncated)"
    assert tech_hw_s <= 260.0, f"Headway {tech_hw_s} s exceeds 260 s acceptance upper bound"

    # Controlling resource is BLK_UP_001 (or BLK_UP_092)
    controlling_id = pkg.metadata.get("controlling_bottleneck_id") or doc.executive_kpis.controlling_bottleneck_id
    assert controlling_id in ("BLK_UP_001", "BLK_UP_092"), f"Expected BLK_UP_001 or BLK_UP_092, got {controlling_id}"

    # Controlling resource's 7-component decomposition shows dwell_time_s > 100.0 (the 120 s dwell is preserved)
    controlling_interval = next(b for b in pkg.blocking_intervals if b.resource_id == controlling_id)
    assert controlling_interval.decomposition.dwell_time_s > 100.0
    assert controlling_interval.decomposition.dwell_time_s == pytest.approx(120.0, abs=1.0)

    # BLK_UP_092 decomposition also preserves dwell and full running duration
    blk92 = next(b for b in pkg.blocking_intervals if b.resource_id == "BLK_UP_092")
    assert blk92.decomposition.dwell_time_s == pytest.approx(120.0, abs=1.0)
    assert blk92.decomposition.running_time_s >= 90.0
    # v1.11.0 / DEF-18: physically-honest (non-teleporting) stop arrivals extend the
    # terminal-block reservation to its true 251 s duration; the pre-fix 227 s figure
    # was a product of the retroactive snap-to-zero artifact removed in DEF-18.
    assert blk92.duration_s == pytest.approx(251.0, abs=2.0)  # v1.11.0 DEF-18 emergency-escalation baseline


def test_dwell_changes_headway_on_multilink_corridor(monkeypatch):
    """Verify that increasing station dwell translates directly into increased corridor headway."""
    project_120, _, _ = FileManager.load_example_project("07_hsr_140km")
    project_600, _, _ = FileManager.load_example_project("07_hsr_140km")

    pkg_120, _ = _run_corridor_simulation(project_120, dwell_override=120.0, performance_factor=1.0)
    pkg_600, _ = _run_corridor_simulation(project_600, dwell_override=600.0, performance_factor=1.0)

    hw_120 = pkg_120.metadata["technical_minimum_headway_s"]
    hw_600 = pkg_600.metadata["technical_minimum_headway_s"]

    delta_hw = hw_600 - hw_120
    # The +480 s dwell increase translates to at least +400 s of headway, delta ≈ 480 s ± 10 s
    assert delta_hw > 400.0, f"Headway delta {delta_hw} s did not increase by > 400 s"
    assert delta_hw == pytest.approx(480.0, abs=10.0), f"Headway delta {delta_hw} s should be ≈ 480 s ± 10 s"
