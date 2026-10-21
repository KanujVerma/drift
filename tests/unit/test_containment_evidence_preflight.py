"""Synthetic-only, unrun AntiGravity test vectors for #521."""

from __future__ import annotations

from typing import cast

from scripts.containment_evidence_preflight import (
    preflight_containment_evidence,
)

HASH = "d" * 64
COMMIT = "e" * 40


def fixture() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for i in range(1, 12):
        name = f"A{i:02}"
        case: dict[str, object] = {
            "case_id": name,
            "denial_status": "passed",
            "control_status": "passed",
            "denial_receipt_ref": f"outside-enforcer-denial-{name}",
            "control_receipt_ref": f"outside-enforcer-control-{name}",
            "enforcer_path_ref": "same-policy-engine",
            "environment_ref": "synthetic-env-id",
            "evidence_origin": "independent_enforcer",
        }
        if name in ("A01", "A11"):
            case["independent_before_after_anchor_ref"] = f"outside-anchor-{name}"
        if name == "A07":
            case["direct_alternate_path_denial_receipt_ref"] = "alternate-client"
        if name == "A08":
            case["control_kind"] = "offline_local_fixture"
            case["egress_policy_denial_receipt_ref"] = "mock-egress-denial"
        if name == "A10":
            case["no_unconfined_retry_receipt_ref"] = "synthetic-retry-refusal"
        cases.append(case)

    return {
        "run_id": "synthetic-run-only",
        "environment_ref": "synthetic-env-id",
        "sandbox_image_ref": "proposed-build-id",
        "grant_verification_receipt_ref": "independent-grant-proof",
        "capability_inventory_ref": "complete-declared-tools",
        "network_policy_receipt_ref": "offline-egress-profile",
        "trusted_enforcer_ref": "separately-controlled-enforcer",
        "external_enforcer_receipt_ref": "external-policy-check",
        "mechanism_author": "mechanism-author",
        "independent_verifier": "independent-reviewer",
        "independent_review_ref": "signed-offline-review-reference",
        "independent_custody_anchor_ref": "original-anchor",
        "source_commit": COMMIT,
        "policy_sha256": HASH,
        "network_profile": "offline",
        "unconfined_fallback": "refused",
        "evidence_origin": "independent_enforcer",
        "cases": cases,
    }


def _cases(item: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], item["cases"])


def test_complete_claim_is_only_reviewable_not_authorization() -> None:
    verdict = preflight_containment_evidence(fixture())
    assert verdict.structurally_reviewable
    assert verdict.reasons == ()
    assert not verdict.authorizes_worker_launch


def test_missing_denial_case_not_silently_ignored() -> None:
    item = fixture()
    _cases(item).pop()
    assert "A11.missing" in preflight_containment_evidence(item).reasons


def test_duplicate_case_id_refused() -> None:
    item = fixture()
    _cases(item).append(_cases(item)[0].copy())
    assert "A01.duplicate" in preflight_containment_evidence(item).reasons


def test_positive_only_is_not_confinement() -> None:
    item = fixture()
    _cases(item)[0]["denial_status"] = "not_run"
    assert "A01.denial_status.not_passed" in preflight_containment_evidence(
        item
    ).reasons


def test_denial_only_broken_fixture_cannot_count_as_pass() -> None:
    item = fixture()
    _cases(item)[1]["control_status"] = "failed"
    assert "A02.control_status.not_passed" in preflight_containment_evidence(
        item
    ).reasons


def test_worker_self_attestation_refused() -> None:
    item = fixture()
    _cases(item)[6]["evidence_origin"] = "worker"
    assert "A07.worker_claim_not_enforcement_proof" in (
        preflight_containment_evidence(item).reasons
    )


def test_a07_requires_real_alternate_enforcement_path_receipt() -> None:
    item = fixture()
    _cases(item)[6].pop("direct_alternate_path_denial_receipt_ref")
    assert "A07.direct_alternate_path_receipt.missing" in (
        preflight_containment_evidence(item).reasons
    )


def test_a08_offline_profile_does_not_take_network_positive_control() -> None:
    item = fixture()
    _cases(item)[7]["control_kind"] = "real_external_network"
    assert "A08.offline_control_kind.invalid" in (
        preflight_containment_evidence(item).reasons
    )


def test_unconfined_fallback_refused() -> None:
    item = fixture()
    item["unconfined_fallback"] = "retry_on_host"
    assert "unconfined_fallback.not_refused" in (
        preflight_containment_evidence(item).reasons
    )


def test_a11_requires_independent_store_anchor() -> None:
    item = fixture()
    _cases(item)[10].pop("independent_before_after_anchor_ref")
    assert "A11.independent_anchor.missing" in (
        preflight_containment_evidence(item).reasons
    )


def test_mismatched_environment_and_self_review() -> None:
    item = fixture()
    _cases(item)[4]["environment_ref"] = "other-env"
    item["independent_verifier"] = "mechanism-author"
    reasons = preflight_containment_evidence(item).reasons
    assert "A05.environment_mismatch" in reasons
    assert "independent_verifier.self_review" in reasons


def test_unhashable_nested_status_is_refused_not_raised() -> None:
    item = fixture()
    _cases(item)[0]["denial_status"] = {"claim": "passed"}
    assert "A01.denial_status.invalid" in preflight_containment_evidence(
        item
    ).reasons


def test_incomplete_evidence_never_authorizes_launch() -> None:
    item = fixture()
    item["cases"] = "I passed all probes"
    verdict = preflight_containment_evidence(item)
    assert not verdict.structurally_reviewable
    assert not verdict.authorizes_worker_launch
