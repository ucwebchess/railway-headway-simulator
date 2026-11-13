# Plotly upgrade checklist

**Status:** filed in v1.15.2 (reference procedure, not a defect).

## Why

Two chart regression tests pin the default-off charts:

| Test | Structure fixture section | SHA-256 fixture |
|---|---|---|
| `tests/integration/test_v1143_chart_overlays.py::test_default_off_byte_identical_to_v1142` (04/07 × FWD/REV × speed/stairway) | `v1142_default_off` | `tests/fixtures/v1142_chart_hashes.json` |
| `tests/integration/test_v1142_chart_overlays.py::test_tvs_overlay_absent_when_flag_false` (07 FWD, speed/stairway) | `v1141_default_off` | `tests/fixtures/v1141_chart_hashes.json` |

`fig.to_json()` embeds Plotly's default template, so the SHA-256 values change on **any** Plotly upgrade, even when the chart is identical. Since v1.15.2 both tests go through `tests/chart_structure.py::assert_chart_matches`:

- **Always:** compare the structural fingerprint in `tests/fixtures/v1142_chart_structure.json`: trace count, sorted trace names, x range `[min, max]` of all trace data (the charts autorange), and `[name, points]` per trace. Trace names in order are also still asserted.
- **Only when `plotly.__version__ == hash_plotly_version`** (in the structure file; currently `7.1.0`): also require the SHA-256 (byte identity).

After a Plotly upgrade, the structural tests must still pass and the SHA-256 checks are skipped automatically. A structural failure after an upgrade means the chart content changed. Investigate it; do not regenerate the fixture to make it pass.

The structure does not cover y values, bar bases, annotations or styling. On a non-matching Plotly version those are covered only by the other chart tests.

## Procedure when upgrading Plotly

1. Upgrade Plotly in the environment and in CI (`requirements.txt` / `pyproject.toml`). Record the new version.
2. Run the two tests above. **The structural assertions must pass unchanged.** Do not edit `v1142_chart_structure.json` to make them pass.
3. Regenerate the SHA-256 fixtures in the CI environment (same Python, pandas and numpy as CI), on an unmodified commit, from the same figures:
   - `v1142_chart_hashes.json`: `doc.figures_data[chart]` from `SimulationRunner.run_simulation_pipeline(load_corrected_variant(example)[0], running_direction=d)`.
   - `v1141_chart_hashes.json`: the 07_hsr_140km FORWARD figures built in `test_tvs_overlay_absent_when_flag_false`.
   - Update each file's `_comment` with the new environment.
4. Set `hash_plotly_version` in `tests/fixtures/v1142_chart_structure.json` to the new version, so byte identity is enforced again.
5. Note the upgrade and the regenerated fixtures in `docs/CHANGELOG.md`.

Other plotly-version-specific pins to check at the same time: `tests/fixtures/v1142_chart_hashes.json` `_comment` (environment record) and any CHANGELOG notes referring to chart hashes.
