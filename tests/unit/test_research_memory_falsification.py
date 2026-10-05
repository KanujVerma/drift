"""Unit tests for HypothesisManager and FailurePostmortemEngine (M6-3)."""

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
from drift.domain.hypotheses import Hypothesis
from drift.domain.research_memory import (
    FailureCategory,
    HypothesisStatus,
    TrialOutcome,
    build_research_trial_record,
)
from drift.domain.scorecards import (
    MultipleTestingSummaryV1,
    build_model_scorecard,
)
from drift.domain.sessions import SessionKeyV1
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.hypothesis import (
    HypothesisFalsificationCriteria,
    HypothesisManager,
    HypothesisNotFoundError,
    InvalidStateTransitionError,
)
from drift.memory.postmortem import FailurePostmortemEngine
from drift.memory.recorder import ResearchMemoryRecorder
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


def make_hypothesis(
    hypothesis_id: UUID = HYPOTHESIS_ID_1,
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        created_at=TIMESTAMP,
        title="Momentum Factor in Large Cap Equities",
        statement=(
            "Equities with top quintile 12-month returns outperform bottom quintile."
        ),
        mechanism="Gradual information diffusion and behavioral underreaction.",
        expected_direction="positive",
        universe="top_100_liquid",
        horizon="21_sessions",
        falsification_criteria="Negative mean Spearman IC across evaluation period",
        author_type="agent",
        author_version="m6_test",
        tags=("momentum", "cross_sectional"),
    )


# =========================================================================
# Hypothesis State Machine & Transition Tests
# =========================================================================


def test_hypothesis_state_machine_valid_transitions(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    manager = HypothesisManager(recorder)

    hypo = make_hypothesis()
    lc = manager.register_hypothesis(hypo)
    assert lc.status == HypothesisStatus.PROPOSED
    assert manager.get_state(hypo.hypothesis_id).status == HypothesisStatus.PROPOSED

    # Transition to ACTIVE
    lc_active = manager.activate_hypothesis(hypo.hypothesis_id)
    assert lc_active.status == HypothesisStatus.ACTIVE

    # Transition to VALIDATED
    lc_val = manager.validate_hypothesis(
        hypo.hypothesis_id,
        evidence_hashes=(HASH_1,),
        notes="Validated by out-of-sample test",
    )
    assert lc_val.status == HypothesisStatus.VALIDATED
    assert lc_val.validated_at is not None
    assert lc_val.validation_evidence == (HASH_1,)

    # From VALIDATED, can be falsified later by counter-evidence
    lc_fals = manager.falsify_hypothesis(
        hypo.hypothesis_id,
        evidence_hashes=(HASH_1, "b" * 64),
        notes="Regime shift invalidated original claim",
    )
    assert lc_fals.status == HypothesisStatus.FALSIFIED
    assert lc_fals.falsified_at is not None

    ledger.verify_chain()


def test_hypothesis_state_machine_invalid_transitions(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    manager = HypothesisManager(recorder)

    hypo = make_hypothesis()
    manager.register_hypothesis(hypo)

    # Cannot transition directly from PROPOSED to VALIDATED
    with pytest.raises(InvalidStateTransitionError):
        manager.validate_hypothesis(
            hypo.hypothesis_id,
            evidence_hashes=(HASH_1,),
        )

    # Cannot transition directly from PROPOSED to FALSIFIED
    with pytest.raises(InvalidStateTransitionError):
        manager.falsify_hypothesis(
            hypo.hypothesis_id,
            evidence_hashes=(HASH_1,),
        )

    # Transition to ABANDONED
    manager.abandon_hypothesis(hypo.hypothesis_id)
    assert manager.get_state(hypo.hypothesis_id).status == HypothesisStatus.ABANDONED

    # ABANDONED is terminal: cannot transition to ACTIVE
    with pytest.raises(InvalidStateTransitionError):
        manager.activate_hypothesis(hypo.hypothesis_id)


def test_hypothesis_not_found(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    manager = HypothesisManager(recorder)

    with pytest.raises(HypothesisNotFoundError):
        manager.get_state(UUID("018f3a5b-6c7d-7890-8123-000000000000"))


# =========================================================================
# Pre-Registered Falsification Criteria Evaluation Tests
# =========================================================================


def test_falsification_triggered_by_drawdown_limit(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    manager = HypothesisManager(recorder)

    hypo = make_hypothesis()
    criteria = HypothesisFalsificationCriteria(max_drawdown_limit=Decimal("-0.20"))
    manager.register_hypothesis(hypo, criteria=criteria)
    manager.activate_hypothesis(hypo.hypothesis_id)

    identity = make_run_identity_v2()
    # 25% drawdown
    metrics = make_sample_metrics(drawdown_nav=Decimal("75000.00"))
    scorecard = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=hypo.hypothesis_id,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        headline_metrics={"sharpe_ratio": "-1.2"},
        trial_outcome=TrialOutcome.FAILED,
        created_at=TIMESTAMP,
    )

    lc = manager.evaluate_trial(
        hypothesis_id=hypo.hypothesis_id,
        trial=trial,
        scorecard=scorecard,
    )
    assert lc.status == HypothesisStatus.FALSIFIED
    assert trial.trial_hash in lc.falsification_evidence
    assert scorecard.scorecard_hash in lc.falsification_evidence
    ledger.verify_chain()


def test_falsification_triggered_by_consecutive_failures(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    manager = HypothesisManager(recorder)

    hypo = make_hypothesis()
    criteria = HypothesisFalsificationCriteria(max_consecutive_failures=2)
    manager.register_hypothesis(hypo, criteria=criteria)
    manager.activate_hypothesis(hypo.hypothesis_id)

    trial1 = build_research_trial_record(
        trial_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd11"),
        hypothesis_id=hypo.hypothesis_id,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 10},
        headline_metrics={"sharpe_ratio": "0.1"},
        trial_outcome=TrialOutcome.FAILED,
        created_at=TIMESTAMP,
    )
    lc1 = manager.evaluate_trial(
        hypothesis_id=hypo.hypothesis_id,
        trial=trial1,
    )
    # First failure does not trigger falsification yet
    assert lc1.status == HypothesisStatus.ACTIVE

    trial2 = build_research_trial_record(
        trial_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd12"),
        hypothesis_id=hypo.hypothesis_id,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        headline_metrics={"sharpe_ratio": "-0.5"},
        trial_outcome=TrialOutcome.FAILED,
        created_at=TIMESTAMP,
    )
    lc2 = manager.evaluate_trial(
        hypothesis_id=hypo.hypothesis_id,
        trial=trial2,
    )
    # Second failure triggers falsification!
    assert lc2.status == HypothesisStatus.FALSIFIED
    ledger.verify_chain()


def test_validation_triggered_by_superior_trial(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    manager = HypothesisManager(recorder)

    hypo = make_hypothesis()
    criteria = HypothesisFalsificationCriteria(
        min_validation_sharpe=Decimal("1.50"),
        require_dsr_significant=True,
    )
    manager.register_hypothesis(hypo, criteria=criteria)
    manager.activate_hypothesis(hypo.hypothesis_id)

    identity = make_run_identity_v2()
    metrics = make_sample_metrics()
    strat_scorecard = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    mt_summary = MultipleTestingSummaryV1(
        trial_count=10,
        sharpe_trial_variance=Decimal("0.20"),
        expected_max_null_sharpe=Decimal("1.20"),
        deflated_sharpe_ratio=Decimal("0.98"),
        is_dsr_significant_at_95=True,
        bonferroni_adjusted_p_value=Decimal("0.02"),
        holm_adjusted_p_value=Decimal("0.02"),
        benjamini_hochberg_fdr_q=Decimal("0.02"),
    )

    model_scorecard = build_model_scorecard(
        scorecard_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde2"),
        run_identity=identity,
        lane="exploratory",
        created_at=TIMESTAMP,
        strategy_scorecard=strat_scorecard,
        multiple_testing=mt_summary,
    )

    trial = build_research_trial_record(
        trial_id=TRIAL_ID_1,
        hypothesis_id=hypo.hypothesis_id,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 50},
        headline_metrics={"sharpe_ratio": "1.85"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )

    lc = manager.evaluate_trial(
        hypothesis_id=hypo.hypothesis_id,
        trial=trial,
        scorecard=model_scorecard,
    )
    assert lc.status == HypothesisStatus.VALIDATED
    assert trial.trial_hash in lc.validation_evidence
    ledger.verify_chain()


# =========================================================================
# FailurePostmortemEngine Tests
# =========================================================================


def test_extract_postmortem_drawdown_breach(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    engine = FailurePostmortemEngine(recorder)

    identity = make_run_identity_v2()
    metrics = make_sample_metrics(drawdown_nav=Decimal("70000.00"))
    scorecard = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    pm = engine.extract_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        scorecard=scorecard,
        custom_forbidden_variations=("Do not trade without volatility stops",),
        created_at=TIMESTAMP,
    )

    assert pm.failure_category == FailureCategory.DRAWDOWN_BREACH
    assert "Risk limit breach" in pm.root_cause_summary
    assert "stop-loss" in pm.lessons_learned
    assert "Do not trade without volatility stops" in pm.forbidden_variations
    assert scorecard.scorecard_hash in pm.evidence_hashes
    ledger.verify_chain()


def test_extract_postmortem_overfitting_rejection(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    engine = FailurePostmortemEngine(recorder)

    identity = make_run_identity_v2()
    metrics = make_sample_metrics()
    strat_scorecard = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=TIMESTAMP,
    )

    mt_summary = MultipleTestingSummaryV1(
        trial_count=100,
        sharpe_trial_variance=Decimal("0.50"),
        expected_max_null_sharpe=Decimal("2.10"),
        deflated_sharpe_ratio=Decimal("0.70"),
        is_dsr_significant_at_95=False,
        bonferroni_adjusted_p_value=Decimal("0.80"),
        holm_adjusted_p_value=Decimal("0.75"),
        benjamini_hochberg_fdr_q=Decimal("0.70"),
    )

    model_scorecard = build_model_scorecard(
        scorecard_id=UUID("018f3a5b-6c7d-7890-8123-456789abcde3"),
        run_identity=identity,
        lane="exploratory",
        created_at=TIMESTAMP,
        strategy_scorecard=strat_scorecard,
        multiple_testing=mt_summary,
    )

    pm = engine.extract_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        scorecard=model_scorecard,
        created_at=TIMESTAMP,
    )

    assert pm.failure_category == FailureCategory.OVERFITTING_REJECTION
    assert "Selection bias rejection" in pm.root_cause_summary
    assert "Bailey & Lopez de Prado" in pm.lessons_learned
    ledger.verify_chain()
