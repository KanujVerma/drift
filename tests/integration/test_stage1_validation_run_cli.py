"""Integration tests for Stage 1 validation-run CLI.

Workstream F, Issue 575.
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from drift.experiments.stage1_model_validation import (
    create_immutable_model_binding,
)
from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    create_calibration_attempt_receipt,
    create_calibration_result,
)

H = "6" * 64
NOW = datetime(2026, 11, 2, 6, 0, 0, tzinfo=UTC)


def test_validation_run_cli_refuses_unverified_execution(tmp_path: Path) -> None:
    binding = create_immutable_model_binding(
        binding_id="BINDING-CLI-TEST",
        provider="synthetic-test-provider",
        deployment_version="synthetic-fixture-v1",
        prompt_text="Allocate.",
        seed=42,
    )
    binding_file = tmp_path / "binding.json"
    binding_file.write_text(
        json.dumps(binding.model_dump(mode="json")), encoding="utf-8"
    )

    attempts = [
        create_calibration_attempt_receipt(
            attempt_id=f"ATT-{p.lambda_v}-{p.lambda_d}",
            pair=p,
            status="COMPLETED",
            plan_hash=H,
            terminal_net_return=Decimal("0.10000000"),
            absolute_maximum_drawdown=Decimal("0.05000000"),
            total_gross_turnover=Decimal("0.50000000"),
            operating_cost=Decimal("0.00000000"),
        )
        for p in ORDERED_CALIBRATION_PAIRS
    ]
    cal_res = create_calibration_result(
        plan_hash=H,
        completed_at=NOW,
        attempts=tuple(attempts),
    )
    cal_file = tmp_path / "cal_result.json"
    cal_file.write_text(json.dumps(cal_res.model_dump(mode="json")), encoding="utf-8")

    host_config_file = tmp_path / "host_config.json"
    host_config_file.write_text(json.dumps({}), encoding="utf-8")

    out_file = tmp_path / "val_run_result.json"
    ledger_dir = tmp_path / "uncreated-ledgers"

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "validation-run",
            "--model-binding",
            str(binding_file),
            "--calibration-result",
            str(cal_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(out_file),
            "--ledger-dir",
            str(ledger_dir),
            "--session-count",
            "25",
            "--update-host-config",
        ],
        capture_output=True,
    )
    assert proc.returncode == 1
    assert b"VALIDATION_ORIGINAL_EVIDENCE_UNAVAILABLE" in proc.stderr
    assert not out_file.exists()
    assert not ledger_dir.exists()
    assert json.loads(host_config_file.read_text(encoding="utf-8")) == {}


def test_validation_run_cli_negative_control_missing_comparator(
    tmp_path: Path,
) -> None:
    binding = create_immutable_model_binding(
        binding_id="BINDING-CLI-NEG",
        provider="anthropic",
        deployment_version="claude-3-5-sonnet-20241022",
        prompt_text="Allocate.",
        seed=42,
    )
    binding_file = tmp_path / "binding.json"
    binding_file.write_text(
        json.dumps(binding.model_dump(mode="json")), encoding="utf-8"
    )

    # Empty calibration result without selected_pair
    cal_res = create_calibration_result(
        plan_hash=H,
        completed_at=NOW,
        attempts=(),
        selected_pair=None,
    )
    cal_file = tmp_path / "cal_result_empty.json"
    cal_file.write_text(json.dumps(cal_res.model_dump(mode="json")), encoding="utf-8")

    host_config_file = tmp_path / "host_config.json"
    host_config_file.write_text(json.dumps({}), encoding="utf-8")

    out_file = tmp_path / "val_run_neg.json"

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "validation-run",
            "--model-binding",
            str(binding_file),
            "--calibration-result",
            str(cal_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 2
    assert b"missing selected comparator pair" in proc.stderr
