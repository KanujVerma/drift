"""Compose orthogonal observation missingness and narrow research usability."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal, cast

from pydantic import ValidationError

from drift.datasets.assertions import (
    build_cutoff_selection_proof,
    build_validated_dataset_bundle,
    select_assertion_version,
)
from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import (
    AssertionVersionProjectionV1,
    BoundaryShape,
    CutoffSelectionProofV1,
    InformationRole,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
)
from drift.domain.observation_query import (
    M1dSelectionProofV1,
    ObservationQueryV1,
    ObservationSourceSelectionPolicyV1,
    m1d_implementation_hash,
    observation_cutoff,
)
from drift.domain.observation_usability import (
    ActivityStatus,
    InterruptionAggregationPolicyV1,
    ListingEligibilitySegmentV1,
    ListingSessionEligibilityResultV1,
    ObservationAssessmentResultV1,
    ObservationAssessmentV1,
    ObservationCoverageStatus,
    ObservationLifecycleStatus,
    ObservationNumericViewV1,
    ObservationReadFailureV1,
    ProfileCompatibilityStatus,
    ProviderGapStatus,
    RequiredFieldsStatus,
    ScheduledDayStatus,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationContractV1,
    ObservationCoverageVersionV1,
    ObservationFieldMethodV1,
    regular_session_trade_bar_profile_hash,
)
from drift.domain.securities import (
    IdentityAssignmentVersionV1,
    IdentityKind,
    IdentityReferenceV1,
    IdentityRelationshipVersionV1,
    IdentityResolutionResultV1,
    ListingHistoryCoverageResolutionV1,
    ListingHistoryCoverageVersionV1,
    ListingLifecycleResolutionV1,
    ListingLifecycleVersionV1,
    ListingRoleVersionV1,
    ListingTerminationResolutionV1,
    ListingTerminationVersionV1,
    ListingV1,
    SecurityClassificationVersionV1,
    identity_reference,
)
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduleArtifactV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
)
from drift.domain.temporal import AvailabilityChannelV1
from drift.domain.universes import (
    SourceUniverseDefinitionVersionV1,
    UniverseMembershipVersionV1,
)
from drift.errors import ArtifactIntegrityError
from drift.markets.identity import (
    _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    resolve_identity,
    resolve_listing_history_coverage,
    resolve_listing_lifecycle,
    resolve_listing_termination,
)
from drift.markets.observation_selection import (
    SelectedObservationContractV1,
    select_observation_records,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    ObservationArtifactUnavailableError,
    m1d_context_hash,
)
from drift.markets.session_binding import bind_observation_session
from drift.markets.session_generation import (
    generate_schedule,
    validate_schedule_generation_policy,
)
from drift.markets.universes import (
    ValidatedRecords,
    resolve_structural_eligibility,
    structural_subject,
)
from drift.serialization.canonical import canonical_json, content_hash

_USABILITY_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "orthogonal_observation_usability_v1",
    "provider_gap": "all_positive_premises",
    "lifecycle": "finite_boundary_sweep_using_m1b_as_known",
    "numeric_view": "regular_session_trade_bar_only",
    "missingness": "independent_axes_without_dominant_reason",
    "read_failure_precedence": "context_and_policy_before_exact_artifact_read",
    "cutoff_axis": "selected_version_witness_for_present_row",
    "coverage_chronology": "exact_snapshot_complete_by_cutoff_not_backdated",
    "profile_order": "intrinsic_source_compatibility_before_session_binding",
    "interruption_aggregation": "exact_contract_bound_closed_policy_required",
    "realized_interruption": "independent_complete-coverage-and-policy-gate",
    "activity_consistency": (
        "positive-qualifying-trade-bar-fields-or-price-trade-conflict-with-"
        "explicit-no-any-trade"
    ),
}
_ELIGIBILITY_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "listing_session_research_eligibility_v1",
    "resolution_mode": "as_known",
    "inner_cutoff": "outer_k_or_v",
    "interval": "exact_realized_boundary_sweep",
    "scheduled_interval": "verified_generated_schedule_when_realization_unavailable",
    "boundaries": "all_causally_selected_structural_inputs",
    "unknown_boundary": "whole_interval_indeterminate",
    "bounded_overlap": "lower_before_segment_close_and_upper_after_segment_open",
    "m1b_channel": "outer_or_explicit_context_mapping_only",
    "realized_interruption": "complete-coverage-and-exact-aggregation-policy-required",
}


def observation_usability_algorithm_hash() -> str:
    """Return the semantic identity of orthogonal usability composition."""
    return content_hash(_USABILITY_ALGORITHM_V1)


def listing_session_eligibility_algorithm_hash() -> str:
    """Return the semantic identity of listing interval composition."""
    return content_hash(_ELIGIBILITY_ALGORITHM_V1)


def assess_observation(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ObservationAssessmentResultV1:
    """Assess one source observation without collapsing independent axes."""
    requested_hash = _requested_observation_artifact_hash(context)
    _validate_assessment_authority(query, context)
    try:
        _verify_requested_observation_bytes(context)
        return _assess_verified_observation(query, context)
    except ArtifactIntegrityError:
        return _read_failure(query, requested_hash, "corrupt")
    except ObservationArtifactUnavailableError:
        return _read_failure(query, requested_hash, "unavailable")


def verify_observation_assessment(
    result: ObservationAssessmentResultV1, context: M1dResolutionContext
) -> None:
    """Replay the exact read and assessment and compare the complete result."""
    replayed = assess_observation(result.query, context)
    if replayed != result:
        raise ValueError("observation assessment replay mismatch")


def resolve_listing_session_eligibility(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ListingSessionEligibilityResultV1:
    """Resolve scheduled research eligibility without claiming realization."""
    if query.input_context_hash != m1d_context_hash(context):
        raise ValueError("observation query context hash mismatch")
    schedule_selection = select_observation_records(query, "scheduled_session", context)
    realized_selection = select_observation_records(query, "realized_session", context)
    contract_selection = select_observation_records(query, "contract", context)
    assert isinstance(contract_selection, SelectedObservationContractV1)
    schedule = _one(schedule_selection.records, ScheduledSessionVersionV1)
    realized = _one(realized_selection.records, RealizedSessionVersionV1)
    schedule_hash = content_hash(schedule) if schedule is not None else None
    generated_schedule = _generate_schedule_for_eligibility(query, context)
    generated_schedule_hash = _stable_schedule_hash(generated_schedule)
    reasons: list[str] = []
    segments: tuple[ListingEligibilitySegmentV1, ...] = ()
    structural_hashes: tuple[str, ...] = ()
    lifecycle_hashes: tuple[str, ...] = ()
    lifecycle: ObservationLifecycleStatus = "indeterminate"
    classification: Literal["eligible", "ineligible", "indeterminate"] = "indeterminate"

    if schedule is None:
        reasons.append("scheduled_day_unknown")
    elif schedule.state in {"closed"}:
        classification = "ineligible"
        reasons.append("scheduled_day_closed")
    elif schedule.state == "unknown":
        reasons.append("scheduled_day_unknown")

    interval: tuple[datetime, datetime] | None = None
    if (
        realized is not None
        and realized.outcome == "opened"
        and realized.actual_open is not None
        and realized.actual_close is not None
        and realized.actual_close > realized.actual_open
    ):
        interval = (realized.actual_open, realized.actual_close)
    elif (
        generated_schedule is not None
        and generated_schedule.classification == "generated"
        and len(generated_schedule.rows) == 1
        and generated_schedule.rows[0].output.interpretation_status == "authorized"
        and generated_schedule.rows[0].output.state in {"regular", "early_close"}
        and generated_schedule.rows[0].output.utc_open is not None
        and generated_schedule.rows[0].output.utc_close is not None
    ):
        interval = (
            generated_schedule.rows[0].output.utc_open,
            generated_schedule.rows[0].output.utc_close,
        )

    structural_context = context.structural_context
    definition = context.research_definition
    if (
        structural_context is None
        or definition is None
        or context.issuer_id is None
        or context.structural_methodology_id is None
    ):
        reasons.append("m1b_context_unavailable")
    elif interval is None:
        reasons.append("authorized_scheduled_interval_unavailable")
    else:
        segments = _resolve_interval_segments(query, context, interval[0], interval[1])
        structural_hashes = tuple(
            sorted({item.structural_resolution_hash for item in segments})
        )
        lifecycle_hashes = tuple(
            sorted(
                {
                    item.lifecycle_resolution_hash
                    for item in segments
                    if item.lifecycle_resolution_hash is not None
                }
            )
        )
        lifecycle = _interval_lifecycle(segments)
        interval_classification, interval_reasons = _classify_interval(
            segments, realized, contract_selection.contract, context
        )
        reasons.extend(interval_reasons)
        if classification != "ineligible":
            classification = interval_classification

    if schedule is not None and schedule.state in {"regular", "early_close"}:
        reasons.append(f"scheduled_day_{schedule.state}")
    if not reasons:
        reasons.append("eligibility_indeterminate")
    return ListingSessionEligibilityResultV1(
        query=query,
        query_hash=content_hash(query),
        structural_resolution_hashes=structural_hashes,
        lifecycle_resolution_hashes=lifecycle_hashes,
        selected_schedule_hash=schedule_hash,
        selected_schedule_proof_hash=content_hash(schedule_selection.proof),
        generated_schedule_hash=generated_schedule_hash,
        classification=classification,
        lifecycle=lifecycle,
        segments=segments,
        reasons=tuple(sorted(set(reasons))),
        context_hash=query.input_context_hash,
        policy_hash=(
            content_hash(definition) if definition is not None else query.profile_hash
        ),
        semantic_algorithm_hash=listing_session_eligibility_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
        inner_knowledge_cutoff=observation_cutoff(query),
    )


def _assess_verified_observation(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ObservationAssessmentV1:
    observation_selection = select_observation_records(query, "observation", context)
    coverage_selection = select_observation_records(
        query, "observation_coverage", context
    )
    schedule_selection = select_observation_records(query, "scheduled_session", context)
    realized_selection = select_observation_records(query, "realized_session", context)
    contract_selection = select_observation_records(query, "contract", context)
    assert isinstance(contract_selection, SelectedObservationContractV1)
    observation = _one(observation_selection.records, DailySourceObservationVersionV1)
    coverage_record = _one(coverage_selection.records, ObservationCoverageVersionV1)
    schedule = _one(schedule_selection.records, ScheduledSessionVersionV1)
    realized = _one(realized_selection.records, RealizedSessionVersionV1)
    contract = contract_selection.contract
    binding = bind_observation_session(query, context)
    eligibility = resolve_listing_session_eligibility(query, context)

    scheduled_day: ScheduledDayStatus = (
        schedule.state if schedule is not None else "unknown"
    )
    realized_outcome: Literal["opened", "did_not_open", "unknown"] = (
        realized.outcome if realized is not None else "unknown"
    )
    coverage: ObservationCoverageStatus = (
        coverage_record.status if coverage_record is not None else "unknown"
    )
    record_presence: Literal["present", "absent", "unknown"] = (
        "present"
        if observation is not None
        else "absent"
        if observation_selection.proof.classification == "absent"
        else "unknown"
    )
    required_fields = _required_fields_status(observation)
    qualifying_activity: ActivityStatus = (
        "reported"
        if observation is not None
        and observation.activity_claim == "qualifying_price_trade"
        else "explicit_none"
        if observation is not None
        and observation.activity_claim == "explicit_no_qualifying_price_trade"
        else "unknown"
    )
    any_activity: ActivityStatus = (
        "reported"
        if observation is not None and observation.any_trade_claim == "reported"
        else "explicit_none"
        if observation is not None and observation.any_trade_claim == "explicit_none"
        else "unknown"
    )
    cutoff_availability = _cutoff_axis(observation_selection.proof, observation, query)
    source_basis: Literal[
        "unadjusted",
        "split_adjusted",
        "dividend_adjusted",
        "total_return_like",
        "mixed",
        "unknown",
    ] = contract.adjustment_basis if contract is not None else "unknown"
    profile_status, profile_reasons, values = _profile_compatibility(
        query, observation, contract, binding.classification, context
    )
    if qualifying_activity == "reported" and any_activity == "explicit_none":
        profile_status = "incompatible"
        profile_reasons = (
            *profile_reasons,
            "activity_claim_conflict:any_trade_explicit_none_with_qualifying_price_trade",
        )
        values = None
    elif (
        qualifying_activity == "unknown"
        and any_activity == "explicit_none"
        and values is not None
    ):
        profile_status = "incompatible"
        profile_reasons = (
            *profile_reasons,
            "activity_claim_conflict:any_trade_explicit_none_with_positive_qualifying_trade_bar_fields",
        )
        values = None
    provider_gap: ProviderGapStatus = (
        "proven"
        if _provider_gap_is_proven(
            record_presence,
            coverage_record,
            realized,
            contract,
            eligibility,
            cutoff_availability,
            query,
        )
        else "not_proven"
    )
    usability = _compose_usability(
        scheduled_day=scheduled_day,
        realized_outcome=realized_outcome,
        eligibility=eligibility.classification,
        record_presence=record_presence,
        required_fields=required_fields,
        cutoff_availability=cutoff_availability,
        profile=profile_status,
        binding=binding.classification,
        qualifying_activity=qualifying_activity,
    )
    numeric_view = None
    if usability == "usable" and observation is not None and contract is not None:
        assert values is not None
        numeric_view = ObservationNumericViewV1(
            open=values["open"],
            high=values["high"],
            low=values["low"],
            close=values["close"],
            volume=values["volume"],
            currency=contract.currency,
            source_basis="unadjusted",
            observation_hash=content_hash(observation),
            contract_hash=content_hash(contract),
        )
    reasons = {
        f"scheduled_day:{scheduled_day}",
        f"realized_outcome:{realized_outcome}",
        f"lifecycle:{eligibility.lifecycle}",
        f"coverage:{coverage}",
        f"record_presence:{record_presence}",
        f"required_fields:{required_fields}",
        f"qualifying_price_activity:{qualifying_activity}",
        f"any_reported_activity:{any_activity}",
        f"cutoff_availability:{cutoff_availability}",
        f"source_basis:{source_basis}",
        f"profile_compatibility:{profile_status}",
        f"provider_gap:{provider_gap}",
        *profile_reasons,
        *binding.reasons,
        *eligibility.reasons,
    }
    proofs = {
        content_hash(observation_selection.proof),
        content_hash(coverage_selection.proof),
        content_hash(schedule_selection.proof),
        content_hash(realized_selection.proof),
        content_hash(contract_selection.proof),
        content_hash(binding),
        content_hash(eligibility),
        *eligibility.structural_resolution_hashes,
        *eligibility.lifecycle_resolution_hashes,
    }
    return ObservationAssessmentV1(
        query=query,
        query_hash=content_hash(query),
        scheduled_day=scheduled_day,
        realized_outcome=realized_outcome,
        lifecycle=eligibility.lifecycle,
        coverage=coverage,
        record_presence=record_presence,
        required_fields=required_fields,
        qualifying_price_activity=qualifying_activity,
        any_reported_activity=any_activity,
        cutoff_availability=cutoff_availability,
        source_basis=source_basis,
        profile_compatibility=profile_status,
        provider_gap=provider_gap,
        usability=usability,
        eligibility=eligibility,
        numeric_view=numeric_view,
        observation_selection_proof_hash=content_hash(observation_selection.proof),
        coverage_selection_proof_hash=content_hash(coverage_selection.proof),
        realized_selection_proof_hash=content_hash(realized_selection.proof),
        session_binding_hash=content_hash(binding),
        contributing_proof_hashes=tuple(sorted(proofs)),
        reasons=tuple(sorted(reasons)),
        context_hash=query.input_context_hash,
        semantic_algorithm_hash=observation_usability_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
    )


def _resolve_interval_segments(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    interval_open: datetime,
    interval_close: datetime,
) -> tuple[ListingEligibilitySegmentV1, ...]:
    structural = context.structural_context
    definition = context.research_definition
    issuer_id = context.issuer_id
    methodology = context.structural_methodology_id
    assert structural is not None
    assert definition is not None
    assert issuer_id is not None
    assert methodology is not None

    initial_query = _structural_query(query, context, interval_open)
    resolve_structural_eligibility(
        definition,
        ListingV1(
            schema_version="1",
            listing_id=query.listing_id,
            venue=query.venue,
        ),
        issuer_id,
        query.security_id,
        methodology,
        initial_query,
        structural,
    )
    boundaries = {interval_open, interval_close}
    whole_interval_unknown = False
    lifecycle_unknown = False
    claims: list[tuple[Any, bool]] = []
    for record in _causally_selected_structural_records(query, context):
        is_lifecycle = isinstance(
            record, ListingLifecycleVersionV1 | ListingTerminationVersionV1
        )
        if hasattr(record, "effective_time"):
            claims.append((record.effective_time, is_lifecycle))
        elif hasattr(record, "effective_interval"):
            claims.append((record.effective_interval.start, is_lifecycle))
            if record.effective_interval.end is not None:
                claims.append((record.effective_interval.end, is_lifecycle))
        elif hasattr(record, "complete_through"):
            claims.append((record.complete_through, is_lifecycle))
    bounded_overlaps: list[tuple[Any, bool]] = []
    for claim, is_lifecycle in claims:
        if claim.shape is BoundaryShape.UNKNOWN:
            whole_interval_unknown = True
            lifecycle_unknown = lifecycle_unknown or is_lifecycle
            continue
        assert claim.lower_bound is not None and claim.upper_bound is not None
        if claim.upper_bound < interval_open or claim.lower_bound > interval_close:
            continue
        if claim.shape is BoundaryShape.BOUNDED:
            bounded_overlaps.append((claim, is_lifecycle))
        boundaries.add(max(interval_open, claim.lower_bound))
        boundaries.add(min(interval_close, claim.upper_bound))
    ordered = tuple(sorted(boundaries))
    segments: list[ListingEligibilitySegmentV1] = []
    for opened_at, closed_at in zip(ordered, ordered[1:], strict=False):
        if opened_at == closed_at:
            continue
        inner_query = _structural_query(query, context, opened_at)
        structural_result = resolve_structural_eligibility(
            definition,
            ListingV1(
                schema_version="1",
                listing_id=query.listing_id,
                venue=query.venue,
            ),
            issuer_id,
            query.security_id,
            methodology,
            inner_query,
            structural,
        )
        lifecycle_result, termination_result, coverage_result = _resolve_lifecycle(
            inner_query, query, context
        )
        lifecycle: ObservationLifecycleStatus = (
            "indeterminate"
            if lifecycle_unknown
            or any(
                claim.shape is not BoundaryShape.EXACT
                and claim.lower_bound is not None
                and claim.upper_bound is not None
                and claim.lower_bound < closed_at
                and claim.upper_bound > opened_at
                and is_lifecycle
                for claim, is_lifecycle in bounded_overlaps
            )
            else lifecycle_result.status.value
        )
        structural_classification: Literal[
            "eligible", "ineligible", "indeterminate"
        ] = (
            "indeterminate"
            if whole_interval_unknown
            or any(
                claim.lower_bound is not None
                and claim.upper_bound is not None
                and claim.lower_bound < closed_at
                and claim.upper_bound > opened_at
                for claim, _is_lifecycle in bounded_overlaps
            )
            else structural_result.classification.value
        )
        proof_hashes = tuple(
            sorted(
                {
                    *structural_result.selection_proof_hashes,
                    *lifecycle_result.evidence.selection_proof_hashes,
                    *termination_result.evidence.selection_proof_hashes,
                    *coverage_result.evidence.selection_proof_hashes,
                }
            )
        )
        segments.append(
            ListingEligibilitySegmentV1(
                opened_at=opened_at,
                closed_at=closed_at,
                lifecycle=lifecycle,
                structural_classification=structural_classification,
                structural_resolution_hash=content_hash(structural_result),
                lifecycle_resolution_hash=content_hash(lifecycle_result),
                selection_proof_hashes=proof_hashes,
            )
        )
    return tuple(segments)


def _causally_selected_structural_records(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> tuple[Any, ...]:
    structural = context.structural_context
    assert structural is not None
    universe = structural.universe
    datasets = (
        universe.memberships,
        universe.source_definitions,
        universe.assignments,
        structural.relationships,
        structural.classifications,
        structural.roles,
        structural.lifecycle,
        structural.terminations,
        structural.coverage,
    )
    channel = _m1b_requested_channel(query, context)
    selected: list[Any] = []
    for dataset in datasets:
        chains: dict[object, list[Any]] = {}
        for record in dataset.records:
            chains.setdefault(record.revision.logical_record_id, []).append(record)
        for chain in chains.values():
            selection = select_assertion_version(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=record.revision,
                        record_hash=content_hash(record),
                    )
                    for record in chain
                ),
                channel,
                universe.policy,
                observation_cutoff(query),
                universe.retained_evidence,
            )
            if selection.selected_record_hash is None:
                continue
            selected.extend(
                record
                for record in chain
                if content_hash(record) == selection.selected_record_hash
            )
    return _relevant_structural_records(tuple(selected), query, context)


def _relevant_structural_records(
    records: tuple[Any, ...],
    query: ObservationQueryV1,
    context: M1dResolutionContext,
) -> tuple[Any, ...]:
    assert context.issuer_id is not None
    definition = context.research_definition
    assert definition is not None
    targets = {
        IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=context.issuer_id),
        IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=query.security_id),
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=query.listing_id),
    }
    relationships = tuple(
        item for item in records if isinstance(item, IdentityRelationshipVersionV1)
    )
    connected = set(targets)
    changed = True
    while changed:
        changed = False
        for relationship in relationships:
            if (
                relationship.left not in connected
                and relationship.right not in connected
            ):
                continue
            before = len(connected)
            connected.update((relationship.left, relationship.right))
            changed = changed or len(connected) != before

    def relevant(record: Any) -> bool:
        if isinstance(record, IdentityAssignmentVersionV1):
            return identity_reference(record.identity) in connected
        if isinstance(record, IdentityRelationshipVersionV1):
            return record.left in connected or record.right in connected
        if isinstance(record, SecurityClassificationVersionV1):
            return (
                record.issuer_id == context.issuer_id
                and record.security_id == query.security_id
            )
        if isinstance(record, ListingRoleVersionV1):
            return (
                record.security_id == query.security_id
                and record.methodology_id == context.structural_methodology_id
            )
        if isinstance(
            record,
            ListingLifecycleVersionV1
            | ListingTerminationVersionV1
            | ListingHistoryCoverageVersionV1,
        ):
            return record.listing_id == query.listing_id
        if isinstance(record, UniverseMembershipVersionV1):
            return (
                record.universe_id == definition.universe_id
                and record.universe_version == definition.universe_version
                and record.target_id == query.listing_id
            )
        if isinstance(record, SourceUniverseDefinitionVersionV1):
            return (
                record.universe_id == definition.universe_id
                and record.universe_version == definition.universe_version
            )
        return False

    return tuple(record for record in records if relevant(record))


def _structural_query(
    outer: ObservationQueryV1,
    context: M1dResolutionContext,
    evaluation_time: datetime,
) -> NormalizedSelectionQueryV1:
    structural = context.structural_context
    definition = context.research_definition
    assert structural is not None and definition is not None
    assert (
        context.issuer_id is not None and context.structural_methodology_id is not None
    )
    universe = structural.universe
    data = universe.memberships
    return NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        information_role=InformationRole.DECISION_INFORMATION,
        resolution_mode=ResolutionMode.AS_KNOWN,
        subject_hash=content_hash(
            structural_subject(
                definition,
                context.issuer_id,
                outer.security_id,
                outer.listing_id,
                context.structural_methodology_id,
            )
        ),
        source_manifest_hash=data.decision.manifest_hash,
        validation_decision_hash=content_hash(data.decision),
        context_bundle_hashes=tuple(
            sorted(
                (
                    content_hash(universe.identity_bundle),
                    content_hash(universe.universe_bundle),
                )
            )
        ),
        dataset_role_hash=content_hash(data.manifest.dataset_role),
        record_contract_hash=content_hash(data.manifest.temporal_contract.contract),
        schema_hash=data.manifest.schema_definition.schema_hash,
        knowledge_cutoff=observation_cutoff(outer),
        evaluation_time=evaluation_time,
        requested_channel=_m1b_requested_channel(outer, context),
        policy_id=universe.policy.policy_id,
        policy_hash=content_hash(universe.policy),
    )


def _m1b_requested_channel(
    outer: ObservationQueryV1, context: M1dResolutionContext
) -> AvailabilityChannelV1:
    structural = context.structural_context
    assert structural is not None
    universe = structural.universe
    datasets = (
        universe.assignments,
        universe.memberships,
        universe.source_definitions,
        structural.relationships,
        structural.classifications,
        structural.roles,
        structural.lifecycle,
        structural.terminations,
        structural.coverage,
    )
    declared = tuple(
        set(item.manifest.temporal_contract.contract.declared_channels)
        for item in datasets
    )
    common = set.intersection(*declared)
    if outer.requested_channel in common:
        return outer.requested_channel
    if (
        context.m1b_requested_channel is not None
        and context.m1b_requested_channel in common
    ):
        return context.m1b_requested_channel
    raise ValueError("M1b requested channel is not uniquely authenticated")


def _generate_schedule_for_eligibility(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ScheduleArtifactV1 | None:
    policy = _load_schedule_generation_policy(context)
    if policy is None:
        return None
    return generate_schedule(query, context, policy)


def _load_schedule_generation_policy(
    context: M1dResolutionContext,
) -> ScheduleGenerationPolicyV1 | None:
    policy_hash = context.schedule_generation_policy_hash
    if policy_hash is None:
        return None
    artifact = context.supporting_artifacts.get(policy_hash)
    if artifact is None:
        raise ValueError("schedule generation policy bytes unavailable")
    try:
        policy = ScheduleGenerationPolicyV1.model_validate_json(artifact.data)
    except ValidationError as error:
        raise ValueError("schedule generation policy bytes invalid") from error
    if (
        canonical_json(policy) != artifact.data
        or content_hash(policy) != policy_hash
        or sha256(artifact.data).hexdigest() != policy_hash
    ):
        raise ValueError("schedule generation policy hash mismatch")
    validate_schedule_generation_policy(policy, context)
    return policy


def _stable_schedule_hash(artifact: ScheduleArtifactV1 | None) -> str | None:
    if artifact is None:
        return None
    return content_hash(artifact.model_dump(mode="python", exclude={"generated_at"}))


def _dependent_query(
    parent: NormalizedSelectionQueryV1,
    data: ValidatedRecords[object],
    purpose: M1bSelectionPurpose,
    subject: object,
) -> NormalizedSelectionQueryV1:
    return parent.model_copy(
        update={
            "purpose": purpose,
            "subject_hash": content_hash(subject),
            "source_manifest_hash": data.decision.manifest_hash,
            "validation_decision_hash": content_hash(data.decision),
            "dataset_role_hash": content_hash(data.manifest.dataset_role),
            "record_contract_hash": content_hash(
                data.manifest.temporal_contract.contract
            ),
            "schema_hash": data.manifest.schema_definition.schema_hash,
        }
    )


def _resolve_lifecycle(
    parent: NormalizedSelectionQueryV1,
    outer: ObservationQueryV1,
    context: M1dResolutionContext,
) -> tuple[
    ListingLifecycleResolutionV1,
    ListingTerminationResolutionV1,
    ListingHistoryCoverageResolutionV1,
]:
    structural = context.structural_context
    assert structural is not None
    universe = structural.universe
    subject = {"listing_id": outer.listing_id}
    relationship_resolution, relationship_proof = _relationship_dependency(
        parent, outer, context
    )
    coverage_query = _dependent_query(
        parent,
        cast(ValidatedRecords[object], structural.coverage),
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        subject,
    ).model_copy(
        update={"context_bundle_hashes": (content_hash(universe.identity_bundle),)}
    )
    coverage = resolve_listing_history_coverage(
        outer.listing_id,
        structural.coverage.records,
        coverage_query,
        universe.identity_bundle,
        structural.coverage.manifest,
        structural.coverage.decision,
        universe.policy,
        universe.retained_evidence,
    )
    termination_query = _dependent_query(
        parent,
        cast(ValidatedRecords[object], structural.terminations),
        M1bSelectionPurpose.LISTING_TERMINATION,
        subject,
    ).model_copy(
        update={"context_bundle_hashes": (content_hash(universe.identity_bundle),)}
    )
    termination = resolve_listing_termination(
        outer.listing_id,
        structural.terminations.records,
        coverage,
        termination_query,
        universe.identity_bundle,
        structural.terminations.manifest,
        structural.terminations.decision,
        universe.policy,
        universe.retained_evidence,
        coverage_versions=structural.coverage.records,
        coverage_manifest=structural.coverage.manifest,
        coverage_decision=structural.coverage.decision,
        identity_relationships=structural.relationships.records,
        relationship_resolution=relationship_resolution,
        relationship_proof=relationship_proof,
        relationship_manifest=structural.relationships.manifest,
        relationship_decision=structural.relationships.decision,
        identity_assignments=universe.assignments.records,
        assignment_manifest=universe.assignments.manifest,
        assignment_decision=universe.assignments.decision,
    )
    lifecycle_query = _dependent_query(
        parent,
        cast(ValidatedRecords[object], structural.lifecycle),
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        subject,
    ).model_copy(
        update={"context_bundle_hashes": (content_hash(universe.identity_bundle),)}
    )
    lifecycle = resolve_listing_lifecycle(
        outer.listing_id,
        structural.lifecycle.records,
        termination,
        lifecycle_query,
        universe.identity_bundle,
        structural.lifecycle.manifest,
        structural.lifecycle.decision,
        universe.policy,
        universe.retained_evidence,
        terminations=structural.terminations.records,
        termination_manifest=structural.terminations.manifest,
        termination_decision=structural.terminations.decision,
        coverage=coverage,
        coverage_versions=structural.coverage.records,
        coverage_manifest=structural.coverage.manifest,
        coverage_decision=structural.coverage.decision,
        identity_relationships=structural.relationships.records,
        relationship_resolution=relationship_resolution,
        relationship_proof=relationship_proof,
        relationship_manifest=structural.relationships.manifest,
        relationship_decision=structural.relationships.decision,
        identity_assignments=universe.assignments.records,
        assignment_manifest=universe.assignments.manifest,
        assignment_decision=universe.assignments.decision,
    )
    return lifecycle, termination, coverage


def _relationship_dependency(
    parent: NormalizedSelectionQueryV1,
    outer: ObservationQueryV1,
    context: M1dResolutionContext,
) -> tuple[IdentityResolutionResultV1, CutoffSelectionProofV1]:
    structural = context.structural_context
    assert structural is not None
    universe = structural.universe
    subject = IdentityReferenceV1(
        kind=IdentityKind.SECURITY, internal_id=outer.security_id
    )
    relationship_query = _dependent_query(
        parent,
        cast(ValidatedRecords[object], structural.relationships),
        M1bSelectionPurpose.IDENTITY_RESOLUTION,
        subject,
    ).model_copy(
        update={"context_bundle_hashes": (content_hash(universe.identity_bundle),)}
    )
    resolution = resolve_identity(
        subject,
        universe.assignments.records,
        structural.relationships.records,
        relationship_query,
        universe.identity_bundle,
        structural.relationships.manifest,
        structural.relationships.decision,
        universe.policy,
        universe.retained_evidence,
        assignment_manifest=universe.assignments.manifest,
        assignment_decision=universe.assignments.decision,
    )
    chains: dict[object, list[Any]] = {}
    for relationship in structural.relationships.records:
        if subject not in {relationship.left, relationship.right} and not (
            relationship.left.kind is subject.kind
            and relationship.right.kind is subject.kind
        ):
            continue
        chains.setdefault(relationship.revision.logical_record_id, []).append(
            relationship
        )
    selections = tuple(
        select_assertion_version(
            tuple(
                AssertionVersionProjectionV1(
                    revision=item.revision,
                    record_hash=content_hash(item),
                )
                for item in chain
            ),
            relationship_query.requested_channel,
            universe.policy,
            relationship_query.knowledge_cutoff,
            universe.retained_evidence,
        )
        for chain in chains.values()
    )
    proof = build_cutoff_selection_proof(
        relationship_query,
        selections,
        structural.relationships.manifest,
        structural.relationships.decision,
        (universe.identity_bundle,),
        _IDENTITY_RELATIONSHIP_SELECTION_IMPLEMENTATION_HASH,
    )
    return resolution, proof


def _classify_interval(
    segments: tuple[ListingEligibilitySegmentV1, ...],
    realized: RealizedSessionVersionV1 | None,
    contract: ObservationContractV1 | None,
    context: M1dResolutionContext,
) -> tuple[Literal["eligible", "ineligible", "indeterminate"], tuple[str, ...]]:
    if not segments:
        return "indeterminate", ("lifecycle_interval_unresolved",)
    structural = {item.structural_classification for item in segments}
    lifecycle = {item.lifecycle for item in segments}
    interruption_reasons: tuple[str, ...]
    if realized is not None and realized.interruption_intervals:
        if (
            contract is not None
            and _complete_realized_interruption_coverage(realized)
            and _compatible_interruption_policy(contract, context)
        ):
            interruption_reasons = ("realized_interruption_explicitly_aggregated",)
        else:
            return "indeterminate", ("realized_interruption_aggregation_unknown",)
    else:
        interruption_reasons = ()
    if lifecycle == {"active", "suspended"} and structural <= {
        "eligible",
        "ineligible",
    }:
        if (
            realized is not None
            and contract is not None
            and _complete_interruption_aggregation(segments, realized)
            and _compatible_interruption_policy(contract, context)
        ):
            return "eligible", tuple(
                sorted(
                    {
                        *interruption_reasons,
                        "partial_suspension_explicitly_aggregated",
                    }
                )
            )
        return "indeterminate", ("partial_suspension_aggregation_unknown",)
    if "ineligible" in structural or lifecycle in (
        {"not_yet_listed"},
        {"suspended"},
        {"terminated"},
    ):
        return "ineligible", ("known_ineligible_listing_interval",)
    if "indeterminate" in structural or "indeterminate" in lifecycle:
        return "indeterminate", ("listing_interval_indeterminate",)
    if lifecycle == {"active"} and structural == {"eligible"}:
        return "eligible", tuple(
            sorted({*interruption_reasons, "listing_interval_active"})
        )
    return "indeterminate", ("listing_interval_mixed",)


def _complete_interruption_aggregation(
    segments: tuple[ListingEligibilitySegmentV1, ...],
    realized: RealizedSessionVersionV1,
) -> bool:
    if realized.interruption_coverage != "complete":
        return False
    interrupted = tuple(item for item in segments if item.lifecycle == "suspended")
    claims = realized.interruption_intervals
    if len(interrupted) != len(claims):
        return False
    return all(
        claim.start.shape is BoundaryShape.EXACT
        and claim.end is not None
        and claim.end.shape is BoundaryShape.EXACT
        and claim.start.lower_bound == segment.opened_at
        and claim.end.upper_bound == segment.closed_at
        for claim, segment in zip(claims, interrupted, strict=True)
    )


def _complete_realized_interruption_coverage(
    realized: RealizedSessionVersionV1,
) -> bool:
    if (
        realized.interruption_coverage != "complete"
        or realized.actual_open is None
        or realized.actual_close is None
    ):
        return False
    intervals: list[tuple[datetime, datetime]] = []
    for claim in realized.interruption_intervals:
        if (
            claim.start.shape is not BoundaryShape.EXACT
            or claim.end is None
            or claim.end.shape is not BoundaryShape.EXACT
            or claim.start.lower_bound is None
            or claim.start.lower_bound != claim.start.upper_bound
            or claim.end.lower_bound is None
            or claim.end.lower_bound != claim.end.upper_bound
            or claim.start.lower_bound < realized.actual_open
            or claim.end.lower_bound > realized.actual_close
            or claim.end.lower_bound <= claim.start.lower_bound
        ):
            return False
        intervals.append((claim.start.lower_bound, claim.end.lower_bound))
    return all(
        prior_close <= next_open
        for (_prior_open, prior_close), (next_open, _next_close) in zip(
            intervals, intervals[1:], strict=False
        )
    )


def _compatible_interruption_policy(
    contract: ObservationContractV1, context: M1dResolutionContext
) -> bool:
    digest = contract.interval_policy.event_policy_hash
    artifact = context.supporting_artifacts.get(digest)
    if artifact is None:
        return False
    try:
        policy = InterruptionAggregationPolicyV1.model_validate_json(artifact.data)
    except ValidationError:
        return False
    return bool(
        artifact.byte_size == len(artifact.data)
        and artifact.content_hash == digest
        and sha256(artifact.data).hexdigest() == digest
        and canonical_json(policy) == artifact.data
        and content_hash(policy) == digest
        and policy.contract_id == contract.contract_id
        and policy.contract_version == contract.version
        and policy.source_id == contract.source_id
        and policy.required_fields == ("open", "high", "low", "close", "volume")
    )


def _interval_lifecycle(
    segments: tuple[ListingEligibilitySegmentV1, ...],
) -> ObservationLifecycleStatus:
    values = {item.lifecycle for item in segments}
    if not values or "indeterminate" in values:
        return "indeterminate"
    if values == {"active"} or values == {"active", "suspended"}:
        return "active"
    if len(values) == 1:
        return next(iter(values))
    return "indeterminate"


def _required_fields_status(
    observation: DailySourceObservationVersionV1 | None,
) -> RequiredFieldsStatus:
    if observation is None:
        return "unknown"
    fields = {item.field_name: item for item in observation.fields}
    required = {"open", "high", "low", "close", "volume"}
    if required - set(fields):
        return "partial"
    if any(fields[name].state in {"null", "omitted", "sentinel"} for name in required):
        return "partial"
    if any(fields[name].state == "unknown" for name in required):
        return "unknown"
    return "complete"


def _cutoff_axis(
    proof: M1dSelectionProofV1,
    observation: DailySourceObservationVersionV1 | None,
    query: ObservationQueryV1,
) -> Literal["eligible", "ineligible", "indeterminate"]:
    if proof.classification == "selected" and observation is not None:
        selected_evidence_hashes = {
            content_hash(item)
            for item in observation.revision.availability
            if item.channel == query.requested_channel
        }
        selected_decisions = tuple(
            item.classification.value
            for item in proof.availability_decisions
            if item.evidence_hash in selected_evidence_hashes
        )
        if selected_decisions and set(selected_decisions) == {"eligible"}:
            return "eligible"
        return "indeterminate"
    if proof.classification == "absent":
        decisions = tuple(
            item.classification.value for item in proof.availability_decisions
        )
        if "ineligible" in decisions:
            return "ineligible"
        if "indeterminate" in decisions:
            return "indeterminate"
        return "eligible"
    decisions = tuple(
        item.classification.value for item in proof.availability_decisions
    )
    return (
        "ineligible"
        if decisions and set(decisions) == {"ineligible"}
        else "indeterminate"
    )


def _profile_compatibility(
    query: ObservationQueryV1,
    observation: DailySourceObservationVersionV1 | None,
    contract: ObservationContractV1 | None,
    binding: str,
    context: M1dResolutionContext,
) -> tuple[ProfileCompatibilityStatus, tuple[str, ...], Mapping[str, Decimal] | None]:
    if query.profile_hash != regular_session_trade_bar_profile_hash():
        return "incompatible", ("unsupported_observation_profile",), None
    if observation is None or contract is None:
        return "indeterminate", ("source_claim_unavailable",), None
    fields = {item.field_name: item for item in observation.fields}
    if _required_fields_status(observation) != "complete":
        return "incompatible", ("required_source_fields_incomplete",), None
    required = ("open", "high", "low", "close", "volume")
    values = {name: fields[name].value for name in required}
    if any(value is None for value in values.values()):
        return "incompatible", ("required_source_value_missing",), None
    exact_values = cast(dict[str, Decimal], values)
    if any(value <= 0 for value in exact_values.values()):
        return "incompatible", ("required_source_value_not_positive",), None
    if not (
        exact_values["low"]
        <= min(exact_values["open"], exact_values["close"])
        <= max(exact_values["open"], exact_values["close"])
        <= exact_values["high"]
    ):
        return "incompatible", ("source_price_range_invalid",), None
    if contract.currency != "USD" or contract.adjustment_basis != "unadjusted":
        return "incompatible", ("source_basis_incompatible",), None
    methods = {
        (item.field_name, item.method_id): item for item in contract.field_methods
    }
    selected = {name: methods.get((name, fields[name].method_id)) for name in required}
    if any(value is None for value in selected.values()):
        return "incompatible", ("source_method_not_selected",), None
    selected_methods = cast(dict[str, ObservationFieldMethodV1], selected)
    expected_selectors = {
        "open": "first",
        "high": "maximum",
        "low": "minimum",
        "close": "last",
        "volume": "sum",
    }
    expected_meanings = {
        "open": {"first_trade_price", "official_open"},
        "high": {"maximum_trade_price"},
        "low": {"minimum_trade_price"},
        "close": {"last_trade_price", "official_close"},
        "volume": {"share_volume"},
    }
    price_populations = {
        selected_methods[name].population_id
        for name in ("open", "high", "low", "close")
    }
    if (
        len(price_populations) != 1
        or any(
            selected_methods[name].effective_selector != selector
            for name, selector in expected_selectors.items()
        )
        or any(
            selected_methods[name].meaning not in meanings
            for name, meanings in expected_meanings.items()
        )
    ):
        return "incompatible", ("source_selector_or_population_incompatible",), None
    if any(
        selected_methods[name].unit != "currency_per_share"
        or selected_methods[name].adjustment_basis != "unadjusted"
        or selected_methods[name].intraday_basis_homogeneity != "homogeneous"
        or selected_methods[name].ordering != "execution_time_then_source_sequence"
        or selected_methods[name].ordering_policy_hash
        not in context.supporting_artifacts
        for name in ("open", "high", "low", "close")
    ) or (
        selected_methods["volume"].unit != "shares"
        or selected_methods["volume"].adjustment_basis != "unadjusted"
        or selected_methods["volume"].intraday_basis_homogeneity != "homogeneous"
    ):
        return "incompatible", ("source_field_basis_or_unit_incompatible",), None
    price_population = next(iter(price_populations))
    volume_population = selected_methods["volume"].population_id
    relationship = next(
        (
            item
            for item in contract.volume_relationships
            if item.price_population_id == price_population
            and item.volume_population_id == volume_population
            and item.relation in {"equal", "price_subset_of_volume"}
        ),
        None,
    )
    population = next(
        (
            item
            for item in contract.populations
            if item.population_id == price_population
        ),
        None,
    )
    if (
        relationship is None
        or population is None
        or (
            population.session_scope != "regular"
            or population.event_time_basis != "execution"
            or query.venue.value not in population.venue_scope
            or population.odd_lot_rule not in {"included", "excluded"}
            or population.opening_auction_rule not in {"included", "excluded"}
            or population.closing_auction_rule not in {"included", "excluded"}
            or population.sale_condition_policy_hash not in context.supporting_artifacts
            or population.correction_cancellation_policy_hash
            not in context.supporting_artifacts
            or relationship.evidence_hash not in context.supporting_artifacts
            or contract.interval_policy.event_policy_hash
            not in context.supporting_artifacts
        )
    ):
        return "incompatible", ("source_population_profile_incompatible",), None
    if binding != "bound":
        return "indeterminate", ("exact_realized_binding_unavailable",), exact_values
    return "compatible", ("regular_session_trade_bar_profile_satisfied",), exact_values


def _provider_gap_is_proven(
    record_presence: str,
    coverage: ObservationCoverageVersionV1 | None,
    realized: RealizedSessionVersionV1 | None,
    contract: ObservationContractV1 | None,
    eligibility: ListingSessionEligibilityResultV1,
    cutoff_availability: str,
    query: ObservationQueryV1,
) -> bool:
    return bool(
        record_presence == "absent"
        and realized is not None
        and realized.outcome == "opened"
        and realized.actual_open is not None
        and realized.actual_close is not None
        and eligibility.classification == "eligible"
        and contract is not None
        and contract.row_emission.kind == "every_relevant_session"
        and coverage is not None
        and coverage.status == "expected_complete"
        and coverage.revision_history_completeness == "complete"
        and coverage.methodology_artifact_hash == contract.methodology_artifact_hash
        and coverage.omission_rule_hash
        == contract.row_emission.omission_marker_policy_hash
        and _coverage_snapshot_is_causal(coverage, query)
        and not coverage.exception_keys
        and not coverage.missing_artifact_hashes
        and cutoff_availability == "eligible"
    )


def _coverage_snapshot_is_causal(
    coverage: ObservationCoverageVersionV1, query: ObservationQueryV1
) -> bool:
    snapshot = coverage.snapshot_as_of
    if (
        snapshot.shape is not BoundaryShape.EXACT
        or snapshot.upper_bound is None
        or snapshot.upper_bound > observation_cutoff(query)
    ):
        return False
    availability = next(
        (
            item
            for item in coverage.revision.availability
            if item.channel == query.requested_channel
        ),
        None,
    )
    return bool(
        availability is not None
        and availability.lower_bound is not None
        and availability.upper_bound is not None
        and availability.lower_bound >= snapshot.upper_bound
        and availability.upper_bound >= snapshot.upper_bound
    )


def _compose_usability(
    *,
    scheduled_day: str,
    realized_outcome: str,
    eligibility: str,
    record_presence: str,
    required_fields: str,
    cutoff_availability: str,
    profile: str,
    binding: str,
    qualifying_activity: str,
) -> Literal["usable", "unusable", "indeterminate"]:
    if (
        scheduled_day == "closed"
        or realized_outcome == "did_not_open"
        or eligibility == "ineligible"
        or record_presence == "absent"
        or required_fields == "partial"
        or cutoff_availability == "ineligible"
        or profile == "incompatible"
        or binding == "conflict"
        or qualifying_activity == "explicit_none"
    ):
        return "unusable"
    if (
        scheduled_day == "unknown"
        or realized_outcome == "unknown"
        or eligibility == "indeterminate"
        or record_presence == "unknown"
        or required_fields == "unknown"
        or cutoff_availability == "indeterminate"
        or profile == "indeterminate"
        or binding == "indeterminate"
        or qualifying_activity == "unknown"
    ):
        return "indeterminate"
    return "usable"


def _one[T](values: Sequence[object], expected: type[T]) -> T | None:
    return values[0] if len(values) == 1 and isinstance(values[0], expected) else None


def _requested_observation_artifact_hash(context: M1dResolutionContext) -> str:
    for dataset in context.observation_datasets:
        if dataset.manifest.dataset_role.name == "source_observation":
            if dataset.manifest.partitions:
                return dataset.manifest.partitions[0].artifact.content_hash
    return "0" * 64


def _validate_assessment_authority(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> None:
    if query.input_context_hash != m1d_context_hash(context):
        raise ValueError("observation query context hash mismatch")
    if any(
        item.manifest.dataset_role.name
        not in {"source_observation", "observation_coverage"}
        for item in context.observation_datasets
    ) or any(
        item.manifest.dataset_role.name
        not in {"scheduled_session", "realized_session", "session_coverage"}
        for item in context.session_datasets
    ):
        raise ValueError("M1d context dataset slot mismatch")
    context_datasets = tuple(
        cast(Any, item)
        for item in (*context.observation_datasets, *context.session_datasets)
    )
    identities = tuple(
        (item.manifest.source.source_id, item.manifest.dataset_role.name)
        for item in context_datasets
    )
    if len(set(identities)) != len(identities):
        raise ValueError("M1d context contains duplicate source-role authority")
    for key, policy_value in context.availability_policies.items():
        if key != content_hash(policy_value):
            raise ValueError("M1d availability policy mapping mismatch")
    for key, evidence in context.retained_evidence.items():
        if key != content_hash(evidence):
            raise ValueError("M1d availability evidence mapping mismatch")
    for key, support in context.supporting_artifacts.items():
        if (
            key != support.content_hash
            or support.byte_size != len(support.data)
            or sha256(support.data).hexdigest() != support.content_hash
        ):
            raise ValueError("M1d supporting artifact mapping mismatch")
    for dataset in context_datasets:
        if (
            dataset.decision.result.value != "pass"
            or dataset.decision.manifest_hash != manifest_hash(dataset.manifest)
        ):
            raise ValueError("M1d validated dataset authority mismatch")
        rebuilt_bundle = build_validated_dataset_bundle(
            bundle_id=dataset.bundle.bundle_id,
            bundle_version=dataset.bundle.bundle_version,
            created_at=dataset.bundle.created_at,
            validated_datasets=((dataset.manifest, dataset.decision),),
        )
        if rebuilt_bundle != dataset.bundle:
            raise ValueError("M1d dataset bundle authority mismatch")
    availability_policy = context.availability_policies.get(
        query.availability_policy_hash
    )
    if (
        availability_policy is None
        or availability_policy.policy_id != query.availability_policy_id
        or content_hash(availability_policy) != query.availability_policy_hash
    ):
        raise ValueError("observation availability policy binding mismatch")
    artifact = context.supporting_artifacts.get(query.source_selection_policy_hash)
    if artifact is None:
        raise ValueError("source selection policy bytes unavailable")
    try:
        policy = ObservationSourceSelectionPolicyV1.model_validate_json(artifact.data)
    except ValidationError as error:
        raise ValueError("source selection policy bytes invalid") from error
    if (
        artifact.byte_size != len(artifact.data)
        or artifact.content_hash != query.source_selection_policy_hash
        or sha256(artifact.data).hexdigest() != query.source_selection_policy_hash
        or canonical_json(policy) != artifact.data
        or content_hash(policy) != query.source_selection_policy_hash
    ):
        raise ValueError("source selection policy hash mismatch")
    if not any(
        item.dataset_role == "source_observation"
        and item.source_id == query.source_id
        and item.contract_hash == query.contract_hash
        and item.venue is query.venue
        and item.listing_id == query.listing_id
        and item.start_date <= query.session_date <= item.end_date
        for item in policy.bindings
    ):
        raise ValueError("source selection policy query binding mismatch")
    if context.structural_context is not None:
        _m1b_requested_channel(query, context)
    _load_schedule_generation_policy(context)


def _verify_requested_observation_bytes(context: M1dResolutionContext) -> None:
    found = False
    for dataset in context.observation_datasets:
        if dataset.manifest.dataset_role.name not in {
            "source_observation",
            "observation_coverage",
        }:
            continue
        for partition in dataset.manifest.partitions:
            found = True
            digest = partition.artifact.content_hash
            artifact = dataset.artifacts.get(digest)
            if artifact is None:
                raise ObservationArtifactUnavailableError(
                    "requested observation artifact is unavailable"
                )
            if (
                artifact.content_hash != digest
                or artifact.byte_size != partition.byte_size
                or artifact.byte_size != len(artifact.data)
                or sha256(artifact.data).hexdigest() != digest
            ):
                raise ArtifactIntegrityError(
                    "requested observation artifact is corrupt"
                )
    if not found:
        raise ObservationArtifactUnavailableError(
            "requested observation artifact is unavailable"
        )


def _read_failure(
    query: ObservationQueryV1,
    requested_hash: str,
    integrity: Literal["corrupt", "unavailable"],
) -> ObservationReadFailureV1:
    return ObservationReadFailureV1(
        query=query,
        query_hash=content_hash(query),
        requested_artifact_hash=requested_hash,
        integrity=integrity,
        error_code=(
            "artifact_integrity_error"
            if integrity == "corrupt"
            else "observation_artifact_unavailable"
        ),
        usability="unusable" if integrity == "corrupt" else "indeterminate",
        context_hash=query.input_context_hash,
        semantic_algorithm_hash=observation_usability_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
    )
