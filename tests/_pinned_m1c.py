"""Isolated, byte-pinned M1c replay support used only by pytest tests.

Two pin inventories live side by side and they are not interchangeable.

``m1c-v2-protected-sha256.json`` is the HISTORICAL inventory. It records the
protected paths exactly as they stand at ``V2_INTERPRETER_COMMIT`` (aecee94),
and it authenticates the archive extracted from that commit
(``verify_archive_inputs``). It is preserved byte-identical and never
regenerated.

``m1c-v3-protected-sha256.json`` (issue #63, stage 2) is the first M1c
supersession link and the CURRENT inventory: the protected paths as they must
stand in the live working tree (``verify_protected_inputs``). The M1c validator
run identity and the M1c selection, projection and composition identities moved
from the whole-tree inventory to the ``m1c-source-validation-v1`` and
``m1c-evidence-v1`` semantic attestations, which changed the bytes of the three
M1c stamp-site modules. The link carries exactly that delta over v2, the same
way the M1d freeze links do (``tests/_pinned_m1d.py``):

* ``superseded_paths`` names a path v2 already pins whose bytes moved, and
  records both the digest it replaces and the current one.
* ``added_paths`` names a path v2 does not pin and brings it under the freeze,
  with the link's issue and its own justification. It may not shadow a v2 pin.

``_load_link`` re-derives the link over the re-read v2 pins on every load, so a
pin can be neither silently re-signed nor silently introduced, and neither
inventory can be edited without breaking its literal byte pin. The live-tree
freeze moves forward only by a new link; history is superseded, never
rewritten.
"""

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
_HISTORICAL_INVENTORY_ID = "m1c-v2-protected-sha256"
"""v2 declares no id of its own; the link names it by this id and its path."""
_LINK_PATH = REPO_ROOT / "tests/fixtures/m1d-compatibility/m1c-v3-protected-sha256.json"
_LINK_INVENTORY_ID = "m1c-v3-protected-sha256"
_LINK_ISSUE = 63
_EXPECTED_LINK_SHA256 = (
    "63f88e707a92809243ee05f69e1a0a2f00e74fc596e45c4b0c7391e8a76c2b6d"
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


HISTORICAL_PROTECTED_SHA256 = _load_inventory()
"""Historical pins: the protected paths exactly as they stand at aecee94."""


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _superseded_link_pins(document: dict[str, object]) -> dict[str, dict[str, str]]:
    """Return the declared supersessions, rejecting a malformed declaration."""
    supersedes = document.get("supersedes")
    superseded = document.get("superseded_paths")
    if (
        not isinstance(supersedes, dict)
        or not isinstance(superseded, dict)
        or not superseded
        or supersedes.get("inventory_id") != _HISTORICAL_INVENTORY_ID
        or supersedes.get("path") != _INVENTORY_PATH.relative_to(REPO_ROOT).as_posix()
        or supersedes.get("file_sha256") != _EXPECTED_INVENTORY_SHA256
        or supersedes.get("commit") != V2_INTERPRETER_COMMIT
        or supersedes.get("issue") != _LINK_ISSUE
        or not _is_nonblank(supersedes.get("status"))
        or not _is_nonblank(supersedes.get("reason"))
    ):
        raise PinnedReplayError("m1c-v3 inventory supersession is malformed")
    for path, record in superseded.items():
        if (
            not isinstance(path, str)
            or not isinstance(record, dict)
            or set(record) != {"historical_sha256", "current_sha256"}
            or not all(_is_digest(value) for value in record.values())
            or record["historical_sha256"] == record["current_sha256"]
        ):
            raise PinnedReplayError(
                f"m1c-v3 inventory supersession is malformed for {path}"
            )
    return dict(superseded)


def _added_link_pins(document: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return the declared additions, each on its own issue and justification."""
    added = document.get("added_paths", {})
    if not isinstance(added, dict):
        raise PinnedReplayError("m1c-v3 inventory addition block is malformed")
    for path, record in added.items():
        if (
            not isinstance(path, str)
            or not isinstance(record, dict)
            or set(record) != {"current_sha256", "issue", "justification"}
            or not _is_digest(record["current_sha256"])
            or record["issue"] != _LINK_ISSUE
            or not _is_nonblank(record["justification"])
        ):
            raise PinnedReplayError(
                f"m1c-v3 inventory addition is malformed for {path}"
            )
    return dict(added)


def _validated_link_pins(document: object, parent: Mapping[str, str]) -> dict[str, str]:
    """Re-derive the link's pins from the v2 pins plus its declared delta.

    The link may differ from v2 only on the paths its own ``superseded_paths``
    and ``added_paths`` blocks declare. A superseded path must already be
    pinned by v2 and must carry the digest it replaces; an added path must not
    be pinned by v2 at all. Anything else is a silent re-signing, widening or
    omission and fails closed here.
    """
    if not isinstance(document, dict):
        raise PinnedReplayError("m1c-v3 inventory is malformed")
    pins = document.get("sha256")
    superseded = _superseded_link_pins(document)
    added = _added_link_pins(document)
    if (
        not isinstance(pins, dict)
        or document.get("inventory_id") != _LINK_INVENTORY_ID
        or document.get("role") != "current"
        or document.get("baseline_commit") != V2_INTERPRETER_COMMIT
        or not all(
            isinstance(path, str) and _is_digest(digest)
            for path, digest in pins.items()
        )
    ):
        raise PinnedReplayError("m1c-v3 inventory is malformed")
    expected = dict(parent)
    for path, record in superseded.items():
        if path not in expected:
            raise PinnedReplayError(
                f"m1c-v3 inventory supersedes an unpinned path: {path}"
            )
        if record["historical_sha256"] != expected[path]:
            raise PinnedReplayError(
                f"m1c-v3 inventory misstates the superseded pin for {path}"
            )
        expected[path] = record["current_sha256"]
    for path, addition in added.items():
        if path in parent:
            raise PinnedReplayError(
                "m1c-v3 inventory declares an addition the inventory it "
                f"supersedes already pins: {path}"
            )
        expected[path] = str(addition["current_sha256"])
    undeclared = sorted(set(pins) - set(expected))
    if undeclared:
        raise PinnedReplayError(
            f"m1c-v3 inventory pins an undeclared added path: {undeclared}"
        )
    omitted = sorted(set(expected) - set(pins))
    if omitted:
        raise PinnedReplayError(
            f"m1c-v3 inventory omits a required protected path: {omitted}"
        )
    if pins != expected:
        drifted = sorted(path for path in pins if pins[path] != expected[path])
        raise PinnedReplayError(
            f"m1c-v3 inventory re-signs undeclared protected paths: {drifted}"
        )
    return dict(pins)


def _load_link() -> dict[str, str]:
    """Read the link, authenticated by its literal pin, and re-derive it over v2."""
    parent = _load_inventory()
    try:
        raw = _LINK_PATH.read_bytes()
    except OSError as error:
        raise PinnedReplayError(f"cannot read m1c-v3 inventory: {error}") from error
    if hashlib.sha256(raw).hexdigest() != _EXPECTED_LINK_SHA256:
        raise PinnedReplayError("m1c-v3 inventory sha256 mismatch")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PinnedReplayError(f"cannot parse m1c-v3 inventory: {error}") from error
    return _validated_link_pins(document, parent)


PROTECTED_SHA256 = _load_link()
"""Current pins: the protected paths as they must stand in the working tree."""
_REQUIRED_PROTECTED_PATHS = frozenset(PROTECTED_SHA256)
_REQUIRED_ARCHIVE_PATHS = frozenset(HISTORICAL_PROTECTED_SHA256)


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
    """Reject changed live M1c inputs against the current m1c-v3 pins."""
    pins = dict(PROTECTED_SHA256 if expected is None else expected)
    if set(pins) != _REQUIRED_PROTECTED_PATHS:
        raise PinnedReplayError(
            "protected inventory is incomplete or contains unknown paths"
        )
    _verify_pins(pins, root=root, read_bytes=read_bytes)


def verify_archive_inputs(
    *, root: Path, expected: Mapping[str, str] | None = None
) -> None:
    """Reject a changed aecee94 archive against the historical v2 pins."""
    pins = dict(HISTORICAL_PROTECTED_SHA256 if expected is None else expected)
    if set(pins) != _REQUIRED_ARCHIVE_PATHS:
        raise PinnedReplayError(
            "historical inventory is incomplete or contains unknown paths"
        )
    _verify_pins(pins, root=root, read_bytes=None)


def _verify_pins(
    pins: Mapping[str, str],
    *,
    root: Path,
    read_bytes: Callable[[str], bytes] | None,
) -> None:
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
