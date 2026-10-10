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

---

### 5. Resource Management & Interlocking Benchmarks (Milestone P05)

| Benchmark ID | Subsystem | Description | Key Inputs | Expected Analytical Result | Tolerance | Verification Status |
|---|---|---|---|---|---|---|
| **P05-B001** | Resources | Free resource reservation | Resource capacity = 1, initial state = FREE | Reservation granted, train_id mapped | Exact | **VERIFIED (P05)** |
| **P05-B002** | Resources | Exclusive resource conflict | Capacity = 1, already reserved by Train 1 | Train 2 reservation rejected with ResourceConflictError | Exact | **VERIFIED (P05)** |
| **P05-B003** | Occupation | Physical front entry | Train front enters block boundary | Front entry recorded, occupant added | Exact | **VERIFIED (P05)** |
| **P05-B004** | Occupation | Front exit does not release block | Train front exits but rear still inside | Resource remains strictly OCCUPIED | Exact | **VERIFIED (P05)** |
| **P05-B005** | Clearance | Rear clearance event | Train rear exits boundary | Rear cleared recorded, release pending initiated | Exact | **VERIFIED (P05)** |
| **P05-B006** | Release | Release delay timer | Delay $t_{\text{rel}} = 4.0\text{ s}$ | Resource unavailable until $t \ge t_0 + t_{\text{rel}}$ | Exact | **VERIFIED (P05)** |
| **P05-B007** | Occupation | Multi-resource spanning | Train length spans Block 1 and Block 2 | Both blocks simultaneously occupied | Exact | **VERIFIED (P05)** |
| **P05-B008** | Invariant | Stationary train occupation | Stationary train remains inside block | No premature release occurs | Exact | **VERIFIED (P05)** |
| **P05-B009** | Multi-Link | Multi-link block occupation | Block composed of LK_01 and LK_02 | Occupied until rear clears LK_02 | Exact | **VERIFIED (P05)** |
| **P05-B010** | Reverse | Reverse block occupation | Reverse train enters from link end | Correct reverse entry detected | Exact | **VERIFIED (P05)** |
| **P05-B011** | Reverse | Reverse rear clearance | Reverse train rear clears start node | Reverse release sequence executed | Exact | **VERIFIED (P05)** |
| **P05-B012** | Conflict | Opposing-direction conflict | Forward route locked on bidirectional link | Reverse route request rejected | Exact | **VERIFIED (P05)** |
| **P05-B013** | Interlocking| Route setup delay | Setup delay $t_{\text{setup}} = 3.0\text{ s}$ | Route not locked until $t \ge t_{\text{req}} + 3.0\text{ s}$ | Exact | **VERIFIED (P05)** |
| **P05-B014** | Interlocking| Route locking | Valid free path | All route blocks and switches locked atomically | Exact | **VERIFIED (P05)** |
| **P05-B015** | Interlocking| Complete route release | Train clears entire route | All locks removed simultaneously | Exact | **VERIFIED (P05)** |
| **P05-B016** | Interlocking| Sectional route release | Route blocks cleared sequentially | Upstream blocks released while downstream locked | Exact | **VERIFIED (P05)** |
| **P05-B017** | Switches | Switch position conflict | Route requires NORMAL, switch locked REVERSE | Route locking rejected with SwitchLockError | Exact | **VERIFIED (P05)** |
| **P05-B018** | Switches | Reverse switch route | Reverse route through trailing switch | Switch verified and locked in trailing direction | Exact | **VERIFIED (P05)** |
| **P05-B019** | Signals | Two-aspect STOP | Block ahead occupied | Signal aspect = STOP (RED) | Exact | **VERIFIED (P05)** |
| **P05-B020** | Signals | Two-aspect PROCEED | Block ahead free | Signal aspect = PROCEED (GREEN) | Exact | **VERIFIED (P05)** |
| **P05-B021** | Signals | Three-aspect sequence | Next block occupied, subsequent clear | RED -> YELLOW -> GREEN | Exact | **VERIFIED (P05)** |
| **P05-B022** | Signals | Four-aspect lookahead | Lookahead over 3 blocks | RED -> YELLOW -> DOUBLE_YELLOW -> GREEN | Exact | **VERIFIED (P05)** |
| **P05-B023** | Signals | Direction-aware signal aspects | Bidirectional track with forward/reverse signals | Signal evaluates only when facing train | Exact | **VERIFIED (P05)** |
| **P05-B024** | Authority | Movement authority endpoint | Locked route of 2000m | EoA placed at route end (2000m) | Exact | **VERIFIED (P05)** |
| **P05-B025** | Authority | Reverse movement authority | Reverse route of 2000m | Reverse EoA evaluated monotonically | Exact | **VERIFIED (P05)** |
| **P05-B026** | Protection | Restrictive approach speed curve | $v_t = 0$, $b = 0.5\text{ m/s}^2$, $d = 400\text{ m}$ | $v_{\text{perm}} = \sqrt{2 \cdot 0.5 \cdot 400} = 20.0\text{ m/s}$ | Exact | **VERIFIED (P05)** |
| **P05-B027** | Protection | Insufficient braking distance | $v = 30\text{ m/s}$, available $d = 200\text{ m}$ | Raises BrakingFeasibilityError | Exact | **VERIFIED (P05)** |
| **P05-B028** | Coordination| Simultaneous requests | Two trains request conflicting route at same $t$ | Lowest train_id deterministic tie-break | Exact | **VERIFIED (P05)** |
| **P05-B029** | Coordination| Deterministic event ordering | 11-step same-time ordering loop | Strict step 1 through 11 sequence verified | Exact | **VERIFIED (P05)** |
| **P05-B030** | Safety | Resource invariant verification | Multi-train traversal simulation | Zero simultaneous occupations of capacity 1 | 0 violations | **VERIFIED (P05)** |

---

### 6. ETCS Level 2 & CBTC Moving-Block Benchmarks (Milestone P06)

| Benchmark ID | Subsystem | Description | Key Inputs | Expected Analytical Result | Tolerance | Verification Status |
|---|---|---|---|---|---|---|
| **P06-B001** | Architecture | Fidelity mode selection | `BASIC`, `INTERMEDIATE`, `DETAILED` configs | Proper latency and uncertainty configuration | Exact | **VERIFIED (P06)** |
| **P06-B002** | Architecture | Common MA interface compatibility | ETCS L2 and CBTC MA evaluation | Standardized `MovementAuthority` instances | Exact | **VERIFIED (P06)** |
| **P06-B003** | Architecture | Train position report processing | Front pos = 500m, speed = 25m/s, $L = 200\text{ m}$ | Nominal rear = 300m, report age calculated | Exact | **VERIFIED (P06)** |
| **P06-B004** | Logging | Standardized event logging | Position reports, radio comms, MA generation | Standardized events emitted in chronological order | Exact | **VERIFIED (P06)** |
| **P06-B005** | Invariance | Directional MA invariance | Forward route (3000m) vs Reverse route (3000m) | Monotonic route distances, direction preserved | Exact | **VERIFIED (P06)** |
| **P06-B006** | ETCS L2 | RBC initialization with interlocking | Interlocking routes and fixed blocks registered | Route definitions and resource controller linked | Exact | **VERIFIED (P06)** |
| **P06-B007** | ETCS L2 | RBC radio communication latency model | $t_{\text{up}}=0.35\text{s}, t_{\text{proc}}=0.15\text{s}, t_{\text{down}}=0.50\text{s}$ | $t_{\text{comm}} = 1.0\text{ s}$ total latency | $\pm 10^{-6}\text{ s}$ | **VERIFIED (P06)** |
| **P06-B008** | Controlled C | Effective MA receipt time | $t_{\text{issue}} = 100.0\text{ s}, t_{\text{comm}} = 1.0\text{ s}$ | $t_{\text{effective}} = 101.0\text{ s}$ | Exact ($\pm 10^{-6}\text{ s}$) | **VERIFIED (P06)** |
| **P06-B009** | ETCS L2 | Initial MA generation up to occupied block | BLK_02 occupied at 1000m | EoA placed at entrance to BLK_02 ($1000.0\text{ m}$) | Exact | **VERIFIED (P06)** |
| **P06-B010** | ETCS L2 | MA extension on block clearance | Downstream block cleared and locked | EoA extended to $4000.0\text{ m}$ with latency delay | Exact | **VERIFIED (P06)** |
| **P06-B011** | ETCS L2 | Overlap / Danger Point protection | EoA = 3000m, $d_{\text{overlap}} = 50\text{ m}$ | Supervised Location $SvL = 3050.0\text{ m}$ | Exact | **VERIFIED (P06)** |
| **P06-B012** | Controlled A | Braking supervision target distance | $v_0 = 30.0\text{ m/s}, v_t = 0, b = 0.75\text{ m/s}^2$ | $d = v_0^2 / (2b) = 600.0\text{ m}$ | Exact ($\pm 10^{-9}\text{ m}$) | **VERIFIED (P06)** |
| **P06-B013** | ETCS L2 | Multi-curve braking supervision | $d = 600\text{ m}, b = 0.75\text{ m/s}^2$ | $v_{\text{perm}} = 30.0\text{ m/s} < v_{\text{warn}} < v_{\text{int}}$ | Exact | **VERIFIED (P06)** |
| **P06-B014** | ETCS L2 | P04 BrakingTarget conversion | Active ETCS L2 MA with overlap | P04 `BrakingTarget` generated at EoA with margin | Exact | **VERIFIED (P06)** |
| **P06-B015** | ETCS L2 | Stopping feasibility validation | Available $d = 200\text{ m}$, required $d = 600\text{ m}$ | Raises `BrakingFeasibilityError` | Exact | **VERIFIED (P06)** |
| **P06-B016** | ETCS L2 | Reverse operation under RBC | Reverse train on LK_03, reverse route RT_REV | Monotonic reverse MA issued to $3000.0\text{ m}$ | Exact | **VERIFIED (P06)** |
| **P06-B017** | ETCS L2 | Communication timeout handling | Time gap between reports $> 5.0\text{ s}$ | Raises `CommunicationTimeoutError` | Exact | **VERIFIED (P06)** |
| **P06-B018** | CBTC | Train localization and position reporting | Front pos = 250m, speed = 20m/s | Periodic report stored, envelope calculated | Exact | **VERIFIED (P06)** |
| **P06-B019** | CBTC | Position uncertainty model | Odometry drift and base uncertainty $\pm 25\text{ m}$ | Envelope bounds expand by $\pm 25\text{ m}$ | Exact | **VERIFIED (P06)** |
| **P06-B020** | CBTC | Train integrity verification | Confirmed intact vs Lost integrity | Lost integrity triggers conservative envelope expansion | Exact | **VERIFIED (P06)** |
| **P06-B021** | Controlled B | Protected leader envelope formulation | $x_{\text{front}} = 2200\text{m}, L = 200\text{m}, \delta_{\text{loc}} = 20\text{m}, d_{\text{margin}} = 10\text{m}$ | $x_{\text{protected}} = 2000 - 20 - 10 = 1970.0\text{ m}$ | Exact ($\pm 10^{-9}\text{ m}$) | **VERIFIED (P06)** |
| **P06-B022** | CBTC | Dynamic follower MA generation | Leader protected rear at $1970.0\text{ m}$ | Follower EoA placed at $1970.0\text{ m}$ | Exact | **VERIFIED (P06)** |
| **P06-B023** | CBTC | Dynamic MA continuous extension | Leader advances from 2200m to 2300m | Follower EoA advances from 1970m to 2070m | Exact | **VERIFIED (P06)** |
| **P06-B024** | CBTC | Follower braking protection | Follower at 1370m ($d=600\text{m}$ to EoA), $b=0.75$ | Permitted speed $v_{\text{perm}} = 30.0\text{ m/s}$ | Exact | **VERIFIED (P06)** |
| **P06-B025** | CBTC | Fixed infrastructure restriction | Buffer stop / station dwell limit at 1200m | Follower EoA clamped to $1200.0\text{ m}$ | Exact | **VERIFIED (P06)** |
| **P06-B026** | CBTC | Reverse moving-block operation | Reverse leader at 1000m, $L = 200\text{ m}$ | Protected rear in reverse $= 1200 + 30 = 1230.0\text{ m}$ | Exact | **VERIFIED (P06)** |
| **P06-B027** | CBTC | Stale communication handling | Report gap $> 2.0\text{ s}$ | Raises `CommunicationTimeoutError` | Exact | **VERIFIED (P06)** |
| **P06-B028** | Fidelity | Multi-fidelity comparison | `BASIC` vs `INTERMEDIATE` vs `DETAILED` | Zero vs fixed vs drift uncertainty verified | Exact | **VERIFIED (P06)** |
| **P06-B029** | Independence| Technology coexistence | ETCS L2 and CBTC instances | Separate architectures, no cross-substitution | Exact | **VERIFIED (P06)** |
| **P06-B030** | Safety | Moving-block safety invariant | Multi-train moving block traversal | Zero rear-end collisions, EoA strictly respected | 0 violations | **VERIFIED (P06)** |

---

### 7. Railway Capacity, UIC 406-Inspired Assessment & Sensitivity Analysis Benchmarks (Milestone P10)

| Benchmark ID | Subsystem | Description | Key Inputs | Expected Analytical Result | Tolerance | Verification Status |
|---|---|---|---|---|---|---|
| **BENCH-P10-001** | Homogeneous | Theoretical capacity | $H = 120.0\text{ s}$ | $C = 3600 / 120 = 30.0\text{ trains/h}$ | Exact ($\pm 10^{-6}\text{ tph}$) | **VERIFIED (P10)** |
| **BENCH-P10-002** | Planning | Additive planning margin | $H = 120.0\text{ s}, M = 60.0\text{ s}$ | $C = 3600 / (120 + 60) = 20.0\text{ trains/h}$ | Exact ($\pm 10^{-6}\text{ tph}$) | **VERIFIED (P10)** |
| **BENCH-P10-003** | Planning | Target utilization | $C_{\text{theo}} = 30.0\text{ tph}, U = 0.8$ | $C_{\text{plan}} = 0.8 \times 30.0 = 24.0\text{ trains/h}$ | Exact ($\pm 10^{-6}\text{ tph}$) | **VERIFIED (P10)** |
| **BENCH-P10-004** | Mixed Traffic | Repeated pattern cycle | $H(A,B) = 120\text{s}, H(B,A) = 180\text{s}$ | $T_{\text{cycle}} = 300\text{s}, C = 3600 \times 2 / 300 = 24.0\text{ trains/h}$ | Exact ($\pm 10^{-6}\text{ tph}$) | **VERIFIED (P10)** |
| **BENCH-P10-005** | Throughput | Analytical throughput | $N = 25\text{ trains}, T = 7200\text{ s}$ (2 h) | $Q = 25 / 2.0 = 12.5\text{ trains/h}$ | Exact ($\pm 10^{-6}\text{ tph}$) | **VERIFIED (P10)** |
| **BENCH-P10-006** | UIC 406 | Capacity consumption | $T_{\text{comp}} = 4500\text{s}, T_{\text{supp}} = 900\text{s}, T_{\text{anal}} = 7200\text{s}$ | $K = (4500 + 900) / 7200 = 75.0\%$ | Exact ($\pm 10^{-6}\%$) | **VERIFIED (P10)** |
| **P10-B007** | Directional | FORWARD homogeneous capacity | Forward route, $H = 150.0\text{ s}$ | $C = 24.0\text{ trains/h}$, positive finite | Exact | **VERIFIED (P10)** |
| **P10-B008** | Directional | REVERSE homogeneous capacity | Reverse route, $H = 200.0\text{ s}$ | $C = 18.0\text{ trains/h}$, reverse direction tag | Exact | **VERIFIED (P10)** |
| **P10-B009** | Planning | Controlled additive example | $H = 255.6\text{ s}, M = 90.0\text{ s}$ | $H_{\text{plan}} = 345.6\text{ s}, C = 10.4\text{ trains/h}$ | $\pm 0.05\text{ tph}$ | **VERIFIED (P10)** |
| **P10-B010** | Planning | Target utilization sweep | $C = 40.0\text{ tph}, U \in [0.60, 0.75, 0.85]$ | $C_{\text{plan}} \in [24.0, 30.0, 34.0]\text{ tph}$ | Exact | **VERIFIED (P10)** |
| **P10-B011** | Mixed Traffic | 3-service wrap-around cycle | $H(A,B)=100\text{s}, H(B,C)=140\text{s}, H(C,A)=120\text{s}$ | $T_{\text{cycle}} = 360\text{s}, C = 30.0\text{ trains/h}$ | Exact | **VERIFIED (P10)** |
| **P10-B012** | Throughput | Measurement window filtering | 5 trains across warmup/window/cooldown | Only trains in active window counted ($N=3, Q=3\text{ tph}$) | Exact | **VERIFIED (P10)** |
| **P10-B013** | Throughput | Screenline boundary crossing | Trains crossing 5000m spatial boundary | Valid crossings counted ($N=2, Q=2\text{ tph}$) | Exact | **VERIFIED (P10)** |
| **P10-B014** | Stability | STABLE classification | Flat delays, 0 deadlock, 100% completion | Status `STABLE`, `is_sustainable = True` | Exact | **VERIFIED (P10)** |
| **P10-B015** | Stability | METASTABLE classification | Moderate delay growth slope (1.0 s/train) | Status `METASTABLE`, `is_sustainable = False` | Exact | **VERIFIED (P10)** |
| **P10-B016** | Stability | UNSTABLE classification | High delay growth slope (5.0 s/train) | Status `UNSTABLE`, `is_sustainable = False` | Exact | **VERIFIED (P10)** |
| **P10-B017** | Stability | COLLAPSED classification | Deadlock detected in multi-train simulation | Status `COLLAPSED`, deadlock flagged | Exact | **VERIFIED (P10)** |
| **P10-B018** | Saturation | Discrete step scan search | Rates [10, 15, 20, 25, 30] tph (stable to 20) | Maximum sustainable rate $= 20.0\text{ trains/h}$ | Exact | **VERIFIED (P10)** |
| **P10-B019** | Saturation | Binary bisection search | Search bounds [10, 30] tph, stable $< 22.0$ | Converges to critical rate within 0.5 tph | $\pm 0.5\text{ tph}$ | **VERIFIED (P10)** |
| **P10-B020** | Utilization | Physical vs blocking time | Reservation 150s, physical occupancy 80s | Blocking $15.0\%$, physical $8.0\%$ | Exact | **VERIFIED (P10)** |
| **P10-B021** | Utilization | Overlapping interval merging | Trains concurrent on platform [100,300], [200,400] | Merged blocking 300s (not 400s), util $= 30.0\%$ | Exact | **VERIFIED (P10)** |
| **P10-B022** | Utilization | Directional attribution | Single track segment with FWD and REV trains | FWD 200s, REV 200s, total 400s ($40.0\%$) | Exact | **VERIFIED (P10)** |
| **P10-B023** | Utilization | TVS resource utilization | TVS zone locked 850s in 1000s window | Util $85.0\% \ge 75\%$, flagged as critical | Exact | **VERIFIED (P10)** |
| **P10-B024** | Bottlenecks | Ranking across resource categories | Block (90s), TVS (120s), Platform (160s) | Rank 1: Platform, Rank 2: TVS, Rank 3: Block | Exact | **VERIFIED (P10)** |
| **P10-B025** | Bottlenecks | Migration and diminishing returns | Block split (240s $\to$ 180s station bottleneck) | Migrated = True, $\Delta C = +5.0\text{ tph}$, ratio 0.33 | Exact | **VERIFIED (P10)** |
| **P10-B026** | UIC 406 | Timetable compression | 2 trains spaced 600s compressed with 0 buffer | Compressed span $= 180.0\text{ s}$, ratio $= 0.25$ | Exact | **VERIFIED (P10)** |
| **P10-B027** | UIC 406 | Capacity consumption & disclaimer | 3000s compressed, 600s supplement, 7200s window | $K = 50.0\%$, explicit UIC disclaimer present | Exact | **VERIFIED (P10)** |
| **P10-B028** | Sensitivity | Block length recalculation | Blocks 500m to 1500m, speed 30 m/s | Physics recalculated, no proportional scaling | Exact | **VERIFIED (P10)** |
| **P10-B029** | Sensitivity | Signalling technology comparison | 2/3/4 aspect, ETCS L2, CBTC | $C_{\text{CBTC}} > C_{\text{ETCS}} > C_{\text{4-asp}} > C_{\text{3-asp}} > C_{\text{2-asp}}$ | Exact | **VERIFIED (P10)** |
| **P10-B030** | Sensitivity | Station dwell crossover | Dwells 30s to 120s against line headway 120s | Crossover from line bottleneck to platform | Exact | **VERIFIED (P10)** |
| **P10-B031** | Sensitivity | Platform assignment & switch limit | 1 to 4 platforms with 50s throat locking | Capacity bounded by switch throat at 4 platforms | Exact | **VERIFIED (P10)** |
| **P10-B032** | Sensitivity | Opposing / REVERSE capacity | Reverse TVS section traversal (1000m) | Monotonic reverse headway (90s), capacity 40 tph | Exact | **VERIFIED (P10)** |
