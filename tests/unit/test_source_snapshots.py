"""Unit tests for M1e real-source snapshots and snapshot-frozen transition."""

import json
from datetime import UTC, date, datetime
from typing import cast
from uuid import uuid7

import pytest
from economic_test_support import validated_case
from pydantic import ValidationError
from session_test_support import (
    schedule_record,
    session_dataset,
    session_supporting_artifacts,
)
from test_universes import structural_inputs

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    TemporalBoundaryClaimV1,
)
from drift.domain.common import SHA256Hash
from drift.domain.qualification import (
    AcquisitionState,
    ConsumerPurpose,
    M1ePilotStateV1,
    PilotStage,
    PurposeStageStateV1,
    QualificationTargetV1,
)
from drift.domain.source_snapshots import (
    CanonicalReplayInputEntryV1,
    ConsistencyStatus,
    CoordinatedCutoffRuleV1,
    CrossComponentConsistencyDecisionV1,
    ExpectedOutputKind,
    ExpectedOutputV1,
    ProviderReleaseEvidenceV1,
    RawReplayInputEntryV1,
    RealSourceSnapshotV1,
    ReplayInputEntryV1,
    ReplayInputKind,
    SourceComponentRole,
    cross_component_consistency_decision_hash,
    real_source_snapshot_hash,
)
from drift.domain.temporal import SourcePrecision
from drift.markets.economic_validation import (
    EconomicResolutionContext,
    economic_context_hash,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
)
from drift.markets.universes import StructuralResolutionContext
from drift.qualification.lifecycle import (
    transition_snapshot_frozen,
)
from drift.qualification.snapshots import (
    ExistingContractContexts,
    verify_real_source_snapshot,
)
from drift.serialization.canonical import content_hash

H = tuple((f"{index:x}" * 64)[:64] for index in range(1, 20))
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _make_artifact(payload: bytes) -> tuple[ArtifactReference, VerifiedArtifactBytes]:
    from hashlib import sha256

    chash = sha256(payload).hexdigest()
    ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.OTHER,
        content_hash=chash,
        location=f"drift+sha256://{chash}",
    )
    vbytes = VerifiedArtifactBytes(
        data=payload,
        byte_size=len(payload),
        content_hash=chash,
    )
    return ref, vbytes


def _make_temporal_claim(iso_date: str) -> TemporalBoundaryClaimV1:
    ref, _ = _make_artifact(b"temporal-evidence")
    instant = datetime.fromisoformat(f"{iso_date}T00:00:00Z")
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=instant,
        upper_bound=instant,
        source_precision=SourcePrecision.SECOND,
        source_time_label=f"{iso_date}T00:00:00Z",
        source_timezone=None,
        evidence_reference=ref,
    )


def _make_release_evidence(
    role: SourceComponentRole = SourceComponentRole.IDENTITY_UNIVERSE,
    release_id: str = "rel-1",
    receipt_hash: SHA256Hash = H[0],
) -> ProviderReleaseEvidenceV1:
    ref, _ = _make_artifact(b"release-evidence")
    return ProviderReleaseEvidenceV1(
        component_role=role,
        provider_release_id=release_id,
        provider_object_ids=("obj-1", "obj-2"),
        native_state_label="final",
        temporal_boundary=_make_temporal_claim("2026-01-01"),
        availability_evidence_hashes=(H[1],),
        acquisition_receipt_hash=receipt_hash,
        evidence_references=(ref,),
    )


def _make_cutoff_rule(profile_set_hash: SHA256Hash = H[2]) -> CoordinatedCutoffRuleV1:
    ref, _ = _make_artifact(b"cutoff-rule-evidence")
    return CoordinatedCutoffRuleV1(
        profile_set_hash=profile_set_hash,
        per_component_cutoff_rules={
            SourceComponentRole.IDENTITY_UNIVERSE: "2026-01-01T00:00:00Z",
            SourceComponentRole.ACTION_TERMS: "2026-01-01T00:00:00Z",
            SourceComponentRole.OBSERVATIONS: "2026-01-01T00:00:00Z",
        },
        revision_horizon="P30D",
        ordering_rule="arrival_time_then_sequence",
        semantic_hash=H[3],
        evidence_references=(ref,),
    )


def _make_consistency_decision(
    release_hashes: tuple[SHA256Hash, ...],
    rule_hash: SHA256Hash,
    status: ConsistencyStatus = ConsistencyStatus.PASS,
) -> CrossComponentConsistencyDecisionV1:
    decision = CrossComponentConsistencyDecisionV1.model_construct(
        component_release_hashes=release_hashes,
        coordinated_rule_hash=rule_hash,
        result=status,
        conflicts_and_gaps=(),
        decision_policy_hash=H[4],
        decision_id=uuid7(),
        decided_at=NOW,
        decision_hash=content_hash("placeholder"),
    )
    computed_hash = cross_component_consistency_decision_hash(decision)
    return decision.model_copy(update={"decision_hash": computed_hash})


def _make_valid_contexts() -> tuple[ExistingContractContexts, str, str]:
    # M1c authentic context
    harness = validated_case(())
    m1c_ctx = harness.context
    m1c_hash = economic_context_hash(m1c_ctx)

    # M1d authentic context
    methodology_hash, support, retained = session_supporting_artifacts()
    row = schedule_record(
        date(2026, 1, 5),
        "regular",
        methodology_hash,
        support,
        retained,
        suffix=340,
    )
    dataset = session_dataset("scheduled_session", (row,), support)
    m1d_ctx = M1dResolutionContext(
        observation_datasets=(),
        session_datasets=(dataset,),
        availability_policies={},
        retained_evidence=retained,
        supporting_artifacts=support,
    )
    m1d_hash = m1d_context_hash(m1d_ctx)

    # M1b authentic context
    _, m1b_ctx = structural_inputs()

    contexts = ExistingContractContexts(
        m1b_contexts=(m1b_ctx,),
        m1c_context=m1c_ctx,
        m1d_context=m1d_ctx,
    )
    return contexts, m1c_hash, m1d_hash


def _make_all_replay_inputs(
    purpose: ConsumerPurpose,
    profile_hash: SHA256Hash,
    m1c_hash: str | None = None,
    m1d_hash: str | None = None,
) -> tuple[tuple[ReplayInputEntryV1, ...], dict[str, VerifiedArtifactBytes]]:
    entries: list[ReplayInputEntryV1] = []
    artifacts: dict[str, VerifiedArtifactBytes] = {}

    for kind in ReplayInputKind:
        if kind in (
            ReplayInputKind.NATIVE_ARTIFACT,
            ReplayInputKind.GRADING_EVIDENCE,
            ReplayInputKind.METHODOLOGY_OR_SCHEMA,
        ):
            payload = f"raw-bytes-for-{kind.value}".encode()
            ref, vbytes = _make_artifact(payload)
            artifacts[ref.content_hash] = vbytes
            entries.append(
                RawReplayInputEntryV1(
                    kind=kind,
                    artifact_reference=ref,
                    content_hash=ref.content_hash,
                    byte_object_descriptor_hash=content_hash(f"desc-{kind.value}"),
                    media_type="application/octet-stream",
                    schema_descriptor=None,
                    purpose=purpose,
                    profile_hash=profile_hash,
                    component_role=SourceComponentRole.OBSERVATIONS,
                    rights_binding_hash=H[6],
                )
            )
        else:
            if kind == ReplayInputKind.M1C_QUERY_POLICY_CONTEXT_RESULT and m1c_hash:
                orig_id = m1c_hash
            elif kind == ReplayInputKind.M1D_QUERY_POLICY_CONTEXT_RESULT and m1d_hash:
                orig_id = m1d_hash
            else:
                orig_id = f"orig-{kind.value}"

            payload = json.dumps({"kind": kind.value, "identity": orig_id}).encode()
            ref, vbytes = _make_artifact(payload)
            artifacts[ref.content_hash] = vbytes
            entries.append(
                CanonicalReplayInputEntryV1(
                    kind=kind,
                    artifact_reference=ref,
                    content_hash=ref.content_hash,
                    model_type=f"Model{kind.name}",
                    model_version="1",
                    purpose=purpose,
                    profile_hash=profile_hash,
                    component_role=SourceComponentRole.OBSERVATIONS,
                    original_identity=orig_id,
                )
            )
    return tuple(entries), artifacts


def _make_expected_outputs(
    purpose: ConsumerPurpose,
    profile_hash: SHA256Hash,
) -> tuple[ExpectedOutputV1, ...]:
    outputs: list[ExpectedOutputV1] = []
    for kind in ExpectedOutputKind:
        outputs.append(
            ExpectedOutputV1(
                kind=kind,
                purpose=purpose,
                profile_hash=profile_hash,
                canonical_output_hash=content_hash(f"output-{kind.value}"),
                semantic_owner="drift.qualification",
                query_hash=content_hash(f"query-{kind.value}"),
                input_context_hash=content_hash(f"input-ctx-{kind.value}"),
                original_identity=f"expected-out-{kind.value}",
            )
        )
    return tuple(outputs)


def test_provider_release_evidence_validation() -> None:
    ref, _ = _make_artifact(b"test-evidence")
    evidence = ProviderReleaseEvidenceV1(
        component_role=SourceComponentRole.IDENTITY_UNIVERSE,
        provider_release_id="rel-123",
        provider_object_ids=("b-obj", "a-obj"),
        native_state_label="final",
        temporal_boundary=_make_temporal_claim("2026-01-01"),
        availability_evidence_hashes=(H[1], H[0]),
        acquisition_receipt_hash=H[2],
        evidence_references=(ref,),
    )
    assert evidence.provider_object_ids == ("a-obj", "b-obj")
    assert evidence.availability_evidence_hashes == (H[0], H[1])

    with pytest.raises(ValidationError):
        evidence.model_copy(update={"provider_release_id": ""})


def test_replay_input_discriminator_and_invariants() -> None:
    ref, _ = _make_artifact(b"raw-bytes")
    raw = RawReplayInputEntryV1(
        kind=ReplayInputKind.NATIVE_ARTIFACT,
        artifact_reference=ref,
        content_hash=ref.content_hash,
        byte_object_descriptor_hash=H[0],
        media_type="application/json",
        schema_descriptor=None,
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        profile_hash=H[1],
        component_role=SourceComponentRole.OBSERVATIONS,
        rights_binding_hash=H[2],
    )
    assert raw.discriminator == "raw_bytes"

    canonical = CanonicalReplayInputEntryV1(
        kind=ReplayInputKind.M1B_QUERY_CONTEXT_RESULT,
        artifact_reference=ref,
        content_hash=ref.content_hash,
        model_type="StructuralResolutionContext",
        model_version="1",
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        profile_hash=H[1],
        component_role=SourceComponentRole.IDENTITY_UNIVERSE,
        original_identity="orig-1",
    )
    assert canonical.discriminator == "canonical_model"


def test_real_source_snapshot_self_excluding_hash_and_tamper() -> None:
    rel = _make_release_evidence()
    rel_hash = content_hash(rel)
    rule = _make_cutoff_rule(H[0])
    rule_hash = content_hash(rule)
    decision = _make_consistency_decision((rel_hash,), rule_hash)
    purpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT
    profile_hash = H[1]
    inputs, _ = _make_all_replay_inputs(purpose, profile_hash)
    outputs = _make_expected_outputs(purpose, profile_hash)

    pre_snapshot = RealSourceSnapshotV1.model_construct(
        snapshot_id=uuid7(),
        snapshot_version="1",
        created_at=NOW,
        profile_set_hash=H[0],
        profile_hashes=(profile_hash,),
        authorized_profile_hashes=(profile_hash,),
        rights_assessment_hashes=(H[2],),
        receipt_hashes=(H[3],),
        native_artifact_hashes=(inputs[0].content_hash,),
        grading_artifact_hashes=(),
        release_evidence=(rel,),
        consistency_decision=decision,
        cutoff_assertions=("cutoff-1",),
        coverage_assertions=("coverage-1",),
        methodology_schema_hashes=(H[4],),
        adapter_semantic_hashes=(H[5],),
        adapter_source_hashes=(H[6],),
        existing_manifest_hashes=(H[7],),
        validation_decision_hashes=(H[8],),
        validation_bundle_hashes=(H[9],),
        m1a_policy_hashes=(H[10],),
        replay_inputs=inputs,
        expected_outputs=outputs,
        snapshot_hash=H[0],
    )
    computed_hash = real_source_snapshot_hash(pre_snapshot)
    snapshot = pre_snapshot.model_copy(update={"snapshot_hash": computed_hash})
    assert snapshot.snapshot_hash == real_source_snapshot_hash(snapshot)

    # Tampering with snapshot_hash fails validator
    with pytest.raises(ValueError, match="snapshot_hash"):
        bad_dump = snapshot.model_copy(update={"snapshot_hash": H[11]}).model_dump(
            mode="python"
        )
        RealSourceSnapshotV1.model_validate(bad_dump)

    # Mutating semantic fields without updating snapshot_hash fails validation
    with pytest.raises(ValidationError, match="snapshot_hash"):
        snapshot.model_copy(update={"rights_assessment_hashes": (H[12],)})

    with pytest.raises(ValidationError, match="snapshot_hash"):
        snapshot.model_copy(update={"receipt_hashes": (H[13],)})

    with pytest.raises(ValidationError, match="snapshot_hash"):
        mut_rel = _make_release_evidence(release_id="rel-mutated")
        snapshot.model_copy(update={"release_evidence": (mut_rel,)})

    with pytest.raises(ValidationError, match="snapshot_hash"):
        snapshot.model_copy(update={"replay_inputs": inputs[1:]})

    with pytest.raises(ValidationError, match="snapshot_hash"):
        snapshot.model_copy(update={"expected_outputs": outputs[1:]})

    # Recomputing the hash for the mutated preimage yields a distinct hash
    mutated_rights_pre = pre_snapshot.model_construct(rights_assessment_hashes=(H[12],))
    assert real_source_snapshot_hash(mutated_rights_pre) != computed_hash

    mutated_receipts_pre = pre_snapshot.model_construct(receipt_hashes=(H[13],))
    assert real_source_snapshot_hash(mutated_receipts_pre) != computed_hash


def test_real_source_snapshot_step1_semantic_mutations() -> None:
    """Every Task 5 Step 1 semantic mutation must change snapshot identity."""
    rel = _make_release_evidence()
    rel_hash = content_hash(rel)
    rule = _make_cutoff_rule(H[0])
    rule_hash = content_hash(rule)
    decision = _make_consistency_decision((rel_hash,), rule_hash)
    purpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT
    profile_hash = H[1]
    inputs, _ = _make_all_replay_inputs(purpose, profile_hash)
    outputs = _make_expected_outputs(purpose, profile_hash)

    base = RealSourceSnapshotV1.model_construct(
        snapshot_id=uuid7(),
        snapshot_version="1",
        created_at=NOW,
        profile_set_hash=H[0],
        profile_hashes=(profile_hash,),
        authorized_profile_hashes=(profile_hash,),
        rights_assessment_hashes=(H[2],),
        receipt_hashes=(H[3],),
        native_artifact_hashes=(inputs[0].content_hash,),
        grading_artifact_hashes=(),
        release_evidence=(rel,),
        consistency_decision=decision,
        cutoff_assertions=("cutoff-1",),
        coverage_assertions=("coverage-1",),
        methodology_schema_hashes=(H[4],),
        adapter_semantic_hashes=(H[5],),
        adapter_source_hashes=(H[6],),
        existing_manifest_hashes=(H[7],),
        validation_decision_hashes=(H[8],),
        validation_bundle_hashes=(H[9],),
        m1a_policy_hashes=(H[10],),
        replay_inputs=inputs,
        expected_outputs=outputs,
        snapshot_hash=H[0],
    )
    base_hash = real_source_snapshot_hash(base)

    mutations = [
        # Rights assessment mutation
        base.model_construct(rights_assessment_hashes=(H[14],)),
        # Receipt ordering / content mutation
        base.model_construct(receipt_hashes=(H[14], H[3])),
        # Byte layer descriptor mutation in replay inputs
        base.model_construct(
            replay_inputs=(
                inputs[0].model_copy(update={"byte_object_descriptor_hash": H[14]}),
                *inputs[1:],
            )
        ),
        # Release ID mutation
        base.model_construct(
            release_evidence=(_make_release_evidence(release_id="rel-mutated-2"),)
        ),
        # Source-state time mutation
        base.model_construct(created_at=datetime(2027, 1, 1, tzinfo=UTC)),
        # Cutoff rule mutation (via decision)
        base.model_construct(
            consistency_decision=_make_consistency_decision((rel_hash,), H[14])
        ),
        # Coverage assertions mutation
        base.model_construct(coverage_assertions=("coverage-mutated",)),
        # Methodology / schema mutation
        base.model_construct(methodology_schema_hashes=(H[14],)),
        # Adapter semantic mutation
        base.model_construct(adapter_semantic_hashes=(H[14],)),
        # Adapter source mutation
        base.model_construct(adapter_source_hashes=(H[14],)),
        # Validation decision mutation
        base.model_construct(validation_decision_hashes=(H[14],)),
        # Validation bundle mutation
        base.model_construct(validation_bundle_hashes=(H[14],)),
        # M1a policy mutation
        base.model_construct(m1a_policy_hashes=(H[14],)),
        # Expected outputs mutation
        base.model_construct(
            expected_outputs=(
                outputs[0].model_copy(update={"canonical_output_hash": H[14]}),
                *outputs[1:],
            )
        ),
        # Query hash mutation
        base.model_construct(
            expected_outputs=(
                outputs[0].model_copy(update={"query_hash": H[14]}),
                *outputs[1:],
            )
        ),
        # Input context hash mutation
        base.model_construct(
            expected_outputs=(
                outputs[0].model_copy(update={"input_context_hash": H[14]}),
                *outputs[1:],
            )
        ),
    ]

    for mutated in mutations:
        mutated_hash = real_source_snapshot_hash(mutated)
        assert mutated_hash != base_hash, f"Mutation failed to alter hash: {mutated}"


def test_verify_real_source_snapshot_location_neutrality() -> None:
    contexts, m1c_hash, m1d_hash = _make_valid_contexts()
    rel = _make_release_evidence()
    rel_hash = content_hash(rel)
    rule = _make_cutoff_rule(H[0])
    rule_hash = content_hash(rule)
    decision = _make_consistency_decision((rel_hash,), rule_hash)
    purpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT
    profile_hash = H[1]
    inputs, artifacts = _make_all_replay_inputs(
        purpose, profile_hash, m1c_hash=m1c_hash, m1d_hash=m1d_hash
    )
    outputs = _make_expected_outputs(purpose, profile_hash)

    native_hashes = tuple(
        sorted(
            {
                item.content_hash
                for item in inputs
                if item.kind == ReplayInputKind.NATIVE_ARTIFACT
            }
        )
    )

    snapshot_unhashed = RealSourceSnapshotV1.model_construct(
        snapshot_id=uuid7(),
        snapshot_version="1",
        created_at=NOW,
        profile_set_hash=H[0],
        profile_hashes=(profile_hash,),
        authorized_profile_hashes=(profile_hash,),
        rights_assessment_hashes=(H[2],),
        receipt_hashes=(H[3],),
        native_artifact_hashes=native_hashes,
        grading_artifact_hashes=(),
        release_evidence=(rel,),
        consistency_decision=decision,
        cutoff_assertions=("cutoff-1",),
        coverage_assertions=("coverage-1",),
        methodology_schema_hashes=(),
        adapter_semantic_hashes=(),
        adapter_source_hashes=(),
        existing_manifest_hashes=(),
        validation_decision_hashes=(),
        validation_bundle_hashes=(),
        m1a_policy_hashes=(),
        replay_inputs=inputs,
        expected_outputs=outputs,
        snapshot_hash=H[0],
    )
    snapshot = snapshot_unhashed.model_copy(
        update={"snapshot_hash": real_source_snapshot_hash(snapshot_unhashed)}
    )

    # Verifying with matching artifacts succeeds
    verify_real_source_snapshot(snapshot, artifacts, contexts)

    # Relocating artifacts (changing references/paths without changing content
    # bytes) still verifies
    relocated_artifacts = {}
    for chash, vart in artifacts.items():
        relocated_artifacts[chash] = VerifiedArtifactBytes(
            data=vart.data,
            byte_size=vart.byte_size,
            content_hash=chash,
        )
    verify_real_source_snapshot(snapshot, relocated_artifacts, contexts)

    # Non-content URI location is rejected
    bad_ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.OTHER,
        content_hash=inputs[0].content_hash,
        location="/Users/alice/data.parquet",
    )
    with pytest.raises(ValidationError, match="drift\\+sha256://"):
        inputs[0].model_copy(update={"artifact_reference": bad_ref})

    # Missing artifact fails verification
    missing_one = dict(artifacts)
    first_key = next(iter(missing_one))
    del missing_one[first_key]
    with pytest.raises(ValueError, match="missing required artifact bytes"):
        verify_real_source_snapshot(snapshot, missing_one, contexts)

    # Corrupt artifact bytes fail verification
    corrupt_one = dict(artifacts)
    corrupt_one[first_key] = VerifiedArtifactBytes(
        data=b"tampered-bytes",
        byte_size=len(b"tampered-bytes"),
        content_hash=first_key,
    )
    with pytest.raises(ValueError, match="artifact byte hash mismatch"):
        verify_real_source_snapshot(snapshot, corrupt_one, contexts)


def test_verify_real_source_snapshot_context_integrity_and_anti_tamper() -> None:
    contexts, m1c_hash, m1d_hash = _make_valid_contexts()
    rel = _make_release_evidence()
    rel_hash = content_hash(rel)
    rule = _make_cutoff_rule(H[0])
    rule_hash = content_hash(rule)
    decision = _make_consistency_decision((rel_hash,), rule_hash)
    purpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT
    profile_hash = H[1]
    inputs, artifacts = _make_all_replay_inputs(
        purpose, profile_hash, m1c_hash=m1c_hash, m1d_hash=m1d_hash
    )
    outputs = _make_expected_outputs(purpose, profile_hash)

    native_hashes = tuple(
        sorted(
            {
                item.content_hash
                for item in inputs
                if item.kind == ReplayInputKind.NATIVE_ARTIFACT
            }
        )
    )

    snapshot_unhashed = RealSourceSnapshotV1.model_construct(
        snapshot_id=uuid7(),
        snapshot_version="1",
        created_at=NOW,
        profile_set_hash=H[0],
        profile_hashes=(profile_hash,),
        authorized_profile_hashes=(profile_hash,),
        rights_assessment_hashes=(H[2],),
        receipt_hashes=(H[3],),
        native_artifact_hashes=native_hashes,
        grading_artifact_hashes=(),
        release_evidence=(rel,),
        consistency_decision=decision,
        cutoff_assertions=("cutoff-1",),
        coverage_assertions=("coverage-1",),
        methodology_schema_hashes=(),
        adapter_semantic_hashes=(),
        adapter_source_hashes=(),
        existing_manifest_hashes=(),
        validation_decision_hashes=(),
        validation_bundle_hashes=(),
        m1a_policy_hashes=(),
        replay_inputs=inputs,
        expected_outputs=outputs,
        snapshot_hash=H[0],
    )
    snapshot = snapshot_unhashed.model_copy(
        update={"snapshot_hash": real_source_snapshot_hash(snapshot_unhashed)}
    )

    # 1. Dummy M1c context is rejected
    dummy_m1c = ExistingContractContexts(
        m1b_contexts=contexts.m1b_contexts,
        m1c_context=cast(EconomicResolutionContext, object()),
        m1d_context=contexts.m1d_context,
    )
    with pytest.raises(
        ValueError, match="m1c_context must be EconomicResolutionContext"
    ):
        verify_real_source_snapshot(snapshot, artifacts, dummy_m1c)

    # 2. Dummy M1d context is rejected
    dummy_m1d = ExistingContractContexts(
        m1b_contexts=contexts.m1b_contexts,
        m1c_context=contexts.m1c_context,
        m1d_context=cast(M1dResolutionContext, object()),
    )
    with pytest.raises(ValueError, match="m1d_context must be M1dResolutionContext"):
        verify_real_source_snapshot(snapshot, artifacts, dummy_m1d)

    # 3. Dummy M1b context is rejected
    dummy_m1b = ExistingContractContexts(
        m1b_contexts=cast(tuple[StructuralResolutionContext, ...], (object(),)),
        m1c_context=contexts.m1c_context,
        m1d_context=contexts.m1d_context,
    )
    with pytest.raises(
        ValueError, match="m1b_contexts\\[0\\] must be StructuralResolutionContext"
    ):
        verify_real_source_snapshot(snapshot, artifacts, dummy_m1b)

    # 4. Context substitution (tampered hash) is rejected
    from economic_test_support import effect_record

    other_harness = validated_case((effect_record(631),))
    sub_m1c = ExistingContractContexts(
        m1b_contexts=contexts.m1b_contexts,
        m1c_context=other_harness.context,
        m1d_context=contexts.m1d_context,
    )
    with pytest.raises(ValueError, match="m1c context hash mismatch"):
        verify_real_source_snapshot(snapshot, artifacts, sub_m1c)


def _make_sample_snapshot_and_state() -> tuple[
    RealSourceSnapshotV1,
    dict[str, VerifiedArtifactBytes],
    ExistingContractContexts,
    QualificationTargetV1,
    M1ePilotStateV1,
]:
    contexts, m1c_hash, m1d_hash = _make_valid_contexts()
    rel = _make_release_evidence()
    rel_hash = content_hash(rel)
    rule = _make_cutoff_rule(H[0])
    rule_hash = content_hash(rule)
    decision = _make_consistency_decision((rel_hash,), rule_hash)
    purpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT
    profile_hash = H[1]
    inputs, artifacts = _make_all_replay_inputs(
        purpose, profile_hash, m1c_hash=m1c_hash, m1d_hash=m1d_hash
    )
    outputs = _make_expected_outputs(purpose, profile_hash)

    native_hashes = tuple(
        sorted(
            {
                item.content_hash
                for item in inputs
                if item.kind == ReplayInputKind.NATIVE_ARTIFACT
            }
        )
    )

    snapshot_unhashed = RealSourceSnapshotV1.model_construct(
        snapshot_id=uuid7(),
        snapshot_version="1",
        created_at=NOW,
        profile_set_hash=H[0],
        profile_hashes=(profile_hash,),
        authorized_profile_hashes=(profile_hash,),
        rights_assessment_hashes=(H[2],),
        receipt_hashes=(H[3],),
        native_artifact_hashes=native_hashes,
        grading_artifact_hashes=(),
        release_evidence=(rel,),
        consistency_decision=decision,
        cutoff_assertions=("cutoff-1",),
        coverage_assertions=("coverage-1",),
        methodology_schema_hashes=(),
        adapter_semantic_hashes=(),
        adapter_source_hashes=(),
        existing_manifest_hashes=(),
        validation_decision_hashes=(),
        validation_bundle_hashes=(),
        m1a_policy_hashes=(),
        replay_inputs=inputs,
        expected_outputs=outputs,
        snapshot_hash=H[0],
    )
    snapshot = snapshot_unhashed.model_copy(
        update={"snapshot_hash": real_source_snapshot_hash(snapshot_unhashed)}
    )

    target = QualificationTargetV1(
        profile_hash=profile_hash,
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=snapshot.receipt_hashes,
        snapshot_hash=snapshot.snapshot_hash,
        failure_evidence_hashes=(),
    )

    sibling_hash = "f0" + "0" * 62
    state = M1ePilotStateV1(
        profile_set_hash=H[0],
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=profile_hash,
                stage=PilotStage.ACQUIRED,
                reached_stage_artifact_hashes=(H[3],),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=sibling_hash,
                stage=None,
                reached_stage_artifact_hashes=(),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=snapshot.receipt_hashes,
    )

    return snapshot, artifacts, contexts, target, state


def test_lifecycle_transition_snapshot_frozen_advances_stage() -> None:
    snapshot, artifacts, contexts, target, state = _make_sample_snapshot_and_state()
    advanced = transition_snapshot_frozen(state, target, snapshot, artifacts, contexts)
    assert advanced.purpose_states[0].stage is PilotStage.SNAPSHOT_FROZEN
    assert (
        snapshot.snapshot_hash
        in advanced.purpose_states[0].reached_stage_artifact_hashes
    )
    assert (
        content_hash(target) in advanced.purpose_states[0].reached_stage_artifact_hashes
    )


def test_lifecycle_transition_snapshot_frozen_receipt_provenance_enforced() -> None:
    snapshot, artifacts, contexts, target, state = _make_sample_snapshot_and_state()
    # Unacquired receipt in snapshot is rejected
    unacquired_state = state.model_copy(update={"shared_artifact_hashes": ()})
    with pytest.raises(ValueError, match="snapshot receipt hashes were not acquired"):
        transition_snapshot_frozen(
            unacquired_state, target, snapshot, artifacts, contexts
        )

    # State purpose without the receipt reached is rejected
    tampered_purpose_state = state.model_copy(
        update={
            "purpose_states": (
                state.purpose_states[0].model_copy(
                    update={"reached_stage_artifact_hashes": (H[15],)}
                ),
                state.purpose_states[1],
            )
        }
    )
    with pytest.raises(ValueError, match="does not contain the acquired receipt"):
        transition_snapshot_frozen(
            tampered_purpose_state, target, snapshot, artifacts, contexts
        )


def test_lifecycle_transition_snapshot_frozen_requires_acquired_stage() -> None:
    snapshot, artifacts, contexts, target, state = _make_sample_snapshot_and_state()
    unready_state = state.model_copy(
        update={
            "purpose_states": (
                state.purpose_states[0].model_copy(
                    update={"stage": PilotStage.ACQUISITION_AUTHORIZED}
                ),
                state.purpose_states[1],
            )
        }
    )
    with pytest.raises(ValueError, match="ACQUIRED"):
        transition_snapshot_frozen(unready_state, target, snapshot, artifacts, contexts)


def test_lifecycle_transition_snapshot_frozen_requires_snapshot_bound_target() -> None:
    snapshot, artifacts, contexts, target, state = _make_sample_snapshot_and_state()
    invalid_target = QualificationTargetV1(
        profile_hash=target.profile_hash,
        acquisition_state=AcquisitionState.ACQUIRED_UNSNAPSHOTTED,
        receipt_hashes=snapshot.receipt_hashes,
        snapshot_hash=None,
        failure_evidence_hashes=(H[4],),
    )
    with pytest.raises(ValueError, match="SNAPSHOT_BOUND"):
        transition_snapshot_frozen(state, invalid_target, snapshot, artifacts, contexts)


def test_lifecycle_target_with_failure_evidence_rejected() -> None:
    # Target in SNAPSHOT_BOUND cannot carry failure_evidence_hashes
    with pytest.raises(ValidationError, match="no failure evidence"):
        QualificationTargetV1(
            profile_hash=H[1],
            acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
            receipt_hashes=(H[3],),
            snapshot_hash=H[0],
            failure_evidence_hashes=(H[4],),
        )


def test_lifecycle_transition_snapshot_frozen_hash_mismatch_fails() -> None:
    snapshot, artifacts, contexts, target, state = _make_sample_snapshot_and_state()
    mismatched_target = target.model_copy(update={"snapshot_hash": H[15]})
    with pytest.raises(ValueError, match="target snapshot hash does not match"):
        transition_snapshot_frozen(
            state, mismatched_target, snapshot, artifacts, contexts
        )

    mismatched_state = state.model_copy(update={"profile_set_hash": "9" * 64})
    with pytest.raises(ValueError, match="snapshot profile set does not match"):
        transition_snapshot_frozen(
            mismatched_state, target, snapshot, artifacts, contexts
        )
