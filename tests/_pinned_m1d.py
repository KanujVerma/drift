"""Authenticated, byte-pinned M1d v3 replay support used only by pytest tests.

Two pin inventories live side by side and they are not interchangeable.

``m1d-v3-protected-sha256.json`` is the HISTORICAL inventory. It records the
protected paths exactly as they stand at ``PINNED_M1D_COMMIT`` (af75cce), and
it authenticates the archive extracted from that commit. It is preserved
byte-identical for audit and is never regenerated.

``m1d-v4-protected-sha256.json`` is the CURRENT inventory. It records the
protected paths as they must stand in the live working tree, and it supersedes
v3 for that one role only. Under issue #32 the M1d validator run identity moved
from the whole-tree ``economic_implementation_hash()`` to the versioned
semantic attestation, which changed the bytes of the two M1d validation entry
points and introduced the module that now defines the identity. v4 carries two
explicit, separately justified deltas over v3 and nothing else:

* ``superseded_paths`` names a path v3 already pins whose working-tree bytes
  moved, and records both the historical digest it replaces and the current
  one.
* ``added_paths`` names a path v3 does not pin at all and brings it under the
  freeze, with its own issue reference and justification. An addition may not
  shadow a path v3 already pins; that is what ``superseded_paths`` is for.

``_validated_current_pins`` re-derives the whole reconstruction on every load,
so a pin can be neither silently re-signed nor silently introduced for any path
the inventory does not declare.
"""

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
_CURRENT_INVENTORY_PATH = (
    REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v4-protected-sha256.json"
)
_EXPECTED_CURRENT_INVENTORY_SHA256 = (
    "4af2e06734e8fadde2002d69fe9d48bd5eca369e771862f2e09df150238d76d2"
)
_CURRENT_INVENTORY_ID = "m1d-v4-protected-sha256"
_SUPERSEDED_INVENTORY_ID = "m1d-v3-protected-sha256"
_SUPERSESSION_ISSUE = 32
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


PROTECTED_M1D_ARCHIVE_SHA256 = _load_inventory()
"""Historical pins: the protected paths exactly as they stand at af75cce."""


def _superseded_source_pins(document: object) -> dict[str, dict[str, str]]:
    """Return the declared supersessions, rejecting a malformed declaration."""
    if not isinstance(document, dict):
        raise PinnedM1dReplayError("current M1d inventory is malformed")
    supersedes = document.get("supersedes")
    superseded = document.get("superseded_paths")
    if (
        not isinstance(supersedes, dict)
        or not isinstance(superseded, dict)
        or not superseded
        or supersedes.get("inventory_id") != _SUPERSEDED_INVENTORY_ID
        or supersedes.get("commit") != PINNED_M1D_COMMIT
        or supersedes.get("file_sha256") != _EXPECTED_INVENTORY_SHA256
        or supersedes.get("issue") != _SUPERSESSION_ISSUE
        or not isinstance(supersedes.get("reason"), str)
        or not supersedes["reason"].strip()
    ):
        raise PinnedM1dReplayError("current M1d inventory supersession is malformed")
    for path, record in superseded.items():
        if (
            not isinstance(path, str)
            or not isinstance(record, dict)
            or set(record) != {"historical_sha256", "current_sha256"}
            or any(
                not isinstance(value, str) or len(value) != 64
                for value in record.values()
            )
            or record["historical_sha256"] == record["current_sha256"]
        ):
            raise PinnedM1dReplayError(
                f"current M1d inventory supersession is malformed for {path}"
            )
    return dict(superseded)


def _added_source_pins(document: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return the declared additions, rejecting a malformed declaration.

    An addition widens the freeze onto a path v3 never pinned, so it has to
    stand on its own justification rather than on the key sets merely
    differing. Declaring no additions at all is allowed; what is not allowed
    is a pin that no declaration accounts for.
    """
    added = document.get("added_paths", {})
    if not isinstance(added, dict):
        raise PinnedM1dReplayError("current M1d inventory addition block is malformed")
    for path, record in added.items():
        justification = (
            record.get("justification") if isinstance(record, dict) else None
        )
        if (
            not isinstance(path, str)
            or not isinstance(record, dict)
            or set(record) != {"current_sha256", "issue", "justification"}
            or not isinstance(record["current_sha256"], str)
            or len(record["current_sha256"]) != 64
            or record["issue"] != _SUPERSESSION_ISSUE
            or not isinstance(justification, str)
            or not justification.strip()
        ):
            raise PinnedM1dReplayError(
                f"current M1d inventory addition is malformed for {path}"
            )
    return dict(added)


def _validated_current_pins(document: object) -> dict[str, str]:
    """Re-derive the current pins from the historical pins plus the delta.

    The current inventory is only allowed to differ from the preserved v3
    inventory on the paths its own ``superseded_paths`` and ``added_paths``
    blocks declare. A superseded path must already be pinned by v3 and must
    carry the historical digest it replaces; an added path must not be pinned
    by v3 at all and must carry its own justification. Anything else is a
    silent re-signing or a silent widening and fails closed here.
    """
    if not isinstance(document, dict):
        raise PinnedM1dReplayError("current M1d inventory is malformed")
    pins = document.get("sha256")
    superseded = _superseded_source_pins(document)
    added = _added_source_pins(document)
    if (
        not isinstance(pins, dict)
        or document.get("inventory_id") != _CURRENT_INVENTORY_ID
        or document.get("baseline_commit") != PINNED_M1D_COMMIT
        or any(
            not isinstance(digest, str) or len(digest) != 64 for digest in pins.values()
        )
    ):
        raise PinnedM1dReplayError("current M1d inventory is malformed")
    expected = dict(PROTECTED_M1D_ARCHIVE_SHA256)
    for path, record in superseded.items():
        if path not in expected:
            raise PinnedM1dReplayError(
                f"current M1d inventory supersedes an unpinned path: {path}"
            )
        if record["historical_sha256"] != expected[path]:
            raise PinnedM1dReplayError(
                f"current M1d inventory misstates the historical pin for {path}"
            )
        expected[path] = record["current_sha256"]
    for path, addition in added.items():
        if path in PROTECTED_M1D_ARCHIVE_SHA256:
            raise PinnedM1dReplayError(
                "current M1d inventory declares an addition the historical "
                f"inventory already pins: {path}"
            )
        expected[path] = str(addition["current_sha256"])
    undeclared = sorted(set(pins) - set(expected))
    if undeclared:
        raise PinnedM1dReplayError(
            f"current M1d inventory pins an undeclared added path: {undeclared}"
        )
    omitted = sorted(set(expected) - set(pins))
    if omitted:
        raise PinnedM1dReplayError(
            f"current M1d inventory omits a required protected path: {omitted}"
        )
    if pins != expected:
        drifted = sorted(path for path in pins if pins[path] != expected[path])
        raise PinnedM1dReplayError(
            f"current M1d inventory re-signs undeclared protected paths: {drifted}"
        )
    return dict(pins)


def _load_current_inventory() -> dict[str, str]:
    try:
        raw = _CURRENT_INVENTORY_PATH.read_bytes()
    except OSError as error:
        raise PinnedM1dReplayError(
            f"cannot read current M1d inventory: {error}"
        ) from error
    if hashlib.sha256(raw).hexdigest() != _EXPECTED_CURRENT_INVENTORY_SHA256:
        raise PinnedM1dReplayError("current M1d inventory sha256 mismatch")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PinnedM1dReplayError(
            f"cannot parse current M1d inventory: {error}"
        ) from error
    return _validated_current_pins(document)


PROTECTED_M1D_SHA256 = _load_current_inventory()
"""Current pins: the protected paths as they must stand in the working tree."""

_REQUIRED_PROTECTED_PATHS = frozenset(PROTECTED_M1D_SHA256)
_REQUIRED_ARCHIVE_PATHS = frozenset(PROTECTED_M1D_ARCHIVE_SHA256)


def _verify_pinned_inputs(
    *, root: Path, pins: Mapping[str, str], required: frozenset[str], label: str
) -> None:
    if set(pins) != required:
        raise PinnedM1dReplayError(
            f"{label} M1d inventory is incomplete or contains unknown paths"
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


def verify_m1d_protected_inputs(
    *, root: Path, expected: Mapping[str, str] | None = None
) -> None:
    """Reject a changed M1d source, fixture, or environment input in the tree.

    This is the CURRENT freeze. It uses the v4 pins, which supersede v3 on the
    paths issue #32 moved, add the module that now defines the M1d replay
    identity, and reproduce v3 everywhere else.
    """
    pins = PROTECTED_M1D_SHA256 if expected is None else expected
    _verify_pinned_inputs(
        root=root, pins=pins, required=_REQUIRED_PROTECTED_PATHS, label="protected"
    )


def verify_m1d_archive_inputs(
    *, root: Path, expected: Mapping[str, str] | None = None
) -> None:
    """Reject an archived M1d input that is not exactly af75cce.

    This is the HISTORICAL freeze. The extracted replay archive is commit
    af75cce, so it must authenticate against the preserved v3 pins and never
    against the superseded working-tree pins.
    """
    pins = PROTECTED_M1D_ARCHIVE_SHA256 if expected is None else expected
    _verify_pinned_inputs(
        root=root, pins=pins, required=_REQUIRED_ARCHIVE_PATHS, label="archived"
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
    verify_m1d_archive_inputs(root=destination)
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
    verify_m1d_archive_inputs(root=archive_root)
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
