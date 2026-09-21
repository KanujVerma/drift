"""Deterministic portfolio accounting kernel for M2 evaluation."""

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal

from drift.domain.common import UUID7, SHA256Hash
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioStateV1,
    SecurityHoldingV1,
    decimal_context,
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
        settled_claim_ids=(),
        is_marked=False,
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
        self._marked = state.is_marked
        self._settled: set[SHA256Hash] = set(state.settled_claim_ids)
        self._realized_gross = state.realized_gross_pnl
        self._realized_net = state.realized_net_pnl
        self._costs = state.cumulative_transaction_costs
        self._session = state.session_key

    @property
    def state(self) -> PortfolioStateV1:
        """Current immutable state."""
        return self._state

    def _snapshot(self) -> tuple[object, ...]:
        return (
            dict(self._holdings),
            dict(self._claims),
            self._cash,
            self._market_value,
            self._marked,
            set(self._settled),
            self._realized_gross,
            self._realized_net,
            self._costs,
            self._session,
            self._state,
        )

    def _restore(self, snapshot: tuple[object, ...]) -> None:
        (
            self._holdings,
            self._claims,
            self._cash,
            self._market_value,
            self._marked,
            self._settled,
            self._realized_gross,
            self._realized_net,
            self._costs,
            self._session,
            self._state,
        ) = snapshot  # type: ignore[assignment]

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Apply a mutation atomically.

        Without this, a mutation that fails validation during rebuild would
        leave the kernel's internal fields advanced while state still showed
        the old value, so a rejected fill would be silently committed by the
        next successful operation.
        """
        snapshot = self._snapshot()
        try:
            yield
        except BaseException:
            self._restore(snapshot)
            raise

    def _rebuild(self) -> None:
        with decimal_context():
            self._rebuild_under_pinned_context()

    def _rebuild_under_pinned_context(self) -> None:
        claims_value = sum(
            (claim.total_cash_expected for claim in self._claims.values()), ZERO
        )
        self._state = PortfolioStateV1(
            session_key=self._session,
            cash_balance=self._cash,
            holdings=_ordered_holdings(self._holdings),
            pending_cash_claims=_ordered_claims(self._claims),
            settled_claim_ids=tuple(sorted(self._settled)),
            is_marked=self._marked,
            holdings_market_value=self._market_value,
            pending_claims_value=claims_value,
            net_asset_value=self._cash + self._market_value + claims_value,
            realized_gross_pnl=self._realized_gross,
            realized_net_pnl=self._realized_net,
            cumulative_transaction_costs=self._costs,
        )

    def apply_fill(self, fill: PortfolioFillV1) -> None:
        """Apply one executed fill to cash, holdings, and realized results.

        Any existing mark is invalidated, because a mark taken against the
        previous holdings no longer describes the position.
        """
        with self._transaction(), decimal_context():
            if fill.side == "buy":
                self._apply_buy(fill)
            else:
                self._apply_sell(fill)
            self._costs += fill.transaction_costs
            self._marked = False
            self._market_value = ZERO
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
        proceeds = fill.fill_price * fill.quantity
        net_proceeds = proceeds - fill.transaction_costs
        if self._cash + net_proceeds < ZERO:
            raise ValueError(
                f"insufficient cash for sell costs: proceeds {proceeds}, "
                f"costs {fill.transaction_costs}, holds {self._cash}"
            )
        relieved = existing.cost_basis * fill.quantity / existing.quantity
        self._cash += net_proceeds
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
        # Settlement removes the claim from the pending set, so the pending
        # check alone stops guarding it. Claim identity is the economic
        # occurrence, so a settled id must never be payable again.
        if claim.claim_id in self._settled:
            raise ValueError(f"claim already settled {claim.claim_id}")
        with self._transaction():
            self._claims[claim.claim_id] = claim
            self._rebuild()

    def settle_claims(self, delivered_claim_ids: Collection[SHA256Hash]) -> None:
        """Convert claims with proven delivered settlement evidence into cash.

        Only claims explicitly proven delivered settle. A claim whose payable
        session falls on a non-trading date therefore settles on the first
        later session where delivered evidence exists, because settlement is
        driven by evidence rather than by the calendar.
        """
        # Normalize once. Accepting a bare Container let a mapping or deque
        # satisfy membership while silently skipping the unknown-claim guard.
        requested = frozenset(delivered_claim_ids)
        unknown = tuple(sorted(requested - set(self._claims)))
        if unknown:
            raise ValueError(f"unknown claim {unknown[0]}")
        settling = tuple(self._claims[claim_id] for claim_id in sorted(requested))
        for claim in settling:
            if claim.payable_session > self._session.local_date:
                raise ValueError(
                    f"claim {claim.claim_id} is not yet payable: "
                    f"payable {claim.payable_session}, session "
                    f"{self._session.local_date}"
                )
        with self._transaction(), decimal_context():
            for claim in settling:
                self._cash += claim.total_cash_expected
                del self._claims[claim.claim_id]
                self._settled.add(claim.claim_id)
            self._rebuild()

    def advance_session(self, session_key: SessionKeyV1) -> None:
        """Move the book to a later session and drop any stale mark."""
        if session_key.local_date <= self._session.local_date:
            raise ValueError(
                f"session must advance beyond {self._session.local_date}, "
                f"got {session_key.local_date}"
            )
        with self._transaction():
            self._session = session_key
            self._marked = False
            self._market_value = ZERO
            self._rebuild()

    def mark_close(self, close_prices: Mapping[UUID7, Decimal]) -> None:
        """Mark every held position at its exact unadjusted close price."""
        total = ZERO
        with decimal_context():
            total = self._marked_total(close_prices)
        with self._transaction():
            self._market_value = total
            self._marked = True
            self._rebuild()

    def _marked_total(self, close_prices: Mapping[UUID7, Decimal]) -> Decimal:
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
        return total
