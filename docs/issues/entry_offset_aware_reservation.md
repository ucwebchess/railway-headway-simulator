# Origin entry block is reserved at dispatch even when it starts far ahead of the train (target: v1.15.2)

**Status:** open. Noted during v1.15.0 (dispatcher entry-block fix, #69). Out of scope there (decision D7). v1.15.0 discloses the case with `WARNING_ENTRY_GAP` but does not change the reservation time.

## Observation

`OriginDepartureQueue.dispatch_candidate` reserves the entry block at the dispatch instant (t = departure). Since v1.15.0 the block is selected direction-aware (`select_entry_block`), but the reservation time does not depend on how far ahead of the train the block starts.

Example 03 (single link `LNK_STN_01`, 1500 m; `BLK_STN_01` covers offsets 100–750 m):

| Direction | Entry point → block entry | Section 10 row 1 Approach | Technical headway |
|---|---|---|---|
| FORWARD | 0 → 100 m | 17.0 s | 140 s |
| REVERSE | 0 → 750 m (route frame) | **51.0 s** | **179 s** |

In REVERSE the block is held from t = 0 while the train covers the 750 m run-in, so the blocking interval and the headway grow. v1.15.0 reports this with `WARNING_ENTRY_GAP` (gap 750 m > `max(train length 160 m, 100 m)`), once per train in `package.metadata["warnings"]` and in report Section 0.0. The headway (179 s) is unchanged by v1.15.0.

## Expected (to be decided)

- Reserve the origin entry block when the train reaches the block's approach point, i.e. entry minus (sighting + reaction + setup) running time, instead of at dispatch. Alternatively start the origin block's blocking interval at the same point it would have for a non-origin block.
- Unchanged where the train starts inside, or at the entry of, its first block (05c, 07c), and in both directions symmetrically.
- Verify FORWARD and REVERSE. Expected change: 03 REV headway drops towards the FORWARD value. Other shipped examples (06: 100 m run-in in both directions) to be re-baselined explicitly.

## References

- v1.15.0 PR (dispatcher entry-block selection, closes #69). `test_03_reverse_warns_entry_gap` pins the current 179 s.
