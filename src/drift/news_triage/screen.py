"""Deterministic, synthetic-only candidate screening for issue #381.

These are *consumer-local projection types*, not Matthew's accepted SRC wire
schema, source authentication, historical coverage, or trading authorization.
Until the exact producer contract in #394 is independently accepted, this
module is a draft offline test seam only. All external text remains inert.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeGuard

from drift.serialization.canonical import content_hash

Outcome = Literal["CANDIDATE_ALERT", "NO_ALERT", "ABSTAIN", "UNAVAILABLE"]
QualityState = Literal["usable", "missing", "conflicting"]
CoverageState = Literal["covered", "partial", "failed", "unknown"]
FeedState = Literal[
    "covered_empty", "covered_with_events", "partial", "failed", "unknown"
]
FeedDisposition = Literal["EMPTY", "EVENTS_PRESENT", "INCOMPLETE", "UNAVAILABLE"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """A retained asserted digest, not independent origin authentication."""

    ref_id: str
    sha256: str


@dataclass(frozen=True, slots=True)
class EventKey:
    source_id: str
    event_id: str
    version: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class EventEvidence:
    """Typed synthetic source assertion supplied by a separate producer."""

    key: EventKey
    category: str | None
    received_at: datetime | None
    normalized_at: datetime | None
    available_at: datetime | None
    availability_ref: EvidenceRef | None
    content_ref: EvidenceRef | None
    quality_ref: EvidenceRef | None
    quality_state: QualityState
    coverage_state: CoverageState
    published_at: datetime | None = None
    revision_of: EventKey | None = None
    untrusted_text: str = ""


@dataclass(frozen=True, slots=True)
class ScreeningPolicy:
    """Caller-supplied explicit allow/deny lists, never model-selected."""

    policy_id: str
    version: str
    policy_sha256: str
    allowed_categories: frozenset[str]
    excluded_categories: frozenset[str]


@dataclass(frozen=True, slots=True)
class PriorScreening:
    """Caller-retained conclusive or inconclusive result at actual availability."""

    event_key: EventKey
    policy_id: str
    policy_version: str
    policy_sha256: str
    context_id: str
    quality_evidence_sha256: str
    outcome: Outcome
    evidence_available_at: datetime
    result_ref: EvidenceRef


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    """No order, investment decision, model call or persistence is performed."""

    outcome: Outcome
    reason: str
    event_key: EventKey | None
    category: str | None
    policy_id: str | None
    policy_version: str | None
    policy_sha256: str | None
    context_id: str | None
    decision_cutoff_utc: str | None
    duplicate_of: EvidenceRef | None
    revision_of: EventKey | None
    evidence_refs: tuple[EvidenceRef, ...]
    record_hash: str


@dataclass(frozen=True, slots=True)
class FeedCoverage:
    """A separate upstream coverage assertion, never a fabricated news item."""

    source_id: str
    scope_ref: EvidenceRef
    start_at: datetime
    end_at: datetime
    observed_at: datetime
    available_at: datetime
    state: FeedState
    event_count: int


@dataclass(frozen=True, slots=True)
class FeedScreeningResult:
    disposition: FeedDisposition
    reason: str
    source_id: str | None
    scope_ref: EvidenceRef | None
    record_hash: str


def _token(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value) <= 512
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
    )


def _digest(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _reference(value: object) -> TypeGuard[EvidenceRef]:
    return type(value) is EvidenceRef and _token(value.ref_id) and _digest(value.sha256)


def _utc(value: object) -> str | None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        return None
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _key(value: object) -> TypeGuard[EventKey]:
    return (
        type(value) is EventKey
        and _token(value.source_id)
        and _token(value.event_id)
        and _token(value.version)
        and _digest(value.content_sha256)
    )


def _key_dict(key: EventKey | None) -> dict[str, str] | None:
    if key is None:
        return None
    return {
        "source_id": key.source_id,
        "event_id": key.event_id,
        "version": key.version,
        "content_sha256": key.content_sha256,
    }


def _ref_dict(ref: EvidenceRef | None) -> dict[str, str] | None:
    return None if ref is None else {"ref_id": ref.ref_id, "sha256": ref.sha256}


def policy_digest(
    policy_id: str,
    version: str,
    allowed_categories: frozenset[str],
    excluded_categories: frozenset[str],
) -> str:
    """Local policy identity; source/owner authorization is a different gate."""
    return content_hash(
        {
            "policy_id": policy_id,
            "version": version,
            "allowed_categories": sorted(allowed_categories),
            "excluded_categories": sorted(excluded_categories),
        }
    )


def _valid_policy(policy: object) -> TypeGuard[ScreeningPolicy]:
    if type(policy) is not ScreeningPolicy:
        return False
    if not _token(policy.policy_id) or not _token(policy.version):
        return False
    if type(policy.allowed_categories) is not frozenset:
        return False
    if type(policy.excluded_categories) is not frozenset:
        return False
    if any(
        not _token(c) for c in policy.allowed_categories | policy.excluded_categories
    ):
        return False
    if policy.allowed_categories & policy.excluded_categories:
        return False
    return _digest(policy.policy_sha256) and policy.policy_sha256 == policy_digest(
        policy.policy_id,
        policy.version,
        policy.allowed_categories,
        policy.excluded_categories,
    )


def _result(
    outcome: Outcome,
    reason: str,
    evidence: EventEvidence | None,
    policy: ScreeningPolicy | None,
    context_id: str | None,
    cutoff: datetime,
    duplicate_of: EvidenceRef | None = None,
) -> ScreeningResult:
    key = evidence.key if evidence is not None and _key(evidence.key) else None
    revision = (
        evidence.revision_of
        if evidence is not None and _key(evidence.revision_of)
        else None
    )
    p = policy if _valid_policy(policy) else None
    refs: tuple[EvidenceRef, ...] = ()
    if evidence is not None:
        refs = tuple(
            sorted(
                {
                    (ref.ref_id, ref.sha256): ref
                    for ref in (
                        evidence.availability_ref,
                        evidence.content_ref,
                        evidence.quality_ref,
                    )
                    if _reference(ref)
                }.values(),
                key=lambda x: (x.ref_id, x.sha256),
            )
        )
    category = (
        evidence.category
        if evidence is not None and _token(evidence.category)
        else None
    )
    cutoff_text = _utc(cutoff)
    preimage = {
        "profile": "drift-news-triage/1-synthetic",
        "outcome": outcome,
        "reason": reason,
        "event_key": _key_dict(key),
        "category": category,
        "policy_id": p.policy_id if p else None,
        "policy_version": p.version if p else None,
        "policy_sha256": p.policy_sha256 if p else None,
        "policy_allowed": sorted(p.allowed_categories) if p else None,
        "policy_excluded": sorted(p.excluded_categories) if p else None,
        "context_id": context_id if _token(context_id) else None,
        "cutoff": cutoff_text,
        "event_received": _utc(evidence.received_at) if evidence else None,
        "event_normalized": _utc(evidence.normalized_at) if evidence else None,
        "event_available": _utc(evidence.available_at) if evidence else None,
        "event_published": _utc(evidence.published_at) if evidence else None,
        "quality_state": (
            evidence.quality_state
            if evidence is not None and type(evidence.quality_state) is str
            else None
        ),
        "coverage_state": (
            evidence.coverage_state
            if evidence is not None and type(evidence.coverage_state) is str
            else None
        ),
        "revision_of": _key_dict(revision),
        "evidence_refs": [_ref_dict(ref) for ref in refs],
        "duplicate_of": _ref_dict(duplicate_of),
    }
    return ScreeningResult(
        outcome=outcome,
        reason=reason,
        event_key=key,
        category=category,
        policy_id=p.policy_id if p else None,
        policy_version=p.version if p else None,
        policy_sha256=p.policy_sha256 if p else None,
        context_id=context_id if _token(context_id) else None,
        decision_cutoff_utc=cutoff_text,
        duplicate_of=duplicate_of,
        revision_of=revision,
        evidence_refs=refs,
        record_hash=content_hash(preimage),
    )


def screen_event(
    *,
    evidence: EventEvidence | None,
    policy: ScreeningPolicy | None,
    context_id: str,
    decision_cutoff: datetime,
    prior: Sequence[PriorScreening] = (),
) -> ScreeningResult:
    """Classify only caller-asserted *synthetic* source facts, without side effects.

    The upstream SRC producer is responsible for validating authenticity,
    rights, retained bytes and original availability. A local `usable` flag
    and self-consistent SHA do not prove those external claims.
    """
    cutoff_utc = _utc(decision_cutoff)
    if cutoff_utc is None or not _token(context_id):
        return _result(
            "UNAVAILABLE",
            "INVALID_DECISION_CONTEXT",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if type(evidence) is not EventEvidence or not _key(evidence.key):
        return _result(
            "UNAVAILABLE",
            "MALFORMED_SOURCE_IDENTITY",
            None,
            policy,
            context_id,
            decision_cutoff,
        )
    if (
        not _reference(evidence.availability_ref)
        or not _reference(evidence.content_ref)
        or not _reference(evidence.quality_ref)
        or evidence.content_ref.sha256 != evidence.key.content_sha256
    ):
        return _result(
            "UNAVAILABLE",
            "MISSING_OR_CONTRADICTORY_SOURCE_PROOF",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if evidence.quality_state == "conflicting":
        return _result(
            "ABSTAIN",
            "CONFLICTING_SOURCE_EVIDENCE",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if evidence.quality_state != "usable" or evidence.coverage_state not in (
        "covered",
        "partial",
        "failed",
        "unknown",
    ):
        return _result(
            "UNAVAILABLE",
            "SOURCE_QUALITY_OR_STATE_UNAVAILABLE",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    receipt = _utc(evidence.received_at)
    normalized = _utc(evidence.normalized_at)
    available = _utc(evidence.available_at)
    if receipt is None or normalized is None or available is None:
        return _result(
            "UNAVAILABLE",
            "MISSING_VERIFIED_EVENT_CLOCK",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if evidence.published_at is not None and _utc(evidence.published_at) is None:
        return _result(
            "UNAVAILABLE",
            "INVALID_PUBLICATION_CLOCK",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if available < receipt or available < normalized or normalized < receipt:
        return _result(
            "UNAVAILABLE",
            "INVALID_EVENT_CLOCK_ORDER",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if available > cutoff_utc:
        return _result(
            "UNAVAILABLE",
            "EVENT_AFTER_DECISION_CUTOFF",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if evidence.revision_of is not None and (
        not _key(evidence.revision_of)
        or evidence.revision_of.source_id != evidence.key.source_id
        or evidence.revision_of.event_id != evidence.key.event_id
        or evidence.revision_of.version == evidence.key.version
    ):
        return _result(
            "ABSTAIN",
            "CONFLICTING_REVISION_RELATION",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if not _valid_policy(policy):
        return _result(
            "ABSTAIN",
            "MISSING_OR_INVALID_SCREENING_POLICY",
            evidence,
            None,
            context_id,
            decision_cutoff,
        )

    duplicate_ref: EvidenceRef | None = None
    seen_receipts: dict[str, str] = {}
    for earlier in prior:
        if type(earlier) is not PriorScreening:
            return _result(
                "ABSTAIN",
                "MALFORMED_PRIOR_SCREENING",
                evidence,
                policy,
                context_id,
                decision_cutoff,
            )
        prior_utc = _utc(earlier.evidence_available_at)
        if prior_utc is None:
            return _result(
                "ABSTAIN",
                "MALFORMED_PRIOR_SCREENING",
                evidence,
                policy,
                context_id,
                decision_cutoff,
            )
        if prior_utc > cutoff_utc:
            # Known future records cannot influence this historical screening,
            # even when their other fields are inconsistent or malformed.
            continue
        if (
            not _key(earlier.event_key)
            or not _reference(earlier.result_ref)
            or not _token(earlier.context_id)
            or not _token(earlier.policy_id)
            or not _token(earlier.policy_version)
            or not _digest(earlier.policy_sha256)
            or not _digest(earlier.quality_evidence_sha256)
            or earlier.outcome not in (
                "CANDIDATE_ALERT", "NO_ALERT", "ABSTAIN", "UNAVAILABLE"
            )
        ):
            return _result(
                "ABSTAIN",
                "MALFORMED_PRIOR_SCREENING",
                evidence,
                policy,
                context_id,
                decision_cutoff,
            )
        same_event = (
            earlier.event_key.source_id == evidence.key.source_id
            and earlier.event_key.event_id == evidence.key.event_id
            and earlier.event_key.version == evidence.key.version
        )
        if (
            same_event
            and earlier.event_key.content_sha256 != evidence.key.content_sha256
        ):
            return _result(
                "ABSTAIN",
                "CONFLICTING_SOURCE_VERSION",
                evidence,
                policy,
                context_id,
                decision_cutoff,
            )
        if (
            same_event
            and earlier.event_key.content_sha256 == evidence.key.content_sha256
            and earlier.policy_id == policy.policy_id
            and earlier.policy_version == policy.version
            and earlier.policy_sha256 == policy.policy_sha256
            and earlier.context_id == context_id
            and earlier.quality_evidence_sha256 == evidence.quality_ref.sha256
            and earlier.outcome in ("CANDIDATE_ALERT", "NO_ALERT")
        ):
            incumbent_digest = seen_receipts.get(earlier.result_ref.ref_id)
            if (
                incumbent_digest is not None
                and incumbent_digest != earlier.result_ref.sha256
            ):
                return _result(
                    "ABSTAIN",
                    "CONFLICTING_PRIOR_RECEIPT",
                    evidence,
                    policy,
                    context_id,
                    decision_cutoff,
                )
            seen_receipts[earlier.result_ref.ref_id] = earlier.result_ref.sha256
            if duplicate_ref is None or (
                earlier.result_ref.ref_id,
                earlier.result_ref.sha256,
            ) < (duplicate_ref.ref_id, duplicate_ref.sha256):
                duplicate_ref = earlier.result_ref
    if duplicate_ref is not None:
        return _result(
            "NO_ALERT",
            "PROVEN_CONTEXT_SCOPED_DUPLICATE",
            evidence,
            policy,
            context_id,
            decision_cutoff,
            duplicate_ref,
        )
    if not _token(evidence.category):
        return _result(
            "ABSTAIN",
            "UNKNOWN_EVENT_CATEGORY",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if evidence.category in policy.allowed_categories:
        return _result(
            "CANDIDATE_ALERT",
            "EXPLICIT_ALLOWED_CATEGORY",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    if evidence.category in policy.excluded_categories:
        return _result(
            "NO_ALERT",
            "EXPLICIT_EXCLUDED_CATEGORY",
            evidence,
            policy,
            context_id,
            decision_cutoff,
        )
    return _result(
        "ABSTAIN",
        "UNSPECIFIED_POLICY_CATEGORY",
        evidence,
        policy,
        context_id,
        decision_cutoff,
    )


def screen_feed_coverage(
    *, coverage: FeedCoverage | None, decision_cutoff: datetime
) -> FeedScreeningResult:
    """Classify a covered-empty interval without manufacturing an event."""
    good = (
        type(coverage) is FeedCoverage
        and _token(coverage.source_id)
        and _reference(coverage.scope_ref)
        and _utc(coverage.start_at) is not None
        and _utc(coverage.end_at) is not None
        and _utc(coverage.observed_at) is not None
        and _utc(coverage.available_at) is not None
        and _utc(decision_cutoff) is not None
        and type(coverage.event_count) is int
        and coverage.event_count >= 0
        and coverage.start_at < coverage.end_at
        and coverage.observed_at <= coverage.available_at <= decision_cutoff
        and coverage.state
        in ("covered_empty", "covered_with_events", "partial", "failed", "unknown")
    )
    if not good:
        status: FeedDisposition = "UNAVAILABLE"
        reason = "INVALID_OR_UNAVAILABLE_COVERAGE"
    elif (
        coverage is not None
        and coverage.state == "covered_empty"
        and coverage.event_count == 0
    ):
        status = "EMPTY"
        reason = "COMPLETE_COVERED_EMPTY_INTERVAL"
    elif (
        coverage is not None
        and coverage.state == "covered_with_events"
        and coverage.event_count > 0
    ):
        status = "EVENTS_PRESENT"
        reason = "COMPLETE_COVERED_INTERVAL_WITH_EVENTS"
    elif coverage is not None and coverage.state == "partial":
        status = "INCOMPLETE"
        reason = "PARTIAL_COVERAGE"
    else:
        status = "UNAVAILABLE"
        reason = "SOURCE_COVERAGE_NOT_CONFIRMED"
    source_id = (
        coverage.source_id
        if type(coverage) is FeedCoverage and _token(coverage.source_id)
        else None
    )
    scope_ref = (
        coverage.scope_ref
        if type(coverage) is FeedCoverage and _reference(coverage.scope_ref)
        else None
    )
    hash_value = content_hash(
        {
            "profile": "drift-news-triage-feed/1-synthetic",
            "disposition": status,
            "reason": reason,
            "source_id": source_id,
            "scope_ref": _ref_dict(scope_ref),
            "start_at": _utc(coverage.start_at)
            if type(coverage) is FeedCoverage
            else None,
            "end_at": _utc(coverage.end_at) if type(coverage) is FeedCoverage else None,
            "observed_at": _utc(coverage.observed_at)
            if type(coverage) is FeedCoverage
            else None,
            "available_at": _utc(coverage.available_at)
            if type(coverage) is FeedCoverage
            else None,
            "count": coverage.event_count
            if type(coverage) is FeedCoverage and type(coverage.event_count) is int
            else None,
            "state": (
                coverage.state
                if type(coverage) is FeedCoverage and type(coverage.state) is str
                else None
            ),
            "decision_cutoff": _utc(decision_cutoff),
        }
    )
    return FeedScreeningResult(
        disposition=status,
        reason=reason,
        source_id=source_id,
        scope_ref=scope_ref,
        record_hash=hash_value,
    )
