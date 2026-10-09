# EXCEL INPUT SYSTEM SCHEMA & SPECIFICATION
## Railway Headway & Capacity Simulator

**Document ID:** RHS-XLS-001  
**Version:** 1.0.0  
**Status:** IMPLEMENTED & OPERATIONAL (Milestone P01)  
**Governing Prompt:** RHS-P01-001 § 13 & § 14  
**Implementation Source:** `headway.data.excel_registry` & `headway.data.template_generator`  

---

### 1. Authoritative Schema Architecture

Per **RHS-P01-001 § 13 (P01-XLS-007)**:
A single authoritative worksheet schema registry (`headway.data.excel_registry`) defines all field names, data types, unit conventions, requirement flags, and allowed enumerations. Both the template generator and the Excel importer derive their operational logic directly from this registry.

---

### 2. Standardized Workbooks

The simulator supports six standardized Microsoft Excel (`.xlsx`) workbooks:

| Workbook # | Template Filename | Worksheets / Tabs | Purpose |
|---|---|---|---|
| **WB-01** | `HEADWAY_INFRASTRUCTURE_v1.0.xlsx` | `METADATA`, `Nodes`, `Tracks`, `TrackLinks`, `Stations`, `Platforms`, `StoppingPoints`, `Tunnels`, `TVSSections`, `SharedResourceGroups` | Physical network topology, 1D links, alignment geometry, stations, and TVS ventilation boundaries. |
| **WB-02** | `HEADWAY_SIGNALLING_v1.0.xlsx` | `METADATA`, `SignallingSystem`, `Signals`, `Blocks`, `InterlockingRoutes` | Signalling system rules, signals, fixed blocks, overlaps, and route conflicts. |
| **WB-03** | `HEADWAY_ROLLING_STOCK_v1.0.xlsx` | `METADATA`, `TrainTypes`, `TractionCurves`, `BrakingCurves` | Rolling stock fleet parameters, Davis polynomial resistance, traction curves, and deceleration models. |
| **WB-04** | `HEADWAY_OPERATIONS_v1.0.xlsx` | `METADATA`, `ServicePatterns`, `StoppingPatterns` | Operational service patterns, route link sequences, stopping patterns, and dwell durations. |
| **WB-05** | `HEADWAY_ANALYSIS_v1.0.xlsx` | `METADATA`, `AnalysisSettings` | Headway analysis pairs, simulation integration steps, convergence tolerances, and planning margins. |
| **WB-06** | `HEADWAY_SCENARIOS_v1.0.xlsx` | `METADATA`, `ScenarioDefinitions`, `Overrides` | Alternative scenario definitions and targeted scalar parameter overrides. |

---

### 3. Ingestion & Security Rules

1. **Macro Prohibition:** Workbooks containing VBA macros (`.xlsm`) are strictly rejected (`ERR_SECURITY_MACRO_REJECTED`).
2. **Workbook Identity:** Ingestion detects workbook identity via the `METADATA` sheet (`WORKBOOK_TYPE` property), not file naming.
3. **Cached Formula Reading:** Workbooks are loaded with `data_only=True` to read cached formula evaluations without macro execution.
4. **Instructional Example Rows:** Example rows marked with `EXAMPLE_*` IDs are automatically recognized and omitted from imported simulation datasets.
5. **No Direct Simulation:** The microscopic simulation engine never accesses Excel files directly; all data is converted into canonical SI models.
