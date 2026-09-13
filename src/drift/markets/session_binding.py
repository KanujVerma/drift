"""Bind completed source observations to exact realized venue sessions."""

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.observation_query import (
    ObservationQueryV1,
    m1d_implementation_hash,
    observation_cutoff,
    observation_horizon,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationContractV1,
    ObservationCoverageVersionV1,
)
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    SessionCoverageVersionV1,
    SessionKeyV1,
)
from drift.markets.observation_selection import (
    SelectedObservationContractV1,
    select_observation_records,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
)
from drift.serialization.canonical import content_hash


class ObservationSourceLabelMappingV1(FrozenModel):
    """Exact source-label semantics mapped to one venue session key."""

    schema_version: Literal["1"] = "1"
    source_local_label: NonBlankStr
    source_timezone: NonBlankStr
    timestamp_meaning: NonBlankStr
    source_label_syntax: NonBlankStr
    session_key: SessionKeyV1


class ExactSessionIntervalV1(FrozenModel):
    """Exact actual regular-session UTC bounds from a realized report."""

    schema_version: Literal["1"] = "1"
    opened_at: UTCDateTime
    closed_at: UTCDateTime

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.closed_at <= self.opened_at:
            raise ValueError("actual session close must follow open")
        return self


class ObservationSessionBindingResultV1(FrozenModel):
    """Replayable result for one observation and realized-session binding."""

    schema_version: Literal["1"] = "1"
    query: ObservationQueryV1
    query_hash: SHA256Hash
    observation_hash: SHA256Hash | None
    contract_hash: SHA256Hash
    session_key: SessionKeyV1
    selected_schedule_proof_hash: SHA256Hash | None
    selected_realized_proof_hash: SHA256Hash | None
    source_label_mapping: ObservationSourceLabelMappingV1 | None
    claimed_interval: TemporalIntervalClaimV1 | None
    actual_interval: ExactSessionIntervalV1 | None
    classification: Literal["bound", "conflict", "indeterminate"]
    reasons: tuple[NonBlankStr, ...]
    dependency_hashes: tuple[SHA256Hash, ...]
    context_hash: SHA256Hash
    source_selection_policy_hash: SHA256Hash
    semantic_algorithm_hash: SHA256Hash
    implementation_hash: SHA256Hash

    @field_validator("reasons")
    @classmethod
    def canonicalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(set(values)) != len(values):
            raise ValueError("binding reasons must be nonempty and unique")
        return tuple(sorted(values))

    @field_validator("dependency_hashes")
    @classmethod
    def canonicalize_dependencies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(set(values)) != len(values):
            raise ValueError("binding dependencies must be nonempty and unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.query_hash != content_hash(self.query):
            raise ValueError("binding query hash mismatch")
        if self.context_hash != self.query.input_context_hash:
            raise ValueError("binding context hash mismatch")
        if self.contract_hash != self.query.contract_hash:
            raise ValueError("binding contract hash mismatch")
        if (
            self.session_key.mic != self.query.venue.value
            or self.session_key.local_date != self.query.session_date
            or self.session_key.session_scope != "regular"
        ):
            raise ValueError("binding session key must match query")
        if self.source_selection_policy_hash != self.query.source_selection_policy_hash:
            raise ValueError("binding source policy hash mismatch")
        if self.classification == "bound" and (
            self.observation_hash is None
            or self.source_label_mapping is None
            or self.claimed_interval is None
            or self.actual_interval is None
            or self.selected_realized_proof_hash is None
        ):
            raise ValueError("bound classification requires exact dependencies")
        if self.actual_interval is not None and self.classification != "bound":
            raise ValueError(
                "only a bound result may carry an eligible actual interval"
            )
        return self


_BINDING_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "observation_realized_session_binding_v1",
    "session_authority": "exact_realized_interval_only",
    "schedule_role": "separate_comparison_evidence",
    "label_mapping": "exact_contract_declared_local_session_date",
    "endpoint_policy": "explicit_open_close_and_auction",
}


def binding_algorithm_hash() -> str:
    """Return the semantic identity of exact realized-session binding."""
    return content_hash(_BINDING_ALGORITHM_V1)


def bind_observation_session(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ObservationSessionBindingResultV1:
    """Bind a selected completed bar to exact realized regular-session bounds."""
    validate_m1d_resolution_context(context)
    if query.input_context_hash != m1d_context_hash(context):
        raise ValueError("observation query context hash mismatch")
    observation = select_observation_records(query, "observation", context)
    coverage = select_observation_records(query, "observation_coverage", context)
    schedule = select_observation_records(query, "scheduled_session", context)
    realized = select_observation_records(query, "realized_session", context)
    session_coverage = select_observation_records(query, "session_coverage", context)
    contract_selection = select_observation_records(query, "contract", context)
    assert isinstance(contract_selection, SelectedObservationContractV1)
    contract = contract_selection.contract
    contract_proof = contract_selection.proof

    observation_record = _one(observation.records, DailySourceObservationVersionV1)
    coverage_record = _one(coverage.records, ObservationCoverageVersionV1)
    schedule_record = _one(schedule.records, ScheduledSessionVersionV1)
    realized_record = _one(realized.records, RealizedSessionVersionV1)
    session_coverage_record = _one(session_coverage.records, SessionCoverageVersionV1)
    session_key = SessionKeyV1(
        mic=query.venue.value,
        session_scope="regular",
        local_date=query.session_date,
    )
    label_mapping = (
        _label_mapping(observation_record, contract, session_key, context)
        if observation_record is not None and contract is not None
        else None
    )
    classification: Literal["bound", "conflict", "indeterminate"] = "indeterminate"
    blocking_reasons: list[str] = []
    diagnostic_reasons: list[str] = []
    actual_interval = None

    if observation_record is None:
        blocking_reasons.append(
            "observation_absent_in_verified_inventory"
            if observation.proof.classification == "absent"
            else "observation_not_selected"
        )
    if contract is None:
        blocking_reasons.append("observation_contract_not_selected")
    if coverage_record is None or not _coverage_proves_observation(
        coverage_record, observation_record
    ):
        diagnostic_reasons.append("observation_coverage_unproven")
    if (
        label_mapping is None
        and observation_record is not None
        and contract is not None
    ):
        blocking_reasons.append("observation_label_mapping_unproven")
    if (
        contract is not None
        and observation_record is not None
        and not _endpoint_policy_is_explicit(observation_record, contract, context)
    ):
        blocking_reasons.append("observation_endpoint_policy_unproven")

    if observation_record is not None and realized_record is not None:
        if realized_record.outcome == "did_not_open":
            classification = "conflict"
            blocking_reasons = ["realized_session_did_not_open"]
        elif (
            realized_record.outcome != "opened"
            or realized_record.actual_open is None
            or realized_record.actual_close is None
        ):
            blocking_reasons.append("realized_session_interval_unknown")
        elif not _realized_interval_is_causal(realized_record, query):
            blocking_reasons.append("realized_session_interval_beyond_query")
        elif not _claimed_interval_is_compatible(
            observation_record, realized_record, contract
        ):
            classification = "conflict"
            blocking_reasons = ["claimed_interval_not_exact_realized_session"]
        elif not blocking_reasons:
            classification = "bound"
            actual_interval = ExactSessionIntervalV1(
                opened_at=realized_record.actual_open,
                closed_at=realized_record.actual_close,
            )
            diagnostic_reasons.append("bound_to_exact_realized_session")
    elif realized_record is None:
        blocking_reasons.append("realized_session_not_selected")

    if (
        classification == "bound"
        and schedule_record is not None
        and schedule_record.state in {"closed", "unknown"}
    ):
        diagnostic_reasons.append("schedule_realized_difference")
    if schedule_record is not None and not _session_coverage_proves_schedule(
        session_coverage_record, schedule_record
    ):
        diagnostic_reasons.append("schedule_coverage_unproven")
    if not blocking_reasons and not diagnostic_reasons:
        blocking_reasons.append("binding_evidence_indeterminate")

    dependencies = [
        content_hash(observation.proof),
        content_hash(coverage.proof),
        content_hash(schedule.proof),
        content_hash(realized.proof),
        content_hash(session_coverage.proof),
        content_hash(contract_proof),
        query.input_context_hash,
        query.source_selection_policy_hash,
        binding_algorithm_hash(),
        m1d_implementation_hash(),
    ]
    for selected in (observation, coverage, schedule, realized, session_coverage):
        dependencies.extend(content_hash(item) for item in selected.records)
    if contract is not None:
        dependencies.append(content_hash(contract))

    return ObservationSessionBindingResultV1(
        query=query,
        query_hash=content_hash(query),
        observation_hash=(
            content_hash(observation_record) if observation_record is not None else None
        ),
        contract_hash=query.contract_hash,
        session_key=session_key,
        selected_schedule_proof_hash=(
            content_hash(schedule.proof) if schedule_record is not None else None
        ),
        selected_realized_proof_hash=(
            content_hash(realized.proof) if realized_record is not None else None
        ),
        source_label_mapping=label_mapping,
        claimed_interval=(
            observation_record.claimed_interval
            if observation_record is not None
            else None
        ),
        actual_interval=actual_interval,
        classification=classification,
        reasons=tuple((*blocking_reasons, *diagnostic_reasons)),
        dependency_hashes=tuple(sorted(set(dependencies))),
        context_hash=query.input_context_hash,
        source_selection_policy_hash=query.source_selection_policy_hash,
        semantic_algorithm_hash=binding_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
    )


def verify_session_binding(
    result: ObservationSessionBindingResultV1, context: M1dResolutionContext
) -> None:
    """Replay a binding and compare complete selected values and derivation."""
    replayed = bind_observation_session(result.query, context)
    if replayed != result:
        raise ValueError("session binding replay mismatch")


def _one[T](values: Sequence[object], expected: type[T]) -> T | None:
    if len(values) == 1 and isinstance(values[0], expected):
        return values[0]
    return None


def _label_mapping(
    observation: DailySourceObservationVersionV1,
    contract: ObservationContractV1,
    session_key: SessionKeyV1,
    context: M1dResolutionContext,
) -> ObservationSourceLabelMappingV1 | None:
    if (
        contract.timestamp_meaning != "exchange_local_session_date"
        or contract.source_label_syntax != "YYYY-MM-DD"
        or observation.source_local_label != session_key.local_date.isoformat()
        or observation.source_timezone != contract.source_timezone
        or session_key.mic not in contract.market_venues
        or contract.methodology_artifact_hash not in context.supporting_artifacts
    ):
        return None
    return ObservationSourceLabelMappingV1(
        source_local_label=observation.source_local_label,
        source_timezone=observation.source_timezone,
        timestamp_meaning=contract.timestamp_meaning,
        source_label_syntax=contract.source_label_syntax,
        session_key=session_key,
    )


def _endpoint_policy_is_explicit(
    observation: DailySourceObservationVersionV1,
    contract: ObservationContractV1,
    context: M1dResolutionContext,
) -> bool:
    known = {"included", "excluded"}
    interval = contract.interval_policy
    if (
        interval.open_inclusion not in known
        or interval.close_inclusion not in known
        or interval.auction_event_inclusion not in known
        or interval.event_policy_hash not in context.supporting_artifacts
    ):
        return False
    methods = {
        (item.field_name, item.method_id): item for item in contract.field_methods
    }
    populations = {item.population_id: item for item in contract.populations}
    flags = {item.key: item.value for item in observation.source_flags}
    used_populations = set()
    for field in observation.fields:
        method = methods.get((field.field_name, field.method_id))
        if method is None:
            return False
        branches = tuple(
            item
            for item in contract.method_branches
            if item.method_id == method.method_id
        )
        active = tuple(
            item
            for item in branches
            if item.trigger_kind == "always"
            or flags.get(item.marker_name or "") == item.marker_value
        )
        if len(active) != 1 or method.population_id not in populations:
            return False
        used_populations.add(method.population_id)
    if not used_populations:
        return False
    return all(
        population.session_scope == "regular"
        and population.event_time_basis == "execution"
        and observation.venue.value in population.venue_scope
        and population.opening_auction_rule == interval.auction_event_inclusion
        and population.closing_auction_rule == interval.auction_event_inclusion
        for population_id in used_populations
        for population in (populations[population_id],)
    )


def _coverage_proves_observation(
    coverage: ObservationCoverageVersionV1,
    observation: DailySourceObservationVersionV1 | None,
) -> bool:
    if observation is None:
        return False
    return (
        coverage.status == "expected_complete"
        and coverage.revision_history_completeness == "complete"
        and any(
            item.assertion_id == observation.revision.logical_record_id
            and item.version_id == observation.revision.record_version_id
            and item.record_hash == content_hash(observation)
            for item in coverage.record_inventory
        )
    )


def _session_coverage_proves_schedule(
    coverage: SessionCoverageVersionV1 | None,
    schedule: ScheduledSessionVersionV1,
) -> bool:
    if coverage is None:
        return False
    return (
        coverage.status == "expected_complete"
        and coverage.revision_history_completeness == "complete"
        and any(
            item.assertion_id == schedule.revision.logical_record_id
            and item.version_id == schedule.revision.record_version_id
            and item.record_hash == content_hash(schedule)
            for item in coverage.record_inventory
        )
    )


def _realized_interval_is_causal(
    realized: RealizedSessionVersionV1, query: ObservationQueryV1
) -> bool:
    if realized.actual_close is None:
        return False
    return realized.actual_close <= min(
        observation_cutoff(query), observation_horizon(query)
    )


def _claimed_interval_is_compatible(
    observation: DailySourceObservationVersionV1,
    realized: RealizedSessionVersionV1,
    contract: ObservationContractV1 | None,
) -> bool:
    claimed_end = observation.claimed_interval.end
    if (
        contract is None
        or realized.actual_open is None
        or realized.actual_close is None
        or observation.claimed_interval.start.lower_bound is None
        or observation.claimed_interval.start.upper_bound is None
        or claimed_end is None
        or claimed_end.lower_bound is None
        or claimed_end.upper_bound is None
        or observation.claimed_interval.start.lower_bound
        != observation.claimed_interval.start.upper_bound
        or claimed_end.lower_bound != claimed_end.upper_bound
    ):
        return False
    start = observation.claimed_interval.start.lower_bound
    end = claimed_end.upper_bound
    if start != realized.actual_open or end != realized.actual_close:
        return False
    first = observation.first_eligible_trade_time
    last = observation.last_eligible_trade_time
    if (
        first is not None
        and first.lower_bound == realized.actual_open
        and contract.interval_policy.open_inclusion != "included"
    ):
        return False
    return not (
        last is not None
        and last.upper_bound == realized.actual_close
        and contract.interval_policy.close_inclusion != "included"
    )
