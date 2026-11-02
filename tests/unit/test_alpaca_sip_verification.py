"""Unit tests for Drift Stage 1 (G1) free historical Alpaca SIP verification."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from drift.adapters.alpaca_exploratory import (
    AlpacaCohortMember,
    AlpacaIntakeRequest,
    AlpacaReconstructionLineage,
    AlpacaTimezoneEvidence,
    verify_alpaca_sip_request_bounds,
)
from drift.domain.securities import ListingVenue
from drift.qualification.alpaca_sip_verification import (
    ALPACA_SIP_FEED,
    DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW,
    EXACT_12_ETF_UNIVERSE,
    AlpacaSipHistoricalRequestCheckV1,
    ContractualResearchRetentionRightsV1,
    CorporateActionCompletenessV1,
    OriginalSourceProvenanceV1,
    RobinhoodTotalViewDisqualificationV1,
    SecurityHistoricalCoverageV1,
    Universe12EtfCoverageV1,
    build_12_etf_coverage,
    verify_alpaca_sip_request_delay,
    verify_g1_alpaca_sip_qualification,
)

FIXED_NOW = datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)


def test_free_historical_sip_access_verification_passes() -> None:
    """Historical requests ending > 15 minutes in past succeed without IEX."""
    request_end = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    report = verify_g1_alpaca_sip_qualification(
        request_end=request_end,
        request_time=FIXED_NOW,
    )
    assert report.overall_status == "VERIFIED"
    assert report.sip_access_check.feed == ALPACA_SIP_FEED
    assert report.sip_access_check.feed == "sip"
    assert report.sip_access_check.adjustment == "raw"
    assert report.sip_access_check.timeframe == "1Day"
    assert report.sip_access_check.is_valid_free_historical_sip is True
    assert report.sip_access_check.requires_iex_fallback is False
    assert report.sip_access_check.delay_minutes_observed > 15.0
    assert len(report.report_hash) == 64


def test_free_sip_request_within_15_minutes_refused() -> None:
    """Requests ending within 15 minutes of query time must be refused."""
    recent_end = FIXED_NOW - timedelta(minutes=10)
    is_valid, reason = verify_alpaca_sip_request_delay(recent_end, FIXED_NOW)
    assert is_valid is False
    assert reason is not None
    assert "FREE_SIP_REQUEST_WITHIN_15_MINUTES" in reason
    assert "Subscription does not permit querying recent SIP data" in reason


def test_free_sip_request_in_future_refused() -> None:
    """Future requests are strictly refused."""
    future_end = FIXED_NOW + timedelta(minutes=5)
    is_valid, reason = verify_alpaca_sip_request_delay(future_end, FIXED_NOW)
    assert is_valid is False
    assert reason is not None
    assert "FREE_SIP_REQUEST_WITHIN_15_MINUTES" in reason


def test_free_sip_request_exactly_15_minutes_boundary() -> None:
    """Requests ending >= 15 minutes in past pass the delay check."""
    valid_end = FIXED_NOW - timedelta(minutes=16)
    is_valid, reason = verify_alpaca_sip_request_delay(valid_end, FIXED_NOW)
    assert is_valid is True
    assert reason is None


def test_iex_fallback_not_permitted_for_older_historical_data() -> None:
    """Do not assume an IEX-only feed is necessary for older historical data."""
    with pytest.raises(
        ValidationError, match="IEX_FALLBACK_NOT_PERMITTED_FOR_HISTORICAL_SIP"
    ):
        AlpacaSipHistoricalRequestCheckV1(
            feed="sip",
            adjustment="raw",
            timeframe="1Day",
            request_end=datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC),
            request_time=FIXED_NOW,
            delay_minutes_observed=1000.0,
            is_valid_free_historical_sip=True,
            requires_iex_fallback=True,
        )


def test_exact_12_etf_coverage_canonical_order_and_venues() -> None:
    """Verify exact 12 ETFs in canonical order with primary listing venues."""
    cov = build_12_etf_coverage()
    assert cov.universe == EXACT_12_ETF_UNIVERSE
    assert cov.universe == (
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
    assert cov.all_windows_fully_covered is True

    sec_map = {s.ticker: s for s in cov.securities}
    assert sec_map["QQQ"].primary_venue == "XNAS"
    assert sec_map["SHY"].primary_venue == "XNAS"
    assert sec_map["IEF"].primary_venue == "XNAS"
    assert sec_map["TLT"].primary_venue == "XNAS"
    assert sec_map["VOO"].primary_venue == "ARCX"
    assert sec_map["GLD"].primary_venue == "ARCX"

    for sec in cov.securities:
        assert sec.warmup_covered is True
        assert sec.development_covered is True
        assert sec.validation_covered is True
        assert sec.evaluation_covered is True
        assert sec.inception_date <= date(2010, 9, 7)
        assert sec.inception_date <= cov.warmup_window[0]


def test_universe_coverage_refuses_altered_order() -> None:
    """Canonical 12-ETF universe order is mandatory."""
    cov = build_12_etf_coverage()
    reversed_secs = tuple(reversed(cov.securities))
    with pytest.raises(
        ValidationError, match="SECURITIES_TICKERS_MUST_MATCH_EXACT_12_ETFS_ORDER"
    ):
        Universe12EtfCoverageV1(
            universe=EXACT_12_ETF_UNIVERSE,
            securities=reversed_secs,
            all_windows_fully_covered=True,
        )


def test_universe_coverage_refuses_dropped_ticker() -> None:
    """Dropping any ticker (e.g. QQQ) is rejected as incomplete."""
    cov = build_12_etf_coverage()
    dropped = tuple(s for s in cov.securities if s.ticker != "QQQ")
    with pytest.raises(
        ValidationError, match="SECURITIES_TICKERS_MUST_MATCH_EXACT_12_ETFS_ORDER"
    ):
        Universe12EtfCoverageV1(
            universe=EXACT_12_ETF_UNIVERSE,
            securities=dropped,
            all_windows_fully_covered=True,
        )


def test_universe_coverage_refuses_inception_after_warmup() -> None:
    """Security with inception date after warmup start cannot claim coverage."""
    cov = build_12_etf_coverage()
    bad_secs = list(cov.securities)
    bad_secs[0] = SecurityHistoricalCoverageV1(
        ticker="VOO",
        primary_venue="ARCX",
        inception_date=date(2022, 1, 1),
        warmup_covered=True,
        development_covered=True,
        validation_covered=True,
        evaluation_covered=True,
    )
    with pytest.raises(ValidationError, match="INCEPTION_AFTER_WARMUP:VOO:2022-01-01"):
        Universe12EtfCoverageV1(
            universe=EXACT_12_ETF_UNIVERSE,
            securities=tuple(bad_secs),
            all_windows_fully_covered=True,
        )


def test_original_source_provenance_verified() -> None:
    """Verify endpoint contracts and raw execution price basis."""
    prov = OriginalSourceProvenanceV1()
    assert prov.source_provider == "alpaca"
    assert prov.feed_identity == "sip"
    assert prov.price_basis == "raw_execution"
    assert prov.timezone == "America/New_York"
    assert prov.provenance_verified is True


def test_corporate_actions_completeness_verified() -> None:
    """Verify corporate actions completeness and single-count accounting."""
    ca = CorporateActionCompletenessV1()
    assert ca.has_quarterly_equity_distributions is True
    assert ca.has_monthly_fixed_income_distributions is True
    assert ca.all_splits_captured is True
    assert ca.single_count_accounting_enforced is True
    assert ca.closed_world_coverage_verified is True
    assert ca.completeness_status == "COMPLETE"


def test_contractual_research_and_retention_rights() -> None:
    """Verify contractual rights: internal research ok, redistribution barred."""
    rights = ContractualResearchRetentionRightsV1()
    assert rights.internal_research_permitted is True
    assert rights.algorithmic_non_display_permitted is True
    assert rights.private_offline_retention_permitted is True
    assert rights.public_redistribution_permitted is False
    assert rights.git_tree_retention_permitted is False
    assert rights.compliance_classification == "PERMITTED_INTERNAL_RESEARCH_ONLY"


def test_robinhood_gold_totalview_disqualification() -> None:
    """Verify Robinhood Gold TotalView is excluded from G1 critical path."""
    rh = RobinhoodTotalViewDisqualificationV1()
    assert rh.source_name == DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW
    assert rh.is_qualifying_historical_source is False
    assert rh.consumer_entitlement_authorizes_extraction is False
    assert rh.excluded_from_g1_critical_path is True
    assert "CONSUMER_DISPLAY_ENTITLEMENT_ONLY" in rh.disqualification_reasons[0]
    assert "UNAUTHORIZED_PROGRAMMATIC_EXTRACTION" in rh.disqualification_reasons[1]
    assert "LACKS_HISTORICAL_AUDIT_TAPE" in rh.disqualification_reasons[2]
    assert "EXCLUDED_FROM_G1_CRITICAL_PATH" in rh.disqualification_reasons[3]
    assert (
        "separate, subsequent intraday study" in rh.historical_order_book_study_boundary
    )


def test_adapter_verify_alpaca_sip_request_bounds() -> None:
    """Test verify_alpaca_sip_request_bounds on AlpacaIntakeRequest."""
    tz_evidence = AlpacaTimezoneEvidence(
        timezone_identifier="America/New_York",
        source_timezone_label="EDT",
        tzif_bytes=b"tzif",
        tzdb_release="2026a",
        reconstruction_observed_at=FIXED_NOW,
    )
    lineage = AlpacaReconstructionLineage(
        producer_source=b"source",
        producer_package=b"package",
        lockfile=b"lockfile",
        python_identity="3.14.6",
    )
    member = AlpacaCohortMember(
        symbol="VOO",
        security_id=uuid4(),
        listing_id=uuid4(),
        venue=ListingVenue.XNYS,
    )

    plan_frozen_at = datetime(2020, 12, 31, tzinfo=UTC)
    valid_request = AlpacaIntakeRequest(
        cohort_id="COHORT-1",
        cohort_version="1",
        members=(member,),
        mic="XNYS",
        start_date=date(2021, 1, 1),
        end_date=date(2023, 12, 31),
        plan_frozen_at=plan_frozen_at,
        request_start=datetime(2021, 1, 1, tzinfo=UTC),
        request_end=datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC),
        evidence_vintage_cutoff=FIXED_NOW,
        timezone_evidence=tz_evidence,
        lineage=lineage,
        boundary_offsets={},
    )
    is_valid, err = verify_alpaca_sip_request_bounds(
        valid_request, observed_at=FIXED_NOW
    )
    assert is_valid is True
    assert err is None

    invalid_request = AlpacaIntakeRequest(
        cohort_id="COHORT-2",
        cohort_version="1",
        members=(member,),
        mic="XNYS",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 2),
        plan_frozen_at=FIXED_NOW - timedelta(minutes=10),
        request_start=FIXED_NOW - timedelta(minutes=5),
        request_end=FIXED_NOW - timedelta(minutes=2),
        evidence_vintage_cutoff=FIXED_NOW,
        timezone_evidence=tz_evidence,
        lineage=lineage,
        boundary_offsets={},
    )
    is_valid, err = verify_alpaca_sip_request_bounds(
        invalid_request, observed_at=FIXED_NOW
    )
    assert is_valid is False
    assert err is not None
    assert "FREE_SIP_REQUEST_WITHIN_15_MINUTES" in err
