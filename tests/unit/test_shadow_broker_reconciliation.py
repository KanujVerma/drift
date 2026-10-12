"""Unit tests for Shadow Broker accounting reconciliation and replay (M12-4)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

import pytest

from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
)
from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    EligibilityStatus,
    build_market_execution_eligibility,
    build_simulated_order,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.shadow.broker import ShadowBroker
from drift.shadow.journal import SimulationExecutionJournal
from drift.shadow.reconciler import (
    ReconciliationMismatchError,
    ShadowBrokerReconciler,
)

NOW1 = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
NOW2 = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))
KEY2 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2))


def _make_cost_model() -> EvaluationCostModelV1:
    placeholder = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="test-reconciler-costs",
        commission_per_share=Decimal("0.01"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("0.00"),
        adverse_slippage_basis_points=Decimal("5.00"),
        cost_model_hash="placeholder",
    )
    c_hash = evaluation_cost_model_hash(placeholder)
    return EvaluationCostModelV1(
        schema_version="1",
        model_id="test-reconciler-costs",
        commission_per_share=Decimal("0.01"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("0.00"),
        adverse_slippage_basis_points=Decimal("5.00"),
        cost_model_hash=c_hash,
    )


def _make_clock_and_state(
    initial_cash: Decimal = Decimal("100000"),
) -> tuple[SessionClockV1, PortfolioStateV2]:
    p1 = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=KEY1,
        authority="realized",
        opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 1, 21, 0, tzinfo=UTC),
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash="placeholder",
    )
    sess1 = EvaluationSessionV1(
        schema_version="1",
        session_key=KEY1,
        authority="realized",
        opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 1, 21, 0, tzinfo=UTC),
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash=evaluation_session_hash(p1),
    )

    p2 = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=KEY2,
        authority="realized",
        opened_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 2, 21, 0, tzinfo=UTC),
        authority_record_hashes=("3" * 64,),
        authority_proof_hashes=("4" * 64,),
        session_hash="placeholder",
    )
    sess2 = EvaluationSessionV1(
        schema_version="1",
        session_key=KEY2,
        authority="realized",
        opened_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 2, 21, 0, tzinfo=UTC),
        authority_record_hashes=("3" * 64,),
        authority_proof_hashes=("4" * 64,),
        session_hash=evaluation_session_hash(p2),
    )

    pc = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1, sess2),
        acknowledged_limitations=(),
        clock_hash="placeholder",
    )
    clock = SessionClockV1(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1, sess2),
        acknowledged_limitations=(),
        clock_hash=session_clock_hash(pc),
    )

    state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="5" * 64,
        session_key=KEY1,
        cash_balance=initial_cash,
        holdings=(),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        mark=None,
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=initial_cash,
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
    )
    return clock, state


def test_reconciler_matched_session() -> None:
    """Verifies successful reconciliation when broker matches portfolio state."""
    clock, initial_state = _make_clock_and_state()
    kernel = PortfolioAccountingKernel(initial_state, session_clock=clock)
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)
    reconciler = ShadowBrokerReconciler(broker=broker)

    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=50,
        created_at=NOW1,
    )
    broker.submit_order(order)
    broker.execute_order(
        order,
        open_price=Decimal("100"),
        eligibility=el,
        execution_time=NOW1,
    )

    rec = reconciler.reconcile_session(
        session_key=KEY1,
        reconciled_at=NOW1,
    )
    assert rec.status == "matched"
    assert rec.discrepancies == ()
    assert rec.holdings_count == 1
    assert rec.cash == kernel.state.cash_balance

    # Verify journal recorded reconciliation
    journal_recs = journal.list_reconciliations_for_session(KEY1)
    assert len(journal_recs) == 1
    assert journal_recs[0] == rec


def test_reconciler_discrepancy_and_fail_fast() -> None:
    """Verifies reconciliation detects session mismatch and respects fail_fast."""
    clock, initial_state = _make_clock_and_state()
    kernel = PortfolioAccountingKernel(initial_state, session_clock=clock)
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)
    reconciler = ShadowBrokerReconciler(broker=broker)

    # Kernel is at KEY1, but reconciliation requested for KEY2
    rec = reconciler.reconcile_session(
        session_key=KEY2,
        reconciled_at=NOW2,
        fail_fast=False,
    )
    assert rec.status == "mismatched"
    assert len(rec.discrepancies) == 1
    assert "session_key_mismatch" in rec.discrepancies[0]

    with pytest.raises(ReconciliationMismatchError, match="session_key_mismatch"):
        reconciler.reconcile_session(
            session_key=KEY2,
            reconciled_at=NOW2,
            fail_fast=True,
        )


def test_verify_replay_projection_invariance() -> None:
    """Verifies journal replay reproduces exact live portfolio state bit for bit."""
    clock, initial_state = _make_clock_and_state()
    kernel = PortfolioAccountingKernel(initial_state, session_clock=clock)
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)
    reconciler = ShadowBrokerReconciler(broker=broker)

    sec1 = uuid7()
    sec2 = uuid7()
    el1 = build_market_execution_eligibility(
        security_id=sec1,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )
    el2 = build_market_execution_eligibility(
        security_id=sec2,
        session_key=KEY2,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="2" * 64,
    )

    # Session 1: Buy sec1
    ord1 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec1,
        side="buy",
        quantity=100,
        created_at=NOW1,
    )
    broker.submit_order(ord1)
    broker.execute_session(
        session_key=KEY1,
        open_prices={sec1: Decimal("50.00")},
        eligibilities={sec1: el1},
        execution_time=NOW1,
    )

    # Advance to Session 2
    kernel.advance_session(KEY2)

    # Session 2: Buy sec2, sell part of sec1
    ord2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY2,
        security_id=sec2,
        side="buy",
        quantity=50,
        created_at=NOW2,
    )
    ord3 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY2,
        security_id=sec1,
        side="sell",
        quantity=30,
        created_at=NOW2,
    )
    broker.submit_order(ord2)
    broker.submit_order(ord3)
    broker.execute_session(
        session_key=KEY2,
        open_prices={sec1: Decimal("55.00"), sec2: Decimal("80.00")},
        eligibilities={sec1: el1, sec2: el2},
        execution_time=NOW2,
    )

    # Run replay invariance verification
    assert (
        reconciler.verify_replay_projection(
            initial_state=initial_state,
            session_clock=clock,
        )
        is True
    )
