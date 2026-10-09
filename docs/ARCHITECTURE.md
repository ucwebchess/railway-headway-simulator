# SOFTWARE ARCHITECTURE SPECIFICATION
## Railway Headway & Capacity Simulator

**Document ID:** RHS-ARCH-001  
**Version:** 1.2.0  
**Status:** UPDATED (Milestone P02 Infrastructure Engine Integrated)  
**Governing Prompt:** RHS-MASTER-001 § 4; RHS-P01-001; RHS-P02-001  

---

### 1. Architectural Principles

The Railway Headway & Capacity Simulator is organized as a layered, modular Python package (`headway`).

Key design rules:
1. **Decoupled User Interface:** The simulation engine, data models, infrastructure network, and reporting subsystems are completely independent of Gradio.
2. **Permanent Forward and Reverse Support:** The infrastructure engine supports both FORWARD and REVERSE railway operations across all components from the beginning without duplicating physical link identities.
3. **Unidirectional Layered Flow:** Dependencies flow strictly downward from high-level orchestrators to low-level core services. Circular imports are strictly forbidden.
4. **Data Pipeline Separation:** The data layer cleanly separates Excel reading (`importer.py`), validation (`validator.py`), normalization (`converter.py`), serialization (`serializer.py`), hashing (`hashing.py`), and project archive packaging (`package.py`).
5. **Google Colab Launcher:** The Colab Jupyter Notebook (`colab/Railway_Headway_Simulator.ipynb`) serves purely as a launcher and bootstrap environment.

---

### 2. Subsystem Layout & Module Responsibilities

```text
src/headway/
├── core/               # Application configuration, logging, exceptions, version, units, identifiers
│   ├── configuration.py    # AppConfig, DirectoryConfig, GradioServerConfig
│   ├── exceptions.py       # HeadwayError hierarchy and UI sanitization
│   ├── identifiers.py      # Identifier normalization, syntax checks, duplicate detection
│   ├── logging_config.py   # Centralized contextual logging
│   ├── units.py            # Centralized unit normalization (SI) and Davis coefficient conversion
│   └── version.py          # Single authoritative version source (0.1.0-dev)
│
├── data/               # Excel ingestion, validation, canonical contracts, packaging (P01)
│   ├── canonical.py        # Strongly typed Pydantic models with SI internal units
│   ├── converter.py        # Raw workbook to CanonicalProject conversion
│   ├── excel_registry.py   # Single authoritative registry for templates and importers
│   ├── hashing.py          # SHA-256 cryptographic hashing (source, canonical, scenario)
│   ├── importer.py         # Openpyxl workbook parser and Level 1/2 field extractor
│   ├── package.py          # Safe project ZIP package exporter and importer
│   ├── serializer.py       # Deterministic JSON serializer and Draft 2020-12 validator
│   ├── template_generator.py# Generates the 6 standardized Excel template workbooks
│   ├── validation.py       # ValidationFinding and ValidationReport data structures
│   └── validator.py        # Multi-level validation engine (Levels 3, 4, 5)
│
├── scenarios/          # Scenario management and parameter overrides (P01/P12)
│   └── engine.py           # Baseline immutability and isolated parameter overrides
│
├── infrastructure/     # 1D topological track graph, links, nodes, switches, TVS sections (P02)
│   ├── adapters.py         # Visualization data adapters for UI and diagrams
│   ├── alignment.py        # Route alignment profiles (gradients with sign reversal, curvature)
│   ├── chainage.py         # Engineering chainage mapping (forward, reverse, equations)
│   ├── direction.py        # RunningDirection enum (FORWARD, REVERSE) and DirectionPolicy
│   ├── graph.py            # PhysicalNetworkGraph with NetworkX MultiDiGraph
│   ├── preprocessor.py     # Direction-aware RouteProfile compiler with deterministic caching
│   ├── resources.py        # Multi-link, continuous, disjoint, and branching resource geometry
│   ├── route.py            # LinkTraversal, Route, RouteEngine, forward and reverse position lookups
│   ├── speed.py            # RouteSpeedProfile with direction-filtered SpeedRestrictions
│   ├── stations.py         # StationPlatformModel, stopping points, and platform coverage checks
│   ├── switches.py         # Switch, SwitchMovement, and JunctionTopology models
│   ├── train_geometry.py   # TrainFootprint, multi-link distribution, and boundary handling
│   ├── tunnels.py          # TunnelTVSModel with invariant physical TVS and reversed entry/exit
│   └── validator.py        # InfrastructureValidator integrated with ValidationReport
│
├── rolling_stock/      # Train physical characteristics, Davis resistance, traction curves (P03)
├── signalling/         # Fixed-block, ETCS L2, CBTC models, interlocking routes (P05/P06)
├── simulation/         # 0.1s microscopic numerical motion solver (P04/P07/P09)
├── analysis/           # 7-component blocking time, pairwise headway H(i,j), capacity engine (P08/P10/P11)
├── reporting/          # Reference-standard PDF, HTML, Excel reports and Plotly figures (P13/P14)
└── ui/                 # Gradio user interface subsystem (P00/P15)
```

---

### 3. Infrastructure Subsystem Architecture (P02)

```text
       Canonical InfrastructureModel (P01)
                     │
                     ▼
           PhysicalNetworkGraph
         (NetworkX MultiDiGraph)
      ├── Single Physical Link Identity
      ├── Parallel Physical Link Support
      └── Directed Traversal Views
                     │
                     ▼
                 RouteEngine
      ├── LinkTraversal (FORWARD / REVERSE)
      ├── Node-to-Node Continuity Verification
      ├── Cumulative Route Distance: s ∈ [0, L_route]
      └── Reverse Route Derivation: create_reverse_route()
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
RouteAlignment  RouteSpeedProfile RouteStationTVS
 ├── Gradient    ├── Direction     ├── Platforms & Stops
 │   Inversion   │   Filtering     ├── TVS Entry/Exit
 └── Curvature   └── Governing Min └── Resource Intersections
     Invariance
                     │
                     ▼
          InfrastructurePreprocessor
       ├── Direction-Aware RouteProfile
       ├── Deterministic Caching (Hash + Route + Dir)
       └── Immutability of Physical Baseline
```
