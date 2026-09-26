"""M2 adversarial acceptance: EXPLORATORY accounting on reconstructed prices.

Issue 54, adjudicated in #62 (Q2, option C): in the EXPLORATORY reconstructed
lane only, a verified reconstruction's open is an exploratory execution price
and its close is an exploratory mark, read through the dedicated
``ExploratoryReconstructedAccountingPriceV1`` record. Missing or ambiguous
evidence stays INDETERMINATE, a realized bundle cannot carry a reconstruction
to price from (issue 72), and no promotion artifact may carry the resulting PnL.
"""

# ruff: noqa: E402

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    JAN7,
    LISTING,
    LISTING_OTHER,
    SEC,
    ReconstructedTargetStrategy,
    bundle_of,
    cohort_of,
    exploratory_admission,
    promotion_admission,
    reconstructed_engine,
    replay_of,
    run_engine,
    scheduled_bundle,
    scheduled_session_case,
)
from pydantic import ValidationError
from test_evaluator_engine import (
    BOOK_NAMESPACE,
    CODE_VERSION_HASH,
    ENVIRONMENT_HASH,
    ROLE_RECORDS,
    STRATEGY_REFERENCE,
    _bundle,
    _buy_ten,
    _cost_model,
    _protocol,
)

from drift.domain.evaluator_exploratory_accounting import (
    ExploratoryReconstructedAccountingPriceV1,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
    PromotionEvaluationResultV1,
    evaluation_result_hash,
)
from drift.domain.evaluator_trace import EvaluationPhase, seal_evaluation_trace_log
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_run_identity,
)
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence

BUY_AND_HOLD = ReconstructedTargetStrategy(
    {JAN5: ((SEC, 10),), JAN6: ((SEC, 10),), JAN7: ((SEC, 10),)}
)


def _strategy() -> ReconstructedTargetStrategy:
    return ReconstructedTargetStrategy(dict(BUY_AND_HOLD.targets))


def _priced(artifacts: EvaluationRunArtifactsV2) -> list[Any]:
    return [
        event
        for event in artifacts.trace.events
        if event.kind == "exploratory_accounting_price"
    ]


def _cause(artifacts: EvaluationRunArtifactsV2) -> Any:
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    return causes[0]


# --- the priced path -------------------------------------------------------------


def test_fills_read_the_reconstructed_open_and_marks_read_the_close() -> None:
    """JAN6 opens at 100.000 and closes at 100.500, so the roles are distinct."""
    jan5 = scheduled_session_case(JAN5)
    jan6 = scheduled_session_case(JAN6, close="100.500")
    jan7 = scheduled_session_case(JAN7)

    artifacts = run_engine(
        reconstructed_engine(bundle_of((jan5, jan6, jan7))), _strategy()
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    (fill,) = [event.fill for event in artifacts.trace.events if event.kind == "fill"]
    assert (fill.side, fill.quantity, fill.fill_price) == (
        "buy",
        10,
        Decimal("100.000"),
    )
    opened, marked_jan6, marked_jan7 = _priced(artifacts)
    assert opened.phase is EvaluationPhase.OPEN_EXECUTION
    assert [price.reconstruction_hash for price in opened.prices] == [
        jan6[0].reconstruction_hash
    ]
    assert [price.unadjusted_price for price in marked_jan6.prices] == [
        Decimal("100.500")
    ]
    assert [price.reconstruction_hash for price in marked_jan7.prices] == [
        jan7[0].reconstruction_hash
    ]
    (jan6_mark,) = [
        event
        for event in artifacts.trace.events
        if event.kind == "session_mark" and event.session_index == 1
    ]
    assert jan6_mark.holdings_market_value == Decimal("1005.000")


def test_every_mark_is_graded_exploratory_and_bound_to_its_price_record() -> None:
    artifacts = run_engine(
        reconstructed_engine(
            bundle_of(
                (
                    scheduled_session_case(JAN5),
                    scheduled_session_case(JAN6),
                    scheduled_session_case(JAN7),
                )
            )
        ),
        _strategy(),
    )

    mark = artifacts.final_state.mark
    assert mark is not None
    (price,) = mark.prices
    assert price.evidence.grade == "exploratory"
    record = _priced(artifacts)[-1].prices[0]
    assert isinstance(record, ExploratoryReconstructedAccountingPriceV1)
    assert price.evidence.evidence_hash == record.price_hash
    assert record.evidence_grade == "exploratory_reconstructed"
    assert record.is_promotion_grade_evidence is False
    assert record.field_role == "close"


def test_every_price_event_states_exactly_the_admission_limitations() -> None:
    """A price event carries the run's own limitations, not merely the minimum.

    The admission here acknowledges one limitation beyond what the grade
    requires, so an event that stated only the minimum would drop it.
    """
    bundle = bundle_of(
        (
            scheduled_session_case(JAN5),
            scheduled_session_case(JAN6),
            scheduled_session_case(JAN7),
        )
    )
    admission = exploratory_admission(
        bundle,
        limitations=(
            *exploratory_admission(bundle).acknowledged_limitations,
            "an additional acknowledged limitation",
        ),
    )

    artifacts = run_engine(
        reconstructed_engine(bundle, admission=admission), _strategy()
    )

    priced = _priced(artifacts)
    assert priced
    for event in priced:
        assert event.acknowledged_limitations == admission.acknowledged_limitations
    assert "an additional acknowledged limitation" in admission.acknowledged_limitations


def test_a_non_trading_baseline_reads_no_price() -> None:
    """Control: holding cash consumes no reconstructed price at all."""
    artifacts = run_engine(
        reconstructed_engine(
            bundle_of(
                (
                    scheduled_session_case(JAN5),
                    scheduled_session_case(JAN6),
                )
            )
        ),
        ReconstructedTargetStrategy({}),
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _priced(artifacts) == []


# --- missing and ambiguous evidence stays INDETERMINATE ---------------------------


def test_a_missing_open_is_indeterminate_at_execution() -> None:
    """The JAN6 session is in the clock, but no reconstruction prices its open."""
    (jan5, s5), (_, s6), (jan7, s7) = (
        scheduled_session_case(JAN5),
        scheduled_session_case(JAN6),
        scheduled_session_case(JAN7),
    )
    bundle = scheduled_bundle((jan5, jan7), (s5, s6, s7))

    artifacts = run_engine(reconstructed_engine(bundle), _strategy())

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 1
    assert artifacts.result.metrics.committed_fill_count == 0
    cause = _cause(artifacts)
    assert cause.phase is EvaluationPhase.OPEN_EXECUTION
    assert cause.cause == (
        f"no exploratory reconstructed accounting price for security {SEC} on "
        "XNYS 2026-01-06"
    )


def test_a_missing_close_is_indeterminate_at_the_mark() -> None:
    """The position is held into JAN7, whose close no reconstruction prices."""
    (jan5, s5), (jan6, s6), (_, s7) = (
        scheduled_session_case(JAN5),
        scheduled_session_case(JAN6),
        scheduled_session_case(JAN7),
    )
    bundle = scheduled_bundle((jan5, jan6), (s5, s6, s7))

    artifacts = run_engine(reconstructed_engine(bundle), _strategy())

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 2
    cause = _cause(artifacts)
    assert cause.phase is EvaluationPhase.CLOSE_MARK
    assert cause.cause == (
        f"no exploratory reconstructed accounting price for security {SEC} on "
        "XNYS 2026-01-07"
    )


def test_two_reconstructions_of_the_execution_session_are_indeterminate() -> None:
    """Two admissible opens is not an answer."""
    jan5 = scheduled_session_case(JAN5)
    first, session = scheduled_session_case(JAN6)
    second, _ = scheduled_session_case(JAN6, close="101.000")
    bundle = scheduled_bundle((jan5[0], first, second), (jan5[1], session))

    artifacts = run_engine(reconstructed_engine(bundle), _strategy())

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    cause = _cause(artifacts)
    assert cause.phase is EvaluationPhase.OPEN_EXECUTION
    assert cause.cause.startswith(
        "more than one exploratory reconstruction for security"
    )


@pytest.mark.parametrize("close", ["0", "-1.000"])
def test_a_non_positive_reconstructed_close_is_indeterminate_at_the_mark(
    close: str,
) -> None:
    """A re-derived bar may state any finite close; one that cannot mark halts."""
    corpus = (
        scheduled_session_case(JAN5),
        scheduled_session_case(JAN6, close=close),
        scheduled_session_case(JAN7),
    )

    artifacts = run_engine(reconstructed_engine(bundle_of(corpus)), _strategy())

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 1
    cause = _cause(artifacts)
    assert cause.phase is EvaluationPhase.CLOSE_MARK
    assert cause.cause == (
        f"exploratory reconstructed close price for security {SEC} on XNYS "
        f"2026-01-06 is not strictly positive: {close}"
    )


def test_a_reconstructed_open_from_another_listing_cannot_fill() -> None:
    """The execution-listing guard still binds a reconstructed open's listing."""
    corpus = (
        scheduled_session_case(JAN5),
        scheduled_session_case(JAN6, listing_id=LISTING_OTHER),
        scheduled_session_case(JAN7),
    )

    artifacts = run_engine(reconstructed_engine(bundle_of(corpus)), _strategy())

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.metrics.committed_fill_count == 0
    assert artifacts.result.halt_reason == (
        f"unadjusted open price for security {SEC} is bound to listing "
        f"{LISTING_OTHER}, but execution resolved listing {LISTING}"
    )


def test_a_price_in_another_currency_than_the_book_is_indeterminate() -> None:
    bundle = bundle_of((scheduled_session_case(JAN5), scheduled_session_case(JAN6)))
    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=exploratory_admission(bundle),
        protocol=_protocol(warmup=1),
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=ROLE_RECORDS,
            exploratory_cohort=cohort_of(),
            exploratory_reconstruction_replay=replay_of(
                bundle.exploratory_reconstructed_observations
            ),
        ),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code="EUR",
    )

    artifacts = run_engine(engine, _strategy())

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert _cause(artifacts).cause == (
        f"exploratory reconstructed open price for security {SEC} on XNYS "
        "2026-01-06 is in USD, not the book currency EUR"
    )


# --- the grade never leaves its lane -----------------------------------------------


def test_a_realized_bundle_cannot_carry_a_reconstruction_to_price_from() -> None:
    """The realized lane prices from authentic accounting views only.

    The reconstruction would sit on JAN7, the session the realized run fills
    and first marks, with a close (123.000) the authentic view does not state,
    so reading it would change the numbers. Issue 72 refuses it entry to a
    realized-clock bundle at all, and the realized run prices as it always did.
    """
    realized = _bundle()
    observation, _ = scheduled_session_case(JAN7, close="123.000")
    with pytest.raises(
        ValueError,
        match=(
            r"a bundle on a realized_session_authority clock cannot carry "
            r"exploratory reconstructions \(issue 72\)"
        ),
    ):
        assemble_evaluation_input_bundle(
            evaluation_interval=realized.evaluation_interval,
            session_clock=realized.session_clock,
            security_identities=realized.security_identities,
            listing_identities=realized.listing_identities,
            structural_eligibilities=realized.structural_eligibilities,
            economic_outcomes=realized.economic_outcomes,
            authentic_decision_views=realized.authentic_decision_views,
            authentic_accounting_views=realized.authentic_accounting_views,
            exploratory_reconstructed_observations=(observation,),
        )
    artifacts = run_engine(
        reconstructed_engine(realized, protocol=_protocol(), with_cohort=False),
        _buy_ten(),
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _priced(artifacts) == []
    (fill,) = [event.fill for event in artifacts.trace.events if event.kind == "fill"]
    # The authentic view states 100.00 and the refused bar 100.000: equal
    # numbers, but exact decimals, so the stamped open names its source.
    assert str(fill.unadjusted_open_price) == "100.00"
    marks = {
        event.session_key.local_date: event.holdings_market_value
        for event in artifacts.trace.events
        if event.kind == "session_mark"
    }
    # Ten shares at the authentic JAN7 close, never at the refused 123.000.
    assert marks[JAN7] == Decimal("1100")


def _promotion_artifacts_over_priced_trace() -> dict[str, Any]:
    """A genuine priced exploratory trace, stripped of its decision events.

    Removing the ``exploratory_strategy_decision`` events leaves a trace whose
    only weaker-grade events are the accounting prices, so the promotion
    refusal reached is the accounting one, not the decision one. The run buys
    and then sells back to flat, so the final mark carries no exploratory
    price for the mark-grade validator to refuse first.
    """
    bundle = bundle_of(
        (
            scheduled_session_case(JAN5),
            scheduled_session_case(JAN6),
            scheduled_session_case(JAN7),
        )
    )
    engine = reconstructed_engine(bundle)
    artifacts = run_engine(engine, ReconstructedTargetStrategy({JAN5: ((SEC, 10),)}))
    kept = [
        event
        for event in artifacts.trace.events
        if event.kind != "exploratory_strategy_decision"
    ]
    trace = seal_evaluation_trace_log(
        [
            event.model_copy(update={"sequence": position})
            for position, event in enumerate(kept)
        ]
    )
    assert any(event.kind == "exploratory_accounting_price" for event in trace.events)
    promotion = promotion_admission(bundle)
    identity = build_evaluation_run_identity(
        strategy_hash=STRATEGY_REFERENCE.code_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=promotion,
        bundle=bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        code_version_hash=CODE_VERSION_HASH,
        environment_closure_hash=ENVIRONMENT_HASH,
    )
    source = artifacts.result
    draft = PromotionEvaluationResultV1.model_construct(
        run_identity=identity,
        classification=source.classification,
        halted_session_index=source.halted_session_index,
        halt_reason=source.halt_reason,
        metrics=source.metrics,
        trace_hash=trace.trace_hash,
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
    return {"result": result, "trace": trace, "final_state": final_state}


def test_a_promotion_result_cannot_bind_a_trace_of_reconstructed_prices() -> None:
    with pytest.raises(
        ValidationError,
        match=(
            r"a promotion result cannot bind a trace of accounting priced on "
            r"EXPLORATORY reconstructed evidence: 3 exploratory_accounting_price"
        ),
    ):
        EvaluationRunArtifactsV2.model_validate(
            _promotion_artifacts_over_priced_trace()
        )
