"""Deterministic next-open atomic rebalance execution for M2 evaluation.

Two responsibilities live here. First, resolving the active historical primary
execution listing for a security as of the execution session, from M1b role
evidence, failing closed whenever the answer is not unique and provable.
Second, planning and atomically committing the whole rebalance at unadjusted
source-basis open prices, with versioned costs and adverse slippage.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from drift.domain.assertions import TemporalBoundaryClaimV1, TemporalIntervalClaimV1
from drift.domain.common import UUID7
from drift.domain.evaluator_clock import EvaluationSessionV1, SessionClockV1
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_execution import (
    BASIS_POINT_DENOMINATOR,
    ZERO,
    AtomicRebalanceCommitError,
    ExecutionFillV1,
    FillRejectionV1,
    IndeterminateExecutionError,
    ListingOpenPriceV1,
    RebalanceOutcomeV2,
    RebalancePlanV1,
    canonical_fill_order,
    positions_digest,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateBasisError,
    PortfolioStateV2,
    decimal_context,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.securities import (
    ListingLifecycleEventKind,
    ListingLifecycleVersionV1,
    ListingRole,
    ListingRoleVersionV1,
    ListingTerminationVersionV1,
    ListingV1,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel

ONE = Decimal("1")


def _security_order(security_id: UUID) -> bytes:
    """Canonical collection order for securities: raw UUID bytes."""
    return security_id.bytes


def _definitely_started(interval: TemporalIntervalClaimV1, instant: datetime) -> bool:
    upper = interval.start.upper_bound
    return upper is not None and upper <= instant


def _definitely_not_started(
    interval: TemporalIntervalClaimV1, instant: datetime
) -> bool:
    lower = interval.start.lower_bound
    return lower is not None and lower > instant


def _definitely_ended(interval: TemporalIntervalClaimV1, instant: datetime) -> bool:
    if interval.end is None:
        return False
    upper = interval.end.upper_bound
    return upper is not None and upper <= instant


def _definitely_not_ended(interval: TemporalIntervalClaimV1, instant: datetime) -> bool:
    if interval.end is None:
        return True
    lower = interval.end.lower_bound
    return lower is not None and lower > instant


def _is_active(interval: TemporalIntervalClaimV1, instant: datetime) -> bool:
    """Whether the record provably covers the instant.

    Deliberately three-valued at the call site: a record that is neither
    provably active nor provably inactive is ambiguous and poisons resolution,
    because it might be the true primary listing.
    """
    return _definitely_started(interval, instant) and _definitely_not_ended(
        interval, instant
    )


def _is_inactive(interval: TemporalIntervalClaimV1, instant: datetime) -> bool:
    return _definitely_not_started(interval, instant) or _definitely_ended(
        interval, instant
    )


def _boundary_reached(boundary: TemporalBoundaryClaimV1, instant: datetime) -> bool:
    """Whether the boundary provably falls at or before the instant."""
    upper = boundary.upper_bound
    return upper is not None and upper <= instant


def _boundary_not_reached(boundary: TemporalBoundaryClaimV1, instant: datetime) -> bool:
    """Whether the boundary provably falls strictly after the instant."""
    lower = boundary.lower_bound
    return lower is not None and lower > instant


def _require_unterminated(
    *,
    listing_id: UUID,
    instant: datetime,
    termination_records: Sequence[ListingTerminationVersionV1],
) -> None:
    """Fail closed unless the listing provably has not terminated yet.

    `ListingTerminationVersionV1` is the sole M1b authority that a listing
    terminated, so an evidence set carrying none for this listing proves the
    listing is unterminated. A record that is neither provably in effect nor
    provably still in the future poisons the answer, exactly as an ambiguous
    role interval does.
    """
    for record in termination_records:
        if record.listing_id != listing_id:
            continue
        boundary = record.effective_time
        if _boundary_reached(boundary, instant):
            raise IndeterminateExecutionError(
                f"terminated listing is not executable: listing {listing_id} "
                f"at {instant.isoformat()}"
            )
        if not _boundary_not_reached(boundary, instant):
            raise IndeterminateExecutionError(
                "listing termination evidence has an ambiguous effective time "
                f"for listing {listing_id} at {instant.isoformat()}"
            )


def _require_unsuspended(
    *,
    listing_id: UUID,
    instant: datetime,
    lifecycle_records: Sequence[ListingLifecycleVersionV1],
) -> None:
    """Fail closed unless the listing provably trades at the instant.

    A suspension lifts only on a resumption that provably follows it. A
    suspension with no such resumption leaves the listing either suspended or
    unprovably resumed, and neither is executable.
    """
    suspensions: list[TemporalBoundaryClaimV1] = []
    resumptions: list[TemporalBoundaryClaimV1] = []
    halting = {
        ListingLifecycleEventKind.SUSPENDED,
        ListingLifecycleEventKind.RESUMED,
    }
    for record in lifecycle_records:
        if record.listing_id != listing_id or record.event_kind not in halting:
            continue
        boundary = record.effective_time
        if _boundary_not_reached(boundary, instant):
            continue
        if not _boundary_reached(boundary, instant):
            raise IndeterminateExecutionError(
                "listing lifecycle evidence has an ambiguous effective time for "
                f"listing {listing_id} at {instant.isoformat()}"
            )
        target = (
            suspensions
            if record.event_kind is ListingLifecycleEventKind.SUSPENDED
            else resumptions
        )
        target.append(boundary)

    for suspension in suspensions:
        if not any(_follows(resumption, suspension) for resumption in resumptions):
            raise IndeterminateExecutionError(
                f"suspended listing is not executable: listing {listing_id} "
                f"at {instant.isoformat()}"
            )


def _follows(later: TemporalBoundaryClaimV1, earlier: TemporalBoundaryClaimV1) -> bool:
    """Whether `later` provably falls strictly after `earlier`.

    Two events the source places at the same instant have no provable order,
    so a resumption simultaneous with its suspension does not lift it.
    """
    lower = later.lower_bound
    upper = earlier.upper_bound
    return lower is not None and upper is not None and lower > upper


def resolve_execution_listing(
    *,
    security_id: UUID7,
    execution_session: EvaluationSessionV1,
    role_records: Sequence[ListingRoleVersionV1],
    listings: Sequence[ListingV1],
    termination_records: Sequence[ListingTerminationVersionV1],
    lifecycle_records: Sequence[ListingLifecycleVersionV1],
) -> ListingV1:
    """Resolve the active historical primary execution listing for a security.

    Resolution is as of the execution session open, so a security that
    migrated venues between decision and execution executes on the listing
    that was primary at execution time. Role evidence alone does not prove a
    listing is tradable: a delisted or suspended listing can still carry an
    open-ended primary role record, so termination and lifecycle evidence are
    consulted too. Anything short of a unique, provable answer fails closed.

    The termination and lifecycle evidence sets are required rather than
    defaulted, so a caller must state what it holds instead of silently
    resolving on role evidence alone.
    """
    instant = execution_session.opened_at
    candidates = tuple(
        record for record in role_records if record.security_id == security_id
    )
    active_roles: dict[UUID, set[ListingRole]] = {}
    for record in candidates:
        interval = record.effective_interval
        active = _is_active(interval, instant)
        if not active and not _is_inactive(interval, instant):
            raise IndeterminateExecutionError(
                "listing role evidence has an ambiguous effective interval for "
                f"security {security_id} at {instant.isoformat()}"
            )
        if not active:
            continue
        if record.role is ListingRole.INDETERMINATE:
            raise IndeterminateExecutionError(
                "listing role evidence is indeterminate for security "
                f"{security_id} at {instant.isoformat()}"
            )
        active_roles.setdefault(record.listing_id, set()).add(record.role)

    # One listing asserted two roles at once is evidence that contradicts
    # itself, exactly as two distinct active primaries are. Silently keeping
    # the primary half would pick a side of a contradiction.
    contradictory = tuple(
        sorted(
            (
                listing_id
                for listing_id, roles in active_roles.items()
                if len(roles) > 1
            ),
            key=lambda listing_id: listing_id.bytes,
        )
    )
    if contradictory:
        raise IndeterminateExecutionError(
            "listing role evidence is contradictory for listing "
            f"{contradictory[0]} of security {security_id} at "
            f"{instant.isoformat()}"
        )

    active_listing_ids = {
        listing_id
        for listing_id, roles in active_roles.items()
        if ListingRole.PRIMARY in roles
    }
    if not active_listing_ids:
        raise IndeterminateExecutionError(
            f"no active primary listing for security {security_id} at "
            f"{instant.isoformat()}"
        )
    if len(active_listing_ids) > 1:
        raise IndeterminateExecutionError(
            f"primary listing is not uniquely resolved for security {security_id} "
            f"at {instant.isoformat()}"
        )
    resolved_id = next(iter(active_listing_ids))
    _require_unterminated(
        listing_id=resolved_id,
        instant=instant,
        termination_records=termination_records,
    )
    _require_unsuspended(
        listing_id=resolved_id,
        instant=instant,
        lifecycle_records=lifecycle_records,
    )
    for listing in listings:
        if listing.listing_id == resolved_id:
            return listing
    raise IndeterminateExecutionError(
        f"resolved primary listing identity is unavailable: {resolved_id}"
    )


def resolve_execution_listings(
    *,
    security_ids: Iterable[UUID7],
    execution_session: EvaluationSessionV1,
    role_records: Sequence[ListingRoleVersionV1],
    listings: Sequence[ListingV1],
    termination_records: Sequence[ListingTerminationVersionV1],
    lifecycle_records: Sequence[ListingLifecycleVersionV1],
) -> dict[UUID7, ListingV1]:
    """Resolve one execution listing per security, failing closed on any gap."""
    return {
        security_id: resolve_execution_listing(
            security_id=security_id,
            execution_session=execution_session,
            role_records=role_records,
            listings=listings,
            termination_records=termination_records,
            lifecycle_records=lifecycle_records,
        )
        for security_id in sorted(set(security_ids), key=_security_order)
    }


def _require_determinate_sells(
    *, state: PortfolioStateV2, plan: RebalancePlanV1
) -> None:
    """Refuse a funded plan that sells a holding whose basis is indeterminate.

    A sale relieves basis into realized PnL, and an indeterminate basis has
    none to relieve, so the sale fails closed (spec 12.5, issue 103). This is
    judged after funding, so an unfunded plan is still a fully evidenced
    rejection, and before commit: raised inside the commit, the kernel's
    refusal would surface as ``AtomicRebalanceCommitError`` and crash the run
    rather than classify it INDETERMINATE.
    """
    held = {holding.security_id: holding for holding in state.holdings}
    for fill in plan.planned_fills:
        holding = held.get(fill.security_id)
        if fill.side != "sell" or holding is None or holding.cost_basis is not None:
            continue
        raise IndeterminateBasisError(
            f"the rebalance sells {fill.quantity} of {fill.security_id}, whose "
            "cost basis is indeterminate, caused by "
            f"{', '.join(holding.basis_indeterminate_by)}, so the realized PnL "
            "of the sale is not proven"
        )


class AtomicRebalanceEngine:
    """Plans and atomically commits one next-open rebalance.

    The engine never mutates the state handed to it. A commit is built against
    a throwaway accounting kernel, so a plan that cannot be booked leaves the
    caller holding exactly the state it passed in.
    """

    def __init__(
        self,
        *,
        cost_model: EvaluationCostModelV1,
        session_clock: SessionClockV1,
    ) -> None:
        self._cost_model = cost_model
        self._session_clock = session_clock

    @property
    def cost_model(self) -> EvaluationCostModelV1:
        """The versioned cost and slippage model applied to every fill."""
        return self._cost_model

    @property
    def session_clock(self) -> SessionClockV1:
        """Authority-bound clock the committing kernel is validated against."""
        return self._session_clock

    def plan(
        self,
        *,
        state: PortfolioStateV2,
        staged_targets: Sequence[SecurityTargetPositionV1],
        open_prices: Mapping[UUID7, ListingOpenPriceV1],
        execution_listings: Mapping[UUID7, ListingV1],
    ) -> RebalancePlanV1:
        """Price every non-zero target delta and test the complete rebalance."""
        with decimal_context():
            return self._plan_under_pinned_context(
                state=state,
                staged_targets=staged_targets,
                open_prices=open_prices,
                execution_listings=execution_listings,
            )

    def _plan_under_pinned_context(
        self,
        *,
        state: PortfolioStateV2,
        staged_targets: Sequence[SecurityTargetPositionV1],
        open_prices: Mapping[UUID7, ListingOpenPriceV1],
        execution_listings: Mapping[UUID7, ListingV1],
    ) -> RebalancePlanV1:
        targets = self._target_quantities(staged_targets)
        held = {holding.security_id: holding.quantity for holding in state.holdings}
        # The complete target set rule is applied once, at the strategy
        # boundary. If a held security is missing here, that rule was skipped
        # and a liquidation would silently vanish.
        uncovered = tuple(sorted(set(held) - set(targets), key=_security_order))
        if uncovered:
            # The evaluator cannot know whether the missing security was meant
            # to be held or liquidated, so this is indeterminate rather than a
            # bare ValueError outside the execution error taxonomy.
            raise IndeterminateExecutionError(
                f"staged targets must cover every held security, missing {uncovered[0]}"
            )

        fills: list[ExecutionFillV1] = []
        for security_id in sorted(set(targets) | set(held), key=_security_order):
            delta = targets[security_id] - held.get(security_id, 0)
            if delta == 0:
                continue
            fills.append(
                self._build_fill(
                    security_id=security_id,
                    delta=delta,
                    open_prices=open_prices,
                    execution_listings=execution_listings,
                )
            )
        planned_fills = canonical_fill_order(fills)
        sells = tuple(fill for fill in planned_fills if fill.side == "sell")
        buys = tuple(fill for fill in planned_fills if fill.side == "buy")

        gross_sell_proceeds = sum((fill.gross_notional for fill in sells), ZERO)
        sell_transaction_costs = sum((fill.transaction_costs for fill in sells), ZERO)
        required_cash = sum(
            (fill.gross_notional + fill.transaction_costs for fill in buys), ZERO
        )
        return RebalancePlanV1(
            session_key=state.session_key,
            planned_fills=planned_fills,
            opening_positions_hash=positions_digest(state.holdings),
            current_cash=state.cash_balance,
            gross_sell_proceeds=gross_sell_proceeds,
            sell_transaction_costs=sell_transaction_costs,
            required_cash=required_cash,
            projected_cash=(
                state.cash_balance
                + gross_sell_proceeds
                - sell_transaction_costs
                - required_cash
            ),
        )

    @staticmethod
    def _target_quantities(
        staged_targets: Sequence[SecurityTargetPositionV1],
    ) -> dict[UUID7, int]:
        targets: dict[UUID7, int] = {}
        for target in staged_targets:
            if target.target_quantity < 0:
                raise ValueError(
                    "staged target quantity must be non-negative, got "
                    f"{target.target_quantity} for {target.security_id}"
                )
            if target.security_id in targets:
                raise ValueError(
                    f"staged targets must be unique by security: {target.security_id}"
                )
            targets[target.security_id] = target.target_quantity
        return targets

    def _build_fill(
        self,
        *,
        security_id: UUID7,
        delta: int,
        open_prices: Mapping[UUID7, ListingOpenPriceV1],
        execution_listings: Mapping[UUID7, ListingV1],
    ) -> ExecutionFillV1:
        listing = execution_listings.get(security_id)
        if listing is None:
            raise IndeterminateExecutionError(
                f"no resolved execution listing for security {security_id}"
            )
        quoted = open_prices.get(security_id)
        # Never substitute a close or a prior open for a missing open.
        if quoted is None:
            raise IndeterminateExecutionError(
                f"no unadjusted open price for security {security_id}"
            )
        # A price is evidence about the listing it was observed on. A security
        # that migrated venues resolves to the new listing, and carrying over
        # the old listing's print would stamp the fill with a
        # (listing_id, venue, price) triple that never traded together.
        if quoted.listing_id != listing.listing_id:
            raise IndeterminateExecutionError(
                f"unadjusted open price for security {security_id} is bound to "
                f"listing {quoted.listing_id}, but execution resolved listing "
                f"{listing.listing_id}"
            )
        if quoted.venue is not listing.venue:
            raise IndeterminateExecutionError(
                f"unadjusted open price for security {security_id} is bound to "
                f"venue {quoted.venue.value}, but execution resolved venue "
                f"{listing.venue.value}"
            )
        open_price = quoted.unadjusted_open_price
        if not open_price.is_finite() or open_price <= ZERO:
            raise IndeterminateExecutionError(
                f"unadjusted open price must be strictly positive for security "
                f"{security_id}, got {open_price}"
            )

        side: Literal["buy", "sell"] = "buy" if delta > 0 else "sell"
        quantity = abs(delta)
        slippage = (
            self._cost_model.adverse_slippage_basis_points / BASIS_POINT_DENOMINATOR
        )
        fill_price = open_price * (ONE + slippage if side == "buy" else ONE - slippage)
        gross_notional = fill_price * quantity
        # The notional fee is charged on traded value at the unadjusted open,
        # not on the slipped fill price. Slippage is an execution shortfall,
        # not a fee base.
        transaction_costs = (
            quantity * self._cost_model.commission_per_share
            + self._cost_model.fixed_fee_per_order
            + quantity
            * open_price
            * self._cost_model.notional_fee_basis_points
            / BASIS_POINT_DENOMINATOR
        )
        cash_delta = (
            gross_notional - transaction_costs
            if side == "sell"
            else -(gross_notional + transaction_costs)
        )
        return ExecutionFillV1(
            security_id=security_id,
            listing_id=listing.listing_id,
            venue=listing.venue,
            side=side,
            quantity=quantity,
            unadjusted_open_price=open_price,
            fill_price=fill_price,
            gross_notional=gross_notional,
            transaction_costs=transaction_costs,
            cash_delta=cash_delta,
        )

    def execute(
        self, *, state: PortfolioStateV2, plan: RebalancePlanV1
    ) -> RebalanceOutcomeV2:
        """Commit the whole plan, or none of it."""
        if plan.session_key != state.session_key:
            raise ValueError(
                "plan session must match the portfolio session: plan "
                f"{plan.session_key.local_date}, state {state.session_key.local_date}"
            )
        if plan.current_cash != state.cash_balance:
            raise ValueError(
                "plan cash must match the portfolio cash balance: plan "
                f"{plan.current_cash}, state {state.cash_balance}"
            )
        # Every fill is a delta against the book the plan was computed on.
        # Committing it onto a different book silently changes the target
        # position the strategy asked for.
        if plan.opening_positions_hash != positions_digest(state.holdings):
            raise ValueError(
                "plan positions must match the portfolio holdings the plan was "
                "computed against"
            )
        if not plan.is_funded:
            return self._reject(state=state, plan=plan)
        _require_determinate_sells(state=state, plan=plan)
        return self._commit(state=state, plan=plan)

    @staticmethod
    def _reject(
        *, state: PortfolioStateV2, plan: RebalancePlanV1
    ) -> RebalanceOutcomeV2:
        with decimal_context():
            rejection = FillRejectionV1(
                session_key=plan.session_key,
                reason="insufficient_cash",
                current_cash=plan.current_cash,
                gross_sell_proceeds=plan.gross_sell_proceeds,
                sell_transaction_costs=plan.sell_transaction_costs,
                required_cash=plan.required_cash,
                projected_cash=plan.projected_cash,
                cash_shortfall=-plan.projected_cash,
            )
        return RebalanceOutcomeV2(
            classification="rejected",
            plan=plan,
            committed_fills=(),
            rejection=rejection,
            state=state,
            halt_stepping=True,
        )

    def _commit(
        self, *, state: PortfolioStateV2, plan: RebalancePlanV1
    ) -> RebalanceOutcomeV2:
        # The throwaway kernel is validated against the same authority-bound
        # clock as the real book. Synthesizing a clock here would defeat the
        # guard that a book cannot operate on an unauthorized session.
        kernel = PortfolioAccountingKernel(state, session_clock=self._session_clock)
        try:
            for fill in plan.planned_fills:
                kernel.apply_fill(fill.to_portfolio_fill())
        except Exception as error:
            # The kernel is local, so nothing reached the caller's state. Turn
            # a would-be partial application into a hard stop.
            raise AtomicRebalanceCommitError(
                f"funded rebalance could not be booked: {error}"
            ) from error
        return RebalanceOutcomeV2(
            classification="executed",
            plan=plan,
            committed_fills=plan.planned_fills,
            rejection=None,
            state=kernel.state,
            halt_stepping=False,
        )

    def rebalance(
        self,
        *,
        state: PortfolioStateV2,
        staged_targets: Sequence[SecurityTargetPositionV1],
        open_prices: Mapping[UUID7, ListingOpenPriceV1],
        execution_listings: Mapping[UUID7, ListingV1],
    ) -> RebalanceOutcomeV2:
        """Plan and atomically commit one next-open rebalance."""
        plan = self.plan(
            state=state,
            staged_targets=staged_targets,
            open_prices=open_prices,
            execution_listings=execution_listings,
        )
        return self.execute(state=state, plan=plan)
