"""Replay M1c split occurrences onto exact M1d realized sessions."""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, cast

from pydantic import BaseModel, ValidationError

from drift.domain.action_sessions import (
    ActionBasisBoundaryV1,
    ActionDateProjectionV1,
    ActionDateRoleMethodologyV1,
    ActionSessionPolicyV1,
    ActionSessionQueryV1,
    ActionSessionTransitionClaimV1,
    ActionShareComponentProjectionV1,
    FirstPostActionSessionResultV1,
    action_session_algorithm_hash,
)
from drift.domain.economic_common import ActionKind, ShareComponentV1
from drift.domain.economic_coverage import policy_owner
from drift.domain.economic_events import (
    CancelledActionV1,
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    OccurredEffectV1,
    TermsPayloadV1,
    UnknownEffectV1,
)
from drift.domain.economic_queries import (
    MarketDecisionQueryV1,
    MarketOutcomeQueryV1,
    MarketSelectionQueryV1,
)
from drift.domain.economic_results import (
    EconomicAssociationResolutionV1,
    EconomicEffectProjectionV1,
    EconomicOutcomeResolutionV1,
)
from drift.domain.observation_query import m1d_implementation_hash
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    SelectedSessionRecordsV1,
    SessionCoverageVersionV1,
    SessionKeyV1,
)
from drift.markets.economic_outcomes import resolve_economic_facts
from drift.markets.economic_selection import select_market_records
from drift.markets.economic_validation import economic_context_hash
from drift.markets.observation_selection import (
    select_observation_records,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
)
from drift.serialization.canonical import canonical_json, content_hash

_REQUIRED_ACTION_KINDS = tuple(
    sorted(
        (
            ActionKind.FORWARD_SPLIT,
            ActionKind.REVERSE_SPLIT,
            ActionKind.REGULAR_CASH_DIVIDEND,
            ActionKind.SPECIAL_CASH_DISTRIBUTION,
            ActionKind.STOCK_DIVIDEND,
            ActionKind.CASH_ACQUISITION,
            ActionKind.STOCK_ACQUISITION,
            ActionKind.MIXED_ACQUISITION,
            ActionKind.SPINOFF,
            ActionKind.CONVERSION,
            ActionKind.LIQUIDATION,
            ActionKind.BANKRUPTCY_REORGANIZATION,
            ActionKind.RIGHTS_WARRANTS_CVR,
            ActionKind.OTHER_UNSUPPORTED,
        ),
        key=lambda item: item.value,
    )
)


def map_action_to_session(
    query: ActionSessionQueryV1, context: M1dResolutionContext
) -> FirstPostActionSessionResultV1:
    """Map one replayed occurred split to its first proven post-basis session."""
    validate_m1d_resolution_context(context)
    if query.outer_query.input_context_hash != m1d_context_hash(context):
        raise ValueError("action session query context mismatch")
    economic_context = context.economic_context
    source_policy = context.economic_source_policy
    if economic_context is None or source_policy is None:
        raise ValueError("action session mapping requires exact M1c context and policy")
    if (
        content_hash(source_policy) != query.economic_source_policy_hash
        or source_policy.security_id != query.security_id
    ):
        raise ValueError("action session economic source policy mismatch")

    policy = _load_artifact_model(
        query.action_session_policy_hash, ActionSessionPolicyV1, context
    )
    methodology = _load_artifact_model(
        policy.date_role_methodology_hash, ActionDateRoleMethodologyV1, context
    )
    economic_query = _economic_query(query, context)
    base_dependencies = {
        query.outer_query.input_context_hash,
        query.action_session_policy_hash,
        policy.date_role_methodology_hash,
        query.economic_source_policy_hash,
        action_session_algorithm_hash(),
        m1d_implementation_hash(),
        content_hash(economic_query),
    }

    def finish(
        classification: Literal["mapped", "not_applicable", "indeterminate"],
        reasons: Sequence[str],
        *,
        outcome: EconomicOutcomeResolutionV1 | None = None,
        first_post_session: SessionKeyV1 | None = None,
        transition: ActionSessionTransitionClaimV1 | None = None,
        projection: ActionDateProjectionV1 | None = None,
        same_occurrence_hashes: Sequence[str] = (),
        selected_session_proof_hashes: Sequence[str] = (),
        selected_session_record_hashes: Sequence[str] = (),
        association: EconomicAssociationResolutionV1 | None = None,
        additional_dependencies: Sequence[str] = (),
    ) -> FirstPostActionSessionResultV1:
        dependencies = set(base_dependencies)
        dependencies.update(additional_dependencies)
        dependencies.update(selected_session_proof_hashes)
        dependencies.update(selected_session_record_hashes)
        if outcome is not None:
            dependencies.update(
                {
                    content_hash(outcome),
                    outcome.selection_proof_hash,
                    *outcome.safe_projection_hashes,
                }
            )
        if projection is not None:
            dependencies.add(content_hash(projection))
        if association is not None:
            dependencies.add(content_hash(association))
        return FirstPostActionSessionResultV1(
            query=query,
            query_hash=content_hash(query),
            classification=classification,
            first_post_session=first_post_session,
            transition_claim=transition,
            economic_query=economic_query,
            economic_query_hash=content_hash(economic_query),
            economic_outcome_hash=(
                content_hash(outcome) if outcome is not None else None
            ),
            economic_selection_proof_hash=(
                outcome.selection_proof_hash if outcome is not None else None
            ),
            source_selection_policy_hash=query.economic_source_policy_hash,
            selected_terms_hash=query.selected_terms_hash,
            selected_effect_hash=query.selected_effect_hash,
            same_occurrence_effect_hashes=tuple(sorted(set(same_occurrence_hashes))),
            selected_session_proof_hashes=tuple(
                sorted(set(selected_session_proof_hashes))
            ),
            selected_session_record_hashes=tuple(
                sorted(set(selected_session_record_hashes))
            ),
            date_projection_hash=(
                content_hash(projection) if projection is not None else None
            ),
            association_result_hash=(
                content_hash(association) if association is not None else None
            ),
            reasons=tuple(reasons),
            dependency_hashes=tuple(dependencies),
            policy_hash=query.action_session_policy_hash,
            context_hash=query.outer_query.input_context_hash,
            semantic_algorithm_hash=action_session_algorithm_hash(),
            implementation_hash=m1d_implementation_hash(),
        )

    policy_reasons = _policy_reasons(query, policy, methodology)
    if policy_reasons:
        return finish("indeterminate", policy_reasons)
    if set(source_policy.action_kinds) != set(_REQUIRED_ACTION_KINDS):
        return finish("indeterminate", ("economic_action_class_coverage_incomplete",))
    if policy_owner(source_policy, "effect").source_id != query.source_id:
        return finish("indeterminate", ("selected_effect_source_mismatch",))

    outcome = resolve_economic_facts(economic_query, economic_context, source_policy)
    proof = select_market_records(economic_query, economic_context, source_policy)
    records = {
        content_hash(record): record
        for dataset in economic_context.datasets
        for record in dataset.records
    }
    selected_hashes = set(proof.revision_selected_record_hashes)
    effect = records.get(query.selected_effect_hash)
    if query.selected_effect_hash not in selected_hashes or not isinstance(
        effect, EconomicEffectVersionV1
    ):
        return finish(
            "indeterminate",
            ("selected_effect_not_causally_selected",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof),),
        )
    if effect.source_key.source_id != query.source_id:
        return finish(
            "indeterminate",
            ("selected_effect_source_mismatch",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof),),
        )
    if effect.security_id != query.security_id:
        return finish(
            "indeterminate",
            ("selected_effect_security_mismatch",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof),),
        )
    payload = effect.payload
    if isinstance(payload, CancelledActionV1):
        return finish(
            "not_applicable",
            ("selected_action_cancelled",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof), query.selected_effect_hash),
        )
    if isinstance(payload, UnknownEffectV1) or payload is None:
        return finish(
            "indeterminate",
            ("selected_action_occurrence_unknown",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof), query.selected_effect_hash),
        )
    if not isinstance(payload, OccurredEffectV1):
        return finish(
            "indeterminate",
            ("selected_action_occurrence_unproved",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof),),
        )
    effect_projection = next(
        (
            item
            for item in outcome.effect_projections
            if item.source_record_hash == query.selected_effect_hash
        ),
        None,
    )
    if effect_projection is None or effect_projection.effective_status not in {
        "before_window",
        "effective",
    }:
        return finish(
            "indeterminate",
            ("selected_action_occurrence_not_effective",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof), query.selected_effect_hash),
        )
    if (
        effect.occurrence.kind != "identified"
        or effect.occurrence.native_occurrence_id != query.native_occurrence_id
    ):
        return finish(
            "indeterminate",
            ("selected_effect_occurrence_mismatch",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof),),
        )
    if payload.action_kind not in {
        ActionKind.FORWARD_SPLIT,
        ActionKind.REVERSE_SPLIT,
    }:
        return finish(
            "not_applicable",
            ("selected_action_not_a_split",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof),),
        )

    required_coverage = {
        item.family: item
        for item in outcome.coverage_results
        if item.family in {"terms", "effect"}
    }
    if any(
        family not in required_coverage
        or required_coverage[family].status != "complete"
        or not required_coverage[family].occurrence_identity_supported
        for family in ("terms", "effect")
    ):
        return finish(
            "indeterminate",
            ("economic_action_class_coverage_incomplete",),
            outcome=outcome,
            additional_dependencies=(content_hash(proof),),
        )
    settlement_incomplete = any(
        item.family == "settlement" and item.status != "complete"
        for item in outcome.coverage_results
    )
    association_map = {
        (item.source_record_hash, item.association_field): item
        for item in outcome.associations
    }
    effect_projection_map = {
        item.source_record_hash: item for item in outcome.effect_projections
    }
    same_occurrence = tuple(
        record
        for record_hash, record in records.items()
        if record_hash in selected_hashes
        and isinstance(record, EconomicEffectVersionV1)
        and record.source_key.source_id == query.source_id
        and record.security_id == query.security_id
        and record.occurrence.kind == "identified"
        and record.occurrence.native_occurrence_id == query.native_occurrence_id
    )
    same_occurrence_hashes = tuple(content_hash(item) for item in same_occurrence)
    projections: list[
        tuple[
            ActionBasisBoundaryV1,
            ActionShareComponentProjectionV1,
            CorporateActionTermsVersionV1 | None,
            EconomicAssociationResolutionV1 | None,
            str,
        ]
    ] = []
    projection_reasons: list[str] = []
    for candidate in same_occurrence:
        built, candidate_reasons = _project_candidate(
            candidate,
            query,
            methodology,
            records,
            selected_hashes,
            association_map,
            effect_projection_map,
        )
        if built is None:
            projection_reasons.extend(candidate_reasons)
        else:
            projections.append(built)
    if projection_reasons or len(projections) != len(same_occurrence):
        selected_association = (
            None
            if query.selected_terms_hash is None
            else association_map.get((query.selected_effect_hash, "terms"))
        )
        return finish(
            "indeterminate",
            projection_reasons or ("same_occurrence_projection_incomplete",),
            outcome=outcome,
            same_occurrence_hashes=same_occurrence_hashes,
            association=selected_association,
            additional_dependencies=(content_hash(proof), *same_occurrence_hashes),
        )
    signatures: set[str] = set()
    for candidate, (candidate_boundary, candidate_share, _, _, date_source_id) in zip(
        same_occurrence, projections, strict=True
    ):
        assert isinstance(candidate.payload, OccurredEffectV1)
        signatures.add(
            content_hash(
                {
                    "boundary": candidate_boundary,
                    "effect_boundary": {
                        "shape": candidate.effective_time.shape,
                        "lower_bound": candidate.effective_time.lower_bound,
                        "upper_bound": candidate.effective_time.upper_bound,
                        "source_precision": candidate.effective_time.source_precision,
                        "source_time_label": candidate.effective_time.source_time_label,
                        "source_timezone": candidate.effective_time.source_timezone,
                    },
                    "action_kind": candidate.payload.action_kind,
                    "effect_source_id": candidate.source_key.source_id,
                    "date_source_id": date_source_id,
                    "share": {
                        "recipient_security_id": (
                            candidate_share.recipient_security_id
                        ),
                        "predecessor_security_id": (
                            candidate_share.predecessor_security_id
                        ),
                        "ratio": candidate_share.ratio,
                        "ratio_meaning": candidate_share.ratio_meaning,
                        "share_basis": candidate_share.share_basis,
                        "applicability": candidate_share.applicability,
                    },
                }
            )
        )
    if len(signatures) != 1:
        return finish(
            "indeterminate",
            ("same_occurrence_economic_disagreement",),
            outcome=outcome,
            same_occurrence_hashes=same_occurrence_hashes,
            additional_dependencies=(content_hash(proof), *same_occurrence_hashes),
        )

    selected_index = same_occurrence_hashes.index(query.selected_effect_hash)
    boundary, share, terms, association, date_source_id = projections[selected_index]
    date_record: CorporateActionTermsVersionV1 | EconomicEffectVersionV1 = (
        cast(CorporateActionTermsVersionV1, terms)
        if methodology.field_origin == "selected_terms_date"
        else effect
    )
    assert date_record.listing_id is not None
    projection = ActionDateProjectionV1(
        query_hash=content_hash(query),
        effect_source_id=query.source_id,
        date_source_id=date_source_id,
        native_occurrence_id=query.native_occurrence_id,
        action_kind=payload.action_kind,
        listing_id=date_record.listing_id,
        security_id=date_record.security_id,
        mic=query.mic,
        selected_terms_hash=query.selected_terms_hash,
        selected_effect_hash=query.selected_effect_hash,
        same_occurrence_effect_hashes=same_occurrence_hashes,
        association_result_hashes=tuple(
            content_hash(item[3]) for item in projections if item[3] is not None
        ),
        date_role=methodology.date_role,
        basis_boundary=boundary,
        share_component=share,
        date_role_methodology_hash=policy.date_role_methodology_hash,
        economic_query_hash=content_hash(economic_query),
        economic_outcome_hash=content_hash(outcome),
        economic_selection_proof_hash=outcome.selection_proof_hash,
        economic_source_policy_hash=query.economic_source_policy_hash,
    )
    if methodology.mapping_mode == "exact_trading_basis_transition" and (
        boundary.upper_bound is None or boundary.upper_bound > _outer_horizon(query)
    ):
        return finish(
            "indeterminate",
            ("basis_transition_beyond_outer_horizon",),
            outcome=outcome,
            projection=projection,
            same_occurrence_hashes=same_occurrence_hashes,
            association=association,
            additional_dependencies=(content_hash(proof),),
        )

    mapping = _map_projection_to_session(query, context, methodology, projection)
    mapping_reasons = list(mapping.reasons)
    if settlement_incomplete:
        mapping_reasons.append("settlement_coverage_incomplete_audit_only")
    return finish(
        mapping.classification,
        mapping_reasons,
        outcome=outcome,
        first_post_session=mapping.session_key,
        transition=mapping.transition,
        projection=projection,
        same_occurrence_hashes=same_occurrence_hashes,
        selected_session_proof_hashes=mapping.proof_hashes,
        selected_session_record_hashes=mapping.record_hashes,
        association=association,
        additional_dependencies=(content_hash(proof), *same_occurrence_hashes),
    )


def verify_action_session_mapping(
    result: FirstPostActionSessionResultV1, context: M1dResolutionContext
) -> None:
    """Replay and compare the complete action/session mapping result."""
    expected = map_action_to_session(result.query, context)
    if result != expected or content_hash(result) != content_hash(expected):
        raise ValueError("action session mapping replay mismatch")


def _load_artifact_model[T: BaseModel](
    digest: str, model: type[T], context: M1dResolutionContext
) -> T:
    artifact = context.supporting_artifacts.get(digest)
    if artifact is None:
        raise ValueError("action session policy artifact unavailable")
    try:
        parsed = model.model_validate_json(artifact.data)
    except ValidationError as error:
        raise ValueError("action session policy artifact invalid") from error
    if canonical_json(parsed) != artifact.data or content_hash(parsed) != digest:
        raise ValueError("action session policy artifact hash mismatch")
    return parsed


def _economic_query(
    query: ActionSessionQueryV1, context: M1dResolutionContext
) -> MarketSelectionQueryV1:
    economic_context = context.economic_context
    source_policy = context.economic_source_policy
    assert economic_context is not None and source_policy is not None
    outer = query.outer_query
    if outer.kind == "decision":
        return MarketDecisionQueryV1(
            schema_version="1",
            kind="decision",
            purpose="economic_facts",
            security_id=query.security_id,
            action_kinds=_REQUIRED_ACTION_KINDS,
            history_start=source_policy.history_start,
            requested_channel=outer.requested_channel,
            availability_policy_id=economic_context.availability_policy.policy_id,
            availability_policy_hash=content_hash(economic_context.availability_policy),
            source_selection_policy_hash=query.economic_source_policy_hash,
            input_context_hash=economic_context_hash(economic_context),
            decision_time=outer.decision_time,
            knowledge_cutoff=outer.knowledge_cutoff,
            effective_cutoff=outer.effective_cutoff,
        )
    return MarketOutcomeQueryV1(
        schema_version="1",
        kind="outcome",
        purpose="economic_outcome",
        security_id=query.security_id,
        action_kinds=_REQUIRED_ACTION_KINDS,
        history_start=source_policy.history_start,
        requested_channel=outer.requested_channel,
        availability_policy_id=economic_context.availability_policy.policy_id,
        availability_policy_hash=content_hash(economic_context.availability_policy),
        source_selection_policy_hash=query.economic_source_policy_hash,
        input_context_hash=economic_context_hash(economic_context),
        economic_horizon=outer.economic_horizon,
        evidence_vintage_cutoff=outer.evidence_vintage_cutoff,
    )


def _policy_reasons(
    query: ActionSessionQueryV1,
    policy: ActionSessionPolicyV1,
    methodology: ActionDateRoleMethodologyV1,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if policy.mapping_mode != methodology.mapping_mode:
        reasons.append("date_methodology_mapping_mode_mismatch")
    if (
        methodology.effect_source_id != query.source_id
        or methodology.security_id != query.security_id
        or methodology.listing_id != query.listing_id
        or methodology.mic != query.mic
    ):
        reasons.append("date_methodology_subject_mismatch")
    if (
        methodology.field_origin == "selected_effect_time"
        and methodology.date_source_id != query.source_id
    ):
        reasons.append("date_methodology_source_mismatch")
    if methodology.mapping_mode == "explicit_first_basis_date" and (
        methodology.date_role not in {"ex", "trading_basis"}
    ):
        reasons.append("date_role_not_trading_basis")
    if methodology.mapping_mode == "exact_trading_basis_transition" and (
        methodology.field_origin == "selected_terms_date"
        and methodology.date_role != "trading_basis"
    ):
        reasons.append("date_role_not_trading_basis")
    return tuple(reasons)


def _project_candidate(
    effect: EconomicEffectVersionV1,
    query: ActionSessionQueryV1,
    methodology: ActionDateRoleMethodologyV1,
    records: Mapping[str, object],
    selected_hashes: set[str],
    associations: Mapping[
        tuple[str, Literal["terms", "effect"]], EconomicAssociationResolutionV1
    ],
    effect_projections: Mapping[str, EconomicEffectProjectionV1],
) -> tuple[
    tuple[
        ActionBasisBoundaryV1,
        ActionShareComponentProjectionV1,
        CorporateActionTermsVersionV1 | None,
        EconomicAssociationResolutionV1 | None,
        str,
    ]
    | None,
    tuple[str, ...],
]:
    payload = effect.payload
    if not isinstance(payload, OccurredEffectV1):
        return None, ("same_occurrence_contains_nonoccurred_report",)
    if effect.listing_id != query.listing_id:
        return None, ("selected_effect_listing_mismatch",)
    effect_projection = effect_projections.get(content_hash(effect))
    if effect_projection is None or effect_projection.component_gaps:
        return None, ("pure_split_component_shape_unproved",)
    effect_share = _share_projection(payload.owed_components, query.security_id)
    if effect_share is None:
        return None, ("pure_split_component_shape_unproved",)
    if not _ratio_direction_valid(payload.action_kind, effect_share):
        return None, ("split_ratio_direction_mismatch",)
    if (
        payload.action_kind not in {ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT}
        or payload.claim_status != "continuing"
        or payload.consideration_status != "components"
    ):
        return None, ("pure_split_effect_shape_unproved",)
    effect_only = (
        methodology.field_origin == "selected_effect_time"
        and query.selected_terms_hash is None
    )
    association: EconomicAssociationResolutionV1 | None = None
    terms: CorporateActionTermsVersionV1 | None = None
    if not effect_only:
        association = associations.get((content_hash(effect), "terms"))
        if association is None or association.status != "resolved":
            return None, ("selected_terms_association_unresolved",)
        target_hash = association.selected_target_hash
        target = records.get(target_hash or "")
        if target_hash not in selected_hashes or not isinstance(
            target, CorporateActionTermsVersionV1
        ):
            return None, ("selected_terms_association_unresolved",)
        terms = target
        if content_hash(effect) == query.selected_effect_hash:
            if query.selected_terms_hash is None:
                return None, ("selected_terms_required_for_terms_date",)
            if target_hash != query.selected_terms_hash:
                return None, ("selected_terms_association_mismatch",)
        if not isinstance(terms.payload, TermsPayloadV1):
            return None, ("selected_terms_payload_unavailable",)
        if terms.payload.kind != "fixed":
            return None, ("selected_terms_not_fixed",)
        if terms.payload.action_kind != payload.action_kind:
            return None, ("selected_terms_effect_action_kind_mismatch",)
        if terms.listing_id != query.listing_id:
            return None, ("selected_terms_listing_mismatch",)
        terms_share = _share_projection(terms.payload.components, query.security_id)
        if terms_share is None or _share_economic_signature(terms_share) != (
            _share_economic_signature(effect_share)
        ):
            return None, ("pure_split_component_shape_unproved",)
    if methodology.field_origin == "selected_terms_date":
        assert terms is not None
        assert isinstance(terms.payload, TermsPayloadV1)
        if methodology.date_source_id != terms.source_key.source_id:
            return None, ("date_methodology_source_mismatch",)
        matching_dates = tuple(
            item for item in terms.payload.dates if item.role == methodology.date_role
        )
        if len(matching_dates) != 1:
            return None, ("selected_terms_basis_date_unavailable",)
        source_boundary = matching_dates[0].boundary
        date_source_id = terms.source_key.source_id
    else:
        if methodology.mapping_mode != "exact_trading_basis_transition":
            return None, ("effect_time_not_valid_for_date_mapping",)
        source_boundary = effect.effective_time
        date_source_id = effect.source_key.source_id
    if source_boundary.source_time_label is None:
        return None, ("action_boundary_source_label_unavailable",)
    boundary = ActionBasisBoundaryV1(
        shape=source_boundary.shape,
        lower_bound=source_boundary.lower_bound,
        upper_bound=source_boundary.upper_bound,
        source_precision=source_boundary.source_precision,
        source_time_label=source_boundary.source_time_label,
        source_timezone=source_boundary.source_timezone,
    )
    if methodology.mapping_mode == "explicit_first_basis_date":
        try:
            date.fromisoformat(boundary.source_time_label)
        except ValueError:
            return None, ("first_basis_date_not_exact_local_date",)
    elif boundary.shape.value != "exact":
        return None, ("trading_basis_transition_not_exact",)
    return (boundary, effect_share, terms, association, date_source_id), ()


def _share_projection(
    components: Sequence[object], security_id: object
) -> ActionShareComponentProjectionV1 | None:
    if len(components) != 1:
        return None
    matches = tuple(
        item
        for item in components
        if isinstance(item, ShareComponentV1)
        and item.recipient.kind == "security"
        and item.recipient.security_id == security_id
        and item.unit_basis.security_id == security_id
        and item.ratio_meaning == "resulting_per_predecessor"
        and item.unit_basis.share_basis == "predecessor_pre_action"
        and item.applicability == "ordinary_passive_holder"
        and not item.conditions
    )
    if len(matches) != 1:
        return None
    item = matches[0]
    assert item.recipient.security_id is not None
    return ActionShareComponentProjectionV1(
        source_component_hash=content_hash(item),
        component_id=item.component_id,
        recipient_security_id=item.recipient.security_id,
        predecessor_security_id=item.unit_basis.security_id,
        ratio=item.ratio,
        ratio_meaning="resulting_per_predecessor",
        share_basis="predecessor_pre_action",
        applicability="ordinary_passive_holder",
    )


def _ratio_direction_valid(
    action_kind: ActionKind, component: ActionShareComponentProjectionV1
) -> bool:
    numerator = int(component.ratio.numerator)
    denominator = int(component.ratio.denominator)
    if action_kind == ActionKind.FORWARD_SPLIT:
        return numerator > denominator
    if action_kind == ActionKind.REVERSE_SPLIT:
        return numerator < denominator
    return False


def _share_economic_signature(component: ActionShareComponentProjectionV1) -> str:
    return content_hash(
        {
            "recipient_security_id": component.recipient_security_id,
            "predecessor_security_id": component.predecessor_security_id,
            "ratio": component.ratio,
            "ratio_meaning": component.ratio_meaning,
            "share_basis": component.share_basis,
            "applicability": component.applicability,
        }
    )


class _SessionMapping:
    def __init__(
        self,
        classification: Literal["mapped", "indeterminate"],
        reasons: tuple[str, ...],
        *,
        session_key: SessionKeyV1 | None,
        transition: ActionSessionTransitionClaimV1 | None,
        proof_hashes: tuple[str, ...],
        record_hashes: tuple[str, ...],
    ) -> None:
        self.classification = classification
        self.reasons = reasons
        self.session_key = session_key
        self.transition = transition
        self.proof_hashes = proof_hashes
        self.record_hashes = record_hashes


type _SessionSnapshot = tuple[
    ScheduledSessionVersionV1 | None,
    RealizedSessionVersionV1 | None,
    SessionCoverageVersionV1 | None,
    tuple[str, ...],
    tuple[str, ...],
]


def _map_projection_to_session(
    query: ActionSessionQueryV1,
    context: M1dResolutionContext,
    methodology: ActionDateRoleMethodologyV1,
    projection: ActionDateProjectionV1,
) -> _SessionMapping:
    snapshots = {
        day: _session_snapshot(query, context, day)
        for day in _date_range(query.candidate_start_date, query.candidate_end_date)
    }
    proof_hashes = tuple(
        digest for snapshot in snapshots.values() for digest in snapshot[3]
    )
    record_hashes = tuple(
        digest for snapshot in snapshots.values() for digest in snapshot[4]
    )
    boundary = projection.basis_boundary
    if methodology.mapping_mode == "explicit_first_basis_date":
        try:
            basis_date = date.fromisoformat(boundary.source_time_label)
        except ValueError:
            return _indeterminate(
                "first_basis_date_not_exact_local_date", proof_hashes, record_hashes
            )
        snapshot = snapshots.get(basis_date)
        if snapshot is None:
            return _indeterminate(
                "basis_date_outside_candidate_range", proof_hashes, record_hashes
            )
        scheduled, realized, coverage, _, _ = snapshot
        if realized is not None and realized.outcome == "did_not_open":
            return _indeterminate(
                "candidate_session_did_not_open", proof_hashes, record_hashes
            )
        if (
            scheduled is None
            or scheduled.state not in {"regular", "early_close"}
            or realized is None
            or realized.outcome != "opened"
            or realized.actual_open is None
            or realized.actual_close is None
            or not _coverage_proves_schedule(coverage, scheduled)
        ):
            return _indeterminate(
                "candidate_session_not_proven_open", proof_hashes, record_hashes
            )
        key = realized.session_key
        transition = ActionSessionTransitionClaimV1(
            mapping_mode=methodology.mapping_mode,
            relationship="explicit_first_basis_date",
            basis_boundary=boundary,
            source_session_key=key,
            source_actual_open=realized.actual_open,
            source_actual_close=realized.actual_close,
            session_key=key,
            actual_open=realized.actual_open,
            actual_close=realized.actual_close,
            applied_rule="exact_date_is_actual_open_session",
        )
        return _SessionMapping(
            "mapped",
            ("exact_first_basis_session_proven",),
            session_key=key,
            transition=transition,
            proof_hashes=proof_hashes,
            record_hashes=record_hashes,
        )

    transition_at = boundary.lower_bound
    if transition_at is None:
        return _indeterminate(
            "trading_basis_transition_not_exact", proof_hashes, record_hashes
        )
    if not _source_label_matches_exact_boundary(boundary):
        return _indeterminate(
            "exact_transition_source_label_mismatch", proof_hashes, record_hashes
        )
    located = _locate_source_session(snapshots, transition_at)
    if located is None:
        return _indeterminate(
            "basis_source_session_unproved", proof_hashes, record_hashes
        )
    source_date, current = located
    scheduled, realized, coverage, _, _ = current
    if realized is not None and realized.outcome == "did_not_open":
        return _indeterminate(
            "candidate_session_did_not_open", proof_hashes, record_hashes
        )
    if (
        scheduled is None
        or scheduled.state not in {"regular", "early_close"}
        or realized is None
        or realized.outcome != "opened"
        or realized.actual_open is None
        or realized.actual_close is None
    ):
        return _indeterminate(
            "candidate_session_not_proven_open", proof_hashes, record_hashes
        )
    relationship: Literal[
        "strictly_before_open",
        "strictly_after_close",
        "exactly_at_open",
        "exactly_at_close",
    ]
    if transition_at == realized.actual_open:
        if methodology.open_endpoint_designation != "post_basis":
            return _indeterminate(
                "transition_endpoint_undesignated", proof_hashes, record_hashes
            )
        relationship = "exactly_at_open"
    elif transition_at == realized.actual_close:
        if methodology.close_endpoint_designation != "pre_basis":
            return _indeterminate(
                "transition_endpoint_undesignated", proof_hashes, record_hashes
            )
        relationship = "exactly_at_close"
    elif transition_at < realized.actual_open:
        relationship = "strictly_before_open"
    elif transition_at > realized.actual_close:
        relationship = "strictly_after_close"
    else:
        return _indeterminate(
            "intraday_basis_transition_indeterminate", proof_hashes, record_hashes
        )
    if not _coverage_proves_schedule(coverage, scheduled):
        return _indeterminate(
            (
                "intervening_session_coverage_incomplete"
                if relationship in {"strictly_after_close", "exactly_at_close"}
                else "source_session_coverage_incomplete"
            ),
            proof_hashes,
            record_hashes,
        )
    if relationship in {"strictly_before_open", "exactly_at_open"}:
        if methodology.before_open_rule != "current_proven_open_session":
            return _indeterminate(
                "before_open_rule_unproved", proof_hashes, record_hashes
            )
        transition = ActionSessionTransitionClaimV1(
            mapping_mode=methodology.mapping_mode,
            relationship=relationship,
            basis_boundary=boundary,
            source_session_key=realized.session_key,
            source_actual_open=realized.actual_open,
            source_actual_close=realized.actual_close,
            session_key=realized.session_key,
            actual_open=realized.actual_open,
            actual_close=realized.actual_close,
            applied_rule=(
                "designated_open_post_basis"
                if relationship == "exactly_at_open"
                else "before_open_current_session"
            ),
        )
        return _SessionMapping(
            "mapped",
            ("before_open_current_session_proven",),
            session_key=realized.session_key,
            transition=transition,
            proof_hashes=proof_hashes,
            record_hashes=record_hashes,
        )
    if (
        methodology.after_close_rule
        != "next_proven_open_with_complete_intervening_coverage"
    ):
        return _indeterminate("after_close_rule_unproved", proof_hashes, record_hashes)
    later = tuple(
        (day, snapshot)
        for day, snapshot in snapshots.items()
        if day > source_date
        and snapshot[1] is not None
        and snapshot[1].outcome == "opened"
        and snapshot[1].actual_open is not None
        and snapshot[1].actual_close is not None
    )
    if not later:
        return _indeterminate(
            "next_actual_open_session_unproved", proof_hashes, record_hashes
        )
    next_date, next_snapshot = min(later, key=lambda item: item[0])
    for day in _date_range(source_date + timedelta(days=1), next_date):
        day_schedule, _day_realized, day_coverage, _, _ = snapshots[day]
        if day_schedule is None or not _coverage_proves_schedule(
            day_coverage, day_schedule
        ):
            return _indeterminate(
                "intervening_session_coverage_incomplete",
                proof_hashes,
                record_hashes,
            )
        if day < next_date and day_schedule.state != "closed":
            return _indeterminate(
                "intervening_session_state_not_closed", proof_hashes, record_hashes
            )
    next_schedule, next_realized, next_coverage, _, _ = next_snapshot
    assert next_realized is not None
    assert next_realized.actual_open is not None
    assert next_realized.actual_close is not None
    if next_schedule is None or not _coverage_proves_schedule(
        next_coverage, next_schedule
    ):
        return _indeterminate(
            "intervening_session_coverage_incomplete", proof_hashes, record_hashes
        )
    transition = ActionSessionTransitionClaimV1(
        mapping_mode=methodology.mapping_mode,
        relationship=relationship,
        basis_boundary=boundary,
        source_session_key=realized.session_key,
        source_actual_open=realized.actual_open,
        source_actual_close=realized.actual_close,
        session_key=next_realized.session_key,
        actual_open=next_realized.actual_open,
        actual_close=next_realized.actual_close,
        applied_rule=(
            "designated_close_pre_basis_next_open_complete_coverage"
            if relationship == "exactly_at_close"
            else "after_close_next_open_complete_coverage"
        ),
    )
    return _SessionMapping(
        "mapped",
        ("after_close_next_open_proven",),
        session_key=next_realized.session_key,
        transition=transition,
        proof_hashes=proof_hashes,
        record_hashes=record_hashes,
    )


def _session_snapshot(
    query: ActionSessionQueryV1, context: M1dResolutionContext, local_date: date
) -> _SessionSnapshot:
    outer = query.outer_query.model_copy(update={"session_date": local_date})
    selections = tuple(
        cast(
            SelectedSessionRecordsV1,
            select_observation_records(outer, purpose, context),
        )
        for purpose in ("scheduled_session", "realized_session", "session_coverage")
    )
    schedule = _one_record(selections[0].records, ScheduledSessionVersionV1)
    realized = _one_record(selections[1].records, RealizedSessionVersionV1)
    coverage = _one_record(selections[2].records, SessionCoverageVersionV1)
    return (
        schedule,
        realized,
        coverage,
        tuple(content_hash(item.proof) for item in selections),
        tuple(content_hash(record) for item in selections for record in item.records),
    )


def _one_record[T](values: Sequence[object], model: type[T]) -> T | None:
    return values[0] if len(values) == 1 and isinstance(values[0], model) else None


def _coverage_proves_schedule(
    coverage: SessionCoverageVersionV1 | None,
    schedule: ScheduledSessionVersionV1,
) -> bool:
    return bool(
        coverage is not None
        and coverage.status == "expected_complete"
        and coverage.start_date <= schedule.session_key.local_date <= coverage.end_date
        and any(
            item.assertion_id == schedule.revision.logical_record_id
            and item.version_id == schedule.revision.record_version_id
            and item.record_hash == content_hash(schedule)
            for item in coverage.record_inventory
        )
    )


def _date_range(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset) for offset in range((end - start).days + 1)
    )


def _source_label_matches_exact_boundary(boundary: ActionBasisBoundaryV1) -> bool:
    if boundary.lower_bound is None:
        return False
    try:
        source_value = datetime.fromisoformat(
            boundary.source_time_label.replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if source_value.tzinfo is None:
        return False
    return source_value.astimezone(UTC) == boundary.lower_bound


def _locate_source_session(
    snapshots: Mapping[date, _SessionSnapshot], transition_at: datetime
) -> tuple[date, _SessionSnapshot] | None:
    matches: list[tuple[date, _SessionSnapshot]] = []
    for local_date, snapshot in snapshots.items():
        scheduled, realized, _coverage, _proofs, _records = snapshot
        if (
            scheduled is None
            or scheduled.state not in {"regular", "early_close"}
            or realized is None
            or realized.outcome != "opened"
            or realized.actual_open is None
            or realized.actual_close is None
        ):
            continue
        day_bounds = _scheduled_local_day_bounds(scheduled)
        if day_bounds is None:
            continue
        day_start, day_end = day_bounds
        if day_start <= transition_at < day_end:
            matches.append((local_date, snapshot))
    return matches[0] if len(matches) == 1 else None


def _scheduled_local_day_bounds(
    schedule: ScheduledSessionVersionV1,
) -> tuple[datetime, datetime] | None:
    open_offset = next(
        (
            item.utc_offset_seconds
            for item in schedule.historical_boundary_offsets
            if item.boundary == "open"
        ),
        None,
    )
    if open_offset is None:
        return None
    local_midnight = datetime.combine(schedule.session_key.local_date, time(), UTC)
    start = local_midnight - timedelta(seconds=open_offset)
    return start, start + timedelta(days=1)


def _indeterminate(
    reason: str, proof_hashes: tuple[str, ...], record_hashes: tuple[str, ...]
) -> _SessionMapping:
    return _SessionMapping(
        "indeterminate",
        (reason,),
        session_key=None,
        transition=None,
        proof_hashes=proof_hashes,
        record_hashes=record_hashes,
    )


def _outer_horizon(query: ActionSessionQueryV1) -> datetime:
    outer = query.outer_query
    return (
        outer.effective_cutoff if outer.kind == "decision" else outer.economic_horizon
    )
