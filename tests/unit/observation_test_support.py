"""Literal exact-byte fixtures for M1d source-observation contract tests."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal
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
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    ObservationOutcomeQueryV1,
    ObservationQueryV1,
    ObservationSourceBindingV1,
    ObservationSourceSelectionPolicyV1,
)
from drift.domain.observation_usability import (
    InterruptionAggregationPolicyV1,
    ObservationAssessmentResultV1,
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
    RuleDisposition,
    SourceFieldValueV1,
    TradePopulationV1,
    observation_methodology_for_contract,
    regular_session_trade_bar_profile_hash,
)
from drift.domain.revisions import RevisionKind
from drift.domain.securities import ListingVenue
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.markets.observation_validation import (
    OBSERVATION_VALIDATION_PROFILE_ID,
    M1dDatasetInput,
    M1dResolutionContext,
    m1d_context_hash,
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


def market_uid(suffix: int) -> UUID:
    """Match the immutable M1b synthetic identity namespace."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


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
    population_id: str = "regular-trades",
) -> ObservationFieldMethodV1:
    return ObservationFieldMethodV1(
        method_id=method_id,
        field_name=field_name,
        meaning=meaning,
        population_id=population_id,
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


def observation_contract(
    *,
    auction_event_inclusion: RuleDisposition = "included",
    used_population_rules: RuleDisposition = "included",
) -> tuple[ObservationContractV1, dict[str, VerifiedArtifactBytes]]:
    population_id = (
        "regular-trades"
        if used_population_rules == "included"
        else "z-field-used-trades"
    )
    methods = (
        method(
            "open-v1", "open", "first_trade_price", "first", population_id=population_id
        ),
        method(
            "high-v1",
            "high",
            "maximum_trade_price",
            "maximum",
            population_id=population_id,
        ),
        method(
            "low-v1",
            "low",
            "minimum_trade_price",
            "minimum",
            population_id=population_id,
        ),
        method(
            "close-v1", "close", "last_trade_price", "last", population_id=population_id
        ),
        method("volume-v1", "volume", "share_volume", "sum", "shares", population_id),
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
            *(
                (
                    TradePopulationV1(
                        population_id="a-unused-decoy",
                        feed_identity="synthetic-decoy-feed",
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
                )
                if used_population_rules != "included"
                else ()
            ),
            TradePopulationV1(
                population_id=population_id,
                feed_identity="synthetic-feed",
                feed_version="1",
                venue_scope=("XNYS",),
                session_scope="regular",
                event_time_basis="execution",
                sale_condition_policy_hash=RULE_HASH,
                odd_lot_rule="included",
                opening_auction_rule=used_population_rules,
                closing_auction_rule=used_population_rules,
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
                price_population_id=population_id,
                volume_population_id=population_id,
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
            auction_event_inclusion=auction_event_inclusion,
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
    contract_input: tuple[ObservationContractV1, dict[str, VerifiedArtifactBytes]]
    | None = None,
) -> tuple[
    DatasetManifestV2,
    dict[str, VerifiedArtifactBytes],
    ValidationRunContextV1,
    dict[str, VerifiedArtifactBytes],
]:
    contract, support = contract_input or observation_contract()
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
    status: Literal["expected_complete", "not_expected", "partial", "unknown"] = (
        "expected_complete"
    ),
    revision_history_completeness: Literal[
        "complete", "current_only", "unknown"
    ] = "complete",
    snapshot_as_of: TemporalBoundaryClaimV1 | None = None,
    snapshot_availability: AvailabilityEvidenceV1 | None = None,
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
            availability=(snapshot_availability or availability(6),),
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
        "snapshot_as_of": snapshot_as_of or boundary(5),
        "covered_dataset_hashes": (manifest_hash(target.manifest),),
        "covered_partition_hashes": tuple(sorted(target.artifacts)),
        "record_inventory": tuple(
            ObservationInventoryEntryV1(
                assertion_id=record.revision.logical_record_id,
                version_id=record.revision.record_version_id,
                record_hash=(
                    inventory_record_hash
                    if inventory_record_hash is not None and index == 0
                    else content_hash(record)
                ),
            )
            for index, record in enumerate(target.records)
        ),
        "methodology_artifact_hash": contract.methodology_artifact_hash,
        "omission_rule_hash": contract.row_emission.omission_marker_policy_hash,
        "status": status,
        "exception_keys": (),
        "missing_artifact_hashes": (),
        "revision_history_completeness": revision_history_completeness,
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


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _evidence_at(
    value: datetime, suffix: int, *, evidence_digest: str = RULE_HASH
) -> AvailabilityEvidenceV1:
    return AvailabilityEvidenceV1(
        channel=public_channel(),
        shape=AvailabilityShape.EXACT,
        lower_bound=value,
        upper_bound=value,
        precision=SourcePrecision.SECOND,
        source_time_label=value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=reference(suffix, evidence_digest),
        rule_derivation=None,
    )


def _boundary_at(value: datetime, suffix: int) -> TemporalBoundaryClaimV1:
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


class ObservationHarness:
    """Immutable-context fixture for finite observation selection."""

    def __init__(
        self,
        *,
        session_date: date = date(2026, 1, 5),
        close: str = "100.000",
        available_at: str = "2026-01-05T21:30:00Z",
        auction_event_inclusion: RuleDisposition = "included",
        used_population_rules: RuleDisposition = "included",
        assessment_ready: bool = False,
    ) -> None:
        self.session_date = session_date
        self.security_id = market_uid(200)
        self.listing_id = market_uid(201)
        self.issuer_id = market_uid(202)
        self._assessment_ready = False
        self._default_lifecycle_case = "active"
        self._contract, self._contract_support = observation_contract(
            auction_event_inclusion=auction_event_inclusion,
            used_population_rules=used_population_rules,
        )
        self._record_support: dict[str, VerifiedArtifactBytes] = {}
        self._coverage_status: Literal[
            "expected_complete", "not_expected", "partial", "unknown"
        ] = "expected_complete"
        self._coverage_revision_history: Literal[
            "complete", "current_only", "unknown"
        ] = "complete"
        self._coverage_snapshot: TemporalBoundaryClaimV1 | None = None
        self._coverage_snapshot_availability: AvailabilityEvidenceV1 | None = None
        self._include_coverage = True
        self._records: tuple[DailySourceObservationVersionV1, ...] = (
            self._record(
                close=close,
                available_at=_parse_instant(available_at),
                suffix=1000,
                predecessor=None,
            ),
        )
        self._rebuild()
        self._assessment_ready = assessment_ready
        if assessment_ready:
            self.attach_sessions(interruption_coverage="complete")
            self.attach_m1b()

    def _record(
        self,
        *,
        close: str,
        available_at: datetime,
        suffix: int,
        predecessor: DailySourceObservationVersionV1 | None,
        record_date: date | None = None,
    ) -> DailySourceObservationVersionV1:
        effective_date = self.session_date if record_date is None else record_date
        midnight = datetime.combine(effective_date, datetime.min.time(), tzinfo=UTC)
        session_open = midnight.replace(hour=14, minute=35)
        session_close = midnight.replace(hour=20, minute=55)
        source_bytes = canonical_json(
            {
                "kind": "synthetic-source-observation",
                "schema_version": "1",
                "native_record_id": "record-1",
                "source_sequence": (
                    0
                    if predecessor is None
                    else predecessor.revision.source_sequence + 1
                ),
                "close": close,
            }
        )
        source_hash = sha256(source_bytes).hexdigest()
        self._record_support[source_hash] = VerifiedArtifactBytes(
            data=source_bytes,
            byte_size=len(source_bytes),
            content_hash=source_hash,
        )
        prior_revision = predecessor.revision if predecessor is not None else None
        revision = RevisionEnvelopeV1(
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
            source_sequence=(
                prior_revision.source_sequence + 1 if prior_revision else 0
            ),
            availability=(_evidence_at(available_at, suffix + 2),),
            history_completeness=HistoryCompleteness.UNKNOWN,
            source_native_revision_label=None,
            source_artifact=reference(suffix + 3, source_hash),
            payload_hash="0" * 64,
        )
        values: dict[str, object] = {
            "schema_version": "1",
            "revision": revision,
            "source_key": ObservationSourceKeyV1(
                source_id="synthetic-source", native_record_id="record-1"
            ),
            "source_record_locator": f"synthetic://record-1/{suffix}",
            "source_record_hash": source_hash,
            "contract_hash": content_hash(self._contract),
            "security_id": self.security_id,
            "listing_id": self.listing_id,
            "venue": ListingVenue.XNYS,
            "session_date": effective_date,
            "source_local_label": effective_date.isoformat(),
            "source_timezone": "America/New_York",
            "claimed_interval": TemporalIntervalClaimV1(
                schema_version="1",
                start=_boundary_at(session_open, suffix + 4),
                end=_boundary_at(session_close, suffix + 5),
            ),
            "completion_time": _boundary_at(session_close, suffix + 6),
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
                    ("close", close),
                    ("high", "101.000"),
                    ("low", "99.000"),
                    ("open", "100.000"),
                    ("volume", "1000.000"),
                )
            ),
            "source_flags": (NativeSourceFlagV1(key="source", value="synthetic"),),
            "first_eligible_trade_time": _boundary_at(session_open, suffix + 7),
            "last_eligible_trade_time": _boundary_at(session_close, suffix + 8),
            "activity_claim": "qualifying_price_trade",
            "any_trade_claim": "reported",
        }
        provisional = DailySourceObservationVersionV1.model_construct(
            **values  # type: ignore[arg-type]
        )
        values["revision"] = revision.model_copy(
            update={
                "payload_hash": content_hash(assertion_version_payload(provisional))
            }
        )
        return DailySourceObservationVersionV1.model_validate(values)

    def _rebuild(self) -> None:
        manifest, artifacts, run, support = observation_validation_inputs(
            self._records,
            (
                self._contract,
                {**self._contract_support, **self._record_support},
            ),
        )
        decision, parsed = validate_observation_dataset(
            manifest, artifacts, run, support
        )
        source = M1dDatasetInput(
            manifest=manifest,
            validation_run=run,
            artifacts=artifacts,
            records=parsed,
            decision=decision,
            bundle=build_validated_dataset_bundle(
                bundle_id=uid(1200),
                bundle_version="1",
                created_at=instant(9),
                validated_datasets=((manifest, decision),),
            ),
        )
        coverage = (
            coverage_dataset(
                source,
                support,
                status=self._coverage_status,
                revision_history_completeness=self._coverage_revision_history,
                snapshot_as_of=self._coverage_snapshot,
                snapshot_availability=self._coverage_snapshot_availability,
            )
            if source.records and self._include_coverage
            else None
        )
        bindings = (
            ObservationSourceBindingV1(
                dataset_role="source_observation",
                source_id="synthetic-source",
                contract_hash=content_hash(self._contract),
                venue=ListingVenue.XNYS,
                listing_id=self.listing_id,
                start_date=self.session_date,
                end_date=self.session_date,
                manifest_hashes=(manifest_hash(source.manifest),),
                methodology_hashes=(self._contract.methodology_artifact_hash,),
            ),
            *(
                (
                    ObservationSourceBindingV1(
                        dataset_role="observation_coverage",
                        source_id="synthetic-source",
                        contract_hash=content_hash(self._contract),
                        venue=ListingVenue.XNYS,
                        listing_id=self.listing_id,
                        start_date=self.session_date,
                        end_date=self.session_date,
                        manifest_hashes=(manifest_hash(coverage.manifest),),
                        methodology_hashes=(self._contract.methodology_artifact_hash,),
                    ),
                )
                if coverage is not None
                else ()
            ),
        )
        policy = ObservationSourceSelectionPolicyV1(
            policy_id="synthetic-observation-authority",
            version="1",
            bindings=bindings,
        )
        policy_bytes = canonical_json(policy)
        policy_hash = sha256(policy_bytes).hexdigest()
        support[policy_hash] = VerifiedArtifactBytes(
            data=policy_bytes,
            byte_size=len(policy_bytes),
            content_hash=policy_hash,
        )
        availability_policy = AvailabilityPolicyV1(
            policy_id="public-exact", permitted_rule_hashes=()
        )
        availability_policy_hash = content_hash(availability_policy)
        self._source_policy_hash = policy_hash
        self._observation_bindings = bindings
        self._current_bindings = bindings
        self.context = M1dResolutionContext(
            observation_datasets=(
                source,
                *((coverage,) if coverage is not None else ()),
            ),
            availability_policies={availability_policy_hash: availability_policy},
            retained_evidence={},
            supporting_artifacts=support,
        )
        self._availability_policy_hash = availability_policy_hash
        if self._assessment_ready:
            self.attach_sessions(interruption_coverage="complete")
            self.attach_m1b(self._default_lifecycle_case)

    def decision(
        self,
        decision_time: str,
        knowledge_cutoff: str,
        effective_cutoff: str,
        session_date: str,
    ) -> ObservationDecisionQueryV1:
        return ObservationDecisionQueryV1(
            kind="decision",
            decision_time=_parse_instant(decision_time),
            knowledge_cutoff=_parse_instant(knowledge_cutoff),
            effective_cutoff=_parse_instant(effective_cutoff),
            listing_id=self.listing_id,
            security_id=self.security_id,
            venue=ListingVenue.XNYS,
            session_date=date.fromisoformat(session_date),
            source_id="synthetic-source",
            contract_hash=content_hash(self._contract),
            source_selection_policy_hash=self._source_policy_hash,
            profile_hash=regular_session_trade_bar_profile_hash(),
            requested_channel=public_channel(),
            availability_policy_id="public-exact",
            availability_policy_hash=self._availability_policy_hash,
            input_context_hash=m1d_context_hash(self.context),
        )

    def outcome(
        self,
        economic_horizon: str,
        evidence_vintage_cutoff: str,
        session_date: str,
    ) -> ObservationOutcomeQueryV1:
        return ObservationOutcomeQueryV1(
            kind="outcome",
            economic_horizon=_parse_instant(economic_horizon),
            evidence_vintage_cutoff=_parse_instant(evidence_vintage_cutoff),
            listing_id=self.listing_id,
            security_id=self.security_id,
            venue=ListingVenue.XNYS,
            session_date=date.fromisoformat(session_date),
            source_id="synthetic-source",
            contract_hash=content_hash(self._contract),
            source_selection_policy_hash=self._source_policy_hash,
            profile_hash=regular_session_trade_bar_profile_hash(),
            requested_channel=public_channel(),
            availability_policy_id="public-exact",
            availability_policy_hash=self._availability_policy_hash,
            input_context_hash=m1d_context_hash(self.context),
        )

    def replace_source_revision(self, *, close: str, available_at: str) -> None:
        self._records = (
            *self._records,
            self._record(
                close=close,
                available_at=_parse_instant(available_at),
                suffix=1100 + len(self._records) * 10,
                predecessor=self._records[-1],
            ),
        )
        self._rebuild()

    def use_empty_source_inventory(self) -> None:
        self._records = ()
        self._rebuild()

    def use_unproven_observation_coverage(
        self, *, mode: Literal["absent", "partial"]
    ) -> None:
        self._include_coverage = mode != "absent"
        self._coverage_status = "partial" if mode == "partial" else "expected_complete"
        self._rebuild()

    def use_wrong_contract_policy(self) -> None:
        bindings = tuple(
            item.model_copy(update={"contract_hash": "f" * 64})
            if item.dataset_role == "source_observation"
            else item
            for item in self._observation_bindings
        )
        policy = ObservationSourceSelectionPolicyV1(
            policy_id="wrong-observation-contract-authority",
            version="1",
            bindings=bindings,
        )
        policy_bytes = canonical_json(policy)
        policy_hash = sha256(policy_bytes).hexdigest()
        support = dict(self.context.supporting_artifacts)
        support[policy_hash] = VerifiedArtifactBytes(
            data=policy_bytes,
            byte_size=len(policy_bytes),
            content_hash=policy_hash,
        )
        self._source_policy_hash = policy_hash
        self.context = M1dResolutionContext(
            observation_datasets=self.context.observation_datasets,
            session_datasets=self.context.session_datasets,
            availability_policies=self.context.availability_policies,
            retained_evidence=self.context.retained_evidence,
            supporting_artifacts=support,
            structural_context=self.context.structural_context,
            research_definition=self.context.research_definition,
            issuer_id=self.context.issuer_id,
            structural_methodology_id=self.context.structural_methodology_id,
            m1b_requested_channel=self.context.m1b_requested_channel,
            schedule_generation_policy_hash=(
                self.context.schedule_generation_policy_hash
            ),
        )

    def use_extra_contract_methodology(self, *, retained: bool) -> None:
        support = dict(self.context.supporting_artifacts)
        if retained:
            extra_bytes = canonical_json(
                {"kind": "extra-unselected-methodology", "schema_version": "1"}
            )
            extra_hash = sha256(extra_bytes).hexdigest()
            support[extra_hash] = VerifiedArtifactBytes(
                data=extra_bytes,
                byte_size=len(extra_bytes),
                content_hash=extra_hash,
            )
        else:
            extra_hash = "e" * 64
        bindings = tuple(
            item.model_copy(
                update={"methodology_hashes": (*item.methodology_hashes, extra_hash)}
            )
            if item.dataset_role == "source_observation"
            else item
            for item in self._current_bindings
        )
        policy = ObservationSourceSelectionPolicyV1(
            policy_id="extra-contract-methodology-authority",
            version="1",
            bindings=bindings,
        )
        policy_bytes = canonical_json(policy)
        policy_hash = sha256(policy_bytes).hexdigest()
        support[policy_hash] = VerifiedArtifactBytes(
            data=policy_bytes,
            byte_size=len(policy_bytes),
            content_hash=policy_hash,
        )
        self._source_policy_hash = policy_hash
        self._current_bindings = bindings
        self.context = M1dResolutionContext(
            observation_datasets=self.context.observation_datasets,
            session_datasets=self.context.session_datasets,
            availability_policies=self.context.availability_policies,
            retained_evidence=self.context.retained_evidence,
            supporting_artifacts=support,
            structural_context=self.context.structural_context,
            research_definition=self.context.research_definition,
            issuer_id=self.context.issuer_id,
            structural_methodology_id=self.context.structural_methodology_id,
            m1b_requested_channel=self.context.m1b_requested_channel,
            schedule_generation_policy_hash=(
                self.context.schedule_generation_policy_hash
            ),
        )

    def use_overlapping_binding(
        self, *, kind: Literal["equivalent_observation", "distinct_schedule"]
    ) -> None:
        if kind == "equivalent_observation":
            base = next(
                item
                for item in self._current_bindings
                if item.dataset_role == "source_observation"
            )
            extra = base.model_copy(
                update={
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 1, 31),
                }
            )
        else:
            base = next(
                item
                for item in self._current_bindings
                if item.dataset_role == "scheduled_session"
            )
            extra = base.model_copy(update={"source_id": "competing-calendar-source"})
        bindings = (*self._current_bindings, extra)
        policy = ObservationSourceSelectionPolicyV1(
            policy_id=f"{kind}-authority",
            version="1",
            bindings=bindings,
        )
        policy_bytes = canonical_json(policy)
        policy_hash = sha256(policy_bytes).hexdigest()
        support = dict(self.context.supporting_artifacts)
        support[policy_hash] = VerifiedArtifactBytes(
            data=policy_bytes,
            byte_size=len(policy_bytes),
            content_hash=policy_hash,
        )
        self._source_policy_hash = policy_hash
        self._current_bindings = bindings
        self.context = M1dResolutionContext(
            observation_datasets=self.context.observation_datasets,
            session_datasets=self.context.session_datasets,
            availability_policies=self.context.availability_policies,
            retained_evidence=self.context.retained_evidence,
            supporting_artifacts=support,
            structural_context=self.context.structural_context,
            research_definition=self.context.research_definition,
            issuer_id=self.context.issuer_id,
            structural_methodology_id=self.context.structural_methodology_id,
            m1b_requested_channel=self.context.m1b_requested_channel,
            schedule_generation_policy_hash=(
                self.context.schedule_generation_policy_hash
            ),
        )

    def attach_sessions(
        self,
        *,
        schedule_state: Literal["regular", "early_close", "closed", "unknown"] = (
            "regular"
        ),
        realized_outcome: Literal[
            "opened", "opened_without_bounds", "did_not_open", "unknown", "missing"
        ] = "opened",
        realized_available_at: str = "2026-01-05T21:30:00Z",
        completion_evidence: Literal[
            "matching",
            "missing",
            "mismatched",
            "mismatched_availability",
            "foreign_availability",
            "legacy",
        ] = "matching",
        corrected_schedule: bool = False,
        corrected_realized_available_at: str | None = None,
        interruption_coverage: Literal["complete", "partial", "unknown"] = "complete",
        with_interruption: bool = False,
    ) -> None:
        """Replace the context with a combined exact observation/session snapshot."""
        from session_test_support import (
            AUTHORITY_HASH,
            generation_case,
            realized_record,
            session_dataset,
        )

        from drift.domain.sessions import (
            RealizedSessionVersionV1,
            ScheduledSessionVersionV1,
            SessionCoverageVersionV1,
        )

        session_context, _query, generation_policy = generation_case(
            local_date=self.session_date,
            state=schedule_state,
            corrected=corrected_schedule,
            record_availability_day=1,
            coverage_availability_day=1,
            methodology_availability_day=1,
            offset_availability_day=1,
        )
        support = {
            **dict(self.context.supporting_artifacts),
            **dict(session_context.supporting_artifacts),
        }
        generation_policy_bytes = canonical_json(generation_policy)
        generation_policy_hash = sha256(generation_policy_bytes).hexdigest()
        support[generation_policy_hash] = VerifiedArtifactBytes(
            data=generation_policy_bytes,
            byte_size=len(generation_policy_bytes),
            content_hash=generation_policy_hash,
        )
        session_datasets = tuple(session_context.session_datasets)
        realized_dataset = None
        if realized_outcome != "missing":
            base = realized_record(suffix=1400)
            revision = base.revision.model_copy(
                update={
                    "availability": (
                        _evidence_at(
                            _parse_instant(realized_available_at),
                            1402,
                            evidence_digest=base.revision.source_artifact.content_hash,
                        ),
                    ),
                    "payload_hash": "0" * 64,
                }
            )
            actual_open = base.actual_open
            actual_close = base.actual_close
            base_completion = base.actual_close
            outcome = realized_outcome
            if realized_outcome == "opened_without_bounds":
                outcome = "opened"
                actual_open = None
                actual_close = None
            elif realized_outcome in {"did_not_open", "unknown"}:
                actual_open = None
                actual_close = None
            source_evidence_hashes = base.source_evidence_hashes
            if (
                realized_outcome in {"did_not_open", "opened_without_bounds"}
                and completion_evidence != "missing"
            ):
                assert base_completion is not None
                completion_payload = {
                    "schema_version": "1",
                    "kind": "realized_session_completion",
                    "source_id": (
                        "wrong-calendar-source"
                        if completion_evidence == "mismatched"
                        else "calendar-source"
                    ),
                    "session_key": base.session_key,
                    "outcome": outcome,
                    "logical_record_id": revision.logical_record_id,
                    "record_version_id": revision.record_version_id,
                    "source_artifact_hash": revision.source_artifact.content_hash,
                    "completion_time": _boundary_at(base_completion, 1410),
                }
                if completion_evidence != "legacy":
                    completion_payload["record_availability_evidence_hash"] = (
                        "f" * 64
                        if completion_evidence == "mismatched_availability"
                        else content_hash(base.revision.availability[0])
                        if completion_evidence == "foreign_availability"
                        else content_hash(revision.availability[0])
                    )
                completion_bytes = canonical_json(completion_payload)
                completion_hash = sha256(completion_bytes).hexdigest()
                support[completion_hash] = VerifiedArtifactBytes(
                    data=completion_bytes,
                    byte_size=len(completion_bytes),
                    content_hash=completion_hash,
                )
                source_evidence_hashes = (
                    *source_evidence_hashes,
                    completion_hash,
                )
            source_evidence_hashes = tuple(sorted(source_evidence_hashes))
            values = {
                "schema_version": "1",
                "revision": revision,
                "source_id": base.source_id,
                "session_key": base.session_key,
                "outcome": outcome,
                "actual_open": actual_open,
                "actual_close": actual_close,
                "reported_as_scheduled": base.reported_as_scheduled,
                "late_open": base.late_open,
                "early_close": base.early_close,
                "interruption_intervals": (
                    base.interruption_intervals if with_interruption else ()
                ),
                "interruption_coverage": interruption_coverage,
                "source_evidence_hashes": source_evidence_hashes,
                "methodology_hashes": base.methodology_hashes,
                "compared_schedule_hash": base.compared_schedule_hash,
            }
            provisional = type(base).model_construct(
                **values  # type: ignore[arg-type]
            )
            values["revision"] = revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(provisional))
                }
            )
            realized = type(base).model_validate(values)
            realized_records: tuple[RealizedSessionVersionV1, ...] = (realized,)
            if corrected_realized_available_at is not None:
                assert base_completion is not None
                correction_revision = RevisionEnvelopeV1(
                    schema_version="1",
                    logical_record_id=realized.revision.logical_record_id,
                    record_version_id=uid(1451),
                    revision_kind=RevisionKind.CORRECTION,
                    supersedes_record_version_id=realized.revision.record_version_id,
                    source_sequence=realized.revision.source_sequence + 1,
                    availability=(
                        _evidence_at(
                            _parse_instant(corrected_realized_available_at),
                            1452,
                            evidence_digest=realized.revision.source_artifact.content_hash,
                        ),
                    ),
                    history_completeness=HistoryCompleteness.UNKNOWN,
                    source_native_revision_label=None,
                    source_artifact=reference(1453, AUTHORITY_HASH),
                    payload_hash="0" * 64,
                )
                correction_companion = {
                    "schema_version": "1",
                    "kind": "realized_session_completion",
                    "source_id": realized.source_id,
                    "session_key": realized.session_key,
                    "outcome": realized.outcome,
                    "logical_record_id": correction_revision.logical_record_id,
                    "record_version_id": correction_revision.record_version_id,
                    "source_artifact_hash": (
                        correction_revision.source_artifact.content_hash
                    ),
                    "record_availability_evidence_hash": content_hash(
                        correction_revision.availability[0]
                    ),
                    "completion_time": _boundary_at(base_completion, 1454),
                }
                correction_companion_bytes = canonical_json(correction_companion)
                correction_companion_hash = sha256(
                    correction_companion_bytes
                ).hexdigest()
                support[correction_companion_hash] = VerifiedArtifactBytes(
                    data=correction_companion_bytes,
                    byte_size=len(correction_companion_bytes),
                    content_hash=correction_companion_hash,
                )
                correction_values = {
                    **values,
                    "revision": correction_revision,
                    "source_evidence_hashes": tuple(
                        sorted(
                            (*base.source_evidence_hashes, correction_companion_hash)
                        )
                    ),
                }
                provisional_correction = type(base).model_construct(
                    **correction_values  # type: ignore[arg-type]
                )
                correction_values["revision"] = correction_revision.model_copy(
                    update={
                        "payload_hash": content_hash(
                            assertion_version_payload(provisional_correction)
                        )
                    }
                )
                correction = type(base).model_validate(correction_values)
                realized_records = (realized, correction)
            realized_dataset = session_dataset(
                "realized_session", realized_records, support
            )
            session_datasets = (*session_datasets, realized_dataset)
        scheduled = next(
            item
            for item in session_datasets
            if item.manifest.dataset_role.name == "scheduled_session"
        )
        session_coverage = next(
            item
            for item in session_datasets
            if item.manifest.dataset_role.name == "session_coverage"
        )
        scheduled_record = scheduled.records[0]
        coverage_record = session_coverage.records[0]
        assert isinstance(scheduled_record, ScheduledSessionVersionV1)
        assert isinstance(coverage_record, SessionCoverageVersionV1)
        session_bindings = [
            ObservationSourceBindingV1(
                dataset_role="scheduled_session",
                source_id="calendar-source",
                contract_hash=None,
                venue=ListingVenue.XNYS,
                listing_id=self.listing_id,
                start_date=self.session_date,
                end_date=self.session_date,
                manifest_hashes=(manifest_hash(scheduled.manifest),),
                methodology_hashes=(scheduled_record.source_methodology_hash,),
            ),
            ObservationSourceBindingV1(
                dataset_role="session_coverage",
                source_id="calendar-source",
                contract_hash=None,
                venue=ListingVenue.XNYS,
                listing_id=self.listing_id,
                start_date=self.session_date,
                end_date=self.session_date,
                manifest_hashes=(manifest_hash(session_coverage.manifest),),
                methodology_hashes=(coverage_record.methodology_hash,),
            ),
        ]
        if realized_dataset is not None:
            session_bindings.append(
                ObservationSourceBindingV1(
                    dataset_role="realized_session",
                    source_id="calendar-source",
                    contract_hash=None,
                    venue=ListingVenue.XNYS,
                    listing_id=self.listing_id,
                    start_date=self.session_date,
                    end_date=self.session_date,
                    manifest_hashes=(manifest_hash(realized_dataset.manifest),),
                    methodology_hashes=(AUTHORITY_HASH,),
                )
            )
        policy = ObservationSourceSelectionPolicyV1(
            policy_id="combined-observation-session-authority",
            version="1",
            bindings=(*self._observation_bindings, *session_bindings),
        )
        policy_bytes = canonical_json(policy)
        policy_hash = sha256(policy_bytes).hexdigest()
        support[policy_hash] = VerifiedArtifactBytes(
            data=policy_bytes,
            byte_size=len(policy_bytes),
            content_hash=policy_hash,
        )
        self._source_policy_hash = policy_hash
        self._current_bindings = policy.bindings
        self.context = M1dResolutionContext(
            observation_datasets=self.context.observation_datasets,
            session_datasets=session_datasets,
            availability_policies={
                **dict(self.context.availability_policies),
                **dict(session_context.availability_policies),
            },
            retained_evidence={
                **dict(self.context.retained_evidence),
                **dict(session_context.retained_evidence),
            },
            supporting_artifacts=support,
            structural_context=self.context.structural_context,
            research_definition=self.context.research_definition,
            issuer_id=self.context.issuer_id,
            structural_methodology_id=self.context.structural_methodology_id,
            m1b_requested_channel=self.context.m1b_requested_channel,
            schedule_generation_policy_hash=generation_policy_hash,
        )

    def attach_m1b(
        self, lifecycle_case: str = "active", structural_case: str | None = None
    ) -> None:
        """Attach genuinely validated M1b inputs for interval replay."""
        from test_assertions import public_availability, unknown_boundary
        from test_listing_semantics import (
            assignment_dataset,
            assignment_for_dependency,
            bounded_boundary,
            classification_record,
            coverage_record,
            issuer_security_relationship,
            lifecycle_record,
            relationship_dataset,
            relationship_record,
            role_dataset,
            role_record,
            role_validation_context,
            termination_record,
        )
        from test_universes import membership, membership_context

        from drift.datasets.assertions import build_validated_dataset_bundle
        from drift.domain.dataset_validation import ValidationResult
        from drift.domain.securities import (
            IdentityKind,
            IdentityReferenceV1,
            IssuerForm,
            ListingHistoryCoverageStatus,
            ListingLifecycleEventKind,
            ListingLifecycleVersionV1,
            ListingTerminationReason,
            ListingTerminationVersionV1,
            ListingV1,
            ListingVenue,
        )
        from drift.domain.universes import MembershipEffect
        from drift.markets.universes import (
            STRICT_CLASSIFICATION_CONTRACT_HASH,
            StructuralResolutionContext,
            ValidatedRecords,
        )
        from drift.markets.validation import validate_identity_dataset

        membership_records: tuple[Any, ...] = (
            membership(
                2640,
                MembershipEffect.INCLUDED,
                "2019-01-02T00:00:00Z",
                target=201,
            ),
        )
        if structural_case == "membership_removal":
            membership_records = (
                *membership_records,
                membership(
                    2641,
                    MembershipEffect.EXCLUDED,
                    "2026-01-05T17:00:00Z",
                    target=201,
                ),
            )
        base_definition, universe = membership_context(membership_records)
        references = (
            IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=self.issuer_id),
            IdentityReferenceV1(
                kind=IdentityKind.SECURITY, internal_id=self.security_id
            ),
            IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=self.listing_id),
        )
        assignments = tuple(
            assignment_for_dependency(reference_value, 2650 + index)
            for index, reference_value in enumerate(references)
        )
        listing_assignment = assignments[2].model_copy(
            update={
                "identity": ListingV1(
                    schema_version="1",
                    listing_id=self.listing_id,
                    venue=ListingVenue.XNYS,
                )
            }
        )
        listing_assignment = listing_assignment.model_copy(
            update={
                "revision": listing_assignment.revision.model_copy(
                    update={
                        "payload_hash": content_hash(
                            assertion_version_payload(listing_assignment)
                        )
                    }
                )
            }
        )
        assignments = (*assignments[:2], listing_assignment)
        assignment_manifest, assignment_decision = assignment_dataset(assignments)
        relationships: tuple[Any, ...] = (
            issuer_security_relationship(2660, issuer=202, security=200),
            relationship_record(200, 201, 2670),
        )
        if lifecycle_case == "venue_transfer":
            related = IdentityReferenceV1(
                kind=IdentityKind.LISTING, internal_id=market_uid(203)
            )
            related_assignment = assignment_for_dependency(related, 2654)
            assignments = (*assignments, related_assignment)
            relationships = (
                *relationships,
                relationship_record(
                    200,
                    203,
                    2671,
                    start="2026-01-05T17:00:00Z",
                ),
            )
            assignment_manifest, assignment_decision = assignment_dataset(assignments)
        relationship_manifest, relationship_decision = relationship_dataset(
            relationships
        )

        events: tuple[ListingLifecycleVersionV1, ...] = (
            lifecycle_record(
                2681,
                ListingLifecycleEventKind.ADMITTED,
                "2019-01-02T00:00:00Z",
                listing=201,
            ),
            lifecycle_record(
                2682,
                ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
                "2019-01-03T14:30:00Z",
                listing=201,
            ),
        )
        terminations: tuple[ListingTerminationVersionV1, ...] = ()
        if lifecycle_case == "not_yet_listed":
            events = (
                lifecycle_record(
                    2681,
                    ListingLifecycleEventKind.ADMITTED,
                    "2026-01-06T00:00:00Z",
                    listing=201,
                ),
                lifecycle_record(
                    2682,
                    ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
                    "2026-01-06T14:30:00Z",
                    listing=201,
                ),
            )
        elif lifecycle_case == "fully_suspended":
            events = (
                *events,
                lifecycle_record(
                    2683,
                    ListingLifecycleEventKind.SUSPENDED,
                    "2026-01-04T00:00:00Z",
                    listing=201,
                ),
            )
        elif lifecycle_case == "partial_suspension":
            events = (
                *events,
                lifecycle_record(
                    2683,
                    ListingLifecycleEventKind.SUSPENDED,
                    "2026-01-05T17:00:00Z",
                    listing=201,
                ),
                lifecycle_record(
                    2684,
                    ListingLifecycleEventKind.RESUMED,
                    "2026-01-05T17:15:00Z",
                    listing=201,
                ),
            )
        elif lifecycle_case == "disjoint_bounded_unknown":
            events = (
                *events,
                lifecycle_record(
                    2683,
                    ListingLifecycleEventKind.SUSPENDED,
                    bounded_boundary("2026-01-01T10:00:00Z", "2026-01-01T12:00:00Z"),
                    listing=201,
                ),
                lifecycle_record(
                    2684,
                    ListingLifecycleEventKind.RESUMED,
                    "2026-01-02T00:00:00Z",
                    listing=201,
                ),
            )
        elif lifecycle_case == "overlapping_bounded_unknown":
            events = (
                *events,
                lifecycle_record(
                    2683,
                    ListingLifecycleEventKind.SUSPENDED,
                    bounded_boundary("2026-01-05T16:30:00Z", "2026-01-05T17:30:00Z"),
                    listing=201,
                ),
                lifecycle_record(
                    2684,
                    ListingLifecycleEventKind.RESUMED,
                    "2026-01-05T18:00:00Z",
                    listing=201,
                ),
            )
        elif lifecycle_case == "bounded_endpoint_touch":
            events = (
                *events,
                lifecycle_record(
                    2683,
                    ListingLifecycleEventKind.SUSPENDED,
                    bounded_boundary("2026-01-05T16:30:00Z", "2026-01-05T17:00:00Z"),
                    listing=201,
                ),
                lifecycle_record(
                    2684,
                    ListingLifecycleEventKind.RESUMED,
                    "2026-01-05T17:00:00Z",
                    listing=201,
                ),
            )
        elif lifecycle_case == "unknown_boundary":
            events = (
                *events,
                lifecycle_record(
                    2683,
                    ListingLifecycleEventKind.SUSPENDED,
                    unknown_boundary(),
                    listing=201,
                ),
            )
        elif lifecycle_case == "venue_transfer":
            events = (
                *events,
                lifecycle_record(
                    2683,
                    ListingLifecycleEventKind.VENUE_TRANSFER,
                    "2026-01-05T17:00:00Z",
                    listing=201,
                    related_listing=203,
                ),
            )
            terminations = (
                termination_record(
                    2690,
                    ListingTerminationReason.VENUE_TRANSFER,
                    listing=201,
                    last_trade="2026-01-05T16:59:00Z",
                    effective_time="2026-01-05T17:00:00Z",
                ),
            )
        elif lifecycle_case in {
            "terminated_before",
            "terminated_after",
            "late_known_termination",
        }:
            effective = (
                "2026-01-04T00:00:00Z"
                if lifecycle_case == "terminated_before"
                else "2026-01-06T00:00:00Z"
                if lifecycle_case == "terminated_after"
                else "2026-01-05T14:00:00Z"
            )
            termination = termination_record(
                2690,
                ListingTerminationReason.EXCHANGE_DELISTING,
                listing=201,
                last_trade="2026-01-03T21:00:00Z",
                effective_time=effective,
            )
            if lifecycle_case == "late_known_termination":
                revision = termination.revision.model_copy(
                    update={
                        "availability": (public_availability("2026-01-08T00:00:00Z"),)
                    }
                )
                termination = termination.model_copy(update={"revision": revision})
                termination = termination.model_copy(
                    update={
                        "revision": revision.model_copy(
                            update={
                                "payload_hash": content_hash(
                                    assertion_version_payload(termination)
                                )
                            }
                        )
                    }
                )
            terminations = (termination,)

        classifications: tuple[Any, ...] = (
            classification_record(
                2700,
                issuer=202,
                security=200,
                end=(
                    "2026-01-05T17:00:00Z"
                    if structural_case == "classification_change"
                    else None
                ),
            ),
        )
        if structural_case == "classification_change":
            classifications = (
                *classifications,
                classification_record(
                    2701,
                    issuer=202,
                    security=200,
                    issuer_form=IssuerForm.FUND,
                    start="2026-01-05T17:00:00Z",
                ),
            )
        record_sets: dict[str, tuple[Any, ...]] = {
            "security_classification": classifications,
            "listing_role": (role_record(2710, 201, security=200),),
            "listing_lifecycle": events,
            "listing_termination": terminations,
            "listing_history_coverage": (
                coverage_record(
                    2720,
                    ListingHistoryCoverageStatus.COMPLETE,
                    "2026-12-31T00:00:00Z",
                    listing=201,
                ),
            ),
        }
        datasets: dict[str, ValidatedRecords[Any]] = {}
        for role, records in record_sets.items():
            manifest, data = role_dataset(role, records)
            decision = validate_identity_dataset(
                manifest, (data,), role_validation_context(2730)
            )
            assert decision.result is ValidationResult.PASS
            datasets[role] = ValidatedRecords(
                records=records, manifest=manifest, decision=decision
            )
        identity_bundle = build_validated_dataset_bundle(
            market_uid(2740),
            "1",
            datetime(2026, 9, 4, tzinfo=UTC),
            (
                (assignment_manifest, assignment_decision),
                (relationship_manifest, relationship_decision),
                *((value.manifest, value.decision) for value in datasets.values()),
            ),
        )
        universe = replace(
            universe,
            identity_bundle=identity_bundle,
            assignments=ValidatedRecords(
                records=assignments,
                manifest=assignment_manifest,
                decision=assignment_decision,
            ),
        )
        definition = base_definition.model_copy(
            update={
                "identity_bundle_hash": content_hash(identity_bundle),
                "classification_contract_hash": STRICT_CLASSIFICATION_CONTRACT_HASH,
            }
        )
        structural = StructuralResolutionContext(
            universe=universe,
            relationships=ValidatedRecords(
                records=relationships,
                manifest=relationship_manifest,
                decision=relationship_decision,
            ),
            classifications=datasets["security_classification"],
            roles=datasets["listing_role"],
            lifecycle=datasets["listing_lifecycle"],
            terminations=datasets["listing_termination"],
            coverage=datasets["listing_history_coverage"],
        )
        self.context = replace(
            self.context,
            structural_context=structural,
            research_definition=definition,
            issuer_id=self.issuer_id,
            structural_methodology_id="synthetic-primary-v1",
            m1b_requested_channel=public_availability("2018-01-01T00:00:00Z").channel,
        )

    def _replace_contract(self, **updates: object) -> None:
        provisional = self._contract.model_copy(update=updates)
        methodology_bytes = canonical_json(
            observation_methodology_for_contract(provisional)
        )
        methodology_hash = sha256(methodology_bytes).hexdigest()
        self._contract = provisional.model_copy(
            update={"methodology_artifact_hash": methodology_hash}
        )
        contract_bytes = canonical_json(self._contract)
        contract_hash = sha256(contract_bytes).hexdigest()
        support = dict(self._contract_support)
        support[methodology_hash] = VerifiedArtifactBytes(
            data=methodology_bytes,
            byte_size=len(methodology_bytes),
            content_hash=methodology_hash,
        )
        support[contract_hash] = VerifiedArtifactBytes(
            data=contract_bytes,
            byte_size=len(contract_bytes),
            content_hash=contract_hash,
        )
        self._contract_support = support
        self._records = tuple(
            self._reseal_record(record, contract_hash=contract_hash)
            for record in self._records
        )

    def _reseal_record(
        self, record: DailySourceObservationVersionV1, **updates: object
    ) -> DailySourceObservationVersionV1:
        values = {
            name: getattr(record, name)
            for name in DailySourceObservationVersionV1.model_fields
        }
        values.update(updates)
        values["revision"] = record.revision
        revision = record.revision.model_copy(update={"payload_hash": "0" * 64})
        values["revision"] = revision.model_copy(
            update={
                "payload_hash": content_hash(
                    assertion_version_payload(
                        DailySourceObservationVersionV1.model_construct(**values)
                    )
                )
            }
        )
        return DailySourceObservationVersionV1.model_validate(values)

    def use_absent_query_row(
        self,
        *,
        coverage: str = "complete",
        row_emission: Literal[
            "every_relevant_session",
            "conditional_on_qualifying_activity",
            "explicit_markers",
            "unknown",
        ] = "every_relevant_session",
        snapshot_case: str = "exact",
    ) -> None:
        if row_emission != self._contract.row_emission.kind:
            self._replace_contract(
                row_emission=RowEmissionPolicyV1(
                    kind=row_emission,
                    omission_marker_policy_hash=RULE_HASH,
                )
            )
        self._coverage_status = (
            "partial"
            if coverage == "partial"
            else "unknown"
            if coverage == "unknown"
            else "expected_complete"
        )
        self._coverage_revision_history = (
            "current_only" if coverage == "current_only" else "complete"
        )
        self._coverage_snapshot = None
        self._coverage_snapshot_availability = None
        if snapshot_case == "unknown":
            self._coverage_snapshot = TemporalBoundaryClaimV1(
                schema_version="1",
                shape=BoundaryShape.UNKNOWN,
                lower_bound=None,
                upper_bound=None,
                source_precision=SourcePrecision.UNKNOWN,
                source_time_label=None,
                source_timezone=None,
                evidence_reference=None,
            )
        elif snapshot_case == "bounded":
            self._coverage_snapshot = TemporalBoundaryClaimV1(
                schema_version="1",
                shape=BoundaryShape.BOUNDED,
                lower_bound=_parse_instant("2026-01-05T20:00:00Z"),
                upper_bound=_parse_instant("2026-01-05T22:00:00Z"),
                source_precision=SourcePrecision.INTERVAL,
                source_time_label="2026-01-05T20:00:00Z/2026-01-05T22:00:00Z",
                source_timezone=None,
                evidence_reference=reference(1810),
            )
        elif snapshot_case == "future":
            self._coverage_snapshot = _boundary_at(
                _parse_instant("2026-01-08T21:00:00Z"), 1811
            )
            self._coverage_snapshot_availability = _evidence_at(
                _parse_instant("2026-01-09T21:00:00Z"), 1812
            )
        elif snapshot_case == "backdated":
            self._coverage_snapshot = _boundary_at(
                _parse_instant("2026-01-05T21:00:00Z"), 1813
            )
            self._coverage_snapshot_availability = _evidence_at(
                _parse_instant("2026-01-04T21:00:00Z"), 1814
            )
        self._records = (
            self._record(
                close="100.000",
                available_at=_parse_instant("2026-01-04T21:30:00Z"),
                suffix=1800,
                predecessor=None,
                record_date=date(2026, 1, 4),
            ),
        )
        self._rebuild()

    def use_field_case(self, case: str) -> None:
        record = self._records[0]
        fields = list(record.fields)
        if case in {"split_adjusted", "dividend_adjusted", "unknown_basis"}:
            basis = {
                "split_adjusted": "split_adjusted",
                "dividend_adjusted": "dividend_adjusted",
                "unknown_basis": "unknown",
            }[case]
            methods = tuple(
                item.model_copy(update={"adjustment_basis": basis})
                for item in self._contract.field_methods
            )
            self._replace_contract(adjustment_basis=basis, field_methods=methods)
            record = self._records[0]
        elif case == "mixed_population":
            base_population = self._contract.populations[0]
            other = base_population.model_copy(update={"population_id": "other-trades"})
            methods = tuple(
                item.model_copy(update={"population_id": "other-trades"})
                if item.field_name == "close"
                else item
                for item in self._contract.field_methods
            )
            self._replace_contract(
                populations=(*self._contract.populations, other),
                field_methods=methods,
            )
            record = self._records[0]
        elif case in {"official_close_unproven", "official_close_equivalent"}:
            methods = tuple(
                item.model_copy(
                    update={
                        "meaning": "official_close",
                        "effective_selector": (
                            "official" if case == "official_close_unproven" else "last"
                        ),
                    }
                )
                if item.field_name == "close"
                else item
                for item in self._contract.field_methods
            )
            self._replace_contract(field_methods=methods)
            record = self._records[0]
        elif case == "unknown_method_meaning":
            methods = tuple(
                item.model_copy(update={"meaning": "unknown"})
                if item.field_name == "close"
                else item
                for item in self._contract.field_methods
            )
            self._replace_contract(field_methods=methods)
            record = self._records[0]
        elif case == "unknown_ordering":
            methods = tuple(
                item.model_copy(update={"ordering": "unknown"})
                if item.field_name == "close"
                else item
                for item in self._contract.field_methods
            )
            self._replace_contract(field_methods=methods)
            record = self._records[0]

        fields = list(record.fields)
        if case in {"zero_volume", "volume_sentinel"}:
            fields = [
                item.model_copy(
                    update={
                        "value": Decimal("0"),
                        "native_text": "0.000",
                        "state": "sentinel" if case == "volume_sentinel" else "value",
                    }
                )
                if item.field_name == "volume"
                else item
                for item in fields
            ]
        elif case == "null_close":
            fields = [
                item.model_copy(
                    update={"state": "null", "value": None, "native_text": None}
                )
                if item.field_name == "close"
                else item
                for item in fields
            ]
        elif case == "partial_fields":
            fields = [item for item in fields if item.field_name != "close"]
        elif case == "negative_price":
            fields = [
                item.model_copy(update={"value": Decimal("-1"), "native_text": "-1"})
                if item.field_name == "open"
                else item
                for item in fields
            ]
        elif case == "range_failure":
            fields = [
                item.model_copy(update={"value": Decimal("98"), "native_text": "98"})
                if item.field_name == "high"
                else item
                for item in fields
            ]
        activity = (
            "explicit_no_qualifying_price_trade"
            if case == "explicit_no_price_trade"
            else "unknown"
            if case in {"zero_volume", "volume_sentinel", "null_close"}
            or case == "unknown_activity"
            else record.activity_claim
        )
        any_trade = (
            "reported"
            if case == "explicit_no_price_trade"
            else (
                "unknown"
                if case in {"zero_volume", "volume_sentinel", "null_close"}
                else record.any_trade_claim
            )
        )
        self._records = (
            self._reseal_record(
                record,
                fields=tuple(fields),
                activity_claim=activity,
                any_trade_claim=any_trade,
            ),
        )
        self._rebuild()

    def use_lifecycle_case(
        self,
        case: str,
        *,
        interruption_coverage: Literal["complete", "partial", "unknown"] = "complete",
        aggregation_policy: str = "matching",
    ) -> None:
        self._default_lifecycle_case = case
        if case == "partial_suspension":
            self._configure_aggregation_policy(aggregation_policy)
            self._rebuild()
        self.attach_sessions(
            interruption_coverage=interruption_coverage,
            with_interruption=case == "partial_suspension",
        )
        self.attach_m1b(case)

    def _configure_aggregation_policy(self, kind: str) -> None:
        if kind == "missing":
            return
        if kind == "unknown":
            policy_bytes = canonical_json(
                {"kind": "unknown-interval-aggregation", "schema_version": "1"}
            )
        else:
            policy = InterruptionAggregationPolicyV1(
                kind="observation_interval_event_policy",
                contract_id=(
                    market_uid(999)
                    if kind == "mismatched"
                    else self._contract.contract_id
                ),
                contract_version=self._contract.version,
                source_id=self._contract.source_id,
                interval_semantics="half_open_utc_segments_v1",
                interruption_aggregation=(
                    "exclude_suspended_segments_aggregate_eligible_segments_v1"
                ),
                required_fields=("open", "high", "low", "close", "volume"),
                require_complete_interruption_intervals=True,
            )
            policy_bytes = canonical_json(policy)
        digest = sha256(policy_bytes).hexdigest()
        support = dict(self._contract_support)
        support[digest] = VerifiedArtifactBytes(
            data=policy_bytes,
            byte_size=len(policy_bytes),
            content_hash=digest,
        )
        self._contract_support = support
        self._replace_contract(
            interval_policy=self._contract.interval_policy.model_copy(
                update={"event_policy_hash": digest}
            )
        )

    def use_structural_change(self, change: str) -> None:
        self.attach_m1b(structural_case=change)

    def remove_m1b_channel_mapping(self) -> None:
        self.context = replace(self.context, m1b_requested_channel=None)

    def use_generation_policy_case(self, case: str) -> None:
        from drift.domain.sessions import ScheduleGenerationPolicyV1

        policy_hash = self.context.schedule_generation_policy_hash
        assert policy_hash is not None
        policy = ScheduleGenerationPolicyV1.model_validate_json(
            self.context.supporting_artifacts[policy_hash].data
        )
        field = {
            "missing_producer_source": "producer_source_hash",
            "missing_producer_package": "producer_package_hash",
            "missing_lockfile": "lockfile_hash",
        }.get(case)
        if case == "false_implementation":
            policy = policy.model_copy(update={"implementation_hash": "f" * 64})
        elif field is not None:
            policy = policy.model_copy(update={field: "f" * 64})
        else:
            raise ValueError("unsupported generation policy test case")
        policy_bytes = canonical_json(policy)
        changed_hash = sha256(policy_bytes).hexdigest()
        support = dict(self.context.supporting_artifacts)
        support[changed_hash] = VerifiedArtifactBytes(
            data=policy_bytes,
            byte_size=len(policy_bytes),
            content_hash=changed_hash,
        )
        self.context = replace(
            self.context,
            supporting_artifacts=support,
            schedule_generation_policy_hash=changed_hash,
        )

    def use_read_failure(self, failure: str) -> None:
        source = next(
            item
            for item in self.context.observation_datasets
            if item.manifest.dataset_role.name == "source_observation"
        )
        if failure == "unavailable":
            artifacts = {}
        else:
            digest, artifact = next(iter(source.artifacts.items()))
            artifacts = {
                digest: VerifiedArtifactBytes(
                    data=b"corrupt",
                    byte_size=artifact.byte_size,
                    content_hash=artifact.content_hash,
                )
            }
        changed_source = replace(source, artifacts=artifacts)
        self.context = replace(
            self.context,
            observation_datasets=tuple(
                changed_source if item is source else item
                for item in self.context.observation_datasets
            ),
        )

    def assess(self, query: ObservationQueryV1) -> ObservationAssessmentResultV1:
        from drift.markets.observation_usability import assess_observation

        return assess_observation(query, self.context)

    def verify(
        self,
        result: ObservationAssessmentResultV1,
        *,
        context: M1dResolutionContext | None = None,
    ) -> None:
        from drift.markets.observation_usability import verify_observation_assessment

        verify_observation_assessment(
            result, self.context if context is None else context
        )
