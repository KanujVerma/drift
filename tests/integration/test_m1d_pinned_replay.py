"""Behavioral tests for the authenticated archived M1d v3 replay lane."""

from __future__ import annotations

import dataclasses
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
V4_INVENTORY_COMMIT = "4ad90aa97da677386ac212c3596703fccb309f3b"
V5_INVENTORY_COMMIT = "200bfebaf04c5c1e171db029547a75187d2ef665"
V6_INVENTORY_COMMIT = "a906ab293d5690084bb82415c7dcb09cc14903f3"
V7_INVENTORY_COMMIT = "b21efc5612259661b7e380b8f856febf49cbf5a6"
CLOSED_WORLD_SOURCE_PATHS = frozenset(
    {
        "src/drift/domain/session_closed_world.py",
        "src/drift/markets/session_closed_world.py",
    }
)
"""The closed-world coverage modules issue 71 adds to m1d-evidence-v1."""
M1C_STAMP_SITE_PATHS = frozenset(
    {
        "src/drift/markets/economic_outcomes.py",
        "src/drift/markets/economic_selection.py",
        "src/drift/markets/economic_validation.py",
    }
)
"""The M1c modules whose identity stamps issue 63 stage 2 switched."""
FREEZE_LINK_ISSUES = {"v4": 32, "v5": 63, "v6": 107, "v7": 63, "v8": 71}
"""Every freeze link, in chain order, with the issue that minted it."""
FREEZE_LINK_SUPERSESSIONS = {
    "v4": {
        "src/drift/markets/observation_validation.py",
        "src/drift/markets/session_validation.py",
    },
    "v5": {IDENTITY_ACCESSOR_PATH, ATTESTATION_SOURCE_PATH},
    "v6": {ATTESTATION_SOURCE_PATH},
    "v7": {ATTESTATION_SOURCE_PATH, *M1C_STAMP_SITE_PATHS},
    "v8": {ATTESTATION_SOURCE_PATH},
}
"""The paths each link supersedes, stated independently of the helper."""
FREEZE_LINK_ADDITIONS = {
    "v4": {ATTESTATION_SOURCE_PATH},
    "v5": set(),
    "v6": set(),
    "v7": set(),
    "v8": set(CLOSED_WORLD_SOURCE_PATHS),
}
"""The paths each link adds to the freeze, stated independently of the helper."""


def _document(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _link_document(helper: ModuleType, label: str) -> dict[str, Any]:
    return _document(helper._freeze_link(label).path)


def test_freeze_chain_is_v4_to_v8_over_the_historical_v3() -> None:
    """The chain is ordered, each link names its predecessor, and v8 is the tip."""
    helper = _load_replay_helper()
    assert [link.label for link in helper.FREEZE_LINKS] == list(FREEZE_LINK_ISSUES)
    assert {link.label: link.issue for link in helper.FREEZE_LINKS} == (
        FREEZE_LINK_ISSUES
    )
    assert list(helper.FREEZE_CHAIN_SHA256) == list(FREEZE_LINK_ISSUES)
    assert [link.superseded_commit for link in helper.FREEZE_LINKS] == [
        helper.PINNED_M1D_COMMIT,
        V4_INVENTORY_COMMIT,
        V5_INVENTORY_COMMIT,
        V6_INVENTORY_COMMIT,
        V7_INVENTORY_COMMIT,
    ]
    parents = [helper._INVENTORY_PATH, *(link.path for link in helper.FREEZE_LINKS)]
    for link, parent in zip(helper.FREEZE_LINKS, parents[:-1], strict=True):
        assert link.superseded_path == parent.relative_to(helper.REPO_ROOT).as_posix()
        assert (
            link.superseded_file_sha256
            == hashlib.sha256(parent.read_bytes()).hexdigest()
        )
        assert link.file_sha256 == hashlib.sha256(link.path.read_bytes()).hexdigest()
    assert [link.requires_current_role for link in helper.FREEZE_LINKS] == [
        False,
        False,
        False,
        False,
        True,
    ]
    assert helper.PROTECTED_M1D_SHA256 == helper.FREEZE_CHAIN_SHA256["v8"]


def test_freeze_chain_shape_fails_closed_and_grows_by_appending_one_link() -> None:
    """Only the tip leaves its commit open; the next link only appends."""
    helper = _load_replay_helper()
    inventories = helper._FREEZE_INVENTORIES
    tip = inventories[-1]
    with pytest.raises(helper.PinnedM1dReplayError, match="v8 M1d freeze link"):
        helper._chain_links(
            (*inventories[:-1], dataclasses.replace(tip, commit="0" * 40))
        )
    with pytest.raises(helper.PinnedM1dReplayError, match="v7 M1d freeze link"):
        helper._chain_links(
            (*inventories[:-2], dataclasses.replace(inventories[-2], commit=None), tip)
        )
    with pytest.raises(helper.PinnedM1dReplayError, match="must start at v3"):
        helper._chain_links(inventories[1:])

    # Appending v9 without recording the commit that last wrote v8 fails ...
    v9 = dataclasses.replace(
        tip, label="v9", inventory_id="m1d-v9-protected-sha256", issue=999
    )
    with pytest.raises(helper.PinnedM1dReplayError, match="v8 M1d freeze link"):
        helper._chain_links((*inventories, v9))
    # ... and once it is recorded, v9 supersedes v8 and nothing else moves.
    grown = helper._chain_links(
        (*inventories[:-1], dataclasses.replace(tip, commit="1" * 40), v9)
    )
    assert grown[:-2] == helper.FREEZE_LINKS[:-1]
    assert grown[-1].superseded_id == "m1d-v8-protected-sha256"
    assert grown[-1].superseded_commit == "1" * 40
    assert [link.requires_current_role for link in grown] == [
        False,
        False,
        False,
        False,
        False,
        True,
    ]


def test_v7_records_the_commit_that_last_wrote_it_once_v8_supersedes_it() -> None:
    """Issue 71 appended v8 and closed v7 on b21efc5 (its last writer)."""
    helper = _load_replay_helper()
    v7 = helper._FREEZE_INVENTORIES[-2]
    assert v7.label == "v7"
    assert v7.commit == V7_INVENTORY_COMMIT
    assert helper._FREEZE_INVENTORIES[-1].commit is None
    assert helper._freeze_link("v8").superseded_commit == V7_INVENTORY_COMMIT


def test_v6_records_the_commit_that_last_wrote_it_once_v7_supersedes_it() -> None:
    """Issue 63 stage 2 appended v7 and closed v6 on a906ab2 (its last writer)."""
    helper = _load_replay_helper()
    v6 = helper._FREEZE_INVENTORIES[-3]
    assert v6.label == "v6"
    assert v6.commit == V6_INVENTORY_COMMIT
    assert helper._freeze_link("v7").superseded_commit == V6_INVENTORY_COMMIT


def test_freeze_chain_requires_a_hex_superseded_commit_and_a_link(
    tmp_path: Path,
) -> None:
    """A chain of only v3 raises, and a non-hex superseded commit fails closed."""
    helper = _load_replay_helper()
    inventories = helper._FREEZE_INVENTORIES
    with pytest.raises(
        helper.PinnedM1dReplayError, match="chain needs at least one link"
    ):
        helper._chain_links(inventories[:1])
    # A superseded commit that is not a git SHA is rejected, not trusted. A
    # shorter or longer hex string is accepted by shape; only non-hex, too
    # short, or too long fails.
    for junk in ("not-a-sha", "0" * 41, "XYZ123", "200bfe", ""):
        broken = (
            dataclasses.replace(inventories[2], commit=junk),
            *inventories[3:],
        )
        with pytest.raises(
            helper.PinnedM1dReplayError, match="v6 M1d freeze link is malformed"
        ):
            helper._chain_links((*inventories[:2], *broken))


def test_freeze_link_rejects_an_empty_or_no_op_supersession() -> None:
    """A link must move at least one pin, and never to the digest it replaces."""
    helper = _load_replay_helper()
    for label in FREEZE_LINK_ISSUES:
        empty = _link_document(helper, label)
        empty["superseded_paths"] = {}
        with pytest.raises(
            helper.PinnedM1dReplayError, match="inventory supersession is malformed"
        ):
            helper._validated_chain_pins(label, empty)

        no_op = _link_document(helper, label)
        path, record = next(iter(no_op["superseded_paths"].items()))
        no_op["superseded_paths"][path] = {
            "historical_sha256": record["historical_sha256"],
            "current_sha256": record["historical_sha256"],
        }
        no_op["sha256"][path] = record["historical_sha256"]
        with pytest.raises(
            helper.PinnedM1dReplayError,
            match=f"inventory supersession is malformed for {path}",
        ):
            helper._validated_chain_pins(label, no_op)


def test_archived_replay_still_authenticates_against_the_historical_pins() -> None:
    """Superseding the working-tree pins must not re-sign the af75cce archive."""
    helper = _load_replay_helper()
    historical = helper.PROTECTED_M1D_ARCHIVE_SHA256
    current = helper.PROTECTED_M1D_SHA256
    parent = historical
    for label, paths in FREEZE_LINK_SUPERSESSIONS.items():
        link = _link_document(helper, label)
        pins = helper.FREEZE_CHAIN_SHA256[label]
        assert set(pins) == set(parent) | set(link["added_paths"]), label
        assert not set(link["added_paths"]) & set(parent), label
        assert set(link["superseded_paths"]) == paths, label
        assert set(link["added_paths"]) == FREEZE_LINK_ADDITIONS[label], label
        parent = pins
    superseded = {
        path
        for path in historical
        if path in current and historical[path] != current[path]
    }
    assert superseded == {
        "src/drift/markets/observation_validation.py",
        "src/drift/markets/session_validation.py",
        IDENTITY_ACCESSOR_PATH,
        *M1C_STAMP_SITE_PATHS,
    }
    v4 = _link_document(helper, "v4")
    assert v4["supersedes"]["commit"] == helper.PINNED_M1D_COMMIT
    assert v4["supersedes"]["file_sha256"] == helper._EXPECTED_INVENTORY_SHA256
    v5 = _link_document(helper, "v5")
    assert v5["supersedes"]["commit"] == V4_INVENTORY_COMMIT
    assert v5["supersedes"]["file_sha256"] == helper._freeze_link("v4").file_sha256
    v6 = _link_document(helper, "v6")
    assert v6["supersedes"]["commit"] == V5_INVENTORY_COMMIT
    assert v6["supersedes"]["file_sha256"] == helper._freeze_link("v5").file_sha256
    v7 = _link_document(helper, "v7")
    assert v7["supersedes"]["commit"] == V6_INVENTORY_COMMIT
    assert v7["supersedes"]["file_sha256"] == helper._freeze_link("v6").file_sha256
    v8 = _link_document(helper, "v8")
    assert v8["supersedes"]["commit"] == V7_INVENTORY_COMMIT
    assert v8["supersedes"]["file_sha256"] == helper._freeze_link("v7").file_sha256


def test_current_inventory_pins_the_identity_defining_modules() -> None:
    """The files that define the evidence identity must themselves be pinned."""
    helper = _load_replay_helper()
    assert ATTESTATION_SOURCE_PATH not in helper.PROTECTED_M1D_ARCHIVE_SHA256
    for path in (ATTESTATION_SOURCE_PATH, IDENTITY_ACCESSOR_PATH):
        live = (helper.REPO_ROOT / path).read_bytes()
        assert helper.PROTECTED_M1D_SHA256[path] == hashlib.sha256(live).hexdigest()

    v4 = _link_document(helper, "v4")
    added = v4["added_paths"][ATTESTATION_SOURCE_PATH]
    assert added["issue"] == 32
    assert added["justification"].strip()
    v5 = _link_document(helper, "v5")
    assert v5["supersedes"]["issue"] == 63
    v5_record = v5["superseded_paths"][ATTESTATION_SOURCE_PATH]
    assert v5_record["historical_sha256"] == added["current_sha256"]
    v6 = _link_document(helper, "v6")
    assert v6["supersedes"]["issue"] == 107
    v6_record = v6["superseded_paths"][ATTESTATION_SOURCE_PATH]
    assert v6_record["historical_sha256"] == v5_record["current_sha256"]
    assert v6_record["historical_sha256"] == v5["sha256"][ATTESTATION_SOURCE_PATH]
    v7 = _link_document(helper, "v7")
    assert v7["supersedes"]["issue"] == 63
    v7_record = v7["superseded_paths"][ATTESTATION_SOURCE_PATH]
    assert v7_record["historical_sha256"] == v6_record["current_sha256"]
    assert v7_record["historical_sha256"] == v6["sha256"][ATTESTATION_SOURCE_PATH]
    for path in M1C_STAMP_SITE_PATHS:
        stamp = v7["superseded_paths"][path]
        assert stamp["historical_sha256"] == v6["sha256"][path], path
        live = (helper.REPO_ROOT / path).read_bytes()
        assert stamp["current_sha256"] == hashlib.sha256(live).hexdigest(), path
        assert helper.PROTECTED_M1D_SHA256[path] == stamp["current_sha256"], path
    v8 = _link_document(helper, "v8")
    assert v8["supersedes"]["issue"] == 71
    record = v8["superseded_paths"][ATTESTATION_SOURCE_PATH]
    assert record["historical_sha256"] == v7_record["current_sha256"]
    assert record["historical_sha256"] == v7["sha256"][ATTESTATION_SOURCE_PATH]
    pinned = helper.PROTECTED_M1D_SHA256[ATTESTATION_SOURCE_PATH]
    assert record["current_sha256"] == pinned
    # Issue 71 brings the two closed-world modules under the freeze.
    for path in CLOSED_WORLD_SOURCE_PATHS:
        assert path not in v7["sha256"], path
        added = v8["added_paths"][path]
        assert added["issue"] == 71
        assert added["justification"].strip()
        live = (helper.REPO_ROOT / path).read_bytes()
        assert added["current_sha256"] == hashlib.sha256(live).hexdigest(), path
        assert helper.PROTECTED_M1D_SHA256[path] == added["current_sha256"], path

    # The pins are load-bearing, not decorative: a changed byte is rejected.
    helper.verify_m1d_protected_inputs(root=helper.REPO_ROOT)
    for path in (ATTESTATION_SOURCE_PATH, IDENTITY_ACCESSOR_PATH):
        tampered = dict(helper.PROTECTED_M1D_SHA256)
        tampered[path] = "0" * 64
        with pytest.raises(helper.PinnedM1dReplayError, match="sha256 mismatch for"):
            helper.verify_m1d_protected_inputs(root=helper.REPO_ROOT, expected=tampered)


def test_current_pins_are_re_derived_through_every_link() -> None:
    """v3, then the issue 32, 63, 107, 63 and 71 deltas in order, and nothing else."""
    helper = _load_replay_helper()
    expected = dict(helper.PROTECTED_M1D_ARCHIVE_SHA256)
    for label in FREEZE_LINK_ISSUES:
        link = _link_document(helper, label)
        for relative, record in link["superseded_paths"].items():
            assert expected[relative] == record["historical_sha256"], relative
            expected[relative] = record["current_sha256"]
        for relative, record in link["added_paths"].items():
            assert relative not in expected, relative
            expected[relative] = record["current_sha256"]
        assert link["sha256"] == expected
        assert helper._validated_chain_pins(label, link) == expected, label
        assert helper.FREEZE_CHAIN_SHA256[label] == expected, label
    assert expected == helper.PROTECTED_M1D_SHA256


def test_current_inventory_cannot_pin_an_undeclared_added_path() -> None:
    """A new path may only enter the current pins through an explicit addition."""
    helper = _load_replay_helper()
    document = _link_document(helper, "v8")

    smuggled = json.loads(json.dumps(document))
    smuggled["sha256"]["src/drift/domain/replay_provenance.py"] = "0" * 64
    with pytest.raises(
        helper.PinnedM1dReplayError, match="pins an undeclared added path"
    ):
        helper._validated_chain_pins("v8", smuggled)

    for dropped_path in (
        ATTESTATION_SOURCE_PATH,
        IDENTITY_ACCESSOR_PATH,
        *sorted(CLOSED_WORLD_SOURCE_PATHS),
    ):
        dropped = json.loads(json.dumps(document))
        del dropped["sha256"][dropped_path]
        with pytest.raises(
            helper.PinnedM1dReplayError, match="omits a required protected path"
        ):
            helper._validated_chain_pins("v8", dropped)
    # An addition's pin is held to its declaration like any other pin.
    for added_path in sorted(CLOSED_WORLD_SOURCE_PATHS):
        resigned = json.loads(json.dumps(document))
        resigned["sha256"][added_path] = "3" * 64
        with pytest.raises(
            helper.PinnedM1dReplayError, match="re-signs undeclared protected paths"
        ):
            helper._validated_chain_pins("v8", resigned)
        undeclared = json.loads(json.dumps(document))
        del undeclared["added_paths"][added_path]
        with pytest.raises(
            helper.PinnedM1dReplayError, match="pins an undeclared added path"
        ):
            helper._validated_chain_pins("v8", undeclared)


def test_inventory_additions_require_their_own_link_justification() -> None:
    """An addition is admitted by declaration, not merely by being different."""
    helper = _load_replay_helper()
    document = _link_document(helper, "v4")

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
            helper._validated_chain_pins("v4", broken)

    stripped = json.loads(json.dumps(document))
    del stripped["added_paths"][ATTESTATION_SOURCE_PATH]["justification"]
    with pytest.raises(helper.PinnedM1dReplayError, match="addition is malformed"):
        helper._validated_chain_pins("v4", stripped)

    listed = json.loads(json.dumps(document))
    listed["added_paths"] = [ATTESTATION_SOURCE_PATH]
    with pytest.raises(
        helper.PinnedM1dReplayError, match="addition block is malformed"
    ):
        helper._validated_chain_pins("v4", listed)

    # A later link's addition is admitted only under that link's own issue,
    # with its own justification, never under its predecessor's issue.
    target = "src/drift/domain/replay_provenance.py"
    for label, issue, predecessor_issue in (
        ("v5", 63, 32),
        ("v6", 107, 63),
        ("v7", 63, 107),
        ("v8", 71, 63),
    ):
        addition = {
            "current_sha256": "0" * 64,
            "issue": issue,
            "justification": "pinned",
        }
        widened = json.loads(json.dumps(_link_document(helper, label)))
        widened["added_paths"][target] = dict(addition)
        widened["sha256"][target] = "0" * 64
        assert target in helper._validated_chain_pins(label, widened)
        link_mutations: tuple[dict[str, object], ...] = (
            {"issue": predecessor_issue},
            {"justification": ""},
        )
        for link_mutation in link_mutations:
            broken = json.loads(json.dumps(widened))
            broken["added_paths"][target].update(link_mutation)
            with pytest.raises(
                helper.PinnedM1dReplayError, match="addition is malformed"
            ):
                helper._validated_chain_pins(label, broken)


def test_inventory_addition_cannot_shadow_a_pin_of_the_superseded_inventory() -> None:
    """The addition channel must not become a second way to re-sign history."""
    helper = _load_replay_helper()
    target = "src/drift/domain/temporal.py"
    for label, issue in FREEZE_LINK_ISSUES.items():
        shadowed = _link_document(helper, label)
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
            helper._validated_chain_pins(label, shadowed)


def test_current_inventory_cannot_re_sign_an_undeclared_protected_path() -> None:
    """Only the paths a link's supersession names may differ from its parent."""
    helper = _load_replay_helper()
    for label, target in (
        ("v4", "src/drift/markets/session_validation.py"),
        ("v5", IDENTITY_ACCESSOR_PATH),
        ("v6", ATTESTATION_SOURCE_PATH),
        ("v7", "src/drift/markets/economic_outcomes.py"),
        ("v8", ATTESTATION_SOURCE_PATH),
    ):
        document = _link_document(helper, label)
        smuggled = json.loads(json.dumps(document))
        smuggled["sha256"]["src/drift/domain/temporal.py"] = "0" * 64
        with pytest.raises(
            helper.PinnedM1dReplayError, match="re-signs undeclared protected paths"
        ):
            helper._validated_chain_pins(label, smuggled)

        misstated = json.loads(json.dumps(document))
        misstated["superseded_paths"][target]["historical_sha256"] = "1" * 64
        with pytest.raises(
            helper.PinnedM1dReplayError, match="misstates the superseded pin"
        ):
            helper._validated_chain_pins(label, misstated)

        # Editing a declared pin without its supersession record is a re-sign.
        edited = json.loads(json.dumps(document))
        edited["sha256"][target] = "2" * 64
        with pytest.raises(
            helper.PinnedM1dReplayError, match="re-signs undeclared protected paths"
        ):
            helper._validated_chain_pins(label, edited)


def test_current_inventory_cannot_supersede_a_path_its_parent_does_not_pin() -> None:
    """A path the previous link never pinned enters only as an addition."""
    helper = _load_replay_helper()
    document = _link_document(helper, "v8")
    target = "src/drift/domain/replay_provenance.py"
    document["superseded_paths"][target] = {
        "historical_sha256": "1" * 64,
        "current_sha256": "2" * 64,
    }
    document["sha256"][target] = "2" * 64
    with pytest.raises(helper.PinnedM1dReplayError, match="supersedes an unpinned"):
        helper._validated_chain_pins("v8", document)


def test_current_inventory_must_name_the_exact_inventory_it_supersedes() -> None:
    """Each link names its exact predecessor; naming an older one fails.

    v5 is a link from v4 at 4ad90aa under issue 63, v6 is a link from v5 at
    200bfeb under issue 107, v7 is a link from v6 at a906ab2 under issue 63, and
    v8 is a link from v7 at b21efc5 under issue 71.
    """
    helper = _load_replay_helper()
    v3_path = helper._INVENTORY_PATH.relative_to(helper.REPO_ROOT).as_posix()
    v4 = helper._freeze_link("v4")
    v4_path = v4.path.relative_to(helper.REPO_ROOT).as_posix()
    v5 = helper._freeze_link("v5")
    v5_path = v5.path.relative_to(helper.REPO_ROOT).as_posix()
    v6 = helper._freeze_link("v6")
    v6_path = v6.path.relative_to(helper.REPO_ROOT).as_posix()
    wrong_predecessors: dict[str, tuple[dict[str, object], ...]] = {
        "v5": (
            {"inventory_id": "m1d-v3-protected-sha256"},
            {"path": v3_path},
            {"file_sha256": helper._EXPECTED_INVENTORY_SHA256},
            {"commit": helper.PINNED_M1D_COMMIT},
            {"issue": 32},
        ),
        "v6": (
            {"inventory_id": "m1d-v4-protected-sha256"},
            {"path": v4_path},
            {"file_sha256": v4.file_sha256},
            {"commit": V4_INVENTORY_COMMIT},
            {"issue": 63},
        ),
        "v7": (
            {"inventory_id": "m1d-v5-protected-sha256"},
            {"path": v5_path},
            {"file_sha256": v5.file_sha256},
            {"commit": V5_INVENTORY_COMMIT},
            {"issue": 107},
        ),
        "v8": (
            {"inventory_id": "m1d-v6-protected-sha256"},
            {"path": v6_path},
            {"file_sha256": v6.file_sha256},
            {"commit": V6_INVENTORY_COMMIT},
            {"issue": 63},
        ),
    }
    for label, supersession_mutations in wrong_predecessors.items():
        document = _link_document(helper, label)
        for mutation in (*supersession_mutations, {"reason": "  "}, {"status": ""}):
            broken = json.loads(json.dumps(document))
            broken["supersedes"].update(mutation)
            with pytest.raises(
                helper.PinnedM1dReplayError,
                match="inventory supersession is malformed",
            ):
                helper._validated_chain_pins(label, broken)
        predecessor_id = helper._freeze_link(label).superseded_id
        for key, value in (
            ("inventory_id", predecessor_id),
            ("baseline_commit", "0" * 40),
        ):
            broken = json.loads(json.dumps(document))
            broken[key] = value
            with pytest.raises(
                helper.PinnedM1dReplayError, match="inventory is malformed"
            ):
                helper._validated_chain_pins(label, broken)
    # Only the tip must still call itself current.
    tip = _link_document(helper, "v8")
    tip["role"] = "historical"
    with pytest.raises(helper.PinnedM1dReplayError, match="inventory is malformed"):
        helper._validated_chain_pins("v8", tip)
    superseded = _link_document(helper, "v7")
    superseded["role"] = "historical"
    assert (
        helper._validated_chain_pins("v7", superseded)
        == (helper.FREEZE_CHAIN_SHA256["v7"])
    )


def test_an_edited_link_inventory_is_rejected_although_v8_is_current(
    tmp_path: Path,
) -> None:
    """History stays byte-identical: an edited link cannot anchor the chain."""
    helper = _load_replay_helper()
    for label in FREEZE_LINK_ISSUES:
        link = helper._freeze_link(label)
        edited = tmp_path / link.path.name
        edited.write_bytes(link.path.read_bytes() + b"\n")
        with pytest.raises(
            helper.PinnedM1dReplayError,
            match=f"{label} M1d inventory sha256 mismatch",
        ):
            helper._load_link_document(dataclasses.replace(link, path=edited))


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
