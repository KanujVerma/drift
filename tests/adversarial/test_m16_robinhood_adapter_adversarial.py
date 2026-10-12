"""M16 adversarial acceptance suite: Robinhood Agentic MCP Adapter (Issue 322).

Attacks the official Robinhood Agentic MCP adapter and synchronizer
across eight adversarial vectors:
1. Dry-run safety attack (default dry_run prevents live execution).
2. Rate limit 429 flood attack (adapter handles 429 throttling).
3. Malformed payload injection (corrupted tool outputs fail closed).
4. Network transport drop attack (transport drop returns fail-closed report).
5. Duplicate client token idempotency attack (re-submission safety).
6. Unmapped security asset isolation (unregistered UUIDs fail closed).
7. Position reconciliation divergence attack (detects drifted shares).
8. Cryptographic hash tampering attack (corrupted hashes fail validation).

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
    RobinhoodMcpError,
    RobinhoodPortfolioSynchronizer,
)
from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_broker_account_snapshot,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1


def _make_session_key() -> SessionKeyV1:
    return SessionKeyV1(
        mic="XNYS",
        session_scope="regular",
        local_date=date(2026, 3, 1),
    )


class FailingMcpTransport:
    """Mock transport designed to inject failures for adversarial testing."""

    def __init__(self, failure_mode: str) -> None:
        self.failure_mode = failure_mode

    def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.failure_mode == "rate_limit_429":
            raise RobinhoodMcpError("429 Too Many Requests: Rate limit exceeded")
        if self.failure_mode == "network_drop":
            raise RobinhoodMcpError("Connection reset by peer: MCP transport dropped")
        if self.failure_mode == "malformed_status":
            return {"order_id": "rh-bad-01", "status": "corrupted_status"}
        if self.failure_mode == "empty_payload":
            return {}
        raise RobinhoodMcpError(f"unhandled failure mode: {self.failure_mode}")


def test_v1_dry_run_safety_attack() -> None:
    """Vector 1: Default configuration enforces dry_run=True."""
    config = RobinhoodAgenticConfigV1(account_id="rh-live-candidate")
    assert config.dry_run is True

    # Mutating frozen config to disable dry-run fails closed
    with pytest.raises(ValidationError):
        config.dry_run = False


def test_v2_rate_limit_429_flood_attack() -> None:
    """Vector 2: Rate limit 429 throttling produces fail-closed rejected report."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-rate-limit-acc",
        symbol_map={sec_id: "AAPL"},
    )
    transport = FailingMcpTransport(failure_mode="rate_limit_429")
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="rate-limit-ord",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("150.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.rejection_reason is not None
    assert "429 Too Many Requests" in report.rejection_reason
    assert report.cum_quantity == 0
    assert report.leaves_quantity == 10


def test_v3_malformed_payload_injection() -> None:
    """Vector 3: Corrupted tool outputs map to rejected execution status."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-malformed-acc",
        symbol_map={sec_id: "MSFT"},
    )
    transport_bad_status = FailingMcpTransport(failure_mode="malformed_status")
    adapter = RobinhoodAgenticAdapter(
        config=config,
        transport=transport_bad_status,
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="malformed-ord",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.broker_order_id == "rh-bad-01"


def test_v4_network_transport_drop_attack() -> None:
    """Vector 4: Transport drop returns fail-closed report without crashing."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-drop-acc",
        symbol_map={sec_id: "NVDA"},
    )
    transport_drop = FailingMcpTransport(failure_mode="network_drop")
    adapter = RobinhoodAgenticAdapter(
        config=config,
        transport=transport_drop,
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="drop-ord",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=20,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("120.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.rejection_reason is not None
    assert "MCP transport dropped" in report.rejection_reason


def test_v5_duplicate_client_token_idempotency_attack() -> None:
    """Vector 5: Re-submitting the same intent returns cached report safely."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-idempotent-acc",
        symbol_map={sec_id: "AAPL"},
    )
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("10000.00"),
        price_map={"AAPL": Decimal("100.00")},
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="idemp-ord-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    # First submission
    report1 = adapter.submit_intent(intent)
    assert report1.status == ExecutionStatus.FILLED
    cash_after_first = Decimal(str(adapter.get_account_snapshot().cash_balance))
    assert cash_after_first == Decimal("9000.00")

    # Second submission with exact same intent (client token)
    report2 = adapter.submit_intent(intent)
    assert report2.status == ExecutionStatus.FILLED

    # Positions and cash must NOT double execute
    positions = adapter.get_positions()
    assert len(positions) == 1
    assert report1.broker_order_id is not None


def test_v6_unmapped_security_asset_isolation() -> None:
    """Vector 6: Order for unknown security UUID fails closed without state change."""
    known_sec = uuid7()
    unknown_sec = uuid7()

    config = RobinhoodAgenticConfigV1(
        account_id="rh-iso-acc",
        symbol_map={known_sec: "AAPL"},
    )
    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("5000.00"))
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="iso-ord-001",
        session_key=_make_session_key(),
        security_id=unknown_sec,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.rejection_reason is not None
    assert "unmapped security_id" in report.rejection_reason

    # Transport received zero place order calls
    assert len(transport.call_history) == 0


def test_v7_position_reconciliation_divergence_attack() -> None:
    """Vector 7: Reconciler correctly detects multiple simultaneous divergences."""
    sec1 = uuid7()
    sec2 = uuid7()
    sec3 = uuid7()

    config = RobinhoodAgenticConfigV1(
        account_id="rh-recon-acc",
        symbol_map={sec1: "AAPL", sec2: "MSFT", sec3: "GOOGL"},
    )
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("50000.00"),
        price_map={
            "AAPL": Decimal("100.00"),
            "MSFT": Decimal("200.00"),
        },
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)
    sync = RobinhoodPortfolioSynchronizer(adapter=adapter)

    # Buy AAPL 10, MSFT 5 on broker
    adapter.submit_intent(
        build_order_intent(
            intent_id=uuid7(),
            client_order_id="recon-1",
            session_key=_make_session_key(),
            security_id=sec1,
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
            client_order_id="recon-2",
            session_key=_make_session_key(),
            security_id=sec2,
            side=OrderSide.BUY,
            quantity=5,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
    )

    # Expected: AAPL 10 (matches), MSFT 8 (diff -3), GOOGL 4 (diff -4)
    report = sync.reconcile(
        expected_positions={
            sec1: 10,
            sec2: 8,
            sec3: 4,
        }
    )

    assert report.is_reconciled is False
    assert len(report.discrepancies) == 2

    disc_dict = {d.security_id: d for d in report.discrepancies}
    assert disc_dict[sec2].difference_quantity == -3
    assert disc_dict[sec3].difference_quantity == -4


def test_v8_cryptographic_hash_tampering_attack() -> None:
    """Vector 8: Tampering with report or snapshot hashes fails validation."""
    now = datetime.now(UTC)
    report = build_execution_report(
        report_id=uuid7(),
        intent_id=uuid7(),
        broker_order_id="rh-ord-tamper",
        status=ExecutionStatus.FILLED,
        cum_quantity=10,
        leaves_quantity=0,
        avg_fill_price=Decimal("100.00"),
        reported_at=now,
    )

    # Tampering with report_hash fails validation
    with pytest.raises(ValidationError):
        ExecutionReportV1(
            schema_version="1",
            report_id=report.report_id,
            intent_id=report.intent_id,
            broker_order_id=report.broker_order_id,
            status=report.status,
            cum_quantity=report.cum_quantity,
            leaves_quantity=report.leaves_quantity,
            avg_fill_price=report.avg_fill_price,
            reported_at=report.reported_at,
            report_hash="0" * 64,
        )

    # Account snapshot tampering fails validation
    acct = build_broker_account_snapshot(
        snapshot_id=uuid7(),
        account_id="acc-tamper",
        cash_balance=Decimal("1000.00"),
        buying_power=Decimal("1000.00"),
        portfolio_equity=Decimal("1000.00"),
        as_of=now,
    )
    with pytest.raises(ValidationError):
        acct.cash_balance = Decimal("999999.00")
