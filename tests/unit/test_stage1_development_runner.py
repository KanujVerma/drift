"""Unit tests for Stage 1 development runner and 9-pair R calibration.

Workstream E, Issue 575.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_development_runner import (
    DevelopmentRunConfigV1,
    DevelopmentRunResultV1,
    execute_development_run,
)
from drift.experiments.stage1_economic_costs import create_stage1_cost_model
from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    DevelopmentCalibrationPlanV1,
    create_development_calibration_plan,
)
from drift.experiments.stage1_study_freeze import StudyDateWindowV1

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


def test_unqualified_synthetic_run_refuses_without_creating_artifacts(
    tmp_path: Path,
) -> None:
    """An unqualified generated series must not become historical calibration."""
    plan, _, _ = _create_valid_dev_plan()
    ledger_dir = tmp_path / "ledgers"
    artifacts: dict[str, Any] = {}
    receipts: dict[str, Any] = {}
    config = DevelopmentRunConfigV1(plan=plan, session_count=130, ledger_dir=ledger_dir)
    with pytest.raises(ValueError, match="DEVELOPMENT_CALIBRATION_UNQUALIFIED"):
        execute_development_run(
            config, artifact_store=artifacts, receipt_store=receipts
        )
    assert not ledger_dir.exists()
    assert artifacts == {}
    assert receipts == {}


def test_development_run_executes_all_nine_pairs_with_independent_accounts(
    tmp_path: Path,
) -> None:
    plan, _, _ = _create_valid_dev_plan()
    cost_model = create_stage1_cost_model()

    ledger_dir = tmp_path / "ledgers"
    config = DevelopmentRunConfigV1(
        plan=plan,
        authority_id="trusted-dev-root",
        cost_model=cost_model,
        session_count=130,  # 126 lookback + 4 decision sessions
        ledger_dir=ledger_dir,
    )

    receipt_store: dict[str, Any] = {}
    artifact_store: dict[str, Any] = {}

    run_result, cal_result = execute_development_run(
        config,
        artifact_store=artifact_store,
        receipt_store=receipt_store,
    )

    assert run_result.status == "COMPLETED"
    assert run_result.evaluated_sessions_count == 130
    assert len(run_result.attempts) == 9
    assert len(run_result.account_ids) == 9

    # Verify each pair has an independent account
    assert len(set(run_result.account_ids)) == 9
    for pair in ORDERED_CALIBRATION_PAIRS:
        expected_account = f"ACCOUNT-DEV-CALIB-R-{pair.lambda_v}-{pair.lambda_d}"
        assert expected_account in run_result.account_ids

    # Verify distinct SQLite ledgers exist and are non-empty
    assert len(run_result.ledger_paths) == 9
    for _acc_id, path_str in run_result.ledger_paths.items():
        p = Path(path_str)
        assert p.exists()
        assert p.stat().st_size > 0

    # Verify all 9 attempts completed with valid metrics
    for att in run_result.attempts:
        assert att.status == "COMPLETED"
        assert att.terminal_net_return is not None
        assert att.absolute_maximum_drawdown is not None
        assert att.total_gross_turnover is not None
        assert att.operating_cost is not None
        assert att.plan_hash == plan.plan_hash
        assert att.receipt_hash in receipt_store

    # Verify winner selection and ranking proof
    assert run_result.selected_pair is not None
    assert run_result.selected_pair == cal_result.selected_pair
    assert (
        run_result.selected_pair_receipt_hash == cal_result.selected_pair_receipt_hash
    )
    assert len(run_result.ranking_proof) == 9
    assert run_result.ranking_proof == cal_result.ranking_proof


def test_development_run_negative_control_shared_account_prohibited(
    tmp_path: Path,
) -> None:
    plan, _, _ = _create_valid_dev_plan()
    config = DevelopmentRunConfigV1(
        plan=plan,
        session_count=130,
        ledger_dir=tmp_path / "ledgers",
    )

    # Pre-allocating one of the pair accounts simulates two pairs sharing an account
    conflicting_account = "ACCOUNT-DEV-CALIB-R-0.25-0.25"
    with pytest.raises(ValueError, match="CALIBRATION_SHARED_ACCOUNT_PROHIBITED"):
        execute_development_run(
            config,
            allocated_accounts={conflicting_account},
        )


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


def test_development_run_result_hash_tamper_fails() -> None:
    plan, _, _ = _create_valid_dev_plan()
    config = DevelopmentRunConfigV1(plan=plan, session_count=130)
    run_result, _ = execute_development_run(config)

    # Tampering with run_result_hash fails closed
    dump = run_result.model_dump(mode="python")
    dump["run_result_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="DEVELOPMENT_RUN_RESULT_HASH_MISMATCH"):
        DevelopmentRunResultV1.model_validate(dump)
