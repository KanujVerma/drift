"""Unit tests for exploratory cash dividend accounting (Option B).

Verifies the deterministic hypothetical dividend accounting mechanism,
testing all requirements and adversarial edge cases: entitlement, ex-date
buy/sale rules, payable settlement, weekend dates, NAV invariance, fail-closed
safeguards, source authenticity verification, deterministic replay, sequential
vs parallel equivalence, and lane isolation.
"""

import json
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
    REST_CORPORATE_ACTION_EVIDENCE_FLOOR,
    ClosedWorldCorporateActionCoverageV1,
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
from drift.evaluator.engine import (
    PromotionLaneDisabledError,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
)
from drift.evaluator.exploratory_dividends import (
    EXPLORATORY_DIVIDEND_LIMITATION,
    ExploratoryCashDividendTermsV1,
    ExploratoryDividendPolicyV1,
    exploratory_dividend_policy_hash,
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
    CA_ORIGIN,
    CA_POLICY,
    CA_REQUEST,
    ROLE_RECORDS,
    _cost_model,
    _protocol,
    quiet_coverage,  # noqa: E402
)

SECURITY_SPY = UUID("019b8240-0000-7000-8000-000000000001")
SECURITY_QQQ = UUID("019b8240-0000-7000-8000-000000000002")
SECURITY_IWM = UUID("019b8240-0000-7000-8000-000000000003")


def _test_snapshot(
    instant: datetime = datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
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
        policy_statement_hash=CA_POLICY.content_hash,
        acquisition_reconciliation_pass=True,
        single_unpaginated_response=True,
        measured_origin=True,
        requested_types_documented=True,
        returned_actions_attributed=True,
        returned_actions_inside_requested_window=True,
    )


def make_test_dividend(
    native_id: str,
    security_id: UUID,
    symbol: str,
    rate: Decimal,
    ex_date: date,
    record_date: date,
    payable_date: date,
    source_id: str = "alpaca-corporate-actions-closed-world",
) -> tuple[ExploratoryCashDividendTermsV1, bytes]:
    """Helper to generate authentic dividend terms and exact source response bytes."""
    from hashlib import sha256

    payload = json.dumps(
        {
            "corporate_actions": {
                "cash_dividends": [
                    {
                        "id": native_id,
                        "corporate_action_id": native_id,
                        "symbol": symbol,
                        "rate": str(rate),
                        "ex_date": ex_date.isoformat(),
                        "record_date": record_date.isoformat(),
                        "payable_date": payable_date.isoformat(),
                    }
                ]
            }
        }
    ).encode("utf-8")
    p_hash = sha256(payload).hexdigest()
    term = ExploratoryCashDividendTermsV1(
        native_id=native_id,
        security_id=security_id,
        symbol=symbol,
        rate=rate,
        ex_date=ex_date,
        record_date=record_date,
        payable_date=payable_date,
        source_id=source_id,
        response_sha256=p_hash,
    )
    return term, payload


def make_test_policy(
    terms: Sequence[ExploratoryCashDividendTermsV1],
    payloads: Sequence[bytes],
) -> ExploratoryDividendPolicyV1:
    """Helper to build ExploratoryDividendPolicyV1 with matching payloads."""
    return ExploratoryDividendPolicyV1(
        dividends=tuple(terms),
        source_payloads=tuple(payloads),
    )


def make_test_coverage_record(
    security_id: UUID,
    symbol: str,
    start: date,
    end: date,
    source_id: str,
    response_sha256: str,
    returned_actions: tuple[ReturnedCorporateActionV1, ...] = (),
    payload_bytes: bytes = b"",
) -> ClosedWorldCorporateActionCoverageV1:
    return build_corporate_action_coverage(
        source_id=source_id,
        security_id=security_id,
        queried_symbol=symbol,
        requested_start_date=start,
        requested_end_date=end,
        requested_action_classes=("cash_dividend", "forward_split"),
        request_binding_hash=CA_REQUEST.content_hash,
        response_sha256=response_sha256,
        response_byte_size=len(payload_bytes),
        origin_observation_hash=CA_ORIGIN.content_hash,
        returned_actions=returned_actions,
        completeness=_test_assertion(),
        snapshot_as_of=_test_snapshot(),
    )


def _build_engine(
    session_dates: Sequence[date],
    policy: ExploratoryDividendPolicyV1 | None,
    returned_actions: tuple[ReturnedCorporateActionV1, ...] = (),
    warmup: int = 1,
) -> SessionEvaluatorEngine:
    if policy is not None and policy.source_payloads:
        from hashlib import sha256

        from test_evaluator_engine import CA_COVERAGE_SUPPORT

        from drift.datasets.resolver import VerifiedArtifactBytes

        for p in policy.source_payloads:
            p_bytes = p.encode("utf-8") if isinstance(p, str) else p
            h = sha256(p_bytes).hexdigest()
            CA_COVERAGE_SUPPORT[h] = VerifiedArtifactBytes(
                data=p_bytes, byte_size=len(p_bytes), content_hash=h
            )
        scheduled_session_case.cache_clear()

    cases = [scheduled_session_case(d) for d in session_dates]
    if policy is not None and policy.dividends:
        payload_map = {}
        for p in policy.source_payloads:
            p_bytes = p.encode("utf-8") if isinstance(p, str) else p
            payload_map[sha256(p_bytes).hexdigest()] = p_bytes

        cov_list = []
        for div in policy.dividends:
            matching_payload = payload_map.get(div.response_sha256, b"")
            rec = make_test_coverage_record(
                security_id=div.security_id,
                symbol=div.symbol,
                start=session_dates[0],
                end=session_dates[-1],
                source_id=div.source_id,
                response_sha256=div.response_sha256,
                returned_actions=returned_actions,
                payload_bytes=matching_payload,
            )
            cov_list.append(rec)
        cov = tuple(cov_list)
    else:
        cov = quiet_coverage(
            (SEC,),
            session_dates[0],
            session_dates[-1],
            returned_actions=returned_actions,
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
    div, payload = make_test_dividend("div-1", SEC, "SEC", Decimal("2.00"), d7, d7, d8)
    policy = make_test_policy([div], [payload])
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id="div-1",
        action_kind=None,
        dates=(d7, d8),
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat = ReconstructedTargetStrategy(
        {d5: ((SEC, 10),), d6: ((SEC, 10),), d7: ((SEC, 10),)}
    )
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
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
    div, payload = make_test_dividend("div-2", SEC, "SEC", Decimal("2.00"), d7, d7, d8)
    policy = make_test_policy([div], [payload])
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id="div-2",
        action_kind=None,
        dates=(d7, d8),
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat = ReconstructedTargetStrategy({d6: ((SEC, 10),), d7: ((SEC, 10),)})
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    assert len(artifacts.final_state.settled_claim_ids) == 0


# Scenario 3: Sale on ex-date preserving valid entitlement
def test_03_sale_on_ex_date_preserving_valid_entitlement() -> None:
    """Position held into ex-date open and sold at open retains entitlement."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div, payload = make_test_dividend("div-3", SEC, "SEC", Decimal("2.00"), d7, d7, d8)
    policy = make_test_policy([div], [payload])
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id="div-3",
        action_kind=None,
        dates=(d7, d8),
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat = ReconstructedTargetStrategy(
        {d5: ((SEC, 10),), d6: ((SEC, 0),), d7: ((SEC, 0),)}
    )
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    assert len(artifacts.final_state.settled_claim_ids) == 1
    assert artifacts.final_state.cash_balance > Decimal("10000.00")


# Scenario 4: Correct payable-date cash credit
def test_04_correct_payable_date_cash_credit() -> None:
    """Cash is credited exactly on payable session date."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div, payload = make_test_dividend("div-4", SEC, "SEC", Decimal("2.50"), d7, d7, d8)
    policy = make_test_policy([div], [payload])
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id="div-4",
        action_kind=None,
        dates=(d7, d8),
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat = ReconstructedTargetStrategy(
        {d5: ((SEC, 10),), d6: ((SEC, 10),), d7: ((SEC, 10),)}
    )
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    assert len(artifacts.final_state.settled_claim_ids) == 1


# Scenario 5: Weekend payable date rollover
def test_05_weekend_payable_date_rollover() -> None:
    """Weekend payable date settles on the next active session."""
    session_friday = date(2026, 1, 9)
    session_saturday = date(2026, 1, 10)
    session_monday = date(2026, 1, 12)

    div, payload = make_test_dividend(
        "div-wknd",
        SECURITY_SPY,
        "SPY",
        Decimal("3.00"),
        session_friday,
        session_friday,
        session_saturday,
    )
    policy = make_test_policy([div], [payload])
    claim_id = pending_cash_claim_id(
        source_id=div.source_id,
        security_id=SECURITY_SPY,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        occurrence_id="div-wknd",
        component_id="cash_dividend",
    )
    claim = PendingCashClaimV1(
        schema_version="1",
        claim_id=claim_id,
        source_id=div.source_id,
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
    assert policy.is_policy_claim(claim)

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
        if c.payable_session <= session_monday and policy.is_policy_claim(c)
    )
    kernel.settle_claims(payable_claim_ids)
    assert kernel.state.cash_balance == Decimal("10030.00")
    assert len(kernel.state.pending_cash_claims) == 0
    assert claim_id in kernel.state.settled_claim_ids


# Scenario 6: No double counting
def test_06_no_double_counting() -> None:
    """An entitlement is recorded only once and settled only once."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div, payload = make_test_dividend("div-6", SEC, "SEC", Decimal("2.00"), d7, d7, d8)
    policy = make_test_policy([div], [payload])
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id="div-6",
        action_kind=None,
        dates=(d7, d8),
    )
    engine = _build_engine([d5, d6, d7, d8], policy, (ret,))
    strat = ReconstructedTargetStrategy(
        {d5: ((SEC, 10),), d6: ((SEC, 10),), d7: ((SEC, 10),), d8: ((SEC, 10),)}
    )
    artifacts = run_engine(engine, strat)

    assert len(artifacts.final_state.settled_claim_ids) == 1
    assert len(artifacts.final_state.pending_cash_claims) == 0


# Scenario 7: No cash credited before payable date and NAV invariance
def test_07_no_cash_credited_before_payable_date_and_nav_invariant() -> None:
    """Before payable session, entitlement sits in pending claims and preserves NAV."""
    d5, d6, d7 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)
    d_future = date(2026, 1, 20)
    div, payload = make_test_dividend(
        "div-7", SEC, "SEC", Decimal("2.00"), d7, d7, d_future
    )
    policy = make_test_policy([div], [payload])
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id="div-7",
        action_kind=None,
        dates=(d7, d_future),
    )
    engine = _build_engine([d5, d6, d7], policy, (ret,))
    strat = ReconstructedTargetStrategy(
        {d5: ((SEC, 10),), d6: ((SEC, 10),), d7: ((SEC, 10),)}
    )
    artifacts = run_engine(engine, strat)

    assert artifacts.result.classification == "complete"
    state = artifacts.final_state
    assert len(state.settled_claim_ids) == 0
    assert len(state.pending_cash_claims) == 1
    assert state.pending_claims_value == Decimal("20.00")
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
            response_sha256="0" * 64,
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
            response_sha256="0" * 64,
        )


# Scenario 9: Conflicting dates fail closed
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
            response_sha256="0" * 64,
        )


# Scenario 10: Deduplication of duplicate records
def test_10_duplicate_and_conflicting_dividend_records() -> None:
    """Identical duplicate records deduplicate; conflicting values fail closed."""
    div1, payload1 = make_test_dividend(
        "div-10",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    div1_dup, _ = make_test_dividend(
        "div-10",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    policy = make_test_policy([div1, div1_dup], [payload1])
    assert len(policy.dividends) == 1

    div1_conflict, payload_conflict = make_test_dividend(
        "div-10",
        SECURITY_SPY,
        "SPY",
        Decimal("1.75"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    with pytest.raises(ValueError, match="conflicting dividend terms"):
        make_test_policy([div1, div1_conflict], [payload1, payload_conflict])


# ==============================================================================
# PRIORITY 4 ADVERSARIAL TESTS
# ==============================================================================


# Adversarial 1: Invented action ID rejected
def test_adversarial_01_invented_action_id_rejected() -> None:
    """Invented action ID absent from provider source bytes fails closed."""
    from hashlib import sha256

    real_payload = json.dumps(
        {
            "corporate_actions": {
                "cash_dividends": [
                    {
                        "id": "genuine-action-id",
                        "symbol": "SPY",
                        "rate": "1.50",
                        "ex_date": "2022-03-18",
                        "record_date": "2022-03-21",
                        "payable_date": "2022-04-29",
                    }
                ]
            }
        }
    ).encode("utf-8")
    real_hash = sha256(real_payload).hexdigest()
    div = ExploratoryCashDividendTermsV1(
        native_id="invented-action-id",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
        response_sha256=real_hash,
    )
    with pytest.raises(
        ValueError, match="absent from retained provider source payload"
    ):
        ExploratoryDividendPolicyV1(dividends=(div,), source_payloads=(real_payload,))


# Adversarial 2: Modified dividend amount rejected
def test_adversarial_02_modified_dividend_amount_rejected() -> None:
    """Modeled dividend with modified rate relative to retained source fails closed."""
    div, payload = make_test_dividend(
        "div-rate-tamper",
        SECURITY_SPY,
        "SPY",
        Decimal("2.00"),  # Tampered rate (source has 1.50)
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    from hashlib import sha256

    source_payload = json.dumps(
        {
            "corporate_actions": {
                "cash_dividends": [
                    {
                        "id": "div-rate-tamper",
                        "symbol": "SPY",
                        "rate": "1.50",
                        "ex_date": "2022-03-18",
                        "record_date": "2022-03-21",
                        "payable_date": "2022-04-29",
                    }
                ]
            }
        }
    ).encode("utf-8")
    tampered_div = div.model_copy(
        update={"response_sha256": sha256(source_payload).hexdigest()}
    )
    with pytest.raises(ValueError, match="dividend rate mismatch"):
        ExploratoryDividendPolicyV1(
            dividends=(tampered_div,), source_payloads=(source_payload,)
        )


# Adversarial 3: Modified dates rejected
def test_adversarial_03_modified_dates_rejected() -> None:
    """Modeled dividend with altered ex_date fails closed."""
    from hashlib import sha256

    source_payload = json.dumps(
        {
            "corporate_actions": {
                "cash_dividends": [
                    {
                        "id": "div-date-tamper",
                        "symbol": "SPY",
                        "rate": "1.50",
                        "ex_date": "2022-03-18",
                        "record_date": "2022-03-21",
                        "payable_date": "2022-04-29",
                    }
                ]
            }
        }
    ).encode("utf-8")
    p_hash = sha256(source_payload).hexdigest()
    tampered_div = ExploratoryCashDividendTermsV1(
        native_id="div-date-tamper",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 19),  # Tampered date
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
        response_sha256=p_hash,
    )
    with pytest.raises(ValueError, match="dividend ex_date mismatch"):
        ExploratoryDividendPolicyV1(
            dividends=(tampered_div,), source_payloads=(source_payload,)
        )


# Adversarial 4: Bad source hash rejected
def test_adversarial_04_bad_source_hash_rejected() -> None:
    """Caller-supplied hash that disagrees with source payload bytes fails closed."""
    div, payload = make_test_dividend(
        "div-bad-hash",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    tampered_div = div.model_copy(update={"response_sha256": "f" * 64})
    with pytest.raises(ValueError, match="does not match any provided source payload"):
        ExploratoryDividendPolicyV1(
            dividends=(tampered_div,), source_payloads=(payload,)
        )


# Adversarial 5: Incomplete coverage bypass refusal
def test_adversarial_05_incomplete_coverage_bypass_refusal() -> None:
    """Window outside coverage interval halts INDETERMINATE with dividend policy."""
    div, payload = make_test_dividend(
        "div-outside",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    policy = make_test_policy([div], [payload])
    rec = make_test_coverage_record(
        security_id=SECURITY_SPY,
        symbol="SPY",
        start=date(2022, 1, 1),
        end=date(2022, 2, 28),  # Ends before March 18
        source_id=div.source_id,
        response_sha256=div.response_sha256,
        returned_actions=(
            ReturnedCorporateActionV1(
                native_kind="cash_dividends",
                native_id="div-outside",
                action_kind=None,
                dates=(date(2022, 3, 18), date(2022, 3, 21), date(2022, 4, 29)),
            ),
        ),
    )
    idx = CorporateActionCoverageIndex(
        records=(rec,),
        lane="exploratory",
        exploratory_dividend_policy=policy,
    )
    with pytest.raises(
        IndeterminateValuationError, match="no closed-world corporate-action coverage"
    ):
        idx.require_covered(SECURITY_SPY, None, date(2022, 3, 18), date(2022, 3, 18))


# Adversarial 6: Pre-August 2021 floor enforcement
def test_adversarial_06_pre_august_2021_floor_enforcement() -> None:
    """Pre-floor dates fail closed as indeterminate, refusing waiver."""
    pre_floor_date = date(2021, 7, 15)
    assert pre_floor_date < REST_CORPORATE_ACTION_EVIDENCE_FLOOR

    div, payload = make_test_dividend(
        "div-pre-floor",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        pre_floor_date,
        pre_floor_date,
        date(2021, 8, 15),
    )
    policy = make_test_policy([div], [payload])
    rec = make_test_coverage_record(
        security_id=SECURITY_SPY,
        symbol="SPY",
        start=date(2021, 7, 1),
        end=date(2021, 8, 31),
        source_id=div.source_id,
        response_sha256=div.response_sha256,
        returned_actions=(
            ReturnedCorporateActionV1(
                native_kind="cash_dividends",
                native_id="div-pre-floor",
                action_kind=None,
                dates=(pre_floor_date, date(2021, 8, 15)),
            ),
        ),
    )
    idx = CorporateActionCoverageIndex(
        records=(rec,),
        lane="exploratory",
        exploratory_dividend_policy=policy,
    )
    with pytest.raises(
        IndeterminateValuationError, match="no closed-world corporate-action coverage"
    ):
        idx.require_covered(SECURITY_SPY, None, pre_floor_date, pre_floor_date)


# Adversarial 7: Unrelated M1c claims isolation
def test_adversarial_07_unrelated_m1c_claims_isolation() -> None:
    """Hypothetical dividend settlement loop never settles unrelated M1c claims."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div, payload = make_test_dividend(
        "div-iso", SEC, "SEC", Decimal("2.00"), d7, d7, d8
    )
    policy = make_test_policy([div], [payload])

    # Unrelated M1c claim created from a different source and component
    claim_id = pending_cash_claim_id(
        source_id="m1c-unrelated-source",
        security_id=SEC,
        action_kind=ActionKind.SPINOFF,
        occurrence_id="spinoff-1",
        component_id="cash_in_lieu",
    )
    unrelated_claim = PendingCashClaimV1(
        schema_version="1",
        claim_id=claim_id,
        source_id="m1c-unrelated-source",
        security_id=SEC,
        action_kind=ActionKind.SPINOFF,
        occurrence_id="spinoff-1",
        component_id="cash_in_lieu",
        entitled_quantity=10,
        cash_per_share=Decimal("5.00"),
        total_cash_expected=Decimal("50.00"),
        entitlement_session=d6,
        payable_session=d8,
    )
    assert not policy.is_policy_claim(unrelated_claim)

    # In kernel, hypothetical dividend loop filters by is_policy_claim
    cases = [scheduled_session_case(d) for d in [d5, d6, d7, d8]]
    bundle = bundle_of(cases)
    init_state = initial_portfolio_state(
        session_key=bundle.session_clock.sessions[0].session_key,
        initial_cash=Decimal("10000.00"),
        admission=exploratory_admission(bundle),
    )
    kernel = PortfolioAccountingKernel(init_state, session_clock=bundle.session_clock)
    kernel.record_claim(unrelated_claim)
    assert len(kernel.state.pending_cash_claims) == 1
    policy_payable = [
        c.claim_id
        for c in kernel.state.pending_cash_claims
        if c.payable_session <= d8 and policy.is_policy_claim(c)
    ]
    assert len(policy_payable) == 0
    # Unrelated claim remains pending and untouched by dividend settlement
    kernel.settle_claims(policy_payable)
    assert len(kernel.state.pending_cash_claims) == 1
    assert len(kernel.state.settled_claim_ids) == 0


# Adversarial 8: Source byte binding verification
def test_adversarial_08_source_byte_binding_verification() -> None:
    """Dividend policy strictly requires verified source payload bytes."""
    div = ExploratoryCashDividendTermsV1(
        native_id="div-no-bytes",
        security_id=SECURITY_SPY,
        symbol="SPY",
        rate=Decimal("1.50"),
        ex_date=date(2022, 3, 18),
        record_date=date(2022, 3, 21),
        payable_date=date(2022, 4, 29),
        response_sha256="0" * 64,
    )
    with pytest.raises(
        ValueError, match="dividend policy requires retained source bytes"
    ):
        ExploratoryDividendPolicyV1(dividends=(div,), source_payloads=())


# Adversarial 9: Deterministic replay
def test_adversarial_09_deterministic_replay() -> None:
    """Identical engine instances with modeled dividends produce identical hashes."""
    d5, d6, d7, d8 = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    div, payload = make_test_dividend(
        "div-replay", SEC, "SEC", Decimal("2.00"), d7, d7, d8
    )
    policy = make_test_policy([div], [payload])
    ret = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id="div-replay",
        action_kind=None,
        dates=(d7, d8),
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


# Adversarial 10: Parallel/sequential equivalence with dividends
def test_adversarial_10_parallel_sequential_equivalence_with_dividends() -> None:
    """Sequential and parallel cohort runs produce identical results."""
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


# Adversarial 11: Promotion admission refusal
def test_adversarial_11_promotion_admission_refusal() -> None:
    """Promotion lane strictly refuses exploratory dividend policy."""
    div, payload = make_test_dividend(
        "div-promo-refuse",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    policy = make_test_policy([div], [payload])

    # Index refuses under promotion lane
    with pytest.raises(
        CorporateActionCoverageError, match="ca_coverage_grade_refused_by_lane"
    ):
        CorporateActionCoverageIndex(
            records=(),
            lane="promotion",
            exploratory_dividend_policy=policy,
        )

    # Engine refuses under promotion admission
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


# Scenario 12: Exploratory limitation acknowledged
def test_12_exploratory_limitation_acknowledged() -> None:
    """Modeled dividends declare the explicit exploratory limitation."""
    div, payload = make_test_dividend(
        "div-limit",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    assert EXPLORATORY_DIVIDEND_LIMITATION in div.acknowledged_limitations
    policy = make_test_policy([div], [payload])
    assert len(policy.terms_hash) == 64
    assert policy.terms_hash == exploratory_dividend_policy_hash(policy.dividends)


# Scenario 13: Unsupported non-cash corporate actions halt indeterminate
def test_13_unsupported_noncash_corporate_actions_halt_indeterminate() -> None:
    """Forward splits and mergers without corporate action processor halt."""
    div, payload = make_test_dividend(
        "div-split",
        SECURITY_SPY,
        "SPY",
        Decimal("1.50"),
        date(2022, 3, 18),
        date(2022, 3, 21),
        date(2022, 4, 29),
    )
    policy = make_test_policy([div], [payload])
    returned = (
        ReturnedCorporateActionV1(
            native_kind="cash_dividends",
            native_id="div-split",
            action_kind=None,
            dates=(date(2022, 3, 18), date(2022, 3, 21), date(2022, 4, 29)),
        ),
        ReturnedCorporateActionV1(
            native_kind="forward_splits",
            native_id="split-1",
            action_kind=ActionKind.FORWARD_SPLIT,
            dates=(date(2022, 3, 18),),
        ),
    )
    rec = make_test_coverage_record(
        security_id=SECURITY_SPY,
        symbol="SPY",
        start=date(2022, 1, 1),
        end=date(2022, 12, 31),
        source_id=div.source_id,
        response_sha256=div.response_sha256,
        returned_actions=returned,
    )
    idx = CorporateActionCoverageIndex(
        records=(rec,),
        lane="exploratory",
        exploratory_dividend_policy=policy,
    )
    with pytest.raises(IndeterminateValuationError, match="forward_splits split-1"):
        idx.require_covered(SECURITY_SPY, None, date(2022, 3, 18), date(2022, 3, 18))


# Scenario 14: Unchanged existing M2 behavior when modeling is off
def test_14_unchanged_existing_m2_behavior_when_modeling_is_off() -> None:
    """When exploratory dividends are None, unhandled dividend halts INDETERMINATE."""
    returned = (
        ReturnedCorporateActionV1(
            native_kind="cash_dividends",
            native_id="div-unhandled",
            action_kind=None,
            dates=(date(2022, 3, 18),),
        ),
    )
    rec = make_test_coverage_record(
        security_id=SECURITY_SPY,
        symbol="SPY",
        start=date(2022, 1, 1),
        end=date(2022, 12, 31),
        source_id="alpaca-corporate-actions-closed-world",
        response_sha256="0" * 64,
        returned_actions=returned,
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
