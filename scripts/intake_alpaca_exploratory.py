"""CLI for bounded Alpaca exploratory cohort acquisition and intake.

This is the only part of the Alpaca bridge that is allowed to touch the
network. The adapter it drives imports no transport module at all, so every
mapping, validation, reconstruction, and bundling step stays offline and
replayable.

Only two hosts are ever contacted: ``data.alpaca.markets`` for bars and
corporate actions, and ``paper-api.alpaca.markets`` for the market calendar.
Alpaca was selected as the free development source because paper account
credentials exist, so the calendar is read from the paper trading API, never
from the live brokerage host ``api.alpaca.markets``, and there is no switch
that selects it. Any other host is refused before a request is built.

API keys are read from the environment and from nowhere else: exactly
``APCA_API_KEY_ID`` and ``APCA_API_SECRET_KEY``, and nothing else in this
repository may read them. They are passed straight into request headers and
are never printed, logged, written to the private store, or placed into any
receipt: `RequestIdentityV1` is credential-free by construction and the
receipt is screened before it is minted. When either key is unset the tool
reports that it is skipping network acquisition and exits successfully, so an
unconfigured checkout never raises. A key that is set but is not non-empty
printable ASCII free of whitespace and control characters is refused by the
name of its variable, before any request exists, because `http.client` would
otherwise either put it on the wire unchanged or raise an exception whose
message is the key itself.

Redirects are refused outright. `urllib`'s default redirect handler copies
every request header, including both API keys, onto the redirect target and
permits a plaintext `http://` destination on another origin, so a single 302
from anywhere on the path is enough to hand the credentials to a third party
in clear text. A market data API has no business redirecting an authenticated
GET, so the opener built here declines every 3xx instead of following it, and
each response is checked to have come back from the exact `https://` origin
that was asked for before its body is read.

Origin evidence is measured, never assumed. Each fetch records the HTTP
status, the content type, the host, the instant the body finished being read,
and the SHA-256 and byte size of the exact body, and those measurements are
what reach the acquisition receipt. An online run also persists each
measurement as a content-addressed record in the private store, beside the
bytes it measured. On the ``--offline-bytes`` path no HTTP exchange happens in
this process at all, so there is nothing to measure: an origin is certified
only by a retained record that names the SHA-256 of exactly the bytes being
replayed, and every other object is recorded as an unverified origin, which
makes the bridge fail closed. Replay against the same ``--private-root`` the
acquisition wrote to. No free-standing file beside the bytes is ever read as
origin evidence.

Typical offline use, which needs no keys at all:

    uv run python scripts/intake_alpaca_exploratory.py \
        --offline-bytes /private/alpaca/raw \
        --private-root /private/alpaca/store \
        --declaration /private/alpaca/cohort.json
"""

import argparse
import http.client
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
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
    ALPACA_PAPER_TRADING_HOST,
    BARS_OBJECT_KEY,
    CALENDAR_OBJECT_KEY,
    AlpacaCohortMember,
    AlpacaIntakeRequest,
    AlpacaNativePayloads,
    AlpacaOriginObservation,
    AlpacaReconstructionLineage,
    AlpacaTimezoneEvidence,
    RetainedNativeBytes,
    load_retained_origin_observations,
    retain_native_bytes,
    retain_origin_observations,
    run_alpaca_exploratory_intake,
)
from drift.domain.securities import ListingVenue  # noqa: E402

KEY_ID_VARIABLE = "APCA_API_KEY_ID"
SECRET_KEY_VARIABLE = "APCA_API_SECRET_KEY"

BARS_FILE_NAME = "bars.json"
CALENDAR_FILE_NAME = "calendar.json"
ACTIONS_FILE_NAME = "corporate-actions.json"

#: The only hosts this tool may ever contact, written as literals rather than
#: derived from the adapter's endpoint table so that no changed constant can
#: widen it. The live brokerage host ``api.alpaca.markets`` is not one of them.
PERMITTED_HOSTS = frozenset({"data.alpaca.markets", "paper-api.alpaca.markets"})

_EXPECTED_OBJECT_KEYS = (BARS_OBJECT_KEY, CALENDAR_OBJECT_KEY, ACTIONS_OBJECT_KEY)
_TIMEOUT_SECONDS = 30


class RedirectRefusedError(OSError):
    """Raised when a provider tries to redirect an authenticated request."""


class UnauthorizedHostError(ValueError):
    """Raised before any request is built for a host this tool may not contact."""


class InvalidApiKeyError(ValueError):
    """Raised for a key that is set but cannot be sent safely.

    The message names the environment variable and never the value, so this
    exception is safe to print and safe to let a traceback show.
    """

    def __init__(self, variable: str) -> None:
        super().__init__(
            f"{variable} is set but is not a usable Alpaca API key: a key must be "
            "non-empty printable ASCII with no whitespace or control characters. "
            "Its value is not shown."
        )
        self.variable = variable


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


def _usable_key(value: str) -> bool:
    """Return whether a key is non-empty printable ASCII with no whitespace."""
    return bool(value) and all("!" <= character <= "~" for character in value)


def _api_keys_from_environment() -> tuple[str, str] | None:
    """Read the two Alpaca keys from the environment without echoing them.

    Returns ``None`` when either variable is unset. Raises
    `InvalidApiKeyError`, naming only the variable, when a set value could not
    be sent as a header verbatim.
    """
    key_id = os.environ.get(KEY_ID_VARIABLE)
    secret_key = os.environ.get(SECRET_KEY_VARIABLE)
    if key_id is None or secret_key is None:
        return None
    if not _usable_key(key_id):
        raise InvalidApiKeyError(KEY_ID_VARIABLE)
    if not _usable_key(secret_key):
        raise InvalidApiKeyError(SECRET_KEY_VARIABLE)
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
    the receipt can carry a real status, a real content type, a real host, and
    the digest of the real body instead of a constant.
    """
    if host not in PERMITTED_HOSTS:
        raise UnauthorizedHostError(
            f"Alpaca acquisition refuses to contact {host}: only "
            f"{', '.join(sorted(PERMITTED_HOSTS))} are authorized"
        )
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
        body_sha256=sha256(body).hexdigest(),
        body_byte_size=len(body),
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
        ALPACA_PAPER_TRADING_HOST,
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


def _failure_label(error: BaseException) -> str:
    """Name a failure by its type, plus the measured status of an HTTP error.

    Never the message: `http.client` builds exception messages out of header
    values and raw status lines, either of which can carry a key.
    """
    label = type(error).__name__
    if isinstance(error, urllib.error.HTTPError):
        label = f"{label} (HTTP {int(error.code)})"
    return label


def _load_offline_payloads(directory: Path) -> AlpacaNativePayloads:
    """Load exact retained response bytes already on disk."""
    return AlpacaNativePayloads(
        bars=(directory / BARS_FILE_NAME).read_bytes(),
        calendar=(directory / CALENDAR_FILE_NAME).read_bytes(),
        corporate_actions=(directory / ACTIONS_FILE_NAME).read_bytes(),
    )


def _replayed_origin(
    retained: RetainedNativeBytes, request: AlpacaIntakeRequest
) -> dict[str, AlpacaOriginObservation] | None:
    """Recover the measured origin of the replayed bytes, or report none.

    Only a record an online acquisition wrote beside these exact bytes counts.
    Unless every expected object has one, nothing is certified at all, and the
    receipt records every origin as unverified.
    """
    bound = load_retained_origin_observations(
        retained, window_start=request.request_start, window_end=request.request_end
    )
    unbound = tuple(key for key in _EXPECTED_OBJECT_KEYS if key not in bound)
    if not unbound:
        return bound
    print(
        f"no retained origin record binds {', '.join(unbound)} to the replayed "
        "bytes inside the declared acquisition window: this run performs no "
        "HTTP exchange, so the receipt will record an unverified origin and the "
        "bridge fails closed. Only a record written by an online acquisition "
        "of these exact bytes into this private root can be replayed."
    )
    return None


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

    measured: dict[str, AlpacaOriginObservation] | None = None
    if arguments.offline_bytes is not None:
        payloads = _load_offline_payloads(arguments.offline_bytes)
        print(f"loaded retained bytes from {arguments.offline_bytes}")
    else:
        try:
            keys = _api_keys_from_environment()
        except InvalidApiKeyError as error:
            print(f"refusing Alpaca acquisition: {error}")
            return 2
        if keys is None:
            print(
                "skipping Alpaca acquisition: "
                f"{KEY_ID_VARIABLE} and {SECRET_KEY_VARIABLE} are not both set. "
                "Re-run with --offline-bytes to use already-retained responses."
            )
            return 0
        if declaration is None or request is None:
            print(
                "skipping Alpaca acquisition: --declaration is required to "
                "bound the requested cohort and window."
            )
            return 0
        try:
            payloads, measured = _acquire_payloads(declaration, keys)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            http.client.HTTPException,
        ) as error:
            print(f"Alpaca acquisition failed: {_failure_label(error)}")
            return 1
        # Refuse a measurement the declaration cannot own, before anything is
        # retained on the strength of it.
        request = replace(request, origin_observations=measured)

    retained = retain_native_bytes(arguments.private_root, payloads)
    print(f"retained bars sha256 {retained.bars_hash}")
    print(f"retained calendar sha256 {retained.calendar_hash}")
    print(f"retained corporate actions sha256 {retained.corporate_actions_hash}")
    if measured is not None:
        for digest in retain_origin_observations(retained, measured):
            print(f"retained origin record sha256 {digest}")

    if request is None:
        print("no declaration supplied; stopping after private retention")
        return 0
    if measured is None:
        request = replace(
            request, origin_observations=_replayed_origin(retained, request)
        )

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
