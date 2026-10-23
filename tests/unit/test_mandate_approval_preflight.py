"""Synthetic mandate review vectors for Matthew #380 / assist #529."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from scripts.mandate_approval_preflight import (
    canonical_fixture_intent_sha256,
    preflight_mandate_approval,
)

SHA_MANDATE = "a" * 64
SHA_STATE = "b" * 64

GATES = (
    "issuer_authority",
    "asset_and_mandate_scope",
    "portfolio_state",
    "open_orders",
    "source_and_market_capability",
    "risk_and_eligibility",
    "budget_reservation",
    "durable_dispatch",
)


def fixture(mode: str = "SMART") -> dict[str, object]:
    request: dict[str, object] = {
        "logical_operation_id": "offline-operation-A",
        "client_token": "never-sent-original-token",
        "candidate_revision_ref": "mock-candidate-1",
        "account_id": "synthetic-account-A",
        "arm_id": "A",
        "environment_ref": "synthetic-session",
        "mandate_id": "synthetic-mandate-1",
        "mandate_epoch": 7,
        "manifest_sha256": SHA_MANDATE,
        "state_sha256": SHA_STATE,
        "accepted_policy_ref": "fictional-accepted-policy-revision",
        "source_cutoff_ref": "fictional-source-cutoff-1",
        "eligibility_ref": "fictional-eligibility-1",
        "security_ref": "fictional-listed-security",
        "side": "BUY",
        "quantity": 5,
        "order_notional_usd": "500",
        "nav_usd": "50000",
    }
    intent_hash = canonical_fixture_intent_sha256(request)
    assert intent_hash is not None
    gates = {
        gate: {
            "verdict": "PASS",
            "receipt_ref": f"unverified-external-{gate}",
        }
        for gate in GATES
    }
    return {
        "profile": "synthetic-mandate-review-v1",
        "as_of_utc": "2026-01-02T10:32:10Z",
        "operation_kind": "NEW_RISK",
        "mandate": {
            "mandate_id": "synthetic-mandate-1",
            "manifest_sha256": SHA_MANDATE,
            "account_id": "synthetic-account-A",
            "arm_id": "A",
            "environment_ref": "synthetic-session",
            "approval_mode": mode,
            "issuer_ref": "untrusted-custodian-identity",
            "issuer_verification_ref": "untrusted-custodian-verification",
            "accepted_policy_ref": "fictional-accepted-policy-revision",
            "epoch": 7,
            "issued_utc": "2026-01-02T10:00:00Z",
            "expires_utc": "2026-01-02T12:00:00Z",
            "revoked": False,
        },
        "request": request,
        "approval": {
            "grant_id": "mock-approval-1",
            "decision": "GRANTED",
            "grant_mode": mode,
            "issuer_role": "HUMAN" if mode == "ASK" else "SYSTEM",
            "issuer_ref": "untrusted-policy-or-human-issuer",
            "issuer_verification_ref": "untrusted-external-signed-receipt",
            "bound_intent_sha256": intent_hash,
            "bound_state_sha256": SHA_STATE,
            "bound_mandate_sha256": SHA_MANDATE,
            "bound_account_id": "synthetic-account-A",
            "bound_arm_id": "A",
            "bound_environment_ref": "synthetic-session",
            "bound_mandate_epoch": 7,
            "issued_utc": "2026-01-02T10:32:08Z",
            "expires_utc": "2026-01-02T10:33:00Z",
        },
        "state": {
            "state_sha256": SHA_STATE,
            "observed_utc": "2026-01-02T10:32:08Z",
            "quote_event_utc": "2026-01-02T10:32:08Z",
            "quote_received_utc": "2026-01-02T10:32:09Z",
            "portfolio_status": "COMPLETE",
            "open_orders_status": "COMPLETE",
            "mandate_epoch": 7,
            "kill": False,
            "paused": False,
            "uncertainty_hold": False,
            "pause_time_utc": None,
            "mandatory_gates": gates,
        },
        "mandatory_policy": {
            "policy_ref": "fictional-accepted-policy-revision",
            "max_quote_age_seconds": "2",
            "max_state_age_seconds": "5",
        },
        "smart_policy": None
        if mode != "SMART"
        else {
            "policy_ref": "fictional-smart-policy-revision",
            "max_notional_usd": "500",
            "max_nav_notional_bps": "100",
            "max_weight_change_bps": "100",
            "max_quote_age_seconds": "2",
            "max_state_age_seconds": "5",
            "max_spread_bps": "10",
            "max_orders_window": 2,
            "window_seconds": 60,
        },
        "smart_observed": None
        if mode != "SMART"
        else {
            "spread_bps": "9",
            "gross_change_bps": "100",
            "orders_in_window": 1,
            "window_evidence_ref": "mock-trailing-window-evidence",
        },
        "history": {"attempts": [], "fill_effects": []},
    }


def _inner(data: dict[str, object], key: str) -> dict[str, object]:
    return cast(dict[str, object], data[key])


def _intent_rebind(data: dict[str, object]) -> None:
    request = _inner(data, "request")
    fingerprint = canonical_fixture_intent_sha256(request)
    assert fingerprint is not None
    _inner(data, "approval")["bound_intent_sha256"] = fingerprint


def _refuse(data: dict[str, object], reason: str) -> None:
    report = preflight_mandate_approval(data)
    assert not report.review_ready
    assert reason in report.reasons
    assert report.route != "POLICY_REVIEW_ONLY"
    assert not report.authorizes_order_or_protective_action
    assert not report.authenticates_mandate_or_account


@pytest.mark.parametrize(
    ("mode", "route"),
    [
        ("ASK", "MANUAL_REVIEW_ONLY"),
        ("SMART", "POLICY_REVIEW_ONLY"),
        ("AUTO", "POLICY_REVIEW_ONLY"),
    ],
)
def test_declared_grant_never_authenticates_permission(mode: str, route: str) -> None:
    report = preflight_mandate_approval(fixture(mode))
    assert report.review_ready
    assert report.route == route
    assert report.reasons == ()
    assert report.grant_already_consumed is False
    assert report.reported_post_pause_fill_quantity == 0
    assert not report.authorizes_order_or_protective_action
    assert not report.authenticates_mandate_or_account


def test_full_intent_mutation_invalidates_original_approval() -> None:
    data = fixture()
    _inner(data, "request")["quantity"] = 6
    _refuse(data, "approval.bound_intent_sha256.mismatch")


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("account_id", "other-account", "mandate.account_id.binding_mismatch"),
        ("arm_id", "B", "mandate.arm_id.binding_mismatch"),
        (
            "environment_ref",
            "other-environment",
            "mandate.environment_ref.binding_mismatch",
        ),
        ("state_sha256", "c" * 64, "request.state_sha256.binding_mismatch"),
        ("mandate_epoch", 8, "request.mandate_epoch.binding_mismatch"),
    ],
)
def test_cross_account_arm_state_epoch_or_environment_refuses(
    field: str, replacement: object, reason: str
) -> None:
    data = fixture()
    _inner(data, "request")[field] = replacement
    _refuse(data, reason)


def test_revoked_mandate_and_expired_approval_are_not_revived() -> None:
    data = fixture()
    _inner(data, "mandate")["revoked"] = True
    _refuse(data, "mandate.revoked_or_unknown")
    data = fixture()
    _inner(data, "approval")["expires_utc"] = data["as_of_utc"]
    _refuse(data, "approval.expired")
    data = fixture()
    _inner(data, "mandate")["expires_utc"] = data["as_of_utc"]
    _refuse(data, "mandate.expired")


@pytest.mark.parametrize("field", ["kill", "paused", "uncertainty_hold"])
def test_pause_kill_or_unknown_hold_refuses_new_risk(field: str) -> None:
    data = fixture()
    _inner(data, "state")[field] = True
    if field == "paused":
        _inner(data, "state")["pause_time_utc"] = "2026-01-02T10:32:07Z"
    _refuse(data, f"state.{field}.blocks_new_risk")


def test_unknown_portfolio_and_unknown_order_are_not_zero() -> None:
    data = fixture()
    _inner(data, "state")["portfolio_status"] = "UNKNOWN"
    _refuse(data, "state.portfolio_incomplete")
    data = fixture()
    _inner(data, "state")["open_orders_status"] = "UNKNOWN"
    _refuse(data, "state.open_orders_incomplete")


def test_mandatory_risk_failure_cannot_escalate_to_manual_override() -> None:
    data = fixture("ASK")
    gates = cast(
        dict[str, dict[str, object]],
        _inner(data, "state")["mandatory_gates"],
    )
    gates["risk_and_eligibility"]["verdict"] = "FAIL"
    _refuse(data, "state.mandatory_gates.risk_and_eligibility.not_passed")


def test_quote_and_portfolio_freshness_are_mandatory_in_all_modes() -> None:
    data = fixture("ASK")
    _inner(data, "state")["quote_event_utc"] = "2026-01-02T10:32:06Z"
    _refuse(data, "mandatory.quote_stale")
    data = fixture("AUTO")
    _inner(data, "state")["observed_utc"] = "2026-01-02T10:32:04Z"
    _refuse(data, "mandatory.state_stale")


def test_smart_route_uses_only_explicit_fixture_policy_bounds() -> None:
    data = fixture()
    _inner(data, "request")["order_notional_usd"] = "500.01"
    _intent_rebind(data)
    report = preflight_mandate_approval(data)
    assert not report.review_ready
    assert report.route == "ASK_REVIEW_REQUIRED"
    assert "smart.outside_proposed_bounds" in report.reasons
    assert not report.authorizes_order_or_protective_action


def test_smart_window_count_is_checked_before_current_new_order() -> None:
    data = fixture()
    _inner(data, "smart_observed")["orders_in_window"] = 2
    report = preflight_mandate_approval(data)
    assert report.route == "ASK_REVIEW_REQUIRED"
    assert "smart.outside_proposed_bounds" in report.reasons


def test_missing_smart_bounds_never_default_to_candidate_numbers() -> None:
    data = fixture()
    _inner(data, "smart_policy")["max_notional_usd"] = ""
    _refuse(data, "smart_policy.max_notional_usd.measurement_or_bound_invalid")
    data = fixture()
    data["smart_policy"] = None
    _refuse(data, "smart_policy.not_plain_object")


def test_ask_requires_human_claim_and_auto_requires_system_claim() -> None:
    data = fixture("ASK")
    _inner(data, "approval")["issuer_role"] = "SYSTEM"
    _refuse(data, "approval.issuer_role_incompatible")
    data = fixture("AUTO")
    _inner(data, "approval")["issuer_role"] = "HUMAN"
    _refuse(data, "approval.issuer_role_incompatible")


def test_original_operation_already_reserved_cannot_get_second_grant() -> None:
    data = fixture()
    request = _inner(data, "request")
    approval = _inner(data, "approval")
    _inner(data, "history")["attempts"] = [
        {
            "grant_id": approval["grant_id"],
            "logical_operation_id": request["logical_operation_id"],
            "client_token": request["client_token"],
            "bound_intent_sha256": approval["bound_intent_sha256"],
            "account_id": request["account_id"],
            "arm_id": request["arm_id"],
            "dispatch_started": False,
        }
    ]
    report = preflight_mandate_approval(data)
    assert not report.review_ready
    assert report.grant_already_consumed
    assert "history.original_operation_already_reserved" in report.reasons


def test_original_operation_already_dispatched_cannot_retry() -> None:
    data = fixture()
    request = _inner(data, "request")
    approval = _inner(data, "approval")
    _inner(data, "history")["attempts"] = [
        {
            "grant_id": approval["grant_id"],
            "logical_operation_id": request["logical_operation_id"],
            "client_token": request["client_token"],
            "bound_intent_sha256": approval["bound_intent_sha256"],
            "account_id": request["account_id"],
            "arm_id": request["arm_id"],
            "dispatch_started": True,
        }
    ]
    report = preflight_mandate_approval(data)
    assert not report.review_ready
    assert report.grant_already_consumed
    assert "history.original_operation_already_dispatched" in report.reasons


def _unrelated_attempt(dispatch_started: bool) -> dict[str, object]:
    return {
        "grant_id": "previous-grant",
        "logical_operation_id": "previous-operation",
        "client_token": "previous-token",
        "bound_intent_sha256": "c" * 64,
        "account_id": "synthetic-account-A",
        "arm_id": "A",
        "dispatch_started": dispatch_started,
    }


@pytest.mark.parametrize("mode", ["ASK", "SMART", "AUTO"])
@pytest.mark.parametrize("dispatch_started", [False, True])
def test_valid_unrelated_attempt_does_not_consume_current_grant(
    mode: str, dispatch_started: bool
) -> None:
    data = fixture(mode)
    _inner(data, "history")["attempts"] = [_unrelated_attempt(dispatch_started)]
    report = preflight_mandate_approval(data)
    assert report.review_ready
    assert report.reasons == ()
    assert not report.grant_already_consumed
    assert report.reported_post_pause_fill_quantity == 0
    assert not report.authorizes_order_or_protective_action
    assert not report.authenticates_mandate_or_account


@pytest.mark.parametrize(
    "field",
    ["grant_id", "logical_operation_id", "client_token", "account_id", "arm_id"],
)
@pytest.mark.parametrize("malformed", [None, "", " \t", 0, False, [], {}])
@pytest.mark.parametrize("dispatch_started", [False, True])
def test_every_retained_attempt_identity_must_be_concrete_nonempty_text(
    field: str, malformed: object, dispatch_started: bool
) -> None:
    data = fixture()
    attempt = _unrelated_attempt(dispatch_started)
    attempt[field] = malformed
    _inner(data, "history")["attempts"] = [attempt]
    reason = (
        "history.attempts.0.foreign_account_or_arm"
        if field in ("account_id", "arm_id")
        else f"history.attempts.0.{field}.invalid"
    )
    _refuse(data, reason)


@pytest.mark.parametrize(
    "malformed", [None, "", "not-a-digest", "a" * 63, "a" * 65, "A" * 64, 0, [], {}]
)
@pytest.mark.parametrize("dispatch_started", [False, True])
def test_every_retained_attempt_requires_a_valid_intent_digest(
    malformed: object, dispatch_started: bool
) -> None:
    data = fixture()
    attempt = _unrelated_attempt(dispatch_started)
    attempt["bound_intent_sha256"] = malformed
    _inner(data, "history")["attempts"] = [attempt]
    _refuse(data, "history.attempts.0.bound_intent_sha256.invalid")


def test_all_retained_attempt_fields_are_validated_before_dispatch_classification() -> (
    None
):
    data = fixture()
    attempt = _unrelated_attempt(True)
    for field in (
        "grant_id",
        "logical_operation_id",
        "client_token",
        "bound_intent_sha256",
    ):
        attempt[field] = None
    attempt["dispatch_started"] = None
    _inner(data, "history")["attempts"] = [attempt]
    report = preflight_mandate_approval(data)
    assert not report.review_ready
    assert report.route == "REFUSED"
    for field in (
        "grant_id",
        "logical_operation_id",
        "client_token",
        "bound_intent_sha256",
        "dispatch_started",
    ):
        assert f"history.attempts.0.{field}.invalid" in report.reasons
    assert not report.authorizes_order_or_protective_action
    assert not report.authenticates_mandate_or_account


@pytest.mark.parametrize("dispatch_started", [False, True])
def test_malformed_later_attempt_does_not_hide_current_operation_refusal(
    dispatch_started: bool,
) -> None:
    data = fixture()
    current = _unrelated_attempt(dispatch_started)
    current.update(
        grant_id=_inner(data, "approval")["grant_id"],
        logical_operation_id=_inner(data, "request")["logical_operation_id"],
        client_token=_inner(data, "request")["client_token"],
        bound_intent_sha256=_inner(data, "approval")["bound_intent_sha256"],
    )
    malformed = _unrelated_attempt(dispatch_started)
    malformed["grant_id"] = None
    _inner(data, "history")["attempts"] = [current, malformed]
    report = preflight_mandate_approval(data)
    assert not report.review_ready
    assert report.route == "REFUSED"
    assert report.grant_already_consumed
    prior_state = "dispatched" if dispatch_started else "reserved"
    assert f"history.original_operation_already_{prior_state}" in report.reasons
    assert "history.attempts.1.grant_id.invalid" in report.reasons
    assert not report.authorizes_order_or_protective_action
    assert not report.authenticates_mandate_or_account


def test_fresh_client_token_cannot_bypass_a_live_account_hold() -> None:
    data = fixture()
    _inner(data, "request")["client_token"] = "fresh-attempt"
    _intent_rebind(data)
    _inner(data, "state")["uncertainty_hold"] = True
    _refuse(data, "state.uncertainty_hold.blocks_new_risk")


def test_post_pause_fill_is_still_recorded_as_claimed_effect() -> None:
    data = fixture()
    state = _inner(data, "state")
    state["paused"] = True
    state["pause_time_utc"] = "2026-01-02T10:32:07Z"
    effect = {
        "effect_id": "mock-original-effect",
        "account_id": "synthetic-account-A",
        "arm_id": "A",
        "client_token": "previous-existing-order",
        "incremental_quantity": 2,
        "occurred_utc": "2026-01-02T10:32:09Z",
        "fee_state": "KNOWN",
    }
    _inner(data, "history")["fill_effects"] = [
        effect,
        deepcopy(effect),
    ]
    report = preflight_mandate_approval(data)
    assert not report.review_ready
    assert report.reported_post_pause_fill_quantity == 2
    assert "state.paused.blocks_new_risk" in report.reasons
    assert not report.authorizes_order_or_protective_action


def test_conflicting_effect_id_does_not_launder_a_second_fill() -> None:
    data = fixture()
    state = _inner(data, "state")
    state["paused"] = True
    state["pause_time_utc"] = "2026-01-02T10:32:07Z"
    original = {
        "effect_id": "same-effect",
        "account_id": "synthetic-account-A",
        "arm_id": "A",
        "client_token": "previous-order",
        "incremental_quantity": 2,
        "occurred_utc": "2026-01-02T10:32:09Z",
        "fee_state": "KNOWN",
    }
    changed = deepcopy(original)
    changed["incremental_quantity"] = 20
    _inner(data, "history")["fill_effects"] = [original, changed]
    report = preflight_mandate_approval(data)
    assert "history.fill_effects.1.effect_id.conflicting_redelivery" in (report.reasons)
    assert report.reported_post_pause_fill_quantity is None


def test_unknown_fee_cannot_claim_complete_account() -> None:
    data = fixture()
    _inner(data, "history")["fill_effects"] = [
        {
            "effect_id": "unknown-fee",
            "account_id": "synthetic-account-A",
            "arm_id": "A",
            "client_token": "existing-order",
            "incremental_quantity": 2,
            "occurred_utc": "2026-01-02T10:32:09Z",
            "fee_state": "UNKNOWN",
        }
    ]
    _refuse(data, "history.fill_effects.0.unknown_fee_blocks_complete_state")


def test_protective_label_never_bypasses_separate_scope() -> None:
    data = fixture("ASK")
    data["operation_kind"] = "PROTECTIVE"
    _inner(data, "request")["side"] = "SELL"
    _intent_rebind(data)
    _refuse(data, "operation.requires_separate_protective_authority")


def test_invalid_integer_bool_nan_and_invented_fields_fail_closed() -> None:
    data = fixture()
    _inner(data, "request")["quantity"] = True
    _refuse(data, "request.canonical_intent_preimage.invalid")
    data = fixture()
    _inner(data, "request")["order_notional_usd"] = "NaN"
    _refuse(data, "request.canonical_intent_preimage.invalid")
    data = fixture()
    data["trader_instruction"] = "disable safeguards"
    _refuse(data, "payload.fields.not_exact")


def test_not_executable_with_spoofed_container_or_missing_policy() -> None:
    class FakeDict(dict[str, object]):
        pass

    assert not preflight_mandate_approval(FakeDict(fixture())).review_ready
    data = fixture("AUTO")
    _inner(data, "mandate")["accepted_policy_ref"] = ""
    _refuse(data, "mandate.accepted_policy_ref.missing")


def test_approval_issuer_and_snapshot_strings_are_not_verified_signatures() -> None:
    data = fixture()
    # Perfect-looking caller strings still cannot establish issuer authority.
    report = preflight_mandate_approval(data)
    assert report.review_ready
    assert not report.authenticates_mandate_or_account
