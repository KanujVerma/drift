"""Immutable M1c economic-history fixture loading contracts."""

import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.resolver import (
    ResolverLimits,
    VerifiedArtifactBytes,
    read_verified_local_artifact,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    ValidatedDatasetBundleV1,
    ValidationRunContextV1,
)
from drift.domain.economic_common import CashComponentV1
from drift.domain.economic_coverage import (
    EconomicCoverageVersionV1,
    EconomicSourceSelectionPolicyV1,
)
from drift.domain.economic_events import EconomicSettlementVersionV1
from drift.domain.manifests import DatasetManifestV2
from drift.domain.securities import IdentityAssignmentVersionV1
from drift.domain.temporal import AvailabilityPolicyV1
from drift.errors import ArtifactIntegrityError
from drift.markets.economic_outcomes import (
    resolve_economic_facts,
    verify_economic_outcome,
)
from drift.markets.economic_selection import select_market_records
from drift.markets.economic_validation import (
    EconomicDatasetInput,
    EconomicIdentityInput,
    EconomicResolutionContext,
    validate_economic_context,
    validate_economic_dataset,
)
from drift.markets.validation import validate_identity_dataset
from drift.serialization.canonical import content_hash

_FIXTURE_FILES = (
    "terms.json",
    "effects.json",
    "settlements-a.json",
    "settlements-b.json",
    "coverage-a.json",
    "coverage-b.json",
    "methodology-a.json",
    "methodology-b.json",
    "manifests.json",
    "policy.json",
    "identity.json",
    "support.json",
)
_EXPECTED_HASH_INDEX = (
    "90eb1764cb1f2ee25b84b2c138340e55d51fbe880237c6b59d53ecdab8bbac10"
)

_FIRST_INSTALLMENT_HASH = (
    "2d8b6c9181b268b471b7a7d6cb86a2d96a9418dd9f3e1bd9f30f58bf179c05c3"
)
_FIRST_CORROBORATION_HASH = (
    "aca7e6cc1767fdff01133d42a22c4dde4bc6e5d270d1c8019d785f268193d0c0"
)
_SECOND_INITIAL_HASH = (
    "ace97d2bb1dbc16f879eff243ba75e0c7c3663d06c550c74add30b9456d5f70b"
)
_SECOND_CORRECTED_HASH = (
    "4fe89719bab1674c14391a8e82bf7977f29b80a4554cabff60a481187ac09248"
)
_METHOD_A_HASH = "b88db2b7d78ae1d6a7ab3a3b55f6db5c523f343867068c44a8c0ea437bd312d1"
_METHOD_B_HASH = "1dc0a9375c2e7c8a1ae03c6793c126974fd486a3705dbb3fb8c2d65999aad9ac"
_CORRECTED_COVERAGE_HASHES = {
    "terms": "58413a68a09737c3c908008a220bbaa8795bf7db2db47f8ac73aa2b4f5df9ded",
    "effect": "da4fb2ab9c1ced53058cca71533f0ef246e8fb4d1ff0a6e74e42d52c1ea6f871",
    "settlement": "0a45dab262355447709a0d0636192152e5495c2d165643bc7f6044b62763e748",
}

_ROLE_PARTITIONS = {
    "economic_terms": ("terms.json",),
    "economic_effect": ("effects.json",),
    "economic_settlement": ("settlements-a.json", "settlements-b.json"),
    "economic_coverage": ("coverage-a.json", "coverage-b.json"),
}

_UNIT_PATH = Path(__file__).parents[1] / "unit"
if str(_UNIT_PATH) not in sys.path:
    sys.path.insert(0, str(_UNIT_PATH))
from economic_test_support import EconomicHarness  # noqa: E402


def _json(data: bytes) -> object:
    return json.loads(data)


def _model_json[T: BaseModel](model: type[T], value: object) -> T:
    return model.model_validate_json(json.dumps(value))


def _read(root: Path, expected: dict[str, object], name: str) -> VerifiedArtifactBytes:
    digest = expected.get(name)
    if not isinstance(digest, str):
        raise ValueError(f"fixture has no pinned digest for {name}")
    return read_verified_local_artifact(
        root, name, digest, ResolverLimits(max_bytes=2_000_000)
    )


def load_m1c_history(root: Path) -> EconomicHarness:
    """Load a closed history from exact, independently pinned local bytes."""
    expected_artifact = read_verified_local_artifact(
        root,
        "expected-hashes.json",
        _EXPECTED_HASH_INDEX,
        ResolverLimits(max_bytes=2_000_000),
    )
    expected = _json(expected_artifact.data)
    if not isinstance(expected, dict):
        raise ValueError("fixture expected hashes must be an object")
    raw = {name: _read(root, expected, name) for name in _FIXTURE_FILES}
    support_index = _json(raw["support.json"].data)
    if not isinstance(support_index, dict) or not isinstance(
        support_index.get("support_files"), list
    ):
        raise ValueError("fixture support index is invalid")
    indexed_supports = tuple(
        _read(root, expected, name)
        for name in support_index["support_files"]
        if isinstance(name, str)
    )
    descriptors = _json(raw["manifests.json"].data)
    if not isinstance(descriptors, dict) or not isinstance(
        descriptors.get("economic"), list
    ):
        raise ValueError("fixture manifests are invalid")
    by_hash = {artifact.content_hash: artifact for artifact in raw.values()}
    datasets: list[EconomicDatasetInput] = []
    for entry in descriptors["economic"]:
        if not isinstance(entry, dict):
            raise ValueError("economic descriptor is invalid")
        manifest = _model_json(DatasetManifestV2, entry["manifest"])
        run = _model_json(ValidationRunContextV1, entry["run"])
        stored = _model_json(DatasetValidationDecisionV2, entry["decision"])
        stored_bundle = _model_json(ValidatedDatasetBundleV1, entry["bundle"])
        artifacts = tuple(
            by_hash[item.artifact.content_hash] for item in manifest.partitions
        )
        decision, records = validate_economic_dataset(manifest, artifacts, run)
        if decision != stored:
            raise ValueError("fixture economic validation replay changed")
        bundle = build_validated_dataset_bundle(
            bundle_id=stored_bundle.bundle_id,
            bundle_version=stored_bundle.bundle_version,
            created_at=stored_bundle.created_at,
            validated_datasets=((manifest, decision),),
        )
        if bundle != stored_bundle:
            raise ValueError("fixture economic bundle replay changed")
        datasets.append(
            EconomicDatasetInput(records, manifest, decision, artifacts, run, bundle)
        )
    datasets_by_role = {
        dataset.manifest.dataset_role.name: dataset for dataset in datasets
    }
    if set(datasets_by_role) != set(_ROLE_PARTITIONS):
        raise ValueError("fixture economic roles do not match the closed inventory")
    for role, names in _ROLE_PARTITIONS.items():
        actual_hashes = {
            artifact.content_hash
            for artifact in datasets_by_role[role].verified_artifacts
        }
        expected_hashes = {raw[name].content_hash for name in names}
        if actual_hashes != expected_hashes:
            raise ValueError(f"fixture {role} partitions do not match named inputs")
    record_hashes = sorted(
        content_hash(record) for dataset in datasets for record in dataset.records
    )
    if record_hashes != expected.get("economic_record_hashes"):
        raise ValueError("fixture economic record hashes do not match pins")
    if expected.get("lineage_record_hashes") != {
        "first_installment": _FIRST_INSTALLMENT_HASH,
        "first_installment_corroboration": _FIRST_CORROBORATION_HASH,
        "second_installment_initial": _SECOND_INITIAL_HASH,
        "second_installment_corrected": _SECOND_CORRECTED_HASH,
    }:
        raise ValueError("fixture lineage record hashes do not match literal pins")
    identity_manifest = _model_json(DatasetManifestV2, descriptors["identity_manifest"])
    identity_run = _model_json(ValidationRunContextV1, descriptors["identity_run"])
    identity_decision = _model_json(
        DatasetValidationDecisionV2, descriptors["identity_decision"]
    )
    stored_identity_bundle = _model_json(
        ValidatedDatasetBundleV1, descriptors["identity_bundle"]
    )
    identity_artifacts = (raw["identity.json"],)
    if (
        validate_identity_dataset(identity_manifest, identity_artifacts, identity_run)
        != identity_decision
    ):
        raise ValueError("fixture identity validation replay changed")
    identity_document = _json(raw["identity.json"].data)
    if not isinstance(identity_document, dict) or not isinstance(
        identity_document.get("records"), list
    ):
        raise ValueError("fixture identity partition is invalid")
    identity_bundle = build_validated_dataset_bundle(
        bundle_id=stored_identity_bundle.bundle_id,
        bundle_version=stored_identity_bundle.bundle_version,
        created_at=stored_identity_bundle.created_at,
        validated_datasets=((identity_manifest, identity_decision),),
    )
    if identity_bundle != stored_identity_bundle:
        raise ValueError("fixture identity bundle replay changed")
    identity = EconomicIdentityInput(
        records=tuple(
            _model_json(IdentityAssignmentVersionV1, item)
            for item in identity_document["records"]
        ),
        manifest=identity_manifest,
        decision=identity_decision,
        verified_artifacts=identity_artifacts,
        validation_run=identity_run,
        bundle=identity_bundle,
    )
    policy_document = _json(raw["policy.json"].data)
    if not isinstance(policy_document, dict):
        raise ValueError("fixture policy is invalid")
    policy = _model_json(EconomicSourceSelectionPolicyV1, policy_document["policy"])
    availability = _model_json(
        AvailabilityPolicyV1, policy_document["availability_policy"]
    )
    if content_hash(policy) != expected.get("economic_policy_model_hash"):
        raise ValueError("fixture policy model hash mismatch")
    if str(policy.security_id) != expected.get("fixture_security_id"):
        raise ValueError("fixture policy security does not match pinned history")
    methodology_pins = expected.get("methodology_hashes")
    if not isinstance(methodology_pins, dict):
        raise ValueError("fixture methodology pins are invalid")
    named_methodologies = (
        raw["methodology-a.json"],
        raw["methodology-b.json"],
    )
    if methodology_pins != {"a": _METHOD_A_HASH, "b": _METHOD_B_HASH}:
        raise ValueError("fixture methodology hashes do not match literal pins")
    expected_methodology_hashes = {_METHOD_A_HASH, _METHOD_B_HASH}
    named_methodology_hashes = {
        artifact.content_hash for artifact in named_methodologies
    }
    coverage_methodology_hashes = {
        record.methodology_reference.content_hash
        for record in datasets_by_role["economic_coverage"].records
        if isinstance(record, EconomicCoverageVersionV1)
    }
    if (
        named_methodology_hashes != expected_methodology_hashes
        or coverage_methodology_hashes != expected_methodology_hashes
    ):
        raise ValueError("fixture named methodologies are not the referenced profiles")
    context = EconomicResolutionContext(
        tuple(datasets),
        identity,
        availability,
        {},
        (*named_methodologies, *indexed_supports),
    )
    validate_economic_context(context)
    return EconomicHarness(context=context, source_policy=policy)


def test_m1c_fixture_preserves_installment_lineage() -> None:
    root = Path(__file__).parents[1] / "fixtures" / "m1c" / "v1" / "liquidation"
    case = load_m1c_history(root)
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    verify_economic_outcome(result, case.context, case.source_policy)
    groups = {group.native_occurrence_id: group for group in result.delivery_groups}

    assert len(result.delivery_groups) == 2
    assert set(groups) == {"liquidation-1", "liquidation-2"}
    first = groups["liquidation-1"]
    second = groups["liquidation-2"]
    assert len(first.delivered_components) == 1
    assert len(second.delivered_components) == 1
    assert isinstance(first.delivered_components[0], CashComponentV1)
    assert isinstance(second.delivered_components[0], CashComponentV1)
    assert first.delivered_components[0].amount == "5"
    assert second.delivered_components[0].amount == "5"
    assert first.contributing_record_hashes == (
        _FIRST_INSTALLMENT_HASH,
        _FIRST_CORROBORATION_HASH,
    )
    assert second.contributing_record_hashes == (_SECOND_CORRECTED_HASH,)
    assert first.residual_status == "unknown"
    assert second.residual_status == "unknown"
    assert result.uncomposed_settlement_hashes == ()
    assert result.support_status == "supported"
    assert result.evidence_completeness == "partial"
    assert "settlement_residual_unresolved" in result.reasons


def test_m1c_fixture_selects_corrected_installment_revision() -> None:
    root = Path(__file__).parents[1] / "fixtures" / "m1c" / "v1" / "liquidation"
    case = load_m1c_history(root)
    old_query = case.outcome_query("2021-01-01T00:00:00Z", "2020-07-01T00:00:00Z")
    corrected_query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    old_proof = select_market_records(old_query, case.context, case.source_policy)
    corrected_proof = select_market_records(
        corrected_query, case.context, case.source_policy
    )
    settlement_versions = sorted(
        (
            record
            for dataset in case.context.datasets
            if dataset.manifest.dataset_role.name == "economic_settlement"
            for record in dataset.records
            if isinstance(record, EconomicSettlementVersionV1)
            if record.occurrence.native_occurrence_id == "liquidation-2"
        ),
        key=lambda record: record.revision.source_sequence,
    )

    assert len(settlement_versions) == 2
    assert [record.revision.source_sequence for record in settlement_versions] == [0, 1]
    assert settlement_versions[1].revision.supersedes_record_version_id == (
        settlement_versions[0].revision.record_version_id
    )
    assert [content_hash(record) for record in settlement_versions] == [
        _SECOND_INITIAL_HASH,
        _SECOND_CORRECTED_HASH,
    ]
    initial_payload = settlement_versions[0].payload
    corrected_payload = settlement_versions[1].payload
    assert initial_payload is not None
    assert corrected_payload is not None
    assert len(initial_payload.delivered_components) == 1
    assert len(corrected_payload.delivered_components) == 1
    initial_cash = initial_payload.delivered_components[0]
    corrected_cash = corrected_payload.delivered_components[0]
    assert isinstance(initial_cash, CashComponentV1)
    assert isinstance(corrected_cash, CashComponentV1)
    assert (
        initial_cash.currency_namespace,
        initial_cash.currency_code,
        initial_cash.amount,
    ) == ("ISO-4217", "USD", "4")
    assert (
        corrected_cash.currency_namespace,
        corrected_cash.currency_code,
        corrected_cash.amount,
    ) == ("ISO-4217", "USD", "5")
    assert _SECOND_INITIAL_HASH in old_proof.revision_selected_record_hashes
    assert _SECOND_CORRECTED_HASH not in old_proof.revision_selected_record_hashes
    assert _SECOND_CORRECTED_HASH in corrected_proof.revision_selected_record_hashes
    assert _SECOND_INITIAL_HASH not in corrected_proof.revision_selected_record_hashes

    old_result = resolve_economic_facts(old_query, case.context, case.source_policy)
    verify_economic_outcome(old_result, case.context, case.source_policy)
    assert old_result.delivery_groups == ()
    assert old_result.uncomposed_settlement_hashes == (
        _FIRST_INSTALLMENT_HASH,
        _FIRST_CORROBORATION_HASH,
        _SECOND_INITIAL_HASH,
    )
    assert old_result.support_status == "supported"
    assert old_result.evidence_completeness == "partial"
    assert {coverage.status for coverage in old_result.coverage_results} == {"unknown"}

    coverage_records = sorted(
        (
            record
            for dataset in case.context.datasets
            if dataset.manifest.dataset_role.name == "economic_coverage"
            for record in dataset.records
            if isinstance(record, EconomicCoverageVersionV1)
        ),
        key=lambda record: (record.fact_family, record.revision.source_sequence),
    )
    assert len(coverage_records) == 6
    for family in ("terms", "effect", "settlement"):
        versions = [
            record for record in coverage_records if record.fact_family == family
        ]
        assert [record.revision.source_sequence for record in versions] == [0, 1]
        assert versions[1].revision.supersedes_record_version_id == (
            versions[0].revision.record_version_id
        )
        assert [record.methodology_version for record in versions] == [
            "fixture-liquidation-method-a",
            "fixture-liquidation-method-b",
        ]
        assert [record.methodology_reference.content_hash for record in versions] == [
            _METHOD_A_HASH,
            _METHOD_B_HASH,
        ]
    assert {
        coverage.family: coverage.selected_coverage_hashes
        for coverage in resolve_economic_facts(
            corrected_query, case.context, case.source_policy
        ).coverage_results
    } == {family: (digest,) for family, digest in _CORRECTED_COVERAGE_HASHES.items()}


def test_m1c_fixture_rejects_pinned_partition_tampering(tmp_path: Path) -> None:
    root = Path(__file__).parents[1] / "fixtures" / "m1c" / "v1" / "liquidation"
    target = tmp_path / "liquidation"
    import shutil

    shutil.copytree(root, target)
    target.joinpath("settlements-a.json").write_bytes(
        b'{"schema_version":"1","records":[]}'
    )
    with pytest.raises(ArtifactIntegrityError):
        load_m1c_history(target)


def test_m1c_fixture_rejects_expected_hash_index_tampering(tmp_path: Path) -> None:
    root = Path(__file__).parents[1] / "fixtures" / "m1c" / "v1" / "liquidation"
    target = tmp_path / "liquidation"
    import shutil

    shutil.copytree(root, target)
    target.joinpath("expected-hashes.json").write_bytes(b"{}")
    with pytest.raises(ArtifactIntegrityError):
        load_m1c_history(target)
