"""Shared, literal fixtures for M1c economic query contract tests."""

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, get_args
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel

from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
)
from drift.domain.common import FrozenModel
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
from drift.domain.revisions import RevisionKind
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.serialization.canonical import canonical_json, content_hash

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def uid(suffix: int) -> UUID:
    """Return a fixed UUIDv7, derived only from a fixture suffix."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


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


def support_bytes(reference: ArtifactReference) -> VerifiedArtifactBytes:
    """Reconstruct and verify bytes encoded by a synthetic economic reference."""
    parsed = urlsplit(reference.location)
    if parsed.scheme != "synthetic-economic" or parsed.netloc != "source":
        raise ValueError("fixture requires a synthetic economic evidence locator")
    statement = unquote(parsed.path.removeprefix("/"))
    reconstructed_reference, verified = economic_evidence(statement)
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
