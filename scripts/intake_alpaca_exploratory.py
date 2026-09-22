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

Typical offline use, which needs no keys at all:

    uv run python scripts/intake_alpaca_exploratory.py \
        --offline-bytes /private/alpaca/raw \
        --private-root /private/alpaca/store \
        --declaration /private/alpaca/cohort.json
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drift.adapters.alpaca_exploratory import (  # noqa: E402
    ALPACA_ACTIONS_ROUTE,
    ALPACA_BARS_ROUTE,
    ALPACA_CALENDAR_ROUTE,
    ALPACA_DATA_HOST,
    ALPACA_TRADING_HOST,
    AlpacaCohortMember,
    AlpacaIntakeRequest,
    AlpacaNativePayloads,
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

_TIMEOUT_SECONDS = 30


def _api_keys_from_environment() -> tuple[str, str] | None:
    """Read the two Alpaca keys from the environment without echoing them."""
    key_id = os.environ.get(KEY_ID_VARIABLE)
    secret_key = os.environ.get(SECRET_KEY_VARIABLE)
    if not key_id or not secret_key:
        return None
    return key_id, secret_key


def _fetch_bytes(
    host: str, route: str, parameters: Mapping[str, str], keys: tuple[str, str]
) -> bytes:
    """Fetch one exact response body over TLS, never logging the keys."""
    query = urllib.parse.urlencode(sorted(parameters.items()))
    url = f"https://{host}{route}?{query}"
    if not url.startswith("https://"):  # pragma: no cover - defensive
        raise ValueError("Alpaca acquisition requires TLS")
    appeal = urllib.request.Request(url, method="GET")
    appeal.add_header("APCA-API-KEY-ID", keys[0])
    appeal.add_header("APCA-API-SECRET-KEY", keys[1])
    appeal.add_header("Accept", "application/json")
    with urllib.request.urlopen(appeal, timeout=_TIMEOUT_SECONDS) as response:
        body = response.read()
    if not isinstance(body, bytes):  # pragma: no cover - defensive
        raise TypeError("Alpaca response body must be exact bytes")
    return body


def _acquire_payloads(
    declaration: Mapping[str, Any], keys: tuple[str, str]
) -> AlpacaNativePayloads:
    """Acquire the three declared endpoints for the bounded cohort."""
    symbols = ",".join(
        sorted(str(member["symbol"]) for member in declaration["members"])
    )
    start = str(declaration["start_date"])
    end = str(declaration["end_date"])
    bars = _fetch_bytes(
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
    calendar = _fetch_bytes(
        ALPACA_TRADING_HOST,
        ALPACA_CALENDAR_ROUTE,
        {"start": start, "end": end},
        keys,
    )
    actions = _fetch_bytes(
        ALPACA_DATA_HOST,
        ALPACA_ACTIONS_ROUTE,
        {"symbols": symbols, "start": start, "end": end, "types": "cash_dividend"},
        keys,
    )
    return AlpacaNativePayloads(bars=bars, calendar=calendar, corporate_actions=actions)


def _load_offline_payloads(directory: Path) -> AlpacaNativePayloads:
    """Load exact retained response bytes already on disk."""
    return AlpacaNativePayloads(
        bars=(directory / BARS_FILE_NAME).read_bytes(),
        calendar=(directory / CALENDAR_FILE_NAME).read_bytes(),
        corporate_actions=(directory / ACTIONS_FILE_NAME).read_bytes(),
    )


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

    if arguments.offline_bytes is not None:
        payloads = _load_offline_payloads(arguments.offline_bytes)
        print(f"loaded retained bytes from {arguments.offline_bytes}")
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
            payloads = _acquire_payloads(declaration, keys)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            print(f"Alpaca acquisition failed: {type(error).__name__}")
            return 1

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
