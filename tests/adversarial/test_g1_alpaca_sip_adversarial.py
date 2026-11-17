"""Adversarial tests for Stage 1 (G1) market data qualification."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from drift.qualification.alpaca_sip_verification import (
    DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW,
    EXACT_12_ETF_UNIVERSE,
    AlpacaSipHistoricalRequestCheckV1,
    ContractualResearchRetentionRightsV1,
    Universe12EtfCoverageV1,
    build_12_etf_coverage,
    verify_alpaca_sip_request_delay,
    verify_g1_alpaca_sip_qualification,
)
from drift.qualification.stage1_market_admission import (
    Stage1MarketDataAdmissionArtifactV1,
    Stage1SecurityAdmissionV1,
    create_market_data_admission,
)

H = "f" * 64
FIXED_NOW = datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)


def make_securities() -> tuple[Stage1SecurityAdmissionV1, ...]:
    return tuple(
        Stage1SecurityAdmissionV1(
            ticker=ticker,
            listing_identity=f"US-EQUITY-{ticker}",
            supported_venues=("XNYS", "XNAS"),
            corporate_actions_verified=True,
            currency="USD",
            has_executable_raw_prices=True,
            usable_source_vintages=("VINTAGE-2026",),
        )
        for ticker in EXACT_12_ETF_UNIVERSE
    )


def test_adversarial_robinhood_totalview_rejected_from_g1() -> None:
    """An adversary attempts to admit Robinhood Gold TotalView into G1.

    Must be rejected with explicit disqualification reason: consumer display
    entitlement does not authorize extraction, lacks historical audit tape, and
    is excluded from G1.
    """
    secs = make_securities()
    artifact = create_market_data_admission(
        admission_id="ATTEMPT-ROBINHOOD-TOTALVIEW",
        admitted_at=FIXED_NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
        candidate_source=DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW,
    )
    assert artifact.status == "REFUSED"
    assert any("DISQUALIFIED_SOURCE" in r for r in artifact.refusal_reasons)
    assert any("TotalView" in r for r in artifact.refusal_reasons)
    assert any("Excluded from G1 critical" in r for r in artifact.refusal_reasons)


def test_adversarial_robinhood_totalview_cannot_masquerade_as_admitted() -> None:
    """Direct model validation must raise if status is ADMITTED with Robinhood."""
    from drift.serialization.canonical import content_hash

    secs = make_securities()
    body = {
        "schema_version": "drift-stage1-market-admission/1",
        "admission_id": "FORGED-ROBINHOOD-ADMISSION",
        "admitted_at": FIXED_NOW,
        "universe": EXACT_12_ETF_UNIVERSE,
        "purpose": "CONFIRMATORY_SCORING",
        "admitted_calendar_hash": H,
        "securities": secs,
        "rights_scope": "RESEARCH_REPLAY_NON_DISPLAY",
        "candidate_source": DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW,
        "alpaca_sip_verification_report_hash": None,
        "limitations": (),
        "contains_synthetic_fixtures": False,
        "diagnostic_authorization": None,
        "status": "ADMITTED",
        "refusal_reasons": (),
        "reviewer_authority": "matthew@drift.local",
    }
    h = content_hash(body)
    with pytest.raises(
        ValidationError,
        match="DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW_NOT_ADMITTED",
    ):
        Stage1MarketDataAdmissionArtifactV1.model_validate(body | {"admission_hash": h})


def test_adversarial_iex_only_assumption_refused_for_historical_data() -> None:
    """An adversary claims an IEX-only feed is necessary for older data.

    Must be rejected: Alpaca provides feed=sip for queries ending > 15m in past.
    """
    with pytest.raises(
        ValidationError, match="IEX_FALLBACK_NOT_PERMITTED_FOR_HISTORICAL_SIP"
    ):
        AlpacaSipHistoricalRequestCheckV1(
            feed="sip",
            adjustment="raw",
            timeframe="1Day",
            request_end=datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC),
            request_time=FIXED_NOW,
            delay_minutes_observed=50000.0,
            is_valid_free_historical_sip=True,
            requires_iex_fallback=True,
        )


def test_adversarial_recent_sip_request_violates_free_tier() -> None:
    """An adversary attempts to query recent SIP data (< 15 min old) under free tier.

    Must fail closed: Alpaca free tier rejects queries inside the 15-minute window.
    """
    recent_end = FIXED_NOW - timedelta(minutes=5)
    is_valid, reason = verify_alpaca_sip_request_delay(recent_end, FIXED_NOW)
    assert is_valid is False
    assert reason is not None
    assert "subscription does not permit querying recent sip data" in reason.lower()

    report = verify_g1_alpaca_sip_qualification(
        request_end=recent_end,
        request_time=FIXED_NOW,
    )
    assert report.overall_status == "REFUSED"
    assert report.sip_access_check.is_valid_free_historical_sip is False


def test_adversarial_altered_etf_universe_refused() -> None:
    """An adversary substitutes the 11-ETF ex-QQQ sensitivity as primary.

    Must be rejected: primary cohort must be exactly the canonical 12 ETFs.
    """
    cov = build_12_etf_coverage()
    ex_qqq = tuple(s for s in cov.securities if s.ticker != "QQQ")
    with pytest.raises(
        ValidationError, match="PRIMARY_UNIVERSE_MUST_MATCH_CANONICAL_12_ETFS"
    ):
        Universe12EtfCoverageV1(
            universe=tuple(s.ticker for s in ex_qqq),
            securities=ex_qqq,
            all_windows_fully_covered=True,
        )


def test_adversarial_public_redistribution_attempt_refused() -> None:
    """An adversary attempts to claim public redistribution or Git storage rights.

    Must fail closed: Alpaca and exchange terms prohibit redistribution.
    """
    with pytest.raises(ValidationError):
        ContractualResearchRetentionRightsV1(
            provider="alpaca",
            license_type="developer_basic_api",
            internal_research_permitted=True,
            algorithmic_non_display_permitted=True,
            private_offline_retention_permitted=True,
            public_redistribution_permitted=True,  # type: ignore[arg-type]
            git_tree_retention_permitted=False,
            compliance_classification="PERMITTED_INTERNAL_RESEARCH_ONLY",
        )


def test_adversarial_tampered_report_hash_refused() -> None:
    """An adversary modifies report fields without updating cryptographic hash.

    Must fail closed with VERIFICATION_REPORT_HASH_MISMATCH.
    """
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=FIXED_NOW,
    )
    tampered_data = report.model_dump()
    tampered_data["report_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="VERIFICATION_REPORT_HASH_MISMATCH"):
        from drift.qualification.alpaca_sip_verification import (
            AlpacaSipG1VerificationReportV1,
        )

        AlpacaSipG1VerificationReportV1.model_validate(tampered_data)
