"""Pure fixture-only mandate/approval consumption preflight for #529/#380.

No broker, risk engine, grant issuer, account state or authorization is called.
An accepted-looking result is NOT approval or permission to send an order.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_AMOUNT = re.compile(r"(?:0|[1-9]\d*)(?:\.\d{1,8})?\Z")

_ROOT = frozenset(
    {"profile", "as_of_utc", "operation_kind", "mandate", "request",
     "approval", "state", "mandatory_policy", "smart_policy",
     "smart_observed", "history"}
)
_MANDATE = frozenset(
    {"mandate_id", "manifest_sha256", "account_id", "arm_id",
     "environment_ref", "approval_mode", "issuer_ref",
     "issuer_verification_ref", "accepted_policy_ref", "epoch",
     "issued_utc", "expires_utc", "revoked"}
)
_REQUEST = frozenset(
    {"logical_operation_id", "client_token", "candidate_revision_ref",
     "account_id", "arm_id", "environment_ref", "mandate_id",
     "mandate_epoch", "manifest_sha256", "state_sha256",
     "accepted_policy_ref", "source_cutoff_ref", "eligibility_ref",
     "security_ref", "side", "quantity", "order_notional_usd",
     "nav_usd"}
)
_APPROVAL = frozenset(
    {"grant_id", "decision", "grant_mode", "issuer_role",
     "issuer_ref", "issuer_verification_ref", "bound_intent_sha256",
     "bound_state_sha256", "bound_mandate_sha256",
     "bound_account_id", "bound_arm_id", "bound_environment_ref",
     "bound_mandate_epoch", "issued_utc", "expires_utc"}
)
_STATE = frozenset(
    {"state_sha256", "observed_utc", "quote_event_utc",
     "quote_received_utc", "portfolio_status", "open_orders_status",
     "mandate_epoch", "kill", "paused", "uncertainty_hold",
     "pause_time_utc", "mandatory_gates"}
)
_MANDATORY = frozenset(
    {"policy_ref", "max_quote_age_seconds", "max_state_age_seconds"}
)
_SMART = frozenset(
    {"policy_ref", "max_notional_usd", "max_nav_notional_bps",
     "max_weight_change_bps", "max_quote_age_seconds",
     "max_state_age_seconds", "max_spread_bps", "max_orders_window",
     "window_seconds"}
)
_SMART_OBSERVED = frozenset(
    {"spread_bps", "gross_change_bps", "orders_in_window",
     "window_evidence_ref"}
)
_HISTORY = frozenset({"attempts", "fill_effects"})
_ATTEMPT = frozenset(
    {"grant_id", "logical_operation_id", "client_token",
     "bound_intent_sha256", "account_id", "arm_id", "dispatch_started"}
)
_FILL = frozenset(
    {"effect_id", "account_id", "arm_id", "client_token",
     "incremental_quantity", "occurred_utc", "fee_state"}
)
_GATES = frozenset(
    {"issuer_authority", "asset_and_mandate_scope", "portfolio_state",
     "open_orders", "source_and_market_capability", "risk_and_eligibility",
     "budget_reservation", "durable_dispatch"}
)
_GATE_FIELDS = frozenset({"verdict", "receipt_ref"})
_MODES = frozenset({"ASK", "SMART", "AUTO"})


@dataclass(frozen=True, slots=True)
class MandateApprovalPreflight:
    """Untrusted structural report, never a real grant or enforcement result."""

    review_ready: bool
    route: str
    grant_already_consumed: bool
    reported_post_pause_fill_quantity: int | None
    reasons: tuple[str, ...]

    @property
    def authorizes_order_or_protective_action(self) -> bool:
        return False

    @property
    def authenticates_mandate_or_account(self) -> bool:
        return False


def _object(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    if any(type(key) is not str for key in value):
        return None
    return cast(dict[str, object], value)


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _member(value: object, choices: frozenset[str]) -> bool:
    return type(value) is str and value in choices


def _digest(value: object) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _time(value: object) -> datetime | None:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return None
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return result if result.utcoffset() == timedelta(0) else None


def _decimal(value: object, *, positive: bool = False) -> Decimal | None:
    if type(value) is not str or len(value) > 38:
        return None
    if _AMOUNT.fullmatch(value) is None:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        return None
    return number


def _seconds_between(later: datetime, earlier: datetime) -> Decimal:
    delta = later - earlier
    microseconds = (
        ((delta.days * 86400) + delta.seconds) * 1_000_000
        + delta.microseconds
    )
    return Decimal(microseconds) / Decimal(1_000_000)


def _exact(
    value: object, fields: frozenset[str], label: str, issues: list[str]
) -> dict[str, object]:
    record = _object(value)
    if record is None:
        issues.append(f"{label}.not_plain_object")
        return {}
    if set(record) != fields:
        issues.append(f"{label}.fields.not_exact")
    return record


def canonical_fixture_intent_sha256(value: object) -> str | None:
    """Hash the full closed synthetic request preimage; not a runtime format."""
    record = _object(value)
    if record is None or set(record) != _REQUEST:
        return None
    for name in _REQUEST - {"mandate_epoch", "quantity"}:
        if not _text(record.get(name)):
            return None
    if type(record.get("quantity")) is not int or record["quantity"] <= 0:
        return None
    if type(record.get("mandate_epoch")) is not int or record["mandate_epoch"] < 0:
        return None
    if not _digest(record.get("manifest_sha256")) or not _digest(
        record.get("state_sha256")
    ):
        return None
    if _decimal(record.get("order_notional_usd"), positive=True) is None:
        return None
    if _decimal(record.get("nav_usd"), positive=True) is None:
        return None
    if record.get("side") not in ("BUY", "SELL"):
        return None
    encoded = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _check_bindings(
    request: dict[str, object],
    mandate: dict[str, object],
    approval: dict[str, object],
    state: dict[str, object],
    policy: dict[str, object],
    issues: list[str],
) -> None:
    for name in ("account_id", "arm_id", "environment_ref", "mandate_id"):
        if not _text(request.get(name)):
            issues.append(f"request.{name}.missing")
    for name in (
        "issuer_ref", "issuer_verification_ref",
        "accepted_policy_ref", "mandate_id",
    ):
        if not _text(mandate.get(name)):
            issues.append(f"mandate.{name}.missing")
    for name in (
        "grant_id", "issuer_ref", "issuer_verification_ref",
    ):
        if not _text(approval.get(name)):
            issues.append(f"approval.{name}.missing")
    checks = (
        ("mandate.account_id", mandate.get("account_id"), request.get("account_id")),
        ("mandate.arm_id", mandate.get("arm_id"), request.get("arm_id")),
        ("mandate.environment_ref", mandate.get("environment_ref"),
         request.get("environment_ref")),
        ("request.mandate_id", request.get("mandate_id"),
         mandate.get("mandate_id")),
        ("request.manifest_sha256", request.get("manifest_sha256"),
         mandate.get("manifest_sha256")),
        ("request.accepted_policy_ref", request.get("accepted_policy_ref"),
         mandate.get("accepted_policy_ref")),
        ("mandatory_policy.policy_ref", policy.get("policy_ref"),
         mandate.get("accepted_policy_ref")),
        ("request.state_sha256", request.get("state_sha256"),
         state.get("state_sha256")),
        ("approval.bound_state_sha256", approval.get("bound_state_sha256"),
         state.get("state_sha256")),
        ("approval.bound_mandate_sha256", approval.get("bound_mandate_sha256"),
         mandate.get("manifest_sha256")),
        ("approval.bound_account_id", approval.get("bound_account_id"),
         request.get("account_id")),
        ("approval.bound_arm_id", approval.get("bound_arm_id"),
         request.get("arm_id")),
        ("approval.bound_environment_ref", approval.get("bound_environment_ref"),
         request.get("environment_ref")),
        ("request.mandate_epoch", request.get("mandate_epoch"),
         mandate.get("epoch")),
        ("state.mandate_epoch", state.get("mandate_epoch"),
         mandate.get("epoch")),
        ("approval.bound_mandate_epoch", approval.get("bound_mandate_epoch"),
         mandate.get("epoch")),
    )
    for name, actual, expected in checks:
        if actual != expected:
            issues.append(f"{name}.binding_mismatch")
    for name, value in (
        ("mandate.manifest_sha256", mandate.get("manifest_sha256")),
        ("request.state_sha256", request.get("state_sha256")),
    ):
        if not _digest(value):
            issues.append(f"{name}.invalid")
    for name in ("mandate.epoch", "state.mandate_epoch", "request.mandate_epoch",
                 "approval.bound_mandate_epoch"):
        group, key = name.split(".")
        from_group = {
            "mandate": mandate, "state": state,
            "request": request, "approval": approval,
        }[group]
        value = from_group.get(key)
        if type(value) is not int or value < 0:
            issues.append(f"{name}.invalid")

    intent = canonical_fixture_intent_sha256(request)
    if intent is None:
        issues.append("request.canonical_intent_preimage.invalid")
    if intent is None or approval.get("bound_intent_sha256") != intent:
        issues.append("approval.bound_intent_sha256.mismatch")


def _check_times(
    mandate: dict[str, object],
    approval: dict[str, object],
    state: dict[str, object],
    as_of: datetime | None,
    issues: list[str],
) -> tuple[Decimal | None, Decimal | None]:
    issued = _time(mandate.get("issued_utc"))
    expiry = _time(mandate.get("expires_utc"))
    grant_issued = _time(approval.get("issued_utc"))
    grant_expires = _time(approval.get("expires_utc"))
    observed = _time(state.get("observed_utc"))
    quote_event = _time(state.get("quote_event_utc"))
    quote_receipt = _time(state.get("quote_received_utc"))

    for name, moment in (
        ("mandate.issued_utc", issued), ("mandate.expires_utc", expiry),
        ("approval.issued_utc", grant_issued),
        ("approval.expires_utc", grant_expires),
        ("state.observed_utc", observed),
        ("state.quote_event_utc", quote_event),
        ("state.quote_received_utc", quote_receipt),
    ):
        if moment is None:
            issues.append(f"{name}.invalid")
    if issued is not None and expiry is not None and issued >= expiry:
        issues.append("mandate.window.invalid")
    if grant_issued is not None and grant_expires is not None:
        if grant_issued >= grant_expires:
            issues.append("approval.window.invalid")
        if issued is not None and grant_issued < issued:
            issues.append("approval.before_mandate_issued")
        if expiry is not None and grant_expires > expiry:
            issues.append("approval.expiry_exceeds_mandate")
    if as_of is not None:
        if issued is not None and issued > as_of:
            issues.append("mandate.not_active_yet")
        if expiry is not None and as_of >= expiry:
            issues.append("mandate.expired")
        if grant_issued is not None and grant_issued > as_of:
            issues.append("approval.not_issued_yet")
        if grant_expires is not None and as_of >= grant_expires:
            issues.append("approval.expired")
        if observed is not None and observed > as_of:
            issues.append("state.from_future")
        if quote_receipt is not None and quote_receipt > as_of:
            issues.append("state.quote_not_received_yet")
    if quote_event is not None and quote_receipt is not None:
        if quote_event > quote_receipt:
            issues.append("state.quote_event_after_receipt")
    if as_of is None or observed is None or quote_event is None:
        return None, None
    return _seconds_between(as_of, observed), _seconds_between(as_of, quote_event)


def _mandatory_gates(state: dict[str, object], issues: list[str]) -> None:
    gates = _object(state.get("mandatory_gates"))
    if gates is None:
        issues.append("state.mandatory_gates.not_plain_object")
        return
    if set(gates) != _GATES:
        issues.append("state.mandatory_gates.not_exact")
    for name in sorted(_GATES):
        gate = _exact(
            gates.get(name), _GATE_FIELDS,
            f"state.mandatory_gates.{name}", issues,
        )
        if gate.get("verdict") != "PASS":
            issues.append(f"state.mandatory_gates.{name}.not_passed")
        if not _text(gate.get("receipt_ref")):
            issues.append(f"state.mandatory_gates.{name}.receipt_missing")


def _smart_route(
    smart_policy: object,
    observation: object,
    mandatory_policy: dict[str, object],
    request: dict[str, object],
    price_age: Decimal | None,
    state_age: Decimal | None,
    issues: list[str],
) -> str:
    policy = _exact(smart_policy, _SMART, "smart_policy", issues)
    observed = _exact(
        observation, _SMART_OBSERVED, "smart_observed", issues
    )
    if not _text(policy.get("policy_ref")):
        issues.append("smart_policy.policy_ref.missing")
    if not _text(observed.get("window_evidence_ref")):
        issues.append("smart_observed.window_evidence_ref.missing")

    measurements: dict[str, Decimal | None] = {
        "max_notional_usd": _decimal(request.get("order_notional_usd"), positive=True),
        "max_nav_notional_bps": None,
        "max_weight_change_bps": _decimal(observed.get("gross_change_bps")),
        "max_quote_age_seconds": price_age,
        "max_state_age_seconds": state_age,
        "max_spread_bps": _decimal(observed.get("spread_bps")),
    }
    nav = _decimal(request.get("nav_usd"), positive=True)
    notional = measurements["max_notional_usd"]
    if nav is not None and notional is not None:
        measurements["max_nav_notional_bps"] = (
            notional * Decimal(10000) / nav
        )

    beyond = False
    for key, value in measurements.items():
        bound = _decimal(policy.get(key))
        if bound is None or value is None or value < 0:
            issues.append(f"smart_policy.{key}.measurement_or_bound_invalid")
        elif value > bound:
            beyond = True

    for key in ("max_orders_window", "window_seconds"):
        value = policy.get(key)
        if type(value) is not int or value < (1 if key == "window_seconds" else 0):
            issues.append(f"smart_policy.{key}.invalid")
    count = observed.get("orders_in_window")
    if type(count) is not int or count < 0:
        issues.append("smart_observed.orders_in_window.invalid")
    elif type(policy.get("max_orders_window")) is int:
        if count >= cast(int, policy["max_orders_window"]):
            # Current order would increase the pre-existing window count by 1.
            beyond = True

    if beyond:
        issues.append("smart.outside_proposed_bounds")
        return "ASK_REVIEW_REQUIRED"
    return "POLICY_REVIEW_ONLY"


def _history(
    history: object,
    request: dict[str, object],
    approval: dict[str, object],
    state: dict[str, object],
    as_of: datetime | None,
    issues: list[str],
) -> tuple[bool, int | None]:
    previous_issue_count = len(issues)
    records = _exact(history, _HISTORY, "history", issues)
    attempts = records.get("attempts")
    effects = records.get("fill_effects")
    if type(attempts) is not list:
        issues.append("history.attempts.not_plain_list")
        attempts = []
    if type(effects) is not list:
        issues.append("history.fill_effects.not_plain_list")
        effects = []

    used = False
    for index, raw_attempt in enumerate(attempts):
        prefix = f"history.attempts.{index}"
        attempt = _exact(raw_attempt, _ATTEMPT, prefix, issues)
        if type(attempt.get("dispatch_started")) is not bool:
            issues.append(f"{prefix}.dispatch_started.invalid")
            continue
        if attempt.get("account_id") != request.get("account_id") or (
            attempt.get("arm_id") != request.get("arm_id")
        ):
            issues.append(f"{prefix}.foreign_account_or_arm")
        if (
            attempt.get("grant_id") == approval.get("grant_id")
            or attempt.get("logical_operation_id") == request.get("logical_operation_id")
            or attempt.get("client_token") == request.get("client_token")
        ):
            for field in ("logical_operation_id", "client_token"):
                if attempt.get(field) != request.get(field):
                    issues.append(f"{prefix}.operation_identity_conflict")
            if (
                attempt.get("bound_intent_sha256")
                != approval.get("bound_intent_sha256")
            ):
                issues.append(f"{prefix}.intent_changed")
            used = True
            if attempt["dispatch_started"]:
                issues.append("history.original_operation_already_dispatched")
            else:
                issues.append("history.original_operation_already_reserved")
        # A different historical operation never grants or restores this request.

    pause = state.get("pause_time_utc")
    pause_time = _time(pause) if pause is not None else None
    if pause is not None and pause_time is None:
        issues.append("state.pause_time_utc.invalid")
    if pause is not None and state.get("paused") is not True:
        issues.append("state.pause_time_requires_current_pause")
    if state.get("paused") is True and pause is None:
        issues.append("state.pause_evidence_missing")
    if pause_time is not None and as_of is not None and pause_time > as_of:
        issues.append("state.pause_time_from_future")

    seen_effects: dict[str, dict[str, object]] = {}
    post_pause = 0
    for index, raw_effect in enumerate(effects):
        prefix = f"history.fill_effects.{index}"
        effect = _exact(raw_effect, _FILL, prefix, issues)
        event_id = effect.get("effect_id")
        if not _text(event_id):
            issues.append(f"{prefix}.effect_id.missing")
            continue
        assert isinstance(event_id, str)
        if event_id in seen_effects:
            if effect != seen_effects[event_id]:
                issues.append(f"{prefix}.effect_id.conflicting_redelivery")
            continue
        seen_effects[event_id] = effect
        if (
            effect.get("account_id") != request.get("account_id")
            or effect.get("arm_id") != request.get("arm_id")
        ):
            issues.append(f"{prefix}.foreign_account_or_arm")
        if not _text(effect.get("client_token")):
            issues.append(f"{prefix}.client_token.missing")
        quantity = effect.get("incremental_quantity")
        if type(quantity) is not int or quantity <= 0:
            issues.append(f"{prefix}.incremental_quantity.invalid")
            continue
        occurred = _time(effect.get("occurred_utc"))
        if occurred is None:
            issues.append(f"{prefix}.occurred_utc.invalid")
        elif as_of is not None and occurred > as_of:
            issues.append(f"{prefix}.future_fill_cannot_be_observed")
        if effect.get("fee_state") not in ("KNOWN", "UNKNOWN"):
            issues.append(f"{prefix}.fee_state.invalid")
        elif effect.get("fee_state") == "UNKNOWN" and (
            state.get("portfolio_status") == "COMPLETE"
        ):
            issues.append(f"{prefix}.unknown_fee_blocks_complete_state")
        if pause_time is not None and occurred is not None:
            if occurred >= pause_time:
                post_pause += quantity
    return used, post_pause if len(issues) == previous_issue_count else None


def preflight_mandate_approval(payload: object) -> MandateApprovalPreflight:
    """Return only review-only diagnostics over untrusted synthetic evidence."""
    root = _object(payload)
    if root is None:
        return MandateApprovalPreflight(
            False, "REFUSED", False, None, ("payload.not_plain_object",)
        )
    problems: list[str] = []
    if set(root) != _ROOT:
        problems.append("payload.fields.not_exact")
    if root.get("profile") != "synthetic-mandate-review-v1":
        problems.append("profile.not_fixture_v1")
    now = _time(root.get("as_of_utc"))
    if now is None:
        problems.append("as_of_utc.invalid")
    if root.get("operation_kind") != "NEW_RISK":
        problems.append("operation.requires_separate_protective_authority")

    mandate = _exact(root.get("mandate"), _MANDATE, "mandate", problems)
    request = _exact(root.get("request"), _REQUEST, "request", problems)
    approval = _exact(root.get("approval"), _APPROVAL, "approval", problems)
    state = _exact(root.get("state"), _STATE, "state", problems)
    mandatory = _exact(
        root.get("mandatory_policy"), _MANDATORY, "mandatory_policy", problems,
    )

    _check_bindings(request, mandate, approval, state, mandatory, problems)
    if not _member(mandate.get("approval_mode"), _MODES):
        problems.append("mandate.approval_mode.invalid")
    if mandate.get("approval_mode") != approval.get("grant_mode"):
        problems.append("approval.mode_mismatch")
    if mandate.get("revoked") is not False:
        problems.append("mandate.revoked_or_unknown")
    if approval.get("decision") != "GRANTED":
        problems.append("approval.not_granted")
    for field in ("kill", "paused", "uncertainty_hold"):
        value = state.get(field)
        if type(value) is not bool:
            problems.append(f"state.{field}.invalid")
        elif value:
            problems.append(f"state.{field}.blocks_new_risk")
    if state.get("portfolio_status") != "COMPLETE":
        problems.append("state.portfolio_incomplete")
    if state.get("open_orders_status") != "COMPLETE":
        problems.append("state.open_orders_incomplete")
    _mandatory_gates(state, problems)

    if approval.get("issuer_role") != (
        "HUMAN" if mandate.get("approval_mode") == "ASK" else "SYSTEM"
    ):
        problems.append("approval.issuer_role_incompatible")
    if not _text(mandate.get("accepted_policy_ref")):
        problems.append("mandate.accepted_policy_ref.missing")
    if not _text(mandatory.get("policy_ref")):
        problems.append("mandatory_policy.policy_ref.missing")

    state_age, quote_age = _check_times(
        mandate, approval, state, now, problems
    )
    max_state = _decimal(mandatory.get("max_state_age_seconds"))
    max_quote = _decimal(mandatory.get("max_quote_age_seconds"))
    if max_state is None:
        problems.append("mandatory_policy.max_state_age_seconds.invalid")
    if max_quote is None:
        problems.append("mandatory_policy.max_quote_age_seconds.invalid")
    if state_age is not None and (
        state_age < 0 or (max_state is not None and state_age > max_state)
    ):
        problems.append("mandatory.state_stale")
    if quote_age is not None and (
        quote_age < 0 or (max_quote is not None and quote_age > max_quote)
    ):
        problems.append("mandatory.quote_stale")

    mode = mandate.get("approval_mode")
    route = "MANUAL_REVIEW_ONLY" if mode == "ASK" else "POLICY_REVIEW_ONLY"
    if mode == "SMART":
        route = _smart_route(
            root.get("smart_policy"), root.get("smart_observed"),
            mandatory, request, quote_age, state_age, problems,
        )
    elif root.get("smart_policy") is not None or (
        root.get("smart_observed") is not None
    ):
        problems.append("smart.undeclared_in_mode")

    used, post_pause = _history(
        root.get("history"), request, approval, state, now, problems,
    )

    if problems:
        return MandateApprovalPreflight(
            False,
            route if problems == ["smart.outside_proposed_bounds"] else "REFUSED",
            used, post_pause, tuple(problems),
        )
    return MandateApprovalPreflight(
        True, route, used, post_pause, (),
    )
