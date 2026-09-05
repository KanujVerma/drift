"""Causal selection and consumer-safe replay for M1c economic evidence."""

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from drift.datasets.assertions import select_assertion_version
from drift.datasets.hashing import manifest_hash
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import (
    AssertionSelectionResultV1,
    AssertionVersionProjectionV1,
    TemporalIntervalClaimV1,
)
from drift.domain.dataset_validation import DatasetValidationError
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicComponentGapV1,
    EconomicComponentV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
    economic_implementation_hash,
)
from drift.domain.economic_coverage import (
    EconomicInputRecordV1,
    EconomicSourceSelectionPolicyV1,
    policy_owner,
)
from drift.domain.economic_events import (
    CancelledActionV1,
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    EconomicRecordV1,
    EconomicSettlementVersionV1,
    OccurredEffectV1,
    UnknownEffectV1,
)
from drift.domain.economic_queries import (
    EconomicApplicabilityV1,
    EconomicSafeFactProjectionV1,
    MarketDatasetSelectionV1,
    MarketDecisionQueryV1,
    MarketDecisionReferenceV1,
    MarketOutcomeQueryV1,
    MarketOutcomeReferenceV1,
    MarketSelectionProofV1,
    MarketSelectionQueryV1,
    RetainedEconomicIdentityV1,
    market_cutoff,
    market_horizon,
)
from drift.domain.securities import (
    IdentityAssignmentEffect,
    IdentityAssignmentVersionV1,
    identity_reference,
)
from drift.domain.temporal import CutoffEligibility, evaluate_availability
from drift.markets.economic_validation import (
    EconomicDatasetInput,
    EconomicResolutionContext,
    economic_context_hash,
    validate_economic_context,
)
from drift.serialization.canonical import content_hash

_SELECTION_SPEC = {
    "profile": "drift-m1c-economic-selection-v1",
    "rule": "finite causal source selection with retained identity",
    "projection_evidence_locator_rule": (
        "derived known components use drift+sha256 content-addressed locators"
    ),
    "retained_identity_rule": (
        "select complete competing assignment subjects; fail closed on definite or "
        "ambiguous interval overlap; stop unassigned prefixes at target changes"
    ),
    "actual_chronology_rule": (
        "selected actual records are vetoed by any independently trusted channel "
        "whose known upper availability strictly predates actual lower"
    ),
}
_PROJECTION_SPEC = {
    "profile": "drift-m1c-economic-safe-projection-v1",
    "rule": "component-local identity withholding without UUID disclosure",
    "evidence_locator_rule": (
        "recursively replace derived known-component artifact locations with "
        "drift+sha256://<content_hash> while preserving artifact identity"
    ),
}

type IdentityProofSelector = Callable[
    [Literal["security", "listing"], UUID], RetainedEconomicIdentityV1
]


def select_market_records(
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> MarketSelectionProofV1:
    """Return the query-bound M1c source selection proof."""
    proof, _ = _selection_pipeline(query, context, source_policy)
    return proof


def _selection_pipeline(
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> tuple[MarketSelectionProofV1, tuple[EconomicSafeFactProjectionV1, ...]]:
    """Build the acyclic audit proof and its separately hash-bound projections."""
    _require_selection_bindings(query, context, source_policy)
    dataset_selections = tuple(
        sorted(
            (
                (dataset, _select_dataset(dataset, query, context))
                for dataset in context.datasets
            ),
            key=lambda item: (
                item[1].role,
                item[1].source_id,
                item[1].manifest_hash,
            ),
        )
    )
    dataset_proofs = tuple(proof for _, proof in dataset_selections)
    selected_by_hash = {
        content_hash(record): record
        for dataset in context.datasets
        for record in dataset.records
    }
    audit_selected = tuple(
        sorted(
            record_hash
            for proof in dataset_proofs
            for record_hash in proof.selected_record_hashes
        )
    )
    identity_proofs: dict[tuple[str, UUID], RetainedEconomicIdentityV1] = {}

    def identity_proof(
        kind: Literal["security", "listing"], item_id: UUID
    ) -> RetainedEconomicIdentityV1:
        key = (kind, item_id)
        proof = identity_proofs.get(key)
        if proof is None:
            proof = _select_retained_identity_from_validated_context(
                kind, item_id, query, context
            )
            identity_proofs[key] = proof
        return proof

    identity_proof("security", query.security_id)
    applicability: list[EconomicApplicabilityV1] = []
    projections: list[EconomicSafeFactProjectionV1] = []
    raw_hashes: list[str] = []
    for dataset, dataset_proof in dataset_selections:
        for record_hash in dataset_proof.selected_record_hashes:
            record = selected_by_hash[record_hash]
            if not isinstance(
                record,
                CorporateActionTermsVersionV1
                | EconomicEffectVersionV1
                | EconomicSettlementVersionV1,
            ):
                continue
            if not _is_source_authorized(record, dataset, query, source_policy):
                continue
            relation = _record_applicability(record, query, context)
            applicability.append(relation)
            projection = _project_record(record, relation, query, identity_proof)
            if projection is not None:
                projections.append(projection)
            if _raw_materializable(record, relation, projection):
                raw_hashes.append(record_hash)
    canonical_projections = tuple(
        sorted(projections, key=lambda item: item.source_record_hash)
    )
    unresolved = tuple(
        sorted(
            content_hash(selection)
            for dataset_proof in dataset_proofs
            for selection in dataset_proof.chain_selections
            if _selection_has_unresolved_version(selection, context)
        )
    )
    result = MarketSelectionProofV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        input_context_hash=economic_context_hash(context),
        source_selection_policy_hash=query.source_selection_policy_hash,
        selection_algorithm="drift-m1c-economic-selection-v1",
        selection_algorithm_spec_hash=content_hash(_SELECTION_SPEC),
        selection_implementation_hash=economic_implementation_hash(),
        dataset_proofs=dataset_proofs,
        identity_proofs=tuple(
            sorted(
                identity_proofs.values(),
                key=lambda item: (item.identity_kind, str(item.identity_id)),
            )
        ),
        revision_selected_record_hashes=audit_selected,
        applicability=tuple(
            sorted(applicability, key=lambda item: item.source_record_hash)
        ),
        raw_materializable_record_hashes=tuple(sorted(raw_hashes)),
        projection_hashes=tuple(
            sorted(content_hash(item) for item in canonical_projections)
        ),
        unresolved_chain_hashes=unresolved,
    )
    return result, canonical_projections


def _selection_has_unresolved_version(
    selection: AssertionSelectionResultV1,
    context: EconomicResolutionContext,
) -> bool:
    """Return whether any complete-chain version remains indeterminate at cutoff."""
    for version in selection.considered_versions:
        evidence = next(
            (
                item
                for item in version.revision.availability
                if item.channel == selection.requested_channel
            ),
            None,
        )
        if evidence is None:
            return True
        result = evaluate_availability(
            evidence,
            selection.requested_channel,
            selection.policy,
            selection.cutoff,
            context.retained_evidence,
        )
        if result.classification is CutoffEligibility.INDETERMINATE:
            return True
    return False


def _require_selection_bindings(
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> None:
    validate_economic_context(context)
    if query.input_context_hash != economic_context_hash(context):
        raise DatasetValidationError.single("economic_selection_context_mismatch")
    if query.availability_policy_id != context.availability_policy.policy_id or (
        query.availability_policy_hash != content_hash(context.availability_policy)
    ):
        raise DatasetValidationError.single("economic_selection_availability_mismatch")
    if query.source_selection_policy_hash != content_hash(source_policy):
        raise DatasetValidationError.single("economic_selection_source_policy_mismatch")
    if (
        query.security_id != source_policy.security_id
        or set(query.action_kinds) != set(source_policy.action_kinds)
        or query.history_start != source_policy.history_start
        or market_horizon(query) != source_policy.through
    ):
        raise DatasetValidationError.single("economic_selection_scope_mismatch")
    actual_bindings = {
        (
            manifest_hash(dataset.manifest),
            content_hash(dataset.decision),
            content_hash(dataset.bundle),
            dataset.manifest.dataset_role.name,
            dataset.manifest.source.source_id,
        )
        for dataset in context.datasets
    }
    expected_bindings = {
        (
            binding.manifest_hash,
            binding.decision_hash,
            binding.bundle_hash,
            binding.role,
            binding.source_id,
        )
        for binding in source_policy.input_dataset_bindings
    }
    if actual_bindings != expected_bindings:
        raise DatasetValidationError.single(
            "economic_selection_dataset_binding_mismatch"
        )


def _select_dataset(
    dataset: EconomicDatasetInput,
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
) -> MarketDatasetSelectionV1:
    by_logical: dict[UUID, list[EconomicInputRecordV1]] = defaultdict(list)
    for record in dataset.records:
        by_logical[record.revision.logical_record_id].append(record)
    selections = []
    for logical_id in sorted(by_logical, key=str):
        chain = by_logical[logical_id]
        selections.append(
            select_assertion_version(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=record.revision,
                        record_hash=content_hash(record),
                    )
                    for record in chain
                ),
                query.requested_channel,
                context.availability_policy,
                market_cutoff(query),
                context.retained_evidence,
            )
        )
    selected = tuple(
        sorted(
            selection.selected_record_hash
            for selection in selections
            if selection.selected_record_hash is not None
        )
    )
    return MarketDatasetSelectionV1(
        manifest_hash=manifest_hash(dataset.manifest),
        decision_hash=content_hash(dataset.decision),
        bundle_hash=content_hash(dataset.bundle),
        role=dataset.manifest.dataset_role.name,
        source_id=dataset.manifest.source.source_id,
        considered_record_hashes=dataset.decision.validated_record_hashes,
        chain_selections=tuple(selections),
        selected_record_hashes=selected,
    )


def select_retained_economic_identity(
    identity_kind: Literal["security", "listing"],
    identity_id: UUID,
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
) -> RetainedEconomicIdentityV1:
    """Replay complete assignment chains to prove a retained identity at K or V."""
    validate_economic_context(context)
    if query.input_context_hash != economic_context_hash(context):
        raise DatasetValidationError.single("identity_context_mismatch")
    if query.availability_policy_id != context.availability_policy.policy_id or (
        query.availability_policy_hash != content_hash(context.availability_policy)
    ):
        raise DatasetValidationError.single("identity_availability_policy_mismatch")
    return _select_retained_identity_from_validated_context(
        identity_kind, identity_id, query, context
    )


def _select_retained_identity_from_validated_context(
    identity_kind: Literal["security", "listing"],
    identity_id: UUID,
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
) -> RetainedEconomicIdentityV1:
    """Select identity evidence after the enclosing context has been replayed."""
    target_subjects = {
        (identity_kind, record.source_namespace, record.source_key)
        for record in context.identity.records
        if identity_reference(record.identity).kind.value == identity_kind
        and identity_reference(record.identity).internal_id == identity_id
    }
    relevant_logical_ids = {
        record.revision.logical_record_id
        for record in context.identity.records
        if (
            identity_reference(record.identity).kind.value,
            record.source_namespace,
            record.source_key,
        )
        in target_subjects
    }
    chains: dict[UUID, list[IdentityAssignmentVersionV1]] = defaultdict(list)
    for record in context.identity.records:
        if record.revision.logical_record_id in relevant_logical_ids:
            chains[record.revision.logical_record_id].append(record)
    selections = list(
        select_assertion_version(
            tuple(
                AssertionVersionProjectionV1(
                    revision=record.revision,
                    record_hash=content_hash(record),
                )
                for record in chains[logical_id]
            ),
            query.requested_channel,
            context.availability_policy,
            market_cutoff(query),
            context.retained_evidence,
        )
        for logical_id in sorted(chains, key=str)
    )
    records_by_hash = {
        content_hash(record): record for record in context.identity.records
    }
    selected_hash_set = {
        selection.selected_record_hash
        for selection in selections
        if selection.selected_record_hash is not None
    }
    selected_records = tuple(
        records_by_hash[record_hash] for record_hash in selected_hash_set
    )
    conflict_reasons: set[str] = set()
    selected_by_subject: dict[
        tuple[str, str, str], list[IdentityAssignmentVersionV1]
    ] = defaultdict(list)
    for record in selected_records:
        reference = identity_reference(record.identity)
        selected_by_subject[
            (reference.kind.value, record.source_namespace, record.source_key)
        ].append(record)
    for subject_records in selected_by_subject.values():
        for index, left in enumerate(subject_records):
            left_reference = identity_reference(left.identity)
            for right in subject_records[index + 1 :]:
                right_reference = identity_reference(right.identity)
                if left_reference.internal_id == right_reference.internal_id:
                    continue
                relation = _assignment_interval_relation(
                    left.effective_interval, right.effective_interval
                )
                if relation == "overlap":
                    conflict_reasons.add("competing_identity_assignments_overlap")
                elif relation == "indeterminate":
                    conflict_reasons.add(
                        "competing_identity_assignment_overlap_indeterminate"
                    )
    known = False
    for selection in tuple(selections):
        selected_hash = selection.selected_record_hash
        if selected_hash is None:
            continue
        current = records_by_hash[selected_hash]
        reference = identity_reference(current.identity)
        if (
            reference.kind.value != identity_kind
            or reference.internal_id != identity_id
        ):
            continue
        if current.assignment_effect is IdentityAssignmentEffect.ASSIGNED:
            known = True
            continue
        prefix = tuple(
            record
            for record in chains[current.revision.logical_record_id]
            if record.revision.source_sequence < current.revision.source_sequence
        )
        while prefix:
            prior = select_assertion_version(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=record.revision,
                        record_hash=content_hash(record),
                    )
                    for record in prefix
                ),
                query.requested_channel,
                context.availability_policy,
                market_cutoff(query),
                context.retained_evidence,
            )
            selections.append(prior)
            if prior.selected_record_hash is None:
                break
            selected_hash_set.add(prior.selected_record_hash)
            previous = records_by_hash[prior.selected_record_hash]
            previous_reference = identity_reference(previous.identity)
            if previous_reference.kind.value != identity_kind or (
                previous_reference.internal_id != identity_id
            ):
                break
            if previous.assignment_effect is IdentityAssignmentEffect.ASSIGNED:
                known = True
                break
            prefix = tuple(
                record
                for record in prefix
                if record.revision.source_sequence < previous.revision.source_sequence
            )
    selected_hashes = tuple(sorted(selected_hash_set))
    status: Literal["known", "unknown", "conflicting"]
    if conflict_reasons:
        status = "conflicting"
    else:
        status = "known" if known else "unknown"
    reasons = (
        tuple(sorted(conflict_reasons))
        if status == "conflicting"
        else ()
        if status == "known"
        else ("identity_assignment_unavailable",)
    )
    return RetainedEconomicIdentityV1(
        schema_version="1",
        identity_kind=identity_kind,
        identity_id=identity_id,
        cutoff=market_cutoff(query),
        channel=query.requested_channel,
        availability_policy_hash=content_hash(context.availability_policy),
        assignment_manifest_hash=manifest_hash(context.identity.manifest),
        assignment_decision_hash=content_hash(context.identity.decision),
        assignment_bundle_hash=content_hash(context.identity.bundle),
        selected_assignment_hashes=selected_hashes,
        selection_evidence_hashes=tuple(
            sorted(content_hash(item) for item in selections)
        ),
        status=status,
        reasons=reasons,
    )


def _assignment_interval_relation(
    left: TemporalIntervalClaimV1,
    right: TemporalIntervalClaimV1,
) -> Literal["disjoint", "overlap", "indeterminate"]:
    """Compare source interval claims without inventing boundary precision."""
    if _interval_definitely_ends_before(left, right) or (
        _interval_definitely_ends_before(right, left)
    ):
        return "disjoint"
    if _interval_start_definitely_precedes_end(left, right) and (
        _interval_start_definitely_precedes_end(right, left)
    ):
        return "overlap"
    return "indeterminate"


def _interval_definitely_ends_before(
    left: TemporalIntervalClaimV1,
    right: TemporalIntervalClaimV1,
) -> bool:
    end = left.end
    return (
        end is not None
        and end.upper_bound is not None
        and right.start.lower_bound is not None
        and end.upper_bound <= right.start.lower_bound
    )


def _interval_start_definitely_precedes_end(
    left: TemporalIntervalClaimV1,
    right: TemporalIntervalClaimV1,
) -> bool:
    if right.end is None:
        return left.start.upper_bound is not None
    return (
        left.start.upper_bound is not None
        and right.end.lower_bound is not None
        and left.start.upper_bound < right.end.lower_bound
    )


def _is_source_authorized(
    record: EconomicRecordV1,
    dataset: EconomicDatasetInput,
    query: MarketSelectionQueryV1,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> bool:
    family = _projection_family(record)
    owner = policy_owner(source_policy, family)
    payload = record.payload
    action_kind: ActionKind | None = None if payload is None else payload.action_kind
    return (
        record.security_id == query.security_id
        and action_kind in query.action_kinds
        and record.source_key.source_id == owner.source_id
        and dataset.manifest.source.source_id == owner.source_id
        and manifest_hash(dataset.manifest) == owner.fact_manifest_hash
        and dataset.manifest.dataset_role.name == f"economic_{family}"
    )


def _terms_applicability(
    record: CorporateActionTermsVersionV1,
    query: MarketSelectionQueryV1,
) -> EconomicApplicabilityV1:
    boundary = record.scheduled_effect_time
    status: Literal["before_window", "in_window", "upcoming", "indeterminate"]
    if boundary.lower_bound is None or boundary.upper_bound is None:
        status = "indeterminate"
        reason = "scheduled_time_unknown"
    elif boundary.upper_bound < query.history_start:
        status = "before_window"
        reason = "scheduled_before_window"
    elif boundary.lower_bound > market_horizon(query):
        status = "upcoming"
        reason = "scheduled_after_horizon"
    elif boundary.lower_bound >= query.history_start and (
        boundary.upper_bound <= market_horizon(query)
    ):
        status = "in_window"
        reason = "scheduled_in_window"
    else:
        status = "indeterminate"
        reason = "scheduled_time_overlaps_boundary"
    return EconomicApplicabilityV1(
        source_record_hash=content_hash(record),
        family="terms",
        status=status,
        reasons=(reason,),
    )


def _record_applicability(
    record: EconomicRecordV1,
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
) -> EconomicApplicabilityV1:
    if isinstance(record, CorporateActionTermsVersionV1):
        return _terms_applicability(record, query)
    boundary = (
        record.effective_time
        if isinstance(record, EconomicEffectVersionV1)
        else record.settled_time
    )
    family: Literal["effect", "settlement"] = (
        "effect" if isinstance(record, EconomicEffectVersionV1) else "settlement"
    )
    status: Literal["before_window", "in_window", "upcoming", "indeterminate"]
    is_actual_claim = isinstance(record, EconomicSettlementVersionV1) or (
        record.payload is not None and isinstance(record.payload, OccurredEffectV1)
    )
    if (
        is_actual_claim
        and boundary.lower_bound is not None
        and _actual_claim_predates_occurrence(record, boundary.lower_bound, context)
    ):
        status = "indeterminate"
        reason = "actual_claim_predates_occurrence"
    elif boundary.lower_bound is None or boundary.upper_bound is None:
        status = "indeterminate"
        reason = "actual_time_unknown"
    elif boundary.upper_bound < query.history_start:
        status = "before_window"
        reason = "actual_before_window"
    elif boundary.lower_bound >= query.history_start and boundary.upper_bound <= min(
        market_horizon(query), market_cutoff(query)
    ):
        status = "in_window"
        reason = "actual_in_window"
    elif boundary.lower_bound > market_horizon(
        query
    ) and boundary.upper_bound <= market_cutoff(query):
        status = "upcoming"
        reason = "actual_after_horizon"
    else:
        status = "indeterminate"
        reason = "actual_time_outside_finite_window"
    return EconomicApplicabilityV1(
        source_record_hash=content_hash(record),
        family=family,
        status=status,
        reasons=(reason,),
    )


def _actual_claim_predates_occurrence(
    record: EconomicEffectVersionV1 | EconomicSettlementVersionV1,
    actual_lower_bound: datetime,
    context: EconomicResolutionContext,
) -> bool:
    """Apply the selected-version chronology veto across trusted own channels."""
    for evidence in record.revision.availability:
        result = evaluate_availability(
            evidence,
            evidence.channel,
            context.availability_policy,
            actual_lower_bound,
            context.retained_evidence,
        )
        if (
            result.classification is CutoffEligibility.ELIGIBLE
            and evidence.upper_bound is not None
            and evidence.upper_bound < actual_lower_bound
        ):
            return True
    return False


def _project_record(
    record: EconomicRecordV1,
    applicability: EconomicApplicabilityV1,
    query: MarketSelectionQueryV1,
    identity_proof: IdentityProofSelector,
) -> EconomicSafeFactProjectionV1 | None:
    source_identity = identity_proof("security", record.security_id)
    if source_identity.status != "known" or record.payload is None:
        return None
    dependencies: dict[tuple[str, UUID], RetainedEconomicIdentityV1] = {
        ("security", record.security_id): source_identity
    }
    optional_reasons: tuple[str, ...] = ()
    if record.listing_id is not None:
        listing_proof = identity_proof("listing", record.listing_id)
        dependencies[("listing", record.listing_id)] = listing_proof
        optional_reasons = ("source_listing_context_omitted",)

    components: tuple[EconomicComponentV1, ...]
    component_role: Literal["terms", "owed", "delivered"]
    claim_status: Literal["continuing", "converted", "extinguished", "unknown"]
    fact_status: Literal[
        "terms", "occurred", "cancelled_action", "unknown", "delivered"
    ]
    consideration_status: Literal["components", "explicit_none", "unknown"]
    residual_status: Literal[
        "closed_for_occurrence", "closed_for_action", "outstanding", "unknown"
    ]
    action_kind: ActionKind
    if isinstance(record, CorporateActionTermsVersionV1):
        terms_payload = record.payload
        components = terms_payload.components
        action_kind = terms_payload.action_kind
        component_role = "terms"
        claim_status = "unknown"
        fact_status = "terms"
        consideration_status = "components" if components else "unknown"
        residual_status = "unknown"
    elif isinstance(record, EconomicEffectVersionV1):
        effect_payload = record.payload
        action_kind = effect_payload.action_kind
        component_role = "owed"
        if isinstance(effect_payload, OccurredEffectV1):
            components = effect_payload.owed_components
            claim_status = effect_payload.claim_status
            fact_status = "occurred"
            consideration_status = effect_payload.consideration_status
            residual_status = effect_payload.residual.kind
        elif isinstance(effect_payload, CancelledActionV1):
            components = ()
            claim_status = "unknown"
            fact_status = "cancelled_action"
            consideration_status = "unknown"
            residual_status = "unknown"
        else:
            assert isinstance(effect_payload, UnknownEffectV1)
            components = ()
            claim_status = "unknown"
            fact_status = "unknown"
            consideration_status = "unknown"
            residual_status = "unknown"
    else:
        settlement_payload = record.payload
        components = settlement_payload.delivered_components
        action_kind = settlement_payload.action_kind
        component_role = "delivered"
        claim_status = "unknown"
        fact_status = "delivered"
        consideration_status = "components"
        residual_status = settlement_payload.residual.kind

    known: list[EconomicComponentV1] = []
    gaps: list[EconomicComponentGapV1] = []
    for component in components:
        component_proofs = _component_identity_proofs(component, identity_proof)
        dependencies.update(component_proofs)
        reason = _unsafe_component_reason(component, component_proofs)
        if reason is None:
            known.append(_projection_safe_component(component))
        else:
            gaps.append(
                EconomicComponentGapV1(
                    component_id=component.component_id,
                    source_component_hash=content_hash(component),
                    reason=reason,
                )
            )
    return EconomicSafeFactProjectionV1(
        schema_version="1",
        query_hash=content_hash(query),
        source_record_hash=content_hash(record),
        family=_projection_family(record),
        security_id=record.security_id,
        action_kind=action_kind,
        applicability=applicability,
        component_role=component_role,
        known_components=tuple(known),
        withheld_components=tuple(gaps),
        claim_status=claim_status,
        fact_status=fact_status,
        consideration_status=consideration_status,
        residual_status=residual_status,
        optional_context_reasons=optional_reasons,
        dependency_proof_hashes=tuple(
            sorted(content_hash(item) for item in dependencies.values())
        ),
        projection_algorithm_spec_hash=content_hash(_PROJECTION_SPEC),
        projection_implementation_hash=economic_implementation_hash(),
    )


def _projection_safe_component(
    component: EconomicComponentV1,
) -> EconomicComponentV1:
    """Opaque nested evidence locations only in the separately hashed projection."""
    if isinstance(component, ShareComponentV1):
        treatment = component.fraction_treatment
        reference = treatment.evidence_reference
        if reference is None:
            return component
        return component.model_copy(
            update={
                "fraction_treatment": treatment.model_copy(
                    update={"evidence_reference": _opaque_reference(reference)}
                )
            }
        )
    if isinstance(component, UnsupportedPropertyComponentV1):
        return component.model_copy(
            update={
                "evidence_reference": _opaque_reference(component.evidence_reference)
            }
        )
    return component


def _opaque_reference(reference: ArtifactReference) -> ArtifactReference:
    """Preserve content identity while removing source-bearing physical context."""
    return reference.model_copy(
        update={"location": f"drift+sha256://{reference.content_hash}"}
    )


def _projection_family(
    record: EconomicRecordV1,
) -> Literal["terms", "effect", "settlement"]:
    if isinstance(record, CorporateActionTermsVersionV1):
        return "terms"
    if isinstance(record, EconomicEffectVersionV1):
        return "effect"
    return "settlement"


def _component_identity_proofs(
    component: EconomicComponentV1,
    identity_proof: IdentityProofSelector,
) -> dict[tuple[str, UUID], RetainedEconomicIdentityV1]:
    identifiers: list[UUID] = []
    if isinstance(component, CashComponentV1):
        identifiers.append(component.unit_basis.security_id)
    elif isinstance(component, ShareComponentV1):
        identifiers.append(component.unit_basis.security_id)
        if component.recipient.kind == "security":
            assert component.recipient.security_id is not None
            identifiers.append(component.recipient.security_id)
    elif (
        isinstance(component, UnsupportedPropertyComponentV1)
        and component.recipient.kind == "security"
    ):
        assert component.recipient.security_id is not None
        identifiers.append(component.recipient.security_id)
    return {
        ("security", item_id): identity_proof("security", item_id)
        for item_id in identifiers
    }


def _unsafe_component_reason(
    component: EconomicComponentV1,
    proofs: Mapping[tuple[str, UUID], RetainedEconomicIdentityV1],
) -> str | None:
    basis_id: UUID | None = None
    recipient_id: UUID | None = None
    if isinstance(component, CashComponentV1 | ShareComponentV1):
        basis_id = component.unit_basis.security_id
    if isinstance(component, ShareComponentV1 | UnsupportedPropertyComponentV1) and (
        component.recipient.kind == "security"
    ):
        recipient_id = component.recipient.security_id
    if basis_id is not None and proofs[("security", basis_id)].status != "known":
        return "basis_identity_unavailable"
    if (
        recipient_id is not None
        and proofs[("security", recipient_id)].status != "known"
    ):
        return "recipient_identity_unavailable"
    return None


def _raw_materializable(
    record: EconomicRecordV1,
    applicability: EconomicApplicabilityV1,
    projection: EconomicSafeFactProjectionV1 | None,
) -> bool:
    if (
        projection is None
        or record.listing_id is not None
        or projection.withheld_components
    ):
        return False
    if isinstance(record, CorporateActionTermsVersionV1):
        return applicability.status != "indeterminate"
    return applicability.status in {"before_window", "in_window"}


def decision_reference(
    query: MarketDecisionQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> MarketDecisionReferenceV1:
    """Build a decision-only materialization capability."""
    if not isinstance(query, MarketDecisionQueryV1):
        raise TypeError("decision_reference requires a decision query")
    proof = select_market_records(query, context, source_policy)
    return MarketDecisionReferenceV1(
        schema_version="1",
        kind="decision_reference",
        query_hash=content_hash(query),
        selection_proof_hash=content_hash(proof),
        selected_record_hashes=proof.raw_materializable_record_hashes,
        projection_hashes=proof.projection_hashes,
    )


def outcome_reference(
    query: MarketOutcomeQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> MarketOutcomeReferenceV1:
    """Build an outcome-only materialization capability."""
    if not isinstance(query, MarketOutcomeQueryV1):
        raise TypeError("outcome_reference requires an outcome query")
    proof = select_market_records(query, context, source_policy)
    return MarketOutcomeReferenceV1(
        schema_version="1",
        kind="outcome_reference",
        query_hash=content_hash(query),
        selection_proof_hash=content_hash(proof),
        selected_record_hashes=proof.raw_materializable_record_hashes,
        projection_hashes=proof.projection_hashes,
    )


def verify_market_selection(
    proof: MarketSelectionProofV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> None:
    """Replay and verify a complete selection proof."""
    expected, _ = _selection_pipeline(proof.query, context, source_policy)
    if proof != expected:
        raise ValueError("selection proof does not match exact replay")


def resolve_decision_records(
    reference: MarketDecisionReferenceV1,
    query: MarketDecisionQueryV1,
    records_by_hash: Mapping[str, EconomicRecordV1],
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> Mapping[str, EconomicRecordV1]:
    """Resolve raw values named by a decision capability."""
    if not isinstance(reference, MarketDecisionReferenceV1):
        raise TypeError("resolve_decision_records requires a decision reference")
    if not isinstance(query, MarketDecisionQueryV1):
        raise TypeError("resolve_decision_records requires a decision query")
    expected = decision_reference(query, context, source_policy)
    if reference != expected:
        raise ValueError("decision reference does not match exact replay")
    if set(records_by_hash) != set(reference.selected_record_hashes):
        raise ValueError("decision record hash keys must match authorized set")
    if any(content_hash(value) != key for key, value in records_by_hash.items()):
        raise ValueError("decision record hash does not match supplied value")
    return MappingProxyType(dict(records_by_hash))


def resolve_outcome_records(
    reference: MarketOutcomeReferenceV1,
    query: MarketOutcomeQueryV1,
    records_by_hash: Mapping[str, EconomicRecordV1],
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> Mapping[str, EconomicRecordV1]:
    """Resolve raw values named by an outcome capability."""
    if not isinstance(reference, MarketOutcomeReferenceV1):
        raise TypeError("resolve_outcome_records requires an outcome reference")
    if not isinstance(query, MarketOutcomeQueryV1):
        raise TypeError("resolve_outcome_records requires an outcome query")
    expected = outcome_reference(query, context, source_policy)
    if reference != expected:
        raise ValueError("outcome reference does not match exact replay")
    if set(records_by_hash) != set(reference.selected_record_hashes):
        raise ValueError("outcome record hash keys must match authorized set")
    if any(content_hash(value) != key for key, value in records_by_hash.items()):
        raise ValueError("outcome record hash does not match supplied value")
    return MappingProxyType(dict(records_by_hash))


def resolve_decision_projections(
    reference: MarketDecisionReferenceV1,
    query: MarketDecisionQueryV1,
    projections_by_hash: Mapping[str, EconomicSafeFactProjectionV1],
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> Mapping[str, EconomicSafeFactProjectionV1]:
    """Resolve safe projections named by a decision capability."""
    if not isinstance(reference, MarketDecisionReferenceV1):
        raise TypeError("resolve_decision_projections requires a decision reference")
    if not isinstance(query, MarketDecisionQueryV1):
        raise TypeError("resolve_decision_projections requires a decision query")
    expected = decision_reference(query, context, source_policy)
    if reference != expected:
        raise ValueError("decision reference does not match exact replay")
    if set(projections_by_hash) != set(reference.projection_hashes):
        raise ValueError("decision projection hash keys must match authorized set")
    if any(content_hash(value) != key for key, value in projections_by_hash.items()):
        raise ValueError("decision projection hash does not match supplied value")
    return MappingProxyType(dict(projections_by_hash))


def resolve_outcome_projections(
    reference: MarketOutcomeReferenceV1,
    query: MarketOutcomeQueryV1,
    projections_by_hash: Mapping[str, EconomicSafeFactProjectionV1],
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> Mapping[str, EconomicSafeFactProjectionV1]:
    """Resolve safe projections named by an outcome capability."""
    if not isinstance(reference, MarketOutcomeReferenceV1):
        raise TypeError("resolve_outcome_projections requires an outcome reference")
    if not isinstance(query, MarketOutcomeQueryV1):
        raise TypeError("resolve_outcome_projections requires an outcome query")
    expected = outcome_reference(query, context, source_policy)
    if reference != expected:
        raise ValueError("outcome reference does not match exact replay")
    if set(projections_by_hash) != set(reference.projection_hashes):
        raise ValueError("outcome projection hash keys must match authorized set")
    if any(content_hash(value) != key for key, value in projections_by_hash.items()):
        raise ValueError("outcome projection hash does not match supplied value")
    return MappingProxyType(dict(projections_by_hash))


def project_market_facts(
    query: MarketSelectionQueryV1,
    context: EconomicResolutionContext,
    source_policy: EconomicSourceSelectionPolicyV1,
) -> tuple[EconomicSafeFactProjectionV1, ...]:
    """Return component-redacted economic source facts safe for this query."""
    _, projections = _selection_pipeline(query, context, source_policy)
    return projections
