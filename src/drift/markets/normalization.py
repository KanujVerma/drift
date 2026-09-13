"""Causal source-basis and split-normalized observation materialization."""

import sys
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from math import gcd
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from pydantic import BaseModel, ValidationError

from drift.domain.action_sessions import (
    ActionSessionPolicyV1,
    ActionSessionQueryV1,
    FirstPostActionSessionResultV1,
)
from drift.domain.economic_common import ActionKind, CashComponentV1, ShareComponentV1
from drift.domain.economic_coverage import EconomicSourceSelectionPolicyV1
from drift.domain.economic_events import (
    CancelledActionV1,
    EconomicEffectVersionV1,
    OccurredEffectV1,
    UnknownEffectV1,
)
from drift.domain.economic_queries import (
    MarketDecisionQueryV1,
    MarketOutcomeQueryV1,
    MarketSelectionQueryV1,
)
from drift.domain.economic_results import EconomicEffectProjectionV1
from drift.domain.normalization import (
    AnchorOpeningEvidenceV1,
    DerivedObservationViewV1,
    ExactRatioV1,
    FieldTransformV1,
    NormalizationDerivationV1,
    NormalizationPolicyV1,
    NormalizationQueryV1,
    NormalizationResultV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
    derived_view_output_hash,
    normalization_algorithm_hash,
)
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    ObservationOutcomeQueryV1,
    ObservationQueryV1,
    m1d_implementation_hash,
    observation_cutoff,
    observation_horizon,
)
from drift.domain.observation_usability import (
    ObservationAssessmentV1,
    ObservationReadFailureV1,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationContractV1,
)
from drift.domain.sessions import RealizedSessionVersionV1, SessionKeyV1
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityShape,
    CutoffEligibility,
)
from drift.markets.action_sessions import map_action_to_session
from drift.markets.economic_outcomes import (
    boundary_economic_value_v1,
    component_economic_value_v1,
    resolve_economic_facts,
)
from drift.markets.economic_selection import select_market_records
from drift.markets.economic_validation import economic_context_hash
from drift.markets.observation_selection import (
    SelectedObservationContractV1,
    select_observation_records,
)
from drift.markets.observation_usability import assess_observation
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
)
from drift.markets.session_binding import (
    ObservationSessionBindingResultV1,
    bind_observation_session,
)
from drift.serialization.canonical import canonical_json, content_hash

_MAX_COMPUTATIONAL_DIGITS = 4096
_REQUIRED_ACTION_KINDS = tuple(sorted(tuple(ActionKind), key=lambda item: item.value))


def compose_split_factors(
    ratios: tuple[ExactRatioV1, ...],
) -> tuple[ExactRatioV1, ExactRatioV1]:
    """Compose exact reciprocal price and share-volume split factors."""
    quantity = Fraction(1)
    for ratio in ratios:
        if int(ratio.numerator) <= 0:
            raise ValueError("split factors require strictly positive ratios")
        numerator = int(ratio.numerator)
        denominator = int(ratio.denominator)
        left_numerator = quantity.numerator
        left_denominator = quantity.denominator
        cross_left = gcd(left_numerator, denominator)
        cross_right = gcd(numerator, left_denominator)
        left_numerator //= cross_left
        denominator //= cross_left
        numerator //= cross_right
        left_denominator //= cross_right
        if (
            _integer_digits(left_numerator) + _integer_digits(numerator)
            > _MAX_COMPUTATIONAL_DIGITS
            or _integer_digits(left_denominator) + _integer_digits(denominator)
            > _MAX_COMPUTATIONAL_DIGITS
        ):
            raise ValueError("normalization computational expansion exceeds safe bound")
        quantity = Fraction(left_numerator * numerator, left_denominator * denominator)
    price = 1 / quantity
    return (
        ExactRatioV1(
            numerator=str(price.numerator), denominator=str(price.denominator)
        ),
        ExactRatioV1(
            numerator=str(quantity.numerator), denominator=str(quantity.denominator)
        ),
    )


def _integer_digits(value: int) -> int:
    return len(str(abs(value)))


def quantize_exact_ratio(
    source: Decimal, factor: ExactRatioV1, scale: int
) -> tuple[ExactRatioV1, Decimal]:
    """Apply one exact factor and quantize once with signed half-even rounding."""
    if not source.is_finite():
        raise ValueError("normalization requires a finite source decimal")
    if not 0 <= scale <= 1000:
        raise ValueError("normalization scale exceeds the computational guard")
    sign, digits, raw_exponent = source.as_tuple()
    exponent = cast(int, raw_exponent)
    expansion = (
        len(digits)
        + abs(exponent)
        + scale
        + len(factor.numerator.removeprefix("-"))
        + len(factor.denominator)
    )
    if expansion > _MAX_COMPUTATIONAL_DIGITS:
        raise ValueError("normalization computational expansion exceeds safe bound")
    coefficient = int("".join(str(digit) for digit in digits) or "0")
    if sign:
        coefficient = -coefficient
    if exponent >= 0:
        source_ratio = Fraction(coefficient * (10**exponent), 1)
    else:
        source_ratio = Fraction(coefficient, 10 ** (-exponent))
    transformed = source_ratio * Fraction(
        int(factor.numerator), int(factor.denominator)
    )
    scaled = transformed * (10**scale)
    sign_value = -1 if scaled < 0 else 1
    units, remainder = divmod(abs(scaled.numerator), scaled.denominator)
    twice = 2 * remainder
    increment = twice > scaled.denominator or (
        twice == scaled.denominator and units % 2 == 1
    )
    rounded_units = sign_value * (units + int(increment))
    absolute_digits = tuple(int(char) for char in str(abs(rounded_units)))
    quantized = Decimal((1 if rounded_units < 0 else 0, absolute_digits, -scale))
    return (
        ExactRatioV1(
            numerator=str(transformed.numerator),
            denominator=str(transformed.denominator),
        ),
        quantized,
    )


def normalize_observation(
    query: NormalizationQueryV1, context: M1dResolutionContext
) -> NormalizationResultV1:
    """Materialize one query-authorized source or split-normalized view."""
    snapshot = _snapshot_context(context)
    policy = _load_artifact(query.policy_hash, NormalizationPolicyV1, snapshot)
    if policy.mode == "source_basis":
        snapshot = replace(snapshot, economic_context=None, economic_source_policy=None)
    if query.observation.input_context_hash != m1d_context_hash(snapshot):
        raise ValueError("normalization query context mismatch")
    if policy.profile_hash != query.observation.profile_hash:
        raise ValueError("normalization policy profile mismatch")
    if policy.mode == "source_basis" and query.anchor_session is not None:
        raise ValueError("source-basis query cannot carry an anchor session")
    if policy.mode == "split_normalized" and query.anchor_session is None:
        raise ValueError("split-normalized query requires an anchor session")

    assessment = assess_observation(query.observation, snapshot)
    base_dependencies = {
        query.observation.input_context_hash,
        query.policy_hash,
        content_hash(assessment),
        normalization_algorithm_hash(),
        m1d_implementation_hash(),
    }
    if isinstance(assessment, ObservationReadFailureV1):
        return _failed_result(
            query,
            "unusable" if assessment.integrity == "corrupt" else "indeterminate",
            (f"source_{assessment.integrity}",),
            base_dependencies,
        )
    if assessment.usability != "usable" or assessment.numeric_view is None:
        return _failed_result(
            query,
            "unusable" if assessment.usability == "unusable" else "indeterminate",
            (*assessment.reasons, f"source_assessment_{assessment.usability}"),
            (*base_dependencies, *assessment.contributing_proof_hashes),
        )

    selected = select_observation_records(query.observation, "observation", snapshot)
    contract_result = select_observation_records(
        query.observation, "contract", snapshot
    )
    assert isinstance(contract_result, SelectedObservationContractV1)
    record = (
        selected.records[0]
        if len(selected.records) == 1
        and isinstance(selected.records[0], DailySourceObservationVersionV1)
        else None
    )
    if record is None or contract_result.contract is None:
        return _failed_result(
            query,
            "indeterminate",
            ("source_record_or_contract_unavailable",),
            (*base_dependencies, content_hash(selected.proof)),
        )
    contract = contract_result.contract
    binding = bind_observation_session(query.observation, snapshot)
    if binding.classification != "bound" or binding.actual_interval is None:
        return _failed_result(
            query,
            "indeterminate",
            ("source_session_binding_unavailable",),
            (*base_dependencies, content_hash(binding)),
        )
    source_session = binding.session_key
    dependencies = {
        *base_dependencies,
        *assessment.contributing_proof_hashes,
        *binding.dependency_hashes,
        content_hash(selected.proof),
        content_hash(contract_result.proof),
        content_hash(record),
        content_hash(contract),
        content_hash(binding),
    }
    artifact_hashes = {
        query.policy_hash,
        query.observation.source_selection_policy_hash,
        record.source_record_hash,
        record.contract_hash,
        contract.methodology_artifact_hash,
    }
    if policy.mode == "source_basis":
        return _materialized_result(
            query=query,
            policy=policy,
            assessment=assessment,
            record=record,
            contract=contract,
            source_session=source_session,
            target_basis=source_session,
            price_factor=ExactRatioV1(numerator="1", denominator="1"),
            share_factor=ExactRatioV1(numerator="1", denominator="1"),
            action_mappings=(),
            selected_action_hashes=(),
            action_coverage_hashes=(),
            session_proof_hashes=tuple(
                value
                for value in (
                    binding.selected_schedule_proof_hash,
                    binding.selected_realized_proof_hash,
                )
                if value is not None
            ),
            session_record_hashes=(),
            dependencies=dependencies,
            artifact_hashes=artifact_hashes,
            reasons=("source_basis_exact_unadjusted",),
        )

    validate_m1d_resolution_context(snapshot)
    anchor = cast(SessionKeyV1, query.anchor_session)
    if anchor.local_date > observation_horizon(query.observation).date():
        return _failed_result(
            query,
            "indeterminate",
            ("anchor_basis_beyond_effective_cutoff",),
            dependencies,
        )
    anchor_info = _anchor_basis(
        query.observation, source_session, binding, anchor, snapshot
    )
    if isinstance(anchor_info, str):
        return _failed_result(
            query,
            "indeterminate",
            (anchor_info,),
            dependencies,
        )
    (
        anchor_open,
        anchor_proof_hashes,
        anchor_record_hashes,
        anchor_artifact_hashes,
    ) = anchor_info
    artifact_hashes.update(anchor_artifact_hashes)
    cutoff = observation_cutoff(query.observation)
    horizon = observation_horizon(query.observation)
    if anchor_open > horizon:
        return _failed_result(
            query,
            "indeterminate",
            ("anchor_basis_beyond_effective_cutoff",),
            (*dependencies, *anchor_proof_hashes, *anchor_record_hashes),
        )
    if anchor_open > cutoff:
        return _failed_result(
            query,
            "indeterminate",
            ("anchor_basis_beyond_knowledge_cutoff",),
            (*dependencies, *anchor_proof_hashes, *anchor_record_hashes),
        )
    split = _split_lineage(
        query,
        snapshot,
        policy,
        source_session,
        anchor,
        anchor_open,
        binding.actual_interval.opened_at,
    )
    if split.failure_reason is not None:
        failed_mapping_hashes = tuple(content_hash(item) for item in split.mappings)
        return _failed_result(
            query,
            "indeterminate",
            (split.failure_reason, *split.audit_reasons),
            (
                *dependencies,
                *anchor_proof_hashes,
                *anchor_record_hashes,
                *split.coverage_hashes,
                *failed_mapping_hashes,
            ),
            selected_action_hashes=split.selected_action_hashes,
            action_mapping_hashes=failed_mapping_hashes,
        )
    dependencies.update(anchor_proof_hashes)
    dependencies.update(anchor_record_hashes)
    dependencies.update(content_hash(item) for item in split.mappings)
    for mapping in split.mappings:
        dependencies.update(mapping.dependency_hashes)
    dependencies.update(split.coverage_hashes)
    artifact_hashes.update(
        value
        for value in (
            policy.mapping_policy_hash,
            content_hash(snapshot.economic_source_policy)
            if snapshot.economic_source_policy is not None
            else None,
        )
        if value is not None
    )
    try:
        price_factor, share_factor = compose_split_factors(split.ratios)
    except ValueError as error:
        if "computational expansion" not in str(error):
            raise
        return _failed_result(
            query,
            "indeterminate",
            ("normalization_computational_expansion", *split.audit_reasons),
            dependencies,
            selected_action_hashes=split.selected_action_hashes,
            action_mapping_hashes=tuple(content_hash(item) for item in split.mappings),
        )
    try:
        return _materialized_result(
            query=query,
            policy=policy,
            assessment=assessment,
            record=record,
            contract=contract,
            source_session=source_session,
            target_basis=anchor,
            price_factor=price_factor,
            share_factor=share_factor,
            action_mappings=split.mappings,
            selected_action_hashes=split.selected_action_hashes,
            action_coverage_hashes=split.coverage_hashes,
            session_proof_hashes=tuple(
                {
                    *anchor_proof_hashes,
                    *(
                        item
                        for mapping in split.mappings
                        for item in mapping.selected_session_proof_hashes
                    ),
                }
            ),
            session_record_hashes=tuple(
                {
                    *anchor_record_hashes,
                    *(
                        item
                        for mapping in split.mappings
                        for item in mapping.selected_session_record_hashes
                    ),
                }
            ),
            dependencies=dependencies,
            artifact_hashes=artifact_hashes,
            reasons=("split_units_exact", *split.audit_reasons),
        )
    except _PositivePriceRoundedToZero:
        return _failed_result(
            query,
            "unusable",
            ("positive_price_rounded_to_zero", *split.audit_reasons),
            dependencies,
            selected_action_hashes=split.selected_action_hashes,
            action_mapping_hashes=tuple(content_hash(item) for item in split.mappings),
        )
    except ValueError as error:
        if "computational expansion" not in str(error):
            raise
        return _failed_result(
            query,
            "indeterminate",
            ("normalization_computational_expansion", *split.audit_reasons),
            dependencies,
            selected_action_hashes=split.selected_action_hashes,
            action_mapping_hashes=tuple(content_hash(item) for item in split.mappings),
        )


def verify_normalization(
    result: NormalizationResultV1, context: M1dResolutionContext
) -> None:
    """Replay and compare a complete normalization result."""
    expected = normalize_observation(result.query, context)
    if result != expected or content_hash(result) != content_hash(expected):
        raise ValueError("normalization replay mismatch")


def materialize_observation_decision(
    reference: ObservationDecisionReferenceV1,
    query: NormalizationQueryV1,
    context: M1dResolutionContext,
) -> DerivedObservationViewV1:
    """Resolve a decision-role view through full dependent replay."""
    if not isinstance(reference, ObservationDecisionReferenceV1):
        raise TypeError("decision materialization requires a decision reference")
    if not isinstance(query.observation, ObservationDecisionQueryV1):
        raise TypeError("decision materialization requires a decision query")
    return _materialize(reference, query, context)


def materialize_observation_outcome(
    reference: ObservationOutcomeReferenceV1,
    query: NormalizationQueryV1,
    context: M1dResolutionContext,
) -> DerivedObservationViewV1:
    """Resolve an outcome-role view through full dependent replay."""
    if not isinstance(reference, ObservationOutcomeReferenceV1):
        raise TypeError("outcome materialization requires an outcome reference")
    if not isinstance(query.observation, ObservationOutcomeQueryV1):
        raise TypeError("outcome materialization requires an outcome query")
    return _materialize(reference, query, context)


def _materialize(
    reference: ObservationDecisionReferenceV1 | ObservationOutcomeReferenceV1,
    query: NormalizationQueryV1,
    context: M1dResolutionContext,
) -> DerivedObservationViewV1:
    if reference.query_hash != content_hash(query):
        raise ValueError("normalization reference query mismatch")
    result = normalize_observation(query, context)
    if result.classification != "materialized" or result.view is None:
        raise ValueError("normalization reference no longer materializes")
    if result.reference != reference:
        raise ValueError("normalization reference does not match exact replay")
    return result.view


class _PositivePriceRoundedToZero(ValueError):
    pass


class _SplitLineage:
    def __init__(
        self,
        *,
        ratios: tuple[ExactRatioV1, ...] = (),
        mappings: tuple[FirstPostActionSessionResultV1, ...] = (),
        selected_action_hashes: tuple[str, ...] = (),
        coverage_hashes: tuple[str, ...] = (),
        audit_reasons: tuple[str, ...] = (),
        failure_reason: str | None = None,
    ) -> None:
        self.ratios = ratios
        self.mappings = mappings
        self.selected_action_hashes = selected_action_hashes
        self.coverage_hashes = coverage_hashes
        self.audit_reasons = audit_reasons
        self.failure_reason = failure_reason


def _snapshot_context(context: M1dResolutionContext) -> M1dResolutionContext:
    return replace(
        context,
        observation_datasets=tuple(context.observation_datasets),
        session_datasets=tuple(context.session_datasets),
        availability_policies=MappingProxyType(dict(context.availability_policies)),
        retained_evidence=MappingProxyType(dict(context.retained_evidence)),
        supporting_artifacts=MappingProxyType(dict(context.supporting_artifacts)),
    )


def _load_artifact[T: BaseModel](
    digest: str, model: type[T], context: M1dResolutionContext
) -> T:
    artifact = context.supporting_artifacts.get(digest)
    if artifact is None:
        raise ValueError("normalization policy artifact unavailable")
    try:
        parsed = model.model_validate_json(artifact.data)
    except ValidationError as error:
        raise ValueError("normalization policy artifact invalid") from error
    if (
        artifact.byte_size != len(artifact.data)
        or artifact.content_hash != digest
        or sha256(artifact.data).hexdigest() != digest
        or canonical_json(parsed) != artifact.data
        or content_hash(parsed) != digest
    ):
        raise ValueError("normalization policy artifact hash mismatch")
    return parsed


def _failed_result(
    query: NormalizationQueryV1,
    classification: Literal["unusable", "indeterminate"],
    reasons: tuple[str, ...],
    dependencies: Iterable[str],
    *,
    selected_action_hashes: tuple[str, ...] = (),
    action_mapping_hashes: tuple[str, ...] = (),
) -> NormalizationResultV1:
    return NormalizationResultV1(
        query=query,
        query_hash=content_hash(query),
        classification=classification,
        reasons=tuple(reasons),
        dependency_hashes=tuple(sorted(set(dependencies))),
        selected_action_hashes=selected_action_hashes,
        action_mapping_hashes=action_mapping_hashes,
        view=None,
        derivation=None,
        derivation_hash=None,
        reference=None,
        context_hash=query.observation.input_context_hash,
        policy_hash=query.policy_hash,
        semantic_algorithm_hash=normalization_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
    )


def _anchor_basis(
    outer: ObservationQueryV1,
    source_session: SessionKeyV1,
    source_binding: ObservationSessionBindingResultV1,
    anchor: SessionKeyV1,
    context: M1dResolutionContext,
) -> tuple[datetime, tuple[str, ...], tuple[str, ...], tuple[str, ...]] | str:
    if anchor == source_session:
        actual = source_binding.actual_interval
        assert actual is not None
        return actual.opened_at, (), (), ()
    dependent = outer.model_copy(update={"session_date": anchor.local_date})
    selected = select_observation_records(dependent, "realized_session", context)
    records = tuple(
        item for item in selected.records if isinstance(item, RealizedSessionVersionV1)
    )
    if len(records) == 1:
        record = records[0]
        if (
            record.outcome == "opened"
            and record.actual_open is not None
            and record.actual_close is not None
        ):
            return (
                record.actual_open,
                (content_hash(selected.proof),),
                (content_hash(record),),
                (),
            )
    causally_selected_hashes = {
        selection.selected_record_hash
        for selection in selected.proof.assertion_selections
        if selection.classification is CutoffEligibility.ELIGIBLE
        and selection.selected_record_hash is not None
    }
    causal_records = tuple(
        record
        for dataset in context.session_datasets
        if dataset.manifest.dataset_role.name == "realized_session"
        for record in dataset.records
        if isinstance(record, RealizedSessionVersionV1)
        and content_hash(record) in causally_selected_hashes
        and record.source_id == selected.proof.subject.source_id
        and record.session_key == anchor
    )
    if len(causal_records) != 1:
        return "anchor_basis_unproved"
    record = causal_records[0]
    if (
        record.outcome != "opened"
        or record.actual_open is not None
        or record.actual_close is not None
    ):
        return "anchor_basis_unproved"
    availability = tuple(
        evidence
        for evidence in record.revision.availability
        if evidence.channel == outer.requested_channel
        and evidence.shape is AvailabilityShape.EXACT
        and evidence.lower_bound is not None
        and evidence.lower_bound == evidence.upper_bound
        and evidence.basis is AvailabilityBasis.SOURCE_OBSERVED
        and evidence.evidence_reference is not None
        and evidence.evidence_reference.content_hash
        == record.revision.source_artifact.content_hash
    )
    if len(availability) != 1:
        return "anchor_basis_unproved"
    witness = availability[0]
    assert witness.upper_bound is not None
    matches: list[tuple[AnchorOpeningEvidenceV1, str]] = []
    for digest in record.source_evidence_hashes:
        artifact = context.supporting_artifacts.get(digest)
        if artifact is None:
            continue
        try:
            opening = AnchorOpeningEvidenceV1.model_validate_json(artifact.data)
        except ValidationError:
            continue
        if (
            canonical_json(opening) != artifact.data
            or content_hash(opening) != digest
            or sha256(artifact.data).hexdigest() != digest
            or opening.source_id != record.source_id
            or opening.logical_record_id != record.revision.logical_record_id
            or opening.record_version_id != record.revision.record_version_id
            or opening.session_key != record.session_key
            or opening.source_artifact_hash
            != record.revision.source_artifact.content_hash
            or opening.record_availability_evidence_hash != content_hash(witness)
            or opening.actual_open >= witness.upper_bound
            or witness.upper_bound > observation_cutoff(outer)
            or opening.actual_open > observation_horizon(outer)
        ):
            continue
        matches.append((opening, digest))
    if len(matches) != 1:
        return "anchor_basis_unproved"
    opening, digest = matches[0]
    return (
        opening.actual_open,
        (content_hash(selected.proof),),
        (content_hash(record),),
        (digest,),
    )


def _economic_query(
    outer: ObservationQueryV1,
    context: M1dResolutionContext,
    *,
    source_policy: EconomicSourceSelectionPolicyV1,
    history_start: datetime,
    through: datetime,
) -> MarketSelectionQueryV1:
    economic_context = context.economic_context
    assert economic_context is not None
    if isinstance(outer, ObservationDecisionQueryV1):
        return MarketDecisionQueryV1(
            schema_version="1",
            kind="decision",
            purpose="economic_facts",
            security_id=outer.security_id,
            action_kinds=_REQUIRED_ACTION_KINDS,
            history_start=history_start,
            requested_channel=outer.requested_channel,
            availability_policy_id=economic_context.availability_policy.policy_id,
            availability_policy_hash=content_hash(economic_context.availability_policy),
            source_selection_policy_hash=content_hash(source_policy),
            input_context_hash=economic_context_hash(economic_context),
            decision_time=outer.decision_time,
            knowledge_cutoff=outer.knowledge_cutoff,
            effective_cutoff=through,
        )
    return MarketOutcomeQueryV1(
        schema_version="1",
        kind="outcome",
        purpose="economic_outcome",
        security_id=outer.security_id,
        action_kinds=_REQUIRED_ACTION_KINDS,
        history_start=history_start,
        requested_channel=outer.requested_channel,
        availability_policy_id=economic_context.availability_policy.policy_id,
        availability_policy_hash=content_hash(economic_context.availability_policy),
        source_selection_policy_hash=content_hash(source_policy),
        input_context_hash=economic_context_hash(economic_context),
        economic_horizon=through,
        evidence_vintage_cutoff=outer.evidence_vintage_cutoff,
    )


def _split_lineage(
    query: NormalizationQueryV1,
    context: M1dResolutionContext,
    policy: NormalizationPolicyV1,
    source_session: SessionKeyV1,
    anchor: SessionKeyV1,
    anchor_open: datetime,
    source_open: datetime,
) -> _SplitLineage:
    economic_context = context.economic_context
    source_policy = context.economic_source_policy
    if economic_context is None or source_policy is None:
        return _SplitLineage(failure_reason="economic_context_unavailable")
    if source_policy.history_start > source_open or source_policy.through < anchor_open:
        return _SplitLineage(failure_reason="economic_history_window_mismatch")
    if set(source_policy.action_kinds) != set(_REQUIRED_ACTION_KINDS):
        return _SplitLineage(failure_reason="economic_action_class_coverage_incomplete")
    assert policy.mapping_policy_hash is not None
    _load_artifact(policy.mapping_policy_hash, ActionSessionPolicyV1, context)
    window_policy = source_policy.model_copy(
        update={"history_start": source_open, "through": anchor_open}
    )
    economic_query = _economic_query(
        query.observation,
        context,
        source_policy=window_policy,
        history_start=source_open,
        through=anchor_open,
    )
    outcome = resolve_economic_facts(economic_query, economic_context, window_policy)
    proof = select_market_records(economic_query, economic_context, window_policy)
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
        return _SplitLineage(failure_reason="economic_action_class_coverage_incomplete")
    coverage_hashes = tuple(
        sorted(
            {
                selected_hash
                for item in outcome.coverage_results
                if item.family in {"terms", "effect", "settlement"}
                for selected_hash in item.selected_coverage_hashes
            }
        )
    )
    audit_reasons = (
        ("settlement_coverage_incomplete_audit_only",)
        if any(
            item.family == "settlement" and item.status != "complete"
            for item in outcome.coverage_results
        )
        else ()
    )
    records = {
        content_hash(record): record
        for dataset in economic_context.datasets
        for record in dataset.records
    }
    projection_by_hash = {
        item.source_record_hash: item for item in outcome.effect_projections
    }
    applicability_by_hash = {
        item.source_record_hash: item for item in proof.applicability
    }
    selected_effects = tuple(
        cast(EconomicEffectVersionV1, records[item_hash])
        for item_hash in proof.revision_selected_record_hashes
        if isinstance(records.get(item_hash), EconomicEffectVersionV1)
        and item_hash in applicability_by_hash
        and applicability_by_hash[item_hash].status
        in {"before_window", "in_window", "upcoming", "indeterminate"}
    )
    groups: dict[tuple[str, str], list[EconomicEffectVersionV1]] = {}
    for effect in selected_effects:
        boundary = effect.effective_time
        if effect.occurrence.kind != "identified" or (
            effect.occurrence.native_occurrence_id is None
        ):
            if (
                boundary.upper_bound is not None and boundary.upper_bound <= source_open
            ) or (
                boundary.lower_bound is not None and boundary.lower_bound > anchor_open
            ):
                continue
            return _SplitLineage(
                failure_reason="relevant_action_occurrence_indeterminate",
                coverage_hashes=coverage_hashes,
                audit_reasons=audit_reasons,
            )
        key = (effect.source_key.source_id, effect.occurrence.native_occurrence_id)
        groups.setdefault(key, []).append(effect)
    mappings: list[FirstPostActionSessionResultV1] = []
    ratios: list[ExactRatioV1] = []
    selected_actions: list[str] = []
    associations = {
        item.source_record_hash: item
        for item in outcome.associations
        if item.association_field == "terms"
    }
    for (_source, occurrence), effects in sorted(groups.items()):
        group_kind, group_signature = _classify_occurrence_group(
            effects, projection_by_hash
        )
        if group_signature is None:
            return _SplitLineage(
                failure_reason="same_occurrence_economic_disagreement",
                coverage_hashes=coverage_hashes,
                audit_reasons=audit_reasons,
            )
        if all(
            effect.effective_time.lower_bound is not None
            and effect.effective_time.lower_bound > anchor_open
            for effect in effects
        ):
            continue
        if group_kind in {"cancelled", "cash_only"}:
            continue
        if group_kind != "split":
            if all(
                effect.effective_time.upper_bound is not None
                and effect.effective_time.upper_bound <= source_open
                for effect in effects
            ):
                continue
            return _SplitLineage(
                failure_reason="unsupported_relevant_share_basis_action",
                coverage_hashes=coverage_hashes,
                audit_reasons=audit_reasons,
            )
        representative = sorted(effects, key=content_hash)[0]
        payload = representative.payload
        assert isinstance(payload, OccurredEffectV1)
        effect_hash = content_hash(representative)
        association = associations.get(effect_hash)
        selected_terms_hash = (
            association.selected_target_hash
            if association is not None and association.status == "resolved"
            else None
        )
        mapping_query = ActionSessionQueryV1(
            outer_query=query.observation,
            source_id=representative.source_key.source_id,
            native_occurrence_id=occurrence,
            selected_terms_hash=selected_terms_hash,
            selected_effect_hash=effect_hash,
            listing_id=query.observation.listing_id,
            security_id=query.observation.security_id,
            mic=query.observation.venue.value,
            candidate_start_date=source_session.local_date,
            candidate_end_date=anchor.local_date,
            economic_history_start=source_open,
            economic_through=anchor_open,
            action_session_policy_hash=policy.mapping_policy_hash,
            economic_source_policy_hash=content_hash(source_policy),
        )
        mapped = map_action_to_session(mapping_query, context)
        if mapped.classification != "mapped" or mapped.first_post_session is None:
            return _SplitLineage(
                failure_reason="split_mapping_indeterminate",
                mappings=tuple((*mappings, mapped)),
                coverage_hashes=coverage_hashes,
                audit_reasons=audit_reasons,
            )
        if mapped.first_post_session.local_date > anchor.local_date:
            continue
        if mapped.transition_claim is None:
            return _SplitLineage(failure_reason="split_mapping_indeterminate")
        transition_bound = mapped.transition_claim.basis_boundary.upper_bound
        if (
            transition_bound is None
            or transition_bound > observation_horizon(query.observation)
            or transition_bound > observation_cutoff(query.observation)
        ):
            return _SplitLineage(failure_reason="split_basis_transition_beyond_cutoff")
        if mapped.first_post_session.local_date <= source_session.local_date:
            mappings.append(mapped)
            continue
        date_projection_hash = mapped.date_projection_hash
        assert date_projection_hash is not None
        # The mapped result is replay-bound to the exact projected component. Read
        # the ratio from the selected source effect only after that replay succeeds.
        share_components = tuple(
            component
            for component in payload.owed_components
            if isinstance(component, ShareComponentV1)
        )
        if len(share_components) != 1:
            return _SplitLineage(failure_reason="split_mapping_indeterminate")
        source_ratio = share_components[0].ratio
        ratios.append(
            ExactRatioV1(
                numerator=source_ratio.numerator,
                denominator=source_ratio.denominator,
            )
        )
        mappings.append(mapped)
        selected_actions.extend(mapped.same_occurrence_effect_hashes)
    return _SplitLineage(
        ratios=tuple(ratios),
        mappings=tuple(mappings),
        selected_action_hashes=tuple(sorted(set(selected_actions))),
        coverage_hashes=coverage_hashes,
        audit_reasons=audit_reasons,
    )


def _classify_occurrence_group(
    effects: list[EconomicEffectVersionV1],
    projections: dict[str, EconomicEffectProjectionV1],
) -> tuple[
    Literal["split", "cancelled", "cash_only", "unsupported", "indeterminate"],
    str | None,
]:
    """Classify and compare a complete selected occurrence before neutralization."""
    kinds: list[
        Literal["split", "cancelled", "cash_only", "unsupported", "indeterminate"]
    ] = []
    signatures: list[str] = []
    for effect in effects:
        payload = effect.payload
        boundary = boundary_economic_value_v1(effect.effective_time)
        if isinstance(payload, CancelledActionV1):
            kind: Literal[
                "split", "cancelled", "cash_only", "unsupported", "indeterminate"
            ] = "cancelled"
            signature_payload: object = {
                "status": "cancelled_action",
                "action_kind": payload.action_kind,
                "effective_time": boundary,
            }
        elif isinstance(payload, UnknownEffectV1) or payload is None:
            kind = "indeterminate"
            signature_payload = {
                "status": "unknown",
                "action_kind": payload.action_kind if payload is not None else None,
                "effective_time": boundary,
            }
        else:
            assert isinstance(payload, OccurredEffectV1)
            projection = projections.get(content_hash(effect))
            components = tuple(
                component_economic_value_v1(component)
                for component in payload.owed_components
            )
            if payload.action_kind in {
                ActionKind.FORWARD_SPLIT,
                ActionKind.REVERSE_SPLIT,
            }:
                kind = "split"
            elif (
                payload.owed_components
                and all(
                    isinstance(component, CashComponentV1)
                    for component in payload.owed_components
                )
                and projection is not None
                and not projection.component_gaps
            ):
                kind = "cash_only"
            else:
                kind = "unsupported"
            signature_payload = {
                "status": "occurred",
                "action_kind": payload.action_kind,
                "effective_time": boundary,
                "claim_status": payload.claim_status,
                "consideration_status": payload.consideration_status,
                "components": components,
                "component_gaps": (
                    projection.component_gaps if projection is not None else None
                ),
                "residual_kind": payload.residual.kind,
            }
        kinds.append(kind)
        signatures.append(content_hash(signature_payload))
    if len(set(kinds)) != 1 or len(set(signatures)) != 1:
        return "indeterminate", None
    return kinds[0], signatures[0]


def _materialized_result(
    *,
    query: NormalizationQueryV1,
    policy: NormalizationPolicyV1,
    assessment: ObservationAssessmentV1,
    record: DailySourceObservationVersionV1,
    contract: ObservationContractV1,
    source_session: SessionKeyV1,
    target_basis: SessionKeyV1,
    price_factor: ExactRatioV1,
    share_factor: ExactRatioV1,
    action_mappings: tuple[FirstPostActionSessionResultV1, ...],
    selected_action_hashes: tuple[str, ...],
    action_coverage_hashes: tuple[str, ...],
    session_proof_hashes: tuple[str, ...],
    session_record_hashes: tuple[str, ...],
    dependencies: set[str],
    artifact_hashes: set[str],
    reasons: tuple[str, ...],
) -> NormalizationResultV1:
    fields_by_name = {item.field_name: item for item in record.fields}
    methods = {
        (item.field_name, item.method_id): item for item in contract.field_methods
    }
    transforms: list[FieldTransformV1] = []
    for name in ("open", "high", "low", "close", "volume"):
        source_field = fields_by_name[name]
        assert source_field.value is not None
        method = methods[(name, source_field.method_id)]
        factor = share_factor if name == "volume" else price_factor
        exact = None
        quantized = None
        scale = None
        rounded_to_zero = False
        if policy.mode == "split_normalized":
            scale = (
                policy.volume_output_scale
                if name == "volume"
                else policy.price_output_scale
            )
            assert scale is not None
            exact, quantized = quantize_exact_ratio(source_field.value, factor, scale)
            rounded_to_zero = quantized == 0 and exact.numerator != "0"
            if name != "volume" and rounded_to_zero:
                raise _PositivePriceRoundedToZero
        transforms.append(
            FieldTransformV1(
                field_name=name,
                method_id=method.method_id,
                meaning="share_volume" if name == "volume" else "price",
                source_value=source_field.value,
                exact_factor=factor,
                exact_transformed_value=exact,
                quantized_value=quantized,
                output_scale=scale,
                rounded_to_zero=rounded_to_zero,
            )
        )
    view_values = {
        "schema_version": "1",
        "role": query.observation.kind,
        "query": query,
        "query_hash": content_hash(query),
        "source_session": source_session,
        "listing_id": query.observation.listing_id,
        "security_id": query.observation.security_id,
        "basis_mode": policy.mode,
        "anchor_session": query.anchor_session,
        "fields": tuple(sorted(transforms, key=lambda item: item.field_name)),
        "usability_hash": content_hash(assessment),
        "output_hash": "0" * 64,
        "derivation_hash": "0" * 64,
    }
    provisional_view = DerivedObservationViewV1.model_construct(
        _fields_set=None, **cast(Any, view_values)
    )
    output_hash = derived_view_output_hash(provisional_view)
    action_mapping_hashes = tuple(content_hash(item) for item in action_mappings)
    derivation = NormalizationDerivationV1(
        query=query,
        query_hash=content_hash(query),
        role=query.observation.kind,
        source_assessment_hash=content_hash(assessment),
        source_selection_proof_hash=assessment.observation_selection_proof_hash,
        source_binding_hash=assessment.session_binding_hash,
        normalization_policy_hash=query.policy_hash,
        mapping_policy_hash=policy.mapping_policy_hash,
        action_mapping_hashes=action_mapping_hashes,
        selected_action_hashes=selected_action_hashes,
        action_coverage_hashes=action_coverage_hashes,
        session_proof_hashes=session_proof_hashes,
        session_record_hashes=session_record_hashes,
        artifact_hashes=tuple(artifact_hashes),
        dependency_hashes=tuple(dependencies),
        target_basis=target_basis,
        price_factor=price_factor,
        share_volume_factor=share_factor,
        output_hash=output_hash,
        semantic_algorithm_hash=normalization_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
        python_identity=(
            f"{sys.implementation.name}-{sys.version_info.major}."
            f"{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        lockfile_hash=_runtime_lockfile_hash(),
    )
    derivation_hash = content_hash(derivation)
    view = DerivedObservationViewV1.model_validate(
        {**view_values, "output_hash": output_hash, "derivation_hash": derivation_hash}
    )
    reference: ObservationDecisionReferenceV1 | ObservationOutcomeReferenceV1
    reference_values = {
        "query_hash": content_hash(query),
        "view_hash": content_hash(view),
        "derivation_hash": derivation_hash,
        "context_hash": query.observation.input_context_hash,
    }
    if isinstance(query.observation, ObservationDecisionQueryV1):
        reference = ObservationDecisionReferenceV1(
            query_hash=reference_values["query_hash"],
            view_hash=reference_values["view_hash"],
            derivation_hash=reference_values["derivation_hash"],
            context_hash=reference_values["context_hash"],
        )
    else:
        reference = ObservationOutcomeReferenceV1(
            query_hash=reference_values["query_hash"],
            view_hash=reference_values["view_hash"],
            derivation_hash=reference_values["derivation_hash"],
            context_hash=reference_values["context_hash"],
        )
    return NormalizationResultV1(
        query=query,
        query_hash=content_hash(query),
        classification="materialized",
        reasons=reasons,
        dependency_hashes=tuple(dependencies),
        selected_action_hashes=selected_action_hashes,
        action_mapping_hashes=action_mapping_hashes,
        view=view,
        derivation=derivation,
        derivation_hash=derivation_hash,
        reference=reference,
        context_hash=query.observation.input_context_hash,
        policy_hash=query.policy_hash,
        semantic_algorithm_hash=normalization_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
    )


def _runtime_lockfile_hash() -> str:
    """Hash the exact local dependency lock, or the explicit absent state."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "uv.lock"
        if candidate.is_file():
            return sha256(candidate.read_bytes()).hexdigest()
    return content_hash({"schema_version": "1", "lockfile": "not_retained"})
