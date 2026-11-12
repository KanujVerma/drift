"""Integration test for isolated arch 8.0.0 block length worker contract."""

import json
import os
import subprocess
from fractions import Fraction
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


@pytest.mark.parametrize(
    ("precision", "rounding", "rounded"),
    [
        (6, "ROUND_HALF_EVEN", "0.123457"),
        (28, "ROUND_HALF_EVEN", "0.1234567890123456789012345679"),
        (6, "ROUND_DOWN", "0.123456"),
    ],
)
@pytest.mark.parametrize("offset", ["0", "1"])
def test_block_length_difference_is_exact_under_decimal_context(
    repo_root: Path, precision: int, rounding: str, rounded: str, offset: str
) -> None:
    exact = "0.123456789012345678901234567891"
    assert Fraction(exact) != Fraction(rounded)
    first_b = exact if offset == "0" else "1." + exact[2:]
    assert Fraction(first_b) - Fraction(offset) == Fraction(exact)
    b_returns = [first_b, *(["0.01", "-0.01", "0.02"] * 39), "0.01", "-0.01"]
    difference_returns = [exact, *b_returns[1:]]
    payload = {
        "schema_version": "drift-stage1-block-length-input/1",
        "sessions": [f"S{i:03d}" for i in range(len(b_returns))],
        "b_returns": b_returns,
        "r_returns": [offset, *(["0"] * (len(b_returns) - 1))],
        "difference_returns": difference_returns,
    }
    worker_dir = repo_root / "tools" / "stage1-statistics"
    worker_script = worker_dir / "block_length_worker.py"
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    runner = (
        "import decimal,runpy,sys;"
        "decimal.getcontext().prec=int(sys.argv[1]);"
        "decimal.getcontext().rounding=sys.argv[2];"
        "runpy.run_path(sys.argv[3],run_name='__main__')"
    )

    def run_worker() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                "uv",
                "--directory",
                str(worker_dir),
                "run",
                "--locked",
                "python",
                "-c",
                runner,
                str(precision),
                rounding,
                str(worker_script),
            ],
            input=json.dumps(payload).encode(),
            capture_output=True,
            env=env,
        )

    valid = run_worker()
    assert valid.returncode == 0, valid.stderr.decode()
    assert json.loads(valid.stdout)["package_identity"] == "arch==8.0.0"

    difference_returns[0] = rounded
    invalid = run_worker()
    assert invalid.returncode != 0
    assert b"DIFFERENCE_RETURN_MISMATCH" in invalid.stderr


@pytest.mark.parametrize("nonfinite", ["NaN", "Infinity", "-Infinity"])
def test_block_length_rejects_nonfinite_decimal(
    repo_root: Path, nonfinite: str
) -> None:
    worker_dir = repo_root / "tools" / "stage1-statistics"
    payload = {
        "schema_version": "drift-stage1-block-length-input/1",
        "sessions": ["S01"],
        "b_returns": [nonfinite],
        "r_returns": ["0"],
        "difference_returns": [nonfinite],
    }
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.run(
        [
            "uv",
            "--directory",
            str(worker_dir),
            "run",
            "--locked",
            "python",
            str(worker_dir / "block_length_worker.py"),
        ],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env=env,
    )
    assert proc.returncode != 0
    assert b"NON_FINITE_FLOAT_ENCOUNTERED" in proc.stderr


def test_tiny_mismatch_reports_the_original_validation_error(repo_root: Path) -> None:
    worker_dir = repo_root / "tools" / "stage1-statistics"
    payload = {
        "schema_version": "drift-stage1-block-length-input/1",
        "sessions": ["S01"],
        "b_returns": ["1e-5000"],
        "r_returns": ["0"],
        "difference_returns": ["0"],
    }
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.run(
        [
            "uv",
            "--directory",
            str(worker_dir),
            "run",
            "--locked",
            "python",
            str(worker_dir / "block_length_worker.py"),
        ],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env=env,
    )
    assert proc.returncode != 0
    assert b"DIFFERENCE_RETURN_MISMATCH_AT_INDEX_0" in proc.stderr


@pytest.mark.parametrize(
    ("b", "r", "difference", "expected"),
    [
        ("1e100000000", "1e100000000", "0", "nonfinite"),
        ("1e-100000000", "1e-100000000", "0", "accepted"),
        ("2e100000000", "1e100000000", "1e100000000", "nonfinite"),
        ("1", "1e-100000000", "1", "mismatch"),
    ],
)
def test_block_length_exact_comparison_does_not_expand_extreme_exponents(
    repo_root: Path, b: str, r: str, difference: str, expected: str
) -> None:
    worker_dir = repo_root / "tools" / "stage1-statistics"
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    interpreter = (
        subprocess.run(
            [
                "uv",
                "--directory",
                str(worker_dir),
                "run",
                "--locked",
                "python",
                "-c",
                "import sys; print(sys.executable)",
            ],
            capture_output=True,
            check=True,
            env=env,
        )
        .stdout.decode()
        .strip()
    )
    payload = {
        "schema_version": "drift-stage1-block-length-input/1",
        "sessions": ["S01", "S02"],
        "b_returns": [b, b],
        "r_returns": [r, r],
        "difference_returns": [difference, difference],
    }
    proc = subprocess.run(
        [interpreter, str(worker_dir / "block_length_worker.py")],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env=env,
        timeout=5,
    )
    if expected == "accepted":
        assert proc.returncode == 0, proc.stderr.decode()
        assert json.loads(proc.stdout)["aggregated_block_length"] is None
    else:
        assert proc.returncode != 0
        error = (
            b"DIFFERENCE_RETURN_MISMATCH"
            if expected == "mismatch"
            else b"NON_FINITE_FLOAT_ENCOUNTERED"
        )
        assert error in proc.stderr
