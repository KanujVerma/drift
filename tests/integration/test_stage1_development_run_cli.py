"""Integration tests for Stage 1 development-run and calibrate CLI pipeline.

Workstream E, Issue 575.
"""

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from drift.experiments.stage1_study_artifacts import (
    create_calibration_attempt_receipt,
    create_development_calibration_plan,
)
from drift.experiments.stage1_study_freeze import StudyDateWindowV1

H = "7" * 64
NOW = datetime(2026, 11, 2, 6, 0, 0, tzinfo=UTC)


def test_unqualified_development_cli_leaves_no_outputs(tmp_path: Path) -> None:
    plan = create_development_calibration_plan(
        plan_id="CAL-PLAN-CLI-CONTAINMENT",
        created_at=NOW,
        method_version="grid-9-conventional/1",
        owner_reference="kanuj@drift.local",
        reviewer_reference="matthew@drift.local",
        development_window=StudyDateWindowV1(
            start=date(2021, 1, 1), end=date(2023, 12, 31)
        ),
        prohibited_windows=(),
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        execution_policy_hash=H,
        cost_policy_hash=H,
        mandate_policy_hash=H,
        access_log_policy_hash=H,
    )
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan.model_dump(mode="json")), encoding="utf-8")
    host = tmp_path / "host.json"
    host.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    ledger_dir = tmp_path / "ledgers"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "development-run",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host),
            "--output",
            str(output),
            "--ledger-dir",
            str(ledger_dir),
            "--session-count",
            "130",
            "--update-host-config",
        ],
        capture_output=True,
    )
    assert proc.returncode != 0
    assert b"DEVELOPMENT_CALIBRATION_UNQUALIFIED" in proc.stderr
    assert not output.exists()
    assert not ledger_dir.exists()
    assert host.read_text(encoding="utf-8") == "{}"


def test_development_run_cli_and_calibrate_pipeline(tmp_path: Path) -> None:
    plan = create_development_calibration_plan(
        plan_id="CAL-PLAN-CLI-TEST",
        created_at=NOW,
        method_version="grid-9-conventional/1",
        owner_reference="kanuj@drift.local",
        reviewer_reference="matthew@drift.local",
        development_window=StudyDateWindowV1(
            start=date(2021, 1, 1), end=date(2023, 12, 31)
        ),
        prohibited_windows=(
            StudyDateWindowV1(start=date(2024, 1, 1), end=date(2024, 12, 31)),
            StudyDateWindowV1(start=date(2025, 1, 1), end=date(2025, 12, 31)),
        ),
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        execution_policy_hash=H,
        cost_policy_hash=H,
        mandate_policy_hash=H,
        access_log_policy_hash=H,
    )

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan.model_dump(mode="json")), encoding="utf-8")

    host_config_file = tmp_path / "host_config.json"
    host_config_file.write_text(json.dumps({}), encoding="utf-8")

    dev_run_out = tmp_path / "dev_run_result.json"

    # 1. Run development-run CLI
    proc_dev = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "development-run",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(dev_run_out),
            "--session-count",
            "130",
            "--update-host-config",
        ],
        capture_output=True,
    )
    assert proc_dev.returncode == 0, (
        f"development-run failed: {proc_dev.stderr.decode('utf-8')}"
    )
    assert dev_run_out.exists()

    run_manifest = json.loads(dev_run_out.read_text(encoding="utf-8"))
    assert run_manifest["status"] == "COMPLETED"
    assert len(run_manifest["attempts"]) == 9
    assert run_manifest["selected_pair"] is not None

    # Host config should be updated with attempts and calibration_result
    updated_host = json.loads(host_config_file.read_text(encoding="utf-8"))
    assert "attempts" in updated_host
    assert len(updated_host["attempts"]) == 9

    # 2. Feed into calibrate CLI to independently confirm deterministic ranking
    cal_out = tmp_path / "cal_result.json"
    proc_cal = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "calibrate",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(cal_out),
        ],
        capture_output=True,
    )
    assert proc_cal.returncode == 0, (
        f"calibrate failed: {proc_cal.stderr.decode('utf-8')}"
    )
    assert cal_out.exists()

    cal_manifest = json.loads(cal_out.read_text(encoding="utf-8"))
    assert cal_manifest["selected_pair"] == run_manifest["selected_pair"]
    assert (
        cal_manifest["selected_pair_receipt_hash"]
        == run_manifest["selected_pair_receipt_hash"]
    )
    assert cal_manifest["ranking_proof"] == run_manifest["ranking_proof"]


def test_calibrate_cli_negative_control_incomplete_grid(tmp_path: Path) -> None:
    plan = create_development_calibration_plan(
        plan_id="CAL-PLAN-CLI-NEG",
        created_at=NOW,
        method_version="grid-9-conventional/1",
        owner_reference="kanuj@drift.local",
        reviewer_reference="matthew@drift.local",
        development_window=StudyDateWindowV1(
            start=date(2021, 1, 1), end=date(2023, 12, 31)
        ),
        prohibited_windows=(),
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        execution_policy_hash=H,
        cost_policy_hash=H,
        mandate_policy_hash=H,
        access_log_policy_hash=H,
    )

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan.model_dump(mode="json")), encoding="utf-8")

    # Incomplete host config with only 8 attempts
    attempts = [
        create_calibration_attempt_receipt(
            attempt_id=f"ATT-{p.lambda_v}-{p.lambda_d}",
            pair=p,
            status="COMPLETED",
            plan_hash=plan.plan_hash,
            terminal_net_return=Decimal("0.10000000"),
            absolute_maximum_drawdown=Decimal("0.05000000"),
            total_gross_turnover=Decimal("0.50000000"),
            operating_cost=Decimal("0.00000000"),
        ).model_dump(mode="json")
        for p in plan.coefficient_pairs[:8]
    ]

    host_config_file = tmp_path / "host_config.json"
    host_config_file.write_text(json.dumps({"attempts": attempts}), encoding="utf-8")

    cal_out = tmp_path / "cal_result.json"
    proc_cal = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "calibrate",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(cal_out),
        ],
        capture_output=True,
    )
    assert proc_cal.returncode == 2
    assert b"Calibration incomplete" in proc_cal.stderr
