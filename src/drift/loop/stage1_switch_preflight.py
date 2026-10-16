"""Deterministic strategy-switch eligibility preflight for Stage 1 (Issue 422).

Evaluates whether a proposed Stage 1 strategy selection (B3, B4, or B5) is
eligible to proceed toward portfolio target staging. Operates as a pure,
non-mutating preflight component that enforces historical observation
completeness, fixed universe integrity, price validity, and incumbent
portfolio safety before any candidate targets can reach the evaluator.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from drift.analysis.analytical_returns import (
    CorporateActionAdjustment,
    build_analytical_return_series,
)
from drift.baselines.b3_monthly_equal_weight_rebalance import (
    B3MonthlyEqualWeightRebalanceStrategy,
)
from drift.baselines.b4_momentum import (
    B4_STRATEGY_HASH,
)
from drift.baselines.b5_low_volatility import (
    B5_STRATEGY_HASH,
)
from drift.baselines.common import (
    deterministic_baseline_uuid7,
    extract_security_history,
    get_admitted_securities,
)
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.serialization.canonical import content_hash

STAGE1_ETF_SYMBOLS: tuple[str, ...] = (
    "VOO",
    "IJH",
    "IJR",
    "QQQ",
    "VEA",
    "VWO",
    "SHY",
    "IEF",
    "TLT",
    "TIP",
    "LQD",
    "GLD",
)
STAGE1_EXPECTED_UNIVERSE_SIZE = len(STAGE1_ETF_SYMBOLS)

B3_STRATEGY_NAMES = frozenset(
    {"b3", "b3_monthly_equal_weight_rebalance", "b3_equal_weight"}
)
B4_STRATEGY_NAMES = frozenset({"b4", "b4_momentum"})
B5_STRATEGY_NAMES = frozenset({"b5", "b5_low_volatility"})

STAGE1_ADMITTED_STRATEGIES = B3_STRATEGY_NAMES | B4_STRATEGY_NAMES | B5_STRATEGY_NAMES

B3_MIN_SESSIONS = 1
B4_MIN_SESSIONS = 253
B5_MIN_SESSIONS = 61

B3_CANONICAL_HASH: SHA256Hash = B3MonthlyEqualWeightRebalanceStrategy()._strategy_hash
B4_CANONICAL_HASH: SHA256Hash = B4_STRATEGY_HASH
B5_CANONICAL_HASH: SHA256Hash = B5_STRATEGY_HASH

B3_CANONICAL_ID: UUID = deterministic_baseline_uuid7(
    "drift.baselines.b3_monthly_equal_weight_rebalance"
)
B4_CANONICAL_ID: UUID = deterministic_baseline_uuid7("drift.baselines.b4_momentum")
B5_CANONICAL_ID: UUID = deterministic_baseline_uuid7(
    "drift.baselines.b5_low_volatility"
)

B3_CANONICAL_LOCATION = "drift/baselines/b3_monthly_equal_weight_rebalance.py"
B4_CANONICAL_LOCATION = "drift/baselines/b4_momentum.py"
B5_CANONICAL_LOCATION = "drift/baselines/b5_low_volatility.py"


class PreflightStatus(StrEnum):
    """Categorical outcomes of the Stage 1 switch preflight evaluation."""

    ELIGIBLE = "eligible"
    UNAVAILABLE = "unavailable"
    ABSTAIN = "abstain"
    REJECTED = "rejected"
    INDETERMINATE_SAFETY = "indeterminate_safety"


class Stage1SwitchPreflightResult(FrozenModel):
    """Immutable, tamper-evident preflight verdict for Stage 1 strategy switching."""

    schema_version: Literal["1"] = "1"
    status: PreflightStatus
    reason: NonBlankStr
    proposed_strategy: str
    current_strategy: str | None
    effective_strategy: str | None
    is_tradeable: bool
    hold_incumbent: bool
    requires_containment: bool
    session_key: SessionKeyV1 | None = None
    decision_cutoff: UTCDateTime | None = None
    cohort_hash: SHA256Hash | None = None
    admitted_universe: tuple[UUID7, ...] = ()
    portfolio_state_hash: SHA256Hash | None = None
    account_id: str | None = None
    mandate: str | None = None
    preflight_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_preflight_verdict(self) -> Self:
        """Self-validate status/flag coherence and cryptographic content hash."""
        if self.status == PreflightStatus.ELIGIBLE:
            if not self.is_tradeable:
                raise ValueError("ELIGIBLE status requires is_tradeable=True")
            if self.hold_incumbent:
                raise ValueError("ELIGIBLE status requires hold_incumbent=False")
            if self.requires_containment:
                raise ValueError("ELIGIBLE status requires requires_containment=False")
            if self.effective_strategy != self.proposed_strategy:
                raise ValueError(
                    "ELIGIBLE status requires effective_strategy == proposed_strategy"
                )
            if self.session_key is None:
                raise ValueError("ELIGIBLE status requires bound session_key")
            if self.decision_cutoff is None:
                raise ValueError("ELIGIBLE status requires bound decision_cutoff")
            if not self.admitted_universe:
                raise ValueError("ELIGIBLE status requires non-empty admitted_universe")
            if self.portfolio_state_hash is None:
                raise ValueError("ELIGIBLE status requires bound portfolio_state_hash")

        elif self.status == PreflightStatus.ABSTAIN:
            if self.is_tradeable:
                raise ValueError("ABSTAIN status requires is_tradeable=False")
            if self.hold_incumbent:
                if self.requires_containment:
                    raise ValueError(
                        "safe hold_incumbent requires requires_containment=False"
                    )
                if self.effective_strategy != self.current_strategy:
                    raise ValueError(
                        "safe hold_incumbent requires "
                        "effective_strategy == current_strategy"
                    )
            else:
                if not self.requires_containment:
                    raise ValueError(
                        "failed hold_incumbent requires requires_containment=True"
                    )
                if self.effective_strategy is not None:
                    raise ValueError(
                        "failed hold_incumbent requires effective_strategy=None"
                    )

        elif self.status in (PreflightStatus.UNAVAILABLE, PreflightStatus.REJECTED):
            if self.is_tradeable:
                raise ValueError(f"{self.status} status requires is_tradeable=False")
            if self.hold_incumbent:
                if self.requires_containment:
                    raise ValueError(
                        "safe hold_incumbent requires requires_containment=False"
                    )
                if self.effective_strategy != self.current_strategy:
                    raise ValueError(
                        "safe hold_incumbent requires "
                        "effective_strategy == current_strategy"
                    )
            else:
                if not self.requires_containment:
                    raise ValueError(
                        "failed hold_incumbent requires requires_containment=True"
                    )
                if self.effective_strategy is not None:
                    raise ValueError(
                        "failed hold_incumbent requires effective_strategy=None"
                    )

        elif self.status == PreflightStatus.INDETERMINATE_SAFETY:
            if self.is_tradeable:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires is_tradeable=False"
                )
            if self.hold_incumbent:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires hold_incumbent=False"
                )
            if not self.requires_containment:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires requires_containment=True"
                )
            if self.effective_strategy is not None:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires effective_strategy=None"
                )

        expected_hash = compute_preflight_hash(
            status=self.status,
            reason=self.reason,
            proposed_strategy=self.proposed_strategy,
            current_strategy=self.current_strategy,
            effective_strategy=self.effective_strategy,
            is_tradeable=self.is_tradeable,
            hold_incumbent=self.hold_incumbent,
            requires_containment=self.requires_containment,
            session_key=self.session_key,
            decision_cutoff=self.decision_cutoff,
            cohort_hash=self.cohort_hash,
            admitted_universe=self.admitted_universe,
            portfolio_state_hash=self.portfolio_state_hash,
            account_id=self.account_id,
            mandate=self.mandate,
        )
        if self.preflight_hash != expected_hash:
            raise ValueError(
                f"preflight hash mismatch: expected {expected_hash}, "
                f"got {self.preflight_hash}"
            )
        return self


def validate_strategy_identity(
    strategy: str | StrategyReference | None,
) -> tuple[str | None, str | None]:
    """Validate strategy identity against Stage 1 admitted references.

    Returns (canonical_name, rejection_reason).
    canonical_name is one of 'B3', 'B4', 'B5', 'ABSTAIN', or None.
    If rejection_reason is not None, validation failed.
    """
    if strategy is None:
        return None, None
    if isinstance(strategy, StrategyReference):
        if strategy.strategy_version != "1":
            return (
                None,
                f"unsupported_strategy_version: expected '1', "
                f"got {strategy.strategy_version!r}",
            )
        if strategy.strategy_id == B3_CANONICAL_ID:
            if strategy.code_hash != B3_CANONICAL_HASH:
                return (
                    None,
                    f"strategy_code_hash_mismatch: B3 code hash {strategy.code_hash} "
                    f"does not match canonical {B3_CANONICAL_HASH}",
                )
            if strategy.artifact_reference.location != B3_CANONICAL_LOCATION:
                return (
                    None,
                    "strategy_location_mismatch: B3 location "
                    f"{strategy.artifact_reference.location!r} "
                    "does not match canonical",
                )
            if strategy.artifact_reference.content_hash != strategy.code_hash:
                return (
                    None,
                    "strategy_artifact_hash_mismatch: artifact content hash "
                    "does not match strategy code hash",
                )
            return "B3", None

        if strategy.strategy_id == B4_CANONICAL_ID:
            if strategy.code_hash != B4_CANONICAL_HASH:
                return (
                    None,
                    f"strategy_code_hash_mismatch: B4 code hash {strategy.code_hash} "
                    f"does not match canonical {B4_CANONICAL_HASH}",
                )
            if strategy.artifact_reference.location != B4_CANONICAL_LOCATION:
                return (
                    None,
                    "strategy_location_mismatch: B4 location "
                    f"{strategy.artifact_reference.location!r} "
                    "does not match canonical",
                )
            if strategy.artifact_reference.content_hash != strategy.code_hash:
                return (
                    None,
                    "strategy_artifact_hash_mismatch: artifact content hash "
                    "does not match strategy code hash",
                )
            return "B4", None

        if strategy.strategy_id == B5_CANONICAL_ID:
            if strategy.code_hash != B5_CANONICAL_HASH:
                return (
                    None,
                    f"strategy_code_hash_mismatch: B5 code hash {strategy.code_hash} "
                    f"does not match canonical {B5_CANONICAL_HASH}",
                )
            if strategy.artifact_reference.location != B5_CANONICAL_LOCATION:
                return (
                    None,
                    "strategy_location_mismatch: B5 location "
                    f"{strategy.artifact_reference.location!r} "
                    "does not match canonical",
                )
            if strategy.artifact_reference.content_hash != strategy.code_hash:
                return (
                    None,
                    "strategy_artifact_hash_mismatch: artifact content hash "
                    "does not match strategy code hash",
                )
            return "B5", None

        return (
            None,
            f"unrecognized_strategy_id: strategy_id {strategy.strategy_id} "
            "is not an approved Stage 1 baseline",
        )

    norm = strategy.strip().lower()
    if norm in B3_STRATEGY_NAMES or norm == "b3":
        return "B3", None
    if norm in B4_STRATEGY_NAMES or norm == "b4":
        return "B4", None
    if norm in B5_STRATEGY_NAMES or norm == "b5":
        return "B5", None
    if norm == "abstain":
        return "ABSTAIN", None
    return (
        None,
        f"unsupported_stage1_strategy: proposed strategy {strategy!r} "
        "is not an admitted Stage 1 candidate (admitted: B3, B4, B5, ABSTAIN)",
    )


def compute_preflight_hash(
    *,
    status: PreflightStatus,
    reason: str,
    proposed_strategy: str,
    current_strategy: str | None,
    effective_strategy: str | None,
    is_tradeable: bool,
    hold_incumbent: bool,
    requires_containment: bool,
    session_key: SessionKeyV1 | None,
    decision_cutoff: datetime | None,
    cohort_hash: str | None,
    admitted_universe: tuple[UUID7, ...],
    portfolio_state_hash: str | None = None,
    account_id: str | None = None,
    mandate: str | None = None,
) -> SHA256Hash:
    """Compute deterministic SHA256 content hash of the preflight verdict."""
    payload = {
        "status": status.value,
        "reason": reason,
        "proposed_strategy": proposed_strategy,
        "current_strategy": current_strategy,
        "effective_strategy": effective_strategy,
        "is_tradeable": is_tradeable,
        "hold_incumbent": hold_incumbent,
        "requires_containment": requires_containment,
        "session_key": (
            {
                "mic": session_key.mic,
                "session_scope": session_key.session_scope,
                "local_date": str(session_key.local_date),
            }
            if session_key is not None
            else None
        ),
        "decision_cutoff": (
            decision_cutoff.isoformat() if decision_cutoff is not None else None
        ),
        "cohort_hash": cohort_hash,
        "admitted_universe": [str(u) for u in admitted_universe],
        "portfolio_state_hash": portfolio_state_hash,
        "account_id": account_id,
        "mandate": mandate,
    }
    return content_hash(payload)


def _build_result(
    *,
    status: PreflightStatus,
    reason: str,
    proposed_strategy: str,
    current_strategy: str | None,
    effective_strategy: str | None,
    is_tradeable: bool,
    hold_incumbent: bool,
    requires_containment: bool,
    session_key: SessionKeyV1 | None = None,
    decision_cutoff: datetime | None = None,
    cohort_hash: str | None = None,
    admitted_universe: tuple[UUID7, ...] = (),
    portfolio_state_hash: str | None = None,
    account_id: str | None = None,
    mandate: str | None = None,
) -> Stage1SwitchPreflightResult:
    p_hash = compute_preflight_hash(
        status=status,
        reason=reason,
        proposed_strategy=proposed_strategy,
        current_strategy=current_strategy,
        effective_strategy=effective_strategy,
        is_tradeable=is_tradeable,
        hold_incumbent=hold_incumbent,
        requires_containment=requires_containment,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=admitted_universe,
        portfolio_state_hash=portfolio_state_hash,
        account_id=account_id,
        mandate=mandate,
    )
    return Stage1SwitchPreflightResult(
        schema_version="1",
        status=status,
        reason=reason,
        proposed_strategy=proposed_strategy,
        current_strategy=current_strategy,
        effective_strategy=effective_strategy,
        is_tradeable=is_tradeable,
        hold_incumbent=hold_incumbent,
        requires_containment=requires_containment,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=admitted_universe,
        portfolio_state_hash=portfolio_state_hash,
        account_id=account_id,
        mandate=mandate,
        preflight_hash=p_hash,
    )


def _get_raw_observations(
    context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None,
    security_id: UUID7,
) -> tuple[object, ...]:
    if context is None:
        return ()
    if isinstance(context, StrategyDecisionContextV1):
        for group in context.decision_views:
            if group.security_id == security_id:
                return tuple(group.views)
        return ()
    for recon_group in context.reconstructed_decision_views:
        if recon_group.security_id == security_id:
            return tuple(recon_group.observations)
    return ()


def verify_stage1_switch_preflight_result(
    result: Stage1SwitchPreflightResult,
    *,
    current_portfolio_state: PortfolioStateV2 | None = None,
    expected_account_id: str | None = None,
    expected_mandate: str | None = None,
    expected_session_key: SessionKeyV1 | None = None,
) -> bool:
    """Cryptographically revalidate a preflight verdict for consumers (Issue 423).

    Verifies:
    1. Internal hash and flag coherence (enforced by result model validator).
    2. Exact portfolio state binding: ensures live portfolio matches the exact book
       evaluated by preflight, catching state modifications or drift.
    3. Account binding: ensures verdict cannot be replayed across accounts.
    4. Mandate binding: ensures verdict matches expected mandate.
    5. Session binding: ensures verdict belongs to the active decision session.

    Raises ValueError if any binding fails, or returns True on success.
    """
    if expected_session_key is not None and result.session_key != expected_session_key:
        raise ValueError(
            f"verdict session key mismatch: expected {expected_session_key}, "
            f"got {result.session_key}"
        )

    if expected_account_id is not None and result.account_id != expected_account_id:
        raise ValueError(
            f"verdict account_id mismatch: expected {expected_account_id!r}, "
            f"got {result.account_id!r}"
        )

    if expected_mandate is not None and result.mandate != expected_mandate:
        raise ValueError(
            f"verdict mandate mismatch: expected {expected_mandate!r}, "
            f"got {result.mandate!r}"
        )

    if current_portfolio_state is not None:
        state_hash = content_hash(current_portfolio_state.model_dump(mode="python"))
        if result.portfolio_state_hash != state_hash:
            raise ValueError(
                f"portfolio state changed: preflight evaluated "
                f"{result.portfolio_state_hash}, live state is {state_hash}"
            )
    elif result.portfolio_state_hash is not None:
        raise ValueError(
            "preflight result binds a portfolio state, but live "
            "current_portfolio_state was not provided"
        )

    return True


def evaluate_stage1_switch_preflight(
    *,
    proposed_strategy: str | StrategyReference,
    current_strategy: str | StrategyReference | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    required_universe: Sequence[UUID7] | None = None,
    expected_universe_hash: SHA256Hash | None = None,
    current_portfolio_state: PortfolioStateV2 | None = None,
    allow_incumbent_continuation: bool = True,
    adjustments_by_security: (
        Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None
    ) = None,
    account_id: str | None = None,
    mandate: str | None = None,
    open_orders: Sequence[object] | None = None,
    mandate_verified: bool = True,
    risk_verified: bool = True,
) -> Stage1SwitchPreflightResult:
    """Evaluate whether a proposed switch is eligible for Stage 1 target staging.

    Distinguishes:
    - ELIGIBLE: Proposed strategy has sufficient, valid evidence to compute targets.
    - UNAVAILABLE: Required data/history is missing; trade generation is blocked.
    - ABSTAIN: Deliberate hold; incumbent strategy continues if safe.
    - REJECTED: Proposed strategy or configuration fails deterministic validation.
    - INDETERMINATE_SAFETY: Portfolio or risk state is unknown; containment needed.
    """
    port_state_hash = (
        content_hash(current_portfolio_state.model_dump(mode="python"))
        if current_portfolio_state is not None
        else None
    )

    # 1. Strategy identity validation
    prop_name, prop_err = validate_strategy_identity(proposed_strategy)
    curr_name, curr_err = validate_strategy_identity(current_strategy)

    if prop_err is not None or prop_name is None:
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=prop_err or "unsupported_strategy: proposed strategy cannot be None",
            prop_name=str(proposed_strategy),
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if curr_err is not None:
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=f"unadmitted_incumbent_strategy: {curr_err}",
            prop_name=prop_name or "UNKNOWN",
            curr_name=str(current_strategy),
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    # 2. Decision context presence and basic sanity
    if decision_context is None:
        reason = "missing_decision_context: decision context is None"
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.UNAVAILABLE,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=None,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    session_key = decision_context.session_key
    decision_cutoff = decision_context.decision_cutoff
    cohort_hash = getattr(decision_context, "cohort_hash", None)
    context_cohort = get_admitted_securities(decision_context)

    if decision_context.portfolio_nav <= Decimal("0"):
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason="non_positive_nav: context portfolio_nav is non-positive",
            proposed_strategy=prop_name or "UNKNOWN",
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=context_cohort,
            portfolio_state_hash=port_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    # 3. Portfolio state verification (Point 2)
    if current_portfolio_state is None:
        reason = (
            "missing_portfolio_state: current_portfolio_state is required "
            "to establish safe trading or holding"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=None,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=None,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if current_portfolio_state.cash_balance < Decimal("0"):
        reason = "negative_cash: current portfolio cash balance is negative"
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    for h in current_portfolio_state.holdings:
        if h.basis_status == "indeterminate":
            reason = (
                f"indeterminate_holding_basis: holding {h.security_id} "
                "has indeterminate cost basis"
            )
            return _resolve_non_eligible_outcome(
                status=PreflightStatus.INDETERMINATE_SAFETY,
                reason=reason,
                prop_name=prop_name or "UNKNOWN",
                curr_name=curr_name,
                decision_context=decision_context,
                current_portfolio_state=current_portfolio_state,
                allow_incumbent_continuation=allow_incumbent_continuation,
                account_id=account_id,
                mandate=mandate,
                portfolio_state_hash=port_state_hash,
                open_orders=open_orders,
                mandate_verified=mandate_verified,
                risk_verified=risk_verified,
            )

    if current_portfolio_state.session_key != decision_context.session_key:
        reason = (
            "portfolio_context_session_mismatch: portfolio session "
            f"{current_portfolio_state.session_key} does not match "
            f"context {decision_context.session_key}"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if abs(
        current_portfolio_state.net_asset_value - decision_context.portfolio_nav
    ) > Decimal("0.01"):
        reason = (
            f"portfolio_context_nav_mismatch: portfolio NAV "
            f"{current_portfolio_state.net_asset_value} does not match context NAV "
            f"{decision_context.portfolio_nav}"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if hasattr(decision_context, "current_cash") and abs(
        current_portfolio_state.cash_balance - decision_context.current_cash
    ) > Decimal("0.01"):
        reason = (
            f"portfolio_context_cash_mismatch: portfolio cash "
            f"{current_portfolio_state.cash_balance} does not match context cash "
            f"{decision_context.current_cash}"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if hasattr(decision_context, "current_holdings"):
        ctx_holdings = {
            h.security_id: h.quantity for h in decision_context.current_holdings
        }
        port_holdings = {
            h.security_id: h.quantity for h in current_portfolio_state.holdings
        }
        if ctx_holdings != port_holdings:
            reason = (
                "portfolio_context_holdings_mismatch: "
                "portfolio holdings do not match context holdings"
            )
            return _resolve_non_eligible_outcome(
                status=PreflightStatus.INDETERMINATE_SAFETY,
                reason=reason,
                prop_name=prop_name or "UNKNOWN",
                curr_name=curr_name,
                decision_context=decision_context,
                current_portfolio_state=current_portfolio_state,
                allow_incumbent_continuation=allow_incumbent_continuation,
                account_id=account_id,
                mandate=mandate,
                portfolio_state_hash=port_state_hash,
                open_orders=open_orders,
                mandate_verified=mandate_verified,
                risk_verified=risk_verified,
            )

    if open_orders:
        reason = (
            f"pending_orders_present: portfolio has {len(open_orders)} "
            "open or pending orders"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if not mandate_verified:
        reason = "unverified_mandate: portfolio investment mandate is unverified"
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=False,
            risk_verified=risk_verified,
        )

    if not risk_verified:
        reason = "unverified_risk: portfolio risk verification checks failed or missing"
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=False,
        )

    # 4. Incumbent strategy verification
    if curr_name is None:
        reason = (
            "missing_current_strategy: current incumbent strategy selection is "
            "required to verify strategy transition safety"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=None,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if curr_name not in {"B3", "B4", "B5"}:
        reason = (
            f"unadmitted_incumbent_strategy: incumbent strategy {curr_name!r} "
            "is not an admitted Stage 1 candidate"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            prop_name=prop_name or "UNKNOWN",
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    # 5. Deliberate Abstain / Hold Request
    if prop_name == "ABSTAIN":
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.ABSTAIN,
            reason="deliberate_abstain: selector requested hold of incumbent strategy",
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    # 6. Universe Completeness Verification (Point 1)
    if required_universe is None or len(required_universe) == 0:
        reason = (
            "missing_required_universe: required_universe must be an explicit, "
            "nonempty sequence of admitted security IDs"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.UNAVAILABLE,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if len(required_universe) != len(set(required_universe)):
        reason = (
            "duplicate_security_in_required_universe: required_universe contains "
            "duplicate security IDs"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if len(required_universe) != STAGE1_EXPECTED_UNIVERSE_SIZE:
        reason = (
            "mismatched_universe_size: expected exactly "
            f"{STAGE1_EXPECTED_UNIVERSE_SIZE} Stage 1 ETFs, "
            f"got {len(required_universe)}"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if len(context_cohort) != len(set(context_cohort)):
        reason = (
            "duplicate_security_in_context_cohort: context admitted securities "
            "contain duplicates"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    req_set = set(required_universe)
    ctx_set = set(context_cohort)

    if ctx_set - req_set:
        extra_uuids = sorted(str(u) for u in (ctx_set - req_set))
        reason = (
            f"extra_securities_in_context: context contains unapproved extra "
            f"securities: {extra_uuids}"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if req_set - ctx_set:
        missing_uuids = sorted(str(u) for u in (req_set - ctx_set))
        reason = (
            f"incomplete_admitted_universe: context missing required "
            f"securities: {missing_uuids}"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.UNAVAILABLE,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if expected_universe_hash is not None and cohort_hash != expected_universe_hash:
        reason = (
            f"universe_hash_mismatch: expected {expected_universe_hash}, "
            f"got {cohort_hash}"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    eval_universe = tuple(sorted(req_set, key=lambda u: u.bytes))

    # 7. Determine Historical Session Minimum
    if prop_name == "B3":
        min_required_sessions = B3_MIN_SESSIONS
    elif prop_name == "B4":
        min_required_sessions = B4_MIN_SESSIONS
    elif prop_name == "B5":
        min_required_sessions = B5_MIN_SESSIONS
    else:
        min_required_sessions = 1

    # 8. Evaluate Evidence and Adjustments for Each Admitted Security (Point 4)
    cutoff_date = session_key.local_date
    eligible_momentum_securities: list[UUID7] = []
    eligible_volatility_securities: list[UUID7] = []

    for sec_id in eval_universe:
        raw_obs = _get_raw_observations(decision_context, sec_id)
        seen_raw_sessions = set()
        for raw_item in raw_obs:
            raw_s_key = getattr(raw_item, "source_session", None) or getattr(
                raw_item, "session_key", None
            )
            if raw_s_key is not None:
                if raw_s_key.local_date > cutoff_date:
                    reason = (
                        f"future_observation_detected: observation for security "
                        f"{sec_id} dated {raw_s_key.local_date} exceeds cutoff "
                        f"{cutoff_date}"
                    )
                    return _resolve_non_eligible_outcome(
                        status=PreflightStatus.UNAVAILABLE,
                        reason=reason,
                        prop_name=prop_name,
                        curr_name=curr_name,
                        decision_context=decision_context,
                        current_portfolio_state=current_portfolio_state,
                        allow_incumbent_continuation=allow_incumbent_continuation,
                        account_id=account_id,
                        mandate=mandate,
                        portfolio_state_hash=port_state_hash,
                        open_orders=open_orders,
                        mandate_verified=mandate_verified,
                        risk_verified=risk_verified,
                    )
                if raw_s_key in seen_raw_sessions:
                    reason = (
                        f"duplicate_session_observation: security {sec_id} "
                        f"has duplicate observation for session {raw_s_key}"
                    )
                    return _resolve_non_eligible_outcome(
                        status=PreflightStatus.REJECTED,
                        reason=reason,
                        prop_name=prop_name,
                        curr_name=curr_name,
                        decision_context=decision_context,
                        current_portfolio_state=current_portfolio_state,
                        allow_incumbent_continuation=allow_incumbent_continuation,
                        account_id=account_id,
                        mandate=mandate,
                        portfolio_state_hash=port_state_hash,
                        open_orders=open_orders,
                        mandate_verified=mandate_verified,
                        risk_verified=risk_verified,
                    )
                seen_raw_sessions.add(raw_s_key)

            # Check time-of-day availability / late-arriving timestamps
            for time_attr in (
                "available_at",
                "observed_at",
                "closed_at",
                "received_at",
                "timestamp",
                "evidence_vintage_cutoff",
            ):
                t_val = getattr(raw_item, time_attr, None)
                if isinstance(t_val, datetime) and t_val > decision_cutoff:
                    reason = (
                        "late_available_observation_detected: observation for security "
                        f"{sec_id} {time_attr} {t_val.isoformat()} exceeds "
                        f"decision cutoff {decision_cutoff.isoformat()}"
                    )
                    return _resolve_non_eligible_outcome(
                        status=PreflightStatus.UNAVAILABLE,
                        reason=reason,
                        prop_name=prop_name,
                        curr_name=curr_name,
                        decision_context=decision_context,
                        current_portfolio_state=current_portfolio_state,
                        allow_incumbent_continuation=allow_incumbent_continuation,
                        account_id=account_id,
                        mandate=mandate,
                        portfolio_state_hash=port_state_hash,
                        open_orders=open_orders,
                        mandate_verified=mandate_verified,
                        risk_verified=risk_verified,
                    )

        history = extract_security_history(decision_context, sec_id)
        if not history:
            reason = (
                f"missing_security_history: security {sec_id} has 0 observations; "
                f"minimum {min_required_sessions} required for {prop_name}"
            )
            return _resolve_non_eligible_outcome(
                status=PreflightStatus.UNAVAILABLE,
                reason=reason,
                prop_name=prop_name,
                curr_name=curr_name,
                decision_context=decision_context,
                current_portfolio_state=current_portfolio_state,
                allow_incumbent_continuation=allow_incumbent_continuation,
                account_id=account_id,
                mandate=mandate,
                portfolio_state_hash=port_state_hash,
                open_orders=open_orders,
                mandate_verified=mandate_verified,
                risk_verified=risk_verified,
            )

        if len(history) < min_required_sessions:
            reason = (
                f"insufficient_history: security {sec_id} has {len(history)} "
                f"observations; minimum {min_required_sessions} required for "
                f"{prop_name}"
            )
            return _resolve_non_eligible_outcome(
                status=PreflightStatus.UNAVAILABLE,
                reason=reason,
                prop_name=prop_name,
                curr_name=curr_name,
                decision_context=decision_context,
                current_portfolio_state=current_portfolio_state,
                allow_incumbent_continuation=allow_incumbent_continuation,
                account_id=account_id,
                mandate=mandate,
                portfolio_state_hash=port_state_hash,
                open_orders=open_orders,
                mandate_verified=mandate_verified,
                risk_verified=risk_verified,
            )

        # Validate causality, duplicates, price sanity, and current session close
        seen_sessions = set()
        prev_date = None
        has_current_session_close = False

        for obs in history:
            s_date = obs.session_key.local_date
            if s_date > cutoff_date:
                reason = (
                    f"future_observation_detected: observation for security {sec_id} "
                    f"dated {s_date} exceeds decision cutoff {cutoff_date}"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.UNAVAILABLE,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )

            if obs.session_key in seen_sessions:
                reason = (
                    f"duplicate_session_observation: security {sec_id} has duplicate "
                    f"observation for session {obs.session_key}"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.REJECTED,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )
            seen_sessions.add(obs.session_key)

            if prev_date is not None and s_date < prev_date:
                reason = (
                    f"out_of_order_observations: security {sec_id} observations not "
                    f"chronologically sorted ({s_date} follows {prev_date})"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.REJECTED,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )
            prev_date = s_date

            p = obs.close_price
            if p is None or not p.is_finite() or p <= Decimal("0"):
                reason = (
                    f"invalid_close_price: security {sec_id} has invalid price {p} "
                    f"on session {obs.session_key}"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.REJECTED,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )

            if obs.session_key == session_key:
                has_current_session_close = True

        # Explicit current session closing mark check (no stale fallback trap)
        if not has_current_session_close:
            reason = (
                f"missing_current_session_close: security {sec_id} lacks explicit "
                f"closing mark for decision session {session_key}"
            )
            return _resolve_non_eligible_outcome(
                status=PreflightStatus.UNAVAILABLE,
                reason=reason,
                prop_name=prop_name,
                curr_name=curr_name,
                decision_context=decision_context,
                current_portfolio_state=current_portfolio_state,
                allow_incumbent_continuation=allow_incumbent_continuation,
                account_id=account_id,
                mandate=mandate,
                portfolio_state_hash=port_state_hash,
                open_orders=open_orders,
                mandate_verified=mandate_verified,
                risk_verified=risk_verified,
            )

        # Corporate action adjustments verification
        sec_adjs = (
            adjustments_by_security.get(sec_id, ())
            if adjustments_by_security is not None
            else ()
        )
        for adj in sec_adjs:
            if adj.split_ratio <= Decimal("0"):
                reason = (
                    f"invalid_corporate_action_adjustment: security {sec_id} "
                    f"split ratio {adj.split_ratio} must be strictly positive"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.REJECTED,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )
            if adj.cash_distribution < Decimal("0"):
                reason = (
                    f"invalid_corporate_action_adjustment: security {sec_id} "
                    f"cash distribution {adj.cash_distribution} cannot be negative"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.REJECTED,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )
            if adj.effective_date > session_key.local_date:
                reason = (
                    f"future_corporate_action_adjustment: adjustment for security "
                    f"{sec_id} dated {adj.effective_date} exceeds decision session "
                    f"date {session_key.local_date}"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.UNAVAILABLE,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )

        # Analytical return series verification for B4 and B5
        if prop_name in {"B4", "B5"}:
            try:
                series = build_analytical_return_series(
                    security_id=sec_id,
                    grade="exploratory",
                    observations=history,
                    adjustments=sec_adjs,
                )
            except Exception as exc:
                reason = (
                    f"analytical_series_error: security {sec_id} cannot build "
                    f"analytical return series: {exc}"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.UNAVAILABLE,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )

            if len(series.sessions) < min_required_sessions:
                reason = (
                    f"insufficient_analytical_sessions: security {sec_id} "
                    f"produced {len(series.sessions)} analytical sessions; "
                    f"minimum {min_required_sessions} required"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.UNAVAILABLE,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                    account_id=account_id,
                    mandate=mandate,
                    portfolio_state_hash=port_state_hash,
                    open_orders=open_orders,
                    mandate_verified=mandate_verified,
                    risk_verified=risk_verified,
                )

            if prop_name == "B4":
                t = len(series.sessions) - 1
                close_skip = series.sessions[t - 21].analytical_close
                close_form = series.sessions[t - 252].analytical_close
                if close_form > Decimal("0") and close_skip > Decimal("0"):
                    eligible_momentum_securities.append(sec_id)
            elif prop_name == "B5":
                valid_returns = [
                    s.return_from_prior
                    for s in series.sessions[-60:]
                    if s.return_from_prior is not None
                ]
                if len(valid_returns) >= 60:
                    eligible_volatility_securities.append(sec_id)

    # Check minimum eligible securities for B4 and B5 (accidental liquidation safeguard)
    if prop_name == "B4" and len(eligible_momentum_securities) < 2:
        reason = (
            f"insufficient_eligible_securities: only "
            f"{len(eligible_momentum_securities)} securities have valid momentum; "
            "minimum 2 required for B4"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.UNAVAILABLE,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if prop_name == "B5" and len(eligible_volatility_securities) < 2:
        reason = (
            f"insufficient_eligible_securities: only "
            f"{len(eligible_volatility_securities)} securities have valid "
            "volatility; minimum 2 required for B5"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.UNAVAILABLE,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    # 9. All checks passed: Candidate strategy is ELIGIBLE
    assert prop_name is not None
    reason = (
        f"eligible: proposed strategy {prop_name} satisfied all evidence, "
        f"history ({len(eval_universe)} names >= {min_required_sessions} sessions), "
        "portfolio safety, and fixed universe completeness requirements"
    )
    return _build_result(
        status=PreflightStatus.ELIGIBLE,
        reason=reason,
        proposed_strategy=prop_name,
        current_strategy=curr_name,
        effective_strategy=prop_name,
        is_tradeable=True,
        hold_incumbent=False,
        requires_containment=False,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=eval_universe,
        portfolio_state_hash=port_state_hash,
        account_id=account_id,
        mandate=mandate,
    )


def _resolve_non_eligible_outcome(
    *,
    status: PreflightStatus,
    reason: str,
    prop_name: str | None = None,
    curr_name: str | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    current_portfolio_state: PortfolioStateV2 | None,
    allow_incumbent_continuation: bool,
    account_id: str | None = None,
    mandate: str | None = None,
    portfolio_state_hash: str | None = None,
    open_orders: Sequence[object] | None = None,
    mandate_verified: bool = True,
    risk_verified: bool = True,
) -> Stage1SwitchPreflightResult:
    """Resolve whether an unavailable/rejected switch can safely hold incumbent."""
    candidate_strategy = prop_name if prop_name is not None else "UNKNOWN"
    session_key = decision_context.session_key if decision_context else None
    decision_cutoff = decision_context.decision_cutoff if decision_context else None
    cohort_hash = (
        getattr(decision_context, "cohort_hash", None) if decision_context else None
    )
    admitted_universe = (
        get_admitted_securities(decision_context) if decision_context else ()
    )

    if status == PreflightStatus.INDETERMINATE_SAFETY:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    if not allow_incumbent_continuation:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; incumbent continuation disabled",
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    # Missing portfolio state cannot grant safe hold (fail closed)
    if current_portfolio_state is None:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=(
                f"{reason}; missing authoritative portfolio state, "
                "cannot establish safe hold"
            ),
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=None,
            account_id=account_id,
            mandate=mandate,
        )

    # Verify incumbent strategy identity
    if curr_name is None or curr_name not in {"B3", "B4", "B5"}:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=(
                f"{reason}; unknown or unadmitted incumbent strategy {curr_name!r}, "
                "cannot establish safe hold"
            ),
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    # Verify portfolio state sanity for safe hold
    if current_portfolio_state.cash_balance < Decimal("0"):
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; incumbent portfolio cash is negative",
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    for h in current_portfolio_state.holdings:
        if h.basis_status == "indeterminate":
            return _build_result(
                status=PreflightStatus.INDETERMINATE_SAFETY,
                reason=(
                    f"{reason}; incumbent portfolio holding {h.security_id} "
                    "has indeterminate basis"
                ),
                proposed_strategy=candidate_strategy,
                current_strategy=curr_name,
                effective_strategy=None,
                is_tradeable=False,
                hold_incumbent=False,
                requires_containment=True,
                session_key=session_key,
                decision_cutoff=decision_cutoff,
                cohort_hash=cohort_hash,
                admitted_universe=admitted_universe,
                portfolio_state_hash=portfolio_state_hash,
                account_id=account_id,
                mandate=mandate,
            )

    if (
        decision_context is not None
        and current_portfolio_state.session_key != decision_context.session_key
    ):
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=(
                f"{reason}; portfolio session does not match decision context session"
            ),
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    if decision_context is not None and abs(
        current_portfolio_state.net_asset_value - decision_context.portfolio_nav
    ) > Decimal("0.01"):
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; portfolio NAV does not match decision context NAV",
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    if open_orders:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; pending orders present on incumbent portfolio",
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    if not mandate_verified or not risk_verified:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; incumbent mandate or risk unverified",
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    # Safe hold of incumbent verified
    return _build_result(
        status=status,
        reason=f"{reason}; incumbent strategy {curr_name} safely retained",
        proposed_strategy=candidate_strategy,
        current_strategy=curr_name,
        effective_strategy=curr_name,
        is_tradeable=False,
        hold_incumbent=True,
        requires_containment=False,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=admitted_universe,
        portfolio_state_hash=portfolio_state_hash,
        account_id=account_id,
        mandate=mandate,
    )
