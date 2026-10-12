"""Broker-neutral domain models, order intents, and execution reports (M14-1).

Provides immutable domain models for vendor-neutral order intents, execution reports,
account snapshots, and position snapshots decoupling research from broker APIs.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_portfolio import (
    CanonicalMoney,
    canonical_money,
)
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

EXECUTION_SCHEMA_VERSION: Literal["1"] = "1"

ORDER_INTENT_PROFILE = "drift-order-intent-v1"
EXECUTION_REPORT_PROFILE = "drift-execution-report-v1"
BROKER_ACCOUNT_SNAPSHOT_PROFILE = "drift-broker-account-snapshot-v1"
BROKER_POSITION_SNAPSHOT_PROFILE = "drift-broker-position-snapshot-v1"

__all__ = [
    "EXECUTION_SCHEMA_VERSION",
    "BrokerAccountSnapshotV1",
    "BrokerPositionSnapshotV1",
    "ExecutionReportV1",
    "ExecutionStatus",
    "OrderIntentV1",
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "build_broker_account_snapshot",
    "build_broker_position_snapshot",
    "build_execution_report",
    "build_order_intent",
    "compute_broker_account_snapshot_hash",
    "compute_broker_position_snapshot_hash",
    "compute_execution_report_hash",
    "compute_order_intent_hash",
]


class OrderSide(StrEnum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Order pricing type."""

    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    """Order duration in force."""

    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"


class ExecutionStatus(StrEnum):
    """Execution lifecycle status."""

    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# =========================================================================
# Content Hashing Functions
# =========================================================================


def compute_order_intent_hash(
    *,
    schema_version: str,
    intent_id: UUID,
    client_order_id: str,
    session_key: SessionKeyV1,
    security_id: UUID,
    side: str,
    quantity: int,
    order_type: str,
    limit_price: Decimal | None,
    time_in_force: str,
    created_at: datetime,
) -> SHA256Hash:
    """Compute deterministic SHA-256 hash for an order intent."""
    payload: dict[str, Any] = {
        "profile": ORDER_INTENT_PROFILE,
        "schema_version": schema_version,
        "intent_id": str(intent_id),
        "client_order_id": client_order_id,
        "session_key": session_key.model_dump(mode="python"),
        "security_id": str(security_id),
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "limit_price": str(limit_price) if limit_price is not None else None,
        "time_in_force": time_in_force,
        "created_at": created_at.isoformat(),
    }
    return content_hash(payload)


def compute_execution_report_hash(
    *,
    schema_version: str,
    report_id: UUID,
    intent_id: UUID,
    broker_order_id: str | None,
    status: str,
    cum_quantity: int,
    leaves_quantity: int,
    last_fill_price: Decimal | None,
    last_fill_quantity: int | None,
    avg_fill_price: Decimal | None,
    fee_amount: Decimal,
    rejection_reason: str | None,
    reported_at: datetime,
) -> SHA256Hash:
    """Compute deterministic SHA-256 hash for an execution report."""
    payload: dict[str, Any] = {
        "profile": EXECUTION_REPORT_PROFILE,
        "schema_version": schema_version,
        "report_id": str(report_id),
        "intent_id": str(intent_id),
        "broker_order_id": broker_order_id,
        "status": status,
        "cum_quantity": cum_quantity,
        "leaves_quantity": leaves_quantity,
        "last_fill_price": str(last_fill_price)
        if last_fill_price is not None
        else None,
        "last_fill_quantity": last_fill_quantity,
        "avg_fill_price": str(avg_fill_price) if avg_fill_price is not None else None,
        "fee_amount": str(fee_amount),
        "rejection_reason": rejection_reason,
        "reported_at": reported_at.isoformat(),
    }
    return content_hash(payload)


def compute_broker_account_snapshot_hash(
    *,
    schema_version: str,
    snapshot_id: UUID,
    account_id: str,
    cash_balance: Decimal,
    buying_power: Decimal,
    portfolio_equity: Decimal,
    as_of: datetime,
) -> SHA256Hash:
    """Compute deterministic SHA-256 hash for a broker account snapshot."""
    payload: dict[str, Any] = {
        "profile": BROKER_ACCOUNT_SNAPSHOT_PROFILE,
        "schema_version": schema_version,
        "snapshot_id": str(snapshot_id),
        "account_id": account_id,
        "cash_balance": str(cash_balance),
        "buying_power": str(buying_power),
        "portfolio_equity": str(portfolio_equity),
        "as_of": as_of.isoformat(),
    }
    return content_hash(payload)


def compute_broker_position_snapshot_hash(
    *,
    schema_version: str,
    snapshot_id: UUID,
    security_id: UUID,
    quantity: int,
    cost_basis: Decimal,
    current_price: Decimal | None,
    market_value: Decimal | None,
    as_of: datetime,
) -> SHA256Hash:
    """Compute deterministic SHA-256 hash for a broker position snapshot."""
    payload: dict[str, Any] = {
        "profile": BROKER_POSITION_SNAPSHOT_PROFILE,
        "schema_version": schema_version,
        "snapshot_id": str(snapshot_id),
        "security_id": str(security_id),
        "quantity": quantity,
        "cost_basis": str(cost_basis),
        "current_price": str(current_price) if current_price is not None else None,
        "market_value": str(market_value) if market_value is not None else None,
        "as_of": as_of.isoformat(),
    }
    return content_hash(payload)


# =========================================================================
# Domain Models
# =========================================================================


class OrderIntentV1(FrozenModel):
    """Vendor-neutral representation of an outbound order desire."""

    schema_version: Literal["1"] = EXECUTION_SCHEMA_VERSION
    intent_id: UUID7
    client_order_id: NonBlankStr
    session_key: SessionKeyV1
    security_id: UUID7
    side: OrderSide
    quantity: int = Field(gt=0)
    order_type: OrderType
    limit_price: CanonicalMoney | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    created_at: UTCDateTime
    intent_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_pricing_and_hash(self) -> Self:
        if self.order_type == OrderType.LIMIT:
            if self.limit_price is None or self.limit_price <= Decimal("0"):
                raise ValueError("limit order requires positive limit_price")
        elif self.limit_price is not None:
            raise ValueError("market order must not specify limit_price")

        expected_hash = compute_order_intent_hash(
            schema_version=self.schema_version,
            intent_id=self.intent_id,
            client_order_id=self.client_order_id,
            session_key=self.session_key,
            security_id=self.security_id,
            side=self.side.value,
            quantity=self.quantity,
            order_type=self.order_type.value,
            limit_price=self.limit_price,
            time_in_force=self.time_in_force.value,
            created_at=self.created_at,
        )
        if self.intent_hash != expected_hash:
            raise ValueError(
                f"intent_hash mismatch: expected {expected_hash}, "
                f"got {self.intent_hash}"
            )
        return self


class ExecutionReportV1(FrozenModel):
    """Vendor-neutral execution report tracking order lifecycle events."""

    schema_version: Literal["1"] = EXECUTION_SCHEMA_VERSION
    report_id: UUID7
    intent_id: UUID7
    broker_order_id: NonBlankStr | None = None
    status: ExecutionStatus
    cum_quantity: int = Field(ge=0)
    leaves_quantity: int = Field(ge=0)
    last_fill_price: CanonicalMoney | None = None
    last_fill_quantity: int | None = Field(default=None, ge=1)
    avg_fill_price: CanonicalMoney | None = None
    fee_amount: CanonicalMoney = Decimal("0")
    rejection_reason: NonBlankStr | None = None
    reported_at: UTCDateTime
    report_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.fee_amount < Decimal("0"):
            raise ValueError("fee_amount must be non-negative")

        if self.status in (
            ExecutionStatus.PARTIALLY_FILLED,
            ExecutionStatus.FILLED,
        ):
            if self.cum_quantity == 0:
                raise ValueError("filled execution report must have cum_quantity > 0")

        if self.status == ExecutionStatus.REJECTED and self.rejection_reason is None:
            raise ValueError("rejected execution report requires rejection_reason")

        expected_hash = compute_execution_report_hash(
            schema_version=self.schema_version,
            report_id=self.report_id,
            intent_id=self.intent_id,
            broker_order_id=self.broker_order_id,
            status=self.status.value,
            cum_quantity=self.cum_quantity,
            leaves_quantity=self.leaves_quantity,
            last_fill_price=self.last_fill_price,
            last_fill_quantity=self.last_fill_quantity,
            avg_fill_price=self.avg_fill_price,
            fee_amount=self.fee_amount,
            rejection_reason=self.rejection_reason,
            reported_at=self.reported_at,
        )
        if self.report_hash != expected_hash:
            raise ValueError(
                f"report_hash mismatch: expected {expected_hash}, "
                f"got {self.report_hash}"
            )
        return self


class BrokerAccountSnapshotV1(FrozenModel):
    """Point-in-time snapshot of broker account balances and buying power."""

    schema_version: Literal["1"] = EXECUTION_SCHEMA_VERSION
    snapshot_id: UUID7
    account_id: NonBlankStr
    cash_balance: CanonicalMoney
    buying_power: CanonicalMoney
    portfolio_equity: CanonicalMoney
    as_of: UTCDateTime
    snapshot_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.cash_balance < Decimal("0"):
            raise ValueError("cash_balance must be non-negative")
        if self.buying_power < Decimal("0"):
            raise ValueError("buying_power must be non-negative")
        if self.portfolio_equity < Decimal("0"):
            raise ValueError("portfolio_equity must be non-negative")

        expected_hash = compute_broker_account_snapshot_hash(
            schema_version=self.schema_version,
            snapshot_id=self.snapshot_id,
            account_id=self.account_id,
            cash_balance=self.cash_balance,
            buying_power=self.buying_power,
            portfolio_equity=self.portfolio_equity,
            as_of=self.as_of,
        )
        if self.snapshot_hash != expected_hash:
            raise ValueError(
                f"snapshot_hash mismatch: expected {expected_hash}, "
                f"got {self.snapshot_hash}"
            )
        return self


class BrokerPositionSnapshotV1(FrozenModel):
    """Point-in-time snapshot of a single held position reported by broker."""

    schema_version: Literal["1"] = EXECUTION_SCHEMA_VERSION
    snapshot_id: UUID7
    security_id: UUID7
    quantity: int = Field(ge=0)
    cost_basis: CanonicalMoney
    current_price: CanonicalMoney | None = None
    market_value: CanonicalMoney | None = None
    as_of: UTCDateTime
    snapshot_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_position(self) -> Self:
        if self.cost_basis < Decimal("0"):
            raise ValueError("cost_basis must be non-negative")
        if self.current_price is not None and self.current_price < Decimal("0"):
            raise ValueError("current_price must be non-negative")
        if self.market_value is not None and self.market_value < Decimal("0"):
            raise ValueError("market_value must be non-negative")

        expected_hash = compute_broker_position_snapshot_hash(
            schema_version=self.schema_version,
            snapshot_id=self.snapshot_id,
            security_id=self.security_id,
            quantity=self.quantity,
            cost_basis=self.cost_basis,
            current_price=self.current_price,
            market_value=self.market_value,
            as_of=self.as_of,
        )
        if self.snapshot_hash != expected_hash:
            raise ValueError(
                f"snapshot_hash mismatch: expected {expected_hash}, "
                f"got {self.snapshot_hash}"
            )
        return self


# =========================================================================
# Builders
# =========================================================================


def build_order_intent(
    *,
    intent_id: UUID,
    client_order_id: str,
    session_key: SessionKeyV1,
    security_id: UUID,
    side: OrderSide | str,
    quantity: int,
    order_type: OrderType | str,
    limit_price: Decimal | None = None,
    time_in_force: TimeInForce | str = TimeInForce.DAY,
    created_at: datetime,
) -> OrderIntentV1:
    """Build an immutable OrderIntentV1 with automatic hash computation."""
    norm_side = OrderSide(side) if isinstance(side, str) else side
    norm_type = OrderType(order_type) if isinstance(order_type, str) else order_type
    norm_tif = (
        TimeInForce(time_in_force) if isinstance(time_in_force, str) else time_in_force
    )
    norm_limit = canonical_money(limit_price) if limit_price is not None else None

    h = compute_order_intent_hash(
        schema_version=EXECUTION_SCHEMA_VERSION,
        intent_id=intent_id,
        client_order_id=client_order_id,
        session_key=session_key,
        security_id=security_id,
        side=norm_side.value,
        quantity=quantity,
        order_type=norm_type.value,
        limit_price=norm_limit,
        time_in_force=norm_tif.value,
        created_at=created_at,
    )
    return OrderIntentV1(
        schema_version=EXECUTION_SCHEMA_VERSION,
        intent_id=intent_id,
        client_order_id=client_order_id,
        session_key=session_key,
        security_id=security_id,
        side=norm_side,
        quantity=quantity,
        order_type=norm_type,
        limit_price=norm_limit,
        time_in_force=norm_tif,
        created_at=created_at,
        intent_hash=h,
    )


def build_execution_report(
    *,
    report_id: UUID,
    intent_id: UUID,
    broker_order_id: str | None = None,
    status: ExecutionStatus | str,
    cum_quantity: int = 0,
    leaves_quantity: int = 0,
    last_fill_price: Decimal | None = None,
    last_fill_quantity: int | None = None,
    avg_fill_price: Decimal | None = None,
    fee_amount: Decimal = Decimal("0"),
    rejection_reason: str | None = None,
    reported_at: datetime,
) -> ExecutionReportV1:
    """Build an immutable ExecutionReportV1 with automatic hash computation."""
    norm_status = ExecutionStatus(status) if isinstance(status, str) else status
    norm_last_price = (
        canonical_money(last_fill_price) if last_fill_price is not None else None
    )
    norm_avg_price = (
        canonical_money(avg_fill_price) if avg_fill_price is not None else None
    )
    norm_fee = canonical_money(fee_amount)

    h = compute_execution_report_hash(
        schema_version=EXECUTION_SCHEMA_VERSION,
        report_id=report_id,
        intent_id=intent_id,
        broker_order_id=broker_order_id,
        status=norm_status.value,
        cum_quantity=cum_quantity,
        leaves_quantity=leaves_quantity,
        last_fill_price=norm_last_price,
        last_fill_quantity=last_fill_quantity,
        avg_fill_price=norm_avg_price,
        fee_amount=norm_fee,
        rejection_reason=rejection_reason,
        reported_at=reported_at,
    )
    return ExecutionReportV1(
        schema_version=EXECUTION_SCHEMA_VERSION,
        report_id=report_id,
        intent_id=intent_id,
        broker_order_id=broker_order_id,
        status=norm_status,
        cum_quantity=cum_quantity,
        leaves_quantity=leaves_quantity,
        last_fill_price=norm_last_price,
        last_fill_quantity=last_fill_quantity,
        avg_fill_price=norm_avg_price,
        fee_amount=norm_fee,
        rejection_reason=rejection_reason,
        reported_at=reported_at,
        report_hash=h,
    )


def build_broker_account_snapshot(
    *,
    snapshot_id: UUID,
    account_id: str,
    cash_balance: Decimal,
    buying_power: Decimal,
    portfolio_equity: Decimal,
    as_of: datetime,
) -> BrokerAccountSnapshotV1:
    """Build an immutable BrokerAccountSnapshotV1 with automatic hash computation."""
    c_cash = canonical_money(cash_balance)
    c_bp = canonical_money(buying_power)
    c_equity = canonical_money(portfolio_equity)

    h = compute_broker_account_snapshot_hash(
        schema_version=EXECUTION_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        account_id=account_id,
        cash_balance=c_cash,
        buying_power=c_bp,
        portfolio_equity=c_equity,
        as_of=as_of,
    )
    return BrokerAccountSnapshotV1(
        schema_version=EXECUTION_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        account_id=account_id,
        cash_balance=c_cash,
        buying_power=c_bp,
        portfolio_equity=c_equity,
        as_of=as_of,
        snapshot_hash=h,
    )


def build_broker_position_snapshot(
    *,
    snapshot_id: UUID,
    security_id: UUID,
    quantity: int,
    cost_basis: Decimal,
    current_price: Decimal | None = None,
    market_value: Decimal | None = None,
    as_of: datetime,
) -> BrokerPositionSnapshotV1:
    """Build an immutable BrokerPositionSnapshotV1 with automatic hash computation."""
    c_basis = canonical_money(cost_basis)
    c_price = canonical_money(current_price) if current_price is not None else None
    c_mv = canonical_money(market_value) if market_value is not None else None

    h = compute_broker_position_snapshot_hash(
        schema_version=EXECUTION_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        security_id=security_id,
        quantity=quantity,
        cost_basis=c_basis,
        current_price=c_price,
        market_value=c_mv,
        as_of=as_of,
    )
    return BrokerPositionSnapshotV1(
        schema_version=EXECUTION_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        security_id=security_id,
        quantity=quantity,
        cost_basis=c_basis,
        current_price=c_price,
        market_value=c_mv,
        as_of=as_of,
        snapshot_hash=h,
    )
