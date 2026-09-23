"""Admission-to-bundle lane gates and deterministic evaluation run identity."""

from drift.domain.assertions import NormalizedSelectionQueryV1, TemporalIntervalClaimV1
from drift.domain.common import UUID7, SHA256Hash
from drift.domain.economic_queries import MarketSelectionQueryV1
from drift.domain.economic_results import EconomicOutcomeResolutionV1
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    EvaluationRunIdentityV1,
    evaluation_input_bundle_hash,
    evaluation_run_identity_hash,
)
from drift.domain.evaluator_clock import SessionClockV1
from drift.domain.evaluator_lanes import (
    EvaluationAdmissionV1,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryCohortAuthorizationV1,
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    NormalizationQueryV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
)
from drift.domain.observation_query import ObservationQueryV1
from drift.domain.qualification import (
    ConsumerPurpose,
    M1eCompletionRecordV1,
    PilotProfileSetV1,
    PurposeQualificationReportV1,
    QualificationProfileV1,
    qualification_profile_hash,
)
from drift.domain.qualification_adapters import QualifiedSourceHandoffV1
from drift.domain.replay_provenance import (
    BundleProvenanceProofV1,
    QualifiedReplayContextV1,
    ReplayContextIdentityV1,
    _build_bundle_provenance_proof,
    bind_context_identity_to_snapshot,
    bundle_provenance_proof_hash,
    replay_context_identity_hash,
    validate_bundle_component_coverage,
    verify_snapshot_binding,
    verify_snapshot_binding_purpose,
)
from drift.domain.securities import ListingV1, SecurityV1
from drift.domain.source_snapshots import RealSourceSnapshotV1
from drift.domain.universes import StructuralEligibilityResultV1
from drift.evaluator.admission import validate_m1e_promotion_evidence
from drift.evaluator.clock import verify_session_clock
from drift.evaluator.reconstruction import (
    ExploratoryReconstructionReplay,
    replay_exploratory_reconstructions,
    require_scheduled_calendar_row,
    verify_exploratory_reconstructions,
)
from drift.markets.economic_outcomes import resolve_economic_facts
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_descriptor,
    m1d_context_hash,
)
from drift.markets.universes import resolve_structural_eligibility
from drift.serialization.canonical import content_hash

type DecisionReplayRequests = tuple[
    tuple[ObservationDecisionReferenceV1, NormalizationQueryV1], ...
]
type OutcomeReplayRequests = tuple[
    tuple[ObservationOutcomeReferenceV1, NormalizationQueryV1], ...
]
type SessionReplayQueries = tuple[ObservationQueryV1, ...]
"""The session queries a bundle clock is built from, in either mode."""
type StructuralReplayRequests = tuple[
    tuple[ListingV1, UUID7, NormalizedSelectionQueryV1], ...
]
"""One `(listing, security_id, query)` per structural eligibility.

The research definition, issuer, methodology and M1b evidence come from the
replay context, where its identity binds them, exactly as M1d resolves an
observation's own structural admission; only the per-listing subject and the
query are requested.
"""
type EconomicReplayRequests = tuple[MarketSelectionQueryV1, ...]
"""One M1c query per economic outcome, resolved over the context's M1c evidence."""


def _ordered[T](members: tuple[T, ...]) -> tuple[T, ...]:
    """Order bundle members by exact content hash."""
    paired = tuple((content_hash(member), member) for member in members)
    return tuple(member for _, member in sorted(paired, key=lambda pair: pair[0]))


def assemble_evaluation_input_bundle(
    *,
    evaluation_interval: TemporalIntervalClaimV1,
    session_clock: SessionClockV1,
    security_identities: tuple[SecurityV1, ...] = (),
    listing_identities: tuple[ListingV1, ...] = (),
    structural_eligibilities: tuple[StructuralEligibilityResultV1, ...] = (),
    economic_outcomes: tuple[EconomicOutcomeResolutionV1, ...] = (),
    authentic_decision_views: tuple[DerivedObservationViewV1, ...] = (),
    authentic_accounting_views: tuple[DerivedObservationViewV1, ...] = (),
    exploratory_reconstructed_observations: tuple[
        ExploratoryReconstructedSessionObservationV1, ...
    ] = (),
    source_snapshot_hash: SHA256Hash | None = None,
) -> EvaluationInputBundleV1:
    """Assemble a bundle with canonical member ordering and an exact bundle hash.

    This performs no replay verification. It trusts the caller to supply views
    that were genuinely materialized. Use build_evaluation_input_bundle for the
    spec preparation boundary, or verify_evaluation_input_bundle to check an
    already-assembled bundle against exact upstream replay.
    """
    draft = EvaluationInputBundleV1.model_construct(
        schema_version="1",
        evaluation_interval=evaluation_interval,
        source_snapshot_hash=source_snapshot_hash,
        session_clock=session_clock,
        security_identities=_ordered(security_identities),
        listing_identities=_ordered(listing_identities),
        structural_eligibilities=_ordered(structural_eligibilities),
        economic_outcomes=_ordered(economic_outcomes),
        authentic_decision_views=_ordered(authentic_decision_views),
        authentic_accounting_views=_ordered(authentic_accounting_views),
        exploratory_reconstructed_observations=_ordered(
            exploratory_reconstructed_observations
        ),
        bundle_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"bundle_hash": evaluation_input_bundle_hash(draft)}
    )
    return EvaluationInputBundleV1.model_validate(candidate.model_dump())


def replay_decision_views(
    requests: DecisionReplayRequests, context: M1dResolutionContext
) -> tuple[DerivedObservationViewV1, ...]:
    """Materialize decision-role views through full dependent M1d replay."""
    return tuple(
        materialize_observation_decision(reference, query, context)
        for reference, query in requests
    )


def replay_accounting_views(
    requests: OutcomeReplayRequests, context: M1dResolutionContext
) -> tuple[DerivedObservationViewV1, ...]:
    """Materialize outcome-role accounting views through full dependent replay."""
    return tuple(
        materialize_observation_outcome(reference, query, context)
        for reference, query in requests
    )


def replay_structural_eligibilities(
    requests: StructuralReplayRequests, context: M1dResolutionContext
) -> tuple[StructuralEligibilityResultV1, ...]:
    """Resolve each structural eligibility over the context's own M1b evidence.

    Uses the one canonical M1b resolver with the research definition, issuer,
    methodology and structural context the replay context carries, so no
    requested input can substitute evidence the context identity does not bind.
    """
    if not requests:
        return ()
    structural = context.structural_context
    definition = context.research_definition
    issuer_id = context.issuer_id
    methodology_id = context.structural_methodology_id
    if (
        structural is None
        or definition is None
        or issuer_id is None
        or methodology_id is None
    ):
        raise ValueError(
            "structural eligibility replay requires the replay context's M1b evidence"
        )
    return tuple(
        resolve_structural_eligibility(
            definition,
            listing,
            issuer_id,
            security_id,
            methodology_id,
            query,
            structural,
        )
        for listing, security_id, query in requests
    )


def replay_economic_outcomes(
    requests: EconomicReplayRequests, context: M1dResolutionContext
) -> tuple[EconomicOutcomeResolutionV1, ...]:
    """Resolve each economic outcome over the context's own M1c evidence."""
    if not requests:
        return ()
    economic = context.economic_context
    source_policy = context.economic_source_policy
    if economic is None or source_policy is None:
        raise ValueError(
            "economic outcome replay requires the replay context's M1c evidence"
        )
    return tuple(
        resolve_economic_facts(query, economic, source_policy) for query in requests
    )


def build_evaluation_input_bundle(
    *,
    evaluation_interval: TemporalIntervalClaimV1,
    session_clock: SessionClockV1,
    context: M1dResolutionContext,
    decision_requests: DecisionReplayRequests = (),
    accounting_requests: OutcomeReplayRequests = (),
    security_identities: tuple[SecurityV1, ...] = (),
    listing_identities: tuple[ListingV1, ...] = (),
    structural_eligibilities: tuple[StructuralEligibilityResultV1, ...] = (),
    economic_outcomes: tuple[EconomicOutcomeResolutionV1, ...] = (),
    exploratory_cohort: ExploratoryCohortAuthorizationV1 | None = None,
    exploratory_reconstruction_replay: ExploratoryReconstructionReplay | None = None,
    source_snapshot_hash: SHA256Hash | None = None,
) -> EvaluationInputBundleV1:
    """Prepare a bundle whose views come from exact upstream Drift replay.

    This is the spec preparation boundary. Views are never accepted from the
    caller; they are materialized here, so a view that no genuine replay
    produces cannot enter a bundle built through this path. Exploratory
    reconstructions are likewise derived here, through the one canonical
    builder, from their declared cohort and replay inputs (issue 55).
    """
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=evaluation_interval,
        session_clock=session_clock,
        security_identities=security_identities,
        listing_identities=listing_identities,
        structural_eligibilities=structural_eligibilities,
        economic_outcomes=economic_outcomes,
        authentic_decision_views=replay_decision_views(decision_requests, context),
        authentic_accounting_views=replay_accounting_views(
            accounting_requests, context
        ),
        exploratory_reconstructed_observations=_replayed_reconstructions(
            exploratory_cohort, exploratory_reconstruction_replay, context
        ),
        source_snapshot_hash=source_snapshot_hash,
    )
    _require_calendar_rows(bundle)
    return bundle


def _replayed_reconstructions(
    cohort: ExploratoryCohortAuthorizationV1 | None,
    replay: ExploratoryReconstructionReplay | None,
    context: M1dResolutionContext,
) -> tuple[ExploratoryReconstructedSessionObservationV1, ...]:
    """Derive reconstructions only from a complete cohort and replay pair."""
    if cohort is None and replay is None:
        return ()
    if cohort is None or replay is None:
        raise ValueError(
            "exploratory reconstruction replay requires both its declared cohort "
            "and its replay inputs"
        )
    _require_replay_context(replay, context)
    return replay_exploratory_reconstructions(replay, cohort)


def _require_replay_context(
    replay: ExploratoryReconstructionReplay, context: M1dResolutionContext
) -> None:
    """Refuse replay requests resolving against any context but the bundle's.

    Authentic views are replayed against the one context the caller presents
    here. Reconstructions must be too, or whoever supplies a reconstruction
    would also supply the source it is checked against. Each builder call
    already refuses a query whose context hash does not match its own
    context, so binding every query to this context binds the request too.
    """
    expected = m1d_context_hash(context)
    foreign = tuple(
        sorted({query.input_context_hash for query, _ in replay.requests} - {expected})
    )
    if foreign:
        raise ValueError(
            "exploratory reconstruction replay resolves against another M1d "
            f"context than {expected}: {foreign}"
        )


def _require_calendar_rows(bundle: EvaluationInputBundleV1) -> None:
    """Bind every reconstruction to the calendar row of a scheduled clock.

    A realized clock does not time decisions on reconstructions, so riding
    reconstructions there have no scheduled row to bind.
    """
    if bundle.session_clock.mode != "scheduled_session_reconstruction":
        return
    sessions = {
        session.session_key: session for session in bundle.session_clock.sessions
    }
    for observation in bundle.exploratory_reconstructed_observations:
        require_scheduled_calendar_row(observation, sessions[observation.session_key])


def verify_evaluation_input_bundle(
    *,
    bundle: EvaluationInputBundleV1,
    context: M1dResolutionContext,
    session_queries: SessionReplayQueries | None = None,
    decision_requests: DecisionReplayRequests = (),
    accounting_requests: OutcomeReplayRequests = (),
    structural_requests: StructuralReplayRequests = (),
    economic_requests: EconomicReplayRequests = (),
    exploratory_cohort: ExploratoryCohortAuthorizationV1 | None = None,
    exploratory_reconstruction_replay: ExploratoryReconstructionReplay | None = None,
) -> None:
    """Verify every stored member against exact upstream replay.

    Re-materializes the declared views and requires exact equality with what
    the bundle carries. A forged, hand-constructed, or exploratory-derived view
    cannot survive this check, so it is what makes a bundle's contents trusted
    rather than merely self-declared. Exploratory reconstructions are
    re-derived the same way; a bundle carrying any without the inputs to
    re-derive them is refused.

    Structural eligibilities and economic outcomes are re-derived the same way
    from their requests over the context's M1b and M1c evidence, and the clock
    from its session queries under its own mode (issue 80). A bundle carrying
    any of them without the request that re-derives it is refused. A realized
    clock is never taken on trust: without its session queries it is refused.
    A scheduled-reconstruction clock is re-derived whenever its queries are
    supplied; without them it is not re-derived here, because it is exploratory
    by construction and the promotion gate refuses its mode outright.
    """
    _require_replayed(
        "decision view",
        "decision views",
        replay_decision_views(decision_requests, context),
        bundle.authentic_decision_views,
    )
    _require_replayed(
        "accounting view",
        "accounting views",
        replay_accounting_views(accounting_requests, context),
        bundle.authentic_accounting_views,
    )
    _require_replayed(
        "structural eligibility",
        "structural eligibilities",
        replay_structural_eligibilities(structural_requests, context),
        bundle.structural_eligibilities,
    )
    _require_replayed(
        "economic outcome",
        "economic outcomes",
        replay_economic_outcomes(economic_requests, context),
        bundle.economic_outcomes,
    )

    if exploratory_cohort is None and exploratory_reconstruction_replay is None:
        if bundle.exploratory_reconstructed_observations:
            raise ValueError(
                "bundle carries exploratory reconstructions without the replay "
                "inputs to re-derive them"
            )
    elif exploratory_cohort is None or exploratory_reconstruction_replay is None:
        raise ValueError(
            "exploratory reconstruction replay requires both its declared cohort "
            "and its replay inputs"
        )
    else:
        _require_replay_context(exploratory_reconstruction_replay, context)
        verify_exploratory_reconstructions(
            bundle.exploratory_reconstructed_observations,
            replay=exploratory_reconstruction_replay,
            cohort=exploratory_cohort,
        )
        _require_calendar_rows(bundle)

    if session_queries is not None:
        verify_session_clock(bundle.session_clock, session_queries, context)
    elif bundle.session_clock.mode == "realized_session_authority":
        raise ValueError(
            "bundle carries a realized session clock without the session queries "
            "to re-derive it"
        )

    rebuilt = evaluation_input_bundle_hash(bundle)
    if rebuilt != bundle.bundle_hash:
        raise ValueError("bundle hash does not match its own contents")


def _require_replayed[T](
    singular: str,
    plural: str,
    expected: tuple[T, ...],
    stored: tuple[T, ...],
) -> None:
    """Require the stored members to equal their replay as an exact multiset."""
    if len(expected) != len(stored):
        raise ValueError(
            f"{singular} count mismatch against replay: "
            f"expected {len(expected)}, bundle carries {len(stored)}"
        )
    # Both sides are canonically ordered by content hash, so compare digests.
    expected_digests = sorted(content_hash(member) for member in expected)
    stored_digests = sorted(content_hash(member) for member in stored)
    if expected_digests != stored_digests:
        raise ValueError(f"{plural} do not match exact upstream replay")


def _request_hash(reference: object, query: object) -> SHA256Hash:
    """Exact identity of one replay request as a reference/query pair."""
    return content_hash({"reference": reference, "query": query})


def _query_request_hash(query: object) -> SHA256Hash:
    """Exact identity of one replay request that is a query alone."""
    return content_hash({"query": query})


def _structural_request_hash(
    listing: ListingV1, security_id: UUID7, query: NormalizedSelectionQueryV1
) -> SHA256Hash:
    """Exact identity of one structural eligibility replay request."""
    return content_hash(
        {"listing": listing, "security_id": security_id, "query": query}
    )


def _require_bound_identities(
    bundle: EvaluationInputBundleV1, context: M1dResolutionContext
) -> None:
    """Bind every security and listing identity to the context's M1b evidence.

    `SecurityV1` and `ListingV1` are opaque identities that no builder derives,
    so they are bound rather than re-derived: each must equal an identity that
    the context's validated M1b identity assignments carry, which the replay
    context identity, and so the snapshot witness, attests. A listing's venue is
    part of its identity, so a listing id on another venue is not bound.
    """
    members: tuple[SecurityV1 | ListingV1, ...] = (
        *bundle.security_identities,
        *bundle.listing_identities,
    )
    if not members:
        return
    structural = context.structural_context
    if structural is None:
        raise ValueError(
            "bundle carries security or listing identities, but the replay "
            "context supplies no M1b identity evidence to bind them"
        )
    attested = {
        content_hash(record.identity)
        for record in structural.universe.assignments.records
    }
    unbound = tuple(
        sorted(
            digest
            for digest in (content_hash(member) for member in members)
            if digest not in attested
        )
    )
    if unbound:
        raise ValueError(
            "bundle identities are not attested by the replay context's M1b "
            f"identity assignments: {unbound}"
        )


def derive_replay_context_identity(
    context: M1dResolutionContext,
) -> ReplayContextIdentityV1:
    """Derive the deterministic identity of an M1d resolution context.

    `M1dResolutionContext` is deliberately not modified. Identity is a pure
    function of it, taken from the same canonical descriptor that already backs
    `m1d_context_hash`, so this contract stays additive across every existing
    construction site.
    """
    descriptor = m1d_context_descriptor(context)
    observation_entries = descriptor["observation_datasets"]
    session_entries = descriptor["session_datasets"]
    assert isinstance(observation_entries, tuple)
    assert isinstance(session_entries, tuple)

    m1b = descriptor.get("m1b")
    m1c = descriptor.get("m1c")

    draft = ReplayContextIdentityV1.model_construct(
        schema_version="1",
        observation_dataset_hashes=tuple(
            sorted({content_hash(entry) for entry in observation_entries})
        ),
        session_dataset_hashes=tuple(
            sorted({content_hash(entry) for entry in session_entries})
        ),
        availability_policy_hashes=tuple(
            sorted(
                {
                    content_hash(value)
                    for value in context.availability_policies.values()
                }
            )
        ),
        retained_evidence_hashes=tuple(
            sorted(
                {content_hash(value) for value in context.retained_evidence.values()}
            )
        ),
        supporting_artifact_hashes=tuple(sorted(set(context.supporting_artifacts))),
        m1b_context_hash=content_hash(m1b) if m1b is not None else None,
        m1c_context_hash=content_hash(m1c) if m1c is not None else None,
        schedule_generation_policy_hash=context.schedule_generation_policy_hash,
        identity_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"identity_hash": replay_context_identity_hash(draft)}
    )
    return ReplayContextIdentityV1.model_validate(candidate.model_dump())


def qualify_replay_context(
    *,
    context: M1dResolutionContext,
    snapshot: RealSourceSnapshotV1,
) -> QualifiedReplayContextV1:
    """Bind a resolution context to a qualified snapshot by total containment.

    A context whose artifacts are not all attested by the snapshot cannot be
    qualified, which is exactly the adversarial case that previously passed.
    """
    return bind_context_identity_to_snapshot(
        identity=derive_replay_context_identity(context),
        snapshot=snapshot,
    )


def mint_bundle_provenance_proof(
    *,
    qualified_context: QualifiedReplayContextV1,
    context: M1dResolutionContext,
    bundle: EvaluationInputBundleV1,
    session_queries: SessionReplayQueries,
    decision_requests: DecisionReplayRequests = (),
    accounting_requests: OutcomeReplayRequests = (),
    structural_requests: StructuralReplayRequests = (),
    economic_requests: EconomicReplayRequests = (),
) -> BundleProvenanceProofV1:
    """Run replay verification once and mint the proof the gate validates.

    This is the only production path to a `BundleProvenanceProofV1`. It refuses
    to mint unless the replay context presented here is the very context the
    qualified snapshot binding was proven over, and unless the bundle asserts
    that same snapshot.

    Coverage is every authority-bearing input the issue 31 Decision 4 ruling
    names (issue 80): views, structural eligibility, and economic outcomes are
    re-derived from their requests, the clock from its session queries, which
    have no default, and security and listing identity is bound to the
    context's M1b evidence. The proof records every request hash.
    """
    identity = derive_replay_context_identity(context)
    if identity.identity_hash != qualified_context.context_identity.identity_hash:
        raise ValueError(
            "replay context identity does not match the qualified replay context: "
            f"replayed {identity.identity_hash}, qualified "
            f"{qualified_context.context_identity.identity_hash}"
        )
    if bundle.source_snapshot_hash != qualified_context.source_snapshot_hash:
        raise ValueError(
            "bundle source snapshot does not match the qualified replay context: "
            f"bundle {bundle.source_snapshot_hash}, qualified "
            f"{qualified_context.source_snapshot_hash}"
        )

    verify_evaluation_input_bundle(
        bundle=bundle,
        context=context,
        session_queries=session_queries,
        decision_requests=decision_requests,
        accounting_requests=accounting_requests,
        structural_requests=structural_requests,
        economic_requests=economic_requests,
    )
    _require_bound_identities(bundle, context)

    return _build_bundle_provenance_proof(
        qualified_context_hash=qualified_context.qualified_hash,
        source_snapshot_hash=qualified_context.source_snapshot_hash,
        bundle=bundle,
        decision_request_hashes=tuple(
            _request_hash(reference, query) for reference, query in decision_requests
        ),
        accounting_request_hashes=tuple(
            _request_hash(reference, query) for reference, query in accounting_requests
        ),
        session_request_hashes=tuple(
            _query_request_hash(query) for query in session_queries
        ),
        structural_request_hashes=tuple(
            _structural_request_hash(listing, security_id, query)
            for listing, security_id, query in structural_requests
        ),
        economic_request_hashes=tuple(
            _query_request_hash(query) for query in economic_requests
        ),
    )


def validate_exploratory_admission(
    *,
    admission: ExploratoryEvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
) -> None:
    """Validate an exploratory admission against its input bundle.

    Binds the admission to the exact bundle, refuses any promotion snapshot
    binding on exploratory evidence, and requires the admission to acknowledge
    every limitation the bundle's own evidence carries.
    """
    if admission.lane != "exploratory":
        raise ValueError("admission lane must be exploratory")

    if bundle.bundle_hash != admission.input_bundle_hash:
        raise ValueError("input bundle hash mismatch with admission")

    # An exploratory bundle must not wear promotion snapshot identity. Allowing
    # it would let a later reader infer snapshot-backed provenance for evidence
    # that never passed M1e qualification.
    if bundle.source_snapshot_hash is not None:
        raise ValueError(
            "exploratory evaluation cannot bind a promotion source snapshot"
        )

    acknowledged = set(admission.acknowledged_limitations)
    missing = tuple(
        limitation
        for limitation in bundle.required_limitations
        if limitation not in acknowledged
    )
    if missing:
        raise ValueError(
            f"exploratory admission omits required bundle limitations: {missing}"
        )


def _require_snapshot_purposes(
    *,
    admission: PromotionEvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    decision_profile: QualificationProfileV1,
    audit_profile: QualificationProfileV1,
    qualified_context: QualifiedReplayContextV1,
    snapshot: RealSourceSnapshotV1,
) -> None:
    """Bind the snapshot to the admission's M1e profiles and purposes.

    Containment alone matched entries by content hash, so decision evidence
    attested only as retrospective-audit input, under a profile of no bound
    profile set, was admitted (issue 80). The snapshot must belong to the
    admission's profile set and authorize both of its profiles, and every
    witnessed entry must attest its artifact for the purpose each view class
    the bundle carries requires, under that purpose's own profile.

    One qualified context holds one witness entry per artifact, and one M1d
    context backs both view classes, so a bundle carrying both decision and
    accounting views cannot satisfy both purposes and fails closed here.
    """
    if snapshot.profile_set_hash != admission.m1e_profile_set_hash:
        raise ValueError(
            "source snapshot profile set mismatch with admission: snapshot binds "
            f"{snapshot.profile_set_hash}, admission binds "
            f"{admission.m1e_profile_set_hash}"
        )
    decision_profile_hash = qualification_profile_hash(decision_profile)
    audit_profile_hash = qualification_profile_hash(audit_profile)
    authorized = set(snapshot.authorized_profile_hashes)
    for role, profile_hash in (
        ("decision", decision_profile_hash),
        ("audit", audit_profile_hash),
    ):
        if profile_hash not in authorized:
            raise ValueError(
                f"source snapshot does not authorize the {role} profile {profile_hash}"
            )
    if bundle.authentic_decision_views:
        verify_snapshot_binding_purpose(
            qualified=qualified_context,
            snapshot=snapshot,
            purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
            profile_hash=decision_profile_hash,
            consumer="decision views",
        )
    if bundle.authentic_accounting_views:
        verify_snapshot_binding_purpose(
            qualified=qualified_context,
            snapshot=snapshot,
            purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
            profile_hash=audit_profile_hash,
            consumer="accounting views",
        )


def validate_promotion_admission(
    *,
    admission: PromotionEvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    profile_set: PilotProfileSetV1,
    completion: M1eCompletionRecordV1,
    decision_profile: QualificationProfileV1,
    audit_profile: QualificationProfileV1,
    decision_report: PurposeQualificationReportV1,
    audit_report: PurposeQualificationReportV1,
    decision_handoff: QualifiedSourceHandoffV1,
    audit_handoff: QualifiedSourceHandoffV1,
    proof: BundleProvenanceProofV1,
    qualified_context: QualifiedReplayContextV1,
    snapshot: RealSourceSnapshotV1,
) -> None:
    """Validate a promotion admission against M1e evidence and its input bundle.

    Composes the Task 1 M1e evidence gate with structural anti-laundering
    verification of the bundle itself and with the provenance chain that binds
    the bundle's contents to a qualified snapshot.

    The proof, the qualified replay context, and the snapshot are all required.
    The unsafe signature that accepted a bundle carrying only a self-declared
    `source_snapshot_hash` is deliberately not preserved for compatibility, and
    neither is the intermediate signature that took a proof but had no channel
    through which the containment witness could be re-audited: the issue 31
    ruling forbids keeping an unsafe signature. A proof alone proved only that
    some qualified context existed, never that its witness was real, because
    `QualifiedReplayContextV1` cannot check its own witness without a snapshot.

    No full M1d replay runs here. Replay verification already ran once at mint
    time, and re-auditing the witness is only `content_hash` recomputation and
    dictionary lookups over `snapshot.replay_inputs`, so this gate stays cheap.
    The same holds for the snapshot's own hash and for its profile set, profile
    authorization, and per-entry purpose bindings (issue 80).
    """
    validate_m1e_promotion_evidence(
        admission=admission,
        profile_set=profile_set,
        completion=completion,
        decision_profile=decision_profile,
        audit_profile=audit_profile,
        decision_report=decision_report,
        audit_report=audit_report,
        decision_handoff=decision_handoff,
        audit_handoff=audit_handoff,
    )

    if bundle.bundle_hash != admission.input_bundle_hash:
        raise ValueError("input bundle hash mismatch with admission")
    if bundle.source_snapshot_hash != decision_handoff.snapshot_hash:
        raise ValueError("input bundle snapshot mismatch with promotion admission")

    # Provenance chain, validated cheaply and fail-closed. A bundle that merely
    # asserts a qualified snapshot hash cannot satisfy this: only a proof minted
    # from a verified qualified replay context can.
    recomputed_proof_hash = bundle_provenance_proof_hash(proof)
    if proof.proof_hash != recomputed_proof_hash:
        raise ValueError(
            "inconsistent provenance proof hash: recomputed "
            f"{recomputed_proof_hash}, declared {proof.proof_hash}"
        )
    if proof.bundle_hash != bundle.bundle_hash:
        raise ValueError(
            "provenance proof bundle hash mismatch: proof binds "
            f"{proof.bundle_hash}, bundle is {bundle.bundle_hash}"
        )
    if proof.source_snapshot_hash != bundle.source_snapshot_hash:
        raise ValueError(
            "provenance proof snapshot mismatch: proof binds "
            f"{proof.source_snapshot_hash}, bundle asserts "
            f"{bundle.source_snapshot_hash}"
        )

    # The proof names a qualified replay context by hash. Without the context
    # itself the gate would trust that name, so require the object and bind it.
    if proof.qualified_context_hash != qualified_context.qualified_hash:
        raise ValueError(
            "provenance proof qualified context mismatch: proof binds "
            f"{proof.qualified_context_hash}, context is "
            f"{qualified_context.qualified_hash}"
        )
    if qualified_context.source_snapshot_hash != bundle.source_snapshot_hash:
        raise ValueError(
            "qualified replay context snapshot mismatch with bundle: context "
            f"binds {qualified_context.source_snapshot_hash}, bundle asserts "
            f"{bundle.source_snapshot_hash}"
        )
    # A qualified context validates its own witness only for coverage of the
    # context, because proving containment needs the snapshot and the model
    # never sees one. Re-audit it here against the snapshot in hand, which is
    # the check that refuses a hand-built witness naming a foreign corpus.
    verify_snapshot_binding(qualified=qualified_context, snapshot=snapshot)
    _require_snapshot_purposes(
        admission=admission,
        bundle=bundle,
        decision_profile=decision_profile,
        audit_profile=audit_profile,
        qualified_context=qualified_context,
        snapshot=snapshot,
    )

    validate_bundle_component_coverage(proof=proof, bundle=bundle)
    if admission.provenance_proof_hash != proof.proof_hash:
        raise ValueError(
            "admission is not bound to the provenance proof: admission carries "
            f"{admission.provenance_proof_hash}, proof is {proof.proof_hash}"
        )

    if bundle.has_exploratory_reconstructions:
        raise ValueError(
            "promotion evaluation cannot consume exploratory reconstructed inputs"
        )
    if bundle.session_clock.mode != "realized_session_authority":
        raise ValueError(
            "promotion evaluation requires authentic realized session authority"
        )
    if any(
        session.authority != "realized" for session in bundle.session_clock.sessions
    ):
        raise ValueError(
            "promotion evaluation requires realized session evidence for every session"
        )

    # A promotion bundle has passed the M1e hard gates by definition. Evidence
    # that still declares development-grade limitations contradicts that claim,
    # so fail closed rather than admitting a self-contradicting bundle.
    if bundle.required_limitations:
        raise ValueError(
            "promotion evaluation cannot consume evidence declaring limitations: "
            f"{bundle.required_limitations}"
        )

    # An empty bundle carries no decision information, so admitting it would
    # authorize an evaluation with nothing to evaluate against.
    if not bundle.authentic_decision_views:
        raise ValueError(
            "promotion evaluation requires at least one authentic decision view"
        )


def build_evaluation_run_identity(
    *,
    strategy_hash: SHA256Hash,
    protocol_hash: SHA256Hash,
    cost_model_hash: SHA256Hash,
    admission: EvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    evaluator_evidence_hash: SHA256Hash,
    code_version_hash: SHA256Hash,
    environment_closure_hash: SHA256Hash,
) -> EvaluationRunIdentityV1:
    """Build the deterministic semantic identity for one evaluation run.

    The admission and the bundle are taken as objects rather than as loose
    hashes so the declared chain `admission.input_bundle_hash == bundle_hash`
    is enforced here. Accepting the two hashes independently allowed a run
    identity to bind an admission to a bundle that admission never admitted.
    """
    if admission.input_bundle_hash != bundle.bundle_hash:
        raise ValueError(
            "run identity requires the admission to admit this exact bundle: "
            f"admission binds {admission.input_bundle_hash}, "
            f"bundle is {bundle.bundle_hash}"
        )
    draft = EvaluationRunIdentityV1.model_construct(
        schema_version="1",
        strategy_hash=strategy_hash,
        protocol_hash=protocol_hash,
        cost_model_hash=cost_model_hash,
        admission_hash=admission.admission_hash,
        bundle_hash=bundle.bundle_hash,
        evaluator_evidence_hash=evaluator_evidence_hash,
        code_version_hash=code_version_hash,
        environment_closure_hash=environment_closure_hash,
        run_identity_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"run_identity_hash": evaluation_run_identity_hash(draft)}
    )
    return EvaluationRunIdentityV1.model_validate(candidate.model_dump())
