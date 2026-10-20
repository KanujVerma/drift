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
    PlatformExecutionRequest,
    PortfolioStateBinding,
    bridge_candidate_to_execution,
)
from drift.serialization.canonical import content_hash


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
            parameters={"threshold": "0.5"},
            parameters_hash=content_hash({"threshold": "0.5"}),
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
        state_verified=True,
        verification_ref=ArtifactReference(
            id="fixture:verified-account-observation",
            version="synthetic-v1",
            sha256="e" * 64
        ),
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
    assert req.target_allocations == ()
    assert req.cash_weight is None
    assert "UNSUPPORTED_SESSION" in (req.refusal_reason or "")


def test_t08_hold_and_abstain_admitted_without_trade(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """T08: Hold and abstain dispositions admitted with session_target none."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)

    hold_dict = sample_candidate.model_dump(mode="python")
    hold_dict["disposition"] = "hold"
    hold_dict["strategy"] = None
    hold_dict["targets"] = []
    hold_dict["cash_weight"] = None
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
        state_verified=True,
        verification_ref=ArtifactReference(
            id="fixture:verified-account-observation",
            version="synthetic-v1",
            sha256="e" * 64
        ),
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
        state_verified=True,
        verification_ref=ArtifactReference(
            id="fixture:verified-account-observation",
            version="synthetic-v1",
            sha256="e" * 64
        ),
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
        state_verified=True,
        verification_ref=ArtifactReference(
            id="fixture:verified-account-observation",
            version="synthetic-v1",
            sha256="e" * 64
        ),
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
        state_verified=True,
        verification_ref=ArtifactReference(
            id="fixture:verified-account-observation",
            version="synthetic-v1",
            sha256="e" * 64
        ),
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
        state_verified=True,
        verification_ref=ArtifactReference(
            id="fixture:verified-account-observation",
            version="synthetic-v1",
            sha256="e" * 64
        ),
    )

    req = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=other_arm_state,
        current_time=dispatch_time,
    )

    assert req.status == "refused"
    assert "SCOPE_MISMATCH" in (req.refusal_reason or "")


def test_unknown_account_verification_is_not_safe(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """Missing trusted account evidence cannot be inferred as a safe hold or trade."""
    state = matching_portfolio_state.model_copy(
        update={"state_verified": False, "verification_ref": None}
    )
    request = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=state,
        current_time=sample_candidate.completed_at + timedelta(minutes=5),
    )
    assert request.status == "refused"
    assert request.target_allocations == ()
    assert "UNVERIFIED_PORTFOLIO_STATE" in (request.refusal_reason or "")


def test_future_account_snapshot_refuses(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """No evidence from after the request instant is visible to the bridge."""
    now = sample_candidate.completed_at + timedelta(minutes=5)
    state = matching_portfolio_state.model_copy(
        update={"observed_at": now + timedelta(seconds=1)}
    )
    request = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=state, current_time=now
    )
    assert request.status == "refused"
    assert "STALE_OR_FUTURE_STATE" in (request.refusal_reason or "")


def test_ambiguous_timezones_fail_closed(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    naive = sample_candidate.completed_at.replace(tzinfo=None)
    with pytest.raises(ValueError, match="INDETERMINATE_TIMEZONE"):
        bridge_candidate_to_execution(
            candidate=sample_candidate,
            portfolio_state=matching_portfolio_state,
            current_time=naive,
        )


def test_request_identity_is_stable_for_identical_inputs(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    now = sample_candidate.completed_at + timedelta(minutes=5)
    one = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=now
    )
    two = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=now
    )
    assert one.request_id == two.request_id
    assert one.record_hash == two.record_hash


def test_stage1_empty_propose_refuses_before_platform(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """An ineligible empty proposal never becomes an M2 sell-all instruction."""
    payload = sample_candidate.model_dump(mode="python")
    payload["targets"] = []
    payload["cash_weight"] = "1"
    payload["record_hash"] = compute_record_hash(payload)
    candidate = ResearchCandidate.model_validate(payload)
    request = bridge_candidate_to_execution(
        candidate=candidate,
        portfolio_state=matching_portfolio_state,
        current_time=candidate.completed_at + timedelta(minutes=5),
    )
    assert request.status == "refused"
    assert request.target_allocations == ()
    assert "EMPTY_STAGE1_TARGETS" in (request.refusal_reason or "")


def test_untrusted_model_copy_cannot_relabel_refusal_as_admission(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    state = matching_portfolio_state.model_copy(
        update={"state_verified": False, "verification_ref": None}
    )
    rejected = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=state,
        current_time=sample_candidate.completed_at + timedelta(minutes=5),
    )
    assert rejected.status == "refused"
    attacked = rejected.model_copy(update={"status": "admitted"})
    with pytest.raises(ValueError, match="PLATFORM_REQUEST_HASH_MISMATCH"):
        type(rejected).model_validate(attacked.model_dump(mode="python"))


def test_refusal_cannot_be_laundered_with_cash_weight(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    """A refused request cannot carry an executable cash/target allocation."""
    dispatch_time = sample_candidate.completed_at + timedelta(minutes=5)
    paused_state = matching_portfolio_state.model_copy(update={"is_paused": True})
    refused = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=paused_state,
        current_time=dispatch_time,
    )
    assert refused.status == "refused"
    assert refused.target_allocations == ()
    assert refused.cash_weight is None
    tampered = refused.model_dump(mode="python")
    tampered["cash_weight"] = "0.40"
    tampered["record_hash"] = compute_record_hash(tampered)
    with pytest.raises(ValueError, match="NON_ACTIONABLE_PLATFORM_REQUEST_HAS_TARGETS"):
        PlatformExecutionRequest.model_validate(tampered)



@pytest.mark.parametrize(
    ("weights", "cash"),
    [
        (("0.80", "0.40"), "0.0"),
        (("0.30", "0.30"), "0.2"),
        (("0.60", "0.40"), "NaN"),
        (("0.60", "0.40"), "Infinity"),
        (("0.60", "0.40"), "1e-3"),
    ],
)
def test_self_rehashed_invalid_weights_never_make_a_platform_request(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
    weights: tuple[str, str],
    cash: str,
) -> None:
    """A valid-looking hash cannot replace a real weight-sum check."""
    payload = sample_candidate.model_dump(mode="python")
    payload["targets"][0]["weight"] = weights[0]
    payload["targets"][1]["weight"] = weights[1]
    payload["cash_weight"] = cash
    payload["record_hash"] = compute_record_hash(payload)
    # A self-rehashed record must fail *intrinsic K1 validation* before
    # it could become a K5 research execution request.
    with pytest.raises(ValueError):
        ResearchCandidate.model_validate(payload)

    # model_copy(update=...) can bypass Pydantic validators at construction.
    # K5 must still reject that forged object at its own trust boundary.
    forged = sample_candidate.model_copy(
        update={
            "targets": tuple(
                target.model_copy(update={"weight": value})
                for target, value in zip(sample_candidate.targets, weights, strict=True)
            ),
            "cash_weight": cash,
            "record_hash": payload["record_hash"],
        }
    )
    with pytest.raises(ValueError):
        bridge_candidate_to_execution(
            candidate=forged,
            portfolio_state=matching_portfolio_state,
            current_time=sample_candidate.completed_at + timedelta(minutes=5),
        )


def test_full_portfolio_and_mandate_refs_must_match_even_with_same_hash(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    now = sample_candidate.completed_at + timedelta(minutes=5)
    wrong_portfolio = matching_portfolio_state.model_copy(
        update={"portfolio_ref": ArtifactReference(
            id="port:other", version=matching_portfolio_state.portfolio_ref.version,
            sha256=matching_portfolio_state.portfolio_ref.sha256,
        )}
    )
    portfolio_refusal = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=wrong_portfolio,
        current_time=now,
    )
    assert portfolio_refusal.status == "refused"
    assert "STALE_PORTFOLIO_STATE" in (portfolio_refusal.refusal_reason or "")
    wrong_mandate = matching_portfolio_state.model_copy(
        update={"mandate_ref": ArtifactReference(
            id=matching_portfolio_state.mandate_ref.id, version="v2",
            sha256=matching_portfolio_state.mandate_ref.sha256,
        )}
    )
    mandate_refusal = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=wrong_mandate,
        current_time=now,
    )
    assert mandate_refusal.status == "refused"
    assert "MANDATE_MISMATCH" in (mandate_refusal.refusal_reason or "")
    assert portfolio_refusal.target_allocations == ()
    assert mandate_refusal.target_allocations == ()


def test_bridge_request_identity_binds_session_and_verification_state(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    now = sample_candidate.completed_at + timedelta(minutes=5)
    baseline = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=matching_portfolio_state,
        current_time=now, intraday_supported=True,
    )
    next_open = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=matching_portfolio_state,
        current_time=now, intraday_supported=False,
    )
    no_session = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=matching_portfolio_state,
        current_time=now, intraday_supported=False,
        allow_next_open_fallback=False,
    )
    other_proof = matching_portfolio_state.model_copy(
        update={"verification_ref": ArtifactReference(
            id="synthetic:alternate-proof", version="v1", sha256="f" * 64
        )}
    )
    different_verification = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=other_proof,
        current_time=now, intraday_supported=True,
    )
    paused = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state.model_copy(
            update={"is_paused": True}
        ),
        current_time=now, intraday_supported=True,
    )
    assert baseline.status == "admitted"
    assert next_open.session_target == "next_open"
    assert no_session.status == "unsupported"
    assert paused.status == "refused"
    ids = [
        baseline.request_id, next_open.request_id, no_session.request_id,
        different_verification.request_id, paused.request_id,
    ]
    assert len(set(ids)) == len(ids)
    replay = bridge_candidate_to_execution(
        candidate=sample_candidate, portfolio_state=matching_portfolio_state,
        current_time=now, intraday_supported=True,
    )
    assert baseline.request_id == replay.request_id
    assert baseline.record_hash == replay.record_hash


@pytest.mark.parametrize(
    ("weights", "cash"),
    [
        (("0.80", "0.40"), "0"),
        (("0.60", "0.40"), "NaN"),
        (("0.60", "0.40"), "Infinity"),
        (("0.60", "0.40"), "-0.10"),
        (("0.60", "0.40"), "1e-3"),
    ],
)
def test_self_rehashed_platform_request_refuses_bad_actionable_weights(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
    weights: tuple[str, str],
    cash: str,
) -> None:
    approved = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=sample_candidate.completed_at + timedelta(minutes=5),
        intraday_supported=True,
    )
    assert approved.status == "admitted"
    payload = approved.model_dump(mode="python")
    payload["target_allocations"][0]["weight"] = weights[0]
    payload["target_allocations"][1]["weight"] = weights[1]
    payload["cash_weight"] = cash
    payload["record_hash"] = compute_record_hash(payload)
    with pytest.raises(ValueError, match="INVALID_PLATFORM_TARGET_WEIGHTS"):
        PlatformExecutionRequest.model_validate(payload)


def test_direct_rehashed_request_refuses_duplicate_target_id(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    approved = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=sample_candidate.completed_at + timedelta(minutes=5),
        intraday_supported=True,
    )
    payload = approved.model_dump(mode="python")
    payload["target_allocations"][1]["security_id"] = "SPY"
    payload["record_hash"] = compute_record_hash(payload)
    with pytest.raises(ValueError, match="DUPLICATE_PLATFORM_TARGET"):
        PlatformExecutionRequest.model_validate(payload)


def test_admitted_request_cannot_be_rehashed_from_unavailable_disposition(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    approved = bridge_candidate_to_execution(
        candidate=sample_candidate,
        portfolio_state=matching_portfolio_state,
        current_time=sample_candidate.completed_at + timedelta(minutes=5),
        intraday_supported=True,
    )
    payload = approved.model_dump(mode="python")
    payload["disposition"] = "unavailable"
    payload["record_hash"] = compute_record_hash(payload)
    with pytest.raises(ValueError, match="INVALID_ADMITTED_PLATFORM_REQUEST"):
        PlatformExecutionRequest.model_validate(payload)


def test_model_copy_state_flag_cannot_forge_verified_permission(
    sample_candidate: ResearchCandidate,
    matching_portfolio_state: PortfolioStateBinding,
) -> None:
    forged = matching_portfolio_state.model_copy(
        update={"state_verified": "true"}
    )
    with pytest.raises(ValueError):
        bridge_candidate_to_execution(
            candidate=sample_candidate, portfolio_state=forged,
            current_time=sample_candidate.completed_at + timedelta(minutes=5),
        )
