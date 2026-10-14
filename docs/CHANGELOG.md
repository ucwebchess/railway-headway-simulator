# CHANGELOG
## Railway Headway & Capacity Simulator

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] — Operational Performance Factor

### Added

- **Operational Performance Factor (`performance_factor`)**:
  - Implemented configurable operational traction and service braking derating ($f_p \in [0.50, 1.00]$).
  - Precedence hierarchy: Analysis row setting > Scenario default (`default_performance_factor`) > Baseline fallback (1.0).
  - Derates operational traction force $F_{\text{traction, effective}} = f_p \cdot F_{\text{traction, nominal}}(v)$ in `DynamicMode.ACCELERATING`.
  - Derates operational service braking $b_{\text{service, effective}} = f_p \cdot b_{\text{service, nominal}}(v)$ in `DynamicMode.SERVICE_BRAKING`.
  - Wheel-rail adhesion limits applied to the derated traction force.
- **Safety Invariants Preserved**:
  - Emergency braking deceleration ($b_{\text{emergency}}$) strictly preserved at 100% unscaled capability.
  - Movement authority protection and supervised braking envelope calculation strictly computed from 100% unscaled nominal capability.
  - Cruising/coasting, running resistances (Davis equation), track gradients, curvature, civil speed restrictions, and rolling stock maximum speed remain unaffected.
- **Canonical Model & Excel Schema Extensions**:
  - `AnalysisConfig`: Added `performance_factor: float` and `performance_factor_source: str`.
  - `Scenario` / `ScenarioDefinition`: Added `default_performance_factor: Optional[float]`.
  - `AnalysisSettings` worksheet: Added optional `PERFORMANCE_FACTOR` column (FLOAT, [0.5, 1.0]).
  - `ScenarioDefinitions` worksheet: Added optional `DEFAULT_PERFORMANCE_FACTOR` column (FLOAT, [0.5, 1.0]).
  - Excel importer and dataset validator enforce `ERR_FIELD_RANGE` for values outside [0.5, 1.0].
  - JSON draft schemas (`analysis.schema.json`, `scenario.schema.json`) updated to support new attributes.
  - Regenerated all standard Excel templates in `templates/` with updated engineering guidance.
- **Reporting & Visualizations**:
  - Added Performance Factor headline KPI card across Gradio UI, interactive HTML reports, formal ReportLab PDF documents, and Excel assessment export.
  - Documented effective factor and resolution source in engineering report assumptions and audit log trail.
- **Verification Suite**:
  - Added dedicated test suite (`tests/engineering/test_performance_factor.py`) covering canonical models, precedence hierarchy, importer/validator checks, traction derating, braking distance scaling, emergency braking safety invariants, and reporting rendering.

---

## [1.2.0] — Multi-Link Signalling Blocks & Schema Extension

### Added

- **Multi-Link Signalling Blocks**: Formalized spatial decomposition of fixed signalling blocks across multiple contiguous physical track links via dedicated `BlockGeometry` worksheet (`BLOCK_ID`, `SEQUENCE`, `LINK_ID`, `START_OFFSET_M`, `END_OFFSET_M`).
- **Multi-Link TVS Sections**: Formalized spatial decomposition of Tunnel Ventilation Sections across multiple contiguous physical track links via dedicated `TVSGeometry` worksheet (`TVS_ID`, `SEQUENCE`, `LINK_ID`, `START_OFFSET_M`, `END_OFFSET_M`).
- **Topological & Geometric Validation**:
  - Sequence continuity starting at 1 with strict monotonic numbering (`ERR_GEOMETRY_SEQUENCE_DISCONTINUITY`).
  - Network link continuity verifying consecutive intervals connect at shared topology vertices (`ERR_ENG_LINK_DISCONTINUITY`).
  - Physical boundary continuity across links and on same link (`ERR_ENG_PHYSICAL_DISCONTINUITY`).
  - Link bounds clamping and coordinate order verification (`ERR_ENG_BLOCK_BOUNDS_INVALID`, `ERR_ENG_TVS_BOUNDS_INVALID`).
  - Referential integrity checks for `BLOCK_ID`, `TVS_ID`, and `LINK_ID`.
- **Dual Geometry Detection**: Emits `WARN_DUAL_GEOMETRY_SPECIFIED` when both geometry worksheets and legacy single-link columns are present, seamlessly giving precedence to geometry worksheets.
- **Reference Dataset `06_multilink_blocks`**: Reference 4.7 km corridor with 3 multi-link signalling blocks, multi-link TVS section, station platforms, and pairwise headway analysis validating with zero errors.
- **Template Updates**: Standard Excel templates updated to include `BlockGeometry` and `TVSGeometry` worksheets, omitting deprecated geometry columns from master tables.

### Fixed

- **Multi-Train Simulation Resource Clearance**: Corrected premature resource clearance in `multi_train_engine.py` (`_update_resource_occupations`). The engine now maintains per-train, per-resource active interval tracking; a resource is held whenever the train front intersects any interval and releases only after the train rear has cleared all traversed intervals and post-clearance delay timers expire.
- **Multi-Link EOA Calculation**: Corrected downstream End of Authority calculation in `_find_downstream_eoa` to accurately evaluate block entry distance for multi-link blocks.

---

## [1.1.0] — Comprehensive Demonstration Line

### Added

- **Comprehensive Demonstration Line** — new reference example dataset
  in `examples/05_comprehensive_line/`. A 26 km double-track railway
  corridor with:
  - 11 topology nodes, 3 tracks (Up, Down, Siding), 18 track links.
  - 3 passenger stations with 8 platform faces.
  - A 5.0 km twin-bore mountain tunnel with 4 sectional Tunnel
    Ventilation System (TVS) zones on the Up bore and a single
    cross-bore shared resource group.
  - Generic 3-aspect fixed-block signalling: 18 signals, 18 blocks,
    6 interlocking routes.
  - Heterogeneous rolling stock fleet: High-Speed Passenger, Regional
    Commuter, and Heavy Freight with full Davis resistance coefficients
    and multi-point traction and braking curves.
  - 6 service patterns covering express, all-stops, through-freight,
    and overtaking-loop duties.
  - 10 headway analysis cases covering homogeneous, heterogeneous,
    directional, TVS-constrained, and high-precision integration.
  - 5 study scenarios: baseline, block length subdivision, speed
    upgrade, dwell stress, and TVS safety-rule comparison.

  The example demonstrates FORWARD and REVERSE operation, mixed-traffic
  headway, tunnel ventilation restrictions, and scenario comparison in
  a single validated project.

### Fixed

- `TRK_DN` directionality corrected from `REVERSE` to `NOMINAL` so that
  the Down track's physical link orientation (South to North) matches
  the permitted traversal direction. Down-line analyses now resolve
  correctly.
- Down-line signal directionality aligned to match.

### Verified

- All six workbooks of the comprehensive example load with zero
  validation errors.
- All 10 analysis cases resolve to valid headway results.
- The example appears in the Data Import tab's example dropdown.

### Notes

- `05_comprehensive_line` is now the reference multi-scenario example
  for training, testing, and capability demonstration. The existing
  minimal examples (`01`–`04`) remain available for focused single-topic
  use.

---

## [1.0.3] — Template Example Consistency

### Fixed

- The six Excel workbook templates now load with zero validation errors.
  The example rows in the infrastructure, signalling, and scenario
  workbooks referenced identifiers that were not defined elsewhere in the
  example network. These missing definitions have been added, or the
  references removed where a single-resource example is sufficient.
- The INSTRUCTIONS worksheet no longer claims that example rows are
  prefixed with `EXAMPLE_`. The example is a runnable minimal network and
  now documents itself accurately.
- The SignallingSystem worksheet now accepts all five values defined in
  the canonical `SignallingTechnologyType` enum, including
  `ETCS_LEVEL_2_ENGINEERING_MODEL` and
  `CBTC_MOVING_BLOCK_ENGINEERING_MODEL`.
- Cross-reference validation now checks
  `SharedResourceGroups.resource_ids` against defined block and TVS
  resources.

### Added

- 8 regression tests that verify template integrity, ensuring that any
  future change to the schema registry triggers a test failure if the
  templates fall out of alignment.

### Verified

- All six templates from `templates/` load with 0 errors and 0 warnings.
- Test suite: 769 tests passing.

---

## [1.0.2] — Post-Release Fixes (Round 2)

### Fixed

- Download failure in Google Colab: report files are now served through
  an embedded base64 data URI so downloads work without exposing the
  internal Colab runtime hostname. The application continues to run with
  `share=False`.
- Total service duration for the complete line is now displayed in the
  engineering report summary.
- The Speed & Alignment chart now displays the permissible speed envelope
  as a red dashed line, matching the reference report.

### Verified

- All report download formats work in a real Google Colab session.

## [1.0.1] — Post-Release Fixes

### Fixed

- Action buttons: ensured visibility, correct positioning, and correct
  click handler binding for all UI buttons across tabs.
- HTML report preview: figures are now embedded correctly and appear in
  the interactive preview.
- Report download: PDF, HTML, Excel, CSV, JSON, and ZIP package downloads
  now return existing files.
- Data import: corrected a method call to `ScenarioManager` that caused
  `ERR_SIM_FAIL` during custom Excel workbook upload.

## [1.0.0] — Initial Release

### Summary

First formal release of the Railway Headway & Capacity Simulator — a
microscopic railway headway and capacity simulation application with a
Gradio interface running in Google Colab.

### Added

#### Project Foundation (P00)
- Python package architecture with a modular layout.
- Gradio application shell with ten navigation tabs.
- Google Colab launcher notebook.
- pytest test framework.
- Structured exception handling, logging, and centralized configuration.

#### Data Architecture (P01)
- Canonical engineering data models using SI units.
- JSON Schema Draft 2020-12 artifacts for all major data contracts.
- Six standardized Excel workbooks: Infrastructure, Signalling, Rolling
  Stock, Operations, Headway Analysis, and Scenarios.
- Excel import, validation, and canonical conversion.
- SHA-256 hashing of source files and canonical configurations.
- Basic scenario configuration and project ZIP export/import.
- Example datasets covering single-track, double-track, station, and tunnel
  scenarios.

#### Infrastructure (P02)
- Detailed 1D railway network with nodes and physical track links.
- FORWARD and REVERSE route traversal and position mapping.
- Engineering chainage independent of physical route distance.
- Gradient, curvature, speed restriction, switch, station, platform, and
  tunnel geometry.
- Multi-link resource geometry and train-length utilities.
- Infrastructure validation and route profiles.

#### Rolling Stock and Dynamics (P03, P04)
- Multiple rolling stock types with mass, length, and traction models.
- Davis running resistance, Roeckl curvature resistance, and distributed
  gradient resistance.
- Equivalent dynamic mass and longitudinal force balance.
- Service, supervised, and emergency braking models.
- Constant and speed-dependent braking curves.
- Forward traction and backward braking speed profile passes.
- Fixed-step microscopic numerical integration with event localization.
- Train-front and train-rear tracking across multiple links.
- Station stopping, dwell, and departure.
- Unconstrained journey-time calculation.

#### Signalling (P05, P06)
- Common resource management framework with separate physical occupation,
  reservation, locking, release eligibility, and availability.
- Interlocking route setup, locking, and sectional release.
- Generic two-, three-, and four-aspect fixed-block signalling.
- ETCS Level 2 engineering simulation model with RBC movement authority
  and communication delays.
- CBTC moving-block engineering simulation model with localization
  uncertainty and protected train envelope.
- Common movement authority interface shared across signalling systems.

#### Stations, Junctions, and TVS (P07)
- Platform reservation, occupation, and release with rear clearance.
- Residual stationary rear occupation detection.
- Multi-platform allocation and shared station throat handling.
- Junction, merge, diverge, and crossover conflict control.
- Tunnel Ventilation Section resources with one-train-per-section-per-track
  default.
- Shared TVS restrictions across tracks and whole-tunnel restrictions.
- TVS entry authorization with holding points.

#### Headway Analysis (P08)
- Event-derived resource blocking intervals.
- Seven-component blocking-time decomposition.
- Leader–follower conflict detection and analytical temporal shift.
- Microscopic joint-simulation verification.
- Homogeneous and heterogeneous technical headway.
- Directional mixed-traffic headway matrix.
- Controlling bottleneck identification and conflict ranking.
- Blocking-time stairway data for visualization.

#### Multi-Train Operations (P09)
- Simultaneous multi-train microscopic simulation with one shared clock.
- Deterministic event scheduler.
- Timetable, fixed-interval, and mixed-pattern train generation.
- Dispatching policies and train priorities.
- Junction sequencing and queue formation.
- TVS entry waiting and queue tracking.
- Constrained journey time and delay propagation.
- Deadlock detection.

#### Capacity (P10)
- Theoretical homogeneous and mixed-pattern capacity.
- Planning capacity with additive margin or utilization.
- Achieved operational throughput.
- Sustainable capacity search and stability assessment.
- UIC 406-inspired timetable compression and capacity consumption.
- Block-length, signalling, station, and TVS sensitivity analysis.
- Bottleneck migration detection.

#### Stochastic Simulation (P11)
- Eight probability distributions with validated parameters.
- Reproducible Monte Carlo execution with controlled seeds.
- Stochastic dwell, departure readiness, and driving variability.
- Signalling and TVS variability.
- Correlated stochastic variables and common random numbers.
- Statistical summaries, confidence intervals, and reliability criteria.
- Reliability-based capacity.

#### Scenario Management (P12)
- Immutable baseline protection.
- Scenario creation, duplication, and inheritance.
- Explicit parameter overrides with precedence rules.
- Effective configuration generation and hashing.
- Scenario validation and comparison.
- Result association with effective configuration hash.

#### Visualization (P13)
- Interactive Plotly charts for Gradio integration.
- Static figure export for reports.
- Speed, gradient, and curvature diagrams.
- Time–distance diagrams.
- Blocking-time stairway and seven-component charts.
- Mixed-traffic headway matrix heatmaps.
- Station, platform, and TVS occupation diagrams.
- Capacity sensitivity, stochastic distributions, and scenario comparison
  charts.
- FORWARD and REVERSE direction visualization.

#### Engineering Reporting (P14)
- Professional engineering report generator matching the reference
  document style.
- Executive KPI dashboard.
- Eighteen report sections covering all engineering domains.
- Rule-based engineering recommendations.
- PDF, HTML, Excel, CSV, and JSON export.
- Complete report package.
- Full calculation provenance and auditability.

#### Complete Application (P15)
- Full Gradio interface with ten functional tabs.
- **Running direction selector: FORWARD / REVERSE.**
- Background simulation execution with progress and cancellation.
- File upload and download management.
- Session state management.
- Google Colab launcher.
- End-to-end workflow verification.

### Engineering Constraints Maintained

- No hardcoded reference report values.
- No forward-only assumptions.
- No silent substitution of simplified models as certified systems.
- No baseline mutation.
- Full traceability of every KPI.

### Known Limitations

See `docs/KNOWN_LIMITATIONS.md` for the complete list.

### Notes

This is an engineering simulation tool for headway and capacity assessment.
It does not constitute a certified signalling safety system, and the ETCS
Level 2 and CBTC models are engineering approximations unless independently
verified against a specific specification.

---

## [1.0.0] - Milestone P15 (Final Milestone & Production Release)

### Added
- **Complete Ten-Tab Interactive Gradio User Interface (`headway.ui`):**
  - **Tab 1: Project Dashboard (`headway.ui.tab_dashboard`):** Project metadata, ID, dataset status, microscopic headline KPIs, live system diagnostics, and quick navigation actions.
  - **Tab 2: Data Import (`headway.ui.tab_data_import`):** Upload manager for 6 Excel workbooks, project ZIP archives, verified example project loader (4 official datasets), and template package exporter.
  - **Tab 3: Data Validation (`headway.ui.tab_validation`):** Simulation readiness indicator, severity filterable findings table (CRITICAL, ERROR, WARNING, INFO), and Excel findings report export.
  - **Tab 4: Infrastructure Explorer (`headway.ui.tab_infrastructure`):** Interactive Plotly network schematic, vertical gradient profile, FORWARD / REVERSE coordinate orientation toggle, and infrastructure registers.
  - **Tab 5: Rolling Stock & Signalling (`headway.ui.tab_rolling_stock_signalling`):** Microscopic physics inspector, tractive effort vs velocity curves, Davis train resistance, aspect progressions, and signals register.
  - **Tab 6: Services & Operations (`headway.ui.tab_operations`):** Commercial service pattern inspector, route link sequences, platform stopping schedules, dwell durations, and traversal schematic.
  - **Tab 7: Scenario Manager (`headway.ui.tab_scenarios`):** Immutable baseline scenario protection, branching/cloning/deletion, TVS evacuation policies, stochastic settings, and parameter diff tables.
  - **Tab 8: Simulation Control (`headway.ui.tab_simulation`):** **MANDATORY explicit FORWARD / REVERSE running direction selector**, numerical step size, margins, pre-simulation summary, background execution, progress reporting, and user cancellation.
  - **Tab 9: Results & Comparison (`headway.ui.tab_results`):** Prominent direction banner, executive KPI cards, 10 interactive Plotly chart views (speed, blocking stairway, 7-component, platforms, mixed-traffic, TVS, sensitivity, Monte Carlo, scenario comparison, bottleneck migration), and Excel/JSON result exporters.
  - **Tab 10: Reports & Export (`headway.ui.tab_reports`):** Assessment type dropdown, section selection toggles, publication-grade interactive HTML preview, multi-format deliverable downloads (PDF, Excel, CSVs, JSON, complete Assessment ZIP), and session state backup/restoration.
- **Mandatory Explicit FORWARD / REVERSE Running Direction Integration (`headway.ui.direction_selector`):**
  - Enforced mandatory selection of running direction before simulation execution.
  - Topological corridor validation rejecting simulation runs that conflict with track link directionality.
  - Full propagation of directional parameters to physics integration, headway solver, blocking stairway, and reports.
- **Asynchronous Non-Blocking Execution Manager (`headway.ui.background_executor`, `headway.ui.progress`):**
  - ThreadPool background executor executing microscopic simulations without freezing the Gradio UI.
  - Thread-safe cancellation token allowing instant user abort of ongoing simulation tasks.
  - Monotonic progress tracking with elapsed time, estimated remaining time, and stage logging.
- **Professional Engineering Error Boundaries (`headway.ui.error_handling`):**
  - Translation of internal exceptions into structured, actionable railway engineering feedback cards.
  - Complete suppression of raw unformatted Python tracebacks in user-facing components.
- **Google Colab Launcher Notebook (`colab/Railway_Headway_Simulator.ipynb`):**
  - Environment detection and hardware resource verification (CPU/RAM).
  - Dependency installation and official example dataset discovery.
  - In-line Gradio app launching with `share=False` default security compliance.
- **Comprehensive Verification Test Suites:**
  - `tests/unit/test_ui_benchmarks.py`: Full verification across all 40 UI benchmarks (`P15-B001` through `P15-B040`).
  - `tests/unit/test_ui_negative.py`: Negative testing verifying error boundaries without raw tracebacks.
  - `tests/integration/test_ui_e2e.py`: End-to-end integration workflows (`P15-E2E-001` to `P15-E2E-025`) across all example datasets.

---

## [0.1.0-dev] - Milestone P14 (Current Milestone)

### Added
- **Canonical Report Data Models & Configuration (`headway.reporting.report_models`, `headway.reporting.report_config`):**
  - Canonical `ReportDocument` container maintaining report metadata, executive KPIs, rolling stock parameters, infrastructure properties, bottleneck diagnosis, 18 standard engineering sections, figures, recommendations, and audit events.
  - Immutable headline KPI container (`ExecutiveKpis`) exposing technical headway (s and min), theoretical capacity (tph), planning capacity (tph), controlling bottleneck ID, type, and physical location.
  - Structured engineering metadata (`ReportMetadata`) with run ID, scenario ID, project ID, generation timestamp, software version, input configuration hash, and validation status.
  - Comprehensive configuration model (`ReportConfig`) supporting report types (FULL_ASSESSMENT, EXECUTIVE_SUMMARY, TECHNICAL_APPENDIX, DIRECTIONAL_ASSESSMENT), paper sizes (A4, LETTER), orientations (PORTRAIT, LANDSCAPE), section selection toggles, and formatting thresholds.
- **Deterministic Rule-Based Recommendation Engine (`headway.reporting.recommendations`):**
  - Six deterministic engineering recommendation rules (`RecommendationEngine`):
    1. Residual rear fouling: identifies station throat block clearance delays and recommends clearing point repositioning or berth adjustments.
    2. Long signal blocks: identifies open-line blocks exceeding 1200 m with occupation > 60 s and recommends intermediate block section splitting.
    3. Platform dwell bottleneck: detects platform dwell dominating line headway and recommends dual-berth operation or automated passenger management.
    4. Junction sectional release: detects interlocking approach locking and recommends intermediate route release sections.
    5. TVS single-train holding: detects tunnel ventilation headway constraints and recommends intermediate TVS section dividing.
    6. Stochastic operational delay buffering: evaluates P95 vs deterministic spread and recommends timetable planning margins.
  - Purely deterministic logic grounded strictly in microscopic simulation results; no unsupported or generative AI technical claims.
- **18-Section Automated Report Assembly Engine (`headway.reporting.report_assembly`):**
  - `ReportAssembler` assembling all 18 standard engineering sections directly from `SimulationResultPackage` without recalculating dynamics or headway:
    - Section 1: Executive Summary & Headline KPIs (4 KPI dashboard cards).
    - Section 2: Speed Profile, Gradient and Alignment Curvature (3-panel composite).
    - Section 3: Blocking-Time Stairway Diagram.
    - Section 4: Seven-Component Blocking Breakdown (stacked chart & reconciliation).
    - Section 5: Pairwise Headway Route-Conflict Ranking Table.
    - Section 6: Longest Individual Resource Occupations Table.
    - Section 7: Station Resource and Platform Track Occupation.
    - Section 8: Mixed-Traffic Directional Headway Matrix & Heatmap.
    - Section 9: Station Stopping, Dwell and Multi-Platform Allocation Table.
    - Section 10: Constrained Block-Length Sensitivity Analysis.
    - Section 11: Detailed Resource Occupation Timing Breakdown Table.
    - Section 12: Resource Geometry Provenance & Baseline Integrity Table.
    - Section 13: Assumptions, Methodology and Signalling Configuration Audit.
    - Section 14: Tunnel Ventilation System (TVS) Headway Assessment.
    - Section 15: Multi-Train Operational Assessment & Capacity Stability.
    - Section 16: Stochastic Headway & Operational Reliability (P90, P95, P99).
    - Section 17: Scenario Comparison & Capacity Improvement.
    - Section 18: Verification, Methodological Limits and Conclusions/Recommendations.
  - Transparent omission disclosure: unexecuted optional subsystems are retained with clear not-applicable notices rather than silently omitted.
  - Strict directional banner compliance: explicit `Running Direction: FORWARD` or `Running Direction: REVERSE` banner rendered prominently across all sections.
- **Publication-Grade HTML5 Renderer (`headway.reporting.html_renderer`):**
  - `HtmlReportRenderer` generating standalone publication-grade HTML matching the reference engineering report.
  - Embedded CSS with dark navy headers (`#1B365D`), light gray background (`#F8F9FA`), KPI dashboard cards, zebra-striped tables with red highlighting on controlling bottlenecks, callout boxes, and print `@media print` rules for A4 pagination.
- **Formal A4 Portrait PDF Renderer (`headway.reporting.pdf_renderer`):**
  - `PdfReportRenderer` utilizing ReportLab for formal engineering deliverable generation in A4 portrait format.
  - Numbered canvas with running header, title, date, running direction, page numbering (`Page X of Y`), KPI summary cards, embedded charts, styled engineering tables, and audit metadata.
- **Multi-Tab OOXML Excel Exporter (`headway.reporting.excel_export`):**
  - `ExcelReportExporter` generating multi-sheet `.xlsx` workbooks.
  - `Executive_Summary` tab with project metadata, headline KPIs, rolling stock parameters, and infrastructure properties.
  - `RECOMMENDATIONS` tab tabulating engineering interventions with rationale.
  - Dedicated worksheets for individual engineering tables with dark navy headers, bold text, freeze panes, auto-fitted column widths, and red highlighting on controlling rows.
- **Tabular CSV & JSON Exporters (`headway.reporting.csv_export`, `headway.reporting.json_export`):**
  - `CsvReportExporter` exporting individual CSV files for all applicable result tables.
  - `JsonReportExporter` serializing `ReportDocument` into versioned, schema-compliant JSON format.
- **Comprehensive Report Package Exporter (`headway.reporting.report_package`):**
  - `ReportPackageExporter` bundling HTML, PDF, Excel, CSVs, JSON, and SHA-256 metadata manifest into a consolidated ZIP assessment archive.
- **Report Validation & Audit Engine (`headway.reporting.report_validation`):**
  - `ReportValidator` enforcing criteria P14-RPT-VAL-001 through P14-RPT-VAL-008.
  - Mathematical capacity verification ($C = 3600 / H$).
  - Reconciliation between Executive KPIs and detailed conflict ranking tables.
  - Blocking duration component sum check ($t_1..t_7 = t_{\mathrm{total}}$).
  - Silent omission prevention and configuration hash integrity verification.

### Verification
- **Engineering Benchmarks:**
  - 35 mandatory benchmarks (`P14-B001` through `P14-B035`) verified in `tests/engineering/test_report_benchmarks.py`.
- **Negative & Integration Test Suites:**
  - 9 negative tests verifying formula mismatches, KPI discrepancies, hash mismatches, and omission detection in `tests/unit/test_report_negative.py`.
  - 3 end-to-end integration tests verifying cross-format rendering, ZIP packaging, and reverse-direction integrity in `tests/integration/test_report_integration.py`.
- **Regression:**
  - 693 total tests passing across all milestones (P01 through P14) with zero regressions.

---

## [0.1.0-dev] - Milestone P13

### Added
- **Canonical Simulation Result Architecture (`headway.reporting.result_models`):**
  - Authoritative result package container (`SimulationResultPackage`) consolidating microscopic train trajectories, speed envelopes, alignment profiles, blocking intervals, technical headway results, mixed-traffic matrices, platform occupations, TVS occupations, sensitivity studies, stochastic summaries, and scenario comparison reports.
  - Frozen, immutable display and provenance record models (`PlatformOccupationRecord`, `StationStopRecord`, `ConflictRankingRecord`, `ResourceTimingRecord`, `ResourceProvenanceRecord`).
  - Zero engineering recalculation guarantee: visualizers read directly from upstream simulation results without re-integrating train dynamics or recomputing blocking times.
  - Explicit running direction field (`RunningDirection`) on all visualization models and records.
- **Result Validation & Diagnostic Engine (`headway.reporting.result_validation`):**
  - Comprehensive pre-chart validation engine (`ResultValidator`, `ResultValidationReport`, `ResultDiagnostic`).
  - Structured diagnostic error codes (`MISSING_IDENTITY`, `INVALID_DIRECTION`, `EMPTY_TRAJECTORY`, `NON_MONOTONIC_TIME`, `NON_MONOTONIC_DISTANCE`, `NON_FINITE_VALUE`, `INVALID_INTERVAL`, `INVALID_HEADWAY`, `INVALID_MATRIX`, `DIRECTION_MISMATCH`, `EMPTY_RESOURCE_LIST`, `MISSING_DATASET`).
  - Strict inspection of physical coordinates, temporal monotonicity, non-finite values (NaN/Inf), and negative speeds.
- **Standardized Chart Themes & Engineering Styling (`headway.reporting.chart_theme`):**
  - Professional railway engineering palette (`ChartColors`: navy, blue, teal, green, amber, red).
  - Explicit physical units on all axes (m, km, km/h, m/s, s, ‰, 1/m).
  - Prominent running direction banners (`Running Direction: FORWARD` / `REVERSE`).
  - Distinct highlights for controlling resources, critical blocks, and bottleneck shifts.
  - Dual theme support: interactive Plotly figures and publication-ready Matplotlib figures.
- **Direction-Aware Visualization Data Adapters (`headway.reporting.visualization_adapters`):**
  - Intelligent trajectory downsampling preserving mode changes, velocity extrema, and boundary events.
  - Directional chainage alignment (route vs physical chainage).
  - Gradient profile adaptation with sign inversion in `REVERSE` running direction (+15‰ uphill becomes -15‰ downhill).
  - Curvature profile adaptation calculating reciprocal curvature ($1/R$).
  - Extraction adapters for conflict ranking, longest occupation, and 7-component timing.
- **Microscopic Speed, Gradient & Curvature Visualization (`headway.reporting.charts_speed`):**
  - Detailed speed profile diagrams (`create_speed_distance_figure`).
  - Stepped permissible civil and signalling speed envelopes.
  - Station platform stop markers and dwell zones.
  - Track alignment profiles (`create_gradient_profile_figure`, `create_curvature_profile_figure`).
  - Stacked 3-panel track alignment composite figure (`create_track_alignment_combined_figure`).
- **Blocking-Time Stairway & Seven-Component Stacked Charts (`headway.reporting.charts_blocking`):**
  - Microscopic blocking-time stairway diagrams (`create_blocking_stairway_figure`) rendering leader and follower blocking intervals with technical minimum headway shift $H$.
  - Seven-component decomposition stacked bar charts (`create_seven_component_figure`) tabulating setup $t_1$, approach $t_2$, running $t_3$, dwell $t_4$, geometric clearance $t_5$, residual rear $t_6$, and release $t_7$.
  - Sub-millisecond mathematical duration reconciliation verification.
- **Operational Time-Distance Diagrams & Mixed-Traffic Heatmaps (`headway.reporting.charts_headway`):**
  - Multi-train time-distance operational trajectories (`create_time_distance_figure`) with station locations and dwell intervals.
  - Bidirectional and opposing-direction train trajectory rendering.
  - Mixed-traffic minimum headway matrix heatmaps (`create_mixed_traffic_heatmap`) with values, color coding, and controlling bottleneck labels.
- **Station Platform Track Occupation & TVS Diagrams (`headway.reporting.charts_station`, `headway.reporting.charts_tvs`):**
  - Platform track occupation timeline diagrams (`create_platform_occupation_figure`) showing train arrival, dwell, departure, and clearance.
  - Platform residual rear occupation visualization highlighting upstream block fouling.
  - TVS section occupancy timeline diagrams (`create_tvs_occupation_figure`) verifying single-train occupancy rule.
  - Signalling vs TVS minimum headway comparison diagrams (`create_tvs_comparison_figure`).
- **Multi-Train Capacity & Stochastic Distribution Charts (`headway.reporting.charts_capacity`, `headway.reporting.charts_stochastic`):**
  - Two-panel block length sensitivity figures (`create_block_sensitivity_figure`).
  - Capacity saturation curves with queue development and stability boundaries (`create_capacity_saturation_figure`).
  - Monte Carlo frequency histograms with mean and percentile reference lines (`create_stochastic_histogram_figure`).
  - Point estimates with confidence interval error bars (`create_confidence_interval_figure`).
- **Scenario Comparison & Bottleneck Migration Diagrams (`headway.reporting.charts_scenario`):**
  - Scenario KPI grouped bar charts (`create_scenario_kpi_comparison_figure`) with absolute values and percentage deltas.
  - Bottleneck migration plots (`create_bottleneck_migration_figure`) tracing governing resource movement.
- **Standardized Engineering Tables & Multi-Format Exporters (`headway.reporting.tables`, `headway.reporting.export_static`):**
  - Tabulation utilities for conflict ranking, longest occupation, station stopping, 7-component timing, infrastructure provenance, mixed-traffic matrices, and scenario comparisons.
  - Export capabilities for CSV, Excel OOXML (`.xlsx`), JSON, and HTML.
  - Headless static figure export (`StaticFigureExporter`, `export_figure_headless`, `export_matplotlib_figure`) supporting PNG, SVG, PDF, and high-DPI rendering with automatic headless fallback.
- **Verification & Benchmark Coverage:**
  - 35 mandatory benchmarks (`P13-B001` through `P13-B035`) verified in `tests/engineering/test_visualization_benchmarks.py`.
  - 17 negative tests in `tests/unit/test_visualization_negative.py`.
  - 4 end-to-end integration workflows in `tests/integration/test_visualization_integration.py`.
  - Full suite expanded to 646 passing tests (100% pass rate).

---

## [0.1.0-dev] - Milestone P12

### Added
- **Scenario Identity & Metadata (`headway.scenarios.scenario_models`):**
  - Standardized scenario lifecycle metadata: `SCENARIO_ID`, `SCENARIO_NAME`, `DESCRIPTION`, `BASE_SCENARIO_ID`, `STATUS` (`DRAFT`, `ACTIVE`, `ARCHIVED`), `CREATION_DATE`, `LAST_MODIFIED_DATE`, tags, and user metadata.
  - Immutable baseline scenario (`BASELINE`) guaranteed to be read-only and never modified or deleted.
  - Complete scenario isolation: scenarios are represented as isolated deltas from baseline or parent, preventing state contamination across variants.
  - Explicit override schema (`ExplicitOverride`) supporting target dataset domains (`infrastructure`, `signalling`, `rolling_stock`, `operations`, `analysis`, `stochastic`), target object IDs, dot-notation parameter paths, override actions (`REPLACE`, `ADD`, `REMOVE`), typing, units, and engineering rationales.
- **Override Navigation & In-Place Application (`headway.scenarios.overrides`):**
  - Recursive nested dictionary/list path traversal with dot-notation navigation (`OverrideNavigator`).
  - Strict type casting and validation (`cast_override_value`) preventing type drift.
  - Multi-collection entity ID lookup across nodes, track links, stations, platforms, TVS sections, train types, and routes.
  - Support for `GLOBAL`, `PROJECT`, and `ROOT` object targets for global project parameters and stochastic configurations.
- **Effective Configuration Generation & Caching (`headway.scenarios.effective_config`):**
  - Multi-level scenario inheritance resolution supporting parent-child chains of arbitrary depth ($\ge 3$ levels).
  - Precedence ordering: `Baseline` $\rightarrow$ `Parent` $\rightarrow$ `Child` $\rightarrow$ `Grandchild`.
  - Same-level conflict detection raising `ConflictingOverrideError` on conflicting parameter assignments.
  - Circular inheritance cycle detection raising `CircularInheritanceError` on direct, multi-level, or self-referential cycles.
  - Deep-copy isolated configuration generation ensuring no shared mutable state.
  - Deterministic SHA-256 hash calculation (`calculate_effective_hash`) invariant under dictionary key ordering.
  - Config generator caching keyed by effective scenario hash with automated invalidation.
- **Scenario & Configuration Validation Engine (`headway.scenarios.scenario_validation`):**
  - Pre-execution scenario validation checking domain existence, target object existence, parameter path validity, and physical engineering bounds.
  - Effective configuration network consistency checks: positive link lengths, undefined node reference detection, platform offset host link bounds, route node continuity, and TVS single-occupancy invariant enforcement.
  - Clear severity separation (`CRITICAL`, `ERROR`, `WARNING`, `INFO`), blocking simulation execution upon presence of critical findings.
- **Pre-Configured Engineering Scenario Templates (`headway.scenarios.templates`):**
  - Standardized factory methods for railway engineering studies:
    - Baseline reference scenario (`create_baseline_scenario`)
    - Signalling comparison scenario (`create_signalling_comparison_scenario`)
    - Block length sensitivity scenario (`create_block_sensitivity_scenario`)
    - Station dwell and platform optimization scenario (`create_station_optimization_scenario`)
    - TVS ventilation operational policy scenarios (`create_tvs_policy_scenario`: `TVS_PER_TRACK`, `TVS_SHARED`, `WHOLE_TUNNEL`)
    - Stochastic Monte Carlo simulation scenario (`create_stochastic_scenario`)
    - Operational disruption and incident scenario (`create_disruption_scenario`)
- **Simulation Result Association & Invalidation (`headway.scenarios.result_association`):**
  - Execution run registry (`ScenarioResultRegistry`) storing runs with unique `RUN_ID`, scenario ID, effective configuration hash, timestamps, parameters, metrics, and artifact references.
  - Automated staleness detection: modifying any override or running direction updates the scenario effective hash and automatically marks prior simulation runs as `STALE`.
  - Multi-run history preservation preventing silent overwrite of engineering results.
- **Scenario Comparison Engine (`headway.scenarios.scenario_comparison`):**
  - Multi-scenario comparative analytics (`ScenarioComparisonEngine`, `ScenarioComparisonReport`).
  - Automated parameter diffing tabulating baseline values alongside scenario values.
  - Metric delta calculations: absolute changes, percentage changes, and directional improvement flags (`is_improvement`).
  - Running direction compatibility checks flagging directional mismatches (e.g. comparing FORWARD vs REVERSE).
  - Bottleneck migration analysis identifying shifts in critical infrastructure constraints between scenarios.
- **Scenario Manager Facade (`headway.scenarios.scenario_manager`):**
  - Unified central coordinator (`ScenarioManager`) managing the complete scenario lifecycle: creation, duplication, renaming, deletion, archiving, override editing, direction setting, validation, simulation registration, comparison, and JSON export.
- **Verification Benchmarks & Tests (`tests/engineering/`, `tests/unit/`, `tests/integration/`):**
  - Mandatory engineering benchmarks P12-B001 to P12-B028 covering baseline immutability, inheritance precedence, cycle rejection, hash stability, validation, templates, comparison analytics, bottleneck shifts, result invalidation, and deterministic reproducibility.
  - 19 negative unit tests verifying baseline protections, circular inheritance, conflicting overrides, out-of-bounds values, invalid paths, and TVS occupancy invariants.
  - 5 end-to-end integration tests verifying multi-level inheritance ($\ge 3$ levels), signalling upgrade studies, block sensitivity matrices, directional analysis, and result invalidation.
  - Complete regression test suite passing with 0 failures (590 total passing tests).

---

## [0.1.0-dev] - Milestone P11

### Added
- **Stochastic Variable Definitions & Disruptions (`headway.analysis.random_variables`):**
  - Standardized schema for configurable stochastic variables with target object types, parameter identifiers, units, bounds, and correlation groups.
  - Granular sampling scopes: `PER_REPLICATION`, `PER_TRAIN`, `PER_STATION_STOP`, `PER_RESOURCE_EVENT`, `PER_COMMUNICATION_EVENT`, and `PER_TIME_WINDOW`.
  - Operational disruptions: temporary speed restrictions (TSR), extended station dwell, delayed route setting, temporary platform unavailability, TVS delays, communication latency, and traction reduction.
- **Probability Distribution Engine (`headway.analysis.distributions`):**
  - Fully validated continuous and discrete distributions: Normal, Truncated Normal, Lognormal, Uniform, Triangular, Exponential, Empirical Discrete, and Empirical Continuous.
  - Strict parameter validation (positive std/scale, monotonic bounds/CDF, unit probability sums).
  - Exact analytical moments (mean, variance) and PPF quantile functions.
- **RNG, Seed Management & Common Random Numbers (`headway.analysis.stochastic`):**
  - Modern NumPy `default_rng` generator architecture utilizing PCG64 bit generators.
  - `MasterSeedManager` generating deterministic child streams per replication via `SeedSequence.spawn()`.
  - `CorrelationGroup` managing correlated random variables via Gaussian copula, positive semi-definite matrix validation, and Cholesky decomposition.
  - `CommonRandomNumbersManager` providing synchronized random draws across scenario comparisons for variance reduction.
  - `StochasticParameterSampler` enforcing scope caching and bounding.
- **Statistical Summary & Confidence Intervals (`headway.analysis.statistics`):**
  - Non-rounded statistical summaries: count, mean, median, sample std, min, max, P5, P50, P90, P95, P99 using linear quantile interpolation.
  - Student's t-distribution confidence intervals for sample means.
  - Wilson score confidence intervals for binomial proportions (punctuality).
- **Operational Reliability Assessment (`headway.analysis.reliability`):**
  - User-configurable `ReliabilityCriterion` thresholds (punctuality %, mean delay, P95 delay, TVS waiting, max queue).
  - Multi-criteria replication evaluator with Wilson score CI and diagnostic summary generation.
- **Monte Carlo Simulation Manager (`headway.analysis.monte_carlo`):**
  - Isolated replication runner executing the microscopic multi-train engine (`MultiTrainSimulator`) without state leakage.
  - Deepcopy cloning ensuring deterministic baseline parameter immutability.
  - Stochastic parameter application across dwell, departure readiness, traction utilization, braking utilization, and TVS release timers.
  - Progress callbacks, cancellation tokens, and non-fatal replication failure recording.
  - Statistical aggregation across headways, journey times, delays, TVS queues, and throughputs.
- **Reliability-Based Capacity Calculator (`headway.analysis.stochastic_capacity`):**
  - Candidate demand rate sweep testing sustainable capacity under stochastic operational variability.
  - Highest reliable rate identification satisfying all configured reliability criteria.
- **Verification Benchmarks & Tests (`tests/engineering/`, `tests/unit/`, `tests/integration/`):**
  - Numerical Benchmarks A (Uniform distribution mean 15.0s, var 8.3333 s^2), B (Binomial punctuality 95/100 = 0.95), C (Delay sample mean 30.0s, std 15.8114s), and D (TVS waiting mean 24.0s, wait prob 60.0%).
  - Mandatory engineering benchmarks P11-B001 to P11-B038 covering schema validation, distributions, RNG reproducibility, TVS single-train occupancy invariants, and bidirectional operations.
  - 23 negative unit tests verifying parameter boundaries and error handling.
  - 7 end-to-end integration tests verifying FORWARD, REVERSE, opposing-direction simultaneous trains, TVS queueing, disruptions, CRN synchronization, and reliability-based capacity calculation.
  - Zero regression across all prior milestones (538 total passing tests).

---

## [0.1.0-dev] - Milestone P10

### Added
- **Theoretical and Planning Capacity Engine (`headway.analysis.capacity`):**
  - Ideal homogeneous theoretical capacity calculation ($C = 3600 / H$).
  - Additive planning margin method ($H_{\mathrm{plan}} = H_{\mathrm{technical}} + M$, $C_{\mathrm{plan}} = 3600 / H_{\mathrm{plan}}$).
  - Target utilization method ($C_{\mathrm{plan}} = U \cdot C_{\mathrm{theoretical}}$).
  - Repeated mixed-traffic cycle capacity with wrap-around pair ($T_{\mathrm{cycle}} = \sum_{k=1}^{N-1} H(s_k, s_{k+1}) + H(s_N, s_1)$, $C = 3600N / T_{\mathrm{cycle}}$).
  - Complete directional segregation supporting both `RunningDirection.FORWARD` and `RunningDirection.REVERSE`.
- **Operational Throughput Engine (`headway.analysis.throughput`):**
  - Observation window partitioning separating warm-up, active measurement window, and cool-down periods.
  - Completed trip counting and spatial boundary screenline crossing counting.
  - Throughput calculation $Q = N_{\mathrm{counted}} / (T_{\mathrm{measurement}} / 3600)$.
- **Operational Stability Evaluation (`headway.analysis.stability`):**
  - Four-state classification: `STABLE`, `METASTABLE`, `UNSTABLE`, and `COLLAPSED`.
  - Linear regression delay growth slope calculation ($s\text{ delay increase per dispatched train}$).
  - Multi-train queue growth tracking, completion ratio enforcement, and deadlock detection.
  - Distinction between technical headway capacity and sustainable operational capacity.
- **Capacity Saturation Search Engine (`headway.analysis.saturation`):**
  - Step-wise demand rate scanning across candidate rates.
  - Binary bisection search converging to maximum sustainable operational capacity within specified tolerance.
- **Resource Utilization Analysis (`headway.analysis.resource_utilization`):**
  - Rigorous differentiation between physical occupation time and blocking/reservation time.
  - Overlapping reservation interval merging preventing artificial $> 100\%$ utilization.
  - Directional attribution: FORWARD vs REVERSE blocking time.
  - Resource categories: track blocks, station platforms, interlocking switches, TVS zones, and shared groups.
- **Timetable Compression & UIC 406-Inspired Capacity Consumption (`headway.analysis.timetable_compression` & `headway.analysis.capacity_consumption`):**
  - Train path stairway extraction and chronological compression up to safety buffer margins.
  - Preservation of train running times, dynamic profiles, and station dwell durations.
  - Capacity consumption calculation $K = (T_{\mathrm{compressed}} + T_{\mathrm{supplement}}) / T_{\mathrm{analysis}}$.
  - Standard UIC 406 methodology disclaimer string enforcement.
- **Bottleneck Diagnostics & Migration Tracking (`headway.analysis.bottleneck_migration`):**
  - Multi-criteria bottleneck ranking based on limiting headway, blocking utilization, and accumulated delay.
  - Bottleneck migration tracking across scenario modifications.
  - Diminishing returns ratio calculation and diagnostic engineering commentary.
- **Sensitivity Analysis Framework (`headway.analysis.sensitivity`):**
  - Baseline immutability guarantee preventing in-place parameter corruption.
  - Full physical recalculation principle strictly prohibiting proportional scaling shortcuts.
  - Sensitivity sweeps: block length, signalling technology (2/3/4 aspect, ETCS L2, CBTC), station dwell, parallel platform assignment, and TVS parameters.
- **Verification Benchmarks & Tests (`tests/engineering/`, `tests/unit/`, `tests/integration/`):**
  - Analytical benchmarks BENCH-P10-001 through BENCH-P10-006 (exact analytical values).
  - Operational benchmarks P10-B007 through P10-B032 (26 comprehensive benchmarks).
  - 35 unit negative tests covering validation, edge cases, and immutability invariants.
  - 5 end-to-end integration tests connecting multi-train simulation, headway solving, capacity analysis, UIC 406 compression, and sensitivity analysis.
  - Full test suite passing: 466 tests in 9.4s.

---

## [0.1.0-dev] - Milestone P09

### Added
- **Simultaneous Multi-Train Microscopic Simulator (`headway.simulation.multi_train_engine`):**
  - Shared multi-train simulation clock and discrete-time event stepper advancing all active trains simultaneously under unified signalling/resource state.
  - Continuous train-front and train-rear tracking ($s_{\mathrm{rear}} = s_{\mathrm{front}} - L_{\mathrm{train}}$) across physical links without independent trajectory shifting.
  - Force balance and distributed resistance integration based on P04 physics (`ForceBalanceEngine` & `DistributedResistanceEngine`).
  - Speed enforcement against line limits, dynamic service braking deceleration profiles, and movement authorities.
  - Complete support for `RunningDirection.FORWARD` and `RunningDirection.REVERSE` railway operations.
- **Train Service Instances & Generation (`headway.simulation.service_instance`):**
  - `ServiceType` definition linking rolling stock, route, stops, priority, and directionality.
  - `TrainServiceInstance` tracking microscopic dynamics, operational state machines, cumulative and primary delays, and boundary events.
  - `TrainGenerator` supporting single, pairwise, fixed-interval ($t_n = t_0 + nH$), repeated homogeneous, repeated mixed-traffic, and timetable generation.
- **Origin Queue & Dispatching Engine (`headway.simulation.dispatching`):**
  - `OriginDepartureQueue` managing pending departures at route origin links.
  - Four dispatching policies: `FIRST_COME_FIRST_SERVED`, `TIMETABLE_ORDER`, `PRIORITY_BASED`, and `FIXED_SEQUENCE`.
  - Deterministic tie-breaking on identical timestamps and safety priority gating against occupied entry blocks.
  - Starvation warning emission when train waiting times exceed configured thresholds.
  - Departure delay calculation: $D_{\mathrm{departure}} = t_{\mathrm{actual}} - t_{\mathrm{requested}}$.
- **Operational Signalling, Station & TVS Integrations:**
  - Common movement authority interface across Fixed-Block (P05), ETCS Level 2 (P06), and CBTC Moving-Block (P06).
  - Station stops with deterministic dwell times, platform entry locking, and rear-clearance-based release delay timers.
  - Multi-platform allocation with fallback alternatives (`PREFERRED_WITH_ALTERNATIVES`, `EARLIEST_FEASIBLE`).
  - Junction interlocking route sequencing, route locking, and release.
  - TVS entry authorization, protection holding points, complete rear clearance, shared group exclusivity, and queue tracking (`TVSQueueTracker`).
- **Deadlock Detection & Graph Analysis (`headway.simulation.deadlock`):**
  - Directed wait-for dependency graph construction (`build_wait_graph`).
  - Cycle detection using Tarjan's algorithm / DFS finding circular resource waits.
  - Single-track opposing head-on deadlock detection (`detect_opposing_head_on_deadlock`).
  - Structured deadlock reporting (`DeadlockReport`) and optional simulation termination (`DeadlockError`).
- **Journey-Time & Delay Analysis (`headway.analysis.journey_time` & `headway.analysis.delays`):**
  - Additive journey-time decomposition ($T_{\mathrm{operational}} = T_{\mathrm{unconstrained}} + \sum D_k$): moving time, planned dwell, dwell extension, TVS waiting, junction waiting, platform waiting, signalling waiting, and braking/reacceleration losses.
  - Schedule delay attribution ($D = t_{\mathrm{actual}} - t_{\mathrm{scheduled}}$) with primary and secondary delay separation.
  - Operational KPIs calculation (`OperationalKPIs`): requested, dispatched, and completed trains, punctuality percentage, delay statistics, and departure sequences.
- **Time-Distance Dataset Export (`headway.simulation.time_distance`):**
  - `MultiTrainTimeDistanceDataset` storing high-resolution time-distance points for all active trains.
  - Preserved route identity, chainage, speed, acceleration, and operational state for downstream visualization (P13).
  - DataFrame export utility (`to_dataframe`).
- **Verification Benchmarks & Tests (`tests/engineering/`, `tests/unit/`, `tests/integration/`):**
  - 35 mandatory benchmarks (P09-B001 through P09-B035) plus Numerical Benchmarks A–D (39 engineering tests in `test_multi_train_benchmarks.py`).
  - 10 unit negative tests for error handling, parameter validation, and deadlocks (`test_multi_train_negative.py`).
  - 3 integration tests covering end-to-end multi-train multi-station corridors, dispatching policies, and bidirectional traversals (`test_multi_train_integration.py`).

---

## [0.1.0-dev] - Milestone P08

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
