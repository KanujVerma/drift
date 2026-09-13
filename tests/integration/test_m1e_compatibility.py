"""Task 1 boundary checks before any M1e production source exists."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parents[2]
PINNED_M1D_COMMIT = "af75cce0f763de025f8ae3516577a9d0a1acead9"
TASK1_M1D_PIN_COMMIT = "1c647bfc8b7c2a61a83cef4468a5a8cd17e9a060"
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
M1E_PRODUCTION_PATHS = frozenset(
    path for path in ALLOWED_M1E_PRODUCTION_PATHS if path.startswith("src/drift/")
)
M1E_SCRIPT_PATHS = frozenset(
    path for path in ALLOWED_M1E_PRODUCTION_PATHS if path.startswith("scripts/")
)
PROCESS_ORCHESTRATION_SCRIPT_PATHS = frozenset(
    {
        "scripts/capture_m1e_environment.py",
        "scripts/replay_m1e_offline.py",
        "scripts/qualify_m1e_pilot.py",
    }
)
ACQUISITION_SCRIPT_PATH = "scripts/acquire_m1e_pilot.py"
NETWORK_IMPORT_ROOTS = frozenset(
    {
        "boto3",
        "ftplib",
        "http",
        "httpx",
        "requests",
        "socket",
        "urllib",
        "webbrowser",
    }
)
PROCESS_IMPORT_ROOTS = frozenset({"asyncio", "multiprocessing", "subprocess"})
FORBIDDEN_PRODUCTION_IMPORT_ROOTS = NETWORK_IMPORT_ROOTS | PROCESS_IMPORT_ROOTS
FORBIDDEN_PROCESS_CALLS = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.fork",
        "os.forkpty",
        "os.popen",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.run",
    }
)
FORBIDDEN_DYNAMIC_CALLS = frozenset(
    {
        "__import__",
        "builtins.exec",
        "builtins.eval",
        "compile",
        "exec",
        "execfile",
        "eval",
        "run_path",
    }
)
NETWORK_OR_CREDENTIAL_DEFINITION_TERMS = frozenset({"credential", "network"})
FORBIDDEN_DEFINITION_TERMS = frozenset(
    {"agent", "backtest", "broker", "evaluator", "portfolio", "trading"}
)
CREDENTIAL_READ_CALLS = frozenset(
    {"keyring.get_password", "os.environ.get", "os.getenv"}
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


def _git_is_ancestor(older: str, newer: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode in {0, 1}, completed.stdout + completed.stderr
    return completed.returncode == 0


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


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".", maxsplit=1)[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _call_path(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _call_path(node.value, aliases)
        return f"{owner}.{node.attr}" if owner is not None else node.attr
    return None


def _assert_definition_allowed(name: str, relative: str, *, script: bool) -> None:
    lowered = name.lower()
    assert not any(term in lowered for term in FORBIDDEN_DEFINITION_TERMS), (
        f"forbidden M1e capability definition: {name}"
    )
    if "process" in lowered:
        assert script and relative in PROCESS_ORCHESTRATION_SCRIPT_PATHS, (
            f"process definition outside planned orchestration script: {name}"
        )
    if any(term in lowered for term in NETWORK_OR_CREDENTIAL_DEFINITION_TERMS):
        assert script and relative == ACQUISITION_SCRIPT_PATH, (
            f"network or credential definition outside acquisition script: {name}"
        )


def _assert_m1e_production_module_allowed(source: str, label: str) -> None:
    tree = ast.parse(source, label)
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            assert (
                module.split(".", maxsplit=1)[0]
                not in FORBIDDEN_PRODUCTION_IMPORT_ROOTS
            )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _assert_definition_allowed(node.name, label, script=False)
        if isinstance(node, ast.Call):
            call_path = _call_path(node.func, aliases)
            assert call_path not in FORBIDDEN_PROCESS_CALLS, (
                f"forbidden M1e process call {call_path} in {label}"
            )
            assert call_path not in FORBIDDEN_DYNAMIC_CALLS, (
                f"forbidden M1e dynamic call {call_path} in {label}"
            )


def _assert_m1e_script_allowed(relative: str, source: str) -> None:
    assert relative in M1E_SCRIPT_PATHS, f"unexpected M1e script: {relative}"
    tree = ast.parse(source, relative)
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            root = module.split(".", maxsplit=1)[0]
            if root in NETWORK_IMPORT_ROOTS:
                assert relative == ACQUISITION_SCRIPT_PATH, (
                    f"network import outside acquisition script: {module}"
                )
            if root in PROCESS_IMPORT_ROOTS:
                assert relative in PROCESS_ORCHESTRATION_SCRIPT_PATHS, (
                    f"process import outside planned orchestration script: {module}"
                )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _assert_definition_allowed(node.name, relative, script=True)
        if isinstance(node, ast.Call):
            call_path = _call_path(node.func, aliases)
            assert call_path not in FORBIDDEN_DYNAMIC_CALLS, (
                f"forbidden M1e dynamic call {call_path} in {relative}"
            )
            if call_path in FORBIDDEN_PROCESS_CALLS:
                assert relative in PROCESS_ORCHESTRATION_SCRIPT_PATHS, (
                    f"process call outside planned orchestration script: {call_path}"
                )
            if call_path in CREDENTIAL_READ_CALLS:
                assert relative == ACQUISITION_SCRIPT_PATH, (
                    f"credential read outside acquisition script: {call_path}"
                )
        if isinstance(node, ast.Subscript):
            access_path = _call_path(node.value, aliases)
            if access_path == "os.environ":
                assert relative == ACQUISITION_SCRIPT_PATH, (
                    "credential read outside acquisition script: os.environ"
                )


def _load_pinned_helper() -> ModuleType:
    helper_path = REPO_ROOT / "tests/_pinned_m1d.py"
    spec = importlib.util.spec_from_file_location("_m1e_pinned_m1d", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_task1_pin_commit_precedes_live_m1e_source_additions() -> None:
    """M1e paths can be added later only after the historical M1d pin exists."""
    assert _git_is_ancestor(PINNED_M1D_COMMIT, TASK1_M1D_PIN_COMMIT)
    assert _git_is_ancestor(TASK1_M1D_PIN_COMMIT, "HEAD")
    pinned_paths = _git_paths(TASK1_M1D_PIN_COMMIT, "src/drift") | _git_paths(
        TASK1_M1D_PIN_COMMIT, "scripts"
    )
    assert not pinned_paths.intersection(ALLOWED_M1E_PRODUCTION_PATHS)


def test_m1e_additions_are_allowlisted_inert_and_leave_m1d_pins_unchanged() -> None:
    """Future M1e code is constrained separately from byte-pinned M1d history."""
    present = _m1e_paths_on_disk()
    assert present <= ALLOWED_M1E_PRODUCTION_PATHS
    for relative in present:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        if relative in M1E_PRODUCTION_PATHS:
            _assert_m1e_production_module_allowed(source, relative)
        else:
            _assert_m1e_script_allowed(relative, source)

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


def test_production_ast_guard_rejects_alias_aware_process_and_dynamic_execution() -> (
    None
):
    """A future M1e module cannot hide local process execution behind aliases."""
    attacks = (
        "import os\nos.system('true')\n",
        "import os as platform\nplatform.system('true')\n",
        "import subprocess as sp\nsp.run(['true'])\n",
        "from os import system as shell\nshell('true')\n",
        "from builtins import exec as execute\nexecute('pass')\n",
        "def run_process() -> None:\n    pass\n",
    )
    for source in attacks:
        with pytest.raises(AssertionError):
            _assert_m1e_production_module_allowed(source, "negative-control.py")


def test_script_ast_guard_partitions_process_and_acquisition_capabilities() -> None:
    """Only planned scripts can orchestrate processes or eventually acquire bytes."""
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/intake_m1e_truth.py",
            "import subprocess\nsubprocess.run(['true'])\n",
        )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/qualify_m1e_pilot.py",
            "import requests\nrequests.get('https://example.invalid')\n",
        )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/qualify_m1e_pilot.py",
            "import os\nos.getenv('M1E_TOKEN')\n",
        )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/replay_m1e_offline.py",
            "import os\nos.environ['M1E_TOKEN']\n",
        )
    _assert_m1e_script_allowed(
        "scripts/capture_m1e_environment.py",
        "import subprocess\nsubprocess.run(['true'])\n",
    )
    _assert_m1e_script_allowed(
        "scripts/acquire_m1e_pilot.py",
        "import requests\nimport os\nrequests.get('https://example.invalid')\nos.getenv('M1E_TOKEN')\n",
    )
