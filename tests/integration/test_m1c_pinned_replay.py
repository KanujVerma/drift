"""Behavioral tests for the isolated M1c legacy replay lane."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_replay_helper() -> Any:
    helper_path = Path(__file__).parents[1] / "_pinned_m1c.py"
    spec = importlib.util.spec_from_file_location("_pinned_m1c", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_replay_requires_a_helper_with_the_pinned_route_contract() -> None:
    """A removed or renamed historical case must not silently run current code."""
    helper = _load_replay_helper()

    assert helper.is_pinned_m1c_node(
        "tests/integration/test_m1c_economic_history.py::"
        "test_m1c_fixture_preserves_installment_lineage"
    )
    assert not helper.is_pinned_m1c_node(
        "tests/integration/test_m1c_economic_history.py::test_m1c_future_case"
    )


def test_selected_archived_case_replays_without_requiring_the_other_five() -> None:
    """An intentionally focused historical node must replay from its V2 archive."""
    helper = _load_replay_helper()
    environment = dict(os.environ)
    environment.pop("DRIFT_PINNED_REPLAY_CHILD", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"{helper.HISTORY_MODULE}::test_m1c_fixture_preserves_installment_lineage",
        ],
        cwd=helper.REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_history_definition_renaming_is_rejected_in_a_controlled_copy(
    tmp_path: Path,
) -> None:
    """A renamed history case cannot evade the complete-six definition gate."""
    helper = _load_replay_helper()
    controlled = tmp_path / "test_m1c_economic_history.py"
    controlled.write_bytes(
        helper.read_git_bytes(helper.HISTORY_MODULE).replace(
            b"test_m1c_v2_preserves_v1_economic_source_facts",
            b"test_m1c_v2_preserves_renamed_source_facts",
            1,
        )
    )

    with pytest.raises(helper.PinnedReplayError, match="approved six"):
        helper.verify_history_test_definitions(controlled)


def test_pinned_replay_executes_all_archived_v1_cases() -> None:
    """The archived V1 implementation, rather than current source, remains runnable."""
    helper = _load_replay_helper()

    completed = helper.run_archived_v1_cases()

    assert completed.returncode == 0, completed.output
    assert completed.case_count == 4


def test_protected_input_tampering_is_rejected_by_literal_sha256_pins() -> None:
    """A changed archived fixture byte must fail before a child replay starts."""
    helper = _load_replay_helper()
    target = "tests/fixtures/m1c/v2/liquidation/settlements-a.json"

    with pytest.raises(helper.PinnedReplayError, match="sha256 mismatch"):
        helper.verify_protected_inputs(
            read_bytes=lambda path: (
                b"tampered" if path == target else helper.read_git_bytes(path)
            )
        )


def test_missing_literal_inventory_pin_is_rejected_before_archive_extraction(
    tmp_path: Path,
) -> None:
    """Removing a path from the JSON inventory cannot become an automatic re-sign."""
    helper = _load_replay_helper()
    inventory = json.loads(helper._INVENTORY_PATH.read_text(encoding="utf-8"))
    del inventory["sha256"]["src/drift/domain/temporal.py"]
    controlled = tmp_path / "missing-pin.json"
    controlled.write_text(json.dumps(inventory), encoding="utf-8")
    original = helper._INVENTORY_PATH
    helper._INVENTORY_PATH = controlled
    try:
        with pytest.raises(helper.PinnedReplayError, match="inventory sha256 mismatch"):
            helper._load_inventory()
    finally:
        helper._INVENTORY_PATH = original


def test_re_signed_literal_inventory_digest_is_rejected_before_archive_extraction(
    tmp_path: Path,
) -> None:
    """Replacing a protected digest in the JSON inventory cannot bless changed bytes."""
    helper = _load_replay_helper()
    inventory = json.loads(helper._INVENTORY_PATH.read_text(encoding="utf-8"))
    inventory["sha256"]["src/drift/domain/temporal.py"] = "0" * 64
    controlled = tmp_path / "re-signed-pin.json"
    controlled.write_text(json.dumps(inventory), encoding="utf-8")
    original = helper._INVENTORY_PATH
    helper._INVENTORY_PATH = controlled
    try:
        with pytest.raises(helper.PinnedReplayError, match="inventory sha256 mismatch"):
            helper._load_inventory()
    finally:
        helper._INVENTORY_PATH = original


def test_wrong_child_import_location_is_rejected() -> None:
    """A child importing ambient Drift must fail rather than replay ambiguously."""
    helper = _load_replay_helper()

    with pytest.raises(helper.PinnedReplayError, match="outside pinned archive"):
        helper.verify_child_import_location(
            "/tmp/ambient/drift/__init__.py", Path("/tmp/pinned-archive")
        )


def test_child_failure_output_is_propagated_to_the_parent() -> None:
    """A nonzero archival pytest exit is surfaced with its captured diagnostics."""
    helper = _load_replay_helper()

    with pytest.raises(helper.PinnedReplayError, match="does_not_exist"):
        helper.run_archived_node(
            helper.V2_INTERPRETER_COMMIT,
            "tests/integration/test_m1c_economic_history.py::does_not_exist",
        )


def test_additive_m1d_source_is_not_part_of_the_protected_m1c_inventory(
    tmp_path: Path,
) -> None:
    """A new source module does not invalidate pinned M1c source contracts.

    The archive is authenticated against the historical v2 pins: since issue
    63 stage 2, v2 is the archive authority and the m1c-v3 link describes the
    live working tree instead.
    """
    helper = _load_replay_helper()
    archive = helper.extract_archive(helper.V2_INTERPRETER_COMMIT, tmp_path / "archive")
    added = archive / "src" / "drift" / "domain" / "observations.py"
    added.write_text('"""Additive M1d model."""\n', encoding="utf-8")

    helper.verify_archive_inputs(root=archive)


# --- the m1c-v3 supersession link (issue 63, stage 2) -------------------------

V2_INVENTORY_SHA256 = "f3fa52804a4f282c9b6cf8f7d67cc94232d63c557193686f7dc9ffa3268613c6"
M1C_LINK_SUPERSEDED_PATHS = frozenset(
    {
        "src/drift/markets/economic_outcomes.py",
        "src/drift/markets/economic_selection.py",
        "src/drift/markets/economic_validation.py",
    }
)
"""The paths issue 63 stage 2 moved, stated independently of the helper."""


def _link_document(helper: Any) -> dict[str, Any]:
    document = json.loads(helper._LINK_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _copy(document: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(document))
    assert isinstance(copied, dict)
    return copied


def _git_sha256(helper: Any, commit: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=helper.REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def test_the_m1c_v3_link_supersedes_v2_by_exactly_the_stage_2_paths() -> None:
    """v3 is v2 with the three stamp-site modules re-pinned, and nothing else."""
    helper = _load_replay_helper()
    document = _link_document(helper)
    assert document["inventory_id"] == "m1c-v3-protected-sha256"
    assert document["role"] == "current"
    assert document["baseline_commit"] == helper.V2_INTERPRETER_COMMIT
    supersedes = document["supersedes"]
    assert supersedes["inventory_id"] == "m1c-v2-protected-sha256"
    assert supersedes["path"] == (
        helper._INVENTORY_PATH.relative_to(helper.REPO_ROOT).as_posix()
    )
    assert supersedes["file_sha256"] == V2_INVENTORY_SHA256
    assert supersedes["commit"] == helper.V2_INTERPRETER_COMMIT
    assert supersedes["issue"] == 63
    assert "semantic attestation" in supersedes["reason"]
    assert "aecee94 archive" in supersedes["status"]
    assert set(document["superseded_paths"]) == M1C_LINK_SUPERSEDED_PATHS
    assert document["added_paths"] == {}

    historical = helper.HISTORICAL_PROTECTED_SHA256
    expected = dict(historical)
    for path, record in document["superseded_paths"].items():
        # The historical side is the v2 pin, which is the aecee94 byte content.
        assert record["historical_sha256"] == historical[path], path
        assert record["historical_sha256"] == _git_sha256(
            helper, helper.V2_INTERPRETER_COMMIT, path
        ), path
        live = (helper.REPO_ROOT / path).read_bytes()
        assert record["current_sha256"] == hashlib.sha256(live).hexdigest(), path
        assert record["current_sha256"] != record["historical_sha256"], path
        expected[path] = record["current_sha256"]
    assert document["sha256"] == expected
    assert helper.PROTECTED_SHA256 == expected
    assert len(expected) == 126


def test_the_live_tree_is_v3_and_the_aecee94_archive_is_v2(tmp_path: Path) -> None:
    """Two pin sets, not interchangeable: v3 for the live tree, v2 for history."""
    helper = _load_replay_helper()
    helper.verify_protected_inputs()
    with pytest.raises(helper.PinnedReplayError, match="sha256 mismatch for src/drift"):
        helper.verify_protected_inputs(expected=helper.HISTORICAL_PROTECTED_SHA256)

    # Nothing historical moved: v2 still describes the aecee94 archive exactly,
    # and the current pins do not.
    archive = helper.extract_archive(helper.V2_INTERPRETER_COMMIT, tmp_path / "archive")
    helper.verify_archive_inputs(root=archive)
    with pytest.raises(helper.PinnedReplayError, match="sha256 mismatch for src/drift"):
        helper.verify_protected_inputs(root=archive)


def test_the_archive_verifier_rejects_a_changed_archived_byte(tmp_path: Path) -> None:
    helper = _load_replay_helper()
    archive = helper.extract_archive(helper.V2_INTERPRETER_COMMIT, tmp_path / "archive")
    target = archive / "src/drift/markets/economic_outcomes.py"
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    with pytest.raises(helper.PinnedReplayError, match="sha256 mismatch for"):
        helper.verify_archive_inputs(root=archive)
    incomplete = dict(helper.HISTORICAL_PROTECTED_SHA256)
    del incomplete["src/drift/domain/temporal.py"]
    with pytest.raises(helper.PinnedReplayError, match="incomplete"):
        helper.verify_archive_inputs(root=archive, expected=incomplete)


def test_the_m1c_link_cannot_misstate_a_v2_pin() -> None:
    helper = _load_replay_helper()
    misstated = _copy(_link_document(helper))
    path = "src/drift/markets/economic_outcomes.py"
    misstated["superseded_paths"][path]["historical_sha256"] = "1" * 64
    with pytest.raises(helper.PinnedReplayError, match="misstates the superseded pin"):
        helper._validated_link_pins(misstated, helper.HISTORICAL_PROTECTED_SHA256)


def test_the_m1c_link_cannot_supersede_a_path_v2_does_not_pin() -> None:
    helper = _load_replay_helper()
    widened = _copy(_link_document(helper))
    target = "src/drift/domain/semantic_attestation.py"
    widened["superseded_paths"][target] = {
        "historical_sha256": "1" * 64,
        "current_sha256": "2" * 64,
    }
    widened["sha256"][target] = "2" * 64
    with pytest.raises(helper.PinnedReplayError, match="supersedes an unpinned"):
        helper._validated_link_pins(widened, helper.HISTORICAL_PROTECTED_SHA256)


def test_the_m1c_link_cannot_declare_an_addition_v2_already_pins() -> None:
    helper = _load_replay_helper()
    target = "src/drift/domain/temporal.py"
    shadowed = _copy(_link_document(helper))
    shadowed["added_paths"][target] = {
        "current_sha256": "0" * 64,
        "issue": 63,
        "justification": "forged addition over an already pinned path",
    }
    shadowed["sha256"][target] = "0" * 64
    with pytest.raises(
        helper.PinnedReplayError,
        match="an addition the inventory it supersedes already pins",
    ):
        helper._validated_link_pins(shadowed, helper.HISTORICAL_PROTECTED_SHA256)

    # A genuine addition needs its own issue and justification.
    added = "src/drift/domain/semantic_attestation.py"
    for record in (
        {"current_sha256": "0" * 64, "issue": 32, "justification": "pinned"},
        {"current_sha256": "0" * 64, "issue": 63, "justification": " "},
        {"current_sha256": "0" * 64, "issue": 63},
    ):
        broken = _copy(_link_document(helper))
        broken["added_paths"][added] = record
        broken["sha256"][added] = "0" * 64
        with pytest.raises(helper.PinnedReplayError, match="addition is malformed"):
            helper._validated_link_pins(broken, helper.HISTORICAL_PROTECTED_SHA256)
    accepted = _copy(_link_document(helper))
    accepted["added_paths"][added] = {
        "current_sha256": "0" * 64,
        "issue": 63,
        "justification": "pinned",
    }
    accepted["sha256"][added] = "0" * 64
    assert added in helper._validated_link_pins(
        accepted, helper.HISTORICAL_PROTECTED_SHA256
    )


def test_the_m1c_link_cannot_re_sign_widen_or_omit_an_undeclared_path() -> None:
    helper = _load_replay_helper()
    document = _link_document(helper)
    re_signed = _copy(document)
    re_signed["sha256"]["src/drift/domain/temporal.py"] = "0" * 64
    with pytest.raises(
        helper.PinnedReplayError, match="re-signs undeclared protected paths"
    ):
        helper._validated_link_pins(re_signed, helper.HISTORICAL_PROTECTED_SHA256)

    # Editing a declared pin without its supersession record is a re-sign too.
    edited = _copy(document)
    edited["sha256"]["src/drift/markets/economic_selection.py"] = "2" * 64
    with pytest.raises(
        helper.PinnedReplayError, match="re-signs undeclared protected paths"
    ):
        helper._validated_link_pins(edited, helper.HISTORICAL_PROTECTED_SHA256)

    widened = _copy(document)
    widened["sha256"]["src/drift/domain/replay_provenance.py"] = "0" * 64
    with pytest.raises(helper.PinnedReplayError, match="undeclared added path"):
        helper._validated_link_pins(widened, helper.HISTORICAL_PROTECTED_SHA256)

    omitted = _copy(document)
    del omitted["sha256"]["src/drift/domain/temporal.py"]
    with pytest.raises(helper.PinnedReplayError, match="omits a required"):
        helper._validated_link_pins(omitted, helper.HISTORICAL_PROTECTED_SHA256)

    empty: object
    for empty in ({}, []):
        broken = _copy(document)
        broken["superseded_paths"] = empty
        with pytest.raises(helper.PinnedReplayError, match="supersession is malformed"):
            helper._validated_link_pins(broken, helper.HISTORICAL_PROTECTED_SHA256)
    no_op = _copy(document)
    path = "src/drift/markets/economic_validation.py"
    record = no_op["superseded_paths"][path]
    record["current_sha256"] = record["historical_sha256"]
    no_op["sha256"][path] = record["historical_sha256"]
    with pytest.raises(
        helper.PinnedReplayError, match=f"supersession is malformed for {path}"
    ):
        helper._validated_link_pins(no_op, helper.HISTORICAL_PROTECTED_SHA256)


def test_the_m1c_link_must_name_exactly_the_inventory_it_supersedes() -> None:
    helper = _load_replay_helper()
    document = _link_document(helper)
    for mutation in (
        {"inventory_id": "m1c-v1-protected-sha256"},
        {"path": "tests/fixtures/m1d-compatibility/m1c-v1-protected-sha256.json"},
        {"file_sha256": "0" * 64},
        {"commit": helper.V1_INTERPRETER_COMMIT},
        {"issue": 32},
        {"reason": "  "},
        {"status": ""},
    ):
        broken = _copy(document)
        broken["supersedes"].update(mutation)
        with pytest.raises(helper.PinnedReplayError, match="supersession is malformed"):
            helper._validated_link_pins(broken, helper.HISTORICAL_PROTECTED_SHA256)
    for key, value in (
        ("inventory_id", "m1c-v2-protected-sha256"),
        ("baseline_commit", "0" * 40),
        ("role", "historical"),
    ):
        broken = _copy(document)
        broken[key] = value
        with pytest.raises(helper.PinnedReplayError, match="inventory is malformed"):
            helper._validated_link_pins(broken, helper.HISTORICAL_PROTECTED_SHA256)


def test_an_edited_v2_or_v3_byte_is_rejected_although_v3_is_current(
    tmp_path: Path,
) -> None:
    """History stays byte-identical: neither inventory can be edited silently."""
    helper = _load_replay_helper()
    original = helper._INVENTORY_PATH
    edited = tmp_path / original.name
    edited.write_bytes(original.read_bytes() + b"\n")
    helper._INVENTORY_PATH = edited
    try:
        # The link is re-derived over v2 on every load, so it cannot anchor
        # itself on an edited predecessor.
        for load in (helper._load_inventory, helper._load_link):
            with pytest.raises(
                helper.PinnedReplayError, match="literal inventory sha256 mismatch"
            ):
                load()
    finally:
        helper._INVENTORY_PATH = original

    original = helper._LINK_PATH
    edited = tmp_path / original.name
    edited.write_bytes(original.read_bytes() + b"\n")
    helper._LINK_PATH = edited
    try:
        with pytest.raises(
            helper.PinnedReplayError, match="m1c-v3 inventory sha256 mismatch"
        ):
            helper._load_link()
    finally:
        helper._LINK_PATH = original
    assert helper._load_link() == helper.PROTECTED_SHA256
    assert helper._load_inventory() == helper.HISTORICAL_PROTECTED_SHA256


def test_the_link_loader_re_derives_the_link_even_under_a_matching_pin(
    tmp_path: Path,
) -> None:
    """A re-signed link whose literal pin was updated to match is still refused.

    The literal pin only authenticates the bytes; the loader must also
    re-derive the pins over v2, so changing the link and its pin together
    cannot re-sign an undeclared path.
    """
    helper = _load_replay_helper()
    forged = _copy(_link_document(helper))
    forged["sha256"]["src/drift/domain/temporal.py"] = "0" * 64
    data = (json.dumps(forged, indent=2) + "\n").encode("utf-8")
    path = tmp_path / helper._LINK_PATH.name
    path.write_bytes(data)
    original_path, original_pin = helper._LINK_PATH, helper._EXPECTED_LINK_SHA256
    helper._LINK_PATH = path
    helper._EXPECTED_LINK_SHA256 = hashlib.sha256(data).hexdigest()
    try:
        with pytest.raises(
            helper.PinnedReplayError, match="re-signs undeclared protected paths"
        ):
            helper._load_link()
    finally:
        helper._LINK_PATH, helper._EXPECTED_LINK_SHA256 = original_path, original_pin
