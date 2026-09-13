"""Fixture-only exact-byte loader for the immutable current M1d v2 fixture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import manifest_hash
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
from drift.domain.economic_coverage import EconomicSourceSelectionPolicyV1
from drift.domain.manifests import DatasetManifestV2
from drift.domain.normalization import (
    DerivedObservationViewV1,
    FieldTransformV1,
    NormalizationQueryV1,
    NormalizationResultV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
)
from drift.domain.securities import (
    IdentityAssignmentVersionV1,
    IdentityRelationshipVersionV1,
    ListingHistoryCoverageVersionV1,
    ListingLifecycleVersionV1,
    ListingRoleVersionV1,
    ListingTerminationVersionV1,
    SecurityClassificationVersionV1,
)
from drift.domain.sessions import ScheduleArtifactV1
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
)
from drift.domain.universes import (
    ResearchUniverseDefinitionV1,
    SourceUniverseDefinitionVersionV1,
    UniverseMembershipVersionV1,
)
from drift.markets.economic_validation import (
    EconomicDatasetInput,
    EconomicIdentityInput,
    EconomicResolutionContext,
    validate_economic_context,
    validate_economic_dataset,
)
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
    verify_normalization,
)
from drift.markets.observation_validation import (
    M1dDatasetInput,
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
    validate_observation_dataset,
)
from drift.markets.session_generation import verify_schedule
from drift.markets.session_validation import validate_session_dataset
from drift.markets.universes import (
    StructuralResolutionContext,
    UniverseResolutionContext,
    ValidatedRecords,
)
from drift.markets.validation import validate_identity_dataset
from drift.serialization.canonical import canonical_json, content_hash

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "m1d" / "v2"
EXPECTED_HASH_INDEX_SHA256 = (
    "23dd18f8ba2626c6f68906ec3559d4552e8155be4cdca66ef09a6945ece1f2e6"
)

__all__ = (
    "EXPECTED_HASH_INDEX_SHA256",
    "FIXTURE_ROOT",
    "LoadedM1dFixtureV2",
    "assert_roundtrip_replays",
    "field",
    "load_m1d_fixture_v2",
    "materialize_result",
)

_LIMITS = ResolverLimits(max_bytes=64 * 1024 * 1024)


@dataclass(frozen=True)
class LoadedM1dFixtureV2:
    context: M1dResolutionContext
    decision_query: NormalizationQueryV1
    decision_result: NormalizationResultV1
    outcome_query: NormalizationQueryV1
    outcome_result: NormalizationResultV1
    schedule_artifact: ScheduleArtifactV1


class _DuplicateKey(ValueError):
    pass


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _canonical_document(data: bytes) -> Any:
    value = json.loads(data, object_pairs_hook=_pairs)
    if canonical_json(value) != data:
        raise ValueError("M1d fixture contains noncanonical JSON")
    return value


def _read_fixture_objects(
    root: Path,
) -> tuple[dict[str, bytes], dict[str, VerifiedArtifactBytes]]:
    index_artifact = read_verified_local_artifact(
        root, "hash-index.json", EXPECTED_HASH_INDEX_SHA256, _LIMITS
    )
    index = _canonical_document(index_artifact.data)
    if not isinstance(index, dict) or set(index) != {
        "schema_version",
        "fixture_version",
        "entries",
    }:
        raise ValueError("invalid M1d fixture hash index")
    if index["schema_version"] != "1" or index["fixture_version"] != "m1d/v2":
        raise ValueError("unexpected M1d fixture version")
    entries = index["entries"]
    if not isinstance(entries, list):
        raise TypeError("invalid M1d fixture hash entries")
    declared: dict[str, tuple[int, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "byte_size", "sha256"}:
            raise ValueError("invalid M1d fixture hash entry")
        path = entry["path"]
        size = entry["byte_size"]
        digest = entry["sha256"]
        if (
            not isinstance(path, str)
            or not isinstance(size, int)
            or not isinstance(digest, str)
        ):
            raise TypeError("invalid M1d fixture hash entry types")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or path == "hash-index.json":
            raise ValueError("unsafe M1d fixture path")
        if path in declared:
            raise ValueError("duplicate M1d fixture path")
        declared[path] = (size, digest)
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("M1d fixture may not contain symlinks")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(declared) | {"hash-index.json"}:
        raise ValueError("M1d fixture file inventory mismatch")
    files: dict[str, bytes] = {}
    objects: dict[str, VerifiedArtifactBytes] = {}
    for path, (size, digest) in declared.items():
        verified = read_verified_local_artifact(root, path, digest, _LIMITS)
        if verified.byte_size != size:
            raise ValueError("M1d fixture byte-size mismatch")
        files[path] = verified.data
        prefix = "objects/sha256/"
        if path.startswith(prefix):
            object_digest = path.removeprefix(prefix)
            if object_digest != digest:
                raise ValueError("content-addressed object path mismatch")
            objects[object_digest] = verified
    return files, objects


def _model[T: BaseModel](
    objects: dict[str, VerifiedArtifactBytes], digest: str, model: type[T]
) -> T:
    artifact = objects[digest]
    parsed = model.model_validate_json(artifact.data)
    if canonical_json(parsed) != artifact.data or content_hash(parsed) != digest:
        raise ValueError("fixture model object does not match its content address")
    return parsed


def _objects(
    objects: dict[str, VerifiedArtifactBytes], hashes: list[str]
) -> tuple[VerifiedArtifactBytes, ...]:
    return tuple(objects[digest] for digest in hashes)


def _check_bundles(
    descriptors: list[dict[str, Any]],
    loaded: list[Any],
    objects: dict[str, VerifiedArtifactBytes],
) -> None:
    for bundle_digest in {item["bundle"] for item in descriptors}:
        bundle = _model(objects, bundle_digest, ValidatedDatasetBundleV1)
        members = [
            (dataset.manifest, dataset.decision)
            for descriptor, dataset in zip(descriptors, loaded, strict=True)
            if descriptor["bundle"] == bundle_digest
        ]
        rebuilt = build_validated_dataset_bundle(
            bundle.bundle_id,
            bundle.bundle_version,
            bundle.created_at,
            members,
        )
        if rebuilt != bundle:
            raise ValueError("fixture validated bundle replay mismatch")


def _load_m1d_datasets(
    descriptors: list[dict[str, Any]],
    objects: dict[str, VerifiedArtifactBytes],
    support: dict[str, VerifiedArtifactBytes],
) -> tuple[M1dDatasetInput[Any], ...]:
    loaded: list[M1dDatasetInput[Any]] = []
    for descriptor in descriptors:
        manifest = _model(objects, descriptor["manifest"], DatasetManifestV2)
        run = _model(objects, descriptor["validation_run"], ValidationRunContextV1)
        stored_decision = _model(
            objects, descriptor["decision"], DatasetValidationDecisionV2
        )
        stored_bundle = _model(objects, descriptor["bundle"], ValidatedDatasetBundleV1)
        artifacts = {
            artifact.content_hash: artifact
            for artifact in _objects(objects, descriptor["partition_objects"])
        }
        role = manifest.dataset_role.name
        records: tuple[Any, ...]
        if role in {"source_observation", "observation_coverage"}:
            decision, observation_records = validate_observation_dataset(
                manifest, artifacts, run, support
            )
            records = observation_records
        else:
            decision, session_records = validate_session_dataset(
                manifest, artifacts, run, support
            )
            records = session_records
        if decision != stored_decision:
            raise ValueError("fixture M1d validation decision replay mismatch")
        loaded.append(
            M1dDatasetInput(
                manifest=manifest,
                validation_run=run,
                artifacts=artifacts,
                records=records,
                decision=decision,
                bundle=stored_bundle,
            )
        )
    _check_bundles(descriptors, loaded, objects)
    return tuple(loaded)


_M1B_MODELS: dict[str, type[BaseModel]] = {
    "IdentityAssignmentVersionV1": IdentityAssignmentVersionV1,
    "UniverseMembershipVersionV1": UniverseMembershipVersionV1,
    "SourceUniverseDefinitionVersionV1": SourceUniverseDefinitionVersionV1,
    "IdentityRelationshipVersionV1": IdentityRelationshipVersionV1,
    "SecurityClassificationVersionV1": SecurityClassificationVersionV1,
    "ListingRoleVersionV1": ListingRoleVersionV1,
    "ListingLifecycleVersionV1": ListingLifecycleVersionV1,
    "ListingTerminationVersionV1": ListingTerminationVersionV1,
    "ListingHistoryCoverageVersionV1": ListingHistoryCoverageVersionV1,
}


def _parse_record_objects(data: bytes, model: type[BaseModel]) -> tuple[BaseModel, ...]:
    document = _canonical_document(data)
    if not isinstance(document, dict) or set(document) != {"schema_version", "records"}:
        raise ValueError("invalid fixture record envelope")
    if document["schema_version"] != "1" or not isinstance(document["records"], list):
        raise ValueError("invalid fixture record envelope")
    return tuple(
        model.model_validate_json(canonical_json(item)) for item in document["records"]
    )


def _load_m1b(
    descriptor: dict[str, Any], objects: dict[str, VerifiedArtifactBytes]
) -> tuple[
    StructuralResolutionContext,
    ResearchUniverseDefinitionV1,
    UUID,
    str,
    AvailabilityChannelV1,
]:
    records_by_name: dict[str, ValidatedRecords[Any]] = {}
    collection_descriptors = descriptor["collections"]
    for item in collection_descriptors:
        manifest = _model(objects, item["manifest"], DatasetManifestV2)
        run = _model(objects, item["validation_run"], ValidationRunContextV1)
        decision = _model(objects, item["decision"], DatasetValidationDecisionV2)
        artifacts = _objects(objects, item["partition_objects"])
        if validate_identity_dataset(manifest, artifacts, run) != decision:
            raise ValueError("fixture M1b validation decision replay mismatch")
        model = _M1B_MODELS[item["record_model"]]
        parsed = tuple(
            record
            for artifact in artifacts
            for record in _parse_record_objects(artifact.data, model)
        )
        records_by_name[item["name"]] = ValidatedRecords(
            records=parsed, manifest=manifest, decision=decision
        )
    identity_bundle = _model(
        objects, descriptor["identity_bundle"], ValidatedDatasetBundleV1
    )
    universe_bundle = _model(
        objects, descriptor["universe_bundle"], ValidatedDatasetBundleV1
    )
    for bundle in (identity_bundle, universe_bundle):
        selected = [
            value
            for value in records_by_name.values()
            if manifest_hash(value.manifest)
            in {member.manifest_hash for member in bundle.members}
        ]
        rebuilt = build_validated_dataset_bundle(
            bundle.bundle_id,
            bundle.bundle_version,
            bundle.created_at,
            [(value.manifest, value.decision) for value in selected],
        )
        if rebuilt != bundle:
            raise ValueError("fixture M1b bundle replay mismatch")
    policy = _model(objects, descriptor["availability_policy"], AvailabilityPolicyV1)
    retained = {
        digest: _model(objects, object_hash, AvailabilityEvidenceV1)
        for digest, object_hash in descriptor["retained_evidence"].items()
    }
    universe = UniverseResolutionContext(
        identity_bundle=identity_bundle,
        universe_bundle=universe_bundle,
        assignments=records_by_name["assignments"],
        memberships=records_by_name["memberships"],
        source_definitions=records_by_name["source_definitions"],
        policy=policy,
        retained_evidence=retained,
    )
    structural = StructuralResolutionContext(
        universe=universe,
        relationships=records_by_name["relationships"],
        classifications=records_by_name["classifications"],
        roles=records_by_name["roles"],
        lifecycle=records_by_name["lifecycle"],
        terminations=records_by_name["terminations"],
        coverage=records_by_name["coverage"],
    )
    return (
        structural,
        _model(
            objects, descriptor["research_definition"], ResearchUniverseDefinitionV1
        ),
        UUID(descriptor["issuer_id"]),
        descriptor["structural_methodology_id"],
        _model(objects, descriptor["requested_channel"], AvailabilityChannelV1),
    )


def _load_economic_dataset(
    descriptor: dict[str, Any], objects: dict[str, VerifiedArtifactBytes]
) -> EconomicDatasetInput:
    manifest = _model(objects, descriptor["manifest"], DatasetManifestV2)
    run = _model(objects, descriptor["validation_run"], ValidationRunContextV1)
    stored_decision = _model(
        objects, descriptor["decision"], DatasetValidationDecisionV2
    )
    bundle = _model(objects, descriptor["bundle"], ValidatedDatasetBundleV1)
    artifacts = _objects(objects, descriptor["partition_objects"])
    decision, records = validate_economic_dataset(manifest, artifacts, run)
    if decision != stored_decision:
        raise ValueError("fixture M1c validation decision replay mismatch")
    return EconomicDatasetInput(
        records=records,
        manifest=manifest,
        decision=decision,
        verified_artifacts=artifacts,
        validation_run=run,
        bundle=bundle,
    )


def _load_m1c(
    descriptor: dict[str, Any], objects: dict[str, VerifiedArtifactBytes]
) -> tuple[EconomicResolutionContext, EconomicSourceSelectionPolicyV1]:
    datasets = tuple(
        _load_economic_dataset(item, objects) for item in descriptor["datasets"]
    )
    _check_bundles(descriptor["datasets"], list(datasets), objects)
    identity_descriptor = descriptor["identity"]
    manifest = _model(objects, identity_descriptor["manifest"], DatasetManifestV2)
    run = _model(objects, identity_descriptor["validation_run"], ValidationRunContextV1)
    decision = _model(
        objects, identity_descriptor["decision"], DatasetValidationDecisionV2
    )
    bundle = _model(objects, identity_descriptor["bundle"], ValidatedDatasetBundleV1)
    artifacts = _objects(objects, identity_descriptor["partition_objects"])
    if validate_identity_dataset(manifest, artifacts, run) != decision:
        raise ValueError("fixture economic identity decision replay mismatch")
    records = tuple(
        cast(IdentityAssignmentVersionV1, record)
        for artifact in artifacts
        for record in _parse_record_objects(artifact.data, IdentityAssignmentVersionV1)
    )
    identity = EconomicIdentityInput(
        records=records,
        manifest=manifest,
        decision=decision,
        verified_artifacts=artifacts,
        validation_run=run,
        bundle=bundle,
    )
    rebuilt_identity_bundle = build_validated_dataset_bundle(
        bundle.bundle_id,
        bundle.bundle_version,
        bundle.created_at,
        [(manifest, decision)],
    )
    if rebuilt_identity_bundle != bundle:
        raise ValueError("fixture economic identity bundle replay mismatch")
    context = EconomicResolutionContext(
        datasets=datasets,
        identity=identity,
        availability_policy=_model(
            objects, descriptor["availability_policy"], AvailabilityPolicyV1
        ),
        retained_evidence={
            digest: _model(objects, object_hash, AvailabilityEvidenceV1)
            for digest, object_hash in descriptor["retained_evidence"].items()
        },
        supporting_artifacts=_objects(objects, descriptor["supporting_artifacts"]),
    )
    validate_economic_context(context)
    return (
        context,
        _model(objects, descriptor["source_policy"], EconomicSourceSelectionPolicyV1),
    )


def _load_context(
    data: bytes, objects: dict[str, VerifiedArtifactBytes]
) -> M1dResolutionContext:
    descriptor = _canonical_document(data)
    support = {
        digest: objects[object_hash]
        for digest, object_hash in descriptor["supporting_artifacts"].items()
    }
    observations = _load_m1d_datasets(
        descriptor["observation_datasets"], objects, support
    )
    sessions = _load_m1d_datasets(descriptor["session_datasets"], objects, support)
    m1b_values: tuple[Any, Any, Any, Any, Any] = (None, None, None, None, None)
    if "m1b" in descriptor:
        m1b_values = _load_m1b(descriptor["m1b"], objects)
    economic_context = None
    economic_policy = None
    if "m1c" in descriptor:
        economic_context, economic_policy = _load_m1c(descriptor["m1c"], objects)
    context = M1dResolutionContext(
        observation_datasets=cast(Any, observations),
        session_datasets=cast(Any, sessions),
        availability_policies={
            digest: _model(objects, object_hash, AvailabilityPolicyV1)
            for digest, object_hash in descriptor["availability_policies"].items()
        },
        retained_evidence={
            digest: _model(objects, object_hash, AvailabilityEvidenceV1)
            for digest, object_hash in descriptor["retained_evidence"].items()
        },
        supporting_artifacts=support,
        structural_context=m1b_values[0],
        research_definition=m1b_values[1],
        issuer_id=m1b_values[2],
        structural_methodology_id=m1b_values[3],
        m1b_requested_channel=m1b_values[4],
        schedule_generation_policy_hash=descriptor["schedule_generation_policy_hash"],
        economic_context=economic_context,
        economic_source_policy=economic_policy,
    )
    validate_m1d_resolution_context(context)
    if m1d_context_hash(context) != descriptor["context_hash"]:
        raise ValueError("fixture M1d context hash mismatch")
    return context


def load_m1d_fixture_v2(root: Path = FIXTURE_ROOT) -> LoadedM1dFixtureV2:
    files, objects = _read_fixture_objects(root)
    context = _load_context(files["joined-context.json"], objects)
    decision_query = NormalizationQueryV1.model_validate_json(
        files["expected-decision-query.json"]
    )
    decision_result = NormalizationResultV1.model_validate_json(
        files["expected-decision-result.json"]
    )
    outcome_query = NormalizationQueryV1.model_validate_json(
        files["expected-outcome-query.json"]
    )
    outcome_result = NormalizationResultV1.model_validate_json(
        files["expected-outcome-result.json"]
    )
    if decision_result.query != decision_query or outcome_result.query != outcome_query:
        raise ValueError("fixture expected query/result mismatch")
    for query in (decision_query, outcome_query):
        if query.observation.input_context_hash != m1d_context_hash(context):
            raise ValueError("fixture query is not pinned to joined context")
    assert_roundtrip_replays(decision_result, context)
    assert_roundtrip_replays(outcome_result, context)
    materialize_result(decision_result, context)
    materialize_result(outcome_result, context)
    schedule_artifact = ScheduleArtifactV1.model_validate_json(
        files["joined-schedule-result.json"]
    )
    verify_schedule(schedule_artifact, context)
    return LoadedM1dFixtureV2(
        context=context,
        decision_query=decision_query,
        decision_result=decision_result,
        outcome_query=outcome_query,
        outcome_result=outcome_result,
        schedule_artifact=schedule_artifact,
    )


def assert_roundtrip_replays(
    result: NormalizationResultV1, context: M1dResolutionContext
) -> None:
    loaded = NormalizationResultV1.model_validate_json(result.model_dump_json())
    verify_normalization(loaded, context)
    assert loaded == result


def materialize_result(
    result: NormalizationResultV1, context: M1dResolutionContext
) -> DerivedObservationViewV1:
    reference = result.reference
    if isinstance(reference, ObservationDecisionReferenceV1):
        return materialize_observation_decision(reference, result.query, context)
    if isinstance(reference, ObservationOutcomeReferenceV1):
        return materialize_observation_outcome(reference, result.query, context)
    raise AssertionError("materialized fixture requires a role-specific reference")


def field(result: NormalizationResultV1, name: str) -> FieldTransformV1:
    if result.view is None:
        raise AssertionError("field lookup requires a materialized view")
    return next(item for item in result.view.fields if item.field_name == name)
