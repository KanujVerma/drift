"""Adversarial tests for causal boundaries, cross-arm memory isolation,
and holdout sealing.

Verifies strict security and causal guarantees from research.md and DP-R5/DP-R8:
- T01 / T02: Lookahead and post-cutoff causality attacks fail closed.
- T04: Cross-arm memory leakage attacks fail closed.
- T05: Sealed holdout contamination attacks fail closed.
- Order perturbation invariance: input ordering does not alter canonical record hash.
"""

from datetime import UTC, datetime, timedelta

import pytest

from drift.intelligence.context_builder import CandidateInput, build_context
from drift.intelligence.contracts import ArtifactReference, Scope
from drift.intelligence.learning import (
    TrialFeedbackRecord,
    advance_learning,
)


@pytest.fixture
def sample_scope_b() -> Scope:
    return Scope(
        experiment_id="01900000-0000-7000-8000-000000000001",
        arm_id="fixture:B",
        account_id="01900000-0000-7000-8000-000000000011",
        campaign_ref=ArtifactReference(
            id="fixture:campaign", version="v1", sha256="c" * 64
        ),
    )


@pytest.fixture
def sample_refs() -> dict[str, ArtifactReference]:
    return {
        "portfolio_ref": ArtifactReference(
            id="fixture:portfolio", version="v1", sha256="1" * 64
        ),
        "mandate_ref": ArtifactReference(
            id="fixture:mandate", version="v1", sha256="2" * 64
        ),
        "universe_ref": ArtifactReference(
            id="fixture:universe", version="v1", sha256="3" * 64
        ),
        "registry_ref": ArtifactReference(
            id="fixture:registry", version="v1", sha256="4" * 64
        ),
        "method_ref": ArtifactReference(
            id="fixture:method", version="v1", sha256="5" * 64
        ),
        "clock_policy_ref": ArtifactReference(
            id="fixture:clocks", version="v1", sha256="6" * 64
        ),
        "budget_ref": ArtifactReference(
            id="fixture:budget", version="v1", sha256="8" * 64
        ),
        "memory_snapshot_ref": ArtifactReference(
            id="fixture:memory", version="v1", sha256="9" * 64
        ),
        "excluded_inputs_ref": ArtifactReference(
            id="fixture:exclusions", version="v1", sha256="7" * 64
        ),
    }


def test_adversarial_t04_cross_arm_memory_leakage_prevented(
    sample_refs: dict[str, ArtifactReference],
) -> None:
    """T04: Feedback from Arm B must NEVER leak into Arm C learning state."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    # Arm B trial outcome
    arm_b_trial = TrialFeedbackRecord(
        trial_id="trial-arm-b-001",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=1),
        matured_at=cutoff - timedelta(hours=1),
        candidate_id="cand-b",
        status="completed",
        pnl="500.00",
        metrics={"sharpe": "2.0"},
        is_complete=True,
    )

    # Attempt to ingest Arm B feedback into Arm C learning memory
    snap_c = advance_learning(
        previous_snapshot=None,
        feedback_records=[arm_b_trial],
        cutoff=cutoff,
        arm_id="arm-C",  # Target arm is C!
        method_ref=sample_refs["method_ref"],
    )

    # Arm C memory must remain completely empty
    assert len(snap_c.matured_trials) == 0


def test_adversarial_t05_sealed_holdout_contamination_prevented(
    sample_refs: dict[str, ArtifactReference],
) -> None:
    """T05: Ingestion of sealed holdout data triggers security violation."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    holdout_trial = TrialFeedbackRecord(
        trial_id="holdout:trial-001",
        arm_id="arm-B",
        decision_cutoff=cutoff - timedelta(days=1),
        matured_at=cutoff - timedelta(hours=1),
        candidate_id="cand-holdout",
        status="completed",
        pnl="1000.00",
        metrics={"sharpe": "3.0"},
        is_complete=True,
        is_holdout=True,
    )

    with pytest.raises(ValueError, match="HOLDOUT_ACCESS_VIOLATION"):
        advance_learning(
            previous_snapshot=None,
            feedback_records=[holdout_trial],
            cutoff=cutoff,
            arm_id="arm-B",
            method_ref=sample_refs["method_ref"],
        )


def test_adversarial_t01_t02_subsecond_lookahead_refusal(
    sample_scope_b: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """T01, T02: Subsecond future information is strictly detected and refused."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, 0, tzinfo=UTC)

    # Input available 1 millisecond into the future
    subsecond_future = CandidateInput(
        input_ref=ArtifactReference(id="input:tick", version="v1", sha256="a" * 64),
        role="intraday_tick",
        available_at=cutoff + timedelta(milliseconds=1),
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="b" * 64
        ),
    )

    with pytest.raises(
        ValueError, match="refuse: input availability after 10:00 cutoff"
    ):
        build_context(
            scope=sample_scope_b,
            decision_cutoff=cutoff,
            portfolio_ref=sample_refs["portfolio_ref"],
            mandate_ref=sample_refs["mandate_ref"],
            universe_ref=sample_refs["universe_ref"],
            registry_ref=sample_refs["registry_ref"],
            method_ref=sample_refs["method_ref"],
            clock_policy_ref=sample_refs["clock_policy_ref"],
            budget_ref=sample_refs["budget_ref"],
            memory_snapshot_ref=sample_refs["memory_snapshot_ref"],
            excluded_inputs_ref=sample_refs["excluded_inputs_ref"],
            inputs=[subsecond_future],
        )


def test_adversarial_order_perturbation_invariance(
    sample_scope_b: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """Permuting the order of admitted inputs produces identical context record_hash."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    inp1 = CandidateInput(
        input_ref=ArtifactReference(id="input:1", version="v1", sha256="1" * 64),
        role="news",
        available_at=cutoff - timedelta(minutes=10),
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="b" * 64
        ),
    )
    inp2 = CandidateInput(
        input_ref=ArtifactReference(id="input:2", version="v1", sha256="2" * 64),
        role="prices",
        available_at=cutoff - timedelta(minutes=5),
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="b" * 64
        ),
    )

    ctx_order_a = build_context(
        scope=sample_scope_b,
        decision_cutoff=cutoff,
        portfolio_ref=sample_refs["portfolio_ref"],
        mandate_ref=sample_refs["mandate_ref"],
        universe_ref=sample_refs["universe_ref"],
        registry_ref=sample_refs["registry_ref"],
        method_ref=sample_refs["method_ref"],
        clock_policy_ref=sample_refs["clock_policy_ref"],
        budget_ref=sample_refs["budget_ref"],
        memory_snapshot_ref=sample_refs["memory_snapshot_ref"],
        excluded_inputs_ref=sample_refs["excluded_inputs_ref"],
        inputs=[inp1, inp2],
        context_id="fixed-ctx-id",
    )

    ctx_order_b = build_context(
        scope=sample_scope_b,
        decision_cutoff=cutoff,
        portfolio_ref=sample_refs["portfolio_ref"],
        mandate_ref=sample_refs["mandate_ref"],
        universe_ref=sample_refs["universe_ref"],
        registry_ref=sample_refs["registry_ref"],
        method_ref=sample_refs["method_ref"],
        clock_policy_ref=sample_refs["clock_policy_ref"],
        budget_ref=sample_refs["budget_ref"],
        memory_snapshot_ref=sample_refs["memory_snapshot_ref"],
        excluded_inputs_ref=sample_refs["excluded_inputs_ref"],
        inputs=[inp2, inp1],  # Permuted order!
        context_id="fixed-ctx-id",
    )

    assert ctx_order_a.record_hash == ctx_order_b.record_hash
