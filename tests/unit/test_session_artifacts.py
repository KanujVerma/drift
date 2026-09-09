"""Behavioral contract tests for immutable M1d session artifacts."""

import json
from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from typing import BinaryIO
from zoneinfo import ZoneInfo

import pytest
from session_test_support import (
    dataset_with_unique_nested_reference,
    date_evidence,
    generation_case,
    instant,
    realized_record,
    revision,
    schedule_record,
    session_dataset,
    session_supporting_artifacts,
    timezone_bytes,
    uid,
)

from drift.serialization.canonical import content_hash


def test_retained_synthetic_winter_and_summer() -> None:
    zone = ZoneInfo.from_file(BytesIO(timezone_bytes()), key="Synthetic/Eastern")
    winter = datetime(2026, 1, 5, 9, 30, tzinfo=zone).astimezone(UTC)
    summer = datetime(2026, 7, 6, 9, 30, tzinfo=zone).astimezone(UTC)
    assert winter.isoformat() == "2026-01-05T14:30:00+00:00"
    assert summer.isoformat() == "2026-07-06T13:30:00+00:00"


def test_schedule_models_enforce_source_state_shapes() -> None:
    from drift.domain.sessions import ScheduledSessionVersionV1, SessionKeyV1

    key = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 1, 5))
    with pytest.raises(ValueError, match="open session requires local boundaries"):
        ScheduledSessionVersionV1.model_validate(
            {
                "schema_version": "1",
                "revision": revision(),
                "source_id": "calendar-source",
                "session_key": key,
                "source_temporal_evidence": date_evidence(date(2026, 1, 5), 50),
                "state": "regular",
                "local_open": None,
                "local_close": None,
                "timezone_identifier": "Synthetic/Eastern",
                "open_fold": None,
                "close_fold": None,
                "historical_boundary_offsets": (),
                "source_methodology_hash": "0" * 64,
            }
        )


def test_realized_report_retains_independent_axes_without_schedule() -> None:
    report = realized_record()
    assert report.reported_as_scheduled == "denied"
    assert report.late_open == "asserted"
    assert report.early_close == "asserted"
    assert report.compared_schedule_hash is None


def test_realized_did_not_open_cannot_carry_proven_open_bounds() -> None:
    from drift.domain.sessions import RealizedSessionVersionV1, SessionKeyV1

    with pytest.raises(ValueError, match="cannot carry actual bounds"):
        RealizedSessionVersionV1(
            schema_version="1",
            revision=revision(20),
            source_id="incident-source",
            session_key=SessionKeyV1(
                mic="XNYS",
                session_scope="regular",
                local_date=date(2026, 1, 5),
            ),
            outcome="did_not_open",
            actual_open=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
            actual_close=None,
            reported_as_scheduled="unknown",
            late_open="unknown",
            early_close="unknown",
            interruption_intervals=(),
            interruption_coverage="unknown",
            source_evidence_hashes=("1" * 64,),
            methodology_hashes=("2" * 64,),
            compared_schedule_hash=None,
        )


def test_methodology_requires_recognized_canonical_encoding_contract() -> None:
    from drift.domain.sessions import HistoricalTimezoneMethodologyV1

    with pytest.raises(ValueError, match="recognized v1 encoding contract"):
        HistoricalTimezoneMethodologyV1(
            schema_version="1",
            source_id="calendar-source",
            methodology_id="explicit-offsets",
            methodology_version="1",
            source_timezone_label="Eastern",
            timezone_identifier="Synthetic/Eastern",
            interpretation="explicit_boundary_offsets_v1",
            source_methodology_artifact_hash="1" * 64,
            source_methodology_availability_evidence_hash="2" * 64,
            canonical_encoding_contract_hash="0" * 64,
        )


def test_conflicting_session_output_never_carries_eligible_utc_bounds() -> None:
    from drift.domain.sessions import SessionKeyV1, SessionOutputV1

    with pytest.raises(ValueError, match="indeterminate or conflicting output"):
        SessionOutputV1(
            schema_version="1",
            session_key=SessionKeyV1(
                mic="XNYS",
                session_scope="regular",
                local_date=date(2026, 1, 5),
            ),
            state="regular",
            utc_open=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
            utc_close=datetime(2026, 1, 5, 21, tzinfo=UTC),
            local_open="2026-01-05T09:30:00",
            local_close="2026-01-05T16:00:00",
            open_fold=None,
            close_fold=None,
            interpretation_status="conflict",
        )


def test_schedule_dataset_retains_open_closed_and_unknown_source_claims() -> None:
    methodology_hash, support, retained = session_supporting_artifacts()
    rows = (
        schedule_record(
            date(2026, 1, 5),
            "regular",
            methodology_hash,
            support,
            retained,
            suffix=300,
        ),
        schedule_record(
            date(2026, 11, 26),
            "closed",
            methodology_hash,
            support,
            retained,
            suffix=310,
        ),
        schedule_record(
            date(2026, 11, 28),
            "unknown",
            methodology_hash,
            support,
            retained,
            suffix=320,
        ),
    )

    dataset = session_dataset("scheduled_session", rows, support)

    assert dataset.records == rows
    assert rows[0].source_temporal_evidence.source_time_label == "2026-01-05"
    assert tuple(record.state for record in dataset.records) == (
        "regular",
        "closed",
        "unknown",
    )


def test_m1d_context_replays_session_datasets_with_immutable_empty_default() -> None:
    from drift.markets.observation_validation import (
        M1dResolutionContext,
        m1d_context_hash,
        validate_m1d_resolution_context,
    )

    methodology_hash, support, retained = session_supporting_artifacts()
    row = schedule_record(
        date(2026, 1, 5),
        "regular",
        methodology_hash,
        support,
        retained,
        suffix=340,
    )
    dataset = session_dataset("scheduled_session", (row,), support)
    context = M1dResolutionContext(
        observation_datasets=(),
        session_datasets=(dataset,),
        availability_policies={},
        retained_evidence=retained,
        supporting_artifacts=support,
    )

    validate_m1d_resolution_context(context)
    assert context.session_datasets == (dataset,)
    assert m1d_context_hash(context) == m1d_context_hash(context)


def test_source_policy_supports_role_specific_calendar_authority() -> None:
    from drift.domain.observation_query import ObservationSourceBindingV1
    from drift.domain.securities import ListingVenue

    binding = ObservationSourceBindingV1(
        schema_version="1",
        dataset_role="scheduled_session",
        source_id="calendar-source",
        contract_hash=None,
        venue=ListingVenue.XNYS,
        listing_id=uid(900),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        manifest_hashes=("1" * 64,),
        methodology_hashes=("2" * 64,),
    )

    assert binding.source_id == "calendar-source"
    assert binding.contract_hash is None


@pytest.mark.parametrize(
    ("local_date", "state", "expected_open", "expected_close"),
    (
        (
            date(2026, 1, 5),
            "regular",
            "2026-01-05T14:30:00+00:00",
            "2026-01-05T21:00:00+00:00",
        ),
        (
            date(2026, 7, 6),
            "regular",
            "2026-07-06T13:30:00+00:00",
            "2026-07-06T20:00:00+00:00",
        ),
        (
            date(2026, 11, 27),
            "early_close",
            "2026-11-27T14:30:00+00:00",
            "2026-11-27T18:00:00+00:00",
        ),
    ),
)
def test_generation_uses_pinned_tzif_and_historical_offsets(
    local_date: date, state: str, expected_open: str, expected_close: str
) -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(local_date=local_date, state=state)  # type: ignore[arg-type]

    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "generated"
    assert len(artifact.rows) == 1
    assert artifact.rows[0].output.utc_open.isoformat() == expected_open  # type: ignore[union-attr]
    assert artifact.rows[0].output.utc_close.isoformat() == expected_close  # type: ignore[union-attr]
    assert artifact.rows[0].output.interpretation_status == "authorized"


def test_modern_reconstruction_after_cutoff_does_not_claim_historical_authority() -> (
    None
):
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(local_date=date(2026, 1, 5))
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "generated"
    assert context.supporting_artifacts[policy.timezone_input_hash].data
    assert query.knowledge_cutoff < datetime(2027, 1, 1, tzinfo=UTC)
    assert len(artifact.historical_authority_availability_proof_hashes) == 3


def test_newer_conflicting_tzif_is_conflict_without_eligible_utc_bounds() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 7, 6), summer_offset_seconds=-10_800
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "conflict"
    assert artifact.rows[0].output.interpretation_status == "conflict"
    assert artifact.rows[0].output.utc_open is None
    assert artifact.rows[0].output.utc_close is None
    assert artifact.reasons == ("historical_offset_reconstruction_disagreement",)


def test_semantic_output_identity_ignores_unused_tzif_and_producer_lineage() -> None:
    from drift.markets.session_generation import generate_schedule

    first_context, first_query, first_policy = generation_case(
        local_date=date(2026, 1, 5), summer_offset_seconds=-14_400
    )
    second_context, second_query, second_policy = generation_case(
        local_date=date(2026, 1, 5), summer_offset_seconds=-10_800
    )
    first = generate_schedule(first_query, first_context, first_policy)
    second = generate_schedule(second_query, second_context, second_policy)

    assert first.rows[0].output == second.rows[0].output
    assert first.canonical_output_bytes_hash == second.canonical_output_bytes_hash
    assert first.output_row_inventory_hash != second.output_row_inventory_hash
    assert first.timezone_bytes_hash != second.timezone_bytes_hash


def test_finite_correction_selection_retains_both_versions_and_selects_latest() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5), corrected=True
    )
    artifact = generate_schedule(query, context, policy)

    schedule_dataset = next(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == "scheduled_session"
    )
    assert len(schedule_dataset.records) == 2
    assert artifact.rows[0].source_version_hash == content_hash(
        schedule_dataset.records[1]
    )


@pytest.mark.parametrize(
    ("session_date", "state", "classification", "status"),
    (
        (date(2026, 11, 26), "closed", "generated", "authorized"),
        (date(2026, 11, 28), "closed", "generated", "authorized"),
        (date(2026, 11, 29), "closed", "generated", "authorized"),
        (date(2026, 11, 30), "regular", "generated", "authorized"),
        (date(2026, 11, 25), "unknown", "indeterminate", "indeterminate"),
    ),
)
def test_explicit_closed_unknown_and_reopened_dates(
    session_date: date, state: str, classification: str, status: str
) -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=session_date,
        state=state,  # type: ignore[arg-type]
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == classification
    assert artifact.rows[0].output.interpretation_status == status
    if state in {"closed", "unknown"}:
        assert artifact.rows[0].output.utc_open is None
        assert artifact.rows[0].output.utc_close is None


def test_policy_methodology_set_must_equal_selected_boundary_claims() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(local_date=date(2026, 1, 5))
    forged = policy.model_copy(
        update={"historical_timezone_methodology_encoding_hashes": ()}
    )
    artifact = generate_schedule(query, context, forged)

    assert artifact.classification == "indeterminate"
    assert artifact.rows[0].output.utc_open is None
    assert artifact.reasons == ("generation_policy_methodology_set_mismatch",)


def test_schedule_replay_rejects_byte_substitution() -> None:
    from drift.markets.session_generation import generate_schedule, verify_schedule

    context, query, policy = generation_case(local_date=date(2026, 1, 5))
    artifact = generate_schedule(query, context, policy)
    verify_schedule(artifact, context)

    forged = artifact.model_copy(update={"canonical_output_bytes_hash": "f" * 64})
    with pytest.raises(ValueError, match="replay mismatch"):
        verify_schedule(forged, context)


@pytest.mark.parametrize(
    ("authority_known", "offset_seconds", "expected_reason"),
    (
        (False, None, "historical_offset_authority_unknown"),
        (True, 90_000, "historical_offset_out_of_supported_range"),
    ),
)
def test_unknown_or_unsupported_historical_offset_is_indeterminate(
    authority_known: bool, offset_seconds: int | None, expected_reason: str
) -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5),
        authority_known=authority_known,
        claimed_offset_seconds=offset_seconds,
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "indeterminate"
    assert artifact.rows[0].output.utc_open is None
    assert artifact.reasons == (expected_reason,)


def test_unsupported_raw_precision_stops_before_ambient_timezone_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.datasets.resolver import VerifiedArtifactBytes
    from drift.markets.session_validation import validate_session_dataset
    from drift.serialization.canonical import canonical_json

    methodology_hash, support, retained = session_supporting_artifacts()
    row = schedule_record(
        date(2026, 1, 5),
        "regular",
        methodology_hash,
        support,
        retained,
        suffix=720,
    )
    dataset = session_dataset("scheduled_session", (row,), support)
    original = next(iter(dataset.artifacts.values()))
    raw = json.loads(original.data)
    raw["records"][0]["revision"]["availability"][0]["precision"] = "date"
    bad_bytes = canonical_json(raw)
    bad_hash = sha256(bad_bytes).hexdigest()
    bad_reference = dataset.manifest.partitions[0].artifact.model_copy(
        update={
            "content_hash": bad_hash,
            "location": f"drift+sha256://{bad_hash}",
        }
    )
    bad_partition = dataset.manifest.partitions[0].model_copy(
        update={"artifact": bad_reference, "byte_size": len(bad_bytes)}
    )
    bad_manifest = dataset.manifest.model_copy(update={"partitions": (bad_partition,)})
    bad_artifacts = {
        bad_hash: VerifiedArtifactBytes(
            data=bad_bytes, byte_size=len(bad_bytes), content_hash=bad_hash
        )
    }

    class AmbientLookupForbidden:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("ambient timezone lookup must not occur")

    monkeypatch.setattr("drift.domain.temporal.ZoneInfo", AmbientLookupForbidden)
    decision, records = validate_session_dataset(
        bad_manifest, bad_artifacts, dataset.validation_run, support
    )

    assert records == ()
    assert tuple(item.code for item in decision.findings) == (
        "session_unsupported_raw_temporal_precision",
    )


def test_role_parser_rejects_schedule_bytes_as_realized_reports() -> None:
    from drift.domain.dataset_validation import DatasetValidationError
    from drift.markets.session_validation import parse_session_document

    methodology_hash, support, retained = session_supporting_artifacts()
    row = schedule_record(
        date(2026, 1, 5),
        "regular",
        methodology_hash,
        support,
        retained,
        suffix=740,
    )
    dataset = session_dataset("scheduled_session", (row,), support)
    source_bytes = next(iter(dataset.artifacts.values())).data

    with pytest.raises(DatasetValidationError) as caught:
        parse_session_document(source_bytes, "realized_session")
    assert tuple(item.code for item in caught.value.findings) == (
        "session_record_invalid",
    )


def test_source_schedule_model_rejects_payload_hash_substitution() -> None:
    methodology_hash, support, retained = session_supporting_artifacts()
    row = schedule_record(
        date(2026, 1, 5),
        "regular",
        methodology_hash,
        support,
        retained,
        suffix=760,
    )

    with pytest.raises(ValueError, match="schedule payload hash mismatch"):
        row.model_copy(
            update={
                "revision": row.revision.model_copy(update={"payload_hash": "f" * 64})
            }
        )


def test_timezone_and_generation_policy_require_exact_contract_hashes() -> None:
    from drift.domain.sessions import TimezoneInputV1

    context, _query, policy = generation_case(local_date=date(2026, 1, 5))
    descriptor = TimezoneInputV1.model_validate_json(
        context.supporting_artifacts[policy.timezone_input_hash].data
    )

    with pytest.raises(ValueError, match="recognized v1 encoding contract"):
        descriptor.model_copy(update={"canonical_encoding_contract_hash": "0" * 64})
    with pytest.raises(ValueError, match="recognized v1 encoding contract"):
        policy.model_copy(update={"canonical_encoding_contract_hash": "0" * 64})


def test_expected_complete_coverage_requires_exact_closed_inventory() -> None:
    context, _query, _policy = generation_case(local_date=date(2026, 1, 5))
    coverage = next(
        item.records[0]
        for item in context.session_datasets
        if item.manifest.dataset_role.name == "session_coverage"
    )

    with pytest.raises(ValueError, match="exact closed inventory"):
        coverage.model_copy(update={"record_inventory": ()})


def test_context_rejects_coverage_inventory_not_bound_to_exact_source_bytes() -> None:
    from drift.domain.dataset_validation import DatasetValidationError
    from drift.markets.observation_validation import validate_m1d_resolution_context

    context, _query, _policy = generation_case(
        local_date=date(2026, 1, 5), bad_coverage_hash=True
    )

    with pytest.raises(DatasetValidationError) as caught:
        validate_m1d_resolution_context(context)
    assert tuple(item.code for item in caught.value.findings) == (
        "session_coverage_inventory_mismatch",
    )


def test_realized_dataset_retains_late_early_and_interruption_without_schedule() -> (
    None
):
    _methodology_hash, support, _retained = session_supporting_artifacts()
    report = realized_record()
    dataset = session_dataset("realized_session", (report,), support)

    assert dataset.records == (report,)
    assert report.compared_schedule_hash is None
    assert report.late_open == "asserted"
    assert report.early_close == "asserted"
    assert len(report.interruption_intervals) == 1


def test_source_binding_methodology_must_match_selected_source_record() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5), binding_methodology_hash="b" * 64
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "indeterminate"
    assert artifact.rows == ()
    assert artifact.reasons == ("scheduled_session_not_selected",)


def test_session_selection_proof_rejects_observation_subject_shape() -> None:
    from drift.datasets.assertions import select_assertion_version
    from drift.domain.assertions import AssertionVersionProjectionV1
    from drift.domain.observation_query import (
        M1dSelectionProofV1,
        ObservationSubjectV1,
        observation_cutoff,
    )
    from drift.domain.temporal import evaluate_availability
    from drift.serialization.canonical import content_hash

    context, query, _policy = generation_case(local_date=date(2026, 1, 5))
    dataset = next(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == "scheduled_session"
    )
    record = dataset.records[0]
    record_hash = content_hash(record)
    availability_policy = context.availability_policies[query.availability_policy_hash]
    cutoff = observation_cutoff(query)
    selection = select_assertion_version(
        (
            AssertionVersionProjectionV1(
                revision=record.revision, record_hash=record_hash
            ),
        ),
        query.requested_channel,
        availability_policy,
        cutoff,
        context.retained_evidence,
    )
    decision = evaluate_availability(
        record.revision.availability[0],
        query.requested_channel,
        availability_policy,
        cutoff,
        context.retained_evidence,
    )

    with pytest.raises(ValueError, match="requires a session subject"):
        M1dSelectionProofV1(
            query=query,
            query_hash=content_hash(query),
            purpose="scheduled_session",
            context_hash=query.input_context_hash,
            subject=ObservationSubjectV1(
                listing_id=query.listing_id,
                security_id=query.security_id,
                venue=query.venue,
                session_date=query.session_date,
                source_id=query.source_id,
                contract_hash=query.contract_hash,
            ),
            considered_version_hashes=(record_hash,),
            selected_hashes=(record_hash,),
            assertion_selections=(selection,),
            availability_decisions=(decision,),
            semantic_algorithm_hash="a" * 64,
            implementation_hash="b" * 64,
            classification="selected",
        )


def test_realized_payload_hash_survives_dump_load_and_rejects_substitution() -> None:
    from drift.domain.sessions import RealizedSessionVersionV1
    from drift.serialization.canonical import canonical_json

    report = realized_record()
    assert (
        RealizedSessionVersionV1.model_validate_json(canonical_json(report)) == report
    )

    with pytest.raises(ValueError, match="realized session payload hash mismatch"):
        report.model_copy(
            update={
                "revision": report.revision.model_copy(
                    update={"payload_hash": "f" * 64}
                )
            }
        )


def test_realized_direct_construction_rejects_mismatched_payload_hash() -> None:
    from drift.domain.sessions import RealizedSessionVersionV1

    report = realized_record()
    values = {name: getattr(report, name) for name in type(report).model_fields}
    values["revision"] = report.revision.model_copy(update={"payload_hash": "f" * 64})

    with pytest.raises(ValueError, match="realized session payload hash mismatch"):
        RealizedSessionVersionV1(**values)


def test_realized_tampered_serialized_json_rejects_stale_payload_hash() -> None:
    from drift.domain.sessions import RealizedSessionVersionV1
    from drift.serialization.canonical import canonical_json

    raw = json.loads(canonical_json(realized_record()))
    raw["late_open"] = "denied"

    with pytest.raises(ValueError, match="realized session payload hash mismatch"):
        RealizedSessionVersionV1.model_validate_json(canonical_json(raw))


@pytest.mark.parametrize(
    "role",
    (
        "scheduled_session",
        "scheduled_revision",
        "realized_session",
        "session_coverage",
    ),
)
def test_session_validation_requires_all_nested_evidence_artifacts(role: str) -> None:
    from drift.markets.session_validation import validate_session_dataset

    dataset, support, nested_hash = dataset_with_unique_nested_reference(role)  # type: ignore[arg-type]
    pruned_support = dict(support)
    del pruned_support[nested_hash]

    decision, records = validate_session_dataset(
        dataset.manifest,
        dataset.artifacts,
        dataset.validation_run,
        pruned_support,
    )

    assert records == ()
    assert "session_missing_supporting_artifact" in {
        finding.code for finding in decision.findings
    }


def test_context_rejects_session_dataset_in_observation_slot() -> None:
    from drift.domain.dataset_validation import DatasetValidationError
    from drift.markets.observation_validation import (
        M1dResolutionContext,
        validate_m1d_resolution_context,
    )

    context, _query, _policy = generation_case(local_date=date(2026, 1, 5))
    scheduled = next(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == "scheduled_session"
    )
    swapped = M1dResolutionContext(
        observation_datasets=(scheduled,),  # type: ignore[arg-type]
        session_datasets=(),
        availability_policies=context.availability_policies,
        retained_evidence=context.retained_evidence,
        supporting_artifacts=context.supporting_artifacts,
    )

    with pytest.raises(DatasetValidationError) as caught:
        validate_m1d_resolution_context(swapped)
    assert tuple(item.code for item in caught.value.findings) == (
        "session_dataset_in_observation_slot",
    )


def test_context_rejects_observation_dataset_in_session_slot() -> None:
    from observation_test_support import observation_dataset

    from drift.domain.dataset_validation import DatasetValidationError
    from drift.markets.observation_validation import (
        M1dResolutionContext,
        validate_m1d_resolution_context,
    )

    observation, support = observation_dataset()
    swapped = M1dResolutionContext(
        observation_datasets=(),
        session_datasets=(observation,),  # type: ignore[arg-type]
        availability_policies={},
        retained_evidence={},
        supporting_artifacts=support,
    )

    with pytest.raises(DatasetValidationError) as caught:
        validate_m1d_resolution_context(swapped)
    assert tuple(item.code for item in caught.value.findings) == (
        "observation_dataset_in_session_slot",
    )


@pytest.mark.parametrize(
    "field_name", ("producer_source_hash", "producer_package_hash", "lockfile_hash")
)
def test_generation_requires_retained_reconstruction_lineage_artifacts(
    field_name: str,
) -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(local_date=date(2026, 1, 5))
    forged = policy.model_copy(update={field_name: "f" * 64})

    with pytest.raises(ValueError, match="reconstruction lineage artifact unavailable"):
        generate_schedule(query, context, forged)


def test_generation_binds_running_implementation_identity() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(local_date=date(2026, 1, 5))
    forged = policy.model_copy(update={"implementation_hash": "f" * 64})

    with pytest.raises(ValueError, match="implementation identity mismatch"):
        generate_schedule(query, context, forged)


def test_replay_rechecks_reconstruction_lineage_closure() -> None:
    from drift.markets.session_generation import generate_schedule, verify_schedule

    context, query, policy = generation_case(local_date=date(2026, 1, 5))
    artifact = generate_schedule(query, context, policy)
    forged_policy = policy.model_copy(update={"producer_source_hash": "f" * 64})
    forged_artifact = artifact.model_copy(
        update={
            "generation_policy": forged_policy,
            "generation_policy_hash": content_hash(forged_policy),
        }
    )

    with pytest.raises(ValueError, match="reconstruction lineage artifact unavailable"):
        verify_schedule(forged_artifact, context)


def test_correction_selection_changes_at_cutoff_and_old_artifact_replays() -> None:
    from drift.domain.sessions import ScheduleArtifactV1
    from drift.markets.session_generation import generate_schedule, verify_schedule
    from drift.serialization.canonical import canonical_json

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5),
        corrected=True,
        record_availability_day=1,
        coverage_availability_day=1,
        methodology_availability_day=1,
        offset_availability_day=1,
    )
    before_query = query.model_copy(update={"knowledge_cutoff": instant(2)})
    after_query = query.model_copy(update={"knowledge_cutoff": instant(3)})

    before = generate_schedule(before_query, context, policy)
    after = generate_schedule(after_query, context, policy)
    source_dataset = next(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == "scheduled_session"
    )

    assert before.classification == "generated"
    assert after.classification == "generated"
    assert before.rows[0].source_version_hash == content_hash(source_dataset.records[0])
    assert after.rows[0].source_version_hash == content_hash(source_dataset.records[1])
    assert before.canonical_output_bytes_hash == after.canonical_output_bytes_hash

    loaded_before = ScheduleArtifactV1.model_validate_json(canonical_json(before))
    assert loaded_before == before
    verify_schedule(loaded_before, context)


def test_historical_methodology_crosses_cutoff_but_modern_capture_does_not() -> None:
    from drift.domain.sessions import TimezoneInputV1
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5),
        record_availability_day=1,
        coverage_availability_day=1,
        methodology_availability_day=3,
        offset_availability_day=1,
    )
    before_query = query.model_copy(update={"knowledge_cutoff": instant(2)})
    after_query = query.model_copy(update={"knowledge_cutoff": instant(3)})

    before = generate_schedule(before_query, context, policy)
    after = generate_schedule(after_query, context, policy)
    timezone_input = TimezoneInputV1.model_validate_json(
        context.supporting_artifacts[policy.timezone_input_hash].data
    )

    assert before.classification == "indeterminate"
    assert before.reasons == ("historical_authority_unavailable_by_cutoff",)
    assert after.classification == "generated"
    assert timezone_input.reconstruction_observed_at > after_query.knowledge_cutoff


@pytest.mark.parametrize("evidence_mode", ("mismatched", "foreign"))
def test_mismatched_or_foreign_offset_evidence_is_indeterminate(
    evidence_mode: str,
) -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5),
        offset_evidence_mode=evidence_mode,  # type: ignore[arg-type]
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "indeterminate"
    assert artifact.rows[0].output.utc_open is None
    assert artifact.rows[0].output.utc_close is None
    assert artifact.reasons == ("historical_authority_availability_unknown",)


@pytest.mark.parametrize("evidence_mode", ("mismatched", "foreign"))
def test_mismatched_or_foreign_methodology_evidence_is_indeterminate(
    evidence_mode: str,
) -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5),
        methodology_evidence_mode=evidence_mode,  # type: ignore[arg-type]
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "indeterminate"
    assert artifact.rows[0].output.utc_open is None
    assert artifact.rows[0].output.utc_close is None
    assert artifact.reasons == ("historical_authority_availability_unknown",)


def test_ambiguous_local_time_requires_fold_and_fold_one_is_exact() -> None:
    from drift.markets.session_generation import generate_schedule

    unknown_context, unknown_query, unknown_policy = generation_case(
        local_date=date(2026, 11, 1),
        local_open_time="01:30:00",
        local_close_time="01:45:00",
    )
    folded_context, folded_query, folded_policy = generation_case(
        local_date=date(2026, 11, 1),
        local_open_time="01:30:00",
        local_close_time="01:45:00",
        open_fold=1,
        close_fold=1,
    )

    unknown = generate_schedule(unknown_query, unknown_context, unknown_policy)
    folded = generate_schedule(folded_query, folded_context, folded_policy)

    assert unknown.classification == "indeterminate"
    assert unknown.reasons == ("ambiguous_local_boundary_requires_fold",)
    assert folded.classification == "generated"
    assert folded.rows[0].output.utc_open == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert folded.rows[0].output.utc_close == datetime(2026, 11, 1, 6, 45, tzinfo=UTC)


def test_nonexistent_local_gap_is_conflict() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 3, 8),
        local_open_time="02:30:00",
        local_close_time="03:30:00",
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "conflict"
    assert artifact.rows[0].output.utc_open is None
    assert artifact.reasons == ("nonexistent_or_invalid_local_boundary",)


def test_wrong_fold_conflicts_with_historical_offset_authority() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 11, 1),
        local_open_time="01:30:00",
        local_close_time="01:45:00",
        open_fold=0,
        close_fold=0,
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "conflict"
    assert artifact.rows[0].output.utc_open is None
    assert artifact.reasons == ("historical_offset_reconstruction_disagreement",)


def test_sparse_unproven_schedule_date_is_indeterminate_not_closed() -> None:
    from drift.markets.session_generation import generate_schedule

    context, query, policy = generation_case(
        local_date=date(2026, 1, 5),
        additional_dates=(date(2026, 1, 7),),
        query_date=date(2026, 1, 6),
        binding_start_date=date(2026, 1, 5),
        binding_end_date=date(2026, 1, 7),
        coverage_start_date=date(2026, 1, 5),
        coverage_end_date=date(2026, 1, 7),
        coverage_status="partial",
    )
    artifact = generate_schedule(query, context, policy)

    assert artifact.classification == "indeterminate"
    assert artifact.rows == ()
    assert artifact.reasons == ("scheduled_session_not_selected",)


def test_changed_producer_lineage_preserves_semantic_output_only() -> None:
    from drift.markets.session_generation import generate_schedule

    first_context, first_query, first_policy = generation_case(
        local_date=date(2026, 1, 5), producer_lineage_variant="producer-a"
    )
    second_context, second_query, second_policy = generation_case(
        local_date=date(2026, 1, 5), producer_lineage_variant="producer-b"
    )
    first = generate_schedule(first_query, first_context, first_policy)
    second = generate_schedule(second_query, second_context, second_policy)

    assert first.classification == second.classification == "generated"
    assert first.rows[0].output == second.rows[0].output
    assert first.canonical_output_bytes_hash == second.canonical_output_bytes_hash
    assert first.generation_policy_hash != second.generation_policy_hash
    assert first.output_row_inventory_hash != second.output_row_inventory_hash


def test_authorized_utc_change_updates_semantic_and_derivation_identity() -> None:
    from drift.markets.session_generation import generate_schedule

    old_context, old_query, old_policy = generation_case(
        local_date=date(2026, 7, 6),
        summer_offset_seconds=-14_400,
        claimed_offset_seconds=-14_400,
    )
    new_context, new_query, new_policy = generation_case(
        local_date=date(2026, 7, 6),
        summer_offset_seconds=-10_800,
        claimed_offset_seconds=-10_800,
    )
    old = generate_schedule(old_query, old_context, old_policy)
    new = generate_schedule(new_query, new_context, new_policy)

    assert old.classification == new.classification == "generated"
    assert old.rows[0].output.utc_open == datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    assert new.rows[0].output.utc_open == datetime(2026, 7, 6, 12, 30, tzinfo=UTC)
    assert old.canonical_output_bytes_hash != new.canonical_output_bytes_hash
    assert old.output_row_inventory_hash != new.output_row_inventory_hash


def test_public_generation_and_replay_need_no_ambient_timezone_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import drift.markets.session_generation as session_generation
    from drift.markets.session_generation import generate_schedule, verify_schedule

    real_zone_info = ZoneInfo

    class RetainedBytesOnlyZoneInfo:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("ambient timezone lookup must not occur")

        @classmethod
        def from_file(
            cls, file_obj: BinaryIO, /, *, key: str | None = None
        ) -> ZoneInfo:
            return real_zone_info.from_file(file_obj, key=key)

    with pytest.raises(AssertionError, match="ambient timezone lookup"):
        RetainedBytesOnlyZoneInfo("Synthetic/Eastern")

    monkeypatch.setattr(session_generation, "ZoneInfo", RetainedBytesOnlyZoneInfo)
    context, query, policy = generation_case(local_date=date(2026, 7, 6))

    artifact = generate_schedule(query, context, policy)
    verify_schedule(artifact, context)

    assert artifact.classification == "generated"
    assert artifact.rows[0].output.utc_open == datetime(2026, 7, 6, 13, 30, tzinfo=UTC)


def test_historical_offset_correction_uses_fresh_context_and_preserves_old_replay() -> (
    None
):
    from drift.markets.session_generation import generate_schedule, verify_schedule

    old_context, old_query, old_policy = generation_case(
        local_date=date(2026, 7, 6),
        summer_offset_seconds=-14_400,
        claimed_offset_seconds=-14_400,
        record_availability_day=1,
        coverage_availability_day=1,
        methodology_availability_day=1,
        offset_availability_day=1,
        knowledge_cutoff=instant(2),
    )
    new_context, new_query, new_policy = generation_case(
        local_date=date(2026, 7, 6),
        summer_offset_seconds=-10_800,
        claimed_offset_seconds=-14_400,
        corrected=True,
        correction_offset_seconds=-10_800,
        record_availability_day=1,
        coverage_availability_day=1,
        methodology_availability_day=1,
        offset_availability_day=1,
        knowledge_cutoff=instant(3),
    )

    old_artifact = generate_schedule(old_query, old_context, old_policy)
    new_artifact = generate_schedule(new_query, new_context, new_policy)

    assert old_artifact.classification == new_artifact.classification == "generated"
    assert old_artifact.rows[0].output.utc_open == datetime(
        2026, 7, 6, 13, 30, tzinfo=UTC
    )
    assert new_artifact.rows[0].output.utc_open == datetime(
        2026, 7, 6, 12, 30, tzinfo=UTC
    )
    assert (
        old_artifact.canonical_output_bytes_hash
        != new_artifact.canonical_output_bytes_hash
    )
    assert (
        old_artifact.output_row_inventory_hash != new_artifact.output_row_inventory_hash
    )

    verify_schedule(old_artifact, old_context)
    verify_schedule(new_artifact, new_context)
    with pytest.raises(ValueError, match="context hash mismatch"):
        verify_schedule(old_artifact, new_context)
