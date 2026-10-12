"""M18 adversarial acceptance suite: Bounded Autonomy and Improvement (Issue 346).

Attacks the bounded autonomy governor, orchestrator, and evidence ledger
across eight adversarial vectors:
1. Premature tier elevation attack (insufficient session count rejected).
2. Statistical degradation demotion attack (degraded DSR or high PBO demotes tier).
3. Execution drift spike demotion attack (excessive drift triggers demotion).
4. Emergency kill switch immediate freeze attack (freezes tier to Tier 0 Canary).
5. Hard risk position limit breach demotion attack (risk halts step down tiers).
6. Audit ledger append-only trigger tampering attack (SQL updates/deletes aborted).
7. Cryptographic hash chain corruption attack (invalid hashes fail validation).
8. Idempotent re-evaluation and max tier saturation attack (capped at Tier 3 limits).

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously. Strictly zero Unicode em dashes.
"""

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.autonomy.governor import AllocationExpansionGovernor
from drift.autonomy.ledger import (
    GovernanceAppendOnlyViolationError,
    GovernanceChainIntegrityError,
    PersistentEvidenceLedger,
)
from drift.autonomy.orchestrator import BoundedAutonomyOrchestrator
from drift.domain.autonomy import (
    AUTONOMY_SCHEMA_VERSION,
    AutonomyTier,
    GovernanceTransitionType,
    GovernanceTransitionV1,
    build_governance_transition,
    compute_governance_transition_hash,
)
from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.risk import build_risk_policy
from drift.domain.sessions import SessionKeyV1
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal


def _make_session_key() -> SessionKeyV1:
    return SessionKeyV1(
        mic="XNYS",
        session_scope="regular",
        local_date=date(2026, 3, 1),
    )


def test_v1_premature_tier_elevation_attack(tmp_path: Path) -> None:
    """Vector 1: Premature tier elevation is refused when session count is immature."""
    db_path = tmp_path / "v1_gov.db"
    ledger = PersistentEvidenceLedger(db_path=db_path)
    governor = AllocationExpansionGovernor(
        ledger=ledger,
        initial_tier=AutonomyTier.TIER_0_CANARY,
        min_sessions_per_tier=5,
        min_deflated_sharpe=Decimal("1.0"),
        max_pbo=Decimal("0.20"),
    )

    # Record only 2 clean sessions (threshold is 5)
    governor.record_clean_session()
    governor.record_clean_session()
    assert governor.clean_sessions_at_current_tier == 2

    # Attack: Submit stellar scorecard attempting to force premature elevation
    stellar_scorecard = {
        "deflated_sharpe_ratio": "2.5",
        "pbo": "0.05",
    }
    transition = governor.evaluate_evidence(stellar_scorecard)

    # Attack assertion: Governor refuses promotion; remains HOLD at TIER_0_CANARY
    assert transition.transition_type == GovernanceTransitionType.HOLD
    assert transition.previous_tier == AutonomyTier.TIER_0_CANARY
    assert transition.target_tier == AutonomyTier.TIER_0_CANARY
    assert "insufficient_sessions: 2/5" in transition.trigger_reason
    assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY

    # Control: After satisfying required 5 clean sessions, promotion succeeds
    for _ in range(3):
        governor.record_clean_session()
    assert governor.clean_sessions_at_current_tier == 5

    ctrl_transition = governor.evaluate_evidence(stellar_scorecard)
    assert ctrl_transition.transition_type == GovernanceTransitionType.PROMOTION
    assert ctrl_transition.previous_tier == AutonomyTier.TIER_0_CANARY
    assert ctrl_transition.target_tier == AutonomyTier.TIER_1_MICRO
    assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO
    assert governor.clean_sessions_at_current_tier == 0

    ledger.close()


def test_v2_statistical_degradation_demotion_attack(tmp_path: Path) -> None:
    """Vector 2: Degraded statistical metrics immediately trigger tier demotion."""
    db_path = tmp_path / "v2_gov.db"
    ledger = PersistentEvidenceLedger(db_path=db_path)
    governor = AllocationExpansionGovernor(
        ledger=ledger,
        initial_tier=AutonomyTier.TIER_2_SMALL,
        min_sessions_per_tier=5,
        min_deflated_sharpe=Decimal("1.0"),
        max_pbo=Decimal("0.20"),
    )

    for _ in range(10):
        governor.record_clean_session()

    # Attack: Scorecard with degraded DSR (0.4 < 1.0) and degraded PBO (0.35 > 0.20)
    degraded_scorecard = {
        "deflated_sharpe_ratio": "0.4",
        "pbo": "0.35",
    }
    transition = governor.evaluate_evidence(degraded_scorecard)

    # Attack assertion: Demoted from TIER_2_SMALL down to TIER_1_MICRO
    assert transition.transition_type == GovernanceTransitionType.DEMOTION
    assert transition.previous_tier == AutonomyTier.TIER_2_SMALL
    assert transition.target_tier == AutonomyTier.TIER_1_MICRO
    assert "statistical_degradation" in transition.trigger_reason
    assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO
    assert governor.clean_sessions_at_current_tier == 0

    # Repeat attack at TIER_1_MICRO: Demoted down to TIER_0_CANARY
    transition_2 = governor.evaluate_evidence(degraded_scorecard)
    assert transition_2.transition_type == GovernanceTransitionType.DEMOTION
    assert transition_2.previous_tier == AutonomyTier.TIER_1_MICRO
    assert transition_2.target_tier == AutonomyTier.TIER_0_CANARY
    assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY

    # Control: Healthy metrics hold at TIER_0_CANARY until session threshold met
    healthy_scorecard = {
        "deflated_sharpe_ratio": "1.5",
        "pbo": "0.10",
    }
    ctrl_transition = governor.evaluate_evidence(healthy_scorecard)
    assert ctrl_transition.transition_type == GovernanceTransitionType.HOLD
    assert ctrl_transition.target_tier == AutonomyTier.TIER_0_CANARY

    ledger.close()


def test_v3_execution_drift_spike_demotion_attack(tmp_path: Path) -> None:
    """Vector 3: Execution drift spike beyond threshold triggers demotion."""
    db_path = tmp_path / "v3_gov.db"
    ledger = PersistentEvidenceLedger(db_path=db_path)
    governor = AllocationExpansionGovernor(
        ledger=ledger,
        initial_tier=AutonomyTier.TIER_1_MICRO,
        max_drift_multiplier=Decimal("1.5"),
    )

    scorecard = {
        "deflated_sharpe_ratio": "1.8",
        "pbo": "0.08",
    }

    # Attack: Execution drift multiplier 2.2 exceeds threshold 1.5
    transition = governor.evaluate_evidence(
        scorecard=scorecard,
        drift_multiplier=Decimal("2.2"),
    )

    # Attack assertion: Demoted from TIER_1_MICRO to TIER_0_CANARY
    assert transition.transition_type == GovernanceTransitionType.DEMOTION
    assert transition.previous_tier == AutonomyTier.TIER_1_MICRO
    assert transition.target_tier == AutonomyTier.TIER_0_CANARY
    assert "excessive_execution_drift" in transition.trigger_reason
    assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY

    # Control: Normal drift within threshold (1.1 <= 1.5) does not demote
    ctrl_transition = governor.evaluate_evidence(
        scorecard=scorecard,
        drift_multiplier=Decimal("1.1"),
    )
    assert ctrl_transition.transition_type == GovernanceTransitionType.HOLD
    assert ctrl_transition.target_tier == AutonomyTier.TIER_0_CANARY

    ledger.close()


def test_v4_emergency_kill_switch_immediate_freeze_attack(tmp_path: Path) -> None:
    """Vector 4: Tripped kill switch halts order and freezes tier to Tier 0 Canary."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "v4_gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_3_BOUNDED,
    )
    assert governor.get_current_tier() == AutonomyTier.TIER_3_BOUNDED

    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("1000.00"),
        price_map={"AAPL": Decimal("50.00")},
    )
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-v4", symbol_map=symbol_map),
        transport=transport,
    )
    intent_journal = PersistentOrderIntentJournal(db_path=tmp_path / "v4_intent.db")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=intent_journal)

    risk_journal = PersistentRiskJournal(db_path=tmp_path / "v4_risk.db")
    risk_policy = build_risk_policy(
        policy_id="v4-risk-pol",
        max_order_notional=Decimal("1000.00"),
        max_order_quantity=50,
        max_position_notional=Decimal("5000.00"),
        max_position_weight_basis_points=2000,
        max_gross_exposure_basis_points=5000,
        max_session_drawdown_basis_points=500,
        max_trailing_drawdown_basis_points=500,
        max_orders_per_minute=20,
    )
    risk_gatekeeper = HardRiskGatekeeper(policy=risk_policy, journal=risk_journal)

    orchestrator = BoundedAutonomyOrchestrator(
        governor=governor,
        router=router,
        risk_gatekeeper=risk_gatekeeper,
    )

    # Attack: Trip emergency kill switch
    risk_journal.trip_kill_switch(
        reason="extreme tail risk drawdown breach",
        tripped_at=datetime.now(UTC),
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-kill-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    # Order submission is immediately rejected
    exec_report = orchestrator.submit_autonomous_intent(intent)
    assert exec_report.status == ExecutionStatus.REJECTED
    assert exec_report.rejection_reason == "emergency_kill_switch_active"

    # Attack assertion: Governor immediately froze allocation directly to TIER_0_CANARY
    assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY
    latest_trans = gov_ledger.get_latest_transition()
    assert latest_trans is not None
    assert latest_trans.transition_type == GovernanceTransitionType.EMERGENCY_HALT
    assert latest_trans.target_tier == AutonomyTier.TIER_0_CANARY
    assert "emergency_kill_switch_trip" in latest_trans.trigger_reason

    # Control: Untripped risk gatekeeper routes order without freeze
    gov_ledger2 = PersistentEvidenceLedger(db_path=tmp_path / "v4_ctrl_gov.db")
    governor2 = AllocationExpansionGovernor(
        ledger=gov_ledger2,
        initial_tier=AutonomyTier.TIER_1_MICRO,
    )
    risk_journal2 = PersistentRiskJournal(db_path=tmp_path / "v4_ctrl_risk.db")
    risk_gatekeeper2 = HardRiskGatekeeper(policy=risk_policy, journal=risk_journal2)
    orchestrator2 = BoundedAutonomyOrchestrator(
        governor=governor2,
        router=router,
        risk_gatekeeper=risk_gatekeeper2,
    )

    ctrl_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="ctrl-kill-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("20.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    ctrl_report = orchestrator2.submit_autonomous_intent(ctrl_intent)
    assert ctrl_report.status == ExecutionStatus.FILLED
    assert governor2.get_current_tier() == AutonomyTier.TIER_1_MICRO

    gov_ledger.close()
    gov_ledger2.close()
    risk_journal.close()
    risk_journal2.close()


def test_v5_hard_risk_position_limit_breach_demotion_attack(tmp_path: Path) -> None:
    """Vector 5: Hard risk halts step down allocation tiers progressively."""
    db_path = tmp_path / "v5_gov.db"
    ledger = PersistentEvidenceLedger(db_path=db_path)
    governor = AllocationExpansionGovernor(
        ledger=ledger,
        initial_tier=AutonomyTier.TIER_2_SMALL,
    )

    # Attack 1: Risk halt at TIER_2_SMALL demotes to TIER_1_MICRO
    t1 = governor.record_risk_halt("position limit breach")
    assert t1.transition_type == GovernanceTransitionType.DEMOTION
    assert t1.previous_tier == AutonomyTier.TIER_2_SMALL
    assert t1.target_tier == AutonomyTier.TIER_1_MICRO
    assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO

    # Attack 2: Subsequent risk halt demotes to TIER_0_CANARY
    t2 = governor.record_risk_halt("secondary risk halt")
    assert t2.transition_type == GovernanceTransitionType.DEMOTION
    assert t2.previous_tier == AutonomyTier.TIER_1_MICRO
    assert t2.target_tier == AutonomyTier.TIER_0_CANARY
    assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY

    # Attack 3: Risk halt at TIER_0_CANARY freezes at TIER_0_CANARY without underflow
    t3 = governor.record_risk_halt("canary floor breach")
    assert t3.transition_type == GovernanceTransitionType.EMERGENCY_HALT
    assert t3.previous_tier == AutonomyTier.TIER_0_CANARY
    assert t3.target_tier == AutonomyTier.TIER_0_CANARY
    assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY

    # Control: Clean sessions increment normally
    governor.record_clean_session()
    assert governor.clean_sessions_at_current_tier == 1

    ledger.close()


def test_v6_audit_ledger_append_only_trigger_tampering_attack(tmp_path: Path) -> None:
    """Vector 6: SQL UPDATE and DELETE on evidence ledger are aborted by triggers."""
    db_path = tmp_path / "v6_gov.db"
    ledger = PersistentEvidenceLedger(db_path=db_path)

    # Seed an event
    ev_id = uuid7()
    trans = build_governance_transition(
        event_id=ev_id,
        previous_tier=AutonomyTier.TIER_0_CANARY,
        target_tier=AutonomyTier.TIER_1_MICRO,
        transition_type=GovernanceTransitionType.PROMOTION,
        trigger_reason="promoted via evidence",
        evaluated_at=datetime.now(UTC),
    )
    ledger.record_transition(trans)

    # Direct database connection attack
    raw_conn = sqlite3.connect(db_path)

    # Attack 1: Attempt raw SQL UPDATE to alter target tier
    with pytest.raises(
        (sqlite3.DatabaseError, GovernanceAppendOnlyViolationError)
    ) as exc_update:
        raw_conn.execute(
            "UPDATE governance_transitions SET target_tier = ? WHERE event_id = ?",
            (AutonomyTier.TIER_3_BOUNDED.value, str(ev_id)),
        )
    assert "append-only: no updates" in str(exc_update.value)

    # Attack 2: Attempt raw SQL DELETE to purge audit records
    with pytest.raises(
        (sqlite3.DatabaseError, GovernanceAppendOnlyViolationError)
    ) as exc_delete:
        raw_conn.execute(
            "DELETE FROM governance_transitions WHERE event_id = ?",
            (str(ev_id),),
        )
    assert "append-only: no deletes" in str(exc_delete.value)

    raw_conn.close()

    # Control: Append-only insert of legitimate transition succeeds
    ev_id2 = uuid7()
    trans2 = build_governance_transition(
        event_id=ev_id2,
        previous_tier=AutonomyTier.TIER_1_MICRO,
        target_tier=AutonomyTier.TIER_1_MICRO,
        transition_type=GovernanceTransitionType.HOLD,
        trigger_reason="evidence hold",
        previous_chain_hash=trans.chain_hash,
        evaluated_at=datetime.now(UTC),
    )
    ledger.record_transition(trans2)
    assert len(ledger.get_all_transitions()) == 2

    ledger.close()


def test_v7_cryptographic_hash_chain_corruption_attack(tmp_path: Path) -> None:
    """Vector 7: Tampered or mismatched chain hashes are detected and refused."""
    db_path = tmp_path / "v7_gov.db"
    ledger = PersistentEvidenceLedger(db_path=db_path)

    now = datetime.now(UTC)
    ev_id = uuid7()
    valid_hash = compute_governance_transition_hash(
        schema_version=AUTONOMY_SCHEMA_VERSION,
        event_id=ev_id,
        previous_tier=AutonomyTier.TIER_0_CANARY.value,
        target_tier=AutonomyTier.TIER_1_MICRO.value,
        transition_type=GovernanceTransitionType.PROMOTION.value,
        trigger_reason="valid promotion",
        scorecard_summary={},
        previous_chain_hash=None,
        evaluated_at=now,
    )
    assert len(valid_hash) == 64

    # Attack 1: Corrupted hash in domain model constructor fails validation
    tampered_hash = "f" * 64
    with pytest.raises(ValueError, match="chain_hash mismatch"):
        GovernanceTransitionV1(
            schema_version=AUTONOMY_SCHEMA_VERSION,
            event_id=ev_id,
            previous_tier=AutonomyTier.TIER_0_CANARY,
            target_tier=AutonomyTier.TIER_1_MICRO,
            transition_type=GovernanceTransitionType.PROMOTION,
            trigger_reason="valid promotion",
            scorecard_summary={},
            previous_chain_hash=None,
            chain_hash=tampered_hash,
            evaluated_at=now,
        )

    # Append valid initial transition
    trans1 = build_governance_transition(
        event_id=ev_id,
        previous_tier=AutonomyTier.TIER_0_CANARY,
        target_tier=AutonomyTier.TIER_1_MICRO,
        transition_type=GovernanceTransitionType.PROMOTION,
        trigger_reason="valid promotion",
        evaluated_at=now,
    )
    ledger.record_transition(trans1)

    # Attack 2: Second transition with mismatched previous_chain_hash fails ledger check
    trans2_corrupted = build_governance_transition(
        event_id=uuid7(),
        previous_tier=AutonomyTier.TIER_1_MICRO,
        target_tier=AutonomyTier.TIER_2_SMALL,
        transition_type=GovernanceTransitionType.PROMOTION,
        trigger_reason="forged chain link",
        previous_chain_hash="0" * 64,  # Does not match trans1.chain_hash
        evaluated_at=datetime.now(UTC),
    )
    with pytest.raises(
        GovernanceChainIntegrityError, match="previous_chain_hash mismatch"
    ):
        ledger.record_transition(trans2_corrupted)

    # Control: Valid hash chaining succeeds and integrity verification passes
    trans2_valid = build_governance_transition(
        event_id=uuid7(),
        previous_tier=AutonomyTier.TIER_1_MICRO,
        target_tier=AutonomyTier.TIER_2_SMALL,
        transition_type=GovernanceTransitionType.PROMOTION,
        trigger_reason="legitimate chain link",
        previous_chain_hash=trans1.chain_hash,
        evaluated_at=datetime.now(UTC),
    )
    ledger.record_transition(trans2_valid)
    assert ledger.verify_chain_integrity() is True

    ledger.close()


def test_v8_idempotent_re_evaluation_and_max_tier_saturation_attack(
    tmp_path: Path,
) -> None:
    """Vector 8: Maximum tier saturation remains bounded and enforces hard caps."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "v8_gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_3_BOUNDED,
        min_sessions_per_tier=5,
    )
    for _ in range(10):
        governor.record_clean_session()

    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("5000.00"),
        price_map={"AAPL": Decimal("10.00")},
    )
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-v8", symbol_map=symbol_map),
        transport=transport,
    )
    intent_journal = PersistentOrderIntentJournal(db_path=tmp_path / "v8_intent.db")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=intent_journal)
    orchestrator = BoundedAutonomyOrchestrator(governor=governor, router=router)

    # Attack 1: Re-evaluating stellar scorecard cannot elevate past Tier 3
    scorecard = {
        "deflated_sharpe_ratio": "3.0",
        "pbo": "0.01",
    }
    transition = orchestrator.review_evidence_and_update_tier(scorecard)
    assert transition.transition_type == GovernanceTransitionType.HOLD
    assert transition.previous_tier == AutonomyTier.TIER_3_BOUNDED
    assert transition.target_tier == AutonomyTier.TIER_3_BOUNDED
    assert transition.trigger_reason == "at_maximum_tier_bounded_operating"
    assert governor.get_current_tier() == AutonomyTier.TIER_3_BOUNDED

    # Attack 2: Order exceeding Tier 3 caps (quantity 100 > 50 max_order_quantity)
    intent_qty_breach = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-max-qty",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=100,  # Tier 3 limit is 50
        order_type=OrderType.LIMIT,
        limit_price=Decimal("10.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    rep_qty = orchestrator.submit_autonomous_intent(intent_qty_breach)
    assert rep_qty.status == ExecutionStatus.REJECTED
    assert "tier_quantity_limit_exceeded" in (rep_qty.rejection_reason or "")

    # Attack 3: Order exceeding Tier 3 notional ($600.00 > $500.00 max_order_notional)
    intent_notional_breach = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-max-notional",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=30,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("20.00"),  # 30 * 20 = $600 > $500 max
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    rep_notional = orchestrator.submit_autonomous_intent(intent_notional_breach)
    assert rep_notional.status == ExecutionStatus.REJECTED
    assert "tier_notional_limit_exceeded" in (rep_notional.rejection_reason or "")

    # Control: Valid order within Tier 3 caps is routed and filled
    ctrl_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="ctrl-tier3-valid",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=40,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("10.00"),  # 40 * 10 = $400 <= $500 max
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    rep_ctrl = orchestrator.submit_autonomous_intent(ctrl_intent)
    assert rep_ctrl.status == ExecutionStatus.FILLED

    gov_ledger.close()
