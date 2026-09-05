"""Real-data regressions for dependent assignment equivalence authentication."""

from typing import Any

import pytest
from test_assertions import parse_utc
from test_listing_semantics import (
    assignment_dataset,
    assignment_for_dependency,
    exact_dataset_query,
    interval,
    relationship_dataset,
    revision,
    uid,
)

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import assertion_version_payload
from drift.domain.assertions import M1bSelectionPurpose, ResolutionMode
from drift.domain.dataset_validation import DatasetValidationError, ValidationResult
from drift.domain.securities import (
    IdentityAssignmentSubjectV1,
    IdentityKind,
    IdentityReferenceV1,
    IdentityRelationshipKind,
    IdentityRelationshipVersionV1,
    IdentityResolutionClassification,
    ResolutionStatus,
)
from drift.domain.temporal import AvailabilityPolicyV1
from drift.markets.identity import (
    _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    _select_records_for_query,
    resolve_identity,
    resolve_identity_assignment,
)
from drift.serialization.canonical import content_hash


def actual_equivalence_arguments(
    kind: IdentityRelationshipKind,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build real validated assignment/relationship bytes and genuine query proofs."""
    first = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(2))
    second = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(3))
    assignments = tuple(
        assignment_for_dependency(target, 6100 + index).model_copy(
            update={
                "source_key": "shared-equivalence",
            }
        )
        for index, target in enumerate((first, second))
    )
    assignments = tuple(
        record.model_copy(
            update={
                "revision": record.revision.model_copy(
                    update={
                        "payload_hash": content_hash(assertion_version_payload(record)),
                    }
                )
            }
        )
        for record in assignments
    )
    relationship = IdentityRelationshipVersionV1(
        schema_version="1",
        revision=revision(6200),
        left=first,
        right=second,
        relationship_kind=kind,
        resolution_status=ResolutionStatus.RESOLVED,
        effective_interval=interval("2019-01-01T00:00:00Z"),
        source_relationship_code=None,
    )
    relationship = relationship.model_copy(
        update={
            "revision": relationship.revision.model_copy(
                update={
                    "payload_hash": content_hash(
                        assertion_version_payload(relationship)
                    ),
                }
            )
        }
    )
    assignment_manifest, assignment_decision = assignment_dataset(assignments)
    relationship_manifest, relationship_decision = relationship_dataset((relationship,))
    assert assignment_decision.result is ValidationResult.PASS
    assert relationship_decision.result is ValidationResult.PASS
    bundle = build_validated_dataset_bundle(
        uid(6300),
        "1",
        parse_utc("2020-02-01T00:00:00Z"),
        (
            (assignment_manifest, assignment_decision),
            (relationship_manifest, relationship_decision),
        ),
    )
    policy = AvailabilityPolicyV1(policy_id="strict")
    subject = IdentityAssignmentSubjectV1(
        identity_kind=IdentityKind.SECURITY,
        source_namespace="synthetic-master",
        source_key="shared-equivalence",
    )
    assignment_query = exact_dataset_query(
        assignment_manifest,
        assignment_decision,
        bundle,
        purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
        subject=subject,
        evaluation_time="2020-02-01T00:00:00Z",
        knowledge_cutoff="2020-02-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )
    relationship_query = exact_dataset_query(
        relationship_manifest,
        relationship_decision,
        bundle,
        purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
        subject=first,
        evaluation_time="2020-02-01T00:00:00Z",
        knowledge_cutoff="2020-02-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )
    result = resolve_identity(
        first,
        assignments,
        (relationship,),
        relationship_query,
        bundle,
        relationship_manifest,
        relationship_decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    _, proof = _select_records_for_query(
        (relationship,),
        relationship_query,
        bundle,
        relationship_manifest,
        relationship_decision,
        policy,
        {},
        _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    )
    assert result.selection_proof_hashes == (content_hash(proof),)
    return {
        "subject": subject,
        "assignments": assignments,
        "query": assignment_query,
        "identity_bundle": bundle,
        "manifest": assignment_manifest,
        "decision": assignment_decision,
        "policy": policy,
        "retained_evidence": {},
        "equivalence_resolution": result,
        "equivalence_proof": proof,
    }, {
        "equivalence_relationships": (relationship,),
        "equivalence_manifest": relationship_manifest,
        "equivalence_decision": relationship_decision,
    }


def test_distinction_proof_cannot_authorize_a_forged_equivalence_result() -> None:
    arguments, dependencies = actual_equivalence_arguments(
        IdentityRelationshipKind.DISTINCT_FROM
    )
    first = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(2))
    second = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(3))
    real = arguments["equivalence_resolution"]
    assert real.resolved_identities == (first,)
    base = {
        key: value
        for key, value in arguments.items()
        if not key.startswith("equivalence_")
    }
    assert (
        resolve_identity_assignment(**base).classification
        is IdentityResolutionClassification.CONFLICT
    )
    arguments["equivalence_resolution"] = real.model_copy(
        update={"resolved_identities": (first, second)}
    )
    arguments.update(dependencies)
    with pytest.raises(DatasetValidationError, match="resolution_replay"):
        resolve_identity_assignment(**arguments)


def test_genuine_equivalence_still_resolves_both_assigned_identities() -> None:
    arguments, dependencies = actual_equivalence_arguments(
        IdentityRelationshipKind.EQUIVALENT_TO
    )
    arguments.update(dependencies)
    result = resolve_identity_assignment(**arguments)
    assert result.classification is IdentityResolutionClassification.RESOLVED
    assert result.assigned_identities == (
        IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(2)),
        IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(3)),
    )


def test_equivalence_proof_without_result_cannot_be_silently_ignored() -> None:
    arguments, _ = actual_equivalence_arguments(IdentityRelationshipKind.EQUIVALENT_TO)
    arguments.pop("equivalence_resolution")
    with pytest.raises(DatasetValidationError, match="equivalence"):
        resolve_identity_assignment(**arguments)


@pytest.mark.parametrize(
    "missing",
    (
        "equivalence_resolution",
        "equivalence_proof",
        "equivalence_relationships",
        "equivalence_manifest",
        "equivalence_decision",
    ),
)
def test_optional_equivalence_dependencies_must_be_complete(missing: str) -> None:
    arguments, dependencies = actual_equivalence_arguments(
        IdentityRelationshipKind.EQUIVALENT_TO
    )
    arguments.update(dependencies)
    arguments.pop(missing)
    with pytest.raises(DatasetValidationError, match="equivalence"):
        resolve_identity_assignment(**arguments)


@pytest.mark.parametrize("substitution", ("records", "manifest", "decision"))
def test_equivalence_dependencies_must_match_the_exact_validated_dataset(
    substitution: str,
) -> None:
    arguments, dependencies = actual_equivalence_arguments(
        IdentityRelationshipKind.EQUIVALENT_TO
    )
    arguments.update(dependencies)
    if substitution == "records":
        arguments["equivalence_relationships"] = ()
    elif substitution == "manifest":
        arguments["equivalence_manifest"] = arguments["manifest"]
    else:
        arguments["equivalence_decision"] = arguments["decision"]
    with pytest.raises(DatasetValidationError):
        resolve_identity_assignment(**arguments)
