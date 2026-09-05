"""Behavioral contracts for additive M1c economic primitives and queries."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from economic_test_support import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    cash_component,
    instant,
    public_channel,
    uid,
)
from pydantic import BaseModel, TypeAdapter, ValidationError

from drift.domain.economic_common import (
    ActionKind,
    CanonicalCash,
    EconomicAssociationV1,
    EconomicRecipientV1,
    EconomicShareBasisV1,
    EconomicSourceKeyV1,
    FractionTreatmentV1,
    PositiveRatioV1,
    ShareComponentV1,
    economic_implementation_hash,
)
from drift.domain.economic_queries import (
    EconomicApplicabilityV1,
    EconomicSafeFactProjectionV1,
    MarketDecisionQueryV1,
    MarketDecisionReferenceV1,
    MarketOutcomeQueryV1,
    MarketOutcomeReferenceV1,
    MarketSelectionProofV1,
    market_cutoff,
    market_horizon,
)
from drift.domain.temporal import AvailabilityPolicyV1
from drift.serialization.canonical import content_hash


def decision_values() -> dict[str, Any]:
    """Return literal decision input values, independently of query helpers."""
    return {
        "schema_version": "1",
        "kind": "decision",
        "purpose": "economic_facts",
        "security_id": uid(1),
        "action_kinds": (ActionKind.REGULAR_CASH_DIVIDEND,),
        "decision_time": instant(5),
        "knowledge_cutoff": instant(4),
        "effective_cutoff": instant(3),
        "history_start": instant(1),
        "requested_channel": public_channel(),
        "availability_policy_id": "public-v1",
        "availability_policy_hash": HASH_A,
        "source_selection_policy_hash": HASH_B,
        "input_context_hash": HASH_C,
    }


def outcome_values() -> dict[str, Any]:
    """Return literal outcome input values, independently of query helpers."""
    return {
        "schema_version": "1",
        "kind": "outcome",
        "purpose": "economic_outcome",
        "security_id": uid(1),
        "action_kinds": (ActionKind.REGULAR_CASH_DIVIDEND,),
        "economic_horizon": instant(3),
        "evidence_vintage_cutoff": instant(5),
        "history_start": instant(1),
        "requested_channel": public_channel(),
        "availability_policy_id": "public-v1",
        "availability_policy_hash": HASH_A,
        "source_selection_policy_hash": HASH_B,
        "input_context_hash": HASH_C,
    }


@pytest.mark.parametrize(
    "text", ["1e3", "+1", "01", "1.0", "-0", "0.00", "NaN", "Infinity"]
)
def test_noncanonical_cash_rejected(text: str) -> None:
    """A relaxed cash parser would admit a distinct numeric spelling."""
    with pytest.raises(ValidationError):
        TypeAdapter(CanonicalCash).validate_python(text)


def test_exact_ratio_and_cash_round_trip() -> None:
    """A non-reduced ratio or noncanonical amount must not enter a source record."""
    ratio = PositiveRatioV1(numerator="3", denominator="2")
    assert PositiveRatioV1.model_validate_json(ratio.model_dump_json()) == ratio
    assert TypeAdapter(CanonicalCash).validate_python("5.125") == "5.125"
    with pytest.raises(ValidationError):
        PositiveRatioV1(numerator="6", denominator="4")
    with pytest.raises(ValidationError, match="ratio_meaning"):
        ShareComponentV1(  # type: ignore[call-arg]
            kind="shares",
            component_id="share-1",
            recipient=EconomicRecipientV1(kind="security", security_id=uid(2)),
            ratio=PositiveRatioV1(numerator="1", denominator="2"),
            unit_basis=EconomicShareBasisV1(
                security_id=uid(1), share_basis="predecessor_pre_action"
            ),
            fraction_treatment=FractionTreatmentV1(kind="unknown"),
            applicability="ordinary_passive_holder",
            conditions=(),
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"knowledge_cutoff": instant(6)}, "knowledge cutoff"),
        ({"effective_cutoff": instant(6)}, "effective cutoff"),
        ({"history_start": instant(4)}, "history start"),
    ],
)
def test_decision_rejects_invalid_k_e_t_window(
    updates: dict[str, Any], message: str
) -> None:
    """A missing K/E/T ordering check would admit future knowledge or a bad range."""
    with pytest.raises(ValidationError, match=message):
        MarketDecisionQueryV1(**(decision_values() | updates))


def test_outcome_allows_independent_horizon_and_vintage_order() -> None:
    """Imposing a made-up H/V order would reject valid ex-post evidence queries."""
    query = MarketOutcomeQueryV1(
        **(
            outcome_values()
            | {"economic_horizon": instant(5), "evidence_vintage_cutoff": instant(3)}
        )
    )
    assert market_cutoff(query) == instant(3)
    assert market_horizon(query) == instant(5)


def test_outcome_rejects_history_start_after_horizon() -> None:
    """A horizon cannot silently exclude the query's declared history start."""
    with pytest.raises(ValidationError, match="history start"):
        MarketOutcomeQueryV1(**(outcome_values() | {"history_start": instant(4)}))


def test_query_helpers_choose_the_selection_cutoff_and_economic_horizon() -> None:
    """Swapping K with E would evaluate decision evidence at the wrong clock."""
    query = MarketDecisionQueryV1(**decision_values())
    assert market_cutoff(query) == instant(4)
    assert market_horizon(query) == instant(3)


def test_query_rejects_unsorted_or_duplicate_action_kinds() -> None:
    """A noncanonical action-class set would give equivalent queries distinct hashes."""
    values = decision_values()
    with pytest.raises(ValidationError, match="sorted and unique"):
        MarketDecisionQueryV1(
            **(
                values
                | {
                    "action_kinds": (
                        ActionKind.STOCK_DIVIDEND,
                        ActionKind.REGULAR_CASH_DIVIDEND,
                    )
                }
            )
        )
    with pytest.raises(ValidationError, match="sorted and unique"):
        MarketDecisionQueryV1(
            **(
                values
                | {
                    "action_kinds": (
                        ActionKind.REGULAR_CASH_DIVIDEND,
                        ActionKind.REGULAR_CASH_DIVIDEND,
                    )
                }
            )
        )


def test_query_rejects_opposite_role_fields_and_naive_dates() -> None:
    """A permissive query model could blend decision and outcome semantics."""
    with pytest.raises(ValidationError):
        MarketDecisionQueryV1(**(decision_values() | {"economic_horizon": instant(3)}))
    with pytest.raises(ValidationError):
        MarketDecisionQueryV1(
            **(decision_values() | {"evidence_vintage_cutoff": instant(3)})
        )
    with pytest.raises(ValidationError):
        MarketOutcomeQueryV1(**(outcome_values() | {"decision_time": instant(5)}))
    for field in ("knowledge_cutoff", "effective_cutoff"):
        with pytest.raises(ValidationError):
            MarketOutcomeQueryV1(**(outcome_values() | {field: instant(3)}))
    with pytest.raises(ValidationError):
        MarketDecisionQueryV1(
            **(decision_values() | {"decision_time": instant(5).replace(tzinfo=None)})
        )


def test_source_association_requires_a_truthful_union_shape() -> None:
    """A claim marked identified must not degrade into an unresolvable source link."""
    target = EconomicSourceKeyV1(
        source_id="issuer", family="terms", native_record_id="notice-1"
    )
    assert EconomicAssociationV1(kind="identified", target=target).target == target
    with pytest.raises(ValidationError, match="identified association"):
        EconomicAssociationV1(kind="identified", target=None)
    with pytest.raises(ValidationError, match="native hint"):
        EconomicAssociationV1(kind="native_hint", native_hint=None)
    with pytest.raises(ValidationError, match="unknown association"):
        EconomicAssociationV1(kind="unknown", reason=None)


def test_recipient_requires_a_truthful_union_shape() -> None:
    """A source recipient cannot be both identified and unresolved property."""
    assert EconomicRecipientV1(kind="security", security_id=uid(2)).security_id == uid(
        2
    )
    with pytest.raises(ValidationError, match="unresolved property"):
        EconomicRecipientV1(kind="unresolved_property", source_property_key="property")
    with pytest.raises(ValidationError, match="security recipient"):
        EconomicRecipientV1(
            kind="security", security_id=uid(2), source_property_key="property"
        )


def test_projection_rejects_impossible_family_role_and_status_combination() -> None:
    """Changing a terms projection to delivered must not create a realized fact."""
    applicability = EconomicApplicabilityV1(
        source_record_hash=HASH_A,
        family="terms",
        status="upcoming",
        reasons=("scheduled date is after the window",),
    )
    values: dict[str, Any] = {
        "schema_version": "1",
        "query_hash": HASH_B,
        "source_record_hash": HASH_A,
        "family": "terms",
        "security_id": uid(1),
        "action_kind": ActionKind.REGULAR_CASH_DIVIDEND,
        "applicability": applicability,
        "component_role": "terms",
        "known_components": (),
        "withheld_components": (),
        "claim_status": "unknown",
        "fact_status": "terms",
        "consideration_status": "unknown",
        "residual_status": "unknown",
        "optional_context_reasons": (),
        "dependency_proof_hashes": (),
        "projection_algorithm_spec_hash": HASH_C,
        "projection_implementation_hash": HASH_D,
    }
    assert EconomicSafeFactProjectionV1(**values).component_role == "terms"
    with pytest.raises(ValidationError, match="component role"):
        EconomicSafeFactProjectionV1(**(values | {"component_role": "delivered"}))
    with pytest.raises(ValidationError, match="fact status"):
        EconomicSafeFactProjectionV1(**(values | {"fact_status": "occurred"}))


def test_projection_matrix_rejects_cancelled_effect_authority() -> None:
    """Cancellation cannot establish extinguishment, no consideration, or closure."""
    applicability = EconomicApplicabilityV1(
        source_record_hash=HASH_A,
        family="effect",
        status="in_window",
        reasons=("effect evidence is in the requested window",),
    )
    values: dict[str, Any] = {
        "schema_version": "1",
        "query_hash": HASH_B,
        "source_record_hash": HASH_A,
        "family": "effect",
        "security_id": uid(1),
        "action_kind": ActionKind.REGULAR_CASH_DIVIDEND,
        "applicability": applicability,
        "component_role": "owed",
        "known_components": (),
        "withheld_components": (),
        "claim_status": "extinguished",
        "fact_status": "cancelled_action",
        "consideration_status": "explicit_none",
        "residual_status": "closed_for_action",
        "optional_context_reasons": (),
        "dependency_proof_hashes": (),
        "projection_algorithm_spec_hash": HASH_C,
        "projection_implementation_hash": HASH_D,
    }
    with pytest.raises(ValidationError, match="claim status"):
        EconomicSafeFactProjectionV1(**values)
    with pytest.raises(ValidationError, match="components"):
        EconomicSafeFactProjectionV1(
            **(
                values
                | {
                    "claim_status": "unknown",
                    "consideration_status": "unknown",
                    "residual_status": "unknown",
                    "known_components": (cash_component(),),
                }
            )
        )


def test_projection_matrix_permits_partial_delivered_settlement() -> None:
    """A delivered installment can retain its sourced outstanding residual."""
    projection = EconomicSafeFactProjectionV1(
        schema_version="1",
        query_hash=HASH_B,
        source_record_hash=HASH_A,
        family="settlement",
        security_id=uid(1),
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        applicability=EconomicApplicabilityV1(
            source_record_hash=HASH_A,
            family="settlement",
            status="in_window",
            reasons=("settlement evidence is in the requested window",),
        ),
        component_role="delivered",
        known_components=(cash_component(),),
        withheld_components=(),
        claim_status="unknown",
        fact_status="delivered",
        consideration_status="components",
        residual_status="outstanding",
        optional_context_reasons=(),
        dependency_proof_hashes=(),
        projection_algorithm_spec_hash=HASH_C,
        projection_implementation_hash=HASH_D,
    )
    assert projection.residual_status == "outstanding"


@pytest.mark.parametrize(
    ("family", "fact_status", "claim_status", "consideration", "residual"),
    (
        ("terms", "terms", "unknown", "unknown", "unknown"),
        ("effect", "occurred", "continuing", "explicit_none", "closed_for_action"),
        ("effect", "cancelled_action", "unknown", "unknown", "unknown"),
        ("effect", "unknown", "unknown", "unknown", "unknown"),
        (
            "settlement",
            "delivered",
            "unknown",
            "components",
            "closed_for_occurrence",
        ),
    ),
)
def test_projection_matrix_accepts_each_source_fact_row(
    family: Any,
    fact_status: Any,
    claim_status: Any,
    consideration: Any,
    residual: Any,
) -> None:
    """Each row represents only authority owned by its source fact family."""
    component_role: Any = {
        "terms": "terms",
        "effect": "owed",
        "settlement": "delivered",
    }[family]
    known_components = (cash_component(),) if consideration == "components" else ()
    projection = EconomicSafeFactProjectionV1(
        schema_version="1",
        query_hash=HASH_B,
        source_record_hash=HASH_A,
        family=family,
        security_id=uid(1),
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        applicability=EconomicApplicabilityV1(
            source_record_hash=HASH_A,
            family=family,
            status="in_window",
            reasons=("source fact is in the requested window",),
        ),
        component_role=component_role,
        known_components=known_components,
        withheld_components=(),
        claim_status=claim_status,
        fact_status=fact_status,
        consideration_status=consideration,
        residual_status=residual,
        optional_context_reasons=(),
        dependency_proof_hashes=(),
        projection_algorithm_spec_hash=HASH_C,
        projection_implementation_hash=HASH_D,
    )
    assert projection.fact_status == fact_status


def test_projection_matrix_rejects_components_for_unknown_effect() -> None:
    """An unknown effect cannot expose a payment or an inferred consideration state."""
    with pytest.raises(ValidationError, match="consideration status"):
        EconomicSafeFactProjectionV1(
            schema_version="1",
            query_hash=HASH_B,
            source_record_hash=HASH_A,
            family="effect",
            security_id=uid(1),
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            applicability=EconomicApplicabilityV1(
                source_record_hash=HASH_A,
                family="effect",
                status="indeterminate",
                reasons=("effect boundary is unknown",),
            ),
            component_role="owed",
            known_components=(cash_component(),),
            withheld_components=(),
            claim_status="unknown",
            fact_status="unknown",
            consideration_status="components",
            residual_status="unknown",
            optional_context_reasons=(),
            dependency_proof_hashes=(),
            projection_algorithm_spec_hash=HASH_C,
            projection_implementation_hash=HASH_D,
        )


def test_decision_reference_rejects_self_consistent_outcome_json() -> None:
    """An outcome capability cannot pose as a decision-safe reference."""
    outcome = MarketOutcomeReferenceV1(
        schema_version="1",
        kind="outcome_reference",
        query_hash=HASH_A,
        selection_proof_hash=HASH_B,
        selected_record_hashes=(),
        projection_hashes=(),
    )
    with pytest.raises(ValidationError):
        MarketDecisionReferenceV1.model_validate_json(outcome.model_dump_json())


def test_hash_collections_are_canonical_and_zero_selected_hashes_are_valid() -> None:
    """An empty authorized set differs from an invalid or duplicate hash collection."""
    reference = MarketDecisionReferenceV1(
        schema_version="1",
        kind="decision_reference",
        query_hash=HASH_A,
        selection_proof_hash=HASH_B,
        selected_record_hashes=(),
        projection_hashes=(),
    )
    assert reference.selected_record_hashes == ()
    assert content_hash(reference) == content_hash(reference.model_dump(mode="python"))
    canonicalized = MarketDecisionReferenceV1(
        schema_version="1",
        kind="decision_reference",
        query_hash=HASH_A,
        selection_proof_hash=HASH_B,
        selected_record_hashes=(HASH_B, HASH_A),
        projection_hashes=(),
    )
    assert canonicalized.selected_record_hashes == (HASH_A, HASH_B)
    with pytest.raises(ValidationError, match="unique"):
        MarketDecisionReferenceV1(
            schema_version="1",
            kind="decision_reference",
            query_hash=HASH_A,
            selection_proof_hash=HASH_B,
            selected_record_hashes=(HASH_A, HASH_A),
            projection_hashes=(),
        )


def test_literal_digests_bind_contract_identities() -> None:
    """Changing a content-addressed economic contract must not retain its old digest."""
    query = MarketDecisionQueryV1(**decision_values())
    policy = AvailabilityPolicyV1(
        policy_id="public-v1", permitted_rule_hashes=(HASH_A,)
    )
    association = EconomicAssociationV1(
        kind="identified",
        target=EconomicSourceKeyV1(
            source_id="issuer", family="terms", native_record_id="notice-1"
        ),
        asserted_target_version_hash=HASH_A,
    )
    proof = MarketSelectionProofV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        input_context_hash=HASH_C,
        source_selection_policy_hash=HASH_B,
        selection_algorithm="drift-m1c-economic-selection-v1",
        selection_algorithm_spec_hash=HASH_D,
        selection_implementation_hash=HASH_A,
        dataset_proofs=(),
        identity_proofs=(),
        revision_selected_record_hashes=(),
        applicability=(),
        raw_materializable_record_hashes=(),
        projection_hashes=(),
        unresolved_chain_hashes=(),
    )
    reference = MarketDecisionReferenceV1(
        schema_version="1",
        kind="decision_reference",
        query_hash=content_hash(query),
        selection_proof_hash=content_hash(proof),
        selected_record_hashes=(),
        projection_hashes=(),
    )
    outcome = MarketOutcomeReferenceV1(
        schema_version="1",
        kind="outcome_reference",
        query_hash=HASH_A,
        selection_proof_hash=HASH_B,
        selected_record_hashes=(),
        projection_hashes=(),
    )
    assert {
        "query": content_hash(query),
        "policy": content_hash(policy),
        "proof": content_hash(proof),
        "reference": content_hash(reference),
        "association": content_hash(association),
        "outcome": content_hash(outcome),
    } == {
        "query": "b870575e2ca0dbf2c748b80960124b5e8caa8d6c300825318ba8f13572806904",
        "policy": "2da00acfc87b45f2b950d26e7a0be7b41cb1003e7f11cbf2ec2774e4cff9829f",
        "proof": "372977ff7fb38b7c152c55a594fd8ac92200c630214e02c51db8829b674adb26",
        "reference": "8dab61844801956efb552258d5e1151bca0bbc24cc510c49b530e5e67ff0dda7",
        "association": (
            "be3fc852c8a0e936bd0991a51c43ac4e926faaa7cbaf88a507db341aad3d5071"
        ),
        "outcome": "ab692214b7d7220ac9be7d1a0eca3782e841397749cafcd9f2b87767751d4353",
    }


def test_digest_mutation_table_changes_every_fixture_identity() -> None:
    """A relevant field mutation must change its contract's full canonical digest."""
    query = MarketDecisionQueryV1(**decision_values())
    policy = AvailabilityPolicyV1(
        policy_id="public-v1", permitted_rule_hashes=(HASH_A,)
    )
    association = EconomicAssociationV1(
        kind="identified",
        target=EconomicSourceKeyV1(
            source_id="issuer", family="terms", native_record_id="notice-1"
        ),
    )
    proof = MarketSelectionProofV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        input_context_hash=HASH_C,
        source_selection_policy_hash=HASH_B,
        selection_algorithm="drift-m1c-economic-selection-v1",
        selection_algorithm_spec_hash=HASH_D,
        selection_implementation_hash=HASH_A,
        dataset_proofs=(),
        identity_proofs=(),
        revision_selected_record_hashes=(),
        applicability=(),
        raw_materializable_record_hashes=(),
        projection_hashes=(),
        unresolved_chain_hashes=(),
    )
    reference = MarketDecisionReferenceV1(
        schema_version="1",
        kind="decision_reference",
        query_hash=content_hash(query),
        selection_proof_hash=content_hash(proof),
        selected_record_hashes=(),
        projection_hashes=(),
    )
    outcome = MarketOutcomeReferenceV1(
        schema_version="1",
        kind="outcome_reference",
        query_hash=HASH_A,
        selection_proof_hash=HASH_B,
        selected_record_hashes=(),
        projection_hashes=(),
    )
    mutations = (
        (query, query.model_copy(update={"input_context_hash": HASH_D})),
        (policy, policy.model_copy(update={"policy_id": "public-v2"})),
        (
            association,
            EconomicAssociationV1(kind="unknown", reason="no source link supplied"),
        ),
        (proof, proof.model_copy(update={"projection_hashes": (HASH_A,)})),
        (reference, reference.model_copy(update={"projection_hashes": (HASH_A,)})),
        (outcome, outcome.model_copy(update={"selected_record_hashes": (HASH_A,)})),
    )
    for original, changed in mutations:
        assert content_hash(original) != content_hash(changed)


def test_digest_mutation_table_covers_every_identity_field() -> None:
    """No mutable semantic or provenance field is omitted from a full digest."""
    query = MarketDecisionQueryV1(**decision_values())
    policy = AvailabilityPolicyV1(
        policy_id="public-v1", permitted_rule_hashes=(HASH_A,)
    )
    association = EconomicAssociationV1(
        kind="identified",
        target=EconomicSourceKeyV1(
            source_id="issuer", family="terms", native_record_id="notice-1"
        ),
        asserted_target_version_hash=HASH_A,
    )
    proof = MarketSelectionProofV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        input_context_hash=HASH_C,
        source_selection_policy_hash=HASH_B,
        selection_algorithm="drift-m1c-economic-selection-v1",
        selection_algorithm_spec_hash=HASH_D,
        selection_implementation_hash=HASH_A,
        dataset_proofs=(),
        identity_proofs=(),
        revision_selected_record_hashes=(),
        applicability=(),
        raw_materializable_record_hashes=(),
        projection_hashes=(),
        unresolved_chain_hashes=(),
    )
    reference = MarketDecisionReferenceV1(
        schema_version="1",
        kind="decision_reference",
        query_hash=content_hash(query),
        selection_proof_hash=content_hash(proof),
        selected_record_hashes=(),
        projection_hashes=(),
    )
    outcome = MarketOutcomeReferenceV1(
        schema_version="1",
        kind="outcome_reference",
        query_hash=HASH_A,
        selection_proof_hash=HASH_B,
        selected_record_hashes=(),
        projection_hashes=(),
    )

    def assert_fields_are_hashed(
        model: BaseModel, replacements: dict[str, object], literals: set[str]
    ) -> None:
        original = model.model_dump(mode="python")
        assert set(replacements) == set(original) - literals
        for field, replacement in replacements.items():
            assert content_hash(original) != content_hash(
                original | {field: replacement}
            )

    assert_fields_are_hashed(
        query,
        {
            "security_id": uid(3),
            "action_kinds": (ActionKind.STOCK_DIVIDEND,),
            "history_start": instant(2),
            "requested_channel": public_channel().model_copy(
                update={"identifier": "issuer-notices"}
            ),
            "availability_policy_id": "public-v2",
            "availability_policy_hash": HASH_D,
            "source_selection_policy_hash": HASH_D,
            "input_context_hash": HASH_D,
            "decision_time": instant(6),
            "knowledge_cutoff": instant(3),
            "effective_cutoff": instant(2),
        },
        {"schema_version", "kind", "purpose"},
    )
    assert_fields_are_hashed(
        policy,
        {"policy_id": "public-v2", "permitted_rule_hashes": (HASH_D,)},
        set(),
    )
    assert_fields_are_hashed(
        association,
        {
            "kind": "unknown",
            "target": EconomicSourceKeyV1(
                source_id="issuer-v2", family="terms", native_record_id="notice-1"
            ),
            "asserted_target_version_hash": HASH_D,
            "native_hint": "notice-1",
            "reason": "source did not give an exact key",
        },
        set(),
    )
    assert_fields_are_hashed(
        proof,
        {
            "query": MarketOutcomeQueryV1(**outcome_values()),
            "query_hash": HASH_D,
            "input_context_hash": HASH_D,
            "source_selection_policy_hash": HASH_D,
            "selection_algorithm_spec_hash": HASH_A,
            "selection_implementation_hash": HASH_D,
            "dataset_proofs": ({"dataset": "alternate"},),
            "identity_proofs": ({"identity": "alternate"},),
            "revision_selected_record_hashes": (HASH_A,),
            "applicability": ({"status": "alternate"},),
            "raw_materializable_record_hashes": (HASH_A,),
            "projection_hashes": (HASH_A,),
            "unresolved_chain_hashes": (HASH_A,),
        },
        {"schema_version", "selection_algorithm"},
    )
    assert_fields_are_hashed(
        reference,
        {
            "query_hash": HASH_D,
            "selection_proof_hash": HASH_D,
            "selected_record_hashes": (HASH_A,),
            "projection_hashes": (HASH_A,),
        },
        {"schema_version", "kind"},
    )
    assert_fields_are_hashed(
        outcome,
        {
            "query_hash": HASH_D,
            "selection_proof_hash": HASH_D,
            "selected_record_hashes": (HASH_A,),
            "projection_hashes": (HASH_A,),
        },
        {"schema_version", "kind"},
    )
    for model, field, invalid in (
        (query, "schema_version", "2"),
        (query, "kind", "outcome"),
        (query, "purpose", "economic_outcome"),
        (proof, "schema_version", "2"),
        (proof, "selection_algorithm", "other"),
        (reference, "schema_version", "2"),
        (reference, "kind", "outcome_reference"),
        (outcome, "schema_version", "2"),
        (outcome, "kind", "decision_reference"),
    ):
        with pytest.raises(ValidationError):
            type(model).model_validate(
                model.model_dump(mode="python") | {field: invalid}
            )


def test_implementation_hash_covers_full_package_bytes_not_its_semantic_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A byte change anywhere in the package must change the code identity digest."""
    import drift.domain.economic_common as economic_common

    real_package = Path(economic_common.__file__).resolve().parents[1]
    copied_package = tmp_path / "drift"
    shutil.copytree(real_package, copied_package)
    copied_module = copied_package / "domain" / "economic_common.py"
    monkeypatch.setattr(economic_common, "__file__", str(copied_module))
    original = economic_implementation_hash()
    target = copied_package / "domain" / "unrelated.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    assert economic_implementation_hash() != original


@pytest.mark.parametrize("link_kind", ("package", "module", "file", "directory"))
def test_implementation_hash_rejects_lexical_symlink_layouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link_kind: str
) -> None:
    """A lexical source-tree link must not be silently resolved or skipped."""
    import drift.domain.economic_common as economic_common

    real_package = Path(economic_common.__file__).resolve().parents[1]
    copied_package = tmp_path / "drift"
    shutil.copytree(real_package, copied_package)
    copied_module = copied_package / "domain" / "economic_common.py"
    if link_kind == "package":
        linked_package = tmp_path / "linked-drift"
        linked_package.symlink_to(copied_package, target_is_directory=True)
        copied_module = linked_package / "domain" / "economic_common.py"
    elif link_kind == "module":
        linked_module = copied_package / "domain" / "linked-economic-common.py"
        linked_module.symlink_to(copied_module)
        copied_module = linked_module
    elif link_kind == "file":
        target = tmp_path / "linked-source-target.py"
        target.write_text("VALUE = 1\n", encoding="utf-8")
        (copied_package / "domain" / "linked-source.py").symlink_to(target)
    else:
        target_directory = tmp_path / "linked-source-directory"
        target_directory.mkdir()
        (target_directory / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
        (copied_package / "linked-directory").symlink_to(
            target_directory, target_is_directory=True
        )
    monkeypatch.setattr(economic_common, "__file__", str(copied_module))
    with pytest.raises(ValueError, match="symlink|real directory|regular file"):
        economic_implementation_hash()
