"""Tests for dated external identifier mapping semantics."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_assertions import (
    artifact,
    exact_boundary,
    parse_utc,
    public_availability,
    query_for,
)
from test_dataset_validation_v2 import fixed_manifest, passing_decision

import drift.markets.identity as identity_module
from drift.datasets.assertions import (
    build_cutoff_selection_proof,
    build_validated_dataset_bundle,
)
from drift.datasets.hashing import assertion_version_payload, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.assertions import (
    AssertionSelectionResultV1,
    AssertionVersionProjectionV1,
    BoundaryShape,
    CutoffSelectionProofV1,
    HistoryCompleteness,
    InformationRole,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    ValidatedDatasetBundleV1,
    ValidationResult,
    ValidationRunContextV1,
    ValidationScope,
)
from drift.domain.manifests import (
    AssertionEffectiveShape,
    AssertionTemporalContractV1,
    DatasetManifestV2,
    EvidenceGranularity,
    FieldDescriptorV1,
    LogicalType,
    SchemaDescriptorV1,
    TemporalContractBindingV2,
    TemporalContractKindV2,
)
from drift.domain.revisions import RevisionKind
from drift.domain.securities import (
    ClassificationValueStatus,
    DomesticStatus,
    ExternalIdentifierKind,
    ExternalIdentifierMappingVersionV1,
    ExternalIdentifierNamespaceV1,
    ExternalIdentifierResolutionResultV1,
    IdentityAssignmentEffect,
    IdentityAssignmentVersionV1,
    IdentityKind,
    IdentityReferenceV1,
    IdentityRelationshipKind,
    IdentityRelationshipVersionV1,
    IdentityResolutionClassification,
    IdentityResolutionResultV1,
    InstrumentForm,
    IssuerForm,
    IssuerV1,
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
    ListingVenue,
    MappingStatus,
    OutcomeEvidenceStatus,
    PrimaryListingResolutionV1,
    RecordResolutionClassification,
    ResolutionStatus,
    SecurityClassificationResolutionV1,
    SecurityClassificationStatus,
    SecurityClassificationVersionV1,
    SecurityV1,
    SourcedTextValueV1,
    identity_reference,
)
from drift.domain.temporal import (
    AvailabilityPolicyV1,
    AvailabilityShape,
    SourcePrecision,
)
from drift.markets.identity import (
    _build_assignment_context_query,
    _relationship_chains_for_subject,
    _select_identity_chain,
    resolve_external_identifier,
    resolve_identity,
    resolve_listing_history_coverage,
    resolve_listing_lifecycle,
    resolve_listing_termination,
    resolve_primary_listing,
    resolve_security_classification,
)
from drift.markets.validation import (
    validate_external_identifier_mappings,
    validate_identity_bundle_references,
    validate_identity_dataset,
    validate_listing_lifecycle,
    validate_listing_roles,
    validate_listing_terminations,
)
from drift.serialization.canonical import canonical_json, content_hash


def uid(suffix: int) -> UUID:
    """Return a fixed UUIDv7 for one synthetic history record."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def interval(start: str, end: str | None = None) -> TemporalIntervalClaimV1:
    """Create a hand-specified half-open mapping interval."""
    return TemporalIntervalClaimV1(
        schema_version="1",
        start=exact_boundary(start),
        end=None if end is None else exact_boundary(end),
    )


def bounded_boundary(lower: str, upper: str) -> TemporalBoundaryClaimV1:
    """Build retained interval-precision evidence with hand-specified bounds."""
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=parse_utc(lower),
        upper_bound=parse_utc(upper),
        source_precision=SourcePrecision.INTERVAL,
        source_time_label=f"{lower}/{upper}",
        source_timezone=None,
        evidence_reference=artifact(),
    )


def revision(suffix: int) -> RevisionEnvelopeV1:
    """Build availability evidence predating every query in the history."""
    return RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=uid(suffix),
        record_version_id=uid(suffix + 100),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(public_availability("2018-01-01T00:00:00Z"),),
        history_completeness=HistoryCompleteness.COMPLETE,
        source_native_revision_label=None,
        source_artifact=artifact(),
        payload_hash="a" * 64,
    )


def ticker_namespace(venue: ListingVenue) -> ExternalIdentifierNamespaceV1:
    """Return the versioned synthetic ticker namespace for one venue."""
    return ExternalIdentifierNamespaceV1(
        kind=ExternalIdentifierKind.TICKER,
        scheme="synthetic-ticker-v1",
        authority="synthetic",
        target_level=IdentityKind.LISTING,
        venue=venue,
    )


def mapping(
    suffix: int,
    namespace: ExternalIdentifierNamespaceV1,
    value: str,
    listing_id: int,
    start: str,
    end: str | None = None,
) -> ExternalIdentifierMappingVersionV1:
    """Return one dated asserted ticker mapping without implicit normalization."""
    record = ExternalIdentifierMappingVersionV1(
        schema_version="1",
        revision=revision(suffix),
        namespace=namespace,
        identifier_value=value,
        target=IdentityReferenceV1(
            kind=IdentityKind.LISTING, internal_id=uid(listing_id)
        ),
        mapping_status=MappingStatus.ASSERTED,
        effective_interval=interval(start, end),
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def mapping_for_target(
    suffix: int,
    namespace: ExternalIdentifierNamespaceV1,
    value: str,
    target: IdentityReferenceV1,
) -> ExternalIdentifierMappingVersionV1:
    """Create one mapping for collision tests at an explicitly chosen target level."""
    return ExternalIdentifierMappingVersionV1(
        schema_version="1",
        revision=revision(suffix),
        namespace=namespace,
        identifier_value=value,
        target=target,
        mapping_status=MappingStatus.ASSERTED,
        effective_interval=interval("2019-01-02T00:00:00Z"),
    )


def decision_for(
    *records: ExternalIdentifierMappingVersionV1,
) -> DatasetValidationDecisionV2:
    """Build exact record validation evidence for the mapping dataset."""
    return passing_decision("external_identifier_mapping").model_copy(
        update={
            "validation_scope": ValidationScope.RECORDS,
            "validated_record_hashes": tuple(
                sorted(content_hash(item) for item in records)
            ),
        }
    )


def listing_assignment(
    suffix: int,
    listing_id: int,
    venue: ListingVenue,
    start: str,
    end: str | None = None,
) -> IdentityAssignmentVersionV1:
    """Retain the Task 2 assignment that establishes a listing's interval."""
    record = IdentityAssignmentVersionV1(
        schema_version="1",
        revision=revision(suffix),
        identity=ListingV1(schema_version="1", listing_id=uid(listing_id), venue=venue),
        source_namespace="synthetic-master",
        source_key=f"listing-{listing_id}",
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
        effective_interval=interval(start, end),
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def security_assignment(
    suffix: int, security_id: int, start: str
) -> IdentityAssignmentVersionV1:
    """Retain the Task 2 assignment that establishes one security identity."""
    record = IdentityAssignmentVersionV1(
        schema_version="1",
        revision=revision(suffix),
        identity=SecurityV1(schema_version="1", security_id=uid(security_id)),
        source_namespace="synthetic-master",
        source_key=f"security-{security_id}",
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
        effective_interval=interval(start),
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def history_assignments() -> tuple[IdentityAssignmentVersionV1, ...]:
    """Return the retained typed identities and listing lifetimes for the history."""
    return (
        security_assignment(300, 10, "2019-01-02T00:00:00Z"),
        security_assignment(310, 11, "2024-01-02T00:00:00Z"),
        listing_assignment(
            320,
            1,
            ListingVenue.XNAS,
            "2019-01-02T00:00:00Z",
            "2021-12-31T00:00:00Z",
        ),
        listing_assignment(330, 2, ListingVenue.XNYS, "2022-01-03T00:00:00Z"),
        listing_assignment(340, 3, ListingVenue.XNAS, "2024-01-02T00:00:00Z"),
    )


@dataclass(frozen=True)
class ResolutionInputs:
    """One fully validated mapping and identity-assignment resolution context."""

    namespace: ExternalIdentifierNamespaceV1
    value: str
    records: tuple[ExternalIdentifierMappingVersionV1, ...]
    query: NormalizedSelectionQueryV1
    bundle: ValidatedDatasetBundleV1
    manifest: DatasetManifestV2
    decision: DatasetValidationDecisionV2
    policy: AvailabilityPolicyV1
    assignments: tuple[IdentityAssignmentVersionV1, ...]
    assignment_manifest: DatasetManifestV2
    assignment_decision: DatasetValidationDecisionV2
    lifecycle_events: tuple[ListingLifecycleVersionV1, ...]
    lifecycle_manifest: DatasetManifestV2
    lifecycle_decision: DatasetValidationDecisionV2
    terminations: tuple[ListingTerminationVersionV1, ...]
    termination_manifest: DatasetManifestV2
    termination_decision: DatasetValidationDecisionV2


def resolution_inputs(
    namespace: ExternalIdentifierNamespaceV1,
    value: str,
    records: tuple[ExternalIdentifierMappingVersionV1, ...],
    instant: str,
) -> ResolutionInputs:
    """Build a mapping query whose authorization binds retained assignments."""
    manifest, mapping_bytes = role_dataset("external_identifier_mapping", records)
    decision = validate_identity_dataset(
        manifest, (mapping_bytes,), role_validation_context(600)
    )
    assert decision.result is ValidationResult.PASS
    assignments = history_assignments()
    assignment_manifest, assignment_decision = assignment_dataset(assignments)
    lifecycle_events = (
        lifecycle_record(
            9100,
            ListingLifecycleEventKind.ADMITTED,
            "2019-01-02T00:00:00Z",
            listing=1,
        ),
        lifecycle_record(
            9110,
            ListingLifecycleEventKind.ADMITTED,
            "2022-01-03T00:00:00Z",
            listing=2,
        ),
        lifecycle_record(
            9120,
            ListingLifecycleEventKind.ADMITTED,
            "2024-01-02T00:00:00Z",
            listing=3,
        ),
    )
    terminations = (
        termination_record(
            9130,
            ListingTerminationReason.VENUE_TRANSFER,
            listing=1,
            effective_time="2021-12-31T00:00:00Z",
        ),
    )
    lifecycle_manifest, lifecycle_bytes = role_dataset(
        "listing_lifecycle", lifecycle_events
    )
    lifecycle_decision = validate_identity_dataset(
        lifecycle_manifest, (lifecycle_bytes,), role_validation_context(604)
    )
    termination_manifest, termination_bytes = role_dataset(
        "listing_termination", terminations
    )
    termination_decision = validate_identity_dataset(
        termination_manifest, (termination_bytes,), role_validation_context(605)
    )
    assert lifecycle_decision.result is ValidationResult.PASS
    assert termination_decision.result is ValidationResult.PASS
    bundle = build_validated_dataset_bundle(
        uid(900),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (manifest, decision),
            (assignment_manifest, assignment_decision),
            (lifecycle_manifest, lifecycle_decision),
            (termination_manifest, termination_decision),
        ),
    )
    policy = AvailabilityPolicyV1(policy_id="strict")
    query = exact_dataset_query(
        manifest,
        decision,
        bundle,
        purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
        subject={"namespace": namespace, "identifier_value": value},
        evaluation_time=instant,
        knowledge_cutoff="2026-01-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )
    return ResolutionInputs(
        namespace,
        value,
        records,
        query,
        bundle,
        manifest,
        decision,
        policy,
        assignments,
        assignment_manifest,
        assignment_decision,
        lifecycle_events,
        lifecycle_manifest,
        lifecycle_decision,
        terminations,
        termination_manifest,
        termination_decision,
    )


def resolve_at(
    namespace: ExternalIdentifierNamespaceV1,
    value: str,
    records: tuple[ExternalIdentifierMappingVersionV1, ...],
    instant: str,
) -> ExternalIdentifierResolutionResultV1:
    """Resolve a mapping using its complete validated provenance context."""
    inputs = resolution_inputs(namespace, value, records, instant)
    return resolve_external_identifier(
        inputs.namespace,
        inputs.value,
        inputs.records,
        inputs.query,
        inputs.bundle,
        inputs.manifest,
        inputs.decision,
        inputs.policy,
        {},
        assignments=inputs.assignments,
        assignment_manifest=inputs.assignment_manifest,
        assignment_decision=inputs.assignment_decision,
        lifecycle_events=inputs.lifecycle_events,
        lifecycle_manifest=inputs.lifecycle_manifest,
        lifecycle_decision=inputs.lifecycle_decision,
        terminations=inputs.terminations,
        termination_manifest=inputs.termination_manifest,
        termination_decision=inputs.termination_decision,
    )


def with_assignment_context(
    inputs: ResolutionInputs,
    assignments: tuple[IdentityAssignmentVersionV1, ...],
    cutoff: str,
) -> ResolutionInputs:
    """Rebind a mapping query to a replacement complete assignment dataset."""
    assignment_manifest, assignment_decision = assignment_dataset(assignments)
    bundle = build_validated_dataset_bundle(
        uid(902),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (inputs.manifest, inputs.decision),
            (assignment_manifest, assignment_decision),
            (inputs.lifecycle_manifest, inputs.lifecycle_decision),
            (inputs.termination_manifest, inputs.termination_decision),
        ),
    )
    return ResolutionInputs(
        namespace=inputs.namespace,
        value=inputs.value,
        records=inputs.records,
        query=inputs.query.model_copy(
            update={
                "context_bundle_hashes": (content_hash(bundle),),
                "knowledge_cutoff": parse_utc(cutoff),
            }
        ),
        bundle=bundle,
        manifest=inputs.manifest,
        decision=inputs.decision,
        policy=inputs.policy,
        assignments=assignments,
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
        lifecycle_events=inputs.lifecycle_events,
        lifecycle_manifest=inputs.lifecycle_manifest,
        lifecycle_decision=inputs.lifecycle_decision,
        terminations=inputs.terminations,
        termination_manifest=inputs.termination_manifest,
        termination_decision=inputs.termination_decision,
    )


def invoke_resolution(
    inputs: ResolutionInputs,
    *,
    query: NormalizedSelectionQueryV1 | None = None,
) -> ExternalIdentifierResolutionResultV1:
    """Run the resolver with the complete context retained by a test fixture."""
    return resolve_external_identifier(
        inputs.namespace,
        inputs.value,
        inputs.records,
        inputs.query if query is None else query,
        inputs.bundle,
        inputs.manifest,
        inputs.decision,
        inputs.policy,
        {},
        assignments=inputs.assignments,
        assignment_manifest=inputs.assignment_manifest,
        assignment_decision=inputs.assignment_decision,
        lifecycle_events=inputs.lifecycle_events,
        lifecycle_manifest=inputs.lifecycle_manifest,
        lifecycle_decision=inputs.lifecycle_decision,
        terminations=inputs.terminations,
        termination_manifest=inputs.termination_manifest,
        termination_decision=inputs.termination_decision,
    )


def test_namespace_enforces_target_level_and_venue_scope() -> None:
    """Allowing a ticker to target a security or CIK to carry a venue is a bug."""
    with pytest.raises(ValidationError, match="listing"):
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.TICKER,
            scheme="synthetic-ticker-v1",
            authority="synthetic",
            target_level=IdentityKind.SECURITY,
            venue=ListingVenue.XNAS,
        )


@pytest.mark.parametrize(
    "kind",
    (ExternalIdentifierKind.TICKER, ExternalIdentifierKind.EXCHANGE_SYMBOL),
)
def test_listing_symbol_namespaces_require_a_venue(
    kind: ExternalIdentifierKind,
) -> None:
    """A venue-free ticker or exchange symbol cannot identify one listing."""
    with pytest.raises(ValidationError, match="require a venue"):
        ExternalIdentifierNamespaceV1(
            kind=kind,
            scheme="synthetic-symbol-v1",
            authority="synthetic",
            target_level=IdentityKind.LISTING,
            venue=None,
        )


def test_exchange_symbol_requires_a_listing_target() -> None:
    """An exchange symbol belongs to a listing, never an issuer or security."""
    with pytest.raises(ValidationError, match="target listings"):
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.EXCHANGE_SYMBOL,
            scheme="synthetic-symbol-v1",
            authority="synthetic",
            target_level=IdentityKind.SECURITY,
            venue=ListingVenue.XNAS,
        )


def test_cik_requires_an_issuer_target_without_venue() -> None:
    """Treating a filer identifier as a security or listing identifier is invalid."""
    with pytest.raises(ValidationError, match="target issuers"):
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.CIK,
            scheme="sec-cik-v1",
            authority="sec",
            target_level=IdentityKind.SECURITY,
            venue=None,
        )
    with pytest.raises(ValidationError, match="forbid a venue"):
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.CIK,
            scheme="sec-cik-v1",
            authority="sec",
            target_level=IdentityKind.ISSUER,
            venue=ListingVenue.XNAS,
        )


@pytest.mark.parametrize(
    "kind",
    (
        ExternalIdentifierKind.CUSIP,
        ExternalIdentifierKind.FIGI,
        ExternalIdentifierKind.PROVIDER,
        ExternalIdentifierKind.OTHER,
    ),
)
def test_general_identifier_venue_scope_must_be_explicit(
    kind: ExternalIdentifierKind,
) -> None:
    """A generic identifier cannot acquire venue scope from a non-versioned label."""
    with pytest.raises(ValidationError, match="listing-venue scheme"):
        ExternalIdentifierNamespaceV1(
            kind=kind,
            scheme="synthetic-id-v1",
            authority="synthetic",
            target_level=IdentityKind.LISTING,
            venue=ListingVenue.XNAS,
        )
    with pytest.raises(ValidationError, match="target listings"):
        ExternalIdentifierNamespaceV1(
            kind=kind,
            scheme="synthetic-listing-venue-v1",
            authority="synthetic",
            target_level=IdentityKind.SECURITY,
            venue=ListingVenue.XNAS,
        )
    assert ExternalIdentifierNamespaceV1(
        kind=kind,
        scheme="synthetic-listing-venue-v1",
        authority="synthetic",
        target_level=IdentityKind.LISTING,
        venue=ListingVenue.XNAS,
    )


def test_mapping_target_kind_must_match_its_namespace() -> None:
    """A ticker record pointing at a security instead of a listing is invalid."""
    with pytest.raises(ValidationError, match="target kind"):
        ExternalIdentifierMappingVersionV1.model_validate(
            mapping(
                10,
                ticker_namespace(ListingVenue.XNAS),
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
            ).model_dump(mode="python")
            | {
                "target": IdentityReferenceV1(
                    kind=IdentityKind.SECURITY, internal_id=uid(1)
                )
            }
        )


def test_mapping_validation_rejects_overlapping_asserted_targets() -> None:
    """Concurrent ticker reuse must not silently resolve to one listing."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    first = mapping(20, namespace, "OLD", 1, "2019-01-02T00:00:00Z")
    second = mapping(30, namespace, "OLD", 2, "2020-01-02T00:00:00Z")
    with pytest.raises(DatasetValidationError, match="overlapping"):
        validate_external_identifier_mappings(
            (first, second),
            target_intervals={
                first.target: (interval("2018-01-01T00:00:00Z"),),
                second.target: (interval("2018-01-01T00:00:00Z"),),
            },
        )


def test_mapping_validation_allows_explicitly_ambiguous_overlap() -> None:
    """Explicit ambiguity, not a hidden winner, is the sole overlap exception."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    first = mapping(40, namespace, "OLD", 1, "2019-01-02T00:00:00Z").model_copy(
        update={"mapping_status": MappingStatus.AMBIGUOUS}
    )
    second = mapping(50, namespace, "OLD", 2, "2020-01-02T00:00:00Z").model_copy(
        update={"mapping_status": MappingStatus.AMBIGUOUS}
    )
    validate_external_identifier_mappings(
        (first, second),
        target_intervals={
            first.target: (interval("2018-01-01T00:00:00Z"),),
            second.target: (interval("2018-01-01T00:00:00Z"),),
        },
    )


@pytest.mark.parametrize(
    "alternate",
    (
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.TICKER,
            scheme="synthetic-ticker-v1",
            authority="other-authority",
            target_level=IdentityKind.LISTING,
            venue=ListingVenue.XNAS,
        ),
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.TICKER,
            scheme="other-ticker-v1",
            authority="synthetic",
            target_level=IdentityKind.LISTING,
            venue=ListingVenue.XNAS,
        ),
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.EXCHANGE_SYMBOL,
            scheme="synthetic-exchange-symbol-v1",
            authority="synthetic",
            target_level=IdentityKind.LISTING,
            venue=ListingVenue.XNAS,
        ),
        ExternalIdentifierNamespaceV1(
            kind=ExternalIdentifierKind.TICKER,
            scheme="synthetic-ticker-v1",
            authority="synthetic",
            target_level=IdentityKind.LISTING,
            venue=ListingVenue.XNYS,
        ),
    ),
)
def test_collision_key_keeps_every_namespace_dimension_distinct(
    alternate: ExternalIdentifierNamespaceV1,
) -> None:
    """Only records sharing every collision-key dimension can collide."""
    base = ticker_namespace(ListingVenue.XNAS)
    first = mapping(55, base, "OLD", 1, "2019-01-02T00:00:00Z")
    second = mapping(56, alternate, "OLD", 2, "2019-01-02T00:00:00Z")
    validate_external_identifier_mappings(
        (first, second),
        target_intervals={
            first.target: (interval("2018-01-01T00:00:00Z"),),
            second.target: (interval("2018-01-01T00:00:00Z"),),
        },
    )


def test_collision_key_keeps_target_level_distinct_with_same_namespace_text() -> None:
    """Issuer and security mappings with identical namespace text cannot collide."""
    issuer_namespace = ExternalIdentifierNamespaceV1(
        kind=ExternalIdentifierKind.CUSIP,
        scheme="synthetic-cusip-v1",
        authority="synthetic",
        target_level=IdentityKind.ISSUER,
        venue=None,
    )
    security_namespace = issuer_namespace.model_copy(
        update={"target_level": IdentityKind.SECURITY}
    )
    issuer_target = IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=uid(20))
    security_target = IdentityReferenceV1(
        kind=IdentityKind.SECURITY, internal_id=uid(21)
    )
    first = mapping_for_target(57, issuer_namespace, "123456789", issuer_target)
    second = mapping_for_target(58, security_namespace, "123456789", security_target)
    validate_external_identifier_mappings(
        (first, second),
        target_intervals={
            issuer_target: (interval("2018-01-01T00:00:00Z"),),
            security_target: (interval("2018-01-01T00:00:00Z"),),
        },
    )


def test_collision_key_keeps_exact_identifier_value_distinct() -> None:
    """Distinct exact ticker text cannot collide even under one namespace."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    first = mapping(59, namespace, "OLD", 1, "2019-01-02T00:00:00Z")
    second = mapping(60, namespace, "NEW", 2, "2019-01-02T00:00:00Z")
    validate_external_identifier_mappings(
        (first, second),
        target_intervals={
            first.target: (interval("2018-01-01T00:00:00Z"),),
            second.target: (interval("2018-01-01T00:00:00Z"),),
        },
    )


def test_mapping_validation_rejects_possible_bounded_overlap() -> None:
    """Using latest-start evidence to declare disjointness loses possible overlap."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    first = mapping(60, namespace, "OLD", 1, "2019-01-01T00:00:00Z").model_copy(
        update={
            "effective_interval": TemporalIntervalClaimV1(
                schema_version="1",
                start=bounded_boundary("2019-01-01T00:00:00Z", "2019-01-10T00:00:00Z"),
                end=exact_boundary("2019-01-15T00:00:00Z"),
            )
        }
    )
    second = mapping(70, namespace, "OLD", 2, "2019-01-06T00:00:00Z")
    with pytest.raises(DatasetValidationError, match="overlapping"):
        validate_external_identifier_mappings(
            (first, second),
            target_intervals={
                first.target: (interval("2018-01-01T00:00:00Z"),),
                second.target: (interval("2018-01-01T00:00:00Z"),),
            },
        )


def test_mapping_validation_rejects_possible_target_interval_escape() -> None:
    """A mapping that may precede or outlast its target interval is not admissible."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    candidate = mapping(80, namespace, "OLD", 1, "2019-01-01T00:00:00Z").model_copy(
        update={
            "effective_interval": TemporalIntervalClaimV1(
                schema_version="1",
                start=bounded_boundary("2019-01-01T00:00:00Z", "2019-01-10T00:00:00Z"),
                end=bounded_boundary("2019-01-15T00:00:00Z", "2019-01-25T00:00:00Z"),
            )
        }
    )
    with pytest.raises(DatasetValidationError, match="outside"):
        validate_external_identifier_mappings(
            (candidate,),
            target_intervals={
                candidate.target: (
                    interval("2019-01-05T00:00:00Z", "2019-01-20T00:00:00Z"),
                )
            },
        )


def test_mapping_resolution_rejects_unbound_or_duplicate_provenance() -> None:
    """A resolver must reject mismatched authorization objects and duplicate input."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    records = (mapping(90, namespace, "OLD", 1, "2019-01-02T00:00:00Z"),)
    inputs = resolution_inputs(namespace, "OLD", records, "2019-02-01T00:00:00Z")

    def invoke(
        *,
        query: NormalizedSelectionQueryV1 | None = None,
        bundle: ValidatedDatasetBundleV1 | None = None,
        manifest: DatasetManifestV2 | None = None,
        decision: DatasetValidationDecisionV2 | None = None,
        policy: AvailabilityPolicyV1 | None = None,
        mappings: tuple[ExternalIdentifierMappingVersionV1, ...] | None = None,
        assignments: tuple[IdentityAssignmentVersionV1, ...] | None = None,
    ) -> ExternalIdentifierResolutionResultV1:
        return resolve_external_identifier(
            inputs.namespace,
            inputs.value,
            inputs.records if mappings is None else mappings,
            inputs.query if query is None else query,
            inputs.bundle if bundle is None else bundle,
            inputs.manifest if manifest is None else manifest,
            inputs.decision if decision is None else decision,
            inputs.policy if policy is None else policy,
            {},
            assignments=inputs.assignments if assignments is None else assignments,
            assignment_manifest=inputs.assignment_manifest,
            assignment_decision=inputs.assignment_decision,
            lifecycle_events=inputs.lifecycle_events,
            lifecycle_manifest=inputs.lifecycle_manifest,
            lifecycle_decision=inputs.lifecycle_decision,
            terminations=inputs.terminations,
            termination_manifest=inputs.termination_manifest,
            termination_decision=inputs.termination_decision,
        )

    with pytest.raises(DatasetValidationError, match="subject_hash"):
        invoke(query=inputs.query.model_copy(update={"subject_hash": "b" * 64}))
    with pytest.raises(DatasetValidationError, match="policy"):
        invoke(policy=AvailabilityPolicyV1(policy_id="different"))
    with pytest.raises(DatasetValidationError, match="mapping_role"):
        invoke(manifest=inputs.assignment_manifest)
    with pytest.raises(DatasetValidationError, match="mapping_manifest_hash"):
        invoke(decision=inputs.assignment_decision)
    assignment_only_bundle = build_validated_dataset_bundle(
        uid(901),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        ((inputs.assignment_manifest, inputs.assignment_decision),),
    )
    with pytest.raises(DatasetValidationError, match="mapping_not_in_context_bundle"):
        invoke(bundle=assignment_only_bundle)
    with pytest.raises(DatasetValidationError, match="identity_record_set_mismatch"):
        invoke(assignments=())
    with pytest.raises(DatasetValidationError, match="mapping_duplicate_record_hash"):
        invoke(mappings=inputs.records + inputs.records)
    outliving = resolution_inputs(
        namespace,
        "OLD",
        (mapping(92, namespace, "OLD", 1, "2019-01-02T00:00:00Z"),),
        "2019-02-01T00:00:00Z",
    )
    with pytest.raises(DatasetValidationError, match="outside_target_interval"):
        resolve_external_identifier(
            outliving.namespace,
            outliving.value,
            outliving.records,
            outliving.query,
            outliving.bundle,
            outliving.manifest,
            outliving.decision,
            outliving.policy,
            {},
            assignments=outliving.assignments,
            assignment_manifest=outliving.assignment_manifest,
            assignment_decision=outliving.assignment_decision,
            lifecycle_events=outliving.lifecycle_events,
            lifecycle_manifest=outliving.lifecycle_manifest,
            lifecycle_decision=outliving.lifecycle_decision,
            terminations=outliving.terminations,
            termination_manifest=outliving.termination_manifest,
            termination_decision=outliving.termination_decision,
        )


def test_resolution_result_rejects_impossible_target_shapes() -> None:
    """Persisted results cannot authorize zero, hidden, or singular-conflict targets."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    result = resolve_at(
        namespace,
        "OLD",
        (
            mapping(
                95,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    values = result.model_dump(mode="python")
    for classification, targets in (
        (RecordResolutionClassification.RESOLVED, ()),
        (RecordResolutionClassification.CONFLICT, result.targets),
        (RecordResolutionClassification.INDETERMINATE, result.targets),
    ):
        with pytest.raises(ValidationError):
            ExternalIdentifierResolutionResultV1.model_validate(
                values | {"classification": classification, "targets": targets}
            )
    proof_hash = result.target_assignment_proof_hashes[0]
    with pytest.raises(ValidationError, match="proof hashes"):
        ExternalIdentifierResolutionResultV1.model_validate(
            values | {"target_assignment_proof_hashes": (proof_hash, proof_hash)}
        )


def test_ticker_change_reuse_and_venue_transfer_resolve_by_period() -> None:
    """Collapsing ticker text into identity loses the required dated history."""
    nasdaq = ticker_namespace(ListingVenue.XNAS)
    nyse = ticker_namespace(ListingVenue.XNYS)
    records = (
        mapping(100, nasdaq, "OLD", 1, "2019-01-02T00:00:00Z", "2020-06-01T00:00:00Z"),
        mapping(110, nasdaq, "NEW", 1, "2020-06-01T00:00:00Z", "2021-12-31T00:00:00Z"),
        mapping(120, nyse, "NEW", 2, "2022-01-03T00:00:00Z"),
        mapping(130, nasdaq, "OLD", 3, "2024-01-02T00:00:00Z"),
    )

    old_before_change = resolve_at(nasdaq, "OLD", records, "2019-02-01T00:00:00Z")
    new_before_transfer = resolve_at(nasdaq, "NEW", records, "2021-01-01T00:00:00Z")
    new_after_transfer = resolve_at(nyse, "NEW", records, "2022-02-01T00:00:00Z")
    old_after_reuse = resolve_at(nasdaq, "OLD", records, "2024-02-01T00:00:00Z")

    assert old_before_change.classification is RecordResolutionClassification.RESOLVED
    assert old_before_change.target_assignment_proof_hashes
    assert old_before_change.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
    )
    assert new_before_transfer.targets == old_before_change.targets
    assert new_after_transfer.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(2)),
    )
    assert old_after_reuse.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(3)),
    )
    assert resolve_at(nasdaq, "old", records, "2019-02-01T00:00:00Z").targets == ()

    security_sa = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(10))
    security_sc = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(11))
    listing_links = (
        IdentityRelationshipVersionV1(
            schema_version="1",
            revision=revision(400),
            left=security_sa,
            right=old_before_change.targets[0],
            relationship_kind=IdentityRelationshipKind.SECURITY_HAS_LISTING,
            resolution_status=ResolutionStatus.RESOLVED,
            effective_interval=interval("2019-01-02T00:00:00Z", "2021-12-31T00:00:00Z"),
            source_relationship_code=None,
        ),
        IdentityRelationshipVersionV1(
            schema_version="1",
            revision=revision(410),
            left=security_sa,
            right=new_after_transfer.targets[0],
            relationship_kind=IdentityRelationshipKind.SECURITY_HAS_LISTING,
            resolution_status=ResolutionStatus.RESOLVED,
            effective_interval=interval("2022-01-03T00:00:00Z"),
            source_relationship_code=None,
        ),
        IdentityRelationshipVersionV1(
            schema_version="1",
            revision=revision(420),
            left=security_sc,
            right=old_after_reuse.targets[0],
            relationship_kind=IdentityRelationshipKind.SECURITY_HAS_LISTING,
            resolution_status=ResolutionStatus.RESOLVED,
            effective_interval=interval("2024-01-02T00:00:00Z"),
            source_relationship_code=None,
        ),
    )
    retained_references = {
        identity_reference(assignment.identity) for assignment in history_assignments()
    }
    assert {
        endpoint for link in listing_links for endpoint in (link.left, link.right)
    }.issubset(retained_references)
    assert listing_links[0].left == listing_links[1].left == security_sa
    assert listing_links[2].left == security_sc != security_sa


def test_mapping_resolution_rejects_assignment_venue_mismatch() -> None:
    """An XNYS namespace cannot authorize an XNAS retained listing identity."""
    namespace = ticker_namespace(ListingVenue.XNYS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                430,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    with pytest.raises(DatasetValidationError, match="namespace_venue_mismatch"):
        resolve_external_identifier(
            inputs.namespace,
            inputs.value,
            inputs.records,
            inputs.query,
            inputs.bundle,
            inputs.manifest,
            inputs.decision,
            inputs.policy,
            {},
            assignments=inputs.assignments,
            assignment_manifest=inputs.assignment_manifest,
            assignment_decision=inputs.assignment_decision,
            lifecycle_events=inputs.lifecycle_events,
            lifecycle_manifest=inputs.lifecycle_manifest,
            lifecycle_decision=inputs.lifecycle_decision,
            terminations=inputs.terminations,
            termination_manifest=inputs.termination_manifest,
            termination_decision=inputs.termination_decision,
        )


def test_mapping_interval_cannot_outlive_validated_listing_lifecycle() -> None:
    """An open identity assignment cannot hide a known listing termination."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (mapping(435, namespace, "OLD", 1, "2019-01-02T00:00:00Z"),),
        "2019-02-01T00:00:00Z",
    )
    assignments = tuple(
        assignment.model_copy(
            update={"effective_interval": interval("2019-01-02T00:00:00Z")}
        )
        if identity_reference(assignment.identity)
        == IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1))
        else assignment
        for assignment in inputs.assignments
    )
    assignments = tuple(
        assignment.model_copy(
            update={
                "revision": assignment.revision.model_copy(
                    update={
                        "payload_hash": content_hash(
                            assertion_version_payload(assignment)
                        )
                    }
                )
            }
        )
        for assignment in assignments
    )

    with pytest.raises(DatasetValidationError, match="outside_target_interval"):
        invoke_resolution(
            with_assignment_context(inputs, assignments, "2026-01-01T00:00:00Z")
        )


def test_assignment_authorization_uses_as_known_selected_revision() -> None:
    """A future unassignment cannot alter an earlier mapping authorization."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                440,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    initial = next(
        assignment
        for assignment in inputs.assignments
        if identity_reference(assignment.identity)
        == IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1))
    )
    future_unassignment = initial.model_copy(
        update={
            "revision": initial.revision.model_copy(
                update={
                    "record_version_id": uid(550),
                    "revision_kind": RevisionKind.CORRECTION,
                    "supersedes_record_version_id": initial.revision.record_version_id,
                    "source_sequence": 1,
                    "availability": (public_availability("2027-01-01T00:00:00Z"),),
                }
            ),
            "assignment_effect": IdentityAssignmentEffect.UNASSIGNED,
        }
    )
    future_unassignment = future_unassignment.model_copy(
        update={
            "revision": future_unassignment.revision.model_copy(
                update={
                    "payload_hash": content_hash(
                        assertion_version_payload(future_unassignment)
                    )
                }
            )
        }
    )
    assignments = inputs.assignments + (future_unassignment,)
    assert invoke_resolution(
        with_assignment_context(inputs, assignments, "2026-01-01T00:00:00Z")
    )
    with pytest.raises(DatasetValidationError, match="assignment_unassigned"):
        invoke_resolution(
            with_assignment_context(inputs, assignments, "2028-01-01T00:00:00Z")
        )


@pytest.mark.parametrize(
    "field",
    (
        "source_manifest_hash",
        "validation_decision_hash",
        "dataset_role_hash",
        "record_contract_hash",
        "schema_hash",
    ),
)
def test_mapping_query_rejects_each_dataset_binding_mismatch(field: str) -> None:
    """Every mapping dataset discriminator is enforced at the selection boundary."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                460,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    query = NormalizedSelectionQueryV1.model_validate(
        inputs.query.model_dump(mode="python") | {field: "b" * 64}
    )
    with pytest.raises(
        DatasetValidationError, match="selection_query_dataset_mismatch"
    ):
        invoke_resolution(inputs, query=query)


def test_mapping_query_rejects_wrong_context_and_accepts_current_mode() -> None:
    """Bundle drift fails, while an explicit ex-post mapping replay remains valid."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                470,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    wrong_bundle = NormalizedSelectionQueryV1.model_validate(
        inputs.query.model_dump(mode="python") | {"context_bundle_hashes": ("b" * 64,)}
    )
    with pytest.raises(DatasetValidationError, match="context_bundle_hash_mismatch"):
        invoke_resolution(inputs, query=wrong_bundle)
    current_mode = NormalizedSelectionQueryV1.model_validate(
        inputs.query.model_dump(mode="python")
        | {
            "information_role": InformationRole.EX_POST_OUTCOME,
            "resolution_mode": ResolutionMode.CURRENT_INTERPRETATION,
        }
    )
    current = invoke_resolution(inputs, query=current_mode)
    assert current.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
    )


def test_mapping_query_rejects_wrong_purpose_and_requested_channel() -> None:
    """Purpose and channel are preserved when selecting target assignments."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                480,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    wrong_purpose = NormalizedSelectionQueryV1.model_validate(
        inputs.query.model_dump(mode="python")
        | {"purpose": M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY}
    )
    with pytest.raises(DatasetValidationError, match="purpose_required"):
        invoke_resolution(inputs, query=wrong_purpose)
    wrong_channel = NormalizedSelectionQueryV1.model_validate(
        inputs.query.model_dump(mode="python")
        | {
            "requested_channel": inputs.query.requested_channel.model_copy(
                update={"identifier": "different"}
            )
        }
    )
    unavailable = invoke_resolution(inputs, query=wrong_channel)
    assert unavailable.classification is RecordResolutionClassification.INDETERMINATE


def test_assignment_context_query_binds_exact_targets_and_mapping_k_e() -> None:
    """Assignment selection cannot use a different cutoff, time, channel, or policy."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                490,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    targets = tuple(
        sorted(
            {record.target for record in inputs.records},
            key=lambda item: (item.kind.value, str(item.internal_id)),
        )
    )
    assignment_query = _build_assignment_context_query(
        inputs.query,
        targets,
        inputs.assignment_manifest,
        inputs.assignment_decision,
    )
    assert assignment_query.subject_hash == content_hash({"mapping_targets": targets})
    assert assignment_query.knowledge_cutoff == inputs.query.knowledge_cutoff
    assert assignment_query.evaluation_time == inputs.query.evaluation_time
    assert assignment_query.requested_channel == inputs.query.requested_channel
    assert assignment_query.policy_id == inputs.query.policy_id
    assert assignment_query.policy_hash == inputs.query.policy_hash


def sourced_text(value: str | None) -> SourcedTextValueV1:
    """Build a sourced known or explicit-unknown text value."""
    return SourcedTextValueV1(
        status=(
            ClassificationValueStatus.UNKNOWN
            if value is None
            else ClassificationValueStatus.KNOWN
        ),
        value=value,
    )


_ASSERTION_ROLE_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    "schema_version": (LogicalType.STRING, False),
    "revision.logical_record_id": (LogicalType.STRING, False),
    "revision.record_version_id": (LogicalType.STRING, False),
    "revision.revision_kind": (LogicalType.STRING, False),
    "revision.supersedes_record_version_id": (LogicalType.STRING, True),
    "revision.source_sequence": (LogicalType.INTEGER, False),
    "revision.availability": (LogicalType.JSON, False),
    "revision.history_completeness": (LogicalType.STRING, False),
    "revision.source_native_revision_label": (LogicalType.STRING, True),
    "revision.source_artifact": (LogicalType.JSON, False),
    "revision.payload_hash": (LogicalType.STRING, False),
}

_ROLE_FIELDS: dict[str, dict[str, tuple[LogicalType, bool]]] = {
    "external_identifier_mapping": {
        "namespace": (LogicalType.JSON, False),
        "identifier_value": (LogicalType.STRING, False),
        "target": (LogicalType.JSON, False),
        "mapping_status": (LogicalType.STRING, False),
        "effective_interval": (LogicalType.JSON, False),
    },
    "security_classification": {
        "issuer_id": (LogicalType.STRING, False),
        "security_id": (LogicalType.STRING, False),
        "issuer_form": (LogicalType.STRING, False),
        "issuer_domicile": (LogicalType.JSON, False),
        "incorporation_country": (LogicalType.JSON, False),
        "instrument_form": (LogicalType.STRING, False),
        "share_class_label": (LogicalType.JSON, False),
        "domestic_status": (LogicalType.STRING, False),
        "effective_interval": (LogicalType.JSON, False),
        "source_taxonomy_id": (LogicalType.STRING, False),
        "source_taxonomy_version": (LogicalType.STRING, False),
        "source_fields": (LogicalType.JSON, False),
    },
    "listing_role": {
        "security_id": (LogicalType.STRING, False),
        "listing_id": (LogicalType.STRING, False),
        "role": (LogicalType.STRING, False),
        "methodology_id": (LogicalType.STRING, False),
        "methodology_version": (LogicalType.STRING, False),
        "effective_interval": (LogicalType.JSON, False),
    },
    "listing_lifecycle": {
        "listing_id": (LogicalType.STRING, False),
        "event_kind": (LogicalType.STRING, False),
        "effective_time": (LogicalType.JSON, False),
        "related_listing_id": (LogicalType.STRING, True),
    },
    "listing_termination": {
        "listing_id": (LogicalType.STRING, False),
        "reason": (LogicalType.STRING, False),
        "source_reason_code": (LogicalType.STRING, True),
        "source_reason_text": (LogicalType.STRING, True),
        "last_regular_trade_time": (LogicalType.JSON, False),
        "effective_time": (LogicalType.JSON, False),
        "successor_relationship_ids": (LogicalType.JSON, False),
        "outcome_evidence_status": (LogicalType.STRING, False),
    },
    "listing_history_coverage": {
        "listing_id": (LogicalType.STRING, False),
        "coverage_status": (LogicalType.STRING, False),
        "complete_through": (LogicalType.JSON, False),
    },
}


def exact_role_schema(role: str) -> SchemaDescriptorV1:
    """Build the literal role schema required by the executable plan."""
    expected = _ASSERTION_ROLE_FIELDS | _ROLE_FIELDS[role]
    fields = tuple(
        FieldDescriptorV1(
            field_id=field_id,
            name=field_id,
            logical_type=logical_type,
            nullable=nullable,
        )
        for field_id, (logical_type, nullable) in expected.items()
    )
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1",
        fields=tuple(sorted(fields, key=lambda item: item.field_id)),
        schema_hash="b" * 64,
    )
    return SchemaDescriptorV1(
        schema_version="1",
        fields=provisional.fields,
        schema_hash=schema_hash(provisional),
    )


def role_dataset(
    role: str,
    records: tuple[
        ExternalIdentifierMappingVersionV1
        | SecurityClassificationVersionV1
        | ListingRoleVersionV1
        | ListingLifecycleVersionV1
        | ListingTerminationVersionV1
        | ListingHistoryCoverageVersionV1,
        ...,
    ],
) -> tuple[DatasetManifestV2, VerifiedArtifactBytes]:
    """Build exact bytes and an exact-schema manifest for one role."""
    data = canonical_json({"schema_version": "1", "records": records})
    digest = sha256(data).hexdigest()
    schema = exact_role_schema(role)
    base = fixed_manifest(role)
    partition = base.partitions[0]
    partition = partition.model_copy(
        update={
            "artifact": partition.artifact.model_copy(
                update={
                    "content_hash": digest,
                    "location": f"drift+sha256://{digest}",
                }
            ),
            "byte_size": len(data),
            "row_count": len(records),
            "schema_hash": schema.schema_hash,
        }
    )
    effective_field = {
        "external_identifier_mapping": "effective_interval",
        "security_classification": "effective_interval",
        "listing_role": "effective_interval",
        "listing_lifecycle": "effective_time",
        "listing_termination": "effective_time",
        "listing_history_coverage": "complete_through",
    }[role]
    semantic_fields = tuple(
        field_id for field_id in _ROLE_FIELDS[role] if field_id != effective_field
    )
    contract = AssertionTemporalContractV1(
        contract_version="1",
        evidence_granularity=EvidenceGranularity.RECORD,
        logical_record_id_field_id="revision.logical_record_id",
        record_version_id_field_id="revision.record_version_id",
        revision_kind_field_id="revision.revision_kind",
        supersedes_field_id="revision.supersedes_record_version_id",
        source_sequence_field_id="revision.source_sequence",
        availability_field_id="revision.availability",
        source_artifact_field_id="revision.source_artifact",
        payload_hash_field_id="revision.payload_hash",
        effective_time_field_id=effective_field,
        effective_shape=(
            AssertionEffectiveShape.INTERVAL
            if effective_field == "effective_interval"
            else AssertionEffectiveShape.BOUNDARY
        ),
        semantic_state_field_ids=semantic_fields,
        declared_channels=base.temporal_contract.contract.declared_channels,
    )
    manifest = base.model_copy(
        update={
            "schema_definition": schema,
            "partitions": (partition,),
            "temporal_contract": TemporalContractBindingV2(
                kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
                contract=contract,
            ),
        }
    )
    return manifest, VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=digest,
    )


def role_validation_context(suffix: int) -> ValidationRunContextV1:
    """Build a deterministic context for real role-record validation."""
    return ValidationRunContextV1(
        decision_id=uid(suffix),
        validator_version="1",
        validator_implementation_hash="b" * 64,
        validation_profile_id="m1b-role-v1",
        validation_profile_hash="c" * 64,
        checked_at=datetime(2026, 9, 3, 12, tzinfo=UTC),
    )


_RELATIONSHIP_SCHEMA_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    "revision.logical_record_id": (LogicalType.STRING, False),
    "revision.record_version_id": (LogicalType.STRING, False),
    "revision.revision_kind": (LogicalType.STRING, False),
    "revision.supersedes_record_version_id": (LogicalType.STRING, True),
    "revision.source_sequence": (LogicalType.INTEGER, False),
    "revision.availability": (LogicalType.JSON, False),
    "revision.source_artifact": (LogicalType.JSON, False),
    "revision.payload_hash": (LogicalType.STRING, False),
    "effective_interval": (LogicalType.JSON, False),
    "relationship_kind": (LogicalType.STRING, False),
    "resolution_status": (LogicalType.STRING, False),
}

_ASSIGNMENT_SCHEMA_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    "revision.logical_record_id": (LogicalType.STRING, False),
    "revision.record_version_id": (LogicalType.STRING, False),
    "revision.revision_kind": (LogicalType.STRING, False),
    "revision.supersedes_record_version_id": (LogicalType.STRING, True),
    "revision.source_sequence": (LogicalType.INTEGER, False),
    "revision.availability": (LogicalType.JSON, False),
    "revision.source_artifact": (LogicalType.JSON, False),
    "revision.payload_hash": (LogicalType.STRING, False),
    "effective_interval": (LogicalType.JSON, False),
    "assignment_effect": (LogicalType.STRING, False),
}


def assignment_dataset(
    records: tuple[IdentityAssignmentVersionV1, ...],
) -> tuple[DatasetManifestV2, DatasetValidationDecisionV2]:
    """Validate exact assignment bytes through the accepted Task 2 contract."""
    fields = tuple(
        FieldDescriptorV1(
            field_id=field_id,
            name=field_id,
            logical_type=logical_type,
            nullable=nullable,
        )
        for field_id, (logical_type, nullable) in _ASSIGNMENT_SCHEMA_FIELDS.items()
    )
    ordered = tuple(sorted(fields, key=lambda item: item.field_id))
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=ordered, schema_hash="b" * 64
    )
    schema = SchemaDescriptorV1(
        schema_version="1", fields=ordered, schema_hash=schema_hash(provisional)
    )
    data = canonical_json({"schema_version": "1", "records": records})
    digest = sha256(data).hexdigest()
    base = fixed_manifest("identity_assignment")
    partition = base.partitions[0].model_copy(
        update={
            "artifact": base.partitions[0].artifact.model_copy(
                update={
                    "content_hash": digest,
                    "location": f"drift+sha256://{digest}",
                }
            ),
            "byte_size": len(data),
            "row_count": len(records),
            "schema_hash": schema.schema_hash,
        }
    )
    contract = AssertionTemporalContractV1(
        contract_version="1",
        evidence_granularity=EvidenceGranularity.RECORD,
        logical_record_id_field_id="revision.logical_record_id",
        record_version_id_field_id="revision.record_version_id",
        revision_kind_field_id="revision.revision_kind",
        supersedes_field_id="revision.supersedes_record_version_id",
        source_sequence_field_id="revision.source_sequence",
        availability_field_id="revision.availability",
        source_artifact_field_id="revision.source_artifact",
        payload_hash_field_id="revision.payload_hash",
        effective_time_field_id="effective_interval",
        effective_shape=AssertionEffectiveShape.INTERVAL,
        semantic_state_field_ids=("assignment_effect",),
        declared_channels=base.temporal_contract.contract.declared_channels,
    )
    manifest = base.model_copy(
        update={
            "schema_definition": schema,
            "partitions": (partition,),
            "temporal_contract": TemporalContractBindingV2(
                kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
                contract=contract,
            ),
        }
    )
    verified = VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=digest
    )
    decision = validate_identity_dataset(
        manifest, (verified,), role_validation_context(599)
    )
    assert decision.result is ValidationResult.PASS
    return manifest, decision


def relationship_dataset(
    records: tuple[IdentityRelationshipVersionV1, ...],
) -> tuple[DatasetManifestV2, DatasetValidationDecisionV2]:
    """Validate exact relationship bytes through the accepted Task 2 contract."""
    fields = tuple(
        FieldDescriptorV1(
            field_id=field_id,
            name=field_id,
            logical_type=logical_type,
            nullable=nullable,
        )
        for field_id, (logical_type, nullable) in _RELATIONSHIP_SCHEMA_FIELDS.items()
    )
    ordered = tuple(sorted(fields, key=lambda item: item.field_id))
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=ordered, schema_hash="b" * 64
    )
    schema = SchemaDescriptorV1(
        schema_version="1", fields=ordered, schema_hash=schema_hash(provisional)
    )
    data = canonical_json({"schema_version": "1", "records": records})
    digest = sha256(data).hexdigest()
    base = fixed_manifest("identity_relationship")
    partition = base.partitions[0]
    partition = partition.model_copy(
        update={
            "artifact": partition.artifact.model_copy(
                update={
                    "content_hash": digest,
                    "location": f"drift+sha256://{digest}",
                }
            ),
            "byte_size": len(data),
            "row_count": len(records),
            "schema_hash": schema.schema_hash,
        }
    )
    contract = AssertionTemporalContractV1(
        contract_version="1",
        evidence_granularity=EvidenceGranularity.RECORD,
        logical_record_id_field_id="revision.logical_record_id",
        record_version_id_field_id="revision.record_version_id",
        revision_kind_field_id="revision.revision_kind",
        supersedes_field_id="revision.supersedes_record_version_id",
        source_sequence_field_id="revision.source_sequence",
        availability_field_id="revision.availability",
        source_artifact_field_id="revision.source_artifact",
        payload_hash_field_id="revision.payload_hash",
        effective_time_field_id="effective_interval",
        effective_shape=AssertionEffectiveShape.INTERVAL,
        semantic_state_field_ids=("relationship_kind", "resolution_status"),
        declared_channels=base.temporal_contract.contract.declared_channels,
    )
    manifest = base.model_copy(
        update={
            "schema_definition": schema,
            "partitions": (partition,),
            "temporal_contract": TemporalContractBindingV2(
                kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
                contract=contract,
            ),
        }
    )
    verified = VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=digest
    )
    decision = validate_identity_dataset(
        manifest, (verified,), role_validation_context(601)
    )
    assert decision.result is ValidationResult.PASS
    return manifest, decision


def assignment_for_dependency(
    reference: IdentityReferenceV1, suffix: int
) -> IdentityAssignmentVersionV1:
    """Retain one typed identity assignment used by relationship resolution."""
    identity = (
        IssuerV1(schema_version="1", issuer_id=reference.internal_id)
        if reference.kind is IdentityKind.ISSUER
        else SecurityV1(schema_version="1", security_id=reference.internal_id)
        if reference.kind is IdentityKind.SECURITY
        else ListingV1(
            schema_version="1",
            listing_id=reference.internal_id,
            venue=ListingVenue.XNAS,
        )
    )
    record = IdentityAssignmentVersionV1(
        schema_version="1",
        revision=revision(suffix),
        identity=identity,
        source_namespace="synthetic-master",
        source_key=f"dependency-{reference.kind.value}-{reference.internal_id}",
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
        effective_interval=interval("2018-01-01T00:00:00Z"),
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def exact_dataset_query(
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    bundle: ValidatedDatasetBundleV1,
    *,
    purpose: M1bSelectionPurpose,
    subject: object,
    evaluation_time: str,
    knowledge_cutoff: str,
    resolution_mode: ResolutionMode,
    policy_id: str = "strict",
) -> NormalizedSelectionQueryV1:
    """Build a query bound to one exact role dataset and identity bundle."""
    information_role = (
        InformationRole.DECISION_INFORMATION
        if resolution_mode is ResolutionMode.AS_KNOWN
        else InformationRole.EX_POST_OUTCOME
    )
    values = query_for(decision, content_hash(bundle)).model_dump(mode="python")
    values.update(
        {
            "purpose": purpose,
            "information_role": information_role,
            "resolution_mode": resolution_mode,
            "subject_hash": content_hash(subject),
            "source_manifest_hash": decision.manifest_hash,
            "validation_decision_hash": content_hash(decision),
            "context_bundle_hashes": (content_hash(bundle),),
            "dataset_role_hash": content_hash(manifest.dataset_role),
            "record_contract_hash": content_hash(manifest.temporal_contract.contract),
            "schema_hash": manifest.schema_definition.schema_hash,
            "knowledge_cutoff": parse_utc(knowledge_cutoff),
            "evaluation_time": parse_utc(evaluation_time),
            "policy_id": policy_id,
            "policy_hash": content_hash(AvailabilityPolicyV1(policy_id=policy_id)),
        }
    )
    return NormalizedSelectionQueryV1.model_validate(values)


@dataclass(frozen=True)
class RoleResolutionInputs:
    """One role query plus authenticated dependent relationship evidence."""

    query: NormalizedSelectionQueryV1
    bundle: ValidatedDatasetBundleV1
    manifest: DatasetManifestV2
    decision: DatasetValidationDecisionV2
    policy: AvailabilityPolicyV1
    assignments: tuple[IdentityAssignmentVersionV1, ...]
    assignment_manifest: DatasetManifestV2
    assignment_decision: DatasetValidationDecisionV2
    relationships: tuple[IdentityRelationshipVersionV1, ...]
    relationship_manifest: DatasetManifestV2
    relationship_decision: DatasetValidationDecisionV2
    relationship_resolution: IdentityResolutionResultV1
    relationship_proof: CutoffSelectionProofV1


def role_resolution_inputs(
    role: str,
    records: tuple[SecurityClassificationVersionV1 | ListingRoleVersionV1, ...],
    relationships: tuple[IdentityRelationshipVersionV1, ...],
    relationship_subject: IdentityReferenceV1,
    role_subject: object,
    *,
    evaluation_time: str = "2020-01-01T00:00:00Z",
    knowledge_cutoff: str = "2026-01-01T00:00:00Z",
    resolution_mode: ResolutionMode = ResolutionMode.AS_KNOWN,
) -> RoleResolutionInputs:
    """Build real role and relationship decisions with a shared exact context."""
    manifest, role_bytes = role_dataset(role, records)
    decision = validate_identity_dataset(
        manifest,
        (role_bytes,),
        role_validation_context(602 if role == "security_classification" else 603),
    )
    assert decision.result is ValidationResult.PASS
    relationship_manifest, relationship_decision = relationship_dataset(relationships)
    endpoints = tuple(
        sorted(
            {
                endpoint
                for relationship in relationships
                for endpoint in (relationship.left, relationship.right)
            },
            key=lambda item: (item.kind.value, str(item.internal_id)),
        )
    )
    assignments = tuple(
        assignment_for_dependency(reference, 7000 + index)
        for index, reference in enumerate(endpoints)
    )
    assignment_manifest, assignment_decision = assignment_dataset(assignments)
    bundle = build_validated_dataset_bundle(
        uid(980),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (manifest, decision),
            (relationship_manifest, relationship_decision),
            (assignment_manifest, assignment_decision),
        ),
    )
    policy = AvailabilityPolicyV1(policy_id="strict")
    relationship_query = exact_dataset_query(
        relationship_manifest,
        relationship_decision,
        bundle,
        purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
        subject=relationship_subject,
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
    )
    relationship_resolution = resolve_identity(
        relationship_subject,
        assignments,
        relationships,
        relationship_query,
        bundle,
        relationship_manifest,
        relationship_decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    chains: dict[UUID, list[IdentityRelationshipVersionV1]] = {}
    for relationship in relationships:
        chains.setdefault(relationship.revision.logical_record_id, []).append(
            relationship
        )
    selections: list[AssertionSelectionResultV1] = []
    for chain in chains.values():
        selections.append(
            _select_identity_chain(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=item.revision, record_hash=content_hash(item)
                    )
                    for item in chain
                ),
                relationship_query,
                policy,
                {},
            )
        )
    relationship_proof = build_cutoff_selection_proof(
        relationship_query,
        tuple(selections),
        relationship_manifest,
        relationship_decision,
        (bundle,),
        "bf61c84a232e0d5c11a99b6451f9a43f37f96dab220c1c7036456252394c961d",
    )
    assert relationship_resolution.selection_proof_hashes == (
        content_hash(relationship_proof),
    )
    query = exact_dataset_query(
        manifest,
        decision,
        bundle,
        purpose=M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        subject=role_subject,
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
    )
    return RoleResolutionInputs(
        query=query,
        bundle=bundle,
        manifest=manifest,
        decision=decision,
        policy=policy,
        assignments=assignments,
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
        relationships=relationships,
        relationship_manifest=relationship_manifest,
        relationship_decision=relationship_decision,
        relationship_resolution=relationship_resolution,
        relationship_proof=relationship_proof,
    )


def classification_record(
    suffix: int,
    *,
    issuer: int = 20,
    security: int = 21,
    issuer_form: IssuerForm = IssuerForm.OPERATING_COMPANY,
    instrument_form: InstrumentForm = InstrumentForm.COMMON_SHARE,
    domestic_status: DomesticStatus = DomesticStatus.DOMESTIC,
    domicile: str | None = "US",
    incorporation: str | None = "US",
    share_class: str | None = "Class A",
    start: str = "2019-01-02T00:00:00Z",
    end: str | None = None,
) -> SecurityClassificationVersionV1:
    """Build one source-backed classification assertion for a synthetic share."""
    record = SecurityClassificationVersionV1(
        schema_version="1",
        revision=revision(suffix),
        issuer_id=uid(issuer),
        security_id=uid(security),
        issuer_form=issuer_form,
        issuer_domicile=sourced_text(domicile),
        incorporation_country=sourced_text(incorporation),
        instrument_form=instrument_form,
        share_class_label=sourced_text(share_class),
        domestic_status=domestic_status,
        effective_interval=interval(start, end),
        source_taxonomy_id="synthetic-security-taxonomy",
        source_taxonomy_version="1",
        source_fields={"native_kind": "common"},
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def issuer_security_relationship(
    suffix: int = 610,
    *,
    issuer: int = 20,
    security: int = 21,
    start: str = "2019-01-02T00:00:00Z",
    end: str | None = None,
) -> IdentityRelationshipVersionV1:
    """Build one authenticated issuer-to-security identity relationship."""
    record = IdentityRelationshipVersionV1(
        schema_version="1",
        revision=revision(suffix),
        left=IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=uid(issuer)),
        right=IdentityReferenceV1(
            kind=IdentityKind.SECURITY, internal_id=uid(security)
        ),
        relationship_kind=IdentityRelationshipKind.ISSUER_HAS_SECURITY,
        resolution_status=ResolutionStatus.RESOLVED,
        effective_interval=interval(start, end),
        source_relationship_code="issued",
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def classification_inputs(
    records: tuple[SecurityClassificationVersionV1, ...],
    *,
    issuer: int = 20,
    security: int = 21,
    relationships: tuple[IdentityRelationshipVersionV1, ...] | None = None,
    evaluation_time: str = "2020-01-01T00:00:00Z",
    knowledge_cutoff: str = "2026-01-01T00:00:00Z",
    resolution_mode: ResolutionMode = ResolutionMode.AS_KNOWN,
) -> RoleResolutionInputs:
    """Build exact classification K/E and validation context."""
    relationship_records = (
        (issuer_security_relationship(issuer=issuer, security=security),)
        if relationships is None
        else relationships
    )
    return role_resolution_inputs(
        "security_classification",
        records,
        relationship_records,
        IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=uid(issuer)),
        {"issuer_id": uid(issuer), "security_id": uid(security)},
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
    )


def resolve_classification(
    records: tuple[SecurityClassificationVersionV1, ...],
    *,
    issuer: int = 20,
    security: int = 21,
    relationships: tuple[IdentityRelationshipVersionV1, ...] | None = None,
    evaluation_time: str = "2020-01-01T00:00:00Z",
    knowledge_cutoff: str = "2026-01-01T00:00:00Z",
    resolution_mode: ResolutionMode = ResolutionMode.AS_KNOWN,
) -> SecurityClassificationResolutionV1:
    """Resolve one classification from its retained assertion set."""
    inputs = classification_inputs(
        records,
        issuer=issuer,
        security=security,
        relationships=relationships,
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
    )
    return invoke_classification(records, inputs, issuer=issuer, security=security)


def invoke_classification(
    records: tuple[SecurityClassificationVersionV1, ...],
    inputs: RoleResolutionInputs,
    *,
    issuer: int = 20,
    security: int = 21,
    query: NormalizedSelectionQueryV1 | None = None,
    relationships: tuple[IdentityRelationshipVersionV1, ...] | None = None,
    relationship_resolution: IdentityResolutionResultV1 | None = None,
    relationship_proof: CutoffSelectionProofV1 | None = None,
) -> SecurityClassificationResolutionV1:
    """Invoke classification with individually replaceable proof inputs."""
    return resolve_security_classification(
        uid(issuer),
        uid(security),
        records,
        inputs.query if query is None else query,
        inputs.bundle,
        inputs.manifest,
        inputs.decision,
        inputs.policy,
        {},
        identity_assignments=inputs.assignments,
        assignment_manifest=inputs.assignment_manifest,
        assignment_decision=inputs.assignment_decision,
        identity_relationships=(
            inputs.relationships if relationships is None else relationships
        ),
        relationship_resolution=(
            inputs.relationship_resolution
            if relationship_resolution is None
            else relationship_resolution
        ),
        relationship_proof=(
            inputs.relationship_proof
            if relationship_proof is None
            else relationship_proof
        ),
        relationship_manifest=inputs.relationship_manifest,
        relationship_decision=inputs.relationship_decision,
    )


def test_sourced_text_requires_known_value_and_unknown_absence() -> None:
    """Text cannot silently switch between a source value and source absence."""
    with pytest.raises(ValidationError, match="known"):
        SourcedTextValueV1(status=ClassificationValueStatus.KNOWN, value=None)
    with pytest.raises(ValidationError, match="unknown"):
        SourcedTextValueV1(status=ClassificationValueStatus.UNKNOWN, value="US")


@pytest.mark.parametrize(
    "record",
    (
        classification_record(600, issuer_form=IssuerForm.FUND),
        classification_record(610, issuer_form=IssuerForm.REIT),
        classification_record(620, issuer_form=IssuerForm.TRUST),
        classification_record(630, issuer_form=IssuerForm.ACQUISITION_COMPANY),
        classification_record(640, issuer_form=IssuerForm.OTHER),
        classification_record(650, instrument_form=InstrumentForm.PREFERRED),
        classification_record(660, instrument_form=InstrumentForm.RECEIPT),
        classification_record(670, instrument_form=InstrumentForm.UNIT),
        classification_record(680, instrument_form=InstrumentForm.WARRANT),
        classification_record(690, instrument_form=InstrumentForm.RIGHT),
        classification_record(700, instrument_form=InstrumentForm.OTHER),
        classification_record(710, domestic_status=DomesticStatus.FOREIGN),
    ),
)
def test_explicitly_excluded_categories_are_unsupported(
    record: SecurityClassificationVersionV1,
) -> None:
    """Every initial-scope issuer, instrument, and foreign exclusion stays explicit."""
    assert (
        resolve_classification((record,)).classification
        is SecurityClassificationStatus.UNSUPPORTED
    )


@pytest.mark.parametrize(
    "record",
    (
        classification_record(720, issuer_form=IssuerForm.UNKNOWN),
        classification_record(730, instrument_form=InstrumentForm.UNKNOWN),
        classification_record(740, domestic_status=DomesticStatus.INDETERMINATE),
        classification_record(750, domicile=None),
        classification_record(760, incorporation=None),
        classification_record(770, share_class=None),
    ),
)
def test_unknown_classification_evidence_is_indeterminate(
    record: SecurityClassificationVersionV1,
) -> None:
    """Missing source facts cannot be relabeled as a policy exclusion."""
    assert (
        resolve_classification((record,)).classification
        is SecurityClassificationStatus.INDETERMINATE
    )


def test_supported_classification_is_bound_to_both_typed_ids() -> None:
    """A source-supported domestic common share resolves only for its exact pair."""
    record = classification_record(780)
    result = resolve_classification((record,))
    assert result.classification is SecurityClassificationStatus.SUPPORTED
    inputs = classification_inputs((record,))
    with pytest.raises(DatasetValidationError, match="subject_hash"):
        resolve_security_classification(
            uid(20),
            uid(22),
            (record,),
            inputs.query,
            inputs.bundle,
            inputs.manifest,
            inputs.decision,
            inputs.policy,
            {},
            identity_assignments=inputs.assignments,
            assignment_manifest=inputs.assignment_manifest,
            assignment_decision=inputs.assignment_decision,
            identity_relationships=inputs.relationships,
            relationship_resolution=inputs.relationship_resolution,
            relationship_proof=inputs.relationship_proof,
            relationship_manifest=inputs.relationship_manifest,
            relationship_decision=inputs.relationship_decision,
        )


def test_classification_persists_authenticated_issuer_security_provenance() -> None:
    """Supported classification retains the actual link result and proof hashes."""
    record = classification_record(782)
    relationship = issuer_security_relationship(783)
    inputs = classification_inputs((record,), relationships=(relationship,))

    result = invoke_classification((record,), inputs)

    assert result.dependent_relationship_proof_hashes == (
        content_hash(inputs.relationship_proof),
    )
    assert result.dependent_identity_resolution_hashes == (
        content_hash(inputs.relationship_resolution),
    )
    assert result.selected_relationship_record_hashes == (content_hash(relationship),)
    assert set(result.dependent_relationship_proof_hashes).isdisjoint(
        result.evidence.selection_proof_hashes
    )


def test_classification_rejects_raw_or_inactive_issuer_security_link() -> None:
    """A caller-created or inactive link cannot authorize supported classification."""
    record = classification_record(784)
    relationship = issuer_security_relationship(785)
    inputs = classification_inputs((record,), relationships=(relationship,))
    forged = issuer_security_relationship(786, issuer=20, security=22)
    with pytest.raises(DatasetValidationError, match="relationship_record_set"):
        invoke_classification((record,), inputs, relationships=(forged,))

    inactive = issuer_security_relationship(
        787,
        start="2018-01-01T00:00:00Z",
        end="2019-01-01T00:00:00Z",
    )
    inactive_inputs = classification_inputs((record,), relationships=(inactive,))
    with pytest.raises(DatasetValidationError, match="active_issuer_has_security"):
        invoke_classification((record,), inactive_inputs)


@pytest.mark.parametrize(
    "field",
    (
        "subject_hash",
        "source_manifest_hash",
        "validation_decision_hash",
        "context_bundle_hashes",
        "dataset_role_hash",
        "record_contract_hash",
        "schema_hash",
        "knowledge_cutoff",
        "evaluation_time",
        "requested_channel",
        "policy_id",
        "policy_hash",
        "resolution_mode",
        "information_role",
    ),
)
def test_classification_rejects_each_relationship_query_mismatch(field: str) -> None:
    """Dependent identity evidence must share exact query and dataset bindings."""
    record = classification_record(788)
    inputs = classification_inputs((record,))
    query = inputs.relationship_proof.normalized_query
    replacement: object = "b" * 64
    if field in {"knowledge_cutoff", "evaluation_time"}:
        replacement = parse_utc("2025-12-31T00:00:00Z")
    elif field == "requested_channel":
        replacement = query.requested_channel.model_copy(
            update={"identifier": "other-channel"}
        )
    elif field == "policy_id":
        replacement = "other-policy"
    elif field == "context_bundle_hashes":
        replacement = ("b" * 64,)
    query_update = {field: replacement}
    if field in {"resolution_mode", "information_role"}:
        query_update.update(
            {
                "resolution_mode": ResolutionMode.CURRENT_INTERPRETATION,
                "information_role": InformationRole.EX_POST_OUTCOME,
            }
        )
    mutated_query = query.model_copy(update=query_update)
    proof_update: dict[str, object] = {
        "normalized_query": mutated_query,
        "normalized_query_hash": content_hash(mutated_query),
    }
    if field == "source_manifest_hash":
        proof_update["source_manifest_hash"] = replacement
    if field == "validation_decision_hash":
        proof_update["validation_decision_hash"] = replacement
    mutated_proof = inputs.relationship_proof.model_copy(update=proof_update)

    with pytest.raises(DatasetValidationError, match="relationship_"):
        invoke_classification((record,), inputs, relationship_proof=mutated_proof)


def test_classification_rejects_identity_result_not_bound_to_actual_proof() -> None:
    """A matching raw link and proof still require the actual identity result."""
    record = classification_record(789)
    inputs = classification_inputs((record,))
    forged_result = inputs.relationship_resolution.model_copy(
        update={"selection_proof_hashes": ("f" * 64,)}
    )

    with pytest.raises(DatasetValidationError, match="relationship_resolution"):
        invoke_classification((record,), inputs, relationship_resolution=forged_result)


def test_classification_rejects_manufactured_schema_wrong_decision() -> None:
    """Record hashes cannot upgrade an assignment schema into classification proof."""
    record = classification_record(781)
    inputs = classification_inputs((record,))
    manifest = fixed_manifest("security_classification")
    decision = passing_decision("security_classification").model_copy(
        update={
            "validation_scope": ValidationScope.RECORDS,
            "validated_record_hashes": (content_hash(record),),
        }
    )
    bundle = build_validated_dataset_bundle(
        uid(961),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (manifest, decision),
            (inputs.relationship_manifest, inputs.relationship_decision),
        ),
    )
    query = exact_dataset_query(
        manifest,
        decision,
        bundle,
        purpose=M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        subject={"issuer_id": uid(20), "security_id": uid(21)},
        evaluation_time="2020-01-01T00:00:00Z",
        knowledge_cutoff="2026-01-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )

    with pytest.raises(DatasetValidationError, match="schema_or_contract"):
        resolve_security_classification(
            uid(20),
            uid(21),
            (record,),
            query,
            bundle,
            manifest,
            decision,
            inputs.policy,
            {},
            identity_assignments=inputs.assignments,
            assignment_manifest=inputs.assignment_manifest,
            assignment_decision=inputs.assignment_decision,
            identity_relationships=inputs.relationships,
            relationship_resolution=inputs.relationship_resolution,
            relationship_proof=inputs.relationship_proof,
            relationship_manifest=inputs.relationship_manifest,
            relationship_decision=inputs.relationship_decision,
        )


def test_conflicting_active_classification_is_not_an_exclusion() -> None:
    """Contradictory source assertions remain indeterminate rather than unsupported."""
    supported = classification_record(790)
    excluded = classification_record(800, instrument_form=InstrumentForm.PREFERRED)
    assert (
        resolve_classification((supported, excluded)).classification
        is SecurityClassificationStatus.CONFLICT
    )


def test_inactive_unknown_classification_does_not_poison_active_evidence() -> None:
    """Only active or temporally uncertain classifications can affect E."""
    active = classification_record(801)
    historical_unknown = classification_record(
        802,
        issuer_form=IssuerForm.UNKNOWN,
        start="2018-01-01T00:00:00Z",
        end="2019-01-01T00:00:00Z",
    )
    future_unknown = classification_record(
        803,
        instrument_form=InstrumentForm.UNKNOWN,
        start="2021-01-01T00:00:00Z",
    )

    result = resolve_classification((active, historical_unknown, future_unknown))

    assert result.classification is SecurityClassificationStatus.SUPPORTED


def test_two_share_classes_keep_classification_bound_to_each_security() -> None:
    """Two classes under one issuer never share one classification assertion."""
    class_a = classification_record(804, security=21, share_class="Class A")
    class_b = classification_record(805, security=22, share_class="Class B")
    relationships = (
        issuer_security_relationship(806, security=21),
        issuer_security_relationship(807, security=22),
    )

    result_a = resolve_classification(
        (class_a, class_b), security=21, relationships=relationships
    )
    result_b = resolve_classification(
        (class_a, class_b), security=22, relationships=relationships
    )

    assert result_a.classification is SecurityClassificationStatus.SUPPORTED
    assert result_b.classification is SecurityClassificationStatus.SUPPORTED
    assert result_a.evidence.selected_record_hashes == (content_hash(class_a),)
    assert result_b.evidence.selected_record_hashes == (content_hash(class_b),)
    assert (
        result_a.evidence.normalized_query.subject_hash
        != result_b.evidence.normalized_query.subject_hash
    )


def test_classification_current_interpretation_selects_retained_correction() -> None:
    """Audit mode selects the manifest-current correction without changing replay."""
    original = classification_record(808)
    correction = original.model_copy(
        update={
            "revision": original.revision.model_copy(
                update={
                    "record_version_id": uid(809),
                    "revision_kind": RevisionKind.CORRECTION,
                    "supersedes_record_version_id": original.revision.record_version_id,
                    "source_sequence": 1,
                    "availability": (public_availability("2027-01-01T00:00:00Z"),),
                }
            ),
            "instrument_form": InstrumentForm.PREFERRED,
        }
    )
    correction = correction.model_copy(
        update={
            "revision": correction.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(correction))
                }
            )
        }
    )
    relationship = issuer_security_relationship(811)

    replay = resolve_classification(
        (original, correction),
        relationships=(relationship,),
        knowledge_cutoff="2026-01-01T00:00:00Z",
    )
    current = resolve_classification(
        (original, correction),
        relationships=(relationship,),
        knowledge_cutoff="2026-01-01T00:00:00Z",
        resolution_mode=ResolutionMode.CURRENT_INTERPRETATION,
    )

    assert replay.classification is SecurityClassificationStatus.SUPPORTED
    assert replay.evidence.selected_record_hashes == (content_hash(original),)
    assert current.classification is SecurityClassificationStatus.UNSUPPORTED
    assert current.evidence.selected_record_hashes == (content_hash(correction),)


def test_classification_result_rejects_subject_proof_and_outcome_tampering() -> None:
    """Persisted classification fields cannot drift from their bound evidence."""
    result = resolve_classification((classification_record(812),))
    with pytest.raises(ValidationError, match="subject"):
        result.model_copy(update={"security_id": uid(99)})
    with pytest.raises(ValidationError, match="selection proof"):
        result.model_copy(
            update={
                "evidence": result.evidence.model_copy(
                    update={"selection_proof_hashes": ()}
                )
            }
        )
    with pytest.raises(ValidationError, match="relationship proof"):
        result.model_copy(
            update={
                "dependent_relationship_proof_hashes": (
                    result.evidence.selection_proof_hashes[0],
                )
            }
        )
    with pytest.raises(ValidationError, match="subject|outcome binding"):
        result.model_copy(
            update={"classification": SecurityClassificationStatus.UNSUPPORTED}
        )


def role_record(
    suffix: int,
    listing: int,
    *,
    security: int = 21,
    role: ListingRole = ListingRole.PRIMARY,
    methodology: str = "synthetic-primary-v1",
    start: str = "2019-01-02T00:00:00Z",
    end: str | None = None,
) -> ListingRoleVersionV1:
    """Build one dated primary-listing methodology assertion."""
    record = ListingRoleVersionV1(
        schema_version="1",
        revision=revision(suffix),
        security_id=uid(security),
        listing_id=uid(listing),
        role=role,
        methodology_id=methodology,
        methodology_version="1",
        effective_interval=interval(start, end),
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def lifecycle_record(
    suffix: int,
    event_kind: ListingLifecycleEventKind,
    effective_time: str | TemporalBoundaryClaimV1,
    *,
    listing: int = 1,
    related_listing: int | None = None,
) -> ListingLifecycleVersionV1:
    """Build one source-backed listing lifecycle event."""
    record = ListingLifecycleVersionV1(
        schema_version="1",
        revision=revision(suffix),
        listing_id=uid(listing),
        event_kind=event_kind,
        effective_time=(
            exact_boundary(effective_time)
            if isinstance(effective_time, str)
            else effective_time
        ),
        related_listing_id=(None if related_listing is None else uid(related_listing)),
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def termination_record(
    suffix: int,
    reason: ListingTerminationReason,
    *,
    listing: int = 1,
    last_trade: str | TemporalBoundaryClaimV1 = "2021-12-30T21:00:00Z",
    effective_time: str | TemporalBoundaryClaimV1 = "2021-12-31T00:00:00Z",
    successor_relationship_ids: tuple[UUID, ...] = (),
    source_reason_code: str | None = "SYNTHETIC",
    source_reason_text: str | None = "synthetic termination",
    outcome_status: OutcomeEvidenceStatus = OutcomeEvidenceStatus.UNKNOWN,
) -> ListingTerminationVersionV1:
    """Build one source-backed listing termination assertion."""
    record = ListingTerminationVersionV1(
        schema_version="1",
        revision=revision(suffix),
        listing_id=uid(listing),
        reason=reason,
        source_reason_code=source_reason_code,
        source_reason_text=source_reason_text,
        last_regular_trade_time=(
            exact_boundary(last_trade) if isinstance(last_trade, str) else last_trade
        ),
        effective_time=(
            exact_boundary(effective_time)
            if isinstance(effective_time, str)
            else effective_time
        ),
        successor_relationship_ids=successor_relationship_ids,
        outcome_evidence_status=outcome_status,
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def coverage_record(
    suffix: int,
    status: ListingHistoryCoverageStatus,
    complete_through: str | TemporalBoundaryClaimV1,
    *,
    listing: int = 1,
) -> ListingHistoryCoverageVersionV1:
    """Build one sourced statement about retained listing-history coverage."""
    record = ListingHistoryCoverageVersionV1(
        schema_version="1",
        revision=revision(suffix),
        listing_id=uid(listing),
        coverage_status=status,
        complete_through=(
            exact_boundary(complete_through)
            if isinstance(complete_through, str)
            else complete_through
        ),
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def hashed_mapping_record() -> ExternalIdentifierMappingVersionV1:
    """Build one payload-bound mapping record for typed role validation."""
    record = mapping(
        590,
        ticker_namespace(ListingVenue.XNAS),
        "OLD",
        1,
        "2019-01-02T00:00:00Z",
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


@pytest.mark.parametrize(
    ("role", "record", "checked_contract"),
    (
        (
            "security_classification",
            classification_record(591),
            "security-classification-v1",
        ),
        ("listing_role", role_record(592, 1), "listing-role-v1"),
        (
            "external_identifier_mapping",
            hashed_mapping_record(),
            "external-identifier-mapping-v1",
        ),
        (
            "listing_lifecycle",
            lifecycle_record(
                593,
                ListingLifecycleEventKind.ADMITTED,
                "2019-01-02T00:00:00Z",
            ),
            "listing-lifecycle-v1",
        ),
        (
            "listing_termination",
            termination_record(594, ListingTerminationReason.EXCHANGE_DELISTING),
            "listing-termination-v1",
        ),
        (
            "listing_history_coverage",
            coverage_record(
                595,
                ListingHistoryCoverageStatus.COMPLETE,
                "2026-01-01T00:00:00Z",
            ),
            "listing-history-coverage-v1",
        ),
    ),
)
def test_role_datasets_require_exact_schema_typed_parse_and_checked_contract(
    role: str,
    record: (
        ExternalIdentifierMappingVersionV1
        | SecurityClassificationVersionV1
        | ListingRoleVersionV1
        | ListingLifecycleVersionV1
        | ListingTerminationVersionV1
        | ListingHistoryCoverageVersionV1
    ),
    checked_contract: str,
) -> None:
    """A passing role decision proves the literal schema and parsed record type."""
    manifest, artifact_bytes = role_dataset(role, (record,))

    decision = validate_identity_dataset(
        manifest,
        (artifact_bytes,),
        role_validation_context(596),
    )

    assert decision.result is ValidationResult.PASS
    assert decision.schema_hash == exact_role_schema(role).schema_hash
    assert decision.validated_record_hashes == (content_hash(record),)
    assert checked_contract in decision.checked_contracts


@pytest.mark.parametrize(
    ("role", "record"),
    (
        ("security_classification", classification_record(595)),
        ("listing_role", role_record(596, 1)),
        ("external_identifier_mapping", hashed_mapping_record()),
        (
            "listing_lifecycle",
            lifecycle_record(
                597,
                ListingLifecycleEventKind.ADMITTED,
                "2019-01-02T00:00:00Z",
            ),
        ),
        (
            "listing_termination",
            termination_record(598, ListingTerminationReason.BANKRUPTCY),
        ),
        (
            "listing_history_coverage",
            coverage_record(
                599,
                ListingHistoryCoverageStatus.PARTIAL,
                "2020-01-01T00:00:00Z",
            ),
        ),
    ),
)
def test_role_dataset_rejects_schema_wrong_manifest(
    role: str,
    record: (
        ExternalIdentifierMappingVersionV1
        | SecurityClassificationVersionV1
        | ListingRoleVersionV1
        | ListingLifecycleVersionV1
        | ListingTerminationVersionV1
        | ListingHistoryCoverageVersionV1
    ),
) -> None:
    """A relabeled assignment schema cannot validate classification or role bytes."""
    _, artifact_bytes = role_dataset(role, (record,))
    wrong = fixed_manifest(role)
    partition = wrong.partitions[0]
    wrong = wrong.model_copy(
        update={
            "partitions": (
                partition.model_copy(
                    update={
                        "artifact": partition.artifact.model_copy(
                            update={
                                "content_hash": artifact_bytes.content_hash,
                                "location": (
                                    f"drift+sha256://{artifact_bytes.content_hash}"
                                ),
                            }
                        ),
                        "byte_size": artifact_bytes.byte_size,
                        "row_count": 1,
                    }
                ),
            )
        }
    )

    decision = validate_identity_dataset(
        wrong, (artifact_bytes,), role_validation_context(597)
    )

    assert decision.result is ValidationResult.FAIL
    assert "identity_role_schema_mismatch" in {
        finding.code for finding in decision.findings
    }


@pytest.mark.parametrize(
    ("role", "record", "semantic_field"),
    (
        ("security_classification", classification_record(598), "issuer_form"),
        ("listing_role", role_record(599, 1), "role"),
        (
            "external_identifier_mapping",
            hashed_mapping_record(),
            "mapping_status",
        ),
        (
            "listing_lifecycle",
            lifecycle_record(
                600,
                ListingLifecycleEventKind.ADMITTED,
                "2019-01-02T00:00:00Z",
            ),
            "event_kind",
        ),
        (
            "listing_termination",
            termination_record(601, ListingTerminationReason.MERGER),
            "reason",
        ),
        (
            "listing_history_coverage",
            coverage_record(
                602,
                ListingHistoryCoverageStatus.UNKNOWN,
                "2020-01-01T00:00:00Z",
            ),
            "coverage_status",
        ),
    ),
)
def test_role_dataset_rejects_incomplete_temporal_contract(
    role: str,
    record: (
        ExternalIdentifierMappingVersionV1
        | SecurityClassificationVersionV1
        | ListingRoleVersionV1
        | ListingLifecycleVersionV1
        | ListingTerminationVersionV1
        | ListingHistoryCoverageVersionV1
    ),
    semantic_field: str,
) -> None:
    """The checked role contract must bind every required semantic field."""
    manifest, artifact_bytes = role_dataset(role, (record,))
    contract = manifest.temporal_contract.contract
    assert isinstance(contract, AssertionTemporalContractV1)
    wrong_contract = contract.model_copy(
        update={"semantic_state_field_ids": (semantic_field,)}
    )
    wrong_manifest = manifest.model_copy(
        update={
            "temporal_contract": manifest.temporal_contract.model_copy(
                update={"contract": wrong_contract}
            )
        }
    )

    decision = validate_identity_dataset(
        wrong_manifest, (artifact_bytes,), role_validation_context(600)
    )

    assert decision.result is ValidationResult.FAIL
    assert "identity_role_contract_mismatch" in {
        finding.code for finding in decision.findings
    }


@pytest.mark.parametrize(
    ("role", "wrong_record"),
    (
        ("security_classification", role_record(605, 1)),
        ("listing_role", classification_record(606)),
        (
            "external_identifier_mapping",
            lifecycle_record(
                607,
                ListingLifecycleEventKind.ADMITTED,
                "2019-01-02T00:00:00Z",
            ),
        ),
        (
            "listing_lifecycle",
            termination_record(608, ListingTerminationReason.VOLUNTARY_WITHDRAWAL),
        ),
        (
            "listing_termination",
            coverage_record(
                609,
                ListingHistoryCoverageStatus.COMPLETE,
                "2026-01-01T00:00:00Z",
            ),
        ),
        ("listing_history_coverage", hashed_mapping_record()),
    ),
)
def test_role_dataset_parser_rejects_the_other_role_record_type(
    role: str,
    wrong_record: (
        ExternalIdentifierMappingVersionV1
        | SecurityClassificationVersionV1
        | ListingRoleVersionV1
        | ListingLifecycleVersionV1
        | ListingTerminationVersionV1
        | ListingHistoryCoverageVersionV1
    ),
) -> None:
    """A correct envelope and schema cannot relabel another role's record type."""
    manifest, artifact_bytes = role_dataset(role, (wrong_record,))

    decision = validate_identity_dataset(
        manifest, (artifact_bytes,), role_validation_context(607)
    )

    assert decision.result is ValidationResult.FAIL
    assert "identity_record_invalid" in {finding.code for finding in decision.findings}


def relationship_record(
    security: int,
    listing: int,
    suffix: int = 810,
    *,
    start: str = "2019-01-02T00:00:00Z",
    end: str | None = None,
) -> IdentityRelationshipVersionV1:
    """Build the selected security-to-listing relationship required by a role."""
    record = IdentityRelationshipVersionV1(
        schema_version="1",
        revision=revision(suffix),
        left=IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(security)),
        right=IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(listing)),
        relationship_kind=IdentityRelationshipKind.SECURITY_HAS_LISTING,
        resolution_status=ResolutionStatus.RESOLVED,
        effective_interval=interval(start, end),
        source_relationship_code="listed",
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def primary_inputs(
    roles: tuple[ListingRoleVersionV1, ...],
    methodology: str = "synthetic-primary-v1",
    relationships: tuple[IdentityRelationshipVersionV1, ...] | None = None,
    *,
    evaluation_time: str = "2020-01-01T00:00:00Z",
    knowledge_cutoff: str = "2026-01-01T00:00:00Z",
    resolution_mode: ResolutionMode = ResolutionMode.AS_KNOWN,
) -> RoleResolutionInputs:
    """Build exact role K/E and validation context."""
    relationship_records = (
        (relationship_record(21, 1),) if relationships is None else relationships
    )
    return role_resolution_inputs(
        "listing_role",
        roles,
        relationship_records,
        IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(21)),
        {"security_id": uid(21), "methodology_id": methodology},
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
    )


def resolve_primary(
    roles: tuple[ListingRoleVersionV1, ...],
    relationships: tuple[IdentityRelationshipVersionV1, ...],
    methodology: str = "synthetic-primary-v1",
) -> PrimaryListingResolutionV1:
    """Resolve exactly one primary listing under a selected methodology."""
    inputs = primary_inputs(roles, methodology, relationships)
    return invoke_primary(roles, relationships, inputs, methodology=methodology)


def invoke_primary(
    roles: tuple[ListingRoleVersionV1, ...],
    relationships: tuple[IdentityRelationshipVersionV1, ...],
    inputs: RoleResolutionInputs,
    *,
    methodology: str = "synthetic-primary-v1",
    query: NormalizedSelectionQueryV1 | None = None,
    relationship_resolution: IdentityResolutionResultV1 | None = None,
    relationship_proof: CutoffSelectionProofV1 | None = None,
) -> PrimaryListingResolutionV1:
    """Invoke primary resolution with replaceable relationship proof inputs."""
    return resolve_primary_listing(
        uid(21),
        methodology,
        roles,
        relationships,
        inputs.query if query is None else query,
        inputs.bundle,
        inputs.manifest,
        inputs.decision,
        inputs.policy,
        {},
        identity_assignments=inputs.assignments,
        assignment_manifest=inputs.assignment_manifest,
        assignment_decision=inputs.assignment_decision,
        relationship_resolution=(
            inputs.relationship_resolution
            if relationship_resolution is None
            else relationship_resolution
        ),
        relationship_proof=(
            inputs.relationship_proof
            if relationship_proof is None
            else relationship_proof
        ),
        relationship_manifest=inputs.relationship_manifest,
        relationship_decision=inputs.relationship_decision,
    )


def test_listing_role_rejects_timeless_primary() -> None:
    """Primary status must always carry a time-scoped effective interval."""
    values = role_record(820, 1).model_dump(mode="python")
    values["effective_interval"] = None
    with pytest.raises(ValidationError):
        ListingRoleVersionV1.model_validate(values)


def test_same_methodology_overlapping_primaries_fail_validation() -> None:
    """One methodology cannot nominate two listings for the same instant."""
    with pytest.raises(DatasetValidationError, match="overlapping"):
        validate_listing_roles((role_record(830, 1), role_record(840, 2)))


def test_cross_methodology_primary_disagreement_remains_separate() -> None:
    """A selected methodology resolves independently of another provider's opinion."""
    first = role_record(850, 1)
    other = role_record(860, 2, methodology="other-primary-v1")
    validate_listing_roles((first, other))
    result = resolve_primary((first, other), (relationship_record(21, 1),))
    assert result.classification is RecordResolutionClassification.RESOLVED
    assert result.listing_id == uid(1)


def test_primary_persists_authenticated_security_listing_provenance() -> None:
    """A resolved primary retains the selected role, link, result, and proof."""
    role = role_record(853, 1)
    relationship = relationship_record(21, 1, 854)
    inputs = primary_inputs((role,), relationships=(relationship,))

    result = invoke_primary((role,), (relationship,), inputs)

    assert result.selected_role_record_hash == content_hash(role)
    assert result.selected_relationship_record_hashes == (content_hash(relationship),)
    assert result.dependent_relationship_proof_hashes == (
        content_hash(inputs.relationship_proof),
    )
    assert result.dependent_identity_resolution_hashes == (
        content_hash(inputs.relationship_resolution),
    )
    assert set(result.dependent_relationship_proof_hashes).isdisjoint(
        result.evidence.selection_proof_hashes
    )


def test_primary_rejects_raw_or_inactive_security_listing_link() -> None:
    """A raw or inactive relationship cannot authorize a primary listing."""
    role = role_record(855, 1)
    relationship = relationship_record(21, 1, 856)
    inputs = primary_inputs((role,), relationships=(relationship,))
    forged = relationship_record(21, 2, 857)
    with pytest.raises(DatasetValidationError, match="relationship_record_set"):
        invoke_primary((role,), (forged,), inputs)

    inactive = relationship.model_copy(
        update={
            "effective_interval": interval(
                "2018-01-01T00:00:00Z", "2019-01-01T00:00:00Z"
            )
        }
    )
    inactive = inactive.model_copy(
        update={
            "revision": inactive.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(inactive))
                }
            )
        }
    )
    inactive_inputs = primary_inputs((role,), relationships=(inactive,))
    with pytest.raises(DatasetValidationError, match="active_security_has_listing"):
        invoke_primary((role,), (inactive,), inactive_inputs)


def test_primary_rejects_relationship_proof_from_different_evaluation_time() -> None:
    """The primary result and dependent identity proof must use the same E."""
    role = role_record(858, 1)
    relationship = relationship_record(21, 1, 859)
    inputs = primary_inputs((role,), relationships=(relationship,))
    other = primary_inputs(
        (role,),
        relationships=(relationship,),
        evaluation_time="2020-02-01T00:00:00Z",
    )

    with pytest.raises(DatasetValidationError, match="relationship_query_context"):
        invoke_primary(
            (role,),
            (relationship,),
            inputs,
            relationship_resolution=other.relationship_resolution,
            relationship_proof=other.relationship_proof,
        )


def test_primary_resolver_rejects_two_independent_active_primaries() -> None:
    """Independent active role assertions cannot both win one methodology."""
    roles = (role_record(862, 1), role_record(863, 2))
    relationships = (
        relationship_record(21, 1, 864),
        relationship_record(21, 2, 865),
    )
    inputs = primary_inputs(roles, relationships=relationships)

    with pytest.raises(DatasetValidationError, match="overlapping_primary"):
        invoke_primary(roles, relationships, inputs)


def test_primary_rejects_manufactured_schema_wrong_decision() -> None:
    """Record hashes cannot upgrade an assignment schema into listing-role proof."""
    role = role_record(861, 1)
    relationship = relationship_record(21, 1)
    inputs = primary_inputs((role,), relationships=(relationship,))
    manifest = fixed_manifest("listing_role")
    decision = passing_decision("listing_role").model_copy(
        update={
            "validation_scope": ValidationScope.RECORDS,
            "validated_record_hashes": (content_hash(role),),
        }
    )
    bundle = build_validated_dataset_bundle(
        uid(971),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (manifest, decision),
            (inputs.relationship_manifest, inputs.relationship_decision),
        ),
    )
    query = exact_dataset_query(
        manifest,
        decision,
        bundle,
        purpose=M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        subject={"security_id": uid(21), "methodology_id": "synthetic-primary-v1"},
        evaluation_time="2020-01-01T00:00:00Z",
        knowledge_cutoff="2026-01-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )

    with pytest.raises(DatasetValidationError, match="schema_or_contract"):
        resolve_primary_listing(
            uid(21),
            "synthetic-primary-v1",
            (role,),
            (relationship,),
            query,
            bundle,
            manifest,
            decision,
            inputs.policy,
            {},
            identity_assignments=inputs.assignments,
            assignment_manifest=inputs.assignment_manifest,
            assignment_decision=inputs.assignment_decision,
            relationship_resolution=inputs.relationship_resolution,
            relationship_proof=inputs.relationship_proof,
            relationship_manifest=inputs.relationship_manifest,
            relationship_decision=inputs.relationship_decision,
        )


def test_primary_role_requires_selected_security_listing_relationship() -> None:
    """A primary listing cannot be asserted without a retained typed link."""
    role = role_record(870, 1)
    with pytest.raises(DatasetValidationError, match="security_has_listing"):
        resolve_primary((role,), (relationship_record(21, 2, 871),))


def test_each_active_listing_role_requires_its_selected_relationship() -> None:
    """A linked primary cannot hide an unlinked active secondary assertion."""
    roles = (
        role_record(872, 1),
        role_record(873, 2, role=ListingRole.SECONDARY),
    )
    relationship = relationship_record(21, 1, 874)
    inputs = primary_inputs(roles, relationships=(relationship,))

    with pytest.raises(DatasetValidationError, match="security_has_listing"):
        invoke_primary(roles, (relationship,), inputs)


def test_inactive_indeterminate_roles_do_not_poison_active_primary() -> None:
    """Past and future unknown roles cannot alter the role active at E."""
    active = role_record(880, 1)
    historical_unknown = role_record(
        890,
        2,
        role=ListingRole.INDETERMINATE,
        start="2018-01-01T00:00:00Z",
        end="2019-01-01T00:00:00Z",
    )
    future_unknown = role_record(
        900,
        2,
        role=ListingRole.INDETERMINATE,
        start="2021-01-01T00:00:00Z",
    )

    result = resolve_primary(
        (active, historical_unknown, future_unknown),
        (relationship_record(21, 1),),
    )

    assert result.classification is RecordResolutionClassification.RESOLVED
    assert result.listing_id == uid(1)


def test_superseded_primary_correction_is_checked_after_causal_selection() -> None:
    """A retained wrong primary may be corrected without invalidating history."""
    original = role_record(910, 1)
    correction = original.model_copy(
        update={
            "revision": original.revision.model_copy(
                update={
                    "record_version_id": uid(912),
                    "revision_kind": RevisionKind.CORRECTION,
                    "supersedes_record_version_id": original.revision.record_version_id,
                    "source_sequence": 1,
                    "availability": (public_availability("2027-01-01T00:00:00Z"),),
                }
            ),
            "listing_id": uid(2),
        }
    )
    correction = correction.model_copy(
        update={
            "revision": correction.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(correction))
                }
            )
        }
    )

    relationships = (
        relationship_record(21, 1, 913),
        relationship_record(21, 2, 914),
    )
    replay = resolve_primary(
        (original, correction),
        relationships,
    )
    current_inputs = primary_inputs(
        (original, correction),
        relationships=relationships,
        resolution_mode=ResolutionMode.CURRENT_INTERPRETATION,
    )
    current = invoke_primary((original, correction), relationships, current_inputs)

    assert replay.classification is RecordResolutionClassification.RESOLVED
    assert replay.listing_id == uid(1)
    assert replay.selected_role_record_hash == content_hash(original)
    assert current.classification is RecordResolutionClassification.RESOLVED
    assert current.listing_id == uid(2)
    assert current.selected_role_record_hash == content_hash(correction)


def test_primary_result_rejects_subject_proof_and_outcome_tampering() -> None:
    """Persisted primary fields cannot drift from role and relationship proof."""
    role = role_record(915, 1)
    relationship = relationship_record(21, 1, 916)
    result = resolve_primary((role,), (relationship,))
    with pytest.raises(ValidationError, match="subject"):
        result.model_copy(update={"methodology_id": "other-methodology"})
    with pytest.raises(ValidationError, match="selection proof"):
        result.model_copy(
            update={
                "evidence": result.evidence.model_copy(
                    update={"selection_proof_hashes": ()}
                )
            }
        )
    with pytest.raises(ValidationError, match="bound role"):
        result.model_copy(update={"selected_role_record_hash": "f" * 64})
    with pytest.raises(ValidationError, match="outcome binding"):
        result.model_copy(update={"listing_id": uid(2)})


def test_lifecycle_event_vocabulary_excludes_termination() -> None:
    """Adding a duplicate terminal lifecycle event would create two authorities."""
    assert tuple(ListingLifecycleEventKind) == (
        ListingLifecycleEventKind.ADMITTED,
        ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
        ListingLifecycleEventKind.SUSPENDED,
        ListingLifecycleEventKind.RESUMED,
        ListingLifecycleEventKind.VENUE_TRANSFER,
    )
    with pytest.raises(ValidationError):
        ListingLifecycleVersionV1.model_validate(
            {
                **lifecycle_record(
                    1000,
                    ListingLifecycleEventKind.ADMITTED,
                    "2019-01-02T00:00:00Z",
                ).model_dump(mode="python"),
                "event_kind": "terminated",
            }
        )


def test_lifecycle_model_requires_only_transfer_to_name_distinct_listing() -> None:
    """A transfer must name a new listing, while every other event must not."""
    with pytest.raises(ValidationError, match="transfer.*related"):
        lifecycle_record(
            1010,
            ListingLifecycleEventKind.VENUE_TRANSFER,
            "2021-12-31T00:00:00Z",
        )
    with pytest.raises(ValidationError, match="distinct"):
        lifecycle_record(
            1020,
            ListingLifecycleEventKind.VENUE_TRANSFER,
            "2021-12-31T00:00:00Z",
            related_listing=1,
        )
    with pytest.raises(ValidationError, match="only.*transfer"):
        lifecycle_record(
            1030,
            ListingLifecycleEventKind.ADMITTED,
            "2019-01-02T00:00:00Z",
            related_listing=2,
        )
    transfer = lifecycle_record(
        1040,
        ListingLifecycleEventKind.VENUE_TRANSFER,
        "2021-12-31T00:00:00Z",
        related_listing=2,
    )
    assert transfer.related_listing_id == uid(2)


@pytest.mark.parametrize("reason", tuple(ListingTerminationReason))
def test_termination_model_accepts_each_broad_reason_and_source_detail(
    reason: ListingTerminationReason,
) -> None:
    """Dropping a broad termination family or source-native detail loses evidence."""
    record = termination_record(
        1100 + list(ListingTerminationReason).index(reason), reason
    )
    assert record.reason is reason
    assert record.source_reason_code == "SYNTHETIC"
    assert record.source_reason_text == "synthetic termination"


def test_termination_model_accepts_bounded_trade_and_effective_boundaries() -> None:
    """Coercing source windows to exact instants would invent lifecycle precision."""
    record = termination_record(
        1120,
        ListingTerminationReason.UNKNOWN,
        last_trade=bounded_boundary("2021-12-29T00:00:00Z", "2021-12-30T00:00:00Z"),
        effective_time=bounded_boundary("2021-12-31T00:00:00Z", "2022-01-02T00:00:00Z"),
        source_reason_code=None,
        source_reason_text=None,
        outcome_status=OutcomeEvidenceStatus.PARTIAL,
    )
    assert record.last_regular_trade_time.shape is BoundaryShape.BOUNDED
    assert record.effective_time.shape is BoundaryShape.BOUNDED


@pytest.mark.parametrize("field", ("cash", "payout", "share_ratio", "return_value"))
def test_termination_model_rejects_economic_outcome_fields(field: str) -> None:
    """M1c economic results must not leak into the M1b termination authority."""
    values = termination_record(1130, ListingTerminationReason.ACQUISITION).model_dump(
        mode="python"
    )
    values[field] = "forbidden"
    with pytest.raises(ValidationError, match="extra"):
        ListingTerminationVersionV1.model_validate(values)


def test_termination_model_requires_canonical_successor_relationship_ids() -> None:
    """Successor reference order and duplication must not destabilize identity."""
    with pytest.raises(ValidationError, match="successor.*sorted.*unique"):
        termination_record(
            1140,
            ListingTerminationReason.REORGANIZATION,
            successor_relationship_ids=(uid(42), uid(41)),
        )
    with pytest.raises(ValidationError, match="successor.*sorted.*unique"):
        termination_record(
            1150,
            ListingTerminationReason.REORGANIZATION,
            successor_relationship_ids=(uid(41), uid(41)),
        )


@pytest.mark.parametrize("status", tuple(ListingHistoryCoverageStatus))
def test_coverage_model_preserves_explicit_status_and_boundary(
    status: ListingHistoryCoverageStatus,
) -> None:
    """Missing history must remain distinct from each sourced coverage state."""
    record = coverage_record(1160, status, "2026-01-01T00:00:00Z")
    assert record.coverage_status is status
    assert record.complete_through == exact_boundary("2026-01-01T00:00:00Z")


def successor_relationship(
    suffix: int,
    *,
    predecessor_security: int = 21,
    successor_security: int = 22,
    kind: IdentityRelationshipKind = IdentityRelationshipKind.SUCCESSOR_OF,
) -> IdentityRelationshipVersionV1:
    """Build one sourced security succession relationship."""
    record = IdentityRelationshipVersionV1(
        schema_version="1",
        revision=revision(suffix),
        left=IdentityReferenceV1(
            kind=IdentityKind.SECURITY,
            internal_id=uid(successor_security),
        ),
        right=IdentityReferenceV1(
            kind=IdentityKind.SECURITY,
            internal_id=uid(predecessor_security),
        ),
        relationship_kind=kind,
        resolution_status=ResolutionStatus.RESOLVED,
        effective_interval=interval("2021-12-31T00:00:00Z"),
        source_relationship_code="synthetic-successor",
    )
    return record.model_copy(
        update={
            "revision": record.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


@dataclass(frozen=True)
class LifecycleResolutionInputs:
    """Three independently validated lifecycle stages in one exact bundle."""

    events: tuple[ListingLifecycleVersionV1, ...]
    terminations: tuple[ListingTerminationVersionV1, ...]
    coverage_versions: tuple[ListingHistoryCoverageVersionV1, ...]
    lifecycle_manifest: DatasetManifestV2
    lifecycle_decision: DatasetValidationDecisionV2
    termination_manifest: DatasetManifestV2
    termination_decision: DatasetValidationDecisionV2
    coverage_manifest: DatasetManifestV2
    coverage_decision: DatasetValidationDecisionV2
    bundle: ValidatedDatasetBundleV1
    lifecycle_query: NormalizedSelectionQueryV1
    termination_query: NormalizedSelectionQueryV1
    coverage_query: NormalizedSelectionQueryV1
    policy: AvailabilityPolicyV1
    assignments: tuple[IdentityAssignmentVersionV1, ...]
    assignment_manifest: DatasetManifestV2 | None
    assignment_decision: DatasetValidationDecisionV2 | None
    relationships: tuple[IdentityRelationshipVersionV1, ...]
    relationship_manifest: DatasetManifestV2 | None
    relationship_decision: DatasetValidationDecisionV2 | None
    relationship_resolution: IdentityResolutionResultV1 | None
    relationship_proof: CutoffSelectionProofV1 | None


def lifecycle_inputs(
    events: tuple[ListingLifecycleVersionV1, ...],
    terminations: tuple[ListingTerminationVersionV1, ...] = (),
    coverage_versions: tuple[ListingHistoryCoverageVersionV1, ...] | None = None,
    relationships: tuple[IdentityRelationshipVersionV1, ...] = (),
    *,
    evaluation_time: str = "2020-01-01T00:00:00Z",
    knowledge_cutoff: str = "2026-01-01T00:00:00Z",
    resolution_mode: ResolutionMode = ResolutionMode.AS_KNOWN,
    relationship_subject_security: int = 21,
    policy_id: str = "strict",
) -> LifecycleResolutionInputs:
    """Build exact coverage, termination, lifecycle, and relationship provenance."""
    coverage_records = (
        (
            coverage_record(
                1200,
                ListingHistoryCoverageStatus.COMPLETE,
                "2026-12-31T00:00:00Z",
            ),
        )
        if coverage_versions is None
        else coverage_versions
    )
    lifecycle_manifest, lifecycle_bytes = role_dataset("listing_lifecycle", events)
    lifecycle_decision = validate_identity_dataset(
        lifecycle_manifest, (lifecycle_bytes,), role_validation_context(1201)
    )
    termination_manifest, termination_bytes = role_dataset(
        "listing_termination", terminations
    )
    termination_decision = validate_identity_dataset(
        termination_manifest, (termination_bytes,), role_validation_context(1202)
    )
    coverage_manifest, coverage_bytes = role_dataset(
        "listing_history_coverage", coverage_records
    )
    coverage_decision = validate_identity_dataset(
        coverage_manifest, (coverage_bytes,), role_validation_context(1203)
    )
    assert lifecycle_decision.result is ValidationResult.PASS
    assert termination_decision.result is ValidationResult.PASS
    assert coverage_decision.result is ValidationResult.PASS

    members: list[tuple[DatasetManifestV2, DatasetValidationDecisionV2]] = [
        (lifecycle_manifest, lifecycle_decision),
        (termination_manifest, termination_decision),
        (coverage_manifest, coverage_decision),
    ]
    relationship_manifest: DatasetManifestV2 | None = None
    relationship_decision: DatasetValidationDecisionV2 | None = None
    assignment_manifest: DatasetManifestV2 | None = None
    assignment_decision: DatasetValidationDecisionV2 | None = None
    assignments: tuple[IdentityAssignmentVersionV1, ...] = ()
    relationship_subject = IdentityReferenceV1(
        kind=IdentityKind.SECURITY,
        internal_id=uid(relationship_subject_security),
    )
    if relationships:
        relationship_manifest, relationship_decision = relationship_dataset(
            relationships
        )
        endpoints = {
            relationship_subject,
            *(
                endpoint
                for relationship in relationships
                for endpoint in (relationship.left, relationship.right)
            ),
        }
        assignments = tuple(
            assignment_for_dependency(reference, 1210 + index)
            for index, reference in enumerate(
                sorted(
                    endpoints,
                    key=lambda item: (item.kind.value, str(item.internal_id)),
                )
            )
        )
        assignment_manifest, assignment_decision = assignment_dataset(assignments)
        members.extend(
            (
                (relationship_manifest, relationship_decision),
                (assignment_manifest, assignment_decision),
            )
        )
    bundle = build_validated_dataset_bundle(
        uid(1290),
        "2",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        tuple(members),
    )
    policy = AvailabilityPolicyV1(policy_id=policy_id)
    subject = {"listing_id": uid(1)}
    coverage_query = exact_dataset_query(
        coverage_manifest,
        coverage_decision,
        bundle,
        purpose=M1bSelectionPurpose.LISTING_LIFECYCLE,
        subject=subject,
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
        policy_id=policy_id,
    )
    termination_query = exact_dataset_query(
        termination_manifest,
        termination_decision,
        bundle,
        purpose=M1bSelectionPurpose.LISTING_TERMINATION,
        subject=subject,
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
        policy_id=policy_id,
    )
    lifecycle_query = exact_dataset_query(
        lifecycle_manifest,
        lifecycle_decision,
        bundle,
        purpose=M1bSelectionPurpose.LISTING_LIFECYCLE,
        subject=subject,
        evaluation_time=evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        resolution_mode=resolution_mode,
        policy_id=policy_id,
    )
    relationship_resolution: IdentityResolutionResultV1 | None = None
    relationship_proof: CutoffSelectionProofV1 | None = None
    if relationships:
        assert relationship_manifest is not None
        assert relationship_decision is not None
        assert assignment_manifest is not None
        assert assignment_decision is not None
        relationship_query = exact_dataset_query(
            relationship_manifest,
            relationship_decision,
            bundle,
            purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
            subject=relationship_subject,
            evaluation_time=evaluation_time,
            knowledge_cutoff=knowledge_cutoff,
            resolution_mode=resolution_mode,
            policy_id=policy_id,
        )
        relationship_resolution = resolve_identity(
            relationship_subject,
            assignments,
            relationships,
            relationship_query,
            bundle,
            relationship_manifest,
            relationship_decision,
            policy,
            {},
            assignment_manifest=assignment_manifest,
            assignment_decision=assignment_decision,
        )
        chains = _relationship_chains_for_subject(
            relationships,
            relationship_subject,
        )
        selections = tuple(
            _select_identity_chain(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=item.revision,
                        record_hash=content_hash(item),
                    )
                    for item in chain
                ),
                relationship_query,
                policy,
                {},
            )
            for chain in chains.values()
        )
        relationship_proof = build_cutoff_selection_proof(
            relationship_query,
            selections,
            relationship_manifest,
            relationship_decision,
            (bundle,),
            "bf61c84a232e0d5c11a99b6451f9a43f37f96dab220c1c7036456252394c961d",
        )
    return LifecycleResolutionInputs(
        events=events,
        terminations=terminations,
        coverage_versions=coverage_records,
        lifecycle_manifest=lifecycle_manifest,
        lifecycle_decision=lifecycle_decision,
        termination_manifest=termination_manifest,
        termination_decision=termination_decision,
        coverage_manifest=coverage_manifest,
        coverage_decision=coverage_decision,
        bundle=bundle,
        lifecycle_query=lifecycle_query,
        termination_query=termination_query,
        coverage_query=coverage_query,
        policy=policy,
        assignments=assignments,
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
        relationships=relationships,
        relationship_manifest=relationship_manifest,
        relationship_decision=relationship_decision,
        relationship_resolution=relationship_resolution,
        relationship_proof=relationship_proof,
    )


def invoke_coverage(
    inputs: LifecycleResolutionInputs,
    *,
    query: NormalizedSelectionQueryV1 | None = None,
) -> ListingHistoryCoverageResolutionV1:
    """Resolve the first independently authenticated lifecycle stage."""
    return resolve_listing_history_coverage(
        uid(1),
        inputs.coverage_versions,
        inputs.coverage_query if query is None else query,
        inputs.bundle,
        inputs.coverage_manifest,
        inputs.coverage_decision,
        inputs.policy,
        {},
    )


def invoke_termination(
    inputs: LifecycleResolutionInputs,
    coverage: ListingHistoryCoverageResolutionV1,
    *,
    query: NormalizedSelectionQueryV1 | None = None,
    terminations: tuple[ListingTerminationVersionV1, ...] | None = None,
) -> ListingTerminationResolutionV1:
    """Resolve termination only after replaying the supplied coverage result."""
    return resolve_listing_termination(
        uid(1),
        inputs.terminations if terminations is None else terminations,
        coverage,
        inputs.termination_query if query is None else query,
        inputs.bundle,
        inputs.termination_manifest,
        inputs.termination_decision,
        inputs.policy,
        {},
        coverage_versions=inputs.coverage_versions,
        coverage_manifest=inputs.coverage_manifest,
        coverage_decision=inputs.coverage_decision,
        identity_relationships=inputs.relationships,
        relationship_resolution=inputs.relationship_resolution,
        relationship_proof=inputs.relationship_proof,
        relationship_manifest=inputs.relationship_manifest,
        relationship_decision=inputs.relationship_decision,
        identity_assignments=inputs.assignments,
        assignment_manifest=inputs.assignment_manifest,
        assignment_decision=inputs.assignment_decision,
    )


def invoke_lifecycle(
    inputs: LifecycleResolutionInputs,
    *,
    coverage: ListingHistoryCoverageResolutionV1 | None = None,
    termination: ListingTerminationResolutionV1 | None = None,
    query: NormalizedSelectionQueryV1 | None = None,
) -> ListingLifecycleResolutionV1:
    """Resolve lifecycle after independently replaying both dependency stages."""
    selected_coverage = invoke_coverage(inputs) if coverage is None else coverage
    selected_termination = (
        invoke_termination(inputs, selected_coverage)
        if termination is None
        else termination
    )
    return resolve_listing_lifecycle(
        uid(1),
        inputs.events,
        selected_termination,
        inputs.lifecycle_query if query is None else query,
        inputs.bundle,
        inputs.lifecycle_manifest,
        inputs.lifecycle_decision,
        inputs.policy,
        {},
        terminations=inputs.terminations,
        termination_manifest=inputs.termination_manifest,
        termination_decision=inputs.termination_decision,
        coverage=selected_coverage,
        coverage_versions=inputs.coverage_versions,
        coverage_manifest=inputs.coverage_manifest,
        coverage_decision=inputs.coverage_decision,
        identity_relationships=inputs.relationships,
        relationship_resolution=inputs.relationship_resolution,
        relationship_proof=inputs.relationship_proof,
        relationship_manifest=inputs.relationship_manifest,
        relationship_decision=inputs.relationship_decision,
        identity_assignments=inputs.assignments,
        assignment_manifest=inputs.assignment_manifest,
        assignment_decision=inputs.assignment_decision,
    )


def standard_lifecycle_events() -> tuple[ListingLifecycleVersionV1, ...]:
    """Return one admitted, traded, suspended, and resumed synthetic history."""
    return (
        lifecycle_record(
            1300,
            ListingLifecycleEventKind.ADMITTED,
            "2019-01-02T00:00:00Z",
        ),
        lifecycle_record(
            1310,
            ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
            "2019-01-03T14:30:00Z",
        ),
        lifecycle_record(
            1320,
            ListingLifecycleEventKind.SUSPENDED,
            "2020-03-01T00:00:00Z",
        ),
        lifecycle_record(
            1330,
            ListingLifecycleEventKind.RESUMED,
            "2020-04-01T00:00:00Z",
        ),
    )


@pytest.mark.parametrize(
    ("evaluation_time", "expected"),
    (
        ("2019-01-01T00:00:00Z", ListingLifecycleStatus.NOT_YET_LISTED),
        ("2019-01-02T12:00:00Z", ListingLifecycleStatus.NOT_YET_LISTED),
        ("2019-01-04T00:00:00Z", ListingLifecycleStatus.ACTIVE),
        ("2020-03-02T00:00:00Z", ListingLifecycleStatus.SUSPENDED),
        ("2020-04-02T00:00:00Z", ListingLifecycleStatus.ACTIVE),
    ),
)
def test_lifecycle_resolves_pre_admission_first_trade_and_suspension_history(
    evaluation_time: str,
    expected: ListingLifecycleStatus,
) -> None:
    """Activity must begin at first regular trade and suspension must alternate."""
    inputs = lifecycle_inputs(
        standard_lifecycle_events(), evaluation_time=evaluation_time
    )
    result = invoke_lifecycle(inputs)
    assert result.status is expected
    assert result.selected_termination_version_id is None
    assert result.termination_resolution_hash == content_hash(
        invoke_termination(inputs, invoke_coverage(inputs))
    )


def test_bounded_first_regular_trade_is_indeterminate_inside_source_window() -> None:
    """A bounded first-trade claim cannot activate a listing inside its window."""
    events = (
        lifecycle_record(
            1340,
            ListingLifecycleEventKind.ADMITTED,
            "2019-01-02T00:00:00Z",
        ),
        lifecycle_record(
            1350,
            ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
            bounded_boundary("2019-01-03T00:00:00Z", "2019-01-05T00:00:00Z"),
        ),
    )
    result = invoke_lifecycle(
        lifecycle_inputs(events, evaluation_time="2019-01-04T00:00:00Z")
    )
    assert result.status is ListingLifecycleStatus.INDETERMINATE


@pytest.mark.parametrize(
    ("coverage_status", "complete_through", "expected"),
    (
        (
            ListingHistoryCoverageStatus.COMPLETE,
            "2021-01-01T00:00:00Z",
            ListingTerminationStatus.NOT_TERMINATED,
        ),
        (
            ListingHistoryCoverageStatus.COMPLETE,
            "2019-12-31T00:00:00Z",
            ListingTerminationStatus.INDETERMINATE,
        ),
        (
            ListingHistoryCoverageStatus.PARTIAL,
            "2021-01-01T00:00:00Z",
            ListingTerminationStatus.INDETERMINATE,
        ),
        (
            ListingHistoryCoverageStatus.UNKNOWN,
            "2021-01-01T00:00:00Z",
            ListingTerminationStatus.INDETERMINATE,
        ),
    ),
)
def test_no_termination_requires_complete_history_through_e(
    coverage_status: ListingHistoryCoverageStatus,
    complete_through: str,
    expected: ListingTerminationStatus,
) -> None:
    """An absent termination row proves nothing without complete coverage through E."""
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        coverage_versions=(coverage_record(1360, coverage_status, complete_through),),
        evaluation_time="2020-01-01T00:00:00Z",
    )
    coverage = invoke_coverage(inputs)
    termination = invoke_termination(inputs, coverage)
    assert termination.status is expected
    assert termination.selected_termination_version_id is None


def test_missing_coverage_and_termination_records_remain_indeterminate() -> None:
    """Two missing record families must never be promoted to termination or activity."""
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        coverage_versions=(),
        evaluation_time="2020-01-01T00:00:00Z",
    )
    coverage = invoke_coverage(inputs)
    termination = invoke_termination(inputs, coverage)
    lifecycle = invoke_lifecycle(inputs, coverage=coverage, termination=termination)
    assert coverage.status is ListingHistoryCoverageStatus.UNKNOWN
    assert termination.status is ListingTerminationStatus.INDETERMINATE
    assert lifecycle.status is ListingLifecycleStatus.INDETERMINATE


def test_termination_boundary_is_authoritative_only_when_definitely_effective() -> None:
    """A selected bounded termination cannot terminate inside its source window."""
    termination = termination_record(
        1370,
        ListingTerminationReason.BANKRUPTCY,
        last_trade=bounded_boundary("2020-05-28T00:00:00Z", "2020-05-30T00:00:00Z"),
        effective_time=bounded_boundary("2020-05-31T00:00:00Z", "2020-06-02T00:00:00Z"),
    )
    inside = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        evaluation_time="2020-06-01T00:00:00Z",
    )
    after = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        evaluation_time="2020-06-03T00:00:00Z",
    )
    inside_result = invoke_termination(inside, invoke_coverage(inside))
    after_result = invoke_termination(after, invoke_coverage(after))
    assert inside_result.status is ListingTerminationStatus.INDETERMINATE
    assert after_result.status is ListingTerminationStatus.TERMINATED
    assert after_result.selected_termination_version_id == (
        termination.revision.record_version_id
    )


def test_effective_termination_overrides_prior_active_lifecycle() -> None:
    """The sole termination record must end an otherwise active lifecycle."""
    termination = termination_record(
        1380,
        ListingTerminationReason.EXCHANGE_DELISTING,
        last_trade="2020-05-29T20:00:00Z",
        effective_time="2020-06-01T00:00:00Z",
    )
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        evaluation_time="2020-06-02T00:00:00Z",
    )
    result = invoke_lifecycle(inputs)
    assert result.status is ListingLifecycleStatus.TERMINATED
    assert result.selected_termination_version_id == (
        termination.revision.record_version_id
    )


def test_observation_shaped_input_cannot_create_termination() -> None:
    """Missing bars or observations are not a valid termination authority."""
    values = termination_record(1390, ListingTerminationReason.UNKNOWN).model_dump(
        mode="python"
    )
    values.pop("reason")
    values["observation_status"] = "provider_missing"
    with pytest.raises(ValidationError):
        ListingTerminationVersionV1.model_validate(values)


@pytest.mark.parametrize(
    "events",
    (
        (
            lifecycle_record(
                1400,
                ListingLifecycleEventKind.ADMITTED,
                "2019-01-02T00:00:00Z",
            ),
            lifecycle_record(
                1410,
                ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
                "2019-01-03T00:00:00Z",
            ),
            lifecycle_record(
                1420,
                ListingLifecycleEventKind.RESUMED,
                "2019-02-01T00:00:00Z",
            ),
        ),
        (
            lifecycle_record(
                1430,
                ListingLifecycleEventKind.ADMITTED,
                "2019-01-02T00:00:00Z",
            ),
            lifecycle_record(
                1440,
                ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
                "2019-01-03T00:00:00Z",
            ),
            lifecycle_record(
                1450,
                ListingLifecycleEventKind.SUSPENDED,
                "2019-02-01T00:00:00Z",
            ),
            lifecycle_record(
                1460,
                ListingLifecycleEventKind.SUSPENDED,
                "2019-03-01T00:00:00Z",
            ),
        ),
    ),
)
def test_suspension_and_resumption_must_alternate_causally(
    events: tuple[ListingLifecycleVersionV1, ...],
) -> None:
    """A resume without suspension or consecutive suspensions corrupt state."""
    inputs = lifecycle_inputs(events, evaluation_time="2020-01-01T00:00:00Z")
    with pytest.raises(DatasetValidationError, match="alternat"):
        invoke_lifecycle(inputs)


def test_multiple_independent_termination_records_are_rejected() -> None:
    """One listing cannot have two simultaneous logical termination authorities."""
    records = (
        termination_record(1470, ListingTerminationReason.MERGER),
        termination_record(1480, ListingTerminationReason.BANKRUPTCY),
    )
    with pytest.raises(DatasetValidationError, match="sole_termination"):
        validate_listing_terminations(records)


def test_transfer_requires_same_security_and_matching_termination() -> None:
    """A venue transfer must link two listing identities of one security."""
    transfer = lifecycle_record(
        1490,
        ListingLifecycleEventKind.VENUE_TRANSFER,
        "2021-12-31T00:00:00Z",
        related_listing=2,
    )
    termination = termination_record(
        1500,
        ListingTerminationReason.VENUE_TRANSFER,
        effective_time="2021-12-31T00:00:00Z",
    )
    same_security = (
        relationship_record(21, 1, 1510),
        relationship_record(21, 2, 1520, start="2022-01-03T00:00:00Z"),
    )
    inputs = lifecycle_inputs(
        (*standard_lifecycle_events(), transfer),
        (termination,),
        relationships=same_security,
        evaluation_time="2022-01-01T00:00:00Z",
    )
    assert invoke_lifecycle(inputs).status is ListingLifecycleStatus.TERMINATED

    different_security = (
        relationship_record(21, 1, 1530),
        relationship_record(22, 2, 1540),
    )
    invalid = lifecycle_inputs(
        (*standard_lifecycle_events(), transfer),
        (termination,),
        relationships=different_security,
        evaluation_time="2022-01-01T00:00:00Z",
    )
    with pytest.raises(DatasetValidationError, match="same_security"):
        invoke_lifecycle(invalid)


@pytest.mark.parametrize(
    "termination",
    (
        None,
        termination_record(
            1550,
            ListingTerminationReason.MERGER,
            effective_time="2021-12-31T00:00:00Z",
        ),
        termination_record(
            1560,
            ListingTerminationReason.VENUE_TRANSFER,
            effective_time="2022-01-01T00:00:00Z",
        ),
    ),
)
def test_transfer_rejects_missing_reason_or_time_mismatched_termination(
    termination: ListingTerminationVersionV1 | None,
) -> None:
    """A transfer event cannot stand without its exact sole termination record."""
    transfer = lifecycle_record(
        1570,
        ListingLifecycleEventKind.VENUE_TRANSFER,
        "2021-12-31T00:00:00Z",
        related_listing=2,
    )
    relationships = (
        relationship_record(21, 1, 1580),
        relationship_record(21, 2, 1590),
    )
    inputs = lifecycle_inputs(
        (*standard_lifecycle_events(), transfer),
        () if termination is None else (termination,),
        relationships=relationships,
        evaluation_time="2022-01-02T00:00:00Z",
    )
    with pytest.raises(DatasetValidationError, match="matching_transfer_termination"):
        invoke_lifecycle(inputs)


@pytest.mark.parametrize(
    "kind",
    (
        IdentityRelationshipKind.SUCCESSOR_OF,
        IdentityRelationshipKind.REORGANIZED_FROM,
    ),
)
def test_termination_accepts_selected_security_successor_relationships(
    kind: IdentityRelationshipKind,
) -> None:
    """Successor IDs must resolve through selected security succession evidence."""
    listing_link = relationship_record(21, 1, 1600)
    successor = successor_relationship(1610, kind=kind)
    termination = termination_record(
        1620,
        ListingTerminationReason.REORGANIZATION,
        successor_relationship_ids=(successor.revision.logical_record_id,),
    )
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        relationships=(listing_link, successor),
        evaluation_time="2022-01-01T00:00:00Z",
    )
    result = invoke_termination(inputs, invoke_coverage(inputs))
    assert result.status is ListingTerminationStatus.TERMINATED


@pytest.mark.parametrize(
    "relationship",
    (
        successor_relationship(
            1630,
            kind=IdentityRelationshipKind.DISTINCT_FROM,
        ),
        relationship_record(21, 2, 1640),
    ),
)
def test_termination_rejects_non_successor_relationship_ids(
    relationship: IdentityRelationshipVersionV1,
) -> None:
    """Distinctness and listing links can never satisfy successor references."""
    listing_link = relationship_record(21, 1, 1650)
    termination = termination_record(
        1660,
        ListingTerminationReason.REORGANIZATION,
        successor_relationship_ids=(relationship.revision.logical_record_id,),
    )
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        relationships=(listing_link, relationship),
        evaluation_time="2022-01-01T00:00:00Z",
    )
    with pytest.raises(DatasetValidationError, match="successor_relationship"):
        invoke_termination(inputs, invoke_coverage(inputs))


def test_termination_rejects_unselected_successor_relationship_id() -> None:
    """A raw logical ID not selected by the relationship proof is no authority."""
    listing_link = relationship_record(21, 1, 1670)
    successor = successor_relationship(1680)
    termination = termination_record(
        1690,
        ListingTerminationReason.REORGANIZATION,
        successor_relationship_ids=(uid(9999),),
    )
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        relationships=(listing_link, successor),
        evaluation_time="2022-01-01T00:00:00Z",
    )
    with pytest.raises(DatasetValidationError, match="successor_relationship"):
        invoke_termination(inputs, invoke_coverage(inputs))


def test_termination_rejects_coverage_from_a_different_evaluation_context() -> None:
    """Coverage and termination must share every historical query discriminator."""
    first = lifecycle_inputs(
        standard_lifecycle_events(), evaluation_time="2020-01-01T00:00:00Z"
    )
    other = lifecycle_inputs(
        standard_lifecycle_events(), evaluation_time="2020-02-01T00:00:00Z"
    )
    with pytest.raises(DatasetValidationError, match="coverage.*context"):
        invoke_termination(first, invoke_coverage(other))


def test_lifecycle_rejects_termination_from_a_different_policy_context() -> None:
    """A termination result from another query cannot authorize lifecycle state."""
    first = lifecycle_inputs(standard_lifecycle_events())
    other = lifecycle_inputs(
        standard_lifecycle_events(),
        policy_id="other",
    )
    forged = invoke_termination(
        other,
        invoke_coverage(other),
    )
    with pytest.raises(DatasetValidationError, match="termination.*context"):
        invoke_lifecycle(first, termination=forged)


def test_lifecycle_result_rejects_subject_termination_and_status_tampering() -> None:
    """Persisted lifecycle output must remain bound to both selection stages."""
    result = invoke_lifecycle(lifecycle_inputs(standard_lifecycle_events()))
    with pytest.raises(ValidationError, match="subject"):
        result.model_copy(update={"listing_id": uid(99)})
    with pytest.raises(ValidationError, match="termination"):
        result.model_copy(update={"termination_resolution_hash": "f" * 64})
    with pytest.raises(ValidationError, match="termination version"):
        result.model_copy(
            update={
                "status": ListingLifecycleStatus.TERMINATED,
                "selected_termination_version_id": None,
            }
        )


def test_coverage_and_termination_results_reject_subject_or_shape_tampering() -> None:
    """Persisted stage results cannot drift from their bound queries or selections."""
    inputs = lifecycle_inputs(standard_lifecycle_events())
    coverage = invoke_coverage(inputs)
    termination = invoke_termination(inputs, coverage)
    with pytest.raises(ValidationError, match="subject"):
        coverage.model_copy(update={"listing_id": uid(99)})
    with pytest.raises(ValidationError, match="subject"):
        termination.model_copy(update={"listing_id": uid(99)})
    with pytest.raises(ValidationError, match="termination version"):
        termination.model_copy(
            update={
                "status": ListingTerminationStatus.TERMINATED,
                "selected_termination_version_id": None,
            }
        )


def test_lifecycle_validator_rejects_first_trade_before_admission() -> None:
    """A listing cannot begin regular trading before it has been admitted."""
    events = (
        lifecycle_record(
            1700,
            ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
            "2019-01-01T00:00:00Z",
        ),
        lifecycle_record(
            1710,
            ListingLifecycleEventKind.ADMITTED,
            "2019-01-02T00:00:00Z",
        ),
    )
    with pytest.raises(DatasetValidationError, match="first_trade.*admission"):
        validate_listing_lifecycle(events)


def test_lifecycle_validator_rejects_suspension_before_first_trade() -> None:
    """Suspension state cannot exist before regular trading has begun."""
    events = (
        lifecycle_record(
            1720,
            ListingLifecycleEventKind.ADMITTED,
            "2019-01-01T00:00:00Z",
        ),
        lifecycle_record(
            1730,
            ListingLifecycleEventKind.SUSPENDED,
            "2019-01-02T00:00:00Z",
        ),
        lifecycle_record(
            1740,
            ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
            "2019-01-03T00:00:00Z",
        ),
    )
    with pytest.raises(DatasetValidationError, match="suspension.*first_trade"):
        validate_listing_lifecycle(events)


def test_mapping_resolver_requires_exact_typed_mapping_validation() -> None:
    """A record-hash decision over an assignment schema cannot authorize mappings."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                1800,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )

    wrong_manifest = fixed_manifest("external_identifier_mapping")
    wrong_decision = decision_for(*inputs.records)
    wrong_bundle = build_validated_dataset_bundle(
        uid(1990),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (wrong_manifest, wrong_decision),
            (inputs.assignment_manifest, inputs.assignment_decision),
        ),
    )
    wrong_query = exact_dataset_query(
        wrong_manifest,
        wrong_decision,
        wrong_bundle,
        purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
        subject={"namespace": namespace, "identifier_value": "OLD"},
        evaluation_time="2019-02-01T00:00:00Z",
        knowledge_cutoff="2026-01-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )

    with pytest.raises(DatasetValidationError, match="schema_or_contract"):
        resolve_external_identifier(
            inputs.namespace,
            inputs.value,
            inputs.records,
            wrong_query,
            wrong_bundle,
            wrong_manifest,
            wrong_decision,
            inputs.policy,
            {},
            assignments=inputs.assignments,
            assignment_manifest=inputs.assignment_manifest,
            assignment_decision=inputs.assignment_decision,
            lifecycle_events=inputs.lifecycle_events,
            lifecycle_manifest=inputs.lifecycle_manifest,
            lifecycle_decision=inputs.lifecycle_decision,
            terminations=inputs.terminations,
            termination_manifest=inputs.termination_manifest,
            termination_decision=inputs.termination_decision,
        )


def test_relationship_dependency_replays_the_complete_identity_outcome() -> None:
    """A forged resolved result cannot reuse a genuine proof from a conflict."""
    classification = classification_record(1810)
    issued = issuer_security_relationship(1820)
    subject = IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=uid(20))
    other = IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=uid(22))

    def issuer_relation(
        suffix: int, kind: IdentityRelationshipKind
    ) -> IdentityRelationshipVersionV1:
        record = IdentityRelationshipVersionV1(
            schema_version="1",
            revision=revision(suffix),
            left=subject,
            right=other,
            relationship_kind=kind,
            resolution_status=ResolutionStatus.RESOLVED,
            effective_interval=interval("2019-01-02T00:00:00Z"),
            source_relationship_code="synthetic-contradiction",
        )
        return record.model_copy(
            update={
                "revision": record.revision.model_copy(
                    update={
                        "payload_hash": content_hash(assertion_version_payload(record))
                    }
                )
            }
        )

    inputs = classification_inputs(
        (classification,),
        relationships=(
            issued,
            issuer_relation(1830, IdentityRelationshipKind.EQUIVALENT_TO),
            issuer_relation(1840, IdentityRelationshipKind.DISTINCT_FROM),
        ),
    )
    assert (
        inputs.relationship_resolution.classification
        is IdentityResolutionClassification.CONFLICT
    )
    forged_values = inputs.relationship_resolution.model_dump(mode="python")
    forged_values.update(
        {
            "classification": IdentityResolutionClassification.RESOLVED,
            "resolved_identities": (subject,),
            "reasons": ("resolved",),
        }
    )
    forged = IdentityResolutionResultV1.model_validate(forged_values)

    with pytest.raises(DatasetValidationError, match="resolution_replay"):
        invoke_classification(
            (classification,),
            inputs,
            relationship_resolution=forged,
        )


def test_mapping_selects_target_changing_correction_before_collision_checks() -> None:
    """A future target correction cannot make the earlier interpretation collide."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    original = mapping(
        1850,
        namespace,
        "OLD",
        1,
        "2019-01-02T00:00:00Z",
        "2021-12-31T00:00:00Z",
    )
    corrected = original.model_copy(
        update={
            "revision": original.revision.model_copy(
                update={
                    "record_version_id": uid(1951),
                    "revision_kind": RevisionKind.CORRECTION,
                    "supersedes_record_version_id": original.revision.record_version_id,
                    "source_sequence": 1,
                    "availability": (public_availability("2027-01-01T00:00:00Z"),),
                }
            ),
            "target": IdentityReferenceV1(
                kind=IdentityKind.LISTING, internal_id=uid(2)
            ),
        }
    )
    corrected = corrected.model_copy(
        update={
            "revision": corrected.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(corrected))
                }
            )
        }
    )

    result = resolve_at(
        namespace,
        "OLD",
        (original, corrected),
        "2019-02-01T00:00:00Z",
    )

    assert result.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
    )


def test_mapping_current_interpretation_uses_target_changing_correction() -> None:
    """Current interpretation selects the retained correction without collision."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    original = mapping(
        1852,
        namespace,
        "OLD",
        1,
        "2019-01-02T00:00:00Z",
        "2021-12-31T00:00:00Z",
    )
    corrected = original.model_copy(
        update={
            "revision": original.revision.model_copy(
                update={
                    "record_version_id": uid(1953),
                    "revision_kind": RevisionKind.CORRECTION,
                    "supersedes_record_version_id": original.revision.record_version_id,
                    "source_sequence": 1,
                    "availability": (public_availability("2027-01-01T00:00:00Z"),),
                }
            ),
            "target": IdentityReferenceV1(
                kind=IdentityKind.LISTING, internal_id=uid(3)
            ),
            "effective_interval": interval("2024-01-02T00:00:00Z"),
        }
    )
    corrected = corrected.model_copy(
        update={
            "revision": corrected.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(corrected))
                }
            )
        }
    )
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (original, corrected),
        "2024-02-01T00:00:00Z",
    )
    current_query = inputs.query.model_copy(
        update={
            "information_role": InformationRole.EX_POST_OUTCOME,
            "resolution_mode": ResolutionMode.CURRENT_INTERPRETATION,
        }
    )

    result = invoke_resolution(inputs, query=current_query)

    assert result.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(3)),
    )


def test_unrelated_future_mapping_does_not_require_its_target_for_earlier_query() -> (
    None
):
    """A future unrelated record cannot poison an earlier requested mapping."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    requested = mapping(
        1860,
        namespace,
        "OLD",
        1,
        "2019-01-02T00:00:00Z",
        "2021-12-31T00:00:00Z",
    )
    unrelated = mapping(
        1870,
        namespace,
        "FUTURE",
        99,
        "2027-01-01T00:00:00Z",
    )
    unrelated = unrelated.model_copy(
        update={
            "revision": unrelated.revision.model_copy(
                update={
                    "availability": (public_availability("2027-01-01T00:00:00Z"),),
                    "payload_hash": "a" * 64,
                }
            )
        }
    )
    unrelated = unrelated.model_copy(
        update={
            "revision": unrelated.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(unrelated))
                }
            )
        }
    )

    result = resolve_at(
        namespace,
        "OLD",
        (requested, unrelated),
        "2019-02-01T00:00:00Z",
    )

    assert result.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("identifier_value", "CHANGED"),
        ("classification", RecordResolutionClassification.INDETERMINATE),
        ("reasons", ("changed",)),
        ("target_assignment_proof_hashes", ("f" * 64,)),
        ("outcome_binding_hash", "f" * 64),
    ),
)
def test_mapping_result_rejects_outcome_tampering(
    field: str, replacement: object
) -> None:
    """Every persisted public mapping field must remain bound to its evidence."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    result = resolve_at(
        namespace,
        "OLD",
        (
            mapping(
                1880,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    values = result.model_dump(mode="python")
    values[field] = replacement

    with pytest.raises(
        ValidationError, match="subject|cannot expose targets|outcome binding"
    ):
        ExternalIdentifierResolutionResultV1.model_validate(values)


def test_mapping_result_rejects_namespace_target_and_evidence_tampering() -> None:
    """Subject, target, and selected mapping evidence are outcome-bound."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    result = resolve_at(
        namespace,
        "OLD",
        (
            mapping(
                1890,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2019-02-01T00:00:00Z",
    )
    values = result.model_dump(mode="python")
    other_namespace = namespace.model_copy(update={"scheme": "other-ticker-v1"})
    other_target = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(2))
    other_evidence = result.evidence.model_copy(
        update={
            "considered_record_hashes": ("f" * 64,),
            "selected_record_hashes": ("f" * 64,),
        }
    )
    for update in (
        {"namespace": other_namespace},
        {"targets": (other_target,)},
        {"evidence": other_evidence},
    ):
        with pytest.raises(ValidationError, match="subject|outcome binding"):
            ExternalIdentifierResolutionResultV1.model_validate(values | update)


def test_future_transfer_does_not_require_future_listing_link_before_event() -> None:
    """A retained future transfer cannot abort a pre-transfer lifecycle query."""
    transfer = lifecycle_record(
        1900,
        ListingLifecycleEventKind.VENUE_TRANSFER,
        "2021-12-31T00:00:00Z",
        related_listing=2,
    )
    termination = termination_record(
        1910,
        ListingTerminationReason.VENUE_TRANSFER,
        effective_time="2021-12-31T00:00:00Z",
    )
    old_link = relationship_record(21, 1, 1920)
    future_link = relationship_record(
        21,
        2,
        1930,
        start="2022-01-03T00:00:00Z",
    )
    inputs = lifecycle_inputs(
        (*standard_lifecycle_events(), transfer),
        (termination,),
        relationships=(old_link, future_link),
        evaluation_time="2020-01-01T00:00:00Z",
    )

    assert invoke_lifecycle(inputs).status is ListingLifecycleStatus.ACTIVE


def test_future_successor_does_not_require_future_proof_before_termination() -> None:
    """A retained future successor cannot abort a pre-termination query."""
    listing_link = relationship_record(21, 1, 1940)
    successor = successor_relationship(1950)
    termination = termination_record(
        1960,
        ListingTerminationReason.REORGANIZATION,
        successor_relationship_ids=(successor.revision.logical_record_id,),
    )
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        relationships=(listing_link, successor),
        evaluation_time="2020-01-01T00:00:00Z",
    )

    result = invoke_termination(inputs, invoke_coverage(inputs))

    assert result.status is ListingTerminationStatus.NOT_TERMINATED
    assert result.selected_successor_relationship_record_hashes == ()


def test_termination_validation_rejects_overlapping_bounded_trade_window() -> None:
    """A possible trade after termination cannot be admitted as ordered history."""
    record = termination_record(
        1970,
        ListingTerminationReason.UNKNOWN,
        last_trade=bounded_boundary("2021-12-29T00:00:00Z", "2022-01-02T00:00:00Z"),
        effective_time=bounded_boundary("2021-12-31T00:00:00Z", "2022-01-03T00:00:00Z"),
    )

    with pytest.raises(DatasetValidationError, match="last_regular_trade"):
        validate_listing_terminations((record,))


def test_unknown_last_trade_ordering_makes_termination_indeterminate() -> None:
    """An exact termination cannot hide unknown last-trade ordering."""
    unknown = TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.UNKNOWN,
        lower_bound=None,
        upper_bound=None,
        source_precision=SourcePrecision.UNKNOWN,
        source_time_label=None,
        source_timezone=None,
        evidence_reference=None,
    )
    termination = termination_record(
        1980,
        ListingTerminationReason.UNKNOWN,
        last_trade=unknown,
        effective_time="2021-12-31T00:00:00Z",
    )
    inputs = lifecycle_inputs(
        standard_lifecycle_events(),
        (termination,),
        evaluation_time="2022-01-01T00:00:00Z",
    )

    result = invoke_termination(inputs, invoke_coverage(inputs))

    assert result.status is ListingTerminationStatus.INDETERMINATE


def test_cross_role_validator_accepts_closed_identity_context() -> None:
    """Every Task 3 reference resolves through typed, interval-compatible identity."""
    issuer = IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=uid(20))
    security = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(21))
    assignments = (
        assignment_for_dependency(issuer, 2000),
        assignment_for_dependency(security, 2010),
        listing_assignment(2020, 1, ListingVenue.XNAS, "2018-01-01T00:00:00Z"),
    )
    relationships = (
        issuer_security_relationship(2030),
        relationship_record(21, 1, 2040),
    )
    mappings = (
        mapping(
            2050, ticker_namespace(ListingVenue.XNAS), "OLD", 1, "2019-01-02T00:00:00Z"
        ),
    )
    classifications = (classification_record(2060),)
    roles = (role_record(2070, 1),)
    events = (
        lifecycle_record(
            2080,
            ListingLifecycleEventKind.ADMITTED,
            "2019-01-02T00:00:00Z",
        ),
    )
    coverage = (
        coverage_record(
            2090,
            ListingHistoryCoverageStatus.COMPLETE,
            "2026-01-01T00:00:00Z",
        ),
    )

    validate_identity_bundle_references(
        assignments,
        relationships,
        mappings,
        classifications,
        roles,
        events,
        (),
        coverage,
    )


@pytest.mark.parametrize("mutation", ("missing", "mistyped", "inactive", "interval"))
def test_cross_role_validator_rejects_invalid_mapping_reference(mutation: str) -> None:
    """Missing, mistyped, inactive, and interval-incompatible references fail."""
    listing = listing_assignment(2100, 1, ListingVenue.XNAS, "2019-01-02T00:00:00Z")
    assignments: tuple[IdentityAssignmentVersionV1, ...] = (listing,)
    target_id = 1
    start = "2019-01-02T00:00:00Z"
    if mutation == "missing":
        assignments = ()
    elif mutation == "mistyped":
        assignments = (security_assignment(2110, 1, "2019-01-02T00:00:00Z"),)
    elif mutation == "inactive":
        assignments = (
            listing.model_copy(
                update={"assignment_effect": IdentityAssignmentEffect.UNASSIGNED}
            ),
        )
    else:
        start = "2018-01-01T00:00:00Z"
    mappings = (
        mapping(2120, ticker_namespace(ListingVenue.XNAS), "OLD", target_id, start),
    )

    with pytest.raises(DatasetValidationError, match="mapping_target"):
        validate_identity_bundle_references(
            assignments,
            (),
            mappings,
            (),
            (),
            (),
            (),
            (),
        )


def test_selection_implementation_hashes_derive_from_pinned_specs() -> None:
    """Selection proof implementation IDs must hash documented immutable specs."""
    expected = {
        "_LISTING_COVERAGE_SELECTION_IMPLEMENTATION_HASH": (
            "32e70af63c8da70f4671537f5c3c6f636d9dd61f94dbbb948d62ff16057862c9"
        ),
        "_LISTING_TERMINATION_SELECTION_IMPLEMENTATION_HASH": (
            "77d589a19c24aa404bf638165b3566dd6cfcb44440f9a49f489cd55e4a458fff"
        ),
        "_LISTING_LIFECYCLE_SELECTION_IMPLEMENTATION_HASH": (
            "99938548614bd63368494e0803cbb40060ca7cffb151d95e8980092c2c21cf20"
        ),
    }
    for hash_name in expected:
        spec_name = hash_name.replace("_HASH", "_SPEC_V1")
        implementation_hash = getattr(identity_module, hash_name)
        specification = getattr(identity_module, spec_name)
        assert implementation_hash == content_hash(specification)
        assert implementation_hash == expected[hash_name]


@pytest.mark.parametrize("availability_case", ("indeterminate", "unavailable"))
def test_mapping_is_indeterminate_when_effective_termination_is_not_usable(
    availability_case: str,
) -> None:
    """An effective but unusable termination dependency cannot authorize mapping."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                2200,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2020-07-01T00:00:00Z",
    )
    termination = termination_record(
        2210,
        ListingTerminationReason.EXCHANGE_DELISTING,
        last_trade="2020-05-31T20:00:00Z",
        effective_time="2020-06-01T00:00:00Z",
    )
    dependency_availability = (
        termination.revision.availability[0].model_copy(
            update={
                "shape": AvailabilityShape.BOUNDED,
                "lower_bound": parse_utc("2025-01-01T00:00:00Z"),
                "upper_bound": parse_utc("2027-01-01T00:00:00Z"),
                "precision": SourcePrecision.INTERVAL,
                "source_time_label": "2025-01-01T00:00:00Z/2027-01-01T00:00:00Z",
            }
        )
        if availability_case == "indeterminate"
        else public_availability("2027-01-01T00:00:00Z")
    )
    termination = termination.model_copy(
        update={
            "revision": termination.revision.model_copy(
                update={
                    "availability": (dependency_availability,),
                    "payload_hash": "0" * 64,
                }
            )
        }
    )
    termination = termination.model_copy(
        update={
            "revision": termination.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(termination))
                }
            )
        }
    )
    termination_manifest, termination_bytes = role_dataset(
        "listing_termination", (termination,)
    )
    termination_decision = validate_identity_dataset(
        termination_manifest,
        (termination_bytes,),
        role_validation_context(2220),
    )
    assert termination_decision.result is ValidationResult.PASS
    bundle = build_validated_dataset_bundle(
        uid(2230),
        "2",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (inputs.manifest, inputs.decision),
            (inputs.assignment_manifest, inputs.assignment_decision),
            (inputs.lifecycle_manifest, inputs.lifecycle_decision),
            (termination_manifest, termination_decision),
        ),
    )
    uncertain_inputs = replace(
        inputs,
        query=inputs.query.model_copy(
            update={"context_bundle_hashes": (content_hash(bundle),)}
        ),
        bundle=bundle,
        terminations=(termination,),
        termination_manifest=termination_manifest,
        termination_decision=termination_decision,
    )

    result = invoke_resolution(uncertain_inputs)

    assert result.classification is RecordResolutionClassification.INDETERMINATE
    assert result.targets == ()
    assert "mapping_lifecycle_dependency_unusable" in result.reasons
    assert len(result.target_lifecycle_proof_hashes) == 2


def test_mapping_is_indeterminate_when_lifecycle_admission_is_indeterminate() -> None:
    """An uncertain admission selection cannot define a mapping target interval."""
    namespace = ticker_namespace(ListingVenue.XNAS)
    inputs = resolution_inputs(
        namespace,
        "OLD",
        (
            mapping(
                2231,
                namespace,
                "OLD",
                1,
                "2019-01-02T00:00:00Z",
                "2021-12-31T00:00:00Z",
            ),
        ),
        "2020-07-01T00:00:00Z",
    )
    admission = next(
        event
        for event in inputs.lifecycle_events
        if event.listing_id == uid(1)
        and event.event_kind is ListingLifecycleEventKind.ADMITTED
    )
    uncertain_availability = admission.revision.availability[0].model_copy(
        update={
            "shape": AvailabilityShape.BOUNDED,
            "lower_bound": parse_utc("2025-01-01T00:00:00Z"),
            "upper_bound": parse_utc("2027-01-01T00:00:00Z"),
            "precision": SourcePrecision.INTERVAL,
            "source_time_label": "2025-01-01T00:00:00Z/2027-01-01T00:00:00Z",
        }
    )
    admission = admission.model_copy(
        update={
            "revision": admission.revision.model_copy(
                update={
                    "availability": (uncertain_availability,),
                    "payload_hash": "0" * 64,
                }
            )
        }
    )
    admission = admission.model_copy(
        update={
            "revision": admission.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(admission))
                }
            )
        }
    )
    events = tuple(
        admission
        if event.listing_id == uid(1)
        and event.event_kind is ListingLifecycleEventKind.ADMITTED
        else event
        for event in inputs.lifecycle_events
    )
    lifecycle_manifest, lifecycle_bytes = role_dataset("listing_lifecycle", events)
    lifecycle_decision = validate_identity_dataset(
        lifecycle_manifest,
        (lifecycle_bytes,),
        role_validation_context(2232),
    )
    assert lifecycle_decision.result is ValidationResult.PASS
    bundle = build_validated_dataset_bundle(
        uid(2233),
        "2",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (inputs.manifest, inputs.decision),
            (inputs.assignment_manifest, inputs.assignment_decision),
            (lifecycle_manifest, lifecycle_decision),
            (inputs.termination_manifest, inputs.termination_decision),
        ),
    )
    uncertain_inputs = replace(
        inputs,
        query=inputs.query.model_copy(
            update={"context_bundle_hashes": (content_hash(bundle),)}
        ),
        bundle=bundle,
        lifecycle_events=events,
        lifecycle_manifest=lifecycle_manifest,
        lifecycle_decision=lifecycle_decision,
    )

    result = invoke_resolution(uncertain_inputs)

    assert result.classification is RecordResolutionClassification.INDETERMINATE
    assert result.targets == ()
    assert "mapping_lifecycle_dependency_unusable" in result.reasons
    assert len(result.target_lifecycle_proof_hashes) == 2


def successor_validation_context(
    successor: IdentityRelationshipVersionV1,
    *,
    successor_id: UUID | None = None,
    extra_relationships: tuple[IdentityRelationshipVersionV1, ...] = (),
) -> tuple[
    tuple[IdentityAssignmentVersionV1, ...],
    tuple[IdentityRelationshipVersionV1, ...],
    tuple[ListingTerminationVersionV1, ...],
]:
    """Build a closed predecessor listing plus one successor relationship chain."""
    issuer = IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=uid(20))
    predecessor = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=uid(21))
    successor_security = IdentityReferenceV1(
        kind=IdentityKind.SECURITY, internal_id=uid(22)
    )
    listing = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1))
    assignments = tuple(
        assignment_for_dependency(reference, 2240 + index)
        for index, reference in enumerate(
            (issuer, predecessor, successor_security, listing)
        )
    )
    listing_link = relationship_record(
        21,
        1,
        2250,
        start="2019-01-02T00:00:00Z",
    )
    relationships = (
        issuer_security_relationship(2260, security=21),
        issuer_security_relationship(2270, security=22),
        listing_link,
        successor,
        *extra_relationships,
    )
    termination = termination_record(
        2280,
        ListingTerminationReason.REORGANIZATION,
        successor_relationship_ids=(
            successor.revision.logical_record_id
            if successor_id is None
            else successor_id,
        ),
    )
    return assignments, relationships, (termination,)


def validate_successor_context(
    successor: IdentityRelationshipVersionV1,
    *,
    successor_id: UUID | None = None,
    extra_relationships: tuple[IdentityRelationshipVersionV1, ...] = (),
) -> None:
    """Invoke cross-role validation for one synthetic successor interpretation."""
    assignments, relationships, terminations = successor_validation_context(
        successor,
        successor_id=successor_id,
        extra_relationships=extra_relationships,
    )
    validate_identity_bundle_references(
        assignments,
        relationships,
        (),
        (),
        (),
        (),
        terminations,
        (),
    )


def test_cross_role_validator_accepts_selected_successor_semantics() -> None:
    """One resolved, correctly directed successor active at termination is valid."""
    validate_successor_context(successor_relationship(2290))


@pytest.mark.parametrize(
    "mutation",
    (
        "missing",
        "wrong_kind",
        "unresolved",
        "superseded",
        "withdrawn",
        "wrong_direction",
        "interval_incompatible",
    ),
)
def test_cross_role_validator_rejects_invalid_successor_semantics(
    mutation: str,
) -> None:
    """Successor IDs authorize only the selected causal security relationship."""
    successor = successor_relationship(2300)
    successor_id: UUID | None = None
    extra: tuple[IdentityRelationshipVersionV1, ...] = ()
    if mutation == "missing":
        successor_id = uid(9999)
    elif mutation == "wrong_kind":
        successor_id = uid(2250)
    elif mutation == "unresolved":
        successor = successor.model_copy(
            update={"resolution_status": ResolutionStatus.DISPUTED}
        )
    elif mutation in {"superseded", "withdrawn"}:
        latest = successor.model_copy(
            update={
                "revision": successor.revision.model_copy(
                    update={
                        "record_version_id": uid(2301),
                        "revision_kind": (
                            RevisionKind.CORRECTION
                            if mutation == "superseded"
                            else RevisionKind.WITHDRAWAL
                        ),
                        "supersedes_record_version_id": (
                            successor.revision.record_version_id
                        ),
                        "source_sequence": 1,
                    }
                ),
                "resolution_status": (
                    ResolutionStatus.DISPUTED
                    if mutation == "superseded"
                    else ResolutionStatus.RESOLVED
                ),
            }
        )
        extra = (latest,)
    elif mutation == "wrong_direction":
        successor = successor.model_copy(
            update={"left": successor.right, "right": successor.left}
        )
    else:
        successor = successor.model_copy(
            update={"effective_interval": interval("2022-01-01T00:00:00Z")}
        )

    with pytest.raises(DatasetValidationError, match="termination_successor"):
        validate_successor_context(
            successor,
            successor_id=successor_id,
            extra_relationships=extra,
        )
