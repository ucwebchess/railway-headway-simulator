# The v1.14.1 platform fit check is not wired into the simulation pipeline (target: v1.15.0)

**Status:** open. Found in the v1.14.6 pre-flight audit (branch `fix/v1.14.6-reverse-berth-overhang`). Deliberately **not** fixed in v1.14.6 (decisions A3 / C2 / C3).

## Observation

v1.14.1 added a length-only platform fit rule: a train fits iff `train_length_m <= parent_platform_length_m + FIT_TOLERANCE_M` (1 mm), where the parent length is the sum of the parent platform's segment lengths. A train that does not fit should raise `ERR_TRAIN_OVERHANG` (`TrainOverhangError`).

The rule exists in two places:

- `headway.infrastructure.stations.RoutePlatformStop.check_train_fit` / `is_train_accommodated`
- `headway.signalling.platform_controller.PlatformController.validate_platform_compatibility` (raises `PlatformCompatibilityError`)

Neither is called on the production simulation path (`SimulationRunner.run_simulation_pipeline` → `MultiTrainSimulator`). The pre-flight audit instrumented both entry points during u8000 FORWARD and REVERSE runs and recorded **no calls**. The engine also passes `station_views=[]` to the braking-target resolver, so `resolve_route_stops` is not on the production path either.

## Consequence

A train longer than its physical platform is simulated without an error. u8000: `TRN_HSR` (202 m) at `PLT_AUH` (200 m). By the v1.14.1 rule, 202 > 200.001 should raise `ERR_TRAIN_OVERHANG`. Instead the train berths with a 2 m overhang.

## What v1.14.6 does instead

The berth containment check of the central berth rule (`berth_front_offset` → `check_berth_containment`, `ERR_PLATFORM_BERTH_OVERHANG`) tolerates the **unavoidable** overhang `max(0, L - P) + 1 mm`. It rejects only footprints that leave the platform by more than that, which no correct berth produces. It does **not** reject trains that are too long for their platform: that is the fit check's job, and changing it would change results for existing projects (u8000 would start failing).

## Proposed v1.15.0 work

1. Call the fit check once per scheduled stop in the pipeline, before the engine run, in both running directions. Use the stop segment, attributed to the parent platform as in the v1.14.1 check and the v1.14.5 Section 6.
2. Decide the policy for too-long trains: a hard `ERR_TRAIN_OVERHANG` (consistent with "prefer loud failure"), or a reported overhang with a named warning. u8000 `PLT_AUH` / `TRN_HSR` is the reference case.
3. Once the fit check runs, tighten the berth containment allowance from `max(0, L - P) + 1 mm` to `1 mm`, since a train that passed the fit check has no unavoidable overhang.
4. Tests in both directions: a fitting train (no error), a too-long train (error or warning per decision 2), and a train exactly at the platform length (fits).
