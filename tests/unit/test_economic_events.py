"""Behavioral contracts for M1c terms, effects, settlements, and shape rules."""

import json
from typing import Any, Literal

import pytest
from economic_test_support import (
    bounded_boundary,
    cash_component,
    economic_evidence,
    effect_record,
    parse_utc,
    rebind_record_evidence,
    revise_record,
    seal_record,
    settlement_record,
    support_bytes,
    terms_record,
    uid,
)
from pydantic import ValidationError

from drift.datasets.assertions import validate_assertion_chain
from drift.domain.assertions import (
    AssertionVersionProjectionV1,
    BoundaryShape,
    TemporalBoundaryClaimV1,
)
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicAssociationV1,
    EconomicComponentV1,
    EconomicDateFactV1,
    EconomicOccurrenceV1,
    EconomicRecipientV1,
    EconomicShareBasisV1,
    EconomicUnitBasisV1,
    FractionTreatmentV1,
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
    OccurredEffectV1,
    ResidualClaimV1,
    TermsPayloadV1,
    UnknownEffectV1,
    classify_economic_shape,
    economic_record_family,
    validate_economic_record_ownership,
)
from drift.domain.revisions import RevisionKind
from drift.domain.temporal import SourcePrecision
from drift.serialization.canonical import content_hash


def _share(
    recipient: int,
    numerator: str,
    denominator: str,
    meaning: str,
    *,
    component_id: str = "shares",
    fraction: Literal[
        "fraction_issued",
        "round_up",
        "round_down",
        "round_nearest",
        "aggregate_sale_cash",
        "unknown",
    ] = "round_up",
) -> ShareComponentV1:
    reference, _ = economic_evidence(
        f"{component_id} ratio {numerator}/{denominator} fraction {fraction}"
    )
    fraction_treatment = (
        FractionTreatmentV1(kind="unknown")
        if fraction == "unknown"
        else FractionTreatmentV1(
            kind=fraction,
            source_rule=f"source says {fraction}",
            evidence_reference=reference,
        )
    )
    return ShareComponentV1.model_validate(
        {
            "kind": "shares",
            "component_id": component_id,
            "recipient": EconomicRecipientV1(
                kind="security", security_id=uid(recipient)
            ),
            "ratio": PositiveRatioV1(numerator=numerator, denominator=denominator),
            "ratio_meaning": meaning,
            "unit_basis": EconomicShareBasisV1(
                security_id=uid(21), share_basis="predecessor_pre_action"
            ),
            "fraction_treatment": fraction_treatment,
            "applicability": "ordinary_passive_holder",
            "conditions": (),
        }
    )


def _with_payload[T: EconomicRecordV1](
    record: T, payload: object, **changes: object
) -> T:
    values = {field: getattr(record, field) for field in type(record).model_fields}
    values.update(changes)
    values["payload"] = payload
    return rebind_record_evidence(type(record), values)


def _terms(
    action_kind: ActionKind,
    components: tuple[EconomicComponentV1, ...],
    *,
    conditions: tuple[str, ...] = (),
) -> CorporateActionTermsVersionV1:
    record = terms_record(10_000 + len(components), action_kind=action_kind)
    return _with_payload(
        record,
        TermsPayloadV1.model_validate(
            {
                "kind": "fixed",
                "action_kind": action_kind,
                "components": components,
                "dates": (),
                "conditions": conditions,
                "reason": None,
            }
        ),
    )


def _effect(
    action_kind: ActionKind,
    components: tuple[EconomicComponentV1, ...],
    claim_status: str,
) -> EconomicEffectVersionV1:
    record = effect_record(20_000 + len(components))
    reference = record.revision.source_artifact
    payload = OccurredEffectV1.model_validate(
        {
            "kind": "occurred",
            "action_kind": action_kind,
            "claim_status": claim_status,
            "consideration_status": "components",
            "owed_components": components,
            "residual": ResidualClaimV1(
                kind="unknown", reason="source did not address residual"
            ),
            "evidence_reference": reference,
        }
    )
    return _with_payload(record, payload)


def _settlement(
    action_kind: ActionKind, components: tuple[EconomicComponentV1, ...]
) -> EconomicSettlementVersionV1:
    record = settlement_record(30_000 + len(components))
    return _with_payload(
        record,
        DeliveredSettlementV1(
            kind="delivered",
            action_kind=action_kind,
            delivered_components=components,
            residual=ResidualClaimV1(
                kind="unknown", reason="source did not address residual"
            ),
            evidence_reference=record.revision.source_artifact,
        ),
    )


def _source_semantics(record: Any) -> dict[str, Any]:
    outer = json.loads(support_bytes(record.revision.source_artifact).data)
    statement = outer["synthetic_source_statement"]
    try:
        decoded = json.loads(statement)
    except json.JSONDecodeError:
        return {}
    assert isinstance(decoded, dict)
    return decoded


def test_announcement_cancelled_action_and_payment_are_distinct() -> None:
    """Collapsing proposal, cancellation, and delivery into one event must fail."""
    terms = terms_record(100)
    cancelled = effect_record(200, kind="cancelled_action")
    paid = settlement_record(300)
    assert terms.payload is not None
    assert cancelled.payload is not None
    assert paid.payload is not None
    assert terms.payload.kind == "fixed"
    assert cancelled.payload.kind == "cancelled_action"
    assert not hasattr(cancelled.payload, "claim_status")
    component = paid.payload.delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "5"
    assert paid.terms_association.kind == "unknown"


def test_fixture_evidence_is_real_independent_canonical_bytes() -> None:
    """A hardcoded digest with no bytes would falsely look authoritative."""
    first = terms_record(401)
    second = settlement_record(402, amount="7")
    for reference in (first.revision.source_artifact, second.revision.source_artifact):
        verified = support_bytes(reference)
        assert verified.content_hash == reference.content_hash
        assert verified.byte_size == len(verified.data)
    assert first.revision.source_artifact.content_hash != (
        second.revision.source_artifact.content_hash
    )
    assert _source_semantics(first)["payload"]["action_kind"] == (
        "regular_cash_dividend"
    )
    assert (
        _source_semantics(second)["payload"]["delivered_components"][0]["amount"] == "7"
    )


def test_action_and_correction_source_bytes_state_final_semantics() -> None:
    """Sealed action records must not retain bytes describing an earlier payload."""
    mixed = _settlement(ActionKind.MIXED_ACQUISITION, (cash_component(),))
    stock = _effect(
        ActionKind.STOCK_ACQUISITION,
        (_share(22, "3", "2", "resulting_per_predecessor"),),
        "converted",
    )
    original = settlement_record(415, occurrence_id=None)
    changed_evidence, _ = economic_evidence("payment correction source")
    corrected = revise_record(
        original,
        416,
        "2020-07-01T00:00:00Z",
        {
            "security_id": uid(22),
            "occurrence": EconomicOccurrenceV1(
                kind="identified",
                native_occurrence_id="payment-22",
                evidence_reference=changed_evidence,
            ),
            "payload": DeliveredSettlementV1(
                kind="delivered",
                action_kind=ActionKind.MIXED_ACQUISITION,
                delivered_components=(cash_component(amount="7"),),
                residual=ResidualClaimV1(kind="unknown", reason="not addressed"),
                evidence_reference=changed_evidence,
            ),
        },
    )

    mixed_payload = _source_semantics(mixed)["payload"]
    assert mixed_payload["kind"] == "delivered"
    assert mixed_payload["action_kind"] == "mixed_acquisition"
    assert mixed_payload["delivered_components"][0]["amount"] == "5"
    stock_payload = _source_semantics(stock)["payload"]
    assert stock_payload["kind"] == "occurred"
    assert stock_payload["action_kind"] == "stock_acquisition"
    assert stock_payload["claim_status"] == "converted"
    assert stock_payload["consideration_status"] == "components"
    stock_share = stock_payload["owed_components"][0]
    assert stock_share["ratio"] == {"denominator": "2", "numerator": "3"}
    assert stock_share["ratio_meaning"] == "resulting_per_predecessor"
    assert stock_share["recipient"]["security_id"] == str(uid(22))
    corrected_semantics = _source_semantics(corrected)
    assert corrected_semantics["security_id"] == str(uid(22))
    assert corrected_semantics["occurrence"]["kind"] == "identified"
    assert corrected_semantics["occurrence"]["native_occurrence_id"] == "payment-22"
    assert corrected_semantics["occurrence"]["reason"] is None
    assert corrected_semantics["occurrence"]["evidence_reference"] == {"present": True}
    assert corrected_semantics["payload"]["action_kind"] == "mixed_acquisition"
    assert corrected_semantics["payload"]["delivered_components"][0]["amount"] == "7"
    assert corrected.revision.source_artifact == corrected.occurrence.evidence_reference
    assert corrected.payload is not None
    assert corrected.revision.source_artifact == corrected.payload.evidence_reference


def test_source_projection_hashes_every_nonreference_semantic_field() -> None:
    """Changing a retained source fact must change its raw source bytes and digest."""
    base = terms_record(417)
    assert base.payload is not None
    base_cash = base.payload.components[0]
    assert isinstance(base_cash, CashComponentV1)

    cash_mutations = (
        (
            "currency_namespace",
            base_cash.model_copy(update={"currency_namespace": "SYNTH-CURRENCY"}),
            "SYNTH-CURRENCY",
        ),
        (
            "currency_code",
            base_cash.model_copy(update={"currency_code": "EUR"}),
            "EUR",
        ),
        (
            "unit_basis",
            base_cash.model_copy(
                update={
                    "unit_basis": EconomicUnitBasisV1(
                        security_id=uid(21),
                        denominator=PositiveRatioV1(numerator="100", denominator="1"),
                        share_basis="predecessor_pre_action",
                    )
                }
            ),
            {
                "denominator": {"denominator": "1", "numerator": "100"},
                "security_id": str(uid(21)),
                "share_basis": "predecessor_pre_action",
            },
        ),
        (
            "unit_basis",
            base_cash.model_copy(
                update={
                    "unit_basis": EconomicUnitBasisV1(
                        security_id=uid(21),
                        denominator=PositiveRatioV1(numerator="1", denominator="1"),
                        share_basis="predecessor_post_action",
                    )
                }
            ),
            {
                "denominator": {"denominator": "1", "numerator": "1"},
                "security_id": str(uid(21)),
                "share_basis": "predecessor_post_action",
            },
        ),
        (
            "unit_basis",
            base_cash.model_copy(
                update={
                    "unit_basis": EconomicUnitBasisV1(
                        security_id=uid(22),
                        denominator=PositiveRatioV1(numerator="1", denominator="1"),
                        share_basis="predecessor_pre_action",
                    )
                }
            ),
            {
                "denominator": {"denominator": "1", "numerator": "1"},
                "security_id": str(uid(22)),
                "share_basis": "predecessor_pre_action",
            },
        ),
        (
            "amount_basis",
            base_cash.model_copy(update={"amount_basis": "net"}),
            "net",
        ),
        (
            "source_amount_text",
            base_cash.model_copy(update={"source_amount_text": "USD 5.00"}),
            "USD 5.00",
        ),
        (
            "source_precision",
            base_cash.model_copy(update={"source_precision": 2}),
            2,
        ),
    )
    base_hash = base.revision.source_artifact.content_hash
    base_bytes = support_bytes(base.revision.source_artifact).data
    for field, changed_component, expected in cash_mutations:
        changed = _with_payload(
            base,
            base.payload.model_copy(update={"components": (changed_component,)}),
        )
        assert changed.revision.source_artifact.content_hash != base_hash
        assert support_bytes(changed.revision.source_artifact).data != base_bytes
        assert _source_semantics(changed)["payload"]["components"][0][field] == (
            expected
        )

    share = _share(22, "3", "2", "resulting_per_predecessor")
    stock = _terms(ActionKind.STOCK_ACQUISITION, (share,))
    assert stock.payload is not None
    changed_basis = share.model_copy(
        update={
            "unit_basis": EconomicShareBasisV1(
                security_id=uid(21), share_basis="predecessor_post_action"
            )
        }
    )
    changed_unit_security = share.model_copy(
        update={
            "unit_basis": EconomicShareBasisV1(
                security_id=uid(22), share_basis="predecessor_pre_action"
            )
        }
    )
    changed_rule = share.model_copy(
        update={
            "fraction_treatment": share.fraction_treatment.model_copy(
                update={"source_rule": "issuer rounds every fraction upward"}
            )
        }
    )
    unresolved = share.model_copy(
        update={
            "recipient": EconomicRecipientV1(
                kind="unresolved_property",
                source_property_key="successor-class",
                reason="source identity unresolved",
            )
        }
    )
    changed_reason = unresolved.model_copy(
        update={
            "recipient": unresolved.recipient.model_copy(
                update={"reason": "successor identity unresolved"}
            )
        }
    )
    stock_hash = stock.revision.source_artifact.content_hash
    stock_bytes = support_bytes(stock.revision.source_artifact).data
    for changed_share in (
        changed_basis,
        changed_unit_security,
        changed_rule,
        unresolved,
        changed_reason,
    ):
        changed = _with_payload(
            stock,
            stock.payload.model_copy(update={"components": (changed_share,)}),
        )
        assert changed.revision.source_artifact.content_hash != stock_hash
        assert support_bytes(changed.revision.source_artifact).data != stock_bytes
    unresolved_record = _with_payload(
        stock,
        stock.payload.model_copy(update={"components": (unresolved,)}),
    )
    changed_reason_record = _with_payload(
        stock,
        stock.payload.model_copy(update={"components": (changed_reason,)}),
    )
    assert unresolved_record.revision.source_artifact.content_hash != (
        changed_reason_record.revision.source_artifact.content_hash
    )
    assert support_bytes(unresolved_record.revision.source_artifact).data != (
        support_bytes(changed_reason_record.revision.source_artifact).data
    )
    basis_semantics = _source_semantics(
        _with_payload(
            stock,
            stock.payload.model_copy(update={"components": (changed_basis,)}),
        )
    )
    assert basis_semantics["payload"]["components"][0]["unit_basis"] == {
        "security_id": str(uid(21)),
        "share_basis": "predecessor_post_action",
    }
    rule_semantics = _source_semantics(
        _with_payload(
            stock,
            stock.payload.model_copy(update={"components": (changed_rule,)}),
        )
    )
    assert rule_semantics["payload"]["components"][0]["fraction_treatment"] == {
        "evidence_reference": {"present": True},
        "kind": "round_up",
        "source_rule": "issuer rounds every fraction upward",
    }
    reason_semantics = _source_semantics(
        _with_payload(
            stock,
            stock.payload.model_copy(update={"components": (changed_reason,)}),
        )
    )
    assert reason_semantics["payload"]["components"][0]["recipient"] == {
        "kind": "unresolved_property",
        "reason": "successor identity unresolved",
        "security_id": None,
        "source_property_key": "successor-class",
    }

    reference, _ = economic_evidence("optional evidence is explicitly present")
    dated_without_rule = _with_payload(
        base,
        base.payload.model_copy(
            update={
                "dates": (
                    EconomicDateFactV1(
                        role="record",
                        boundary=base.scheduled_effect_time,
                        rule_reference=None,
                    ),
                )
            }
        ),
    )
    dated_with_rule = _with_payload(
        base,
        base.payload.model_copy(
            update={
                "dates": (
                    EconomicDateFactV1(
                        role="record",
                        boundary=base.scheduled_effect_time,
                        rule_reference=reference,
                    ),
                )
            }
        ),
    )
    assert dated_without_rule.revision.source_artifact.content_hash != (
        dated_with_rule.revision.source_artifact.content_hash
    )
    assert support_bytes(dated_without_rule.revision.source_artifact).data != (
        support_bytes(dated_with_rule.revision.source_artifact).data
    )
    assert _source_semantics(dated_without_rule)["payload"]["dates"][0][
        "rule_reference"
    ] == {"present": False}
    assert _source_semantics(dated_with_rule)["payload"]["dates"][0][
        "rule_reference"
    ] == {"present": True}

    effect = effect_record(418)
    assert isinstance(effect.payload, OccurredEffectV1)
    residual_with_evidence = effect.payload.residual.model_copy(
        update={"evidence_reference": reference}
    )
    effect_with_residual_evidence = _with_payload(
        effect,
        effect.payload.model_copy(update={"residual": residual_with_evidence}),
    )
    assert effect.revision.source_artifact.content_hash != (
        effect_with_residual_evidence.revision.source_artifact.content_hash
    )
    assert (
        support_bytes(effect.revision.source_artifact).data
        != support_bytes(effect_with_residual_evidence.revision.source_artifact).data
    )
    assert _source_semantics(effect)["payload"]["residual"]["evidence_reference"] == {
        "present": False
    }
    assert _source_semantics(effect_with_residual_evidence)["payload"]["residual"][
        "evidence_reference"
    ] == {"present": True}
    semantics = _source_semantics(effect_with_residual_evidence)
    assert "payload_hash" not in semantics["revision"]
    assert semantics["revision"]["source_artifact"] == {"present": True}


def test_currency_only_corrections_have_distinct_source_bytes() -> None:
    """USD and EUR corrections must not share a raw source statement or hash."""
    original = settlement_record(419)
    assert original.payload is not None
    usd = revise_record(
        original,
        420,
        "2020-07-01T00:00:00Z",
        {"payload": original.payload},
    )
    cash = original.payload.delivered_components[0]
    assert isinstance(cash, CashComponentV1)
    eur_payload = original.payload.model_copy(
        update={
            "delivered_components": (cash.model_copy(update={"currency_code": "EUR"}),)
        }
    )
    eur = revise_record(
        original,
        420,
        "2020-07-01T00:00:00Z",
        {"payload": eur_payload},
    )
    assert usd.revision.source_artifact.content_hash != (
        eur.revision.source_artifact.content_hash
    )
    assert (
        support_bytes(usd.revision.source_artifact).data
        != support_bytes(eur.revision.source_artifact).data
    )
    assert (
        _source_semantics(usd)["payload"]["delivered_components"][0]["currency_code"]
        == "USD"
    )
    assert (
        _source_semantics(eur)["payload"]["delivered_components"][0]["currency_code"]
        == "EUR"
    )


def test_effect_and_settlement_default_known_time_to_actual_instant() -> None:
    """Inheriting an old generic availability instant would create future leakage."""
    effect = effect_record(410, effective_at="2021-02-03T04:05:06Z")
    settlement = settlement_record(411, settled_at="2021-03-04T05:06:07Z")
    assert effect.revision.availability[0].upper_bound == parse_utc(
        "2021-02-03T04:05:06Z"
    )
    assert settlement.revision.availability[0].upper_bound == parse_utc(
        "2021-03-04T05:06:07Z"
    )


def test_record_family_and_payload_hash_are_locally_bound() -> None:
    """Changing a family or semantic value without resealing must fail validation."""
    record = terms_record(420)
    assert economic_record_family(record) == "terms"
    values = {field: getattr(record, field) for field in type(record).model_fields}
    values["security_id"] = uid(99)
    with pytest.raises(ValidationError, match="payload hash"):
        type(record).model_validate(values)
    values = {field: getattr(record, field) for field in type(record).model_fields}
    values["source_key"] = record.source_key.model_copy(update={"family": "effect"})
    with pytest.raises(ValidationError, match="source family"):
        seal_record(type(record), values)


def test_known_settlement_with_unknown_parents_is_valid() -> None:
    """Missing parent claims must not erase a source-reported delivery."""
    record = settlement_record(430)
    assert record.terms_association.kind == "unknown"
    assert record.effect_association.kind == "unknown"
    assert classify_economic_shape(record) == "supported"


def test_consideration_status_never_defaults_empty_to_zero() -> None:
    """An unknown or explicit-none outcome must not carry or infer components."""
    reference, _ = economic_evidence("explicit none for occurrence occ-1")
    with pytest.raises(ValidationError, match="components"):
        OccurredEffectV1(
            kind="occurred",
            action_kind=ActionKind.CASH_ACQUISITION,
            claim_status="extinguished",
            consideration_status="components",
            owed_components=(),
            residual=ResidualClaimV1(kind="unknown", reason="not addressed"),
            evidence_reference=reference,
        )
    with pytest.raises(ValidationError, match="empty"):
        OccurredEffectV1(
            kind="occurred",
            action_kind=ActionKind.CASH_ACQUISITION,
            claim_status="extinguished",
            consideration_status="unknown",
            owed_components=(cash_component(),),
            residual=ResidualClaimV1(kind="unknown", reason="not addressed"),
            evidence_reference=reference,
        )


def test_residual_closure_requires_exact_scope_and_evidence() -> None:
    """Closure needs its causal occurrence or action to avoid invented finality."""
    reference, _ = economic_evidence("occurrence occ-1 is fully settled")
    assert (
        ResidualClaimV1(
            kind="closed_for_occurrence",
            scope_occurrence_id="occ-1",
            evidence_reference=reference,
        ).scope_occurrence_id
        == "occ-1"
    )
    association = EconomicAssociationV1(
        kind="identified",
        target=terms_record(440).source_key,
    )
    assert (
        ResidualClaimV1(
            kind="closed_for_action",
            scope_action=association,
            evidence_reference=reference,
        ).scope_action
        == association
    )
    with pytest.raises(ValidationError, match="occurrence"):
        ResidualClaimV1(kind="closed_for_occurrence", evidence_reference=reference)
    with pytest.raises(ValidationError, match="identified"):
        ResidualClaimV1(
            kind="closed_for_action",
            scope_action=EconomicAssociationV1(kind="unknown", reason="unknown"),
            evidence_reference=reference,
        )


def test_dates_are_independent_but_roles_and_component_ids_are_unique() -> None:
    """Dates have no universal order, but role and component IDs stay unique."""
    record = terms_record(450)
    reference = record.revision.source_artifact
    later = bounded_boundary("2020-06-20T00:00:00Z", "2020-06-21T00:00:00Z", reference)
    earlier = bounded_boundary(
        "2020-06-01T00:00:00Z", "2020-06-02T00:00:00Z", reference
    )
    dates = (
        EconomicDateFactV1(role="record", boundary=later),
        EconomicDateFactV1(role="payable", boundary=earlier),
    )
    payload = TermsPayloadV1(
        kind="fixed",
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(cash_component(),),
        dates=dates,
        conditions=(),
    )
    assert len(payload.dates) == 2
    with pytest.raises(ValidationError, match="date roles"):
        TermsPayloadV1(
            kind="fixed",
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            components=(cash_component(),),
            dates=(dates[0], dates[0]),
            conditions=(),
        )


def test_late_date_only_due_bill_unknown_and_withdrawal_boundaries() -> None:
    """Source precision and withdrawal semantics must survive without coercion."""
    record = terms_record(
        451,
        known_at="2020-07-01T00:00:00Z",
        scheduled_at="2020-06-01T00:00:00Z",
    )
    reference = record.revision.source_artifact
    date_only = TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=parse_utc("2020-06-01T04:00:00Z"),
        upper_bound=parse_utc("2020-06-02T04:00:00Z"),
        source_precision=SourcePrecision.DATE,
        source_time_label="2020-06-01",
        source_timezone="America/New_York",
        evidence_reference=reference,
    )
    due_bill_dates = tuple(
        EconomicDateFactV1(role=role, boundary=date_only)
        for role in ("due_bill_start", "due_bill_end", "due_bill_redemption")
    )
    assert record.payload is not None
    dated = _with_payload(
        record,
        record.payload.model_copy(update={"dates": due_bill_dates}),
    )
    assert dated.payload is not None
    assert dated.revision.availability[0].lower_bound is not None
    assert dated.scheduled_effect_time.upper_bound is not None
    assert (
        dated.revision.availability[0].lower_bound
        > dated.scheduled_effect_time.upper_bound
    )
    assert tuple(date.role for date in dated.payload.dates) == (
        "due_bill_start",
        "due_bill_end",
        "due_bill_redemption",
    )
    assert {date.boundary.source_precision for date in dated.payload.dates} == {
        SourcePrecision.DATE
    }

    unknown = TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.UNKNOWN,
        lower_bound=None,
        upper_bound=None,
        source_precision=SourcePrecision.UNKNOWN,
        source_time_label=None,
        source_timezone=None,
        evidence_reference=reference,
    )
    unknown_time = _with_payload(record, record.payload, scheduled_effect_time=unknown)
    assert unknown_time.scheduled_effect_time.shape is BoundaryShape.UNKNOWN
    assert unknown_time.scheduled_effect_time.lower_bound is None

    withdrawal_revision = record.revision.model_copy(
        update={
            "record_version_id": uid(1_451_000),
            "revision_kind": RevisionKind.WITHDRAWAL,
            "supersedes_record_version_id": record.revision.record_version_id,
            "source_sequence": 1,
        }
    )
    withdrawal_values = {
        field: getattr(record, field) for field in type(record).model_fields
    }
    withdrawal_values.update({"revision": withdrawal_revision, "payload": None})
    withdrawal = rebind_record_evidence(type(record), withdrawal_values)
    assert economic_record_family(withdrawal) == "terms"
    assert withdrawal.scheduled_effect_time.model_dump(
        mode="python", exclude={"evidence_reference"}
    ) == record.scheduled_effect_time.model_dump(
        mode="python", exclude={"evidence_reference"}
    )
    assert withdrawal.payload is None
    assert classify_economic_shape(withdrawal) == "indeterminate"
    with pytest.raises(ValidationError, match="component IDs"):
        DeliveredSettlementV1(
            kind="delivered",
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            delivered_components=(cash_component(), cash_component()),
            residual=ResidualClaimV1(kind="unknown", reason="not addressed"),
            evidence_reference=reference,
        )


@pytest.mark.parametrize(
    ("record", "expected"),
    (
        (
            _terms(
                ActionKind.FORWARD_SPLIT,
                (_share(21, "2", "1", "resulting_per_predecessor"),),
            ),
            "supported",
        ),
        (
            _terms(
                ActionKind.REVERSE_SPLIT,
                (_share(21, "1", "10", "resulting_per_predecessor"),),
            ),
            "supported",
        ),
        (
            _terms(
                ActionKind.STOCK_DIVIDEND,
                (_share(21, "1", "10", "additional_per_predecessor"),),
            ),
            "supported",
        ),
        (_terms(ActionKind.REGULAR_CASH_DIVIDEND, (cash_component(),)), "supported"),
        (
            _terms(ActionKind.SPECIAL_CASH_DISTRIBUTION, (cash_component(),)),
            "supported",
        ),
        (_terms(ActionKind.CASH_ACQUISITION, (cash_component(),)), "supported"),
        (
            _terms(
                ActionKind.STOCK_ACQUISITION,
                (_share(22, "3", "2", "resulting_per_predecessor"),),
            ),
            "supported",
        ),
        (
            _terms(
                ActionKind.MIXED_ACQUISITION,
                (cash_component(), _share(22, "1", "2", "resulting_per_predecessor")),
            ),
            "supported",
        ),
        (
            _terms(
                ActionKind.SPINOFF,
                (_share(22, "1", "4", "additional_per_predecessor"),),
                conditions=("regulatory approval required",),
            ),
            "supported",
        ),
        (
            _terms(
                ActionKind.CONVERSION,
                (_share(22, "1", "1", "resulting_per_predecessor"),),
            ),
            "supported",
        ),
        (_terms(ActionKind.LIQUIDATION, (cash_component(),)), "supported"),
        (_terms(ActionKind.RIGHTS_WARRANTS_CVR, (cash_component(),)), "unsupported"),
    ),
)
def test_terms_classifier_implements_fixed_family_shapes(
    record: Any, expected: str
) -> None:
    """A wrong action/component rule must change the literal expected classification."""
    assert classify_economic_shape(record) == expected


def test_classifier_distinguishes_split_and_stock_dividend_ratio_meanings() -> None:
    """An additional stock ratio must not be treated as a resulting split ratio."""
    wrong_split = _terms(
        ActionKind.FORWARD_SPLIT,
        (_share(21, "2", "1", "additional_per_predecessor"),),
    )
    wrong_dividend = _terms(
        ActionKind.STOCK_DIVIDEND,
        (_share(21, "1", "10", "resulting_per_predecessor"),),
    )
    assert classify_economic_shape(wrong_split) == "unsupported"
    assert classify_economic_shape(wrong_dividend) == "unsupported"


def test_effect_classifier_uses_claim_state_owned_by_effects() -> None:
    """Effect shapes require the action's exact claim transition."""
    cases = (
        (
            _effect(ActionKind.CASH_ACQUISITION, (cash_component(),), "extinguished"),
            "supported",
        ),
        (
            _effect(
                ActionKind.STOCK_ACQUISITION,
                (_share(22, "1", "1", "resulting_per_predecessor"),),
                "converted",
            ),
            "supported",
        ),
        (
            _effect(
                ActionKind.MIXED_ACQUISITION,
                (cash_component(), _share(22, "1", "1", "resulting_per_predecessor")),
                "extinguished",
            ),
            "supported",
        ),
        (
            _effect(
                ActionKind.SPINOFF,
                (_share(22, "1", "3", "additional_per_predecessor"),),
                "continuing",
            ),
            "supported",
        ),
        (
            _effect(
                ActionKind.CONVERSION,
                (_share(22, "1", "1", "resulting_per_predecessor"),),
                "converted",
            ),
            "supported",
        ),
        (
            _effect(
                ActionKind.SPINOFF,
                (_share(22, "1", "3", "additional_per_predecessor"),),
                "unknown",
            ),
            "indeterminate",
        ),
    )
    assert tuple(classify_economic_shape(record) for record, _ in cases) == tuple(
        expected for _, expected in cases
    )


def test_cancelled_unknown_and_no_consideration_effects_stay_distinct() -> None:
    """Cancellation must not imply occurrence, extinction, or zero consideration."""
    cancelled = effect_record(500, kind="cancelled_action")
    unknown = effect_record(501, kind="unknown")
    occurred = effect_record(502)
    reference = occurred.revision.source_artifact
    explicit_none = _with_payload(
        occurred,
        OccurredEffectV1(
            kind="occurred",
            action_kind=ActionKind.CASH_ACQUISITION,
            claim_status="extinguished",
            consideration_status="explicit_none",
            owed_components=(),
            residual=ResidualClaimV1(kind="unknown", reason="not addressed"),
            evidence_reference=reference,
        ),
    )
    assert isinstance(cancelled.payload, CancelledActionV1)
    assert isinstance(unknown.payload, UnknownEffectV1)
    assert classify_economic_shape(cancelled) == "supported"
    assert classify_economic_shape(unknown) == "indeterminate"
    assert classify_economic_shape(explicit_none) == "supported"


def test_effect_status_precedes_broad_action_family_exclusions() -> None:
    """Known status semantics must not be erased by a broad action-name filter."""
    unknown = _with_payload(
        effect_record(505, kind="unknown"),
        UnknownEffectV1(
            kind="unknown",
            action_kind=ActionKind.BANKRUPTCY_REORGANIZATION,
            reason="source did not establish occurrence",
        ),
    )
    cancelled = _with_payload(
        effect_record(506, kind="cancelled_action"),
        CancelledActionV1(
            kind="cancelled_action",
            action_kind=ActionKind.RIGHTS_WARRANTS_CVR,
            reason="source cancelled the proposal",
            evidence_reference=effect_record(506).revision.source_artifact,
        ),
    )
    occurred = effect_record(507)
    explicit_none = _with_payload(
        occurred,
        OccurredEffectV1(
            kind="occurred",
            action_kind=ActionKind.BANKRUPTCY_REORGANIZATION,
            claim_status="extinguished",
            consideration_status="explicit_none",
            owed_components=(),
            residual=ResidualClaimV1(kind="unknown", reason="not addressed"),
            evidence_reference=occurred.revision.source_artifact,
        ),
    )
    fixed_cash = _terms(ActionKind.BANKRUPTCY_REORGANIZATION, (cash_component(),))
    assert tuple(
        classify_economic_shape(record)
        for record in (unknown, cancelled, explicit_none, fixed_cash)
    ) == ("indeterminate", "supported", "supported", "supported")


def test_settlement_classifier_uses_only_delivered_facts() -> None:
    """A delivery classifier must not require promised or owed parent records."""
    cases = (
        _settlement(ActionKind.CASH_ACQUISITION, (cash_component(),)),
        _settlement(
            ActionKind.STOCK_ACQUISITION,
            (_share(22, "1", "1", "resulting_per_predecessor"),),
        ),
        _settlement(
            ActionKind.MIXED_ACQUISITION,
            (cash_component(), _share(22, "1", "1", "resulting_per_predecessor")),
        ),
        _settlement(
            ActionKind.SPINOFF, (_share(22, "1", "4", "additional_per_predecessor"),)
        ),
        _settlement(ActionKind.LIQUIDATION, (cash_component(),)),
    )
    assert {classify_economic_shape(record) for record in cases} == {"supported"}


def test_settlement_classifier_accepts_separate_permitted_acquisition_legs() -> None:
    """A delivered row must not imply that the source reports the whole terms vector."""
    cases = (
        _settlement(ActionKind.MIXED_ACQUISITION, (cash_component(),)),
        _settlement(
            ActionKind.MIXED_ACQUISITION,
            (_share(22, "1", "1", "resulting_per_predecessor"),),
        ),
        _settlement(ActionKind.STOCK_ACQUISITION, (cash_component(),)),
    )
    assert tuple(classify_economic_shape(record) for record in cases) == (
        "supported",
        "supported",
        "supported",
    )


def test_unknown_and_conditional_component_shapes() -> None:
    """Unknown economics stay unknown and holder conditions are not fixed."""
    unknown_fraction = _terms(
        ActionKind.STOCK_DIVIDEND,
        (_share(21, "1", "10", "additional_per_predecessor", fraction="unknown"),),
    )
    conditional_cash = cash_component().model_copy(
        update={"applicability": "conditional", "conditions": ("holder election",)}
    )
    assert classify_economic_shape(unknown_fraction) == "indeterminate"
    with pytest.raises(ValidationError, match="ordinary passive holder"):
        TermsPayloadV1(
            kind="fixed",
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            components=(conditional_cash,),
            dates=(),
            conditions=(),
        )
    base = terms_record(511)
    unsupported = _with_payload(
        base,
        TermsPayloadV1(
            kind="unsupported",
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            components=(conditional_cash,),
            dates=(),
            conditions=(),
            reason="holder election changes consideration",
        ),
    )
    assert classify_economic_shape(unsupported) == "unsupported"


def test_unsupported_property_is_retained_without_invented_value() -> None:
    """Excluded property remains evidence without an invented value or ratio."""
    reference, _ = economic_evidence("conversion delivered an unvalued trust interest")
    component = UnsupportedPropertyComponentV1(
        kind="unsupported_property",
        component_id="trust-interest",
        recipient=EconomicRecipientV1(
            kind="unresolved_property",
            source_property_key="trust-7",
            reason="no supported security identity",
        ),
        source_description="one trust interest",
        reason="M1c does not value this property",
        evidence_reference=reference,
    )
    record = _terms(ActionKind.CONVERSION, (component,))
    assert record.payload is not None
    retained = record.payload.components[0]
    assert isinstance(retained, UnsupportedPropertyComponentV1)
    assert retained.model_dump(mode="python", exclude={"evidence_reference"}) == (
        component.model_dump(mode="python", exclude={"evidence_reference"})
    )
    assert classify_economic_shape(record) == "unsupported"


def test_security_occurrence_date_and_amount_can_be_corrected_in_one_report_chain() -> (
    None
):
    """Correctable semantic attribution must not split source-report history."""
    original = settlement_record(600, occurrence_id=None)
    evidence, _ = economic_evidence("correction identifies payment-9")
    occurrence = EconomicOccurrenceV1(
        kind="identified",
        native_occurrence_id="payment-9",
        evidence_reference=evidence,
    )
    payload = DeliveredSettlementV1(
        kind="delivered",
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        delivered_components=(cash_component(amount="7"),),
        residual=ResidualClaimV1(kind="unknown", reason="not addressed"),
        evidence_reference=evidence,
    )
    corrected = revise_record(
        original,
        601,
        "2020-07-01T00:00:00Z",
        {
            "security_id": uid(22),
            "occurrence": occurrence,
            "settled_time": bounded_boundary(
                "2020-06-15T00:00:00Z", "2020-06-16T00:00:00Z", evidence
            ),
            "payload": payload,
        },
    )
    assert corrected.source_key == original.source_key
    assert corrected.revision.logical_record_id == original.revision.logical_record_id
    later_evidence, _ = economic_evidence("correction changes payment-9 to payment-10")
    corrected_again = revise_record(
        corrected,
        602,
        "2020-07-02T00:00:00Z",
        {
            "occurrence": EconomicOccurrenceV1(
                kind="identified",
                native_occurrence_id="payment-10",
                evidence_reference=later_evidence,
            )
        },
    )
    assert (
        validate_economic_record_ownership((original, corrected, corrected_again)) == ()
    )
    projections = tuple(
        AssertionVersionProjectionV1(
            revision=item.revision, record_hash=content_hash(item)
        )
        for item in (original, corrected, corrected_again)
    )
    assert validate_assertion_chain(projections) == ()


def test_ownership_rejects_source_report_split_and_source_key_change() -> None:
    """Both directions of the report-key/logical-ID bijection must be enforced."""
    first = terms_record(700)
    second = terms_record(701)
    split_values = {
        field: getattr(second, field) for field in type(second).model_fields
    }
    split_values["source_key"] = first.source_key
    split = seal_record(type(second), split_values)
    assert {
        finding.code for finding in validate_economic_record_ownership((first, split))
    } == {"economic_source_key_multiple_logical_records"}

    changed_values = {
        field: getattr(second, field) for field in type(second).model_fields
    }
    changed_revision = second.revision.model_copy(
        update={"logical_record_id": first.revision.logical_record_id}
    )
    changed_values["revision"] = changed_revision
    changed = seal_record(type(second), changed_values)
    assert {
        finding.code for finding in validate_economic_record_ownership((first, changed))
    } == {
        "economic_logical_record_multiple_source_keys",
        "multiple_initial_roots",
    }
