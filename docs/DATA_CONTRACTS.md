# CANONICAL DATA CONTRACTS
## Railway Headway & Capacity Simulator

**Document ID:** RHS-DATA-001  
**Version:** 1.0.0  
**Status:** IMPLEMENTED & VERIFIED (Milestone P01)  
**Governing Prompt:** RHS-P01-001  
**JSON Schema Specification:** JSON Schema Draft 2020-12  

---

### 1. Architectural Purpose

The simulation engine strictly decouples itself from external file formats (Excel, CSV, proprietary simulation exports). All external inputs are ingested, validated, normalized to pure SI units, and converted into immutable, strongly typed Pydantic canonical models (`headway.data.canonical.CanonicalProject`).

---

### 2. Standard Engineering Units (SI Normalization Contract)

All canonical models strictly store and compute values in standard SI units:
- **Distance:** meters ($m$)
- **Speed:** meters per second ($m/s$)
- **Mass:** kilograms ($kg$)
- **Force:** Newtons ($N$)
- **Power:** Watts ($W$)
- **Energy:** Joules ($J$)
- **Time:** seconds ($s$)
- **Acceleration / Deceleration:** meters per second squared ($m/s^2$)
- **Gradient:** dimensionless decimal ($m/m$)
- **Curve Radius:** meters ($m$)

---

### 3. Canonical Domain Models

The canonical data architecture is implemented in `headway.data.canonical` and comprises:

#### 3.1 Infrastructure Domain
- `Node`: Vertex in track topology (`node_id`, `node_type`).
- `Track`: Railway track line (`track_id`, `directionality`).
- `TrackLink`: 1D continuous track segment (`link_id`, `track_id`, `start_node_id`, `end_node_id`, `length_m`, `max_speed_ms`, `gradient_decimal`, `curvature_radius_m`).
- `Station` & `Platform`: Passenger facilities and boarding platforms (`station_id`, `platform_id`, `link_id`, `start_offset_m`, `end_offset_m`, `length_m`).
- `StoppingPoint`: Train stopping target along platform (`stopping_point_id`, `offset_m`).
- `Tunnel`: Tunnel structure (`tunnel_id`, `name`).
- `TVSSection`: Tunnel Ventilation Section enforcing single-train occupancy rule (`tvs_id`, `link_intervals`, `max_train_occupancy=1`, `holding_signal_id`, `release_delay_s`).
- `SharedResourceGroup`: Mutually exclusive resource group (`group_id`, `resource_ids`).

#### 3.2 Rolling Stock Domain
- `TrainType`: Rolling stock characteristics (`train_type_id`, `length_m`, `mass_empty_kg`, `mass_loaded_kg`, `rotating_mass_factor`, `max_speed_ms`, `max_service_deceleration_ms2`, `emergency_deceleration_ms2`).
- `TractionModel`: Simplified power/force limit or detailed speed-force curve (`TractionCurvePoint`).
- `BrakingModel`: Constant deceleration or speed-dependent deceleration curve (`BrakingCurvePoint`) with declared semantics (`NET_EFFECTIVE` or `BRAKE_GENERATED`).
- `DavisResistance`: Normalized polynomial resistance coefficients $A$ (N), $B$ (N*s/m), $C$ (N*s²/m²).

#### 3.3 Signalling Domain
- `SignallingSystem`: System rules (`technology_type`, `aspect_model`, `default_overlap_m`, `sighting_time_s`, `route_setup_time_s`, `release_delay_s`).
- `Signal`: Wayside signals and marker boards (`signal_id`, `link_id`, `offset_m`, `direction`, `signal_type`, `sighting_distance_m`).
- `SignallingBlock`: Fixed signalling blocks (`block_id`, `entry_signal_id`, `exit_signal_id`, `link_intervals`, `overlap_m`, `release_delay_s`).
- `InterlockingRoute`: Locked route paths (`route_id`, `entry_signal_id`, `exit_signal_id`, `link_sequence`, `protected_blocks`, `conflicting_route_ids`).

#### 3.4 Operations Domain
- `ServicePattern`: Train service pattern (`service_pattern_id`, `train_type_id`, `route_link_sequence`, `priority`, `planned_headway_s`).
- `StationStop`: Sequence of scheduled passenger dwells (`station_id`, `platform_id`, `dwell_time_s`, `min_dwell_s`, `is_mandatory_stop`).

#### 3.5 Analysis Domain
- `AnalysisConfig`: Simulation analysis run (`analysis_id`, `analysis_type`, `leader_service_id`, `follower_service_id`, `integration_step_s`, `headway_tolerance_s`, `search_time_window_s`, `planning_margin_s`, `reference_link_id`, `reference_offset_m`).

#### 3.6 Scenarios Domain
- `Scenario`: Baseline or alternative scenario (`scenario_id`, `is_baseline`, `overrides`).
- `ScenarioOverride`: Scalar parameter override (`target_domain`, `target_object_id`, `parameter_name`, `override_value`).

---

### 4. Canonical JSON Schemas (Draft 2020-12)

All 16 machine-readable schemas reside in `schemas/` and are validated using Draft 2020-12:
1. `project.schema.json`
2. `infrastructure.schema.json`
3. `network_position.schema.json`
4. `resource_geometry.schema.json`
5. `resource.schema.json`
6. `signalling.schema.json`
7. `rolling_stock.schema.json`
8. `operations.schema.json`
9. `analysis.schema.json`
10. `scenario.schema.json`
11. `event.schema.json`
12. `resource_usage.schema.json`
13. `headway_result.schema.json`
14. `capacity_result.schema.json`
15. `tvs_result.schema.json`
16. `report_result.schema.json`
