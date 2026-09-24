"""Real source snapshot fixtures for M1d replay provenance binding.

Lives outside the test modules that use it because both
``test_replay_provenance`` and ``test_evaluator_bundles`` need a genuine
``RealSourceSnapshotV1`` now that the promotion gate re-audits the containment
witness, and ``test_replay_provenance`` already imports clock helpers from
``test_evaluator_bundles``. Duplicating the builder, or importing it back the
other way, would either drift apart or cycle.
"""

from datetime import UTC, datetime
from functools import cache
from uuid import UUID

from observation_test_support import uid
from test_evaluator_admission_gatekeeper import make_test_fixture

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.qualification import ConsumerPurpose, qualification_profile_hash
from drift.domain.replay_provenance import context_supplied_artifact_hashes
from drift.domain.source_snapshots import (
    CanonicalReplayInputEntryV1,
    ConsistencyStatus,
    CrossComponentConsistencyDecisionV1,
    RealSourceSnapshotV1,
    ReplayInputEntryV1,
    ReplayInputKind,
    SourceComponentRole,
    cross_component_consistency_decision_hash,
    real_source_snapshot_hash,
)
from drift.evaluator.bundles import derive_replay_context_identity
from drift.markets.observation_validation import M1dResolutionContext
from drift.serialization.canonical import content_hash

H = {c: c * 64 for c in "0123456789abcdef"}
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
SNAPSHOT_ID = UUID("019c0000-0000-7000-8000-000000000001")
DECISION_ID = UUID("019c0000-0000-7000-8000-000000000002")


@cache
def admission_profile_hashes() -> tuple[str, str, str]:
    """The profile set, decision profile, and audit profile the admission binds.

    The promotion gate requires the snapshot to belong to the admission's M1e
    profile set, to authorize both of its profiles, and to attest decision
    evidence under the decision profile (issue 80), so a snapshot fixture that
    invents its own profile identities could never reach the gate.
    """
    fixture = make_test_fixture()
    return (
        content_hash(fixture["profile_set"]),
        qualification_profile_hash(fixture["decision_profile"]),
        qualification_profile_hash(fixture["audit_profile"]),
    )


def _replay_entry(digest: str, index: int) -> CanonicalReplayInputEntryV1:
    reference = ArtifactReference(
        artifact_id=uid(index),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )
    return CanonicalReplayInputEntryV1(
        kind=ReplayInputKind.M1D_QUERY_POLICY_CONTEXT_RESULT,
        artifact_reference=reference,
        content_hash=digest,
        model_type="ReplayContextArtifact",
        model_version="1",
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        profile_hash=admission_profile_hashes()[1],
        component_role=SourceComponentRole.OBSERVATIONS,
        original_identity=digest,
    )


def snapshot_over(
    digests: tuple[str, ...],
    *,
    purpose: ConsumerPurpose | None = None,
    profile_hash: str | None = None,
    profile_set_hash: str | None = None,
    authorized_profile_hashes: tuple[str, ...] | None = None,
) -> RealSourceSnapshotV1:
    """Build a real snapshot that attests exactly the given artifact hashes.

    By default every entry attests its artifact as historical decision input
    under the admission's decision profile, and the snapshot belongs to the
    admission's profile set and authorizes both of its profiles. Each keyword
    overrides one of those bindings, so a test can break exactly one of them.
    """
    set_hash, decision_hash, audit_hash = admission_profile_hashes()
    decision_draft = CrossComponentConsistencyDecisionV1.model_construct(
        schema_version="1",
        component_release_hashes=(),
        coordinated_rule_hash=H["1"],
        result=ConsistencyStatus.PASS,
        conflicts_and_gaps=(),
        decision_policy_hash=H["2"],
        decision_id=DECISION_ID,
        decided_at=NOW,
        decision_hash=H["0"],
    )
    decision = decision_draft.model_copy(
        update={
            "decision_hash": cross_component_consistency_decision_hash(decision_draft)
        }
    )
    entries: tuple[ReplayInputEntryV1, ...] = tuple(
        _replay_entry(digest, index)
        for index, digest in enumerate(sorted(set(digests)))
    )
    overrides: dict[str, object] = {}
    if purpose is not None:
        overrides["purpose"] = purpose
    if profile_hash is not None:
        overrides["profile_hash"] = profile_hash
    if overrides:
        entries = tuple(entry.model_copy(update=overrides) for entry in entries)
    authorized = (
        (decision_hash, audit_hash)
        if authorized_profile_hashes is None
        else authorized_profile_hashes
    )
    draft = RealSourceSnapshotV1.model_construct(
        schema_version="1",
        snapshot_id=SNAPSHOT_ID,
        snapshot_version="1",
        created_at=NOW,
        profile_set_hash=set_hash if profile_set_hash is None else profile_set_hash,
        profile_hashes=tuple(sorted({decision_hash, audit_hash, *authorized})),
        authorized_profile_hashes=tuple(sorted(authorized)),
        rights_assessment_hashes=(H["4"],),
        receipt_hashes=(H["5"],),
        native_artifact_hashes=(),
        grading_artifact_hashes=(),
        release_evidence=(),
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
        replay_inputs=entries,
        expected_outputs=(),
        snapshot_hash=H["0"],
    )
    return draft.model_copy(update={"snapshot_hash": real_source_snapshot_hash(draft)})


def qualified_snapshot(context: M1dResolutionContext) -> RealSourceSnapshotV1:
    """Build the snapshot that genuinely attests every artifact a context supplies."""
    identity = derive_replay_context_identity(context)
    return snapshot_over(context_supplied_artifact_hashes(identity))
