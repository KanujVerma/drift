"""CLI for bounded Alpaca exploratory cohort acquisition and intake.

This is the only part of the Alpaca bridge that is allowed to touch the
network. The adapter it drives imports no transport module at all, so every
mapping, validation, reconstruction, and bundling step stays offline and
replayable.

API keys are read from the environment and from nowhere else. They are passed
straight into request headers and are never printed, logged, written to the
private store, or placed into any receipt: `RequestIdentityV1` is
credential-free by construction and the receipt is screened before it is
minted. When either key is absent the tool reports that it is skipping network
acquisition and exits successfully, so an unconfigured checkout never raises.

Redirects are refused outright. `urllib`'s default redirect handler copies
every request header, including both API keys, onto the redirect target and
permits a plaintext `http://` destination on another origin, so a single 302
from anywhere on the path is enough to hand the credentials to a third party
in clear text. A market data API has no business redirecting an authenticated
GET, so the opener built here declines every 3xx instead of following it, and
each response is checked to have come back from the exact `https://` origin
that was asked for.

Origin evidence is measured, never assumed. Each fetch records the HTTP
status, the content type, the host, and the instant the body finished being
read, and those measurements are what reach the acquisition receipt. On the
`--offline-bytes` path no HTTP exchange happens in this process at all, so
there is nothing to measure: the measurements retained alongside the bytes at
acquisition time are read from an `origin.json` sidecar in the same directory,
and when that sidecar is absent the receipt records an unverified origin and
the bridge fails closed rather than asserting an exchange that did not happen.

Typical offline use, which needs no keys at all:

    uv run python scripts/intake_alpaca_exploratory.py \
        --offline-bytes /private/alpaca/raw \
        --private-root /private/alpaca/store \
        --declaration /private/alpaca/cohort.json

The `origin.json` sidecar has this exact shape, one entry per expected object
key, holding what was measured when the bytes were first acquired:

    {
      "schema_version": "1",
      "objects": {
        "alpaca-historical-bars": {
          "request_host": "data.alpaca.markets",
          "tls_endpoint_identity": "data.alpaca.markets",
          "http_status": 200,
          "content_type": "application/json",
          "observed_at": "2026-09-20T11:45:00+00:00"
        }
      }
    }
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drift.adapters.alpaca_exploratory import (  # noqa: E402
    ACTIONS_OBJECT_KEY,
    ALPACA_ACTIONS_ROUTE,
    ALPACA_BARS_ROUTE,
    ALPACA_CALENDAR_ROUTE,
    ALPACA_DATA_HOST,
    ALPACA_TRADING_HOST,
    BARS_OBJECT_KEY,
    CALENDAR_OBJECT_KEY,
    AlpacaCohortMember,
    AlpacaIntakeRequest,
    AlpacaNativePayloads,
    AlpacaOriginObservation,
    AlpacaReconstructionLineage,
    AlpacaTimezoneEvidence,
    retain_native_bytes,
    run_alpaca_exploratory_intake,
)
from drift.domain.securities import ListingVenue  # noqa: E402

KEY_ID_VARIABLE = "APCA_API_KEY_ID"
SECRET_KEY_VARIABLE = "APCA_API_SECRET_KEY"

BARS_FILE_NAME = "bars.json"
CALENDAR_FILE_NAME = "calendar.json"
ACTIONS_FILE_NAME = "corporate-actions.json"
ORIGIN_FILE_NAME = "origin.json"

_TIMEOUT_SECONDS = 30


class RedirectRefusedError(OSError):
    """Raised when a provider tries to redirect an authenticated request."""


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Decline every redirect instead of forwarding the API keys onward.

    `urllib`'s default handler rebuilds the request for the redirect target
    while stripping only Content-Type and Content-Length, so both
    `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` are copied verbatim onto
    whatever origin the Location header names, over plaintext `http://` if it
    says so. Refusing here means no second hop exists to leak them to.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise RedirectRefusedError(
            f"Alpaca acquisition refuses HTTP {code} redirects; the "
            "authenticated request was not forwarded"
        )


def _build_opener() -> urllib.request.OpenerDirector:
    """Build the one opener this tool is allowed to fetch through."""
    return urllib.request.build_opener(_RefuseRedirects())


def _api_keys_from_environment() -> tuple[str, str] | None:
    """Read the two Alpaca keys from the environment without echoing them."""
    key_id = os.environ.get(KEY_ID_VARIABLE)
    secret_key = os.environ.get(SECRET_KEY_VARIABLE)
    if not key_id or not secret_key:
        return None
    return key_id, secret_key


def _assert_same_tls_origin(requested: str, answered: str) -> None:
    """Refuse a response that came back from anywhere but the asked-for origin.

    TLS is required on every hop, not only the first. With redirects refused
    there is only one hop, and this states that as an executable check rather
    than leaving it to the construction of the URL.
    """
    wanted = urllib.parse.urlsplit(requested)
    got = urllib.parse.urlsplit(answered)
    if got.scheme != "https":
        raise RedirectRefusedError(
            f"Alpaca acquisition requires TLS on every hop, got {got.scheme}"
        )
    if (got.scheme, got.netloc) != (wanted.scheme, wanted.netloc):
        raise RedirectRefusedError(
            "Alpaca acquisition answered from a different origin than the one "
            "it was sent to"
        )


def _fetch_bytes(
    object_key: str,
    host: str,
    route: str,
    parameters: Mapping[str, str],
    keys: tuple[str, str],
) -> tuple[bytes, AlpacaOriginObservation]:
    """Fetch one exact response body over TLS, never logging the keys.

    Returns the body together with what was measured about the exchange, so
    the receipt can carry a real status, a real content type, and a real host
    instead of a constant.
    """
    query = urllib.parse.urlencode(sorted(parameters.items()))
    url = f"https://{host}{route}?{query}"
    if not url.startswith("https://"):  # pragma: no cover - defensive
        raise ValueError("Alpaca acquisition requires TLS")
    appeal = urllib.request.Request(url, method="GET")
    appeal.add_header("APCA-API-KEY-ID", keys[0])
    appeal.add_header("APCA-API-SECRET-KEY", keys[1])
    appeal.add_header("Accept", "application/json")
    with _build_opener().open(appeal, timeout=_TIMEOUT_SECONDS) as response:
        answered = response.geturl()
        _assert_same_tls_origin(url, answered)
        status = int(response.status)
        content_type = response.headers.get("Content-Type")
        body = response.read()
        observed_at = datetime.now(UTC)
    if not isinstance(body, bytes):  # pragma: no cover - defensive
        raise TypeError("Alpaca response body must be exact bytes")
    return body, AlpacaOriginObservation(
        object_key=object_key,
        request_host=urllib.parse.urlsplit(answered).hostname or host,
        tls_endpoint_identity=host,
        http_status=status,
        content_type=content_type,
        observed_at=observed_at,
    )


def _acquire_payloads(
    declaration: Mapping[str, Any], keys: tuple[str, str]
) -> tuple[AlpacaNativePayloads, dict[str, AlpacaOriginObservation]]:
    """Acquire the three declared endpoints for the bounded cohort."""
    symbols = ",".join(
        sorted(str(member["symbol"]) for member in declaration["members"])
    )
    start = str(declaration["start_date"])
    end = str(declaration["end_date"])
    bars, bars_origin = _fetch_bytes(
        BARS_OBJECT_KEY,
        ALPACA_DATA_HOST,
        ALPACA_BARS_ROUTE,
        {
            "symbols": symbols,
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "feed": "sip",
            "adjustment": "raw",
        },
        keys,
    )
    calendar, calendar_origin = _fetch_bytes(
        CALENDAR_OBJECT_KEY,
        ALPACA_TRADING_HOST,
        ALPACA_CALENDAR_ROUTE,
        {"start": start, "end": end},
        keys,
    )
    actions, actions_origin = _fetch_bytes(
        ACTIONS_OBJECT_KEY,
        ALPACA_DATA_HOST,
        ALPACA_ACTIONS_ROUTE,
        {"symbols": symbols, "start": start, "end": end, "types": "cash_dividend"},
        keys,
    )
    payloads = AlpacaNativePayloads(
        bars=bars, calendar=calendar, corporate_actions=actions
    )
    return payloads, {
        BARS_OBJECT_KEY: bars_origin,
        CALENDAR_OBJECT_KEY: calendar_origin,
        ACTIONS_OBJECT_KEY: actions_origin,
    }


def _load_offline_payloads(directory: Path) -> AlpacaNativePayloads:
    """Load exact retained response bytes already on disk."""
    return AlpacaNativePayloads(
        bars=(directory / BARS_FILE_NAME).read_bytes(),
        calendar=(directory / CALENDAR_FILE_NAME).read_bytes(),
        corporate_actions=(directory / ACTIONS_FILE_NAME).read_bytes(),
    )


def _load_offline_origin(
    directory: Path,
) -> dict[str, AlpacaOriginObservation] | None:
    """Load the origin evidence retained beside the bytes, if any exists.

    No sidecar means nothing was measured in a form this run can read, so the
    caller gets ``None`` and the receipt records an unverified origin.
    """
    path = directory / ORIGIN_FILE_NAME
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = document["objects"]
    observations: dict[str, AlpacaOriginObservation] = {}
    for key, entry in entries.items():
        tls = entry.get("tls_endpoint_identity")
        content_type = entry.get("content_type")
        observations[str(key)] = AlpacaOriginObservation(
            object_key=str(key),
            request_host=str(entry["request_host"]),
            tls_endpoint_identity=None if tls is None else str(tls),
            http_status=int(entry["http_status"]),
            content_type=None if content_type is None else str(content_type),
            observed_at=_instant(str(entry["observed_at"])),
        )
    return observations


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _read_declaration(path: Path) -> tuple[Mapping[str, Any], AlpacaIntakeRequest]:
    """Read the bounded intake declaration and build its request."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("the intake declaration must be a JSON object")
    root = path.parent
    timezone_block = document["timezone"]
    lineage_block = document["lineage"]
    offsets: dict[tuple[date, str], int] = {}
    for entry in document["boundary_offsets"]:
        offsets[(date.fromisoformat(entry["date"]), str(entry["boundary"]))] = int(
            entry["utc_offset_seconds"]
        )
    members = tuple(
        AlpacaCohortMember(
            symbol=str(member["symbol"]),
            security_id=UUID(str(member["security_id"])),
            listing_id=UUID(str(member["listing_id"])),
            venue=ListingVenue(str(member["venue"])),
        )
        for member in document["members"]
    )
    request = AlpacaIntakeRequest(
        cohort_id=str(document["cohort_id"]),
        cohort_version=str(document["cohort_version"]),
        members=members,
        mic=str(document["mic"]),
        start_date=date.fromisoformat(str(document["start_date"])),
        end_date=date.fromisoformat(str(document["end_date"])),
        plan_frozen_at=_instant(str(document["plan_frozen_at"])),
        request_start=_instant(str(document["request_start"])),
        request_end=_instant(str(document["request_end"])),
        evidence_vintage_cutoff=_instant(str(document["evidence_vintage_cutoff"])),
        timezone_evidence=AlpacaTimezoneEvidence(
            timezone_identifier=str(timezone_block["identifier"]),
            source_timezone_label=str(timezone_block["label"]),
            tzif_bytes=(root / str(timezone_block["tzif_path"])).read_bytes(),
            tzdb_release=str(timezone_block["tzdb_release"]),
            reconstruction_observed_at=_instant(str(document["request_end"])),
        ),
        lineage=AlpacaReconstructionLineage(
            producer_source=(
                root / str(lineage_block["producer_source_path"])
            ).read_bytes(),
            producer_package=(
                root / str(lineage_block["producer_package_path"])
            ).read_bytes(),
            lockfile=(root / str(lineage_block["lockfile_path"])).read_bytes(),
            python_identity=str(lineage_block["python_identity"]),
        ),
        boundary_offsets=offsets,
    )
    return document, request


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intake_alpaca_exploratory",
        description=(
            "Acquire a bounded Alpaca development cohort and run the offline "
            "exploratory intake bridge."
        ),
    )
    parser.add_argument(
        "--private-root",
        type=Path,
        required=True,
        help="private content-addressed retention root, outside any Git tree",
    )
    parser.add_argument(
        "--declaration",
        type=Path,
        default=None,
        help="bounded intake declaration; required to run the full bridge",
    )
    parser.add_argument(
        "--offline-bytes",
        type=Path,
        default=None,
        help="directory of already-retained response bytes; skips all acquisition",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one bounded acquisition and intake, or skip it cleanly."""
    arguments = _build_parser().parse_args(argv)
    declaration: Mapping[str, Any] | None = None
    request: AlpacaIntakeRequest | None = None
    if arguments.declaration is not None:
        declaration, request = _read_declaration(arguments.declaration)

    origin: dict[str, AlpacaOriginObservation] | None = None
    if arguments.offline_bytes is not None:
        payloads = _load_offline_payloads(arguments.offline_bytes)
        origin = _load_offline_origin(arguments.offline_bytes)
        print(f"loaded retained bytes from {arguments.offline_bytes}")
        if origin is None:
            print(
                "no retained origin evidence beside those bytes: this run "
                "performs no HTTP exchange, so the receipt will record an "
                f"unverified origin. Add {ORIGIN_FILE_NAME} to replay the "
                "measurements taken when the bytes were acquired."
            )
    else:
        keys = _api_keys_from_environment()
        if keys is None:
            print(
                "skipping Alpaca acquisition: "
                f"{KEY_ID_VARIABLE} and {SECRET_KEY_VARIABLE} are not both set. "
                "Re-run with --offline-bytes to use already-retained responses."
            )
            return 0
        if declaration is None:
            print(
                "skipping Alpaca acquisition: --declaration is required to "
                "bound the requested cohort and window."
            )
            return 0
        try:
            payloads, origin = _acquire_payloads(declaration, keys)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            print(f"Alpaca acquisition failed: {type(error).__name__}")
            return 1
    if request is not None:
        request = replace(request, origin_observations=origin)

    retained = retain_native_bytes(arguments.private_root, payloads)
    print(f"retained bars sha256 {retained.bars_hash}")
    print(f"retained calendar sha256 {retained.calendar_hash}")
    print(f"retained corporate actions sha256 {retained.corporate_actions_hash}")

    if request is None:
        print("no declaration supplied; stopping after private retention")
        return 0

    result = run_alpaca_exploratory_intake(
        request=request,
        payloads=payloads,
        private_root=arguments.private_root,
    )
    print(f"acquisition receipt {result.acquisition.receipt.receipt_id}")
    print(f"reconciliation {result.acquisition.reconciliation.result.value}")
    print(f"sessions {len(result.session_clock.sessions)}")
    print(f"reconstructions {len(result.reconstructions)}")
    print(f"bundle sha256 {result.bundle.bundle_hash}")
    print(f"exploratory admission sha256 {result.admission.admission_hash}")
    for limitation in result.admission.acknowledged_limitations:
        print(f"acknowledged limitation {limitation}")
    print("lane exploratory; this evidence is never promotion-grade")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
