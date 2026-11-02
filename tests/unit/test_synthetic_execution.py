"""Actual partial quantities and protective dispatch on the original M2 book."""

from decimal import Decimal, localcontext
from typing import Literal

import pytest
import test_evaluator_engine as engine_case
import test_evaluator_execution as execution_case
from observation_test_support import uid
from pydantic import ValidationError

from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_execution import (
    IndeterminateExecutionError,
    RebalanceOutcomeV2,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.synthetic_execution import (
    SyntheticExecutionPolicyV1,
    SyntheticExecutionReceiptV1,
    SyntheticExecutionSelectionV1,
    SyntheticOrderFillSpecV1,
    SyntheticOrderSelectionV1,
    SyntheticSessionFillSpecV1,
)
from drift.evaluator.execution import AtomicRebalanceEngine
from drift.evaluator.session_observer import (
    ExecutionAuthorizationV1,
    ProtectiveExecutionContextV1,
    ProtectiveTargetProposalV1,
    RebalancePreviewV1,
    SessionObservationV1,
    SyntheticExecutionObservationV1,
)
from drift.evaluator.synthetic_execution import (
    execute_synthetic_selection,
    select_synthetic_execution,
)
from drift.serialization.canonical import content_hash

PREVIEW_HASH = "a" * 64


def policy_with(
    *orders: SyntheticOrderFillSpecV1, session_index: int = 2
) -> SyntheticExecutionPolicyV1:
    return SyntheticExecutionPolicyV1(
        policy_id="explicit-unit-synthetic-execution",
        sessions=(
            SyntheticSessionFillSpecV1(session_index=session_index, orders=orders),
        )
        if orders
        else (),
    )


def test_actual_partial_sell_full_buy_and_unknown_order_keep_real_book() -> None:
    case = execution_case
    state = case._state(cash="500", holdings=(case._holding(case.SEC_A, 10, "1000"),))
    prices = {
        case.SEC_A: case._price("100"),
        case.SEC_B: case._price("50"),
        case.SEC_C: case._price("20"),
    }
    listings = case._listings_for(case.SEC_A, case.SEC_B, case.SEC_C)
    engine = AtomicRebalanceEngine(
        cost_model=case.FEE_ONLY, session_clock=case._clock()
    )
    plan = engine.plan(
        state=state,
        staged_targets=(
            case._target(case.SEC_A, 0),
            case._target(case.SEC_B, 4),
            case._target(case.SEC_C, 3),
        ),
        open_prices=prices,
        execution_listings=listings,
    )
    policy = policy_with(
        SyntheticOrderFillSpecV1(
            order_index=0, verified_filled_quantity=4, status="PARTIAL"
        ),
        SyntheticOrderFillSpecV1(
            order_index=1, verified_filled_quantity=0, status="UNKNOWN"
        ),
    )
    selected = select_synthetic_execution(
        policy=policy, session_index=2, preview_hash=PREVIEW_HASH, plan=plan
    )
    with localcontext() as ambient:
        ambient.prec = 5
        receipt = execute_synthetic_selection(
            state=state,
            requested_plan=plan,
            selection=selected,
            preview_hash=PREVIEW_HASH,
            open_prices=prices,
            execution_listings=listings,
            cost_model=case.FEE_ONLY,
            session_clock=case._clock(),
        )
    assert not receipt.complete
    assert receipt.requested_plan == plan
    assert receipt.actual_plan != plan
    assert [(fill.security_id, fill.quantity) for fill in receipt.committed_fills] == [
        (case.SEC_A, 4),
        (case.SEC_C, 3),
    ]
    assert receipt.state.cash_balance == Decimal("838")
    assert {
        holding.security_id: holding.quantity for holding in receipt.state.holdings
    } == {
        case.SEC_A: 6,
        case.SEC_C: 3,
    }
    assert receipt.verified_fill_count == 2
    assert receipt.verified_filled_quantity == 7
    assert receipt.verified_execution_costs == Decimal("2")
    assert receipt.state.cumulative_transaction_costs == Decimal("2")
    assert receipt.unresolved_order_count == 2
    assert [order.unresolved_quantity for order in receipt.selection.orders] == [
        6,
        4,
        0,
    ]
    assert state.cash_balance == Decimal("500")
    assert state.holdings[0].quantity == 10


def single_order_receipt(
    *, status: Literal["FILLED", "PARTIAL", "UNFILLED", "UNKNOWN"], quantity: int
) -> tuple[SyntheticExecutionReceiptV1, RebalanceOutcomeV2]:
    case = execution_case
    state = case._state()
    prices, listings = {case.SEC_A: case._price("100")}, case._listings_for(case.SEC_A)
    engine = AtomicRebalanceEngine(
        cost_model=case.FEE_ONLY, session_clock=case._clock()
    )
    outcome = engine.rebalance(
        state=state,
        staged_targets=(case._target(case.SEC_A, 10),),
        open_prices=prices,
        execution_listings=listings,
    )
    policy = policy_with(
        SyntheticOrderFillSpecV1(
            order_index=0, verified_filled_quantity=quantity, status=status
        )
    )
    selection = select_synthetic_execution(
        policy=policy, session_index=2, preview_hash=PREVIEW_HASH, plan=outcome.plan
    )
    receipt = execute_synthetic_selection(
        state=state,
        requested_plan=outcome.plan,
        selection=selection,
        preview_hash=PREVIEW_HASH,
        open_prices=prices,
        execution_listings=listings,
        cost_model=case.FEE_ONLY,
        session_clock=case._clock(),
    )
    return receipt, outcome


def test_full_selection_matches_the_existing_atomic_outcome() -> None:
    receipt, original = single_order_receipt(status="FILLED", quantity=10)
    assert receipt.complete
    assert receipt.committed_fills == original.committed_fills
    assert receipt.state == original.state
    assert receipt.actual_plan == original.plan
    assert receipt.unresolved_order_count == 0


def test_known_unfilled_and_unknown_zero_are_distinct_and_charge_no_fill_fee() -> None:
    known, _ = single_order_receipt(status="UNFILLED", quantity=0)
    unknown, _ = single_order_receipt(status="UNKNOWN", quantity=0)
    assert known.state == unknown.state
    assert known.state.cash_balance == Decimal("10000")
    assert known.verified_execution_costs == unknown.verified_execution_costs == 0
    assert known.committed_fills == unknown.committed_fills == ()
    assert not known.complete and not unknown.complete
    assert known.unresolved_order_count == 0
    assert unknown.unresolved_order_count == 1
    assert known.selection.orders[0].known_unfilled_quantity == 10
    assert unknown.selection.orders[0].known_unfilled_quantity == 0
    assert unknown.selection.orders[0].unresolved_quantity == 10


@pytest.mark.parametrize(
    ("status", "quantity"),
    [
        ("FILLED", 9),
        ("PARTIAL", 0),
        ("PARTIAL", 10),
        ("UNKNOWN", 10),
        ("UNFILLED", 1),
        ("FILLED", 11),
        ("PARTIAL", -1),
    ],
)
def test_order_status_and_quantity_conservation_are_enforced(
    status: str, quantity: int
) -> None:
    with pytest.raises(ValidationError):
        SyntheticOrderSelectionV1.model_validate(
            {
                "security_id": execution_case.SEC_A,
                "requested_quantity": 10,
                "verified_filled_quantity": quantity,
                "status": status,
            }
        )


def test_unconfirmed_sale_cannot_finance_a_confirmed_purchase() -> None:
    case = execution_case
    state = case._state(cash="0", holdings=(case._holding(case.SEC_A, 10, "1000"),))
    prices = {case.SEC_A: case._price("100"), case.SEC_B: case._price("50")}
    listings = case._listings_for(case.SEC_A, case.SEC_B)
    engine = AtomicRebalanceEngine(
        cost_model=case.FEE_ONLY, session_clock=case._clock()
    )
    plan = engine.plan(
        state=state,
        staged_targets=(case._target(case.SEC_A, 0), case._target(case.SEC_B, 15)),
        open_prices=prices,
        execution_listings=listings,
    )
    assert plan.is_funded
    selected = select_synthetic_execution(
        policy=policy_with(
            SyntheticOrderFillSpecV1(
                order_index=0, verified_filled_quantity=1, status="PARTIAL"
            )
        ),
        session_index=2,
        preview_hash=PREVIEW_HASH,
        plan=plan,
    )
    with pytest.raises(IndeterminateExecutionError, match="VERIFIED_FILLS_UNFUNDED"):
        execute_synthetic_selection(
            state=state,
            requested_plan=plan,
            selection=selected,
            preview_hash=PREVIEW_HASH,
            open_prices=prices,
            execution_listings=listings,
            cost_model=case.FEE_ONLY,
            session_clock=case._clock(),
        )
    assert state.cash_balance == 0
    assert state.holdings[0].quantity == 10


@pytest.mark.parametrize(
    "mutation", ["preview", "plan", "invocation", "order", "quantity"]
)
def test_crossed_execution_selection_refuses_before_commit(mutation: str) -> None:
    case = execution_case
    state = case._state()
    prices, listings = {case.SEC_A: case._price("100")}, case._listings_for(case.SEC_A)
    engine = AtomicRebalanceEngine(
        cost_model=case.FEE_ONLY, session_clock=case._clock()
    )
    plan = engine.plan(
        state=state,
        staged_targets=(case._target(case.SEC_A, 10),),
        open_prices=prices,
        execution_listings=listings,
    )
    original = select_synthetic_execution(
        policy=policy_with(), session_index=2, preview_hash=PREVIEW_HASH, plan=plan
    )
    payload = original.model_dump(mode="python")
    if mutation in ("preview", "plan"):
        payload[mutation + "_hash"] = "b" * 64
    elif mutation == "invocation":
        payload["invocation_id"] = uid(891)
    else:
        orders = [dict(item) for item in payload["orders"]]
        if mutation == "order":
            orders[0]["security_id"] = case.SEC_B
        else:
            orders[0]["requested_quantity"] = 11
            orders[0]["verified_filled_quantity"] = 11
        payload["orders"] = tuple(orders)
    selected = SyntheticExecutionSelectionV1.model_validate(payload)
    with pytest.raises(ValueError, match="SYNTHETIC_EXECUTION_WRONG"):
        execute_synthetic_selection(
            state=state,
            requested_plan=plan,
            selection=selected,
            preview_hash=PREVIEW_HASH,
            open_prices=prices,
            execution_listings=listings,
            cost_model=case.FEE_ONLY,
            session_clock=case._clock(),
        )
    assert state.holdings == ()


class ExecutionObserver:
    def __init__(self, policy: SyntheticExecutionPolicyV1) -> None:
        self.policy = policy
        self.observed: list[SyntheticExecutionObservationV1] = []
        self.verdict: Literal["approve", "reject", "contain"] = "approve"

    def observe_session(self, observation: SessionObservationV1) -> None:
        pass

    def authorize_rebalance(
        self, preview: RebalancePreviewV1
    ) -> ExecutionAuthorizationV1:
        return ExecutionAuthorizationV1(
            preview_hash=preview.financial_hash,
            policy_hash="b" * 64,
            verdict=self.verdict,
            reason="Explicit unit synthetic authorization",
        )

    def select_execution(
        self, preview: RebalancePreviewV1
    ) -> SyntheticExecutionSelectionV1:
        return select_synthetic_execution(
            policy=self.policy,
            session_index=preview.session_index,
            preview_hash=preview.financial_hash,
            plan=preview.outcome.plan,
            invocation_id=preview.invocation_binding.invocation_id
            if preview.invocation_binding
            else None,
        )

    def observe_execution(self, observation: SyntheticExecutionObservationV1) -> None:
        self.observed.append(observation)


def run_engine(
    observer: ExecutionObserver | None,
    strategy: engine_case.FixedTargetStrategy | None = None,
) -> EvaluationRunArtifactsV2:
    engine = engine_case._engine(cost_model=engine_case._cost_model(fixed_fee="1"))
    return engine.run(
        strategy=strategy or engine_case._buy_ten(),
        run_identity=engine_case._run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
        session_observer=observer,
    )


def test_original_engine_partial_commit_halts_and_keeps_last_close_metrics() -> None:
    observer = ExecutionObserver(
        policy_with(
            SyntheticOrderFillSpecV1(
                order_index=0, verified_filled_quantity=4, status="PARTIAL"
            )
        )
    )
    actual = run_engine(observer)
    assert actual.result.classification == EvaluationClassification.INDETERMINATE
    assert actual.result.halted_session_index == 2
    assert actual.final_state.mark is None
    assert actual.final_state.holdings[0].quantity == 4
    assert actual.final_state.cash_balance == Decimal("9599")
    assert actual.final_state.cumulative_transaction_costs == 1
    assert actual.result.metrics.committed_fill_count == 0
    assert actual.result.metrics.cumulative_transaction_costs == 0
    assert actual.result.metrics.ending_net_asset_value == Decimal("10000")
    fills = [event.fill for event in actual.trace.events if event.kind == "fill"]
    assert len(fills) == 1 and fills[0].quantity == 4
    assert len(observer.observed) == 1
    assert observer.observed[0].receipt.committed_fills == tuple(fills)
    assert observer.observed[0].receipt.state == actual.final_state


def test_full_extension_preserves_existing_accounting_and_default_has_no_receipts() -> (
    None
):
    observer = ExecutionObserver(policy_with())
    actual, legacy = run_engine(observer), run_engine(None)
    assert actual.final_state == legacy.final_state
    assert actual.result.metrics == legacy.result.metrics
    assert observer.observed and all(
        item.receipt.complete for item in observer.observed
    )


def test_postcommit_receipt_failure_cannot_erase_actual_partial_fills() -> None:
    class LostAcknowledgement(ExecutionObserver):
        def observe_execution(
            self, observation: SyntheticExecutionObservationV1
        ) -> None:
            super().observe_execution(observation)
            raise OSError("Original receipt committed, acknowledgement lost")

    observer = LostAcknowledgement(
        policy_with(
            SyntheticOrderFillSpecV1(
                order_index=0, verified_filled_quantity=4, status="PARTIAL"
            )
        )
    )
    actual = run_engine(observer)
    assert actual.result.classification == EvaluationClassification.INDETERMINATE
    assert actual.result.halt_reason == "SYNTHETIC_EXECUTION_RECEIPT_RETENTION_FAILED"
    assert actual.final_state.holdings[0].quantity == 4
    assert actual.final_state.cumulative_transaction_costs == 1
    assert len(observer.observed) == 1
    assert observer.observed[0].receipt.state == actual.final_state
    assert sum(event.kind == "fill" for event in actual.trace.events) == 1


def test_precommit_refusal_never_calls_synthetic_execution() -> None:
    class NoDispatch(ExecutionObserver):
        def select_execution(
            self, preview: RebalancePreviewV1
        ) -> SyntheticExecutionSelectionV1:
            raise AssertionError("Refused order must never dispatch")

    observer = NoDispatch(policy_with())
    observer.verdict = "reject"
    actual = run_engine(observer)
    assert actual.final_state.holdings == ()
    assert observer.observed == []
    assert actual.final_state.cash_balance == Decimal("10000")


def test_execution_observer_cannot_mutate_the_committed_original_book() -> None:
    class MutatingReceipt(ExecutionObserver):
        def observe_execution(
            self, observation: SyntheticExecutionObservationV1
        ) -> None:
            object.__setattr__(observation.receipt.state, "cash_balance", Decimal("1"))

    actual = run_engine(MutatingReceipt(policy_with()))
    assert actual.final_state == run_engine(None).final_state


class ProtectiveObserver(ExecutionObserver):
    def __init__(self) -> None:
        super().__init__(policy_with())
        self.contexts: list[ProtectiveExecutionContextV1] = []
        self.target_quantity = 4
        self.wrong_context = False

    def requires_protective_execution(
        self, session_index: int, session: EvaluationSessionV1
    ) -> bool:
        return session_index == 3

    def propose_protective_targets(
        self, context: ProtectiveExecutionContextV1
    ) -> ProtectiveTargetProposalV1:
        self.contexts.append(context)
        return ProtectiveTargetProposalV1(
            context_hash="f" * 64 if self.wrong_context else context.financial_hash,
            policy_hash="d" * 64,
            targets=(
                SecurityTargetPositionV1(
                    security_id=engine_case.SEC_A, target_quantity=self.target_quantity
                ),
            ),
            reason="Explicit protective whole-share unit correction",
        )


def test_protective_sell_supersedes_strategy_buy_in_one_original_open_batch() -> None:
    observer = ProtectiveObserver()
    strategy = engine_case.FixedTargetStrategy(
        {
            engine_case.DAY_1: ((engine_case.SEC_A, 10),),
            engine_case.DAY_2: ((engine_case.SEC_A, 20),),
            engine_case.DAY_3: ((engine_case.SEC_A, 4),),
        }
    )
    actual = run_engine(observer, strategy)
    assert actual.result.classification == EvaluationClassification.COMPLETE
    assert actual.final_state.holdings[0].quantity == 4
    assert actual.final_state.cash_balance == Decimal("9658")
    assert [
        (item.purpose, tuple(fill.quantity for fill in item.receipt.committed_fills))
        for item in observer.observed
    ] == [("strategy", (10,)), ("protective", (6,))]
    assert observer.observed[-1].protective_policy_hash == "d" * 64
    assert observer.contexts[0].before_state.mark is None
    assert observer.contexts[0].staged_targets[0].target_quantity == 20
    assert observer.contexts[0].execution_listings[0].security_id == engine_case.SEC_A
    fills = [event.fill for event in actual.trace.events if event.kind == "fill"]
    assert [(fill.side, fill.quantity) for fill in fills] == [("buy", 10), ("sell", 6)]


@pytest.mark.parametrize("mutation", ["buy", "context"])
def test_protective_hook_refuses_risk_increase_and_wrong_original_context(
    mutation: str,
) -> None:
    observer = ProtectiveObserver()
    if mutation == "buy":
        observer.target_quantity = 11
    else:
        observer.wrong_context = True
    with pytest.raises(ValueError, match="PROTECTIVE_TARGETS"):
        run_engine(observer)
    assert len(observer.observed) == 1
    assert observer.observed[0].purpose == "strategy"


def test_duplicate_order_or_session_specs_cannot_change_scenario_meaning() -> None:
    spec = SyntheticOrderFillSpecV1(
        order_index=0, verified_filled_quantity=0, status="UNKNOWN"
    )
    with pytest.raises(ValidationError, match="ORDER_IDENTITIES"):
        policy_with(spec, spec)
    session = SyntheticSessionFillSpecV1(session_index=2, orders=(spec,))
    with pytest.raises(ValidationError, match="SESSION_IDENTITIES"):
        SyntheticExecutionPolicyV1(policy_id="duplicate", sessions=(session, session))


def test_self_consistent_receipt_cannot_hide_foreign_original_order() -> None:
    receipt, _ = single_order_receipt(status="PARTIAL", quantity=4)
    payload = receipt.model_dump(mode="python")
    payload["selection"]["orders"][0]["security_id"] = execution_case.SEC_B
    with pytest.raises(ValidationError, match="WRONG_ORIGINAL_ORDER"):
        type(receipt).model_validate(payload)
    assert receipt.before_state_hash == content_hash(execution_case._state())
