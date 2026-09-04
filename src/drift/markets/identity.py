"""Point-in-time resolution over validated historical identity assertions."""

from collections import defaultdict
from collections.abc import Mapping, Sequence

from drift.datasets.assertions import (
    build_cutoff_selection_proof,
    select_assertion_version,
    validate_assertion_chain,
)
from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import (
    AssertionSelectionResultV1,
    AssertionVersionProjectionV1,
    CutoffSelectionProofV1,
    IntervalStatus,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionEvidenceV1,
    ResolutionMode,
    evaluate_interval_at,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    ValidatedDatasetBundleV1,
    ValidationResult,
)
from drift.domain.manifests import DatasetManifestV2
from drift.domain.revisions import RevisionKind
from drift.domain.securities import (
    IdentityAssignmentEffect,
    IdentityAssignmentResolutionResultV1,
    IdentityAssignmentSubjectV1,
    IdentityAssignmentVersionV1,
    IdentityReferenceV1,
    IdentityRelationshipKind,
    IdentityRelationshipVersionV1,
    IdentityResolutionClassification,
    IdentityResolutionResultV1,
    ResolutionStatus,
    identity_reference,
)
from drift.domain.temporal import (
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
)
from drift.serialization.canonical import content_hash


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

    all_chains: dict[object, list[IdentityRelationshipVersionV1]] = defaultdict(list)
    for relationship in relationships:
        all_chains[relationship.revision.logical_record_id].append(relationship)
    chains = {
        logical_record_id: chain
        for logical_record_id, chain in all_chains.items()
        if any(
            (relation.left.kind is subject.kind and relation.right.kind is subject.kind)
            or subject in {relation.left, relation.right}
            for relation in chain
        )
    }
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
        "bf61c84a232e0d5c11a99b6451f9a43f37f96dab220c1c7036456252394c961d",
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
