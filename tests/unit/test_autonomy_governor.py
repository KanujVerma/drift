"""Unit tests for Dynamic Allocation Expansion Governor (M18-3)."""

from decimal import Decimal
from pathlib import Path

from drift.autonomy.governor import AllocationExpansionGovernor
from drift.autonomy.ledger import PersistentEvidenceLedger
from drift.domain.autonomy import AutonomyTier, GovernanceTransitionType


def test_governor_initial_state(tmp_path: Path) -> None:
    """Governor starts at canary tier with zero sessions."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        governor = AllocationExpansionGovernor(
            ledger=ledger,
            initial_tier=AutonomyTier.TIER_0_CANARY,
            min_sessions_per_tier=5,
        )
        assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY
        assert governor.clean_sessions_at_current_tier == 0
        limits = governor.get_active_limits()
        assert limits.max_order_notional == Decimal("5.00")
        assert limits.max_cumulative_notional == Decimal("25.00")
    finally:
        ledger.close()


def test_governor_insufficient_sessions_hold(tmp_path: Path) -> None:
    """Valid scorecard without enough sessions yields HOLD transition."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        governor = AllocationExpansionGovernor(
            ledger=ledger,
            min_sessions_per_tier=5,
        )
        # Record only 2 sessions
        governor.record_clean_session()
        governor.record_clean_session()

        scorecard = {"deflated_sharpe_ratio": "1.5", "pbo": "0.10"}
        t = governor.evaluate_evidence(scorecard=scorecard)

        assert t.transition_type == GovernanceTransitionType.HOLD
        assert t.target_tier == AutonomyTier.TIER_0_CANARY
        assert "insufficient_sessions" in t.trigger_reason
        assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY
    finally:
        ledger.close()


def test_governor_evidence_promotion_flow(tmp_path: Path) -> None:
    """Completing minimum clean sessions with passing metrics promotes tier."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        governor = AllocationExpansionGovernor(
            ledger=ledger,
            min_sessions_per_tier=3,
        )
        for _ in range(3):
            governor.record_clean_session()

        scorecard = {"deflated_sharpe_ratio": "1.8", "pbo": "0.08"}
        t = governor.evaluate_evidence(scorecard=scorecard)

        assert t.transition_type == GovernanceTransitionType.PROMOTION
        assert t.previous_tier == AutonomyTier.TIER_0_CANARY
        assert t.target_tier == AutonomyTier.TIER_1_MICRO
        assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO

        # New limits active
        limits = governor.get_active_limits()
        assert limits.max_order_notional == Decimal("25.00")
        assert limits.max_cumulative_notional == Decimal("100.00")
    finally:
        ledger.close()


def test_governor_statistical_degradation_demotion(tmp_path: Path) -> None:
    """Degraded statistical metrics demote allocation tier."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        # Start at Tier 1 Micro
        governor = AllocationExpansionGovernor(
            ledger=ledger,
            initial_tier=AutonomyTier.TIER_1_MICRO,
            min_deflated_sharpe=Decimal("1.0"),
            max_pbo=Decimal("0.20"),
        )
        assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO

        # Degraded scorecard (DSR 0.4 < 1.0)
        bad_scorecard = {"deflated_sharpe_ratio": "0.4", "pbo": "0.30"}
        t = governor.evaluate_evidence(scorecard=bad_scorecard)

        assert t.transition_type == GovernanceTransitionType.DEMOTION
        assert t.previous_tier == AutonomyTier.TIER_1_MICRO
        assert t.target_tier == AutonomyTier.TIER_0_CANARY
        assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY
    finally:
        ledger.close()


def test_governor_execution_drift_demotion(tmp_path: Path) -> None:
    """Excessive execution drift triggers tier contraction."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        governor = AllocationExpansionGovernor(
            ledger=ledger,
            initial_tier=AutonomyTier.TIER_2_SMALL,
            max_drift_multiplier=Decimal("1.5"),
        )
        assert governor.get_current_tier() == AutonomyTier.TIER_2_SMALL

        good_scorecard = {"deflated_sharpe_ratio": "1.5", "pbo": "0.10"}
        # Severe drift 2.5x > 1.5x
        t = governor.evaluate_evidence(
            scorecard=good_scorecard,
            drift_multiplier=Decimal("2.5"),
        )

        assert t.transition_type == GovernanceTransitionType.DEMOTION
        assert t.target_tier == AutonomyTier.TIER_1_MICRO
        assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO
    finally:
        ledger.close()


def test_governor_kill_switch_trip_freeze(tmp_path: Path) -> None:
    """Emergency kill switch immediately collapses tier to Canary."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        governor = AllocationExpansionGovernor(
            ledger=ledger,
            initial_tier=AutonomyTier.TIER_3_BOUNDED,
        )
        assert governor.get_current_tier() == AutonomyTier.TIER_3_BOUNDED

        t = governor.record_kill_switch_trip(reason="circuit breaker tripped")
        assert t.transition_type == GovernanceTransitionType.EMERGENCY_HALT
        assert t.target_tier == AutonomyTier.TIER_0_CANARY
        assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY
    finally:
        ledger.close()
