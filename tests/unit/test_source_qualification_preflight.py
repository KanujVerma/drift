"""Synthetic source-evidence acceptance cases for #524."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from scripts.source_qualification_preflight import preflight_source_qualification

OBSERVED = "2026-10-20T12:00:00Z"


def source_fixture(profile: str = "news_historical") -> dict[str, object]:
    common = {
        "api_documentation",
        "account_entitlement",
        "licensed_purpose",
        "retention_and_replay_rights",
        "source_identity",
        "interval_coverage",
        "complete_cost_basis",
    }
    news = {
        "original_content_version",
        "publication_and_receipt_clocks",
        "correction_lineage",
        "feed_health_and_query_closure",
    }
    market = {
        "point_in_time_listing",
        "real_venue_mapping",
        "session_calendar",
        "quote_resolution",
        "quote_and_size_coverage",
        "corporate_action_basis",
    }
    historical = {"historical_version_archive", "historical_availability_basis"}
    prospective = {"prospective_capture_scope"}
    fields = (
        common
        | (news if profile.startswith("news") else market)
        | (historical if profile.endswith("historical") else prospective)
    )
    dimensions: dict[str, object] = {}
    for name in fields:
        dimensions[name] = {
            "status": "documented" if name == "api_documentation" else "verified",
            "evidence_ref": f"synthetic-proof-{name}",
            "scope_ref": "synthetic-window",
            "observed_utc": OBSERVED,
        }
    return {
        "profile": profile,
        "candidate_id": "candidate-synthetic-A",
        "provider_product_ref": "product-plan-reference",
        "purpose_ref": "offline-historical-review",
        "scope_ref": "synthetic-window",
        "evidence_owner": "fixture-preparer",
        "independent_reviewer": "fixture-reviewer",
        "dimensions": dimensions,
        "sample": {
            "decision_cutoff_utc": "2026-01-02T10:32:05Z",
            "selected_version_id": "original-v1",
            "versions": [
                {
                    "version_id": "original-v1",
                    "payload_ref": "original-retained-bytes-v1",
                    "published_utc": "2026-01-02T10:32:00Z",
                    "first_received_utc": "2026-01-02T10:32:01Z",
                    "normalized_available_utc": "2026-01-02T10:32:02Z",
                    "supersedes_id": None,
                },
                {
                    "version_id": "corrected-v2",
                    "payload_ref": "distinct-retained-bytes-v2",
                    "published_utc": "2026-01-02T10:32:09Z",
                    "first_received_utc": "2026-01-02T10:32:10Z",
                    "normalized_available_utc": "2026-01-02T10:32:11Z",
                    "supersedes_id": "original-v1",
                },
            ],
        },
    }


def _dimensions(payload: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], payload["dimensions"])


def _sample(payload: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], payload["sample"])


def _version(payload: dict[str, object], index: int) -> dict[str, object]:
    versions = cast(list[dict[str, object]], _sample(payload)["versions"])
    return versions[index]


@pytest.mark.parametrize(
    "profile",
    [
        "news_historical",
        "news_prospective",
        "market_historical",
        "market_prospective",
    ],
)
def test_structural_candidate_is_never_a_right_or_access_grant(
    profile: str,
) -> None:
    report = preflight_source_qualification(source_fixture(profile))
    assert report.review_ready is True
    assert report.selected_causal_version_id == "original-v1"
    assert report.reasons == ()
    assert report.establishes_rights_or_source_grade is False
    assert report.authorizes_provider_access is False


@pytest.mark.parametrize(
    ("dimension", "status"),
    [
        ("account_entitlement", "documented"),
        ("licensed_purpose", "unknown"),
        ("retention_and_replay_rights", "denied"),
        ("complete_cost_basis", "unknown"),
        ("interval_coverage", "documented"),
    ],
)
def test_documentation_is_not_account_qualification(
    dimension: str, status: str
) -> None:
    payload = source_fixture()
    entry = cast(dict[str, object], _dimensions(payload)[dimension])
    entry["status"] = status
    report = preflight_source_qualification(payload)
    assert not report.review_ready
    assert f"{dimension}.not_verified" in report.reasons


def test_corrected_version_must_not_backdate_a_decision() -> None:
    payload = source_fixture()
    _sample(payload)["selected_version_id"] = "corrected-v2"
    report = preflight_source_qualification(payload)
    assert not report.review_ready
    assert "sample.selected_version_not_causally_available" in report.reasons


def test_original_bytes_missing_cannot_be_substituted_by_a_hash() -> None:
    payload = source_fixture()
    _version(payload, 0)["payload_ref"] = ""
    result = preflight_source_qualification(payload)
    assert not result.review_ready
    assert "sample.versions.0.payload_ref.missing" in result.reasons


def test_earlier_version_cannot_appear_after_its_normalization() -> None:
    payload = source_fixture()
    _version(payload, 0)["first_received_utc"] = "2026-01-02T10:32:04Z"
    report = preflight_source_qualification(payload)
    assert not report.review_ready
    assert "sample.versions.0.available_before_receipt" in report.reasons


def test_repeated_identifiers_and_broken_correction_lineage_refuse() -> None:
    payload = source_fixture()
    _version(payload, 1)["version_id"] = "original-v1"
    assert "sample.versions.1.version_id.duplicate" in (
        preflight_source_qualification(payload).reasons
    )
    payload = source_fixture()
    _version(payload, 1)["supersedes_id"] = "missing-v0"
    assert "sample.versions.1.supersedes_id.lineage_mismatch" in (
        preflight_source_qualification(payload).reasons
    )


def test_cutoff_equality_without_proven_tie_order_is_ineligible() -> None:
    payload = source_fixture()
    _sample(payload)["decision_cutoff_utc"] = "2026-01-02T10:32:02Z"
    report = preflight_source_qualification(payload)
    assert not report.review_ready
    assert "sample.no_proven_available_version" in report.reasons


def test_scope_or_dimension_mismatch_fails_closed() -> None:
    payload = source_fixture()
    entry = cast(dict[str, object], _dimensions(payload)["account_entitlement"])
    entry["scope_ref"] = "different-product"
    assert "account_entitlement.scope_mismatch" in (
        preflight_source_qualification(payload).reasons
    )
    payload = source_fixture()
    del _dimensions(payload)["account_entitlement"]
    assert "dimensions.must_match_profile" in (
        preflight_source_qualification(payload).reasons
    )


def test_unknown_time_offset_and_extra_fields_are_not_accepted() -> None:
    payload = source_fixture()
    _version(payload, 0)["normalized_available_utc"] = "2026-01-02T02:32:02-08:00"
    assert "sample.versions.0.normalized_available_utc.invalid_or_unknown" in (
        preflight_source_qualification(payload).reasons
    )
    payload = source_fixture()
    payload["unreviewed_capability"] = True
    assert "payload.fields.not_exact" in preflight_source_qualification(payload).reasons


def test_claimed_self_review_and_subclassed_dict_fail() -> None:
    payload = source_fixture()
    payload["independent_reviewer"] = payload["evidence_owner"]
    assert "independent_reviewer.self_review" in (
        preflight_source_qualification(payload).reasons
    )

    class SpoofedDict(dict[str, object]):
        pass

    report = preflight_source_qualification(SpoofedDict(deepcopy(payload)))
    assert report.reasons == ("payload.not_plain_object",)


def _scalar_slot(
    payload: dict[str, object], location: str
) -> tuple[dict[str, object], str]:
    if location.startswith("versions."):
        _, index, field = location.split(".")
        return _version(payload, int(index)), field
    if location.startswith("dimensions."):
        _, dimension, field = location.split(".")
        return cast(dict[str, object], _dimensions(payload)[dimension]), field
    if location == "selected_version_id":
        return _sample(payload), location
    return payload, location


def _hostile_scalar(kind: str, behavior: str, callbacks: list[str]) -> object:
    class Hostile:
        def __eq__(self, _: object) -> bool:
            callbacks.append("equality")
            if behavior == "raise":
                raise AssertionError("untrusted scalar equality invoked")
            return True

        def __ne__(self, _: object) -> bool:
            callbacks.append("inequality")
            if behavior == "raise":
                raise AssertionError("untrusted scalar inequality invoked")
            return False

        def __hash__(self) -> int:
            callbacks.append("hash")
            if behavior == "raise":
                raise AssertionError("untrusted scalar hash invoked")
            return 0

    class HostileText(Hostile, str):
        pass

    return (
        HostileText("nonexistent-version") if kind == "string_subclass" else Hostile()
    )


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        (
            "versions.0.supersedes_id",
            "sample.versions.0.supersedes_id.lineage_mismatch",
        ),
        (
            "versions.1.supersedes_id",
            "sample.versions.1.supersedes_id.lineage_mismatch",
        ),
        ("independent_reviewer", "independent_reviewer.missing"),
        ("evidence_owner", "evidence_owner.missing"),
        ("scope_ref", "scope_ref.missing"),
        (
            "dimensions.account_entitlement.scope_ref",
            "account_entitlement.scope_mismatch",
        ),
        ("selected_version_id", "sample.selected_version_id.missing"),
        ("versions.0.version_id", "sample.versions.0.version_id.missing"),
        ("versions.0.payload_ref", "sample.versions.0.payload_ref.missing"),
    ],
)
@pytest.mark.parametrize("kind", ["object", "string_subclass"])
@pytest.mark.parametrize("behavior", ["spoof", "raise"])
def test_malformed_lineage_and_comparison_scalars_refuse_without_callbacks(
    location: str, reason: str, kind: str, behavior: str
) -> None:
    payload = source_fixture()
    owner, field = _scalar_slot(payload, location)
    callbacks: list[str] = []
    owner[field] = _hostile_scalar(kind, behavior, callbacks)
    report = preflight_source_qualification(payload)
    assert not report.review_ready
    assert report.selected_causal_version_id is None
    assert reason in report.reasons
    assert report.establishes_rights_or_source_grade is False
    assert report.authorizes_provider_access is False
    assert callbacks == []


@pytest.mark.parametrize(
    ("index", "supersedes"),
    [(0, "nonexistent-version"), (1, "nonexistent-version"), (1, None), (1, "")],
)
def test_plain_wrong_predecessors_preserve_lineage_refusal(
    index: int, supersedes: str | None
) -> None:
    payload = source_fixture()
    _version(payload, index)["supersedes_id"] = supersedes
    report = preflight_source_qualification(payload)
    assert not report.review_ready
    assert report.selected_causal_version_id is None
    assert report.reasons == (
        f"sample.versions.{index}.supersedes_id.lineage_mismatch",
    )
    assert report.establishes_rights_or_source_grade is False
    assert report.authorizes_provider_access is False


@pytest.mark.parametrize(
    "profile",
    ["news_historical", "news_prospective", "market_historical", "market_prospective"],
)
@pytest.mark.parametrize(
    ("cutoff", "selected"),
    [
        ("2026-01-02T10:32:11Z", "original-v1"),
        ("2026-01-02T10:32:11.000001Z", "corrected-v2"),
    ],
)
def test_strict_cutoff_preserves_valid_original_and_correction_selection(
    profile: str, cutoff: str, selected: str
) -> None:
    payload = source_fixture(profile)
    _sample(payload).update(decision_cutoff_utc=cutoff, selected_version_id=selected)
    before = deepcopy(payload)
    report = preflight_source_qualification(payload)
    assert report.review_ready
    assert report.selected_causal_version_id == selected
    assert report.reasons == ()
    assert report == preflight_source_qualification(deepcopy(payload))
    assert payload == before
    assert report.establishes_rights_or_source_grade is False
    assert report.authorizes_provider_access is False
