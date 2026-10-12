"""Unit tests for Robinhood account and position synchronizer (M16-3)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    PositionDiscrepancyV1,
    ReconciliationReportV1,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
    RobinhoodPortfolioSynchronizer,
)
from drift.domain.execution import (
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1


def _make_session_key() -> SessionKeyV1:
    return SessionKeyV1(
        mic="XNYS",
        session_scope="regular",
        local_date=date(2026, 3, 1),
    )


def test_discrepancy_and_report_immutability() -> None:
    """PositionDiscrepancyV1 is frozen and immutable."""
    sec = uuid7()
    disc = PositionDiscrepancyV1(
        security_id=sec,
        symbol="AAPL",
        expected_quantity=10,
        actual_quantity=15,
        difference_quantity=5,
    )
    with pytest.raises(ValidationError):
        disc.actual_quantity = 20


def test_synchronizer_sync_account_and_positions() -> None:
    """Synchronizer delegates to adapter for account and position snapshots."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="sync-acc-01",
        symbol_map={sec_id: "AAPL"},
    )
    transport = MockRobinhoodMcpTransport(
        account_id="sync-acc-01",
        initial_cash=Decimal("20000.00"),
        price_map={"AAPL": Decimal("100.00")},
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)
    sync = RobinhoodPortfolioSynchronizer(adapter=adapter)

    # Place fill order
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cli-sync-01",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=50,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    adapter.submit_intent(intent)

    acct_snap = sync.sync_account()
    assert acct_snap.account_id == "sync-acc-01"
    assert Decimal(str(acct_snap.cash_balance)) == Decimal("15000.00")

    pos_snaps = sync.sync_positions()
    assert len(pos_snaps) == 1
    assert pos_snaps[0].security_id == sec_id
    assert pos_snaps[0].quantity == 50


def test_reconcile_perfect_match() -> None:
    """Reconciliation passes when expected internal holdings match broker positions."""
    sec_a = uuid7()
    sec_b = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="sync-acc-02",
        symbol_map={sec_a: "AAPL", sec_b: "MSFT"},
    )
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("50000.00"),
        price_map={"AAPL": Decimal("100.00"), "MSFT": Decimal("200.00")},
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)
    sync = RobinhoodPortfolioSynchronizer(adapter=adapter)

    adapter.submit_intent(
        build_order_intent(
            intent_id=uuid7(),
            client_order_id="ord-a",
            session_key=_make_session_key(),
            security_id=sec_a,
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
    )
    adapter.submit_intent(
        build_order_intent(
            intent_id=uuid7(),
            client_order_id="ord-b",
            session_key=_make_session_key(),
            security_id=sec_b,
            side=OrderSide.BUY,
            quantity=20,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
    )

    report = sync.reconcile(
        expected_positions={
            sec_a: 10,
            sec_b: 20,
        }
    )

    assert isinstance(report, ReconciliationReportV1)
    assert report.is_reconciled is True
    assert len(report.discrepancies) == 0
    assert len(report.position_snapshots) == 2


def test_reconcile_with_discrepancies() -> None:
    """Reconciliation identifies missing, extra, and quantity divergent positions."""
    sec_held = uuid7()
    sec_missing = uuid7()
    sec_extra = uuid7()

    config = RobinhoodAgenticConfigV1(
        account_id="sync-acc-03",
        symbol_map={
            sec_held: "AAPL",
            sec_missing: "GOOGL",
            sec_extra: "AMZN",
        },
    )
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("50000.00"),
        price_map={
            "AAPL": Decimal("100.00"),
            "AMZN": Decimal("150.00"),
        },
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)
    sync = RobinhoodPortfolioSynchronizer(adapter=adapter)

    # Buy AAPL 10 shares on broker
    adapter.submit_intent(
        build_order_intent(
            intent_id=uuid7(),
            client_order_id="ord-1",
            session_key=_make_session_key(),
            security_id=sec_held,
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
    )
    # Buy AMZN 5 shares on broker
    adapter.submit_intent(
        build_order_intent(
            intent_id=uuid7(),
            client_order_id="ord-2",
            session_key=_make_session_key(),
            security_id=sec_extra,
            side=OrderSide.BUY,
            quantity=5,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
    )

    # Expected internally:
    # AAPL: 8 shares (broker has 10 -> diff +2)
    # GOOGL: 12 shares (broker has 0 -> diff -12)
    # AMZN: 0 shares (broker has 5 -> diff +5)
    report = sync.reconcile(
        expected_positions={
            sec_held: 8,
            sec_missing: 12,
        }
    )

    assert report.is_reconciled is False
    assert len(report.discrepancies) == 3

    disc_by_id = {d.security_id: d for d in report.discrepancies}

    # AAPL
    d_held = disc_by_id[sec_held]
    assert d_held.symbol == "AAPL"
    assert d_held.expected_quantity == 8
    assert d_held.actual_quantity == 10
    assert d_held.difference_quantity == 2

    # GOOGL (missing at broker)
    d_miss = disc_by_id[sec_missing]
    assert d_miss.symbol == "GOOGL"
    assert d_miss.expected_quantity == 12
    assert d_miss.actual_quantity == 0
    assert d_miss.difference_quantity == -12

    # AMZN (extra at broker)
    d_extra = disc_by_id[sec_extra]
    assert d_extra.symbol == "AMZN"
    assert d_extra.expected_quantity == 0
    assert d_extra.actual_quantity == 5
    assert d_extra.difference_quantity == 5
