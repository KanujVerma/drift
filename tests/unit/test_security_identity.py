"""Tests for immutable issuer, security, listing, and relationship identity."""

from itertools import product
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_assertions import (
    artifact,
    exact_boundary,
    parse_utc,
    public_availability,
    query_for,
    record_decision,
)
from test_dataset_validation_v2 import fixed_manifest

from drift.datasets.assertions import (
    build_cutoff_selection_proof,
    build_validated_dataset_bundle,
    select_assertion_version,
)
from drift.domain.assertions import (
    AssertionVersionProjectionV1,
    HistoryCompleteness,
    InformationRole,
    NormalizedSelectionQueryV1,
    ResolutionMode,
    RevisionEnvelopeV1,
    TemporalIntervalClaimV1,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    ValidationScope,
)
from drift.domain.revisions import RevisionKind
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
    IssuerV1,
    ListingV1,
    ListingVenue,
    ResolutionStatus,
    SecurityV1,
    identity_reference,
)
from drift.domain.temporal import AvailabilityPolicyV1
from drift.markets.identity import resolve_identity, resolve_identity_assignment
from drift.serialization.canonical import content_hash

HASH_A = "a" * 64


def uid(suffix: int) -> UUID:
    """Return a fixed UUIDv7."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def revision(suffix: int = 10) -> RevisionEnvelopeV1:
    """Build one initial assertion revision."""
    return RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=uid(suffix),
        record_version_id=uid(suffix + 1),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(public_availability("2020-01-02T00:00:00Z"),),
        history_completeness=HistoryCompleteness.COMPLETE,
        source_native_revision_label=None,
        source_artifact=artifact(),
        payload_hash=HASH_A,
    )


def correction_revision(initial: RevisionEnvelopeV1, suffix: int) -> RevisionEnvelopeV1:
    """Build one correction that supersedes an initial test revision."""
    return initial.model_copy(
        update={
            "record_version_id": uid(suffix),
            "revision_kind": RevisionKind.CORRECTION,
            "supersedes_record_version_id": initial.record_version_id,
            "source_sequence": 1,
        }
    )


def reference(kind: IdentityKind, suffix: int) -> IdentityReferenceV1:
    """Build one typed identity reference."""
    return IdentityReferenceV1(kind=kind, internal_id=uid(suffix))


def interval() -> TemporalIntervalClaimV1:
    """Build one open-ended exact interval."""
    return TemporalIntervalClaimV1(schema_version="1", start=exact_boundary(), end=None)


def assignment_for(
    identity: IssuerV1 | SecurityV1 | ListingV1, suffix: int
) -> IdentityAssignmentVersionV1:
    """Build retained typed-assignment provenance for a relationship endpoint."""
    return IdentityAssignmentVersionV1(
        schema_version="1",
        revision=revision(suffix),
        identity=identity,
        source_namespace="synthetic-master",
        source_key=f"identity-{suffix}",
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
        effective_interval=interval(),
    )


def assignment_for_reference(
    reference_value: IdentityReferenceV1,
) -> IdentityAssignmentVersionV1:
    """Build provenance that retains the exact typed reference used by a relation."""
    identity = (
        IssuerV1(schema_version="1", issuer_id=reference_value.internal_id)
        if reference_value.kind is IdentityKind.ISSUER
        else SecurityV1(schema_version="1", security_id=reference_value.internal_id)
        if reference_value.kind is IdentityKind.SECURITY
        else ListingV1(
            schema_version="1",
            listing_id=reference_value.internal_id,
            venue=ListingVenue.XNYS,
        )
    )
    return assignment_for(identity, 500 + int(str(reference_value.internal_id)[-1]))


def relationship(
    kind: IdentityRelationshipKind,
    left: IdentityKind,
    right: IdentityKind,
) -> IdentityRelationshipVersionV1:
    """Build one relationship candidate for the endpoint matrix."""
    return IdentityRelationshipVersionV1(
        schema_version="1",
        revision=revision(),
        left=reference(left, 20),
        right=reference(right, 21),
        relationship_kind=kind,
        resolution_status=ResolutionStatus.RESOLVED,
        effective_interval=interval(),
        source_relationship_code=None,
    )


def test_identity_reference_is_derived_without_ticker_or_name() -> None:
    """Adding ticker/name identity or returning the wrong kind must fail."""
    issuer = IssuerV1(schema_version="1", issuer_id=uid(1))
    security = SecurityV1(schema_version="1", security_id=uid(2))
    listing = ListingV1(schema_version="1", listing_id=uid(3), venue=ListingVenue.XNAS)
    assert identity_reference(issuer) == reference(IdentityKind.ISSUER, 1)
    assert identity_reference(security) == reference(IdentityKind.SECURITY, 2)
    assert identity_reference(listing) == reference(IdentityKind.LISTING, 3)
    assert set(IssuerV1.model_fields) == {"schema_version", "issuer_id"}
    assert set(SecurityV1.model_fields) == {"schema_version", "security_id"}
    assert set(ListingV1.model_fields) == {"schema_version", "listing_id", "venue"}


def test_assignment_retains_the_exact_typed_identity_and_effect() -> None:
    """Replacing a listing object with a ticker or untyped UUID must fail."""
    listing = ListingV1(schema_version="1", listing_id=uid(3), venue=ListingVenue.XNYS)
    assignment = IdentityAssignmentVersionV1(
        schema_version="1",
        revision=revision(),
        identity=listing,
        source_namespace="synthetic-master",
        source_key="listing-3",
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
        effective_interval=interval(),
    )
    assert assignment.identity is listing
    assert assignment.model_copy().identity == listing
    with pytest.raises(ValidationError):
        assignment.model_copy(update={"ticker": "WRONG"})


VALID_ENDPOINTS = {
    (
        IdentityRelationshipKind.ISSUER_HAS_SECURITY,
        IdentityKind.ISSUER,
        IdentityKind.SECURITY,
    ),
    (
        IdentityRelationshipKind.SECURITY_HAS_LISTING,
        IdentityKind.SECURITY,
        IdentityKind.LISTING,
    ),
    *{
        (kind, endpoint, endpoint)
        for kind in (
            IdentityRelationshipKind.EQUIVALENT_TO,
            IdentityRelationshipKind.DISTINCT_FROM,
        )
        for endpoint in IdentityKind
    },
    *{
        (kind, endpoint, endpoint)
        for kind in (
            IdentityRelationshipKind.SUCCESSOR_OF,
            IdentityRelationshipKind.REORGANIZED_FROM,
        )
        for endpoint in (IdentityKind.ISSUER, IdentityKind.SECURITY)
    },
}


@pytest.mark.parametrize(
    ("relationship_kind", "left_kind", "right_kind"),
    tuple(product(IdentityRelationshipKind, IdentityKind, IdentityKind)),
)
def test_relationship_endpoint_matrix_is_closed(
    relationship_kind: IdentityRelationshipKind,
    left_kind: IdentityKind,
    right_kind: IdentityKind,
) -> None:
    """Permitting any endpoint triple outside the approved matrix must fail."""
    candidate = (relationship_kind, left_kind, right_kind)
    if candidate in VALID_ENDPOINTS:
        assert relationship(relationship_kind, left_kind, right_kind)
    else:
        with pytest.raises(ValidationError, match="endpoint"):
            relationship(relationship_kind, left_kind, right_kind)


def test_relationship_rejects_self_relation() -> None:
    """An identity cannot prove equivalence, distinction, or succession to itself."""
    values = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_dump(mode="python")
    values["right"] = values["left"]
    with pytest.raises(ValidationError, match="self"):
        IdentityRelationshipVersionV1.model_validate(values)


def test_issuer_with_two_share_classes_keeps_distinct_security_ids() -> None:
    """Grouping securities under one issuer must never collapse share classes."""
    issuer = reference(IdentityKind.ISSUER, 1)
    first = relationship(
        IdentityRelationshipKind.ISSUER_HAS_SECURITY,
        IdentityKind.ISSUER,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": issuer, "right": reference(IdentityKind.SECURITY, 2)})
    second = first.model_copy(update={"right": reference(IdentityKind.SECURITY, 3)})
    assert first.right != second.right
    assert first.left == second.left == issuer


def test_listing_venue_scope_is_closed() -> None:
    """An unsupported venue cannot enter the initial identity contract."""
    with pytest.raises(ValidationError):
        ListingV1.model_validate(
            {"schema_version": "1", "listing_id": uid(3), "venue": "OTC"}
        )


def test_assignment_resolution_rebuilds_the_same_internal_identity() -> None:
    """Regenerating a UUID instead of replaying the assignment must fail."""
    security = SecurityV1(schema_version="1", security_id=uid(2))
    assignment = IdentityAssignmentVersionV1(
        schema_version="1",
        revision=revision(),
        identity=security,
        source_namespace="synthetic-master",
        source_key="security-alpha",
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
        effective_interval=interval(),
    )
    record_hash = content_hash(assignment)
    manifest = fixed_manifest()
    decision = record_decision(record_hash)
    bundle = build_validated_dataset_bundle(
        uid(80), "1", parse_utc("2020-01-02T00:00:00Z"), ((manifest, decision),)
    )
    subject = IdentityAssignmentSubjectV1(
        identity_kind=IdentityKind.SECURITY,
        source_namespace="synthetic-master",
        source_key="security-alpha",
    )
    query = query_for(decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(subject)}
    )
    result = resolve_identity_assignment(
        subject,
        (assignment,),
        query,
        bundle,
        manifest,
        decision,
        query_policy(),
        {},
    )
    assert isinstance(result, IdentityAssignmentResolutionResultV1)
    assert result.assigned_identities == (identity_reference(security),)
    assert result.classification.value == "resolved"


def query_policy() -> AvailabilityPolicyV1:
    """Return the strict policy used by the shared query helper."""
    return AvailabilityPolicyV1(policy_id="strict")


def decision_for(role: str, *record_hashes: str) -> DatasetValidationDecisionV2:
    """Create a record-scoped decision for a role-specific unit fixture."""
    from test_dataset_validation_v2 import passing_decision

    return passing_decision(role).model_copy(
        update={
            "validation_scope": ValidationScope.RECORDS,
            "validated_record_hashes": tuple(sorted(record_hashes)),
        }
    )


def test_equivalence_returns_a_sorted_set_and_distinction_creates_conflict() -> None:
    """Choosing one alias or ignoring a later distinction must fail."""
    subject = reference(IdentityKind.SECURITY, 2)
    alias = reference(IdentityKind.SECURITY, 3)
    equivalent = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": revision(30)})
    distinct = relationship(
        IdentityRelationshipKind.DISTINCT_FROM,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": revision(40)})
    manifest = fixed_manifest("identity_relationship")
    assignment_records = (
        assignment_for_reference(subject),
        assignment_for_reference(alias),
    )
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    equivalent_hash = content_hash(equivalent)
    equivalent_decision = decision_for("identity_relationship", equivalent_hash)
    equivalent_bundle = build_validated_dataset_bundle(
        uid(81),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        (
            (assignment_manifest, assignment_decision),
            (manifest, equivalent_decision),
        ),
    )
    equivalent_query = query_for(
        equivalent_decision, content_hash(equivalent_bundle)
    ).model_copy(update={"subject_hash": content_hash(subject)})
    resolved = resolve_identity(
        subject,
        assignment_records,
        (equivalent,),
        equivalent_query,
        equivalent_bundle,
        manifest,
        equivalent_decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    assert isinstance(resolved, IdentityResolutionResultV1)
    assert resolved.classification is IdentityResolutionClassification.RESOLVED
    assert resolved.resolved_identities == (subject, alias)

    distinct_hash = content_hash(distinct)
    conflict_decision = decision_for(
        "identity_relationship", equivalent_hash, distinct_hash
    )
    conflict_bundle = build_validated_dataset_bundle(
        uid(82),
        "2",
        parse_utc("2020-01-02T00:00:00Z"),
        (
            (assignment_manifest, assignment_decision),
            (manifest, conflict_decision),
        ),
    )
    conflict_query = query_for(
        conflict_decision, content_hash(conflict_bundle)
    ).model_copy(update={"subject_hash": content_hash(subject)})
    conflict = resolve_identity(
        subject,
        (assignment_for_reference(subject), assignment_for_reference(alias)),
        (equivalent, distinct),
        conflict_query,
        conflict_bundle,
        manifest,
        conflict_decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    assert conflict.classification is IdentityResolutionClassification.CONFLICT
    assert conflict.resolved_identities == ()


def test_identity_resolution_rejects_an_incomplete_validated_relationship_set() -> None:
    """Omitting a validated correction cannot alter a pinned identity replay."""
    subject = reference(IdentityKind.SECURITY, 2)
    alias = reference(IdentityKind.SECURITY, 3)
    equivalent = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": revision(50)})
    distinct = relationship(
        IdentityRelationshipKind.DISTINCT_FROM,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": revision(60)})
    manifest = fixed_manifest("identity_relationship")
    decision = decision_for(
        "identity_relationship", content_hash(equivalent), content_hash(distinct)
    )
    bundle = build_validated_dataset_bundle(
        uid(83), "1", parse_utc("2020-01-02T00:00:00Z"), ((manifest, decision),)
    )
    query = query_for(decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(subject)}
    )
    incomplete_assignment = assignment_for_reference(subject)
    with pytest.raises(DatasetValidationError, match="identity_record_set_mismatch"):
        resolve_identity(
            subject,
            (),
            (equivalent,),
            query,
            bundle,
            manifest,
            decision,
            query_policy(),
            {},
            assignment_manifest=fixed_manifest("identity_assignment"),
            assignment_decision=decision_for(
                "identity_assignment", content_hash(incomplete_assignment)
            ),
        )


def test_identity_resolution_rejects_unassigned_cross_kind_endpoint() -> None:
    """A fabricated issuer endpoint must not enter a validated relationship."""
    subject = reference(IdentityKind.SECURITY, 2)
    fabricated_issuer = reference(IdentityKind.ISSUER, 90)
    issuer_link = relationship(
        IdentityRelationshipKind.ISSUER_HAS_SECURITY,
        IdentityKind.ISSUER,
        IdentityKind.SECURITY,
    ).model_copy(
        update={
            "left": fabricated_issuer,
            "right": subject,
            "revision": revision(70),
        }
    )
    manifest = fixed_manifest("identity_relationship")
    decision = decision_for("identity_relationship", content_hash(issuer_link))
    assignment_records = (assignment_for_reference(subject),)
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    bundle = build_validated_dataset_bundle(
        uid(84),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        ((assignment_manifest, assignment_decision), (manifest, decision)),
    )
    query = query_for(decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(subject)}
    )

    with pytest.raises(DatasetValidationError, match="identity_reference_not_assigned"):
        resolve_identity(
            subject,
            assignment_records,
            (issuer_link,),
            query,
            bundle,
            manifest,
            decision,
            query_policy(),
            {},
            assignment_manifest=assignment_manifest,
            assignment_decision=assignment_decision,
        )


def test_identity_resolution_selects_superseding_issuer_link() -> None:
    """A corrected issuer link must supersede the retained wrong endpoint."""
    issuer = reference(IdentityKind.ISSUER, 1)
    old_issuer = reference(IdentityKind.ISSUER, 6)
    security = reference(IdentityKind.SECURITY, 2)
    initial_revision = revision(80)
    wrong_link = relationship(
        IdentityRelationshipKind.ISSUER_HAS_SECURITY,
        IdentityKind.ISSUER,
        IdentityKind.SECURITY,
    ).model_copy(
        update={
            "left": old_issuer,
            "right": security,
            "revision": initial_revision,
        }
    )
    corrected_link = wrong_link.model_copy(
        update={
            "left": issuer,
            "revision": correction_revision(initial_revision, 82),
        }
    )
    manifest = fixed_manifest("identity_relationship")
    decision = decision_for(
        "identity_relationship", content_hash(wrong_link), content_hash(corrected_link)
    )
    assignment_records = tuple(
        assignment_for_reference(item) for item in (issuer, old_issuer, security)
    )
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    bundle = build_validated_dataset_bundle(
        uid(85),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        ((assignment_manifest, assignment_decision), (manifest, decision)),
    )
    query = query_for(decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(issuer)}
    )

    result = resolve_identity(
        issuer,
        assignment_records,
        (wrong_link, corrected_link),
        query,
        bundle,
        manifest,
        decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )

    assert result.resolved_identities == (issuer,)
    assert result.considered_assertion_hashes == tuple(
        sorted((content_hash(wrong_link), content_hash(corrected_link)))
    )
    assert result.selected_assertion_hashes == (content_hash(corrected_link),)


def test_multiple_assignments_resolve_only_with_equivalence_evidence() -> None:
    """Multiple assignments need an explicit selected equivalence assertion."""
    first = reference(IdentityKind.SECURITY, 2)
    second = reference(IdentityKind.SECURITY, 3)
    assignments = (
        assignment_for_reference(first).model_copy(
            update={"source_key": "shared-security"}
        ),
        assignment_for_reference(second).model_copy(
            update={"source_key": "shared-security"}
        ),
    )
    equivalent = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": first, "right": second, "revision": revision(90)})
    assignment_manifest = fixed_manifest("identity_assignment")
    relationship_manifest = fixed_manifest("identity_relationship")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignments)
    )
    relationship_decision = decision_for(
        "identity_relationship", content_hash(equivalent)
    )
    bundle = build_validated_dataset_bundle(
        uid(86),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        (
            (assignment_manifest, assignment_decision),
            (relationship_manifest, relationship_decision),
        ),
    )
    relationship_query = query_for(
        relationship_decision, content_hash(bundle)
    ).model_copy(update={"subject_hash": content_hash(first)})
    equivalence = resolve_identity(
        first,
        assignments,
        (equivalent,),
        relationship_query,
        bundle,
        relationship_manifest,
        relationship_decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    assignment_subject = IdentityAssignmentSubjectV1(
        identity_kind=IdentityKind.SECURITY,
        source_namespace="synthetic-master",
        source_key="shared-security",
    )
    assignment_query = query_for(assignment_decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(assignment_subject)}
    )
    conflicted = resolve_identity_assignment(
        assignment_subject,
        assignments,
        assignment_query,
        bundle,
        assignment_manifest,
        assignment_decision,
        query_policy(),
        {},
    )
    assert conflicted.classification is IdentityResolutionClassification.CONFLICT

    with pytest.raises(
        DatasetValidationError, match="equivalence_selection_proof_required"
    ):
        resolve_identity_assignment(
            assignment_subject,
            assignments,
            assignment_query,
            bundle,
            assignment_manifest,
            assignment_decision,
            query_policy(),
            {},
            equivalence_resolution=equivalence,
        )

    selection = select_assertion_version(
        (
            AssertionVersionProjectionV1(
                revision=equivalent.revision,
                record_hash=content_hash(equivalent),
            ),
        ),
        relationship_query.requested_channel,
        query_policy(),
        relationship_query.knowledge_cutoff,
        {},
    )
    proof = build_cutoff_selection_proof(
        relationship_query,
        (selection,),
        relationship_manifest,
        relationship_decision,
        (bundle,),
        "bf61c84a232e0d5c11a99b6451f9a43f37f96dab220c1c7036456252394c961d",
    )
    resolved = resolve_identity_assignment(
        assignment_subject,
        assignments,
        assignment_query,
        bundle,
        assignment_manifest,
        assignment_decision,
        query_policy(),
        {},
        equivalence_resolution=equivalence,
        equivalence_proof=proof,
    )
    assert resolved.classification is IdentityResolutionClassification.RESOLVED
    assert resolved.assigned_identities == (first, second)


def test_identity_resolution_requires_validated_assignment_decision() -> None:
    """Raw assignment records cannot authorize a relationship graph."""
    subject = reference(IdentityKind.SECURITY, 2)
    alias = reference(IdentityKind.SECURITY, 3)
    equivalent = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": revision(95)})
    assignment_records = (
        assignment_for_reference(subject),
        assignment_for_reference(alias),
    )
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    relationship_manifest = fixed_manifest("identity_relationship")
    relationship_decision = decision_for(
        "identity_relationship", content_hash(equivalent)
    )
    bundle = build_validated_dataset_bundle(
        uid(92),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        (
            (assignment_manifest, assignment_decision),
            (relationship_manifest, relationship_decision),
        ),
    )
    query = query_for(relationship_decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(subject)}
    )
    with pytest.raises(DatasetValidationError, match="identity_record_set_mismatch"):
        resolve_identity(
            subject,
            assignment_records[:1],
            (equivalent,),
            query,
            bundle,
            relationship_manifest,
            relationship_decision,
            query_policy(),
            {},
            assignment_manifest=assignment_manifest,
            assignment_decision=assignment_decision,
        )


def test_equivalence_resolution_requires_its_actual_cutoff_proof() -> None:
    """Matching result metadata without the retained proof is not authority."""
    subject = reference(IdentityKind.SECURITY, 2)
    alias = reference(IdentityKind.SECURITY, 3)
    equivalent = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": revision(96)})
    assignments = (
        assignment_for_reference(subject).model_copy(
            update={"source_key": "proof-security"}
        ),
        assignment_for_reference(alias).model_copy(
            update={"source_key": "proof-security"}
        ),
    )
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignments)
    )
    relationship_manifest = fixed_manifest("identity_relationship")
    relationship_decision = decision_for(
        "identity_relationship", content_hash(equivalent)
    )
    bundle = build_validated_dataset_bundle(
        uid(93),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        (
            (assignment_manifest, assignment_decision),
            (relationship_manifest, relationship_decision),
        ),
    )
    query = query_for(relationship_decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(subject)}
    )
    result = resolve_identity(
        subject,
        assignments,
        (equivalent,),
        query,
        bundle,
        relationship_manifest,
        relationship_decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    assignment_subject = IdentityAssignmentSubjectV1(
        identity_kind=IdentityKind.SECURITY,
        source_namespace="synthetic-master",
        source_key="proof-security",
    )
    assignment_query = query_for(assignment_decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(assignment_subject)}
    )
    with pytest.raises(
        DatasetValidationError, match="equivalence_selection_proof_required"
    ):
        resolve_identity_assignment(
            assignment_subject,
            assignments,
            assignment_query,
            bundle,
            assignment_manifest,
            assignment_decision,
            query_policy(),
            {},
            equivalence_resolution=result,
        )


def test_current_interpretation_uses_manifest_current_correction() -> None:
    """Current interpretation must select a retained correction after old K."""
    subject = reference(IdentityKind.SECURITY, 2)
    alias = reference(IdentityKind.SECURITY, 3)
    initial_revision = revision(100)
    equivalent = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": initial_revision})
    correction = correction_revision(initial_revision, 102).model_copy(
        update={
            "availability": (public_availability("2021-02-01T00:00:00Z"),),
        }
    )
    distinct = equivalent.model_copy(
        update={
            "relationship_kind": IdentityRelationshipKind.DISTINCT_FROM,
            "revision": correction,
        }
    )
    manifest = fixed_manifest("identity_relationship")
    decision = decision_for(
        "identity_relationship", content_hash(equivalent), content_hash(distinct)
    )
    assignment_records = (
        assignment_for_reference(subject),
        assignment_for_reference(alias),
    )
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    bundle = build_validated_dataset_bundle(
        uid(87),
        "1",
        parse_utc("2021-02-02T00:00:00Z"),
        ((assignment_manifest, assignment_decision), (manifest, decision)),
    )
    query_values = query_for(decision, content_hash(bundle)).model_dump(mode="python")
    query_values.update(
        {
            "subject_hash": content_hash(subject),
            "resolution_mode": ResolutionMode.CURRENT_INTERPRETATION,
            "information_role": InformationRole.EX_POST_OUTCOME,
            "knowledge_cutoff": parse_utc("2020-02-01T00:00:00Z"),
        }
    )
    query = NormalizedSelectionQueryV1.model_validate(query_values)

    result = resolve_identity(
        subject,
        assignment_records,
        (equivalent, distinct),
        query,
        bundle,
        manifest,
        decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )

    assert result.resolution_mode is ResolutionMode.CURRENT_INTERPRETATION
    assert result.resolved_identities == (subject,)
    assert result.selected_assertion_hashes == (content_hash(distinct),)


def test_identity_resolution_rejects_wrong_kind_subject_uuid() -> None:
    """Changing only the kind tag cannot reinterpret an assigned UUID."""
    security = reference(IdentityKind.SECURITY, 2)
    wrong_kind = IdentityReferenceV1(
        kind=IdentityKind.ISSUER, internal_id=security.internal_id
    )
    relation = relationship(
        IdentityRelationshipKind.ISSUER_HAS_SECURITY,
        IdentityKind.ISSUER,
        IdentityKind.SECURITY,
    ).model_copy(
        update={
            "left": wrong_kind,
            "right": security,
            "revision": revision(110),
        }
    )
    manifest = fixed_manifest("identity_relationship")
    decision = decision_for("identity_relationship", content_hash(relation))
    assignment_records = (assignment_for_reference(security),)
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    bundle = build_validated_dataset_bundle(
        uid(88),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        ((assignment_manifest, assignment_decision), (manifest, decision)),
    )
    query = query_for(decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(wrong_kind)}
    )

    with pytest.raises(DatasetValidationError, match="identity_reference_not_assigned"):
        resolve_identity(
            wrong_kind,
            assignment_records,
            (relation,),
            query,
            bundle,
            manifest,
            decision,
            query_policy(),
            {},
            assignment_manifest=assignment_manifest,
            assignment_decision=assignment_decision,
        )


def test_directional_cycle_is_conflict_and_dispute_is_indeterminate() -> None:
    """Directional cycles and disputed evidence must never choose a winner."""
    first = reference(IdentityKind.SECURITY, 2)
    second = reference(IdentityKind.SECURITY, 3)
    forward = relationship(
        IdentityRelationshipKind.SUCCESSOR_OF,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": first, "right": second, "revision": revision(120)})
    reverse = forward.model_copy(
        update={"left": second, "right": first, "revision": revision(130)}
    )
    manifest = fixed_manifest("identity_relationship")
    decision = decision_for(
        "identity_relationship", content_hash(forward), content_hash(reverse)
    )
    assignment_records = (
        assignment_for_reference(first),
        assignment_for_reference(second),
    )
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    bundle = build_validated_dataset_bundle(
        uid(89),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        ((assignment_manifest, assignment_decision), (manifest, decision)),
    )
    query = query_for(decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(first)}
    )
    cycle = resolve_identity(
        first,
        assignment_records,
        (forward, reverse),
        query,
        bundle,
        manifest,
        decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    assert cycle.classification is IdentityResolutionClassification.CONFLICT
    assert cycle.resolved_identities == ()

    disputed = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(
        update={
            "left": first,
            "right": second,
            "revision": revision(140),
            "resolution_status": ResolutionStatus.DISPUTED,
        }
    )
    disputed_decision = decision_for("identity_relationship", content_hash(disputed))
    disputed_assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    disputed_bundle = build_validated_dataset_bundle(
        uid(90),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        (
            (assignment_manifest, disputed_assignment_decision),
            (manifest, disputed_decision),
        ),
    )
    disputed_query = query_for(
        disputed_decision, content_hash(disputed_bundle)
    ).model_copy(update={"subject_hash": content_hash(first)})
    uncertain = resolve_identity(
        first,
        assignment_records,
        (disputed,),
        disputed_query,
        disputed_bundle,
        manifest,
        disputed_decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=disputed_assignment_decision,
    )
    assert uncertain.classification is IdentityResolutionClassification.INDETERMINATE
    assert uncertain.resolved_identities == ()


def test_identity_serialization_has_no_mutable_graph_state() -> None:
    """Serialized identity evidence must not retain parent or canonical shortcuts."""
    subject = reference(IdentityKind.SECURITY, 2)
    alias = reference(IdentityKind.SECURITY, 3)
    equivalent = relationship(
        IdentityRelationshipKind.EQUIVALENT_TO,
        IdentityKind.SECURITY,
        IdentityKind.SECURITY,
    ).model_copy(update={"left": subject, "right": alias, "revision": revision(150)})
    manifest = fixed_manifest("identity_relationship")
    decision = decision_for("identity_relationship", content_hash(equivalent))
    assignment_records = (
        assignment_for_reference(subject),
        assignment_for_reference(alias),
    )
    assignment_manifest = fixed_manifest("identity_assignment")
    assignment_decision = decision_for(
        "identity_assignment", *(content_hash(item) for item in assignment_records)
    )
    bundle = build_validated_dataset_bundle(
        uid(91),
        "1",
        parse_utc("2020-01-02T00:00:00Z"),
        ((assignment_manifest, assignment_decision), (manifest, decision)),
    )
    query = query_for(decision, content_hash(bundle)).model_copy(
        update={"subject_hash": content_hash(subject)}
    )
    result = resolve_identity(
        subject,
        assignment_records,
        (equivalent,),
        query,
        bundle,
        manifest,
        decision,
        query_policy(),
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list | tuple):
            return set().union(*(keys(item) for item in value))
        return set()

    forbidden = {
        "parent",
        "parent_id",
        "path_compression",
        "canonical_identity",
        "chosen_identity",
    }
    assert keys(equivalent.model_dump(mode="json")).isdisjoint(forbidden)
    assert keys(result.model_dump(mode="json")).isdisjoint(forbidden)
