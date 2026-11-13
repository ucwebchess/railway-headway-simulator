# Escalate large platform overhangs to `ERR_TRAIN_OVERHANG` (target: v1.15.2)

**Status:** open. Deferred from v1.15.1 (fit-check wiring, Option B).

## Background

v1.15.1 wires the v1.14.1 fit check (`RoutePlatformStop.check_train_fit`) into `SimulationRunner.run_simulation_pipeline` (`_fit_check_service_stops`, before Pass 1). A train longer than the physical (parent) platform it stops at is **disclosed, not rejected**:

- `WARNING_TRAIN_OVERHANG` record in `package.metadata["warnings"]` and Section 0.0;
- Section 6 "Overhang (m)" and Section 11 "Train Fits" columns;
- the simulation continues and its results are unchanged.

`src/headway/reporting/report_config.py` defines the escalation threshold, which v1.15.1 does not read:

```python
TRAIN_OVERHANG_ERROR_LIMIT_M: Optional[float] = None
```

## Proposal

- When `TRAIN_OVERHANG_ERROR_LIMIT_M` is a float and a stop's overhang `L - P` exceeds it, raise `ERR_TRAIN_OVERHANG` (`TrainOverhangError`, already defined in `infrastructure/stations.py`) before Pass 1, instead of recording a warning. Overhangs at or below the limit keep the v1.15.1 warning.
- `None` keeps v1.15.1 behaviour (warn only). Decide whether the default stays `None` or becomes a value, and whether the limit should be project-level (workbook) rather than a module constant.
- The error message names the train type, parent platform, stop segment, direction, `L`, `P`, the overhang and the limit, and points at the constant.
- Tests in FORWARD and REVERSE: an overhang below, equal to and above the limit; `None` (warn only); and the shipped examples unchanged.
- Note: `tests/integration/test_v1151_fit_check_wiring.py::test_overhang_error_limit_not_enforced` asserts the v1.15.1 non-enforcement and must be migrated.

## Reference cases

- u8000 (user project): TRN_HSR 202 m. Each direction has three 2.0 m overhangs: PLT_ADS 200.00 m, PLT_YAS 123.12 + 76.88 m and PLT_AUH 61.08 + 138.92 m. Any limit ≥ 2.0 m keeps u8000 running.
- Shipped examples: no overhang.

## Related

- `docs/issues/fit_check_not_wired.md` (resolved in v1.15.1), item 3: tighten the berth containment allowance once too-long trains are rejected.
