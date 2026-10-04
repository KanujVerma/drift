"""Unit tests for evaluator results domain models.

Focuses on realized PnL completeness models and validation.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.common import UUID7
from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_results import (
    DISPOSAL_EXCLUSION_SPINOFF_RESIDUAL_UNALLOCATED_BASIS,
    EvaluationSummaryMetricsV1,
    ExcludedDisposalV1,
    RealizedPnLCompletenessV1,
    SessionEquityPointV1,
    disposal_sort_key,
    require_canonical_disposals,
)
from drift.domain.sessions import SessionKeyV1

ZERO = Decimal("0")

SEC_1 = UUID("018f3a2b-0001-7000-8000-000000000001")
SEC_2 = UUID("018f3a2b-0002-7000-8000-000000000002")
SESSION_1 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2)
)
SESSION_2 = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 3, 3)
)
EFFECT_ID_1 = "1" * 64
EFFECT_ID_2 = "2" * 64


def _sample_disposal(
    *,
    security_id: UUID7 = SEC_1,
    source_id: str = "src-1",
    action_kind: ActionKind = ActionKind.SPINOFF,
    occurrence_id: str = "occ-1",
    component_id: str = "cmp-1",
    session_key: SessionKeyV1 = SESSION_1,
    cash_proceeds: Decimal = Decimal("10.50"),
    reason: str = DISPOSAL_EXCLUSION_SPINOFF_RESIDUAL_UNALLOCATED_BASIS,
    applied_effect_id: str = EFFECT_ID_1,
) -> ExcludedDisposalV1:
    return ExcludedDisposalV1(
        security_id=security_id,
        source_id=source_id,
        action_kind=action_kind,
        occurrence_id=occurrence_id,
        component_id=component_id,
        session_key=session_key,
        cash_proceeds=cash_proceeds,
        reason=reason,
        applied_effect_id=applied_effect_id,
    )


def test_excluded_disposal_valid() -> None:
    disposal = _sample_disposal()
    assert disposal.schema_version == "1"
    assert disposal.security_id == SEC_1
    assert disposal.cash_proceeds == Decimal("10.50")
    assert disposal.reason == DISPOSAL_EXCLUSION_SPINOFF_RESIDUAL_UNALLOCATED_BASIS


def test_excluded_disposal_negative_proceeds_refused() -> None:
    with pytest.raises(ValidationError, match="cash proceeds must be non-negative"):
        _sample_disposal(cash_proceeds=Decimal("-0.01"))


def test_excluded_disposal_zero_proceeds_allowed() -> None:
    disposal = _sample_disposal(cash_proceeds=ZERO)
    assert disposal.cash_proceeds == ZERO


def test_disposal_sort_key_order() -> None:
    d1 = _sample_disposal(session_key=SESSION_1, security_id=SEC_1, component_id="a")
    d2 = _sample_disposal(session_key=SESSION_1, security_id=SEC_1, component_id="b")
    d3 = _sample_disposal(session_key=SESSION_1, security_id=SEC_2, component_id="a")
    d4 = _sample_disposal(session_key=SESSION_2, security_id=SEC_1, component_id="a")

    items = [d4, d3, d2, d1]
    sorted_items = sorted(items, key=disposal_sort_key)
    assert sorted_items == [d1, d2, d3, d4]


def test_require_canonical_disposals_rejects_duplicates() -> None:
    d1 = _sample_disposal(component_id="cmp-1")
    d2 = _sample_disposal(component_id="cmp-1")
    with pytest.raises(ValueError, match="excluded disposals must be unique"):
        require_canonical_disposals((d1, d2))


def test_require_canonical_disposals_rejects_unsorted() -> None:
    d1 = _sample_disposal(component_id="a")
    d2 = _sample_disposal(component_id="b")
    with pytest.raises(
        ValueError, match="excluded disposals must be canonically sorted"
    ):
        require_canonical_disposals((d2, d1))


def test_realized_pnl_completeness_default_is_complete() -> None:
    signal = RealizedPnLCompletenessV1()
    assert signal.schema_version == "1"
    assert signal.is_complete is True
    assert signal.excluded_disposals == ()


def test_realized_pnl_completeness_complete_with_exclusions_refused() -> None:
    d = _sample_disposal()
    with pytest.raises(
        ValidationError,
        match="a complete realized PnL signal cannot declare excluded disposals",
    ):
        RealizedPnLCompletenessV1(is_complete=True, excluded_disposals=(d,))


def test_realized_pnl_completeness_incomplete_without_exclusions_refused() -> None:
    with pytest.raises(
        ValidationError,
        match="an incomplete realized PnL signal must name the excluded disposals",
    ):
        RealizedPnLCompletenessV1(is_complete=False, excluded_disposals=())


def test_realized_pnl_completeness_incomplete_valid() -> None:
    d = _sample_disposal()
    signal = RealizedPnLCompletenessV1(is_complete=False, excluded_disposals=(d,))
    assert signal.is_complete is False
    assert signal.excluded_disposals == (d,)


def test_evaluation_summary_metrics_default_completeness() -> None:
    point = SessionEquityPointV1(
        session_index=0,
        session_key=SESSION_1,
        cash_balance=Decimal("1000"),
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal("1000"),
    )
    metrics = EvaluationSummaryMetricsV1(
        evaluated_session_count=1,
        initial_cash=Decimal("1000"),
        initial_net_asset_value=Decimal("1000"),
        ending_cash=Decimal("1000"),
        ending_net_asset_value=Decimal("1000"),
        net_profit_and_loss=Decimal("0"),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
        gross_traded_notional=Decimal("0"),
        committed_fill_count=0,
        equity_series=(point,),
    )
    assert metrics.realized_pnl_completeness.is_complete is True
    assert metrics.realized_pnl_completeness.excluded_disposals == ()
