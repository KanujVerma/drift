"""Unit tests for ResearchMemoryRecorder and M0 ledger persistence (M6-2)."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

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
from drift.domain.predictions import PredictionTargetType
from drift.domain.research_memory import (
    HYPOTHESIS_STATE_EVENT_TYPE,
    POSTMORTEM_EVENT_TYPE,
    TRIAL_EVENT_TYPE,
    FailureCategory,
    HypothesisStatus,
    TrialOutcome,
    build_failure_postmortem,
    build_hypothesis_lifecycle,
    build_research_trial_record,
)
from drift.domain.scorecards import (
    CalibrationSummaryV1,
    InformationCoefficientSummaryV1,
    MultipleTestingSummaryV1,
    build_model_scorecard,
    build_prediction_scorecard,
)
from drift.domain.sessions import SessionKeyV1
from drift.errors import DuplicateEventError
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.recorder import (
    HYPOTHESIS_ENTITY_TYPE,
    POSTMORTEM_ENTITY_TYPE,
    TRIAL_ENTITY_TYPE,
    ResearchMemoryRecorder,
)
from drift.scorecards.performance import generate_strategy_scorecard

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
HYPOTHESIS_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
RUN_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
TRIAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")
POSTMORTEM_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd05")
HASH_1 = "a" * 64
SESSION_KEY_1 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 5)
)
SESSION_KEY_2 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 6)
)


def make_run_identity_v2(**overrides: Any) -> EvaluationRunIdentityV2:
    fields: dict[str, Any] = {
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


def make_sample_metrics(
    *,
    is_complete: bool = True,
    drawdown_nav: Decimal = Decimal("105000.00"),
    traded_notional: Decimal = Decimal("10000.00"),
) -> EvaluationSummaryMetricsV1:
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
            cash_balance=drawdown_nav,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=drawdown_nav,
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
        ending_cash=drawdown_nav,
        ending_net_asset_value=drawdown_nav,
        net_profit_and_loss=drawdown_nav - Decimal("100000.00"),
        realized_gross_pnl=drawdown_nav - Decimal("100000.00"),
        realized_net_pnl=drawdown_nav - Decimal("100000.00"),
        cumulative_transaction_costs=Decimal("0.00"),
        gross_traded_notional=traded_notional,
        committed_fill_count=1,
        equity_series=points,
        realized_pnl_completeness=RealizedPnLCompletenessV1(
            is_complete=is_complete,
            excluded_disposals=exclusions,
        ),
    )


# =========================================================================
# Ledger Recording & Chain Verification Tests
# =========================================================================


def test_record_trial_seals_audit_event(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_sessions": 252},
        headline_metrics={"sharpe_ratio": "1.45"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )

    event = recorder.record_trial(trial)
    assert event.event_type == TRIAL_EVENT_TYPE
    assert event.entity_type == TRIAL_ENTITY_TYPE
    assert event.entity_id == TRIAL_ID_1
    assert isinstance(event.payload, Mapping)
    trial_payload = event.payload["trial"]
    assert isinstance(trial_payload, Mapping)
    assert trial_payload["trial_id"] == str(TRIAL_ID_1)

    # Verify cryptographic chain integrity
    ledger.verify_chain()


def test_record_postmortem_seals_audit_event(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    postmortem = build_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.DRAWDOWN_BREACH,
        root_cause_summary="Drawdown exceeded 20%",
        lessons_learned="Stop loss required",
        created_at=TIMESTAMP,
    )

    event = recorder.record_postmortem(postmortem)
    assert event.event_type == POSTMORTEM_EVENT_TYPE
    assert event.entity_type == POSTMORTEM_ENTITY_TYPE
    assert event.entity_id == POSTMORTEM_ID_1
    assert isinstance(event.payload, Mapping)
    postmortem_payload = event.payload["postmortem"]
    assert isinstance(postmortem_payload, Mapping)
    assert postmortem_payload["postmortem_id"] == str(POSTMORTEM_ID_1)

    ledger.verify_chain()


def test_record_hypothesis_state_seals_audit_event(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    lifecycle = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.PROPOSED,
        updated_at=TIMESTAMP,
        notes="Newly formulated hypothesis",
    )

    event = recorder.record_hypothesis_state(lifecycle)
    assert event.event_type == HYPOTHESIS_STATE_EVENT_TYPE
    assert event.entity_type == HYPOTHESIS_ENTITY_TYPE
    assert event.entity_id == HYPOTHESIS_ID_1
    assert isinstance(event.payload, Mapping)
    lifecycle_payload = event.payload["lifecycle"]
    assert isinstance(lifecycle_payload, Mapping)
    assert lifecycle_payload["status"] == "proposed"

    ledger.verify_chain()


def test_duplicate_trial_rejected_by_deduplication_key(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_sessions": 252},
        headline_metrics={"sharpe_ratio": "1.45"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )

    recorder.record_trial(trial)
    with pytest.raises(DuplicateEventError):
        recorder.record_trial(trial)


# =========================================================================
# Failure Category Diagnosis & Automated Postmortem Tests
# =========================================================================


def test_detect_failure_data_defect(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    identity = make_run_identity_v2()

    incomplete_metrics = make_sample_metrics(is_complete=False)
    scorecard = generate_strategy_scorecard(
        result=incomplete_metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    postmortem, event = recorder.create_and_record_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        scorecard=scorecard,
        root_cause_summary="Realized PnL incompleteness detected",
        lessons_learned="Fix cost basis allocation before evaluation",
        created_at=TIMESTAMP,
    )

    assert postmortem.failure_category == FailureCategory.DATA_DEFECT
    assert event.event_type == POSTMORTEM_EVENT_TYPE
    ledger.verify_chain()


def test_detect_failure_drawdown_breach(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    identity = make_run_identity_v2()

    severe_drawdown_metrics = make_sample_metrics(drawdown_nav=Decimal("75000.00"))
    scorecard = generate_strategy_scorecard(
        result=severe_drawdown_metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    postmortem, event = recorder.create_and_record_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        scorecard=scorecard,
        root_cause_summary="Maximum drawdown exceeded 20% limit",
        lessons_learned="Implement tighter stop loss rules",
        created_at=TIMESTAMP,
    )

    assert postmortem.failure_category == FailureCategory.DRAWDOWN_BREACH
    assert event.event_type == POSTMORTEM_EVENT_TYPE
    ledger.verify_chain()


def test_detect_failure_turnover_drag(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    identity = make_run_identity_v2()

    extreme_turnover_metrics = make_sample_metrics(
        traded_notional=Decimal("2000000.00")
    )
    scorecard = generate_strategy_scorecard(
        result=extreme_turnover_metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    postmortem, event = recorder.create_and_record_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        scorecard=scorecard,
        root_cause_summary="Excessive turnover drag",
        lessons_learned="Reduce rebalancing frequency",
        created_at=TIMESTAMP,
    )

    assert postmortem.failure_category == FailureCategory.TURNOVER_DRAG
    assert event.event_type == POSTMORTEM_EVENT_TYPE
    ledger.verify_chain()


def test_detect_failure_negative_alpha_and_calibration(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_memory.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    identity = make_run_identity_v2()

    # Strategy scorecard
    metrics = make_sample_metrics()
    strat_scorecard = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    # Prediction scorecard with negative IC
    pred_scorecard = build_prediction_scorecard(
        scorecard_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd99"),
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.DIRECTIONAL_RETURN,
        ic_summary=InformationCoefficientSummaryV1(
            evaluated_sessions=10,
            mean_spearman_ic=Decimal("-0.05"),
            std_spearman_ic=Decimal("0.10"),
            information_ratio_ic=Decimal("-0.50"),
            t_statistic_ic=Decimal("-1.58"),
            positive_ic_ratio=Decimal("0.40"),
            mean_pearson_ic=Decimal("-0.04"),
        ),
        calibration_summary=CalibrationSummaryV1(
            brier_score=Decimal("0.30"),
            expected_calibration_error=Decimal("0.10"),
        ),
        total_predictions=10,
        resolved_predictions=10,
        indeterminate_predictions=0,
        delisted_predictions=0,
        created_at=TIMESTAMP,
    )

    model_scorecard = build_model_scorecard(
        scorecard_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde0"),
        run_identity=identity,
        lane="exploratory",
        created_at=TIMESTAMP,
        prediction_scorecard=pred_scorecard,
        strategy_scorecard=strat_scorecard,
    )

    postmortem, _ = recorder.create_and_record_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        scorecard=model_scorecard,
        root_cause_summary="Information coefficient is negative",
        lessons_learned="Invert signal logic or re-estimate features",
        created_at=TIMESTAMP,
    )
    assert postmortem.failure_category == FailureCategory.NEGATIVE_ALPHA

    # Test overfitting rejection via multiple testing
    mt_summary = MultipleTestingSummaryV1(
        trial_count=100,
        sharpe_trial_variance=Decimal("0.50"),
        expected_max_null_sharpe=Decimal("2.10"),
        deflated_sharpe_ratio=Decimal("0.60"),
        is_dsr_significant_at_95=False,
        bonferroni_adjusted_p_value=Decimal("0.80"),
        holm_adjusted_p_value=Decimal("0.75"),
        benjamini_hochberg_fdr_q=Decimal("0.70"),
    )
    overfit_model_scorecard = build_model_scorecard(
        scorecard_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde1"),
        run_identity=identity,
        lane="exploratory",
        created_at=TIMESTAMP,
        strategy_scorecard=strat_scorecard,
        multiple_testing=mt_summary,
    )

    pm2, _ = recorder.create_and_record_failure_postmortem(
        postmortem_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd06"),
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        scorecard=overfit_model_scorecard,
        root_cause_summary="DSR fell below 95% threshold",
        lessons_learned="Penalize hypothesis trial count",
        created_at=TIMESTAMP,
    )
    assert pm2.failure_category == FailureCategory.OVERFITTING_REJECTION
