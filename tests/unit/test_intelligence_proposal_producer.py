"""Unit tests for scripted AI proposal producer and output failure handling.

Verifies acceptance criteria T07, T09 from research.md and DP-R3/DP-R4:
- T07: Output failure handling (malformed JSON, bad weights, out-of-envelope).
- T09: All attempts and attempts-to-candidate links retained.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from drift.intelligence.contracts import (
    ArtifactReference,
    ResearchContext,
    StrategySelection,
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


def test_t09_positive_proposal_production(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    """T09: Valid structured proposal generates attempt and candidate links."""
    recorder = ResearchReceiptStore()
    raw_choice = fixture_data["raw_choice"]

    transport = FakeTransport(raw_choice=raw_choice)
    method_ref = ArtifactReference(id="method:scripted", version="v1", sha256="a" * 64)
    val_policy = ArtifactReference(id="policy:standard", version="v1", sha256="b" * 64)

    res = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=method_ref,
        validation_policy=val_policy,
        recorder=recorder,
        transport=transport,
        attempt_id="att-pos-001",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )

    assert res.is_success is True
    assert res.status == "VALID"
    assert res.candidate is not None
    assert res.candidate.disposition == "propose"

    # Verify attempt retention (T09)
    events = recorder.get_attempt_events("att-pos-001")
    assert len(events) == 2
    assert events[0].status == "started"
    assert events[1].status == "completed"
    assert events[1].candidate_ref is not None
    assert events[1].candidate_ref.id == res.candidate.candidate_id

    # Verify cost receipt
    costs = recorder.get_cost_receipts_for_attempt("att-pos-001")
    assert len(costs) == 1
    assert costs[0].amount_basis == "verified_zero"


def test_t07_malformed_json_failure(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """T07: Malformed output produces failed attempt record without candidate."""
    recorder = ResearchReceiptStore()
    transport = FakeTransport(malformed_json="Broken payload {")

    res = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="method:scripted", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="b" * 64
        ),
        recorder=recorder,
        transport=transport,
        attempt_id="att-malformed-001",
    )

    assert res.is_success is False
    assert res.status == "MALFORMED_OUTPUT"
    assert res.candidate is None

    events = recorder.get_attempt_events("att-malformed-001")
    assert len(events) == 2
    assert events[1].status == "failed"
    assert "MALFORMED_OUTPUT" in events[1].reason_codes


def test_t07_bad_weights_rejection(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """T07: Invalid weights sum fails closed with rejected attempt and cost."""
    recorder = ResearchReceiptStore()
    bad_weights_choice = {
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
            }
        ],
        "cash_weight": "0.2",  # Sums to 0.5 != 1.0
        "evidence_ids": [],
        "rationale": "Invalid sum",
        "reason_codes": [],
    }

    transport = FakeTransport(raw_choice=bad_weights_choice)
    res = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="method:scripted", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="b" * 64
        ),
        recorder=recorder,
        transport=transport,
        attempt_id="att-bad-weights-001",
    )

    assert res.is_success is False
    assert res.status == "INVALID"
    assert "weights sum" in (res.reason or "")

    events = recorder.get_attempt_events("att-bad-weights-001")
    assert len(events) == 2
    assert events[1].status == "failed"

    # Incurred work and cost still retained (T10)
    costs = recorder.get_cost_receipts_for_attempt("att-bad-weights-001")
    assert len(costs) == 1


def test_t07_timeout_failure(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """T07: Transport timeout yields failed attempt and unknown cost receipt."""
    recorder = ResearchReceiptStore()
    transport = FakeTransport(should_timeout=True)

    res = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="method:scripted", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="b" * 64
        ),
        recorder=recorder,
        transport=transport,
        attempt_id="att-timeout-001",
    )

    assert res.is_success is False
    assert res.status == "TIMEOUT"

    events = recorder.get_attempt_events("att-timeout-001")
    assert len(events) == 2
    assert events[1].status == "failed"
    assert "TIMEOUT" in events[1].reason_codes

    costs = recorder.get_cost_receipts_for_attempt("att-timeout-001")
    assert len(costs) == 1
    assert costs[0].amount_basis == "unknown"


def test_scripted_nonzero_cost_is_an_estimate_not_an_actual_bill(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    store = ResearchReceiptStore()
    result = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="synthetic:method", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="b" * 64
        ),
        recorder=store,
        transport=FakeTransport(
            raw_choice=fixture_data["raw_choice"], cost_amount="0.17"
        ),
        attempt_id="synthetic-estimated-cost",
        checked_at=at,
    )
    assert result.is_success
    costs = store.get_cost_receipts_for_attempt(result.attempt_id)
    assert len(costs) == 1
    assert costs[0].amount_basis == "estimate"
    assert costs[0].amount == "0.17"
    assert costs[0].billing_identity == "scripted_offline"


def test_malformed_response_also_records_cost_and_terminal_receipt(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    store = ResearchReceiptStore()
    result = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="synthetic:method", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="b" * 64
        ),
        recorder=store,
        transport=FakeTransport(
            malformed_json="{malformed", cost_amount="0.21"
        ),
        attempt_id="synthetic-malformed-billed",
    )
    assert result.status == "MALFORMED_OUTPUT"
    assert result.candidate is None
    assert [e.status for e in store.get_attempt_events(result.attempt_id)] == [
        "started", "failed"
    ]
    costs = store.get_cost_receipts_for_attempt(result.attempt_id)
    assert len(costs) == 1
    assert costs[0].amount_basis == "estimate"
    assert costs[0].amount == "0.21"


def test_identical_scripted_replay_retains_identical_candidate_and_event_hashes(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
) -> None:
    at = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)
    def run() -> tuple[str, str, tuple[str, ...]]:
        store = ResearchReceiptStore()
        result = produce_proposal(
            context=sample_context,
            resolved_inputs=sample_bindings,
            frozen_method=ArtifactReference(
                id="synthetic:method", version="v1", sha256="a" * 64
            ),
            validation_policy=ArtifactReference(
                id="synthetic:policy", version="v1", sha256="b" * 64
            ),
            recorder=store,
            transport=FakeTransport(raw_choice=fixture_data["raw_choice"]),
            attempt_id="synthetic-repeatable",
            checked_at=at,
        )
        assert result.is_success and result.candidate is not None
        return (
            result.attempt_id,
            result.candidate.record_hash,
            tuple(e.record_hash for e in store.get_attempt_events(result.attempt_id)),
        )
    assert run() == run()


def test_scripted_minimal_abstention_uses_typed_output_binding(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """Omitting optional JSON keys cannot break a valid abstention receipt."""
    store = ResearchReceiptStore()
    result = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="method:scripted", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="b" * 64
        ),
        recorder=store,
        transport=FakeTransport(
            raw_choice={"disposition": "abstain", "rationale": "Insufficient signal"}
        ),
        attempt_id="synthetic-minimal-abstain",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )
    assert result.is_success
    assert result.status == "VALID"
    assert result.candidate is not None
    assert result.candidate.disposition == "abstain"
    assert result.candidate.targets == ()
    assert len(store.get_attempt_events(result.attempt_id)) == 2
    assert len(store.get_cost_receipts_for_attempt(result.attempt_id)) == 1



@pytest.mark.parametrize("invalid_param", [float("nan"), object()])
def test_noncanonical_scripted_output_retains_failure_and_cost(
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    fixture_data: dict[str, Any],
    invalid_param: object,
) -> None:
    """A failed serializer must not strand a billed attempt in started status."""
    raw_choice = json.loads(json.dumps(fixture_data["raw_choice"]))
    raw_choice["selection"]["parameters"] = {"unsafe": invalid_param}
    recorder = ResearchReceiptStore()
    result = produce_proposal(
        context=sample_context,
        resolved_inputs=sample_bindings,
        frozen_method=ArtifactReference(
            id="synthetic:method", version="v1", sha256="a" * 64
        ),
        validation_policy=ArtifactReference(
            id="synthetic:policy", version="v1", sha256="b" * 64
        ),
        recorder=recorder,
        transport=FakeTransport(raw_choice=raw_choice, cost_amount="0.20"),
        attempt_id="synthetic:invalid-parameter",
        checked_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
    )
    assert result.status == "INVALID"
    assert result.candidate is None
    assert [event.status for event in recorder.get_attempt_events(result.attempt_id)] == [
        "started", "failed",
    ]
    costs = recorder.get_cost_receipts_for_attempt(result.attempt_id)
    assert len(costs) == 1
    assert costs[0].amount_basis == "estimate"
    assert costs[0].amount == "0.20"
