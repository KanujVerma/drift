"""Unit tests for Canary domain models, policy, and settlement reports (M17-1)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.canary import (
    CANARY_SCHEMA_VERSION,
    CanaryEvaluationResultV1,
    CanaryPolicyV1,
    CanarySettlementReportV1,
    build_canary_settlement_report,
)


def test_canary_policy_defaults() -> None:
    """Policy initializes with safe defaults and fail-closed authorization."""
    policy = CanaryPolicyV1()
    assert policy.schema_version == CANARY_SCHEMA_VERSION
    assert policy.canary_authorized is False
    assert policy.max_order_notional == Decimal("5.00")
    assert policy.max_cumulative_notional == Decimal("25.00")
    assert policy.max_order_quantity == 1
    assert policy.whitelisted_symbols == frozenset()
    assert policy.max_slippage_bps == 50


def test_canary_policy_custom_and_immutability() -> None:
    """Policy accepts valid custom parameters and enforces immutability."""
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_notional=Decimal("10.00"),
        max_cumulative_notional=Decimal("50.00"),
        max_order_quantity=2,
        whitelisted_symbols=frozenset({"AAPL", "MSFT"}),
        max_slippage_bps=25,
    )
    assert policy.canary_authorized is True
    assert policy.whitelisted_symbols == frozenset({"AAPL", "MSFT"})

    with pytest.raises(ValidationError):
        policy.canary_authorized = False


def test_canary_policy_validations() -> None:
    """Policy rejects invalid bounds."""
    # Zero or negative max_order_notional
    with pytest.raises(ValidationError):
        CanaryPolicyV1(max_order_notional=Decimal("0.00"))

    with pytest.raises(ValidationError):
        CanaryPolicyV1(max_order_notional=Decimal("-5.00"))

    # Cumulative < order notional
    with pytest.raises(ValidationError):
        CanaryPolicyV1(
            max_order_notional=Decimal("10.00"),
            max_cumulative_notional=Decimal("5.00"),
        )

    # Quantity <= 0
    with pytest.raises(ValidationError):
        CanaryPolicyV1(max_order_quantity=0)

    # Negative slippage
    with pytest.raises(ValidationError):
        CanaryPolicyV1(max_slippage_bps=-1)


def test_canary_evaluation_result() -> None:
    """Evaluation result holds admission decisions and allocation metrics."""
    res_admitted = CanaryEvaluationResultV1(
        decision="admitted",
        order_notional=Decimal("3.50"),
        cumulative_allocated_notional=Decimal("7.00"),
    )
    assert res_admitted.decision == "admitted"
    assert res_admitted.refusal_reasons == ()

    res_refused = CanaryEvaluationResultV1(
        decision="refused",
        refusal_reasons=("canary_unauthorized", "exceeds_max_order_notional"),
        order_notional=Decimal("10.00"),
        cumulative_allocated_notional=Decimal("0.00"),
    )
    assert res_refused.decision == "refused"
    assert len(res_refused.refusal_reasons) == 2


def test_canary_settlement_report_builder_and_hash() -> None:
    """Settlement report builds with valid deterministic hash and immutability."""
    now = datetime.now(UTC)
    rep_id = uuid7()
    int_id = uuid7()

    report = build_canary_settlement_report(
        report_id=rep_id,
        intent_id=int_id,
        broker_order_id="rh-canary-001",
        is_settled=True,
        expected_notional=Decimal("4.50"),
        actual_fill_notional=Decimal("4.50"),
        fee_amount=Decimal("0.00"),
        cash_balance_delta=Decimal("-4.50"),
        reconciliation_difference=Decimal("0.00"),
        slippage_bps=Decimal("0.0"),
        evaluated_at=now,
    )

    assert report.report_id == rep_id
    assert report.intent_id == int_id
    assert report.is_settled is True
    assert len(report.report_hash) == 64

    # Tampered hash fails validation
    with pytest.raises(ValidationError):
        CanarySettlementReportV1(
            report_id=rep_id,
            intent_id=int_id,
            is_settled=True,
            expected_notional=Decimal("4.50"),
            actual_fill_notional=Decimal("4.50"),
            fee_amount=Decimal("0.00"),
            cash_balance_delta=Decimal("-4.50"),
            reconciliation_difference=Decimal("0.00"),
            slippage_bps=Decimal("0.0"),
            evaluated_at=now,
            report_hash="f" * 64,
        )
