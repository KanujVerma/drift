"""Stage 1 market data admission adapter and qualification contracts.

Enforces source-purpose qualification for the exact 12-instrument universe:
VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD, GLD.
Rejects weekday-only calendar substitutes, ticker-only proofs,
unverified corporate actions, and disqualified consumer display sources
(such as Robinhood Gold Nasdaq TotalView Level II).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.experiments.stage1_study_freeze import STAGE1_UNIVERSE
from drift.qualification.alpaca_sip_verification import (
    ALPACA_DELAY_MINIMUM_MINUTES,
    ALPACA_SIP_FEED,
    DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW,
    EXACT_12_ETF_UNIVERSE,
    AlpacaSipG1VerificationReportV1,
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
from drift.serialization.canonical import canonical_json, content_hash

__all__ = [
    "ALPACA_DELAY_MINIMUM_MINUTES",
    "ALPACA_SIP_FEED",
    "DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW",
    "EXACT_12_ETF_UNIVERSE",
    "STAGE1_UNIVERSE",
    "AdmissionPurpose",
    "AdmissionStatus",
    "AlpacaSipG1VerificationReportV1",
    "AlpacaSipHistoricalRequestCheckV1",
    "ContractualResearchRetentionRightsV1",
    "CorporateActionCompletenessV1",
    "OriginalSourceProvenanceV1",
    "RobinhoodTotalViewDisqualificationV1",
    "SecurityHistoricalCoverageV1",
    "Stage1MarketDataAdmissionArtifactV1",
    "Stage1SecurityAdmissionV1",
    "Universe12EtfCoverageV1",
    "build_12_etf_coverage",
    "create_market_data_admission",
    "validate_market_data_admission_for_production",
    "verify_alpaca_sip_request_delay",
    "verify_g1_alpaca_sip_qualification",
]

AdmissionPurpose = Literal[
    "DEVELOPMENT",
    "VALIDATION",
    "CONFIRMATORY_SCORING",
    "PROSPECTIVE_OBSERVATION",
]
AdmissionStatus = Literal["ADMITTED", "REFUSED"]


class Stage1SecurityAdmissionV1(FrozenModel):
    ticker: NonBlankStr
    listing_identity: NonBlankStr
    supported_venues: tuple[NonBlankStr, ...]
    corporate_actions_verified: bool
    currency: Literal["USD"] = "USD"
    has_executable_raw_prices: bool
    usable_source_vintages: tuple[NonBlankStr, ...]


class Stage1MarketDataAdmissionArtifactV1(FrozenModel):
    schema_version: Literal["drift-stage1-market-admission/1"] = (
        "drift-stage1-market-admission/1"
    )
    admission_id: NonBlankStr
    admitted_at: UTCDateTime
    universe: tuple[str, ...] = STAGE1_UNIVERSE
    purpose: AdmissionPurpose
    admitted_calendar_hash: SHA256Hash
    securities: tuple[Stage1SecurityAdmissionV1, ...]
    rights_scope: Literal["RESEARCH_REPLAY_NON_DISPLAY"] = "RESEARCH_REPLAY_NON_DISPLAY"
    candidate_source: str | None = None
    alpaca_sip_verification_report_hash: SHA256Hash | None = None
    limitations: tuple[str, ...] = ()
    contains_synthetic_fixtures: bool = False
    diagnostic_authorization: str | None = None
    status: AdmissionStatus
    refusal_reasons: tuple[str, ...] = ()
    reviewer_authority: NonBlankStr
    admission_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        body = self.model_dump(mode="python", exclude={"admission_hash"})
        if self.admission_hash != content_hash(body):
            raise ValueError("MARKET_ADMISSION_HASH_MISMATCH")
        if self.contains_synthetic_fixtures:
            if self.status == "ADMITTED" and not self.diagnostic_authorization:
                raise ValueError(
                    "SYNTHETIC_MOCK_EVIDENCE_CANNOT_BE_ADMITTED_IN_PRODUCTION: "
                    "admission artifacts containing synthetic fixtures cannot have "
                    "ADMITTED status without explicit diagnostic_authorization."
                )
        if self.status == "ADMITTED":
            if any("SYNTHETIC_MOCK_EVIDENCE" in r for r in self.refusal_reasons) or any(
                "MOCK" in r for r in self.refusal_reasons
            ):
                raise ValueError(
                    "SYNTHETIC_MOCK_EVIDENCE_CANNOT_BE_ADMITTED_IN_PRODUCTION"
                )
            if self.refusal_reasons:
                raise ValueError("ADMITTED_MARKET_DATA_CANNOT_HAVE_REFUSAL_REASONS")
            if self.candidate_source == DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW:
                raise ValueError("DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW_NOT_ADMITTED")
            admitted_tickers = {s.ticker for s in self.securities}
            if set(self.universe) != admitted_tickers:
                raise ValueError("MARKET_ADMISSION_UNIVERSE_INCOMPLETE")
            for sec in self.securities:
                if not sec.corporate_actions_verified:
                    raise ValueError(f"CORPORATE_ACTIONS_UNVERIFIED:{sec.ticker}")
                if not sec.has_executable_raw_prices:
                    raise ValueError(f"EXECUTABLE_RAW_PRICES_MISSING:{sec.ticker}")
        return self


def create_market_data_admission(
    *,
    admission_id: str,
    admitted_at: datetime,
    purpose: AdmissionPurpose,
    admitted_calendar_hash: str,
    securities: tuple[Stage1SecurityAdmissionV1, ...],
    reviewer_authority: str,
    candidate_source: str | None = None,
    alpaca_sip_report: AlpacaSipG1VerificationReportV1 | None = None,
    limitations: tuple[str, ...] = (),
    refusal_reasons: tuple[str, ...] = (),
    allow_synthetic: bool = False,
    diagnostic_authorization: str | None = None,
) -> Stage1MarketDataAdmissionArtifactV1:
    admitted_tickers = {s.ticker for s in securities}
    reasons = list(refusal_reasons)
    is_synthetic = False

    if candidate_source == DISQUALIFIED_SOURCE_ROBINHOOD_TOTALVIEW:
        reasons.append(
            f"DISQUALIFIED_SOURCE:{candidate_source}: Robinhood Gold Nasdaq "
            "TotalView Level II is a consumer display entitlement. Programmatic "
            "extraction into Drift is unauthorized. Excluded from G1 critical "
            "path. Intraday order-book data deferred to separate execution study."
        )

    if alpaca_sip_report is not None:
        is_synthetic = bool(
            getattr(alpaca_sip_report, "contains_synthetic_fixtures", False)
        )
        if is_synthetic and not (allow_synthetic and diagnostic_authorization):
            reasons.append(
                "SYNTHETIC_MOCK_EVIDENCE_INADMISSIBLE: Alpaca SIP verification "
                "report contains synthetic mock fixtures and cannot be admitted "
                "for production Stage 1 market data without diagnostic_authorization."
            )
        if alpaca_sip_report.overall_status != "VERIFIED":
            reasons.append(
                f"ALPACA_SIP_REPORT_REFUSED:{alpaca_sip_report.verification_id}"
            )
        if not alpaca_sip_report.sip_access_check.is_valid_free_historical_sip:
            reasons.append(
                f"ALPACA_SIP_REQUEST_DELAY_INVALID:{alpaca_sip_report.sip_access_check.refusal_reason}"
            )

    if set(STAGE1_UNIVERSE) != admitted_tickers:
        missing = sorted(set(STAGE1_UNIVERSE) - admitted_tickers)
        reasons.append(f"UNIVERSE_MISSING_SECURITIES:{','.join(missing)}")

    for sec in securities:
        if not sec.corporate_actions_verified:
            reasons.append(f"CORPORATE_ACTIONS_NOT_VERIFIED:{sec.ticker}")
        if not sec.has_executable_raw_prices:
            reasons.append(f"RAW_PRICES_NOT_AVAILABLE:{sec.ticker}")

    status: AdmissionStatus = "REFUSED" if reasons else "ADMITTED"

    body = {
        "schema_version": "drift-stage1-market-admission/1",
        "admission_id": admission_id,
        "admitted_at": admitted_at,
        "universe": STAGE1_UNIVERSE,
        "purpose": purpose,
        "admitted_calendar_hash": admitted_calendar_hash,
        "securities": securities,
        "rights_scope": "RESEARCH_REPLAY_NON_DISPLAY",
        "candidate_source": candidate_source,
        "alpaca_sip_verification_report_hash": (
            alpaca_sip_report.report_hash if alpaca_sip_report is not None else None
        ),
        "limitations": limitations,
        "contains_synthetic_fixtures": is_synthetic,
        "diagnostic_authorization": (
            diagnostic_authorization if is_synthetic else None
        ),
        "status": status,
        "refusal_reasons": tuple(sorted(reasons)),
        "reviewer_authority": reviewer_authority,
    }
    h = content_hash(body)
    return Stage1MarketDataAdmissionArtifactV1.model_validate_json(
        canonical_json(body | {"admission_hash": h})
    )


def validate_market_data_admission_for_production(
    artifact: Stage1MarketDataAdmissionArtifactV1,
) -> None:
    """Validate that an admission artifact is admissible for production execution.

    Fails closed if the artifact carries non-ADMITTED status or contains synthetic
    mock fixtures.
    """
    if artifact.status != "ADMITTED":
        raise ValueError(
            f"ADMISSION_REFUSED: artifact {artifact.admission_id} has status "
            f"{artifact.status}."
        )
    if artifact.contains_synthetic_fixtures:
        raise ValueError(
            f"SYNTHETIC_MOCK_EVIDENCE_INADMISSIBLE_IN_PRODUCTION: artifact "
            f"{artifact.admission_id} contains synthetic mock fixtures and cannot "
            "be consumed in production."
        )
