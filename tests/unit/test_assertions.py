"""Tests for M1b assertion temporality and cutoff authorization."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_dataset_validation_v2 import fixed_manifest, passing_decision

from drift.datasets.assertions import (
    build_cutoff_selection_proof,
    build_validated_dataset_bundle,
    decision_reference_from_proof,
    resolve_selected_records,
    select_assertion_version,
    validate_assertion_chain,
)
from drift.datasets.hashing import assertion_version_payload
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    AssertionSelectionResultV1,
    AssertionVersionProjectionV1,
    BoundaryShape,
    CutoffSelectionProofV1,
    DecisionSelectionReferenceV1,
    EffectiveTimeStatus,
    HistoryCompleteness,
    InformationRole,
    IntervalStatus,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
    evaluate_boundary_at,
    evaluate_interval_at,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    ValidationScope,
)
from drift.domain.revisions import RevisionKind
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    CutoffEligibility,
    SourcePrecision,
)
from drift.serialization.canonical import content_hash

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
LOGICAL_RECORD_ID = UUID("019b8240-0000-7000-8000-000000000020")
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="synthetic")


def parse_utc(value: str) -> datetime:
    """Parse fixed test instants independently of production evaluators."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def artifact(location: str = "evidence/source.json") -> ArtifactReference:
    """Build a fixed safe source artifact."""
    return ArtifactReference(
        artifact_id=UUID("019b8240-0000-7000-8000-000000000001"),
        kind=ArtifactKind.OTHER,
        content_hash=HASH_A,
        location=location,
    )


def exact_boundary(value: str = "2020-01-02T14:30:00Z") -> TemporalBoundaryClaimV1:
    """Build a source-exact second boundary."""
    instant = parse_utc(value)
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=instant,
        upper_bound=instant,
        source_precision=SourcePrecision.SECOND,
        source_time_label=value,
        source_timezone=None,
        evidence_reference=artifact(),
    )


def bounded_day() -> TemporalBoundaryClaimV1:
    """Build a New York date claim with hand-derived UTC bounds."""
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=parse_utc("2020-01-02T05:00:00Z"),
        upper_bound=parse_utc("2020-01-03T05:00:00Z"),
        source_precision=SourcePrecision.DATE,
        source_time_label="2020-01-02",
        source_timezone="America/New_York",
        evidence_reference=artifact(),
    )


def unknown_boundary() -> TemporalBoundaryClaimV1:
    """Build an explicitly unknown effective boundary."""
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.UNKNOWN,
        lower_bound=None,
        upper_bound=None,
        source_precision=SourcePrecision.UNKNOWN,
        source_time_label=None,
        source_timezone=None,
        evidence_reference=artifact(),
    )


@pytest.mark.parametrize(
    ("claim", "instant", "expected"),
    (
        (exact_boundary(), "2020-01-02T14:29:59Z", EffectiveTimeStatus.NOT_EFFECTIVE),
        (exact_boundary(), "2020-01-02T14:30:00Z", EffectiveTimeStatus.EFFECTIVE),
        (bounded_day(), "2020-01-02T04:59:59Z", EffectiveTimeStatus.NOT_EFFECTIVE),
        (bounded_day(), "2020-01-02T12:00:00Z", EffectiveTimeStatus.INDETERMINATE),
        (bounded_day(), "2020-01-03T05:00:00Z", EffectiveTimeStatus.EFFECTIVE),
        (unknown_boundary(), "2030-01-01T00:00:00Z", EffectiveTimeStatus.INDETERMINATE),
    ),
)
def test_effective_boundary_is_conservative(
    claim: TemporalBoundaryClaimV1,
    instant: str,
    expected: EffectiveTimeStatus,
) -> None:
    """Changing either conservative bound branch must fail this table."""
    assert evaluate_boundary_at(claim, parse_utc(instant)) is expected


def test_open_ended_interval_remains_active_after_start() -> None:
    """Treating an omitted end as unknown instead of open-ended must fail."""
    interval = TemporalIntervalClaimV1(
        schema_version="1", start=exact_boundary(), end=None
    )
    assert evaluate_interval_at(interval, parse_utc("2025-01-01T00:00:00Z")) is (
        IntervalStatus.ACTIVE
    )


def test_unknown_end_makes_post_start_state_indeterminate() -> None:
    """Treating an explicitly unknown end as ongoing must fail."""
    interval = TemporalIntervalClaimV1(
        schema_version="1", start=exact_boundary(), end=unknown_boundary()
    )
    assert evaluate_interval_at(interval, parse_utc("2025-01-01T00:00:00Z")) is (
        IntervalStatus.INDETERMINATE
    )


@pytest.mark.parametrize(
    "mutation",
    (
        {"lower_bound": None},
        {"upper_bound": parse_utc("2020-01-02T14:31:00Z")},
        {"source_precision": SourcePrecision.DATE},
        {"source_time_label": "2020-01-02T14:30:01Z"},
    ),
)
def test_exact_boundary_rejects_false_precision(mutation: dict[str, object]) -> None:
    """An exact claim cannot retain missing, unequal, or inconsistent evidence."""
    values = exact_boundary().model_dump(mode="python")
    values.update(mutation)
    with pytest.raises(ValidationError):
        TemporalBoundaryClaimV1.model_validate(values)


def test_boundary_rejects_credential_bearing_evidence_reference() -> None:
    """Credential-bearing source locations must not enter immutable provenance."""
    values = exact_boundary().model_dump(mode="python")
    values["evidence_reference"] = artifact("https://example.test/a?api_key=secret")
    with pytest.raises(ValidationError, match="credential"):
        TemporalBoundaryClaimV1.model_validate(values)


def public_availability(value: str) -> AvailabilityEvidenceV1:
    """Build exact public availability evidence."""
    instant = parse_utc(value)
    return AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.EXACT,
        lower_bound=instant,
        upper_bound=instant,
        precision=SourcePrecision.SECOND,
        source_time_label=value,
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=artifact(),
    )


def test_revision_envelope_canonicalizes_channels_and_rejects_duplicates() -> None:
    """Channel order must be canonical and duplicate evidence must fail."""
    public = public_availability("2020-01-03T00:00:00Z")
    system_channel = AvailabilityChannelV1(
        kind=ChannelKind.SYSTEM, identifier="synthetic"
    )
    system = AvailabilityEvidenceV1(
        channel=system_channel,
        shape=AvailabilityShape.EXACT,
        lower_bound=parse_utc("2020-01-04T00:00:00Z"),
        upper_bound=parse_utc("2020-01-04T00:00:00Z"),
        precision=SourcePrecision.SECOND,
        source_time_label="2020-01-04T00:00:00Z",
        source_timezone=None,
        basis=AvailabilityBasis.LOCAL_INGEST,
        evidence_reference=artifact(),
    )
    envelope = RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=UUID("019b8240-0000-7000-8000-000000000010"),
        record_version_id=UUID("019b8240-0000-7000-8000-000000000011"),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(system, public),
        history_completeness=HistoryCompleteness.COMPLETE,
        source_native_revision_label=None,
        source_artifact=artifact(),
        payload_hash=HASH_A,
    )
    assert envelope.availability == (public, system)

    values = envelope.model_dump(mode="python")
    values["availability"] = (public, public)
    with pytest.raises(ValidationError, match="unique"):
        RevisionEnvelopeV1.model_validate(values)


def test_first_observed_source_correction_cannot_claim_complete_history() -> None:
    """A missing predecessor cannot be hidden behind a complete-history claim."""
    with pytest.raises(ValidationError, match="complete"):
        RevisionEnvelopeV1(
            schema_version="1",
            logical_record_id=UUID("019b8240-0000-7000-8000-000000000010"),
            record_version_id=UUID("019b8240-0000-7000-8000-000000000011"),
            revision_kind=RevisionKind.INITIAL,
            supersedes_record_version_id=None,
            source_sequence=0,
            availability=(public_availability("2020-01-03T00:00:00Z"),),
            history_completeness=HistoryCompleteness.COMPLETE,
            source_native_revision_label="correction",
            source_artifact=artifact(),
            payload_hash=HASH_A,
        )


def test_assertion_payload_excludes_only_nested_self_hash() -> None:
    """Dropping any parent assertion field from its payload preimage must fail."""
    record = {
        "schema_version": "1",
        "revision": {"payload_hash": HASH_A, "source_sequence": 3},
        "business_state": "asserted",
    }
    assert assertion_version_payload(record) == {
        "schema_version": "1",
        "revision": {"source_sequence": 3},
        "business_state": "asserted",
    }


def projection(
    sequence: int,
    available_at: str,
    *,
    revision_kind: RevisionKind = RevisionKind.INITIAL,
    predecessor: UUID | None = None,
    logical_record_id: UUID = LOGICAL_RECORD_ID,
    record_hash: str = HASH_A,
) -> AssertionVersionProjectionV1:
    """Build a fixed assertion projection for causal selection tests."""
    return AssertionVersionProjectionV1(
        revision=RevisionEnvelopeV1(
            schema_version="1",
            logical_record_id=logical_record_id,
            record_version_id=UUID(f"019b8240-0000-7000-8000-{sequence + 21:012d}"),
            revision_kind=revision_kind,
            supersedes_record_version_id=predecessor,
            source_sequence=sequence,
            availability=(public_availability(available_at),),
            history_completeness=HistoryCompleteness.COMPLETE,
            source_native_revision_label=None,
            source_artifact=artifact(),
            payload_hash=HASH_C,
        ),
        record_hash=record_hash,
    )


def test_assertion_chain_rejects_branching_and_logical_key_changes() -> None:
    """A correction chain cannot fork or cross logical record identities."""
    root = projection(0, "2020-01-01T00:00:00Z")
    first = projection(
        1,
        "2020-02-01T00:00:00Z",
        revision_kind=RevisionKind.CORRECTION,
        predecessor=root.revision.record_version_id,
        record_hash=HASH_B,
    )
    branch = projection(
        2,
        "2020-03-01T00:00:00Z",
        revision_kind=RevisionKind.CORRECTION,
        predecessor=root.revision.record_version_id,
        record_hash="d" * 64,
    )
    assert {
        finding.code for finding in validate_assertion_chain((root, first, branch))
    } == {"branching_revision_chain"}

    wrong_key = projection(
        1,
        "2020-02-01T00:00:00Z",
        revision_kind=RevisionKind.CORRECTION,
        predecessor=root.revision.record_version_id,
        logical_record_id=UUID("019b8240-0000-7000-8000-000000000099"),
        record_hash=HASH_B,
    )
    assert "logical_record_id_mismatch" in {
        finding.code for finding in validate_assertion_chain((root, wrong_key))
    }


def test_cutoff_selection_does_not_use_later_correction() -> None:
    """Selecting the latest record regardless of K must fail this test."""
    root = projection(0, "2020-01-01T00:00:00Z")
    corrected = projection(
        1,
        "2020-03-01T00:00:00Z",
        revision_kind=RevisionKind.CORRECTION,
        predecessor=root.revision.record_version_id,
        record_hash=HASH_B,
    )
    result = select_assertion_version(
        (corrected, root),
        PUBLIC,
        AvailabilityPolicyV1(policy_id="strict"),
        parse_utc("2020-02-01T00:00:00Z"),
        {},
    )
    assert result.classification.value == "eligible"
    assert result.selected_record_hash == HASH_A
    assert result.considered_record_hashes == (HASH_A, HASH_B)


def record_decision(*record_hashes: str) -> DatasetValidationDecisionV2:
    """Upgrade a real structure decision to an exact record-scope decision."""
    base = passing_decision()
    return base.model_copy(
        update={
            "validation_scope": ValidationScope.RECORDS,
            "validated_record_hashes": tuple(sorted(record_hashes)),
        }
    )


def query_for(
    decision: DatasetValidationDecisionV2, bundle_hash: str
) -> NormalizedSelectionQueryV1:
    """Build a hash-consistent decision-information query."""
    manifest = fixed_manifest()
    return NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
        information_role=InformationRole.DECISION_INFORMATION,
        resolution_mode=ResolutionMode.AS_KNOWN,
        subject_hash=HASH_C,
        source_manifest_hash=decision.manifest_hash,
        validation_decision_hash=content_hash(decision),
        context_bundle_hashes=(bundle_hash,),
        dataset_role_hash=decision.dataset_role_hash,
        record_contract_hash=decision.temporal_contract_hash,
        schema_hash=manifest.schema_definition.schema_hash,
        knowledge_cutoff=parse_utc("2020-02-01T00:00:00Z"),
        evaluation_time=parse_utc("2020-02-01T00:00:00Z"),
        requested_channel=PUBLIC,
        policy_id="strict",
        policy_hash=content_hash(AvailabilityPolicyV1(policy_id="strict")),
    )


def test_selection_proof_and_decision_reference_hide_considered_records() -> None:
    """Decision capability must hide the audit candidate set."""
    manifest = fixed_manifest()
    decision = record_decision(HASH_A, HASH_B)
    bundle = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000030"),
        "1",
        parse_utc("2020-02-01T00:00:00Z"),
        ((manifest, decision),),
    )
    query = query_for(decision, content_hash(bundle))
    selection = AssertionSelectionResultV1(
        schema_version="1",
        classification=CutoffEligibility.ELIGIBLE,
        reason="latest_definitely_available_version",
        cutoff=query.knowledge_cutoff,
        requested_channel=PUBLIC,
        policy=AvailabilityPolicyV1(policy_id="strict"),
        policy_id="strict",
        policy_hash=query.policy_hash,
        considered_versions=(
            projection(0, "2020-01-01T00:00:00Z"),
            projection(
                1,
                "2020-03-01T00:00:00Z",
                revision_kind=RevisionKind.CORRECTION,
                predecessor=UUID("019b8240-0000-7000-8000-000000000021"),
                record_hash=HASH_B,
            ),
        ),
        considered_record_hashes=(HASH_A, HASH_B),
        selected_record_hash=HASH_A,
    )
    proof = build_cutoff_selection_proof(
        query, (selection,), manifest, decision, (bundle,), "e" * 64
    )
    reference = decision_reference_from_proof(proof)
    assert isinstance(proof, CutoffSelectionProofV1)
    assert isinstance(reference, DecisionSelectionReferenceV1)
    assert reference.selected_record_hashes == (HASH_A,)
    assert not hasattr(reference, "considered_record_hashes")
    assert resolve_selected_records(reference, {HASH_A: b"selected"}) == {
        HASH_A: b"selected"
    }
    with pytest.raises(DatasetValidationError, match="unauthorized_record_hash"):
        resolve_selected_records(reference, {HASH_A: b"selected", HASH_B: b"future"})
    with pytest.raises(DatasetValidationError, match="context_bundle"):
        build_cutoff_selection_proof(
            query, (selection,), manifest, decision, (), "e" * 64
        )


def test_current_interpretation_cannot_become_a_decision_reference() -> None:
    """Ex-post resolution must never gain decision-information authority."""
    query = NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
        information_role=InformationRole.EX_POST_OUTCOME,
        resolution_mode=ResolutionMode.CURRENT_INTERPRETATION,
        subject_hash=HASH_A,
        source_manifest_hash=HASH_A,
        validation_decision_hash=HASH_B,
        context_bundle_hashes=(HASH_C,),
        dataset_role_hash=HASH_A,
        record_contract_hash=HASH_B,
        schema_hash=HASH_C,
        knowledge_cutoff=parse_utc("2020-02-01T00:00:00Z"),
        evaluation_time=parse_utc("2020-02-01T00:00:00Z"),
        requested_channel=PUBLIC,
        policy_id="strict",
        policy_hash=HASH_C,
    )
    proof = CutoffSelectionProofV1(
        schema_version="1",
        source_manifest_hash=HASH_A,
        validation_decision_hash=HASH_B,
        selection_algorithm="drift-m1b-cutoff-selection-v1",
        selection_implementation_hash=HASH_C,
        normalized_query=query,
        normalized_query_hash=content_hash(query),
        considered_record_hashes=(HASH_A,),
        selected_record_hashes=(HASH_A,),
        classification=CutoffEligibility.ELIGIBLE,
        reasons=("current interpretation",),
    )
    with pytest.raises(DatasetValidationError, match="decision_information"):
        decision_reference_from_proof(proof)
