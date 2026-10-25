"""Synthetic real V1 broker report evidence test oracles for Matthew #411."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid7

import pytest

from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    OrderType,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.v1_evidence_audit import (
    SourceClaim,
    V1ExecutionAudit,
    V1OriginalEvidenceClaim,
    audit_execution_v1_originals,
)

T0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
SESSION = SessionKeyV1(
    mic="XNAS",
    session_scope="regular",
    local_date=date(2026, 10, 20),
)


def intent() -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id="synthetic-client-token-1",
        session_key=SESSION,
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        created_at=T0,
    )


def report(
    order: OrderIntentV1,
    *,
    seconds: int = 1,
    status: ExecutionStatus = ExecutionStatus.ACKNOWLEDGED,
    quantity: int = 0,
    leaves: int = 5,
    broker_id: str | None = "mock-order",
    reason: str | None = None,
    fee: str = "0",
    report_id: UUID | None = None,
) -> ExecutionReportV1:
    return build_execution_report(
        report_id=report_id or uuid7(),
        intent_id=order.intent_id,
        broker_order_id=broker_id,
        status=status,
        cum_quantity=quantity,
        leaves_quantity=leaves,
        fee_amount=Decimal(fee),
        rejection_reason=reason,
        reported_at=T0 + timedelta(seconds=seconds),
        avg_fill_price=Decimal("100") if quantity > 0 else None,
        last_fill_price=Decimal("100") if quantity > 0 else None,
        last_fill_quantity=quantity if quantity > 0 else None,
    )


def claim(
    rep: ExecutionReportV1,
    *,
    source_kind: SourceClaim = "BROKER_OBSERVED",
    source_ref: str | None = "unverified-native-broker-receipt",
    available_seconds: int | None = 2,
    fee_ref: str | None = None,
) -> V1OriginalEvidenceClaim:
    return V1OriginalEvidenceClaim(
        report_id=rep.report_id,
        source_kind=source_kind,
        source_receipt_ref=source_ref,
        original_available_at=(
            None
            if available_seconds is None
            else T0 + timedelta(seconds=available_seconds)
        ),
        fee_receipt_ref=fee_ref,
    )


def examine(
    order: OrderIntentV1,
    reps: Sequence[ExecutionReportV1],
    evidences: Sequence[V1OriginalEvidenceClaim],
    *,
    as_of: datetime = T0 + timedelta(seconds=30),
) -> V1ExecutionAudit:
    return audit_execution_v1_originals(
        intent=order,
        reports=reps,
        claims=evidences,
        as_of_utc=as_of,
    )


def refuse(out: V1ExecutionAudit, code: str) -> None:
    assert not out.structurally_reviewable
    assert out.conservative_broker_knowledge == "UNKNOWN"
    assert out.largest_claimed_cumulative_fill is None
    assert not out.claimed_original_fee_complete
    assert code in out.flagged_reasons
    assert not out.authenticates_original_broker_or_account
    assert not out.authorizes_submission_cancellation_or_retry
    assert not out.proves_execution_or_settlement_complete


def test_acknowledged_v1_from_claim_is_not_authenticated_broker() -> None:
    order = intent()
    a = report(order)
    out = examine(order, (a,), (claim(a),))
    assert out.structurally_reviewable
    assert out.claimed_last_v1_status == "acknowledged"
    assert out.conservative_broker_knowledge == "V1_ORIGIN_CLAIM_ONLY"
    assert out.largest_claimed_cumulative_fill == 0
    assert not out.claimed_original_fee_complete
    assert out.distinct_report_hashes == (a.report_hash,)
    assert not out.authenticates_original_broker_or_account
    assert not out.authorizes_submission_cancellation_or_retry


def test_same_v1_zero_fee_requires_a_separate_original_fee_claim() -> None:
    order = intent()
    a = report(order, seconds=1)
    without = examine(order, (a,), (claim(a),))
    with_unverified = examine(
        order, (a,), (claim(a, fee_ref="unverified-zero-fee-source"),)
    )
    assert without.structurally_reviewable
    assert not without.claimed_original_fee_complete
    assert with_unverified.claimed_original_fee_complete
    assert not with_unverified.proves_execution_or_settlement_complete


def test_transport_timeout_current_robinhood_pattern_cannot_be_rejection() -> None:
    order = intent()
    a = report(
        order,
        broker_id=None,
        status=ExecutionStatus.REJECTED,
        reason="mcp_submission_timeout: synthetic transport error",
    )
    out = examine(
        order,
        (a,),
        (
            claim(
                a,
                source_kind="UNCONFIRMED_TRANSPORT",
                source_ref="untrusted-transport-error",
            ),
        ),
    )
    refuse(out, "REPORT_0_UNCONFIRMED_AS_TERMINAL_V1")
    assert out.claimed_last_v1_status == "rejected"


def test_mcp_transport_error_as_rejected_is_not_broker_confirmation() -> None:
    order = intent()
    a = report(
        order,
        broker_id=None,
        status=ExecutionStatus.REJECTED,
        reason="mcp_error: unconfirmed synthetic side effect",
    )
    out = examine(order, (a,), (claim(a),))
    refuse(out, "REPORT_0_UNCONFIRMED_AS_TERMINAL_V1")
    assert "REPORT_0_BROKER_PROOF_CONTRADICTED" in out.flagged_reasons


def test_cancellation_failed_cannot_look_like_canceled() -> None:
    order = intent()
    a = report(
        order,
        status=ExecutionStatus.CANCELED,
        broker_id="test-order",
        reason="cancellation_failed: timeout",
    )
    out = examine(order, (a,), (claim(a, source_kind="UNCONFIRMED_TRANSPORT"),))
    refuse(out, "REPORT_0_UNCONFIRMED_AS_TERMINAL_V1")


def test_rejected_broker_status_with_no_original_receipt_cannot_prove_it() -> None:
    order = intent()
    a = report(
        order,
        status=ExecutionStatus.REJECTED,
        broker_id=None,
        reason="insufficient_buying_power",
    )
    out = examine(order, (a,), (claim(a, source_ref=None),))
    refuse(out, "REPORT_0_ORIGINAL_RECEIPT_CLAIM_MISSING")


def test_original_local_before_send_refusal_preserves_no_broker_fact() -> None:
    order = intent()
    a = report(
        order,
        status=ExecutionStatus.REJECTED,
        broker_id=None,
        reason="unmapped security_id: local policy refusal",
        quantity=0,
        leaves=5,
    )
    out = examine(
        order,
        (a,),
        (
            claim(
                a,
                source_kind="LOCAL_BEFORE_SEND",
                source_ref="unverified-local-policy-receipt",
            ),
        ),
    )
    assert out.structurally_reviewable
    assert not out.authenticates_original_broker_or_account
    assert not out.proves_execution_or_settlement_complete


def test_untrusted_claimed_fill_still_cannot_settle_portfolio() -> None:
    order = intent()
    full = report(
        order,
        status=ExecutionStatus.FILLED,
        quantity=5,
        leaves=0,
        fee="1.50",
    )
    out = examine(
        order,
        (full,),
        (claim(full, fee_ref="unverified-fee-receipt"),),
    )
    assert out.structurally_reviewable
    assert out.largest_claimed_cumulative_fill == 5
    assert out.claimed_original_fee_complete
    assert not out.proves_execution_or_settlement_complete


@pytest.mark.parametrize("source_kind", ["LOCAL_BEFORE_SEND", "BROKER_OBSERVED"])
@pytest.mark.parametrize(
    ("later_status", "quantity", "leaves"),
    [
        (ExecutionStatus.PARTIALLY_FILLED, 2, 3),
        (ExecutionStatus.FILLED, 5, 0),
    ],
)
def test_original_rejection_claim_cannot_be_followed_by_same_intent_fill(
    source_kind: SourceClaim,
    later_status: ExecutionStatus,
    quantity: int,
    leaves: int,
) -> None:
    order = intent()
    rejected = report(
        order,
        status=ExecutionStatus.REJECTED,
        broker_id=None,
        reason="synthetic explicit rejection",
    )
    later = report(
        order,
        seconds=3,
        status=later_status,
        quantity=quantity,
        leaves=leaves,
        fee="1.50",
    )
    assert rejected.intent_id == later.intent_id == order.intent_id
    outcome = examine(
        order,
        (rejected, later),
        (
            claim(rejected, source_kind=source_kind, fee_ref="unverified-zero-fee"),
            claim(later, available_seconds=4, fee_ref="unverified-fill-fee"),
        ),
    )
    reason = (
        "REPORT_1_LOCAL_NO_SEND_CONTRADICTED_BY_LATER_FILL"
        if source_kind == "LOCAL_BEFORE_SEND"
        else "REPORT_1_FILL_AFTER_CLAIMED_BROKER_REJECTION"
    )
    refuse(outcome, reason)
    assert outcome.claimed_last_v1_status == later_status.value
    assert outcome.distinct_report_hashes == ()


@pytest.mark.parametrize("source_kind", ["UNCONFIRMED_TRANSPORT", "UNVERIFIED"])
@pytest.mark.parametrize(
    "initial_status", [ExecutionStatus.ACKNOWLEDGED, ExecutionStatus.REJECTED]
)
def test_uncertain_original_claim_is_not_a_definite_rejection_latch(
    source_kind: SourceClaim, initial_status: ExecutionStatus
) -> None:
    order = intent()
    uncertain = report(
        order,
        status=initial_status,
        broker_id=None,
        reason=(
            "synthetic uncertain rejection label"
            if initial_status is ExecutionStatus.REJECTED
            else None
        ),
    )
    resolved = report(
        order,
        seconds=3,
        status=ExecutionStatus.FILLED,
        quantity=5,
        leaves=0,
    )
    outcome = examine(
        order,
        (uncertain, resolved),
        (
            claim(uncertain, source_kind=source_kind),
            claim(resolved, available_seconds=4),
        ),
    )
    assert outcome.structurally_reviewable
    assert outcome.flagged_reasons == ()
    assert outcome.claimed_last_v1_status == "filled"
    assert outcome.largest_claimed_cumulative_fill == 5
    assert outcome.conservative_broker_knowledge == "UNKNOWN"
    assert not outcome.claimed_original_fee_complete
    assert not outcome.authenticates_original_broker_or_account
    assert not outcome.authorizes_submission_cancellation_or_retry
    assert not outcome.proves_execution_or_settlement_complete


def test_claimed_broker_rejection_without_later_fill_remains_idempotent() -> None:
    order = intent()
    rejected = report(
        order,
        status=ExecutionStatus.REJECTED,
        broker_id=None,
        reason="synthetic explicit broker rejection",
    )
    evidence = claim(rejected)
    original = examine(order, (rejected,), (evidence,))
    redelivered = examine(order, (rejected, rejected), (evidence,))
    assert original == redelivered
    assert original.structurally_reviewable
    assert original.flagged_reasons == ()
    assert original.conservative_broker_knowledge == "V1_ORIGIN_CLAIM_ONLY"
    assert original.largest_claimed_cumulative_fill == 0
    assert not original.authenticates_original_broker_or_account
    assert not original.authorizes_submission_cancellation_or_retry
    assert not original.proves_execution_or_settlement_complete


@pytest.mark.parametrize(
    "later_status", [ExecutionStatus.CANCELED, ExecutionStatus.REJECTED]
)
def test_nonfill_terminal_report_can_carry_prior_cumulative_quantity(
    later_status: ExecutionStatus,
) -> None:
    order = intent()
    partial = report(
        order,
        status=ExecutionStatus.PARTIALLY_FILLED,
        quantity=2,
        leaves=3,
    )
    rejected = build_execution_report(
        report_id=uuid7(),
        intent_id=order.intent_id,
        broker_order_id="mock-order",
        status=ExecutionStatus.REJECTED,
        cum_quantity=2,
        leaves_quantity=3,
        avg_fill_price=Decimal("100"),
        rejection_reason="synthetic remainder rejection",
        reported_at=T0 + timedelta(seconds=3),
    )
    later = build_execution_report(
        report_id=uuid7(),
        intent_id=order.intent_id,
        broker_order_id="mock-order",
        status=later_status,
        cum_quantity=2,
        leaves_quantity=3,
        avg_fill_price=Decimal("100"),
        rejection_reason=(
            "synthetic repeated remainder rejection"
            if later_status is ExecutionStatus.REJECTED
            else None
        ),
        reported_at=T0 + timedelta(seconds=5),
    )
    assert rejected.last_fill_quantity is None
    assert later.last_fill_quantity is None
    outcome = examine(
        order,
        (partial, rejected, later),
        (
            claim(partial),
            claim(rejected, available_seconds=4),
            claim(later, available_seconds=6),
        ),
    )
    assert outcome.structurally_reviewable
    assert outcome.flagged_reasons == ()
    assert outcome.claimed_last_v1_status == later_status.value
    assert outcome.largest_claimed_cumulative_fill == 2
    assert outcome.conservative_broker_knowledge == "V1_ORIGIN_CLAIM_ONLY"
    assert not outcome.claimed_original_fee_complete
    assert not outcome.authenticates_original_broker_or_account
    assert not outcome.authorizes_submission_cancellation_or_retry
    assert not outcome.proves_execution_or_settlement_complete


def test_cumulative_partial_then_complete_is_structurally_consistent() -> None:
    order = intent()
    part = report(
        order,
        status=ExecutionStatus.PARTIALLY_FILLED,
        seconds=1,
        quantity=2,
        leaves=3,
        fee="0.25",
    )
    full = report(
        order,
        status=ExecutionStatus.FILLED,
        seconds=3,
        quantity=5,
        leaves=0,
        fee="0.75",
    )
    out = examine(
        order,
        (part, full),
        (claim(part), claim(full, available_seconds=4)),
    )
    assert out.structurally_reviewable
    assert out.largest_claimed_cumulative_fill == 5
    assert out.distinct_report_hashes == (part.report_hash, full.report_hash)
    assert not out.claimed_original_fee_complete


def test_exact_same_v1_report_id_redelivery_is_idempotent() -> None:
    order = intent()
    a = report(order)
    out = examine(order, (a, a), (claim(a),))
    assert out.structurally_reviewable
    assert out.distinct_report_hashes == (a.report_hash,)


def test_conflicting_same_report_id_must_fail_closed() -> None:
    order = intent()
    report_id = uuid7()
    a = report(order, status=ExecutionStatus.ACKNOWLEDGED, report_id=report_id)
    b = report(
        order,
        status=ExecutionStatus.REJECTED,
        report_id=report_id,
        broker_id=None,
        reason="test rejection",
    )
    out = examine(order, (a, b), (claim(a),))
    refuse(out, "REPORT_1_CONFLICTING_ID_REDELIVERY")


def test_reports_from_different_intents_are_not_one_account() -> None:
    order = intent()
    foreign = intent()
    a = report(foreign)
    out = examine(order, (a,), (claim(a),))
    refuse(out, "REPORT_0_FOREIGN_INTENT")


def test_out_of_order_or_future_source_receipt_cannot_be_historical_fact() -> None:
    order = intent()
    a = report(order, seconds=3)
    b = report(order, seconds=1)
    refuse(
        examine(
            order,
            (a, b),
            (
                claim(a),
                claim(b),
            ),
        ),
        "REPORT_1_NOT_STRICTLY_ORDERED",
    )
    refuse(
        examine(
            order,
            (a,),
            (claim(a, available_seconds=45),),
        ),
        "REPORT_0_ORIGINAL_UNAVAILABLE_AT_CUTOFF",
    )


def test_regressing_or_overfilled_cumulative_report_is_not_valid() -> None:
    order = intent()
    partial = report(
        order,
        status=ExecutionStatus.PARTIALLY_FILLED,
        quantity=3,
        leaves=2,
    )
    lower = report(
        order,
        seconds=3,
        status=ExecutionStatus.PARTIALLY_FILLED,
        quantity=2,
        leaves=3,
    )
    refuse(
        examine(
            order, (partial, lower), (claim(partial), claim(lower, available_seconds=4))
        ),
        "REPORT_1_CUMULATIVE_QUANTITY_REGRESSED",
    )
    over = report(
        order,
        status=ExecutionStatus.FILLED,
        quantity=6,
        leaves=0,
    )
    refuse(
        examine(order, (over,), (claim(over),)),
        "REPORT_0_OVERFILLS_INTENT",
    )


def test_filled_v1_incomplete_quantity_is_not_final_account_reconciliation() -> None:
    order = intent()
    bad = report(
        order,
        status=ExecutionStatus.FILLED,
        quantity=2,
        leaves=0,
    )
    refuse(
        examine(order, (bad,), (claim(bad),)),
        "REPORT_0_FILLED_WITH_UNRECONCILED_QUANTITY",
    )


def test_missing_original_claims_can_never_assume_trust() -> None:
    order = intent()
    a = report(order)
    refuse(examine(order, (a,), ()), "ORIGINAL_REPORT_AND_CLAIM_SET_MISMATCH")


def test_non_utc_review_cutoff_refuses() -> None:
    order = intent()
    a = report(order)
    out = examine(
        order,
        (a,),
        (claim(a),),
        as_of=datetime(2026, 10, 20, 10, 2),
    )
    refuse(out, "AS_OF_UTC_INVALID")


def test_subclassed_or_constructed_forgeries_do_not_bypass_original_v1() -> None:
    order = intent()
    a = report(order)
    forged = type(a).model_construct(
        **(
            a.model_dump(mode="python")
            | {
                "status": "silently-successful",
            }
        )
    )
    refuse(
        examine(order, (forged,), (claim(a),)),
        "REPORT_0_ORIGINAL_INVALID",
    )


def test_original_claim_wrong_report_id_is_not_a_valid_join() -> None:
    order = intent()
    a = report(order)
    c = replace(claim(a), report_id=uuid7())
    refuse(
        examine(order, (a,), (c,)),
        "ORIGINAL_REPORT_AND_CLAIM_SET_MISMATCH",
    )


@pytest.mark.parametrize(
    "invalid_available_at",
    [
        datetime(2026, 10, 20, 10, 0, 2),
        datetime(2026, 10, 20, 10, 0, 2, tzinfo=timezone(timedelta(hours=1))),
        "2026-10-20T10:00:02Z",
        7,
    ],
)
def test_malformed_original_clock_refuses_before_ordering_comparison(
    invalid_available_at: object,
) -> None:
    order = intent()
    original = report(order)
    declaration = replace(
        claim(original),
        original_available_at=cast(datetime, invalid_available_at),
    )
    outcome = examine(order, (original,), (declaration,))
    refuse(outcome, "CLAIM_0_ORIGINAL_CLOCK_INVALID")
