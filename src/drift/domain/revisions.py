"""Immutable fact revisions and conservative point-in-time selection."""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, TypedDict
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from drift.datasets.hashing import fact_version_payload
from drift.domain.artifacts import ArtifactReference
from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
    _normalize_utc,
)
from drift.domain.dataset_validation import (
    DatasetValidationError,
    FindingSeverity,
    ValidationFindingV1,
)
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
    ValidPeriodV1,
    evaluate_availability,
)
from drift.serialization.canonical import content_hash


class RevisionKind(StrEnum):
    """Source-native meaning of an immutable fact version."""

    INITIAL = "initial"
    REVISION = "revision"
    RESTATEMENT = "restatement"
    CORRECTION = "correction"
    WITHDRAWAL = "withdrawal"


class LogicalFactKeyV1(FrozenModel):
    """The stable identity shared by all versions of one logical fact."""

    source_id: NonBlankStr
    entity_key: NonBlankStr
    concept: NonBlankStr
    valid_period: ValidPeriodV1
    unit: NonBlankStr
    dimensions: ImmutableJSON


class FactVersionV1(FrozenModel):
    """One append-only version of an asset-neutral reported fact."""

    fact_version_id: UUID7
    logical_key: LogicalFactKeyV1
    revision_kind: RevisionKind
    supersedes_fact_version_id: UUID7 | None = None
    source_sequence: Annotated[int, Field(ge=0)]
    value: ImmutableJSON
    null_reason: NonBlankStr | None = None
    availability: tuple[AvailabilityEvidenceV1, ...]
    source_artifact: ArtifactReference
    payload_hash: SHA256Hash

    @field_validator("source_artifact", mode="before")
    @classmethod
    def require_source_artifact(cls, value: object) -> object:
        """Reject facts that lose their source artifact binding."""
        if value is None:
            msg = "source artifact is required"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_immutable_fact(self) -> FactVersionV1:
        """Enforce immutable payload and record-local invariants."""
        if not self.availability:
            msg = "fact version requires availability evidence"
            raise ValueError(msg)
        channels = tuple(evidence.channel for evidence in self.availability)
        if len(channels) != len(set(channels)):
            msg = "fact version availability channels must be unique"
            raise ValueError(msg)
        if self.revision_kind is RevisionKind.WITHDRAWAL:
            if self.value is not None or self.null_reason != "withdrawn":
                msg = "withdrawal requires null value and null reason withdrawn"
                raise ValueError(msg)
        elif self.value is None and self.null_reason is None:
            msg = "null value requires an explicit null reason"
            raise ValueError(msg)
        if self.payload_hash != content_hash(fact_version_payload(self)):
            msg = "fact version payload hash must match its canonical payload"
            raise ValueError(msg)
        return self


class FactSelectionResultV1(FrozenModel):
    """Hash-bound output of a single channel, policy, and cutoff query."""

    classification: CutoffEligibility
    reason: NonBlankStr
    cutoff: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    considered_versions: tuple[FactVersionV1, ...]
    considered_version_hashes: tuple[SHA256Hash, ...]
    selected_version_hash: SHA256Hash | None = None
    selected_version: FactVersionV1 | None = None

    @model_validator(mode="after")
    def validate_identity_bindings(self) -> FactSelectionResultV1:
        """Bind every result field to the exact query inputs and selection."""
        if self.policy_id != self.policy.policy_id:
            msg = "result policy id must match policy"
            raise ValueError(msg)
        if self.policy_hash != content_hash(self.policy):
            msg = "result policy hash must match policy"
            raise ValueError(msg)
        ordered = tuple(
            sorted(self.considered_versions, key=lambda item: item.source_sequence)
        )
        if self.considered_versions != ordered:
            msg = "considered versions must be in source sequence order"
            raise ValueError(msg)
        expected_hashes = tuple(content_hash(item) for item in self.considered_versions)
        if self.considered_version_hashes != expected_hashes:
            msg = "considered version hashes must match considered versions"
            raise ValueError(msg)
        if len(set(self.considered_version_hashes)) != len(
            self.considered_version_hashes
        ):
            msg = "considered version hashes must be unique"
            raise ValueError(msg)
        if (self.selected_version is None) != (self.selected_version_hash is None):
            msg = "selected version and selected version hash must appear together"
            raise ValueError(msg)
        if self.selected_version is not None:
            if self.selected_version not in self.considered_versions:
                msg = "selected version must be considered"
                raise ValueError(msg)
            if self.selected_version_hash != content_hash(self.selected_version):
                msg = "selected version hash must match selected version"
                raise ValueError(msg)
        return self


class _SelectionIdentity(TypedDict):
    cutoff: datetime
    requested_channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    policy_id: str
    policy_hash: str
    considered_versions: tuple[FactVersionV1, ...]
    considered_version_hashes: tuple[str, ...]


def validate_revision_chain(
    versions: Sequence[FactVersionV1],
) -> tuple[ValidationFindingV1, ...]:
    """Return deterministic findings for malformed immutable revision chains."""
    findings: list[ValidationFindingV1] = []
    identifiers = tuple(version.fact_version_id for version in versions)
    if len(set(identifiers)) != len(identifiers):
        findings.append(_finding("duplicate_fact_version_id"))
    by_id = {version.fact_version_id: version for version in versions}
    roots = tuple(
        version
        for version in versions
        if version.revision_kind is RevisionKind.INITIAL
        and version.supersedes_fact_version_id is None
    )
    if not roots:
        findings.append(_finding("missing_initial_root"))
    elif len(roots) > 1:
        findings.append(_finding("multiple_initial_roots"))

    children: Counter[UUID] = Counter()
    for version in versions:
        _validate_record(version, findings)
        predecessor_id = version.supersedes_fact_version_id
        if version.revision_kind is RevisionKind.INITIAL:
            if predecessor_id is not None:
                findings.append(_finding("initial_version_has_predecessor"))
            continue
        if predecessor_id is None or predecessor_id not in by_id:
            findings.append(_finding("missing_predecessor"))
            continue
        predecessor = by_id[predecessor_id]
        children[predecessor_id] += 1
        if version.logical_key != predecessor.logical_key:
            findings.append(_finding("logical_key_mismatch"))
        if version.source_sequence <= predecessor.source_sequence:
            findings.append(_finding("non_increasing_source_sequence"))
    if any(count > 1 for count in children.values()):
        findings.append(_finding("branching_revision_chain"))
    if _has_cycle(by_id):
        findings.append(_finding("revision_cycle"))
    return tuple(findings)


def select_fact_version(
    versions: Sequence[FactVersionV1],
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> FactSelectionResultV1:
    """Select the latest definitely available version without future leakage."""
    findings = validate_revision_chain(versions)
    if findings:
        raise DatasetValidationError(findings)
    cutoff_utc = _normalize_utc(cutoff)
    ordered = tuple(sorted(versions, key=lambda version: version.source_sequence))
    query_identity: _SelectionIdentity = {
        "cutoff": cutoff_utc,
        "requested_channel": channel,
        "policy": policy,
        "policy_id": policy.policy_id,
        "policy_hash": content_hash(policy),
        "considered_versions": ordered,
        "considered_version_hashes": tuple(content_hash(item) for item in ordered),
    }
    decisions = tuple(
        (
            version,
            evaluate_availability(
                next(
                    evidence
                    for evidence in version.availability
                    if evidence.channel == channel
                ),
                channel,
                policy,
                cutoff_utc,
                retained_evidence,
            ),
        )
        for version in ordered
        if any(evidence.channel == channel for evidence in version.availability)
    )
    eligible = tuple(
        item
        for item in decisions
        if item[1].classification is CutoffEligibility.ELIGIBLE
    )
    if eligible:
        selected = max(eligible, key=lambda item: item[0].source_sequence)[0]
        if selected.revision_kind is RevisionKind.WITHDRAWAL:
            return FactSelectionResultV1(
                classification=CutoffEligibility.INELIGIBLE,
                reason="latest_available_version_withdrawn",
                selected_version=None,
                selected_version_hash=None,
                **query_identity,
            )
        return FactSelectionResultV1(
            classification=CutoffEligibility.ELIGIBLE,
            reason="latest_definitely_available_version",
            selected_version=selected,
            selected_version_hash=content_hash(selected),
            **query_identity,
        )
    classification = (
        CutoffEligibility.INDETERMINATE
        if not decisions
        or any(
            decision.classification is CutoffEligibility.INDETERMINATE
            for _, decision in decisions
        )
        else CutoffEligibility.INELIGIBLE
    )
    return FactSelectionResultV1(
        classification=classification,
        reason=(
            "availability_not_established"
            if classification is CutoffEligibility.INDETERMINATE
            else "no_version_available_by_cutoff"
        ),
        selected_version=None,
        selected_version_hash=None,
        **query_identity,
    )


def _validate_record(
    version: FactVersionV1, findings: list[ValidationFindingV1]
) -> None:
    """Defend chain validation against unvalidated deserialized model instances."""
    if version.source_artifact is None:
        findings.append(_finding("missing_source_artifact"))
    if not version.availability:
        findings.append(_finding("missing_availability_evidence"))
    elif len({evidence.channel for evidence in version.availability}) != len(
        version.availability
    ):
        findings.append(_finding("duplicate_availability_channel"))
    if version.revision_kind is RevisionKind.WITHDRAWAL:
        if version.value is not None or version.null_reason != "withdrawn":
            findings.append(_finding("invalid_withdrawal"))
    elif version.value is None and version.null_reason is None:
        findings.append(_finding("missing_null_reason"))
    if version.payload_hash != content_hash(fact_version_payload(version)):
        findings.append(_finding("payload_hash_mismatch"))


def _has_cycle(by_id: Mapping[UUID, FactVersionV1]) -> bool:
    """Detect predecessor cycles without trusting source sequence values."""
    for start in by_id:
        seen: set[UUID] = set()
        current: UUID | None = start
        while current is not None:
            if current in seen:
                return True
            seen.add(current)
            version = by_id.get(current)
            if version is None:
                break
            current = version.supersedes_fact_version_id
    return False


def _finding(code: str) -> ValidationFindingV1:
    """Build a stable error finding for a revision validation failure."""
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
    )
