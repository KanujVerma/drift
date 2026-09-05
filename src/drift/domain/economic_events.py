"""Immutable source terms, actual effects, and delivered settlements for M1c."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.datasets.assertions import validate_assertion_chain
from drift.datasets.hashing import assertion_version_payload
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import (
    AssertionVersionProjectionV1,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
)
from drift.domain.common import UUID7, FrozenModel, NonBlankStr
from drift.domain.dataset_validation import FindingSeverity, ValidationFindingV1
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicAssociationV1,
    EconomicComponentV1,
    EconomicDateFactV1,
    EconomicFamily,
    EconomicOccurrenceV1,
    EconomicSourceKeyV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
)
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.domain.revisions import RevisionKind
from drift.serialization.canonical import content_hash

type EconomicShape = Literal["supported", "unsupported", "indeterminate"]


def _require_unique_component_ids(
    components: tuple[EconomicComponentV1, ...],
) -> tuple[EconomicComponentV1, ...]:
    identifiers = tuple(component.component_id for component in components)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("economic component IDs must be unique")
    return components


class TermsPayloadV1(FrozenModel):
    """One source's proposed or fixed economic terms, never an occurrence claim."""

    kind: Literal["fixed", "incomplete", "unsupported"]
    action_kind: ActionKind
    components: tuple[EconomicComponentV1, ...]
    dates: tuple[EconomicDateFactV1, ...]
    conditions: tuple[NonBlankStr, ...]
    reason: NonBlankStr | None = None

    @field_validator("components")
    @classmethod
    def require_unique_components(
        cls, components: tuple[EconomicComponentV1, ...]
    ) -> tuple[EconomicComponentV1, ...]:
        return _require_unique_component_ids(components)

    @field_validator("dates")
    @classmethod
    def require_unique_date_roles(
        cls, dates: tuple[EconomicDateFactV1, ...]
    ) -> tuple[EconomicDateFactV1, ...]:
        roles = tuple(date.role for date in dates)
        if len(set(roles)) != len(roles):
            raise ValueError("economic date roles must be unique")
        return dates

    @model_validator(mode="after")
    def validate_completeness_label(self) -> Self:
        if self.kind == "fixed":
            if self.reason is not None:
                raise ValueError("fixed terms cannot carry an incomplete reason")
            if not self.components:
                raise ValueError("fixed terms require applicable components")
            for component in self.components:
                if isinstance(component, CashComponentV1 | ShareComponentV1) and (
                    component.applicability != "ordinary_passive_holder"
                    or component.conditions
                ):
                    raise ValueError(
                        "fixed terms require ordinary passive holder components"
                    )
        elif self.reason is None:
            raise ValueError("incomplete or unsupported terms require a reason")
        return self


class ResidualClaimV1(FrozenModel):
    """A precisely scoped source claim about consideration still outstanding."""

    kind: Literal[
        "closed_for_occurrence", "closed_for_action", "outstanding", "unknown"
    ]
    scope_occurrence_id: NonBlankStr | None = None
    scope_action: EconomicAssociationV1 | None = None
    evidence_reference: ArtifactReference | None = None
    reason: NonBlankStr | None = None

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference | None
    ) -> ArtifactReference | None:
        if reference is None:
            return None
        return validate_safe_provenance_reference(reference)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.kind == "closed_for_occurrence":
            if (
                self.scope_occurrence_id is None
                or self.evidence_reference is None
                or self.scope_action is not None
            ):
                raise ValueError(
                    "closed-for-occurrence residual requires exact occurrence "
                    "and evidence"
                )
            if self.reason is not None:
                raise ValueError("closed residual cannot carry an unresolved reason")
        elif self.kind == "closed_for_action":
            target = None if self.scope_action is None else self.scope_action.target
            if (
                self.scope_occurrence_id is not None
                or self.scope_action is None
                or self.scope_action.kind != "identified"
                or target is None
                or target.family not in {"terms", "effect"}
                or self.evidence_reference is None
            ):
                raise ValueError(
                    "closed-for-action residual requires an identified terms "
                    "or effect action and evidence"
                )
            if self.reason is not None:
                raise ValueError("closed residual cannot carry an unresolved reason")
        else:
            if self.scope_occurrence_id is not None:
                raise ValueError(
                    "open or unknown residual cannot claim occurrence closure"
                )
            if self.reason is None:
                raise ValueError("outstanding or unknown residual requires a reason")
        return self


class OccurredEffectV1(FrozenModel):
    """A source report that the economic action actually occurred."""

    kind: Literal["occurred"]
    action_kind: ActionKind
    claim_status: Literal["continuing", "converted", "extinguished", "unknown"]
    consideration_status: Literal["components", "explicit_none", "unknown"]
    owed_components: tuple[EconomicComponentV1, ...]
    residual: ResidualClaimV1
    evidence_reference: ArtifactReference

    @field_validator("owed_components")
    @classmethod
    def require_unique_components(
        cls, components: tuple[EconomicComponentV1, ...]
    ) -> tuple[EconomicComponentV1, ...]:
        return _require_unique_component_ids(components)

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference
    ) -> ArtifactReference:
        return validate_safe_provenance_reference(reference)

    @model_validator(mode="after")
    def validate_consideration(self) -> Self:
        if self.consideration_status == "components":
            if not self.owed_components:
                raise ValueError("components consideration requires components")
        elif self.owed_components:
            raise ValueError(
                "explicit-none or unknown consideration requires empty components"
            )
        return self


class CancelledActionV1(FrozenModel):
    """A source report that a proposed action was cancelled, not reversed."""

    kind: Literal["cancelled_action"]
    action_kind: ActionKind
    reason: NonBlankStr
    evidence_reference: ArtifactReference

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference
    ) -> ArtifactReference:
        return validate_safe_provenance_reference(reference)


class UnknownEffectV1(FrozenModel):
    """A source report that does not establish whether an action occurred."""

    kind: Literal["unknown"]
    action_kind: ActionKind
    reason: NonBlankStr


type EffectPayloadV1 = Annotated[
    OccurredEffectV1 | CancelledActionV1 | UnknownEffectV1,
    Field(discriminator="kind"),
]


class DeliveredSettlementV1(FrozenModel):
    """A source report of delivered consideration, distinct from amounts owed."""

    kind: Literal["delivered"]
    action_kind: ActionKind
    delivered_components: tuple[EconomicComponentV1, ...]
    residual: ResidualClaimV1
    evidence_reference: ArtifactReference

    @field_validator("delivered_components")
    @classmethod
    def require_nonempty_unique_components(
        cls, components: tuple[EconomicComponentV1, ...]
    ) -> tuple[EconomicComponentV1, ...]:
        if not components:
            raise ValueError("delivered settlement requires components")
        return _require_unique_component_ids(components)

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_reference(
        cls, reference: ArtifactReference
    ) -> ArtifactReference:
        return validate_safe_provenance_reference(reference)


class _EconomicRecordBaseV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    source_key: EconomicSourceKeyV1
    security_id: UUID7
    listing_id: UUID7 | None
    occurrence: EconomicOccurrenceV1
    source_action_code: NonBlankStr | None


class CorporateActionTermsVersionV1(_EconomicRecordBaseV1):
    """One immutable version of source-proposed corporate-action terms."""

    scheduled_effect_time: TemporalBoundaryClaimV1
    payload: TermsPayloadV1 | None

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        _require_economic_payload(self)
        return self


class EconomicEffectVersionV1(_EconomicRecordBaseV1):
    """One immutable version of a source report about actual economic effect."""

    effective_time: TemporalBoundaryClaimV1
    terms_association: EconomicAssociationV1
    payload: EffectPayloadV1 | None

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        _require_economic_payload(self)
        return self


class EconomicSettlementVersionV1(_EconomicRecordBaseV1):
    """One immutable version of a source report about delivered consideration."""

    settled_time: TemporalBoundaryClaimV1
    terms_association: EconomicAssociationV1
    effect_association: EconomicAssociationV1
    payload: DeliveredSettlementV1 | None

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        _require_economic_payload(self)
        return self


type EconomicRecordV1 = (
    CorporateActionTermsVersionV1
    | EconomicEffectVersionV1
    | EconomicSettlementVersionV1
)


def economic_record_family(record: EconomicRecordV1) -> EconomicFamily:
    """Return the exact source family owned by an economic record type."""
    if isinstance(record, CorporateActionTermsVersionV1):
        return "terms"
    if isinstance(record, EconomicEffectVersionV1):
        return "effect"
    if isinstance(record, EconomicSettlementVersionV1):
        return "settlement"
    raise TypeError("unsupported economic record type")


def _require_economic_payload(record: EconomicRecordV1) -> None:
    """Enforce withdrawal, local hash, and source-family invariants."""
    withdrawn = record.revision.revision_kind is RevisionKind.WITHDRAWAL
    if withdrawn != (record.payload is None):
        raise ValueError("only withdrawal has no payload")
    if record.revision.payload_hash != content_hash(assertion_version_payload(record)):
        raise ValueError("economic payload hash mismatch")
    if record.source_key.family != economic_record_family(record):
        raise ValueError("economic source family mismatch")


def classify_economic_shape(record: EconomicRecordV1) -> EconomicShape:
    """Classify only the shape facts supplied by this record's own family."""
    payload = record.payload
    if payload is None:
        return "indeterminate"
    if isinstance(payload, TermsPayloadV1):
        if payload.kind == "incomplete":
            return "indeterminate"
        if payload.kind == "unsupported":
            return "unsupported"
        return _classify_components(
            record.security_id, payload.action_kind, payload.components
        )
    if isinstance(payload, UnknownEffectV1):
        return "indeterminate"
    if isinstance(payload, CancelledActionV1):
        return "supported"
    if isinstance(payload, OccurredEffectV1):
        if payload.consideration_status == "unknown":
            return "indeterminate"
        if payload.consideration_status == "explicit_none":
            if payload.claim_status == "unknown":
                return "indeterminate"
            return (
                "supported" if payload.claim_status == "extinguished" else "unsupported"
            )
        shape = _classify_components(
            record.security_id, payload.action_kind, payload.owed_components
        )
        if shape != "supported":
            return shape
        return _classify_effect_claim(payload.action_kind, payload.claim_status)
    return _classify_delivered_components(
        record.security_id, payload.action_kind, payload.delivered_components
    )


def _classify_effect_claim(
    action_kind: ActionKind,
    claim_status: Literal["continuing", "converted", "extinguished", "unknown"],
) -> EconomicShape:
    if action_kind in {
        ActionKind.CASH_ACQUISITION,
        ActionKind.STOCK_ACQUISITION,
        ActionKind.MIXED_ACQUISITION,
        ActionKind.CONVERSION,
    }:
        if claim_status == "unknown":
            return "indeterminate"
        return (
            "supported"
            if claim_status in {"converted", "extinguished"}
            else "unsupported"
        )
    if action_kind == ActionKind.SPINOFF:
        if claim_status == "unknown":
            return "indeterminate"
        return "supported" if claim_status == "continuing" else "unsupported"
    return "supported"


def _classify_components(
    security_id: UUID7,
    action_kind: ActionKind,
    components: Sequence[EconomicComponentV1],
) -> EconomicShape:
    precheck = _component_precheck(security_id, components)
    if precheck != "supported":
        return precheck
    cash = tuple(item for item in components if isinstance(item, CashComponentV1))
    shares = tuple(item for item in components if isinstance(item, ShareComponentV1))
    if action_kind == ActionKind.FORWARD_SPLIT:
        return _single_same_security_ratio(shares, cash, security_id, greater=True)
    if action_kind == ActionKind.REVERSE_SPLIT:
        return _single_same_security_ratio(shares, cash, security_id, greater=False)
    if action_kind == ActionKind.STOCK_DIVIDEND:
        return _share_shape(
            shares, cash, security_id, same=True, meaning="additional_per_predecessor"
        )
    if action_kind in {
        ActionKind.REGULAR_CASH_DIVIDEND,
        ActionKind.SPECIAL_CASH_DISTRIBUTION,
        ActionKind.CASH_ACQUISITION,
    }:
        return "supported" if cash and len(cash) == len(components) else "unsupported"
    if action_kind == ActionKind.STOCK_ACQUISITION:
        return _share_shape(
            shares,
            cash,
            security_id,
            same=False,
            meaning="resulting_per_predecessor",
            allow_cash=True,
        )
    if action_kind == ActionKind.MIXED_ACQUISITION:
        shape = _share_shape(
            shares,
            cash,
            security_id,
            same=False,
            meaning="resulting_per_predecessor",
            allow_cash=True,
        )
        return shape if shape != "supported" or cash else "unsupported"
    if action_kind == ActionKind.SPINOFF:
        return _share_shape(
            shares, cash, security_id, same=False, meaning="additional_per_predecessor"
        )
    if action_kind == ActionKind.CONVERSION:
        return _share_shape(
            shares, cash, security_id, same=False, meaning="resulting_per_predecessor"
        )
    if action_kind in {
        ActionKind.LIQUIDATION,
        ActionKind.BANKRUPTCY_REORGANIZATION,
    }:
        return (
            "supported"
            if components and len(cash) + len(shares) == len(components)
            else "unsupported"
        )
    return "unsupported"


def _classify_delivered_components(
    security_id: UUID7,
    action_kind: ActionKind,
    components: Sequence[EconomicComponentV1],
) -> EconomicShape:
    """Classify supplied delivery legs without inferring the complete terms vector."""
    if action_kind not in {
        ActionKind.STOCK_ACQUISITION,
        ActionKind.MIXED_ACQUISITION,
    }:
        return _classify_components(security_id, action_kind, components)
    precheck = _component_precheck(security_id, components)
    if precheck != "supported":
        return precheck
    cash = tuple(item for item in components if isinstance(item, CashComponentV1))
    shares = tuple(item for item in components if isinstance(item, ShareComponentV1))
    if len(cash) + len(shares) != len(components):
        return "unsupported"
    if not shares:
        return "supported" if cash else "unsupported"
    return _share_shape(
        shares,
        cash,
        security_id,
        same=False,
        meaning="resulting_per_predecessor",
        allow_cash=True,
    )


def _component_precheck(
    security_id: UUID7, components: Sequence[EconomicComponentV1]
) -> EconomicShape:
    if any(isinstance(item, UnsupportedPropertyComponentV1) for item in components):
        return "unsupported"
    for component in components:
        if isinstance(component, CashComponentV1):
            if (
                component.applicability == "unknown"
                or component.amount_basis == "unknown"
            ):
                return "indeterminate"
            if component.applicability == "conditional" or component.conditions:
                return "unsupported"
            if component.unit_basis.share_basis == "as_reported_unknown":
                return "indeterminate"
            if component.unit_basis.security_id != security_id:
                return "unsupported"
        elif isinstance(component, ShareComponentV1):
            if component.applicability == "unknown":
                return "indeterminate"
            if component.applicability == "conditional" or component.conditions:
                return "unsupported"
            if component.fraction_treatment.kind == "unknown":
                return "indeterminate"
            if component.unit_basis.share_basis == "as_reported_unknown":
                return "indeterminate"
            if component.unit_basis.security_id != security_id:
                return "unsupported"
            if component.recipient.kind == "unresolved_property":
                return "indeterminate"
    return "supported"


def _single_same_security_ratio(
    shares: Sequence[ShareComponentV1],
    cash: Sequence[CashComponentV1],
    security_id: UUID7,
    *,
    greater: bool,
) -> EconomicShape:
    if len(shares) != 1 or cash:
        return "unsupported"
    share = shares[0]
    recipient = share.recipient.security_id
    ratio = share.ratio
    comparison = int(ratio.numerator) - int(ratio.denominator)
    valid_order = comparison > 0 if greater else comparison < 0
    return (
        "supported"
        if recipient == security_id
        and share.ratio_meaning == "resulting_per_predecessor"
        and valid_order
        else "unsupported"
    )


def _share_shape(
    shares: Sequence[ShareComponentV1],
    cash: Sequence[CashComponentV1],
    security_id: UUID7,
    *,
    same: bool,
    meaning: Literal["resulting_per_predecessor", "additional_per_predecessor"],
    allow_cash: bool = False,
) -> EconomicShape:
    if not shares or (cash and not allow_cash):
        return "unsupported"
    for share in shares:
        recipient = share.recipient.security_id
        if recipient is None:
            return "indeterminate"
        if (recipient == security_id) != same or share.ratio_meaning != meaning:
            return "unsupported"
    return "supported"


def validate_economic_record_ownership(
    records: Sequence[EconomicRecordV1],
) -> tuple[ValidationFindingV1, ...]:
    """Validate source-report/logical-record bijection and every revision chain."""
    findings: list[ValidationFindingV1] = []
    logical_ids_by_source: dict[EconomicSourceKeyV1, set[UUID7]] = defaultdict(set)
    source_keys_by_logical: dict[UUID7, set[EconomicSourceKeyV1]] = defaultdict(set)
    chains: dict[UUID7, list[EconomicRecordV1]] = defaultdict(list)
    for record in records:
        logical_id = record.revision.logical_record_id
        logical_ids_by_source[record.source_key].add(logical_id)
        source_keys_by_logical[logical_id].add(record.source_key)
        chains[logical_id].append(record)
    if any(len(logical_ids) > 1 for logical_ids in logical_ids_by_source.values()):
        findings.append(_finding("economic_source_key_multiple_logical_records"))
    if any(len(source_keys) > 1 for source_keys in source_keys_by_logical.values()):
        findings.append(_finding("economic_logical_record_multiple_source_keys"))
    for chain in chains.values():
        projections = tuple(
            AssertionVersionProjectionV1(
                revision=record.revision, record_hash=content_hash(record)
            )
            for record in chain
        )
        findings.extend(validate_assertion_chain(projections))
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.code,
                finding.severity.value,
                finding.message,
            ),
        )
    )


def _finding(code: str) -> ValidationFindingV1:
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
    )
