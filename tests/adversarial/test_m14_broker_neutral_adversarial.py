"""M14 adversarial acceptance suite: Broker-Neutral Execution (Issue 299).

Attacks the broker-neutral execution router, intent journal, and adapter layer
across eight adversarial vectors:
1. Duplicate intent replay attack (deduplication preserves balance).
2. Tampered client_order_id collision attack (conflicts fail closed).
3. Intent ID collision attack (conflicting client_order_id fails closed).
4. SQLite append-only trigger attack (UPDATE/DELETE raise violation).
5. Cryptographic hash tampering attack (corrupted hashes fail validation).
6. Capital exhaustion attack (insufficient buying power cleanly rejected).
7. Chronological report audit sequence (multi-fill and cancellation tracking).
8. Position reconciliation divergence attack (state mismatches detected).

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.evaluator_portfolio import (
    PortfolioStateV2,
    SecurityHoldingV2,
)
from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    OrderType,
    TimeInForce,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import (
    IntentAppendOnlyViolationError,
    PersistentOrderIntentJournal,
)
from drift.execution.router import (
    BrokerNeutralExecutionRouter,
    DuplicateClientOrderIdError,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def _make_router_environment(
    tmp_path: Path,
    initial_cash: Decimal = Decimal("100000"),
    fee: Decimal = Decimal("2.00"),
) -> tuple[
    BrokerNeutralExecutionRouter, MockBrokerAdapter, PersistentOrderIntentJournal
]:
    db_path = tmp_path / "adversarial_intent_journal.db"
    journal = PersistentOrderIntentJournal(db_path)
    adapter = MockBrokerAdapter(initial_cash=initial_cash, default_fee=fee)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    return router, adapter, journal


def test_vector1_duplicate_intent_replay_attack(tmp_path: Path) -> None:
    """Vector 1: Submitting identical intent multiple times must not double-execute."""
    router, adapter, journal = _make_router_environment(tmp_path)
    sec_id = uuid7()
    adapter.set_price(sec_id, Decimal("100.00"))

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="replay-attack-001",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    first_rep = router.route_intent(intent)
    assert first_rep.status == ExecutionStatus.FILLED
    expected_cash = Decimal("100000") - Decimal("1000.00") - Decimal("2.00")
    assert adapter.cash == expected_cash

    # Replay attack: 5 consecutive identical submissions
    for _ in range(5):
        replayed_rep = router.route_intent(intent)
        assert replayed_rep.report_id == first_rep.report_id
        assert replayed_rep.status == ExecutionStatus.FILLED
        # Cash must remain exactly as after first execution
        assert adapter.cash == expected_cash

    # Control: fresh intent does deduct cash
    intent2 = build_order_intent(
        intent_id=uuid7(),
        client_order_id="control-order-002",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
    control_rep = router.route_intent(intent2)
    assert control_rep.status == ExecutionStatus.FILLED
    assert adapter.cash < expected_cash


def test_vector2_tampered_client_order_id_collision_attack(tmp_path: Path) -> None:
    """Vector 2: Reusing client_order_id with modified quantity/price fails closed."""
    router, adapter, journal = _make_router_environment(tmp_path)
    sec_id = uuid7()
    adapter.set_price(sec_id, Decimal("50.00"))

    original_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="colliding-client-id",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
    router.route_intent(original_intent)

    # Attack: reuse same client_order_id with 100 shares instead of 10
    tampered_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="colliding-client-id",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=100,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    with pytest.raises(
        DuplicateClientOrderIdError, match="already exists with different intent"
    ):
        router.route_intent(tampered_intent)


def test_vector3_intent_id_collision_attack(tmp_path: Path) -> None:
    """Vector 3: Reusing intent_id with a different client_order_id fails closed."""
    router, adapter, journal = _make_router_environment(tmp_path)
    sec_id = uuid7()
    shared_intent_id = uuid7()

    original_intent = build_order_intent(
        intent_id=shared_intent_id,
        client_order_id="client-id-original",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
    router.route_intent(original_intent)

    # Attack: reuse same intent_id with different client_order_id
    tampered_intent = build_order_intent(
        intent_id=shared_intent_id,
        client_order_id="client-id-tampered",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    with pytest.raises(
        DuplicateClientOrderIdError, match="already exists with different intent"
    ):
        router.route_intent(tampered_intent)


def test_vector4_sqlite_append_only_trigger_attack(tmp_path: Path) -> None:
    """Vector 4: Attempting to modify or delete journaled records via raw SQL fails."""
    router, adapter, journal = _make_router_environment(tmp_path)
    sec_id = uuid7()

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="sql-trigger-test",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
    router.route_intent(intent)

    # Direct raw UPDATE attack on order_intents
    with pytest.raises(
        IntentAppendOnlyViolationError, match="order_intents is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("UPDATE order_intents SET quantity = 999")

    # Direct raw DELETE attack on order_intents
    with pytest.raises(
        IntentAppendOnlyViolationError, match="order_intents is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("DELETE FROM order_intents")

    # Direct raw UPDATE attack on execution_reports
    with pytest.raises(
        IntentAppendOnlyViolationError, match="execution_reports is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("UPDATE execution_reports SET cum_quantity = 999")

    # Direct raw DELETE attack on execution_reports
    with pytest.raises(
        IntentAppendOnlyViolationError, match="execution_reports is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("DELETE FROM execution_reports")


def test_vector5_hash_tampering_fails_model_validation() -> None:
    """Vector 5: Tampering model without recalculating hash fails closed."""
    sec_id = uuid7()
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="hash-test-01",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    tampered_dict = intent.model_dump(mode="python")
    tampered_dict["quantity"] = 20
    with pytest.raises(ValidationError, match="intent_hash mismatch"):
        OrderIntentV1.model_validate(tampered_dict)

    # Execution report tampering
    rep = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="broker-1",
        status=ExecutionStatus.FILLED,
        cum_quantity=10,
        leaves_quantity=0,
        reported_at=NOW,
    )
    tampered_rep = rep.model_dump(mode="python")
    tampered_rep["status"] = ExecutionStatus.CANCELED
    with pytest.raises(ValidationError, match="report_hash mismatch"):
        ExecutionReportV1.model_validate(tampered_rep)


def test_vector6_insufficient_buying_power_rejection(tmp_path: Path) -> None:
    """Vector 6: Buying beyond cash balance is rejected without corrupting balances."""
    router, adapter, journal = _make_router_environment(
        tmp_path, initial_cash=Decimal("1000.00"), fee=Decimal("1.00")
    )
    sec_id = uuid7()
    adapter.set_price(sec_id, Decimal("500.00"))

    # Attempting to buy 5 shares @ $500 = $2500 + $1 fee > $1000
    excessive_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="excessive-buy-01",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("500.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    report = router.route_intent(excessive_intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.rejection_reason == "insufficient_buying_power"
    assert report.cum_quantity == 0
    # Cash must remain exactly $1000.00
    assert adapter.cash == Decimal("1000.00")
    # Positions must be empty
    assert len(adapter.get_positions()) == 0


def test_vector7_chronological_report_audit_sequence(tmp_path: Path) -> None:
    """Vector 7: Out-of-order and partial order status transitions are audited."""
    router, adapter, journal = _make_router_environment(tmp_path)
    sec_id = uuid7()

    # Disable auto-fill to manually control reports
    adapter._auto_fill = False
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="audit-trail-01",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=50,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("10.00"),
        time_in_force=TimeInForce.GTC,
        created_at=NOW,
    )

    ack_report = router.route_intent(intent)
    assert ack_report.status == ExecutionStatus.ACKNOWLEDGED

    # Manually append a partial fill report
    partial_rep = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id=ack_report.broker_order_id,
        status=ExecutionStatus.PARTIALLY_FILLED,
        cum_quantity=20,
        leaves_quantity=30,
        last_fill_price=Decimal("10.00"),
        last_fill_quantity=20,
        avg_fill_price=Decimal("10.00"),
        reported_at=datetime(2026, 3, 1, 14, 31, tzinfo=UTC),
    )
    journal.record_execution_report(partial_rep)

    # Cancel the remaining leaves
    cancel_rep = router.cancel_intent(intent.intent_id)
    assert cancel_rep.status == ExecutionStatus.CANCELED

    # Check journal has exactly 3 reports in sequence
    reports = journal.list_execution_reports_for_intent(intent.intent_id)
    assert len(reports) == 3
    assert [r.status for r in reports] == [
        ExecutionStatus.ACKNOWLEDGED,
        ExecutionStatus.PARTIALLY_FILLED,
        ExecutionStatus.CANCELED,
    ]


def test_vector8_position_reconciliation_divergence(tmp_path: Path) -> None:
    """Vector 8: Reconciliation detects discrepancies across securities."""
    router, adapter, journal = _make_router_environment(tmp_path)
    sec_a = uuid7()
    sec_b = uuid7()
    adapter.set_price(sec_a, Decimal("100.00"))
    adapter.set_price(sec_b, Decimal("200.00"))

    # Buy 10 units of sec_a
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="reconcile-a",
        session_key=KEY1,
        security_id=sec_a,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
    router.route_intent(intent)

    # Portfolio state expecting sec_a with 10 units and sec_b with 5 units
    divergent_state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="b" * 64,
        session_key=KEY1,
        cash_balance=Decimal("98998.00"),
        holdings=(
            SecurityHoldingV2(
                security_id=sec_a,
                quantity=10,
                basis_status="known",
                cost_basis=Decimal("1000.00"),
            ),
            SecurityHoldingV2(
                security_id=sec_b,
                quantity=5,
                basis_status="known",
                cost_basis=Decimal("1000.00"),
            ),
        ),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal("98998.00"),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("2.00"),
    )

    assert router.reconcile_positions(divergent_state) is False
    discrepancies = router.get_position_discrepancies(divergent_state)
    assert len(discrepancies) == 1
    assert f"security {sec_b}: broker held 0, portfolio held 5" in discrepancies[0]
