"""Synthetic-only recovery evidence vectors for #520 verification."""

from __future__ import annotations

from typing import cast

import pytest

from scripts.recovery_evidence_preflight import preflight_recovery_evidence

HASH = "b" * 64
COMMIT = "a" * 40


def fixture(target: str = "FEATURE_OFF") -> dict[str, object]:
    record: dict[str, object] = {
        "target": target,
        "run_id": "synthetic-run-1",
        "manifest_id": "synthetic-manifest-1",
        "manifest_sha256": HASH,
        "grant_ref": "synthetic-grant",
        "grant_verification_receipt_ref": "separate-grant-witness",
        "mechanism_author": "builder",
        "independent_verifier": "separate-reviewer",
        "independent_review_ref": "external-review",
        "external_custody_anchor_ref": "external-anchor",
        "append_only_lineage_ref": "retained-history",
        "execution_hold_state": "CLEAR",
        "components": {
            name: {
                "status": "passed",
                "receipt_ref": f"distinct-{name}",
                "revision_ref": "original-tree-and-policy",
                "environment_ref": "isolated-environment",
                "manifest_sha256": HASH,
            }
            for name in ("CODE", "PRIVATE_STATE", "RUNTIME")
        },
    }
    if target == "FEATURE_OFF":
        record.update(
            corrected_kernel_commit=COMMIT,
            corrected_kernel_acceptance_ref="separate-kernel-review",
            feature_config_sha256=HASH,
            current_state_receipt_ref="existing-current-state",
            supported_path_receipt_ref="supported-config-path",
        )
    elif target == "ISOLATED_ORIGINAL":
        record.update(
            historical_tree_commit=COMMIT,
            custodian_ref="private-archive-custodian-reference",
            isolation_destination_receipt_ref="canonical-destination-witness",
            snapshot_consistency_receipt_ref="transaction-consistency",
            historical_runtime_pin_ref="original-dependencies",
            original_scope_ref="original-state-inventory",
        )
    elif target == "FROZEN_CONTROL":
        record.update(
            corrected_kernel_commit=COMMIT,
            corrected_kernel_acceptance_ref="separate-kernel-review",
            frozen_policy_sha256=HASH,
            arm_account_isolation_receipt_ref="distinct-A-account",
            comparability_receipt_ref="same-kernel-rules",
            frozen_arm="A",
        )
    return record


@pytest.mark.parametrize(
    "target",
    ["FEATURE_OFF", "ISOLATED_ORIGINAL", "FROZEN_CONTROL"],
)
def test_complete_synthetic_record_is_only_reviewable(target: str) -> None:
    verdict = preflight_recovery_evidence(fixture(target))
    assert verdict.structurally_reviewable
    assert verdict.reasons == ()
    assert not verdict.authorizes_recovery_or_execution


def test_untrusted_non_plain_object_refused() -> None:
    assert not preflight_recovery_evidence([fixture()]).structurally_reviewable


def test_original_private_state_absent_cannot_be_restored() -> None:
    item = fixture("ISOLATED_ORIGINAL")
    dimensions = cast(dict[str, object], item["components"])
    state = cast(dict[str, object], dimensions["PRIVATE_STATE"])
    state["status"] = "unavailable"
    assert (
        "PRIVATE_STATE.status.not_passed" in preflight_recovery_evidence(item).reasons
    )


def test_missing_transactional_snapshot_ref_refused() -> None:
    item = fixture("ISOLATED_ORIGINAL")
    item.pop("snapshot_consistency_receipt_ref")
    assert (
        "snapshot_consistency_receipt_ref.missing"
        in preflight_recovery_evidence(item).reasons
    )


def test_self_review_is_not_independence() -> None:
    item = fixture()
    item["independent_verifier"] = "builder"
    assert (
        "independent_verifier.self_review" in preflight_recovery_evidence(item).reasons
    )


def test_component_manifest_mismatch_fails_closed() -> None:
    item = fixture()
    components = cast(dict[str, object], item["components"])
    runtime = cast(dict[str, object], components["RUNTIME"])
    runtime["manifest_sha256"] = "c" * 64
    assert "RUNTIME.manifest_mismatch" in preflight_recovery_evidence(item).reasons


def test_same_receipt_is_not_three_independent_dimensions() -> None:
    item = fixture()
    components = cast(dict[str, object], item["components"])
    runtime = cast(dict[str, object], components["RUNTIME"])
    runtime["receipt_ref"] = "distinct-CODE"
    assert (
        "RUNTIME.receipt_reused_across_dimensions"
        in preflight_recovery_evidence(item).reasons
    )


def test_hold_not_cleared_by_preflight() -> None:
    item = fixture()
    item["execution_hold_state"] = "UNKNOWN"
    result = preflight_recovery_evidence(item)
    assert "execution_hold_state.not_resolved_for_resumption" in result.reasons
    assert not result.authorizes_recovery_or_execution


def test_frozen_control_is_arm_a_not_campaign_c() -> None:
    item = fixture("FROZEN_CONTROL")
    item["frozen_arm"] = "C"
    assert "frozen_control.requires_arm_A" in preflight_recovery_evidence(item).reasons


def test_unhashable_nested_status_is_refused_not_raised() -> None:
    item = fixture()
    components = cast(dict[str, object], item["components"])
    code = cast(dict[str, object], components["CODE"])
    code["status"] = {"unexpected": "passed"}
    assert "CODE.status.invalid" in preflight_recovery_evidence(item).reasons


def test_unverified_manifest_hash_rejected() -> None:
    item = fixture()
    item["manifest_sha256"] = "123"
    assert "manifest_sha256.invalid" in preflight_recovery_evidence(item).reasons


def _hostile_scalar(kind: str, text: str, callbacks: list[str]) -> object:
    class Hostile:
        def __eq__(self, _: object) -> bool:
            callbacks.append("equality")
            raise AssertionError("untrusted scalar equality invoked")

        def __ne__(self, _: object) -> bool:
            callbacks.append("inequality")
            raise AssertionError("untrusted scalar inequality invoked")

        def __hash__(self) -> int:
            callbacks.append("hash")
            raise AssertionError("untrusted scalar hash invoked")

    class HostileText(Hostile, str):
        pass

    return HostileText(text) if kind == "string_subclass" else Hostile()


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("target", "target.invalid"),
        ("execution_hold_state", "execution_hold_state.invalid"),
        ("independent_verifier", "independent_verifier.missing"),
        ("mechanism_author", "mechanism_author.missing"),
        ("manifest_sha256", "manifest_sha256.invalid"),
        ("frozen_arm", "frozen_arm.missing"),
    ],
)
@pytest.mark.parametrize("kind", ["object", "string_subclass"])
def test_malformed_root_scalars_refuse_without_attacker_callbacks(
    field: str, reason: str, kind: str
) -> None:
    item = fixture("FROZEN_CONTROL")
    callbacks: list[str] = []
    item[field] = _hostile_scalar(kind, cast(str, item[field]), callbacks)
    report = preflight_recovery_evidence(item)
    assert not report.structurally_reviewable
    assert reason in report.reasons
    assert report.authorizes_recovery_or_execution is False
    assert callbacks == []


@pytest.mark.parametrize("dimension", ["CODE", "PRIVATE_STATE", "RUNTIME"])
@pytest.mark.parametrize(
    ("field", "suffix"),
    [
        ("status", "status.invalid"),
        ("receipt_ref", "receipt_ref.missing"),
        ("manifest_sha256", "manifest_sha256.invalid"),
    ],
)
@pytest.mark.parametrize("kind", ["object", "string_subclass"])
def test_malformed_component_scalars_refuse_without_attacker_callbacks(
    dimension: str, field: str, suffix: str, kind: str
) -> None:
    item = fixture()
    components = cast(dict[str, object], item["components"])
    entry = cast(dict[str, object], components[dimension])
    callbacks: list[str] = []
    entry[field] = _hostile_scalar(kind, cast(str, entry[field]), callbacks)
    report = preflight_recovery_evidence(item)
    assert not report.structurally_reviewable
    assert f"{dimension}.{suffix}" in report.reasons
    assert report.authorizes_recovery_or_execution is False
    assert callbacks == []


@pytest.mark.parametrize(
    "target", ["FEATURE_OFF", "ISOLATED_ORIGINAL", "FROZEN_CONTROL"]
)
@pytest.mark.parametrize("hold", ["HELD", "UNKNOWN"])
def test_all_valid_targets_preserve_unresolved_hold_refusal(
    target: str, hold: str
) -> None:
    item = fixture(target)
    item["execution_hold_state"] = hold
    report = preflight_recovery_evidence(item)
    assert not report.structurally_reviewable
    assert report.reasons == ("execution_hold_state.not_resolved_for_resumption",)
    assert report.authorizes_recovery_or_execution is False
