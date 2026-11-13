# `VERSION_INFO` and `get_build_info()["phase"]` are stale (target: v1.15.2)

**Status:** resolved in v1.15.2. `VERSION_INFO: Tuple[int, ...] = tuple(int(p) for p in __version__.split("."))` and `get_build_info()["phase"] = f"Release {__version__}"`. `tests/unit/test_version.py` now asserts both against `__version__` (the hard-coded `(1, 11, 3)` and `len == 3` pins are gone). Originally noted during v1.15.0.1 (report direction in a UI session), where it was out of scope (decision D3).

## Observation

`src/headway/core/version.py`:

```python
__version__: str = "1.15.0.1"

VERSION_INFO: Tuple[int, int, int] = (1, 11, 3)
```

- `VERSION_INFO` has not been bumped since v1.11.3, so it disagrees with `__version__` across every release from v1.11.4 to v1.15.0.1.
- `get_build_info()` returns `"phase": "Release 1.11.2"`, which is older still.
- `VERSION_INFO` is a 3-tuple and cannot represent a four-part version such as `1.15.0.1`.
- `tests/unit/test_version.py` **pins** the stale values: `test_version_info` asserts `len(VERSION_INFO) == 3` and `VERSION_INFO == (1, 11, 3)`, and `test_build_info` asserts `info["version_info"] == (1, 11, 3)`. For `phase` it checks only `"Release" in info["phase"]`. The drift is therefore locked in by tests rather than caught.
- `VERSION_INFO` is re-exported from `headway.core` and `headway` (`__all__` in both `__init__.py`), so it is public API.

## Expected

- `VERSION_INFO` is derived from `__version__` (for example `tuple(int(p) for p in __version__.split("."))`), with its type widened to `Tuple[int, ...]`, so there is a single source of truth.
- `get_build_info()["phase"]` is derived from `__version__`, or removed.
- `test_version.py` asserts that `VERSION_INFO` and `phase` agree with `__version__`, replacing the hard-coded `(1, 11, 3)` and the `len == 3` assertion.
- Check consumers of `VERSION_INFO` and `get_build_info()["version_info"]` before changing the tuple length. On v1.15.0.1 the only in-repo consumers are the re-exports and `test_version.py`.

## References

- v1.15.0.1 PR (report direction authoritative from the package). Decision D3.
