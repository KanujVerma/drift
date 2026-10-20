"""Pure synthetic Stage 1 admission before complete-target staging (#423).

Consumes K0's accepted local API at 288fc74147de7ad6327062e0e74ad953adf2ef9b.
The caller supplies trusted, current account/mandate/risk/source evidence.
Neither a verdict hash nor caller-supplied verification flags authenticate that
evidence. This module does not wire the engine, generate orders, mutate accounts,
estimate costs, qualify data, or authorize trading. Later integration must make
this boundary mandatory and bind its inputs to authoritative producer receipts.

Inputs are detached before verification. Concrete list/tuple collections and
dict mappings are accepted; executable collection subclasses are refused.
The returned targets are a staging result, never orders or evidence of fills.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from drift.analysis.analytical_returns import CorporateActionAdjustment
from drift.domain.common import UUID7, FrozenModel, SHA256Hash
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
    stage_exploratory_decision_targets,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
    stage_decision_targets,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.loop.stage1_switch_preflight import (
    PreflightStatus,
    Stage1SwitchPreflightResult,
    evaluate_stage1_switch_preflight,
    verify_stage1_switch_preflight_result,
)


class AdmissionStatus(StrEnum):
    ADMITTED = "admitted"
    REFUSED = "refused"
    CONTAINMENT = "containment"


@dataclass(frozen=True)
class Stage1SwitchAdmission:
    """Ephemeral local decision; only ADMITTED carries staged targets."""

    status: AdmissionStatus
    reason: str
    hold_incumbent: bool = False
    staged_targets: tuple[SecurityTargetPositionV1, ...] = ()

    @property
    def requires_containment(self) -> bool:
        return self.status == AdmissionStatus.CONTAINMENT


def _rebuild[Model: FrozenModel](value: Model, expected: type[Model]) -> Model:
    if type(value) is not expected:
        raise ValueError(f"expected exact {expected.__name__}")
    # JSON roundtrip removes caller-defined leaf equality and reruns validators,
    # including for model_copy/model_construct inputs. Do not trust frozen alone.
    return expected.model_validate_json(value.model_dump_json())


def _sequence[Item](value: Sequence[Item], name: str) -> tuple[Item, ...]:
    if type(value) not in (list, tuple):
        raise ValueError(f"{name} requires a concrete list or tuple")
    return tuple(value)


def _strategy(value: str | StrategyReference | None) -> str | StrategyReference | None:
    if value is None or type(value) is str:
        return value
    if isinstance(value, StrategyReference):
        return _rebuild(value, StrategyReference)
    raise ValueError("unsupported strategy representation")


def _manifest(
    value: Mapping[UUID7, str] | Mapping[str, UUID7] | None,
) -> dict[UUID7, str]:
    if type(value) is not dict:
        raise ValueError("universe manifest requires a concrete dict")
    normalized: dict[UUID7, str] = {}
    symbols: set[str] = set()
    for key, item in value.items():
        security: UUID7
        symbol: str
        if type(key) is UUID and type(item) is str:
            security, symbol = key, item.upper()
        elif type(key) is str and type(item) is UUID:
            security, symbol = item, key.upper()
        else:
            raise ValueError("invalid universe manifest entries")
        if security in normalized or symbol in symbols:
            raise ValueError("duplicate or contradictory universe manifest identity")
        normalized[security] = symbol
        symbols.add(symbol)
    return normalized


def _adjustments(
    value: Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None,
) -> dict[UUID7, tuple[CorporateActionAdjustment, ...]] | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError("adjustments require a concrete dict")
    copied: dict[UUID7, tuple[CorporateActionAdjustment, ...]] = {}
    for security, adjustments in value.items():
        if type(security) is not UUID:
            raise ValueError("adjustment security must be UUID")
        entries = _sequence(adjustments, "adjustments")
        for entry in entries:
            if (
                type(entry) is not CorporateActionAdjustment
                or type(entry.effective_date) is not date
                or type(entry.split_ratio) is not Decimal
                or type(entry.cash_distribution) is not Decimal
                or type(entry.effect_hash) is not str
            ):
                raise ValueError("invalid adjustment representation")
        copied[security] = entries
    return copied


def admit_stage1_switch(
    *,
    preflight: Stage1SwitchPreflightResult,
    intent: StrategyDecisionIntentV1 | None,
    proposed_strategy: str | StrategyReference,
    current_strategy: str | StrategyReference | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    current_portfolio_state: PortfolioStateV2 | None,
    required_universe: Sequence[UUID7],
    expected_universe_hash: SHA256Hash,
    universe_manifest: Mapping[UUID7, str] | Mapping[str, UUID7] | None,
    account_id: str,
    mandate: str,
    open_orders: Sequence[object] | None,
    mandate_verified: bool | None,
    risk_verified: bool | None,
    completed_sessions: Sequence[date | SessionKeyV1] | None,
    adjustments_by_security: (
        Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None
    ) = None,
) -> Stage1SwitchAdmission:
    """Refuse before staging unless K0, current evidence and intent all agree.

    Missing, stale, contradictory or unsafe evidence requests containment without
    claiming a safe hold. A verified noneligible verdict preserves the incumbent
    only when a fresh producer evaluation independently permits continuation.
    Even an eligible verdict cannot authorize an empty or all-zero Stage 1
    target set. A nonempty positive selection retains ordinary complete-target
    exits for omitted holdings through the existing lane-specific stager.
    """
    try:
        verdict = _rebuild(preflight, Stage1SwitchPreflightResult)
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1
        if type(decision_context) is StrategyDecisionContextV1:
            context = _rebuild(decision_context, StrategyDecisionContextV1)
        elif type(decision_context) is ExploratoryStrategyDecisionContextV1:
            context = _rebuild(decision_context, ExploratoryStrategyDecisionContextV1)
        else:
            raise ValueError("missing or unsupported decision context")
        if current_portfolio_state is None:
            raise ValueError("missing current portfolio state")
        portfolio = _rebuild(current_portfolio_state, PortfolioStateV2)
        universe = _sequence(required_universe, "required_universe")
        if not universe or any(type(security) is not UUID for security in universe):
            raise ValueError("required universe must contain UUIDs")
        if len(set(universe)) != len(universe):
            raise ValueError("duplicate required universe identity")
        # K0 returns a byte-sorted universe; its verifier expects that exact order.
        universe = tuple(sorted(universe, key=lambda security: security.bytes))
        if any(
            type(value) is not str
            for value in (account_id, mandate, expected_universe_hash)
        ):
            raise ValueError("account, mandate and cohort identifiers must be strings")
        manifest = _manifest(universe_manifest)
        orders = None if open_orders is None else _sequence(open_orders, "open_orders")
        sessions = (
            None
            if completed_sessions is None
            else _sequence(completed_sessions, "completed_sessions")
        )
        if sessions is not None and any(
            type(session) not in (date, SessionKeyV1) for session in sessions
        ):
            raise ValueError("invalid completed-session representation")
        proposed = _strategy(proposed_strategy)
        if proposed is None:
            raise ValueError("missing proposed strategy")
        incumbent = _strategy(current_strategy)
        verify_stage1_switch_preflight_result(
            verdict,
            expected_account_id=account_id,
            expected_mandate=mandate,
            expected_session_key=context.session_key,
            expected_decision_cutoff=context.decision_cutoff,
            expected_cohort_hash=expected_universe_hash,
            expected_universe=universe,
            current_portfolio_state=portfolio,
        )
        fresh = evaluate_stage1_switch_preflight(
            proposed_strategy=proposed,
            current_strategy=incumbent,
            decision_context=context,
            current_portfolio_state=portfolio,
            required_universe=universe,
            expected_universe_hash=expected_universe_hash,
            universe_manifest=manifest,
            account_id=account_id,
            mandate=mandate,
            open_orders=orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
            completed_sessions=sessions,
            adjustments_by_security=_adjustments(adjustments_by_security),
        )
        if fresh.requires_containment:
            raise ValueError(f"current evidence requires containment: {fresh.reason}")
        if fresh.preflight_hash != verdict.preflight_hash:
            raise ValueError("preflight differs from current producer evaluation")
    except (ValueError, TypeError, AttributeError, ArithmeticError) as error:
        return Stage1SwitchAdmission(AdmissionStatus.CONTAINMENT, str(error))

    if fresh.status != PreflightStatus.ELIGIBLE:
        return Stage1SwitchAdmission(
            AdmissionStatus.REFUSED, fresh.reason, hold_incumbent=fresh.hold_incumbent
        )

    try:
        if type(intent) is not StrategyDecisionIntentV1:
            raise ValueError("eligible selection requires an explicit target intent")
        targets = _sequence(intent.targets, "targets")
        if not targets:
            raise ValueError("empty target intent cannot select a Stage 1 strategy")
        if any(
            type(target) is not SecurityTargetPositionV1
            or type(target.target_quantity) is not int
            for target in targets
        ):
            raise ValueError("target quantities must be exact whole-share integers")
        checked_intent = _rebuild(intent, StrategyDecisionIntentV1)
        if not any(target.target_quantity > 0 for target in checked_intent.targets):
            raise ValueError("Stage 1 cannot select an all-cash target")
        if isinstance(context, StrategyDecisionContextV1):
            staged = stage_decision_targets(checked_intent, context)
        else:
            staged = stage_exploratory_decision_targets(checked_intent, context)
    except (ValueError, TypeError, AttributeError) as error:
        return Stage1SwitchAdmission(AdmissionStatus.REFUSED, str(error))

    return Stage1SwitchAdmission(
        AdmissionStatus.ADMITTED, "verified synthetic selection", staged_targets=staged
    )
