"""Behavioral tests for the isolated M1c legacy replay lane."""

from __future__ import annotations

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
    """A new source module does not invalidate pinned M1c source contracts."""
    helper = _load_replay_helper()
    archive = helper.extract_archive(helper.V2_INTERPRETER_COMMIT, tmp_path / "archive")
    added = archive / "src" / "drift" / "domain" / "observations.py"
    added.write_text('"""Additive M1d model."""\n', encoding="utf-8")

    helper.verify_protected_inputs(root=archive)
