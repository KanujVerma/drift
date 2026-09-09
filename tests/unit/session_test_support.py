"""Finite authored exact-byte fixtures for M1d session tests."""

from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from struct import pack
from typing import Literal, cast
from uuid import UUID

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import assertion_version_payload, manifest_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
)
from drift.domain.dataset_validation import ValidationRunContextV1
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    DatasetKind,
    DatasetManifestV2,
    DatasetRoleV1,
    LicenseDescriptorV1,
    PartitionDescriptorV1,
    SourceDescriptorV1,
    TemporalContractBindingV2,
    TemporalContractKindV2,
)
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    m1d_implementation_hash,
)
from drift.domain.revisions import RevisionKind
from drift.domain.sessions import (
    HistoricalBoundaryOffsetV1,
    HistoricalTimezoneMethodologyV1,
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionCoverageVersionV1,
    SessionInputRecordV1,
    SessionInventoryEntryV1,
    SessionKeyV1,
    TimezoneInputV1,
    canonical_session_encoding_contract_hash,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.markets.observation_validation import M1dDatasetInput, M1dResolutionContext
from drift.serialization.canonical import canonical_json, content_hash

AUTHORITY_BYTES = b'{"kind":"synthetic-session-authority","schema_version":"1"}'
AUTHORITY_HASH = sha256(AUTHORITY_BYTES).hexdigest()


def uid(suffix: int) -> UUID:
    return UUID(f"01990000-0000-7000-8000-{suffix:012d}")


def instant(day: int = 2, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def reference(suffix: int, digest: str = AUTHORITY_HASH) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uid(suffix),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def public_channel() -> AvailabilityChannelV1:
    return AvailabilityChannelV1(
        kind=ChannelKind.PUBLIC, identifier="synthetic-public", version="1"
    )


def availability(
    day: int = 2,
    *,
    evidence_digest: str = AUTHORITY_HASH,
    channel: AvailabilityChannelV1 | None = None,
) -> AvailabilityEvidenceV1:
    observed = instant(day)
    return AvailabilityEvidenceV1(
        channel=channel or public_channel(),
        shape=AvailabilityShape.EXACT,
        lower_bound=observed,
        upper_bound=observed,
        precision=SourcePrecision.SECOND,
        source_time_label=observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=reference(100 + day, evidence_digest),
        rule_derivation=None,
    )


def revision(suffix: int = 1, *, availability_day: int = 2) -> RevisionEnvelopeV1:
    return RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=uid(suffix),
        record_version_id=uid(suffix + 1),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(availability(availability_day),),
        history_completeness=HistoryCompleteness.UNKNOWN,
        source_native_revision_label=None,
        source_artifact=reference(suffix + 2),
        payload_hash="0" * 64,
    )


def timezone_bytes(*, summer_offset_seconds: int = -14_400) -> bytes:
    """Return a finite TZif v1 with only the two authored 2026 transitions."""
    transitions = (
        int(datetime(2026, 3, 8, 7, tzinfo=UTC).timestamp()),
        int(datetime(2026, 11, 1, 6, tzinfo=UTC).timestamp()),
    )
    abbreviations = b"EST\0EDT\0"
    header = (
        b"TZif\0"
        + (b"\0" * 15)
        + pack(">6l", 0, 0, 0, len(transitions), 2, len(abbreviations))
    )
    transition_table = b"".join(pack(">l", value) for value in transitions)
    transition_types = bytes((1, 0))
    local_time_types = pack(">lbb", -18_000, 0, 0) + pack(
        ">lbb", summer_offset_seconds, 1, 4
    )
    return (
        header + transition_table + transition_types + local_time_types + abbreviations
    )


def exact_boundary(day: int = 2) -> TemporalBoundaryClaimV1:
    value = instant(day)
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        source_precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        evidence_reference=reference(200 + day),
    )


def boundary_at(value: datetime, suffix: int) -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        source_precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        evidence_reference=reference(suffix),
    )


def date_evidence(value: date, suffix: int) -> TemporalBoundaryClaimV1:
    lower = datetime.combine(value, time(), tzinfo=UTC)
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=lower,
        upper_bound=lower + timedelta(days=1),
        source_precision=SourcePrecision.INTERVAL,
        source_time_label=value.isoformat(),
        source_timezone=None,
        evidence_reference=reference(suffix),
    )


def realized_record(*, suffix: int = 400) -> RealizedSessionVersionV1:
    from drift.domain.assertions import TemporalIntervalClaimV1

    envelope = revision(suffix)
    interrupted_at = datetime(2026, 1, 5, 17, tzinfo=UTC)
    resumed_at = datetime(2026, 1, 5, 17, 15, tzinfo=UTC)
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": envelope,
        "source_id": "calendar-source",
        "session_key": SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 1, 5)
        ),
        "outcome": "opened",
        "actual_open": datetime(2026, 1, 5, 14, 35, tzinfo=UTC),
        "actual_close": datetime(2026, 1, 5, 20, 55, tzinfo=UTC),
        "reported_as_scheduled": "denied",
        "late_open": "asserted",
        "early_close": "asserted",
        "interruption_intervals": (
            TemporalIntervalClaimV1(
                schema_version="1",
                start=boundary_at(interrupted_at, suffix + 10),
                end=boundary_at(resumed_at, suffix + 11),
            ),
        ),
        "interruption_coverage": "partial",
        "source_evidence_hashes": (AUTHORITY_HASH,),
        "methodology_hashes": (AUTHORITY_HASH,),
        "compared_schedule_hash": None,
    }
    provisional = RealizedSessionVersionV1.model_construct(**values)  # type: ignore[arg-type]
    values["revision"] = envelope.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return RealizedSessionVersionV1.model_validate(values)


def source_methodology_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "kind": "historical_timezone_methodology",
        "source_id": "calendar-source",
        "methodology_id": "explicit-offsets",
        "methodology_version": "1",
        "source_timezone_label": "Eastern",
        "timezone_identifier": "Synthetic/Eastern",
        "interpretation": "explicit_boundary_offsets_v1",
    }


def boundary_authority_payload(
    local_date: date,
    boundary: Literal["open", "close"],
    local_label: str,
    offset_seconds: int,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "kind": "historical_boundary_offset",
        "source_id": "calendar-source",
        "mic": "XNYS",
        "local_date": local_date.isoformat(),
        "boundary": boundary,
        "local_label": local_label,
        "timezone_identifier": "Synthetic/Eastern",
        "utc_offset_seconds": offset_seconds,
    }


def session_supporting_artifacts(
    *,
    methodology_availability_day: int = 2,
    methodology_evidence_mode: Literal["normal", "mismatched", "foreign"] = "normal",
) -> tuple[
    str,
    dict[str, VerifiedArtifactBytes],
    dict[str, AvailabilityEvidenceV1],
]:
    support: dict[str, VerifiedArtifactBytes] = {
        AUTHORITY_HASH: VerifiedArtifactBytes(
            data=AUTHORITY_BYTES,
            byte_size=len(AUTHORITY_BYTES),
            content_hash=AUTHORITY_HASH,
        )
    }
    retained: dict[str, AvailabilityEvidenceV1] = {}
    source_bytes = canonical_json(source_methodology_payload())
    source_hash = sha256(source_bytes).hexdigest()
    methodology_channel = (
        AvailabilityChannelV1(
            kind=ChannelKind.PUBLIC,
            identifier="foreign-public",
            version="1",
        )
        if methodology_evidence_mode == "foreign"
        else public_channel()
    )
    source_evidence = availability(
        methodology_availability_day,
        evidence_digest=(
            AUTHORITY_HASH if methodology_evidence_mode == "mismatched" else source_hash
        ),
        channel=methodology_channel,
    )
    source_evidence_hash = content_hash(source_evidence)
    retained[source_evidence_hash] = source_evidence
    support[source_hash] = VerifiedArtifactBytes(
        data=source_bytes, byte_size=len(source_bytes), content_hash=source_hash
    )
    methodology = HistoricalTimezoneMethodologyV1(
        schema_version="1",
        source_id="calendar-source",
        methodology_id="explicit-offsets",
        methodology_version="1",
        source_timezone_label="Eastern",
        timezone_identifier="Synthetic/Eastern",
        interpretation="explicit_boundary_offsets_v1",
        source_methodology_artifact_hash=source_hash,
        source_methodology_availability_evidence_hash=source_evidence_hash,
        canonical_encoding_contract_hash=canonical_session_encoding_contract_hash(),
    )
    methodology_bytes = canonical_json(methodology)
    methodology_hash = sha256(methodology_bytes).hexdigest()
    support[methodology_hash] = VerifiedArtifactBytes(
        data=methodology_bytes,
        byte_size=len(methodology_bytes),
        content_hash=methodology_hash,
    )
    return methodology_hash, support, retained


def schedule_record(
    local_date: date,
    state: Literal["regular", "early_close", "closed", "unknown"],
    methodology_hash: str,
    support: dict[str, VerifiedArtifactBytes],
    retained: dict[str, AvailabilityEvidenceV1],
    *,
    suffix: int,
    offset_seconds: int | None = None,
    authority_known: bool = True,
    record_availability_day: int = 2,
    offset_availability_day: int = 2,
    offset_evidence_mode: Literal["normal", "mismatched", "foreign"] = "normal",
    local_open_time: str = "09:30:00",
    local_close_time: str | None = None,
    open_fold: Literal[0, 1] | None = None,
    close_fold: Literal[0, 1] | None = None,
    predecessor: ScheduledSessionVersionV1 | None = None,
) -> ScheduledSessionVersionV1:
    local_open = None
    local_close = None
    offsets: tuple[HistoricalBoundaryOffsetV1, ...] = ()
    if state in {"regular", "early_close"}:
        local_open = f"{local_date.isoformat()}T{local_open_time}"
        close_time = local_close_time or (
            "13:00:00" if state == "early_close" else "16:00:00"
        )
        local_close = f"{local_date.isoformat()}T{close_time}"
        asserted_offset = (
            offset_seconds
            if offset_seconds is not None
            else (
                -14_400
                if date(2026, 3, 8) <= local_date < date(2026, 11, 1)
                else -18_000
            )
        )
        built: list[HistoricalBoundaryOffsetV1] = []
        for name, label in (("open", local_open), ("close", local_close)):
            boundary_name = cast(Literal["open", "close"], name)
            if not authority_known:
                built.append(
                    HistoricalBoundaryOffsetV1(
                        boundary=boundary_name,
                        utc_offset_seconds=None,
                        methodology_encoding_hash=None,
                        authority_artifact_hash=None,
                        authority_availability_evidence_hash=None,
                    )
                )
                continue
            payload = boundary_authority_payload(
                local_date,
                boundary_name,
                label,
                asserted_offset,
            )
            payload_bytes = canonical_json(payload)
            payload_hash = sha256(payload_bytes).hexdigest()
            offset_channel = (
                AvailabilityChannelV1(
                    kind=ChannelKind.PUBLIC,
                    identifier="foreign-public",
                    version="1",
                )
                if offset_evidence_mode == "foreign"
                else public_channel()
            )
            evidence = availability(
                offset_availability_day,
                evidence_digest=(
                    AUTHORITY_HASH
                    if offset_evidence_mode == "mismatched"
                    else payload_hash
                ),
                channel=offset_channel,
            )
            evidence_hash = content_hash(evidence)
            support[payload_hash] = VerifiedArtifactBytes(
                data=payload_bytes,
                byte_size=len(payload_bytes),
                content_hash=payload_hash,
            )
            retained[evidence_hash] = evidence
            built.append(
                HistoricalBoundaryOffsetV1(
                    boundary=boundary_name,
                    utc_offset_seconds=asserted_offset,
                    methodology_encoding_hash=methodology_hash,
                    authority_artifact_hash=payload_hash,
                    authority_availability_evidence_hash=evidence_hash,
                )
            )
        offsets = tuple(built)
    prior_revision = predecessor.revision if predecessor is not None else None
    envelope = RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=(
            prior_revision.logical_record_id if prior_revision else uid(suffix)
        ),
        record_version_id=uid(suffix + 1),
        revision_kind=(
            RevisionKind.CORRECTION if prior_revision else RevisionKind.INITIAL
        ),
        supersedes_record_version_id=(
            prior_revision.record_version_id if prior_revision else None
        ),
        source_sequence=(prior_revision.source_sequence + 1 if prior_revision else 0),
        availability=(
            availability(
                max(record_availability_day, 3)
                if predecessor
                else record_availability_day
            ),
        ),
        history_completeness=HistoryCompleteness.UNKNOWN,
        source_native_revision_label=None,
        source_artifact=reference(suffix + 2),
        payload_hash="0" * 64,
    )
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": envelope,
        "source_id": "calendar-source",
        "session_key": SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=local_date
        ),
        "source_temporal_evidence": date_evidence(local_date, suffix + 3),
        "state": state,
        "local_open": local_open,
        "local_close": local_close,
        "timezone_identifier": "Synthetic/Eastern",
        "open_fold": open_fold,
        "close_fold": close_fold,
        "historical_boundary_offsets": offsets,
        "source_methodology_hash": methodology_hash,
    }
    provisional = ScheduledSessionVersionV1.model_construct(**values)  # type: ignore[arg-type]
    values["revision"] = envelope.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return ScheduledSessionVersionV1.model_validate(values)


def session_dataset(
    role: Literal["scheduled_session", "realized_session", "session_coverage"],
    records: tuple[SessionInputRecordV1, ...],
    support: dict[str, VerifiedArtifactBytes],
) -> M1dDatasetInput[SessionInputRecordV1]:
    from drift.markets.session_validation import (
        SESSION_VALIDATION_PROFILE_ID,
        session_role_contract,
        session_role_schema,
        session_validation_profile_hash,
        session_validator_implementation_hash,
        validate_session_dataset,
    )

    data = canonical_json({"schema_version": "1", "records": records})
    digest = sha256(data).hexdigest()
    schema = session_role_schema(role)
    artifact_reference = ArtifactReference(
        artifact_id=uid(800 + len(records)),
        kind=ArtifactKind.DATASET,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )
    manifest = DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uid(810 + len(records)),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(namespace="drift", name=role, version="1"),
        created_at=instant(5),
        source=SourceDescriptorV1(
            source_id="calendar-source",
            publisher="Drift",
            product="M1d synthetic fixture",
            evidence_reference=reference(820),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=instant(5),
            collector_id="session-test-support",
            collector_version="1",
            evidence_reference=reference(821),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=instant(5),
            terms_evidence_reference=reference(822),
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=uid(823),
                partition_key="all",
                artifact=artifact_reference,
                byte_size=len(data),
                media_type="application/json",
                format_version="1",
                row_count=len(records),
                schema_hash=schema.schema_hash,
                coverage=TemporalCoverage(started_at=instant(1), ended_at=instant(5)),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=session_role_contract(role, (public_channel(),)),
        ),
        lineage=None,
    )
    artifacts = {
        digest: VerifiedArtifactBytes(
            data=data, byte_size=len(data), content_hash=digest
        )
    }
    run = ValidationRunContextV1(
        decision_id=uid(824),
        validator_version="1",
        validator_implementation_hash=session_validator_implementation_hash(),
        validation_profile_id=SESSION_VALIDATION_PROFILE_ID,
        validation_profile_hash=session_validation_profile_hash(),
        checked_at=instant(6),
    )
    decision, parsed = validate_session_dataset(manifest, artifacts, run, support)
    bundle = build_validated_dataset_bundle(
        bundle_id=uid(825),
        bundle_version="1",
        created_at=instant(6),
        validated_datasets=((manifest, decision),),
    )
    return M1dDatasetInput(
        manifest=manifest,
        validation_run=run,
        artifacts=artifacts,
        records=parsed,
        decision=decision,
        bundle=bundle,
    )


def coverage_record(
    target: M1dDatasetInput[SessionInputRecordV1],
    methodology_hash: str,
    *,
    suffix: int = 500,
    inventory_record_hash: str | None = None,
    availability_day: int = 2,
    start_date: date | None = None,
    end_date: date | None = None,
    status: Literal["expected_complete", "not_expected", "partial", "unknown"] = (
        "expected_complete"
    ),
) -> SessionCoverageVersionV1:
    records = tuple(
        item for item in target.records if isinstance(item, ScheduledSessionVersionV1)
    )
    dates = tuple(item.session_key.local_date for item in records)
    envelope = revision(suffix, availability_day=availability_day)
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": envelope,
        "source_id": "calendar-source",
        "native_record_id": "coverage-1",
        "mic": "XNYS",
        "session_scope": "regular",
        "start_date": start_date or min(dates),
        "end_date": end_date or max(dates),
        "snapshot_identifier": "snapshot-1",
        "snapshot_as_of": exact_boundary(5),
        "covered_dataset_hashes": (manifest_hash(target.manifest),),
        "covered_partition_hashes": tuple(sorted(target.artifacts)),
        "record_inventory": tuple(
            SessionInventoryEntryV1(
                assertion_id=item.revision.logical_record_id,
                version_id=item.revision.record_version_id,
                record_hash=(
                    inventory_record_hash
                    if inventory_record_hash is not None and index == 0
                    else content_hash(item)
                ),
            )
            for index, item in enumerate(records)
        ),
        "expected_daily_cardinality": 1,
        "exception_dates": (),
        "methodology_hash": methodology_hash,
        "status": status,
        "missing_artifact_hashes": (),
        "revision_history_completeness": "complete",
    }
    provisional = SessionCoverageVersionV1.model_construct(**values)  # type: ignore[arg-type]
    values["revision"] = envelope.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return SessionCoverageVersionV1.model_validate(values)


def generation_case(
    *,
    local_date: date = date(2026, 1, 5),
    state: Literal["regular", "early_close", "closed", "unknown"] = "regular",
    summer_offset_seconds: int = -14_400,
    claimed_offset_seconds: int | None = None,
    authority_known: bool = True,
    corrected: bool = False,
    correction_offset_seconds: int | None = None,
    additional_dates: tuple[date, ...] = (),
    bad_coverage_hash: bool = False,
    binding_methodology_hash: str | None = None,
    record_availability_day: int = 2,
    coverage_availability_day: int = 2,
    methodology_availability_day: int = 2,
    offset_availability_day: int = 2,
    methodology_evidence_mode: Literal["normal", "mismatched", "foreign"] = "normal",
    offset_evidence_mode: Literal["normal", "mismatched", "foreign"] = "normal",
    local_open_time: str = "09:30:00",
    local_close_time: str | None = None,
    open_fold: Literal[0, 1] | None = None,
    close_fold: Literal[0, 1] | None = None,
    knowledge_cutoff: datetime | None = None,
    query_date: date | None = None,
    binding_start_date: date | None = None,
    binding_end_date: date | None = None,
    coverage_start_date: date | None = None,
    coverage_end_date: date | None = None,
    coverage_status: Literal[
        "expected_complete", "not_expected", "partial", "unknown"
    ] = "expected_complete",
    producer_lineage_variant: str = "base",
) -> tuple[
    M1dResolutionContext, ObservationDecisionQueryV1, ScheduleGenerationPolicyV1
]:
    from drift.domain.observation_query import (
        ObservationDecisionQueryV1,
        ObservationSourceBindingV1,
        ObservationSourceSelectionPolicyV1,
    )
    from drift.domain.securities import ListingVenue
    from drift.domain.temporal import AvailabilityPolicyV1
    from drift.markets.observation_validation import (
        M1dResolutionContext,
        m1d_context_hash,
    )
    from drift.markets.session_generation import schedule_generation_algorithm_hash

    methodology_hash, support, retained = session_supporting_artifacts(
        methodology_availability_day=methodology_availability_day,
        methodology_evidence_mode=methodology_evidence_mode,
    )
    initial = schedule_record(
        local_date,
        state,
        methodology_hash,
        support,
        retained,
        suffix=600,
        offset_seconds=claimed_offset_seconds,
        authority_known=authority_known,
        record_availability_day=record_availability_day,
        offset_availability_day=offset_availability_day,
        offset_evidence_mode=offset_evidence_mode,
        local_open_time=local_open_time,
        local_close_time=local_close_time,
        open_fold=open_fold,
        close_fold=close_fold,
    )
    records: tuple[ScheduledSessionVersionV1, ...] = (initial,)
    if corrected:
        correction = schedule_record(
            local_date,
            state,
            methodology_hash,
            support,
            retained,
            suffix=610,
            offset_seconds=(
                correction_offset_seconds
                if correction_offset_seconds is not None
                else claimed_offset_seconds
            ),
            authority_known=authority_known,
            record_availability_day=record_availability_day,
            offset_availability_day=offset_availability_day,
            offset_evidence_mode=offset_evidence_mode,
            local_open_time=local_open_time,
            local_close_time=local_close_time,
            open_fold=open_fold,
            close_fold=close_fold,
            predecessor=initial,
        )
        records = (initial, correction)
    for index, additional_date in enumerate(additional_dates):
        records = (
            *records,
            schedule_record(
                additional_date,
                state,
                methodology_hash,
                support,
                retained,
                suffix=630 + (index * 10),
                offset_seconds=claimed_offset_seconds,
                authority_known=authority_known,
                record_availability_day=record_availability_day,
                offset_availability_day=offset_availability_day,
                offset_evidence_mode=offset_evidence_mode,
            ),
        )
    scheduled = session_dataset("scheduled_session", records, support)
    coverage = coverage_record(
        scheduled,
        methodology_hash,
        inventory_record_hash=("a" * 64 if bad_coverage_hash else None),
        availability_day=coverage_availability_day,
        start_date=coverage_start_date,
        end_date=coverage_end_date,
        status=coverage_status,
    )
    coverage_dataset_input = session_dataset("session_coverage", (coverage,), support)

    tzif = timezone_bytes(summer_offset_seconds=summer_offset_seconds)
    tzif_hash = sha256(tzif).hexdigest()
    support[tzif_hash] = VerifiedArtifactBytes(
        data=tzif, byte_size=len(tzif), content_hash=tzif_hash
    )
    timezone_input = TimezoneInputV1(
        schema_version="1",
        timezone_identifier="Synthetic/Eastern",
        tzif_sha256=tzif_hash,
        tzdb_release="synthetic",
        artifact_hash=tzif_hash,
        reconstruction_observed_at=datetime(2027, 1, 1, tzinfo=UTC),
        canonical_encoding_contract_hash=canonical_session_encoding_contract_hash(),
    )
    timezone_input_bytes = canonical_json(timezone_input)
    timezone_input_hash = sha256(timezone_input_bytes).hexdigest()
    support[timezone_input_hash] = VerifiedArtifactBytes(
        data=timezone_input_bytes,
        byte_size=len(timezone_input_bytes),
        content_hash=timezone_input_hash,
    )
    lineage_hashes: dict[str, str] = {}
    for name in ("producer_source", "producer_package", "lockfile"):
        lineage_bytes = canonical_json(
            {
                "kind": f"synthetic-{name}",
                "schema_version": "1",
                "variant": producer_lineage_variant,
            }
        )
        lineage_hash = sha256(lineage_bytes).hexdigest()
        support[lineage_hash] = VerifiedArtifactBytes(
            data=lineage_bytes,
            byte_size=len(lineage_bytes),
            content_hash=lineage_hash,
        )
        lineage_hashes[name] = lineage_hash
    listing_id = uid(900)
    binding_start = binding_start_date or local_date
    binding_end = binding_end_date or local_date
    bindings = (
        ObservationSourceBindingV1(
            dataset_role="scheduled_session",
            source_id="calendar-source",
            contract_hash=None,
            venue=ListingVenue.XNYS,
            listing_id=listing_id,
            start_date=binding_start,
            end_date=binding_end,
            manifest_hashes=(manifest_hash(scheduled.manifest),),
            methodology_hashes=(binding_methodology_hash or methodology_hash,),
        ),
        ObservationSourceBindingV1(
            dataset_role="session_coverage",
            source_id="calendar-source",
            contract_hash=None,
            venue=ListingVenue.XNYS,
            listing_id=listing_id,
            start_date=binding_start,
            end_date=binding_end,
            manifest_hashes=(manifest_hash(coverage_dataset_input.manifest),),
            methodology_hashes=(binding_methodology_hash or methodology_hash,),
        ),
    )
    source_policy = ObservationSourceSelectionPolicyV1(
        policy_id="session-authority", version="1", bindings=bindings
    )
    source_policy_bytes = canonical_json(source_policy)
    source_policy_hash = sha256(source_policy_bytes).hexdigest()
    support[source_policy_hash] = VerifiedArtifactBytes(
        data=source_policy_bytes,
        byte_size=len(source_policy_bytes),
        content_hash=source_policy_hash,
    )
    availability_policy = AvailabilityPolicyV1(
        policy_id="public-exact", permitted_rule_hashes=()
    )
    availability_policy_hash = content_hash(availability_policy)
    context = M1dResolutionContext(
        observation_datasets=(),
        session_datasets=(scheduled, coverage_dataset_input),
        availability_policies={availability_policy_hash: availability_policy},
        retained_evidence=retained,
        supporting_artifacts=support,
    )
    query = ObservationDecisionQueryV1(
        schema_version="1",
        kind="decision",
        decision_time=datetime(2026, 12, 2, tzinfo=UTC),
        knowledge_cutoff=knowledge_cutoff or datetime(2026, 12, 1, tzinfo=UTC),
        effective_cutoff=datetime(2026, 12, 1, tzinfo=UTC),
        listing_id=listing_id,
        security_id=uid(901),
        venue=ListingVenue.XNYS,
        session_date=query_date or local_date,
        source_id="bar-source",
        contract_hash="9" * 64,
        source_selection_policy_hash=source_policy_hash,
        profile_hash="8" * 64,
        requested_channel=public_channel(),
        availability_policy_id="public-exact",
        availability_policy_hash=availability_policy_hash,
        input_context_hash=m1d_context_hash(context),
    )
    policy = ScheduleGenerationPolicyV1(
        schema_version="1",
        algorithm="explicit_local_rows_to_utc_v1",
        semantic_algorithm_hash=schedule_generation_algorithm_hash(),
        producer_name="drift",
        producer_version="1",
        producer_source_hash=lineage_hashes["producer_source"],
        producer_package_hash=lineage_hashes["producer_package"],
        implementation_hash=m1d_implementation_hash(),
        python_identity="cpython-synthetic",
        lockfile_hash=lineage_hashes["lockfile"],
        timezone_input_hash=timezone_input_hash,
        canonical_encoding_contract_hash=canonical_session_encoding_contract_hash(),
        historical_timezone_methodology_encoding_hashes=tuple(
            sorted(
                {
                    item.methodology_encoding_hash
                    for item in records[-1].historical_boundary_offsets
                    if item.methodology_encoding_hash is not None
                }
            )
        ),
    )
    return context, query, policy


def dataset_with_unique_nested_reference(
    role: Literal[
        "scheduled_session",
        "scheduled_revision",
        "realized_session",
        "session_coverage",
    ],
) -> tuple[
    M1dDatasetInput[SessionInputRecordV1],
    dict[str, VerifiedArtifactBytes],
    str,
]:
    methodology_hash, support, retained = session_supporting_artifacts()
    nested_bytes = canonical_json({"kind": f"{role}-nested-reference"})
    nested_hash = sha256(nested_bytes).hexdigest()
    support[nested_hash] = VerifiedArtifactBytes(
        data=nested_bytes,
        byte_size=len(nested_bytes),
        content_hash=nested_hash,
    )
    nested_reference = reference(990, nested_hash)
    dataset_role: Literal["scheduled_session", "realized_session", "session_coverage"]
    if role in {"scheduled_session", "scheduled_revision"}:
        dataset_role = "scheduled_session"
        record: SessionInputRecordV1 = schedule_record(
            date(2026, 1, 5),
            "regular",
            methodology_hash,
            support,
            retained,
            suffix=920,
        )
        assert isinstance(record, ScheduledSessionVersionV1)
        if role == "scheduled_revision":
            revision_value = record.revision.model_copy(
                update={
                    "availability": (
                        record.revision.availability[0].model_copy(
                            update={"evidence_reference": nested_reference}
                        ),
                    )
                }
            )
            record = _reseal_session_record(record, revision=revision_value)
        else:
            record = _reseal_session_record(
                record,
                source_temporal_evidence=record.source_temporal_evidence.model_copy(
                    update={"evidence_reference": nested_reference}
                ),
            )
    elif role == "realized_session":
        dataset_role = "realized_session"
        record = realized_record(suffix=930)
        assert isinstance(record, RealizedSessionVersionV1)
        interruption = record.interruption_intervals[0]
        record = _reseal_session_record(
            record,
            interruption_intervals=(
                interruption.model_copy(
                    update={
                        "start": interruption.start.model_copy(
                            update={"evidence_reference": nested_reference}
                        )
                    }
                ),
            ),
        )
    else:
        dataset_role = "session_coverage"
        scheduled = session_dataset(
            "scheduled_session",
            (
                schedule_record(
                    date(2026, 1, 5),
                    "regular",
                    methodology_hash,
                    support,
                    retained,
                    suffix=940,
                ),
            ),
            support,
        )
        record = coverage_record(scheduled, methodology_hash, suffix=950)
        record = _reseal_session_record(
            record,
            snapshot_as_of=record.snapshot_as_of.model_copy(
                update={"evidence_reference": nested_reference}
            ),
        )
    return session_dataset(dataset_role, (record,), support), support, nested_hash


def _reseal_session_record(
    record: SessionInputRecordV1, **updates: object
) -> SessionInputRecordV1:
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values.update(updates)
    supplied_revision = values["revision"]
    assert isinstance(supplied_revision, RevisionEnvelopeV1)
    revision_value = supplied_revision.model_copy(update={"payload_hash": "0" * 64})
    values["revision"] = revision_value
    provisional = type(record).model_construct(**values)
    values["revision"] = revision_value.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return type(record).model_validate(values)
