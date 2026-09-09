"""Immutable results for orthogonal observation missingness and usability."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.observation_query import ObservationQueryV1
from drift.serialization.canonical import content_hash

type ScheduledDayStatus = Literal["regular", "early_close", "closed", "unknown"]
type RealizedOutcomeStatus = Literal["opened", "did_not_open", "unknown"]
type ObservationLifecycleStatus = Literal[
    "active", "not_yet_listed", "suspended", "terminated", "indeterminate"
]
type ObservationCoverageStatus = Literal[
    "expected_complete", "not_expected", "partial", "unknown"
]
type PresenceStatus = Literal["present", "absent", "unknown"]
type RequiredFieldsStatus = Literal["complete", "partial", "unknown"]
type ActivityStatus = Literal["reported", "explicit_none", "unknown"]
type CutoffAvailabilityStatus = Literal["eligible", "ineligible", "indeterminate"]
type ProviderGapStatus = Literal["proven", "not_proven"]
type UsabilityStatus = Literal["usable", "unusable", "indeterminate"]
type ProfileCompatibilityStatus = Literal["compatible", "incompatible", "indeterminate"]


class InterruptionAggregationPolicyV1(FrozenModel):
    """Closed source policy for excluding and aggregating interruption segments."""

    schema_version: Literal["1"] = "1"
    kind: Literal["observation_interval_event_policy"]
    contract_id: UUID7
    contract_version: NonBlankStr
    source_id: NonBlankStr
    interval_semantics: Literal["half_open_utc_segments_v1"]
    interruption_aggregation: Literal[
        "exclude_suspended_segments_aggregate_eligible_segments_v1"
    ]
    required_fields: tuple[
        Literal["open"],
        Literal["high"],
        Literal["low"],
        Literal["close"],
        Literal["volume"],
    ]
    require_complete_interruption_intervals: Literal[True]


class ObservationNumericViewV1(FrozenModel):
    """Exact source-basis values admitted by the narrow research profile."""

    schema_version: Literal["1"] = "1"
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    currency: NonBlankStr
    source_basis: Literal["unadjusted"]
    observation_hash: SHA256Hash
    contract_hash: SHA256Hash


class ListingEligibilitySegmentV1(FrozenModel):
    """One constant-state segment in the finite listing interval sweep."""

    schema_version: Literal["1"] = "1"
    opened_at: UTCDateTime
    closed_at: UTCDateTime
    lifecycle: ObservationLifecycleStatus
    structural_classification: Literal["eligible", "ineligible", "indeterminate"]
    structural_resolution_hash: SHA256Hash
    lifecycle_resolution_hash: SHA256Hash | None
    selection_proof_hashes: tuple[SHA256Hash, ...]

    @field_validator("selection_proof_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(set(values))):
            raise ValueError("eligibility segment proof hashes must be canonical")
        return values

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.closed_at <= self.opened_at:
            raise ValueError("eligibility segment close must follow open")
        return self


class ListingSessionEligibilityResultV1(FrozenModel):
    """Research-universe and scheduled-session eligibility, not tradability."""

    schema_version: Literal["1"] = "1"
    query: ObservationQueryV1
    query_hash: SHA256Hash
    structural_resolution_hashes: tuple[SHA256Hash, ...]
    lifecycle_resolution_hashes: tuple[SHA256Hash, ...]
    selected_schedule_hash: SHA256Hash | None
    selected_schedule_proof_hash: SHA256Hash
    generated_schedule_hash: SHA256Hash | None
    classification: Literal["eligible", "ineligible", "indeterminate"]
    lifecycle: ObservationLifecycleStatus
    segments: tuple[ListingEligibilitySegmentV1, ...]
    reasons: tuple[NonBlankStr, ...]
    context_hash: SHA256Hash
    policy_hash: SHA256Hash
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash
    inner_knowledge_cutoff: UTCDateTime

    @field_validator("structural_resolution_hashes", "lifecycle_resolution_hashes")
    @classmethod
    def canonicalize_result_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("eligibility result hashes must be canonical")
        return values

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(set(values))):
            raise ValueError("eligibility reasons must be canonical")
        return values

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("eligibility query hash mismatch")
        if self.context_hash != self.query.input_context_hash:
            raise ValueError("eligibility context hash mismatch")
        if self.classification == "eligible" and (
            not self.segments or not self.structural_resolution_hashes
        ):
            raise ValueError("eligible result requires replayed interval evidence")
        return self


class ObservationAssessmentV1(FrozenModel):
    """All independent source, session, lifecycle, and admission axes."""

    schema_version: Literal["1"] = "1"
    kind: Literal["assessment"] = "assessment"
    query: ObservationQueryV1
    query_hash: SHA256Hash
    scheduled_day: ScheduledDayStatus
    realized_outcome: RealizedOutcomeStatus
    lifecycle: ObservationLifecycleStatus
    coverage: ObservationCoverageStatus
    record_presence: PresenceStatus
    required_fields: RequiredFieldsStatus
    qualifying_price_activity: ActivityStatus
    any_reported_activity: ActivityStatus
    integrity: Literal["verified"] = "verified"
    cutoff_availability: CutoffAvailabilityStatus
    source_basis: Literal[
        "unadjusted",
        "split_adjusted",
        "dividend_adjusted",
        "total_return_like",
        "mixed",
        "unknown",
    ]
    profile_compatibility: ProfileCompatibilityStatus
    provider_gap: ProviderGapStatus
    usability: UsabilityStatus
    eligibility: ListingSessionEligibilityResultV1
    numeric_view: ObservationNumericViewV1 | None
    observation_selection_proof_hash: SHA256Hash
    coverage_selection_proof_hash: SHA256Hash
    realized_selection_proof_hash: SHA256Hash
    session_binding_hash: SHA256Hash
    contributing_proof_hashes: tuple[SHA256Hash, ...]
    reasons: tuple[NonBlankStr, ...]
    context_hash: SHA256Hash
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash

    @field_validator("contributing_proof_hashes")
    @classmethod
    def canonicalize_proofs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(set(values))):
            raise ValueError("assessment proof hashes must be canonical")
        return values

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(set(values))):
            raise ValueError("assessment reasons must be canonical")
        return values

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("assessment query hash mismatch")
        if self.context_hash != self.query.input_context_hash:
            raise ValueError("assessment context hash mismatch")
        if self.eligibility.query != self.query:
            raise ValueError("assessment eligibility query mismatch")
        if self.usability == "usable" and (
            self.numeric_view is None
            or self.record_presence != "present"
            or self.required_fields != "complete"
            or self.profile_compatibility != "compatible"
        ):
            raise ValueError("usable assessment requires an admitted numeric view")
        if self.usability != "usable" and self.numeric_view is not None:
            raise ValueError("nonusable assessment cannot expose a numeric view")
        return self


class ObservationReadFailureV1(FrozenModel):
    """Typed exact-byte read failure without parsed source conclusions."""

    schema_version: Literal["1"] = "1"
    kind: Literal["read_failure"] = "read_failure"
    query: ObservationQueryV1
    query_hash: SHA256Hash
    requested_artifact_hash: SHA256Hash
    integrity: Literal["corrupt", "unavailable"]
    error_code: Literal["artifact_integrity_error", "observation_artifact_unavailable"]
    scheduled_day: Literal["unknown"] = "unknown"
    realized_outcome: Literal["unknown"] = "unknown"
    lifecycle: Literal["indeterminate"] = "indeterminate"
    coverage: Literal["unknown"] = "unknown"
    record_presence: Literal["unknown"] = "unknown"
    required_fields: Literal["unknown"] = "unknown"
    qualifying_price_activity: Literal["unknown"] = "unknown"
    any_reported_activity: Literal["unknown"] = "unknown"
    cutoff_availability: Literal["indeterminate"] = "indeterminate"
    source_basis: Literal["unknown"] = "unknown"
    profile_compatibility: Literal["indeterminate"] = "indeterminate"
    provider_gap: Literal["not_proven"] = "not_proven"
    usability: Literal["unusable", "indeterminate"]
    numeric_view: None = None
    context_hash: SHA256Hash
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("read failure query hash mismatch")
        if self.context_hash != self.query.input_context_hash:
            raise ValueError("read failure context hash mismatch")
        expected = "unusable" if self.integrity == "corrupt" else "indeterminate"
        if self.usability != expected:
            raise ValueError("read failure usability must follow integrity status")
        return self


ObservationAssessmentResultV1 = Annotated[
    ObservationAssessmentV1 | ObservationReadFailureV1,
    Field(discriminator="kind"),
]


def observation_interval_boundaries(
    segments: tuple[ListingEligibilitySegmentV1, ...],
) -> tuple[datetime, ...]:
    """Return the retained interval sweep boundaries for audit display."""
    if not segments:
        return ()
    return (segments[0].opened_at, *(item.closed_at for item in segments))
