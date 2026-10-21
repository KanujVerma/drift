"""Deferred synthetic/adversarial AntiGravity vectors for #525/#379."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from scripts.execution_trace_preflight import preflight_execution_trace

SHA = "a" * 64


def trace_fixture() -> dict[str, object]:
    return {
        "profile": "drift-exec-intraday-v1",
        "request": {
            "run_id": "mock-run",
            "arm_id": "A",
            "account_id": "mock-account-A",
            "client_token": "original-token-A",
            "request_hash": SHA,
            "side": "BUY",
            "order_type": "LIMIT",
            "session": "REGULAR",
            "requested_qty": 100,
            "limit_price": "100.00",
        },
        "evidence": {
            "source_version_ref": "mock-version-v1",
            "input_cutoff_utc": "2026-01-02T10:32:06Z",
            "mandate_ref": "mock-mandate",
            "risk_ref": "mock-risk",
            "session_capability_ref": "mock-venue-capability",
            "venue_ref": "mock-listed-venue",
            "policy_revision_ref": "mock-sim-policy",
            "order_capability_ref": "mock-order-capability",
            "halt_at_arrival": "CLEAR",
        },
        "timeline": {
            "source_received_utc": "2026-01-02T10:32:03Z",
            "normalized_available_utc": "2026-01-02T10:32:04Z",
            "analysis_completed_utc": "2026-01-02T10:32:08Z",
            "decision_utc": "2026-01-02T10:32:09Z",
            "approval_utc": "2026-01-02T10:32:10Z",
            "risk_utc": "2026-01-02T10:32:10Z",
            "submission_utc": "2026-01-02T10:32:11Z",
            "arrival_utc": "2026-01-02T10:32:12Z",
        },
        "tie_proofs": {},
        "quote": {
            "kind": "EXECUTABLE_QUOTE",
            "quote_event_utc": "2026-01-02T10:32:06Z",
            "quote_received_utc": "2026-01-02T10:32:07Z",
            "max_age_seconds": "10",
            "quote_receipt_ref": "mock-quote",
        },
        "attempts": [
            {
                "client_token": "original-token-A",
                "request_hash": SHA,
                "dispatched": True,
            },
        ],
        "reports": [
            {
                "report_id": "fill-1",
                "cumulative_qty": 100,
                "execution_utc": "2026-01-02T10:32:13Z",
                "received_utc": "2026-01-02T10:32:14Z",
                "price": "99.99",
                "fee": "1.20",
                "fee_status": "known",
                "effect_ref": "ledger-effect-1",
            }
        ],
        "state": {
            "dispatch_knowledge": "ACKNOWLEDGED",
            "lifecycle": "FILLED",
            "claimed_accounting_complete": True,
            "terminal_receipt_ref": "mock-terminal",
            "ledger_receipt_ref": "mock-ledger",
            "valuation_receipt_ref": "mock-valuation",
        },
    }


def _inner(payload: dict[str, object], field: str) -> dict[str, object]:
    return cast(dict[str, object], payload[field])


def _reports(payload: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], payload["reports"])


def _attempts(payload: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], payload["attempts"])


def _fail(payload: dict[str, object], expected: str) -> None:
    report = preflight_execution_trace(payload)
    assert not report.review_ready
    assert report.reported_cumulative_qty is None
    assert not report.claimed_accounting_structurally_possible
    assert expected in report.reasons


def test_coherent_synthetic_trace_still_grants_nothing() -> None:
    report = preflight_execution_trace(trace_fixture())
    assert report.review_ready
    assert report.reported_cumulative_qty == 100
    assert report.claimed_accounting_structurally_possible
    assert report.reasons == ()
    assert not report.authorizes_order_placement
    assert not report.proves_fill_or_settlement


def test_partially_filled_order_retains_open_obligation() -> None:
    payload = trace_fixture()
    _inner(payload, "state")["lifecycle"] = "PARTIAL"
    _inner(payload, "state")["claimed_accounting_complete"] = False
    _reports(payload)[0]["cumulative_qty"] = 20
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 20
    assert not report.claimed_accounting_structurally_possible


def test_cumulative_fills_are_not_summed_or_recounted() -> None:
    payload = trace_fixture()
    _inner(payload, "request")["requested_qty"] = 10
    first = _reports(payload)[0]
    first["cumulative_qty"] = 5
    later = deepcopy(first)
    later["report_id"] = "fill-2"
    later["cumulative_qty"] = 10
    later["effect_ref"] = "ledger-effect-2"
    later["execution_utc"] = "2026-01-02T10:32:15Z"
    later["received_utc"] = "2026-01-02T10:32:16Z"
    _reports(payload).extend([later, deepcopy(first)])
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 10


def test_duplicate_id_with_mutated_payload_refuses() -> None:
    payload = trace_fixture()
    replay = deepcopy(_reports(payload)[0])
    replay["price"] = "80.00"
    _reports(payload).append(replay)
    _fail(payload, "reports.1.conflicting_redelivery")


def test_cumulative_decrease_refuses() -> None:
    payload = trace_fixture()
    earlier = _reports(payload)[0]
    earlier["cumulative_qty"] = 80
    second = deepcopy(earlier)
    second["report_id"] = "later-lower"
    second["cumulative_qty"] = 60
    _reports(payload).append(second)
    _fail(payload, "reports.1.cumulative_decreased")


@pytest.mark.parametrize(
    ("changed", "value", "reason"),
    [
        ("submission_utc", "2026-01-02T10:32:09Z",
         "causal.approval_utc->submission_utc.reversed"),
        ("normalized_available_utc", "2026-01-02T10:32:10Z",
         "causal.normalized_available_utc->input_cutoff_utc.reversed"),
        ("arrival_utc", "2026-01-02T10:32:10Z",
         "causal.submission_utc->arrival_utc.reversed"),
    ],
)
def test_early_actions_and_late_information_fail(
    changed: str, value: str, reason: str
) -> None:
    payload = trace_fixture()
    _inner(payload, "timeline")[changed] = value
    _fail(payload, reason)


def test_coarse_timestamp_requires_external_causal_proof() -> None:
    payload = trace_fixture()
    _inner(payload, "timeline")["normalized_available_utc"] = (
        "2026-01-02T10:32:03Z"
    )
    _fail(
        payload,
        "causal.source_received_utc->normalized_available_utc.tie_unproven",
    )
    _inner(payload, "tie_proofs")[
        "source_received_utc->normalized_available_utc"
    ] = "untrusted-external-ordering-reference"
    assert preflight_execution_trace(payload).review_ready


def test_quote_staleness_and_bar_only_fill_fail() -> None:
    payload = trace_fixture()
    _inner(payload, "quote")["max_age_seconds"] = "2"
    _fail(payload, "quote.stale_at_arrival")
    payload = trace_fixture()
    _inner(payload, "quote")["kind"] = "BAR_ONLY"
    _fail(payload, "fills.bar_only_cannot_prove_execution")


def test_extended_market_order_without_capability_refuses() -> None:
    payload = trace_fixture()
    _inner(payload, "request")["session"] = "POST"
    _inner(payload, "request")["order_type"] = "MARKET"
    _inner(payload, "request")["limit_price"] = None
    _fail(payload, "request.extended_session_requires_limit")


def test_halt_or_unknown_at_arrival_forbids_claimed_fill() -> None:
    payload = trace_fixture()
    _inner(payload, "evidence")["halt_at_arrival"] = "UNKNOWN"
    _fail(payload, "fills.halt_or_unknown_at_arrival")


def test_unknown_dispatch_cannot_be_reported_complete_or_resubmitted() -> None:
    payload = trace_fixture()
    _reports(payload).clear()
    state = _inner(payload, "state")
    state["dispatch_knowledge"] = "UNKNOWN"
    state["lifecycle"] = "UNKNOWN"
    state["claimed_accounting_complete"] = False
    report = preflight_execution_trace(payload)
    assert report.review_ready
    assert report.reported_cumulative_qty == 0
    assert not report.claimed_accounting_structurally_possible
    state["claimed_accounting_complete"] = True
    _fail(payload, "state.open_or_unknown_cannot_be_complete")
    state["claimed_accounting_complete"] = False
    _attempts(payload).append(
        {"client_token": "fresh-token", "request_hash": SHA, "dispatched": True}
    )
    _fail(payload, "attempts.1.new_or_foreign_token")


def test_unknown_fee_does_not_become_zero() -> None:
    payload = trace_fixture()
    _reports(payload)[0]["fee_status"] = "unknown"
    _reports(payload)[0]["fee"] = None
    _fail(payload, "state.unknown_dispatch_or_fee_cannot_be_complete")


def test_buy_limit_sell_limit_and_unknown_price() -> None:
    payload = trace_fixture()
    _reports(payload)[0]["price"] = "100.01"
    _fail(payload, "reports.0.buy_limit_exceeded")
    payload = trace_fixture()
    _inner(payload, "request")["side"] = "SELL"
    _reports(payload)[0]["price"] = "99.99"
    _fail(payload, "reports.0.sell_limit_exceeded")
    payload = trace_fixture()
    _reports(payload)[0]["price"] = "NaN"
    _fail(payload, "reports.0.price.invalid")


def test_duplicate_dispatch_and_foreign_intent_fail_closed() -> None:
    payload = trace_fixture()
    _attempts(payload).append(deepcopy(_attempts(payload)[0]))
    _fail(payload, "attempts.duplicate_placement")
    payload = trace_fixture()
    _attempts(payload)[0]["request_hash"] = "b" * 64
    _fail(payload, "attempts.0.changed_intent")


def test_partial_and_terminal_state_cannot_fake_completeness() -> None:
    payload = trace_fixture()
    _reports(payload)[0]["cumulative_qty"] = 20
    _inner(payload, "state")["lifecycle"] = "PARTIAL"
    _fail(payload, "state.open_or_unknown_cannot_be_complete")
    payload = trace_fixture()
    _inner(payload, "state")["ledger_receipt_ref"] = ""
    _fail(payload, "state.ledger_receipt_ref.missing_for_complete")


def test_malformed_payload_or_bools_cannot_be_accepted_as_counts() -> None:
    payload = trace_fixture()
    _inner(payload, "request")["requested_qty"] = True
    _fail(payload, "request.requested_qty.invalid")
    payload = trace_fixture()
    _reports(payload)[0]["cumulative_qty"] = True
    _fail(payload, "reports.0.cumulative_qty.invalid")
    assert not preflight_execution_trace([]).review_ready
