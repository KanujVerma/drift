"""Unit tests for Drift Stage 1 (G1) free historical Alpaca SIP verification."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
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
    AlpacaSipIntakeEvidenceV1,
    ContractualResearchRetentionRightsV1,
    ContractualRightsAssessmentEvidenceV1,
    CorporateActionCompletenessV1,
    CorporateActionEvidenceRecordV1,
    OriginalSourceProvenanceV1,
    RobinhoodTotalViewDisqualificationV1,
    SecurityHistoricalCoverageEvidenceV1,
    SecurityHistoricalCoverageV1,
    Universe12EtfCoverageV1,
    build_12_etf_coverage,
    create_mock_alpaca_sip_evidence_fixtures,
    verify_alpaca_sip_request_delay,
    verify_g1_alpaca_sip_qualification,
)

FIXED_NOW = datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)


def make_mock_evidence() -> tuple[
    AlpacaSipIntakeEvidenceV1,
    tuple[SecurityHistoricalCoverageEvidenceV1, ...],
    tuple[CorporateActionEvidenceRecordV1, ...],
    ContractualRightsAssessmentEvidenceV1,
]:
    return create_mock_alpaca_sip_evidence_fixtures()


def test_free_historical_sip_access_verification_fails_closed_without_evidence() -> (
    None
):
    """Calling verification without evidence fails closed and returns REFUSED."""
    request_end = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    report = verify_g1_alpaca_sip_qualification(
        request_end=request_end,
        request_time=FIXED_NOW,
    )
    assert report.overall_status == "REFUSED"
    assert len(report.refusal_reasons) == 4
    assert any("MISSING_PROVIDER_EVIDENCE" in r for r in report.refusal_reasons)
    assert any("UNRESOLVED_CONTRACTUAL_RIGHTS" in r for r in report.refusal_reasons)
    assert any("INCOMPLETE_CORPORATE_ACTIONS" in r for r in report.refusal_reasons)
    assert any("INCOMPLETE_UNIVERSE_COVERAGE" in r for r in report.refusal_reasons)


def test_sol_adversarial_reproduction_refuses_arbitrary_objects() -> None:
    """Sol Review Round 2 blocker regression: arbitrary objects must be refused."""
    report = verify_g1_alpaca_sip_qualification(
        intake_result=object(),
        corporate_actions=[None] * 12,
        rights_assessment=object(),
        covered_tickers=EXACT_12_ETF_UNIVERSE,
    )
    assert report.overall_status == "REFUSED"
    assert len(report.refusal_reasons) >= 4
    assert any("MISSING_PROVIDER_EVIDENCE" in r for r in report.refusal_reasons)
    assert any("INCOMPLETE_CORPORATE_ACTIONS" in r for r in report.refusal_reasons)
    assert any("UNRESOLVED_CONTRACTUAL_RIGHTS" in r for r in report.refusal_reasons)
    assert any("INCOMPLETE_UNIVERSE_COVERAGE" in r for r in report.refusal_reasons)
    assert report.source_provenance.provenance_verified is False
    assert report.corporate_actions.completeness_status == "INCOMPLETE"
    assert report.contractual_rights.is_verified is False
    assert report.universe_coverage.all_windows_fully_covered is False


def test_free_historical_sip_access_verification_passes_with_evidence() -> None:
    """Historical requests ending > 15 minutes in past succeed with evidence."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    request_end = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    report = verify_g1_alpaca_sip_qualification(
        request_end=request_end,
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
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
    assert report.refusal_reasons == ()


def test_verification_refuses_when_provider_evidence_missing() -> None:
    """Refuse verification if provider response / intake evidence is missing."""
    _, cov_ev, ca_records, rights = make_mock_evidence()
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=None,
        raw_payloads=None,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("MISSING_PROVIDER_EVIDENCE" in r for r in report.refusal_reasons)


def test_verification_refuses_when_corporate_actions_incomplete() -> None:
    """Refuse verification if corporate-actions coverage is incomplete (< 12)."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    incomplete_ca = ca_records[:-1]  # Only 11 records
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=incomplete_ca,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("INCOMPLETE_CORPORATE_ACTIONS" in r for r in report.refusal_reasons)


def test_verification_refuses_when_universe_coverage_incomplete() -> None:
    """Refuse verification if 12-ETF coverage is missing a ticker."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    missing_one = cov_ev[:-1]  # Missing last ticker
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=missing_one,
    )
    assert report.overall_status == "REFUSED"
    assert any("INCOMPLETE_UNIVERSE_COVERAGE" in r for r in report.refusal_reasons)


def test_verification_refuses_when_contractual_rights_unresolved() -> None:
    """Refuse verification if contractual rights assessment is absent."""
    intake_res, cov_ev, ca_records, _ = make_mock_evidence()
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=None,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("UNRESOLVED_CONTRACTUAL_RIGHTS" in r for r in report.refusal_reasons)


def test_verification_clock_defaults_to_now() -> None:
    """Default clock must be datetime.now(UTC), not a fixed hardcoded date."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    before = datetime.now(UTC)
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=None,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
    )
    after = datetime.now(UTC)
    req_time = report.sip_access_check.request_time
    assert before <= req_time <= after


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
    cov_empty = build_12_etf_coverage()
    assert cov_empty.universe == EXACT_12_ETF_UNIVERSE
    assert cov_empty.all_windows_fully_covered is False

    _, cov_ev, _, _ = make_mock_evidence()
    cov = build_12_etf_coverage(cov_ev)
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
    _, cov_ev, _, _ = make_mock_evidence()
    cov = build_12_etf_coverage(cov_ev)
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
    _, cov_ev, _, _ = make_mock_evidence()
    cov = build_12_etf_coverage(cov_ev)
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
    _, cov_ev, _, _ = make_mock_evidence()
    cov = build_12_etf_coverage(cov_ev)
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
    prov_default = OriginalSourceProvenanceV1()
    assert prov_default.source_provider == "alpaca"
    assert prov_default.feed_identity == "sip"
    assert prov_default.price_basis == "raw_execution"
    assert prov_default.timezone == "America/New_York"
    assert prov_default.provenance_verified is False

    prov_verified = OriginalSourceProvenanceV1(
        provenance_verified=True,
        bars_sha256="a" * 64,
        calendar_sha256="b" * 64,
        corporate_actions_sha256="c" * 64,
    )
    assert prov_verified.provenance_verified is True


def test_corporate_actions_completeness_verified() -> None:
    """Verify corporate actions completeness and single-count accounting."""
    ca_default = CorporateActionCompletenessV1()
    assert ca_default.completeness_status == "INCOMPLETE"
    assert ca_default.closed_world_coverage_verified is False

    ca_verified = CorporateActionCompletenessV1(
        has_quarterly_equity_distributions=True,
        has_monthly_fixed_income_distributions=True,
        all_splits_captured=True,
        single_count_accounting_enforced=True,
        closed_world_coverage_verified=True,
        completeness_status="COMPLETE",
        covered_security_count=12,
    )
    assert ca_verified.has_quarterly_equity_distributions is True
    assert ca_verified.has_monthly_fixed_income_distributions is True
    assert ca_verified.all_splits_captured is True
    assert ca_verified.single_count_accounting_enforced is True
    assert ca_verified.closed_world_coverage_verified is True
    assert ca_verified.completeness_status == "COMPLETE"


def test_contractual_research_and_retention_rights() -> None:
    """Verify contractual rights: internal research ok, redistribution barred."""
    rights_default = ContractualResearchRetentionRightsV1()
    assert rights_default.is_verified is False
    assert rights_default.compliance_classification == "UNRESOLVED_NEEDS_RIGHTS_AUDIT"

    rights_verified = ContractualResearchRetentionRightsV1(
        is_verified=True,
        internal_research_permitted=True,
        algorithmic_non_display_permitted=True,
        private_offline_retention_permitted=True,
        public_redistribution_permitted=False,
        git_tree_retention_permitted=False,
        compliance_classification="PERMITTED_INTERNAL_RESEARCH_ONLY",
        rights_assessment_hash="d" * 64,
    )
    assert rights_verified.internal_research_permitted is True
    assert rights_verified.algorithmic_non_display_permitted is True
    assert rights_verified.private_offline_retention_permitted is True
    assert rights_verified.public_redistribution_permitted is False
    assert rights_verified.git_tree_retention_permitted is False
    assert (
        rights_verified.compliance_classification == "PERMITTED_INTERNAL_RESEARCH_ONLY"
    )


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


def test_refuses_intake_with_unverified_reconciliation_pass() -> None:
    """Refuse provenance if intake reconciliation did not pass."""
    _, cov_ev, ca_records, rights = make_mock_evidence()
    from types import SimpleNamespace

    fake_res = SimpleNamespace(
        retained=SimpleNamespace(
            bars=SimpleNamespace(sha256="a" * 64, byte_size=100),
            calendar=SimpleNamespace(sha256="b" * 64, byte_size=100),
            corporate_actions=SimpleNamespace(sha256="c" * 64, byte_size=100),
        ),
        acquisition=SimpleNamespace(
            receipt=SimpleNamespace(provider="alpaca"),
            reconciliation=SimpleNamespace(result="FAILED"),
        ),
    )
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=fake_res,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("intake acquisition reconciliation" in r for r in report.refusal_reasons)


def test_refuses_raw_payloads_with_invalid_json() -> None:
    """Refuse provenance if raw payload bytes are not valid JSON objects."""
    _, cov_ev, ca_records, rights = make_mock_evidence()
    from types import SimpleNamespace

    bad_payloads = SimpleNamespace(
        bars=b"not valid json",
        calendar=b"[]",
        corporate_actions=b"[]",
    )
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        raw_payloads=bad_payloads,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("raw_payloads failed verification" in r for r in report.refusal_reasons)


def test_refuses_corporate_actions_when_quarterly_distribution_missing_for_equity() -> (
    None
):
    """Refuse corporate actions if an equity ETF claims no quarterly distributions."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    bad_ca: list[Any] = list(ca_records)
    bad_ca[0] = {
        "ticker": "VOO",
        "has_quarterly_equity_distributions": False,
        "has_monthly_fixed_income_distributions": False,
        "all_splits_captured": True,
        "closed_world_coverage_verified": True,
        "covered_start_date": date(2019, 10, 1),
        "covered_end_date": date(2025, 12, 31),
        "single_count_accounting_enforced": True,
        "completeness_basis": "ALPACA_EXPLORATORY_CLOSED_WORLD_V1",
    }
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=bad_ca,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("EQUITY_ETF_MISSING_QUARTERLY" in r for r in report.refusal_reasons)


def test_refuses_corporate_actions_when_monthly_distribution_missing_for_bond() -> None:
    """Refuse corporate actions if a bond ETF claims no monthly distributions."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    bad_ca: list[Any] = list(ca_records)
    # SHY is index 6
    bad_ca[6] = {
        "ticker": "SHY",
        "has_quarterly_equity_distributions": False,
        "has_monthly_fixed_income_distributions": False,
        "all_splits_captured": True,
        "closed_world_coverage_verified": True,
        "covered_start_date": date(2019, 10, 1),
        "covered_end_date": date(2025, 12, 31),
        "single_count_accounting_enforced": True,
        "completeness_basis": "ALPACA_EXPLORATORY_CLOSED_WORLD_V1",
    }
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=bad_ca,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("BOND_ETF_MISSING_MONTHLY" in r for r in report.refusal_reasons)


def test_refuses_rights_assessment_when_entitlement_not_active() -> None:
    """Refuse rights if entitlement is expired or terminated."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    from types import SimpleNamespace

    expired_rights = SimpleNamespace(
        assessment_id="ASSESSMENT-1",
        assessor_identity="matthew@drift.local",
        entitlement_state="expired",
        notice_evidence_hashes=("e" * 64,),
    )
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=expired_rights,
        coverage_evidence=cov_ev,
    )
    assert report.overall_status == "REFUSED"
    assert any("entitlement_state is not active" in r for r in report.refusal_reasons)


def test_refuses_coverage_when_dates_do_not_span_full_study_window() -> None:
    """Refuse coverage if historical span ends early (e.g. 2024 instead of 2025)."""
    intake_res, cov_ev, ca_records, rights = make_mock_evidence()
    bad_cov: list[Any] = list(cov_ev)
    bad_cov[0] = {
        "ticker": "VOO",
        "warmup_covered": True,
        "development_covered": True,
        "validation_covered": True,
        "evaluation_covered": False,
        "coverage_start": date(2019, 10, 1),
        "coverage_end": date(2024, 12, 31),
        "observed_bars_count": 1200,
    }
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=bad_cov,
    )
    assert report.overall_status == "REFUSED"
    assert any("INCOMPLETE_UNIVERSE_COVERAGE" in r for r in report.refusal_reasons)
