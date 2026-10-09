# ENGINEERING VERIFICATION BENCHMARK REGISTER
## Railway Headway & Capacity Simulator

**Document ID:** RHS-BM-001  
**Version:** 1.2.0  
**Status:** UPDATED (Milestones P01 & P02 Verified)  
**Governing Prompt:** RHS-MASTER-001 § 28; RHS-P01-001; RHS-P02-001 § 22  

---

### 1. Benchmark Register Objectives

In strict compliance with **RHS-MASTER-001 § 28 (Mandatory Verification)**:
- Engineering modules shall be verified against independent analytical benchmarks.
- Expected benchmark values must be derived independently of production calculations.
- Benchmarks shall never be altered or relaxed merely to make code pass.

---

### 2. Physical Infrastructure Network Benchmarks (Milestone P02)

| Benchmark ID | Subsystem | Description | Key Inputs | Expected Result | Tolerance | Verification Status |
|---|---|---|---|---|---|---|
| **BENCH-P02-001** | Infrastructure | Simple Forward Route Length | A $\rightarrow$ B: 1000m, B $\rightarrow$ C: 2000m | $L_{\text{route}} = 3000\text{ m}$ | Exact | **VERIFIED (P02)** |
| **BENCH-P02-002** | Infrastructure | Reverse Route Traversal | C $\rightarrow$ B $\rightarrow$ A over same physical links | $L_{\text{route}} = 3000\text{ m}$, identical physical links | Exact | **VERIFIED (P02)** |
| **BENCH-P02-003** | Infrastructure | Reverse Position Mapping | $L = 1000\text{ m}$, reverse local $s = 200\text{ m}$ | $x_{\text{physical}} = 800\text{ m}$ ($L - s$) | Exact | **VERIFIED (P02)** |
| **BENCH-P02-004** | Infrastructure | Reverse Gradient Sign Inversion | Physical forward gradient $+10$‰ | Effective reverse gradient $-10$‰ | Exact | **VERIFIED (P02)** |
| **BENCH-P02-005** | Infrastructure | Directional Speed Restriction | Forward-only vs BOTH restrictions | Forward-only ignored in reverse; BOTH applied | Exact | **VERIFIED (P02)** |
| **BENCH-P02-006** | Infrastructure | Reverse Chainage Mapping | Route chainage 0–10 km in reverse | $s = 0\text{ km} \rightarrow 10\text{ km}$; $s = 10\text{ km} \rightarrow 0\text{ km}$ | Exact | **VERIFIED (P02)** |
| **BENCH-P02-007** | Infrastructure | Train Length Across Links | $L_{\text{train}} = 200\text{ m}$, front 50m into 2nd link | 50m in 2nd link, 150m in preceding link | Exact | **VERIFIED (P02)** |
| **BENCH-P02-008** | Infrastructure | Reverse Train Length | Repeat BENCH-P02-007 in reverse | Total physical occupied length = 200m | Exact | **VERIFIED (P02)** |
| **BENCH-P02-009** | Infrastructure | TVS Reverse Entry Boundary | TVS physically 5–10 km | Forward entry 5km; Reverse entry 10km | Exact | **VERIFIED (P02)** |
| **BENCH-P02-010** | Infrastructure | Track Direction Policy Enforcement | Track marked `NOMINAL` (FORWARD_ONLY) | Reverse traversal rejected with `DirectionPolicyError` | 0 violations | **VERIFIED (P02)** |

---

### 3. Comprehensive Subsystem Benchmark Register

| Benchmark ID | Subsystem | Description | Key Inputs | Expected Result | Tolerance | Implementation Status | Verification Status |
|---|---|---|---|---|---|---|---|
| **BM-PHY-001** | Train Dynamics | Constant acceleration kinematic motion on flat tangent track | $v_0 = 0$, $a = 1.0\text{ m/s}^2$, $t = 20.0\text{ s}$ | $s = 200.0\text{ m}$, $v = 20.0\text{ m/s}$ | $\pm 0.01\%$ | Reserved (P04) | Pending P04 |
| **BM-PHY-002** | Running Resistance | Davis polynomial coefficient normalization & force evaluation | $V = 100\text{ km/h}$, $A = 4.0\text{ kN}$, $B = 0.05\text{ kN/(km/h)}$, $C = 0.001\text{ kN/(km/h)}^2$ | $A_{\text{si}} = 4000\text{ N}$, $B_{\text{si}} = 180\text{ N}\cdot\text{s/m}$, $C_{\text{si}} = 12.96\text{ N}\cdot\text{s}^2/\text{m}^2$; $R(100) = 19000\text{ N}$ | Exact ($\pm 0.001\text{ N}$) | Implemented (`headway.core.units`) | **VERIFIED (P01)** |
| **BM-PHY-003** | Curvature Resistance | Roeckl curve formula verification | $R = 400\text{ m}$ | $w_c = 1.884\text{ kg/t}$ ($18.48\text{ N/kN}$) | $\pm 0.1\%$ | Reserved (P03) | Pending P03 |
| **BM-PHY-004** | Braking Deceleration | Stopping distance under constant brake deceleration | $v_0 = 40\text{ m/s}$, $d = -1.0\text{ m/s}^2$ | $s_{\text{stop}} = 800.0\text{ m}$, $t_{\text{stop}} = 40.0\text{ s}$ | $\pm 0.01\%$ | Reserved (P04) | Pending P04 |
| **BM-SIG-001** | Blocking Time | 7-Component blocking time additive conservation | $t_1=3, t_2=8, t_3=40, t_4=60, t_5=30, t_6=10, t_7=4$ | $T_{\text{blocking}} = 155.0\text{ s}$ | Exact ($\sum t_k = T$) | Reserved (P08) | Pending P08 |
| **BM-TVS-001** | TVS Invariant | Single train occupancy enforcement in ventilation section | Follower train attempting TVS entry while leader rear inside | Follower held at TVS entry signal / boundary | 0 violations allowed | Reserved (P07) | Pending P07 |
| **BM-HDW-001** | Headway | Homogeneous 2-train technical minimum headway | Equal train trajectories, identical block layout | $H = t_{\text{leader-release}} - t_{\text{follower-start}}$ | $\pm 0.1\text{ s}$ | Reserved (P08) | Pending P08 |
| **BM-CAP-001** | Capacity | Homogeneous theoretical line capacity calculation | $H = 120.0\text{ s}$ | $C = 30.0\text{ trains/hour}$ | Exact | Reserved (P10) | Pending P10 |
| **BM-CAP-002** | Capacity | Planning operational capacity with margin $M = 30\text{ s}$ | $H = 120.0\text{ s}$, $M = 30.0\text{ s}$ | $C_{\text{planning}} = 24.0\text{ trains/hour}$ | Exact | Reserved (P10) | Pending P10 |
