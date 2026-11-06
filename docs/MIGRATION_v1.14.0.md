# Migration Guide — v1.14.0: `Platforms` → `PlatformSpans`

**v1.14.0 is a breaking schema change.** The Infrastructure workbook's `Platforms` and
`StoppingPoints` sheets are replaced by a single `PlatformSpans` sheet with **one row per
physical platform**. Workbooks that still contain `Platforms` or `StoppingPoints` are
**rejected on import** (`ERR_PLATFORMS_DEPRECATED`, `ERR_STOPPINGPOINTS_DEPRECATED`);
there is no backward compatibility and no automatic migration in the importer.

Quick path:

1. `python docs/migrate_platforms.py HEADWAY_INFRASTRUCTURE.xlsx --operations HEADWAY_OPERATIONS.xlsx`
2. Review the printed table (one row per platform, with its source rows).
3. Load the workbooks written to `migrated_v1.14/` (originals are not modified).

Why: a 400 m platform crossing four track links used to need four `Platforms` rows,
four IDs, and a `StoppingPoints` row on the right one. It is now one row; the importer
splits it into link-level segments for the simulation automatically.

---

## 1. The new `PlatformSpans` sheet

| Column | Required | Unit | Meaning |
|---|---|---|---|
| `PLATFORM_ID` | yes | — | Unique platform ID (unique across the workbook). This is the ID you use everywhere (StoppingPatterns, reports). |
| `STATION_ID` | yes | — | Must exist in `Stations`. |
| `TRACK_ID` | yes | — | Must exist in `Tracks`. |
| `START_CHAINAGE_KM` | yes | km | Where the platform begins, in **per-track chainage**. |
| `END_CHAINAGE_KM` | yes | km | Where the platform ends (`END > START`, length ≥ 10 m). |
| `SEGMENT_HINT_OFFSET_M` | no | m | **Segment hint**, measured from `START_CHAINAGE_KM`. Blank → mid-platform, `(END − START) / 2`. Must lie within `[0, length]`. It only selects **which segment** the train berths on (§2); it is **not** the exact stop position. A column still named `NOMINAL_STOP_OFFSET_M` is rejected with `ERR_PLATFORM_SPAN_DEPRECATED_COLUMN` (§6). |
| `DESCRIPTION` | no | — | Free text. |

**Per-track chainage.** Each track starts at **0 km at the start node of its first link**;
its links are laid end to end in topological order (`START_NODE_ID` → `END_NODE_ID`), so a
track covers `0 … Σ LENGTH_M` of its links. `Stations.CHAINAGE_KM` is informational and
is **not** used. The span must lie within the track's coverage.

## 2. What the importer does with a span (auto-segmentation)

For each span the importer walks the track's links in order and creates one link-level
platform **segment** per overlapped link:

- Segment ID `<PLATFORM_ID>@s<N>` — `N` is 1-based in link order. The format is stable
  across versions; the same input always gives the same IDs.
- Each segment carries `parent_platform_id = <PLATFORM_ID>`, the station, the link, and
  the start/end offsets on that link.
- The segment hint point (`START + SEGMENT_HINT_OFFSET_M`) selects the segment that
  contains it (on a boundary between two segments, the first one wins). That segment is the
  platform's **stop segment**; the tool records it with an internal stopping point
  (`<PLATFORM_ID>@stop`).

**Berthing.** The simulation berths the train in the stop segment using the unchanged
berthing rule (FORWARD: train front at segment start + min(train length, segment length);
REVERSE: mirrored from the segment end) — exactly what v1.13 did with the `Platforms` row
your StoppingPattern referenced. So `SEGMENT_HINT_OFFSET_M` chooses the berthing
segment; it is not an exact train-front position (hence the name). To berth in a particular
link-level part of a long platform, put the hint inside that part.

**Train fit.** Whether a train fits is checked against the **whole physical platform**: the
sum of its segment lengths (`parent_platform_length_m`), not the stop segment alone. A
202 m train berthing on a 200 m segment of a 400 m platform fits; a train longer than the
whole platform fails with `ERR_TRAIN_OVERHANG`.

Segment IDs are generated: you cannot enter them yourself (IDs containing `@` are rejected),
and StoppingPatterns must not reference them (`ERR_STOPPING_PATTERN_REFERENCES_SEGMENT`).

## 3. Worked example — 400 m platform over 4 links → 1 span

Track `TRK_UP` consists of these links (in order):

| LINK_ID | LENGTH_M | Track chainage (km) |
|---|---|---|
| LNK_09 | 1000 | 0.000 – 1.000 |
| LNK_10 | 500 | 1.000 – 1.500 |
| LNK_11 | 80 | 1.500 – 1.580 |
| LNK_12 | 120 | 1.580 – 1.700 |
| LNK_13 | 300 | 1.700 – 2.000 |

**Before (v1.13 and earlier)** — four `Platforms` rows and one `StoppingPoints` row:

| PLATFORM_ID | STATION_ID | LINK_ID | START_OFFSET_M | END_OFFSET_M |
|---|---|---|---|---|
| PLT_CEN_1_1 | STN_CEN | LNK_10 | 380 | 500 |
| PLT_CEN_1_2 | STN_CEN | LNK_11 | 0 | 80 |
| PLT_CEN_1_3 | STN_CEN | LNK_12 | 0 | 120 |
| PLT_CEN_1_4 | STN_CEN | LNK_13 | 0 | 80 |

| STOPPING_POINT_ID | PLATFORM_ID | LINK_ID | OFFSET_M |
|---|---|---|---|
| SP_CEN_1 | PLT_CEN_1_4 | LNK_13 | 70 |

StoppingPatterns referenced `PLT_CEN_1_4` (the row holding the stop).

**After (v1.14.0)** — one `PlatformSpans` row:

| PLATFORM_ID | STATION_ID | TRACK_ID | START_CHAINAGE_KM | END_CHAINAGE_KM | SEGMENT_HINT_OFFSET_M |
|---|---|---|---|---|---|
| PLT_CEN_1 | STN_CEN | TRK_UP | 1.380 | 1.780 | 390 |

- Start = 1000 (LNK_09) + 380 = 1380 m → 1.380 km; end = 1500 + 80 + 120 + 80 = 1780 m → 1.780 km.
- Stop = LNK_13 start (1700 m) + 70 = 1770 m → offset from start = 1770 − 1380 = **390 m**.
- StoppingPatterns now reference **`PLT_CEN_1`**.

The importer regenerates exactly the old geometry:

| Segment | LINK_ID | Start (m) | End (m) |
|---|---|---|---|
| PLT_CEN_1@s1 | LNK_10 | 380 | 500 |
| PLT_CEN_1@s2 | LNK_11 | 0 | 80 |
| PLT_CEN_1@s3 | LNK_12 | 0 | 120 |
| PLT_CEN_1@s4 | LNK_13 | 0 | 80 ← stop at 70 m (`PLT_CEN_1@stop`) |

Simulation results are unchanged; reports show `PLT_CEN_1` (Section 6 lists the segments
in its `Segments` column and footnote; Section 11 has one provenance row per segment with
its `Parent Platform`).

## 4. Step by step

### 4.1 Automatic (recommended)

```bash
python docs/migrate_platforms.py path/to/HEADWAY_INFRASTRUCTURE.xlsx \
    --operations path/to/HEADWAY_OPERATIONS.xlsx            # rewrites StoppingPatterns.PLATFORM_ID
# options: --out-dir DIR (default: <input folder>/migrated_v1.14), --in-place, --dry-run
```

The helper:

1. places every `Platforms` row on its track's per-track chainage (from `TrackLinks.LENGTH_M`);
2. groups rows into one platform when they share `STATION_ID`, track and ID stem (the ID
   without a trailing `_<n>`/`-<n>`) **and** are contiguous along the track — a single row
   keeps its ID, a multi-row group is named by the stem (`PLT_CEN_1_1…_4` → `PLT_CEN_1`);
3. converts each `StoppingPoints` row into `SEGMENT_HINT_OFFSET_M`;
4. writes the Infrastructure copy without `Platforms`/`StoppingPoints` and with `PlatformSpans`,
   and (with `--operations`) the Operations copy with StoppingPatterns pointing at the new IDs;
5. copies the other workbooks so the output folder is a complete project.

Review the printed table and warnings (non-contiguous rows with the same stem, platforms
with several or no stopping points, spans under 10 m). Rename platforms if you prefer
other IDs — then update StoppingPatterns accordingly.

### 4.2 Manual

1. Add a `PlatformSpans` sheet (headers as in §1; download the v1.14.0 template from the
   app for the exact layout).
2. For each physical platform, compute start/end on the per-track chainage (§1) and enter one row.
3. Delete the `Platforms` and `StoppingPoints` sheets.
4. In the Operations workbook, set `StoppingPatterns.PLATFORM_ID` to the new `PLATFORM_ID`s.

## 5. Migrating `StoppingPoints`

`StoppingPoints` is removed. Its information moves to `PlatformSpans.SEGMENT_HINT_OFFSET_M`:

```
SEGMENT_HINT_OFFSET_M = (track chainage of the stopping point's link start + OFFSET_M) − START_CHAINAGE_KM × 1000
```

One segment hint per platform. A platform without a stopping point gets a mid-platform hint
(previously it had none); it is still only occupied if a StoppingPattern stops there.

## 6. Error reference

Every message names the offending sheet/ID and points to this guide.

| Code | Raised when | Fix |
|---|---|---|
| `ERR_PLATFORMS_DEPRECATED` | The Infrastructure workbook contains a `Platforms` sheet. | Migrate to `PlatformSpans` (§4), delete the sheet. |
| `ERR_STOPPINGPOINTS_DEPRECATED` | The Infrastructure workbook contains a `StoppingPoints` sheet. | Move offsets to `SEGMENT_HINT_OFFSET_M` (§5), delete the sheet. |
| `ERR_PLATFORM_SPAN_INVALID` | `START ≥ END`; span < 10 m; `STATION_ID` / `TRACK_ID` not found; a generated-style ID (`…@s<N>`) entered by hand; the track is not a simple link chain. | Correct the row. |
| `ERR_PLATFORM_SPAN_EXCEEDS_TRACK` | The span lies (partly) outside the track's coverage `0 … Σ link lengths`. | Check per-track chainage (§1). |
| `ERR_PLATFORM_SPAN_DUPLICATE` | A `PLATFORM_ID` appears more than once. | Use unique IDs. |
| `ERR_PLATFORM_SPAN_DEPRECATED_COLUMN` | The `PlatformSpans` sheet has a column named `NOMINAL_STOP_OFFSET_M` (its pre-release name). Message: *Column NOMINAL_STOP_OFFSET_M is deprecated. Rename it to SEGMENT_HINT_OFFSET_M. See docs/MIGRATION_v1.14.0.md.* | Rename the column header to `SEGMENT_HINT_OFFSET_M`; values stay the same. |
| `ERR_PLATFORM_SEGMENT_HINT_INVALID` | `SEGMENT_HINT_OFFSET_M` < 0 or > platform length. | Enter an offset within the platform. |
| `ERR_TRAIN_OVERHANG` | A train is longer than the whole physical platform it stops at (sum of the platform's segment lengths). | Lengthen the platform span or use a shorter train. |
| `ERR_STOPPING_PATTERN_REFERENCES_SEGMENT` | A StoppingPattern references a generated segment ID (`PLT_X@s2`). | Reference the platform `PLT_X`. |

## 7. Unchanged

- Results: the segments reproduce the link-level geometry of the old rows, so headway,
  journey time and block counts are unchanged (verified on all shipped examples).
- Segment ID format `<PLATFORM_ID>@s<N>` is a stable contract.
