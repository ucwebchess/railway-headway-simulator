# CHANGELOG
## Railway Headway & Capacity Simulator

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0-dev] - Milestone P02 (Current Milestone)

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
