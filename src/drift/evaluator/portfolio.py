"""Deterministic portfolio accounting kernel for M2 evaluation."""

from collections.abc import Container, Mapping
from decimal import Decimal

from drift.domain.common import UUID7, SHA256Hash
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioStateV1,
    SecurityHoldingV1,
)
from drift.domain.sessions import SessionKeyV1

ZERO = Decimal("0")


def initial_portfolio_state(
    *, session_key: SessionKeyV1, initial_cash: Decimal
) -> PortfolioStateV1:
    """Build the opening state for an evaluation run."""
    if initial_cash <= ZERO:
        raise ValueError("initial cash must be strictly positive")
    return PortfolioStateV1(
        session_key=session_key,
        cash_balance=initial_cash,
        holdings=(),
        pending_cash_claims=(),
        holdings_market_value=ZERO,
        pending_claims_value=ZERO,
        net_asset_value=initial_cash,
        realized_gross_pnl=ZERO,
        realized_net_pnl=ZERO,
        cumulative_transaction_costs=ZERO,
    )


def _ordered_holdings(
    holdings: Mapping[UUID7, SecurityHoldingV1],
) -> tuple[SecurityHoldingV1, ...]:
    return tuple(holdings[key] for key in sorted(holdings, key=str))


def _ordered_claims(
    claims: Mapping[SHA256Hash, PendingCashClaimV1],
) -> tuple[PendingCashClaimV1, ...]:
    return tuple(claims[key] for key in sorted(claims))


class PortfolioAccountingKernel:
    """Applies fills, claims, settlement, and marking with exact arithmetic.

    Marking is deliberately not carried forward across sessions: advancing the
    session clears the mark so a stale price can never value a later session.
    """

    def __init__(self, state: PortfolioStateV1) -> None:
        self._state = state
        self._holdings: dict[UUID7, SecurityHoldingV1] = {
            holding.security_id: holding for holding in state.holdings
        }
        self._claims: dict[SHA256Hash, PendingCashClaimV1] = {
            claim.claim_id: claim for claim in state.pending_cash_claims
        }
        self._cash = state.cash_balance
        self._market_value = state.holdings_market_value
        self._realized_gross = state.realized_gross_pnl
        self._realized_net = state.realized_net_pnl
        self._costs = state.cumulative_transaction_costs
        self._session = state.session_key

    @property
    def state(self) -> PortfolioStateV1:
        """Current immutable state."""
        return self._state

    def _rebuild(self) -> None:
        claims_value = sum(
            (claim.total_cash_expected for claim in self._claims.values()), ZERO
        )
        self._state = PortfolioStateV1(
            session_key=self._session,
            cash_balance=self._cash,
            holdings=_ordered_holdings(self._holdings),
            pending_cash_claims=_ordered_claims(self._claims),
            holdings_market_value=self._market_value,
            pending_claims_value=claims_value,
            net_asset_value=self._cash + self._market_value + claims_value,
            realized_gross_pnl=self._realized_gross,
            realized_net_pnl=self._realized_net,
            cumulative_transaction_costs=self._costs,
        )

    def apply_fill(self, fill: PortfolioFillV1) -> None:
        """Apply one executed fill to cash, holdings, and realized results."""
        if fill.side == "buy":
            self._apply_buy(fill)
        else:
            self._apply_sell(fill)
        self._costs += fill.transaction_costs
        self._rebuild()

    def _apply_buy(self, fill: PortfolioFillV1) -> None:
        gross = fill.fill_price * fill.quantity
        required = gross + fill.transaction_costs
        if required > self._cash:
            raise ValueError(
                f"insufficient cash for fill: requires {required}, holds {self._cash}"
            )
        self._cash -= required
        existing = self._holdings.get(fill.security_id)
        if existing is None:
            self._holdings[fill.security_id] = SecurityHoldingV1(
                security_id=fill.security_id,
                quantity=fill.quantity,
                cost_basis=required,
            )
            return
        self._holdings[fill.security_id] = SecurityHoldingV1(
            security_id=fill.security_id,
            quantity=existing.quantity + fill.quantity,
            cost_basis=existing.cost_basis + required,
        )

    def _apply_sell(self, fill: PortfolioFillV1) -> None:
        existing = self._holdings.get(fill.security_id)
        if existing is None or fill.quantity > existing.quantity:
            held = 0 if existing is None else existing.quantity
            raise ValueError(
                f"sell quantity {fill.quantity} exceeds held quantity {held}"
            )
        relieved = existing.cost_basis * fill.quantity / existing.quantity
        proceeds = fill.fill_price * fill.quantity
        self._cash += proceeds - fill.transaction_costs
        self._realized_gross += proceeds - relieved
        self._realized_net += proceeds - relieved - fill.transaction_costs
        remaining = existing.quantity - fill.quantity
        if remaining == 0:
            del self._holdings[fill.security_id]
            return
        self._holdings[fill.security_id] = SecurityHoldingV1(
            security_id=fill.security_id,
            quantity=remaining,
            cost_basis=existing.cost_basis - relieved,
        )

    def record_claim(self, claim: PendingCashClaimV1) -> None:
        """Record cash owed by a corporate action. Does not move cash."""
        if claim.claim_id in self._claims:
            raise ValueError(f"duplicate pending claim {claim.claim_id}")
        self._claims[claim.claim_id] = claim
        self._rebuild()

    def settle_claims(self, delivered_claim_ids: Container[SHA256Hash]) -> None:
        """Convert claims with proven delivered settlement evidence into cash.

        Only claims explicitly proven delivered settle. A claim whose payable
        session falls on a non-trading date therefore settles on the first
        later session where delivered evidence exists, because settlement is
        driven by evidence rather than by the calendar.
        """
        settling = tuple(
            claim
            for claim_id, claim in self._claims.items()
            if claim_id in delivered_claim_ids
        )
        for claim_id in _requested_ids(delivered_claim_ids):
            if claim_id not in self._claims:
                raise ValueError(f"unknown claim {claim_id}")
        for claim in settling:
            if claim.payable_session > self._session.local_date:
                raise ValueError(
                    f"claim {claim.claim_id} is not yet payable: "
                    f"payable {claim.payable_session}, session "
                    f"{self._session.local_date}"
                )
        for claim in settling:
            self._cash += claim.total_cash_expected
            del self._claims[claim.claim_id]
        self._rebuild()

    def advance_session(self, session_key: SessionKeyV1) -> None:
        """Move the book to a later session and drop any stale mark."""
        if session_key.local_date <= self._session.local_date:
            raise ValueError(
                f"session must advance beyond {self._session.local_date}, "
                f"got {session_key.local_date}"
            )
        self._session = session_key
        self._market_value = ZERO
        self._rebuild()

    def mark_close(self, close_prices: Mapping[UUID7, Decimal]) -> None:
        """Mark every held position at its exact unadjusted close price."""
        total = ZERO
        for holding in self._holdings.values():
            price = close_prices.get(holding.security_id)
            if price is None:
                raise IndeterminateValuationError(
                    f"no authorized close price for held security {holding.security_id}"
                )
            if price <= ZERO:
                raise ValueError(f"close price must be strictly positive, got {price}")
            total += price * holding.quantity
        self._market_value = total
        self._rebuild()


def _requested_ids(delivered: Container[SHA256Hash]) -> tuple[SHA256Hash, ...]:
    """Enumerate requested ids when the container supports it."""
    if isinstance(delivered, (tuple, list, set, frozenset)):
        return tuple(delivered)
    return ()
