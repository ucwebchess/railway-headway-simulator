"""Stochastic seed management, correlation groups, and parameter sampling engine.

Milestone P11 — Stochastic Simulation, Monte Carlo & Railway Operational Reliability (RHS-P11-001).
Covers:
- P11-RNG-001 to P11-RNG-006: Master seed and replication stream management via NumPy SeedSequence
- P11-CRN-001 to P11-CRN-004: Common random numbers (CRN) for paired scenario comparisons
- P11-COR-001 to P11-COR-006: Correlated stochastic variables via Gaussian copula / NORTA
- P11-SCOPE-001 to P11-SCOPE-003: Deterministic sampling scopes (PER_REPLICATION, PER_TRAIN, PER_STATION_STOP, etc.)
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import numpy as np

from headway.analysis.distributions import ProbabilityDistribution, create_distribution
from headway.analysis.random_variables import (
    DisruptionType,
    OperationalDisruption,
    SamplingScope,
    StochasticVariableDefinition,
    TargetObjectType,
)


class MasterSeedManager:
    """P11-RNG: Deterministic seed and independent stream generation for Monte Carlo replications."""

    def __init__(self, master_seed: Optional[int] = None) -> None:
        if master_seed is not None and master_seed < 0:
            raise ValueError(f"Master seed must be non-negative (got {master_seed}).")
        self.master_seed: int = master_seed if master_seed is not None else 42
        self._seed_sequence = np.random.SeedSequence(self.master_seed)
        self._spawned_streams: Dict[int, np.random.Generator] = {}

    def get_replication_generator(self, replication_index: int, total_replications: int = 100) -> np.random.Generator:
        """P11-RNG-003 & 004: Returns an independent, reproducible generator for a specific replication index."""
        if replication_index < 0:
            raise ValueError(f"Replication index must be non-negative (got {replication_index}).")
        if replication_index not in self._spawned_streams:
            # Deterministically derive child seed sequence for replication
            child_seq = self._seed_sequence.spawn(replication_index + 1)[-1]
            self._spawned_streams[replication_index] = np.random.default_rng(child_seq)
        return self._spawned_streams[replication_index]


class CorrelationGroup:
    """P11-COR: Correlated stochastic variables preserving marginal distributions via Gaussian copula."""

    def __init__(
        self,
        group_id: str,
        variable_ids: List[str],
        correlation_matrix: Sequence[Sequence[float]],
    ) -> None:
        if not variable_ids or len(variable_ids) < 2:
            raise ValueError(f"Correlation group '{group_id}' requires at least two variables.")

        n = len(variable_ids)
        r = np.asarray(correlation_matrix, dtype=float)

        if r.shape != (n, n):
            raise ValueError(f"Correlation matrix shape {r.shape} must match variable count ({n}, {n}).")
        if not np.allclose(r, r.T, atol=1e-5):
            raise ValueError(f"Correlation matrix for group '{group_id}' must be symmetric.")
        if not np.allclose(np.diag(r), 1.0, atol=1e-5):
            raise ValueError(f"Diagonal elements of correlation matrix must be exactly 1.0.")

        # Check positive semi-definite
        eigenvalues = np.linalg.eigvalsh(r)
        if np.any(eigenvalues < -1e-6):
            raise ValueError(
                f"Correlation matrix for group '{group_id}' is not positive semi-definite (min eigenvalue {np.min(eigenvalues)})."
            )

        # Cholesky decomposition with slight regularization if needed
        regularized = r + np.eye(n) * max(0.0, -np.min(eigenvalues) + 1e-8) if np.min(eigenvalues) < 1e-8 else r
        try:
            self.cholesky_l = np.linalg.cholesky(regularized)
        except np.linalg.LinAlgError as e:
            raise ValueError(f"Cholesky decomposition failed for correlation matrix '{group_id}': {e}")

        self.group_id = group_id
        self.variable_ids = list(variable_ids)
        self.correlation_matrix = r

    def sample_correlated_uniforms(self, rng: np.random.Generator) -> Dict[str, float]:
        """Generate correlated uniform random variables U_i in (0, 1) using Gaussian copula."""
        n = len(self.variable_ids)
        z_iid = rng.standard_normal(size=n)
        z_corr = self.cholesky_l @ z_iid

        # Standard normal CDF: Phi(Z)
        import scipy.special
        u_corr = 0.5 * (1.0 + scipy.special.erf(z_corr / math.sqrt(2.0)))
        # Clip to avoid exact 0.0 or 1.0
        u_corr = np.clip(u_corr, 1e-8, 1.0 - 1e-8)

        return {var_id: float(u_corr[i]) for i, var_id in enumerate(self.variable_ids)}


class CommonRandomNumbersManager:
    """P11-CRN: Manages shared pseudo-random numbers across compared scenarios."""

    def __init__(self, master_seed: int = 12345) -> None:
        self.master_seed = master_seed
        self._shared_cache: Dict[Tuple[int, str], float] = {}

    def get_or_draw_uniform(
        self,
        replication_index: int,
        key: str,
        rng: np.random.Generator,
    ) -> float:
        """P11-CRN-002: Returns an identical random draw for the same replication and key across scenarios."""
        cache_key = (replication_index, key)
        if cache_key not in self._shared_cache:
            self._shared_cache[cache_key] = float(rng.uniform(0.0, 1.0))
        return self._shared_cache[cache_key]


class StochasticParameterSampler:
    """Samples defined stochastic variables and handles scope caching."""

    def __init__(
        self,
        variables: Sequence[StochasticVariableDefinition],
        correlation_groups: Optional[Sequence[CorrelationGroup]] = None,
        use_common_random_numbers: bool = False,
        crn_manager: Optional[CommonRandomNumbersManager] = None,
    ) -> None:
        self.variables = {v.variable_id: v for v in variables if v.enabled}
        self.distributions: Dict[str, ProbabilityDistribution] = {}
        for var_id, var in self.variables.items():
            self.distributions[var_id] = create_distribution(var.distribution_type, var.distribution_parameters)

        self.correlation_groups = {g.group_id: g for g in (correlation_groups or [])}
        self.use_crn = use_common_random_numbers
        self.crn_manager = crn_manager or CommonRandomNumbersManager()

        # Cache for sampled values per replication, train, stop, etc.
        self._sampled_cache: Dict[Tuple[str, str], float] = {}

    def reset_for_replication(self) -> None:
        """Reset internal caches for a fresh independent replication."""
        self._sampled_cache.clear()

    def sample_variable(
        self,
        variable_id: str,
        scope_entity_id: str,
        rng: np.random.Generator,
        replication_index: int = 0,
    ) -> float:
        """Sample a variable value respecting scope and clamping limits."""
        var = self.variables.get(variable_id)
        if not var:
            raise KeyError(f"Stochastic variable '{variable_id}' not found or disabled.")

        cache_key = (variable_id, scope_entity_id)
        if cache_key in self._sampled_cache:
            return self._sampled_cache[cache_key]

        dist = self.distributions[variable_id]

        # Check if variable is part of a correlation group
        if var.correlation_group and var.correlation_group in self.correlation_groups:
            cgroup = self.correlation_groups[var.correlation_group]
            u_dict = cgroup.sample_correlated_uniforms(rng)
            for vid, u_val in u_dict.items():
                if vid in self.distributions and vid in self.variables:
                    sampled_raw = float(self.distributions[vid].ppf(u_val))
                    clamped_val = self.variables[vid].clamp(sampled_raw)
                    self._sampled_cache[(vid, scope_entity_id)] = clamped_val
            return self._sampled_cache[cache_key]

        # Common random numbers check
        if self.use_crn:
            crn_key = f"{var.target_object_type.value}:{var.target_object_id or 'GLOBAL'}:{var.variable_id}:{scope_entity_id}"
            u = self.crn_manager.get_or_draw_uniform(replication_index, crn_key, rng)
            val = float(dist.ppf(u))
        else:
            val = float(dist.sample(rng))

        clamped = var.clamp(val)
        self._sampled_cache[cache_key] = clamped
        return clamped
