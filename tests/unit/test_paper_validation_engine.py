"""Unit tests for ShadowValidationEngine (M15-4)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest

from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.paper_validation import build_market_tick
from drift.domain.risk import build_risk_policy
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal
from drift.validation.engine import (
    RiskHaltValidationError,
    ShadowValidationEngine,
)
from drift.validation.feed import MockMarketDataStreamer
from drift.validation.journal import PersistentShadowValidationJournal

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def _make_engine(
    tmp_path: Path,
    with_risk: bool = False,
) -> tuple[
    ShadowValidationEngine,
    MockMarketDataStreamer,
    MockBrokerAdapter,
    PersistentRiskJournal | None,
]:
    streamer = MockMarketDataStreamer()
    intent_db = tmp_path / "intent_journal.db"
    intent_journal = PersistentOrderIntentJournal(intent_db)
    adapter = MockBrokerAdapter(
        initial_cash=Decimal("100000"), default_fee=Decimal("1.00")
    )
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=intent_journal)

    shadow_db = tmp_path / "shadow_journal.db"
    shadow_journal = PersistentShadowValidationJournal(shadow_db)

    risk_gatekeeper: HardRiskGatekeeper | None = None
    risk_journal: PersistentRiskJournal | None = None
    if with_risk:
        risk_db = tmp_path / "risk_journal.db"
        risk_journal = PersistentRiskJournal(risk_db)
        policy = build_risk_policy(
            policy_id="test-risk-policy",
            max_order_notional=Decimal("10000"),
            max_order_quantity=1000,
            max_position_notional=Decimal("50000"),
            max_position_weight_basis_points=5000,
            max_gross_exposure_basis_points=10000,
            max_session_drawdown_basis_points=1000,
            max_trailing_drawdown_basis_points=1000,
            max_orders_per_minute=20,
        )
        risk_gatekeeper = HardRiskGatekeeper(
            policy=policy,
            journal=risk_journal,
            initial_nav=Decimal("100000"),
        )

    engine = ShadowValidationEngine(
        streamer=streamer,
        router=router,
        journal=shadow_journal,
        session_key=KEY1,
        risk_gatekeeper=risk_gatekeeper,
    )
    return engine, streamer, adapter, risk_journal


def test_engine_process_ticks_and_price_sync(tmp_path: Path) -> None:
    """Verifies tick processing updates engine price map and adapter pricing."""
    engine, streamer, adapter, _ = _make_engine(tmp_path)
    sec_id = uuid7()

    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("125.50"),
        last_size=100,
        bid_price=Decimal("125.40"),
        ask_price=Decimal("125.60"),
    )
    streamer.push_tick(tick)

    processed = engine.process_next_tick()
    assert processed is not None
    assert processed.tick_id == tick.tick_id
    assert engine.get_latest_price(sec_id) == Decimal("125.50")
    # Verify adapter has updated mock price
    assert adapter._fill_price_map.get(sec_id) == Decimal("125.50")


def test_engine_route_intent_and_drift_tracking(tmp_path: Path) -> None:
    """Verifies intent execution records fill and calculates slippage drift."""
    engine, streamer, adapter, _ = _make_engine(tmp_path)
    sec_id = uuid7()

    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.00"),
        last_size=50,
    )
    streamer.push_tick(tick)
    engine.process_next_tick()

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="engine-test-order-1",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    report = engine.route_intent(intent, intended_price=Decimal("99.50"))
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 10

    # Drift report should be recorded in journal
    drifts = engine.journal.list_drift_reports_for_security(sec_id)
    assert len(drifts) == 1
    # ((100 - 99.50) / 99.50) * 10000 = 50.25 bps
    assert drifts[0].intended_price == Decimal("99.50")
    assert drifts[0].fill_price == Decimal("100.00")


def test_engine_kill_switch_halt(tmp_path: Path) -> None:
    """Verifies tripped kill switch halts order submission."""
    engine, streamer, adapter, risk_journal = _make_engine(tmp_path, with_risk=True)
    assert risk_journal is not None
    sec_id = uuid7()

    # Trip kill switch
    risk_journal.trip_kill_switch(reason="emergency test halt", tripped_at=NOW)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="halted-order-1",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
    )

    with pytest.raises(RiskHaltValidationError, match="kill switch active"):
        engine.route_intent(intent)


def test_engine_finalize_summary(tmp_path: Path) -> None:
    """Verifies end-to-end session summary generation and persistence."""
    engine, streamer, adapter, _ = _make_engine(tmp_path)
    sec_id = uuid7()

    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("50.00"),
        last_size=10,
    )
    streamer.push_tick(tick)
    engine.process_next_tick()

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="summary-order-1",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=20,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )
    engine.route_intent(intent)

    summary = engine.finalize_summary(final_equity=Decimal("99999.00"))
    assert summary.total_ticks_processed == 1
    assert summary.orders_generated == 1
    assert summary.orders_filled == 1
    assert summary.final_equity == Decimal("99999.00")

    # Verify journal stored summary
    stored = engine.journal.get_summary(summary.validation_id)
    assert stored is not None
    assert stored.validation_id == summary.validation_id
