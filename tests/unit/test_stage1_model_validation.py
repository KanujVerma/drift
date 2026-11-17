"""Unit tests for Stage 1 immutable Model B binding and 2024 validation.

Workstream F, Issue 575.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_model_validation import (
    ImmutableModelBindingV1,
    ValidationRunConfigV1,
    ValidationRunResultV1,
    create_immutable_model_binding,
    create_study_model_policy,
    execute_2024_validation,
)
from drift.experiments.stage1_study_artifacts import CalibrationPairV1
from drift.experiments.stage1_study_freeze import StudyDateWindowV1
from drift.serialization.canonical import content_hash


def _create_valid_binding() -> ImmutableModelBindingV1:
    return create_immutable_model_binding(
        binding_id="synthetic-binding",
        provider="synthetic-test-provider",
        deployment_version="synthetic-fixture-v1",
        prompt_text="You are an asset allocator. Select B3, B4, or B5.",
        seed=42,
        token_ceiling=4096,
        monetary_ceiling=Decimal("10.00"),
        transport_kind="DIRECT_API",
        known_training_cutoff=date(2023, 12, 31),
    )


@pytest.mark.parametrize("supply_returns", [False, True])
def test_validation_refuses_unverified_execution_without_side_effects(
    tmp_path: Path, supply_returns: bool
) -> None:
    ledger_dir = tmp_path / "uncreated-ledgers"
    config = ValidationRunConfigV1(
        model_binding=_create_valid_binding(),
        comparator_pair=CalibrationPairV1(
            lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50")
        ),
        session_count=42,
        ledger_dir=ledger_dir,
    )
    artifacts: dict[str, Any] = {"existing": "unchanged"}
    receipts: dict[str, Any] = {"existing": "unchanged"}
    supplied = [Decimal("0.01")] * 42 if supply_returns else None

    with pytest.raises(ValueError, match="VALIDATION_ORIGINAL_EVIDENCE_UNAVAILABLE"):
        execute_2024_validation(
            config,
            artifact_store=artifacts,
            receipt_store=receipts,
            daily_b_returns=supplied,
            daily_r_returns=supplied,
        )
    assert not ledger_dir.exists()
    assert artifacts == {"existing": "unchanged"}
    assert receipts == {"existing": "unchanged"}


def test_immutable_model_binding_and_study_policy_conformance() -> None:
    binding = _create_valid_binding()
    assert binding.provider == "synthetic-test-provider"
    assert binding.deployment_version == "synthetic-fixture-v1"
    assert binding.seed == 42
    assert binding.token_ceiling == 4096
    assert binding.known_training_cutoff == date(2023, 12, 31)

    policy = create_study_model_policy(binding)
    assert policy.provider == "synthetic-test-provider"
    assert policy.immutable_model_revision == "synthetic-fixture-v1"
    assert policy.seed == 42
    assert policy.known_training_cutoff == date(2023, 12, 31)
    assert len(policy.model_record_hash) == 64
    assert len(policy.prompt_hash) == 64


def test_validation_negative_control_fake_transport_rejected() -> None:
    with pytest.raises(ValueError, match="FAKE_TRANSPORT_NOT_AUTHENTIC_AI"):
        create_immutable_model_binding(
            binding_id="BINDING-FAKE",
            provider="anthropic",
            deployment_version="claude-3-5-sonnet-20241022",
            prompt_text="Alloc.",
            transport_kind="FAKE_TRANSPORT",
        )


def test_validation_negative_control_unpinned_revision_rejected() -> None:
    with pytest.raises(ValueError, match="VALIDATION_UNPINNED_MODEL_REVISION"):
        create_immutable_model_binding(
            binding_id="BINDING-UNPINNED",
            provider="anthropic",
            deployment_version="claude-3-5-sonnet-latest",
            prompt_text="Alloc.",
        )


def test_validation_negative_control_training_cutoff_overlaps_validation() -> None:
    with pytest.raises(ValueError, match="MODEL_TRAINED_ON_VALIDATION_DATA"):
        create_immutable_model_binding(
            binding_id="BINDING-LEAKED",
            provider="anthropic",
            deployment_version="claude-3-5-sonnet-20241022",
            prompt_text="Alloc.",
            known_training_cutoff=date(2024, 6, 1),
        )


def test_validation_negative_control_invalid_window() -> None:
    binding = _create_valid_binding()
    comparator = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50"))
    bad_window = StudyDateWindowV1(start=date(2023, 1, 1), end=date(2023, 12, 31))

    config = ValidationRunConfigV1(
        model_binding=binding,
        comparator_pair=comparator,
        validation_window=bad_window,
    )
    with pytest.raises(ValueError, match="INVALID_VALIDATION_WINDOW"):
        execute_2024_validation(config)


def test_synthetic_validation_result_tamper_fails() -> None:
    # Test-only failed record: it is not emitted by the validation runner.
    body = {
        "schema_version": "drift-stage1-validation-run/1",
        "run_id": "synthetic-test-only",
        "status": "FAILED",
        "completed_at": datetime(2024, 1, 1, tzinfo=UTC),
        "model_binding_hash": "a" * 64,
        "comparator_pair": CalibrationPairV1(
            lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50")
        ),
        "validation_window": StudyDateWindowV1(
            start=date(2024, 1, 1), end=date(2024, 12, 31)
        ),
        "evaluated_sessions_count": 0,
        "b_terminal_nav": Decimal("10000"),
        "r_terminal_nav": Decimal("10000"),
        "b_net_return": Decimal("0"),
        "r_net_return": Decimal("0"),
        "b_receipt_refs": (),
        "r_receipt_refs": (),
        "model_replay_refs": (),
        "exposure_record": (),
        "ledger_paths": {},
    }
    result = ValidationRunResultV1.model_validate(
        body | {"validation_hash": content_hash(body)}
    )
    dump = result.model_dump(mode="python")
    dump["validation_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="VALIDATION_HASH_MISMATCH"):
        ValidationRunResultV1.model_validate(dump)
