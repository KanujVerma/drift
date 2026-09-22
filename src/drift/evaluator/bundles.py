"""Admission-to-bundle lane gates and deterministic evaluation run identity."""

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.common import SHA256Hash
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
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    NormalizationQueryV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
)
from drift.domain.qualification import (
    M1eCompletionRecordV1,
    PilotProfileSetV1,
    PurposeQualificationReportV1,
    QualificationProfileV1,
)
from drift.domain.qualification_adapters import QualifiedSourceHandoffV1
from drift.domain.replay_provenance import (
    BundleProvenanceProofV1,
    QualifiedReplayContextV1,
    ReplayContextIdentityV1,
    bind_context_identity_to_snapshot,
    build_bundle_provenance_proof,
    bundle_provenance_proof_hash,
    replay_context_identity_hash,
    validate_bundle_component_coverage,
)
from drift.domain.securities import ListingV1, SecurityV1
from drift.domain.source_snapshots import RealSourceSnapshotV1
from drift.domain.universes import StructuralEligibilityResultV1
from drift.evaluator.admission import validate_m1e_promotion_evidence
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_descriptor,
)
from drift.serialization.canonical import content_hash

type DecisionReplayRequests = tuple[
    tuple[ObservationDecisionReferenceV1, NormalizationQueryV1], ...
]
type OutcomeReplayRequests = tuple[
    tuple[ObservationOutcomeReferenceV1, NormalizationQueryV1], ...
]


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
    exploratory_reconstructed_observations: tuple[
        ExploratoryReconstructedSessionObservationV1, ...
    ] = (),
    source_snapshot_hash: SHA256Hash | None = None,
) -> EvaluationInputBundleV1:
    """Prepare a bundle whose views come from exact upstream Drift replay.

    This is the spec preparation boundary. Views are never accepted from the
    caller; they are materialized here, so a view that no genuine replay
    produces cannot enter a bundle built through this path.
    """
    return assemble_evaluation_input_bundle(
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
        exploratory_reconstructed_observations=exploratory_reconstructed_observations,
        source_snapshot_hash=source_snapshot_hash,
    )


def verify_evaluation_input_bundle(
    *,
    bundle: EvaluationInputBundleV1,
    context: M1dResolutionContext,
    decision_requests: DecisionReplayRequests = (),
    accounting_requests: OutcomeReplayRequests = (),
) -> None:
    """Verify every stored view against exact upstream replay.

    Re-materializes the declared views and requires exact equality with what
    the bundle carries. A forged, hand-constructed, or exploratory-derived view
    cannot survive this check, so it is what makes a bundle's contents trusted
    rather than merely self-declared.
    """
    expected_decision = replay_decision_views(decision_requests, context)
    expected_accounting = replay_accounting_views(accounting_requests, context)

    for label, expected, stored in (
        ("decision", expected_decision, bundle.authentic_decision_views),
        ("accounting", expected_accounting, bundle.authentic_accounting_views),
    ):
        if len(expected) != len(stored):
            raise ValueError(
                f"{label} view count mismatch against replay: "
                f"expected {len(expected)}, bundle carries {len(stored)}"
            )
        # Both sides are canonically ordered by content hash, so compare digests.
        expected_digests = sorted(content_hash(view) for view in expected)
        stored_digests = sorted(content_hash(view) for view in stored)
        if expected_digests != stored_digests:
            raise ValueError(f"{label} views do not match exact upstream replay")

    rebuilt = evaluation_input_bundle_hash(bundle)
    if rebuilt != bundle.bundle_hash:
        raise ValueError("bundle hash does not match its own contents")


def _request_hash(reference: object, query: object) -> SHA256Hash:
    """Exact identity of one replay request as a reference/query pair."""
    return content_hash({"reference": reference, "query": query})


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
    decision_requests: DecisionReplayRequests = (),
    accounting_requests: OutcomeReplayRequests = (),
) -> BundleProvenanceProofV1:
    """Run replay verification once and mint the proof the gate validates.

    This is the only production path to a `BundleProvenanceProofV1`. It refuses
    to mint unless the replay context presented here is the very context the
    qualified snapshot binding was proven over, and unless the bundle asserts
    that same snapshot.
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
        decision_requests=decision_requests,
        accounting_requests=accounting_requests,
    )

    return build_bundle_provenance_proof(
        qualified_context_hash=qualified_context.qualified_hash,
        source_snapshot_hash=qualified_context.source_snapshot_hash,
        bundle=bundle,
        decision_request_hashes=tuple(
            _request_hash(reference, query) for reference, query in decision_requests
        ),
        accounting_request_hashes=tuple(
            _request_hash(reference, query) for reference, query in accounting_requests
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
) -> None:
    """Validate a promotion admission against M1e evidence and its input bundle.

    Composes the Task 1 M1e evidence gate with structural anti-laundering
    verification of the bundle itself and with the provenance proof that binds
    the bundle to a qualified snapshot.

    The proof parameter is required. The unsafe signature that accepted a bundle
    carrying only a self-declared `source_snapshot_hash` is deliberately not
    preserved for compatibility: the issue 31 ruling forbids it.

    No full M1d replay runs here. Replay verification already ran once at mint
    time; this gate revalidates the minted proof cheaply and fail-closed.
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
        code_version_hash=code_version_hash,
        environment_closure_hash=environment_closure_hash,
        run_identity_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"run_identity_hash": evaluation_run_identity_hash(draft)}
    )
    return EvaluationRunIdentityV1.model_validate(candidate.model_dump())
