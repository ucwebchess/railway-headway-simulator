# High-Speed Rail 140 km Corridor Example (`07_hsr_140km`)

> **Fixture scope — read before interpreting any metric in this document.**  
> This fixture is a *representative* 320 km/h high-speed corridor stress model. It reproduces the target corridor's topology (447 links, 448 nodes, 92 blocks, 91 signals), rolling stock (`TRN_HSR`, 8-car, 202 m, 465/485 t, 320 km/h, Davis A=2.506 kN / B=0.04065 / C=0.00043), and operations (`SRV_6000`, 5 stops, 120 s dwell). It does **not** reproduce the user's project exactly. Three differences are material:
>
> 1. **Station positions.** The fixture places intermediate stations at 35.0 km, 70.0 km, and 105.0 km (evenly spaced). The user's corridor places them at 4.4 km, 24.21 km, and 101.79 km — producing one uninterrupted 78 km non-stop segment between `STN_YAS` and `STN_MKT`. The fixture inserts one extra kinetic stop penalty (≈111 s) and one extra 120 s dwell that the user's corridor does not contain.
> 2. **Signalling aspect model.** The fixture uses `THREE_ASPECT`. The user's project uses `TWO_ASPECT`. Minimum headway is aspect-model sensitive.
> 3. **Tunnel / TVS.** The fixture has no tunnel sections. The user's corridor includes `TNL_01` with 14 TVS sections.
>
> Consequently, the 2,575 s (100 % PF) total service duration and the 52.9 s technical minimum headway reported for this fixture are **not** predictions for the user's project. Validation against the user's actual Excel workbooks is tracked as Phase 1 Closeout (see below).

---

The **High-Speed Rail 140 km Corridor** (`07_hsr_140km`) reference dataset models a microscopic 140 km, 320 km/h intercity high-speed passenger corridor operating under ETCS Level 2 cab signalling.

---

## 1. Executive Summary & Purpose

This dataset serves as the benchmark for large-scale corridor simulation and headway analysis:
- **Corridor Length**: 140,000 m (140.0 km) of continuous civil infrastructure.
- **Topological Density**: 447 track links (`LNK_0001` to `LNK_0447`), 448 nodes (`ND_0001` to `ND_0448`), single running track (`TRK_UP`).
- **High-Speed Dynamics**: 320 km/h maximum operating speed with 8-car high-speed electric multiple units (`TRN_HSR`).
- **Signalling Infrastructure**: ETCS Level 2 continuous cab signalling with 91 physical signal locations (`SIG_001` to `SIG_091`) and 92 signalling blocks (`BLK_UP_001` to `BLK_UP_092`) utilizing multi-link `BlockGeometry`.
- **Passenger Stations**: 5 intermediate and terminal stations (`STN_ADR` through `STN_DJD`) with 250 m platforms and scheduled passenger dwells.

---

## 2. Infrastructure & Topology

The corridor is defined as a contiguous sequence of 447 track links connecting 448 nodes along track `TRK_UP`:

| Parameter | Specification | Notes |
|---|---|---|
| Total Corridor Length | 140.00 km (140,000 m) | Uniformly graded at 0.0 ‰ |
| Track Links | 447 (`LNK_0001` – `LNK_0447`) | Segment lengths ~313 m (terminal links ~402 m) |
| Nodes | 448 (`ND_0001` – `ND_0448`) | Endpoints `ND_0001` & `ND_0448`; intermediate junctions |
| Line Speed Limit | 320 km/h (88.89 m/s) | Uniform civil line speed along the corridor |

### Passenger Stations & Platforms

| Station ID | Station Name | Chainage (km) | Platform ID | Link ID | Length | Dwell Time |
|---|---|---|---|---|---|---|
| `STN_ADR` | Al-Dar Station (Origin) | 0.47 km | `PLT_ADR` | `LNK_0002` | 250 m | 120.0 s |
| `STN_02` | Station 02 | 35.00 km | `PLT_02` | `LNK_0112` | 250 m | 120.0 s |
| `STN_03` | Station 03 | 70.00 km | `PLT_03` | `LNK_0224` | 250 m | 120.0 s |
| `STN_04` | Station 04 | 105.00 km | `PLT_04` | `LNK_0336` | 250 m | 120.0 s |
| `STN_DJD` | Al-Jadid Station (Terminus) | 139.25 km | `PLT_DJD` | `LNK_0445` | 250 m | 120.0 s |

---

## 3. Signalling System (ETCS Level 2)

The signalling system implements ETCS Level 2 cab signalling characteristics:
- **Technology Model**: `ETCS_LEVEL_2`
- **Aspect Model**: `THREE_ASPECT` equivalent movement authority supervision
- **Overlap Distance**: 50.0 m
- **Driver Sighting / Transmission Time**: 10.0 s
- **Route Setup Time**: 3.0 s
- **Block Release Delay**: 4.0 s

### Block & Interlocking Layout
- **91 Signals**: `SIG_001` through `SIG_091` spaced regularly along the route.
- **92 Blocks**: `BLK_UP_001` through `BLK_UP_092` mapped via multi-interval geometry in `BlockGeometry` across the 447 track links.
- **Route**: `RTE_UP_MAIN` from entry signal `SIG_001` to exit signal `SIG_091`.

---

## 4. Rolling Stock (`TRN_HSR`)

The high-speed rolling stock model reflects modern 320 km/h 8-car train dynamics:

| Parameter | Value | Unit |
|---|---|---|
| Train Type ID | `TRN_HSR` | - |
| Description | High Speed Train 8-Car 320 km/h Consist | - |
| Consist Length | 202.0 | m |
| Empty Mass (Tare) | 465.0 | tonnes |
| Loaded Mass (Gross) | 485.0 | tonnes |
| Rotating Mass Factor | 0.08 | - |
| Maximum Operational Speed | 320.0 | km/h |
| Maximum Acceleration | 0.80 | m/s² |
| Full Service Deceleration | 0.80 | m/s² |
| Emergency Deceleration | 1.20 | m/s² |
| Installed Traction Power | 8,800 | kW |
| Maximum Starting Tractive Effort | 320.0 | kN |
| Davis Coefficient A | 2.506 | kN |
| Davis Coefficient B | 0.04065 | kN/(km/h) |
| Davis Coefficient C | 0.00043 | kN/(km/h)² |

---

## 5. Operations & Stopping Pattern

Service pattern `SRV_6000` operates in the forward direction along route `RTE_UP_MAIN` stopping at all five passenger platforms:
- Stop 1: `STN_ADR` / `PLT_ADR` (120 s dwell)
- Stop 2: `STN_02` / `PLT_02` (120 s dwell)
- Stop 3: `STN_03` / `PLT_03` (120 s dwell)
- Stop 4: `STN_04` / `PLT_04` (120 s dwell)
- Stop 5: `STN_DJD` / `PLT_DJD` (120 s dwell)

---

## 6. Simulation & Headway Performance Verification

Running the microscopic multi-train simulation pipeline (`SimulationRunner.run_simulation_pipeline`) yields the following verified metrics:

| Key Performance Indicator | 100% Performance Factor | 95% Performance Factor | Variance / Impact |
|---|---|---|---|
| **Technical Minimum Headway** | **52.9 s** (0.88 min) | **52.9 s** (0.88 min) | 0.0 s (signalling headway governed by line speed block clearance) |
| **Theoretical Line Capacity** | **68.1 tph** | **68.1 tph** | 0.0 tph |
| **Planning Operational Capacity** | **50.8 tph** | **50.8 tph** | 0.0 tph (with 18.0 s planning margin) |
| **Controlling Bottleneck Resource** | `BLK_UP_092` | `BLK_UP_092` | Terminal block approaching station clearance |
| **Total Service Duration** | **2,575.0 s** (00:42:55) | **2,598.0 s** (00:43:18) | **+23.0 s** (+0.89% running time due to traction scaling) |
| **Leader Journey Time** | 2,937.0 s | 2,965.0 s | +28.0 s |
| **Follower Journey Time** | 3,058.0 s | 3,099.0 s | +41.0 s |
| **Maximum Simulated Speed** | 320.1 km/h (88.9 m/s) | 320.0 km/h (88.9 m/s) | Both achieve design line speed of 320 km/h |
| **Trajectory Sample Count** | 2,938 (Leader) / 3,060 (Follower) | 2,966 (Leader) / 3,101 (Follower) | Microscopic 1 Hz dynamic integration |
