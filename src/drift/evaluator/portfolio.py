"""Deterministic portfolio accounting kernel for M2 evaluation."""

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal

from drift.domain.common import UUID7, SHA256Hash
from drift.domain.evaluator_clock import SessionClockV1
from drift.domain.evaluator_lanes import EvaluationAdmissionV1
from drift.domain.evaluator_portfolio import (
    LANE_ADMISSIBLE_MARK_GRADES,
    EvaluationLane,
    IndeterminateBasisError,
    IndeterminateValuationError,
    LaneAdmissibilityError,
    MarkPriceV1,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioMarkV1,
    PortfolioStateV2,
    SecurityHoldingV2,
    decimal_context,
)
from drift.domain.sessions import SessionKeyV1

ZERO = Decimal("0")


def initial_portfolio_state(
    *,
    session_key: SessionKeyV1,
    initial_cash: Decimal,
    admission: EvaluationAdmissionV1,
) -> PortfolioStateV2:
    """Build the opening state for an evaluation run in an admitted lane.

    The lane is taken from the admission rather than passed alongside it, so a
    book can never claim a lane its admission does not authorize.
    """
    if initial_cash <= ZERO:
        raise ValueError("initial cash must be strictly positive")
    return PortfolioStateV2(
        lane=admission.lane,
        admission_hash=admission.admission_hash,
        session_key=session_key,
        cash_balance=initial_cash,
        holdings=(),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        mark=None,
        holdings_market_value=ZERO,
        pending_claims_value=ZERO,
        net_asset_value=initial_cash,
        realized_gross_pnl=ZERO,
        realized_net_pnl=ZERO,
        cumulative_transaction_costs=ZERO,
    )


def _ordered_holdings(
    holdings: Mapping[UUID7, SecurityHoldingV2],
) -> tuple[SecurityHoldingV2, ...]:
    return tuple(holdings[key] for key in sorted(holdings, key=str))


def known_cost_basis(holding: SecurityHoldingV2) -> Decimal:
    """The exact cost basis of a holding, refusing one that is indeterminate.

    Realized PnL is relieved from this basis, so an indeterminate one fails
    closed rather than reading as zero (spec 12.5).
    """
    if holding.cost_basis is None:
        raise IndeterminateBasisError(
            f"the cost basis of {holding.security_id} is indeterminate, caused by "
            f"{', '.join(holding.basis_indeterminate_by)}, so realizing it "
            "would invent realized PnL"
        )
    return holding.cost_basis


def pooled_holding(
    existing: SecurityHoldingV2 | None, received: SecurityHoldingV2
) -> SecurityHoldingV2:
    """Pool shares received into a holding of the same security.

    The pooled basis is known only if both sides are known, and is then their
    exact sum. Otherwise it is indeterminate and names every cause either
    side carried, so pooling can never turn an unknown basis into a known one.
    """
    if existing is None:
        return received
    if existing.security_id != received.security_id:
        raise ValueError("only holdings of one security can be pooled")
    quantity = existing.quantity + received.quantity
    if existing.cost_basis is not None and received.cost_basis is not None:
        with decimal_context():
            basis = existing.cost_basis + received.cost_basis
        return SecurityHoldingV2(
            security_id=existing.security_id,
            quantity=quantity,
            basis_status="known",
            cost_basis=basis,
        )
    return SecurityHoldingV2(
        security_id=existing.security_id,
        quantity=quantity,
        basis_status="indeterminate",
        cost_basis=None,
        basis_indeterminate_by=tuple(
            sorted(
                set(existing.basis_indeterminate_by)
                | set(received.basis_indeterminate_by)
            )
        ),
    )


def indeterminate_holding(
    holding: SecurityHoldingV2, cause: SHA256Hash
) -> SecurityHoldingV2:
    """The same shares, with a basis ``cause`` left without proven allocation."""
    return SecurityHoldingV2(
        security_id=holding.security_id,
        quantity=holding.quantity,
        basis_status="indeterminate",
        cost_basis=None,
        basis_indeterminate_by=tuple(
            sorted(set(holding.basis_indeterminate_by) | {cause})
        ),
    )


def _ordered_claims(
    claims: Mapping[SHA256Hash, PendingCashClaimV1],
) -> tuple[PendingCashClaimV1, ...]:
    return tuple(claims[key] for key in sorted(claims))


class PortfolioAccountingKernel:
    """Applies fills, claims, settlement, and marking with exact arithmetic.

    Marking is deliberately not carried forward across sessions: advancing the
    session clears the mark so a stale price can never value a later session.

    The kernel is bound to the ``SessionClockV1`` that authorizes its sessions.
    Advancement follows that clock rather than a bare local-date comparison, so
    a legal multi-venue clock holding two sessions on one local date advances
    correctly while a session key the clock never authorized is refused.
    """

    def __init__(
        self, state: PortfolioStateV2, *, session_clock: SessionClockV1
    ) -> None:
        self._clock = session_clock
        self._session_positions: dict[SessionKeyV1, int] = {
            session.session_key: position
            for position, session in enumerate(session_clock.sessions)
        }
        if state.session_key not in self._session_positions:
            raise ValueError(
                "session clock does not authorize book session "
                f"{state.session_key.mic}/{state.session_key.session_scope}/"
                f"{state.session_key.local_date}"
            )
        self._state = state
        self._lane: EvaluationLane = state.lane
        self._holdings: dict[UUID7, SecurityHoldingV2] = {
            holding.security_id: holding for holding in state.holdings
        }
        self._claims: dict[SHA256Hash, PendingCashClaimV1] = {
            claim.claim_id: claim for claim in state.pending_cash_claims
        }
        self._cash = state.cash_balance
        self._mark: PortfolioMarkV1 | None = state.mark
        self._settled: set[SHA256Hash] = set(state.settled_claim_ids)
        # The kernel applies no economic effect itself, so it carries the
        # book's applied effects through every mutation unchanged.
        self._applied = state.applied_effect_ids
        self._realized_gross = state.realized_gross_pnl
        self._realized_net = state.realized_net_pnl
        self._costs = state.cumulative_transaction_costs
        self._session = state.session_key

    @property
    def state(self) -> PortfolioStateV2:
        """Current immutable state."""
        return self._state

    def _snapshot(self) -> tuple[object, ...]:
        return (
            dict(self._holdings),
            dict(self._claims),
            self._cash,
            self._mark,
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
            self._mark,
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

    def _marked_value(self) -> Decimal:
        """Value the current holdings from the current mark, if any.

        Market value is derived from the mark rather than cached beside it, so
        the two can never disagree about what was priced.
        """
        if self._mark is None:
            return ZERO
        priced = {price.security_id: price.close_price for price in self._mark.prices}
        total = ZERO
        for holding in self._holdings.values():
            total += priced[holding.security_id] * holding.quantity
        return total

    def _rebuild_under_pinned_context(self) -> None:
        claims_value = sum(
            (claim.total_cash_expected for claim in self._claims.values()), ZERO
        )
        market_value = self._marked_value()
        self._state = PortfolioStateV2(
            lane=self._lane,
            admission_hash=self._state.admission_hash,
            session_key=self._session,
            cash_balance=self._cash,
            holdings=_ordered_holdings(self._holdings),
            pending_cash_claims=_ordered_claims(self._claims),
            settled_claim_ids=tuple(sorted(self._settled)),
            applied_effect_ids=self._applied,
            mark=self._mark,
            holdings_market_value=market_value,
            pending_claims_value=claims_value,
            net_asset_value=self._cash + market_value + claims_value,
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
            self._mark = None
            self._rebuild()

    def _apply_buy(self, fill: PortfolioFillV1) -> None:
        gross = fill.fill_price * fill.quantity
        required = gross + fill.transaction_costs
        if required > self._cash:
            raise ValueError(
                f"insufficient cash for fill: requires {required}, holds {self._cash}"
            )
        self._cash -= required
        # A buy costs exactly what it paid, but pooled into an indeterminate
        # basis it leaves the pool indeterminate.
        self._holdings[fill.security_id] = pooled_holding(
            self._holdings.get(fill.security_id),
            SecurityHoldingV2(
                security_id=fill.security_id,
                quantity=fill.quantity,
                basis_status="known",
                cost_basis=required,
            ),
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
        basis = known_cost_basis(existing)
        relieved = basis * fill.quantity / existing.quantity
        self._cash += net_proceeds
        self._realized_gross += proceeds - relieved
        self._realized_net += proceeds - relieved - fill.transaction_costs
        remaining = existing.quantity - fill.quantity
        if remaining == 0:
            del self._holdings[fill.security_id]
            return
        self._holdings[fill.security_id] = SecurityHoldingV2(
            security_id=fill.security_id,
            quantity=remaining,
            basis_status="known",
            cost_basis=basis - relieved,
        )

    def record_claim(self, claim: PendingCashClaimV1) -> None:
        """Record cash owed by a corporate action. Does not move cash."""
        # Settlement removes the claim from the pending set, so the pending
        # check alone stops guarding it. Claim identity is the source-scoped
        # economic occurrence and is independent of every revisable date, so a
        # settled id must never be payable again, however its dates are later
        # revised.
        if claim.claim_id in self._settled:
            raise ValueError(f"claim already settled {claim.claim_id}")
        if claim.claim_id in self._claims:
            raise ValueError(f"duplicate pending claim {claim.claim_id}")
        with self._transaction():
            self._claims[claim.claim_id] = claim
            self._rebuild()

    def supersede_claim(self, claim: PendingCashClaimV1) -> None:
        """Replace a pending claim with a revision of the same identity.

        M1c carries payable and entitlement dates as revisable source claims,
        so a date revision revises the claim already recorded. Because identity
        is date-independent, the revision resolves here by supersession and can
        never mint a second claim for one economic entitlement. A settled claim
        is refused: delivery already happened, so there is nothing left to
        revise into a second payment.
        """
        if claim.claim_id in self._settled:
            raise ValueError(f"claim already settled {claim.claim_id}")
        if claim.claim_id not in self._claims:
            raise ValueError(f"unknown claim {claim.claim_id}")
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
        """Move the book to a later clock session and drop any stale mark.

        Advancement is measured in the bound session clock's own order, not by
        local date. That admits a legal multi-venue clock holding two sessions
        on one local date, and refuses any key the clock never authorized, so
        a book cannot silently accept a session from a different venue or
        scope.
        """
        target = self._session_positions.get(session_key)
        if target is None:
            raise ValueError(
                "session clock does not authorize session "
                f"{session_key.mic}/{session_key.session_scope}/"
                f"{session_key.local_date}"
            )
        if target <= self._session_positions[self._session]:
            raise ValueError(
                "session must advance beyond "
                f"{self._session.mic}/{self._session.local_date}, got "
                f"{session_key.mic}/{session_key.local_date}"
            )
        with self._transaction():
            self._session = session_key
            self._mark = None
            self._rebuild()

    def mark_close(self, marks: Collection[MarkPriceV1]) -> None:
        """Mark every held position at an exact, evidence-bound close price.

        Every mark must name the evidence it came from. A mark whose provenance
        is indeterminate is refused in every lane, and a promotion-lane book
        refuses evidence weaker than promotion-grade, so an exploratory
        reconstruction can never reach a promotion-grade net asset value.
        """
        priced = self._indexed_marks(marks)
        missing = tuple(sorted(str(key) for key in self._holdings if key not in priced))
        if missing:
            raise IndeterminateValuationError(
                f"no authorized close price for held security {missing[0]}"
            )
        unheld = tuple(sorted(str(key) for key in priced if key not in self._holdings))
        if unheld:
            raise ValueError(f"close price for unheld security {unheld[0]}")
        for security_id in sorted(priced, key=str):
            self._admit_mark_evidence(priced[security_id])
        mark = PortfolioMarkV1(
            session_key=self._session,
            lane=self._lane,
            prices=tuple(priced[key] for key in sorted(priced, key=str)),
        )
        with self._transaction(), decimal_context():
            self._mark = mark
            self._rebuild()

    def _indexed_marks(
        self, marks: Collection[MarkPriceV1]
    ) -> dict[UUID7, MarkPriceV1]:
        indexed: dict[UUID7, MarkPriceV1] = {}
        for mark in marks:
            if mark.security_id in indexed:
                raise ValueError(
                    f"repeated close price for security {mark.security_id}"
                )
            indexed[mark.security_id] = mark
        return indexed

    def _admit_mark_evidence(self, mark: MarkPriceV1) -> None:
        grade = mark.evidence.grade
        if grade == "indeterminate":
            raise IndeterminateValuationError(
                f"close price for security {mark.security_id} has indeterminate "
                f"provenance: {mark.evidence.reason}"
            )
        if grade not in LANE_ADMISSIBLE_MARK_GRADES[self._lane]:
            raise LaneAdmissibilityError(
                f"{self._lane} lane refuses {grade} mark evidence for security "
                f"{mark.security_id}"
            )
