"""Immutable research policies and source-derived historical universe assertions."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import (
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionEvidenceV1,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.domain.securities import (
    IdentityKind,
    IdentityReferenceV1,
    RecordResolutionClassification,
)
from drift.serialization.canonical import content_hash


class UniverseTargetLevel(StrEnum):
    """A universe version has one explicit economic target level."""

    SECURITY = "security"
    LISTING = "listing"


class SourceUniverseKind(StrEnum):
    """Sourced membership meaning, separate from researcher-authored eligibility."""

    INDEX = "index"
    PROVIDER_COVERAGE = "provider_coverage"


class _UniverseDefinition(FrozenModel):
    schema_version: Literal["1"]
    universe_id: UUID7
    universe_version: NonBlankStr
    target_level: UniverseTargetLevel
    methodology_reference: ArtifactReference
    methodology_hash: SHA256Hash
    identity_bundle_hash: SHA256Hash

    @field_validator("methodology_reference")
    @classmethod
    def safe_methodology(cls, reference: ArtifactReference) -> ArtifactReference:
        return validate_safe_provenance_reference(reference)

    @model_validator(mode="after")
    def validate_methodology_hash(self) -> Self:
        if self.methodology_reference.content_hash != self.methodology_hash:
            raise ValueError("methodology hash must match the retained artifact")
        return self


class ResearchUniverseDefinitionV1(_UniverseDefinition):
    """Content-addressed initial listing policy, not a historical source claim."""

    universe_kind: Literal["structural"]
    target_level: Literal[UniverseTargetLevel.LISTING]
    universe_bundle_hash: SHA256Hash
    classification_contract_hash: SHA256Hash
    created_at: UTCDateTime


class SourceUniverseDefinitionVersionV1(_UniverseDefinition):
    """Causally available version of a source's universe methodology."""

    revision: RevisionEnvelopeV1
    universe_kind: SourceUniverseKind
    effective_interval: TemporalIntervalClaimV1


class UniverseDefinitionSubjectV1(FrozenModel):
    """The source-defined universe version requested by a historical query."""

    universe_id: UUID7
    universe_version: NonBlankStr


class MembershipEffect(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"


class MembershipStatus(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    INDETERMINATE = "indeterminate"


class UniverseMembershipVersionV1(FrozenModel):
    """One version of a sourced business event, distinct from its revision kind."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    universe_id: UUID7
    universe_version: NonBlankStr
    target_level: UniverseTargetLevel
    target_id: UUID7
    membership_effect: MembershipEffect
    effective_time: TemporalBoundaryClaimV1
    source_event_id: NonBlankStr


class SourceUniverseDefinitionResolutionV1(FrozenModel):
    """A source definition selected from its complete validated dataset."""

    schema_version: Literal["1"]
    subject: UniverseDefinitionSubjectV1
    definition: SourceUniverseDefinitionVersionV1 | None
    classification: RecordResolutionClassification
    evidence: ResolutionEvidenceV1
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.evidence.normalized_query.subject_hash != content_hash(self.subject):
            raise ValueError("source definition subject mismatch")
        if (
            self.evidence.normalized_query.purpose
            is not M1bSelectionPurpose.UNIVERSE_MEMBERSHIP
        ):
            raise ValueError("source definition purpose mismatch")
        if self.classification is RecordResolutionClassification.RESOLVED:
            if (
                self.definition is None
                or content_hash(self.definition)
                not in self.evidence.selected_record_hashes
            ):
                raise ValueError("resolved definition requires a selected record")
        elif self.definition is not None:
            raise ValueError(
                "unresolved source definition cannot authorize a definition"
            )
        if self.outcome_binding_hash != content_hash(
            self.model_dump(mode="python", exclude={"outcome_binding_hash"})
        ):
            raise ValueError("source definition outcome binding mismatch")
        return self


class UniverseMembershipResolutionV1(FrozenModel):
    """Definition-bound membership at E, using only assertions knowable by K."""

    schema_version: Literal["1"]
    universe_id: UUID7
    universe_version: NonBlankStr
    target_level: UniverseTargetLevel
    target_id: UUID7
    definition_hash: SHA256Hash | None
    definition_resolution_hash: SHA256Hash | None
    identity_bundle_hash: SHA256Hash
    universe_bundle_hash: SHA256Hash
    target_assignment_proof_hashes: tuple[SHA256Hash, ...]
    status: MembershipStatus
    known_upcoming_effects: tuple[MembershipEffect, ...]
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        target = IdentityReferenceV1(
            kind=IdentityKind(self.target_level.value), internal_id=self.target_id
        )
        subject = {
            "universe_id": self.universe_id,
            "universe_version": self.universe_version,
            "definition_hash": self.definition_hash,
            "definition_resolution_hash": self.definition_resolution_hash,
            "target": target,
        }
        if self.evidence.normalized_query.subject_hash != content_hash(subject):
            raise ValueError("membership subject mismatch")
        if (
            self.evidence.normalized_query.purpose
            is not M1bSelectionPurpose.UNIVERSE_MEMBERSHIP
        ):
            raise ValueError("membership purpose mismatch")
        if (
            self.status is not MembershipStatus.INDETERMINATE
            and self.definition_hash is None
        ):
            raise ValueError("known membership requires a selected definition")
        if self.outcome_binding_hash != content_hash(
            self.model_dump(mode="python", exclude={"outcome_binding_hash"})
        ):
            raise ValueError("membership outcome binding mismatch")
        return self


class StructuralEligibilityClassification(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


class StructuralEligibilityResultV1(FrozenModel):
    """Query-bound admission evidence, without market-data or execution claims."""

    schema_version: Literal["1"]
    issuer_id: UUID7
    security_id: UUID7
    listing_id: UUID7
    methodology_id: NonBlankStr
    definition_hash: SHA256Hash
    classification: StructuralEligibilityClassification
    reasons: tuple[NonBlankStr, ...]
    normalized_query: NormalizedSelectionQueryV1
    identity_bundle_hash: SHA256Hash
    universe_bundle_hash: SHA256Hash
    identity_assignment_resolution_hashes: tuple[SHA256Hash, ...]
    identity_resolution_hashes: tuple[SHA256Hash, ...]
    classification_resolution_hash: SHA256Hash | None
    primary_listing_resolution_hash: SHA256Hash | None
    lifecycle_resolution_hash: SHA256Hash | None
    membership_resolution_hash: SHA256Hash
    selection_proof_hashes: tuple[SHA256Hash, ...]
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        subject = {
            "definition_hash": self.definition_hash,
            "issuer_id": self.issuer_id,
            "security_id": self.security_id,
            "listing_id": self.listing_id,
            "methodology_id": self.methodology_id,
        }
        if self.normalized_query.subject_hash != content_hash(subject):
            raise ValueError("structural subject mismatch")
        if (
            self.normalized_query.purpose
            is not M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY
        ):
            raise ValueError("structural purpose mismatch")
        if self.normalized_query.context_bundle_hashes != tuple(
            sorted((self.identity_bundle_hash, self.universe_bundle_hash))
        ):
            raise ValueError("structural bundle mismatch")
        if self.classification is StructuralEligibilityClassification.ELIGIBLE and (
            len(self.identity_assignment_resolution_hashes) < 3
            or len(self.identity_resolution_hashes) < 2
            or self.classification_resolution_hash is None
            or self.primary_listing_resolution_hash is None
            or self.lifecycle_resolution_hash is None
            or not self.selection_proof_hashes
        ):
            raise ValueError(
                "eligible structural result requires all component evidence"
            )
        if self.outcome_binding_hash != content_hash(
            self.model_dump(mode="python", exclude={"outcome_binding_hash"})
        ):
            raise ValueError("structural outcome binding mismatch")
        return self

    @property
    def knowledge_cutoff(self) -> UTCDateTime:
        return self.normalized_query.knowledge_cutoff

    @property
    def evaluation_time(self) -> UTCDateTime:
        return self.normalized_query.evaluation_time
