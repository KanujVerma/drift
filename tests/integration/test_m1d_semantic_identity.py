"""M1d evidence identity survives unrelated edits (issue 63, stage 1).

Before issue 63 every M1d derivation, result and retained policy bound the
whole installed source inventory, so a comment anywhere in ``src/drift`` moved
every M1d hash and, through them, every M2 bundle, admission, result and trace
hash (the issue 46 reproduction). Stage 1 binds the M1d evidence identity to the
versioned ``m1d-evidence-v1`` semantic attestation instead and keeps the whole
inventory as build provenance only.

Each scenario runs in a fresh interpreter over its own copy of the installed
``drift`` package, because the attestation is computed once per process: an
in-process edit could never show that the identity ignores it. The unrelated
edit is a comment in ``drift/evaluator/engine.py``; the declared edit is the
same comment in ``drift/markets/normalization.py``, which the closure declares.
Only source-basis evidence is exercised here. Split-normalized evidence
composes M1c history, whose identities stage 2 moved onto the M1c semantic
attestations; its stability is proved in
``tests/integration/test_m1c_semantic_identity.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_alpaca_exploratory_adapter import run_pinned_intake  # noqa: E402

from drift.adapters import alpaca_exploratory as bridge  # noqa: E402
from drift.domain.economic_common import economic_implementation_hash  # noqa: E402
from drift.domain.observation_query import m1d_implementation_hash  # noqa: E402
from drift.domain.sessions import ScheduleGenerationPolicyV1  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
UNRELATED_MODULE = "evaluator/engine.py"
DECLARED_MODULE = "markets/normalization.py"
COMMENT_EDIT = b"\n# issue 63: a comment-only edit\n"
MOVED_BY_IDENTITY = (
    "bundle_hash",
    "admission_hash",
    "result_hash",
    "trace_hash",
    "m1d_implementation_hash",
)

_PRELUDE = """
import json
import sys
from pathlib import Path

import drift

root = Path(sys.argv[1]).resolve()
if not Path(drift.__file__).resolve().is_relative_to(root):
    raise SystemExit(f"imported Drift outside the source copy: {drift.__file__}")

from drift.domain.economic_common import economic_implementation_hash
from drift.domain.observation_query import m1d_implementation_hash
from drift.serialization.canonical import canonical_json
"""

_BUNDLE_PROGRAM = (
    _PRELUDE
    + """
import test_evaluator_engine as engine_tests

engine = engine_tests._engine()
artifacts = engine_tests._run(engine)
print(json.dumps({
    "source_inventory_hash": economic_implementation_hash(),
    "m1d_implementation_hash": m1d_implementation_hash(),
    "bundle_hash": engine.bundle.bundle_hash,
    "admission_hash": engine.admission.admission_hash,
    "result_hash": artifacts.result.result_hash,
    "trace_hash": artifacts.trace.trace_hash,
}))
"""
)

_MINT_RESULT_PROGRAM = (
    _PRELUDE
    + """
from observation_test_support import NormalizationHarness

harness = NormalizationHarness()
result = harness.normalize(harness.normalization_query("source_basis"))
if result.classification != "materialized":
    raise SystemExit(f"retained result did not materialize: {result.classification}")
Path(sys.argv[2]).write_bytes(canonical_json(result))
print(json.dumps({"derivation_hash": result.derivation_hash}))
"""
)

_CHECK_RESULT_PROGRAM = (
    _PRELUDE
    + """
from observation_test_support import NormalizationHarness

from drift.domain.normalization import NormalizationResultV1

retained = Path(sys.argv[2]).read_bytes()
try:
    NormalizationResultV1.model_validate_json(retained)
except ValueError as error:
    print(json.dumps({"valid": False, "error": str(error)}))
    raise SystemExit(0)
harness = NormalizationHarness()
rederived = harness.normalize(harness.normalization_query("source_basis"))
print(json.dumps({
    "valid": True,
    "rederived_identical": canonical_json(rederived) == retained,
}))
"""
)

_MINT_POLICY_PROGRAM = (
    _PRELUDE
    + """
from datetime import date

from session_test_support import generation_case

_context, _query, policy = generation_case(local_date=date(2026, 1, 5))
Path(sys.argv[2]).write_bytes(canonical_json(policy))
print(json.dumps({"implementation_hash": policy.implementation_hash}))
"""
)

_CHECK_POLICY_PROGRAM = (
    _PRELUDE
    + """
from datetime import date

from session_test_support import generation_case

from drift.domain.sessions import ScheduleGenerationPolicyV1
from drift.markets.session_generation import (
    generate_schedule,
    validate_schedule_generation_policy,
)

context, query, _policy = generation_case(local_date=date(2026, 1, 5))
retained = ScheduleGenerationPolicyV1.model_validate_json(
    Path(sys.argv[2]).read_bytes()
)
try:
    validate_schedule_generation_policy(retained, context)
except ValueError as error:
    print(json.dumps({"valid": False, "error": str(error)}))
    raise SystemExit(0)
print(json.dumps({
    "valid": True,
    "classification": generate_schedule(query, context, retained).classification,
}))
"""
)

_ALPACA_PROGRAM = (
    _PRELUDE
    + """
from test_alpaca_exploratory_adapter import run_pinned_intake

intake = run_pinned_intake(Path(sys.argv[2]))
print(json.dumps({
    "bundle_hash": intake.bundle.bundle_hash,
    "admission_hash": intake.admission.admission_hash,
}))
"""
)


def _source_copy(base: Path, name: str, edited: str | None) -> Path:
    """Copy the installed package (and its lock) and apply one comment edit."""
    root = base / name
    shutil.copytree(
        REPO_ROOT / "src" / "drift",
        root / "src" / "drift",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(REPO_ROOT / "uv.lock", root / "uv.lock")
    if edited is not None:
        target = root / "src" / "drift" / edited
        target.write_bytes(target.read_bytes() + COMMENT_EDIT)
    return root


def _run(root: Path, program: str, *arguments: str) -> dict[str, Any]:
    """Run one program in a fresh interpreter importing Drift from ``root``."""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (
                str(root / "src"),
                str(REPO_ROOT / "tests" / "unit"),
                str(REPO_ROOT / "tests"),
            )
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        [sys.executable, "-c", program, str(root), *arguments],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    document = json.loads(completed.stdout.strip().splitlines()[-1])
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="module")
def copies(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("m1d-semantic-identity")
    return {
        "pristine": _source_copy(base, "pristine", None),
        "unrelated": _source_copy(base, "unrelated", UNRELATED_MODULE),
        "declared": _source_copy(base, "declared", DECLARED_MODULE),
    }


@pytest.fixture(scope="module")
def bundles(copies: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: _run(root, _BUNDLE_PROGRAM) for name, root in copies.items()}


def test_the_pristine_copy_is_the_installed_package(
    bundles: dict[str, dict[str, Any]],
) -> None:
    """The copies are faithful, so their identities describe this tree."""
    pristine = bundles["pristine"]
    assert pristine["source_inventory_hash"] == economic_implementation_hash()
    assert pristine["m1d_implementation_hash"] == m1d_implementation_hash()


def test_an_unrelated_comment_edit_does_not_move_the_realized_lane_bundle(
    bundles: dict[str, dict[str, Any]],
) -> None:
    """The issue 46 reproduction: identical inputs, identical hashes."""
    pristine, unrelated = bundles["pristine"], bundles["unrelated"]
    # The edit is real: the whole-tree build provenance sees it.
    assert unrelated["source_inventory_hash"] != pristine["source_inventory_hash"]
    for key in MOVED_BY_IDENTITY:
        assert unrelated[key] == pristine[key], key


def test_the_same_edit_in_a_declared_m1d_module_moves_identity_and_bundle(
    bundles: dict[str, dict[str, Any]],
) -> None:
    """The identity is not blind: the closure it declares still moves it."""
    pristine, declared = bundles["pristine"], bundles["declared"]
    assert declared["source_inventory_hash"] != pristine["source_inventory_hash"]
    for key in MOVED_BY_IDENTITY:
        assert declared[key] != pristine[key], key


def test_a_retained_m1d_normalization_result_revalidates_after_an_unrelated_edit(
    copies: dict[str, Path], tmp_path: Path
) -> None:
    """Retained evidence re-validates and re-derives to identical bytes."""
    retained = tmp_path / "retained-result.json"
    _run(copies["pristine"], _MINT_RESULT_PROGRAM, str(retained))

    unrelated = _run(copies["unrelated"], _CHECK_RESULT_PROGRAM, str(retained))
    assert unrelated == {"valid": True, "rederived_identical": True}

    declared = _run(copies["declared"], _CHECK_RESULT_PROGRAM, str(retained))
    assert declared["valid"] is False
    assert "implementation mismatch" in declared["error"]


def test_a_retained_schedule_generation_policy_revalidates_after_an_unrelated_edit(
    copies: dict[str, Path], tmp_path: Path
) -> None:
    """A retained reconstruction policy no longer goes stale on any commit."""
    retained = tmp_path / "retained-policy.json"
    _run(copies["pristine"], _MINT_POLICY_PROGRAM, str(retained))

    unrelated = _run(copies["unrelated"], _CHECK_POLICY_PROGRAM, str(retained))
    assert unrelated == {"valid": True, "classification": "generated"}

    declared = _run(copies["declared"], _CHECK_POLICY_PROGRAM, str(retained))
    assert declared["valid"] is False
    assert "schedule implementation identity mismatch" in declared["error"]


def test_the_alpaca_bridge_bundle_is_stable_across_an_unrelated_edit(
    copies: dict[str, Path], tmp_path: Path
) -> None:
    runs: dict[str, dict[str, Any]] = {}
    for name, root in copies.items():
        private = tmp_path / name
        private.mkdir()
        runs[name] = _run(root, _ALPACA_PROGRAM, str(private))
    assert runs["unrelated"] == runs["pristine"]
    assert runs["declared"]["bundle_hash"] != runs["pristine"]["bundle_hash"]


def test_collector_provenance_is_the_source_inventory_not_the_m1d_evidence_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which code collected is build provenance; which code derived is not.

    The collector is outside the M1d evidence closure, so the evidence
    identity cannot attest its source. The schedule policy the bridge authors
    is executed by M1d session generation, so it carries the evidence identity.
    """
    from drift.domain.observation_query import drift_source_inventory_hash

    executions: list[Any] = []
    screen = bridge._screen_acquisition_payloads

    def recording_screen(*arguments: Any) -> Any:
        executions.append(arguments[1])
        return screen(*arguments)

    monkeypatch.setattr(bridge, "_screen_acquisition_payloads", recording_screen)
    intake = run_pinned_intake(tmp_path / "private")

    provenance = drift_source_inventory_hash()
    assert provenance == economic_implementation_hash()
    assert provenance != m1d_implementation_hash()
    (execution,) = executions
    assert execution.collector_source_hash == provenance
    assert execution.executable_evidence_hashes == (provenance,)
    assert intake.acquisition.receipt.collector_source_hash == provenance

    policies = []
    for artifact in intake.context.supporting_artifacts.values():
        try:
            document = json.loads(artifact.data)
        except UnicodeDecodeError, ValueError:
            continue
        if (
            isinstance(document, dict)
            and document.get("algorithm") == "explicit_local_rows_to_utc_v1"
        ):
            policies.append(
                ScheduleGenerationPolicyV1.model_validate_json(artifact.data)
            )
    assert policies
    identity = m1d_implementation_hash()
    assert all(item.implementation_hash == identity for item in policies)
