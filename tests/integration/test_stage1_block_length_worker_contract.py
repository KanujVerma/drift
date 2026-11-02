"""Integration test for isolated arch 8.0.0 block length worker contract."""

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_block_length_worker_execution(repo_root: Path) -> None:
    worker_script = repo_root / "tools" / "stage1-statistics" / "block_length_worker.py"
    worker_dir = repo_root / "tools" / "stage1-statistics"

    input_payload = {
        "schema_version": "drift-stage1-block-length-input/1",
        "sessions": [f"S{i:03d}" for i in range(120)],
        "b_returns": ["0.01", "-0.01", "0.02"] * 40,
        "r_returns": ["0.005", "-0.005", "0.01"] * 40,
        "difference_returns": ["0.005", "-0.005", "0.01"] * 40,
    }

    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    proc = subprocess.run(
        [
            "uv",
            "--directory",
            str(worker_dir),
            "run",
            "python",
            str(worker_script),
        ],
        input=json.dumps(input_payload).encode("utf-8"),
        capture_output=True,
        check=True,
        env=env,
    )

    out = json.loads(proc.stdout.decode("utf-8"))
    assert out["schema_version"] == "drift-stage1-block-length-output/1"
    assert out["package_identity"] == "arch==8.0.0"
    assert out["aggregated_block_length"] is not None
    assert out["aggregated_block_length"] >= 1
    assert "b_returns" in out["series_results"]
    assert "r_returns" in out["series_results"]
    assert "difference_returns" in out["series_results"]
    assert len(out["worker_source_hash"]) == 64


def test_block_length_worker_rejects_difference_mismatch(repo_root: Path) -> None:
    worker_script = repo_root / "tools" / "stage1-statistics" / "block_length_worker.py"
    worker_dir = repo_root / "tools" / "stage1-statistics"

    bad_payload = {
        "schema_version": "drift-stage1-block-length-input/1",
        "sessions": ["S01", "S02"],
        "b_returns": ["0.01", "0.02"],
        "r_returns": ["0.005", "0.01"],
        "difference_returns": ["0.999", "0.01"],  # Mismatch!
    }

    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    proc = subprocess.run(
        [
            "uv",
            "--directory",
            str(worker_dir),
            "run",
            "python",
            str(worker_script),
        ],
        input=json.dumps(bad_payload).encode("utf-8"),
        capture_output=True,
        env=env,
    )

    assert proc.returncode != 0
    assert b"DIFFERENCE_RETURN_MISMATCH" in proc.stderr
