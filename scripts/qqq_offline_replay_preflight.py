"""Bounded offline, in-memory QQQ replay evidence review for #536 / #409.

No filesystem, provider or broker I/O. Matching bytes and metadata do not
authenticate Alpaca provenance, retention rights or historical coverage.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import cast

_REQUIRED_FILES = frozenset({"bars.json", "calendar.json", "corporate-actions.json"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_ROOT = frozenset({"profile", "window", "acquisition", "timezone", "objects"})
_WINDOW = frozenset({"name", "symbol", "start_date", "end_date"})
_ACQUISITION = frozenset({"started_utc", "finished_utc", "rights_state"})
_TZ = frozenset({"zone_id", "release", "tzif_sha256", "retained_tzif_ref"})
_OBJECT = frozenset(
    {
        "sha256",
        "origin_ref",
        "measured_request",
        "first_received_utc",
        "host",
        "route",
        "params",
        "pagination_state",
    }
)
_TYPES = (
    "capital_gains_distribution",
    "cash_dividend",
    "cash_merger",
    "forward_split",
    "name_change",
    "partial_call",
    "redemption",
    "reorganization",
    "reverse_split",
    "rights_distribution",
    "spin_off",
    "stock_and_cash_merger",
    "stock_dividend",
    "stock_merger",
    "unit_split",
    "worthless_removal",
)
_ENDPOINTS: dict[str, tuple[str, str]] = {
    "bars.json": ("data.alpaca.markets", "/v2/stocks/bars"),
    "calendar.json": ("paper-api.alpaca.markets", "/v2/calendar"),
    "corporate-actions.json": ("data.alpaca.markets", "/v1/corporate-actions"),
}
_MAX_OBJECT_BYTES = 2_000_000


@dataclass(frozen=True, slots=True)
class QQQReplayPreflight:
    """Self-described input audit; no externally authenticated evidence."""

    structurally_reviewable: bool
    exact_byte_digest_matches: tuple[str, ...]
    sources_with_claimed_origin: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def proves_entitlement_or_historical_origin(self) -> bool:
        return False

    @property
    def authorizes_data_access_or_trading(self) -> bool:
        return False


def _plain_json(value: object, depth: int, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0 or depth > 8:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is str:
        return len(value) <= 4096
    if type(value) is list:
        return len(value) <= 32 and all(
            _plain_json(v, depth + 1, budget) for v in value
        )
    if type(value) is dict:
        return len(value) <= 32 and all(
            type(k) is str and len(k) <= 100 and _plain_json(v, depth + 1, budget)
            for k, v in value.items()
        )
    return False


def _obj(
    value: object, fields: frozenset[str], path: str, problems: list[str]
) -> dict[str, object]:
    if type(value) is not dict:
        problems.append(f"{path}.not_plain_object")
        return {}
    record = cast(dict[str, object], value)
    if set(record) != fields:
        problems.append(f"{path}.fields.not_exact")
    return record


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _digest(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _utc(value: object) -> datetime | None:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return None
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return dt if dt.utcoffset() == timedelta(0) else None


def _day(value: object) -> date | None:
    if type(value) is not str or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _json_native(data: bytes) -> object:
    def reject_constant(value: str) -> object:
        raise ValueError(f"non-JSON numeric constant: {value}")

    def reject_duplicate(pairs: list[tuple[str, object]]) -> object:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate native JSON key")
            result[key] = value
        return result

    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=reject_duplicate,
        parse_constant=reject_constant,
    )


def _params_for(name: str, start: str, end: str) -> dict[str, str]:
    common = {"start": start, "end": end}
    if name == "bars.json":
        return {
            **common,
            "symbols": "QQQ",
            "feed": "sip",
            "timeframe": "1Day",
            "adjustment": "raw",
            "limit": "10000",
        }
    if name == "corporate-actions.json":
        return {**common, "symbols": "QQQ", "types": ",".join(_TYPES)}
    return common


def preflight_qqq_offline_replay(
    payloads: object, manifest: object
) -> QQQReplayPreflight:
    """Compare bytes with declared metadata; refuse partial or inconsistent data.

    Bytes supplied by the caller are never fetched, retained, or trusted as
    original provider responses. Digest matches are not signed origin proofs.
    """
    reasons: list[str] = []
    if type(payloads) is not dict:
        return QQQReplayPreflight(False, (), (), ("payloads.not_plain_object",))
    byte_map = cast(dict[str, object], payloads)
    if any(type(name) is not str for name in byte_map):
        return QQQReplayPreflight(
            False, (), (), ("payloads.filename.not_plain_string",)
        )
    if set(byte_map) != _REQUIRED_FILES:
        reasons.append("payloads.must_have_exact_three_sources")
    if not _plain_json(manifest, 0, [512]):
        return QQQReplayPreflight(False, (), (), ("manifest.not_plain_json",))
    root = _obj(manifest, _ROOT, "manifest", reasons)
    if root.get("profile") != "synthetic-qqq-replay-review-v1":
        reasons.append("profile.unsupported")
    window = _obj(root.get("window"), _WINDOW, "window", reasons)
    acquisition = _obj(root.get("acquisition"), _ACQUISITION, "acquisition", reasons)
    timezone = _obj(root.get("timezone"), _TZ, "timezone", reasons)
    objects = _obj(root.get("objects"), _REQUIRED_FILES, "objects", reasons)

    if not _text(window.get("name")):
        reasons.append("window.name.missing")
    if window.get("symbol") != "QQQ":
        reasons.append("window.symbol.must_be_QQQ")
    start = _day(window.get("start_date"))
    end = _day(window.get("end_date"))
    if start is None or end is None or end < start:
        reasons.append("window.date_range.invalid")
    start_str = start.isoformat() if start is not None else ""
    end_str = end.isoformat() if end is not None else ""
    acquisition_start = _utc(acquisition.get("started_utc"))
    acquisition_end = _utc(acquisition.get("finished_utc"))
    if (
        acquisition_start is None
        or acquisition_end is None
        or acquisition_start > acquisition_end
    ):
        reasons.append("acquisition.window.invalid")
    if acquisition.get("rights_state") not in (
        "UNKNOWN",
        "RESTRICTED",
        "CLAIMED_ALLOWED",
    ):
        reasons.append("acquisition.rights_state.invalid")

    if timezone.get("zone_id") != "America/New_York":
        reasons.append("timezone.zone_id.invalid")
    if not _text(timezone.get("release")):
        reasons.append("timezone.release.missing")
    if not _digest(timezone.get("tzif_sha256")):
        reasons.append("timezone.tzif_sha256.invalid")
    if not _text(timezone.get("retained_tzif_ref")):
        reasons.append("timezone.retained_tzif_ref.missing")

    matches: list[str] = []
    claimed_origin: list[str] = []
    for name in sorted(_REQUIRED_FILES):
        entry = _obj(objects.get(name), _OBJECT, f"objects.{name}", reasons)
        body = byte_map.get(name)
        if type(body) is not bytes or len(body) > _MAX_OBJECT_BYTES:
            reasons.append(f"{name}.payload.not_bounded_bytes")
            continue
        if not body:
            reasons.append(f"{name}.payload.empty")
            continue
        calculated = hashlib.sha256(body).hexdigest()
        if not _digest(entry.get("sha256")):
            reasons.append(f"{name}.sha256.invalid")
        elif calculated != entry["sha256"]:
            reasons.append(f"{name}.sha256.mismatch")
        else:
            matches.append(name)

        expected_host, expected_route = _ENDPOINTS[name]
        if entry.get("host") != expected_host:
            reasons.append(f"{name}.host.mismatch")
        if entry.get("route") != expected_route:
            reasons.append(f"{name}.route.mismatch")
        expected_params = _params_for(name, start_str, end_str)
        if entry.get("params") != expected_params:
            reasons.append(f"{name}.params.mismatch")

        when = _utc(entry.get("first_received_utc"))
        if when is None:
            reasons.append(f"{name}.first_received_utc.invalid")
        elif (
            acquisition_start is None
            or acquisition_end is None
            or not acquisition_start <= when <= acquisition_end
        ):
            reasons.append(f"{name}.receipt_outside_acquisition")
        if entry.get("measured_request") is not True:
            reasons.append(f"{name}.measured_request.not_proven")
        if not _text(entry.get("origin_ref")):
            reasons.append(f"{name}.origin_ref.missing")
        elif entry.get("measured_request") is True:
            claimed_origin.append(name)

        if entry.get("pagination_state") != "NO_MORE_PAGES":
            reasons.append(f"{name}.pagination.not_closed")
        try:
            doc = _json_native(body)
        except ValueError, UnicodeDecodeError, json.JSONDecodeError:
            reasons.append(f"{name}.native_json.invalid_or_duplicate_key")
            continue
        if name == "calendar.json":
            if type(doc) is not list:
                reasons.append("calendar.json.not_list")
        elif type(doc) is not dict:
            reasons.append(f"{name}.native_json.not_object")
        elif doc.get("next_page_token") is not None:
            reasons.append(f"{name}.native_pagination.open")

    if reasons:
        return QQQReplayPreflight(False, (), (), tuple(reasons))
    return QQQReplayPreflight(True, tuple(matches), tuple(claimed_origin), ())
