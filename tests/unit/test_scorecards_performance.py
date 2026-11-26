"""Unit tests for performance attribution, risk profiles, and drawdown engine.

Covers M5-3 (Issue 193).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

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
from drift.domain.sessions import SessionKeyV1
from drift.scorecards.performance import (
    compute_drawdown_profile,
    compute_return_and_risk,
    compute_turnover_summary,
    generate_strategy_scorecard,
)

RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcde0")
SCORECARD_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
AS_OF = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
SESSION_KEY_1 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 5)
)
SESSION_KEY_2 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 6)
)
SESSION_KEY_3 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 7)
)
SESSION_KEY_4 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 8)
)
SESSION_KEY_5 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 1, 9)
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


# =========================================================================
# Unit tests: compute_return_and_risk
# =========================================================================


def test_return_and_risk_positive_trajectory() -> None:
    navs = [
        Decimal("101000.00"),
        Decimal("102500.00"),
        Decimal("104000.00"),
        Decimal("103500.00"),
        Decimal("105000.00"),
    ]
    cum_ret, ann_ret, ann_vol, down_dev, sharpe, sortino, calmar = (
        compute_return_and_risk(navs, initial_nav=Decimal("100000.00"))
    )
    assert cum_ret == Decimal("0.0500")
    assert ann_ret > Decimal("0")
    assert ann_vol > Decimal("0")
    assert down_dev > Decimal("0")
    assert sharpe > Decimal("0")
    assert sortino > Decimal("0")
    assert calmar > Decimal("0")


def test_return_and_risk_flat_nav() -> None:
    navs = [Decimal("100000.00")] * 5
    cum_ret, ann_ret, ann_vol, down_dev, sharpe, sortino, calmar = (
        compute_return_and_risk(navs, initial_nav=Decimal("100000.00"))
    )
    assert cum_ret == Decimal("0.0000")
    assert ann_ret == Decimal("0.0000")
    assert ann_vol == Decimal("0.0000")
    assert sharpe == Decimal("0.0000")
    assert sortino == Decimal("0.0000")
    assert calmar == Decimal("0.0000")


def test_return_and_risk_empty() -> None:
    results = compute_return_and_risk([], initial_nav=Decimal("100000.00"))
    assert all(r == Decimal("0") for r in results)


# =========================================================================
# Unit tests: compute_drawdown_profile
# =========================================================================


def test_drawdown_profile_monotonically_increasing() -> None:
    navs = [Decimal("100.0"), Decimal("110.0"), Decimal("120.0")]
    profile = compute_drawdown_profile(navs, initial_nav=Decimal("100.0"))
    assert profile.maximum_drawdown == Decimal("0.0000")
    assert profile.current_drawdown == Decimal("0.0000")
    assert profile.is_recovered is True
    assert profile.max_drawdown_duration_sessions == 0


def test_drawdown_profile_with_recovery() -> None:
    # Day 1: 100, Day 2: 110 (Peak), Day 3: 99 (Trough, -10%),
    # Day 4: 105, Day 5: 120 (Recovery)
    navs = [
        Decimal("100.00"),
        Decimal("110.00"),
        Decimal("99.00"),
        Decimal("105.00"),
        Decimal("120.00"),
    ]
    profile = compute_drawdown_profile(navs, initial_nav=Decimal("100.00"))
    assert profile.maximum_drawdown == Decimal("-0.1000")
    assert profile.peak_to_trough_sessions == 1
    assert profile.recovery_sessions == 2
    assert profile.is_recovered is True
    assert profile.current_drawdown == Decimal("0.0000")


def test_drawdown_profile_unrecovered() -> None:
    navs = [Decimal("100.00"), Decimal("120.00"), Decimal("96.00")]
    profile = compute_drawdown_profile(navs, initial_nav=Decimal("100.00"))
    assert profile.maximum_drawdown == Decimal("-0.2000")
    assert profile.current_drawdown == Decimal("-0.2000")
    assert profile.is_recovered is False


# =========================================================================
# Unit tests: compute_turnover_summary
# =========================================================================


def test_turnover_summary() -> None:
    points = (
        SessionEquityPointV1(
            session_index=0,
            session_key=SESSION_KEY_1,
            cash_balance=Decimal("50000.00"),
            holdings_market_value=Decimal("50000.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("100000.00"),
        ),
    )
    metrics = EvaluationSummaryMetricsV1(
        evaluated_session_count=1,
        initial_cash=Decimal("100000.00"),
        initial_net_asset_value=Decimal("100000.00"),
        ending_cash=Decimal("50000.00"),
        ending_net_asset_value=Decimal("100000.00"),
        net_profit_and_loss=Decimal("0.00"),
        realized_gross_pnl=Decimal("0.00"),
        realized_net_pnl=Decimal("0.00"),
        cumulative_transaction_costs=Decimal("50.00"),
        gross_traded_notional=Decimal("10000.00"),
        committed_fill_count=2,
        equity_series=points,
    )
    turnover = compute_turnover_summary(metrics)
    assert turnover.mean_session_turnover == Decimal("0.0500")
    assert turnover.annualized_turnover == Decimal("12.6000")
    assert turnover.estimated_cost_drag == Decimal("0.0005")


# =========================================================================
# Unit tests: generate_strategy_scorecard
# =========================================================================


def test_generate_strategy_scorecard_complete_pnl() -> None:
    identity = make_run_identity_v2()
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
    metrics = EvaluationSummaryMetricsV1(
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

    card = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=AS_OF,
        scorecard_id=SCORECARD_ID,
    )

    assert card.scorecard_id == SCORECARD_ID
    assert card.lane == "exploratory"
    assert card.cumulative_return == Decimal("0.0200")
    assert card.pnl_completeness.is_complete is True
    assert len(card.pnl_completeness.excluded_disposals) == 0


def test_generate_strategy_scorecard_incomplete_pnl_preserved() -> None:
    identity = make_run_identity_v2()
    disposal = ExcludedDisposalV1(
        security_id=UUID("00000000-0000-7000-8000-000000000001"),
        source_id="src-1",
        action_kind=ActionKind.SPINOFF,
        occurrence_id="occ-1",
        component_id="cmp-1",
        session_key=SESSION_KEY_1,
        cash_proceeds=Decimal("10.50"),
        reason="unallocated parent cost basis for spin-off child residual disposal",
        applied_effect_id="1" * 64,
    )
    pnl_comp = RealizedPnLCompletenessV1(
        is_complete=False,
        excluded_disposals=(disposal,),
    )
    points = (
        SessionEquityPointV1(
            session_index=0,
            session_key=SESSION_KEY_1,
            cash_balance=Decimal("101000.00"),
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("101000.00"),
        ),
    )
    metrics = EvaluationSummaryMetricsV1(
        evaluated_session_count=1,
        initial_cash=Decimal("100000.00"),
        initial_net_asset_value=Decimal("100000.00"),
        ending_cash=Decimal("101000.00"),
        ending_net_asset_value=Decimal("101000.00"),
        net_profit_and_loss=Decimal("1000.00"),
        realized_gross_pnl=Decimal("1000.00"),
        realized_net_pnl=Decimal("1000.00"),
        cumulative_transaction_costs=Decimal("0.00"),
        gross_traded_notional=Decimal("0.00"),
        committed_fill_count=0,
        equity_series=points,
        realized_pnl_completeness=pnl_comp,
    )

    card = generate_strategy_scorecard(
        result=metrics,
        run_identity=identity,
        lane="exploratory",
        as_of_time=AS_OF,
        scorecard_id=SCORECARD_ID,
    )

    assert card.pnl_completeness.is_complete is False
    assert len(card.pnl_completeness.excluded_disposals) == 1
    assert card.pnl_completeness.excluded_disposals[0].security_id == UUID(
        "00000000-0000-7000-8000-000000000001"
    )
