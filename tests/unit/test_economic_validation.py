"""Tests for exact M1c economic dataset and context validation."""

import json
from dataclasses import replace
from hashlib import sha256

import pytest
from economic_test_support import (
    HASH_A,
    HASH_B,
    coverage_record,
    economic_dataset,
    economic_evidence,
    effect_record,
    parse_utc,
    public_availability,
    public_channel,
    rebind_coverage_evidence,
    rebind_record_evidence,
    revise_record,
    seal_record,
    settlement_record,
    support_bytes,
    terms_record,
    uid,
    validated_case,
)

import drift.markets.economic_validation as economic_validation
from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.dataset_validation import (
    DatasetValidationError,
    ValidationResult,
    ValidationScope,
)
from drift.domain.economic_common import (
    EconomicRecipientV1,
    EconomicShareBasisV1,
    FractionTreatmentV1,
    PositiveRatioV1,
    ShareComponentV1,
)
from drift.domain.economic_coverage import EconomicCoverageVersionV1
from drift.domain.manifests import (
    AssertionTemporalContractV1,
    FieldDescriptorV1,
    LogicalType,
    SchemaDescriptorV1,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.serialization.canonical import canonical_json, content_hash

ROLE_CASES = {
    "economic_terms": (terms_record(101), "scheduled_effect_time", "boundary"),
    "economic_effect": (effect_record(102), "effective_time", "boundary"),
    "economic_settlement": (settlement_record(103), "settled_time", "boundary"),
}

SHARED_FIELDS = {
    "schema_version": (LogicalType.STRING, False),
    "revision.schema_version": (LogicalType.STRING, False),
    "revision.logical_record_id": (LogicalType.STRING, False),
    "revision.record_version_id": (LogicalType.STRING, False),
    "revision.revision_kind": (LogicalType.STRING, False),
    "revision.supersedes_record_version_id": (LogicalType.STRING, True),
    "revision.source_sequence": (LogicalType.INTEGER, False),
    "revision.availability": (LogicalType.JSON, False),
    "revision.history_completeness": (LogicalType.STRING, False),
    "revision.source_native_revision_label": (LogicalType.STRING, True),
    "revision.source_artifact": (LogicalType.JSON, False),
    "revision.payload_hash": (LogicalType.STRING, False),
    "source_key": (LogicalType.JSON, False),
    "security_id": (LogicalType.STRING, False),
    "listing_id": (LogicalType.STRING, True),
}
FACT_FIELDS = {
    "occurrence": (LogicalType.JSON, False),
    "source_action_code": (LogicalType.STRING, True),
    "payload": (LogicalType.JSON, True),
}
EXPECTED_ROLE_FIELDS = {
    "economic_terms": {
        **SHARED_FIELDS,
        **FACT_FIELDS,
        "scheduled_effect_time": (LogicalType.JSON, False),
    },
    "economic_effect": {
        **SHARED_FIELDS,
        **FACT_FIELDS,
        "effective_time": (LogicalType.JSON, False),
        "terms_association": (LogicalType.JSON, False),
    },
    "economic_settlement": {
        **SHARED_FIELDS,
        **FACT_FIELDS,
        "settled_time": (LogicalType.JSON, False),
        "terms_association": (LogicalType.JSON, False),
        "effect_association": (LogicalType.JSON, False),
    },
    "economic_coverage": {
        **SHARED_FIELDS,
        "coverage_interval": (LogicalType.JSON, False),
        "fact_family": (LogicalType.STRING, False),
        "action_kinds": (LogicalType.JSON, False),
        "target_manifest_hash": (LogicalType.STRING, False),
        "inventory_artifact_hashes": (LogicalType.JSON, False),
        "inventory_record_hashes": (LogicalType.JSON, False),
        "methodology_reference": (LogicalType.JSON, False),
        "methodology_version": (LogicalType.STRING, False),
        "snapshot_at": (LogicalType.DATETIME, False),
        "completeness": (LogicalType.STRING, False),
        "revision_support": (LogicalType.STRING, False),
        "occurrence_key_semantics": (LogicalType.STRING, False),
        "gaps": (LogicalType.JSON, False),
        "exceptions": (LogicalType.JSON, False),
    },
}


def test_valid_empty_dataset_is_not_an_event_absence_assertion() -> None:
    dataset = economic_dataset("economic_settlement", ())
    assert dataset.records == ()
    assert dataset.decision.validation_scope is ValidationScope.MANIFEST_ONLY
    assert "economic-settlement-v1-exact-empty" in dataset.decision.checked_contracts
    assert dataset.decision.validated_record_hashes == ()


@pytest.mark.parametrize("role", tuple(ROLE_CASES) + ("economic_coverage",))
def test_role_schemas_are_exact_sorted_and_hash_bound(role: str) -> None:
    schema = economic_validation.economic_role_schema(role)
    field_ids = tuple(field.field_id for field in schema.fields)
    assert field_ids == tuple(sorted(field_ids))
    assert "revision" not in field_ids
    assert schema.schema_hash == schema_hash(schema)
    assert all(
        field.name == field.field_id and field.unit is None for field in schema.fields
    )
    assert {
        field.field_id: (field.logical_type, field.nullable) for field in schema.fields
    } == EXPECTED_ROLE_FIELDS[role]


def test_role_contract_binds_every_non_revision_semantic_field() -> None:
    schema = economic_validation.economic_role_schema("economic_settlement")
    contract = economic_validation.economic_role_contract(
        "economic_settlement", (public_channel(),)
    )
    excluded = {
        "revision.logical_record_id",
        "revision.record_version_id",
        "revision.revision_kind",
        "revision.supersedes_record_version_id",
        "revision.source_sequence",
        "revision.availability",
        "revision.source_artifact",
        "revision.payload_hash",
        "settled_time",
    }
    assert contract.effective_time_field_id == "settled_time"
    assert contract.effective_shape.value == "boundary"
    assert contract.semantic_state_field_ids == tuple(
        sorted(
            field.field_id for field in schema.fields if field.field_id not in excluded
        )
    )


def test_role_schema_constants_are_literal_hash_pins() -> None:
    expected = {
        "economic_terms": (
            "ECONOMIC_TERMS_SCHEMA_V1",
            "e3bdf085b06113b66bb553de4c1f49d04f6d7df94973f62bf3cec1b408b7a0c8",
        ),
        "economic_effect": (
            "ECONOMIC_EFFECT_SCHEMA_V1",
            "d827cd05b11801c8867abfe1f61a9b05bffb0df69896ba1756bf300a47ff7c57",
        ),
        "economic_settlement": (
            "ECONOMIC_SETTLEMENT_SCHEMA_V1",
            "20d93fe8bb7af2d6b3862598adbbd2a74957b98df93710b031c687977ccfdf94",
        ),
        "economic_coverage": (
            "ECONOMIC_COVERAGE_SCHEMA_V1",
            "657451052b99a99245b7d2edc7a42b1b712660ac78c1552d349033309615d903",
        ),
    }
    for role, (name, expected_hash) in expected.items():
        schema = getattr(economic_validation, name)
        assert schema == economic_validation.economic_role_schema(role)
        assert schema.schema_hash == expected_hash


@pytest.mark.parametrize("role", ROLE_CASES)
def test_exact_role_document_round_trips_through_its_model(role: str) -> None:
    record = ROLE_CASES[role][0]
    data = canonical_json({"schema_version": "1", "records": (record,)})
    assert economic_validation.parse_economic_document(data, role) == (record,)
    wrong_role = next(candidate for candidate in ROLE_CASES if candidate != role)
    with pytest.raises(Exception, match="economic_record_invalid"):
        economic_validation.parse_economic_document(data, wrong_role)


def test_structure_failure_never_calls_economic_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = economic_dataset("economic_terms", (terms_record(201),))
    corrupt = VerifiedArtifactBytes(
        data=b"corrupt", byte_size=7, content_hash=sha256(b"corrupt").hexdigest()
    )

    def forbidden_parser(data: bytes, role: str) -> tuple[object, ...]:
        raise AssertionError(f"parser called for {role} with {data!r}")

    monkeypatch.setattr(
        economic_validation, "parse_economic_document", forbidden_parser
    )
    decision, records = economic_validation.validate_economic_dataset(
        dataset.manifest, (corrupt,), dataset.validation_run
    )
    assert decision.result is ValidationResult.FAIL
    assert records == ()


def test_exact_validator_rejects_schema_contract_channels_and_source_owner() -> None:
    record = terms_record(301)
    dataset = economic_dataset("economic_terms", (record,))
    schema = dataset.manifest.schema_definition
    extra = FieldDescriptorV1(
        field_id="marketing_label",
        name="marketing_label",
        logical_type=LogicalType.STRING,
        nullable=True,
    )
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1",
        fields=tuple(sorted((*schema.fields, extra), key=lambda field: field.field_id)),
        schema_hash=HASH_A,
    )
    wrong_schema = SchemaDescriptorV1(
        schema_version="1",
        fields=provisional.fields,
        schema_hash=schema_hash(provisional),
    )
    wrong_schema_manifest = dataset.manifest.model_copy(
        update={
            "schema_definition": wrong_schema,
            "partitions": (
                dataset.manifest.partitions[0].model_copy(
                    update={"schema_hash": wrong_schema.schema_hash}
                ),
            ),
        }
    )
    decision, _ = economic_validation.validate_economic_dataset(
        wrong_schema_manifest, dataset.verified_artifacts, dataset.validation_run
    )
    assert {finding.code for finding in decision.findings} == {
        "economic_role_schema_mismatch"
    }

    contract = dataset.manifest.temporal_contract.contract
    assert isinstance(contract, AssertionTemporalContractV1)
    wrong_contract = contract.model_copy(
        update={"semantic_state_field_ids": contract.semantic_state_field_ids[:-1]}
    )
    wrong_contract_manifest = dataset.manifest.model_copy(
        update={
            "temporal_contract": dataset.manifest.temporal_contract.model_copy(
                update={"contract": wrong_contract}
            )
        }
    )
    decision, _ = economic_validation.validate_economic_dataset(
        wrong_contract_manifest, dataset.verified_artifacts, dataset.validation_run
    )
    assert {finding.code for finding in decision.findings} == {
        "economic_role_contract_mismatch"
    }

    private_channel = AvailabilityChannelV1(
        kind=ChannelKind.VENDOR,
        identifier="private-feed",
        version="v1",
    )
    channel_contract = economic_validation.economic_role_contract(
        "economic_terms", (private_channel,)
    )
    channel_manifest = dataset.manifest.model_copy(
        update={
            "temporal_contract": dataset.manifest.temporal_contract.model_copy(
                update={"contract": channel_contract}
            )
        }
    )
    decision, _ = economic_validation.validate_economic_dataset(
        channel_manifest, dataset.verified_artifacts, dataset.validation_run
    )
    assert {finding.code for finding in decision.findings} == {
        "economic_undeclared_availability_channel"
    }

    foreign_values = {name: getattr(record, name) for name in type(record).model_fields}
    foreign_values["source_key"] = record.source_key.model_copy(
        update={"source_id": "other"}
    )
    foreign = rebind_record_evidence(type(record), foreign_values)
    foreign_bytes = canonical_json({"schema_version": "1", "records": (foreign,)})
    foreign_hash = sha256(foreign_bytes).hexdigest()
    foreign_manifest = dataset.manifest.model_copy(
        update={
            "partitions": (
                dataset.manifest.partitions[0].model_copy(
                    update={
                        "artifact": dataset.manifest.partitions[0].artifact.model_copy(
                            update={
                                "content_hash": foreign_hash,
                                "location": f"drift+sha256://{foreign_hash}",
                            }
                        ),
                        "byte_size": len(foreign_bytes),
                    }
                ),
            )
        }
    )
    foreign_artifact = VerifiedArtifactBytes(
        data=foreign_bytes,
        byte_size=len(foreign_bytes),
        content_hash=foreign_hash,
    )
    decision, _ = economic_validation.validate_economic_dataset(
        foreign_manifest, (foreign_artifact,), dataset.validation_run
    )
    assert "economic_source_id_mismatch" in {
        finding.code for finding in decision.findings
    }


def test_exact_validator_rejects_row_count_and_duplicate_records() -> None:
    record = settlement_record(401)
    dataset = economic_dataset("economic_settlement", (record,))
    wrong_count = dataset.manifest.model_copy(
        update={
            "partitions": (
                dataset.manifest.partitions[0].model_copy(update={"row_count": 2}),
            )
        }
    )
    decision, records = economic_validation.validate_economic_dataset(
        wrong_count, dataset.verified_artifacts, dataset.validation_run
    )
    assert decision.result is ValidationResult.FAIL
    assert records == ()
    assert {finding.code for finding in decision.findings} == {
        "economic_row_count_mismatch"
    }

    duplicate_bytes = canonical_json(
        {"schema_version": "1", "records": (record, record)}
    )
    duplicate_hash = sha256(duplicate_bytes).hexdigest()
    duplicate_manifest = dataset.manifest.model_copy(
        update={
            "partitions": (
                dataset.manifest.partitions[0].model_copy(
                    update={
                        "artifact": dataset.manifest.partitions[0].artifact.model_copy(
                            update={
                                "content_hash": duplicate_hash,
                                "location": f"drift+sha256://{duplicate_hash}",
                            }
                        ),
                        "byte_size": len(duplicate_bytes),
                        "row_count": 2,
                    }
                ),
            )
        }
    )
    duplicate_artifact = VerifiedArtifactBytes(
        data=duplicate_bytes,
        byte_size=len(duplicate_bytes),
        content_hash=duplicate_hash,
    )
    decision, records = economic_validation.validate_economic_dataset(
        duplicate_manifest, (duplicate_artifact,), dataset.validation_run
    )
    assert decision.result is ValidationResult.FAIL
    assert records == ()
    assert {finding.code for finding in decision.findings} == {
        "duplicate_economic_record_hash",
        "duplicate_record_hash",
        "duplicate_record_version_id",
        "multiple_initial_roots",
    }


def test_coverage_methodology_requires_exact_recognized_independent_profile() -> None:
    record = coverage_record(
        501,
        "terms",
        HASH_A,
        (HASH_A,),
        (HASH_B,),
    )
    exact = support_bytes(record.methodology_reference)
    assert economic_validation.economic_coverage_methodology_supported(record, (exact,))

    for statement in (
        "best in class complete coverage methodology",
        '{"kind":"coverage_methodology","methodology_version":"wrong"}',
    ):
        reference, artifact = economic_evidence(statement)
        changed = type(record).model_construct(
            **{
                **{name: getattr(record, name) for name in type(record).model_fields},
                "methodology_reference": reference,
            }
        )
        assert not economic_validation.economic_coverage_methodology_supported(
            changed, (artifact,)
        )
    mismatched = type(record).model_construct(
        **{
            **{name: getattr(record, name) for name in type(record).model_fields},
            "methodology_version": "different-version",
        }
    )
    assert not economic_validation.economic_coverage_methodology_supported(
        mismatched, (exact,)
    )


def test_coverage_methodology_rejects_wrong_capability_hash_length_and_extra_key() -> (
    None
):
    record = coverage_record(
        502,
        "effect",
        HASH_A,
        (HASH_A,),
        (HASH_B,),
    )
    valid = support_bytes(record.methodology_reference)
    document = __import__("json").loads(valid.data)
    variants = (
        document | {"revision_tracking": "marketing_claim"},
        document | {"extra": True},
    )
    for variant in variants:
        data = canonical_json(variant)
        digest = sha256(data).hexdigest()
        reference = type(record.methodology_reference).model_construct(
            **{
                **{
                    name: getattr(record.methodology_reference, name)
                    for name in type(record.methodology_reference).model_fields
                },
                "content_hash": digest,
            }
        )
        changed = type(record).model_construct(
            **{
                **{name: getattr(record, name) for name in type(record).model_fields},
                "methodology_reference": reference,
            }
        )
        artifact = VerifiedArtifactBytes(
            data=data, byte_size=len(data), content_hash=digest
        )
        assert not economic_validation.economic_coverage_methodology_supported(
            changed, (artifact,)
        )

    assert not economic_validation.economic_coverage_methodology_supported(
        record,
        (
            VerifiedArtifactBytes(
                data=valid.data,
                byte_size=len(valid.data) + 1,
                content_hash=valid.content_hash,
            ),
        ),
    )
    assert not economic_validation.economic_coverage_methodology_supported(
        record,
        (
            VerifiedArtifactBytes(
                data=valid.data + b" ",
                byte_size=len(valid.data) + 1,
                content_hash=valid.content_hash,
            ),
        ),
    )


def test_coverage_methodology_rejects_noncanonical_and_duplicate_key_bytes() -> None:
    record = coverage_record(503, "settlement", HASH_A, (HASH_A,), (HASH_B,))
    canonical = support_bytes(record.methodology_reference)
    document = json.loads(canonical.data)
    noncanonical = json.dumps(document, indent=2).encode()
    duplicate_key = canonical.data.replace(
        b'"schema_version":"1"',
        b'"schema_version":"1","schema_version":"1"',
        1,
    )
    for data in (noncanonical, duplicate_key):
        digest = sha256(data).hexdigest()
        reference = type(record.methodology_reference).model_construct(
            **{
                **{
                    name: getattr(record.methodology_reference, name)
                    for name in type(record.methodology_reference).model_fields
                },
                "content_hash": digest,
            }
        )
        changed = type(record).model_construct(
            **{
                **{name: getattr(record, name) for name in type(record).model_fields},
                "methodology_reference": reference,
            }
        )
        artifact = VerifiedArtifactBytes(
            data=data,
            byte_size=len(data),
            content_hash=digest,
        )
        assert not economic_validation.economic_coverage_methodology_supported(
            changed, (artifact,)
        )


def test_validated_context_rechecks_exact_inputs_and_hashes_queries() -> None:
    harness = validated_case(
        (terms_record(601), effect_record(602), settlement_record(603))
    )
    economic_validation.validate_economic_context(harness.context)
    context_hash = economic_validation.economic_context_hash(harness.context)
    assert context_hash != "0" * 64
    assert context_hash == economic_validation.economic_context_hash(harness.context)
    decision_query = harness.decision_query(
        "2021-01-02T00:00:00Z",
        "2021-01-02T00:00:00Z",
        "2021-01-01T00:00:00Z",
    )
    outcome_query = harness.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    assert decision_query.input_context_hash == context_hash
    assert outcome_query.input_context_hash == context_hash
    assert decision_query.source_selection_policy_hash == content_hash(
        harness.source_policy
    )


def test_context_rejects_omitted_records_decision_and_artifact_substitution() -> None:
    harness = validated_case((terms_record(611),))
    dataset = harness.context.datasets[0]
    mutations = (
        replace(dataset, records=()),
        replace(dataset, records=(*dataset.records, dataset.records[0])),
        replace(
            dataset,
            decision=dataset.decision.model_copy(
                update={"validation_profile_hash": HASH_A}
            ),
        ),
        replace(
            dataset,
            verified_artifacts=(
                VerifiedArtifactBytes(
                    data=dataset.verified_artifacts[0].data + b" ",
                    byte_size=dataset.verified_artifacts[0].byte_size + 1,
                    content_hash=dataset.verified_artifacts[0].content_hash,
                ),
            ),
        ),
    )
    for mutation in mutations:
        context = replace(
            harness.context,
            datasets=(mutation, *harness.context.datasets[1:]),
        )
        with pytest.raises(DatasetValidationError):
            economic_validation.validate_economic_context(context)


def test_context_requires_exact_closed_supporting_byte_set() -> None:
    harness = validated_case(
        (terms_record(621), effect_record(622), settlement_record(623))
    )
    support = harness.context.supporting_artifacts
    foreign_reference, foreign = economic_evidence("unreferenced supporting bytes")
    del foreign_reference
    corrupt = VerifiedArtifactBytes(
        data=support[0].data + b" ",
        byte_size=support[0].byte_size + 1,
        content_hash=support[0].content_hash,
    )
    mutations = (
        support[1:],
        (*support, support[0]),
        (*support, foreign),
        (corrupt, *support[1:]),
    )
    for supporting_artifacts in mutations:
        context = replace(harness.context, supporting_artifacts=supporting_artifacts)
        with pytest.raises(DatasetValidationError):
            economic_validation.require_m1c_evidence_closure(context)


def test_context_snapshots_mutable_inputs_and_hash_binds_retained_evidence() -> None:
    harness = validated_case((effect_record(631),))
    retained: dict[str, object] = {}
    context = economic_validation.EconomicResolutionContext(
        datasets=list(harness.context.datasets),  # type: ignore[arg-type]
        identity=harness.context.identity,
        availability_policy=harness.context.availability_policy,
        retained_evidence=retained,  # type: ignore[arg-type]
        supporting_artifacts=list(harness.context.supporting_artifacts),  # type: ignore[arg-type]
    )
    original_hash = economic_validation.economic_context_hash(context)
    retained[HASH_A] = object()
    assert context.datasets == harness.context.datasets
    assert context.supporting_artifacts == harness.context.supporting_artifacts
    assert dict(context.retained_evidence) == {}
    assert economic_validation.economic_context_hash(context) == original_hash


def test_context_allows_same_role_from_separate_source_bundles_only() -> None:
    harness = validated_case(())
    other = economic_dataset("economic_settlement", (), "synthetic-b")
    added_support = tuple(
        support_bytes(reference)
        for reference in (
            other.manifest.source.evidence_reference,
            other.manifest.acquisition.evidence_reference,
            other.manifest.license.terms_evidence_reference,
        )
    )
    supporting = {
        artifact.content_hash: artifact
        for artifact in (*harness.context.supporting_artifacts, *added_support)
    }
    context = replace(
        harness.context,
        datasets=(*harness.context.datasets, other),
        supporting_artifacts=tuple(supporting[key] for key in sorted(supporting)),
    )
    economic_validation.validate_economic_context(context)

    duplicate = replace(
        harness.context,
        datasets=(*harness.context.datasets, harness.context.datasets[0]),
    )
    with pytest.raises(DatasetValidationError, match="duplicate_economic_source_role"):
        economic_validation.validate_economic_context(duplicate)

    settlement = harness.context.datasets[2]
    with pytest.raises(ValueError, match="roles must be unique"):
        build_validated_dataset_bundle(
            settlement.bundle.bundle_id,
            "combined",
            settlement.bundle.created_at,
            (
                (settlement.manifest, settlement.decision),
                (other.manifest, other.decision),
            ),
        )


def test_context_rejects_false_coverage_inventory_and_invented_empty_marker() -> None:
    harness = validated_case((terms_record(641),))
    coverage_input = harness.context.datasets[-1]
    coverage = coverage_input.records[0]
    values = {name: getattr(coverage, name) for name in type(coverage).model_fields}
    values["inventory_record_hashes"] = (HASH_A,)
    false_inventory = rebind_coverage_evidence(values)
    changed_coverage_input = economic_dataset(
        "economic_coverage",
        (false_inventory, *coverage_input.records[1:]),
    )
    context = replace(
        harness.context,
        datasets=(*harness.context.datasets[:-1], changed_coverage_input),
    )
    with pytest.raises(DatasetValidationError, match="coverage_inventory_mismatch"):
        economic_validation.validate_economic_context(context)

    terms_input = harness.context.datasets[0]
    invented = replace(
        terms_input,
        decision=terms_input.decision.model_copy(
            update={
                "checked_contracts": tuple(
                    sorted(
                        {
                            *terms_input.decision.checked_contracts,
                            "economic-terms-v1-exact-empty",
                        }
                    )
                )
            }
        ),
    )
    with pytest.raises(DatasetValidationError, match="decision_mismatch"):
        economic_validation.validate_economic_context(
            replace(
                harness.context,
                datasets=(invented, *harness.context.datasets[1:]),
            )
        )


def test_closure_rejects_partition_self_reference_and_fake_reference() -> None:
    harness = validated_case((terms_record(651),))
    dataset = harness.context.datasets[0]
    record = dataset.records[0]
    partition_reference = dataset.manifest.partitions[0].artifact
    self_revision = type(record.revision).model_construct(
        **{
            **{
                name: getattr(record.revision, name)
                for name in type(record.revision).model_fields
            },
            "source_artifact": partition_reference,
        }
    )
    self_record = type(record).model_construct(
        **{
            **{name: getattr(record, name) for name in type(record).model_fields},
            "revision": self_revision,
        }
    )
    self_context = replace(
        harness.context,
        datasets=(
            replace(dataset, records=(self_record,)),
            *harness.context.datasets[1:],
        ),
    )
    with pytest.raises(DatasetValidationError, match="partition_self_reference"):
        economic_validation.require_m1c_evidence_closure(self_context)

    fake_reference, _ = economic_evidence("fabricated unretained source citation")
    fake_revision = type(record.revision).model_construct(
        **{
            **{
                name: getattr(record.revision, name)
                for name in type(record.revision).model_fields
            },
            "source_artifact": fake_reference,
        }
    )
    fake_record = type(record).model_construct(
        **{
            **{name: getattr(record, name) for name in type(record).model_fields},
            "revision": fake_revision,
        }
    )
    fake_context = replace(
        harness.context,
        datasets=(
            replace(dataset, records=(fake_record,)),
            *harness.context.datasets[1:],
        ),
    )
    with pytest.raises(DatasetValidationError, match="missing_supporting_artifact"):
        economic_validation.require_m1c_evidence_closure(fake_context)


def test_closure_reaches_effect_availability_fraction_and_methodology_references() -> (
    None
):
    effect = effect_record(661)
    effect_reference, _ = economic_evidence("independent effect evidence")
    assert effect.payload is not None and effect.payload.kind == "occurred"
    effect_payload = effect.payload.model_copy(
        update={"evidence_reference": effect_reference}
    )
    effect_values = {name: getattr(effect, name) for name in type(effect).model_fields}
    effect_values["payload"] = effect_payload
    effect = seal_record(type(effect), effect_values)

    availability_reference, _ = economic_evidence("independent availability evidence")
    terms = terms_record(662)
    terms_revision = terms.revision.model_copy(
        update={
            "availability": (
                public_availability("2020-05-01T00:00:00Z", availability_reference),
            )
        }
    )
    fraction_reference, _ = economic_evidence("independent fraction rule evidence")
    share = ShareComponentV1(
        kind="shares",
        component_id="share",
        recipient=EconomicRecipientV1(kind="security", security_id=terms.security_id),
        ratio=PositiveRatioV1(numerator="2", denominator="1"),
        ratio_meaning="resulting_per_predecessor",
        unit_basis=EconomicShareBasisV1(
            security_id=terms.security_id,
            share_basis="predecessor_pre_action",
        ),
        fraction_treatment=FractionTreatmentV1(
            kind="aggregate_sale_cash",
            source_rule="aggregate fractional shares and pay cash",
            evidence_reference=fraction_reference,
        ),
        applicability="ordinary_passive_holder",
        conditions=(),
    )
    assert terms.payload is not None
    terms_values = {name: getattr(terms, name) for name in type(terms).model_fields}
    terms_values["revision"] = terms_revision
    terms_values["payload"] = terms.payload.model_copy(update={"components": (share,)})
    terms = seal_record(type(terms), terms_values)

    harness = validated_case((terms, effect))
    methodology_hash = next(
        record.methodology_reference.content_hash
        for record in harness.context.datasets[-1].records
        if isinstance(record, EconomicCoverageVersionV1)
        and record.fact_family == "terms"
    )
    for required_hash in (
        effect_reference.content_hash,
        availability_reference.content_hash,
        fraction_reference.content_hash,
        methodology_hash,
    ):
        support = tuple(
            artifact
            for artifact in harness.context.supporting_artifacts
            if artifact.content_hash != required_hash
        )
        with pytest.raises(DatasetValidationError, match="missing_supporting_artifact"):
            economic_validation.require_m1c_evidence_closure(
                replace(harness.context, supporting_artifacts=support)
            )


def test_validated_case_rejects_early_snapshot_and_query_horizon_drift() -> None:
    with pytest.raises(ValueError, match="snapshot precedes"):
        validated_case(
            (terms_record(671),),
            coverage_snapshot_at="2021-01-01T00:00:00Z",
        )
    harness = validated_case(())
    with pytest.raises(ValueError, match="must equal policy through"):
        harness.outcome_query("2021-01-02T00:00:00Z", "2021-01-03T00:00:00Z")


def test_unknown_inventory_availability_cannot_build_complete_coverage() -> None:
    terms = terms_record(681)
    unknown = AvailabilityEvidenceV1(
        channel=public_channel(),
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
    values = {name: getattr(terms, name) for name in type(terms).model_fields}
    values["revision"] = terms.revision.model_copy(update={"availability": (unknown,)})
    terms = seal_record(type(terms), values)
    with pytest.raises(ValueError, match="unknown availability"):
        validated_case((terms,))
    partial = validated_case((terms,), complete_coverage=False)
    economic_validation.validate_economic_context(partial.context)


def test_context_rejects_resealed_coverage_snapshot_before_inventory_vintage() -> None:
    terms = terms_record(691, known_at="2020-06-04T00:00:00Z")
    harness = validated_case((terms,), through="2020-06-01T00:00:00Z")
    coverage_input = harness.context.datasets[-1]
    coverage = coverage_input.records[0]
    assert isinstance(coverage, EconomicCoverageVersionV1)
    values = {name: getattr(coverage, name) for name in type(coverage).model_fields}
    values["snapshot_at"] = parse_utc("2020-06-02T00:00:00Z")
    earlier = rebind_coverage_evidence(values)
    changed = economic_dataset(
        "economic_coverage", (earlier, *coverage_input.records[1:])
    )
    context = replace(
        harness.context,
        datasets=(*harness.context.datasets[:-1], changed),
    )
    with pytest.raises(DatasetValidationError, match="snapshot_precedes_inventory"):
        economic_validation.validate_economic_context(context)


def test_whole_manifest_inventory_can_include_an_unrelated_security() -> None:
    owned = terms_record(701)
    unrelated = terms_record(702)
    unrelated_values = {
        name: getattr(unrelated, name) for name in type(unrelated).model_fields
    }
    assert unrelated.payload is not None
    unrelated_component = unrelated.payload.components[0]
    assert hasattr(unrelated_component, "unit_basis")
    unrelated_values["security_id"] = uid(22)
    unrelated_values["payload"] = unrelated.payload.model_copy(
        update={
            "components": (
                unrelated_component.model_copy(
                    update={
                        "unit_basis": unrelated_component.unit_basis.model_copy(
                            update={"security_id": uid(22)}
                        )
                    }
                ),
            )
        }
    )
    unrelated = rebind_record_evidence(type(unrelated), unrelated_values)
    harness = validated_case((owned, unrelated))
    economic_validation.validate_economic_context(harness.context)


def test_whole_manifest_inventory_retains_attribution_correction_chain() -> None:
    original = terms_record(711)
    assert original.payload is not None
    component = original.payload.components[0]
    assert hasattr(component, "unit_basis")
    corrected_payload = original.payload.model_copy(
        update={
            "components": (
                component.model_copy(
                    update={
                        "unit_basis": component.unit_basis.model_copy(
                            update={"security_id": uid(22)}
                        )
                    }
                ),
            )
        }
    )
    corrected = revise_record(
        original,
        712,
        "2020-07-01T00:00:00Z",
        {"security_id": uid(22), "payload": corrected_payload},
    )
    harness = validated_case((original, corrected))
    economic_validation.validate_economic_context(harness.context)


def test_whole_manifest_inventory_preserves_optional_listing_context() -> None:
    record = terms_record(721)
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values["listing_id"] = uid(99)
    listed = rebind_record_evidence(type(record), values)
    harness = validated_case((listed,))
    coverage = harness.context.datasets[-1].records[0]
    assert isinstance(coverage, EconomicCoverageVersionV1)
    assert coverage.listing_id is None
    economic_validation.validate_economic_context(harness.context)
