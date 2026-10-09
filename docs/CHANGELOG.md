# CHANGELOG
## Railway Headway & Capacity Simulator

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0-dev] - Milestone P01 (Current Milestone)

### Added
- **Centralized Units and Normalization (`headway.core.units`):**
  - Strict SI conversion functions for distance ($m$), speed ($m/s$), mass ($kg$), force ($N$), power ($W$), energy ($J$), time ($s$), acceleration ($m/s^2$), gradient ($m/m$), curvature ($m$).
  - Mathematical normalization of Davis polynomial resistance coefficients ($A$, $B$, $C$) from $kN$ and $km/h$ into pure SI units ($N$, $N\cdot s/m$, $N\cdot s^2/m^2$).
- **Identifier Management (`headway.core.identifiers`):**
  - Whitespace-trimming without case alteration.
  - Regex syntax verification (`^[A-Za-z0-9_][A-Za-z0-9_\-\.:]*$`).
  - Namespace-aware `IdentifierRegistry` with duplicate detection and foreign reference verification.
- **Canonical Data Models (`headway.data.canonical`):**
  - Strongly typed Pydantic v2 canonical models for Infrastructure, Rolling Stock, Signalling, Operations, Analysis, and Scenarios with strict extra-field rejection.
- **JSON Schema Draft 2020-12 Artifacts (`schemas/`):**
  - 16 verified Draft 2020-12 schema files covering project, domains, simulation events, resource usages, headway, capacity, TVS, and report results.
- **Authoritative Excel Schema Registry (`headway.data.excel_registry`):**
  - Single source of truth governing workbook definitions, worksheet layouts, columns, units, types, and enum constraints.
- **Excel Template Generator (`headway.data.template_generator`):**
  - Automatic generation of the 6 standardized workbooks (`HEADWAY_INFRASTRUCTURE_v1.0.xlsx` through `HEADWAY_SCENARIOS_v1.0.xlsx`) with openpyxl styling and dropdown data validations.
- **Excel Importer (`headway.data.importer`):**
  - Robust parser reading cached formula values (`data_only=True`), rejecting macro files (`.xlsm`), identifying workbooks via `METADATA`, and filtering example rows (`EXAMPLE_*`).
- **Multi-Level Validation Framework (`headway.data.validator`, `headway.data.validation`):**
  - Structured `ValidationFinding` reporting across Levels 1–5 with error codes, severities, Excel coordinates, recommendations, and Excel export capability.
- **Raw-to-Canonical Converter (`headway.data.converter`):**
  - Conversion pipeline translating parsed Excel records into canonical SI models.
- **Deterministic Serialization & Hashing (`headway.data.serializer`, `headway.data.hashing`):**
  - Deterministic JSON serializer (NaN/inf rejection, Draft 2020-12 schema validation).
  - SHA-256 hashing for source files, canonical projects, and scenarios.
- **Scenario Foundation (`headway.scenarios.engine`):**
  - Baseline immutability preservation, scalar parameter overrides, and isolated effective configuration derivation.
- **Project Packaging (`headway.data.package`):**
  - Safe ZIP project archive export and import protecting against path traversal, absolute paths, and decompression bombs.
- **Official Example Datasets (`examples/`):**
  - `01_single_track`, `02_double_track`, `03_station_platform`, and `04_tunnel_tvs`, each containing all 6 workbooks and passing full validation.

---

## [0.1.0-dev] - Milestone P00 Baseline

### Added
- Package foundation (`src/headway/core`, `ui`, subpackage scaffolds).
- Application configuration, logging, and structured exceptions.
- Gradio Blocks UI shell with 10 navigation tabs and reference report styling.
- Google Colab launcher notebook (`colab/Railway_Headway_Simulator.ipynb`).
- Initial documentation suite and automated pytest framework.
