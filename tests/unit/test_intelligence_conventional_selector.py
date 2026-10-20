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
    assert events[0].budget_ref == sample_context.budget_ref
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
            method_ref=ArtifactReference(id="method:R", version="v1", sha256="e" * 64),
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


def test_conventional_pool_rejects_semantically_duplicate_optional_fields(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """An omitted optional key is not a distinct candidate in a frozen pool."""
    explicit = deepcopy(fixture_data["raw_choice"])
    shortened = deepcopy(explicit)
    shortened.pop("evidence_ids", None)
    shortened.pop("reason_codes", None)
    recorder = ResearchReceiptStore()
    result = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[explicit, shortened],
        objective_fn=lambda _candidate: Decimal("1"),
        method_ref=ArtifactReference(id="method:R", version="v1", sha256="e" * 64),
        validation_policy=ArtifactReference(
            id="policy:fixed", version="v1", sha256="f" * 64
        ),
        recorder=recorder,
        attempt_id="semantic-duplicate-pool",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )
    assert result.status == "REJECTED"
    assert not result.is_success
    events = recorder.get_attempt_events(result.attempt_id)
    assert len(events) == 2
    assert "DUPLICATE_CANDIDATE_POOL_MEMBER" in events[-1].reason_codes


@pytest.mark.parametrize("invalid_param", [float("nan"), object()])
def test_noncanonical_pool_retains_explicit_attempt_and_cost(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
    invalid_param: object,
) -> None:
    """Invalid candidate bytes are never silently assigned a winning score."""
    bad = deepcopy(fixture_data["raw_choice"])
    bad["selection"]["parameters"] = {"unsafe": invalid_param}
    recorder = ResearchReceiptStore()
    result = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[bad],
        objective_fn=lambda _candidate: Decimal("1"),
        method_ref=ArtifactReference(
            id="synthetic:method", version="v1", sha256="e" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="f" * 64
        ),
        recorder=recorder,
        attempt_id="synthetic:noncanonical-pool",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )
    assert not result.is_success
    assert result.status == "REJECTED"
    assert result.selected_candidate is None
    events = recorder.get_attempt_events(result.attempt_id)
    assert [event.status for event in events] == ["started", "rejected"]
    assert "INVALID_CANDIDATE_POOL_SERIALIZATION" in events[-1].reason_codes
    assert len(recorder.get_cost_receipts_for_attempt(result.attempt_id)) == 1


def test_noncanonical_pool_without_explicit_attempt_id_cannot_claim_replay_identity(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """No invented stable hash for unknown opaque candidate objects."""
    bad = deepcopy(fixture_data["raw_choice"])
    bad["selection"]["parameters"] = {"unsafe": object()}
    recorder = ResearchReceiptStore()
    with pytest.raises(
        ValueError, match="NONCANONICAL_POOL_REQUIRES_EXPLICIT_ATTEMPT_ID"
    ):
        select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=[bad],
            objective_fn=lambda _candidate: Decimal("1"),
            method_ref=ArtifactReference(
                id="synthetic:method", version="v1", sha256="e" * 64
            ),
            validation_policy=ArtifactReference(
                id="synthetic:policy", version="v1", sha256="f" * 64
            ),
            recorder=recorder,
            checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
        )
    assert recorder.export_events() == []


def test_r_rejects_entire_pool_if_any_member_invalid(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """Do not silently drop invalid registered candidates and pick a winner."""
    valid = deepcopy(fixture_data["raw_choice"])
    invalid = deepcopy(valid)
    invalid["cash_weight"] = "0.9"
    invalid["targets"][0]["weight"] = "0.9"
    for index, pool in enumerate(([valid, invalid], [invalid, valid])):
        recorder = ResearchReceiptStore()
        scores_seen: list[str] = []

        def objective(candidate: ResearchCandidate) -> Decimal:
            scores_seen.append(candidate.candidate_id)
            return Decimal("1")

        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=pool,
            objective_fn=objective,
            method_ref=ArtifactReference(
                id="synthetic:method-R", version="v1", sha256="e" * 64
            ),
            validation_policy=ArtifactReference(
                id="synthetic:policy", version="v1", sha256="f" * 64
            ),
            recorder=recorder,
            attempt_id=f"whole-pool-refusal-{index}",
            checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
        )
        assert not result.is_success
        assert result.selected_candidate is None
        assert result.candidate_scores == {}
        events = recorder.get_attempt_events(result.attempt_id)
        assert [event.status for event in events] == ["started", "rejected"]
        assert "INVALID_CANDIDATE_POOL_MEMBER" in events[-1].reason_codes
        assert len(recorder.get_cost_receipts_for_attempt(result.attempt_id)) == 1
        assert len(scores_seen) <= 1


def test_r_tie_breaks_on_actual_parameter_digest(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """Two parameterizations sharing one code digest must rank by params."""
    registration = sample_bindings.strategy_registry["fixture.equal_weight"]
    resolved = sample_bindings.model_copy(
        update={
            "strategy_registry": {
                "fixture.equal_weight": registration.model_copy(
                    update={"allowed_parameters": {"choice_number": int}}
                )
            }
        }
    )
    choices = []
    for number in range(18):
        raw = deepcopy(fixture_data["raw_choice"])
        raw["selection"]["parameters"] = {"choice_number": number}
        choices.append(raw)

    method = ArtifactReference(id="synthetic:method-R", version="v1", sha256="e" * 64)
    policy = ArtifactReference(id="synthetic:policy", version="v1", sha256="f" * 64)
    cutoff = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    observed: list[ResearchCandidate] = []

    def remember(candidate: ResearchCandidate) -> Decimal:
        observed.append(candidate)
        return Decimal("7")

    probe = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=resolved,
        candidate_pool=choices,
        objective_fn=remember,
        method_ref=method,
        validation_policy=policy,
        recorder=ResearchReceiptStore(),
        attempt_id="synthetic:parameter-tie",
        checked_at=cutoff,
    )
    assert probe.is_success
    assert len(observed) == len(choices)
    inversion = next(
        (
            (a, b)
            for a in observed
            for b in observed
            if a.strategy is not None
            and b.strategy is not None
            and a.strategy.parameters_hash < b.strategy.parameters_hash
            and a.candidate_id > b.candidate_id
        ),
        None,
    )
    assert inversion is not None
    expected, other = inversion
    assert expected.strategy is not None
    assert other.strategy is not None
    expected_number = expected.strategy.parameters["choice_number"]
    other_number = other.strategy.parameters["choice_number"]

    for pair in (
        (choices[expected_number], choices[other_number]),
        (choices[other_number], choices[expected_number]),
    ):
        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=resolved,
            candidate_pool=pair,
            objective_fn=lambda _candidate: Decimal("7"),
            method_ref=method,
            validation_policy=policy,
            recorder=ResearchReceiptStore(),
            attempt_id="synthetic:parameter-tie",
            checked_at=cutoff,
        )
        assert result.is_success
        assert result.selected_candidate is not None
        assert result.selected_candidate.candidate_id == expected.candidate_id


def test_r_attempts_bind_policy_request_and_context_profile(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """Different invocations cannot alias one started/terminal/cost identity."""
    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    method = ArtifactReference(id="synthetic:method-R", version="v1", sha256="e" * 64)
    policy_a = ArtifactReference(id="synthetic:policy-A", version="v1", sha256="a" * 64)
    policy_b = ArtifactReference(id="synthetic:policy-B", version="v1", sha256="b" * 64)
    store = ResearchReceiptStore()

    def run(request: str, policy: ArtifactReference) -> str:
        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=[fixture_data["raw_choice"]],
            objective_fn=lambda _candidate: Decimal("1"),
            method_ref=method,
            validation_policy=policy,
            recorder=store,
            logical_request_id=request,
            checked_at=at,
        )
        assert result.is_success
        assert result.selected_candidate is not None
        events = store.get_attempt_events(result.attempt_id)
        assert [event.status for event in events] == ["started", "completed"]
        assert events[0].context_ref.version == sample_context.profile
        assert events[1].candidate_ref is not None
        assert events[1].candidate_ref.id == result.selected_candidate.candidate_id
        assert events[1].candidate_ref.version == result.selected_candidate.profile
        assert events[1].candidate_ref.sha256 == result.selected_candidate.record_hash
        assert len(store.get_cost_receipts_for_attempt(result.attempt_id)) == 1
        return result.attempt_id

    policy_new_version = ArtifactReference(
        id=policy_a.id, version="v2", sha256=policy_a.sha256
    )
    ids = [
        run("synthetic:request-A", policy_a),
        run("synthetic:request-B", policy_a),
        run("synthetic:request-A", policy_b),
        run("synthetic:request-A", policy_new_version),
    ]
    assert len(set(ids)) == 4
    # Idempotent identical replay does not mint a new cost or attempt chain.
    assert run("synthetic:request-A", policy_a) == ids[0]
    assert len(store.export_events()) == 12


def test_r_freezes_pool_before_objective_side_effects(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """Scoring cannot rewrite later pool choices under an old pool hash."""
    first = deepcopy(fixture_data["raw_choice"])
    second = deepcopy(first)
    second["targets"][0]["weight"] = "0.4"
    second["targets"][1]["weight"] = "0.4"
    second["cash_weight"] = "0.2"
    original_second = deepcopy(second)
    seen: list[str] = []

    def untrusted_score(candidate: ResearchCandidate) -> Decimal:
        seen.append(candidate.candidate_id)
        if len(seen) == 1:
            # A mutable caller-owned input changes only *after* the
            # predeclared and prevalidated pool was snapshotted.
            second["cash_weight"] = "0.99"
            second["targets"][0]["weight"] = "0.99"
            if candidate.strategy is not None and isinstance(
                candidate.strategy.parameters, dict
            ):
                candidate.strategy.parameters["untrusted_mutation"] = True
        return Decimal("1")

    recorder = ResearchReceiptStore()
    result = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[first, second],
        objective_fn=untrusted_score,
        method_ref=ArtifactReference(
            id="synthetic:method-R", version="v1", sha256="e" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="f" * 64
        ),
        recorder=recorder,
        attempt_id="synthetic:snapshot-side-effects",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )
    assert result.is_success
    assert result.selected_candidate is not None
    assert len(seen) == 2
    assert len(result.candidate_scores) == 2
    assert second != original_second
    assert all(
        event.status == expected
        for event, expected in zip(
            recorder.get_attempt_events(result.attempt_id),
            ("started", "completed"),
            strict=True,
        )
    )
    assert len(recorder.get_cost_receipts_for_attempt(result.attempt_id)) == 1
    # The retained, scored winner still passes intrinsic hash validation even
    # after the scoring callback tried to mutate its separate nested mapping.
    ResearchCandidate.model_validate(
        result.selected_candidate.model_dump(mode="python")
    )


def test_r_naive_ttl_rejected_without_incurred_attempt(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    recorder = ResearchReceiptStore()
    with pytest.raises(ValueError, match="INDETERMINATE_TIMEZONE"):
        select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=[fixture_data["raw_choice"]],
            objective_fn=lambda _candidate: Decimal("1"),
            method_ref=ArtifactReference(
                id="synthetic:method-R", version="v1", sha256="e" * 64
            ),
            validation_policy=ArtifactReference(
                id="synthetic:policy", version="v1", sha256="f" * 64
            ),
            recorder=recorder,
            checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
            valid_until=datetime(2024, 1, 2, 11, 0),
        )
    assert recorder.export_events() == []


def test_ai_and_r_attempt_stores_do_not_leak_across_arms(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """T13: identical context refs need not imply one mutable attempt store."""
    ai_store = ResearchReceiptStore()
    r_store = ResearchReceiptStore()
    now = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    ai = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="synthetic:AI", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="b" * 64
        ),
        recorder=ai_store,
        transport=FakeTransport(raw_choice=fixture_data["raw_choice"]),
        attempt_id="synthetic:ai-isolated",
        checked_at=now,
    )
    conventional = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[fixture_data["raw_choice"]],
        objective_fn=lambda _candidate: Decimal("1"),
        method_ref=ArtifactReference(id="synthetic:R", version="v1", sha256="e" * 64),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="f" * 64
        ),
        recorder=r_store,
        attempt_id="synthetic:r-isolated",
        checked_at=now,
    )
    assert ai.is_success and conventional.is_success
    ai_start = ai_store.get_attempt_events(ai.attempt_id)[0]
    r_start = r_store.get_attempt_events(conventional.attempt_id)[0]
    assert ai_start.context_ref.sha256 == sample_context.record_hash
    assert r_start.context_ref.sha256 == sample_context.record_hash
    assert ai_store.get_attempt_events(conventional.attempt_id) == ()
    assert r_store.get_attempt_events(ai.attempt_id) == ()
    assert len(ai_store.get_cost_receipts_for_attempt(ai.attempt_id)) == 1
    assert len(r_store.get_cost_receipts_for_attempt(conventional.attempt_id)) == 1


def test_r_opaque_pool_refuses_before_deepcopy_side_effects(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """Invalid opaque input cannot execute custom deepcopy code."""

    class DangerousInput:
        touched = False

        def __deepcopy__(self, memo: dict[int, object]) -> object:
            self.touched = True
            raise AssertionError("opaque input must not be copied")

    poisoned = DangerousInput()
    raw = deepcopy(fixture_data["raw_choice"])
    raw["selection"]["parameters"] = {"untrusted": poisoned}
    recorder = ResearchReceiptStore()
    result = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[raw],
        objective_fn=lambda _candidate: Decimal("1"),
        method_ref=ArtifactReference(
            id="synthetic:method-R", version="v1", sha256="e" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="f" * 64
        ),
        recorder=recorder,
        attempt_id="synthetic:opaque-pool",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )
    assert not poisoned.touched
    assert result.status == "REJECTED"
    assert result.selected_candidate is None
    events = recorder.get_attempt_events(result.attempt_id)
    assert [event.status for event in events] == ["started", "rejected"]
    assert len(recorder.get_cost_receipts_for_attempt(result.attempt_id)) == 1
