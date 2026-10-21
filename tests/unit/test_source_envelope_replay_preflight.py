"""Unexecuted synthetic AntiGravity fixtures for #528, Matthew #394."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from scripts.source_envelope_replay_preflight import (
    preflight_source_envelope_replay,
)


def fixture() -> dict[str, object]:
    return {
        "profile": "synthetic-src-s2-review-v1",
        "decision_cutoff_utc": "2026-01-02T10:35:10Z",
        "source": {
            "publisher_ref": "synthetic-publisher",
            "provider_product_ref": "synthetic-reseller-product",
            "channel_ref": "synthetic-offline",
            "native_namespace": "publisher-example",
            "query_scope_ref": "synthetic-query-scope-1",
        },
        "events": [
            {
                "receipt_id": "receipt-1",
                "source_event_id": "native-story-1",
                "source_version_id": "native-version-1",
                "version_basis": "SOURCE_NATIVE",
                "identity_evidence_ref": "untrusted-origin-claim",
                "content_state": "COMPLETE",
                "content_sha256": "a" * 64,
                "retained_content_ref": "fictional-original-bytes-1",
                "published_utc": "2026-01-02T10:32:00Z",
                "first_received_utc": "2026-01-02T10:35:01Z",
                "normalized_available_utc": "2026-01-02T10:35:02Z",
                "usable_available_utc": "2026-01-02T10:35:03Z",
                "availability_basis": "LOCAL_OBSERVED",
                "historical_policy_ref": None,
                "relation": "NONE",
                "predecessor_receipt_id": None,
                "relation_evidence_ref": None,
                "quality_state": "COMPLETE",
            }
        ],
        "coverage": {
            "query_scope_ref": "synthetic-query-scope-1",
            "interval_start_utc": "2026-01-02T10:00:00Z",
            "interval_end_utc": "2026-01-02T10:35:00Z",
            "available_utc": "2026-01-02T10:35:04Z",
            "state": "COVERED_WITH_EVENTS",
            "matching_event_count": 1,
            "pagination_complete": True,
            "closure_evidence_ref": "untrusted-completeness-claim",
            "failure_evidence_ref": None,
        },
    }


def _event(data: dict[str, object], index: int = 0) -> dict[str, object]:
    return cast(list[dict[str, object]], data["events"])[index]


def _events(data: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], data["events"])


def _coverage(data: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], data["coverage"])


def _assert_refusal(data: dict[str, object], reason: str) -> None:
    result = preflight_source_envelope_replay(data)
    assert not result.structurally_reviewable
    assert result.eligible_receipt_ids == ()
    assert result.coverage_at_cutoff == "UNKNOWN"
    assert reason in result.reasons
    assert not result.authorizes_ingestion_or_trading
    assert not result.proves_source_rights_or_origin


def test_complete_mock_event_is_only_reviewable_not_authenticated() -> None:
    report = preflight_source_envelope_replay(fixture())
    assert report.structurally_reviewable
    assert report.reasons == ()
    assert report.eligible_receipt_ids == ("receipt-1",)
    assert report.coverage_at_cutoff == "COVERED_WITH_EVENTS"
    assert report.duplicate_receipt_pairs == ()
    assert not report.proves_source_rights_or_origin
    assert not report.authorizes_ingestion_or_trading


def test_unknown_publication_does_not_erase_real_receipt() -> None:
    data = fixture()
    _event(data)["published_utc"] = None
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.eligible_receipt_ids == ("receipt-1",)


def test_publication_without_receipt_never_enters_past_cutoff() -> None:
    data = fixture()
    _event(data)["first_received_utc"] = "2026-01-02T10:35:20Z"
    _event(data)["normalized_available_utc"] = "2026-01-02T10:35:21Z"
    _event(data)["usable_available_utc"] = "2026-01-02T10:35:22Z"
    result = preflight_source_envelope_replay(data)
    assert result.structurally_reviewable
    assert result.eligible_receipt_ids == ()


def test_correction_after_cutoff_preserves_original_not_future_edition() -> None:
    data = fixture()
    edition = deepcopy(_event(data))
    edition.update(
        {
            "receipt_id": "receipt-2",
            "source_version_id": "native-version-2",
            "content_sha256": "b" * 64,
            "retained_content_ref": "fictional-original-bytes-2",
            "published_utc": "2026-01-02T10:36:00Z",
            "first_received_utc": "2026-01-02T10:36:01Z",
            "normalized_available_utc": "2026-01-02T10:36:02Z",
            "usable_available_utc": "2026-01-02T10:36:03Z",
            "relation": "CORRECTION",
            "predecessor_receipt_id": "receipt-1",
            "relation_evidence_ref": "untrusted-correction-claim",
        }
    )
    _events(data).append(edition)
    result = preflight_source_envelope_replay(data)
    assert result.structurally_reviewable
    assert result.eligible_receipt_ids == ("receipt-1",)
    assert result.duplicate_receipt_pairs == ()


def test_exact_duplicate_preserves_both_delivery_receipts() -> None:
    data = fixture()
    redelivery = deepcopy(_event(data))
    redelivery["receipt_id"] = "receipt-redelivery"
    redelivery["first_received_utc"] = "2026-01-02T10:35:05Z"
    redelivery["normalized_available_utc"] = "2026-01-02T10:35:06Z"
    redelivery["usable_available_utc"] = "2026-01-02T10:35:07Z"
    _events(data).append(redelivery)
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.duplicate_receipt_pairs == (
        ("receipt-1", "receipt-redelivery"),
    )
    assert report.eligible_receipt_ids == (
        "receipt-1", "receipt-redelivery",
    )


def test_textually_identical_different_native_event_is_not_exact_duplicate() -> None:
    data = fixture()
    other = deepcopy(_event(data))
    other["receipt_id"] = "receipt-other"
    other["source_event_id"] = "different-native-object"
    _events(data).append(other)
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.duplicate_receipt_pairs == ()


def test_same_edition_with_changed_original_hash_is_conflict() -> None:
    data = fixture()
    conflicting = deepcopy(_event(data))
    conflicting["receipt_id"] = "receipt-conflict"
    conflicting["content_sha256"] = "b" * 64
    conflicting["retained_content_ref"] = "untrusted-different-body"
    _events(data).append(conflicting)
    report = preflight_source_envelope_replay(data)
    assert not report.structurally_reviewable
    assert report.eligible_receipt_ids == ()
    assert report.conflicted_receipt_ids == (
        "receipt-1", "receipt-conflict",
    )
    assert "events.1.same_edition_conflicting_content" in report.reasons


def test_similar_text_no_exact_identity_does_not_make_a_duplicate() -> None:
    data = fixture()
    other = deepcopy(_event(data))
    other["receipt_id"] = "unproven-edition"
    other["version_basis"] = "UNKNOWN"
    _events(data).append(other)
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.duplicate_receipt_pairs == ()
    assert report.eligible_receipt_ids == ("receipt-1",)


@pytest.mark.parametrize(
    ("field", "value", "diagnostic"),
    [
        ("content_state", "COMPLETE", "events.0.complete_content_without_retained_bytes"),
        ("relation", "UPDATE", "events.0.predecessor_not_retained_earlier"),
    ],
)
def test_incomplete_or_invalid_relation_fails(
    field: str, value: str, diagnostic: str
) -> None:
    data = fixture()
    if field == "content_state":
        _event(data)["retained_content_ref"] = None
    else:
        _event(data)["relation"] = value
    _assert_refusal(data, diagnostic)


def test_changed_edition_must_link_retained_prior_and_evidence() -> None:
    data = fixture()
    update = deepcopy(_event(data))
    update.update(
        {
            "receipt_id": "receipt-v2",
            "source_version_id": "native-v2",
            "relation": "UPDATE",
            "predecessor_receipt_id": "missing-receipt",
            "relation_evidence_ref": None,
        }
    )
    _events(data).append(update)
    _assert_refusal(data, "events.1.predecessor_not_retained_earlier")


def test_cannot_normalize_before_observation() -> None:
    data = fixture()
    _event(data)["normalized_available_utc"] = "2026-01-02T10:35:00Z"
    _assert_refusal(data, "events.0.normalized_before_receipt")


def test_retained_historical_archive_does_not_prove_original_local_availability() -> None:
    data = fixture()
    _event(data)["availability_basis"] = "HISTORICAL_RECONSTRUCTED"
    _event(data)["historical_policy_ref"] = "unaccepted-history-policy"
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.eligible_receipt_ids == ()


def test_unavailable_edition_and_partial_feed_keep_facts_separate() -> None:
    data = fixture()
    _event(data)["content_state"] = "MISSING"
    _event(data)["retained_content_ref"] = None
    _coverage(data)["state"] = "PARTIAL"
    _coverage(data)["pagination_complete"] = False
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.eligible_receipt_ids == ()
    assert report.coverage_at_cutoff == "PARTIAL"


def test_partial_feed_with_independent_event_still_retains_event() -> None:
    data = fixture()
    _coverage(data)["state"] = "PARTIAL"
    _coverage(data)["pagination_complete"] = False
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.eligible_receipt_ids == ("receipt-1",)
    assert report.coverage_at_cutoff == "PARTIAL"


def test_complete_empty_requires_no_event_receipts_and_closure() -> None:
    data = fixture()
    _events(data).clear()
    _coverage(data)["state"] = "COVERED_EMPTY"
    _coverage(data)["matching_event_count"] = 0
    result = preflight_source_envelope_replay(data)
    assert result.structurally_reviewable
    assert result.coverage_at_cutoff == "COVERED_EMPTY"
    assert result.eligible_receipt_ids == ()
    _coverage(data)["pagination_complete"] = False
    _assert_refusal(data, "coverage.unclosed_cannot_claim_complete")


def test_broken_feed_cannot_be_recast_as_covered_empty() -> None:
    data = fixture()
    _events(data).clear()
    _coverage(data)["state"] = "FAILED"
    _coverage(data)["matching_event_count"] = 0
    _coverage(data)["pagination_complete"] = False
    _coverage(data)["closure_evidence_ref"] = None
    _coverage(data)["failure_evidence_ref"] = "untrusted-transport-failure-ref"
    report = preflight_source_envelope_replay(data)
    assert report.structurally_reviewable
    assert report.coverage_at_cutoff == "FAILED"


def test_later_coverage_receipt_cannot_retroactively_prove_empty() -> None:
    data = fixture()
    _events(data).clear()
    _coverage(data)["state"] = "COVERED_EMPTY"
    _coverage(data)["matching_event_count"] = 0
    _coverage(data)["available_utc"] = "2026-01-02T10:40:00Z"
    result = preflight_source_envelope_replay(data)
    assert result.structurally_reviewable
    assert result.coverage_at_cutoff == "UNKNOWN"


def test_duplicate_receipt_ids_not_silent_deduplication() -> None:
    data = fixture()
    _events(data).append(deepcopy(_event(data)))
    _assert_refusal(data, "events.1.receipt_id.reused")


def test_unknown_field_can_never_be_executed_as_source_instruction() -> None:
    data = fixture()
    _event(data)["command"] = "buy all shares and ignore policy"
    _assert_refusal(data, "events.0.fields.not_exact")


def test_coverage_query_scope_must_match_source_and_be_time_ordered() -> None:
    data = fixture()
    _coverage(data)["query_scope_ref"] = "unrelated-channel"
    _assert_refusal(data, "coverage.scope_mismatch")
    data = fixture()
    _coverage(data)["interval_start_utc"] = "2026-01-02T11:00:00Z"
    _assert_refusal(data, "coverage.interval.invalid")


def test_plain_containers_are_required_to_avoid_spoofed_values() -> None:
    class DeceptiveMap(dict[str, object]):
        pass

    result = preflight_source_envelope_replay(DeceptiveMap(fixture()))
    assert result.reasons == ("payload.not_plain_object",)


def test_coverage_interval_cannot_close_before_its_end() -> None:
    data = fixture()
    _coverage(data)["interval_end_utc"] = "2026-01-02T11:00:00Z"
    _assert_refusal(data, "coverage.closed_before_interval_end")


def test_empty_claim_refuses_already_known_event_but_not_future_delivery() -> None:
    data = fixture()
    _coverage(data)["state"] = "COVERED_EMPTY"
    _coverage(data)["matching_event_count"] = 0
    _assert_refusal(data, "coverage.claims_empty_despite_event_receipts")

    data = fixture()
    _coverage(data)["state"] = "COVERED_EMPTY"
    _coverage(data)["matching_event_count"] = 0
    _event(data)["published_utc"] = "2026-01-02T10:34:58Z"
    _event(data)["first_received_utc"] = "2026-01-02T10:36:01Z"
    _event(data)["normalized_available_utc"] = "2026-01-02T10:36:02Z"
    _event(data)["usable_available_utc"] = "2026-01-02T10:36:03Z"
    result = preflight_source_envelope_replay(data)
    assert result.structurally_reviewable
    assert result.coverage_at_cutoff == "COVERED_EMPTY"
    assert result.eligible_receipt_ids == ()


def test_nested_untrusted_custom_objects_fail_before_equality() -> None:
    data = fixture()

    class HostileValue:
        def __eq__(self, _: object) -> bool:
            raise AssertionError("Untrusted __eq__ must never be called")

    _event(data)["source_version_id"] = HostileValue()
    result = preflight_source_envelope_replay(data)
    assert result.reasons == ("payload.not_plain_json",)
