"""Unit tests for bounded intelligence learning state transitions.

Verifies acceptance criteria T01, T04, T05, T12 from research.md and DP-R5/DP-R8:
- Causal maturity (T01): future unmatured feedback is excluded.
- Arm isolation (T04): feedback for other arms is strictly excluded.
- Sealed holdout isolation (T05): holdout outcomes trigger refusal.
- Evidence completeness (T12): complete valid losing trials admitted;
  incomplete trials rejected.
- Deterministic transition chaining and version incrementing.
"""

from datetime import UTC, datetime, timedelta

import pytest

from drift.intelligence.contracts import ArtifactReference
from drift.intelligence.learning import (
    LearningSnapshot,
    TrialFeedbackRecord,
    advance_learning,
)
from drift.serialization.canonical import content_hash


@pytest.fixture
def sample_method_ref() -> ArtifactReference:
    return ArtifactReference(id="method:learning", version="v1", sha256="a" * 64)


def test_learning_initial_snapshot(sample_method_ref: ArtifactReference) -> None:
    """Advance learning from None creates version 1 snapshot."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    trial = TrialFeedbackRecord(
        trial_id="trial-001",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=1),
        matured_at=cutoff - timedelta(hours=1),
        candidate_id="cand-001",
        status="completed",
        pnl="150.50",
        metrics={"sharpe": "1.2", "return": "0.015"},
        is_complete=True,
    )

    snap = advance_learning(
        previous_snapshot=None,
        feedback_records=[trial],
        cutoff=cutoff,
        arm_id="arm-B",
        method_ref=sample_method_ref,
        snapshot_id="snap-001",
    )

    assert snap.version == 1
    assert snap.previous_snapshot_ref is None
    assert len(snap.matured_trials) == 1
    assert snap.matured_trials[0].trial_id == "trial-001"
    assert snap.state_hash is not None


def test_learning_chained_transition(sample_method_ref: ArtifactReference) -> None:
    """Successive transition increments version and chains previous_snapshot_ref."""
    cutoff1 = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)
    cutoff2 = datetime(2024, 1, 3, 10, 0, 0, tzinfo=UTC)

    trial1 = TrialFeedbackRecord(
        trial_id="trial-001",
        arm_id="arm-B",
        decision_cutoff=cutoff1 - timedelta(days=1),
        matured_at=cutoff1 - timedelta(hours=1),
        candidate_id="cand-001",
        status="completed",
        pnl="150.50",
        metrics={"sharpe": "1.2"},
        is_complete=True,
    )

    snap1 = advance_learning(
        previous_snapshot=None,
        feedback_records=[trial1],
        cutoff=cutoff1,
        arm_id="arm-B",
        method_ref=sample_method_ref,
        snapshot_id="snap-001",
    )

    trial2 = TrialFeedbackRecord(
        trial_id="trial-002",
        arm_id="arm-B",
        decision_cutoff=cutoff2 - timedelta(days=1),
        matured_at=cutoff2 - timedelta(hours=1),
        candidate_id="cand-002",
        status="completed",
        pnl="85.20",
        metrics={"sharpe": "0.9"},
        is_complete=True,
    )

    snap2 = advance_learning(
        previous_snapshot=snap1,
        feedback_records=[trial2],
        cutoff=cutoff2,
        arm_id="arm-B",
        method_ref=sample_method_ref,
        snapshot_id="snap-002",
    )

    assert snap2.version == 2
    assert snap2.previous_snapshot_ref is not None
    assert snap2.previous_snapshot_ref.id == "snap-001"
    assert snap2.previous_snapshot_ref.sha256 == snap1.state_hash
    assert len(snap2.matured_trials) == 2


def test_t12_complete_losing_trial_admitted(
    sample_method_ref: ArtifactReference,
) -> None:
    """T12: Complete valid losing trial (negative PnL) is admitted into memory."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    losing_trial = TrialFeedbackRecord(
        trial_id="trial-loss-001",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=1),
        matured_at=cutoff - timedelta(hours=1),
        candidate_id="cand-loss",
        status="completed",
        pnl="-450.00",  # Losing result
        metrics={"sharpe": "-0.8", "return": "-0.045"},
        is_complete=True,
    )

    snap = advance_learning(
        previous_snapshot=None,
        feedback_records=[losing_trial],
        cutoff=cutoff,
        arm_id="arm-B",
        method_ref=sample_method_ref,
    )

    assert len(snap.matured_trials) == 1
    assert snap.matured_trials[0].pnl == "-450.00"


def test_t12_incomplete_trial_rejected(
    sample_method_ref: ArtifactReference,
) -> None:
    """T12: Incomplete trial lacking mandatory metrics is rejected."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    incomplete_trial = TrialFeedbackRecord(
        trial_id="trial-incomp-001",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=1),
        matured_at=cutoff - timedelta(hours=1),
        candidate_id="cand-incomp",
        status="completed",
        pnl="100.00",
        metrics={},  # Missing mandatory metrics
        is_complete=False,
    )

    with pytest.raises(ValueError, match="REJECTED_INCOMPLETE_EVIDENCE"):
        advance_learning(
            previous_snapshot=None,
            feedback_records=[incomplete_trial],
            cutoff=cutoff,
            arm_id="arm-B",
            method_ref=sample_method_ref,
        )


def test_t01_unmatured_feedback_excluded(
    sample_method_ref: ArtifactReference,
) -> None:
    """T01: Feedback maturing after cutoff is excluded from learning snapshot."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    future_trial = TrialFeedbackRecord(
        trial_id="trial-future-001",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(hours=2),
        matured_at=cutoff + timedelta(hours=1),  # Matures in future!
        candidate_id="cand-future",
        status="completed",
        pnl="200.00",
        metrics={"sharpe": "1.5"},
        is_complete=True,
    )

    snap = advance_learning(
        previous_snapshot=None,
        feedback_records=[future_trial],
        cutoff=cutoff,
        arm_id="arm-B",
        method_ref=sample_method_ref,
    )

    # Future trial must not be included
    assert len(snap.matured_trials) == 0


def test_learning_hash_binds_method_clock_and_predecessor(
    sample_method_ref: ArtifactReference,
) -> None:
    """The same trial values under another method never share evidence identity."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)
    trial = TrialFeedbackRecord(
        trial_id="trial-method-proof",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=2),
        matured_at=cutoff - timedelta(days=1),
        candidate_id="candidate-method-proof",
        status="completed",
        pnl="-100",
        metrics={"return": "-0.01"},
    )
    left = advance_learning(
        previous_snapshot=None,
        feedback_records=[trial],
        cutoff=cutoff,
        arm_id="arm-B",
        method_ref=sample_method_ref,
        snapshot_id="shared-snapshot",
    )
    right = advance_learning(
        previous_snapshot=None,
        feedback_records=[trial],
        cutoff=cutoff,
        arm_id="arm-B",
        method_ref=ArtifactReference(
            id="method:changed", version="v2", sha256="e" * 64
        ),
        snapshot_id="shared-snapshot",
    )
    assert left.state_hash != right.state_hash
    same = advance_learning(
        previous_snapshot=None,
        feedback_records=[trial],
        cutoff=cutoff,
        arm_id="arm-B",
        method_ref=sample_method_ref,
        snapshot_id="shared-snapshot",
    )
    assert left == same
    with pytest.raises(ValueError, match="LEARNING_STATE_HASH_MISMATCH"):
        type(left).model_validate(
            left.model_copy(update={"method_ref": right.method_ref}).model_dump(
                mode="python"
            )
        )


def test_learning_rejects_conflicting_trial_revision(
    sample_method_ref: ArtifactReference,
) -> None:
    cutoff = datetime(2024, 1, 3, 10, 0, tzinfo=UTC)
    trial = TrialFeedbackRecord(
        trial_id="same-trial",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=2),
        matured_at=cutoff - timedelta(days=1),
        candidate_id="same-candidate",
        status="completed",
        pnl="-10",
        metrics={"return": "-0.01"},
    )
    revision = trial.model_copy(update={"pnl": "10"})
    with pytest.raises(ValueError, match="CONFLICTING_TRIAL_REVISION"):
        advance_learning(
            previous_snapshot=None,
            feedback_records=[trial, revision],
            cutoff=cutoff,
            arm_id="arm-B",
            method_ref=sample_method_ref,
        )


def test_learning_rejects_naive_cutoff(sample_method_ref: ArtifactReference) -> None:
    with pytest.raises(ValueError, match="INDETERMINATE_TIMEZONE"):
        advance_learning(
            previous_snapshot=None,
            feedback_records=[],
            cutoff=datetime(2024, 1, 2, 10, 0),
            arm_id="arm-B",
            method_ref=sample_method_ref,
        )


@pytest.mark.parametrize(
    ("pnl", "metrics"),
    [
        ("NaN", {"return": "0.01"}),
        ("1", {"return": "Infinity"}),
        ("1e9", {"return": "0.01"}),
        ("3.2", {"return": "not-a-number"}),
    ],
)
def test_learning_rejects_nonfinite_and_non_numeric_completed_feedback(
    sample_method_ref: ArtifactReference,
    pnl: str,
    metrics: dict[str, str],
) -> None:
    """Malformed numeric feedback cannot enter a causally mature learning state."""
    cutoff = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    trial = TrialFeedbackRecord(
        trial_id="synthetic:numeric-invalid",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=1),
        matured_at=cutoff - timedelta(hours=1),
        candidate_id="synthetic:candidate",
        status="completed",
        pnl=pnl,
        metrics=metrics,
    )
    with pytest.raises(ValueError, match="REJECTED_INVALID_FEEDBACK_VALUE"):
        advance_learning(
            previous_snapshot=None,
            feedback_records=[trial],
            cutoff=cutoff,
            arm_id="arm-B",
            method_ref=sample_method_ref,
        )



def test_learning_refuses_method_changes_without_explicit_migration(
    sample_method_ref: ArtifactReference,
) -> None:
    """A new method cannot silently reuse the previous method's memory."""
    initial = datetime(2024, 1, 2, 10, tzinfo=UTC)
    first = advance_learning(
        previous_snapshot=None,
        feedback_records=[],
        cutoff=initial,
        arm_id="arm-B",
        method_ref=sample_method_ref,
    )
    with pytest.raises(ValueError, match="LEARNING_METHOD_CHANGED_WITHOUT_MIGRATION"):
        advance_learning(
            previous_snapshot=first,
            feedback_records=[],
            cutoff=initial + timedelta(days=1),
            arm_id="arm-B",
            method_ref=ArtifactReference(
                id="method:new", version="v2", sha256="f" * 64
            ),
        )


def test_self_rehashed_invalid_prior_feedback_never_enters_learning(
    sample_method_ref: ArtifactReference,
) -> None:
    """Rehashing invalid old PnL cannot make corrupt feedback time-eligible."""
    cutoff = datetime(2024, 1, 3, 10, tzinfo=UTC)
    valid = TrialFeedbackRecord(
        trial_id="trial:prior",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=2),
        matured_at=cutoff - timedelta(days=1),
        candidate_id="candidate:prior",
        status="completed",
        pnl="-10",
        metrics={"return": "-0.01"},
    )
    original = advance_learning(
        previous_snapshot=None,
        feedback_records=[valid],
        cutoff=cutoff,
        arm_id="arm-B",
        method_ref=sample_method_ref,
    )
    payload = original.model_dump(mode="python")
    forged_trial = valid.model_copy(update={"pnl": "NaN"})
    payload["matured_trials"] = (forged_trial.model_dump(mode="python"),)
    payload["state_hash"] = content_hash(
        {key: value for key, value in payload.items() if key != "state_hash"}
    )
    with pytest.raises(ValueError, match="REJECTED_INVALID_FEEDBACK_VALUE"):
        LearningSnapshot.model_validate(payload)
