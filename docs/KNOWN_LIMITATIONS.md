# KNOWN LIMITATIONS REGISTER
## Railway Headway & Capacity Simulator

**Software Version:** `0.1.0-dev`  
**Milestone:** `P03 — Rolling Stock, Traction & Resistance Engine`  
**Authority:** RHS-MASTER-001 § 3; RHS-P01-001; RHS-P02-001; RHS-P03-001 § 18  

---

### 1. Statement of Milestone Scope Limitation

**MILESTONE P03 IS STRICTLY A ROLLING STOCK CHARACTERISTICS, TRACTION, ADHESION, RUNNING RESISTANCE, DISTRIBUTED INTEGRATION, AND INSTANTANEOUS LONGITUDINAL FORCE BALANCE ENGINE PHASE.**

In strict compliance with **RHS-P03-001 § 18 (Critical Prohibitions)**:
- **No Numerical Time-Stepping Integration:** Milestone P03 evaluates instantaneous point forces and resultant acceleration ($a = F_{\text{net}} / m_{\text{eq}}$). Discrete-time integration ($\Delta t = 0.1\text{ s}$), Runge-Kutta numerical solvers, and trajectory time series generation are deferred to Milestone P04.
- **No Train Trajectory Simulation:** Complete acceleration profiles, cruising runs, coasting trajectories, and station braking profiles are simulated in Milestone P04.
- **No Signalling or Movement Authority:** Signalling aspects, interlocking route reservations, and movement authorities belong to Milestones P05 and P06.
- **No Station Dwell or Headway/Capacity:** Timetable dwelling, TVS resource control, blocking time steps, pairwise headways, and capacity analyses belong to Milestones P07, P08, and P10.
- **No Stochastic Simulation:** Monte Carlo perturbations, delay modeling, and stochastic reliability evaluations are reserved for Milestone P11.
- **No UI Widget Wiring:** Dedicated plotting widgets and PDF report generators are reserved for Milestones P13, P14, and P15.

---

### 2. Status of Functional Subsystems

| Subsystem Domain | Milestone P01 Status | Milestone P02 Status | Milestone P03 Status | Scheduled Resolution |
|---|---|---|---|---|
| **Excel Engineering Ingestion** | Fully Implemented | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Canonical Data Models & SI Normalization** | Fully Implemented | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Data Validation Pipeline (Levels 1–5)** | Fully Implemented | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Project Packaging (ZIP Import/Export)** | Fully Implemented | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 |
| **Scenario Overrides & Baseline Immutability** | Fully Implemented | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P01 / P12 |
| **1D Infrastructure Graph & Pathfinding** | Unsupported | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P02 |
| **Forward & Reverse Route Traversal Engine** | Unsupported | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P02 |
| **Direction-Aware Track Alignment & Speed** | Unsupported | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P02 |
| **Stations, Platforms & TVS Geometry** | Unsupported | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P02 |
| **Multi-Link Resources & Train Footprint** | Unsupported | Fully Implemented | **FULLY IMPLEMENTED** | Milestone P02 |
| **Rolling Stock Physics & Dynamics Curves** | Unsupported | Unsupported | **FULLY IMPLEMENTED** (Mass, traction, adhesion, Davis, Roeckl, distributed integration, force balance) | Milestone P03 |
| **Braking Models & Microscopic Motion Solver** | Unsupported | Unsupported | Unsupported (0.1s numerical solver belongs to P04) | Milestone P04 |
| **Fixed-Block Signalling & Aspect Logic** | Unsupported | Unsupported | Unsupported (Signalling engine belongs to P05) | Milestone P05 |
| **ETCS Level 2 & CBTC Advanced Signalling** | Unsupported | Unsupported | Unsupported (Signalling engine belongs to P06) | Milestone P06 |
| **Station Dwell & TVS Control Engine** | Unsupported | Unsupported | Unsupported (TVS occupancy manager belongs to P07) | Milestone P07 |
| **Seven-Component Blocking Time & Headway** | Unsupported | Unsupported | Unsupported (Headway calculation engine belongs to P08) | Milestone P08 |
| **Multi-Train Continuous Operations** | Unsupported | Unsupported | Unsupported (Multi-train dispatcher belongs to P09) | Milestone P09 |
| **Line Capacity Assessment & UIC 406** | Unsupported | Unsupported | Unsupported (Capacity engine belongs to P10) | Milestone P10 |
| **Stochastic Monte Carlo Simulation** | Unsupported | Unsupported | Unsupported (Stochastic engine belongs to P11) | Milestone P11 |
| **Advanced Scenario Optimization** | Unsupported | Unsupported | Unsupported (Advanced sensitivity belongs to P12) | Milestone P12 |
| **Interactive Visualizations (Plotly)** | Unsupported | Unsupported | Unsupported (Visualizations belong to P13) | Milestone P13 |
| **Reference Engineering Report Generation** | Unsupported | Unsupported | Unsupported (PDF/HTML/XLSX export belongs to P14) | Milestone P14 |
| **Full Gradio UI Workflow Integration** | Unsupported | Unsupported | Unsupported (UI wiring belongs to P15) | Milestone P15 |

---

### 3. Resolution Plan

Each unsupported subsystem listed above will be implemented sequentially according to the approved 15-Prompt Development Sequence under separate, authorized implementation prompts.
