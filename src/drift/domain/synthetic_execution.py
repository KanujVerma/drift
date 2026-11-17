"""Explicit synthetic execution scenarios, separate from atomic M2 outcomes.

An instruction selects quantities to simulate. Only an evaluator receipt says
those quantities were committed to the original account. Unverified quantities
are never evidence that no additional execution occurred.
"""

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.evaluator_execution import ExecutionFillV1, RebalancePlanV1
from drift.domain.evaluator_portfolio import PortfolioStateV2, decimal_context
from drift.serialization.canonical import content_hash

SyntheticOrderStatus = Literal["FILLED", "PARTIAL", "UNFILLED", "UNKNOWN"]


class ProtectiveCorrectionPolicyV1(FrozenModel):
    schema_version: Literal["drift-protective-correction/1"] = (
        "drift-protective-correction/1"
    )
    algorithm: Literal["WHOLE_SHARE_TARGETED_V1"] = "WHOLE_SHARE_TARGETED_V1"
    enabled: bool = Field(strict=True)
    allow_while_paused: bool = Field(strict=True)
    maximum_preview_evaluations: int = Field(strict=True, gt=0, le=4096)

    @property
    def policy_hash(self) -> str:
        return content_hash(self)


class SyntheticOrderFillSpecV1(FrozenModel):
    """An explicit override for one order in the original canonical plan."""

    order_index: int = Field(strict=True, ge=0)
    verified_filled_quantity: int = Field(strict=True, ge=0)
    status: SyntheticOrderStatus

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status in ("FILLED", "PARTIAL") and self.verified_filled_quantity == 0:
            raise ValueError("SYNTHETIC_FILLED_STATUS_REQUIRES_POSITIVE_QUANTITY")
        if self.status == "UNFILLED" and self.verified_filled_quantity != 0:
            raise ValueError("SYNTHETIC_UNFILLED_STATUS_REQUIRES_ZERO_QUANTITY")
        return self


class SyntheticSessionFillSpecV1(FrozenModel):
    session_index: int = Field(strict=True, ge=0)
    orders: tuple[SyntheticOrderFillSpecV1, ...]

    @model_validator(mode="after")
    def validate_orders(self) -> Self:
        indices = tuple(order.order_index for order in self.orders)
        if indices != tuple(sorted(set(indices))):
            raise ValueError("SYNTHETIC_FILL_SPEC_ORDER_IDENTITIES")
        return self


class SyntheticExecutionPolicyV1(FrozenModel):
    """Unspecified sessions/orders execute fully under the original M2 model."""

    schema_version: Literal["drift-synthetic-execution/1"] = (
        "drift-synthetic-execution/1"
    )
    policy_id: NonBlankStr
    sessions: tuple[SyntheticSessionFillSpecV1, ...]

    @model_validator(mode="after")
    def validate_sessions(self) -> Self:
        indices = tuple(session.session_index for session in self.sessions)
        if indices != tuple(sorted(set(indices))):
            raise ValueError("SYNTHETIC_FILL_SPEC_SESSION_IDENTITIES")
        return self

    @property
    def policy_hash(self) -> str:
        return content_hash(self)


class SyntheticOrderSelectionV1(FrozenModel):
    security_id: UUID7
    requested_quantity: int = Field(strict=True, gt=0)
    verified_filled_quantity: int = Field(strict=True, ge=0)
    status: SyntheticOrderStatus

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        filled, requested = self.verified_filled_quantity, self.requested_quantity
        if filled > requested:
            raise ValueError("SYNTHETIC_ORDER_OVERFILL")
        if self.status == "FILLED" and filled != requested:
            raise ValueError("SYNTHETIC_FALSE_FILLED_STATUS")
        if self.status == "PARTIAL" and not 0 < filled < requested:
            raise ValueError("SYNTHETIC_FALSE_PARTIAL_STATUS")
        if self.status == "UNFILLED" and filled != 0:
            raise ValueError("SYNTHETIC_FALSE_UNFILLED_STATUS")
        if self.status == "UNKNOWN" and filled >= requested:
            raise ValueError("SYNTHETIC_UNKNOWN_REQUIRES_UNVERIFIED_QUANTITY")
        return self

    @property
    def unresolved_quantity(self) -> int:
        if self.status in ("PARTIAL", "UNKNOWN"):
            return self.requested_quantity - self.verified_filled_quantity
        return 0

    @property
    def known_unfilled_quantity(self) -> int:
        return self.requested_quantity if self.status == "UNFILLED" else 0


class SyntheticExecutionSelectionV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    preview_hash: SHA256Hash
    plan_hash: SHA256Hash
    policy_hash: SHA256Hash
    orders: tuple[SyntheticOrderSelectionV1, ...]
    invocation_id: UUID7 | None = None

    @model_validator(mode="after")
    def validate_orders(self) -> Self:
        securities = tuple(order.security_id for order in self.orders)
        if len(securities) != len(set(securities)):
            raise ValueError("SYNTHETIC_DUPLICATE_ORDER_SELECTION")
        return self

    @property
    def complete(self) -> bool:
        return all(order.status == "FILLED" for order in self.orders)


class SyntheticExecutionReceiptV1(FrozenModel):
    """Actual original-account commitment, retaining the full requested plan."""

    schema_version: Literal["1"] = "1"
    selection: SyntheticExecutionSelectionV1
    requested_plan: RebalancePlanV1
    actual_plan: RebalancePlanV1
    committed_fills: tuple[ExecutionFillV1, ...]
    before_state_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    state: PortfolioStateV2

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        requested, actual = self.requested_plan, self.actual_plan
        if self.selection.plan_hash != content_hash(requested):
            raise ValueError("SYNTHETIC_RECEIPT_WRONG_REQUESTED_PLAN")
        if (
            actual.session_key != requested.session_key
            or actual.opening_positions_hash != requested.opening_positions_hash
            or actual.current_cash != requested.current_cash
            or not actual.is_funded
            or self.state.session_key != requested.session_key
            or self.state.cash_balance != actual.projected_cash
            or self.committed_fills != actual.planned_fills
        ):
            raise ValueError("SYNTHETIC_RECEIPT_ACTUAL_PLAN_OR_STATE")
        if len(self.selection.orders) != len(requested.planned_fills):
            raise ValueError("SYNTHETIC_RECEIPT_ORDER_INVENTORY")
        committed = {fill.security_id: fill for fill in self.committed_fills}
        for selected, original in zip(
            self.selection.orders, requested.planned_fills, strict=True
        ):
            if (
                selected.security_id != original.security_id
                or selected.requested_quantity != original.quantity
            ):
                raise ValueError("SYNTHETIC_RECEIPT_WRONG_ORIGINAL_ORDER")
            fill = committed.pop(selected.security_id, None)
            if selected.verified_filled_quantity == 0:
                if fill is not None:
                    raise ValueError("SYNTHETIC_RECEIPT_UNVERIFIED_FILL")
                continue
            if (
                fill is None
                or fill.quantity != selected.verified_filled_quantity
                or fill.side != original.side
                or fill.listing_id != original.listing_id
                or fill.venue != original.venue
                or fill.unadjusted_open_price != original.unadjusted_open_price
                or fill.fill_price != original.fill_price
            ):
                raise ValueError("SYNTHETIC_RECEIPT_FALSE_ACTUAL_FILL")
        if committed:
            raise ValueError("SYNTHETIC_RECEIPT_FOREIGN_FILL")
        return self

    @property
    def complete(self) -> bool:
        return self.selection.complete

    @property
    def unresolved_order_count(self) -> int:
        return sum(
            order.status in ("PARTIAL", "UNKNOWN") for order in self.selection.orders
        )

    @property
    def verified_fill_count(self) -> int:
        return len(self.committed_fills)

    @property
    def verified_filled_quantity(self) -> int:
        return sum(fill.quantity for fill in self.committed_fills)

    @property
    def verified_execution_costs(self) -> Decimal:
        with decimal_context():
            return sum(
                (fill.transaction_costs for fill in self.committed_fills), Decimal(0)
            )
