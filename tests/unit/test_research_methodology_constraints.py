"""Unit tests for research methodology constraints (Phase 4)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from drift.agent.context import (
    DEFAULT_STRATEGY_TYPES,
)
from drift.agent.validator import ProposalValidator
from drift.domain.research_agent import (
    ProposalValidationStatus,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
)
from drift.domain.research_memory import (
    build_parameter_search_space,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.evaluator_adapter import (
    STRATEGY_REGISTRY,
    StrategyParameterValidationError,
    UnknownStrategyTypeError,
    resolve_and_instantiate_strategy,
)
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import deterministic_memory_uuid7

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
HYPOTHESIS_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
EXPERIMENT_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")


def test_default_strategy_types_match_m3_canonical_baselines() -> None:
    """DEFAULT_STRATEGY_TYPES contains canonical M3 baseline names."""
    expected = (
        "b0_cash",
        "b1_single_buy_and_hold",
        "b2_equal_weight_buy_and_hold",
        "b3_monthly_equal_weight_rebalance",
        "b4_momentum",
        "b5_low_volatility",
    )
    assert DEFAULT_STRATEGY_TYPES == expected


def test_incompatible_legacy_aliases_rejected() -> None:
    """Incompatible legacy aliases must be rejected with UnknownStrategyTypeError."""
    incompatible = (
        "b0_passive_equal_weight",
        "b1_market_cap_weight",
        "b2_fixed_universe_rebalance",
        "b3_mean_reversion",
    )
    for name in incompatible:
        assert name not in STRATEGY_REGISTRY
        with pytest.raises(UnknownStrategyTypeError):
            resolve_and_instantiate_strategy(name)


def test_strategy_parameter_validation_allowlist_and_types() -> None:
    """Verify strict parameter allowlists and typing across M3 baselines."""
    # B0 rejects unknown params
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b0_cash", {"unknown_param": 123})

    # B1 requires target_security_id and rejects unknown params
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b1_single_buy_and_hold", {})
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy(
            "b1_single_buy_and_hold",
            {"target_security_id": "018f3a5b-6c7d-7890-8123-456789abcd01", "extra": 1},
        )

    # B2 rejects unknown params
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b2_equal_weight_buy_and_hold", {"unknown": 1})

    # B4 rejects bool, float, str for integer parameters
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b4_momentum", {"formation_sessions": True})
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b4_momentum", {"formation_sessions": 12.5})
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b4_momentum", {"formation_sessions": "252"})
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b4_momentum", {"unexpected_param": 10})

    # B5 rejects bool, float, str
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy(
            "b5_low_volatility", {"lookback_returns": False}
        )
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy(
            "b5_low_volatility", {"lookback_returns": 30.5}
        )
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy(
            "b5_low_volatility", {"lookback_returns": "60"}
        )
    with pytest.raises(StrategyParameterValidationError):
        resolve_and_instantiate_strategy("b5_low_volatility", {"unknown_param": 5})


def test_validator_rejects_hypothesis_experiment_strategy_mismatch(
    tmp_path: Path,
) -> None:
    """Validator rejects proposal when experiment strategy does not match hypothesis."""
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)
    validator = ProposalValidator(archive)

    hyp = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID,
        title="Momentum Hypothesis",
        economic_rationale="Trend following returns",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.00"),
        created_at=TIMESTAMP,
    )
    # Experiment specifies b0_cash instead of b4_momentum
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID,
        hypothesis_proposal_id=HYPOTHESIS_ID,
        strategy_type="b0_cash",
        proposed_parameters={},
        universe_id="sp500",
        rebalance_frequency="daily",
        created_at=TIMESTAMP,
    )

    res = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )
    assert res.is_accepted is False
    assert res.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert any("does not match" in r for r in res.rejection_reasons)


def test_validator_rejects_exhausted_parameter_search_space(tmp_path: Path) -> None:
    """Validator rejects proposals targeting a fully exhausted search space."""
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)

    space_id = deterministic_memory_uuid7("exhausted_space")
    exhausted_space = build_parameter_search_space(
        search_space_id=space_id,
        strategy_type="b4_momentum",
        dimension_names=("formation_sessions", "skip_sessions"),
        exhaustion_fraction=Decimal("1.0"),
        created_at=TIMESTAMP,
    )

    validator = ProposalValidator(
        archive,
        search_spaces={"b4_momentum": exhausted_space},
    )

    hyp = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID,
        title="Momentum Hypothesis",
        economic_rationale="Trend following returns",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.00"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID,
        hypothesis_proposal_id=HYPOTHESIS_ID,
        strategy_type="b4_momentum",
        proposed_parameters={"formation_sessions": 20, "skip_sessions": 5},
        universe_id="sp500",
        rebalance_frequency="daily",
        created_at=TIMESTAMP,
    )

    res = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )
    assert res.is_accepted is False
    assert res.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert any("fully exhausted" in r for r in res.rejection_reasons)


def test_validator_rejects_invalid_baseline_parameters(tmp_path: Path) -> None:
    """Validator rejects proposals with invalid baseline parameters upfront."""
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)
    validator = ProposalValidator(archive)

    # 1. B1 with non-UUID target_security_id
    hyp_b1 = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID,
        title="B1 Buy and Hold",
        economic_rationale="Equity premium",
        target_strategy_type="b1_single_buy_and_hold",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.00"),
        created_at=TIMESTAMP,
    )
    exp_b1 = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID,
        hypothesis_proposal_id=HYPOTHESIS_ID,
        strategy_type="b1_single_buy_and_hold",
        proposed_parameters={"target_security_id": "not-a-valid-uuid"},
        universe_id="sp500",
        rebalance_frequency="daily",
        created_at=TIMESTAMP,
    )
    res_b1 = validator.validate_proposal(
        hypothesis=hyp_b1,
        experiment=exp_b1,
        as_of_time=TIMESTAMP,
    )
    assert res_b1.is_accepted is False
    assert res_b1.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert any(
        "Invalid target_security_id UUID string" in r for r in res_b1.rejection_reasons
    )

    # 2. B4 with negative formation_sessions
    hyp_b4 = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID,
        title="B4 Momentum",
        economic_rationale="Trend following",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.00"),
        created_at=TIMESTAMP,
    )
    exp_b4 = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID,
        hypothesis_proposal_id=HYPOTHESIS_ID,
        strategy_type="b4_momentum",
        proposed_parameters={"formation_sessions": -10, "skip_sessions": 5},
        universe_id="sp500",
        rebalance_frequency="daily",
        created_at=TIMESTAMP,
    )
    res_b4 = validator.validate_proposal(
        hypothesis=hyp_b4,
        experiment=exp_b4,
        as_of_time=TIMESTAMP,
    )
    assert res_b4.is_accepted is False
    assert res_b4.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert any("must be positive integer" in r for r in res_b4.rejection_reasons)

    # 3. B5 with non-integer lookback
    hyp_b5 = build_hypothesis_proposal(
        proposal_id=HYPOTHESIS_ID,
        title="B5 Low Vol",
        economic_rationale="Low beta anomaly",
        target_strategy_type="b5_low_volatility",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.00"),
        created_at=TIMESTAMP,
    )
    exp_b5 = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID,
        hypothesis_proposal_id=HYPOTHESIS_ID,
        strategy_type="b5_low_volatility",
        proposed_parameters={"lookback_returns": "invalid"},
        universe_id="sp500",
        rebalance_frequency="daily",
        created_at=TIMESTAMP,
    )
    res_b5 = validator.validate_proposal(
        hypothesis=hyp_b5,
        experiment=exp_b5,
        as_of_time=TIMESTAMP,
    )
    assert res_b5.is_accepted is False
    assert res_b5.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert any("must be positive integer" in r for r in res_b5.rejection_reasons)
