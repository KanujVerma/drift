"""Stage 1 market data admission adapter and qualification contracts.

Enforces source-purpose qualification for the exact 12-instrument universe:
VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD, GLD.
Rejects weekday-only calendar substitutes, ticker-only proofs,
and unverified corporate actions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.experiments.stage1_study_freeze import STAGE1_UNIVERSE
from drift.serialization.canonical import canonical_json, content_hash

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
    limitations: tuple[str, ...] = ()
    status: AdmissionStatus
    refusal_reasons: tuple[str, ...] = ()
    reviewer_authority: NonBlankStr
    admission_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        body = self.model_dump(mode="python", exclude={"admission_hash"})
        if self.admission_hash != content_hash(body):
            raise ValueError("MARKET_ADMISSION_HASH_MISMATCH")
        if self.status == "ADMITTED":
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
    limitations: tuple[str, ...] = (),
    refusal_reasons: tuple[str, ...] = (),
) -> Stage1MarketDataAdmissionArtifactV1:
    admitted_tickers = {s.ticker for s in securities}
    reasons = list(refusal_reasons)

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
        "limitations": limitations,
        "status": status,
        "refusal_reasons": tuple(sorted(reasons)),
        "reviewer_authority": reviewer_authority,
    }
    h = content_hash(body)
    return Stage1MarketDataAdmissionArtifactV1.model_validate_json(
        canonical_json(body | {"admission_hash": h})
    )
