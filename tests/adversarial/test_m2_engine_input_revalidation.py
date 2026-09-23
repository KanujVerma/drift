"""M2 adversarial acceptance: the engine revalidates every input it runs on.

Issue 78, from the #8 final acceptance review (finding F6). Pydantic trusts an
existing model instance placed in a typed field, so an input built with
``model_construct`` is never checked unless something revalidates it. The
engine compared declared hashes only: a bundle could keep a genuine
``bundle_hash`` over different prices, and a raw vendor payload could ride a
typed field into ``RuntimeStrategy.decide``. Every input is now revalidated
through its canonical validated boundary at construction.
"""

# ruff: noqa: E402

import dataclasses
import sys
import typing
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
import test_evaluator_engine as eng
from pydantic import ValidationError, model_validator
from test_evaluator_reconstruction import make_policy

from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    evaluation_input_bundle_hash,
)
from drift.domain.evaluator_reconstruction import ExploratoryReconstructionPolicyV1
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
    )
    forged = type(identity).model_construct(
        **(dict(identity) | {"run_identity_hash": "e" * 64})
    )
    strategy = eng._buy_ten()

    with pytest.raises(ValidationError, match=r"run identity hash mismatch"):
        engine.run(strategy=strategy, run_identity=forged)
    assert strategy.seen == []
