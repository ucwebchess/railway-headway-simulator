# KNOWN LIMITATIONS REGISTER
## Railway Headway & Capacity Simulator

**Software Version:** `0.1.0-dev`  
**Milestone:** `P01 — Canonical Data Architecture & Excel Input System`  
**Authority:** RHS-MASTER-001 § 3; RHS-P01-001 § 25  

---

### 1. Statement of Milestone Scope Limitation

**MILESTONE P01 IS STRICTLY A DATA FOUNDATION, CANONICAL ARCHITECTURE, EXCEL INGESTION, AND PROJECT DATA MANAGEMENT PHASE.**

In strict compliance with **RHS-P01-001 § 25 (Critical Prohibitions)**:
No railway microscopic numerical train dynamics, signalling aspect calculations, interlocking state machines, TVS entry permissions, headway searches, or capacity evaluations were introduced during P01. The objective of P01 was to establish the authoritative data contracts, schemas, validation framework, and Excel ingestion pipeline.

---

### 2. Status of Functional Subsystems

| Subsystem Domain | Milestone P00 Status | Milestone P01 Status | Scheduled Resolution |
|---|---|---|---|
| **Excel Engineering Ingestion** | Unsupported | **FULLY IMPLEMENTED** (6 workbooks, openpyxl, registry-driven) | Milestone P01 |
| **Canonical Data Models & SI Normalization** | Unsupported | **FULLY IMPLEMENTED** (Pydantic v2, Draft 2020-12) | Milestone P01 |
| **Data Validation Pipeline (Levels 1–5)** | Unsupported | **FULLY IMPLEMENTED** (Structural, Field, Cross-Ref, Bounds) | Milestone P01 |
| **Project Packaging (ZIP Import/Export)** | Unsupported | **FULLY IMPLEMENTED** (Safe ZIP handling, manifest, hashes) | Milestone P01 |
| **Scenario Overrides & Baseline Immutability** | Unsupported | **FULLY IMPLEMENTED** (Basic scalar parameter overrides) | Milestone P01 / P12 |
| **1D Infrastructure Graph & Pathfinding** | Unsupported | Unsupported (Topological algorithms belong to P02) | Milestone P02 |
| **Rolling Stock Physics & Dynamics Curves** | Unsupported | Unsupported (Numerical dynamics belong to P03) | Milestone P03 |
| **Braking Models & Microscopic Motion Solver** | Unsupported | Unsupported (0.1s numerical solver belongs to P04) | Milestone P04 |
| **Fixed-Block Signalling & Aspect Logic** | Unsupported | Unsupported (Signalling engine belongs to P05) | Milestone P05 |
| **ETCS Level 2 & CBTC Advanced Signalling** | Unsupported | Unsupported (Signalling engine belongs to P06) | Milestone P06 |
| **Stations, Junctions & TVS Control Engine** | Unsupported | Unsupported (TVS occupancy manager belongs to P07) | Milestone P07 |
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
