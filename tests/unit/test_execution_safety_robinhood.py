"""Unit tests for Robinhood MCP adapter safety hardening (Issue #363, S3-S5).

Verifies fail-closed handling for:
- S3: Cancellation failure transport errors (prevent swallowed CANCELED status).
- S4: Submission timeouts and client_token reconciliation.
- S5: Unmapped positions quarantine (prevent UUIDv7 schema crash).
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid7

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
    RobinhoodMcpError,
)
from drift.domain.execution import (
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def _make_intent(
    *,
    sec_id: UUID,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 10,
    price: Decimal = Decimal("50.00"),
    client_order_id: str = "rh-safety-01",
) -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=client_order_id,
        session_key=KEY1,
        security_id=sec_id,
        side=side,
        quantity=quantity,
        order_type=OrderType.LIMIT,
        limit_price=price,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )


class CancellationFailingTransport(MockRobinhoodMcpTransport):
    """Simulates broker cancel failure while keeping order active."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cancel_should_fail = True

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool_name == "robinhood_cancel_order" and self.cancel_should_fail:
            raise RobinhoodMcpError("broker_cancel_rejected: order already in market")
        return super().call_tool(tool_name, arguments)


class SubmissionTimeoutTransport(MockRobinhoodMcpTransport):
    """Simulates place_order timeout while broker successfully receives order."""

    def __init__(self, *, place_should_time_out: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.place_should_time_out = place_should_time_out
        self.server_placed_order = True

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool_name == "robinhood_place_order" and self.place_should_time_out:
            if self.server_placed_order:
                # Broker creates order in its database, but network times out on reply
                super().call_tool(tool_name, arguments)
            raise RobinhoodMcpError("Request timed out after 30 seconds")
        return super().call_tool(tool_name, arguments)


def test_s3_cancel_failure_does_not_falsely_emit_canceled() -> None:
    """S3: Cancellation transport error must fail closed and preserve active status."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-s3-acc",
        symbol_map={sec_id: "AAPL"},
    )
    transport = CancellationFailingTransport(
        auto_fill=False,
        price_map={"AAPL": Decimal("50.00")},
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = _make_intent(sec_id=sec_id, quantity=10, client_order_id="s3-ord-01")
    submit_report = adapter.submit_intent(intent)
    assert submit_report.status == ExecutionStatus.ACKNOWLEDGED
    assert submit_report.leaves_quantity == 10

    # Attempt cancel; transport fails
    cancel_report = adapter.cancel_intent(intent.intent_id)

    # Must NOT be CANCELED with 0 leaves
    assert cancel_report.status != ExecutionStatus.CANCELED
    assert cancel_report.leaves_quantity == 10
    assert cancel_report.rejection_reason is not None
    assert "cancellation_failed" in cancel_report.rejection_reason


def test_s4_submission_timeout_reconciles_via_client_token() -> None:
    """S4: Order placed on broker during timeout is recovered via client_token."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-s4-acc",
        symbol_map={sec_id: "MSFT"},
    )
    # Server placed order before response timed out
    transport = SubmissionTimeoutTransport(
        place_should_time_out=True,
        auto_fill=True,
        price_map={"MSFT": Decimal("200.00")},
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = _make_intent(
        sec_id=sec_id, quantity=5, price=Decimal("200.00"), client_order_id="s4-ord-01"
    )

    # Submission timed out, but reconciliation finds the fill
    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 5
    assert report.broker_order_id is not None


def test_s4_submission_timeout_without_broker_order_fails_closed() -> None:
    """S4: Timeout without broker order fails closed with timeout classification."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-s4-acc2",
        symbol_map={sec_id: "MSFT"},
    )
    transport = SubmissionTimeoutTransport(
        place_should_time_out=True,
        auto_fill=False,
    )
    transport.server_placed_order = False  # Broker never created order
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = _make_intent(
        sec_id=sec_id, quantity=5, price=Decimal("200.00"), client_order_id="s4-ord-02"
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert "mcp_submission_timeout" in str(report.rejection_reason)


def test_s5_unmapped_positions_quarantined_without_schema_crash() -> None:
    """S5: Unmapped positions in Robinhood account are safely quarantined."""
    mapped_sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="rh-s5-acc",
        symbol_map={mapped_sec_id: "AAPL"},  # Only AAPL mapped; HOOD and SPY unmapped
    )
    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("5000.00"))
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    # Seed positions: 10 AAPL (mapped), 5 HOOD (unmapped), 2 SPY (unmapped)
    transport._positions["AAPL"] = {"quantity": 10, "cost_basis": Decimal("1500.00")}
    transport._positions["HOOD"] = {"quantity": 5, "cost_basis": Decimal("100.00")}
    transport._positions["SPY"] = {"quantity": 2, "cost_basis": Decimal("800.00")}

    # Querying positions must NOT crash with ValidationError (UUIDv7 mismatch)
    positions = adapter.get_positions()

    # Only mapped AAPL position should be returned
    assert len(positions) == 1
    assert positions[0].security_id == mapped_sec_id
    assert positions[0].quantity == 10

    # Unmapped HOOD and SPY must be recorded in quarantined_symbols
    assert "HOOD" in adapter.quarantined_symbols
    assert "SPY" in adapter.quarantined_symbols
    assert "AAPL" not in adapter.quarantined_symbols
