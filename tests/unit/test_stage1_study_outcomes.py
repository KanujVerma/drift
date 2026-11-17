"""Unit tests for Stage 1 outcome classification, N7 materiality, and N8 precedence."""

from decimal import Decimal

from drift.experiments.stage1_study_outcomes import (
    classify_study_outcome,
    compute_materiality_hurdle,
)


def test_n7_materiality_hurdle() -> None:
    # Materiality is 100 at N=252 and 200 at N=504
    assert compute_materiality_hurdle(252) == Decimal("100")
    assert compute_materiality_hurdle(504) == Decimal("200")


def test_n7_risk_boundaries() -> None:
    # B volatility 0.11 and R 0.10 satisfy 1.10 boundary
    out = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("150"),
        primary_nav_diff_lower=Decimal("0.01"),
        primary_econ_lower=Decimal("50"),
        b_volatility=Decimal("0.11"),
        r_volatility=Decimal("0.10"),
        b_max_drawdown=Decimal("0.15"),
        r_max_drawdown=Decimal("0.15"),
        is_prospective_complete=True,
        is_independently_accepted=True,
    )
    assert out.outcome == "SUCCESS"
    assert out.is_risk_comparable is True

    # R vol 0 with positive B vol fails
    out_zero_r = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("150"),
        b_volatility=Decimal("0.01"),
        r_volatility=Decimal("0.00"),
        b_max_drawdown=Decimal("0.10"),
        r_max_drawdown=Decimal("0.10"),
    )
    assert out_zero_r.is_risk_comparable is False

    # B drawdown 0.17 with R 0.15 satisfies +0.02 bound; 0.170001 fails
    out_dd_pass = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("150"),
        b_volatility=Decimal("0.10"),
        r_volatility=Decimal("0.10"),
        b_max_drawdown=Decimal("0.17"),
        r_max_drawdown=Decimal("0.15"),
    )
    assert out_dd_pass.is_risk_comparable is True

    out_dd_fail = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("150"),
        b_volatility=Decimal("0.10"),
        r_volatility=Decimal("0.10"),
        b_max_drawdown=Decimal("0.170001"),
        r_max_drawdown=Decimal("0.15"),
    )
    assert out_dd_fail.is_risk_comparable is False


def test_n8_precedence() -> None:
    # 1. Known invalid outranks all profit figures -> INVALID
    out_inv = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("5000"),
        is_invalid=True,
        invalid_reason="LOOKAHEAD_IN_MODEL_CONTEXT",
    )
    assert out_inv.outcome == "INVALID"

    # 2. Missing required evidence -> UNAVAILABLE
    out_unavail = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=None,
    )
    assert out_unavail.outcome == "UNAVAILABLE"

    # 3. Known E <= 0 remains UNSUCCESSFUL even without uncertainty
    out_unsucc = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("-50"),
        b_volatility=Decimal("0.10"),
        r_volatility=Decimal("0.10"),
        b_max_drawdown=Decimal("0.10"),
        r_max_drawdown=Decimal("0.10"),
    )
    assert out_unsucc.outcome == "UNSUCCESSFUL"

    # 4. Positive E with absent prospective completion -> PROMISING_BUT_INCONCLUSIVE
    out_inconcl = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("250"),
        primary_nav_diff_lower=Decimal("0.01"),
        primary_econ_lower=Decimal("50"),
        b_volatility=Decimal("0.10"),
        r_volatility=Decimal("0.10"),
        b_max_drawdown=Decimal("0.10"),
        r_max_drawdown=Decimal("0.10"),
        is_prospective_complete=False,
        is_independently_accepted=True,
    )
    assert out_inconcl.outcome == "PROMISING_BUT_INCONCLUSIVE"
