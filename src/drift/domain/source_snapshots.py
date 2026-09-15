"""Immutable M1e real-source snapshot and replay-closure domain contracts."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import TemporalBoundaryClaimV1
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.domain.qualification import ConsumerPurpose
from drift.serialization.canonical import canonical_data, content_hash


class SourceComponentRole(StrEnum):
    """The role of one provider component in historical market semantics."""

    IDENTITY_UNIVERSE = "identity_universe"
    ACTION_TERMS = "action_terms"
    OCCURRED_EFFECTS = "occurred_effects"
    SETTLEMENT_OUTCOMES = "settlement_outcomes"
    OBSERVATIONS = "observations"
    SCHEDULED_SESSIONS = "scheduled_sessions"
    REALIZED_SESSIONS = "realized_sessions"
    GRADING_TRUTH = "grading_truth"


class ConsistencyStatus(StrEnum):
    """Result of cross-component vintage and temporal coordination."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"


class ReplayInputKind(StrEnum):
    """Closed categories of replay inputs required for replay closure."""

    NATIVE_ARTIFACT = "native_artifact"
    GRADING_EVIDENCE = "grading_evidence"
    METHODOLOGY_OR_SCHEMA = "methodology_or_schema"
    RIGHTS = "rights"
    MANIFEST = "manifest"
    VALIDATION_RUN_DECISION_BUNDLE = "validation_run_decision_bundle"
    M1A_AVAILABILITY_EVIDENCE_POLICY = "m1a_availability_evidence_policy"
    M1B_QUERY_CONTEXT_RESULT = "m1b_query_context_result"
    M1C_QUERY_POLICY_CONTEXT_RESULT = "m1c_query_policy_context_result"
    M1D_QUERY_POLICY_CONTEXT_RESULT = "m1d_query_policy_context_result"
    ADAPTER_MAPPING = "adapter_mapping"
    QUALIFICATION_POLICY = "qualification_policy"


class ExpectedOutputKind(StrEnum):
    """Closed categories of pre-evaluator expected outputs."""

    SELECTED_SOURCE_RECORD = "selected_source_record"
    M1B_RESOLUTION = "m1b_resolution"
    M1C_OUTCOME_OR_REFERENCE = "m1c_outcome_or_reference"
    M1D_SCHEDULE_MAPPING_DERIVATION_VIEW_REFERENCE = (
        "m1d_schedule_mapping_derivation_view_reference"
    )


def _sorted_unique_strings(
    values: tuple[str, ...], *, label: str, nonempty: bool = False
) -> tuple[str, ...]:
    if (nonempty and not values) or len(values) != len(set(values)):
        qualifier = "nonempty and " if nonempty else ""
        raise ValueError(f"{label} must be {qualifier}unique")
    return tuple(sorted(values))


class ProviderReleaseEvidenceV1(FrozenModel):
    """Immutable evidence for one component's provider release."""

    schema_version: Literal["1"] = "1"
    component_role: SourceComponentRole
    provider_release_id: NonBlankStr
    provider_object_ids: tuple[NonBlankStr, ...] = ()
    native_state_label: NonBlankStr
    temporal_boundary: TemporalBoundaryClaimV1
    availability_evidence_hashes: tuple[SHA256Hash, ...]
    acquisition_receipt_hash: SHA256Hash
    evidence_references: tuple[ArtifactReference, ...] = ()

    @field_validator("provider_object_ids")
    @classmethod
    def canonicalize_object_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="provider_object_ids")

    @field_validator("availability_evidence_hashes")
    @classmethod
    def canonicalize_evidence_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="availability_evidence_hashes")


class CoordinatedCutoffRuleV1(FrozenModel):
    """Per-component cutoff and revision horizon rule for cross-consistency."""

    schema_version: Literal["1"] = "1"
    profile_set_hash: SHA256Hash
    per_component_cutoff_rules: Mapping[SourceComponentRole, NonBlankStr]
    revision_horizon: NonBlankStr
    ordering_rule: NonBlankStr
    semantic_hash: SHA256Hash
    evidence_references: tuple[ArtifactReference, ...] = ()


def consistency_decision_body(
    decision: CrossComponentConsistencyDecisionV1,
) -> dict[str, Any]:
    """Return canonical data for CrossComponentConsistencyDecisionV1
    without decision_hash.
    """
    body = canonical_data(decision)
    assert isinstance(body, dict)
    body.pop("decision_hash", None)
    return body


def cross_component_consistency_decision_hash(
    decision: CrossComponentConsistencyDecisionV1,
) -> str:
    """Compute canonical hash of CrossComponentConsistencyDecisionV1
    excluding its decision_hash.
    """
    return content_hash(consistency_decision_body(decision))


class CrossComponentConsistencyDecisionV1(FrozenModel):
    """Typed outcome of evaluating cross-component temporal overlap."""

    schema_version: Literal["1"] = "1"
    component_release_hashes: tuple[SHA256Hash, ...]
    coordinated_rule_hash: SHA256Hash
    result: ConsistencyStatus
    conflicts_and_gaps: tuple[NonBlankStr, ...] = ()
    decision_policy_hash: SHA256Hash
    decision_id: UUID7
    decided_at: UTCDateTime
    decision_hash: SHA256Hash

    @field_validator("component_release_hashes")
    @classmethod
    def canonicalize_release_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="component_release_hashes")

    @model_validator(mode="after")
    def validate_decision_hash(self) -> Self:
        expected = cross_component_consistency_decision_hash(self)
        if self.decision_hash != expected:
            raise ValueError(
                f"decision_hash mismatch: declared {self.decision_hash} != {expected}"
            )
        return self


class RawReplayInputEntryV1(FrozenModel):
    """Byte-addressed raw replay input entry."""

    discriminator: Literal["raw_bytes"] = "raw_bytes"
    kind: ReplayInputKind
    artifact_reference: ArtifactReference
    content_hash: SHA256Hash
    byte_object_descriptor_hash: SHA256Hash
    media_type: NonBlankStr
    schema_descriptor: NonBlankStr | None = None
    purpose: ConsumerPurpose
    profile_hash: SHA256Hash
    component_role: SourceComponentRole
    rights_binding_hash: SHA256Hash

    @field_validator("artifact_reference")
    @classmethod
    def validate_reference_locator(
        cls, artifact: ArtifactReference
    ) -> ArtifactReference:
        validate_safe_provenance_reference(artifact)
        expected_location = f"drift+sha256://{artifact.content_hash}"
        if artifact.location != expected_location:
            raise ValueError(
                "artifact reference must use a stable content URI bound to its hash "
                f"(expected {expected_location}, got {artifact.location})"
            )
        return artifact

    @model_validator(mode="after")
    def validate_reference_hash(self) -> Self:
        if self.artifact_reference.content_hash != self.content_hash:
            raise ValueError("artifact reference hash does not match content hash")
        return self


class CanonicalReplayInputEntryV1(FrozenModel):
    """Canonical parsed model replay input entry."""

    discriminator: Literal["canonical_model"] = "canonical_model"
    kind: ReplayInputKind
    artifact_reference: ArtifactReference
    content_hash: SHA256Hash
    model_type: NonBlankStr
    model_version: NonBlankStr
    purpose: ConsumerPurpose
    profile_hash: SHA256Hash
    component_role: SourceComponentRole
    original_identity: NonBlankStr

    @field_validator("artifact_reference")
    @classmethod
    def validate_reference_locator(
        cls, artifact: ArtifactReference
    ) -> ArtifactReference:
        validate_safe_provenance_reference(artifact)
        expected_location = f"drift+sha256://{artifact.content_hash}"
        if artifact.location != expected_location:
            raise ValueError(
                "artifact reference must use a stable content URI bound to its hash "
                f"(expected {expected_location}, got {artifact.location})"
            )
        return artifact

    @model_validator(mode="after")
    def validate_reference_hash(self) -> Self:
        if self.artifact_reference.content_hash != self.content_hash:
            raise ValueError("artifact reference hash does not match content hash")
        return self


type ReplayInputEntryV1 = Annotated[
    RawReplayInputEntryV1 | CanonicalReplayInputEntryV1,
    Field(discriminator="discriminator"),
]


class ExpectedOutputV1(FrozenModel):
    """Pre-evaluator canonical expected output record."""

    schema_version: Literal["1"] = "1"
    kind: ExpectedOutputKind
    purpose: ConsumerPurpose
    profile_hash: SHA256Hash
    canonical_output_hash: SHA256Hash
    semantic_owner: NonBlankStr
    query_hash: SHA256Hash
    input_context_hash: SHA256Hash
    original_identity: NonBlankStr


def snapshot_body(snapshot: RealSourceSnapshotV1) -> dict[str, Any]:
    """Return the canonical preimage without the self-excluding snapshot_hash."""
    body = canonical_data(snapshot)
    assert isinstance(body, dict)
    body.pop("snapshot_hash", None)
    return body


def real_source_snapshot_hash(snapshot: RealSourceSnapshotV1) -> str:
    """Compute canonical hash of RealSourceSnapshotV1 excluding its snapshot_hash."""
    return content_hash(snapshot_body(snapshot))


class RealSourceSnapshotV1(FrozenModel):
    """Frozen real-source snapshot binding exact qualification inputs."""

    schema_version: Literal["1"] = "1"
    snapshot_id: UUID7
    snapshot_version: NonBlankStr = "1"
    created_at: UTCDateTime
    profile_set_hash: SHA256Hash
    profile_hashes: tuple[SHA256Hash, ...]
    authorized_profile_hashes: tuple[SHA256Hash, ...]
    rights_assessment_hashes: tuple[SHA256Hash, ...]
    receipt_hashes: tuple[SHA256Hash, ...]
    native_artifact_hashes: tuple[SHA256Hash, ...]
    grading_artifact_hashes: tuple[SHA256Hash, ...]
    release_evidence: tuple[ProviderReleaseEvidenceV1, ...]
    consistency_decision: CrossComponentConsistencyDecisionV1
    cutoff_assertions: tuple[NonBlankStr, ...]
    coverage_assertions: tuple[NonBlankStr, ...]
    methodology_schema_hashes: tuple[SHA256Hash, ...]
    adapter_semantic_hashes: tuple[SHA256Hash, ...]
    adapter_source_hashes: tuple[SHA256Hash, ...]
    existing_manifest_hashes: tuple[SHA256Hash, ...]
    validation_decision_hashes: tuple[SHA256Hash, ...]
    validation_bundle_hashes: tuple[SHA256Hash, ...]
    m1a_policy_hashes: tuple[SHA256Hash, ...]
    replay_inputs: tuple[ReplayInputEntryV1, ...]
    expected_outputs: tuple[ExpectedOutputV1, ...]
    snapshot_hash: SHA256Hash

    @field_validator(
        "profile_hashes",
        "authorized_profile_hashes",
        "rights_assessment_hashes",
        "receipt_hashes",
        "native_artifact_hashes",
        "grading_artifact_hashes",
        "methodology_schema_hashes",
        "adapter_semantic_hashes",
        "adapter_source_hashes",
        "existing_manifest_hashes",
        "validation_decision_hashes",
        "validation_bundle_hashes",
        "m1a_policy_hashes",
    )
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="snapshot hashes")

    @field_validator("cutoff_assertions", "coverage_assertions")
    @classmethod
    def canonicalize_assertions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(values, label="snapshot assertions")

    @model_validator(mode="after")
    def validate_snapshot_invariants(self) -> Self:
        # Check subset
        profile_set = set(self.profile_hashes)
        for p in self.authorized_profile_hashes:
            if p not in profile_set:
                raise ValueError(
                    f"authorized profile hash {p} not in declared profile hashes"
                )

        # Check self-excluding hash
        expected_hash = real_source_snapshot_hash(self)
        if self.snapshot_hash != expected_hash:
            msg = (
                f"snapshot_hash mismatch: declared {self.snapshot_hash} "
                f"!= {expected_hash}"
            )
            raise ValueError(msg)
        return self
