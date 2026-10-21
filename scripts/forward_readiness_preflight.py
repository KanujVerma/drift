"""Pure in-memory prospective readiness gap review, issue #537 / Matthew #384.

This is not an operational permission engine or a connected broker probe.
All supplied authorization, account and evidence references are untrusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

_UTC = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z"
)
_ROOT = frozenset({
    "profile", "mode", "as_of_utc", "campaign_ref",
    "requested_arm_count", "accounts", "dimensions",
    "contracts", "feed_state", "account_hold",
    "credential_mode", "operation_grant", "reviews",
})
_ACCOUNT = frozenset({
    "arm_id", "account_id", "environment_ref",
    "original_allocation_receipt_ref", "allocation_issuer_ref",
    "external_account_ref",
})
_DIMENSION = frozenset({
    "claim", "evidence_ref", "scope_ref", "first_available_utc",
    "producer_ref", "independent_review_ref",
})
_CONTRACT = frozenset({
    "claim", "accepted_revision_ref", "review_ref",
})
_GRANT = frozenset({
    "issuer_ref", "issuer_verification_ref", "scope_ref",
    "principal_ref", "not_before_utc", "expires_utc",
    "revoked", "purpose",
})
_REVIEWS = frozenset({
    "producer_ref", "source_custodian_ref", "independent_reviewer_ref",
    "independent_review_receipt_ref",
})
_COMMON_DIMS = frozenset({
    "original_information", "source_use_and_retention",
    "venue_and_session", "mandate_and_risk",
    "execution_and_fills", "account_state_and_orders",
    "account_arm_isolation", "cost_attribution",
    "audit_retention", "privacy_and_storage",
    "feed_failure_containment", "rollback_and_fencing",
})
_EXTERNAL_DIMS = frozenset({
    "provider_account_entitlement", "provider_feed_entitlement",
    "credential_custody", "broker_order_permission",
    "durable_unknown_reconciliation", "external_budget",
    "executor_containment", "account_issuer_verification",
})
_LIVE_DIMS = frozenset({
    "live_capital_scope", "live_broker_account",
    "human_operational_signoff", "loss_and_liquidity_controls",
})
_COMMON_CONTRACTS = frozenset({
    "m_sources_378", "m_timing_379",
    "m_mandate_380", "scientific_method_377",
})
_EXTERNAL_CONTRACTS = frozenset({
    "m_unknown_411", "m_result_376",
    "m_provisioning_508", "containment_396",
})
_LIVE_CONTRACTS = frozenset({"forward_authority_384", "live_risk_review"})
_MODES = {
    "LOCAL_SHADOW": (
        _COMMON_DIMS, _COMMON_CONTRACTS, "NO_EXTERNAL_CREDENTIALS"
    ),
    "CONNECTED_PAPER": (
        _COMMON_DIMS | _EXTERNAL_DIMS,
        _COMMON_CONTRACTS | _EXTERNAL_CONTRACTS,
        "EXTERNAL_CUSTODY_ASSERTED",
    ),
    "LIVE": (
        _COMMON_DIMS | _EXTERNAL_DIMS | _LIVE_DIMS,
        _COMMON_CONTRACTS | _EXTERNAL_CONTRACTS | _LIVE_CONTRACTS,
        "EXTERNAL_CUSTODY_ASSERTED",
    ),
}


@dataclass(frozen=True, slots=True)
class ForwardReadinessPreflight:
    """Untrusted review completeness, never readiness or access permission."""

    structurally_reviewable: bool
    checked_mode: str | None
    claimed_distinct_account_count: int | None
    missing_or_unaccepted_dimensions: tuple[str, ...]
    unresolved_contracts: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def authorizes_provider_connection(self) -> bool:
        return False

    @property
    def authorizes_paper_live_or_deployment(self) -> bool:
        return False

    @property
    def proves_real_account_entitlement(self) -> bool:
        return False


def _plain_json(value: object, depth: int, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is str:
        return len(value) <= 4096
    if type(value) is list:
        return len(value) <= 100 and all(
            _plain_json(x, depth + 1, budget) for x in value
        )
    if type(value) is dict:
        return len(value) <= 100 and all(
            type(k) is str and len(k) <= 128
            and _plain_json(v, depth + 1, budget)
            for k, v in value.items()
        )
    return False


def _obj(
    value: object, fields: frozenset[str], label: str, reasons: list[str]
) -> dict[str, object]:
    if type(value) is not dict:
        reasons.append(f"{label}.not_plain_object")
        return {}
    entry = cast(dict[str, object], value)
    if set(entry) != fields:
        reasons.append(f"{label}.fields.not_exact")
    return entry


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _utc(value: object) -> datetime | None:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timedelta(0) else None


def preflight_forward_readiness(payload: object) -> ForwardReadinessPreflight:
    """Build a conservative review-gap inventory from untrusted fixture data."""
    if not _plain_json(payload, 0, [5000]):
        return ForwardReadinessPreflight(
            False, None, None, (), (), ("payload.not_plain_json",)
        )
    reasons: list[str] = []
    root = _obj(payload, _ROOT, "payload", reasons)
    mode = root.get("mode")
    if type(mode) is not str or mode not in _MODES:
        reasons.append("mode.unsupported")
        expected_dimensions = frozenset[str]()
        expected_contracts = frozenset[str]()
        expected_credentials = None
        resolved_mode: str | None = None
    else:
        expected_dimensions, expected_contracts, expected_credentials = (
            _MODES[mode]
        )
        resolved_mode = mode
    if root.get("profile") != "synthetic-forward-readiness-review-v1":
        reasons.append("profile.unsupported")
    as_of = _utc(root.get("as_of_utc"))
    if as_of is None:
        reasons.append("as_of_utc.invalid")
    if not _text(root.get("campaign_ref")):
        reasons.append("campaign_ref.missing")
    count = root.get("requested_arm_count")
    if type(count) is not int or count <= 0 or count > 32:
        reasons.append("requested_arm_count.invalid")
        count = None
    if root.get("credential_mode") != expected_credentials:
        reasons.append("credential_mode.invalid_for_mode")

    accounts = root.get("accounts")
    seen_arms: set[str] = set()
    seen_account_ids: set[str] = set()
    seen_external_ids: set[str] = set()
    if type(accounts) is not list:
        reasons.append("accounts.not_plain_list")
        accounts = []
    if count is not None and len(accounts) != count:
        reasons.append("accounts.count_mismatch")
    for index, raw in enumerate(accounts):
        label = f"accounts.{index}"
        account = _obj(raw, _ACCOUNT, label, reasons)
        for field in (
            "arm_id", "account_id", "environment_ref",
            "original_allocation_receipt_ref", "allocation_issuer_ref",
        ):
            if not _text(account.get(field)):
                reasons.append(f"{label}.{field}.missing")
        arm = account.get("arm_id")
        internal = account.get("account_id")
        if _text(arm):
            assert isinstance(arm, str)
            if arm in seen_arms:
                reasons.append(f"{label}.duplicate_arm")
            seen_arms.add(arm)
        if _text(internal):
            assert isinstance(internal, str)
            if internal in seen_account_ids:
                reasons.append(f"{label}.duplicate_account_alias")
            seen_account_ids.add(internal)
        external = account.get("external_account_ref")
        if resolved_mode == "LOCAL_SHADOW":
            if external is not None:
                reasons.append(f"{label}.external_account_not_local")
        elif resolved_mode in ("CONNECTED_PAPER", "LIVE"):
            if not _text(external):
                reasons.append(f"{label}.external_account_ref.missing")
            else:
                assert isinstance(external, str)
                if external in seen_external_ids:
                    reasons.append(f"{label}.duplicate_external_account")
                seen_external_ids.add(external)

    dimensions = _obj(
        root.get("dimensions"), expected_dimensions, "dimensions", reasons
    )
    incomplete_dimensions: list[str] = []
    for name in sorted(expected_dimensions):
        item = _obj(
            dimensions.get(name), _DIMENSION, f"dimensions.{name}", reasons
        )
        if item.get("claim") != "CLAIMED_COMPLETE":
            incomplete_dimensions.append(name)
        for field in (
            "evidence_ref", "scope_ref", "producer_ref",
            "independent_review_ref",
        ):
            if not _text(item.get(field)):
                reasons.append(f"dimensions.{name}.{field}.missing")
        if item.get("scope_ref") != root.get("campaign_ref"):
            reasons.append(f"dimensions.{name}.scope_mismatch")
        when = _utc(item.get("first_available_utc"))
        if when is None:
            reasons.append(f"dimensions.{name}.first_available_utc.invalid")
        elif as_of is not None and when > as_of:
            reasons.append(f"dimensions.{name}.future_evidence")
        if (
            _text(item.get("producer_ref"))
            and item.get("producer_ref") == item.get("independent_review_ref")
        ):
            reasons.append(f"dimensions.{name}.self_review")

    contracts = _obj(
        root.get("contracts"), expected_contracts, "contracts", reasons
    )
    unresolved: list[str] = []
    for name in sorted(expected_contracts):
        item = _obj(contracts.get(name), _CONTRACT, f"contracts.{name}", reasons)
        if item.get("claim") != "CLAIMED_ACCEPTED":
            unresolved.append(name)
        for field in ("accepted_revision_ref", "review_ref"):
            if not _text(item.get(field)):
                reasons.append(f"contracts.{name}.{field}.missing")
    if root.get("feed_state") != "CLAIMED_COMPLETE":
        reasons.append("feed_state.incomplete_or_unknown")
    if root.get("account_hold") != "CLAIMED_CLEAR":
        reasons.append("account_hold.held_or_unknown")

    reviews = _obj(root.get("reviews"), _REVIEWS, "reviews", reasons)
    for field in _REVIEWS:
        if not _text(reviews.get(field)):
            reasons.append(f"reviews.{field}.missing")
    if (
        _text(reviews.get("producer_ref"))
        and reviews.get("producer_ref") == reviews.get(
            "independent_reviewer_ref"
        )
    ):
        reasons.append("reviews.self_review")

    raw_grant = root.get("operation_grant")
    if resolved_mode == "LOCAL_SHADOW":
        if raw_grant is not None:
            reasons.append("operation_grant.not_allowed_for_local_only")
    elif resolved_mode in ("CONNECTED_PAPER", "LIVE"):
        grant = _obj(raw_grant, _GRANT, "operation_grant", reasons)
        for field in (
            "issuer_ref", "issuer_verification_ref", "scope_ref",
            "principal_ref",
        ):
            if not _text(grant.get(field)):
                reasons.append(f"operation_grant.{field}.missing")
        if grant.get("scope_ref") != root.get("campaign_ref"):
            reasons.append("operation_grant.scope_mismatch")
        if grant.get("purpose") != resolved_mode:
            reasons.append("operation_grant.purpose_mismatch")
        if grant.get("revoked") is not False:
            reasons.append("operation_grant.revoked_or_unknown")
        begins = _utc(grant.get("not_before_utc"))
        expiry = _utc(grant.get("expires_utc"))
        if begins is None or expiry is None or begins >= expiry:
            reasons.append("operation_grant.window.invalid")
        elif as_of is not None and not begins <= as_of < expiry:
            reasons.append("operation_grant.outside_claimed_window")

    if incomplete_dimensions:
        reasons.append("dimensions.unresolved")
    if unresolved:
        reasons.append("contracts.unaccepted_or_unknown")
    return ForwardReadinessPreflight(
        not reasons,
        resolved_mode,
        len(seen_account_ids) if not reasons else None,
        tuple(incomplete_dimensions),
        tuple(unresolved),
        tuple(reasons),
    )
