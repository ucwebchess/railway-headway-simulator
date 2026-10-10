# CHANGELOG
## Railway Headway & Capacity Simulator

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0-dev] - Milestone P08 (Current Milestone)

### Added
- **Blocking-Time Analysis & Seven-Component Decomposition (`headway.analysis.blocking_time`):**
  - Standardized half-open resource blocking interval model $B = [t_{\mathrm{start}}, t_{\mathrm{end}})$.
  - Seven non-overlapping additive components: Setup ($t_1$), Approach ($t_2$), Running ($t_3$), Dwell ($t_4$), Geometric Clearance ($t_5$), Residual Rear ($t_6$), and Release ($t_7$).
  - Additive reconciliation ($T_{\mathrm{blocking}} = \sum_{k=1}^7 t_k$) with discrepancy and gap reporting.
  - Event-derived and usage-record-derived timeline builders (`BlockingTimeline`).
- **Resource Conflict Detection (`headway.analysis.conflict_detection`):**
  - `ConflictDetector` evaluating ordered leader–follower incompatible resource pairs.
  - Conflict classifications: `IDENTICAL_RESOURCE`, `SHARED_CONFLICT_GROUP`, `INTERLOCKING_CONFLICT`, `STATION_PLATFORM_CONFLICT`, `RESIDUAL_REAR_CONFLICT`, `WHOLE_TUNNEL_CONFLICT`.
  - Analytical temporal shift calculation: $H_{u,v} = t_{\mathrm{leader-release}, u} - t_{\mathrm{follower-start}, v} + \text{margin}$.
- **Bottlenecks & Slack Margins (`headway.analysis.bottlenecks`):**
  - Slack calculation ($S_k = H_{\min} - H_k$) and controlling bottleneck detection ($S_k \le \text{tolerance}$).
  - Bottleneck categorization: `OPEN_LINE_BLOCK`, `STATION_APPROACH`, `PLATFORM`, `RESIDUAL_REAR_OCCUPATION`, `JUNCTION_MERGE`, `JUNCTION_CROSSOVER`, `INTERLOCKING_ROUTE`, `TVS_SECTION`, `SHARED_TVS_GROUP`, `WHOLE_TUNNEL`.
  - Conflict ranking (descending order of required headway).
  - Standalone longest resource occupation ranking ($T_{\mathrm{blocking}} = t_{\mathrm{release}} - t_{\mathrm{start}}$).
- **Technical Minimum Headway Solvers (`headway.analysis.headway_solver` & `headway_search`):**
  - `TechnicalHeadwaySolver` calculating $H_{\min} = \max(H_{\mathrm{dispatch}}, \max H_{u,v})$.
  - Minimum dispatch separation clamping ($H \ge H_{\mathrm{dispatch-min}}$).
  - Microscopic joint simulation verification of calculated headways (`verify_with_joint_simulation`).
  - Iterative numerical bisection search (`IterativeHeadwaySearch`) converging to $\le 0.1\text{ s}$ tolerance.
- **Directional Mixed-Traffic Headway Matrices (`headway.analysis.mixed_traffic`):**
  - $N \times N$ matrix evaluation across ordered service pairs preserving asymmetry ($H(i, j) \ne H(j, i)$).
  - Separate matrices for `RunningDirection.FORWARD` and `RunningDirection.REVERSE`.
  - Export to pandas DataFrame with leader rows and follower columns.
- **Verification Benchmarks & Tests (`tests/engineering/`, `tests/unit/`, `tests/integration/`):**
  - Analytical Benchmarks P08-B001 (pairwise 115s), P08-B002 (blocking duration 84s), P08-B003 (7-component 84s), P08-B004 (matrix asymmetry 150s/110s), P08-B005 (TVS 213s).
  - Heterogeneous train pairs, station dwell, residual rear occupation, junction merge, and TVS constraint benchmarks.
  - Unit negative tests and end-to-end integration tests.

---

## [0.1.0-dev] - Milestone P07

### Added
- **Stations, Platforms & Multi-Platform Allocation (`headway.signalling.platform_controller`):**
  - Canonical station and platform resource lifecycle under `ResourceCategory.PLATFORM`.
  - Usable platform length compatibility check ($L_{\mathrm{train}} \le L_{\mathrm{platform}}$).
  - Exclusive platform reservations, front entry, stationary dwell start/end lifecycle, and rear-clearance-based release delay timers.
  - Strict release invariant: platforms are strictly prohibited from releasing upon dwell completion or front exit.
  - Deterministic multi-platform allocation engine (`FIXED_ASSIGNMENT`, `PREFERRED_WITH_ALTERNATIVES`, `EARLIEST_FEASIBLE`).
- **Residual Stationary Rear Occupation (`headway.signalling.residual_occupation`):**
  - Geometric detection of rear infringement into upstream resources ($d_{\mathrm{infringement}} = \max(0, x_{\mathrm{boundary}} - x_{\mathrm{rear}})$).
  - Stationary dwell duration ($180.0\text{ s}$) keeping upstream resource physically occupied throughout dwell.
  - Post-departure moving clearance time calculation ($t = \sqrt{2 \cdot d / a} \approx 14.142\text{ s}$).
  - Full support for both FORWARD and REVERSE railway movements.
- **Junction & Crossover Control (`headway.signalling.junction_controller`):**
  - Merge, diverge, crossover, and diamond crossing conflict prevention.
  - Dynamic switch alignment and route locking through `SwitchController` and `InterlockingEngine`.
  - Sectional release of junction zones and switches upon train-rear clearance.
- **Tunnel Ventilation Section (TVS) Control Engine (`headway.signalling.tvs_controller`):**
  - Canonical TVS resource model with independent chainage boundaries from signalling blocks.
  - Single-train rule ($N_{\max} = 1$) with configurable exclusivity scopes: `PER_TRACK`, `CROSS_TRACK_SHARED_TVS`, and `WHOLE_TUNNEL`.
  - TVS entry request authorization gate with processing delay $t_{\mathrm{auth\_delay}}$.
  - TVS entry holding point and MA clamping when unauthorized; automatic unclamping once authorized.
  - Consecutive TVS multi-section dual occupancy.
  - Post-clearance release delay timers and safety invariant enforcement.
- **Verification Benchmarks & Tests (`tests/engineering/`, `tests/unit/`, `tests/integration/`):**
  - 35 engineering benchmarks (`P07-B001` through `P07-B035`) including numerical benchmarks A, B, C, D.
  - 14 negative unit tests and 4 corridor integration tests.

---

## [0.1.0-dev] - Milestone P06
  - `SignallingModelFidelity` enum (`BASIC`, `INTERMEDIATE`, `DETAILED`) defining simulation fidelity levels.
  - `TrainIntegrityStatus` enum (`CONFIRMED`, `UNCONFIRMED`, `LOST`) for on-board train integrity tracking.
  - `RadioCommunicationConfig` model with decomposed latencies ($t_{\mathrm{uplink}}$, $t_{\mathrm{proc}}$, $t_{\mathrm{downlink}}$), total latency property, and timeout enforcement.
  - `TrainPositionReport` model supporting periodic reports with speed, coordinates, localization uncertainty, and age calculation.
  - `SupervisionProfile` and `SupervisionState` (`NORMAL`, `INDICATION`, `WARNING`, `INTERVENTION`) contracts.
  - `ProtectedTrainEnvelope` model capturing conservative moving-block spatial envelopes.
  - `AdvancedSignallingEngine` abstract base class standardizing train registration, position report ingestion, MA calculation, and braking supervision.
  - Standardized advanced signalling exceptions: `AdvancedSignallingError`, `CommunicationTimeoutError`, `PositionReportError`, `SupervisionInterventionError`, `ProtectedEnvelopeError`.
  - Standardized advanced signalling event types in `ResourceEventType`: `RADIO_MESSAGE_SENT`, `RADIO_MESSAGE_RECEIVED`, `POSITION_REPORT_RECEIVED`, `SUPERVISION_WARNING`, `SUPERVISION_INTERVENTION`, `COMMUNICATION_TIMEOUT`, `ENVELOPE_UPDATED`, `MA_EXTENDED`.
- **ETCS Level 2 Engineering Model (`headway.signalling.etcs`):**
  - `ETCSLevel2Config` with fidelity selection, radio communication configuration, and supervision margins.
  - `RadioBlockCentre` (RBC) integrating fixed-block detection from P05 `ResourceController` and route locking from `InterlockingEngine`.
  - Realistic communication latency model: Controlled Benchmark C verification ($t_{\mathrm{effective}} = 101.0\text{ s}$ from $t_{\mathrm{issue}} = 100.0\text{ s}$ and $t_{\mathrm{comm}} = 1.0\text{ s}$).
  - Movement Authority (MA) issuance up to first occupied block / signal / EoA, with continuous extension upon block clearance.
  - Multi-stage braking supervision curves (Indication, Permitted, Warning, Intervention/Emergency): Controlled Benchmark A verification ($d = 600.0\text{ m}$ for $v_0 = 30\text{ m/s}$ at $b = 0.75\text{ m/s}^2$).
  - Overlap / Danger Point protection: Supervised Location ($SvL$) extending beyond EoA by $d_{\mathrm{overlap}}$.
  - P04 `BrakingTarget` conversion and stopping feasibility validation.
  - Communication timeout detection and automatic session loss handling.
  - Bidirectional invariance across FORWARD and REVERSE railway routes.
- **CBTC Moving-Block Engineering Model (`headway.signalling.cbtc`):**
  - `CBTCConfig` supporting configurable update intervals, odometry drift rates, and safety buffers.
  - `ProtectedTrainEnvelopeCalculator` calculating leader train conservative envelope ($x_{\mathrm{protected}}$) accounting for report age, localization uncertainty, train integrity status, and safety margins: Controlled Benchmark B verification ($x_{\mathrm{protected}} = 1970.0\text{ m}$).
  - `CBTCMovingBlockEngine` managing moving-block train separation without wayside fixed blocks.
  - Dynamic Movement Authority generation and continuous downstream extension tracking moving leaders.
  - Dynamic follower braking protection using P04 braking models.
  - Fixed infrastructure restrictions (`P06-CBTC-RES`): interlocking route boundaries, switch locking enforcement, and station dwell limits.
  - Symmetric forward and reverse moving-block train separation.
- **Master Signalling Coordinator (`headway.signalling.coordinator`):**
  - Integration of `technology_type` supporting fixed-block, ETCS Level 2, and CBTC moving block in a unified coordinator.
- **Verification Benchmarks & Tests (`tests/engineering/`, `tests/unit/`, `tests/integration/`):**
  - 30 comprehensive engineering benchmarks (`P06-B001` through `P06-B030`) including Controlled Benchmarks A, B, and C.
  - 18 negative tests rejecting invalid latencies, negative coordinates, timeouts, non-monotonic extensions, and infeasible braking.
  - 3 end-to-end integration tests verifying multi-train flows on bidirectional corridors.

---

## [0.1.0-dev] - Milestone P05

### Added
- **Resource Management, Interlocking & Fixed-Block Signalling (`headway.signalling`):**
  - Canonical resource categories and decoupled state model (`ManagedResource`, `ResourceController`).
  - Switch throw delay, locking, and position tracking (`SwitchController`).
  - Interlocking route formation, atomic locking, complete release, and sectional release (`InterlockingEngine`).
  - 2-, 3-, and 4-aspect signal evaluations with sighting distance (`SignalAspectController`).
  - Standardized Movement Authority (MA) contracts and lifecycle management (`MovementAuthorityController`).
  - Braking protection envelope and P04 `BrakingTarget` conversion (`BrakingProtectionEngine`).
  - Master 11-step deterministic same-time event coordinator (`SignallingCoordinator`).
  - 30 engineering benchmarks (`P05-B001` through `P05-B030`).

---

## [0.1.0-dev] - Milestone P04

### Added
- **Rolling Stock Braking Models & Numerical Solver (`headway.rolling_stock.braking`, `headway.simulation`):**
  - Constant deceleration and piecewise linear speed-dependent braking curves.
  - Net effective deceleration vs brake-generated deceleration distinction.
  - Numerical integration engine using 4th-order Runge-Kutta and adaptive stepping.
  - Boundary crossing event localization and directional speed profile generation.
  - 22 engineering benchmarks (`BENCH-P04-001` through `BENCH-P04-022`).

---

## [0.1.0-dev] - Milestone P03

### Added
- **Rolling Stock Parameters & Mass Engine (`headway.rolling_stock.train`):**
  - `RollingStockParameters` model capturing dimensions, mass conditions, kinematic limits, rotating mass factor $\lambda$, and adhesion properties.
  - Three operational mass conditions: `EMPTY` (tare mass), `NOMINAL` (standard design load), and `MAXIMUM` (crush payload).
  - Equivalent dynamic mass calculation $m_{\text{eq}} = m(1 + \lambda)$ separating gravitational physical mass from acceleration mass.
  - `TrainFormation` model supporting multi-vehicle consists with aggregated length, mass, and governing minimum speed limit.
- **Traction and Adhesion Physics Engine (`headway.rolling_stock.traction`):**
  - `SimplifiedTractionModel`: Hyperbolic model $F_t(v) = \min(F_{\max}, P_{\max}/v)$ with division-by-zero protection at standstill ($F_t(0) = F_{\max}$).
  - `DetailedTractionCurveModel`: Piecewise linear interpolation of $(v, F_t)$ points with strict validation of monotonicity and documented boundary clamping.
  - Operational acceleration limit enforcement ($F_t \le m_{\text{eq}} \cdot a_{\max}$) and mechanical power verification ($P \le P_{\max}$).
  - Adhesion limit model $F_{\text{adh}} = \mu \cdot m_{\text{adh}} \cdot g$ with explicit adhesive mass fraction and direction invariance.
- **Authoritative Running, Gradient & Curvature Resistance (`headway.rolling_stock.resistance`):**
  - `DavisResistanceModel`: SI-unit polynomial evaluation $R_D(v) = A + Bv + Cv^2$ with strict non-negativity and standstill evaluation $R_D(0) = A$.
  - `GradientResistanceModel`: Small-gradient approximation $F_g = m g i$ with strict direction awareness and sign inversion in reverse ($F_{g,\text{rev}} = -F_{g,\text{fwd}}$).
  - `CurvatureResistanceModel`: Roeckl formula $W_c = 650/(R - 55)$‰ for $R \ge 300\text{ m}$, tangent track ($F_c = 0$), and non-negative direction invariance.
  - `DistributedResistanceEngine`: Mass-weighted integration over full train length $L_{\text{train}}$ across multi-link alignments and route boundary conditions.
- **Longitudinal Force Balance & Instantaneous Acceleration (`headway.rolling_stock.force_balance`):**
  - Net force equation $F_{\text{net}} = F_t - F_b - F_D - F_g - F_c$ and equivalent acceleration $a = F_{\text{net}} / m_{\text{eq}}$.
  - Instantaneous operational modes (`ACCELERATING`, `CRUISING`, `COASTING`, `BRAKING`, `STANDSTILL`).
  - Target deceleration to required braking force conversion ($F_b = m_{\text{eq}} d - \sum R$).
  - Operational acceleration and emergency deceleration capping.
- **Rolling Stock Diagnostics & Tabular Adapters (`headway.rolling_stock.diagnostics`):**
  - Performance sweep generator across speed ranges $[0, v_{\max}]$, evaluating forces, mechanical power, resistances, and net acceleration.
  - Steady-state balancing speed solver ($F_t(v) = R_{\text{tot}}(v)$) using bisection.
  - Tabular dictionary/DataFrame export adapters for frontend integration in P13/P14.
- **Engineering Validator (`headway.rolling_stock.validator`):**
  - Semantic and kinematic validation for canonical `TrainType` and `RollingStockParameters`.
  - Integration with P01 `ValidationReport` and `ValidationFinding`.
- **Engineering Benchmarks (`tests/engineering/test_rolling_stock_benchmarks.py`):**
  - Complete test suite for all 25 mandatory benchmarks (`P03-B001` through `P03-B025`), achieving 100% verification.

---

## [0.1.0-dev] - Milestone P02

### Added
- **Permanent Forward & Reverse Operation Architecture (`headway.infrastructure.direction`):**
  - `RunningDirection` enum (`FORWARD`, `REVERSE`) with inversion (`opposite()`) and helper predicates.
  - `DirectionPolicy` enforcing track directionality rules (`BIDIRECTIONAL`, `NOMINAL` / forward-only, `REVERSE` / reverse-only).
- **Physical Network Graph Engine (`headway.infrastructure.graph`):**
  - Directed multi-graph topology on NetworkX (`MultiDiGraph`).
  - Strict preservation of physical link singularity without duplicate instances.
  - Support for parallel physical links connecting identical node pairs.
- **Physical Route Engine (`headway.infrastructure.route`):**
  - Ordered sequence of `LinkTraversal`s with continuity verification.
  - Cumulative route distance $s \in [0, L_{\text{route}}]$ strictly increasing in running direction.
  - Forward and reverse position mapping: local $x_{\text{physical}} = s$ for forward, $x_{\text{physical}} = L - s$ for reverse.
  - Reverse lookup with occurrence indexing for looped routes.
  - Automatic reverse route generation (`create_reverse_route`) with policy validation.
- **Engineering Chainage Mapping (`headway.infrastructure.chainage`):**
  - Piecewise linear mapping independent of cumulative route distance.
  - Support for forward increasing and reverse decreasing chainage, as well as chainage equations/discontinuities.
- **Vertical and Horizontal Alignment Profiles (`headway.infrastructure.alignment`):**
  - Direction-aware gradient profiles with sign inversion (+10‰ forward becomes -10‰ in reverse).
  - Curvature profiles preserving non-negative radius magnitudes under Roeckl curvature formulas.
  - Multi-section intersection queries for distributed train length resistance calculations in P03.
- **Directional Speed Profile Engine (`headway.infrastructure.speed`):**
  - `SpeedRestriction` model with direction filtering (`FORWARD`, `REVERSE`, `BOTH`) and train category filtering.
  - Continuous `RouteSpeedProfile` with governing minimum speed across overlapping restrictions.
- **Switch & Junction Topology (`headway.infrastructure.switches`):**
  - Explicit permitted entry/exit link combinations and switch positions (`NORMAL`, `REVERSE`).
  - Directional validation ensuring forward permission does not imply reverse permission without explicit authorization.
- **Station & Platform Geometry (`headway.infrastructure.stations`):**
  - Physical platform intervals and stopping points mapped along routes.
  - Direction-aware station arrival sequence and stopping position resolution.
  - Usable platform length validation and train footprint accommodation checks.
- **Tunnel & TVS Geometry Engine (`headway.infrastructure.tunnels`):**
  - Tunnel and TVS physical geometry independent of signalling blocks.
  - Invariant physical TVS boundaries with direction-reversed entry and exit resolution.
  - Geometric TVS length calculation.
- **Multi-Link & Branching Resource Geometry (`headway.infrastructure.resources`):**
  - Spatially continuous, disjoint, and branching physical resource intervals.
  - Spatial intersection detection and occupied length calculation across arbitrary route intervals.
- **Train Footprint Geometry Utilities (`headway.infrastructure.train_geometry`):**
  - Train footprint calculation across multi-link routes with boundary condition tracking without silent truncation.
  - Footprint distribution across intersecting links for both forward and reverse running.
- **Infrastructure Validation (`headway.infrastructure.validator`):**
  - Comprehensive structural and engineering validation integrated with P01 `ValidationReport`.
  - Direction-specific route feasibility reporting (independent forward vs reverse checks).
- **Infrastructure Preprocessing & Caching (`headway.infrastructure.preprocessor`):**
  - Consolidated `RouteProfile` data structures with deterministic caching keyed by `(dataset_hash, route_id, running_direction)`.
  - Baseline immutability preservation.
- **Visualization Data Adapters (`headway.infrastructure.adapters`):**
  - Structured Pandas DataFrame exporters for nodes, traversals, gradients, curves, speed limits, stations, and TVS sections in running order.
- **Engineering Benchmark Verification (`tests/engineering/test_infrastructure_benchmarks.py`):**
  - Verified benchmarks `BENCH-P02-001` through `BENCH-P02-010`.

---

## [0.1.0-dev] - Milestone CI

### Added
- **Automated Testing Workflow (`.github/workflows/python-tests.yml`):**
  - GitHub Actions CI workflow executing pytest across `unit`, `integration`, `engineering`, `regression`, and `end_to_end` categories.
  - Pinned action commit SHAs for supply-chain security (`actions/checkout`, `actions/setup-python`).
  - Python 3.11 environment with pip dependency caching.

---

## [0.1.0-dev] - Milestone P01

### Added
- Centralized Units and Normalization (`headway.core.units`).
- Identifier Management (`headway.core.identifiers`).
- Canonical Data Models (`headway.data.canonical`).
- JSON Schema Draft 2020-12 Artifacts (`schemas/`).
- Authoritative Excel Schema Registry (`headway.data.excel_registry`).
- Excel Template Generator (`headway.data.template_generator`).
- Excel Importer (`headway.data.importer`).
- Multi-Level Validation Framework (`headway.data.validator`, `headway.data.validation`).
- Raw-to-Canonical Converter (`headway.data.converter`).
- Deterministic Serialization & Hashing (`headway.data.serializer`, `headway.data.hashing`).
- Scenario Foundation (`headway.scenarios.engine`).
- Project Packaging (`headway.data.package`).
- Official Example Datasets (`examples/`).

---

## [0.1.0-dev] - Milestone P00 Baseline

### Added
- Package foundation (`src/headway/core`, `ui`, subpackage scaffolds).
- Application configuration, logging, and structured exceptions.
- Gradio Blocks UI shell with 10 navigation tabs and reference report styling.
- Google Colab launcher notebook (`colab/Railway_Headway_Simulator.ipynb`).
- Initial documentation suite and automated pytest framework.
