"""Bounded sell-only correction previews against the original account kernel.

This module never commits an account. The evaluator supplies its original
current-session listings and open prices, and must revalidate the returned
targets at the execution boundary. Input hashes bind those supplied originals;
they do not authenticate a source or grant execution permission.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.evaluator_clock import EvaluationSessionV1, SessionClockV1
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_execution import (
    AtomicRebalanceCommitError,
    IndeterminateExecutionError,
    ListingOpenPriceV1,
    RebalanceOutcomeV2,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateBasisError,
    PortfolioStateV2,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.securities import ListingV1
from drift.domain.synthetic_execution import (
    ProtectiveCorrectionPolicyV1 as ProtectiveCorrectionPolicyV1,
)
from drift.evaluator.execution import AtomicRebalanceEngine
from drift.loop.stage1_controlled_contracts import SyntheticMandateV1, exact_decimal
from drift.serialization.canonical import canonical_json, content_hash


class ProtectiveCorrectionPlanV1(FrozenModel):
    """A reproducible preview, never evidence that protective trades occurred."""

    schema_version: Literal["drift-protective-plan/1"] = "drift-protective-plan/1"
    status: Literal["READY", "NOT_REQUIRED", "UNRESOLVED"]
    reason: NonBlankStr
    inputs_hash: SHA256Hash
    state_hash: SHA256Hash
    policy_hash: SHA256Hash
    mandate_hash: SHA256Hash
    execution_session_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    session_clock_hash: SHA256Hash
    targets: tuple[SecurityTargetPositionV1, ...]
    outcome: RebalanceOutcomeV2 | None
    before_open_nav: Decimal | None
    projected_open_nav: Decimal | None
    preview_evaluations: int = Field(strict=True, ge=0, le=4096)
    initial_breaches: tuple[NonBlankStr, ...]
    final_breaches: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        for nav in (self.before_open_nav, self.projected_open_nav):
            if nav is not None and not nav.is_finite():
                raise ValueError("CORRECTION_NONFINITE_NAV")
        if self.status != "READY":
            if self.targets or self.outcome is not None:
                raise ValueError("CORRECTION_UNREADY_EXECUTABLE_PLAN")
            return self
        outcome = self.outcome
        ids = tuple(target.security_id.bytes for target in self.targets)
        if (
            not ids
            or ids != tuple(sorted(set(ids)))
            or outcome is None
            or outcome.classification != "executed"
            or not outcome.committed_fills
            or any(fill.side != "sell" for fill in outcome.committed_fills)
            or not self.initial_breaches
            or self.final_breaches
            or not self.preview_evaluations
            or self.before_open_nav is None
            or self.before_open_nav <= 0
            or self.projected_open_nav is None
            or self.projected_open_nav <= 0
        ):
            raise ValueError("CORRECTION_INVALID_READY_PLAN")
        target_quantities = {
            target.security_id: target.target_quantity for target in self.targets
        }
        actual_quantities = {
            holding.security_id: holding.quantity for holding in outcome.state.holdings
        }
        if {
            sid: qty for sid, qty in target_quantities.items() if qty
        } != actual_quantities:
            raise ValueError("CORRECTION_TARGET_STATE_MISMATCH")
        return self

    @property
    def plan_hash(self) -> str:
        return content_hash(self)


@dataclass(frozen=True)
class _Exposure:
    nav: Fraction
    securities: tuple[UUID, ...]
    classes: tuple[str, ...]
    gross: bool

    @property
    def breaches(self) -> tuple[str, ...]:
        return (
            tuple(f"SECURITY_CAP:{security}" for security in self.securities)
            + tuple(f"CLASS_CAP:{asset_class}" for asset_class in self.classes)
            + (("GROSS_CAP",) if self.gross else ())
        )


def _exposure(
    *,
    mandate: SyntheticMandateV1,
    quantities: Mapping[UUID, int],
    prices: Mapping[UUID, Fraction],
    cash: Decimal,
    pending_claims: Decimal,
) -> _Exposure:
    values = {security: prices[security] * qty for security, qty in quantities.items()}
    gross = sum(values.values(), Fraction(0))
    nav = Fraction(cash) + Fraction(pending_claims) + gross
    classes: dict[str, Fraction] = {}
    securities: list[UUID] = []
    for rule in mandate.securities:
        value = values.get(rule.security_id, Fraction(0))
        if value > nav * Fraction(rule.maximum_fraction):
            securities.append(rule.security_id)
        classes[rule.asset_class] = classes.get(rule.asset_class, Fraction(0)) + value
    return _Exposure(
        nav=nav,
        securities=tuple(securities),
        classes=tuple(
            rule.asset_class
            for rule in mandate.classes
            if classes.get(rule.asset_class, Fraction(0))
            > nav * Fraction(rule.maximum_fraction)
        ),
        gross=gross > nav * Fraction(mandate.maximum_gross_fraction),
    )


def _next_security(
    *,
    exposure: _Exposure,
    order: tuple[UUID, ...],
    quantities: Mapping[UUID, int],
    asset_classes: Mapping[UUID, str],
    already_selling: set[UUID],
) -> UUID | None:
    """Individual cap, then class name, then gross; original notional breaks ties."""
    available = tuple(security for security in order if quantities[security] > 0)
    for security in available:
        if security in exposure.securities:
            return security
    for asset_class in exposure.classes:
        for security in available:
            if asset_classes[security] == asset_class:
                return security
    if exposure.gross and available:
        return available[0]
    # A fixed fee can leave the first correcting sale unfunded. More shares
    # from an already selected position may fund it without a new order/fee.
    return next(
        (security for security in available if security in already_selling), None
    )


def plan_protective_correction(
    *,
    policy: ProtectiveCorrectionPolicyV1,
    mandate: SyntheticMandateV1,
    state: PortfolioStateV2,
    execution_session: EvaluationSessionV1,
    open_prices: Mapping[UUID, ListingOpenPriceV1],
    execution_listings: Mapping[UUID, ListingV1],
    cost_model: EvaluationCostModelV1,
    session_clock: SessionClockV1,
) -> ProtectiveCorrectionPlanV1:
    """Find the first compliant cumulative whole-share trim on a fixed path.

    Security breaches take priority over class breaches, then gross exposure.
    Class names are canonical; within a constraint, descending *original*
    open notional and then UUID bytes select the position to reduce. Each
    candidate reduces one share, reprices the complete cumulative sell plan
    from the unchanged original account, and rechecks every cap using exact
    rational comparisons against post-cost open NAV. Fixed fees are therefore
    charged once per final order, not once per preview. This bounded policy
    is deterministic, not a claim of globally optimal portfolio liquidation.

    Current-session price origin/freshness is the evaluator's responsibility:
    ListingOpenPriceV1 has no independent timestamp or source authority. This
    boundary verifies the original clock/session, complete held coverage and
    matching listing/venue, and never substitutes a stale or missing quote.
    """
    # Unvalidated model_construct can bypass otherwise frozen contracts. A
    # canonical round-trip reruns nested constraints and content-hash checks.
    policy = ProtectiveCorrectionPolicyV1.model_validate_json(canonical_json(policy))
    mandate = SyntheticMandateV1.model_validate_json(canonical_json(mandate))
    state = PortfolioStateV2.model_validate_json(canonical_json(state))
    execution_session = EvaluationSessionV1.model_validate_json(
        canonical_json(execution_session)
    )
    cost_model = EvaluationCostModelV1.model_validate_json(canonical_json(cost_model))
    session_clock = SessionClockV1.model_validate_json(canonical_json(session_clock))
    open_prices = {
        security: ListingOpenPriceV1.model_validate_json(canonical_json(price))
        for security, price in open_prices.items()
    }
    execution_listings = {
        security: ListingV1.model_validate_json(canonical_json(listing))
        for security, listing in execution_listings.items()
    }
    inputs_hash = content_hash(
        {
            "policy": policy,
            "mandate": mandate,
            "state": state,
            "execution_session": execution_session,
            "open_prices": {str(key): value for key, value in open_prices.items()},
            "execution_listings": {
                str(key): value for key, value in execution_listings.items()
            },
            "cost_model": cost_model,
            "session_clock": session_clock,
        }
    )
    initial: _Exposure | None = None
    current: _Exposure | None = None
    evaluations = 0

    def result(
        status: Literal["READY", "NOT_REQUIRED", "UNRESOLVED"],
        reason: str,
        *,
        targets: tuple[SecurityTargetPositionV1, ...] = (),
        outcome: RebalanceOutcomeV2 | None = None,
    ) -> ProtectiveCorrectionPlanV1:
        return ProtectiveCorrectionPlanV1(
            status=status,
            reason=reason,
            inputs_hash=inputs_hash,
            state_hash=content_hash(state),
            policy_hash=policy.policy_hash,
            mandate_hash=mandate.policy_hash,
            execution_session_hash=execution_session.session_hash,
            cost_model_hash=cost_model.cost_model_hash,
            session_clock_hash=session_clock.clock_hash,
            targets=targets,
            outcome=outcome,
            before_open_nav=exact_decimal(initial.nav) if initial is not None else None,
            projected_open_nav=exact_decimal(current.nav)
            if current is not None
            else None,
            preview_evaluations=evaluations,
            initial_breaches=initial.breaches if initial is not None else (),
            final_breaches=current.breaches if current is not None else (),
        )

    if not policy.enabled:
        return result("UNRESOLVED", "CORRECTION_DISABLED")
    if mandate.execution_knowledge != "RESOLVED":
        return result("UNRESOLVED", "CORRECTION_EXECUTION_UNRESOLVED")
    if (
        state.session_key != execution_session.session_key
        or execution_session not in session_clock.sessions
        or state.is_marked
    ):
        return result("UNRESOLVED", "CORRECTION_SESSION_MISMATCH")
    quantities = {holding.security_id: holding.quantity for holding in state.holdings}
    authorized = {rule.security_id for rule in mandate.securities}
    if not set(quantities) <= authorized:
        return result("UNRESOLVED", "CORRECTION_FOREIGN_SECURITY")
    if (
        not set(quantities) <= set(open_prices)
        or set(open_prices) != set(execution_listings)
        or not set(open_prices) <= authorized
    ):
        return result("UNRESOLVED", "CORRECTION_EVIDENCE_COVERAGE")
    if any(
        price.listing_id != execution_listings[security].listing_id
        or price.venue != execution_listings[security].venue
        for security, price in open_prices.items()
    ):
        return result("UNRESOLVED", "CORRECTION_LISTING_MISMATCH")
    prices = {
        security: Fraction(price.unadjusted_open_price)
        for security, price in open_prices.items()
    }
    initial = current = _exposure(
        mandate=mandate,
        quantities=quantities,
        prices=prices,
        cash=state.cash_balance,
        pending_claims=state.pending_claims_value,
    )
    if initial.nav <= 0:
        return result("UNRESOLVED", "CORRECTION_NONPOSITIVE_NAV")
    if not initial.breaches:
        return result("NOT_REQUIRED", "CORRECTION_NOT_REQUIRED")
    if mandate.paused and not policy.allow_while_paused:
        return result("UNRESOLVED", "CORRECTION_PAUSED")
    order = tuple(
        sorted(
            quantities,
            key=lambda security: (
                -quantities[security] * prices[security],
                security.bytes,
            ),
        )
    )
    asset_classes = {rule.security_id: rule.asset_class for rule in mandate.securities}
    engine = AtomicRebalanceEngine(cost_model=cost_model, session_clock=session_clock)
    original_quantities = dict(quantities)
    already_selling: set[UUID] = set()
    while evaluations < policy.maximum_preview_evaluations:
        security = _next_security(
            exposure=current,
            order=order,
            quantities=quantities,
            asset_classes=asset_classes,
            already_selling=already_selling,
        )
        if security is None:
            return result("UNRESOLVED", "CORRECTION_NO_FUNDED_COMPLIANT_PLAN")
        quantities[security] -= 1
        already_selling.add(security)
        turnover_notional = sum(
            (
                (original_quantities[sid] - qty) * prices[sid]
                for sid, qty in quantities.items()
            ),
            Fraction(0),
        )
        if turnover_notional > initial.nav * Fraction(
            mandate.maximum_turnover_fraction
        ):
            return result("UNRESOLVED", "CORRECTION_TURNOVER_CAP")
        targets = tuple(
            SecurityTargetPositionV1(security_id=sid, target_quantity=qty)
            for sid, qty in sorted(quantities.items(), key=lambda item: item[0].bytes)
        )
        evaluations += 1
        try:
            preview = engine.plan(
                state=state,
                staged_targets=targets,
                open_prices=open_prices,
                execution_listings=execution_listings,
            )
            current = _exposure(
                mandate=mandate,
                quantities=quantities,
                prices=prices,
                cash=preview.projected_cash,
                pending_claims=state.pending_claims_value,
            )
            if current.nav <= 0:
                return result("UNRESOLVED", "CORRECTION_NONPOSITIVE_NAV")
            if not preview.is_funded or current.breaches:
                continue
            outcome = engine.execute(state=state, plan=preview)
        except (
            IndeterminateExecutionError,
            IndeterminateBasisError,
            AtomicRebalanceCommitError,
        ):
            return result("UNRESOLVED", "CORRECTION_ACCOUNTING_UNRESOLVED")
        # A ready plan must be established by the original financial kernel,
        # not just the projected-cash arithmetic used while searching.
        current = _exposure(
            mandate=mandate,
            quantities={
                holding.security_id: holding.quantity
                for holding in outcome.state.holdings
            },
            prices=prices,
            cash=outcome.state.cash_balance,
            pending_claims=outcome.state.pending_claims_value,
        )
        if outcome.classification != "executed" or current.nav <= 0 or current.breaches:
            return result("UNRESOLVED", "CORRECTION_ACCOUNTING_UNRESOLVED")
        return result("READY", "CORRECTION_READY", targets=targets, outcome=outcome)
    return result("UNRESOLVED", "CORRECTION_PREVIEW_BUDGET_EXHAUSTED")
