"""Offline, synthetic intelligence integration without execution authorization.

The K0 preflight and K1-K5 producer boundary are independently testable before
Matthew's M0 admission and Kanuj's scientific experiment are integrated. This
suite must never claim to test broker, paid source or live-market operations.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from drift.intelligence.contracts import (
    ArtifactReference,
    ResearchCandidate,
    ResearchContext,
    StrategySelection,
)
from drift.intelligence.conventional_selector import select_conventional_candidate
from drift.intelligence.platform_bridge import (
    PortfolioStateBinding,
    bridge_candidate_to_execution,
)
from drift.intelligence.proposal_producer import FakeTransport, produce_proposal
from drift.intelligence.receipts import ResearchReceiptStore
from drift.intelligence.validation import ResolvedDependencies, StrategyRegistration
from drift.loop.stage1_switch_preflight import (
    PreflightStatus,
    evaluate_stage1_switch_preflight,
)

FIXTURE = Path("tests/fixtures/adaptive_research/research_v1.json")


def _context_and_bindings() -> tuple[ResearchContext, ResolvedDependencies, dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    context = ResearchContext.model_validate(data["fixtures"]["F01"])
    candidate = data["fixtures"]["F02"]
    strategy = candidate["strategy"]
    selection = StrategySelection(
        family_id=strategy["family_id"],
        strategy_version=strategy["strategy_ref"]["version"],
        parameters={},
    )
    resolved = ResolvedDependencies(
        portfolio_ref=context.portfolio_ref,
        mandate_ref=context.mandate_ref,
        universe_ref=context.universe_ref,
        registry_ref=context.registry_ref,
        method_ref=context.method_ref,
        admitted_securities=tuple(
            target["security_id"] for target in candidate["targets"]
        ),
        strategy_registry={
            selection.family_id: StrategyRegistration(
                family_id=selection.family_id,
                strategy_ref=ArtifactReference.model_validate(strategy["strategy_ref"]),
                envelope_ref=ArtifactReference.model_validate(strategy["envelope_ref"]),
                eligibility_ref=ArtifactReference.model_validate(
                    strategy["eligibility_ref"]
                ),
                allowed_parameters={},
            ),
        },
        current_selection=selection,
    )
    return context, resolved, data["raw_choice"]


def test_ai_and_r_share_context_but_not_mutable_receipts() -> None:
    """Two arms see the same causal evidence and retain independent attempt IDs."""
    context, bindings, raw = _context_and_bindings()
    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    ai_store, r_store = ResearchReceiptStore(), ResearchReceiptStore()
    policy = ArtifactReference(id="synthetic:validation", version="v1", sha256="b" * 64)
    ai = produce_proposal(
        context=context,
        resolved_inputs=bindings,
        frozen_method=ArtifactReference(
            id="synthetic:ai-method", version="v1", sha256="a" * 64
        ),
        validation_policy=policy,
        recorder=ai_store,
        transport=FakeTransport(raw_choice=raw),
        attempt_id="synthetic-ai",
        checked_at=at,
    )
    conventional = select_conventional_candidate(
        context=context,
        resolved_inputs=bindings,
        candidate_pool=[raw],
        objective_fn=lambda _candidate: Decimal("1"),
        method_ref=ArtifactReference(
            id="synthetic:r-method", version="v1", sha256="c" * 64
        ),
        validation_policy=policy,
        recorder=r_store,
        attempt_id="synthetic-r",
        checked_at=at,
    )
    assert ai.is_success and conventional.is_success
    assert ai.candidate is not None and conventional.selected_candidate is not None
    assert ai.candidate.context_ref.sha256 == context.record_hash
    assert conventional.selected_candidate.context_ref.sha256 == context.record_hash
    assert ai.attempt_id != conventional.attempt_id
    assert len(ai_store.get_attempt_events(ai.attempt_id)) == 2
    assert len(r_store.get_attempt_events(conventional.attempt_id)) == 2
    assert r_store.get_attempt_events(ai.attempt_id) == ()
    assert ai_store.get_attempt_events(conventional.attempt_id) == ()
    assert len(ai_store.get_cost_receipts_for_attempt(ai.attempt_id)) == 1
    assert len(r_store.get_cost_receipts_for_attempt(conventional.attempt_id)) == 1


def test_valid_scripted_choice_stops_at_the_unintegrated_platform_boundary() -> None:
    """A typed next-open research request is not a trade or an M0 admission."""
    context, bindings, raw = _context_and_bindings()
    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    ai = produce_proposal(
        context=context,
        resolved_inputs=bindings,
        frozen_method=ArtifactReference(
            id="synthetic:method", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="b" * 64
        ),
        recorder=ResearchReceiptStore(),
        transport=FakeTransport(raw_choice=raw),
        attempt_id="synthetic-ai-platform",
        checked_at=at,
    )
    assert ai.candidate is not None
    candidate = ai.candidate
    observed = PortfolioStateBinding(
        portfolio_ref=candidate.portfolio_ref,
        mandate_ref=candidate.mandate_ref,
        account_id=candidate.scope.account_id,
        arm_id=candidate.scope.arm_id,
        state_hash=candidate.portfolio_ref.sha256,
        is_paused=False,
        has_pending_orders=False,
        observed_at=at + timedelta(seconds=1),
        state_verified=True,
        verification_ref=ArtifactReference(
            id="synthetic:account-evidence", version="v1", sha256="d" * 64
        ),
    )
    proposal = bridge_candidate_to_execution(
        candidate=candidate,
        portfolio_state=observed,
        current_time=at + timedelta(seconds=2),
        intraday_supported=False,
        allow_next_open_fallback=True,
    )
    assert proposal.status == "admitted"
    assert proposal.session_target == "next_open"
    assert proposal.target_allocations
    # This integration suite has no order-sender, M0 admission, or accounting
    # mutation: a proposal is intentionally the terminal artifact.


def test_scripted_proposal_cannot_bypass_unknown_platform_safety() -> None:
    """A valid decision is not sufficient to make unknown account state safe."""
    context, bindings, raw = _context_and_bindings()
    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    ai = produce_proposal(
        context=context,
        resolved_inputs=bindings,
        frozen_method=ArtifactReference(
            id="synthetic:method", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="b" * 64
        ),
        recorder=ResearchReceiptStore(),
        transport=FakeTransport(raw_choice=raw),
        attempt_id="synthetic-ai-unknown",
        checked_at=at,
    )
    assert ai.candidate is not None
    candidate = ai.candidate
    unverifiable = PortfolioStateBinding(
        portfolio_ref=candidate.portfolio_ref,
        mandate_ref=candidate.mandate_ref,
        account_id=candidate.scope.account_id,
        arm_id=candidate.scope.arm_id,
        state_hash=candidate.portfolio_ref.sha256,
        is_paused=False,
        has_pending_orders=False,
        observed_at=at,
        # No platform verification, regardless of caller-supplied state hashes.
    )
    request = bridge_candidate_to_execution(
        candidate=candidate,
        portfolio_state=unverifiable,
        current_time=at + timedelta(seconds=1),
    )
    assert request.status == "refused"
    assert request.session_target == "none"
    assert request.target_allocations == ()
    assert "UNVERIFIED_PORTFOLIO_STATE" in (request.refusal_reason or "")


def test_k0_unavailable_without_evidence_cannot_become_a_sell_all() -> None:
    """A standalone preflight must fail closed before complete-target staging."""
    verdict = evaluate_stage1_switch_preflight(
        proposed_strategy="B4",
        current_strategy="B3",
        decision_context=None,
    )
    assert verdict.status != PreflightStatus.ELIGIBLE
    assert not verdict.is_tradeable
    assert not verdict.hold_incumbent
    assert verdict.requires_containment
    # No Stage 1 proposer has authority to manufacture a sell-all order here.


def test_b3_b4_b5_fixed_family_proposals_share_causal_context_with_r() -> None:
    """Prove the bounded family choice seam without inventing market eligibility."""
    context, inputs, fixture_choice = _context_and_bindings()
    selections = {}
    for index, family in enumerate(("B3", "B4", "B5"), start=1):
        selections[family] = StrategyRegistration(
            family_id=family,
            strategy_ref=ArtifactReference(
                id=f"synthetic:{family}:strategy",
                version="synthetic-v1",
                sha256=f"{index}" * 64,
            ),
            envelope_ref=ArtifactReference(
                id=f"synthetic:{family}:envelope",
                version="synthetic-v1",
                sha256="8" * 64,
            ),
            eligibility_ref=ArtifactReference(
                id=f"synthetic:{family}:eligibility",
                version="synthetic-v1",
                sha256="a" * 64,
            ),
            allowed_parameters={},
        )
    resolved = ResolvedDependencies(
        portfolio_ref=inputs.portfolio_ref,
        mandate_ref=inputs.mandate_ref,
        universe_ref=inputs.universe_ref,
        registry_ref=inputs.registry_ref,
        method_ref=inputs.method_ref,
        admitted_securities=inputs.admitted_securities,
        strategy_registry=selections,
        current_selection=StrategySelection(
            family_id="B3", strategy_version="synthetic-v1", parameters={}
        ),
    )

    def choice(family: str) -> dict[str, Any]:
        proposal = json.loads(json.dumps(fixture_choice))
        proposal["selection"] = {
            "family_id": family,
            "strategy_version": "synthetic-v1",
            "parameters": {},
        }
        return proposal

    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    policy = ArtifactReference(id="synthetic:policy", version="v1", sha256="b" * 64)
    ai_store = ResearchReceiptStore()
    conventional_store = ResearchReceiptStore()
    ai = produce_proposal(
        context=context,
        resolved_inputs=resolved,
        frozen_method=ArtifactReference(
            id="synthetic:scripted-ai", version="v1", sha256="c" * 64
        ),
        validation_policy=policy,
        recorder=ai_store,
        transport=FakeTransport(raw_choice=choice("B4")),
        attempt_id="synthetic-stage1-ai",
        checked_at=at,
    )

    def synthetic_score(candidate: ResearchCandidate) -> Decimal:
        """Frozen fixture rank only, not an authorized market objective."""
        if candidate.strategy is None:
            return Decimal("-1")
        return {
            "B3": Decimal("0.1"),
            "B4": Decimal("0.2"),
            "B5": Decimal("0.3"),
        }[candidate.strategy.family_id]

    comparison = select_conventional_candidate(
        context=context,
        resolved_inputs=resolved,
        candidate_pool=[choice("B3"), choice("B4"), choice("B5")],
        objective_fn=synthetic_score,
        method_ref=ArtifactReference(
            id="synthetic:registered-objective", version="v1", sha256="d" * 64
        ),
        validation_policy=policy,
        recorder=conventional_store,
        attempt_id="synthetic-stage1-r",
        checked_at=at,
    )
    assert ai.is_success and comparison.is_success
    assert ai.candidate is not None
    assert comparison.selected_candidate is not None
    assert ai.candidate.strategy is not None
    assert comparison.selected_candidate.strategy is not None
    assert ai.candidate.strategy.family_id == "B4"
    assert comparison.selected_candidate.strategy.family_id == "B5"
    assert (
        ai.candidate.context_ref.sha256
        == comparison.selected_candidate.context_ref.sha256
    )
    assert ai_store.get_attempt_events(comparison.attempt_id) == ()
    assert conventional_store.get_attempt_events(ai.attempt_id) == ()
    # Registered fixture hashes are not authenticated market eligibility:
    # no fill, broker call or scored scientific experiment follows this choice.
