"""M2 next-open execution contracts: planned fills, rejections, and outcomes.

Execution is plan-then-commit. A plan is a complete, self-reconciling
statement of what the rebalance would do; an outcome states whether the whole
plan was committed or none of it was. There is no representation for a
partially applied rebalance, by construction.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, SHA256Hash
from drift.domain.evaluator_portfolio import (
    PortfolioFillV1,
    PortfolioStateV1,
    SecurityHoldingV1,
    decimal_context,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.errors import DriftError
from drift.serialization.canonical import content_hash

ZERO = Decimal("0")
BASIS_POINT_DENOMINATOR = Decimal("10000")


class IndeterminateExecutionError(DriftError):
    """Raised when a rebalance cannot be executed from authorized evidence.

    Distinct from a rejection. A rejection is a fully evidenced, scientifically
    meaningful "this intent was unfunded"; this error means the evaluator
    cannot know what would have happened, and the run fails closed to
    INDETERMINATE rather than inventing a price or a venue.
    """


class AtomicRebalanceCommitError(DriftError):
    """Raised when a funded plan cannot be booked, so nothing was booked.

    The engine builds every commit against a throwaway accounting kernel, so
    reaching this error means zero mutations were applied to the caller's
    state. It exists to convert a would-be partial application into a hard
    fail-closed stop.
    """


def _security_order(security_id: UUID) -> bytes:
    """Canonical collection order for securities: raw UUID bytes."""
    return security_id.bytes


def positions_digest(holdings: Sequence[SecurityHoldingV1]) -> SHA256Hash:
    """Digest the share counts a rebalance plan was computed against.

    Quantities only. Cost basis does not change any delta, and hashing an
    exact Decimal would make two economically identical books disagree over
    trailing zeros.
    """
    return content_hash(
        {str(holding.security_id): holding.quantity for holding in holdings}
    )


class ListingOpenPriceV1(FrozenModel):
    """One unadjusted session-open price bound to the listing it was observed on.

    A price is evidence about a listing, never about a security in the
    abstract. Carrying the listing and venue with the number lets the engine
    prove that the price it stamps on a fill came from the listing execution
    actually resolved, instead of asserting a `(listing_id, venue, price)`
    triple nothing ever checked.
    """

    schema_version: Literal["1"] = "1"
    listing_id: UUID7
    venue: ListingVenue
    unadjusted_open_price: Decimal

    @model_validator(mode="after")
    def validate_open_price(self) -> Self:
        with decimal_context():
            if (
                not self.unadjusted_open_price.is_finite()
                or self.unadjusted_open_price <= ZERO
            ):
                raise ValueError("unadjusted open price must be strictly positive")
        return self


class ExecutionFillV1(FrozenModel):
    """One planned or committed whole-share fill at a resolved listing.

    The listing and venue are the ones the evaluator resolved as of the
    execution session, not anything the strategy chose.
    """

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    listing_id: UUID7
    venue: ListingVenue
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    unadjusted_open_price: Decimal
    fill_price: Decimal
    gross_notional: Decimal
    transaction_costs: Decimal
    cash_delta: Decimal

    @model_validator(mode="after")
    def validate_fill(self) -> Self:
        with decimal_context():
            return self._validate_under_pinned_context()

    def _validate_under_pinned_context(self) -> Self:
        if self.unadjusted_open_price <= ZERO:
            raise ValueError("unadjusted open price must be strictly positive")
        if self.fill_price <= ZERO:
            raise ValueError("fill price must be strictly positive")
        if self.transaction_costs < ZERO:
            raise ValueError("transaction costs must be non-negative")
        expected_notional = self.fill_price * self.quantity
        if self.gross_notional != expected_notional:
            raise ValueError(
                f"gross notional must equal {expected_notional}, "
                f"got {self.gross_notional}"
            )
        expected_delta = (
            self.gross_notional - self.transaction_costs
            if self.side == "sell"
            else -(self.gross_notional + self.transaction_costs)
        )
        if self.cash_delta != expected_delta:
            raise ValueError(
                f"cash delta must equal {expected_delta}, got {self.cash_delta}"
            )
        return self

    def to_portfolio_fill(self) -> PortfolioFillV1:
        """Project this fill into the portfolio accounting kernel's input."""
        return PortfolioFillV1(
            security_id=self.security_id,
            side=self.side,
            quantity=self.quantity,
            fill_price=self.fill_price,
            transaction_costs=self.transaction_costs,
        )


def canonical_fill_order(
    fills: Sequence[ExecutionFillV1],
) -> tuple[ExecutionFillV1, ...]:
    """Canonical commit order for one rebalance: sells first, then buys.

    Sells are ordered by descending ``cash_delta``. Booking the largest
    cash-positive sells first makes running cash a concave sequence over the
    sell leg, so its minimum is attained at one of the two endpoints: the
    opening cash, which is non-negative, or the balance after every sell,
    which a funded plan proves non-negative. No intermediate step can dip
    below zero, so a sell whose fixed fee exceeds its own proceeds can never
    abort an otherwise funded rebalance. Ordering sells by security UUID
    bytes has no such property: whether the rebalance aborts would depend on
    which identifiers the securities happen to carry.

    Ties break on security UUID bytes, keeping the result a canonical total
    order. Buys follow, ordered by security UUID bytes, because cash only
    falls across the buy leg and the final balance is therefore its minimum.
    """
    sells = [fill for fill in fills if fill.side == "sell"]
    buys = [fill for fill in fills if fill.side == "buy"]
    # Two stable passes rather than one negated key: unary minus on a Decimal
    # is a context operation, and canonical order must not depend on the
    # ambient decimal context.
    sells.sort(key=lambda fill: _security_order(fill.security_id))
    sells.sort(key=lambda fill: fill.cash_delta, reverse=True)
    buys.sort(key=lambda fill: _security_order(fill.security_id))
    return tuple(sells) + tuple(buys)


class FillRejectionV1(FrozenModel):
    """Evidence that one complete rebalance intent was unfunded.

    Carries the whole solvency computation so the trace can state the exact
    shortfall. Task 6 wraps this into `FillRejectionTraceEventV1`.
    """

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    reason: Literal["insufficient_cash"] = "insufficient_cash"
    current_cash: Decimal
    gross_sell_proceeds: Decimal
    sell_transaction_costs: Decimal
    required_cash: Decimal
    projected_cash: Decimal
    cash_shortfall: Decimal

    @model_validator(mode="after")
    def validate_rejection(self) -> Self:
        with decimal_context():
            return self._validate_under_pinned_context()

    def _validate_under_pinned_context(self) -> Self:
        expected_projected = (
            self.current_cash
            + self.gross_sell_proceeds
            - self.sell_transaction_costs
            - self.required_cash
        )
        if self.projected_cash != expected_projected:
            raise ValueError(
                f"projected cash must equal {expected_projected}, "
                f"got {self.projected_cash}"
            )
        if self.projected_cash >= ZERO:
            raise ValueError(
                "a rejection requires a negative projected cash, got "
                f"{self.projected_cash}"
            )
        if self.cash_shortfall != -self.projected_cash:
            raise ValueError(
                f"cash shortfall must equal {-self.projected_cash}, "
                f"got {self.cash_shortfall}"
            )
        return self


class RebalancePlanV1(FrozenModel):
    """A complete, self-reconciling next-open rebalance plan.

    `gross_sell_proceeds` is stated before sell costs; the solvency identity
    subtracts them explicitly so the plan can be audited term by term.
    """

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    planned_fills: tuple[ExecutionFillV1, ...]
    opening_positions_hash: SHA256Hash
    current_cash: Decimal
    gross_sell_proceeds: Decimal
    sell_transaction_costs: Decimal
    required_cash: Decimal
    projected_cash: Decimal

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        with decimal_context():
            return self._validate_under_pinned_context()

    def _validate_under_pinned_context(self) -> Self:
        if self.current_cash < ZERO:
            raise ValueError("current cash must be non-negative")
        securities = tuple(fill.security_id for fill in self.planned_fills)
        if len(set(securities)) != len(securities):
            raise ValueError("a plan must carry at most one fill per security")

        sells = tuple(fill for fill in self.planned_fills if fill.side == "sell")
        buys = tuple(fill for fill in self.planned_fills if fill.side == "buy")
        # Sells fund buys, so the committed order is part of the contract, not
        # an implementation detail.
        if self.planned_fills != canonical_fill_order(self.planned_fills):
            raise ValueError(
                "planned fills must be in canonical order: sells by descending "
                "cash delta, then buys, each tie broken by security UUID bytes"
            )

        expected_proceeds = sum((fill.gross_notional for fill in sells), ZERO)
        if self.gross_sell_proceeds != expected_proceeds:
            raise ValueError(
                f"gross sell proceeds must equal {expected_proceeds}, "
                f"got {self.gross_sell_proceeds}"
            )
        expected_sell_costs = sum((fill.transaction_costs for fill in sells), ZERO)
        if self.sell_transaction_costs != expected_sell_costs:
            raise ValueError(
                f"sell transaction costs must equal {expected_sell_costs}, "
                f"got {self.sell_transaction_costs}"
            )
        expected_required = sum(
            (fill.gross_notional + fill.transaction_costs for fill in buys), ZERO
        )
        if self.required_cash != expected_required:
            raise ValueError(
                f"required cash must equal {expected_required}, "
                f"got {self.required_cash}"
            )
        expected_projected = (
            self.current_cash
            + self.gross_sell_proceeds
            - self.sell_transaction_costs
            - self.required_cash
        )
        if self.projected_cash != expected_projected:
            raise ValueError(
                f"projected cash must equal {expected_projected}, "
                f"got {self.projected_cash}"
            )
        return self

    @property
    def is_funded(self) -> bool:
        """Whether the complete rebalance is funded without margin."""
        return self.projected_cash >= ZERO


class RebalanceOutcomeV1(FrozenModel):
    """The all-or-nothing result of one next-open rebalance."""

    schema_version: Literal["1"] = "1"
    classification: Literal["executed", "rejected"]
    plan: RebalancePlanV1
    committed_fills: tuple[ExecutionFillV1, ...]
    rejection: FillRejectionV1 | None
    state: PortfolioStateV1
    halt_stepping: bool

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.classification == "rejected":
            if self.rejection is None:
                raise ValueError("a rejected rebalance requires its rejection")
            if self.committed_fills:
                raise ValueError("a rejected rebalance must commit zero fills")
            if not self.halt_stepping:
                raise ValueError("a rejected rebalance must halt session stepping")
            if self.rejection.session_key != self.plan.session_key:
                raise ValueError("rejection and plan must share a session")
            return self
        if self.rejection is not None:
            raise ValueError("an executed rebalance must not carry a rejection")
        if self.halt_stepping:
            raise ValueError("an executed rebalance must not halt session stepping")
        if self.committed_fills != self.plan.planned_fills:
            raise ValueError("an executed rebalance must commit every planned fill")
        return self
