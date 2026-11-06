# Dispatcher picks the origin entry block without regard to running direction or offset (dispatching.py)

> Issue draft — to be filed on GitHub (deferred from PR #68). The first heading is the issue title; the rest is the issue body.

## Summary
Deferred from PR #68 (v1.14.0 Platform schema replacement). It's out of scope there because it's unrelated to the platform schema.

When a train is dispatched from its origin, `OriginDepartureQueue` chooses the "entry block" to **check** (`can_authorize_entry`, `src/headway/simulation/dispatching.py` ~L141–155) and to **reserve** (`dispatch_candidate`, ~L203–214) as:

```python
# first TRACK_BLOCK, in resource-registration order, with ANY interval on the route's first link
if any(inv.link_id == first_link_id for inv in res.intervals) or res_id == f"BLK_{first_link_id}":
    ... reserve ...; break
```

## Problems (from code reading; a reproducer is part of this issue)
1. **Not direction-aware.** On a first link that holds more than one block, FORWARD and REVERSE pick the **same** block: whichever was registered first. A REVERSE train enters the link at its **end** offset, so its real entry block is the one containing the link end. The dispatcher checks and reserves a different block, and the true entry block is neither checked nor reserved at dispatch.
2. **Not offset-aware.** Selection uses "any interval on the link", not "the interval containing the train's entry offset" (the traversal's start offset in its running direction).
3. **Order-dependent and name-convention fallback.** The result depends on dict/registration order, and the `res_id == f"BLK_{first_link_id}"` fallback matches by naming convention only.
4. **State is mutated before a reservation that can raise.** `dispatch_candidate` removes the train from the queue and sets `RUNNING`/`ACCELERATING` *before* calling `reserve_resource`, which raises `ResourceConflictError` if the block (or a shared-group peer) is unavailable. The authorization check (1–3) may have looked at a different block.

## Expected
- Entry block = the TRACK_BLOCK whose interval on the first link contains the train's entry offset **in its running direction** (FWD: traversal start, REV: link end). Fail with a named `ERR_*` if none or more than one matches.
- `can_authorize_entry` and `dispatch_candidate` use the **same** selection (one helper).
- Reserve first, then transition state (or make the transition atomic).
- Tests in **both FORWARD and REVERSE** on a first link with ≥ 2 blocks.

## Notes
- The physics engine itself is not involved; this is the dispatching/resource layer.
- Shipped examples should be re-checked for headway/journey parity after the fix, because the entry-block reservation timing feeds blocking time.
