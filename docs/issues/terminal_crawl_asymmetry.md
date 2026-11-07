# FORWARD/REVERSE terminal clearing time differs on u8000: 88 s vs 52 s (target: v1.15.0)

**Status:** open, observation for follow-up investigation. Not fixed in v1.14.4.

## Observation

The v1.14.4 Section 8 footnote reports the terminal clearing movement (from the final station arrival to the end of track) as:

| Direction | Terminus | Terminus arrival | End of trajectory | Clearing time |
|---|---|---|---|---|
| FORWARD (ADR → AUH) | AUH | 1172 s | 1260 s | **88 s** |
| REVERSE (AUH → ADR) | ADR | 1226 s | 1278 s | **52 s** |

## Initial analysis (v1.14.4 PR)

The two clearing movements are at **opposite ends of the line**. FORWARD ends at AUH and REVERSE ends at ADR. They are not the same physical track run in two directions. The geometry and speed limits differ:

| Direction | Track past the stop | Permissible speed | Peak speed reached | Clearing time |
|---|---|---|---|---|
| FORWARD, past AUH | 120.1 m (35,608.9 → 35,729.0 m; LNK_175 + LNK_176) | 5 km/h | 5.0 km/h | 88 s |
| REVERSE, past ADR | 464.0 m (forward chainage 464.0 → 0.0 m; LNK_01 onward) | 72.5 km/h | 61.5 km/h (traction then braking; braking starts before the limit is reached) | 52 s |

Both values match simple kinematics for their own section:
- 120 m at 5 km/h ≈ 86 s, plus the 0 → 5 km/h acceleration.
- 464 m with ≈0.69 m/s² acceleration and ≈0.68 m/s² braking ≈ 52 s.

So the different times **come from the input data, not from the physics engine**.

The same mirrored pattern shows up in the run-in before the origin departure:
- FORWARD: 53 s for 468 m at the ADR end.
- REVERSE: 111 s for about 220 m at the AUH end, including about 117 m at 5 km/h.

## Items for the follow-up investigation

1. **Confirm the intended layout of both line ends** (see `terminal_crawl_track.md`). If both ends should be symmetric (e.g. the same overrun length and buffer-stop approach speed), the user workbook needs changing; the simulator does not.
2. **Side observation in the trajectory export:** on LNK_175 (−3.5 ‰, FORWARD), `acceleration_ms2` reads +0.024 to +0.027 m/s² while `speed_ms` is held constant at 5 km/h. This is about the size of the gradient term, so the field appears to report acceleration before the speed hold is applied. The REVERSE run-in over the same zone (uphill) reads 0.000.
   - The acceleration-phase CSV uses finite differences of speed, so it is not affected.
   - Decide whether the exported `acceleration_ms2` should reflect the applied (held) value. This is a physics-layer change, so it needs explicit approval.
3. Only if the layout is confirmed symmetric and the times still differ: investigate the physics engine. This is not expected, given the analysis above.

## Acceptance

- Layout intent confirmed by the user, and the clearing times explained or corrected in the data.
- A decision recorded on item 2.
- Any change is verified in both FORWARD and REVERSE.
