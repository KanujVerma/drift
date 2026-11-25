"""Unit tests for conventional candidate selector, optimizer R seam, and controls (T13).

Verifies acceptance criteria T07, T09, T13 from research.md and DP-R6:
- Conventional selection over finite candidate pool with deterministic tie-breaking.
- Handling empty/all-rejected candidate pool.
- T13: AI and R share identical context refs with isolated mutable state.
"""

import json
import random
from copy import deepcopy
from datetime import UTC, datetime
from decimal import (
    MAX_EMAX,
    MIN_ETINY,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    getcontext,
    localcontext,
)
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from drift.intelligence._exact_decimal import within_selector_band
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

        def constant_score(
            _candidate: ResearchCandidate, score: Decimal = bad
        ) -> Decimal:
            return score

        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=[fixture_data["raw_choice"]],
            objective_fn=constant_score,
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


def test_r_score_decimal_subclass_cannot_override_comparison(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    class HostileDecimal(Decimal):
        def is_finite(self) -> bool:
            return True

        def __sub__(self, other: object) -> Decimal:
            raise AssertionError("subclass arithmetic used")

    store = ResearchReceiptStore()
    result = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[fixture_data["raw_choice"]],
        objective_fn=lambda _: HostileDecimal("NaN"),
        method_ref=ArtifactReference(id="synthetic:R", version="v1", sha256="e" * 64),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="f" * 64
        ),
        recorder=store,
        attempt_id="synthetic:hostile-decimal",
    )
    assert result.status == "REJECTED"
    assert result.reason == "INVALID_OBJECTIVE_SCORE"
    assert [event.status for event in store.get_attempt_events(result.attempt_id)] == [
        "started",
        "rejected",
    ]


def test_r_finite_decimal_subclass_is_normalized_before_use(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    class HostileDecimal(Decimal):
        def __str__(self) -> str:
            raise AssertionError("subclass string conversion used")

        def __sub__(self, other: object) -> Decimal:
            raise AssertionError("subclass arithmetic used")

        def is_finite(self) -> bool:
            raise AssertionError("subclass predicate used")

    store = ResearchReceiptStore()
    result = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=sample_bindings,
        candidate_pool=[fixture_data["raw_choice"]],
        objective_fn=lambda _: HostileDecimal("1"),
        method_ref=ArtifactReference(id="synthetic:R", version="v1", sha256="e" * 64),
        validation_policy=ArtifactReference(id="policy", version="v1", sha256="f" * 64),
        recorder=store,
        attempt_id="synthetic:hostile-finite-decimal",
    )
    assert result.is_success
    assert list(result.candidate_scores.values()) == ["1"]


def test_exact_band_matches_fraction_oracle() -> None:
    rng = random.Random(469)
    tolerance = Fraction(1, 10**9)
    for _ in range(5000):
        a = Decimal(
            (
                rng.randrange(2),
                tuple(map(int, str(rng.randrange(10**12)))),
                rng.randrange(-25, 10),
            )
        )
        b = Decimal(
            (
                rng.randrange(2),
                tuple(map(int, str(rng.randrange(10**12)))),
                rng.randrange(-25, 10),
            )
        )
        maximum, score = max(a, b), min(a, b)
        assert within_selector_band(maximum, score) == (
            Fraction(maximum) - Fraction(score) <= tolerance
        )
    for _ in range(5000):
        base = rng.randrange(-100000, 100000)
        delta = rng.randrange(-10000, 10001)
        maximum = Decimal((int(base < 0), tuple(map(int, str(abs(base)))), -5))
        # Construct the exact lower value using integer arithmetic at 1e-14.
        low_units = base * 10**9 - (100000 + delta)
        score = Decimal((int(low_units < 0), tuple(map(int, str(abs(low_units)))), -14))
        assert within_selector_band(maximum, score) == (
            Fraction(maximum) - Fraction(score) <= tolerance
        )


@pytest.mark.parametrize(
    ("maximum", "score", "expected"),
    [
        ("1e-9", "-1e-999999999", False),
        ("1e-9", "-0", True),
        ("0", "-1e-999999999", True),
        ("1e999999999", "-1e999999999", False),
        (f"9e{MAX_EMAX}", f"-9e{MAX_EMAX}", False),
        ("0", f"-1e{MIN_ETINY}", True),
        ("0", "-0", True),
    ],
)
def test_exact_band_extreme_exponents_and_flags(
    maximum: str, score: str, expected: bool
) -> None:
    context = Context(
        prec=1, Emin=-3, Emax=3, flags=[Rounded], traps=[Inexact, Rounded]
    )
    with localcontext(context) as active:
        before = active.copy()
        assert within_selector_band(Decimal(maximum), Decimal(score)) is expected
        assert active.flags == before.flags
        assert active.traps == before.traps


@pytest.mark.parametrize("reverse", [False, True])
def test_r_invalid_exact_weight_refuses_whole_pool_before_scoring(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
    reverse: bool,
) -> None:
    good = deepcopy(fixture_data["raw_choice"])
    bad = deepcopy(good)
    bad["targets"][0]["weight"] = "0.29999999999999999999"
    pool = [bad, good] if reverse else [good, bad]
    seen: list[str] = []
    store = ResearchReceiptStore()

    def score(candidate: ResearchCandidate) -> Decimal:
        seen.append(candidate.candidate_id)
        return Decimal(1)

    with localcontext(Context(prec=9, traps=[Inexact, Rounded])) as active:
        before = active.copy()
        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=pool,
            objective_fn=score,
            method_ref=ArtifactReference(
                id="synthetic:R", version="v1", sha256="e" * 64
            ),
            validation_policy=ArtifactReference(
                id="policy", version="v1", sha256="f" * 64
            ),
            recorder=store,
            attempt_id="synthetic:exact-weight-refusal",
        )
        assert active.flags == before.flags
    assert result.reason == "INVALID_CANDIDATE_POOL_MEMBER"
    assert result.selected_candidate is None and result.candidate_scores == {}
    assert seen == []
    events = store.get_attempt_events(result.attempt_id)
    assert [event.status for event in events] == ["started", "rejected"]
    costs = store.get_cost_receipts_for_attempt(result.attempt_id)
    assert len(costs) == 1 and events[-1].cost_receipt_ids == (costs[0].receipt_id,)


def test_r_callback_context_changes_do_not_change_band_comparison(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    choices = [deepcopy(fixture_data["raw_choice"]) for _ in range(2)]
    choices[0]["rationale"] = "higher"
    choices[1]["rationale"] = "lower"
    store = ResearchReceiptStore()

    def score(candidate: ResearchCandidate) -> Decimal:
        getcontext().prec = 1
        getcontext().traps[Inexact] = True
        return (
            Decimal("1")
            if candidate.rationale == "higher"
            else Decimal("0.99999999899999999999")
        )

    with localcontext(Context(prec=28)) as active:
        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=sample_bindings,
            candidate_pool=choices,
            objective_fn=score,
            method_ref=ArtifactReference(
                id="synthetic:R", version="v1", sha256="e" * 64
            ),
            validation_policy=ArtifactReference(
                id="policy", version="v1", sha256="f" * 64
            ),
            recorder=store,
            attempt_id="synthetic:context-changing-callback",
        )
        # The selector isolates its own arithmetic; it does not sandbox callbacks.
        assert active.prec == 1 and active.traps[Inexact]
    assert result.selected_candidate is not None
    assert result.selected_candidate.rationale == "higher"
    assert [event.status for event in store.get_attempt_events(result.attempt_id)] == [
        "started",
        "completed",
    ]


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

        def objective(
            candidate: ResearchCandidate, collector: list[str] = scores_seen
        ) -> Decimal:
            collector.append(candidate.candidate_id)
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


def test_r_nonzero_score_gaps_respect_tie_band_and_parameter_hash(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """The DP-R6 band uses parameter identity before candidate ID or order."""
    original_context = getcontext()
    original_state = original_context.copy()

    def assert_context_restored(expected: Context, snapshot: Context) -> None:
        actual = getcontext()
        assert actual is expected
        assert actual.prec == snapshot.prec
        assert actual.rounding == snapshot.rounding
        assert actual.Emin == snapshot.Emin
        assert actual.Emax == snapshot.Emax
        assert actual.capitals == snapshot.capitals
        assert actual.clamp == snapshot.clamp
        assert actual.flags == snapshot.flags
        assert actual.traps == snapshot.traps

    selector_context = Context(
        prec=28,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Inexact, Rounded],
    )
    adversarial_contexts = (
        Context(
            prec=28,
            rounding=ROUND_HALF_EVEN,
            Emin=-999999,
            Emax=999999,
            capitals=1,
            clamp=0,
            flags=[Inexact],
            traps=[Inexact, Rounded],
        ),
        Context(
            prec=9,
            rounding=ROUND_HALF_EVEN,
            Emin=-3,
            Emax=3,
            capitals=0,
            clamp=1,
            flags=[Rounded],
            traps=[Inexact, Rounded],
        ),
    )
    for adversarial in adversarial_contexts:
        with localcontext(adversarial) as ambient_context:
            ambient_state = ambient_context.copy()
            with localcontext(selector_context) as active_context:
                _assert_r_nonzero_score_gaps(
                    sample_context, sample_bindings, fixture_data
                )
                assert getcontext() is active_context
            assert_context_restored(ambient_context, ambient_state)
    assert_context_restored(original_context, original_state)


def _assert_r_nonzero_score_gaps(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
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

    def observe(candidate: ResearchCandidate) -> Decimal:
        observed.append(candidate)
        return Decimal("1")

    probe = select_conventional_candidate(
        context=sample_context,
        resolved_inputs=resolved,
        candidate_pool=choices,
        objective_fn=observe,
        method_ref=method,
        validation_policy=policy,
        recorder=ResearchReceiptStore(),
        attempt_id="synthetic:nonzero-parameter-tie",
        checked_at=cutoff,
    )
    assert probe.is_success and len(observed) == len(choices)
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
    hash_winner, score_winner = inversion
    assert hash_winner.strategy is not None and score_winner.strategy is not None
    hash_number = hash_winner.strategy.parameters["choice_number"]
    score_number = score_winner.strategy.parameters["choice_number"]

    selector_context = getcontext()
    demonstration_context = Context(
        prec=9,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[],
    )
    with localcontext(demonstration_context) as low_context:
        # Without isolation the inside-band score rounds to an exact tie.
        assert Decimal("1") - Decimal("0.0000000005") == Decimal("1")
        assert low_context.flags[Inexact] and low_context.flags[Rounded]
    assert getcontext() is selector_context
    for gap, exact_lower_score, expected in (
        (Decimal("0.0000000005"), Decimal("0.9999999995"), hash_winner),
        (Decimal("0.000000001"), Decimal("0.999999999"), hash_winner),
        (Decimal("0.000000002"), Decimal("0.999999998"), score_winner),
    ):

        def score(candidate: ResearchCandidate, gap_value: Decimal = gap) -> Decimal:
            assert candidate.strategy is not None
            if candidate.strategy.parameters["choice_number"] == hash_number:
                return Decimal("1") - gap_value
            assert candidate.strategy.parameters["choice_number"] == score_number
            return Decimal("1")

        for pair in (
            (choices[hash_number], choices[score_number]),
            (choices[score_number], choices[hash_number]),
        ):
            result = select_conventional_candidate(
                context=sample_context,
                resolved_inputs=resolved,
                candidate_pool=pair,
                objective_fn=score,
                method_ref=method,
                validation_policy=policy,
                recorder=ResearchReceiptStore(),
                attempt_id="synthetic:nonzero-parameter-tie",
                checked_at=cutoff,
            )
            assert result.is_success and result.selected_candidate is not None
            assert (
                Decimal(result.candidate_scores[hash_winner.candidate_id])
                == exact_lower_score
            )
            assert result.candidate_scores[score_winner.candidate_id] == "1"
            assert result.selected_candidate.candidate_id == expected.candidate_id


@pytest.mark.parametrize("precision", [9, 28])
@pytest.mark.parametrize("reverse_pool", [False, True])
@pytest.mark.parametrize(
    ("lower_score", "expected_number"),
    [
        (Decimal("0.999999999"), 1),
        (Decimal("0.9999999989999999999999"), 0),
    ],
    ids=["inclusive-boundary", "just-outside"],
)
def test_r_tie_boundary_is_independent_of_decimal_precision(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
    precision: int,
    reverse_pool: bool,
    lower_score: Decimal,
    expected_number: int,
) -> None:
    """Compare exact scores against the inclusive band from the maximum."""
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
    for number in (0, 1):
        choice = deepcopy(fixture_data["raw_choice"])
        choice["selection"]["parameters"] = {"choice_number": number}
        choices.append(choice)
    if reverse_pool:
        choices.reverse()

    seen: dict[int, ResearchCandidate] = {}

    def score(candidate: ResearchCandidate) -> Decimal:
        assert candidate.strategy is not None
        number = candidate.strategy.parameters["choice_number"]
        seen[number] = candidate
        return lower_score if number == 1 else Decimal("1")

    recorder = ResearchReceiptStore()
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_EVEN, traps=[])):
        result = select_conventional_candidate(
            context=sample_context,
            resolved_inputs=resolved,
            candidate_pool=choices,
            objective_fn=score,
            method_ref=ArtifactReference(
                id="synthetic:method-R", version="v1", sha256="e" * 64
            ),
            validation_policy=ArtifactReference(
                id="synthetic:policy", version="v1", sha256="f" * 64
            ),
            recorder=recorder,
            checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
        )

    assert result.is_success and result.selected_candidate is not None, result.reason
    assert set(seen) == {0, 1}
    assert seen[0].strategy is not None and seen[1].strategy is not None
    # Hash order favors the lower score, so a false tie changes the winner.
    assert seen[1].strategy.parameters_hash < seen[0].strategy.parameters_hash
    assert result.candidate_scores[seen[0].candidate_id] == "1"
    assert result.candidate_scores[seen[1].candidate_id] == str(lower_score)
    events = recorder.get_attempt_events(result.attempt_id)
    assert [event.status for event in events] == ["started", "completed"]
    assert events[-1].candidate_ref is not None
    assert events[-1].candidate_ref.id == result.selected_candidate.candidate_id
    costs = recorder.get_cost_receipts_for_attempt(result.attempt_id)
    assert len(costs) == 1 and costs[0].amount_basis == "verified_zero"
    assert result.selected_candidate.candidate_id == seen[expected_number].candidate_id


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
