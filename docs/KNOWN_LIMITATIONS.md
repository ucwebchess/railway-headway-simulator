# KNOWN LIMITATIONS REGISTER
## Railway Headway & Capacity Simulator

**Software Version:** `0.1.0-dev`  
**Milestone:** `P02 — Railway Infrastructure & Network Topology Engine`  
**Authority:** RHS-MASTER-001 § 3; RHS-P01-001; RHS-P02-001 § 29  

---

### 1. Statement of Milestone Scope Limitation

**MILESTONE P02 IS STRICTLY A PHYSICAL INFRASTRUCTURE, NETWORK GRAPH, ROUTE TOPOLOGY, AND GEOMETRY ENGINE PHASE.**

In strict compliance with **RHS-P02-001 § 29 (Critical Prohibitions)**:
No train acceleration or braking physics, microscopic motion solver, signalling aspect logic, movement authority calculation, interlocking state transitions, TVS entry authorization, technical headway calculations, or line capacity evaluations were introduced during P02. The objective of P02 was to establish the physical railway infrastructure network engine supporting both FORWARD and REVERSE railway operations across all components.

---

### 2. Status of Functional Subsystems

| Subsystem Domain | Milestone P01 Status | Milestone P02 Status | Scheduled Resolution |
|---|---|---|---|
| **Excel Engineering Ingestion** | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Canonical Data Models & SI Normalization** | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Data Validation Pipeline (Levels 1–5)** | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Project Packaging (ZIP Import/Export)** | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Scenario Overrides & Baseline Immutability** | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 / P12 |
| **1D Infrastructure Graph & Pathfinding** | Unsupported | **FULLY IMPLEMENTED** (NetworkX MultiDiGraph, parallel links) | Milestone P02 |
| **Forward & Reverse Route Traversal Engine** | Unsupported | **FULLY IMPLEMENTED** (Continuous distance, coordinate mapping) | Milestone P02 |
| **Direction-Aware Track Alignment & Speed** | Unsupported | **FULLY IMPLEMENTED** (Gradient sign reversal, speed profiles) | Milestone P02 |
| **Stations, Platforms & TVS Geometry** | Unsupported | **FULLY IMPLEMENTED** (Physical geometry, reverse entry/exit) | Milestone P02 |
| **Multi-Link Resources & Train Footprint** | Unsupported | **FULLY IMPLEMENTED** (Link distribution, boundary handling) | Milestone P02 |
| **Rolling Stock Physics & Dynamics Curves** | Unsupported | Unsupported (Dynamics equations belong to P03) | Milestone P03 |
| **Braking Models & Microscopic Motion Solver** | Unsupported | Unsupported (0.1s numerical solver belongs to P04) | Milestone P04 |
| **Fixed-Block Signalling & Aspect Logic** | Unsupported | Unsupported (Signalling engine belongs to P05) | Milestone P05 |
| **ETCS Level 2 & CBTC Advanced Signalling** | Unsupported | Unsupported (Signalling engine belongs to P06) | Milestone P06 |
| **Station Dwell & TVS Control Engine** | Unsupported | Unsupported (TVS occupancy manager belongs to P07) | Milestone P07 |
| **Seven-Component Blocking Time & Headway** | Unsupported | Unsupported (Headway calculation engine belongs to P08) | Milestone P08 |
| **Multi-Train Continuous Operations** | Unsupported | Unsupported (Multi-train dispatcher belongs to P09) | Milestone P09 |
| **Line Capacity Assessment & UIC 406** | Unsupported | Unsupported (Capacity engine belongs to P10) | Milestone P10 |
| **Stochastic Monte Carlo Simulation** | Unsupported | Unsupported (Stochastic engine belongs to P11) | Milestone P11 |
| **Advanced Scenario Optimization** | Unsupported | Unsupported (Advanced sensitivity belongs to P12) | Milestone P12 |
| **Interactive Visualizations (Plotly)** | Unsupported | Unsupported (Visualizations belong to P13) | Milestone P13 |
| **Reference Engineering Report Generation** | Unsupported | Unsupported (PDF/HTML/XLSX export belongs to P14) | Milestone P14 |
| **Full Gradio UI Workflow Integration** | Unsupported | Unsupported (UI wiring belongs to P15) | Milestone P15 |

---

### 3. Resolution Plan

Each unsupported subsystem listed above will be implemented sequentially according to the approved 15-Prompt Development Sequence under separate, authorized implementation prompts.
