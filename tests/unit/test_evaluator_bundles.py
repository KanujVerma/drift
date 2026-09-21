"""Unit tests for M2 Task 2B input bundle, lane gates, and run identity."""

from datetime import date
from typing import Any, Literal

import pytest
from observation_test_support import (
    NormalizationHarness,
    ObservationHarness,
    uid,
)
from pydantic import ValidationError
from test_assertions import exact_boundary
from test_evaluator_admission_gatekeeper import make_test_fixture, rebind_admission
from test_evaluator_reconstruction import build_from_harness

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    evaluation_input_bundle_hash,
    evaluation_run_identity_hash,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.replay_provenance import build_bundle_provenance_proof
from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_input_bundle,
    build_evaluation_run_identity,
    validate_exploratory_admission,
    validate_promotion_admission,
    verify_evaluation_input_bundle,
)
from drift.evaluator.clock import (
    build_realized_session_clock,
    build_scheduled_reconstruction_clock,
)
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)

H = {c: c * 64 for c in "0123456789abcdef"}


# --- fixtures ---


RealizedOutcomeT = Literal[
    "opened", "opened_without_bounds", "did_not_open", "unknown", "missing"
]


def _harness(*, realized_outcome: RealizedOutcomeT = "missing") -> ObservationHarness:
    harness = ObservationHarness()
    harness.attach_sessions(schedule_state="regular", realized_outcome=realized_outcome)
    return harness


def _queries(harness: ObservationHarness) -> tuple[ObservationOutcomeQueryV1, ...]:
    return (
        harness.outcome(
            economic_horizon="2026-01-06T00:00:00Z",
            evidence_vintage_cutoff="2026-01-06T00:00:00Z",
            session_date="2026-01-05",
        ),
    )


def _interval() -> TemporalIntervalClaimV1:
    return TemporalIntervalClaimV1(schema_version="1", start=exact_boundary(), end=None)


def _realized_clock() -> Any:
    harness = _harness(realized_outcome="opened")
    return build_realized_session_clock(_queries(harness), harness.context)


def _scheduled_clock() -> Any:
    harness = _harness()
    return build_scheduled_reconstruction_clock(_queries(harness), harness.context)


def _realized_bundle(**overrides: Any) -> EvaluationInputBundleV1:
    kwargs: dict[str, Any] = {
        "evaluation_interval": _interval(),
        "session_clock": _realized_clock(),
    }
    kwargs.update(overrides)
    return assemble_evaluation_input_bundle(**kwargs)


def _scheduled_bundle(**overrides: Any) -> EvaluationInputBundleV1:
    kwargs: dict[str, Any] = {
        "evaluation_interval": _interval(),
        "session_clock": _scheduled_clock(),
    }
    kwargs.update(overrides)
    return assemble_evaluation_input_bundle(**kwargs)


def _exploratory_admission(
    bundle: EvaluationInputBundleV1, limitations: tuple[str, ...] | None = None
) -> ExploratoryEvaluationAdmissionV1:
    acknowledged = (
        limitations if limitations is not None else bundle.required_limitations
    )
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=bundle.bundle_hash,
        acknowledged_limitations=tuple(sorted(acknowledged)),
        admission_hash=H["0"],
    )
    candidate = draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )
    return ExploratoryEvaluationAdmissionV1.model_validate(candidate.model_dump())


# --- bundle hashing ---


def test_bundle_hash_is_self_excluding_and_exact() -> None:
    bundle = _realized_bundle()
    assert bundle.bundle_hash == evaluation_input_bundle_hash(bundle)


def test_bundle_hash_is_acyclic_over_its_own_field() -> None:
    bundle = _realized_bundle()
    mutated = EvaluationInputBundleV1.model_construct(
        **(dict(bundle) | {"bundle_hash": H["f"]})
    )
    # Recomputing over the mutated object yields the original digest, proving
    # bundle_hash is excluded from its own preimage.
    assert evaluation_input_bundle_hash(mutated) == bundle.bundle_hash


def test_bundle_rebuild_is_deterministic() -> None:
    assert _realized_bundle().bundle_hash == _realized_bundle().bundle_hash


def test_bundle_rejects_tampered_hash() -> None:
    bundle = _realized_bundle()
    payload = bundle.model_dump()
    payload["bundle_hash"] = H["a"]
    with pytest.raises(ValidationError):
        EvaluationInputBundleV1.model_validate(payload)


def test_bundle_member_order_does_not_change_hash() -> None:
    first = SecurityV1(schema_version="1", security_id=uid(21))
    second = SecurityV1(schema_version="1", security_id=uid(22))
    forward = _realized_bundle(security_identities=(first, second))
    reverse = _realized_bundle(security_identities=(second, first))
    assert forward.bundle_hash == reverse.bundle_hash
    assert forward.security_identities == reverse.security_identities


def test_bundle_rejects_duplicate_members() -> None:
    listing = ListingV1(schema_version="1", listing_id=uid(1), venue=ListingVenue.XNAS)
    with pytest.raises((ValidationError, ValueError)):
        _realized_bundle(listing_identities=(listing, listing))


def test_bundle_hash_changes_when_a_member_changes() -> None:
    base = _realized_bundle()
    with_security = _realized_bundle(
        security_identities=(SecurityV1(schema_version="1", security_id=uid(21)),)
    )
    assert base.bundle_hash != with_security.bundle_hash


# --- exploratory reconstruction detection ---


def test_realized_bundle_has_no_exploratory_reconstructions() -> None:
    assert _realized_bundle().has_exploratory_reconstructions is False


def test_scheduled_clock_marks_bundle_as_exploratory() -> None:
    bundle = _scheduled_bundle()
    assert bundle.session_clock.mode == "scheduled_session_reconstruction"
    assert bundle.has_exploratory_reconstructions is True


def test_scheduled_bundle_requires_reconstruction_limitations() -> None:
    required = _scheduled_bundle().required_limitations
    assert ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION in required
    assert ALPACA_LIMITATION_ABSENT_HALTS in required


# --- exploratory lane gate ---


def test_exploratory_gate_accepts_bound_bundle() -> None:
    bundle = _scheduled_bundle()
    validate_exploratory_admission(
        admission=_exploratory_admission(bundle), bundle=bundle
    )


def test_exploratory_gate_rejects_bundle_hash_mismatch() -> None:
    bundle = _scheduled_bundle()
    admission = _exploratory_admission(bundle)
    other = _realized_bundle(
        security_identities=(SecurityV1(schema_version="1", security_id=uid(31)),)
    )
    with pytest.raises(ValueError, match="input bundle hash mismatch"):
        validate_exploratory_admission(admission=admission, bundle=other)


def test_exploratory_gate_rejects_promotion_snapshot_binding() -> None:
    bundle = _scheduled_bundle(source_snapshot_hash=H["b"])
    with pytest.raises(ValueError, match="cannot bind a promotion source snapshot"):
        validate_exploratory_admission(
            admission=_exploratory_admission(bundle), bundle=bundle
        )


def test_exploratory_gate_rejects_dropped_limitation() -> None:
    bundle = _scheduled_bundle()
    kept = tuple(
        item
        for item in bundle.required_limitations
        if item != ALPACA_LIMITATION_ABSENT_HALTS
    )
    admission = _exploratory_admission(bundle, limitations=kept)
    with pytest.raises(ValueError, match="omits required bundle limitations"):
        validate_exploratory_admission(admission=admission, bundle=bundle)


# --- promotion lane gate (anti-laundering) ---


def _promotion_case(bundle: EvaluationInputBundleV1) -> dict[str, Any]:
    fixture = make_test_fixture()
    # The gate now validates a provenance proof. Snapshot binding of the proof
    # itself is exercised in tests/unit/test_replay_provenance.py.
    proof = build_bundle_provenance_proof(
        qualified_context_hash=H["9"],
        source_snapshot_hash=bundle.source_snapshot_hash or H["0"],
        bundle=bundle,
    )
    fixture["admission"] = rebind_admission(
        fixture,
        input_bundle_hash=bundle.bundle_hash,
        provenance_proof_hash=proof.proof_hash,
    )
    fixture["bundle"] = bundle
    fixture["proof"] = proof
    return fixture


def test_promotion_gate_accepts_realized_snapshot_bound_bundle() -> None:
    snapshot = make_test_fixture()["decision_handoff"].snapshot_hash
    _, _, _, decision_view = _decision_case()
    validate_promotion_admission(
        **_promotion_case(
            _realized_bundle(
                source_snapshot_hash=snapshot,
                authentic_decision_views=(decision_view,),
            )
        )
    )


def test_promotion_gate_rejects_exploratory_reconstruction_clock() -> None:
    snapshot = make_test_fixture()["decision_handoff"].snapshot_hash
    case = _promotion_case(_scheduled_bundle(source_snapshot_hash=snapshot))
    with pytest.raises(ValueError, match="cannot consume exploratory reconstructed"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_bundle_hash_mismatch() -> None:
    snapshot = make_test_fixture()["decision_handoff"].snapshot_hash
    case = _promotion_case(_realized_bundle(source_snapshot_hash=snapshot))
    case["bundle"] = _realized_bundle(
        source_snapshot_hash=snapshot,
        security_identities=(SecurityV1(schema_version="1", security_id=uid(41)),),
    )
    with pytest.raises(ValueError, match="input bundle hash mismatch"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_snapshot_mismatch() -> None:
    case = _promotion_case(_realized_bundle(source_snapshot_hash=H["c"]))
    with pytest.raises(ValueError, match="snapshot mismatch"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_missing_snapshot() -> None:
    case = _promotion_case(_realized_bundle())
    with pytest.raises(ValueError, match="snapshot mismatch"):
        validate_promotion_admission(**case)


# --- deterministic run identity ---


def _identity_args(**overrides: str) -> dict[str, str]:
    args = {
        "strategy_hash": H["1"],
        "protocol_hash": H["2"],
        "cost_model_hash": H["3"],
        "admission_hash": H["4"],
        "bundle_hash": H["5"],
        "code_version_hash": H["6"],
        "environment_closure_hash": H["7"],
    }
    args.update(overrides)
    return args


def test_run_identity_is_deterministic() -> None:
    first = build_evaluation_run_identity(**_identity_args())
    second = build_evaluation_run_identity(**_identity_args())
    assert first.run_identity_hash == second.run_identity_hash
    assert first.run_identity_hash == evaluation_run_identity_hash(first)


@pytest.mark.parametrize(
    "field",
    [
        "strategy_hash",
        "protocol_hash",
        "cost_model_hash",
        "admission_hash",
        "bundle_hash",
        "code_version_hash",
        "environment_closure_hash",
    ],
)
def test_run_identity_depends_on_every_input(field: str) -> None:
    base = build_evaluation_run_identity(**_identity_args())
    changed = build_evaluation_run_identity(**_identity_args(**{field: H["e"]}))
    assert base.run_identity_hash != changed.run_identity_hash


def test_run_identity_rejects_tampered_hash() -> None:
    identity = build_evaluation_run_identity(**_identity_args())
    payload = identity.model_dump()
    payload["run_identity_hash"] = H["d"]
    with pytest.raises(ValidationError):
        type(identity).model_validate(payload)


# --- replay-bound preparation and verification ---


def _decision_case() -> tuple[Any, Any, Any, Any]:
    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    result = harness.normalize(query)
    view = materialize_observation_decision(result.reference, query, harness.context)
    return harness, query, result.reference, view


def _accounting_case() -> tuple[Any, Any, Any, Any]:
    harness = NormalizationHarness()
    query = harness.normalization_query("source_basis")
    result = harness.normalize(query)
    view = materialize_observation_outcome(result.reference, query, harness.context)
    return harness, query, result.reference, view


def test_build_bundle_materializes_views_through_replay() -> None:
    harness, query, reference, view = _decision_case()
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=_realized_clock(),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    assert bundle.authentic_decision_views == (view,)


def test_verify_accepts_genuinely_replayed_bundle() -> None:
    harness, query, reference, _ = _decision_case()
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=_realized_clock(),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    verify_evaluation_input_bundle(
        bundle=bundle,
        context=harness.context,
        decision_requests=((reference, query),),
    )


def test_verify_rejects_view_that_replay_did_not_produce() -> None:
    harness, query, reference, view = _decision_case()
    forged = EvaluationInputBundleV1.model_construct(
        **(
            dict(
                assemble_evaluation_input_bundle(
                    evaluation_interval=_interval(),
                    session_clock=_realized_clock(),
                    authentic_decision_views=(view,),
                )
            )
        )
    )
    tampered = EvaluationInputBundleV1.model_construct(
        **(dict(forged) | {"authentic_decision_views": ()})
    )
    with pytest.raises(ValueError, match="view count mismatch against replay"):
        verify_evaluation_input_bundle(
            bundle=tampered,
            context=harness.context,
            decision_requests=((reference, query),),
        )


def test_verify_rejects_bundle_whose_hash_does_not_match_contents() -> None:
    harness, query, reference, _ = _decision_case()
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=_realized_clock(),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    broken = EvaluationInputBundleV1.model_construct(
        **(dict(bundle) | {"bundle_hash": H["9"]})
    )
    with pytest.raises(ValueError, match="does not match its own contents"):
        verify_evaluation_input_bundle(
            bundle=broken,
            context=harness.context,
            decision_requests=((reference, query),),
        )


# --- view role and basis binding ---


def test_decision_bucket_rejects_outcome_role_view() -> None:
    _, _, _, outcome_view = _accounting_case()
    with pytest.raises((ValidationError, ValueError), match="decision-role evidence"):
        _realized_bundle(authentic_decision_views=(outcome_view,))


def test_accounting_bucket_rejects_decision_role_view() -> None:
    _, _, _, decision_view = _decision_case()
    with pytest.raises((ValidationError, ValueError), match="outcome-role evidence"):
        _realized_bundle(authentic_accounting_views=(decision_view,))


def test_accounting_bucket_requires_unadjusted_source_basis() -> None:
    harness = NormalizationHarness()
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    result = harness.normalize(query)
    view = materialize_observation_outcome(result.reference, query, harness.context)
    assert view.basis_mode == "split_normalized"
    with pytest.raises((ValidationError, ValueError), match="unadjusted source basis"):
        _realized_bundle(authentic_accounting_views=(view,))


# --- exploratory reconstruction carried on a realized clock ---


def test_reconstructed_observations_mark_bundle_exploratory_on_realized_clock() -> None:
    harness = _harness()
    observation = build_from_harness(harness)
    bundle = _realized_bundle(exploratory_reconstructed_observations=(observation,))
    assert bundle.session_clock.mode == "realized_session_authority"
    assert bundle.has_exploratory_reconstructions is True


def test_reconstruction_limitations_merge_into_required_limitations() -> None:
    harness = _harness()
    observation = build_from_harness(harness)
    bundle = _realized_bundle(exploratory_reconstructed_observations=(observation,))
    for limitation in observation.acknowledged_limitations:
        assert limitation in bundle.required_limitations


def test_promotion_gate_rejects_reconstructions_on_realized_clock() -> None:
    harness = _harness()
    observation = build_from_harness(harness)
    snapshot = make_test_fixture()["decision_handoff"].snapshot_hash
    case = _promotion_case(
        _realized_bundle(
            source_snapshot_hash=snapshot,
            exploratory_reconstructed_observations=(observation,),
        )
    )
    with pytest.raises(ValueError, match="cannot consume exploratory reconstructed"):
        validate_promotion_admission(**case)


# --- promotion evidence sufficiency ---


def test_promotion_gate_rejects_vacuous_bundle() -> None:
    snapshot = make_test_fixture()["decision_handoff"].snapshot_hash
    case = _promotion_case(_realized_bundle(source_snapshot_hash=snapshot))
    with pytest.raises(ValueError, match="at least one authentic decision view"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_clock_declaring_exploratory_limitations() -> None:
    harness = _harness()
    observation = build_from_harness(harness)
    _, _, _, decision_view = _decision_case()
    snapshot = make_test_fixture()["decision_handoff"].snapshot_hash
    bundle = _realized_bundle(
        source_snapshot_hash=snapshot,
        authentic_decision_views=(decision_view,),
        exploratory_reconstructed_observations=(observation,),
    )
    case = _promotion_case(bundle)
    with pytest.raises(ValueError):
        validate_promotion_admission(**case)


def test_bundle_source_snapshot_defaults_to_none() -> None:
    assert _realized_bundle().source_snapshot_hash is None


def test_verify_rejects_same_count_view_that_differs_from_replay() -> None:
    harness, query, reference, view = _decision_case()
    forged = DerivedObservationViewV1.model_construct(
        **(dict(view) | {"derivation_hash": H["e"]})
    )
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=_realized_clock(),
        authentic_decision_views=(forged,),
    )
    assert len(bundle.authentic_decision_views) == 1
    with pytest.raises(ValueError, match="do not match exact upstream replay"):
        verify_evaluation_input_bundle(
            bundle=bundle,
            context=harness.context,
            decision_requests=((reference, query),),
        )


def test_build_and_verify_accounting_views_through_replay() -> None:
    harness, query, reference, view = _accounting_case()
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=_realized_clock(),
        context=harness.context,
        accounting_requests=((reference, query),),
    )
    assert bundle.authentic_accounting_views == (view,)
    verify_evaluation_input_bundle(
        bundle=bundle,
        context=harness.context,
        accounting_requests=((reference, query),),
    )
