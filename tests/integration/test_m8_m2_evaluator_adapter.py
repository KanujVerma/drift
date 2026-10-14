"""Integration tests for M2 trial evaluator adapter (Phase 2)."""

import sys
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

_UNIT_PATH = Path(__file__).resolve().parents[1] / "unit"
_ADV_PATH = Path(__file__).resolve().parents[1] / "adversarial"
if str(_UNIT_PATH) not in sys.path:
    sys.path.insert(0, str(_UNIT_PATH))
if str(_ADV_PATH) not in sys.path:
    sys.path.insert(0, str(_ADV_PATH))

from test_evaluator_engine import (  # noqa: E402
    DAY_2,
    DAYS,
    SEC_A,
    _accounting_view,
    _bundle,
    _engine,
)
from test_m8_research_loop_adversarial import (  # noqa: E402
    TIMESTAMP,
    _build_test_env,
)

from drift.domain.research_agent import (  # noqa: E402
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
)
from drift.domain.research_loop import (  # noqa: E402
    IterationStatus,
    build_research_loop_config,
)
from drift.domain.research_memory import (  # noqa: E402
    FailureCategory,
    TrialOutcome,
)
from drift.loop.diagnosis import diagnose_trial_outcome  # noqa: E402
from drift.loop.evaluator_adapter import (  # noqa: E402
    DeterministicMockTrialEvaluator,
    M2TrialEvaluatorAdapter,
    MockEvaluatorProductionError,
    StrategyParameterValidationError,
    UnknownStrategyTypeError,
)
from drift.loop.runner import ResearchLoopRunner  # noqa: E402


def _make_proposals(
    strategy_type: str,
    parameters: dict[str, object] | None = None,
) -> tuple[object, object]:
    """Helper to build matched hypothesis and experiment proposals."""
    hyp = build_hypothesis_proposal(
        proposal_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd01"),
        title="Test Hypothesis",
        economic_rationale="Economic rationale for test hypothesis.",
        target_strategy_type=strategy_type,
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.50"),
        max_turnover_limit=Decimal("10.0"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd03"),
        hypothesis_proposal_id=hyp.proposal_id,
        strategy_type=strategy_type,
        universe_id="drift.universe.sp500",
        rebalance_frequency="daily",
        proposed_parameters=parameters or {},
        created_at=TIMESTAMP,
    )
    return hyp, exp


def test_m2_adapter_b0_cash_evaluation() -> None:
    """B0 Cash strategy evaluates cleanly and produces genuine empirical metrics."""
    engine = _engine()
    adapter = M2TrialEvaluatorAdapter(engine=engine)
    _, exp = _make_proposals("b0_cash")

    metrics = adapter.evaluate_experiment(exp)  # type: ignore[arg-type]

    assert metrics["classification"] == "complete"
    assert metrics["is_mock"] is False
    assert metrics["is_synthetic"] is False
    assert metrics["annualized_sharpe"] == Decimal("0")
    assert metrics["max_drawdown"] == Decimal("0")
    assert metrics["annualized_turnover"] == Decimal("0")
    assert metrics["is_pnl_complete"] is True
    assert len(metrics["session_returns"]) == len(engine.bundle.session_clock.sessions)
    assert all(r == Decimal("0") for r in metrics["session_returns"])
    assert metrics["bundle_hash"] == engine.bundle.bundle_hash
    assert len(metrics["run_identity_hash"]) == 64


def test_m2_adapter_b1_single_buy_and_hold_evaluation() -> None:
    """B1 Single Buy-and-Hold produces empirical Sharpe, returns, and drawdown."""
    engine = _engine()
    adapter = M2TrialEvaluatorAdapter(engine=engine)
    _, exp = _make_proposals(
        "b1_single_buy_and_hold",
        {"target_security_id": str(SEC_A)},
    )

    metrics = adapter.evaluate_experiment(exp)  # type: ignore[arg-type]

    assert metrics["classification"] == "complete"
    assert metrics["is_mock"] is False
    assert metrics["is_synthetic"] is False
    assert isinstance(metrics["annualized_sharpe"], Decimal)
    assert isinstance(metrics["max_drawdown"], Decimal)
    assert metrics["is_pnl_complete"] is True
    assert len(metrics["session_returns"]) == len(engine.bundle.session_clock.sessions)
    assert metrics["net_profit_and_loss"] > Decimal("0")


def test_m2_adapter_b4_momentum_evaluation() -> None:
    """B4 Momentum baseline evaluates cleanly with parameter injection."""
    engine = _engine()
    adapter = M2TrialEvaluatorAdapter(engine=engine)
    _, exp = _make_proposals(
        "b4_momentum",
        {
            "formation_sessions": 1,
            "skip_sessions": 0,
            "min_eligible_count": 1,
        },
    )

    metrics = adapter.evaluate_experiment(exp)  # type: ignore[arg-type]

    assert metrics["classification"] == "complete"
    assert metrics["is_mock"] is False
    assert metrics["is_synthetic"] is False
    assert isinstance(metrics["annualized_sharpe"], Decimal)
    assert metrics["is_pnl_complete"] is True


def test_m2_adapter_unknown_strategy_type_raises_cleanly() -> None:
    """Unrecognized strategy type raises UnknownStrategyTypeError without executing."""
    engine = _engine()
    adapter = M2TrialEvaluatorAdapter(engine=engine)
    _, exp = _make_proposals("unregistered_arbitrary_strategy_alpha")

    with pytest.raises(
        UnknownStrategyTypeError, match="Unknown or unsupported strategy"
    ):
        adapter.evaluate_experiment(exp)  # type: ignore[arg-type]


def test_m2_adapter_invalid_parameters_raise_validation_error() -> None:
    """Invalid parameter values for baselines raise StrategyParameterValidationError."""
    engine = _engine()
    adapter = M2TrialEvaluatorAdapter(engine=engine)

    # B1 with invalid UUID string
    _, exp_b1_bad_uuid = _make_proposals(
        "b1_single_buy_and_hold",
        {"target_security_id": "not-a-valid-uuid"},
    )
    with pytest.raises(
        StrategyParameterValidationError, match="Invalid target_security_id"
    ):
        adapter.evaluate_experiment(exp_b1_bad_uuid)  # type: ignore[arg-type]

    # B4 with non-integer parameter
    _, exp_b4_bad_int = _make_proposals(
        "b4_momentum",
        {"formation_sessions": "not_an_integer"},
    )
    with pytest.raises(StrategyParameterValidationError, match="must be integers"):
        adapter.evaluate_experiment(exp_b4_bad_int)  # type: ignore[arg-type]

    # B4 with negative parameter
    _, exp_b4_negative = _make_proposals(
        "b4_momentum",
        {"formation_sessions": -5},
    )
    with pytest.raises(StrategyParameterValidationError, match="must be positive"):
        adapter.evaluate_experiment(exp_b4_negative)  # type: ignore[arg-type]

    # B5 with non-integer parameter
    _, exp_b5_bad = _make_proposals(
        "b5_low_volatility",
        {"lookback_returns": "invalid"},
    )
    with pytest.raises(StrategyParameterValidationError, match="must be integers"):
        adapter.evaluate_experiment(exp_b5_bad)  # type: ignore[arg-type]


def test_m2_adapter_indeterminate_evaluation_propagates_without_fabrication() -> None:
    """Indeterminate evaluation fails closed without fabricating metrics."""
    # Build engine missing Day 2 open price to trigger indeterminate halt
    views = tuple(_accounting_view(SEC_A, day) for day in DAYS if day != DAY_2)
    engine = _engine(bundle=_bundle(accounting_views=views))
    adapter = M2TrialEvaluatorAdapter(engine=engine)

    hyp, exp = _make_proposals(
        "b1_single_buy_and_hold",
        {"target_security_id": str(SEC_A)},
    )

    metrics = adapter.evaluate_experiment(exp)  # type: ignore[arg-type]

    assert metrics["classification"] == "indeterminate"
    assert metrics["is_indeterminate"] is True
    assert metrics["annualized_sharpe"] is None
    assert metrics["max_drawdown"] is None
    assert metrics["annualized_turnover"] is None
    assert metrics["is_pnl_complete"] is False

    diag = diagnose_trial_outcome(
        hypothesis=hyp,  # type: ignore[arg-type]
        experiment=exp,  # type: ignore[arg-type]
        metrics=metrics,
    )
    assert diag.outcome == TrialOutcome.INVALIDATED
    assert diag.failure_category == FailureCategory.DATA_DEFECT
    assert "indeterminate" in diag.root_cause_summary


def test_mock_evaluator_cannot_be_used_in_production_mode(tmp_path: Path) -> None:
    """Mock evaluator is rejected with error in production mode."""
    # 1. DeterministicMockTrialEvaluator rejects mock=False directly
    with pytest.raises(
        MockEvaluatorProductionError, match="cannot be used in production mode"
    ):
        DeterministicMockTrialEvaluator(mock=False)

    # 2. ResearchLoopRunner rejects mock evaluator when production_mode=True
    (
        ledger,
        recorder,
        archive,
        synthesizer,
        validator,
        agent,
        loop_rec,
        _,
    ) = _build_test_env(tmp_path)

    config = build_research_loop_config(
        loop_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd99"),
        target_strategy_type="b0_cash",
        created_at=TIMESTAMP,
    )

    with pytest.raises(
        MockEvaluatorProductionError, match="cannot be used in production mode"
    ):
        ResearchLoopRunner(
            config=config,
            synthesizer=synthesizer,
            agent=agent,
            validator=validator,
            evaluator=DeterministicMockTrialEvaluator(),
            recorder=recorder,
            archive=archive,
            loop_recorder=loop_rec,
            production_mode=True,
        )


def test_genuine_adapter_end_to_end_in_production_mode(tmp_path: Path) -> None:
    """ResearchLoopRunner runs end-to-end with genuine M2 adapter in production mode."""
    (
        ledger,
        recorder,
        archive,
        synthesizer,
        validator,
        agent,
        loop_rec,
        loop_arc,
    ) = _build_test_env(tmp_path)

    engine = _engine()
    genuine_evaluator = M2TrialEvaluatorAdapter(engine=engine)

    config = build_research_loop_config(
        loop_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd99"),
        target_strategy_type="b0_cash",
        max_iterations=1,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synthesizer,
        agent=agent,
        validator=validator,
        evaluator=genuine_evaluator,
        recorder=recorder,
        archive=archive,
        loop_recorder=loop_rec,
        production_mode=True,
    )

    summary, iterations = runner.run(start_time=TIMESTAMP)

    assert summary.total_iterations == 1
    assert len(iterations) == 1
    assert all(it.status == IterationStatus.EVALUATION_COMPLETED for it in iterations)
    assert all(it.annualized_sharpe is not None for it in iterations)

    trials = archive.get_trials()
    assert len(trials) == 1
    for t in trials:
        assert isinstance(t.headline_metrics, Mapping)
        assert t.headline_metrics.get("is_mock") is False
        assert t.headline_metrics.get("is_synthetic") is False
        assert t.headline_metrics.get("classification") == "complete"
