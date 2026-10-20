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
from drift.intelligence.contracts import ArtifactReference, ResearchContext, Scope


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


def _context_with_sources(
    scope: Scope,
    refs: dict[str, ArtifactReference],
    inputs: list[CandidateInput],
    *,
    cutoff: datetime,
    source_grade: str = "synthetic_fixture",
) -> ResearchContext:
    return build_context(
        scope=scope,
        decision_cutoff=cutoff,
        portfolio_ref=refs["portfolio_ref"],
        mandate_ref=refs["mandate_ref"],
        universe_ref=refs["universe_ref"],
        registry_ref=refs["registry_ref"],
        method_ref=refs["method_ref"],
        clock_policy_ref=refs["clock_policy_ref"],
        budget_ref=refs["budget_ref"],
        memory_snapshot_ref=refs["memory_snapshot_ref"],
        inputs=inputs,
        source_grade=source_grade,
    )


def test_equal_bytes_different_sources_preserved_and_permutation_stable(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    cutoff = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    a = CandidateInput(
        input_ref=ArtifactReference(id="source:A", version="v1", sha256="a" * 64),
        role="security_a_close",
        available_at=cutoff - timedelta(seconds=1),
        availability_basis_ref=ArtifactReference(
            id="basis:A", version="v1", sha256="c" * 64
        ),
    )
    b = CandidateInput(
        input_ref=ArtifactReference(id="source:B", version="v1", sha256="a" * 64),
        role="security_b_close",
        available_at=cutoff - timedelta(seconds=1),
        availability_basis_ref=ArtifactReference(
            id="basis:B", version="v1", sha256="d" * 64
        ),
    )
    one = _context_with_sources(sample_scope, sample_refs, [a, b], cutoff=cutoff)
    two = _context_with_sources(sample_scope, sample_refs, [b, a], cutoff=cutoff)
    assert len(one.inputs) == 2
    assert one.record_hash == two.record_hash
    assert one.context_id == two.context_id


def test_same_source_revision_conflicting_bytes_rejected(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    cutoff = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    def source(digest: str) -> CandidateInput:
        return CandidateInput(
            input_ref=ArtifactReference(
                id="source:one", version="v1", sha256=digest
            ),
            role="close",
            available_at=cutoff - timedelta(seconds=1),
            availability_basis_ref=ArtifactReference(
                id="basis:one", version="v1", sha256="b" * 64
            ),
        )
    with pytest.raises(ValueError, match="INPUT_REVISION_CONFLICT"):
        _context_with_sources(
            sample_scope, sample_refs, [source("a" * 64), source("c" * 64)],
            cutoff=cutoff,
        )


def test_unknown_timing_authority_is_not_implicitly_utc(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    aware = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="INDETERMINATE_TIMEZONE"):
        _context_with_sources(
            sample_scope, sample_refs, [], cutoff=aware.replace(tzinfo=None)
        )
    with pytest.raises(ValueError, match="CLOCK_AUTHORITY_REQUIRED"):
        _context_with_sources(
            sample_scope, sample_refs, [], cutoff=aware,
            source_grade="exploratory",
        )


def test_generated_context_id_binds_authoritative_budget_and_scope(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """A changed budget or feedback reference cannot reuse the old context ID."""
    cutoff = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    original = _context_with_sources(sample_scope, sample_refs, [], cutoff=cutoff)
    changed_budget = build_context(
        scope=sample_scope,
        decision_cutoff=cutoff,
        portfolio_ref=sample_refs["portfolio_ref"],
        mandate_ref=sample_refs["mandate_ref"],
        universe_ref=sample_refs["universe_ref"],
        registry_ref=sample_refs["registry_ref"],
        method_ref=sample_refs["method_ref"],
        clock_policy_ref=sample_refs["clock_policy_ref"],
        budget_ref=ArtifactReference(
            id=sample_refs["budget_ref"].id,
            version=sample_refs["budget_ref"].version,
            sha256="f" * 64,
        ),
        memory_snapshot_ref=sample_refs["memory_snapshot_ref"],
    )
    changed_feedback = build_context(
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
        feedback_refs=(
            ArtifactReference(id="synthetic:feedback", version="v1", sha256="e" * 64),
        ),
    )
    assert len(
        {original.context_id, changed_budget.context_id, changed_feedback.context_id}
    ) == 3
    assert len(
        {original.record_hash, changed_budget.record_hash, changed_feedback.record_hash}
    ) == 3


def _context_with_feedback(
    scope: Scope,
    refs: dict[str, ArtifactReference],
    feedback: tuple[ArtifactReference, ...],
) -> ResearchContext:
    """Build a fixed synthetic context with explicitly supplied feedback refs."""
    return build_context(
        scope=scope,
        decision_cutoff=datetime(2024, 1, 2, 10, tzinfo=UTC),
        portfolio_ref=refs["portfolio_ref"],
        mandate_ref=refs["mandate_ref"],
        universe_ref=refs["universe_ref"],
        registry_ref=refs["registry_ref"],
        method_ref=refs["method_ref"],
        clock_policy_ref=refs["clock_policy_ref"],
        budget_ref=refs["budget_ref"],
        memory_snapshot_ref=refs["memory_snapshot_ref"],
        feedback_refs=feedback,
    )


def test_forged_frozen_context_inputs_are_reparsed_before_aggregation(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """model_copy may bypass a ref validator but never K4 readback."""
    cutoff = datetime(2024, 1, 2, 10, tzinfo=UTC)
    original = CandidateInput(
        input_ref=ArtifactReference(
            id="synthetic:news", version="v1", sha256="a" * 64
        ),
        role="news",
        available_at=cutoff - timedelta(seconds=1),
        availability_basis_ref=ArtifactReference(
            id="synthetic:basis", version="v1", sha256="b" * 64
        ),
    )
    forged_ref = original.input_ref.model_copy(update={"sha256": "not-a-digest"})
    forged_inputs = (
        original.model_copy(update={"input_ref": forged_ref}),
        original.model_copy(update={"available_at": "unknown"}),
    )
    for entry in forged_inputs:
        with pytest.raises(ValueError, match="INVALID_CONTEXT_INPUT"):
            _context_with_sources(
                sample_scope, sample_refs, [entry], cutoff=cutoff
            )


def test_feedback_refs_refuse_forgery_sealed_access_and_revision_conflicts(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """Bare refs do not certify feedback, but obvious invalid proof is refused."""
    valid = ArtifactReference(
        id="synthetic:feedback", version="v1", sha256="a" * 64
    )
    altered = ArtifactReference(
        id=valid.id, version=valid.version, sha256="b" * 64
    )
    corrupted = valid.model_copy(update={"sha256": "not-a-sha256"})
    sealed = ArtifactReference(
        id="HOLDOUT:sealed-feedback", version="v1", sha256="c" * 64
    )
    with pytest.raises(ValueError, match="INVALID_FEEDBACK_REFERENCE"):
        _context_with_feedback(sample_scope, sample_refs, (corrupted,))
    with pytest.raises(ValueError, match="HOLDOUT_ACCESS_VIOLATION"):
        _context_with_feedback(sample_scope, sample_refs, (sealed,))
    for entries in ((valid, altered), (altered, valid)):
        with pytest.raises(ValueError, match="FEEDBACK_REVISION_CONFLICT"):
            _context_with_feedback(sample_scope, sample_refs, entries)


def test_repeated_or_reordered_identical_feedback_revisions_are_idempotent(
    sample_scope: Scope, sample_refs: dict[str, ArtifactReference]
) -> None:
    """One exact feedback ref cannot manufacture extra learned evidence."""
    first = ArtifactReference(
        id="synthetic:feedback:A", version="v1", sha256="a" * 64
    )
    second = ArtifactReference(
        id="synthetic:feedback:B", version="v1", sha256="b" * 64
    )
    one = _context_with_feedback(sample_scope, sample_refs, (first, second))
    replay = _context_with_feedback(
        sample_scope, sample_refs, (second, first, first, second)
    )
    assert one.context_id == replay.context_id
    assert one.record_hash == replay.record_hash
    assert one.feedback_refs == replay.feedback_refs
    assert len(replay.feedback_refs) == 2
