"""Unit tests for proof-bearing M1d replay provenance binding (issues 31, 34).

The adversarial finding these tests pin is that a bundle could assert a
qualified snapshot hash while its views were materialized through a genuine
replay over a completely unrelated resolution context. Replay-boundness was
proven; provenance was not. Every test below either proves the binding holds
or proves it fails closed.
"""

from datetime import date
from typing import Any, Literal, get_args, get_origin

import pytest
from economic_test_support import validated_case
from observation_test_support import (
    NormalizationHarness,
    ObservationHarness,
    uid,
)
from pydantic import ValidationError
from pydantic_core import PydanticUndefined
from replay_provenance_test_support import qualified_snapshot, snapshot_over
from test_assertions import exact_boundary
from test_evaluator_admission_gatekeeper import make_test_fixture, rebind_admission
from test_evaluator_bundles import (
    normalization_realized_clock,
    normalization_scheduled_clock,
)
from test_universes import invoke_structural, structural_inputs

from drift.domain import replay_provenance
from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_lanes import (
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.replay_provenance import (
    BUNDLE_PROVENANCE_PROOF_VERSION,
    BundleProvenanceProofV1,
    QualifiedReplayContextV1,
    ReplayContextIdentityV1,
    SnapshotBindingEntryV1,
    _build_bundle_provenance_proof,
    bundle_component_hashes,
    bundle_provenance_proof_hash,
    context_supplied_artifact_hashes,
    qualified_replay_context_hash,
    replay_context_identity_hash,
    snapshot_binding_witness_hash,
    verify_snapshot_binding,
)
from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
from drift.domain.source_snapshots import RealSourceSnapshotV1
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_input_bundle,
    derive_replay_context_identity,
    mint_bundle_provenance_proof,
    qualify_replay_context,
    validate_exploratory_admission,
    validate_promotion_admission,
    verify_evaluation_input_bundle,
)
from drift.markets.economic_outcomes import resolve_economic_facts
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)
from drift.markets.observation_validation import M1dResolutionContext
from drift.serialization.canonical import content_hash

H = {c: c * 64 for c in "0123456789abcdef"}


# --- context and snapshot fixtures ---


def _decision_harness() -> NormalizationHarness:
    return NormalizationHarness(outer_kind="decision")


def _decision_case() -> tuple[NormalizationHarness, Any, Any]:
    harness = _decision_harness()
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    result = harness.normalize(query)
    return harness, query, result.reference


def _unrelated_context() -> M1dResolutionContext:
    """A genuine but entirely different M1d resolution context.

    This is the adversary's context: real, replayable, and unrelated to the
    snapshot whose identity the bundle asserts.
    """
    harness = ObservationHarness(assessment_ready=True, close="123.456")
    context: M1dResolutionContext = harness.context
    return context


# --- bundle fixtures ---


def _interval() -> TemporalIntervalClaimV1:
    return TemporalIntervalClaimV1(schema_version="1", start=exact_boundary(), end=None)


def _promotion_bundle(
    harness: NormalizationHarness,
    query: Any,
    reference: Any,
    snapshot: RealSourceSnapshotV1,
) -> EvaluationInputBundleV1:
    # The clock comes from the same corpus the views replay over, because a
    # bundle member outside its own session clock now fails closed.
    return build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_realized_clock(harness),
        context=harness.context,
        decision_requests=((reference, query),),
        source_snapshot_hash=snapshot.snapshot_hash,
    )


def _fully_populated_bundle() -> EvaluationInputBundleV1:
    """A bundle carrying at least one member of all six authority-bearing classes."""
    decision_harness = _decision_harness()
    decision_query = decision_harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    decision_view = materialize_observation_decision(
        decision_harness.normalize(decision_query).reference,
        decision_query,
        decision_harness.context,
    )

    accounting_harness = NormalizationHarness()
    accounting_query = accounting_harness.normalization_query("source_basis")
    accounting_view = materialize_observation_outcome(
        accounting_harness.normalize(accounting_query).reference,
        accounting_query,
        accounting_harness.context,
    )

    economic_case = validated_case(())
    economic_outcome = resolve_economic_facts(
        economic_case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"),
        economic_case.context,
        economic_case.source_policy,
    )

    return assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_realized_clock(decision_harness),
        security_identities=(SecurityV1(schema_version="1", security_id=uid(21)),),
        listing_identities=(
            ListingV1(schema_version="1", listing_id=uid(22), venue=ListingVenue.XNAS),
        ),
        structural_eligibilities=(invoke_structural(*structural_inputs()),),
        economic_outcomes=(economic_outcome,),
        authentic_decision_views=(decision_view,),
        authentic_accounting_views=(accounting_view,),
    )


def _promotion_case(
    bundle: EvaluationInputBundleV1,
    proof: BundleProvenanceProofV1,
    snapshot: RealSourceSnapshotV1,
    qualified: QualifiedReplayContextV1,
) -> dict[str, Any]:
    """Assemble the full gate kwargs, evidence included.

    The snapshot and the qualified replay context are passed as objects rather
    than as hashes because the gate now re-audits the containment witness, so a
    caller that can only name the snapshot cannot open a promotion admission.
    """
    fixture = make_test_fixture(snapshot_hash=snapshot.snapshot_hash)
    fixture["admission"] = rebind_admission(
        fixture,
        input_bundle_hash=bundle.bundle_hash,
        provenance_proof_hash=proof.proof_hash,
    )
    fixture["bundle"] = bundle
    fixture["proof"] = proof
    fixture["qualified_context"] = qualified
    fixture["snapshot"] = snapshot
    return fixture


def _rehash_qualified(draft: QualifiedReplayContextV1) -> QualifiedReplayContextV1:
    """Recompute both dependent digests so only the mutation under test remains."""
    witness = tuple(
        sorted(draft.snapshot_binding_witness, key=lambda item: item.artifact_hash)
    )
    rebound = QualifiedReplayContextV1.model_construct(
        **(
            dict(draft)
            | {
                "snapshot_binding_witness": witness,
                "snapshot_binding_proof_hash": snapshot_binding_witness_hash(witness),
            }
        )
    )
    return QualifiedReplayContextV1.model_construct(
        **(dict(rebound) | {"qualified_hash": qualified_replay_context_hash(rebound)})
    )


# --- replay context identity ---


def test_context_identity_is_deterministic_and_self_excluding() -> None:
    first = derive_replay_context_identity(_decision_harness().context)
    second = derive_replay_context_identity(_decision_harness().context)
    assert first == second
    assert first.identity_hash == replay_context_identity_hash(first)


def test_context_identity_separates_unrelated_contexts() -> None:
    qualified = derive_replay_context_identity(_decision_harness().context)
    unrelated = derive_replay_context_identity(_unrelated_context())
    assert qualified.identity_hash != unrelated.identity_hash


def test_context_identity_tuples_are_canonically_sorted() -> None:
    identity = derive_replay_context_identity(_decision_harness().context)
    for values in (
        identity.observation_dataset_hashes,
        identity.session_dataset_hashes,
        identity.availability_policy_hashes,
        identity.retained_evidence_hashes,
        identity.supporting_artifact_hashes,
    ):
        assert tuple(sorted(set(values))) == values


def test_context_identity_populates_every_component() -> None:
    """Identity must not silently drop a class of context input."""
    identity = derive_replay_context_identity(_decision_harness().context)
    assert identity.observation_dataset_hashes
    assert identity.session_dataset_hashes
    assert identity.availability_policy_hashes
    assert identity.retained_evidence_hashes
    assert identity.supporting_artifact_hashes
    assert identity.m1b_context_hash is not None
    assert identity.m1c_context_hash is not None
    assert set(context_supplied_artifact_hashes(identity)) == {
        *identity.observation_dataset_hashes,
        *identity.session_dataset_hashes,
        *identity.availability_policy_hashes,
        *identity.retained_evidence_hashes,
        *identity.supporting_artifact_hashes,
        identity.m1b_context_hash,
        identity.m1c_context_hash,
    }


def test_context_identity_rejects_tampered_hash() -> None:
    identity = derive_replay_context_identity(_decision_harness().context)
    payload = identity.model_dump()
    payload["identity_hash"] = H["e"]
    with pytest.raises(ValidationError):
        ReplayContextIdentityV1.model_validate(payload)


# --- qualified replay context: the binding proof ---


def test_context_derived_from_the_qualified_snapshot_verifies() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)

    assert qualified.source_snapshot_hash == snapshot.snapshot_hash
    assert qualified.context_identity == derive_replay_context_identity(context)
    assert qualified.qualified_hash == qualified_replay_context_hash(qualified)
    assert qualified.snapshot_binding_proof_hash == snapshot_binding_witness_hash(
        qualified.snapshot_binding_witness
    )
    verify_snapshot_binding(qualified=qualified, snapshot=snapshot)


def test_binding_is_total_over_every_context_artifact() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)
    expected = context_supplied_artifact_hashes(qualified.context_identity)
    assert expected
    assert (
        tuple(entry.artifact_hash for entry in qualified.snapshot_binding_witness)
        == expected
    )


def test_unrelated_context_fails_closed_against_the_asserted_snapshot() -> None:
    """The adversarial case from issue 31. It currently succeeds; it must not."""
    qualified_context = _decision_harness().context
    snapshot = qualified_snapshot(qualified_context)
    unrelated = _unrelated_context()

    qualified_artifacts = set(
        context_supplied_artifact_hashes(
            derive_replay_context_identity(qualified_context)
        )
    )
    unrelated_artifacts = set(
        context_supplied_artifact_hashes(derive_replay_context_identity(unrelated))
    )
    assert not unrelated_artifacts <= qualified_artifacts

    with pytest.raises(ValueError, match="absent from source snapshot"):
        qualify_replay_context(context=unrelated, snapshot=snapshot)


def test_mint_rejects_a_qualified_context_from_a_different_replay_context() -> None:
    """Genuine replay over context B cannot mint a proof for snapshot A."""
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)

    unrelated = _unrelated_context()
    bundle = _promotion_bundle(harness, query, reference, snapshot)

    with pytest.raises(ValueError, match="replay context identity"):
        mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=unrelated,
            bundle=bundle,
            decision_requests=((reference, query),),
        )


def test_binding_rejects_a_vacuous_context_supplying_nothing() -> None:
    empty = M1dResolutionContext(
        observation_datasets=(),
        availability_policies={},
        retained_evidence={},
        supporting_artifacts={},
    )
    snapshot = snapshot_over((H["a"],))
    with pytest.raises(ValueError, match="supplies no artifacts"):
        qualify_replay_context(context=empty, snapshot=snapshot)


def test_witness_missing_one_context_artifact_fails_closed() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)

    truncated = QualifiedReplayContextV1.model_construct(
        **(
            dict(qualified)
            | {"snapshot_binding_witness": qualified.snapshot_binding_witness[1:]}
        )
    )
    with pytest.raises(ValueError, match="witness must cover every context artifact"):
        QualifiedReplayContextV1.model_validate(
            _rehash_qualified(truncated).model_dump()
        )


def test_witness_entry_pointing_at_a_nonexistent_snapshot_entry_fails_closed() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)

    first, *rest = qualified.snapshot_binding_witness
    forged = SnapshotBindingEntryV1(
        schema_version="1",
        artifact_hash=first.artifact_hash,
        snapshot_entry_hash=H["f"],
    )
    tampered = _rehash_qualified(
        QualifiedReplayContextV1.model_construct(
            **(dict(qualified) | {"snapshot_binding_witness": (forged, *rest)})
        )
    )
    with pytest.raises(ValueError, match="does not resolve to a snapshot entry"):
        verify_snapshot_binding(qualified=tampered, snapshot=snapshot)


def test_witness_entry_resolving_to_the_wrong_artifact_fails_closed() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)

    first, second, *rest = qualified.snapshot_binding_witness
    swapped = SnapshotBindingEntryV1(
        schema_version="1",
        artifact_hash=first.artifact_hash,
        snapshot_entry_hash=second.snapshot_entry_hash,
    )
    tampered = _rehash_qualified(
        QualifiedReplayContextV1.model_construct(
            **(dict(qualified) | {"snapshot_binding_witness": (swapped, second, *rest)})
        )
    )
    with pytest.raises(ValueError, match="does not attest artifact"):
        verify_snapshot_binding(qualified=tampered, snapshot=snapshot)


def test_reordering_the_witness_does_not_change_the_binding_proof_hash() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)

    reversed_witness = tuple(reversed(qualified.snapshot_binding_witness))
    assert reversed_witness != qualified.snapshot_binding_witness
    assert (
        snapshot_binding_witness_hash(reversed_witness)
        == qualified.snapshot_binding_proof_hash
    )
    # Reordering is normalized away by validation, not merely tolerated.
    payload = qualified.model_dump()
    payload["snapshot_binding_witness"] = tuple(
        entry.model_dump() for entry in reversed_witness
    )
    revalidated = QualifiedReplayContextV1.model_validate(payload)
    assert revalidated.snapshot_binding_witness == qualified.snapshot_binding_witness
    assert revalidated.qualified_hash == qualified.qualified_hash


def test_mutating_one_snapshot_entry_hash_invalidates_the_proof() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)

    first, *rest = qualified.snapshot_binding_witness
    mutated = SnapshotBindingEntryV1(
        schema_version="1",
        artifact_hash=first.artifact_hash,
        snapshot_entry_hash=H["c"],
    )
    payload = qualified.model_dump()
    payload["snapshot_binding_witness"] = tuple(
        entry.model_dump() for entry in (mutated, *rest)
    )
    with pytest.raises(ValidationError, match="snapshot_binding_proof_hash"):
        QualifiedReplayContextV1.model_validate(payload)


def test_witness_rejects_duplicate_artifact_entries() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)
    duplicated = (
        qualified.snapshot_binding_witness[0],
        *qualified.snapshot_binding_witness,
    )
    payload = qualified.model_dump()
    payload["snapshot_binding_witness"] = tuple(
        entry.model_dump() for entry in duplicated
    )
    with pytest.raises(ValidationError, match="unique by artifact_hash"):
        QualifiedReplayContextV1.model_validate(payload)


def test_qualified_context_rejects_tampered_self_hash() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)
    payload = qualified.model_dump()
    payload["qualified_hash"] = H["d"]
    with pytest.raises(ValidationError, match="qualified_hash"):
        QualifiedReplayContextV1.model_validate(payload)


def test_verify_snapshot_binding_rejects_a_different_snapshot() -> None:
    context = _decision_harness().context
    snapshot = qualified_snapshot(context)
    qualified = qualify_replay_context(context=context, snapshot=snapshot)
    other = snapshot_over(
        context_supplied_artifact_hashes(qualified.context_identity) + (H["a"],)
    )
    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        verify_snapshot_binding(qualified=qualified, snapshot=other)


# --- bundle provenance proof ---


def test_proof_identity_is_deterministic_and_versioned() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)

    first = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    second = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    assert first == second
    assert first.proof_version == BUNDLE_PROVENANCE_PROOF_VERSION
    assert first.proof_hash == bundle_provenance_proof_hash(first)
    assert first.bundle_hash == bundle.bundle_hash
    assert first.source_snapshot_hash == snapshot.snapshot_hash
    assert first.qualified_context_hash == qualified.qualified_hash
    # Request identity binds both the reference and the query, so a proof
    # cannot be reused across a different replay request.
    assert first.decision_request_hashes == (
        content_hash({"reference": reference, "query": query}),
    )
    assert first.accounting_request_hashes == ()


def test_proof_version_is_pinned_and_cannot_be_relabelled() -> None:
    annotation = BundleProvenanceProofV1.model_fields["proof_version"].annotation
    assert get_origin(annotation) is Literal
    assert get_args(annotation) == (BUNDLE_PROVENANCE_PROOF_VERSION,)

    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    payload = proof.model_dump()
    payload["proof_version"] = "m2-bundle-provenance-v2"
    # The message must come from the pinned literal, not from an incidental
    # self-hash mismatch that a widened annotation would also produce.
    with pytest.raises(
        ValidationError, match="Input should be 'm2-bundle-provenance-v1'"
    ):
        BundleProvenanceProofV1.model_validate(payload)


def test_proof_requires_at_least_one_component() -> None:
    """A proof covering nothing proves nothing, so it must not be constructible."""
    draft = BundleProvenanceProofV1.model_construct(
        schema_version="1",
        proof_version=BUNDLE_PROVENANCE_PROOF_VERSION,
        qualified_context_hash=H["1"],
        source_snapshot_hash=H["2"],
        decision_request_hashes=(),
        accounting_request_hashes=(),
        component_hashes=(),
        bundle_hash=H["3"],
        proof_hash=H["0"],
    )
    payload = draft.model_dump()
    payload["proof_hash"] = bundle_provenance_proof_hash(draft)
    with pytest.raises(ValidationError, match="at least one component hash"):
        BundleProvenanceProofV1.model_validate(payload)


def test_proof_rejects_tampered_self_hash() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    payload = proof.model_dump()
    payload["proof_hash"] = H["b"]
    with pytest.raises(ValidationError, match="proof_hash"):
        BundleProvenanceProofV1.model_validate(payload)


def test_mint_rejects_a_bundle_asserting_a_different_snapshot() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_realized_clock(harness),
        context=harness.context,
        decision_requests=((reference, query),),
        source_snapshot_hash=H["7"],
    )
    with pytest.raises(ValueError, match="bundle source snapshot"):
        mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=harness.context,
            bundle=bundle,
            decision_requests=((reference, query),),
        )


def test_mint_rejects_a_bundle_whose_views_replay_did_not_produce() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_realized_clock(harness),
        source_snapshot_hash=snapshot.snapshot_hash,
    )
    with pytest.raises(ValueError, match="view count mismatch against replay"):
        mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=harness.context,
            bundle=bundle,
            decision_requests=((reference, query),),
        )


def test_component_hashes_cover_all_six_authority_bearing_classes() -> None:
    bundle = _fully_populated_bundle()
    covered = set(bundle_component_hashes(bundle))

    # Every one of the six Decision 4 classes is present in this bundle, so a
    # coverage function that silently omits a class cannot pass this test.
    assert bundle.security_identities
    assert bundle.listing_identities
    assert bundle.structural_eligibilities
    assert bundle.economic_outcomes
    assert bundle.authentic_decision_views
    assert bundle.authentic_accounting_views

    assert content_hash(bundle.session_clock) in covered
    for member in (
        *bundle.security_identities,
        *bundle.listing_identities,
        *bundle.structural_eligibilities,
        *bundle.economic_outcomes,
        *bundle.authentic_decision_views,
        *bundle.authentic_accounting_views,
    ):
        assert content_hash(member) in covered

    expected_size = (
        1
        + len(bundle.security_identities)
        + len(bundle.listing_identities)
        + len(bundle.structural_eligibilities)
        + len(bundle.economic_outcomes)
        + len(bundle.authentic_decision_views)
        + len(bundle.authentic_accounting_views)
    )
    assert len(covered) == expected_size


def test_proof_carrying_a_component_the_bundle_lacks_fails_closed() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    padded = tuple(sorted({*proof.component_hashes, H["a"]}))
    forged = BundleProvenanceProofV1.model_construct(
        **(dict(proof) | {"component_hashes": padded})
    )
    forged = BundleProvenanceProofV1.model_validate(
        dict(forged.model_dump()) | {"proof_hash": bundle_provenance_proof_hash(forged)}
    )
    case = _promotion_case(bundle, forged, snapshot, qualified)
    with pytest.raises(ValueError, match="component coverage"):
        validate_promotion_admission(**case)


def test_bundle_member_missing_from_component_hashes_fails_closed() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )

    dropped = content_hash(bundle.authentic_decision_views[0])
    thinned = tuple(item for item in proof.component_hashes if item != dropped)
    assert len(thinned) == len(proof.component_hashes) - 1
    forged = BundleProvenanceProofV1.model_construct(
        **(dict(proof) | {"component_hashes": thinned})
    )
    forged = BundleProvenanceProofV1.model_validate(
        dict(forged.model_dump()) | {"proof_hash": bundle_provenance_proof_hash(forged)}
    )

    case = _promotion_case(bundle, forged, snapshot, qualified)
    with pytest.raises(ValueError, match="component coverage"):
        validate_promotion_admission(**case)


def test_swapping_a_single_component_after_minting_invalidates_the_proof() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )

    dropped = content_hash(bundle.session_clock)
    swapped = tuple(
        sorted({item for item in proof.component_hashes if item != dropped} | {H["a"]})
    )
    forged = BundleProvenanceProofV1.model_construct(
        **(dict(proof) | {"component_hashes": swapped})
    )
    forged = BundleProvenanceProofV1.model_validate(
        dict(forged.model_dump()) | {"proof_hash": bundle_provenance_proof_hash(forged)}
    )

    case = _promotion_case(bundle, forged, snapshot, qualified)
    with pytest.raises(ValueError, match="component coverage"):
        validate_promotion_admission(**case)


def test_build_proof_is_pure_assembly_over_the_same_bundle() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    minted = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    assembled = _build_bundle_provenance_proof(
        qualified_context_hash=qualified.qualified_hash,
        source_snapshot_hash=snapshot.snapshot_hash,
        bundle=bundle,
        decision_request_hashes=minted.decision_request_hashes,
    )
    assert assembled == minted


def test_the_assembly_function_is_not_exported() -> None:
    """The module boundary, not a docstring, keeps unverified assembly private.

    `_build_bundle_provenance_proof` accepts any 64-hex context hash and checks
    nothing, so an exported alias of it is a minting oracle. Re-exporting it
    under any public name, or renaming it back, must fail here.
    """
    aliases = {
        name
        for name, value in vars(replay_provenance).items()
        if not name.startswith("_") and value is _build_bundle_provenance_proof
    }
    assert aliases == set()
    assert not hasattr(replay_provenance, "build_bundle_provenance_proof")
    assert _build_bundle_provenance_proof.__name__ == "_build_bundle_provenance_proof"


# --- promotion admission gate ---


def test_promotion_gate_accepts_a_minted_proof() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    validate_promotion_admission(**_promotion_case(bundle, proof, snapshot, qualified))


def test_promotion_gate_rejects_a_proof_for_another_bundle() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    forged = BundleProvenanceProofV1.model_construct(
        **(dict(proof) | {"bundle_hash": H["9"]})
    )
    forged = BundleProvenanceProofV1.model_validate(
        dict(forged.model_dump()) | {"proof_hash": bundle_provenance_proof_hash(forged)}
    )
    case = _promotion_case(bundle, forged, snapshot, qualified)
    with pytest.raises(ValueError, match="provenance proof bundle hash"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_a_proof_for_another_snapshot() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    forged = BundleProvenanceProofV1.model_construct(
        **(dict(proof) | {"source_snapshot_hash": H["8"]})
    )
    forged = BundleProvenanceProofV1.model_validate(
        dict(forged.model_dump()) | {"proof_hash": bundle_provenance_proof_hash(forged)}
    )
    case = _promotion_case(bundle, forged, snapshot, qualified)
    with pytest.raises(ValueError, match="provenance proof snapshot"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_an_admission_not_bound_to_the_proof() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    case = _promotion_case(bundle, proof, snapshot, qualified)
    case["admission"] = rebind_admission(
        case, input_bundle_hash=bundle.bundle_hash, provenance_proof_hash=H["6"]
    )
    with pytest.raises(ValueError, match="admission is not bound to the provenance"):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_a_proof_with_an_inconsistent_self_hash() -> None:
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    case = _promotion_case(bundle, proof, snapshot, qualified)
    # model_construct bypasses the model validator, so the gate must not rely
    # on construction alone to have checked the proof's own digest.
    case["proof"] = BundleProvenanceProofV1.model_construct(
        **(dict(proof) | {"proof_hash": H["5"]})
    )
    case["admission"] = rebind_admission(
        case, input_bundle_hash=bundle.bundle_hash, provenance_proof_hash=H["5"]
    )
    with pytest.raises(ValueError, match="inconsistent provenance proof hash"):
        validate_promotion_admission(**case)


# --- the gate re-verifies the provenance evidence it is handed (issue 31) ---


def _forge_witness(qualified: QualifiedReplayContextV1) -> QualifiedReplayContextV1:
    """Replace every witness entry hash with an invented one, then reseal.

    The result is fully valid under `QualifiedReplayContextV1`: the contract can
    only check that the witness covers the context and that its two self-hashes
    are exact, because proving containment needs the snapshot and the model
    never sees one.
    """
    witness = tuple(
        SnapshotBindingEntryV1(
            schema_version="1",
            artifact_hash=entry.artifact_hash,
            snapshot_entry_hash=content_hash({"forged-entry-for": entry.artifact_hash}),
        )
        for entry in qualified.snapshot_binding_witness
    )
    draft = QualifiedReplayContextV1.model_construct(
        **(dict(qualified) | {"snapshot_binding_witness": witness})
    )
    return QualifiedReplayContextV1.model_validate(
        _rehash_qualified(draft).model_dump()
    )


def test_promotion_gate_rejects_a_qualified_context_the_proof_does_not_name() -> None:
    """A valid context for some other replay context does not satisfy the proof."""
    harness, query, reference = _decision_case()
    other_context = _unrelated_context()
    shared = snapshot_over(
        (
            *context_supplied_artifact_hashes(
                derive_replay_context_identity(harness.context)
            ),
            *context_supplied_artifact_hashes(
                derive_replay_context_identity(other_context)
            ),
        )
    )
    qualified = qualify_replay_context(context=harness.context, snapshot=shared)
    # Genuinely qualified, genuinely witnessed, and genuinely not this bundle's.
    foreign = qualify_replay_context(context=other_context, snapshot=shared)
    verify_snapshot_binding(qualified=foreign, snapshot=shared)
    assert foreign.qualified_hash != qualified.qualified_hash

    bundle = _promotion_bundle(harness, query, reference, shared)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    case = _promotion_case(bundle, proof, shared, foreign)

    with pytest.raises(
        ValueError,
        match=(
            r"^provenance proof qualified context mismatch: proof binds "
            rf"{qualified.qualified_hash}, context is {foreign.qualified_hash}$"
        ),
    ):
        validate_promotion_admission(**case)


def test_promotion_gate_rejects_a_qualified_context_for_another_snapshot() -> None:
    """The context must be bound to the very snapshot the bundle asserts."""
    harness, query, reference = _decision_case()
    artifacts = context_supplied_artifact_hashes(
        derive_replay_context_identity(harness.context)
    )
    asserted = snapshot_over(artifacts)
    # A second real snapshot that also attests this context, so the context is
    # honestly qualified: only the snapshot it is qualified against differs.
    other = snapshot_over((*artifacts, H["a"]))
    assert other.snapshot_hash != asserted.snapshot_hash
    elsewhere = qualify_replay_context(context=harness.context, snapshot=other)
    verify_snapshot_binding(qualified=elsewhere, snapshot=other)

    bundle = _promotion_bundle(harness, query, reference, asserted)
    proof = _build_bundle_provenance_proof(
        qualified_context_hash=elsewhere.qualified_hash,
        source_snapshot_hash=asserted.snapshot_hash,
        bundle=bundle,
    )
    case = _promotion_case(bundle, proof, asserted, elsewhere)

    with pytest.raises(
        ValueError,
        match=(
            r"^qualified replay context snapshot mismatch with bundle: context "
            rf"binds {other.snapshot_hash}, bundle asserts {asserted.snapshot_hash}$"
        ),
    ):
        validate_promotion_admission(**case)


def test_promotion_gate_re_audits_the_containment_witness() -> None:
    """The gate proves the witness against the snapshot, not merely its shape."""
    harness, query, reference = _decision_case()
    snapshot = qualified_snapshot(harness.context)
    honest = qualify_replay_context(context=harness.context, snapshot=snapshot)
    forged = _forge_witness(honest)
    assert forged.source_snapshot_hash == snapshot.snapshot_hash
    assert tuple(
        entry.artifact_hash for entry in forged.snapshot_binding_witness
    ) == tuple(entry.artifact_hash for entry in honest.snapshot_binding_witness)
    assert forged.qualified_hash != honest.qualified_hash

    bundle = _promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=forged,
        context=harness.context,
        bundle=bundle,
        decision_requests=((reference, query),),
    )
    case = _promotion_case(bundle, proof, snapshot, forged)

    entry = forged.snapshot_binding_witness[0]
    with pytest.raises(
        ValueError,
        match=(
            rf"^witness entry {entry.snapshot_entry_hash} does not resolve to a "
            rf"snapshot entry of {snapshot.snapshot_hash}$"
        ),
    ):
        validate_promotion_admission(**case)


def test_bundle_carries_no_proof_or_admission_reference() -> None:
    """Acyclicity: the proof references the bundle, never the reverse."""
    fields = set(EvaluationInputBundleV1.model_fields)
    for forbidden in (
        "provenance_proof_hash",
        "provenance_proof",
        "qualified_context_hash",
        "qualified_replay_context",
        "admission_hash",
        "admission",
    ):
        assert forbidden not in fields


def test_promotion_admission_requires_a_provenance_proof_hash() -> None:
    """An optional binding would let a promotion claim stand with no proof."""
    field = PromotionEvaluationAdmissionV1.model_fields["provenance_proof_hash"]
    assert field.is_required()
    assert field.default is PydanticUndefined

    payload = make_test_fixture()["admission"].model_dump()
    del payload["provenance_proof_hash"]
    with pytest.raises(ValidationError, match="Field required"):
        PromotionEvaluationAdmissionV1.model_validate(payload)


# --- exploratory lane stays unaffected ---


def test_exploratory_unqualified_context_stays_constructible_and_usable() -> None:
    harness, query, reference = _decision_case()
    # No snapshot, no qualification, no proof: the exploratory lane is untouched.
    identity = derive_replay_context_identity(harness.context)
    assert identity.identity_hash

    bundle = build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=normalization_scheduled_clock(harness),
        context=harness.context,
        decision_requests=((reference, query),),
    )
    assert bundle.source_snapshot_hash is None
    verify_evaluation_input_bundle(
        bundle=bundle,
        context=harness.context,
        decision_requests=((reference, query),),
    )

    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=bundle.bundle_hash,
        acknowledged_limitations=bundle.required_limitations,
        admission_hash=H["0"],
    )
    admission = ExploratoryEvaluationAdmissionV1.model_validate(
        draft.model_copy(
            update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
        ).model_dump()
    )
    validate_exploratory_admission(admission=admission, bundle=bundle)


def test_m1d_resolution_context_is_unmodified_by_this_contract() -> None:
    """The contract is additive: identity is derived, never stored on the context."""
    context = _decision_harness().context
    assert not hasattr(context, "snapshot_hash")
    assert not hasattr(context, "qualified_context")
    derive_replay_context_identity(context)
