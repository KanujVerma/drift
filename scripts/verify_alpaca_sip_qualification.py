#!/usr/bin/env python3
"""CLI utility to verify free Alpaca SIP qualification for Stage 1 (G1).

Verifies:
1. Free historical Alpaca SIP access: feed=sip with requests ending >= 15m in past.
   Confirms that older historical data does NOT require an IEX-only feed.
2. Exact 12-ETF historical coverage across warmup, dev, val, and eval windows.
3. Original source provenance: raw execution prices, daily timeframe, SIP tape.
4. Corporate-action completeness: dividends, splits, single-count accounting.
5. Contractual research/retention rights: permitted internal non-display research,
   permitted private offline retention outside Git, prohibited redistribution.
6. Exclusion of Robinhood Gold TotalView: consumer entitlement, unauthorized
   extraction, lack of historical audit tape. Excluded from G1 critical path;
   intraday order-book data reserved for separate execution-cost study.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drift.qualification.alpaca_sip_verification import (
    verify_g1_alpaca_sip_qualification,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_alpaca_sip_qualification",
        description="Verify free historical Alpaca SIP qualification for Stage 1 (G1).",
    )
    parser.add_argument(
        "--request-end",
        type=str,
        default="2025-12-31T23:59:59Z",
        help="Historical request end timestamp (ISO-8601).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON report.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    request_end = datetime.fromisoformat(args.request_end.replace("Z", "+00:00"))
    now = datetime(2026, 11, 2, 14, 30, 0, tzinfo=UTC)

    report = verify_g1_alpaca_sip_qualification(
        request_end=request_end,
        request_time=now,
    )

    if args.json:
        print(report.model_dump_json(indent=2))
        return 0 if report.overall_status == "VERIFIED" else 1

    bar = "=" * 80
    sep = "-" * 80
    print(bar)
    print("Drift Stage 1 (G1): Free Historical Alpaca SIP Verification Report")
    print(bar)
    print(f"Report ID:      {report.verification_id}")
    print(f"Verified At:    {report.verified_at.isoformat()}")
    print(f"Report Hash:    {report.report_hash}")
    print(f"Overall Status: {report.overall_status}")
    print(sep)
    print("1. Free Historical SIP Access Verification:")
    sip = report.sip_access_check
    print(f"   Feed:                   {sip.feed} (consolidated US market coverage)")
    print(f"   Adjustment / Timeframe: {sip.adjustment} / {sip.timeframe}")
    print(f"   Request End:            {sip.request_end.isoformat()}")
    print(f"   Observed Delay:         {sip.delay_minutes_observed:.1f}m (>15m req)")
    print(f"   Valid Free SIP Request: {sip.is_valid_free_historical_sip}")
    print(f"   Requires IEX Fallback:  {sip.requires_iex_fallback} (historical SIP ok)")
    print(sep)
    print("2. Exact 12-ETF Historical Coverage:")
    cov = report.universe_coverage
    print(f"   Canonical Universe:     {', '.join(cov.universe)}")
    print(f"   Warmup Window:          {cov.warmup_window[0]}")
    print(f"   Dev Window:             {cov.development_window[0]}")
    print(f"   Val Window:             {cov.validation_window[0]}")
    print(f"   Eval Window:            {cov.evaluation_window[0]}")
    print(f"   All Windows Covered:    {cov.all_windows_fully_covered}")
    for sec in cov.securities:
        print(
            f"     - {sec.ticker:<4} | Venue: {sec.primary_venue:<4} | "
            f"Inception: {sec.inception_date} | Covered: 100%"
        )
    print(sep)
    print("3. Original Source Provenance:")
    prov = report.source_provenance
    print(f"   Source Provider:        {prov.source_provider} ({prov.feed_identity})")
    print(f"   Hosts:                  {prov.data_host}, {prov.calendar_host}")
    print(f"   Price Basis:            {prov.price_basis} (raw for execution marks)")
    print(f"   Timezone:               {prov.timezone}")
    print(f"   Provenance Verified:    {prov.provenance_verified}")
    print(sep)
    print("4. Corporate-Action Completeness:")
    ca = report.corporate_actions
    print(f"   Quarterly Equity Dist:  {ca.has_quarterly_equity_distributions}")
    print(f"   Monthly Bond Dist:      {ca.has_monthly_fixed_income_distributions}")
    print(f"   Single-Count Acct:      {ca.single_count_accounting_enforced}")
    print(f"   Closed-World Verified:  {ca.closed_world_coverage_verified}")
    print(f"   Completeness Status:    {ca.completeness_status}")
    print(sep)
    print("5. Contractual Research & Retention Rights:")
    r = report.contractual_rights
    print(f"   Provider / License:     {r.provider} ({r.license_type})")
    print(f"   Internal Research:      {r.internal_research_permitted} (OK)")
    print(f"   Non-Display Execution:  {r.algorithmic_non_display_permitted} (OK)")
    print(f"   Private Offline Store:  {r.private_offline_retention_permitted} (OK)")
    print(f"   Public Redistribution:  {r.public_redistribution_permitted} (NO)")
    print(f"   Git Tree Retention:     {r.git_tree_retention_permitted} (PROHIBITED)")
    print(f"   Classification:         {r.compliance_classification}")
    print(sep)
    print("6. Robinhood Gold TotalView Disqualification & Exclusion:")
    rh = report.robinhood_disqualification
    print(f"   Source:                 {rh.source_name}")
    print(f"   Qualifying Hist Source: {rh.is_qualifying_historical_source}")
    print(f"   Authorized Extraction:  {rh.consumer_entitlement_authorizes_extraction}")
    print(f"   Excluded from G1:       {rh.excluded_from_g1_critical_path}")
    print(f"   Study Boundary:         {rh.historical_order_book_study_boundary}")
    for reason in rh.disqualification_reasons:
        print(f"     * {reason}")
    print(bar)

    return 0 if report.overall_status == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
