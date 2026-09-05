"""Shared, literal fixtures for M1c economic query contract tests."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal, get_args
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import assertion_version_payload, manifest_hash, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import FrozenModel
from drift.domain.dataset_validation import ValidationResult, ValidationRunContextV1
from drift.domain.datasets import TemporalCoverage
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicAssociationV1,
    EconomicComponentV1,
    EconomicOccurrenceV1,
    EconomicSourceKeyV1,
    EconomicUnitBasisV1,
    PositiveRatioV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
)
from drift.domain.economic_coverage import (
    DatasetBindingV1,
    EconomicCoverageVersionV1,
    EconomicInputRecordV1,
    EconomicSourceOwnerV1,
    EconomicSourceSelectionPolicyV1,
)
from drift.domain.economic_events import (
    CancelledActionV1,
    CorporateActionTermsVersionV1,
    DeliveredSettlementV1,
    EconomicEffectVersionV1,
    EconomicRecordV1,
    EconomicSettlementVersionV1,
    EffectPayloadV1,
    OccurredEffectV1,
    ResidualClaimV1,
    TermsPayloadV1,
    UnknownEffectV1,
)
from drift.domain.economic_queries import MarketDecisionQueryV1, MarketOutcomeQueryV1
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    AssertionEffectiveShape,
    AssertionTemporalContractV1,
    DatasetKind,
    DatasetManifestV2,
    DatasetRoleV1,
    EvidenceGranularity,
    FieldDescriptorV1,
    LicenseDescriptorV1,
    LogicalType,
    PartitionDescriptorV1,
    SchemaDescriptorV1,
    SourceDescriptorV1,
    TemporalContractBindingV2,
    TemporalContractKindV2,
)
from drift.domain.revisions import RevisionKind
from drift.domain.securities import (
    IdentityAssignmentEffect,
    IdentityAssignmentVersionV1,
    SecurityV1,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.markets.economic_validation import (
    ECONOMIC_VALIDATION_PROFILE_ID,
    EconomicDatasetInput,
    EconomicIdentityInput,
    EconomicResolutionContext,
    economic_context_hash,
    economic_role_contract,
    economic_role_schema,
    economic_validation_profile_hash,
    economic_validator_implementation_hash,
    validate_economic_dataset,
)
from drift.markets.validation import validate_identity_dataset
from drift.serialization.canonical import canonical_json, content_hash

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def uid(suffix: int) -> UUID:
    """Return a fixed UUIDv7, derived only from a fixture suffix."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def _stable_suffix(label: str) -> int:
    return int(sha256(label.encode()).hexdigest()[:12], 16) % 1_000_000_000_000


def instant(day: int) -> datetime:
    """Return an aware UTC instant in the hand-checked fixture window."""
    return datetime(2026, 1, day, 12, tzinfo=UTC)


def public_channel() -> AvailabilityChannelV1:
    """Return the fixed channel used by market-query fixtures."""
    return AvailabilityChannelV1(
        kind=ChannelKind.PUBLIC,
        identifier="issuer-filings",
        version="v1",
    )


def cash_component(amount: str = "5", component_id: str = "cash") -> CashComponentV1:
    """Return a literal source-reported cash component for projection tests."""
    return CashComponentV1(
        kind="cash",
        component_id=component_id,
        amount=amount,
        currency_namespace="ISO-4217",
        currency_code="USD",
        unit_basis=EconomicUnitBasisV1(
            security_id=uid(21),
            denominator=PositiveRatioV1(numerator="1", denominator="1"),
            share_basis="predecessor_pre_action",
        ),
        amount_basis="gross",
        applicability="ordinary_passive_holder",
        conditions=(),
    )


def parse_utc(value: str) -> datetime:
    """Parse a fixed source instant independently of production evaluators."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def economic_evidence(
    statement: str,
) -> tuple[ArtifactReference, VerifiedArtifactBytes]:
    """Build a real content-addressed synthetic source statement and its bytes."""
    data = canonical_json(
        {"schema_version": "1", "synthetic_source_statement": statement}
    )
    digest = sha256(data).hexdigest()
    artifact_suffix = int(digest[:12], 16) % 1_000_000_000_000
    reference = ArtifactReference(
        artifact_id=uid(artifact_suffix),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"synthetic-economic://source/{quote(statement, safe='')}",
    )
    return reference, VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=digest
    )


def economic_methodology(
    methodology_version: str = "synthetic-economic-occurrence-v1",
) -> tuple[ArtifactReference, VerifiedArtifactBytes]:
    """Build the exact independent synthetic M1c methodology profile bytes."""
    data = canonical_json(
        {
            "schema_version": "1",
            "kind": "drift_economic_coverage_methodology",
            "methodology_version": methodology_version,
            "omission_detection": "closed_artifact_and_record_inventory",
            "revision_tracking": "source_sequence_and_supersession",
            "occurrence_identification": "stable_economic_occurrence_id",
        }
    )
    digest = sha256(data).hexdigest()
    reference = ArtifactReference(
        artifact_id=uid(_stable_suffix(f"methodology:{digest}")),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"synthetic-economic://methodology/{quote(data.decode(), safe='')}",
    )
    return reference, VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=digest
    )


def support_bytes(reference: ArtifactReference) -> VerifiedArtifactBytes:
    """Reconstruct and verify bytes encoded by a synthetic economic reference."""
    parsed = urlsplit(reference.location)
    if parsed.scheme != "synthetic-economic" or parsed.netloc not in {
        "source",
        "methodology",
    }:
        raise ValueError("fixture requires a synthetic economic evidence locator")
    statement = unquote(parsed.path.removeprefix("/"))
    reconstructed_reference, verified = (
        economic_evidence(statement)
        if parsed.netloc == "source"
        else economic_methodology(
            __import__("json").loads(statement)["methodology_version"]
        )
    )
    if reconstructed_reference.content_hash != reference.content_hash:
        raise ValueError("synthetic economic evidence digest mismatch")
    return verified


def exact_boundary(
    value: str, evidence_reference: ArtifactReference
) -> TemporalBoundaryClaimV1:
    """Build a source-exact second boundary using real synthetic evidence."""
    instant_value = parse_utc(value)
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=instant_value,
        upper_bound=instant_value,
        source_precision=SourcePrecision.SECOND,
        source_time_label=value,
        source_timezone=None,
        evidence_reference=evidence_reference,
    )


def bounded_boundary(
    lower: str, upper: str, evidence_reference: ArtifactReference
) -> TemporalBoundaryClaimV1:
    """Build an interval-precision boundary using real synthetic evidence."""
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=parse_utc(lower),
        upper_bound=parse_utc(upper),
        source_precision=SourcePrecision.INTERVAL,
        source_time_label=f"{lower}/{upper}",
        source_timezone=None,
        evidence_reference=evidence_reference,
    )


def public_availability(
    value: str, evidence_reference: ArtifactReference
) -> AvailabilityEvidenceV1:
    """Build exact public availability backed by the actual source bytes."""
    instant_value = parse_utc(value)
    return AvailabilityEvidenceV1(
        channel=public_channel(),
        shape=AvailabilityShape.EXACT,
        lower_bound=instant_value,
        upper_bound=instant_value,
        precision=SourcePrecision.SECOND,
        source_time_label=value,
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=evidence_reference,
    )


def revision(
    suffix: int, known_at: str, source_artifact: ArtifactReference
) -> RevisionEnvelopeV1:
    """Build one initial source revision with evidence at its actual known instant."""
    return RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=uid(suffix),
        record_version_id=uid(suffix + 1_000_000),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(public_availability(known_at, source_artifact),),
        history_completeness=HistoryCompleteness.COMPLETE,
        source_native_revision_label=None,
        source_artifact=source_artifact,
        payload_hash=HASH_A,
    )


def seal_record[T: FrozenModel](model: type[T], values: dict[str, object]) -> T:
    """Compute an assertion hash over the final self-excluding test fixture."""
    provisional = model.model_construct(**values)  # type: ignore[arg-type]
    source_revision = values["revision"]
    if not isinstance(source_revision, RevisionEnvelopeV1):
        raise TypeError("fixture requires a real revision envelope")
    corrected_revision = source_revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return model.model_validate({**values, "revision": corrected_revision})


def _record_source_semantics[T: EconomicRecordV1](
    model: type[T], values: dict[str, object]
) -> dict[str, object]:
    del model
    revision_value = values["revision"]
    source_key_value = values["source_key"]
    occurrence_value = values["occurrence"]
    if not isinstance(revision_value, RevisionEnvelopeV1):
        raise TypeError("fixture requires a real revision envelope")
    if not isinstance(source_key_value, EconomicSourceKeyV1):
        raise TypeError("fixture requires a real economic source key")
    if not isinstance(occurrence_value, EconomicOccurrenceV1):
        raise TypeError("fixture requires a real economic occurrence")
    semantics = _acyclic_source_semantics(values)
    if not isinstance(semantics, dict):
        raise TypeError("economic source semantics require an object")
    return semantics


def _coverage_source_semantics(
    values: dict[str, object],
) -> dict[str, object]:
    """Project every coverage assertion field without evidence-reference cycles."""
    revision_value = values["revision"]
    source_key_value = values["source_key"]
    if not isinstance(revision_value, RevisionEnvelopeV1):
        raise TypeError("coverage fixture requires a real revision envelope")
    if not isinstance(source_key_value, EconomicSourceKeyV1):
        raise TypeError("coverage fixture requires a real economic source key")
    semantics = _acyclic_source_semantics(values)
    if not isinstance(semantics, dict):
        raise TypeError("coverage source semantics require an object")
    return semantics


def _acyclic_source_semantics(value: object) -> object:
    """Project every model field while replacing evidence identities by presence."""
    if isinstance(value, ArtifactReference):
        return {"present": True}
    if isinstance(value, BaseModel):
        projected: dict[str, object] = {}
        for field_name, field_info in type(value).model_fields.items():
            if isinstance(value, RevisionEnvelopeV1) and field_name == "payload_hash":
                continue
            field_value = getattr(value, field_name)
            if _contains_artifact_reference(field_info.annotation):
                projected[field_name] = {"present": field_value is not None}
            else:
                projected[field_name] = _acyclic_source_semantics(field_value)
        return projected
    if isinstance(value, Mapping):
        return {key: _acyclic_source_semantics(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return tuple(_acyclic_source_semantics(item) for item in value)
    return value


def _contains_artifact_reference(annotation: object) -> bool:
    if annotation is ArtifactReference:
        return True
    return any(_contains_artifact_reference(item) for item in get_args(annotation))


def _rebind_boundary(
    boundary: TemporalBoundaryClaimV1, reference: ArtifactReference
) -> TemporalBoundaryClaimV1:
    if boundary.evidence_reference is None:
        return boundary
    return boundary.model_copy(update={"evidence_reference": reference})


def _rebind_component(
    component: EconomicComponentV1, reference: ArtifactReference
) -> EconomicComponentV1:
    if isinstance(component, ShareComponentV1):
        fraction = component.fraction_treatment
        if fraction.kind != "unknown":
            fraction = fraction.model_copy(update={"evidence_reference": reference})
        return component.model_copy(update={"fraction_treatment": fraction})
    if isinstance(component, UnsupportedPropertyComponentV1):
        return component.model_copy(update={"evidence_reference": reference})
    return component


def _rebind_residual(
    residual: ResidualClaimV1, reference: ArtifactReference
) -> ResidualClaimV1:
    if residual.evidence_reference is None:
        return residual
    return residual.model_copy(update={"evidence_reference": reference})


def _rebind_payload(payload: object, reference: ArtifactReference) -> object:
    if payload is None:
        return None
    if isinstance(payload, TermsPayloadV1):
        dates = tuple(
            date.model_copy(
                update={
                    "boundary": _rebind_boundary(date.boundary, reference),
                    "rule_reference": reference
                    if date.rule_reference is not None
                    else None,
                }
            )
            for date in payload.dates
        )
        return payload.model_copy(
            update={
                "components": tuple(
                    _rebind_component(item, reference) for item in payload.components
                ),
                "dates": dates,
            }
        )
    if isinstance(payload, OccurredEffectV1):
        return payload.model_copy(
            update={
                "owed_components": tuple(
                    _rebind_component(item, reference)
                    for item in payload.owed_components
                ),
                "residual": _rebind_residual(payload.residual, reference),
                "evidence_reference": reference,
            }
        )
    if isinstance(payload, CancelledActionV1):
        return payload.model_copy(update={"evidence_reference": reference})
    if isinstance(payload, DeliveredSettlementV1):
        return payload.model_copy(
            update={
                "delivered_components": tuple(
                    _rebind_component(item, reference)
                    for item in payload.delivered_components
                ),
                "residual": _rebind_residual(payload.residual, reference),
                "evidence_reference": reference,
            }
        )
    if isinstance(payload, UnknownEffectV1):
        return payload
    raise TypeError("unsupported economic fixture payload")


def rebind_record_evidence[T: EconomicRecordV1](
    model: type[T], values: dict[str, object]
) -> T:
    """Bind final semantic fixture values to an acyclic raw source statement."""
    statement = canonical_json(_record_source_semantics(model, values)).decode()
    reference, _ = economic_evidence(statement)
    revision_value = values["revision"]
    occurrence_value = values["occurrence"]
    if not isinstance(revision_value, RevisionEnvelopeV1):
        raise TypeError("fixture requires a real revision envelope")
    if not isinstance(occurrence_value, EconomicOccurrenceV1):
        raise TypeError("fixture requires a real economic occurrence")
    revision_value = revision_value.model_copy(
        update={
            "availability": tuple(
                evidence.model_copy(update={"evidence_reference": reference})
                for evidence in revision_value.availability
            ),
            "source_artifact": reference,
        }
    )
    if occurrence_value.kind == "identified":
        occurrence_value = occurrence_value.model_copy(
            update={"evidence_reference": reference}
        )
    rebound = dict(values)
    rebound["revision"] = revision_value
    rebound["occurrence"] = occurrence_value
    rebound["payload"] = _rebind_payload(values["payload"], reference)
    for field in ("scheduled_effect_time", "effective_time", "settled_time"):
        boundary = rebound.get(field)
        if isinstance(boundary, TemporalBoundaryClaimV1):
            rebound[field] = _rebind_boundary(boundary, reference)
    return seal_record(model, rebound)


def rebind_coverage_evidence(
    values: dict[str, object],
) -> EconomicCoverageVersionV1:
    """Bind a coverage assertion and its methodology to final acyclic source bytes."""
    methodology_version = values.get("methodology_version")
    if not isinstance(methodology_version, str):
        raise TypeError("coverage fixture requires a methodology version")
    methodology, _ = economic_methodology(methodology_version)
    rebound = dict(values)
    rebound["methodology_reference"] = methodology
    source_statement = canonical_json(
        {"kind": "coverage_assertion", "coverage": _coverage_source_semantics(rebound)}
    ).decode()
    reference, _ = economic_evidence(source_statement)
    revision_value = rebound["revision"]
    interval_value = rebound["coverage_interval"]
    if not isinstance(revision_value, RevisionEnvelopeV1):
        raise TypeError("coverage fixture requires a real revision envelope")
    if not isinstance(interval_value, TemporalIntervalClaimV1):
        raise TypeError("coverage fixture requires a temporal interval")
    rebound["revision"] = revision_value.model_copy(
        update={
            "availability": tuple(
                evidence.model_copy(update={"evidence_reference": reference})
                if evidence.evidence_reference is not None
                else evidence
                for evidence in revision_value.availability
            ),
            "source_artifact": reference,
        }
    )
    rebound["coverage_interval"] = interval_value.model_copy(
        update={
            "start": _rebind_boundary(interval_value.start, reference),
            "end": None
            if interval_value.end is None
            else _rebind_boundary(interval_value.end, reference),
        }
    )
    return seal_record(EconomicCoverageVersionV1, rebound)


def _unknown_association() -> EconomicAssociationV1:
    return EconomicAssociationV1(kind="unknown", reason="source did not name a parent")


def _unknown_occurrence() -> EconomicOccurrenceV1:
    return EconomicOccurrenceV1(kind="unknown", reason="source did not name occurrence")


def _unknown_residual() -> ResidualClaimV1:
    return ResidualClaimV1(kind="unknown", reason="source did not address residual")


def terms_record(
    suffix: int,
    action_kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
    known_at: str = "2020-05-01T00:00:00Z",
    scheduled_at: str = "2020-06-01T00:00:00Z",
) -> CorporateActionTermsVersionV1:
    """Build one fixed synthetic source terms report."""
    statement = f"terms report-{suffix} announces {action_kind.value} amount 5"
    evidence, _ = economic_evidence(statement)
    return rebind_record_evidence(
        CorporateActionTermsVersionV1,
        {
            "schema_version": "1",
            "revision": revision(suffix, known_at, evidence),
            "source_key": EconomicSourceKeyV1(
                source_id="synthetic-a",
                family="terms",
                native_record_id=f"report-{suffix}",
            ),
            "security_id": uid(21),
            "listing_id": None,
            "occurrence": _unknown_occurrence(),
            "source_action_code": action_kind.value,
            "scheduled_effect_time": exact_boundary(scheduled_at, evidence),
            "payload": TermsPayloadV1(
                kind="fixed",
                action_kind=action_kind,
                components=(cash_component(),),
                dates=(),
                conditions=(),
                reason=None,
            ),
        },
    )


def effect_record(
    suffix: int,
    kind: Literal["occurred", "cancelled_action", "unknown"] = "occurred",
    claim_status: Literal[
        "continuing", "converted", "extinguished", "unknown"
    ] = "continuing",
    effective_at: str = "2020-06-01T00:00:00Z",
    known_at: str | None = None,
) -> EconomicEffectVersionV1:
    """Build one source effect known at the effect instant by default."""
    known = effective_at if known_at is None else known_at
    statement = (
        f"effect report-{suffix} records {kind} "
        f"{ActionKind.REGULAR_CASH_DIVIDEND.value} amount 5"
    )
    evidence, _ = economic_evidence(statement)
    payload: EffectPayloadV1
    if kind == "occurred":
        payload = OccurredEffectV1(
            kind="occurred",
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            claim_status=claim_status,
            consideration_status="components",
            owed_components=(cash_component(),),
            residual=_unknown_residual(),
            evidence_reference=evidence,
        )
        occurrence = EconomicOccurrenceV1(
            kind="identified",
            native_occurrence_id=f"effect-{suffix}",
            evidence_reference=evidence,
        )
    elif kind == "cancelled_action":
        payload = CancelledActionV1(
            kind="cancelled_action",
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            reason="source cancelled the proposed action",
            evidence_reference=evidence,
        )
        occurrence = _unknown_occurrence()
    else:
        payload = UnknownEffectV1(
            kind="unknown",
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            reason="source did not establish occurrence",
        )
        occurrence = _unknown_occurrence()
    return rebind_record_evidence(
        EconomicEffectVersionV1,
        {
            "schema_version": "1",
            "revision": revision(suffix, known, evidence),
            "source_key": EconomicSourceKeyV1(
                source_id="synthetic-a",
                family="effect",
                native_record_id=f"report-{suffix}",
            ),
            "security_id": uid(21),
            "listing_id": None,
            "occurrence": occurrence,
            "source_action_code": kind,
            "effective_time": exact_boundary(effective_at, evidence),
            "terms_association": _unknown_association(),
            "payload": payload,
        },
    )


def settlement_record(
    suffix: int,
    amount: str = "5",
    occurrence_id: str | None = "payment-1",
    settled_at: str = "2020-06-15T00:00:00Z",
    known_at: str | None = None,
) -> EconomicSettlementVersionV1:
    """Build one delivery known at its settlement instant by default."""
    known = settled_at if known_at is None else known_at
    statement = (
        f"settlement report-{suffix} delivered "
        f"{ActionKind.REGULAR_CASH_DIVIDEND.value} amount {amount}"
    )
    evidence, _ = economic_evidence(statement)
    occurrence = (
        EconomicOccurrenceV1(
            kind="identified",
            native_occurrence_id=occurrence_id,
            evidence_reference=evidence,
        )
        if occurrence_id is not None
        else _unknown_occurrence()
    )
    return rebind_record_evidence(
        EconomicSettlementVersionV1,
        {
            "schema_version": "1",
            "revision": revision(suffix, known, evidence),
            "source_key": EconomicSourceKeyV1(
                source_id="synthetic-a",
                family="settlement",
                native_record_id=f"report-{suffix}",
            ),
            "security_id": uid(21),
            "listing_id": None,
            "occurrence": occurrence,
            "source_action_code": "cash-delivery",
            "settled_time": exact_boundary(settled_at, evidence),
            "terms_association": _unknown_association(),
            "effect_association": _unknown_association(),
            "payload": DeliveredSettlementV1(
                kind="delivered",
                action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
                delivered_components=(
                    cash_component(amount=amount, component_id="cash"),
                ),
                residual=_unknown_residual(),
                evidence_reference=evidence,
            ),
        },
    )


def revise_record[T: EconomicRecordV1](
    record: T, suffix: int, known_at: str, changes: dict[str, object]
) -> T:
    """Build a correction retaining source report and logical identities."""
    statement = (
        f"correction {suffix} to {record.source_key.native_record_id} "
        f"changes {','.join(sorted(changes))}"
    )
    evidence, _ = economic_evidence(statement)
    corrected_revision = RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=record.revision.logical_record_id,
        record_version_id=uid(suffix + 1_000_000),
        revision_kind=RevisionKind.CORRECTION,
        supersedes_record_version_id=record.revision.record_version_id,
        source_sequence=record.revision.source_sequence + 1,
        availability=(public_availability(known_at, evidence),),
        history_completeness=record.revision.history_completeness,
        source_native_revision_label=f"correction-{suffix}",
        source_artifact=evidence,
        payload_hash=HASH_A,
    )
    values = {field: getattr(record, field) for field in type(record).model_fields}
    values.update(changes)
    values["revision"] = corrected_revision
    return rebind_record_evidence(type(record), values)


def coverage_inventory_hashes(suffix: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return independently hash-addressed retained inventory identities."""
    artifact_hashes = tuple(
        sorted(
            economic_evidence(f"coverage {suffix} retained artifact {index}")[
                0
            ].content_hash
            for index in (1, 2)
        )
    )
    record_hashes = tuple(
        sorted(
            economic_evidence(f"coverage {suffix} retained record {index}")[
                0
            ].content_hash
            for index in (1, 2)
        )
    )
    return artifact_hashes, record_hashes


def coverage_record(
    suffix: int,
    family: Literal["terms", "effect", "settlement"],
    target_manifest_hash: str,
    inventory_artifact_hashes: tuple[str, ...],
    inventory_record_hashes: tuple[str, ...],
    completeness: Literal["complete", "partial", "unknown"] = "complete",
    *,
    action_kinds: tuple[ActionKind, ...] = tuple(ActionKind),
    revision_support: Literal["captured_history", "current_only", "unknown"] = (
        "captured_history"
    ),
    occurrence_key_semantics: Literal[
        "economic_occurrence_ids", "report_ids_only", "unknown"
    ] = "economic_occurrence_ids",
    snapshot_at: str = "2021-01-02T00:00:00Z",
    security_id: UUID | None = None,
    listing_id: UUID | None = None,
    availability: tuple[AvailabilityEvidenceV1, ...] | None = None,
    source_id: str = "synthetic-a",
    coverage_start: str = "2020-01-01T00:00:00Z",
    coverage_end: str = "2021-01-02T00:00:00Z",
) -> EconomicCoverageVersionV1:
    """Build a hash-addressed synthetic coverage declaration with final claims."""
    snapshot = parse_utc(snapshot_at)
    placeholder, _ = economic_evidence("coverage fixture placeholder")
    interval = TemporalIntervalClaimV1(
        schema_version="1",
        start=exact_boundary(coverage_start, placeholder),
        end=exact_boundary(coverage_end, placeholder),
    )
    revision_value = revision(suffix, snapshot_at, placeholder)
    if availability is not None:
        revision_value = revision_value.model_copy(
            update={"availability": availability}
        )
    return rebind_coverage_evidence(
        {
            "schema_version": "1",
            "revision": revision_value,
            "source_key": EconomicSourceKeyV1(
                source_id=source_id,
                family="coverage",
                native_record_id=f"coverage-{suffix}",
            ),
            "security_id": uid(21) if security_id is None else security_id,
            "listing_id": listing_id,
            "coverage_interval": interval,
            "fact_family": family,
            "action_kinds": action_kinds,
            "target_manifest_hash": target_manifest_hash,
            "inventory_artifact_hashes": inventory_artifact_hashes,
            "inventory_record_hashes": inventory_record_hashes,
            "methodology_reference": placeholder,
            "methodology_version": "synthetic-economic-occurrence-v1",
            "snapshot_at": snapshot,
            "completeness": completeness,
            "revision_support": revision_support,
            "occurrence_key_semantics": occurrence_key_semantics,
            "gaps": (),
            "exceptions": (),
        }
    )


def correct_coverage(
    record: EconomicCoverageVersionV1,
    suffix: int,
    known_at: str,
    changes: dict[str, object] | None = None,
) -> EconomicCoverageVersionV1:
    """Build an immutable correction with new hash-addressed source bytes."""
    placeholder, _ = economic_evidence("coverage correction placeholder")
    corrected_revision = RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=record.revision.logical_record_id,
        record_version_id=uid(suffix + 1_000_000),
        revision_kind=RevisionKind.CORRECTION,
        supersedes_record_version_id=record.revision.record_version_id,
        source_sequence=record.revision.source_sequence + 1,
        availability=(public_availability(known_at, placeholder),),
        history_completeness=record.revision.history_completeness,
        source_native_revision_label=f"correction-{suffix}",
        source_artifact=placeholder,
        payload_hash=HASH_A,
    )
    values = {field: getattr(record, field) for field in type(record).model_fields}
    if changes is not None:
        values.update(changes)
    values["revision"] = corrected_revision
    return rebind_coverage_evidence(values)


def source_policy(
    security_id: UUID,
    bindings: tuple[DatasetBindingV1, ...],
    owners: tuple[EconomicSourceOwnerV1, ...],
    history_start: datetime,
    through: datetime,
) -> EconomicSourceSelectionPolicyV1:
    """Build the literal bounded source-policy fixture shape."""
    return EconomicSourceSelectionPolicyV1(
        schema_version="1",
        policy_id="synthetic-economic-policy",
        policy_version="1",
        security_id=security_id,
        action_kinds=tuple(ActionKind),
        scope="all_security_occurrences",
        history_start=history_start,
        through=through,
        owners=owners,
        input_dataset_bindings=bindings,
    )


def economic_dataset(
    role: str,
    records: tuple[EconomicInputRecordV1, ...],
    source_id: str = "synthetic-a",
) -> EconomicDatasetInput:
    """Build and validate one exact-byte synthetic M1c role dataset."""
    data = canonical_json({"schema_version": "1", "records": records})
    digest = sha256(data).hexdigest()
    schema = economic_role_schema(role)
    now = parse_utc("2026-09-05T12:00:00Z")
    source_reference, _ = economic_evidence(
        f"manifest source evidence for {source_id} {role}"
    )
    acquisition_reference, _ = economic_evidence(
        f"manifest acquisition evidence for {source_id} {role}"
    )
    license_reference, _ = economic_evidence(
        f"manifest license evidence for {source_id} {role}"
    )
    role_suffix = _stable_suffix(f"{source_id}:{role}")
    partition_reference = ArtifactReference(
        artifact_id=uid(_stable_suffix(f"partition:{source_id}:{role}")),
        kind=ArtifactKind.DATASET,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )
    manifest = DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uid(role_suffix),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(namespace="drift", name=role, version="1"),
        created_at=now,
        source=SourceDescriptorV1(
            source_id=source_id,
            publisher="Drift",
            product="M1c synthetic fixture",
            evidence_reference=source_reference,
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=now,
            collector_id="economic-test-support",
            collector_version="1",
            evidence_reference=acquisition_reference,
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=now,
            terms_evidence_reference=license_reference,
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=uid(_stable_suffix(f"descriptor:{source_id}:{role}")),
                partition_key="all",
                artifact=partition_reference,
                byte_size=len(data),
                media_type="application/json",
                format_version="1",
                row_count=len(records),
                schema_hash=schema.schema_hash,
                coverage=TemporalCoverage(started_at=now, ended_at=now),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=economic_role_contract(role, (public_channel(),)),
        ),
        lineage=None,
    )
    verified = VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=digest,
    )
    run = ValidationRunContextV1(
        decision_id=uid(_stable_suffix(f"decision:{source_id}:{role}:{digest}")),
        validator_version="1",
        validator_implementation_hash=economic_validator_implementation_hash(),
        validation_profile_id=ECONOMIC_VALIDATION_PROFILE_ID,
        validation_profile_hash=economic_validation_profile_hash(),
        checked_at=now,
    )
    decision, parsed = validate_economic_dataset(manifest, (verified,), run)
    bundle = build_validated_dataset_bundle(
        bundle_id=uid(_stable_suffix(f"bundle:{source_id}:{role}:{digest}")),
        bundle_version="1",
        created_at=now,
        validated_datasets=((manifest, decision),),
    )
    return EconomicDatasetInput(
        records=parsed,
        manifest=manifest,
        decision=decision,
        verified_artifacts=(verified,),
        validation_run=run,
        bundle=bundle,
    )


def _identity_assignment(suffix: int, security_id: int) -> IdentityAssignmentVersionV1:
    evidence, _ = economic_evidence(f"identity assignment for security {security_id}")
    revision_value = revision(suffix, "2020-01-01T00:00:00Z", evidence)
    record = IdentityAssignmentVersionV1(
        schema_version="1",
        revision=revision_value,
        identity=SecurityV1(schema_version="1", security_id=uid(security_id)),
        source_namespace="synthetic-master",
        source_key=f"security-{security_id}",
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
        effective_interval=TemporalIntervalClaimV1(
            schema_version="1",
            start=exact_boundary("2020-01-01T00:00:00Z", evidence),
            end=None,
        ),
    )
    return record.model_copy(
        update={
            "revision": revision_value.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(record))}
            )
        }
    )


def history_assignments() -> tuple[IdentityAssignmentVersionV1, ...]:
    """Return fresh synthetic assigned security and recipient identities."""
    return (_identity_assignment(2100, 21), _identity_assignment(2200, 22))


def identity_input(
    assignments: tuple[IdentityAssignmentVersionV1, ...],
) -> EconomicIdentityInput:
    """Build exact identity bytes, decision, and bundle for an M1c context."""
    field_types = {
        "revision.logical_record_id": (LogicalType.STRING, False),
        "revision.record_version_id": (LogicalType.STRING, False),
        "revision.revision_kind": (LogicalType.STRING, False),
        "revision.supersedes_record_version_id": (LogicalType.STRING, True),
        "revision.source_sequence": (LogicalType.INTEGER, False),
        "revision.availability": (LogicalType.JSON, False),
        "revision.source_artifact": (LogicalType.JSON, False),
        "revision.payload_hash": (LogicalType.STRING, False),
        "effective_interval": (LogicalType.JSON, False),
        "assignment_effect": (LogicalType.STRING, False),
    }
    fields = tuple(
        sorted(
            (
                FieldDescriptorV1(
                    field_id=field_id,
                    name=field_id,
                    logical_type=logical_type,
                    nullable=nullable,
                )
                for field_id, (logical_type, nullable) in field_types.items()
            ),
            key=lambda item: item.field_id,
        )
    )
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=fields, schema_hash=HASH_A
    )
    schema = SchemaDescriptorV1(
        schema_version="1", fields=fields, schema_hash=schema_hash(provisional)
    )
    data = canonical_json({"schema_version": "1", "records": assignments})
    digest = sha256(data).hexdigest()
    now = parse_utc("2026-09-05T12:00:00Z")
    source_reference, _ = economic_evidence("identity manifest source")
    acquisition_reference, _ = economic_evidence("identity manifest acquisition")
    license_reference, _ = economic_evidence("identity manifest license")
    manifest = DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uid(_stable_suffix(f"identity:{digest}")),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(
            namespace="drift", name="identity_assignment", version="1"
        ),
        created_at=now,
        source=SourceDescriptorV1(
            source_id="synthetic-identity",
            publisher="Drift",
            product="M1c identity fixture",
            evidence_reference=source_reference,
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=now,
            collector_id="economic-test-support",
            collector_version="1",
            evidence_reference=acquisition_reference,
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=now,
            terms_evidence_reference=license_reference,
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=uid(_stable_suffix(f"identity-partition:{digest}")),
                partition_key="all",
                artifact=ArtifactReference(
                    artifact_id=uid(_stable_suffix(f"identity-artifact:{digest}")),
                    kind=ArtifactKind.DATASET,
                    content_hash=digest,
                    location=f"drift+sha256://{digest}",
                ),
                byte_size=len(data),
                media_type="application/json",
                format_version="1",
                row_count=len(assignments),
                schema_hash=schema.schema_hash,
                coverage=TemporalCoverage(started_at=now, ended_at=now),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=AssertionTemporalContractV1(
                contract_version="1",
                evidence_granularity=EvidenceGranularity.RECORD,
                logical_record_id_field_id="revision.logical_record_id",
                record_version_id_field_id="revision.record_version_id",
                revision_kind_field_id="revision.revision_kind",
                supersedes_field_id="revision.supersedes_record_version_id",
                source_sequence_field_id="revision.source_sequence",
                availability_field_id="revision.availability",
                source_artifact_field_id="revision.source_artifact",
                payload_hash_field_id="revision.payload_hash",
                effective_time_field_id="effective_interval",
                effective_shape=AssertionEffectiveShape.INTERVAL,
                semantic_state_field_ids=("assignment_effect",),
                declared_channels=(public_channel(),),
            ),
        ),
        lineage=None,
    )
    verified = VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=digest
    )
    run = ValidationRunContextV1(
        decision_id=uid(_stable_suffix(f"identity-decision:{digest}")),
        validator_version="1",
        validator_implementation_hash=HASH_A,
        validation_profile_id="m1b-role-v1",
        validation_profile_hash=HASH_B,
        checked_at=now,
    )
    decision = validate_identity_dataset(manifest, (verified,), run)
    assert decision.result is ValidationResult.PASS
    bundle = build_validated_dataset_bundle(
        bundle_id=uid(_stable_suffix(f"identity-bundle:{digest}")),
        bundle_version="1",
        created_at=now,
        validated_datasets=((manifest, decision),),
    )
    return EconomicIdentityInput(
        records=assignments,
        manifest=manifest,
        decision=decision,
        verified_artifacts=(verified,),
        validation_run=run,
        bundle=bundle,
    )


def _fixture_artifact_references(value: object) -> tuple[ArtifactReference, ...]:
    references: list[ArtifactReference] = []

    def visit(item: object) -> None:
        if isinstance(item, ArtifactReference):
            references.append(item)
        elif isinstance(item, BaseModel):
            for name in type(item).model_fields:
                visit(getattr(item, name))
        elif isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, tuple | list):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(references)


@dataclass(frozen=True)
class EconomicHarness:
    """One fully validated synthetic M1c context and its source policy."""

    context: EconomicResolutionContext
    source_policy: EconomicSourceSelectionPolicyV1

    def decision_query(self, t: str, k: str, e: str) -> MarketDecisionQueryV1:
        effective = parse_utc(e)
        if effective != self.source_policy.through:
            raise ValueError("decision effective cutoff must equal policy through")
        return MarketDecisionQueryV1(
            schema_version="1",
            kind="decision",
            purpose="economic_facts",
            security_id=self.source_policy.security_id,
            action_kinds=tuple(sorted(ActionKind, key=lambda item: item.value)),
            history_start=parse_utc("2020-01-01T00:00:00Z"),
            requested_channel=public_channel(),
            availability_policy_id=self.context.availability_policy.policy_id,
            availability_policy_hash=content_hash(self.context.availability_policy),
            source_selection_policy_hash=content_hash(self.source_policy),
            input_context_hash=economic_context_hash(self.context),
            decision_time=parse_utc(t),
            knowledge_cutoff=parse_utc(k),
            effective_cutoff=effective,
        )

    def outcome_query(self, h: str, v: str) -> MarketOutcomeQueryV1:
        horizon = parse_utc(h)
        if horizon != self.source_policy.through:
            raise ValueError("outcome horizon must equal policy through")
        return MarketOutcomeQueryV1(
            schema_version="1",
            kind="outcome",
            purpose="economic_outcome",
            security_id=self.source_policy.security_id,
            action_kinds=tuple(sorted(ActionKind, key=lambda item: item.value)),
            history_start=parse_utc("2020-01-01T00:00:00Z"),
            requested_channel=public_channel(),
            availability_policy_id=self.context.availability_policy.policy_id,
            availability_policy_hash=content_hash(self.context.availability_policy),
            source_selection_policy_hash=content_hash(self.source_policy),
            input_context_hash=economic_context_hash(self.context),
            economic_horizon=horizon,
            evidence_vintage_cutoff=parse_utc(v),
        )


def validated_case(
    records: tuple[EconomicRecordV1, ...],
    *,
    complete_coverage: bool = True,
    owner_source: str = "synthetic-a",
    through: str = "2021-01-01T00:00:00Z",
    coverage_snapshot_at: str | None = None,
) -> EconomicHarness:
    """Build a closed, immutable synthetic M1c validation context."""
    owned_records: list[EconomicRecordV1] = []
    for record in records:
        if record.source_key.source_id == owner_source:
            owned_records.append(record)
            continue
        values = {name: getattr(record, name) for name in type(record).model_fields}
        values["source_key"] = record.source_key.model_copy(
            update={"source_id": owner_source}
        )
        owned_records.append(rebind_record_evidence(type(record), values))

    fact_inputs = tuple(
        economic_dataset(
            role,
            tuple(
                record
                for record in owned_records
                if (
                    role == "economic_terms"
                    and isinstance(record, CorporateActionTermsVersionV1)
                )
                or (
                    role == "economic_effect"
                    and isinstance(record, EconomicEffectVersionV1)
                )
                or (
                    role == "economic_settlement"
                    and isinstance(record, EconomicSettlementVersionV1)
                )
            ),
            owner_source,
        )
        for role in ("economic_terms", "economic_effect", "economic_settlement")
    )
    through_value = parse_utc(through)
    minimum_snapshot = through_value + timedelta(days=1)
    if complete_coverage and any(
        evidence.upper_bound is None
        for record in owned_records
        for evidence in record.revision.availability
    ):
        raise ValueError("unknown availability cannot support complete coverage")
    known_upper_bounds = tuple(
        evidence.upper_bound
        for record in owned_records
        for evidence in record.revision.availability
        if evidence.upper_bound is not None
    )
    if known_upper_bounds:
        minimum_snapshot = max(minimum_snapshot, *known_upper_bounds)
    snapshot = (
        minimum_snapshot
        if coverage_snapshot_at is None
        else parse_utc(coverage_snapshot_at)
    )
    if snapshot < minimum_snapshot:
        raise ValueError("coverage snapshot precedes synthetic inventory vintage")
    coverage_end = (through_value + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot_text = snapshot.strftime("%Y-%m-%dT%H:%M:%SZ")
    families: tuple[Literal["terms", "effect", "settlement"], ...] = (
        "terms",
        "effect",
        "settlement",
    )
    coverage_records = tuple(
        coverage_record(
            3000 + index,
            family,
            manifest_hash(dataset.manifest),
            dataset.decision.validated_artifact_hashes,
            dataset.decision.validated_record_hashes,
            completeness="complete" if complete_coverage else "partial",
            snapshot_at=snapshot_text,
            source_id=owner_source,
            coverage_end=coverage_end,
        )
        for index, (family, dataset) in enumerate(
            zip(families, fact_inputs, strict=True)
        )
    )
    coverage_input = economic_dataset(
        "economic_coverage", coverage_records, owner_source
    )
    datasets = (*fact_inputs, coverage_input)
    identity = identity_input(history_assignments())
    references_by_hash: dict[str, ArtifactReference] = {}
    for dataset in datasets:
        for reference in _fixture_artifact_references(
            (
                dataset.records,
                dataset.manifest.source,
                dataset.manifest.acquisition,
                dataset.manifest.license,
            )
        ):
            references_by_hash.setdefault(reference.content_hash, reference)
    supporting_artifacts = tuple(
        sorted(
            (support_bytes(reference) for reference in references_by_hash.values()),
            key=lambda artifact: artifact.content_hash,
        )
    )
    context = EconomicResolutionContext(
        datasets=datasets,
        identity=identity,
        availability_policy=AvailabilityPolicyV1(
            policy_id="public-v1", permitted_rule_hashes=()
        ),
        retained_evidence={},
        supporting_artifacts=supporting_artifacts,
    )
    bindings = tuple(
        DatasetBindingV1(
            manifest_hash=manifest_hash(dataset.manifest),
            decision_hash=content_hash(dataset.decision),
            bundle_hash=content_hash(dataset.bundle),
            role=dataset.manifest.dataset_role.name,
            source_id=dataset.manifest.source.source_id,
        )
        for dataset in datasets
    )
    coverage_manifest_hash = manifest_hash(coverage_input.manifest)
    owners = tuple(
        EconomicSourceOwnerV1(
            family=family,
            source_id=owner_source,
            fact_manifest_hash=manifest_hash(dataset.manifest),
            coverage_manifest_hash=coverage_manifest_hash,
        )
        for family, dataset in zip(families, fact_inputs, strict=True)
    )
    policy = source_policy(
        uid(21),
        bindings,
        owners,
        parse_utc("2020-01-01T00:00:00Z"),
        through_value,
    )
    return EconomicHarness(context=context, source_policy=policy)


def policy_fixture() -> EconomicSourceSelectionPolicyV1:
    """Build policy shape only, never a resolution-ready dataset context."""
    hashes = (HASH_A, HASH_B, HASH_C, HASH_D, HASH_E, "f" * 64)
    owners = (
        EconomicSourceOwnerV1(
            family="terms",
            source_id="synthetic-a",
            fact_manifest_hash=hashes[0],
            coverage_manifest_hash=hashes[1],
        ),
        EconomicSourceOwnerV1(
            family="effect",
            source_id="synthetic-b",
            fact_manifest_hash=hashes[2],
            coverage_manifest_hash=hashes[3],
        ),
        EconomicSourceOwnerV1(
            family="settlement",
            source_id="synthetic-a",
            fact_manifest_hash=hashes[4],
            coverage_manifest_hash=hashes[5],
        ),
    )
    bindings = tuple(
        DatasetBindingV1(
            manifest_hash=digest,
            decision_hash=digest,
            bundle_hash=digest,
            role=(
                "economic_terms"
                if index == 0
                else "economic_effect"
                if index == 2
                else "economic_settlement"
                if index == 4
                else "economic_coverage"
            ),
            source_id="synthetic-b" if index in (2, 3) else "synthetic-a",
        )
        for index, digest in enumerate(hashes)
    )
    return source_policy(
        uid(21),
        bindings,
        owners,
        parse_utc("2020-01-01T00:00:00Z"),
        parse_utc("2021-01-01T00:00:00Z"),
    )
