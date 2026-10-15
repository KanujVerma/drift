"""Bounded historical benchmark smoke tests for QQQ (XNAS).

Tests:
1. Action-free interval (August 2021): B0 (Cash) and B1 (QQQ Buy-and-Hold).
2. Dividend-crossing interval (August-November 2021):
   - Fail-closed run without modeled dividends: verify INDETERMINATE.
   - Exploratory run with modeled dividends: verify entitlement and NAV.
"""

import json
import re
import sys
import time
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


def _run_bounded_qqq_test(
    start_date: date,
    end_date: date,
    store_dir: Path,
    label: str,
) -> tuple[Any, AlpacaNativePayloads]:
    keys = _get_api_keys()
    store_dir.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(UTC).replace(microsecond=0)
    t_start = now_utc - timedelta(minutes=5)
    t_end = now_utc + timedelta(minutes=5)

    print(
        f"\n[{label}] Acquiring historical data for QQQ "
        f"from {start_date} to {end_date}..."
    )
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    actions_params = {
        "end": end_str,
        "start": start_str,
        "symbols": "QQQ",
        "types": ",".join(ALPACA_ACTION_TYPES),
    }
    actions_body, actions_obs = _fetch_bytes(
        ACTIONS_OBJECT_KEY, ALPACA_DATA_HOST, ALPACA_ACTIONS_ROUTE, actions_params, keys
    )

    cal_params = {"end": end_str, "start": start_str}
    cal_body, cal_obs = _fetch_bytes(
        CALENDAR_OBJECT_KEY,
        ALPACA_PAPER_TRADING_HOST,
        ALPACA_CALENDAR_ROUTE,
        cal_params,
        keys,
    )

    bars_params = {
        "adjustment": "raw",
        "end": end_str,
        "feed": "sip",
        "limit": "10000",
        "start": start_str,
        "symbols": "QQQ",
        "timeframe": "1Day",
    }
    bars_body, bars_obs = _fetch_bytes(
        BARS_OBJECT_KEY, ALPACA_DATA_HOST, ALPACA_BARS_ROUTE, bars_params, keys
    )

    payloads = AlpacaNativePayloads(
        bars=bars_body, calendar=cal_body, corporate_actions=actions_body
    )

    cal_json = json.loads(cal_body)
    ny = ZoneInfo("America/New_York")
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

    tz_bytes, tzdb_release = resolve_timezone_evidence("America/New_York")

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
        origin_observations={
            ACTIONS_OBJECT_KEY: actions_obs,
            CALENDAR_OBJECT_KEY: cal_obs,
            BARS_OBJECT_KEY: bars_obs,
        },
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


def main() -> None:
    print("=" * 80)
    print("DRIFT REAL HISTORICAL BENCHMARK: QQQ SINGLE-VENUE SMOKE TESTS")
    print("=" * 80)

    base_store = Path.home() / ".drift" / "historical_benchmark_qqq" / "store"

    # --------------------------------------------------------------------------
    # Test 1: Action-Free Interval (August 2021, post-floor)
    # --------------------------------------------------------------------------
    print("\n--- TEST 1: ACTION-FREE INTERVAL (August 2021) ---")
    intake_aug, payloads_aug = _run_bounded_qqq_test(
        start_date=date(2021, 8, 2),
        end_date=date(2021, 8, 31),
        store_dir=base_store / "action_free_aug2021",
        label="Test 1 (Action-Free Aug 2021)",
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
    assert b1_res.classification == "complete", (
        f"B1 classification was {b1_res.classification}"
    )
    assert b1_res.ending_nav > Decimal("10000.00"), (
        f"B1 ending NAV was {b1_res.ending_nav}"
    )
    assert b1_res.fill_count > 0, f"B1 fill count was {b1_res.fill_count}"

    # --------------------------------------------------------------------------
    # Test 2: Dividend-Crossing Interval (Aug-Nov 2021, post-floor)
    # --------------------------------------------------------------------------
    print("\n--- TEST 2: DIVIDEND-CROSSING INTERVAL (Aug-Nov 2021) ---")
    intake_div, payloads_div = _run_bounded_qqq_test(
        start_date=date(2021, 8, 2),
        end_date=date(2021, 11, 5),
        store_dir=base_store / "dividend_aug_nov_2021",
        label="Test 2 (Dividend-Crossing Aug-Nov 2021)",
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
        f"  Built dividend policy with {len(div_policy.dividends)} terms, "
        f"hash: {div_policy.terms_hash[:16]}..."
    )
    for d in div_policy.dividends:
        print(
            f"    Dividend {d.native_id}: ex={d.ex_date}, "
            f"pay={d.payable_date}, rate=${d.rate}"
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
    assert b1_div_res.classification == "complete", (
        f"B1 div classification was {b1_div_res.classification}"
    )
    assert b1_div_res.settled_dividend_count >= 1, (
        f"B1 settled dividends was {b1_div_res.settled_dividend_count}"
    )
    assert b1_div_res.ending_nav > Decimal("10000.00"), (
        f"B1 ending NAV was {b1_div_res.ending_nav}"
    )

    print("\n" + "=" * 80)
    print("ALL QQQ BENCHMARK SMOKE TESTS COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    main()
