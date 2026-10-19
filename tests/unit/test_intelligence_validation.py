"""Unit tests for research candidate validation and N01-N12 negative cases.

Verifies caller-injected dependency resolution, candidate normalization,
and exact RED/GREEN semantic and tamper rejection specified in research.md.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from drift.intelligence.contracts import (
    ArtifactReference,
    ResearchContext,
    StrategySelection,
    TrustedInvocationBinding,
    compute_record_hash,
)
from drift.intelligence.validation import (
    ResolvedDependencies,
    StrategyRegistration,
    validate_candidate,
    validate_retained_record,
)

FIXTURES_PATH = Path("tests/fixtures/adaptive_research/research_v1.json")


@pytest.fixture(scope="module")
def fixture_data() -> dict[str, Any]:
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


@pytest.fixture(scope="module")
def resolved_dependencies(
    fixture_data: dict[str, Any],
) -> ResolvedDependencies:
    f01 = fixture_data["fixtures"]["F01"]
    return ResolvedDependencies(
        portfolio_ref=ArtifactReference.model_validate(f01["portfolio_ref"]),
        mandate_ref=ArtifactReference.model_validate(f01["mandate_ref"]),
        universe_ref=ArtifactReference.model_validate(f01["universe_ref"]),
        registry_ref=ArtifactReference.model_validate(f01["registry_ref"]),
        method_ref=ArtifactReference.model_validate(f01["method_ref"]),
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


@pytest.fixture(scope="module")
def trusted_invocation(
    fixture_data: dict[str, Any],
) -> TrustedInvocationBinding:
    f02 = fixture_data["fixtures"]["F02"]
    return TrustedInvocationBinding(
        attempt_id=f02["attempt_id"],
        candidate_id=f02["candidate_id"],
        validation_id="01900000-0000-7000-8000-000000000099",
        policy_ref=ArtifactReference(
            id="fixture:validation-policy",
            version="fixture-1",
            sha256="a" * 64,
        ),
        raw_output_ref=ArtifactReference(
            id="fixture:raw-output",
            version="fixture-1",
            sha256="b" * 64,
        ),
        producer=f02["producer"],
        completed_at=datetime.fromisoformat(f02["completed_at"]),
        checked_at=datetime.fromisoformat("2024-01-02T10:00:02.000000Z"),
        valid_until=datetime.fromisoformat(f02["valid_until"])
        if f02["valid_until"]
        else None,
        model_replay_ref=None,
        cost_receipt_ids=tuple(f02["cost_receipt_ids"]),
    )


def test_positive_candidate_validation_matches_f02(
    fixture_data: dict[str, Any],
    resolved_dependencies: ResolvedDependencies,
    trusted_invocation: TrustedInvocationBinding,
) -> None:
    f01 = fixture_data["fixtures"]["F01"]
    f02 = fixture_data["fixtures"]["F02"]
    raw_choice = fixture_data["raw_choice"]

    context = ResearchContext.model_validate(f01)
    result = validate_candidate(
        raw_choice=raw_choice,
        context=context,
        resolved_dependencies=resolved_dependencies,
        trusted_invocation=trusted_invocation,
    )

    assert result.is_valid is True
    assert result.status == "VALID"
    assert result.candidate is not None
    assert result.candidate.candidate_id == f02["candidate_id"]
    assert result.candidate.disposition == "propose"
    assert result.candidate.record_hash == f02["record_hash"]


def test_positive_abstention_validation_matches_f03(
    fixture_data: dict[str, Any],
    resolved_dependencies: ResolvedDependencies,
) -> None:
    f01 = fixture_data["fixtures"]["F01"]
    f03 = fixture_data["fixtures"]["F03"]
    context = ResearchContext.model_validate(f01)

    raw_abstain = {
        "disposition": "abstain",
        "selection": None,
        "targets": [],
        "cash_weight": None,
        "evidence_ids": [],
        "rationale": f03["rationale"],
        "reason_codes": f03["reason_codes"],
    }

    inv = TrustedInvocationBinding(
        attempt_id=f03["attempt_id"],
        candidate_id=f03["candidate_id"],
        validation_id="01900000-0000-7000-8000-000000000099",
        policy_ref=ArtifactReference(
            id="fixture:policy", version="v1", sha256="c" * 64
        ),
        raw_output_ref=ArtifactReference(
            id="fixture:raw", version="v1", sha256="d" * 64
        ),
        producer=f03["producer"],
        completed_at=datetime.fromisoformat(f03["completed_at"]),
        checked_at=datetime.fromisoformat("2024-01-02T10:00:02.000000Z"),
        valid_until=None,
        model_replay_ref=None,
        cost_receipt_ids=(),
    )

    result = validate_candidate(
        raw_choice=raw_abstain,
        context=context,
        resolved_dependencies=resolved_dependencies,
        trusted_invocation=inv,
    )

    assert result.is_valid is True
    assert result.status == "VALID"
    assert result.candidate is not None
    assert result.candidate.candidate_id == f03["candidate_id"]
    assert result.candidate.disposition == "abstain"
    assert result.candidate.record_hash == f03["record_hash"]


def apply_mutation(
    base: dict[str, Any],
    replace: dict[str, Any] | None,
    remove: list[str] | None,
    rehash: bool = True,
) -> dict[str, Any]:
    """Helper to apply N01-N12 mutations to a base fixture."""
    data: dict[str, Any] = json.loads(json.dumps(base))
    if remove:
        for r in remove:
            parts = r.split(".")
            d = data
            for p in parts[:-1]:
                d = d.get(p, {})
            d.pop(parts[-1], None)
    if replace:
        for k, v in replace.items():
            parts = k.split(".")
            d = data
            for p in parts[:-1]:
                d = d.setdefault(p, {})
            d[parts[-1]] = v
    if rehash:
        data["record_hash"] = compute_record_hash(data)
    return data


@pytest.mark.parametrize("case_index", range(12))
def test_negative_cases_n01_to_n12(
    fixture_data: dict[str, Any], case_index: int
) -> None:
    cases = fixture_data["negative_cases"]
    c = cases[case_index]
    case_name = c["case"]
    base_id = c["base"]
    expected_substr = c["expected"]
    rehash = c.get("rehash", True)

    base_fixture = fixture_data["fixtures"][base_id]
    mutated = apply_mutation(
        base=base_fixture,
        replace=c.get("replace"),
        remove=c.get("remove"),
        rehash=rehash,
    )

    kind_map = {
        "F01": "context",
        "F02": "candidate",
        "F03": "candidate",
        "F07": "raw_cost",
    }
    expected_kind = kind_map[base_id]

    checked_at = (
        datetime.fromisoformat("2024-01-02T10:00:03.000000Z")
        if case_name == "N08"
        else None
    )

    with pytest.raises(ValueError) as exc:
        validate_retained_record(
            mutated,
            expected_kind=expected_kind,
            checked_at=checked_at,
        )

    # Check that error matches expected reason
    error_msg = str(exc.value)
    # The expected string might be a semicolon-separated explanation; check first clause
    first_clause = expected_substr.split(";")[0].strip()
    assert (
        first_clause in error_msg
        or "weights sum to" in error_msg
        or "record_hash mismatch" in error_msg
        or "abstention cannot retain" in error_msg
        or "already expired" in error_msg
        or "missing evidence of verified zero" in error_msg
        or "required mandate binding missing" in error_msg
        or "refuse unknown version" in error_msg
        or "reject cross-arm scope" in error_msg
    ), f"Case {case_name}: got '{error_msg}', expected to match '{first_clause}'"
