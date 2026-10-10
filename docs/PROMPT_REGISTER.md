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
| **RHS-P07-001** | P07 | Stations, Junctions & TVS Control Engine | Completed | Milestone P07 | Station/Platform controllers, multi-platform allocation, residual rear occupation, junction zone interlocking locking/release, TVS single-train rule ($N_{\max}=1$), TVS MA clamping, TVS queue tracker, whole-tunnel single-train rule. All 35 benchmarks verified. 294 total tests passing. |
| **RHS-P08-001** | P08 | Seven-Component Blocking Time & Headway Analysis | Completed | Milestone P08 | Standardized half-open blocking intervals $B = [t_{\mathrm{start}}, t_{\mathrm{end}})$, 7-component additive decomposition, conflict detector, analytical shift, slack margins, controlling bottlenecks, technical minimum headway solver, microscopic joint verification, $N \times N$ directional mixed-traffic headway matrices. All benchmarks verified. 342 total tests passing. |
| **RHS-P09-001** | P09 | Multi-Train Operational Simulation Engine | Completed | Milestone P09 | Simultaneous microscopic multi-train operational simulation under single shared clock, continuous train-front and train-rear tracking ($s_{\mathrm{rear}} = s_{\mathrm{front}} - L_{\mathrm{train}}$), dispatching policies (FCFS, Timetable, Priority, Fixed sequence), origin queues, station stops, multi-platform allocation, junction interlocking sequencing, TVS queues and holding points, wait-for dependency graph cycle analysis, deadlock diagnosis, additive journey-time decomposition, delay attribution, and time-distance datasets. All 39 benchmarks (P09-B001 to P09-B035 + Numerical Benchmarks A-D) verified. 394 total tests passing. |
| **RHS-P10-001** | P10 | Line Capacity, UIC 406 & Sensitivity Analysis | Completed | Milestone P10 | Theoretical homogeneous capacity ($C = 3600 / H$), additive planning margin, target utilization, mixed-pattern cycle capacity with wrap-around pair, operational throughput with warmup/cooldown windowing, 4-state operational stability evaluator (STABLE, METASTABLE, UNSTABLE, COLLAPSED), capacity saturation search (step scan & bisection), physical occupation vs blocking time analysis with interval merging, directional resource attribution, UIC 406 timetable compression and capacity consumption index with buffer supplement and UIC disclaimer, bottleneck migration tracking with diminishing returns, and sensitivity analysis framework with full physical recalculation (no proportional scaling shortcut) and baseline immutability. All 32 benchmarks (BENCH-P10-001 to 006, P10-B007 to B032) verified. 466 total tests passing. |
| **RHS-P11-001** | P11 | Stochastic Simulation, Monte Carlo & Railway Operational Reliability | Completed | Milestone P11 | Stochastic variable definitions and sampling scopes (PER_REPLICATION, PER_TRAIN, PER_STATION_STOP, PER_RESOURCE_EVENT, PER_COMMUNICATION_EVENT, PER_TIME_WINDOW), validated continuous and discrete probability distributions (Normal, Truncated Normal, Lognormal, Uniform, Triangular, Exponential, Empirical Discrete & Continuous), RNG and MasterSeedManager with reproducible PCG64 streams, correlation groups via Gaussian copula with positive semi-definite matrix validation and Cholesky decomposition, Common Random Numbers (CRN) for scenario comparisons, microscopic operational variability (dwell floor, readiness jitter, traction/braking utilization, TVS release delay), temporary operational disruptions (TSR, extended dwell, platform unavailability) with secondary delay propagation, Monte Carlo simulation manager with isolated replications, cancellation support and non-fatal failure recording, statistical summaries with linear quantile interpolation (P5, P50, P90, P95, P99), Student's t and Wilson score confidence intervals, user-configurable operational reliability criteria, and reliability-based capacity calculation finding maximum sustainable demand rate. All 42 benchmarks (BENCH-P11-A through BENCH-P11-D, P11-B001 to P11-B038) verified. 538 total tests passing. |

---

### 2. Reserved Downstream Prompt Register

| Prompt ID | Milestone | Title | Status | Prerequisite |
|---|---|---|---|---|
| **RHS-P12-001** | P12 | Scenario Management & Sensitivity Engine | Authorized Next | RHS-P11-001 |
| **RHS-P13-001** | P13 | Interactive Engineering Visualizations | Reserved | RHS-P12-001 |
| **RHS-P14-001** | P14 | Professional Engineering Reporting System | Reserved | RHS-P13-001 |
| **RHS-P15-001** | P15 | Full Gradio UI Integration & Final Verification | Reserved | RHS-P14-001 |
