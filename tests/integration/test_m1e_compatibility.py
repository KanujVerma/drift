"""Task 1 boundary checks before any M1e production source exists."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).parents[2]
PINNED_M1D_COMMIT = "af75cce0f763de025f8ae3516577a9d0a1acead9"
ALLOWED_M1E_PRODUCTION_PATHS = frozenset(
    {
        "src/drift/domain/qualification.py",
        "src/drift/qualification/__init__.py",
        "src/drift/qualification/lifecycle.py",
        "src/drift/domain/rights.py",
        "src/drift/qualification/rights.py",
        "src/drift/domain/acquisition.py",
        "src/drift/qualification/acquisition.py",
        "src/drift/qualification/store.py",
        "src/drift/domain/source_snapshots.py",
        "src/drift/qualification/snapshots.py",
        "src/drift/domain/qualification_adapters.py",
        "src/drift/domain/golden_cases.py",
        "src/drift/qualification/adapters.py",
        "src/drift/qualification/golden_cases.py",
        "src/drift/qualification/harness.py",
        "src/drift/domain/environment_closure.py",
        "src/drift/domain/qualification_replay.py",
        "src/drift/qualification/environment.py",
        "src/drift/qualification/replay.py",
        "src/drift/qualification/pilot_adapter.py",
        "scripts/intake_m1e_truth.py",
        "scripts/capture_m1e_environment.py",
        "scripts/replay_m1e_offline.py",
        "scripts/acquire_m1e_pilot.py",
        "scripts/qualify_m1e_pilot.py",
    }
)
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "asyncio",
        "boto3",
        "ftplib",
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "webbrowser",
    }
)
FORBIDDEN_DEFINITION_TERMS = frozenset(
    {"agent", "backtest", "broker", "evaluator", "portfolio", "trading"}
)


def _git_paths(ref: str, prefix: str) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", prefix],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return set(filter(None, completed.stdout.splitlines()))


def _m1e_paths_on_disk() -> set[str]:
    candidates: set[str] = set()
    for root in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
        if root.exists():
            candidates.update(
                path.relative_to(REPO_ROOT).as_posix()
                for path in root.rglob("*.py")
                if path.is_file()
            )
    baseline = _git_paths(PINNED_M1D_COMMIT, "src/drift") | _git_paths(
        PINNED_M1D_COMMIT, "scripts"
    )
    return candidates - baseline


def _assert_m1e_module_is_inert(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            assert module.split(".", maxsplit=1)[0] not in FORBIDDEN_IMPORT_ROOTS
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not any(
                term in node.name.lower() for term in FORBIDDEN_DEFINITION_TERMS
            ), f"forbidden M1e capability definition: {node.name}"


def _load_pinned_helper() -> ModuleType:
    helper_path = REPO_ROOT / "tests/_pinned_m1d.py"
    spec = importlib.util.spec_from_file_location("_m1e_pinned_m1d", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_m1e_source_is_absent_until_a_later_owned_task() -> None:
    """Task 1 adds replay tests only, leaving all planned M1e source absent."""
    assert _m1e_paths_on_disk() == set()


def test_m1e_additions_are_allowlisted_inert_and_leave_m1d_pins_unchanged() -> None:
    """Future M1e code is constrained separately from byte-pinned M1d history."""
    present = _m1e_paths_on_disk()
    assert present <= ALLOWED_M1E_PRODUCTION_PATHS
    for relative in present:
        _assert_m1e_module_is_inert(REPO_ROOT / relative)

    helper = _load_pinned_helper()
    helper.verify_m1d_protected_inputs(root=REPO_ROOT)
    assert (REPO_ROOT / "pyproject.toml").read_bytes() == subprocess.run(
        ["git", "show", f"{PINNED_M1D_COMMIT}:pyproject.toml"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert (REPO_ROOT / "uv.lock").read_bytes() == subprocess.run(
        ["git", "show", f"{PINNED_M1D_COMMIT}:uv.lock"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
