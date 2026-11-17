"""Unit tests for the optional point-in-time cash yield (exploratory).

Idle cash earns interest only when the caller supplies a
``CashYieldPolicyV1``. These tests pin the accrual formula against an
independent oracle, the policy and trace-event refusals, the kernel credit,
and the order in which the engine credits interest within a session.

The fixture builders here are shared with the adversarial acceptance tests in
``tests/adversarial/test_m2_cash_yield.py``.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Context, Decimal, localcontext
from fractions import Fraction
from functools import cache
from hashlib import sha256
from typing import Any

import pytest
import test_evaluator_engine as eng
from pydantic import ValidationError

from drift.baselines import B0CashStrategy
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_cash_yield import (
    CASH_YIELD_LIMITATION,
    MAX_ANNUALIZED_CASH_RATE,
    CashRateObservationV1,
    CashYieldDayCount,
    CashYieldPolicyV1,
    CashYieldRefusedError,
    cash_interest,
    cash_yield_policy_terms_hash,
)
from drift.domain.evaluator_portfolio import (
    LaneAdmissibilityError,
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioFillV1,
    PortfolioStateV2,
    canonical_money,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.domain.evaluator_trace import (
    CashInterestAccruedTraceEventV1,
    EvaluationPhase,
    EvaluationTraceLogV1,
    EvaluationTraceLogV2,
    SessionStartTraceEventV1,
    seal_observed_evaluation_trace_log,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.errors import DriftError
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.evaluator.portfolio import PortfolioAccountingKernel, initial_portfolio_state
from drift.serialization.canonical import canonical_json, content_hash

# Four consecutive sessions, then a weekend: Tuesday to Friday, then Monday.
CASH_DAYS = (
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
    date(2026, 1, 9),
    date(2026, 1, 12),
)
CASH_RATE = "0.0525"
INITIAL_CASH = "100000.00"
SOURCE_SHA256 = sha256(b"synthetic cash rate series, tests only").hexdigest()

#: The worked example of the design: ACT/360, 5.25%, quantum 0.01, 100000.
EXPECTED_CASH_SERIES = (
    Decimal("100000"),
    Decimal("100014.58"),
    Decimal("100029.17"),
    Decimal("100043.76"),
    Decimal("100087.53"),
)
EXPECTED_INTEREST = (
    Decimal("14.58"),
    Decimal("14.59"),
    Decimal("14.59"),
    Decimal("43.77"),
)


# --- shared fixture builders -------------------------------------------


def known_at_close(day: date) -> datetime:
    """A rate published at the close of its own date, before the next open."""
    return eng._close_of(day)


def cash_rate(
    day: date, rate: str = CASH_RATE, *, known_at: datetime | None = None
) -> CashRateObservationV1:
    return CashRateObservationV1(
        rate_date=day,
        annualized_rate=Decimal(rate),
        known_at=known_at_close(day) if known_at is None else known_at,
    )


def cash_policy(
    *,
    days: Sequence[date] = CASH_DAYS,
    rates: Mapping[date, str] | None = None,
    records: tuple[CashRateObservationV1, ...] | None = None,
    **changes: Any,
) -> CashYieldPolicyV1:
    """A policy stating one rate for every date an accrual over ``days`` reads.

    The last session's date is never read: nothing accrues from its close.
    """
    stated = dict.fromkeys(days[:-1], CASH_RATE) | dict(rates or {})
    values: dict[str, Any] = {
        "source_id": "synthetic-cash-rate-series-v1",
        "source_sha256": SOURCE_SHA256,
        "currency_namespace": eng.BOOK_NAMESPACE,
        "currency_code": eng.BOOK_CODE,
        "day_count": "ACT/360",
        "interest_quantum": Decimal("0.01"),
        "rates": (
            tuple(cash_rate(day, rate) for day, rate in stated.items())
            if records is None
            else records
        ),
    }
    return CashYieldPolicyV1(**(values | changes))


def _decision_view(day: date) -> DerivedObservationViewV1:
    cutoff = eng._close_of(day)
    observation = eng._template_view().query.observation.model_copy(
        update={
            "security_id": eng.SEC_A,
            "listing_id": eng.LISTING_A,
            "session_date": day,
            "decision_time": cutoff,
            "knowledge_cutoff": cutoff,
            "effective_cutoff": cutoff,
        }
    )
    return eng._restated_view(
        role="decision",
        observation=observation,
        security_id=eng.SEC_A,
        listing_id=eng.LISTING_A,
        source_day=day,
        open_price="100.00",
        close_price="100.00",
    )


def _accounting_view(day: date) -> DerivedObservationViewV1:
    base = dict(eng._template_view().query.observation)
    for name in ("kind", "decision_time", "knowledge_cutoff", "effective_cutoff"):
        base.pop(name, None)
    horizon = eng._close_of(day)
    observation = ObservationOutcomeQueryV1(
        **(
            base
            | {
                "kind": "outcome",
                "security_id": eng.SEC_A,
                "listing_id": eng.LISTING_A,
                "session_date": day,
                "economic_horizon": horizon,
                "evidence_vintage_cutoff": horizon,
            }
        )
    )
    return eng._restated_view(
        role="outcome",
        observation=observation,
        security_id=eng.SEC_A,
        listing_id=eng.LISTING_A,
        source_day=day,
        open_price="100.00",
        close_price="100.00",
    )


@cache
def cash_bundle(days: tuple[date, ...] = CASH_DAYS) -> EvaluationInputBundleV1:
    """A realized-lane bundle over ``days`` pricing SEC_A flat at 100.00."""
    return eng._bundle(
        days=days,
        decision_views=tuple(_decision_view(day) for day in days[1:]),
        accounting_views=tuple(_accounting_view(day) for day in days),
    )


def cash_engine(
    *,
    policy: CashYieldPolicyV1 | None,
    bundle: EvaluationInputBundleV1 | None = None,
    cash: str = INITIAL_CASH,
) -> SessionEvaluatorEngine:
    resolved = cash_bundle() if bundle is None else bundle
    return SessionEvaluatorEngine(
        bundle=resolved,
        admission=eng._admission(resolved),
        protocol=eng._protocol(cash=cash),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS, cash_yield=policy
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )


def run_cash(
    engine: SessionEvaluatorEngine,
    strategy: B0CashStrategy | eng.FixedTargetStrategy | None = None,
) -> EvaluationRunArtifactsV2:
    """Run ``strategy`` (the B0 cash baseline unless stated) under a V1 identity."""
    resolved = B0CashStrategy() if strategy is None else strategy
    return engine.run(
        strategy=resolved,
        run_identity=eng._run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
            strategy_hash=resolved.strategy_reference.code_hash,
        ),
    )


def interest_events(
    artifacts: EvaluationRunArtifactsV2,
) -> tuple[CashInterestAccruedTraceEventV1, ...]:
    return tuple(
        event
        for event in artifacts.trace.events
        if isinstance(event, CashInterestAccruedTraceEventV1)
    )


# ==========================================================================
# 1. The accrual formula
# ==========================================================================


def _oracle(
    cash: Decimal, rate: Decimal, days: int, basis: int, quantum: Decimal
) -> Fraction:
    """Half-even rounding in integers, independent of ``round`` and decimals."""
    units = Fraction(cash) * Fraction(rate) * days / basis / Fraction(quantum)
    whole, remainder = divmod(units.numerator, units.denominator)
    twice = 2 * remainder
    if twice > units.denominator or (twice == units.denominator and whole % 2):
        whole += 1
    return whole * Fraction(quantum)


def test_cash_interest_equals_an_independent_rational_oracle() -> None:
    bases: dict[CashYieldDayCount, int] = {"ACT/360": 360, "ACT/365F": 365}
    checked = 0
    for cash in ("100000", "100014.58", "0.01", "12345.67", "999999999999.99"):
        for rate in ("0", "0.0525", "0.0001", "0.04321", "1"):
            for days in (1, 3, 4, 366):
                for day_count, basis in bases.items():
                    for quantum in ("0.01", "0.0001", "1", "10"):
                        result = cash_interest(
                            cash=Decimal(cash),
                            annualized_rate=Decimal(rate),
                            accrual_days=days,
                            day_count=day_count,
                            quantum=Decimal(quantum),
                        )
                        assert Fraction(result) == _oracle(
                            Decimal(cash), Decimal(rate), days, basis, Decimal(quantum)
                        )
                        # The amount is already in the one canonical spelling.
                        assert str(result) == str(canonical_money(result))
                        checked += 1
    assert checked == 5 * 5 * 4 * 2 * 4


@pytest.mark.parametrize(
    ("cash", "days", "expected"),
    [
        ("100000", 1, "14.58"),
        ("100014.58", 1, "14.59"),
        ("100029.17", 1, "14.59"),
        ("100043.76", 3, "43.77"),
    ],
)
def test_cash_interest_reproduces_the_worked_example(
    cash: str, days: int, expected: str
) -> None:
    assert cash_interest(
        cash=Decimal(cash),
        annualized_rate=Decimal(CASH_RATE),
        accrual_days=days,
        day_count="ACT/360",
        quantum=Decimal("0.01"),
    ) == Decimal(expected)


@pytest.mark.parametrize(
    ("cash", "expected"),
    [("100", "0"), ("300", "0.02"), ("500", "0.02"), ("700", "0.04")],
)
def test_cash_interest_rounds_an_exact_tie_to_the_even_quantum(
    cash: str, expected: str
) -> None:
    # 1.8% over one day of 360 is exactly cash / 20000: 0.005, 0.015, 0.025, 0.035.
    assert Fraction(cash) * Fraction("0.018") / 360 * 200 % 1 == 0
    assert cash_interest(
        cash=Decimal(cash),
        annualized_rate=Decimal("0.018"),
        accrual_days=1,
        day_count="ACT/360",
        quantum=Decimal("0.01"),
    ) == Decimal(expected)


def test_a_three_day_gap_is_rounded_once_and_not_as_three_rounded_days() -> None:
    def accrue(days: int) -> Decimal:
        return cash_interest(
            cash=Decimal("100000"),
            annualized_rate=Decimal(CASH_RATE),
            accrual_days=days,
            day_count="ACT/360",
            quantum=Decimal("0.01"),
        )

    # Three days are exactly 43.75. One day is 14.5833..., so three separately
    # rounded days would credit a cent less.
    assert accrue(3) == Decimal("43.75")
    assert accrue(1) == Decimal("14.58")
    assert accrue(1) + accrue(1) + accrue(1) == Decimal("43.74")


def test_cash_interest_day_count_changes_the_basis() -> None:
    def accrue(day_count: CashYieldDayCount) -> Decimal:
        return cash_interest(
            cash=Decimal("100000"),
            annualized_rate=Decimal(CASH_RATE),
            accrual_days=1,
            day_count=day_count,
            quantum=Decimal("0.01"),
        )

    assert accrue("ACT/360") == Decimal("14.58")
    assert accrue("ACT/365F") == Decimal("14.38")


@pytest.mark.parametrize("cash", ["0", "-0.01", "-100000"])
def test_cash_that_is_not_positive_accrues_nothing(cash: str) -> None:
    assert cash_interest(
        cash=Decimal(cash),
        annualized_rate=Decimal(CASH_RATE),
        accrual_days=1,
        day_count="ACT/360",
        quantum=Decimal("0.01"),
    ) == Decimal("0")


def test_a_zero_rate_accrues_nothing() -> None:
    assert cash_interest(
        cash=Decimal("100000"),
        annualized_rate=Decimal("0"),
        accrual_days=3,
        day_count="ACT/360",
        quantum=Decimal("0.01"),
    ) == Decimal("0")


def test_cash_interest_ignores_the_ambient_decimal_context() -> None:
    arguments: dict[str, Any] = {
        "cash": Decimal("100043.76"),
        "annualized_rate": Decimal(CASH_RATE),
        "accrual_days": 3,
        "day_count": "ACT/360",
        "quantum": Decimal("0.01"),
    }
    baseline = cash_interest(**arguments)

    with localcontext(Context(prec=2, rounding=ROUND_UP)):
        perturbed = cash_interest(**arguments)

    assert str(perturbed) == str(baseline) == "43.77"


class _SpoofedDecimal(Decimal):
    """A Decimal subclass, which could answer comparisons as it chose."""


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"cash": 100000}, r"requires an exact Decimal cash, got int"),
        ({"cash": 100000.0}, r"requires an exact Decimal cash, got float"),
        ({"cash": _SpoofedDecimal("1")}, r"an exact Decimal cash, got _SpoofedDecimal"),
        ({"cash": Decimal("NaN")}, r"requires a finite cash"),
        ({"cash": Decimal("Infinity")}, r"requires a finite cash"),
        ({"annualized_rate": "0.05"}, r"an exact Decimal annualized rate, got str"),
        ({"annualized_rate": Decimal("NaN")}, r"requires a finite annualized rate"),
        ({"annualized_rate": Decimal("-0.0001")}, r"between 0 and 1, got -0.0001"),
        ({"annualized_rate": Decimal("1.0001")}, r"between 0 and 1, got 1.0001"),
        ({"annualized_rate": Decimal("5.25")}, r"between 0 and 1, got 5.25"),
        ({"accrual_days": 0}, r"at least one whole day, got 0"),
        ({"accrual_days": -1}, r"at least one whole day, got -1"),
        ({"accrual_days": True}, r"at least one whole day, got True"),
        ({"accrual_days": 1.0}, r"at least one whole day, got 1.0"),
        ({"day_count": "30/360"}, r"does not know the day count '30/360'"),
        ({"day_count": None}, r"does not know the day count None"),
        ({"quantum": Decimal("0")}, r"positive power of ten, got 0"),
        ({"quantum": Decimal("-0.01")}, r"positive power of ten, got -0.01"),
        ({"quantum": Decimal("0.05")}, r"positive power of ten, got 0.05"),
        ({"quantum": Decimal("0.011")}, r"positive power of ten, got 0.011"),
        ({"quantum": Decimal("Infinity")}, r"requires a finite interest quantum"),
        ({"quantum": 0.01}, r"an exact Decimal interest quantum, got float"),
    ],
)
def test_cash_interest_refuses_an_inexact_or_out_of_range_input(
    change: dict[str, Any], problem: str
) -> None:
    arguments: dict[str, Any] = {
        "cash": Decimal("100000"),
        "annualized_rate": Decimal(CASH_RATE),
        "accrual_days": 1,
        "day_count": "ACT/360",
        "quantum": Decimal("0.01"),
    }

    with pytest.raises(CashYieldRefusedError, match=problem):
        cash_interest(**(arguments | change))


def test_cash_interest_refuses_an_amount_the_book_cannot_hold_exactly() -> None:
    # A tenth of the cash: 35 significant digits of interest, one too many.
    with pytest.raises(CashYieldRefusedError, match=r"cannot be held exactly"):
        cash_interest(
            cash=Decimal("4" + "1" * 34 + "0"),
            annualized_rate=Decimal("1"),
            accrual_days=36,
            day_count="ACT/360",
            quantum=Decimal("1"),
        )


def test_the_refusal_is_a_drift_value_error() -> None:
    assert issubclass(CashYieldRefusedError, DriftError)
    assert issubclass(CashYieldRefusedError, ValueError)


# ==========================================================================
# 2. The policy and its rate records
# ==========================================================================


def test_a_policy_holds_its_rates_in_date_order() -> None:
    policy = cash_policy()

    assert tuple(item.rate_date for item in policy.rates) == CASH_DAYS[:-1]
    assert policy.acknowledged_limitations == (CASH_YIELD_LIMITATION,)
    assert policy.day_count == "ACT/360"


def test_the_caller_order_of_rates_does_not_move_the_content_hash() -> None:
    forward = tuple(cash_rate(day) for day in CASH_DAYS)
    shuffled = (forward[3], forward[0], forward[4], forward[2], forward[1])

    assert content_hash(cash_policy(records=forward)) == content_hash(
        cash_policy(records=shuffled)
    )
    assert cash_policy(records=shuffled).rates == forward
    # Control: one changed rate moves it.
    changed = (cash_rate(CASH_DAYS[0], "0.05"), *forward[1:])
    assert content_hash(cash_policy(records=changed)) != content_hash(
        cash_policy(records=forward)
    )


def test_rate_for_answers_only_the_exact_date() -> None:
    policy = cash_policy(rates={CASH_DAYS[1]: "0.04"})

    found = policy.rate_for(CASH_DAYS[1])
    assert found is not None
    assert found.annualized_rate == Decimal("0.04")
    assert found.known_at == known_at_close(CASH_DAYS[1])
    # A date between two stated dates, and dates outside them, have no rate.
    assert policy.rate_for(date(2026, 1, 10)) is None
    assert policy.rate_for(CASH_DAYS[-1]) is None
    assert policy.rate_for(CASH_DAYS[0] - timedelta(days=1)) is None


@pytest.mark.parametrize(
    ("rate", "problem"),
    [
        ("-0.0001", r"cannot be negative, got -0.0001"),
        ("1.0001", r"cannot exceed 1, got 1.0001"),
        ("5.25", r"cannot exceed 1, got 5.25"),
    ],
)
def test_a_rate_record_refuses_a_rate_outside_zero_to_one(
    rate: str, problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem):
        cash_rate(CASH_DAYS[0], rate)


def test_a_rate_record_admits_the_bounds_and_spells_its_rate_canonically() -> None:
    assert cash_rate(CASH_DAYS[0], "0").annualized_rate == Decimal("0")
    assert cash_rate(CASH_DAYS[0], "1").annualized_rate == MAX_ANNUALIZED_CASH_RATE
    assert str(cash_rate(CASH_DAYS[0], "0.052500").annualized_rate) == "0.0525"
    assert content_hash(cash_rate(CASH_DAYS[0], "0.052500")) == content_hash(
        cash_rate(CASH_DAYS[0], "0.0525")
    )


@pytest.mark.parametrize(
    "change",
    [
        {"annualized_rate": 0.0525},
        {"annualized_rate": "0.0525"},
        {"annualized_rate": Decimal("NaN")},
        {"known_at": datetime(2026, 1, 6, 21, 0)},
        {"rate_date": "2026-01-06"},
        {"rate_date": datetime(2026, 1, 6, 21, 0, tzinfo=UTC)},
    ],
    ids=[
        "float-rate",
        "text-rate",
        "nan-rate",
        "naive-known-at",
        "text-date",
        "datetime-for-date",
    ],
)
def test_a_rate_record_refuses_an_inexact_member(change: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "rate_date": CASH_DAYS[0],
        "annualized_rate": Decimal(CASH_RATE),
        "known_at": known_at_close(CASH_DAYS[0]),
    }

    with pytest.raises(ValidationError):
        CashRateObservationV1(**(values | change))


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"records": ()}, r"requires at least one rate"),
        (
            {
                "records": (
                    cash_rate(CASH_DAYS[0]),
                    cash_rate(CASH_DAYS[0], "0.04"),
                )
            },
            r"at most one rate per date",
        ),
        ({"interest_quantum": Decimal("0")}, r"positive power of ten, got 0"),
        ({"interest_quantum": Decimal("-0.01")}, r"positive power of ten, got -0.01"),
        ({"interest_quantum": Decimal("0.05")}, r"positive power of ten, got 0.05"),
        ({"interest_quantum": Decimal("0.025")}, r"positive power of ten"),
        ({"acknowledged_limitations": ()}, r"must acknowledge the limitation"),
        (
            {"acknowledged_limitations": ("some-other-limitation",)},
            r"must acknowledge the limitation",
        ),
        (
            {
                "acknowledged_limitations": (
                    CASH_YIELD_LIMITATION,
                    CASH_YIELD_LIMITATION,
                )
            },
            r"acknowledged limitations must be unique",
        ),
        ({"day_count": "30/360"}, r"day_count"),
        ({"source_sha256": "not a digest"}, r"source_sha256"),
        ({"source_id": "   "}, r"source_id"),
        ({"currency_code": ""}, r"currency_code"),
    ],
    ids=[
        "empty-rates",
        "duplicate-rate-date",
        "zero-quantum",
        "negative-quantum",
        "quantum-not-a-power-of-ten",
        "quantum-two-digits",
        "no-limitation",
        "other-limitation-only",
        "repeated-limitation",
        "unknown-day-count",
        "malformed-source-hash",
        "blank-source-id",
        "blank-currency",
    ],
)
def test_a_policy_refuses_a_malformed_member(
    change: dict[str, Any], problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem):
        cash_policy(**change)


@pytest.mark.parametrize("missing", ["day_count", "interest_quantum"])
def test_a_policy_has_no_default_accrual_convention(missing: str) -> None:
    values = cash_policy().model_dump(mode="python")
    del values[missing]

    with pytest.raises(ValidationError, match=missing):
        CashYieldPolicyV1.model_validate(values)


@pytest.mark.parametrize("quantum", ["0.0001", "0.01", "0.1", "1", "10", "100"])
def test_a_policy_admits_every_positive_power_of_ten_quantum(quantum: str) -> None:
    assert cash_policy(interest_quantum=Decimal(quantum)).interest_quantum == Decimal(
        quantum
    )


def test_a_policy_survives_a_strict_json_round_trip() -> None:
    policy = cash_policy(
        acknowledged_limitations=("a-second-limitation", CASH_YIELD_LIMITATION)
    )

    rebuilt = CashYieldPolicyV1.model_validate_json(policy.model_dump_json())

    assert rebuilt == policy
    assert canonical_json(rebuilt) == canonical_json(policy)
    assert rebuilt.acknowledged_limitations == (
        "a-second-limitation",
        CASH_YIELD_LIMITATION,
    )


def test_the_policy_terms_hash_ignores_rates_and_binds_every_convention() -> None:
    policy = cash_policy()
    terms = cash_yield_policy_terms_hash(policy)

    # A rate is bound by its own record hash, never by the terms hash.
    assert cash_yield_policy_terms_hash(cash_policy(rates={CASH_DAYS[3]: "0.01"})) == (
        terms
    )
    assert terms != content_hash(policy)
    for change in (
        {"source_id": "another-source"},
        {"source_sha256": "f" * 64},
        {"currency_namespace": "another-namespace"},
        {"currency_code": "EUR"},
        {"day_count": "ACT/365F"},
        {"interest_quantum": Decimal("0.0001")},
        {"acknowledged_limitations": (CASH_YIELD_LIMITATION, "a-second-limitation")},
    ):
        assert cash_yield_policy_terms_hash(cash_policy(**change)) != terms, change


# ==========================================================================
# 3. The kernel credit
# ==========================================================================


def _kernel(
    *, lane: str = "exploratory"
) -> tuple[PortfolioAccountingKernel, PortfolioStateV2]:
    bundle = eng._bundle()
    admission = (
        eng._admission(bundle)
        if lane == "exploratory"
        else eng._promotion_admission(bundle)
    )
    state = initial_portfolio_state(
        session_key=eng._key(eng.DAY_0),
        initial_cash=Decimal("10000.00"),
        admission=admission,
    )
    return PortfolioAccountingKernel(state, session_clock=eng._clock()), state


def test_a_credit_raises_cash_and_value_by_exactly_the_amount() -> None:
    kernel, before = _kernel()

    kernel.credit_cash_interest(Decimal("1.46"))

    after = kernel.state
    assert after.cash_balance == Decimal("10001.46")
    assert after.net_asset_value == Decimal("10001.46")
    assert after.cash_balance - before.cash_balance == Decimal("1.46")
    assert after.model_dump(
        exclude={"cash_balance", "net_asset_value"}
    ) == before.model_dump(exclude={"cash_balance", "net_asset_value"})
    assert after.realized_gross_pnl == Decimal("0")
    assert after.realized_net_pnl == Decimal("0")
    assert after.cumulative_transaction_costs == Decimal("0")


def test_a_credit_leaves_holdings_costs_realized_results_and_the_mark() -> None:
    kernel, _ = _kernel()
    kernel.apply_fill(
        PortfolioFillV1(
            security_id=eng.SEC_A,
            side="buy",
            quantity=10,
            fill_price=Decimal("100.00"),
            transaction_costs=Decimal("1.25"),
        )
    )
    kernel.apply_fill(
        PortfolioFillV1(
            security_id=eng.SEC_A,
            side="sell",
            quantity=4,
            fill_price=Decimal("110.00"),
            transaction_costs=Decimal("0.75"),
        )
    )
    kernel.mark_close(
        (
            MarkPriceV1(
                security_id=eng.SEC_A,
                close_price=Decimal("120.00"),
                evidence=MarkEvidenceV1(grade="exploratory", evidence_hash="1" * 64),
            ),
        )
    )
    before = kernel.state

    kernel.credit_cash_interest(Decimal("0.01"))

    after = kernel.state
    assert after.cash_balance == before.cash_balance + Decimal("0.01")
    assert after.net_asset_value == before.net_asset_value + Decimal("0.01")
    assert after.model_dump(
        exclude={"cash_balance", "net_asset_value"}
    ) == before.model_dump(exclude={"cash_balance", "net_asset_value"})
    assert after.mark is not None
    assert after.holdings_market_value == Decimal("720")
    assert after.realized_gross_pnl == before.realized_gross_pnl != Decimal("0")
    assert after.realized_net_pnl == before.realized_net_pnl
    assert after.cumulative_transaction_costs == Decimal("2")


@pytest.mark.parametrize(
    ("amount", "error", "problem"),
    [
        (Decimal("0"), ValueError, r"must be strictly positive, got 0"),
        (Decimal("-0.01"), ValueError, r"must be strictly positive, got -0.01"),
        (Decimal("NaN"), ValueError, r"must be finite"),
        (Decimal("Infinity"), ValueError, r"must be finite"),
        (Decimal("-Infinity"), ValueError, r"must be finite"),
        (1, TypeError, r"exact Decimal, got int"),
        (0.01, TypeError, r"exact Decimal, got float"),
        ("0.01", TypeError, r"exact Decimal, got str"),
        (None, TypeError, r"exact Decimal, got NoneType"),
        (_SpoofedDecimal("0.01"), TypeError, r"exact Decimal, got _SpoofedDecimal"),
        (Decimal("0." + "0" * 40 + "1"), ValueError, r"cannot be held exactly"),
    ],
    ids=[
        "zero",
        "negative",
        "nan",
        "infinity",
        "negative-infinity",
        "int",
        "float",
        "text",
        "none",
        "decimal-subclass",
        "wider-than-the-book",
    ],
)
def test_a_refused_credit_leaves_the_book_untouched(
    amount: Any, error: type[Exception], problem: str
) -> None:
    kernel, before = _kernel()

    with pytest.raises(error, match=problem):
        kernel.credit_cash_interest(amount)

    assert kernel.state is before
    # The next mutation starts from the untouched book, not a half-applied one.
    kernel.credit_cash_interest(Decimal("0.01"))
    assert kernel.state.cash_balance == Decimal("10000.01")


def test_a_credit_the_book_cannot_hold_exactly_is_refused_not_rounded() -> None:
    kernel, before = _kernel()

    # 10000 plus 1e-30 needs 35 significant digits; the book holds 34.
    with pytest.raises(ValueError, match=r"cannot be held exactly"):
        kernel.credit_cash_interest(Decimal("1E-30"))

    assert kernel.state is before
    # Control: one digit fewer fits, and is held exactly.
    kernel.credit_cash_interest(Decimal("1E-29"))
    assert str(kernel.state.cash_balance) == "10000." + "0" * 28 + "1"


def test_a_promotion_lane_book_refuses_modeled_interest() -> None:
    kernel, before = _kernel(lane="promotion")
    assert before.lane == "promotion"

    with pytest.raises(
        LaneAdmissibilityError, match=r"^promotion lane refuses modeled cash interest"
    ):
        kernel.credit_cash_interest(Decimal("0.01"))

    assert kernel.state is before


def test_a_credit_ignores_the_ambient_decimal_context() -> None:
    kernel, _ = _kernel()

    with localcontext(Context(prec=2, rounding=ROUND_UP)):
        kernel.credit_cash_interest(Decimal("1.46"))

    assert str(kernel.state.cash_balance) == "10001.46"


# ==========================================================================
# 4. The trace event
# ==========================================================================


def _event(**changes: Any) -> CashInterestAccruedTraceEventV1:
    policy = cash_policy()
    record = policy.rates[2]
    values: dict[str, Any] = {
        "sequence": 2,
        "session_index": 1,
        "session_key": eng._key(CASH_DAYS[4]),
        "policy_terms_hash": cash_yield_policy_terms_hash(policy),
        "rate_record_hash": content_hash(record),
        "accrual_start_date": CASH_DAYS[3],
        "accrual_days": 3,
        "annualized_rate": Decimal(CASH_RATE),
        "day_count": "ACT/360",
        "interest_quantum": Decimal("0.01"),
        "accrual_base_cash": Decimal("100043.76"),
        "interest": Decimal("43.77"),
        "cash_balance_after": Decimal("100087.53"),
    }
    return CashInterestAccruedTraceEventV1(**(values | changes))


def test_the_event_states_its_phase_and_its_evidence_grade() -> None:
    event = _event()

    assert event.kind == "cash_interest_accrued"
    assert event.phase is EvaluationPhase.PRE_OPEN_EFFECTS
    assert event.is_promotion_grade_evidence is False


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"interest": Decimal("43.76")}, r"interest must equal 43.77, got 43.76"),
        ({"interest": Decimal("43.78")}, r"interest must equal 43.77, got 43.78"),
        (
            {"interest": Decimal("43.78"), "cash_balance_after": Decimal("100087.54")},
            r"interest must equal 43.77, got 43.78",
        ),
        (
            {"cash_balance_after": Decimal("100087.54")},
            r"cash balance after the credit must equal 100087.53, got 100087.54",
        ),
        (
            {"cash_balance_after": Decimal("100043.76")},
            r"cash balance after the credit must equal 100087.53",
        ),
        (
            {"accrual_days": 1},
            r"accrual of 1 calendar days from 2026-01-09 does not end on the session "
            r"date 2026-01-12",
        ),
        (
            {"accrual_start_date": CASH_DAYS[2]},
            r"accrual of 3 calendar days from 2026-01-08 does not end on the session",
        ),
        ({"day_count": "ACT/365F"}, r"interest must equal 43.17, got 43.77"),
        ({"day_count": "30/360"}, r"day_count"),
        ({"annualized_rate": Decimal("0.05")}, r"interest must equal 41.68"),
        ({"annualized_rate": Decimal("1.5")}, r"between 0 and 1, got 1.5"),
        ({"interest_quantum": Decimal("0.1")}, r"interest must equal 43.8"),
        ({"interest_quantum": Decimal("0.05")}, r"positive power of ten"),
        ({"accrual_base_cash": Decimal("100043.75")}, r"cash balance after"),
        ({"accrual_days": 0, "accrual_start_date": CASH_DAYS[4]}, r"accrual_days"),
        ({"is_promotion_grade_evidence": True}, r"is_promotion_grade_evidence"),
        ({"phase": EvaluationPhase.OPEN_EXECUTION}, r"phase"),
        ({"session_index": 0, "sequence": 0}, r"first session"),
    ],
    ids=[
        "interest-one-cent-low",
        "interest-one-cent-high",
        "interest-and-balance-both-inflated",
        "balance-one-cent-high",
        "balance-without-the-credit",
        "days-not-matching-the-dates",
        "start-date-not-matching-the-days",
        "another-day-count",
        "unknown-day-count",
        "another-rate",
        "rate-above-one",
        "another-quantum",
        "quantum-not-a-power-of-ten",
        "another-base",
        "zero-days",
        "promotion-grade-claim",
        "another-phase",
        "first-session",
    ],
)
def test_the_event_refuses_an_account_that_does_not_reconcile(
    change: dict[str, Any], problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem):
        _event(**change)


def test_the_event_refuses_a_credit_of_nothing() -> None:
    with pytest.raises(ValidationError, match=r"interest must be strictly positive"):
        _event(
            annualized_rate=Decimal("0"),
            interest=Decimal("0"),
            cash_balance_after=Decimal("100043.76"),
        )


def test_the_event_survives_a_strict_json_round_trip() -> None:
    event = _event()

    rebuilt = CashInterestAccruedTraceEventV1.model_validate_json(
        event.model_dump_json()
    )

    assert rebuilt == event
    assert canonical_json(rebuilt) == canonical_json(event)
    assert rebuilt.model_dump_json() == event.model_dump_json()


def _opened_sessions() -> tuple[SessionStartTraceEventV1, SessionStartTraceEventV1]:
    """The two session starts a log needs before the event of session one."""
    first, second = (
        SessionStartTraceEventV1(
            sequence=index,
            session_index=index,
            session_key=eng._key(day),
            session_hash=str(index + 1) * 64,
            opening_cash=Decimal("100043.76"),
            opening_net_asset_value=Decimal("100043.76"),
        )
        for index, day in enumerate(CASH_DAYS[3:])
    )
    return first, second


def test_a_log_holding_the_event_is_version_two_and_round_trips() -> None:
    events = (*_opened_sessions(), _event())

    log = seal_observed_evaluation_trace_log(events)

    assert isinstance(log, EvaluationTraceLogV2)
    assert log.schema_version == "2"
    rebuilt = EvaluationTraceLogV2.model_validate_json(log.model_dump_json())
    assert rebuilt == log
    assert rebuilt.trace_hash == log.trace_hash
    assert isinstance(rebuilt.events[2], CashInterestAccruedTraceEventV1)
    # Without the event the same prefix still seals as the frozen version 1.
    assert seal_observed_evaluation_trace_log(events[:2]).schema_version == "1"


def test_the_frozen_version_one_log_refuses_the_event() -> None:
    events = (*_opened_sessions(), _event())

    with pytest.raises(ValidationError, match=r"cash_interest_accrued"):
        EvaluationTraceLogV1.model_validate(
            {"schema_version": "1", "events": events, "trace_hash": "0" * 64}
        )


# ==========================================================================
# 5. The cash baseline compounds at session frequency
# ==========================================================================


def test_the_cash_baseline_compounds_the_worked_example() -> None:
    policy = cash_policy()
    artifacts = run_cash(cash_engine(policy=policy))

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    series = artifacts.result.metrics.equity_series
    assert tuple(point.cash_balance for point in series) == EXPECTED_CASH_SERIES
    assert tuple(point.net_asset_value for point in series) == EXPECTED_CASH_SERIES
    metrics = artifacts.result.metrics
    assert metrics.initial_cash == Decimal("100000")
    assert metrics.ending_cash == Decimal("100087.53")
    assert metrics.net_profit_and_loss == Decimal("87.53")
    # Interest is not a trading result: nothing was realized, filled or charged.
    assert metrics.realized_gross_pnl == Decimal("0")
    assert metrics.realized_net_pnl == Decimal("0")
    assert metrics.cumulative_transaction_costs == Decimal("0")
    assert metrics.committed_fill_count == 0
    assert artifacts.final_state.cash_balance == Decimal("100087.53")

    events = interest_events(artifacts)
    assert tuple(event.interest for event in events) == EXPECTED_INTEREST
    assert sum((event.interest for event in events), Decimal("0")) == Decimal("87.53")
    assert tuple(event.session_index for event in events) == (1, 2, 3, 4)
    assert tuple(event.accrual_days for event in events) == (1, 1, 1, 3)
    assert tuple(event.accrual_start_date for event in events) == CASH_DAYS[:-1]
    terms = cash_yield_policy_terms_hash(policy)
    for event, record in zip(events, policy.rates, strict=True):
        assert event.policy_terms_hash == terms
        assert event.rate_record_hash == content_hash(record)
        assert event.annualized_rate == Decimal(CASH_RATE)
        assert event.day_count == "ACT/360"
        assert event.interest_quantum == Decimal("0.01")
        assert event.is_promotion_grade_evidence is False


def test_each_credit_is_based_on_that_session_opening_cash() -> None:
    artifacts = run_cash(cash_engine(policy=cash_policy()))
    starts = {
        event.session_index: event
        for event in artifacts.trace.events
        if isinstance(event, SessionStartTraceEventV1)
    }

    events = interest_events(artifacts)
    assert len(events) == len(CASH_DAYS) - 1
    for event in events:
        start = starts[event.session_index]
        assert event.accrual_base_cash == start.opening_cash
        assert event.sequence == start.sequence + 1
        assert event.cash_balance_after == event.accrual_base_cash + event.interest
    # The first session has no earlier close, so it opens on the seed capital.
    assert starts[0].opening_cash == Decimal("100000")
    assert all(event.session_index != 0 for event in events)
    # Each session opens on the cash the previous one closed with.
    assert tuple(starts[index].opening_cash for index in range(5)) == (
        Decimal("100000"),
        *EXPECTED_CASH_SERIES[:-1],
    )


def test_a_run_that_credits_interest_seals_a_version_two_trace() -> None:
    artifacts = run_cash(cash_engine(policy=cash_policy()))

    assert isinstance(artifacts.trace, EvaluationTraceLogV2)
    assert artifacts.trace.schema_version == "2"
    assert artifacts.result.trace_hash == artifacts.trace.trace_hash
    assert artifacts.result.is_promotion_grade_evidence is False
    assert artifacts.result.lane == "exploratory"


def test_cash_yield_artifacts_survive_the_experiment_runner_json_rebuild() -> None:
    artifacts = run_cash(cash_engine(policy=cash_policy()))

    rebuilt = EvaluationRunArtifactsV2.model_validate_json(
        artifacts.model_dump_json(warnings=False)
    )

    assert rebuilt == artifacts
    assert canonical_json(rebuilt) == canonical_json(artifacts)
    assert interest_events(rebuilt) == interest_events(artifacts)


def test_the_day_count_convention_changes_the_credited_interest() -> None:
    artifacts = run_cash(cash_engine(policy=cash_policy(day_count="ACT/365F")))

    # 100000 * 0.0525 / 365 = 14.3835..., then compounding session by session.
    assert tuple(event.interest for event in interest_events(artifacts)) == (
        Decimal("14.38"),
        Decimal("14.39"),
        Decimal("14.39"),
        Decimal("43.17"),
    )
    assert artifacts.result.metrics.net_profit_and_loss == Decimal("86.33")


def test_a_zero_rate_credits_nothing_and_emits_no_event() -> None:
    zero = dict.fromkeys(CASH_DAYS[:-1], "0")
    artifacts = run_cash(cash_engine(policy=cash_policy(rates=zero)))

    assert interest_events(artifacts) == ()
    assert artifacts.trace.schema_version == "1"
    assert artifacts.result.metrics.net_profit_and_loss == Decimal("0")
    assert artifacts.final_state.cash_balance == Decimal("100000")


def test_interest_below_half_a_quantum_credits_nothing() -> None:
    # 3 * 0.0525 / 360 = 0.0004375, which rounds to no cent at all.
    artifacts = run_cash(cash_engine(policy=cash_policy(), cash="3.00"))

    assert interest_events(artifacts) == ()
    assert artifacts.final_state.cash_balance == Decimal("3")


# ==========================================================================
# 6. Ordering inside a session
# ==========================================================================


def buy_at_third_open() -> eng.FixedTargetStrategy:
    """Decide ten SEC_A at the second close, so the buy fills at the third open."""
    return eng.FixedTargetStrategy({day: ((eng.SEC_A, 10),) for day in CASH_DAYS[1:]})


def test_interest_is_credited_on_the_cash_held_before_the_open_fill() -> None:
    artifacts = run_cash(cash_engine(policy=cash_policy()), buy_at_third_open())

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    session_two = [
        event for event in artifacts.trace.events if event.session_index == 2
    ]
    kinds = [event.kind for event in session_two]
    assert kinds == [
        "session_start",
        "cash_interest_accrued",
        "fill",
        "session_mark",
        "strategy_decision",
    ]
    start, credit, fill = session_two[0], session_two[1], session_two[2]
    assert isinstance(start, SessionStartTraceEventV1)
    assert isinstance(credit, CashInterestAccruedTraceEventV1)
    assert fill.kind == "fill"
    # The base is the cash carried from the previous close: no fill has run.
    assert start.opening_cash == Decimal("100014.58")
    assert credit.accrual_base_cash == Decimal("100014.58")
    assert credit.interest == Decimal("14.59")
    assert credit.cash_balance_after == Decimal("100029.17")
    assert credit.sequence < fill.sequence
    # The fill then spends from the credited balance: ten shares at 100.00.
    assert artifacts.result.metrics.equity_series[2].cash_balance == Decimal("99029.17")


def test_interest_never_accrues_on_cash_a_fill_already_spent() -> None:
    artifacts = run_cash(cash_engine(policy=cash_policy()), buy_at_third_open())

    events = {event.session_index: event for event in interest_events(artifacts)}
    # After the buy the book holds 99029.17 in cash and 1000.00 in shares.
    assert events[3].accrual_base_cash == Decimal("99029.17")
    # 99029.17 * 0.0525 / 360 = 14.44175..., on cash alone, never on the shares.
    assert events[3].interest == Decimal("14.44")
    assert events[4].accrual_base_cash == Decimal("99043.61")
    # 99043.61 * 0.0525 * 3 / 360 = 43.33157...
    assert events[4].interest == Decimal("43.33")
    final = artifacts.final_state
    assert final.cash_balance == Decimal("99086.94")
    assert final.holdings_market_value == Decimal("1000")
    assert final.net_asset_value == Decimal("100086.94")
    assert final.realized_gross_pnl == Decimal("0")


def test_the_absent_policy_run_over_the_same_bundle_credits_nothing() -> None:
    """Control: the cash fixture earns nothing without a policy."""
    artifacts = run_cash(cash_engine(policy=None))

    assert interest_events(artifacts) == ()
    assert artifacts.trace.schema_version == "1"
    assert (
        tuple(point.cash_balance for point in artifacts.result.metrics.equity_series)
        == (Decimal("100000"),) * 5
    )
    assert artifacts.result.metrics.net_profit_and_loss == Decimal("0")
