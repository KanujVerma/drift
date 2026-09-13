"""Immutable M1e qualification profiles, results, and lifecycle contracts."""

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.serialization.canonical import content_hash


class ConsumerPurpose(StrEnum):
    """The exact downstream claim evaluated by one qualification profile."""

    HISTORICAL_DECISION_INPUT = "historical_decision_input"
    RETROSPECTIVE_AUDIT = "retrospective_audit"


class QualificationStatus(StrEnum):
    """Evidence result for one qualification dimension and purpose."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"


class ExecutionReachability(StrEnum):
    """Whether qualification execution reached a dimension."""

    REACHED = "reached"
    NOT_REACHED = "not_reached"


class AcquisitionState(StrEnum):
    """The exact source-byte state bound by a qualification target."""

    NOT_ACQUIRED = "not_acquired"
    ACQUIRED_UNSNAPSHOTTED = "acquired_unsnapshotted"
    SNAPSHOT_BOUND = "snapshot_bound"


class PilotStage(StrEnum):
    """A purpose-specific stage in the M1e pilot lifecycle."""

    PROFILE_FROZEN = "profile_frozen"
    RIGHTS_ASSESSED = "rights_assessed"
    ACQUISITION_AUTHORIZED = "acquisition_authorized"
    ACQUIRED = "acquired"
    SNAPSHOT_FROZEN = "snapshot_frozen"
    QUALIFIED = "qualified"
    REPLAY_AUTHORIZED = "replay_authorized"
    REPLAYED = "replayed"
    COMPLETED_POSITIVE = "completed_positive"
    COMPLETED_NEGATIVE = "completed_negative"


class QualificationDimension(StrEnum):
    """One independent M1e qualification dimension."""

    SECURITY_LISTING_IDENTITY = "security_listing_identity"
    UNIVERSE_LIFECYCLE = "universe_lifecycle"
    CORPORATE_ACTION_TERMS = "corporate_action_terms"
    OCCURRED_EFFECTS = "occurred_effects"
    SETTLEMENTS_TERMINAL_OUTCOMES = "settlements_terminal_outcomes"
    OBSERVATIONS_METHODOLOGIES = "observations_methodologies"
    SCHEDULED_REALIZED_SESSIONS = "scheduled_realized_sessions"
    REVISIONS_POINT_IN_TIME = "revisions_point_in_time"
    COVERAGE_OMISSION = "coverage_omission"
    LICENSING_RETENTION = "licensing_retention"
    ACQUISITION_SNAPSHOT = "acquisition_snapshot"
    OFFLINE_REPLAY = "offline_replay"


class ExternalDependencyStatus(StrEnum):
    """Resolution state for evidence controlled outside Drift."""

    PENDING = "pending"
    SATISFIED = "satisfied"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    INQUIRY_EXHAUSTED = "inquiry_exhausted"
    UNAVAILABLE = "unavailable"


class PreProfileAttemptStatus(StrEnum):
    """Only terminal outcome for discovery that ends before profile freeze."""

    ABANDONED_PRE_PROFILE = "abandoned_pre_profile"


class ContentDispositionStatus(StrEnum):
    """Observed state of one content object and its declared backup copies."""

    RETAINED = "retained"
    DELETED = "deleted"
    CERTIFIED_DELETED = "certified_deleted"
    PENDING = "pending"


class ContentDispositionDuty(StrEnum):
    """Contractual disposition duty for one exact content object."""

    NONE = "none"
    RETAIN = "retain"
    DELETE = "delete"
    CERTIFY_DELETE = "certify_delete"


class M1eCompletionKind(StrEnum):
    """Pilot completion kind without any provider-wide generalization."""

    COMPLETED_POSITIVE = "completed_positive"
    COMPLETED_NEGATIVE = "completed_negative"


_PRE_REPLAY_DIMENSIONS = tuple(QualificationDimension)[:-1]
_ALL_DIMENSIONS = tuple(QualificationDimension)
_TASK2_PERSISTED_STAGES = {None, PilotStage.PROFILE_FROZEN}


def _sorted_unique_strings(
    values: tuple[str, ...], *, label: str, nonempty: bool = False
) -> tuple[str, ...]:
    if (nonempty and not values) or len(values) != len(set(values)):
        qualifier = "nonempty and " if nonempty else ""
        raise ValueError(f"{label} must be {qualifier}unique")
    return tuple(sorted(values))


def _second_anniversary(value: date) -> date:
    try:
        return value.replace(year=value.year + 2)
    except ValueError:
        return value.replace(year=value.year + 2, day=28)


class ProviderProductScopeV1(FrozenModel):
    """Exact provider, product, publisher, field, and documentation scope."""

    schema_version: Literal["1"] = "1"
    provider_legal_name: NonBlankStr
    provider_legal_id: NonBlankStr
    product_id: NonBlankStr
    dataset_ids: tuple[NonBlankStr, ...]
    publisher_ids: tuple[NonBlankStr, ...]
    declared_fields: tuple[NonBlankStr, ...]
    methodology_reference_hashes: tuple[SHA256Hash, ...]
    schema_reference_hashes: tuple[SHA256Hash, ...]

    @field_validator(
        "dataset_ids",
        "publisher_ids",
        "declared_fields",
        "methodology_reference_hashes",
        "schema_reference_hashes",
    )
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(
            values, label="provider product scope collections", nonempty=True
        )


class SubscriberUseScopeV1(FrozenModel):
    """Exact subscribing entity, user, requested uses, and classification."""

    schema_version: Literal["1"] = "1"
    subscriber_legal_entity: NonBlankStr
    authorized_user_id: NonBlankStr
    model_development_requested: bool
    trading_support_requested: bool
    provider_classification_label: NonBlankStr | None
    classification_unresolved: bool
    classification_evidence_hashes: tuple[SHA256Hash, ...]

    @field_validator("classification_evidence_hashes")
    @classmethod
    def canonicalize_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="classification evidence hashes")

    @model_validator(mode="after")
    def validate_classification(self) -> Self:
        if not (self.model_development_requested or self.trading_support_requested):
            raise ValueError("subscriber scope requires at least one requested use")
        if self.classification_unresolved == (
            self.provider_classification_label is not None
        ):
            raise ValueError(
                "provider classification requires a label or unresolved state"
            )
        if (
            not self.classification_unresolved
            and not self.classification_evidence_hashes
        ):
            raise ValueError("resolved provider classification requires evidence")
        return self


class InfrastructureScopeV1(FrozenModel):
    """Declared people, machine, services, storage policy, and backup scope."""

    schema_version: Literal["1"] = "1"
    machine_identity: NonBlankStr
    user_ids: tuple[NonBlankStr, ...]
    contractor_ids: tuple[NonBlankStr, ...]
    shared_account: bool
    real_data_ci: bool
    cloud_processing: bool
    service_provider_ids: tuple[NonBlankStr, ...]
    private_store_policy_hash: SHA256Hash
    backup_location_ids: tuple[NonBlankStr, ...]

    @field_validator(
        "user_ids", "contractor_ids", "service_provider_ids", "backup_location_ids"
    )
    @classmethod
    def canonicalize_identifiers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="infrastructure identifiers")

    @model_validator(mode="after")
    def require_one_user(self) -> Self:
        if len(self.user_ids) != 1:
            raise ValueError("M1e infrastructure scope requires exactly one user")
        return self


class QualificationDataScopeV1(FrozenModel):
    """Bounded US daily-equity source and golden-event selection."""

    schema_version: Literal["1"] = "1"
    market: Literal["US"] = "US"
    frequency: Literal["daily_equity"] = "daily_equity"
    security_ids: tuple[NonBlankStr, ...]
    universe_ids: tuple[NonBlankStr, ...]
    start_date: date
    end_date: date
    requested_fields: tuple[NonBlankStr, ...]
    revision_cutoff: UTCDateTime
    event_window_ids: tuple[NonBlankStr, ...]
    sessions_before_event: int = Field(ge=0, le=20)
    sessions_after_event: int = Field(ge=0, le=20)

    @field_validator(
        "security_ids", "universe_ids", "requested_fields", "event_window_ids"
    )
    @classmethod
    def canonicalize_selections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="qualification data selections")

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if not self.security_ids or len(self.security_ids) > 100:
            raise ValueError("qualification scope requires 1 through 100 securities")
        if not self.universe_ids:
            raise ValueError("qualification scope requires explicit universe selection")
        if not self.requested_fields:
            raise ValueError("qualification scope requires requested fields")
        if self.start_date > self.end_date:
            raise ValueError("qualification date interval cannot be reversed")
        if self.end_date >= _second_anniversary(self.start_date):
            raise ValueError("qualification date interval exceeds two continuous years")
        if len(self.event_window_ids) > 20:
            raise ValueError("qualification scope exceeds 20 event windows")
        return self


class QualificationProfileV1(FrozenModel):
    """Snapshot-free immutable qualification identity for one purpose."""

    schema_version: Literal["1"] = "1"
    profile_id: UUID7
    profile_version: NonBlankStr
    provider: ProviderProductScopeV1
    subscriber: SubscriberUseScopeV1
    infrastructure: InfrastructureScopeV1
    data: QualificationDataScopeV1
    purpose: ConsumerPurpose
    critical_dimensions: tuple[QualificationDimension, ...]
    required_golden_case_ids: tuple[NonBlankStr, ...]
    golden_case_instance_manifest_hash: SHA256Hash
    adjudication_policy_hash: SHA256Hash

    @field_validator("critical_dimensions")
    @classmethod
    def canonicalize_dimensions(
        cls, values: tuple[QualificationDimension, ...]
    ) -> tuple[QualificationDimension, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("critical dimensions must be nonempty and unique")
        return tuple(sorted(values, key=_ALL_DIMENSIONS.index))

    @field_validator("required_golden_case_ids")
    @classmethod
    def canonicalize_cases(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(
            values, label="required golden case IDs", nonempty=True
        )

    @model_validator(mode="after")
    def validate_user_scope(self) -> Self:
        if self.infrastructure.user_ids != (self.subscriber.authorized_user_id,):
            raise ValueError("subscriber user must match the infrastructure user scope")
        return self


def qualification_profile_hash(profile: QualificationProfileV1) -> SHA256Hash:
    """Return the exact canonical identity of one snapshot-free profile."""

    return content_hash(profile)


class PilotProfileSetV1(FrozenModel):
    """Exactly two otherwise aligned profiles, one for each consumer purpose."""

    schema_version: Literal["1"] = "1"
    pilot_id: UUID7
    pilot_version: NonBlankStr
    profiles: tuple[QualificationProfileV1, QualificationProfileV1]

    @model_validator(mode="after")
    def validate_profiles(self) -> Self:
        if len(self.profiles) != 2:
            raise ValueError("pilot profile set requires exactly two profiles")
        by_purpose = {item.purpose: item for item in self.profiles}
        if set(by_purpose) != set(ConsumerPurpose) or len(by_purpose) != 2:
            raise ValueError(
                "pilot profile set requires exactly one profile per purpose"
            )
        if len({item.profile_id for item in self.profiles}) != 2:
            raise ValueError("purpose profiles require distinct profile IDs")
        ordered = tuple(by_purpose[purpose] for purpose in ConsumerPurpose)
        baseline = ordered[0]
        for candidate in ordered[1:]:
            if (
                candidate.provider != baseline.provider
                or candidate.subscriber != baseline.subscriber
                or candidate.infrastructure != baseline.infrastructure
                or candidate.data != baseline.data
                or candidate.adjudication_policy_hash
                != baseline.adjudication_policy_hash
                or candidate.required_golden_case_ids
                != baseline.required_golden_case_ids
                or candidate.golden_case_instance_manifest_hash
                != baseline.golden_case_instance_manifest_hash
            ):
                raise ValueError("purpose profiles must have matching frozen scopes")
        object.__setattr__(self, "profiles", ordered)
        return self


class QualificationTargetV1(FrozenModel):
    """One profile bound to its truthful source-byte acquisition state."""

    schema_version: Literal["1"] = "1"
    profile_hash: SHA256Hash
    acquisition_state: AcquisitionState
    receipt_hashes: tuple[SHA256Hash, ...]
    snapshot_hash: SHA256Hash | None
    failure_evidence_hashes: tuple[SHA256Hash, ...]

    @field_validator("receipt_hashes", "failure_evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="qualification target hashes")

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.acquisition_state is AcquisitionState.NOT_ACQUIRED:
            if self.receipt_hashes or self.snapshot_hash is not None:
                raise ValueError(
                    "not-acquired target cannot carry receipts or snapshot"
                )
        elif self.acquisition_state is AcquisitionState.ACQUIRED_UNSNAPSHOTTED:
            if (
                not self.receipt_hashes
                or self.snapshot_hash is not None
                or not self.failure_evidence_hashes
            ):
                raise ValueError(
                    "acquired-unsnapshotted target requires receipts and blocker only"
                )
        elif not self.receipt_hashes or self.snapshot_hash is None:
            raise ValueError("snapshot-bound target requires receipts and snapshot")
        return self


class DimensionQualificationResultV1(FrozenModel):
    """One purpose-scoped result with independent execution reachability."""

    schema_version: Literal["1"] = "1"
    dimension: QualificationDimension
    purpose: ConsumerPurpose
    status: QualificationStatus
    reachability: ExecutionReachability
    evidence_hashes: tuple[SHA256Hash, ...]
    tested_golden_case_ids: tuple[NonBlankStr, ...]
    admitted_purpose: bool
    limitations: tuple[NonBlankStr, ...]
    adjudication_policy_hash: SHA256Hash

    @field_validator("evidence_hashes", "tested_golden_case_ids", "limitations")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="dimension result collections")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.reachability is ExecutionReachability.NOT_REACHED:
            if (
                self.status is not QualificationStatus.UNKNOWN
                or self.evidence_hashes
                or self.tested_golden_case_ids
                or self.admitted_purpose
                or not self.limitations
            ):
                raise ValueError(
                    "not-reached result must be unknown, unsupported, and limited"
                )
            return self
        if not self.evidence_hashes:
            raise ValueError("reached qualification result requires evidence")
        if self.status is QualificationStatus.PASS and not self.admitted_purpose:
            raise ValueError("a passing reached result must admit its purpose")
        if (
            self.status in {QualificationStatus.FAIL, QualificationStatus.UNKNOWN}
            and self.admitted_purpose
        ):
            raise ValueError("failed or unknown result cannot admit its purpose")
        if self.status is not QualificationStatus.PASS and not self.limitations:
            raise ValueError("non-passing reached result requires limitations")
        return self


def _canonicalize_results(
    values: tuple[DimensionQualificationResultV1, ...],
) -> tuple[DimensionQualificationResultV1, ...]:
    dimensions = tuple(item.dimension for item in values)
    if len(dimensions) != len(set(dimensions)):
        raise ValueError("qualification report dimensions must be unique")
    return tuple(sorted(values, key=lambda item: _ALL_DIMENSIONS.index(item.dimension)))


class PreReplayQualificationReportV1(FrozenModel):
    """The eleven non-replay results admitted as immutable replay input."""

    schema_version: Literal["1"] = "1"
    purpose: ConsumerPurpose
    target: QualificationTargetV1
    results: tuple[DimensionQualificationResultV1, ...]

    @field_validator("results")
    @classmethod
    def canonicalize_results(
        cls, values: tuple[DimensionQualificationResultV1, ...]
    ) -> tuple[DimensionQualificationResultV1, ...]:
        return _canonicalize_results(values)

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.target.acquisition_state is not AcquisitionState.SNAPSHOT_BOUND:
            raise ValueError("pre-replay report requires a snapshot-bound target")
        if tuple(item.dimension for item in self.results) != _PRE_REPLAY_DIMENSIONS:
            raise ValueError("pre-replay report requires exactly 11 non-replay results")
        if any(item.purpose is not self.purpose for item in self.results):
            raise ValueError("pre-replay results cannot cross consumer purposes")
        if any(
            item.reachability is not ExecutionReachability.REACHED
            for item in self.results
        ):
            raise ValueError("pre-replay report requires 11 reached dimensions")
        if len({item.adjudication_policy_hash for item in self.results}) != 1:
            raise ValueError("pre-replay results require one adjudication policy")
        return self


class PurposeQualificationReportV1(FrozenModel):
    """Final twelve-dimension report for one exact target and purpose."""

    schema_version: Literal["1"] = "1"
    report_id: UUID7
    report_version: NonBlankStr
    reported_at: UTCDateTime
    purpose: ConsumerPurpose
    target: QualificationTargetV1
    results: tuple[DimensionQualificationResultV1, ...]
    pre_replay_report_hash: SHA256Hash | None

    @field_validator("results")
    @classmethod
    def canonicalize_results(
        cls, values: tuple[DimensionQualificationResultV1, ...]
    ) -> tuple[DimensionQualificationResultV1, ...]:
        return _canonicalize_results(values)

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if tuple(item.dimension for item in self.results) != _ALL_DIMENSIONS:
            raise ValueError("final purpose report requires exactly all 12 dimensions")
        if any(item.purpose is not self.purpose for item in self.results):
            raise ValueError(
                "final qualification results cannot cross consumer purposes"
            )
        if len({item.adjudication_policy_hash for item in self.results}) != 1:
            raise ValueError("final qualification results require one policy")
        replay = self.results[-1]
        replay_reached = replay.reachability is ExecutionReachability.REACHED
        if replay_reached != (self.pre_replay_report_hash is not None):
            raise ValueError(
                "reached replay requires exactly one pre-replay report hash"
            )
        if (
            replay_reached
            and self.target.acquisition_state is not AcquisitionState.SNAPSHOT_BOUND
        ):
            raise ValueError("reached replay requires a snapshot-bound target")
        if replay_reached and any(
            item.reachability is not ExecutionReachability.REACHED
            for item in self.results[:-1]
        ):
            raise ValueError("reached replay requires all prior dimensions reached")
        return self


class ExternalDependencyResolutionV1(FrozenModel):
    """Evidence-backed resolution of one external dependency."""

    schema_version: Literal["1"] = "1"
    dependency_kind: NonBlankStr
    responsible_party: NonBlankStr
    status: ExternalDependencyStatus
    evidence_hashes: tuple[SHA256Hash, ...]
    decision_time: UTCDateTime | None
    limitations: tuple[NonBlankStr, ...]

    @field_validator("evidence_hashes", "limitations")
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="external dependency collections")

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.status is ExternalDependencyStatus.PENDING:
            if self.decision_time is not None:
                raise ValueError("pending external dependency has no decision time")
        elif not self.evidence_hashes or self.decision_time is None:
            raise ValueError("resolved external dependency requires evidence and time")
        if not self.limitations:
            raise ValueError("external dependency resolution requires limitations")
        return self


class PreProfileAttemptRecordV1(FrozenModel):
    """Terminal candidate-discovery record that is not M1e completion."""

    schema_version: Literal["1"] = "1"
    attempt_id: UUID7
    attempt_version: NonBlankStr
    attempted_candidate_ids: tuple[NonBlankStr, ...]
    external_dependencies: tuple[ExternalDependencyResolutionV1, ...]
    reasons: tuple[NonBlankStr, ...]
    outcome: Literal[PreProfileAttemptStatus.ABANDONED_PRE_PROFILE] = (
        PreProfileAttemptStatus.ABANDONED_PRE_PROFILE
    )

    @field_validator("attempted_candidate_ids", "reasons")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(
            values, label="pre-profile attempt collections", nonempty=True
        )

    @field_validator("external_dependencies")
    @classmethod
    def canonicalize_dependencies(
        cls, values: tuple[ExternalDependencyResolutionV1, ...]
    ) -> tuple[ExternalDependencyResolutionV1, ...]:
        if not values:
            raise ValueError("pre-profile abandonment requires external evidence")
        hashes = tuple(content_hash(item) for item in values)
        if len(hashes) != len(set(hashes)):
            raise ValueError("pre-profile external dependencies must be unique")
        return tuple(item for _, item in sorted(zip(hashes, values, strict=True)))

    @model_validator(mode="after")
    def require_terminal_blocker(self) -> Self:
        blockers = {
            ExternalDependencyStatus.DECLINED,
            ExternalDependencyStatus.WITHDRAWN,
            ExternalDependencyStatus.INQUIRY_EXHAUSTED,
            ExternalDependencyStatus.UNAVAILABLE,
        }
        if any(item.status not in blockers for item in self.external_dependencies):
            raise ValueError(
                "pre-profile abandonment requires terminal blocking evidence"
            )
        return self


class ContentDispositionRecordV1(FrozenModel):
    """Contractual disposition of one exact content object and backup set."""

    schema_version: Literal["1"] = "1"
    content_hash: SHA256Hash
    backup_hashes: tuple[SHA256Hash, ...]
    contractual_duty: ContentDispositionDuty
    status: ContentDispositionStatus
    evidence_hashes: tuple[SHA256Hash, ...]
    disposition_time: UTCDateTime | None

    @field_validator("backup_hashes", "evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="content disposition hashes")

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.status is ContentDispositionStatus.PENDING:
            if self.disposition_time is not None:
                raise ValueError("pending disposition has no disposition time")
            return self
        if not self.evidence_hashes or self.disposition_time is None:
            raise ValueError("completed disposition requires evidence and time")
        allowed = {
            ContentDispositionDuty.NONE: set(ContentDispositionStatus)
            - {ContentDispositionStatus.PENDING},
            ContentDispositionDuty.RETAIN: {ContentDispositionStatus.RETAINED},
            ContentDispositionDuty.DELETE: {
                ContentDispositionStatus.DELETED,
                ContentDispositionStatus.CERTIFIED_DELETED,
            },
            ContentDispositionDuty.CERTIFY_DELETE: {
                ContentDispositionStatus.CERTIFIED_DELETED
            },
        }
        if self.status not in allowed[self.contractual_duty]:
            raise ValueError("content disposition does not satisfy contractual duty")
        return self


class PurposeStageStateV1(FrozenModel):
    """Ordered stage and evidence history for one purpose profile."""

    schema_version: Literal["1"] = "1"
    purpose: ConsumerPurpose
    profile_hash: SHA256Hash
    stage: PilotStage | None
    reached_stage_artifact_hashes: tuple[SHA256Hash, ...]
    terminal_blocker: QualificationDimension | None

    @model_validator(mode="after")
    def validate_stage(self) -> Self:
        if self.stage not in _TASK2_PERSISTED_STAGES:
            raise ValueError("later purpose stage requires its typed verifier")
        if self.stage is None:
            if self.reached_stage_artifact_hashes or self.terminal_blocker is not None:
                raise ValueError("initial purpose state cannot carry reached evidence")
        elif not self.reached_stage_artifact_hashes:
            raise ValueError("reached purpose stage requires artifact evidence")
        if self.terminal_blocker is not None:
            raise ValueError("Task 2 cannot bind a terminal blocker")
        return self


class M1ePilotStateV1(FrozenModel):
    """The two purpose-specific state lanes for one frozen profile-set identity."""

    schema_version: Literal["1"] = "1"
    profile_set_hash: SHA256Hash
    purpose_states: tuple[PurposeStageStateV1, PurposeStageStateV1]
    shared_artifact_hashes: tuple[SHA256Hash, ...]

    @field_validator("shared_artifact_hashes")
    @classmethod
    def canonicalize_shared_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="shared artifact hashes")

    @model_validator(mode="after")
    def validate_purposes(self) -> Self:
        if len(self.purpose_states) != 2:
            raise ValueError("M1e pilot state requires exactly two purpose states")
        by_purpose = {item.purpose: item for item in self.purpose_states}
        if set(by_purpose) != set(ConsumerPurpose) or len(by_purpose) != 2:
            raise ValueError("M1e pilot state requires one state per purpose")
        if len({item.profile_hash for item in self.purpose_states}) != 2:
            raise ValueError("M1e purpose states require distinct profile hashes")
        if any(
            item.stage not in _TASK2_PERSISTED_STAGES for item in self.purpose_states
        ):
            raise ValueError("pilot state contains a stage without a typed verifier")
        object.__setattr__(
            self,
            "purpose_states",
            tuple(by_purpose[purpose] for purpose in ConsumerPurpose),
        )
        return self


class M1eTransitionV1(FrozenModel):
    """Verified Task 2 start of one exact purpose profile."""

    schema_version: Literal["1"] = "1"
    transition_id: UUID7
    profile_set: PilotProfileSetV1
    profile: QualificationProfileV1
    from_stage: Literal[None] = None
    to_stage: Literal[PilotStage.PROFILE_FROZEN] = PilotStage.PROFILE_FROZEN

    @model_validator(mode="after")
    def validate_exact_profile(self) -> Self:
        matches = tuple(
            item
            for item in self.profile_set.profiles
            if item.purpose is self.profile.purpose
        )
        if len(matches) != 1 or matches[0] != self.profile:
            raise ValueError("profile freeze requires the exact purpose profile")
        return self


class M1eCompletionRecordV1(FrozenModel):
    """Persisted terminal pilot record, constructed only by the later finalizer."""

    schema_version: Literal["1"] = "1"
    completion_id: UUID7
    completion_version: NonBlankStr
    completed_at: UTCDateTime
    profile_set_hash: SHA256Hash
    purpose_states: tuple[PurposeStageStateV1, PurposeStageStateV1]
    shared_artifact_hashes: tuple[SHA256Hash, ...]
    blocking_dimensions: tuple[QualificationDimension, ...]
    blocking_evidence_hashes: tuple[SHA256Hash, ...]
    purpose_reports: tuple[PurposeQualificationReportV1, PurposeQualificationReportV1]
    content_dispositions: tuple[ContentDispositionRecordV1, ...]
    external_dependencies: tuple[ExternalDependencyResolutionV1, ...]
    completion_kind: M1eCompletionKind

    @field_validator("shared_artifact_hashes", "blocking_evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="completion hashes")

    @field_validator("blocking_dimensions")
    @classmethod
    def canonicalize_blockers(
        cls, values: tuple[QualificationDimension, ...]
    ) -> tuple[QualificationDimension, ...]:
        if len(values) != len(set(values)):
            raise ValueError("blocking dimensions must be unique")
        return tuple(sorted(values, key=_ALL_DIMENSIONS.index))

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        raise ValueError("M1e completion requires the Task 7 typed finalizer")


def build_negative_report(
    target: QualificationTargetV1,
    reached_results: tuple[DimensionQualificationResultV1, ...],
    blocker_dimension: QualificationDimension,
    *,
    report_id: UUID7,
    reported_at: UTCDateTime,
) -> PurposeQualificationReportV1:
    """Build a truthful final report without inventing unreached artifacts."""

    if not reached_results:
        raise ValueError("negative report requires at least one reached result")
    dimensions = tuple(item.dimension for item in reached_results)
    if len(dimensions) != len(set(dimensions)):
        raise ValueError("negative report reached dimensions must be unique")
    if any(
        item.reachability is not ExecutionReachability.REACHED
        for item in reached_results
    ):
        raise ValueError("negative report inputs must be genuinely reached")
    purposes = {item.purpose for item in reached_results}
    policies = {item.adjudication_policy_hash for item in reached_results}
    if len(purposes) != 1 or len(policies) != 1:
        raise ValueError("negative report cannot mix purposes or policies")
    by_dimension = {item.dimension: item for item in reached_results}
    blocker = by_dimension.get(blocker_dimension)
    if (
        blocker is None
        or blocker.status is QualificationStatus.PASS
        or blocker.admitted_purpose
    ):
        raise ValueError("negative report requires a reached non-passing blocker")
    purpose = next(iter(purposes))
    policy_hash = next(iter(policies))
    results = tuple(
        by_dimension.get(dimension)
        or DimensionQualificationResultV1(
            dimension=dimension,
            purpose=purpose,
            status=QualificationStatus.UNKNOWN,
            reachability=ExecutionReachability.NOT_REACHED,
            evidence_hashes=(),
            tested_golden_case_ids=(),
            admitted_purpose=False,
            limitations=(f"not reached after {blocker_dimension.value} blocker",),
            adjudication_policy_hash=policy_hash,
        )
        for dimension in QualificationDimension
    )
    return PurposeQualificationReportV1(
        report_id=report_id,
        report_version="1",
        reported_at=reported_at,
        purpose=purpose,
        target=target,
        results=results,
        pre_replay_report_hash=None,
    )
