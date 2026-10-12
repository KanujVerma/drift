"""Unit tests for BrokerNeutralExecutionRouter (M14-4)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest

from drift.domain.evaluator_portfolio import (
    PortfolioStateV2,
    SecurityHoldingV2,
)
from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import (
    BrokerNeutralExecutionRouter,
    DuplicateClientOrderIdError,
    UnknownIntentError,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def _make_router(
    tmp_path: Path,
) -> tuple[
    BrokerNeutralExecutionRouter, MockBrokerAdapter, PersistentOrderIntentJournal
]:
    db_path = tmp_path / "intent_journal.db"
    journal = PersistentOrderIntentJournal(db_path)
    adapter = MockBrokerAdapter(
        initial_cash=Decimal("50000"), default_fee=Decimal("1.50")
    )
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    return router, adapter, journal


def test_route_intent_new_submission(tmp_path: Path) -> None:
    """Verifies fresh order submission is journaled, executed, and reported."""
    router, adapter, journal = _make_router(tmp_path)
    sec_id = uuid7()
    adapter.set_price(sec_id, Decimal("150.00"))

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="order-alpha-001",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("150.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    report = router.route_intent(intent)
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 10
    assert report.avg_fill_price == Decimal("150.00")
    assert report.fee_amount == Decimal("1.50")

    # Verify journaled intent and report
    stored_intent = journal.get_intent(intent.intent_id)
    assert stored_intent is not None
    assert stored_intent.client_order_id == "order-alpha-001"

    stored_rep = journal.get_execution_report(report.report_id)
    assert stored_rep is not None
    assert stored_rep.cum_quantity == 10

    # Verify adapter state
    # 50000 - (10 * 150 + 1.50) = 50000 - 1501.50 = 48498.50
    assert adapter.cash == Decimal("48498.50")


def test_route_intent_idempotent_replay(tmp_path: Path) -> None:
    """Verifies idempotent replay returns report without duplicate execution."""
    router, adapter, journal = _make_router(tmp_path)
    sec_id = uuid7()
    adapter.set_price(sec_id, Decimal("100.00"))

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="order-replay-001",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
    )

    first_report = router.route_intent(intent)
    assert first_report.status == ExecutionStatus.FILLED
    cash_after_first = adapter.cash

    # Replay same intent
    second_report = router.route_intent(intent)
    assert second_report.report_id == first_report.report_id
    assert second_report.cum_quantity == 5
    # Adapter cash must not have been deducted twice
    assert adapter.cash == cash_after_first


def test_route_intent_duplicate_client_order_id_rejected(tmp_path: Path) -> None:
    """Verifies reusing client_order_id raises DuplicateClientOrderIdError."""
    router, adapter, journal = _make_router(tmp_path)
    sec_id = uuid7()

    intent1 = build_order_intent(
        intent_id=uuid7(),
        client_order_id="shared-client-id-01",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
    )
    router.route_intent(intent1)

    # Different quantity, same client_order_id
    intent2 = build_order_intent(
        intent_id=uuid7(),
        client_order_id="shared-client-id-01",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
    )

    with pytest.raises(
        DuplicateClientOrderIdError, match="already exists with different intent"
    ):
        router.route_intent(intent2)


def test_cancel_intent_workflow(tmp_path: Path) -> None:
    """Verifies cancellation workflow and unknown intent rejection."""
    router, adapter, journal = _make_router(tmp_path)
    sec_id = uuid7()

    # Canceling an unknown intent raises UnknownIntentError
    unknown_id = uuid7()
    with pytest.raises(UnknownIntentError, match="not found in journal"):
        router.cancel_intent(unknown_id)

    # Route an intent without auto-fill
    adapter._auto_fill = False
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="order-cancel-001",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=20,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("120.00"),
        time_in_force=TimeInForce.GTC,
        created_at=NOW,
    )
    initial_rep = router.route_intent(intent)
    assert initial_rep.status == ExecutionStatus.ACKNOWLEDGED

    cancel_rep = router.cancel_intent(intent.intent_id)
    assert cancel_rep.status == ExecutionStatus.CANCELED

    # Check journal has both reports
    reports = journal.list_execution_reports_for_intent(intent.intent_id)
    assert len(reports) == 2
    assert reports[0].status == ExecutionStatus.ACKNOWLEDGED
    assert reports[1].status == ExecutionStatus.CANCELED


def test_position_reconciliation(tmp_path: Path) -> None:
    """Verifies position reconciliation detects both matches and discrepancies."""
    router, adapter, journal = _make_router(tmp_path)
    sec1 = uuid7()
    sec2 = uuid7()
    adapter.set_price(sec1, Decimal("100.00"))
    adapter.set_price(sec2, Decimal("50.00"))

    # Buy 10 units of sec1
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="pos-test-1",
        session_key=KEY1,
        security_id=sec1,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
    router.route_intent(intent)

    # State matching sec1 with 10 units
    matched_state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="a" * 64,
        session_key=KEY1,
        cash_balance=Decimal("48998.50"),
        holdings=(
            SecurityHoldingV2(
                security_id=sec1,
                quantity=10,
                basis_status="known",
                cost_basis=Decimal("1000.00"),
            ),
        ),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal("48998.50"),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("1.50"),
    )

    assert router.reconcile_positions(matched_state) is True
    assert router.get_position_discrepancies(matched_state) == ()

    # Mismatched quantity state (holding 15 instead of 10)
    mismatched_state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="a" * 64,
        session_key=KEY1,
        cash_balance=Decimal("48998.50"),
        holdings=(
            SecurityHoldingV2(
                security_id=sec1,
                quantity=15,
                basis_status="known",
                cost_basis=Decimal("1500.00"),
            ),
        ),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal("48998.50"),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("1.50"),
    )

    assert router.reconcile_positions(mismatched_state) is False
    discrepancies = router.get_position_discrepancies(mismatched_state)
    assert len(discrepancies) == 1
    assert "broker held 10, portfolio held 15" in discrepancies[0]
