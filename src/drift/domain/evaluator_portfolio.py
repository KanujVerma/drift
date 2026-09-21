"""M2 portfolio state, whole-share holdings, and deterministic cash claims."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.economic_common import ActionKind
from drift.domain.sessions import SessionKeyV1
from drift.errors import DriftError
from drift.serialization.canonical import content_hash

CLAIM_ID_PROFILE = "drift-pending-cash-claim-v1"

# Proportional basis relief can produce a non-terminating quotient, so the
# arithmetic context must be pinned rather than inherited. Without this an
# unrelated dependency touching getcontext() would silently change recorded
# books and break replay reproducibility.
PORTFOLIO_DECIMAL_PRECISION = 34
PORTFOLIO_DECIMAL_ROUNDING = ROUND_HALF_EVEN


@contextmanager
def decimal_context() -> Iterator[None]:
    """Pin the decimal context used for all portfolio arithmetic."""
    with localcontext(
        Context(prec=PORTFOLIO_DECIMAL_PRECISION, rounding=PORTFOLIO_DECIMAL_ROUNDING)
    ):
        yield


class IndeterminateValuationError(DriftError):
    """Raised when a held position cannot be marked from authorized evidence."""


def pending_cash_claim_id(
    *,
    security_id: UUID7,
    action_kind: ActionKind,
    occurrence_id: str,
    component_id: str,
    entitlement_session: date,
    payable_session: date,
) -> SHA256Hash:
    """Derive the deterministic identity of one occurrence-bound cash claim.

    Component identity is part of the preimage so that several cash components
    of one action on one date remain distinct claims.
    """
    return content_hash(
        {
            "profile": CLAIM_ID_PROFILE,
            "security_id": str(security_id),
            "action_kind": action_kind.value,
            "occurrence_id": occurrence_id,
            "component_id": component_id,
            "entitlement_session": entitlement_session.isoformat(),
            "payable_session": payable_session.isoformat(),
        }
    )


class SecurityHoldingV1(FrozenModel):
    """One long, whole-share position with its exact acquisition cost."""

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    quantity: int = Field(gt=0)
    cost_basis: Decimal

    @model_validator(mode="after")
    def validate_holding(self) -> Self:
        if self.cost_basis < Decimal("0"):
            raise ValueError("cost basis must be non-negative")
        return self

    @property
    def average_cost_per_share(self) -> Decimal:
        """Per-share cost under the pinned Drift decimal context.

        Not exact in general: a basis that does not divide evenly by quantity
        has no finite decimal representation. The pinned context makes the
        rounding deterministic, not absent.
        """
        with decimal_context():
            return self.cost_basis / self.quantity


class PendingCashClaimV1(FrozenModel):
    """Cash owed to the portfolio by a corporate action but not yet delivered."""

    schema_version: Literal["1"] = "1"
    claim_id: SHA256Hash
    security_id: UUID7
    action_kind: ActionKind
    occurrence_id: NonBlankStr
    component_id: NonBlankStr
    entitled_quantity: int = Field(gt=0)
    cash_per_share: Decimal
    total_cash_expected: Decimal
    entitlement_session: date
    payable_session: date

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        with decimal_context():
            return self._validate_claim_under_pinned_context()

    def _validate_claim_under_pinned_context(self) -> Self:
        if self.cash_per_share < Decimal("0"):
            raise ValueError("cash per share must be non-negative")
        expected_total = self.cash_per_share * self.entitled_quantity
        if self.total_cash_expected != expected_total:
            raise ValueError(
                f"total cash expected must equal {expected_total}, "
                f"got {self.total_cash_expected}"
            )
        if self.payable_session < self.entitlement_session:
            raise ValueError("payable session cannot precede entitlement session")
        expected_id = pending_cash_claim_id(
            security_id=self.security_id,
            action_kind=self.action_kind,
            occurrence_id=self.occurrence_id,
            component_id=self.component_id,
            entitlement_session=self.entitlement_session,
            payable_session=self.payable_session,
        )
        if self.claim_id != expected_id:
            raise ValueError(
                f"claim id mismatch: expected {expected_id}, got {self.claim_id}"
            )
        return self


class PortfolioFillV1(FrozenModel):
    """One executed whole-share fill as the accounting kernel consumes it."""

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    fill_price: Decimal
    transaction_costs: Decimal = Decimal("0.00")

    @model_validator(mode="after")
    def validate_fill(self) -> Self:
        if self.fill_price <= Decimal("0"):
            raise ValueError("fill price must be strictly positive")
        if self.transaction_costs < Decimal("0"):
            raise ValueError("transaction costs must be non-negative")
        return self


class PortfolioStateV1(FrozenModel):
    """Immutable portfolio state as of one evaluation session."""

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    cash_balance: Decimal
    holdings: tuple[SecurityHoldingV1, ...]
    pending_cash_claims: tuple[PendingCashClaimV1, ...]
    settled_claim_ids: tuple[SHA256Hash, ...] = ()
    is_marked: bool
    holdings_market_value: Decimal
    pending_claims_value: Decimal
    net_asset_value: Decimal
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        with decimal_context():
            return self._validate_under_pinned_context()

    def _validate_under_pinned_context(self) -> Self:
        if self.cash_balance < Decimal("0"):
            raise ValueError("cash balance must be non-negative")
        if self.holdings_market_value < Decimal("0"):
            raise ValueError("holdings market value must be non-negative")
        if self.cumulative_transaction_costs < Decimal("0"):
            raise ValueError("cumulative transaction costs must be non-negative")

        securities = tuple(holding.security_id for holding in self.holdings)
        if len(set(securities)) != len(securities):
            raise ValueError("holdings must carry at most one entry per security")
        claim_ids = tuple(claim.claim_id for claim in self.pending_cash_claims)
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("pending claims must be unique by claim id")

        # A settled claim must never reappear as pending. Claim identity is
        # derived from the economic occurrence, so the same id is the same
        # entitlement and paying it twice creates cash from nothing.
        if len(set(self.settled_claim_ids)) != len(self.settled_claim_ids):
            raise ValueError("settled claim ids must be unique")
        if tuple(sorted(self.settled_claim_ids)) != self.settled_claim_ids:
            raise ValueError("settled claim ids must be canonically sorted")
        replayed = set(self.settled_claim_ids) & set(claim_ids)
        if replayed:
            raise ValueError(
                f"claim already settled cannot be pending again: {sorted(replayed)[0]}"
            )

        expected_claims = sum(
            (claim.total_cash_expected for claim in self.pending_cash_claims),
            Decimal("0"),
        )
        if self.pending_claims_value != expected_claims:
            raise ValueError(
                f"pending claims value must equal {expected_claims}, "
                f"got {self.pending_claims_value}"
            )

        # A mark is only meaningful for the holdings it was taken against.
        # Coupling the two here stops a stale mark surviving a fill and
        # inventing net asset value that no position backs.
        if not self.is_marked and self.holdings_market_value != Decimal("0"):
            raise ValueError("unmarked state cannot carry a holdings market value")
        if not self.holdings and self.holdings_market_value != Decimal("0"):
            raise ValueError("state without holdings cannot carry a market value")
        if (
            self.is_marked
            and self.holdings
            and self.holdings_market_value <= Decimal("0")
        ):
            raise ValueError("marked holdings must carry a positive market value")

        expected_nav = (
            self.cash_balance + self.holdings_market_value + self.pending_claims_value
        )
        if self.net_asset_value != expected_nav:
            raise ValueError(
                f"net asset value must reconcile to {expected_nav}, "
                f"got {self.net_asset_value}"
            )
        return self
