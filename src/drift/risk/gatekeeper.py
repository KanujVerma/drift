"""Deterministic hard risk gatekeeper engine (M13-3).

Enforces non-negotiable position limits, gross exposure caps, drawdown stops,
persistent kill switches, and order rate throttles prior to order submission.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from drift.domain.evaluator_portfolio import (
    PortfolioStateV2,
    canonical_money,
    decimal_context,
)
from drift.domain.risk import (
    RiskPolicyV1,
    RiskVerdictStatus,
    RiskVerdictV1,
    build_risk_verdict,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import SimulatedOrderV1
from drift.risk.journal import PersistentRiskJournal

BPS_DENOMINATOR = Decimal("10000")

__all__ = [
    "HardRiskGatekeeper",
]


class HardRiskGatekeeper:
    """Deterministic pre-execution risk gatekeeper engine."""

    def __init__(
        self,
        *,
        policy: RiskPolicyV1,
        journal: PersistentRiskJournal,
        initial_nav: Decimal | None = None,
    ) -> None:
        self._policy = policy
        self._journal = journal
        self._peak_nav = initial_nav if initial_nav is not None else Decimal("0")
        self._session_start_nav = initial_nav
        self._current_session_key: SessionKeyV1 | None = None
        self._order_timestamps: list[datetime] = []

    @property
    def policy(self) -> RiskPolicyV1:
        """Active hard risk policy."""
        return self._policy

    @property
    def journal(self) -> PersistentRiskJournal:
        """Persistent SQLite risk journal and latching kill switch."""
        return self._journal

    def evaluate_order(
        self,
        order: SimulatedOrderV1,
        *,
        portfolio_state: PortfolioStateV2,
        current_price: Decimal | None,
        evaluation_time: datetime,
    ) -> RiskVerdictV1:
        """Evaluate order against non-negotiable hard risk limits.

        Returns RiskVerdictV1 and logs verdict into PersistentRiskJournal.
        """
        # 1. Persistent Kill Switch Latch Check
        if self._journal.is_kill_switch_tripped():
            return self._record_verdict(
                order_id=order.order_id,
                status=RiskVerdictStatus.KILL_SWITCH_ACTIVE,
                reason="emergency_kill_switch_is_active: trading halted",
                evaluated_at=evaluation_time,
            )

        # 2. Fail-Closed Price Validation
        if (
            current_price is None
            or not current_price.is_finite()
            or current_price <= Decimal("0")
        ):
            return self._record_verdict(
                order_id=order.order_id,
                status=RiskVerdictStatus.REJECTED,
                reason="indeterminate_market_price: fail closed on invalid price",
                evaluated_at=evaluation_time,
            )

        # 3. Order Rate Limiter (Sliding 60-Second Window)
        cutoff = evaluation_time - timedelta(seconds=60)
        self._order_timestamps = [t for t in self._order_timestamps if t > cutoff]
        if len(self._order_timestamps) >= self._policy.max_orders_per_minute:
            return self._record_verdict(
                order_id=order.order_id,
                status=RiskVerdictStatus.REJECTED,
                reason=(
                    f"order_rate_limit_exceeded: maximum "
                    f"{self._policy.max_orders_per_minute} orders per minute"
                ),
                evaluated_at=evaluation_time,
            )

        # 4. NAV & Drawdown Circuit Breakers
        nav = portfolio_state.net_asset_value
        if nav <= Decimal("0"):
            self._journal.trip_kill_switch(
                reason="portfolio_insolvency: NAV is non-positive",
                tripped_at=evaluation_time,
            )
            return self._record_verdict(
                order_id=order.order_id,
                status=RiskVerdictStatus.KILL_SWITCH_ACTIVE,
                reason="portfolio_insolvency: NAV is non-positive",
                evaluated_at=evaluation_time,
            )

        with decimal_context():
            if self._session_start_nav is None:
                self._session_start_nav = nav
            if nav > self._peak_nav:
                self._peak_nav = nav

            if self._current_session_key is None:
                self._current_session_key = portfolio_state.session_key
            elif self._current_session_key != portfolio_state.session_key:
                self._session_start_nav = nav
                self._current_session_key = portfolio_state.session_key

            # Session Drawdown Check
            if nav < self._session_start_nav:
                loss = self._session_start_nav - nav
                session_dd_bps = int((loss / self._session_start_nav) * BPS_DENOMINATOR)
                if session_dd_bps >= self._policy.max_session_drawdown_basis_points:
                    limit_bps = self._policy.max_session_drawdown_basis_points
                    self._journal.trip_kill_switch(
                        reason=(
                            f"session_drawdown_breached: {session_dd_bps} bps >= "
                            f"limit {limit_bps} bps"
                        ),
                        tripped_at=evaluation_time,
                    )
                    return self._record_verdict(
                        order_id=order.order_id,
                        status=RiskVerdictStatus.KILL_SWITCH_ACTIVE,
                        reason="session_drawdown_breached: kill switch tripped",
                        evaluated_at=evaluation_time,
                    )

            # Trailing Peak Drawdown Check
            if nav < self._peak_nav:
                trailing_loss = self._peak_nav - nav
                trailing_dd_bps = int(
                    (trailing_loss / self._peak_nav) * BPS_DENOMINATOR
                )
                if trailing_dd_bps >= self._policy.max_trailing_drawdown_basis_points:
                    limit_tr = self._policy.max_trailing_drawdown_basis_points
                    self._journal.trip_kill_switch(
                        reason=(
                            f"trailing_drawdown_breached: {trailing_dd_bps} bps >= "
                            f"limit {limit_tr} bps"
                        ),
                        tripped_at=evaluation_time,
                    )
                    return self._record_verdict(
                        order_id=order.order_id,
                        status=RiskVerdictStatus.KILL_SWITCH_ACTIVE,
                        reason="trailing_drawdown_breached: kill switch tripped",
                        evaluated_at=evaluation_time,
                    )

        # 5. Order Size Limits
        if order.quantity > self._policy.max_order_quantity:
            return self._record_verdict(
                order_id=order.order_id,
                status=RiskVerdictStatus.REJECTED,
                reason=(
                    f"max_order_quantity_exceeded: requested {order.quantity} "
                    f"> limit {self._policy.max_order_quantity}"
                ),
                evaluated_at=evaluation_time,
            )

        with decimal_context():
            order_notional = canonical_money(Decimal(order.quantity) * current_price)
        if order_notional > self._policy.max_order_notional:
            return self._record_verdict(
                order_id=order.order_id,
                status=RiskVerdictStatus.REJECTED,
                reason=(
                    f"max_order_notional_exceeded: order notional {order_notional} "
                    f"> limit {self._policy.max_order_notional}"
                ),
                evaluated_at=evaluation_time,
            )

        # 6. Position Concentration and Gross Exposure (for BUY orders)
        if order.side == "buy":
            current_held = 0
            for h in portfolio_state.holdings:
                if h.security_id == order.security_id:
                    current_held = h.quantity
                    break

            with decimal_context():
                proj_qty = current_held + order.quantity
                proj_pos_notional = canonical_money(Decimal(proj_qty) * current_price)
                if proj_pos_notional > self._policy.max_position_notional:
                    return self._record_verdict(
                        order_id=order.order_id,
                        status=RiskVerdictStatus.REJECTED,
                        reason=(
                            f"max_position_notional_exceeded: {proj_pos_notional} "
                            f"> limit {self._policy.max_position_notional}"
                        ),
                        evaluated_at=evaluation_time,
                    )

                proj_weight_bps = int((proj_pos_notional / nav) * BPS_DENOMINATOR)
                limit_w = self._policy.max_position_weight_basis_points
                if proj_weight_bps > limit_w:
                    return self._record_verdict(
                        order_id=order.order_id,
                        status=RiskVerdictStatus.REJECTED,
                        reason=(
                            f"max_position_weight_exceeded: {proj_weight_bps} "
                            f"bps > limit {limit_w} bps"
                        ),
                        evaluated_at=evaluation_time,
                    )

                proj_gross = portfolio_state.holdings_market_value + order_notional
                proj_gross_bps = int((proj_gross / nav) * BPS_DENOMINATOR)
                limit_g = self._policy.max_gross_exposure_basis_points
                if proj_gross_bps > limit_g:
                    return self._record_verdict(
                        order_id=order.order_id,
                        status=RiskVerdictStatus.REJECTED,
                        reason=(
                            f"max_gross_exposure_exceeded: {proj_gross_bps} "
                            f"bps > limit {limit_g} bps"
                        ),
                        evaluated_at=evaluation_time,
                    )

        # 7. Allowed
        self._order_timestamps.append(evaluation_time)
        return self._record_verdict(
            order_id=order.order_id,
            status=RiskVerdictStatus.ALLOWED,
            reason=None,
            evaluated_at=evaluation_time,
        )

    def _record_verdict(
        self,
        *,
        order_id: UUID,
        status: RiskVerdictStatus,
        reason: str | None,
        evaluated_at: datetime,
    ) -> RiskVerdictV1:
        verdict = build_risk_verdict(
            order_id=order_id,
            status=status,
            reason=reason,
            evaluated_at=evaluated_at,
        )
        self._journal.record_verdict(verdict)
        return verdict
