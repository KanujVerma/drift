"""Unit tests for offline deterministic model replay runtime without network access.

Verifies acceptance criteria T06 from research.md and DP-R4:
- Positive deterministic replay matching candidate validation and replay provenance.
- Timeout call replay producing valid failure record.
- Negative digests and malformed response JSON refusal (MR_N01 to MR_N03).
- Zero network calls during offline replay.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from drift.intelligence.contracts import (
    ArtifactReference,
    ResearchContext,
    StoredArtifactRef,
    StrategySelection,
)
from drift.intelligence.model_replay import replay_model_output
from drift.intelligence.validation import (
    ResolvedDependencies,
    StrategyRegistration,
)

MODEL_REPLAY_FIXTURES = Path("tests/fixtures/adaptive_research/model_replay_v1.json")
RESEARCH_FIXTURES = Path("tests/fixtures/adaptive_research/research_v1.json")


@pytest.fixture(scope="module")
def replay_fixtures() -> dict[str, Any]:
    with open(MODEL_REPLAY_FIXTURES, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


@pytest.fixture(scope="module")
def sample_context() -> ResearchContext:
    with open(RESEARCH_FIXTURES, encoding="utf-8") as f:
        data = json.load(f)
    return ResearchContext.model_validate(data["fixtures"]["F01"])


@pytest.fixture(scope="module")
def sample_bindings(sample_context: ResearchContext) -> ResolvedDependencies:
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


def test_t06_positive_model_replay_and_zero_network(
    replay_fixtures: dict[str, Any],
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """T06: Positive offline model replay succeeds with zero network calls."""
    pos = replay_fixtures["positive_replay"]
    req = pos["request"]
    resp = pos["response"]

    now = datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC)

    # Patch socket to guarantee zero network calls
    with patch("socket.socket") as mock_sock:
        res = replay_model_output(
            recorded_request=StoredArtifactRef(
                artifact_id="req-art-01",
                kind="other",
                content_hash=req["content_hash"],
                location=req["location"],
            ),
            recorded_response=StoredArtifactRef(
                artifact_id="resp-art-01",
                kind="other",
                content_hash=resp["content_hash"],
                location=resp["location"],
            ),
            request_payload=req["payload"],
            response_payload=resp["payload"],
            original_context=sample_context,
            original_bindings=sample_bindings,
            adapter_revision=ArtifactReference(
                id="adapter:offline", version="v1", sha256="a" * 64
            ),
            parser_schema_ref=ArtifactReference(
                id="schema:raw-choice", version="v1", sha256="b" * 64
            ),
            validation_policy=ArtifactReference(
                id="policy:standard", version="v1", sha256="c" * 64
            ),
            attempt_id="att-replay-001",
            checked_at=now,
        )
        assert mock_sock.call_count == 0

    assert res.is_success is True
    assert res.status == "VALID"
    assert res.candidate is not None
    assert res.candidate.disposition == "propose"
    assert res.candidate.cash_weight == "0.4"
    assert len(res.candidate.targets) == 2
    assert res.replay_record is not None
    assert res.replay_record.finish_reason == "stop"
    assert res.replay_record.mode == "offline_deterministic"


def test_t06_timeout_model_replay(
    replay_fixtures: dict[str, Any],
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
) -> None:
    """T06: Timeout call produces valid timeout replay record without response."""
    timeout_data = replay_fixtures["timeout_replay"]
    req = timeout_data["request"]

    res = replay_model_output(
        recorded_request=StoredArtifactRef(
            artifact_id="req-art-01",
            kind="other",
            content_hash=req["content_hash"],
            location=req["location"],
        ),
        recorded_response=None,
        request_payload=req["payload"],
        response_payload=None,
        original_context=sample_context,
        original_bindings=sample_bindings,
        adapter_revision=ArtifactReference(
            id="adapter:offline", version="v1", sha256="a" * 64
        ),
        parser_schema_ref=ArtifactReference(
            id="schema:raw-choice", version="v1", sha256="b" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="c" * 64
        ),
        attempt_id="att-timeout-001",
    )

    assert res.is_success is False
    assert res.status == "TIMEOUT"
    assert res.candidate is None
    assert res.replay_record is not None
    assert res.replay_record.finish_reason == "timeout"


@pytest.mark.parametrize("case_index", range(3))
def test_t06_negative_replay_cases(
    replay_fixtures: dict[str, Any],
    sample_context: ResearchContext,
    sample_bindings: ResolvedDependencies,
    case_index: int,
) -> None:
    """T06: Verify corrupted hashes and malformed JSON fail closed."""
    case = replay_fixtures["negative_cases"][case_index]
    req = case["request"]
    resp = case["response"]
    exp_status = case["expected_status"]
    exp_reason = case["expected_reason"]

    res = replay_model_output(
        recorded_request=StoredArtifactRef(
            artifact_id="req-art-neg",
            kind="other",
            content_hash=req["content_hash"],
            location=req["location"],
        ),
        recorded_response=StoredArtifactRef(
            artifact_id="resp-art-neg",
            kind="other",
            content_hash=resp["content_hash"],
            location=resp["location"],
        ),
        request_payload=req["payload"],
        response_payload=resp["payload"],
        original_context=sample_context,
        original_bindings=sample_bindings,
        adapter_revision=ArtifactReference(
            id="adapter:offline", version="v1", sha256="a" * 64
        ),
        parser_schema_ref=ArtifactReference(
            id="schema:raw-choice", version="v1", sha256="b" * 64
        ),
        validation_policy=ArtifactReference(
            id="policy:standard", version="v1", sha256="c" * 64
        ),
        attempt_id=f"att-neg-{case['case']}",
    )

    assert res.is_success is False
    assert res.status == exp_status
    assert res.reason is not None
    assert exp_reason in res.reason
