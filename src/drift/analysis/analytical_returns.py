"""Corporate-action-consistent analytical return series builder (Issue 116).

Pure-function builder that constructs AnalyticalReturnSeriesV1 from causally
ordered session observations and corporate action adjustments.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from drift.domain.analytical_returns import (
    ADJUSTMENT_METHOD_TOTAL_RETURN,
    AnalyticalAdjustmentMethod,
    AnalyticalReturnSeriesV1,
    AnalyticalReturnSessionV1,
    analytical_return_series_hash,
)
from drift.domain.common import (
    UUID7,
    NonBlankStr,
    SHA256Hash,
)
from drift.domain.evaluator_portfolio import IndeterminateValuationError
from drift.domain.sessions import SessionKeyV1


@dataclass(frozen=True)
class SessionObservationRecord:
    """One session observation record used as input to series construction."""

    session_key: SessionKeyV1
    close_price: Decimal
    observation_hash: SHA256Hash


@dataclass(frozen=True)
class CorporateActionAdjustment:
    """One corporate action adjustment applicable on an effective date."""

    effective_date: date
    split_ratio: Decimal = Decimal("1")
    cash_distribution: Decimal = Decimal("0")
    effect_hash: SHA256Hash = ""


def build_analytical_return_series(
    *,
    security_id: UUID7,
    grade: Literal["exploratory", "promotion"],
    adjustment_method: AnalyticalAdjustmentMethod = ADJUSTMENT_METHOD_TOTAL_RETURN,
    observations: Sequence[SessionObservationRecord],
    adjustments: Sequence[CorporateActionAdjustment] = (),
    acknowledged_limitations: tuple[NonBlankStr, ...] = (),
) -> AnalyticalReturnSeriesV1:
    """Build an AnalyticalReturnSeriesV1 from observations and adjustments.

    Applies exact point-in-time corporate action adjustments to compute
    causal close-to-close returns and compound analytical close prices.
    """
    if not observations:
        raise IndeterminateValuationError(
            "analytical return series requires at least one observation"
        )

    # Sort observations chronologically
    sorted_obs = sorted(observations, key=lambda o: o.session_key.local_date)

    # Check for duplicate session dates
    dates = [o.session_key.local_date for o in sorted_obs]
    if len(dates) != len(set(dates)):
        raise IndeterminateValuationError(
            "duplicate session dates in observation inputs"
        )

    # Group adjustments by effective date
    adj_by_date: dict[date, list[CorporateActionAdjustment]] = {}
    applied_hashes: set[SHA256Hash] = set()
    for adj in adjustments:
        if adj.split_ratio <= Decimal("0"):
            raise IndeterminateValuationError(
                "corporate action split ratio must be strictly positive"
            )
        if adj.cash_distribution < Decimal("0"):
            raise IndeterminateValuationError(
                "corporate action cash distribution cannot be negative"
            )
        adj_by_date.setdefault(adj.effective_date, []).append(adj)
        if adj.effect_hash:
            applied_hashes.add(adj.effect_hash)

    sessions: list[AnalyticalReturnSessionV1] = []
    first_obs = sorted_obs[0]
    if first_obs.close_price <= Decimal("0"):
        raise IndeterminateValuationError("close price must be strictly positive")

    # Base session 0: analytical_close = unadjusted_close, return = None
    analytical_close = first_obs.close_price
    cumulative_split = Decimal("1")

    sessions.append(
        AnalyticalReturnSessionV1(
            session_key=first_obs.session_key,
            unadjusted_close=first_obs.close_price,
            analytical_close=analytical_close,
            return_from_prior=None,
            cumulative_split_factor=cumulative_split,
        )
    )

    prior_unadjusted = first_obs.close_price

    for obs in sorted_obs[1:]:
        curr_unadjusted = obs.close_price
        if curr_unadjusted <= Decimal("0"):
            raise IndeterminateValuationError("close price must be strictly positive")

        # Aggregate adjustments effective on this session date
        eff_adjs = adj_by_date.get(obs.session_key.local_date, [])
        step_split = Decimal("1")
        step_cash = Decimal("0")
        for adj in eff_adjs:
            step_split *= adj.split_ratio
            step_cash += adj.cash_distribution

        cumulative_split *= step_split

        # Compute return from prior session close to current session close
        if adjustment_method == ADJUSTMENT_METHOD_TOTAL_RETURN:
            # (step_split * curr_price + step_cash) / prior_price - 1
            wealth_ratio = (step_split * curr_unadjusted + step_cash) / prior_unadjusted
            return_val = wealth_ratio - Decimal("1")
        else:
            # price return only: (step_split * curr_price) / prior_price - 1
            wealth_ratio = (step_split * curr_unadjusted) / prior_unadjusted
            return_val = wealth_ratio - Decimal("1")

        analytical_close = analytical_close * (Decimal("1") + return_val)

        sessions.append(
            AnalyticalReturnSessionV1(
                session_key=obs.session_key,
                unadjusted_close=curr_unadjusted,
                analytical_close=analytical_close,
                return_from_prior=return_val,
                cumulative_split_factor=cumulative_split,
            )
        )

        prior_unadjusted = curr_unadjusted

    obs_hashes = tuple(
        sorted({o.observation_hash for o in sorted_obs if o.observation_hash})
    )
    eff_hashes = tuple(sorted(applied_hashes))
    interval = (sessions[0].session_key, sessions[-1].session_key)

    draft = AnalyticalReturnSeriesV1.model_construct(
        schema_version="1",
        security_id=security_id,
        grade=grade,
        adjustment_method=adjustment_method,
        sessions=tuple(sessions),
        lookback_interval=interval,
        source_observation_hashes=obs_hashes,
        applied_effect_hashes=eff_hashes,
        acknowledged_limitations=acknowledged_limitations,
        series_hash="0" * 64,
    )
    return draft.model_copy(
        update={"series_hash": analytical_return_series_hash(draft)}
    )
