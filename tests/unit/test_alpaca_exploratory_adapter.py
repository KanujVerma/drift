"""Offline unit tests for the bounded Alpaca exploratory development bridge.

Every provider byte consumed here is a pinned literal declared in this module
and authenticated by a pinned SHA-256 digest. No test in this module opens a
socket, reads a `.env` file, or requires any credential. One test executes the
entire pipeline with `socket.socket` replaced by a raising stub, so the offline
claim is proven by execution rather than asserted by convention.
"""

import ast
import json
import os
import stat
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from struct import pack
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from drift.adapters.alpaca_exploratory import (
    _CORE_PACKAGES,
    _POLICY_DOCUMENTS,
    ACTIONS_OBJECT_KEY,
    ALPACA_ACTION_SOURCE_ID,
    ALPACA_BAR_SOURCE_ID,
    ALPACA_CALENDAR_SOURCE_ID,
    ALPACA_DATA_HOST,
    ALPACA_EXPLORATORY_LIMITATIONS,
    ALPACA_TRADING_HOST,
    BARS_OBJECT_KEY,
    CALENDAR_OBJECT_KEY,
    AlpacaBridgeIncompleteError,
    AlpacaBridgeProhibitedError,
    AlpacaCohortMember,
    AlpacaExploratoryIntakeResult,
    AlpacaIntakeRequest,
    AlpacaNativePayloads,
    AlpacaOriginObservation,
    AlpacaReconstructionLineage,
    AlpacaTimezoneEvidence,
    RetainedNativeBytes,
    _coverage_record,
    _exact_decimal,
    _policy_hash,
    _session_bounds,
    _verified,
    assert_core_isolation,
    build_alpaca_acquisition_evidence,
    build_bridge_admission,
    map_calendar_day,
    map_cash_dividend,
    map_native_bar,
    parse_alpaca_bars,
    parse_alpaca_calendar,
    parse_alpaca_cash_dividends,
    retain_native_bytes,
    run_alpaca_exploratory_intake,
)
from drift.domain.acquisition import AcquisitionCompleteness, OriginStatus
from drift.domain.economic_common import CashComponentV1
from drift.domain.economic_events import CorporateActionTermsVersionV1
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ALPACA_LIMITATION_TRUNCATED_CA,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.securities import ListingVenue
from drift.domain.sessions import (
    ScheduledSessionVersionV1,
    SessionCoverageVersionV1,
)
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    validate_exploratory_admission,
)
from drift.markets.observation_validation import M1dDatasetInput

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = REPO_ROOT / "src" / "drift" / "adapters" / "alpaca_exploratory.py"

NETWORK_MODULE_ROOTS = frozenset(
    {
        "boto3",
        "ftplib",
        "http",
        "httpx",
        "requests",
        "socket",
        "ssl",
        "urllib",
        "webbrowser",
    }
)

# --- pinned provider bytes -------------------------------------------------------

PINNED_BARS = (
    b'{"bars":{"AAPL":['
    b'{"c":191.25,"h":192.00,"l":189.75,"n":410000,"o":190.50,'
    b'"t":"2026-01-05T05:00:00Z","v":52000000},'
    b'{"c":192.80,"h":193.10,"l":190.90,"n":395000,"o":191.30,'
    b'"t":"2026-01-06T05:00:00Z","v":48500000},'
    b'{"c":193.60,"h":194.20,"l":192.10,"n":402000,"o":192.75,'
    b'"t":"2026-01-07T05:00:00Z","v":51200000},'
    b'{"c":194.40,"h":195.00,"l":193.00,"n":388000,"o":193.50,'
    b'"t":"2026-01-08T05:00:00Z","v":49750000},'
    b'{"c":195.90,"h":196.30,"l":193.85,"n":415000,"o":194.20,'
    b'"t":"2026-01-09T05:00:00Z","v":53100000}'
    b'],"MSFT":['
    b'{"c":412.75,"h":413.40,"l":409.20,"n":210000,"o":410.10,'
    b'"t":"2026-01-05T05:00:00Z","v":21000000},'
    b'{"c":414.25,"h":415.60,"l":411.80,"n":198000,"o":412.90,'
    b'"t":"2026-01-06T05:00:00Z","v":19800000},'
    b'{"c":416.10,"h":417.00,"l":413.90,"n":205000,"o":414.50,'
    b'"t":"2026-01-07T05:00:00Z","v":20450000},'
    b'{"c":417.90,"h":418.75,"l":415.50,"n":201000,"o":416.30,'
    b'"t":"2026-01-08T05:00:00Z","v":19950000},'
    b'{"c":419.75,"h":420.50,"l":417.25,"n":219000,"o":418.00,'
    b'"t":"2026-01-09T05:00:00Z","v":22100000}'
    b']},"next_page_token":null}'
)

PINNED_CALENDAR = (
    b'[{"close":"16:00","date":"2026-01-05","open":"09:30",'
    b'"settlement_date":"2026-01-07"},'
    b'{"close":"16:00","date":"2026-01-06","open":"09:30",'
    b'"settlement_date":"2026-01-08"},'
    b'{"close":"16:00","date":"2026-01-07","open":"09:30",'
    b'"settlement_date":"2026-01-09"},'
    b'{"close":"16:00","date":"2026-01-08","open":"09:30",'
    b'"settlement_date":"2026-01-12"},'
    b'{"close":"16:00","date":"2026-01-09","open":"09:30",'
    b'"settlement_date":"2026-01-13"}]'
)

PINNED_CORPORATE_ACTIONS = (
    b'{"corporate_actions":{"cash_dividends":[{'
    b'"corporate_action_id":"ca-aapl-20260107-cash-dividend",'
    b'"ex_date":"2026-01-07","payable_date":"2026-01-15",'
    b'"process_date":"2026-01-07","rate":"0.250","record_date":"2026-01-08",'
    b'"symbol":"AAPL"}]},"next_page_token":null}'
)

PINNED_BARS_SHA256 = "0a47b18c3f1213b4ba20c4a06a8794daaea7dca1b89814762e588b493d4dd542"
PINNED_CALENDAR_SHA256 = (
    "88fdfaeed9cf6b15dd4487ccda801c6b1b2379a73331f142c74595c20a28940e"
)
PINNED_CORPORATE_ACTIONS_SHA256 = (
    "d856871b2a9d879d7982fb381b4cdc25987abc0d9106e7f16b255fe4f8996148"
)
PINNED_TZIF_SHA256 = "787dbeac1a6eca77706fd0c52763596ca5805d5e12c7030fe2573904796012d6"

PRODUCER_SOURCE_BYTES = b'{"kind":"drift-alpaca-bridge-producer-source","version":"1"}'
PRODUCER_PACKAGE_BYTES = b'{"kind":"drift-alpaca-bridge-package","version":"1"}'
LOCKFILE_BYTES = b'{"kind":"drift-alpaca-bridge-lockfile","version":"1"}'

SESSION_DATES = (
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
    date(2026, 1, 9),
)
WINTER_OFFSET_SECONDS = -18_000

AAPL_ID = UUID("019b8240-0000-7000-8000-000000000101")
AAPL_LISTING = UUID("019b8240-0000-7000-8000-000000000102")
MSFT_ID = UUID("019b8240-0000-7000-8000-000000000201")
MSFT_LISTING = UUID("019b8240-0000-7000-8000-000000000202")

PLAN_FROZEN_AT = datetime(2026, 9, 20, 11, 0, tzinfo=UTC)
REQUEST_START = datetime(2026, 9, 20, 11, 30, tzinfo=UTC)
REQUEST_END = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
EVIDENCE_CUTOFF = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
#: The instant each pinned response finished being read. Pinned exactly like
#: the bytes are, and inside the declared acquisition window, because the
#: bridge refuses a window that does not contain its own measurements.
MEASURED_AT = datetime(2026, 9, 20, 11, 45, tzinfo=UTC)


#: Directories whose contents churn because of the test runner, the virtual
#: environment, or Git itself rather than because of the bridge. Everything
#: else in the working tree, including `.venv`, is scanned.
_UNSCANNED_REPOSITORY_DIRECTORIES = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)


def repository_paths() -> set[str]:
    """Return every path inside the working tree, so a new one is detectable."""
    found: set[str] = set()
    for directory, subdirectories, files in os.walk(REPO_ROOT):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in _UNSCANNED_REPOSITORY_DIRECTORIES
        ]
        for name in (*subdirectories, *files):
            found.add(Path(directory, name).relative_to(REPO_ROOT).as_posix())
    return found


def assert_private_bytes_are_locked_down(root: Path) -> None:
    """Assert every retained provider byte is readable only by its owner."""
    files = sorted(path for path in root.rglob("*") if path.is_file())
    directories = [root, *sorted(path for path in root.rglob("*") if path.is_dir())]
    assert files, f"nothing was retained under {root}"
    for path in files:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, (
            f"retained provider bytes are not owner-only: {path}"
        )
    for path in directories:
        assert stat.S_IMODE(path.stat().st_mode) == 0o700, (
            f"a private retention directory is not owner-only: {path}"
        )


def pinned_tzif_bytes() -> bytes:
    """Return a finite TZif v1 carrying only the two authored 2026 transitions."""
    transitions = (
        int(datetime(2026, 3, 8, 7, tzinfo=UTC).timestamp()),
        int(datetime(2026, 11, 1, 6, tzinfo=UTC).timestamp()),
    )
    abbreviations = b"EST\0EDT\0"
    header = (
        b"TZif\0"
        + (b"\0" * 15)
        + pack(">6l", 0, 0, 0, len(transitions), 2, len(abbreviations))
    )
    table = b"".join(pack(">l", value) for value in transitions)
    types = bytes((1, 0))
    local_types = pack(">lbb", -18_000, 0, 0) + pack(">lbb", -14_400, 1, 4)
    return header + table + types + local_types + abbreviations


def pinned_payloads() -> AlpacaNativePayloads:
    """Return the pinned native response bytes for the quiet January window."""
    return AlpacaNativePayloads(
        bars=PINNED_BARS,
        calendar=PINNED_CALENDAR,
        corporate_actions=PINNED_CORPORATE_ACTIONS,
    )


def pinned_cohort() -> tuple[AlpacaCohortMember, ...]:
    """Return the predeclared bounded exploratory cohort."""
    return (
        AlpacaCohortMember(
            symbol="AAPL",
            security_id=AAPL_ID,
            listing_id=AAPL_LISTING,
            venue=ListingVenue.XNAS,
        ),
        AlpacaCohortMember(
            symbol="MSFT",
            security_id=MSFT_ID,
            listing_id=MSFT_LISTING,
            venue=ListingVenue.XNAS,
        ),
    )


def pinned_boundary_offsets() -> dict[tuple[date, str], int]:
    """Return the externally attested UTC offsets for the pinned window."""
    return {
        (session_date, boundary): WINTER_OFFSET_SECONDS
        for session_date in SESSION_DATES
        for boundary in ("open", "close")
    }


def pinned_origin_observations() -> dict[str, AlpacaOriginObservation]:
    """Return the origin evidence measured when the pinned bytes were fetched.

    These are measurements the transport took, pinned beside the bytes they
    describe. The adapter opens no connection and so measures none of this
    itself; supplying nothing here is the honest "no HTTP exchange happened"
    case, and the bridge then refuses to certify the origin at all.
    """
    return {
        BARS_OBJECT_KEY: AlpacaOriginObservation(
            object_key=BARS_OBJECT_KEY,
            request_host=ALPACA_DATA_HOST,
            tls_endpoint_identity=ALPACA_DATA_HOST,
            http_status=200,
            content_type="application/json",
            observed_at=MEASURED_AT,
        ),
        CALENDAR_OBJECT_KEY: AlpacaOriginObservation(
            object_key=CALENDAR_OBJECT_KEY,
            # The calendar comes off the trading host, not the data host.
            request_host=ALPACA_TRADING_HOST,
            tls_endpoint_identity=ALPACA_TRADING_HOST,
            http_status=200,
            content_type="application/json",
            observed_at=MEASURED_AT,
        ),
        ACTIONS_OBJECT_KEY: AlpacaOriginObservation(
            object_key=ACTIONS_OBJECT_KEY,
            request_host=ALPACA_DATA_HOST,
            tls_endpoint_identity=ALPACA_DATA_HOST,
            http_status=200,
            content_type="application/json",
            observed_at=MEASURED_AT,
        ),
    }


def pinned_request(**overrides: Any) -> AlpacaIntakeRequest:
    """Return the pinned bounded intake declaration, with optional overrides."""
    request = AlpacaIntakeRequest(
        cohort_id="alpaca-quiet-window-2026-01",
        cohort_version="1",
        members=pinned_cohort(),
        mic="XNAS",
        start_date=SESSION_DATES[0],
        end_date=SESSION_DATES[-1],
        plan_frozen_at=PLAN_FROZEN_AT,
        request_start=REQUEST_START,
        request_end=REQUEST_END,
        evidence_vintage_cutoff=EVIDENCE_CUTOFF,
        timezone_evidence=AlpacaTimezoneEvidence(
            timezone_identifier="America/New_York",
            source_timezone_label="Eastern",
            tzif_bytes=pinned_tzif_bytes(),
            tzdb_release="pinned-fixture",
            reconstruction_observed_at=REQUEST_END,
        ),
        lineage=AlpacaReconstructionLineage(
            producer_source=PRODUCER_SOURCE_BYTES,
            producer_package=PRODUCER_PACKAGE_BYTES,
            lockfile=LOCKFILE_BYTES,
            python_identity="cpython-3.14",
        ),
        boundary_offsets=pinned_boundary_offsets(),
        origin_observations=pinned_origin_observations(),
    )
    return replace(request, **overrides) if overrides else request


def run_pinned_intake(root: Path, **overrides: Any) -> AlpacaExploratoryIntakeResult:
    """Run the full offline bridge pipeline over the pinned bytes."""
    return run_alpaca_exploratory_intake(
        request=pinned_request(**overrides),
        payloads=pinned_payloads(),
        private_root=root,
    )


@pytest.fixture(scope="module")
def intake(tmp_path_factory: pytest.TempPathFactory) -> AlpacaExploratoryIntakeResult:
    """Run the pipeline once for the many assertions that only read its output."""
    return run_pinned_intake(tmp_path_factory.mktemp("alpaca-private"))


# --- pinned fixture authenticity ---------------------------------------------------


def test_pinned_provider_bytes_match_their_declared_digests() -> None:
    assert sha256(PINNED_BARS).hexdigest() == PINNED_BARS_SHA256
    assert sha256(PINNED_CALENDAR).hexdigest() == PINNED_CALENDAR_SHA256
    assert (
        sha256(PINNED_CORPORATE_ACTIONS).hexdigest() == PINNED_CORPORATE_ACTIONS_SHA256
    )
    assert sha256(pinned_tzif_bytes()).hexdigest() == PINNED_TZIF_SHA256


# --- native parsing ------------------------------------------------------------------


def test_bars_parse_into_exact_decimals_without_any_binary_float() -> None:
    bars = parse_alpaca_bars(PINNED_BARS)

    assert len(bars) == 10
    first = bars[0]
    assert first.symbol == "AAPL"
    assert first.session_date == date(2026, 1, 5)
    assert first.close == Decimal("191.25")
    assert first.volume == Decimal("52000000")
    for bar in bars:
        for value in (bar.open, bar.high, bar.low, bar.close, bar.volume):
            assert isinstance(value, Decimal)
    # `isinstance(value, Decimal)` alone would still hold for a value routed
    # through a binary float, so the exact provider spelling is checked too:
    # 192.00 must survive as two decimal places rather than collapsing to the
    # nearest binary double and re-rendering as 192.0.
    assert str(first.high) == "192.00"
    assert str(first.volume) == "52000000"
    assert Decimal(str(first.close)) == Decimal("191.25")
    # The same literal routed through a binary float loses the trailing zero,
    # so this comparison fails the moment the parser stops being exact.
    assert str(Decimal(str(float("192.00")))) == "192.0" != str(first.high)


def test_bar_parsing_refuses_a_truncated_paginated_response() -> None:
    truncated = PINNED_BARS.replace(
        b'"next_page_token":null', b'"next_page_token":"cursor-2"'
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        parse_alpaca_bars(truncated)

    assert "bars response is paginated and incomplete" in str(error.value)


def test_corporate_action_parsing_refuses_a_truncated_paginated_response() -> None:
    truncated = PINNED_CORPORATE_ACTIONS.replace(
        b'"next_page_token":null', b'"next_page_token":"cursor-2"'
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        parse_alpaca_cash_dividends(truncated)

    assert "corporate actions response is paginated and incomplete" in str(error.value)


def test_calendar_parsing_rejects_a_repeated_session_date() -> None:
    document = json.loads(PINNED_CALENDAR)
    duplicated = json.dumps([*document, document[0]]).encode("utf-8")

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        parse_alpaca_calendar(duplicated)

    assert "calendar response repeats a session date" in str(error.value)


def test_calendar_parses_every_pinned_session() -> None:
    days = parse_alpaca_calendar(PINNED_CALENDAR)

    assert tuple(day.session_date for day in days) == SESSION_DATES
    assert {day.local_open for day in days} == {"09:30"}
    assert {day.local_close for day in days} == {"16:00"}


def test_cash_dividends_parse_into_canonical_exact_cash() -> None:
    dividends = parse_alpaca_cash_dividends(PINNED_CORPORATE_ACTIONS)

    assert len(dividends) == 1
    dividend = dividends[0]
    assert dividend.symbol == "AAPL"
    assert dividend.rate == Decimal("0.250")
    # The provider prints a trailing zero; M1c canonical cash does not carry one.
    assert dividend.rate_text == "0.25"
    assert dividend.ex_date == date(2026, 1, 7)


# --- step 1: private retention outside Git --------------------------------------------


def test_retention_writes_content_addressed_private_objects(tmp_path: Path) -> None:
    retained = retain_native_bytes(tmp_path / "private", pinned_payloads())

    stored = retained.root / "objects" / "sha256" / retained.bars_hash
    assert stored.read_bytes() == PINNED_BARS
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert stat.S_IMODE(stored.parent.stat().st_mode) == 0o700
    assert set(retained.artifacts) == {
        retained.bars_hash,
        retained.calendar_hash,
        retained.corporate_actions_hash,
    }


def test_retention_refuses_a_root_inside_a_git_working_tree(tmp_path: Path) -> None:
    root = tmp_path / "tree" / "private"
    (tmp_path / "tree").mkdir(parents=True)
    (tmp_path / "tree" / ".git").mkdir()

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        retain_native_bytes(root, pinned_payloads())

    assert "must be retained outside Git" in str(error.value)
    assert not root.exists()


def test_retention_refuses_a_relative_root() -> None:
    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        retain_native_bytes(Path("relative/private"), pinned_payloads())

    assert "private retention root must be absolute" in str(error.value)


# --- step 2: acquisition receipt ------------------------------------------------------


def test_acquisition_reconciles_the_closed_world_inventory(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    reconciliation = intake.acquisition.reconciliation

    assert reconciliation.result is AcquisitionCompleteness.PASS
    assert reconciliation.missing_keys == ()
    assert reconciliation.extra_keys == ()
    assert reconciliation.count_reconciled is True


def test_acquisition_receipt_binds_the_exact_retained_bytes(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    receipt = intake.acquisition.receipt
    graph_hashes = {item.content_hash for item in receipt.byte_graph.objects}

    # Recomputed from the pinned literals rather than from the object under
    # test: `byte_graph_hash == content_hash(byte_graph)` is enforced by the
    # model validator, so asserting it here could never fail.
    assert graph_hashes == {
        PINNED_BARS_SHA256,
        PINNED_CALENDAR_SHA256,
        PINNED_CORPORATE_ACTIONS_SHA256,
    }
    assert graph_hashes == {
        intake.retained.bars_hash,
        intake.retained.calendar_hash,
        intake.retained.corporate_actions_hash,
    }
    sizes = {item.content_hash: item.byte_size for item in receipt.byte_graph.objects}
    assert sizes == {
        PINNED_BARS_SHA256: len(PINNED_BARS),
        PINNED_CALENDAR_SHA256: len(PINNED_CALENDAR),
        PINNED_CORPORATE_ACTIONS_SHA256: len(PINNED_CORPORATE_ACTIONS),
    }
    assert receipt.collector_version == "1"


def test_unverified_origin_evidence_stops_the_pipeline(tmp_path: Path) -> None:
    plaintext = {
        key: replace(observation, tls_endpoint_identity=None)
        for key, observation in pinned_origin_observations().items()
    }

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_pinned_intake(tmp_path / "private", origin_observations=plaintext)

    assert "closed-world acquisition reconciliation did not pass" in str(error.value)


def test_a_replay_that_measured_nothing_asserts_no_http_exchange(
    tmp_path: Path,
) -> None:
    """No measurement means no claim, not a fabricated 200 over TLS."""
    request = pinned_request(origin_observations=None)
    retained = retain_native_bytes(tmp_path / "private", pinned_payloads())
    evidence = build_alpaca_acquisition_evidence(request, retained)

    for observed in evidence.receipt.observed_objects:
        origin = observed.origin_evidence
        assert origin.origin_status is OriginStatus.UNKNOWN
        assert origin.safe_response_metadata is None
        assert origin.tls_endpoint_identity is None
    assert evidence.reconciliation.result is not AcquisitionCompleteness.PASS
    assert any(
        "unverified origin evidence" in reason
        for reason in evidence.reconciliation.reasons
    )

    # And the pipeline refuses to build anything on top of it.
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_pinned_intake(tmp_path / "second", origin_observations=None)
    assert "closed-world acquisition reconciliation did not pass" in str(error.value)


def test_the_receipt_carries_the_measured_status_content_type_and_host(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """Every origin claim in the receipt traces to one measurement."""
    by_key = {
        str(item.matched_expected_key): item
        for item in intake.acquisition.receipt.observed_objects
    }
    measured = pinned_origin_observations()

    assert set(by_key) == set(measured)
    for key, observed in by_key.items():
        origin = observed.origin_evidence
        assert origin.origin_status is OriginStatus.VERIFIED
        assert origin.safe_response_metadata == {
            "content_type": measured[key].content_type,
            "http_status": str(measured[key].http_status),
            "observed_at": MEASURED_AT.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request_host": measured[key].request_host,
        }
        assert origin.tls_endpoint_identity == measured[key].tls_endpoint_identity


def test_the_calendar_origin_names_the_trading_host_not_the_data_host(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """The calendar is fetched from api.alpaca.markets and must say so."""
    by_key = {
        item.matched_expected_key: item
        for item in intake.acquisition.receipt.observed_objects
    }
    calendar = by_key[CALENDAR_OBJECT_KEY].origin_evidence
    bars = by_key[BARS_OBJECT_KEY].origin_evidence

    assert calendar.tls_endpoint_identity == ALPACA_TRADING_HOST
    assert bars.tls_endpoint_identity == ALPACA_DATA_HOST
    assert calendar.tls_endpoint_identity != bars.tls_endpoint_identity
    # The request identity names both authenticated hosts, not just one.
    host_field = intake.acquisition.receipt.request.authenticated_provider_host
    assert ALPACA_TRADING_HOST in host_field
    assert ALPACA_DATA_HOST in host_field


def test_origin_evidence_measured_against_the_wrong_host_is_refused() -> None:
    """A response from another origin cannot be filed under a declared key."""
    observations = pinned_origin_observations()
    observations[CALENDAR_OBJECT_KEY] = replace(
        observations[CALENDAR_OBJECT_KEY], request_host="evil.example.invalid"
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(origin_observations=observations)

    assert "declared to come from" in str(error.value)


def test_an_acquisition_window_that_excludes_its_own_measurement_is_refused() -> None:
    """acquired_at is anchored to measured instants, not merely declared."""
    observations = pinned_origin_observations()
    observations[BARS_OBJECT_KEY] = replace(
        observations[BARS_OBJECT_KEY],
        observed_at=datetime(2026, 9, 20, 13, 0, tzinfo=UTC),
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(origin_observations=observations)

    assert "outside the declared acquisition window" in str(error.value)


def test_a_non_200_response_is_not_a_complete_provider_response() -> None:
    observations = pinned_origin_observations()
    observations[ACTIONS_OBJECT_KEY] = replace(
        observations[ACTIONS_OBJECT_KEY], http_status=429
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(origin_observations=observations)

    assert "returned HTTP 429" in str(error.value)


def test_partial_origin_evidence_cannot_cover_only_some_endpoints() -> None:
    observations = pinned_origin_observations()
    del observations[ACTIONS_OBJECT_KEY]

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(origin_observations=observations)

    assert "must cover exactly the declared endpoints" in str(error.value)


def test_a_payload_filed_under_the_wrong_object_key_is_refused(
    tmp_path: Path,
) -> None:
    """matched_expected_key has to be earned by the bytes, not assigned."""
    swapped = AlpacaNativePayloads(
        bars=PINNED_CALENDAR,
        calendar=PINNED_BARS,
        corporate_actions=PINNED_CORPORATE_ACTIONS,
    )
    retained = retain_native_bytes(tmp_path / "private", swapped)

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        build_alpaca_acquisition_evidence(pinned_request(), retained)

    assert "do not have the shape" in str(error.value)
    # The correctly filed payloads still reconcile, so this is the shape check
    # firing and not an unrelated failure.
    correct = retain_native_bytes(tmp_path / "correct", pinned_payloads())
    assert (
        build_alpaca_acquisition_evidence(
            pinned_request(), correct
        ).reconciliation.result
        is AcquisitionCompleteness.PASS
    )


def test_the_expected_inventory_declares_each_endpoints_own_fields(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """A calendar row has no OHLCV and a dividend row has no OHLCV."""
    fields = {
        item.object_key: item.fields
        for item in intake.acquisition.expected_inventory.objects
    }

    assert fields[BARS_OBJECT_KEY] == ("close", "high", "low", "open", "volume")
    assert fields[CALENDAR_OBJECT_KEY] == ("close", "date", "open")
    assert fields[ACTIONS_OBJECT_KEY] == (
        "corporate_action_id",
        "ex_date",
        "payable_date",
        "rate",
        "record_date",
        "symbol",
    )
    assert len({fields[key] for key in fields}) == 3
    endpoints = {
        item.object_key: item.endpoint_or_file
        for item in intake.acquisition.expected_inventory.objects
    }
    assert endpoints[CALENDAR_OBJECT_KEY].startswith(f"https://{ALPACA_TRADING_HOST}")
    assert endpoints[BARS_OBJECT_KEY].startswith(f"https://{ALPACA_DATA_HOST}")


def test_two_endpoints_returning_identical_bodies_are_refused(
    tmp_path: Path,
) -> None:
    """Otherwise the receipt claims three objects over a two-object graph."""
    same = b'[{"close":"16:00","date":"2026-01-05","open":"09:30"}]'

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        retain_native_bytes(
            tmp_path / "private",
            AlpacaNativePayloads(
                bars=same, calendar=same, corporate_actions=PINNED_CORPORATE_ACTIONS
            ),
        )

    assert "byte-identical bodies" in str(error.value)


def test_a_retention_key_that_does_not_address_its_value_is_refused(
    tmp_path: Path,
) -> None:
    """A content-addressed store that never checks its own addresses is not one."""
    honest = retain_native_bytes(tmp_path / "private", pinned_payloads())
    forged = dict(honest.artifacts)
    forged[honest.bars_hash] = _verified(b"not the bars at all")

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        RetainedNativeBytes(
            root=honest.root,
            bars_hash=honest.bars_hash,
            calendar_hash=honest.calendar_hash,
            corporate_actions_hash=honest.corporate_actions_hash,
            artifacts=forged,
        )

    assert "filed under a digest it does not hash to" in str(error.value)


def test_receipt_verification_catches_a_forged_retention_mapping(
    tmp_path: Path,
) -> None:
    """M28: `build_alpaca_acquisition_evidence` is public and must be protected.

    `RetainedNativeBytes` now validates its own keys, so the mutant is built
    around that constructor to prove the *second*, independent defence:
    `verify_acquisition_receipt` inside `build_alpaca_acquisition_evidence`
    refuses a byte graph whose declared digest does not address its bytes.
    """
    honest = retain_native_bytes(tmp_path / "private", pinned_payloads())
    forged_artifacts = dict(honest.artifacts)
    # Right shape, wrong bytes: the endpoint-shape check passes, so the only
    # thing left standing between this and a minted receipt is the digest.
    forged_artifacts[honest.bars_hash] = _verified(
        b'{"bars":{"AAPL":[]},"next_page_token":null}'
    )
    forged = object.__new__(RetainedNativeBytes)
    for name, value in (
        ("root", honest.root),
        ("bars_hash", honest.bars_hash),
        ("calendar_hash", honest.calendar_hash),
        ("corporate_actions_hash", honest.corporate_actions_hash),
        ("artifacts", forged_artifacts),
    ):
        object.__setattr__(forged, name, value)

    with pytest.raises(ValueError) as error:
        build_alpaca_acquisition_evidence(pinned_request(), forged)

    assert "artifact hash mismatch" in str(error.value)


# --- steps 3 and 4: mapping and public validation -------------------------------------


def test_public_validators_accept_every_mapped_dataset(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    assert len(intake.validation_decisions) == 4
    for decision in intake.validation_decisions:
        assert decision.result.value == "pass"
        assert decision.findings == ()


def test_mapped_identities_cover_the_declared_cohort(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    assert {item.security_id for item in intake.securities} == {AAPL_ID, MSFT_ID}
    assert {item.listing_id for item in intake.listings} == {AAPL_LISTING, MSFT_LISTING}
    assert {item.venue for item in intake.listings} == {ListingVenue.XNAS}


def test_observation_contract_records_alpacas_unversioned_snapshot_semantics(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    contract = intake.observation_contract

    assert contract.source_id == ALPACA_BAR_SOURCE_ID
    assert contract.adjustment_basis == "unadjusted"
    # Alpaca overwrites derived bars in place and rejects pit=true.
    assert contract.revision_policy.kind == "current_snapshot_only"
    assert {item.adjustment_basis for item in contract.field_methods} == {"unadjusted"}


def test_every_policy_slot_addresses_its_own_contentful_document(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """A hash over an empty document attests nothing, so there are no stubs."""
    contract = intake.observation_contract
    population = contract.populations[0]
    receipt = intake.acquisition.receipt
    slots = {
        "ordering": contract.field_methods[0].ordering_policy_hash,
        "basis": contract.field_methods[0].basis_methodology_hash,
        "sale_condition": population.sale_condition_policy_hash,
        "correction": population.correction_cancellation_policy_hash,
        "population": population.evidence_hash,
        "volume_relationship": contract.volume_relationships[0].evidence_hash,
        "interval": contract.interval_policy.event_policy_hash,
        "revision": contract.revision_policy.policy_hash,
        "row_emission": contract.row_emission.omission_marker_policy_hash,
        "acquisition_methodology": receipt.native_layer_rule.methodology_hash,
        "license": receipt.license_evidence_hashes[0],
    }

    # Eleven slots, eleven documents, no reuse.
    assert len(set(slots.values())) == len(slots)
    assert set(slots.values()) <= {
        _policy_hash(policy_id) for policy_id in _POLICY_DOCUMENTS
    }
    assert receipt.methodology_evidence_hashes == (
        _policy_hash("alpaca-acquisition-methodology"),
    )

    # Every document says something: a subject, a statement, and an explicit
    # record of what is not established.
    for policy_id, document in _POLICY_DOCUMENTS.items():
        assert document["policy_id"] == policy_id
        assert len(str(document["subject"])) > 20
        assert len(str(document["statement"])) > 60
        assert document["not_established"]
        assert document["provider_publication"] in {
            "published",
            "partially_published",
            "not_published",
        }

    # And every one of them is resolvable as retained bytes, so the hashes
    # address something a reader can actually read.
    for policy_id in _POLICY_DOCUMENTS:
        digest = _policy_hash(policy_id)
        assert digest in intake.context.supporting_artifacts
        assert (
            sha256(intake.context.supporting_artifacts[digest].data).hexdigest()
            == digest
        )


def test_auction_dispositions_are_unknown_because_alpaca_publishes_none(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """These are load-bearing in session binding and were asserted as fact."""
    contract = intake.observation_contract
    population = contract.populations[0]

    assert population.opening_auction_rule == "unknown"
    assert population.closing_auction_rule == "unknown"
    assert contract.interval_policy.auction_event_inclusion == "unknown"
    assert population.odd_lot_rule == "unknown"
    # The rule document behind the interval policy says so in words too.
    interval_document = _POLICY_DOCUMENTS["alpaca-interval-endpoints"]
    assert interval_document["provider_publication"] == "not_published"
    assert "auction" in str(interval_document["statement"])


def test_the_license_reference_is_a_license_document_not_market_data(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """Pointing licence evidence at a bars response is not licence evidence."""
    retained_digests = {
        intake.retained.bars_hash,
        intake.retained.calendar_hash,
        intake.retained.corporate_actions_hash,
    }
    manifests = [
        *(item.manifest for item in intake.context.observation_datasets),
        *(item.manifest for item in intake.context.session_datasets),
        intake.economic_terms.manifest,
    ]

    for manifest in manifests:
        reference = manifest.license.terms_evidence_reference
        assert reference.content_hash not in retained_digests
        assert reference.content_hash == _policy_hash("alpaca-license-terms")
    document = _POLICY_DOCUMENTS["alpaca-license-terms"]
    assert "alpaca-basic-free-development-tier" in str(document["statement"])
    assert intake.acquisition.receipt.license_evidence_hashes == (
        _policy_hash("alpaca-license-terms"),
    )


def test_corporate_actions_map_as_terms_only(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    terms = intake.economic_terms.records

    assert len(terms) == 1
    record = terms[0]
    assert isinstance(record, CorporateActionTermsVersionV1)
    assert record.source_key.family == "terms"
    assert record.source_key.source_id == ALPACA_ACTION_SOURCE_ID
    assert record.payload is not None
    component = record.payload.components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "0.25"
    assert component.currency_code == "USD"
    # No occurred effect and no delivered settlement is ever minted, so the
    # evaluation bundle carries no economic outcome to mutate a book with.
    assert intake.bundle.economic_outcomes == ()


# --- step 5 and 6: selection, generation, reconstruction ------------------------------


def test_session_clock_is_scheduled_reconstruction_over_every_pinned_session(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    clock = intake.session_clock

    assert clock.mode == "scheduled_session_reconstruction"
    assert (
        tuple(item.session_key.local_date for item in clock.sessions) == SESSION_DATES
    )
    assert {item.authority for item in clock.sessions} == {"scheduled_reconstruction"}
    assert clock.sessions[0].opened_at == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert clock.sessions[0].closed_at == datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
    assert set(clock.acknowledged_limitations) == {
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
        ALPACA_LIMITATION_ABSENT_HALTS,
    }


def test_calendar_source_id_never_masquerades_as_the_bar_source(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    datasets: tuple[M1dDatasetInput[Any], ...] = (
        *intake.context.observation_datasets,
        *intake.context.session_datasets,
    )
    roles = {
        item.manifest.dataset_role.name: item.manifest.source.source_id
        for item in datasets
    }

    assert roles["source_observation"] == ALPACA_BAR_SOURCE_ID
    assert roles["scheduled_session"] == ALPACA_CALENDAR_SOURCE_ID
    assert roles["session_coverage"] == ALPACA_CALENDAR_SOURCE_ID
    assert "realized_session" not in roles


def test_reconstructions_project_exact_native_values_for_every_member_session(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    assert len(intake.reconstructions) == len(pinned_cohort()) * len(SESSION_DATES)
    by_key = {
        (item.security_id, item.session_key.local_date): item
        for item in intake.reconstructions
    }
    target = by_key[(AAPL_ID, date(2026, 1, 5))]
    values = {item.field_name: item.source_value for item in target.fields}

    assert values == {
        "open": Decimal("190.50"),
        "high": Decimal("192.00"),
        "low": Decimal("189.75"),
        "close": Decimal("191.25"),
        "volume": Decimal("52000000"),
    }
    assert target.currency == "USD"
    assert target.evidence_vintage_cutoff == EVIDENCE_CUTOFF
    assert set(target.acknowledged_limitations) == {
        ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
        ALPACA_LIMITATION_UNVERSIONED_BARS,
    }


def test_reconstructions_bind_the_declared_cohort_authorization(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    assert {item.cohort_hash for item in intake.reconstructions} == {
        intake.cohort.cohort_hash
    }
    assert intake.cohort.security_ids == tuple(sorted((AAPL_ID, MSFT_ID), key=str))
    assert {item.reconstruction_policy_hash for item in intake.reconstructions} == {
        intake.reconstruction_policy.policy_hash
    }


# --- step 7: bundle and admission ----------------------------------------------------


def test_bundle_carries_reconstructions_and_no_derived_views(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    bundle = intake.bundle

    # Alpaca publishes no realized session evidence, so M1d can bind no view.
    assert bundle.authentic_decision_views == ()
    assert bundle.authentic_accounting_views == ()
    assert len(bundle.exploratory_reconstructed_observations) == len(
        intake.reconstructions
    )
    assert bundle.has_exploratory_reconstructions is True
    # An exploratory bundle must never wear promotion snapshot identity.
    assert bundle.source_snapshot_hash is None


def test_admission_binds_all_six_canonical_alpaca_limitations(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    admission = intake.admission

    assert admission.lane == "exploratory"
    assert set(admission.acknowledged_limitations) == {
        ALPACA_LIMITATION_TRUNCATED_CA,
        ALPACA_LIMITATION_UNVERSIONED_BARS,
        ALPACA_LIMITATION_ABSENT_HALTS,
        ALPACA_LIMITATION_BOUNDED_COHORT,
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
        ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    }
    # Comparing the admission against the module constant the bridge built it
    # from is circular, so the independently spelled set above carries the
    # content and these two only pin shape: six distinct limitations, sorted.
    assert len(set(admission.acknowledged_limitations)) == 6
    assert list(admission.acknowledged_limitations) == sorted(
        admission.acknowledged_limitations
    )
    assert admission.acknowledged_limitations == ALPACA_EXPLORATORY_LIMITATIONS
    assert admission.input_bundle_hash == intake.bundle.bundle_hash
    validate_exploratory_admission(admission=admission, bundle=intake.bundle)


def test_admission_covers_every_limitation_the_bundle_evidence_requires(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    required = set(intake.bundle.required_limitations)

    assert required
    assert required <= set(intake.admission.acknowledged_limitations)


# --- adversarial: the four layering prohibitions --------------------------------------


def test_constructing_a_derived_view_from_alpaca_json_is_rejected(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    bar = parse_alpaca_bars(PINNED_BARS)[0]
    member = pinned_cohort()[0]
    bounds = (
        datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 5, 21, 0, tzinfo=UTC),
    )

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        map_native_bar(
            bar,
            member,
            pinned_request(),
            intake.observation_contract,
            bounds,
            intake.retained,
            target="derived_view",
        )

    assert "cannot construct a DerivedObservationViewV1" in str(error.value)
    # The same call without the prohibited target succeeds, so the rejection is
    # the guard and not an unrelated failure.
    record, _artifact = map_native_bar(
        bar,
        member,
        pinned_request(),
        intake.observation_contract,
        bounds,
        intake.retained,
    )
    assert record.session_date == date(2026, 1, 5)


def test_converting_a_scheduled_calendar_row_into_a_realized_session_is_rejected(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    day = parse_alpaca_calendar(PINNED_CALENDAR)[0]
    methodology_hash = intake.session_clock.sessions[0].session_hash
    sentinel_support: dict[str, Any] = {"sentinel": "untouched"}
    sentinel_evidence: dict[str, Any] = {"sentinel": "untouched"}
    support = dict(sentinel_support)
    evidence = dict(sentinel_evidence)

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        map_calendar_day(
            day,
            pinned_request(),
            methodology_hash,
            intake.retained,
            support,
            evidence,
            target="realized_session",
        )

    assert "cannot convert a scheduled calendar row" in str(error.value)
    assert "RealizedSessionVersionV1" in str(error.value)
    # A refused conversion must not have written anything into the context.
    # Comparing against a pre-seeded sentinel rather than against `{}` so the
    # assertion cannot pass merely because both sides are empty.
    assert support == sentinel_support
    assert evidence == sentinel_evidence

    # The permitted target does write into both, so "unchanged" above is a
    # real observation about the refusal and not about these arguments being
    # write-only in general.
    map_calendar_day(
        day,
        pinned_request(),
        methodology_hash,
        intake.retained,
        support,
        evidence,
    )
    assert support != sentinel_support
    assert evidence != sentinel_evidence


@pytest.mark.parametrize("target", ["effect", "settlement"])
def test_minting_a_corporate_action_effect_or_settlement_is_rejected(
    intake: AlpacaExploratoryIntakeResult, target: str
) -> None:
    dividend = parse_alpaca_cash_dividends(PINNED_CORPORATE_ACTIONS)[0]
    member = pinned_cohort()[0]

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        map_cash_dividend(
            dividend,
            member,
            pinned_request(),
            intake.retained,
            target=target,  # type: ignore[arg-type]
        )

    assert "maps corporate actions as terms only" in str(error.value)
    # The terms mapping itself still succeeds, so the rejection is the guard.
    terms = map_cash_dividend(dividend, member, pinned_request(), intake.retained)
    assert terms.source_key.family == "terms"


def test_emitting_a_promotion_admission_from_the_bridge_is_rejected(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        build_bridge_admission(bundle=intake.bundle, lane="promotion")

    assert "exploratory-only" in str(error.value)
    assert "PromotionEvaluationAdmissionV1" in str(error.value)
    # The exploratory lane still mints, so the rejection is the lane guard.
    assert build_bridge_admission(bundle=intake.bundle).lane == "exploratory"


def test_caller_supplied_derived_views_cannot_enter_the_bundle(
    intake: AlpacaExploratoryIntakeResult, tmp_path: Path
) -> None:
    forged = DerivedObservationViewV1.model_construct()

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=pinned_payloads(),
            private_root=tmp_path / "private",
            authentic_decision_views=(forged,),
        )

    assert "cannot place caller-supplied derived views" in str(error.value)

    with pytest.raises(AlpacaBridgeProhibitedError):
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=pinned_payloads(),
            private_root=tmp_path / "private",
            authentic_accounting_views=(forged,),
        )


# --- adversarial: architecture boundary -----------------------------------------------


def test_the_installed_drift_core_does_not_import_the_alpaca_bridge() -> None:
    assert_core_isolation()


def _synthetic_core(root: Path) -> Path:
    """Build a complete, clean synthetic Drift core rooted at ``root``."""
    for name in _CORE_PACKAGES:
        package = root / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "errors.py").write_text(
        "class DriftError(Exception):\n    pass\n", encoding="utf-8"
    )
    (root / "evaluator" / "engine.py").write_text(
        "from drift.domain.evaluator_bundles import EvaluationInputBundleV1\n",
        encoding="utf-8",
    )
    return root


def test_a_core_module_importing_the_bridge_is_detected(tmp_path: Path) -> None:
    root = _synthetic_core(tmp_path / "drift")
    (root / "evaluator" / "engine.py").write_text(
        "from drift.adapters.alpaca_exploratory import run_alpaca_exploratory_intake\n",
        encoding="utf-8",
    )

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        assert_core_isolation(root)

    assert "must not import drift.adapters" in str(error.value)
    assert "evaluator/engine.py" in str(error.value)


def test_a_clean_synthetic_core_passes_the_boundary_check(tmp_path: Path) -> None:
    assert_core_isolation(_synthetic_core(tmp_path / "drift"))


def test_a_top_level_core_module_importing_the_bridge_is_detected(
    tmp_path: Path,
) -> None:
    """errors.py is core, is imported nearly everywhere, and was never scanned."""
    root = _synthetic_core(tmp_path / "drift")
    (root / "errors.py").write_text(
        "from drift.adapters.alpaca_exploratory import retain_native_bytes\n",
        encoding="utf-8",
    )

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        assert_core_isolation(root)

    assert "errors.py" in str(error.value)


@pytest.mark.parametrize(
    "statement",
    [
        "from .. import adapters\n",
        "from . import adapters\n",
        "from drift import adapters\n",
        "from ..adapters import alpaca_exploratory\n",
        "from .adapters.alpaca_exploratory import retain_native_bytes\n",
    ],
)
def test_a_relative_or_aliased_adapter_import_is_detected(
    tmp_path: Path, statement: str
) -> None:
    """An ImportFrom can name the adapter package without naming it in `module`."""
    root = _synthetic_core(tmp_path / "drift")
    (root / "markets" / "session_binding.py").write_text(statement, encoding="utf-8")

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        assert_core_isolation(root)

    assert "markets/session_binding.py" in str(error.value)


def test_an_absent_core_package_fails_loudly_instead_of_being_skipped(
    tmp_path: Path,
) -> None:
    """A skipped directory is a skipped scan, so it is an error, not a pass."""
    root = _synthetic_core(tmp_path / "drift")
    for path in sorted((root / "markets").rglob("*")):
        path.unlink()
    (root / "markets").rmdir()

    with pytest.raises(AlpacaBridgeProhibitedError) as error:
        assert_core_isolation(root)

    assert "declared core packages are absent" in str(error.value)
    assert "markets" in str(error.value)


def test_the_boundary_scan_ignores_only_the_adapter_package_itself(
    tmp_path: Path,
) -> None:
    """The bridge is allowed to be an adapter; nothing else under drift is."""
    root = _synthetic_core(tmp_path / "drift")
    (root / "adapters").mkdir()
    (root / "adapters" / "alpaca_exploratory.py").write_text(
        "from drift.adapters import something\n", encoding="utf-8"
    )

    assert_core_isolation(root)


# --- adversarial: offline execution and secret hygiene --------------------------------


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_bytes(), str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_adapter_imports_no_network_module() -> None:
    assert not _imported_roots(ADAPTER_PATH) & NETWORK_MODULE_ROOTS


def test_the_adapter_never_reads_the_environment() -> None:
    tree = ast.parse(ADAPTER_PATH.read_bytes(), str(ADAPTER_PATH))
    reads: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}:
            reads.append(node.attr)

    assert reads == []


def test_the_full_pipeline_runs_with_every_socket_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the Alpaca bridge must never open a socket")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    result = run_pinned_intake(tmp_path / "private")

    assert result.bundle.bundle_hash == result.admission.input_bundle_hash
    assert not (REPO_ROOT / ".env").exists()


def test_no_provider_bytes_are_written_inside_the_repository(tmp_path: Path) -> None:
    """Run the real write path and prove the repository is untouched by it.

    Asserting that a ``tmp_path`` the test itself chose is not inside the
    repository proves nothing about where the adapter writes. This snapshots
    every path in the working tree, runs the actual retention and the whole
    pipeline over it, and snapshots again: any file or directory the bridge
    creates anywhere under the repository, at any path and under any name,
    shows up as a difference.
    """
    before = repository_paths()

    result = run_pinned_intake(tmp_path / "private")

    after = repository_paths()
    assert after - before == set(), (
        f"the bridge created paths inside the repository: {sorted(after - before)}"
    )
    assert before - after == set()
    assert_private_bytes_are_locked_down(result.retained.root)
    assert REPO_ROOT not in result.retained.root.parents
    assert os.path.commonpath([str(REPO_ROOT), str(result.retained.root)]) != str(
        REPO_ROOT
    )


def test_the_retention_scan_detects_a_write_into_the_repository(
    tmp_path: Path,
) -> None:
    """The scan above is only worth having if it can see a stray write.

    This writes one byte into the working tree by hand, exactly as an
    accidental cache copy inside ``retain_native_bytes`` would, and proves the
    comparison catches it. Without this the scan could silently degrade into
    comparing two empty sets.
    """
    before = repository_paths()
    stray = REPO_ROOT / "src" / "drift" / "_stray_provider_cache.json"
    assert not stray.exists()
    stray.write_bytes(PINNED_BARS)
    try:
        after = repository_paths()
        assert after - before == {stray.relative_to(REPO_ROOT).as_posix()}
    finally:
        stray.unlink()

    assert repository_paths() == before


def test_every_retained_private_object_is_owner_only(tmp_path: Path) -> None:
    retained = retain_native_bytes(tmp_path / "private", pinned_payloads())

    assert_private_bytes_are_locked_down(retained.root)
    # Including the root itself, which Path.mkdir(parents=True) used to leave
    # at the ambient umask while locking only the leaf directory.
    assert stat.S_IMODE(retained.root.stat().st_mode) == 0o700
    assert stat.S_IMODE((retained.root / "objects").stat().st_mode) == 0o700


# --- determinism ----------------------------------------------------------------------


def test_the_bridge_is_deterministic_across_two_independent_runs(
    tmp_path: Path,
) -> None:
    first = run_pinned_intake(tmp_path / "first")
    second = run_pinned_intake(tmp_path / "second")

    assert first.bundle.bundle_hash == second.bundle.bundle_hash
    assert first.admission.admission_hash == second.admission.admission_hash
    assert first.session_clock.clock_hash == second.session_clock.clock_hash
    assert tuple(item.reconstruction_hash for item in first.reconstructions) == tuple(
        item.reconstruction_hash for item in second.reconstructions
    )


def test_changing_one_native_price_changes_the_bundle_hash(tmp_path: Path) -> None:
    baseline = run_pinned_intake(tmp_path / "baseline")
    mutated = run_alpaca_exploratory_intake(
        request=pinned_request(),
        payloads=AlpacaNativePayloads(
            bars=PINNED_BARS.replace(b'"c":191.25', b'"c":191.26'),
            calendar=PINNED_CALENDAR,
            corporate_actions=PINNED_CORPORATE_ACTIONS,
        ),
        private_root=tmp_path / "mutated",
    )

    assert mutated.bundle.bundle_hash != baseline.bundle.bundle_hash
    assert mutated.admission.admission_hash != baseline.admission.admission_hash


# --- fail-closed intake ---------------------------------------------------------------


def test_a_missing_attested_offset_fails_closed(tmp_path: Path) -> None:
    offsets = pinned_boundary_offsets()
    del offsets[(date(2026, 1, 7), "close")]

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_pinned_intake(tmp_path / "private", boundary_offsets=offsets)

    assert "no attested UTC offset for 2026-01-07 close" in str(error.value)


def test_a_symbol_outside_the_declared_cohort_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_pinned_intake(tmp_path / "private", members=pinned_cohort()[:1])

    assert "outside the declared bounded cohort" in str(error.value)


def test_a_bar_without_a_scheduled_session_fails_closed(tmp_path: Path) -> None:
    extra = PINNED_BARS.replace(
        b'"t":"2026-01-09T05:00:00Z","v":53100000}',
        b'"t":"2026-01-09T05:00:00Z","v":53100000},'
        b'{"c":196.10,"h":197.00,"l":195.50,"n":400000,"o":195.95,'
        b'"t":"2026-01-12T05:00:00Z","v":50000000}',
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=AlpacaNativePayloads(
                bars=extra,
                calendar=PINNED_CALENDAR,
                corporate_actions=PINNED_CORPORATE_ACTIONS,
            ),
            private_root=tmp_path / "private",
        )

    assert "has no scheduled session" in str(error.value)


def test_an_evidence_cutoff_before_acquisition_is_rejected() -> None:
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(evidence_vintage_cutoff=datetime(2026, 1, 1, tzinfo=UTC))

    assert "retrospective evidence cutoff cannot precede acquisition" in str(
        error.value
    )


def test_a_cohort_listed_off_the_declared_calendar_venue_is_rejected() -> None:
    elsewhere = AlpacaCohortMember(
        symbol="AAPL",
        security_id=AAPL_ID,
        listing_id=AAPL_LISTING,
        venue=ListingVenue.XNYS,
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(members=(elsewhere,))

    assert "cannot use the XNAS calendar" in str(error.value)


def test_a_corrupt_retained_private_object_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "private"
    objects = root / "objects" / "sha256"
    objects.mkdir(parents=True)
    (objects / PINNED_BARS_SHA256).write_bytes(b"truncated")

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        retain_native_bytes(root, pinned_payloads())

    assert "does not match its content address" in str(error.value)


def test_a_bar_whose_session_had_not_closed_is_rejected(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    bar = parse_alpaca_bars(PINNED_BARS)[0]
    member = pinned_cohort()[0]
    after_acquisition = (
        datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
        datetime(2026, 9, 20, 21, 0, tzinfo=UTC),
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        map_native_bar(
            bar,
            member,
            pinned_request(),
            intake.observation_contract,
            after_acquisition,
            intake.retained,
        )

    assert "had not closed when the bytes were observed" in str(error.value)


def test_inverted_session_bounds_are_rejected(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    bar = parse_alpaca_bars(PINNED_BARS)[0]
    member = pinned_cohort()[0]
    inverted = (
        datetime(2026, 1, 5, 21, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        map_native_bar(
            bar,
            member,
            pinned_request(),
            intake.observation_contract,
            inverted,
            intake.retained,
        )

    assert "do not close after they open" in str(error.value)


def test_a_missing_bar_on_a_scheduled_session_fails_closed(tmp_path: Path) -> None:
    without_msft_wednesday = PINNED_BARS.replace(
        b'{"c":416.10,"h":417.00,"l":413.90,"n":205000,"o":414.50,'
        b'"t":"2026-01-07T05:00:00Z","v":20450000},',
        b"",
    )
    assert without_msft_wednesday != PINNED_BARS

    with pytest.raises(ValueError) as error:
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=AlpacaNativePayloads(
                bars=without_msft_wednesday,
                calendar=PINNED_CALENDAR,
                corporate_actions=PINNED_CORPORATE_ACTIONS,
            ),
            private_root=tmp_path / "private",
        )

    # A missing bar on a scheduled open is never read as a halt or a zero.
    assert "requires exactly one source observation" in str(error.value)


def test_a_duplicated_native_bar_is_rejected_by_the_public_validators(
    tmp_path: Path,
) -> None:
    duplicated_row = (
        b'{"c":191.25,"h":192.00,"l":189.75,"n":410000,"o":190.50,'
        b'"t":"2026-01-05T05:00:00Z","v":52000000},'
    )
    duplicated = PINNED_BARS.replace(duplicated_row, duplicated_row * 2, 1)
    assert duplicated != PINNED_BARS

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=AlpacaNativePayloads(
                bars=duplicated,
                calendar=PINNED_CALENDAR,
                corporate_actions=PINNED_CORPORATE_ACTIONS,
            ),
            private_root=tmp_path / "private",
        )

    assert "rejected the mapped source_observation dataset" in str(error.value)


def test_the_bridge_admission_refuses_a_bundle_wearing_promotion_identity(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    promotional = assemble_evaluation_input_bundle(
        evaluation_interval=intake.bundle.evaluation_interval,
        session_clock=intake.bundle.session_clock,
        exploratory_reconstructed_observations=(
            intake.bundle.exploratory_reconstructed_observations
        ),
        source_snapshot_hash="a" * 64,
    )

    with pytest.raises(ValueError) as error:
        build_bridge_admission(bundle=promotional)

    assert "cannot bind a promotion source snapshot" in str(error.value)


def test_a_binary_float_is_refused_even_if_one_reaches_the_mapper() -> None:
    # The parser never creates a float, but the numeric guard is a second
    # independent defence and is tested on its own rather than only in
    # composition with the parser.
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        _exact_decimal(191.25, "bar close")

    assert "got a binary float" in str(error.value)

    with pytest.raises(AlpacaBridgeIncompleteError) as boolean:
        _exact_decimal(True, "bar volume")

    assert "got a boolean" in str(boolean.value)


def test_a_bar_mapped_onto_the_wrong_cohort_member_is_rejected(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    apple_bar = parse_alpaca_bars(PINNED_BARS)[0]
    other_member = pinned_cohort()[1]
    bounds = (
        datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 5, 21, 0, tzinfo=UTC),
    )
    assert apple_bar.symbol != other_member.symbol

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        map_native_bar(
            apple_bar,
            other_member,
            pinned_request(),
            intake.observation_contract,
            bounds,
            intake.retained,
        )

    assert "bar symbol does not match its cohort member" in str(error.value)


def test_an_early_close_row_maps_to_an_early_close_session(tmp_path: Path) -> None:
    early = PINNED_CALENDAR.replace(
        b'{"close":"16:00","date":"2026-01-08","open":"09:30",',
        b'{"close":"13:00","date":"2026-01-08","open":"09:30",',
    )
    assert early != PINNED_CALENDAR

    result = run_alpaca_exploratory_intake(
        request=pinned_request(),
        payloads=AlpacaNativePayloads(
            bars=PINNED_BARS,
            calendar=early,
            corporate_actions=PINNED_CORPORATE_ACTIONS,
        ),
        private_root=tmp_path / "private",
    )

    scheduled = {
        item.session_key.local_date: item
        for dataset in result.context.session_datasets
        for item in dataset.records
        if isinstance(item, ScheduledSessionVersionV1)
    }
    assert scheduled[date(2026, 1, 8)].state == "early_close"
    assert scheduled[date(2026, 1, 7)].state == "regular"
    closed = {
        item.session_key.local_date: item.closed_at
        for item in result.session_clock.sessions
    }
    # The clock closes at the scheduled 13:00 local boundary, not at 16:00.
    assert closed[date(2026, 1, 8)] == datetime(2026, 1, 8, 18, 0, tzinfo=UTC)
    assert closed[date(2026, 1, 7)] == datetime(2026, 1, 7, 21, 0, tzinfo=UTC)


def test_a_late_close_row_is_not_filed_as_an_early_close(tmp_path: Path) -> None:
    late = PINNED_CALENDAR.replace(
        b'{"close":"16:00","date":"2026-01-08","open":"09:30",',
        b'{"close":"16:30","date":"2026-01-08","open":"09:30",',
    )
    # Without this the test silently becomes a no-op the moment the pinned
    # calendar is edited, exactly as its four sibling mutation tests guard.
    assert late != PINNED_CALENDAR

    result = run_alpaca_exploratory_intake(
        request=pinned_request(),
        payloads=AlpacaNativePayloads(
            bars=PINNED_BARS,
            calendar=late,
            corporate_actions=PINNED_CORPORATE_ACTIONS,
        ),
        private_root=tmp_path / "private",
    )

    scheduled = {
        item.session_key.local_date: item
        for dataset in result.context.session_datasets
        for item in dataset.records
        if isinstance(item, ScheduledSessionVersionV1)
    }
    assert scheduled[date(2026, 1, 8)].state == "regular"


# --- fail-closed intake: the declaration guards ---------------------------------------


def test_an_empty_cohort_is_rejected() -> None:
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(members=())

    assert "intake requires a nonempty cohort" in str(error.value)


def test_a_cohort_repeating_one_symbol_is_rejected() -> None:
    twin = AlpacaCohortMember(
        symbol="AAPL",
        security_id=MSFT_ID,
        listing_id=MSFT_LISTING,
        venue=ListingVenue.XNAS,
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(members=(pinned_cohort()[0], twin))

    assert "cohort symbols must be unique" in str(error.value)


def test_a_reversed_intake_window_is_rejected() -> None:
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(start_date=SESSION_DATES[-1], end_date=SESSION_DATES[0])

    assert "intake window cannot be reversed" in str(error.value)


def test_a_plan_frozen_after_the_request_started_is_rejected() -> None:
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(plan_frozen_at=REQUEST_START + timedelta(seconds=1))

    assert "must be frozen before the request starts" in str(error.value)


def test_a_request_ending_before_it_started_is_rejected() -> None:
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        pinned_request(
            request_end=REQUEST_START - timedelta(seconds=1),
            origin_observations=None,
        )

    assert "request end cannot precede its start" in str(error.value)


# --- fail-closed intake: the mapping and generation guards ----------------------------


def test_a_negative_cash_amount_is_refused(tmp_path: Path) -> None:
    negative = PINNED_CORPORATE_ACTIONS.replace(b'"rate":"0.250"', b'"rate":"-0.250"')
    assert negative != PINNED_CORPORATE_ACTIONS

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=AlpacaNativePayloads(
                bars=PINNED_BARS,
                calendar=PINNED_CALENDAR,
                corporate_actions=negative,
            ),
            private_root=tmp_path / "private",
        )

    assert "cash amounts cannot be negative" in str(error.value)


def test_a_window_that_returned_no_bars_fails_closed(tmp_path: Path) -> None:
    empty = b'{"bars":{},"next_page_token":null}'

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=AlpacaNativePayloads(
                bars=empty,
                calendar=PINNED_CALENDAR,
                corporate_actions=PINNED_CORPORATE_ACTIONS,
            ),
            private_root=tmp_path / "private",
        )

    assert "the bounded window returned no bars" in str(error.value)


def test_a_session_closing_before_it_opens_fails_closed(tmp_path: Path) -> None:
    inverted = PINNED_CALENDAR.replace(
        b'{"close":"16:00","date":"2026-01-08","open":"09:30",',
        b'{"close":"08:00","date":"2026-01-08","open":"09:30",',
    )
    assert inverted != PINNED_CALENDAR

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_alpaca_exploratory_intake(
            request=pinned_request(),
            payloads=AlpacaNativePayloads(
                bars=PINNED_BARS,
                calendar=inverted,
                corporate_actions=PINNED_CORPORATE_ACTIONS,
            ),
            private_root=tmp_path / "private",
        )

    assert "does not close after it opens" in str(error.value)


def test_a_scheduled_row_stripped_of_its_attested_offset_fails_closed(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """The second offset guard, on the generation side rather than the map side.

    `map_calendar_day` refuses to build a row without an attested offset, so
    this one is reached only by a row that lost its offsets afterwards. It is
    exercised directly rather than left unprotected.
    """
    row = next(
        item
        for dataset in intake.context.session_datasets
        for item in dataset.records
        if isinstance(item, ScheduledSessionVersionV1)
    )
    stripped = SimpleNamespace(
        session_key=row.session_key,
        local_open=row.local_open,
        local_close=row.local_close,
        historical_boundary_offsets=(),
    )

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        _session_bounds((cast(Any, stripped),), pinned_request())

    assert "lacks an attested UTC offset" in str(error.value)
    # The untouched row still resolves, so the refusal is the guard.
    assert _session_bounds((row,), pinned_request())


def test_a_calendar_snapshot_with_no_session_rows_fails_closed(
    intake: AlpacaExploratoryIntakeResult,
) -> None:
    """Reached directly: the pipeline trips an earlier guard on an empty calendar."""
    empty = SimpleNamespace(records=())

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        _coverage_record(
            cast(Any, empty),
            pinned_request(),
            "0" * 64,
            intake.retained,
        )

    assert "calendar snapshot carries no session rows" in str(error.value)


def _consecutive_payloads(days: tuple[date, ...]) -> AlpacaNativePayloads:
    """Build a closed response set covering exactly the given session dates."""
    calendar = [
        {
            "close": "16:00",
            "date": day.isoformat(),
            "open": "09:30",
            "settlement_date": day.isoformat(),
        }
        for day in days
    ]
    bars = {
        symbol: [
            {
                "c": "191.25",
                "h": "192.00",
                "l": "189.75",
                "n": 410000,
                "o": "190.50",
                "t": f"{day.isoformat()}T05:00:00Z",
                "v": "52000000",
            }
            for day in days
        ]
        for symbol in ("AAPL", "MSFT")
    }
    return AlpacaNativePayloads(
        bars=json.dumps({"bars": bars, "next_page_token": None}).encode("utf-8"),
        calendar=json.dumps(calendar).encode("utf-8"),
        corporate_actions=PINNED_CORPORATE_ACTIONS,
    )


def _window_request(days: tuple[date, ...]) -> AlpacaIntakeRequest:
    return pinned_request(
        start_date=days[0],
        end_date=days[-1],
        boundary_offsets={
            (day, boundary): WINTER_OFFSET_SECONDS
            for day in days
            for boundary in ("open", "close")
        },
    )


def test_a_window_spanning_a_weekend_gap_fails_closed_by_name(
    tmp_path: Path,
) -> None:
    """The structural ceiling, pinned: one unbroken run of calendar days.

    `expected_complete` with `expected_daily_cardinality=1` means, upstream,
    that every calendar day between the first and last session carries exactly
    one session. `session_validation` applies no exception-date skip and
    `generate_schedule` refuses any status other than `expected_complete`, so
    neither populating `exception_dates` nor downgrading the status widens
    this. A two-week window therefore cannot be acquired, and the limit is
    stated here rather than left to be discovered as an opaque
    `session_coverage_daily_cardinality_mismatch`.
    """
    fortnight = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16))

    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        run_alpaca_exploratory_intake(
            request=_window_request(fortnight),
            payloads=_consecutive_payloads(fortnight),
            private_root=tmp_path / "fortnight",
        )

    message = str(error.value)
    assert "one unbroken run of consecutive calendar days" in message
    assert "2026-01-10" in message and "2026-01-11" in message


def test_one_unbroken_run_of_sessions_is_accepted(tmp_path: Path) -> None:
    """The other half of the ceiling: inside the limit the bridge still works.

    Without this the refusal above could be satisfied by a bridge that refuses
    every window.
    """
    week = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9))
    result = run_alpaca_exploratory_intake(
        request=_window_request(week),
        payloads=_consecutive_payloads(week),
        private_root=tmp_path / "week",
    )

    assert len(result.session_clock.sessions) == len(week)
    coverage = next(
        item
        for dataset in result.context.session_datasets
        for item in dataset.records
        if isinstance(item, SessionCoverageVersionV1)
    )
    assert coverage.status == "expected_complete"
    assert coverage.expected_daily_cardinality == 1
    assert coverage.exception_dates == ()


def test_a_cohort_repeating_one_security_or_listing_is_rejected() -> None:
    repeated_security = AlpacaCohortMember(
        symbol="MSFT",
        security_id=AAPL_ID,
        listing_id=MSFT_LISTING,
        venue=ListingVenue.XNAS,
    )
    with pytest.raises(AlpacaBridgeIncompleteError) as security_error:
        pinned_request(members=(pinned_cohort()[0], repeated_security))
    assert "cohort securities must be unique" in str(security_error.value)

    repeated_listing = AlpacaCohortMember(
        symbol="MSFT",
        security_id=MSFT_ID,
        listing_id=AAPL_LISTING,
        venue=ListingVenue.XNAS,
    )
    with pytest.raises(AlpacaBridgeIncompleteError) as listing_error:
        pinned_request(members=(pinned_cohort()[0], repeated_listing))
    assert "cohort listings must be unique" in str(listing_error.value)
