"""Unit tests for composite scorecard generator harness and pipeline integration.

Covers M5-5 (Issue 197).
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    evaluation_run_identity_v2_hash,
)
from drift.domain.evaluator_results import (
    EvaluationSummaryMetricsV1,
    RealizedPnLCompletenessV1,
    SessionEquityPointV1,
)
from drift.domain.predictions import PredictionTargetType
from drift.domain.scorecards import (
    SCORECARD_EVENT_TYPE,
    ModelScorecardV1,
    MultipleTestingSummaryV1,
    PredictionScorecardV1,
    StrategyScorecardV1,
    build_prediction_scorecard,
)
from drift.domain.sessions import SessionKeyV1
from drift.ledger.sqlite import SQLiteLedger
from drift.scorecards.generator import (
    ScorecardGeneratorHarness,
    deterministic_scorecard_uuid7,
    generate_model_scorecard,
)
from drift.scorecards.predictive import (
    aggregate_information_coefficients,
    compute_calibration_summary,
)

CREATED_AT = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
SESSION_KEY_1 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 5)
)
SESSION_KEY_2 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 6)
)


def make_run_identity_v2(**overrides: Any) -> EvaluationRunIdentityV2:
    fields = {
        "strategy_hash": "a" * 64,
        "strategy_parameters_hash": "b" * 64,
        "protocol_hash": "c" * 64,
        "cost_model_hash": "d" * 64,
        "admission_hash": "e" * 64,
        "bundle_hash": "f" * 64,
        "evaluator_evidence_hash": "1" * 64,
        "code_version_hash": "2" * 64,
        "environment_closure_hash": "3" * 64,
        "run_identity_hash": "0" * 64,
        **overrides,
    }
    draft = EvaluationRunIdentityV2.model_construct(schema_version="2", **fields)
    expected = evaluation_run_identity_v2_hash(draft)
    return EvaluationRunIdentityV2.model_validate(
        {**fields, "run_identity_hash": expected}
    )


def make_sample_evaluation_metrics() -> EvaluationSummaryMetricsV1:
    points = (
        SessionEquityPointV1(
            session_index=0,
            session_key=SESSION_KEY_1,
            cash_balance=Decimal("101000.00"),
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("101000.00"),
        ),
        SessionEquityPointV1(
            session_index=1,
            session_key=SESSION_KEY_2,
            cash_balance=Decimal("102000.00"),
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("102000.00"),
        ),
    )
    return EvaluationSummaryMetricsV1(
        evaluated_session_count=2,
        initial_cash=Decimal("100000.00"),
        initial_net_asset_value=Decimal("100000.00"),
        ending_cash=Decimal("102000.00"),
        ending_net_asset_value=Decimal("102000.00"),
        net_profit_and_loss=Decimal("2000.00"),
        realized_gross_pnl=Decimal("2000.00"),
        realized_net_pnl=Decimal("2000.00"),
        cumulative_transaction_costs=Decimal("0.00"),
        gross_traded_notional=Decimal("0.00"),
        committed_fill_count=0,
        equity_series=points,
        realized_pnl_completeness=RealizedPnLCompletenessV1(is_complete=True),
    )


def make_sample_prediction_scorecard() -> PredictionScorecardV1:
    identity = make_run_identity_v2()
    ic = aggregate_information_coefficients(
        epoch_spearman_ics=[Decimal("0.05"), Decimal("0.08"), Decimal("0.03")],
        epoch_pearson_ics=[Decimal("0.04"), Decimal("0.07"), Decimal("0.02")],
    )
    cal = compute_calibration_summary(
        predictions=[Decimal("0.6"), Decimal("0.8")],
        ground_truth=[Decimal("1"), Decimal("1")],
    )
    return build_prediction_scorecard(
        scorecard_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd01"),
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        ic_summary=ic,
        calibration_summary=cal,
        total_predictions=10,
        resolved_predictions=10,
        indeterminate_predictions=0,
        delisted_predictions=0,
        created_at=CREATED_AT,
    )


def test_deterministic_scorecard_uuid7() -> None:
    u1 = deterministic_scorecard_uuid7("seed:alpha")
    u2 = deterministic_scorecard_uuid7("seed:alpha")
    u3 = deterministic_scorecard_uuid7("seed:beta")

    assert u1 == u2
    assert u1 != u3
    assert u1.version == 7


def test_generate_model_scorecard_rejects_empty() -> None:
    identity = make_run_identity_v2()
    with pytest.raises(
        ValueError,
        match="at least one sub-scorecard must be provided in ModelScorecardV1",
    ):
        generate_model_scorecard(
            run_identity=identity,
            lane="exploratory",
            created_at=CREATED_AT,
        )


def test_generate_model_scorecard_with_strategy_result() -> None:
    identity = make_run_identity_v2()
    metrics = make_sample_evaluation_metrics()

    card = generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=metrics,
        created_at=CREATED_AT,
    )
    assert card.strategy_scorecard is not None
    assert isinstance(card.strategy_scorecard, StrategyScorecardV1)
    assert card.strategy_scorecard.cumulative_return == Decimal("0.0200")
    assert card.strategy_scorecard.pnl_completeness.is_complete is True


def test_generate_model_scorecard_with_prediction_scorecard() -> None:
    identity = make_run_identity_v2()
    pred_sc = make_sample_prediction_scorecard()

    card = generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        prediction_scorecard=pred_sc,
        created_at=CREATED_AT,
    )
    assert card.prediction_scorecard is not None
    assert isinstance(card.prediction_scorecard, PredictionScorecardV1)
    assert card.prediction_scorecard.total_predictions == 10


def test_generate_model_scorecard_with_multiple_testing() -> None:
    identity = make_run_identity_v2()
    metrics = make_sample_evaluation_metrics()
    trials = [Decimal("0.5"), Decimal("1.2"), Decimal("1.85")]

    card = generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=metrics,
        trial_sharpe_ratios=trials,
        created_at=CREATED_AT,
    )
    assert card.multiple_testing is not None
    assert isinstance(card.multiple_testing, MultipleTestingSummaryV1)
    assert card.multiple_testing.trial_count == 3
    assert card.multiple_testing.sharpe_trial_variance > Decimal("0")


def test_generate_model_scorecard_full_composite() -> None:
    identity = make_run_identity_v2()
    metrics = make_sample_evaluation_metrics()
    pred_sc = make_sample_prediction_scorecard()
    trials = [Decimal("0.5"), Decimal("1.2"), Decimal("1.85")]

    card = generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=metrics,
        prediction_scorecard=pred_sc,
        trial_sharpe_ratios=trials,
        created_at=CREATED_AT,
    )
    assert card.strategy_scorecard is not None
    assert card.prediction_scorecard is not None
    assert card.multiple_testing is not None
    assert card.lane == "exploratory"


def test_scorecard_generator_harness_with_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "research_audit.sqlite3"
    ledger = SQLiteLedger(ledger_path)
    harness = ScorecardGeneratorHarness(ledger=ledger, deterministic=True)

    identity = make_run_identity_v2()
    metrics = make_sample_evaluation_metrics()

    card = harness.generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=metrics,
        created_at=CREATED_AT,
    )
    assert isinstance(card, ModelScorecardV1)

    # Verify event was sealed in ledger
    events = ledger.events()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == SCORECARD_EVENT_TYPE
    assert event.entity_type == "scorecard"
    assert event.entity_id == card.scorecard_id
    assert isinstance(event.payload, Mapping)
    assert event.payload["scorecard_hash"] == card.scorecard_hash


def test_generate_model_scorecard_deterministic_reproducibility() -> None:
    identity = make_run_identity_v2()
    metrics = make_sample_evaluation_metrics()
    trials = [Decimal("0.5"), Decimal("1.2"), Decimal("1.85")]

    card1 = generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=metrics,
        trial_sharpe_ratios=trials,
        created_at=CREATED_AT,
        deterministic=True,
    )
    card2 = generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=metrics,
        trial_sharpe_ratios=trials,
        created_at=CREATED_AT,
        deterministic=True,
    )
    assert card1.scorecard_id == card2.scorecard_id
    assert card1.scorecard_hash == card2.scorecard_hash
    assert card1 == card2
