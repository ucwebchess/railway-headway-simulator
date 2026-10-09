# ENGINEERING VERIFICATION BENCHMARK REGISTER
## Railway Headway & Capacity Simulator

**Document ID:** RHS-BM-001  
**Version:** 1.3.0  
**Status:** UPDATED (Milestones P01, P02 & P03 Formally Verified)  
**Governing Prompt:** RHS-MASTER-001 § 28; RHS-P01-001; RHS-P02-001 § 22; RHS-P03-001 § 16  

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

### 3. Rolling Stock, Traction & Resistance Benchmarks (Milestone P03)

| Benchmark ID | Subsystem | Description | Mathematical Formulation / Inputs | Expected Analytical Result | Tolerance | Verification Status |
|---|---|---|---|---|---|---|
| **P03-B001** | Mass | Equivalent dynamic mass | $m_{\text{eq}} = m(1 + \lambda)$; $m = 400\text{ t}$, $\lambda = 0.10$ | $m_{\text{eq}} = 440,000\text{ kg}$ | Exact ($\pm 10^{-6}$) | **VERIFIED (P03)** |
| **P03-B002** | Traction | Standstill tractive effort | $v = 0 \implies F_t(0) = F_{\max}$; $F_{\max} = 300\text{ kN}$, $P = 6\text{ MW}$ | $F_t(0) = 300,000\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B003** | Traction | Constant-force region | $v \le P_{\max}/F_{\max} = 20\text{ m/s}$; $v = 10\text{ m/s}$ | $F_t(10) = 300,000\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B004** | Traction | Constant-power region | $v > P_{\max}/F_{\max}$; $v = 40\text{ m/s}$, $P = 6\text{ MW}$ | $F_t(40) = 6,000,000 / 40 = 150,000\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B005** | Traction | Detailed curve piecewise interpolation | Linear interpolation between $(20\text{ m/s}, 300\text{ kN})$ and $(40\text{ m/s}, 150\text{ kN})$ at $v = 30\text{ m/s}$ | $F_t(30) = 225,000\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B006** | Traction | Traction power limit | Mechanical power $P(v) = F_t(v) \cdot v \le P_{\max}$ across all operating speeds $[0, v_{\max}]$ | $P(v) \le 6,000,000\text{ W}$ | $\pm 0.0001\text{ W}$ | **VERIFIED (P03)** |
| **P03-B007** | Adhesion | Adhesion force limit | $F_{\text{adh}} = \mu m_{\text{adh}} g$; $\mu = 0.25$, $m_{\text{adh}} = 200\text{ t}$, $g = 9.81\text{ m/s}^2$ | $F_{\text{adh}} = 490,500\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B008** | Davis | Running resistance at 200 km/h | $R(V) = 2.506 + 0.04065 V + 0.00043 V^2$; $V = 200\text{ km/h}$ | $R(200) = 27,836\text{ N}$ ($27.836\text{ kN}$) | $\pm 0.1\%$ | **VERIFIED (P03)** |
| **P03-B009** | Davis | Coefficient SI normalization | Verify $(A_{\text{si}}, B_{\text{si}}, C_{\text{si}})$ evaluates identically to engineering units | $R_{\text{si}}(v) = R_{\text{eng}}(V)$ | $\pm 10^{-6}$ | **VERIFIED (P03)** |
| **P03-B010** | Gradient | Positive gradient resistance | $F_g = m g i$; $m = 400\text{ t}$, $i = +10$‰ ($+0.010$) | $F_g = +39,240\text{ N}$ ($+39.24\text{ kN}$) | Exact | **VERIFIED (P03)** |
| **P03-B011** | Gradient | Negative gradient resistance | $F_g = m g i$; $m = 400\text{ t}$, $i = -10$‰ ($-0.010$) | $F_g = -39,240\text{ N}$ ($-39.24\text{ kN}$) | Exact | **VERIFIED (P03)** |
| **P03-B012** | Gradient | Reverse gradient sign inversion | Physical $+10$‰ slope traversed in REVERSE | Effective $-10$‰ $\implies F_g = -39,240\text{ N} = -F_{g,\text{fwd}}$ | Exact | **VERIFIED (P03)** |
| **P03-B013** | Curvature | Roeckl curve resistance | $W_c = 650/(R - 55)$‰; $R = 500\text{ m}$, $m = 400\text{ t}$ | $W_c = 1.46067$‰ $\implies F_c = 5,731.68\text{ N}$ | $\pm 0.1\%$ | **VERIFIED (P03)** |
| **P03-B014** | Curvature | Straight-track curvature resistance | Tangent track ($R = \text{None}$ or $R \le 0$) | $F_c = 0.0\text{ N}$ | Exact ($0.0$) | **VERIFIED (P03)** |
| **P03-B015** | Distributed | Distributed gradient over two sections | $L = 200\text{ m}$, $m = 400\text{ t}$; $100\text{ m}$ on $+10$‰, $100\text{ m}$ on $+20$‰ | $F_g = 19,620 + 39,240 = 58,860\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B016** | Distributed | Distributed curvature over two sections | $L = 200\text{ m}$, $m = 400\text{ t}$; $100\text{ m}$ on $R=500\text{ m}$, $100\text{ m}$ straight | $F_c = 0.5 \times 5,731.68 = 2,865.84\text{ N}$ | $\pm 0.1\%$ | **VERIFIED (P03)** |
| **P03-B017** | Distributed | Train spanning multiple links | $L=200\text{ m}$; $150\text{ m}$ on LK_01 ($+10$‰), $50\text{ m}$ on LK_02 ($+20$‰) | $F_g = 400\text{t} \times g \times (0.75 \times 0.010 + 0.25 \times 0.020) = 49,050\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B018** | Distributed | Reverse multi-link resistance | Reverse traversal of LK_02 and LK_01 in opposite direction | $F_g = 400\text{t} \times g \times (0.75 \times (-0.020) + 0.25 \times (-0.010)) < 0$ | Exact | **VERIFIED (P03)** |
| **P03-B019** | Force Balance| Net longitudinal force balance | $F_{\text{net}} = F_t - F_b - F_D - F_g - F_c$; $150\text{k} - 0 - 27.836\text{k} - 39.24\text{k} - 5.732\text{k}$ | $F_{\text{net}} = 77,192\text{ N}$ | Exact | **VERIFIED (P03)** |
| **P03-B020** | Acceleration | Equivalent-mass acceleration | $a = F_{\text{net}} / m_{\text{eq}}$; $F_{\text{net}} = 77,192\text{ N}$, $m_{\text{eq}} = 440,000\text{ kg}$ | $a = 0.175436\text{ m/s}^2$ | Exact | **VERIFIED (P03)** |
| **P03-B021** | Validation | Invalid traction curve rejection | Decreasing or duplicate speeds in curve points | Raises `RollingStockError` | Exact | **VERIFIED (P03)** |
| **P03-B022** | Validation | Unsupported curve radius rejection | Roeckl curve formula with $R < 300\text{ m}$ | Raises `RollingStockError` | Exact | **VERIFIED (P03)** |
| **P03-B023** | Standstill | Zero-speed running resistance | At $v = 0$, $R(0) = A_{\text{si}} > 0$ | $R(0) = A_{\text{si}}$ | Exact | **VERIFIED (P03)** |
| **P03-B024** | Invariance | Direction-independent traction | $F_t(v)$ evaluated identically in forward and reverse | $F_{t,\text{fwd}}(v) = F_{t,\text{rev}}(v)$ | Exact | **VERIFIED (P03)** |
| **P03-B025** | Immutability | Baseline parameter immutability | Physics evaluation does not modify canonical parameters | Initial parameters identical before and after evaluation | 0 mutations | **VERIFIED (P03)** |

---

### 4. Comprehensive Subsystem Benchmark Register

| Benchmark ID | Subsystem | Description | Key Inputs | Expected Result | Tolerance | Implementation Status | Verification Status |
|---|---|---|---|---|---|---|---|
| **BM-PHY-001** | Train Dynamics | Constant acceleration kinematic motion on flat tangent track | $v_0 = 0$, $a = 1.0\text{ m/s}^2$, $t = 20.0\text{ s}$ | $s = 200.0\text{ m}$, $v = 20.0\text{ m/s}$ | $\pm 0.01\%$ | Reserved (P04) | Pending P04 |
| **BM-PHY-002** | Running Resistance | Davis polynomial coefficient normalization & force evaluation | $V = 100\text{ km/h}$, $A = 4.0\text{ kN}$, $B = 0.05\text{ kN/(km/h)}$, $C = 0.001\text{ kN/(km/h)}^2$ | $A_{\text{si}} = 4000\text{ N}$, $B_{\text{si}} = 180\text{ N}\cdot\text{s/m}$, $C_{\text{si}} = 12.96\text{ N}\cdot\text{s}^2/\text{m}^2$; $R(100) = 19000\text{ N}$ | Exact ($\pm 0.001\text{ N}$) | Implemented (`headway.core.units`) | **VERIFIED (P01)** |
| **BM-PHY-003** | Curvature Resistance | Roeckl curve formula verification | $R = 400\text{ m}$ | $w_c = 1.884\text{ kg/t}$ ($18.48\text{ N/kN}$) | $\pm 0.1\%$ | Implemented (`headway.rolling_stock`) | **VERIFIED (P03)** |
| **BM-PHY-004** | Braking Deceleration | Stopping distance under constant brake deceleration | $v_0 = 40\text{ m/s}$, $d = -1.0\text{ m/s}^2$ | $s_{\text{stop}} = 800.0\text{ m}$, $t_{\text{stop}} = 40.0\text{ s}$ | $\pm 0.01\%$ | Reserved (P04) | Pending P04 |
| **BM-SIG-001** | Blocking Time | 7-Component blocking time additive conservation | $t_1=3, t_2=8, t_3=40, t_4=60, t_5=30, t_6=10, t_7=4$ | $T_{\text{blocking}} = 155.0\text{ s}$ | Exact ($\sum t_k = T$) | Reserved (P08) | Pending P08 |
| **BM-TVS-001** | TVS Invariant | Single train occupancy enforcement in ventilation section | Follower train attempting TVS entry while leader rear inside | Follower held at TVS entry signal / boundary | 0 violations allowed | Reserved (P07) | Pending P07 |
| **BM-HDW-001** | Headway | Homogeneous 2-train technical minimum headway | Equal train trajectories, identical block layout | $H = t_{\text{leader-release}} - t_{\text{follower-start}}$ | $\pm 0.1\text{ s}$ | Reserved (P08) | Pending P08 |
| **BM-CAP-001** | Capacity | Homogeneous theoretical line capacity calculation | $H = 120.0\text{ s}$ | $C = 30.0\text{ trains/hour}$ | Exact | Reserved (P10) | Pending P10 |
| **BM-CAP-002** | Capacity | Planning operational capacity with margin $M = 30\text{ s}$ | $H = 120.0\text{ s}$, $M = 30.0\text{ s}$ | $C_{\text{planning}} = 24.0\text{ trains/hour}$ | Exact | Reserved (P10) | Pending P10 |
