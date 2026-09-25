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
import tomllib
from collections.abc import Callable
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
PINNED_M1D_COMMIT = "af75cce0f763de025f8ae3516577a9d0a1acead9"
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
        "tests/_pinned_m1d.py",
        "tests/conftest.py",
        "tests/integration/test_m1c_pinned_replay.py",
        "tests/integration/test_m1d_pinned_replay.py",
        "tests/integration/test_m1e_compatibility.py",
        "tests/fixtures/m1d-compatibility/m1c-v2-protected-sha256.json",
        "tests/fixtures/m1e-compatibility/m1d-v3-protected-sha256.json",
        # v4 supersedes v3 as the working-tree freeze under issue #32.  v3
        # stays above, unedited, as the historical af75cce inventory.
        "tests/fixtures/m1e-compatibility/m1d-v4-protected-sha256.json",
        # v5 supersedes v4 under issue #63.  v4 stays above, unedited, as the
        # inventory that exactly describes commit 4ad90aa.
        "tests/fixtures/m1e-compatibility/m1d-v5-protected-sha256.json",
        # v6 supersedes v5 under issue #107.  v5 stays above, unedited, as the
        # inventory that exactly describes commit 200bfeb.
        "tests/fixtures/m1e-compatibility/m1d-v6-protected-sha256.json",
        # v7 supersedes v6 under issue #63 stage 2.  v6 stays above, unedited,
        # as the inventory that exactly describes commit a906ab2.
        "tests/fixtures/m1e-compatibility/m1d-v7-protected-sha256.json",
        # m1c-v3 supersedes m1c-v2 under issue #63 stage 2, the first M1c
        # supersession link.  m1c-v2 stays above, unedited, as the inventory
        # that exactly describes commit aecee94 and authenticates its archive.
        "tests/fixtures/m1d-compatibility/m1c-v3-protected-sha256.json",
    }
)
HISTORICAL_M1D_INVENTORY = (
    REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v3-protected-sha256.json"
)
PREVIOUS_M1D_INVENTORY = (
    REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v4-protected-sha256.json"
)
V5_M1D_INVENTORY = (
    REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v5-protected-sha256.json"
)
V6_M1D_INVENTORY = (
    REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v6-protected-sha256.json"
)
CURRENT_M1D_INVENTORY = (
    REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v7-protected-sha256.json"
)
HISTORICAL_M1D_INVENTORY_SHA256 = (
    "6fb819eb863ebf83e1a3b4e3a7e6af261748116502cdb0ad3603d108d17c2e2b"
)
PREVIOUS_M1D_INVENTORY_SHA256 = (
    "4af2e06734e8fadde2002d69fe9d48bd5eca369e771862f2e09df150238d76d2"
)
PREVIOUS_M1D_INVENTORY_COMMIT = "4ad90aa97da677386ac212c3596703fccb309f3b"
"""The commit that last wrote v4; every v4 pin describes that commit exactly."""
V5_M1D_INVENTORY_SHA256 = (
    "a4610db34e6588ee7e0f232f39f2a50a98109f0299533f2509f5963b16200710"
)
V5_M1D_INVENTORY_COMMIT = "200bfebaf04c5c1e171db029547a75187d2ef665"
"""The commit that last wrote v5; every v5 pin describes that commit exactly."""
V6_M1D_INVENTORY_SHA256 = (
    "b99a435fd6f420ec7427a49c0fce877fd5b369ce51b98e09e90d3585e9cf252e"
)
V6_M1D_INVENTORY_COMMIT = "a906ab293d5690084bb82415c7dcb09cc14903f3"
"""The commit that last wrote v6; every v6 pin describes that commit exactly."""
M1C_V2_INVENTORY = (
    REPO_ROOT / "tests/fixtures/m1d-compatibility/m1c-v2-protected-sha256.json"
)
M1C_V3_INVENTORY = (
    REPO_ROOT / "tests/fixtures/m1d-compatibility/m1c-v3-protected-sha256.json"
)
M1C_STAMP_SITE_PATHS = frozenset(
    {
        "src/drift/markets/economic_outcomes.py",
        "src/drift/markets/economic_selection.py",
        "src/drift/markets/economic_validation.py",
    }
)
"""The only old-contract paths the M1c link supersedes (issue 63 stage 2).

Stated here independently of the link, so a link that named more paths could
not exempt them from the planning-baseline checks below."""

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


def _run_archived_m1d_replay(generation: str, nodes: tuple[str, ...]) -> None:
    """Replay nodes under one generation's own source commit.

    The shared pinned-replay helper verifies the exact interpreter identity
    before extracting anything, authenticates the archive, and classifies any
    failure as an environment, artifact, semantic, or integrity failure.
    """
    helper = _load_module("_task8_pinned_m1d", REPO_ROOT / "tests" / "_pinned_m1d.py")
    result = helper.run_m1d_generation_replay(generation, nodes)
    assert result.returncode == 0, result.output


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
    for path in _git("ls-files", "--others", "--exclude-standard").splitlines():
        if path:
            rows.append(("A", path))
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
    """Every added runtime path; an old one may move only through the M1c link.

    The paths the M1c link supersedes are modified, not added, and their exact
    bytes are held to the link's current pins by ``test_c01``.
    """
    superseded = _m1c_superseded_paths()
    additions = []
    for status, path in _current_diff():
        if path.startswith("src/drift/"):
            if path in superseded:
                assert status == "M", f"superseded old runtime source {status}: {path}"
                continue
            assert status == "A", f"old runtime source modified: {path}"
            additions.append(REPO_ROOT / path)
    return tuple(sorted(additions))


def _accepted_m1d_runtime_paths() -> tuple[str, ...]:
    """Return the finite M1d source additions, not a prohibition on M1e source."""
    baseline = set(_git_paths(BASELINE, "src/drift"))
    accepted = set(_git_paths(PINNED_M1D_COMMIT, "src/drift"))
    return tuple(sorted(path for path in accepted - baseline if path.endswith(".py")))


def _accepted_m1d_source_paths() -> tuple[str, ...]:
    return tuple(
        path
        for path in _git_paths(PINNED_M1D_COMMIT, "src/drift")
        if path.endswith(".py")
    )


def _current_m1d_inventory() -> dict[str, object]:
    document = json.loads(CURRENT_M1D_INVENTORY.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _previous_m1d_inventory() -> dict[str, object]:
    document = json.loads(PREVIOUS_M1D_INVENTORY.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _v5_m1d_inventory() -> dict[str, object]:
    document = json.loads(V5_M1D_INVENTORY.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _v6_m1d_inventory() -> dict[str, object]:
    document = json.loads(V6_M1D_INVENTORY.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _m1c_link() -> dict[str, object]:
    document = json.loads(M1C_V3_INVENTORY.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _m1c_superseded_paths() -> dict[str, dict[str, str]]:
    """The M1c link's supersessions, held to the independently stated paths."""
    superseded = _m1c_link()["superseded_paths"]
    assert isinstance(superseded, dict)
    assert set(superseded) == M1C_STAMP_SITE_PATHS
    return superseded


def _superseded_m1d_source_pins() -> dict[str, str]:
    """Return the accepted current sha256 of each superseded M1d source path.

    These are the only accepted M1d source paths whose bytes are allowed to
    differ from ``PINNED_M1D_COMMIT``.  Each one still has to match an exact
    pinned digest recorded in the current inventory, so the byte freeze is
    moved forward rather than relaxed.  A path can be superseded by any link
    of the chain (v4 under issue #32, v5 under issue #63, v6 under issue
    #107, v7 under issue #63 stage 2); the latest link that names it carries
    the digest the working tree must match.
    """
    current = _current_m1d_inventory()
    pins = current["sha256"]
    assert isinstance(pins, dict)
    historical = json.loads(HISTORICAL_M1D_INVENTORY.read_text(encoding="utf-8"))[
        "sha256"
    ]
    latest: dict[str, str] = {}
    for document in (
        _previous_m1d_inventory(),
        _v5_m1d_inventory(),
        _v6_m1d_inventory(),
        current,
    ):
        superseded = document["superseded_paths"]
        assert isinstance(superseded, dict) and superseded
        for path, record in superseded.items():
            assert path.startswith("src/drift/"), path
            assert record["historical_sha256"] != record["current_sha256"], path
            latest[path] = record["current_sha256"]
    resolved: dict[str, str] = {}
    for path, digest in latest.items():
        assert digest == pins[path], path
        if path in historical:
            resolved[path] = digest
    moved = {
        path
        for path, digest in historical.items()
        if path.startswith("src/drift/") and pins[path] != digest
    }
    assert moved == set(resolved)
    return resolved


def _m1c_baseline_violations(
    expected: dict[str, str],
    superseded: dict[str, dict[str, str]],
    read_bytes: Callable[[str], bytes | None],
    changed_paths: set[str],
) -> list[str]:
    """Every way the working tree departs from the planning baseline.

    A protected path must hold its baseline bytes, except exactly the paths the
    M1c link supersedes (issue 63 stage 2), which must hold the link's current
    bytes instead and whose historical side must be the baseline bytes. The
    diff against the baseline may touch exactly those paths and no other
    protected one.
    """
    violations: list[str] = []
    accepted = dict(expected)
    for path, record in superseded.items():
        if path not in expected:
            violations.append(f"supersedes an unprotected path: {path}")
            continue
        if record["historical_sha256"] != expected[path]:
            violations.append(f"misstates the baseline bytes of {path}")
        accepted[path] = record["current_sha256"]
    for path, digest in accepted.items():
        data = read_bytes(path)
        if data is None:
            violations.append(f"protected path is missing: {path}")
        elif hashlib.sha256(data).hexdigest() != digest:
            violations.append(f"protected old path changed: {path}")
    touched = changed_paths.intersection(expected)
    if touched != set(superseded):
        violations.append(
            f"diff touches protected paths {sorted(touched)}, "
            f"not exactly the superseded {sorted(superseded)}"
        )
    return violations


def _live_bytes(path: str) -> bytes | None:
    current = REPO_ROOT / path
    return current.read_bytes() if current.is_file() else None


def test_c01_protected_m0_m1c_bytes_match_planning_baseline() -> None:
    """Canonical, ledger, temporal, identity, economic and fixture bytes stay old.

    The single exception is the M1c supersession link of issue 63 stage 2: the
    three M1c stamp-site modules moved to the M1c semantic attestations, so
    they hold the link's pinned current bytes instead. The freeze is moved
    forward for exactly those paths, not relaxed.
    """
    expected = _baseline_hashes()
    assert len(expected) == 148
    inventory = json.loads(M1C_V2_INVENTORY.read_text(encoding="utf-8"))
    assert inventory["commit"] == BASELINE
    pinned_subset = inventory["sha256"]
    assert len(pinned_subset) == 126
    assert set(pinned_subset).issubset(expected)
    assert all(expected[path] == digest for path, digest in pinned_subset.items())

    link = _m1c_link()
    assert link["baseline_commit"] == BASELINE
    supersedes = link["supersedes"]
    assert isinstance(supersedes, dict)
    assert supersedes["commit"] == BASELINE
    assert (
        supersedes["file_sha256"]
        == hashlib.sha256(M1C_V2_INVENTORY.read_bytes()).hexdigest()
    )
    superseded = _m1c_superseded_paths()
    for path, record in superseded.items():
        assert path in pinned_subset, path
        assert (
            record["historical_sha256"]
            == hashlib.sha256(_git_bytes(BASELINE, path)).hexdigest()
        ), path

    changed_paths = {path for _status, path in _current_diff()}
    assert (
        _m1c_baseline_violations(expected, superseded, _live_bytes, changed_paths) == []
    )


def test_c01_rejects_an_undeclared_protected_change_beside_the_m1c_link() -> None:
    """Negative controls: the supersession exempts its own paths and no other."""
    expected = _baseline_hashes()
    superseded = _m1c_superseded_paths()
    changed_paths = {path for _status, path in _current_diff()}
    undeclared = "src/drift/domain/temporal.py"
    assert undeclared in expected and undeclared not in superseded

    def tampered(path: str) -> bytes | None:
        data = _live_bytes(path)
        return b"tampered" if path == undeclared else data

    assert _m1c_baseline_violations(expected, superseded, tampered, changed_paths) == [
        f"protected old path changed: {undeclared}"
    ]
    # The diff rule stands on its own: touching an undeclared protected path is
    # refused even when its bytes happen to match.
    assert _m1c_baseline_violations(
        expected, superseded, _live_bytes, changed_paths | {undeclared}
    ) == [
        f"diff touches protected paths {sorted(set(superseded) | {undeclared})}, "
        f"not exactly the superseded {sorted(superseded)}"
    ]
    # A superseded path is held to the link's current bytes, not the baseline.
    stale = next(iter(sorted(superseded)))

    def reverted(path: str) -> bytes | None:
        return _git_bytes(BASELINE, path) if path == stale else _live_bytes(path)

    assert _m1c_baseline_violations(expected, superseded, reverted, changed_paths) == [
        f"protected old path changed: {stale}"
    ]
    # A link that misstates the baseline bytes of a path it supersedes fails.
    misstated = json.loads(json.dumps(superseded))
    misstated[stale]["historical_sha256"] = "1" * 64
    assert _m1c_baseline_violations(
        expected, misstated, _live_bytes, changed_paths
    ) == [f"misstates the baseline bytes of {stale}"]


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
    # The replay runs against the cpython-3.14.6 baseline that supersedes these
    # historical bytes (issue #48); the generator node proves TASK7_COMMIT
    # itself regenerates that baseline byte-for-byte.
    _run_archived_m1d_replay(
        "v1",
        (
            "tests/integration/test_m1d_adversarial_matrix.py::"
            "test_task7_v1_fixture_hash_index_is_exact",
            "tests/integration/test_m1d_adversarial_matrix.py::"
            "test_task7_v1_generator_reproduces_exact_bytes_and_refuses_overwrite",
            "tests/integration/test_m1d_adversarial_matrix.py::"
            "test_task7_expected_decision_and_outcome_bytes_replay",
        ),
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
    # The replay runs against the cpython-3.14.6 baseline that supersedes these
    # historical bytes (issue #48); the generator node proves TASK8_COMMIT
    # itself regenerates that baseline byte-for-byte.
    _run_archived_m1d_replay(
        "v2",
        (
            "tests/integration/test_m1d_adversarial_matrix.py::"
            "test_current_v2_fixture_hash_index_is_exact",
            "tests/integration/test_m1d_adversarial_matrix.py::"
            "test_v2_generator_reproduces_exact_bytes_and_refuses_both_versions",
            "tests/integration/test_m1d_adversarial_matrix.py::"
            "test_task7_expected_decision_and_outcome_bytes_replay",
        ),
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

    accepted_additions = _accepted_m1d_runtime_paths()
    assert len(accepted_additions) == 14
    assert set(_runtime_additions()) >= {
        REPO_ROOT / path for path in accepted_additions
    }
    superseded = _superseded_m1d_source_pins()
    for relative in _accepted_m1d_source_paths():
        path = REPO_ROOT / relative
        if relative in superseded:
            # Superseded under issue #32, #63 (both stages) or #107: still
            # byte-pinned, but against the current inventory instead of
            # PINNED_M1D_COMMIT.
            assert (
                hashlib.sha256(path.read_bytes()).hexdigest() == superseded[relative]
            ), relative
        else:
            assert path.read_bytes() == _git_bytes(PINNED_M1D_COMMIT, relative), (
                relative
            )
    for relative in accepted_additions:
        path = REPO_ROOT / relative
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


def test_v3_source_pins_are_superseded_by_v4_without_rewriting_history() -> None:
    """v3 stays the historical inventory; v4 carries the declared delta only.

    v4 is itself superseded by v5 under issue #63, so it no longer describes
    the working tree.  It still describes commit 4ad90aa exactly, and that is
    what is checked here.
    """
    historical_raw = HISTORICAL_M1D_INVENTORY.read_bytes()
    assert (
        hashlib.sha256(historical_raw).hexdigest() == HISTORICAL_M1D_INVENTORY_SHA256
    ), "the historical M1d inventory must stay byte-identical for audit"
    historical = json.loads(historical_raw)
    assert historical["commit"] == PINNED_M1D_COMMIT
    assert len(historical["sha256"]) == 544

    previous_raw = PREVIOUS_M1D_INVENTORY.read_bytes()
    assert hashlib.sha256(previous_raw).hexdigest() == PREVIOUS_M1D_INVENTORY_SHA256
    assert previous_raw == _git_bytes(
        PREVIOUS_M1D_INVENTORY_COMMIT,
        PREVIOUS_M1D_INVENTORY.relative_to(REPO_ROOT).as_posix(),
    ), "v4 must stay byte-identical to the commit that last wrote it"
    previous = json.loads(previous_raw)
    assert previous["inventory_id"] == "m1d-v4-protected-sha256"
    assert previous["baseline_commit"] == PINNED_M1D_COMMIT
    supersedes = previous["supersedes"]
    assert isinstance(supersedes, dict)
    assert supersedes["inventory_id"] == "m1d-v3-protected-sha256"
    assert supersedes["commit"] == PINNED_M1D_COMMIT
    assert supersedes["file_sha256"] == HISTORICAL_M1D_INVENTORY_SHA256
    assert supersedes["issue"] == 32
    assert "semantic attestation" in supersedes["reason"]

    superseded = previous["superseded_paths"]
    assert set(superseded) == {
        "src/drift/markets/observation_validation.py",
        "src/drift/markets/session_validation.py",
    }
    source_commit = previous["source_commit"]
    assert isinstance(source_commit, str)
    assert _git("merge-base", "--is-ancestor", source_commit, "HEAD") == ""
    assert (
        _git("merge-base", "--is-ancestor", PREVIOUS_M1D_INVENTORY_COMMIT, "HEAD") == ""
    )

    added = previous["added_paths"]
    assert isinstance(added, dict) and added
    assert set(added) == {"src/drift/domain/semantic_attestation.py"}
    assert not set(added) & set(historical["sha256"])

    # The supersession is exactly reproducible: v4 is v3 with the declared
    # paths taken from source_commit, plus the declared additions as they
    # stood when v4 was last written, and nothing else touched.
    expected = dict(historical["sha256"])
    for relative, record in superseded.items():
        digest = record["current_sha256"]
        assert (
            hashlib.sha256(_git_bytes(source_commit, relative)).hexdigest() == digest
        ), relative
        expected[relative] = digest
    for relative, record in added.items():
        assert record["issue"] == 32, relative
        assert isinstance(record["justification"], str), relative
        assert record["justification"].strip(), relative
        recorded = _git_bytes(PREVIOUS_M1D_INVENTORY_COMMIT, relative)
        assert hashlib.sha256(recorded).hexdigest() == record["current_sha256"], (
            relative
        )
        expected[relative] = record["current_sha256"]
    assert previous["sha256"] == expected


def test_v4_source_pins_are_superseded_by_v5_without_rewriting_history() -> None:
    """v5 is v4 with exactly the paths issue #63 moved, and nothing else.

    The historical side of every superseded path is the byte content at the
    commit v4 describes. v5 is itself superseded by v6 under issue #107, so
    its current side is the byte content at 200bfeb, the commit that last
    wrote v5, rather than the working tree.
    """
    previous = _previous_m1d_inventory()
    v5_raw = V5_M1D_INVENTORY.read_bytes()
    assert hashlib.sha256(v5_raw).hexdigest() == V5_M1D_INVENTORY_SHA256
    assert v5_raw == _git_bytes(
        V5_M1D_INVENTORY_COMMIT, V5_M1D_INVENTORY.relative_to(REPO_ROOT).as_posix()
    ), "v5 must stay byte-identical to the commit that last wrote it"
    assert _git("merge-base", "--is-ancestor", V5_M1D_INVENTORY_COMMIT, "HEAD") == ""
    v5 = json.loads(v5_raw)
    assert v5["inventory_id"] == "m1d-v5-protected-sha256"
    # v5 still calls itself current: history is superseded, never rewritten.
    assert v5["role"] == "current"
    assert v5["baseline_commit"] == PINNED_M1D_COMMIT
    supersedes = v5["supersedes"]
    assert isinstance(supersedes, dict)
    assert supersedes["inventory_id"] == "m1d-v4-protected-sha256"
    assert (
        supersedes["path"] == PREVIOUS_M1D_INVENTORY.relative_to(REPO_ROOT).as_posix()
    )
    assert supersedes["file_sha256"] == PREVIOUS_M1D_INVENTORY_SHA256
    assert supersedes["commit"] == PREVIOUS_M1D_INVENTORY_COMMIT
    assert supersedes["issue"] == 63
    assert "semantic attestation" in supersedes["reason"]

    superseded = v5["superseded_paths"]
    assert isinstance(superseded, dict)
    assert set(superseded) == {
        "src/drift/domain/observation_query.py",
        "src/drift/domain/semantic_attestation.py",
    }
    assert v5["added_paths"] == {}

    previous_pins = previous["sha256"]
    assert isinstance(previous_pins, dict)
    expected = dict(previous_pins)
    for relative, record in superseded.items():
        recorded = _git_bytes(PREVIOUS_M1D_INVENTORY_COMMIT, relative)
        assert (
            hashlib.sha256(recorded).hexdigest()
            == record["historical_sha256"]
            == previous_pins[relative]
        ), relative
        written = _git_bytes(V5_M1D_INVENTORY_COMMIT, relative)
        assert hashlib.sha256(written).hexdigest() == record["current_sha256"], relative
        assert record["current_sha256"] != record["historical_sha256"], relative
        expected[relative] = record["current_sha256"]
    assert v5["sha256"] == expected


def test_v5_source_pins_are_superseded_by_v6_without_rewriting_history() -> None:
    """v6 is v5 with exactly the path issue #107 moved, and nothing else.

    The historical side of the superseded path is the byte content at 200bfeb,
    the commit v5 describes. v6 is itself superseded by v7 under issue #63
    stage 2, so its current side is the byte content at a906ab2, the commit
    that last wrote v6, rather than the working tree.
    """
    v5 = _v5_m1d_inventory()
    v6_raw = V6_M1D_INVENTORY.read_bytes()
    assert hashlib.sha256(v6_raw).hexdigest() == V6_M1D_INVENTORY_SHA256
    assert v6_raw == _git_bytes(
        V6_M1D_INVENTORY_COMMIT, V6_M1D_INVENTORY.relative_to(REPO_ROOT).as_posix()
    ), "v6 must stay byte-identical to the commit that last wrote it"
    assert _git("merge-base", "--is-ancestor", V6_M1D_INVENTORY_COMMIT, "HEAD") == ""
    v6 = json.loads(v6_raw)
    assert v6["inventory_id"] == "m1d-v6-protected-sha256"
    # v6 still calls itself current: history is superseded, never rewritten.
    assert v6["role"] == "current"
    assert v6["baseline_commit"] == PINNED_M1D_COMMIT
    supersedes = v6["supersedes"]
    assert isinstance(supersedes, dict)
    assert supersedes["inventory_id"] == "m1d-v5-protected-sha256"
    assert supersedes["path"] == V5_M1D_INVENTORY.relative_to(REPO_ROOT).as_posix()
    assert supersedes["file_sha256"] == V5_M1D_INVENTORY_SHA256
    assert supersedes["commit"] == V5_M1D_INVENTORY_COMMIT
    assert supersedes["issue"] == 107
    assert "closure guard" in supersedes["reason"]

    superseded = v6["superseded_paths"]
    assert isinstance(superseded, dict)
    assert set(superseded) == {"src/drift/domain/semantic_attestation.py"}
    assert v6["added_paths"] == {}

    v5_pins = v5["sha256"]
    assert isinstance(v5_pins, dict)
    expected = dict(v5_pins)
    for relative, record in superseded.items():
        recorded = _git_bytes(V5_M1D_INVENTORY_COMMIT, relative)
        assert (
            hashlib.sha256(recorded).hexdigest()
            == record["historical_sha256"]
            == v5_pins[relative]
        ), relative
        written = _git_bytes(V6_M1D_INVENTORY_COMMIT, relative)
        assert hashlib.sha256(written).hexdigest() == record["current_sha256"], relative
        assert record["current_sha256"] != record["historical_sha256"], relative
        expected[relative] = record["current_sha256"]
    assert v6["sha256"] == expected


def test_v6_source_pins_are_superseded_by_v7_without_rewriting_history() -> None:
    """v7 is v6 with exactly the paths issue #63 stage 2 moved, and nothing else.

    Stage 2 moved the M1c identities onto the M1c semantic attestations, which
    changed the attestation module and the three M1c stamp-site modules. The
    historical side of every superseded path is the byte content at a906ab2,
    the commit v6 describes; the current side is the working tree.
    """
    v6 = _v6_m1d_inventory()
    current = _current_m1d_inventory()
    assert current["inventory_id"] == "m1d-v7-protected-sha256"
    assert current["role"] == "current"
    assert current["baseline_commit"] == PINNED_M1D_COMMIT
    supersedes = current["supersedes"]
    assert isinstance(supersedes, dict)
    assert supersedes["inventory_id"] == "m1d-v6-protected-sha256"
    assert supersedes["path"] == V6_M1D_INVENTORY.relative_to(REPO_ROOT).as_posix()
    assert supersedes["file_sha256"] == V6_M1D_INVENTORY_SHA256
    assert supersedes["commit"] == V6_M1D_INVENTORY_COMMIT
    assert supersedes["issue"] == 63
    assert "semantic attestation" in supersedes["reason"]

    superseded = current["superseded_paths"]
    assert isinstance(superseded, dict)
    assert set(superseded) == {
        "src/drift/domain/semantic_attestation.py",
        *M1C_STAMP_SITE_PATHS,
    }
    assert current["added_paths"] == {}

    v6_pins = v6["sha256"]
    assert isinstance(v6_pins, dict)
    expected = dict(v6_pins)
    for relative, record in superseded.items():
        recorded = _git_bytes(V6_M1D_INVENTORY_COMMIT, relative)
        assert (
            hashlib.sha256(recorded).hexdigest()
            == record["historical_sha256"]
            == v6_pins[relative]
        ), relative
        live = (REPO_ROOT / relative).read_bytes()
        assert hashlib.sha256(live).hexdigest() == record["current_sha256"], relative
        assert record["current_sha256"] != record["historical_sha256"], relative
        expected[relative] = record["current_sha256"]
    assert current["sha256"] == expected

    # The M1d and M1c links agree on the three M1c stamp-site modules.
    m1c = _m1c_superseded_paths()
    for relative in M1C_STAMP_SITE_PATHS:
        assert (
            m1c[relative]["current_sha256"] == superseded[relative]["current_sha256"]
        ), relative
