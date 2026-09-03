"""Effective-time claims and immutable assertion revision envelopes."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.domain.revisions import RevisionKind
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
    SourcePrecision,
    availability_channel_identity,
    expected_exact_second,
    expected_source_window,
)
from drift.serialization.canonical import content_hash


class BoundaryShape(StrEnum):
    """Precision shape of an effective-time boundary."""

    EXACT = "exact"
    BOUNDED = "bounded"
    UNKNOWN = "unknown"


class EffectiveTimeStatus(StrEnum):
    """Conservative relation between a boundary and an evaluation instant."""

    NOT_EFFECTIVE = "not_effective"
    EFFECTIVE = "effective"
    INDETERMINATE = "indeterminate"


class IntervalStatus(StrEnum):
    """Conservative state of an interval at an evaluation instant."""

    BEFORE = "before"
    ACTIVE = "active"
    ENDED = "ended"
    INDETERMINATE = "indeterminate"


class HistoryCompleteness(StrEnum):
    """How completely a retained source snapshot captures earlier revisions."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ResolutionMode(StrEnum):
    """Whether resolution is historical decision-time or current audit-time."""

    AS_KNOWN = "as_known"
    CURRENT_INTERPRETATION = "current_interpretation"


class InformationRole(StrEnum):
    """Authorized information role of a selection query."""

    DECISION_INFORMATION = "decision_information"
    EX_POST_OUTCOME = "ex_post_outcome"


class M1bSelectionPurpose(StrEnum):
    """Closed M1b purpose vocabulary for cutoff selection."""

    IDENTITY_RESOLUTION = "identity_resolution"
    STRUCTURAL_ELIGIBILITY = "structural_eligibility"
    UNIVERSE_MEMBERSHIP = "universe_membership"
    LISTING_LIFECYCLE = "listing_lifecycle"
    LISTING_TERMINATION = "listing_termination"


class TemporalBoundaryClaimV1(FrozenModel):
    """A source-preserving claim about when a state became effective."""

    schema_version: Literal["1"]
    shape: BoundaryShape
    lower_bound: UTCDateTime | None
    upper_bound: UTCDateTime | None
    source_precision: SourcePrecision
    source_time_label: NonBlankStr | None
    source_timezone: NonBlankStr | None
    evidence_reference: ArtifactReference | None

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_locator(
        cls, reference: ArtifactReference | None
    ) -> ArtifactReference | None:
        if reference is None:
            return None
        return validate_safe_provenance_reference(reference)

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        if self.shape is BoundaryShape.UNKNOWN:
            if self.lower_bound is not None or self.upper_bound is not None:
                msg = "unknown boundary cannot have bounds"
                raise ValueError(msg)
            if self.source_precision is not SourcePrecision.UNKNOWN:
                msg = "unknown boundary requires unknown precision"
                raise ValueError(msg)
            if self.source_time_label is not None or self.source_timezone is not None:
                msg = "unknown boundary cannot invent a source label or timezone"
                raise ValueError(msg)
            return self

        if self.lower_bound is None or self.upper_bound is None:
            msg = "known boundary requires bounds"
            raise ValueError(msg)
        if self.source_time_label is None:
            msg = "known boundary requires a retained source label"
            raise ValueError(msg)

        if self.shape is BoundaryShape.EXACT:
            if self.source_precision is not SourcePrecision.SECOND:
                msg = "exact boundary requires second precision"
                raise ValueError(msg)
            if self.lower_bound != self.upper_bound:
                msg = "exact boundary requires equal bounds"
                raise ValueError(msg)
            if self.lower_bound != expected_exact_second(self.source_time_label):
                msg = "exact boundary bounds must match its source label"
                raise ValueError(msg)
            return self

        if self.lower_bound >= self.upper_bound:
            msg = "bounded boundary requires ordered bounds"
            raise ValueError(msg)
        if self.source_precision in {SourcePrecision.DATE, SourcePrecision.MINUTE}:
            if self.source_timezone is None:
                msg = "date or minute boundary requires an IANA timezone"
                raise ValueError(msg)
            expected = expected_source_window(
                self.source_time_label,
                self.source_precision,
                self.source_timezone,
            )
            if (self.lower_bound, self.upper_bound) != expected:
                msg = "bounded boundary bounds must match its source label window"
                raise ValueError(msg)
        elif self.source_precision not in {
            SourcePrecision.SECOND,
            SourcePrecision.INTERVAL,
            SourcePrecision.SESSION,
        }:
            msg = "bounded boundary requires known bounded precision"
            raise ValueError(msg)
        if (
            self.source_precision is SourcePrecision.SESSION
            and self.evidence_reference is None
        ):
            msg = "session boundary requires an evidence artifact"
            raise ValueError(msg)
        return self


class TemporalIntervalClaimV1(FrozenModel):
    """A possibly open-ended effective interval."""

    schema_version: Literal["1"]
    start: TemporalBoundaryClaimV1
    end: TemporalBoundaryClaimV1 | None

    @model_validator(mode="after")
    def validate_known_order(self) -> Self:
        if (
            self.end is not None
            and self.start.lower_bound is not None
            and self.end.upper_bound is not None
            and self.end.upper_bound < self.start.lower_bound
        ):
            msg = "interval end cannot definitely precede its start"
            raise ValueError(msg)
        return self


class RevisionEnvelopeV1(FrozenModel):
    """Causal revision metadata shared by versioned M1b assertions."""

    schema_version: Literal["1"]
    logical_record_id: UUID7
    record_version_id: UUID7
    revision_kind: RevisionKind
    supersedes_record_version_id: UUID7 | None
    source_sequence: Annotated[int, Field(ge=0)]
    availability: tuple[AvailabilityEvidenceV1, ...]
    history_completeness: HistoryCompleteness
    source_native_revision_label: NonBlankStr | None
    source_artifact: ArtifactReference
    payload_hash: SHA256Hash

    @field_validator("availability")
    @classmethod
    def canonicalize_availability(
        cls, availability: tuple[AvailabilityEvidenceV1, ...]
    ) -> tuple[AvailabilityEvidenceV1, ...]:
        if not availability:
            msg = "assertion revision requires availability evidence"
            raise ValueError(msg)
        channels = tuple(item.channel for item in availability)
        if len(set(channels)) != len(channels):
            msg = "assertion revision availability channels must be unique"
            raise ValueError(msg)
        return tuple(
            sorted(
                availability,
                key=lambda item: availability_channel_identity(item.channel),
            )
        )

    @field_validator("source_artifact")
    @classmethod
    def reject_credential_bearing_source(
        cls, source: ArtifactReference
    ) -> ArtifactReference:
        return validate_safe_provenance_reference(source)

    @model_validator(mode="after")
    def validate_causal_shape(self) -> Self:
        if self.logical_record_id == self.record_version_id:
            msg = "logical record and record version IDs must differ"
            raise ValueError(msg)
        if self.revision_kind is RevisionKind.INITIAL:
            if self.supersedes_record_version_id is not None:
                msg = "initial revision cannot have a predecessor"
                raise ValueError(msg)
            if (
                self.source_native_revision_label is not None
                and self.history_completeness is HistoryCompleteness.COMPLETE
            ):
                msg = "first observed source revision cannot claim complete history"
                raise ValueError(msg)
        elif self.supersedes_record_version_id is None:
            msg = "non-initial revision requires a predecessor"
            raise ValueError(msg)
        if self.supersedes_record_version_id == self.record_version_id:
            msg = "assertion revision cannot supersede itself"
            raise ValueError(msg)
        return self


class AssertionVersionProjectionV1(FrozenModel):
    """Revision metadata paired with the owning assertion record hash."""

    revision: RevisionEnvelopeV1
    record_hash: SHA256Hash


class AssertionSelectionResultV1(FrozenModel):
    """Hash-bound selection result for one logical assertion chain."""

    schema_version: Literal["1"]
    classification: CutoffEligibility
    reason: NonBlankStr
    cutoff: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    considered_versions: tuple[AssertionVersionProjectionV1, ...]
    considered_record_hashes: tuple[SHA256Hash, ...]
    selected_record_hash: SHA256Hash | None

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.policy_id != self.policy.policy_id:
            msg = "selection policy ID must match policy"
            raise ValueError(msg)
        if self.policy_hash != content_hash(self.policy):
            msg = "selection policy hash must match policy"
            raise ValueError(msg)
        ordered = tuple(
            sorted(
                self.considered_versions,
                key=lambda item: item.revision.source_sequence,
            )
        )
        if self.considered_versions != ordered:
            msg = "considered assertion versions must be in source sequence order"
            raise ValueError(msg)
        expected_hashes = tuple(item.record_hash for item in ordered)
        if self.considered_record_hashes != expected_hashes:
            msg = "considered record hashes must match considered versions"
            raise ValueError(msg)
        if len(set(expected_hashes)) != len(expected_hashes):
            msg = "considered record hashes must be unique"
            raise ValueError(msg)
        if (
            self.selected_record_hash is not None
            and self.selected_record_hash not in expected_hashes
        ):
            msg = "selected record hash must be considered"
            raise ValueError(msg)
        if (
            self.classification is CutoffEligibility.ELIGIBLE
            and self.selected_record_hash is None
        ):
            msg = "eligible selection requires a selected record hash"
            raise ValueError(msg)
        if (
            self.classification is not CutoffEligibility.ELIGIBLE
            and self.selected_record_hash is not None
        ):
            msg = "non-eligible selection cannot expose a selected record hash"
            raise ValueError(msg)
        return self


class NormalizedSelectionQueryV1(FrozenModel):
    """Exact purpose, time, channel, policy, and dataset identity for selection."""

    schema_version: Literal["1"]
    purpose: M1bSelectionPurpose
    information_role: InformationRole
    resolution_mode: ResolutionMode
    subject_hash: SHA256Hash
    source_manifest_hash: SHA256Hash
    validation_decision_hash: SHA256Hash
    context_bundle_hashes: tuple[SHA256Hash, ...]
    dataset_role_hash: SHA256Hash
    record_contract_hash: SHA256Hash
    schema_hash: SHA256Hash
    knowledge_cutoff: UTCDateTime
    evaluation_time: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash

    @field_validator("context_bundle_hashes")
    @classmethod
    def canonicalize_bundle_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if not hashes:
            msg = "selection query requires a context bundle"
            raise ValueError(msg)
        if len(set(hashes)) != len(hashes):
            msg = "selection query context bundle hashes must be unique"
            raise ValueError(msg)
        return tuple(sorted(hashes))

    @model_validator(mode="after")
    def validate_role_mode(self) -> Self:
        if self.resolution_mode is ResolutionMode.AS_KNOWN:
            if self.information_role is not InformationRole.DECISION_INFORMATION:
                msg = "as-known resolution requires decision information"
                raise ValueError(msg)
        elif self.information_role is not InformationRole.EX_POST_OUTCOME:
            msg = "current interpretation requires the ex-post audit role"
            raise ValueError(msg)
        return self


class CutoffSelectionProofV1(FrozenModel):
    """Audit-side proof retaining the complete considered and selected sets."""

    schema_version: Literal["1"]
    source_manifest_hash: SHA256Hash
    validation_decision_hash: SHA256Hash
    selection_algorithm: Literal["drift-m1b-cutoff-selection-v1"]
    selection_implementation_hash: SHA256Hash
    normalized_query: NormalizedSelectionQueryV1
    normalized_query_hash: SHA256Hash
    considered_record_hashes: tuple[SHA256Hash, ...]
    selected_record_hashes: tuple[SHA256Hash, ...]
    classification: CutoffEligibility
    reasons: tuple[NonBlankStr, ...]

    @field_validator("considered_record_hashes", "selected_record_hashes")
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(hashes)) != len(hashes):
            msg = "selection proof record hashes must be unique"
            raise ValueError(msg)
        return tuple(sorted(hashes))

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(
        cls, reasons: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        if not reasons:
            msg = "selection proof requires a reason"
            raise ValueError(msg)
        return tuple(sorted(set(reasons)))

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.source_manifest_hash != self.normalized_query.source_manifest_hash:
            msg = "proof manifest hash must match normalized query"
            raise ValueError(msg)
        if (
            self.validation_decision_hash
            != self.normalized_query.validation_decision_hash
        ):
            msg = "proof validation decision hash must match normalized query"
            raise ValueError(msg)
        if self.normalized_query_hash != content_hash(self.normalized_query):
            msg = "normalized query hash must match normalized query"
            raise ValueError(msg)
        if not set(self.selected_record_hashes).issubset(self.considered_record_hashes):
            msg = "selected record hashes must be considered"
            raise ValueError(msg)
        if (
            self.classification is CutoffEligibility.ELIGIBLE
            and not self.selected_record_hashes
        ):
            msg = "eligible proof requires selected records"
            raise ValueError(msg)
        if (
            self.classification is not CutoffEligibility.ELIGIBLE
            and self.selected_record_hashes
        ):
            msg = "non-eligible proof cannot expose selected records"
            raise ValueError(msg)
        return self


class DecisionSelectionReferenceV1(FrozenModel):
    """Decision-side capability exposing only selected record hashes."""

    schema_version: Literal["1"]
    selection_proof_hash: SHA256Hash
    normalized_query_hash: SHA256Hash
    purpose: M1bSelectionPurpose
    information_role: Literal[InformationRole.DECISION_INFORMATION]
    selected_record_hashes: tuple[SHA256Hash, ...]

    @field_validator("selected_record_hashes")
    @classmethod
    def canonicalize_selected_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(hashes)) != len(hashes):
            msg = "decision selection record hashes must be unique"
            raise ValueError(msg)
        return tuple(sorted(hashes))


class ResolutionEvidenceV1(FrozenModel):
    """Common exact selection evidence embedded in M1b resolution results."""

    schema_version: Literal["1"]
    normalized_query: NormalizedSelectionQueryV1
    normalized_query_hash: SHA256Hash
    considered_record_hashes: tuple[SHA256Hash, ...]
    selected_record_hashes: tuple[SHA256Hash, ...]
    selection_proof_hashes: tuple[SHA256Hash, ...]

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        if self.normalized_query_hash != content_hash(self.normalized_query):
            msg = "resolution query hash must match normalized query"
            raise ValueError(msg)
        for label, hashes in (
            ("considered", self.considered_record_hashes),
            ("selected", self.selected_record_hashes),
            ("proof", self.selection_proof_hashes),
        ):
            if hashes != tuple(sorted(set(hashes))):
                msg = f"resolution {label} hashes must be sorted and unique"
                raise ValueError(msg)
        if not set(self.selected_record_hashes).issubset(self.considered_record_hashes):
            msg = "resolution selected hashes must be considered"
            raise ValueError(msg)
        return self


def evaluate_boundary_at(
    claim: TemporalBoundaryClaimV1, instant: datetime
) -> EffectiveTimeStatus:
    """Evaluate an effective boundary without inventing precision."""
    instant_utc = instant.astimezone(UTC) if instant.tzinfo is not None else None
    if instant_utc is None or instant.utcoffset() is None:
        msg = "evaluation instant must be timezone-aware"
        raise ValueError(msg)
    if claim.shape is BoundaryShape.UNKNOWN:
        return EffectiveTimeStatus.INDETERMINATE
    assert claim.lower_bound is not None
    assert claim.upper_bound is not None
    if instant_utc < claim.lower_bound:
        return EffectiveTimeStatus.NOT_EFFECTIVE
    if instant_utc >= claim.upper_bound:
        return EffectiveTimeStatus.EFFECTIVE
    return EffectiveTimeStatus.INDETERMINATE


def evaluate_interval_at(
    claim: TemporalIntervalClaimV1, instant: datetime
) -> IntervalStatus:
    """Evaluate a possibly open interval at one instant."""
    start = evaluate_boundary_at(claim.start, instant)
    if start is EffectiveTimeStatus.NOT_EFFECTIVE:
        return IntervalStatus.BEFORE
    if start is EffectiveTimeStatus.INDETERMINATE:
        return IntervalStatus.INDETERMINATE
    if claim.end is None:
        return IntervalStatus.ACTIVE
    end = evaluate_boundary_at(claim.end, instant)
    if end is EffectiveTimeStatus.NOT_EFFECTIVE:
        return IntervalStatus.ACTIVE
    if end is EffectiveTimeStatus.EFFECTIVE:
        return IntervalStatus.ENDED
    return IntervalStatus.INDETERMINATE
