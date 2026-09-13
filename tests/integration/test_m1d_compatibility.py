"""Bounded Task8 compatibility and scope checks for the Drift M1d candidate.

This file is intentionally staged outside the repository.  It derives the
protected M0-M1c expected bytes from the immutable planning baseline with
``git show`` and checks the candidate's working tree against those bytes.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from io import BytesIO
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(
    os.environ.get("DRIFT_REPO_ROOT", str(Path(__file__).parents[2]))
).resolve()
BASELINE = "aecee94207dbd64aa5154fe03295f35566ec7268"
V1_COMMIT = "4d54d7e553beba8cdd5413ea1181e7efac7a236b"
M1C_V2_COMMIT = BASELINE
TASK7_COMMIT = "256154e40121d28cec6a65ebcde223c12563752d"
TASK8_COMMIT = "a909148a941081d8d05c5090794346c5ce54db8c"
HISTORY_MODULE = "tests/integration/test_m1c_economic_history.py"
M1D_V1_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "m1d" / "v1"
M1D_V2_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "m1d" / "v2"
M1D_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "m1d" / "v3"
MATRIX_INDEX = M1D_FIXTURE_ROOT / "matrix-index.json"
HASH_INDEX = M1D_FIXTURE_ROOT / "hash-index.json"
EXPECTED_HASH_INDEX_SHA256 = (
    "f57be824420909b7ee07f7c8062d379515b045a4729602533fd08f266e6f47b5"
)
EXPECTED_V2_HASH_INDEX_SHA256 = (
    "23dd18f8ba2626c6f68906ec3559d4552e8155be4cdca66ef09a6945ece1f2e6"
)
EXPECTED_V1_HASH_INDEX_SHA256 = (
    "9dee138ff8768bf37f7d78d1204ad4a5c92b223a8f0d39d9462561d51dc57c02"
)

# These are the only files introduced by Task1 solely to keep the persisted
# M1c replay lane runnable.  M1d source and tests are additive and are not
# part of this old-contract allowlist.
ALLOWED_TASK1_PINNED_LANE_ADDITIONS = frozenset(
    {
        "tests/_pinned_m1c.py",
        "tests/conftest.py",
        "tests/integration/test_m1c_pinned_replay.py",
        "tests/fixtures/m1d-compatibility/m1c-v2-protected-sha256.json",
    }
)

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "alpaca",
        "asyncio",
        "boto3",
        "broker",
        "builtins",
        "database",
        "ftplib",
        "http",
        "httpx",
        "imaplib",
        "multiprocessing",
        "poplib",
        "requests",
        "robinhood",
        "socket",
        "smtplib",
        "sqlalchemy",
        "sqlite3",
        "subprocess",
        "telnetlib",
        "urllib",
        "webbrowser",
        "xmlrpc",
    }
)
FORBIDDEN_DYNAMIC_CALLS = frozenset(
    {"__import__", "compile", "eval", "exec", "execfile", "popen", "run_path"}
)
FORBIDDEN_PROCESS_CALLS = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.fork",
        "os.forkpty",
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
FORBIDDEN_RUNTIME_DEFINITION_NAMES = frozenset(
    {
        "agent",
        "backtest",
        "broker",
        "credential",
        "database",
        "evaluator",
        "network",
        "portfolio",
        "provider",
        "trading",
    }
)


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout


def _git_paths(ref: str, prefix: str) -> tuple[str, ...]:
    return tuple(
        path
        for path in _git("ls-tree", "-r", "--name-only", ref, "--", prefix).splitlines()
        if path
    )


def _git_bytes(ref: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return completed.stdout


def _run_archived_m1d_replay(commit: str, node: str, label: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"drift-m1d-{label}-replay-") as directory:
        archive_root = Path(directory)
        completed = subprocess.run(
            [
                "git",
                "archive",
                "--format=tar",
                commit,
                "--",
                "src/drift",
                "tests",
                "pyproject.toml",
                "uv.lock",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")
        with tarfile.open(fileobj=BytesIO(completed.stdout), mode="r:") as archive:
            members = archive.getmembers()
            assert not any(
                member.name.startswith("/") or ".." in Path(member.name).parts
                for member in members
            )
            archive.extractall(archive_root, members=members, filter="data")
        environment = dict(os.environ)
        environment.pop("PYTEST_ADDOPTS", None)
        environment["PYTHONPATH"] = os.pathsep.join(
            (
                str(archive_root / "src"),
                str(archive_root / "tests" / "unit"),
                str(archive_root / "tests" / "integration"),
            )
        )
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        imported = subprocess.run(
            [sys.executable, "-c", "import drift; print(drift.__file__)"],
            cwd=archive_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert imported.returncode == 0, imported.stdout + imported.stderr
        assert (
            Path(imported.stdout.strip())
            .resolve()
            .is_relative_to(archive_root.resolve())
        )
        replay = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                node,
            ],
            cwd=archive_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr
        assert "1 passed" in replay.stdout


def _protected_baseline_paths() -> tuple[str, ...]:
    """Independent old-contract path inventory, derived from the baseline tree."""
    source = set(_git_paths(BASELINE, "src/drift"))
    source = {path for path in source if path.endswith(".py")}
    fixture_paths = set(_git_paths(BASELINE, "tests/fixtures"))
    fixture_paths = {path for path in fixture_paths if path.endswith(".json")}
    fixed = {
        "pyproject.toml",
        "uv.lock",
        "tests/integration/test_m1c_economic_history.py",
        "tests/unit/economic_test_support.py",
    }
    return tuple(sorted(source | fixture_paths | fixed))


def _baseline_hashes() -> dict[str, str]:
    return {
        path: hashlib.sha256(_git_bytes(BASELINE, path)).hexdigest()
        for path in _protected_baseline_paths()
    }


def _current_diff() -> list[tuple[str, str]]:
    rows = []
    for line in _git("diff", "--name-status", BASELINE).splitlines():
        status, path, *_ = line.split("\t")
        rows.append((status, path))
    return rows


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_fixture_support() -> ModuleType:
    integration = str(REPO_ROOT / "tests" / "integration")
    if integration not in sys.path:
        sys.path.insert(0, integration)
    path = REPO_ROOT / "tests" / "integration" / "m1d_fixture_support.py"
    return _load_module("_task8_m1d_fixture_support", path)


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


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


def _assert_runtime_ast_allowed(source: str, label: str) -> None:
    tree = ast.parse(source, label)
    aliases = _import_aliases(tree)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            root = module.split(".", maxsplit=1)[0]
            assert root not in FORBIDDEN_IMPORT_ROOTS, f"{label}: import {module}"
            assert root in stdlib or root in {"drift", "pydantic"}, (
                f"new dependency import {module} in {label}"
            )
        if isinstance(node, ast.Call):
            terminal = _terminal_name(node.func)
            call_path = _call_path(node.func, aliases)
            assert terminal not in FORBIDDEN_DYNAMIC_CALLS, (
                f"dynamic execution call {terminal} in {label}"
            )
            assert call_path not in FORBIDDEN_PROCESS_CALLS, (
                f"process execution call {call_path} in {label}"
            )
        if isinstance(node, ast.ClassDef):
            assert node.name.lower() not in FORBIDDEN_RUNTIME_DEFINITION_NAMES, (
                f"capability-shaped runtime class {node.name} in {label}"
            )


def _runtime_additions() -> tuple[Path, ...]:
    additions = []
    for status, path in _current_diff():
        if path.startswith("src/drift/"):
            assert status == "A", f"old runtime source modified: {path}"
            additions.append(REPO_ROOT / path)
    return tuple(sorted(additions))


def test_c01_protected_m0_m1c_bytes_match_planning_baseline() -> None:
    """Canonical, ledger, temporal, identity, economic and fixture bytes stay old."""
    expected = _baseline_hashes()
    assert len(expected) == 148
    inventory_path = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "m1d-compatibility"
        / "m1c-v2-protected-sha256.json"
    )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["commit"] == BASELINE
    pinned_subset = inventory["sha256"]
    assert len(pinned_subset) == 126
    assert set(pinned_subset).issubset(expected)
    assert all(expected[path] == digest for path, digest in pinned_subset.items())
    for path, digest in expected.items():
        current = REPO_ROOT / path
        assert current.is_file(), path
        assert hashlib.sha256(current.read_bytes()).hexdigest() == digest, path

    changed_paths = {path for _status, path in _current_diff()}
    assert not changed_paths.intersection(expected), "protected old path changed"


def test_c01_legacy_contracts_are_exercised_by_the_current_compatibility_tests() -> (
    None
):
    """Byte checks accompany canonical, ledger, temporal, identity and economic
    tests.
    """
    nodes = (
        "tests/integration/test_m1_m0_compatibility.py::"
        "test_m0_fixture_serialization_and_event_hashes_are_unchanged",
        "tests/integration/test_replay.py::"
        "test_replay_verifies_integrity_before_returning_events",
        "tests/integration/test_m1b_m1a_compatibility.py::"
        "test_m1a_manifest_decision_and_events_keep_their_canonical_identity",
        "tests/unit/test_assertions.py::test_cutoff_selection_does_not_use_later_correction",
        "tests/unit/test_security_identity.py::"
        "test_assignment_resolution_rebuilds_the_same_internal_identity",
        "tests/integration/test_m1c_action_matrix.py::test_m1c_selected_value_substitution",
    )
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *nodes],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "6 passed" in completed.stdout, completed.stdout


def test_c02_actual_pinned_v1_and_v2_m1c_replay_executes() -> None:
    """Both archived interpreters execute tests, rather than only checking hashes."""
    helper = _load_module("_task8_pinned_m1c", REPO_ROOT / "tests" / "_pinned_m1c.py")
    v1 = helper.run_archived_v1_cases()
    assert v1.returncode == 0, v1.output
    assert v1.case_count == 4
    assert len(helper.REPLAY_TEST_NAMES) == 6
    for name in sorted(helper.REPLAY_TEST_NAMES):
        result = helper.run_archived_node(M1C_V2_COMMIT, f"{HISTORY_MODULE}::{name}")
        assert result.returncode == 0, result.output


def test_c02_current_code_composes_m1c_into_fixture_only_m1d_replay() -> None:
    """The public fixture runner verifies M1c context plus M1d materialization."""
    support = _load_fixture_support()
    fixture = support.load_m1d_fixture_v3()
    assert fixture.context.economic_context is not None
    assert fixture.context.economic_source_policy is not None
    for result in (fixture.decision_result, fixture.outcome_result):
        support.assert_roundtrip_replays(result, fixture.context)
        assert result.reference is not None
        assert result.derivation is not None
        assert result.dependency_hashes
        assert support.materialize_result(result, fixture.context) == result.view
    assert fixture.decision_query.observation.input_context_hash == (
        support.m1d_context_hash(fixture.context)
    )


def test_task7_matrix_fixture_and_c03_pointer_are_current_and_complete() -> None:
    """Task7's exact 81-row index and the deferred C03 pointer remain connected."""
    matrix = json.loads(MATRIX_INDEX.read_text(encoding="utf-8"))
    rows = matrix["rows"]
    identifiers = [row["id"] for row in rows]
    assert len(rows) == 81
    assert len(set(identifiers)) == 81
    assert identifiers == sorted(identifiers)
    c03 = [row for row in rows if row["id"] == "C03"]
    assert c03 == [
        {
            "coverage": "task8",
            "id": "C03",
            "pointers": [
                "tests/integration/test_m1d_compatibility.py::"
                "test_c03_forbidden_runtime_capabilities_and_dependencies_remain_absent"
            ],
        }
    ]

    raw_index = HASH_INDEX.read_bytes()
    assert hashlib.sha256(raw_index).hexdigest() == EXPECTED_HASH_INDEX_SHA256
    index = json.loads(raw_index)
    declared = {entry["path"] for entry in index["entries"]}
    actual = {
        path.relative_to(M1D_FIXTURE_ROOT).as_posix()
        for path in M1D_FIXTURE_ROOT.rglob("*")
        if path.is_file()
    }
    assert len(actual) == 160
    assert actual == declared | {"hash-index.json"}
    assert len(declared) == 159
    for entry in index["entries"]:
        data = (M1D_FIXTURE_ROOT / entry["path"]).read_bytes()
        assert len(data) == entry["byte_size"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]


def test_m1d_v1_bytes_match_task7_and_replay_under_archived_code() -> None:
    """Accepted v1 stays byte-exact and executes only with its pinned package."""
    paths = _git_paths(TASK7_COMMIT, "tests/fixtures/m1d/v1")
    assert len(paths) == 160
    assert (
        hashlib.sha256(
            (M1D_V1_FIXTURE_ROOT / "hash-index.json").read_bytes()
        ).hexdigest()
        == EXPECTED_V1_HASH_INDEX_SHA256
    )
    for path in paths:
        assert (REPO_ROOT / path).read_bytes() == _git_bytes(TASK7_COMMIT, path)
    _run_archived_m1d_replay(
        TASK7_COMMIT,
        "tests/integration/test_m1d_adversarial_matrix.py::"
        "test_task7_expected_decision_and_outcome_bytes_replay",
        "v1",
    )


def test_m1d_v2_bytes_match_task8_and_replay_under_archived_code() -> None:
    """Accepted v2 stays byte-exact and executes only with Task 8 code."""
    paths = _git_paths(TASK8_COMMIT, "tests/fixtures/m1d/v2")
    assert len(paths) == 160
    assert (
        hashlib.sha256(
            (M1D_V2_FIXTURE_ROOT / "hash-index.json").read_bytes()
        ).hexdigest()
        == EXPECTED_V2_HASH_INDEX_SHA256
    )
    for path in paths:
        assert (REPO_ROOT / path).read_bytes() == _git_bytes(TASK8_COMMIT, path)
    _run_archived_m1d_replay(
        TASK8_COMMIT,
        "tests/integration/test_m1d_adversarial_matrix.py::"
        "test_task7_expected_decision_and_outcome_bytes_replay",
        "v2",
    )


def test_c03_forbidden_runtime_capabilities_and_dependencies_remain_absent() -> None:
    """No external provider, network, process, or dependency capability was added."""
    baseline_pyproject = _git_bytes(BASELINE, "pyproject.toml")
    baseline_lock = _git_bytes(BASELINE, "uv.lock")
    assert (REPO_ROOT / "pyproject.toml").read_bytes() == baseline_pyproject
    assert (REPO_ROOT / "uv.lock").read_bytes() == baseline_lock
    assert b'requires-python = ">=3.14"' in baseline_pyproject

    metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["requires-python"] == ">=3.14"
    assert not any(
        path.startswith("pyproject.toml") or path.startswith("uv.lock")
        for _status, path in _current_diff()
    )

    runtime_files = _runtime_additions()
    assert len(runtime_files) == 14
    for path in runtime_files:
        _assert_runtime_ast_allowed(path.read_text(encoding="utf-8"), str(path))

    # A generator's lock is temporary test machinery; it must not leak into
    # the candidate repository or fixture tree.
    assert not list(REPO_ROOT.rglob(".v1.generation.lock"))
    assert not list(REPO_ROOT.rglob(".v2.generation.lock"))
    assert not list(REPO_ROOT.rglob(".v3.generation.lock"))


def test_c03_ast_guard_rejects_process_and_network_but_allows_local_identity() -> None:
    attacks = (
        "import subprocess\nsubprocess.run(['true'])\n",
        "import subprocess as sp\nsp.run(['true'])\n",
        "import http.client\nhttp.client.HTTPSConnection('example.invalid')\n",
        "import os\nos.system('true')\n",
        "from os import system as run\nrun('true')\n",
        "from asyncio import create_subprocess_exec as spawn\nspawn('true')\n",
        "from builtins import exec as execute\nexecute('pass')\n",
        "import asyncio\nasyncio.open_connection('example.invalid', 443)\n",
    )
    for source in attacks:
        with pytest.raises(AssertionError):
            _assert_runtime_ast_allowed(source, "negative-control.py")

    _assert_runtime_ast_allowed(
        "from pathlib import Path\nPath('uv.lock').read_bytes()\n",
        "local-identity-control.py",
    )


def test_task1_pinned_lane_additions_are_explicit_and_no_old_contract_is_re_signed(  # noqa: E501
) -> None:
    """Any Task1 compatibility additions are named; the old path set stays closed."""
    additions = {
        path
        for status, path in _current_diff()
        if status == "A" and path in ALLOWED_TASK1_PINNED_LANE_ADDITIONS
    }
    assert additions == ALLOWED_TASK1_PINNED_LANE_ADDITIONS
    pinned = json.loads(
        (
            REPO_ROOT
            / "tests"
            / "fixtures"
            / "m1d-compatibility"
            / "m1c-v2-protected-sha256.json"
        ).read_text(encoding="utf-8")
    )["sha256"]
    assert len(pinned) == 126
    assert set(pinned).issubset(_baseline_hashes())
