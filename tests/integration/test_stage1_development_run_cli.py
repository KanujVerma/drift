"""CLI containment and explicit fixture ranking; no historical execution."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from drift.experiments.stage1_study_artifacts import (
    CalibrationResultV1,
    create_calibration_attempt_receipt,
    create_development_calibration_plan,
)
from drift.experiments.stage1_study_freeze import StudyDateWindowV1

H = "7" * 64
NOW = datetime(2026, 11, 2, 6, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("existing_outputs", [False, True])
def test_unqualified_development_cli_leaves_no_outputs(
    tmp_path: Path,
    existing_outputs: bool,
) -> None:
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
    host_bytes = b'{"artifact_store":{"sentinel":[1]},"receipt_store":{"sentinel":[2]}}'
    host.write_bytes(host_bytes)
    output = tmp_path / "result.json"
    ledger_dir = tmp_path / "ledgers"
    output_bytes = b"existing output sentinel"
    ledger_bytes = b"existing ledger sentinel"
    if existing_outputs:
        output.write_bytes(output_bytes)
        ledger_dir.mkdir()
        (ledger_dir / "calib_r_0.25_0.25.db").write_bytes(ledger_bytes)
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
    assert proc.returncode == 1
    assert b"DEVELOPMENT_CALIBRATION_UNQUALIFIED" in proc.stderr
    assert host.read_bytes() == host_bytes
    if existing_outputs:
        assert output.read_bytes() == output_bytes
        ledger = ledger_dir / "calib_r_0.25_0.25.db"
        assert ledger.read_bytes() == ledger_bytes
        assert tuple(ledger_dir.iterdir()) == (ledger,)
    else:
        assert not output.exists()
        assert not ledger_dir.exists()


def test_calibrate_cli_ranks_explicit_nine_pair_fixtures(tmp_path: Path) -> None:
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

    # These supplied metrics only exercise ranking. No account execution,
    # original-data authentication, or scientific acceptance is represented.
    attempts = [
        create_calibration_attempt_receipt(
            attempt_id=f"FIXTURE-{index}",
            pair=pair,
            status="COMPLETED",
            plan_hash=plan.plan_hash,
            terminal_net_return=Decimal("0.12") if index == 4 else Decimal("0.08"),
            absolute_maximum_drawdown=Decimal("0.05"),
            total_gross_turnover=Decimal("0.50"),
            operating_cost=Decimal("0.00"),
        )
        for index, pair in enumerate(plan.coefficient_pairs)
    ]
    expected = [attempts[4], *[a for i, a in enumerate(attempts) if i != 4]]
    host_config_file = tmp_path / "host_config.json"
    proof: tuple[str, ...] | None = None
    for order in (attempts, list(reversed(attempts))):
        host_config_file.write_text(
            json.dumps({"attempts": [a.model_dump(mode="json") for a in order]}),
            encoding="utf-8",
        )
        host_before = host_config_file.read_bytes()
        cal_out = tmp_path / "fixture_ranking.json"
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
        assert proc_cal.returncode == 0, proc_cal.stderr.decode("utf-8")
        result = CalibrationResultV1.model_validate_json(cal_out.read_text("utf-8"))
        assert result.selected_pair == plan.coefficient_pairs[4]
        assert result.selected_pair_receipt_hash == attempts[4].receipt_hash
        assert len(result.attempts) == 9
        assert len(result.ranking_proof) == 9
        assert result.original_acceptance_receipts == ()
        assert host_config_file.read_bytes() == host_before
        if proof is not None:
            assert result.ranking_proof == proof
        proof = result.ranking_proof
        assert result.ranking_proof == tuple(
            hashlib.sha256(
                f"{a.pair.lambda_v}:{a.pair.lambda_d}:{a.receipt_hash}".encode()
            ).hexdigest()
            for a in expected
        )


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
    assert not cal_out.exists()
