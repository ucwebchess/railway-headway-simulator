# PROMPT EXECUTION REGISTER
## Railway Headway & Capacity Simulator

**Document ID:** RHS-REG-001  
**Version:** 1.3.0  
**Authority:** RHS-MASTER-001 § 34; RHS-P01-001; RHS-P02-001; RHS-P03-001  

---

### 1. Historical & Active Prompts

| Prompt ID | Milestone | Title | Status | Date / Turn | Outcome |
|---|---|---|---|---|---|
| **RHS-MASTER-001** | Master Governance | Master AI-Agent Governance Prompt | Accepted | Baseline | Master directives established; P00 through P15 roadmap frozen. |
| **RHS-P00-001** | P00 | Project Foundation, Architecture, Testing & Colab Launcher | Completed | Baseline | Foundation package, Gradio shell, Colab notebook, test suite established. |
| **RHS-P01-001** | P01 | Canonical Data Architecture & Excel Input System | Completed | Milestone P01 | 16 JSON Schemas, authoritative Excel registry, 6 templates, multi-level validator, SI converter, serializer, hashing, project ZIP packager, 4 example datasets. |
| **RHS-CI-001** | CI | Automated Testing with GitHub Actions | Completed | Milestone CI | `.github/workflows/python-tests.yml` configured, dependency caching, 64 tests verified in CI. |
| **RHS-P02-001** | P02 | Infrastructure Network Model & Topology Engine | Completed | Milestone P02 | Physical network graph, forward/reverse route traversal, direction policy, alignment, speed, switches, stations, TVS, train footprint, preprocessor, adapters. All 10 benchmarks verified. PR #4 open. |
| **RHS-P03-001** | P03 | Rolling Stock Characteristics & Physics | Completed | Milestone P03 | Mass parameters, equivalent mass ($m_{\text{eq}} = m(1+\lambda)$), simplified & detailed traction models, adhesion limits, Davis resistance, Roeckl curvature ($R \ge 300\text{ m}$), multi-link distributed train resistance, longitudinal force balance & acceleration utility, diagnostics sweeps. All 25 benchmarks (`P03-B001`–`P03-B025`) verified. 136 total tests passing. |
| **RHS-P04-001** | P04 | Braking Models & Numerical Solver | Completed | Milestone P04 | Constant deceleration, speed-dependent piecewise linear curves, net effective vs brake generated deceleration, Runge-Kutta numerical solver, boundary localization, directional speed profiles. All 22 benchmarks verified. 178 total tests passing. |
| **RHS-P05-001** | P05 | Resource Management Engine & Fixed-Block Signalling | Completed | Milestone P05 | Common resource architecture, decoupled state tracking, atomic reservations, conflict groups, switch locking, interlocking routes, sectional release, 2/3/4-aspect signals, Movement Authority, braking protection. All 30 benchmarks verified. 208 total tests passing. |
| **RHS-P06-001** | P06 | Advanced Signalling (ETCS Level 2 & CBTC) | Completed | Milestone P06 | ETCS Level 2 with RBC, radio communication latency, multi-stage supervision curves, SvL/overlap; CBTC moving block with train localization, odometry uncertainty, protected envelope $x_{\mathrm{protected}}$, dynamic MA updates, fixed infrastructure restrictions; forward/reverse support. All 30 benchmarks verified (including Controlled Benchmarks A, B, C). 259 total tests passing. |

---

### 2. Reserved Downstream Prompt Register

| Prompt ID | Milestone | Title | Status | Prerequisite |
|---|---|---|---|---|
| **RHS-P07-001** | P07 | Stations, Junctions & TVS Control Engine | Authorized Next | RHS-P06-001 |
| **RHS-P08-001** | P08 | Seven-Component Blocking Time & Headway Analysis | Reserved | RHS-P07-001 |
| **RHS-P09-001** | P09 | Multi-Train Operational Simulation Engine | Reserved | RHS-P08-001 |
| **RHS-P10-001** | P10 | Line Capacity & UIC 406-Inspired Analysis | Reserved | RHS-P09-001 |
| **RHS-P11-001** | P11 | Stochastic Simulation & Operational Reliability | Reserved | RHS-P10-001 |
| **RHS-P12-001** | P12 | Scenario Management & Sensitivity Engine | Reserved | RHS-P11-001 |
| **RHS-P13-001** | P13 | Interactive Engineering Visualizations | Reserved | RHS-P12-001 |
| **RHS-P14-001** | P14 | Professional Engineering Reporting System | Reserved | RHS-P13-001 |
| **RHS-P15-001** | P15 | Full Gradio UI Integration & Final Verification | Reserved | RHS-P14-001 |
