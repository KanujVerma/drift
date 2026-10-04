"""Unit tests for corporate-action-consistent analytical return series (Issue 116)."""

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
    ADJUSTMENT_METHOD_PRICE_RETURN,
    ADJUSTMENT_METHOD_TOTAL_RETURN,
    AnalyticalReturnSeriesV1,
    AnalyticalReturnSessionV1,
    analytical_return_series_hash,
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


def _session_key(day_num: int) -> SessionKeyV1:
    day = date(2026, 1, 1) + date.resolution * day_num
    return SessionKeyV1(local_date=day, mic=VENUE, session_scope="regular")


def _sample_session(
    day_num: int,
    unadjusted: str,
    analytical: str,
    prior_return: str | None = None,
    split_factor: str = "1",
) -> AnalyticalReturnSessionV1:
    return AnalyticalReturnSessionV1(
        session_key=_session_key(day_num),
        unadjusted_close=Decimal(unadjusted),
        analytical_close=Decimal(analytical),
        return_from_prior=Decimal(prior_return) if prior_return is not None else None,
        cumulative_split_factor=Decimal(split_factor),
    )


def _build_series(
    *,
    sessions: tuple[AnalyticalReturnSessionV1, ...],
    security_id: UUID = SEC_A,
    grade: str = "exploratory",
    adjustment_method: str = ADJUSTMENT_METHOD_TOTAL_RETURN,
    source_observation_hashes: tuple[str, ...] = (),
    applied_effect_hashes: tuple[str, ...] = (),
    acknowledged_limitations: tuple[str, ...] = (),
) -> AnalyticalReturnSeriesV1:
    interval = (
        (sessions[0].session_key, sessions[-1].session_key)
        if sessions
        else (_session_key(0), _session_key(0))
    )
    draft = AnalyticalReturnSeriesV1.model_construct(
        schema_version="1",
        security_id=security_id,
        grade=grade,
        adjustment_method=adjustment_method,
        sessions=sessions,
        lookback_interval=interval,
        source_observation_hashes=source_observation_hashes,
        applied_effect_hashes=applied_effect_hashes,
        acknowledged_limitations=acknowledged_limitations,
        series_hash="0" * 64,
    )
    return draft.model_copy(
        update={"series_hash": analytical_return_series_hash(draft)}
    )


def test_analytical_return_session_validation() -> None:
    session = _sample_session(0, "100.0", "100.0")
    assert session.unadjusted_close == Decimal("100.0")
    assert session.analytical_close == Decimal("100.0")
    assert session.return_from_prior is None
    assert session.cumulative_split_factor == Decimal("1")

    with pytest.raises(
        ValidationError, match="unadjusted close must be strictly positive"
    ):
        AnalyticalReturnSessionV1(
            session_key=_session_key(0),
            unadjusted_close=Decimal("0"),
            analytical_close=Decimal("100.0"),
        )

    with pytest.raises(
        ValidationError, match="analytical close must be strictly positive"
    ):
        AnalyticalReturnSessionV1(
            session_key=_session_key(0),
            unadjusted_close=Decimal("100.0"),
            analytical_close=Decimal("-10.0"),
        )

    with pytest.raises(
        ValidationError, match="cumulative split factor must be strictly positive"
    ):
        AnalyticalReturnSessionV1(
            session_key=_session_key(0),
            unadjusted_close=Decimal("100.0"),
            analytical_close=Decimal("100.0"),
            cumulative_split_factor=Decimal("0"),
        )


def test_analytical_return_series_hash_and_validation() -> None:
    s0 = _sample_session(0, "100.0", "100.0")
    s1 = _sample_session(1, "105.0", "105.0", prior_return="0.05")
    series = _build_series(
        sessions=(s0, s1),
        source_observation_hashes=(H1,),
        applied_effect_hashes=(H2,),
        acknowledged_limitations=("lim1",),
    )

    assert series.grade == "exploratory"
    assert series.adjustment_method == ADJUSTMENT_METHOD_TOTAL_RETURN
    assert len(series.sessions) == 2
    assert series.source_observation_hashes == (H1,)
    assert series.applied_effect_hashes == (H2,)
    assert series.acknowledged_limitations == ("lim1",)


def test_analytical_return_series_tampered_hash_rejected() -> None:
    s0 = _sample_session(0, "100.0", "100.0")
    s1 = _sample_session(1, "105.0", "105.0", prior_return="0.05")

    with pytest.raises(ValidationError, match="series hash mismatch"):
        AnalyticalReturnSeriesV1(
            schema_version="1",
            security_id=SEC_A,
            grade="exploratory",
            adjustment_method=ADJUSTMENT_METHOD_PRICE_RETURN,
            sessions=(s0, s1),
            lookback_interval=(s0.session_key, s1.session_key),
            source_observation_hashes=(),
            applied_effect_hashes=(),
            acknowledged_limitations=(),
            series_hash="f" * 64,
        )


def test_analytical_return_series_unsorted_sessions_rejected() -> None:
    s0 = _sample_session(0, "100.0", "100.0")
    s1 = _sample_session(1, "105.0", "105.0", prior_return="0.05")

    draft = AnalyticalReturnSeriesV1.model_construct(
        schema_version="1",
        security_id=SEC_A,
        grade="exploratory",
        adjustment_method=ADJUSTMENT_METHOD_TOTAL_RETURN,
        sessions=(s1, s0),  # unsorted
        lookback_interval=(s1.session_key, s0.session_key),
        source_observation_hashes=(),
        applied_effect_hashes=(),
        acknowledged_limitations=(),
        series_hash="0" * 64,
    )
    with pytest.raises(ValidationError, match="sessions must be strictly sorted"):
        AnalyticalReturnSeriesV1.model_validate(
            draft.model_copy(
                update={"series_hash": analytical_return_series_hash(draft)}
            ).model_dump()
        )


def test_eligibility_check() -> None:
    assert not is_security_eligible_for_lookback(None, 61)

    s0 = _sample_session(0, "100.0", "100.0")
    s1 = _sample_session(1, "105.0", "105.0", prior_return="0.05")
    draft = AnalyticalReturnSeriesV1.model_construct(
        schema_version="1",
        security_id=SEC_A,
        grade="exploratory",
        adjustment_method=ADJUSTMENT_METHOD_TOTAL_RETURN,
        sessions=(s0, s1),
        lookback_interval=(s0.session_key, s1.session_key),
        source_observation_hashes=(),
        applied_effect_hashes=(),
        acknowledged_limitations=(),
        series_hash="0" * 64,
    )
    series = draft.model_copy(
        update={"series_hash": analytical_return_series_hash(draft)}
    )

    assert is_security_eligible_for_lookback(series, 2)
    assert not is_security_eligible_for_lookback(series, 3)


def test_calculate_momentum_12_1() -> None:
    sessions: list[AnalyticalReturnSessionV1] = []
    # Build 253 sessions
    for i in range(253):
        # Price increases from 100 on day 0 to 200 on day 252
        price = Decimal(100 + i)
        prior_ret = Decimal("0.01") if i > 0 else None
        sessions.append(
            _sample_session(
                i,
                unadjusted=str(price),
                analytical=str(price),
                prior_return=str(prior_ret) if prior_ret is not None else None,
            )
        )

    series = _build_series(sessions=tuple(sessions))

    # Momentum 12-1 is analytical_close[t-21] / analytical_close[t-252] - 1
    # t = 252
    # t - 21 = 231 -> price 100 + 231 = 331
    # t - 252 = 0 -> price 100 + 0 = 100
    # momentum = 331 / 100 - 1 = 2.31
    expected_mom = (Decimal("331") / Decimal("100")) - Decimal("1")
    assert calculate_momentum_12_1(series) == expected_mom

    # If series is too short, raises IndeterminateValuationError
    short_series = _build_series(sessions=tuple(sessions[:200]))
    with pytest.raises(
        IndeterminateValuationError, match="requires at least 253 sessions"
    ):
        calculate_momentum_12_1(short_series)


def test_calculate_low_volatility_60() -> None:
    sessions: list[AnalyticalReturnSessionV1] = []
    # Build 61 sessions with alternating returns +0.02 and -0.02
    for i in range(61):
        if i == 0:
            ret = None
        else:
            ret = "0.02" if i % 2 == 1 else "-0.02"
        sessions.append(
            _sample_session(
                i,
                unadjusted="100.0",
                analytical="100.0",
                prior_return=ret,
            )
        )

    series = _build_series(sessions=tuple(sessions))

    # 30 returns of 0.02, 30 returns of -0.02
    # mean is 0.0
    # squared diffs are all 0.0004
    # variance is 0.0004
    assert calculate_low_volatility_60(series) == Decimal("0.0004")

    # If series is too short, raises IndeterminateValuationError
    short_series = _build_series(sessions=tuple(sessions[:50]))
    with pytest.raises(
        IndeterminateValuationError, match="requires at least 61 sessions"
    ):
        calculate_low_volatility_60(short_series)


def test_build_analytical_return_series_unadjusted() -> None:
    obs = [
        SessionObservationRecord(_session_key(0), Decimal("100.0"), H1),
        SessionObservationRecord(_session_key(1), Decimal("105.0"), H2),
    ]
    series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        observations=obs,
    )
    assert len(series.sessions) == 2
    assert series.sessions[0].analytical_close == Decimal("100.0")
    assert series.sessions[0].return_from_prior is None
    assert series.sessions[1].analytical_close == Decimal("105.0")
    assert series.sessions[1].return_from_prior == Decimal("0.05")
    assert series.sessions[1].cumulative_split_factor == Decimal("1")


def test_build_analytical_return_series_forward_split() -> None:
    # Day 0: 100.0, Day 1: 50.0 after 2:1 forward split
    obs = [
        SessionObservationRecord(_session_key(0), Decimal("100.0"), H1),
        SessionObservationRecord(_session_key(1), Decimal("50.0"), H2),
    ]
    adjs = [
        CorporateActionAdjustment(
            effective_date=_session_key(1).local_date,
            split_ratio=Decimal("2"),
            effect_hash="3" * 64,
        )
    ]
    series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        observations=obs,
        adjustments=adjs,
    )
    assert series.sessions[1].unadjusted_close == Decimal("50.0")
    assert series.sessions[1].return_from_prior == Decimal("0.0")
    assert series.sessions[1].analytical_close == Decimal("100.0")
    assert series.sessions[1].cumulative_split_factor == Decimal("2")


def test_build_analytical_return_series_cash_dividend() -> None:
    # Day 0: 100.0, Day 1: 98.0 with $2 cash dividend
    obs = [
        SessionObservationRecord(_session_key(0), Decimal("100.0"), H1),
        SessionObservationRecord(_session_key(1), Decimal("98.0"), H2),
    ]
    adjs = [
        CorporateActionAdjustment(
            effective_date=_session_key(1).local_date,
            cash_distribution=Decimal("2.0"),
            effect_hash="4" * 64,
        )
    ]
    # Total return reinvested
    total_series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        adjustment_method=ADJUSTMENT_METHOD_TOTAL_RETURN,
        observations=obs,
        adjustments=adjs,
    )
    assert total_series.sessions[1].return_from_prior == Decimal("0.0")
    assert total_series.sessions[1].analytical_close == Decimal("100.0")

    # Price return only (ignores cash dividend)
    price_series = build_analytical_return_series(
        security_id=SEC_A,
        grade="exploratory",
        adjustment_method=ADJUSTMENT_METHOD_PRICE_RETURN,
        observations=obs,
        adjustments=adjs,
    )
    assert price_series.sessions[1].return_from_prior == Decimal("-0.02")
    assert price_series.sessions[1].analytical_close == Decimal("98.0")


def test_build_analytical_return_series_invalid_inputs() -> None:
    with pytest.raises(
        IndeterminateValuationError, match="requires at least one observation"
    ):
        build_analytical_return_series(
            security_id=SEC_A,
            grade="exploratory",
            observations=[],
        )

    obs = [
        SessionObservationRecord(_session_key(0), Decimal("100.0"), H1),
        # duplicate date
        SessionObservationRecord(_session_key(0), Decimal("105.0"), H2),
    ]
    with pytest.raises(IndeterminateValuationError, match="duplicate session dates"):
        build_analytical_return_series(
            security_id=SEC_A,
            grade="exploratory",
            observations=obs,
        )
