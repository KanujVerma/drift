"""Dynamic Allocation Expansion Governor for evidence-gated autonomy (M18-3).

Manages progressive capital allocation tiers, enforces empirical promotion gates,
and triggers fail-closed contraction upon statistical degradation or risk halts
per ADR 0011, ADR 0013, and ADR 0014.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid7

from drift.autonomy.ledger import PersistentEvidenceLedger
from drift.domain.autonomy import (
    TIER_LIMITS,
    AutonomyTier,
    GovernanceTransitionType,
    GovernanceTransitionV1,
    TierAllocationLimitsV1,
    build_governance_transition,
)

__all__ = [
    "AllocationExpansionGovernor",
]

_TIER_SEQUENCE: tuple[AutonomyTier, ...] = (
    AutonomyTier.TIER_0_CANARY,
    AutonomyTier.TIER_1_MICRO,
    AutonomyTier.TIER_2_SMALL,
    AutonomyTier.TIER_3_BOUNDED,
)


class AllocationExpansionGovernor:
    """Governor managing evidence-gated allocation tier promotion and contraction."""

    def __init__(
        self,
        *,
        ledger: PersistentEvidenceLedger,
        initial_tier: AutonomyTier = AutonomyTier.TIER_0_CANARY,
        min_sessions_per_tier: int = 5,
        min_deflated_sharpe: Decimal = Decimal("1.0"),
        max_pbo: Decimal = Decimal("0.20"),
        max_drift_multiplier: Decimal = Decimal("1.5"),
    ) -> None:
        self._ledger = ledger
        self._initial_tier = initial_tier
        self._min_sessions = min_sessions_per_tier
        self._min_dsr = min_deflated_sharpe
        self._max_pbo = max_pbo
        self._max_drift = max_drift_multiplier
        self._clean_sessions = 0

    @property
    def clean_sessions_at_current_tier(self) -> int:
        """Number of clean trading sessions completed at current tier."""
        return self._clean_sessions

    def get_current_tier(self) -> AutonomyTier:
        """Determine active tier from latest ledger record or initial default."""
        latest = self._ledger.get_latest_transition()
        if latest is not None:
            return latest.target_tier
        return self._initial_tier

    def get_active_limits(self) -> TierAllocationLimitsV1:
        """Return allocation caps for current active tier."""
        return TIER_LIMITS[self.get_current_tier()]

    def record_clean_session(self) -> None:
        """Record completion of a clean, halt-free trading session."""
        self._clean_sessions += 1

    def record_kill_switch_trip(
        self,
        reason: str,
        scorecard: Mapping[str, Any] | None = None,
    ) -> GovernanceTransitionV1:
        """Immediately contract to Tier 0 Canary on emergency kill switch trip."""
        current_tier = self.get_current_tier()
        now = datetime.now(UTC)
        self._clean_sessions = 0
        latest_hash = self._ledger.get_latest_chain_hash()

        transition = build_governance_transition(
            event_id=uuid7(),
            previous_tier=current_tier,
            target_tier=AutonomyTier.TIER_0_CANARY,
            transition_type=GovernanceTransitionType.EMERGENCY_HALT,
            trigger_reason=f"emergency_kill_switch_trip: {reason}",
            scorecard_summary=scorecard or {},
            previous_chain_hash=latest_hash,
            evaluated_at=now,
        )
        self._ledger.record_transition(transition)
        return transition

    def record_risk_halt(
        self,
        reason: str,
        scorecard: Mapping[str, Any] | None = None,
    ) -> GovernanceTransitionV1:
        """Demote allocation tier upon hard risk limit halt."""
        current_tier = self.get_current_tier()
        idx = _TIER_SEQUENCE.index(current_tier)
        now = datetime.now(UTC)
        self._clean_sessions = 0
        latest_hash = self._ledger.get_latest_chain_hash()

        if idx > 0:
            target_tier = _TIER_SEQUENCE[idx - 1]
            t_type = GovernanceTransitionType.DEMOTION
            trig_msg = f"risk_halt_demotion: {reason}"
        else:
            target_tier = AutonomyTier.TIER_0_CANARY
            t_type = GovernanceTransitionType.EMERGENCY_HALT
            trig_msg = f"risk_halt_canary_freeze: {reason}"

        transition = build_governance_transition(
            event_id=uuid7(),
            previous_tier=current_tier,
            target_tier=target_tier,
            transition_type=t_type,
            trigger_reason=trig_msg,
            scorecard_summary=scorecard or {},
            previous_chain_hash=latest_hash,
            evaluated_at=now,
        )
        self._ledger.record_transition(transition)
        return transition

    def evaluate_evidence(
        self,
        scorecard: Mapping[str, Any],
        drift_multiplier: Decimal | None = None,
    ) -> GovernanceTransitionV1:
        """Evaluate empirical statistical evidence and decide tier transition."""
        current_tier = self.get_current_tier()
        idx = _TIER_SEQUENCE.index(current_tier)
        now = datetime.now(UTC)
        latest_hash = self._ledger.get_latest_chain_hash()

        dsr = Decimal(str(scorecard.get("deflated_sharpe_ratio", "0.0")))
        pbo = Decimal(str(scorecard.get("pbo", "1.0")))

        # 1. Check for statistical degradation (triggers demotion)
        if dsr < self._min_dsr or pbo > self._max_pbo:
            self._clean_sessions = 0
            target_tier = _TIER_SEQUENCE[max(0, idx - 1)]
            transition = build_governance_transition(
                event_id=uuid7(),
                previous_tier=current_tier,
                target_tier=target_tier,
                transition_type=(
                    GovernanceTransitionType.DEMOTION
                    if target_tier != current_tier
                    else GovernanceTransitionType.HOLD
                ),
                trigger_reason=(
                    f"statistical_degradation: dsr={dsr} (min {self._min_dsr}), "
                    f"pbo={pbo} (max {self._max_pbo})"
                ),
                scorecard_summary=scorecard,
                previous_chain_hash=latest_hash,
                evaluated_at=now,
            )
            self._ledger.record_transition(transition)
            return transition

        # 2. Check for excessive execution drift
        if drift_multiplier is not None and drift_multiplier > self._max_drift:
            self._clean_sessions = 0
            target_tier = _TIER_SEQUENCE[max(0, idx - 1)]
            transition = build_governance_transition(
                event_id=uuid7(),
                previous_tier=current_tier,
                target_tier=target_tier,
                transition_type=(
                    GovernanceTransitionType.DEMOTION
                    if target_tier != current_tier
                    else GovernanceTransitionType.HOLD
                ),
                trigger_reason=(
                    f"excessive_execution_drift: multiplier={drift_multiplier} "
                    f"(max {self._max_drift})"
                ),
                scorecard_summary=scorecard,
                previous_chain_hash=latest_hash,
                evaluated_at=now,
            )
            self._ledger.record_transition(transition)
            return transition

        # 3. Check session count maturity for promotion
        if self._clean_sessions < self._min_sessions:
            transition = build_governance_transition(
                event_id=uuid7(),
                previous_tier=current_tier,
                target_tier=current_tier,
                transition_type=GovernanceTransitionType.HOLD,
                trigger_reason=(
                    f"insufficient_sessions: {self._clean_sessions}"
                    f"/{self._min_sessions} clean sessions"
                ),
                scorecard_summary=scorecard,
                previous_chain_hash=latest_hash,
                evaluated_at=now,
            )
            self._ledger.record_transition(transition)
            return transition

        # 4. Promotion eligible
        if idx < len(_TIER_SEQUENCE) - 1:
            target_tier = _TIER_SEQUENCE[idx + 1]
            self._clean_sessions = 0
            transition = build_governance_transition(
                event_id=uuid7(),
                previous_tier=current_tier,
                target_tier=target_tier,
                transition_type=GovernanceTransitionType.PROMOTION,
                trigger_reason=(
                    f"evidence_promotion_satisfied: dsr={dsr}, pbo={pbo}, "
                    f"sessions={self._min_sessions}"
                ),
                scorecard_summary=scorecard,
                previous_chain_hash=latest_hash,
                evaluated_at=now,
            )
            self._ledger.record_transition(transition)
            return transition

        # Already at highest tier
        transition = build_governance_transition(
            event_id=uuid7(),
            previous_tier=current_tier,
            target_tier=current_tier,
            transition_type=GovernanceTransitionType.HOLD,
            trigger_reason="at_maximum_tier_bounded_operating",
            scorecard_summary=scorecard,
            previous_chain_hash=latest_hash,
            evaluated_at=now,
        )
        self._ledger.record_transition(transition)
        return transition
