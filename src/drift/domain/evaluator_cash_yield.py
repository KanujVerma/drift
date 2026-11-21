"""M2 optional point-in-time cash yield: the policy, its rates and the accrual.

Idle cash in an evaluation book earns nothing unless the caller supplies a
``CashYieldPolicyV1``. The policy is caller evidence, not a provider fact: it
names the source its rates were read from, binds the retained source bytes by
hash, and states every convention the accrual needs (day count and rounding
quantum), so that none is a hidden default. Modeled interest is EXPLORATORY
and never promotion-grade.

One function, ``cash_interest``, computes every accrual. The engine calls it
to credit the book and the trace event calls it again to check what was
credited, so the two can never disagree about the formula. All arithmetic is
exact: rationals for the product and the single rounding, decimals only for
the final amount.
"""

from bisect import bisect_left
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.evaluator_portfolio import (
    CanonicalMoney,
    canonical_money,
    decimal_context,
)
from drift.errors import DriftError
from drift.serialization.canonical import content_hash

CASH_YIELD_LIMITATION: NonBlankStr = "hypothetical-exploratory-modeled-cash-yield"
"""The limitation every cash-yield policy must acknowledge."""

CASH_YIELD_TERMS_HASH_PROFILE = "drift-cash-yield-policy-terms-v1"
"""Names the preimage of ``cash_yield_policy_terms_hash``."""

type CashYieldDayCount = Literal["ACT/360", "ACT/365F"]
"""Actual calendar days over a fixed 360 or 365 day year."""

MAX_ANNUALIZED_CASH_RATE = Decimal("1")
"""The highest admissible rate: 100% a year, as a fraction.

Rates are fractions per year, so ``0.0525`` is 5.25%. A value above one is far
more likely a percentage typed where a fraction belongs (``5.25``) than a real
cash rate, so it is refused rather than compounded into a book.
"""

_DAY_COUNT_BASIS: dict[str, int] = {"ACT/360": 360, "ACT/365F": 365}
_ZERO = Decimal("0")


class CashYieldRefusedError(DriftError, ValueError):
    """Raised when a cash-yield policy, rate or accrual is refused.

    Every refusal fails closed: no interest is credited on a policy the
    evaluator cannot prove admissible, causal and exactly computable.
    """


def _exact_date(value: date) -> date:
    """``value`` as an exact ``date``, read through the base methods only."""
    return date.fromordinal(date.toordinal(value))


def _is_positive_power_of_ten(value: Decimal) -> bool:
    """Whether ``value`` is exactly ``10 ** n`` for some integer ``n``.

    Read from the digits themselves, so the answer never depends on the
    ambient decimal context.
    """
    sign, digits, exponent = value.as_tuple()
    if sign or not isinstance(exponent, int):
        return False
    return digits[0] == 1 and not any(digits[1:])


def _exact_finite_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal) or type(value) is not Decimal:
        raise CashYieldRefusedError(
            f"cash interest requires an exact Decimal {name}, got "
            f"{type(value).__name__}"
        )
    if not value.is_finite():
        raise CashYieldRefusedError(f"cash interest requires a finite {name}")
    return value


def cash_interest(
    *,
    cash: Decimal,
    annualized_rate: Decimal,
    accrual_days: int,
    day_count: CashYieldDayCount,
    quantum: Decimal,
) -> Decimal:
    """Simple interest on ``cash`` over ``accrual_days``, rounded exactly once.

    ``exact = cash * annualized_rate * accrual_days / basis`` is computed in
    rationals, with ``basis`` 360 or 365 by ``day_count``. It is then rounded
    to a whole number of ``quantum`` units, ties to even (the rounding the
    portfolio context pins), and returned in the canonical money spelling.
    That one rounding is the only inexact step, and the policy declares it.

    Cash that is zero or negative accrues nothing: this models interest on
    idle cash, never a borrowing charge. A result the pinned portfolio
    context cannot hold exactly is refused, not rounded a second time.
    """
    cash = _exact_finite_decimal(cash, "cash")
    annualized_rate = _exact_finite_decimal(annualized_rate, "annualized rate")
    quantum = _exact_finite_decimal(quantum, "interest quantum")
    if type(accrual_days) is not int or accrual_days < 1:
        raise CashYieldRefusedError(
            f"cash interest accrues over at least one whole day, got {accrual_days!r}"
        )
    basis = _DAY_COUNT_BASIS.get(day_count) if type(day_count) is str else None
    if basis is None:
        raise CashYieldRefusedError(
            f"cash interest does not know the day count {day_count!r}"
        )
    if annualized_rate < _ZERO or annualized_rate > MAX_ANNUALIZED_CASH_RATE:
        raise CashYieldRefusedError(
            "an annualized cash rate is a fraction per year between 0 and "
            f"{MAX_ANNUALIZED_CASH_RATE}, got {annualized_rate}"
        )
    if not _is_positive_power_of_ten(quantum):
        raise CashYieldRefusedError(
            f"the interest quantum must be a positive power of ten, got {quantum}"
        )
    if cash <= _ZERO:
        return _ZERO
    step = Fraction(quantum)
    exact = Fraction(cash) * Fraction(annualized_rate) * accrual_days / basis
    # ``round`` of a Fraction is exact and rounds a tie to the even integer.
    units = round(exact / step)
    held: Decimal | None = None
    try:
        with decimal_context():
            interest = Decimal(units) * quantum
        if Fraction(interest) == units * step:
            held = canonical_money(interest)
    except ArithmeticError, ValueError:
        held = None
    if held is None:
        raise CashYieldRefusedError(
            f"interest of {units} units of {quantum} cannot be held exactly in "
            "the pinned portfolio context; it is refused, not rounded"
        )
    return held


class CashRateObservationV1(FrozenModel):
    """One annualized cash rate as a caller's source stated it for one date.

    ``rate_date`` is the local date of the session whose closing cash starts
    accruing at this rate. ``known_at`` is the instant the caller's source
    made the rate knowable. It is asserted by the caller: the evaluator
    enforces its ordering against the session clock, not its truth.
    """

    schema_version: Literal["1"] = "1"
    rate_date: date
    annualized_rate: CanonicalMoney
    known_at: UTCDateTime

    @field_validator("rate_date")
    @classmethod
    def canonical_rate_date(cls, value: date) -> date:
        return _exact_date(value)

    @model_validator(mode="after")
    def validate_rate(self) -> Self:
        if self.annualized_rate < _ZERO:
            raise ValueError(
                "an annualized cash rate cannot be negative, got "
                f"{self.annualized_rate}"
            )
        if self.annualized_rate > MAX_ANNUALIZED_CASH_RATE:
            raise ValueError(
                "an annualized cash rate is a fraction per year and cannot exceed "
                f"{MAX_ANNUALIZED_CASH_RATE}, got {self.annualized_rate}"
            )
        return self


class CashYieldPolicyV1(FrozenModel):
    """A caller-declared, point-in-time cash rate series and its conventions.

    The day count and the rounding quantum have no default: an accrual
    convention nobody chose is a hidden assumption about money. The rates are
    held in date order whatever order the caller supplied, so the policy has
    one content hash. ``source_sha256`` binds the retained source bytes the
    rates were read from. A matching hash shows the bytes are the same; it
    does not authenticate where they came from.
    """

    schema_version: Literal["1"] = "1"
    source_id: NonBlankStr
    source_sha256: SHA256Hash
    currency_namespace: NonBlankStr
    currency_code: NonBlankStr
    day_count: CashYieldDayCount
    interest_quantum: CanonicalMoney
    rates: tuple[CashRateObservationV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...] = (CASH_YIELD_LIMITATION,)

    @field_validator("interest_quantum")
    @classmethod
    def require_power_of_ten_quantum(cls, value: Decimal) -> Decimal:
        if not _is_positive_power_of_ten(value):
            raise ValueError(
                f"the interest quantum must be a positive power of ten, got {value}"
            )
        return value

    @field_validator("rates")
    @classmethod
    def canonicalize_rates(
        cls, values: tuple[CashRateObservationV1, ...]
    ) -> tuple[CashRateObservationV1, ...]:
        if not values:
            raise ValueError("a cash yield policy requires at least one rate")
        ordinals = tuple(date.toordinal(item.rate_date) for item in values)
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("a cash yield policy carries at most one rate per date")
        return tuple(sorted(values, key=lambda item: date.toordinal(item.rate_date)))

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("acknowledged limitations must be unique")
        if CASH_YIELD_LIMITATION not in values:
            raise ValueError(
                "a cash yield policy must acknowledge the limitation "
                f"{CASH_YIELD_LIMITATION}"
            )
        return tuple(sorted(values))

    def rate_for(self, rate_date: date) -> CashRateObservationV1 | None:
        """The rate stated for exactly ``rate_date``, or ``None``.

        Never the nearest earlier record. A date the source did not state has
        no rate, and carrying another date's rate onto it would invent one.
        """
        wanted = date.toordinal(rate_date)
        position = bisect_left(
            self.rates, wanted, key=lambda item: date.toordinal(item.rate_date)
        )
        if position == len(self.rates):
            return None
        found = self.rates[position]
        return found if date.toordinal(found.rate_date) == wanted else None


def cash_yield_policy_terms_hash(policy: CashYieldPolicyV1) -> SHA256Hash:
    """The identity of a policy's source and conventions, without its rates.

    A trace event names the policy it was credited under by this hash. The
    rate series is left out on purpose: an event must not change because a
    rate dated after it changed, and the one rate an accrual did read is bound
    by its own record hash. The complete policy, rates included, is bound by
    the evaluator evidence hash in the run identity.
    """
    terms = policy.model_dump(mode="python")
    del terms["rates"]
    return content_hash({"profile": CASH_YIELD_TERMS_HASH_PROFILE, "terms": terms})
