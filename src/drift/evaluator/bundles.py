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
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.qualification import (
    M1eCompletionRecordV1,
    PilotProfileSetV1,
    PurposeQualificationReportV1,
    QualificationProfileV1,
)
from drift.domain.qualification_adapters import QualifiedSourceHandoffV1
from drift.domain.securities import ListingV1, SecurityV1
from drift.domain.universes import StructuralEligibilityResultV1
from drift.evaluator.admission import validate_m1e_promotion_evidence
from drift.serialization.canonical import content_hash


def _ordered[T](members: tuple[T, ...]) -> tuple[T, ...]:
    """Order bundle members by exact content hash."""
    paired = tuple((content_hash(member), member) for member in members)
    return tuple(member for _, member in sorted(paired, key=lambda pair: pair[0]))


def build_evaluation_input_bundle(
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

    Members are ordered before hashing so the computed hash matches the order
    the model's own validators enforce on revalidation.
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
) -> None:
    """Validate a promotion admission against M1e evidence and its input bundle.

    Composes the Task 1 M1e evidence gate with structural anti-laundering
    verification of the bundle itself.
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


def build_evaluation_run_identity(
    *,
    strategy_hash: SHA256Hash,
    protocol_hash: SHA256Hash,
    cost_model_hash: SHA256Hash,
    admission_hash: SHA256Hash,
    bundle_hash: SHA256Hash,
    code_version_hash: SHA256Hash,
    environment_closure_hash: SHA256Hash,
) -> EvaluationRunIdentityV1:
    """Build the deterministic semantic identity for one evaluation run."""
    draft = EvaluationRunIdentityV1.model_construct(
        schema_version="1",
        strategy_hash=strategy_hash,
        protocol_hash=protocol_hash,
        cost_model_hash=cost_model_hash,
        admission_hash=admission_hash,
        bundle_hash=bundle_hash,
        code_version_hash=code_version_hash,
        environment_closure_hash=environment_closure_hash,
        run_identity_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"run_identity_hash": evaluation_run_identity_hash(draft)}
    )
    return EvaluationRunIdentityV1.model_validate(candidate.model_dump())
