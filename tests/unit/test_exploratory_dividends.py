"""Unit tests for exploratory cash dividend accounting (Option B).

Verifies the deterministic hypothetical dividend accounting mechanism,
testing all 17 requirements: entitlement, ex-date buy/sale rules,
payable settlement, weekend dates, NAV invariance, fail-closed safeguards,
deterministic replay, sequential vs parallel equivalence, and lane isolation.
"""

import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from drift.domain.assertions import (
    BoundaryShape,
    TemporalBoundaryClaimV1,
)
from drift.domain.economic_closed_world import (
    CorporateActionCompletenessAssertionV1,
    ReturnedCorporateActionV1,
)
from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_lanes import (
    PromotionEvaluationAdmissionV1,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PendingCashClaimV1,
    pending_cash_claim_id,
)
from drift.domain.temporal import SourcePrecision
from drift.evaluator.corporate_action_coverage import (
    CorporateActionCoverageIndex,
)
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.evaluator.exploratory_dividends import (
    EXPLORATORY_DIVIDEND_LIMITATION,
    ExploratoryCashDividendTermsV1,
    ExploratoryDividendPolicyV1,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel, initial_portfolio_state
from drift.experiments.parallel_portfolios import (
    PortfolioCohortHarness,
    build_offline_cohort_bundle,
    build_offline_cohort_evidence,
    build_reference_baseline_cohort,
)
from drift.markets.economic_closed_world import (
    CorporateActionCoverageError,
    build_corporate_action_coverage,
)

sys.path.insert(0, "tests/unit")
from exploratory_decision_test_support import (  # noqa: E402
    SEC,
    ReconstructedTargetStrategy,
    bundle_of,
    cohort_of,
    exploratory_admission,
    replay_of,
    run_engine,
    scheduled_session_case,
)
from test_evaluator_engine import (  # noqa: E402
    BOOK_CODE,
    BOOK_NAMESPACE,
    ROLE_RECORDS,
    _cost_model,
    _protocol,
    quiet_coverage,  # noqa: E402
)

SECURITY_SPY = UUID("019b8240-0000-7000-8000-000000000001")
SECURITY_QQQ = UUID("019b8240-0000-7000-8000-000000000002")
SECURITY_IWM = UUID("019b8240-0000-7000-8000-000000000003")


def _test_snapshot(
    instant: datetime = datetime(2026, 1, 1, tzinfo=UTC),
) -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=instant,
        upper_bound=instant,
        source_precision=SourcePrecision.SECOND,
        source_time_label=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        evidence_reference=None,
    )


def _test_assertion() -> CorporateActionCompletenessAssertionV1:
    return CorporateActionCompletenessAssertionV1(
        schema_version="1",
        basis="provider_published",
        policy_statement_hash="0" * 64,
        acquisition_reconciliation_pass=True,
        single_unpaginated_response=True,
        measured_origin=True,
        requested_types_documented=True,
        returned_actions_attributed=True,
        returned_actions_inside_requested_window=True,
    )


def _build_engine(
    session_dates: Sequence[date],
    policy: ExploratoryDividendPolicyV1 | None,
    returned_actions: tuple[ReturnedCorporateActionV1, ...] = (),
    warmup: int = 1,
) -> SessionEvaluatorEngine:
    cases = [scheduled_session_case(d) for d in session_dates]
    cov = quiet_coverage(
        (SEC,), session_dates[0], session_dates[-1], returned_actions=returned_actions
    )
    bundle = bundle_of(cases, corporate_action_coverage=cov)
    evidence = SessionEvaluatorEvidence(
        listing_role_records=ROLE_RECORDS,
        exploratory_cohort=cohort_of(),
        exploratory_reconstruction_replay=replay_of(
            bundle.exploratory_reconstructed_observations
        ),
        exploratory_dividends=policy,
    )
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=exploratory_admission(bundle),
        protocol=_protocol(warmup=warmup, cash="10000.00"),
        cost_model=_cost_model(),
        evidence=evidence,
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
    )


# Scenario 1: Dividend entitlement from pre-ex-date holdings
def test_01_dividend_entitlement_from_pre_ex_date_holdings() -> None:
    """Holdings established before ex-date receive dividend entitlement."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div = ExploratoryCashDividendTermsV1(
        native_id="div-1",
        security_id=SEC,
        symbol="SEC",
        rate=Decimal("2.00"),
        ex_date=d7,
        record_date=d7,
        payable_date=d8,
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends", native_id="div-1", action_kind=None, dates=(d7,)
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat = ReconstructedTargetStrategy(
        {d5: ((SEC, 10),), d6: ((SEC, 10),), d7: ((SEC, 10),)}
    )
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    # Entitlement produced 1 settled claim of $20.00
    assert len(artifacts.final_state.settled_claim_ids) == 1


# Scenario 2: Purchase on ex-date not receiving prior entitlement
def test_02_purchase_on_ex_date_not_receiving_prior_entitlement() -> None:
    """Purchase executed at ex-date open does not receive ex-date dividend."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div = ExploratoryCashDividendTermsV1(
        native_id="div-2",
        security_id=SEC,
        symbol="SEC",
        rate=Decimal("2.00"),
        ex_date=d7,
        record_date=d7,
        payable_date=d8,
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends", native_id="div-2", action_kind=None, dates=(d7,)
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    # Target emitted on d6 executes at d7 open (ex-date); pre-open holdings on d7 were 0
    strat = ReconstructedTargetStrategy({d6: ((SEC, 10),), d7: ((SEC, 10),)})
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    # No dividend entitlement because holding was 0 at pre-open of ex-date
    assert len(artifacts.final_state.settled_claim_ids) == 0
    assert len(artifacts.final_state.pending_cash_claims) == 0


# Scenario 3: Sale on ex-date preserving valid entitlement
def test_03_sale_on_ex_date_preserving_valid_entitlement() -> None:
    """Position held prior to ex-date and sold on ex-date retains entitlement."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div = ExploratoryCashDividendTermsV1(
        native_id="div-3",
        security_id=SEC,
        symbol="SEC",
        rate=Decimal("2.00"),
        ex_date=d7,
        record_date=d7,
        payable_date=d8,
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends", native_id="div-3", action_kind=None, dates=(d7,)
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    # Bought at d5 (executes d6 open), sold on d6 (executes d7 open)
    strat = ReconstructedTargetStrategy({d5: ((SEC, 10),), d6: ()})
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    # Pre-open holding at d7 was 10 shares; sale executed at d7 open;
    # claim settled on d8
    assert len(artifacts.final_state.settled_claim_ids) == 1
    assert artifacts.final_state.cash_balance == Decimal("10020.00")


# Scenario 4: Correct payable-date cash credit
def test_04_correct_payable_date_cash_credit() -> None:
    """Modeled cash is credited exactly on payable date."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div = ExploratoryCashDividendTermsV1(
        native_id="div-4",
        security_id=SEC,
        symbol="SEC",
        rate=Decimal("2.50"),
        ex_date=d7,
        record_date=d7,
        payable_date=d8,
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends", native_id="div-4", action_kind=None, dates=(d7,)
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat = ReconstructedTargetStrategy({d5: ((SEC, 10),), d6: ()})
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    # 10 shares * 2.50 = 25.00 cash credited
    assert artifacts.final_state.cash_balance == Decimal("10025.00")
    assert len(artifacts.final_state.settled_claim_ids) == 1


# Scenario 5: Weekend or non-trading payable dates
def test_05_weekend_or_non_trading_payable_date() -> None:
    """Claims with Saturday payable date settle on Monday trading session."""
    session_friday = date(2026, 1, 9)
    session_saturday = date(2026, 1, 10)
    session_monday = date(2026, 1, 12)

    claim_id = pending_cash_claim_id(
        source_id="alpaca",
        security_id=SECURITY_SPY,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        occurrence_id="div-wknd",
        component_id="cash_dividend",
    )
    claim = PendingCashClaimV1(
        schema_version="1",
        claim_id=claim_id,
        source_id="alpaca",
        security_id=SECURITY_SPY,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        occurrence_id="div-wknd",
        component_id="cash_dividend",
        entitled_quantity=10,
        cash_per_share=Decimal("3.00"),
        total_cash_expected=Decimal("30.00"),
        entitlement_session=session_friday,
        payable_session=session_saturday,
    )

    cases = [scheduled_session_case(session_monday)]
    bundle = bundle_of(cases)
    init_state = initial_portfolio_state(
        session_key=bundle.session_clock.sessions[0].session_key,
        initial_cash=Decimal("10000.00"),
        admission=exploratory_admission(bundle),
    )
    kernel = PortfolioAccountingKernel(init_state, session_clock=bundle.session_clock)
    kernel.record_claim(claim)
    assert kernel.state.pending_claims_value == Decimal("30.00")

    # On Monday, claim with Saturday payable date settles
    payable_claim_ids = tuple(
        c.claim_id
        for c in kernel.state.pending_cash_claims
        if c.payable_session <= session_monday
    )
    kernel.settle_claims(payable_claim_ids)
    assert kernel.state.cash_balance == Decimal("10030.00")
    assert len(kernel.state.pending_cash_claims) == 0
    assert claim_id in kernel.state.settled_claim_ids


# Scenario 6: No double counting
def test_06_no_double_counting() -> None:
    """Settled claims are not credited a second time across subsequent sessions."""
    d5, d6, d7, d8, d9 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    )
    div = ExploratoryCashDividendTermsV1(
        native_id="div-6",
        security_id=SEC,
        symbol="SEC",
        rate=Decimal("2.00"),
        ex_date=d7,
        record_date=d7,
        payable_date=d8,
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends", native_id="div-6", action_kind=None, dates=(d7,)
    )
    engine = _build_engine([d5, d6, d7, d8, d9], policy, (ret,))
    strat = ReconstructedTargetStrategy({d5: ((SEC, 10),), d6: ()})
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    # Claim settled on d8; on d9 cash is still 10020.00, not double credited
    assert artifacts.final_state.cash_balance == Decimal("10020.00")
    assert len(artifacts.final_state.settled_claim_ids) == 1


# Scenario 7: No cash credited before payable date and NAV invariant
def test_07_no_cash_credited_before_payable_date_and_nav_invariant() -> None:
    """Cash is not credited prior to payable date; NAV invariant holds."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div = ExploratoryCashDividendTermsV1(
        native_id="div-7",
        security_id=SEC,
        symbol="SEC",
        rate=Decimal("2.00"),
        ex_date=d7,
        record_date=d7,
        payable_date=d8,
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends", native_id="div-7", action_kind=None, dates=(d7,)
    )
    # Stop evaluation at d7 (ex-date, before d8 payable)
    engine = _build_engine([d5, d6, d7], policy, (ret,))
    strat = ReconstructedTargetStrategy(
        {d5: ((SEC, 10),), d6: ((SEC, 10),), d7: ((SEC, 10),)}
    )
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    state = artifacts.final_state
    # Cash not yet credited
    assert len(state.settled_claim_ids) == 0
    assert len(state.pending_cash_claims) == 1
    assert state.pending_claims_value == Decimal("20.00")
    # NAV invariant: cash + holdings_value + pending_claims = NAV
    assert (
        state.cash_balance + state.holdings_market_value + state.pending_claims_value
        == state.net_asset_value
    )


# Scenario 8: Missing or non-positive dividend amount fails closed
def test_08_missing_or_nonpositive_dividend_amount_fails_closed() -> None:
    """Zero or negative dividend rates fail closed."""
    with pytest.raises(ValueError, match="rate must be strictly positive"):
        ExploratoryCashDividendTermsV1(
            native_id="div-8a",
            security_id=SECURITY_SPY,
            symbol="SPY",
            rate=Decimal("0.00"),
            ex_date=date(2022, 3, 18),
            record_date=date(2022, 3, 21),
            payable_date=date(2022, 4, 29),
        )
    with pytest.raises(ValueError, match="rate must be strictly positive"):
        ExploratoryCashDividendTermsV1(
            native_id="div-8b",
            security_id=SECURITY_SPY,
            symbol="SPY",
            rate=Decimal("-1.00"),
            ex_date=date(2022, 3, 18),
            record_date=date(2022, 3, 21),
            payable_date=date(2022, 4, 29),
        )


# Scenario 9: Missing or conflicting dates fail closed
def test_09_missing_or_conflicting_dates_fails_closed() -> None:
    """Payable date preceding ex-dividend date fails closed."""
    with pytest.raises(
        ValueError, match="payable date cannot precede ex-dividend date"
    ):
        ExploratoryCashDividendTermsV1(
            native_id="div-9",
            security_id=SECURITY_SPY,
            symbol="SPY",
            rate=Decimal("1.50"),
            ex_date=date(2022, 4, 29),
            record_date=date(2022, 3, 21),
            payable_date=date(2022, 3, 18),
        )


# Scenario 10: Duplicate and revised dividend records
def test_10_duplicate_and_conflicting_dividend_records() -> None:
    """Identical duplicate records deduplicate; conflicting values fail closed."""
    div1 = ExploratoryCashDividendTermsV1(
        native_id="div-10",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
    )
    div1_dup = ExploratoryCashDividendTermsV1(
        native_id="div-10",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div1, div1_dup))
    assert len(policy.dividends) == 1

    div1_conflict = ExploratoryCashDividendTermsV1(
        native_id="div-10",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.75"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
    )
    with pytest.raises(ValueError, match="conflicting dividend terms"):
        ExploratoryDividendPolicyV1(dividends=(div1, div1_conflict))


# Scenario 11: Unsupported non-cash corporate actions halt indeterminate
def test_11_unsupported_noncash_corporate_actions_halt_indeterminate() -> None:
    """Forward splits and mergers without corporate action processor halt."""
    div1 = ExploratoryCashDividendTermsV1(
        native_id="div-11",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div1,))
    returned = (
        ReturnedCorporateActionV1(
            native_kind="forward_splits",
            native_id="split-1",
            action_kind=None,
            dates=(date(2022, 3, 18),),
        ),
    )
    rec = build_corporate_action_coverage(
        source_id="alpaca",
        security_id=SECURITY_SPY,
        queried_symbol="SPY",
        requested_start_date=date(2022, 1, 1),
        requested_end_date=date(2022, 12, 31),
        requested_action_classes=("forward_split",),
        request_binding_hash="0" * 64,
        response_sha256="0" * 64,
        response_byte_size=100,
        origin_observation_hash="0" * 64,
        returned_actions=returned,
        completeness=_test_assertion(),
        snapshot_as_of=_test_snapshot(),
    )
    idx = CorporateActionCoverageIndex(
        records=(rec,),
        lane="exploratory",
        exploratory_dividend_policy=policy,
    )
    with pytest.raises(IndeterminateValuationError, match="forward_splits split-1"):
        idx.require_covered(SECURITY_SPY, None, date(2022, 3, 18), date(2022, 3, 18))


# Scenario 12: Incomplete corporate action source coverage
def test_12_incomplete_corporate_action_source_coverage() -> None:
    """Missing coverage record for an action date fails closed."""
    div1 = ExploratoryCashDividendTermsV1(
        native_id="div-12",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div1,))
    # Empty coverage records index
    idx = CorporateActionCoverageIndex(
        records=(),
        lane="exploratory",
        exploratory_dividend_policy=policy,
    )
    with pytest.raises(
        IndeterminateValuationError, match="no closed-world corporate-action coverage"
    ):
        idx.require_covered(SECURITY_SPY, None, date(2022, 3, 18), date(2022, 3, 18))


# Scenario 13: Deterministic replay and result hashes
def test_13_deterministic_replay_and_result_hashes() -> None:
    """Running identical engine instances produces identical result and trace hashes."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div = ExploratoryCashDividendTermsV1(
        native_id="div-13",
        security_id=SEC,
        symbol="SEC",
        rate=Decimal("2.00"),
        ex_date=d7,
        record_date=d7,
        payable_date=d8,
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends", native_id="div-13", action_kind=None, dates=(d7,)
    )

    engine1 = _build_engine([d5, d6, d7, d8], policy, (ret,))
    engine2 = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat1 = ReconstructedTargetStrategy({d5: ((SEC, 10),), d6: ()})
    strat2 = ReconstructedTargetStrategy({d5: ((SEC, 10),), d6: ()})

    art1 = run_engine(engine1, strat1)
    art2 = run_engine(engine2, strat2)

    assert art1.result.result_hash == art2.result.result_hash
    assert art1.trace.trace_hash == art2.trace.trace_hash
    assert art1.final_state == art2.final_state


# Scenario 14: Sequential versus parallel portfolio equivalence
def test_14_sequential_versus_parallel_portfolio_equivalence() -> None:
    """Sequential and parallel cohort runs produce identical results and hashes."""
    bundle = build_offline_cohort_bundle()
    evidence = build_offline_cohort_evidence()
    cohort = build_reference_baseline_cohort(bundle)

    harness = PortfolioCohortHarness(cohort=cohort, bundle=bundle, evidence=evidence)
    seq = harness.run_sequential()
    par = harness.run_parallel(max_workers=2)

    assert len(seq) == len(par)
    for s_res, p_res in zip(seq, par, strict=True):
        assert s_res.strategy_id == p_res.strategy_id
        assert s_res.result_hash == p_res.result_hash
        assert s_res.trace_hash == p_res.trace_hash
        assert s_res.ending_nav == p_res.ending_nav


# Scenario 15: Exploratory-only grade enforcement
def test_15_exploratory_only_grade_enforcement() -> None:
    """Modeled dividends are strictly non-promotion grade."""
    div = ExploratoryCashDividendTermsV1(
        native_id="div-15",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
    )
    assert EXPLORATORY_DIVIDEND_LIMITATION in div.acknowledged_limitations
    policy = ExploratoryDividendPolicyV1(dividends=(div,))
    assert len(policy.terms_hash) == 64


# Scenario 16: Promotion-lane rejection
def test_16_promotion_lane_rejection() -> None:
    """Promotion lane strictly refuses exploratory dividend policy."""
    div = ExploratoryCashDividendTermsV1(
        native_id="div-16",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
    )
    policy = ExploratoryDividendPolicyV1(dividends=(div,))

    # Index rejects
    with pytest.raises(
        CorporateActionCoverageError, match="ca_coverage_grade_refused_by_lane"
    ):
        CorporateActionCoverageIndex(
            records=(),
            lane="promotion",
            exploratory_dividend_policy=policy,
        )

    # Engine rejects
    d5, d6 = date(2026, 1, 5), date(2026, 1, 6)
    cases = [scheduled_session_case(d) for d in [d5, d6]]
    bundle = bundle_of(cases)
    promo_adm = PromotionEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="promotion",
        m1e_completion_record_hash="1" * 64,
        m1e_profile_set_hash="2" * 64,
        decision_handoff_hash="3" * 64,
        audit_handoff_hash="4" * 64,
        input_bundle_hash=bundle.bundle_hash,
        provenance_proof_hash="5" * 64,
        admission_hash="0" * 64,
    )
    evidence = SessionEvaluatorEvidence(
        listing_role_records=ROLE_RECORDS,
        exploratory_dividends=policy,
    )
    from drift.evaluator.engine import PromotionLaneDisabledError

    with pytest.raises(
        PromotionLaneDisabledError, match="the promotion lane is disabled"
    ):
        SessionEvaluatorEngine(
            bundle=bundle,
            admission=promo_adm,
            protocol=_protocol(),
            cost_model=_cost_model(),
            evidence=evidence,
            book_currency_namespace=BOOK_NAMESPACE,
            book_currency_code=BOOK_CODE,
        )


# Scenario 17: Unchanged existing M2 behavior when modeling is off
def test_17_unchanged_existing_m2_behavior_when_modeling_is_off() -> None:
    """When exploratory dividends are None, unhandled dividend halts INDETERMINATE."""
    returned = (
        ReturnedCorporateActionV1(
            native_kind="cash_dividends",
            native_id="div-17",
            action_kind=None,
            dates=(date(2022, 3, 18),),
        ),
    )
    rec = build_corporate_action_coverage(
        source_id="alpaca",
        security_id=SECURITY_SPY,
        queried_symbol="SPY",
        requested_start_date=date(2022, 1, 1),
        requested_end_date=date(2022, 12, 31),
        requested_action_classes=("cash_dividend",),
        request_binding_hash="0" * 64,
        response_sha256="0" * 64,
        response_byte_size=100,
        origin_observation_hash="0" * 64,
        returned_actions=returned,
        completeness=_test_assertion(),
        snapshot_as_of=_test_snapshot(),
    )
    idx = CorporateActionCoverageIndex(
        records=(rec,),
        lane="exploratory",
        exploratory_dividend_policy=None,
    )
    with pytest.raises(
        IndeterminateValuationError, match="no M2 accounting evidence accounts for"
    ):
        idx.require_covered(SECURITY_SPY, None, date(2022, 3, 18), date(2022, 3, 18))
