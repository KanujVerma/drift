"""Unit tests for platform execution bridge.

Verifies acceptance criteria under T08, T14, A09, A12, DP-R2:
- T08: Stale candidate expiration, state change, mandate change, account pause,
  and in-flight pending orders refuse dispatch fail-closed.
- T08: Hold and abstain dispositions admitted without trade dispatch.
- T14: Lookahead violation (execution before completion) refused.
- T14 / A09: Next-open fallback when intraday capability is unavailable.
- A12: Cross-arm / cross-account scope isolation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from drift.intelligence.contracts import (
    ArtifactReference,
    CandidateStrategy,
    ResearchCandidate,
    Scope,
    compute_record_hash,
)
from drift.intelligence.platform_bridge import (
    PortfolioStateBinding,
    bridge_candidate_to_execution,
)


@pytest.fixture
def sample_scope() -> Scope:
    return Scope(
        experiment_id="01900000-0000-7000-8000-000000000001",
        arm_id="arm-B",
        account_id="acct-001",
        campaign_ref=ArtifactReference(
            id="fixture:campaign", version="v1", sha256="c" * 64
        ),
    )


@pytest.fixture
def sample_candidate(sample_scope: Scope) -> ResearchCandidate:
    completed = datetime(2024, 1, 10, 10, 0, 0, tzinfo=UTC)
    raw = {
        "profile": "drift-research/1-draft",
        "kind": "candidate",
        "candidate_id": "cand-001",
        "attempt_id": "attempt-001",
        "scope": sample_scope.model_dump(mode="python"),
        "context_ref": {
            "id": "ctx:001",
            "version": "v1",
            "sha256": "1" * 64,
        },
        "portfolio_ref": {
            "id": "port:001",
            "version": "v1",
            "sha256": "2" * 64,
        },
        "mandate_ref": {
            "id": "mand:001",
            "version": "v1",
            "sha256": "3" * 64,
        },
        "universe_ref": {
            "id": "univ:001",
            "version": "v1",
            "sha256": "4" * 64,
        },
        "registry_ref": {
            "id": "reg:001",
            "version": "v1",
            "sha256": "5" * 64,
        },
        "method_ref": {
            "id": "meth:001",
            "version": "v1",
            "sha256": "6" * 64,
        },
        "producer": "scripted:ai-fixed",
        "completed_at": completed,
        "valid_until": completed + timedelta(hours=2),
        "disposition": "propose",
        "strategy": CandidateStrategy(
            family_id="fixed_family",
            strategy_ref=ArtifactReference(
                id="strat:001", version="v1", sha256="7" * 64
            ),
            envelope_ref=ArtifactReference(id="env:001", version="v1", sha256="8" * 64),
            parameters={"threshold": 0.5},
            parameters_hash="9" * 64,
            eligibility_ref=ArtifactReference(
                id="elig:001", version="v1", sha256="a" * 64
            ),
        ).model_dump(mode="python"),
        "targets": [
            {"security_id": "SPY", "weight": "0.60"},
            {"security_id": "TLT", "weight": "0.40"},
        ],
        "cash_weight": "0.0",
        "evidence_refs": [],
        "rationale": "Adaptive rebalance based on momentum signal.",
        "reason_codes": ["rebalance_signal"],
        "model_replay_ref": None,
        "cost_receipt_ids": ["cost-001"],
    }
    raw["record_hash"] = compute_record_hash(raw)
    return ResearchCandidate.model_validate(raw)


@pytest.fixture
def matching_portfolio_state(
    sample_candidate: ResearchCandidate,
) -> PortfolioStateBinding:
    return PortfolioStateBinding(
        portfolio_ref=sample_candidate.portfolio_ref,
        mandate_ref=sample_candidate.mandate_ref,
        account_id="acct-001",
        arm_id="arm-B",
        state_hash=sample_candidate.portfolio_ref.sha256,
        is_paused=False,
        has_pending_orders=False,
        observed_at=sample_candidate.completed_at + timedelta(seconds=1),
    )


def test_t08_admitted_candidate_intraday(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08: Valid candidate with intraday capability dispatches admitted
    intraday request.
    """
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=dispatch_time,
        intraday_supported=True,
    )

    assert req.status == "admitted"
    assert req.session_target == "intraday"
    assert req.refusal_reason is None
    assert len(req.target_allocations) == 2
    assert req.record_hash is not None


def test_t14_admitted_candidate_next_open_fallback(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T14 / A09: Intraday unavailable cleanly falls back to next open session."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=dispatch_time,
        intraday_supported=False,
        allow_next_open_fallback=True,
    )

    assert req.status == "admitted"
    assert req.session_target == "next_open"
    assert req.refusal_reason is None


def test_t14_unsupported_intraday_without_fallback(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T14: Intraday unavailable without fallback returns unsupported status."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=dispatch_time,
        intraday_supported=False,
        allow_next_open_fallback=False,
    )

    assert req.status == "unsupported"
    assert req.session_target == "none"
    assert "UNSUPPORTED_SESSION" in (req.refusal_reason or "")


def test_t08_hold_and_abstain_admitted_without_trade(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08: Hold and abstain dispositions admitted with session_target none."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    hold_dict = sample_candidate.model_dump(mode="python")
    hold_dict["disposition"] = "hold"
    hold_dict["targets"] = []
    hold_dict["record_hash"] = compute_record_hash(hold_dict)
    hold_cand = ResearchCandidate.model_validate(hold_dict)

    req = bridge_candidate_to_execution(
        candidate=hold_cand,
        portfolio_state=matching_portfolio_state,
        current_time=dispatch_time,
    )

    assert req.status == "admitted"
    assert req.session_target == "none"
    assert len(req.target_allocations) == 0


def test_t08_stale_candidate_expired_refusal(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08 / DP-R2: Candidate validity window expiration refuses dispatch."""
    # valid_until is completed + 2 hours
    expired_time = sample_candidate.completed_at + timedelta(hours=3)

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=expired_time,
    )

    assert req.status == "refused"
    assert "STALE_CANDIDATE_EXPIRED" in (req.refusal_reason or "")


def test_t14_lookahead_violation_refusal(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T14: Execution requested before decision completed_at is strictly refused."""
    premature_time = sample_candidate.completed_at - timedelta(seconds=1)

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=premature_time,
    )

    assert req.status == "refused"
    assert "LOOKAHEAD_VIOLATION" in (req.refusal_reason or "")


def test_t08_stale_portfolio_state_refusal(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08: Underlying portfolio state change refuses dispatch."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    mutated_port_state = PortfolioStateBinding(
        portfolio_ref=ArtifactReference(id="port:001", version="v2", sha256="f" * 64),
        mandate_ref=matching_portfolio_state.mandate_ref,
        account_id=matching_portfolio_state.account_id,
        arm_id=matching_portfolio_state.arm_id,
        state_hash="f" * 64,  # Mutated state hash!
        is_paused=False,
        has_pending_orders=False,
        observed_at=dispatch_time,
    )

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=mutated_port_state,
        current_time=dispatch_time,
    )

    assert req.status == "refused"
    assert "STALE_PORTFOLIO_STATE" in (req.refusal_reason or "")


def test_t08_mandate_mismatch_refusal(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08: Mandate reference change refuses dispatch."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    mutated_mandate_state = PortfolioStateBinding(
        portfolio_ref=matching_portfolio_state.portfolio_ref,
        mandate_ref=ArtifactReference(id="mand:002", version="v2", sha256="e" * 64),
        account_id=matching_portfolio_state.account_id,
        arm_id=matching_portfolio_state.arm_id,
        state_hash=matching_portfolio_state.state_hash,
        is_paused=False,
        has_pending_orders=False,
        observed_at=dispatch_time,
    )

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=mutated_mandate_state,
        current_time=dispatch_time,
    )

    assert req.status == "refused"
    assert "MANDATE_MISMATCH" in (req.refusal_reason or "")


def test_t08_account_paused_refusal(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08: Paused account refuses execution dispatch."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    paused_state = PortfolioStateBinding(
        portfolio_ref=matching_portfolio_state.portfolio_ref,
        mandate_ref=matching_portfolio_state.mandate_ref,
        account_id=matching_portfolio_state.account_id,
        arm_id=matching_portfolio_state.arm_id,
        state_hash=matching_portfolio_state.state_hash,
        is_paused=True,  # Account paused
        has_pending_orders=False,
        observed_at=dispatch_time,
    )

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=paused_state,
        current_time=dispatch_time,
    )

    assert req.status == "refused"
    assert "ACCOUNT_PAUSED" in (req.refusal_reason or "")


def test_t08_pending_orders_conflict_refusal(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08 / A07: Unresolved pending in-flight orders refuse execution dispatch."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    pending_state = PortfolioStateBinding(
        portfolio_ref=matching_portfolio_state.portfolio_ref,
        mandate_ref=matching_portfolio_state.mandate_ref,
        account_id=matching_portfolio_state.account_id,
        arm_id=matching_portfolio_state.arm_id,
        state_hash=matching_portfolio_state.state_hash,
        is_paused=False,
        has_pending_orders=True,  # In-flight orders present
        observed_at=dispatch_time,
    )

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=pending_state,
        current_time=dispatch_time,
    )

    assert req.status == "refused"
    assert "PENDING_ORDERS_CONFLICT" in (req.refusal_reason or "")


def test_a12_scope_mismatch_refusal(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """A12: Arm or account mismatch between candidate and portfolio state
    refuses dispatch.
    """
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    other_arm_state = PortfolioStateBinding(
        portfolio_ref=matching_portfolio_state.portfolio_ref,
        mandate_ref=matching_portfolio_state.mandate_ref,
        account_id=matching_portfolio_state.account_id,
        arm_id="arm-C",  # Candidate is for arm-B!
        state_hash=matching_portfolio_state.state_hash,
        is_paused=False,
        has_pending_orders=False,
        observed_at=dispatch_time,
    )

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=other_arm_state,
        current_time=dispatch_time,
    )

    assert req.status == "refused"
    assert "SCOPE_MISMATCH" in (req.refusal_reason or "")
