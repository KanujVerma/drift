"""Adversarial tests for causal universe membership and structural admission."""

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast

import pytest
from pydantic import ValidationError
from test_assertions import artifact, exact_boundary, public_availability
from test_dataset_validation_v2 import fixed_manifest
from test_listing_semantics import (
    assignment_dataset,
    bounded_boundary,
    exact_dataset_query,
    history_assignments,
    interval,
    revision,
    role_validation_context,
    uid,
)

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.assertions import (
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
    TemporalBoundaryClaimV1,
)
from drift.domain.common import FrozenModel
from drift.domain.dataset_validation import DatasetValidationError, ValidationResult
from drift.domain.manifests import AssertionEffectiveShape, TemporalContractBindingV2
from drift.domain.revisions import RevisionKind
from drift.domain.securities import (
    IdentityAssignmentEffect,
    IdentityAssignmentVersionV1,
    IdentityKind,
    IdentityReferenceV1,
    identity_reference,
)
from drift.domain.temporal import AvailabilityPolicyV1
from drift.domain.universes import (
    MembershipEffect,
    MembershipStatus,
    ResearchUniverseDefinitionV1,
    SourceUniverseDefinitionResolutionV1,
    SourceUniverseDefinitionVersionV1,
    SourceUniverseKind,
    StructuralEligibilityResultV1,
    UniverseDefinitionSubjectV1,
    UniverseMembershipResolutionV1,
    UniverseMembershipVersionV1,
    UniverseTargetLevel,
)
from drift.markets.universes import (
    StructuralResolutionContext,
    UniverseResolutionContext,
    ValidatedRecords,
    membership_subject,
    resolve_source_universe_definition,
    resolve_universe_membership,
)
from drift.markets.validation import (
    SOURCE_UNIVERSE_DEFINITION_SCHEMA_V1,
    UNIVERSE_MEMBERSHIP_SCHEMA_V1,
    validate_identity_dataset,
)
from drift.serialization.canonical import canonical_json, content_hash


def research_definition() -> ResearchUniverseDefinitionV1:
    """One immutable synthetic listing policy with explicit input bindings."""
    reference = artifact()
    return ResearchUniverseDefinitionV1(
        schema_version="1",
        universe_id=uid(2400),
        universe_version="1",
        universe_kind="structural",
        target_level=UniverseTargetLevel.LISTING,
        methodology_reference=reference,
        methodology_hash=reference.content_hash,
        identity_bundle_hash="a" * 64,
        universe_bundle_hash="b" * 64,
        classification_contract_hash="c" * 64,
        created_at=datetime(2026, 9, 4, tzinfo=UTC),
    )


def source_definition() -> SourceUniverseDefinitionVersionV1:
    """One sourced synthetic index definition, not a timeless policy."""
    definition = research_definition()
    return SourceUniverseDefinitionVersionV1(
        schema_version="1",
        revision=revision(2410),
        universe_id=definition.universe_id,
        universe_version="1",
        universe_kind=SourceUniverseKind.INDEX,
        target_level=UniverseTargetLevel.LISTING,
        methodology_reference=definition.methodology_reference,
        methodology_hash=definition.methodology_hash,
        identity_bundle_hash=definition.identity_bundle_hash,
        effective_interval=interval("2019-01-01T00:00:00Z"),
    )


def test_definition_roundtrip_preserves_exact_policy_identity() -> None:
    for definition in (research_definition(), source_definition()):
        restored = type(definition).model_validate_json(definition.model_dump_json())
        assert restored == definition
        assert content_hash(restored) == content_hash(definition)
        with pytest.raises(ValidationError):
            definition.universe_version = "2"


@pytest.mark.parametrize("level", ("issuer", "mixed", "security"))
def test_initial_structural_definition_requires_listing_target(level: str) -> None:
    values = research_definition().model_dump(mode="python")
    values["target_level"] = level
    with pytest.raises(ValidationError):
        ResearchUniverseDefinitionV1.model_validate(values)


def test_source_definition_can_explicitly_target_security() -> None:
    assert (
        source_definition()
        .model_copy(
            update={
                "target_level": UniverseTargetLevel.SECURITY,
            }
        )
        .target_level
        is UniverseTargetLevel.SECURITY
    )


@pytest.mark.parametrize("source", (False, True))
def test_definition_rejects_wrong_methodology_hash_and_unsafe_reference(
    source: bool,
) -> None:
    definition = source_definition() if source else research_definition()
    with pytest.raises(ValidationError, match="methodology"):
        definition.model_copy(update={"methodology_hash": "d" * 64})
    unsafe = definition.methodology_reference.model_copy(
        update={
            "location": "https://example.test/methodology?token=secret",
        }
    )
    with pytest.raises(ValidationError):
        definition.model_copy(update={"methodology_reference": unsafe})


@pytest.mark.parametrize("field", ("price", "volume", "market_cap", "rank"))
def test_definition_cannot_embed_strategy_screen(field: str) -> None:
    values = research_definition().model_dump(mode="python")
    values[field] = 1
    with pytest.raises(ValidationError):
        ResearchUniverseDefinitionV1.model_validate(values)


def seal[T: SourceUniverseDefinitionVersionV1 | UniverseMembershipVersionV1](
    record: T,
) -> T:
    return cast(
        T,
        record.model_copy(
            update={
                "revision": record.revision.model_copy(
                    update={
                        "payload_hash": content_hash(assertion_version_payload(record)),
                    }
                )
            }
        ),
    )


def membership(
    suffix: int,
    effect: MembershipEffect,
    effective: str,
    *,
    available: str = "2019-01-01T00:00:00Z",
    target: int = 1,
    boundary: TemporalBoundaryClaimV1 | None = None,
) -> UniverseMembershipVersionV1:
    return seal(
        UniverseMembershipVersionV1(
            schema_version="1",
            revision=revision(suffix).model_copy(
                update={
                    "availability": (public_availability(available),),
                }
            ),
            universe_id=uid(2400),
            universe_version="1",
            target_level=UniverseTargetLevel.LISTING,
            target_id=uid(target),
            membership_effect=effect,
            effective_time=exact_boundary(effective) if boundary is None else boundary,
            source_event_id=f"synthetic-membership-{suffix}",
        )
    )


def universe_dataset[T: FrozenModel](
    role: str, records: tuple[T, ...]
) -> ValidatedRecords[T]:
    data = canonical_json({"schema_version": "1", "records": records})
    digest = sha256(data).hexdigest()
    schema = (
        SOURCE_UNIVERSE_DEFINITION_SCHEMA_V1
        if role == "source_universe_definition"
        else UNIVERSE_MEMBERSHIP_SCHEMA_V1
    )
    effective_field = (
        "effective_interval"
        if role == "source_universe_definition"
        else "effective_time"
    )
    base = fixed_manifest(role)
    fields = tuple(
        sorted(
            field.field_id
            for field in schema.fields
            if field.field_id not in {"schema_version", effective_field}
            and not field.field_id.startswith("revision.")
        )
    )
    contract = base.temporal_contract.contract.model_copy(
        update={
            "effective_time_field_id": effective_field,
            "effective_shape": (
                AssertionEffectiveShape.INTERVAL
                if role == "source_universe_definition"
                else AssertionEffectiveShape.BOUNDARY
            ),
            "semantic_state_field_ids": fields,
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
            "byte_size": len(data),
            "row_count": len(records),
            "schema_hash": schema.schema_hash,
        }
    )
    manifest = base.model_copy(
        update={
            "schema_definition": schema,
            "partitions": (partition,),
            "temporal_contract": TemporalContractBindingV2(
                kind=base.temporal_contract.kind, contract=contract
            ),
        }
    )
    decision = validate_identity_dataset(
        manifest,
        (
            VerifiedArtifactBytes(
                data=data,
                byte_size=len(data),
                content_hash=digest,
            ),
        ),
        role_validation_context(2420),
    )
    return ValidatedRecords(records=records, manifest=manifest, decision=decision)


def membership_context(
    records: tuple[UniverseMembershipVersionV1, ...],
    *,
    definitions: tuple[SourceUniverseDefinitionVersionV1, ...] | None = None,
    assignments: tuple[IdentityAssignmentVersionV1, ...] | None = None,
) -> tuple[ResearchUniverseDefinitionV1, UniverseResolutionContext]:
    assignments = history_assignments() if assignments is None else assignments
    assignment_manifest, assignment_decision = assignment_dataset(assignments)
    identity_bundle = build_validated_dataset_bundle(
        uid(2430),
        "1",
        datetime(2026, 9, 4, tzinfo=UTC),
        ((assignment_manifest, assignment_decision),),
    )
    memberships = universe_dataset("universe_membership", records)
    source_records = (
        (
            seal(
                source_definition().model_copy(
                    update={
                        "identity_bundle_hash": content_hash(identity_bundle),
                    }
                )
            ),
        )
        if definitions is None
        else definitions
    )
    sources = universe_dataset("source_universe_definition", source_records)
    assert memberships.decision.result is ValidationResult.PASS
    assert sources.decision.result is ValidationResult.PASS
    bundle = build_validated_dataset_bundle(
        uid(2431),
        "1",
        datetime(2026, 9, 4, tzinfo=UTC),
        (
            (memberships.manifest, memberships.decision),
            (sources.manifest, sources.decision),
        ),
    )
    definition = research_definition().model_copy(
        update={
            "identity_bundle_hash": content_hash(identity_bundle),
            "universe_bundle_hash": content_hash(bundle),
        }
    )
    return definition, UniverseResolutionContext(
        identity_bundle=identity_bundle,
        universe_bundle=bundle,
        assignments=ValidatedRecords(
            records=assignments,
            manifest=assignment_manifest,
            decision=assignment_decision,
        ),
        memberships=memberships,
        source_definitions=sources,
        policy=AvailabilityPolicyV1(policy_id="strict"),
        retained_evidence={},
    )


def member_query(
    definition: ResearchUniverseDefinitionV1 | SourceUniverseDefinitionResolutionV1,
    context: UniverseResolutionContext,
    *,
    evaluation: str = "2020-05-25T00:00:00Z",
    cutoff: str = "2020-05-25T00:00:00Z",
) -> NormalizedSelectionQueryV1:
    return exact_dataset_query(
        context.memberships.manifest,
        context.memberships.decision,
        context.universe_bundle,
        purpose=M1bSelectionPurpose.UNIVERSE_MEMBERSHIP,
        subject=membership_subject(
            definition,
            IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
        ),
        evaluation_time=evaluation,
        knowledge_cutoff=cutoff,
        resolution_mode=ResolutionMode.AS_KNOWN,
    )


def resolve_members(
    records: tuple[UniverseMembershipVersionV1, ...],
    *,
    evaluation: str = "2020-05-25T00:00:00Z",
    cutoff: str = "2020-05-25T00:00:00Z",
) -> UniverseMembershipResolutionV1:
    definition, context = membership_context(records)
    return resolve_universe_membership(
        definition,
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
        member_query(definition, context, evaluation=evaluation, cutoff=cutoff),
        context,
    )


@pytest.mark.parametrize(
    ("evaluation", "expected", "upcoming"),
    (
        (
            "2020-05-25T00:00:00Z",
            MembershipStatus.EXCLUDED,
            (MembershipEffect.INCLUDED,),
        ),
        ("2020-06-01T00:00:00Z", MembershipStatus.INCLUDED, ()),
        ("2020-07-01T00:00:00Z", MembershipStatus.EXCLUDED, ()),
    ),
)
def test_membership_announcement_is_not_effective_membership(
    evaluation: str, expected: MembershipStatus, upcoming: tuple[MembershipEffect, ...]
) -> None:
    records = (
        membership(2440, MembershipEffect.EXCLUDED, "2019-01-02T00:00:00Z"),
        membership(
            2450,
            MembershipEffect.INCLUDED,
            "2020-06-01T00:00:00Z",
            available="2020-05-20T00:00:00Z",
        ),
        membership(
            2460,
            MembershipEffect.EXCLUDED,
            "2020-07-01T00:00:00Z",
            available="2020-06-20T00:00:00Z",
        ),
    )
    result = resolve_members(records, evaluation=evaluation, cutoff=evaluation)
    assert result.status is expected
    assert result.known_upcoming_effects == upcoming


def test_upcoming_addition_without_prior_fact_does_not_prove_exclusion() -> None:
    result = resolve_members(
        (
            membership(
                2470,
                MembershipEffect.INCLUDED,
                "2020-06-01T00:00:00Z",
                available="2020-05-20T00:00:00Z",
            ),
        )
    )
    assert result.status is MembershipStatus.INDETERMINATE
    assert result.known_upcoming_effects == (MembershipEffect.INCLUDED,)


def test_current_snapshot_cannot_backfill_historical_membership() -> None:
    result = resolve_members(
        (
            membership(
                2480,
                MembershipEffect.INCLUDED,
                "2026-01-01T00:00:00Z",
                available="2026-01-01T00:00:00Z",
            ),
        )
    )
    assert result.status is MembershipStatus.INDETERMINATE
    assert result.known_upcoming_effects == ()
    assert result.evidence.selected_record_hashes == ()


@pytest.mark.parametrize("tie", (False, True))
def test_opposing_latest_events_without_definite_order_are_indeterminate(
    tie: bool,
) -> None:
    boundary = (
        exact_boundary("2020-05-01T00:00:00Z")
        if tie
        else bounded_boundary("2020-04-01T00:00:00Z", "2020-05-20T00:00:00Z")
    )
    result = resolve_members(
        (
            membership(2490, MembershipEffect.INCLUDED, "2020-05-01T00:00:00Z"),
            membership(
                2500,
                MembershipEffect.EXCLUDED,
                "2020-05-01T00:00:00Z",
                boundary=boundary,
            ),
        )
    )
    assert result.status is MembershipStatus.INDETERMINATE


def test_membership_selection_checks_full_dataset_before_target_filtering() -> None:
    records = (
        membership(2510, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z"),
        membership(2520, MembershipEffect.EXCLUDED, "2020-01-01T00:00:00Z", target=2),
    )
    definition, context = membership_context(records)
    reduced = replace(
        context, memberships=replace(context.memberships, records=records[:1])
    )
    with pytest.raises(DatasetValidationError, match="record_set"):
        resolve_universe_membership(
            definition,
            IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
            member_query(definition, context),
            reduced,
        )


@pytest.mark.parametrize(
    "changed", ("target_id", "universe_version", "source_event_id")
)
def test_membership_correction_cannot_change_its_logical_event_owner(
    changed: str,
) -> None:
    original = membership(2530, MembershipEffect.INCLUDED, "2020-06-01T00:00:00Z")
    correction = seal(
        original.model_copy(
            update={
                changed: uid(2) if changed == "target_id" else "changed",
                "revision": original.revision.model_copy(
                    update={
                        "record_version_id": uid(2540),
                        "revision_kind": RevisionKind.CORRECTION,
                        "supersedes_record_version_id": (
                            original.revision.record_version_id
                        ),
                        "source_sequence": 1,
                    }
                ),
            }
        )
    )
    dataset = universe_dataset("universe_membership", (original, correction))
    assert dataset.decision.result is ValidationResult.FAIL


def test_source_definition_must_itself_be_causally_selected() -> None:
    definition, context = membership_context(
        (membership(2550, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z"),)
    )
    subject = UniverseDefinitionSubjectV1(universe_id=uid(2400), universe_version="1")
    source_query = exact_dataset_query(
        context.source_definitions.manifest,
        context.source_definitions.decision,
        context.universe_bundle,
        purpose=M1bSelectionPurpose.UNIVERSE_MEMBERSHIP,
        subject=subject,
        evaluation_time="2020-05-25T00:00:00Z",
        knowledge_cutoff="2010-01-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )
    selected = resolve_source_universe_definition(subject, source_query, context)
    assert selected.definition is None
    result = resolve_universe_membership(
        selected,
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
        member_query(selected, context, cutoff="2010-01-01T00:00:00Z"),
        context,
    )
    assert result.status is MembershipStatus.INDETERMINATE


@pytest.mark.parametrize("withdraw", (False, True))
def test_membership_correction_and_withdrawal_replay_by_cutoff(withdraw: bool) -> None:
    previous = membership(2560, MembershipEffect.EXCLUDED, "2019-01-02T00:00:00Z")
    original = membership(2570, MembershipEffect.INCLUDED, "2020-05-01T00:00:00Z")
    correction = seal(
        original.model_copy(
            update={
                "effective_time": exact_boundary("2020-07-01T00:00:00Z"),
                "revision": original.revision.model_copy(
                    update={
                        "record_version_id": uid(2580),
                        "revision_kind": RevisionKind.WITHDRAWAL
                        if withdraw
                        else RevisionKind.CORRECTION,
                        "supersedes_record_version_id": (
                            original.revision.record_version_id
                        ),
                        "source_sequence": 1,
                        "availability": (public_availability("2020-06-01T00:00:00Z"),),
                    }
                ),
            }
        )
    )
    before = resolve_members((previous, original, correction))
    after = resolve_members(
        (previous, original, correction), cutoff="2020-06-02T00:00:00Z"
    )
    assert before.status is MembershipStatus.INCLUDED
    assert after.status is MembershipStatus.EXCLUDED
    assert after.known_upcoming_effects == (
        () if withdraw else (MembershipEffect.INCLUDED,)
    )
    assert content_hash(original) in before.evidence.selected_record_hashes
    assert content_hash(original) not in after.evidence.selected_record_hashes
    assert (
        content_hash(correction) not in after.evidence.selected_record_hashes
        if withdraw
        else True
    )
    old_definition, old_context = membership_context((previous, original))
    old_query = member_query(old_definition, old_context, cutoff="2020-06-02T00:00:00Z")
    target = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1))
    old_result = resolve_universe_membership(
        old_definition, target, old_query, old_context
    )
    assert old_result.status is MembershipStatus.INCLUDED
    assert old_result.universe_bundle_hash != after.universe_bundle_hash
    assert (
        resolve_universe_membership(old_definition, target, old_query, old_context)
        == old_result
    )


def test_withdrawal_without_another_event_is_not_a_business_exclusion() -> None:
    original = membership(2590, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z")
    withdrawal = seal(
        original.model_copy(
            update={
                "revision": original.revision.model_copy(
                    update={
                        "record_version_id": uid(2600),
                        "revision_kind": RevisionKind.WITHDRAWAL,
                        "supersedes_record_version_id": (
                            original.revision.record_version_id
                        ),
                        "source_sequence": 1,
                    }
                )
            }
        )
    )
    assert (
        resolve_members((original, withdrawal)).status is MembershipStatus.INDETERMINATE
    )


def test_revision_sequence_does_not_order_independent_membership_events() -> None:
    original = membership(2610, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z")
    correction = seal(
        original.model_copy(
            update={
                "revision": original.revision.model_copy(
                    update={
                        "record_version_id": uid(2620),
                        "revision_kind": RevisionKind.CORRECTION,
                        "supersedes_record_version_id": (
                            original.revision.record_version_id
                        ),
                        "source_sequence": 1,
                    }
                )
            }
        )
    )
    excluded = membership(2630, MembershipEffect.EXCLUDED, "2020-01-01T00:00:00Z")
    assert (
        resolve_members((original, correction, excluded)).status
        is MembershipStatus.EXCLUDED
    )


def test_raw_source_definition_cannot_authorize_membership() -> None:
    with pytest.raises(DatasetValidationError, match="resolution_required"):
        membership_subject(
            cast(Any, source_definition()),
            IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1)),
        )


def structural_inputs(
    *,
    classification_kind: str = "supported",
    coverage_kind: str = "complete",
    included: bool = True,
    instrument_kind: str = "common_share",
    domestic_status: str = "domestic",
) -> tuple[ResearchUniverseDefinitionV1, StructuralResolutionContext]:
    from test_listing_semantics import (
        assignment_for_dependency,
        classification_record,
        coverage_record,
        issuer_security_relationship,
        relationship_dataset,
        relationship_record,
        role_dataset,
        role_record,
        standard_lifecycle_events,
    )

    from drift.domain.securities import (
        DomesticStatus,
        InstrumentForm,
        IssuerForm,
        ListingHistoryCoverageStatus,
    )
    from drift.markets.universes import (
        STRICT_CLASSIFICATION_CONTRACT_HASH,
        StructuralResolutionContext,
    )

    base_definition, universe = membership_context(
        (
            membership(
                2640,
                MembershipEffect.INCLUDED if included else MembershipEffect.EXCLUDED,
                "2019-01-02T00:00:00Z",
            ),
        )
    )
    assignments = tuple(
        assignment_for_dependency(
            IdentityReferenceV1(kind=kind, internal_id=uid(number)), 2650 + index
        )
        for index, (kind, number) in enumerate(
            (
                (IdentityKind.ISSUER, 20),
                (IdentityKind.SECURITY, 21),
                (IdentityKind.LISTING, 1),
            )
        )
    )
    assignment_manifest, assignment_decision = assignment_dataset(assignments)
    relationships = (
        issuer_security_relationship(2660),
        relationship_record(21, 1, 2670),
    )
    relationship_manifest, relationship_decision = relationship_dataset(relationships)
    classified = classification_record(2680)
    if classification_kind != "supported":
        classified = classified.model_copy(
            update={"issuer_form": IssuerForm(classification_kind)}
        )
        classified = classified.model_copy(
            update={
                "revision": classified.revision.model_copy(
                    update={
                        "payload_hash": content_hash(
                            assertion_version_payload(classified)
                        ),
                    }
                )
            }
        )
    classified = classified.model_copy(
        update={
            "instrument_form": InstrumentForm(instrument_kind),
            "domestic_status": DomesticStatus(domestic_status),
        }
    )
    classified = classified.model_copy(
        update={
            "revision": classified.revision.model_copy(
                update={
                    "payload_hash": content_hash(assertion_version_payload(classified)),
                }
            )
        }
    )
    record_sets: dict[str, tuple[Any, ...]] = {
        "security_classification": (classified,),
        "listing_role": (role_record(2690, 1),),
        "listing_lifecycle": standard_lifecycle_events(),
        "listing_termination": (),
        "listing_history_coverage": (
            ()
            if coverage_kind == "missing"
            else (
                coverage_record(
                    2700,
                    ListingHistoryCoverageStatus(coverage_kind),
                    "2026-12-31T00:00:00Z",
                ),
            )
        ),
    }
    datasets: dict[str, ValidatedRecords[Any]] = {}
    for role, records in record_sets.items():
        manifest, data = role_dataset(role, records)
        decision = validate_identity_dataset(
            manifest, (data,), role_validation_context(2710)
        )
        assert decision.result is ValidationResult.PASS
        datasets[role] = ValidatedRecords(
            records=records, manifest=manifest, decision=decision
        )
    bundle = build_validated_dataset_bundle(
        uid(2720),
        "2",
        datetime(2026, 9, 4, tzinfo=UTC),
        (
            (assignment_manifest, assignment_decision),
            (relationship_manifest, relationship_decision),
            *((value.manifest, value.decision) for value in datasets.values()),
        ),
    )
    universe = replace(
        universe,
        identity_bundle=bundle,
        assignments=ValidatedRecords(
            records=assignments,
            manifest=assignment_manifest,
            decision=assignment_decision,
        ),
    )
    definition = base_definition.model_copy(
        update={
            "identity_bundle_hash": content_hash(bundle),
            "classification_contract_hash": STRICT_CLASSIFICATION_CONTRACT_HASH,
        }
    )
    return definition, StructuralResolutionContext(
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


def structural_query(
    definition: ResearchUniverseDefinitionV1,
    context: StructuralResolutionContext,
    *,
    evaluation: str = "2020-05-25T00:00:00Z",
    cutoff: str = "2026-01-01T00:00:00Z",
) -> NormalizedSelectionQueryV1:
    from drift.markets.universes import structural_subject

    subject = structural_subject(
        definition, uid(20), uid(21), uid(1), "synthetic-primary-v1"
    )
    return exact_dataset_query(
        context.universe.memberships.manifest,
        context.universe.memberships.decision,
        context.universe.universe_bundle,
        purpose=M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        subject=subject,
        evaluation_time=evaluation,
        knowledge_cutoff=cutoff,
        resolution_mode=ResolutionMode.AS_KNOWN,
    ).model_copy(
        update={
            "context_bundle_hashes": tuple(
                sorted(
                    (
                        content_hash(context.universe.identity_bundle),
                        content_hash(context.universe.universe_bundle),
                    )
                )
            )
        }
    )


def invoke_structural(
    definition: ResearchUniverseDefinitionV1,
    context: StructuralResolutionContext,
    *,
    query: NormalizedSelectionQueryV1 | None = None,
) -> StructuralEligibilityResultV1:
    from drift.domain.securities import ListingV1, ListingVenue
    from drift.markets.universes import resolve_structural_eligibility

    return resolve_structural_eligibility(
        definition,
        ListingV1(schema_version="1", listing_id=uid(1), venue=ListingVenue.XNAS),
        uid(20),
        uid(21),
        "synthetic-primary-v1",
        structural_query(definition, context) if query is None else query,
        context,
    )


@pytest.mark.parametrize(
    ("classification_kind", "expected"),
    (
        ("supported", "eligible"),
        ("fund", "ineligible"),
        ("reit", "ineligible"),
        ("acquisition_company", "ineligible"),
        ("unknown", "indeterminate"),
    ),
)
def test_structural_admission_uses_replayed_classification(
    classification_kind: str, expected: str
) -> None:
    definition, context = structural_inputs(classification_kind=classification_kind)
    result = invoke_structural(definition, context)
    assert result.classification.value == expected
    assert result.membership_resolution_hash
    assert result.selection_proof_hashes


@pytest.mark.parametrize("coverage_kind", ("partial", "unknown", "missing"))
def test_known_membership_does_not_authorize_unknown_activity(
    coverage_kind: str,
) -> None:
    definition, context = structural_inputs(coverage_kind=coverage_kind)
    assert (
        invoke_structural(definition, context).classification.value == "indeterminate"
    )


def test_structural_explicit_membership_exclusion_remains_ineligible() -> None:
    definition, context = structural_inputs(included=False)
    assert invoke_structural(definition, context).classification.value == "ineligible"


@pytest.mark.parametrize(
    "field",
    ("source_manifest_hash", "validation_decision_hash", "policy_hash", "subject_hash"),
)
def test_structural_query_cannot_substitute_provenance(field: str) -> None:
    definition, context = structural_inputs()
    query = structural_query(definition, context).model_copy(update={field: "e" * 64})
    with pytest.raises(DatasetValidationError):
        invoke_structural(definition, context, query=query)


def test_structural_resolver_cannot_accept_a_caller_status_in_place_of_records() -> (
    None
):
    definition, context = structural_inputs()
    forged = replace(
        context, classifications=replace(context.classifications, records=())
    )
    with pytest.raises(DatasetValidationError):
        invoke_structural(definition, forged)


@pytest.mark.parametrize(
    "instrument", ("preferred", "receipt", "unit", "warrant", "right", "other")
)
def test_structural_excludes_each_unsupported_instrument(instrument: str) -> None:
    definition, context = structural_inputs(instrument_kind=instrument)
    assert invoke_structural(definition, context).classification.value == "ineligible"


@pytest.mark.parametrize(
    ("domestic", "expected"),
    (("foreign", "ineligible"), ("indeterminate", "indeterminate")),
)
def test_structural_requires_explicit_domestic_classification(
    domestic: str, expected: str
) -> None:
    definition, context = structural_inputs(domestic_status=domestic)
    assert invoke_structural(definition, context).classification.value == expected


def test_unknown_competing_membership_event_cannot_be_ignored() -> None:
    from drift.domain.assertions import BoundaryShape
    from drift.domain.temporal import SourcePrecision

    unknown = TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.UNKNOWN,
        lower_bound=None,
        upper_bound=None,
        source_precision=SourcePrecision.UNKNOWN,
        source_time_label=None,
        source_timezone=None,
        evidence_reference=None,
    )
    result = resolve_members(
        (
            membership(2800, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z"),
            membership(
                2810,
                MembershipEffect.EXCLUDED,
                "2020-01-01T00:00:00Z",
                boundary=unknown,
            ),
        )
    )
    assert result.status is MembershipStatus.INDETERMINATE


def test_unavailable_future_membership_record_cannot_change_current_facts() -> None:
    included = membership(2820, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z")
    future = membership(
        2830,
        MembershipEffect.EXCLUDED,
        "2020-01-01T00:00:00Z",
        available="2027-01-01T00:00:00Z",
    )
    result = resolve_members((included, future))
    assert result.status is MembershipStatus.INCLUDED
    assert result.evidence.selected_record_hashes == (content_hash(included),)


@pytest.mark.parametrize("wrong", ("target", "records", "definition"))
def test_membership_target_kind_cannot_be_substituted(wrong: str) -> None:
    record = membership(2840, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z")
    if wrong == "records":
        record = seal(
            record.model_copy(update={"target_level": UniverseTargetLevel.SECURITY})
        )
    definition, context = membership_context((record,))
    target = IdentityReferenceV1(
        kind=IdentityKind.SECURITY if wrong == "target" else IdentityKind.LISTING,
        internal_id=uid(1),
    )
    query = member_query(definition, context)
    if wrong == "definition":
        definition = definition.model_copy(
            update={
                "methodology_hash": "d" * 64,
                "methodology_reference": definition.methodology_reference.model_copy(
                    update={"content_hash": "d" * 64}
                ),
            }
        )
    with pytest.raises(DatasetValidationError):
        resolve_universe_membership(definition, target, query, context)


def test_source_definition_result_must_replay_not_just_hash_consistently() -> None:
    from drift.domain.securities import RecordResolutionClassification

    _, context = membership_context(
        (membership(2850, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z"),)
    )
    subject = UniverseDefinitionSubjectV1(universe_id=uid(2400), universe_version="1")
    query = exact_dataset_query(
        context.source_definitions.manifest,
        context.source_definitions.decision,
        context.universe_bundle,
        purpose=M1bSelectionPurpose.UNIVERSE_MEMBERSHIP,
        subject=subject,
        evaluation_time="2020-05-25T00:00:00Z",
        knowledge_cutoff="2010-01-01T00:00:00Z",
        resolution_mode=ResolutionMode.AS_KNOWN,
    )
    original = resolve_source_universe_definition(subject, query, context)
    assert original.definition is None
    record = context.source_definitions.records[0]
    forged_values = original.model_dump(mode="python", exclude={"outcome_binding_hash"})
    forged_values.update(
        {
            "definition": record,
            "classification": RecordResolutionClassification.RESOLVED,
            "evidence": original.evidence.model_copy(
                update={"selected_record_hashes": (content_hash(record),)}
            ),
        }
    )
    forged = SourceUniverseDefinitionResolutionV1.model_validate(
        {
            **forged_values,
            "outcome_binding_hash": content_hash(forged_values),
        }
    )
    target = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1))
    with pytest.raises(
        DatasetValidationError, match="source_definition_replay_mismatch"
    ):
        resolve_universe_membership(
            forged,
            target,
            member_query(forged, context, cutoff="2010-01-01T00:00:00Z"),
            context,
        )


def test_structural_current_interpretation_cannot_enter_decision_information() -> None:
    from drift.domain.assertions import InformationRole

    definition, context = structural_inputs()
    query = structural_query(definition, context).model_copy(
        update={
            "resolution_mode": ResolutionMode.CURRENT_INTERPRETATION,
            "information_role": InformationRole.EX_POST_OUTCOME,
        }
    )
    with pytest.raises(DatasetValidationError, match="decision_mode"):
        invoke_structural(definition, context, query=query)


@pytest.mark.parametrize(
    "association", ("ended", "unassigned", "withdrawn", "future", "only_unassigned")
)
def test_membership_retains_identity_without_inferring_current_association(
    association: str,
) -> None:
    target = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=uid(1))
    original = next(
        record
        for record in history_assignments()
        if identity_reference(record.identity) == target
    )
    records: tuple[IdentityAssignmentVersionV1, ...] = (original,)
    if association in {"unassigned", "withdrawn"}:
        corrected = original.model_copy(
            update={
                "assignment_effect": IdentityAssignmentEffect.UNASSIGNED,
                "revision": original.revision.model_copy(
                    update={
                        "record_version_id": uid(2860),
                        "source_sequence": 1,
                        "revision_kind": RevisionKind.WITHDRAWAL
                        if association == "withdrawn"
                        else RevisionKind.CORRECTION,
                        "supersedes_record_version_id": (
                            original.revision.record_version_id
                        ),
                    }
                ),
            }
        )
        corrected = corrected.model_copy(
            update={
                "revision": corrected.revision.model_copy(
                    update={
                        "payload_hash": content_hash(
                            assertion_version_payload(corrected)
                        )
                    }
                )
            }
        )
        records += (corrected,)
    elif association == "future":
        original = original.model_copy(
            update={
                "revision": original.revision.model_copy(
                    update={
                        "availability": (public_availability("2027-01-01T00:00:00Z"),)
                    }
                )
            }
        )
        original = original.model_copy(
            update={
                "revision": original.revision.model_copy(
                    update={
                        "payload_hash": content_hash(
                            assertion_version_payload(original)
                        )
                    }
                )
            }
        )
        records = (original,)
    elif association == "only_unassigned":
        original = original.model_copy(
            update={"assignment_effect": IdentityAssignmentEffect.UNASSIGNED}
        )
        original = original.model_copy(
            update={
                "revision": original.revision.model_copy(
                    update={
                        "payload_hash": content_hash(
                            assertion_version_payload(original)
                        )
                    }
                )
            }
        )
        records = (original,)
    definition, context = membership_context(
        (membership(2870, MembershipEffect.EXCLUDED, "2022-01-01T00:00:00Z"),),
        assignments=records,
    )
    result = resolve_universe_membership(
        definition,
        target,
        member_query(
            definition,
            context,
            evaluation="2022-01-02T00:00:00Z",
            cutoff="2026-01-01T00:00:00Z",
        ),
        context,
    )
    assert result.status is (
        MembershipStatus.EXCLUDED
        if association in {"ended", "unassigned"}
        else MembershipStatus.INDETERMINATE
    )


@pytest.mark.parametrize("role", ("source_universe_definition", "universe_membership"))
def test_universe_role_version_requires_an_explicit_supported_contract(
    role: str,
) -> None:
    records = (
        (seal(source_definition()),)
        if role == "source_universe_definition"
        else (membership(2880, MembershipEffect.INCLUDED, "2019-01-02T00:00:00Z"),)
    )
    dataset = universe_dataset(role, records)
    expected_schema_hash = (
        "c8922549fcd2fea10c3c07840f10dd4ca4b906cdaf010f8f67881c134c3ba4bd"
        if role == "source_universe_definition"
        else "452f10f651911627f578495233eb205b46691bd2534abc1947266ae31853287a"
    )
    assert dataset.manifest.schema_definition.schema_hash == expected_schema_hash
    with pytest.raises(ValidationError):
        dataset.manifest.dataset_role.model_copy(update={"version": "2"})
