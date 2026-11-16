"""Containment and serialization tests; no historical execution is asserted."""

from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_development_runner import (
    DevelopmentRunConfigV1,
    DevelopmentRunResultV1,
    execute_development_run,
)
from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    DevelopmentCalibrationPlanV1,
    compute_ranking_proof,
    create_calibration_attempt_receipt,
    create_development_calibration_plan,
)
from drift.experiments.stage1_study_freeze import StudyDateWindowV1
from drift.serialization.canonical import content_hash

H = "8" * 64
NOW = datetime(2026, 11, 2, 6, 0, 0, tzinfo=UTC)


def _create_valid_dev_plan() -> tuple[
    DevelopmentCalibrationPlanV1,
    StudyDateWindowV1,
    tuple[StudyDateWindowV1, ...],
]:
    dev_win = StudyDateWindowV1(start=date(2021, 1, 1), end=date(2023, 12, 31))
    prohib = (
        StudyDateWindowV1(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        StudyDateWindowV1(start=date(2025, 1, 1), end=date(2025, 12, 31)),
    )
    plan = create_development_calibration_plan(
        plan_id="CAL-PLAN-TEST-2021-2023",
        created_at=NOW,
        method_version="grid-9-conventional/1",
        owner_reference="kanuj@drift.local",
        reviewer_reference="matthew@drift.local",
        development_window=dev_win,
        prohibited_windows=prohib,
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        execution_policy_hash=H,
        cost_policy_hash=H,
        mandate_policy_hash=H,
        access_log_policy_hash=H,
    )
    return plan, dev_win, prohib


@pytest.mark.parametrize("session_count", [None, 0, 126, 130, 754])
def test_unqualified_synthetic_run_refuses_without_creating_artifacts(
    tmp_path: Path,
    session_count: int | None,
) -> None:
    """An unqualified generated series must not become historical calibration."""
    plan, _, _ = _create_valid_dev_plan()
    ledger_dir = tmp_path / "ledgers"
    artifacts: dict[str, Any] = {}
    receipts: dict[str, Any] = {}
    config = DevelopmentRunConfigV1(
        plan=plan, session_count=session_count, ledger_dir=ledger_dir
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_CALIBRATION_UNQUALIFIED"):
        execute_development_run(
            config, artifact_store=artifacts, receipt_store=receipts
        )
    assert not ledger_dir.exists()
    assert artifacts == {}
    assert receipts == {}


@pytest.mark.parametrize("shared_account", [False, True])
def test_refusal_preserves_existing_stores_accounts_and_ledger(
    tmp_path: Path,
    shared_account: bool,
) -> None:
    plan, _, _ = _create_valid_dev_plan()
    ledger_dir = tmp_path / "ledgers"
    ledger_dir.mkdir()
    ledger = ledger_dir / "calib_r_0.25_0.25.db"
    original_bytes = b"existing caller-owned ledger sentinel"
    ledger.write_bytes(original_bytes)
    artifacts: dict[str, Any] = {"existing": {"values": [1, 2]}}
    receipts: dict[str, Any] = {"existing": {"values": [3, 4]}}
    accounts = (
        {"ACCOUNT-DEV-CALIB-R-0.25-0.25"} if shared_account else {"other-account"}
    )
    before = deepcopy((artifacts, receipts, accounts))
    config = DevelopmentRunConfigV1(
        plan=plan,
        session_count=130,
        ledger_dir=ledger_dir,
        authority_id="caller-supplied-label-does-not-qualify-data",
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_CALIBRATION_UNQUALIFIED"):
        execute_development_run(
            config,
            artifact_store=artifacts,
            receipt_store=receipts,
            allocated_accounts=accounts,
        )
    assert (artifacts, receipts, accounts) == before
    assert ledger.read_bytes() == original_bytes
    assert tuple(ledger_dir.iterdir()) == (ledger,)


def test_development_run_negative_control_overlaps_prohibited_window() -> None:
    # Attempting to calibrate using a window that overlaps prohibited 2024 or 2025
    dev_win_bad = StudyDateWindowV1(start=date(2023, 1, 1), end=date(2024, 6, 30))
    prohib = (
        StudyDateWindowV1(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        StudyDateWindowV1(start=date(2025, 1, 1), end=date(2025, 12, 31)),
    )

    with pytest.raises(ValueError, match="CALIBRATION_PLAN_WINDOW_OVERLAPS_PROHIBITED"):
        create_development_calibration_plan(
            plan_id="CAL-PLAN-BAD",
            created_at=NOW,
            method_version="grid-9-conventional/1",
            owner_reference="kanuj@drift.local",
            reviewer_reference="matthew@drift.local",
            development_window=dev_win_bad,
            prohibited_windows=prohib,
            installed_source_hash=H,
            dataset_manifest_hash=H,
            calendar_and_universe_hash=H,
            execution_policy_hash=H,
            cost_policy_hash=H,
            mandate_policy_hash=H,
            access_log_policy_hash=H,
        )


def test_fixture_result_round_trip_and_hash_tamper_refusal() -> None:
    """Explicit serialization fixture, never an executed account campaign."""
    plan, _, _ = _create_valid_dev_plan()
    attempts = tuple(
        create_calibration_attempt_receipt(
            attempt_id=f"FIXTURE-{index}",
            pair=pair,
            status="COMPLETED",
            plan_hash=plan.plan_hash,
            terminal_net_return=Decimal("0.10"),
            absolute_maximum_drawdown=Decimal("0.05"),
            total_gross_turnover=Decimal("0.50"),
            operating_cost=Decimal("0.00"),
        )
        for index, pair in enumerate(ORDERED_CALIBRATION_PAIRS)
    )
    body: dict[str, Any] = {
        "schema_version": "drift-stage1-development-run/1",
        "run_id": "FIXTURE-SERIALIZATION-ONLY",
        "plan_hash": plan.plan_hash,
        "status": "COMPLETED",
        "completed_at": NOW,
        "evaluated_sessions_count": 130,
        "attempts": attempts,
        "selected_pair": attempts[0].pair,
        "selected_pair_receipt_hash": attempts[0].receipt_hash,
        "ranking_proof": compute_ranking_proof(attempts),
        "account_ids": (),
        "ledger_paths": {},
    }
    fixture = DevelopmentRunResultV1.model_validate(
        {**body, "run_result_hash": content_hash(body)}
    )
    assert (
        DevelopmentRunResultV1.model_validate_json(fixture.model_dump_json()) == fixture
    )
    for field, value in (
        ("run_result_hash", "f" * 64),
        ("evaluated_sessions_count", 131),
        ("status", "FAILED"),
    ):
        tampered = fixture.model_dump(mode="python")
        tampered[field] = value
        with pytest.raises(
            ValidationError, match="DEVELOPMENT_RUN_RESULT_HASH_MISMATCH"
        ):
            DevelopmentRunResultV1.model_validate(tampered)
