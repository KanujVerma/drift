"""Stage 1 paired stationary bootstrap and uncertainty implementation.

Implements locked inferential protocol:
- 10,000 replicates, seed 575, two-sided 95% percentile intervals.
- Paired session indices for B, R, and attributable operating costs.
- Fixed-order RNG draw and reproducible stream digest.
- Linear interpolation at position 9999 * p for p in (0.025, 0.975).
- 21, 42, 63 mean-block sensitivities.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.common import FrozenModel, SHA256Hash
from drift.serialization.canonical import canonical_json, content_hash


def generate_stationary_bootstrap_indices(
    *,
    n: int,
    mean_block_length: float | int,
    replicate_count: int = 10000,
    seed: int = 575,
) -> tuple[list[list[int]], str]:
    """Generates ordered paired bootstrap indices using locked PRNG semantics."""
    if n <= 0:
        raise ValueError("SAMPLE_SIZE_MUST_BE_POSITIVE")
    if mean_block_length < 1:
        raise ValueError("MEAN_BLOCK_LENGTH_MUST_BE_AT_LEAST_ONE")

    rng = random.Random(seed)
    prob_switch = 1.0 / float(mean_block_length)
    replicates: list[list[int]] = []

    hasher = hashlib.sha256()

    for _ in range(replicate_count):
        first = rng.randrange(n)
        indices = [first]
        hasher.update(first.to_bytes(4, byteorder="big", signed=False))
        for _ in range(n - 1):
            draw = rng.random()
            if draw < prob_switch:
                idx = rng.randrange(n)
            else:
                idx = (indices[-1] + 1) % n
            indices.append(idx)
            hasher.update(idx.to_bytes(4, byteorder="big", signed=False))
        replicates.append(indices)

    digest = hasher.hexdigest()
    return replicates, digest


def compute_quantile_linear_interpolation(
    sorted_values: Sequence[Decimal],
    p: float | Decimal,
) -> Decimal:
    """Computes quantile by exact linear interpolation at position 9999 * p."""
    if len(sorted_values) != 10000:
        raise ValueError("QUANTILE_REQUIRES_EXACTLY_10000_SORTED_VALUES")

    p_dec = Decimal(str(p))
    pos = Decimal("9999") * p_dec
    low_idx = int(pos)
    frac = pos - Decimal(low_idx)

    if low_idx >= 9999:
        return sorted_values[9999]

    low_val = sorted_values[low_idx]
    high_val = sorted_values[low_idx + 1]
    return low_val + frac * (high_val - low_val)


class SensitivityIntervalV1(FrozenModel):
    mean_block: int
    lower: Decimal
    upper: Decimal


class PairedUncertaintyArtifactV1(FrozenModel):
    schema_version: Literal["drift-stage1-uncertainty/1"] = "drift-stage1-uncertainty/1"
    mean_block_length: int | None
    primary_nav_diff_point: Decimal
    primary_economic_point: Decimal
    primary_nav_diff_interval: tuple[Decimal, Decimal] | None = None
    primary_economic_interval: tuple[Decimal, Decimal] | None = None
    sensitivities: tuple[SensitivityIntervalV1, ...] = ()
    reproducible_digest: SHA256Hash
    artifact_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        body = self.model_dump(mode="python", exclude={"artifact_hash"})
        if self.artifact_hash != content_hash(body):
            raise ValueError("UNCERTAINTY_ARTIFACT_HASH_MISMATCH")
        return self


def compute_paired_uncertainty_artifact(
    *,
    b_returns: Sequence[Decimal],
    r_returns: Sequence[Decimal],
    initial_capital: Decimal = Decimal("10000"),
    incremental_operating_costs: Decimal = Decimal("0"),
    mean_block_length: int | None = None,
    seed: int = 575,
) -> PairedUncertaintyArtifactV1:
    n = len(b_returns)
    if n == 0 or len(r_returns) != n:
        raise ValueError("RETURNS_LENGTH_MISMATCH_OR_EMPTY")

    # Point estimates
    # Compound B
    b_compound = Decimal("1")
    for r in b_returns:
        b_compound *= Decimal("1") + r
    r_b = b_compound - Decimal("1")

    # Compound R
    r_compound = Decimal("1")
    for r in r_returns:
        r_compound *= Decimal("1") + r
    r_r = r_compound - Decimal("1")

    delta_nav_point = r_b - r_r
    economic_point = (initial_capital * delta_nav_point) - incremental_operating_costs

    primary_nav_interval: tuple[Decimal, Decimal] | None = None
    primary_econ_interval: tuple[Decimal, Decimal] | None = None

    if mean_block_length is not None and mean_block_length >= 1:
        reps, digest = generate_stationary_bootstrap_indices(
            n=n, mean_block_length=mean_block_length, seed=seed
        )
        nav_diffs: list[Decimal] = []
        econ_diffs: list[Decimal] = []
        for rep in reps:
            b_rep_prod = Decimal("1")
            r_rep_prod = Decimal("1")
            for idx in rep:
                b_rep_prod *= Decimal("1") + b_returns[idx]
                r_rep_prod *= Decimal("1") + r_returns[idx]
            d_nav = (b_rep_prod - Decimal("1")) - (r_rep_prod - Decimal("1"))
            nav_diffs.append(d_nav)
            e_val = (initial_capital * d_nav) - incremental_operating_costs
            econ_diffs.append(e_val)

        nav_diffs.sort()
        econ_diffs.sort()

        primary_nav_interval = (
            compute_quantile_linear_interpolation(nav_diffs, 0.025),
            compute_quantile_linear_interpolation(nav_diffs, 0.975),
        )
        primary_econ_interval = (
            compute_quantile_linear_interpolation(econ_diffs, 0.025),
            compute_quantile_linear_interpolation(econ_diffs, 0.975),
        )
    else:
        # Fallback digest when primary block estimation is undefined
        digest = "0" * 64

    # Calculate 21, 42, 63 sensitivities
    sensitivities: list[SensitivityIntervalV1] = []
    for sens_b in (21, 42, 63):
        reps, _ = generate_stationary_bootstrap_indices(
            n=n, mean_block_length=sens_b, seed=seed
        )
        econ_sens: list[Decimal] = []
        for rep in reps:
            b_rep_prod = Decimal("1")
            r_rep_prod = Decimal("1")
            for idx in rep:
                b_rep_prod *= Decimal("1") + b_returns[idx]
                r_rep_prod *= Decimal("1") + r_returns[idx]
            d_nav = (b_rep_prod - Decimal("1")) - (r_rep_prod - Decimal("1"))
            e_val = (initial_capital * d_nav) - incremental_operating_costs
            econ_sens.append(e_val)
        econ_sens.sort()
        sensitivities.append(
            SensitivityIntervalV1(
                mean_block=sens_b,
                lower=compute_quantile_linear_interpolation(econ_sens, 0.025),
                upper=compute_quantile_linear_interpolation(econ_sens, 0.975),
            )
        )

    body = {
        "schema_version": "drift-stage1-uncertainty/1",
        "mean_block_length": mean_block_length,
        "primary_nav_diff_point": delta_nav_point,
        "primary_economic_point": economic_point,
        "primary_nav_diff_interval": primary_nav_interval,
        "primary_economic_interval": primary_econ_interval,
        "sensitivities": tuple(sensitivities),
        "reproducible_digest": digest,
    }
    h = content_hash(body)
    return PairedUncertaintyArtifactV1.model_validate_json(
        canonical_json(body | {"artifact_hash": h})
    )
