"""Finite source selection and pinned explicit-row schedule reconstruction."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from drift.datasets.assertions import select_assertion_version
from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import AssertionVersionProjectionV1
from drift.domain.observation_query import (
    M1dSelectionProofV1,
    ObservationQueryV1,
    ObservationSourceBindingV1,
    ObservationSourceSelectionPolicyV1,
    SessionSubjectV1,
    m1d_implementation_hash,
    observation_cutoff,
)
from drift.domain.sessions import (
    GeneratedSessionRowV1,
    HistoricalBoundaryOffsetV1,
    HistoricalTimezoneMethodologyV1,
    ScheduleArtifactV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionCoverageVersionV1,
    SessionInputRecordV1,
    SessionOutputV1,
    TimezoneInputV1,
    canonical_session_encoding_contract_hash,
)
from drift.domain.sessions import (
    schedule_generation_algorithm_hash as _schedule_generation_algorithm_hash,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    CutoffEligibility,
    CutoffEligibilityResultV1,
    SourcePrecision,
    evaluate_availability,
)
from drift.markets.observation_validation import (
    M1dDatasetInput,
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
)
from drift.serialization.canonical import canonical_json, content_hash


def schedule_generation_algorithm_hash() -> str:
    """Return the semantic identity of the only supported generator."""
    return _schedule_generation_algorithm_hash()


def generate_schedule(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    policy: ScheduleGenerationPolicyV1,
) -> ScheduleArtifactV1:
    """Generate one explicit session row from independently authorized inputs."""
    return _generate_schedule(query, context, policy, datetime.now(UTC))


def verify_schedule(
    artifact: ScheduleArtifactV1, context: M1dResolutionContext
) -> None:
    """Replay a generated artifact from its retained query, policy, and context."""
    replayed = _generate_schedule(
        artifact.query, context, artifact.generation_policy, artifact.generated_at
    )
    if replayed != artifact:
        raise ValueError("schedule artifact replay mismatch")


def _generate_schedule(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    policy: ScheduleGenerationPolicyV1,
    generated_at: datetime,
) -> ScheduleArtifactV1:
    validate_m1d_resolution_context(context)
    if query.input_context_hash != m1d_context_hash(context):
        raise ValueError("schedule query context hash mismatch")
    if (
        policy.semantic_algorithm_hash != schedule_generation_algorithm_hash()
        or policy.canonical_encoding_contract_hash
        != canonical_session_encoding_contract_hash()
    ):
        raise ValueError("schedule generation policy identity mismatch")
    if policy.implementation_hash != m1d_implementation_hash():
        raise ValueError("schedule implementation identity mismatch")
    if any(
        digest not in context.supporting_artifacts
        for digest in (
            policy.producer_source_hash,
            policy.producer_package_hash,
            policy.lockfile_hash,
        )
    ):
        raise ValueError("reconstruction lineage artifact unavailable")
    availability_policy = context.availability_policies.get(
        query.availability_policy_hash
    )
    if (
        availability_policy is None
        or availability_policy.policy_id != query.availability_policy_id
        or content_hash(availability_policy) != query.availability_policy_hash
    ):
        raise ValueError("schedule availability policy binding mismatch")
    source_policy = _load_source_policy(query, context)
    scheduled_binding, scheduled_reason = _unique_binding(
        source_policy, query, "scheduled_session"
    )
    coverage_binding, coverage_reason = _unique_binding(
        source_policy, query, "session_coverage"
    )
    if scheduled_binding is None or coverage_binding is None:
        reasons = tuple(
            sorted(
                {
                    reason
                    for reason in (scheduled_reason, coverage_reason)
                    if reason is not None
                }
            )
        )
        return _artifact(
            query,
            policy,
            generated_at,
            timezone_bytes_hash="0" * 64,
            rows=(),
            source_proof=None,
            coverage_proof=None,
            authority_decisions=(),
            reconstruction_hashes=(policy.timezone_input_hash,),
            classification="indeterminate",
            reasons=reasons or ("session_source_binding_missing",),
        )
    selected_source, source_proof, source_dataset = _select_record(
        query, context, availability_policy, scheduled_binding
    )
    selected_coverage, coverage_proof, coverage_dataset = _select_record(
        query, context, availability_policy, coverage_binding
    )
    if not isinstance(selected_source, ScheduledSessionVersionV1):
        return _artifact(
            query,
            policy,
            generated_at,
            timezone_bytes_hash="0" * 64,
            rows=(),
            source_proof=source_proof,
            coverage_proof=coverage_proof,
            authority_decisions=(),
            reconstruction_hashes=(policy.timezone_input_hash,),
            classification="indeterminate",
            reasons=("scheduled_session_not_selected",),
        )
    if not isinstance(selected_coverage, SessionCoverageVersionV1):
        return _artifact(
            query,
            policy,
            generated_at,
            timezone_bytes_hash="0" * 64,
            rows=(),
            source_proof=source_proof,
            coverage_proof=coverage_proof,
            authority_decisions=(),
            reconstruction_hashes=(policy.timezone_input_hash,),
            classification="indeterminate",
            reasons=("session_coverage_not_selected",),
        )
    assert source_dataset is not None and coverage_dataset is not None
    inventory_reason = _coverage_reason(
        selected_coverage, source_dataset, query.session_date
    )
    if inventory_reason is not None:
        return _artifact(
            query,
            policy,
            generated_at,
            timezone_bytes_hash="0" * 64,
            rows=(),
            source_proof=source_proof,
            coverage_proof=coverage_proof,
            authority_decisions=(),
            reconstruction_hashes=(policy.timezone_input_hash,),
            classification="indeterminate",
            reasons=(inventory_reason,),
        )
    timezone_input, timezone_bytes = _load_timezone_input(policy, context)
    reconstruction_hashes = tuple(
        sorted(
            {
                policy.timezone_input_hash,
                timezone_input.artifact_hash,
                policy.producer_source_hash,
                policy.producer_package_hash,
                policy.implementation_hash,
                policy.lockfile_hash,
            }
        )
    )
    output, authority_decisions, reasons = _reconstruct_output(
        selected_source, timezone_input, timezone_bytes, query, context
    )
    referenced_methods = tuple(
        sorted(
            {
                item.methodology_encoding_hash
                for item in selected_source.historical_boundary_offsets
                if item.methodology_encoding_hash is not None
            }
        )
    )
    if policy.historical_timezone_methodology_encoding_hashes != referenced_methods:
        output = output.model_copy(
            update={
                "utc_open": None,
                "utc_close": None,
                "interpretation_status": "indeterminate",
            }
        )
        reasons = (*reasons, "generation_policy_methodology_set_mismatch")
    reasons = tuple(sorted(set(reasons)))
    classification: Literal["generated", "indeterminate", "conflict"] = (
        "conflict"
        if output.interpretation_status == "conflict"
        else "indeterminate"
        if output.interpretation_status == "indeterminate"
        else "generated"
    )
    row = GeneratedSessionRowV1(
        output=output,
        source_version_hash=content_hash(selected_source),
        generation_policy_hash=content_hash(policy),
    )
    return _artifact(
        query,
        policy,
        generated_at,
        timezone_bytes_hash=timezone_input.tzif_sha256,
        rows=(row,),
        source_proof=source_proof,
        coverage_proof=coverage_proof,
        authority_decisions=authority_decisions,
        reconstruction_hashes=reconstruction_hashes,
        classification=classification,
        reasons=reasons or ("authorized_explicit_session",),
    )


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
) -> tuple[ObservationSourceBindingV1 | None, str | None]:
    matches = tuple(
        item
        for item in policy.bindings
        if item.dataset_role == role
        and item.venue is query.venue
        and item.listing_id == query.listing_id
        and item.start_date <= query.session_date <= item.end_date
    )
    if len(matches) == 1:
        return matches[0], None
    return None, (
        "session_source_binding_missing"
        if not matches
        else "competing_session_source_bindings"
    )


def _select_record(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    availability_policy: AvailabilityPolicyV1,
    binding: ObservationSourceBindingV1,
) -> tuple[
    ScheduledSessionVersionV1 | SessionCoverageVersionV1 | None,
    M1dSelectionProofV1,
    M1dDatasetInput[SessionInputRecordV1] | None,
]:
    matching_datasets = tuple(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == binding.dataset_role
        and item.manifest.source.source_id == binding.source_id
        and manifest_hash(item.manifest) in binding.manifest_hashes
    )
    candidates: list[ScheduledSessionVersionV1 | SessionCoverageVersionV1] = []
    for dataset in matching_datasets:
        for record in dataset.records:
            if isinstance(record, ScheduledSessionVersionV1) and (
                binding.dataset_role == "scheduled_session"
                and record.source_id == binding.source_id
                and record.source_methodology_hash in binding.methodology_hashes
                and record.session_key.mic == query.venue.value
                and record.session_key.session_scope == "regular"
                and record.session_key.local_date == query.session_date
            ):
                candidates.append(record)
            elif isinstance(record, SessionCoverageVersionV1) and (
                binding.dataset_role == "session_coverage"
                and record.source_id == binding.source_id
                and record.methodology_hash in binding.methodology_hashes
                and record.mic == query.venue.value
                and record.session_scope == "regular"
                and record.start_date <= query.session_date <= record.end_date
            ):
                candidates.append(record)
    by_logical: dict[
        object, list[ScheduledSessionVersionV1 | SessionCoverageVersionV1]
    ] = {}
    for record in candidates:
        by_logical.setdefault(record.revision.logical_record_id, []).append(record)
    selections = tuple(
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
    selected_hashes = tuple(
        selection.selected_record_hash
        for selection in selections
        if selection.classification is CutoffEligibility.ELIGIBLE
        and selection.selected_record_hash is not None
    )
    selected = tuple(
        record for record in candidates if content_hash(record) in selected_hashes
    )
    availability_decisions: list[CutoffEligibilityResultV1] = []
    for record in candidates:
        evidence = next(
            (
                item
                for item in record.revision.availability
                if item.channel == query.requested_channel
            ),
            None,
        )
        if evidence is not None:
            availability_decisions.append(
                evaluate_availability(
                    evidence,
                    query.requested_channel,
                    availability_policy,
                    observation_cutoff(query),
                    context.retained_evidence,
                )
            )
    selection_classification: Literal["selected", "absent", "indeterminate"] = (
        "selected"
        if len(selected) == 1
        else "indeterminate"
        if any(
            item.classification is CutoffEligibility.INDETERMINATE
            for item in selections
        )
        or len(selected) > 1
        else "absent"
    )
    proof = M1dSelectionProofV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        purpose=binding.dataset_role,  # type: ignore[arg-type]
        context_hash=query.input_context_hash,
        subject=SessionSubjectV1(
            source_id=binding.source_id,
            mic=query.venue.value,
            session_date=query.session_date,
            session_scope="regular",
        ),
        considered_version_hashes=tuple(content_hash(item) for item in candidates),
        selected_hashes=(content_hash(selected[0]),) if len(selected) == 1 else (),
        assertion_selections=selections,
        availability_decisions=tuple(availability_decisions),
        semantic_algorithm_hash=schedule_generation_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
        classification=selection_classification,
    )
    selected_dataset = matching_datasets[0] if len(matching_datasets) == 1 else None
    return (selected[0] if len(selected) == 1 else None), proof, selected_dataset


def _coverage_reason(
    coverage: SessionCoverageVersionV1,
    source_dataset: M1dDatasetInput[SessionInputRecordV1],
    session_date: object,
) -> str | None:
    records = tuple(
        item
        for item in source_dataset.records
        if isinstance(item, ScheduledSessionVersionV1)
    )
    inventory = tuple(
        sorted(
            (
                item.revision.logical_record_id,
                item.revision.record_version_id,
                content_hash(item),
            )
            for item in records
        )
    )
    actual = tuple(
        sorted(
            (item.assertion_id, item.version_id, item.record_hash)
            for item in coverage.record_inventory
        )
    )
    logical_dates = {
        (item.revision.logical_record_id, item.session_key.local_date)
        for item in records
    }
    counts: dict[object, int] = {}
    for _, item_date in logical_dates:
        counts[item_date] = counts.get(item_date, 0) + 1
    if (
        coverage.status != "expected_complete"
        or coverage.revision_history_completeness != "complete"
    ):
        return "session_coverage_not_complete"
    if manifest_hash(source_dataset.manifest) not in coverage.covered_dataset_hashes:
        return "session_coverage_target_manifest_mismatch"
    if tuple(sorted(source_dataset.artifacts)) != coverage.covered_partition_hashes:
        return "session_coverage_partition_inventory_mismatch"
    if actual != inventory:
        return "session_coverage_record_inventory_mismatch"
    if counts.get(session_date) != coverage.expected_daily_cardinality:
        return "session_coverage_daily_cardinality_mismatch"
    return None


def _load_timezone_input(
    policy: ScheduleGenerationPolicyV1, context: M1dResolutionContext
) -> tuple[TimezoneInputV1, bytes]:
    encoding = context.supporting_artifacts.get(policy.timezone_input_hash)
    if encoding is None:
        raise ValueError("timezone input descriptor unavailable")
    try:
        value = TimezoneInputV1.model_validate_json(encoding.data)
    except ValidationError as error:
        raise ValueError("timezone input descriptor invalid") from error
    if (
        canonical_json(value) != encoding.data
        or content_hash(value) != policy.timezone_input_hash
    ):
        raise ValueError("timezone input descriptor hash mismatch")
    if (
        value.canonical_encoding_contract_hash
        != canonical_session_encoding_contract_hash()
    ):
        raise ValueError("timezone input encoding contract mismatch")
    artifact = context.supporting_artifacts.get(value.artifact_hash)
    if artifact is None or artifact.content_hash != value.tzif_sha256:
        raise ValueError("timezone input bytes unavailable")
    if sha256(artifact.data).hexdigest() != value.tzif_sha256:
        raise ValueError("timezone input bytes hash mismatch")
    return value, artifact.data


def _reconstruct_output(
    record: ScheduledSessionVersionV1,
    timezone_input: TimezoneInputV1,
    timezone_bytes: bytes,
    query: ObservationQueryV1,
    context: M1dResolutionContext,
) -> tuple[SessionOutputV1, tuple[CutoffEligibilityResultV1, ...], tuple[str, ...]]:
    base: dict[str, object] = {
        "schema_version": "1",
        "session_key": record.session_key,
        "state": record.state,
        "local_open": record.local_open,
        "local_close": record.local_close,
        "open_fold": record.open_fold,
        "close_fold": record.close_fold,
    }
    if record.state == "unknown":
        return _failed_output(base, "indeterminate", "source_session_state_unknown")
    if record.state == "closed":
        return (
            SessionOutputV1.model_validate(
                {
                    **base,
                    "utc_open": None,
                    "utc_close": None,
                    "interpretation_status": "authorized",
                }
            ),
            (),
            (),
        )
    if record.timezone_identifier != timezone_input.timezone_identifier:
        return _failed_output(base, "conflict", "timezone_identifier_mismatch")
    try:
        zone = ZoneInfo.from_file(
            BytesIO(timezone_bytes), key=timezone_input.timezone_identifier
        )
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("verified TZif bytes are invalid") from error
    decisions: list[CutoffEligibilityResultV1] = []
    converted: dict[str, datetime] = {}
    statuses: list[str] = []
    reasons: list[str] = []
    offsets = {item.boundary: item for item in record.historical_boundary_offsets}
    labels = {"open": record.local_open, "close": record.local_close}
    folds = {"open": record.open_fold, "close": record.close_fold}
    for name in ("open", "close"):
        offset = offsets[name]
        label = labels[name]
        assert label is not None
        authority_status, authority_reason, authority_decisions = _check_authority(
            record, offset, label, query, context
        )
        decisions.extend(authority_decisions)
        if authority_status != "authorized":
            statuses.append(authority_status)
            reasons.append(authority_reason)
            continue
        converted_value, conversion_status, conversion_reason = _convert_boundary(
            label, folds[name], offset, zone
        )
        if converted_value is None:
            statuses.append(conversion_status)
            reasons.append(conversion_reason)
        else:
            converted[name] = converted_value
    if statuses:
        status = "conflict" if "conflict" in statuses else "indeterminate"
        output, _, _ = _failed_output(base, status, reasons[0])
        return output, tuple(decisions), tuple(reasons)
    return (
        SessionOutputV1.model_validate(
            {
                **base,
                "utc_open": converted["open"],
                "utc_close": converted["close"],
                "interpretation_status": "authorized",
            }
        ),
        tuple(decisions),
        (),
    )


def _failed_output(
    base: dict[str, object], status: str, reason: str
) -> tuple[SessionOutputV1, tuple[CutoffEligibilityResultV1, ...], tuple[str, ...]]:
    return (
        SessionOutputV1.model_validate(
            {
                **base,
                "utc_open": None,
                "utc_close": None,
                "interpretation_status": status,
            }
        ),
        (),
        (reason,),
    )


def _check_authority(
    record: ScheduledSessionVersionV1,
    offset: HistoricalBoundaryOffsetV1,
    local_label: str,
    query: ObservationQueryV1,
    context: M1dResolutionContext,
) -> tuple[str, str, tuple[CutoffEligibilityResultV1, ...]]:
    values = (
        offset.utc_offset_seconds,
        offset.methodology_encoding_hash,
        offset.authority_artifact_hash,
        offset.authority_availability_evidence_hash,
    )
    if any(value is None for value in values):
        return "indeterminate", "historical_offset_authority_unknown", ()
    assert offset.utc_offset_seconds is not None
    assert offset.methodology_encoding_hash is not None
    assert offset.authority_artifact_hash is not None
    assert offset.authority_availability_evidence_hash is not None
    if not -86_400 < offset.utc_offset_seconds < 86_400:
        return "indeterminate", "historical_offset_out_of_supported_range", ()
    methodology_artifact = context.supporting_artifacts.get(
        offset.methodology_encoding_hash
    )
    if methodology_artifact is None:
        return "indeterminate", "historical_methodology_encoding_unavailable", ()
    try:
        methodology = HistoricalTimezoneMethodologyV1.model_validate_json(
            methodology_artifact.data
        )
    except ValidationError:
        return "indeterminate", "historical_methodology_encoding_unsupported", ()
    if (
        canonical_json(methodology) != methodology_artifact.data
        or content_hash(methodology) != offset.methodology_encoding_hash
        or record.source_methodology_hash != offset.methodology_encoding_hash
        or methodology.source_id != record.source_id
        or methodology.timezone_identifier != record.timezone_identifier
    ):
        return "conflict", "historical_methodology_binding_mismatch", ()
    source_methodology = context.supporting_artifacts.get(
        methodology.source_methodology_artifact_hash
    )
    expected_methodology = {
        "schema_version": "1",
        "kind": "historical_timezone_methodology",
        "source_id": methodology.source_id,
        "methodology_id": methodology.methodology_id,
        "methodology_version": methodology.methodology_version,
        "source_timezone_label": methodology.source_timezone_label,
        "timezone_identifier": methodology.timezone_identifier,
        "interpretation": methodology.interpretation,
    }
    if source_methodology is None:
        return "indeterminate", "source_methodology_artifact_unavailable", ()
    if source_methodology.data != canonical_json(expected_methodology):
        return "conflict", "source_methodology_payload_mismatch", ()
    methodology_decision = _authority_availability(
        methodology.source_methodology_availability_evidence_hash,
        methodology.source_methodology_artifact_hash,
        query,
        context,
    )
    authority = context.supporting_artifacts.get(offset.authority_artifact_hash)
    expected_offset = {
        "schema_version": "1",
        "kind": "historical_boundary_offset",
        "source_id": record.source_id,
        "mic": record.session_key.mic,
        "local_date": record.session_key.local_date.isoformat(),
        "boundary": offset.boundary,
        "local_label": local_label,
        "timezone_identifier": record.timezone_identifier,
        "utc_offset_seconds": offset.utc_offset_seconds,
    }
    if authority is None:
        return (
            "indeterminate",
            "historical_offset_artifact_unavailable",
            (methodology_decision,),
        )
    if authority.data != canonical_json(expected_offset):
        return (
            "conflict",
            "historical_offset_payload_mismatch",
            (methodology_decision,),
        )
    offset_decision = _authority_availability(
        offset.authority_availability_evidence_hash,
        offset.authority_artifact_hash,
        query,
        context,
    )
    decisions = (methodology_decision, offset_decision)
    if any(
        item.classification is CutoffEligibility.INDETERMINATE for item in decisions
    ):
        return "indeterminate", "historical_authority_availability_unknown", decisions
    if any(item.classification is not CutoffEligibility.ELIGIBLE for item in decisions):
        return "indeterminate", "historical_authority_unavailable_by_cutoff", decisions
    return "authorized", "historical_authority_eligible", decisions


def _authority_availability(
    evidence_hash: str,
    artifact_hash: str,
    query: ObservationQueryV1,
    context: M1dResolutionContext,
) -> CutoffEligibilityResultV1:
    evidence = context.retained_evidence.get(evidence_hash)
    policy = context.availability_policies[query.availability_policy_hash]
    if evidence is None or content_hash(evidence) != evidence_hash:
        evidence = AvailabilityEvidenceV1(
            channel=query.requested_channel,
            shape=AvailabilityShape.UNKNOWN,
            lower_bound=None,
            upper_bound=None,
            precision=SourcePrecision.UNKNOWN,
            source_time_label=None,
            source_timezone=None,
            basis=AvailabilityBasis.SOURCE_OBSERVED,
            evidence_reference=None,
            rule_derivation=None,
        )
    elif (
        evidence.evidence_reference is None
        or evidence.evidence_reference.content_hash != artifact_hash
    ):
        decision = evaluate_availability(
            evidence,
            query.requested_channel,
            policy,
            observation_cutoff(query),
            context.retained_evidence,
        )
        return decision.model_copy(
            update={
                "classification": CutoffEligibility.INDETERMINATE,
                "reason": "authority_evidence_artifact_mismatch",
            }
        )
    return evaluate_availability(
        evidence,
        query.requested_channel,
        policy,
        observation_cutoff(query),
        context.retained_evidence,
    )


def _convert_boundary(
    local_label: str,
    fold: int | None,
    offset: HistoricalBoundaryOffsetV1,
    zone: ZoneInfo,
) -> tuple[datetime | None, str, str]:
    try:
        local = datetime.fromisoformat(local_label)
    except ValueError:
        return None, "indeterminate", "invalid_local_boundary_label"
    if local.tzinfo is not None:
        return None, "conflict", "local_boundary_label_must_be_naive"
    candidates = []
    for candidate_fold in (0, 1):
        aware = local.replace(tzinfo=zone, fold=candidate_fold)
        utc_value = aware.astimezone(UTC)
        roundtrip = utc_value.astimezone(zone)
        if roundtrip.replace(tzinfo=None) == local and roundtrip.fold == candidate_fold:
            candidates.append((candidate_fold, aware, utc_value))
    distinct_offsets = {aware.utcoffset() for _, aware, _ in candidates}
    if len(distinct_offsets) > 1 and fold is None:
        return None, "indeterminate", "ambiguous_local_boundary_requires_fold"
    chosen_fold = fold if fold is not None else 0
    chosen = next((item for item in candidates if item[0] == chosen_fold), None)
    if chosen is None:
        return None, "conflict", "nonexistent_or_invalid_local_boundary"
    _, aware, reconstructed = chosen
    actual_offset = aware.utcoffset()
    assert offset.utc_offset_seconds is not None
    if (
        actual_offset is None
        or int(actual_offset.total_seconds()) != offset.utc_offset_seconds
    ):
        return None, "conflict", "historical_offset_reconstruction_disagreement"
    authoritative = (local - timedelta(seconds=offset.utc_offset_seconds)).replace(
        tzinfo=UTC
    )
    if authoritative != reconstructed:
        return None, "conflict", "authoritative_utc_reconstruction_disagreement"
    return authoritative, "authorized", "authorized"


def _artifact(
    query: ObservationQueryV1,
    policy: ScheduleGenerationPolicyV1,
    generated_at: datetime,
    *,
    timezone_bytes_hash: str,
    rows: Sequence[GeneratedSessionRowV1],
    source_proof: M1dSelectionProofV1 | None,
    coverage_proof: M1dSelectionProofV1 | None,
    authority_decisions: Sequence[CutoffEligibilityResultV1],
    reconstruction_hashes: tuple[str, ...],
    classification: str,
    reasons: tuple[str, ...],
) -> ScheduleArtifactV1:
    row_tuple = tuple(rows)
    outputs = tuple(item.output for item in row_tuple)
    output_bytes = canonical_json({"schema_version": "1", "rows": outputs})
    inventory_hash = content_hash({"schema_version": "1", "rows": row_tuple})
    proof_hashes = tuple(sorted({content_hash(item) for item in authority_decisions}))
    return ScheduleArtifactV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        selected_source_proof_hash=(
            content_hash(source_proof) if source_proof is not None else None
        ),
        selected_coverage_proof_hash=(
            content_hash(coverage_proof) if coverage_proof is not None else None
        ),
        generation_policy=policy,
        generation_policy_hash=content_hash(policy),
        timezone_bytes_hash=timezone_bytes_hash,
        generated_at=generated_at,
        rows=row_tuple,
        canonical_output_bytes_hash=sha256(output_bytes).hexdigest(),
        output_row_inventory_hash=inventory_hash,
        historical_authority_availability_proof_hashes=proof_hashes,
        reconstruction_input_hashes=tuple(sorted(set(reconstruction_hashes))),
        classification=classification,  # type: ignore[arg-type]
        reasons=tuple(sorted(set(reasons))),
    )
