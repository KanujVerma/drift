"""Validation and selection helpers for correction-capable assertion datasets."""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from types import MappingProxyType
from uuid import UUID

from pydantic import ValidationError

from drift.datasets.hashing import manifest_hash, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes, verify_partition_bytes
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import (
    AssertionSelectionResultV1,
    AssertionVersionProjectionV1,
    CutoffSelectionProofV1,
    DecisionSelectionReferenceV1,
    InformationRole,
    NormalizedSelectionQueryV1,
    ResolutionMode,
)
from drift.domain.common import UUID7, SHA256Hash
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    FindingSeverity,
    ValidatedDatasetBundleV1,
    ValidatedDatasetMemberV1,
    ValidationFindingV1,
    ValidationResult,
    ValidationRunContextV1,
    ValidationScope,
)
from drift.domain.manifests import DatasetKind, DatasetManifestV2
from drift.domain.revisions import RevisionKind
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
    evaluate_availability,
)
from drift.errors import ArtifactIntegrityError
from drift.serialization.canonical import content_hash

_SUPPORTED_VALIDATOR_VERSION = "1"


def validate_manifest_v2_structure(
    manifest: DatasetManifestV2,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
) -> DatasetValidationDecisionV2:
    """Validate the exact V2 manifest and supplied verified partition bytes."""
    findings: list[ValidationFindingV1] = []
    if context.validator_version != _SUPPORTED_VALIDATOR_VERSION:
        findings.append(_finding("unsupported_validator_version"))
    try:
        DatasetManifestV2.model_validate(manifest.model_dump(mode="python"))
    except ValidationError:
        findings.append(_finding("invalid_manifest_structure"))
    try:
        if manifest.schema_definition.schema_hash != schema_hash(
            manifest.schema_definition
        ):
            findings.append(_finding("schema_hash_mismatch"))
    except AssertionError, KeyError, TypeError, ValueError:
        findings.append(_finding("schema_hash_mismatch"))

    if manifest.dataset_kind is DatasetKind.SOURCE_FACTS:
        if manifest.lineage is not None:
            findings.append(_finding("unexpected_source_lineage"))
    elif manifest.lineage is None:
        findings.append(_finding("missing_derived_lineage"))
    elif manifest.lineage.output_schema_hash != manifest.schema_definition.schema_hash:
        findings.append(_finding("derived_lineage_schema_mismatch"))

    partition_hashes = tuple(
        partition.artifact.content_hash for partition in manifest.partitions
    )
    verified_hashes = tuple(item.content_hash for item in verified_artifacts)
    if len(set(partition_hashes)) != len(partition_hashes) or len(
        set(verified_hashes)
    ) != len(verified_hashes):
        findings.append(_finding("duplicate_artifact_hash"))

    partition_hash_set = set(partition_hashes)
    verified_hash_set = set(verified_hashes)
    for partition in manifest.partitions:
        matches = [
            item
            for item in verified_artifacts
            if item.content_hash == partition.artifact.content_hash
        ]
        if not matches:
            findings.append(_finding("missing_partition_artifact", partition.artifact))
            continue
        if len(matches) != 1:
            continue
        verified = matches[0]
        if verified.byte_size != len(verified.data):
            findings.append(_finding("verified_byte_size_mismatch", partition.artifact))
        if sha256(verified.data).hexdigest() != verified.content_hash:
            findings.append(
                _finding("verified_content_hash_mismatch", partition.artifact)
            )
        try:
            verify_partition_bytes(partition, verified)
        except ArtifactIntegrityError as error:
            code = (
                "partition_byte_size_mismatch"
                if "byte size" in str(error)
                else "partition_content_hash_mismatch"
            )
            findings.append(_finding(code, partition.artifact))
    if verified_hash_set - partition_hash_set:
        findings.append(_finding("undeclared_partition_artifact"))

    canonical_findings = _canonical_findings(findings)
    contract = manifest.temporal_contract.contract
    contract_name = manifest.temporal_contract.kind.value.replace("_", "-")
    return DatasetValidationDecisionV2(
        decision_schema_version="2",
        **context.model_dump(mode="python"),
        manifest_hash=manifest_hash(manifest),
        manifest_schema_version=manifest.manifest_schema_version,
        dataset_role_hash=content_hash(manifest.dataset_role),
        schema_hash=manifest.schema_definition.schema_hash,
        temporal_contract_kind=manifest.temporal_contract.kind,
        temporal_contract_version=contract.contract_version,
        temporal_contract_hash=content_hash(contract),
        validation_scope=ValidationScope.MANIFEST_ONLY,
        result=(
            ValidationResult.FAIL
            if any(
                finding.severity is FindingSeverity.ERROR
                for finding in canonical_findings
            )
            else ValidationResult.PASS
        ),
        validated_artifact_hashes=tuple(sorted(set(verified_hashes))),
        validated_record_hashes=(),
        checked_contracts=tuple(sorted(("dataset-manifest-v2", contract_name))),
        findings=canonical_findings,
    )


def build_validated_dataset_bundle(
    bundle_id: UUID7,
    bundle_version: str,
    created_at: datetime,
    validated_datasets: Sequence[tuple[DatasetManifestV2, DatasetValidationDecisionV2]],
) -> ValidatedDatasetBundleV1:
    """Bind role manifests to the passing decisions that checked them."""
    members: list[ValidatedDatasetMemberV1] = []
    for manifest, decision in validated_datasets:
        if decision.result is not ValidationResult.PASS:
            msg = "validated dataset bundle requires passing decisions"
            raise ValueError(msg)
        if decision.manifest_hash != manifest_hash(manifest):
            msg = "validation decision manifest hash mismatch"
            raise ValueError(msg)
        if decision.dataset_role_hash != content_hash(manifest.dataset_role):
            msg = "validation decision dataset role mismatch"
            raise ValueError(msg)
        if decision.schema_hash != manifest.schema_definition.schema_hash:
            msg = "validation decision schema hash mismatch"
            raise ValueError(msg)
        if decision.temporal_contract_kind is not manifest.temporal_contract.kind:
            msg = "validation decision temporal contract kind mismatch"
            raise ValueError(msg)
        contract = manifest.temporal_contract.contract
        if decision.temporal_contract_version != contract.contract_version:
            msg = "validation decision temporal contract version mismatch"
            raise ValueError(msg)
        if decision.temporal_contract_hash != content_hash(contract):
            msg = "validation decision temporal contract hash mismatch"
            raise ValueError(msg)
        members.append(
            ValidatedDatasetMemberV1(
                dataset_role=manifest.dataset_role,
                manifest_hash=decision.manifest_hash,
                validation_decision_hash=content_hash(decision),
            )
        )
    return ValidatedDatasetBundleV1(
        schema_version="1",
        bundle_id=bundle_id,
        bundle_version=bundle_version,
        members=tuple(members),
        created_at=created_at,
    )


def validate_assertion_chain(
    versions: Sequence[AssertionVersionProjectionV1],
) -> tuple[ValidationFindingV1, ...]:
    """Return deterministic findings for one immutable assertion chain."""
    findings: list[ValidationFindingV1] = []
    version_ids = tuple(item.revision.record_version_id for item in versions)
    record_hashes = tuple(item.record_hash for item in versions)
    if len(set(version_ids)) != len(version_ids):
        findings.append(_finding("duplicate_record_version_id"))
    if len(set(record_hashes)) != len(record_hashes):
        findings.append(_finding("duplicate_record_hash"))
    by_id = {item.revision.record_version_id: item for item in versions}
    roots = tuple(
        item
        for item in versions
        if item.revision.revision_kind is RevisionKind.INITIAL
        and item.revision.supersedes_record_version_id is None
    )
    if not roots:
        findings.append(_finding("missing_initial_root"))
    elif len(roots) > 1:
        findings.append(_finding("multiple_initial_roots"))

    children: Counter[UUID] = Counter()
    for item in versions:
        revision = item.revision
        predecessor_id = revision.supersedes_record_version_id
        if revision.revision_kind is RevisionKind.INITIAL:
            continue
        if predecessor_id is None or predecessor_id not in by_id:
            findings.append(_finding("missing_predecessor"))
            continue
        predecessor = by_id[predecessor_id].revision
        children[predecessor_id] += 1
        if revision.logical_record_id != predecessor.logical_record_id:
            findings.append(_finding("logical_record_id_mismatch"))
        if revision.source_sequence <= predecessor.source_sequence:
            findings.append(_finding("non_increasing_source_sequence"))
        if _has_backward_availability(predecessor.availability, revision.availability):
            findings.append(_finding("backward_availability"))
    if any(count > 1 for count in children.values()):
        findings.append(_finding("branching_revision_chain"))
    if _has_revision_cycle(by_id):
        findings.append(_finding("revision_cycle"))
    return _canonical_findings(findings)


def select_assertion_version(
    versions: Sequence[AssertionVersionProjectionV1],
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
    retained_evidence: Mapping[str, AvailabilityEvidenceV1],
) -> AssertionSelectionResultV1:
    """Select the latest causally and definitely available assertion version."""
    findings = validate_assertion_chain(versions)
    if findings:
        raise DatasetValidationError(findings)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        msg = "cutoff must be timezone-aware"
        raise ValueError(msg)
    cutoff_utc = cutoff.astimezone(UTC)
    ordered = tuple(sorted(versions, key=lambda item: item.revision.source_sequence))
    decisions = {}
    for item in ordered:
        evidence = next(
            (claim for claim in item.revision.availability if claim.channel == channel),
            None,
        )
        decisions[item.revision.record_version_id] = (
            None
            if evidence is None
            else evaluate_availability(
                evidence, channel, policy, cutoff_utc, retained_evidence
            )
        )

    causally_available: set[UUID] = set()
    unresolved: set[UUID] = set()
    eligible: list[AssertionVersionProjectionV1] = []
    for item in ordered:
        revision = item.revision
        decision = decisions[revision.record_version_id]
        if (
            decision is None
            or decision.classification is CutoffEligibility.INDETERMINATE
        ):
            unresolved.add(revision.record_version_id)
            continue
        if decision.classification is not CutoffEligibility.ELIGIBLE:
            continue
        predecessor_id = revision.supersedes_record_version_id
        if predecessor_id is None or predecessor_id in causally_available:
            causally_available.add(revision.record_version_id)
            eligible.append(item)
        elif predecessor_id in unresolved:
            unresolved.add(revision.record_version_id)

    selected = (
        None
        if not eligible
        else max(eligible, key=lambda item: item.revision.source_sequence)
    )
    considered_hashes = tuple(item.record_hash for item in ordered)
    if (
        selected is not None
        and selected.revision.revision_kind is not RevisionKind.WITHDRAWAL
    ):
        return AssertionSelectionResultV1(
            schema_version="1",
            classification=CutoffEligibility.ELIGIBLE,
            reason="latest_definitely_available_version",
            cutoff=cutoff_utc,
            requested_channel=channel,
            policy=policy,
            policy_id=policy.policy_id,
            policy_hash=content_hash(policy),
            considered_versions=ordered,
            considered_record_hashes=considered_hashes,
            selected_record_hash=selected.record_hash,
        )
    if selected is not None:
        return AssertionSelectionResultV1(
            schema_version="1",
            classification=CutoffEligibility.INELIGIBLE,
            reason="latest_available_version_withdrawn",
            cutoff=cutoff_utc,
            requested_channel=channel,
            policy=policy,
            policy_id=policy.policy_id,
            policy_hash=content_hash(policy),
            considered_versions=ordered,
            considered_record_hashes=considered_hashes,
            selected_record_hash=None,
        )
    classification = (
        CutoffEligibility.INDETERMINATE if unresolved else CutoffEligibility.INELIGIBLE
    )
    return AssertionSelectionResultV1(
        schema_version="1",
        classification=classification,
        reason=(
            "availability_not_established"
            if classification is CutoffEligibility.INDETERMINATE
            else "no_version_available_by_cutoff"
        ),
        cutoff=cutoff_utc,
        requested_channel=channel,
        policy=policy,
        policy_id=policy.policy_id,
        policy_hash=content_hash(policy),
        considered_versions=ordered,
        considered_record_hashes=considered_hashes,
        selected_record_hash=None,
    )


def build_cutoff_selection_proof(
    query: NormalizedSelectionQueryV1,
    selections: Sequence[AssertionSelectionResultV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    context_bundles: Sequence[ValidatedDatasetBundleV1],
    selection_implementation_hash: SHA256Hash,
) -> CutoffSelectionProofV1:
    """Build an audit-side proof from exact validated selection results."""
    _validate_query_dataset_binding(query, manifest, decision)
    bundle_hashes = tuple(sorted(content_hash(bundle) for bundle in context_bundles))
    if bundle_hashes != query.context_bundle_hashes:
        raise DatasetValidationError.single("context_bundle_hash_mismatch")
    if not any(
        member.manifest_hash == decision.manifest_hash
        and member.validation_decision_hash == content_hash(decision)
        and member.dataset_role == manifest.dataset_role
        for bundle in context_bundles
        for member in bundle.members
    ):
        raise DatasetValidationError.single("manifest_not_in_context_bundle")
    considered = tuple(
        sorted(
            {
                record_hash
                for selection in selections
                for record_hash in selection.considered_record_hashes
            }
        )
    )
    selected = tuple(
        sorted(
            {
                selection.selected_record_hash
                for selection in selections
                if selection.selected_record_hash is not None
            }
        )
    )
    if not set(considered).issubset(decision.validated_record_hashes):
        raise DatasetValidationError.single("unvalidated_considered_record_hash")
    if any(
        selection.cutoff != query.knowledge_cutoff
        or selection.requested_channel != query.requested_channel
        or selection.policy_id != query.policy_id
        or selection.policy_hash != query.policy_hash
        for selection in selections
    ):
        raise DatasetValidationError.single("selection_query_mismatch")
    if any(
        selection.classification is CutoffEligibility.INDETERMINATE
        for selection in selections
    ):
        classification = CutoffEligibility.INDETERMINATE
    elif selected:
        classification = CutoffEligibility.ELIGIBLE
    else:
        classification = CutoffEligibility.INELIGIBLE
    return CutoffSelectionProofV1(
        schema_version="1",
        source_manifest_hash=query.source_manifest_hash,
        validation_decision_hash=query.validation_decision_hash,
        selection_algorithm="drift-m1b-cutoff-selection-v1",
        selection_implementation_hash=selection_implementation_hash,
        normalized_query=query,
        normalized_query_hash=content_hash(query),
        considered_record_hashes=considered,
        selected_record_hashes=selected
        if classification is CutoffEligibility.ELIGIBLE
        else (),
        classification=classification,
        reasons=tuple(selection.reason for selection in selections)
        or ("no_assertion_chains",),
    )


def decision_reference_from_proof(
    proof: CutoffSelectionProofV1,
) -> DecisionSelectionReferenceV1:
    """Reduce an audit proof to the hashes authorized for decision code."""
    query = proof.normalized_query
    if query.information_role is not InformationRole.DECISION_INFORMATION:
        raise DatasetValidationError.single("decision_information_required")
    if query.resolution_mode is not ResolutionMode.AS_KNOWN:
        raise DatasetValidationError.single("as_known_resolution_required")
    return DecisionSelectionReferenceV1(
        schema_version="1",
        selection_proof_hash=content_hash(proof),
        normalized_query_hash=proof.normalized_query_hash,
        purpose=query.purpose,
        information_role=InformationRole.DECISION_INFORMATION,
        selected_record_hashes=proof.selected_record_hashes,
    )


def resolve_selected_records[T](
    reference: DecisionSelectionReferenceV1,
    records_by_hash: Mapping[str, T],
) -> Mapping[str, T]:
    """Verify selected content: canonical model/JSON hashes or exact-byte SHA-256."""
    records = dict(records_by_hash)
    if set(records) != set(reference.selected_record_hashes):
        raise DatasetValidationError.single("unauthorized_record_hash")
    for expected_hash, value in records.items():
        actual_hash = (
            sha256(value).hexdigest()
            if isinstance(value, bytes)
            else content_hash(value)
        )
        if actual_hash != expected_hash:
            raise DatasetValidationError.single("selected_record_content_hash_mismatch")
    return MappingProxyType(records)


def _validate_query_dataset_binding(
    query: NormalizedSelectionQueryV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
) -> None:
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single("validation_decision_not_passing")
    expected = (
        manifest_hash(manifest),
        content_hash(decision),
        content_hash(manifest.dataset_role),
        content_hash(manifest.temporal_contract.contract),
        manifest.schema_definition.schema_hash,
    )
    actual = (
        query.source_manifest_hash,
        query.validation_decision_hash,
        query.dataset_role_hash,
        query.record_contract_hash,
        query.schema_hash,
    )
    if actual != expected:
        raise DatasetValidationError.single("selection_query_dataset_mismatch")


def _has_backward_availability(
    predecessor: Sequence[AvailabilityEvidenceV1],
    successor: Sequence[AvailabilityEvidenceV1],
) -> bool:
    predecessor_by_channel = {item.channel: item for item in predecessor}
    return any(
        prior.upper_bound is not None
        and item.upper_bound is not None
        and item.upper_bound < prior.upper_bound
        for item in successor
        if (prior := predecessor_by_channel.get(item.channel)) is not None
    )


def _has_revision_cycle(
    by_id: Mapping[UUID, AssertionVersionProjectionV1],
) -> bool:
    for start in by_id:
        seen: set[UUID] = set()
        current: UUID | None = start
        while current is not None:
            if current in seen:
                return True
            seen.add(current)
            item = by_id.get(current)
            if item is None:
                break
            current = item.revision.supersedes_record_version_id
    return False


def _finding(
    code: str, artifact: ArtifactReference | None = None
) -> ValidationFindingV1:
    references = () if artifact is None else (artifact,)
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
        artifact_references=references,
    )


def _canonical_findings(
    findings: Iterable[ValidationFindingV1],
) -> tuple[ValidationFindingV1, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.code,
                item.severity.value,
                item.message,
                tuple(ref.content_hash for ref in item.artifact_references),
            ),
        )
    )
