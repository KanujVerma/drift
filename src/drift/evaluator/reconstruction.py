"""Exploratory scheduled source-basis observation reconstruction for M2."""

from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.evaluator_reconstruction import (
    REQUIRED_RECONSTRUCTION_FIELDS,
    ExploratoryCohortAuthorizationV1,
    ExploratoryReconstructedFieldV1,
    ExploratoryReconstructedSessionObservationV1,
    ExploratoryReconstructionPolicyV1,
    cohort_authorization_hash,
    exploratory_reconstruction_hash,
    exploratory_reconstruction_semantic_hash,
    reconstruction_policy_hash,
)
from drift.domain.observation_query import (
    ObservationOutcomeQueryV1,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationContractV1,
    ObservationFieldMethodV1,
)
from drift.domain.sessions import (
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
)
from drift.markets.observation_selection import select_observation_records
from drift.markets.observation_validation import (
    M1dResolutionContext,
    validate_m1d_resolution_context,
)
from drift.markets.session_generation import generate_schedule
from drift.serialization.canonical import content_hash

_PRICE_MEANINGS: dict[str, frozenset[str]] = {
    "open": frozenset({"official_open", "first_trade_price"}),
    "high": frozenset({"maximum_trade_price"}),
    "low": frozenset({"minimum_trade_price"}),
    "close": frozenset({"official_close", "last_trade_price"}),
}


def build_exploratory_reconstructed_session_observation(
    query: ObservationOutcomeQueryV1,
    context: M1dResolutionContext,
    cohort: ExploratoryCohortAuthorizationV1,
    policy: ExploratoryReconstructionPolicyV1,
) -> ExploratoryReconstructedSessionObservationV1:
    """Build one scheduled exploratory session observation from exact source events."""
    if not isinstance(query, ObservationOutcomeQueryV1) or query.kind != "outcome":
        raise ValueError("exploratory reconstruction requires an outcome query")
    validate_m1d_resolution_context(context)
    if cohort.cohort_hash != cohort_authorization_hash(cohort):
        raise ValueError("cohort authorization hash is not self-consistent")
    if policy.policy_hash != reconstruction_policy_hash(policy):
        raise ValueError("reconstruction policy hash is not self-consistent")
    if policy.semantic_policy_hash != exploratory_reconstruction_semantic_hash():
        raise ValueError("reconstruction policy semantic identity mismatch")
    if policy.mode != "source_basis_scheduled_session_reconstruction_v1":
        raise ValueError("unsupported reconstruction policy mode")
    if policy.required_basis != "unadjusted":
        raise ValueError("exploratory reconstruction supports source basis only")
    if query.security_id not in cohort.security_ids:
        raise ValueError("query security is not authorized by the declared cohort")

    selected_observation = select_observation_records(query, "observation", context)
    if (
        selected_observation.proof.classification != "selected"
        or len(selected_observation.records) != 1
    ):
        raise ValueError(
            "exploratory reconstruction requires exactly one source observation"
        )
    observation_record = selected_observation.records[0]
    if not isinstance(observation_record, DailySourceObservationVersionV1):
        raise ValueError("selected source observation must be a daily observation")
    if observation_record.security_id != query.security_id:
        raise ValueError("source observation security mismatch")
    if observation_record.listing_id != query.listing_id:
        raise ValueError("source observation listing mismatch")
    if observation_record.venue != query.venue:
        raise ValueError("source observation venue mismatch")
    if observation_record.session_date != query.session_date:
        raise ValueError("source observation session date mismatch")
    if observation_record.contract_hash != query.contract_hash:
        raise ValueError("source observation contract mismatch")

    selected_contract = select_observation_records(query, "contract", context)
    if (
        selected_contract.proof.classification != "selected"
        or len(selected_contract.records) != 1
    ):
        raise ValueError(
            "exploratory reconstruction requires exactly one observation contract"
        )
    contract_record = selected_contract.records[0]
    if not isinstance(contract_record, ObservationContractV1):
        raise ValueError("selected contract must be an ObservationContractV1")
    if content_hash(contract_record) != query.contract_hash:
        raise ValueError("selected observation contract hash mismatch")
    if contract_record.source_id != query.source_id:
        raise ValueError("selected observation contract source mismatch")
    if contract_record.adjustment_basis != "unadjusted":
        raise ValueError("exploratory reconstruction requires an unadjusted contract")

    selected_session = select_observation_records(query, "scheduled_session", context)
    if (
        selected_session.proof.classification != "selected"
        or len(selected_session.records) != 1
    ):
        raise ValueError(
            "exploratory reconstruction requires exactly one scheduled session"
        )
    session_record = selected_session.records[0]
    if not isinstance(session_record, ScheduledSessionVersionV1):
        raise ValueError("selected scheduled session has an unexpected record type")
    if session_record.session_key.mic != query.venue.value:
        raise ValueError("selected scheduled session venue mismatch")
    if session_record.session_key.local_date != query.session_date:
        raise ValueError("selected scheduled session date mismatch")

    policy_hash = _policy_generation_hash(context)
    schedule_policy = policy_hash
    schedule_artifact = generate_schedule(query, context, schedule_policy)
    if schedule_artifact.classification != "generated":
        raise ValueError(
            "exploratory reconstruction requires a generated session schedule"
        )
    rows = tuple(
        row
        for row in schedule_artifact.rows
        if row.output.session_key.mic == query.venue.value
        and row.output.session_key.local_date == query.session_date
    )
    if len(rows) != 1:
        raise ValueError(
            "exploratory reconstruction requires exactly one generated session"
        )
    generated_row = rows[0]
    if generated_row.source_version_hash != content_hash(session_record):
        raise ValueError(
            "generated schedule source does not match the independently "
            "selected scheduled session"
        )
    if generated_row.output.interpretation_status != "authorized":
        raise ValueError(
            "exploratory reconstruction requires an authorized generated session"
        )
    if generated_row.output.state not in {"regular", "early_close"}:
        raise ValueError(
            f"exploratory reconstruction cannot use a {generated_row.output.state!r}"
        )
    if generated_row.output.utc_open is None or generated_row.output.utc_close is None:
        raise ValueError(
            "exploratory reconstruction requires generated session UTC boundaries"
        )

    methods_by_name: dict[str, dict[str, ObservationFieldMethodV1]] = {}
    for method in contract_record.field_methods:
        if method.field_name not in methods_by_name:
            methods_by_name[method.field_name] = {}
        methods_by_name[method.field_name][method.method_id] = method

    projected_fields: list[ExploratoryReconstructedFieldV1] = []
    source_fields = {field.field_name: field for field in observation_record.fields}
    for field_name in REQUIRED_RECONSTRUCTION_FIELDS:
        field = source_fields.get(field_name)
        if field is None or field.state != "value" or field.value is None:
            raise ValueError(
                f"required field {field_name} is missing from the source observation"
            )
        candidates = methods_by_name.get(field_name)
        if candidates is None or field.method_id not in candidates:
            raise ValueError(
                f"selected field method {field.method_id!r} is not in the contract"
            )
        method = candidates[field.method_id]
        if method.adjustment_basis != "unadjusted":
            raise ValueError(f"field {field_name} method must be unadjusted")
        allowed = (
            frozenset({"share_volume"})
            if field_name == "volume"
            else _PRICE_MEANINGS[field_name]
        )
        if method.meaning not in allowed:
            raise ValueError(
                f"field {field_name} method has unsupported meaning {method.meaning!r}"
            )
        projected_fields.append(
            ExploratoryReconstructedFieldV1(
                schema_version="1",
                field_name=field_name,
                source_value=field.value,
                method_id=field.method_id,
                meaning="share_volume" if field_name == "volume" else "price",
                source_field_hash=content_hash(field),
            )
        )

    reconstruction = ExploratoryReconstructedSessionObservationV1.model_construct(
        schema_version="1",
        kind="exploratory_reconstructed_session_observation",
        session_key=generated_row.output.session_key,
        security_id=query.security_id,
        listing_id=query.listing_id,
        venue=query.venue,
        cohort_hash=cohort.cohort_hash,
        source_observation_hash=content_hash(observation_record),
        observation_contract_hash=query.contract_hash,
        observation_selection_proof_hash=content_hash(selected_observation.proof),
        contract_selection_proof_hash=content_hash(selected_contract.proof),
        scheduled_session_hash=content_hash(session_record),
        scheduled_selection_proof_hash=content_hash(selected_session.proof),
        schedule_artifact_hash=content_hash(
            schedule_artifact.model_dump(mode="python", exclude={"generated_at"})
        ),
        generated_session_row_hash=content_hash(generated_row),
        outcome_query_hash=content_hash(query),
        source_context_hash=query.input_context_hash,
        evidence_vintage_cutoff=query.evidence_vintage_cutoff,
        reconstruction_policy_hash=policy.policy_hash,
        currency=contract_record.currency,
        fields=tuple(projected_fields),
        acknowledged_limitations=tuple(
            sorted(
                (
                    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
                    ALPACA_LIMITATION_UNVERSIONED_BARS,
                )
            )
        ),
        reconstruction_hash="0" * 64,
    )
    candidate = reconstruction.model_copy(
        update={"reconstruction_hash": exploratory_reconstruction_hash(reconstruction)}
    )
    return ExploratoryReconstructedSessionObservationV1.model_validate(
        candidate.model_dump(mode="python")
    )


def _policy_generation_hash(
    context: M1dResolutionContext,
) -> ScheduleGenerationPolicyV1:
    digest = context.schedule_generation_policy_hash
    if digest is None:
        raise ValueError("schedule generation policy unavailable")
    artifact = context.supporting_artifacts.get(digest)
    if artifact is None:
        raise ValueError("schedule generation policy bytes unavailable")
    return ScheduleGenerationPolicyV1.model_validate_json(artifact.data)
