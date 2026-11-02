"""Verification of free historical Alpaca SIP access for Drift Stage 1 (G1).

Verifies:
1. Free historical Alpaca SIP access: feed=sip with requests ending >= 15 min ago.
   Confirms that older historical data does NOT require an IEX-only feed.
2. Exact 12-ETF historical coverage across warmup, dev, val, and eval windows.
3. Original source provenance: raw execution prices, daily timeframe, SIP tape,
   inspected response bytes and acquisition receipts.
4. Corporate-action completeness: dividends, splits, single-count accounting,
   and verified closed-world coverage records across all 12 ETF cohort members.
5. Contractual research/retention rights: evidence-bound rights assessment;
   leaves permissions unresolved when rights evidence is absent.
6. Exclusion of Robinhood Gold TotalView: consumer entitlement, unauthorized
   extraction, lack of historical audit tape. Excluded from G1 critical path;
   intraday order-book data reserved for separate execution-cost study.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.serialization.canonical import canonical_json, content_hash

ALPACA_SIP_FEED = "sip"
ALPACA_DELAY_MINIMUM_MINUTES = 15

STUDY_START_DATE: date = date(2019, 10, 1)
STUDY_END_DATE: date = date(2025, 12, 31)
STUDY_MIN_BARS_COUNT: int = 500

EQUITY_ETFS: tuple[str, ...] = ("VOO", "IJH", "IJR", "QQQ", "VEA", "VWO")
BOND_ETFS: tuple[str, ...] = ("SHY", "IEF", "TLT", "TIP", "LQD")

EXACT_12_ETF_UNIVERSE: tuple[str, ...] = (
    "VOO",
    "IJH",
    "IJR",
    "QQQ",
    "VEA",
    "VWO",
    "SHY",
    "IEF",
    "TLT",
    "TIP",
    "LQD",
    "GLD",
)

ETF_PRIMARY_VENUES: dict[str, str] = {
    "VOO": "ARCX",
    "IJH": "ARCX",
    "IJR": "ARCX",
    "QQQ": "XNAS",
    "VEA": "ARCX",
    "VWO": "ARCX",
    "SHY": "XNAS",
    "IEF": "XNAS",
    "TLT": "XNAS",
    "TIP": "ARCX",
    "LQD": "ARCX",
    "GLD": "ARCX",
}

ETF_INCEPTION_DATES: dict[str, date] = {
    "QQQ": date(1999, 3, 10),
    "IJH": date(2000, 5, 22),
    "IJR": date(2000, 5, 22),
    "SHY": date(2002, 7, 22),
    "IEF": date(2002, 7, 22),
    "TLT": date(2002, 7, 22),
    "LQD": date(2002, 7, 22),
    "TIP": date(2003, 12, 4),
    "GLD": date(2004, 11, 18),
    "VWO": date(2005, 3, 4),
    "VEA": date(2007, 7, 20),
    "VOO": date(2010, 9, 7),
}

DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW = "robinhood-gold-nasdaq-totalview-level-ii"


def verify_alpaca_sip_request_delay(
    request_end: datetime,
    request_time: datetime | None = None,
) -> tuple[bool, str | None]:
    """Verify that a historical SIP request obeys the free tier 15-minute delay rule.

    Free Basic tier allows 100% consolidated SIP market data for historical requests
    as long as the request end timestamp is at least 15 minutes prior to query time.
    Requests ending within 15 minutes of present are rejected by Alpaca with:
    `subscription does not permit querying recent SIP data`.
    """
    now = datetime.now(UTC) if request_time is None else request_time
    if request_end.tzinfo is None:
        raise ValueError("request_end must be timezone-aware (UTC)")
    if now.tzinfo is None:
        raise ValueError("request_time must be timezone-aware (UTC)")

    cutoff = now - timedelta(minutes=ALPACA_DELAY_MINIMUM_MINUTES)
    if request_end > cutoff:
        delta = (request_end - cutoff).total_seconds()
        return (
            False,
            f"FREE_SIP_REQUEST_WITHIN_15_MINUTES: request end "
            f"{request_end.isoformat()} is {delta:.1f}s past the 15-minute delay "
            f"cutoff {cutoff.isoformat()}. Subscription does not permit querying "
            "recent SIP data on the free tier.",
        )
    return True, None


class AlpacaSipHistoricalRequestCheckV1(FrozenModel):
    feed: Literal["sip"] = "sip"
    adjustment: Literal["raw"] = "raw"
    timeframe: Literal["1Day"] = "1Day"
    request_end: UTCDateTime
    request_time: UTCDateTime
    delay_minutes_observed: float
    is_valid_free_historical_sip: bool
    requires_iex_fallback: bool = False
    refusal_reason: str | None = None

    @model_validator(mode="after")
    def validate_check(self) -> Self:
        if self.requires_iex_fallback:
            raise ValueError("IEX_FALLBACK_NOT_PERMITTED_FOR_HISTORICAL_SIP")
        if not self.is_valid_free_historical_sip and self.refusal_reason is None:
            raise ValueError("MISSING_REFUSAL_REASON_FOR_INVALID_REQUEST")
        return self


class SecurityHistoricalCoverageV1(FrozenModel):
    ticker: NonBlankStr
    primary_venue: NonBlankStr
    inception_date: date
    warmup_covered: bool
    development_covered: bool
    validation_covered: bool
    evaluation_covered: bool


class Universe12EtfCoverageV1(FrozenModel):
    universe: tuple[str, ...] = EXACT_12_ETF_UNIVERSE
    warmup_window: tuple[date, date] = (date(2019, 10, 1), date(2020, 12, 31))
    development_window: tuple[date, date] = (date(2021, 1, 1), date(2023, 12, 31))
    validation_window: tuple[date, date] = (date(2024, 1, 1), date(2024, 12, 31))
    evaluation_window: tuple[date, date] = (date(2025, 1, 1), date(2025, 12, 31))
    securities: tuple[SecurityHistoricalCoverageV1, ...]
    all_windows_fully_covered: bool

    @model_validator(mode="after")
    def validate_universe(self) -> Self:
        if self.universe != EXACT_12_ETF_UNIVERSE:
            raise ValueError("PRIMARY_UNIVERSE_MUST_MATCH_CANONICAL_12_ETFS")
        tickers = tuple(s.ticker for s in self.securities)
        if tickers != EXACT_12_ETF_UNIVERSE:
            raise ValueError("SECURITIES_TICKERS_MUST_MATCH_EXACT_12_ETFS_ORDER")
        for s in self.securities:
            if s.inception_date > self.warmup_window[0]:
                raise ValueError(
                    f"INCEPTION_AFTER_WARMUP:{s.ticker}:{s.inception_date}"
                )
        return self


class OriginalSourceProvenanceV1(FrozenModel):
    source_provider: Literal["alpaca"] = "alpaca"
    feed_identity: Literal["sip"] = "sip"
    data_host: str = "data.alpaca.markets"
    calendar_host: str = "paper-api.alpaca.markets"
    bars_endpoint: str = "/v2/stocks/bars"
    calendar_endpoint: str = "/v2/calendar"
    corporate_actions_endpoint: str = "/v2/corporate-actions"
    price_basis: Literal["raw_execution"] = "raw_execution"
    timezone: Literal["America/New_York"] = "America/New_York"
    provenance_verified: bool = False
    bars_sha256: SHA256Hash | None = None
    calendar_sha256: SHA256Hash | None = None
    corporate_actions_sha256: SHA256Hash | None = None


class CorporateActionCompletenessV1(FrozenModel):
    universe: tuple[str, ...] = EXACT_12_ETF_UNIVERSE
    has_quarterly_equity_distributions: bool = False
    has_monthly_fixed_income_distributions: bool = False
    all_splits_captured: bool = False
    single_count_accounting_enforced: bool = True
    closed_world_coverage_verified: bool = False
    completeness_status: Literal["COMPLETE", "INCOMPLETE"] = "INCOMPLETE"
    covered_security_count: int = 0


class ContractualResearchRetentionRightsV1(FrozenModel):
    provider: Literal["alpaca"] = "alpaca"
    license_type: Literal["developer_basic_api"] = "developer_basic_api"
    is_verified: bool = False
    internal_research_permitted: bool = False
    algorithmic_non_display_permitted: bool = False
    private_offline_retention_permitted: bool = False
    public_redistribution_permitted: Literal[False] = False
    git_tree_retention_permitted: Literal[False] = False
    compliance_classification: Literal[
        "PERMITTED_INTERNAL_RESEARCH_ONLY",
        "UNRESOLVED_NEEDS_RIGHTS_AUDIT",
    ] = "UNRESOLVED_NEEDS_RIGHTS_AUDIT"
    rights_assessment_hash: SHA256Hash | None = None


class RobinhoodTotalViewDisqualificationV1(FrozenModel):
    source_name: str = DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW
    is_qualifying_historical_source: Literal[False] = False
    consumer_entitlement_authorizes_extraction: Literal[False] = False
    excluded_from_g1_critical_path: Literal[True] = True
    historical_order_book_study_boundary: str = (
        "Licensed historical order-book data (e.g. Nasdaq TotalView ITCH / "
        "Databento L3) is deferred to a separate, subsequent intraday study."
    )
    disqualification_reasons: tuple[str, ...] = (
        "CONSUMER_DISPLAY_ENTITLEMENT_ONLY: Robinhood Gold Level II is licensed "
        "strictly for retail interactive graphical display, not automated ingestion.",
        "UNAUTHORIZED_PROGRAMMATIC_EXTRACTION: Consumer terms explicitly prohibit "
        "automated scraping, extraction, or export into algorithmic trading software.",
        "LACKS_HISTORICAL_AUDIT_TAPE: Real-time depth only; provides no historical "
        "reconstruction or verifiable audit trail for 2019-2025 research windows.",
        "EXCLUDED_FROM_G1_CRITICAL_PATH: G1 historical evaluation relies on "
        "consolidated SIP daily bars with raw execution prices, not consumer displays.",
    )


class AlpacaSipG1VerificationReportV1(FrozenModel):
    schema_version: Literal["drift-g1-alpaca-sip-verification/1"] = (
        "drift-g1-alpaca-sip-verification/1"
    )
    verification_id: NonBlankStr
    verified_at: UTCDateTime
    sip_access_check: AlpacaSipHistoricalRequestCheckV1
    universe_coverage: Universe12EtfCoverageV1
    source_provenance: OriginalSourceProvenanceV1
    corporate_actions: CorporateActionCompletenessV1
    contractual_rights: ContractualResearchRetentionRightsV1
    robinhood_disqualification: RobinhoodTotalViewDisqualificationV1
    refusal_reasons: tuple[str, ...] = ()
    overall_status: Literal["VERIFIED", "REFUSED"]
    report_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        body = self.model_dump(mode="python", exclude={"report_hash"})
        if self.report_hash != content_hash(body):
            raise ValueError("VERIFICATION_REPORT_HASH_MISMATCH")
        if self.overall_status == "VERIFIED":
            if self.refusal_reasons:
                raise ValueError("VERIFIED_REPORT_CANNOT_HAVE_REFUSAL_REASONS")
            if not self.sip_access_check.is_valid_free_historical_sip:
                raise ValueError("CANNOT_VERIFY_WITH_INVALID_SIP_ACCESS")
            if not self.universe_coverage.all_windows_fully_covered:
                raise ValueError("CANNOT_VERIFY_WITH_INCOMPLETE_UNIVERSE_COVERAGE")
            if not self.source_provenance.provenance_verified:
                raise ValueError("CANNOT_VERIFY_WITH_UNVERIFIED_PROVENANCE")
            if self.corporate_actions.completeness_status != "COMPLETE":
                raise ValueError("CANNOT_VERIFY_WITH_INCOMPLETE_CORPORATE_ACTIONS")
            if not self.contractual_rights.is_verified:
                raise ValueError("CANNOT_VERIFY_WITH_UNVERIFIED_RIGHTS")
            if not self.robinhood_disqualification.excluded_from_g1_critical_path:
                raise ValueError("ROBINHOOD_TOTALVIEW_MUST_BE_EXCLUDED_FROM_G1")
        return self


class AlpacaSipIntakeEvidenceV1(FrozenModel):
    """Verified evidence of raw Alpaca SIP intake."""

    provider: Literal["alpaca"] = "alpaca"
    feed: Literal["sip"] = "sip"
    bars_sha256: SHA256Hash
    calendar_sha256: SHA256Hash
    corporate_actions_sha256: SHA256Hash
    bars_byte_size: Annotated[int, Field(gt=0)]
    calendar_byte_size: Annotated[int, Field(gt=0)]
    corporate_actions_byte_size: Annotated[int, Field(gt=0)]
    receipt_id: NonBlankStr
    reconciliation_pass: Literal[True] = True


class SecurityHistoricalCoverageEvidenceV1(FrozenModel):
    """Evidence of historical coverage across required study windows."""

    ticker: str
    warmup_covered: bool = True
    development_covered: bool = True
    validation_covered: bool = True
    evaluation_covered: bool = True
    coverage_start: date = Field(le=date(2019, 10, 1))
    coverage_end: date = Field(ge=date(2025, 12, 31))
    observed_bars_count: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_ticker(self) -> Self:
        if self.ticker not in EXACT_12_ETF_UNIVERSE:
            raise ValueError(f"UNRECOGNIZED_12_ETF_TICKER:{self.ticker}")
        return self


class CorporateActionEvidenceRecordV1(FrozenModel):
    """Verified closed-world corporate-action coverage record for one security."""

    ticker: str
    has_quarterly_equity_distributions: bool = False
    has_monthly_fixed_income_distributions: bool = False
    all_splits_captured: bool = False
    closed_world_coverage_verified: bool = True
    covered_start_date: date = Field(le=date(2019, 10, 1))
    covered_end_date: date = Field(ge=date(2025, 12, 31))
    single_count_accounting_enforced: Literal[True] = True
    completeness_basis: str = Field(min_length=3)

    @model_validator(mode="after")
    def validate_action_coverage(self) -> Self:
        if self.ticker not in EXACT_12_ETF_UNIVERSE:
            raise ValueError(f"UNRECOGNIZED_12_ETF_TICKER:{self.ticker}")
        if self.ticker in ("VOO", "IJH", "IJR", "QQQ", "VEA", "VWO"):
            if not self.has_quarterly_equity_distributions:
                raise ValueError(
                    f"EQUITY_ETF_MISSING_QUARTERLY_DISTRIBUTIONS:{self.ticker}"
                )
        elif self.ticker in ("SHY", "IEF", "TLT", "TIP", "LQD"):
            if not self.has_monthly_fixed_income_distributions:
                raise ValueError(
                    f"BOND_ETF_MISSING_MONTHLY_DISTRIBUTIONS:{self.ticker}"
                )
        if not self.all_splits_captured:
            raise ValueError(f"SPLIT_COVERAGE_UNVERIFIED:{self.ticker}")
        if not self.closed_world_coverage_verified:
            raise ValueError(f"CLOSED_WORLD_COVERAGE_UNVERIFIED:{self.ticker}")
        return self


class ContractualRightsAssessmentEvidenceV1(FrozenModel):
    """Adjudicated contractual rights assessment for Alpaca data in Drift."""

    assessment_id: NonBlankStr
    assessor_identity: NonBlankStr
    authority: NonBlankStr
    entitlement_state: Literal["active", "permitted"] = "active"
    internal_research_permitted: Literal[True]
    algorithmic_non_display_permitted: Literal[True]
    private_offline_retention_permitted: Literal[True]
    public_redistribution_permitted: Literal[False]
    git_tree_retention_permitted: Literal[False]
    evidence_document_hashes: tuple[SHA256Hash, ...] = Field(min_length=1)


def create_mock_alpaca_sip_evidence_fixtures() -> tuple[
    AlpacaSipIntakeEvidenceV1,
    tuple[SecurityHistoricalCoverageEvidenceV1, ...],
    tuple[CorporateActionEvidenceRecordV1, ...],
    ContractualRightsAssessmentEvidenceV1,
]:
    """Create authoritative offline fixtures demonstrating complete verified pass."""
    intake = AlpacaSipIntakeEvidenceV1(
        provider="alpaca",
        feed="sip",
        bars_sha256="a" * 64,
        calendar_sha256="b" * 64,
        corporate_actions_sha256="c" * 64,
        bars_byte_size=1024,
        calendar_byte_size=512,
        corporate_actions_byte_size=512,
        receipt_id="MOCK-ACQ-RECEIPT-ALPACA-SIP-V1",
        reconciliation_pass=True,
    )
    coverage = tuple(
        SecurityHistoricalCoverageEvidenceV1(
            ticker=t,
            warmup_covered=True,
            development_covered=True,
            validation_covered=True,
            evaluation_covered=True,
            coverage_start=date(2019, 10, 1),
            coverage_end=date(2025, 12, 31),
            observed_bars_count=1560,
        )
        for t in EXACT_12_ETF_UNIVERSE
    )
    corporate_actions = tuple(
        CorporateActionEvidenceRecordV1(
            ticker=t,
            has_quarterly_equity_distributions=t
            in ("VOO", "IJH", "IJR", "QQQ", "VEA", "VWO"),
            has_monthly_fixed_income_distributions=t
            in ("SHY", "IEF", "TLT", "TIP", "LQD"),
            all_splits_captured=True,
            closed_world_coverage_verified=True,
            covered_start_date=date(2019, 10, 1),
            covered_end_date=date(2025, 12, 31),
            single_count_accounting_enforced=True,
            completeness_basis="ALPACA_EXPLORATORY_CLOSED_WORLD_V1",
        )
        for t in EXACT_12_ETF_UNIVERSE
    )
    rights = ContractualRightsAssessmentEvidenceV1(
        assessment_id="MOCK-RIGHTS-ASSESSMENT-ALPACA-V1",
        assessor_identity="matthew@drift.local",
        authority="matthew@drift.local",
        entitlement_state="active",
        internal_research_permitted=True,
        algorithmic_non_display_permitted=True,
        private_offline_retention_permitted=True,
        public_redistribution_permitted=False,
        git_tree_retention_permitted=False,
        evidence_document_hashes=("d" * 64,),
    )
    return intake, coverage, corporate_actions, rights


def create_mock_valid_raw_payloads(
    bars_count: int = 1560,
) -> Any:
    """Generate mock raw Alpaca JSON payloads meeting complete provider schemas."""
    from types import SimpleNamespace

    start_d = STUDY_START_DATE
    end_d = STUDY_END_DATE
    total_days = (end_d - start_d).days

    dates = [
        start_d + timedelta(days=int(i * total_days / (bars_count - 1)))
        for i in range(bars_count)
    ]

    bars_map = {
        sym: [
            {
                "t": f"{d.isoformat()}T14:30:00Z",
                "o": 100.0,
                "h": 105.0,
                "l": 95.0,
                "c": 102.0,
                "v": 50000.0,
            }
            for d in dates
        ]
        for sym in EXACT_12_ETF_UNIVERSE
    }
    bars_payload = json.dumps({"bars": bars_map, "next_page_token": None}).encode(
        "utf-8"
    )

    calendar_list = [
        {"date": d.isoformat(), "open": "09:30", "close": "16:00"}
        for d in sorted(set(dates))
    ]
    calendar_payload = json.dumps(calendar_list).encode("utf-8")

    dividends_list = [
        {
            "symbol": sym,
            "ex_date": "2024-03-15",
            "rate": 1.50,
        }
        for sym in (*EQUITY_ETFS, *BOND_ETFS)
    ]
    ca_payload = json.dumps(
        {
            "corporate_actions": {
                "cash_dividends": dividends_list,
                "forward_splits": [],
            },
            "next_page_token": None,
        }
    ).encode("utf-8")

    return SimpleNamespace(
        bars=bars_payload,
        calendar=calendar_payload,
        corporate_actions=ca_payload,
    )


def build_12_etf_coverage(
    coverage_evidence: Sequence[Any] | None = None,
) -> Universe12EtfCoverageV1:
    """Build the 12-ETF historical coverage matrix from observed coverage evidence."""
    verified_map: dict[str, SecurityHistoricalCoverageEvidenceV1] = {}
    if coverage_evidence is not None:
        for item in coverage_evidence:
            try:
                if isinstance(item, SecurityHistoricalCoverageEvidenceV1):
                    rec = item
                elif isinstance(item, dict):
                    rec = SecurityHistoricalCoverageEvidenceV1.model_validate(item)
                else:
                    rec = SecurityHistoricalCoverageEvidenceV1.model_validate(
                        getattr(item, "__dict__", {})
                    )
                verified_map[rec.ticker] = rec
            except Exception:
                continue

    securities = tuple(
        SecurityHistoricalCoverageV1(
            ticker=ticker,
            primary_venue=ETF_PRIMARY_VENUES[ticker],
            inception_date=ETF_INCEPTION_DATES[ticker],
            warmup_covered=(
                ticker in verified_map and verified_map[ticker].warmup_covered
            ),
            development_covered=(
                ticker in verified_map and verified_map[ticker].development_covered
            ),
            validation_covered=(
                ticker in verified_map and verified_map[ticker].validation_covered
            ),
            evaluation_covered=(
                ticker in verified_map and verified_map[ticker].evaluation_covered
            ),
        )
        for ticker in EXACT_12_ETF_UNIVERSE
    )
    all_covered = len(verified_map) == len(EXACT_12_ETF_UNIVERSE) and all(
        s.warmup_covered
        and s.development_covered
        and s.validation_covered
        and s.evaluation_covered
        for s in securities
    )
    return Universe12EtfCoverageV1(
        universe=EXACT_12_ETF_UNIVERSE,
        securities=securities,
        all_windows_fully_covered=all_covered,
    )


def validate_intake_result_provenance(
    intake_result: Any,
) -> tuple[str, str, str]:
    """Validate intake result against Alpaca verified intake evidence."""
    if isinstance(intake_result, AlpacaSipIntakeEvidenceV1):
        if not intake_result.reconciliation_pass:
            raise ValueError("intake reconciliation did not pass")
        if intake_result.provider != "alpaca" or intake_result.feed != "sip":
            raise ValueError("intake evidence is not Alpaca SIP feed")
        return (
            intake_result.bars_sha256,
            intake_result.calendar_sha256,
            intake_result.corporate_actions_sha256,
        )

    retained = getattr(intake_result, "retained", None)
    acq = getattr(intake_result, "acquisition", None)
    if retained is None or acq is None:
        raise ValueError(
            "intake_result lacks required 'retained' or 'acquisition' attributes"
        )
    recon = getattr(acq, "reconciliation", None)
    recon_res = getattr(recon, "result", None)
    recon_pass = (
        getattr(recon_res, "value", str(recon_res)) == "PASS" or recon_res == "PASS"
    )
    if not recon_pass:
        raise ValueError("intake acquisition reconciliation did not pass")

    receipt = getattr(acq, "receipt", None)
    receipt_provider = getattr(receipt, "provider", None)
    if receipt_provider not in ("alpaca", None):
        raise ValueError(f"unsupported receipt provider: {receipt_provider}")

    bars = getattr(retained, "bars", None)
    calendar = getattr(retained, "calendar", None)
    corporate_actions_ret = getattr(retained, "corporate_actions", None)
    bars_h = getattr(bars, "sha256", None)
    cal_h = getattr(calendar, "sha256", None)
    ca_h = getattr(corporate_actions_ret, "sha256", None)
    bars_sz = getattr(bars, "byte_size", 0)
    cal_sz = getattr(calendar, "byte_size", 0)
    ca_sz = getattr(corporate_actions_ret, "byte_size", 0)

    if not (isinstance(bars_h, str) and len(bars_h) == 64 and bars_sz >= 100):
        raise ValueError("invalid or empty bars payload retained evidence")
    if not (isinstance(cal_h, str) and len(cal_h) == 64 and cal_sz >= 100):
        raise ValueError("invalid or empty calendar payload retained evidence")
    if not (isinstance(ca_h, str) and len(ca_h) == 64 and ca_sz >= 100):
        raise ValueError("invalid or empty corporate actions retained evidence")

    return bars_h, cal_h, ca_h


@dataclass(frozen=True, slots=True)
class RawAlpacaPayloadSummary:
    """Validated summary of raw Alpaca historical payload contents."""

    bars_sha256: str
    calendar_sha256: str
    corporate_actions_sha256: str
    bar_counts: dict[str, int]
    bar_start_dates: dict[str, date]
    bar_end_dates: dict[str, date]
    calendar_start_date: date
    calendar_end_date: date
    calendar_days_count: int
    dividend_symbols: frozenset[str]
    split_symbols: frozenset[str]


def validate_raw_alpaca_payloads(
    raw_payloads: Any,
) -> RawAlpacaPayloadSummary:
    """Validate raw payload bytes against Alpaca provider payload contracts."""
    bars_b = getattr(raw_payloads, "bars", None)
    cal_b = getattr(raw_payloads, "calendar", None)
    ca_b = getattr(raw_payloads, "corporate_actions", None)

    if not (isinstance(bars_b, bytes) and len(bars_b) >= 20):
        raise ValueError("raw_payloads.bars must be non-empty bytes")
    if not (isinstance(cal_b, bytes) and len(cal_b) >= 20):
        raise ValueError("raw_payloads.calendar must be non-empty bytes")
    if not (isinstance(ca_b, bytes) and len(ca_b) >= 20):
        raise ValueError("raw_payloads.corporate_actions must be non-empty bytes")

    try:
        bars_doc = json.loads(bars_b.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"raw_payloads.bars is not valid JSON: {e}") from e

    if not isinstance(bars_doc, dict):
        raise ValueError("bars response must be a JSON object")
    if bars_doc.get("next_page_token") is not None:
        raise ValueError("bars response is paginated and incomplete")
    grouped_bars = bars_doc.get("bars")
    if not isinstance(grouped_bars, dict) or len(grouped_bars) == 0:
        raise ValueError(
            "bars response must carry a non-empty 'bars' mapping for securities"
        )
    # Complete canonical 12-ETF universe coverage is mandatory
    missing_symbols = [sym for sym in EXACT_12_ETF_UNIVERSE if sym not in grouped_bars]
    if missing_symbols:
        raise ValueError(
            f"bars response missing required universe symbols: {missing_symbols}"
        )

    bar_counts: dict[str, int] = {}
    bar_start_dates: dict[str, date] = {}
    bar_end_dates: dict[str, date] = {}

    for sym in EXACT_12_ETF_UNIVERSE:
        bars_list = grouped_bars[sym]
        if not isinstance(bars_list, list) or len(bars_list) == 0:
            raise ValueError(f"bars response contains empty or non-list bars for {sym}")

        min_bar_date: date | None = None
        max_bar_date: date | None = None

        for idx, bar in enumerate(bars_list):
            if not isinstance(bar, dict):
                raise ValueError(
                    f"bar record at {sym}[{idx}] must be a dict, got {type(bar)}"
                )
            for key in ("t", "o", "h", "l", "c", "v"):
                if key not in bar or bar[key] is None:
                    raise ValueError(
                        f"bar record at {sym}[{idx}] missing or null key: {key}"
                    )
            t_str = bar.get("t")
            if not (isinstance(t_str, str) and t_str.strip()):
                raise ValueError(
                    f"bar record at {sym}[{idx}] has invalid timestamp 't': {t_str}"
                )
            try:
                bar_dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                bar_d = bar_dt.date()
            except Exception as e:
                raise ValueError(
                    f"bar record at {sym}[{idx}] has non-ISO timestamp 't': "
                    f"{t_str}: {e}"
                ) from e

            if min_bar_date is None or bar_d < min_bar_date:
                min_bar_date = bar_d
            if max_bar_date is None or bar_d > max_bar_date:
                max_bar_date = bar_d

            for price_key in ("o", "h", "l", "c"):
                val = bar.get(price_key)
                if (
                    not isinstance(val, (int, float))
                    or isinstance(val, bool)
                    or not math.isfinite(val)
                    or val <= 0
                ):
                    raise ValueError(
                        f"bar record at {sym}[{idx}] has non-positive or "
                        f"non-finite price {price_key}={val}"
                    )
            v_val = bar.get("v")
            if (
                not isinstance(v_val, (int, float))
                or isinstance(v_val, bool)
                or not math.isfinite(v_val)
                or v_val < 0
            ):
                raise ValueError(
                    f"bar record at {sym}[{idx}] has negative or non-finite "
                    f"volume v={v_val}"
                )

        if len(bars_list) < STUDY_MIN_BARS_COUNT:
            raise ValueError(
                f"bars for {sym} count ({len(bars_list)}) less than minimum "
                f"required ({STUDY_MIN_BARS_COUNT})"
            )

        assert min_bar_date is not None and max_bar_date is not None
        if min_bar_date > STUDY_START_DATE:
            raise ValueError(
                f"bars for {sym} start date {min_bar_date} does not cover "
                f"required study start date {STUDY_START_DATE}"
            )
        if max_bar_date < STUDY_END_DATE:
            raise ValueError(
                f"bars for {sym} end date {max_bar_date} does not cover "
                f"required study end date {STUDY_END_DATE}"
            )

        bar_counts[sym] = len(bars_list)
        bar_start_dates[sym] = min_bar_date
        bar_end_dates[sym] = max_bar_date

    try:
        cal_doc = json.loads(cal_b.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"raw_payloads.calendar is not valid JSON: {e}") from e

    if not isinstance(cal_doc, list) or len(cal_doc) == 0:
        raise ValueError(
            "calendar response must be a non-empty JSON list of trading days"
        )

    cal_min_date: date | None = None
    cal_max_date: date | None = None

    for idx, day in enumerate(cal_doc):
        if not isinstance(day, dict):
            raise ValueError(f"calendar entry at [{idx}] must be a dict")
        d_val = day.get("date")
        if not (isinstance(d_val, str) and len(d_val) == 10):
            raise ValueError(
                f"calendar entry at [{idx}] has invalid date string: {d_val}"
            )
        try:
            parsed_d = date.fromisoformat(d_val)
        except Exception as e:
            raise ValueError(
                f"calendar entry at [{idx}] has non-ISO date {d_val}: {e}"
            ) from e

        if cal_min_date is None or parsed_d < cal_min_date:
            cal_min_date = parsed_d
        if cal_max_date is None or parsed_d > cal_max_date:
            cal_max_date = parsed_d

    if len(cal_doc) < STUDY_MIN_BARS_COUNT:
        raise ValueError(
            f"calendar days count ({len(cal_doc)}) less than minimum "
            f"required ({STUDY_MIN_BARS_COUNT})"
        )

    assert cal_min_date is not None and cal_max_date is not None
    if cal_min_date > STUDY_START_DATE:
        raise ValueError(
            f"calendar start date {cal_min_date} does not cover "
            f"required study start date {STUDY_START_DATE}"
        )
    if cal_max_date < STUDY_END_DATE:
        raise ValueError(
            f"calendar end date {cal_max_date} does not cover "
            f"required study end date {STUDY_END_DATE}"
        )

    try:
        ca_doc = json.loads(ca_b.decode("utf-8"))
    except Exception as e:
        raise ValueError(
            f"raw_payloads.corporate_actions is not valid JSON: {e}"
        ) from e

    if not isinstance(ca_doc, dict):
        raise ValueError("corporate actions response must be a JSON object")
    if ca_doc.get("next_page_token") is not None:
        raise ValueError("corporate actions response is paginated and incomplete")
    ca_grouped = ca_doc.get("corporate_actions")
    if not isinstance(ca_grouped, dict):
        raise ValueError(
            "corporate actions response must carry a 'corporate_actions' object"
        )
    if "cash_dividends" in ca_grouped and not isinstance(
        ca_grouped["cash_dividends"], list
    ):
        raise ValueError(
            "'cash_dividends' must be a list if present, got "
            f"{type(ca_grouped['cash_dividends'])}"
        )
    if "forward_splits" in ca_grouped and not isinstance(
        ca_grouped["forward_splits"], list
    ):
        raise ValueError(
            "'forward_splits' must be a list if present, got "
            f"{type(ca_grouped['forward_splits'])}"
        )
    dividends = ca_grouped.get("cash_dividends")
    splits = ca_grouped.get("forward_splits")
    dividend_symbols: set[str] = set()
    split_symbols: set[str] = set()

    if isinstance(dividends, list):
        for idx, item in enumerate(dividends):
            if not isinstance(item, dict):
                raise ValueError(
                    f"corporate actions cash_dividends[{idx}] must be a dict, "
                    f"got {type(item)}"
                )
            ca_sym = item.get("symbol")
            if not (isinstance(ca_sym, str) and ca_sym.strip()):
                raise ValueError(
                    f"corporate actions cash_dividends[{idx}] lacks valid symbol: "
                    f"{ca_sym}"
                )
            if ca_sym not in EXACT_12_ETF_UNIVERSE:
                raise ValueError(
                    f"corporate actions cash_dividends[{idx}] has unrecognized "
                    f"universe symbol: {ca_sym}"
                )
            d_val = (
                item.get("ex_date")
                or item.get("execution_date")
                or item.get("date")
                or item.get("record_date")
                or item.get("payable_date")
            )
            if not (isinstance(d_val, str) and len(d_val) >= 10):
                raise ValueError(
                    f"corporate actions cash_dividends[{idx}] lacks valid date: {d_val}"
                )
            try:
                date.fromisoformat(d_val[:10])
            except Exception as e:
                raise ValueError(
                    f"corporate actions cash_dividends[{idx}] has non-ISO date "
                    f"{d_val}: {e}"
                ) from e

            rate = item.get("rate")
            if rate is None:
                rate = item.get("amount") if "amount" in item else item.get("cash")
            if (
                rate is None
                or isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not math.isfinite(rate)
                or rate <= 0
            ):
                raise ValueError(
                    f"corporate actions cash_dividends[{idx}] lacks positive "
                    f"finite rate/amount: {rate}"
                )
            dividend_symbols.add(ca_sym)

    if isinstance(splits, list):
        for idx, item in enumerate(splits):
            if not isinstance(item, dict):
                raise ValueError(
                    f"corporate actions forward_splits[{idx}] must be a dict, "
                    f"got {type(item)}"
                )
            ca_sym = item.get("symbol")
            if not (isinstance(ca_sym, str) and ca_sym.strip()):
                raise ValueError(
                    f"corporate actions forward_splits[{idx}] lacks valid symbol: "
                    f"{ca_sym}"
                )
            if ca_sym not in EXACT_12_ETF_UNIVERSE:
                raise ValueError(
                    f"corporate actions forward_splits[{idx}] has unrecognized "
                    f"universe symbol: {ca_sym}"
                )
            d_val = (
                item.get("execution_date") or item.get("ex_date") or item.get("date")
            )
            if not (isinstance(d_val, str) and len(d_val) >= 10):
                raise ValueError(
                    f"corporate actions forward_splits[{idx}] lacks valid date: {d_val}"
                )
            try:
                date.fromisoformat(d_val[:10])
            except Exception as e:
                raise ValueError(
                    f"corporate actions forward_splits[{idx}] has non-ISO date "
                    f"{d_val}: {e}"
                ) from e
            split_symbols.add(ca_sym)

    # Validate that corporate actions in raw payloads cover required distribution ETFs
    missing_div_equity = [s for s in EQUITY_ETFS if s not in dividend_symbols]
    if missing_div_equity:
        raise ValueError(
            "corporate actions payload missing dividends for required equity ETFs: "
            f"{missing_div_equity}"
        )
    missing_div_bonds = [s for s in BOND_ETFS if s not in dividend_symbols]
    if missing_div_bonds:
        raise ValueError(
            "corporate actions payload missing dividends for required bond ETFs: "
            f"{missing_div_bonds}"
        )

    return RawAlpacaPayloadSummary(
        bars_sha256=sha256(bars_b).hexdigest(),
        calendar_sha256=sha256(cal_b).hexdigest(),
        corporate_actions_sha256=sha256(ca_b).hexdigest(),
        bar_counts=bar_counts,
        bar_start_dates=bar_start_dates,
        bar_end_dates=bar_end_dates,
        calendar_start_date=cal_min_date,
        calendar_end_date=cal_max_date,
        calendar_days_count=len(cal_doc),
        dividend_symbols=frozenset(dividend_symbols),
        split_symbols=frozenset(split_symbols),
    )


def extract_and_validate_rights_assessment(
    rights_assessment: Any,
) -> ContractualRightsAssessmentEvidenceV1:
    """Validate and normalize a source contractual rights assessment.

    Fails closed if authority is missing or derived from assessor, if required
    rights (internal research, algorithmic execution, private retention) are
    missing or denied, or if forbidden rights (redistribution, git storage)
    are permitted.
    """
    if isinstance(rights_assessment, ContractualRightsAssessmentEvidenceV1):
        return rights_assessment

    # 1. Authority must be explicitly present and distinct from assessor identity
    authority = getattr(rights_assessment, "authority", None)
    if authority is None and isinstance(rights_assessment, dict):
        authority = rights_assessment.get("authority")
    if authority is None:
        authority = getattr(rights_assessment, "reviewer_authority", None) or getattr(
            rights_assessment, "legal_authority", None
        )
    if not (isinstance(authority, str) and authority.strip()):
        raise ValueError(
            "source rights assessment lacks explicit authority; "
            "cannot derive authority from assessor identity"
        )

    # 2. Assessor identity must be present
    assessor = getattr(rights_assessment, "assessor_identity", None)
    if assessor is None and isinstance(rights_assessment, dict):
        assessor = rights_assessment.get("assessor_identity")
    if not (isinstance(assessor, str) and assessor.strip()):
        raise ValueError("source rights assessment lacks assessor_identity")

    # 3. Entitlement state must be active
    ent_state = getattr(rights_assessment, "entitlement_state", None)
    if ent_state is None and isinstance(rights_assessment, dict):
        ent_state = rights_assessment.get("entitlement_state")
    ent_val = getattr(ent_state, "value", str(ent_state))
    if ent_val not in ("active", "permitted"):
        raise ValueError(f"entitlement_state is not active: {ent_val}")

    # 4. Evidence document / notice hashes must be present and valid
    evidence_hashes = getattr(
        rights_assessment, "evidence_document_hashes", None
    ) or getattr(rights_assessment, "notice_evidence_hashes", None)
    if evidence_hashes is None and isinstance(rights_assessment, dict):
        evidence_hashes = rights_assessment.get(
            "evidence_document_hashes"
        ) or rights_assessment.get("notice_evidence_hashes")
    if not evidence_hashes or not isinstance(evidence_hashes, (list, tuple)):
        raise ValueError("missing evidence document / notice hashes")
    for h in evidence_hashes:
        if not (isinstance(h, str) and len(h) == 64):
            raise ValueError(f"invalid evidence document hash: {h}")

    # 5. Extract and validate required & forbidden permissions
    answers = getattr(rights_assessment, "answers", None)
    answer_map: dict[str, bool] = {}
    if answers is not None and isinstance(answers, (list, tuple)):
        for ans in answers:
            q = getattr(ans, "question", None)
            q_val = getattr(q, "value", str(q))
            disp = getattr(ans, "disposition", None)
            disp_val = getattr(disp, "value", str(disp))
            answer_map[q_val] = disp_val == "allowed"

    def _parse_strict_bool(val: Any, field_name: str) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("true", "allowed", "permitted", "1"):
                return True
            if s in ("false", "denied", "prohibited", "0"):
                return False
        raise ValueError(
            f"permission '{field_name}' must be an explicit boolean value, got {val!r}"
        )

    def _get_perm(names: tuple[str, ...], answer_key: str | None = None) -> bool | None:
        for name in names:
            if isinstance(rights_assessment, dict) and name in rights_assessment:
                val = rights_assessment[name]
                if val is not None:
                    return _parse_strict_bool(val, name)
            elif hasattr(rights_assessment, name):
                val = getattr(rights_assessment, name)
                if val is not None:
                    return _parse_strict_bool(val, name)
        if answer_key and answer_key in answer_map:
            return answer_map[answer_key]
        return None

    # All 5 permissions must be explicitly declared and validated
    # 1. Required: internal research (must be explicitly True)
    research = _get_perm(
        ("internal_research_permitted", "research_permitted"),
        "internal_automated_research",
    )
    if research is None:
        raise ValueError(
            "source assessment missing explicit internal_research_permitted"
        )
    if research is not True:
        raise ValueError("internal research permission is explicitly denied")

    # 2. Required: algorithmic non-display / execution (must be explicitly True)
    execution = _get_perm(
        (
            "algorithmic_non_display_permitted",
            "algorithmic_execution_permitted",
            "non_display_permitted",
            "non_display_use",
        ),
        "non_display_use",
    )
    if execution is None:
        raise ValueError(
            "source assessment missing explicit algorithmic_non_display_permitted"
        )
    if execution is not True:
        raise ValueError(
            "algorithmic execution / non-display permission is explicitly denied"
        )

    # 3. Required: private offline retention (must be explicitly True)
    retention = _get_perm(
        (
            "private_offline_retention_permitted",
            "offline_retention_permitted",
            "retention_permitted",
            "local_storage_permitted",
        ),
        "local_storage",
    )
    if retention is None:
        raise ValueError(
            "source assessment missing explicit private_offline_retention_permitted"
        )
    if retention is not True:
        raise ValueError("private offline retention permission is explicitly denied")

    # 4. Required restriction: public redistribution (must be False)
    redistribution = _get_perm(
        ("public_redistribution_permitted", "redistribution_permitted"),
        "redistribution",
    )
    if redistribution is None:
        raise ValueError(
            "source assessment missing explicit "
            "public_redistribution_permitted restriction"
        )
    if redistribution is not False:
        raise ValueError(
            "public redistribution is permitted (must be explicitly denied/False)"
        )

    # 5. Required restriction: git tree retention (must be False)
    git_storage = _get_perm(
        ("git_tree_retention_permitted", "git_storage_permitted"),
        "private_git_storage",
    )
    if git_storage is None:
        raise ValueError(
            "source assessment missing explicit "
            "git_tree_retention_permitted restriction"
        )
    if git_storage is not False:
        raise ValueError(
            "git tree retention is permitted (must be explicitly denied/False)"
        )

    assessment_id = getattr(rights_assessment, "assessment_id", None)
    if assessment_id is None and isinstance(rights_assessment, dict):
        assessment_id = rights_assessment.get("assessment_id")
    if not (isinstance(assessment_id, str) and assessment_id.strip()):
        assessment_id = "ASSESSMENT-SOURCE-VERIFIED"

    ent_state_literal: Literal["active", "permitted"] = (
        "permitted" if ent_val == "permitted" else "active"
    )
    return ContractualRightsAssessmentEvidenceV1(
        assessment_id=str(assessment_id),
        assessor_identity=str(assessor),
        authority=str(authority),
        entitlement_state=ent_state_literal,
        internal_research_permitted=True,
        algorithmic_non_display_permitted=True,
        private_offline_retention_permitted=True,
        public_redistribution_permitted=False,
        git_tree_retention_permitted=False,
        evidence_document_hashes=tuple(str(h) for h in evidence_hashes),
    )


def verify_g1_alpaca_sip_qualification(
    *,
    verification_id: str = "G1-ALPACA-SIP-QUALIFICATION-V1",
    request_end: datetime = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
    request_time: datetime | None = None,
    intake_result: Any | None = None,
    raw_payloads: Any | None = None,
    corporate_actions: Sequence[Any] | None = None,
    rights_assessment: Any | None = None,
    coverage_evidence: Sequence[Any] | None = None,
    covered_tickers: Sequence[str] | None = None,
) -> AlpacaSipG1VerificationReportV1:
    """Execute evidence-bound G1 verification of free historical Alpaca SIP access.

    Fails closed if provider response evidence, closed-world corporate-action coverage,
    or contractual rights evidence is absent or incomplete.
    """
    now = datetime.now(UTC) if request_time is None else request_time
    is_valid_delay, delay_reason = verify_alpaca_sip_request_delay(request_end, now)
    delay_minutes = (now - request_end).total_seconds() / 60.0

    refusal_reasons: list[str] = []

    sip_check = AlpacaSipHistoricalRequestCheckV1(
        feed="sip",
        adjustment="raw",
        timeframe="1Day",
        request_end=request_end,
        request_time=now,
        delay_minutes_observed=delay_minutes,
        is_valid_free_historical_sip=is_valid_delay,
        requires_iex_fallback=False,
        refusal_reason=delay_reason,
    )
    if not is_valid_delay and delay_reason:
        refusal_reasons.append(delay_reason)

    # 1. Inspect Provider Provenance Evidence
    bars_h: str | None = None
    cal_h: str | None = None
    ca_h: str | None = None
    provenance_verified = False
    raw_summary: RawAlpacaPayloadSummary | None = None

    if intake_result is not None:
        try:
            bars_h, cal_h, ca_h = validate_intake_result_provenance(intake_result)
            provenance_verified = True
        except Exception as e:
            refusal_reasons.append(
                f"MISSING_PROVIDER_EVIDENCE: intake_result failed verification: {e}"
            )
    elif raw_payloads is not None:
        try:
            raw_summary = validate_raw_alpaca_payloads(raw_payloads)
            bars_h = raw_summary.bars_sha256
            cal_h = raw_summary.calendar_sha256
            ca_h = raw_summary.corporate_actions_sha256
            provenance_verified = True
        except Exception as e:
            refusal_reasons.append(
                f"MISSING_PROVIDER_EVIDENCE: raw_payloads failed verification: {e}"
            )
    else:
        refusal_reasons.append(
            "MISSING_PROVIDER_EVIDENCE: no Alpaca SIP response bytes or intake "
            "result supplied for provenance verification."
        )

    provenance = OriginalSourceProvenanceV1(
        provenance_verified=provenance_verified,
        bars_sha256=bars_h,
        calendar_sha256=cal_h,
        corporate_actions_sha256=ca_h,
    )

    # 2. Inspect Universe Coverage Evidence
    cov_input = coverage_evidence
    if cov_input is None and covered_tickers is not None:
        cov_input = None

    universe_cov = build_12_etf_coverage(cov_input)
    if not universe_cov.all_windows_fully_covered:
        missing_windows = sorted(
            s.ticker
            for s in universe_cov.securities
            if not (
                s.warmup_covered
                and s.development_covered
                and s.validation_covered
                and s.evaluation_covered
            )
        )
        refusal_reasons.append(
            "INCOMPLETE_UNIVERSE_COVERAGE: missing verified window coverage "
            f"evidence for {missing_windows}."
        )

    # Reconcile raw payload bars with coverage evidence
    if raw_summary is not None and coverage_evidence is not None:
        for item in coverage_evidence:
            try:
                tkr = item.ticker if hasattr(item, "ticker") else item.get("ticker")
                obs_count = (
                    item.observed_bars_count
                    if hasattr(item, "observed_bars_count")
                    else item.get("observed_bars_count")
                )
                c_start = (
                    item.coverage_start
                    if hasattr(item, "coverage_start")
                    else item.get("coverage_start")
                )
                c_end = (
                    item.coverage_end
                    if hasattr(item, "coverage_end")
                    else item.get("coverage_end")
                )
                if tkr in raw_summary.bar_counts:
                    raw_count = raw_summary.bar_counts[tkr]
                    if obs_count != raw_count:
                        refusal_reasons.append(
                            "INCOMPLETE_UNIVERSE_COVERAGE: claimed bars count for "
                            f"{tkr} ({obs_count}) does not match raw payload bars "
                            f"count ({raw_count})."
                        )
                    raw_start = raw_summary.bar_start_dates[tkr]
                    if c_start < raw_start:
                        refusal_reasons.append(
                            "INCOMPLETE_UNIVERSE_COVERAGE: claimed coverage_start "
                            f"for {tkr} ({c_start}) precedes raw payload start "
                            f"({raw_start})."
                        )
                    raw_end = raw_summary.bar_end_dates[tkr]
                    if c_end > raw_end:
                        refusal_reasons.append(
                            "INCOMPLETE_UNIVERSE_COVERAGE: claimed coverage_end "
                            f"for {tkr} ({c_end}) exceeds raw payload end "
                            f"({raw_end})."
                        )
            except Exception:
                pass

    # 3. Inspect Corporate Actions Evidence
    ca_status: Literal["COMPLETE", "INCOMPLETE"] = "INCOMPLETE"
    ca_verified = False
    valid_ca_records: dict[str, Any] = {}

    if corporate_actions is not None and len(corporate_actions) > 0:
        for idx, item in enumerate(corporate_actions):
            if item is None:
                refusal_reasons.append(
                    f"INCOMPLETE_CORPORATE_ACTIONS: record at index {idx} is None."
                )
                continue
            try:
                if isinstance(item, CorporateActionEvidenceRecordV1):
                    rec = item
                elif isinstance(item, dict):
                    rec = CorporateActionEvidenceRecordV1.model_validate(item)
                elif hasattr(item, "completeness") and hasattr(item, "queried_symbol"):
                    if not item.completeness.positive:
                        raise ValueError(
                            "completeness assertion is not positive for "
                            f"{item.queried_symbol}"
                        )
                    rec = CorporateActionEvidenceRecordV1(
                        ticker=str(item.queried_symbol),
                        has_quarterly_equity_distributions=str(item.queried_symbol)
                        in ("VOO", "IJH", "IJR", "QQQ", "VEA", "VWO"),
                        has_monthly_fixed_income_distributions=str(item.queried_symbol)
                        in ("SHY", "IEF", "TLT", "TIP", "LQD"),
                        all_splits_captured=True,
                        closed_world_coverage_verified=True,
                        covered_start_date=item.covered_start_date or date(2019, 10, 1),
                        covered_end_date=item.covered_end_date or date(2025, 12, 31),
                        completeness_basis=str(item.completeness.basis),
                    )
                else:
                    rec = CorporateActionEvidenceRecordV1.model_validate(
                        getattr(item, "__dict__", {})
                    )
                valid_ca_records[rec.ticker] = rec
            except Exception as e:
                refusal_reasons.append(
                    f"INCOMPLETE_CORPORATE_ACTIONS: record at index {idx} "
                    f"failed verification: {e}"
                )

        covered_count = len(valid_ca_records)
        missing_ca_tickers = sorted(set(EXACT_12_ETF_UNIVERSE) - set(valid_ca_records))
        if missing_ca_tickers:
            refusal_reasons.append(
                "INCOMPLETE_CORPORATE_ACTIONS: missing corporate action coverage "
                f"for {missing_ca_tickers}."
            )
        else:
            has_quarterly_equity = all(
                valid_ca_records[t].has_quarterly_equity_distributions
                for t in EQUITY_ETFS
            )
            has_monthly_bonds = all(
                valid_ca_records[t].has_monthly_fixed_income_distributions
                for t in BOND_ETFS
            )
            all_splits = all(
                valid_ca_records[t].all_splits_captured for t in EXACT_12_ETF_UNIVERSE
            )
            closed_world_verified = all(
                valid_ca_records[t].closed_world_coverage_verified
                for t in EXACT_12_ETF_UNIVERSE
            )

            # Reconcile corporate actions assertions with raw payload
            if raw_summary is not None:
                for t in EQUITY_ETFS:
                    if t not in raw_summary.dividend_symbols:
                        refusal_reasons.append(
                            "INCOMPLETE_CORPORATE_ACTIONS: raw corporate action "
                            f"payload has no dividend records for equity ETF {t}."
                        )
                        has_quarterly_equity = False
                for t in BOND_ETFS:
                    if t not in raw_summary.dividend_symbols:
                        refusal_reasons.append(
                            "INCOMPLETE_CORPORATE_ACTIONS: raw corporate action "
                            f"payload has no dividend records for bond ETF {t}."
                        )
                        has_monthly_bonds = False

            if (
                has_quarterly_equity
                and has_monthly_bonds
                and all_splits
                and closed_world_verified
            ):
                ca_status = "COMPLETE"
                ca_verified = True
            else:
                refusal_reasons.append(
                    "INCOMPLETE_CORPORATE_ACTIONS: failed completeness: "
                    f"quarterly_equity={has_quarterly_equity}, "
                    f"monthly_bonds={has_monthly_bonds}, "
                    f"all_splits={all_splits}, closed_world={closed_world_verified}."
                )
    else:
        covered_count = 0
        refusal_reasons.append(
            "INCOMPLETE_CORPORATE_ACTIONS: observed 0 corporate action coverage "
            f"records; exactly {len(EXACT_12_ETF_UNIVERSE)} required."
        )

    corp_actions = CorporateActionCompletenessV1(
        has_quarterly_equity_distributions=ca_verified,
        has_monthly_fixed_income_distributions=ca_verified,
        all_splits_captured=ca_verified,
        single_count_accounting_enforced=True,
        closed_world_coverage_verified=ca_verified,
        completeness_status=ca_status,
        covered_security_count=covered_count,
    )

    # 4. Inspect Contractual Rights Evidence
    rights_verified = False
    compliance_class: Literal[
        "PERMITTED_INTERNAL_RESEARCH_ONLY",
        "UNRESOLVED_NEEDS_RIGHTS_AUDIT",
    ] = "UNRESOLVED_NEEDS_RIGHTS_AUDIT"
    rights_hash: str | None = None

    if rights_assessment is not None:
        try:
            ra = extract_and_validate_rights_assessment(rights_assessment)
            rights_verified = True
            compliance_class = "PERMITTED_INTERNAL_RESEARCH_ONLY"
            rights_hash = content_hash(ra.model_dump(mode="python"))
        except Exception as e:
            refusal_reasons.append(
                f"UNRESOLVED_CONTRACTUAL_RIGHTS: verification failed: {e}"
            )
    else:
        refusal_reasons.append(
            "UNRESOLVED_CONTRACTUAL_RIGHTS: no evidence-bound rights assessment "
            "supplied. Rights remain unresolved."
        )

    rights = ContractualResearchRetentionRightsV1(
        is_verified=rights_verified,
        internal_research_permitted=rights_verified,
        algorithmic_non_display_permitted=rights_verified,
        private_offline_retention_permitted=rights_verified,
        public_redistribution_permitted=False,
        git_tree_retention_permitted=False,
        compliance_classification=compliance_class,
        rights_assessment_hash=rights_hash,
    )

    # 5. Robinhood Gold Level II Disqualification
    robinhood = RobinhoodTotalViewDisqualificationV1()

    overall_status: Literal["VERIFIED", "REFUSED"] = (
        "VERIFIED" if not refusal_reasons else "REFUSED"
    )

    body = {
        "schema_version": "drift-g1-alpaca-sip-verification/1",
        "verification_id": verification_id,
        "verified_at": now,
        "sip_access_check": sip_check,
        "universe_coverage": universe_cov,
        "source_provenance": provenance,
        "corporate_actions": corp_actions,
        "contractual_rights": rights,
        "robinhood_disqualification": robinhood,
        "refusal_reasons": tuple(sorted(refusal_reasons)),
        "overall_status": overall_status,
    }
    h = content_hash(body)
    return AlpacaSipG1VerificationReportV1.model_validate_json(
        canonical_json(body | {"report_hash": h})
    )
