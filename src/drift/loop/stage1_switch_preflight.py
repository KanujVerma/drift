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
from typing import Literal

from drift.analysis.analytical_returns import CorporateActionAdjustment
from drift.baselines.common import (
    extract_current_close_price,
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

B3_STRATEGY_NAMES = frozenset(
    {"b3", "b3_monthly_equal_weight_rebalance", "b3_equal_weight"}
)
B4_STRATEGY_NAMES = frozenset({"b4", "b4_momentum"})
B5_STRATEGY_NAMES = frozenset({"b5", "b5_low_volatility"})

STAGE1_ADMITTED_STRATEGIES = B3_STRATEGY_NAMES | B4_STRATEGY_NAMES | B5_STRATEGY_NAMES

B3_MIN_SESSIONS = 1
B4_MIN_SESSIONS = 253
B5_MIN_SESSIONS = 61


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
    preflight_hash: SHA256Hash


def _canonical_strategy_name(strategy: str | StrategyReference | None) -> str | None:
    if strategy is None:
        return None
    if isinstance(strategy, StrategyReference):
        # Extract name from artifact location or string representation
        loc = strategy.artifact_reference.location
        if "b3" in loc:
            return "B3"
        if "b4" in loc:
            return "B4"
        if "b5" in loc:
            return "B5"
        return str(strategy.strategy_id)
    norm = strategy.strip().lower()
    if norm in B3_STRATEGY_NAMES or norm == "b3":
        return "B3"
    if norm in B4_STRATEGY_NAMES or norm == "b4":
        return "B4"
    if norm in B5_STRATEGY_NAMES or norm == "b5":
        return "B5"
    if norm == "abstain":
        return "ABSTAIN"
    return strategy.strip()


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


def evaluate_stage1_switch_preflight(
    *,
    proposed_strategy: str | StrategyReference,
    current_strategy: str | StrategyReference | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    required_universe: Sequence[UUID7] | None = None,
    current_portfolio_state: PortfolioStateV2 | None = None,
    allow_incumbent_continuation: bool = True,
    adjustments_by_security: (
        Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None
    ) = None,
) -> Stage1SwitchPreflightResult:
    """Evaluate whether a proposed switch is eligible for Stage 1 target staging.

    Distinguishes:
    - ELIGIBLE: Proposed strategy has sufficient, valid evidence to compute targets.
    - UNAVAILABLE: Required data/history is missing; trade generation is blocked.
    - ABSTAIN: Deliberate hold; incumbent strategy continues if safe.
    - REJECTED: Proposed strategy or configuration fails deterministic validation.
    - INDETERMINATE_SAFETY: Portfolio or risk state is unknown; containment needed.
    """
    prop_name = _canonical_strategy_name(proposed_strategy) or "UNKNOWN"
    curr_name = _canonical_strategy_name(current_strategy)

    # 1. Reject invalid, malformed, or all-cash proposed strategies
    if prop_name.lower() in {
        "cash",
        "b0",
        "b0_cash",
        "all_cash",
        "b1",
        "b2",
    } or prop_name not in {"B3", "B4", "B5", "ABSTAIN"}:
        reason = (
            f"unsupported_stage1_strategy: proposed strategy {proposed_strategy!r} "
            "is not an admitted Stage 1 candidate (admitted: B3, B4, B5, ABSTAIN)"
        )
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.REJECTED,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
        )

    # 2. Context presence and sanity checks
    if decision_context is None:
        reason = "missing_decision_context: decision context is None"
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.UNAVAILABLE,
            reason=reason,
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=None,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
        )

    session_key = decision_context.session_key
    decision_cutoff = decision_context.decision_cutoff
    cohort_hash = getattr(decision_context, "cohort_hash", None)
    context_cohort = get_admitted_securities(decision_context)

    # Check portfolio solvency / NAV sanity on context
    if decision_context.portfolio_nav <= Decimal("0"):
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason="non_positive_nav: context portfolio_nav is non-positive",
            proposed_strategy=prop_name,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=context_cohort,
        )

    # 3. Deliberate Abstain / Hold Request
    if prop_name == "ABSTAIN":
        return _resolve_non_eligible_outcome(
            status=PreflightStatus.ABSTAIN,
            reason="deliberate_abstain: selector requested hold of incumbent strategy",
            prop_name=prop_name,
            curr_name=curr_name,
            decision_context=decision_context,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
        )

    # 4. Universe Completeness Verification
    cohort_set = set(context_cohort)
    if required_universe is not None:
        req_set = set(required_universe)
        if not req_set.issubset(cohort_set):
            missing_uuids = sorted(str(u) for u in (req_set - cohort_set))
            reason = (
                f"incomplete_admitted_universe: context admitted_cohort missing "
                f"required securities: {missing_uuids}"
            )
            return _resolve_non_eligible_outcome(
                status=PreflightStatus.UNAVAILABLE,
                reason=reason,
                prop_name=prop_name,
                curr_name=curr_name,
                decision_context=decision_context,
                current_portfolio_state=current_portfolio_state,
                allow_incumbent_continuation=allow_incumbent_continuation,
            )
        eval_universe = tuple(sorted(req_set, key=lambda u: u.bytes))
    else:
        eval_universe = context_cohort

    # 5. Determine Historical Session Minimum
    if prop_name == "B3":
        min_required_sessions = B3_MIN_SESSIONS
    elif prop_name == "B4":
        min_required_sessions = B4_MIN_SESSIONS
    elif prop_name == "B5":
        min_required_sessions = B5_MIN_SESSIONS
    else:
        min_required_sessions = 1

    # 6. Evaluate Evidence for Each Admitted Security
    cutoff_date = session_key.local_date
    for sec_id in eval_universe:
        raw_obs = _get_raw_observations(decision_context, sec_id)
        # Check raw observations for future dates or duplicates
        seen_raw_sessions = set()
        for raw_item in raw_obs:
            raw_s_key = getattr(raw_item, "source_session", None) or getattr(
                raw_item, "session_key", None
            )
            if raw_s_key is None:
                continue
            if raw_s_key.local_date > cutoff_date:
                reason = (
                    f"future_observation_detected: observation for security {sec_id} "
                    f"dated {raw_s_key.local_date} exceeds cutoff {cutoff_date}"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.UNAVAILABLE,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                )
            if raw_s_key in seen_raw_sessions:
                reason = (
                    f"duplicate_session_observation: security {sec_id} has duplicate "
                    f"observation for session {raw_s_key}"
                )
                return _resolve_non_eligible_outcome(
                    status=PreflightStatus.REJECTED,
                    reason=reason,
                    prop_name=prop_name,
                    curr_name=curr_name,
                    decision_context=decision_context,
                    current_portfolio_state=current_portfolio_state,
                    allow_incumbent_continuation=allow_incumbent_continuation,
                )
            seen_raw_sessions.add(raw_s_key)

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
            )

        # Validate causality, duplicates, and price sanity
        seen_sessions = set()
        prev_date = None
        for obs in history:
            s_date = obs.session_key.local_date
            # Causality check: observations cannot be after decision cutoff session
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
                )

            # Duplicate session check
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
                )
            seen_sessions.add(obs.session_key)

            # Strict chronological order check
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
                )
            prev_date = s_date

            # Price validity: must be positive and finite Decimal
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
                )

        # Check current close price presence
        curr_price = extract_current_close_price(decision_context, sec_id)
        if (
            curr_price is None
            or not curr_price.is_finite()
            or curr_price <= Decimal("0")
        ):
            reason = (
                f"missing_current_close_price: security {sec_id} lacks valid current "
                f"closing mark at decision cutoff {decision_cutoff}"
            )
            return _resolve_non_eligible_outcome(
                status=PreflightStatus.UNAVAILABLE,
                reason=reason,
                prop_name=prop_name,
                curr_name=curr_name,
                decision_context=decision_context,
                current_portfolio_state=current_portfolio_state,
                allow_incumbent_continuation=allow_incumbent_continuation,
            )

    # 7. All checks passed: Candidate strategy is ELIGIBLE
    reason = (
        f"eligible: proposed strategy {prop_name} satisfied all evidence, "
        f"history ({len(eval_universe)} names >= {min_required_sessions} sessions), "
        "and universe completeness requirements"
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
    )


def _resolve_non_eligible_outcome(
    *,
    status: PreflightStatus,
    reason: str,
    prop_name: str,
    curr_name: str | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    current_portfolio_state: PortfolioStateV2 | None,
    allow_incumbent_continuation: bool,
) -> Stage1SwitchPreflightResult:
    """Resolve whether an unavailable/rejected switch can safely hold."""
    session_key = decision_context.session_key if decision_context else None
    decision_cutoff = decision_context.decision_cutoff if decision_context else None
    cohort_hash = getattr(decision_context, "cohort_hash", None) if decision_context else None
    admitted_universe = (
        get_admitted_securities(decision_context) if decision_context else ()
    )

    # Check whether incumbent continuation is permissible
    if not allow_incumbent_continuation:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; incumbent continuation disabled",
            proposed_strategy=prop_name,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
        )

    # Verify incumbent strategy identity
    if curr_name is None or curr_name not in {"B3", "B4", "B5"}:
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=(
                f"{reason}; unknown or unadmitted incumbent strategy {curr_name!r}, "
                "cannot establish safe hold"
            ),
            proposed_strategy=prop_name,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
        )

    # Verify portfolio state sanity for safe hold
    if current_portfolio_state is not None:
        if current_portfolio_state.cash_balance < Decimal("0"):
            return _build_result(
                status=PreflightStatus.INDETERMINATE_SAFETY,
                reason=f"{reason}; incumbent portfolio cash is negative",
                proposed_strategy=prop_name,
                current_strategy=curr_name,
                effective_strategy=None,
                is_tradeable=False,
                hold_incumbent=False,
                requires_containment=True,
                session_key=session_key,
                decision_cutoff=decision_cutoff,
                cohort_hash=cohort_hash,
                admitted_universe=admitted_universe,
            )
        # Check holdings basis status
        for h in current_portfolio_state.holdings:
            if h.basis_status == "indeterminate":
                return _build_result(
                    status=PreflightStatus.INDETERMINATE_SAFETY,
                    reason=(
                        f"{reason}; incumbent portfolio holding {h.security_id} "
                        "has indeterminate basis"
                    ),
                    proposed_strategy=prop_name,
                    current_strategy=curr_name,
                    effective_strategy=None,
                    is_tradeable=False,
                    hold_incumbent=False,
                    requires_containment=True,
                    session_key=session_key,
                    decision_cutoff=decision_cutoff,
                    cohort_hash=cohort_hash,
                    admitted_universe=admitted_universe,
                )
    elif decision_context is not None:
        if decision_context.portfolio_nav <= Decimal("0"):
            return _build_result(
                status=PreflightStatus.INDETERMINATE_SAFETY,
                reason=f"{reason}; context NAV is non-positive",
                proposed_strategy=prop_name,
                current_strategy=curr_name,
                effective_strategy=None,
                is_tradeable=False,
                hold_incumbent=False,
                requires_containment=True,
                session_key=session_key,
                decision_cutoff=decision_cutoff,
                cohort_hash=cohort_hash,
                admitted_universe=admitted_universe,
            )
    else:
        # Neither portfolio state nor decision context available
        return _build_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; missing both portfolio state and decision context",
            proposed_strategy=prop_name,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
        )

    # Safe hold of incumbent verified
    return _build_result(
        status=status,
        reason=f"{reason}; incumbent strategy {curr_name} safely retained",
        proposed_strategy=prop_name,
        current_strategy=curr_name,
        effective_strategy=curr_name,
        is_tradeable=False,
        hold_incumbent=True,
        requires_containment=False,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=admitted_universe,
    )
