"""M5 adversarial acceptance suite: statistical and model scorecards (Issue 199).

Attacks the scorecard kernel across seven criteria:
1. Bit-Flip Hash Tampering: Any mutation in metric payloads invalidates hashes.
2. Degenerate Return Series: Zero-volatility, single-session, and flat curves fail.
3. PnL Incompleteness Laundering: Excluded disposals cannot be suppressed.
4. Multiple-Testing Monotonicity: FWER step-down and FDR step-up constraints.
5. Large-Scale Selection Bias Deflation: DSR deflates candidate Sharpes.
6. Degenerate Prediction & Calibration Bounds: Identical ranks and empty epochs.
7. Ledger Event Tamper Detection: Database modification breaks chain verification.

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    evaluation_run_identity_v2_hash,
)
from drift.domain.evaluator_results import (
    EvaluationSummaryMetricsV1,
    ExcludedDisposalV1,
    RealizedPnLCompletenessV1,
    SessionEquityPointV1,
)
from drift.domain.outcomes import (
    OutcomeResolutionStatus,
    build_realized_outcome_batch,
    build_realized_outcome_record,
)
from drift.domain.predictions import (
    HorizonSpecificationV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
    build_ex_ante_prediction_record,
    build_ex_ante_prediction_set,
)
from drift.domain.scorecards import (
    StrategyScorecardV1,
    compute_strategy_scorecard_hash,
)
from drift.domain.sessions import SessionKeyV1
from drift.errors import LedgerIntegrityError
from drift.ledger.sqlite import SQLiteLedger
from drift.scorecards.generator import (
    ScorecardGeneratorHarness,
    generate_model_scorecard,
)
from drift.scorecards.multiple_testing import (
    benjamini_hochberg_adjust_all,
    compute_deflated_sharpe_ratio,
    compute_expected_max_null_sharpe,
    holm_bonferroni_adjust_all,
)
from drift.scorecards.performance import (
    compute_drawdown_profile,
    compute_return_and_risk,
    generate_strategy_scorecard,
)
from drift.scorecards.predictive import (
    compute_calibration_summary,
    compute_pearson_correlation,
    compute_spearman_rank_correlation,
    fractional_ranks,
    generate_prediction_scorecard,
)

CREATED_AT = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
SCORECARD_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
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


def make_sample_metrics(*, is_complete: bool = True) -> EvaluationSummaryMetricsV1:
    points = (
        SessionEquityPointV1(
            session_index=0,
            session_key=SESSION_KEY_1,
            cash_balance=Decimal("100000.00"),
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("100000.00"),
        ),
        SessionEquityPointV1(
            session_index=1,
            session_key=SESSION_KEY_2,
            cash_balance=Decimal("105000.00"),
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("105000.00"),
        ),
    )
    exclusions: tuple[ExcludedDisposalV1, ...] = ()
    if not is_complete:
        exclusions = (
            ExcludedDisposalV1(
                security_id=UUID("00000000-0000-7000-8000-000000000001"),
                source_id="src-1",
                action_kind=ActionKind.SPINOFF,
                occurrence_id="occ-1",
                component_id="comp-1",
                session_key=SESSION_KEY_1,
                cash_proceeds=Decimal("150.00"),
                reason="unallocated basis",
                applied_effect_id="e" * 64,
            ),
        )
    return EvaluationSummaryMetricsV1(
        evaluated_session_count=2,
        initial_cash=Decimal("100000.00"),
        initial_net_asset_value=Decimal("100000.00"),
        ending_cash=Decimal("105000.00"),
        ending_net_asset_value=Decimal("105000.00"),
        net_profit_and_loss=Decimal("5000.00"),
        realized_gross_pnl=Decimal("5000.00"),
        realized_net_pnl=Decimal("5000.00"),
        cumulative_transaction_costs=Decimal("0.00"),
        gross_traded_notional=Decimal("10000.00"),
        committed_fill_count=1,
        equity_series=points,
        realized_pnl_completeness=RealizedPnLCompletenessV1(
            is_complete=is_complete,
            excluded_disposals=exclusions,
        ),
    )


# =========================================================================
# Attack 1: Bit-Flip Hash Tampering
# =========================================================================


def test_adversarial_hash_bit_flip_sensitivity() -> None:
    identity = make_run_identity_v2()
    metrics = make_sample_metrics()

    card_honest = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=CREATED_AT,
        scorecard_id=SCORECARD_ID_1,
    )

    # Control: deterministic re-generation yields bitwise identical hash
    card_repeat = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=CREATED_AT,
        scorecard_id=SCORECARD_ID_1,
    )
    assert card_honest.scorecard_hash == card_repeat.scorecard_hash

    # Attack: modify cumulative return by 1 basis point; hash must differ
    mutated_unsigned = card_honest.model_dump(mode="python")
    mutated_unsigned["cumulative_return"] = Decimal("0.0501")
    tampered_hash = compute_strategy_scorecard_hash(mutated_unsigned)
    assert tampered_hash != card_honest.scorecard_hash

    # Attack: attempt to validate model with forged hash fails
    with pytest.raises(ValidationError, match="strategy scorecard hash mismatch"):
        StrategyScorecardV1.model_validate(
            {
                **card_honest.model_dump(mode="python"),
                "scorecard_hash": "f" * 64,
            }
        )


# =========================================================================
# Attack 2: Degenerate Return Series & Division-by-Zero Resistance
# =========================================================================


def test_adversarial_degenerate_zero_volatility_returns() -> None:
    # 10 sessions with perfectly constant NAV
    flat_navs = [Decimal("100000.00")] * 10
    cum_ret, ann_ret, ann_vol, down_dev, sharpe, sortino, calmar = (
        compute_return_and_risk(flat_navs, initial_nav=Decimal("100000.00"))
    )
    assert cum_ret == Decimal("0.0000")
    assert ann_ret == Decimal("0.0000")
    assert ann_vol == Decimal("0.0000")
    assert down_dev == Decimal("0.0000")
    assert sharpe == Decimal("0.0000")
    assert sortino == Decimal("0.0000")
    assert calmar == Decimal("0.0000")

    # Drawdown profile for flat curve
    dd_profile = compute_drawdown_profile(flat_navs, initial_nav=Decimal("100000.00"))
    assert dd_profile.maximum_drawdown == Decimal("0.0000")
    assert dd_profile.max_drawdown_duration_sessions == 0
    assert dd_profile.current_drawdown == Decimal("0.0000")
    assert dd_profile.is_recovered is True


def test_adversarial_single_observation_session() -> None:
    # Single session returns
    single_nav = [Decimal("101000.00")]
    cum_ret, ann_ret, ann_vol, down_dev, sharpe, sortino, calmar = (
        compute_return_and_risk(single_nav, initial_nav=Decimal("100000.00"))
    )
    assert cum_ret == Decimal("0.0100")
    # Single session has undefined sample variance, defaults to 0
    assert ann_vol == Decimal("0.0000")
    assert sharpe == Decimal("0.0000")


# =========================================================================
# Attack 3: PnL Incompleteness Laundering Protection
# =========================================================================


def test_adversarial_pnl_incompleteness_anti_laundering() -> None:
    identity = make_run_identity_v2()
    incomplete_metrics = make_sample_metrics(is_complete=False)

    card = generate_strategy_scorecard(
        result=incomplete_metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=CREATED_AT,
    )
    # Defense: incompleteness is strictly propagated
    assert card.pnl_completeness.is_complete is False
    assert len(card.pnl_completeness.excluded_disposals) == 1
    assert card.pnl_completeness.excluded_disposals[0].action_kind == ActionKind.SPINOFF

    # Attack: attempting to forge is_complete=False without naming disposals fails
    with pytest.raises(
        ValidationError,
        match="an incomplete realized PnL signal must name the excluded disposals",
    ):
        RealizedPnLCompletenessV1(is_complete=False, excluded_disposals=())


# =========================================================================
# Attack 4: Multiple-Testing Monotonicity Constraints
# =========================================================================


def test_adversarial_holm_bonferroni_monotonicity_guarantee() -> None:
    # Adversarial scrambled p-value sequence
    pathological_p = [
        Decimal("0.0450"),
        Decimal("0.0010"),
        Decimal("0.0320"),
        Decimal("0.0150"),
        Decimal("0.0320"),
    ]
    adj = holm_bonferroni_adjust_all(pathological_p)

    # Check monotonicity when sorted by original p-value
    pairs = sorted(zip(pathological_p, adj, strict=True), key=lambda x: x[0])
    for i in range(len(pairs) - 1):
        assert pairs[i][1] <= pairs[i + 1][1], (
            f"Holm monotonicity violated: {pairs[i][1]} > {pairs[i + 1][1]}"
        )


def test_adversarial_benjamini_hochberg_step_up_monotonicity() -> None:
    # Adversarial scrambled p-values with ties
    pathological_p = [
        Decimal("0.0500"),
        Decimal("0.0020"),
        Decimal("0.0200"),
        Decimal("0.0020"),
        Decimal("0.0800"),
    ]
    q_values = benjamini_hochberg_adjust_all(pathological_p)

    # Check step-up monotonicity when sorted by original p-value
    pairs = sorted(zip(pathological_p, q_values, strict=True), key=lambda x: x[0])
    for i in range(len(pairs) - 1):
        assert pairs[i][1] <= pairs[i + 1][1], (
            f"BH step-up monotonicity violated: {pairs[i][1]} > {pairs[i + 1][1]}"
        )


# =========================================================================
# Attack 5: Large-Scale Selection Bias Deflation (Bailey & Lopez de Prado)
# =========================================================================


def test_adversarial_large_trial_selection_bias_deflation() -> None:
    # Strategy with apparent Sharpe of 1.50
    candidate_sharpe = Decimal("1.50")
    n_sessions = 252

    # Control: single trial evaluates to significant DSR
    dsr_single = compute_deflated_sharpe_ratio(
        candidate_sharpe=candidate_sharpe,
        expected_max_null_sharpe=Decimal("0.0"),
        sample_size_sessions=n_sessions,
    )
    assert dsr_single >= Decimal("0.9500")

    # Attack: candidate was selected after testing 2000 trial variants
    # with substantial variance
    # Simulate trial distribution
    trial_count = 2000
    # Expected max null Sharpe should be > 1.80 under 2000 trials
    fake_trials = [
        Decimal("-1.5") + Decimal(str(i % 31)) * Decimal("0.1")
        for i in range(trial_count)
    ]
    variance, sr_star = compute_expected_max_null_sharpe(fake_trials)

    assert sr_star > candidate_sharpe

    dsr_deflated = compute_deflated_sharpe_ratio(
        candidate_sharpe=candidate_sharpe,
        expected_max_null_sharpe=sr_star,
        sample_size_sessions=n_sessions,
    )
    # Deflated Sharpe ratio correctly rejects selection-biased strategy
    assert dsr_deflated < Decimal("0.5000")
    assert dsr_deflated < dsr_single


# =========================================================================
# Attack 6: Degenerate Prediction & Calibration Bounds
# =========================================================================


def test_adversarial_predictive_all_identical_predictions() -> None:
    # If all predictions are identical, variance is zero
    identical_preds = [Decimal("0.05")] * 10
    truths = [Decimal("0.01") * Decimal(str(i)) for i in range(10)]

    # Fractional ranks assigns identical rank (5.5) to all
    ranks = fractional_ranks(identical_preds)
    assert all(r == Decimal("5.5") for r in ranks)

    # Spearman and Pearson correlation fail closed to 0 without division by zero
    spearman = compute_spearman_rank_correlation(identical_preds, truths)
    pearson = compute_pearson_correlation(identical_preds, truths)
    assert spearman == Decimal("0.0000")
    assert pearson == Decimal("0.0000")


def test_adversarial_calibration_binary_extremes() -> None:
    # Predictions strictly 0.0 or 1.0 matching labels
    preds = [Decimal("0.0"), Decimal("1.0"), Decimal("1.0"), Decimal("0.0")]
    labels = [Decimal("0.0"), Decimal("1.0"), Decimal("1.0"), Decimal("0.0")]

    summary = compute_calibration_summary(preds, labels)
    assert summary.brier_score == Decimal("0.0000")
    assert summary.mean_absolute_error == Decimal("0.0000")
    assert summary.expected_calibration_error == Decimal("0.0000")


# =========================================================================
# Attack 7: Ledger Event Cryptographic Chain Tampering
# =========================================================================


def test_adversarial_ledger_event_tamper_detection(tmp_path: Path) -> None:
    ledger_path = tmp_path / "research_audit.sqlite3"
    ledger = SQLiteLedger(ledger_path)
    harness = ScorecardGeneratorHarness(ledger=ledger, deterministic=True)

    identity = make_run_identity_v2()
    metrics = make_sample_metrics()

    card = harness.generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=metrics,
        created_at=CREATED_AT,
    )
    # Control: ledger verifies chain cleanly
    ledger.verify_chain()

    # Attack: verify SQLite trigger prevents direct update
    conn = sqlite3.connect(ledger_path)
    cursor = conn.cursor()
    with pytest.raises(sqlite3.DatabaseError, match="audit_events is append-only"):
        cursor.execute(
            "UPDATE audit_events SET payload_json = '{\"tampered\": true}' "
            "WHERE entity_id = ?",
            (str(card.scorecard_id),),
        )

    # Attack: simulate raw low-level database tamper by dropping trigger,
    # mutating payload, and restoring trigger
    cursor.execute("DROP TRIGGER audit_events_no_update")
    cursor.execute(
        "UPDATE audit_events SET payload_json = '{\"tampered\":true}' "
        "WHERE entity_id = ?",
        (str(card.scorecard_id),),
    )
    cursor.execute("""
        CREATE TRIGGER audit_events_no_update
        BEFORE UPDATE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'audit_events is append-only');
        END
    """)
    conn.commit()
    conn.close()

    # Defense: reopened ledger detects cryptographic event hash mismatch
    tampered_ledger = SQLiteLedger(ledger_path)
    with pytest.raises(LedgerIntegrityError, match="event hash mismatch"):
        tampered_ledger.verify_chain()


# =========================================================================
# Attack 8: Empty Shell Laundering Prevention
# =========================================================================


def test_adversarial_empty_model_scorecard_rejection() -> None:
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


def test_adversarial_model_scorecard_pnl_incompleteness_anti_laundering(
    tmp_path: Path,
) -> None:
    identity = make_run_identity_v2()
    incomplete_metrics = make_sample_metrics(is_complete=False)
    ledger = SQLiteLedger(tmp_path / "ledger.sqlite3")
    harness = ScorecardGeneratorHarness(ledger=ledger, deterministic=True)

    card = harness.generate_model_scorecard(
        run_identity=identity,
        lane="exploratory",
        evaluation_result=incomplete_metrics,
        created_at=CREATED_AT,
    )
    assert card.strategy_scorecard is not None
    assert card.strategy_scorecard.pnl_completeness.is_complete is False
    assert len(card.strategy_scorecard.pnl_completeness.excluded_disposals) == 1
    assert (
        card.strategy_scorecard.pnl_completeness.excluded_disposals[0].action_kind
        == ActionKind.SPINOFF
    )


def test_adversarial_empty_prediction_epoch_fail_closed() -> None:
    identity = make_run_identity_v2()
    scorecard = generate_prediction_scorecard(
        prediction_sets=(),
        outcome_batches=(),
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.CROSS_SECTIONAL_RANK,
        as_of_time=CREATED_AT,
        scorecard_id=SCORECARD_ID_1,
    )
    assert scorecard.total_predictions == 0
    assert scorecard.resolved_predictions == 0
    assert scorecard.indeterminate_predictions == 0
    assert scorecard.delisted_predictions == 0
    assert scorecard.ic_summary.mean_spearman_ic == Decimal("0.0000")
    assert scorecard.ic_summary.information_ratio_ic == Decimal("0.0000")
    assert scorecard.calibration_summary.mean_absolute_error is None
    assert len(scorecard.calibration_summary.bins) == 0


def test_adversarial_prediction_epoch_order_invariance() -> None:
    identity = make_run_identity_v2()
    horizon_1 = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    horizon_2 = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 16),
        start_session_date=date(2026, 1, 17),
        end_session_date=date(2026, 1, 17),
    )
    pred_1 = build_ex_ante_prediction_record(
        prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd21"),
        run_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde0"),
        security_id=UUID("00000000-0000-7000-8000-000000000001"),
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=horizon_1,
        as_of_time=CREATED_AT,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
        input_context_hash="0" * 64,
        model_provenance_hash="0" * 64,
    )
    pred_2 = build_ex_ante_prediction_record(
        prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd22"),
        run_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde0"),
        security_id=UUID("00000000-0000-7000-8000-000000000002"),
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=horizon_2,
        as_of_time=CREATED_AT,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.04")),
        input_context_hash="0" * 64,
        model_provenance_hash="0" * 64,
    )
    set_1 = build_ex_ante_prediction_set(
        prediction_set_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd31"),
        run_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde0"),
        session_date=date(2026, 1, 15),
        as_of_time=CREATED_AT,
        lane="exploratory",
        predictions=[pred_1],
    )
    set_2 = build_ex_ante_prediction_set(
        prediction_set_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd32"),
        run_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde0"),
        session_date=date(2026, 1, 16),
        as_of_time=CREATED_AT,
        lane="exploratory",
        predictions=[pred_2],
    )

    out_1 = build_realized_outcome_record(
        outcome_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd41"),
        prediction_id=pred_1.prediction_id,
        status=OutcomeResolutionStatus.RESOLVED,
        realized_value=Decimal("0.02"),
        resolved_at=CREATED_AT,
        evidence_hashes=("1" * 64,),
    )
    out_2 = build_realized_outcome_record(
        outcome_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd42"),
        prediction_id=pred_2.prediction_id,
        status=OutcomeResolutionStatus.RESOLVED,
        realized_value=Decimal("0.04"),
        resolved_at=CREATED_AT,
        evidence_hashes=("1" * 64,),
    )
    batch_1 = build_realized_outcome_batch(
        outcome_batch_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd51"),
        run_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde0"),
        resolved_at=CREATED_AT,
        lane="exploratory",
        outcomes=[out_1],
    )
    batch_2 = build_realized_outcome_batch(
        outcome_batch_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd52"),
        run_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde0"),
        resolved_at=CREATED_AT,
        lane="exploratory",
        outcomes=[out_2],
    )

    sc_forward = generate_prediction_scorecard(
        prediction_sets=[set_1, set_2],
        outcome_batches=[batch_1, batch_2],
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        as_of_time=CREATED_AT,
        scorecard_id=SCORECARD_ID_1,
    )
    sc_reversed = generate_prediction_scorecard(
        prediction_sets=[set_2, set_1],
        outcome_batches=[batch_2, batch_1],
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        as_of_time=CREATED_AT,
        scorecard_id=SCORECARD_ID_1,
    )

    assert sc_forward.scorecard_hash == sc_reversed.scorecard_hash
