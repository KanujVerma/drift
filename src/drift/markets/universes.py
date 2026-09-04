"""Audit-side causal universe resolution over exact retained M1b datasets."""

from collections.abc import Mapping
from dataclasses import dataclass

from drift.domain.assertions import (
    CutoffSelectionProofV1,
    EffectiveTimeStatus,
    InformationRole,
    IntervalStatus,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
    evaluate_boundary_at,
    evaluate_interval_at,
)
from drift.domain.common import UUID7, FrozenModel, SHA256Hash
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    ValidatedDatasetBundleV1,
)
from drift.domain.manifests import DatasetManifestV2
from drift.domain.securities import (
    IdentityAssignmentEffect,
    IdentityAssignmentResolutionResultV1,
    IdentityAssignmentSubjectV1,
    IdentityAssignmentVersionV1,
    IdentityKind,
    IdentityReferenceV1,
    IdentityRelationshipKind,
    IdentityRelationshipVersionV1,
    IdentityResolutionClassification,
    IdentityResolutionResultV1,
    ListingHistoryCoverageVersionV1,
    ListingLifecycleResolutionV1,
    ListingLifecycleStatus,
    ListingLifecycleVersionV1,
    ListingRoleVersionV1,
    ListingTerminationVersionV1,
    ListingV1,
    PrimaryListingResolutionV1,
    RecordResolutionClassification,
    ResolutionStatus,
    SecurityClassificationResolutionV1,
    SecurityClassificationStatus,
    SecurityClassificationVersionV1,
    identity_reference,
)
from drift.domain.temporal import (
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
)
from drift.domain.universes import (
    MembershipStatus,
    ResearchUniverseDefinitionV1,
    SourceUniverseDefinitionResolutionV1,
    SourceUniverseDefinitionVersionV1,
    StructuralEligibilityClassification,
    StructuralEligibilityResultV1,
    UniverseDefinitionSubjectV1,
    UniverseMembershipResolutionV1,
    UniverseMembershipVersionV1,
    UniverseTargetLevel,
)
from drift.markets.identity import (
    _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    _build_dependency_query,
    _relationship_chains_for_subject,
    _require_validated_assignment_dataset,
    _require_validated_relationship_dataset,
    _require_validated_role_dataset,
    _resolution_evidence,
    _select_records_for_query,
    resolve_identity,
    resolve_identity_assignment,
    resolve_listing_history_coverage,
    resolve_listing_lifecycle,
    resolve_listing_termination,
    resolve_primary_listing,
    resolve_security_classification,
)
from drift.serialization.canonical import content_hash


@dataclass(frozen=True)
class ValidatedRecords[T]:
    """Explicit retained record bytes' parsed values and exact validation binding."""

    records: tuple[T, ...]
    manifest: DatasetManifestV2
    decision: DatasetValidationDecisionV2


@dataclass(frozen=True)
class UniverseResolutionContext:
    """Complete audit inputs, never a cache or a trusted result registry."""

    identity_bundle: ValidatedDatasetBundleV1
    universe_bundle: ValidatedDatasetBundleV1
    assignments: ValidatedRecords[IdentityAssignmentVersionV1]
    memberships: ValidatedRecords[UniverseMembershipVersionV1]
    source_definitions: ValidatedRecords[SourceUniverseDefinitionVersionV1]
    policy: AvailabilityPolicyV1
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1]


@dataclass(frozen=True)
class StructuralResolutionContext:
    """All retained inputs required to reconstruct structural component results."""

    universe: UniverseResolutionContext
    relationships: ValidatedRecords[IdentityRelationshipVersionV1]
    classifications: ValidatedRecords[SecurityClassificationVersionV1]
    roles: ValidatedRecords[ListingRoleVersionV1]
    lifecycle: ValidatedRecords[ListingLifecycleVersionV1]
    terminations: ValidatedRecords[ListingTerminationVersionV1]
    coverage: ValidatedRecords[ListingHistoryCoverageVersionV1]


STRICT_CLASSIFICATION_CONTRACT_HASH = content_hash(
    {
        "algorithm_id": "drift.initial-structural-classification",
        "version": "1",
        "issuer_form": "operating_company",
        "instrument_form": "common_share",
        "domestic_status": "domestic",
        "required_source_text": (
            "issuer_domicile",
            "incorporation_country",
            "share_class_label",
        ),
        "unknown_or_conflict": "indeterminate",
        "other_known_forms": "unsupported",
    }
)


_SOURCE_DEFINITION_SPEC_V1 = {
    "algorithm_id": "drift.source-universe-definition",
    "version": "1",
    "rule": "complete-validated-dataset-causal-selection-then-effective-interval",
}
_MEMBERSHIP_SPEC_V1 = {
    "algorithm_id": "drift.universe-membership",
    "version": "1",
    "rule": "causal-chain-selection-then-definitely-latest-business-effect",
    "withdrawal": "no-business-event",
    "absence": "indeterminate",
    "dependencies": "replay-source-definition-and-retained-typed-identity",
}
_MEMBERSHIP_TARGET_SPEC_V1 = {
    "algorithm_id": "drift.membership-retained-target",
    "version": "1",
    "rule": "causally-selected-assignment-establishes-retained-identity",
    "unassigned": "preserve-prior-causal-positive-assignment-without-inferring-removal",
    "withdrawal": "no-authority-from-withdrawn-chain",
    "effective_interval": "association-validity-not-current-listing-activity",
}
SOURCE_DEFINITION_IMPLEMENTATION_HASH = content_hash(_SOURCE_DEFINITION_SPEC_V1)
MEMBERSHIP_IMPLEMENTATION_HASH = content_hash(_MEMBERSHIP_SPEC_V1)
MEMBERSHIP_TARGET_IMPLEMENTATION_HASH = content_hash(_MEMBERSHIP_TARGET_SPEC_V1)


def _bound_result[T: FrozenModel](model: type[T], values: dict[str, object]) -> T:
    return model.model_validate(
        {**values, "outcome_binding_hash": content_hash(values)}
    )


def _require_universe_query(
    query: NormalizedSelectionQueryV1,
    subject: object,
    context: UniverseResolutionContext,
) -> None:
    if query.purpose is not M1bSelectionPurpose.UNIVERSE_MEMBERSHIP:
        raise DatasetValidationError.single("universe_membership_purpose_required")
    if query.subject_hash != content_hash(subject):
        raise DatasetValidationError.single("universe_subject_mismatch")
    if query.context_bundle_hashes != (content_hash(context.universe_bundle),):
        raise DatasetValidationError.single("universe_bundle_mismatch")
    if query.policy_id != context.policy.policy_id or query.policy_hash != content_hash(
        context.policy
    ):
        raise DatasetValidationError.single("universe_policy_mismatch")


def _same_temporal_context(
    left: NormalizedSelectionQueryV1, right: NormalizedSelectionQueryV1
) -> bool:
    return all(
        getattr(left, name) == getattr(right, name)
        for name in (
            "knowledge_cutoff",
            "evaluation_time",
            "requested_channel",
            "policy_id",
            "policy_hash",
            "resolution_mode",
            "information_role",
        )
    )


def resolve_source_universe_definition(
    subject: UniverseDefinitionSubjectV1,
    query: NormalizedSelectionQueryV1,
    context: UniverseResolutionContext,
) -> SourceUniverseDefinitionResolutionV1:
    """Resolve the source methodology itself before it can authorize membership."""
    _require_universe_query(query, subject, context)
    dataset = context.source_definitions
    _require_validated_role_dataset(
        dataset.records,
        dataset.manifest,
        dataset.decision,
        context.universe_bundle,
        "source_universe_definition",
        "source_universe_definition",
        allow_empty=True,
    )
    candidates = tuple(
        record
        for record in dataset.records
        if record.universe_id == subject.universe_id
        and record.universe_version == subject.universe_version
    )
    selected, proof = _select_records_for_query(
        candidates,
        query,
        context.universe_bundle,
        dataset.manifest,
        dataset.decision,
        context.policy,
        context.retained_evidence,
        SOURCE_DEFINITION_IMPLEMENTATION_HASH,
    )
    active = tuple(
        record
        for record in selected
        if evaluate_interval_at(record.effective_interval, query.evaluation_time)
        is IntervalStatus.ACTIVE
    )
    uncertain = proof.classification is CutoffEligibility.INDETERMINATE or any(
        evaluate_interval_at(record.effective_interval, query.evaluation_time)
        is IntervalStatus.INDETERMINATE
        for record in selected
    )
    definition = active[0] if len(active) == 1 and not uncertain else None
    classification = (
        RecordResolutionClassification.RESOLVED
        if definition is not None
        else RecordResolutionClassification.CONFLICT
        if len(active) > 1
        else RecordResolutionClassification.INDETERMINATE
    )
    if definition is not None and definition.identity_bundle_hash != content_hash(
        context.identity_bundle
    ):
        raise DatasetValidationError.single(
            "source_definition_identity_bundle_mismatch"
        )
    return _bound_result(
        SourceUniverseDefinitionResolutionV1,
        {
            "schema_version": "1",
            "subject": subject,
            "definition": definition,
            "classification": classification,
            "evidence": _resolution_evidence(query, proof),
        },
    )


def membership_subject(
    definition: ResearchUniverseDefinitionV1 | SourceUniverseDefinitionResolutionV1,
    target: IdentityReferenceV1,
) -> dict[str, object]:
    """Bind the selected methodology and its interpretation, not only universe text."""
    if isinstance(definition, ResearchUniverseDefinitionV1):
        return {
            "universe_id": definition.universe_id,
            "universe_version": definition.universe_version,
            "definition_hash": content_hash(definition),
            "definition_resolution_hash": None,
            "target": target,
        }
    if not isinstance(definition, SourceUniverseDefinitionResolutionV1):
        raise DatasetValidationError.single("source_definition_resolution_required")
    return {
        "universe_id": definition.subject.universe_id,
        "universe_version": definition.subject.universe_version,
        "definition_hash": None
        if definition.definition is None
        else content_hash(definition.definition),
        "definition_resolution_hash": content_hash(definition),
        "target": target,
    }


def _target_assignments(
    target: IdentityReferenceV1,
    query: NormalizedSelectionQueryV1,
    context: UniverseResolutionContext,
) -> tuple[IdentityAssignmentResolutionResultV1, ...]:
    dataset = context.assignments
    _require_validated_assignment_dataset(
        dataset.records, dataset.manifest, dataset.decision, context.identity_bundle
    )
    subjects = {
        IdentityAssignmentSubjectV1(
            identity_kind=target.kind,
            source_namespace=record.source_namespace,
            source_key=record.source_key,
        )
        for record in dataset.records
        if identity_reference(record.identity) == target
    }
    results = []
    for subject in sorted(
        subjects, key=lambda item: (item.source_namespace, item.source_key)
    ):
        assignment_query = _build_dependency_query(
            query,
            dataset.manifest,
            dataset.decision,
            M1bSelectionPurpose.IDENTITY_RESOLUTION,
            subject,
        ).model_copy(
            update={
                "context_bundle_hashes": (content_hash(context.identity_bundle),),
            }
        )
        results.append(
            resolve_identity_assignment(
                subject,
                dataset.records,
                assignment_query,
                context.identity_bundle,
                dataset.manifest,
                dataset.decision,
                context.policy,
                context.retained_evidence,
            )
        )
    return tuple(results)


def resolve_universe_membership(
    definition: ResearchUniverseDefinitionV1 | SourceUniverseDefinitionResolutionV1,
    target: IdentityReferenceV1,
    query: NormalizedSelectionQueryV1,
    context: UniverseResolutionContext,
) -> UniverseMembershipResolutionV1:
    """Replay source methodology and exact target provenance before business effect."""
    subject = membership_subject(definition, target)
    _require_universe_query(query, subject, context)
    dataset = context.memberships
    _require_validated_role_dataset(
        dataset.records,
        dataset.manifest,
        dataset.decision,
        context.universe_bundle,
        "universe_membership",
        "universe_membership",
        allow_empty=True,
    )
    selected_definition: (
        ResearchUniverseDefinitionV1 | SourceUniverseDefinitionVersionV1 | None
    )
    if isinstance(definition, SourceUniverseDefinitionResolutionV1):
        if not _same_temporal_context(definition.evidence.normalized_query, query):
            raise DatasetValidationError.single("source_definition_context_mismatch")
        replay = resolve_source_universe_definition(
            definition.subject, definition.evidence.normalized_query, context
        )
        if replay != definition:
            raise DatasetValidationError.single("source_definition_replay_mismatch")
        selected_definition = replay.definition
    else:
        selected_definition = definition
        if definition.universe_bundle_hash != content_hash(context.universe_bundle):
            raise DatasetValidationError.single("research_universe_bundle_mismatch")
    if target.kind not in {IdentityKind.SECURITY, IdentityKind.LISTING}:
        raise DatasetValidationError.single("unsupported_universe_target_level")
    if selected_definition is not None:
        if selected_definition.target_level.value != target.kind.value:
            raise DatasetValidationError.single("universe_target_level_mismatch")
        if selected_definition.identity_bundle_hash != content_hash(
            context.identity_bundle
        ):
            raise DatasetValidationError.single("universe_identity_bundle_mismatch")
    universe_records = tuple(
        record
        for record in dataset.records
        if record.universe_id == subject["universe_id"]
        and record.universe_version == subject["universe_version"]
    )
    if any(
        record.target_level.value != target.kind.value for record in universe_records
    ):
        raise DatasetValidationError.single(
            "membership_definition_target_level_mismatch"
        )
    candidates = tuple(
        record for record in universe_records if record.target_id == target.internal_id
    )
    selected, proof = _select_records_for_query(
        candidates,
        query,
        context.universe_bundle,
        dataset.manifest,
        dataset.decision,
        context.policy,
        context.retained_evidence,
        MEMBERSHIP_IMPLEMENTATION_HASH,
    )
    identity_known, assignment_proofs = _retained_target_provenance(
        target, query, context
    )
    statuses = tuple(
        (record, evaluate_boundary_at(record.effective_time, query.evaluation_time))
        for record in selected
    )
    active = tuple(
        record for record, status in statuses if status is EffectiveTimeStatus.EFFECTIVE
    )
    upcoming = tuple(
        sorted(
            {
                record.membership_effect
                for record, status in statuses
                if status is EffectiveTimeStatus.NOT_EFFECTIVE
            },
            key=lambda effect: effect.value,
        )
    )
    uncertain = (
        selected_definition is None
        or not identity_known
        or proof.classification is CutoffEligibility.INDETERMINATE
        or any(status is EffectiveTimeStatus.INDETERMINATE for _, status in statuses)
    )
    # A latest candidate is excluded only when another event is definitely later.
    # Equal or overlapping opposing events cannot be ordered by revision sequence.
    latest = tuple(
        record
        for record in active
        if not any(
            other.effective_time.lower_bound is not None
            and record.effective_time.upper_bound is not None
            and other.effective_time.lower_bound > record.effective_time.upper_bound
            for other in active
            if other is not record
        )
    )
    effects = {record.membership_effect for record in latest}
    status = (
        MembershipStatus.INDETERMINATE
        if uncertain or len(effects) != 1
        else MembershipStatus(next(iter(effects)).value)
    )
    return _bound_result(
        UniverseMembershipResolutionV1,
        {
            "schema_version": "1",
            "universe_id": subject["universe_id"],
            "universe_version": subject["universe_version"],
            "target_level": UniverseTargetLevel(target.kind.value),
            "target_id": target.internal_id,
            "definition_hash": subject["definition_hash"],
            "definition_resolution_hash": subject["definition_resolution_hash"],
            "identity_bundle_hash": content_hash(context.identity_bundle),
            "universe_bundle_hash": content_hash(context.universe_bundle),
            "target_assignment_proof_hashes": assignment_proofs,
            "status": status,
            "known_upcoming_effects": upcoming,
            "reasons": (status.value,),
            "evidence": _resolution_evidence(query, proof),
        },
    )


def _retained_target_provenance(
    target: IdentityReferenceV1,
    query: NormalizedSelectionQueryV1,
    context: UniverseResolutionContext,
) -> tuple[bool, tuple[SHA256Hash, ...]]:
    """Prove retained identity at K without requiring its association active at E."""
    dataset = context.assignments
    _require_validated_assignment_dataset(
        dataset.records, dataset.manifest, dataset.decision, context.identity_bundle
    )
    relevant_ids = {
        record.revision.logical_record_id
        for record in dataset.records
        if identity_reference(record.identity) == target
    }
    candidates = tuple(
        record
        for record in dataset.records
        if record.revision.logical_record_id in relevant_ids
    )
    dependency_query = _identity_query(
        query,
        dataset,
        M1bSelectionPurpose.IDENTITY_RESOLUTION,
        {"retained_identity": target},
        context,
    )
    selected, proof = _select_records_for_query(
        candidates,
        dependency_query,
        context.identity_bundle,
        dataset.manifest,
        dataset.decision,
        context.policy,
        context.retained_evidence,
        MEMBERSHIP_TARGET_IMPLEMENTATION_HASH,
    )
    hashes = {content_hash(proof)}
    known = False
    for current in selected:
        if identity_reference(current.identity) != target:
            continue
        if current.assignment_effect is IdentityAssignmentEffect.ASSIGNED:
            known = True
            continue
        # UNASSIGNED ends an association. It cannot invent identity by itself,
        # but a prior non-withdrawn, causally selected assignment remains evidence.
        prefix = tuple(
            record
            for record in candidates
            if record.revision.logical_record_id == current.revision.logical_record_id
            and record.revision.source_sequence < current.revision.source_sequence
        )
        while prefix:
            previous, prior_proof = _select_records_for_query(
                prefix,
                dependency_query,
                context.identity_bundle,
                dataset.manifest,
                dataset.decision,
                context.policy,
                context.retained_evidence,
                MEMBERSHIP_TARGET_IMPLEMENTATION_HASH,
            )
            hashes.add(content_hash(prior_proof))
            if not previous or identity_reference(previous[0].identity) != target:
                break
            if previous[0].assignment_effect is IdentityAssignmentEffect.ASSIGNED:
                known = True
                break
            prefix = tuple(
                record
                for record in prefix
                if record.revision.source_sequence
                < previous[0].revision.source_sequence
            )
    return known, tuple(sorted(hashes))


def structural_subject(
    definition: ResearchUniverseDefinitionV1,
    issuer_id: UUID7,
    security_id: UUID7,
    listing_id: UUID7,
    methodology_id: str,
) -> dict[str, object]:
    return {
        "definition_hash": content_hash(definition),
        "issuer_id": issuer_id,
        "security_id": security_id,
        "listing_id": listing_id,
        "methodology_id": methodology_id,
    }


def _identity_query[T](
    query: NormalizedSelectionQueryV1,
    data: ValidatedRecords[T],
    purpose: M1bSelectionPurpose,
    subject: object,
    context: UniverseResolutionContext,
) -> NormalizedSelectionQueryV1:
    return _build_dependency_query(
        query, data.manifest, data.decision, purpose, subject
    ).model_copy(
        update={
            "context_bundle_hashes": (content_hash(context.identity_bundle),),
        }
    )


def _relationship_evidence(
    subject: IdentityReferenceV1,
    query: NormalizedSelectionQueryV1,
    context: StructuralResolutionContext,
) -> tuple[IdentityResolutionResultV1, CutoffSelectionProofV1]:
    universe = context.universe
    data = context.relationships
    assignments = universe.assignments
    dependency_query = _identity_query(
        query, data, M1bSelectionPurpose.IDENTITY_RESOLUTION, subject, universe
    )
    resolution = resolve_identity(
        subject,
        assignments.records,
        data.records,
        dependency_query,
        universe.identity_bundle,
        data.manifest,
        data.decision,
        universe.policy,
        universe.retained_evidence,
        assignment_manifest=assignments.manifest,
        assignment_decision=assignments.decision,
    )
    candidates = tuple(
        record
        for chain in _relationship_chains_for_subject(data.records, subject).values()
        for record in chain
    )
    _, proof = _select_records_for_query(
        candidates,
        dependency_query,
        universe.identity_bundle,
        data.manifest,
        data.decision,
        universe.policy,
        universe.retained_evidence,
        _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    )
    return resolution, proof


def _compose_structural(
    definition: ResearchUniverseDefinitionV1,
    listing: ListingV1,
    issuer_id: UUID7,
    security_id: UUID7,
    methodology_id: str,
    query: NormalizedSelectionQueryV1,
    assignments: tuple[IdentityAssignmentResolutionResultV1, ...],
    identities: tuple[IdentityResolutionResultV1, ...],
    classification: SecurityClassificationResolutionV1 | None,
    primary: PrimaryListingResolutionV1 | None,
    lifecycle: ListingLifecycleResolutionV1 | None,
    membership: UniverseMembershipResolutionV1,
    additional_proofs: tuple[SHA256Hash, ...],
) -> StructuralEligibilityResultV1:
    """Pure final composition; only the public reconstruction boundary calls this."""
    unresolved = (
        classification is None
        or primary is None
        or lifecycle is None
        or classification.classification
        in {
            SecurityClassificationStatus.INDETERMINATE,
            SecurityClassificationStatus.CONFLICT,
        }
        or primary.classification is not RecordResolutionClassification.RESOLVED
        or lifecycle.status is ListingLifecycleStatus.INDETERMINATE
        or membership.status is MembershipStatus.INDETERMINATE
    )
    excluded = bool(
        classification is not None
        and classification.classification is SecurityClassificationStatus.UNSUPPORTED
        or primary is not None
        and primary.listing_id != listing.listing_id
        or lifecycle is not None
        and lifecycle.status
        in {
            ListingLifecycleStatus.NOT_YET_LISTED,
            ListingLifecycleStatus.SUSPENDED,
            ListingLifecycleStatus.TERMINATED,
        }
        or membership.status is MembershipStatus.EXCLUDED
    )
    status = (
        StructuralEligibilityClassification.INDETERMINATE
        if unresolved
        else StructuralEligibilityClassification.INELIGIBLE
        if excluded
        else StructuralEligibilityClassification.ELIGIBLE
    )
    proofs = set(additional_proofs)
    for assignment in assignments:
        proofs.update(assignment.evidence.selection_proof_hashes)
    for identity in identities:
        proofs.update(identity.selection_proof_hashes)
    for component in (classification, primary, lifecycle, membership):
        if component is not None:
            proofs.update(component.evidence.selection_proof_hashes)
    proofs.update(membership.target_assignment_proof_hashes)
    return _bound_result(
        StructuralEligibilityResultV1,
        {
            "schema_version": "1",
            "issuer_id": issuer_id,
            "security_id": security_id,
            "listing_id": listing.listing_id,
            "methodology_id": methodology_id,
            "definition_hash": content_hash(definition),
            "classification": status,
            "reasons": (status.value,),
            "normalized_query": query,
            "identity_bundle_hash": definition.identity_bundle_hash,
            "universe_bundle_hash": definition.universe_bundle_hash,
            "identity_assignment_resolution_hashes": tuple(
                sorted({content_hash(result) for result in assignments})
            ),
            "identity_resolution_hashes": tuple(
                sorted({content_hash(result) for result in identities})
            ),
            "classification_resolution_hash": None
            if classification is None
            else content_hash(classification),
            "primary_listing_resolution_hash": None
            if primary is None
            else content_hash(primary),
            "lifecycle_resolution_hash": None
            if lifecycle is None
            else content_hash(lifecycle),
            "membership_resolution_hash": content_hash(membership),
            "selection_proof_hashes": tuple(sorted(proofs)),
        },
    )


def resolve_structural_eligibility(
    definition: ResearchUniverseDefinitionV1,
    listing: ListingV1,
    issuer_id: UUID7,
    security_id: UUID7,
    methodology_id: str,
    query: NormalizedSelectionQueryV1,
    context: StructuralResolutionContext,
) -> StructuralEligibilityResultV1:
    """Reconstruct every component from exact datasets before pure composition."""
    universe = context.universe
    subject = structural_subject(
        definition, issuer_id, security_id, listing.listing_id, methodology_id
    )
    expected = _build_dependency_query(
        query,
        universe.memberships.manifest,
        universe.memberships.decision,
        M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        subject,
    )
    if query != expected or query.context_bundle_hashes != tuple(
        sorted(
            (
                content_hash(universe.identity_bundle),
                content_hash(universe.universe_bundle),
            )
        )
    ):
        raise DatasetValidationError.single("structural_query_binding_mismatch")
    if (
        query.resolution_mode is not ResolutionMode.AS_KNOWN
        or query.information_role is not InformationRole.DECISION_INFORMATION
    ):
        raise DatasetValidationError.single("structural_decision_mode_required")
    if (
        query.policy_id != universe.policy.policy_id
        or query.policy_hash != content_hash(universe.policy)
    ):
        raise DatasetValidationError.single("structural_policy_mismatch")
    if definition.classification_contract_hash != STRICT_CLASSIFICATION_CONTRACT_HASH:
        raise DatasetValidationError.single(
            "unsupported_structural_classification_contract"
        )
    _require_validated_relationship_dataset(
        context.relationships.records,
        context.relationships.manifest,
        context.relationships.decision,
        universe.identity_bundle,
    )
    for data, role in (
        (context.classifications, "security_classification"),
        (context.roles, "listing_role"),
        (context.lifecycle, "listing_lifecycle"),
        (context.terminations, "listing_termination"),
        (context.coverage, "listing_history_coverage"),
    ):
        _require_validated_role_dataset(
            data.records,
            data.manifest,
            data.decision,
            universe.identity_bundle,
            role,
            role,
            allow_empty=True,
        )
    listing_ref = identity_reference(listing)
    membership_query = _build_dependency_query(
        query,
        universe.memberships.manifest,
        universe.memberships.decision,
        M1bSelectionPurpose.UNIVERSE_MEMBERSHIP,
        membership_subject(definition, listing_ref),
    ).model_copy(
        update={
            "context_bundle_hashes": (content_hash(universe.universe_bundle),),
        }
    )
    member = resolve_universe_membership(
        definition, listing_ref, membership_query, universe
    )
    targets = (
        IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=issuer_id),
        IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=security_id),
        listing_ref,
    )
    grouped_assignments = tuple(
        _target_assignments(target, query, universe) for target in targets
    )
    assignment_results = tuple(
        result for group in grouped_assignments for result in group
    )
    assignment_known = all(
        group
        and all(
            result.classification is IdentityResolutionClassification.RESOLVED
            and result.assigned_identities == (target,)
            for result in group
        )
        for target, group in zip(targets, grouped_assignments, strict=True)
    )
    if not assignment_known:
        return _compose_structural(
            definition,
            listing,
            issuer_id,
            security_id,
            methodology_id,
            query,
            assignment_results,
            (),
            None,
            None,
            None,
            member,
            (),
        )
    selected_assignment_hashes = {
        digest
        for result in grouped_assignments[2]
        for digest in result.evidence.selected_record_hashes
    }
    if not any(
        record.identity == listing
        and content_hash(record) in selected_assignment_hashes
        for record in universe.assignments.records
    ):
        raise DatasetValidationError.single("structural_listing_assignment_mismatch")
    issuer_identity, issuer_proof = _relationship_evidence(targets[0], query, context)
    security_identity, security_proof = _relationship_evidence(
        targets[1], query, context
    )
    identities = (issuer_identity, security_identity)
    selected_links = set(issuer_proof.selected_record_hashes) | set(
        security_proof.selected_record_hashes
    )

    def linked(
        left: IdentityReferenceV1,
        right: IdentityReferenceV1,
        kind: IdentityRelationshipKind,
    ) -> bool:
        return any(
            record.left == left
            and record.right == right
            and record.relationship_kind is kind
            and record.resolution_status is ResolutionStatus.RESOLVED
            and content_hash(record) in selected_links
            and evaluate_interval_at(record.effective_interval, query.evaluation_time)
            is IntervalStatus.ACTIVE
            for record in context.relationships.records
        )

    if (
        any(
            result.classification is not IdentityResolutionClassification.RESOLVED
            for result in identities
        )
        or not linked(
            targets[0], targets[1], IdentityRelationshipKind.ISSUER_HAS_SECURITY
        )
        or not linked(
            targets[1], targets[2], IdentityRelationshipKind.SECURITY_HAS_LISTING
        )
    ):
        return _compose_structural(
            definition,
            listing,
            issuer_id,
            security_id,
            methodology_id,
            query,
            assignment_results,
            identities,
            None,
            None,
            None,
            member,
            (),
        )
    assignments = universe.assignments
    relationships = context.relationships
    classification_query = _identity_query(
        query,
        context.classifications,
        M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        {"issuer_id": issuer_id, "security_id": security_id},
        universe,
    )
    classification = resolve_security_classification(
        issuer_id,
        security_id,
        context.classifications.records,
        classification_query,
        universe.identity_bundle,
        context.classifications.manifest,
        context.classifications.decision,
        universe.policy,
        universe.retained_evidence,
        identity_assignments=assignments.records,
        assignment_manifest=assignments.manifest,
        assignment_decision=assignments.decision,
        identity_relationships=relationships.records,
        relationship_resolution=issuer_identity,
        relationship_proof=issuer_proof,
        relationship_manifest=relationships.manifest,
        relationship_decision=relationships.decision,
    )
    primary_query = _identity_query(
        query,
        context.roles,
        M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        {"security_id": security_id, "methodology_id": methodology_id},
        universe,
    )
    primary = resolve_primary_listing(
        security_id,
        methodology_id,
        context.roles.records,
        relationships.records,
        primary_query,
        universe.identity_bundle,
        context.roles.manifest,
        context.roles.decision,
        universe.policy,
        universe.retained_evidence,
        identity_assignments=assignments.records,
        assignment_manifest=assignments.manifest,
        assignment_decision=assignments.decision,
        relationship_resolution=security_identity,
        relationship_proof=security_proof,
        relationship_manifest=relationships.manifest,
        relationship_decision=relationships.decision,
    )
    listing_subject = {"listing_id": listing.listing_id}
    coverage_query = _identity_query(
        query,
        context.coverage,
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        listing_subject,
        universe,
    )
    coverage = resolve_listing_history_coverage(
        listing.listing_id,
        context.coverage.records,
        coverage_query,
        universe.identity_bundle,
        context.coverage.manifest,
        context.coverage.decision,
        universe.policy,
        universe.retained_evidence,
    )
    termination_query = _identity_query(
        query,
        context.terminations,
        M1bSelectionPurpose.LISTING_TERMINATION,
        listing_subject,
        universe,
    )
    termination = resolve_listing_termination(
        listing.listing_id,
        context.terminations.records,
        coverage,
        termination_query,
        universe.identity_bundle,
        context.terminations.manifest,
        context.terminations.decision,
        universe.policy,
        universe.retained_evidence,
        coverage_versions=context.coverage.records,
        coverage_manifest=context.coverage.manifest,
        coverage_decision=context.coverage.decision,
        identity_relationships=relationships.records,
        relationship_resolution=security_identity,
        relationship_proof=security_proof,
        relationship_manifest=relationships.manifest,
        relationship_decision=relationships.decision,
        identity_assignments=assignments.records,
        assignment_manifest=assignments.manifest,
        assignment_decision=assignments.decision,
    )
    lifecycle_query = _identity_query(
        query,
        context.lifecycle,
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        listing_subject,
        universe,
    )
    lifecycle = resolve_listing_lifecycle(
        listing.listing_id,
        context.lifecycle.records,
        termination,
        lifecycle_query,
        universe.identity_bundle,
        context.lifecycle.manifest,
        context.lifecycle.decision,
        universe.policy,
        universe.retained_evidence,
        terminations=context.terminations.records,
        termination_manifest=context.terminations.manifest,
        termination_decision=context.terminations.decision,
        coverage=coverage,
        coverage_versions=context.coverage.records,
        coverage_manifest=context.coverage.manifest,
        coverage_decision=context.coverage.decision,
        identity_relationships=relationships.records,
        relationship_resolution=security_identity,
        relationship_proof=security_proof,
        relationship_manifest=relationships.manifest,
        relationship_decision=relationships.decision,
        identity_assignments=assignments.records,
        assignment_manifest=assignments.manifest,
        assignment_decision=assignments.decision,
    )
    return _compose_structural(
        definition,
        listing,
        issuer_id,
        security_id,
        methodology_id,
        query,
        assignment_results,
        identities,
        classification,
        primary,
        lifecycle,
        member,
        (
            *coverage.evidence.selection_proof_hashes,
            *termination.evidence.selection_proof_hashes,
        ),
    )
