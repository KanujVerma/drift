"""Unit tests for M2 Task 2B input bundle, lane gates, and run identity."""

from datetime import date, timedelta
from functools import cache
from typing import Any, Literal

import pytest
from observation_test_support import (
    NormalizationHarness,
    ObservationHarness,
    uid,
)
from pydantic import ValidationError
from replay_provenance_test_support import qualified_snapshot
from test_assertions import exact_boundary
from test_evaluator_admission_gatekeeper import make_test_fixture, rebind_admission
from test_evaluator_reconstruction import build_from_harness

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    evaluation_input_bundle_hash,
    evaluation_run_identity_hash,
)
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockMode,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.replay_provenance import _build_bundle_provenance_proof
from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
from drift.domain.source_snapshots import RealSourceSnapshotV1
from drift.evaluator.bundles import (
    DecisionReplayRequests,
    OutcomeReplayRequests,
    assemble_evaluation_input_bundle,
    build_evaluation_input_bundle,
    build_evaluation_run_identity,
    mint_bundle_provenance_proof,
    qualify_replay_context,
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
from drift.markets.observation_validation import m1d_context_hash

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


def _normalization_session_query(harness: NormalizationHarness) -> Any:
    """A session query over the normalization corpus's own realized session."""
    return harness.source.outcome(
        economic_horizon="2026-12-01T00:00:00Z",
        evidence_vintage_cutoff="2026-12-01T00:00:00Z",
        session_date="2026-11-27",
    ).model_copy(
        update={
            "source_selection_policy_hash": harness._source_policy_hash,
            "input_context_hash": m1d_context_hash(harness.context),
        }
    )


def normalization_session_queries(harness: NormalizationHarness) -> tuple[Any, ...]:
    """The session queries both normalization clocks are built from.

    Minting and verification re-derive the bundle clock from exactly these
    (issue 80), so a test hands them over rather than rebuilding them.
    """
    return (_normalization_session_query(harness),)


def normalization_realized_clock(harness: NormalizationHarness) -> Any:
    """Realized clock over the session the normalization views actually bind.

    Bundle members must fall inside their own clock, so evidence materialized
    from a normalization harness needs a clock built from that same corpus.
    """
    return build_realized_session_clock(
        normalization_session_queries(harness), harness.context
    )


def normalization_scheduled_clock(harness: NormalizationHarness) -> Any:
    """Scheduled-reconstruction clock over the normalization corpus's session."""
    return build_scheduled_reconstruction_clock(
        normalization_session_queries(harness), harness.context
    )


def _merged_realized_clock(harness: NormalizationHarness) -> SessionClockV1:
    """One realized clock covering both corpora used by these fixtures."""
    sessions = tuple(
        sorted(
            (
                *_realized_clock().sessions,
                *normalization_realized_clock(harness).sessions,
            ),
            key=session_order_key,
        )
    )
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=sessions,
        acknowledged_limitations=(),
        clock_hash=H["0"],
    )
    return SessionClockV1.model_validate(
        draft.model_copy(update={"clock_hash": session_clock_hash(draft)}).model_dump()
    )


def resealed_clock(
    clock: SessionClockV1,
    *,
    mode: SessionClockMode | None = None,
    acknowledged_limitations: tuple[str, ...] | None = None,
    **session_updates: object,
) -> SessionClockV1:
    """Edit every session of a clock, then reseal it so only the edit remains.

    The result is fully valid under `SessionClockV1`: its own hashes prove only
    that it is self-consistent, never that a builder produced it.
    """
    sessions = []
    for session in clock.sessions:
        draft = EvaluationSessionV1.model_construct(**(dict(session) | session_updates))
        sessions.append(
            EvaluationSessionV1.model_validate(
                dict(draft) | {"session_hash": evaluation_session_hash(draft)}
            )
        )
    clock_updates: dict[str, object] = {"sessions": tuple(sessions)}
    if mode is not None:
        clock_updates["mode"] = mode
    if acknowledged_limitations is not None:
        clock_updates["acknowledged_limitations"] = acknowledged_limitations
    draft_clock = SessionClockV1.model_construct(**(dict(clock) | clock_updates))
    return SessionClockV1.model_validate(
        dict(draft_clock) | {"clock_hash": session_clock_hash(draft_clock)}
    )


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


@cache
def _provenance_harness() -> ObservationHarness:
    """The corpus behind `_realized_clock`, for bundles that replay no view.

    Cached so that the snapshot a test asserts on its bundle and the snapshot
    the case qualifies against are the same artifact rather than two
    independently rebuilt ones that merely ought to agree.
    """
    return _harness(realized_outcome="opened")


def _provenance_context() -> Any:
    """A real M1d resolution context for bundles that carry no replayed view."""
    return _provenance_harness().context


def _provenance_session_queries() -> tuple[ObservationOutcomeQueryV1, ...]:
    """The session queries `_realized_clock` is built from."""
    return _queries(_provenance_harness())


@cache
def _default_promotion_snapshot() -> RealSourceSnapshotV1:
    """The snapshot for the default context, built once for the whole module."""
    return qualified_snapshot(_provenance_context())


def _promotion_snapshot(context: Any | None = None) -> RealSourceSnapshotV1:
    """The real snapshot a promotion bundle must assert to be admissible."""
    if context is None:
        return _default_promotion_snapshot()
    return qualified_snapshot(context)


def _promotion_case(
    bundle: EvaluationInputBundleV1,
    *,
    context: Any | None = None,
    session_queries: tuple[Any, ...] | None = None,
    decision_requests: DecisionReplayRequests = (),
    accounting_requests: OutcomeReplayRequests = (),
    handoff_snapshot_hash: str | None = None,
) -> dict[str, Any]:
    """Build gate kwargs through the verified path, never by raw assembly.

    The proof is minted from a genuinely qualified replay context over a real
    source snapshot, because the gate now re-audits the containment witness.
    Assembling a proof directly would no longer reach any gate under test.
    Minting re-derives the bundle clock (issue 80), so a case over another
    context must name that context's own session queries.
    """
    replay_context = context if context is not None else _provenance_context()
    if session_queries is None:
        session_queries = _provenance_session_queries() if context is None else ()
    snapshot = _promotion_snapshot(context)
    qualified = qualify_replay_context(context=replay_context, snapshot=snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=replay_context,
        bundle=bundle,
        session_queries=session_queries,
        decision_requests=decision_requests,
        accounting_requests=accounting_requests,
    )
    fixture = make_test_fixture(
        snapshot_hash=handoff_snapshot_hash
        if handoff_snapshot_hash is not None
        else snapshot.snapshot_hash
    )
    fixture["admission"] = rebind_admission(
        fixture,
        input_bundle_hash=bundle.bundle_hash,
        provenance_proof_hash=proof.proof_hash,
    )
    fixture["bundle"] = bundle
    fixture["proof"] = proof
    fixture["qualified_context"] = qualified
    fixture["snapshot"] = snapshot
    return fixture


def test_promotion_gate_accepts_realized_snapshot_bound_bundle() -> None:
    harness, query, reference, decision_view = _decision_case()
    snapshot = _promotion_snapshot(harness.context)
    # The clock must contain the session the decision view binds. This test
    # previously encoded the broken shape where it did not.
    validate_promotion_admission(
        **_promotion_case(
            _realized_bundle(
                session_clock=normalization_realized_clock(harness),
                source_snapshot_hash=snapshot.snapshot_hash,
                authentic_decision_views=(decision_view,),
            ),
            context=harness.context,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )
    )


def test_promotion_gate_rejects_exploratory_reconstruction_clock() -> None:
    snapshot = _promotion_snapshot()
    # Minting re-derives the clock (issue 80), so the scheduled clock must come
    # from the corpus the case replays against. It is genuine, and the gate
    # still refuses its mode.
    genuine = build_scheduled_reconstruction_clock(
        _provenance_session_queries(), _provenance_context()
    )
    case = _promotion_case(
        _scheduled_bundle(
            session_clock=genuine, source_snapshot_hash=snapshot.snapshot_hash
        )
    )
    with pytest.raises(ValueError, match="cannot consume exploratory reconstructed"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_bundle_hash_mismatch() -> None:
    snapshot = _promotion_snapshot()
    case = _promotion_case(
        _realized_bundle(source_snapshot_hash=snapshot.snapshot_hash)
    )
    case["bundle"] = _realized_bundle(
        source_snapshot_hash=snapshot.snapshot_hash,
        security_identities=(SecurityV1(schema_version="1", security_id=uid(41)),),
    )
    with pytest.raises(ValueError, match="input bundle hash mismatch"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_snapshot_mismatch() -> None:
    snapshot = _promotion_snapshot()
    # The bundle is genuinely bound to its snapshot; the admission's M1e
    # handoff names a different one, which is the mismatch under test.
    case = _promotion_case(
        _realized_bundle(source_snapshot_hash=snapshot.snapshot_hash),
        handoff_snapshot_hash=H["c"],
    )
    with pytest.raises(
        ValueError, match=r"^input bundle snapshot mismatch with promotion admission$"
    ):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_missing_snapshot() -> None:
    snapshot = _promotion_snapshot()
    case = _promotion_case(
        _realized_bundle(source_snapshot_hash=snapshot.snapshot_hash)
    )
    unbound = _realized_bundle()
    assert unbound.source_snapshot_hash is None
    case["bundle"] = unbound
    case["admission"] = rebind_admission(
        case,
        input_bundle_hash=unbound.bundle_hash,
        provenance_proof_hash=case["proof"].proof_hash,
    )
    with pytest.raises(
        ValueError, match=r"^input bundle snapshot mismatch with promotion admission$"
    ):
        validate_promotion_admission(**case)


def test_minting_refuses_a_bundle_that_asserts_no_snapshot() -> None:
    """A bundle with no snapshot can never obtain a proof in the first place."""
    replay_context = _provenance_context()
    snapshot = qualified_snapshot(replay_context)
    qualified = qualify_replay_context(context=replay_context, snapshot=snapshot)
    with pytest.raises(
        ValueError,
        match=r"^bundle source snapshot does not match the qualified replay context",
    ):
        mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=replay_context,
            bundle=_realized_bundle(),
            session_queries=_provenance_session_queries(),
        )


# --- bundle evidence bound to its own session clock ---


def test_bundle_rejects_decision_view_outside_its_session_clock() -> None:
    """Lane leakage: evidence must belong to the clock the bundle declares."""
    _, _, _, decision_view = _decision_case()
    with pytest.raises(
        (ValidationError, ValueError), match="session clock does not contain"
    ):
        _realized_bundle(authentic_decision_views=(decision_view,))


def test_bundle_rejects_accounting_view_outside_its_session_clock() -> None:
    _, _, _, accounting_view = _accounting_case()
    with pytest.raises(
        (ValidationError, ValueError), match="session clock does not contain"
    ):
        _realized_bundle(authentic_accounting_views=(accounting_view,))


def test_bundle_rejects_reconstruction_outside_its_session_clock() -> None:
    observation = build_from_harness(_harness())
    harness = NormalizationHarness(outer_kind="decision")
    with pytest.raises(
        (ValidationError, ValueError), match="session clock does not contain"
    ):
        assemble_evaluation_input_bundle(
            evaluation_interval=_interval(),
            session_clock=normalization_realized_clock(harness),
            exploratory_reconstructed_observations=(observation,),
        )


def test_bundle_accepts_evidence_inside_its_session_clock() -> None:
    harness, _, _, decision_view = _decision_case()
    clock = normalization_realized_clock(harness)
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=clock,
        authentic_decision_views=(decision_view,),
    )
    assert bundle.authentic_decision_views == (decision_view,)
    assert decision_view.source_session in {
        session.session_key for session in clock.sessions
    }


def test_bundle_rejects_clock_opening_before_its_evaluation_interval() -> None:
    late = TemporalIntervalClaimV1(
        schema_version="1", start=exact_boundary("2026-06-01T00:00:00Z"), end=None
    )
    with pytest.raises(
        (ValidationError, ValueError), match="opens before its evaluation interval"
    ):
        assemble_evaluation_input_bundle(
            evaluation_interval=late, session_clock=_realized_clock()
        )


def test_bundle_rejects_clock_closing_after_its_evaluation_interval() -> None:
    early = TemporalIntervalClaimV1(
        schema_version="1",
        start=exact_boundary("2020-01-02T14:30:00Z"),
        end=exact_boundary("2026-01-04T00:00:00Z"),
    )
    with pytest.raises(
        (ValidationError, ValueError), match="closes after its evaluation interval"
    ):
        assemble_evaluation_input_bundle(
            evaluation_interval=early, session_clock=_realized_clock()
        )


def test_bundle_accepts_a_clock_inside_its_evaluation_interval() -> None:
    spanning = TemporalIntervalClaimV1(
        schema_version="1",
        start=exact_boundary("2026-01-01T00:00:00Z"),
        end=exact_boundary("2026-01-31T00:00:00Z"),
    )
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=spanning, session_clock=_realized_clock()
    )
    assert bundle.evaluation_interval == spanning


# --- deterministic run identity ---


def _identity_args(**overrides: Any) -> dict[str, Any]:
    bundle = _scheduled_bundle()
    args: dict[str, Any] = {
        "strategy_hash": H["1"],
        "protocol_hash": H["2"],
        "cost_model_hash": H["3"],
        "admission": _exploratory_admission(bundle),
        "bundle": bundle,
        "evaluator_evidence_hash": H["5"],
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
        "evaluator_evidence_hash",
        "code_version_hash",
        "environment_closure_hash",
    ],
)
def test_run_identity_depends_on_every_input(field: str) -> None:
    base = build_evaluation_run_identity(**_identity_args())
    changed = build_evaluation_run_identity(**_identity_args(**{field: H["e"]}))
    assert base.run_identity_hash != changed.run_identity_hash


def test_run_identity_depends_on_the_admitted_bundle() -> None:
    base = build_evaluation_run_identity(**_identity_args())
    other = _scheduled_bundle(
        security_identities=(SecurityV1(schema_version="1", security_id=uid(51)),)
    )
    changed = build_evaluation_run_identity(
        **_identity_args(admission=_exploratory_admission(other), bundle=other)
    )
    assert base.bundle_hash != changed.bundle_hash
    assert base.admission_hash != changed.admission_hash
    assert base.run_identity_hash != changed.run_identity_hash


def test_run_identity_depends_on_the_admission() -> None:
    bundle = _scheduled_bundle()
    base = build_evaluation_run_identity(**_identity_args(bundle=bundle))
    widened = _exploratory_admission(
        bundle,
        limitations=(*bundle.required_limitations, ALPACA_LIMITATION_BOUNDED_COHORT),
    )
    changed = build_evaluation_run_identity(
        **_identity_args(bundle=bundle, admission=widened)
    )
    assert base.bundle_hash == changed.bundle_hash
    assert base.run_identity_hash != changed.run_identity_hash


def test_run_identity_requires_the_admission_to_admit_this_bundle() -> None:
    """The declared chain input_bundle_hash == bundle_hash is enforced, not assumed."""
    admitted = _scheduled_bundle()
    other = _scheduled_bundle(
        security_identities=(SecurityV1(schema_version="1", security_id=uid(52)),)
    )
    assert admitted.bundle_hash != other.bundle_hash
    with pytest.raises(ValueError, match="admission to admit this exact bundle"):
        build_evaluation_run_identity(
            **_identity_args(admission=_exploratory_admission(admitted), bundle=other)
        )


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
        session_clock=normalization_realized_clock(harness),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    assert bundle.authentic_decision_views == (view,)


def test_verify_accepts_genuinely_replayed_bundle() -> None:
    harness, query, reference, _ = _decision_case()
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_realized_clock(harness),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    verify_evaluation_input_bundle(
        bundle=bundle,
        context=harness.context,
        session_queries=normalization_session_queries(harness),
        decision_requests=((reference, query),),
    )


def test_verify_rejects_view_that_replay_did_not_produce() -> None:
    harness, query, reference, view = _decision_case()
    forged = EvaluationInputBundleV1.model_construct(
        **(
            dict(
                assemble_evaluation_input_bundle(
                    evaluation_interval=_interval(),
                    session_clock=normalization_realized_clock(harness),
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
        session_clock=normalization_realized_clock(harness),
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
            session_queries=normalization_session_queries(harness),
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
    snapshot = _promotion_snapshot()
    poisoned = _realized_bundle(
        source_snapshot_hash=snapshot.snapshot_hash,
        exploratory_reconstructed_observations=(observation,),
    )
    # The only production path to a proof re-derives every reconstruction, and
    # it takes no replay inputs, so it can never cover one (issue 55).
    with pytest.raises(
        ValueError,
        match=r"^bundle carries exploratory reconstructions without the replay",
    ):
        _promotion_case(poisoned)

    # A proof assembled directly still meets the gate's own refusal.
    case = _promotion_case(
        _realized_bundle(source_snapshot_hash=snapshot.snapshot_hash)
    )
    proof = _build_bundle_provenance_proof(
        qualified_context_hash=case["proof"].qualified_context_hash,
        source_snapshot_hash=snapshot.snapshot_hash,
        bundle=poisoned,
    )
    case["bundle"] = poisoned
    case["proof"] = proof
    case["admission"] = rebind_admission(
        case,
        input_bundle_hash=poisoned.bundle_hash,
        provenance_proof_hash=proof.proof_hash,
    )
    with pytest.raises(ValueError, match="cannot consume exploratory reconstructed"):
        validate_promotion_admission(**case)


# --- promotion evidence sufficiency ---


def test_promotion_gate_rejects_vacuous_bundle() -> None:
    snapshot = _promotion_snapshot()
    case = _promotion_case(
        _realized_bundle(source_snapshot_hash=snapshot.snapshot_hash)
    )
    with pytest.raises(ValueError, match="at least one authentic decision view"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_clock_declaring_exploratory_limitations() -> None:
    normalization, query, reference, decision_view = _decision_case()
    snapshot = _promotion_snapshot(normalization.context)
    # The clock spans both corpora so the bundle is internally coherent, and it
    # is the promotion gate, not bundle validation, that rejects this case. The
    # bundle carries no reconstruction, so the limitation gate is the only gate
    # that can fire and the anchored message below names it exactly.
    base = _merged_realized_clock(normalization)
    draft = SessionClockV1.model_construct(
        **(dict(base) | {"acknowledged_limitations": (ALPACA_LIMITATION_ABSENT_HALTS,)})
    )
    limited = SessionClockV1.model_validate(
        dict(draft) | {"clock_hash": session_clock_hash(draft)}
    )
    bundle = _realized_bundle(
        session_clock=limited,
        source_snapshot_hash=snapshot.snapshot_hash,
        authentic_decision_views=(decision_view,),
    )
    assert bundle.has_exploratory_reconstructions is False
    assert bundle.required_limitations == (ALPACA_LIMITATION_ABSENT_HALTS,)
    # No canonical builder emits a realized clock declaring limitations, so
    # minting, which re-derives the clock (issue 80), refuses it first.
    with pytest.raises(
        ValueError,
        match=r"^session clock does not match its canonical re-derivation",
    ):
        _promotion_case(
            bundle,
            context=normalization.context,
            session_queries=normalization_session_queries(normalization),
            decision_requests=((reference, query),),
        )

    # A proof assembled directly still meets the gate's own refusal.
    case = _promotion_case(
        _realized_bundle(
            session_clock=normalization_realized_clock(normalization),
            source_snapshot_hash=snapshot.snapshot_hash,
            authentic_decision_views=(decision_view,),
        ),
        context=normalization.context,
        session_queries=normalization_session_queries(normalization),
        decision_requests=((reference, query),),
    )
    proof = _build_bundle_provenance_proof(
        qualified_context_hash=case["proof"].qualified_context_hash,
        source_snapshot_hash=snapshot.snapshot_hash,
        bundle=bundle,
    )
    case["bundle"] = bundle
    case["proof"] = proof
    case["admission"] = rebind_admission(
        case,
        input_bundle_hash=bundle.bundle_hash,
        provenance_proof_hash=proof.proof_hash,
    )
    with pytest.raises(
        ValueError,
        match=(
            r"^promotion evaluation cannot consume evidence declaring limitations: "
            rf"\('{ALPACA_LIMITATION_ABSENT_HALTS}',\)$"
        ),
    ):
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
        session_clock=normalization_realized_clock(harness),
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
        session_clock=normalization_realized_clock(harness),
        context=harness.context,
        accounting_requests=((reference, query),),
    )
    assert bundle.authentic_accounting_views == (view,)
    verify_evaluation_input_bundle(
        bundle=bundle,
        context=harness.context,
        session_queries=normalization_session_queries(harness),
        accounting_requests=((reference, query),),
    )


# --- the bundle clock is re-derived, never trusted (issue 80) ---


def test_verify_refuses_a_realized_clock_without_its_session_queries() -> None:
    """Realized authority is re-derived or refused, never taken on trust."""
    harness, query, reference, _ = _decision_case()
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_realized_clock(harness),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    with pytest.raises(
        ValueError,
        match=(
            r"^bundle carries a realized session clock without the session "
            r"queries to re-derive it$"
        ),
    ):
        verify_evaluation_input_bundle(
            bundle=bundle,
            context=harness.context,
            decision_requests=((reference, query),),
        )


@pytest.mark.parametrize(
    "edit",
    ["later_close", "invented_records", "invented_proofs"],
)
def test_verify_refuses_a_realized_clock_edited_after_its_build(edit: str) -> None:
    """Each session field is bound, not only the authority hashes."""
    harness, query, reference, view = _decision_case()
    genuine = normalization_realized_clock(harness)
    session = genuine.sessions[0]
    updates: dict[str, Any] = {
        "later_close": {"closed_at": session.closed_at + timedelta(hours=3)},
        "invented_records": {"authority_record_hashes": (H["e"],)},
        "invented_proofs": {"authority_proof_hashes": (H["f"],)},
    }[edit]
    forged = resealed_clock(genuine, **updates)
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=forged,
        authentic_decision_views=(view,),
    )
    with pytest.raises(
        ValueError,
        match=(
            r"^session clock does not match its canonical re-derivation: bundle "
            rf"clock {forged.clock_hash}, re-derived {genuine.clock_hash}$"
        ),
    ):
        verify_evaluation_input_bundle(
            bundle=bundle,
            context=harness.context,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )


def test_verify_refuses_a_scheduled_row_relabelled_as_realized() -> None:
    """The mode is re-derived too: a calendar row is not realized authority."""
    harness, query, reference, view = _decision_case()
    relabelled = resealed_clock(
        normalization_scheduled_clock(harness),
        mode="realized_session_authority",
        acknowledged_limitations=(),
        authority="realized",
    )
    genuine = normalization_realized_clock(harness)
    assert relabelled.sessions[0].session_key == genuine.sessions[0].session_key
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=relabelled,
        authentic_decision_views=(view,),
    )
    with pytest.raises(
        ValueError,
        match=(
            r"^session clock does not match its canonical re-derivation: bundle "
            rf"clock {relabelled.clock_hash}, re-derived {genuine.clock_hash}$"
        ),
    ):
        verify_evaluation_input_bundle(
            bundle=bundle,
            context=harness.context,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )


def test_verify_re_derives_a_scheduled_clock_when_its_queries_are_supplied() -> None:
    harness, query, reference, view = _decision_case()
    genuine = normalization_scheduled_clock(harness)
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=genuine,
        context=harness.context,
        decision_requests=((reference, query),),
    )
    verify_evaluation_input_bundle(
        bundle=bundle,
        context=harness.context,
        session_queries=normalization_session_queries(harness),
        decision_requests=((reference, query),),
    )

    session = genuine.sessions[0]
    moved = resealed_clock(genuine, closed_at=session.closed_at + timedelta(hours=3))
    forged = assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=moved,
        authentic_decision_views=(view,),
    )
    with pytest.raises(
        ValueError,
        match=(
            r"^session clock does not match its canonical re-derivation: bundle "
            rf"clock {moved.clock_hash}, re-derived {genuine.clock_hash}$"
        ),
    ):
        verify_evaluation_input_bundle(
            bundle=forged,
            context=harness.context,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )


def test_verify_does_not_re_derive_an_unqueried_scheduled_clock() -> None:
    """A known gap, pinned so it cannot widen, or close, silently.

    Without its session queries a scheduled-reconstruction clock is not
    re-derived by verification, so its session times are only as trusted as
    the caller that built it. That is not safe merely because the clock is
    exploratory; it is left open because requiring those queries overlaps the
    scheduled-lane clock work of issue 84, and the promotion gate refuses the
    mode regardless. Minting always supplies the queries, and every other
    present caller of this verifier is a test; the Alpaca bridge itself never
    calls it. A realized clock gets no such allowance.
    """
    harness, query, reference, _ = _decision_case()
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_scheduled_clock(harness),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    assert bundle.has_exploratory_reconstructions is True
    verify_evaluation_input_bundle(
        bundle=bundle,
        context=harness.context,
        decision_requests=((reference, query),),
    )
