"""Isolated, byte-pinned M1c replay support used only by pytest tests."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Mapping
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

V1_INTERPRETER_COMMIT = "4d54d7e553beba8cdd5413ea1181e7efac7a236b"
V2_INTERPRETER_COMMIT = "aecee94207dbd64aa5154fe03295f35566ec7268"
HISTORY_MODULE = "tests/integration/test_m1c_economic_history.py"
REPLAY_TEST_NAMES = frozenset(
    {
        "test_m1c_fixture_preserves_installment_lineage",
        "test_m1c_fixture_selects_corrected_installment_revision",
        "test_m1c_fixture_rejects_pinned_partition_tampering",
        "test_m1c_fixture_rejects_expected_hash_index_tampering",
        "test_m1c_v1_bytes_remain_valid_but_replay_requires_pinned_code",
        "test_m1c_v2_preserves_v1_economic_source_facts",
    }
)
V1_TEST_NAMES = (
    "test_m1c_fixture_preserves_installment_lineage",
    "test_m1c_fixture_selects_corrected_installment_revision",
    "test_m1c_fixture_rejects_pinned_partition_tampering",
    "test_m1c_fixture_rejects_expected_hash_index_tampering",
)
REPO_ROOT = Path(__file__).resolve().parents[1]
_INVENTORY_PATH = (
    REPO_ROOT / "tests/fixtures/m1d-compatibility/m1c-v2-protected-sha256.json"
)
_ARCHIVE_COMMON_PATHS = (
    "src/drift",
    HISTORY_MODULE,
    "tests/unit/economic_test_support.py",
    "tests/fixtures/m1c/v1",
    "pyproject.toml",
    "uv.lock",
)
_V2_ARCHIVE_PATHS = (*_ARCHIVE_COMMON_PATHS, "tests/fixtures/m1c/v2")
_REQUIRED_PYTHON_FLOOR = (3, 14)
_EXPECTED_INVENTORY_SHA256 = (
    "f3fa52804a4f282c9b6cf8f7d67cc94232d63c557193686f7dc9ffa3268613c6"
)


class PinnedReplayError(RuntimeError):
    """A required historical replay precondition did not hold."""


def _load_inventory() -> dict[str, str]:
    try:
        inventory_bytes = _INVENTORY_PATH.read_bytes()
    except OSError as error:
        raise PinnedReplayError(
            f"cannot read literal M1c inventory: {error}"
        ) from error
    if hashlib.sha256(inventory_bytes).hexdigest() != _EXPECTED_INVENTORY_SHA256:
        raise PinnedReplayError("literal inventory sha256 mismatch")
    try:
        document = json.loads(inventory_bytes)
    except json.JSONDecodeError as error:
        raise PinnedReplayError(
            f"cannot parse literal M1c inventory: {error}"
        ) from error
    if (
        not isinstance(document, dict)
        or document.get("commit") != V2_INTERPRETER_COMMIT
        or not isinstance(document.get("sha256"), dict)
        or not all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in document["sha256"].items()
        )
    ):
        raise PinnedReplayError("literal M1c inventory is malformed")
    return dict(document["sha256"])


PROTECTED_SHA256 = _load_inventory()
_REQUIRED_PROTECTED_PATHS = frozenset(PROTECTED_SHA256)


def read_git_bytes(path: str) -> bytes:
    """Read a current protected byte path without deriving an expected hash."""
    try:
        return (REPO_ROOT / path).read_bytes()
    except OSError as error:
        raise PinnedReplayError(
            f"protected path is unavailable: {path}: {error}"
        ) from error


def verify_protected_inputs(
    *,
    root: Path = REPO_ROOT,
    expected: Mapping[str, str] | None = None,
    read_bytes: Callable[[str], bytes] | None = None,
) -> None:
    """Reject changed M1c inputs against the committed, literal V2 inventory."""
    pins = dict(PROTECTED_SHA256 if expected is None else expected)
    if set(pins) != _REQUIRED_PROTECTED_PATHS:
        raise PinnedReplayError(
            "protected inventory is incomplete or contains unknown paths"
        )
    for path, digest in pins.items():
        try:
            data = (
                read_bytes(path)
                if read_bytes is not None
                else (root / path).read_bytes()
            )
        except OSError as error:
            raise PinnedReplayError(
                f"protected path is unavailable: {path}: {error}"
            ) from error
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise PinnedReplayError(
                f"protected sha256 mismatch for {path}: expected {digest}, got {actual}"
            )


def is_pinned_m1c_node(nodeid: str) -> bool:
    """Return whether this exact historical test node is routed to V2 source."""
    prefix = f"{HISTORY_MODULE}::"
    if not nodeid.startswith(prefix):
        return False
    return nodeid.removeprefix(prefix) in REPLAY_TEST_NAMES


def verify_history_test_definitions(history_module: Path) -> None:
    """Require the complete, unexecuted history module test inventory to be exact."""
    try:
        tree = ast.parse(
            history_module.read_text(encoding="utf-8"), str(history_module)
        )
    except (OSError, SyntaxError) as error:
        raise PinnedReplayError(
            f"cannot inspect M1c history definitions: {error}"
        ) from error
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }
    if defined != REPLAY_TEST_NAMES:
        raise PinnedReplayError(
            "M1c history module must define exactly the approved six tests; "
            f"found {sorted(defined)!r}"
        )


def _archive_paths(commit: str) -> tuple[str, ...]:
    if commit == V1_INTERPRETER_COMMIT:
        return _ARCHIVE_COMMON_PATHS
    if commit == V2_INTERPRETER_COMMIT:
        return _V2_ARCHIVE_PATHS
    raise PinnedReplayError(f"unapproved M1c interpreter commit: {commit}")


def extract_archive(commit: str, destination: Path) -> Path:
    """Extract only the finite historical replay inputs from local Git."""
    if tuple(sys.version_info[:2]) < _REQUIRED_PYTHON_FLOOR:
        raise PinnedReplayError("pinned replay requires the project Python 3.14 floor")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["git", "archive", "--format=tar", commit, "--", *_archive_paths(commit)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        output = _combined_output(completed)
        raise PinnedReplayError(
            f"cannot extract pinned commit {commit}: {output.strip()}"
        )
    try:
        with tarfile.open(fileobj=BytesIO(completed.stdout), mode="r:") as archive:
            members = archive.getmembers()
            if any(
                member.name.startswith("/") or ".." in Path(member.name).parts
                for member in members
            ):
                raise PinnedReplayError("pinned Git archive contains an unsafe path")
            archive.extractall(destination, members=members, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise PinnedReplayError(
            f"cannot unpack pinned commit {commit}: {error}"
        ) from error
    return destination


def verify_child_import_location(imported_file: str, archive_root: Path) -> None:
    """Require the child interpreter to import Drift from its bounded archive."""
    imported = Path(imported_file).resolve()
    archive = archive_root.resolve()
    if not imported.is_relative_to(archive):
        raise PinnedReplayError(
            f"child imported Drift outside pinned archive: {imported}"
        )


def _child_environment(archive_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(archive_root / "src"), str(archive_root / "tests" / "unit"))
    )
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["DRIFT_PINNED_REPLAY_CHILD"] = "1"
    return environment


def _combined_output(completed: subprocess.CompletedProcess[bytes]) -> str:
    return "\n".join(
        part.decode("utf-8", errors="replace")
        for part in (completed.stdout, completed.stderr)
        if part
    )


def _run_archived_node_in_root(archive_root: Path, nodeid: str) -> SimpleNamespace:
    environment = _child_environment(archive_root)
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            "import drift; print(drift.__file__)",
        ],
        cwd=archive_root,
        env=environment,
        check=False,
        capture_output=True,
    )
    if imported.returncode != 0:
        raise PinnedReplayError(
            f"child cannot import pinned Drift: {_combined_output(imported)}"
        )
    verify_child_import_location(imported.stdout.decode("utf-8").strip(), archive_root)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", nodeid],
        cwd=archive_root,
        env=environment,
        check=False,
        capture_output=True,
    )
    result = SimpleNamespace(
        returncode=completed.returncode,
        output=_combined_output(completed),
        nodeid=nodeid,
    )
    if result.returncode != 0:
        raise PinnedReplayError(f"pinned replay failed for {nodeid}:\n{result.output}")
    return result


def run_archived_node(commit: str, nodeid: str) -> SimpleNamespace:
    """Run one archived node and surface child diagnostics unchanged on failure."""
    with tempfile.TemporaryDirectory(prefix="drift-m1c-replay-") as directory:
        archive = extract_archive(commit, Path(directory))
        return _run_archived_node_in_root(archive, nodeid)


def run_archived_v1_cases() -> SimpleNamespace:
    """Run the original four V1 cases once under their original interpreter source."""
    with tempfile.TemporaryDirectory(prefix="drift-m1c-v1-replay-") as directory:
        archive = extract_archive(V1_INTERPRETER_COMMIT, Path(directory))
        output: list[str] = []
        for name in V1_TEST_NAMES:
            result = _run_archived_node_in_root(archive, f"{HISTORY_MODULE}::{name}")
            output.append(result.output)
        return SimpleNamespace(returncode=0, output="\n".join(output), case_count=4)


class PinnedArchiveCache:
    """One deterministic temporary V2 archive for a parent pytest session."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="drift-m1c-v2-replay-")
        self.root = extract_archive(V2_INTERPRETER_COMMIT, Path(self._temporary.name))

    def close(self) -> None:
        self._temporary.cleanup()
