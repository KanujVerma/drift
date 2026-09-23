"""Interpreter identity guard and failure classes for pinned M1d replay (#48).

Pinned M1d replay binds the exact interpreter patch version into every
normalization derivation (``derivation.python_identity``). These tests prove
that the replay harness checks that identity against the repository pin
before any expensive replay work, and that the four failure classes the
architecture ruling on issue #47 requires stay distinguishable:

* environment mismatch: the running interpreter is not the pinned one;
* environment artifact unavailable: the pinned interpreter or another
  required replay environment artifact cannot be obtained;
* semantic replay mismatch: the environment matched and every input
  authenticated, but the recomputed artifact differs;
* fixture or inventory integrity failure: protected bytes differ from their
  inventory, or an inventory or pin is itself malformed.

Every negative test catches ``BaseException`` and asserts the exact failure
type, so a guard that silently skipped (``pytest.skip`` raises a
``BaseException``) or downgraded to a sibling class would fail here rather
than pass or disappear from the report.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PINNED_IDENTITY = "cpython-3.14.6"
V3_REPLAY_NODE = (
    "tests/integration/test_m1d_adversarial_matrix.py::"
    "test_current_expected_decision_and_outcome_bytes_replay"
)


def _load_replay_helper() -> ModuleType:
    helper_path = REPO_ROOT / "tests" / "_pinned_m1d.py"
    spec = importlib.util.spec_from_file_location("_m1d_env_pinned_m1d", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _raised(call: Callable[[], object]) -> BaseException:
    """Return whatever ``call`` raised, including skip and exit outcomes."""
    try:
        call()
    except BaseException as error:  # skip and exit outcomes must be caught too
        return error
    pytest.fail("expected the pinned replay guard to raise, but it returned")


def _classes(helper: ModuleType) -> tuple[Any, ...]:
    return (
        helper.PinnedReplayEnvironmentMismatch,
        helper.PinnedReplayEnvironmentArtifactUnavailable,
        helper.PinnedReplaySemanticMismatch,
        helper.PinnedReplayIntegrityFailure,
    )


def _executable_script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_repository_pin_is_one_exact_patch_version() -> None:
    """``.python-version`` is the single exact pin; the package floor is separate."""
    assert (REPO_ROOT / ".python-version").read_bytes() == b"3.14.6\n"
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.14"' in pyproject
    helper = _load_replay_helper()
    assert helper.PYTHON_PIN_PATH == REPO_ROOT / ".python-version"
    assert helper.pinned_interpreter_identity() == PINNED_IDENTITY


def test_exact_pinned_interpreter_is_accepted() -> None:
    """The pinned identity passes, and this pinned environment really is it."""
    helper = _load_replay_helper()
    assert helper.verify_replay_interpreter(observed=PINNED_IDENTITY) == (
        PINNED_IDENTITY
    )
    observed = helper.observed_interpreter_identity()
    assert observed == (
        f"{sys.implementation.name}-{sys.version_info.major}."
        f"{sys.version_info.minor}.{sys.version_info.micro}"
    )
    assert helper.verify_replay_interpreter() == observed == PINNED_IDENTITY


@pytest.mark.parametrize(
    "found",
    (
        "cpython-3.14.5",
        "cpython-3.14.7",
        "cpython-3.15.6",
        "cpython-3.14",
        "cpython-3.14.60",
        "pypy-3.14.6",
    ),
)
def test_wrong_interpreter_is_rejected_with_the_named_diagnostic(found: str) -> None:
    """Any other identity, including another patch, fails with both identities."""
    helper = _load_replay_helper()
    error = _raised(lambda: helper.verify_replay_interpreter(observed=found))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert re.fullmatch(
        rf"PINNED_REPLAY_ENVIRONMENT_MISMATCH expected cpython-3\.14\.6 "
        rf"found {re.escape(found)}",
        str(error),
    ), str(error)


def test_wrong_patch_is_rejected_before_archive_extraction(tmp_path: Path) -> None:
    """The guard runs before any archive is written, not after replay work."""
    helper = _load_replay_helper()
    destination = tmp_path / "archive"
    error = _raised(
        lambda: helper.extract_m1d_archive(
            destination, observed_identity="cpython-3.14.5"
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error) == (
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH expected cpython-3.14.6 "
        "found cpython-3.14.5"
    )
    assert not destination.exists()


def test_wrong_patch_is_rejected_before_archived_inputs_are_read(
    tmp_path: Path,
) -> None:
    """A missing archive would be an integrity failure; the guard fires first."""
    helper = _load_replay_helper()
    missing_root = tmp_path / "never-extracted"
    error = _raised(
        lambda: helper._run_archived_m1d_node_in_root(
            missing_root, V3_REPLAY_NODE, observed_identity="cpython-3.14.5"
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error).startswith(
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH expected cpython-3.14.6 "
        "found cpython-3.14.5"
    )
    # Control: with the identity matching, the same call reaches the input
    # check and reports the missing archive as an integrity failure instead.
    control = _raised(
        lambda: helper._run_archived_m1d_node_in_root(missing_root, V3_REPLAY_NODE)
    )
    assert type(control) is helper.PinnedReplayIntegrityFailure


@pytest.mark.parametrize(
    ("content", "detail"),
    (
        (b"3.14\n", "must name exactly one X.Y.Z interpreter version"),
        (b"3.14.6\n3.14.7\n", "must name exactly one X.Y.Z interpreter version"),
        (b">=3.14.6\n", "must name exactly one X.Y.Z interpreter version"),
        (b"", "must name exactly one X.Y.Z interpreter version"),
    ),
)
def test_coarse_or_ambiguous_pin_is_an_integrity_failure(
    tmp_path: Path, content: bytes, detail: str
) -> None:
    """The pin cannot be coarsened to a minor version or widened to a range."""
    helper = _load_replay_helper()
    pin = tmp_path / ".python-version"
    pin.write_bytes(content)
    error = _raised(
        lambda: helper.verify_replay_interpreter(observed=PINNED_IDENTITY, pin_path=pin)
    )
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        f"PINNED_REPLAY_INTEGRITY_FAILURE interpreter pin {pin} {detail}"
    ), str(error)


def test_missing_pin_is_an_integrity_failure(tmp_path: Path) -> None:
    helper = _load_replay_helper()
    pin = tmp_path / ".python-version"
    error = _raised(
        lambda: helper.verify_replay_interpreter(observed=PINNED_IDENTITY, pin_path=pin)
    )
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        f"PINNED_REPLAY_INTEGRITY_FAILURE cannot read interpreter pin {pin}"
    ), str(error)


def test_replay_child_interpreter_identity_is_verified(tmp_path: Path) -> None:
    """The child that recomputes the derivation must itself be the pinned one."""
    helper = _load_replay_helper()
    impostor = _executable_script(tmp_path / "python", "echo cpython-3.14.5")
    error = _raised(lambda: helper.verify_replay_child_interpreter(str(impostor)))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error) == (
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH expected cpython-3.14.6 "
        f"found cpython-3.14.5 in replay child interpreter {impostor}"
    )
    assert helper.verify_replay_child_interpreter(sys.executable) == (PINNED_IDENTITY)


# --- installed distributions against uv.lock (#53) ---------------------------------


def _installed(helper: ModuleType) -> dict[str, frozenset[str]]:
    """This environment's installed distribution set, as the guard reads it."""
    return dict(helper.observed_distribution_versions())


def _locked_version(helper: ModuleType, name: str) -> str:
    return str(helper.locked_environment().required[name])


def _dist_info(root: Path, name: str, version: str | None) -> Path:
    """Write one minimal installed-distribution record under ``root``."""
    folder = root / f"{name}-{version or 'unversioned'}.dist-info"
    folder.mkdir(parents=True)
    lines = ["Metadata-Version: 2.1", f"Name: {name}"]
    if version is not None:
        lines.append(f"Version: {version}")
    (folder / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _synthetic_lock(path: Path, body: str) -> Path:
    path.write_text("version = 1\nrevision = 3\n" + body, encoding="utf-8")
    return path


def test_the_installed_distributions_match_the_lock() -> None:
    """A `uv sync --locked` environment passes, and the check is not empty."""
    helper = _load_replay_helper()
    installed = _installed(helper)
    assert "pydantic" in installed
    assert helper.verify_replay_distributions() == len(installed)


def test_a_drifted_distribution_version_is_an_environment_mismatch() -> None:
    """A package upgraded outside `uv sync` is environment, never semantic."""
    helper = _load_replay_helper()
    drifted = _installed(helper) | {"pydantic": frozenset({"0.0.1"})}
    error = _raised(lambda: helper.verify_replay_distributions(installed=drifted))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error) == (
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH installed distributions differ from "
        "uv.lock in running interpreter: pydantic found ['0.0.1'] expected "
        f"['{_locked_version(helper, 'pydantic')}']"
    )


def test_an_unlocked_distribution_is_an_environment_mismatch() -> None:
    """Anything installed that the lock does not name is drift too."""
    helper = _load_replay_helper()
    extra = _installed(helper) | {"requests": frozenset({"2.32.0"})}
    error = _raised(lambda: helper.verify_replay_distributions(installed=extra))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error) == (
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH installed distributions differ from "
        "uv.lock in running interpreter: requests ['2.32.0'] is installed but not "
        "locked"
    )


def test_the_required_set_is_the_marker_evaluated_closure_of_the_lock() -> None:
    """The lock resolves every platform; this interpreter must install its share.

    `colorama` is locked only behind `sys_platform == 'win32'`, so it is
    required exactly on Windows, and the synced environment is exactly the
    required set.
    """
    helper = _load_replay_helper()
    environment = helper.locked_environment()
    installed = _installed(helper)
    assert "colorama" in environment.locked
    assert ("colorama" in environment.required) is (sys.platform == "win32")
    assert set(environment.required) == set(installed)
    assert set(environment.required) <= set(environment.locked)
    assert helper.verify_replay_distributions(installed=installed) == len(installed)


def test_a_missing_required_distribution_is_an_environment_mismatch() -> None:
    """A required package that is absent is the environment, not the replay."""
    helper = _load_replay_helper()
    installed = _installed(helper)
    del installed["pytest"]
    error = _raised(lambda: helper.verify_replay_distributions(installed=installed))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error) == (
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH installed distributions differ from "
        "uv.lock in running interpreter: pytest is required at "
        f"{_locked_version(helper, 'pytest')} but not installed"
    )


ROOT_PACKAGE = (
    '[[package]]\nname = "demo"\nversion = "1.0"\nsource = { editable = "." }\n'
)


def _package(name: str, version: str = "1.0", extra: str = "") -> str:
    return f'[[package]]\nname = "{name}"\nversion = "{version}"\n{extra}'


def test_a_locked_but_unrequired_distribution_is_an_environment_mismatch(
    tmp_path: Path,
) -> None:
    """A package the lock resolves but does not require here is drift here.

    Built on a synthetic lock so it holds on every platform: `extra-only` is
    locked, and nothing the project needs pulls it in.
    """
    helper = _load_replay_helper()
    lock = _synthetic_lock(
        tmp_path / "uv.lock",
        ROOT_PACKAGE
        + 'dependencies = [{ name = "a" }]\n'
        + _package("a")
        + _package("extra-only"),
    )
    installed = {"demo": {"1.0"}, "a": {"1.0"}, "extra-only": {"1.0"}}
    error = _raised(
        lambda: helper.verify_replay_distributions(
            installed=installed, lock_path=lock, authenticate=False
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error) == (
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH installed distributions differ from "
        "uv.lock in running interpreter: extra-only ['1.0'] is installed but "
        "uv.lock does not require it for this interpreter"
    )


def test_an_extra_requested_on_a_later_edge_is_still_required(tmp_path: Path) -> None:
    """`a` is reached plainly first, then as `a[x]`; the extra's `c` counts."""
    helper = _load_replay_helper()
    lock = _synthetic_lock(
        tmp_path / "uv.lock",
        ROOT_PACKAGE
        + 'dependencies = [{ name = "a" }, { name = "b" }]\n'
        + _package("a", extra='[package.optional-dependencies]\nx = [{ name = "c" }]\n')
        + _package("b", extra='dependencies = [{ name = "a", extra = ["x"] }]\n')
        + _package("c"),
    )
    environment = helper.locked_environment(lock, authenticate=False, default_groups=())
    assert environment.required == {"a": "1.0", "b": "1.0", "c": "1.0", "demo": "1.0"}


def test_a_virtual_root_is_not_itself_required(tmp_path: Path) -> None:
    """uv never installs a virtual project, so only its dependencies count."""
    helper = _load_replay_helper()
    lock = _synthetic_lock(
        tmp_path / "uv.lock",
        '[[package]]\nname = "demo"\nversion = "1.0"\nsource = { virtual = "." }\n'
        'dependencies = [{ name = "a" }]\n' + _package("a"),
    )
    environment = helper.locked_environment(lock, authenticate=False, default_groups=())
    assert environment.required == {"a": "1.0"}


def test_only_the_default_dependency_groups_are_required(tmp_path: Path) -> None:
    """A non-default group is locked but not installed by `uv sync`."""
    helper = _load_replay_helper()
    lock = _synthetic_lock(
        tmp_path / "uv.lock",
        ROOT_PACKAGE
        + "[package.dev-dependencies]\n"
        + 'dev = [{ name = "d" }]\ndocs = [{ name = "e" }]\n'
        + _package("d")
        + _package("e"),
    )
    by_default = helper.locked_environment(lock, authenticate=False)
    assert by_default.required == {"d": "1.0", "demo": "1.0"}
    every = helper.locked_environment(lock, authenticate=False, default_groups=None)
    assert every.required == {"d": "1.0", "demo": "1.0", "e": "1.0"}


@pytest.mark.parametrize(
    "marker",
    ("'dev' in dependency_groups", "'x' in extras", "python_version >"),
)
def test_an_unevaluable_marker_is_an_integrity_failure(
    tmp_path: Path, marker: str
) -> None:
    helper = _load_replay_helper()
    lock = _synthetic_lock(
        tmp_path / "uv.lock",
        ROOT_PACKAGE
        + f'dependencies = [{{ name = "a", marker = "{marker}" }}]\n'
        + _package("a"),
    )
    error = _raised(lambda: helper.locked_environment(lock, authenticate=False))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        f"PINNED_REPLAY_INTEGRITY_FAILURE cannot read lockfile {lock}: "
        f"unevaluable marker {marker!r}"
    ), str(error)


def test_a_non_list_dependency_group_is_an_integrity_failure(tmp_path: Path) -> None:
    helper = _load_replay_helper()
    lock = _synthetic_lock(
        tmp_path / "uv.lock",
        ROOT_PACKAGE + '[package.dev-dependencies]\ndev = "mypy"\n',
    )
    error = _raised(lambda: helper.locked_environment(lock, authenticate=False))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error) == (
        f"PINNED_REPLAY_INTEGRITY_FAILURE cannot read lockfile {lock}: "
        "demo dev-dependencies dev is not a list"
    )


def test_a_missing_marker_evaluator_is_an_unavailable_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _load_replay_helper()
    monkeypatch.setitem(sys.modules, "packaging.markers", None)
    error = _raised(helper.locked_environment)
    assert type(error) is helper.PinnedReplayEnvironmentArtifactUnavailable
    assert str(error).startswith(
        "PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE the marker evaluator the "
        "lock requires is unavailable"
    ), str(error)


def test_an_edited_lockfile_is_an_integrity_failure(tmp_path: Path) -> None:
    """The lock the environment is held to is itself held to its protected pin."""
    helper = _load_replay_helper()
    lock = REPO_ROOT / "uv.lock"
    edited = tmp_path / "uv.lock"
    edited.write_bytes(
        lock.read_bytes().replace(
            b'name = "iniconfig"\nversion = "', b'name = "iniconfig"\nversion = "9.'
        )
    )
    assert edited.read_bytes() != lock.read_bytes()
    error = _raised(lambda: helper.verify_replay_distributions(lock_path=edited))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        f"PINNED_REPLAY_INTEGRITY_FAILURE lockfile {edited} sha256 mismatch: "
        f"expected {helper.PROTECTED_M1D_SHA256['uv.lock']}"
    ), str(error)


def test_a_marker_fork_admits_only_this_interpreters_version(tmp_path: Path) -> None:
    """One name locked at two versions resolves to exactly one here."""
    helper = _load_replay_helper()
    lock = _synthetic_lock(
        tmp_path / "uv.lock",
        '[[package]]\nname = "demo"\nversion = "1.0"\nsource = { editable = "." }\n'
        "dependencies = [\n"
        '    { name = "forked", version = "1.0",'
        " marker = \"python_version < '3.14'\" },\n"
        '    { name = "forked", version = "2.0",'
        " marker = \"python_version >= '3.14'\" },\n"
        "]\n"
        '[[package]]\nname = "forked"\nversion = "1.0"\n'
        '[[package]]\nname = "forked"\nversion = "2.0"\n',
    )
    environment = helper.locked_environment(lock, authenticate=False)
    assert environment.required == {"demo": "1.0", "forked": "2.0"}
    wrong_fork = {"demo": {"1.0"}, "forked": {"1.0"}}
    error = _raised(
        lambda: helper.verify_replay_distributions(
            installed=wrong_fork, lock_path=lock, authenticate=False
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert "forked found ['1.0'] expected ['2.0']" in str(error)
    assert (
        helper.verify_replay_distributions(
            installed={"demo": {"1.0"}, "forked": {"2.0"}},
            lock_path=lock,
            authenticate=False,
        )
        == 2
    )


@pytest.mark.parametrize(
    ("body", "detail"),
    (
        ("", "it locks no packages"),
        ("package = []\n", "it locks no packages"),
        (
            '[[package]]\nname = "orphan"\n',
            "a locked package lacks a name or a version",
        ),
        (
            '[[package]]\nname = "a"\nversion = "1"\n',
            "expected exactly one project package, found 0",
        ),
    ),
)
def test_a_malformed_lock_is_an_integrity_failure(
    tmp_path: Path, body: str, detail: str
) -> None:
    helper = _load_replay_helper()
    lock = _synthetic_lock(tmp_path / "uv.lock", body)
    error = _raised(lambda: helper.locked_environment(lock, authenticate=False))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error) == (
        f"PINNED_REPLAY_INTEGRITY_FAILURE cannot read lockfile {lock}: {detail}"
    )


def test_distribution_drift_is_rejected_before_archive_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drift is caught before any archive is written, as interpreter drift is."""
    helper = _load_replay_helper()
    drifted = _installed(helper) | {"pydantic": frozenset({"0.0.1"})}
    monkeypatch.setattr(helper, "observed_distribution_versions", lambda: drifted)
    destination = tmp_path / "archive"
    error = _raised(lambda: helper.extract_m1d_archive(destination))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert "pydantic found ['0.0.1']" in str(error)
    assert not destination.exists()


def test_distribution_drift_is_rejected_before_generation_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The historical generation archives are guarded the same way."""
    helper = _load_replay_helper()
    drifted = _installed(helper) | {"pydantic": frozenset({"0.0.1"})}
    monkeypatch.setattr(helper, "observed_distribution_versions", lambda: drifted)
    destination = tmp_path / "v1"
    error = _raised(lambda: helper.extract_m1d_generation_archive(destination, "v1"))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert "pydantic found ['0.0.1']" in str(error)
    assert not destination.exists()


def test_distribution_drift_is_rejected_before_archived_inputs_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing archive would be integrity; the environment guard fires first."""
    helper = _load_replay_helper()
    drifted = _installed(helper) | {"pydantic": frozenset({"0.0.1"})}
    monkeypatch.setattr(helper, "observed_distribution_versions", lambda: drifted)
    error = _raised(
        lambda: helper._run_archived_m1d_node_in_root(
            tmp_path / "never-extracted", V3_REPLAY_NODE
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert "in running interpreter: pydantic found ['0.0.1']" in str(error)


def test_a_shadowing_distribution_is_caught_in_the_parent_and_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second installed copy at another version, seen by the real programs.

    Exercises the parent's own observer and the real child program, with the
    child's environment passed through, rather than an impostor's report.
    """
    helper = _load_replay_helper()
    shadow = _dist_info(tmp_path / "shadow", "pydantic", "0.0.1")
    locked = _locked_version(helper, "pydantic")
    expected = f"pydantic found ['0.0.1', '{locked}'] expected ['{locked}']"
    child = helper.verify_replay_child_distributions
    error = _raised(
        lambda: child(
            sys.executable, environment={**os.environ, "PYTHONPATH": str(shadow)}
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert f"in replay child interpreter {sys.executable}: {expected}" in str(error)
    monkeypatch.syspath_prepend(str(shadow))
    error = _raised(helper.verify_replay_distributions)
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert f"in running interpreter: {expected}" in str(error)


def test_an_unversioned_distribution_is_classified_alike_in_parent_and_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metadata with no version is environment drift wherever it is observed."""
    helper = _load_replay_helper()
    shadow = _dist_info(tmp_path / "shadow", "pydantic", None)
    child = helper.verify_replay_child_distributions
    error = _raised(
        lambda: child(
            sys.executable, environment={**os.environ, "PYTHONPATH": str(shadow)}
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert "pydantic is installed with no version" in str(error)
    monkeypatch.syspath_prepend(str(shadow))
    error = _raised(helper.verify_replay_distributions)
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert "pydantic is installed with no version" in str(error)


def test_the_replay_child_distributions_are_verified(tmp_path: Path) -> None:
    """The child that recomputes the derivation is held to the lock as well."""
    helper = _load_replay_helper()
    locked = {
        name: sorted(versions)
        for name, versions in helper.observed_distribution_versions().items()
    }
    locked["pydantic"] = ["0.0.1"]
    impostor = _executable_script(
        tmp_path / "python", f"echo '{json.dumps(locked, sort_keys=True)}'"
    )
    error = _raised(lambda: helper.verify_replay_child_distributions(str(impostor)))
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error).startswith(
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH installed distributions differ from "
        f"uv.lock in replay child interpreter {impostor}: pydantic found ['0.0.1']"
    ), str(error)
    # Control: the real child interpreter is the synced environment.
    assert helper.verify_replay_child_distributions(sys.executable) == len(
        _installed(helper)
    )


def test_a_drifted_replay_child_is_refused_before_it_replays(tmp_path: Path) -> None:
    """The replay harness itself asks the child, after its identity, not later.

    The impostor answers the identity query with the pinned identity and the
    distribution query with one drifted package. Were the harness not to ask,
    it would go on to run the archived node, and the drift would surface as a
    semantic mismatch or an import failure instead of as the environment.
    """
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "archive")
    reported = {
        name: sorted(versions)
        for name, versions in helper.observed_distribution_versions().items()
    }
    reported["pydantic"] = ["0.0.1"]
    impostor = _executable_script(
        tmp_path / "python",
        'case "$2" in\n'
        f"  *metadata*) echo '{json.dumps(reported, sort_keys=True)}' ;;\n"
        f"  *) echo {PINNED_IDENTITY} ;;\n"
        "esac",
    )
    error = _raised(
        lambda: helper.run_replay_child(
            archive,
            (V3_REPLAY_NODE,),
            commit=helper.PINNED_M1D_COMMIT,
            expected_pins=helper.PROTECTED_M1D_ARCHIVE_SHA256,
            label="archived",
            executable=str(impostor),
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error).startswith(
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH installed distributions differ from "
        f"uv.lock in replay child interpreter {impostor}: pydantic found ['0.0.1']"
    ), str(error)


def test_a_distribution_visible_only_to_the_replay_child_is_caught(
    tmp_path: Path,
) -> None:
    """The child is asked in its own environment, where the archive is on path.

    A shadow copy placed inside the extracted archive is invisible to this
    process and visible to the child, so only a child check run with the
    child's environment and working directory can see it.
    """
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "archive")
    _dist_info(archive / "src", "pydantic", "0.0.1")
    assert helper.verify_replay_distributions() == len(_installed(helper))
    error = _raised(
        lambda: helper.run_replay_child(
            archive,
            (V3_REPLAY_NODE,),
            commit=helper.PINNED_M1D_COMMIT,
            expected_pins=helper.PROTECTED_M1D_ARCHIVE_SHA256,
            label="archived",
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    locked = _locked_version(helper, "pydantic")
    assert (
        f"in replay child interpreter {sys.executable}: pydantic found "
        f"['0.0.1', '{locked}'] expected ['{locked}']"
    ) in str(error)


def test_the_child_identity_is_checked_before_its_distributions(
    tmp_path: Path,
) -> None:
    """Wrong interpreter and drifted packages together: the identity is named."""
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "archive")
    impostor = _executable_script(
        tmp_path / "python",
        'case "$2" in\n'
        '  *metadata*) echo \'{"pydantic": ["0.0.1"]}\' ;;\n'
        "  *) echo cpython-3.14.5 ;;\n"
        "esac",
    )
    error = _raised(
        lambda: helper.run_replay_child(
            archive,
            (V3_REPLAY_NODE,),
            commit=helper.PINNED_M1D_COMMIT,
            expected_pins=helper.PROTECTED_M1D_ARCHIVE_SHA256,
            label="archived",
            executable=str(impostor),
        )
    )
    assert type(error) is helper.PinnedReplayEnvironmentMismatch
    assert str(error) == (
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH expected cpython-3.14.6 found "
        f"cpython-3.14.5 in replay child interpreter {impostor}"
    )


def test_a_malformed_child_distribution_report_is_an_unavailable_artifact(
    tmp_path: Path,
) -> None:
    helper = _load_replay_helper()
    impostor = _executable_script(tmp_path / "python", "echo not-json")
    error = _raised(lambda: helper.verify_replay_child_distributions(str(impostor)))
    assert type(error) is helper.PinnedReplayEnvironmentArtifactUnavailable
    assert str(error).startswith(
        "PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE replay child interpreter "
        f"{impostor} could not report its distributions (exit 0)"
    ), str(error)


def test_an_unreadable_lock_is_an_integrity_failure(tmp_path: Path) -> None:
    helper = _load_replay_helper()
    broken = tmp_path / "uv.lock"
    broken.write_text("[[package]\nname = 1\n", encoding="utf-8")
    error = _raised(lambda: helper.locked_environment(broken, authenticate=False))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        f"PINNED_REPLAY_INTEGRITY_FAILURE cannot read lockfile {broken}"
    ), str(error)


def test_unavailable_pinned_interpreter_is_its_own_failure_class(
    tmp_path: Path,
) -> None:
    """A missing, non-executable, or dead interpreter is not a replay failure."""
    helper = _load_replay_helper()
    missing = tmp_path / "missing-python"
    not_executable = tmp_path / "not-executable-python"
    not_executable.write_text("#!/bin/sh\necho cpython-3.14.6\n", encoding="utf-8")
    not_executable.chmod(0o644)
    dead = _executable_script(tmp_path / "dead-python", "exit 127")
    for executable, detail in (
        ("", "executable is unavailable"),
        (str(missing), "executable is unavailable"),
        (str(not_executable), "executable is unavailable"),
        (str(dead), "could not start"),
    ):
        error = _raised(partial(helper.verify_replay_child_interpreter, executable))
        assert type(error) is helper.PinnedReplayEnvironmentArtifactUnavailable
        assert str(error).startswith(
            "PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE pinned interpreter "
            f"cpython-3.14.6 {detail}"
        ), str(error)


def test_unavailable_historical_commit_is_an_artifact_failure() -> None:
    """A checkout without the historical objects cannot replay, and says so."""
    helper = _load_replay_helper()
    absent = "0123456789abcdef0123456789abcdef01234567"
    error = _raised(lambda: helper._archive_bytes(absent))
    assert type(error) is helper.PinnedReplayEnvironmentArtifactUnavailable
    assert str(error).startswith(
        "PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE historical Git commit "
        f"{absent} is unavailable"
    ), str(error)


def test_semantic_mismatch_is_reported_when_environment_matches_but_bytes_differ(
    tmp_path: Path,
) -> None:
    """The historical cpython-3.14.5 bytes, replayed under the pin, still fail.

    The archive is authenticated against the preserved v3 inventory and the
    interpreter matches the pin, so the only remaining explanation is that the
    recomputed artifact differs. That must surface as a semantic replay
    mismatch, not as an environment or integrity failure.
    """
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "historical")
    error = _raised(
        lambda: helper.run_replay_child(
            archive,
            (V3_REPLAY_NODE,),
            commit=helper.PINNED_M1D_COMMIT,
            expected_pins=helper.PROTECTED_M1D_ARCHIVE_SHA256,
            label="archived",
        )
    )
    assert type(error) is helper.PinnedReplaySemanticMismatch
    assert str(error).startswith(
        "PINNED_REPLAY_SEMANTIC_MISMATCH environment cpython-3.14.6 matched and "
        "archived inputs authenticated, but replay failed for "
        f"{V3_REPLAY_NODE}"
    ), str(error)[:400]
    assert "normalization replay mismatch" in str(error)


def test_protected_byte_drift_is_an_integrity_failure(tmp_path: Path) -> None:
    """Tampered protected bytes stop before the child runs, as integrity."""
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "archive")
    target = archive / "tests/fixtures/m1d/v3/expected-outcome-result.json"
    target.write_bytes(target.read_bytes() + b" ")
    error = _raised(
        lambda: helper.run_replay_child(
            archive,
            (V3_REPLAY_NODE,),
            commit=helper.PINNED_M1D_COMMIT,
            expected_pins=helper.PROTECTED_M1D_ARCHIVE_SHA256,
            label="archived",
        )
    )
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        "PINNED_REPLAY_INTEGRITY_FAILURE protected M1d sha256 mismatch for "
        "tests/fixtures/m1d/v3/expected-outcome-result.json"
    ), str(error)


def test_missing_archived_node_is_an_integrity_failure_not_semantic(
    tmp_path: Path,
) -> None:
    """A node the authenticated archive does not define is a harness defect."""
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "archive")
    node = "tests/integration/test_m1d_adversarial_matrix.py::does_not_exist"
    error = _raised(
        lambda: helper.run_replay_child(
            archive,
            (node,),
            commit=helper.PINNED_M1D_COMMIT,
            expected_pins=helper.PROTECTED_M1D_ARCHIVE_SHA256,
            label="archived",
        )
    )
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        "PINNED_REPLAY_INTEGRITY_FAILURE archived replay could not execute "
        f"{node} (pytest exit 4)"
    ), str(error)[:400]


def test_failure_classes_are_four_distinct_siblings() -> None:
    """No class can stand in for another, and each carries its own code."""
    helper = _load_replay_helper()
    classes = _classes(helper)
    assert len(set(classes)) == 4
    for cls in classes:
        assert issubclass(cls, helper.PinnedM1dReplayError)
        assert cls.__bases__ == (helper.PinnedM1dReplayError,)
        for other in classes:
            if other is not cls:
                assert not issubclass(cls, other)
    assert [cls.code for cls in classes] == [
        "PINNED_REPLAY_ENVIRONMENT_MISMATCH",
        "PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE",
        "PINNED_REPLAY_SEMANTIC_MISMATCH",
        "PINNED_REPLAY_INTEGRITY_FAILURE",
    ]


def test_pinned_replay_lane_has_no_skip_path() -> None:
    """A failed guard must fail the run; the lane may never skip or xfail."""
    skip_names = {"skip", "skipif", "xfail", "importorskip"}
    for relative in ("tests/_pinned_m1d.py", "tests/conftest.py"):
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                # Any owner, so an aliased or dynamically imported pytest
                # cannot hide a skip.
                assert node.attr not in skip_names, (
                    f"{relative}:{node.lineno} uses .{node.attr}"
                )
                owner = node.value
                assert not (
                    node.attr == "exit"
                    and isinstance(owner, ast.Name)
                    and owner.id == "pytest"
                ), f"{relative}:{node.lineno} uses pytest.exit"
            if isinstance(node, ast.Name):
                assert node.id not in skip_names, (
                    f"{relative}:{node.lineno} references {node.id}"
                )
    # The replay helper classifies failures by raising; it never talks to
    # pytest at all, so it cannot convert a failure into an outcome.
    helper = ast.parse((REPO_ROOT / "tests/_pinned_m1d.py").read_text("utf-8"))
    for node in ast.walk(helper):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] != "pytest" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "pytest"


CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CANONICAL_GATE = (
    "uv run pytest",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run mypy src tests",
    "uv build",
    "git diff --check",
)


def _run_steps(workflow: str) -> list[str]:
    """Return every single-line ``run:`` command in the workflow, in order."""
    return [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s+run: (?!\|)(.+)$", workflow)
    ]


def test_ci_consumes_the_same_interpreter_pin_used_locally() -> None:
    """CI reads .python-version, never a duplicated version, and checks it."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    pin = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert pin not in workflow, "CI must not duplicate the interpreter pin"
    assert "python-version:" not in workflow
    assert "python-version-file" not in workflow
    assert "UV_PYTHON:" not in workflow
    assert re.search(r"(?m)^\s+if ! uv python install; then$", workflow)
    assert "UV_PYTHON_PREFERENCE: only-managed" in workflow
    assert "import _pinned_m1d as replay" in workflow
    assert "replay.verify_replay_interpreter()" in workflow
    assert "PINNED_REPLAY_ENVIRONMENT_ARTIFACT_UNAVAILABLE" in workflow


def test_ci_runs_the_canonical_gate_on_every_pull_request_and_main() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^on:\n  pull_request:\n  push:\n    branches: \[main\]$", workflow
    )
    assert re.search(r"(?m)^\s+timeout-minutes: [0-9]+$", workflow)
    assert "fetch-depth: 0" in workflow
    assert 'UV_LOCKED: "1"' in workflow
    steps = _run_steps(workflow)
    assert "uv sync --locked" in steps
    positions = [steps.index(command) for command in CANONICAL_GATE]
    assert positions == sorted(positions)
    assert steps.index("uv sync --locked") < positions[0]


def test_ci_observes_repository_truth_and_never_repairs_it() -> None:
    """Read-only token, no secrets, no fixture regeneration, no write-back."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"(?m)^permissions:\n  contents: read$", workflow)
    assert "persist-credentials: false" in workflow
    for forbidden in (
        "secrets.",
        "write-all",
        ": write",
        "pull_request_target",
        "git commit",
        "git push",
        "git add",
        "write_fixture",
        "--upgrade",
        "uv lock",
        "--no-locked",
    ):
        assert forbidden not in workflow, forbidden
    assert 'test -z "$(git status --porcelain --untracked-files=no)"' in workflow
