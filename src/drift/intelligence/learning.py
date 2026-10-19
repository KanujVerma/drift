"""Bounded intelligence learning state transitions and matured feedback runtime.

Implements Slice K4 advance_learning() under DP-R5 and DP-R8, enforcing
causal maturity (T01), arm isolation (T04), holdout isolation (T05), and
evidence completeness (T12).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    ProfileLiteral,
)
from drift.serialization.canonical import content_hash


class TrialFeedbackRecord(ImmutableModel):
    """Authoritative outcome and metric attribution for an evaluation trial."""

    trial_id: str
    arm_id: str
    decision_cutoff: datetime
    matured_at: datetime
    candidate_id: str
    status: Literal["completed", "failed", "rejected"]
    pnl: str | None = None
    metrics: dict[str, str] = {}
    is_complete: bool = True
    is_holdout: bool = False


class LearningSnapshot(ImmutableModel):
    """Immutable point-in-time learning memory state for an adaptive arm."""

    profile: ProfileLiteral = "drift-research/1-draft"
    kind: Literal["learning_snapshot"] = "learning_snapshot"
    snapshot_id: str
    arm_id: str
    version: int
    cutoff: datetime
    previous_snapshot_ref: ArtifactReference | None = None
    matured_trials: tuple[TrialFeedbackRecord, ...] = ()
    state_hash: str


def advance_learning(
    *,
    previous_snapshot: LearningSnapshot | None,
    feedback_records: Sequence[TrialFeedbackRecord],
    cutoff: datetime,
    arm_id: str,
    method_ref: ArtifactReference,
    snapshot_id: str | None = None,
) -> LearningSnapshot:
    """Advance arm learning state by appending eligible matured trial feedback.

    Guarantees:
    - Immutable deterministic transition chaining previous snapshot ref.
    - Causal maturity: only feedback with matured_at <= cutoff is admitted (T01).
    - Holdout isolation: holdout feedback unconditionally rejected (T05).
    - Arm isolation: feedback for other arms is strictly excluded (T04).
    - Completeness check: incomplete feedback without metrics is rejected (T12).
    - Complete losing trials (negative PnL) are admitted without bias (T12).
    """
    actual_snapshot_id = snapshot_id or str(uuid4())
    cutoff_utc = cutoff.astimezone(UTC) if cutoff.tzinfo else cutoff.replace(tzinfo=UTC)

    # Start with trials from prior snapshot
    existing_trials_by_id: dict[str, TrialFeedbackRecord] = {}
    if previous_snapshot is not None:
        if previous_snapshot.arm_id != arm_id:
            raise ValueError(
                f"CROSS_ARM_LEAKAGE: snapshot arm {previous_snapshot.arm_id} "
                f"does not match target arm {arm_id}"
            )
        for t in previous_snapshot.matured_trials:
            existing_trials_by_id[t.trial_id] = t

    # Ingest and validate new feedback records
    for record in feedback_records:
        # 1. Sealed holdout isolation (T05)
        if record.is_holdout or record.trial_id.startswith("holdout:"):
            raise ValueError(
                "HOLDOUT_ACCESS_VIOLATION: sealed holdout outcome cannot enter "
                "learning memory"
            )

        # 2. Arm isolation: ignore feedback for other arms (T04)
        if record.arm_id != arm_id:
            continue

        # 3. Causal maturity check (T01, T02)
        rec_matured_utc = (
            record.matured_at.astimezone(UTC)
            if record.matured_at.tzinfo
            else record.matured_at.replace(tzinfo=UTC)
        )
        if rec_matured_utc > cutoff_utc:
            # Future feedback not yet matured
            continue

        # 4. Evidence completeness check (T12)
        if record.status == "completed":
            if not record.is_complete or not record.metrics:
                raise ValueError(
                    "REJECTED_INCOMPLETE_EVIDENCE: trial outcome lacks "
                    "mandatory metrics"
                )
        else:
            # Non-completed outcomes cannot falsify hypotheses or enter learning
            continue

        existing_trials_by_id[record.trial_id] = record

    # Deterministic sorting by (matured_at, trial_id)
    sorted_trials = sorted(
        existing_trials_by_id.values(),
        key=lambda r: (r.matured_at, r.trial_id),
    )
    trials_tuple = tuple(sorted_trials)

    # Compute deterministic state hash
    serialized_trials = [t.model_dump(mode="python") for t in trials_tuple]
    computed_hash = content_hash(serialized_trials)

    if previous_snapshot is None:
        version = 1
        prev_ref = None
    else:
        version = previous_snapshot.version + 1
        prev_ref = ArtifactReference(
            id=previous_snapshot.snapshot_id,
            version=f"v{previous_snapshot.version}",
            sha256=previous_snapshot.state_hash,
        )

    return LearningSnapshot(
        profile="drift-research/1-draft",
        kind="learning_snapshot",
        snapshot_id=actual_snapshot_id,
        arm_id=arm_id,
        version=version,
        cutoff=cutoff_utc,
        previous_snapshot_ref=prev_ref,
        matured_trials=trials_tuple,
        state_hash=computed_hash,
    )
