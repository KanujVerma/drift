"""Immutable source and derived M1d session contracts."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.datasets.hashing import assertion_version_payload
from drift.domain.assertions import (
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.observation_query import (
    M1dSelectionProofV1,
    M1dSelectionPurpose,
    ObservationQueryV1,
    SessionSubjectV1,
)
from drift.serialization.canonical import content_hash

_SESSION_ENCODING_CONTRACT_V1 = {
    "schema_version": "1",
    "contract_id": "drift-m1d-session-canonical-encoding-v1",
    "methods": (
        "historical_timezone_methodology",
        "historical_boundary_offset",
        "session_output",
        "generated_session_row",
    ),
}
_SCHEDULE_GENERATION_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "explicit_local_rows_to_utc_v1",
    "source_selection": "finite_m1a_revision_selection",
    "authority": "row_bound_explicit_offsets",
    "reconstruction": "exact_tzif_bytes",
    "output_identity": "semantic_session_output_bytes",
}


def canonical_session_encoding_contract_hash() -> str:
    """Return the recognized immutable M1d v1 encoding-schema identity."""
    return content_hash(_SESSION_ENCODING_CONTRACT_V1)


def schedule_generation_algorithm_hash() -> str:
    """Return the semantic identity of the only supported generator."""
    return content_hash(_SCHEDULE_GENERATION_ALGORITHM_V1)


class SessionKeyV1(FrozenModel):
    """One exact venue, regular-session scope, and local date."""

    schema_version: Literal["1"] = "1"
    mic: NonBlankStr
    session_scope: Literal["regular"]
    local_date: date

    @field_validator("mic")
    @classmethod
    def require_mic_shape(cls, value: str) -> str:
        if len(value) != 4 or value != value.upper():
            raise ValueError("MIC must be an exact four-character uppercase code")
        return value


class HistoricalBoundaryOffsetV1(FrozenModel):
    """One source-asserted historical UTC offset for a local boundary."""

    schema_version: Literal["1"] = "1"
    boundary: Literal["open", "close"]
    utc_offset_seconds: int | None
    methodology_encoding_hash: SHA256Hash | None
    authority_artifact_hash: SHA256Hash | None
    authority_availability_evidence_hash: SHA256Hash | None


class HistoricalTimezoneMethodologyV1(FrozenModel):
    """Canonical interpretation of retained source methodology bytes."""

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    methodology_id: NonBlankStr
    methodology_version: NonBlankStr
    source_timezone_label: NonBlankStr
    timezone_identifier: NonBlankStr
    interpretation: Literal["explicit_boundary_offsets_v1"]
    source_methodology_artifact_hash: SHA256Hash
    source_methodology_availability_evidence_hash: SHA256Hash
    canonical_encoding_contract_hash: SHA256Hash

    @field_validator("canonical_encoding_contract_hash")
    @classmethod
    def require_recognized_encoding_contract(cls, value: str) -> str:
        if value != canonical_session_encoding_contract_hash():
            raise ValueError("methodology requires recognized v1 encoding contract")
        return value


class ScheduledSessionVersionV1(FrozenModel):
    """One retained source version of an explicit daily schedule row."""

    schema_version: Literal["1"] = "1"
    revision: RevisionEnvelopeV1
    source_id: NonBlankStr
    session_key: SessionKeyV1
    source_temporal_evidence: TemporalBoundaryClaimV1
    state: Literal["regular", "early_close", "closed", "unknown"]
    local_open: NonBlankStr | None
    local_close: NonBlankStr | None
    timezone_identifier: NonBlankStr
    open_fold: Literal[0, 1] | None
    close_fold: Literal[0, 1] | None
    historical_boundary_offsets: tuple[HistoricalBoundaryOffsetV1, ...]
    source_methodology_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_state_shape(self) -> Self:
        is_open = self.state in {"regular", "early_close"}
        boundaries = (self.local_open, self.local_close)
        folds = (self.open_fold, self.close_fold)
        if is_open and any(value is None for value in boundaries):
            raise ValueError("open session requires local boundaries")
        if is_open:
            names = tuple(item.boundary for item in self.historical_boundary_offsets)
            if len(names) != 2 or set(names) != {"open", "close"}:
                raise ValueError("open session requires one offset for each boundary")
            for label in boundaries:
                assert label is not None
                try:
                    parsed = date.fromisoformat(label[:10])
                except ValueError as error:
                    raise ValueError(
                        "local boundary must use an ISO local label"
                    ) from error
                if parsed != self.session_key.local_date:
                    raise ValueError("local boundary date must match session key")
        elif any(value is not None for value in (*boundaries, *folds)):
            raise ValueError("closed or unknown session cannot invent boundaries")
        elif self.historical_boundary_offsets:
            raise ValueError("closed or unknown session cannot claim boundary offsets")
        return self

    @model_validator(mode="after")
    def validate_payload_hash(self) -> Self:
        if self.revision.payload_hash != content_hash(assertion_version_payload(self)):
            raise ValueError("schedule payload hash mismatch")
        return self


class RealizedSessionVersionV1(FrozenModel):
    """One independently sourced realized venue-session report."""

    schema_version: Literal["1"] = "1"
    revision: RevisionEnvelopeV1
    source_id: NonBlankStr
    session_key: SessionKeyV1
    outcome: Literal["opened", "did_not_open", "unknown"]
    actual_open: UTCDateTime | None
    actual_close: UTCDateTime | None
    reported_as_scheduled: Literal["asserted", "denied", "unknown"]
    late_open: Literal["asserted", "denied", "unknown"]
    early_close: Literal["asserted", "denied", "unknown"]
    interruption_intervals: tuple[TemporalIntervalClaimV1, ...]
    interruption_coverage: Literal["complete", "partial", "unknown"]
    source_evidence_hashes: tuple[SHA256Hash, ...]
    methodology_hashes: tuple[SHA256Hash, ...]
    compared_schedule_hash: SHA256Hash | None

    @field_validator("source_evidence_hashes", "methodology_hashes")
    @classmethod
    def canonicalize_support_hashes(
        cls, values: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if not values or len(set(values)) != len(values):
            raise ValueError("realized support hashes must be nonempty and unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> Self:
        if self.outcome != "opened" and (
            self.actual_open is not None or self.actual_close is not None
        ):
            raise ValueError("closed or unknown outcome cannot carry actual bounds")
        if (self.actual_open is None) != (self.actual_close is None):
            raise ValueError("exact realized interval requires both actual bounds")
        if (
            self.actual_open is not None
            and self.actual_close is not None
            and self.actual_close < self.actual_open
        ):
            raise ValueError("actual close cannot precede actual open")
        return self

    @model_validator(mode="after")
    def validate_payload_hash(self) -> Self:
        if self.revision.payload_hash != content_hash(assertion_version_payload(self)):
            raise ValueError("realized session payload hash mismatch")
        return self


class SessionInventoryEntryV1(FrozenModel):
    """Exact source session assertion/version/hash retained by coverage."""

    schema_version: Literal["1"] = "1"
    assertion_id: UUID7
    version_id: UUID7
    record_hash: SHA256Hash


class SessionCoverageVersionV1(FrozenModel):
    """One source claim about a dense exact daily session inventory."""

    schema_version: Literal["1"] = "1"
    revision: RevisionEnvelopeV1
    source_id: NonBlankStr
    native_record_id: NonBlankStr
    mic: NonBlankStr
    session_scope: Literal["regular"]
    start_date: date
    end_date: date
    snapshot_identifier: NonBlankStr
    snapshot_as_of: TemporalBoundaryClaimV1
    covered_dataset_hashes: tuple[SHA256Hash, ...]
    covered_partition_hashes: tuple[SHA256Hash, ...]
    record_inventory: tuple[SessionInventoryEntryV1, ...]
    expected_daily_cardinality: Annotated[int, Field(ge=1)]
    exception_dates: tuple[date, ...]
    methodology_hash: SHA256Hash
    status: Literal["expected_complete", "not_expected", "partial", "unknown"]
    missing_artifact_hashes: tuple[SHA256Hash, ...]
    revision_history_completeness: Literal["complete", "current_only", "unknown"]

    @field_validator(
        "covered_dataset_hashes", "covered_partition_hashes", "missing_artifact_hashes"
    )
    @classmethod
    def canonicalize_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(hashes)) != len(hashes):
            raise ValueError("session coverage hashes must be unique")
        return tuple(sorted(hashes))

    @field_validator("record_inventory")
    @classmethod
    def canonicalize_inventory(
        cls, entries: tuple[SessionInventoryEntryV1, ...]
    ) -> tuple[SessionInventoryEntryV1, ...]:
        identities = tuple((item.assertion_id, item.version_id) for item in entries)
        hashes = tuple(item.record_hash for item in entries)
        if len(set(identities)) != len(identities) or len(set(hashes)) != len(hashes):
            raise ValueError("session coverage inventory entries must be unique")
        return tuple(
            sorted(
                entries, key=lambda item: (str(item.assertion_id), str(item.version_id))
            )
        )

    @field_validator("exception_dates")
    @classmethod
    def canonicalize_exception_dates(cls, values: tuple[date, ...]) -> tuple[date, ...]:
        if len(set(values)) != len(values):
            raise ValueError("session coverage exception dates must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("session coverage date interval cannot be reversed")
        if self.status == "expected_complete" and (
            not self.covered_dataset_hashes
            or not self.covered_partition_hashes
            or not self.record_inventory
            or self.exception_dates
            or self.missing_artifact_hashes
        ):
            raise ValueError(
                "expected-complete session coverage requires an exact closed inventory"
            )
        if self.revision.payload_hash != content_hash(assertion_version_payload(self)):
            raise ValueError("session coverage payload hash mismatch")
        return self


class TimezoneInputV1(FrozenModel):
    """Exact modern TZif reconstruction input identity."""

    schema_version: Literal["1"] = "1"
    timezone_identifier: NonBlankStr
    tzif_sha256: SHA256Hash
    tzdb_release: NonBlankStr
    artifact_hash: SHA256Hash
    reconstruction_observed_at: UTCDateTime
    canonical_encoding_contract_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (
            self.canonical_encoding_contract_hash
            != canonical_session_encoding_contract_hash()
        ):
            raise ValueError("timezone input requires recognized v1 encoding contract")
        if self.tzif_sha256 != self.artifact_hash:
            raise ValueError(
                "timezone input artifact must identify the exact TZif bytes"
            )
        return self


class ScheduleGenerationPolicyV1(FrozenModel):
    """Input-only identity for explicit local-row UTC reconstruction."""

    schema_version: Literal["1"] = "1"
    algorithm: Literal["explicit_local_rows_to_utc_v1"]
    semantic_algorithm_hash: SHA256Hash
    producer_name: NonBlankStr
    producer_version: NonBlankStr
    producer_source_hash: SHA256Hash
    producer_package_hash: SHA256Hash
    implementation_hash: SHA256Hash
    python_identity: NonBlankStr
    lockfile_hash: SHA256Hash
    timezone_input_hash: SHA256Hash
    canonical_encoding_contract_hash: SHA256Hash
    historical_timezone_methodology_encoding_hashes: tuple[SHA256Hash, ...]

    @field_validator("historical_timezone_methodology_encoding_hashes")
    @classmethod
    def canonicalize_methodology_hashes(
        cls, values: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(values)) != len(values):
            raise ValueError("generation methodology hashes must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (
            self.canonical_encoding_contract_hash
            != canonical_session_encoding_contract_hash()
        ):
            raise ValueError(
                "generation policy requires recognized v1 encoding contract"
            )
        if self.semantic_algorithm_hash != schedule_generation_algorithm_hash():
            raise ValueError("generation policy semantic algorithm hash mismatch")
        return self


class SessionOutputV1(FrozenModel):
    """One provenance-free semantic scheduled-session value."""

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    state: Literal["regular", "early_close", "closed", "unknown"]
    utc_open: UTCDateTime | None
    utc_close: UTCDateTime | None
    local_open: NonBlankStr | None
    local_close: NonBlankStr | None
    open_fold: Literal[0, 1] | None
    close_fold: Literal[0, 1] | None
    interpretation_status: Literal["authorized", "indeterminate", "conflict"]

    @model_validator(mode="after")
    def validate_output_shape(self) -> Self:
        boundaries = (self.utc_open, self.utc_close)
        local = (self.local_open, self.local_close)
        if self.interpretation_status != "authorized" and any(
            value is not None for value in boundaries
        ):
            raise ValueError(
                "indeterminate or conflicting output cannot carry UTC bounds"
            )
        is_open = self.state in {"regular", "early_close"}
        if self.interpretation_status == "authorized" and is_open:
            if any(value is None for value in (*boundaries, *local)):
                raise ValueError("authorized open output requires all boundaries")
            assert self.utc_open is not None and self.utc_close is not None
            if self.utc_close <= self.utc_open:
                raise ValueError("authorized session close must follow open")
        elif not is_open and any(value is not None for value in (*boundaries, *local)):
            raise ValueError("closed or unknown output cannot invent boundaries")
        return self


class GeneratedSessionRowV1(FrozenModel):
    """One semantic output bound to selected source and producer lineage."""

    schema_version: Literal["1"] = "1"
    output: SessionOutputV1
    source_version_hash: SHA256Hash
    generation_policy_hash: SHA256Hash


class ScheduleArtifactV1(FrozenModel):
    """Replayable query-bound schedule generation result."""

    schema_version: Literal["1"] = "1"
    query: ObservationQueryV1
    query_hash: SHA256Hash
    selected_source_proof_hash: SHA256Hash | None
    selected_coverage_proof_hash: SHA256Hash | None
    generation_policy: ScheduleGenerationPolicyV1
    generation_policy_hash: SHA256Hash
    timezone_bytes_hash: SHA256Hash
    generated_at: UTCDateTime
    rows: tuple[GeneratedSessionRowV1, ...]
    canonical_output_bytes_hash: SHA256Hash
    output_row_inventory_hash: SHA256Hash
    historical_authority_availability_proof_hashes: tuple[SHA256Hash, ...]
    reconstruction_input_hashes: tuple[SHA256Hash, ...]
    classification: Literal["generated", "indeterminate", "conflict"]
    reasons: tuple[NonBlankStr, ...]


type SessionInputRecordV1 = (
    ScheduledSessionVersionV1 | RealizedSessionVersionV1 | SessionCoverageVersionV1
)


class SelectedSessionRecordsV1(FrozenModel):
    """Query-, role-, and subject-bound selected session source records."""

    schema_version: Literal["1"] = "1"
    query: ObservationQueryV1
    purpose: M1dSelectionPurpose
    dataset_role: Literal["scheduled_session", "realized_session", "session_coverage"]
    records: tuple[SessionInputRecordV1, ...]
    proof: M1dSelectionProofV1

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.query != self.proof.query or self.purpose != self.proof.purpose:
            raise ValueError(
                "selected session records must match proof query and purpose"
            )
        actual = tuple(sorted(content_hash(record) for record in self.records))
        if actual != self.proof.selected_hashes:
            raise ValueError("selected session record hashes must match proof")
        contracts: dict[str, tuple[str, type[SessionInputRecordV1]]] = {
            "scheduled_session": ("scheduled_session", ScheduledSessionVersionV1),
            "realized_session": ("realized_session", RealizedSessionVersionV1),
            "session_coverage": ("session_coverage", SessionCoverageVersionV1),
        }
        current = contracts.get(self.purpose)
        if current is None:
            raise ValueError("selected-session purpose is not owned by Task 2")
        expected_role, expected_type = current
        if self.dataset_role != expected_role:
            raise ValueError("selected session role must match purpose")
        if any(not isinstance(record, expected_type) for record in self.records):
            raise ValueError("selected session record type must match role")
        subject = self.proof.subject
        if not isinstance(subject, SessionSubjectV1):
            raise ValueError("selected session proof requires a session subject")
        for record in self.records:
            if record.source_id != subject.source_id:
                raise ValueError("selected session source must match proof subject")
            if isinstance(record, SessionCoverageVersionV1):
                if (
                    record.mic != subject.mic
                    or record.session_scope != subject.session_scope
                    or not (
                        record.start_date <= subject.session_date <= record.end_date
                    )
                ):
                    raise ValueError("selected session coverage subject mismatch")
            elif (
                record.session_key.mic != subject.mic
                or record.session_key.session_scope != subject.session_scope
                or record.session_key.local_date != subject.session_date
            ):
                raise ValueError("selected session row subject mismatch")
        return self
