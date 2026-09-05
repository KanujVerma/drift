"""Closed M1c coverage declarations and bounded source-selection policies."""

from datetime import datetime
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.datasets.hashing import assertion_version_payload
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import RevisionEnvelopeV1, TemporalIntervalClaimV1
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
    _normalize_utc,
)
from drift.domain.economic_common import ActionKind, EconomicSourceKeyV1
from drift.domain.economic_events import EconomicRecordV1
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.serialization.canonical import content_hash

_ECONOMIC_FAMILIES = ("effect", "settlement", "terms")


class DatasetBindingV1(FrozenModel):
    """One immutable dataset input named by the policy."""

    manifest_hash: SHA256Hash
    decision_hash: SHA256Hash
    bundle_hash: SHA256Hash
    role: NonBlankStr
    source_id: NonBlankStr


class EconomicSourceOwnerV1(FrozenModel):
    """The sole source authority for one economic fact family."""

    family: Literal["terms", "effect", "settlement"]
    source_id: NonBlankStr
    fact_manifest_hash: SHA256Hash
    coverage_manifest_hash: SHA256Hash


class EconomicSourceSelectionPolicyV1(FrozenModel):
    """A closed, query-independent source-authority declaration."""

    schema_version: Literal["1"]
    policy_id: NonBlankStr
    policy_version: NonBlankStr
    security_id: UUID7
    action_kinds: tuple[ActionKind, ...]
    scope: Literal["all_security_occurrences"]
    history_start: UTCDateTime
    through: UTCDateTime
    owners: tuple[EconomicSourceOwnerV1, ...]
    input_dataset_bindings: tuple[DatasetBindingV1, ...]

    @field_validator("action_kinds")
    @classmethod
    def require_unique_action_kinds(
        cls, action_kinds: tuple[ActionKind, ...]
    ) -> tuple[ActionKind, ...]:
        if not action_kinds or len(set(action_kinds)) != len(action_kinds):
            raise ValueError("source policy action kinds must be nonempty and unique")
        return action_kinds

    @field_validator("input_dataset_bindings")
    @classmethod
    def require_unique_bindings(
        cls, bindings: tuple[DatasetBindingV1, ...]
    ) -> tuple[DatasetBindingV1, ...]:
        if not bindings:
            raise ValueError("source policy requires dataset bindings")
        identities = tuple(
            (
                binding.manifest_hash,
                binding.decision_hash,
                binding.bundle_hash,
                binding.role,
                binding.source_id,
            )
            for binding in bindings
        )
        if len(set(identities)) != len(identities):
            raise ValueError("source policy dataset bindings must be unique")
        return bindings

    @model_validator(mode="after")
    def validate_policy_scope(self) -> Self:
        require_owner_partition(self)
        for owner in self.owners:
            self._require_owner_binding(
                owner.fact_manifest_hash,
                owner.source_id,
                f"economic_{owner.family}",
                "fact",
            )
            self._require_owner_binding(
                owner.coverage_manifest_hash,
                owner.source_id,
                "economic_coverage",
                "coverage",
            )
        return self

    def _require_owner_binding(
        self, manifest_hash: SHA256Hash, source_id: str, role: str, label: str
    ) -> None:
        if not any(
            binding.manifest_hash == manifest_hash
            and binding.source_id == source_id
            and binding.role == role
            for binding in self.input_dataset_bindings
        ):
            raise ValueError(
                f"owner {label} manifest must be bound under its source and role"
            )


class EconomicCoverageVersionV1(FrozenModel):
    """One immutable, source-side declaration of retained economic coverage."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    source_key: EconomicSourceKeyV1
    security_id: UUID7
    listing_id: UUID7 | None
    coverage_interval: TemporalIntervalClaimV1
    fact_family: Literal["terms", "effect", "settlement"]
    action_kinds: tuple[ActionKind, ...]
    target_manifest_hash: SHA256Hash
    inventory_artifact_hashes: tuple[SHA256Hash, ...]
    inventory_record_hashes: tuple[SHA256Hash, ...]
    methodology_reference: ArtifactReference
    methodology_version: NonBlankStr
    snapshot_at: UTCDateTime
    completeness: Literal["complete", "partial", "unknown"]
    revision_support: Literal["captured_history", "current_only", "unknown"]
    occurrence_key_semantics: Literal[
        "economic_occurrence_ids", "report_ids_only", "unknown"
    ]
    gaps: tuple[TemporalIntervalClaimV1, ...]
    exceptions: tuple[NonBlankStr, ...]

    @field_validator("methodology_reference")
    @classmethod
    def require_safe_methodology_reference(
        cls, reference: ArtifactReference
    ) -> ArtifactReference:
        return validate_safe_provenance_reference(reference)

    @field_validator("action_kinds")
    @classmethod
    def require_unique_action_kinds(
        cls, action_kinds: tuple[ActionKind, ...]
    ) -> tuple[ActionKind, ...]:
        if not action_kinds or len(set(action_kinds)) != len(action_kinds):
            raise ValueError("coverage action kinds must be nonempty and unique")
        return action_kinds

    @field_validator("inventory_artifact_hashes", "inventory_record_hashes")
    @classmethod
    def require_canonical_inventory_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        if len(set(hashes)) != len(hashes) or hashes != tuple(sorted(hashes)):
            raise ValueError("coverage inventory hashes must be unique and sorted")
        return hashes

    @model_validator(mode="after")
    def validate_coverage_shape(self) -> Self:
        if self.source_key.family != "coverage":
            raise ValueError("coverage source family must be coverage")
        if self.revision.payload_hash != content_hash(assertion_version_payload(self)):
            raise ValueError("economic coverage payload hash mismatch")
        self._validate_snapshot_availability()
        if self.completeness == "complete":
            self._validate_complete_scope()
        return self

    def _validate_snapshot_availability(self) -> None:
        if any(
            evidence.upper_bound is not None and evidence.upper_bound < self.snapshot_at
            for evidence in self.revision.availability
        ):
            raise ValueError("coverage availability cannot definitely predate snapshot")

    def _validate_complete_scope(self) -> None:
        if not self.inventory_artifact_hashes:
            raise ValueError("complete coverage requires inventory artifact hashes")
        if self.gaps or self.exceptions:
            raise ValueError("complete coverage cannot declare gaps or exceptions")
        end = self.coverage_interval.end
        if end is None or end.lower_bound is None:
            raise ValueError("complete coverage requires a bounded interval end")
        if end.lower_bound > self.snapshot_at:
            raise ValueError("complete coverage snapshot cannot precede declared scope")


type EconomicInputRecordV1 = EconomicRecordV1 | EconomicCoverageVersionV1


def coverage_contains(
    coverage: EconomicCoverageVersionV1, start: datetime, through: datetime
) -> bool:
    """Return whether a declared interval contains an inclusive economic horizon."""
    start_utc = _normalize_utc(start)
    through_utc = _normalize_utc(through)
    interval_start = coverage.coverage_interval.start.upper_bound
    interval_end = (
        None
        if coverage.coverage_interval.end is None
        else coverage.coverage_interval.end.lower_bound
    )
    return (
        interval_start is not None
        and interval_end is not None
        and interval_start <= start_utc
        and interval_end > through_utc
    )


def policy_owner(
    policy: EconomicSourceSelectionPolicyV1,
    family: Literal["terms", "effect", "settlement"],
) -> EconomicSourceOwnerV1:
    """Return the source owner for one family."""
    for owner in policy.owners:
        if owner.family == family:
            return owner
    raise ValueError("invalid source policy has no owner for family")


def require_owner_partition(policy: EconomicSourceSelectionPolicyV1) -> None:
    """Reject fallback, partitioning, and omitted-authority policy shapes."""
    families = tuple(owner.family for owner in policy.owners)
    if sorted(families) != list(_ECONOMIC_FAMILIES):
        raise ValueError("exactly one owner per economic family required")
    if policy.history_start > policy.through:
        raise ValueError("source policy window reversed")
