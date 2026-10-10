"""Probability distributions and parameter sampling engines.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- P11-DIST-001 to P11-DIST-009: Validated implementations of:
  * Normal, Truncated Normal, Lognormal
  * Uniform, Triangular, Exponential
  * Empirical Discrete, Empirical Continuous
- Rejecting invalid distribution parameters (negative std, non-finite, inverted bounds)
"""

from __future__ import annotations

import abc
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
import scipy.special

from headway.analysis.random_variables import DistributionType


class ProbabilityDistribution(abc.ABC):
    """Abstract base class for validated probability distributions."""

    @property
    @abc.abstractmethod
    def distribution_type(self) -> DistributionType:
        """The canonical distribution type."""
        pass

    @abc.abstractmethod
    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        """Draw samples using the provided NumPy Generator."""
        pass

    @abc.abstractmethod
    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Cumulative distribution function F(x)."""
        pass

    @abc.abstractmethod
    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Percent point function (inverse CDF) F^{-1}(q) for q in (0, 1)."""
        pass

    @property
    @abc.abstractmethod
    def theoretical_mean(self) -> float:
        """Theoretical mean of the distribution."""
        pass

    @property
    @abc.abstractmethod
    def theoretical_variance(self) -> float:
        """Theoretical variance of the distribution."""
        pass


class NormalDistribution(ProbabilityDistribution):
    """P11-DIST-001: Gaussian normal distribution with mean mu and std dev sigma."""

    def __init__(self, mean: float, std_dev: float) -> None:
        if not math.isfinite(mean):
            raise ValueError(f"Normal mean must be finite (got {mean}).")
        if not math.isfinite(std_dev) or std_dev <= 0.0:
            raise ValueError(f"Normal std_dev must be strictly positive and finite (got {std_dev}).")
        self.mean = float(mean)
        self.std_dev = float(std_dev)

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.NORMAL

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        val = rng.normal(self.mean, self.std_dev, size=size)
        return float(val) if size is None else val

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        z = (np.asarray(x) - self.mean) / (self.std_dev * math.sqrt(2.0))
        res = 0.5 * (1.0 + scipy.special.erf(z))
        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        q_arr = np.asarray(q)
        if np.any((q_arr <= 0.0) | (q_arr >= 1.0)):
            raise ValueError("Quantile q must be strictly within (0, 1).")
        res = self.mean + self.std_dev * math.sqrt(2.0) * scipy.special.erfinv(2.0 * q_arr - 1.0)
        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        return self.mean

    @property
    def theoretical_variance(self) -> float:
        return self.std_dev ** 2


class TruncatedNormalDistribution(ProbabilityDistribution):
    """P11-DIST-002: Truncated normal distribution on interval [lower_bound, upper_bound]."""

    def __init__(self, mean: float, std_dev: float, lower_bound: float, upper_bound: float) -> None:
        if not math.isfinite(mean):
            raise ValueError(f"Mean must be finite (got {mean}).")
        if not math.isfinite(std_dev) or std_dev <= 0.0:
            raise ValueError(f"Std dev must be strictly positive and finite (got {std_dev}).")
        if not math.isfinite(lower_bound) or not math.isfinite(upper_bound):
            raise ValueError("Truncation bounds must be finite.")
        if lower_bound >= upper_bound:
            raise ValueError(f"lower_bound ({lower_bound}) must be strictly less than upper_bound ({upper_bound}).")

        self.mean = float(mean)
        self.std_dev = float(std_dev)
        self.lower_bound = float(lower_bound)
        self.upper_bound = float(upper_bound)

        # Standardized truncation bounds
        self._alpha = (self.lower_bound - self.mean) / self.std_dev
        self._beta = (self.upper_bound - self.mean) / self.std_dev

        self._norm = NormalDistribution(0.0, 1.0)
        self._cdf_a = float(self._norm.cdf(self._alpha))
        self._cdf_b = float(self._norm.cdf(self._beta))

        if self._cdf_b <= self._cdf_a:
            raise ValueError("Truncation bounds yield zero probability mass.")

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.TRUNCATED_NORMAL

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        # Inverse transform sampling on truncated uniform range [cdf_a, cdf_b]
        u = rng.uniform(self._cdf_a, self._cdf_b, size=size)
        res = self.mean + self.std_dev * np.asarray(self._norm.ppf(u))
        # Ensure bounds are strictly respected numerically
        res = np.clip(res, self.lower_bound, self.upper_bound)
        return float(res) if size is None else res

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        x_arr = np.asarray(x)
        z = (x_arr - self.mean) / self.std_dev
        f_z = np.asarray(self._norm.cdf(z))
        res = np.clip((f_z - self._cdf_a) / (self._cdf_b - self._cdf_a), 0.0, 1.0)
        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        q_arr = np.asarray(q)
        if np.any((q_arr <= 0.0) | (q_arr >= 1.0)):
            raise ValueError("Quantile q must be strictly within (0, 1).")
        u = self._cdf_a + q_arr * (self._cdf_b - self._cdf_a)
        res = self.mean + self.std_dev * np.asarray(self._norm.ppf(u))
        res = np.clip(res, self.lower_bound, self.upper_bound)
        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        phi_a = math.exp(-0.5 * self._alpha**2) / math.sqrt(2.0 * math.pi)
        phi_b = math.exp(-0.5 * self._beta**2) / math.sqrt(2.0 * math.pi)
        return self.mean + self.std_dev * (phi_a - phi_b) / (self._cdf_b - self._cdf_a)

    @property
    def theoretical_variance(self) -> float:
        phi_a = math.exp(-0.5 * self._alpha**2) / math.sqrt(2.0 * math.pi)
        phi_b = math.exp(-0.5 * self._beta**2) / math.sqrt(2.0 * math.pi)
        delta_phi = (phi_a - phi_b) / (self._cdf_b - self._cdf_a)
        t2 = (self._alpha * phi_a - self._beta * phi_b) / (self._cdf_b - self._cdf_a)
        return (self.std_dev ** 2) * (1.0 - t2 - delta_phi**2)


class LognormalDistribution(ProbabilityDistribution):
    """P11-DIST-003: Lognormal distribution.

    Parameters mu_log and sigma_log represent the mean and standard deviation
    of the underlying normal distribution ln(X) ~ N(mu_log, sigma_log^2).
    """

    def __init__(self, mean_log: float, std_log: float) -> None:
        if not math.isfinite(mean_log):
            raise ValueError(f"mean_log must be finite (got {mean_log}).")
        if not math.isfinite(std_log) or std_log <= 0.0:
            raise ValueError(f"std_log must be strictly positive and finite (got {std_log}).")
        self.mean_log = float(mean_log)
        self.std_log = float(std_log)
        self._norm = NormalDistribution(self.mean_log, self.std_log)

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.LOGNORMAL

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        val = rng.lognormal(self.mean_log, self.std_log, size=size)
        return float(val) if size is None else val

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        x_arr = np.asarray(x, dtype=float)
        res = np.zeros_like(x_arr)
        pos = x_arr > 0.0
        if np.any(pos):
            res[pos] = self._norm.cdf(np.log(x_arr[pos]))
        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        z = np.asarray(self._norm.ppf(q))
        res = np.exp(z)
        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        return math.exp(self.mean_log + 0.5 * self.std_log**2)

    @property
    def theoretical_variance(self) -> float:
        return (math.exp(self.std_log**2) - 1.0) * math.exp(2.0 * self.mean_log + self.std_log**2)


class UniformDistribution(ProbabilityDistribution):
    """P11-DIST-004 & BENCHMARK A: Continuous uniform distribution on [min_val, max_val]."""

    def __init__(self, min_val: float, max_val: float) -> None:
        if not math.isfinite(min_val) or not math.isfinite(max_val):
            raise ValueError("Uniform bounds must be finite.")
        if min_val >= max_val:
            raise ValueError(f"min_val ({min_val}) must be strictly less than max_val ({max_val}).")
        self.min_val = float(min_val)
        self.max_val = float(max_val)

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.UNIFORM

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        val = rng.uniform(self.min_val, self.max_val, size=size)
        return float(val) if size is None else val

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        x_arr = np.asarray(x)
        res = np.clip((x_arr - self.min_val) / (self.max_val - self.min_val), 0.0, 1.0)
        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        q_arr = np.asarray(q)
        if np.any((q_arr < 0.0) | (q_arr > 1.0)):
            raise ValueError("Quantile q must be within [0, 1].")
        res = self.min_val + q_arr * (self.max_val - self.min_val)
        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        return 0.5 * (self.min_val + self.max_val)

    @property
    def theoretical_variance(self) -> float:
        # Benchmark A: Var = (b - a)^2 / 12
        return ((self.max_val - self.min_val) ** 2) / 12.0


class TriangularDistribution(ProbabilityDistribution):
    """P11-DIST-005: Triangular distribution with lower bound, mode, and upper bound."""

    def __init__(self, min_val: float, mode_val: float, max_val: float) -> None:
        if not (math.isfinite(min_val) and math.isfinite(mode_val) and math.isfinite(max_val)):
            raise ValueError("Triangular bounds and mode must be finite.")
        if min_val >= max_val:
            raise ValueError(f"min_val ({min_val}) must be strictly less than max_val ({max_val}).")
        if not (min_val <= mode_val <= max_val):
            raise ValueError(f"mode_val ({mode_val}) must be within [{min_val}, {max_val}].")
        self.min_val = float(min_val)
        self.mode_val = float(mode_val)
        self.max_val = float(max_val)

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.TRIANGULAR

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        val = rng.triangular(self.min_val, self.mode_val, self.max_val, size=size)
        return float(val) if size is None else val

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        x_arr = np.asarray(x, dtype=float)
        a, c, b = self.min_val, self.mode_val, self.max_val
        res = np.zeros_like(x_arr)

        below_c = (x_arr > a) & (x_arr <= c)
        above_c = (x_arr > c) & (x_arr < b)
        past_b = x_arr >= b

        if c > a:
            res[below_c] = ((x_arr[below_c] - a) ** 2) / ((b - a) * (c - a))
        if b > c:
            res[above_c] = 1.0 - ((b - x_arr[above_c]) ** 2) / ((b - a) * (b - c))
        res[past_b] = 1.0

        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        q_arr = np.asarray(q, dtype=float)
        if np.any((q_arr < 0.0) | (q_arr > 1.0)):
            raise ValueError("Quantile q must be within [0, 1].")
        a, c, b = self.min_val, self.mode_val, self.max_val
        f_c = (c - a) / (b - a)
        res = np.zeros_like(q_arr)

        low = q_arr < f_c
        res[low] = a + np.sqrt(q_arr[low] * (b - a) * (c - a))
        res[~low] = b - np.sqrt((1.0 - q_arr[~low]) * (b - a) * (b - c))

        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        return (self.min_val + self.mode_val + self.max_val) / 3.0

    @property
    def theoretical_variance(self) -> float:
        a, c, b = self.min_val, self.mode_val, self.max_val
        return (a**2 + b**2 + c**2 - a * b - a * c - b * c) / 18.0


class ExponentialDistribution(ProbabilityDistribution):
    """P11-DIST-006: Exponential distribution with scale parameter beta (mean = beta = 1/lambda)."""

    def __init__(self, scale: Optional[float] = None, rate: Optional[float] = None) -> None:
        if scale is not None and rate is not None:
            if not math.isclose(scale, 1.0 / rate, rel_tol=1e-5):
                raise ValueError("Both scale and rate provided but are inconsistent.")
            effective_scale = scale
        elif scale is not None:
            effective_scale = scale
        elif rate is not None:
            if rate <= 0.0 or not math.isfinite(rate):
                raise ValueError(f"Rate must be strictly positive and finite (got {rate}).")
            effective_scale = 1.0 / rate
        else:
            raise ValueError("Either scale or rate must be provided for ExponentialDistribution.")

        if not math.isfinite(effective_scale) or effective_scale <= 0.0:
            raise ValueError(f"Scale must be strictly positive and finite (got {effective_scale}).")

        self.scale = float(effective_scale)

    @property
    def rate(self) -> float:
        return 1.0 / self.scale

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.EXPONENTIAL

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        val = rng.exponential(self.scale, size=size)
        return float(val) if size is None else val

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        x_arr = np.asarray(x, dtype=float)
        res = np.zeros_like(x_arr)
        pos = x_arr > 0.0
        res[pos] = 1.0 - np.exp(-x_arr[pos] / self.scale)
        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        q_arr = np.asarray(q, dtype=float)
        if np.any((q_arr < 0.0) | (q_arr >= 1.0)):
            raise ValueError("Quantile q must be in [0, 1).")
        res = -self.scale * np.log(1.0 - q_arr)
        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        return self.scale

    @property
    def theoretical_variance(self) -> float:
        return self.scale ** 2


class EmpiricalDiscreteDistribution(ProbabilityDistribution):
    """P11-DIST-007: Discrete distribution over finite set of values with probabilities summing to 1."""

    def __init__(self, values: Sequence[float], probabilities: Sequence[float]) -> None:
        if not values or not probabilities:
            raise ValueError("Values and probabilities must not be empty.")
        if len(values) != len(probabilities):
            raise ValueError(f"Lengths mismatch: {len(values)} values vs {len(probabilities)} probabilities.")

        vals = np.asarray(values, dtype=float)
        probs = np.asarray(probabilities, dtype=float)

        if not np.all(np.isfinite(vals)):
            raise ValueError("All values must be finite.")
        if np.any(probs < 0.0) or not np.all(np.isfinite(probs)):
            raise ValueError("Probabilities must be non-negative and finite.")

        total_p = float(np.sum(probs))
        if not math.isclose(total_p, 1.0, abs_tol=1e-4):
            raise ValueError(f"Probabilities must sum to 1.0 within tolerance (sum is {total_p}).")

        # Normalize to exactly 1.0
        probs = probs / total_p

        # Sort by value
        idx = np.argsort(vals)
        self.values = vals[idx]
        self.probabilities = probs[idx]
        self._cdf = np.cumsum(self.probabilities)

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.EMPIRICAL_DISCRETE

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        val = rng.choice(self.values, size=size, p=self.probabilities)
        return float(val) if size is None else val

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        x_arr = np.asarray(x, dtype=float)
        # For discrete, CDF(x) = sum_{v_i <= x} p_i
        idx = np.searchsorted(self.values, x_arr, side="right") - 1
        res = np.where(idx >= 0, self._cdf[np.clip(idx, 0, len(self.values) - 1)], 0.0)
        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        q_arr = np.asarray(q, dtype=float)
        if np.any((q_arr < 0.0) | (q_arr > 1.0)):
            raise ValueError("Quantile q must be within [0, 1].")
        idx = np.searchsorted(self._cdf, q_arr, side="left")
        idx = np.clip(idx, 0, len(self.values) - 1)
        res = self.values[idx]
        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        return float(np.sum(self.values * self.probabilities))

    @property
    def theoretical_variance(self) -> float:
        m = self.theoretical_mean
        return float(np.sum(self.probabilities * (self.values - m) ** 2))


class EmpiricalContinuousDistribution(ProbabilityDistribution):
    """P11-DIST-008: Continuous empirical distribution formed via sample data and linear interpolation."""

    def __init__(self, sample_values: Sequence[float], cumulative_probabilities: Optional[Sequence[float]] = None) -> None:
        if not sample_values or len(sample_values) < 2:
            raise ValueError("Empirical continuous distribution requires at least 2 distinct sample values.")

        vals = np.asarray(sample_values, dtype=float)
        if not np.all(np.isfinite(vals)):
            raise ValueError("All sample values must be finite.")

        if cumulative_probabilities is not None:
            cprobs = np.asarray(cumulative_probabilities, dtype=float)
            if len(cprobs) != len(vals):
                raise ValueError("sample_values and cumulative_probabilities must have equal lengths.")
            if not np.all(np.diff(cprobs) >= 0.0) or cprobs[0] < 0.0 or cprobs[-1] > 1.0:
                raise ValueError("Cumulative probabilities must be monotonically non-decreasing in [0, 1].")
            idx = np.argsort(vals)
            self.values = vals[idx]
            self.cum_probs = cprobs[idx]
        else:
            # Construct standard empirical cumulative distribution from raw sample observations
            self.values = np.sort(vals)
            n = len(self.values)
            # Uniform spacing across (0, 1)
            self.cum_probs = np.linspace(0.0, 1.0, n)

    @property
    def distribution_type(self) -> DistributionType:
        return DistributionType.EMPIRICAL_CONTINUOUS

    def sample(self, rng: np.random.Generator, size: Optional[int] = None) -> Union[float, np.ndarray]:
        u = rng.uniform(0.0, 1.0, size=size)
        res = np.interp(u, self.cum_probs, self.values)
        return float(res) if size is None else res

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        x_arr = np.asarray(x, dtype=float)
        res = np.interp(x_arr, self.values, self.cum_probs, left=0.0, right=1.0)
        return float(res) if np.ndim(x) == 0 else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        q_arr = np.asarray(q, dtype=float)
        if np.any((q_arr < 0.0) | (q_arr > 1.0)):
            raise ValueError("Quantile q must be within [0, 1].")
        res = np.interp(q_arr, self.cum_probs, self.values)
        return float(res) if np.ndim(q) == 0 else res

    @property
    def theoretical_mean(self) -> float:
        # Approximate mean via trapezoidal integration of values over cum_probs
        return float(np.trapezoid(self.values, self.cum_probs))

    @property
    def theoretical_variance(self) -> float:
        m = self.theoretical_mean
        m2 = float(np.trapezoid(self.values ** 2, self.cum_probs))
        return max(0.0, m2 - m**2)


def create_distribution(dist_type: DistributionType, params: Dict[str, Any]) -> ProbabilityDistribution:
    """P11-DIST-009: Factory validating and instantiating probability distributions."""
    try:
        if dist_type == DistributionType.NORMAL:
            return NormalDistribution(mean=params["mean"], std_dev=params["std_dev"])
        elif dist_type == DistributionType.TRUNCATED_NORMAL:
            return TruncatedNormalDistribution(
                mean=params["mean"],
                std_dev=params["std_dev"],
                lower_bound=params["lower_bound"],
                upper_bound=params["upper_bound"],
            )
        elif dist_type == DistributionType.LOGNORMAL:
            mean_log = params.get("mean_log", params.get("mu_log"))
            std_log = params.get("std_log", params.get("sigma_log"))
            if mean_log is not None and std_log is not None:
                return LognormalDistribution(mean_log=mean_log, std_log=std_log)
            elif "mean" in params and "std_dev" in params:
                # Convert normal mean & std dev to lognormal parameters
                m, s = params["mean"], params["std_dev"]
                s_log = math.sqrt(math.log(1.0 + (s / m)**2))
                m_log = math.log(m) - 0.5 * s_log**2
                return LognormalDistribution(mean_log=m_log, std_log=s_log)
            else:
                raise ValueError("Lognormal requires ('mean_log', 'std_log') or ('mean', 'std_dev').")
        elif dist_type == DistributionType.UNIFORM:
            return UniformDistribution(min_val=params["min_val"], max_val=params["max_val"])
        elif dist_type == DistributionType.TRIANGULAR:
            return TriangularDistribution(
                min_val=params["min_val"],
                mode_val=params["mode_val"],
                max_val=params["max_val"],
            )
        elif dist_type == DistributionType.EXPONENTIAL:
            return ExponentialDistribution(scale=params.get("scale"), rate=params.get("rate"))
        elif dist_type == DistributionType.EMPIRICAL_DISCRETE:
            return EmpiricalDiscreteDistribution(
                values=params["values"],
                probabilities=params["probabilities"],
            )
        elif dist_type == DistributionType.EMPIRICAL_CONTINUOUS:
            return EmpiricalContinuousDistribution(
                sample_values=params.get("values", params.get("sample_values", [])),
                cumulative_probabilities=params.get("cumulative_probabilities"),
            )
        else:
            raise ValueError(f"Unsupported distribution type: {dist_type}")
    except KeyError as e:
        raise ValueError(f"Missing required parameter '{e.args[0]}' for {dist_type}") from e
