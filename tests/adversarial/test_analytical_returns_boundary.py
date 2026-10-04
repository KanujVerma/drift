"""Adversarial boundary and anti-laundering tests for analytical returns (Issue 116).

Verifies fail-closed missingness, anti-lookahead causality, exact rational
and decimal precision, and non-promotability boundaries.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.analysis.analytical_returns import (
    CorporateActionAdjustment,
    SessionObservationRecord,
    build_analytical_return_series,
)
from drift.domain.analytical_returns import (
    ADJUSTMENT_METHOD_TOTAL_RETURN,
    calculate_low_volatility_60,
    calculate_momentum_12_1,
    is_security_eligible_for_lookback,
)
from drift.domain.evaluator_portfolio import IndeterminateValuationError
from drift.domain.sessions import SessionKeyV1

SEC_A = UUID("00000000-0000-7000-8000-000000000001")
VENUE = "XNAS"
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


def _session_key(day_num: int) -> SessionKeyV1:
    day = date(2026, 1, 1) + date.resolution * day_num
    return SessionKeyV1(local_date=day, mic=VENUE, session_scope="regular")


def test_missingness_fails_closed() -> None:
    """Missing observations fail closed to ineligible and indeterminate."""
    # Security with no series is not eligible
    assert not is_security_eligible_for_lookback(None, 253)

    # Security with 252 sessions (1 short of 253) is not eligible
    obs = [
        SessionObservationRecord(_session_key(i), Decimal("100.0"), H1)
        for i in range(252)
    ]
    series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        observations=obs,
    )
    assert not is_security_eligible_for_lookback(series, 253)

    with pytest.raises(
        IndeterminateValuationError, match="requires at least 253 sessions"
    ):
        calculate_momentum_12_1(series)

    # Security with 60 sessions (1 short of 61) fails low volatility
    short_obs = obs[:60]
    short_series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        observations=short_obs,
    )
    assert not is_security_eligible_for_lookback(short_series, 61)
    with pytest.raises(
        IndeterminateValuationError, match="requires at least 61 sessions"
    ):
        calculate_low_volatility_60(short_series)


def test_anti_lookahead_future_actions_not_applied() -> None:
    """Corporate actions effective after a session do not perturb earlier returns."""
    obs = [
        SessionObservationRecord(_session_key(0), Decimal("100.0"), H1),
        SessionObservationRecord(_session_key(1), Decimal("100.0"), H2),
        SessionObservationRecord(_session_key(2), Decimal("50.0"), H3),
    ]
    # Split effective on day 2
    adjs = [
        CorporateActionAdjustment(
            effective_date=_session_key(2).local_date,
            split_ratio=Decimal("2"),
            effect_hash="4" * 64,
        )
    ]
    series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        observations=obs,
        adjustments=adjs,
    )

    # Day 0 to Day 1: no action effective on day 1
    assert series.sessions[1].return_from_prior == Decimal("0.0")
    assert series.sessions[1].analytical_close == Decimal("100.0")
    assert series.sessions[1].cumulative_split_factor == Decimal("1")

    # Day 1 to Day 2: 2:1 split applied on day 2
    assert series.sessions[2].return_from_prior == Decimal("0.0")
    assert series.sessions[2].analytical_close == Decimal("100.0")
    assert series.sessions[2].cumulative_split_factor == Decimal("2")


def test_exploratory_grade_is_immutable_and_non_promotable() -> None:
    """An exploratory series cannot be relabeled as promotion-grade."""
    obs = [
        SessionObservationRecord(_session_key(0), Decimal("100.0"), H1),
        SessionObservationRecord(_session_key(1), Decimal("105.0"), H2),
    ]
    series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        observations=obs,
    )
    assert series.grade == "exploratory"

    # Attempting to mutate grade fails because model is frozen
    with pytest.raises(ValidationError):
        series.grade = "promotion"


def test_exact_decimal_arithmetic_without_float_artifacts() -> None:
    """Returns and prices use exact Decimal arithmetic with zero float steps."""
    obs = [
        SessionObservationRecord(_session_key(0), Decimal("0.1"), H1),
        SessionObservationRecord(_session_key(1), Decimal("0.2"), H2),
        SessionObservationRecord(_session_key(2), Decimal("0.3"), H3),
    ]
    series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        adjustment_method=ADJUSTMENT_METHOD_TOTAL_RETURN,
        observations=obs,
    )
    # 0.2 / 0.1 - 1 = 1.0 exactly
    assert series.sessions[1].return_from_prior == Decimal("1.0")
    # 0.3 / 0.2 - 1 = 0.5 exactly
    assert series.sessions[2].return_from_prior == Decimal("0.5")
    assert series.sessions[2].analytical_close == Decimal("0.3")
