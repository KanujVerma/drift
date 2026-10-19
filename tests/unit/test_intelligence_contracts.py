"""Unit tests for immutable intelligence contracts and wire schemas.

Verifies F01-F08 fixture deserialization, canonical record hashing, immutability,
and strict schema enforcement under the 'drift-research/1-draft' profile.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from drift.intelligence.contracts import (
    ArtifactReference,
    AttemptRecord,
    CostReceipt,
    ModelReplayRecord,
    ResearchCandidate,
    ResearchContext,
    TargetWeight,
    compute_record_hash,
)

FIXTURES_PATH = Path("tests/fixtures/adaptive_research/research_v1.json")


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, Any]:
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


def test_f01_research_context_deserialization(
    fixture_data: dict[str, Any],
) -> None:
    f01 = fixture_data["fixtures"]["F01"]
    ctx = ResearchContext.model_validate(f01)
    assert ctx.profile == "drift-research/1-draft"
    assert ctx.kind == "context"
    assert ctx.context_id == "01900000-0000-7000-8000-000000000001"
    assert ctx.scope.arm_id == "fixture:B"
    assert ctx.record_hash == compute_record_hash(ctx)


def test_f02_research_candidate_deserialization(
    fixture_data: dict[str, Any],
) -> None:
    f02 = fixture_data["fixtures"]["F02"]
    cand = ResearchCandidate.model_validate(f02)
    assert cand.profile == "drift-research/1-draft"
    assert cand.kind == "candidate"
    assert cand.disposition == "propose"
    assert cand.cash_weight == "0.4"
    assert len(cand.targets) == 2
    assert cand.record_hash == compute_record_hash(cand)


def test_f03_abstention_deserialization(fixture_data: dict[str, Any]) -> None:
    f03 = fixture_data["fixtures"]["F03"]
    abstain = ResearchCandidate.model_validate(f03)
    assert abstain.disposition == "abstain"
    assert abstain.strategy is None
    assert len(abstain.targets) == 0
    assert abstain.cash_weight is None
    assert abstain.record_hash == compute_record_hash(abstain)


def test_f04_f05_attempt_lifecycle_deserialization(
    fixture_data: dict[str, Any],
) -> None:
    f04 = fixture_data["fixtures"]["F04"]
    f05 = fixture_data["fixtures"]["F05"]
    att_start = AttemptRecord.model_validate(f04)
    att_end = AttemptRecord.model_validate(f05)

    assert att_start.status == "started"
    assert att_start.event_index == 0
    assert att_start.previous_event_ref is None

    assert att_end.status == "completed"
    assert att_end.event_index == 1
    assert att_end.previous_event_ref is not None
    assert att_end.previous_event_ref.sha256 == att_start.record_hash


def test_f06_f07_cost_receipts_deserialization(
    fixture_data: dict[str, Any],
) -> None:
    f06 = fixture_data["fixtures"]["F06"]
    f07 = fixture_data["fixtures"]["F07"]
    cost_zero = CostReceipt.model_validate(f06)
    cost_unknown = CostReceipt.model_validate(f07)

    assert cost_zero.amount_basis == "verified_zero"
    assert cost_zero.amount == "0"
    assert cost_zero.currency == "USD"

    assert cost_unknown.amount_basis == "unknown"
    assert cost_unknown.amount is None
    assert cost_unknown.currency is None
    assert cost_unknown.unknown_reason is not None


def test_f08_model_replay_deserialization(fixture_data: dict[str, Any]) -> None:
    f08 = fixture_data["fixtures"]["F08"]
    replay = ModelReplayRecord.model_validate(f08)
    assert replay.kind == "model_replay"
    assert replay.finish_reason == "timeout"
    assert replay.record_hash == compute_record_hash(replay)


def test_immutability_enforced(fixture_data: dict[str, Any]) -> None:
    f01 = fixture_data["fixtures"]["F01"]
    ctx = ResearchContext.model_validate(f01)
    with pytest.raises(ValidationError):
        ctx.review_reason = "tampered"


def test_extra_keys_forbidden(fixture_data: dict[str, Any]) -> None:
    f01 = dict(fixture_data["fixtures"]["F01"])
    f01["extra_malicious_key"] = "payload"
    with pytest.raises(ValidationError) as exc:
        ResearchContext.model_validate(f01)
    assert "extra_forbidden" in str(exc.value)


def test_target_weight_validation() -> None:
    # Valid DecimalText
    tw = TargetWeight(security_id="01900000-0000-7000-8000-000000000101", weight="0.5")
    assert tw.weight == "0.5"

    # Float is rejected
    with pytest.raises(ValidationError) as exc:
        TargetWeight(security_id="sec-1", weight=0.5)  # type: ignore[arg-type]
    assert "JSON float is not Weight" in str(exc.value)

    # Scientific notation rejected
    with pytest.raises(ValidationError) as exc:
        TargetWeight(security_id="sec-1", weight="1e-1")
    assert "Scientific notation forbidden" in str(exc.value)

    # Out of bounds rejected
    with pytest.raises(ValidationError) as exc:
        TargetWeight(security_id="sec-1", weight="1.5")
    assert "between 0.0 and 1.0" in str(exc.value)


def test_artifact_reference_validation() -> None:
    # 64-char valid hex
    ref = ArtifactReference(id="ref-1", version="v1", sha256="a" * 64)
    assert ref.sha256 == "a" * 64

    # Invalid length
    with pytest.raises(ValidationError):
        ArtifactReference(id="ref-1", version="v1", sha256="abc")

    # Invalid uppercase/non-hex
    with pytest.raises(ValidationError):
        ArtifactReference(id="ref-1", version="v1", sha256="Z" * 64)


def test_rehashed_context_cannot_promote_synthetic_source(
    fixture_data: dict[str, Any],
) -> None:
    """Only a separately qualified source lane can create promotion evidence."""
    forged = dict(fixture_data["fixtures"]["F01"])
    forged["source_grade"] = "promotion_grade"
    forged["record_hash"] = compute_record_hash(forged)
    with pytest.raises(ValueError):
        ResearchContext.model_validate(forged)


def test_exploratory_context_must_acknowledge_limitations(
    fixture_data: dict[str, Any],
) -> None:
    changed = dict(fixture_data["fixtures"]["F01"])
    changed["source_grade"] = "exploratory"
    changed["limitations"] = []
    changed["record_hash"] = compute_record_hash(changed)
    with pytest.raises(ValueError, match="EXPLORATORY_LIMITATIONS_REQUIRED"):
        ResearchContext.model_validate(changed)
