"""Unit tests for Robinhood MCP adapter safety hardening (Issue #363, S3-S5).

Verifies fail-closed handling for:
- S3: Cancellation failure transport errors (prevent swallowed CANCELED status).
- S4: Submission timeouts and client_token reconciliation.
- S5: Unmapped positions quarantine (prevent UUIDv7 schema crash).
"""

import socket
import traceback
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid7

import pytest

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
from drift.errors import DriftError
from drift.execution.adapter import ExecutionOutcomeUnknown

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network access forbidden in adapter tests")

    monkeypatch.setattr(socket, "socket", refuse)


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


def test_ambiguous_submission_never_returns_rejected() -> None:
    sec_id = uuid7()

    class LostResponse(SubmissionTimeoutTransport):
        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            if tool_name == "robinhood_get_order_by_client_token":
                raise RobinhoodMcpError("lookup unavailable")
            return super().call_tool(tool_name, arguments)

    transport = LostResponse(auto_fill=False)
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=transport,
    )
    intent = _make_intent(sec_id=sec_id)
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.submit_intent(intent)
    assert len(transport._orders) == 1
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.submit_intent(intent)
    assert len(transport._orders) == 1


@pytest.mark.parametrize("mode", ["submit", "lookup", "cancel", "status"])
def test_native_timeout_is_redacted_and_keeps_same_instance_marker(mode: str) -> None:
    sec_id = uuid7()

    class NativeTimeout(MockRobinhoodMcpTransport):
        def __init__(self) -> None:
            super().__init__(auto_fill=False)
            self.calls: list[str] = []

        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            self.calls.append(tool_name)
            if tool_name == "robinhood_place_order" and mode in ("submit", "lookup"):
                super().call_tool(tool_name, arguments)
                if mode == "lookup":
                    raise RobinhoodMcpError("synthetic detail")
                raise TimeoutError("synthetic sensitive detail")
            if (
                (
                    mode == "lookup"
                    and tool_name == "robinhood_get_order_by_client_token"
                )
                or (mode == "cancel" and tool_name == "robinhood_cancel_order")
                or (mode == "status" and tool_name == "robinhood_get_order")
            ):
                raise TimeoutError("synthetic sensitive detail")
            return super().call_tool(tool_name, arguments)

    transport = NativeTimeout()
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=transport,
    )
    intent = _make_intent(sec_id=sec_id)
    if mode in ("cancel", "status"):
        assert adapter.submit_intent(intent).status == ExecutionStatus.ACKNOWLEDGED
    with pytest.raises(
        ExecutionOutcomeUnknown, match="^execution outcome unknown$"
    ) as caught:
        if mode in ("submit", "lookup"):
            adapter.submit_intent(intent)
        elif mode == "cancel":
            adapter.cancel_intent(intent.intent_id)
        else:
            adapter.get_intent_status(intent.intent_id)
    formatted_error = "".join(traceback.format_exception(caught.value))
    assert "synthetic sensitive detail" not in formatted_error
    assert "synthetic detail" not in formatted_error
    calls = list(transport.calls)
    with pytest.raises(ExecutionOutcomeUnknown, match="^execution outcome unknown$"):
        adapter.submit_intent(intent)
    assert transport.calls == calls
    assert len(transport._orders) == 1


def test_interrupted_submission_is_not_resent_by_same_adapter() -> None:
    sec_id = uuid7()

    class Interrupted(MockRobinhoodMcpTransport):
        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            if tool_name == "robinhood_place_order":
                super().call_tool(tool_name, arguments)
                raise KeyboardInterrupt
            return super().call_tool(tool_name, arguments)

    transport = Interrupted(auto_fill=False)
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=transport,
    )
    intent = _make_intent(sec_id=sec_id)
    with pytest.raises(KeyboardInterrupt):
        adapter.submit_intent(intent)
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.submit_intent(intent)
    assert len(transport._orders) == 1


def test_unrecognized_submit_status_never_returns_rejected() -> None:
    sec_id = uuid7()

    class UnknownStatus(MockRobinhoodMcpTransport):
        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            raw = super().call_tool(tool_name, arguments)
            if tool_name == "robinhood_place_order":
                return {**raw, "status": "not_a_known_status"}
            return raw

    transport = UnknownStatus(auto_fill=False)
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=transport,
    )
    intent = _make_intent(sec_id=sec_id)
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.submit_intent(intent)
    assert len(transport._orders) == 1
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.submit_intent(intent)
    assert len(transport._orders) == 1


def test_conflicting_order_response_does_not_establish_rejection() -> None:
    sec_id = uuid7()

    class ConflictingResponse(MockRobinhoodMcpTransport):
        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            raw = super().call_tool(tool_name, arguments)
            if tool_name == "robinhood_place_order":
                return {**raw, "status": "rejected", "symbol": "WRONG"}
            return raw

    transport = ConflictingResponse(auto_fill=False)
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=transport,
    )
    intent = _make_intent(sec_id=sec_id)
    with pytest.raises(ExecutionOutcomeUnknown, match="execution outcome unknown"):
        adapter.submit_intent(intent)
    assert len(transport._orders) == 1


@pytest.mark.parametrize("mode", ["unknown_status", "failed"])
def test_ambiguous_status_never_returns_cached_report(mode: str) -> None:
    sec_id = uuid7()

    class UncertainStatus(MockRobinhoodMcpTransport):
        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            if tool_name == "robinhood_get_order":
                if mode == "failed":
                    raise RobinhoodMcpError("unavailable")
                return {**super().call_tool(tool_name, arguments), "status": "mystery"}
            return super().call_tool(tool_name, arguments)

    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=UncertainStatus(auto_fill=False),
    )
    intent = _make_intent(sec_id=sec_id)
    assert adapter.submit_intent(intent).status == ExecutionStatus.ACKNOWLEDGED
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.get_intent_status(intent.intent_id)
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.cancel_intent(intent.intent_id)


@pytest.mark.parametrize(
    ("status", "cumulative", "expected"),
    [
        ("canceled", 0, None),
        ("filled", 5, None),
        ("canceled", 4, ExecutionStatus.CANCELED),
        ("filled", 10, ExecutionStatus.FILLED),
    ],
)
def test_cancellation_preserves_observed_fills_and_terminal_truth(
    status: str, cumulative: int, expected: ExecutionStatus | None
) -> None:
    sec_id = uuid7()

    class PartialThenCancel(MockRobinhoodMcpTransport):
        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            raw = super().call_tool(tool_name, arguments)
            if tool_name == "robinhood_get_order":
                return {
                    **raw,
                    "status": "partially_filled",
                    "cum_quantity": 4,
                    "avg_fill_price": "50.00",
                }
            if tool_name == "robinhood_cancel_order":
                return {
                    **raw,
                    "status": status,
                    "cum_quantity": cumulative,
                    "avg_fill_price": "50.00" if cumulative else None,
                }
            return raw

    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=PartialThenCancel(auto_fill=False),
    )
    intent = _make_intent(sec_id=sec_id)
    assert adapter.submit_intent(intent).status == ExecutionStatus.ACKNOWLEDGED
    before = adapter.get_intent_status(intent.intent_id)
    assert before is not None and before.cum_quantity == 4
    if expected is None:
        with pytest.raises(
            ExecutionOutcomeUnknown, match="^execution outcome unknown$"
        ):
            adapter.cancel_intent(intent.intent_id)
        with pytest.raises(ExecutionOutcomeUnknown):
            adapter.get_intent_status(intent.intent_id)
    else:
        report = adapter.cancel_intent(intent.intent_id)
        assert report.status == expected
        assert report.cum_quantity == cumulative
        assert report.leaves_quantity == 0


@pytest.mark.parametrize("mode", ["failed", "unconfirmed", "missing_order"])
def test_unconfirmed_cancellation_never_returns_canceled(mode: str) -> None:
    sec_id = uuid7()

    class UnconfirmedCancel(MockRobinhoodMcpTransport):
        def call_tool(
            self, tool_name: str, arguments: Mapping[str, Any]
        ) -> dict[str, Any]:
            if tool_name == "robinhood_cancel_order":
                if mode == "failed":
                    raise RobinhoodMcpError("cancel response lost")
                return self._handle_get_order(dict(arguments))
            return super().call_tool(tool_name, arguments)

    transport = UnconfirmedCancel(auto_fill=False)
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="fake", symbol_map={sec_id: "AAPL"}),
        transport=transport,
    )
    intent = _make_intent(sec_id=sec_id)
    assert adapter.submit_intent(intent).status == ExecutionStatus.ACKNOWLEDGED
    if mode == "missing_order":
        adapter._intent_to_broker_order.clear()
    with pytest.raises(DriftError, match="execution outcome unknown"):
        adapter.cancel_intent(intent.intent_id)


def test_s3_cancel_failure_does_not_falsely_emit_canceled() -> None:
    """S3: Cancellation failure cannot return a current V1 status."""
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

    with pytest.raises(ExecutionOutcomeUnknown, match="execution outcome unknown"):
        adapter.cancel_intent(intent.intent_id)
    with pytest.raises(ExecutionOutcomeUnknown, match="execution outcome unknown"):
        adapter.get_intent_status(intent.intent_id)


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
    """S4: Empty lookup does not establish rejection or non-receipt."""
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

    with pytest.raises(ExecutionOutcomeUnknown, match="execution outcome unknown"):
        adapter.submit_intent(intent)
    with pytest.raises(ExecutionOutcomeUnknown, match="execution outcome unknown"):
        adapter.get_intent_status(intent.intent_id)


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
