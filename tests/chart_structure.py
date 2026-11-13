"""v1.15.2: Plotly-version-tolerant chart fingerprints (docs/issues/plotly_upgrade_checklist.md).

``hashlib.sha256(fig.to_json())`` pins Plotly's serialisation, including its default template, so it
changes on every Plotly upgrade even when the chart is identical. The structural fingerprint records
only what the simulator puts on the chart:

- ``trace_count``: number of traces;
- ``trace_names``: trace names, sorted;
- ``x_range``: ``[min, max]`` of every trace's x data (rounded to 1e-6). The report charts autorange,
  so the axis range is the data range;
- ``points_per_trace``: ``[name, number of x points]`` per trace, in trace order.

The SHA-256 fixtures are kept. ``assert_chart_matches`` still requires byte identity when the
installed Plotly is the version the hashes were captured with (``HASH_PLOTLY_VERSION``), so the
current stack (CI) is not loosened. On any other Plotly version only the structure is compared.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional

import plotly

FIXTURES = Path(__file__).parent / "fixtures"
STRUCTURE = json.loads((FIXTURES / "v1142_chart_structure.json").read_text())
HASH_PLOTLY_VERSION: str = STRUCTURE["hash_plotly_version"]


def _x_values(trace: Any):
    xs = getattr(trace, "x", None)
    return () if xs is None else xs


def chart_structure(fig: Any) -> Dict[str, Any]:
    """Structural fingerprint of a Plotly figure (see module docstring)."""
    traces = list(fig.data)
    finite = [
        float(v) for t in traces for v in _x_values(t)
        if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))
    ]
    return {
        "trace_count": len(traces),
        "trace_names": sorted(str(t.name) for t in traces),
        "x_range": [round(min(finite), 6), round(max(finite), 6)] if finite else None,
        "points_per_trace": [[str(t.name), len(_x_values(t))] for t in traces],
    }


def assert_chart_matches(fig: Any, structure: Dict[str, Any], sha256: Optional[str] = None) -> None:
    """Structural comparison always; byte identity too when Plotly matches the hash fixtures."""
    assert chart_structure(fig) == structure
    if sha256 is not None and plotly.__version__ == HASH_PLOTLY_VERSION:
        assert hashlib.sha256(fig.to_json().encode()).hexdigest() == sha256
