"""Exact-file universe evidence composed with the retained Task 3 identity bundle."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from test_m1b_identity_history import canonical_task3_context, fixture_context

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.resolver import ResolverLimits, read_verified_local_artifact
from drift.domain.assertions import (
    InformationRole,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
)
from drift.domain.dataset_validation import DatasetValidationError, ValidationResult
from drift.domain.manifests import AssertionEffectiveShape, TemporalContractBindingV2
from drift.domain.securities import (
    IdentityKind,
    IdentityReferenceV1,
    ListingV1,
    ListingVenue,
)
from drift.domain.universes import (
    ResearchUniverseDefinitionV1,
    SourceUniverseDefinitionVersionV1,
    UniverseDefinitionSubjectV1,
    UniverseMembershipVersionV1,
    UniverseTargetLevel,
)
from drift.markets.universes import (
    STRICT_CLASSIFICATION_CONTRACT_HASH,
    StructuralResolutionContext,
    UniverseResolutionContext,
    ValidatedRecords,
    membership_subject,
    resolve_source_universe_definition,
    resolve_structural_eligibility,
    resolve_universe_membership,
    structural_subject,
)
from drift.markets.validation import (
    SOURCE_UNIVERSE_DEFINITION_SCHEMA_V1,
    UNIVERSE_MEMBERSHIP_SCHEMA_V1,
    validate_identity_dataset,
)
from drift.serialization.canonical import canonical_json, content_hash

ROOT = Path(__file__).parents[1] / "fixtures" / "datasets" / "m1b"
FIXTURES = {
    "source_universe_definition": (
        "source-universe-definitions.json",
        "b5969daa4a462d0c56b1ea862fca2b10e4ede2dfd8838f7df095c359ccae0c9d",
    ),
    "universe_membership": (
        "universe-memberships.json",
        "04ad72661ffc6741d9ad0c8081a7d09a1bb55a8083e920ea0226e92f37ebea0a",
    ),
}


def identifier(number: int) -> UUID:
    return UUID(f"019b8240-0000-7000-8000-{number:012d}")


def universe_fixture_context() -> tuple[
    ResearchUniverseDefinitionV1, StructuralResolutionContext
]:
    identity = canonical_task3_context()
    datasets: dict[str, ValidatedRecords[Any]] = {}
    for index, (role, (filename, digest)) in enumerate(FIXTURES.items()):
        verified = read_verified_local_artifact(
            ROOT, filename, digest, ResolverLimits(max_bytes=200_000)
        )
        document = json.loads(verified.data)
        model = (
            SourceUniverseDefinitionVersionV1
            if role == "source_universe_definition"
            else UniverseMembershipVersionV1
        )
        records = tuple(
            model.model_validate_json(canonical_json(record))
            for record in document["records"]
        )
        schema = (
            SOURCE_UNIVERSE_DEFINITION_SCHEMA_V1
            if role == "source_universe_definition"
            else UNIVERSE_MEMBERSHIP_SCHEMA_V1
        )
        effective = (
            "effective_interval"
            if role == "source_universe_definition"
            else "effective_time"
        )
        base = identity.manifests["security_classification"]
        contract = base.temporal_contract.contract.model_copy(
            update={
                "effective_time_field_id": effective,
                "effective_shape": AssertionEffectiveShape.INTERVAL
                if role == "source_universe_definition"
                else AssertionEffectiveShape.BOUNDARY,
                "semantic_state_field_ids": tuple(
                    sorted(
                        field.field_id
                        for field in schema.fields
                        if field.field_id not in {"schema_version", effective}
                        and not field.field_id.startswith("revision.")
                    )
                ),
            }
        )
        partition = base.partitions[0].model_copy(
            update={
                "artifact": base.partitions[0].artifact.model_copy(
                    update={
                        "content_hash": digest,
                        "location": f"drift+sha256://{digest}",
                    }
                ),
                "byte_size": verified.byte_size,
                "row_count": len(records),
                "schema_hash": schema.schema_hash,
            }
        )
        manifest = base.model_copy(
            update={
                "dataset_id": identifier(4300 + index),
                "dataset_role": base.dataset_role.model_copy(update={"name": role}),
                "schema_definition": schema,
                "partitions": (partition,),
                "temporal_contract": TemporalContractBindingV2(
                    kind=base.temporal_contract.kind, contract=contract
                ),
            }
        )
        decision = validate_identity_dataset(
            manifest, (verified,), fixture_context(4310 + index)
        )
        assert decision.result is ValidationResult.PASS
        datasets[role] = ValidatedRecords(
            records=records, manifest=manifest, decision=decision
        )
    bundle = build_validated_dataset_bundle(
        identifier(4320),
        "1",
        datetime(2026, 9, 4, tzinfo=UTC),
        tuple((dataset.manifest, dataset.decision) for dataset in datasets.values()),
    )
    source = datasets["source_universe_definition"].records[0]
    definition = ResearchUniverseDefinitionV1(
        schema_version="1",
        universe_id=identifier(4010),
        universe_version="1",
        universe_kind="structural",
        target_level=UniverseTargetLevel.LISTING,
        methodology_reference=source.methodology_reference,
        methodology_hash=source.methodology_hash,
        identity_bundle_hash=content_hash(identity.bundle),
        universe_bundle_hash=content_hash(bundle),
        classification_contract_hash=STRICT_CLASSIFICATION_CONTRACT_HASH,
        created_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    universe = UniverseResolutionContext(
        identity_bundle=identity.bundle,
        universe_bundle=bundle,
        assignments=ValidatedRecords(
            records=identity.assignments,
            manifest=identity.assignment_manifest,
            decision=identity.assignment_decision,
        ),
        memberships=datasets["universe_membership"],
        source_definitions=datasets["source_universe_definition"],
        policy=identity.policy,
        retained_evidence={},
    )
    return definition, StructuralResolutionContext(
        universe=universe,
        relationships=ValidatedRecords(
            records=identity.relationships,
            manifest=identity.relationship_manifest,
            decision=identity.relationship_decision,
        ),
        classifications=ValidatedRecords(
            records=identity.classifications,
            manifest=identity.manifests["security_classification"],
            decision=identity.decisions["security_classification"],
        ),
        roles=ValidatedRecords(
            records=identity.roles,
            manifest=identity.manifests["listing_role"],
            decision=identity.decisions["listing_role"],
        ),
        lifecycle=ValidatedRecords(
            records=identity.events,
            manifest=identity.manifests["listing_lifecycle"],
            decision=identity.decisions["listing_lifecycle"],
        ),
        terminations=ValidatedRecords(
            records=identity.terminations,
            manifest=identity.manifests["listing_termination"],
            decision=identity.decisions["listing_termination"],
        ),
        coverage=ValidatedRecords(
            records=identity.coverage,
            manifest=identity.manifests["listing_history_coverage"],
            decision=identity.decisions["listing_history_coverage"],
        ),
    )


def fixture_query(
    data: ValidatedRecords[Any],
    context: UniverseResolutionContext,
    purpose: M1bSelectionPurpose,
    subject: object,
    evaluation: str,
    cutoff: str,
    *,
    structural: bool = False,
) -> NormalizedSelectionQueryV1:
    return NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=purpose,
        information_role=InformationRole.DECISION_INFORMATION,
        resolution_mode=ResolutionMode.AS_KNOWN,
        subject_hash=content_hash(subject),
        source_manifest_hash=data.decision.manifest_hash,
        validation_decision_hash=content_hash(data.decision),
        context_bundle_hashes=tuple(
            sorted(
                (
                    content_hash(context.identity_bundle),
                    content_hash(context.universe_bundle),
                )
            )
        )
        if structural
        else (content_hash(context.universe_bundle),),
        dataset_role_hash=content_hash(data.manifest.dataset_role),
        record_contract_hash=content_hash(data.manifest.temporal_contract.contract),
        schema_hash=data.manifest.schema_definition.schema_hash,
        knowledge_cutoff=datetime.fromisoformat(cutoff),
        evaluation_time=datetime.fromisoformat(evaluation),
        requested_channel=data.manifest.temporal_contract.contract.declared_channels[0],
        policy_id=context.policy.policy_id,
        policy_hash=content_hash(context.policy),
    )


@pytest.mark.parametrize(
    ("evaluation", "cutoff", "expected", "upcoming"),
    (
        ("2020-05-25T00:00:00Z", "2020-05-25T00:00:00Z", "excluded", ("included",)),
        ("2020-06-05T00:00:00Z", "2020-06-05T00:00:00Z", "included", ()),
        ("2020-06-05T00:00:00Z", "2020-06-11T00:00:00Z", "excluded", ("included",)),
        ("2020-06-15T00:00:00Z", "2020-06-15T00:00:00Z", "included", ()),
    ),
)
def test_pinned_synthetic_index_replays_announcement_effect_and_correction(
    evaluation: str, cutoff: str, expected: str, upcoming: tuple[str, ...]
) -> None:
    _, context = universe_fixture_context()
    universe = context.universe
    subject = UniverseDefinitionSubjectV1(
        universe_id=identifier(4000), universe_version="1"
    )
    source = resolve_source_universe_definition(
        subject,
        fixture_query(
            universe.source_definitions,
            universe,
            M1bSelectionPurpose.UNIVERSE_MEMBERSHIP,
            subject,
            evaluation,
            cutoff,
        ),
        universe,
    )
    target = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=identifier(5))
    result = resolve_universe_membership(
        source,
        target,
        fixture_query(
            universe.memberships,
            universe,
            M1bSelectionPurpose.UNIVERSE_MEMBERSHIP,
            membership_subject(source, target),
            evaluation,
            cutoff,
        ),
        universe,
    )
    assert result.status.value == expected
    assert tuple(effect.value for effect in result.known_upcoming_effects) == upcoming
    assert result.definition_hash == content_hash(source.definition)


@pytest.mark.parametrize(
    ("evaluation", "expected"),
    (
        ("2019-01-02T12:00:00Z", "ineligible"),
        ("2019-02-01T00:00:00Z", "eligible"),
        ("2020-03-16T15:00:00Z", "ineligible"),
        ("2020-03-18T00:00:00Z", "eligible"),
    ),
)
def test_structural_eligibility_executes_all_canonical_identity_dependencies(
    evaluation: str, expected: str
) -> None:
    definition, context = universe_fixture_context()
    subject = structural_subject(
        definition, identifier(1), identifier(2), identifier(5), "synthetic-primary-v1"
    )
    query = fixture_query(
        context.universe.memberships,
        context.universe,
        M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        subject,
        evaluation,
        "2026-01-01T00:00:00Z",
        structural=True,
    )
    result = resolve_structural_eligibility(
        definition,
        ListingV1(
            schema_version="1", listing_id=identifier(5), venue=ListingVenue.XNAS
        ),
        identifier(1),
        identifier(2),
        "synthetic-primary-v1",
        query,
        context,
    )
    assert result.classification.value == expected
    assert len(result.identity_assignment_resolution_hashes) == 3
    assert len(result.identity_resolution_hashes) == 2
    assert (
        result.classification_resolution_hash
        and result.primary_listing_resolution_hash
        and result.lifecycle_resolution_hash
    )


def test_later_delisting_does_not_delete_historical_universe_identity() -> None:
    definition, context = universe_fixture_context()
    assert any(
        record.target_id == identifier(5)
        and record.membership_effect.value == "excluded"
        for record in context.universe.memberships.records
    )
    subject = structural_subject(
        definition, identifier(1), identifier(2), identifier(5), "synthetic-primary-v1"
    )
    query = fixture_query(
        context.universe.memberships,
        context.universe,
        M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        subject,
        "2019-02-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        structural=True,
    )
    listing = ListingV1(
        schema_version="1", listing_id=identifier(5), venue=ListingVenue.XNAS
    )
    original = resolve_structural_eligibility(
        definition,
        listing,
        identifier(1),
        identifier(2),
        "synthetic-primary-v1",
        query,
        context,
    )
    resolve_structural_eligibility(
        definition,
        listing,
        identifier(1),
        identifier(2),
        "synthetic-primary-v1",
        query.model_copy(update={"evaluation_time": datetime(2022, 1, 4, tzinfo=UTC)}),
        context,
    )
    assert (
        resolve_structural_eligibility(
            definition,
            listing,
            identifier(1),
            identifier(2),
            "synthetic-primary-v1",
            query,
            context,
        )
        == original
    )
    assert original.classification.value == "eligible"


def test_pinned_membership_records_cannot_be_replaced_by_selected_subset() -> None:
    definition, context = universe_fixture_context()
    universe = context.universe
    target = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=identifier(5))
    query = fixture_query(
        universe.memberships,
        universe,
        M1bSelectionPurpose.UNIVERSE_MEMBERSHIP,
        membership_subject(definition, target),
        "2019-02-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
    )
    subset = tuple(
        record
        for record in universe.memberships.records
        if record.target_id == identifier(5)
    )
    with pytest.raises(DatasetValidationError, match="record_set"):
        resolve_universe_membership(
            definition,
            target,
            query,
            replace(
                universe, memberships=replace(universe.memberships, records=subset)
            ),
        )
