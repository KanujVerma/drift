"""A1 S3/S4 synthetic safety vectors for Matthew #411 / assist #533."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from scripts.unknown_execution_replay_preflight import (
    preflight_unknown_execution_replay,
)

HASH = "a" * 64


def fixture() -> dict[str, object]:
    return {
        "profile": "synthetic-unknown-replay-review-v1",
        "account_key": "mock-registered-account",
        "environment_ref": "mock-sandbox-environment",
        "journal_ref": "mock-single-journal",
        "context_ref": "mock-fixed-context",
        "intent_hash": HASH,
        "client_token": "mock-original-token",
        "events": [],
    }


def events(data: dict[str, object]) -> list[dict[str, object]]:
    raw = data["events"]
    assert type(raw) is list
    return raw


def append(
    data: dict[str, object],
    kind: str,
    **values: object,
) -> dict[str, object]:
    existing = events(data)
    sequence = len(existing) + 1
    event: dict[str, object] = {
        "event_id": f"mock-event-{sequence}",
        "sequence": sequence,
        "previous_event_id": (existing[-1]["event_id"] if existing else None),
        "kind": kind,
        "account_key": data["account_key"],
        "environment_ref": data["environment_ref"],
        "journal_ref": data["journal_ref"],
        "intent_hash": HASH,
        "client_token": data["client_token"],
        "observed_utc": f"2026-01-05T10:00:{sequence:02}Z",
        "evidence_ref": f"untrusted-journal-receipt-{sequence}",
        "reason_code": None,
        "broker_status": None,
        "cumulative_qty": None,
        "cumulative_fee_usd": None,
        "effect_id": None,
        "effect_quantity": None,
        "authority_ref": None,
        "quiescence_ref": None,
        "resolution_ref": None,
        "resume_mandate_ref": None,
        "expires_utc": None,
    }
    event.update(values)
    existing.append(event)
    return event


def started() -> dict[str, object]:
    data = fixture()
    append(data, "PREPARED")
    append(data, "SEND_STARTED")
    return data


def _fail(data: dict[str, object], expected: str) -> None:
    result = preflight_unknown_execution_replay(data)
    assert not result.structurally_reviewable
    assert result.claimed_phase == "INVALID"
    assert result.account_hold_required
    assert result.last_confirmed_cumulative_qty is None
    assert result.distinct_reported_fill_effect_qty is None
    assert expected in result.reasons
    assert not result.authorizes_dispatch_or_resumption


def test_prepared_then_send_without_broker_proof_requires_hold() -> None:
    data = started()
    result = preflight_unknown_execution_replay(data)
    assert result.structurally_reviewable
    assert result.claimed_phase == "SEND_STARTED"
    assert result.latest_broker_knowledge == "UNKNOWN"
    assert result.account_hold_required
    assert result.last_confirmed_cumulative_qty is None
    assert result.last_confirmed_cumulative_fee_usd is None
    assert not result.authorizes_dispatch_or_resumption
    assert not result.authenticates_journal_broker_or_ledger


def test_unknown_transport_does_not_invent_rejection_or_zero_exposure() -> None:
    data = started()
    append(
        data,
        "OBSERVED_UNKNOWN",
        reason_code="submission_unconfirmed",
    )
    report = preflight_unknown_execution_replay(data)
    assert report.structurally_reviewable
    assert report.claimed_phase == "UNKNOWN"
    assert report.latest_broker_knowledge == "UNKNOWN"
    assert report.last_confirmed_broker_status is None
    assert report.last_confirmed_cumulative_qty is None
    assert report.last_confirmed_cumulative_fee_usd is None


def test_known_partial_with_unknown_fee_remains_unsettled() -> None:
    data = started()
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="partially_filled",
        cumulative_qty=3,
        cumulative_fee_usd=None,
    )
    report = preflight_unknown_execution_replay(data)
    assert report.structurally_reviewable
    assert report.last_confirmed_cumulative_qty == 3
    assert report.last_confirmed_cumulative_fee_usd is None
    assert report.account_hold_required
    assert not report.authorizes_dispatch_or_resumption


def test_later_unknown_retains_historical_known_quantity_without_finality() -> None:
    data = started()
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="partially_filled",
        cumulative_qty=3,
        cumulative_fee_usd="0.50",
    )
    append(data, "OBSERVED_UNKNOWN", reason_code="cancellation_unconfirmed")
    report = preflight_unknown_execution_replay(data)
    assert report.structurally_reviewable
    assert report.latest_broker_knowledge == "UNKNOWN"
    assert report.last_confirmed_cumulative_qty == 3
    assert report.last_confirmed_broker_status == "partially_filled"
    assert report.last_confirmed_cumulative_fee_usd == Decimal("0.50")
    assert report.account_hold_required


def test_new_operation_during_pending_or_unknown_is_refused() -> None:
    data = started()
    append(data, "PREPARED")
    _fail(data, "account.new_operation_while_existing_or_held")
    data = started()
    append(data, "OBSERVED_UNKNOWN", reason_code="submission_unconfirmed")
    append(data, "PREPARED", client_token="a-new-token")
    _fail(data, "events.3.client_token.binding_mismatch")


def test_send_before_durable_prepared_record_is_refused() -> None:
    data = fixture()
    append(data, "SEND_STARTED")
    _fail(data, "events.0.send_started_without_unique_prepare")


def test_local_pre_dispatch_refusal_is_not_broker_rejection() -> None:
    data = fixture()
    append(data, "PREPARED")
    append(
        data,
        "NOT_SENT",
        authority_ref="untrusted-verified-refusal",
    )
    report = preflight_unknown_execution_replay(data)
    assert report.structurally_reviewable
    assert report.latest_broker_knowledge == "NOT_SENT"
    assert report.last_confirmed_broker_status is None
    assert report.account_hold_required


def test_not_sent_cannot_follow_possible_broker_dispatch() -> None:
    data = started()
    append(data, "NOT_SENT", authority_ref="claimed-local-refusal")
    _fail(data, "events.2.not_sent_without_proven_unsent")


def test_cancellation_request_never_implies_canceled_broker_order() -> None:
    data = started()
    append(data, "CANCEL_REQUESTED")
    report = preflight_unknown_execution_replay(data)
    assert report.structurally_reviewable
    assert report.latest_broker_knowledge == "UNKNOWN"
    assert report.last_confirmed_broker_status is None


def test_late_fill_after_pause_retains_economic_effect() -> None:
    data = started()
    append(data, "PAUSED")
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="partially_filled",
        cumulative_qty=2,
        cumulative_fee_usd="0.10",
    )
    append(data, "FILL_EFFECT", effect_id="posted-fill-1", effect_quantity=2)
    report = preflight_unknown_execution_replay(data)
    assert report.structurally_reviewable
    assert report.distinct_reported_fill_effect_qty == 2
    assert report.last_confirmed_cumulative_qty == 2
    assert report.account_hold_required


def test_redelivered_fill_effect_is_idempotent() -> None:
    data = started()
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="filled",
        cumulative_qty=5,
        cumulative_fee_usd="0.25",
    )
    append(data, "FILL_EFFECT", effect_id="effect-1", effect_quantity=5)
    append(data, "FILL_EFFECT", effect_id="effect-1", effect_quantity=5)
    result = preflight_unknown_execution_replay(data)
    assert result.structurally_reviewable
    assert result.distinct_reported_fill_effect_qty == 5


def test_conflicting_reused_effect_identity_is_refused() -> None:
    data = started()
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="filled",
        cumulative_qty=5,
        cumulative_fee_usd="0.25",
    )
    append(data, "FILL_EFFECT", effect_id="effect-1", effect_quantity=2)
    append(data, "FILL_EFFECT", effect_id="effect-1", effect_quantity=3)
    _fail(data, "events.4.effect_id.conflicting_redelivery")


def test_effect_beyond_latest_confirmed_quantity_is_refused() -> None:
    data = started()
    append(data, "FILL_EFFECT", effect_id="not-broker-backed", effect_quantity=2)
    _fail(data, "events.2.effect_not_backed_by_known_fill")


@pytest.mark.parametrize(
    ("field", "bad_value", "expected"),
    [
        ("broker_status", "unrecognized_status", "events.2.broker_status.unrecognized"),
        ("cumulative_qty", True, "events.2.cumulative_qty.invalid"),
        ("cumulative_fee_usd", "NaN", "events.2.cumulative_fee_usd.invalid"),
    ],
)
def test_unrecognized_broker_status_and_malformed_facts_refuse(
    field: str, bad_value: object, expected: str
) -> None:
    data = started()
    payload = {
        "broker_status": "filled",
        "cumulative_qty": 5,
        "cumulative_fee_usd": "0.25",
    }
    payload[field] = bad_value
    append(data, "OBSERVED_CONFIRMED", **payload)
    _fail(data, expected)


def test_UNKNOWN_record_cannot_carry_fabricated_rejection_or_zero_fee() -> None:
    data = started()
    append(
        data,
        "OBSERVED_UNKNOWN",
        reason_code="submission_unconfirmed",
        broker_status="rejected",
        cumulative_qty=0,
        cumulative_fee_usd="0",
    )
    _fail(data, "events.2.broker_status.not_allowed_for_OBSERVED_UNKNOWN")


def test_later_lower_cumulative_quantity_or_fee_is_not_valid() -> None:
    data = started()
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="partially_filled",
        cumulative_qty=10,
        cumulative_fee_usd="1.20",
    )
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="partially_filled",
        cumulative_qty=9,
        cumulative_fee_usd="0.50",
    )
    _fail(data, "events.3.cumulative_qty.regressed")


@pytest.mark.parametrize(
    "fees",
    [
        ("5", "4"),
        ("5", None, "4"),
        ("5", None, "0"),
        ("5", None, "4.999999999999"),
        ("5", None, None, "4"),
        ("5", "6", None, "5.50"),
        ("5", None, "6", None, "5.50"),
    ],
)
def test_known_cumulative_fee_floor_survives_missing_observations(
    fees: tuple[str | None, ...],
) -> None:
    data = started()
    for quantity, fee in enumerate(fees, start=1):
        append(
            data,
            "OBSERVED_CONFIRMED",
            broker_status="partially_filled",
            cumulative_qty=quantity,
            cumulative_fee_usd=fee,
        )
    # Quantities increase throughout, so only the fee evidence is contradictory.
    _fail(data, f"events.{len(fees) + 1}.cumulative_fee_usd.regressed")


@pytest.mark.parametrize(
    "fees",
    [
        ("5", None, "6"),
        ("5", None, "5"),
        ("5", None),
        ("5", None, None),
        ("0", None),
        (None, "0"),
        (None, "5", None, "6"),
    ],
)
def test_missing_current_fee_is_unavailable_without_erasing_the_known_bound(
    fees: tuple[str | None, ...],
) -> None:
    data = started()
    for quantity, fee in enumerate(fees, start=1):
        append(
            data,
            "OBSERVED_CONFIRMED",
            broker_status="partially_filled",
            cumulative_qty=quantity,
            cumulative_fee_usd=fee,
        )
    result = preflight_unknown_execution_replay(data)
    assert result.structurally_reviewable
    assert result.reasons == ()
    assert result.latest_broker_knowledge == "CONFIRMED"
    assert result.last_confirmed_cumulative_qty == len(fees)
    expected = None if fees[-1] is None else Decimal(fees[-1])
    assert result.last_confirmed_cumulative_fee_usd == expected
    assert result.account_hold_required
    assert not result.authorizes_dispatch_or_resumption
    assert not result.authenticates_journal_broker_or_ledger


def test_fee_gap_unknown_and_claimed_resolution_do_not_grant_resumption() -> None:
    data = started()
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="partially_filled",
        cumulative_qty=1,
        cumulative_fee_usd="5",
    )
    append(data, "OBSERVED_UNKNOWN", reason_code="cancellation_unconfirmed")
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="partially_filled",
        cumulative_qty=2,
        cumulative_fee_usd=None,
    )
    append(
        data,
        "OBSERVED_CONFIRMED",
        broker_status="filled",
        cumulative_qty=3,
        cumulative_fee_usd="6",
    )
    append(
        data,
        "RESOLVED",
        authority_ref="untrusted-authority",
        quiescence_ref="untrusted-fencing-proof",
        resolution_ref="untrusted-account-reconciliation",
    )
    append(
        data,
        "RESUMED",
        authority_ref="untrusted-resume-authority",
        resume_mandate_ref="untrusted-current-mandate",
        expires_utc="2026-01-05T11:00:00Z",
    )
    result = preflight_unknown_execution_replay(data)
    assert result.structurally_reviewable
    assert result.claimed_phase == "RESUMED_CLAIMED"
    assert result.latest_broker_knowledge == "UNVERIFIED_RESUMPTION"
    assert result.last_confirmed_broker_status == "filled"
    assert result.last_confirmed_cumulative_qty == 3
    assert result.last_confirmed_cumulative_fee_usd == Decimal("6")
    assert result.account_hold_required
    assert not result.authorizes_dispatch_or_resumption
    assert not result.authenticates_journal_broker_or_ledger


def test_same_event_id_changed_payload_is_a_conflict_not_redelivery() -> None:
    data = started()
    event = append(
        data,
        "OBSERVED_UNKNOWN",
        reason_code="submission_unconfirmed",
    )
    replay = deepcopy(event)
    events(data).append(replay)
    result = preflight_unknown_execution_replay(data)
    assert result.structurally_reviewable
    replay["reason_code"] = "evidence_conflict"
    _fail(data, "events.3.event_id.conflicting_redelivery")


def test_event_chain_and_temporal_order_are_bound() -> None:
    data = started()
    append(data, "OBSERVED_UNKNOWN", reason_code="submission_unconfirmed")
    events(data)[2]["previous_event_id"] = "unrelated"
    _fail(data, "events.2.predecessor_mismatch")
    data = started()
    append(
        data,
        "OBSERVED_UNKNOWN",
        reason_code="submission_unconfirmed",
        observed_utc="2026-01-05T10:00:02Z",
    )
    _fail(data, "events.2.observation_order.not_strict")
    data = started()
    append(data, "OBSERVED_UNKNOWN", reason_code="submission_unconfirmed")
    events(data)[2]["sequence"] = 200
    _fail(data, "events.2.sequence.gap_or_out_of_order")


def test_account_context_alias_and_journal_swap_do_not_clear_hold() -> None:
    data = started()
    append(data, "OBSERVED_UNKNOWN", reason_code="submission_unconfirmed")
    events(data)[2]["journal_ref"] = "alternative-journal"
    _fail(data, "events.2.journal_ref.binding_mismatch")
    data = started()
    append(
        data,
        "OBSERVED_UNKNOWN",
        reason_code="submission_unconfirmed",
        account_key="another-account",
    )
    _fail(data, "events.2.account_key.binding_mismatch")


def test_unverified_resolution_and_resumption_cannot_unhold_account() -> None:
    data = started()
    append(data, "OBSERVED_UNKNOWN", reason_code="submission_unconfirmed")
    append(
        data,
        "RESOLVED",
        authority_ref="untrusted-authority",
        quiescence_ref="untrusted-fencing-proof",
        resolution_ref="untrusted-account-reconciliation",
    )
    append(
        data,
        "RESUMED",
        authority_ref="untrusted-resume-authority",
        resume_mandate_ref="untrusted-current-mandate",
        expires_utc="2026-01-05T11:00:00Z",
    )
    report = preflight_unknown_execution_replay(data)
    assert report.structurally_reviewable
    assert report.claimed_phase == "RESUMED_CLAIMED"
    assert report.account_hold_required
    assert not report.authorizes_dispatch_or_resumption


def test_empty_resolution_readback_or_no_fencing_cannot_resume() -> None:
    data = started()
    append(data, "OBSERVED_UNKNOWN", reason_code="submission_unconfirmed")
    append(data, "RESOLVED", authority_ref="x", resolution_ref="empty-query")
    _fail(data, "events.3.quiescence_ref.missing")
    data = started()
    append(data, "RESUMED", authority_ref="x", resume_mandate_ref="y")
    _fail(data, "events.2.resumption_without_resolution")


def test_expired_claimed_resume_is_refused() -> None:
    data = started()
    append(data, "OBSERVED_UNKNOWN", reason_code="submission_unconfirmed")
    append(
        data,
        "RESOLVED",
        authority_ref="x",
        quiescence_ref="y",
        resolution_ref="z",
    )
    append(
        data,
        "RESUMED",
        authority_ref="x",
        resume_mandate_ref="y",
        expires_utc="2026-01-05T10:00:04Z",
    )
    _fail(data, "events.4.authorization_expired")


def test_hostile_nested_value_never_gets_python_comparison() -> None:
    class Exploit:
        def __eq__(self, _: object) -> bool:
            raise AssertionError("Unexpected caller-defined equality")

    data = started()
    events(data)[1]["journal_ref"] = Exploit()
    report = preflight_unknown_execution_replay(data)
    assert report.reasons == ("payload.not_plain_json",)
