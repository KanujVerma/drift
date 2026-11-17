"""Stage 1 study outcome classification and strict precedence implementation.

Precedence order:
1. INVALID: known lookahead, override, manipulated evidence,
   or violated frozen comparison.
2. UNAVAILABLE: required evidence is missing or contradictory.
3. UNSUCCESSFUL: valid complete comparable evidence gives primary E <= 0.
4. SUCCESS: positive E meets materiality, intervals > 0, risk holds,
   prospective complete, and accepted.
5. PROMISING_BUT_INCONCLUSIVE: positive valid E exists, but one or more
   success requirements are unmet.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.common import FrozenModel, SHA256Hash
from drift.serialization.canonical import canonical_json, content_hash

StudyOutcome = Literal[
    "INVALID",
    "UNAVAILABLE",
    "UNSUCCESSFUL",
    "SUCCESS",
    "PROMISING_BUT_INCONCLUSIVE",
]


class StudyOutcomeClassificationV1(FrozenModel):
    schema_version: Literal["drift-stage1-outcome/1"] = "drift-stage1-outcome/1"
    outcome: StudyOutcome
    primary_economic_advantage: Decimal | None
    materiality_hurdle: Decimal
    is_invalid: bool
    is_available: bool
    is_risk_comparable: bool
    is_prospective_complete: bool
    is_independently_accepted: bool
    reasons: tuple[str, ...]
    classification_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_classification(self) -> Self:
        body = self.model_dump(mode="python", exclude={"classification_hash"})
        if self.classification_hash != content_hash(body):
            raise ValueError("OUTCOME_CLASSIFICATION_HASH_MISMATCH")
        return self


def compute_materiality_hurdle(scheduled_sessions: int) -> Decimal:
    """Computes materiality: 10000 * 0.01 * N / 252 USD.

    Evaluates to USD 100 at 252 scheduled sessions and USD 200 at 504.
    """
    return (Decimal("100") * Decimal(scheduled_sessions)) / Decimal("252")


def classify_study_outcome(
    *,
    scheduled_sessions: int,
    primary_economic_advantage: Decimal | None = None,
    primary_nav_diff_lower: Decimal | None = None,
    primary_econ_lower: Decimal | None = None,
    b_volatility: Decimal | None = None,
    r_volatility: Decimal | None = None,
    b_max_drawdown: Decimal | None = None,
    r_max_drawdown: Decimal | None = None,
    is_invalid: bool = False,
    invalid_reason: str | None = None,
    is_available: bool = True,
    unavailable_reasons: tuple[str, ...] = (),
    is_prospective_complete: bool = False,
    is_independently_accepted: bool = False,
) -> StudyOutcomeClassificationV1:
    reasons: list[str] = []
    materiality = compute_materiality_hurdle(scheduled_sessions)

    # 1. INVALID check
    if is_invalid:
        if invalid_reason:
            reasons.append(invalid_reason)
        return _make_outcome(
            outcome="INVALID",
            econ=primary_economic_advantage,
            hurdle=materiality,
            inv=True,
            avail=is_available,
            risk=False,
            prosp=is_prospective_complete,
            acc=is_independently_accepted,
            reasons=reasons,
        )

    # 2. UNAVAILABLE check
    if (
        not is_available
        or primary_economic_advantage is None
        or b_volatility is None
        or r_volatility is None
        or b_max_drawdown is None
        or r_max_drawdown is None
    ):
        reasons.extend(unavailable_reasons)
        if primary_economic_advantage is None:
            reasons.append("MISSING_PRIMARY_ECONOMIC_ADVANTAGE")
        if b_volatility is None or r_volatility is None:
            reasons.append("MISSING_VOLATILITY_EVIDENCE")
        if b_max_drawdown is None or r_max_drawdown is None:
            reasons.append("MISSING_DRAWDOWN_EVIDENCE")
        return _make_outcome(
            outcome="UNAVAILABLE",
            econ=primary_economic_advantage,
            hurdle=materiality,
            inv=False,
            avail=False,
            risk=False,
            prosp=is_prospective_complete,
            acc=is_independently_accepted,
            reasons=reasons,
        )

    # Risk comparability evaluation
    # B vol <= 1.10 * R vol. When R vol == 0, only B vol == 0 satisfies.
    risk_ok = True
    if r_volatility == Decimal("0"):
        if b_volatility != Decimal("0"):
            risk_ok = False
            reasons.append("RISK_VOLATILITY_RATIO_EXCEEDED:R_VOL_ZERO")
    else:
        if b_volatility > (Decimal("1.10") * r_volatility):
            risk_ok = False
            reasons.append("RISK_VOLATILITY_RATIO_EXCEEDED")

    # B drawdown <= R drawdown + 0.02
    if b_max_drawdown > (r_max_drawdown + Decimal("0.02")):
        risk_ok = False
        reasons.append("RISK_DRAWDOWN_LIMIT_EXCEEDED")

    # 3. UNSUCCESSFUL check: valid complete evidence gives primary E <= 0
    if primary_economic_advantage <= Decimal("0"):
        reasons.append("ECONOMIC_ADVANTAGE_NON_POSITIVE")
        return _make_outcome(
            outcome="UNSUCCESSFUL",
            econ=primary_economic_advantage,
            hurdle=materiality,
            inv=False,
            avail=True,
            risk=risk_ok,
            prosp=is_prospective_complete,
            acc=is_independently_accepted,
            reasons=reasons,
        )

    # 4. Check for SUCCESS vs PROMISING_BUT_INCONCLUSIVE
    success = True
    if primary_economic_advantage < materiality:
        success = False
        reasons.append("MATERIALITY_HURDLE_NOT_MET")

    if primary_nav_diff_lower is None or primary_nav_diff_lower <= Decimal("0"):
        success = False
        reasons.append("NAV_DIFF_INTERVAL_INCLUDES_ZERO")

    if primary_econ_lower is None or primary_econ_lower <= Decimal("0"):
        success = False
        reasons.append("ECONOMIC_INTERVAL_INCLUDES_ZERO")

    if not risk_ok:
        success = False

    if not is_prospective_complete:
        success = False
        reasons.append("PROSPECTIVE_STUDY_INCOMPLETE")

    if not is_independently_accepted:
        success = False
        reasons.append("INDEPENDENT_ACCEPTANCE_MISSING")

    outcome: StudyOutcome = "SUCCESS" if success else "PROMISING_BUT_INCONCLUSIVE"

    return _make_outcome(
        outcome=outcome,
        econ=primary_economic_advantage,
        hurdle=materiality,
        inv=False,
        avail=True,
        risk=risk_ok,
        prosp=is_prospective_complete,
        acc=is_independently_accepted,
        reasons=reasons,
    )


def _make_outcome(
    *,
    outcome: StudyOutcome,
    econ: Decimal | None,
    hurdle: Decimal,
    inv: bool,
    avail: bool,
    risk: bool,
    prosp: bool,
    acc: bool,
    reasons: list[str],
) -> StudyOutcomeClassificationV1:
    body = {
        "schema_version": "drift-stage1-outcome/1",
        "outcome": outcome,
        "primary_economic_advantage": econ,
        "materiality_hurdle": hurdle,
        "is_invalid": inv,
        "is_available": avail,
        "is_risk_comparable": risk,
        "is_prospective_complete": prosp,
        "is_independently_accepted": acc,
        "reasons": tuple(sorted(reasons)),
    }
    h = content_hash(body)
    return StudyOutcomeClassificationV1.model_validate_json(
        canonical_json(body | {"classification_hash": h})
    )
