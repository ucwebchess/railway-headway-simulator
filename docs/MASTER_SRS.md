# MASTER SOFTWARE REQUIREMENTS SPECIFICATION (MASTER SRS)
## Railway Headway & Capacity Simulator

**Document ID:** RHS-SRS-001  
**Version:** 1.0.0-draft  
**Status:** REFERENCE PLACEHOLDER / AWAITING AUTHORITATIVE INJECTION  
**Governing Prompt:** RHS-MASTER-001 § 3, § 41; RHS-P00-001 § 13 (P00-DOC-001)  

---

### 1. Document Purpose & Authority Notice

Per Governance Directive **RHS-P00-001 § 13 (P00-DOC-001)**:
> *"This document shall contain or reference the approved SRS Parts 1–14. If the full SRS text is unavailable in the coding agent's context, create a placeholder identifying the missing source. Do not generate a substitute SRS from memory."*

At the conclusion of Milestone P00, the complete, detailed engineering clauses for SRS Parts 1 through 14 have been formally approved at the governance level, but the raw text awaits explicit modular injection across subsequent milestones (P01 through P15).

---

### 2. High-Level Scope of SRS Parts 1–14

The master specification is structured into the following 14 authoritative parts:

| Part | Title | Scope & Downstream Milestone |
|---|---|---|
| **Part 1** | System Overview & Architecture | Modular architecture, Colab platform, SI unit normalization (P00, P01) |
| **Part 2** | Data Ingestion & Canonical Contracts | Excel input workbooks, schema validation, canonical JSON schemas (P01) |
| **Part 3** | Infrastructure Network Representation | 1D topological graph, nodes, links, chainage, alignment geometry (P02) |
| **Part 4** | Rolling Stock Physics & Traction | Davis resistance, traction effort curves, dynamic mass, adhesion (P03) |
| **Part 5** | Train Longitudinal Dynamics & Braking | Numerical solver, service/protection/emergency braking deceleration (P04) |
| **Part 6** | Fixed-Block Signalling & Aspect Sequences | 2/3/4-aspect signalling, overlaps, approach release, sighting time (P05) |
| **Part 7** | Advanced Signalling (ETCS Level 2 & CBTC) | Radio Block Center, movement authorities, moving-block envelopes (P06) |
| **Part 8** | Stations, Junctions & TVS Constraints | Platform dwell, route locking, TVS single-train occupancy enforcement (P07) |
| **Part 9** | Blocking Time & Headway Analysis | 7-component blocking time breakdown, pairwise conflict search (P08) |
| **Part 10** | Multi-Train Operational Simulation | Continuous multi-train dispatch, priority conflict resolution (P09) |
| **Part 11** | Line Capacity Assessment | Theoretical capacity, planning operational capacity, UIC 406-inspired metrics (P10) |
| **Part 12** | Stochastic Simulation & Reliability | Monte Carlo perturbations, dwell variation, driver reaction, seeds (P11) |
| **Part 13** | Scenario Management & Sensitivity | Baseline immutability, parameter override trees, scenario comparisons (P12) |
| **Part 14** | Engineering Reporting & Gradio UI | Reference report fidelity, Plotly stairways, executive summaries (P13–P15) |

---

### 3. Next Actions

As each respective prompt (P01 through P15) is authorized, the complete clause requirements corresponding to each part will be referenced and validated against implementation tests.
