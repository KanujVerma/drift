"""Historical issuer, security, listing, and relationship contracts."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.assertions import (
    ResolutionEvidenceV1,
    ResolutionMode,
    RevisionEnvelopeV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.temporal import AvailabilityChannelV1


class IdentityKind(StrEnum):
    """Level represented by one internal identity."""

    ISSUER = "issuer"
    SECURITY = "security"
    LISTING = "listing"


class ListingVenue(StrEnum):
    """Supported primary US listing venues by ISO market identifier code."""

    XNYS = "XNYS"
    XNAS = "XNAS"
    XASE = "XASE"


class IssuerV1(FrozenModel):
    """Opaque identity of one legal/reporting economic entity."""

    schema_version: Literal["1"]
    issuer_id: UUID7


class SecurityV1(FrozenModel):
    """Opaque identity of one economic claim or share class."""

    schema_version: Literal["1"]
    security_id: UUID7


class ListingV1(FrozenModel):
    """Opaque identity of one venue-specific trading admission."""

    schema_version: Literal["1"]
    listing_id: UUID7
    venue: ListingVenue


type IdentityV1 = IssuerV1 | SecurityV1 | ListingV1


class IdentityReferenceV1(FrozenModel):
    """Kind-safe reference to one Drift internal identity."""

    kind: IdentityKind
    internal_id: UUID7


def identity_reference(identity: IdentityV1) -> IdentityReferenceV1:
    """Return the typed reference corresponding to an identity object."""
    if isinstance(identity, IssuerV1):
        return IdentityReferenceV1(
            kind=IdentityKind.ISSUER, internal_id=identity.issuer_id
        )
    if isinstance(identity, SecurityV1):
        return IdentityReferenceV1(
            kind=IdentityKind.SECURITY, internal_id=identity.security_id
        )
    return IdentityReferenceV1(
        kind=IdentityKind.LISTING, internal_id=identity.listing_id
    )


class IdentityAssignmentEffect(StrEnum):
    """Business effect of an identity assignment assertion."""

    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


class IdentityAssignmentVersionV1(FrozenModel):
    """Immutable source-key to internal-identity assignment assertion."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    identity: IdentityV1
    source_namespace: NonBlankStr
    source_key: NonBlankStr
    assignment_effect: IdentityAssignmentEffect
    effective_interval: TemporalIntervalClaimV1


class IdentityResolutionClassification(StrEnum):
    """Outcome of resolving identity evidence without choosing a winner."""

    RESOLVED = "resolved"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class IdentityAssignmentSubjectV1(FrozenModel):
    """Exact source key and identity level requested by assignment resolution."""

    identity_kind: IdentityKind
    source_namespace: NonBlankStr
    source_key: NonBlankStr


class IdentityAssignmentResolutionResultV1(FrozenModel):
    """Hash-bound result of resolving one source key to internal identities."""

    schema_version: Literal["1"]
    subject: IdentityAssignmentSubjectV1
    assigned_identities: tuple[IdentityReferenceV1, ...]
    classification: IdentityResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1

    @model_validator(mode="after")
    def validate_identities(self) -> Self:
        expected = tuple(
            sorted(
                set(self.assigned_identities),
                key=lambda item: str(item.internal_id),
            )
        )
        if self.assigned_identities != expected:
            msg = "assigned identities must be sorted and unique"
            raise ValueError(msg)
        if any(item.kind is not self.subject.identity_kind for item in expected):
            msg = "assigned identity kinds must match the requested subject"
            raise ValueError(msg)
        return self


class IdentityRelationshipKind(StrEnum):
    """Closed set of relationships required by M1b identity correction."""

    ISSUER_HAS_SECURITY = "issuer_has_security"
    SECURITY_HAS_LISTING = "security_has_listing"
    EQUIVALENT_TO = "equivalent_to"
    DISTINCT_FROM = "distinct_from"
    SUCCESSOR_OF = "successor_of"
    REORGANIZED_FROM = "reorganized_from"


class ResolutionStatus(StrEnum):
    """Source-supported resolution status of a relationship assertion."""

    RESOLVED = "resolved"
    DISPUTED = "disputed"
    INDETERMINATE = "indeterminate"


class IdentityRelationshipVersionV1(FrozenModel):
    """Immutable correctable relationship between typed internal identities."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    left: IdentityReferenceV1
    right: IdentityReferenceV1
    relationship_kind: IdentityRelationshipKind
    resolution_status: ResolutionStatus
    effective_interval: TemporalIntervalClaimV1
    source_relationship_code: NonBlankStr | None

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        if self.left == self.right:
            msg = "identity relationship cannot be a self relation"
            raise ValueError(msg)
        pair = (self.left.kind, self.right.kind)
        expected: set[tuple[IdentityKind, IdentityKind]]
        if self.relationship_kind is IdentityRelationshipKind.ISSUER_HAS_SECURITY:
            expected = {(IdentityKind.ISSUER, IdentityKind.SECURITY)}
        elif self.relationship_kind is IdentityRelationshipKind.SECURITY_HAS_LISTING:
            expected = {(IdentityKind.SECURITY, IdentityKind.LISTING)}
        elif self.relationship_kind in {
            IdentityRelationshipKind.EQUIVALENT_TO,
            IdentityRelationshipKind.DISTINCT_FROM,
        }:
            expected = {(kind, kind) for kind in IdentityKind}
        else:
            expected = {
                (IdentityKind.ISSUER, IdentityKind.ISSUER),
                (IdentityKind.SECURITY, IdentityKind.SECURITY),
            }
        if pair not in expected:
            msg = "identity relationship endpoint kinds are invalid"
            raise ValueError(msg)
        return self


class IdentityResolutionResultV1(FrozenModel):
    """Manifest-bound equivalence-set resolution without identity mutation."""

    schema_version: Literal["1"]
    subject: IdentityReferenceV1
    resolved_identities: tuple[IdentityReferenceV1, ...]
    classification: IdentityResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    identity_bundle_hash: SHA256Hash
    resolution_mode: ResolutionMode
    knowledge_cutoff: UTCDateTime
    evaluation_time: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    considered_assertion_hashes: tuple[SHA256Hash, ...]
    selected_assertion_hashes: tuple[SHA256Hash, ...]
    selection_proof_hashes: tuple[SHA256Hash, ...]

    @model_validator(mode="after")
    def validate_resolved_identities(self) -> Self:
        ordered = tuple(
            sorted(
                set(self.resolved_identities), key=lambda item: str(item.internal_id)
            )
        )
        if self.resolved_identities != ordered:
            msg = "resolved identities must be sorted and unique"
            raise ValueError(msg)
        if any(item.kind is not self.subject.kind for item in ordered):
            msg = "resolved identities must match subject kind"
            raise ValueError(msg)
        return self
