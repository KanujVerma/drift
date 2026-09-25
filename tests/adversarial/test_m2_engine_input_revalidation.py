"""M2 adversarial acceptance: the engine revalidates every input it runs on.

Issue 78, from the #8 final acceptance review (finding F6). Pydantic trusts an
existing model instance placed in a typed field, so an input built with
``model_construct`` is never checked unless something revalidates it. The
engine compared declared hashes only: a bundle could keep a genuine
``bundle_hash`` over different prices, and a raw vendor payload could ride a
typed field into ``RuntimeStrategy.decide``. Every input is now revalidated
through its canonical validated boundary at construction.

Issue 111 closes the same gap on the way out. The intent a strategy returns
was staged as returned, so a forged envelope was staged under a schema nobody
enforced. It is now revalidated before staging, in both decision lanes, and a
forged or non-intent return halts the run ``REJECTED`` before any fill.
"""

# ruff: noqa: E402

import dataclasses
import sys
import typing
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
import test_evaluator_engine as eng
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    JAN7,
    SEC,
    SEC_OTHER,
    ReconstructedTargetStrategy,
    bundle_of,
    reconstructed_engine,
    run_engine,
    three_regular_sessions,
)
from pydantic import ValidationError, model_validator
from test_evaluator_reconstruction import make_policy

from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    evaluation_input_bundle_hash,
)
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_reconstruction import ExploratoryReconstructionPolicyV1
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV1,
)
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.evaluator_trace import (
    ExploratoryStrategyDecisionTraceEventV1,
    StrategyDecisionTraceEventV1,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    derived_view_output_hash,
)
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.evaluator.reconstruction import ExploratoryReconstructionReplay

RAW_VENDOR_BAR = {"t": "2026-01-06T05:00:00Z", "o": 100.0, "c": 100.0, "S": "AAPL"}


def _engine(**overrides: Any) -> SessionEvaluatorEngine:
    bundle = overrides.pop("bundle", None) or eng._bundle()
    arguments: dict[str, Any] = {
        "bundle": bundle,
        "admission": eng._admission(bundle),
        "protocol": eng._protocol(),
        "cost_model": eng._cost_model(),
        "evidence": SessionEvaluatorEvidence(listing_role_records=eng.ROLE_RECORDS),
        "book_currency_namespace": eng.BOOK_NAMESPACE,
        "book_currency_code": eng.BOOK_CODE,
    }
    return SessionEvaluatorEngine(**(arguments | overrides))


def _sealed_bundle(**changes: Any) -> EvaluationInputBundleV1:
    """A bundle with ``changes`` and an honestly recomputed bundle hash."""
    draft = EvaluationInputBundleV1.model_construct(**(dict(eng._bundle()) | changes))
    return EvaluationInputBundleV1.model_construct(
        **(dict(draft) | {"bundle_hash": evaluation_input_bundle_hash(draft)})
    )


def test_a_bundle_keeping_a_genuine_hash_over_other_prices_is_refused() -> None:
    """The reviewer's case: forged PnL under the genuine bundle's name."""
    genuine = eng._bundle()
    swapped = tuple(
        eng._accounting_view(eng.SEC_A, day, close_price="240.00")
        if day == eng.DAY_3
        else eng._accounting_view(eng.SEC_A, day)
        for day in eng.DAYS
    )
    impostor = EvaluationInputBundleV1.model_construct(
        **(dict(genuine) | {"authentic_accounting_views": swapped})
    )
    assert impostor.bundle_hash == genuine.bundle_hash

    with pytest.raises(ValidationError, match=r"bundle hash mismatch"):
        _engine(bundle=impostor, admission=eng._admission(genuine))


def test_a_raw_vendor_payload_in_a_typed_field_never_reaches_a_strategy() -> None:
    """Task 7 provider boundary: a raw Alpaca bar dict is refused at build."""

    def poison(view: DerivedObservationViewV1) -> DerivedObservationViewV1:
        draft = DerivedObservationViewV1.model_construct(
            **(dict(view) | {"usability_hash": RAW_VENDOR_BAR})
        )
        return DerivedObservationViewV1.model_construct(
            **(dict(draft) | {"output_hash": derived_view_output_hash(draft)})
        )

    poisoned = _sealed_bundle(
        authentic_decision_views=tuple(
            poison(view) for view in eng._bundle().authentic_decision_views
        )
    )
    strategy = eng._buy_ten()

    with pytest.raises(ValidationError, match=r"usability_hash"):
        eng._run(_engine(bundle=poisoned), strategy)
    assert strategy.seen == []


def test_an_admission_edited_under_its_own_hash_is_refused() -> None:
    bundle = eng._bundle()
    admission = eng._admission(bundle)
    edited = type(admission).model_construct(
        **(dict(admission) | {"acknowledged_limitations": ("an edited limitation",)})
    )

    with pytest.raises(ValidationError, match=r"admission hash mismatch"):
        _engine(bundle=bundle, admission=edited)


def test_a_protocol_edited_under_its_own_hash_is_refused() -> None:
    protocol = eng._protocol()
    edited = type(protocol).model_construct(
        **(dict(protocol) | {"warmup_session_count": protocol.warmup_session_count + 1})
    )

    with pytest.raises(ValidationError, match=r"protocol hash mismatch"):
        _engine(protocol=edited)


def test_a_cost_model_edited_under_its_own_hash_is_refused() -> None:
    cost_model = eng._cost_model()
    edited = type(cost_model).model_construct(
        **(
            dict(cost_model)
            | {
                "adverse_slippage_basis_points": (
                    cost_model.adverse_slippage_basis_points + Decimal("1")
                )
            }
        )
    )

    with pytest.raises(ValidationError, match=r"cost model hash mismatch"):
        _engine(cost_model=edited)


def test_an_evidence_record_built_without_validation_is_refused() -> None:
    """Every evidence model is revalidated too, not only the hashed inputs."""
    record = eng.ROLE_RECORDS[0]
    broken = type(record).model_construct(**(dict(record) | {"schema_version": "9"}))

    with pytest.raises(ValidationError, match=r"schema_version"):
        _engine(
            evidence=SessionEvaluatorEvidence(
                listing_role_records=(broken, *eng.ROLE_RECORDS[1:])
            )
        )


def test_genuine_inputs_run_exactly_as_before() -> None:
    """Control: revalidation changes nothing for validated inputs."""
    first = eng._run(_engine())
    second = eng._run(eng._engine())

    assert first.result == second.result
    assert first.trace.trace_hash == second.trace.trace_hash


def _unvalidated_member(name: str) -> Any:
    """An empty, never-validated instance of the declared type of one member."""
    declared = typing.get_type_hints(SessionEvaluatorEvidence)[name]
    if name == "exploratory_reconstruction_replay":
        return ExploratoryReconstructionReplay(
            policy=ExploratoryReconstructionPolicyV1.model_construct(), requests=()
        )
    member = next(
        argument
        for argument in typing.get_args(declared) or (declared,)
        if argument not in (type(None), Ellipsis)
    )
    empty = member.model_construct()
    return empty if name == "exploratory_cohort" else (empty,)


@pytest.mark.parametrize(
    "name", [field.name for field in dataclasses.fields(SessionEvaluatorEvidence)]
)
def test_every_evidence_member_is_revalidated(name: str) -> None:
    """Every member, by the dataclass's own field list, so none can be missed."""
    with pytest.raises(ValidationError):
        _engine(evidence=SessionEvaluatorEvidence(**{name: _unvalidated_member(name)}))


def test_a_replay_query_is_revalidated() -> None:
    replay = ExploratoryReconstructionReplay(
        policy=make_policy(),
        requests=((ObservationOutcomeQueryV1.model_construct(), None),),  # type: ignore[arg-type]
    )

    with pytest.raises(ValidationError):
        _engine(
            evidence=SessionEvaluatorEvidence(exploratory_reconstruction_replay=replay)
        )


class _LenientBundle(EvaluationInputBundleV1):
    """A subclass excusing itself from the bundle-hash validator."""

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        return self


def test_a_subclass_cannot_excuse_itself_from_validation() -> None:
    """The reviewer's case: validation runs against the declared type."""
    genuine = eng._bundle()
    swapped = tuple(
        eng._accounting_view(eng.SEC_A, day, close_price="240.00")
        if day == eng.DAY_3
        else eng._accounting_view(eng.SEC_A, day)
        for day in eng.DAYS
    )
    lenient = _LenientBundle.model_construct(
        **(dict(genuine) | {"authentic_accounting_views": swapped})
    )

    with pytest.raises(ValidationError, match=r"bundle hash mismatch"):
        _engine(bundle=lenient, admission=eng._admission(genuine))


def test_a_run_identity_built_without_validation_is_refused_before_any_decision() -> (
    None
):
    engine = _engine()
    identity = eng._run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )
    forged = type(identity).model_construct(
        **(dict(identity) | {"run_identity_hash": "e" * 64})
    )
    strategy = eng._buy_ten()

    with pytest.raises(ValidationError, match=r"run identity hash mismatch"):
        engine.run(strategy=strategy, run_identity=forged)
    assert strategy.seen == []


# --- the strategy's returned intent (issue 111) ------------------------------

#: Every decision asks for one admitted buy and one zero on a security the lane
#: does not admit, so a forgery has two real targets to reorder or duplicate.
#: ``SEC`` is ``eng.SEC_A`` and ``SEC_OTHER`` is ``eng.SEC_B``.
REQUESTED = ((SEC, 1), (SEC_OTHER, 0))

INVALID = "strategy returned an invalid decision intent: "
NON_CANONICAL = (
    "strategy returned a non-canonical decision intent: "
    "revalidating it builds a different intent"
)

type _Forgery = Callable[[StrategyDecisionIntentV1], object]


def _unvalidated(
    intent: StrategyDecisionIntentV1, **changes: Any
) -> StrategyDecisionIntentV1:
    """``intent`` with ``changes``, built without validation."""
    return StrategyDecisionIntentV1.model_construct(**(dict(intent) | changes))


def _smuggled(
    intent: StrategyDecisionIntentV1, name: str, value: object
) -> StrategyDecisionIntentV1:
    """``intent`` carrying state its schema does not declare.

    Pydantic's ``model_construct`` silently drops an undeclared key under
    ``extra="forbid"``, so the #111 probe's ``extra_field`` never reached the
    instance. An extra field is carried only by a subclass that declares it,
    or by state set on the instance past its frozen guard, as here.
    """
    object.__setattr__(intent, name, value)
    return intent


def _forged_target_schema(intent: StrategyDecisionIntentV1) -> object:
    first, *rest = intent.targets
    forged = SecurityTargetPositionV1.model_construct(
        **(dict(first) | {"schema_version": "9"})
    )
    return _unvalidated(intent, targets=(forged, *rest))


class _WidenedIntent(StrategyDecisionIntentV1):
    """A subclass declaring a field the frozen intent schema does not have."""

    extra_field: str = "x"


#: Each forgery of the genuine intent, and the exact refusal it must meet.
#: Every one but the duplicate is staged or fails the run before issue 111;
#: the duplicate was already refused by staging, under a different cause.
FORGERIES: dict[str, tuple[_Forgery, str]] = {
    "forged-schema-version": (
        lambda intent: _unvalidated(intent, schema_version="9"),
        INVALID + "schema_version: Input should be '1'",
    ),
    "extra-field-declared-by-a-subclass": (
        lambda intent: _WidenedIntent(**dict(intent)),
        "strategy returned _WidenedIntent, not a StrategyDecisionIntentV1",
    ),
    "extra-field-in-the-extra-slot": (
        lambda intent: _smuggled(intent, "__pydantic_extra__", {"extra_field": "x"}),
        NON_CANONICAL,
    ),
    "extra-field-in-the-instance-dict": (
        lambda intent: _smuggled(intent, "extra_field", "x"),
        NON_CANONICAL,
    ),
    "targets-as-a-list": (
        lambda intent: _unvalidated(intent, targets=list(intent.targets)),
        INVALID + "targets: Input should be a valid tuple",
    ),
    "unsorted-targets": (
        lambda intent: _unvalidated(intent, targets=intent.targets[::-1]),
        NON_CANONICAL,
    ),
    "duplicate-targets": (
        lambda intent: _unvalidated(intent, targets=intent.targets[:1] * 2),
        INVALID + "targets: Value error, targets must be unique by security",
    ),
    "forged-target-schema-version": (
        _forged_target_schema,
        INVALID + "targets.0.schema_version: Input should be '1'",
    ),
    "naive-decision-time": (
        lambda intent: _unvalidated(
            intent, decision_time=intent.decision_time.replace(tzinfo=None)
        ),
        INVALID + "decision_time: Value error, timestamps must be timezone-aware",
    ),
    "none": (
        lambda intent: None,
        "strategy returned NoneType, not a StrategyDecisionIntentV1",
    ),
    "a-dict": (
        lambda intent: intent.model_dump(),
        "strategy returned dict, not a StrategyDecisionIntentV1",
    ),
    "an-arbitrary-object": (
        lambda intent: object(),
        "strategy returned object, not a StrategyDecisionIntentV1",
    ),
}


class _ForgingRealizedStrategy(eng.FixedTargetStrategy):
    def __init__(self, forge: _Forgery) -> None:
        super().__init__(dict.fromkeys(eng.DAYS, REQUESTED))
        self.forge = forge

    def decide(self, context: StrategyDecisionContextV1) -> Any:
        return self.forge(super().decide(context))


class _ForgingReconstructedStrategy(ReconstructedTargetStrategy):
    def __init__(self, forge: _Forgery) -> None:
        super().__init__(dict.fromkeys((JAN5, JAN6, JAN7), REQUESTED))
        self.forge = forge

    def decide_exploratory(self, context: ExploratoryStrategyDecisionContextV1) -> Any:
        return self.forge(super().decide_exploratory(context))


def _run_realized(forge: _Forgery) -> EvaluationRunArtifactsV1:
    return eng._run(eng._engine(), _ForgingRealizedStrategy(forge))


def _run_reconstructed(forge: _Forgery) -> EvaluationRunArtifactsV1:
    return run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())),
        _ForgingReconstructedStrategy(forge),
    )


@dataclasses.dataclass(frozen=True)
class _Lane:
    run: Callable[[_Forgery], EvaluationRunArtifactsV1]
    decision_event: (
        type[StrategyDecisionTraceEventV1]
        | type[ExploratoryStrategyDecisionTraceEventV1]
    )
    first_decision_index: int


LANES = {
    "realized": _Lane(_run_realized, StrategyDecisionTraceEventV1, 1),
    "reconstructed": _Lane(
        _run_reconstructed, ExploratoryStrategyDecisionTraceEventV1, 0
    ),
}


@pytest.mark.parametrize("forgery", FORGERIES)
@pytest.mark.parametrize("lane", LANES)
def test_a_forged_returned_intent_is_rejected_before_any_fill(
    lane: str, forgery: str
) -> None:
    forge, reason = FORGERIES[forgery]
    artifacts = LANES[lane].run(forge)

    result = artifacts.result
    assert result.classification is EvaluationClassification.REJECTED
    assert result.halt_reason == reason
    assert result.halted_session_index == LANES[lane].first_decision_index
    assert result.metrics.committed_fill_count == 0
    assert not [event for event in artifacts.trace.events if event.kind == "fill"]
    decisions = [
        (event.outcome, event.rejection_reason, event.staged_targets)
        for event in artifacts.trace.events
        if isinstance(event, LANES[lane].decision_event)
    ]
    assert decisions == [("rejected", reason, ())]


@pytest.mark.parametrize("lane", LANES)
def test_the_same_intent_unforged_stages_and_fills(lane: str) -> None:
    """Control: the forgery, not what the intent asks for, is refused."""
    artifacts = LANES[lane].run(lambda intent: intent)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.metrics.committed_fill_count == 1


@pytest.mark.parametrize("lane", LANES)
def test_a_strategy_raising_inside_its_decision_still_propagates(lane: str) -> None:
    """Issue 111 revalidates what a strategy returns, never what it raises.

    A ``ValidationError`` raised inside the decision method still propagates,
    so the M0 run records FAILED. Whether it should be REJECTED instead is
    decision D6 of the strategy-surface contract (#113), not decided here.
    """

    def construct_invalid(intent: StrategyDecisionIntentV1) -> object:
        return StrategyDecisionIntentV1(
            **(dict(intent) | {"targets": list(intent.targets)})
        )

    with pytest.raises(
        ValidationError,
        match=r"for StrategyDecisionIntentV1\ntargets\n  Input should be a valid tuple",
    ):
        LANES[lane].run(construct_invalid)


#: Trace and result hashes of genuine runs, pinned from a run at 19c15f8, the
#: commit before issue 111. Revalidating a genuine intent must not move a byte
#: of any trace or result, whether the intent stages or staging refuses it.
#: Re-pin only for a change that deliberately moves these runs. The realized
#: runs also bind the repository ``uv.lock`` through M1d normalization, so a
#: lock change moves them as well.
GENUINE_RUN_HASHES = {
    "realized-staged": (
        "80720399a140980ab0bc99b3d145a92b80e3aa7a907d097a8e6168178b46dd41",
        "f37b894459102c54ea8f5a36f457a338f8063ef77f5b9bc0084e3b1a270bd126",
    ),
    "realized-refused-by-staging": (
        "cb9a40abeb9d39c1275c10a9f217d40fb378a5b45e22460aa333a633bb1f407a",
        "abd2066a9a315e794ea806a1e691bcf75887499ca5b90190c1fba3bba34d3a0f",
    ),
    "reconstructed-staged": (
        "3efa93f66379367fb02ad96ad3958c04d8c4e1196af3e84d67ede6a091d94906",
        "b8b95f4bb2005ec16a77814ceaf80b9504f75b6cafff432985f26971b1ef550f",
    ),
    "reconstructed-refused-by-staging": (
        "a9c99b30489a2e0ace15690752167c8b896de6367386d32536d83dec6c81bc13",
        "a26ad49f4cd184c48439d6dc1898e935085283f567e09ee18fcb99551aa0828c",
    ),
}

GENUINE_RUNS: dict[str, Callable[[], EvaluationRunArtifactsV1]] = {
    "realized-staged": lambda: eng._run(eng._engine()),
    "realized-refused-by-staging": lambda: eng._run(
        eng._engine(), eng.FixedTargetStrategy({eng.DAY_1: ((eng.SEC_B, 1),)})
    ),
    "reconstructed-staged": lambda: run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())),
        ReconstructedTargetStrategy({JAN5: ((SEC, 1),), JAN6: ((SEC, 1),)}),
    ),
    "reconstructed-refused-by-staging": lambda: run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())),
        ReconstructedTargetStrategy({JAN5: ((SEC_OTHER, 1),)}),
    ),
}


@pytest.mark.parametrize("name", GENUINE_RUNS)
def test_a_genuine_intent_runs_byte_identically_to_before_issue_111(
    name: str,
) -> None:
    artifacts = GENUINE_RUNS[name]()

    assert (
        artifacts.trace.trace_hash,
        artifacts.result.result_hash,
    ) == GENUINE_RUN_HASHES[name]
