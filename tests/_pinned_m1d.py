"""Authenticated, byte-pinned M1d replay support used only by pytest tests.

Three pin inventories live side by side and they are not interchangeable.

``m1d-v3-protected-sha256.json`` is the HISTORICAL inventory. It records the
protected paths exactly as they stand at ``PINNED_M1D_COMMIT`` (af75cce), and
it authenticates the archive extracted from that commit. It is preserved
byte-identical for audit and is never regenerated.

The working-tree freeze is an ordered chain of links over v3
(``_FREEZE_INVENTORIES``), each preserved byte-identical once superseded:

* ``m1d-v4-protected-sha256.json`` (issue #32) supersedes v3. The M1d validator
  run identity moved from the whole-tree ``economic_implementation_hash()`` to
  the versioned semantic attestation, which changed the bytes of the two M1d
  validation entry points and introduced the module that now defines the
  identity. v4 exactly describes commit 4ad90aa, the commit that last wrote it.
* ``m1d-v5-protected-sha256.json`` (issue #63) supersedes v4. The M1d evidence
  identity moved from the whole-tree inventory to the ``m1d-evidence-v1``
  semantic attestation, which changed the bytes of the identity accessor and of
  the attestation module. v5 exactly describes commit 200bfeb, the commit that
  last wrote it.
* ``m1d-v6-protected-sha256.json`` (issue #107) supersedes v5 and is the CURRENT
  inventory: the protected paths as they must stand in the live working tree.
  The semantic closure guard was hardened against aliased and indirect dynamic
  imports, which changed the bytes of the attestation module.

A later link is appended to ``_FREEZE_INVENTORIES``; the entry it supersedes
then records the commit that last wrote it. Each link carries two explicit,
separately justified deltas over the inventory it supersedes and nothing else:

* ``superseded_paths`` names a path the superseded inventory already pins whose
  bytes moved, and records both the digest it replaces and the current one.
* ``added_paths`` names a path the superseded inventory does not pin at all and
  brings it under the freeze, with the link's issue and its own justification.
  An addition may not shadow a path already pinned; that is what
  ``superseded_paths`` is for.

``_load_freeze_chain`` re-derives every link on every load, each over the
re-derived pins of the link it supersedes, so a pin can be neither silently
re-signed nor silently introduced for any path a link does not declare, and no
link can be edited without breaking its byte pin.

Replay baseline supersession (issue #48)
----------------------------------------

The M1d result fixtures of generations v1, v2 and v3 were minted under
cpython-3.14.5 by their source commits (``PINNED_M1D_GENERATIONS``). That
historical baseline is preserved byte-identical, in the working tree and in
those commits. ``m1d-replay-baselines/cpython-3.14.6/supersession.json``
supersedes it for replay only: for each generation it re-mints the two
expected result documents and the hash index, regenerated from the same
source commit under cpython-3.14.6, plus the single hash-index digest literal
in that commit's archived fixture loader. It may supersede nothing else, and
never semantic source.

A replay archive is therefore ``git archive`` of the source commit,
authenticated against the preserved v3 pins, with exactly those declared
paths replaced (``apply_m1d_replay_baseline``) and then re-authenticated
against the derived replay pins. ``_validated_replay_baseline`` re-derives
all of it on every load.

Replay environment identity (issue #48)
---------------------------------------

Every M1d normalization derivation binds ``python_identity``, the exact
interpreter implementation and patch version (``cpython-X.Y.Z``). Pinned replay
therefore only means something under the exact interpreter the repository pins
in ``.python-version``. ``verify_replay_interpreter`` checks that identity
before any archive is extracted, and ``verify_replay_child_interpreter`` checks
it again for the child interpreter that actually recomputes the derivation.

The interpreter is not the whole environment. ``verify_replay_distributions``
also holds the installed distribution set to ``uv.lock`` before any archive is
extracted, and ``verify_replay_child_distributions`` holds the replay child to
it too (issue #53), so a package upgraded or installed outside ``uv sync`` is
reported as an environment mismatch rather than surfacing later as a semantic
one. A locked package that is not installed is allowed, because the lock
resolves every platform and markers exclude some packages from any one of
them; a missing dependency the replay needs fails loudly on import instead.

Failures fall into exactly four classes, each a direct subclass of
``PinnedM1dReplayError`` whose message starts with its code:

* ``PINNED_REPLAY_ENVIRONMENT_MISMATCH``: the running or child interpreter is
  not the pinned one, or its installed distributions differ from ``uv.lock``.
  The message names the expected and the found identity or versions.
* ``PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE``: a required replay
  environment artifact cannot be obtained, such as the pinned interpreter
  executable or the historical Git objects the replay extracts.
* ``PINNED_REPLAY_SEMANTIC_MISMATCH``: the environment matched and every
  archived input authenticated, but the replayed computation failed.
* ``PINNED_REPLAY_INTEGRITY_FAILURE``: protected bytes differ from their
  inventory, an inventory or pin is malformed, or the archived harness cannot
  execute the declared nodes.

Nothing on this lane skips. Each class is a hard failure.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import ClassVar

PINNED_M1D_COMMIT = "af75cce0f763de025f8ae3516577a9d0a1acead9"
PINNED_M1D_GENERATIONS: Mapping[str, str] = {
    "v1": "256154e40121d28cec6a65ebcde223c12563752d",
    "v2": "a909148a941081d8d05c5090794346c5ce54db8c",
    "v3": PINNED_M1D_COMMIT,
}
"""Source commit that generated, and therefore replays, each M1d fixture."""
REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PIN_PATH = REPO_ROOT / ".python-version"
"""The single exact interpreter pin, shared with uv and with CI."""
LOCKFILE_PATH = REPO_ROOT / "uv.lock"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
"""Declares the dependency groups ``uv sync`` installs by default."""
"""The locked distribution set every replay environment must be synced to."""
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
_HISTORICAL_INVENTORY_ID = "m1d-v3-protected-sha256"
_REPLAY_BASELINE_DIRECTORY = "tests/fixtures/m1d-replay-baselines/cpython-3.14.6"
_REPLAY_BASELINE_PATH = REPO_ROOT / _REPLAY_BASELINE_DIRECTORY / "supersession.json"
_EXPECTED_REPLAY_BASELINE_SHA256 = (
    "3fd15dfde4f656dcedd4574d2b5d5648b8683315e5e044ac6b78ac1b6a2b0585"
)
_REPLAY_BASELINE_ID = "m1d-replay-baseline-cpython-3.14.6"
_SUPERSEDED_REPLAY_BASELINE_ID = "m1d-replay-baseline-cpython-3.14.5"
_REPLAY_BASELINE_ISSUE = 48
REPLAY_BASELINE_PYTHON_IDENTITY = "cpython-3.14.6"
"""Interpreter identity the current M1d replay baseline was minted under."""
SUPERSEDED_REPLAY_PYTHON_IDENTITY = "cpython-3.14.5"
"""Interpreter identity of the preserved, superseded historical baseline."""
_FIXTURE_SUPPORT_PATH = "tests/integration/m1d_fixture_support.py"
_FIXTURE_SUPPORT_DERIVATION = (
    "the archived loader with its single hash-index.json sha256 literal "
    "replaced by the superseding hash-index.json sha256"
)
_REMINTED_FIXTURE_NAMES = (
    "expected-decision-result.json",
    "expected-outcome-result.json",
    "hash-index.json",
)
_ARCHIVE_PATHS = ("src/drift", "tests", "pyproject.toml", "uv.lock")
_PIN_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_GIT_SHA = re.compile(r"[0-9a-f]{7,40}")
"""A superseded link commit is an abbreviated or full lowercase-hex git SHA."""
_IDENTITY_PROGRAM = (
    "import sys; print(f'{sys.implementation.name}-{sys.version_info.major}."
    "{sys.version_info.minor}.{sys.version_info.micro}')"
)
_CHILD_START_TIMEOUT_SECONDS = 120


class PinnedM1dReplayError(RuntimeError):
    """Exact archived M1d replay could not be authenticated or executed."""

    code: ClassVar[str] = "PINNED_REPLAY_FAILURE"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.code} {detail}")
        self.detail = detail


class PinnedReplayEnvironmentMismatch(PinnedM1dReplayError):
    """The running or replay-child interpreter is not the pinned interpreter."""

    code = "PINNED_REPLAY_ENVIRONMENT_MISMATCH"


class PinnedReplayEnvironmentArtifactUnavailable(PinnedM1dReplayError):
    """A required replay environment artifact cannot be obtained."""

    code = "PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE"


class PinnedReplaySemanticMismatch(PinnedM1dReplayError):
    """Environment matched and inputs authenticated, but replay differed."""

    code = "PINNED_REPLAY_SEMANTIC_MISMATCH"


class PinnedReplayIntegrityFailure(PinnedM1dReplayError):
    """Protected bytes, an inventory, a pin, or the archived harness is wrong."""

    code = "PINNED_REPLAY_INTEGRITY_FAILURE"


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


def observed_interpreter_identity() -> str:
    """Return this interpreter's identity exactly as M1d derivations bind it.

    This mirrors ``python_identity`` in ``src/drift/markets/normalization.py``:
    the implementation name and the full major.minor.micro version.
    """
    return (
        f"{sys.implementation.name}-{sys.version_info.major}."
        f"{sys.version_info.minor}.{sys.version_info.micro}"
    )


def pinned_interpreter_identity(pin_path: Path = PYTHON_PIN_PATH) -> str:
    """Return the identity the repository pins, from ``.python-version`` only."""
    try:
        raw = pin_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot read interpreter pin {pin_path}: {error}"
        ) from error
    entries = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(entries) != 1 or _PIN_VERSION.fullmatch(entries[0]) is None:
        raise PinnedReplayIntegrityFailure(
            f"interpreter pin {pin_path} must name exactly one X.Y.Z interpreter "
            f"version, found {raw!r}"
        )
    identity = f"cpython-{entries[0]}"
    if identity != REPLAY_BASELINE_PYTHON_IDENTITY:
        # Moving the pin is an explicit environment migration: it needs a
        # newly minted baseline and supersession record, not just a new pin.
        raise PinnedReplayIntegrityFailure(
            f"interpreter pin {pin_path} names {identity} but the current replay "
            f"baseline was minted under {REPLAY_BASELINE_PYTHON_IDENTITY}"
        )
    return identity


def verify_replay_interpreter(
    *, observed: str | None = None, pin_path: Path = PYTHON_PIN_PATH
) -> str:
    """Require the running interpreter to be exactly the pinned interpreter.

    ``observed`` exists so tests can present another identity without
    touching ``sys``; production callers leave it unset.
    """
    expected = pinned_interpreter_identity(pin_path)
    found = observed_interpreter_identity() if observed is None else observed
    if found != expected:
        raise PinnedReplayEnvironmentMismatch(f"expected {expected} found {found}")
    return found


def verify_replay_child_interpreter(
    executable: str,
    *,
    environment: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> str:
    """Require the interpreter that recomputes the derivation to be pinned too."""
    expected = pinned_interpreter_identity()
    candidate = Path(executable) if executable else None
    if (
        candidate is None
        or not candidate.is_file()
        or not os.access(candidate, os.X_OK)
    ):
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"pinned interpreter {expected} executable is unavailable: {executable!r}"
        )
    try:
        completed = subprocess.run(
            [executable, "-c", _IDENTITY_PROGRAM],
            cwd=cwd,
            env=None if environment is None else dict(environment),
            check=False,
            capture_output=True,
            timeout=_CHILD_START_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"pinned interpreter {expected} could not start {executable}: {error}"
        ) from error
    reported = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not reported:
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"pinned interpreter {expected} could not start {executable} "
            f"(exit {completed.returncode}): {_combined_output(completed)}"
        )
    if reported != expected:
        raise PinnedReplayEnvironmentMismatch(
            f"expected {expected} found {reported} in replay child interpreter "
            f"{executable}"
        )
    return reported


#: Printed by the replay child: its installed distributions, as JSON. A
#: distribution whose metadata carries no version is reported as "" so the
#: parent classifies the child's environment exactly as it classifies its own.
_DISTRIBUTIONS_PROGRAM = (
    "import importlib.metadata, json, re\n"
    "found = {}\n"
    "for item in importlib.metadata.distributions():\n"
    "    name = item.metadata['Name']\n"
    "    if name:\n"
    "        key = re.sub(r'[-_.]+', '-', name).lower()\n"
    "        found.setdefault(key, set()).add(item.metadata.get('Version') or '')\n"
    "print(json.dumps({key: sorted(value) for key, value in found.items()}))\n"
)
_LOCKFILE_PIN = "uv.lock"


def _distribution_name(name: str) -> str:
    """Normalize a distribution name the way PEP 503 compares names."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True, slots=True)
class LockedEnvironment:
    """What ``uv.lock`` resolves, and what it requires of this interpreter.

    ``locked`` names every package the lock resolves for any platform, with
    the versions it admits. ``required`` is the dependency closure of the
    project and its dev group with every environment marker evaluated for the
    running interpreter, one exact version per name: what ``uv sync --locked``
    installs here.
    """

    locked: Mapping[str, frozenset[str]]
    required: Mapping[str, str]


def _read_lockfile(lock_path: Path, *, authenticate: bool) -> dict[str, object]:
    """Read the lock, authenticated against its protected pin unless told not to.

    An unauthenticated lock would let an edited lock and a matching drifted
    environment agree with each other, so the reference the environment is
    held to is itself held to the pin first.
    """
    try:
        raw = lock_path.read_bytes()
    except OSError as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot read lockfile {lock_path}: {error}"
        ) from error
    if authenticate:
        expected = PROTECTED_M1D_SHA256[_LOCKFILE_PIN]
        found = hashlib.sha256(raw).hexdigest()
        if found != expected:
            raise PinnedReplayIntegrityFailure(
                f"lockfile {lock_path} sha256 mismatch: expected {expected}, "
                f"got {found}"
            )
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot read lockfile {lock_path}: {error}"
        ) from error
    return document


def _default_dependency_groups() -> tuple[str, ...] | None:
    """The dependency groups ``uv sync`` installs by default, from pyproject.

    ``tool.uv.default-groups`` defaults to ``["dev"]``; ``"all"`` selects every
    group and is returned as ``None``.
    """
    try:
        document = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot read {PYPROJECT_PATH}: {error}"
        ) from error
    uv = document.get("tool", {}).get("uv", {})
    groups = uv.get("default-groups", ["dev"]) if isinstance(uv, dict) else ["dev"]
    if groups == "all":
        return None
    if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        raise PinnedReplayIntegrityFailure(
            f"{PYPROJECT_PATH} tool.uv.default-groups must be a list of names"
        )
    return tuple(groups)


def locked_environment(
    lock_path: Path = LOCKFILE_PATH,
    *,
    authenticate: bool = True,
    default_groups: Collection[str] | None | str = "pyproject",
) -> LockedEnvironment:
    """Resolve what the lock requires of this interpreter, failing closed.

    The closure starts at the single project root: its dependencies, plus the
    dependency groups ``uv sync`` installs by default. A ``virtual`` root is
    never installed itself, so only an editable root is required.
    ``default_groups`` defaults to what ``pyproject.toml`` declares; tests pass
    an explicit collection, or ``None`` for every group.
    """
    try:
        from packaging.markers import (
            InvalidMarker,
            Marker,
            UndefinedComparison,
            UndefinedEnvironmentName,
        )
    except ImportError as error:
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"the marker evaluator the lock requires is unavailable: {error}"
        ) from error

    document = _read_lockfile(lock_path, authenticate=authenticate)

    def refuse(detail: str) -> PinnedReplayIntegrityFailure:
        return PinnedReplayIntegrityFailure(
            f"cannot read lockfile {lock_path}: {detail}"
        )

    packages = document.get("package")
    if not isinstance(packages, list) or not packages:
        raise refuse("it locks no packages")
    by_name: dict[str, list[dict[str, object]]] = {}
    roots: list[dict[str, object]] = []
    for entry in packages:
        name = entry.get("name") if isinstance(entry, dict) else None
        version = entry.get("version") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not isinstance(version, str):
            raise refuse("a locked package lacks a name or a version")
        by_name.setdefault(_distribution_name(name), []).append(entry)
        source = entry.get("source")
        if isinstance(source, dict) and ("editable" in source or "virtual" in source):
            roots.append(entry)
    if len(roots) != 1:
        raise refuse(f"expected exactly one project package, found {len(roots)}")

    def edges(container: dict[str, object], key: str, owner: str) -> list[object]:
        value = container.get(key, [])
        if not isinstance(value, list):
            raise refuse(f"{owner} {key} is not a list")
        return value

    def resolve(edge: object) -> dict[str, object] | None:
        if not isinstance(edge, dict) or not isinstance(edge.get("name"), str):
            raise refuse("a dependency edge lacks a name")
        marker = edge.get("marker")
        if marker is not None:
            try:
                if not Marker(str(marker)).evaluate():
                    return None
            except (
                InvalidMarker,
                UndefinedComparison,
                UndefinedEnvironmentName,
            ) as error:
                raise refuse(f"unevaluable marker {marker!r}: {error}") from error
        candidates = by_name.get(_distribution_name(str(edge["name"])), [])
        if edge.get("version") is not None:
            candidates = [c for c in candidates if c["version"] == edge["version"]]
        if len(candidates) != 1:
            raise refuse(
                f"dependency {edge['name']} resolves to {len(candidates)} locked "
                "packages"
            )
        return candidates[0]

    (root,) = roots
    root_name = str(root["name"])
    required: dict[str, str] = {}
    source = root.get("source")
    if not (isinstance(source, dict) and "virtual" in source):
        required[_distribution_name(root_name)] = str(root["version"])
    pending = list(edges(root, "dependencies", root_name))
    groups = root.get("dev-dependencies", {})
    if not isinstance(groups, dict):
        raise refuse("the project dev-dependencies are not a table")
    selected = (
        _default_dependency_groups()
        if default_groups == "pyproject"
        else default_groups
    )
    for group in sorted(groups):
        if selected is None or group in selected:
            pending.extend(edges(groups, group, f"{root_name} dev-dependencies"))
    expanded: set[tuple[str, str]] = set()
    visited: set[str] = set()
    while pending:
        edge = pending.pop(0)
        entry = resolve(edge)
        if entry is None:
            continue
        key = _distribution_name(str(entry["name"]))
        version = str(entry["version"])
        if key in required and required[key] != version:
            raise refuse(f"{key} is required at both {required[key]} and {version}")
        required.setdefault(key, version)
        if key not in visited:
            visited.add(key)
            pending.extend(edges(entry, "dependencies", key))
        # Extras are expanded per edge, so an extra requested on a later edge
        # to an already visited package is still honoured.
        extras = edge.get("extra", []) if isinstance(edge, dict) else []
        optional = entry.get("optional-dependencies", {})
        if not isinstance(extras, list) or not isinstance(optional, dict):
            raise refuse(f"{key} extras or optional-dependencies are malformed")
        for extra in extras:
            if (key, str(extra)) not in expanded:
                expanded.add((key, str(extra)))
                pending.extend(
                    edges(optional, str(extra), f"{key} optional-dependencies")
                )
    locked = {
        name: frozenset(str(item["version"]) for item in entries)
        for name, entries in sorted(by_name.items())
    }
    return LockedEnvironment(locked=locked, required=dict(sorted(required.items())))


def observed_distribution_versions() -> dict[str, frozenset[str]]:
    """Return the distributions installed for this interpreter, by name.

    A distribution whose metadata carries no version is reported as "".
    """
    found: dict[str, set[str]] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name:
            found.setdefault(_distribution_name(name), set()).add(
                distribution.metadata.get("Version") or ""
            )
    return {name: frozenset(versions) for name, versions in sorted(found.items())}


def _verify_distributions(
    installed: Mapping[str, Collection[str]],
    *,
    where: str,
    lock_path: Path,
    authenticate: bool,
) -> int:
    """Hold an installed distribution set to the lock; return how many checked.

    Every difference is an environment mismatch: a package installed without
    a version, installed but not locked, installed but not required for this
    interpreter, installed at another version, or required but missing. Only
    names and versions are compared; a same-version shadow copy of a package
    is outside what installed metadata can show.
    """
    environment = locked_environment(lock_path, authenticate=authenticate)
    normalized: dict[str, set[str]] = {}
    for name, versions in installed.items():
        normalized.setdefault(_distribution_name(name), set()).update(versions)
    differences: list[str] = []
    for name, versions in sorted(normalized.items()):
        found = sorted(versions)
        if "" in versions:
            differences.append(f"{name} is installed with no version")
        elif name not in environment.locked:
            differences.append(f"{name} {found} is installed but not locked")
        elif name not in environment.required:
            differences.append(
                f"{name} {found} is installed but uv.lock does not require it "
                "for this interpreter"
            )
        elif found != [environment.required[name]]:
            differences.append(
                f"{name} found {found} expected {[environment.required[name]]}"
            )
    for name in sorted(set(environment.required) - set(normalized)):
        differences.append(
            f"{name} is required at {environment.required[name]} but not installed"
        )
    if differences:
        raise PinnedReplayEnvironmentMismatch(
            f"installed distributions differ from uv.lock in {where}: "
            + "; ".join(differences)
        )
    return len(normalized)


def verify_replay_distributions(
    *,
    installed: Mapping[str, Collection[str]] | None = None,
    lock_path: Path = LOCKFILE_PATH,
    authenticate: bool = True,
) -> int:
    """Require this interpreter's installed distributions to match ``uv.lock``.

    ``installed``, ``lock_path`` and ``authenticate`` exist so tests can present
    another environment or a synthetic lock; production callers leave them
    unset, so the lock is always authenticated against its protected pin.
    """
    return _verify_distributions(
        observed_distribution_versions() if installed is None else installed,
        where="running interpreter",
        lock_path=lock_path,
        authenticate=authenticate,
    )


def verify_replay_child_distributions(
    executable: str,
    *,
    environment: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    lock_path: Path = LOCKFILE_PATH,
    authenticate: bool = True,
) -> int:
    """Require the replay child's installed distributions to match ``uv.lock``."""
    try:
        completed = subprocess.run(
            [executable, "-c", _DISTRIBUTIONS_PROGRAM],
            cwd=cwd,
            env=None if environment is None else dict(environment),
            check=False,
            capture_output=True,
            timeout=_CHILD_START_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"replay child interpreter {executable} could not report its "
            f"distributions: {error}"
        ) from error
    try:
        reported = json.loads(completed.stdout.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        reported = None
    well_formed = isinstance(reported, dict) and all(
        isinstance(name, str)
        and isinstance(versions, list)
        and all(isinstance(version, str) for version in versions)
        for name, versions in reported.items()
    )
    if completed.returncode != 0 or not well_formed:
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"replay child interpreter {executable} could not report its "
            f"distributions (exit {completed.returncode}): "
            f"{_combined_output(completed)}"
        )
    return _verify_distributions(
        reported,
        where=f"replay child interpreter {executable}",
        lock_path=lock_path,
        authenticate=authenticate,
    )


def _load_inventory() -> dict[str, str]:
    try:
        raw = _INVENTORY_PATH.read_bytes()
    except OSError as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot read literal M1d inventory: {error}"
        ) from error
    if hashlib.sha256(raw).hexdigest() != _EXPECTED_INVENTORY_SHA256:
        raise PinnedReplayIntegrityFailure("literal M1d inventory sha256 mismatch")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PinnedReplayIntegrityFailure(
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
        raise PinnedReplayIntegrityFailure("literal M1d inventory is malformed")
    return dict(pins)


PROTECTED_M1D_ARCHIVE_SHA256 = _load_inventory()
"""Historical pins: the protected paths exactly as they stand at af75cce."""


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True)
class _FreezeInventory:
    """One inventory of the working-tree freeze chain, bound to its exact bytes."""

    label: str
    inventory_id: str
    path: Path
    file_sha256: str
    issue: int | None
    """The issue whose link introduced it; ``None`` only for the v3 root."""
    commit: str | None
    """The commit whose tree every pin describes exactly.

    For a link that is the commit that last wrote it. It is ``None`` only for
    the current tip, which describes the live working tree and cannot name the
    commit that will contain it.
    """


_FREEZE_FIXTURES = REPO_ROOT / "tests/fixtures/m1e-compatibility"
_FREEZE_INVENTORIES: tuple[_FreezeInventory, ...] = (
    _FreezeInventory(
        label="v3",
        inventory_id=_HISTORICAL_INVENTORY_ID,
        path=_INVENTORY_PATH,
        file_sha256=_EXPECTED_INVENTORY_SHA256,
        issue=None,
        commit=PINNED_M1D_COMMIT,
    ),
    _FreezeInventory(
        label="v4",
        inventory_id="m1d-v4-protected-sha256",
        path=_FREEZE_FIXTURES / "m1d-v4-protected-sha256.json",
        file_sha256="4af2e06734e8fadde2002d69fe9d48bd5eca369e771862f2e09df150238d76d2",
        issue=32,
        commit="4ad90aa97da677386ac212c3596703fccb309f3b",
    ),
    _FreezeInventory(
        label="v5",
        inventory_id="m1d-v5-protected-sha256",
        path=_FREEZE_FIXTURES / "m1d-v5-protected-sha256.json",
        file_sha256="a4610db34e6588ee7e0f232f39f2a50a98109f0299533f2509f5963b16200710",
        issue=63,
        commit="200bfebaf04c5c1e171db029547a75187d2ef665",
    ),
    _FreezeInventory(
        label="v6",
        inventory_id="m1d-v6-protected-sha256",
        path=_FREEZE_FIXTURES / "m1d-v6-protected-sha256.json",
        file_sha256="03188643b56525fdcc68dcb191783edff000fc9cc066b88c38a26ef1155bf725",
        issue=107,
        commit=None,
    ),
)
"""The freeze chain, root first; each entry supersedes the one before it.

To supersede the tip, append the new link here and record on the entry it
supersedes the commit that last wrote that entry. Nothing else changes: every
link is re-derived over the re-derived pins of its predecessor."""


@dataclass(frozen=True, slots=True)
class _FreezeLink:
    """One working-tree freeze link and the inventory it supersedes."""

    label: str
    inventory_id: str
    path: Path
    file_sha256: str
    issue: int
    requires_current_role: bool
    superseded_id: str
    superseded_path: str
    superseded_file_sha256: str
    superseded_commit: str


def _chain_links(inventories: Sequence[_FreezeInventory]) -> tuple[_FreezeLink, ...]:
    """Pair every link with the inventory it supersedes, checking the shape.

    The chain starts at the historical v3 inventory. Only the tip may leave its
    commit open and only the tip must still call itself current: a superseded
    link keeps the role it was minted with, because history is superseded,
    never rewritten.
    """
    if not inventories or inventories[0].inventory_id != _HISTORICAL_INVENTORY_ID:
        raise PinnedReplayIntegrityFailure("M1d freeze chain must start at v3")
    if len(inventories) < 2:
        raise PinnedReplayIntegrityFailure("M1d freeze chain needs at least one link")
    tip = len(inventories) - 1
    links: list[_FreezeLink] = []
    for index in range(1, len(inventories)):
        superseded, inventory = inventories[index - 1], inventories[index]
        if (
            superseded.commit is None
            or not _GIT_SHA.fullmatch(superseded.commit)
            or inventory.issue is None
            or (inventory.commit is None) != (index == tip)
        ):
            raise PinnedReplayIntegrityFailure(
                f"{inventory.label} M1d freeze link is malformed"
            )
        links.append(
            _FreezeLink(
                label=inventory.label,
                inventory_id=inventory.inventory_id,
                path=inventory.path,
                file_sha256=inventory.file_sha256,
                issue=inventory.issue,
                requires_current_role=index == tip,
                superseded_id=superseded.inventory_id,
                superseded_path=superseded.path.relative_to(REPO_ROOT).as_posix(),
                superseded_file_sha256=superseded.file_sha256,
                superseded_commit=superseded.commit,
            )
        )
    return tuple(links)


FREEZE_LINKS = _chain_links(_FREEZE_INVENTORIES)
"""v4 (issue #32) over v3, v5 (issue #63) over v4, v6 (issue #107) over v5."""


def _superseded_source_pins(
    document: object, link: _FreezeLink
) -> dict[str, dict[str, str]]:
    """Return the declared supersessions, rejecting a malformed declaration."""
    if not isinstance(document, dict):
        raise PinnedReplayIntegrityFailure(f"{link.label} M1d inventory is malformed")
    supersedes = document.get("supersedes")
    superseded = document.get("superseded_paths")
    if (
        not isinstance(supersedes, dict)
        or not isinstance(superseded, dict)
        or not superseded
        or supersedes.get("inventory_id") != link.superseded_id
        or supersedes.get("path") != link.superseded_path
        or supersedes.get("commit") != link.superseded_commit
        or supersedes.get("file_sha256") != link.superseded_file_sha256
        or supersedes.get("issue") != link.issue
        or not _is_nonblank(supersedes.get("status"))
        or not _is_nonblank(supersedes.get("reason"))
    ):
        raise PinnedReplayIntegrityFailure(
            f"{link.label} M1d inventory supersession is malformed"
        )
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
            raise PinnedReplayIntegrityFailure(
                f"{link.label} M1d inventory supersession is malformed for {path}"
            )
    return dict(superseded)


def _added_source_pins(
    document: Mapping[str, object], link: _FreezeLink
) -> dict[str, dict[str, object]]:
    """Return the declared additions, rejecting a malformed declaration.

    An addition widens the freeze onto a path the superseded inventory never
    pinned, so it has to stand on its own justification and on its own link's
    issue rather than on the key sets merely differing. Declaring no additions
    at all is allowed; what is not allowed is a pin that no declaration
    accounts for.
    """
    added = document.get("added_paths", {})
    if not isinstance(added, dict):
        raise PinnedReplayIntegrityFailure(
            f"{link.label} M1d inventory addition block is malformed"
        )
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
            or record["issue"] != link.issue
            or not isinstance(justification, str)
            or not justification.strip()
        ):
            raise PinnedReplayIntegrityFailure(
                f"{link.label} M1d inventory addition is malformed for {path}"
            )
    return dict(added)


def _validated_link_pins(
    document: object, link: _FreezeLink, parent: Mapping[str, str]
) -> dict[str, str]:
    """Re-derive one link's pins from its parent's pins plus its declared delta.

    A link is only allowed to differ from the inventory it supersedes on the
    paths its own ``superseded_paths`` and ``added_paths`` blocks declare. A
    superseded path must already be pinned by the parent and must carry the
    digest it replaces; an added path must not be pinned by the parent at all
    and must carry its own justification. Anything else is a silent re-signing
    or a silent widening and fails closed here.
    """
    if not isinstance(document, dict):
        raise PinnedReplayIntegrityFailure(f"{link.label} M1d inventory is malformed")
    pins = document.get("sha256")
    superseded = _superseded_source_pins(document, link)
    added = _added_source_pins(document, link)
    if (
        not isinstance(pins, dict)
        or document.get("inventory_id") != link.inventory_id
        or document.get("baseline_commit") != PINNED_M1D_COMMIT
        or (link.requires_current_role and document.get("role") != "current")
        or any(
            not isinstance(digest, str) or len(digest) != 64 for digest in pins.values()
        )
    ):
        raise PinnedReplayIntegrityFailure(f"{link.label} M1d inventory is malformed")
    expected = dict(parent)
    for path, record in superseded.items():
        if path not in expected:
            raise PinnedReplayIntegrityFailure(
                f"{link.label} M1d inventory supersedes an unpinned path: {path}"
            )
        if record["historical_sha256"] != expected[path]:
            raise PinnedReplayIntegrityFailure(
                f"{link.label} M1d inventory misstates the superseded pin for {path}"
            )
        expected[path] = record["current_sha256"]
    for path, addition in added.items():
        if path in parent:
            raise PinnedReplayIntegrityFailure(
                f"{link.label} M1d inventory declares an addition the inventory "
                f"it supersedes already pins: {path}"
            )
        expected[path] = str(addition["current_sha256"])
    undeclared = sorted(set(pins) - set(expected))
    if undeclared:
        raise PinnedReplayIntegrityFailure(
            f"{link.label} M1d inventory pins an undeclared added path: {undeclared}"
        )
    omitted = sorted(set(expected) - set(pins))
    if omitted:
        raise PinnedReplayIntegrityFailure(
            f"{link.label} M1d inventory omits a required protected path: {omitted}"
        )
    if pins != expected:
        drifted = sorted(path for path in pins if pins[path] != expected[path])
        raise PinnedReplayIntegrityFailure(
            f"{link.label} M1d inventory re-signs undeclared protected paths: {drifted}"
        )
    return dict(pins)


def _read_link_document(path: Path, expected_sha256: str, label: str) -> object:
    """Read one link's bytes, authenticated against its literal file pin."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot read {label} M1d inventory: {error}"
        ) from error
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise PinnedReplayIntegrityFailure(f"{label} M1d inventory sha256 mismatch")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot parse {label} M1d inventory: {error}"
        ) from error


def _load_link_document(link: _FreezeLink) -> object:
    """Read one link's document, authenticated against its literal file pin."""
    return _read_link_document(link.path, link.file_sha256, link.label)


def _freeze_link(label: str) -> _FreezeLink:
    for link in FREEZE_LINKS:
        if link.label == label:
            return link
    raise PinnedReplayIntegrityFailure(f"unknown M1d freeze link: {label}")


def _load_freeze_chain() -> dict[str, dict[str, str]]:
    """Re-derive every link, root first, over its predecessor's re-derived pins."""
    chain: dict[str, dict[str, str]] = {}
    parent = PROTECTED_M1D_ARCHIVE_SHA256
    for link in FREEZE_LINKS:
        parent = _validated_link_pins(_load_link_document(link), link, parent)
        chain[link.label] = parent
    return chain


FREEZE_CHAIN_SHA256 = _load_freeze_chain()
"""Re-derived pins of every freeze link, by label, in chain order.

Every superseded link still describes exactly the commit that last wrote it
(``FREEZE_LINKS[i + 1].superseded_commit``); only the tip describes the live
working tree."""


def _validated_chain_pins(label: str, document: object) -> dict[str, str]:
    """Re-derive one link's pins from its predecessor's pins plus its delta."""
    link = _freeze_link(label)
    index = FREEZE_LINKS.index(link)
    parent = (
        FREEZE_CHAIN_SHA256[FREEZE_LINKS[index - 1].label]
        if index
        else PROTECTED_M1D_ARCHIVE_SHA256
    )
    return _validated_link_pins(document, link, parent)


PROTECTED_M1D_SHA256 = FREEZE_CHAIN_SHA256[FREEZE_LINKS[-1].label]
"""Current pins: the protected paths as they must stand in the working tree."""

_REQUIRED_PROTECTED_PATHS = frozenset(PROTECTED_M1D_SHA256)
_REQUIRED_ARCHIVE_PATHS = frozenset(PROTECTED_M1D_ARCHIVE_SHA256)


def _historical_generation_pins(generation: str) -> dict[str, str]:
    """Return the preserved v3 pins that authenticate one generation's archive.

    The af75cce archive is authenticated against every v3 pin. The older v1
    and v2 archives predate the rest of that tree, so they are authenticated
    against the v3 pins of their own fixture directory, whose bytes never
    moved after the commit that generated them.
    """
    if generation == "v3":
        return dict(PROTECTED_M1D_ARCHIVE_SHA256)
    if generation not in PINNED_M1D_GENERATIONS:
        raise PinnedReplayIntegrityFailure(
            f"unknown M1d fixture generation: {generation}"
        )
    prefix = f"tests/fixtures/m1d/{generation}/"
    pins = {
        path: digest
        for path, digest in PROTECTED_M1D_ARCHIVE_SHA256.items()
        if path.startswith(prefix)
    }
    if len(pins) != 160:
        raise PinnedReplayIntegrityFailure(
            f"historical {generation} fixture pins are incomplete: {len(pins)}"
        )
    return pins


@dataclass(frozen=True, slots=True)
class ReplayOverlay:
    """One declared path the superseding baseline replaces in a replay archive.

    ``baseline_path`` names the repository file holding the replacement bytes.
    It is ``None`` only for the archived fixture loader, whose replacement is
    derived by swapping its single hash-index digest literal.
    """

    path: str
    historical_sha256: str
    current_sha256: str
    baseline_path: str | None


@dataclass(frozen=True, slots=True)
class ReplayBaselineGeneration:
    """The superseding replay baseline for one M1d fixture generation."""

    generation: str
    source_commit: str
    overlays: tuple[ReplayOverlay, ...]
    pins: Mapping[str, str]


def _validated_baseline_hash_index(
    label: str, overlays: Mapping[str, ReplayOverlay]
) -> None:
    """Require the superseding index to describe the superseding results."""
    index = next(
        item for path, item in overlays.items() if path.endswith("/hash-index.json")
    )
    assert index.baseline_path is not None
    try:
        entries = json.loads((REPO_ROOT / index.baseline_path).read_bytes())["entries"]
        declared = {entry["path"]: entry for entry in entries}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PinnedReplayIntegrityFailure(
            f"{label} hash index is unreadable: {error}"
        ) from error
    for path, overlay in overlays.items():
        name = path.rsplit("/", maxsplit=1)[-1]
        if overlay.baseline_path is None or name == "hash-index.json":
            continue
        data = (REPO_ROOT / overlay.baseline_path).read_bytes()
        entry = declared.get(name)
        if (
            not isinstance(entry, dict)
            or entry.get("sha256") != overlay.current_sha256
            or entry.get("byte_size") != len(data)
        ):
            raise PinnedReplayIntegrityFailure(
                f"{label} hash index does not describe the superseding {name}"
            )


def _validated_replay_generation(
    generation: str, entry: object
) -> ReplayBaselineGeneration:
    """Validate one generation and derive its replay archive pins."""
    label = f"replay baseline {generation}"
    root = f"tests/fixtures/m1d/{generation}"
    if (
        not isinstance(entry, dict)
        or entry.get("source_commit") != PINNED_M1D_GENERATIONS[generation]
        or entry.get("fixture_root") != root
    ):
        raise PinnedReplayIntegrityFailure(
            f"{label} must name its own source commit and fixture root"
        )
    lockfile = entry.get("lockfile_identity")
    semantic = entry.get("semantic_implementation_identity")
    if (
        not isinstance(lockfile, dict)
        or set(lockfile) != {"uv_lock_sha256"}
        or not _is_digest(lockfile["uv_lock_sha256"])
        or not isinstance(semantic, dict)
        or set(semantic) != {"implementation_hash", "semantic_algorithm_hash"}
        or not all(_is_digest(value) for value in semantic.values())
    ):
        raise PinnedReplayIntegrityFailure(
            f"{label} must name its lockfile and semantic implementation identity"
        )
    replacements = {
        f"{root}/{name}": f"{_REPLAY_BASELINE_DIRECTORY}/{generation}/{name}"
        for name in _REMINTED_FIXTURE_NAMES
    }
    allowed = sorted({*replacements, _FIXTURE_SUPPORT_PATH})
    superseded = entry.get("superseded_paths")
    if not isinstance(superseded, dict) or sorted(superseded) != allowed:
        found = sorted(superseded) if isinstance(superseded, dict) else superseded
        raise PinnedReplayIntegrityFailure(
            f"{label} may only supersede {allowed}, found {found!r}"
        )
    historical = _historical_generation_pins(generation)
    pins = dict(historical)
    overlays: dict[str, ReplayOverlay] = {}
    for path in allowed:
        record = superseded[path]
        if (
            not isinstance(record, dict)
            or not _is_digest(record.get("historical_sha256"))
            or not _is_digest(record.get("current_sha256"))
            or record["historical_sha256"] == record["current_sha256"]
        ):
            raise PinnedReplayIntegrityFailure(
                f"{label} supersession is malformed for {path}"
            )
        baseline_path: str | None
        if path == _FIXTURE_SUPPORT_PATH:
            if (
                set(record) != {"historical_sha256", "current_sha256", "derivation"}
                or record["derivation"] != _FIXTURE_SUPPORT_DERIVATION
                or path in historical
            ):
                raise PinnedReplayIntegrityFailure(
                    f"{label} supersession is malformed for {path}"
                )
            baseline_path = None
        else:
            if (
                set(record) != {"historical_sha256", "current_sha256", "baseline_path"}
                or record["baseline_path"] != replacements[path]
            ):
                raise PinnedReplayIntegrityFailure(
                    f"{label} supersession is malformed for {path}"
                )
            if record["historical_sha256"] != historical.get(path):
                raise PinnedReplayIntegrityFailure(
                    f"{label} misstates the historical pin for {path}"
                )
            baseline_path = record["baseline_path"]
            try:
                data = (REPO_ROOT / baseline_path).read_bytes()
            except OSError as error:
                raise PinnedReplayIntegrityFailure(
                    f"{label} bytes are unavailable for {path}: {error}"
                ) from error
            if hashlib.sha256(data).hexdigest() != record["current_sha256"]:
                raise PinnedReplayIntegrityFailure(
                    f"{label} bytes do not match the supersession record for {path}"
                )
        overlays[path] = ReplayOverlay(
            path=path,
            historical_sha256=record["historical_sha256"],
            current_sha256=record["current_sha256"],
            baseline_path=baseline_path,
        )
        pins[path] = record["current_sha256"]
    _validated_baseline_hash_index(label, overlays)
    return ReplayBaselineGeneration(
        generation=generation,
        source_commit=PINNED_M1D_GENERATIONS[generation],
        overlays=tuple(overlays.values()),
        pins=pins,
    )


def _validated_replay_baseline(document: object) -> dict[str, ReplayBaselineGeneration]:
    """Validate the supersession record and derive every generation's pins.

    The record may re-mint only the two expected result documents and the
    hash index of each generation, plus the one digest literal in that
    generation's archived loader. It can never supersede semantic source.
    """
    if (
        not isinstance(document, dict)
        or document.get("record_id") != _REPLAY_BASELINE_ID
        or document.get("role") != "current"
        or document.get("issue") != _REPLAY_BASELINE_ISSUE
        or not _is_nonblank(document.get("reason"))
    ):
        raise PinnedReplayIntegrityFailure("replay baseline record is malformed")
    if document.get("baseline") != {
        "baseline_id": _REPLAY_BASELINE_ID,
        "python_identity": REPLAY_BASELINE_PYTHON_IDENTITY,
        "interpreter_pin": PYTHON_PIN_PATH.name,
    }:
        raise PinnedReplayIntegrityFailure(
            "replay baseline must name itself, its interpreter identity "
            f"{REPLAY_BASELINE_PYTHON_IDENTITY} and its interpreter pin"
        )
    supersedes = document.get("supersedes")
    if (
        not isinstance(supersedes, dict)
        or supersedes.get("python_identity") != SUPERSEDED_REPLAY_PYTHON_IDENTITY
    ):
        raise PinnedReplayIntegrityFailure(
            "replay baseline supersession must name the superseded interpreter "
            f"identity {SUPERSEDED_REPLAY_PYTHON_IDENTITY}"
        )
    if (
        supersedes.get("baseline_id") != _SUPERSEDED_REPLAY_BASELINE_ID
        or supersedes.get("historical_inventory")
        != {
            "inventory_id": _HISTORICAL_INVENTORY_ID,
            "path": _INVENTORY_PATH.relative_to(REPO_ROOT).as_posix(),
            "file_sha256": _EXPECTED_INVENTORY_SHA256,
        }
        or not _is_nonblank(supersedes.get("status"))
    ):
        raise PinnedReplayIntegrityFailure(
            "replay baseline supersession must name the superseded baseline and "
            "its preserved historical inventory"
        )
    verification = document.get("verification")
    if (
        not isinstance(verification, dict)
        or verification.get("result") != "passed"
        or verification.get("python_identity") != REPLAY_BASELINE_PYTHON_IDENTITY
    ):
        raise PinnedReplayIntegrityFailure(
            "replay baseline must record a passed verification under "
            f"{REPLAY_BASELINE_PYTHON_IDENTITY}"
        )
    generations = document.get("generations")
    if not isinstance(generations, dict) or set(generations) != set(
        PINNED_M1D_GENERATIONS
    ):
        raise PinnedReplayIntegrityFailure(
            "replay baseline must cover every M1d fixture generation"
        )
    return {
        generation: _validated_replay_generation(generation, generations[generation])
        for generation in sorted(PINNED_M1D_GENERATIONS)
    }


def _load_replay_baseline() -> dict[str, ReplayBaselineGeneration]:
    try:
        raw = _REPLAY_BASELINE_PATH.read_bytes()
    except OSError as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot read replay baseline record: {error}"
        ) from error
    if hashlib.sha256(raw).hexdigest() != _EXPECTED_REPLAY_BASELINE_SHA256:
        raise PinnedReplayIntegrityFailure("replay baseline record sha256 mismatch")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot parse replay baseline record: {error}"
        ) from error
    return _validated_replay_baseline(document)


REPLAY_BASELINE = _load_replay_baseline()
"""Current replay baseline: cpython-3.14.6, superseding the 3.14.5 history."""


def _verify_pinned_inputs(
    *, root: Path, pins: Mapping[str, str], required: frozenset[str], label: str
) -> None:
    if set(pins) != required:
        raise PinnedReplayIntegrityFailure(
            f"{label} M1d inventory is incomplete or contains unknown paths"
        )
    for path, digest in pins.items():
        try:
            data = (root / path).read_bytes()
        except OSError as error:
            raise PinnedReplayIntegrityFailure(
                f"protected M1d path is unavailable: {path}: {error}"
            ) from error
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise PinnedReplayIntegrityFailure(
                "protected M1d sha256 mismatch for "
                f"{path}: expected {digest}, got {actual}"
            )


def verify_m1d_protected_inputs(
    *, root: Path, expected: Mapping[str, str] | None = None
) -> None:
    """Reject a changed M1d source, fixture, or environment input in the tree.

    This is the CURRENT freeze. It uses the pins of the chain tip: v3, then
    the v4 delta (the paths issue #32 moved, plus the module that defines the
    M1d replay identities), then the v5 delta (the identity accessor and
    attestation module issue #63 moved), then the v6 delta (the attestation
    module issue #107 hardened), reproducing v3 everywhere else.
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


def _archive_bytes(commit: str) -> bytes:
    """Return the finite tar archive of one historical commit.

    A checkout that lacks the commit, for example a shallow clone, cannot
    replay at all. That is an unavailable environment artifact, not a replay
    or integrity result.
    """
    try:
        present = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"git is unavailable, so historical Git commit {commit} is unavailable: "
            f"{error}"
        ) from error
    if present.returncode != 0:
        raise PinnedReplayEnvironmentArtifactUnavailable(
            f"historical Git commit {commit} is unavailable in this checkout; "
            "pinned replay needs the full history (a non-shallow clone): "
            f"{_combined_output(present)}"
        )
    completed = subprocess.run(
        ["git", "archive", "--format=tar", commit, "--", *_ARCHIVE_PATHS],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise PinnedReplayIntegrityFailure(
            f"cannot extract pinned M1d commit {commit}: {_combined_output(completed)}"
        )
    return completed.stdout


def _unpack_archive(destination: Path, commit: str) -> None:
    raw = _archive_bytes(commit)
    try:
        with tarfile.open(fileobj=BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            if any(
                member.name.startswith("/") or ".." in Path(member.name).parts
                for member in members
            ):
                raise PinnedReplayIntegrityFailure(
                    "pinned M1d Git archive contains an unsafe path"
                )
            archive.extractall(destination, members=members, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise PinnedReplayIntegrityFailure(
            f"cannot unpack pinned M1d commit {commit}: {error}"
        ) from error


def extract_m1d_archive(
    destination: Path,
    *,
    commit: str = PINNED_M1D_COMMIT,
    observed_identity: str | None = None,
) -> Path:
    """Extract the finite authenticated M1d archive from the local pinned commit.

    The interpreter is verified first, so a wrong interpreter never pays for,
    or leaves behind, an extracted archive.
    """
    if commit != PINNED_M1D_COMMIT:
        raise PinnedReplayIntegrityFailure(
            f"unapproved M1d interpreter commit: {commit}"
        )
    verify_replay_interpreter(observed=observed_identity)
    verify_replay_distributions()
    destination.mkdir(parents=True, exist_ok=True)
    _unpack_archive(destination, commit)
    verify_m1d_archive_inputs(root=destination)
    return destination


def extract_m1d_generation_archive(
    destination: Path, generation: str, *, observed_identity: str | None = None
) -> Path:
    """Extract and authenticate the archive of one generation's source commit."""
    if generation not in PINNED_M1D_GENERATIONS:
        raise PinnedReplayIntegrityFailure(
            f"unknown M1d fixture generation: {generation}"
        )
    if generation == "v3":
        return extract_m1d_archive(destination, observed_identity=observed_identity)
    pins = _historical_generation_pins(generation)
    verify_replay_interpreter(observed=observed_identity)
    verify_replay_distributions()
    destination.mkdir(parents=True, exist_ok=True)
    _unpack_archive(destination, PINNED_M1D_GENERATIONS[generation])
    _verify_pinned_inputs(
        root=destination,
        pins=pins,
        required=frozenset(pins),
        label=f"archived {generation}",
    )
    return destination


def apply_m1d_replay_baseline(archive_root: Path, generation: str) -> Path:
    """Replace the declared historical paths with the superseding baseline.

    Each replaced path must still hold its historical bytes, so the overlay
    can only ever be applied once and only over the authenticated history.
    The whole archive is then re-authenticated against the replay pins.
    """
    baseline = REPLAY_BASELINE[generation]
    index = next(
        overlay
        for overlay in baseline.overlays
        if overlay.path.endswith("/hash-index.json")
    )
    for overlay in baseline.overlays:
        target = archive_root / overlay.path
        try:
            historical = target.read_bytes()
        except OSError as error:
            raise PinnedReplayIntegrityFailure(
                f"archived {overlay.path} is unavailable: {error}"
            ) from error
        if hashlib.sha256(historical).hexdigest() != overlay.historical_sha256:
            raise PinnedReplayIntegrityFailure(
                f"archived {overlay.path} is not the superseded historical baseline"
            )
        if overlay.baseline_path is None:
            literal = index.historical_sha256.encode("ascii")
            if historical.count(literal) != 1:
                raise PinnedReplayIntegrityFailure(
                    f"archived {overlay.path} does not pin the historical index once"
                )
            replacement = historical.replace(
                literal, index.current_sha256.encode("ascii")
            )
        else:
            replacement = (REPO_ROOT / overlay.baseline_path).read_bytes()
        if hashlib.sha256(replacement).hexdigest() != overlay.current_sha256:
            raise PinnedReplayIntegrityFailure(
                f"replay baseline {generation} bytes do not match the supersession "
                f"record for {overlay.path}"
            )
        target.write_bytes(replacement)
    _verify_pinned_inputs(
        root=archive_root,
        pins=baseline.pins,
        required=frozenset(baseline.pins),
        label=f"replay baseline {generation}",
    )
    return archive_root


def prepare_m1d_replay_archive(
    destination: Path, generation: str, *, observed_identity: str | None = None
) -> Path:
    """Extract one generation's source commit and apply the current baseline."""
    archive = extract_m1d_generation_archive(
        destination, generation, observed_identity=observed_identity
    )
    return apply_m1d_replay_baseline(archive, generation)


def verify_child_import_location(imported_file: str, archive_root: Path) -> None:
    """Require the child interpreter to import Drift from the extracted archive."""
    imported = Path(imported_file).resolve()
    if not imported.is_relative_to(archive_root.resolve()):
        raise PinnedReplayIntegrityFailure(
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


def run_replay_child(
    archive_root: Path,
    nodes: tuple[str, ...],
    *,
    commit: str,
    expected_pins: Mapping[str, str],
    label: str,
    observed_identity: str | None = None,
    executable: str | None = None,
) -> PinnedM1dReplayResult:
    """Run archived nodes in an authenticated archive and classify any failure.

    Order is load-bearing: interpreter identity and installed distributions,
    then protected input bytes, then the child interpreter's own identity and
    distributions, then the child import location, and only then the replay
    itself. A failure of the replay can therefore only be a semantic replay
    mismatch.
    """
    if not nodes:
        raise PinnedReplayIntegrityFailure(f"{label} replay declares no nodes")
    expected = verify_replay_interpreter(observed=observed_identity)
    verify_replay_distributions()
    _verify_pinned_inputs(
        root=archive_root,
        pins=expected_pins,
        required=frozenset(expected_pins),
        label=label,
    )
    environment = _child_environment(archive_root)
    interpreter = sys.executable if executable is None else executable
    verify_replay_child_interpreter(
        interpreter, environment=environment, cwd=archive_root
    )
    verify_replay_child_distributions(
        interpreter, environment=environment, cwd=archive_root
    )
    imported = subprocess.run(
        [interpreter, "-c", "import drift; print(drift.__file__)"],
        cwd=archive_root,
        env=environment,
        check=False,
        capture_output=True,
    )
    if imported.returncode != 0:
        raise PinnedReplayIntegrityFailure(
            f"child cannot import pinned M1d Drift: {_combined_output(imported)}"
        )
    verify_child_import_location(imported.stdout.decode("utf-8").strip(), archive_root)
    completed = subprocess.run(
        [interpreter, "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes],
        cwd=archive_root,
        env=environment,
        check=False,
        capture_output=True,
    )
    names = " ".join(nodes)
    result = PinnedM1dReplayResult(
        commit=commit,
        nodeid=names,
        returncode=completed.returncode,
        output=_combined_output(completed),
    )
    if result.returncode == 1:
        raise PinnedReplaySemanticMismatch(
            f"environment {expected} matched and {label} inputs authenticated, "
            f"but replay failed for {names}:\n{result.output}"
        )
    if result.returncode != 0:
        raise PinnedReplayIntegrityFailure(
            f"{label} replay could not execute {names} "
            f"(pytest exit {result.returncode}):\n{result.output}"
        )
    if re.search(rf"(?<![0-9]){len(nodes)} passed", result.output) is None:
        raise PinnedReplayIntegrityFailure(
            f"{label} replay did not execute exactly the declared nodes {names}:\n"
            f"{result.output}"
        )
    return result


def _run_archived_m1d_node_in_root(
    archive_root: Path, nodeid: str, *, observed_identity: str | None = None
) -> PinnedM1dReplayResult:
    """Run one M1d node inside an already prepared v3 replay archive."""
    return run_replay_child(
        archive_root,
        (nodeid,),
        commit=PINNED_M1D_COMMIT,
        expected_pins=REPLAY_BASELINE["v3"].pins,
        label="replay baseline v3",
        observed_identity=observed_identity,
    )


def run_archived_m1d_node(nodeid: str) -> PinnedM1dReplayResult:
    """Authenticate and run one exact M1d node without current-package imports."""
    with tempfile.TemporaryDirectory(prefix="drift-m1d-v3-replay-") as directory:
        archive = prepare_m1d_replay_archive(Path(directory), "v3")
        return _run_archived_m1d_node_in_root(archive, nodeid)


def run_m1d_generation_replay(
    generation: str, nodes: tuple[str, ...], *, observed_identity: str | None = None
) -> PinnedM1dReplayResult:
    """Authenticate and run nodes from one generation's own source commit."""
    with tempfile.TemporaryDirectory(
        prefix=f"drift-m1d-{generation}-replay-"
    ) as directory:
        archive = prepare_m1d_replay_archive(
            Path(directory), generation, observed_identity=observed_identity
        )
        return run_replay_child(
            archive,
            nodes,
            commit=PINNED_M1D_GENERATIONS[generation],
            expected_pins=REPLAY_BASELINE[generation].pins,
            label=f"replay baseline {generation}",
            observed_identity=observed_identity,
        )


class PinnedM1dArchiveCache:
    """One prepared v3 replay archive for the parent pytest session."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="drift-m1d-v3-session-")
        self.root = prepare_m1d_replay_archive(Path(self._temporary.name), "v3")

    def close(self) -> None:
        self._temporary.cleanup()
