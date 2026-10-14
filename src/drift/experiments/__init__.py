"""Parallel research portfolios and cohort evaluation experiments (Phase 3)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drift.experiments.parallel_portfolios import (
        CohortPortfolioResult,
        PortfolioCohortHarness,
        build_offline_cohort_bundle,
        build_offline_cohort_evidence,
        compute_daily_returns_correlation,
    )

__all__ = [
    "CohortPortfolioResult",
    "PortfolioCohortHarness",
    "build_offline_cohort_bundle",
    "build_offline_cohort_evidence",
    "compute_daily_returns_correlation",
]


def __getattr__(name: str) -> object:
    if name in __all__:
        import drift.experiments.parallel_portfolios as pp

        return getattr(pp, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
