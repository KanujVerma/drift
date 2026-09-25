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
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Self
from uuid import UUID
from zoneinfo import ZoneInfo

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
    EvaluationRunArtifactsV2,
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
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.evaluator.reconstruction import ExploratoryReconstructionReplay
from drift.serialization.canonical import content_hash

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
WITH = "strategy returned a decision intent with "
NOT_UTC = WITH + "decision_time whose tzinfo is not datetime.UTC"

type _Forgery = Callable[[StrategyDecisionIntentV1], object]


def _unvalidated(
    intent: StrategyDecisionIntentV1, **changes: Any
) -> StrategyDecisionIntentV1:
    """``intent`` with ``changes``, built without validation."""
    return StrategyDecisionIntentV1.model_construct(**(dict(intent) | changes))


def _with_target(
    intent: StrategyDecisionIntentV1, **changes: Any
) -> StrategyDecisionIntentV1:
    """``intent`` whose first target has ``changes``, built without validation."""
    first, *rest = intent.targets
    forged = SecurityTargetPositionV1.model_construct(**(dict(first) | changes))
    return _unvalidated(intent, targets=(forged, *rest))


def _with_session_key(
    intent: StrategyDecisionIntentV1, **changes: Any
) -> StrategyDecisionIntentV1:
    """``intent`` whose session key has ``changes``, built without validation."""
    key = SessionKeyV1.model_construct(**(dict(intent.session_key) | changes))
    return _unvalidated(intent, session_key=key)


def _smuggled(model: Any, name: str, value: object) -> Any:
    """``model`` carrying state its schema does not declare.

    Pydantic's ``model_construct`` silently drops an undeclared key under
    ``extra="forbid"``, so the #111 probe's ``extra_field`` never reached the
    instance. An extra field is carried only by a subclass that declares it,
    or by state set on the instance past its frozen guard, as here.
    """
    object.__setattr__(model, name, value)
    return model


class _WidenedIntent(StrategyDecisionIntentV1):
    """A subclass declaring a field the frozen intent schema does not have."""

    extra_field: str = "x"


# Strict pydantic validation accepts an instance of a subclass and keeps it,
# so each leaf below would reach staging with its own comparisons (#119, F1).


class _RenamingUUID(UUID):
    """Compares and hashes as its value, but names another security."""

    def __str__(self) -> str:
        return str(SEC_OTHER)


class _ForgedInt(int):
    """An int subclass: the issue 88 whole-share rule is on exact ``int``."""


class _AlwaysEqualDateTime(datetime):
    """A decision time equal to every cutoff, whatever instant it holds."""

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = datetime.__hash__


class _AlwaysEqualDate(date):
    """A session date equal to every date, whatever day it holds."""

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = date.__hash__


class _AlwaysEqualStr(str):
    """A venue code equal to every string, whatever venue it names."""

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


class _StatefulTuple(tuple[SecurityTargetPositionV1, ...]):
    """A tuple subclass able to carry state of its own."""


class _AlwaysEqualSessionKey(SessionKeyV1):
    """A session key equal to every key, whatever session it names."""

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = SessionKeyV1.__hash__


class _AlwaysEqualWideTarget(SecurityTargetPositionV1):
    """A target subclass with an undeclared field, equal to every target."""

    note: str = "smuggled"

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = SecurityTargetPositionV1.__hash__


def _renaming_uuid(intent: StrategyDecisionIntentV1) -> object:
    identifier = intent.targets[0].security_id
    return _with_target(intent, security_id=_RenamingUUID(int=identifier.int))


def _uuid_holding_a_forged_int(intent: StrategyDecisionIntentV1) -> object:
    identifier = UUID(int=intent.targets[0].security_id.int)
    _smuggled(identifier, "int", _ForgedInt(identifier.int))
    return _with_target(intent, security_id=identifier)


def _date_thirty_days_earlier(intent: StrategyDecisionIntentV1) -> object:
    earlier = intent.session_key.local_date.toordinal() - 30
    return _with_session_key(intent, local_date=_AlwaysEqualDate.fromordinal(earlier))


def _stateful_targets(intent: StrategyDecisionIntentV1) -> object:
    targets = _StatefulTuple(intent.targets)
    _smuggled(targets, "smuggled", "x")
    return _unvalidated(intent, targets=targets)


def _session_key_of_another_day(intent: StrategyDecisionIntentV1) -> object:
    key = intent.session_key
    other = _AlwaysEqualSessionKey(
        mic=key.mic,
        session_scope=key.session_scope,
        local_date=date.fromordinal(key.local_date.toordinal() - 30),
    )
    return _unvalidated(intent, session_key=other)


def _wide_target(intent: StrategyDecisionIntentV1) -> object:
    first, *rest = intent.targets
    return _unvalidated(intent, targets=(_AlwaysEqualWideTarget(**dict(first)), *rest))


def _target_fields_set(intent: StrategyDecisionIntentV1) -> object:
    first, *rest = intent.targets
    emptied = _smuggled(first.model_copy(), "__pydantic_fields_set__", set())
    return _unvalidated(intent, targets=(emptied, *rest))


class _LyingDict(dict[str, object]):
    """Raw storage holds a forgery; Python-level views show the genuine state.

    Pydantic reads the raw storage of an instance dictionary (#119 round 2).
    """

    def __init__(self, raw: dict[str, object], shown: dict[str, object]) -> None:
        super().__init__(raw)
        self.shown = dict(shown)

    def items(self) -> Any:
        return self.shown.items()

    def keys(self) -> Any:
        return self.shown.keys()

    def values(self) -> Any:
        return self.shown.values()

    def __iter__(self) -> Any:
        return iter(self.shown)


def _lying_instance_dict(intent: StrategyDecisionIntentV1) -> object:
    shown = dict(vars(intent))
    raw = shown | {"targets": vars(_renaming_uuid(intent))["targets"]}
    return _smuggled(intent, "__dict__", _LyingDict(raw, shown))


def _lying_session_key_dict(intent: StrategyDecisionIntentV1) -> object:
    key = intent.session_key.model_copy()
    shown = dict(vars(key))
    earlier = _AlwaysEqualDate.fromordinal(key.local_date.toordinal() - 30)
    _smuggled(key, "__dict__", _LyingDict(shown | {"local_date": earlier}, shown))
    return _unvalidated(intent, session_key=key)


def _uuid_int(offset: int) -> _Forgery:
    """An exact UUID whose integer slot is moved by ``offset``, past its guard."""

    def forge(intent: StrategyDecisionIntentV1) -> object:
        identifier = UUID(int=intent.targets[0].security_id.int)
        _smuggled(identifier, "int", identifier.int + offset)
        return _with_target(intent, security_id=identifier)

    return forge


class _KeyStr(str):
    """A str subclass equal to, and hashing as, the name it spells."""


def _str_subclass_key(intent: StrategyDecisionIntentV1) -> object:
    state = vars(intent)
    state[_KeyStr("targets")] = state.pop("targets")
    return intent


class _FieldsSet(set[str]):
    """A set subclass able to carry state of its own."""


def _loud(*_: object) -> str:
    raise RuntimeError("strategy code ran while its answer was inspected")


class _LoudStr(str):
    """A str subclass that runs strategy code when formatted or printed."""

    __format__ = _loud
    __str__ = _loud


class _Loud:
    """An object that runs strategy code when formatted, printed or shown."""

    __format__ = _loud
    __str__ = _loud
    __repr__ = _loud


class _GuardedNames(type):
    """A metaclass that runs strategy code when a class name is read."""

    def __getattribute__(cls, name: str) -> Any:
        if name in ("__qualname__", "__module__"):
            _loud()
        return super().__getattribute__(name)


class _GuardedReturn(metaclass=_GuardedNames):
    """Neither name may be read through the class itself."""


class _LoudlyNamed:
    """A class whose qualified name is a str subclass."""


_LoudlyNamed.__qualname__ = _LoudStr("_LoudlyNamed")


class _OddlyHoused:
    """A class whose module is not a string at all."""


_OddlyHoused.__module__ = _Loud()  # type: ignore[assignment]


#: Each forgery of the genuine intent, and the exact refusal it must meet.
#: Before issue 111, every one but four is staged or fails the run. The
#: duplicate and the padded venue code were already refused by staging, and
#: the bool and int-subclass quantities by the issue 88 rule, each under a
#: different cause.
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
        WITH + "undeclared state in __pydantic_extra__",
    ),
    "extra-field-in-the-instance-dict": (
        lambda intent: _smuggled(intent, "extra_field", "x"),
        WITH + "undeclared state in __dict__",
    ),
    "private-state": (
        lambda intent: _smuggled(intent, "__pydantic_private__", {"note": "x"}),
        WITH + "undeclared state in __pydantic_private__",
    ),
    "tampered-fields-set": (
        lambda intent: _smuggled(intent, "__pydantic_fields_set__", {"garbage"}),
        WITH + "a tampered __pydantic_fields_set__",
    ),
    "fields-set-naming-an-undeclared-field": (
        lambda intent: _smuggled(
            intent,
            "__pydantic_fields_set__",
            {"garbage", *intent.model_fields_set},
        ),
        WITH + "a tampered __pydantic_fields_set__",
    ),
    "tampered-target-fields-set": (
        _target_fields_set,
        WITH + "a tampered targets.0.__pydantic_fields_set__",
    ),
    "fields-set-of-a-set-subclass": (
        lambda intent: _smuggled(
            intent, "__pydantic_fields_set__", _FieldsSet(intent.model_fields_set)
        ),
        WITH + "a tampered __pydantic_fields_set__",
    ),
    "fields-set-with-a-str-subclass-member": (
        lambda intent: _smuggled(
            intent,
            "__pydantic_fields_set__",
            {_KeyStr(name) for name in intent.model_fields_set},
        ),
        WITH + "a tampered __pydantic_fields_set__",
    ),
    "str-subclass-key-in-the-instance-dict": (
        _str_subclass_key,
        WITH + "undeclared state in __dict__",
    ),
    "lying-instance-dict": (
        _lying_instance_dict,
        WITH + "a __dict__ that is not exactly a dict",
    ),
    "lying-session-key-dict": (
        _lying_session_key_dict,
        WITH + "a session_key.__dict__ that is not exactly a dict",
    ),
    "targets-as-a-list": (
        lambda intent: _unvalidated(intent, targets=list(intent.targets)),
        WITH + "targets of type list, not tuple",
    ),
    "tuple-subclass-with-state": (
        _stateful_targets,
        WITH + "targets of type _StatefulTuple, not tuple",
    ),
    "unsorted-targets": (
        lambda intent: _unvalidated(intent, targets=intent.targets[::-1]),
        NON_CANONICAL,
    ),
    "padded-venue-code": (
        lambda intent: _with_session_key(intent, mic=f" {intent.session_key.mic}"),
        NON_CANONICAL,
    ),
    "duplicate-targets": (
        lambda intent: _unvalidated(intent, targets=intent.targets[:1] * 2),
        INVALID + "targets: Value error, targets must be unique by security",
    ),
    "forged-target-schema-version": (
        lambda intent: _with_target(intent, schema_version="9"),
        INVALID + "targets.0.schema_version: Input should be '1'",
    ),
    "target-subclass-with-an-extra-field": (
        _wide_target,
        WITH + "targets.0 of type _AlwaysEqualWideTarget, not SecurityTargetPositionV1",
    ),
    "uuid-subclass-naming-another-security": (
        _renaming_uuid,
        WITH + "targets.0.security_id of type _RenamingUUID, not UUID",
    ),
    "uuid-holding-an-int-subclass": (
        _uuid_holding_a_forged_int,
        WITH + "targets.0.security_id.int of type _ForgedInt, not int",
    ),
    "uuid-int-past-128-bits": (
        _uuid_int(1 << 128),
        WITH + "targets.0.security_id.int outside the 128-bit range",
    ),
    "uuid-int-below-zero": (
        _uuid_int(-(1 << 128)),
        WITH + "targets.0.security_id.int outside the 128-bit range",
    ),
    "lone-surrogate-venue-code": (
        lambda intent: _with_session_key(intent, mic="\ud800" * 4),
        INVALID
        + "session_key.mic: Input should be a valid string, "
        + "unable to parse raw data as a unicode string",
    ),
    "int-subclass-quantity": (
        lambda intent: _with_target(intent, target_quantity=_ForgedInt(1)),
        WITH + "targets.0.target_quantity of type _ForgedInt, not int",
    ),
    "bool-quantity": (
        lambda intent: _with_target(intent, target_quantity=True),
        WITH + "targets.0.target_quantity of type bool, not int",
    ),
    "session-key-subclass-of-another-day": (
        _session_key_of_another_day,
        WITH + "session_key of type _AlwaysEqualSessionKey, not SessionKeyV1",
    ),
    "date-subclass-thirty-days-earlier": (
        _date_thirty_days_earlier,
        WITH + "session_key.local_date of type _AlwaysEqualDate, not date",
    ),
    "str-subclass-venue-code": (
        lambda intent: _with_session_key(intent, mic=_AlwaysEqualStr("XNAS")),
        WITH + "session_key.mic of type _AlwaysEqualStr, not str",
    ),
    "datetime-subclass-in-2020": (
        lambda intent: _unvalidated(
            intent, decision_time=_AlwaysEqualDateTime(2020, 1, 1, tzinfo=UTC)
        ),
        WITH + "decision_time of type _AlwaysEqualDateTime, not datetime",
    ),
    "non-utc-zone-at-the-same-instant": (
        lambda intent: _unvalidated(
            intent,
            decision_time=intent.decision_time.astimezone(
                timezone(timedelta(hours=-5))
            ),
        ),
        NOT_UTC,
    ),
    "zoneinfo-utc-at-the-same-instant": (
        lambda intent: _unvalidated(
            intent, decision_time=intent.decision_time.replace(tzinfo=ZoneInfo("UTC"))
        ),
        NOT_UTC,
    ),
    "naive-decision-time": (
        lambda intent: _unvalidated(
            intent, decision_time=intent.decision_time.replace(tzinfo=None)
        ),
        NOT_UTC,
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
    "an-object-whose-metaclass-guards-its-names": (
        lambda intent: _GuardedReturn(),
        "strategy returned _GuardedReturn, not a StrategyDecisionIntentV1",
    ),
    "an-object-whose-type-name-is-a-str-subclass": (
        lambda intent: _LoudlyNamed(),
        "strategy returned <unnamed>, not a StrategyDecisionIntentV1",
    ),
    "an-object-whose-type-module-is-not-a-str": (
        lambda intent: _OddlyHoused(),
        "strategy returned _OddlyHoused, not a StrategyDecisionIntentV1",
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


def _run_realized(forge: _Forgery) -> EvaluationRunArtifactsV2:
    return eng._run(eng._engine(), _ForgingRealizedStrategy(forge))


def _run_reconstructed(forge: _Forgery) -> EvaluationRunArtifactsV2:
    return run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())),
        _ForgingReconstructedStrategy(forge),
    )


@dataclasses.dataclass(frozen=True)
class _Lane:
    run: Callable[[_Forgery], EvaluationRunArtifactsV2]
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
    so the M0 run records FAILED, as D6 (a) of the strategy-surface contract
    (#113) rules for a strategy that raises.
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


def _uncanonical(qualified_type: str) -> str:
    return content_hash({"uncanonical_return_type": qualified_type})


_INTENT_TYPE = "drift.domain.evaluator_strategy.StrategyDecisionIntentV1"

#: The intent hash each refused return is traced under: the content hash of
#: what the strategy returned, or, for a return with no canonical form, the
#: hash of this exact payload naming its type. An intent the exact-type walk
#: refuses is never content hashed, since hashing it would run its leaves'
#: own code, and a type name that is not exactly a str is never formatted.
REFUSED_INTENT_HASHES = {
    "none": content_hash(None),
    "an-arbitrary-object": _uncanonical("builtins.object"),
    "naive-decision-time": _uncanonical(_INTENT_TYPE),
    "uuid-subclass-naming-another-security": _uncanonical(_INTENT_TYPE),
    "lying-instance-dict": _uncanonical(_INTENT_TYPE),
    "uuid-int-past-128-bits": _uncanonical(_INTENT_TYPE),
    "lone-surrogate-venue-code": _uncanonical(_INTENT_TYPE),
    "an-object-whose-metaclass-guards-its-names": _uncanonical(
        f"{__name__}._GuardedReturn"
    ),
    "an-object-whose-type-name-is-a-str-subclass": _uncanonical(
        f"{__name__}.<unnamed>"
    ),
    "an-object-whose-type-module-is-not-a-str": _uncanonical("<unnamed>._OddlyHoused"),
}


@pytest.mark.parametrize("forgery", REFUSED_INTENT_HASHES)
@pytest.mark.parametrize("lane", LANES)
def test_a_refused_return_is_traced_under_the_hash_of_what_it_is(
    lane: str, forgery: str
) -> None:
    artifacts = LANES[lane].run(FORGERIES[forgery][0])

    hashes = [
        event.intent_hash
        for event in artifacts.trace.events
        if isinstance(event, LANES[lane].decision_event)
    ]
    assert hashes == [REFUSED_INTENT_HASHES[forgery]]


def _rewriting_earlier_answers() -> _Forgery:
    """Answer genuinely, then rewrite the previous answer past its guard."""
    answered: list[StrategyDecisionIntentV1] = []

    def forge(intent: StrategyDecisionIntentV1) -> object:
        while answered:
            earlier = answered.pop()
            _smuggled(earlier.targets[0], "target_quantity", 0)
            _smuggled(earlier, "targets", ())
        answered.append(intent)
        return intent

    return forge


@pytest.mark.parametrize("lane", LANES)
def test_a_strategy_cannot_rewrite_an_intent_after_it_is_staged(lane: str) -> None:
    """Staging keeps the rebuilt intent, never an object the strategy still holds.

    Each later decision rewrites the models it returned earlier. Had the engine
    staged those objects, the recorded decisions would change after the fact.
    """
    control = LANES[lane].run(lambda intent: intent)
    rewritten = LANES[lane].run(_rewriting_earlier_answers())

    assert rewritten.trace.trace_hash == control.trace.trace_hash
    assert rewritten.result.result_hash == control.result.result_hash


#: The last decision date of each lane, whose intent is staged but never run.
FINAL_DECISION_DATES = {"realized": eng.DAYS[-1], "reconstructed": JAN7}


def _rewriting_kept_identifiers(rewrite_on: date | None) -> _Forgery:
    """Answer on UUIDs the strategy keeps, then rewrite them past their guard.

    With ``rewrite_on`` unset, each decision rewrites the identifiers it
    returned at the previous one. Otherwise every kept identifier is rewritten
    at once, at the decision on that date. Only the strategy's own UUIDs are
    rewritten, never a shared constant.
    """
    kept: list[UUID] = []

    def forge(intent: StrategyDecisionIntentV1) -> object:
        if rewrite_on is None or intent.session_key.local_date == rewrite_on:
            for identifier in kept:
                _smuggled(identifier, "int", SEC_OTHER.int)
            kept.clear()
        first, *rest = intent.targets
        mine = UUID(int=first.security_id.int)
        kept.append(mine)
        target = SecurityTargetPositionV1(
            security_id=mine, target_quantity=first.target_quantity
        )
        return StrategyDecisionIntentV1(
            session_key=intent.session_key,
            decision_time=intent.decision_time,
            targets=(target, *rest),
        )

    return forge


@pytest.mark.parametrize("final", [False, True], ids=["next-decision", "final"])
@pytest.mark.parametrize("lane", LANES)
def test_a_strategy_cannot_rewrite_a_uuid_it_kept_after_the_intent_is_staged(
    lane: str, final: bool
) -> None:
    """Staging holds only fresh objects the strategy never saw (#119 round 2).

    A python-mode rebuild keeps the strategy's own ``uuid.UUID`` instances, so
    one the strategy kept could rewrite what was staged, traced and filled.
    """
    control = LANES[lane].run(lambda intent: intent)
    rewrite_on = FINAL_DECISION_DATES[lane] if final else None
    rewritten = LANES[lane].run(_rewriting_kept_identifiers(rewrite_on))

    assert rewritten.result.classification is EvaluationClassification.COMPLETE
    assert rewritten.trace.trace_hash == control.trace.trace_hash
    assert rewritten.result.result_hash == control.result.result_hash
    assert content_hash(rewritten.final_state) == content_hash(control.final_state)


#: Trace and result hashes of genuine runs, pinned from a run at 19c15f8, the
#: commit before issue 111. Revalidating a genuine intent must not move a byte
#: of any trace or result, whether the intent stages or staging refuses it.
#: Re-pin only for a change that deliberately moves these runs. The realized
#: runs also bind the repository ``uv.lock`` through M1d normalization, so a
#: lock change moves them as well. The result hashes were re-pinned once for
#: issue 92, whose hash-covered bundle field moves every bundle hash and,
#: through the run identity, every result hash. They were re-pinned again,
#: trace and result, for issue 107, which edits a declared module of the
#: m1d-evidence-v1 closure and so moves the M1d evidence identity and every
#: identity-bearing hash of these runs by design (no economic field changes).
#: They were re-pinned again, trace and result, for issue 63 stage 2, which
#: moves the M1c identities onto the M1c semantic attestations: its edits to
#: semantic_attestation.py and the three M1c stamp-site modules, all declared by
#: m1d-evidence-v1, move the M1d evidence identity and the M1c validator
#: identity bound into every M1d context hash. A field-by-field diff of all four
#: runs against main e9e2724 shows only identity-bearing hashes moved; no
#: quantity, price, cash, NAV, classification, count, status, reason, lane or
#: kind leaf changes.
GENUINE_RUN_HASHES = {
    "realized-staged": (
        "5fd254552ea73effee84de6f84d9e5d132c1990d485e53dfccd7860308ea3e9b",
        "395b1912df800fe5f918db02473d05def981385bc59a83f90f76b5686be67ff3",
    ),
    "realized-refused-by-staging": (
        "c7e477f416f17275b398f53a345bbd5b2838716c3e6d0b0ace1c87d22135937b",
        "5828f1d206402d97ce89fed913cb79b936c12b0ebb597a6eae6d869d7d1a0875",
    ),
    "reconstructed-staged": (
        "3cbdba4b5ad822ac2fb37e1d976aa1ef8620f27c1fdc196ed41ea87793304a1f",
        "aebf8c5ba30ae47a449ed5e6e7563fa9407ae53d821bcd24aded92f8cc21dde7",
    ),
    "reconstructed-refused-by-staging": (
        "1f5459b52962c8dc08742c3e3ecf295799561655ac9f2a50125c3593586e8d96",
        "660c7dbc8a3558627eff5e2ef0a3d3de6cdeafdfa97b04e0b6d4e32ec31b030c",
    ),
}

GENUINE_RUNS: dict[str, Callable[[], EvaluationRunArtifactsV2]] = {
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
