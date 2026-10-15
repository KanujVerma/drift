"""Bounded historical benchmark smoke tests for QQQ (XNAS).

Tests:
1. Action-free interval (August 2021): B0 (Cash) and B1 (QQQ Buy-and-Hold).
2. Dividend-crossing interval (August-November 2021):
   - Fail-closed run without modeled dividends: verify INDETERMINATE.
   - Exploratory run with modeled dividends: verify entitlement and NAV.
"""

import argparse
import hashlib
import io
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from drift.adapters.alpaca_exploratory import (
    ACTIONS_OBJECT_KEY,
    ALPACA_ACTION_TYPES,
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
    AlpacaReconstructionLineage,
    AlpacaTimezoneEvidence,
    build_exploratory_dividends_from_alpaca,
    load_retained_origin_observations,
    retain_native_bytes,
    run_alpaca_exploratory_intake,
)
from drift.domain.securities import ListingVenue
from drift.evaluator.engine import SessionEvaluatorEvidence
from drift.experiments.parallel_portfolios import PortfolioCohortHarness

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.intake_alpaca_exploratory import (
    _api_keys_from_environment,
    _fetch_bytes,
)

BARS_FILE_NAME = "bars.json"
CALENDAR_FILE_NAME = "calendar.json"
ACTIONS_FILE_NAME = "corporate-actions.json"


def _get_api_keys() -> tuple[str, str]:
    keys = _api_keys_from_environment()
    if keys is None:
        print("ERROR: Alpaca credentials missing from environment")
        sys.exit(1)
    return keys


@dataclass(frozen=True, slots=True)
class PackagedTimezoneSource:
    """Verifiable timezone package metadata bound to its enclosed TZIF bytes."""

    iana_version: str
    tzif_bytes: bytes


def _detect_os_tzdb_release(tzif_path: Path) -> str:
    """Detect the IANA release label bound to an OS timezone file, or fail closed."""
    resolved = tzif_path.resolve()
    for part in resolved.parts:
        m = re.match(r"^(\d{4}[a-z])(?:\.|$)", part)
        if m:
            return m.group(1)

    for parent in (resolved.parent, resolved.parent.parent):
        zi = parent / "tzdata.zi"
        if zi.is_file():
            first_line = zi.read_text(encoding="utf-8", errors="replace").split(
                "\n", 1
            )[0]
            m = re.search(r"version\s+(\d{4}[a-z])", first_line)
            if m:
                return m.group(1)

    raise RuntimeError(
        f"Cannot verify tzdb release bound to host timezone at {tzif_path} "
        f"(resolved: {resolved}). Failing closed rather than assuming "
        "an unverified release."
    )


def resolve_timezone_evidence(
    timezone_identifier: str = "America/New_York",
    *,
    zoneinfo_dir: Path | None = None,
    package_source: PackagedTimezoneSource | None = None,
) -> tuple[bytes, str]:
    """Resolve verifiable TZIF bytes and the release label strictly bound to them.

    When ``package_source`` is provided, both bytes and release are taken directly
    from that verified packaged source. Otherwise, reads from the OS zoneinfo tree
    and binds to metadata verified within that exact file tree.

    Never borrows a package release label for separately read OS file bytes,
    and fails closed if the selected source cannot be verifiably resolved.
    """
    if package_source is not None:
        release = package_source.iana_version
        if not re.match(r"^\d{4}[a-z]$", release):
            raise RuntimeError(
                f"Package source does not provide a valid IANA version: {release!r}"
            )
        return package_source.tzif_bytes, release

    base_dir = zoneinfo_dir or Path("/usr/share/zoneinfo")
    tzif_path = base_dir / timezone_identifier
    if not tzif_path.is_file():
        raise FileNotFoundError(
            f"Required timezone evidence file not found at {tzif_path}. "
            "Fail-closed: cannot construct authentic timezone evidence."
        )
    tz_bytes = tzif_path.read_bytes()
    tzdb_release = _detect_os_tzdb_release(tzif_path)
    return tz_bytes, tzdb_release


def build_benchmark_request_manifest(
    start_date: date, end_date: date
) -> dict[str, dict[str, Any]]:
    """Build the exact provider GET request manifest from implemented parameters."""
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()
    return {
        ACTIONS_OBJECT_KEY: {
            "host": ALPACA_DATA_HOST,
            "route": ALPACA_ACTIONS_ROUTE,
            "params": {
                "end": end_str,
                "start": start_str,
                "symbols": "QQQ",
                "types": ",".join(ALPACA_ACTION_TYPES),
            },
        },
        CALENDAR_OBJECT_KEY: {
            "host": ALPACA_PAPER_TRADING_HOST,
            "route": ALPACA_CALENDAR_ROUTE,
            "params": {
                "end": end_str,
                "start": start_str,
            },
        },
        BARS_OBJECT_KEY: {
            "host": ALPACA_DATA_HOST,
            "route": ALPACA_BARS_ROUTE,
            "params": {
                "adjustment": "raw",
                "end": end_str,
                "feed": "sip",
                "limit": "10000",
                "start": start_str,
                "symbols": "QQQ",
                "timeframe": "1Day",
            },
        },
    }


def _find_window_offline_dir(base_dir: Path, window_name: str) -> Path:
    """Resolve the directory holding offline payloads for a named benchmark window."""
    sub = base_dir / window_name
    if sub.is_dir():
        return sub
    if (base_dir / BARS_FILE_NAME).is_file():
        return base_dir
    raise FileNotFoundError(
        f"Offline payload directory for {window_name} not found at {sub} or {base_dir}"
    )


def _load_offline_payloads(
    offline_dir: Path,
) -> tuple[AlpacaNativePayloads, dict[str, Any] | None]:
    """Load and verify retained payload files from an offline directory."""
    if not offline_dir.is_dir():
        raise FileNotFoundError(f"Offline payload directory not found: {offline_dir}")

    bars_path = offline_dir / BARS_FILE_NAME
    cal_path = offline_dir / CALENDAR_FILE_NAME
    actions_path = offline_dir / ACTIONS_FILE_NAME

    if not bars_path.is_file():
        raise FileNotFoundError(f"Missing required offline payload: {bars_path}")
    if not cal_path.is_file():
        raise FileNotFoundError(f"Missing required offline payload: {cal_path}")
    if not actions_path.is_file():
        raise FileNotFoundError(f"Missing required offline payload: {actions_path}")

    bars_body = bars_path.read_bytes()
    cal_body = cal_path.read_bytes()
    actions_body = actions_path.read_bytes()

    # Verify SHA-256 digests against manifest if present
    for manifest_name in ("sha256.json", "manifest.json", "checksums.json"):
        manifest_path = offline_dir / manifest_name
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict):
                for fname, expected_hash in manifest.items():
                    target_file = offline_dir / fname
                    if target_file.is_file():
                        actual_hash = hashlib.sha256(
                            target_file.read_bytes()
                        ).hexdigest()
                        if actual_hash != expected_hash:
                            raise ValueError(
                                f"SHA-256 digest mismatch for {fname}: "
                                f"expected {expected_hash}, got {actual_hash}"
                            )

    # Refuse incomplete/paginated evidence
    bars_doc = json.loads(bars_body)
    if isinstance(bars_doc, dict) and bars_doc.get("next_page_token") is not None:
        raise ValueError(
            "Paginated bars response rejected: "
            f"next_page_token={bars_doc.get('next_page_token')!r}"
        )
    actions_doc = json.loads(actions_body)
    if isinstance(actions_doc, dict) and actions_doc.get("next_page_token") is not None:
        raise ValueError(
            "Paginated corporate-actions response rejected: "
            f"next_page_token={actions_doc.get('next_page_token')!r}"
        )

    metadata: dict[str, Any] | None = None
    meta_path = offline_dir / "metadata.json"
    if meta_path.is_file():
        meta_doc = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(meta_doc, dict):
            metadata = meta_doc

    payloads = AlpacaNativePayloads(
        bars=bars_body, calendar=cal_body, corporate_actions=actions_body
    )
    return payloads, metadata


def _run_bounded_qqq_test(
    start_date: date,
    end_date: date,
    store_dir: Path,
    label: str,
    *,
    mode: str = "offline",
    offline_dir: Path | None = None,
) -> tuple[Any, AlpacaNativePayloads]:
    store_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_benchmark_request_manifest(start_date, end_date)

    if mode == "live":
        keys = _get_api_keys()
        now_utc = datetime.now(UTC).replace(microsecond=0)
        t_start = now_utc - timedelta(minutes=5)
        t_end = now_utc + timedelta(minutes=5)

        print(
            f"\n[{label}] Acquiring historical data for QQQ "
            f"from {start_date} to {end_date}..."
        )
        actions_info = manifest[ACTIONS_OBJECT_KEY]
        actions_body, actions_obs = _fetch_bytes(
            ACTIONS_OBJECT_KEY,
            actions_info["host"],
            actions_info["route"],
            actions_info["params"],
            keys,
        )
        cal_info = manifest[CALENDAR_OBJECT_KEY]
        cal_body, cal_obs = _fetch_bytes(
            CALENDAR_OBJECT_KEY,
            cal_info["host"],
            cal_info["route"],
            cal_info["params"],
            keys,
        )
        bars_info = manifest[BARS_OBJECT_KEY]
        bars_body, bars_obs = _fetch_bytes(
            BARS_OBJECT_KEY,
            bars_info["host"],
            bars_info["route"],
            bars_info["params"],
            keys,
        )
        payloads = AlpacaNativePayloads(
            bars=bars_body, calendar=cal_body, corporate_actions=actions_body
        )
        retain_native_bytes(store_dir, payloads)
        origin_obs: dict[str, Any] | None = {
            ACTIONS_OBJECT_KEY: actions_obs,
            CALENDAR_OBJECT_KEY: cal_obs,
            BARS_OBJECT_KEY: bars_obs,
        }
    elif mode == "offline":
        if offline_dir is None:
            raise ValueError(
                f"[{label}] Offline mode requires an offline payload directory"
            )
        print(f"\n[{label}] Loading offline payloads from {offline_dir}...")
        payloads, metadata = _load_offline_payloads(offline_dir)
        cal_body = payloads.calendar
        retained = retain_native_bytes(store_dir, payloads)

        # Copy any origin records from offline_dir to store_dir
        src_origins = offline_dir / "origins" / "sha256"
        if src_origins.is_dir():
            dst_origins = store_dir / "origins" / "sha256"
            dst_origins.mkdir(parents=True, exist_ok=True)
            for entry in src_origins.iterdir():
                if entry.is_file():
                    (dst_origins / entry.name).write_bytes(entry.read_bytes())

        if (
            metadata is not None
            and "request_start" in metadata
            and "request_end" in metadata
        ):
            t_start = datetime.fromisoformat(metadata["request_start"])
            t_end = datetime.fromisoformat(metadata["request_end"])
        else:
            now_utc = datetime.now(UTC).replace(microsecond=0)
            t_start = now_utc - timedelta(days=3650)
            t_end = now_utc + timedelta(days=1)

        bound = load_retained_origin_observations(
            retained, window_start=t_start, window_end=t_end
        )
        unbound = tuple(
            key
            for key in (ACTIONS_OBJECT_KEY, CALENDAR_OBJECT_KEY, BARS_OBJECT_KEY)
            if key not in bound
        )
        if unbound:
            print(
                f"[{label}] Missing origin records for {', '.join(unbound)}. "
                "Intake will record unverified origin evidence."
            )
            origin_obs = None
        else:
            origin_obs = bound
    else:
        raise ValueError(f"Unknown benchmark mode: {mode!r}")

    # Timezone evidence and calendar boundary offsets derived strictly from
    # verified TZIF bytes
    tz_bytes, tzdb_release = resolve_timezone_evidence("America/New_York")
    ny = ZoneInfo.from_file(io.BytesIO(tz_bytes), key="America/New_York")

    cal_json = json.loads(cal_body)
    boundary_offsets = {}
    for item in cal_json:
        d = date.fromisoformat(item["date"])
        dt_o = datetime.combine(d, dtime(9, 30), tzinfo=ny)
        offset_o = dt_o.utcoffset()
        assert offset_o is not None
        boundary_offsets[(d, "open")] = int(offset_o.total_seconds())
        dt_c = datetime.combine(d, dtime(16, 0), tzinfo=ny)
        offset_c = dt_c.utcoffset()
        assert offset_c is not None
        boundary_offsets[(d, "close")] = int(offset_c.total_seconds())

    repo_root = Path(__file__).resolve().parents[1]
    lockfile_path = repo_root / "uv.lock"
    if not lockfile_path.is_file():
        raise FileNotFoundError(
            f"Required lockfile not found at {lockfile_path}. "
            "Fail-closed: cannot construct authentic reconstruction lineage."
        )
    lockfile_bytes = lockfile_path.read_bytes()

    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise FileNotFoundError(
            f"Required pyproject.toml not found at {pyproject_path}. "
            "Fail-closed: cannot construct authentic reconstruction lineage."
        )
    pyproject_bytes = pyproject_path.read_bytes()

    producer_source_path = repo_root / "src/drift/adapters/alpaca_exploratory.py"
    if not producer_source_path.is_file():
        raise FileNotFoundError(
            f"Required producer source not found at {producer_source_path}. "
            "Fail-closed: cannot construct authentic reconstruction lineage."
        )
    producer_source_bytes = producer_source_path.read_bytes()

    qqq_sec_id = UUID("019b8240-0000-7000-8000-000000000002")
    qqq_list_id = UUID("019b8240-0000-7000-8000-000000000012")

    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    req = AlpacaIntakeRequest(
        cohort_id=f"qqq-smoke-{start_str}-{end_str}",
        cohort_version="1",
        members=(
            AlpacaCohortMember(
                symbol="QQQ",
                security_id=qqq_sec_id,
                listing_id=qqq_list_id,
                venue=ListingVenue.XNAS,
            ),
        ),
        mic="XNAS",
        start_date=start_date,
        end_date=end_date,
        plan_frozen_at=t_start,
        request_start=t_start,
        request_end=t_end,
        evidence_vintage_cutoff=t_end,
        timezone_evidence=AlpacaTimezoneEvidence(
            timezone_identifier="America/New_York",
            source_timezone_label="Eastern",
            tzif_bytes=tz_bytes,
            tzdb_release=tzdb_release,
            reconstruction_observed_at=t_end,
        ),
        lineage=AlpacaReconstructionLineage(
            producer_source=producer_source_bytes,
            producer_package=pyproject_bytes,
            lockfile=lockfile_bytes,
            python_identity=f"cpython-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        boundary_offsets=boundary_offsets,
        origin_observations=origin_obs,
    )

    t0 = time.time()
    intake_result = run_alpaca_exploratory_intake(
        request=req,
        payloads=payloads,
        private_root=store_dir,
    )
    print(f"[{label}] Intake completed in {time.time() - t0:.2f}s.")
    print(f"[{label}] Sessions: {len(intake_result.bundle.session_clock.sessions)}")
    print(
        f"[{label}] Corporate actions: "
        f"{len(intake_result.bundle.corporate_action_coverage)}"
    )

    return intake_result, payloads


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark_qqq_historical",
        description="Bounded historical benchmark smoke tests for QQQ (XNAS).",
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help=(
            "execution mode: 'offline' (default, requires --offline-bytes) "
            "or 'live' (explicit provider acquisition)"
        ),
    )
    parser.add_argument(
        "--offline-bytes",
        type=Path,
        default=None,
        help=(
            "directory of previously retained response bytes; required in offline mode"
        ),
    )
    parser.add_argument(
        "--private-root",
        type=Path,
        default=None,
        help=(
            "private retention root outside Git; "
            "defaults to ~/.drift/historical_benchmark_qqq/store"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    print("=" * 80)
    print("DRIFT REAL HISTORICAL BENCHMARK: QQQ SINGLE-VENUE SMOKE TESTS")
    print("=" * 80)

    args = _build_parser().parse_args(argv)
    base_store = args.private_root or (
        Path.home() / ".drift" / "historical_benchmark_qqq" / "store"
    )

    if args.mode == "offline":
        if args.offline_bytes is None:
            print("ERROR: offline mode requires --offline-bytes <directory>.")
            print(
                "For live acquisition, explicitly specify --mode live with "
                "authorized credentials."
            )
            return 1
        offline_aug = _find_window_offline_dir(
            args.offline_bytes, "action_free_aug2021"
        )
        offline_div = _find_window_offline_dir(
            args.offline_bytes, "dividend_aug_nov_2021"
        )
    else:
        offline_aug = None
        offline_div = None

    # --------------------------------------------------------------------------
    # Test 1: Action-Free Interval (August 2021, post-floor)
    # --------------------------------------------------------------------------
    print("\n--- TEST 1: ACTION-FREE INTERVAL (August 2021) ---")
    intake_aug, payloads_aug = _run_bounded_qqq_test(
        start_date=date(2021, 8, 2),
        end_date=date(2021, 8, 31),
        store_dir=base_store / "action_free_aug2021",
        label="Test 1 (Action-Free Aug 2021)",
        mode=args.mode,
        offline_dir=offline_aug,
    )

    qqq_sec_id = UUID("019b8240-0000-7000-8000-000000000002")
    cohort_aug = {
        "B0_Cash": "b0_cash",
        "B1_QQQ_BH": ("b1_single_buy_and_hold", {"target_security_id": qqq_sec_id}),
    }

    evidence_aug = SessionEvaluatorEvidence(
        exploratory_cohort=intake_aug.cohort,
        exploratory_listing_roles=intake_aug.exploratory_listing_roles,
        exploratory_reconstruction_replay=intake_aug.reconstruction_replay,
    )
    harness_aug = PortfolioCohortHarness(
        cohort=cohort_aug,
        bundle=intake_aug.bundle,
        admission=intake_aug.admission,
        evidence=evidence_aug,
    )
    results_aug = harness_aug.run(parallel=False)

    print("\nTest 1 Results (August 2021 Action-Free):")
    print(PortfolioCohortHarness.format_comparison_table(results_aug))
    for r in results_aug:
        print(f"  {r.strategy_id}:")
        print(f"    Classification: {r.classification}")
        print(f"    Halt reason: {r.halt_reason}")
        print(f"    Ending NAV: ${r.ending_nav:,.2f}")
        print(f"    Ending Cash: ${r.ending_cash:,.2f}")
        print(f"    Total Return: {r.total_return_pct}%")
        print(f"    Annualized Sharpe: {r.annualized_sharpe}")
        print(f"    Max Drawdown: {r.max_drawdown_pct}%")
        print(f"    Trading Costs: ${r.transaction_costs:,.2f}")
        print(f"    Settled Dividends: {r.settled_dividend_count}")
        print(f"    Simulated Fills: {r.fill_count}")

    b0_res = next(r for r in results_aug if r.strategy_id == "B0_Cash")
    b1_res = next(r for r in results_aug if r.strategy_id == "B1_QQQ_BH")
    assert b0_res.classification == "complete", (
        f"B0 classification was {b0_res.classification}"
    )
    assert b0_res.ending_nav == Decimal("10000.00"), (
        f"B0 ending NAV was {b0_res.ending_nav}"
    )
    assert b0_res.ending_cash == Decimal("10000.00"), (
        f"B0 ending cash was {b0_res.ending_cash}"
    )
    assert b0_res.fill_count == 0, f"B0 fill count was {b0_res.fill_count}"
    assert b0_res.transaction_costs == Decimal("0.00"), (
        f"B0 transaction costs was {b0_res.transaction_costs}"
    )

    assert b1_res.classification == "complete", (
        f"B1 classification was {b1_res.classification}"
    )
    assert b1_res.fill_count > 0, f"B1 fill count was {b1_res.fill_count}"
    assert b1_res.transaction_costs == Decimal("0.00"), (
        f"B1 transaction costs was {b1_res.transaction_costs}"
    )
    assert b1_res.ending_cash >= Decimal("0.00"), (
        f"B1 ending cash negative: {b1_res.ending_cash}"
    )

    # --------------------------------------------------------------------------
    # Test 2: Dividend-Crossing Interval (Aug-Nov 2021, post-floor)
    # --------------------------------------------------------------------------
    print("\n--- TEST 2: DIVIDEND-CROSSING INTERVAL (Aug-Nov 2021) ---")
    intake_div, payloads_div = _run_bounded_qqq_test(
        start_date=date(2021, 8, 2),
        end_date=date(2021, 11, 5),
        store_dir=base_store / "dividend_aug_nov_2021",
        label="Test 2 (Dividend-Crossing Aug-Nov 2021)",
        mode=args.mode,
        offline_dir=offline_div,
    )

    # Run 2A: Without modeled dividends (must fail closed)
    print("\n[Test 2A] Running B1 without modeled dividends (expecting fail-closed)...")
    evidence_unmodeled = SessionEvaluatorEvidence(
        exploratory_cohort=intake_div.cohort,
        exploratory_listing_roles=intake_div.exploratory_listing_roles,
        exploratory_reconstruction_replay=intake_div.reconstruction_replay,
    )
    harness_unmodeled = PortfolioCohortHarness(
        cohort={
            "B1_QQQ_BH": (
                "b1_single_buy_and_hold",
                {"target_security_id": qqq_sec_id},
            )
        },
        bundle=intake_div.bundle,
        admission=intake_div.admission,
        evidence=evidence_unmodeled,
    )
    results_unmodeled = harness_unmodeled.run(parallel=False)
    r_un = results_unmodeled[0]
    print("VERIFIED FAIL-CLOSED:")
    print(f"  Strategy: {r_un.strategy_id}")
    print(f"  Classification: {r_un.classification}")
    print(f"  Halt reason: {r_un.halt_reason}")
    assert r_un.classification == "indeterminate", (
        f"Test 2A classification was {r_un.classification}"
    )
    assert "corporate-action" in (r_un.halt_reason or ""), (
        f"Test 2A halt reason was {r_un.halt_reason}"
    )

    # Run 2B: With modeled dividends (exploratory accounting)
    print("\n[Test 2B] Running with modeled exploratory dividends...")
    div_policy = build_exploratory_dividends_from_alpaca(
        payloads_div.corporate_actions,
        (
            AlpacaCohortMember(
                symbol="QQQ",
                security_id=qqq_sec_id,
                listing_id=UUID("019b8240-0000-7000-8000-000000000012"),
                venue=ListingVenue.XNAS,
            ),
        ),
        response_sha256=intake_div.retained.corporate_actions_hash,
    )
    print(
        f"Built exploratory dividend terms: "
        f"{len(div_policy.dividends)} term(s) covering "
        f"{', '.join(sorted(str(d.security_id) for d in div_policy.dividends))}"
    )

    evidence_div = SessionEvaluatorEvidence(
        exploratory_cohort=intake_div.cohort,
        exploratory_listing_roles=intake_div.exploratory_listing_roles,
        exploratory_reconstruction_replay=intake_div.reconstruction_replay,
        exploratory_dividends=div_policy,
    )
    cohort_div = {
        "B0_Cash": "b0_cash",
        "B1_QQQ_BH": ("b1_single_buy_and_hold", {"target_security_id": qqq_sec_id}),
    }
    harness_div = PortfolioCohortHarness(
        cohort=cohort_div,
        bundle=intake_div.bundle,
        admission=intake_div.admission,
        evidence=evidence_div,
    )
    results_div = harness_div.run(parallel=False)

    print("\nTest 2B Results (With Modeled Dividends):")
    print(PortfolioCohortHarness.format_comparison_table(results_div))
    for r in results_div:
        print(f"  {r.strategy_id}:")
        print(f"    Classification: {r.classification}")
        print(f"    Halt reason: {r.halt_reason}")
        print(f"    Ending NAV: ${r.ending_nav:,.2f}")
        print(f"    Ending Cash: ${r.ending_cash:,.2f}")
        print(f"    Total Return: {r.total_return_pct}%")
        print(f"    Annualized Sharpe: {r.annualized_sharpe}")
        print(f"    Max Drawdown: {r.max_drawdown_pct}%")
        print(f"    Trading Costs: ${r.transaction_costs:,.2f}")
        print(f"    Settled Dividends: {r.settled_dividend_count}")
        print(f"    Simulated Fills: {r.fill_count}")

    b0_div_res = next(r for r in results_div if r.strategy_id == "B0_Cash")
    b1_div_res = next(r for r in results_div if r.strategy_id == "B1_QQQ_BH")
    assert b0_div_res.classification == "complete", (
        f"B0 div classification was {b0_div_res.classification}"
    )
    assert b0_div_res.ending_nav == Decimal("10000.00"), (
        f"B0 div ending NAV was {b0_div_res.ending_nav}"
    )
    assert b0_div_res.ending_cash == Decimal("10000.00"), (
        f"B0 div ending cash was {b0_div_res.ending_cash}"
    )
    assert b0_div_res.fill_count == 0, f"B0 div fill count was {b0_div_res.fill_count}"
    assert b0_div_res.settled_dividend_count == 0, (
        f"B0 div settled dividends was {b0_div_res.settled_dividend_count}"
    )
    assert b0_div_res.transaction_costs == Decimal("0.00"), (
        f"B0 div transaction costs was {b0_div_res.transaction_costs}"
    )

    assert b1_div_res.classification == "complete", (
        f"B1 div classification was {b1_div_res.classification}"
    )
    assert b1_div_res.settled_dividend_count >= 1, (
        f"B1 settled dividends was {b1_div_res.settled_dividend_count}"
    )
    assert b1_div_res.fill_count > 0, f"B1 div fill count was {b1_div_res.fill_count}"
    assert b1_div_res.transaction_costs == Decimal("0.00"), (
        f"B1 div transaction costs was {b1_div_res.transaction_costs}"
    )
    assert b1_div_res.ending_cash >= Decimal("0.00"), (
        f"B1 div ending cash negative: {b1_div_res.ending_cash}"
    )

    print("\n" + "=" * 80)
    print("ALL QQQ BENCHMARK SMOKE TESTS COMPLETED SUCCESSFULLY")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
