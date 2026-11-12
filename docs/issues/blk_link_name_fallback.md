# `BLK_<link>` name-convention fallback treats a block as "on a link" by its ID alone (target: v1.15.2)

**Status:** open. Noted during v1.15.0 (dispatcher entry-block fix, #69). Deliberately out of scope there (decision D5b): v1.15.0 preserves the fallback unchanged.

## Observation

Several code paths decide whether a TRACK_BLOCK lies on a link by checking its intervals, **or** by checking whether its ID is `BLK_<link_id>`:

- `simulation/dispatching.py` `select_entry_block` (v1.15.0): candidate if `any(inv.link_id == first_link_id ...)` **or** `res.resource_id == f"BLK_{first_link_id}"`. A name-matched block with no interval on the link is entered at the link entry.
- `simulation/multi_train_engine.py` `_get_route_resource_intervals` (~L196): a resource with no matching interval but ID `BLK_<link>` gets an interval covering the whole link.
- `simulation/multi_train_engine.py` `_get_route_block_eoa_entries` (~L235): same match for EOA block entries.

The match depends only on a naming convention, so:

1. A block whose ID happens to be `BLK_<link>` is placed on that link, even if its geometry (link intervals) says otherwise.
2. A block without intervals is silently given whole-link geometry. Strict geometry validation (`ERR_BLOCK_*`) does not see this path.

None of the shipped examples (01–07, corrected variants) or the u8000 user project relies on the fallback for its result. The unit test `tests/unit/test_multi_train_negative.py::test_starvation_warning_in_origin_queue` does: it registers an interval-less `ManagedResource("BLK_<first link>")` to block the origin.

## Expected

- Block-to-link membership comes from link intervals only.
- A TRACK_BLOCK with no link intervals is rejected at registration with a named `ERR_*`, consistent with "prefer loud failure", or this is explicitly documented as a supported synthetic-test convention.
- Migrate the starvation test to a block with an explicit interval, keeping its coverage.
- Verify FORWARD and REVERSE.

## References

- v1.15.0 PR (dispatcher entry-block selection, closes #69). The fallback is preserved there.
- `issue69_audit` pre-flight: `pf_noblock_plugin` run over the full suite. 2 of 155 dispatcher-using tests have no interval block on the route, one of which is the starvation test above.
