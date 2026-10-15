"""Integration tests for historical QQQ benchmark offline replay.

Verifies:
1. Offline mode never accesses credentials (environment variables absent).
2. Offline mode never calls provider endpoints (_fetch_bytes monkeypatched to error).
3. Missing retained source bytes fail closed (FileNotFoundError).
4. Source-hash mismatches fail closed (ValueError).
5. Missing or conflicting origin evidence fails closed (AlpacaBridgeIncompleteError).
6. Paginated/incomplete responses fail closed (next_page_token present).
7. Negative QQQ returns do not fail valid accounting (price drop bar fixture completes).
8. B0 cash behaves correctly (zero fills, 0.00 costs, 10000.00 ending NAV).
9. Unmodeled dividend crossings remain indeterminate.
10. Modeled dividends preserve entitlement and NAV rules.
11. Repeated offline evaluations preserve deterministic run identity and hashes.
12. Timezone evidence matches data used for calendar offsets.
"""

import io
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from drift.adapters.alpaca_exploratory import (
    ACTIONS_OBJECT_KEY,
    ALPACA_DATA_HOST,
    ALPACA_PAPER_TRADING_HOST,
    BARS_OBJECT_KEY,
    CALENDAR_OBJECT_KEY,
    AlpacaBridgeIncompleteError,
    AlpacaCohortMember,
    AlpacaNativePayloads,
    AlpacaOriginObservation,
    build_exploratory_dividends_from_alpaca,
    retain_native_bytes,
    retain_origin_observations,
)
from drift.domain.securities import ListingVenue
from drift.evaluator.engine import SessionEvaluatorEvidence
from drift.experiments.parallel_portfolios import PortfolioCohortHarness

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmark_qqq_historical import (
    PackagedTimezoneSource,
    _load_offline_payloads,
    _run_bounded_qqq_test,
    build_benchmark_request_manifest,
    main,
    resolve_timezone_evidence,
)

QQQ_SEC_ID = UUID("019b8240-0000-7000-8000-000000000002")
QQQ_LIST_ID = UUID("019b8240-0000-7000-8000-000000000012")


def _generate_synthetic_fixture(
    root: Path,
    dates: Sequence[date],
    *,
    price_start: float = 365.0,
    price_delta: float = 0.5,
    dividends: Sequence[dict[str, str]] | None = None,
    next_page_token_bars: str | None = None,
    next_page_token_actions: str | None = None,
    corrupt_bars_hash: bool = False,
    omit_origin_observations: bool = False,
    measured_at: datetime | None = None,
) -> tuple[Path, AlpacaNativePayloads]:
    """Helper to generate a self-contained offline fixture directory."""
    root.mkdir(parents=True, exist_ok=True)
    cal_entries = [
        {"date": d.isoformat(), "open": "09:30", "close": "16:00"} for d in dates
    ]
    bars_entries = []
    price = price_start
    for d in dates:
        bars_entries.append(
            {
                "t": f"{d.isoformat()}T04:00:00Z",
                "o": round(price, 2),
                "h": round(price + 2.0, 2),
                "l": round(price - 1.0, 2),
                "c": round(price + 1.0, 2),
                "v": 1000000,
                "n": 1000,
            }
        )
        price += price_delta

    bars_doc: dict[str, object] = {"bars": {"QQQ": bars_entries}}
    if next_page_token_bars is not None:
        bars_doc["next_page_token"] = next_page_token_bars

    actions_doc: dict[str, object] = {
        "corporate_actions": {"cash_dividends": list(dividends or [])}
    }
    if next_page_token_actions is not None:
        actions_doc["next_page_token"] = next_page_token_actions

    cal_bytes = json.dumps(cal_entries).encode("utf-8")
    bars_bytes = json.dumps(bars_doc).encode("utf-8")
    actions_bytes = json.dumps(actions_doc).encode("utf-8")

    (root / "calendar.json").write_bytes(cal_bytes)
    (root / "bars.json").write_bytes(bars_bytes)
    (root / "corporate-actions.json").write_bytes(actions_bytes)

    meta = {
        "request_start": (dates[0] - timedelta(days=1)).isoformat() + "T00:00:00+00:00",
        "request_end": (dates[-1] + timedelta(days=5)).isoformat() + "T00:00:00+00:00",
    }
    (root / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    payloads = AlpacaNativePayloads(
        bars=bars_bytes, calendar=cal_bytes, corporate_actions=actions_bytes
    )
    retained = retain_native_bytes(root, payloads)

    if corrupt_bars_hash:
        checksum_manifest = {
            "bars.json": "0" * 64,
            "calendar.json": sha256(cal_bytes).hexdigest(),
            "corporate-actions.json": sha256(actions_bytes).hexdigest(),
        }
        (root / "sha256.json").write_text(
            json.dumps(checksum_manifest), encoding="utf-8"
        )

    if not omit_origin_observations:
        obs_time = measured_at or (
            datetime.combine(dates[-1], datetime.min.time(), tzinfo=UTC)
            + timedelta(days=1)
        )
        req_manifest = build_benchmark_request_manifest(dates[0], dates[-1])
        bars_tgt = (
            req_manifest[BARS_OBJECT_KEY]["route"]
            + "?"
            + urlencode(sorted(req_manifest[BARS_OBJECT_KEY]["params"].items()))
        )
        cal_tgt = (
            req_manifest[CALENDAR_OBJECT_KEY]["route"]
            + "?"
            + urlencode(sorted(req_manifest[CALENDAR_OBJECT_KEY]["params"].items()))
        )
        act_tgt = (
            req_manifest[ACTIONS_OBJECT_KEY]["route"]
            + "?"
            + urlencode(sorted(req_manifest[ACTIONS_OBJECT_KEY]["params"].items()))
        )
        obs = {
            BARS_OBJECT_KEY: AlpacaOriginObservation(
                object_key=BARS_OBJECT_KEY,
                request_host=ALPACA_DATA_HOST,
                tls_endpoint_identity=ALPACA_DATA_HOST,
                http_status=200,
                content_type="application/json",
                observed_at=obs_time,
                body_sha256=sha256(bars_bytes).hexdigest(),
                body_byte_size=len(bars_bytes),
                request_target=bars_tgt,
            ),
            CALENDAR_OBJECT_KEY: AlpacaOriginObservation(
                object_key=CALENDAR_OBJECT_KEY,
                request_host=ALPACA_PAPER_TRADING_HOST,
                tls_endpoint_identity=ALPACA_PAPER_TRADING_HOST,
                http_status=200,
                content_type="application/json",
                observed_at=obs_time,
                body_sha256=sha256(cal_bytes).hexdigest(),
                body_byte_size=len(cal_bytes),
                request_target=cal_tgt,
            ),
            ACTIONS_OBJECT_KEY: AlpacaOriginObservation(
                object_key=ACTIONS_OBJECT_KEY,
                request_host=ALPACA_DATA_HOST,
                tls_endpoint_identity=ALPACA_DATA_HOST,
                http_status=200,
                content_type="application/json",
                observed_at=obs_time,
                body_sha256=sha256(actions_bytes).hexdigest(),
                body_byte_size=len(actions_bytes),
                request_target=act_tgt,
            ),
        }
        retain_origin_observations(retained, obs)

    return root, payloads


# ------------------------------------------------------------------------------
# Test 1 & 2: Offline mode never accesses credentials or network
# ------------------------------------------------------------------------------


def test_offline_mode_never_accesses_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline mode runs without env vars and never accesses credentials."""
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    import scripts.benchmark_qqq_historical as b_mod

    def _fail_on_keys(*args: object, **kwargs: object) -> tuple[str, str]:
        raise AssertionError("Credentials must never be accessed in offline mode")

    monkeypatch.setattr(b_mod, "_get_api_keys", _fail_on_keys)

    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)

    intake, payloads = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=tmp_path / "store",
        label="test_creds",
        mode="offline",
        offline_dir=fix_dir,
    )
    assert intake is not None
    assert len(intake.bundle.session_clock.sessions) == 3


def test_offline_mode_never_calls_provider_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline mode must never call _fetch_bytes or connect to any provider endpoint."""
    import scripts.benchmark_qqq_historical as b_mod

    def _fail_on_fetch(*args: object, **kwargs: object) -> object:
        raise AssertionError("Provider endpoint call attempted in offline mode")

    monkeypatch.setattr(b_mod, "_fetch_bytes", _fail_on_fetch)

    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)

    intake, _ = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=tmp_path / "store",
        label="test_network",
        mode="offline",
        offline_dir=fix_dir,
    )
    assert intake is not None


# ------------------------------------------------------------------------------
# Test 3: Missing retained source bytes fail closed
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_filename", ["bars.json", "calendar.json", "corporate-actions.json"]
)
def test_missing_retained_source_bytes_fail_closed(
    tmp_path: Path, missing_filename: str
) -> None:
    """Omitting any required retained source payload must raise FileNotFoundError."""
    dates = [date(2021, 8, 2), date(2021, 8, 3)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)
    (fix_dir / missing_filename).unlink()

    with pytest.raises(FileNotFoundError, match="Missing required offline payload"):
        _load_offline_payloads(fix_dir)


# ------------------------------------------------------------------------------
# Test 4: Source-hash mismatches fail closed
# ------------------------------------------------------------------------------


def test_source_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    """A payload whose hash contradicts sha256.json must raise ValueError."""
    dates = [date(2021, 8, 2), date(2021, 8, 3)]
    fix_dir, _ = _generate_synthetic_fixture(
        tmp_path / "offline_src", dates, corrupt_bars_hash=True
    )

    with pytest.raises(ValueError, match="SHA-256 digest mismatch"):
        _load_offline_payloads(fix_dir)


# ------------------------------------------------------------------------------
# Test 5: Missing or conflicting origin evidence fails closed
# ------------------------------------------------------------------------------


def test_missing_origin_evidence_fails_closed(tmp_path: Path) -> None:
    """When origin observations are absent, intake fails closed."""
    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(
        tmp_path / "offline_src", dates, omit_origin_observations=True
    )

    with pytest.raises(
        AlpacaBridgeIncompleteError,
        match="closed-world acquisition reconciliation did not pass",
    ):
        _run_bounded_qqq_test(
            start_date=dates[0],
            end_date=dates[-1],
            store_dir=tmp_path / "store",
            label="test_no_origin",
            mode="offline",
            offline_dir=fix_dir,
        )


def test_conflicting_origin_evidence_fails_closed(tmp_path: Path) -> None:
    """Conflicting origin request target parameters fail closed."""
    dates = [date(2021, 8, 2), date(2021, 8, 3)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)

    # Overwrite origin record with a conflicting request target
    origins_dir = fix_dir / "origins" / "sha256"
    for entry in origins_dir.iterdir():
        doc = json.loads(entry.read_text(encoding="utf-8"))
        if doc.get("object_key") == ACTIONS_OBJECT_KEY:
            doc["request_target"] = "/v1/corporate-actions?symbols=SPY"
            corrupt_bytes = json.dumps(doc).encode("utf-8")
            entry.unlink()
            (origins_dir / f"{sha256(corrupt_bytes).hexdigest()}.json").write_bytes(
                corrupt_bytes
            )
            break

    with pytest.raises(
        AlpacaBridgeIncompleteError,
        match="closed-world acquisition reconciliation did not pass",
    ):
        _run_bounded_qqq_test(
            start_date=dates[0],
            end_date=dates[-1],
            store_dir=tmp_path / "store",
            label="test_conflicting_origin",
            mode="offline",
            offline_dir=fix_dir,
        )


# ------------------------------------------------------------------------------
# Test 6: Paginated/incomplete responses fail closed
# ------------------------------------------------------------------------------


def test_paginated_bars_fail_closed(tmp_path: Path) -> None:
    """A bars response containing next_page_token must be rejected."""
    dates = [date(2021, 8, 2), date(2021, 8, 3)]
    fix_dir, _ = _generate_synthetic_fixture(
        tmp_path / "offline_src", dates, next_page_token_bars="token_123"
    )

    with pytest.raises(ValueError, match="Paginated bars response rejected"):
        _load_offline_payloads(fix_dir)


def test_paginated_corporate_actions_fail_closed(tmp_path: Path) -> None:
    """A corporate-actions response containing next_page_token must be rejected."""
    dates = [date(2021, 8, 2), date(2021, 8, 3)]
    fix_dir, _ = _generate_synthetic_fixture(
        tmp_path / "offline_src",
        dates,
        next_page_token_actions="token_actions_123",
    )

    with pytest.raises(
        ValueError, match="Paginated corporate-actions response rejected"
    ):
        _load_offline_payloads(fix_dir)


# ------------------------------------------------------------------------------
# Test 7: Negative QQQ returns do not fail valid accounting
# ------------------------------------------------------------------------------


def test_negative_returns_do_not_fail_valid_accounting(tmp_path: Path) -> None:
    """Price drops causing ending NAV < $10k must complete without error."""
    dates = [
        date(2021, 8, 2),
        date(2021, 8, 3),
        date(2021, 8, 4),
        date(2021, 8, 5),
    ]
    # Start at 365.0, price drop each session
    fix_dir, _ = _generate_synthetic_fixture(
        tmp_path / "offline_src", dates, price_start=365.0, price_delta=-80.0
    )

    intake, _ = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=tmp_path / "store",
        label="test_negative",
        mode="offline",
        offline_dir=fix_dir,
    )

    evidence = SessionEvaluatorEvidence(
        exploratory_cohort=intake.cohort,
        exploratory_listing_roles=intake.exploratory_listing_roles,
        exploratory_reconstruction_replay=intake.reconstruction_replay,
    )
    harness = PortfolioCohortHarness(
        cohort={
            "B1_QQQ_BH": (
                "b1_single_buy_and_hold",
                {"target_security_id": QQQ_SEC_ID},
            )
        },
        bundle=intake.bundle,
        admission=intake.admission,
        evidence=evidence,
    )
    results = harness.run(parallel=False)
    r = results[0]

    assert r.classification == "complete"
    assert r.ending_nav < Decimal("10000.00")
    assert r.ending_cash >= Decimal("0.00")
    assert r.fill_count > 0
    assert r.transaction_costs == Decimal("0.00")


# ------------------------------------------------------------------------------
# Test 8: B0 cash behaves correctly
# ------------------------------------------------------------------------------


def test_b0_cash_invariants(tmp_path: Path) -> None:
    """B0 Cash strategy must preserve 0 fills, 0 costs, and exactly $10,000.00 NAV."""
    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)

    intake, _ = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=tmp_path / "store",
        label="test_b0",
        mode="offline",
        offline_dir=fix_dir,
    )

    evidence = SessionEvaluatorEvidence(
        exploratory_cohort=intake.cohort,
        exploratory_listing_roles=intake.exploratory_listing_roles,
        exploratory_reconstruction_replay=intake.reconstruction_replay,
    )
    harness = PortfolioCohortHarness(
        cohort={"B0_Cash": "b0_cash"},
        bundle=intake.bundle,
        admission=intake.admission,
        evidence=evidence,
    )
    results = harness.run(parallel=False)
    r = results[0]

    assert r.classification == "complete"
    assert r.ending_nav == Decimal("10000.00")
    assert r.ending_cash == Decimal("10000.00")
    assert r.fill_count == 0
    assert r.transaction_costs == Decimal("0.00")
    assert r.settled_dividend_count == 0


# ------------------------------------------------------------------------------
# Test 9: Unmodeled dividend crossings remain indeterminate
# ------------------------------------------------------------------------------


def test_unmodeled_dividend_crossings_fail_closed(tmp_path: Path) -> None:
    """An unmodeled corporate action crossing halts B1 as indeterminate."""
    dates = [
        date(2021, 8, 2),
        date(2021, 8, 3),
        date(2021, 8, 4),
        date(2021, 8, 5),
    ]
    divs = [
        {
            "id": "div-1",
            "symbol": "QQQ",
            "rate": "0.50",
            "ex_date": "2021-08-04",
            "record_date": "2021-08-04",
            "payable_date": "2021-08-05",
        }
    ]
    fix_dir, _ = _generate_synthetic_fixture(
        tmp_path / "offline_src", dates, dividends=divs
    )

    intake, _ = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=tmp_path / "store",
        label="test_unmodeled",
        mode="offline",
        offline_dir=fix_dir,
    )

    evidence = SessionEvaluatorEvidence(
        exploratory_cohort=intake.cohort,
        exploratory_listing_roles=intake.exploratory_listing_roles,
        exploratory_reconstruction_replay=intake.reconstruction_replay,
        exploratory_dividends=None,
    )
    harness = PortfolioCohortHarness(
        cohort={
            "B1_QQQ_BH": (
                "b1_single_buy_and_hold",
                {"target_security_id": QQQ_SEC_ID},
            )
        },
        bundle=intake.bundle,
        admission=intake.admission,
        evidence=evidence,
    )
    results = harness.run(parallel=False)
    r = results[0]

    assert r.classification == "indeterminate"
    assert "corporate-action" in (r.halt_reason or "")


# ------------------------------------------------------------------------------
# Test 10: Modeled dividends preserve entitlement and NAV rules
# ------------------------------------------------------------------------------


def test_modeled_dividends_preserve_entitlement_and_nav(tmp_path: Path) -> None:
    """Modeled exploratory dividends entitle and settle correctly into ending cash."""
    dates = [
        date(2021, 8, 2),
        date(2021, 8, 3),
        date(2021, 8, 4),
        date(2021, 8, 5),
        date(2021, 8, 6),
    ]
    div_rate = Decimal("0.50")
    divs = [
        {
            "id": "div-test-1",
            "symbol": "QQQ",
            "rate": str(div_rate),
            "ex_date": "2021-08-05",
            "record_date": "2021-08-05",
            "payable_date": "2021-08-06",
        }
    ]
    fix_dir, payloads = _generate_synthetic_fixture(
        tmp_path / "offline_src", dates, dividends=divs
    )

    intake, _ = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=tmp_path / "store",
        label="test_modeled",
        mode="offline",
        offline_dir=fix_dir,
    )

    div_policy = build_exploratory_dividends_from_alpaca(
        payloads.corporate_actions,
        (
            AlpacaCohortMember(
                symbol="QQQ",
                security_id=QQQ_SEC_ID,
                listing_id=QQQ_LIST_ID,
                venue=ListingVenue.XNAS,
            ),
        ),
        response_sha256=intake.retained.corporate_actions_hash,
    )
    assert len(div_policy.dividends) == 1

    evidence = SessionEvaluatorEvidence(
        exploratory_cohort=intake.cohort,
        exploratory_listing_roles=intake.exploratory_listing_roles,
        exploratory_reconstruction_replay=intake.reconstruction_replay,
        exploratory_dividends=div_policy,
    )
    harness = PortfolioCohortHarness(
        cohort={
            "B1_QQQ_BH": (
                "b1_single_buy_and_hold",
                {"target_security_id": QQQ_SEC_ID},
            )
        },
        bundle=intake.bundle,
        admission=intake.admission,
        evidence=evidence,
    )
    results = harness.run(parallel=False)
    r = results[0]

    assert r.classification == "complete"
    assert r.settled_dividend_count == 1
    # 27 shares * 0.50 = 13.50 dividend cash added (118.00 + 13.50 = 131.50)
    assert r.ending_cash == Decimal("131.50")


# ------------------------------------------------------------------------------
# Test 11: Deterministic evaluation identity and trace hashes
# ------------------------------------------------------------------------------


def test_repeated_offline_evaluations_are_deterministic(tmp_path: Path) -> None:
    """Repeated runs over identical offline data produce identical hashes."""
    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)

    def _execute(run_idx: int) -> tuple[str, str]:
        intake, _ = _run_bounded_qqq_test(
            start_date=dates[0],
            end_date=dates[-1],
            store_dir=tmp_path / f"store_{run_idx}",
            label=f"test_det_{run_idx}",
            mode="offline",
            offline_dir=fix_dir,
        )
        evidence = SessionEvaluatorEvidence(
            exploratory_cohort=intake.cohort,
            exploratory_listing_roles=intake.exploratory_listing_roles,
            exploratory_reconstruction_replay=intake.reconstruction_replay,
        )
        harness = PortfolioCohortHarness(
            cohort={"B0_Cash": "b0_cash"},
            bundle=intake.bundle,
            admission=intake.admission,
            evidence=evidence,
        )
        results = harness.run(parallel=False)
        return intake.bundle.bundle_hash, results[0].result_hash

    b_hash_1, r_hash_1 = _execute(1)
    b_hash_2, r_hash_2 = _execute(2)

    assert b_hash_1 == b_hash_2
    assert r_hash_1 == r_hash_2


# ------------------------------------------------------------------------------
# Test 12: Timezone evidence matches data used for calendar offsets
# ------------------------------------------------------------------------------


def test_timezone_evidence_matches_calendar_offsets() -> None:
    """Timezone evidence bytes are bound and produce consistent calendar offsets."""
    tz_bytes, tzdb_release = resolve_timezone_evidence("America/New_York")
    ny = ZoneInfo.from_file(io.BytesIO(tz_bytes), key="America/New_York")

    # In August 2021, EDT is UTC-4 (-14400 seconds)
    d = date(2021, 8, 2)
    dt_open = datetime.combine(d, datetime.min.time(), tzinfo=ny).replace(
        hour=9, minute=30
    )
    offset = dt_open.utcoffset()
    assert offset is not None
    assert int(offset.total_seconds()) == -14400

    # Package source with invalid IANA version fails closed
    bad_pkg = PackagedTimezoneSource(iana_version="bad_ver", tzif_bytes=tz_bytes)
    with pytest.raises(RuntimeError, match="does not provide a valid IANA version"):
        resolve_timezone_evidence(package_source=bad_pkg)


# ------------------------------------------------------------------------------
# CLI Argument Parsing & Error Handling
# ------------------------------------------------------------------------------


def test_main_cli_offline_without_offline_bytes_fails() -> None:
    """Invoking offline mode without --offline-bytes exits with code 1."""
    code = main(["--mode", "offline"])
    assert code == 1


# ------------------------------------------------------------------------------
# Turnkey Mock Live-to-Offline Replay & Acquisition Metadata Regressions
# ------------------------------------------------------------------------------


def test_mock_acquisition_to_offline_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live acquisition creates a turnkey replay package reproducible offline."""
    import scripts.benchmark_qqq_historical as b_mod

    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]

    cal_entries = [
        {"date": d.isoformat(), "open": "09:30", "close": "16:00"} for d in dates
    ]
    bars_entries = []
    price = 365.0
    for d in dates:
        bars_entries.append(
            {
                "t": f"{d.isoformat()}T04:00:00Z",
                "o": round(price, 2),
                "h": round(price + 2.0, 2),
                "l": round(price - 1.0, 2),
                "c": round(price + 1.0, 2),
                "v": 1000000,
                "n": 1000,
            }
        )
        price += 0.5
    bars_doc = {"bars": {"QQQ": bars_entries}}
    actions_doc: dict[str, object] = {"corporate_actions": {"cash_dividends": []}}

    payload_map = {
        BARS_OBJECT_KEY: json.dumps(bars_doc).encode("utf-8"),
        CALENDAR_OBJECT_KEY: json.dumps(cal_entries).encode("utf-8"),
        ACTIONS_OBJECT_KEY: json.dumps(actions_doc).encode("utf-8"),
    }

    monkeypatch.setattr(b_mod, "_get_api_keys", lambda: ("mock_key", "mock_secret"))

    obs_time = datetime.now(UTC)

    def _mock_fetch(
        object_key: str,
        host: str,
        route: str,
        params: dict[str, str],
        keys: tuple[str, str],
    ) -> tuple[bytes, AlpacaOriginObservation]:
        body = payload_map[object_key]
        tgt = route + "?" + urlencode(sorted(params.items()))
        obs = AlpacaOriginObservation(
            object_key=object_key,
            request_host=host,
            tls_endpoint_identity=host,
            http_status=200,
            content_type="application/json",
            observed_at=obs_time,
            body_sha256=sha256(body).hexdigest(),
            body_byte_size=len(body),
            request_target=tgt,
        )
        return body, obs

    monkeypatch.setattr(b_mod, "_fetch_bytes", _mock_fetch)

    live_store = tmp_path / "live_store"
    live_intake, _ = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=live_store,
        label="test_mock_live",
        mode="live",
    )

    # Verify that live acquisition created the turnkey offline package:
    # 1. Materialized payload files
    assert (live_store / "bars.json").is_file()
    assert (live_store / "calendar.json").is_file()
    assert (live_store / "corporate-actions.json").is_file()
    # 2. Manifests
    assert (live_store / "metadata.json").is_file()
    assert (live_store / "sha256.json").is_file()
    # 3. Retained origin observations
    assert (live_store / "origins" / "sha256").is_dir()

    evidence_live = SessionEvaluatorEvidence(
        exploratory_cohort=live_intake.cohort,
        exploratory_listing_roles=live_intake.exploratory_listing_roles,
        exploratory_reconstruction_replay=live_intake.reconstruction_replay,
    )
    harness_live = PortfolioCohortHarness(
        cohort={"B0_Cash": "b0_cash"},
        bundle=live_intake.bundle,
        admission=live_intake.admission,
        evidence=evidence_live,
    )
    live_res = harness_live.run(parallel=False)[0]

    # Replay offline using ONLY the private root of the live acquisition
    def _fail_on_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("Network/provider call attempted during offline replay")

    monkeypatch.setattr(b_mod, "_fetch_bytes", _fail_on_network)

    def _fail_on_creds() -> tuple[str, str]:
        raise AssertionError("Credentials accessed during offline replay")

    monkeypatch.setattr(b_mod, "_get_api_keys", _fail_on_creds)

    offline_store = tmp_path / "offline_store"
    offline_intake, _ = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=offline_store,
        label="test_mock_offline_replay",
        mode="offline",
        offline_dir=live_store,
    )

    evidence_offline = SessionEvaluatorEvidence(
        exploratory_cohort=offline_intake.cohort,
        exploratory_listing_roles=offline_intake.exploratory_listing_roles,
        exploratory_reconstruction_replay=offline_intake.reconstruction_replay,
    )
    harness_offline = PortfolioCohortHarness(
        cohort={"B0_Cash": "b0_cash"},
        bundle=offline_intake.bundle,
        admission=offline_intake.admission,
        evidence=evidence_offline,
    )
    offline_res = harness_offline.run(parallel=False)[0]

    # Compare bundle, run identity, result and trace hashes
    assert live_intake.bundle.bundle_hash == offline_intake.bundle.bundle_hash
    assert live_res.run_identity_hash == offline_res.run_identity_hash
    assert live_res.result_hash == offline_res.result_hash
    assert live_res.trace_hash == offline_res.trace_hash


def test_missing_metadata_fails_closed(tmp_path: Path) -> None:
    """Offline replay fails closed when metadata.json is missing."""
    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)
    (fix_dir / "metadata.json").unlink()

    with pytest.raises(
        ValueError, match="Missing authoritative acquisition window metadata"
    ):
        _run_bounded_qqq_test(
            start_date=dates[0],
            end_date=dates[-1],
            store_dir=tmp_path / "store",
            label="test_missing_meta",
            mode="offline",
            offline_dir=fix_dir,
        )


def test_contradictory_metadata_fails_closed(tmp_path: Path) -> None:
    """Offline replay fails closed when request_end precedes request_start."""
    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)
    bad_meta = {
        "request_start": "2021-08-05T00:00:00+00:00",
        "request_end": "2021-08-01T00:00:00+00:00",
    }
    (fix_dir / "metadata.json").write_text(json.dumps(bad_meta), encoding="utf-8")

    with pytest.raises(ValueError, match="Contradictory acquisition window metadata"):
        _run_bounded_qqq_test(
            start_date=dates[0],
            end_date=dates[-1],
            store_dir=tmp_path / "store",
            label="test_contradictory_meta",
            mode="offline",
            offline_dir=fix_dir,
        )


def test_path_traversal_payload_fails_closed(tmp_path: Path) -> None:
    """Replay rejects symlinks or payload references resolving outside offline_dir."""
    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)

    # 1. Payload file symlinked to outside
    outside_file = tmp_path / "outside_bars.json"
    outside_file.write_bytes((fix_dir / "bars.json").read_bytes())
    (fix_dir / "bars.json").unlink()
    (fix_dir / "bars.json").symlink_to(outside_file)

    with pytest.raises(ValueError, match="Path traversal rejected"):
        _load_offline_payloads(fix_dir)

    # Restore bars.json
    (fix_dir / "bars.json").unlink()
    (fix_dir / "bars.json").write_bytes(outside_file.read_bytes())

    # 2. Metadata file symlinked outside
    outside_meta = tmp_path / "outside_meta.json"
    outside_meta.write_bytes((fix_dir / "metadata.json").read_bytes())
    (fix_dir / "metadata.json").unlink()
    (fix_dir / "metadata.json").symlink_to(outside_meta)

    with pytest.raises(ValueError, match="Path traversal rejected for metadata.json"):
        _load_offline_payloads(fix_dir)


def test_persisted_acquisition_metadata_replays_successfully(
    tmp_path: Path,
) -> None:
    """Exact persisted request_start/request_end bounds recover origin evidence."""
    dates = [date(2021, 8, 2), date(2021, 8, 3), date(2021, 8, 4)]
    fix_dir, _ = _generate_synthetic_fixture(tmp_path / "offline_src", dates)

    intake, payloads = _run_bounded_qqq_test(
        start_date=dates[0],
        end_date=dates[-1],
        store_dir=tmp_path / "store",
        label="test_persisted_meta",
        mode="offline",
        offline_dir=fix_dir,
    )
    assert intake is not None
    assert intake.bundle.bundle_hash is not None
