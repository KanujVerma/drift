"""Unit tests for cross-component consistency evaluation and replay closure."""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid7

import pytest

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    TemporalBoundaryClaimV1,
)
from drift.domain.qualification import ConsumerPurpose
from drift.domain.source_snapshots import (
    CanonicalReplayInputEntryV1,
    ConsistencyStatus,
    CoordinatedCutoffRuleV1,
    ExpectedOutputKind,
    ExpectedOutputV1,
    ProviderReleaseEvidenceV1,
    RawReplayInputEntryV1,
    RealSourceSnapshotV1,
    ReplayInputEntryV1,
    ReplayInputKind,
    SourceComponentRole,
    real_source_snapshot_hash,
)
from drift.domain.temporal import SourcePrecision
from drift.markets.economic_validation import EconomicResolutionContext
from drift.markets.observation_validation import M1dResolutionContext
from drift.qualification.snapshots import (
    ExistingContractContexts,
    evaluate_cross_component_consistency,
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


def _make_temporal_claim(
    iso_date: str, shape: BoundaryShape = BoundaryShape.EXACT
) -> TemporalBoundaryClaimV1:
    if shape is BoundaryShape.UNKNOWN:
        return TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.UNKNOWN,
            lower_bound=None,
            upper_bound=None,
            source_precision=SourcePrecision.UNKNOWN,
            source_time_label=None,
            source_timezone=None,
            evidence_reference=None,
        )
    ref, _ = _make_artifact(b"temporal-evidence")
    instant = datetime.fromisoformat(f"{iso_date}T00:00:00Z")
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=shape,
        lower_bound=instant,
        upper_bound=instant,
        source_precision=SourcePrecision.SECOND,
        source_time_label=f"{iso_date}T00:00:00Z",
        source_timezone=None,
        evidence_reference=ref,
    )


def _make_release_evidence(
    role: SourceComponentRole,
    iso_date: str,
    shape: BoundaryShape = BoundaryShape.EXACT,
) -> ProviderReleaseEvidenceV1:
    ref, _ = _make_artifact(f"evidence-{role.value}".encode())
    return ProviderReleaseEvidenceV1(
        component_role=role,
        provider_release_id=f"rel-{role.value}",
        provider_object_ids=(f"obj-{role.value}",),
        native_state_label="final",
        temporal_boundary=_make_temporal_claim(iso_date, shape=shape),
        availability_evidence_hashes=(H[1],),
        acquisition_receipt_hash=H[2],
        evidence_references=(ref,),
    )


def _make_cutoff_rule() -> CoordinatedCutoffRuleV1:
    ref, _ = _make_artifact(b"cutoff-rule-evidence")
    return CoordinatedCutoffRuleV1(
        profile_set_hash=H[0],
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


def test_cross_component_consistency_coordinated_vintages_pass() -> None:
    rule = _make_cutoff_rule()
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.OBSERVATIONS, "2026-01-01"),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])
    assert decision.result is ConsistencyStatus.PASS
    assert not decision.conflicts_and_gaps
    assert decision.coordinated_rule_hash == content_hash(rule)


def test_cross_component_consistency_uncoordinated_vintages_fail() -> None:
    rule = _make_cutoff_rule()
    # Observations from 2026-06-01 with universe from 2026-01-01 violates cutoff
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.OBSERVATIONS, "2026-06-01"),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])
    assert decision.result is not ConsistencyStatus.PASS
    assert decision.result in (ConsistencyStatus.FAIL, ConsistencyStatus.PARTIAL)
    assert len(decision.conflicts_and_gaps) > 0


def test_cross_component_consistency_unknown_boundary_unknown() -> None:
    rule = _make_cutoff_rule()
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
        _make_release_evidence(
            SourceComponentRole.OBSERVATIONS, "2026-01-01", shape=BoundaryShape.UNKNOWN
        ),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])
    assert decision.result is ConsistencyStatus.UNKNOWN
    assert len(decision.conflicts_and_gaps) > 0


def test_cross_component_consistency_missing_component_role_returns_fail() -> None:
    rule = _make_cutoff_rule()
    # Missing OBSERVATIONS role declared in rule
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])
    assert decision.result is ConsistencyStatus.FAIL
    assert any(
        SourceComponentRole.OBSERVATIONS.value in gap
        for gap in decision.conflicts_and_gaps
    )


@pytest.mark.parametrize("omitted_kind", list(ReplayInputKind))
def test_replay_input_closure_rejects_missing_families(
    omitted_kind: ReplayInputKind,
) -> None:
    purpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT
    profile_hash = H[1]

    entries: list[ReplayInputEntryV1] = []
    artifacts: dict[str, VerifiedArtifactBytes] = {}

    for kind in ReplayInputKind:
        if kind is omitted_kind:
            continue
        payload = f"payload-{kind.value}".encode()
        ref, vbytes = _make_artifact(payload)
        artifacts[ref.content_hash] = vbytes

        if kind in (
            ReplayInputKind.NATIVE_ARTIFACT,
            ReplayInputKind.GRADING_EVIDENCE,
            ReplayInputKind.METHODOLOGY_OR_SCHEMA,
        ):
            payload = f"payload-{kind.value}".encode()
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
            import json

            payload = json.dumps(
                {"kind": kind.value, "identity": f"orig-{kind.value}"}
            ).encode()
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
                    original_identity=f"orig-{kind.value}",
                )
            )

    rule = _make_cutoff_rule()
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.OBSERVATIONS, "2026-01-01"),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])

    outputs = (
        ExpectedOutputV1(
            kind=ExpectedOutputKind.SELECTED_SOURCE_RECORD,
            purpose=purpose,
            profile_hash=profile_hash,
            canonical_output_hash=H[7],
            semantic_owner="drift.qualification",
            query_hash=H[8],
            input_context_hash=H[9],
            original_identity="expected-out-1",
        ),
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
        native_artifact_hashes=(),
        grading_artifact_hashes=(),
        release_evidence=releases,
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
        replay_inputs=tuple(entries),
        expected_outputs=outputs,
        snapshot_hash=H[0],
    )
    snapshot = snapshot_unhashed.model_copy(
        update={"snapshot_hash": real_source_snapshot_hash(snapshot_unhashed)}
    )

    contexts = ExistingContractContexts(
        m1b_contexts=(),
        m1c_context=cast(EconomicResolutionContext, object()),
        m1d_context=cast(M1dResolutionContext, object()),
    )

    with pytest.raises(ValueError, match="incomplete replay input closure"):
        verify_real_source_snapshot(snapshot, artifacts, contexts)


def test_cross_component_consistency_malformed_cutoff_string_fails() -> None:
    ref, _ = _make_artifact(b"cutoff-rule-evidence")
    rule = CoordinatedCutoffRuleV1(
        profile_set_hash=H[0],
        per_component_cutoff_rules={
            SourceComponentRole.IDENTITY_UNIVERSE: "invalid-not-a-date",
            SourceComponentRole.ACTION_TERMS: "2026-01-01T00:00:00Z",
            SourceComponentRole.OBSERVATIONS: "2026-01-01T00:00:00Z",
        },
        revision_horizon="P30D",
        ordering_rule="arrival_time_then_sequence",
        semantic_hash=H[3],
        evidence_references=(ref,),
    )
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.OBSERVATIONS, "2026-01-01"),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])
    assert decision.result is ConsistencyStatus.FAIL
    assert any("malformed cutoff" in g for g in decision.conflicts_and_gaps)


def test_cross_component_consistency_undeclared_role_in_release_evidence_fails() -> (
    None
):
    rule = _make_cutoff_rule()
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.OBSERVATIONS, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.SETTLEMENT_OUTCOMES, "2026-01-01"),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])
    assert decision.result is ConsistencyStatus.FAIL
    assert any("undeclared component role" in g for g in decision.conflicts_and_gaps)


def test_cross_component_consistency_empty_rules_or_releases_fails() -> None:
    ref, _ = _make_artifact(b"cutoff-rule-evidence")
    empty_rule = CoordinatedCutoffRuleV1(
        profile_set_hash=H[0],
        per_component_cutoff_rules={},
        revision_horizon="P30D",
        ordering_rule="arrival_time_then_sequence",
        semantic_hash=H[3],
        evidence_references=(ref,),
    )
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
    )
    decision = evaluate_cross_component_consistency(
        empty_rule, releases, policy_hash=H[4]
    )
    assert decision.result is ConsistencyStatus.FAIL

    valid_rule = _make_cutoff_rule()
    empty_decision = evaluate_cross_component_consistency(
        valid_rule, (), policy_hash=H[4]
    )
    assert empty_decision.result is ConsistencyStatus.FAIL


def test_cross_component_consistency_decision_hash_tamper_rejected() -> None:
    from drift.domain.source_snapshots import cross_component_consistency_decision_hash

    rule = _make_cutoff_rule()
    releases = (
        _make_release_evidence(SourceComponentRole.IDENTITY_UNIVERSE, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.ACTION_TERMS, "2026-01-01"),
        _make_release_evidence(SourceComponentRole.OBSERVATIONS, "2026-01-01"),
    )
    decision = evaluate_cross_component_consistency(rule, releases, policy_hash=H[4])
    assert decision.decision_hash == cross_component_consistency_decision_hash(decision)

    # Mutating semantic field or tampering decision_hash fails validation
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="decision_hash"):
        decision.model_copy(update={"result": ConsistencyStatus.FAIL})

    with pytest.raises(ValidationError, match="decision_hash"):
        decision.model_copy(update={"decision_hash": "f" * 64})
