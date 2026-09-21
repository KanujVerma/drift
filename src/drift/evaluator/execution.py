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

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.common import UUID7
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_execution import (
    BASIS_POINT_DENOMINATOR,
    ZERO,
    AtomicRebalanceCommitError,
    ExecutionFillV1,
    FillRejectionV1,
    IndeterminateExecutionError,
    RebalanceOutcomeV1,
    RebalancePlanV1,
    positions_digest,
)
from drift.domain.evaluator_portfolio import PortfolioStateV1, decimal_context
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.securities import ListingRole, ListingRoleVersionV1, ListingV1
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


def resolve_execution_listing(
    *,
    security_id: UUID7,
    execution_session: EvaluationSessionV1,
    role_records: Sequence[ListingRoleVersionV1],
    listings: Sequence[ListingV1],
) -> ListingV1:
    """Resolve the active historical primary execution listing for a security.

    Resolution is as of the execution session open, so a security that
    migrated venues between decision and execution executes on the listing
    that was primary at execution time. Anything short of a unique, provable
    answer fails closed.
    """
    instant = execution_session.opened_at
    candidates = tuple(
        record for record in role_records if record.security_id == security_id
    )
    active_listing_ids: set[UUID] = set()
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
        if record.role is ListingRole.PRIMARY:
            active_listing_ids.add(record.listing_id)

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
) -> dict[UUID7, ListingV1]:
    """Resolve one execution listing per security, failing closed on any gap."""
    return {
        security_id: resolve_execution_listing(
            security_id=security_id,
            execution_session=execution_session,
            role_records=role_records,
            listings=listings,
        )
        for security_id in sorted(set(security_ids), key=_security_order)
    }


class AtomicRebalanceEngine:
    """Plans and atomically commits one next-open rebalance.

    The engine never mutates the state handed to it. A commit is built against
    a throwaway accounting kernel, so a plan that cannot be booked leaves the
    caller holding exactly the state it passed in.
    """

    def __init__(self, *, cost_model: EvaluationCostModelV1) -> None:
        self._cost_model = cost_model

    @property
    def cost_model(self) -> EvaluationCostModelV1:
        """The versioned cost and slippage model applied to every fill."""
        return self._cost_model

    def plan(
        self,
        *,
        state: PortfolioStateV1,
        staged_targets: Sequence[SecurityTargetPositionV1],
        open_prices: Mapping[UUID7, Decimal],
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
        state: PortfolioStateV1,
        staged_targets: Sequence[SecurityTargetPositionV1],
        open_prices: Mapping[UUID7, Decimal],
        execution_listings: Mapping[UUID7, ListingV1],
    ) -> RebalancePlanV1:
        targets = self._target_quantities(staged_targets)
        held = {holding.security_id: holding.quantity for holding in state.holdings}
        # The complete target set rule is applied once, at the strategy
        # boundary. If a held security is missing here, that rule was skipped
        # and a liquidation would silently vanish.
        uncovered = tuple(sorted(set(held) - set(targets), key=_security_order))
        if uncovered:
            raise ValueError(
                f"staged targets must cover every held security, missing {uncovered[0]}"
            )

        sells: list[ExecutionFillV1] = []
        buys: list[ExecutionFillV1] = []
        for security_id in sorted(set(targets) | set(held), key=_security_order):
            delta = targets[security_id] - held.get(security_id, 0)
            if delta == 0:
                continue
            fill = self._build_fill(
                security_id=security_id,
                delta=delta,
                open_prices=open_prices,
                execution_listings=execution_listings,
            )
            (buys if delta > 0 else sells).append(fill)

        gross_sell_proceeds = sum((fill.gross_notional for fill in sells), ZERO)
        sell_transaction_costs = sum((fill.transaction_costs for fill in sells), ZERO)
        required_cash = sum(
            (fill.gross_notional + fill.transaction_costs for fill in buys), ZERO
        )
        return RebalancePlanV1(
            session_key=state.session_key,
            planned_fills=tuple(sells) + tuple(buys),
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
        open_prices: Mapping[UUID7, Decimal],
        execution_listings: Mapping[UUID7, ListingV1],
    ) -> ExecutionFillV1:
        open_price = open_prices.get(security_id)
        # Never substitute a close or a prior open for a missing open.
        if open_price is None:
            raise IndeterminateExecutionError(
                f"no unadjusted open price for security {security_id}"
            )
        if not open_price.is_finite() or open_price <= ZERO:
            raise IndeterminateExecutionError(
                f"unadjusted open price must be strictly positive for security "
                f"{security_id}, got {open_price}"
            )
        listing = execution_listings.get(security_id)
        if listing is None:
            raise IndeterminateExecutionError(
                f"no resolved execution listing for security {security_id}"
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
        self, *, state: PortfolioStateV1, plan: RebalancePlanV1
    ) -> RebalanceOutcomeV1:
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
        return self._commit(state=state, plan=plan)

    @staticmethod
    def _reject(
        *, state: PortfolioStateV1, plan: RebalancePlanV1
    ) -> RebalanceOutcomeV1:
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
        return RebalanceOutcomeV1(
            classification="rejected",
            plan=plan,
            committed_fills=(),
            rejection=rejection,
            state=state,
            halt_stepping=True,
        )

    @staticmethod
    def _commit(
        *, state: PortfolioStateV1, plan: RebalancePlanV1
    ) -> RebalanceOutcomeV1:
        kernel = PortfolioAccountingKernel(state)
        try:
            for fill in plan.planned_fills:
                kernel.apply_fill(fill.to_portfolio_fill())
        except Exception as error:
            # The kernel is local, so nothing reached the caller's state. Turn
            # a would-be partial application into a hard stop.
            raise AtomicRebalanceCommitError(
                f"funded rebalance could not be booked: {error}"
            ) from error
        return RebalanceOutcomeV1(
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
        state: PortfolioStateV1,
        staged_targets: Sequence[SecurityTargetPositionV1],
        open_prices: Mapping[UUID7, Decimal],
        execution_listings: Mapping[UUID7, ListingV1],
    ) -> RebalanceOutcomeV1:
        """Plan and atomically commit one next-open rebalance."""
        plan = self.plan(
            state=state,
            staged_targets=staged_targets,
            open_prices=open_prices,
            execution_listings=execution_listings,
        )
        return self.execute(state=state, plan=plan)
