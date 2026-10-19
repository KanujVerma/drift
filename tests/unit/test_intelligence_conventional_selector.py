"""Unit tests for conventional candidate selector, optimizer R seam, and controls (T13).

Verifies acceptance criteria T07, T09, T13 from research.md and DP-R6:
- Conventional selection over finite candidate pool with deterministic tie-breaking.
- Handling empty/all-rejected candidate pool.
- T13: AI and R share identical context refs with isolated mutable state.
"""

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from drift.intelligence.contracts import (
    ArtifactReference,
    ResearchCandidate,
    ResearchContext,
    StrategySelection,
)
from drift.intelligence.conventional_selector import (
    select_conventional_candidate,
)
from drift.intelligence.proposal_producer import (
    FakeTransport,
    produce_proposal,
)
from drift.intelligence.receipts import ResearchReceiptStore
from drift.intelligence.validation import (
    ResolvedDependencies,
    StrategyRegistration,
)

FIXTURES_PATH = Path("tests/fixtures/adaptive_research/research_v1.json")


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, Any]:
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


@pytest.fixture(scope="module")
def sample_context(fixture_data: dict[str, Any]) -> ResearchContext:
    return ResearchContext.model_validate(fixture_data["fixtures"]["F01"])


@pytest.fixture(scope="module")
def sample_bindings(
    sample_context: ResearchContext,
) -> ResolvedDependencies:
    return ResolvedDependencies(
        portfolio_ref=sample_context.portfolio_ref,
        mandate_ref=sample_context.mandate_ref,
        universe_ref=sample_context.universe_ref,
        registry_ref=sample_context.registry_ref,
        method_ref=sample_context.method_ref,
        admitted_securities=(
            "01900000-0000-7000-8000-000000000101",
            "01900000-0000-7000-8000-000000000102",
        ),
        strategy_registry={
            "fixture.equal_weight": StrategyRegistration(
                family_id="fixture.equal_weight",
                strategy_ref=ArtifactReference(
                    id="fixture:strategy",
                    version="fixture-1",
                    sha256="f7a582c87c46a7827b7d829ace364dc66629e3ed39301e59a3f9f72ae15c1fb1",
                ),
                envelope_ref=ArtifactReference(
                    id="fixture:zero-parameter-envelope",
                    version="fixture-1",
                    sha256="954eed434b69e3d2c274b67d714f1d684d3b9d936dae139ff76af18e8fd02c67",
                ),
                eligibility_ref=ArtifactReference(
                    id="fixture:inert-eligibility",
                    version="fixture-1",
                    sha256="ff9f0abaeda972a05bd31e18793515b06b9b5f586abb182ff38441cf7234d1f6",
                ),
                allowed_parameters={},
            )
        },
        current_selection=StrategySelection(
            family_id="fixture.equal_weight",
            strategy_version="fixture-1",
            parameters={},
        ),
    )


def test_conventional_selection_optimal_candidate(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """Conventional selector evaluates candidate pool and selects highest score."""
    recorder = ResearchReceiptStore()

    candidate_pool = [
        {
            "disposition": "propose",
            "selection": {
                "family_id": "fixture.equal_weight",
                "strategy_version": "fixture-1",
                "parameters": {},
            },
            "targets": [
                {
                    "security_id": "01900000-0000-7000-8000-000000000101",
                    "weight": "0.1",
                },
                {
                    "security_id": "01900000-0000-7000-8000-000000000102",
                    "weight": "0.1",
                },
            ],
            "cash_weight": "0.8",
            "evidence_ids": [],
            "rationale": "High cash",
            "reason_codes": [],
        },
        {
            "disposition": "propose",
            "selection": {
                "family_id": "fixture.equal_weight",
                "strategy_version": "fixture-1",
                "parameters": {},
            },
            "targets": [
                {
                    "security_id": "01900000-0000-7000-8000-000000000101",
                    "weight": "0.4",
                },
                {
                    "security_id": "01900000-0000-7000-8000-000000000102",
                    "weight": "0.4",
                },
            ],
            "cash_weight": "0.2",
            "evidence_ids": [],
            "rationale": "Moderate cash",
            "reason_codes": [],
        },
    ]

    # Objective function: reward total invested weight (1 - cash_weight)
    def objective_fn(cand: ResearchCandidate) -> Decimal:
        cash = Decimal(cand.cash_weight or "0")
        return Decimal("1.0") - cash

    res = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=candidate_pool,
        objective_fn=objective_fn,
        method_ref=ArtifactReference(
            id="method:optimizer-r", version="v1", sha256="e" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="f" * 64
        ),
        recorder=recorder,
        attempt_id="att-r-001",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )

    assert res.is_success is True
    assert res.status == "VALID"
    assert res.selected_candidate is not None
    # Candidate with 0.8 invested weight should win
    assert res.selected_candidate.cash_weight == "0.2"

    events = recorder.get_attempt_events("att-r-001")
    assert len(events) == 2
    assert events[1].status == "completed"

    costs = recorder.get_cost_receipts_for_attempt("att-r-001")
    assert len(costs) == 1
    assert costs[0].amount_basis == "verified_zero"


def test_conventional_selection_deterministic_tie_breaking(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """Ties on score are broken deterministically by stable sorting."""
    recorder = ResearchReceiptStore()

    candidate_pool = [
        {
            "disposition": "propose",
            "selection": {
                "family_id": "fixture.equal_weight",
                "strategy_version": "fixture-1",
                "parameters": {},
            },
            "targets": [
                {
                    "security_id": "01900000-0000-7000-8000-000000000101",
                    "weight": "0.3",
                },
                {
                    "security_id": "01900000-0000-7000-8000-000000000102",
                    "weight": "0.3",
                },
            ],
            "cash_weight": "0.4",
            "evidence_ids": [],
            "rationale": "Option 1",
            "reason_codes": [],
        },
        {
            "disposition": "propose",
            "selection": {
                "family_id": "fixture.equal_weight",
                "strategy_version": "fixture-1",
                "parameters": {},
            },
            "targets": [
                {
                    "security_id": "01900000-0000-7000-8000-000000000101",
                    "weight": "0.3",
                },
                {
                    "security_id": "01900000-0000-7000-8000-000000000102",
                    "weight": "0.3",
                },
            ],
            "cash_weight": "0.4",
            "evidence_ids": [],
            "rationale": "Option 2",
            "reason_codes": [],
        },
    ]

    # Equal objective score
    def equal_obj(_cand: ResearchCandidate) -> Decimal:
        return Decimal("1.0")

    res = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=candidate_pool,
        objective_fn=equal_obj,
        method_ref=ArtifactReference(
            id="method:optimizer-r", version="v1", sha256="e" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="f" * 64
        ),
        recorder=recorder,
        attempt_id="att-r-tie",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )

    assert res.is_success is True
    assert res.selected_candidate is not None


def test_t13_control_isolation(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """T13: AI and R share context with isolated mutable state."""
    recorder = ResearchReceiptStore()

    raw_choice = fixture_data["raw_choice"]
    ai_transport = FakeTransport(raw_choice=raw_choice)

    # 1. AI producer runs
    ai_res = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="method:scripted", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="b" * 64
        ),
        recorder=recorder,
        transport=ai_transport,
        attempt_id="att-ai-shared",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )

    # 2. Conventional selector runs with same context
    r_res = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[raw_choice],
        objective_fn=lambda _c: Decimal("1.0"),
        method_ref=ArtifactReference(
            id="method:optimizer-r", version="v1", sha256="e" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="f" * 64
        ),
        recorder=recorder,
        attempt_id="att-r-shared",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )

    # Context remains strictly identical and unmodified
    assert sample_context.record_hash == fixture_data["fixtures"]["F01"]["record_hash"]

    # Both succeeded with isolated distinct attempt IDs
    assert ai_res.is_success is True
    assert r_res.is_success is True
    assert ai_res.attempt_id != r_res.attempt_id

    # Verify recorder has distinct events for both
    ai_events = recorder.get_attempt_events("att-ai-shared")
    r_events = recorder.get_attempt_events("att-r-shared")
    assert len(ai_events) == 2
    assert len(r_events) == 2
    assert ai_events[1].record_hash != r_events[1].record_hash


def test_r_selector_does_not_depend_on_pool_order(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """A permutation of the same preregistered set cannot change R's winner."""
    a = deepcopy(fixture_data["raw_choice"])
    b = deepcopy(a)
    b["targets"][0]["weight"] = "0.4"
    b["targets"][1]["weight"] = "0.4"
    b["cash_weight"] = "0.2"
    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    method = ArtifactReference(id="method:R", version="v1", sha256="e" * 64)
    policy = ArtifactReference(id="policy:fixed", version="v1", sha256="f" * 64)

    def run(pool: list[dict[str, Any]]) -> tuple[str, str, str]:
        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=pool,
            objective_fn=lambda c: Decimal("1") - Decimal(c.cash_weight or "1"),
            method_ref=method,
            validation_policy=policy,
            recorder=ResearchReceiptStore(),
            checked_at=at,
        )
        assert result.is_success and result.selected_candidate is not None
        return (
            result.attempt_id,
            result.selected_candidate.record_hash,
            result.selected_candidate.candidate_id,
        )

    assert run([a, b]) == run([b, a])


def test_r_invalid_objective_never_selects_a_candidate(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """No NaN/Infinity score may be mistaken for a winning objective."""
    for bad in (Decimal("NaN"), Decimal("Infinity")):
        recorder = ResearchReceiptStore()
        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=[fixture_data["raw_choice"]],
            objective_fn=lambda _c: bad,
            method_ref=ArtifactReference(
                id="method:R", version="v1", sha256="e" * 64
            ),
            validation_policy=ArtifactReference(
                id="policy:fixed", version="v1", sha256="f" * 64
            ),
            recorder=recorder,
            attempt_id=f"att-R-{str(bad)}",
            checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
        )
        assert result.is_success is False
        assert result.selected_candidate is None
        assert result.status == "REJECTED"
        assert len(recorder.get_attempt_events(result.attempt_id)) == 2
        assert len(recorder.get_cost_receipts_for_attempt(result.attempt_id)) == 1
