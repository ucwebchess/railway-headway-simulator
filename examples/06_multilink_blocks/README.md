# Multi-Link Blocks and TVS Sections Example (`06_multilink_blocks`)

The **Multi-Link Blocks and TVS Demonstration Line** (`06_multilink_blocks`) is the reference dataset for Schema Version 1.2.0, demonstrating spatial interval decomposition for fixed signalling blocks and Tunnel Ventilation System (TVS) sections across physical track link boundaries.

---

## 1. Executive Summary & Purpose

In real-world railway networks, block sections (track circuits, axle counter detection sections) and tunnel ventilation zones frequently cross civil infrastructure link boundaries (such as bridges, switches, gradient changes, or tunnel portals). 

In Schema 1.0/1.1, blocks and TVS sections were defined with a single `LINK_ID`, `START_OFFSET_M`, and `END_OFFSET_M`. Schema 1.2.0 formally introduces:
1. **`BlockGeometry` worksheet in `02_Signalling.xlsx`**: Defines multi-interval spatial geometry for signalling blocks (`BLOCK_ID`, `SEQUENCE`, `LINK_ID`, `START_OFFSET_M`, `END_OFFSET_M`).
2. **`TVSGeometry` worksheet in `01_Infrastructure.xlsx`**: Defines multi-interval spatial geometry for tunnel ventilation zones (`TVS_ID`, `SEQUENCE`, `LINK_ID`, `START_OFFSET_M`, `END_OFFSET_M`).
3. **Full backward compatibility**: Retains seamless ingestion of legacy single-link schemas from existing models while enforcing strict topological and physical continuity for multi-link intervals.

---

## 2. Infrastructure & Topology

The demonstration corridor consists of 4 contiguous track links spanning 4,700 m:

| Link ID | Length | Start Node | End Node | Maximum Speed | Gradient | Description |
|---|---|---|---|---|---|---|
| `LNK_01` | 1,000 m | `ND_01` | `ND_02` | 120 km/h | 0.0 ‰ | Station Alpha approach & platform track |
| `LNK_02` | 1,200 m | `ND_02` | `ND_03` | 120 km/h | 0.0 ‰ | Intermediate running line leading to tunnel north portal |
| `LNK_03` | 1,000 m | `ND_03` | `ND_04` | 120 km/h | 0.0 ‰ | Bored mountain tunnel interior (`TNL_01`) |
| `LNK_04` | 1,500 m | `ND_04` | `ND_05` | 120 km/h | 0.0 ‰ | Tunnel south exit & Station Beta platform track |

### Stations & Platforms
- **Station Alpha (`STN_01`)**: Platform `PLT_01` on `LNK_01` (100 m – 300 m, length 200 m), Stopping Point `SP_01` at 250 m.
- **Station Beta (`STN_02`)**: Platform `PLT_02` on `LNK_04` (1,000 m – 1,300 m, length 300 m), Stopping Point `SP_02` at 1,200 m.

### Tunnel & Multi-Link TVS Section
- **Tunnel `TNL_01`**: Summit Mountain Tunnel between North Portal `ND_03` and South Portal `ND_04`.
- **TVS Section `TVS_01`**: A multi-link ventilation section spanning 1,100 m across the tunnel entry boundary:
  - Sequence 1: `LNK_02`, offset 600.0 m to 1,200.0 m (600 m length on open-air approach).
  - Sequence 2: `LNK_03`, offset 0.0 m to 500.0 m (500 m length inside tunnel `TNL_01`).
  - Governed by holding signal `SIG_02` on `LNK_02` (at 600.0 m) with 15.0 s ventilation purge delay.

#### Portal Spanning Rationale & `TUNNEL_ID` Foreign Key Handling
In this dataset, `TVS_01` deliberately spans across the North Tunnel Portal at node `ND_03`:
1. **Engineering Design Rationale (NFPA 130 / EN 50126)**: In railway tunnel safety engineering, tunnel ventilation zones often encompass the open-air portal approach (the "portal influence zone" or pre-portal holding buffer). Placing holding signal `SIG_02` on open-air link `LNK_02` (600 m before portal `ND_03`) ensures that following trains are held safely back in the open atmosphere rather than queuing directly at the portal threshold during tunnel smoke extraction, emergency purge, or evacuation operations.
2. **Schema Handling of `TUNNEL_ID`**: In the `TVSSections` worksheet, `TUNNEL_ID` (`TNL_01`) serves as a facility-level foreign key to the `Tunnels` asset registry. It designates the primary tunnel infrastructure and ventilation plant responsible for the zone. The schema intentionally does not constrain constituent track links in `TVSGeometry` to be enclosed tunnel structures, thereby permitting multi-link TVS zones to extend across portal approaches while maintaining clean referential integrity to `TNL_01`.

---

## 3. Signalling System & Multi-Link Block Geometry

Three continuous signalling blocks govern the corridor, each traversing a track link boundary:

### Multi-Link Signalling Blocks

1. **Block `BLK_01`** (Total length: 1,500 m):
   - Entry Signal: `SIG_01` (`LNK_01` @ 100.0 m)
   - Exit Signal: `SIG_02` (`LNK_02` @ 600.0 m)
   - Sequence 1: `LNK_01`, offset 100.0 m to 1,000.0 m (900 m)
   - Sequence 2: `LNK_02`, offset 0.0 m to 600.0 m (600 m)

2. **Block `BLK_02`** (Total length: 1,100 m):
   - Entry Signal: `SIG_02` (`LNK_02` @ 600.0 m)
   - Exit Signal: `SIG_03` (`LNK_03` @ 500.0 m)
   - Sequence 1: `LNK_02`, offset 600.0 m to 1,200.0 m (600 m)
   - Sequence 2: `LNK_03`, offset 0.0 m to 500.0 m (500 m)

3. **Block `BLK_03`** (Total length: 1,900 m):
   - Entry Signal: `SIG_03` (`LNK_03` @ 500.0 m)
   - Exit Signal: `SIG_04` (`LNK_04` @ 1,400.0 m)
   - Sequence 1: `LNK_03`, offset 500.0 m to 1,000.0 m (500 m)
   - Sequence 2: `LNK_04`, offset 0.0 m to 1,400.0 m (1,400 m)

---

## 4. Engineering Validation Guarantees

The dataset validates under `DatasetValidator` with zero errors and zero warnings:
- **Sequence Continuity**: Every multi-link resource sequence starts strictly at 1 and increases monotonically without gaps (`1, 2, ...`).
- **Network Link Continuity**: Consecutive intervals reference links that connect directly at a shared network node.
- **Physical Continuity**: The trailing boundary of sequence $i$ matches the leading boundary of sequence $i+1$ with zero physical gap.
- **Link Bounds Clamping**: All interval offsets are strictly within $[0, L_{\text{link}}]$.
- **Referential Integrity**: All referenced `LINK_ID`, `BLOCK_ID`, `TVS_ID`, and `SIGNAL_ID` cross-references match existing records.

---

## 5. Usage & Reproduction

To regenerate the workbook files:
```bash
python3 examples/06_multilink_blocks/generate.py
```
To load the example programmatically:
```python
from headway.ui.file_manager import FileManager

project, report, file_map = FileManager.load_example_project("06_multilink_blocks")
assert not report.has_errors
```
