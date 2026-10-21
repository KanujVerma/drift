"""Offline, untrusted source-evidence candidate preflight for #524/#378.

No provider I/O, acquisition, license authentication or source-grade promotion.
This is a synthetic fixture/document reviewer, not a production data gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

_UTC_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z"
)
_COMMON = frozenset(
    {
        "api_documentation",
        "account_entitlement",
        "licensed_purpose",
        "retention_and_replay_rights",
        "source_identity",
        "interval_coverage",
        "complete_cost_basis",
    }
)
_MARKET = frozenset(
    {
        "point_in_time_listing",
        "real_venue_mapping",
        "session_calendar",
        "quote_resolution",
        "quote_and_size_coverage",
        "corporate_action_basis",
    }
)
_NEWS = frozenset(
    {
        "original_content_version",
        "publication_and_receipt_clocks",
        "correction_lineage",
        "feed_health_and_query_closure",
    }
)
_HISTORICAL = frozenset(
    {"historical_version_archive", "historical_availability_basis"}
)
_PROSPECTIVE = frozenset({"prospective_capture_scope"})
_PROFILES = {
    "market_historical": _COMMON | _MARKET | _HISTORICAL,
    "news_historical": _COMMON | _NEWS | _HISTORICAL,
    "market_prospective": _COMMON | _MARKET | _PROSPECTIVE,
    "news_prospective": _COMMON | _NEWS | _PROSPECTIVE,
}
_STATUS = frozenset({"verified", "documented", "unknown", "denied"})
_ROOT_KEYS = frozenset(
    {
        "profile",
        "candidate_id",
        "provider_product_ref",
        "purpose_ref",
        "scope_ref",
        "evidence_owner",
        "independent_reviewer",
        "dimensions",
        "sample",
    }
)
_DIMENSION_KEYS = frozenset(
    {"status", "evidence_ref", "scope_ref", "observed_utc"}
)
_SAMPLE_KEYS = frozenset(
    {"decision_cutoff_utc", "selected_version_id", "versions"}
)
_VERSION_KEYS = frozenset(
    {
        "version_id",
        "payload_ref",
        "published_utc",
        "first_received_utc",
        "normalized_available_utc",
        "supersedes_id",
    }
)


@dataclass(frozen=True, slots=True)
class SourcePreflight:
    """Structural report only; references and claims are not authenticated."""

    review_ready: bool
    selected_causal_version_id: str | None
    reasons: tuple[str, ...]

    @property
    def establishes_rights_or_source_grade(self) -> bool:
        return False

    @property
    def authorizes_provider_access(self) -> bool:
        return False


def _map(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    if any(type(k) is not str for k in value):
        return None
    return cast(dict[str, object], value)


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _utc(value: object) -> datetime | None:
    if type(value) is not str or _UTC_PATTERN.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timedelta(0) else None


def preflight_source_qualification(payload: object) -> SourcePreflight:
    """Review the claimed evidence and select only a causally available version.

    A positive result does not show that any referenced bytes, custodian, source,
    rights grant, timestamp or claimed reviewer is authentic or legally usable.
    """
    record = _map(payload)
    if record is None:
        return SourcePreflight(False, None, ("payload.not_plain_object",))

    problems: list[str] = []
    if set(record) != _ROOT_KEYS:
        problems.append("payload.fields.not_exact")

    profile = record.get("profile")
    if type(profile) is not str or profile not in _PROFILES:
        problems.append("profile.invalid")
        required = frozenset[str]()
    else:
        required = _PROFILES[profile]

    for name in (
        "candidate_id",
        "provider_product_ref",
        "purpose_ref",
        "scope_ref",
        "evidence_owner",
        "independent_reviewer",
    ):
        if not _text(record.get(name)):
            problems.append(f"{name}.missing")
    if (
        _text(record.get("evidence_owner"))
        and record.get("evidence_owner") == record.get("independent_reviewer")
    ):
        problems.append("independent_reviewer.self_review")

    dimensions = _map(record.get("dimensions"))
    if dimensions is None:
        problems.append("dimensions.not_plain_object")
    else:
        if set(dimensions) != required:
            problems.append("dimensions.must_match_profile")
        for name in sorted(required):
            entry = _map(dimensions.get(name))
            if entry is None:
                problems.append(f"{name}.missing_or_malformed")
                continue
            if set(entry) != _DIMENSION_KEYS:
                problems.append(f"{name}.fields.not_exact")
            status = entry.get("status")
            if type(status) is not str or status not in _STATUS:
                problems.append(f"{name}.status.invalid")
            elif name == "api_documentation":
                if status not in ("documented", "verified"):
                    problems.append(f"{name}.not_documented")
            elif status != "verified":
                problems.append(f"{name}.not_verified")
            if not _text(entry.get("evidence_ref")):
                problems.append(f"{name}.evidence_ref.missing")
            if (
                not _text(entry.get("scope_ref"))
                or entry.get("scope_ref") != record.get("scope_ref")
            ):
                problems.append(f"{name}.scope_mismatch")
            if _utc(entry.get("observed_utc")) is None:
                problems.append(f"{name}.observed_utc.invalid")

    sample = _map(record.get("sample"))
    if sample is None:
        return SourcePreflight(
            False, None, tuple([*problems, "sample.not_plain_object"])
        )
    if set(sample) != _SAMPLE_KEYS:
        problems.append("sample.fields.not_exact")
    cutoff = _utc(sample.get("decision_cutoff_utc"))
    if cutoff is None:
        problems.append("sample.decision_cutoff_utc.invalid")
    chosen = sample.get("selected_version_id")
    if not _text(chosen):
        problems.append("sample.selected_version_id.missing")

    versions = sample.get("versions")
    if type(versions) is not list or not versions:
        return SourcePreflight(
            False, None, tuple([*problems, "sample.versions.not_nonempty_list"])
        )

    prior_id: str | None = None
    prior_availability: datetime | None = None
    seen: set[str] = set()
    admitted: list[tuple[datetime, str]] = []
    for index, value in enumerate(versions):
        version = _map(value)
        prefix = f"sample.versions.{index}"
        if version is None:
            problems.append(f"{prefix}.not_plain_object")
            continue
        if set(version) != _VERSION_KEYS:
            problems.append(f"{prefix}.fields.not_exact")
        version_id = version.get("version_id")
        if not _text(version_id):
            problems.append(f"{prefix}.version_id.missing")
            continue
        assert isinstance(version_id, str)
        if version_id in seen:
            problems.append(f"{prefix}.version_id.duplicate")
            continue
        seen.add(version_id)
        if not _text(version.get("payload_ref")):
            problems.append(f"{prefix}.payload_ref.missing")

        supersedes = version.get("supersedes_id")
        if supersedes != prior_id:
            problems.append(f"{prefix}.supersedes_id.lineage_mismatch")
        published = _utc(version.get("published_utc"))
        received = _utc(version.get("first_received_utc"))
        available = _utc(version.get("normalized_available_utc"))
        for name, parsed in (
            ("published_utc", published),
            ("first_received_utc", received),
            ("normalized_available_utc", available),
        ):
            if parsed is None:
                problems.append(f"{prefix}.{name}.invalid_or_unknown")
        if published is not None and received is not None:
            if published > received:
                problems.append(f"{prefix}.published_after_receipt")
        if received is not None and available is not None:
            if received > available:
                problems.append(f"{prefix}.available_before_receipt")
        if available is not None:
            if prior_availability is not None and available <= prior_availability:
                problems.append(f"{prefix}.revision_not_later")
            if cutoff is not None and available < cutoff:
                admitted.append((available, version_id))
            prior_availability = available
        prior_id = version_id

    selected: str | None = None
    if cutoff is not None:
        if not admitted:
            problems.append("sample.no_proven_available_version")
        else:
            selected = admitted[-1][1]
            if chosen != selected:
                problems.append("sample.selected_version_not_causally_available")
    return SourcePreflight(not problems, selected if not problems else None, tuple(problems))
