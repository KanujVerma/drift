"""Authenticated, byte-pinned M1d v3 replay support used only by pytest tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

PINNED_M1D_COMMIT = "af75cce0f763de025f8ae3516577a9d0a1acead9"
REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_MODULE = "tests/integration/test_m1d_adversarial_matrix.py"
M1C_COMPOSITION_NODE = (
    "tests/integration/test_m1d_compatibility.py::"
    "test_c02_current_code_composes_m1c_into_fixture_only_m1d_replay"
)
_INVENTORY_PATH = (
    REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v3-protected-sha256.json"
)
_EXPECTED_INVENTORY_SHA256 = (
    "6fb819eb863ebf83e1a3b4e3a7e6af261748116502cdb0ad3603d108d17c2e2b"
)
_ARCHIVE_PATHS = ("src/drift", "tests", "pyproject.toml", "uv.lock")
_REQUIRED_PYTHON_FLOOR = (3, 14)


class PinnedM1dReplayError(RuntimeError):
    """Exact archived M1d replay could not be authenticated or executed."""


@dataclass(frozen=True, slots=True)
class PinnedM1dReplayResult:
    commit: str
    nodeid: str
    returncode: int
    output: str


def _combined_output(completed: subprocess.CompletedProcess[bytes]) -> str:
    return "\n".join(
        part.decode("utf-8", errors="replace")
        for part in (completed.stdout, completed.stderr)
        if part
    )


def _load_inventory() -> dict[str, str]:
    try:
        raw = _INVENTORY_PATH.read_bytes()
    except OSError as error:
        raise PinnedM1dReplayError(
            f"cannot read literal M1d inventory: {error}"
        ) from error
    if hashlib.sha256(raw).hexdigest() != _EXPECTED_INVENTORY_SHA256:
        raise PinnedM1dReplayError("literal M1d inventory sha256 mismatch")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PinnedM1dReplayError(
            f"cannot parse literal M1d inventory: {error}"
        ) from error
    pins = document.get("sha256") if isinstance(document, dict) else None
    if (
        not isinstance(pins, dict)
        or document.get("commit") != PINNED_M1D_COMMIT
        or len(pins) != 544
        or any(
            not isinstance(path, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            for path, digest in pins.items()
        )
    ):
        raise PinnedM1dReplayError("literal M1d inventory is malformed")
    return dict(pins)


PROTECTED_M1D_SHA256 = _load_inventory()
_REQUIRED_PROTECTED_PATHS = frozenset(PROTECTED_M1D_SHA256)


def verify_m1d_protected_inputs(
    *, root: Path, expected: Mapping[str, str] | None = None
) -> None:
    """Reject a changed M1d source, fixture, or environment input before replay."""
    pins = dict(PROTECTED_M1D_SHA256 if expected is None else expected)
    if set(pins) != _REQUIRED_PROTECTED_PATHS:
        raise PinnedM1dReplayError(
            "protected M1d inventory is incomplete or contains unknown paths"
        )
    for path, digest in pins.items():
        try:
            data = (root / path).read_bytes()
        except OSError as error:
            raise PinnedM1dReplayError(
                f"protected M1d path is unavailable: {path}: {error}"
            ) from error
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise PinnedM1dReplayError(
                "protected M1d sha256 mismatch for "
                f"{path}: expected {digest}, got {actual}"
            )


def is_pinned_m1d_node(nodeid: str) -> bool:
    """Return whether an M1d acceptance node must execute from the archive."""
    return nodeid.startswith(f"{MATRIX_MODULE}::") or nodeid == M1C_COMPOSITION_NODE


def extract_m1d_archive(destination: Path, *, commit: str = PINNED_M1D_COMMIT) -> Path:
    """Extract the finite authenticated M1d archive from the local pinned commit."""
    if commit != PINNED_M1D_COMMIT:
        raise PinnedM1dReplayError(f"unapproved M1d interpreter commit: {commit}")
    if tuple(sys.version_info[:2]) < _REQUIRED_PYTHON_FLOOR:
        raise PinnedM1dReplayError("pinned M1d replay requires Python 3.14")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["git", "archive", "--format=tar", commit, "--", *_ARCHIVE_PATHS],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise PinnedM1dReplayError(
            f"cannot extract pinned M1d commit {commit}: {_combined_output(completed)}"
        )
    try:
        with tarfile.open(fileobj=BytesIO(completed.stdout), mode="r:") as archive:
            members = archive.getmembers()
            if any(
                member.name.startswith("/") or ".." in Path(member.name).parts
                for member in members
            ):
                raise PinnedM1dReplayError(
                    "pinned M1d Git archive contains an unsafe path"
                )
            archive.extractall(destination, members=members, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise PinnedM1dReplayError(
            f"cannot unpack pinned M1d commit {commit}: {error}"
        ) from error
    verify_m1d_protected_inputs(root=destination)
    return destination


def verify_child_import_location(imported_file: str, archive_root: Path) -> None:
    """Require the child interpreter to import Drift from the extracted archive."""
    imported = Path(imported_file).resolve()
    if not imported.is_relative_to(archive_root.resolve()):
        raise PinnedM1dReplayError(
            f"child imported Drift outside pinned archive: {imported}"
        )


def _child_environment(archive_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(archive_root / "src"),
            str(archive_root / "tests" / "integration"),
            str(archive_root / "tests" / "unit"),
        )
    )
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["DRIFT_PINNED_REPLAY_CHILD"] = "1"
    return environment


def _run_archived_m1d_node_in_root(
    archive_root: Path, nodeid: str
) -> PinnedM1dReplayResult:
    """Run one M1d node inside an already authenticated archived checkout."""
    verify_m1d_protected_inputs(root=archive_root)
    environment = _child_environment(archive_root)
    imported = subprocess.run(
        [sys.executable, "-c", "import drift; print(drift.__file__)"],
        cwd=archive_root,
        env=environment,
        check=False,
        capture_output=True,
    )
    if imported.returncode != 0:
        raise PinnedM1dReplayError(
            f"child cannot import pinned M1d Drift: {_combined_output(imported)}"
        )
    verify_child_import_location(imported.stdout.decode("utf-8").strip(), archive_root)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", nodeid],
        cwd=archive_root,
        env=environment,
        check=False,
        capture_output=True,
    )
    result = PinnedM1dReplayResult(
        commit=PINNED_M1D_COMMIT,
        nodeid=nodeid,
        returncode=completed.returncode,
        output=_combined_output(completed),
    )
    if result.returncode != 0:
        raise PinnedM1dReplayError(
            f"pinned M1d replay failed for {nodeid}:\n{result.output}"
        )
    return result


def run_archived_m1d_node(nodeid: str) -> PinnedM1dReplayResult:
    """Authenticate and run one exact M1d node without current-package imports."""
    with tempfile.TemporaryDirectory(prefix="drift-m1d-v3-replay-") as directory:
        archive = extract_m1d_archive(Path(directory))
        return _run_archived_m1d_node_in_root(archive, nodeid)


class PinnedM1dArchiveCache:
    """One authenticated M1d archive for the parent pytest session."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="drift-m1d-v3-session-")
        self.root = extract_m1d_archive(Path(self._temporary.name))

    def close(self) -> None:
        self._temporary.cleanup()
