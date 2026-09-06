"""Replayable audit-side composition of selected M1c economic facts."""

from collections import defaultdict
from collections.abc import Mapping, Sequence, Set
from typing import Literal
from uuid import UUID

from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import TemporalBoundaryClaimV1
from drift.domain.economic_common import (
    CashComponentV1,
    EconomicAssociationV1,
    EconomicComponentV1,
    EconomicRecipientV1,
    EconomicSourceKeyV1,
    FractionTreatmentV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
    economic_implementation_hash,
)
from drift.domain.economic_coverage import (
    EconomicCoverageVersionV1,
    EconomicSourceSelectionPolicyV1,
    coverage_contains,
    policy_owner,
)
from drift.domain.economic_events import (
    CancelledActionV1,
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    EconomicRecordV1,
    EconomicSettlementVersionV1,
    OccurredEffectV1,
    ResidualClaimV1,
    UnknownEffectV1,
    classify_economic_shape,
)
from drift.domain.economic_queries import (
    EconomicSafeFactProjectionV1,
    MarketSelectionProofV1,
    MarketSelectionQueryV1,
    market_cutoff,
    market_horizon,
)
from drift.domain.economic_results import (
    ActionResidualResolutionV1,
    CashEconomicValueV1,
    EconomicAssociationResolutionV1,
    EconomicAssociationValueV1,
    EconomicBoundaryValueV1,
    EconomicComparisonComponentV1,
    EconomicCoverageResolutionV1,
    EconomicDeliveryGroupV1,
    EconomicEffectProjectionV1,
    EconomicOutcomeResolutionV1,
    EconomicRecipientValueV1,
    EconomicResidualValueV1,
    FractionEconomicValueV1,
    PropertyEconomicValueV1,
    SettlementEconomicPayloadV1,
    ShareEconomicValueV1,
)
from drift.markets.economic_selection import project_market_facts, select_market_records
from drift.markets.economic_validation import (
    EconomicDatasetInput,
    EconomicResolutionContext,
    economic_coverage_methodology_supported,
)
from drift.serialization.canonical import canonical_json, content_hash

_COMPOSITION_SPEC = {
    "profile": "drift-m1c-economic-composition-v1",
    "comparison_scope": "positively identified same-source same-security occurrence",
    "components": {
        "collection": "multiset",
        "ordering": "canonical_json_bytes",
        "multiplicity": "preserved",
        "matching_prohibition": "never match across occurrence IDs",
    },
    "models": {
        "CashEconomicValueV1": {
            "included_fields": (
                "kind",
                "amount",
                "currency_namespace",
                "currency_code",
                "unit_basis",
                "amount_basis",
                "applicability",
                "conditions",
            ),
            "excluded_source_fields": (
                "component_id",
                "source_amount_text",
                "source_precision",
            ),
        },
        "ShareEconomicValueV1": {
            "included_fields": (
                "kind",
                "recipient",
                "ratio",
                "ratio_meaning",
                "unit_basis",
                "fraction",
                "applicability",
                "conditions",
            ),
            "excluded_source_fields": (
                "component_id",
                "fraction_treatment.evidence_reference",
            ),
        },
        "PropertyEconomicValueV1": {
            "included_fields": ("kind", "recipient", "source_description"),
            "excluded_source_fields": (
                "component_id",
                "reason",
                "evidence_reference",
            ),
        },
        "EconomicRecipientValueV1": {
            "included_fields": (
                "kind",
                "security_id",
                "source_property_key",
            ),
            "excluded_source_fields": ("reason",),
        },
        "FractionEconomicValueV1": {
            "included_fields": ("kind", "source_rule"),
            "excluded_source_fields": ("evidence_reference",),
        },
        "EconomicBoundaryValueV1": {
            "included_fields": ("shape", "lower_bound", "upper_bound"),
            "excluded_source_fields": (
                "schema_version",
                "source_precision",
                "source_time_label",
                "source_timezone",
                "evidence_reference",
            ),
        },
        "EconomicResidualValueV1": {
            "included_fields": (
                "kind",
                "scope_occurrence_id",
                "scope_action",
            ),
            "excluded_source_fields": ("reason", "evidence_reference"),
        },
        "EconomicAssociationValueV1": {
            "included_fields": (
                "kind",
                "target",
                "asserted_target_version_hash",
                "native_hint",
            ),
            "excluded_source_fields": ("reason",),
        },
    },
    "conditions": {
        "meaning": "conjunction",
        "canonicalization": "sorted_unique",
    },
    "excluded_settlement_report_fields": (
        "schema_version",
        "revision",
        "source_key",
        "security_id",
        "listing_id",
        "occurrence",
        "source_action_code",
        "payload.kind",
        "payload.action_kind",
        "payload.evidence_reference",
        "component_order",
    ),
}

type ActionRecord = CorporateActionTermsVersionV1 | EconomicEffectVersionV1
type ActionResolution = tuple[ActionRecord, str] | Literal["conflicting"] | None


def _recipient_economic_value_v1(
    recipient: EconomicRecipientV1,
) -> EconomicRecipientValueV1:
    return EconomicRecipientValueV1(
        kind=recipient.kind,
        security_id=recipient.security_id,
        source_property_key=recipient.source_property_key,
    )


def _fraction_economic_value_v1(
    treatment: FractionTreatmentV1,
) -> FractionEconomicValueV1:
    return FractionEconomicValueV1(
        kind=treatment.kind,
        source_rule=treatment.source_rule,
    )


def component_economic_value_v1(
    component: EconomicComponentV1,
) -> EconomicComparisonComponentV1:
    """Copy exactly the source fields participating in economic equality."""
    if isinstance(component, CashComponentV1):
        return CashEconomicValueV1(
            kind="cash",
            amount=component.amount,
            currency_namespace=component.currency_namespace,
            currency_code=component.currency_code,
            unit_basis=component.unit_basis,
            amount_basis=component.amount_basis,
            applicability=component.applicability,
            conditions=tuple(sorted(set(component.conditions))),
        )
    if isinstance(component, ShareComponentV1):
        return ShareEconomicValueV1(
            kind="shares",
            recipient=_recipient_economic_value_v1(component.recipient),
            ratio=component.ratio,
            ratio_meaning=component.ratio_meaning,
            unit_basis=component.unit_basis,
            fraction=_fraction_economic_value_v1(component.fraction_treatment),
            applicability=component.applicability,
            conditions=tuple(sorted(set(component.conditions))),
        )
    if isinstance(component, UnsupportedPropertyComponentV1):
        return PropertyEconomicValueV1(
            kind="unsupported_property",
            recipient=_recipient_economic_value_v1(component.recipient),
            source_description=component.source_description,
        )
    raise TypeError("unsupported economic component")


def boundary_economic_value_v1(
    boundary: TemporalBoundaryClaimV1,
) -> EconomicBoundaryValueV1:
    """Copy normalized bounds while excluding source precision metadata."""
    return EconomicBoundaryValueV1(
        shape=boundary.shape,
        lower_bound=boundary.lower_bound,
        upper_bound=boundary.upper_bound,
    )


def _association_economic_value_v1(
    association: EconomicAssociationV1,
) -> EconomicAssociationValueV1:
    return EconomicAssociationValueV1(
        kind=association.kind,
        target=association.target,
        asserted_target_version_hash=association.asserted_target_version_hash,
        native_hint=association.native_hint,
    )


def residual_economic_value_v1(
    residual: ResidualClaimV1,
) -> EconomicResidualValueV1:
    """Copy residual economics while excluding evidence and explanatory reason."""
    return EconomicResidualValueV1(
        kind=residual.kind,
        scope_occurrence_id=residual.scope_occurrence_id,
        scope_action=(
            None
            if residual.scope_action is None
            else _association_economic_value_v1(residual.scope_action)
        ),
    )


def settlement_occurrence_payload_v1(
    record: EconomicSettlementVersionV1,
) -> SettlementEconomicPayloadV1:
    """Return the canonical multiset comparison payload for a settlement report."""
    if record.payload is None:
        raise ValueError("withdrawn report has no economic comparison payload")
    projected = tuple(
        component_economic_value_v1(item)
        for item in record.payload.delivered_components
    )
    components = tuple(sorted(projected, key=canonical_json))
    return SettlementEconomicPayloadV1(
        schema_version="1",
        settled_boundary=boundary_economic_value_v1(record.settled_time),
        components=components,
        residual=residual_economic_value_v1(record.payload.residual),
    )


def _records_by_hash(context: EconomicResolutionContext) -> dict[str, object]:
    return {
        content_hash(record): record
        for dataset in context.datasets
        for record in dataset.records
    }


def _fact_dataset(
    context: EconomicResolutionContext, manifest_digest: str
) -> EconomicDatasetInput:
    matches = tuple(
        dataset
        for dataset in context.datasets
        if manifest_hash(dataset.manifest) == manifest_digest
    )
    if len(matches) != 1:
        raise ValueError("source policy fact manifest does not resolve uniquely")
    return matches[0]


def _coverage_results(
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
    proof: MarketSelectionProofV1,
    records_by_hash: Mapping[str, object],
) -> tuple[EconomicCoverageResolutionV1, ...]:
    selected = set(proof.revision_selected_record_hashes)
    results: list[EconomicCoverageResolutionV1] = []
    for family in ("terms", "effect", "settlement"):
        family_literal: Literal["terms", "effect", "settlement"] = family
        owner = policy_owner(source_policy, family_literal)
        fact_dataset = _fact_dataset(context, owner.fact_manifest_hash)
        candidates = tuple(
            record
            for record_hash, record in records_by_hash.items()
            if record_hash in selected
            and isinstance(record, EconomicCoverageVersionV1)
            and record.fact_family == family
            and record.source_key.source_id == owner.source_id
        )
        candidate_hashes = tuple(sorted(content_hash(item) for item in candidates))
        reasons: list[str] = []
        valid: list[EconomicCoverageVersionV1] = []
        for coverage in candidates:
            if coverage.security_id != query.security_id:
                reasons.append("coverage_security_mismatch")
            elif coverage.target_manifest_hash != owner.fact_manifest_hash:
                reasons.append("coverage_target_manifest_mismatch")
            elif set(coverage.action_kinds) != set(query.action_kinds):
                reasons.append("coverage_action_classes_mismatch")
            elif not coverage_contains(
                coverage, query.history_start, market_horizon(query)
            ):
                reasons.append("coverage_window_incomplete")
            elif coverage.snapshot_at > market_cutoff(query):
                reasons.append("coverage_snapshot_after_cutoff")
            elif (
                coverage.inventory_artifact_hashes
                != fact_dataset.decision.validated_artifact_hashes
                or coverage.inventory_record_hashes
                != fact_dataset.decision.validated_record_hashes
            ):
                reasons.append("coverage_inventory_mismatch")
            elif coverage.completeness != "complete":
                reasons.append(f"coverage_declared_{coverage.completeness}")
            elif coverage.revision_support != "captured_history":
                reasons.append("coverage_revision_history_incomplete")
            elif coverage.gaps or coverage.exceptions:
                reasons.append("coverage_has_gaps_or_exceptions")
            elif not economic_coverage_methodology_supported(
                coverage, context.supporting_artifacts
            ):
                reasons.append("coverage_methodology_unsupported")
            else:
                valid.append(coverage)
        if len(valid) == 1 and len(candidates) == 1:
            status: Literal["complete", "partial", "unknown"] = "complete"
            reasons = []
        elif candidates:
            status = "partial"
            if len(candidates) > 1:
                reasons.append("coverage_overlap_conflicting")
        else:
            status = "unknown"
            reasons.append("coverage_unavailable")
        occurrence_supported = bool(
            status == "complete"
            and valid[0].occurrence_key_semantics == "economic_occurrence_ids"
        )
        if status == "complete" and not occurrence_supported:
            status = "partial"
            reasons.append("coverage_occurrence_identity_unsupported")
        results.append(
            EconomicCoverageResolutionV1(
                family=family_literal,
                source_id=owner.source_id,
                selected_coverage_hashes=candidate_hashes,
                target_manifest_hash=owner.fact_manifest_hash,
                status=status,
                occurrence_identity_supported=occurrence_supported,
                reasons=tuple(reasons),
            )
        )
    return tuple(results)


def _authorized_records(
    proof: MarketSelectionProofV1,
    records_by_hash: Mapping[str, object],
    projections: Sequence[EconomicSafeFactProjectionV1],
) -> tuple[EconomicRecordV1, ...]:
    projected_hashes = {item.source_record_hash for item in projections}
    return tuple(
        record
        for record_hash, record in records_by_hash.items()
        if record_hash in projected_hashes
        and isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )


def _resolve_association(
    source: EconomicEffectVersionV1 | EconomicSettlementVersionV1,
    association_field: Literal["terms", "effect"],
    association: EconomicAssociationV1,
    selected_records: Sequence[object],
    source_policy: EconomicSourceSelectionPolicyV1,
    projections_by_source: Mapping[str, EconomicSafeFactProjectionV1],
) -> EconomicAssociationResolutionV1:
    source_hash = content_hash(source)
    if association.kind != "identified":
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="unresolved",
            selected_target_hash=None,
            reasons=(f"{association_field}_association_{association.kind}",),
        )
    target = association.target
    assert target is not None
    if target.family != association_field:
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="conflicting",
            selected_target_hash=None,
            reasons=("association_target_family_mismatch",),
        )
    owner = policy_owner(source_policy, association_field)
    if target.source_id != owner.source_id:
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="unresolved",
            selected_target_hash=None,
            reasons=("association_target_not_admitted",),
        )
    expected_type = (
        CorporateActionTermsVersionV1
        if association_field == "terms"
        else EconomicEffectVersionV1
    )
    matches = tuple(
        item
        for item in selected_records
        if isinstance(item, expected_type) and item.source_key == target
    )
    if not matches:
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="unresolved",
            selected_target_hash=None,
            reasons=("association_selected_target_unavailable",),
        )
    if len(matches) != 1:
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="conflicting",
            selected_target_hash=None,
            reasons=("association_selected_target_not_unique",),
        )
    selected_target = matches[0]
    selected_hash = content_hash(selected_target)
    if selected_target.security_id != source.security_id:
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="conflicting",
            selected_target_hash=None,
            reasons=("association_target_security_mismatch",),
        )
    if (
        association.asserted_target_version_hash is not None
        and association.asserted_target_version_hash != selected_hash
    ):
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="conflicting",
            selected_target_hash=None,
            reasons=("association_asserted_version_mismatch",),
        )
    projection = projections_by_source.get(selected_hash)
    if projection is None:
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="unresolved",
            selected_target_hash=None,
            reasons=("association_target_not_admitted",),
        )
    if association_field == "effect" and projection.applicability.status not in {
        "before_window",
        "in_window",
    }:
        return EconomicAssociationResolutionV1(
            source_record_hash=source_hash,
            association_field=association_field,
            status="unresolved",
            selected_target_hash=None,
            reasons=("association_effect_target_not_applicable",),
        )
    return EconomicAssociationResolutionV1(
        source_record_hash=source_hash,
        association_field=association_field,
        status="resolved",
        selected_target_hash=selected_hash,
        reasons=(),
    )


def _resolve_associations(
    records: Sequence[EconomicRecordV1],
    selected_records: Sequence[object],
    source_policy: EconomicSourceSelectionPolicyV1,
    projections_by_source: Mapping[str, EconomicSafeFactProjectionV1],
) -> tuple[EconomicAssociationResolutionV1, ...]:
    results: list[EconomicAssociationResolutionV1] = []
    for record in records:
        if isinstance(record, EconomicEffectVersionV1):
            results.append(
                _resolve_association(
                    record,
                    "terms",
                    record.terms_association,
                    selected_records,
                    source_policy,
                    projections_by_source,
                )
            )
        elif isinstance(record, EconomicSettlementVersionV1):
            results.extend(
                (
                    _resolve_association(
                        record,
                        "terms",
                        record.terms_association,
                        selected_records,
                        source_policy,
                        projections_by_source,
                    ),
                    _resolve_association(
                        record,
                        "effect",
                        record.effect_association,
                        selected_records,
                        source_policy,
                        projections_by_source,
                    ),
                )
            )
    return tuple(
        sorted(
            results,
            key=lambda item: (item.source_record_hash, item.association_field),
        )
    )


def _delivery_groups(
    settlements: Sequence[EconomicSettlementVersionV1],
    delivery_candidate_hashes: Set[str],
    projections_by_source: Mapping[str, EconomicSafeFactProjectionV1],
    occurrence_identity_supported: bool,
    associations: Sequence[EconomicAssociationResolutionV1],
) -> tuple[tuple[EconomicDeliveryGroupV1, ...], tuple[str, ...], tuple[str, ...]]:
    grouped: dict[tuple[str, UUID, str], list[EconomicSettlementVersionV1]] = (
        defaultdict(list)
    )
    uncomposed: list[str] = []
    reasons: list[str] = []
    for record in settlements:
        record_hash = content_hash(record)
        occurrence_id = record.occurrence.native_occurrence_id
        if (
            record.occurrence.kind != "identified"
            or occurrence_id is None
            or not occurrence_identity_supported
        ):
            if record_hash in delivery_candidate_hashes:
                uncomposed.append(record_hash)
                reasons.append("settlement_occurrence_identity_unavailable")
            continue
        key = (record.source_key.source_id, record.security_id, occurrence_id)
        grouped[key].append(record)

    results: list[EconomicDeliveryGroupV1] = []
    for key, reports in sorted(grouped.items(), key=lambda item: item[0]):
        report_hashes = {content_hash(item) for item in reports}
        if not report_hashes & delivery_candidate_hashes:
            continue
        payloads = {
            content_hash(settlement_occurrence_payload_v1(item)) for item in reports
        }
        if len(payloads) != 1:
            uncomposed.extend(content_hash(item) for item in reports)
            reasons.append("same_occurrence_economics_conflicting")
            continue
        representative = min(reports, key=content_hash)
        representative_hash = content_hash(representative)
        projection = projections_by_source[representative_hash]
        contributing_hashes = tuple(sorted(content_hash(item) for item in reports))
        projection_hashes = tuple(
            sorted(
                content_hash(projections_by_source[item_hash])
                for item_hash in contributing_hashes
            )
        )
        association_hashes = tuple(
            sorted(
                content_hash(item)
                for item in associations
                if item.source_record_hash in contributing_hashes
            )
        )
        results.append(
            EconomicDeliveryGroupV1(
                source_id=key[0],
                security_id=key[1],
                native_occurrence_id=key[2],
                settled_time=representative.settled_time,
                delivered_components=projection.known_components,
                component_gaps=projection.withheld_components,
                residual_status=projection.residual_status,
                contributing_record_hashes=contributing_hashes,
                projection_hashes=projection_hashes,
                association_result_hashes=association_hashes,
            )
        )
    return tuple(results), tuple(sorted(set(uncomposed))), tuple(sorted(set(reasons)))


def _effect_parts(
    effects: Sequence[EconomicEffectVersionV1],
    projections_by_source: Mapping[str, EconomicSafeFactProjectionV1],
) -> tuple[tuple[EconomicEffectProjectionV1, ...], tuple[str, ...], tuple[str, ...]]:
    occurred: list[EconomicEffectProjectionV1] = []
    cancelled: list[str] = []
    unknown: list[str] = []
    for record in sorted(effects, key=content_hash):
        if isinstance(record.payload, CancelledActionV1):
            cancelled.append(content_hash(record))
        elif isinstance(record.payload, UnknownEffectV1):
            unknown.append(content_hash(record))
        elif isinstance(record.payload, OccurredEffectV1):
            projection = projections_by_source[content_hash(record)]
            status_map: dict[
                str,
                Literal["before_window", "effective", "upcoming", "indeterminate"],
            ] = {
                "before_window": "before_window",
                "in_window": "effective",
                "upcoming": "upcoming",
                "indeterminate": "indeterminate",
            }
            occurred.append(
                EconomicEffectProjectionV1(
                    source_record_hash=content_hash(record),
                    effective_status=status_map[projection.applicability.status],
                    claim_status=projection.claim_status,
                    consideration_status=projection.consideration_status,
                    owed_components=projection.known_components,
                    component_gaps=projection.withheld_components,
                    safe_fact_projection_hash=content_hash(projection),
                )
            )
    return tuple(occurred), tuple(sorted(cancelled)), tuple(sorted(unknown))


def _effect_definitely_precedes(
    left: EconomicEffectVersionV1, right: EconomicEffectVersionV1
) -> bool:
    return (
        left.effective_time.upper_bound is not None
        and right.effective_time.lower_bound is not None
        and left.effective_time.upper_bound < right.effective_time.lower_bound
    )


def _claim_status(
    effects: Sequence[EconomicEffectVersionV1],
    projections_by_source: Mapping[str, EconomicSafeFactProjectionV1],
    indeterminate_constraints: Sequence[EconomicEffectVersionV1],
) -> tuple[
    Literal["continuing", "converted", "extinguished", "unknown"], tuple[str, ...]
]:
    applicable = tuple(
        item
        for item in effects
        if isinstance(item.payload, OccurredEffectV1)
        and projections_by_source[content_hash(item)].applicability.status
        in {"before_window", "in_window"}
    )
    if not applicable:
        return "unknown", ("claim_effect_unavailable",)
    for item in applicable:
        payload = item.payload
        assert isinstance(payload, OccurredEffectV1)
        if payload.claim_status == "unknown":
            return "unknown", ("claim_effect_unknown",)
    for index, left in enumerate(applicable):
        for right in applicable[index + 1 :]:
            left_payload = left.payload
            right_payload = right.payload
            assert isinstance(left_payload, OccurredEffectV1)
            assert isinstance(right_payload, OccurredEffectV1)
            if left_payload.claim_status == right_payload.claim_status:
                continue
            left_before_right = (
                left.effective_time.upper_bound is not None
                and right.effective_time.lower_bound is not None
                and left.effective_time.upper_bound < right.effective_time.lower_bound
            )
            right_before_left = (
                right.effective_time.upper_bound is not None
                and left.effective_time.lower_bound is not None
                and right.effective_time.upper_bound < left.effective_time.lower_bound
            )
            if not left_before_right and not right_before_left:
                return "unknown", ("claim_effect_chronology_conflicting",)
    ordered = sorted(
        applicable,
        key=lambda item: (
            item.effective_time.lower_bound is None,
            item.effective_time.lower_bound,
        ),
    )
    terminal_seen = False
    latest: Literal["continuing", "converted", "extinguished", "unknown"] = "unknown"
    for record in ordered:
        payload = record.payload
        assert isinstance(payload, OccurredEffectV1)
        if terminal_seen and payload.claim_status == "continuing":
            return "unknown", ("claim_terminal_state_resurrected",)
        latest = payload.claim_status
        terminal_seen = terminal_seen or latest in {"converted", "extinguished"}
    terminal_statuses = {"converted", "extinguished"}
    definite_terminals = tuple(
        item
        for item in applicable
        if isinstance(item.payload, OccurredEffectV1)
        and item.payload.claim_status in terminal_statuses
    )
    for item in indeterminate_constraints:
        payload = item.payload
        if not isinstance(payload, OccurredEffectV1):
            continue
        if payload.claim_status == latest:
            continue
        if payload.claim_status in terminal_statuses and any(
            isinstance(later.payload, OccurredEffectV1)
            and later.payload.claim_status == "continuing"
            and _effect_definitely_precedes(item, later)
            for later in applicable
        ):
            return "unknown", ("claim_terminal_state_resurrected",)
        if (
            payload.claim_status == "continuing"
            and definite_terminals
            and all(
                _effect_definitely_precedes(item, terminal)
                for terminal in definite_terminals
            )
        ):
            continue
        return "unknown", ("claim_effect_chronology_indeterminate",)
    return latest, ()


def _association_by_source(
    associations: Sequence[EconomicAssociationResolutionV1],
) -> dict[tuple[str, str], EconomicAssociationResolutionV1]:
    return {
        (item.source_record_hash, item.association_field): item for item in associations
    }


def _action_from_effect(
    effect: EconomicEffectVersionV1,
    association_map: Mapping[tuple[str, str], EconomicAssociationResolutionV1],
    selected_by_hash: Mapping[str, object],
    *,
    allow_effect_anchor: bool = True,
) -> ActionResolution:
    resolution = association_map.get((content_hash(effect), "terms"))
    if resolution is not None:
        if resolution.status == "conflicting":
            return "conflicting"
        if resolution.status == "resolved":
            assert resolution.selected_target_hash is not None
            target = selected_by_hash[resolution.selected_target_hash]
            assert isinstance(target, CorporateActionTermsVersionV1)
            return target, resolution.selected_target_hash
        if effect.terms_association.kind == "identified":
            return None
    if (
        allow_effect_anchor
        and isinstance(effect.payload, OccurredEffectV1)
        and effect.terms_association.kind != "identified"
    ):
        return effect, content_hash(effect)
    return None


def _settlement_action(
    settlement: EconomicSettlementVersionV1,
    association_map: Mapping[tuple[str, str], EconomicAssociationResolutionV1],
    selected_by_hash: Mapping[str, object],
) -> ActionResolution:
    source_hash = content_hash(settlement)
    candidates: list[tuple[ActionRecord, str]] = []
    direct = association_map.get((source_hash, "terms"))
    if direct is not None and direct.status == "conflicting":
        return "conflicting"
    if direct is not None and direct.status == "resolved":
        assert direct.selected_target_hash is not None
        target = selected_by_hash[direct.selected_target_hash]
        assert isinstance(target, CorporateActionTermsVersionV1)
        candidates.append((target, direct.selected_target_hash))
    indirect = association_map.get((source_hash, "effect"))
    if indirect is not None and indirect.status == "conflicting":
        return "conflicting"
    if indirect is not None and indirect.status == "resolved":
        assert indirect.selected_target_hash is not None
        effect = selected_by_hash[indirect.selected_target_hash]
        assert isinstance(effect, EconomicEffectVersionV1)
        action = _action_from_effect(
            effect,
            association_map,
            selected_by_hash,
            allow_effect_anchor=not candidates,
        )
        if action == "conflicting":
            return "conflicting"
        if action is not None:
            candidates.append(action)
    identities = {item[0].source_key for item in candidates}
    if len(identities) > 1:
        return "conflicting"
    return candidates[0] if candidates else None


def _normalize_residual_scope(
    association: EconomicAssociationV1 | None,
    selected_records: Sequence[object],
    association_map: Mapping[tuple[str, str], EconomicAssociationResolutionV1],
    selected_by_hash: Mapping[str, object],
    projections_by_source: Mapping[str, EconomicSafeFactProjectionV1],
) -> ActionResolution:
    if association is None or association.kind != "identified":
        return None
    target = association.target
    assert target is not None
    matches = tuple(
        item
        for item in selected_records
        if isinstance(item, CorporateActionTermsVersionV1 | EconomicEffectVersionV1)
        and item.source_key == target
    )
    if len(matches) != 1:
        return None
    item = matches[0]
    item_hash = content_hash(item)
    if association.asserted_target_version_hash not in {None, item_hash}:
        return "conflicting"
    projection = projections_by_source.get(item_hash)
    if projection is None:
        return None
    if isinstance(item, CorporateActionTermsVersionV1):
        return item, item_hash
    if projection.applicability.status not in {"before_window", "in_window"}:
        return None
    return _action_from_effect(item, association_map, selected_by_hash)


def _record_residual(
    record: EconomicEffectVersionV1 | EconomicSettlementVersionV1,
) -> ResidualClaimV1 | None:
    if isinstance(record.payload, OccurredEffectV1):
        return record.payload.residual
    if isinstance(record, EconomicSettlementVersionV1) and record.payload is not None:
        return record.payload.residual
    return None


def _record_boundary(
    record: EconomicEffectVersionV1 | EconomicSettlementVersionV1,
) -> TemporalBoundaryClaimV1:
    if isinstance(record, EconomicEffectVersionV1):
        return record.effective_time
    return record.settled_time


def _residual_resolutions(
    settlements: Sequence[EconomicSettlementVersionV1],
    effects: Sequence[EconomicEffectVersionV1],
    indeterminate_settlements: Sequence[EconomicSettlementVersionV1],
    indeterminate_effects: Sequence[EconomicEffectVersionV1],
    associations: Sequence[EconomicAssociationResolutionV1],
    selected_records: Sequence[object],
    projections_by_source: Mapping[str, EconomicSafeFactProjectionV1],
) -> tuple[ActionResidualResolutionV1, ...]:
    association_map = _association_by_source(associations)
    selected_by_hash = {content_hash(item): item for item in selected_records}
    grouped: dict[
        EconomicSourceKeyV1,
        tuple[ActionRecord, str, list[EconomicSettlementVersionV1]],
    ] = {}
    forced_conflicts: set[EconomicSourceKeyV1] = set()
    for effect in effects:
        if _record_residual(effect) is None:
            continue
        action = _action_from_effect(effect, association_map, selected_by_hash)
        if action is None:
            continue
        if action == "conflicting":
            grouped.setdefault(
                effect.source_key,
                (effect, content_hash(effect), []),
            )
            forced_conflicts.add(effect.source_key)
            continue
        action_record, action_hash = action
        key = action_record.source_key
        grouped.setdefault(key, (action_record, action_hash, []))
    uncertain_settlements: list[EconomicSettlementVersionV1] = []
    for settlement in settlements:
        settlement_action = _settlement_action(
            settlement, association_map, selected_by_hash
        )
        if settlement_action is None or settlement_action == "conflicting":
            uncertain_settlements.append(settlement)
            continue
        action_record, action_hash = settlement_action
        key = action_record.source_key
        if key not in grouped:
            grouped[key] = (action_record, action_hash, [])
        grouped[key][2].append(settlement)

    results: list[ActionResidualResolutionV1] = []
    residual_records: tuple[EconomicEffectVersionV1 | EconomicSettlementVersionV1, ...]
    residual_records = (*effects, *settlements)
    for action_key, (_action_record, action_hash, covered) in grouped.items():
        closure_hashes: list[str] = []
        conflicting = action_key in forced_conflicts
        outstanding_records: list[
            EconomicEffectVersionV1 | EconomicSettlementVersionV1
        ] = []
        for record in residual_records:
            residual = _record_residual(record)
            if residual is None:
                continue
            record_action: tuple[ActionRecord, str] | Literal["conflicting"] | None
            if isinstance(record, EconomicSettlementVersionV1):
                record_action = _settlement_action(
                    record, association_map, selected_by_hash
                )
            else:
                record_action = _action_from_effect(
                    record, association_map, selected_by_hash
                )
            if record_action == "conflicting":
                conflicting = True
                continue
            if record_action is None:
                continue
            if record_action[0].source_key != action_key:
                continue
            if residual.kind == "closed_for_action":
                residual_scope = _normalize_residual_scope(
                    residual.scope_action,
                    selected_records,
                    association_map,
                    selected_by_hash,
                    projections_by_source,
                )
                if residual_scope == "conflicting":
                    conflicting = True
                    continue
                if residual_scope is None or residual_scope[0].source_key != action_key:
                    conflicting = True
                    continue
                boundary = _record_boundary(record)
                if boundary.lower_bound is None or any(
                    item.settled_time.upper_bound is None
                    or item.settled_time.upper_bound > boundary.lower_bound
                    for item in covered
                ):
                    conflicting = True
                    continue
                closure_hashes.append(content_hash(record))
            elif residual.kind == "outstanding":
                outstanding_records.append(record)
        valid_closure_records = tuple(
            record
            for record in residual_records
            if content_hash(record) in closure_hashes
        )
        later_outstanding = False
        for closure in valid_closure_records:
            closure_lower = _record_boundary(closure).lower_bound
            for item in outstanding_records:
                item_upper = _record_boundary(item).upper_bound
                if (
                    closure_lower is None
                    or item_upper is None
                    or item_upper >= closure_lower
                ):
                    later_outstanding = True
        possible_unresolved_later = False
        if closure_hashes:
            for settlement in uncertain_settlements:
                if settlement.security_id != _action_record.security_id:
                    continue
                settlement_upper = settlement.settled_time.upper_bound
                closed_by_later_evidence = False
                if settlement_upper is not None:
                    for closure in valid_closure_records:
                        closure_lower = _record_boundary(closure).lower_bound
                        if (
                            closure_lower is not None
                            and settlement_upper <= closure_lower
                        ):
                            closed_by_later_evidence = True
                            break
                if not closed_by_later_evidence:
                    possible_unresolved_later = True
                    break
        possible_indeterminate_settlement = False
        possible_indeterminate_effect = False
        if closure_hashes:
            constraints: tuple[
                EconomicEffectVersionV1 | EconomicSettlementVersionV1, ...
            ] = (*indeterminate_effects, *indeterminate_settlements)
            for record in constraints:
                if record.security_id != _action_record.security_id:
                    continue
                constraint_action: ActionResolution
                if isinstance(record, EconomicSettlementVersionV1):
                    constraint_action = _settlement_action(
                        record, association_map, selected_by_hash
                    )
                else:
                    constraint_action = _action_from_effect(
                        record, association_map, selected_by_hash
                    )
                if constraint_action is not None and constraint_action != "conflicting":
                    if constraint_action[0].source_key != action_key:
                        continue
                boundary_upper = _record_boundary(record).upper_bound
                closed_by_later_evidence = False
                if boundary_upper is not None:
                    for closure in valid_closure_records:
                        closure_lower = _record_boundary(closure).lower_bound
                        if (
                            closure_lower is not None
                            and boundary_upper <= closure_lower
                        ):
                            closed_by_later_evidence = True
                            break
                if closed_by_later_evidence:
                    continue
                if isinstance(record, EconomicSettlementVersionV1):
                    possible_indeterminate_settlement = True
                else:
                    possible_indeterminate_effect = True
        if conflicting:
            status: Literal["closed", "outstanding", "unknown", "conflicting"] = (
                "conflicting"
            )
            reasons: tuple[str, ...] = (
                "residual_action_scope_or_chronology_conflicting",
            )
        elif possible_unresolved_later or possible_indeterminate_settlement:
            status = "unknown"
            reasons = ("unresolved_later_installment_prevents_closure",)
        elif possible_indeterminate_effect:
            status = "unknown"
            reasons = ("indeterminate_action_fact_prevents_closure",)
        elif closure_hashes and not later_outstanding:
            status = "closed"
            reasons = ()
        elif outstanding_records:
            status = "outstanding"
            reasons = ("action_consideration_outstanding",)
        else:
            status = "unknown"
            reasons = ("action_residual_unknown",)
        results.append(
            ActionResidualResolutionV1(
                action_scope=action_key,
                selected_action_record_hash=action_hash,
                status=status,
                covered_settlement_hashes=tuple(
                    sorted(content_hash(item) for item in covered)
                ),
                closure_record_hashes=tuple(sorted(set(closure_hashes))),
                reasons=reasons,
            )
        )
    return tuple(sorted(results, key=lambda item: canonical_json(item.action_scope)))


def _support_status(
    records: Sequence[EconomicRecordV1],
) -> Literal["supported", "unsupported", "indeterminate"]:
    shapes = {classify_economic_shape(item) for item in records}
    if "unsupported" in shapes:
        return "unsupported"
    if "indeterminate" in shapes or not shapes:
        return "indeterminate"
    return "supported"


def resolve_economic_facts(
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> EconomicOutcomeResolutionV1:
    """Build a query-bound composed outcome from the accepted selector."""
    EconomicSourceSelectionPolicyV1.model_validate(
        source_policy.model_dump(mode="python")
    )
    proof = select_market_records(query, context, source_policy)
    projections = project_market_facts(query, context, source_policy)
    records_by_hash = _records_by_hash(context)
    coverage_results = _coverage_results(
        query, context, source_policy, proof, records_by_hash
    )
    authorized = _authorized_records(proof, records_by_hash, projections)
    projections_by_source = {item.source_record_hash: item for item in projections}
    terms = tuple(
        item for item in authorized if isinstance(item, CorporateActionTermsVersionV1)
    )
    effects = tuple(
        item for item in authorized if isinstance(item, EconomicEffectVersionV1)
    )
    settlements = tuple(
        item for item in authorized if isinstance(item, EconomicSettlementVersionV1)
    )
    relevant_effects = tuple(
        item
        for item in effects
        if projections_by_source[content_hash(item)].applicability.status
        in {"before_window", "in_window"}
    )
    relevant_settlements = tuple(
        item
        for item in settlements
        if projections_by_source[content_hash(item)].applicability.status
        in {"before_window", "in_window"}
    )
    in_window_settlements = tuple(
        item
        for item in relevant_settlements
        if projections_by_source[content_hash(item)].applicability.status == "in_window"
    )
    indeterminate_effects = tuple(
        item
        for item in effects
        if projections_by_source[content_hash(item)].applicability.status
        == "indeterminate"
        and (
            item.effective_time.lower_bound is None
            or item.effective_time.lower_bound <= market_horizon(query)
        )
    )
    indeterminate_settlements = tuple(
        item
        for item in settlements
        if projections_by_source[content_hash(item)].applicability.status
        == "indeterminate"
        and (
            item.settled_time.lower_bound is None
            or item.settled_time.lower_bound <= market_horizon(query)
        )
    )
    indeterminate_settlement_hashes = tuple(
        sorted(
            content_hash(item)
            for item in settlements
            if projections_by_source[content_hash(item)].applicability.status
            == "indeterminate"
        )
    )
    occurrence_supported = next(
        item.occurrence_identity_supported
        for item in coverage_results
        if item.family == "settlement"
    )
    selected_records = tuple(
        records_by_hash[item_hash]
        for item_hash in proof.revision_selected_record_hashes
        if item_hash in records_by_hash
    )
    associations = _resolve_associations(
        authorized,
        selected_records,
        source_policy,
        projections_by_source,
    )
    residual_resolutions = _residual_resolutions(
        relevant_settlements,
        relevant_effects,
        indeterminate_settlements,
        indeterminate_effects,
        associations,
        selected_records,
        projections_by_source,
    )
    delivery_groups, uncomposed, grouping_reasons = _delivery_groups(
        settlements,
        {content_hash(item) for item in in_window_settlements},
        projections_by_source,
        occurrence_supported,
        associations,
    )
    uncomposed = tuple(sorted(set((*uncomposed, *indeterminate_settlement_hashes))))
    effect_projections, cancelled, unknown = _effect_parts(
        effects, projections_by_source
    )
    claim_status, claim_reasons = _claim_status(
        effects, projections_by_source, indeterminate_effects
    )
    selected_terms = tuple(
        sorted(
            content_hash(item)
            for item in terms
            if projections_by_source[content_hash(item)].applicability.status
            in {"before_window", "in_window"}
        )
    )
    upcoming_terms = tuple(
        sorted(
            content_hash(item)
            for item in terms
            if projections_by_source[content_hash(item)].applicability.status
            == "upcoming"
        )
    )
    completeness_reasons = list(grouping_reasons)
    if any(item.status != "complete" for item in coverage_results):
        completeness_reasons.append("source_coverage_incomplete")
    if any(item.withheld_components for item in projections):
        completeness_reasons.append("economic_component_gaps")
    if any(
        item.payload is not None and item.payload.kind == "incomplete" for item in terms
    ):
        completeness_reasons.append("source_terms_incomplete")
    if any(
        isinstance(item.payload, UnknownEffectV1)
        or (
            isinstance(item.payload, OccurredEffectV1)
            and (
                item.payload.claim_status == "unknown"
                or item.payload.consideration_status == "unknown"
            )
        )
        for item in relevant_effects
    ):
        completeness_reasons.append("source_effect_incomplete")
    closed_settlement_hashes = {
        item_hash
        for item in residual_resolutions
        if item.status == "closed"
        for item_hash in item.covered_settlement_hashes
    }
    if any(
        group.residual_status in {"outstanding", "unknown"}
        and not set(group.contributing_record_hashes).issubset(closed_settlement_hashes)
        for group in delivery_groups
    ) or any(item.status != "closed" for item in residual_resolutions):
        completeness_reasons.append("settlement_residual_unresolved")
    if proof.unresolved_chain_hashes:
        completeness_reasons.append("source_revision_selection_unresolved")
    if any(item.status == "indeterminate" for item in proof.applicability):
        completeness_reasons.append("economic_time_indeterminate")
    if any(item.status != "resolved" for item in associations):
        completeness_reasons.append("economic_association_unresolved")
    if effects and claim_status == "unknown":
        completeness_reasons.extend(claim_reasons)
    usable = bool(
        selected_terms
        or effect_projections
        or cancelled
        or delivery_groups
        or uncomposed
    )
    completeness: Literal["known", "partial", "unknown"]
    if completeness_reasons:
        completeness = "partial" if usable else "unknown"
    else:
        completeness = "known"
    result_reasons = tuple(sorted(set(completeness_reasons)))
    return EconomicOutcomeResolutionV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        selection_proof_hash=content_hash(proof),
        source_selection_policy_hash=content_hash(source_policy),
        input_context_hash=query.input_context_hash,
        composition_algorithm="drift-m1c-economic-composition-v1",
        composition_algorithm_spec_hash=content_hash(_COMPOSITION_SPEC),
        composition_implementation_hash=economic_implementation_hash(),
        selected_terms_hashes=selected_terms,
        upcoming_terms_hashes=upcoming_terms,
        effect_projections=effect_projections,
        cancelled_action_hashes=cancelled,
        unknown_effect_hashes=unknown,
        delivery_groups=delivery_groups,
        uncomposed_settlement_hashes=uncomposed,
        associations=associations,
        coverage_results=coverage_results,
        residual_resolutions=residual_resolutions,
        safe_projection_hashes=tuple(
            sorted(content_hash(item) for item in projections)
        ),
        claim_status=claim_status,
        evidence_completeness=completeness,
        support_status=_support_status(
            tuple(
                item
                for item in authorized
                if projections_by_source[content_hash(item)].applicability.status
                != "upcoming"
                or isinstance(item, CorporateActionTermsVersionV1)
            )
        ),
        reasons=result_reasons,
    )


def verify_economic_outcome(
    result: EconomicOutcomeResolutionV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> None:
    """Replay and compare the entire economic outcome result."""
    expected = resolve_economic_facts(result.query, context, source_policy)
    if result != expected or content_hash(result) != content_hash(expected):
        raise ValueError("economic outcome does not match exact replay")
