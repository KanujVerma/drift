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
