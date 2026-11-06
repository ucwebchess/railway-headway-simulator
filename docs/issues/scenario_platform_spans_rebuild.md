# Scenario overrides of platform_spans do not regenerate platform segments / stop segment

> Issue draft — to be filed on GitHub (deferred from PR #68). The first heading is the issue title; the rest is the issue body.

## Summary
Deferred from PR #68 (v1.14.0 Platform schema replacement). It's a scenario-layer defect, so it's out of scope there.

Since v1.14.0 the importer auto-segments each `PlatformSpans` row into link-level platforms `<PLATFORM_ID>@s<N>` (`infrastructure.platforms`) plus one stopping point `<PLATFORM_ID>@stop` (`infrastructure.stopping_points`). The stopping point marks the stop segment selected by `SEGMENT_HINT_OFFSET_M`. This happens **once**, in `convert_raw_to_canonical`.

`apply_scenario_overrides` (`src/headway/scenarios/engine.py`) can target `platform_spans` (it is in `PRIMARY_ID_MAP`), but it only patches the dict and re-validates the model. It does **not** re-run the segmentation. So an override of
- `start_chainage_km` / `end_chainage_km` (lengthen, shorten or move a platform), or
- `segment_hint_offset_m` (choose a different stop segment), or
- `track_id` / `station_id`

changes `platform_spans` but leaves the **old** segments and the old stop segment in place. The simulation (which runs on `platforms` + `stopping_points` via `project_with_stop_segments`) silently ignores the override, and Section 6/11 report stale segments. No error is raised.

Conversely, overriding a generated segment directly (`platforms` / `PLT_X@s2`) bypasses the span. Its geometry then disagrees with the span, also silently.

## Expected
- After applying overrides, regenerate `platforms` + `stopping_points` from the effective `platform_spans` via `headway.data.platform_spans.segment_all_platform_spans`. This raises the usual `ERR_PLATFORM_SPAN_*` / `ERR_PLATFORM_SEGMENT_HINT_INVALID` for invalid overrides.
- Refuse overrides that target generated objects (`platforms` / `stopping_points` IDs containing `@`) with a named `ERR_*` that points to `platform_spans`.
- Tests: an override that lengthens a span across a link boundary yields the new segments and the new stop segment, and the simulation uses them (both FORWARD and REVERSE). An override of `segment_hint_offset_m` moves the stop segment. An override of a segment ID is refused.
