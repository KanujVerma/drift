"""Read-only source-backed V1 broker evidence and uncertainty audit for #543.

Consumes accepted OrderIntentV1 / ExecutionReportV1, not a new EXEC wire.
This module does not invoke an adapter, issue an order, create/cancel risk,
relabel persisted V1 reports, or grant any account dispatch authority.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
)

type SourceClaim = Literal[
    "BROKER_OBSERVED",
    "LOCAL_BEFORE_SEND",
    "UNCONFIRMED_TRANSPORT",
    "UNVERIFIED",
]

_AMBIGUOUS_PREFIXES = (
    "mcp_submission_timeout:",
    "mcp_error:",
    "cancellation_failed:",
)


@dataclass(frozen=True, slots=True)
class V1OriginalEvidenceClaim:
    """Untrusted declaration about a single original V1 execution report."""

    report_id: UUID
    source_kind: SourceClaim
    source_receipt_ref: str | None
    original_available_at: datetime | None
    fee_receipt_ref: str | None = None


@dataclass(frozen=True, slots=True)
class V1ExecutionAudit:
    structurally_reviewable: bool
    claimed_last_v1_status: str | None
    conservative_broker_knowledge: str
    largest_claimed_cumulative_fill: int | None
    claimed_original_fee_complete: bool
    distinct_report_hashes: tuple[str, ...]
    flagged_reasons: tuple[str, ...]

    @property
    def authenticates_original_broker_or_account(self) -> bool:
        return False

    @property
    def authorizes_submission_cancellation_or_retry(self) -> bool:
        return False

    @property
    def proves_execution_or_settlement_complete(self) -> bool:
        return False


def _utc(instant: object) -> bool:
    return (
        type(instant) is datetime
        and instant.tzinfo is not None
        and instant.utcoffset() == timedelta(0)
    )


def _ref(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= 1024


def _reparse_intent(raw: object) -> OrderIntentV1:
    if type(raw) is not OrderIntentV1:
        raise ValueError("ORIGINAL_INTENT_WRONG_TYPE")
    return OrderIntentV1.model_validate(raw.model_dump(mode="python"))


def _reparse_report(raw: object) -> ExecutionReportV1:
    if type(raw) is not ExecutionReportV1:
        raise ValueError("ORIGINAL_REPORT_WRONG_TYPE")
    return ExecutionReportV1.model_validate(raw.model_dump(mode="python"))


def audit_execution_v1_originals(
    *,
    intent: OrderIntentV1,
    reports: Sequence[ExecutionReportV1],
    claims: Sequence[V1OriginalEvidenceClaim],
    as_of_utc: datetime,
) -> V1ExecutionAudit:
    """Audit a supplied ordered V1 sequence using explicit untrusted evidence.

    The existing V1 report defaults an absent fee to zero and can map a
    transport error to REJECTED. This auditor never treats either as
    independent broker evidence or an account reconciliation.
    """
    issues: list[str] = []
    if not _utc(as_of_utc):
        issues.append("AS_OF_UTC_INVALID")
    try:
        original_intent = _reparse_intent(intent)
    except ValueError, TypeError, ValidationError:
        return V1ExecutionAudit(
            False,
            None,
            "UNKNOWN",
            None,
            False,
            (),
            ("ORIGINAL_INTENT_INVALID",),
        )

    if type(reports) not in (tuple, list):
        issues.append("REPORT_SEQUENCE_NOT_PLAIN")
        reports = ()
    if type(claims) not in (tuple, list):
        issues.append("CLAIM_SEQUENCE_NOT_PLAIN")
        claims = ()
    if len(reports) > 512 or len(claims) > 512:
        issues.append("REPORT_REVIEW_BUDGET_EXCEEDED")
        reports = ()
        claims = ()

    evidence: dict[UUID, V1OriginalEvidenceClaim] = {}
    for index, declaration in enumerate(claims):
        if type(declaration) is not V1OriginalEvidenceClaim:
            issues.append(f"CLAIM_{index}_WRONG_TYPE")
            continue
        if type(declaration.report_id) is not UUID or (
            declaration.report_id.version != 7
        ):
            issues.append(f"CLAIM_{index}_REPORT_ID_INVALID")
            continue
        if declaration.report_id in evidence:
            issues.append("CLAIM_DUPLICATE_REPORT_ID")
            continue
        if type(declaration.source_kind) is not str or declaration.source_kind not in (
            "BROKER_OBSERVED",
            "LOCAL_BEFORE_SEND",
            "UNCONFIRMED_TRANSPORT",
            "UNVERIFIED",
        ):
            issues.append(f"CLAIM_{index}_SOURCE_KIND_INVALID")
        if declaration.source_receipt_ref is not None and not _ref(
            declaration.source_receipt_ref
        ):
            issues.append(f"CLAIM_{index}_SOURCE_REF_INVALID")
        if declaration.fee_receipt_ref is not None and not _ref(
            declaration.fee_receipt_ref
        ):
            issues.append(f"CLAIM_{index}_FEE_REF_INVALID")
        if declaration.original_available_at is not None and not _utc(
            declaration.original_available_at
        ):
            issues.append(f"CLAIM_{index}_ORIGINAL_CLOCK_INVALID")
        evidence[declaration.report_id] = declaration

    seen: dict[UUID, ExecutionReportV1] = {}
    first_seq: list[ExecutionReportV1] = []
    for index, item in enumerate(reports):
        try:
            report = _reparse_report(item)
        except ValueError, TypeError, ValidationError:
            issues.append(f"REPORT_{index}_ORIGINAL_INVALID")
            continue
        prior = seen.get(report.report_id)
        if prior is not None:
            if prior.report_hash != report.report_hash:
                issues.append(f"REPORT_{index}_CONFLICTING_ID_REDELIVERY")
            continue
        seen[report.report_id] = report
        first_seq.append(report)

    if set(seen) != set(evidence):
        issues.append("ORIGINAL_REPORT_AND_CLAIM_SET_MISMATCH")

    last_at: datetime | None = None
    known_broker_order_id: str | None = None
    last_reported_status: str | None = None
    largest_cum: int | None = None
    fee_claimed_complete = bool(first_seq)
    unknown_outcome = not first_seq
    local_before_send = False
    for index, report in enumerate(first_seq):
        if report.intent_id != original_intent.intent_id:
            issues.append(f"REPORT_{index}_FOREIGN_INTENT")
        if report.reported_at < original_intent.created_at:
            issues.append(f"REPORT_{index}_BEFORE_INTENT")
        if _utc(as_of_utc) and report.reported_at > as_of_utc:
            issues.append(f"REPORT_{index}_FUTURE_REPORT")
        if last_at is not None and report.reported_at <= last_at:
            issues.append(f"REPORT_{index}_NOT_STRICTLY_ORDERED")
        last_at = report.reported_at
        if report.broker_order_id is not None:
            if known_broker_order_id is not None and (
                known_broker_order_id != report.broker_order_id
            ):
                issues.append(f"REPORT_{index}_BROKER_ORDER_ID_CHANGED")
            known_broker_order_id = report.broker_order_id
        if report.cum_quantity > original_intent.quantity:
            issues.append(f"REPORT_{index}_OVERFILLS_INTENT")
        if largest_cum is not None and report.cum_quantity < largest_cum:
            issues.append(f"REPORT_{index}_CUMULATIVE_QUANTITY_REGRESSED")
        largest_cum = (
            report.cum_quantity
            if largest_cum is None
            else max(largest_cum, report.cum_quantity)
        )

        if report.status is ExecutionStatus.FILLED and (
            report.cum_quantity != original_intent.quantity
            or report.leaves_quantity != 0
        ):
            issues.append(f"REPORT_{index}_FILLED_WITH_UNRECONCILED_QUANTITY")
        if report.status is ExecutionStatus.PARTIALLY_FILLED and (
            not 0 < report.cum_quantity < original_intent.quantity
            or report.leaves_quantity
            != (original_intent.quantity - report.cum_quantity)
        ):
            issues.append(f"REPORT_{index}_PARTIAL_FILL_QUANTITY_INCONSISTENT")
        if report.status in (ExecutionStatus.NEW, ExecutionStatus.ACKNOWLEDGED):
            if report.cum_quantity > 0:
                issues.append(f"REPORT_{index}_UNEXPECTED_PRE_FILL_QUANTITY")

        claim = evidence.get(report.report_id)
        last_reported_status = report.status.value
        if claim is None:
            unknown_outcome = True
            fee_claimed_complete = False
            continue
        if (
            claim.original_available_at is None
            or not _utc(claim.original_available_at)
            or (_utc(as_of_utc) and claim.original_available_at > as_of_utc)
        ):
            issues.append(f"REPORT_{index}_ORIGINAL_UNAVAILABLE_AT_CUTOFF")
            unknown_outcome = True
        if claim.source_kind == "UNCONFIRMED_TRANSPORT":
            unknown_outcome = True
        if claim.source_kind == "UNVERIFIED":
            unknown_outcome = True
        if claim.source_kind in ("BROKER_OBSERVED", "LOCAL_BEFORE_SEND") and not _ref(
            claim.source_receipt_ref
        ):
            issues.append(f"REPORT_{index}_ORIGINAL_RECEIPT_CLAIM_MISSING")
            unknown_outcome = True

        ambiguous = report.rejection_reason is not None and any(
            report.rejection_reason.lower().startswith(prefix)
            for prefix in _AMBIGUOUS_PREFIXES
        )
        if ambiguous:
            unknown_outcome = True
            if report.status in (
                ExecutionStatus.REJECTED,
                ExecutionStatus.CANCELED,
                ExecutionStatus.EXPIRED,
            ):
                issues.append(f"REPORT_{index}_UNCONFIRMED_AS_TERMINAL_V1")
        if claim.source_kind == "LOCAL_BEFORE_SEND":
            local_before_send = True
            if (
                report.status is not ExecutionStatus.REJECTED
                or report.cum_quantity != 0
                or report.broker_order_id is not None
            ):
                issues.append(f"REPORT_{index}_LOCAL_REFUSAL_CONTRADICTS_FILL")
        if (
            claim.source_kind == "BROKER_OBSERVED"
            and report.status is ExecutionStatus.REJECTED
            and ambiguous
        ):
            issues.append(f"REPORT_{index}_BROKER_PROOF_CONTRADICTED")
        # The V1 fee defaults to zero even without an actual measured receipt.
        if not _ref(claim.fee_receipt_ref):
            fee_claimed_complete = False

    if issues:
        return V1ExecutionAudit(
            False,
            last_reported_status,
            "UNKNOWN",
            None,
            False,
            (),
            tuple(issues),
        )
    return V1ExecutionAudit(
        True,
        last_reported_status,
        (
            "UNKNOWN"
            if unknown_outcome
            else "LOCAL_NO_SEND_CLAIM"
            if local_before_send
            else "V1_ORIGIN_CLAIM_ONLY"
        ),
        largest_cum,
        fee_claimed_complete,
        tuple(report.report_hash for report in first_seq),
        (),
    )
