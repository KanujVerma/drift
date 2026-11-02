"""Unit tests for Stage 1 market data admission qualification."""

from datetime import UTC, datetime

from drift.experiments.stage1_study_freeze import STAGE1_UNIVERSE
from drift.qualification.stage1_market_admission import (
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
