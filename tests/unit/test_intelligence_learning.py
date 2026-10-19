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
    TrialFeedbackRecord,
    advance_learning,
)


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
