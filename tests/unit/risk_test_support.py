"""Offline order-intent fixtures for risk checks; no broker or dispatch."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid7

from drift.domain.execution import (
    OrderIntentV1,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def make_intent(
    *,
    sec_id: UUID,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 10,
    price: Decimal = Decimal("50.00"),
    order_type: OrderType = OrderType.LIMIT,
    client_order_id: str = "safety-intent-01",
) -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=client_order_id,
        session_key=KEY1,
        security_id=sec_id,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=price if order_type == OrderType.LIMIT else None,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
