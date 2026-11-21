"""Synthetic forward readiness review vectors for #537."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from scripts.forward_readiness_preflight import (
    _MODES,
    preflight_forward_readiness,
)


def fixture(mode: str = "LOCAL_SHADOW", arm_count: int = 2) -> dict[str, object]:
    dimensions, contracts, credential_mode = _MODES[mode]
    packet: dict[str, object] = {
        "profile": "synthetic-forward-readiness-review-v1",
        "mode": mode,
        "as_of_utc": "2026-10-20T18:00:00Z",
        "campaign_ref": "mock-immutable-campaign",
        "requested_arm_count": arm_count,
        "accounts": [
            {
                "arm_id": f"arm-{i}",
                "account_id": f"mock-original-account-{i}",
                "environment_ref": "test-environment",
                "original_allocation_receipt_ref": f"mock-original-book-{i}",
                "allocation_issuer_ref": "unverified-issuer",
                "external_account_ref": (
                    f"unverified-{mode.lower()}-account-{i}"
                    if mode != "LOCAL_SHADOW"
                    else None
                ),
            }
            for i in range(arm_count)
        ],
        "dimensions": {
            name: {
                "claim": "CLAIMED_COMPLETE",
                "evidence_ref": f"mock-evidence-{name}",
                "scope_ref": "mock-immutable-campaign",
                "first_available_utc": "2026-10-20T16:00:00Z",
                "producer_ref": f"mock-producer-{name}",
                "independent_review_ref": f"unverified-reviewer-{name}",
            }
            for name in dimensions
        },
        "contracts": {
            name: {
                "claim": "CLAIMED_ACCEPTED",
                "accepted_revision_ref": f"fictional-contract-revision-{name}",
                "review_ref": f"unverified-contract-review-{name}",
            }
            for name in contracts
        },
        "feed_state": "CLAIMED_COMPLETE",
        "account_hold": "CLAIMED_CLEAR",
        "credential_mode": credential_mode,
        "operation_grant": None,
        "reviews": {
            "producer_ref": "mock-producer",
            "source_custodian_ref": "unverified-source-custodian",
            "independent_reviewer_ref": "mock-independent-reviewer",
            "independent_review_receipt_ref": "unverified-review-receipt",
        },
    }
    if mode != "LOCAL_SHADOW":
        packet["operation_grant"] = {
            "issuer_ref": "unverified-operational-issuer",
            "issuer_verification_ref": "mock-unverified-issuer-proof",
            "scope_ref": "mock-immutable-campaign",
            "principal_ref": "mock-execution-principal",
            "not_before_utc": "2026-10-20T17:00:00Z",
            "expires_utc": "2026-10-20T19:00:00Z",
            "revoked": False,
            "purpose": mode,
        }
    return packet


def _map(packet: dict[str, object], field: str) -> dict[str, object]:
    return cast(dict[str, object], packet[field])


def _accounts(packet: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], packet["accounts"])


def _refuse(packet: dict[str, object], expected: str) -> None:
    result = preflight_forward_readiness(packet)
    assert not result.structurally_reviewable
    assert result.claimed_distinct_account_count is None
    assert expected in result.reasons
    assert not result.authorizes_provider_connection
    assert not result.authorizes_paper_live_or_deployment
    assert not result.proves_real_account_entitlement


@pytest.mark.parametrize("mode", ["LOCAL_SHADOW", "CONNECTED_PAPER", "LIVE"])
def test_complete_mock_packet_remains_non_authoritative(mode: str) -> None:
    packet = fixture(mode)
    report = preflight_forward_readiness(packet)
    assert report.structurally_reviewable
    assert report.checked_mode == mode
    assert report.claimed_distinct_account_count == 2
    assert report.missing_or_unaccepted_dimensions == ()
    assert report.unresolved_contracts == ()
    assert report.reasons == ()
    assert not report.authorizes_provider_connection
    assert not report.authorizes_paper_live_or_deployment
    assert not report.proves_real_account_entitlement


def test_five_separate_paper_accounts_are_only_five_unverified_claims() -> None:
    packet = fixture("CONNECTED_PAPER", 5)
    result = preflight_forward_readiness(packet)
    assert result.structurally_reviewable
    assert result.claimed_distinct_account_count == 5
    assert not result.proves_real_account_entitlement


@pytest.mark.parametrize("mode", ["LOCAL_SHADOW", "CONNECTED_PAPER", "LIVE"])
@pytest.mark.parametrize("different_issuers", [False, True])
def test_repeated_allocation_receipt_cannot_claim_five_independent_accounts(
    mode: str, different_issuers: bool
) -> None:
    packet = fixture(mode, 5)
    for index, account in enumerate(_accounts(packet)):
        account["original_allocation_receipt_ref"] = "one-original-receipt"
        if different_issuers:
            account["allocation_issuer_ref"] = f"different-unverified-issuer-{index}"
    before = deepcopy(packet)
    _refuse(packet, "accounts.1.duplicate_original_allocation_receipt")
    result = preflight_forward_readiness(packet)
    assert result.checked_mode == mode
    assert result.missing_or_unaccepted_dimensions == ()
    assert result.unresolved_contracts == ()
    assert result.reasons == tuple(
        f"accounts.{index}.duplicate_original_allocation_receipt"
        for index in range(1, 5)
    )
    assert packet == before


@pytest.mark.parametrize("mode", ["LOCAL_SHADOW", "CONNECTED_PAPER", "LIVE"])
@pytest.mark.parametrize(("first", "second"), [(0, 1), (0, 4), (2, 4)])
def test_single_repeated_receipt_refuses_even_among_other_distinct_accounts(
    mode: str, first: int, second: int
) -> None:
    packet = fixture(mode, 5)
    accounts = _accounts(packet)
    accounts[second]["original_allocation_receipt_ref"] = accounts[first][
        "original_allocation_receipt_ref"
    ]
    _refuse(packet, f"accounts.{second}.duplicate_original_allocation_receipt")


@pytest.mark.parametrize("mode", ["LOCAL_SHADOW", "CONNECTED_PAPER", "LIVE"])
def test_distinct_receipts_under_same_issuer_remain_unverified_claims(
    mode: str,
) -> None:
    packet = fixture(mode, 5)
    accounts = _accounts(packet)
    assert (
        len({account["original_allocation_receipt_ref"] for account in accounts}) == 5
    )
    assert len({account["allocation_issuer_ref"] for account in accounts}) == 1
    before = deepcopy(packet)
    result = preflight_forward_readiness(packet)
    assert result.structurally_reviewable
    assert result.checked_mode == mode
    assert result.claimed_distinct_account_count == 5
    assert result.reasons == ()
    assert result.missing_or_unaccepted_dimensions == ()
    assert result.unresolved_contracts == ()
    assert result == preflight_forward_readiness(deepcopy(packet))
    assert packet == before
    assert not result.authorizes_provider_connection
    assert not result.authorizes_paper_live_or_deployment
    assert not result.proves_real_account_entitlement


@pytest.mark.parametrize("mode", ["LOCAL_SHADOW", "CONNECTED_PAPER", "LIVE"])
def test_receipt_subclasses_refuse_without_hash_or_equality_callbacks(
    mode: str,
) -> None:
    class HostileReceipt(str):
        def __hash__(self) -> int:
            raise AssertionError("untrusted receipt hash invoked")

        def __eq__(self, _: object) -> bool:
            raise AssertionError("untrusted receipt equality invoked")

    packet = fixture(mode)
    _accounts(packet)[1]["original_allocation_receipt_ref"] = HostileReceipt(
        "mock-original-book-0"
    )
    _refuse(packet, "payload.not_plain_json")


def test_five_paper_aliases_do_not_prove_five_independent_accounts() -> None:
    packet = fixture("CONNECTED_PAPER", 5)
    _accounts(packet)[4]["external_account_ref"] = _accounts(packet)[0][
        "external_account_ref"
    ]
    _refuse(packet, "accounts.4.duplicate_external_account")


def test_cross_arm_reused_original_account_refuses() -> None:
    packet = fixture()
    _accounts(packet)[1]["account_id"] = _accounts(packet)[0]["account_id"]
    _refuse(packet, "accounts.1.duplicate_account_alias")


def test_unknown_original_allocation_never_defaults_to_new_account() -> None:
    packet = fixture()
    _accounts(packet)[0]["original_allocation_receipt_ref"] = ""
    _refuse(packet, "accounts.0.original_allocation_receipt_ref.missing")


def test_miscounted_arms_and_duplicate_arm_are_not_separate_accounts() -> None:
    packet = fixture()
    packet["requested_arm_count"] = 3
    _refuse(packet, "accounts.count_mismatch")
    packet = fixture()
    _accounts(packet)[1]["arm_id"] = _accounts(packet)[0]["arm_id"]
    _refuse(packet, "accounts.1.duplicate_arm")


def test_local_shadow_does_not_gain_external_creds_or_paper_account() -> None:
    packet = fixture()
    packet["credential_mode"] = "EXTERNAL_CUSTODY_ASSERTED"
    _refuse(packet, "credential_mode.invalid_for_mode")
    packet = fixture()
    _accounts(packet)[0]["external_account_ref"] = "unapproved-paper"
    _refuse(packet, "accounts.0.external_account_not_local")


def test_connected_paper_has_no_automatic_operation_permission() -> None:
    packet = fixture("CONNECTED_PAPER")
    packet["operation_grant"] = None
    _refuse(packet, "operation_grant.not_plain_object")
    packet = fixture("CONNECTED_PAPER")
    _map(packet, "operation_grant")["purpose"] = "LIVE"
    _refuse(packet, "operation_grant.purpose_mismatch")


def test_live_must_keep_separate_scope_not_borrow_paper_grant() -> None:
    packet = fixture("LIVE")
    _map(packet, "operation_grant")["purpose"] = "CONNECTED_PAPER"
    _refuse(packet, "operation_grant.purpose_mismatch")


def test_expired_revoked_or_future_grant_is_no_evidence_of_permission() -> None:
    packet = fixture("CONNECTED_PAPER")
    _map(packet, "operation_grant")["expires_utc"] = packet["as_of_utc"]
    _refuse(packet, "operation_grant.outside_claimed_window")
    packet = fixture("CONNECTED_PAPER")
    _map(packet, "operation_grant")["revoked"] = True
    _refuse(packet, "operation_grant.revoked_or_unknown")
    packet = fixture("CONNECTED_PAPER")
    _map(packet, "operation_grant")["not_before_utc"] = "2026-10-20T18:30:00Z"
    _refuse(packet, "operation_grant.outside_claimed_window")


def test_all_synthetic_contract_labels_still_are_not_authentic_approvals() -> None:
    packet = fixture("LIVE")
    report = preflight_forward_readiness(packet)
    assert report.structurally_reviewable
    assert not report.authorizes_paper_live_or_deployment
    assert not report.authorizes_provider_connection


def test_specific_missing_contract_is_reported_as_unresolved() -> None:
    packet = fixture()
    _map(_map(packet, "contracts"), "m_sources_378")["claim"] = "DRAFT_ONLY"
    report = preflight_forward_readiness(packet)
    assert not report.structurally_reviewable
    assert "m_sources_378" in report.unresolved_contracts
    assert "contracts.unaccepted_or_unknown" in report.reasons


def test_missing_rights_and_cost_evidence_remain_separate_gaps() -> None:
    packet = fixture()
    _map(_map(packet, "dimensions"), "source_use_and_retention")["claim"] = "UNKNOWN"
    _map(_map(packet, "dimensions"), "cost_attribution")["claim"] = "UNKNOWN"
    report = preflight_forward_readiness(packet)
    assert not report.structurally_reviewable
    assert "source_use_and_retention" in report.missing_or_unaccepted_dimensions
    assert "cost_attribution" in report.missing_or_unaccepted_dimensions
    assert "dimensions.unresolved" in report.reasons


def test_feed_outage_or_held_account_blocks_any_claimed_readiness() -> None:
    packet = fixture()
    packet["feed_state"] = "FAILED"
    _refuse(packet, "feed_state.incomplete_or_unknown")
    packet = fixture("CONNECTED_PAPER")
    packet["account_hold"] = "UNKNOWN"
    _refuse(packet, "account_hold.held_or_unknown")


def test_future_retention_or_source_evidence_cannot_backdate_readiness() -> None:
    packet = fixture()
    _map(_map(packet, "dimensions"), "audit_retention")["first_available_utc"] = (
        "2026-10-20T19:00:00Z"
    )
    _refuse(packet, "dimensions.audit_retention.future_evidence")


def test_cross_campaign_receipt_cannot_authorize_other_context() -> None:
    packet = fixture("CONNECTED_PAPER")
    _map(_map(packet, "dimensions"), "mandate_and_risk")["scope_ref"] = (
        "another-campaign"
    )
    _refuse(packet, "dimensions.mandate_and_risk.scope_mismatch")
    packet = fixture("CONNECTED_PAPER")
    _map(packet, "operation_grant")["scope_ref"] = "another-campaign"
    _refuse(packet, "operation_grant.scope_mismatch")


def test_issuer_cannot_claim_independent_review_of_own_proof() -> None:
    packet = fixture()
    entry = _map(_map(packet, "dimensions"), "account_arm_isolation")
    entry["independent_review_ref"] = entry["producer_ref"]
    _refuse(packet, "dimensions.account_arm_isolation.self_review")
    packet = fixture()
    _map(packet, "reviews")["independent_reviewer_ref"] = "mock-producer"
    _refuse(packet, "reviews.self_review")


def test_missing_broker_capability_does_not_become_local_shadow() -> None:
    packet = fixture("CONNECTED_PAPER")
    del _map(packet, "dimensions")["broker_order_permission"]
    _refuse(packet, "dimensions.fields.not_exact")


def test_extra_authorization_controls_are_not_executed() -> None:
    packet = fixture()
    packet["skip_all_gates"] = True
    _refuse(packet, "payload.fields.not_exact")


def test_hostile_nested_objects_refuse_before_custom_equality() -> None:
    class Hostile:
        def __eq__(self, _: object) -> bool:
            raise AssertionError("untrusted custom equality invoked")

    packet = fixture()
    _map(_map(packet, "dimensions"), "mandate_and_risk")["claim"] = Hostile()
    result = preflight_forward_readiness(packet)
    assert result.reasons == ("payload.not_plain_json",)


def test_repeated_preflight_does_not_change_input_or_create_grants() -> None:
    packet = fixture()
    before = deepcopy(packet)
    first = preflight_forward_readiness(packet)
    second = preflight_forward_readiness(packet)
    assert first == second
    assert packet == before
    assert not first.authorizes_paper_live_or_deployment
