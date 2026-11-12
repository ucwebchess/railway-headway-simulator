# Origin authorization checks `SIG_<link>_START` regardless of running direction (target: v1.15.2)

**Status:** open. Noted during v1.15.0 (dispatcher entry-block fix, #69). Out of scope there (decision D5d); the lookup is unchanged.

## Observation

`OriginDepartureQueue.can_authorize_entry` (`src/headway/simulation/dispatching.py`), step 2:

```python
first_sig = coordinator.signal_controller.signals.get(f"SIG_{first_link_id}_START")
if first_sig and first_sig.current_aspect.value == "RED":
    return False, f"ENTRY_SIGNAL_RED_{first_sig.signal_id}"
```

- The lookup uses a naming convention (`SIG_<first link>_START`) and ignores the running direction. A REVERSE train enters its first link at the link **end**, but the check still looks for the signal named after the link start.
- No signal in the shipped examples (01–07) or the u8000 user project uses the `_START` suffix, so the check never finds a signal today. It is a no-op on all known data, and the origin signal aspect is not part of the dispatch authorization.

## Expected

- The origin entry signal comes from the signalling data, not from a name: the entry signal of the block chosen by `select_entry_block`, i.e. `SignallingBlock.entry_signal_id`, which is direction-aware by construction.
- If no such signal exists, keep today's behaviour (no aspect check) and document it. Alternatively raise a named `ERR_*` if an origin signal is mandatory.
- Test in FORWARD and REVERSE with a RED origin signal: the train is held with `ENTRY_SIGNAL_RED_<id>`.

## References

- v1.15.0 PR (dispatcher entry-block selection, closes #69). Out-of-scope list.
