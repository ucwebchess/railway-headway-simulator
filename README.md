# Railway Headway & Capacity Simulator

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.1.0--dev-orange.svg)](docs/CHANGELOG.md)
[![Phase](https://img.shields.io/badge/phase-P00%20Foundation-teal.svg)](docs/DEVELOPMENT_MANIFEST.md)
[![UI: Gradio](https://img.shields.io/badge/UI-Gradio%20Blocks-blueviolet.svg)](src/headway/ui/app.py)

A modular, microscopic railway simulation software system designed to calculate individual train trajectories, technical minimum headway, signalling blocking-time stairways, TVS (Tunnel Ventilation Section) constraints, and line operational capacity with engineering precision comparable to specialized commercial rail tools.

---

### ⚠️ IMPORTANT ENGINEERING DISCLAIMER (MILESTONE P00)

**The current software version (`0.1.0-dev`) represents the P00 Project Foundation milestone.**

In strict adherence to **Master AI-Agent Governance Directive RHS-MASTER-001** and prompt **RHS-P00-001 § 22**:
- This release provides the modular package architecture, configuration framework, logging subsystem, structured exceptions, automated test suites, Google Colab launcher notebook, and Gradio user interface shell.
- **No railway engineering calculations (train dynamics, Davis resistance, signalling aspect evaluation, headway calculations, capacity estimation, or TVS controls) are implemented in Milestone P00.**
- All user-interface KPI cards and downstream calculation tabs are explicitly marked as unavailable placeholders.
- Microscopic simulation algorithms will be introduced sequentially across milestones P01 through P15.

---

## 1. Project Objectives

When fully implemented across Milestones P01–P15, the Railway Headway & Capacity Simulator will provide:
- **Microscopic Train Dynamics:** Deterministic 0.1-second numerical integration accounting for equivalent dynamic mass $m(1+\lambda)$, Davis polynomial drag, distributed gradient and curve resistance over physical train length.
- **Physical Network Model:** 1D continuous topological network with separate route distance and engineering chainage.
- **Signalling Systems:** Fixed-block (2, 3, and 4-aspect), ETCS Level 2, and CBTC moving-block models with realistic sighting distances and overlaps.
- **Tunnel Ventilation Sections (TVS):** Strict single-train TVS occupancy rule enforcement, holding point management, and queue delay analysis.
- **Seven-Component Blocking Times:** Additive, non-overlapping blocking time calculation (Setup, Approach, Running, Dwell, Clearance, Residual, Release).
- **Technical Minimum Headway:** Rigorous pairwise leader–follower headway search $H(i, j)$ preserving unimpeded reference trajectories.
- **Capacity & Throughput:** Theoretical homogeneous capacity, planning operational capacity with operational margins, and UIC 406-inspired assessment.
- **Stochastic Simulation:** Monte Carlo perturbation analysis (dwell variations, driver response, traction variability) for operational reliability.
- **Professional Reporting:** Automated export of executive engineering reports (PDF, HTML, Excel, CSV, JSON) conforming to reference standards.

---

## 2. Technology Stack

- **Core Programming Language:** Python >= 3.10 (Tested on Python 3.13)
- **User Interface Framework:** Gradio (Blocks API with custom engineering theme)
- **Development & Execution Target:** Google Colab / Linux / macOS / Windows
- **Testing & Verification:** pytest (Unit, Integration, Engineering Benchmarks, Regression)
- **Data Validation & Schemas:** Pydantic / JSON Schema (Milestone P01)
- **Data Handling:** pandas / openpyxl (Ingestion in Milestone P01)
- **Visualization:** Plotly (Milestone P13)

---

## 3. Repository Architecture

```text
railway-headway-simulator/
├── colab/
│   └── Railway_Headway_Simulator.ipynb     # Google Colab application launcher
│
├── src/
│   └── headway/
│       ├── __init__.py                     # Package entry and version export
│       ├── __main__.py                     # CLI launcher (headway-sim / python -m headway)
│       │
│       ├── core/                           # Application foundation
│       │   ├── configuration.py            # Strongly typed AppConfig & Colab detector
│       │   ├── exceptions.py               # Structured exception hierarchy
│       │   ├── logging_config.py           # Centralized contextual logging
│       │   └── version.py                  # Single authoritative version source
│       │
│       ├── data/                           # Data ingestion & canonical contracts (P01)
│       ├── infrastructure/                 # 1D physical network model & TVS (P02)
│       ├── rolling_stock/                  # Train physics & Davis resistance (P03)
│       ├── signalling/                     # Fixed-block, ETCS L2, CBTC models (P05/P06)
│       ├── simulation/                     # 0.1s microscopic motion solver (P04/P07/P09)
│       ├── analysis/                       # 7-component blocking time & headway (P08/P10/P11)
│       ├── scenarios/                      # Scenario branching & overrides (P12)
│       ├── reporting/                      # PDF, HTML & calculation exports (P14)
│       │
│       └── ui/                             # Gradio user interface subsystem
│           ├── app.py                      # 10-tab application shell & dashboard
│           ├── components.py               # Header, KPI cards, diagnostics widgets
│           └── theme.py                    # Engineering color scheme & styling
│
├── schemas/                                # Canonical JSON schema definitions
├── templates/                              # Standardized Excel input templates
├── examples/                               # Reference project packages & benchmarks
│
├── tests/
│   ├── unit/                               # Unit test suite
│   ├── integration/                        # Module integration tests
│   ├── engineering/                        # Engineering benchmark verifications
│   ├── regression/                         # Regression defect prevention
│   └── end_to_end/                         # End-to-end operational workflows
│
├── docs/
│   ├── MASTER_SRS.md                       # Master SRS Parts 1–14 reference
│   ├── ENGINEERING_CONTRACT.md             # Equations of motion, SI units, blocking times
│   ├── DATA_CONTRACTS.md                   # Canonical data model specifications
│   ├── EXCEL_SCHEMA.md                     # 6-workbook Excel input schema
│   ├── BENCHMARK_REGISTER.md               # Analytical verification benchmarks
│   ├── ARCHITECTURE.md                     # Layered software architecture
│   ├── DEVELOPMENT_MANIFEST.md             # Live milestone status manifest
│   ├── PROMPT_REGISTER.md                  # Development prompt history
│   ├── CHANGELOG.md                        # Version changelog
│   └── KNOWN_LIMITATIONS.md                # Functional limitations register
│
├── requirements.txt                        # Foundation pip dependencies
├── pyproject.toml                          # Standard packaging configuration
├── LICENSE                                 # Intellectual property notice
├── .gitignore                              # Git exclusion rules
└── .python-version                         # Python version specification
```

---

## 4. Installation & Local Setup

### Prerequisites
- Python 3.10 or newer
- `pip` and `virtualenv` (recommended)

### Local Environment Installation
```bash
# Clone the repository
git clone <REPOSITORY_URL>
cd railway-headway-simulator

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package in editable mode with development tools
pip install -e ".[dev]"
```

---

## 5. Running the Application

### 5.1 Google Colab Launch
1. Open Google Colab: [colab.research.google.com](https://colab.research.google.com).
2. Upload and open `colab/Railway_Headway_Simulator.ipynb`.
3. Follow the sequential cells:
   - **Cell 1:** Runtime verification.
   - **Cell 2:** Package installation via `pip install -e .`.
   - **Cell 3:** Configuration and storage directory setup.
   - **Cell 4:** Launch the interactive Gradio Blocks UI inline within the notebook.

### 5.2 Local Terminal Launch
Launch the application using either the CLI command or module syntax:
```bash
# Using package script
headway-sim --port 7860

# Or using Python module execution
python -m headway --port 7860 --log-level INFO
```
Then open your browser at `http://127.0.0.1:7860`.

---

## 6. Running Automated Tests

Run the test suite using `pytest`:
```bash
# Run all automated tests
pytest

# Run unit tests only
pytest tests/unit

# Run integration tests
pytest tests/integration

# Run with verbose output
pytest -v
```

---

## 7. 15-Prompt Development Roadmap

| Prompt | Scope | Milestone Status |
|---|---|---|
| **P00** | Project Foundation, Architecture, Testing & Colab Launcher | **COMPLETED** |
| **P01** | Canonical Data Architecture & Excel Input System | Authorized Next |
| **P02** | Infrastructure Network Model & Topology | Reserved |
| **P03** | Rolling Stock Characteristics & Physics | Reserved |
| **P04** | Braking Models & Numerical Solver | Reserved |
| **P05** | Resource Management Engine & Fixed-Block Signalling | Reserved |
| **P06** | Advanced Signalling (ETCS Level 2 & CBTC) | Reserved |
| **P07** | Stations, Junctions & TVS Control Engine | Reserved |
| **P08** | Seven-Component Blocking Time & Headway Analysis | Reserved |
| **P09** | Multi-Train Operational Simulation Engine | Reserved |
| **P10** | Line Capacity & UIC 406-Inspired Analysis | Reserved |
| **P11** | Stochastic Simulation & Operational Reliability | Reserved |
| **P12** | Scenario Management & Sensitivity Engine | Reserved |
| **P13** | Interactive Engineering Visualizations | Reserved |
| **P14** | Professional Engineering Reporting System | Reserved |
| **P15** | Full Gradio UI Integration & Final Verification | Reserved |
