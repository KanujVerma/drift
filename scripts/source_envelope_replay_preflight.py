"""Pure synthetic S2 source-envelope replay preflight for issue #528.

This is not the source producer, accepted SRC wire, provenance authenticator
or news triage. No file, clock, network, data provider or broker I/O occurs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = frozenset({"profile", "decision_cutoff_utc", "source", "events", "coverage"})
_SOURCE = frozenset(
    {"publisher_ref", "provider_product_ref", "channel_ref",
     "native_namespace", "query_scope_ref"}
)
_EVENT = frozenset(
    {"receipt_id", "source_event_id", "source_version_id", "version_basis",
     "identity_evidence_ref", "content_state", "content_sha256",
     "retained_content_ref", "published_utc", "first_received_utc",
     "normalized_available_utc", "usable_available_utc",
     "availability_basis", "historical_policy_ref", "relation",
     "predecessor_receipt_id", "relation_evidence_ref", "quality_state"}
)
_COVERAGE = frozenset(
    {"query_scope_ref", "interval_start_utc", "interval_end_utc",
     "available_utc", "state", "matching_event_count",
     "pagination_complete", "closure_evidence_ref", "failure_evidence_ref"}
)
_VERSION_BASIS = frozenset({"SOURCE_NATIVE", "LOCALLY_OBSERVED", "UNKNOWN"})
_CONTENT_STATE = frozenset({"COMPLETE", "PARTIAL", "MISSING"})
_QUALITY = frozenset({"COMPLETE", "UNRESOLVED", "CONFLICT"})
_RELATIONS = frozenset({"NONE", "UPDATE", "CORRECTION", "UNKNOWN"})
_AVAILABILITY = frozenset(
    {"LOCAL_OBSERVED", "HISTORICAL_RECONSTRUCTED", "UNKNOWN"}
)
_COVERAGE_STATES = frozenset(
    {"COVERED_EMPTY", "COVERED_WITH_EVENTS", "PARTIAL", "FAILED", "UNKNOWN"}
)


@dataclass(frozen=True, slots=True)
class EnvelopeReplayPreflight:
    """Review metadata only; these are not authenticated availability facts."""

    structurally_reviewable: bool
    eligible_receipt_ids: tuple[str, ...]
    duplicate_receipt_pairs: tuple[tuple[str, str], ...]
    conflicted_receipt_ids: tuple[str, ...]
    coverage_at_cutoff: str
    reasons: tuple[str, ...]

    @property
    def authorizes_ingestion_or_trading(self) -> bool:
        return False

    @property
    def proves_source_rights_or_origin(self) -> bool:
        return False


def _plain(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    if any(type(key) is not str for key in value):
        return None
    return cast(dict[str, object], value)


def _is_plain_json(value: object, depth: int, budget: list[int]) -> bool:
    """Only untrusted primitive JSON values, never caller-defined equality."""
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is str:
        return len(value) <= 4096
    if type(value) is list:
        return len(value) <= 512 and all(
            _is_plain_json(item, depth + 1, budget) for item in value
        )
    if type(value) is dict:
        return len(value) <= 128 and all(
            type(key) is str
            and len(key) <= 128
            and _is_plain_json(item, depth + 1, budget)
            for key, item in value.items()
        )
    return False


def _nonblank(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _member(value: object, choices: frozenset[str]) -> bool:
    return type(value) is str and value in choices


def _utc(value: object) -> datetime | None:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timedelta(0) else None


def _digest(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _required_map(
    value: object,
    fields: frozenset[str],
    prefix: str,
    issues: list[str],
) -> dict[str, object]:
    record = _plain(value)
    if record is None:
        issues.append(f"{prefix}.not_plain_object")
        return {}
    if set(record) != fields:
        issues.append(f"{prefix}.fields.not_exact")
    return record


def preflight_source_envelope_replay(payload: object) -> EnvelopeReplayPreflight:
    """Review untrusted fixture metadata without interpreting news content.

    A reviewable mock receipt is never a verified original source edition,
    accepted historical availability, feed entitlement, or a triage decision.
    """
    root = _plain(payload)
    if root is None:
        return EnvelopeReplayPreflight(
            False, (), (), (), "UNKNOWN", ("payload.not_plain_object",)
        )
    if not _is_plain_json(root, 0, [4096]):
        return EnvelopeReplayPreflight(
            False, (), (), (), "UNKNOWN", ("payload.not_plain_json",)
        )
    issues: list[str] = []
    if set(root) != _ROOT:
        issues.append("payload.fields.not_exact")
    if root.get("profile") != "synthetic-src-s2-review-v1":
        issues.append("profile.not_fixture_v1")
    cutoff = _utc(root.get("decision_cutoff_utc"))
    if cutoff is None:
        issues.append("decision_cutoff_utc.invalid")

    source = _required_map(root.get("source"), _SOURCE, "source", issues)
    for field in _SOURCE:
        if not _nonblank(source.get(field)):
            issues.append(f"source.{field}.missing")

    items = root.get("events")
    if type(items) is not list:
        issues.append("events.not_plain_list")
        items = []
    known_receipts: dict[str, dict[str, object]] = {}
    editions: dict[tuple[str, str, str], tuple[str, str]] = {}
    conflicting: set[str] = set()
    duplicates: list[tuple[str, str]] = []
    eligible: list[str] = []

    for index, raw_event in enumerate(items):
        prefix = f"events.{index}"
        event = _required_map(raw_event, _EVENT, prefix, issues)
        receipt = event.get("receipt_id")
        if not _nonblank(receipt):
            issues.append(f"{prefix}.receipt_id.missing")
            continue
        assert isinstance(receipt, str)
        if receipt in known_receipts:
            issues.append(f"{prefix}.receipt_id.reused")
            conflicting.add(receipt)
            continue

        for field in ("source_event_id", "source_version_id"):
            if not _nonblank(event.get(field)):
                issues.append(f"{prefix}.{field}.missing")
        if not _member(event.get("version_basis"), _VERSION_BASIS):
            issues.append(f"{prefix}.version_basis.invalid")
        if not _member(event.get("content_state"), _CONTENT_STATE):
            issues.append(f"{prefix}.content_state.invalid")
        if not _member(event.get("quality_state"), _QUALITY):
            issues.append(f"{prefix}.quality_state.invalid")
        if not _member(event.get("relation"), _RELATIONS):
            issues.append(f"{prefix}.relation.invalid")
        if not _member(event.get("availability_basis"), _AVAILABILITY):
            issues.append(f"{prefix}.availability_basis.invalid")

        digest = event.get("content_sha256")
        if digest is not None and not _digest(digest):
            issues.append(f"{prefix}.content_sha256.invalid")
        if event.get("content_state") == "COMPLETE":
            if not _digest(digest) or not _nonblank(event.get("retained_content_ref")):
                issues.append(f"{prefix}.complete_content_without_retained_bytes")

        publication = event.get("published_utc")
        if publication is not None and _utc(publication) is None:
            issues.append(f"{prefix}.published_utc.invalid")
        received = _utc(event.get("first_received_utc"))
        normalized = _utc(event.get("normalized_available_utc"))
        usable = _utc(event.get("usable_available_utc"))
        for field, instant in (
            ("first_received_utc", received),
            ("normalized_available_utc", normalized),
            ("usable_available_utc", usable),
        ):
            raw = event.get(field)
            if raw is not None and instant is None:
                issues.append(f"{prefix}.{field}.invalid")

        published = _utc(publication) if publication is not None else None
        if published is not None and received is not None and published > received:
            issues.append(f"{prefix}.publication_after_local_receipt")
        if received is not None and normalized is not None and received > normalized:
            issues.append(f"{prefix}.normalized_before_receipt")
        if normalized is not None and usable is not None and normalized > usable:
            issues.append(f"{prefix}.usable_before_normalization")

        basis = event.get("availability_basis")
        if basis == "LOCAL_OBSERVED" and (
            received is None or normalized is None or usable is None
        ):
            issues.append(f"{prefix}.local_availability_missing_clock")
        if basis == "HISTORICAL_RECONSTRUCTED" and not _nonblank(
            event.get("historical_policy_ref")
        ):
            issues.append(f"{prefix}.historical_policy_ref.missing")
        if basis != "HISTORICAL_RECONSTRUCTED" and (
            event.get("historical_policy_ref") is not None
        ):
            issues.append(f"{prefix}.historical_policy_unbound")
        if basis == "LOCAL_OBSERVED" and not _nonblank(
            event.get("identity_evidence_ref")
        ):
            issues.append(f"{prefix}.identity_evidence_ref.missing")

        relation = event.get("relation")
        predecessor_id = event.get("predecessor_receipt_id")
        relation_ref = event.get("relation_evidence_ref")
        if relation in ("UPDATE", "CORRECTION"):
            prior = known_receipts.get(predecessor_id) if type(predecessor_id) is str else None
            if prior is None:
                issues.append(f"{prefix}.predecessor_not_retained_earlier")
            else:
                if prior.get("source_event_id") != event.get("source_event_id"):
                    issues.append(f"{prefix}.predecessor_cross_event")
                if prior.get("source_version_id") == event.get("source_version_id"):
                    issues.append(f"{prefix}.revision_reuses_version")
                if prior.get("version_basis") != event.get("version_basis"):
                    issues.append(f"{prefix}.revision_changes_identity_basis")
                prior_received = _utc(prior.get("first_received_utc"))
                if (
                    prior_received is not None and received is not None
                    and received <= prior_received
                ):
                    issues.append(f"{prefix}.revision_not_later")
            if not _nonblank(relation_ref):
                issues.append(f"{prefix}.relation_evidence_ref.missing")
        elif relation == "NONE" and (
            predecessor_id is not None or relation_ref is not None
        ):
            issues.append(f"{prefix}.none_relation_has_predecessor")
        # UNKNOWN records may retain suspected relationships, but never prove one.

        # Native/locally observed edition identity is scoped to this one source.
        # Equal digests by themselves never merge different events or publishers.
        if (
            _nonblank(event.get("source_event_id"))
            and _nonblank(event.get("source_version_id"))
            and event.get("version_basis") in (
                "SOURCE_NATIVE", "LOCALLY_OBSERVED"
            )
            and event.get("content_state") == "COMPLETE"
            and _digest(digest)
            and _nonblank(event.get("identity_evidence_ref"))
        ):
            key = (
                cast(str, event["source_event_id"]),
                cast(str, event["version_basis"]),
                cast(str, event["source_version_id"]),
            )
            first = editions.get(key)
            if first is None:
                editions[key] = (receipt, cast(str, digest))
            elif first[1] != digest:
                issues.append(f"{prefix}.same_edition_conflicting_content")
                conflicting.update((first[0], receipt))
            else:
                duplicates.append((first[0], receipt))

        known_receipts[receipt] = event
        if (
            cutoff is not None
            and usable is not None
            and usable < cutoff
            and basis == "LOCAL_OBSERVED"
            and received is not None
            and normalized is not None
            and received <= normalized <= usable
            and event.get("content_state") == "COMPLETE"
            and event.get("quality_state") == "COMPLETE"
            and _digest(digest)
            and _nonblank(event.get("retained_content_ref"))
            and _nonblank(event.get("identity_evidence_ref"))
            and event.get("version_basis") != "UNKNOWN"
        ):
            eligible.append(receipt)

    coverage = _required_map(root.get("coverage"), _COVERAGE, "coverage", issues)
    if coverage.get("query_scope_ref") != source.get("query_scope_ref"):
        issues.append("coverage.scope_mismatch")
    start = _utc(coverage.get("interval_start_utc"))
    end = _utc(coverage.get("interval_end_utc"))
    observed_available = _utc(coverage.get("available_utc"))
    if start is None or end is None or start >= end:
        issues.append("coverage.interval.invalid")
    if observed_available is None:
        issues.append("coverage.available_utc.invalid")

    status = coverage.get("state")
    if not _member(status, _COVERAGE_STATES):
        issues.append("coverage.state.invalid")
        status = "UNKNOWN"
    count = coverage.get("matching_event_count")
    if count is not None and (type(count) is not int or count < 0):
        issues.append("coverage.matching_event_count.invalid")
    pagination = coverage.get("pagination_complete")
    if pagination is not None and type(pagination) is not bool:
        issues.append("coverage.pagination_complete.invalid")

    reported_at_cutoff = "UNKNOWN"
    if status in ("COVERED_EMPTY", "COVERED_WITH_EVENTS"):
        if pagination is not True or not _nonblank(
            coverage.get("closure_evidence_ref")
        ):
            issues.append("coverage.unclosed_cannot_claim_complete")
        if type(count) is not int or (
            status == "COVERED_EMPTY" and count != 0
        ) or (status == "COVERED_WITH_EVENTS" and count <= 0):
            issues.append("coverage.complete_count_inconsistent")
        if (
            observed_available is not None and end is not None
            and observed_available < end
        ):
            issues.append("coverage.closed_before_interval_end")
        if status == "COVERED_EMPTY" and cutoff is not None:
            # Only versions known by this cutoff can contradict a scoped-empty
            # claim; do not leak future deliveries backward into prior decisions.
            if any(
                (version_available := _utc(e.get("usable_available_utc")))
                is not None and version_available < cutoff
                for e in known_receipts.values()
            ):
                issues.append("coverage.claims_empty_despite_event_receipts")
        if (
            cutoff is not None and observed_available is not None
            and observed_available < cutoff
            and not any(reason.startswith("coverage.") for reason in issues)
        ):
            reported_at_cutoff = cast(str, status)
    elif status == "FAILED":
        if not _nonblank(coverage.get("failure_evidence_ref")):
            issues.append("coverage.failed_without_failure_receipt")
        reported_at_cutoff = "FAILED" if (
            cutoff is not None and observed_available is not None
            and observed_available < cutoff
        ) else "UNKNOWN"
    elif status == "PARTIAL":
        reported_at_cutoff = "PARTIAL" if (
            cutoff is not None and observed_available is not None
            and observed_available < cutoff
        ) else "UNKNOWN"

    # Invalid metadata cannot produce an affirmative eligibility or quiet feed.
    if issues:
        return EnvelopeReplayPreflight(
            False, (), (), tuple(sorted(conflicting)), "UNKNOWN", tuple(issues)
        )
    return EnvelopeReplayPreflight(
        True, tuple(eligible), tuple(duplicates), tuple(sorted(conflicting)),
        reported_at_cutoff, (),
    )
