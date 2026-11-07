# Track beyond the AUH terminus stopping point on the u8000 project (target: v1.15.0)

**Status:** open, observation only. Not fixed in v1.14.4. The user needs to confirm intent.
**Type:** data question (user workbook), not a simulator defect.

## Observation

On the u8000 user project (`HEADWAY_INFRASTRUCTURE_8000_REV_AUH.xlsx`, FORWARD ADR → AUH, v1.14.3/v1.14.4):

- The train stops at the AUH platform at **1172 s**, front of train at **35,608.9 m** (route chainage).
  This is the end of `LNK_174`, at 35,609 m.
- The trajectory then continues to the physical end of track at **35,729.0 m**, arriving at **1260 s**.
- So the train covers **120.1 m in 88 s** after the final station arrival. The v1.14.4 Section 8 footnote now reports this as the "terminal clearing movement". It is not included in the Total Service Duration KPI (1119 s).

The cause is two links in the user's `TrackLinks` sheet:

| LINK_ID | Length (m) | MAX_SPEED_KMH | Gradient (‰) | End chainage (m) |
|---|---|---|---|---|
| LNK_174 | 100 | 92.5 | −3.5 | 35,609 |
| LNK_175 | 100 | **5** | −3.5 | 35,709 |
| LNK_176 | 20 | **5** | 0 | 35,729 |

The train accelerates to 5 km/h within about 6 s, holds 5 km/h for about 114 m, and stops at the end of track.

The same 5 km/h zone appears at the start of a REVERSE run (AUH → ADR). The train starts at the end of track and needs **111 s** to cover the roughly 220 m to the AUH platform stop (5 km/h for about 117 m), before the KPI clock starts.

## Question for the user

Is the 120 m / 5 km/h section past the AUH stopping point intentional?

- **If intentional** (headshunt, overrun/clearance section, buffer-stop approach): document it in the project
  notes. The simulator behaves correctly, and the v1.14.4 footnote already discloses the clearing time.
- **If data drift** (e.g. link chainage extends past where the line was meant to end, or a placeholder speed was left on LNK_175/LNK_176): correct the user workbook. This is a data-quality item for the workbook, not a code change.

## Effect on reported results

- **Total Service Duration KPI:** not affected (it ends at terminus arrival).
- **Trajectory duration (Excel row) and the planned v1.15.0 "full train movement time"** (`dual_duration_kpi.md`): both include the 88 s FORWARD crawl.
- **Platform/track occupation at AUH:** the train occupies the end-of-line section for this time.
- **REVERSE origin departure:** 111 s instead of 53 s in FORWARD, because of the 5 km/h zone at the AUH end.

## Acceptance

- The user confirms intent. Then either document the section, or the user corrects the workbook. No simulator change is expected.
