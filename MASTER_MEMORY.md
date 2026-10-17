# MASTER MEMORY
## Railway Headway & Capacity Simulator

**Document Version:** 2.1.0  
**Last Updated:** 2026-10-17  
**Status:** Released — v1.4.0  
**Authoritative Scope:** Project Architecture, Operational Memory, Governance, and Defect Resolution Register  

---

## 1. Project Overview & Architectural Scope

The Railway Headway & Capacity Simulator is a professional-grade, microscopic railway engineering simulation system developed in Python. It models railway infrastructure, rolling stock kinematics, multi-aspect fixed-block and moving-block (ETCS Level 2 / CBTC) signalling, seven-component blocking times, line capacity per UIC 406 guidelines, and stochastic operational reliability.

The platform provides a ten-tab interactive Gradio Blocks user interface, robust Excel data ingestion and validation, multi-format engineering reporting (interactive sandboxed HTML, publication-quality ReportLab PDF, and structured Excel workbooks), and headless CLI execution capabilities.

---

## 2. Critical Context

### 2.1 Baseline Foundation (Milestones P00–P15)
The foundational software platform encapsulates all core engineering subsystems:
- Microscopic train dynamics solved via numerical differential equation integration (Euler / Runge-Kutta 4th Order).
- Running resistance evaluation using empirical Davis equations ($R = A + Bv + Cv^2$).
- Civil speed envelope generation across complex infrastructure networks.
- Safe braking distance calculations and movement authority enforcement.
- Seven-component blocking time calculation and stairway diagram construction.
- Technical headway analysis, timetable compression, and UIC 406 capacity estimation.
- Monte Carlo operational perturbation simulation and reliability assessment.

### 2.2 Multi-Link Signalling Blocks & Clearance Engine (v1.2.0)
Release v1.2.0 introduced multi-link signalling block resolution, permitting block sections and TVS protection zones to span multiple physical track links while maintaining strict sub-millimetre geometric continuity and direction-aware spatial clearance.

### 2.3 Operational Performance Factor Derating (v1.3.0)
Release v1.3.0 introduced configurable operational traction and service braking derating ($f_p \in [0.50, 1.00]$) to model degraded operational conditions, while strictly preserving emergency braking and movement authority protection envelopes at 100% nominal capability.

### 2.4 v1.4.0 Release (2026-10-17)
The v1.4.0 release represents the formal closure and operational integration of all Section 10 defect corrections (DEF-01 through DEF-04) alongside civil speed envelope discretization refinements. All Phase 1, Phase 2, and Phase 3 pull requests have been merged into `main` with 100% automated test verification:
- **Phase 1 (PR #37, SHA `ddfb425`)**: Replaced the synthetic 35-sample / 68-second trajectory stub in `SimulationRunner` with full-corridor microscopic integration via `MultiTrainSimulator`. Wired the Speed Profile chart in HTML/PDF reporting directly to microscopic simulation outputs.
- **Phase 2 (PR #38, SHA `b74bbaf`)**: Populated station stopping metadata across all simulated trains in multi-train operations, ensuring correct arrival, dwell, and departure timestamps in the Station Stopping Pattern table. Refined civil speed envelope generation to retain discrete link boundaries without over-collapsing adjacent links of identical speed limits.
- **Phase 3 (PR #39, SHA `dd59a49`)**: Implemented complete physical engineering units (`Ns/m` for coefficient B, `Ns²/m²` for coefficient C) and explicit velocity declaration (`(v in m/s)` / `[v in m/s]`) for Davis resistance equations across HTML and PDF executive summaries.

---

## 3. Engineering Invariants & Platform Requirements

1. **Pure SI Units Internally**: All internal calculations, models, and simulation dynamics operate strictly in SI units (metres, seconds, metres per second, Newtons, kilograms, Watts, radians). Display conversions (e.g., km/h, kN) occur exclusively at presentation boundaries.
2. **Safety Envelope Invariance**: Emergency braking decelerations and movement authority supervision boundaries are safety-critical invariants that must never be scaled or weakened by operational derating factors.
3. **Deterministic Numerical Integration**: Numerical integration step sizes and tolerances must ensure reproducible trajectories matching physical energy and momentum balances.
4. **Sandboxed Offline Report Generation**: All interactive HTML reports must function completely offline in sandboxed iframes without relying on external CDNs or unauthenticated script assets.

---

## 4. Governance & Pull Request Process

### 4.1 Branching Strategy
- Core development and defect fixes proceed on dedicated topic branches (`fix/*` or `feature/*`).
- Release tags follow Semantic Versioning (`vMAJOR.MINOR.PATCH`).

### 4.2 PR Description & Verification Standards
Per §4.2, every pull request description submitted to the project repository must explicitly provide:
1. Concise executive summary of changes and background rationale.
2. Direct references to defect IDs or feature specifications.
3. Detailed list of affected modules and files.
4. Before-and-after behavioral comparisons (e.g., code snippets, format strings, data outputs).
5. Verification results including full pytest execution logs and AST architectural audit confirmation.

---

## 5. Version History

| Version | Status | Description |
|:---|:---|:---|
| v1.0.0 | Released | Initial production release (Milestones P00–P15 core simulation platform) |
| v1.1.0 | Released | Comprehensive line reference dataset & examples expansion (`05_comprehensive_line`) |
| v1.2.0 | Released | Multi-link signalling blocks & TVS section validation fixes (`06_multilink_blocks`) |
| v1.3.0 | Released | Operational Performance Factor traction & service braking derating (`RHS-FEATURE-PERF-FACTOR-001`) |
| v1.4.0 | Released | Phase 1–3 corrections; DEF-01 through DEF-04 closed |

---

## 6. Data Contracts & Domain Architecture

- `src/headway/data/canonical.py`: Authoritative Pydantic models with strict SI internal units.
- `src/headway/data/excel_registry.py`: Authoritative schema registry governing workbook columns, data types, and sheet names.
- `src/headway/infrastructure/`: Network graph models, TrackLinks, Stations, Platforms, StoppingPoints, SignallingBlocks, TVS.
- `src/headway/rolling_stock/`: Train physics, Davis resistance parameters, tractive effort curves, braking models.
- `src/headway/simulation/`: Microscopic ODE numerical integration, SingleTrainSimulator, MultiTrainSimulator.
- `src/headway/analysis/`: Seven-component blocking time calculation, technical headway, UIC 406 capacity compression.
- `src/headway/reporting/`: Multi-format report assemblers, HTML renderers, ReportLab PDF generators, Excel exporters.

---

## 7. Numerical Simulation & Signalling Engine

The microscopic engine executes step-by-step forward numerical integration of train dynamics governed by:
$$m_{\text{eff}} \frac{dv}{dt} = F_{\text{traction}}(v) - F_{\text{resistance}}(v) - F_{\text{gradient}}(\theta) - F_{\text{curve}}(R) - F_{\text{braking}}$$

Where:
- $F_{\text{resistance}}(v) = A + Bv + Cv^2$ with $A$ in $\text{N}$, $B$ in $\text{N}\cdot\text{s/m}$, and $C$ in $\text{N}\cdot\text{s}^2\text{/m}^2$.
- Moving block (ETCS Level 2 / CBTC) and fixed block (2, 3, 4-aspect) signalling architectures dynamically project movement authorities based on train braking curves and signal separation margins.

---

## 8. Section 8 — Closed Defects (v1.4.0)

All four open defect items identified in Section 10 are completely resolved, verified, and merged to `main` across Phase 1, Phase 2, and Phase 3 pull requests (#37, #38, #39):

- **DEF-01 — Microscopic Simulation Engine Wiring & Trajectory Scope** (Resolved in Phase 1, PR #37):
  - *Symptom*: Simulation runner executed a synthetic 35-sample / 68-second trajectory stub that only modeled single-link movement.
  - *Fix*: Wired `MultiTrainSimulator` into `SimulationRunner`, resolving actual service patterns, multi-link route traversals, and full corridor trajectories (>1,000 samples) with physically authentic acceleration, cruising, and braking regimes.
- **DEF-02 — Speed Profile Chart Binding & Range** (Resolved in Phase 1, PR #37):
  - *Symptom*: Speed profile chart in HTML and PDF reports displayed synthetic stub trajectory data spanning only 0–1,200 m instead of full corridor results.
  - *Fix*: Bound HTML and PDF speed charts directly to full-corridor microscopic simulation outputs and embedded Plotly JS for sandboxed offline rendering.
- **DEF-03 — Station Stopping Pattern Table Multi-Train Surfacing** (Resolved in Phase 2, PR #38):
  - *Symptom*: Station Stopping Pattern table failed to display arrival, dwell, and departure records for multi-train simulations.
  - *Fix*: Updated `SimulationRunner` to record station stop arrival, dwell, and departure timestamps across all trains and forward them into the report metadata.
- **DEF-04 — Davis Running Resistance Units Display** (Resolved in Phase 3, PR #39):
  - *Symptom*: Executive summaries in HTML and PDF displayed Davis formula coefficients with missing physical units and without declaring velocity units.
  - *Fix*: Updated format strings to explicitly show $B$ in $\text{Ns/m}$, $C$ in $\text{Ns}^2/\text{m}^2$, and declared velocity units as $(v \text{ in m/s})$.

---

## 9. Verification & Test Strategy

- **Unit Testing**: Isolated verification of core kinematics, Davis resistance formulas, unit conversions, and report formatters (`tests/unit/`).
- **Integration Testing**: End-to-end corridor runs, UI Blocks instantiation, and multi-train dispatching (`tests/integration/`).
- **Engineering Benchmarks**: Verification against analytic railway engineering standards and reference corridor datasets (`tests/engineering/`).
- **Regression AST Audit**: Automated static AST inspection ensuring zero parameter mismatches across all Gradio callback functions (`tests/regression/`).

---

## 10. Diagnostic & Completion Standards

### 10.2 Mandatory Completion Report Structure
Per §10.2, completion reports for releases and major patches must include:
1. Remote tag status confirmation (`git ls-remote --tags origin`).
2. Current HEAD SHA matching the release tag.
3. Git commit history showing the release commit at the top of `main`.
4. Full regression pytest execution summary confirming 100% test passage.
5. Exact git diff stat showing only affected release artifacts.
6. Verbatim excerpts of updated changelog and version history entries.
7. Explicit confirmation of all updated version strings.

---

## 11. Deployment & Runtime Environment

- **Python Version**: Python 3.10+ (tested on Python 3.10, 3.11, 3.12, 3.13).
- **Core Dependencies**: Pydantic v2, NumPy, SciPy, Pandas, OpenPyXL, ReportLab, Plotly, Gradio Blocks.
- **Sandboxed Execution**: Complete independence from external runtime CDNs; self-contained report assets.

---

## 12. Known Limitations

- All known engineering limitations, assumptions, and edge cases are maintained in `docs/KNOWN_LIMITATIONS.md`.
- Track link gradients are assumed uniform within individual link definitions.
- Emergency braking does not incorporate regenerative or electro-dynamic blending.

---

## 13. Next Steps

Release v1.4.0 is complete and production-released. All Section 10 defects are closed and verified. Any future feature requests, performance optimizations, or line capacity enhancements should be tracked as new milestone items in future development cycles.
