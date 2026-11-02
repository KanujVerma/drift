"""Integration tests for scripts/stage1_study.py CLI orchestrator."""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_cli_inventory(repo_root: Path, tmp_path: Path) -> None:
    script = repo_root / "scripts" / "stage1_study.py"
    out_file = tmp_path / "inventory.json"

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "inventory",
            "--repo-root",
            str(repo_root),
            "--output",
            str(out_file),
        ],
        capture_output=True,
        check=True,
    )
    assert proc.returncode == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "python_version" in data
    assert data["repo_root"] == str(repo_root)


def test_cli_report(repo_root: Path, tmp_path: Path) -> None:
    script = repo_root / "scripts" / "stage1_study.py"
    manifest_file = tmp_path / "manifest.json"
    host_config_file = tmp_path / "host.json"
    out_file = tmp_path / "report.json"

    host_config_file.write_text("{}", encoding="utf-8")
    classification_payload = {
        "schema_version": "drift-stage1-outcome/1",
        "outcome": "UNSUCCESSFUL",
        "primary_economic_advantage": "0",
        "materiality_hurdle": "100",
        "is_invalid": False,
        "is_available": True,
        "is_risk_comparable": True,
        "is_prospective_complete": False,
        "is_independently_accepted": False,
        "reasons": ["ECONOMIC_ADVANTAGE_NON_POSITIVE"],
    }
    from drift.serialization.canonical import content_hash

    classification_payload["classification_hash"] = content_hash(classification_payload)

    manifest_payload = {
        "study_id": "STUDY-CLI-TEST",
        "protocol_hash": "a" * 64,
        "mode": "RETROSPECTIVE",
        "scheduled_sessions": 252,
        "observed_sessions": 252,
        "primary_economic_advantage": "100.0",
        "outcome_classification": classification_payload,
    }

    manifest_file.write_text(json.dumps(manifest_payload), encoding="utf-8")

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "report",
            "--run-manifest",
            str(manifest_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
        check=True,
    )
    assert proc.returncode == 0
    report_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert report_data["schema_version"] == "drift-stage1-study-report/1"
    assert report_data["study_id"] == "STUDY-CLI-TEST"


def test_cli_prospective_register_and_step(repo_root: Path, tmp_path: Path) -> None:
    from datetime import UTC, date, datetime

    from drift.experiments.stage1_prospective_study import (
        create_prospective_study_plan,
    )
    from drift.experiments.stage1_study_freeze import REQUIRED_ROLES
    from drift.serialization.canonical import content_hash

    script = repo_root / "scripts" / "stage1_study.py"
    plan_file = tmp_path / "plan.json"
    host_config_file = tmp_path / "host.json"
    private_root = tmp_path / "private"
    private_root.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    h = "7" * 64
    plan = create_prospective_study_plan(
        plan_id="PROSP-CLI-01",
        created_at=now,
        calendar_identity="XNYS-2026-2027",
        first_eligible_session=date(2026, 11, 3),
        planned_last_session=date(2028, 11, 3),
        operating_environment_hash=h,
        model_binding_hash=h,
        market_admission_hash=h,
        mandate_hash=h,
        cost_policy_hash=h,
    )
    plan_file.write_text(plan.model_dump_json(), encoding="utf-8")

    receipts_store = {}
    evidence = []
    trust_roots = {}
    for role in REQUIRED_ROLES:
        payload = {
            "role": role,
            "receipt_id": f"RCPT-{role}",
            "protocol_hash": plan.plan_hash,
            "authority_id": "trusted-root",
            "status": "ACCEPTED",
        }
        r_hash = content_hash(payload)
        receipts_store[f"RCPT-{role}"] = payload
        evidence.append(
            {
                "role": role,
                "receipt_id": f"RCPT-{role}",
                "receipt_hash": r_hash,
                "protocol_hash": plan.plan_hash,
                "accepted_at": now.isoformat(),
            }
        )
        trust_roots[role] = ["trusted-root"]

    host_config = {
        "trust_roots": trust_roots,
        "receipt_store": receipts_store,
        "evidence": evidence,
        "has_broker": False,
    }
    host_config_file.write_text(json.dumps(host_config), encoding="utf-8")

    # 1. Register
    reg_proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "prospective-register",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host_config_file),
            "--private-root",
            str(private_root),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert reg_proc.returncode == 0
    reg_file = private_root / f"REG-{plan.plan_id}.json"
    assert reg_file.is_file()
    reg_data = json.loads(reg_file.read_text(encoding="utf-8"))
    assert reg_data["registration_id"] == f"REG-{plan.plan_id}"
    assert reg_data["observed_session_count"] == 0

    # 2. Step
    step_proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "prospective-step",
            "--registration",
            str(reg_file),
            "--host-config",
            str(host_config_file),
            "--private-root",
            str(private_root),
            "--session-date",
            "2026-11-03",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert step_proc.returncode == 0
    step_file = private_root / f"REG-{plan.plan_id}-step-1.json"
    assert step_file.is_file()
    step_data = json.loads(step_file.read_text(encoding="utf-8"))
    assert step_data["observed_session_count"] == 1
    assert step_data["last_observed_session"] == "2026-11-03"
