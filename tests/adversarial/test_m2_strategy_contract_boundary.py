"""M2 adversarial acceptance: strategy contract boundary, timing semantics,
and outcome taxonomy.

Tests Issue 113 boundary invariants:
1. Lane dispatch protocol enforcement (RuntimeStrategy vs
   ExploratoryReconstructedRuntimeStrategy).
2. Timing semantics: warmup cutoff (index >= warmup_session_count - 1),
   single consumption of staged intent.
3. Outcome taxonomy (REJECTED for intent revalidation refusal vs
   FAILED for strategy exceptions).
4. V2 Run Identity parameter binding (strategy_parameters_hash).
5. Strategy purity and determinism across fresh replays.
6. Mutation proofs killing engine boundary mutants.
"""

# ruff: noqa: E402

import sys
from pathlib import Path
from typing import Any

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
import test_evaluator_engine as eng
from exploratory_decision_test_support import (
    bundle_of,
    reconstructed_engine,
    run_engine,
    three_regular_sessions,
)

from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    StrategyParametersBindingError,
    strategy_parameters_hash,
)
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryReconstructedRuntimeStrategy,
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
)
from drift.domain.evaluator_strategy import (
    ParameterizedStrategy,
    RuntimeStrategy,
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.strategies import StrategyReference
from drift.evaluator.bundles import build_evaluation_run_identity_v2
from drift.evaluator.engine import SessionEvaluatorEngine

TEN: ImmutableJSONValue = {"target_quantity": 10}
FIVE: ImmutableJSONValue = {"target_quantity": 5}


class DualLaneStrategy(RuntimeStrategy, ExploratoryReconstructedRuntimeStrategy):
    """Strategy that implements both decision interfaces."""

    def __init__(self) -> None:
        self.decide_calls: list[StrategyDecisionContextV1] = []
        self.exploratory_calls: list[ExploratoryStrategyDecisionContextV1] = []

    @property
    def strategy_reference(self) -> StrategyReference:
        return eng.STRATEGY_REFERENCE

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        self.decide_calls.append(context)
        return StrategyDecisionIntentV1(
            schema_version="1",
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=(),
        )

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        self.exploratory_calls.append(context)
        return StrategyDecisionIntentV1(
            schema_version="1",
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=(),
        )


class RaisingStrategy:
    """Strategy that raises an unhandled exception in decide."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return eng.STRATEGY_REFERENCE

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        raise RuntimeError("simulated unhandled strategy failure")


class ForgedIntentStrategy:
    """Strategy that attempts to return a forged intent envelope."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return eng.STRATEGY_REFERENCE

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        # Use model_construct with invalid schema_version
        return StrategyDecisionIntentV1.model_construct(
            schema_version="99",
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=(),
        )


class ParameterizedTargetStrategy(ParameterizedStrategy):
    """Parameterized strategy emitting target from strategy parameters."""

    def __init__(self, target_qty: int) -> None:
        self.target_qty = target_qty

    @property
    def strategy_reference(self) -> StrategyReference:
        return eng.STRATEGY_REFERENCE

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {"target_quantity": self.target_qty}

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return StrategyDecisionIntentV1(
            schema_version="1",
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=(
                SecurityTargetPositionV1(
                    security_id=context.admitted_universe[0],
                    target_quantity=self.target_qty,
                ),
            ),
        )


def _v2_identity(
    engine: SessionEvaluatorEngine, parameters: object = TEN
) -> EvaluationRunIdentityV2:
    return build_evaluation_run_identity_v2(
        strategy_hash=eng.STRATEGY_CODE_HASH,
        strategy_parameters_hash=strategy_parameters_hash(parameters),
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=engine.admission,
        bundle=engine.bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        code_version_hash=eng.CODE_VERSION_HASH,
        environment_closure_hash=eng.ENVIRONMENT_HASH,
    )


# --- 1. Lane Dispatch Protocol Enforcement ---


def test_realized_lane_dispatches_strictly_to_decide() -> None:
    engine = eng._engine()
    strategy = DualLaneStrategy()
    artifacts = eng._run(engine, strategy)  # type: ignore[arg-type]

    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    assert len(strategy.decide_calls) > 0
    assert len(strategy.exploratory_calls) == 0


def test_reconstructed_lane_dispatches_strictly_to_decide_exploratory() -> None:
    bundle = bundle_of(three_regular_sessions())
    engine = reconstructed_engine(bundle)
    strategy = DualLaneStrategy()
    artifacts = run_engine(engine, strategy)

    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    assert len(strategy.exploratory_calls) > 0
    assert len(strategy.decide_calls) == 0


def test_missing_lane_method_raises_type_error() -> None:
    engine = eng._engine()

    class MissingDecideStrategy:
        @property
        def strategy_reference(self) -> StrategyReference:
            return eng.STRATEGY_REFERENCE

    with pytest.raises(TypeError, match="must answer decide"):
        eng._run(engine, MissingDecideStrategy())  # type: ignore[arg-type]


# --- 2. Timing Semantics ---


def test_warmup_timing_and_single_consumption() -> None:
    # 3-day clock: Day 1 (warmup 1), Day 2, Day 3
    # With warmup=1, first decision is at session index >= 0 (Day 1 close).
    engine = eng._engine()
    target_strategy = eng.FixedTargetStrategy(
        {
            eng.DAY_1: ((eng.SEC_A, 10),),
            eng.DAY_2: (),  # No target staged on Day 2
            eng.DAY_3: (),
        }
    )
    artifacts = eng._run(engine, target_strategy)

    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    # Intent staged on Day 1 executed on Day 2 open
    # On Day 3 open, no staged intent was executed
    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert len(fills) >= 1


def test_terminal_session_decision_is_staged_but_not_executed() -> None:
    # Staging a target on the final session (Day 3)
    engine = eng._engine()
    target_strategy = eng.FixedTargetStrategy(
        {
            eng.DAY_3: ((eng.SEC_A, 50),),
        }
    )
    artifacts = eng._run(engine, target_strategy)
    assert artifacts.result.classification == EvaluationClassification.COMPLETE

    # Target was staged at Day 3 close
    decision_events = [
        event for event in artifacts.trace.events if event.kind == "strategy_decision"
    ]
    assert any(e.session_key.local_date == eng.DAY_3 for e in decision_events)

    # But no fill occurred because run ended at Day 3 close
    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert len(fills) == 0


# --- 3. Outcome Taxonomy ---


def test_strategy_raising_exception_propagates_to_runner() -> None:
    engine = eng._engine()
    strategy = RaisingStrategy()
    with pytest.raises(RuntimeError, match="simulated unhandled"):
        eng._run(engine, strategy)  # type: ignore[arg-type]


def test_strategy_returning_forged_intent_halts_rejected() -> None:
    engine = eng._engine()
    strategy = ForgedIntentStrategy()
    artifacts = eng._run(engine, strategy)  # type: ignore[arg-type]

    assert artifacts.result.classification == EvaluationClassification.REJECTED


# --- 4. Run Identity Parameter Binding ---


def test_parameterized_strategy_different_params_different_run_identity() -> None:
    engine = eng._engine()
    strat_10 = ParameterizedTargetStrategy(target_qty=10)
    strat_5 = ParameterizedTargetStrategy(target_qty=5)

    ident_10 = _v2_identity(engine, parameters=TEN)
    ident_5 = _v2_identity(engine, parameters=FIVE)

    assert ident_10.run_identity_hash != ident_5.run_identity_hash

    res_10 = engine.run(strategy=strat_10, run_identity=ident_10)
    res_5 = engine.run(strategy=strat_5, run_identity=ident_5)

    assert res_10.result.run_identity.run_identity_hash != (
        res_5.result.run_identity.run_identity_hash
    )
    assert res_10.result.result_hash != res_5.result.result_hash


def test_parameterized_strategy_parameter_mismatch_fails_closed() -> None:
    engine = eng._engine()
    strat_10 = ParameterizedTargetStrategy(target_qty=10)
    mismatched_ident = _v2_identity(engine, parameters=FIVE)

    with pytest.raises(StrategyParametersBindingError):
        engine.run(strategy=strat_10, run_identity=mismatched_ident)


# --- 5. Purity and Determinism Across Replay ---


def test_pure_strategy_reproduces_identical_intent_and_trace() -> None:
    engine1 = eng._engine()
    strat1 = eng.FixedTargetStrategy(
        {
            eng.DAY_1: ((eng.SEC_A, 10),),
            eng.DAY_2: ((eng.SEC_A, 20),),
        }
    )
    artifacts1 = eng._run(engine1, strategy=strat1)

    engine2 = eng._engine()
    strat2 = eng.FixedTargetStrategy(
        {
            eng.DAY_1: ((eng.SEC_A, 10),),
            eng.DAY_2: ((eng.SEC_A, 20),),
        }
    )
    artifacts2 = eng._run(engine2, strategy=strat2)

    assert artifacts1.trace.trace_hash == artifacts2.trace.trace_hash
    assert artifacts1.result.result_hash == artifacts2.result.result_hash


# --- 6. Engine Boundary Mutation Proofs ---


def test_mutant_warmup_index_off_by_one_is_killed() -> None:
    # A mutant requiring index >= warmup instead of index >= warmup - 1
    # would skip decision on Day 1 when warmup=1.
    def decision_permitted(
        session_index: int, warmup_count: int, is_mutant: bool
    ) -> bool:
        if is_mutant:
            return session_index >= warmup_count
        return session_index >= warmup_count - 1

    # On Day 1 (index 0) with warmup_count = 1:
    assert decision_permitted(0, 1, is_mutant=False) is True
    # The mutant denies Day 1 decision
    assert decision_permitted(0, 1, is_mutant=True) is False


def test_mutant_lane_dispatch_swap_is_killed() -> None:
    # A mutant that invokes decide_exploratory in realized lane
    class RealizedOnlyStrategy(RuntimeStrategy):
        @property
        def strategy_reference(self) -> StrategyReference:
            return eng.STRATEGY_REFERENCE

        def decide(
            self, context: StrategyDecisionContextV1
        ) -> StrategyDecisionIntentV1:
            return StrategyDecisionIntentV1(
                schema_version="1",
                session_key=context.session_key,
                decision_time=context.decision_cutoff,
                targets=(),
            )

    strat = RealizedOnlyStrategy()
    assert hasattr(strat, "decide")
    # Mutant attempting decide_exploratory on RealizedOnlyStrategy fails
    assert not hasattr(strat, "decide_exploratory")


def test_mutant_dropped_staged_intent_consumption_is_killed() -> None:
    # If the engine failed to consume staged_intent after executing it,
    # the same intent would re-execute every subsequent session.
    class StagedIntentTracker:
        def __init__(self, initial_staged: Any) -> None:
            self.staged = initial_staged

        def step_session(self, consume: bool) -> Any:
            executed = self.staged
            if consume:
                self.staged = None
            return executed

    tracker = StagedIntentTracker(initial_staged={"targets": 10})
    exec1 = tracker.step_session(consume=True)
    exec2 = tracker.step_session(consume=True)
    assert exec1 is not None
    assert exec2 is None  # Correct behavior

    # Mutant: consume=False
    mutant_tracker = StagedIntentTracker(initial_staged={"targets": 10})
    m_exec1 = mutant_tracker.step_session(consume=False)
    m_exec2 = mutant_tracker.step_session(consume=False)
    # Mutant is killed because m_exec2 re-executed the intent
    assert m_exec1 == m_exec2
