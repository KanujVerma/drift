"""Deferred synthetic QQQ in-memory evidence tests for #536; NOT executed."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import cast

import pytest

from scripts.qqq_offline_replay_preflight import (
    _TYPES,
    preflight_qqq_offline_replay,
)


def fixture() -> tuple[dict[str, bytes], dict[str, object]]:
    payloads = {
        "bars.json": b'{"bars":{"QQQ":[]}}',
        "calendar.json": b"[]",
        "corporate-actions.json": b'{"cash_dividend":[]}',
    }
    endpoint = {
        "bars.json": (
            "data.alpaca.markets", "/v2/stocks/bars",
            {"start": "2021-08-03", "end": "2021-08-27",
             "symbols": "QQQ", "feed": "sip", "timeframe": "1Day",
             "adjustment": "raw", "limit": "10000"},
        ),
        "calendar.json": (
            "paper-api.alpaca.markets", "/v2/calendar",
            {"start": "2021-08-03", "end": "2021-08-27"},
        ),
        "corporate-actions.json": (
            "data.alpaca.markets", "/v1/corporate-actions",
            {"start": "2021-08-03", "end": "2021-08-27",
             "symbols": "QQQ", "types": ",".join(_TYPES)},
        ),
    }
    entries: dict[str, object] = {}
    for name, data in payloads.items():
        host, route, params = endpoint[name]
        entries[name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "origin_ref": f"untrusted-origin-{name}",
            "measured_request": True,
            "first_received_utc": "2026-10-20T10:00:05Z",
            "host": host,
            "route": route,
            "params": params,
            "pagination_state": "NO_MORE_PAGES",
        }
    return payloads, {
        "profile": "synthetic-qqq-replay-review-v1",
        "window": {
            "name": "mock-August-2021",
            "symbol": "QQQ",
            "start_date": "2021-08-03",
            "end_date": "2021-08-27",
        },
        "acquisition": {
            "started_utc": "2026-10-20T10:00:00Z",
            "finished_utc": "2026-10-20T10:00:10Z",
            "rights_state": "UNKNOWN",
        },
        "timezone": {
            "zone_id": "America/New_York",
            "release": "2026b",
            "tzif_sha256": "a" * 64,
            "retained_tzif_ref": "untrusted-TZIF-evidence-ref",
        },
        "objects": entries,
    }


def obj(meta: dict[str, object], name: str) -> dict[str, object]:
    return cast(dict[str, object], cast(dict[str, object], meta["objects"])[name])


def _refuse(
    data: dict[str, bytes], meta: dict[str, object], expected: str
) -> None:
    result = preflight_qqq_offline_replay(data, meta)
    assert not result.structurally_reviewable
    assert result.exact_byte_digest_matches == ()
    assert result.sources_with_claimed_origin == ()
    assert expected in result.reasons
    assert not result.proves_entitlement_or_historical_origin
    assert not result.authorizes_data_access_or_trading


def test_coherent_mock_three_source_package_grants_nothing() -> None:
    payloads, meta = fixture()
    result = preflight_qqq_offline_replay(payloads, meta)
    assert result.structurally_reviewable
    assert result.reasons == ()
    assert result.exact_byte_digest_matches == (
        "bars.json", "calendar.json", "corporate-actions.json",
    )
    assert result.sources_with_claimed_origin == (
        "bars.json", "calendar.json", "corporate-actions.json",
    )
    assert not result.proves_entitlement_or_historical_origin
    assert not result.authorizes_data_access_or_trading


def test_unverified_account_rights_never_become_provider_entitlement() -> None:
    payloads, meta = fixture()
    cast(dict[str, object], meta["acquisition"])["rights_state"] = (
        "CLAIMED_ALLOWED"
    )
    result = preflight_qqq_offline_replay(payloads, meta)
    assert result.structurally_reviewable
    assert not result.proves_entitlement_or_historical_origin


def test_required_exact_three_responses_not_silently_omitted() -> None:
    payloads, meta = fixture()
    del payloads["calendar.json"]
    _refuse(payloads, meta, "payloads.must_have_exact_three_sources")


def test_byte_mutation_does_not_still_match_original_digest() -> None:
    payloads, meta = fixture()
    payloads["bars.json"] = b'{"bars":{"QQQ":[{"new":"later"}]}}'
    _refuse(payloads, meta, "bars.json.sha256.mismatch")


def test_spoofed_hash_or_unbounded_payload_refuses() -> None:
    payloads, meta = fixture()
    obj(meta, "bars.json")["sha256"] = "not-a-digest"
    _refuse(payloads, meta, "bars.json.sha256.invalid")
    payloads, meta = fixture()
    payloads["bars.json"] = b"x" * 2_000_001
    _refuse(payloads, meta, "bars.json.payload.not_bounded_bytes")


def test_source_specific_paper_calendar_host_cannot_be_data_host() -> None:
    payloads, meta = fixture()
    obj(meta, "calendar.json")["host"] = "data.alpaca.markets"
    _refuse(payloads, meta, "calendar.json.host.mismatch")


def test_bars_raw_sip_daily_and_limit_are_fixed_fixture_constraints() -> None:
    payloads, meta = fixture()
    params = cast(dict[str, str], obj(meta, "bars.json")["params"])
    params["feed"] = "iex"
    _refuse(payloads, meta, "bars.json.params.mismatch")


def test_actions_full_sixteen_names_required_not_old_one_type() -> None:
    payloads, meta = fixture()
    params = cast(dict[str, str], obj(meta, "corporate-actions.json")["params"])
    params["types"] = "cash_dividend"
    _refuse(payloads, meta, "corporate-actions.json.params.mismatch")


def test_tampered_source_window_dates_do_not_match_request() -> None:
    payloads, meta = fixture()
    cast(dict[str, object], meta["window"])["end_date"] = "2021-09-01"
    _refuse(payloads, meta, "bars.json.params.mismatch")


def test_source_receipt_cannot_precede_measured_acquisition() -> None:
    payloads, meta = fixture()
    obj(meta, "bars.json")["first_received_utc"] = "2026-10-20T09:59:00Z"
    _refuse(payloads, meta, "bars.json.receipt_outside_acquisition")


def test_claimed_origin_must_have_record_and_measured_request() -> None:
    payloads, meta = fixture()
    obj(meta, "bars.json")["measured_request"] = False
    _refuse(payloads, meta, "bars.json.measured_request.not_proven")
    payloads, meta = fixture()
    obj(meta, "bars.json")["origin_ref"] = ""
    _refuse(payloads, meta, "bars.json.origin_ref.missing")


def test_partial_pagination_is_never_complete_replay() -> None:
    payloads, meta = fixture()
    obj(meta, "corporate-actions.json")["pagination_state"] = "UNKNOWN"
    _refuse(payloads, meta, "corporate-actions.json.pagination.not_closed")


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("bars.json", b'{"bars":{},"next_page_token":"later"}'),
        ("corporate-actions.json", b'{"cash_dividend":[],"next_page_token":"more"}'),
    ],
)
def test_native_pagination_token_is_not_an_empty_interval(
    name: str, text: bytes
) -> None:
    payloads, meta = fixture()
    payloads[name] = text
    obj(meta, name)["sha256"] = hashlib.sha256(text).hexdigest()
    _refuse(payloads, meta, f"{name}.native_pagination.open")


def test_duplicate_native_json_keys_are_not_last_wins() -> None:
    payloads, meta = fixture()
    changed = b'{"bars":{},"bars":{"QQQ":[]}}'
    payloads["bars.json"] = changed
    obj(meta, "bars.json")["sha256"] = hashlib.sha256(changed).hexdigest()
    _refuse(payloads, meta, "bars.json.native_json.invalid_or_duplicate_key")


def test_native_payload_must_be_json_of_expected_top_level_shape() -> None:
    payloads, meta = fixture()
    changed = b"{}"
    payloads["calendar.json"] = changed
    obj(meta, "calendar.json")["sha256"] = hashlib.sha256(changed).hexdigest()
    _refuse(payloads, meta, "calendar.json.not_list")


def test_timezone_release_or_TZIF_digest_absence_is_explicit() -> None:
    payloads, meta = fixture()
    cast(dict[str, object], meta["timezone"])["tzif_sha256"] = None
    _refuse(payloads, meta, "timezone.tzif_sha256.invalid")


def test_pretend_live_host_cannot_replace_data_source() -> None:
    payloads, meta = fixture()
    obj(meta, "bars.json")["host"] = "api.alpaca.markets"
    _refuse(payloads, meta, "bars.json.host.mismatch")


def test_extra_network_instruction_rejected_as_schema_noise() -> None:
    payloads, meta = fixture()
    obj(meta, "bars.json")["request_password"] = "do not use"
    _refuse(payloads, meta, "objects.bars.json.fields.not_exact")


def test_self_defined_nested_equality_cannot_run() -> None:
    class Hostile:
        def __eq__(self, _: object) -> bool:
            raise AssertionError("untrusted Python equality invoked")

    payloads, meta = fixture()
    obj(meta, "bars.json")["route"] = Hostile()
    _refuse(payloads, meta, "manifest.not_plain_json")


def test_replay_fixture_not_profitability_or_actual_data_claim() -> None:
    payloads, meta = fixture()
    replay = preflight_qqq_offline_replay(deepcopy(payloads), deepcopy(meta))
    assert replay.structurally_reviewable
    assert replay.exact_byte_digest_matches == (
        "bars.json", "calendar.json", "corporate-actions.json",
    )
    assert replay.proves_entitlement_or_historical_origin is False
