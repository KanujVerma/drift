"""Behavioral tests for the authenticated archived M1d v3 replay lane."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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
IDENTITY_ACCESSOR_PATH = "src/drift/domain/observation_query.py"
PREVIOUS_INVENTORY_COMMIT = "4ad90aa97da677386ac212c3596703fccb309f3b"


def _document(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_archived_replay_still_authenticates_against_the_historical_pins() -> None:
    """Superseding the working-tree pins must not re-sign the af75cce archive."""
    helper = _load_replay_helper()
    historical = helper.PROTECTED_M1D_ARCHIVE_SHA256
    previous = helper.PREVIOUS_M1D_SHA256
    current = helper.PROTECTED_M1D_SHA256
    v4 = _document(helper._PREVIOUS_INVENTORY_PATH)
    v5 = _document(helper._CURRENT_INVENTORY_PATH)
    assert set(previous) == set(historical) | set(v4["added_paths"])
    assert set(current) == set(previous) | set(v5["added_paths"])
    assert not set(v4["added_paths"]) & set(historical)
    assert not set(v5["added_paths"]) & set(previous)
    superseded = {
        path
        for path in historical
        if path in current and historical[path] != current[path]
    }
    assert superseded == {
        "src/drift/markets/observation_validation.py",
        "src/drift/markets/session_validation.py",
        IDENTITY_ACCESSOR_PATH,
    }
    assert set(v4["superseded_paths"]) == {
        "src/drift/markets/observation_validation.py",
        "src/drift/markets/session_validation.py",
    }
    assert set(v5["superseded_paths"]) == {
        IDENTITY_ACCESSOR_PATH,
        ATTESTATION_SOURCE_PATH,
    }
    assert v4["supersedes"]["commit"] == helper.PINNED_M1D_COMMIT
    assert v4["supersedes"]["file_sha256"] == helper._EXPECTED_INVENTORY_SHA256
    assert v5["supersedes"]["commit"] == PREVIOUS_INVENTORY_COMMIT
    assert v5["supersedes"]["file_sha256"] == helper._EXPECTED_PREVIOUS_INVENTORY_SHA256


def test_current_inventory_pins_the_identity_defining_modules() -> None:
    """The files that define the evidence identity must themselves be pinned."""
    helper = _load_replay_helper()
    assert ATTESTATION_SOURCE_PATH not in helper.PROTECTED_M1D_ARCHIVE_SHA256
    for path in (ATTESTATION_SOURCE_PATH, IDENTITY_ACCESSOR_PATH):
        live = (helper.REPO_ROOT / path).read_bytes()
        assert helper.PROTECTED_M1D_SHA256[path] == hashlib.sha256(live).hexdigest()

    v4 = _document(helper._PREVIOUS_INVENTORY_PATH)
    added = v4["added_paths"][ATTESTATION_SOURCE_PATH]
    assert added["issue"] == 32
    assert added["justification"].strip()
    v5 = _document(helper._CURRENT_INVENTORY_PATH)
    assert v5["supersedes"]["issue"] == 63
    record = v5["superseded_paths"][ATTESTATION_SOURCE_PATH]
    assert record["historical_sha256"] == added["current_sha256"]
    pinned = helper.PROTECTED_M1D_SHA256[ATTESTATION_SOURCE_PATH]
    assert record["current_sha256"] == pinned

    # The pins are load-bearing, not decorative: a changed byte is rejected.
    helper.verify_m1d_protected_inputs(root=helper.REPO_ROOT)
    for path in (ATTESTATION_SOURCE_PATH, IDENTITY_ACCESSOR_PATH):
        tampered = dict(helper.PROTECTED_M1D_SHA256)
        tampered[path] = "0" * 64
        with pytest.raises(helper.PinnedM1dReplayError, match="sha256 mismatch for"):
            helper.verify_m1d_protected_inputs(root=helper.REPO_ROOT, expected=tampered)


def test_current_pins_are_re_derived_through_every_link() -> None:
    """v3, then the issue 32 delta, then the issue 63 delta, and nothing else."""
    helper = _load_replay_helper()
    expected = dict(helper.PROTECTED_M1D_ARCHIVE_SHA256)
    for path in (helper._PREVIOUS_INVENTORY_PATH, helper._CURRENT_INVENTORY_PATH):
        link = _document(path)
        for relative, record in link["superseded_paths"].items():
            assert expected[relative] == record["historical_sha256"], relative
            expected[relative] = record["current_sha256"]
        for relative, record in link["added_paths"].items():
            assert relative not in expected, relative
            expected[relative] = record["current_sha256"]
        assert link["sha256"] == expected
    assert expected == helper.PROTECTED_M1D_SHA256
    v4 = _document(helper._PREVIOUS_INVENTORY_PATH)
    assert helper._validated_previous_pins(v4) == helper.PREVIOUS_M1D_SHA256
    v5 = _document(helper._CURRENT_INVENTORY_PATH)
    assert helper._validated_current_pins(v5) == helper.PROTECTED_M1D_SHA256


def test_current_inventory_cannot_pin_an_undeclared_added_path() -> None:
    """A new path may only enter the current pins through an explicit addition."""
    helper = _load_replay_helper()
    document = _document(helper._CURRENT_INVENTORY_PATH)

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


def test_inventory_additions_require_their_own_link_justification() -> None:
    """An addition is admitted by declaration, not merely by being different."""
    helper = _load_replay_helper()
    document = _document(helper._PREVIOUS_INVENTORY_PATH)

    mutations: tuple[dict[str, object], ...] = (
        {"justification": "   "},
        {"issue": 99},
        {"issue": 63},
        {"waiver": "accepted by review"},
    )
    assert mutations
    for mutation in mutations:
        broken = json.loads(json.dumps(document))
        broken["added_paths"][ATTESTATION_SOURCE_PATH].update(mutation)
        with pytest.raises(helper.PinnedM1dReplayError, match="addition is malformed"):
            helper._validated_previous_pins(broken)

    stripped = json.loads(json.dumps(document))
    del stripped["added_paths"][ATTESTATION_SOURCE_PATH]["justification"]
    with pytest.raises(helper.PinnedM1dReplayError, match="addition is malformed"):
        helper._validated_previous_pins(stripped)

    listed = json.loads(json.dumps(document))
    listed["added_paths"] = [ATTESTATION_SOURCE_PATH]
    with pytest.raises(
        helper.PinnedM1dReplayError, match="addition block is malformed"
    ):
        helper._validated_previous_pins(listed)

    # A v5 addition is admitted only under issue 63, with its own justification.
    current = _document(helper._CURRENT_INVENTORY_PATH)
    target = "src/drift/domain/replay_provenance.py"
    addition = {"current_sha256": "0" * 64, "issue": 63, "justification": "pinned"}
    widened = json.loads(json.dumps(current))
    widened["added_paths"][target] = dict(addition)
    widened["sha256"][target] = "0" * 64
    assert target in helper._validated_current_pins(widened)
    link_mutations: tuple[dict[str, object], ...] = (
        {"issue": 32},
        {"justification": ""},
    )
    for link_mutation in link_mutations:
        broken = json.loads(json.dumps(widened))
        broken["added_paths"][target].update(link_mutation)
        with pytest.raises(helper.PinnedM1dReplayError, match="addition is malformed"):
            helper._validated_current_pins(broken)


def test_inventory_addition_cannot_shadow_a_pin_of_the_superseded_inventory() -> None:
    """The addition channel must not become a second way to re-sign history."""
    helper = _load_replay_helper()
    target = "src/drift/domain/temporal.py"
    for path, validate, issue in (
        (helper._PREVIOUS_INVENTORY_PATH, helper._validated_previous_pins, 32),
        (helper._CURRENT_INVENTORY_PATH, helper._validated_current_pins, 63),
    ):
        shadowed = _document(path)
        shadowed["added_paths"][target] = {
            "current_sha256": "0" * 64,
            "issue": issue,
            "justification": "forged addition over an already pinned path",
        }
        shadowed["sha256"][target] = "0" * 64
        with pytest.raises(
            helper.PinnedM1dReplayError,
            match="an addition the inventory it supersedes already pins",
        ):
            validate(shadowed)


def test_current_inventory_cannot_re_sign_an_undeclared_protected_path() -> None:
    """Only the paths a link's supersession names may differ from its parent."""
    helper = _load_replay_helper()
    for path, validate, target in (
        (
            helper._PREVIOUS_INVENTORY_PATH,
            helper._validated_previous_pins,
            "src/drift/markets/session_validation.py",
        ),
        (
            helper._CURRENT_INVENTORY_PATH,
            helper._validated_current_pins,
            IDENTITY_ACCESSOR_PATH,
        ),
    ):
        document = _document(path)
        smuggled = json.loads(json.dumps(document))
        smuggled["sha256"]["src/drift/domain/temporal.py"] = "0" * 64
        with pytest.raises(
            helper.PinnedM1dReplayError, match="re-signs undeclared protected paths"
        ):
            validate(smuggled)

        misstated = json.loads(json.dumps(document))
        misstated["superseded_paths"][target]["historical_sha256"] = "1" * 64
        with pytest.raises(
            helper.PinnedM1dReplayError, match="misstates the superseded pin"
        ):
            validate(misstated)


def test_current_inventory_cannot_supersede_a_path_its_parent_does_not_pin() -> None:
    """A path the previous link never pinned enters only as an addition."""
    helper = _load_replay_helper()
    document = _document(helper._CURRENT_INVENTORY_PATH)
    target = "src/drift/domain/replay_provenance.py"
    document["superseded_paths"][target] = {
        "historical_sha256": "1" * 64,
        "current_sha256": "2" * 64,
    }
    document["sha256"][target] = "2" * 64
    with pytest.raises(helper.PinnedM1dReplayError, match="supersedes an unpinned"):
        helper._validated_current_pins(document)


def test_current_inventory_must_name_the_exact_inventory_it_supersedes() -> None:
    """v5 is a link from v4 at 4ad90aa under issue 63, and says so."""
    helper = _load_replay_helper()
    document = _document(helper._CURRENT_INVENTORY_PATH)
    supersession_mutations: tuple[dict[str, object], ...] = (
        {"inventory_id": "m1d-v3-protected-sha256"},
        {"path": "tests/fixtures/m1e-compatibility/m1d-v3-protected-sha256.json"},
        {"file_sha256": helper._EXPECTED_INVENTORY_SHA256},
        {"commit": helper.PINNED_M1D_COMMIT},
        {"issue": 32},
        {"reason": "  "},
        {"status": ""},
    )
    for mutation in supersession_mutations:
        broken = json.loads(json.dumps(document))
        broken["supersedes"].update(mutation)
        with pytest.raises(
            helper.PinnedM1dReplayError, match="inventory supersession is malformed"
        ):
            helper._validated_current_pins(broken)
    for key, value in (
        ("inventory_id", "m1d-v4-protected-sha256"),
        ("role", "historical"),
        ("baseline_commit", "0" * 40),
    ):
        broken = json.loads(json.dumps(document))
        broken[key] = value
        with pytest.raises(helper.PinnedM1dReplayError, match="inventory is malformed"):
            helper._validated_current_pins(broken)


def test_an_edited_superseded_inventory_is_rejected_although_v5_is_current(
    tmp_path: Path,
) -> None:
    """History stays byte-identical: an edited v4 cannot anchor the chain."""
    helper = _load_replay_helper()
    edited = tmp_path / "m1d-v4-protected-sha256.json"
    edited.write_bytes(helper._PREVIOUS_INVENTORY_PATH.read_bytes() + b"\n")
    original = helper._PREVIOUS_INVENTORY_PATH
    helper._PREVIOUS_INVENTORY_PATH = edited  # type: ignore[attr-defined]
    try:
        with pytest.raises(
            helper.PinnedM1dReplayError,
            match="previous M1d inventory sha256 mismatch",
        ):
            helper._load_previous_inventory()
    finally:
        helper._PREVIOUS_INVENTORY_PATH = original  # type: ignore[attr-defined]


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
