"""Unit tests for trial diagnosis and evaluator adapter (M8-2, Issue 233)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
)
from drift.domain.research_memory import (
    FailureCategory,
    FailurePostmortemV1,
    TrialOutcome,
)
from drift.loop.diagnosis import (
    build_automatic_failure_postmortem,
    diagnose_trial_outcome,
)
from drift.loop.evaluator_adapter import (
    DeterministicMockTrialEvaluator,
    TrialEvaluatorProtocol,
)

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
PROPOSAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
RUN_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")


def _sample_hypothesis() -> HypothesisProposalV1:
    return build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Momentum Trend Hypothesis",
        economic_rationale="Trend following captures drift anomaly.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.60"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        created_at=TIMESTAMP,
    )


def _sample_experiment() -> ExperimentSpecificationProposalV1:
    return build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_days": 60, "rebalance_freq": "weekly"},
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )


def test_diagnose_trial_outcome_superior() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("1.25"),
        "max_drawdown": Decimal("0.10"),
        "annualized_turnover": Decimal("3.2"),
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    assert diag.outcome == TrialOutcome.SUPERIOR
    assert diag.failure_category is None
    assert len(diag.breached_criteria) == 0
    assert len(diag.forbidden_variations) == 0


def test_diagnose_trial_outcome_neutral() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("0.70"),
        "max_drawdown": Decimal("0.15"),
        "annualized_turnover": Decimal("4.0"),
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    assert diag.outcome == TrialOutcome.NEUTRAL
    assert diag.failure_category is None
    assert len(diag.breached_criteria) == 0


def test_diagnose_trial_outcome_negative_alpha() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("-0.20"),
        "max_drawdown": Decimal("0.15"),
        "annualized_turnover": Decimal("3.0"),
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    assert diag.outcome == TrialOutcome.FAILED
    assert diag.failure_category == FailureCategory.NEGATIVE_ALPHA
    assert any("annualized_sharpe" in b for b in diag.breached_criteria)
    assert "lookback_days=60" in diag.forbidden_variations


def test_diagnose_trial_outcome_calibration_failure() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("0.35"),  # positive but below 0.60
        "max_drawdown": Decimal("0.15"),
        "annualized_turnover": Decimal("3.0"),
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    assert diag.outcome == TrialOutcome.FAILED
    assert diag.failure_category == FailureCategory.CALIBRATION_FAILURE
    assert any("annualized_sharpe" in b for b in diag.breached_criteria)


def test_diagnose_trial_outcome_drawdown_breach() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("0.80"),
        "max_drawdown": Decimal("0.32"),  # exceeds 0.20 limit
        "annualized_turnover": Decimal("3.0"),
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    assert diag.outcome == TrialOutcome.FAILED
    assert diag.failure_category == FailureCategory.DRAWDOWN_BREACH
    assert any("max_drawdown" in b for b in diag.breached_criteria)


def test_diagnose_trial_outcome_turnover_drag() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("0.80"),
        "max_drawdown": Decimal("0.15"),
        "annualized_turnover": Decimal("8.5"),  # exceeds 5.0 limit
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    assert diag.outcome == TrialOutcome.FAILED
    assert diag.failure_category == FailureCategory.TURNOVER_DRAG
    assert any("annualized_turnover" in b for b in diag.breached_criteria)


def test_build_automatic_failure_postmortem() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("0.20"),
        "max_drawdown": Decimal("0.35"),
        "annualized_turnover": Decimal("6.0"),
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    pm = build_automatic_failure_postmortem(
        diagnosis=diag,
        experiment_id=exp.experiment_proposal_id,
        run_id=RUN_ID_1,
        falsified_hypothesis_id=hyp.proposal_id,
        created_at=TIMESTAMP,
    )

    assert isinstance(pm, FailurePostmortemV1)
    assert pm.failure_category == FailureCategory.CALIBRATION_FAILURE
    assert pm.experiment_id == exp.experiment_proposal_id
    assert hyp.proposal_id in pm.falsified_hypotheses
    assert "lookback_days=60" in pm.forbidden_variations
    assert len(pm.postmortem_hash) == 64


def test_build_automatic_failure_postmortem_invalid_for_success() -> None:
    hyp = _sample_hypothesis()
    exp = _sample_experiment()
    metrics = {
        "annualized_sharpe": Decimal("1.20"),
        "max_drawdown": Decimal("0.10"),
        "annualized_turnover": Decimal("3.0"),
    }

    diag = diagnose_trial_outcome(hypothesis=hyp, experiment=exp, metrics=metrics)
    with pytest.raises(ValueError, match="non-failing trial diagnosis"):
        build_automatic_failure_postmortem(
            diagnosis=diag,
            experiment_id=exp.experiment_proposal_id,
            run_id=RUN_ID_1,
            created_at=TIMESTAMP,
        )


def test_deterministic_mock_trial_evaluator_protocol_and_overrides() -> None:
    evaluator = DeterministicMockTrialEvaluator()
    assert isinstance(evaluator, TrialEvaluatorProtocol)

    exp = _sample_experiment()
    res = evaluator.evaluate_experiment(exp)
    assert "annualized_sharpe" in res
    assert "max_drawdown" in res
    assert "annualized_turnover" in res

    # Overrides
    custom_metrics = {
        "annualized_sharpe": Decimal("2.10"),
        "max_drawdown": Decimal("0.05"),
        "annualized_turnover": Decimal("1.5"),
    }
    overridden_eval = DeterministicMockTrialEvaluator(
        metric_overrides={exp.parameters_hash: custom_metrics}
    )
    res_custom = overridden_eval.evaluate_experiment(exp)
    assert res_custom["annualized_sharpe"] == Decimal("2.10")
