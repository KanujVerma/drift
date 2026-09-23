"""The cpython-3.14.6 M1d replay baseline supersedes 3.14.5 and launders nothing.

Issue #48 mints a new pinned replay baseline under the exact interpreter the
repository now pins. These tests hold the minted baseline to the architecture
ruling on issue #47:

* the historical cpython-3.14.5 baseline is preserved byte-for-byte;
* the supersession record names the prior and new baseline identity, the old
  and new interpreter identity, the reason, the source commit, the lockfile
  identity, the semantic implementation identity and the verification result;
* the launder check: each new artifact differs from its historical
  counterpart only in ``derivation.python_identity`` and the digests derived
  from it. Any other difference fails with a named ``LAUNDER_CHECK_`` code.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from drift.serialization.canonical import canonical_json, content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORD_PATH = (
    REPO_ROOT / "tests/fixtures/m1d-replay-baselines/cpython-3.14.6/supersession.json"
)
OLD_IDENTITY = "cpython-3.14.5"
NEW_IDENTITY = "cpython-3.14.6"
SOURCE_COMMITS = {
    "v1": "256154e40121d28cec6a65ebcde223c12563752d",
    "v2": "a909148a941081d8d05c5090794346c5ce54db8c",
    "v3": "af75cce0f763de025f8ae3516577a9d0a1acead9",
}
RESULT_NAMES = ("expected-decision-result.json", "expected-outcome-result.json")
SUPPORT_PATH = "tests/integration/m1d_fixture_support.py"
IDENTITY_LEAF = "derivation.python_identity"
DERIVED_RESULT_LEAVES = frozenset(
    {
        "derivation_hash",
        "view.derivation_hash",
        "reference.derivation_hash",
        "reference.view_hash",
    }
)
EXPECTED_DIFFERING_RESULT_LEAVES = (
    "derivation.python_identity",
    "derivation_hash",
    "reference.derivation_hash",
    "reference.view_hash",
    "view.derivation_hash",
)


class LaunderCheckError(AssertionError):
    """The new baseline differs from the historical one beyond the identity."""


def _load_replay_helper() -> ModuleType:
    helper_path = REPO_ROOT / "tests" / "_pinned_m1d.py"
    spec = importlib.util.spec_from_file_location(
        "_m1d_baseline_pinned_m1d", helper_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _raised(call: Callable[[], object]) -> BaseException:
    try:
        call()
    except BaseException as error:  # skip and exit outcomes must be caught too
        return error
    pytest.fail("expected a failure, but the call returned")


def _git_bytes(commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return completed.stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record() -> dict[str, Any]:
    document = json.loads(RECORD_PATH.read_bytes())
    assert isinstance(document, dict)
    return document


def _leaves(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        found: dict[str, object] = {}
        for key, item in value.items():
            found.update(_leaves(item, f"{prefix}.{key}" if prefix else key))
        return found
    if isinstance(value, list):
        found = {}
        for index, item in enumerate(value):
            found.update(_leaves(item, f"{prefix}[{index}]"))
        return found
    return {prefix: value}


def _rehash_result(document: dict[str, Any]) -> dict[str, Any]:
    """Recompute every digest derived from the derivation, as the code does."""
    derivation_hash = content_hash(document["derivation"])
    document["derivation_hash"] = derivation_hash
    document["view"]["derivation_hash"] = derivation_hash
    document["reference"]["derivation_hash"] = derivation_hash
    document["reference"]["view_hash"] = content_hash(document["view"])
    return document


def launder_check_result(
    historical: bytes, current: bytes, *, old_identity: str, new_identity: str
) -> tuple[str, ...]:
    """Prove ``current`` differs from ``historical`` only in the identity.

    Returns the sorted differing leaves, which must be the identity leaf plus
    digests that are provably derived from the derivation that carries it.
    """
    old = json.loads(historical)
    new = json.loads(current)
    for label, raw, parsed in (
        ("historical", historical, old),
        ("current", current, new),
    ):
        if canonical_json(parsed) != raw:
            raise LaunderCheckError(
                f"LAUNDER_CHECK_NONCANONICAL {label} result bytes are not canonical"
            )
    old_leaves, new_leaves = _leaves(old), _leaves(new)
    if old_leaves.keys() != new_leaves.keys():
        raise LaunderCheckError(
            "LAUNDER_CHECK_STRUCTURE leaf paths differ: "
            f"{sorted(old_leaves.keys() ^ new_leaves.keys())}"
        )
    differing = tuple(
        sorted(path for path in old_leaves if old_leaves[path] != new_leaves[path])
    )
    extra = [
        path
        for path in differing
        if path != IDENTITY_LEAF and path not in DERIVED_RESULT_LEAVES
    ]
    if extra:
        raise LaunderCheckError(
            "LAUNDER_CHECK_NON_IDENTITY_FIELD "
            + "; ".join(
                f"{path}: {old_leaves[path]!r} -> {new_leaves[path]!r}"
                for path in extra
            )
        )
    if (
        old_leaves.get(IDENTITY_LEAF) != old_identity
        or new_leaves.get(IDENTITY_LEAF) != new_identity
    ):
        raise LaunderCheckError(
            f"LAUNDER_CHECK_IDENTITY expected {old_identity} -> {new_identity}, "
            f"found {old_leaves.get(IDENTITY_LEAF)!r} -> "
            f"{new_leaves.get(IDENTITY_LEAF)!r}"
        )
    for label, parsed in (("historical", old), ("current", new)):
        derivation_hash = content_hash(parsed["derivation"])
        if (
            parsed["derivation_hash"] != derivation_hash
            or parsed["view"]["derivation_hash"] != derivation_hash
            or parsed["reference"]["derivation_hash"] != derivation_hash
            or parsed["reference"]["view_hash"] != content_hash(parsed["view"])
        ):
            raise LaunderCheckError(
                f"LAUNDER_CHECK_DIGEST_CHAIN {label} derived digests are not the "
                "digests of their preimages"
            )
    restored = copy.deepcopy(new)
    restored["derivation"]["python_identity"] = old_identity
    if canonical_json(_rehash_result(restored)) != historical:
        raise LaunderCheckError(
            f"LAUNDER_CHECK_SUBSTITUTION restoring {old_identity} does not "
            "reproduce the historical bytes"
        )
    return differing


def launder_check_hash_index(
    historical: bytes, current: bytes, *, results: Mapping[str, tuple[bytes, bytes]]
) -> tuple[str, ...]:
    """Prove the index differs only in the digests of the re-minted results."""
    old = json.loads(historical)
    new = json.loads(current)
    for label, raw, parsed in (
        ("historical", historical, old),
        ("current", current, new),
    ):
        if canonical_json(parsed) != raw:
            raise LaunderCheckError(
                f"LAUNDER_CHECK_NONCANONICAL {label} hash index is not canonical"
            )
    old_leaves, new_leaves = _leaves(old), _leaves(new)
    if old_leaves.keys() != new_leaves.keys():
        raise LaunderCheckError("LAUNDER_CHECK_STRUCTURE hash index leaf paths differ")
    allowed: dict[str, tuple[str, str]] = {}
    for position, entry in enumerate(old["entries"]):
        if entry["path"] in results:
            historical_bytes, current_bytes = results[entry["path"]]
            allowed[f"entries[{position}].sha256"] = (
                _sha256(historical_bytes),
                _sha256(current_bytes),
            )
    if len(allowed) != len(results):
        raise LaunderCheckError("LAUNDER_CHECK_STRUCTURE hash index omits a result")
    differing = tuple(
        sorted(path for path in old_leaves if old_leaves[path] != new_leaves[path])
    )
    extra = [path for path in differing if path not in allowed]
    if extra:
        raise LaunderCheckError(
            "LAUNDER_CHECK_NON_IDENTITY_FIELD "
            + "; ".join(
                f"{path}: {old_leaves[path]!r} -> {new_leaves[path]!r}"
                for path in extra
            )
        )
    for path, (old_digest, new_digest) in allowed.items():
        if old_leaves[path] != old_digest or new_leaves[path] != new_digest:
            raise LaunderCheckError(
                f"LAUNDER_CHECK_DIGEST_CHAIN {path} is not the digest of its result"
            )
    restored = copy.deepcopy(new)
    for position, entry in enumerate(restored["entries"]):
        key = f"entries[{position}].sha256"
        if key in allowed:
            entry["sha256"] = allowed[key][0]
    if canonical_json(restored) != historical:
        raise LaunderCheckError(
            "LAUNDER_CHECK_SUBSTITUTION restoring the historical result digests "
            "does not reproduce the historical hash index"
        )
    return differing


def _generation_bytes(generation: str) -> dict[str, tuple[bytes, bytes]]:
    """Return historical and new bytes for each re-minted fixture file."""
    record = _record()
    superseded = record["generations"][generation]["superseded_paths"]
    found: dict[str, tuple[bytes, bytes]] = {}
    for name in (*RESULT_NAMES, "hash-index.json"):
        path = f"tests/fixtures/m1d/{generation}/{name}"
        historical = (REPO_ROOT / path).read_bytes()
        current = (REPO_ROOT / superseded[path]["baseline_path"]).read_bytes()
        found[name] = (historical, current)
    return found


@pytest.mark.parametrize("generation", ("v1", "v2", "v3"))
def test_new_baseline_differs_only_in_python_identity_and_its_digests(
    generation: str,
) -> None:
    """The launder check, for every re-minted generation and every file."""
    record = _record()
    assert record["supersedes"]["python_identity"] == OLD_IDENTITY
    assert record["baseline"]["python_identity"] == NEW_IDENTITY
    files = _generation_bytes(generation)
    for name in RESULT_NAMES:
        historical, current = files[name]
        differing = launder_check_result(
            historical, current, old_identity=OLD_IDENTITY, new_identity=NEW_IDENTITY
        )
        assert differing == EXPECTED_DIFFERING_RESULT_LEAVES, (name, differing)
    index_historical, index_current = files["hash-index.json"]
    index_differing = launder_check_hash_index(
        index_historical,
        index_current,
        results={name: files[name] for name in RESULT_NAMES},
    )
    positions = {
        entry["path"]: position
        for position, entry in enumerate(json.loads(index_historical)["entries"])
    }
    assert index_differing == tuple(
        sorted(f"entries[{positions[name]}].sha256" for name in RESULT_NAMES)
    )

    # The archived loader pins the index digest as one literal. The new
    # baseline changes exactly that literal and nothing else in the module.
    superseded = record["generations"][generation]["superseded_paths"]
    historical_support = _git_bytes(SOURCE_COMMITS[generation], SUPPORT_PATH)
    old_literal = _sha256(index_historical).encode()
    new_literal = _sha256(index_current).encode()
    assert historical_support.count(old_literal) == 1
    assert new_literal not in historical_support
    reminted_support = historical_support.replace(old_literal, new_literal)
    assert (
        _sha256(historical_support) == (superseded[SUPPORT_PATH]["historical_sha256"])
    )
    assert _sha256(reminted_support) == superseded[SUPPORT_PATH]["current_sha256"]


def test_launder_check_rejects_a_changed_non_identity_field() -> None:
    """A laundered semantic change, even with consistent digests, is caught."""
    historical, current = _generation_bytes("v3")["expected-decision-result.json"]
    parsed = json.loads(current)
    field = parsed["derivation"]["price_factor"]
    original = field["numerator"]
    field["numerator"] = str(int(original) + 1)
    injected = canonical_json(_rehash_result(parsed))
    with pytest.raises(
        LaunderCheckError,
        match=(
            r"^LAUNDER_CHECK_NON_IDENTITY_FIELD derivation\.price_factor\.numerator: "
            + re.escape(f"{original!r} -> {str(int(original) + 1)!r}")
            + "$"
        ),
    ):
        launder_check_result(
            historical, injected, old_identity=OLD_IDENTITY, new_identity=NEW_IDENTITY
        )


def test_launder_check_rejects_an_underived_digest_and_a_wrong_identity() -> None:
    historical, current = _generation_bytes("v3")["expected-outcome-result.json"]
    forged = json.loads(current)
    forged["reference"]["view_hash"] = "f" * 64
    with pytest.raises(
        LaunderCheckError, match=r"^LAUNDER_CHECK_DIGEST_CHAIN current derived"
    ):
        launder_check_result(
            historical,
            canonical_json(forged),
            old_identity=OLD_IDENTITY,
            new_identity=NEW_IDENTITY,
        )
    other = json.loads(current)
    other["derivation"]["python_identity"] = "cpython-3.14.7"
    with pytest.raises(
        LaunderCheckError,
        match=r"^LAUNDER_CHECK_IDENTITY expected cpython-3\.14\.5 -> cpython-3\.14\.6",
    ):
        launder_check_result(
            historical,
            canonical_json(_rehash_result(other)),
            old_identity=OLD_IDENTITY,
            new_identity=NEW_IDENTITY,
        )
    with pytest.raises(
        LaunderCheckError, match=r"^LAUNDER_CHECK_NONCANONICAL current result"
    ):
        launder_check_result(
            historical,
            current + b"\n",
            old_identity=OLD_IDENTITY,
            new_identity=NEW_IDENTITY,
        )


def test_launder_check_rejects_a_hash_index_change_outside_the_results() -> None:
    files = _generation_bytes("v2")
    index_historical, index_current = files["hash-index.json"]
    parsed = json.loads(index_current)
    victim = next(
        entry for entry in parsed["entries"] if entry["path"] == "joined-context.json"
    )
    victim["sha256"] = "0" * 64
    with pytest.raises(
        LaunderCheckError, match=r"^LAUNDER_CHECK_NON_IDENTITY_FIELD entries\["
    ):
        launder_check_hash_index(
            index_historical,
            canonical_json(parsed),
            results={name: files[name] for name in RESULT_NAMES},
        )


@pytest.mark.parametrize("generation", ("v1", "v2", "v3"))
def test_historical_cpython_3_14_5_baseline_is_preserved_byte_for_byte(
    generation: str,
) -> None:
    """History is superseded, never rewritten, relabelled or deleted."""
    helper = _load_replay_helper()
    record = _record()
    superseded = record["generations"][generation]["superseded_paths"]
    for name in (*RESULT_NAMES, "hash-index.json"):
        path = f"tests/fixtures/m1d/{generation}/{name}"
        live = (REPO_ROOT / path).read_bytes()
        assert live == _git_bytes(SOURCE_COMMITS[generation], path), path
        digest = _sha256(live)
        assert digest == superseded[path]["historical_sha256"], path
        assert digest == helper.PROTECTED_M1D_ARCHIVE_SHA256[path], path
        assert digest == helper.PROTECTED_M1D_SHA256[path], path
    for name in RESULT_NAMES:
        result = REPO_ROOT / f"tests/fixtures/m1d/{generation}/{name}"
        assert json.loads(result.read_bytes())["derivation"]["python_identity"] == (
            OLD_IDENTITY
        )
    inventory = (
        REPO_ROOT / "tests/fixtures/m1e-compatibility/m1d-v3-protected-sha256.json"
    )
    assert (
        _sha256(inventory.read_bytes())
        == (record["supersedes"]["historical_inventory"]["file_sha256"])
    )


def test_supersession_record_names_everything_the_ruling_requires() -> None:
    """Prior and new identity, interpreters, reason, commits, lock, semantics."""
    helper = _load_replay_helper()
    raw = RECORD_PATH.read_bytes()
    assert _sha256(raw) == helper._EXPECTED_REPLAY_BASELINE_SHA256
    record = json.loads(raw)
    assert record["record_id"] == "m1d-replay-baseline-cpython-3.14.6"
    assert record["issue"] == 48
    assert record["baseline"] == {
        "baseline_id": "m1d-replay-baseline-cpython-3.14.6",
        "python_identity": NEW_IDENTITY,
        "interpreter_pin": ".python-version",
    }
    supersedes = record["supersedes"]
    assert supersedes["baseline_id"] == "m1d-replay-baseline-cpython-3.14.5"
    assert supersedes["python_identity"] == OLD_IDENTITY
    assert supersedes["historical_inventory"]["inventory_id"] == (
        "m1d-v3-protected-sha256"
    )
    for text in (supersedes["status"], record["reason"]):
        assert text.strip()
        assert "invalid" not in text.lower(), text
    assert "unavailable" in supersedes["status"]
    assert "python_identity" in record["reason"]
    assert set(record["generations"]) == set(SOURCE_COMMITS)
    assert helper.PINNED_M1D_GENERATIONS == SOURCE_COMMITS
    live_lock = _sha256((REPO_ROOT / "uv.lock").read_bytes())
    for generation, commit in SOURCE_COMMITS.items():
        entry = record["generations"][generation]
        assert entry["source_commit"] == commit
        lock = entry["lockfile_identity"]["uv_lock_sha256"]
        assert lock == _sha256(_git_bytes(commit, "uv.lock")) == live_lock
        semantic = entry["semantic_implementation_identity"]
        for name in RESULT_NAMES:
            for raw_result in (
                (REPO_ROOT / f"tests/fixtures/m1d/{generation}/{name}").read_bytes(),
                (
                    REPO_ROOT
                    / entry["superseded_paths"][
                        f"tests/fixtures/m1d/{generation}/{name}"
                    ]["baseline_path"]
                ).read_bytes(),
            ):
                derivation = json.loads(raw_result)["derivation"]
                assert derivation["lockfile_hash"] == lock
                assert (
                    derivation["implementation_hash"]
                    == (semantic["implementation_hash"])
                )
                assert (
                    derivation["semantic_algorithm_hash"]
                    == (semantic["semantic_algorithm_hash"])
                )
    verification = record["verification"]
    assert verification["result"] == "passed"
    assert verification["python_identity"] == NEW_IDENTITY
    for relative in verification["enforced_by"]:
        assert (REPO_ROOT / relative).is_file(), relative


def test_supersession_record_cannot_omit_the_superseded_interpreter() -> None:
    """A record that forgets which interpreter it supersedes is rejected."""
    helper = _load_replay_helper()
    document = _record()
    assert helper._validated_replay_baseline(document).keys() == {"v1", "v2", "v3"}
    for mutation in ("delete", "blank", "wrong"):
        broken = copy.deepcopy(document)
        if mutation == "delete":
            del broken["supersedes"]["python_identity"]
        elif mutation == "blank":
            broken["supersedes"]["python_identity"] = ""
        else:
            broken["supersedes"]["python_identity"] = NEW_IDENTITY
        error = _raised(partial(helper._validated_replay_baseline, broken))
        assert type(error) is helper.PinnedReplayIntegrityFailure
        assert str(error).startswith(
            "PINNED_REPLAY_INTEGRITY_FAILURE replay baseline supersession must "
            "name the superseded interpreter identity cpython-3.14.5"
        ), str(error)


def test_supersession_record_cannot_overlay_source_or_misstate_history() -> None:
    """The baseline may re-mint fixture bytes, never semantic code or history."""
    helper = _load_replay_helper()
    document = _record()
    smuggled = copy.deepcopy(document)
    smuggled["generations"]["v3"]["superseded_paths"][
        "src/drift/markets/normalization.py"
    ] = {
        "historical_sha256": "1" * 64,
        "current_sha256": "2" * 64,
        "baseline_path": "tests/fixtures/m1d-replay-baselines/x.py",
    }
    error = _raised(lambda: helper._validated_replay_baseline(smuggled))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        "PINNED_REPLAY_INTEGRITY_FAILURE replay baseline v3 may only supersede"
    ), str(error)

    misstated = copy.deepcopy(document)
    target = "tests/fixtures/m1d/v1/expected-decision-result.json"
    misstated["generations"]["v1"]["superseded_paths"][target]["historical_sha256"] = (
        "3" * 64
    )
    error = _raised(lambda: helper._validated_replay_baseline(misstated))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        "PINNED_REPLAY_INTEGRITY_FAILURE replay baseline v1 misstates the "
        f"historical pin for {target}"
    ), str(error)

    resigned = copy.deepcopy(document)
    resigned["generations"]["v2"]["superseded_paths"][
        "tests/fixtures/m1d/v2/hash-index.json"
    ]["current_sha256"] = "4" * 64
    error = _raised(lambda: helper._validated_replay_baseline(resigned))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        "PINNED_REPLAY_INTEGRITY_FAILURE replay baseline v2 bytes do not match "
        "the supersession record for tests/fixtures/m1d/v2/hash-index.json"
    ), str(error)


def test_pin_that_disagrees_with_the_baseline_is_an_integrity_failure(
    tmp_path: Path,
) -> None:
    """Moving the pin alone, without minting a baseline, cannot pass."""
    helper = _load_replay_helper()
    pin = tmp_path / ".python-version"
    pin.write_text("3.14.7\n", encoding="utf-8")
    error = _raised(
        lambda: helper.verify_replay_interpreter(
            observed="cpython-3.14.7", pin_path=pin
        )
    )
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error) == (
        f"PINNED_REPLAY_INTEGRITY_FAILURE interpreter pin {pin} names "
        "cpython-3.14.7 but the current replay baseline was minted under "
        "cpython-3.14.6"
    )


@pytest.mark.parametrize("generation", ("v1", "v2", "v3"))
def test_replay_archive_carries_exactly_the_superseding_baseline(
    tmp_path: Path, generation: str
) -> None:
    """The prepared archive is the source commit plus the declared overlay only."""
    helper = _load_replay_helper()
    archive = helper.prepare_m1d_replay_archive(tmp_path / "archive", generation)
    record = _record()["generations"][generation]
    pins = helper.REPLAY_BASELINE[generation].pins
    historical = helper._historical_generation_pins(generation)
    moved = {path for path in pins if historical.get(path) != pins[path]}
    assert moved == set(record["superseded_paths"])
    for path, entry in record["superseded_paths"].items():
        assert _sha256((archive / path).read_bytes()) == entry["current_sha256"]
    assert not any(path.startswith("src/") for path in moved)


def test_tampered_superseding_baseline_is_an_integrity_failure(
    tmp_path: Path,
) -> None:
    helper = _load_replay_helper()
    archive = helper.prepare_m1d_replay_archive(tmp_path / "archive", "v3")
    target = archive / "tests/fixtures/m1d/v3/expected-decision-result.json"
    target.write_bytes(target.read_bytes().replace(b"3.14.6", b"3.14.5", 1))
    error = _raised(
        lambda: helper._run_archived_m1d_node_in_root(
            archive,
            "tests/integration/test_m1d_adversarial_matrix.py::"
            "test_current_expected_decision_and_outcome_bytes_replay",
        )
    )
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        "PINNED_REPLAY_INTEGRITY_FAILURE protected M1d sha256 mismatch for "
        "tests/fixtures/m1d/v3/expected-decision-result.json"
    ), str(error)


def test_superseding_baseline_is_applied_only_over_the_historical_bytes(
    tmp_path: Path,
) -> None:
    """The overlay cannot be stacked or applied over anything but history."""
    helper = _load_replay_helper()
    archive = helper.prepare_m1d_replay_archive(tmp_path / "archive", "v1")
    error = _raised(lambda: helper.apply_m1d_replay_baseline(archive, "v1"))
    assert type(error) is helper.PinnedReplayIntegrityFailure
    assert str(error).startswith(
        "PINNED_REPLAY_INTEGRITY_FAILURE archived "
        "tests/fixtures/m1d/v1/expected-decision-result.json is not the "
        "superseded historical baseline"
    ), str(error)
