"""Finite causal selection for immutable M1d source records."""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Self, cast

from pydantic import ValidationError, model_validator

from drift.datasets.assertions import select_assertion_version
from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import (
    AssertionSelectionResultV1,
    AssertionVersionProjectionV1,
    BoundaryShape,
    TemporalBoundaryClaimV1,
)
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.observation_query import (
    M1dSelectedRecordsV1,
    M1dSelectionProofV1,
    M1dSelectionPurpose,
    ObservationQueryV1,
    ObservationSourceBindingV1,
    ObservationSourceSelectionPolicyV1,
    ObservationSubjectV1,
    SessionSubjectV1,
    m1d_implementation_hash,
    observation_cutoff,
    observation_horizon,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationContractV1,
    ObservationCoverageVersionV1,
    ObservationInputRecordV1,
)
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    SelectedSessionRecordsV1,
    SessionCoverageVersionV1,
    SessionInputRecordV1,
    SessionKeyV1,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
    CutoffEligibilityResultV1,
    evaluate_availability,
)
from drift.markets.observation_validation import (
    M1dDatasetInput,
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
)
from drift.serialization.canonical import canonical_json, content_hash


class SelectedObservationContractV1(FrozenModel):
    """Query- and policy-bound selected observation contract artifact."""

    schema_version: Literal["1"] = "1"
    query: ObservationQueryV1
    purpose: Literal["contract"]
    contract: ObservationContractV1 | None
    proof: M1dSelectionProofV1

    @property
    def records(self) -> tuple[ObservationContractV1, ...]:
        """Expose the selected contract through the shared audit facade shape."""
        return (self.contract,) if self.contract is not None else ()

    @property
    def dataset_role(self) -> Literal["contract"]:
        """Expose the supporting-artifact role without calling it a dataset."""
        return "contract"

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.proof.query != self.query or self.proof.purpose != self.purpose:
            raise ValueError("selected contract must match its query and proof")
        selected_hashes = (
            (content_hash(self.contract),) if self.contract is not None else ()
        )
        if selected_hashes != self.proof.selected_hashes:
            raise ValueError("selected contract hash must match proof")
        if self.contract is not None and (
            self.contract.source_id != self.query.source_id
            or content_hash(self.contract) != self.query.contract_hash
            or self.query.venue.value not in self.contract.market_venues
        ):
            raise ValueError("selected contract subject must match query")
        return self


type SelectedM1dRecordsV1 = (
    M1dSelectedRecordsV1 | SelectedSessionRecordsV1 | SelectedObservationContractV1
)
type M1dAnyRecord = ObservationInputRecordV1 | SessionInputRecordV1
type M1dAnyDataset = (
    M1dDatasetInput[ObservationInputRecordV1] | M1dDatasetInput[SessionInputRecordV1]
)
type RecordPurpose = Literal[
    "observation",
    "observation_coverage",
    "scheduled_session",
    "realized_session",
    "session_coverage",
]
type RecordRole = Literal[
    "source_observation",
    "observation_coverage",
    "scheduled_session",
    "realized_session",
    "session_coverage",
]


class RealizedSessionCompletionEvidenceV1(FrozenModel):
    """Exact completion boundary for a realized report without actual close."""

    schema_version: Literal["1"] = "1"
    kind: Literal["realized_session_completion"]
    source_id: NonBlankStr
    session_key: SessionKeyV1
    outcome: Literal["opened", "did_not_open", "unknown"]
    logical_record_id: UUID7
    record_version_id: UUID7
    source_artifact_hash: SHA256Hash
    record_availability_evidence_hash: SHA256Hash
    completion_time: TemporalBoundaryClaimV1

    @model_validator(mode="after")
    def require_exact_completion(self) -> Self:
        if self.completion_time.shape is not BoundaryShape.EXACT:
            raise ValueError("realized completion evidence must be exact")
        return self


_PURPOSE_ROLE: dict[RecordPurpose, RecordRole] = {
    "observation": "source_observation",
    "observation_coverage": "observation_coverage",
    "scheduled_session": "scheduled_session",
    "realized_session": "realized_session",
    "session_coverage": "session_coverage",
}
_SELECTION_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "finite_m1a_revision_selection_v1",
    "chain_order": "before_subject_filter",
    "cutoff": "decision_k_or_outcome_v",
    "observation_completion": "at_or_after_interval_and_by_min_horizon_cutoff",
    "realized_completion": "exact_actual_close_or_record_bound_completion_evidence",
    "realized_intrinsic_chronology": "source_availability_not_before_completion",
}


def observation_selection_algorithm_hash() -> str:
    """Return the semantic identity of M1d finite source selection."""
    return content_hash(_SELECTION_ALGORITHM_V1)


def select_observation_records(
    query: ObservationQueryV1,
    purpose: str,
    context: M1dResolutionContext,
) -> SelectedM1dRecordsV1:
    """Select one exact observation or session source record at finite K or V."""
    if purpose not in {*_PURPOSE_ROLE, "contract"}:
        raise ValueError("record selection purpose is not a source-record family")
    validate_m1d_resolution_context(context)
    _require_query_context(query, context)
    availability_policy = _availability_policy(query, context)
    source_policy = _load_source_policy(query, context)
    if purpose == "contract":
        binding = _unique_binding(source_policy, query, "source_observation")
        return _select_contract(query, context, availability_policy, binding)
    validated_purpose = cast(RecordPurpose, purpose)
    role = _PURPOSE_ROLE[validated_purpose]
    binding = _unique_binding(source_policy, query, role)
    selected, _dataset = _select_bound_records(
        query,
        context,
        availability_policy,
        binding,
        validated_purpose,
        role,
        semantic_algorithm_hash=observation_selection_algorithm_hash(),
    )
    return selected


def verify_observation_selection(
    selected: SelectedM1dRecordsV1, context: M1dResolutionContext
) -> None:
    """Replay selection and compare the complete selected value and proof."""
    replayed = select_observation_records(selected.query, selected.purpose, context)
    if replayed != selected:
        raise ValueError("observation selection replay mismatch")


def _require_query_context(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> None:
    if query.input_context_hash != m1d_context_hash(context):
        raise ValueError("observation query context hash mismatch")


def _availability_policy(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> AvailabilityPolicyV1:
    policy = context.availability_policies.get(query.availability_policy_hash)
    if (
        policy is None
        or policy.policy_id != query.availability_policy_id
        or content_hash(policy) != query.availability_policy_hash
    ):
        raise ValueError("observation availability policy binding mismatch")
    return policy


def _load_source_policy(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ObservationSourceSelectionPolicyV1:
    artifact = context.supporting_artifacts.get(query.source_selection_policy_hash)
    if artifact is None:
        raise ValueError("source selection policy bytes unavailable")
    try:
        policy = ObservationSourceSelectionPolicyV1.model_validate_json(artifact.data)
    except ValidationError as error:
        raise ValueError("source selection policy bytes invalid") from error
    if (
        canonical_json(policy) != artifact.data
        or content_hash(policy) != query.source_selection_policy_hash
    ):
        raise ValueError("source selection policy hash mismatch")
    return policy


def _unique_binding(
    policy: ObservationSourceSelectionPolicyV1,
    query: ObservationQueryV1,
    role: str,
) -> ObservationSourceBindingV1 | None:
    matches = tuple(
        item
        for item in policy.bindings
        if item.dataset_role == role
        and item.venue is query.venue
        and item.listing_id == query.listing_id
        and item.start_date <= query.session_date <= item.end_date
        and (
            role not in {"source_observation", "observation_coverage"}
            or (
                item.source_id == query.source_id
                and item.contract_hash == query.contract_hash
            )
        )
    )
    material_keys = {
        (
            item.dataset_role,
            item.source_id,
            item.contract_hash,
            item.venue,
            item.listing_id,
            item.manifest_hashes,
            item.methodology_hashes,
        )
        for item in matches
    }
    return matches[0] if matches and len(material_keys) == 1 else None


def _select_contract(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    availability_policy: AvailabilityPolicyV1,
    binding: ObservationSourceBindingV1 | None,
) -> SelectedObservationContractV1:
    matching_datasets = _matching_datasets(context, binding, "source_observation")
    inventory_complete = (
        binding is not None
        and tuple(sorted(manifest_hash(item.manifest) for item in matching_datasets))
        == binding.manifest_hashes
    )
    artifact = context.supporting_artifacts.get(query.contract_hash)
    contract = None
    decision: CutoffEligibilityResultV1 | None = None
    if artifact is not None and binding is not None and inventory_complete:
        try:
            candidate = ObservationContractV1.model_validate_json(artifact.data)
        except ValidationError:
            candidate = None
        if (
            candidate is not None
            and canonical_json(candidate) == artifact.data
            and content_hash(candidate) == query.contract_hash
            and candidate.source_id == query.source_id == binding.source_id
            and binding.contract_hash == query.contract_hash
            and query.venue.value in candidate.market_venues
            and binding.methodology_hashes == (candidate.methodology_artifact_hash,)
        ):
            evidence = _channel_evidence(candidate.availability, query)
            if evidence is not None:
                decision = evaluate_availability(
                    evidence,
                    query.requested_channel,
                    availability_policy,
                    observation_cutoff(query),
                    context.retained_evidence,
                )
                if decision.classification is CutoffEligibility.ELIGIBLE:
                    contract = candidate
    proof = M1dSelectionProofV1(
        query=query,
        query_hash=content_hash(query),
        purpose="contract",
        context_hash=query.input_context_hash,
        subject=ObservationSubjectV1(
            listing_id=query.listing_id,
            security_id=query.security_id,
            venue=query.venue,
            session_date=query.session_date,
            source_id=query.source_id,
            contract_hash=query.contract_hash,
        ),
        considered_version_hashes=((query.contract_hash,) if artifact else ()),
        selected_hashes=((query.contract_hash,) if contract is not None else ()),
        assertion_selections=(),
        availability_decisions=((decision,) if decision is not None else ()),
        semantic_algorithm_hash=observation_selection_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
        classification="selected" if contract is not None else "indeterminate",
    )
    return SelectedObservationContractV1(
        query=query,
        purpose="contract",
        contract=contract,
        proof=proof,
    )


def _select_bound_records(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    availability_policy: AvailabilityPolicyV1,
    binding: ObservationSourceBindingV1 | None,
    purpose: RecordPurpose,
    role: RecordRole,
    *,
    semantic_algorithm_hash: str,
) -> tuple[SelectedM1dRecordsV1, M1dAnyDataset | None]:
    matching_datasets = _matching_datasets(context, binding, role)
    inventory_complete = (
        binding is not None
        and tuple(sorted(manifest_hash(item.manifest) for item in matching_datasets))
        == binding.manifest_hashes
    )
    dataset = (
        matching_datasets[0]
        if len(matching_datasets) == 1 and inventory_complete
        else None
    )
    candidates = tuple(dataset.records) if dataset is not None else ()
    selections = _select_chains(candidates, query, availability_policy, context)
    selected_by_chain = {
        item.selected_record_hash
        for item in selections
        if item.classification is CutoffEligibility.ELIGIBLE
        and item.selected_record_hash is not None
    }
    causally_selected = tuple(
        item for item in candidates if content_hash(item) in selected_by_chain
    )
    subject_selected = tuple(
        item
        for item in causally_selected
        if binding is not None and _matches_subject(item, query, binding, role)
    )
    temporally_selected = tuple(
        item for item in subject_selected if _temporal_gate(item, query, context, role)
    )
    contract_decision, contract_ready = _contract_gate(
        query, context, availability_policy, binding, role
    )
    if not contract_ready:
        temporally_selected = ()
    unresolved = (
        binding is None
        or len(matching_datasets) != 1
        or not inventory_complete
        or any(
            item.classification is CutoffEligibility.INDETERMINATE
            for item in selections
        )
        or subject_selected != temporally_selected
        or len(temporally_selected) > 1
        or not contract_ready
    )
    classification: Literal["selected", "absent", "indeterminate"] = (
        "selected"
        if len(temporally_selected) == 1
        else "indeterminate"
        if unresolved
        else "absent"
    )
    records = temporally_selected if classification == "selected" else ()
    availability_decisions = _availability_decisions(
        candidates, query, availability_policy, context
    )
    if contract_decision is not None:
        availability_decisions = _dedupe_decisions(
            (*availability_decisions, contract_decision)
        )
    subject: ObservationSubjectV1 | SessionSubjectV1
    if role in {"source_observation", "observation_coverage"}:
        subject = ObservationSubjectV1(
            listing_id=query.listing_id,
            security_id=query.security_id,
            venue=query.venue,
            session_date=query.session_date,
            source_id=query.source_id,
            contract_hash=query.contract_hash,
        )
    else:
        subject = SessionSubjectV1(
            source_id=binding.source_id if binding is not None else query.source_id,
            mic=query.venue.value,
            session_date=query.session_date,
            session_scope="regular",
        )
    proof = M1dSelectionProofV1(
        query=query,
        query_hash=content_hash(query),
        purpose=cast(M1dSelectionPurpose, purpose),
        context_hash=query.input_context_hash,
        subject=subject,
        considered_version_hashes=tuple(content_hash(item) for item in candidates),
        selected_hashes=tuple(content_hash(item) for item in records),
        assertion_selections=selections,
        availability_decisions=availability_decisions,
        semantic_algorithm_hash=semantic_algorithm_hash,
        implementation_hash=m1d_implementation_hash(),
        classification=classification,
    )
    if role in {"source_observation", "observation_coverage"}:
        result: SelectedM1dRecordsV1 = M1dSelectedRecordsV1(
            query=query,
            purpose=cast(M1dSelectionPurpose, purpose),
            dataset_role=role,
            records=cast(tuple[ObservationInputRecordV1, ...], records),
            proof=proof,
        )
    else:
        result = SelectedSessionRecordsV1(
            query=query,
            purpose=cast(M1dSelectionPurpose, purpose),
            dataset_role=cast(
                Literal["scheduled_session", "realized_session", "session_coverage"],
                role,
            ),
            records=cast(tuple[SessionInputRecordV1, ...], records),
            proof=proof,
        )
    return result, dataset


def _matching_datasets(
    context: M1dResolutionContext,
    binding: ObservationSourceBindingV1 | None,
    role: RecordRole,
) -> tuple[M1dAnyDataset, ...]:
    if binding is None:
        return ()
    datasets: Sequence[M1dAnyDataset]
    if role in {"source_observation", "observation_coverage"}:
        datasets = context.observation_datasets
    else:
        datasets = context.session_datasets
    return tuple(
        item
        for item in datasets
        if item.manifest.dataset_role.name == role
        and item.manifest.source.source_id == binding.source_id
        and manifest_hash(item.manifest) in binding.manifest_hashes
    )


def _select_chains(
    records: Sequence[M1dAnyRecord],
    query: ObservationQueryV1,
    availability_policy: AvailabilityPolicyV1,
    context: M1dResolutionContext,
) -> tuple[AssertionSelectionResultV1, ...]:
    by_logical: dict[object, list[M1dAnyRecord]] = {}
    for record in records:
        by_logical.setdefault(record.revision.logical_record_id, []).append(record)
    return tuple(
        select_assertion_version(
            tuple(
                AssertionVersionProjectionV1(
                    revision=item.revision, record_hash=content_hash(item)
                )
                for item in versions
            ),
            query.requested_channel,
            availability_policy,
            observation_cutoff(query),
            context.retained_evidence,
        )
        for versions in by_logical.values()
    )


def _availability_decisions(
    records: Sequence[M1dAnyRecord],
    query: ObservationQueryV1,
    availability_policy: AvailabilityPolicyV1,
    context: M1dResolutionContext,
) -> tuple[CutoffEligibilityResultV1, ...]:
    decisions: list[CutoffEligibilityResultV1] = []
    for record in records:
        evidence = _channel_evidence(record.revision.availability, query)
        if evidence is None:
            continue
        decisions.append(
            evaluate_availability(
                evidence,
                query.requested_channel,
                availability_policy,
                observation_cutoff(query),
                context.retained_evidence,
            )
        )
    return _dedupe_decisions(decisions)


def _dedupe_decisions(
    decisions: Sequence[CutoffEligibilityResultV1],
) -> tuple[CutoffEligibilityResultV1, ...]:
    unique = {content_hash(item): item for item in decisions}
    return tuple(unique.values())


def _channel_evidence(
    evidence: Sequence[AvailabilityEvidenceV1], query: ObservationQueryV1
) -> AvailabilityEvidenceV1 | None:
    return next(
        (item for item in evidence if item.channel == query.requested_channel), None
    )


def _matches_subject(
    record: M1dAnyRecord,
    query: ObservationQueryV1,
    binding: ObservationSourceBindingV1,
    role: RecordRole,
) -> bool:
    if isinstance(record, DailySourceObservationVersionV1):
        return (
            role == "source_observation"
            and record.source_key.source_id == query.source_id == binding.source_id
            and record.contract_hash == query.contract_hash == binding.contract_hash
            and record.listing_id == query.listing_id
            and record.security_id == query.security_id
            and record.venue is query.venue
            and record.session_date == query.session_date
        )
    if isinstance(record, ObservationCoverageVersionV1):
        return (
            role == "observation_coverage"
            and record.source_id == query.source_id == binding.source_id
            and record.contract_hash == query.contract_hash == binding.contract_hash
            and record.listing_id == query.listing_id
            and record.security_id == query.security_id
            and record.venue is query.venue
            and record.start_date <= query.session_date <= record.end_date
            and record.methodology_artifact_hash in binding.methodology_hashes
        )
    if isinstance(record, SessionCoverageVersionV1):
        return (
            role == "session_coverage"
            and record.source_id == binding.source_id
            and record.mic == query.venue.value
            and record.session_scope == "regular"
            and record.start_date <= query.session_date <= record.end_date
            and record.methodology_hash in binding.methodology_hashes
        )
    if isinstance(record, ScheduledSessionVersionV1):
        return (
            role == "scheduled_session"
            and record.source_id == binding.source_id
            and record.session_key.mic == query.venue.value
            and record.session_key.session_scope == "regular"
            and record.session_key.local_date == query.session_date
            and record.source_methodology_hash in binding.methodology_hashes
        )
    return (
        role == "realized_session"
        and record.source_id == binding.source_id
        and record.session_key.mic == query.venue.value
        and record.session_key.session_scope == "regular"
        and record.session_key.local_date == query.session_date
        and set(record.methodology_hashes).issubset(binding.methodology_hashes)
    )


def _temporal_gate(
    record: M1dAnyRecord,
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    role: RecordRole,
) -> bool:
    if isinstance(record, DailySourceObservationVersionV1):
        end = record.claimed_interval.end
        completion = record.completion_time
        if (
            end is None
            or end.upper_bound is None
            or completion.lower_bound is None
            or completion.upper_bound is None
        ):
            return False
        limit = min(observation_cutoff(query), observation_horizon(query))
        return (
            completion.lower_bound >= end.upper_bound
            and completion.upper_bound <= limit
        )
    if role == "realized_session" and isinstance(record, RealizedSessionVersionV1):
        limit = min(observation_cutoff(query), observation_horizon(query))
        if record.outcome == "opened" and record.actual_close is not None:
            return record.actual_close <= limit
        realized_completion = _realized_completion_time(record, context, query)
        return realized_completion is not None and realized_completion <= limit
    return True


def _realized_completion_time(
    record: RealizedSessionVersionV1,
    context: M1dResolutionContext,
    query: ObservationQueryV1,
) -> datetime | None:
    availability = next(
        (
            item
            for item in record.revision.availability
            if item.channel == query.requested_channel
        ),
        None,
    )
    if (
        availability is None
        or availability.basis is not AvailabilityBasis.SOURCE_OBSERVED
        or availability.evidence_reference is None
        or availability.lower_bound is None
        or availability.upper_bound is None
    ):
        return None
    matches: list[datetime] = []
    for digest in record.source_evidence_hashes:
        artifact = context.supporting_artifacts.get(digest)
        if artifact is None:
            continue
        try:
            evidence = RealizedSessionCompletionEvidenceV1.model_validate_json(
                artifact.data
            )
        except ValidationError:
            continue
        if (
            canonical_json(evidence) != artifact.data
            or content_hash(evidence) != digest
            or evidence.source_id != record.source_id
            or evidence.session_key != record.session_key
            or evidence.outcome != record.outcome
            or evidence.logical_record_id != record.revision.logical_record_id
            or evidence.record_version_id != record.revision.record_version_id
            or evidence.source_artifact_hash
            != record.revision.source_artifact.content_hash
            or evidence.record_availability_evidence_hash != content_hash(availability)
            or availability.evidence_reference.content_hash
            != evidence.source_artifact_hash
            or evidence.completion_time.upper_bound is None
            or availability.lower_bound < evidence.completion_time.upper_bound
            or availability.upper_bound < evidence.completion_time.upper_bound
        ):
            continue
        matches.append(evidence.completion_time.upper_bound)
    return matches[0] if len(matches) == 1 else None


def _contract_gate(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    availability_policy: AvailabilityPolicyV1,
    binding: ObservationSourceBindingV1 | None,
    role: RecordRole,
) -> tuple[CutoffEligibilityResultV1 | None, bool]:
    if role not in {"source_observation", "observation_coverage"}:
        return None, True
    artifact = context.supporting_artifacts.get(query.contract_hash)
    if artifact is None or binding is None:
        return None, False
    try:
        contract = ObservationContractV1.model_validate_json(artifact.data)
    except ValidationError:
        return None, False
    if (
        canonical_json(contract) != artifact.data
        or content_hash(contract) != query.contract_hash
        or contract.source_id != query.source_id
        or query.venue.value not in contract.market_venues
        or binding.methodology_hashes != (contract.methodology_artifact_hash,)
    ):
        return None, False
    evidence = _channel_evidence(contract.availability, query)
    if evidence is None:
        return None, False
    decision = evaluate_availability(
        evidence,
        query.requested_channel,
        availability_policy,
        observation_cutoff(query),
        context.retained_evidence,
    )
    return decision, decision.classification is CutoffEligibility.ELIGIBLE
