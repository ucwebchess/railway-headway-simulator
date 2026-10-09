# ENGINEERING CONTRACT & PHYSICAL FORMULATIONS
## Railway Headway & Capacity Simulator

**Document ID:** RHS-ENG-001  
**Version:** 1.0.0  
**Authority:** Approved Engineering Contract Freeze & RHS-MASTER-001  
**Governing Prompt:** RHS-MASTER-001 § 5–21; RHS-P00-001 § 13 (P00-DOC-002)  

---

### 1. Fundamental Engineering Units (SI)

All internal engineering calculations strictly execute in SI units. Conversions from engineering-friendly Excel inputs occur via centralized normalization.

| Quantity | Symbol | Internal SI Unit | Excel/Input Conventional Unit | Conversion Factor |
|---|---|---|---|---|
| Distance / Position | $s, x$ | $\text{m}$ | $\text{km}$ | $1\text{ km} = 1000\text{ m}$ |
| Time / Duration | $t, T, H$ | $\text{s}$ | $\text{s}$ or $\text{min}$ | $1\text{ min} = 60\text{ s}$ |
| Speed / Velocity | $v, V$ | $\text{m/s}$ | $\text{km/h}$ | $v = V / 3.6$ |
| Acceleration / Deceleration | $a, d$ | $\text{m/s}^2$ | $\text{m/s}^2$ | $1.0$ |
| Mass (Static) | $m$ | $\text{kg}$ | $\text{t}$ (tonnes) | $1\text{ t} = 1000\text{ kg}$ |
| Force (Traction / Resistance) | $F, R$ | $\text{N}$ | $\text{kN}$ | $1\text{ kN} = 1000\text{ N}$ |
| Power | $P$ | $\text{W}$ | $\text{kW}$ | $1\text{ kW} = 1000\text{ W}$ |
| Energy | $E$ | $\text{J}$ | $\text{kWh}$ | $1\text{ kWh} = 3.6 \times 10^6\text{ J}$ |
| Gradient | $g, i$ | dimensionless ($\text{m/m}$) | $\text{permil } (\text{‰})$ | $g = i / 1000$ |
| Curve Radius | $R$ | $\text{m}$ | $\text{m}$ | $1.0$ |

---

### 2. Longitudinal Train Dynamics Equations

The motion of a train along its traversed route is governed by:

$$a(t) = \frac{F_{\text{traction}}(v) - F_{\text{braking}}(v) - F_{\text{Davis}}(v) - F_{\text{gradient}}(s) - F_{\text{curvature}}(s)}{m_{\text{equivalent}}}$$

Where the equivalent dynamic mass accounts for rotating inertial mass via the rotating mass factor $\lambda$:

$$m_{\text{equivalent}} = m \cdot (1 + \lambda)$$

#### 2.1 Running Resistance (Davis Formulation)
$$F_{\text{Davis}}(v) = A + B \cdot v + C \cdot v^2$$
*(Coefficients $A$, $B$, $C$ must adhere to explicit normalized SI units: $\text{N}$, $\text{N}\cdot\text{s/m}$, and $\text{N}\cdot\text{s}^2/\text{m}^2$).*

#### 2.2 Curvature Resistance (Roeckl Formulation)
For curve radius $R > 55\text{ m}$:
$$w_c = \frac{650}{R - 55} \quad [\text{N/kN} \text{ or kg/t equivalent}]$$
$$F_{\text{curvature}} = w_c \cdot (m \cdot g_0) \cdot 10^{-3} \quad [\text{N}]$$

#### 2.3 Distributed Spatial Resistance
Because trains possess physical length $L_{\text{train}}$, gradient and curve resistance shall be integrated over the occupied spatial envelope $[s - L_{\text{train}}, s]$ rather than point-sampled.

---

### 3. Spatial Geometry & Rear Clearance Invariant

A train occupies an interval on the 1D physical track network:
$$s_{\text{rear}}(t) = s_{\text{front}}(t) - L_{\text{train}}$$

**Absolute Invariant:** A physical resource (signalling block, interlocking route, station platform, TVS section) remains occupied until $s_{\text{rear}}(t)$ has cleared the resource boundary plus any safety margin or release delay.

---

### 4. Seven-Component Blocking Time

The resource blocking time timeline is partitioned into seven non-overlapping additive components:
1. **Setup Time ($t_1$):** Route locking, switch movement, aspect progression.
2. **Approach Sighting Time ($t_2$):** Driver sight distance prior to distant/approach signal.
3. **Approach Running Time ($t_3$):** Running time from approach signal to block boundary.
4. **Block Running Time ($t_4$):** Train front running through the block length.
5. **Dwell Time ($t_5$):** Scheduled or simulated passenger dwell (if stopping).
6. **Geometric Clearance Time ($t_6$):** Time required for train rear to clear block exit ($L_{\text{train}} / v_{\text{exit}}$).
7. **Release Time ($t_7$):** Track circuit release delay and interlocking route unlock.

Total resource blocking time:
$$T_{\text{blocking}} = t_{\text{final-release}} - t_{\text{blocking-start}} = \sum_{k=1}^7 t_k$$

---

### 5. Technical Headway and Line Capacity

#### 5.1 Pairwise Technical Minimum Headway
$$H_k(i, j) = t_{\text{leader-release}, k} - t_{\text{follower-start}, k}$$
$$H(i, j) = \max_k \{ H_k(i, j) \}$$

#### 5.2 Theoretical Homogeneous Capacity
$$C_{\text{theoretical}} = \frac{3600}{H} \quad [\text{trains/hour}]$$

#### 5.3 Planning Operational Capacity
With operational margin $M$ (typically $0.25H$ to $0.33H$ or fixed buffer seconds):
$$C_{\text{planning}} = \frac{3600}{H + M} \quad [\text{trains/hour}]$$

---

### 6. Tunnel Ventilation Sections (TVS)

- TVS sections represent distinct physical ventilation zones whose boundaries are decoupled from signalling block boundaries.
- **Rule:** Maximum one train per TVS per track.
- Follower train movement authority shall be capped at the TVS holding point until leader rear clearance plus TVS safety delay is verified.
