"""Literal exact-byte fixtures for M1d source-observation contract tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
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
    TemporalIntervalClaimV1,
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
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    EffectiveSelector,
    FieldUnit,
    IntervalPolicyV1,
    MethodBranchV1,
    NativeSourceFlagV1,
    ObservationContractV1,
    ObservationCoverageVersionV1,
    ObservationFieldMeaning,
    ObservationFieldMethodV1,
    ObservationInputRecordV1,
    ObservationInventoryEntryV1,
    ObservationSourceKeyV1,
    PopulationRelationshipV1,
    RevisionPolicyV1,
    RowEmissionPolicyV1,
    SourceFieldValueV1,
    TradePopulationV1,
    observation_methodology_for_contract,
)
from drift.domain.revisions import RevisionKind
from drift.domain.securities import ListingVenue
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.markets.observation_validation import (
    OBSERVATION_VALIDATION_PROFILE_ID,
    M1dDatasetInput,
    observation_role_contract,
    observation_role_schema,
    observation_validation_profile_hash,
    observation_validator_implementation_hash,
    validate_observation_dataset,
)
from drift.serialization.canonical import canonical_json, content_hash

RULE_BYTES = canonical_json({"kind": "synthetic-observation-rule", "version": "1"})
RULE_HASH = sha256(RULE_BYTES).hexdigest()


def uid(suffix: int) -> UUID:
    return UUID(f"01990000-0000-7000-8000-{suffix:012d}")


def instant(day: int) -> datetime:
    return datetime(2026, 1, day, 21, tzinfo=UTC)


def reference(suffix: int, digest: str = RULE_HASH) -> ArtifactReference:
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


def availability(day: int = 3) -> AvailabilityEvidenceV1:
    value = instant(day)
    return AvailabilityEvidenceV1(
        channel=public_channel(),
        shape=AvailabilityShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=reference(300 + day),
        rule_derivation=None,
    )


def boundary(day: int) -> TemporalBoundaryClaimV1:
    value = instant(day)
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        source_precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        evidence_reference=reference(400 + day),
    )


def method(
    method_id: str,
    field_name: str,
    meaning: ObservationFieldMeaning,
    selector: EffectiveSelector,
    unit: FieldUnit = "currency_per_share",
) -> ObservationFieldMethodV1:
    return ObservationFieldMethodV1(
        method_id=method_id,
        field_name=field_name,
        meaning=meaning,
        population_id="regular-trades",
        effective_selector=selector,
        ordering="execution_time_then_source_sequence",
        ordering_policy_hash=RULE_HASH,
        precision=12,
        scale=3,
        null_meaning="no_value",
        zero_meaning="numeric_zero",
        fallback_branch_id=None,
        equivalence_evidence_hash=None,
        adjustment_basis="unadjusted",
        basis_methodology_hash=RULE_HASH,
        intraday_basis_homogeneity="homogeneous",
        unit=unit,
    )


def observation_contract() -> tuple[
    ObservationContractV1, dict[str, VerifiedArtifactBytes]
]:
    methods = (
        method("open-v1", "open", "first_trade_price", "first"),
        method("high-v1", "high", "maximum_trade_price", "maximum"),
        method("low-v1", "low", "minimum_trade_price", "minimum"),
        method("close-v1", "close", "last_trade_price", "last"),
        method("volume-v1", "volume", "share_volume", "sum", "shares"),
    )
    values: dict[str, object] = {
        "schema_version": "1",
        "contract_id": uid(1),
        "version": "1",
        "source_id": "synthetic-source",
        "methodology_artifact_hash": "0" * 64,
        "availability": (availability(),),
        "market_population": "consolidated",
        "market_venues": ("XNYS",),
        "populations": (
            TradePopulationV1(
                population_id="regular-trades",
                feed_identity="synthetic-feed",
                feed_version="1",
                venue_scope=("XNYS",),
                session_scope="regular",
                event_time_basis="execution",
                sale_condition_policy_hash=RULE_HASH,
                odd_lot_rule="included",
                opening_auction_rule="included",
                closing_auction_rule="included",
                correction_cancellation_policy_hash=RULE_HASH,
                evidence_hash=RULE_HASH,
            ),
        ),
        "field_methods": methods,
        "method_branches": tuple(
            MethodBranchV1(
                branch_id=f"{item.method_id}-always",
                method_id=item.method_id,
                trigger_kind="always",
                marker_name=None,
                marker_value=None,
            )
            for item in methods
        ),
        "method_equivalences": (),
        "volume_relationships": (
            PopulationRelationshipV1(
                price_population_id="regular-trades",
                volume_population_id="regular-trades",
                relation="equal",
                evidence_hash=RULE_HASH,
            ),
        ),
        "currency": "USD",
        "timestamp_meaning": "exchange_local_session_date",
        "source_label_syntax": "YYYY-MM-DD",
        "source_timezone": "America/New_York",
        "interval_policy": IntervalPolicyV1(
            open_inclusion="included",
            close_inclusion="included",
            auction_event_inclusion="included",
            event_policy_hash=RULE_HASH,
        ),
        "revision_policy": RevisionPolicyV1(
            kind="retained_revision_history",
            correction_horizon="finite",
            correction_duration_seconds=86400,
            policy_hash=RULE_HASH,
        ),
        "row_emission": RowEmissionPolicyV1(
            kind="every_relevant_session", omission_marker_policy_hash=RULE_HASH
        ),
        "adjustment_basis": "unadjusted",
    }
    provisional = ObservationContractV1.model_validate(values)
    methodology_bytes = canonical_json(
        observation_methodology_for_contract(provisional)
    )
    methodology_hash = sha256(methodology_bytes).hexdigest()
    contract = ObservationContractV1.model_validate(
        {**values, "methodology_artifact_hash": methodology_hash}
    )
    contract_bytes = canonical_json(contract)
    contract_hash = sha256(contract_bytes).hexdigest()
    support = {
        RULE_HASH: VerifiedArtifactBytes(
            data=RULE_BYTES, byte_size=len(RULE_BYTES), content_hash=RULE_HASH
        ),
        methodology_hash: VerifiedArtifactBytes(
            data=methodology_bytes,
            byte_size=len(methodology_bytes),
            content_hash=methodology_hash,
        ),
        contract_hash: VerifiedArtifactBytes(
            data=contract_bytes,
            byte_size=len(contract_bytes),
            content_hash=contract_hash,
        ),
    }
    return contract, support


def observation_record(contract_hash: str) -> DailySourceObservationVersionV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": RevisionEnvelopeV1(
            schema_version="1",
            logical_record_id=uid(100),
            record_version_id=uid(101),
            revision_kind=RevisionKind.INITIAL,
            supersedes_record_version_id=None,
            source_sequence=0,
            availability=(availability(),),
            history_completeness=HistoryCompleteness.UNKNOWN,
            source_native_revision_label=None,
            source_artifact=reference(102),
            payload_hash="0" * 64,
        ),
        "source_key": ObservationSourceKeyV1(
            source_id="synthetic-source", native_record_id="record-1"
        ),
        "source_record_locator": "synthetic://record-1",
        "source_record_hash": RULE_HASH,
        "contract_hash": contract_hash,
        "security_id": uid(200),
        "listing_id": uid(201),
        "venue": ListingVenue.XNYS,
        "session_date": date(2026, 1, 2),
        "source_local_label": "2026-01-02",
        "source_timezone": "America/New_York",
        "claimed_interval": TemporalIntervalClaimV1(
            schema_version="1", start=boundary(1), end=boundary(2)
        ),
        "completion_time": boundary(2),
        "fields": tuple(
            SourceFieldValueV1(
                field_name=name,
                method_id=f"{name}-v1",
                native_text=text,
                value=Decimal(text),
                state="value",
                native_flag=None,
            )
            for name, text in (
                ("close", "99.500"),
                ("high", "101.000"),
                ("low", "99.000"),
                ("open", "100.000"),
                ("volume", "1000.000"),
            )
        ),
        "source_flags": (NativeSourceFlagV1(key="source", value="synthetic"),),
        "first_eligible_trade_time": boundary(1),
        "last_eligible_trade_time": boundary(2),
        "activity_claim": "qualifying_price_trade",
        "any_trade_claim": "reported",
    }
    provisional = DailySourceObservationVersionV1.model_construct(
        **values  # type: ignore[arg-type]
    )
    payload_hash = content_hash(assertion_version_payload(provisional))
    revision = values["revision"]
    assert isinstance(revision, RevisionEnvelopeV1)
    values["revision"] = revision.model_copy(update={"payload_hash": payload_hash})
    return DailySourceObservationVersionV1.model_validate(values)


def observation_dataset(
    records: tuple[ObservationInputRecordV1, ...] | None = None,
) -> tuple[M1dDatasetInput, dict[str, VerifiedArtifactBytes]]:
    manifest, artifacts, run, support = observation_validation_inputs(records)
    decision, parsed = validate_observation_dataset(manifest, artifacts, run, support)
    bundle = build_validated_dataset_bundle(
        bundle_id=uid(607),
        bundle_version="1",
        created_at=instant(6),
        validated_datasets=((manifest, decision),),
    )
    return (
        M1dDatasetInput(
            manifest=manifest,
            validation_run=run,
            artifacts=artifacts,
            records=parsed,
            decision=decision,
            bundle=bundle,
        ),
        support,
    )


def observation_validation_inputs(
    records: tuple[ObservationInputRecordV1, ...] | None = None,
) -> tuple[
    DatasetManifestV2,
    dict[str, VerifiedArtifactBytes],
    ValidationRunContextV1,
    dict[str, VerifiedArtifactBytes],
]:
    contract, support = observation_contract()
    contract_hash = content_hash(contract)
    rows = (observation_record(contract_hash),) if records is None else records
    data = canonical_json({"schema_version": "1", "records": rows})
    digest = sha256(data).hexdigest()
    schema = observation_role_schema("source_observation")
    partition_ref = ArtifactReference(
        artifact_id=uid(600),
        kind=ArtifactKind.DATASET,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )
    manifest = DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uid(601),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(
            namespace="drift", name="source_observation", version="1"
        ),
        created_at=instant(5),
        source=SourceDescriptorV1(
            source_id="synthetic-source",
            publisher="Drift",
            product="M1d synthetic fixture",
            evidence_reference=reference(602),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=instant(5),
            collector_id="observation-test-support",
            collector_version="1",
            evidence_reference=reference(603),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=instant(5),
            terms_evidence_reference=reference(604),
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=uid(605),
                partition_key="all",
                artifact=partition_ref,
                byte_size=len(data),
                media_type="application/json",
                format_version="1",
                row_count=len(rows),
                schema_hash=schema.schema_hash,
                coverage=TemporalCoverage(started_at=instant(1), ended_at=instant(5)),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=observation_role_contract(
                "source_observation", (public_channel(),)
            ),
        ),
        lineage=None,
    )
    artifact = VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=digest
    )
    artifacts = {digest: artifact}
    run = ValidationRunContextV1(
        decision_id=uid(606),
        validator_version="1",
        validator_implementation_hash=observation_validator_implementation_hash(),
        validation_profile_id=OBSERVATION_VALIDATION_PROFILE_ID,
        validation_profile_hash=observation_validation_profile_hash(),
        checked_at=instant(6),
    )
    return manifest, artifacts, run, support


def coverage_dataset(
    target: M1dDatasetInput,
    support: dict[str, VerifiedArtifactBytes],
    *,
    inventory_record_hash: str | None = None,
) -> M1dDatasetInput:
    contract_hash = target.records[0].contract_hash
    contract_artifact = support[contract_hash]
    contract = ObservationContractV1.model_validate_json(contract_artifact.data)
    target_record = target.records[0]
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": RevisionEnvelopeV1(
            schema_version="1",
            logical_record_id=uid(700),
            record_version_id=uid(701),
            revision_kind=RevisionKind.INITIAL,
            supersedes_record_version_id=None,
            source_sequence=0,
            availability=(availability(6),),
            history_completeness=HistoryCompleteness.UNKNOWN,
            source_native_revision_label=None,
            source_artifact=reference(702),
            payload_hash="0" * 64,
        ),
        "source_id": "synthetic-source",
        "native_record_id": "coverage-1",
        "contract_hash": contract_hash,
        "venue": ListingVenue.XNYS,
        "listing_id": target_record.listing_id,
        "security_id": target_record.security_id,
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 31),
        "snapshot_identifier": "snapshot-1",
        "snapshot_as_of": boundary(5),
        "covered_dataset_hashes": (manifest_hash(target.manifest),),
        "covered_partition_hashes": tuple(sorted(target.artifacts)),
        "record_inventory": (
            ObservationInventoryEntryV1(
                assertion_id=target_record.revision.logical_record_id,
                version_id=target_record.revision.record_version_id,
                record_hash=inventory_record_hash or content_hash(target_record),
            ),
        ),
        "methodology_artifact_hash": contract.methodology_artifact_hash,
        "omission_rule_hash": contract.row_emission.omission_marker_policy_hash,
        "status": "expected_complete",
        "exception_keys": (),
        "missing_artifact_hashes": (),
        "revision_history_completeness": "complete",
    }
    provisional = ObservationCoverageVersionV1.model_construct(
        **values  # type: ignore[arg-type]
    )
    revision = values["revision"]
    assert isinstance(revision, RevisionEnvelopeV1)
    values["revision"] = revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    record = ObservationCoverageVersionV1.model_validate(values)
    data = canonical_json({"schema_version": "1", "records": (record,)})
    digest = sha256(data).hexdigest()
    schema = observation_role_schema("observation_coverage")
    partition_ref = ArtifactReference(
        artifact_id=uid(703),
        kind=ArtifactKind.DATASET,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )
    manifest = DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uid(704),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(
            namespace="drift", name="observation_coverage", version="1"
        ),
        created_at=instant(6),
        source=SourceDescriptorV1(
            source_id="synthetic-source",
            publisher="Drift",
            product="M1d synthetic fixture",
            evidence_reference=reference(705),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=instant(6),
            collector_id="observation-test-support",
            collector_version="1",
            evidence_reference=reference(706),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=instant(6),
            terms_evidence_reference=reference(707),
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=uid(708),
                partition_key="all",
                artifact=partition_ref,
                byte_size=len(data),
                media_type="application/json",
                format_version="1",
                row_count=1,
                schema_hash=schema.schema_hash,
                coverage=TemporalCoverage(started_at=instant(1), ended_at=instant(6)),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=observation_role_contract(
                "observation_coverage", (public_channel(),)
            ),
        ),
        lineage=None,
    )
    artifact = VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=digest
    )
    artifacts = {digest: artifact}
    run = ValidationRunContextV1(
        decision_id=uid(709),
        validator_version="1",
        validator_implementation_hash=observation_validator_implementation_hash(),
        validation_profile_id=OBSERVATION_VALIDATION_PROFILE_ID,
        validation_profile_hash=observation_validation_profile_hash(),
        checked_at=instant(7),
    )
    decision, parsed = validate_observation_dataset(manifest, artifacts, run, support)
    bundle = build_validated_dataset_bundle(
        bundle_id=uid(710),
        bundle_version="1",
        created_at=instant(7),
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
