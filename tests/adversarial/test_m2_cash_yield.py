"""M2 adversarial acceptance: optional point-in-time cash yield.

The evaluator credits modeled interest on idle cash only when the caller
supplies a cash-yield policy. The overriding invariant is that an evaluation
handed no policy is unchanged, byte for byte: the same evidence hash, the same
trace, result and final book. The characterization tests at the top of this
module were written and passed on unchanged main 60d572a before any source
was edited, and their literals were captured there.
"""

# ruff: noqa: E402

import sys
from datetime import date, datetime, timedelta
from decimal import ROUND_UP, Context, Decimal, localcontext
from pathlib import Path
from typing import Any

_SUPPORT = Path(__file__).resolve().parents[1]
for _folder in (_SUPPORT / "unit", _SUPPORT / "integration"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import pytest
import test_evaluator_cash_yield as cy
import test_evaluator_engine as eng
import test_evaluator_experiment_run as run_support
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    JAN7,
    ReconstructedTargetStrategy,
    bundle_of,
    cohort_of,
    exploratory_admission,
    promotion_admission,
    reconstructed_engine,
    replay_of,
    run_engine,
    three_regular_sessions,
)
from pydantic import ValidationError
from test_evaluator_opening_book_lifecycle import _Recorder
from test_m2_engine_input_revalidation import GENUINE_RUN_HASHES

import drift.evaluator.engine as evaluator_engine
from drift.baselines import B0CashStrategy
from drift.domain.evaluator_cash_yield import (
    CASH_YIELD_LIMITATION,
    CashRateObservationV1,
    CashYieldPolicyV1,
    CashYieldRefusedError,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_results import (
    EvaluationRunArtifactsV2,
    PromotionEvaluationResultV1,
    evaluation_result_hash,
)
from drift.domain.evaluator_trace import SessionMarkTraceEventV1
from drift.domain.experiments import ExperimentRunStatus
from drift.evaluator.bundles import build_evaluation_run_identity
from drift.evaluator.engine import (
    PromotionLaneDisabledError,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    _admitted_cash_yield,
    evaluator_evidence_hash,
)
from drift.evaluator.experiment_runner import execute_experiment_run
from drift.evaluator.portfolio import PortfolioAccountingKernel, initial_portfolio_state
from drift.serialization.canonical import canonical_json, content_hash

# ==========================================================================
# Step 0: characterization of the absent input, captured on unchanged main
# ==========================================================================

#: ``evaluator_evidence_hash`` of an empty ``SessionEvaluatorEvidence`` over an
#: ISO-4217 USD book, captured on unchanged main 60d572a. An absent cash-yield
#: policy adds no key to the hashed payload, so this never moves for it.
EMPTY_EVIDENCE_HASH_ON_UNCHANGED_MAIN = (
    "da452144b2ed51deff43810255b2c17a229347f87381624000254b1217cbdd56"
)

#: Every member of the final book of the realized fixture run
#: ``eng._run(eng._engine())`` that is not itself an identity-bearing hash,
#: captured on unchanged main 60d572a. The two members left out, the admission
#: hash and the mark, are bound below to the trace and result hashes the
#: repository already pins, so no second copy of those pins is kept here.
REALIZED_FIXTURE_FINAL_BOOK_ON_UNCHANGED_MAIN: dict[str, Any] = {
    "schema_version": "2",
    "lane": "exploratory",
    "session_key": {
        "schema_version": "1",
        "mic": "XNYS",
        "session_scope": "regular",
        "local_date": "2026-01-08",
    },
    "cash_balance": "9000",
    "holdings": [
        {
            "schema_version": "2",
            "security_id": "019b8240-0000-7000-8000-000000000200",
            "quantity": 10,
            "basis_status": "known",
            "cost_basis": "1000",
            "basis_indeterminate_by": [],
        }
    ],
    "pending_cash_claims": [],
    "settled_claim_ids": [],
    "applied_effect_ids": [],
    "holdings_market_value": "1200",
    "pending_claims_value": "0",
    "net_asset_value": "10200",
    "realized_gross_pnl": "0",
    "realized_net_pnl": "0",
    "cumulative_transaction_costs": "0",
}


def _assert_the_unchanged_realized_fixture_run(
    artifacts: EvaluationRunArtifactsV2,
) -> None:
    """Every byte of the run is the one unchanged main produced.

    The trace hash covers every event and the result hash every result field,
    and both are the pair ``GENUINE_RUN_HASHES`` already pins. The final book
    is then fixed member by member: its plain members by the literal above,
    its admission hash by the result's run identity, and its mark by the mark
    hash the last traced close records.
    """
    assert (
        artifacts.trace.trace_hash,
        artifacts.result.result_hash,
    ) == GENUINE_RUN_HASHES["realized-staged"]
    assert artifacts.trace.schema_version == "1"
    book = artifacts.final_state
    assert (
        book.model_dump(mode="json", exclude={"admission_hash", "mark"})
        == REALIZED_FIXTURE_FINAL_BOOK_ON_UNCHANGED_MAIN
    )
    assert book.admission_hash == artifacts.result.run_identity.admission_hash
    closes = [
        event
        for event in artifacts.trace.events
        if isinstance(event, SessionMarkTraceEventV1)
    ]
    assert book.mark is not None
    assert content_hash(book.mark) == closes[-1].mark_hash


def test_the_empty_evidence_hash_is_the_one_captured_on_unchanged_main() -> None:
    assert (
        evaluator_evidence_hash(
            SessionEvaluatorEvidence(),
            book_currency_namespace="ISO-4217",
            book_currency_code="USD",
        )
        == EMPTY_EVIDENCE_HASH_ON_UNCHANGED_MAIN
    )


def test_a_run_without_a_policy_is_byte_identical_to_unchanged_main() -> None:
    _assert_the_unchanged_realized_fixture_run(eng._run(eng._engine()))


def test_a_prepared_book_run_without_a_policy_is_byte_identical_too() -> None:
    engine = eng._engine()
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)

    artifacts = eng._run(engine)

    assert lifecycle.seen == ["retain", "claim", "consume"]
    _assert_the_unchanged_realized_fixture_run(artifacts)
    assert canonical_json(artifacts) == canonical_json(eng._run(eng._engine()))


def test_an_explicit_none_policy_is_the_absent_policy_byte_for_byte() -> None:
    implicit = eng._run(eng._engine())
    explicit_engine = eng._engine(
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS, cash_yield=None
        )
    )
    explicit = eng._run(explicit_engine)

    assert canonical_json(explicit) == canonical_json(implicit)
    _assert_the_unchanged_realized_fixture_run(explicit)
    assert explicit_engine.evaluator_evidence_hash == (
        eng._engine().evaluator_evidence_hash
    )
    assert (
        evaluator_evidence_hash(
            SessionEvaluatorEvidence(cash_yield=None),
            book_currency_namespace="ISO-4217",
            book_currency_code="USD",
        )
        == EMPTY_EVIDENCE_HASH_ON_UNCHANGED_MAIN
    )


def test_a_run_without_a_policy_never_reaches_the_kernel_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-vacuity: the absent path does not call the credit and discard it."""

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("an evaluation without a policy credited interest")

    monkeypatch.setattr(PortfolioAccountingKernel, "credit_cash_interest", forbidden)

    artifacts = eng._run(eng._engine())
    _assert_the_unchanged_realized_fixture_run(artifacts)
    # Control: with a policy the same patch is reached.
    with pytest.raises(AssertionError, match=r"credited interest"):
        cy.run_cash(cy.cash_engine(policy=cy.cash_policy()))


# ==========================================================================
# No lookahead
# ==========================================================================

LOOKAHEAD = r"^cash yield refused: the rate for 2026-01-06 was known at "


def _policy_with_first_rate_known_at(known_at: datetime) -> CashYieldPolicyV1:
    return cy.cash_policy(
        records=(
            cy.cash_rate(cy.CASH_DAYS[0], known_at=known_at),
            *(cy.cash_rate(day) for day in cy.CASH_DAYS[1:-1]),
        )
    )


@pytest.mark.parametrize(
    "late_by",
    [timedelta(0), timedelta(microseconds=1), timedelta(hours=6), timedelta(days=400)],
    ids=["at-the-open", "one-microsecond-after", "mid-session", "a-year-later"],
)
def test_a_rate_known_at_or_after_the_crediting_open_is_refused(
    late_by: timedelta,
) -> None:
    crediting_open = cy.cash_bundle().session_clock.sessions[1].opened_at

    with pytest.raises(CashYieldRefusedError, match=LOOKAHEAD):
        cy.cash_engine(
            policy=_policy_with_first_rate_known_at(crediting_open + late_by)
        )


def test_a_rate_known_one_microsecond_before_the_crediting_open_is_admitted() -> None:
    crediting_open = cy.cash_bundle().session_clock.sessions[1].opened_at
    policy = _policy_with_first_rate_known_at(
        crediting_open - timedelta(microseconds=1)
    )

    artifacts = cy.run_cash(cy.cash_engine(policy=policy))

    assert (
        tuple(event.interest for event in cy.interest_events(artifacts))
        == cy.EXPECTED_INTEREST
    )


def _session_events(artifacts: EvaluationRunArtifactsV2, before: int) -> list[bytes]:
    return [
        canonical_json(event)
        for event in artifacts.trace.events
        if event.session_index < before
    ]


@pytest.mark.parametrize("changed_index", [1, 2, 3])
def test_a_later_rate_cannot_reach_an_earlier_session(changed_index: int) -> None:
    """Only the rate dated ``changed_index`` moves; it is credited one later."""
    credited = changed_index + 1
    base = cy.run_cash(cy.cash_engine(policy=cy.cash_policy()))
    changed = cy.run_cash(
        cy.cash_engine(
            policy=cy.cash_policy(rates={cy.CASH_DAYS[changed_index]: "0.01"})
        )
    )

    # Every event of every earlier session is byte-identical.
    earlier = _session_events(base, credited)
    assert earlier == _session_events(changed, credited)
    assert sum(b'"cash_interest_accrued"' in event for event in earlier) == (
        changed_index
    )
    assert (
        base.result.metrics.equity_series[:credited]
        == changed.result.metrics.equity_series[:credited]
    )
    # The crediting session moved, and so did every final hash.
    assert (
        cy.interest_events(base)[changed_index].interest
        != cy.interest_events(changed)[changed_index].interest
    )
    assert base.trace.trace_hash != changed.trace.trace_hash
    assert base.result.result_hash != changed.result.result_hash
    assert (
        base.result.run_identity.run_identity_hash
        != changed.result.run_identity.run_identity_hash
    )
    assert content_hash(base.final_state) != content_hash(changed.final_state)


def test_an_unread_rate_moves_the_identity_but_not_one_trace_byte() -> None:
    """A rate nothing accrues from is admitted, whenever it became known."""
    unread = cy.cash_rate(
        cy.CASH_DAYS[-1],
        "0.9",
        known_at=cy.known_at_close(cy.CASH_DAYS[-1]) + timedelta(days=4000),
    )
    read = tuple(cy.cash_rate(day) for day in cy.CASH_DAYS[:-1])
    base = cy.run_cash(cy.cash_engine(policy=cy.cash_policy(records=read)))
    extended = cy.run_cash(
        cy.cash_engine(policy=cy.cash_policy(records=(*read, unread)))
    )

    assert canonical_json(extended.trace) == canonical_json(base.trace)
    assert canonical_json(extended.final_state) == canonical_json(base.final_state)
    assert extended.result.metrics == base.result.metrics
    # The policy is hashed whole into the evidence, so the run identity moves.
    assert (
        extended.result.run_identity.evaluator_evidence_hash
        != base.result.run_identity.evaluator_evidence_hash
    )
    assert extended.result.result_hash != base.result.result_hash


# ==========================================================================
# Construction refusals
# ==========================================================================


@pytest.mark.parametrize("missing_index", [0, 1, 2, 3])
def test_a_missing_rate_for_a_needed_date_is_refused(missing_index: int) -> None:
    missing = cy.CASH_DAYS[missing_index]
    records = tuple(cy.cash_rate(day) for day in cy.CASH_DAYS if day != missing)

    with pytest.raises(
        CashYieldRefusedError,
        match=rf"^cash yield refused: the policy states no rate for {missing}, the "
        rf"date of session {missing_index}",
    ):
        cy.cash_engine(policy=cy.cash_policy(records=records))


def test_a_neighbouring_date_never_stands_in_for_a_missing_rate() -> None:
    """Rates for the calendar days around a session date are not its rate."""
    weekend = tuple(
        cy.cash_rate(day)
        for day in (
            *cy.CASH_DAYS[:3],
            date(2026, 1, 10),
            date(2026, 1, 11),
        )
    )

    with pytest.raises(CashYieldRefusedError, match=r"states no rate for 2026-01-09"):
        cy.cash_engine(policy=cy.cash_policy(records=weekend))


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            {"currency_code": "EUR"},
            r"^cash yield refused: the policy accrues in ISO-4217 EUR, the book is "
            r"held in ISO-4217 USD$",
        ),
        (
            {"currency_namespace": "another-namespace"},
            r"^cash yield refused: the policy accrues in another-namespace USD, the "
            r"book is held in ISO-4217 USD$",
        ),
        ({"currency_code": "usd"}, r"the policy accrues in ISO-4217 usd"),
    ],
    ids=["another-code", "another-namespace", "another-case"],
)
def test_a_policy_in_another_currency_is_refused(
    change: dict[str, Any], problem: str
) -> None:
    with pytest.raises(CashYieldRefusedError, match=problem):
        cy.cash_engine(policy=cy.cash_policy(**change))


def _schedule(lane: str) -> object:
    sessions = cy.cash_bundle().session_clock.sessions
    return _admitted_cash_yield(
        cy.cash_policy(),
        lane=lane,
        sessions=sessions,
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )


@pytest.mark.parametrize("lane", ["promotion", "Exploratory", "", "any-other-lane"])
def test_only_the_exploratory_lane_admits_a_cash_yield_policy(lane: str) -> None:
    with pytest.raises(
        CashYieldRefusedError,
        match=r"^cash yield refused: modeled cash interest is EXPLORATORY evidence",
    ):
        _schedule(lane)

    # Control: the exploratory lane admits the same policy over the same clock.
    assert _schedule("exploratory") is not None


def test_no_policy_is_admitted_as_no_schedule_in_any_lane() -> None:
    sessions = cy.cash_bundle().session_clock.sessions

    for lane in ("exploratory", "promotion"):
        assert (
            _admitted_cash_yield(
                None,
                lane=lane,
                sessions=sessions,
                book_currency_namespace=eng.BOOK_NAMESPACE,
                book_currency_code=eng.BOOK_CODE,
            )
            is None
        )


def test_a_clock_that_does_not_advance_a_whole_day_is_refused() -> None:
    """Defense in depth: the engine refuses such a clock before this is reached."""
    backwards = tuple(reversed(cy.cash_bundle().session_clock.sessions))

    with pytest.raises(
        CashYieldRefusedError,
        match=r"^cash yield refused: session 1 on 2026-01-09 does not follow "
        r"session 0 on 2026-01-12 by a whole day$",
    ):
        _admitted_cash_yield(
            cy.cash_policy(records=tuple(cy.cash_rate(day) for day in cy.CASH_DAYS)),
            lane="exploratory",
            sessions=backwards,
            book_currency_namespace=eng.BOOK_NAMESPACE,
            book_currency_code=eng.BOOK_CODE,
        )


def test_a_promotion_admission_with_a_policy_is_refused_at_construction() -> None:
    """The disabled promotion lane is refused before the policy is even read."""
    bundle = cy.cash_bundle()

    with pytest.raises(PromotionLaneDisabledError, match=r"engine construction"):
        SessionEvaluatorEngine(
            bundle=bundle,
            admission=promotion_admission(bundle),
            protocol=eng._protocol(cash=cy.INITIAL_CASH),
            cost_model=eng._cost_model(),
            evidence=SessionEvaluatorEvidence(
                listing_role_records=eng.ROLE_RECORDS, cash_yield=cy.cash_policy()
            ),
            book_currency_namespace=eng.BOOK_NAMESPACE,
            book_currency_code=eng.BOOK_CODE,
        )


# ==========================================================================
# Run identity
# ==========================================================================

EVIDENCE_NOT_BOUND = r"^the run identity must bind this evaluation's evaluator evidence"


def _identity_of(engine: SessionEvaluatorEngine) -> Any:
    return eng._run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
        strategy_hash=B0CashStrategy().strategy_reference.code_hash,
    )


def test_an_identity_minted_without_the_policy_is_refused_by_an_engine_with_it() -> (
    None
):
    plain = cy.cash_engine(policy=None)
    holding = cy.cash_engine(policy=cy.cash_policy())
    assert plain.evaluator_evidence_hash != holding.evaluator_evidence_hash

    with pytest.raises(ValueError, match=EVIDENCE_NOT_BOUND):
        holding.run(strategy=B0CashStrategy(), run_identity=_identity_of(plain))
    with pytest.raises(ValueError, match=EVIDENCE_NOT_BOUND):
        plain.run(strategy=B0CashStrategy(), run_identity=_identity_of(holding))


def test_an_identity_minted_over_another_policy_is_refused() -> None:
    first = cy.cash_engine(policy=cy.cash_policy())
    second = cy.cash_engine(policy=cy.cash_policy(rates={cy.CASH_DAYS[3]: "0.01"}))

    with pytest.raises(ValueError, match=EVIDENCE_NOT_BOUND):
        second.run(strategy=B0CashStrategy(), run_identity=_identity_of(first))


def _evidence_identity(policy: CashYieldPolicyV1 | None) -> str:
    return evaluator_evidence_hash(
        SessionEvaluatorEvidence(cash_yield=policy),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )


def test_every_policy_member_moves_the_evidence_identity() -> None:
    base = _evidence_identity(cy.cash_policy())
    assert base != _evidence_identity(None)
    first = cy.CASH_DAYS[0]
    later = cy.known_at_close(first) + timedelta(seconds=1)
    rest = tuple(cy.cash_rate(day) for day in cy.CASH_DAYS[1:-1])
    variants = {
        "source_id": cy.cash_policy(source_id="another-source"),
        "source_sha256": cy.cash_policy(source_sha256="f" * 64),
        "currency_namespace": cy.cash_policy(currency_namespace="another"),
        "currency_code": cy.cash_policy(currency_code="EUR"),
        "day_count": cy.cash_policy(day_count="ACT/365F"),
        "interest_quantum": cy.cash_policy(interest_quantum=Decimal("0.0001")),
        "limitations": cy.cash_policy(
            acknowledged_limitations=(CASH_YIELD_LIMITATION, "a-second-limitation")
        ),
        "one-rate": cy.cash_policy(rates={first: "0.0526"}),
        "one-known-at": cy.cash_policy(
            records=(cy.cash_rate(first, known_at=later), *rest)
        ),
        "one-rate-date": cy.cash_policy(
            records=(cy.cash_rate(first - timedelta(days=1)), *rest)
        ),
    }

    identities = {name: _evidence_identity(policy) for name, policy in variants.items()}
    assert base not in identities.values()
    assert len(set(identities.values())) == len(variants)


def test_the_caller_order_of_rates_cannot_move_a_run() -> None:
    forward = tuple(cy.cash_rate(day) for day in cy.CASH_DAYS[:-1])
    backward = tuple(reversed(forward))

    first = cy.run_cash(cy.cash_engine(policy=cy.cash_policy(records=forward)))
    second = cy.run_cash(cy.cash_engine(policy=cy.cash_policy(records=backward)))

    assert canonical_json(first) == canonical_json(second)


def _unvalidated(**changes: Any) -> CashYieldPolicyV1:
    """A policy built without validation, as a forged input would be."""
    return CashYieldPolicyV1.model_construct(**(dict(cy.cash_policy()) | changes))


@pytest.mark.parametrize(
    ("forged", "problem"),
    [
        ({"interest_quantum": Decimal("0.05")}, r"positive power of ten"),
        ({"interest_quantum": Decimal("0.010")}, None),
        ({"day_count": "30/360"}, r"day_count"),
        ({"acknowledged_limitations": ()}, r"must acknowledge the limitation"),
        ({"rates": ()}, r"requires at least one rate"),
        (
            {"rates": (cy.cash_rate(cy.CASH_DAYS[0]), cy.cash_rate(cy.CASH_DAYS[0]))},
            r"at most one rate per date",
        ),
        (
            {
                "rates": (
                    CashRateObservationV1.model_construct(
                        schema_version="1",
                        rate_date=cy.CASH_DAYS[0],
                        annualized_rate=Decimal("5.25"),
                        known_at=cy.known_at_close(cy.CASH_DAYS[0]),
                    ),
                    *(cy.cash_rate(day) for day in cy.CASH_DAYS[1:-1]),
                )
            },
            r"cannot exceed 1, got 5.25",
        ),
        (
            {
                "rates": (
                    CashRateObservationV1.model_construct(
                        schema_version="1",
                        rate_date=cy.CASH_DAYS[0],
                        annualized_rate=Decimal("-0.01"),
                        known_at=cy.known_at_close(cy.CASH_DAYS[0]),
                    ),
                    *(cy.cash_rate(day) for day in cy.CASH_DAYS[1:-1]),
                )
            },
            r"cannot be negative, got -0.01",
        ),
        ({"schema_version": "9"}, r"schema_version"),
        ({"source_sha256": "0" * 63}, r"source_sha256"),
    ],
    ids=[
        "quantum-not-a-power-of-ten",
        "quantum-in-a-second-spelling",
        "unknown-day-count",
        "no-limitation",
        "no-rates",
        "duplicate-rate-date",
        "rate-above-one",
        "negative-rate",
        "unknown-schema-version",
        "malformed-source-hash",
    ],
)
def test_a_policy_built_without_validation_is_revalidated_by_the_engine(
    forged: dict[str, Any], problem: str | None
) -> None:
    policy = _unvalidated(**forged)

    if problem is None:
        # Not a defect, only a second spelling: the engine runs it canonically.
        genuine = cy.cash_engine(policy=cy.cash_policy())
        assert cy.cash_engine(policy=policy).evaluator_evidence_hash == (
            genuine.evaluator_evidence_hash
        )
        return
    with pytest.raises(ValidationError, match=problem):
        cy.cash_engine(policy=policy)


def test_an_empty_unvalidated_policy_is_refused() -> None:
    with pytest.raises(ValidationError):
        cy.cash_engine(policy=CashYieldPolicyV1.model_construct())


def test_rates_built_out_of_order_without_validation_run_canonically() -> None:
    """Revalidation re-sorts, so a forged order cannot pick another record."""
    backward = tuple(reversed(tuple(cy.cash_rate(day) for day in cy.CASH_DAYS[:-1])))
    forged = cy.run_cash(cy.cash_engine(policy=_unvalidated(rates=backward)))
    genuine = cy.run_cash(cy.cash_engine(policy=cy.cash_policy()))

    assert canonical_json(forged) == canonical_json(genuine)


# ==========================================================================
# Replay determinism
# ==========================================================================


def test_a_cash_yield_run_replays_byte_for_byte() -> None:
    first = cy.run_cash(cy.cash_engine(policy=cy.cash_policy()), cy.buy_at_third_open())
    second = cy.run_cash(
        cy.cash_engine(policy=cy.cash_policy()), cy.buy_at_third_open()
    )

    assert canonical_json(first) == canonical_json(second)
    # One engine replays itself too: a run leaves no state behind.
    engine = cy.cash_engine(policy=cy.cash_policy())
    assert canonical_json(cy.run_cash(engine)) == canonical_json(cy.run_cash(engine))


def test_a_perturbed_ambient_decimal_context_cannot_move_a_cash_yield_run() -> None:
    baseline = cy.run_cash(
        cy.cash_engine(policy=cy.cash_policy()), cy.buy_at_third_open()
    )

    with localcontext(Context(prec=2, rounding=ROUND_UP)):
        perturbed = cy.run_cash(
            cy.cash_engine(policy=cy.cash_policy()), cy.buy_at_third_open()
        )

    assert canonical_json(perturbed) == canonical_json(baseline)
    assert str(perturbed.final_state.cash_balance) == "99086.94"
    assert len(cy.interest_events(perturbed)) == 4


def test_the_experiment_runner_records_a_cash_yield_run() -> None:
    """The runner rebuilds artifacts through strict JSON before recording them."""
    engine = cy.cash_engine(policy=cy.cash_policy())
    context = run_support._context(engine, strategy=cy.buy_at_third_open())

    run = execute_experiment_run(
        run_support._specification(dataset_hash=engine.bundle.bundle_hash), context
    )

    assert run.status is ExperimentRunStatus.COMPLETED
    assert run_support._metric(run, "lane") == "exploratory"
    assert run_support._metric(run, "committed_fill_count") == 1
    assert run_support._metric(run, "net_profit_and_loss") == "86.94"
    assert run_support._metric(run, "ending_cash") == "99086.94"


# ==========================================================================
# The prepared opening-book executor
# ==========================================================================


def test_a_prepared_book_run_with_a_policy_matches_the_legacy_run() -> None:
    expected = cy.run_cash(cy.cash_engine(policy=cy.cash_policy()))
    engine = cy.cash_engine(policy=cy.cash_policy())
    lifecycle = _Recorder()
    engine.prepare_opening_book(lifecycle=lifecycle)

    artifacts = cy.run_cash(engine)

    assert canonical_json(artifacts) == canonical_json(expected)
    assert lifecycle.seen == ["retain", "claim", "consume"]
    assert (
        tuple(event.interest for event in cy.interest_events(artifacts))
        == cy.EXPECTED_INTEREST
    )


@pytest.mark.parametrize("at", ["retain", "claim", "consume"])
def test_a_public_class_descriptor_cannot_reach_the_prepared_cash_yield(
    monkeypatch: pytest.MonkeyPatch, at: str
) -> None:
    expected = canonical_json(cy.run_cash(cy.cash_engine(policy=cy.cash_policy())))
    engine = cy.cash_engine(policy=cy.cash_policy())
    accessed = 0

    class InjectsDescriptor(_Recorder):
        def _visit(self, where: str, book: PortfolioStateV2) -> None:
            nonlocal accessed
            if where == at:

                def injected(_owner: object) -> object:
                    nonlocal accessed
                    accessed += 1
                    raise AssertionError(
                        "base-class descriptor reached private executor"
                    )

                monkeypatch.setattr(
                    type(engine), "_cash_yield", property(injected), raising=False
                )
            super()._visit(where, book)

    lifecycle = InjectsDescriptor()
    engine.prepare_opening_book(lifecycle=lifecycle)
    artifacts = cy.run_cash(engine)

    assert canonical_json(artifacts) == expected
    assert accessed == 0
    assert lifecycle.seen == ["retain", "claim", "consume"]


@pytest.mark.parametrize("install_on", ["instance", "class"])
def test_an_injected_accrual_hook_never_sees_the_prepared_book(
    monkeypatch: pytest.MonkeyPatch, install_on: str
) -> None:
    expected = canonical_json(cy.run_cash(cy.cash_engine(policy=cy.cash_policy())))
    engine = cy.cash_engine(policy=cy.cash_policy())
    calls = 0

    class HookInstallingObserver(_Recorder):
        def _visit(self, phase: str, book: PortfolioStateV2) -> None:
            nonlocal calls
            if phase == "consume":

                def injected(*args: Any, **kwargs: Any) -> Any:
                    nonlocal calls
                    calls += 1
                    raise AssertionError("observer-injected accrual hook executed")

                if install_on == "instance":
                    object.__setattr__(engine, "_cash_interest_accrual", injected)
                else:
                    monkeypatch.setattr(
                        type(engine), "_cash_interest_accrual", injected
                    )
            super()._visit(phase, book)

    lifecycle = HookInstallingObserver()
    engine.prepare_opening_book(lifecycle=lifecycle)
    artifacts = cy.run_cash(engine)

    assert canonical_json(artifacts) == expected
    assert calls == 0
    assert lifecycle.seen == ["retain", "claim", "consume"]


def test_the_prepared_executor_shadows_the_cash_yield_collaborator() -> None:
    assert "_cash_yield" in evaluator_engine._PREPARED_INSTANCE_FIELDS
    assert isinstance(
        vars(evaluator_engine._PREPARED_EXECUTOR_TYPE)["_cash_yield"], property
    )
    assert "_cash_interest_accrual" in vars(evaluator_engine._PREPARED_EXECUTOR_TYPE)


# ==========================================================================
# Accrual guards at use
# ==========================================================================


def _loop_at(engine: SessionEvaluatorEngine, index: int) -> Any:
    sessions = engine.bundle.session_clock.sessions
    state = initial_portfolio_state(
        session_key=sessions[0].session_key,
        initial_cash=engine.protocol.initial_cash,
        admission=engine.admission,
    )
    for session in sessions[1 : index + 1]:
        state = engine._advance(state, session.session_key)
    return evaluator_engine._Loop(state=state)


def test_the_accrual_refuses_a_session_its_schedule_was_not_admitted_for() -> None:
    """Defense in depth behind construction: the step re-checks what it reads."""
    engine = cy.cash_engine(policy=cy.cash_policy())
    sessions = engine.bundle.session_clock.sessions
    loop = _loop_at(engine, 1)

    # Session 2 handed in as the step of index 1: two days, not the admitted one.
    with pytest.raises(
        CashYieldRefusedError, match=r"^cash yield refused: the accrual admitted"
    ):
        engine._cash_interest_accrual(loop, 1, sessions[2])

    assert loop.events == []
    assert loop.state.cash_balance == Decimal("100000")
    # Control: the admitted session of that index is credited.
    engine._cash_interest_accrual(loop, 1, sessions[1])
    assert loop.state.cash_balance == Decimal("100014.58")
    assert [event.kind for event in loop.events] == ["cash_interest_accrued"]


def test_the_first_session_never_accrues() -> None:
    engine = cy.cash_engine(policy=cy.cash_policy())
    loop = _loop_at(engine, 0)

    engine._cash_interest_accrual(loop, 0, engine.bundle.session_clock.sessions[0])

    assert loop.events == []
    assert loop.state.cash_balance == Decimal("100000")


# ==========================================================================
# The EXPLORATORY reconstructed lane
# ==========================================================================


def _reconstructed_engine(policy: CashYieldPolicyV1 | None) -> SessionEvaluatorEngine:
    bundle = bundle_of(three_regular_sessions())
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=exploratory_admission(bundle),
        protocol=eng._protocol(warmup=1),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS,
            exploratory_cohort=cohort_of(),
            exploratory_reconstruction_replay=replay_of(
                bundle.exploratory_reconstructed_observations
            ),
            cash_yield=policy,
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )


def test_an_absent_policy_leaves_a_reconstructed_run_byte_identical() -> None:
    """The second decision lane, compared with the support engine's own run."""
    strategy_targets = {JAN5: ((eng.SEC_A, 1),), JAN6: ((eng.SEC_A, 1),)}
    expected = run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())),
        ReconstructedTargetStrategy(strategy_targets),
    )

    explicit = run_engine(
        _reconstructed_engine(None), ReconstructedTargetStrategy(strategy_targets)
    )

    assert canonical_json(explicit) == canonical_json(expected)


def test_the_reconstructed_lane_credits_interest_under_the_same_rule() -> None:
    policy = cy.cash_policy(days=(JAN5, JAN6, JAN7))
    artifacts = run_engine(
        _reconstructed_engine(policy), ReconstructedTargetStrategy({})
    )

    events = cy.interest_events(artifacts)
    # 10000 * 0.0525 / 360 = 1.4583..., then 10001.46 * 0.0525 / 360 = 1.4585...
    assert tuple(event.interest for event in events) == (
        Decimal("1.46"),
        Decimal("1.46"),
    )
    assert tuple(event.session_index for event in events) == (1, 2)
    assert artifacts.final_state.cash_balance == Decimal("10002.92")
    assert artifacts.trace.schema_version == "2"
    assert artifacts.result.is_promotion_grade_evidence is False


# ==========================================================================
# A promotion result cannot bind modeled interest
# ==========================================================================


def _promotion_pairing(
    artifacts: EvaluationRunArtifactsV2, engine: Any
) -> dict[str, object]:
    """The run's own trace and book, re-sealed under a promotion result."""
    bundle = engine.bundle
    promotion = promotion_admission(bundle)
    identity = build_evaluation_run_identity(
        strategy_hash=B0CashStrategy().strategy_reference.code_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=promotion,
        bundle=bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        code_version_hash=eng.CODE_VERSION_HASH,
        environment_closure_hash=eng.ENVIRONMENT_HASH,
    )
    source = artifacts.result
    draft = PromotionEvaluationResultV1.model_construct(
        run_identity=identity,
        classification=source.classification,
        halted_session_index=source.halted_session_index,
        halt_reason=source.halt_reason,
        metrics=source.metrics,
        trace_hash=artifacts.trace.trace_hash,
        admission=promotion,
        result_hash="0" * 64,
    )
    result = PromotionEvaluationResultV1.model_validate(
        dict(draft) | {"result_hash": evaluation_result_hash(draft)}
    )
    state = artifacts.final_state
    assert state.holdings == ()
    mark = state.mark
    assert mark is not None
    assert mark.prices == ()
    final_state = PortfolioStateV2.model_validate(
        dict(state)
        | {
            "lane": "promotion",
            "admission_hash": promotion.admission_hash,
            "mark": mark.model_copy(update={"lane": "promotion"}),
        }
    )
    return {"result": result, "trace": artifacts.trace, "final_state": final_state}


def test_a_promotion_result_cannot_bind_a_trace_of_modeled_interest() -> None:
    engine = cy.cash_engine(policy=cy.cash_policy())
    artifacts = cy.run_cash(engine)

    with pytest.raises(
        ValidationError,
        match=(
            r"a promotion result cannot bind a trace of modeled cash interest: "
            r"4 cash_interest_accrued events"
        ),
    ):
        EvaluationRunArtifactsV2.model_validate(_promotion_pairing(artifacts, engine))


def test_the_promotion_refusal_is_caused_by_the_interest_events_alone() -> None:
    """Control: the same pairing over a trace that credited nothing validates."""
    zero = dict.fromkeys(cy.CASH_DAYS[:-1], "0")
    engine = cy.cash_engine(policy=cy.cash_policy(rates=zero))
    artifacts = cy.run_cash(engine)
    assert cy.interest_events(artifacts) == ()

    paired = EvaluationRunArtifactsV2.model_validate(
        _promotion_pairing(artifacts, engine)
    )

    assert paired.result.lane == "promotion"
