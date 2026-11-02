"""Book declared synthetic partial quantities through the original M2 kernel."""

from collections.abc import Mapping

from drift.domain.common import UUID7
from drift.domain.evaluator_clock import SessionClockV1
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_execution import (
    IndeterminateExecutionError,
    ListingOpenPriceV1,
    RebalancePlanV1,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.securities import ListingV1
from drift.domain.synthetic_execution import (
    SyntheticExecutionPolicyV1,
    SyntheticExecutionReceiptV1,
    SyntheticExecutionSelectionV1,
    SyntheticOrderSelectionV1,
)
from drift.evaluator.execution import AtomicRebalanceEngine
from drift.serialization.canonical import canonical_json, content_hash


def select_synthetic_execution(
    *,
    policy: SyntheticExecutionPolicyV1,
    session_index: int,
    preview_hash: str,
    plan: RebalancePlanV1,
    invocation_id: UUID7 | None = None,
) -> SyntheticExecutionSelectionV1:
    """Resolve a frozen scenario against the actual original complete plan."""
    policy = SyntheticExecutionPolicyV1.model_validate_json(canonical_json(policy))
    plan = RebalancePlanV1.model_validate_json(canonical_json(plan))
    if type(session_index) is not int or session_index < 0:
        raise ValueError("SYNTHETIC_EXECUTION_SESSION_INDEX")
    session_spec = next(
        (item for item in policy.sessions if item.session_index == session_index),
        None,
    )
    overrides = (
        {item.order_index: item for item in session_spec.orders}
        if session_spec is not None
        else {}
    )
    if any(index >= len(plan.planned_fills) for index in overrides):
        raise ValueError("SYNTHETIC_FILL_SPEC_UNKNOWN_ORDER")
    orders: list[SyntheticOrderSelectionV1] = []
    for index, fill in enumerate(plan.planned_fills):
        override = overrides.get(index)
        orders.append(
            SyntheticOrderSelectionV1(
                security_id=fill.security_id,
                requested_quantity=fill.quantity,
                verified_filled_quantity=(
                    override.verified_filled_quantity if override else fill.quantity
                ),
                status=override.status if override else "FILLED",
            )
        )
    return SyntheticExecutionSelectionV1(
        preview_hash=preview_hash,
        plan_hash=content_hash(plan),
        policy_hash=policy.policy_hash,
        orders=tuple(orders),
        invocation_id=invocation_id,
    )


def execute_synthetic_selection(
    *,
    state: PortfolioStateV2,
    requested_plan: RebalancePlanV1,
    selection: SyntheticExecutionSelectionV1,
    preview_hash: str,
    open_prices: Mapping[UUID7, ListingOpenPriceV1],
    execution_listings: Mapping[UUID7, ListingV1],
    cost_model: EvaluationCostModelV1,
    session_clock: SessionClockV1,
    invocation_id: UUID7 | None = None,
) -> SyntheticExecutionReceiptV1:
    """Compute actual fills and state without upgrading the complete intent.

    The subset is funded independently. An unconfirmed sell cannot finance a
    confirmed buy. Prices and fees are recomputed by the same atomic engine;
    callers cannot supply an alternate account, fill price or accounting rule.
    The returned state is immutable and is assigned by the original evaluator.
    """
    state = PortfolioStateV2.model_validate_json(canonical_json(state))
    requested_plan = RebalancePlanV1.model_validate_json(canonical_json(requested_plan))
    selection = SyntheticExecutionSelectionV1.model_validate_json(
        canonical_json(selection)
    )
    cost_model = EvaluationCostModelV1.model_validate_json(canonical_json(cost_model))
    session_clock = SessionClockV1.model_validate_json(canonical_json(session_clock))
    if selection.preview_hash != preview_hash:
        raise ValueError("SYNTHETIC_EXECUTION_WRONG_PREVIEW")
    if selection.invocation_id != invocation_id:
        raise ValueError("SYNTHETIC_EXECUTION_WRONG_INVOCATION")
    if selection.plan_hash != content_hash(requested_plan):
        raise ValueError("SYNTHETIC_EXECUTION_WRONG_PLAN")
    if len(selection.orders) != len(requested_plan.planned_fills):
        raise ValueError("SYNTHETIC_EXECUTION_ORDER_INVENTORY")
    requested_targets = {
        holding.security_id: holding.quantity for holding in state.holdings
    }
    actual_targets = dict(requested_targets)
    for selected, original in zip(
        selection.orders, requested_plan.planned_fills, strict=True
    ):
        if (
            selected.security_id != original.security_id
            or selected.requested_quantity != original.quantity
        ):
            raise ValueError("SYNTHETIC_EXECUTION_WRONG_ORDER")
        sign = 1 if original.side == "buy" else -1
        security_id = original.security_id
        requested_targets[security_id] = (
            requested_targets.get(security_id, 0) + sign * original.quantity
        )
        actual_targets[security_id] = (
            actual_targets.get(security_id, 0)
            + sign * selected.verified_filled_quantity
        )
    engine = AtomicRebalanceEngine(cost_model=cost_model, session_clock=session_clock)

    def plan_targets(targets: dict[UUID7, int]) -> RebalancePlanV1:
        return engine.plan(
            state=state,
            staged_targets=tuple(
                SecurityTargetPositionV1(
                    security_id=security_id, target_quantity=quantity
                )
                for security_id, quantity in sorted(
                    targets.items(), key=lambda item: item[0].bytes
                )
            ),
            open_prices=open_prices,
            execution_listings=execution_listings,
        )

    # Even a self-consistent caller plan must match the original prices, costs,
    # listing authority and actual starting book before it can be committed.
    if plan_targets(requested_targets) != requested_plan:
        raise ValueError("SYNTHETIC_EXECUTION_REQUESTED_PLAN_NOT_REPRODUCIBLE")
    if not requested_plan.is_funded:
        raise IndeterminateExecutionError("SYNTHETIC_EXECUTION_UNFUNDED_REQUEST")
    actual_plan = plan_targets(actual_targets)
    if not actual_plan.is_funded:
        raise IndeterminateExecutionError("SYNTHETIC_VERIFIED_FILLS_UNFUNDED")
    outcome = engine.execute(state=state, plan=actual_plan)
    if outcome.classification != "executed":  # pragma: no cover - funded invariant
        raise IndeterminateExecutionError("SYNTHETIC_ACTUAL_PLAN_NOT_EXECUTED")
    return SyntheticExecutionReceiptV1(
        selection=selection,
        requested_plan=requested_plan,
        actual_plan=actual_plan,
        committed_fills=outcome.committed_fills,
        before_state_hash=content_hash(state),
        cost_model_hash=cost_model.cost_model_hash,
        state=outcome.state,
    )
