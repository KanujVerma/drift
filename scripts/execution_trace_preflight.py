"""Untrusted offline execution-trace preflight for #525 and Matthew #379.

No broker access, simulation, fee calculation or mutable accounting occurs.
E3 remains a draft; this module cannot authorize execution or scored results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_MONEY = re.compile(r"(?:0|[1-9]\d*)(?:\.\d{1,12})?\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = frozenset(
    {
        "profile",
        "request",
        "evidence",
        "timeline",
        "tie_proofs",
        "quote",
        "attempts",
        "reports",
        "state",
    }
)
_REQUEST = frozenset(
    {
        "run_id",
        "arm_id",
        "account_id",
        "client_token",
        "request_hash",
        "side",
        "order_type",
        "session",
        "requested_qty",
        "limit_price",
        "listing_ref",
        "original_account_binding_ref",
    }
)
_EVIDENCE = frozenset(
    {
        "source_version_ref",
        "input_cutoff_utc",
        "mandate_ref",
        "risk_ref",
        "session_capability_ref",
        "venue_ref",
        "policy_revision_ref",
        "order_capability_ref",
        "halt_at_arrival",
    }
)
_TIMELINE = frozenset(
    {
        "source_received_utc",
        "normalized_available_utc",
        "analysis_completed_utc",
        "decision_utc",
        "approval_utc",
        "risk_utc",
        "submission_utc",
        "arrival_utc",
    }
)
_QUOTE = frozenset(
    {
        "kind",
        "quote_event_utc",
        "quote_received_utc",
        "max_age_seconds",
        "quote_receipt_ref",
        "venue_ref",
        "listing_ref",
    }
)
_ATTEMPT = frozenset({"client_token", "request_hash", "dispatched"})
_REPORT = frozenset(
    {
        "report_id",
        "cumulative_qty",
        "execution_utc",
        "received_utc",
        "price",
        "fee",
        "fee_status",
        "effect_ref",
        "run_id",
        "arm_id",
        "account_id",
        "client_token",
        "request_hash",
    }
)
_STATE = frozenset(
    {
        "dispatch_knowledge",
        "lifecycle",
        "claimed_accounting_complete",
        "terminal_receipt_ref",
        "ledger_receipt_ref",
        "valuation_receipt_ref",
    }
)
_EDGES = (
    ("source_received_utc", "normalized_available_utc"),
    ("normalized_available_utc", "input_cutoff_utc"),
    ("input_cutoff_utc", "decision_utc"),
    ("normalized_available_utc", "analysis_completed_utc"),
    ("analysis_completed_utc", "decision_utc"),
    ("decision_utc", "approval_utc"),
    ("decision_utc", "risk_utc"),
    ("approval_utc", "submission_utc"),
    ("risk_utc", "submission_utc"),
    ("submission_utc", "arrival_utc"),
    ("quote_event_utc", "quote_received_utc"),
    ("quote_received_utc", "decision_utc"),
    ("arrival_utc", "execution_utc"),
    ("execution_utc", "received_utc"),
)
_EDGE_NAMES = frozenset(f"{a}->{b}" for a, b in _EDGES)


@dataclass(frozen=True, slots=True)
class ExecutionTracePreflight:
    """Structural trace evidence, not an actual fill or account certificate."""

    review_ready: bool
    reported_cumulative_qty: int | None
    claimed_accounting_structurally_possible: bool
    reasons: tuple[str, ...]

    @property
    def authorizes_order_placement(self) -> bool:
        return False

    @property
    def proves_fill_or_settlement(self) -> bool:
        return False


def _map(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    if any(type(key) is not str for key in value):
        return None
    return cast(dict[str, object], value)


def _plain_json(value: object) -> bool:
    """Check concrete values before equality, without calling user methods.

    Iteration avoids a new nesting limit. Ancestors detect cycles while allowing
    shared plain containers, including an identical report supplied twice.
    """
    pending: list[tuple[object, bool]] = [(value, False)]
    ancestors: set[int] = set()
    checked: set[int] = set()
    while pending:
        item, leaving = pending.pop()
        kind = type(item)
        if item is None or kind is bool or kind is int or kind is float or kind is str:
            continue
        if kind is not list and kind is not dict:
            return False
        identity = id(item)
        if leaving:
            ancestors.remove(identity)
            checked.add(identity)
            continue
        if identity in checked:
            continue
        if identity in ancestors:
            return False
        ancestors.add(identity)
        pending.append((item, True))
        if kind is dict:
            mapping = cast(dict[object, object], item)
            if any(type(key) is not str for key in mapping):
                return False
            pending.extend((child, False) for child in mapping.values())
        else:
            pending.extend((child, False) for child in cast(list[object], item))
    return True


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _time(value: object) -> datetime | None:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return None
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return result if result.utcoffset() == timedelta(0) else None


def _amount(value: object, *, positive: bool) -> Decimal | None:
    if type(value) is not str or len(value) > 40:
        return None
    if _MONEY.fullmatch(value) is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or (positive and amount == 0):
        return None
    return amount


def _exact(
    data: dict[str, object] | None,
    expected: frozenset[str],
    name: str,
    problems: list[str],
) -> dict[str, object]:
    if data is None:
        problems.append(f"{name}.not_plain_object")
        return {}
    if set(data) != expected:
        problems.append(f"{name}.fields.not_exact")
    # Every field in these leaf records is scalar, including identity operands.
    if any(type(item) is list or type(item) is dict for item in data.values()):
        problems.append(f"{name}.not_plain_scalars")
        return {}
    return data


def _ordered(
    left: datetime | None,
    right: datetime | None,
    left_name: str,
    right_name: str,
    tie_proofs: dict[str, object],
    problems: list[str],
) -> None:
    if left is None or right is None:
        return
    edge = f"{left_name}->{right_name}"
    if left > right:
        problems.append(f"causal.{edge}.reversed")
    elif left == right and not _text(tie_proofs.get(edge)):
        problems.append(f"causal.{edge}.tie_unproven")


def _delta_microseconds(value: timedelta) -> int:
    return (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds


def preflight_execution_trace(payload: object) -> ExecutionTracePreflight:
    """Reject self-contradictory synthetic traces, without executing a trade."""
    root = _map(payload)
    if root is None:
        return ExecutionTracePreflight(
            False, None, False, ("payload.not_plain_object",)
        )
    if not _plain_json(root):
        return ExecutionTracePreflight(False, None, False, ("payload.not_plain_json",))
    problems: list[str] = []
    if set(root) != _ROOT:
        problems.append("payload.fields.not_exact")
    if root.get("profile") != "drift-exec-intraday-v1":
        problems.append("profile.not_provisional_E3")

    request = _exact(_map(root.get("request")), _REQUEST, "request", problems)
    evidence = _exact(_map(root.get("evidence")), _EVIDENCE, "evidence", problems)
    trace = _exact(_map(root.get("timeline")), _TIMELINE, "timeline", problems)
    quote = _exact(_map(root.get("quote")), _QUOTE, "quote", problems)
    state = _exact(_map(root.get("state")), _STATE, "state", problems)
    ties = _map(root.get("tie_proofs"))
    if ties is None:
        ties = {}
        problems.append("tie_proofs.not_plain_object")
    if any(name not in _EDGE_NAMES or not _text(ref) for name, ref in ties.items()):
        problems.append("tie_proofs.invalid_edge_or_ref")

    for field in (
        "run_id",
        "arm_id",
        "account_id",
        "client_token",
        "listing_ref",
        "original_account_binding_ref",
    ):
        if not _text(request.get(field)):
            problems.append(f"request.{field}.missing")
    request_hash = request.get("request_hash")
    if type(request_hash) is not str or _SHA256.fullmatch(request_hash) is None:
        problems.append("request.request_hash.invalid")
    side = request.get("side")
    if side not in ("BUY", "SELL"):
        problems.append("request.side.invalid")
    if request.get("order_type") not in ("LIMIT", "MARKET"):
        problems.append("request.order_type.invalid")
    if request.get("session") not in ("REGULAR", "PRE", "POST"):
        problems.append("request.session.invalid")
    qty = request.get("requested_qty")
    if type(qty) is not int or qty <= 0:
        problems.append("request.requested_qty.invalid")
        qty = None
    limit = request.get("limit_price")
    if request.get("order_type") == "LIMIT":
        limit = _amount(limit, positive=True)
        if limit is None:
            problems.append("request.limit_price.invalid")
    elif limit is not None:
        problems.append("request.market_order_has_limit_price")
    if request.get("session") in ("PRE", "POST"):
        if request.get("order_type") != "LIMIT":
            problems.append("request.extended_session_requires_limit")

    for field in (
        "source_version_ref",
        "mandate_ref",
        "risk_ref",
        "session_capability_ref",
        "venue_ref",
        "policy_revision_ref",
        "order_capability_ref",
    ):
        if not _text(evidence.get(field)):
            problems.append(f"evidence.{field}.missing")
    if evidence.get("halt_at_arrival") not in ("CLEAR", "HALTED", "UNKNOWN"):
        problems.append("evidence.halt_at_arrival.invalid")

    moments: dict[str, datetime | None] = {}
    for field in sorted(_TIMELINE):
        moments[field] = _time(trace.get(field))
        if moments[field] is None:
            problems.append(f"timeline.{field}.invalid")
    moments["input_cutoff_utc"] = _time(evidence.get("input_cutoff_utc"))
    if moments["input_cutoff_utc"] is None:
        problems.append("evidence.input_cutoff_utc.invalid")
    moments["quote_event_utc"] = _time(quote.get("quote_event_utc"))
    moments["quote_received_utc"] = _time(quote.get("quote_received_utc"))
    for name in ("quote_event_utc", "quote_received_utc"):
        if moments[name] is None:
            problems.append(f"quote.{name}.invalid")
    for start, end in _EDGES[:12]:
        _ordered(moments.get(start), moments.get(end), start, end, ties, problems)

    if quote.get("kind") not in ("EXECUTABLE_QUOTE", "BAR_ONLY"):
        problems.append("quote.kind.invalid")
    if not _text(quote.get("quote_receipt_ref")):
        problems.append("quote.quote_receipt_ref.missing")
    if not _text(quote.get("venue_ref")) or (
        quote.get("venue_ref") != evidence.get("venue_ref")
    ):
        problems.append("quote.venue_mismatch")
    if not _text(quote.get("listing_ref")) or (
        quote.get("listing_ref") != request.get("listing_ref")
    ):
        problems.append("quote.listing_mismatch")
    max_age = _amount(quote.get("max_age_seconds"), positive=False)
    if max_age is None:
        problems.append("quote.max_age_seconds.invalid")
    arrival = moments.get("arrival_utc")
    event_time = moments.get("quote_event_utc")
    if arrival is not None and event_time is not None and max_age is not None:
        age_us = _delta_microseconds(arrival - event_time)
        if age_us < 0:
            problems.append("quote.from_future")
        elif Decimal(age_us) > max_age * 1_000_000:
            problems.append("quote.stale_at_arrival")

    attempts = root.get("attempts")
    if type(attempts) is not list:
        attempts = []
        problems.append("attempts.not_plain_list")
    placed = 0
    for index, value in enumerate(attempts):
        entry = _exact(_map(value), _ATTEMPT, f"attempts.{index}", problems)
        if entry.get("client_token") != request.get("client_token"):
            problems.append(f"attempts.{index}.new_or_foreign_token")
        if entry.get("request_hash") != request_hash:
            problems.append(f"attempts.{index}.changed_intent")
        if type(entry.get("dispatched")) is not bool:
            problems.append(f"attempts.{index}.dispatched.invalid")
        elif entry["dispatched"]:
            placed += 1
    if placed > 1:
        problems.append("attempts.duplicate_placement")

    reports = root.get("reports")
    if type(reports) is not list:
        reports = []
        problems.append("reports.not_plain_list")
    report_ids: dict[str, dict[str, object]] = {}
    used_effects: set[str] = set()
    cumulative = 0
    unknown_fee = False
    prior_report_execution: datetime | None = None
    prior_report_receipt: datetime | None = None
    for index, value in enumerate(reports):
        report = _exact(_map(value), _REPORT, f"reports.{index}", problems)
        report_id = report.get("report_id")
        if not _text(report_id):
            problems.append(f"reports.{index}.report_id.missing")
            continue
        assert isinstance(report_id, str)
        for name in (
            "run_id",
            "arm_id",
            "account_id",
            "client_token",
            "request_hash",
        ):
            if report.get(name) != request.get(name):
                problems.append(f"reports.{index}.{name}.identity_mismatch")
        original = report_ids.get(report_id)
        if original is not None:
            if report != original:
                problems.append(f"reports.{index}.conflicting_redelivery")
            continue
        report_ids[report_id] = report
        count = report.get("cumulative_qty")
        if type(count) is not int or count < 0:
            problems.append(f"reports.{index}.cumulative_qty.invalid")
            continue
        if count < cumulative:
            problems.append(f"reports.{index}.cumulative_decreased")
        if type(qty) is int and count > qty:
            problems.append(f"reports.{index}.overfill")
        if count > cumulative:
            effect = report.get("effect_ref")
            if not _text(effect):
                problems.append(f"reports.{index}.effect_ref.missing")
            elif effect in used_effects:
                problems.append(f"reports.{index}.effect_ref.reused")
            if type(effect) is str:
                used_effects.add(effect)
        execution = _time(report.get("execution_utc"))
        received = _time(report.get("received_utc"))
        if execution is None or received is None:
            problems.append(f"reports.{index}.time.invalid")
        if execution is not None:
            if (
                prior_report_execution is not None
                and execution < prior_report_execution
            ):
                problems.append(f"reports.{index}.execution_time_reversed")
            prior_report_execution = execution
        if received is not None:
            if prior_report_receipt is not None and received < prior_report_receipt:
                problems.append(f"reports.{index}.receipt_time_reversed")
            prior_report_receipt = received
        _ordered(
            arrival,
            execution,
            "arrival_utc",
            "execution_utc",
            ties,
            problems,
        )
        _ordered(
            execution,
            received,
            "execution_utc",
            "received_utc",
            ties,
            problems,
        )
        price = _amount(report.get("price"), positive=True)
        if price is None:
            problems.append(f"reports.{index}.price.invalid")
        elif isinstance(limit, Decimal):
            if side == "BUY" and price > limit:
                problems.append(f"reports.{index}.buy_limit_exceeded")
            elif side == "SELL" and price < limit:
                problems.append(f"reports.{index}.sell_limit_exceeded")
        if report.get("fee_status") == "known":
            if _amount(report.get("fee"), positive=False) is None:
                problems.append(f"reports.{index}.fee.invalid")
        elif report.get("fee_status") == "unknown":
            unknown_fee = True
            if report.get("fee") is not None:
                problems.append(f"reports.{index}.unknown_fee_must_not_be_zero")
        else:
            problems.append(f"reports.{index}.fee_status.invalid")
        cumulative = max(cumulative, count)

    if cumulative > 0:
        if quote.get("kind") == "BAR_ONLY":
            problems.append("fills.bar_only_cannot_prove_execution")
        if evidence.get("halt_at_arrival") != "CLEAR":
            problems.append("fills.halt_or_unknown_at_arrival")
        if placed != 1:
            problems.append("fills.no_unique_original_dispatch")

    dispatch = state.get("dispatch_knowledge")
    if dispatch not in ("UNSENT", "SENT", "ACKNOWLEDGED", "UNKNOWN"):
        problems.append("state.dispatch_knowledge.invalid")
    elif dispatch == "UNSENT" and placed:
        problems.append("state.unsent_has_dispatch")
    elif dispatch != "UNSENT" and placed != 1:
        problems.append("state.dispatch_without_unique_attempt")
    lifecycle = state.get("lifecycle")
    if lifecycle not in (
        "REFUSED",
        "OPEN",
        "PARTIAL",
        "FILLED",
        "CANCELLED",
        "EXPIRED",
        "UNKNOWN",
    ):
        problems.append("state.lifecycle.invalid")
    if lifecycle == "REFUSED" and (placed or cumulative):
        problems.append("state.refused_with_dispatch_or_fill")
    if lifecycle == "FILLED" and (type(qty) is not int or cumulative != qty):
        problems.append("state.filled_without_full_cumulative_qty")
    if lifecycle == "PARTIAL" and (type(qty) is not int or not 0 < cumulative < qty):
        problems.append("state.partial_inconsistent")
    if dispatch == "UNKNOWN" and lifecycle != "UNKNOWN":
        problems.append("state.unknown_dispatch_cannot_be_terminal")

    complete = state.get("claimed_accounting_complete")
    if type(complete) is not bool:
        problems.append("state.claimed_accounting_complete.invalid")
        complete = False
    if complete:
        if lifecycle not in ("FILLED", "CANCELLED", "EXPIRED", "REFUSED"):
            problems.append("state.open_or_unknown_cannot_be_complete")
        if dispatch == "UNKNOWN" or unknown_fee:
            problems.append("state.unknown_dispatch_or_fee_cannot_be_complete")
        for field in (
            "terminal_receipt_ref",
            "ledger_receipt_ref",
            "valuation_receipt_ref",
        ):
            if not _text(state.get(field)):
                problems.append(f"state.{field}.missing_for_complete")

    ready = not problems
    return ExecutionTracePreflight(
        ready,
        cumulative if ready else None,
        bool(complete) and ready,
        tuple(problems),
    )
