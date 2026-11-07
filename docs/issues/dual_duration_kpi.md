# Dual duration KPI on the executive card (target: v1.15.0)

**Status:** open, deferred from v1.14.4 (labeling-only PR).

## Background

v1.14.4 labels the existing Total Service Duration KPI consistently on every surface as
"origin departure to terminus arrival". It also adds a Section 8 footnote stating the absolute
simulation-time frame and the terminal clearing movement after the last stop, plus an Excel-only
"Trajectory Duration" row (start of run to end of track). The executive card still shows only one
duration.

On layouts where the end of track lies beyond the terminus platform, the train keeps moving after
its final station arrival. That terminal clearing movement still occupies track and platforms, but
the current KPI does not include it.

## Proposal

Show two KPIs on the executive card (HTML, PDF, Excel):

| KPI | Window | Use |
|---|---|---|
| Passenger journey time | origin departure → terminus arrival (= current Total Service Duration) | timetable planning |
| Full train movement time | origin departure → end of track (last trajectory sample) | infrastructure occupation analysis |

The two values differ by exactly the terminal clearing time already stated in the v1.14.4 Section 8 footnote.

## Reference values (u8000 user project, FORWARD, v1.14.3/v1.14.4)

| Quantity | Value |
|---|---|
| Origin departure (ADR) | 53 s |
| Terminus arrival (AUH) | 1172 s |
| End of trajectory | 1260 s |
| Passenger journey time | 1119 s |
| Full train movement time | 1207 s (1260 − 53) |
| Terminal clearing movement | 88 s |

REVERSE (AUH → ADR) on the same project: origin departure 111 s, terminus arrival 1226 s,
trajectory end 1278 s, which gives 1115 s and 1167 s.

## Acceptance criteria

- Both KPIs appear on the HTML and PDF executive cards and in the Excel Executive_Summary, with explicit window labels.
- Full train movement time = `samples[-1].time_s − origin departure_time_s` when there are ≥ 2 station stops. With fewer stops, define a fallback and state it in the label.
- Verified in FORWARD and REVERSE. The existing Total Service Duration value is unchanged.
- Decide whether the Excel-only "Trajectory Duration" row (start of run → end of track) from v1.14.4 is kept or replaced.
