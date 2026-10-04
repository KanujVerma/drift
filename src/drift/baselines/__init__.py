"""Canonical M3 deterministic reference baseline strategies (Issue 166).

Exporting the six standard passive, factor, and mechanical baseline strategies:
- B0: Cash (Null Hypothesis)
- B1: Per-Security Buy-and-Hold
- B2: Equal-Weight Cohort Buy-and-Hold
- B3: Monthly Equal-Weight Rebalance
- B4: 12-1 Momentum
- B5: 60-Session Low Volatility
"""

from drift.baselines.b0_cash import B0CashStrategy
from drift.baselines.b1_single_buy_and_hold import B1SingleBuyAndHoldStrategy
from drift.baselines.b2_equal_weight_buy_and_hold import (
    B2EqualWeightBuyAndHoldStrategy,
)
from drift.baselines.b3_monthly_equal_weight_rebalance import (
    B3MonthlyEqualWeightRebalanceStrategy,
)
from drift.baselines.b4_momentum import B4MomentumStrategy
from drift.baselines.b5_low_volatility import B5LowVolatilityStrategy
from drift.baselines.runner import (
    BaselineReferenceStrategy,
    BaselineSuiteResult,
    build_canonical_run_identity,
    build_canonical_specification,
    make_bundle_dataset_reference,
    run_baseline_suite,
    run_canonical_baseline,
)

__all__ = [
    "B0CashStrategy",
    "B1SingleBuyAndHoldStrategy",
    "B2EqualWeightBuyAndHoldStrategy",
    "B3MonthlyEqualWeightRebalanceStrategy",
    "B4MomentumStrategy",
    "B5LowVolatilityStrategy",
    "BaselineReferenceStrategy",
    "BaselineSuiteResult",
    "build_canonical_run_identity",
    "build_canonical_specification",
    "make_bundle_dataset_reference",
    "run_baseline_suite",
    "run_canonical_baseline",
]
