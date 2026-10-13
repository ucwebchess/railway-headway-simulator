# Comprehensive Demonstration Line (`05_comprehensive_line`)

## 1. Overview & Purpose

The **Comprehensive Demonstration Line** (`05_comprehensive_line`) is the reference multi-train, multi-service corridor benchmark for the Railway Headway Simulator. It exercises all architectural subsystems and capabilities of the platform within a unified, fully validated dataset:

- **Bidirectional double-track corridor** with an active overtaking loop / siding segment.
- **Physical route gradients, speed transitions, and complex station layouts**.
- **A 5.0 km bored mountain tunnel** protected by 4 Tunnel Ventilation System (TVS) sub-segments and a single-train occupancy safety group.
- **Generic 3-aspect fixed-block signalling** with 18 signals, 18 block sections, and 6 interlocking route paths.
- **Heterogeneous rolling stock fleet** featuring High-Speed Passenger (`TRN_HSR`), Regional Commuter (`TRN_REG`), and Heavy Freight (`TRN_FRT`) consists with full Davis resistance coefficients and piecewise non-linear traction and deceleration curves.
- **Complex mixed-traffic operational patterns** and multi-train headway evaluation in both `FORWARD` and `REVERSE` running directions.
- **Scenario variations** demonstrating sensitivity to block layout, civil speed enhancements, dwell expansion, and tunnel ventilation safety criteria.

---

## 2. Infrastructure Specification (`01_Infrastructure.xlsx`)

The physical infrastructure corridor spans approximately 26.0 km between Terminal North (`ND_01`) and Terminal South (`ND_11`), comprising 11 topology nodes, 3 tracks, and 18 track links.

### 2.1 Track Definitions
| Track ID | Description | Directionality |
| :--- | :--- | :--- |
| `TRK_UP` | Main Line Up (North to South) | `NOMINAL` (North to South) |
| `TRK_DN` | Main Line Down (South to North) | `NOMINAL` (South to North) |
| `TRK_SIDING` | Mid-Corridor Overtaking Loop / Freight Siding | `BIDIRECTIONAL` |

*Note on Canonical Directionality Semantics*: In the canonical railway model, `TrackDirectionality` is defined strictly relative to each link's local topological orientation (`start_node_id` $\to$ `end_node_id`). Because the Down track links (`LNK_11` through `LNK_17`) are explicitly oriented in the operational direction of train travel from South (`ND_11`) to North (`ND_01`), `TRK_DN` is configured as `NOMINAL` so that `RunningDirection.FORWARD` traversals along those links are permitted without contradiction.

### 2.2 Corridor Alignment & Track Links
| Link ID | Track ID | Start Node | End Node | Length [m] | Speed Limit [km/h] | Gradient [‰] | Description / Landmark |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `LNK_01` | `TRK_UP` | `ND_01` | `ND_02` | 3,000 | 160 | 0.0 | Terminal North Departure |
| `LNK_02` | `TRK_UP` | `ND_02` | `ND_03` | 1,000 | 100 | +2.0 | Station Alpha Approach & Platforms |
| `LNK_03` | `TRK_UP` | `ND_03` | `ND_04` | 4,000 | 160 | -3.0 | North Inter-Station Section |
| `LNK_04` | `TRK_UP` | `ND_04` | `ND_05` | 2,000 | 140 | 0.0 | Mid-Junction Up Main Through Track |
| `LNK_05` | `TRK_UP` | `ND_05` | `ND_06` | 3,500 | 160 | +5.0 | Rolling Ascent Section |
| `LNK_06` | `TRK_UP` | `ND_06` | `ND_07` | 1,000 | 100 | 0.0 | Station Beta Approach & Platforms |
| `LNK_07` | `TRK_UP` | `ND_07` | `ND_08` | 2,500 | 140 | -2.0 | Tunnel Northern Approach |
| `LNK_08` | `TRK_UP` | `ND_08` | `ND_09` | 5,000 | 120 | 0.0 | Comprehensive Model Tunnel (`TNL_01`) |
| `LNK_09` | `TRK_UP` | `ND_09` | `ND_10` | 2,000 | 120 | +1.0 | Tunnel Southern Exit |
| `LNK_10` | `TRK_UP` | `ND_10` | `ND_11` | 1,000 | 80 | 0.0 | Station Gamma & Terminal South |
| `LNK_11` | `TRK_DN` | `ND_11` | `ND_10` | 1,000 | 80 | 0.0 | Terminal South Departure (Down Line) |
| `LNK_12` | `TRK_DN` | `ND_10` | `ND_09` | 2,000 | 120 | -1.0 | Down Tunnel Approach |
| `LNK_13` | `TRK_DN` | `ND_09` | `ND_08` | 5,000 | 120 | 0.0 | Down Tunnel Segment |
| `LNK_14` | `TRK_DN` | `ND_08` | `ND_07` | 2,500 | 140 | +2.0 | Down Tunnel Exit Ascent |
| `LNK_15` | `TRK_DN` | `ND_07` | `ND_05` | 4,500 | 160 | 0.0 | Down Station Beta Inter-Station |
| `LNK_16` | `TRK_DN` | `ND_05` | `ND_03` | 6,000 | 160 | 0.0 | Down Mid-Corridor Long Section |
| `LNK_17` | `TRK_DN` | `ND_03` | `ND_01` | 4,000 | 160 | 0.0 | Down Station Alpha & Terminal North |
| `LNK_18` | `TRK_SIDING` | `ND_04` | `ND_05` | 2,000 | 80 | 0.0 | Mid-Junction Loop / Freight Siding |

### 2.3 Passenger Stations & Platform Allocations
Three stations with 8 total platform faces:
- **Station Alpha (`STN_ALPHA`)** at km 3.5:
  - `PLT_A1`: Track Link `LNK_02`, offset 100 m – 500 m (Length: 400 m), Stopping Point `SP_A1` (450 m).
  - `PLT_A2`: Track Link `LNK_02`, offset 550 m – 950 m (Length: 400 m), Stopping Point `SP_A2` (900 m).
  - `PLT_A3`: Track Link `LNK_17`, offset 100 m – 500 m (Length: 400 m), Stopping Point `SP_A3` (450 m).
- **Station Beta (`STN_BETA`)** at km 14.0:
  - `PLT_B1`: Track Link `LNK_06`, offset 100 m – 500 m (Length: 400 m), Stopping Point `SP_B1` (450 m).
  - `PLT_B2`: Track Link `LNK_06`, offset 550 m – 950 m (Length: 400 m), Stopping Point `SP_B2` (900 m).
  - `PLT_B3`: Track Link `LNK_15`, offset 100 m – 500 m (Length: 400 m), Stopping Point `SP_B3` (450 m).
- **Station Gamma (`STN_GAMMA`)** at km 23.5:
  - `PLT_G1`: Track Link `LNK_10`, offset 100 m – 500 m (Length: 400 m), Stopping Point `SP_G1` (450 m).
  - `PLT_G2`: Track Link `LNK_11`, offset 100 m – 500 m (Length: 400 m), Stopping Point `SP_G2` (450 m).

### 2.4 Tunnel & TVS Architecture
- **Tunnel `TNL_01`**: 5.0 km length on `LNK_08`.
- Subdivided into 4 TVS sections of 1,250 m each:
  - `TVS_01`: [0 m, 1,250 m], max occupancy 1, holding signal `SIG_UP_08`.
  - `TVS_02`: [1,250 m, 2,500 m], max occupancy 1.
  - `TVS_03`: [2,500 m, 3,750 m], max occupancy 1.
  - `TVS_04`: [3,750 m, 5,000 m], max occupancy 1.
- **Shared Resource Group `SRG_TUNNEL`**: Enforces corridor-wide single-train occupancy across `{TVS_01, TVS_02, TVS_03, TVS_04}` under emergency ventilation regime.

### 2.5 Design Rationale: Asymmetric TVS Allocation (UP Track vs. DN Track)

The allocation of TVS sections exclusively to the UP track (`LNK_08`) while the DN tunnel segment (`LNK_13`) operates without TVS sections is an **intentional engineering design decision** based on three key factors:

1. **Twin-Bore Infrastructure Differentiation**:
   The corridor models a twin single-track base tunnel system with segregated ventilation and safety concepts:
   - **Bore 1 (`TRK_UP`, `LNK_08`)**: Represents an active, mechanically ventilated tunnel tube equipped with four sectional Tunnel Ventilation System zones (`TVS_01`–`TVS_04`), holding signal `SIG_UP_08`, and single-train group protection (`SRG_TUNNEL`).
   - **Bore 2 (`TRK_DN`, `LNK_13`)**: Represents a dedicated uncompartmentalized running tube governed purely by conventional lineside signalling blocks (`BLK_DN_03`), representing a passive ventilation or unrestricted baseline tube.

2. **Comparative Benchmark for TVS Headway Penalties**:
   A primary objective of this reference line is to allow direct comparative assessment of the capacity impact of tunnel ventilation constraints:
   - Headway analysis `AN_TVS_UP` evaluates operations under active TVS and shared resource group safety constraints on `LNK_08`.
   - Headway analyses `AN_HSR_HSR_DN` and `AN_REG_REG_DN` evaluate operations over the identical 5,000 m tunnel physical length on `LNK_13` governed solely by fixed-block signalling.
   - Comparing the resulting headways quantitatively isolates the exact "TVS safety penalty" against a baseline unconstrained tunnel crossing.

3. **Specification & Schema Registry Alignment**:
   The benchmark dataset specification (`RHS-EXPAND-EXAMPLES-001 § 7.1` and `§ 7.6`) explicitly mandates exactly four TVS sections (`TVS_01`–`TVS_04`) and one shared resource group (`SRG_TUNNEL`). Replicating TVS sections on `LNK_13` would alter canonical entity counts (expanding from 4 to 8 TVS sections) and eliminate the deliberate comparative baseline.

---

## 3. Signalling System (`02_Signalling.xlsx`)

- **Technology**: `GENERIC_FIXED_BLOCK_ENGINEERING_MODEL`
- **Aspect Model**: `THREE_ASPECT` (Green, Yellow, Red)
- **Timing Parameters**: Default overlap 50.0 m, driver sighting time 8.0 s, interlocking route setup 3.0 s, resource release delay 4.0 s.
- **Signals**: 18 lineside signals (`SIG_UP_01` to `SIG_UP_10`, `SIG_DN_01` to `SIG_DN_07`, and siding signal `SIG_SD_01`).
- **Blocks**: 18 signalling block sections matching each link interval with safety overlap.
- **Interlocking Routes**:
  1. `RT_UP_MAIN`: Full north-to-south UP corridor through main line links (`LNK_01`–`LNK_10`).
  2. `RT_UP_SIDING`: Bypass route routing trains through siding track `LNK_18` between `ND_04` and `ND_05`. Conflicts with `RT_UP_MAIN`.
  3. `RT_DN_MAIN`: Full south-to-north DOWN corridor through Down line links (`LNK_11`–`LNK_17`).
  4. `RT_UP_SHORT`: Short turnback route terminating at Station Beta (`SIG_UP_07`).
  5. `RT_DN_SHORT`: Short Down line entry route from Station Beta South to Terminal North.
  6. `RT_TVS_SEG`: Isolated tunnel and TVS ventilation evaluation route segment (`LNK_07`–`LNK_09`).

---

## 4. Rolling Stock Fleet (`03_RollingStock.xlsx`)

Three distinct train configurations represent the spectrum of main line operations:

| Parameter | High-Speed Passenger (`TRN_HSR`) | Regional Commuter (`TRN_REG`) | Heavy Freight (`TRN_FRT`) |
| :--- | :--- | :--- | :--- |
| **Description** | Intercity Express Train | Commuter EMU | Heavy Freight Train |
| **Length [m]** | 200.0 | 150.0 | 500.0 |
| **Tare / Loaded Mass [t]** | 400.0 / 450.0 | 160.0 / 200.0 | 800.0 / 2,000.0 |
| **Rotating Mass Factor** | 0.08 | 0.10 | 0.12 |
| **Max Operational Speed** | 200.0 km/h | 160.0 km/h | 100.0 km/h |
| **Max Initial Acceleration** | 0.80 m/s² | 1.00 m/s² | 0.40 m/s² |
| **Service Deceleration** | 0.90 m/s² | 1.00 m/s² | 0.50 m/s² |
| **Emergency Deceleration** | 1.20 m/s² | 1.30 m/s² | 0.70 m/s² |
| **Installed Power [kW]** | 8,000 | 3,000 | 4,500 |
| **Maximum Tractive Effort**| 300.0 kN | 220.0 kN | 400.0 kN |
| **Davis $A$ [kN]** | 3.500 | 2.200 | 8.000 |
| **Davis $B$ [kN/(km/h)]** | 0.040 | 0.030 | 0.080 |
| **Davis $C$ [kN/(km/h)²]**| 0.0006 | 0.0004 | 0.0010 |

Detailed 5-point non-linear traction and deceleration curves are configured for each train type, accurately reflecting motor torque rolloff and brake disc temperature-friction characteristics.

---

## 5. Operations & Service Patterns (`04_Operations.xlsx`)

Six service patterns model diverse operational duties:

1. **`SVC_HSR_EXP_UP`**: High-Speed Express (North $\to$ South). Calls at `STN_BETA` (dwell 90 s); bypasses other stations. Planned headway: 15 min.
2. **`SVC_REG_ALL_UP`**: Regional All-Stops (North $\to$ South). Calls at `STN_ALPHA` (60 s), `STN_BETA` (75 s), and `STN_GAMMA` (60 s). Planned headway: 10 min.
3. **`SVC_FRT_THRU_UP`**: Heavy Freight Through Service (North $\to$ South). Non-stop traversal. Planned headway: 30 min.
4. **`SVC_HSR_EXP_DN`**: High-Speed Express Reverse (South $\to$ North). Calls at `STN_BETA` (dwell 90 s). Planned headway: 15 min.
5. **`SVC_REG_ALL_DN`**: Regional All-Stops Reverse (South $\to$ North). Calls at `STN_GAMMA` (60 s), `STN_BETA` (75 s), and `STN_ALPHA` (60 s). Planned headway: 10 min.
6. **`SVC_FRT_LOOP_UP`**: Heavy Freight Siding Route (North $\to$ South). Operates via siding link `LNK_18` for passenger overtaking. Planned headway: 30 min.

---

## 6. Headway Analysis Configurations (`05_HeadwayAnalysis.xlsx`)

Ten analysis cases evaluate corridor limits:
- **`AN_HSR_HSR_UP`**: Homogeneous high-speed train follower headway on UP corridor.
- **`AN_REG_REG_UP`**: Homogeneous regional commuter headway with all-stop dwell penalties.
- **`AN_FRT_FRT_UP`**: Homogeneous heavy freight headway constrained by braking distance and low acceleration.
- **`AN_HSR_REG_UP`**: Heterogeneous headway: High-speed leader followed by Regional commuter.
- **`AN_REG_HSR_UP`**: Heterogeneous headway: Regional leader followed by High-speed express.
- **`AN_FRT_HSR_UP`**: Mixed freight-passenger headway.
- **`AN_HSR_HSR_DN`**: Directional verification: High-speed headway along Down corridor (South to North).
- **`AN_REG_REG_DN`**: Directional verification: Regional commuter headway along Down corridor (South to North).
- **`AN_TVS_UP`**: TVS comparison analysis on tunnel segment `LNK_08`.
- **`AN_HIGHRES_UP`**: High-precision integration analysis (0.05 s step, 0.01 s tolerance).

---

## 7. Scenario Registry (`06_Scenarios.xlsx`)

Five study scenarios evaluate infrastructure and operational variations:
- **`SCN_BASELINE`**: Baseline infrastructure geometry, 3-aspect block layout, and nominal operating speeds.
- **`SCN_BLOCK_LENGTH`**: Evaluates block section subdivision on `BLK_UP_01` (reduced from 3,000 m to 1,500 m) to relieve headway bottlenecks.
- **`SCN_SPEED_UPGRADE`**: Infrastructure speed limit enhancement on `LNK_01` from 160 km/h to 200 km/h.
- **`SCN_STATION_DWELL`**: Operations stress test: Regional dwell extension to 120 s during peak passenger surge.
- **`SCN_TUNNEL_SAFETY`**: Safety rule comparison: Evaluates TVS multi-train occupancy ($N=2$) versus single-train rule ($N=1$).

---

## 8. Usage & Verification

### Regenerating Workbooks
The dataset can be regenerated at any time from code:
```bash
python3 examples/05_comprehensive_line/generate.py
```

### Loading via UI
1. Launch the web interface (`headway-ui` or `python3 run.py`).
2. Navigate to **Tab 2: Data Import**.
3. Select `05_comprehensive_line` from the official examples dropdown.
4. Click **📂 Load Selected Example**.

### Loading via Python API
```python
from headway.ui.file_manager import FileManager
from headway.infrastructure.direction import RunningDirection
from headway.ui.simulation_runner import SimulationRunner

# Load canonical representation
project, report, files = FileManager.load_example_project("05_comprehensive_line")
assert report.is_simulation_ready

# Run FORWARD or REVERSE simulation pipeline
pkg, doc = SimulationRunner.run_simulation_pipeline(
    project=project,
    running_direction=RunningDirection.FORWARD,
)
print(f"Technical minimum headway: {doc.executive_kpis.technical_headway_s:.1f} s")
```
