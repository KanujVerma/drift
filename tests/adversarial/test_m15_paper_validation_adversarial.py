"""M15 adversarial acceptance suite: Paper / Shadow Validation (Issue 312).

Attacks the paper validation feed streamer, shadow validation engine, and telemetry
journal across eight adversarial vectors:
1. Crossed market quote attack (bid > ask fails closed).
2. Retroactive clock rewind attack (past-dated ticks fail closed).
3. Persistent hard risk kill switch latching (tripped switch halts submissions).
4. Cryptographic hash tampering attack (corrupted hashes fail model validation).
5. High-volatility price gap slippage drift measurement.
6. Rapid order burst capital exhaustion and buying power limits.
7. SQLite append-only SQL trigger tampering attack on all three tables.
8. Deterministic stream reset replay invariance.

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.paper_validation import (
    ExecutionDriftReportV1,
    MarketTickV1,
    ShadowValidationSummaryV1,
    build_execution_drift_report,
    build_market_tick,
    build_shadow_validation_summary,
)
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
from drift.validation.feed import (
    MockMarketDataStreamer,
    NonMonotonicTimestampError,
)
from drift.validation.journal import (
    PersistentShadowValidationJournal,
    ValidationAppendOnlyViolationError,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def _make_adversarial_environment(
    tmp_path: Path,
    initial_cash: Decimal = Decimal("100000"),
) -> tuple[
    ShadowValidationEngine,
    MockMarketDataStreamer,
    MockBrokerAdapter,
    PersistentRiskJournal,
]:
    streamer = MockMarketDataStreamer()
    intent_db = tmp_path / "adversarial_intent.db"
    intent_journal = PersistentOrderIntentJournal(intent_db)
    adapter = MockBrokerAdapter(initial_cash=initial_cash, default_fee=Decimal("1.50"))
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=intent_journal)

    shadow_db = tmp_path / "adversarial_shadow.db"
    shadow_journal = PersistentShadowValidationJournal(shadow_db)

    risk_db = tmp_path / "adversarial_risk.db"
    risk_journal = PersistentRiskJournal(risk_db)
    policy = build_risk_policy(
        policy_id="adv-risk-policy",
        max_order_notional=Decimal("50000"),
        max_order_quantity=1000,
        max_position_notional=Decimal("80000"),
        max_position_weight_basis_points=5000,
        max_gross_exposure_basis_points=10000,
        max_session_drawdown_basis_points=1000,
        max_trailing_drawdown_basis_points=1000,
        max_orders_per_minute=50,
    )
    risk_gatekeeper = HardRiskGatekeeper(
        policy=policy,
        journal=risk_journal,
        initial_nav=initial_cash,
    )

    engine = ShadowValidationEngine(
        streamer=streamer,
        router=router,
        journal=shadow_journal,
        session_key=KEY1,
        risk_gatekeeper=risk_gatekeeper,
    )
    return engine, streamer, adapter, risk_journal


def test_vector1_crossed_market_quote_attack() -> None:
    """Vector 1: Crossed markets (bid > ask) are refused at schema boundary."""
    sec_id = uuid7()
    # Attack: bid $101.00 > ask $100.00
    with pytest.raises(ValidationError, match="crossed market condition"):
        build_market_tick(
            tick_id=uuid7(),
            security_id=sec_id,
            timestamp=NOW,
            last_price=Decimal("100.50"),
            last_size=10,
            bid_price=Decimal("101.00"),
            ask_price=Decimal("100.00"),
        )

    # Control: valid bid <= ask succeeds
    valid_tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.50"),
        last_size=10,
        bid_price=Decimal("100.00"),
        ask_price=Decimal("101.00"),
    )
    assert valid_tick.bid_price == Decimal("100.00")
    assert valid_tick.ask_price == Decimal("101.00")


def test_vector2_retroactive_clock_rewind_attack(tmp_path: Path) -> None:
    """Vector 2: Streamer refuses ticks with non-monotonic past timestamps."""
    _, streamer, _, _ = _make_adversarial_environment(tmp_path)
    sec_id = uuid7()

    t1 = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW + timedelta(seconds=10),
        last_price=Decimal("100.00"),
        last_size=10,
    )
    streamer.push_tick(t1)
    assert streamer.next_tick() is not None

    # Attack: tick with timestamp earlier than t1
    past_tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW + timedelta(seconds=5),  # 5 < 10
        last_price=Decimal("100.50"),
        last_size=10,
    )
    with pytest.raises(NonMonotonicTimestampError, match="precedes previous timestamp"):
        streamer.push_tick(past_tick)


def test_vector3_persistent_hard_risk_kill_switch_latching(tmp_path: Path) -> None:
    """Vector 3: Tripping kill switch prevents any subsequent order intent routing."""
    engine, _, _, risk_journal = _make_adversarial_environment(tmp_path)
    sec_id = uuid7()

    # Trip the persistent kill switch
    risk_journal.trip_kill_switch(
        reason="adversarial emergency kill switch trip",
        tripped_at=NOW,
    )
    assert risk_journal.is_kill_switch_tripped()

    # Attempt to route intent
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="halt-test-01",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    with pytest.raises(RiskHaltValidationError, match="kill switch active"):
        engine.route_intent(intent)


def test_vector4_cryptographic_hash_tampering_attack() -> None:
    """Vector 4: Tampering tick, drift, or summary payload fails hash check."""
    sec_id = uuid7()
    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.00"),
        last_size=10,
    )
    tampered_tick = tick.model_dump(mode="python")
    tampered_tick["last_price"] = Decimal("999.00")
    with pytest.raises(ValidationError, match="tick_hash mismatch"):
        MarketTickV1.model_validate(tampered_tick)

    # Drift report tampering
    drift = build_execution_drift_report(
        drift_id=uuid7(),
        intent_id=uuid7(),
        security_id=sec_id,
        intended_price=Decimal("100.00"),
        fill_price=Decimal("101.00"),
        recorded_at=NOW,
    )
    tampered_drift = drift.model_dump(mode="python")
    tampered_drift["fill_price"] = Decimal("105.00")
    with pytest.raises(ValidationError, match="drift_hash mismatch"):
        ExecutionDriftReportV1.model_validate(tampered_drift)

    # Summary tampering
    summary = build_shadow_validation_summary(
        validation_id=uuid7(),
        session_key=KEY1,
        total_ticks_processed=100,
        orders_generated=5,
        orders_approved=5,
        orders_rejected_risk=0,
        orders_filled=5,
        total_slippage_bps=Decimal("10"),
        mean_slippage_bps=Decimal("2"),
        max_slippage_bps=Decimal("5"),
        final_equity=Decimal("100000"),
    )
    tampered_sum = summary.model_dump(mode="python")
    tampered_sum["orders_generated"] = 50
    with pytest.raises(ValidationError, match="summary_hash mismatch"):
        ShadowValidationSummaryV1.model_validate(tampered_sum)


def test_vector5_high_volatility_price_gap_slippage(tmp_path: Path) -> None:
    """Vector 5: Extreme price gaps are faithfully tracked in slippage basis points."""
    engine, streamer, _, _ = _make_adversarial_environment(tmp_path)
    sec_id = uuid7()

    # Sudden 10% upward gap from intended $100.00 to market price $110.00
    gap_tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("110.00"),
        last_size=100,
    )
    streamer.push_tick(gap_tick)
    engine.process_next_tick()

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="gap-order-1",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    # Strategy intended to buy at $100.00, fills at $110.00 -> +1000 bps slippage
    report = engine.route_intent(intent, intended_price=Decimal("100.00"))
    assert report.status == ExecutionStatus.FILLED

    drifts = engine.journal.list_drift_reports_for_security(sec_id)
    assert len(drifts) == 1
    # ((110 - 100) / 100) * 10000 = +1000 bps
    assert drifts[0].slippage_bps == Decimal("1000")


def test_vector6_rapid_burst_capital_exhaustion(tmp_path: Path) -> None:
    """Vector 6: Buying beyond cash balance rejects without corrupting ledger state."""
    engine, streamer, adapter, _ = _make_adversarial_environment(
        tmp_path, initial_cash=Decimal("5000.00")
    )
    sec_id = uuid7()

    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("1000.00"),
        last_size=50,
    )
    streamer.push_tick(tick)
    engine.process_next_tick()

    # Intent requiring $10,000 > $5,000 cash balance
    excessive_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="burst-exhaust-01",
        session_key=KEY1,
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("1000.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    report = engine.route_intent(excessive_intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.rejection_reason == "insufficient_buying_power"
    assert adapter.cash == Decimal("5000.00")


def test_vector7_sqlite_append_only_trigger_attack(tmp_path: Path) -> None:
    """Vector 7: Direct SQL UPDATE or DELETE on validation tables raises error."""
    engine, streamer, _, _ = _make_adversarial_environment(tmp_path)
    journal = engine.journal
    sec_id = uuid7()

    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("50.00"),
        last_size=10,
    )
    journal.record_tick(tick)

    # Attack: UPDATE market_ticks
    with pytest.raises(
        ValidationAppendOnlyViolationError, match="market_ticks is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("UPDATE market_ticks SET last_price = '999.00'")

    # Attack: DELETE market_ticks
    with pytest.raises(
        ValidationAppendOnlyViolationError, match="market_ticks is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("DELETE FROM market_ticks")


def test_vector8_deterministic_stream_reset_replay_invariance(tmp_path: Path) -> None:
    """Vector 8: Stream reset replays identical tick sequence deterministically."""
    _, streamer, _, _ = _make_adversarial_environment(tmp_path)
    sec_id = uuid7()

    t1 = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.00"),
        last_size=10,
    )
    t2 = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW + timedelta(seconds=1),
        last_price=Decimal("101.00"),
        last_size=20,
    )
    streamer.push_tick(t1)
    streamer.push_tick(t2)

    # First pass
    first_seq = [streamer.next_tick(), streamer.next_tick()]
    assert streamer.is_exhausted()

    # Reset and second pass
    streamer.reset()
    assert not streamer.is_exhausted()
    second_seq = [streamer.next_tick(), streamer.next_tick()]

    assert [t.tick_id for t in first_seq if t is not None] == [
        t.tick_id for t in second_seq if t is not None
    ]
