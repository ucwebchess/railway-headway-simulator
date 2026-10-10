"""Statistical summary engine and confidence interval calculations.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- P11-STAT-001 to P11-STAT-004: Standard statistical summary (mean, median, std, min, max, P5..P99)
- P11-CI-001 to P11-CI-005: Mean confidence intervals and Wilson score proportion intervals
- Numerical Benchmarks A, B, C, D calculations
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
import scipy.stats


@dataclass
class StatisticalSummary:
    """P11 Section 23: Comprehensive descriptive statistics for a simulated metric."""

    metric_name: str
    sample_count: int
    mean: float
    median: float
    std_dev: float
    min_value: float
    max_value: float
    p5: float
    p50: float
    p90: float
    p95: float
    p99: float
    confidence_interval_95: Optional[Tuple[float, float]] = None
    unit: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "sample_count": self.sample_count,
            "mean": self.mean,
            "median": self.median,
            "std_dev": self.std_dev,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "p5": self.p5,
            "p50": self.p50,
            "p90": self.p90,
            "p95": self.p95,
            "p99": self.p99,
            "confidence_interval_95": self.confidence_interval_95,
            "unit": self.unit,
        }


def compute_statistical_summary(
    data: Sequence[float],
    metric_name: str = "METRIC",
    unit: str = "",
    confidence_level: float = 0.95,
) -> StatisticalSummary:
    """Compute standard statistical summaries and confidence intervals without premature rounding."""
    clean_data = [float(x) for x in data if math.isfinite(x)]
    n = len(clean_data)

    if n == 0:
        return StatisticalSummary(
            metric_name=metric_name,
            sample_count=0,
            mean=0.0,
            median=0.0,
            std_dev=0.0,
            min_value=0.0,
            max_value=0.0,
            p5=0.0,
            p50=0.0,
            p90=0.0,
            p95=0.0,
            p99=0.0,
            confidence_interval_95=None,
            unit=unit,
            details={"warning": "INSUFFICIENT_DATA"},
        )

    arr = np.asarray(clean_data, dtype=float)
    mean_val = float(np.mean(arr))
    median_val = float(np.median(arr))
    std_val = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    min_val = float(np.min(arr))
    max_val = float(np.max(arr))

    # Quantiles using linear interpolation
    p5 = float(np.percentile(arr, 5))
    p50 = float(np.percentile(arr, 50))
    p90 = float(np.percentile(arr, 90))
    p95 = float(np.percentile(arr, 95))
    p99 = float(np.percentile(arr, 99))

    ci_mean = None
    if n >= 2 and std_val > 0.0:
        ci_mean = compute_mean_confidence_interval(arr, confidence_level=confidence_level)

    return StatisticalSummary(
        metric_name=metric_name,
        sample_count=n,
        mean=mean_val,
        median=median_val,
        std_dev=std_val,
        min_value=min_val,
        max_value=max_val,
        p5=p5,
        p50=p50,
        p90=p90,
        p95=p95,
        p99=p99,
        confidence_interval_95=ci_mean,
        unit=unit,
    )


def compute_mean_confidence_interval(
    data: Sequence[float],
    confidence_level: float = 0.95,
) -> Optional[Tuple[float, float]]:
    """P11-CI-001: Confidence interval for sample mean using Student's t-distribution."""
    if not (0.0 < confidence_level < 1.0):
        raise ValueError(f"Confidence level must be strictly between 0 and 1 (got {confidence_level}).")
    clean = [float(x) for x in data if math.isfinite(x)]
    n = len(clean)
    if n < 2:
        return None

    mean = float(np.mean(clean))
    std = float(np.std(clean, ddof=1))
    if std == 0.0:
        return (mean, mean)

    alpha = 1.0 - confidence_level
    t_crit = float(scipy.stats.t.ppf(1.0 - alpha / 2.0, df=n - 1))
    margin = t_crit * (std / math.sqrt(n))

    return (mean - margin, mean + margin)


def compute_wilson_score_interval(
    success_count: int,
    total_count: int,
    confidence_level: float = 0.95,
) -> Tuple[float, Tuple[float, float]]:
    """P11-CI-002: Wilson score confidence interval for binomial proportions.

    Recommended for railway punctuality and reliability proportions.
    """
    if not (0.0 < confidence_level < 1.0):
        raise ValueError(f"Confidence level must be strictly between 0 and 1 (got {confidence_level}).")
    if total_count < 0:
        raise ValueError(f"Total trials must be non-negative (got {total_count}).")
    if total_count == 0:
        return 0.0, (0.0, 0.0)
    if success_count < 0 or success_count > total_count:
        raise ValueError(f"Invalid success_count {success_count} for total_count {total_count}.")

    p_hat = float(success_count) / float(total_count)
    if total_count == 1:
        return p_hat, (0.0, 1.0)

    alpha = 1.0 - confidence_level
    z = float(scipy.stats.norm.ppf(1.0 - alpha / 2.0))
    z2 = z ** 2
    n = float(total_count)

    center = (p_hat + z2 / (2.0 * n)) / (1.0 + z2 / n)
    spread = (z / (1.0 + z2 / n)) * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n ** 2)))

    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)

    return p_hat, (lower, upper)
