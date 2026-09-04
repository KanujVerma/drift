"""Point-in-time resolution over validated historical identity assertions."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Protocol

from drift.datasets.assertions import (
    build_cutoff_selection_proof,
    select_assertion_version,
    validate_assertion_chain,
)
from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import (
    AssertionSelectionResultV1,
    AssertionVersionProjectionV1,
    BoundaryShape,
    CutoffSelectionProofV1,
    EffectiveTimeStatus,
    IntervalStatus,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionEvidenceV1,
    ResolutionMode,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
    evaluate_boundary_at,
    evaluate_interval_at,
)
from drift.domain.common import UUID7, SHA256Hash, UTCDateTime
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    ValidatedDatasetBundleV1,
    ValidationResult,
    ValidationScope,
)
from drift.domain.manifests import DatasetManifestV2
from drift.domain.revisions import RevisionKind
from drift.domain.securities import (
    DomesticStatus,
    ExternalIdentifierKind,
    ExternalIdentifierMappingVersionV1,
    ExternalIdentifierNamespaceV1,
    ExternalIdentifierResolutionResultV1,
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
    InstrumentForm,
    IssuerForm,
    ListingHistoryCoverageResolutionV1,
    ListingHistoryCoverageStatus,
    ListingHistoryCoverageVersionV1,
    ListingLifecycleEventKind,
    ListingLifecycleResolutionV1,
    ListingLifecycleStatus,
    ListingLifecycleVersionV1,
    ListingRole,
    ListingRoleVersionV1,
    ListingTerminationReason,
    ListingTerminationResolutionV1,
    ListingTerminationStatus,
    ListingTerminationVersionV1,
    ListingV1,
    MappingStatus,
    PrimaryListingResolutionV1,
    RecordResolutionClassification,
    ResolutionStatus,
    SecurityClassificationResolutionV1,
    SecurityClassificationStatus,
    SecurityClassificationVersionV1,
    external_identifier_resolution_binding_hash,
    identity_reference,
    listing_history_coverage_resolution_binding_hash,
    listing_lifecycle_resolution_binding_hash,
    listing_termination_resolution_binding_hash,
    primary_listing_resolution_binding_hash,
    security_classification_resolution_binding_hash,
)
from drift.domain.temporal import (
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
    SourcePrecision,
)
from drift.markets.validation import (
    is_exact_identity_role_manifest,
    is_exact_typed_role_manifest,
    validate_external_identifier_mappings,
    validate_listing_lifecycle,
    validate_listing_roles,
    validate_listing_terminations,
)
from drift.serialization.canonical import content_hash

_LISTING_COVERAGE_SELECTION_IMPLEMENTATION_SPEC_V1 = {
    "algorithm_id": "drift.listing.coverage-selection",
    "algorithm_version": "1",
    "chain_selection": "causal-as-known-or-pinned-current",
    "definite_rule": "one-selected-nonunknown-boundary",
    "fallback": "unknown",
}
_LISTING_TERMINATION_SELECTION_IMPLEMENTATION_SPEC_V1 = {
    "algorithm_id": "drift.listing.termination-selection",
    "algorithm_version": "1",
    "chain_selection": "causal-as-known-or-pinned-current",
    "ordering_rule": "latest-last-trade-not-after-earliest-termination",
    "absence_rule": "complete-coverage-through-e",
    "dependency_rule": "authenticate-successor-only-when-effective",
}
_LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_SPEC_V1 = {
    "algorithm_id": "drift.listing.lifecycle-selection",
    "algorithm_version": "1",
    "chain_selection": "causal-as-known-or-pinned-current",
    "state_order": (
        "admitted",
        "first-regular-trade",
        "suspended-resumed",
        "termination",
    ),
    "dependency_rule": "authenticate-transfer-only-when-effective",
}

# Retain the V1 specifications above as historical provenance. The current
# resolver emits V2 proofs; reproducing V1 outcomes requires its pinned code.
_EXTERNAL_IDENTIFIER_SELECTION_IMPLEMENTATION_SPEC_V2 = {
    "algorithm_id": "drift.external-identifier-resolution",
    "algorithm_version": "2",
    "chain_selection": "causal-as-known-or-pinned-current",
    "identity_rule": "exact-assignment-namespace-venue-and-mapping-interval",
    "lifetime_rule": "independent-selected-known-admission-and-termination-bounds",
    "unknown_rule": "lifecycle-uncertainty-does-not-erase-mapping",
    "activity_rule": "resolved-mapping-does-not-establish-activity",
}
_LISTING_TERMINATION_SELECTION_IMPLEMENTATION_SPEC_V2 = {
    **_LISTING_TERMINATION_SELECTION_IMPLEMENTATION_SPEC_V1,
    "algorithm_version": "2",
    "ordering_rule": "reject-overlapping-supplied-bounds-preserve-unknown-last-trade",
    "termination_rule": "definitely-effective-selected-termination",
}
_LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_SPEC_V2 = {
    **_LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_SPEC_V1,
    "algorithm_version": "2",
    "termination_rule": "definite-effect-independent-of-unknown-last-trade",
}

_IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH = (
    "bf61c84a232e0d5c11a99b6451f9a43f37f96dab220c1c7036456252394c961d"
)
_EXTERNAL_IDENTIFIER_SELECTION_IMPLEMENTATION_HASH = content_hash(
    _EXTERNAL_IDENTIFIER_SELECTION_IMPLEMENTATION_SPEC_V2
)
_LISTING_COVERAGE_SELECTION_IMPLEMENTATION_HASH = content_hash(
    _LISTING_COVERAGE_SELECTION_IMPLEMENTATION_SPEC_V1
)
_LISTING_TERMINATION_SELECTION_IMPLEMENTATION_HASH = content_hash(
    _LISTING_TERMINATION_SELECTION_IMPLEMENTATION_SPEC_V2
)
_LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_HASH = content_hash(
    _LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_SPEC_V2
)


def resolve_identity_assignment(
    subject: IdentityAssignmentSubjectV1,
    assignments: Sequence[IdentityAssignmentVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[str, AvailabilityEvidenceV1],
    *,
    equivalence_resolution: IdentityResolutionResultV1 | None = None,
    equivalence_proof: CutoffSelectionProofV1 | None = None,
) -> IdentityAssignmentResolutionResultV1:
    """Resolve one source key without minting or guessing an identity."""
    if query.purpose is not M1bSelectionPurpose.IDENTITY_RESOLUTION:
        raise DatasetValidationError.single("identity_resolution_purpose_required")
    if query.subject_hash != content_hash(subject):
        raise DatasetValidationError.single("identity_subject_hash_mismatch")
    if query.policy_id != policy.policy_id or query.policy_hash != content_hash(policy):
        raise DatasetValidationError.single("identity_policy_mismatch")
    _require_validated_assignment_dataset(
        assignments,
        manifest,
        decision,
        identity_bundle,
    )

    candidates = tuple(
        assignment
        for assignment in assignments
        if assignment.source_namespace == subject.source_namespace
        and assignment.source_key == subject.source_key
        and identity_reference(assignment.identity).kind is subject.identity_kind
    )
    chains: dict[object, list[IdentityAssignmentVersionV1]] = defaultdict(list)
    for candidate in candidates:
        chains[candidate.revision.logical_record_id].append(candidate)

    selections = []
    records_by_hash = {content_hash(item): item for item in candidates}
    selected_records: list[IdentityAssignmentVersionV1] = []
    for chain in chains.values():
        projections = tuple(
            AssertionVersionProjectionV1(
                revision=item.revision, record_hash=content_hash(item)
            )
            for item in chain
        )
        selection = _select_identity_chain(
            projections, query, policy, retained_evidence
        )
        selections.append(selection)
        if selection.selected_record_hash is not None:
            selected_records.append(records_by_hash[selection.selected_record_hash])

    proof = build_cutoff_selection_proof(
        query,
        tuple(selections),
        manifest,
        decision,
        (identity_bundle,),
        "14d46d84be838d1c08c710f5d785e1c38887540bb895a86893241f28cc3c9e6f",
    )
    assigned = {
        identity_reference(record.identity)
        for record in selected_records
        if evaluate_interval_at(record.effective_interval, query.evaluation_time)
        is IntervalStatus.ACTIVE
        and record.assignment_effect is IdentityAssignmentEffect.ASSIGNED
    }
    assigned.difference_update(
        identity_reference(record.identity)
        for record in selected_records
        if evaluate_interval_at(record.effective_interval, query.evaluation_time)
        is IntervalStatus.ACTIVE
        and record.assignment_effect is IdentityAssignmentEffect.UNASSIGNED
    )
    unresolved = any(
        evaluate_interval_at(record.effective_interval, query.evaluation_time)
        is IntervalStatus.INDETERMINATE
        for record in selected_records
    )
    if equivalence_resolution is not None:
        if equivalence_proof is None:
            raise DatasetValidationError.single("equivalence_selection_proof_required")
        assignments_are_resolved = _equivalence_resolves_assignments(
            assigned,
            equivalence_resolution,
            equivalence_proof,
            query,
            identity_bundle,
        )
    else:
        assignments_are_resolved = len(assigned) <= 1
    classification = (
        IdentityResolutionClassification.INDETERMINATE
        if proof.classification is CutoffEligibility.INDETERMINATE
        or unresolved
        or not candidates
        else IdentityResolutionClassification.RESOLVED
        if assignments_are_resolved
        else IdentityResolutionClassification.CONFLICT
    )
    return IdentityAssignmentResolutionResultV1(
        schema_version="1",
        subject=subject,
        assigned_identities=tuple(
            sorted(assigned, key=lambda item: str(item.internal_id))
        ),
        classification=classification,
        reasons=(classification.value,),
        evidence=ResolutionEvidenceV1(
            schema_version="1",
            normalized_query=query,
            normalized_query_hash=content_hash(query),
            considered_record_hashes=proof.considered_record_hashes,
            selected_record_hashes=proof.selected_record_hashes,
            selection_proof_hashes=(content_hash(proof),),
        ),
    )


def resolve_external_identifier(
    namespace: ExternalIdentifierNamespaceV1,
    value: str,
    mappings: Sequence[ExternalIdentifierMappingVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
    *,
    assignments: Sequence[IdentityAssignmentVersionV1],
    assignment_manifest: DatasetManifestV2,
    assignment_decision: DatasetValidationDecisionV2,
    lifecycle_events: Sequence[ListingLifecycleVersionV1],
    lifecycle_manifest: DatasetManifestV2,
    lifecycle_decision: DatasetValidationDecisionV2,
    terminations: Sequence[ListingTerminationVersionV1],
    termination_manifest: DatasetManifestV2,
    termination_decision: DatasetValidationDecisionV2,
) -> ExternalIdentifierResolutionResultV1:
    """Resolve an exact external value without treating it as an identity."""
    if query.purpose is not M1bSelectionPurpose.IDENTITY_RESOLUTION:
        raise DatasetValidationError.single("identity_resolution_purpose_required")
    subject = {"namespace": namespace, "identifier_value": value}
    if query.subject_hash != content_hash(subject):
        raise DatasetValidationError.single("external_identifier_subject_hash_mismatch")
    if query.policy_id != policy.policy_id or query.policy_hash != content_hash(policy):
        raise DatasetValidationError.single("identity_policy_mismatch")
    _require_validated_mapping_dataset(mappings, manifest, decision, identity_bundle)
    _require_exact_assignment_dependency_dataset(
        assignments,
        assignment_manifest,
        assignment_decision,
        identity_bundle,
    )
    candidates = tuple(
        mapping
        for mapping in mappings
        if mapping.namespace == namespace and mapping.identifier_value == value
    )
    mapping_chains: dict[object, list[ExternalIdentifierMappingVersionV1]] = (
        defaultdict(list)
    )
    for candidate in candidates:
        mapping_chains[candidate.revision.logical_record_id].append(candidate)
    records_by_hash = {content_hash(record): record for record in candidates}
    selections: list[AssertionSelectionResultV1] = []
    selected: list[ExternalIdentifierMappingVersionV1] = []
    for mapping_chain in mapping_chains.values():
        selection = _select_identity_chain(
            tuple(
                AssertionVersionProjectionV1(
                    revision=record.revision, record_hash=content_hash(record)
                )
                for record in mapping_chain
            ),
            query,
            policy,
            retained_evidence,
        )
        selections.append(selection)
        if selection.selected_record_hash is not None:
            selected.append(records_by_hash[selection.selected_record_hash])
    proof = build_cutoff_selection_proof(
        query,
        tuple(selections),
        manifest,
        decision,
        (identity_bundle,),
        _EXTERNAL_IDENTIFIER_SELECTION_IMPLEMENTATION_HASH,
    )
    mapping_targets = tuple(
        sorted(
            {mapping.target for mapping in selected},
            key=lambda item: (item.kind.value, str(item.internal_id)),
        )
    )
    assignment_query = _build_assignment_context_query(
        query,
        mapping_targets,
        assignment_manifest,
        assignment_decision,
    )
    assignments_by_target: dict[
        IdentityReferenceV1, dict[object, list[IdentityAssignmentVersionV1]]
    ] = defaultdict(lambda: defaultdict(list))
    for assignment in assignments:
        target = identity_reference(assignment.identity)
        if target in mapping_targets:
            assignments_by_target[target][assignment.revision.logical_record_id].append(
                assignment
            )
    assignment_records_by_hash = {
        content_hash(assignment): assignment for assignment in assignments
    }
    assignment_selections: list[AssertionSelectionResultV1] = []
    selected_assignments: dict[
        IdentityReferenceV1, list[IdentityAssignmentVersionV1]
    ] = defaultdict(list)
    for target in mapping_targets:
        assignment_chains = assignments_by_target.get(target)
        if not assignment_chains:
            raise DatasetValidationError.single("mapping_target_assignment_missing")
        for chain in assignment_chains.values():
            selection = _select_identity_chain(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=assignment.revision,
                        record_hash=content_hash(assignment),
                    )
                    for assignment in chain
                ),
                assignment_query,
                policy,
                retained_evidence,
            )
            if selection.classification is CutoffEligibility.INDETERMINATE:
                raise DatasetValidationError.single(
                    "target_assignment_selection_indeterminate"
                )
            assignment_selections.append(selection)
            if selection.selected_record_hash is None:
                raise DatasetValidationError.single(
                    "mapping_target_assignment_unavailable"
                )
            selected_assignment = assignment_records_by_hash[
                selection.selected_record_hash
            ]
            if (
                selected_assignment.assignment_effect
                is not IdentityAssignmentEffect.ASSIGNED
            ):
                raise DatasetValidationError.single(
                    "mapping_target_assignment_unassigned"
                )
            selected_assignments[target].append(selected_assignment)
    assignment_proof = build_cutoff_selection_proof(
        assignment_query,
        tuple(assignment_selections),
        assignment_manifest,
        assignment_decision,
        (identity_bundle,),
        "63f0408521c6edfcac4cc382ef91a4f0a6cf96cb8d9d3c0e2361d51ae2dd45c7",
    )
    if assignment_proof.classification is CutoffEligibility.INDETERMINATE:
        raise DatasetValidationError.single("target_assignment_selection_indeterminate")
    target_intervals: dict[IdentityReferenceV1, list[TemporalIntervalClaimV1]] = (
        defaultdict(list)
    )
    for target, selected_for_target in selected_assignments.items():
        target_intervals[target].extend(
            assignment.effective_interval for assignment in selected_for_target
        )
    for mapping in selected:
        if _namespace_requires_listing_venue(mapping.namespace):
            for assignment in selected_assignments[mapping.target]:
                if not isinstance(assignment.identity, ListingV1) or (
                    assignment.identity.venue is not mapping.namespace.venue
                ):
                    raise DatasetValidationError.single(
                        "mapping_namespace_venue_mismatch"
                    )
    validate_external_identifier_mappings(
        selected,
        target_intervals={
            target: tuple(intervals) for target, intervals in target_intervals.items()
        },
    )
    lifecycle_proof_hashes = _validate_mapping_lifecycle_bounds(
        selected,
        lifecycle_events,
        lifecycle_manifest,
        lifecycle_decision,
        terminations,
        termination_manifest,
        termination_decision,
        query,
        identity_bundle,
        policy,
        retained_evidence,
    )
    active = tuple(
        record
        for record in selected
        if evaluate_interval_at(record.effective_interval, query.evaluation_time)
        is IntervalStatus.ACTIVE
    )
    asserted = {
        record.target
        for record in active
        if record.mapping_status is MappingStatus.ASSERTED
    }
    indeterminate = (
        proof.classification is CutoffEligibility.INDETERMINATE
        or not candidates
        or any(
            record.mapping_status is MappingStatus.AMBIGUOUS
            or evaluate_interval_at(record.effective_interval, query.evaluation_time)
            is IntervalStatus.INDETERMINATE
            for record in selected
        )
    )
    classification = (
        RecordResolutionClassification.INDETERMINATE
        if indeterminate or not asserted
        else RecordResolutionClassification.CONFLICT
        if len(asserted) > 1
        else RecordResolutionClassification.RESOLVED
    )
    targets = (
        ()
        if classification is RecordResolutionClassification.INDETERMINATE
        else tuple(sorted(asserted, key=lambda item: str(item.internal_id)))
    )
    evidence = ResolutionEvidenceV1(
        schema_version="1",
        normalized_query=query,
        normalized_query_hash=content_hash(query),
        considered_record_hashes=proof.considered_record_hashes,
        selected_record_hashes=proof.selected_record_hashes,
        selection_proof_hashes=(content_hash(proof),),
    )
    reasons = (classification.value,)
    assignment_proof_hashes = (content_hash(assignment_proof),)
    return ExternalIdentifierResolutionResultV1(
        schema_version="1",
        namespace=namespace,
        identifier_value=value,
        targets=targets,
        classification=classification,
        reasons=reasons,
        evidence=evidence,
        target_assignment_proof_hashes=assignment_proof_hashes,
        target_lifecycle_proof_hashes=lifecycle_proof_hashes,
        outcome_binding_hash=external_identifier_resolution_binding_hash(
            namespace,
            value,
            targets,
            classification,
            reasons,
            evidence,
            assignment_proof_hashes,
            lifecycle_proof_hashes,
        ),
    )


def _build_assignment_context_query(
    mapping_query: NormalizedSelectionQueryV1,
    mapping_targets: tuple[IdentityReferenceV1, ...],
    assignment_manifest: DatasetManifestV2,
    assignment_decision: DatasetValidationDecisionV2,
) -> NormalizedSelectionQueryV1:
    """Bind assignment selection to the mapping query and exact requested targets."""
    return NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=mapping_query.purpose,
        information_role=mapping_query.information_role,
        resolution_mode=mapping_query.resolution_mode,
        subject_hash=content_hash({"mapping_targets": mapping_targets}),
        source_manifest_hash=assignment_decision.manifest_hash,
        validation_decision_hash=content_hash(assignment_decision),
        context_bundle_hashes=mapping_query.context_bundle_hashes,
        dataset_role_hash=content_hash(assignment_manifest.dataset_role),
        record_contract_hash=content_hash(
            assignment_manifest.temporal_contract.contract
        ),
        schema_hash=assignment_manifest.schema_definition.schema_hash,
        knowledge_cutoff=mapping_query.knowledge_cutoff,
        evaluation_time=mapping_query.evaluation_time,
        requested_channel=mapping_query.requested_channel,
        policy_id=mapping_query.policy_id,
        policy_hash=mapping_query.policy_hash,
    )


def _validate_mapping_lifecycle_bounds(
    mappings: Sequence[ExternalIdentifierMappingVersionV1],
    lifecycle_events: Sequence[ListingLifecycleVersionV1],
    lifecycle_manifest: DatasetManifestV2,
    lifecycle_decision: DatasetValidationDecisionV2,
    terminations: Sequence[ListingTerminationVersionV1],
    termination_manifest: DatasetManifestV2,
    termination_decision: DatasetValidationDecisionV2,
    parent_query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> tuple[SHA256Hash, ...]:
    """Check known lifetime bounds without requiring a proof of listing activity."""
    listing_targets = tuple(
        sorted(
            {
                record.target
                for record in mappings
                if record.target.kind is IdentityKind.LISTING
            },
            key=lambda target: str(target.internal_id),
        )
    )
    if not listing_targets:
        return ()
    _require_validated_lifecycle_dataset(
        lifecycle_events,
        lifecycle_manifest,
        lifecycle_decision,
        identity_bundle,
    )
    _require_validated_termination_dataset(
        terminations,
        termination_manifest,
        termination_decision,
        identity_bundle,
    )
    proof_hashes: list[SHA256Hash] = []
    for target in listing_targets:
        listing_subject = {"listing_id": target.internal_id}
        lifecycle_query = _build_dependency_query(
            parent_query,
            lifecycle_manifest,
            lifecycle_decision,
            M1bSelectionPurpose.LISTING_LIFECYCLE,
            listing_subject,
        )
        selected_events, lifecycle_proof = _select_records_for_query(
            tuple(
                event
                for event in lifecycle_events
                if event.listing_id == target.internal_id
            ),
            lifecycle_query,
            identity_bundle,
            lifecycle_manifest,
            lifecycle_decision,
            policy,
            retained_evidence,
            _LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_HASH,
        )
        termination_query = _build_dependency_query(
            parent_query,
            termination_manifest,
            termination_decision,
            M1bSelectionPurpose.LISTING_TERMINATION,
            listing_subject,
        )
        termination_candidates = tuple(
            termination
            for termination in terminations
            if termination.listing_id == target.internal_id
        )
        selected_terminations, termination_proof = _select_records_for_query(
            termination_candidates,
            termination_query,
            identity_bundle,
            termination_manifest,
            termination_decision,
            policy,
            retained_evidence,
            _LISTING_TERMINATION_SELECTION_IMPLEMENTATION_HASH,
        )
        validate_listing_terminations(selected_terminations)
        if len(selected_terminations) > 1:
            raise DatasetValidationError.single("multiple_sole_termination_records")
        proof_hashes.extend(
            (content_hash(lifecycle_proof), content_hash(termination_proof))
        )
        validate_listing_lifecycle(selected_events)
        admissions = tuple(
            event
            for event in selected_events
            if event.event_kind is ListingLifecycleEventKind.ADMITTED
        )
        for mapping in (record for record in mappings if record.target == target):
            # Each selected known bound constrains the mapping independently.
            # Missing bounds are not evidence of activity or infinite lifetime.
            for admission in admissions:
                admission_upper = admission.effective_time.upper_bound
                mapping_start = mapping.effective_interval.start.lower_bound
                if admission_upper is not None and (
                    mapping_start is None or mapping_start < admission_upper
                ):
                    raise DatasetValidationError.single(
                        "mapping_interval_outside_target_interval"
                    )
            for termination in selected_terminations:
                termination_lower = termination.effective_time.lower_bound
                mapping_end = mapping.effective_interval.end
                if termination_lower is not None and (
                    mapping_end is None
                    or mapping_end.upper_bound is None
                    or mapping_end.upper_bound > termination_lower
                ):
                    raise DatasetValidationError.single(
                        "mapping_interval_outside_target_interval"
                    )
    return tuple(sorted(set(proof_hashes)))


def _build_dependency_query(
    parent_query: NormalizedSelectionQueryV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    purpose: M1bSelectionPurpose,
    subject: object,
) -> NormalizedSelectionQueryV1:
    """Rebind one parent K/E context to an exact dependent role dataset."""
    return NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=purpose,
        information_role=parent_query.information_role,
        resolution_mode=parent_query.resolution_mode,
        subject_hash=content_hash(subject),
        source_manifest_hash=decision.manifest_hash,
        validation_decision_hash=content_hash(decision),
        context_bundle_hashes=parent_query.context_bundle_hashes,
        dataset_role_hash=content_hash(manifest.dataset_role),
        record_contract_hash=content_hash(manifest.temporal_contract.contract),
        schema_hash=manifest.schema_definition.schema_hash,
        knowledge_cutoff=parent_query.knowledge_cutoff,
        evaluation_time=parent_query.evaluation_time,
        requested_channel=parent_query.requested_channel,
        policy_id=parent_query.policy_id,
        policy_hash=parent_query.policy_hash,
    )


def _authenticate_relationship_dependency(
    assignments: Sequence[IdentityAssignmentVersionV1],
    relationships: Sequence[IdentityRelationshipVersionV1],
    resolution: IdentityResolutionResultV1,
    proof: CutoffSelectionProofV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
    parent_query: NormalizedSelectionQueryV1,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
    *,
    assignment_manifest: DatasetManifestV2,
    assignment_decision: DatasetValidationDecisionV2,
    relationship_subject: IdentityReferenceV1,
    relationship_kind: IdentityRelationshipKind,
    expected_right: IdentityReferenceV1 | None,
    missing_code: str,
    required_boundary: TemporalBoundaryClaimV1 | None = None,
) -> tuple[SHA256Hash, ...]:
    """Authenticate selected identity relationships before they authorize a result."""
    _require_exact_assignment_dependency_dataset(
        assignments,
        assignment_manifest,
        assignment_decision,
        identity_bundle,
    )
    _require_validated_relationship_dataset(
        relationships, manifest, decision, identity_bundle
    )
    relationship_query = proof.normalized_query
    if (
        relationship_query.purpose is not M1bSelectionPurpose.IDENTITY_RESOLUTION
        or relationship_query.subject_hash != content_hash(relationship_subject)
    ):
        raise DatasetValidationError.single("relationship_query_subject_mismatch")
    if (
        proof.source_manifest_hash != decision.manifest_hash
        or proof.validation_decision_hash != content_hash(decision)
        or relationship_query.source_manifest_hash != decision.manifest_hash
        or relationship_query.validation_decision_hash != content_hash(decision)
        or relationship_query.dataset_role_hash != content_hash(manifest.dataset_role)
        or relationship_query.record_contract_hash
        != content_hash(manifest.temporal_contract.contract)
        or relationship_query.schema_hash != manifest.schema_definition.schema_hash
    ):
        raise DatasetValidationError.single("relationship_proof_dataset_mismatch")
    if (
        relationship_query.context_bundle_hashes != parent_query.context_bundle_hashes
        or relationship_query.knowledge_cutoff != parent_query.knowledge_cutoff
        or relationship_query.evaluation_time != parent_query.evaluation_time
        or relationship_query.requested_channel != parent_query.requested_channel
        or relationship_query.policy_id != parent_query.policy_id
        or relationship_query.policy_hash != parent_query.policy_hash
        or relationship_query.resolution_mode is not parent_query.resolution_mode
        or relationship_query.information_role is not parent_query.information_role
    ):
        raise DatasetValidationError.single("relationship_query_context_mismatch")
    if parent_query.context_bundle_hashes != (content_hash(identity_bundle),):
        raise DatasetValidationError.single("relationship_bundle_hash_mismatch")
    if proof.classification is not CutoffEligibility.ELIGIBLE:
        raise DatasetValidationError.single("relationship_proof_not_eligible")

    chains = _relationship_chains_for_subject(relationships, relationship_subject)
    selections = tuple(
        _select_identity_chain(
            tuple(
                AssertionVersionProjectionV1(
                    revision=item.revision, record_hash=content_hash(item)
                )
                for item in chain
            ),
            relationship_query,
            policy,
            retained_evidence,
        )
        for chain in chains.values()
    )
    rebuilt_proof = build_cutoff_selection_proof(
        relationship_query,
        selections,
        manifest,
        decision,
        (identity_bundle,),
        _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    )
    if proof != rebuilt_proof:
        raise DatasetValidationError.single("relationship_proof_replay_mismatch")
    rebuilt_resolution = resolve_identity(
        relationship_subject,
        assignments,
        relationships,
        relationship_query,
        identity_bundle,
        manifest,
        decision,
        policy,
        retained_evidence,
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    if resolution != rebuilt_resolution:
        raise DatasetValidationError.single("relationship_resolution_replay_mismatch")
    proof_hash = content_hash(proof)
    if (
        resolution.subject != relationship_subject
        or resolution.classification is not IdentityResolutionClassification.RESOLVED
        or relationship_subject not in resolution.resolved_identities
        or resolution.identity_bundle_hash != content_hash(identity_bundle)
        or resolution.resolution_mode is not relationship_query.resolution_mode
        or resolution.knowledge_cutoff != relationship_query.knowledge_cutoff
        or resolution.evaluation_time != relationship_query.evaluation_time
        or resolution.requested_channel != relationship_query.requested_channel
        or resolution.policy_id != relationship_query.policy_id
        or resolution.policy_hash != relationship_query.policy_hash
        or resolution.considered_assertion_hashes != proof.considered_record_hashes
        or resolution.selected_assertion_hashes != proof.selected_record_hashes
        or resolution.selection_proof_hashes != (proof_hash,)
    ):
        raise DatasetValidationError.single("relationship_resolution_proof_mismatch")

    records_by_hash = {content_hash(item): item for item in relationships}
    selected = tuple(
        records_by_hash[record_hash]
        for record_hash in proof.selected_record_hashes
        if record_hash in records_by_hash
    )
    matching_hashes = tuple(
        sorted(
            content_hash(item)
            for item in selected
            if item.left == relationship_subject
            and item.relationship_kind is relationship_kind
            and item.resolution_status is ResolutionStatus.RESOLVED
            and (expected_right is None or item.right == expected_right)
            and (
                _interval_contains_boundary(item.effective_interval, required_boundary)
                if required_boundary is not None
                else evaluate_interval_at(
                    item.effective_interval, parent_query.evaluation_time
                )
                is IntervalStatus.ACTIVE
            )
        )
    )
    if expected_right is not None and not matching_hashes:
        raise DatasetValidationError.single(missing_code)
    return matching_hashes


def _interval_contains_boundary(
    interval: TemporalIntervalClaimV1,
    boundary: TemporalBoundaryClaimV1,
) -> bool:
    """Require one relationship interval to cover every possible boundary instant."""
    interval_start = interval.start.upper_bound
    boundary_start = boundary.lower_bound
    boundary_end = boundary.upper_bound
    if (
        interval_start is None
        or boundary_start is None
        or boundary_end is None
        or interval_start > boundary_start
    ):
        return False
    if interval.end is None:
        return True
    interval_end = interval.end.lower_bound
    return interval_end is not None and boundary_end <= interval_end


def _relationship_chains_for_subject(
    relationships: Sequence[IdentityRelationshipVersionV1],
    subject: IdentityReferenceV1,
) -> dict[object, list[IdentityRelationshipVersionV1]]:
    all_chains: dict[object, list[IdentityRelationshipVersionV1]] = defaultdict(list)
    for relationship in relationships:
        all_chains[relationship.revision.logical_record_id].append(relationship)
    return {
        logical_record_id: chain
        for logical_record_id, chain in all_chains.items()
        if any(
            (relation.left.kind is subject.kind and relation.right.kind is subject.kind)
            or subject in {relation.left, relation.right}
            for relation in chain
        )
    }


def resolve_security_classification(
    issuer_id: UUID7,
    security_id: UUID7,
    classifications: Sequence[SecurityClassificationVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
    *,
    identity_assignments: Sequence[IdentityAssignmentVersionV1],
    assignment_manifest: DatasetManifestV2,
    assignment_decision: DatasetValidationDecisionV2,
    identity_relationships: Sequence[IdentityRelationshipVersionV1],
    relationship_resolution: IdentityResolutionResultV1,
    relationship_proof: CutoffSelectionProofV1,
    relationship_manifest: DatasetManifestV2,
    relationship_decision: DatasetValidationDecisionV2,
) -> SecurityClassificationResolutionV1:
    """Resolve sourced classification without converting uncertainty into exclusion."""
    if query.purpose is not M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY:
        raise DatasetValidationError.single("structural_eligibility_purpose_required")
    subject = {"issuer_id": issuer_id, "security_id": security_id}
    if query.subject_hash != content_hash(subject):
        raise DatasetValidationError.single(
            "security_classification_subject_hash_mismatch"
        )
    if query.policy_id != policy.policy_id or query.policy_hash != content_hash(policy):
        raise DatasetValidationError.single("security_classification_policy_mismatch")
    _require_validated_classification_dataset(
        classifications, manifest, decision, identity_bundle
    )
    relationship_hashes = _authenticate_relationship_dependency(
        identity_assignments,
        identity_relationships,
        relationship_resolution,
        relationship_proof,
        relationship_manifest,
        relationship_decision,
        identity_bundle,
        query,
        policy,
        retained_evidence,
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
        relationship_subject=IdentityReferenceV1(
            kind=IdentityKind.ISSUER, internal_id=issuer_id
        ),
        relationship_kind=IdentityRelationshipKind.ISSUER_HAS_SECURITY,
        expected_right=IdentityReferenceV1(
            kind=IdentityKind.SECURITY, internal_id=security_id
        ),
        missing_code="active_issuer_has_security_required",
    )
    candidates = tuple(
        item
        for item in classifications
        if item.issuer_id == issuer_id and item.security_id == security_id
    )
    selected, proof = _select_records_for_query(
        candidates,
        query,
        identity_bundle,
        manifest,
        decision,
        policy,
        retained_evidence,
        "63556c8fbab52bbf201cbb15ac3d7d8cf82e4e1c36158010237b4a3ee96099f6",
    )
    active = tuple(
        item
        for item in selected
        if evaluate_interval_at(item.effective_interval, query.evaluation_time)
        is IntervalStatus.ACTIVE
    )
    uncertain = proof.classification is CutoffEligibility.INDETERMINATE or any(
        evaluate_interval_at(item.effective_interval, query.evaluation_time)
        is IntervalStatus.INDETERMINATE
        for item in selected
    )
    statuses = {_classification_evidence_status(item) for item in active}
    classification = (
        SecurityClassificationStatus.INDETERMINATE
        if (
            uncertain
            or not active
            or SecurityClassificationStatus.INDETERMINATE in statuses
        )
        else SecurityClassificationStatus.CONFLICT
        if len(statuses) != 1
        else next(iter(statuses))
    )
    evidence = _resolution_evidence(query, proof)
    reasons = (classification.value,)
    relationship_resolution_hashes = (content_hash(relationship_resolution),)
    relationship_proof_hashes = (content_hash(relationship_proof),)
    return SecurityClassificationResolutionV1(
        schema_version="1",
        issuer_id=issuer_id,
        security_id=security_id,
        classification=classification,
        reasons=reasons,
        evidence=evidence,
        dependent_identity_resolution_hashes=relationship_resolution_hashes,
        dependent_relationship_proof_hashes=relationship_proof_hashes,
        selected_relationship_record_hashes=relationship_hashes,
        outcome_binding_hash=security_classification_resolution_binding_hash(
            issuer_id,
            security_id,
            classification,
            reasons,
            evidence,
            relationship_resolution_hashes,
            relationship_proof_hashes,
            relationship_hashes,
        ),
    )


def resolve_primary_listing(
    security_id: UUID7,
    methodology_id: str,
    roles: Sequence[ListingRoleVersionV1],
    selected_security_listing_relationships: Sequence[IdentityRelationshipVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
    *,
    identity_assignments: Sequence[IdentityAssignmentVersionV1],
    assignment_manifest: DatasetManifestV2,
    assignment_decision: DatasetValidationDecisionV2,
    relationship_resolution: IdentityResolutionResultV1,
    relationship_proof: CutoffSelectionProofV1,
    relationship_manifest: DatasetManifestV2,
    relationship_decision: DatasetValidationDecisionV2,
) -> PrimaryListingResolutionV1:
    """Resolve one active primary only under the caller-selected methodology."""
    if query.purpose is not M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY:
        raise DatasetValidationError.single("structural_eligibility_purpose_required")
    subject = {"security_id": security_id, "methodology_id": methodology_id}
    if query.subject_hash != content_hash(subject):
        raise DatasetValidationError.single("primary_listing_subject_hash_mismatch")
    if query.policy_id != policy.policy_id or query.policy_hash != content_hash(policy):
        raise DatasetValidationError.single("primary_listing_policy_mismatch")
    _require_validated_listing_role_dataset(roles, manifest, decision, identity_bundle)
    candidates = tuple(
        item
        for item in roles
        if item.security_id == security_id and item.methodology_id == methodology_id
    )
    selected, proof = _select_records_for_query(
        candidates,
        query,
        identity_bundle,
        manifest,
        decision,
        policy,
        retained_evidence,
        "59bde8a0eec2de51e6be6399081742fe6825910044395f4023989cc87b15475c",
    )
    validate_listing_roles(selected)
    active = tuple(
        item
        for item in selected
        if evaluate_interval_at(item.effective_interval, query.evaluation_time)
        is IntervalStatus.ACTIVE
    )
    indeterminate = proof.classification is CutoffEligibility.INDETERMINATE or any(
        (status := evaluate_interval_at(item.effective_interval, query.evaluation_time))
        is IntervalStatus.INDETERMINATE
        or (status is IntervalStatus.ACTIVE and item.role is ListingRole.INDETERMINATE)
        for item in selected
    )
    primaries = tuple(item for item in active if item.role is ListingRole.PRIMARY)
    relationship_hashes = _authenticate_relationship_dependency(
        identity_assignments,
        selected_security_listing_relationships,
        relationship_resolution,
        relationship_proof,
        relationship_manifest,
        relationship_decision,
        identity_bundle,
        query,
        policy,
        retained_evidence,
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
        relationship_subject=IdentityReferenceV1(
            kind=IdentityKind.SECURITY, internal_id=security_id
        ),
        relationship_kind=IdentityRelationshipKind.SECURITY_HAS_LISTING,
        expected_right=None,
        missing_code="active_security_has_listing_required",
    )
    relationships_by_hash = {
        content_hash(item): item for item in selected_security_listing_relationships
    }
    linked_listing_ids = {
        relationships_by_hash[record_hash].right.internal_id
        for record_hash in relationship_hashes
    }
    if not {item.listing_id for item in active}.issubset(linked_listing_ids):
        raise DatasetValidationError.single("active_security_has_listing_required")
    if indeterminate or len(primaries) != 1:
        classification = RecordResolutionClassification.INDETERMINATE
        listing_id = None
        selected_role_hash = None
    else:
        primary = primaries[0]
        relationship_hashes = tuple(
            record_hash
            for record_hash in relationship_hashes
            if relationships_by_hash[record_hash].right.internal_id
            == primary.listing_id
        )
        classification = RecordResolutionClassification.RESOLVED
        listing_id = primary.listing_id
        selected_role_hash = content_hash(primary)
    evidence = _resolution_evidence(query, proof)
    reasons = (classification.value,)
    relationship_resolution_hashes = (content_hash(relationship_resolution),)
    relationship_proof_hashes = (content_hash(relationship_proof),)
    return PrimaryListingResolutionV1(
        schema_version="1",
        security_id=security_id,
        methodology_id=methodology_id,
        listing_id=listing_id,
        classification=classification,
        reasons=reasons,
        evidence=evidence,
        selected_role_record_hash=selected_role_hash,
        dependent_identity_resolution_hashes=relationship_resolution_hashes,
        dependent_relationship_proof_hashes=relationship_proof_hashes,
        selected_relationship_record_hashes=relationship_hashes,
        outcome_binding_hash=primary_listing_resolution_binding_hash(
            security_id,
            methodology_id,
            listing_id,
            classification,
            reasons,
            evidence,
            selected_role_hash,
            relationship_resolution_hashes,
            relationship_proof_hashes,
            relationship_hashes,
        ),
    )


def resolve_listing_history_coverage(
    listing_id: UUID7,
    coverage_versions: Sequence[ListingHistoryCoverageVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> ListingHistoryCoverageResolutionV1:
    """Select explicit lifecycle-history coverage without inferring completeness."""
    _require_listing_query(
        listing_id,
        query,
        policy,
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        "coverage",
    )
    _require_validated_coverage_dataset(
        coverage_versions,
        manifest,
        decision,
        identity_bundle,
    )
    candidates = tuple(
        record for record in coverage_versions if record.listing_id == listing_id
    )
    selected, proof = _select_records_for_query(
        candidates,
        query,
        identity_bundle,
        manifest,
        decision,
        policy,
        retained_evidence,
        _LISTING_COVERAGE_SELECTION_IMPLEMENTATION_HASH,
    )
    selected_record = selected[0] if len(selected) == 1 else None
    if (
        proof.classification is CutoffEligibility.INDETERMINATE
        or selected_record is None
        or (
            selected_record.coverage_status is ListingHistoryCoverageStatus.COMPLETE
            and selected_record.complete_through.shape is BoundaryShape.UNKNOWN
        )
    ):
        status = ListingHistoryCoverageStatus.UNKNOWN
        complete_through = _unknown_temporal_boundary()
        selected_hash = None
    else:
        status = selected_record.coverage_status
        complete_through = selected_record.complete_through
        selected_hash = content_hash(selected_record)
    evidence = _resolution_evidence(query, proof)
    reasons = (status.value,)
    return ListingHistoryCoverageResolutionV1(
        schema_version="1",
        listing_id=listing_id,
        status=status,
        complete_through=complete_through,
        reasons=reasons,
        evidence=evidence,
        selected_coverage_record_hash=selected_hash,
        outcome_binding_hash=listing_history_coverage_resolution_binding_hash(
            listing_id,
            status,
            complete_through,
            reasons,
            evidence,
            selected_hash,
        ),
    )


def resolve_listing_termination(
    listing_id: UUID7,
    terminations: Sequence[ListingTerminationVersionV1],
    coverage: ListingHistoryCoverageResolutionV1,
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
    *,
    coverage_versions: Sequence[ListingHistoryCoverageVersionV1],
    coverage_manifest: DatasetManifestV2,
    coverage_decision: DatasetValidationDecisionV2,
    identity_relationships: Sequence[IdentityRelationshipVersionV1] = (),
    relationship_resolution: IdentityResolutionResultV1 | None = None,
    relationship_proof: CutoffSelectionProofV1 | None = None,
    relationship_manifest: DatasetManifestV2 | None = None,
    relationship_decision: DatasetValidationDecisionV2 | None = None,
    identity_assignments: Sequence[IdentityAssignmentVersionV1] = (),
    assignment_manifest: DatasetManifestV2 | None = None,
    assignment_decision: DatasetValidationDecisionV2 | None = None,
) -> ListingTerminationResolutionV1:
    """Resolve sole-authority termination after authenticating history coverage."""
    _require_listing_query(
        listing_id,
        query,
        policy,
        M1bSelectionPurpose.LISTING_TERMINATION,
        "termination",
    )
    _require_dependent_query_context(
        coverage.evidence.normalized_query,
        query,
        identity_bundle,
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        "coverage",
    )
    rebuilt_coverage = resolve_listing_history_coverage(
        listing_id,
        coverage_versions,
        coverage.evidence.normalized_query,
        identity_bundle,
        coverage_manifest,
        coverage_decision,
        policy,
        retained_evidence,
    )
    if rebuilt_coverage != coverage:
        raise DatasetValidationError.single("coverage_resolution_replay_mismatch")
    _require_validated_termination_dataset(
        terminations,
        manifest,
        decision,
        identity_bundle,
    )
    candidates = tuple(
        record for record in terminations if record.listing_id == listing_id
    )
    selected, proof = _select_records_for_query(
        candidates,
        query,
        identity_bundle,
        manifest,
        decision,
        policy,
        retained_evidence,
        _LISTING_TERMINATION_SELECTION_IMPLEMENTATION_HASH,
    )
    validate_listing_terminations(selected)
    selected_record = selected[0] if len(selected) == 1 else None
    successor_hashes: tuple[SHA256Hash, ...] = ()
    relationship_resolution_hashes: tuple[SHA256Hash, ...] = ()
    relationship_proof_hashes: tuple[SHA256Hash, ...] = ()
    boundary_status = (
        None
        if selected_record is None
        else evaluate_boundary_at(selected_record.effective_time, query.evaluation_time)
    )
    if proof.classification is CutoffEligibility.INDETERMINATE:
        status = ListingTerminationStatus.INDETERMINATE
    elif boundary_status is EffectiveTimeStatus.EFFECTIVE:
        status = ListingTerminationStatus.TERMINATED
    elif boundary_status is EffectiveTimeStatus.INDETERMINATE:
        status = ListingTerminationStatus.INDETERMINATE
    elif _coverage_is_complete_through(coverage, query.evaluation_time):
        status = ListingTerminationStatus.NOT_TERMINATED
    else:
        status = ListingTerminationStatus.INDETERMINATE
    if (
        status is ListingTerminationStatus.TERMINATED
        and selected_record is not None
        and selected_record.successor_relationship_ids
    ):
        successor_hashes = _authenticate_termination_successors(
            listing_id,
            selected_record,
            identity_relationships,
            relationship_resolution,
            relationship_proof,
            relationship_manifest,
            relationship_decision,
            identity_assignments,
            assignment_manifest,
            assignment_decision,
            identity_bundle,
            query,
            policy,
            retained_evidence,
        )
        assert relationship_resolution is not None
        assert relationship_proof is not None
        relationship_resolution_hashes = (content_hash(relationship_resolution),)
        relationship_proof_hashes = (content_hash(relationship_proof),)
    selected_version_id = (
        selected_record.revision.record_version_id
        if status is ListingTerminationStatus.TERMINATED and selected_record is not None
        else None
    )
    selected_record_hash = (
        content_hash(selected_record)
        if status is ListingTerminationStatus.TERMINATED and selected_record is not None
        else None
    )
    evidence = _resolution_evidence(query, proof)
    reasons = (
        (status.value, "last_regular_trade_time_unknown")
        if selected_record is not None
        and selected_record.last_regular_trade_time.shape is BoundaryShape.UNKNOWN
        else (status.value,)
    )
    coverage_hash = content_hash(coverage)
    return ListingTerminationResolutionV1(
        schema_version="1",
        listing_id=listing_id,
        status=status,
        selected_termination_version_id=selected_version_id,
        reasons=reasons,
        evidence=evidence,
        coverage_resolution_hash=coverage_hash,
        selected_termination_record_hash=selected_record_hash,
        dependent_relationship_resolution_hashes=relationship_resolution_hashes,
        dependent_relationship_proof_hashes=relationship_proof_hashes,
        selected_successor_relationship_record_hashes=successor_hashes,
        outcome_binding_hash=listing_termination_resolution_binding_hash(
            listing_id,
            status,
            selected_version_id,
            reasons,
            evidence,
            coverage_hash,
            selected_record_hash,
            relationship_resolution_hashes,
            relationship_proof_hashes,
            successor_hashes,
        ),
    )


def resolve_listing_lifecycle(
    listing_id: UUID7,
    events: Sequence[ListingLifecycleVersionV1],
    termination: ListingTerminationResolutionV1,
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
    *,
    terminations: Sequence[ListingTerminationVersionV1],
    termination_manifest: DatasetManifestV2,
    termination_decision: DatasetValidationDecisionV2,
    coverage: ListingHistoryCoverageResolutionV1,
    coverage_versions: Sequence[ListingHistoryCoverageVersionV1],
    coverage_manifest: DatasetManifestV2,
    coverage_decision: DatasetValidationDecisionV2,
    identity_relationships: Sequence[IdentityRelationshipVersionV1] = (),
    relationship_resolution: IdentityResolutionResultV1 | None = None,
    relationship_proof: CutoffSelectionProofV1 | None = None,
    relationship_manifest: DatasetManifestV2 | None = None,
    relationship_decision: DatasetValidationDecisionV2 | None = None,
    identity_assignments: Sequence[IdentityAssignmentVersionV1] = (),
    assignment_manifest: DatasetManifestV2 | None = None,
    assignment_decision: DatasetValidationDecisionV2 | None = None,
) -> ListingLifecycleResolutionV1:
    """Compose event state only after replaying coverage and termination proofs."""
    _require_listing_query(
        listing_id,
        query,
        policy,
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        "lifecycle",
    )
    _require_dependent_query_context(
        termination.evidence.normalized_query,
        query,
        identity_bundle,
        M1bSelectionPurpose.LISTING_TERMINATION,
        "termination",
    )
    rebuilt_termination = resolve_listing_termination(
        listing_id,
        terminations,
        coverage,
        termination.evidence.normalized_query,
        identity_bundle,
        termination_manifest,
        termination_decision,
        policy,
        retained_evidence,
        coverage_versions=coverage_versions,
        coverage_manifest=coverage_manifest,
        coverage_decision=coverage_decision,
        identity_relationships=identity_relationships,
        relationship_resolution=relationship_resolution,
        relationship_proof=relationship_proof,
        relationship_manifest=relationship_manifest,
        relationship_decision=relationship_decision,
        identity_assignments=identity_assignments,
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    if rebuilt_termination != termination:
        raise DatasetValidationError.single("termination_resolution_replay_mismatch")
    _require_validated_lifecycle_dataset(events, manifest, decision, identity_bundle)
    candidates = tuple(event for event in events if event.listing_id == listing_id)
    selected, proof = _select_records_for_query(
        candidates,
        query,
        identity_bundle,
        manifest,
        decision,
        policy,
        retained_evidence,
        _LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_HASH,
    )
    validate_listing_lifecycle(selected)
    transfer_hashes: tuple[SHA256Hash, ...] = ()
    relationship_resolution_hashes: tuple[SHA256Hash, ...] = ()
    relationship_proof_hashes: tuple[SHA256Hash, ...] = ()
    transfers = tuple(
        event
        for event in selected
        if event.event_kind is ListingLifecycleEventKind.VENUE_TRANSFER
    )
    if termination.status is ListingTerminationStatus.TERMINATED:
        status = ListingLifecycleStatus.TERMINATED
    elif termination.status is ListingTerminationStatus.INDETERMINATE:
        status = ListingLifecycleStatus.INDETERMINATE
    elif proof.classification is CutoffEligibility.INDETERMINATE:
        status = ListingLifecycleStatus.INDETERMINATE
    else:
        statuses = tuple(
            (event, evaluate_boundary_at(event.effective_time, query.evaluation_time))
            for event in selected
        )
        if any(
            boundary_status is EffectiveTimeStatus.INDETERMINATE
            for _, boundary_status in statuses
        ) or _has_uncertain_effective_event_order(
            tuple(
                event
                for event, boundary_status in statuses
                if boundary_status is EffectiveTimeStatus.EFFECTIVE
            )
        ):
            status = ListingLifecycleStatus.INDETERMINATE
        else:
            effective = tuple(
                sorted(
                    (
                        event
                        for event, boundary_status in statuses
                        if boundary_status is EffectiveTimeStatus.EFFECTIVE
                    ),
                    key=_effective_event_sort_key,
                )
            )
            status = _lifecycle_status_from_effective_events(effective)
    effective_transfers = tuple(
        transfer
        for transfer in transfers
        if evaluate_boundary_at(transfer.effective_time, query.evaluation_time)
        is EffectiveTimeStatus.EFFECTIVE
    )
    if effective_transfers:
        transfer_hashes = _authenticate_listing_transfer(
            listing_id,
            effective_transfers[0],
            terminations,
            termination,
            identity_relationships,
            relationship_resolution,
            relationship_proof,
            relationship_manifest,
            relationship_decision,
            identity_assignments,
            assignment_manifest,
            assignment_decision,
            identity_bundle,
            query,
            policy,
            retained_evidence,
        )
        assert relationship_resolution is not None
        assert relationship_proof is not None
        relationship_resolution_hashes = (content_hash(relationship_resolution),)
        relationship_proof_hashes = (content_hash(relationship_proof),)
    evidence = _resolution_evidence(query, proof)
    reasons = (status.value,)
    termination_hash = content_hash(termination)
    selected_termination_version_id = (
        termination.selected_termination_version_id
        if status is ListingLifecycleStatus.TERMINATED
        else None
    )
    return ListingLifecycleResolutionV1(
        schema_version="1",
        listing_id=listing_id,
        status=status,
        selected_termination_version_id=selected_termination_version_id,
        termination_resolution_hash=termination_hash,
        reasons=reasons,
        evidence=evidence,
        dependent_relationship_resolution_hashes=relationship_resolution_hashes,
        dependent_relationship_proof_hashes=relationship_proof_hashes,
        selected_transfer_relationship_record_hashes=transfer_hashes,
        outcome_binding_hash=listing_lifecycle_resolution_binding_hash(
            listing_id,
            status,
            selected_termination_version_id,
            termination_hash,
            reasons,
            evidence,
            relationship_resolution_hashes,
            relationship_proof_hashes,
            transfer_hashes,
        ),
    )


def _require_listing_query(
    listing_id: UUID7,
    query: NormalizedSelectionQueryV1,
    policy: AvailabilityPolicyV1,
    purpose: M1bSelectionPurpose,
    label: str,
) -> None:
    if query.purpose is not purpose:
        raise DatasetValidationError.single(f"{label}_purpose_mismatch")
    if query.subject_hash != content_hash({"listing_id": listing_id}):
        raise DatasetValidationError.single(f"{label}_subject_hash_mismatch")
    if query.policy_id != policy.policy_id or query.policy_hash != content_hash(policy):
        raise DatasetValidationError.single(f"{label}_policy_mismatch")


def _require_dependent_query_context(
    dependent: NormalizedSelectionQueryV1,
    parent: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    purpose: M1bSelectionPurpose,
    label: str,
) -> None:
    if (
        dependent.purpose is not purpose
        or dependent.subject_hash != parent.subject_hash
        or dependent.context_bundle_hashes != parent.context_bundle_hashes
        or dependent.context_bundle_hashes != (content_hash(identity_bundle),)
        or dependent.knowledge_cutoff != parent.knowledge_cutoff
        or dependent.evaluation_time != parent.evaluation_time
        or dependent.requested_channel != parent.requested_channel
        or dependent.policy_id != parent.policy_id
        or dependent.policy_hash != parent.policy_hash
        or dependent.resolution_mode is not parent.resolution_mode
        or dependent.information_role is not parent.information_role
    ):
        raise DatasetValidationError.single(f"{label}_resolution_context_mismatch")


def _unknown_temporal_boundary() -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.UNKNOWN,
        lower_bound=None,
        upper_bound=None,
        source_precision=SourcePrecision.UNKNOWN,
        source_time_label=None,
        source_timezone=None,
        evidence_reference=None,
    )


def _coverage_is_complete_through(
    coverage: ListingHistoryCoverageResolutionV1,
    evaluation_time: UTCDateTime,
) -> bool:
    if coverage.status is not ListingHistoryCoverageStatus.COMPLETE:
        return False
    boundary = coverage.complete_through.lower_bound
    return bool(boundary is not None and boundary >= evaluation_time)


def _require_relationship_arguments(
    relationship_resolution: IdentityResolutionResultV1 | None,
    relationship_proof: CutoffSelectionProofV1 | None,
    relationship_manifest: DatasetManifestV2 | None,
    relationship_decision: DatasetValidationDecisionV2 | None,
    identity_assignments: Sequence[IdentityAssignmentVersionV1],
    assignment_manifest: DatasetManifestV2 | None,
    assignment_decision: DatasetValidationDecisionV2 | None,
    code: str,
) -> tuple[
    IdentityResolutionResultV1,
    CutoffSelectionProofV1,
    DatasetManifestV2,
    DatasetValidationDecisionV2,
    Sequence[IdentityAssignmentVersionV1],
    DatasetManifestV2,
    DatasetValidationDecisionV2,
]:
    if (
        relationship_resolution is None
        or relationship_proof is None
        or relationship_manifest is None
        or relationship_decision is None
        or not identity_assignments
        or assignment_manifest is None
        or assignment_decision is None
    ):
        raise DatasetValidationError.single(code)
    return (
        relationship_resolution,
        relationship_proof,
        relationship_manifest,
        relationship_decision,
        identity_assignments,
        assignment_manifest,
        assignment_decision,
    )


def _authenticate_termination_successors(
    listing_id: UUID7,
    termination: ListingTerminationVersionV1,
    relationships: Sequence[IdentityRelationshipVersionV1],
    relationship_resolution: IdentityResolutionResultV1 | None,
    relationship_proof: CutoffSelectionProofV1 | None,
    relationship_manifest: DatasetManifestV2 | None,
    relationship_decision: DatasetValidationDecisionV2 | None,
    identity_assignments: Sequence[IdentityAssignmentVersionV1],
    assignment_manifest: DatasetManifestV2 | None,
    assignment_decision: DatasetValidationDecisionV2 | None,
    identity_bundle: ValidatedDatasetBundleV1,
    query: NormalizedSelectionQueryV1,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> tuple[SHA256Hash, ...]:
    (
        resolution,
        proof,
        manifest,
        decision,
        assignments,
        assignments_manifest,
        assignments_decision,
    ) = _require_relationship_arguments(
        relationship_resolution,
        relationship_proof,
        relationship_manifest,
        relationship_decision,
        identity_assignments,
        assignment_manifest,
        assignment_decision,
        "successor_relationship_proof_required",
    )
    if resolution.subject.kind is not IdentityKind.SECURITY:
        raise DatasetValidationError.single("successor_relationship_subject_mismatch")
    _authenticate_relationship_dependency(
        assignments,
        relationships,
        resolution,
        proof,
        manifest,
        decision,
        identity_bundle,
        query,
        policy,
        retained_evidence,
        assignment_manifest=assignments_manifest,
        assignment_decision=assignments_decision,
        relationship_subject=resolution.subject,
        relationship_kind=IdentityRelationshipKind.SECURITY_HAS_LISTING,
        expected_right=IdentityReferenceV1(
            kind=IdentityKind.LISTING,
            internal_id=listing_id,
        ),
        missing_code="termination_listing_security_relationship_required",
        required_boundary=termination.effective_time,
    )
    selected_by_hash = {
        content_hash(relationship): relationship for relationship in relationships
    }
    selected = tuple(
        selected_by_hash[record_hash]
        for record_hash in proof.selected_record_hashes
        if record_hash in selected_by_hash
    )
    wanted = set(termination.successor_relationship_ids)
    matching = tuple(
        sorted(
            content_hash(relationship)
            for relationship in selected
            if relationship.revision.logical_record_id in wanted
            and relationship.relationship_kind
            in {
                IdentityRelationshipKind.SUCCESSOR_OF,
                IdentityRelationshipKind.REORGANIZED_FROM,
            }
            and relationship.resolution_status is ResolutionStatus.RESOLVED
            and relationship.right == resolution.subject
            and _interval_contains_boundary(
                relationship.effective_interval,
                termination.effective_time,
            )
        )
    )
    matched_ids = {
        selected_by_hash[record_hash].revision.logical_record_id
        for record_hash in matching
    }
    if matched_ids != wanted:
        raise DatasetValidationError.single("successor_relationship_not_selected")
    return matching


def _authenticate_listing_transfer(
    listing_id: UUID7,
    transfer: ListingLifecycleVersionV1,
    terminations: Sequence[ListingTerminationVersionV1],
    termination: ListingTerminationResolutionV1,
    relationships: Sequence[IdentityRelationshipVersionV1],
    relationship_resolution: IdentityResolutionResultV1 | None,
    relationship_proof: CutoffSelectionProofV1 | None,
    relationship_manifest: DatasetManifestV2 | None,
    relationship_decision: DatasetValidationDecisionV2 | None,
    identity_assignments: Sequence[IdentityAssignmentVersionV1],
    assignment_manifest: DatasetManifestV2 | None,
    assignment_decision: DatasetValidationDecisionV2 | None,
    identity_bundle: ValidatedDatasetBundleV1,
    query: NormalizedSelectionQueryV1,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> tuple[SHA256Hash, ...]:
    termination_by_hash = {content_hash(record): record for record in terminations}
    selected_terminations = tuple(
        termination_by_hash[record_hash]
        for record_hash in termination.evidence.selected_record_hashes
        if record_hash in termination_by_hash
    )
    if (
        len(selected_terminations) != 1
        or selected_terminations[0].reason
        is not ListingTerminationReason.VENUE_TRANSFER
        or selected_terminations[0].effective_time != transfer.effective_time
    ):
        raise DatasetValidationError.single("matching_transfer_termination_required")
    (
        resolution,
        proof,
        manifest,
        decision,
        assignments,
        assignments_manifest,
        assignments_decision,
    ) = _require_relationship_arguments(
        relationship_resolution,
        relationship_proof,
        relationship_manifest,
        relationship_decision,
        identity_assignments,
        assignment_manifest,
        assignment_decision,
        "listing_transfer_relationship_proof_required",
    )
    if resolution.subject.kind is not IdentityKind.SECURITY:
        raise DatasetValidationError.single("listing_transfer_same_security_required")
    old_hashes = _authenticate_relationship_dependency(
        assignments,
        relationships,
        resolution,
        proof,
        manifest,
        decision,
        identity_bundle,
        query,
        policy,
        retained_evidence,
        assignment_manifest=assignments_manifest,
        assignment_decision=assignments_decision,
        relationship_subject=resolution.subject,
        relationship_kind=IdentityRelationshipKind.SECURITY_HAS_LISTING,
        expected_right=IdentityReferenceV1(
            kind=IdentityKind.LISTING,
            internal_id=listing_id,
        ),
        missing_code="listing_transfer_same_security_required",
        required_boundary=transfer.effective_time,
    )
    assert transfer.related_listing_id is not None
    selected_by_hash = {
        content_hash(relationship): relationship for relationship in relationships
    }
    transfer_upper = transfer.effective_time.upper_bound

    def starts_at_or_after_transfer(
        relationship: IdentityRelationshipVersionV1,
    ) -> bool:
        relationship_start = relationship.effective_interval.start.lower_bound
        return bool(
            relationship_start is not None
            and transfer_upper is not None
            and relationship_start >= transfer_upper
        )

    new_hashes = tuple(
        sorted(
            record_hash
            for record_hash in proof.selected_record_hashes
            if record_hash in selected_by_hash
            and selected_by_hash[record_hash].left == resolution.subject
            and selected_by_hash[record_hash].right
            == IdentityReferenceV1(
                kind=IdentityKind.LISTING,
                internal_id=transfer.related_listing_id,
            )
            and selected_by_hash[record_hash].relationship_kind
            is IdentityRelationshipKind.SECURITY_HAS_LISTING
            and selected_by_hash[record_hash].resolution_status
            is ResolutionStatus.RESOLVED
            and starts_at_or_after_transfer(selected_by_hash[record_hash])
        )
    )
    if not new_hashes:
        raise DatasetValidationError.single("listing_transfer_same_security_required")
    return tuple(sorted((*old_hashes, *new_hashes)))


def _effective_event_sort_key(event: ListingLifecycleVersionV1) -> UTCDateTime:
    assert event.effective_time.upper_bound is not None
    return event.effective_time.upper_bound


def _has_uncertain_effective_event_order(
    events: Sequence[ListingLifecycleVersionV1],
) -> bool:
    ordered = sorted(events, key=_effective_event_sort_key)
    for index, left in enumerate(ordered):
        assert left.effective_time.upper_bound is not None
        for right in ordered[index + 1 :]:
            assert right.effective_time.lower_bound is not None
            if left.effective_time.upper_bound > right.effective_time.lower_bound:
                return True
    return False


def _lifecycle_status_from_effective_events(
    events: Sequence[ListingLifecycleVersionV1],
) -> ListingLifecycleStatus:
    if not any(
        event.event_kind is ListingLifecycleEventKind.FIRST_REGULAR_TRADE
        for event in events
    ):
        return ListingLifecycleStatus.NOT_YET_LISTED
    status = ListingLifecycleStatus.ACTIVE
    for event in events:
        if event.event_kind is ListingLifecycleEventKind.SUSPENDED:
            status = ListingLifecycleStatus.SUSPENDED
        elif event.event_kind is ListingLifecycleEventKind.RESUMED:
            status = ListingLifecycleStatus.ACTIVE
    return status


def _classification_evidence_status(
    record: SecurityClassificationVersionV1,
) -> SecurityClassificationStatus:
    if (
        record.issuer_form is IssuerForm.UNKNOWN
        or record.instrument_form is InstrumentForm.UNKNOWN
        or record.domestic_status is DomesticStatus.INDETERMINATE
        or any(
            value.value is None
            for value in (
                record.issuer_domicile,
                record.incorporation_country,
                record.share_class_label,
            )
        )
    ):
        return SecurityClassificationStatus.INDETERMINATE
    if (
        record.issuer_form is not IssuerForm.OPERATING_COMPANY
        or record.instrument_form is not InstrumentForm.COMMON_SHARE
        or record.domestic_status is DomesticStatus.FOREIGN
    ):
        return SecurityClassificationStatus.UNSUPPORTED
    return SecurityClassificationStatus.SUPPORTED


class _SelectionRecord(Protocol):
    """Minimal immutable assertion shape shared by local temporal selectors."""

    revision: RevisionEnvelopeV1


def _select_records_for_query[T: _SelectionRecord](
    records: Sequence[T],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
    selection_implementation_hash: SHA256Hash,
) -> tuple[tuple[T, ...], CutoffSelectionProofV1]:
    """Select one causal version per exact logical record and retain its proof."""
    chains: dict[object, list[T]] = defaultdict(list)
    for record in records:
        chains[record.revision.logical_record_id].append(record)
    by_hash = {content_hash(record): record for record in records}
    selections: list[AssertionSelectionResultV1] = []
    selected: list[T] = []
    for chain in chains.values():
        selection = _select_identity_chain(
            tuple(
                AssertionVersionProjectionV1(
                    revision=item.revision, record_hash=content_hash(item)
                )
                for item in chain
            ),
            query,
            policy,
            retained_evidence,
        )
        selections.append(selection)
        if selection.selected_record_hash is not None:
            selected.append(by_hash[selection.selected_record_hash])
    proof = build_cutoff_selection_proof(
        query,
        tuple(selections),
        manifest,
        decision,
        (identity_bundle,),
        selection_implementation_hash,
    )
    return tuple(selected), proof


def _resolution_evidence(
    query: NormalizedSelectionQueryV1, proof: CutoffSelectionProofV1
) -> ResolutionEvidenceV1:
    return ResolutionEvidenceV1(
        schema_version="1",
        normalized_query=query,
        normalized_query_hash=content_hash(query),
        considered_record_hashes=proof.considered_record_hashes,
        selected_record_hashes=proof.selected_record_hashes,
        selection_proof_hashes=(content_hash(proof),),
    )


def _namespace_requires_listing_venue(
    namespace: ExternalIdentifierNamespaceV1,
) -> bool:
    """Return whether namespace semantics require a retained listing venue match."""
    return (
        namespace.kind
        in {
            ExternalIdentifierKind.TICKER,
            ExternalIdentifierKind.EXCHANGE_SYMBOL,
        }
        or namespace.venue is not None
    )


def _equivalence_resolves_assignments(
    assigned: set[IdentityReferenceV1],
    resolution: IdentityResolutionResultV1 | None,
    proof: CutoffSelectionProofV1,
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
) -> bool:
    return bool(
        resolution is not None
        and resolution.classification is IdentityResolutionClassification.RESOLVED
        and set(resolution.resolved_identities) == assigned
        and resolution.subject in assigned
        and proof.classification is CutoffEligibility.ELIGIBLE
        and proof.selected_record_hashes == resolution.selected_assertion_hashes
        and content_hash(proof) in resolution.selection_proof_hashes
        and any(
            member.dataset_role.name == "identity_relationship"
            and member.manifest_hash == proof.source_manifest_hash
            and member.validation_decision_hash == proof.validation_decision_hash
            for member in identity_bundle.members
        )
        and proof.normalized_query.context_bundle_hashes == query.context_bundle_hashes
        and proof.normalized_query.resolution_mode is query.resolution_mode
        and proof.normalized_query.knowledge_cutoff == query.knowledge_cutoff
        and proof.normalized_query.evaluation_time == query.evaluation_time
        and proof.normalized_query.requested_channel == query.requested_channel
        and proof.normalized_query.policy_id == query.policy_id
        and proof.normalized_query.policy_hash == query.policy_hash
        and resolution.identity_bundle_hash == content_hash(identity_bundle)
        and resolution.resolution_mode is query.resolution_mode
        and resolution.knowledge_cutoff == query.knowledge_cutoff
        and resolution.evaluation_time == query.evaluation_time
        and resolution.requested_channel == query.requested_channel
        and resolution.policy_id == query.policy_id
        and resolution.policy_hash == query.policy_hash
    )


def resolve_identity(
    subject: IdentityReferenceV1,
    assignments: Sequence[IdentityAssignmentVersionV1],
    relationships: Sequence[IdentityRelationshipVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[str, AvailabilityEvidenceV1],
    *,
    assignment_manifest: DatasetManifestV2,
    assignment_decision: DatasetValidationDecisionV2,
) -> IdentityResolutionResultV1:
    """Resolve an identity to a deterministic equivalence set."""
    if query.purpose is not M1bSelectionPurpose.IDENTITY_RESOLUTION:
        raise DatasetValidationError.single("identity_resolution_purpose_required")
    if query.subject_hash != content_hash(subject):
        raise DatasetValidationError.single("identity_subject_hash_mismatch")
    if query.policy_id != policy.policy_id or query.policy_hash != content_hash(policy):
        raise DatasetValidationError.single("identity_policy_mismatch")
    _require_exact_validated_records(relationships, decision)
    _require_validated_assignment_dataset(
        assignments,
        assignment_manifest,
        assignment_decision,
        identity_bundle,
    )
    _require_assigned_identity_references(subject, relationships, assignments)

    chains = _relationship_chains_for_subject(relationships, subject)
    candidates = tuple(relation for chain in chains.values() for relation in chain)
    records_by_hash = {content_hash(item): item for item in candidates}
    selections = []
    selected: list[IdentityRelationshipVersionV1] = []
    for chain in chains.values():
        selection = _select_identity_chain(
            tuple(
                AssertionVersionProjectionV1(
                    revision=item.revision, record_hash=content_hash(item)
                )
                for item in chain
            ),
            query,
            policy,
            retained_evidence,
        )
        selections.append(selection)
        if selection.selected_record_hash is not None:
            selected.append(records_by_hash[selection.selected_record_hash])
    proof = build_cutoff_selection_proof(
        query,
        tuple(selections),
        manifest,
        decision,
        (identity_bundle,),
        _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    )
    active = tuple(
        relation
        for relation in selected
        if evaluate_interval_at(relation.effective_interval, query.evaluation_time)
        is IntervalStatus.ACTIVE
    )
    adjacency: dict[IdentityReferenceV1, set[IdentityReferenceV1]] = defaultdict(set)
    for relation in active:
        if (
            relation.relationship_kind is IdentityRelationshipKind.EQUIVALENT_TO
            and relation.resolution_status is ResolutionStatus.RESOLVED
        ):
            adjacency[relation.left].add(relation.right)
            adjacency[relation.right].add(relation.left)
    component = {subject}
    pending = [subject]
    while pending:
        current = pending.pop()
        for neighbor in adjacency[current] - component:
            component.add(neighbor)
            pending.append(neighbor)
    contradiction = any(
        relation.relationship_kind is IdentityRelationshipKind.DISTINCT_FROM
        and relation.resolution_status is ResolutionStatus.RESOLVED
        and relation.left in component
        and relation.right in component
        for relation in active
    )
    uncertain = any(
        relation.resolution_status is not ResolutionStatus.RESOLVED
        or evaluate_interval_at(relation.effective_interval, query.evaluation_time)
        is IntervalStatus.INDETERMINATE
        for relation in selected
    )
    classification = (
        IdentityResolutionClassification.CONFLICT
        if contradiction or _has_directional_cycle(active)
        else IdentityResolutionClassification.INDETERMINATE
        if proof.classification is CutoffEligibility.INDETERMINATE or uncertain
        else IdentityResolutionClassification.RESOLVED
    )
    resolved = (
        ()
        if classification is not IdentityResolutionClassification.RESOLVED
        else tuple(sorted(component, key=lambda item: str(item.internal_id)))
    )
    return IdentityResolutionResultV1(
        schema_version="1",
        subject=subject,
        resolved_identities=resolved,
        classification=classification,
        reasons=(classification.value,),
        identity_bundle_hash=content_hash(identity_bundle),
        resolution_mode=query.resolution_mode,
        knowledge_cutoff=query.knowledge_cutoff,
        evaluation_time=query.evaluation_time,
        requested_channel=query.requested_channel,
        policy_id=query.policy_id,
        policy_hash=query.policy_hash,
        considered_assertion_hashes=proof.considered_record_hashes,
        selected_assertion_hashes=proof.selected_record_hashes,
        selection_proof_hashes=(content_hash(proof),),
    )


def _select_identity_chain(
    projections: tuple[AssertionVersionProjectionV1, ...],
    query: NormalizedSelectionQueryV1,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[str, AvailabilityEvidenceV1],
) -> AssertionSelectionResultV1:
    if query.resolution_mode is ResolutionMode.AS_KNOWN:
        return select_assertion_version(
            projections,
            query.requested_channel,
            policy,
            query.knowledge_cutoff,
            retained_evidence,
        )
    findings = validate_assertion_chain(projections)
    if findings:
        raise DatasetValidationError(findings)
    ordered = tuple(sorted(projections, key=lambda item: item.revision.source_sequence))
    selected = ordered[-1]
    eligible = selected.revision.revision_kind is not RevisionKind.WITHDRAWAL
    return AssertionSelectionResultV1(
        schema_version="1",
        classification=(
            CutoffEligibility.ELIGIBLE if eligible else CutoffEligibility.INELIGIBLE
        ),
        reason=(
            "manifest_current_version" if eligible else "manifest_current_withdrawal"
        ),
        cutoff=query.knowledge_cutoff,
        requested_channel=query.requested_channel,
        policy=policy,
        policy_id=policy.policy_id,
        policy_hash=content_hash(policy),
        considered_versions=ordered,
        considered_record_hashes=tuple(item.record_hash for item in ordered),
        selected_record_hash=selected.record_hash if eligible else None,
    )


def _has_directional_cycle(
    relationships: Sequence[IdentityRelationshipVersionV1],
) -> bool:
    edges: dict[IdentityReferenceV1, set[IdentityReferenceV1]] = defaultdict(set)
    for relationship in relationships:
        if (
            relationship.resolution_status is ResolutionStatus.RESOLVED
            and relationship.relationship_kind
            in {
                IdentityRelationshipKind.SUCCESSOR_OF,
                IdentityRelationshipKind.REORGANIZED_FROM,
            }
        ):
            edges[relationship.left].add(relationship.right)
    visiting: set[IdentityReferenceV1] = set()
    visited: set[IdentityReferenceV1] = set()

    def visit(node: IdentityReferenceV1) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        cyclic = any(visit(neighbor) for neighbor in edges[node])
        visiting.remove(node)
        visited.add(node)
        return cyclic

    return any(visit(node) for node in tuple(edges))


def _require_exact_validated_records(
    records: Sequence[IdentityAssignmentVersionV1 | IdentityRelationshipVersionV1],
    decision: DatasetValidationDecisionV2,
) -> None:
    if {content_hash(record) for record in records} != set(
        decision.validated_record_hashes
    ):
        raise DatasetValidationError.single("identity_record_set_mismatch")


def _require_validated_assignment_dataset(
    assignments: Sequence[IdentityAssignmentVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require assignment provenance to be an exact passing bundle member."""
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single("assignment_validation_not_passing")
    if manifest.dataset_role.name != "identity_assignment":
        raise DatasetValidationError.single("assignment_role_mismatch")
    if decision.manifest_hash != manifest_hash(manifest):
        raise DatasetValidationError.single("assignment_manifest_hash_mismatch")
    if decision.dataset_role_hash != content_hash(manifest.dataset_role):
        raise DatasetValidationError.single("assignment_role_hash_mismatch")
    if not any(
        member.dataset_role == manifest.dataset_role
        and member.manifest_hash == decision.manifest_hash
        and member.validation_decision_hash == content_hash(decision)
        for member in identity_bundle.members
    ):
        raise DatasetValidationError.single("assignment_not_in_context_bundle")
    _require_exact_validated_records(assignments, decision)


def _require_exact_assignment_dependency_dataset(
    assignments: Sequence[IdentityAssignmentVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require exact assignment parsing when records authorize Task 3 results."""
    _require_validated_assignment_dataset(
        assignments,
        manifest,
        decision,
        identity_bundle,
    )
    if (
        decision.validation_scope is not ValidationScope.RECORDS
        or "identity-assignment-v1" not in decision.checked_contracts
        or decision.schema_hash != manifest.schema_definition.schema_hash
        or decision.temporal_contract_hash
        != content_hash(manifest.temporal_contract.contract)
        or not is_exact_identity_role_manifest(manifest)
    ):
        raise DatasetValidationError.single("assignment_schema_or_contract_mismatch")


def _require_validated_mapping_dataset(
    mappings: Sequence[ExternalIdentifierMappingVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require the exact mapping dataset to be a passing identity-bundle member."""
    _require_validated_role_dataset(
        mappings,
        manifest,
        decision,
        identity_bundle,
        "external_identifier_mapping",
        "mapping",
    )


def _require_validated_relationship_dataset(
    relationships: Sequence[IdentityRelationshipVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require exact passing identity-relationship records in the named bundle."""
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single("relationship_validation_not_passing")
    if manifest.dataset_role.name != "identity_relationship":
        raise DatasetValidationError.single("relationship_role_mismatch")
    if decision.manifest_hash != manifest_hash(manifest):
        raise DatasetValidationError.single("relationship_manifest_hash_mismatch")
    if decision.dataset_role_hash != content_hash(manifest.dataset_role):
        raise DatasetValidationError.single("relationship_role_hash_mismatch")
    if (
        decision.validation_scope is not ValidationScope.RECORDS
        or "identity-relationship-v1" not in decision.checked_contracts
        or decision.schema_hash != manifest.schema_definition.schema_hash
        or decision.temporal_contract_hash
        != content_hash(manifest.temporal_contract.contract)
        or not is_exact_identity_role_manifest(manifest)
    ):
        raise DatasetValidationError.single("relationship_schema_or_contract_mismatch")
    if not any(
        member.dataset_role == manifest.dataset_role
        and member.manifest_hash == decision.manifest_hash
        and member.validation_decision_hash == content_hash(decision)
        for member in identity_bundle.members
    ):
        raise DatasetValidationError.single("relationship_not_in_context_bundle")
    record_hashes = tuple(content_hash(item) for item in relationships)
    if len(set(record_hashes)) != len(record_hashes):
        raise DatasetValidationError.single("relationship_duplicate_record_hash")
    if set(record_hashes) != set(decision.validated_record_hashes):
        raise DatasetValidationError.single("relationship_record_set_mismatch")


def _require_validated_classification_dataset(
    classifications: Sequence[SecurityClassificationVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require the exact classification source to be a passing bundle member."""
    _require_validated_role_dataset(
        classifications,
        manifest,
        decision,
        identity_bundle,
        "security_classification",
        "security_classification",
    )


def _require_validated_listing_role_dataset(
    roles: Sequence[ListingRoleVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require the exact primary-role source to be a passing bundle member."""
    _require_validated_role_dataset(
        roles,
        manifest,
        decision,
        identity_bundle,
        "listing_role",
        "listing_role",
    )


def _require_validated_lifecycle_dataset(
    events: Sequence[ListingLifecycleVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require the exact lifecycle-event source, including a valid empty set."""
    _require_validated_role_dataset(
        events,
        manifest,
        decision,
        identity_bundle,
        "listing_lifecycle",
        "listing_lifecycle",
        allow_empty=True,
    )


def _require_validated_termination_dataset(
    terminations: Sequence[ListingTerminationVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require the exact sole-authority termination source."""
    _require_validated_role_dataset(
        terminations,
        manifest,
        decision,
        identity_bundle,
        "listing_termination",
        "listing_termination",
        allow_empty=True,
    )


def _require_validated_coverage_dataset(
    coverage: Sequence[ListingHistoryCoverageVersionV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
) -> None:
    """Require exact listing-history coverage evidence, including absence."""
    _require_validated_role_dataset(
        coverage,
        manifest,
        decision,
        identity_bundle,
        "listing_history_coverage",
        "listing_history_coverage",
        allow_empty=True,
    )


def _require_validated_role_dataset[T](
    records: Sequence[T],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    identity_bundle: ValidatedDatasetBundleV1,
    role: str,
    label: str,
    *,
    allow_empty: bool = False,
) -> None:
    """Enforce manifest, decision, bundle, and exact record-set binding."""
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single(f"{label}_validation_not_passing")
    if manifest.dataset_role.name != role:
        raise DatasetValidationError.single(f"{label}_role_mismatch")
    if decision.manifest_hash != manifest_hash(manifest):
        raise DatasetValidationError.single(f"{label}_manifest_hash_mismatch")
    if decision.dataset_role_hash != content_hash(manifest.dataset_role):
        raise DatasetValidationError.single(f"{label}_role_hash_mismatch")
    checked_contract = f"{role.replace('_', '-')}-v1"
    expected_scope = (
        ValidationScope.RECORDS if records else ValidationScope.MANIFEST_ONLY
    )
    if (
        (not records and not allow_empty)
        or decision.validation_scope is not expected_scope
        or checked_contract not in decision.checked_contracts
        or decision.schema_hash != manifest.schema_definition.schema_hash
        or decision.temporal_contract_hash
        != content_hash(manifest.temporal_contract.contract)
        or not is_exact_typed_role_manifest(manifest)
    ):
        raise DatasetValidationError.single(f"{label}_schema_or_contract_mismatch")
    if not any(
        member.dataset_role == manifest.dataset_role
        and member.manifest_hash == decision.manifest_hash
        and member.validation_decision_hash == content_hash(decision)
        for member in identity_bundle.members
    ):
        raise DatasetValidationError.single(f"{label}_not_in_context_bundle")
    record_hashes = tuple(content_hash(record) for record in records)
    if len(set(record_hashes)) != len(record_hashes):
        raise DatasetValidationError.single(f"{label}_duplicate_record_hash")
    if set(record_hashes) != set(decision.validated_record_hashes):
        raise DatasetValidationError.single(f"{label}_record_set_mismatch")


def _require_assigned_identity_references(
    subject: IdentityReferenceV1,
    relationships: Sequence[IdentityRelationshipVersionV1],
    assignments: Sequence[IdentityAssignmentVersionV1],
) -> None:
    assigned = {identity_reference(record.identity) for record in assignments}
    required = {subject}
    required.update(
        endpoint
        for relationship in relationships
        for endpoint in (relationship.left, relationship.right)
    )
    if not required.issubset(assigned):
        raise DatasetValidationError.single("identity_reference_not_assigned")
