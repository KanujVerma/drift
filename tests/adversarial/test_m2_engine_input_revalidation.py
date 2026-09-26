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
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
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
    cohort_of,
    exploratory_admission,
    reconstructed_engine,
    replay_of,
    run_engine,
    scheduled_bundle,
    scheduled_session_case,
    source_request,
    three_regular_sessions,
)
from observation_test_support import NormalizationHarness, ObservationHarness
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
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
from drift.evaluator.engine import (
    NonCanonicalEngineInputError,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    _canonical_m1d_context,
)
from drift.evaluator.reconstruction import (
    ExploratoryReconstructionReplay,
    build_exploratory_reconstructed_session_observation,
)
from drift.markets.observation_validation import (
    m1d_context_hash,
    validate_m1d_resolution_context,
)
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


def _uuid_int_of(value: int) -> _Forgery:
    """An exact UUID whose integer slot is set to ``value``, past its guard."""

    def forge(intent: StrategyDecisionIntentV1) -> object:
        identifier = UUID(int=intent.targets[0].security_id.int)
        _smuggled(identifier, "int", value)
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
    # The bound itself is outside the range (#119 round 3, mutant X04).
    "uuid-int-of-exactly-2-to-the-128": (
        _uuid_int_of(1 << 128),
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


#: A genuine UUIDv7 whose top bit is set, as every identifier minted after
#: its 48-bit millisecond clock passes 2**47 will be (#119 round 3, mutant X03).
TOP_BIT_UUID7 = UUID("ffffffff-ffff-7fff-bfff-ffffffffffff")


def _liquidating_a_top_bit_security(intent: StrategyDecisionIntentV1) -> object:
    zero = SecurityTargetPositionV1(security_id=TOP_BIT_UUID7, target_quantity=0)
    return StrategyDecisionIntentV1(
        session_key=intent.session_key,
        decision_time=intent.decision_time,
        targets=(*intent.targets, zero),
    )


@pytest.mark.parametrize("lane", LANES)
def test_a_genuine_uuid7_with_its_top_bit_set_is_staged(lane: str) -> None:
    """The 128-bit range admits every genuine identifier, the top bit included."""
    assert TOP_BIT_UUID7.version == 7
    assert TOP_BIT_UUID7.int >= 1 << 127

    artifacts = LANES[lane].run(_liquidating_a_top_bit_security)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.metrics.committed_fill_count == 1
    staged = [
        {target.security_id for target in event.staged_targets}
        for event in artifacts.trace.events
        if isinstance(event, LANES[lane].decision_event)
    ]
    assert staged
    assert all(TOP_BIT_UUID7 in targets for targets in staged)


@pytest.mark.parametrize("lane", LANES)
def test_a_non_intent_return_whose_hashing_raises_fails_the_run(lane: str) -> None:
    """#113 D6 (a): the run fails, never halts REJECTED (#119 round 3, X06).

    A refused return that is not an intent is content hashed for its decision
    event, which can run its own code (here its ``repr``). If that code
    raises, the exception propagates, as one raised inside the decision
    method does, so the M0 run records FAILED.
    """
    with pytest.raises(
        RuntimeError, match=r"^strategy code ran while its answer was inspected$"
    ):
        LANES[lane].run(lambda intent: _Loud())


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


# --- subclassed leaves in engine inputs (issue 123) ---------------------------
#
# Strict validation keeps an instance of a `UUID`, `datetime` or `date`
# subclass, and a python-mode dump hands back the same leaf, so the issue 78
# rebuild shared every such leaf with the forged input. Each forgery below
# keeps the genuine string form, so every content hash over it, the bundle,
# cohort and evidence hashes included, is the genuine one: only equality and
# hashing are forged. The engine must run each input exactly as its canonical
# value, byte for byte, and keep none of the forged leaves.


class _ForgedUUID(UUID):
    """An identifier equal to every identifier, hashing as ``hashes_as``."""

    hashes_as: UUID

    def __hash__(self) -> int:
        return hash(self.hashes_as)

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


def _forged_uuid(value: UUID, *, hashes_as: UUID) -> UUID:
    forged = _ForgedUUID(int=value.int)
    object.__setattr__(forged, "hashes_as", hashes_as)
    return forged


class _DayBeforeHashingDate(date):
    """A session date equal to every date, hashing as the day before it."""

    def __hash__(self) -> int:
        return hash(date.fromordinal(self.toordinal() - 1))

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


def _replaced(model: Any, **changes: Any) -> Any:
    """``model`` with ``changes``, built without validation."""
    return type(model).model_construct(**(dict(model) | changes))


def _hash_invisible(bundle: EvaluationInputBundleV1) -> EvaluationInputBundleV1:
    """The forged bundle, whose content hash is still its genuine bundle hash."""
    assert evaluation_input_bundle_hash(bundle) == bundle.bundle_hash
    return bundle


def _bundle_admitting_every_security() -> EvaluationInputBundleV1:
    """Its one eligible security equals every identifier, hashing as SEC_OTHER."""
    genuine = eng._bundle()
    (eligible,) = genuine.structural_eligibilities
    forged = _replaced(
        eligible,
        security_id=_forged_uuid(eligible.security_id, hashes_as=SEC_OTHER),
    )
    return _hash_invisible(_replaced(genuine, structural_eligibilities=(forged,)))


def _bundle_with_a_decision_time_equal_to_every_cutoff() -> EvaluationInputBundleV1:
    """The last decision view is timed at an instant equal to every instant."""
    genuine = eng._bundle()
    last = eng._close_of(eng.DAY_3)

    def forge(view: DerivedObservationViewV1) -> DerivedObservationViewV1:
        observation: Any = view.query.observation
        if observation.decision_time != last:
            return view
        moment = observation.decision_time
        timed = _replaced(
            observation,
            decision_time=_AlwaysEqualDateTime(
                moment.year,
                moment.month,
                moment.day,
                moment.hour,
                moment.minute,
                moment.second,
                moment.microsecond,
                tzinfo=moment.tzinfo,
            ),
        )
        forged: DerivedObservationViewV1 = _replaced(
            view, query=_replaced(view.query, observation=timed)
        )
        return forged

    views = tuple(forge(view) for view in genuine.authentic_decision_views)
    return _hash_invisible(_replaced(genuine, authentic_decision_views=views))


def _bundle_with_a_session_date_hashing_as_the_day_before() -> EvaluationInputBundleV1:
    """The last accounting view's session date hashes as the day before it."""
    genuine = eng._bundle()

    def forge(view: DerivedObservationViewV1) -> DerivedObservationViewV1:
        session = view.source_session
        if session.local_date != eng.DAY_3:
            return view
        day = session.local_date
        dated = _replaced(
            session, local_date=_DayBeforeHashingDate(day.year, day.month, day.day)
        )
        forged: DerivedObservationViewV1 = _replaced(view, source_session=dated)
        return forged

    views = tuple(forge(view) for view in genuine.authentic_accounting_views)
    return _hash_invisible(_replaced(genuine, authentic_accounting_views=views))


def _role_records_naming_every_security() -> tuple[Any, ...]:
    """SEC_OTHER's primary listing record names a security equal to every one."""
    kept, other = eng.ROLE_RECORDS
    forged = _replaced(
        other,
        security_id=_forged_uuid(other.security_id, hashes_as=other.security_id),
    )
    assert content_hash(forged) == content_hash(other)
    return (kept, forged)


def _cohort_admitting_every_security() -> Any:
    """The cohort's one member equals every identifier, hashing as SEC_OTHER."""
    genuine = cohort_of()
    (member,) = genuine.security_ids
    forged = _replaced(
        genuine, security_ids=(_forged_uuid(member, hashes_as=SEC_OTHER),)
    )
    assert content_hash(forged) == content_hash(genuine)
    return forged


def _replay_querying_every_security() -> ExploratoryReconstructionReplay:
    """The first replay query names a security equal to every one."""
    bundle = bundle_of(three_regular_sessions())
    genuine = replay_of(bundle.exploratory_reconstructed_observations)
    (query, context), *rest = genuine.requests
    forged = _replaced(
        query, security_id=_forged_uuid(query.security_id, hashes_as=query.security_id)
    )
    assert content_hash(forged) == content_hash(query)
    return ExploratoryReconstructionReplay(
        policy=genuine.policy, requests=((forged, context), *rest)
    )


def _with_daily_records(context: Any, forge: Callable[[Any], Any]) -> Any:
    """``context`` whose daily source observations are each passed to ``forge``."""
    return dataclasses.replace(
        context,
        observation_datasets=tuple(
            dataclasses.replace(
                dataset,
                records=tuple(
                    forge(record)
                    if type(record).__name__ == "DailySourceObservationVersionV1"
                    else record
                    for record in dataset.records
                ),
            )
            for dataset in context.observation_datasets
        ),
    )


def _replay_context_naming_every_security() -> ExploratoryReconstructionReplay:
    """The first request's M1d context holds a record naming every security."""
    bundle = bundle_of(three_regular_sessions())
    genuine = replay_of(bundle.exploratory_reconstructed_observations)
    (query, context), *rest = genuine.requests

    def forge(record: Any) -> Any:
        forged = _replaced(
            record,
            security_id=_forged_uuid(record.security_id, hashes_as=record.security_id),
        )
        assert content_hash(forged) == content_hash(record)
        return forged

    return ExploratoryReconstructionReplay(
        policy=genuine.policy,
        requests=((query, _with_daily_records(context, forge)), *rest),
    )


def _replay_context_of_artifact_hashes_equal_to_every_text() -> (
    ExploratoryReconstructionReplay
):
    """The first request's M1d context states each artifact hash as forged text.

    An artifact hash is a scalar field of a dataclass, not a model field.
    """
    bundle = bundle_of(three_regular_sessions())
    genuine = replay_of(bundle.exploratory_reconstructed_observations)
    (query, context), *rest = genuine.requests
    first, *others = context.observation_datasets
    artifacts = {
        name: dataclasses.replace(
            artifact, content_hash=_AlwaysEqualStr(artifact.content_hash)
        )
        for name, artifact in first.artifacts.items()
    }
    assert artifacts
    forged = dataclasses.replace(
        context,
        observation_datasets=(dataclasses.replace(first, artifacts=artifacts), *others),
    )
    return ExploratoryReconstructionReplay(
        policy=genuine.policy, requests=((query, forged), *rest)
    )


def _texts_equal_to_every_text(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_AlwaysEqualStr(value) for value in values)


def _admission_of_forged_text() -> Any:
    admission = eng._admission(eng._bundle())
    return _replaced(
        admission,
        acknowledged_limitations=_texts_equal_to_every_text(
            admission.acknowledged_limitations
        ),
    )


def _protocol_of_forged_text() -> Any:
    protocol = eng._protocol()
    return _replaced(protocol, protocol_id=_AlwaysEqualStr(protocol.protocol_id))


def _cost_model_of_forged_text() -> Any:
    cost_model = eng._cost_model()
    return _replaced(cost_model, model_id=_AlwaysEqualStr(cost_model.model_id))


type _InputForgery = tuple[
    Callable[[], SessionEvaluatorEngine],
    Callable[[], eng.FixedTargetStrategy | ReconstructedTargetStrategy],
    str,
]

#: Each forged input, as the engine it builds and the strategy it runs, and the
#: genuine run it must reproduce byte for byte. Before issue 123 the UUID,
#: datetime and date forgeries in the bundle, the role records and the cohort
#: each ran otherwise: an unadmitted security was staged and halted the run
#: INDETERMINATE; a later decision view was read at an earlier cutoff, whose
#: context then refused it, failing the run; one session was priced from two
#: views; one security resolved two primary listings; or the admitted
#: security fell out of the cohort, failing the run. The replay query and
#: replay context forgeries already ran as genuine, but kept their forged
#: leaves in engine state; the context one until the #123 review, since the
#: M1d resolution context was kept as given. The text forgeries are controls:
#: a python-mode rebuild already normalized a ``str`` subclass to an exact
#: ``str``, and still must.
INPUT_FORGERIES: dict[str, _InputForgery] = {
    "bundle-uuid-equal-to-every-security": (
        lambda: _engine(bundle=_bundle_admitting_every_security()),
        lambda: eng.FixedTargetStrategy({eng.DAY_1: ((eng.SEC_B, 1),)}),
        "realized-refused-by-staging",
    ),
    "bundle-datetime-equal-to-every-cutoff": (
        lambda: _engine(bundle=_bundle_with_a_decision_time_equal_to_every_cutoff()),
        eng._buy_ten,
        "realized-staged",
    ),
    "bundle-date-hashing-as-the-day-before": (
        lambda: _engine(bundle=_bundle_with_a_session_date_hashing_as_the_day_before()),
        eng._buy_ten,
        "realized-staged",
    ),
    "evidence-role-record-uuid-equal-to-every-security": (
        lambda: _engine(
            evidence=SessionEvaluatorEvidence(
                listing_role_records=_role_records_naming_every_security()
            )
        ),
        eng._buy_ten,
        "realized-staged",
    ),
    "evidence-cohort-uuid-equal-to-every-security": (
        lambda: reconstructed_engine(
            bundle_of(three_regular_sessions()),
            cohort=_cohort_admitting_every_security(),
        ),
        lambda: ReconstructedTargetStrategy({JAN5: ((SEC_OTHER, 1),)}),
        "reconstructed-refused-by-staging",
    ),
    "evidence-replay-query-uuid-equal-to-every-security": (
        lambda: reconstructed_engine(
            bundle_of(three_regular_sessions()),
            replay=_replay_querying_every_security(),
        ),
        lambda: ReconstructedTargetStrategy({JAN5: ((SEC, 1),), JAN6: ((SEC, 1),)}),
        "reconstructed-staged",
    ),
    "evidence-replay-context-uuid-equal-to-every-security": (
        lambda: reconstructed_engine(
            bundle_of(three_regular_sessions()),
            replay=_replay_context_naming_every_security(),
        ),
        lambda: ReconstructedTargetStrategy({JAN5: ((SEC, 1),), JAN6: ((SEC, 1),)}),
        "reconstructed-staged",
    ),
    "evidence-replay-context-artifact-hash-equal-to-every-text": (
        lambda: reconstructed_engine(
            bundle_of(three_regular_sessions()),
            replay=_replay_context_of_artifact_hashes_equal_to_every_text(),
        ),
        lambda: ReconstructedTargetStrategy({JAN5: ((SEC, 1),), JAN6: ((SEC, 1),)}),
        "reconstructed-staged",
    ),
    "admission-text-equal-to-every-text": (
        lambda: _engine(admission=_admission_of_forged_text()),
        eng._buy_ten,
        "realized-staged",
    ),
    "protocol-text-equal-to-every-text": (
        lambda: _engine(protocol=_protocol_of_forged_text()),
        eng._buy_ten,
        "realized-staged",
    ),
    "cost-model-text-equal-to-every-text": (
        lambda: _engine(cost_model=_cost_model_of_forged_text()),
        eng._buy_ten,
        "realized-staged",
    ),
}

#: Every forged leaf type these tests build.
_FORGED_LEAF_TYPES = (
    _ForgedUUID,
    _DayBeforeHashingDate,
    _AlwaysEqualDateTime,
    _AlwaysEqualDate,
    _AlwaysEqualStr,
)


def _reachable(*roots: object) -> list[object]:
    """Every object reachable from ``roots``, each once.

    Walks model and dataclass fields, container members, and the instance
    state of ``drift`` objects such as the engine itself.
    """
    seen: dict[int, object] = {}
    pending = list(roots)
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen[id(item)] = item
        if isinstance(item, BaseModel):
            pending.extend(vars(item).values())
        elif dataclasses.is_dataclass(item) and not isinstance(item, type):
            pending.extend(
                getattr(item, name.name) for name in dataclasses.fields(item)
            )
        elif isinstance(item, Mapping):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, tuple | list | set | frozenset):
            pending.extend(item)
        elif type(item).__module__.startswith("drift.") and hasattr(item, "__dict__"):
            pending.extend(vars(item).values())
    return list(seen.values())


def _forged_leaves(*roots: object) -> list[str]:
    return [
        type(item).__name__
        for item in _reachable(*roots)
        if isinstance(item, _FORGED_LEAF_TYPES)
    ]


@pytest.mark.parametrize("forgery", INPUT_FORGERIES)
def test_an_input_leaf_with_forged_equality_runs_as_its_canonical_value(
    forgery: str,
) -> None:
    """Every comparison and every hash reads the canonical value (issue 123)."""
    build, strategy, genuine = INPUT_FORGERIES[forgery]
    artifacts = run_engine(build(), strategy())

    assert (
        artifacts.trace.trace_hash,
        artifacts.result.result_hash,
    ) == GENUINE_RUN_HASHES[genuine]


@pytest.mark.parametrize("forgery", INPUT_FORGERIES)
def test_no_forged_input_leaf_survives_into_engine_state(forgery: str) -> None:
    """Each input is rebuilt through canonical JSON into exact built-in leaves."""
    build, strategy, _ = INPUT_FORGERIES[forgery]
    engine = build()
    artifacts = run_engine(engine, strategy())

    assert _forged_leaves(engine, artifacts) == []


def test_a_run_identity_of_forged_text_runs_as_its_canonical_value() -> None:
    """Control: every run-identity leaf is a string, normalized as before."""
    engine = _engine()
    identity = eng._run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )
    forged = _replaced(
        identity, code_version_hash=_AlwaysEqualStr(identity.code_version_hash)
    )

    artifacts = engine.run(strategy=eng._buy_ten(), run_identity=forged)

    assert (
        artifacts.trace.trace_hash,
        artifacts.result.result_hash,
    ) == GENUINE_RUN_HASHES["realized-staged"]
    assert _forged_leaves(engine, artifacts) == []


class _SpelledDecimal(Decimal):
    """A price holding its own digits, spelling ``spelled``, equal to every value."""

    spelled: str

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = Decimal.__hash__

    def __str__(self) -> str:
        return self.spelled

    def __repr__(self) -> str:
        return f"Decimal('{self.spelled}')"


def _spelled_decimal(digits: str, spelled: str) -> Decimal:
    value = _SpelledDecimal(digits)
    value.spelled = spelled
    return value


def _with_open_of(context: Any, digits: str, spelled: str) -> Any:
    """``context`` whose daily open holds ``digits`` while spelling ``spelled``."""

    def forge(record: Any) -> Any:
        fields = tuple(
            _replaced(item, value=_spelled_decimal(digits, spelled))
            if item.field_name == "open"
            else item
            for item in record.fields
        )
        return _replaced(record, fields=fields)

    return _with_daily_records(context, forge)


def test_an_m1d_context_record_cannot_launder_a_price_it_never_stated() -> None:
    """#123 review F1: the replay's M1d context is rebuilt canonically too.

    The JAN6 source record holds an open of 500.000 that spells 100.000, the
    form its bytes and payload hash state, and equals every value. M1d replay
    compared it with the record its bytes parse to and accepted it, the
    canonical builder re-derived 500.000 from it, and the bundle's
    self-consistent 500 reconstruction then passed verification: the engine
    filled a buy at 500 and ended COMPLETE. Rebuilt canonically, the record
    holds its real digits, which its payload hash does not state.
    """
    cases = [scheduled_session_case(day) for day in (JAN5, JAN6, JAN7)]
    requests = [source_request(observation) for observation, _ in cases]
    query, context = requests[1]
    forged = _with_open_of(context, "500.000", "100.000")
    derived = build_exploratory_reconstructed_session_observation(
        query, forged, cohort_of(), make_policy()
    )
    prices = {item.field_name: item.source_value for item in derived.fields}
    genuine = {item.field_name: item.source_value for item in cases[1][0].fields}
    assert (prices["open"], genuine["open"]) == (Decimal("500"), Decimal("100"))

    bundle = scheduled_bundle(
        (cases[0][0], derived, cases[2][0]), tuple(session for _, session in cases)
    )
    replay = ExploratoryReconstructionReplay(
        policy=make_policy(), requests=(requests[0], (query, forged), requests[2])
    )

    with pytest.raises(ValidationError, match=r"observation payload hash mismatch"):
        reconstructed_engine(bundle, replay=replay)


# --- the rebuild of an M1d context, member by member (#131 round 2) -----------
#
# Each forgery below is refused by name, or rebuilt to its exact canonical
# value, rather than silently repaired into a valid context.


def _structural_context() -> Any:
    """A genuine M1d context carrying an M1b structural context."""
    harness = ObservationHarness()
    harness.attach_m1b()
    return harness.context


def _economic_context() -> Any:
    """A genuine M1d context carrying M1b structural and M1c economic contexts."""
    return NormalizationHarness().context


def _members(value: object, path: str = "context") -> list[tuple[str, type, str]]:
    """Every model and leaf of an M1d context, by path, type and content."""
    if isinstance(value, BaseModel):
        return [(path, type(value), value.model_dump_json())]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [(path, type(value), "")] + [
            member
            for item in dataclasses.fields(value)
            for member in _members(getattr(value, item.name), f"{path}.{item.name}")
        ]
    if isinstance(value, tuple):
        return [(path, tuple, str(len(value)))] + [
            member
            for position, item in enumerate(value)
            for member in _members(item, f"{path}.{position}")
        ]
    if isinstance(value, Mapping):
        return [(path, Mapping, str(len(value)))] + [
            member
            for key, item in value.items()
            for member in _members(key, f"{path}[key]") + _members(item, f"{path}[]")
        ]
    return [(path, type(value), repr(value))]


def _models(value: object) -> list[BaseModel]:
    return [item for item in _reachable(value) if isinstance(item, BaseModel)]


@pytest.mark.parametrize(
    "build", [_structural_context, _economic_context], ids=["m1b", "m1b-and-m1c"]
)
def test_a_genuine_m1d_context_rebuilds_member_for_member(
    build: Callable[[], Any],
) -> None:
    """Every member keeps its type and content, and no model is shared."""
    genuine = build()
    rebuilt = _canonical_m1d_context(genuine)

    assert _members(rebuilt) == _members(genuine)
    assert m1d_context_hash(rebuilt) == m1d_context_hash(genuine)
    assert {id(item) for item in _models(rebuilt)}.isdisjoint(
        id(item) for item in _models(genuine)
    )
    validate_m1d_resolution_context(rebuilt)


class _SpelledUUID(UUID):
    """Holds its own identifier, but spells another."""

    def __str__(self) -> str:
        return "01990000-0000-7000-8000-00000000dead"


class _LyingBytes(bytes):
    """Holds its own bytes, but decodes to other text."""

    def decode(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return "tampered"


class _ApartKey(str):
    """A key equal only to itself, so a mapping can hold it beside its text."""

    def __hash__(self) -> int:
        return hash(("apart", str.__str__(self)))

    def __eq__(self, other: object) -> bool:
        return self is other

    def __ne__(self, other: object) -> bool:
        return self is not other


class _DuckModel(BaseModel):
    """Any model's content, under a model that is not the declared one."""

    model_config = ConfigDict(extra="allow")


class _ItemsOnly:
    """Offers ``items`` and ``len`` of a mapping without being one."""

    def __init__(self, entries: Mapping[Any, Any]) -> None:
        self.entries = dict(entries)

    def items(self) -> Any:
        return self.entries.items()

    def __len__(self) -> int:
        return len(self.entries)


def _fields_of(artifact: Any) -> dict[str, Any]:
    return {
        item.name: getattr(artifact, item.name) for item in dataclasses.fields(artifact)
    }


def _first_supporting_artifact(context: Any, forge: Callable[[Any], Any]) -> Any:
    key, artifact = next(iter(context.supporting_artifacts.items()))
    supporting = dict(context.supporting_artifacts) | {key: forge(artifact)}
    return dataclasses.replace(context, supporting_artifacts=supporting)


def _with_structural(context: Any, **changes: Any) -> Any:
    structural = dataclasses.replace(context.structural_context, **changes)
    return dataclasses.replace(context, structural_context=structural)


def _with_universe(context: Any, **changes: Any) -> Any:
    universe = dataclasses.replace(context.structural_context.universe, **changes)
    return _with_structural(context, universe=universe)


def _with_first_dataset(context: Any, **changes: Any) -> Any:
    first, *rest = context.observation_datasets
    datasets = (dataclasses.replace(first, **changes), *rest)
    return dataclasses.replace(context, observation_datasets=datasets)


def _with_a_second_key_for_one_artifact(context: Any) -> Any:
    key, artifact = next(iter(context.supporting_artifacts.items()))
    supporting = dict(context.supporting_artifacts) | {_ApartKey(key): artifact}
    assert len(supporting) == len(context.supporting_artifacts) + 1
    return dataclasses.replace(context, supporting_artifacts=supporting)


#: Each mistyped, forged or duplicated member of a genuine M1b context, and the
#: exception and message its rebuild must refuse it with. Each would otherwise
#: be kept (a bytes subclass), coerced by lax validation, dropped as a
#: duplicate key, or repaired into a valid member of the declared type.
REFUSED_CONTEXT_MEMBERS: dict[str, tuple[Callable[[Any], Any], type, str]] = {
    "bytes-subclass-with-its-own-decode": (
        lambda context: _first_supporting_artifact(
            context,
            lambda artifact: dataclasses.replace(
                artifact, data=_LyingBytes(artifact.data)
            ),
        ),
        TypeError,
        r"member of type _LyingBytes is not exactly bytes",
    ),
    "identifier-as-text-for-lax-validation": (
        lambda context: dataclasses.replace(context, issuer_id=str(context.issuer_id)),
        ValidationError,
        r"UUID",
    ),
    "one-artifact-under-two-keys-that-are-one": (
        _with_a_second_key_for_one_artifact,
        ValueError,
        r"^an M1d context mapping holds two keys that are one$",
    ),
    "channel-as-a-dict-of-its-fields": (
        lambda context: dataclasses.replace(
            context, m1b_requested_channel=context.m1b_requested_channel.model_dump()
        ),
        TypeError,
        r"member of type dict is not one its declaration admits",
    ),
    "manifest-under-another-model": (
        lambda context: _with_first_dataset(
            context,
            manifest=_DuckModel(
                **context.observation_datasets[0].manifest.model_dump()
            ),
        ),
        TypeError,
        r"member of type _DuckModel is not a DatasetManifestV2",
    ),
    "artifact-as-a-lookalike-object": (
        lambda context: _first_supporting_artifact(
            context, lambda artifact: SimpleNamespace(**_fields_of(artifact))
        ),
        TypeError,
        r"member of type SimpleNamespace is not a VerifiedArtifactBytes",
    ),
    "records-as-a-list": (
        lambda context: _with_structural(
            context,
            roles=dataclasses.replace(
                context.structural_context.roles,
                records=list(context.structural_context.roles.records),
            ),
        ),
        TypeError,
        r"member of type list is not a tuple",
    ),
    "retained-evidence-as-an-items-only-object": (
        lambda context: _with_universe(
            context,
            retained_evidence=_ItemsOnly(
                context.structural_context.universe.retained_evidence
            ),
        ),
        TypeError,
        r"member of type _ItemsOnly is not a mapping",
    ),
}


@pytest.mark.parametrize("member", REFUSED_CONTEXT_MEMBERS)
def test_a_mistyped_m1d_context_member_is_refused_not_repaired(member: str) -> None:
    forge, refusal, reason = REFUSED_CONTEXT_MEMBERS[member]
    forged = forge(_structural_context())

    with pytest.raises(refusal, match=reason):
        _canonical_m1d_context(forged)


def test_a_spelled_identifier_in_an_m1d_context_is_rebuilt_to_its_value() -> None:
    """A strictly valid ``UUID`` subclass is still rebuilt through JSON."""
    genuine = _structural_context()
    forged = dataclasses.replace(
        genuine, issuer_id=_SpelledUUID(int=genuine.issuer_id.int)
    )

    rebuilt = _canonical_m1d_context(forged)

    assert type(rebuilt.issuer_id) is UUID
    assert str(rebuilt.issuer_id) == str(UUID(int=genuine.issuer_id.int))


# --- the book currency strings (#131 round 2) ---------------------------------


def _book_engine(
    *, namespace: str = eng.BOOK_NAMESPACE, code: str
) -> SessionEvaluatorEngine:
    """The reconstructed lane over USD reconstructions, in the given book."""
    bundle = bundle_of((scheduled_session_case(JAN5), scheduled_session_case(JAN6)))
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=exploratory_admission(bundle),
        protocol=eng._protocol(warmup=1),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS,
            exploratory_cohort=cohort_of(),
            exploratory_reconstruction_replay=replay_of(
                bundle.exploratory_reconstructed_observations
            ),
        ),
        book_currency_namespace=namespace,
        book_currency_code=code,
    )


def test_a_book_in_another_currency_still_halts_indeterminate() -> None:
    """Control: an honest EUR book over USD prices never fills."""
    artifacts = run_engine(
        _book_engine(code="EUR"), ReconstructedTargetStrategy({JAN5: ((SEC, 1),)})
    )

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.metrics.committed_fill_count == 0
    assert artifacts.result.halt_reason is not None
    assert artifacts.result.halt_reason.endswith("not the book currency EUR")


@pytest.mark.parametrize("argument", ["namespace", "code"])
def test_a_book_currency_string_with_forged_equality_is_refused(
    argument: str,
) -> None:
    """#131 round 2, G1: the probe's EUR book equal to every currency.

    Held as given, an ``EUR`` book code equal to every string matched the
    USD prices, so the run filled and ended COMPLETE under the evaluator
    evidence hash of an honest EUR book, which refuses those prices.
    """
    honest = {"namespace": eng.BOOK_NAMESPACE, "code": "EUR"}
    forged = honest | {argument: _AlwaysEqualStr(honest[argument])}

    with pytest.raises(
        NonCanonicalEngineInputError,
        match=rf"^the engine's book_currency_{argument} must be exactly a str, "
        r"not _AlwaysEqualStr$",
    ):
        _book_engine(**forged)


# --- the strategy's decision context (issue 123) ------------------------------
#
# The engine handed each strategy a context built from its own objects: the
# admitted universe and the holdings held the very `UUID` instances of the
# bundle and the book (#119 review R2-F2, R3-F1). A strategy rewriting one in
# place rewrote the engine's state, and the run could end COMPLETE with a
# trace naming an unadmitted security. Each strategy now gets a canonical
# JSON-rebuilt copy of its context, sharing no object with the engine.

#: A UUIDv7 no input names: every identifier a strategy rewrites becomes it.
_ELSEWHERE = UUID("01990000-0000-7000-8000-0000000009ff")


def _defaced(value: object) -> object:
    """Another value of the same kind, for a field rewritten in place."""
    if value is None or isinstance(value, bool | Enum):
        return value
    if isinstance(value, date):
        return value + timedelta(days=1)
    if isinstance(value, Decimal | int):
        return value + 1
    if isinstance(value, str):
        return f"{value}-defaced"
    if isinstance(value, tuple):
        return ()
    return value


def _vandalize(*roots: object) -> None:
    """Rewrite every object reachable from ``roots`` in place, past every guard.

    Every identifier's integer slot is moved to ``_ELSEWHERE``, then every
    field of every model is replaced by another value of its kind.
    """
    reachable = _reachable(*roots)
    for item in reachable:
        if isinstance(item, UUID):
            object.__setattr__(item, "int", _ELSEWHERE.int)
    for item in reachable:
        if isinstance(item, BaseModel):
            for name, value in list(vars(item).items()):
                object.__setattr__(item, name, _defaced(value))


def _detached(intent: StrategyDecisionIntentV1) -> StrategyDecisionIntentV1:
    """The answer rebuilt, so it shares no object with the context it read."""
    return StrategyDecisionIntentV1.model_validate_json(intent.model_dump_json())


class _VandalRealizedStrategy(eng.FixedTargetStrategy):
    """Answers as asked, then rewrites every context it was ever handed."""

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        answer = _detached(super().decide(context))
        _vandalize(*self.seen)
        return answer


class _VandalReconstructedStrategy(ReconstructedTargetStrategy):
    """Answers as asked, then rewrites every context it was ever handed."""

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        answer = _detached(super().decide_exploratory(context))
        _vandalize(*self.seen)
        return answer


def _fresh[M: BaseModel](model: M) -> M:
    """A copy sharing no object with ``model``, so no rewrite leaves this test."""
    return type(model).model_validate_json(model.model_dump_json())


def _context_runs(
    lane: str,
) -> tuple[
    EvaluationRunArtifactsV2,
    EvaluationRunArtifactsV2,
    Sequence[StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1],
    Sequence[StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1],
]:
    """A control run and a vandal run, each over inputs shared with nothing."""
    if lane == "realized":
        targets = dict.fromkeys(eng.DAYS, REQUESTED)
        control = eng.FixedTargetStrategy(targets)
        vandal = _VandalRealizedStrategy(targets)
        runs = [
            eng._run(eng._engine(bundle=_fresh(eng._bundle())), strategy)
            for strategy in (control, vandal)
        ]
        return runs[0], runs[1], control.seen, vandal.seen
    exploratory = dict.fromkeys((JAN5, JAN6, JAN7), REQUESTED)
    control_x = ReconstructedTargetStrategy(exploratory)
    vandal_x = _VandalReconstructedStrategy(exploratory)
    runs = [
        run_engine(
            reconstructed_engine(
                _fresh(bundle_of(three_regular_sessions())), cohort=_fresh(cohort_of())
            ),
            strategy,
        )
        for strategy in (control_x, vandal_x)
    ]
    return runs[0], runs[1], control_x.seen, vandal_x.seen


@pytest.mark.parametrize("lane", LANES)
def test_a_strategy_rewriting_its_contexts_changes_nothing_the_engine_records(
    lane: str,
) -> None:
    """No context object a strategy can reach is engine state (issue 123)."""
    control, vandal, genuine_contexts, rewritten_contexts = _context_runs(lane)

    # The rewrite really ran: every context the vandal saw was moved.
    assert len(rewritten_contexts) == len(genuine_contexts) >= 2
    assert all(
        rewritten.decision_cutoff > genuine.decision_cutoff
        for rewritten, genuine in zip(rewritten_contexts, genuine_contexts, strict=True)
    )
    assert vandal.result.classification is EvaluationClassification.COMPLETE
    fills = [
        [content_hash(event) for event in run.trace.events if event.kind == "fill"]
        for run in (control, vandal)
    ]
    assert fills[0]
    assert fills[1] == fills[0]
    assert vandal.trace.trace_hash == control.trace.trace_hash
    assert vandal.result.result_hash == control.result.result_hash
    assert content_hash(vandal.final_state) == content_hash(control.final_state)
