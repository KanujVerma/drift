"""Historical issuer, security, listing, and relationship contracts."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.assertions import (
    M1bSelectionPurpose,
    ResolutionEvidenceV1,
    ResolutionMode,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.temporal import AvailabilityChannelV1
from drift.serialization.canonical import content_hash


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


class ExternalIdentifierKind(StrEnum):
    """Closed external identifier vocabulary for M1b mapping assertions."""

    TICKER = "ticker"
    CIK = "cik"
    CUSIP = "cusip"
    FIGI = "figi"
    PROVIDER = "provider"
    EXCHANGE_SYMBOL = "exchange_symbol"
    OTHER = "other"


class ExternalIdentifierNamespaceV1(FrozenModel):
    """Versioned authority namespace and its explicit identity target level."""

    kind: ExternalIdentifierKind
    scheme: NonBlankStr
    authority: NonBlankStr
    target_level: IdentityKind
    venue: ListingVenue | None

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        listing_scoped = {
            ExternalIdentifierKind.TICKER,
            ExternalIdentifierKind.EXCHANGE_SYMBOL,
        }
        if self.kind in listing_scoped:
            if self.target_level is not IdentityKind.LISTING:
                msg = "ticker and exchange-symbol namespaces must target listings"
                raise ValueError(msg)
            if self.venue is None:
                msg = "ticker and exchange-symbol namespaces require a venue"
                raise ValueError(msg)
        elif self.kind is ExternalIdentifierKind.CIK:
            if self.target_level is not IdentityKind.ISSUER:
                msg = "CIK namespaces must target issuers"
                raise ValueError(msg)
            if self.venue is not None:
                msg = "CIK namespaces forbid a venue"
                raise ValueError(msg)
        elif self.venue is not None:
            if not _is_versioned_listing_venue_scheme(self.scheme):
                msg = (
                    "only an explicit versioned listing-venue scheme may carry a venue"
                )
                raise ValueError(msg)
            if self.target_level is not IdentityKind.LISTING:
                msg = "listing-venue schemes must target listings"
                raise ValueError(msg)
        return self


def _is_versioned_listing_venue_scheme(scheme: str) -> bool:
    """Recognize an explicitly versioned scheme declaring listing-venue scope."""
    prefix, separator, version = scheme.rpartition("-v")
    return bool(separator and prefix.endswith("-listing-venue") and version.isdecimal())


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


class MappingStatus(StrEnum):
    """Source assertion state for one dated external identifier mapping."""

    ASSERTED = "asserted"
    AMBIGUOUS = "ambiguous"
    WITHDRAWN = "withdrawn"


class ExternalIdentifierMappingVersionV1(FrozenModel):
    """Immutable dated claim linking one external value to one typed identity."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    namespace: ExternalIdentifierNamespaceV1
    identifier_value: NonBlankStr
    target: IdentityReferenceV1
    mapping_status: MappingStatus
    effective_interval: TemporalIntervalClaimV1

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.target.kind is not self.namespace.target_level:
            msg = "mapping target kind must match namespace target level"
            raise ValueError(msg)
        if (
            self.namespace.kind is ExternalIdentifierKind.TICKER
            and self.identifier_value != self.identifier_value.upper()
        ):
            msg = "ticker mapping text must be exact uppercase text"
            raise ValueError(msg)
        return self


class RecordResolutionClassification(StrEnum):
    """Resolution outcome for dated external identifier records."""

    RESOLVED = "resolved"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class IssuerForm(StrEnum):
    """Source-mapped issuer form used by the initial eligibility contract."""

    OPERATING_COMPANY = "operating_company"
    FUND = "fund"
    REIT = "reit"
    TRUST = "trust"
    ACQUISITION_COMPANY = "acquisition_company"
    OTHER = "other"
    UNKNOWN = "unknown"


class InstrumentForm(StrEnum):
    """Source-mapped security form used by the initial eligibility contract."""

    COMMON_SHARE = "common_share"
    PREFERRED = "preferred"
    RECEIPT = "receipt"
    UNIT = "unit"
    WARRANT = "warrant"
    RIGHT = "right"
    OTHER = "other"
    UNKNOWN = "unknown"


class DomesticStatus(StrEnum):
    """Source-backed domestic status, never inferred from listing venue."""

    DOMESTIC = "domestic"
    FOREIGN = "foreign"
    INDETERMINATE = "indeterminate"


class ClassificationValueStatus(StrEnum):
    """Whether a source supplied a text value or explicitly left it unknown."""

    KNOWN = "known"
    UNKNOWN = "unknown"


class SourcedTextValueV1(FrozenModel):
    """A source-preserving text field with explicit unknown handling."""

    status: ClassificationValueStatus
    value: NonBlankStr | None

    @model_validator(mode="after")
    def validate_status_value(self) -> Self:
        if self.status is ClassificationValueStatus.KNOWN and self.value is None:
            msg = "known sourced text requires a value"
            raise ValueError(msg)
        if self.status is ClassificationValueStatus.UNKNOWN and self.value is not None:
            msg = "unknown sourced text forbids a value"
            raise ValueError(msg)
        return self


class SecurityClassificationVersionV1(FrozenModel):
    """Immutable sourced issuer/security classification assertion."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    issuer_id: UUID7
    security_id: UUID7
    issuer_form: IssuerForm
    issuer_domicile: SourcedTextValueV1
    incorporation_country: SourcedTextValueV1
    instrument_form: InstrumentForm
    share_class_label: SourcedTextValueV1
    domestic_status: DomesticStatus
    effective_interval: TemporalIntervalClaimV1
    source_taxonomy_id: NonBlankStr
    source_taxonomy_version: NonBlankStr
    source_fields: ImmutableJSON


class SecurityClassificationStatus(StrEnum):
    """Result of applying evidence to the initial classification scope."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


def security_classification_resolution_binding_hash(
    issuer_id: UUID7,
    security_id: UUID7,
    classification: SecurityClassificationStatus,
    reasons: tuple[NonBlankStr, ...],
    evidence: ResolutionEvidenceV1,
    dependent_identity_resolution_hashes: tuple[SHA256Hash, ...],
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...],
    selected_relationship_record_hashes: tuple[SHA256Hash, ...],
) -> SHA256Hash:
    """Bind a persisted classification outcome to all authorizing evidence."""
    return content_hash(
        {
            "issuer_id": issuer_id,
            "security_id": security_id,
            "classification": classification,
            "reasons": reasons,
            "evidence_hash": content_hash(evidence),
            "dependent_identity_resolution_hashes": (
                dependent_identity_resolution_hashes
            ),
            "dependent_relationship_proof_hashes": (
                dependent_relationship_proof_hashes
            ),
            "selected_relationship_record_hashes": (
                selected_relationship_record_hashes
            ),
        }
    )


class SecurityClassificationResolutionV1(FrozenModel):
    """Query-bound result for one issuer/security classification pair."""

    schema_version: Literal["1"]
    issuer_id: UUID7
    security_id: UUID7
    classification: SecurityClassificationStatus
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
    dependent_identity_resolution_hashes: tuple[SHA256Hash, ...]
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...]
    selected_relationship_record_hashes: tuple[SHA256Hash, ...]
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        query = self.evidence.normalized_query
        if (
            query.purpose is not M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY
            or query.subject_hash
            != content_hash(
                {"issuer_id": self.issuer_id, "security_id": self.security_id}
            )
        ):
            raise ValueError("classification result subject must bind structural query")
        if not self.evidence.selection_proof_hashes:
            raise ValueError("classification result requires its selection proof")
        for label, hashes in (
            ("identity resolution", self.dependent_identity_resolution_hashes),
            ("relationship proof", self.dependent_relationship_proof_hashes),
            ("relationship record", self.selected_relationship_record_hashes),
        ):
            if not hashes or hashes != tuple(sorted(set(hashes))):
                raise ValueError(
                    f"classification result requires canonical {label} hashes"
                )
        if set(self.dependent_relationship_proof_hashes) & set(
            self.evidence.selection_proof_hashes
        ):
            raise ValueError(
                "classification result requires canonical relationship proof hashes"
            )
        if (
            self.classification is not SecurityClassificationStatus.INDETERMINATE
            and not self.evidence.selected_record_hashes
        ):
            raise ValueError("definite classification requires selected records")
        if (
            self.classification is SecurityClassificationStatus.CONFLICT
            and len(self.evidence.selected_record_hashes) < 2
        ):
            raise ValueError(
                "classification conflict requires multiple selected records"
            )
        expected_binding = security_classification_resolution_binding_hash(
            self.issuer_id,
            self.security_id,
            self.classification,
            self.reasons,
            self.evidence,
            self.dependent_identity_resolution_hashes,
            self.dependent_relationship_proof_hashes,
            self.selected_relationship_record_hashes,
        )
        if self.outcome_binding_hash != expected_binding:
            raise ValueError("classification outcome binding hash mismatch")
        return self


class ListingRole(StrEnum):
    """Source methodology's role for a listing at a point in history."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    INDETERMINATE = "indeterminate"


class ListingRoleVersionV1(FrozenModel):
    """Immutable sourced primary-listing role assertion."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    security_id: UUID7
    listing_id: UUID7
    role: ListingRole
    methodology_id: NonBlankStr
    methodology_version: NonBlankStr
    effective_interval: TemporalIntervalClaimV1


class ListingLifecycleEventKind(StrEnum):
    """Non-terminal source events in one venue-specific listing history."""

    ADMITTED = "admitted"
    FIRST_REGULAR_TRADE = "first_regular_trade"
    SUSPENDED = "suspended"
    RESUMED = "resumed"
    VENUE_TRANSFER = "venue_transfer"


class ListingLifecycleVersionV1(FrozenModel):
    """Immutable sourced lifecycle event for one listing admission."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    listing_id: UUID7
    event_kind: ListingLifecycleEventKind
    effective_time: TemporalBoundaryClaimV1
    related_listing_id: UUID7 | None

    @model_validator(mode="after")
    def validate_related_listing(self) -> Self:
        if self.event_kind is ListingLifecycleEventKind.VENUE_TRANSFER:
            if self.related_listing_id is None:
                raise ValueError("venue transfer requires a related listing")
            if self.related_listing_id == self.listing_id:
                raise ValueError("venue transfer requires a distinct related listing")
        elif self.related_listing_id is not None:
            raise ValueError("only a venue transfer may name a related listing")
        return self


class ListingTerminationReason(StrEnum):
    """Broad source-preserving reason families for listing termination."""

    ACQUISITION = "acquisition"
    MERGER = "merger"
    BANKRUPTCY = "bankruptcy"
    EXCHANGE_DELISTING = "exchange_delisting"
    VOLUNTARY_WITHDRAWAL = "voluntary_withdrawal"
    VENUE_TRANSFER = "venue_transfer"
    REORGANIZATION = "reorganization"
    UNKNOWN = "unknown"


class OutcomeEvidenceStatus(StrEnum):
    """Completeness of separate future economic-outcome evidence."""

    KNOWN = "known"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ListingTerminationVersionV1(FrozenModel):
    """Sole immutable M1b authority that a listing terminated."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    listing_id: UUID7
    reason: ListingTerminationReason
    source_reason_code: NonBlankStr | None
    source_reason_text: NonBlankStr | None
    last_regular_trade_time: TemporalBoundaryClaimV1
    effective_time: TemporalBoundaryClaimV1
    successor_relationship_ids: tuple[UUID7, ...]
    outcome_evidence_status: OutcomeEvidenceStatus

    @model_validator(mode="after")
    def validate_successor_relationship_ids(self) -> Self:
        expected = tuple(sorted(set(self.successor_relationship_ids), key=str))
        if self.successor_relationship_ids != expected:
            raise ValueError("successor relationship ids must be sorted and unique")
        return self


class ListingHistoryCoverageStatus(StrEnum):
    """Source assertion about lifecycle and termination history coverage."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ListingHistoryCoverageVersionV1(FrozenModel):
    """Immutable coverage statement for one listing history."""

    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    listing_id: UUID7
    coverage_status: ListingHistoryCoverageStatus
    complete_through: TemporalBoundaryClaimV1


class ListingLifecycleStatus(StrEnum):
    """Point-in-time structural state of one venue-specific listing."""

    NOT_YET_LISTED = "not_yet_listed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    INDETERMINATE = "indeterminate"


class ListingTerminationStatus(StrEnum):
    """Point-in-time result from the sole termination authority."""

    TERMINATED = "terminated"
    NOT_TERMINATED = "not_terminated"
    INDETERMINATE = "indeterminate"


def listing_history_coverage_resolution_binding_hash(
    listing_id: UUID7,
    status: ListingHistoryCoverageStatus,
    complete_through: TemporalBoundaryClaimV1,
    reasons: tuple[NonBlankStr, ...],
    evidence: ResolutionEvidenceV1,
    selected_coverage_record_hash: SHA256Hash | None,
) -> SHA256Hash:
    """Bind one coverage outcome to its selected record and proof evidence."""
    return content_hash(
        {
            "listing_id": listing_id,
            "status": status,
            "complete_through": complete_through,
            "reasons": reasons,
            "evidence_hash": content_hash(evidence),
            "selected_coverage_record_hash": selected_coverage_record_hash,
        }
    )


class ListingHistoryCoverageResolutionV1(FrozenModel):
    """Query-bound listing-history coverage selected before termination."""

    schema_version: Literal["1"]
    listing_id: UUID7
    status: ListingHistoryCoverageStatus
    complete_through: TemporalBoundaryClaimV1
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
    selected_coverage_record_hash: SHA256Hash | None
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        query = self.evidence.normalized_query
        if (
            query.purpose is not M1bSelectionPurpose.LISTING_LIFECYCLE
            or query.subject_hash != content_hash({"listing_id": self.listing_id})
        ):
            raise ValueError("coverage result subject must bind lifecycle query")
        if not self.evidence.selection_proof_hashes:
            raise ValueError("coverage result requires its selection proof")
        if self.selected_coverage_record_hash is not None and (
            self.selected_coverage_record_hash
            not in self.evidence.selected_record_hashes
        ):
            raise ValueError("selected coverage record must be selected by proof")
        if (
            self.status is not ListingHistoryCoverageStatus.UNKNOWN
            and self.selected_coverage_record_hash is None
        ):
            raise ValueError("definite coverage requires a selected coverage record")
        expected = listing_history_coverage_resolution_binding_hash(
            self.listing_id,
            self.status,
            self.complete_through,
            self.reasons,
            self.evidence,
            self.selected_coverage_record_hash,
        )
        if self.outcome_binding_hash != expected:
            raise ValueError("coverage outcome binding hash mismatch")
        return self


def listing_termination_resolution_binding_hash(
    listing_id: UUID7,
    status: ListingTerminationStatus,
    selected_termination_version_id: UUID7 | None,
    reasons: tuple[NonBlankStr, ...],
    evidence: ResolutionEvidenceV1,
    coverage_resolution_hash: SHA256Hash,
    selected_termination_record_hash: SHA256Hash | None,
    dependent_relationship_resolution_hashes: tuple[SHA256Hash, ...],
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...],
    selected_successor_relationship_record_hashes: tuple[SHA256Hash, ...],
) -> SHA256Hash:
    """Bind a termination outcome to coverage and successor provenance."""
    return content_hash(
        {
            "listing_id": listing_id,
            "status": status,
            "selected_termination_version_id": selected_termination_version_id,
            "reasons": reasons,
            "evidence_hash": content_hash(evidence),
            "coverage_resolution_hash": coverage_resolution_hash,
            "selected_termination_record_hash": selected_termination_record_hash,
            "dependent_relationship_resolution_hashes": (
                dependent_relationship_resolution_hashes
            ),
            "dependent_relationship_proof_hashes": (
                dependent_relationship_proof_hashes
            ),
            "selected_successor_relationship_record_hashes": (
                selected_successor_relationship_record_hashes
            ),
        }
    )


class ListingTerminationResolutionV1(FrozenModel):
    """Coverage-gated, query-bound listing termination outcome."""

    schema_version: Literal["1"]
    listing_id: UUID7
    status: ListingTerminationStatus
    selected_termination_version_id: UUID7 | None
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
    coverage_resolution_hash: SHA256Hash
    selected_termination_record_hash: SHA256Hash | None
    dependent_relationship_resolution_hashes: tuple[SHA256Hash, ...]
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...]
    selected_successor_relationship_record_hashes: tuple[SHA256Hash, ...]
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        query = self.evidence.normalized_query
        if (
            query.purpose is not M1bSelectionPurpose.LISTING_TERMINATION
            or query.subject_hash != content_hash({"listing_id": self.listing_id})
        ):
            raise ValueError("termination result subject must bind termination query")
        if not self.evidence.selection_proof_hashes:
            raise ValueError("termination result requires its selection proof")
        if self.status is ListingTerminationStatus.TERMINATED:
            if (
                self.selected_termination_version_id is None
                or self.selected_termination_record_hash is None
                or self.selected_termination_record_hash
                not in self.evidence.selected_record_hashes
            ):
                raise ValueError(
                    "terminated result requires a selected termination version"
                )
        elif (
            self.selected_termination_version_id is not None
            or self.selected_termination_record_hash is not None
        ):
            raise ValueError(
                "non-terminated result cannot expose a termination version"
            )
        for label, hashes in (
            ("relationship resolution", self.dependent_relationship_resolution_hashes),
            ("relationship proof", self.dependent_relationship_proof_hashes),
            (
                "successor relationship record",
                self.selected_successor_relationship_record_hashes,
            ),
        ):
            if hashes != tuple(sorted(set(hashes))):
                raise ValueError(f"termination {label} hashes must be canonical")
        if self.selected_successor_relationship_record_hashes and (
            not self.dependent_relationship_resolution_hashes
            or not self.dependent_relationship_proof_hashes
        ):
            raise ValueError(
                "successor records require relationship resolution and proof"
            )
        expected = listing_termination_resolution_binding_hash(
            self.listing_id,
            self.status,
            self.selected_termination_version_id,
            self.reasons,
            self.evidence,
            self.coverage_resolution_hash,
            self.selected_termination_record_hash,
            self.dependent_relationship_resolution_hashes,
            self.dependent_relationship_proof_hashes,
            self.selected_successor_relationship_record_hashes,
        )
        if self.outcome_binding_hash != expected:
            raise ValueError("termination outcome binding hash mismatch")
        return self


def listing_lifecycle_resolution_binding_hash(
    listing_id: UUID7,
    status: ListingLifecycleStatus,
    selected_termination_version_id: UUID7 | None,
    termination_resolution_hash: SHA256Hash,
    reasons: tuple[NonBlankStr, ...],
    evidence: ResolutionEvidenceV1,
    dependent_relationship_resolution_hashes: tuple[SHA256Hash, ...],
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...],
    selected_transfer_relationship_record_hashes: tuple[SHA256Hash, ...],
) -> SHA256Hash:
    """Bind lifecycle state to event, termination, and transfer evidence."""
    return content_hash(
        {
            "listing_id": listing_id,
            "status": status,
            "selected_termination_version_id": selected_termination_version_id,
            "termination_resolution_hash": termination_resolution_hash,
            "reasons": reasons,
            "evidence_hash": content_hash(evidence),
            "dependent_relationship_resolution_hashes": (
                dependent_relationship_resolution_hashes
            ),
            "dependent_relationship_proof_hashes": (
                dependent_relationship_proof_hashes
            ),
            "selected_transfer_relationship_record_hashes": (
                selected_transfer_relationship_record_hashes
            ),
        }
    )


class ListingLifecycleResolutionV1(FrozenModel):
    """Query-bound state composed from lifecycle and termination evidence."""

    schema_version: Literal["1"]
    listing_id: UUID7
    status: ListingLifecycleStatus
    selected_termination_version_id: UUID7 | None
    termination_resolution_hash: SHA256Hash
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
    dependent_relationship_resolution_hashes: tuple[SHA256Hash, ...]
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...]
    selected_transfer_relationship_record_hashes: tuple[SHA256Hash, ...]
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        query = self.evidence.normalized_query
        if (
            query.purpose is not M1bSelectionPurpose.LISTING_LIFECYCLE
            or query.subject_hash != content_hash({"listing_id": self.listing_id})
        ):
            raise ValueError("lifecycle result subject must bind lifecycle query")
        if not self.evidence.selection_proof_hashes:
            raise ValueError("lifecycle result requires its selection proof")
        if self.status is ListingLifecycleStatus.TERMINATED:
            if self.selected_termination_version_id is None:
                raise ValueError(
                    "terminated lifecycle requires a selected termination version"
                )
        elif self.selected_termination_version_id is not None:
            raise ValueError(
                "non-terminated lifecycle cannot expose a termination version"
            )
        for label, hashes in (
            ("relationship resolution", self.dependent_relationship_resolution_hashes),
            ("relationship proof", self.dependent_relationship_proof_hashes),
            (
                "transfer relationship record",
                self.selected_transfer_relationship_record_hashes,
            ),
        ):
            if hashes != tuple(sorted(set(hashes))):
                raise ValueError(f"lifecycle {label} hashes must be canonical")
        if self.selected_transfer_relationship_record_hashes and (
            not self.dependent_relationship_resolution_hashes
            or not self.dependent_relationship_proof_hashes
        ):
            raise ValueError("transfer records require relationship proof")
        expected = listing_lifecycle_resolution_binding_hash(
            self.listing_id,
            self.status,
            self.selected_termination_version_id,
            self.termination_resolution_hash,
            self.reasons,
            self.evidence,
            self.dependent_relationship_resolution_hashes,
            self.dependent_relationship_proof_hashes,
            self.selected_transfer_relationship_record_hashes,
        )
        if self.outcome_binding_hash != expected:
            raise ValueError("lifecycle termination outcome binding hash mismatch")
        return self


def primary_listing_resolution_binding_hash(
    security_id: UUID7,
    methodology_id: NonBlankStr,
    listing_id: UUID7 | None,
    classification: RecordResolutionClassification,
    reasons: tuple[NonBlankStr, ...],
    evidence: ResolutionEvidenceV1,
    selected_role_record_hash: SHA256Hash | None,
    dependent_identity_resolution_hashes: tuple[SHA256Hash, ...],
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...],
    selected_relationship_record_hashes: tuple[SHA256Hash, ...],
) -> SHA256Hash:
    """Bind a persisted primary outcome to role and relationship evidence."""
    return content_hash(
        {
            "security_id": security_id,
            "methodology_id": methodology_id,
            "listing_id": listing_id,
            "classification": classification,
            "reasons": reasons,
            "evidence_hash": content_hash(evidence),
            "selected_role_record_hash": selected_role_record_hash,
            "dependent_identity_resolution_hashes": (
                dependent_identity_resolution_hashes
            ),
            "dependent_relationship_proof_hashes": (
                dependent_relationship_proof_hashes
            ),
            "selected_relationship_record_hashes": (
                selected_relationship_record_hashes
            ),
        }
    )


class PrimaryListingResolutionV1(FrozenModel):
    """Query-bound outcome for a selected primary-listing methodology."""

    schema_version: Literal["1"]
    security_id: UUID7
    methodology_id: NonBlankStr
    listing_id: UUID7 | None
    classification: RecordResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
    selected_role_record_hash: SHA256Hash | None
    dependent_identity_resolution_hashes: tuple[SHA256Hash, ...]
    dependent_relationship_proof_hashes: tuple[SHA256Hash, ...]
    selected_relationship_record_hashes: tuple[SHA256Hash, ...]
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_listing_shape(self) -> Self:
        query = self.evidence.normalized_query
        if (
            query.purpose is not M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY
            or query.subject_hash
            != content_hash(
                {"security_id": self.security_id, "methodology_id": self.methodology_id}
            )
        ):
            raise ValueError(
                "primary listing result subject must bind structural query"
            )
        if not self.evidence.selection_proof_hashes:
            raise ValueError("primary listing result requires its selection proof")
        for label, hashes in (
            ("identity resolution", self.dependent_identity_resolution_hashes),
            ("relationship proof", self.dependent_relationship_proof_hashes),
        ):
            if not hashes or hashes != tuple(sorted(set(hashes))):
                raise ValueError(
                    f"primary listing result requires canonical {label} hashes"
                )
        if self.selected_relationship_record_hashes != tuple(
            sorted(set(self.selected_relationship_record_hashes))
        ):
            raise ValueError("primary listing relationship hashes must be canonical")
        if set(self.dependent_relationship_proof_hashes) & set(
            self.evidence.selection_proof_hashes
        ):
            raise ValueError(
                "primary listing result requires canonical relationship proof hashes"
            )
        if self.classification is RecordResolutionClassification.RESOLVED and (
            self.listing_id is None
            or self.selected_role_record_hash is None
            or self.selected_role_record_hash
            not in self.evidence.selected_record_hashes
            or not self.selected_relationship_record_hashes
        ):
            msg = (
                "resolved primary listing requires bound role and relationship evidence"
            )
            raise ValueError(msg)
        if self.classification is not RecordResolutionClassification.RESOLVED and (
            self.listing_id is not None or self.selected_role_record_hash is not None
        ):
            msg = "unresolved primary listing cannot expose a listing id"
            raise ValueError(msg)
        expected_binding = primary_listing_resolution_binding_hash(
            self.security_id,
            self.methodology_id,
            self.listing_id,
            self.classification,
            self.reasons,
            self.evidence,
            self.selected_role_record_hash,
            self.dependent_identity_resolution_hashes,
            self.dependent_relationship_proof_hashes,
            self.selected_relationship_record_hashes,
        )
        if self.outcome_binding_hash != expected_binding:
            raise ValueError("primary listing outcome binding hash mismatch")
        return self


def external_identifier_resolution_binding_hash(
    namespace: ExternalIdentifierNamespaceV1,
    identifier_value: NonBlankStr,
    targets: tuple[IdentityReferenceV1, ...],
    classification: RecordResolutionClassification,
    reasons: tuple[NonBlankStr, ...],
    evidence: ResolutionEvidenceV1,
    target_assignment_proof_hashes: tuple[SHA256Hash, ...],
    target_lifecycle_proof_hashes: tuple[SHA256Hash, ...],
) -> SHA256Hash:
    """Bind one external-identifier outcome to every authorizing proof."""
    return content_hash(
        {
            "namespace": namespace,
            "identifier_value": identifier_value,
            "targets": targets,
            "classification": classification,
            "reasons": reasons,
            "evidence_hash": content_hash(evidence),
            "target_assignment_proof_hashes": target_assignment_proof_hashes,
            "target_lifecycle_proof_hashes": target_lifecycle_proof_hashes,
        }
    )


class ExternalIdentifierResolutionResultV1(FrozenModel):
    """Exact query-bound result of resolving one external identifier value."""

    schema_version: Literal["1"]
    namespace: ExternalIdentifierNamespaceV1
    identifier_value: NonBlankStr
    targets: tuple[IdentityReferenceV1, ...]
    classification: RecordResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
    target_assignment_proof_hashes: tuple[SHA256Hash, ...]
    target_lifecycle_proof_hashes: tuple[SHA256Hash, ...]
    outcome_binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        query = self.evidence.normalized_query
        if (
            query.purpose is not M1bSelectionPurpose.IDENTITY_RESOLUTION
            or query.subject_hash
            != content_hash(
                {"namespace": self.namespace, "identifier_value": self.identifier_value}
            )
        ):
            raise ValueError("external identifier result subject must bind query")
        if not self.evidence.selection_proof_hashes:
            raise ValueError("external identifier result requires its selection proof")
        ordered = tuple(
            sorted(set(self.targets), key=lambda item: str(item.internal_id))
        )
        if self.targets != ordered:
            msg = "external identifier targets must be sorted and unique"
            raise ValueError(msg)
        if any(item.kind is not self.namespace.target_level for item in ordered):
            msg = "external identifier targets must match namespace target level"
            raise ValueError(msg)
        if self.classification is RecordResolutionClassification.RESOLVED:
            if len(ordered) != 1:
                msg = "resolved external identifier result requires one target"
                raise ValueError(msg)
        elif self.classification is RecordResolutionClassification.CONFLICT:
            if len(ordered) < 2:
                msg = "conflicting external identifier result requires multiple targets"
                raise ValueError(msg)
        elif ordered:
            msg = "indeterminate external identifier result cannot expose targets"
            raise ValueError(msg)
        if not self.target_assignment_proof_hashes or (
            self.target_assignment_proof_hashes
            != tuple(sorted(set(self.target_assignment_proof_hashes)))
        ):
            msg = "target assignment proof hashes must be nonempty, sorted, and unique"
            raise ValueError(msg)
        if self.target_lifecycle_proof_hashes != tuple(
            sorted(set(self.target_lifecycle_proof_hashes))
        ):
            raise ValueError("target lifecycle proof hashes must be sorted and unique")
        if (
            ordered
            and self.namespace.target_level is IdentityKind.LISTING
            and not (self.target_lifecycle_proof_hashes)
        ):
            raise ValueError("listing targets require lifecycle proof hashes")
        expected = external_identifier_resolution_binding_hash(
            self.namespace,
            self.identifier_value,
            self.targets,
            self.classification,
            self.reasons,
            self.evidence,
            self.target_assignment_proof_hashes,
            self.target_lifecycle_proof_hashes,
        )
        if self.outcome_binding_hash != expected:
            raise ValueError("external identifier outcome binding hash mismatch")
        return self


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
