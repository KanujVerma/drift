"""Unit tests for Stage 1 market data admission qualification."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_study_freeze import STAGE1_UNIVERSE
from drift.qualification.alpaca_sip_verification import (
    DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW,
    verify_g1_alpaca_sip_qualification,
)
from drift.qualification.stage1_market_admission import (
    Stage1MarketDataAdmissionArtifactV1,
    Stage1SecurityAdmissionV1,
    create_market_data_admission,
)

H = "e" * 64
NOW = datetime(2026, 11, 2, 5, 0, 0, tzinfo=UTC)


def make_securities(
    *, drop_tickers: tuple[str, ...] = (), unverified_corp_actions: tuple[str, ...] = ()
) -> tuple[Stage1SecurityAdmissionV1, ...]:
    return tuple(
        Stage1SecurityAdmissionV1(
            ticker=ticker,
            listing_identity=f"US-EQUITY-{ticker}",
            supported_venues=("XNYS", "XNAS"),
            corporate_actions_verified=ticker not in unverified_corp_actions,
            currency="USD",
            has_executable_raw_prices=True,
            usable_source_vintages=("VINTAGE-2026",),
        )
        for ticker in STAGE1_UNIVERSE
        if ticker not in drop_tickers
    )


def test_create_valid_market_data_admission() -> None:
    secs = make_securities()
    artifact = create_market_data_admission(
        admission_id="MARKET-ADM-2021-2025-V1",
        admitted_at=NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
    )
    assert artifact.status == "ADMITTED"
    assert len(artifact.securities) == 12
    assert len(artifact.admission_hash) == 64


def test_market_admission_refuses_incomplete_universe() -> None:
    secs = make_securities(drop_tickers=("GLD", "TIP"))
    artifact = create_market_data_admission(
        admission_id="MARKET-ADM-INCOMPLETE",
        admitted_at=NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
    )
    assert artifact.status == "REFUSED"
    assert any("UNIVERSE_MISSING_SECURITIES" in r for r in artifact.refusal_reasons)


def test_market_admission_refuses_unverified_corporate_actions() -> None:
    secs = make_securities(unverified_corp_actions=("QQQ",))
    artifact = create_market_data_admission(
        admission_id="MARKET-ADM-CORP-UNVERIFIED",
        admitted_at=NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
    )
    assert artifact.status == "REFUSED"
    assert any(
        "CORPORATE_ACTIONS_NOT_VERIFIED:QQQ" in r for r in artifact.refusal_reasons
    )


def test_market_admission_with_verified_alpaca_sip_report() -> None:
    from drift.qualification.alpaca_sip_verification import (
        create_mock_alpaca_sip_evidence_fixtures,
    )

    intake_res, cov_ev, ca_records, rights = create_mock_alpaca_sip_evidence_fixtures()
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=NOW,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
        allow_synthetic=True,
    )
    secs = make_securities()
    artifact = create_market_data_admission(
        admission_id="MARKET-ADM-ALPACA-SIP-V1",
        admitted_at=NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
        candidate_source="alpaca-sip",
        alpaca_sip_report=report,
        allow_synthetic=True,
        diagnostic_authorization="DIAGNOSTIC_DEMONSTRATION",
    )
    assert artifact.status == "ADMITTED"
    assert artifact.alpaca_sip_verification_report_hash == report.report_hash
    assert artifact.candidate_source == "alpaca-sip"
    assert artifact.contains_synthetic_fixtures is True
    assert artifact.diagnostic_authorization == "DIAGNOSTIC_DEMONSTRATION"

    # Consuming this synthetic artifact in production must fail closed
    from drift.qualification.stage1_market_admission import (
        validate_market_data_admission_for_production,
    )

    with pytest.raises(
        ValueError, match="SYNTHETIC_MOCK_EVIDENCE_INADMISSIBLE_IN_PRODUCTION"
    ):
        validate_market_data_admission_for_production(artifact)


def test_market_admission_persisted_validation_rejects_synthetic_without_auth() -> None:
    """Deserializing an ADMITTED synthetic artifact without diagnostic auth fails."""
    from drift.serialization.canonical import content_hash

    secs = make_securities()
    body = {
        "schema_version": "drift-stage1-market-admission/1",
        "admission_id": "SYNTHETIC-WITHOUT-DIAG-AUTH",
        "admitted_at": NOW,
        "universe": STAGE1_UNIVERSE,
        "purpose": "CONFIRMATORY_SCORING",
        "admitted_calendar_hash": H,
        "securities": secs,
        "rights_scope": "RESEARCH_REPLAY_NON_DISPLAY",
        "candidate_source": "alpaca-sip",
        "alpaca_sip_verification_report_hash": "a" * 64,
        "limitations": (),
        "contains_synthetic_fixtures": True,
        "diagnostic_authorization": None,
        "status": "ADMITTED",
        "refusal_reasons": (),
        "reviewer_authority": "matthew@drift.local",
    }
    h = content_hash(body)
    with pytest.raises(
        ValidationError,
        match="SYNTHETIC_MOCK_EVIDENCE_CANNOT_BE_ADMITTED_IN_PRODUCTION",
    ):
        Stage1MarketDataAdmissionArtifactV1.model_validate(body | {"admission_hash": h})


def test_market_admission_refuses_synthetic_report_by_default() -> None:
    from drift.qualification.alpaca_sip_verification import (
        create_mock_alpaca_sip_evidence_fixtures,
    )

    intake_res, cov_ev, ca_records, rights = create_mock_alpaca_sip_evidence_fixtures()
    report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=NOW,
        intake_result=intake_res,
        corporate_actions=ca_records,
        rights_assessment=rights,
        coverage_evidence=cov_ev,
        allow_synthetic=True,
    )
    secs = make_securities()
    artifact = create_market_data_admission(
        admission_id="MARKET-ADM-ALPACA-SIP-SYNTH-REFUSED",
        admitted_at=NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
        candidate_source="alpaca-sip",
        alpaca_sip_report=report,
        allow_synthetic=False,
    )
    assert artifact.status == "REFUSED"
    assert any(
        "SYNTHETIC_MOCK_EVIDENCE_INADMISSIBLE" in r for r in artifact.refusal_reasons
    )


def test_market_admission_refuses_unverified_alpaca_sip_report() -> None:
    unverified_report = verify_g1_alpaca_sip_qualification(
        request_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        request_time=NOW,
    )
    assert unverified_report.overall_status == "REFUSED"
    secs = make_securities()
    artifact = create_market_data_admission(
        admission_id="MARKET-ADM-ALPACA-SIP-REFUSED",
        admitted_at=NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
        candidate_source="alpaca-sip",
        alpaca_sip_report=unverified_report,
    )
    assert artifact.status == "REFUSED"
    assert any("ALPACA_SIP_REPORT_REFUSED" in r for r in artifact.refusal_reasons)


def test_market_admission_refuses_robinhood_totalview() -> None:
    secs = make_securities()
    artifact = create_market_data_admission(
        admission_id="MARKET-ADM-REFUSED-ROBINHOOD",
        admitted_at=NOW,
        purpose="CONFIRMATORY_SCORING",
        admitted_calendar_hash=H,
        securities=secs,
        reviewer_authority="matthew@drift.local",
        candidate_source=DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW,
    )
    assert artifact.status == "REFUSED"
    assert any("DISQUALIFIED_SOURCE" in r for r in artifact.refusal_reasons)
    assert any("Excluded from G1 critical path" in r for r in artifact.refusal_reasons)
