"""Canonical runs bind whole-tree code-version provenance (issue 109, issue 63 Q6).

Before issue 63, every M2 bundle implicitly carried the whole-tree
implementation hash through its M1d evidence. Issue 63 made bundle identity
semantic and stable across unrelated source edits. Q6 ruled: keep code-version
provenance separate.

This test asserts in a fresh subprocess over copied package trees (the #46
reproduction style) that canonical baseline runs bind
drift_source_inventory_hash() as code_version_hash, so that code_version_hash
moves when the source tree moves, while bundle_hash, admission_hash, and
evaluation results remain byte-identical.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from drift.domain.economic_common import economic_implementation_hash  # noqa: E402
from drift.domain.observation_query import drift_source_inventory_hash  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
UNRELATED_MODULE = "evaluator/engine.py"
COMMENT_EDIT = b"\n# issue 109: an unrelated comment edit\n"

_PRELUDE = """
import json
import sys
from pathlib import Path

import drift

root = Path(sys.argv[1]).resolve()
if not Path(drift.__file__).resolve().is_relative_to(root):
    raise SystemExit(f"imported Drift outside the source copy: {drift.__file__}")

from drift.domain.economic_common import economic_implementation_hash
from drift.domain.observation_query import drift_source_inventory_hash
"""

_CANONICAL_RUN_PROGRAM = (
    _PRELUDE
    + """
import test_evaluator_engine as engine_tests
from drift.baselines import B0CashStrategy, run_canonical_baseline

engine = engine_tests._engine()
strategy = B0CashStrategy()
experiment_run = run_canonical_baseline(engine=engine, strategy=strategy)

print(json.dumps({
    "source_inventory_hash": economic_implementation_hash(),
    "drift_source_inventory_hash": drift_source_inventory_hash(),
    "code_version_hash": experiment_run.code_hash,
    "bundle_hash": engine.bundle.bundle_hash,
    "admission_hash": engine.admission.admission_hash,
    "run_identity_hash": experiment_run.metrics["run_identity_hash"],
    "status": experiment_run.status.value,
    "evaluated_session_count": experiment_run.metrics["evaluated_session_count"],
    "committed_fill_count": experiment_run.metrics["committed_fill_count"],
    "net_profit_and_loss": experiment_run.metrics["net_profit_and_loss"],
    "ending_cash": experiment_run.metrics["ending_cash"],
    "ending_net_asset_value": experiment_run.metrics["ending_net_asset_value"],
}))
"""
)


def _source_copy(base: Path, name: str, edited: str | None) -> Path:
    """Copy the installed package and its lock, optionally applying one comment edit."""
    root = base / name
    shutil.copytree(
        REPO_ROOT / "src" / "drift",
        root / "src" / "drift",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(REPO_ROOT / "uv.lock", root / "uv.lock")
    if edited is not None:
        target = root / "src" / "drift" / edited
        target.write_bytes(target.read_bytes() + COMMENT_EDIT)
    return root


def _run(root: Path, program: str, *arguments: str) -> dict[str, Any]:
    """Run one program in a fresh interpreter importing Drift from ``root``."""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (
                str(root / "src"),
                str(REPO_ROOT / "tests" / "unit"),
                str(REPO_ROOT / "tests"),
            )
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        [sys.executable, "-c", program, str(root), *arguments],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    document = json.loads(completed.stdout.strip().splitlines()[-1])
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="module")
def copies(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("canonical-code-version-provenance")
    return {
        "pristine": _source_copy(base, "pristine", None),
        "unrelated": _source_copy(base, "unrelated", UNRELATED_MODULE),
    }


@pytest.fixture(scope="module")
def runs(copies: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: _run(root, _CANONICAL_RUN_PROGRAM) for name, root in copies.items()}


def test_pristine_copy_binds_installed_tree_inventory(
    runs: dict[str, dict[str, Any]],
) -> None:
    """The pristine copy binds drift_source_inventory_hash of the installed package."""
    pristine = runs["pristine"]
    assert pristine["source_inventory_hash"] == economic_implementation_hash()
    assert pristine["drift_source_inventory_hash"] == drift_source_inventory_hash()
    assert pristine["code_version_hash"] == drift_source_inventory_hash()
    assert pristine["status"] == "completed"


def test_code_version_hash_moves_with_tree_while_bundle_and_admission_remain_stable(
    runs: dict[str, dict[str, Any]],
) -> None:
    """The Issue 109 / Q6 requirement:

    An unrelated edit moves code_version_hash and run_identity_hash,
    while bundle_hash and admission_hash remain stable.
    """
    pristine, unrelated = runs["pristine"], runs["unrelated"]

    # 1. Whole-tree inventory hash moved with the tree edit
    assert unrelated["source_inventory_hash"] != pristine["source_inventory_hash"], (
        "source inventory hash must move on source edit"
    )
    assert (
        unrelated["drift_source_inventory_hash"]
        != pristine["drift_source_inventory_hash"]
    )

    # 2. Canonical run code_version_hash binds the moving inventory hash
    assert unrelated["code_version_hash"] == unrelated["drift_source_inventory_hash"]
    assert unrelated["code_version_hash"] != pristine["code_version_hash"], (
        "canonical code_version_hash must move with repository tree"
    )

    # 3. Bundle identity remains semantic and stable (Issue 63 property preserved)
    assert unrelated["bundle_hash"] == pristine["bundle_hash"], (
        "bundle_hash must not move on unrelated source edit"
    )

    # 4. Admission identity remains stable
    assert unrelated["admission_hash"] == pristine["admission_hash"], (
        "admission_hash must not move on unrelated source edit"
    )

    # 5. Scientific and economic evaluation outcomes remain identical
    assert unrelated["evaluated_session_count"] == pristine["evaluated_session_count"]
    assert unrelated["committed_fill_count"] == pristine["committed_fill_count"]
    assert unrelated["net_profit_and_loss"] == pristine["net_profit_and_loss"]
    assert unrelated["ending_cash"] == pristine["ending_cash"]
    assert unrelated["ending_net_asset_value"] == pristine["ending_net_asset_value"]

    # 6. Run identity moved specifically because code_version_hash moved
    assert unrelated["run_identity_hash"] != pristine["run_identity_hash"], (
        "run_identity_hash must move when code_version_hash moves"
    )
