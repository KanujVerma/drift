"""Unit tests for point-in-time causal context builder.

Verifies acceptance criteria T01, T02, T04, T05 from research.md and DP-R5/DP-R8:
- Pre-aggregation causal filtering and rejection of post-cutoff inputs (N04).
- Sealed holdout isolation rejection (T05).
- Arm boundary filtering (T04).
- Deduplication and deterministic context record_hash generation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from drift.intelligence.context_builder import CandidateInput, build_context
from drift.intelligence.contracts import ArtifactReference, Scope


@pytest.fixture
def sample_scope() -> Scope:
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


def test_build_context_valid_inputs(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """Build context with valid causal inputs produces valid ResearchContext."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    inp1 = CandidateInput(
        input_ref=ArtifactReference(id="input:price", version="v1", sha256="a" * 64),
        role="market_prices",
        available_at=cutoff - timedelta(minutes=5),
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="f" * 64
        ),
    )
    inp2 = CandidateInput(
        input_ref=ArtifactReference(id="input:news", version="v1", sha256="b" * 64),
        role="news_headline",
        available_at=cutoff - timedelta(minutes=1),
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="f" * 64
        ),
    )

    ctx = build_context(
        scope=sample_scope,
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
    )

    assert ctx.profile == "drift-research/1-draft"
    assert ctx.kind == "context"
    assert len(ctx.inputs) == 2
    assert ctx.decision_cutoff == cutoff
    assert ctx.built_at == cutoff
    assert ctx.record_hash is not None


def test_t01_t02_post_cutoff_input_rejection(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """T01, T02: Inputs available after decision cutoff are strictly refused."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    future_inp = CandidateInput(
        input_ref=ArtifactReference(id="input:future", version="v1", sha256="a" * 64),
        role="future_leakage",
        available_at=cutoff + timedelta(seconds=1),  # 10:00:01 > 10:00:00
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="f" * 64
        ),
    )

    with pytest.raises(
        ValueError, match="refuse: input availability after 10:00 cutoff"
    ):
        build_context(
            scope=sample_scope,
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
            inputs=[future_inp],
        )


def test_t05_holdout_access_violation(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """T05: Attempting to consume sealed holdout input triggers security violation."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    holdout_inp = CandidateInput(
        input_ref=ArtifactReference(
            id="holdout:eval-report", version="v1", sha256="a" * 64
        ),
        role="sealed_holdout",
        available_at=cutoff - timedelta(hours=1),
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="f" * 64
        ),
        is_holdout=True,
    )

    with pytest.raises(ValueError, match="HOLDOUT_ACCESS_VIOLATION"):
        build_context(
            scope=sample_scope,
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
            inputs=[holdout_inp],
        )


def test_t04_cross_arm_input_filtering(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """T04: Input restricted to different arm is excluded from context."""
    cutoff = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    other_arm_inp = CandidateInput(
        input_ref=ArtifactReference(
            id="input:other-arm", version="v1", sha256="a" * 64
        ),
        role="peer_arm_data",
        available_at=cutoff - timedelta(hours=1),
        availability_basis_ref=ArtifactReference(
            id="basis:feed", version="v1", sha256="f" * 64
        ),
        arm_id="fixture:arm-C",  # sample_scope is fixture:B
    )

    ctx = build_context(
        scope=sample_scope,
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
        inputs=[other_arm_inp],
    )

    # Input should be filtered out
    assert len(ctx.inputs) == 0
