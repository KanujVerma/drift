"""Corporate-action-consistent analytical return series contracts (Issue 116).

Provides the immutable domain contracts, validation rules, content hashing,
and baseline metric calculations (B4 12-1 momentum and B5 60-session low volatility)
for corporate-action-consistent analytical return series.
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
)
from drift.domain.evaluator_portfolio import IndeterminateValuationError
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

ANALYTICAL_RETURNS_SCHEMA_VERSION: Literal["1"] = "1"

ADJUSTMENT_METHOD_TOTAL_RETURN: Literal["total_return_reinvested_ex_close"] = (
    "total_return_reinvested_ex_close"
)
ADJUSTMENT_METHOD_PRICE_RETURN: Literal["price_return_split_adjusted"] = (
    "price_return_split_adjusted"
)

type AnalyticalAdjustmentMethod = Literal[
    "total_return_reinvested_ex_close",
    "price_return_split_adjusted",
]

_MOMENTUM_REQUIRED_SESSIONS = 253
_MOMENTUM_LAG_21 = 21
_MOMENTUM_LAG_252 = 252

_LOW_VOLATILITY_REQUIRED_SESSIONS = 61
_LOW_VOLATILITY_RETURN_COUNT = 60


def _session_key_order(key: SessionKeyV1) -> tuple[date, str, str]:
    return (key.local_date, key.mic, key.session_scope)


class AnalyticalReturnSessionV1(FrozenModel):
    """One session entry in an analytical return series."""

    schema_version: Literal["1"] = ANALYTICAL_RETURNS_SCHEMA_VERSION
    session_key: SessionKeyV1
    unadjusted_close: Decimal
    analytical_close: Decimal
    return_from_prior: Decimal | None = None
    cumulative_split_factor: Decimal = Decimal("1")

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if self.unadjusted_close <= Decimal("0"):
            raise ValueError("unadjusted close must be strictly positive")
        if self.analytical_close <= Decimal("0"):
            raise ValueError("analytical close must be strictly positive")
        if self.cumulative_split_factor <= Decimal("0"):
            raise ValueError("cumulative split factor must be strictly positive")
        return self


class AnalyticalReturnSeriesV1(FrozenModel):
    """A causal corporate-action analytical return series for one security."""

    schema_version: Literal["1"] = ANALYTICAL_RETURNS_SCHEMA_VERSION
    security_id: UUID7
    grade: Literal["exploratory", "promotion"]
    adjustment_method: AnalyticalAdjustmentMethod
    sessions: tuple[AnalyticalReturnSessionV1, ...]
    lookback_interval: tuple[SessionKeyV1, SessionKeyV1]
    source_observation_hashes: tuple[SHA256Hash, ...]
    applied_effect_hashes: tuple[SHA256Hash, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]
    series_hash: SHA256Hash

    @field_validator(
        "source_observation_hashes",
        "applied_effect_hashes",
        "acknowledged_limitations",
    )
    @classmethod
    def canonicalize_sorted_tuples(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("series hashes and limitations must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        if self.sessions:
            ordered = tuple(
                sorted(self.sessions, key=lambda s: _session_key_order(s.session_key))
            )
            if self.sessions != ordered:
                raise ValueError("sessions must be strictly sorted chronologically")
            keys = tuple(s.session_key for s in self.sessions)
            if len(set(keys)) != len(keys):
                raise ValueError("session keys within series must be unique")
            if self.sessions[0].return_from_prior is not None:
                raise ValueError("first session must have return_from_prior=None")
            for s in self.sessions[1:]:
                if s.return_from_prior is None:
                    raise ValueError("subsequent sessions must have return_from_prior")
            expected_interval = (
                self.sessions[0].session_key,
                self.sessions[-1].session_key,
            )
            if self.lookback_interval != expected_interval:
                raise ValueError(
                    f"lookback interval mismatch: expected {expected_interval}, "
                    f"got {self.lookback_interval}"
                )
        expected_hash = analytical_return_series_hash(self)
        if self.series_hash != expected_hash:
            raise ValueError(
                f"series hash mismatch: expected {expected_hash}, "
                f"got {self.series_hash}"
            )
        return self


def analytical_return_series_hash(series: AnalyticalReturnSeriesV1) -> SHA256Hash:
    """Compute the canonical content hash for AnalyticalReturnSeriesV1."""
    dump = series.model_dump(mode="python")
    dump.pop("series_hash", None)
    return content_hash(dump)


def is_security_eligible_for_lookback(
    series: AnalyticalReturnSeriesV1 | None,
    required_sessions: int,
) -> bool:
    """Check whether a security is determinate and has sufficient lookback history."""
    if series is None:
        return False
    if len(series.sessions) < required_sessions:
        return False
    return True


def calculate_momentum_12_1(series: AnalyticalReturnSeriesV1) -> Decimal:
    """Calculate B4 12-1 momentum: analytical_close[t-21]/analytical_close[t-252] - 1.

    Requires at least 253 sessions in the series.
    """
    if len(series.sessions) < _MOMENTUM_REQUIRED_SESSIONS:
        raise IndeterminateValuationError(
            f"B4 12-1 momentum requires at least {_MOMENTUM_REQUIRED_SESSIONS} "
            f"sessions, got {len(series.sessions)}"
        )
    t = len(series.sessions) - 1
    close_21 = series.sessions[t - _MOMENTUM_LAG_21].analytical_close
    close_252 = series.sessions[t - _MOMENTUM_LAG_252].analytical_close
    if close_252 <= Decimal("0"):
        raise IndeterminateValuationError(
            "base analytical close must be strictly positive"
        )
    return (close_21 / close_252) - Decimal("1")


def calculate_low_volatility_60(series: AnalyticalReturnSeriesV1) -> Decimal:
    """Calculate B5 60-session low volatility (variance of 60 close returns).

    Requires at least 61 sessions in the series.
    """
    if len(series.sessions) < _LOW_VOLATILITY_REQUIRED_SESSIONS:
        raise IndeterminateValuationError(
            f"B5 low volatility requires at least {_LOW_VOLATILITY_REQUIRED_SESSIONS} "
            f"sessions, got {len(series.sessions)}"
        )
    returns: list[Decimal] = []
    for session in series.sessions[-_LOW_VOLATILITY_RETURN_COUNT:]:
        if session.return_from_prior is None:
            raise IndeterminateValuationError(
                "missing return_from_prior in 60-session low volatility window"
            )
        returns.append(session.return_from_prior)

    count = Decimal(str(len(returns)))
    mean_return = sum(returns, Decimal("0")) / count
    squared_diffs = sum(((r - mean_return) ** 2 for r in returns), Decimal("0"))
    return squared_diffs / count
