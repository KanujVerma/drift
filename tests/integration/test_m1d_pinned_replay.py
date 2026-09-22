"""Behavioral tests for the authenticated archived M1d v3 replay lane."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_replay_helper() -> ModuleType:
    helper_path = Path(__file__).parents[1] / "_pinned_m1d.py"
    spec = importlib.util.spec_from_file_location("_pinned_m1d", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pinned_m1d_lane_routes_only_accepted_archived_nodes() -> None:
    """A new or renamed M1d acceptance node cannot silently run current code."""
    helper = _load_replay_helper()
    assert helper.is_pinned_m1d_node(
        "tests/integration/test_m1d_adversarial_matrix.py::"
        "test_current_expected_decision_and_outcome_bytes_replay"
    )
    assert helper.is_pinned_m1d_node(
        "tests/integration/test_m1d_compatibility.py::"
        "test_c02_current_code_composes_m1c_into_fixture_only_m1d_replay"
    )
    assert helper.is_pinned_m1d_node(
        "tests/integration/test_m1d_adversarial_matrix.py::test_future_case"
    )


def test_changed_archived_source_byte_is_rejected_before_child_replay(
    tmp_path: Path,
) -> None:
    """A source mutation must not be replayed under a re-signed current package."""
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "archive")
    target = archive / "src/drift/domain/temporal.py"
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")

    with pytest.raises(helper.PinnedM1dReplayError, match="sha256 mismatch"):
        helper.verify_m1d_archive_inputs(root=archive)


def test_changed_archived_v3_fixture_byte_is_rejected_before_child_replay(
    tmp_path: Path,
) -> None:
    """Exact archived v3 fixture bytes are an input, not an output to re-sign."""
    helper = _load_replay_helper()
    archive = helper.extract_m1d_archive(tmp_path / "archive")
    target = archive / "tests/fixtures/m1d/v3/expected-decision-result.json"
    target.write_bytes(b"tampered")

    with pytest.raises(helper.PinnedM1dReplayError, match="sha256 mismatch"):
        helper.verify_m1d_archive_inputs(root=archive)


def test_re_signed_or_incomplete_inventory_is_rejected(tmp_path: Path) -> None:
    """Changing the literal inventory cannot bless a changed protected input."""
    helper = _load_replay_helper()
    inventory = json.loads(helper._INVENTORY_PATH.read_text(encoding="utf-8"))
    inventory["sha256"]["src/drift/domain/temporal.py"] = "0" * 64
    controlled = tmp_path / "re-signed.json"
    controlled.write_text(json.dumps(inventory), encoding="utf-8")
    original = helper._INVENTORY_PATH
    helper._INVENTORY_PATH = controlled  # type: ignore[attr-defined]
    try:
        with pytest.raises(
            helper.PinnedM1dReplayError, match="inventory sha256 mismatch"
        ):
            helper._load_inventory()
    finally:
        helper._INVENTORY_PATH = original  # type: ignore[attr-defined]


ATTESTATION_SOURCE_PATH = "src/drift/domain/semantic_attestation.py"


def test_archived_replay_still_authenticates_against_the_historical_pins() -> None:
    """Superseding the working-tree pins must not re-sign the af75cce archive."""
    helper = _load_replay_helper()
    historical = helper.PROTECTED_M1D_ARCHIVE_SHA256
    current = helper.PROTECTED_M1D_SHA256
    inventory = json.loads(helper._CURRENT_INVENTORY_PATH.read_text(encoding="utf-8"))
    added = set(inventory["added_paths"])
    assert set(current) == set(historical) | added
    assert not added & set(historical)
    superseded = {
        path
        for path in historical
        if path in current and historical[path] != current[path]
    }
    assert superseded == {
        "src/drift/markets/observation_validation.py",
        "src/drift/markets/session_validation.py",
    }
    assert set(inventory["superseded_paths"]) == superseded
    assert inventory["supersedes"]["commit"] == helper.PINNED_M1D_COMMIT
    assert inventory["supersedes"]["file_sha256"] == helper._EXPECTED_INVENTORY_SHA256


def test_current_inventory_pins_the_identity_defining_attestation_module() -> None:
    """The file that defines the replay identity must itself be byte-pinned."""
    helper = _load_replay_helper()
    assert ATTESTATION_SOURCE_PATH not in helper.PROTECTED_M1D_ARCHIVE_SHA256
    assert ATTESTATION_SOURCE_PATH in helper.PROTECTED_M1D_SHA256

    live = (helper.REPO_ROOT / ATTESTATION_SOURCE_PATH).read_bytes()
    assert (
        helper.PROTECTED_M1D_SHA256[ATTESTATION_SOURCE_PATH]
        == hashlib.sha256(live).hexdigest()
    )

    inventory = json.loads(helper._CURRENT_INVENTORY_PATH.read_text(encoding="utf-8"))
    record = inventory["added_paths"][ATTESTATION_SOURCE_PATH]
    assert record["issue"] == 32
    assert record["justification"].strip()

    # The pin is load-bearing, not decorative: a changed byte must be rejected.
    helper.verify_m1d_protected_inputs(root=helper.REPO_ROOT)
    tampered = dict(helper.PROTECTED_M1D_SHA256)
    tampered[ATTESTATION_SOURCE_PATH] = "0" * 64
    with pytest.raises(helper.PinnedM1dReplayError, match="sha256 mismatch for"):
        helper.verify_m1d_protected_inputs(root=helper.REPO_ROOT, expected=tampered)


def test_current_inventory_cannot_pin_an_undeclared_added_path() -> None:
    """A new path may only enter the current pins through an explicit addition."""
    helper = _load_replay_helper()
    document = json.loads(helper._CURRENT_INVENTORY_PATH.read_text(encoding="utf-8"))

    smuggled = json.loads(json.dumps(document))
    smuggled["sha256"]["src/drift/domain/replay_provenance.py"] = "0" * 64
    with pytest.raises(
        helper.PinnedM1dReplayError, match="pins an undeclared added path"
    ):
        helper._validated_current_pins(smuggled)

    dropped = json.loads(json.dumps(document))
    del dropped["sha256"][ATTESTATION_SOURCE_PATH]
    with pytest.raises(
        helper.PinnedM1dReplayError, match="omits a required protected path"
    ):
        helper._validated_current_pins(dropped)


def test_current_inventory_addition_requires_its_own_justification() -> None:
    """An addition is admitted by declaration, not merely by being different."""
    helper = _load_replay_helper()
    document = json.loads(helper._CURRENT_INVENTORY_PATH.read_text(encoding="utf-8"))

    mutations: tuple[dict[str, object], ...] = (
        {"justification": "   "},
        {"issue": 99},
        {"waiver": "accepted by review"},
    )
    assert mutations
    for mutation in mutations:
        broken = json.loads(json.dumps(document))
        broken["added_paths"][ATTESTATION_SOURCE_PATH].update(mutation)
        with pytest.raises(helper.PinnedM1dReplayError, match="addition is malformed"):
            helper._validated_current_pins(broken)

    stripped = json.loads(json.dumps(document))
    del stripped["added_paths"][ATTESTATION_SOURCE_PATH]["justification"]
    with pytest.raises(helper.PinnedM1dReplayError, match="addition is malformed"):
        helper._validated_current_pins(stripped)

    listed = json.loads(json.dumps(document))
    listed["added_paths"] = [ATTESTATION_SOURCE_PATH]
    with pytest.raises(
        helper.PinnedM1dReplayError, match="addition block is malformed"
    ):
        helper._validated_current_pins(listed)


def test_current_inventory_addition_cannot_shadow_a_historical_pin() -> None:
    """The addition channel must not become a second way to re-sign v3."""
    helper = _load_replay_helper()
    document = json.loads(helper._CURRENT_INVENTORY_PATH.read_text(encoding="utf-8"))
    target = "src/drift/domain/temporal.py"

    shadowed = json.loads(json.dumps(document))
    shadowed["added_paths"][target] = {
        "current_sha256": "0" * 64,
        "issue": 32,
        "justification": "forged addition over an already pinned path",
    }
    shadowed["sha256"][target] = "0" * 64
    with pytest.raises(
        helper.PinnedM1dReplayError, match="an addition the historical inventory"
    ):
        helper._validated_current_pins(shadowed)


def test_current_inventory_cannot_re_sign_an_undeclared_protected_path() -> None:
    """Only the paths the supersession names may differ from the v3 pins."""
    helper = _load_replay_helper()
    document = json.loads(helper._CURRENT_INVENTORY_PATH.read_text(encoding="utf-8"))
    assert helper._validated_current_pins(document) == helper.PROTECTED_M1D_SHA256

    smuggled = json.loads(json.dumps(document))
    smuggled["sha256"]["src/drift/domain/temporal.py"] = "0" * 64
    with pytest.raises(
        helper.PinnedM1dReplayError, match="re-signs undeclared protected paths"
    ):
        helper._validated_current_pins(smuggled)

    misstated = json.loads(json.dumps(document))
    target = "src/drift/markets/session_validation.py"
    misstated["superseded_paths"][target]["historical_sha256"] = "1" * 64
    with pytest.raises(
        helper.PinnedM1dReplayError, match="misstates the historical pin"
    ):
        helper._validated_current_pins(misstated)


def test_wrong_commit_and_missing_archived_node_fail_closed() -> None:
    """Only the accepted commit and an existing archived pytest node may execute."""
    helper = _load_replay_helper()
    with pytest.raises(helper.PinnedM1dReplayError, match="unapproved M1d"):
        helper.extract_m1d_archive(Path("/tmp/not-used"), commit="0" * 40)
    with pytest.raises(helper.PinnedM1dReplayError, match="does_not_exist"):
        helper.run_archived_m1d_node(
            "tests/integration/test_m1d_adversarial_matrix.py::does_not_exist"
        )


def test_wrong_child_import_location_and_child_failure_are_propagated() -> None:
    """Ambient imports and nonzero archived pytest exits are parent failures."""
    helper = _load_replay_helper()
    with pytest.raises(helper.PinnedM1dReplayError, match="outside pinned archive"):
        helper.verify_child_import_location(
            "/tmp/ambient/drift/__init__.py", Path("/tmp/pinned-archive")
        )
    with pytest.raises(helper.PinnedM1dReplayError, match="does_not_exist"):
        helper.run_archived_m1d_node(
            "tests/integration/test_m1d_adversarial_matrix.py::does_not_exist"
        )
