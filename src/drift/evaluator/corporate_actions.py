"""Deterministic corporate-action and economic outcome accounting for M2.

Two entry points bracket a session. ``apply_pre_open_actions`` folds every M1c
occurred effect that becomes effective on this session into holdings, staged
targets, and cash entitlements, before any price is read.
``apply_intrasession_settlements`` converts entitlements into cash only where a
delivered settlement proves the payment.

Three rules run through everything here.

*Proof, not schedule.* A corporate-action terms record is a plan. Only an
occurred effect moves shares, and only a delivered settlement moves cash.

*Exact, not approximate.* Share entitlements are rationals; cash amounts that
have no exact decimal spelling fail closed instead of rounding.

*Fail closed, never default.* Every ambiguity in this module raises
``IndeterminateValuationError``. There is no branch that quietly picks a
plausible answer, because a plausible answer in an accounting kernel is a
silently wrong book.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from drift.domain.common import UUID7, SHA256Hash
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicDateFactV1,
    EconomicSourceKeyV1,
    FractionTreatmentV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
)
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    OccurredEffectV1,
    TermsPayloadV1,
)
from drift.domain.economic_results import EconomicDeliveryGroupV1
from drift.domain.evaluator_corporate_actions import (
    CashInLieuRateV1,
    DueBillRuleV1,
    SecurityEconomicOutcomeV1,
    TieBreak,
    TieBreakingRuleV1,
    boundary_session_date,
    cash_in_lieu_component_id,
    cash_in_lieu_origin,
    exact_decimal,
    exact_entitled_shares,
    ratio_fraction,
    resolve_whole_shares,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PendingCashClaimV1,
    PortfolioStateV1,
    SecurityHoldingV1,
    decimal_context,
    pending_cash_claim_id,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.serialization.canonical import content_hash

ZERO = Decimal("0")

SPLIT_KINDS = frozenset({ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT})
CASH_DISTRIBUTION_KINDS = frozenset(
    {ActionKind.REGULAR_CASH_DIVIDEND, ActionKind.SPECIAL_CASH_DISTRIBUTION}
)
SHARE_ACQUISITION_KINDS = frozenset(
    {ActionKind.STOCK_ACQUISITION, ActionKind.MIXED_ACQUISITION}
)
DUE_BILL_ROLES = frozenset({"due_bill_start", "due_bill_end", "due_bill_redemption"})
ENDED_CLAIM_STATUSES = frozenset({"converted", "extinguished"})

type ClaimIdentity = tuple[str, UUID, ActionKind, str, str]
type TermsIndex = Mapping[EconomicSourceKeyV1, CorporateActionTermsVersionV1]


@dataclass
class _Book:
    """The in-flight working set for one pre-open pass.

    ``opening`` is the pre-open holding set, frozen before any action in this
    pass ran. A source that quotes cash per *pre-action* share is answered
    from ``opening``; one that quotes per *post-action* share is answered from
    ``holdings``. Without both, a dividend declared alongside a split would
    take its share count from whichever record happened to hash first.
    """

    opening: Mapping[UUID, SecurityHoldingV1]
    holdings: dict[UUID, SecurityHoldingV1]
    targets: dict[UUID, SecurityTargetPositionV1]
    claims: dict[ClaimIdentity, PendingCashClaimV1]


@dataclass(frozen=True)
class _EffectContext:
    """One proven occurred effect, already bound to its source identity."""

    record: EconomicEffectVersionV1
    payload: OccurredEffectV1
    occurrence_id: str
    effective_on: date
    terms: TermsIndex

    @property
    def security_id(self) -> UUID7:
        """The economic security the effect acts on."""
        return self.record.security_id

    @property
    def source_id(self) -> str:
        """The source that reported the occurred effect."""
        return self.record.source_key.source_id


def _security_order(security_id: UUID) -> bytes:
    return security_id.bytes


def _require_positioned(state: PortfolioStateV1, session: SessionKeyV1) -> None:
    if state.session_key != session:
        raise ValueError(
            "portfolio state must already be positioned at the current session: "
            f"state holds {state.session_key.local_date}, "
            f"caller named {session.local_date}"
        )


def _ordered_outcomes(
    outcomes: Iterable[SecurityEconomicOutcomeV1],
) -> tuple[SecurityEconomicOutcomeV1, ...]:
    seen: set[UUID] = set()
    for outcome in outcomes:
        if outcome.security_id in seen:
            raise ValueError("economic outcomes must be unique by security")
        seen.add(outcome.security_id)
    return tuple(sorted(outcomes, key=lambda item: _security_order(item.security_id)))


def _unique_targets(
    staged_targets: Iterable[SecurityTargetPositionV1],
) -> dict[UUID, SecurityTargetPositionV1]:
    targets: dict[UUID, SecurityTargetPositionV1] = {}
    for target in staged_targets:
        if target.security_id in targets:
            raise ValueError("staged targets must be unique by security")
        targets[target.security_id] = target
    return targets


def _replace_holdings(
    state: PortfolioStateV1, holdings: Mapping[UUID, SecurityHoldingV1]
) -> PortfolioStateV1:
    """Rebuild state around new holdings, discarding any mark.

    A mark describes the holdings it was taken against. A corporate action
    replaces those holdings, so carrying the mark forward would value shares
    that no longer exist.
    """
    with decimal_context():
        return PortfolioStateV1(
            session_key=state.session_key,
            cash_balance=state.cash_balance,
            holdings=tuple(holdings[key] for key in sorted(holdings, key=str)),
            pending_cash_claims=state.pending_cash_claims,
            settled_claim_ids=state.settled_claim_ids,
            is_marked=False,
            holdings_market_value=ZERO,
            pending_claims_value=state.pending_claims_value,
            net_asset_value=state.cash_balance + state.pending_claims_value,
            realized_gross_pnl=state.realized_gross_pnl,
            realized_net_pnl=state.realized_net_pnl,
            cumulative_transaction_costs=state.cumulative_transaction_costs,
        )


def _date_facts(payload: TermsPayloadV1) -> dict[str, EconomicDateFactV1]:
    return {fact.role: fact for fact in payload.dates}


class CorporateActionProcessor:
    """Applies M1c occurred effects and delivered settlements to a portfolio.

    The three interpretation registries are deliberately constructor
    arguments. They are source readings that a human made and evidenced; the
    processor will not invent one, and an action that needs a missing reading
    fails closed rather than proceeding on a default.
    """

    def __init__(
        self,
        *,
        book_currency_namespace: str,
        book_currency_code: str,
        tie_breaking_rules: Collection[TieBreakingRuleV1] = (),
        due_bill_rules: Collection[DueBillRuleV1] = (),
        cash_in_lieu_rates: Collection[CashInLieuRateV1] = (),
    ) -> None:
        if not book_currency_namespace.strip() or not book_currency_code.strip():
            raise ValueError("a book currency namespace and code are required")
        self._currency = (book_currency_namespace, book_currency_code)
        self._tie_breaks: dict[tuple[str, str], TieBreak] = {}
        for tie_rule in tie_breaking_rules:
            tie_key = (tie_rule.source_rule, tie_rule.evidence_reference.content_hash)
            if self._tie_breaks.get(tie_key, tie_rule.tie_break) != tie_rule.tie_break:
                raise ValueError(
                    "conflicting interpreted tie-breaking rules for one source artifact"
                )
            self._tie_breaks[tie_key] = tie_rule.tie_break
        self._due_bills: dict[tuple[str, UUID, str], DueBillRuleV1] = {}
        for due_rule in due_bill_rules:
            due_key = (due_rule.source_id, due_rule.security_id, due_rule.occurrence_id)
            if self._due_bills.get(due_key, due_rule) != due_rule:
                raise ValueError(
                    "conflicting interpreted due-bill rules for one occurrence"
                )
            self._due_bills[due_key] = due_rule
        self._in_lieu_rates: dict[tuple[str, UUID, str, str], CashInLieuRateV1] = {}
        for rate in cash_in_lieu_rates:
            rate_key = (
                rate.source_id,
                rate.security_id,
                rate.occurrence_id,
                rate.component_id,
            )
            if self._in_lieu_rates.get(rate_key, rate) != rate:
                raise ValueError(
                    "conflicting aggregate-sale cash rates for one component"
                )
            self._in_lieu_rates[rate_key] = rate

    # -- public surface ---------------------------------------------------

    def apply_pre_open_actions(
        self,
        portfolio_state: PortfolioStateV1,
        staged_targets: Iterable[SecurityTargetPositionV1],
        economic_outcomes: Iterable[SecurityEconomicOutcomeV1],
        current_session: SessionKeyV1,
    ) -> tuple[PortfolioStateV1, tuple[SecurityTargetPositionV1, ...]]:
        """Fold this session's proven corporate actions into book and targets.

        Call this exactly once per session. Cash entitlements are idempotent,
        because a claim already pending or already in ``settled_claim_ids`` is
        recognized and skipped. Share mutations are NOT: a second call for the
        same session would split an already split position again.
        ``PortfolioStateV1`` carries no applied-occurrence ledger to make that
        detectable from state alone, and that model is outside this task's
        write-set. The fix is an ``applied_occurrence_ids`` field there.
        """
        _require_positioned(portfolio_state, current_session)
        opening_holdings = {
            holding.security_id: holding for holding in portfolio_state.holdings
        }
        book = _Book(
            opening=opening_holdings,
            holdings=dict(opening_holdings),
            targets=_unique_targets(staged_targets),
            claims={},
        )
        for outcome in _ordered_outcomes(economic_outcomes):
            self._apply_outcome(outcome, book, current_session)
        state = portfolio_state
        if book.holdings != opening_holdings:
            state = _replace_holdings(state, book.holdings)
        state = self._record_claims(state, book.claims)
        targets = tuple(
            sorted(
                book.targets.values(),
                key=lambda item: _security_order(item.security_id),
            )
        )
        return state, targets

    def apply_intrasession_settlements(
        self,
        portfolio_state: PortfolioStateV1,
        economic_outcomes: Iterable[SecurityEconomicOutcomeV1],
        current_session: SessionKeyV1,
    ) -> PortfolioStateV1:
        """Settle only the entitlements a delivered settlement actually proves."""
        _require_positioned(portfolio_state, current_session)
        index = _index_pending_claims(portfolio_state)
        settling: dict[SHA256Hash, PendingCashClaimV1] = {}
        for outcome in _ordered_outcomes(economic_outcomes):
            resolution = outcome.resolution
            if resolution.support_status != "supported":
                if any(
                    claim.security_id == outcome.security_id
                    for claim in portfolio_state.pending_cash_claims
                ):
                    raise IndeterminateValuationError(
                        "economic outcome resolution is not supported evidence "
                        f"for {outcome.security_id}: {resolution.support_status}"
                    )
                continue
            for group in sorted(
                resolution.delivery_groups,
                key=lambda item: (item.source_id, item.native_occurrence_id),
            ):
                settled_on = boundary_session_date(
                    group.settled_time, role="delivered settlement time"
                )
                if settled_on > current_session.local_date:
                    continue
                delivered_cash = sorted(
                    (
                        component
                        for component in group.delivered_components
                        if isinstance(component, CashComponentV1)
                    ),
                    key=lambda item: item.component_id,
                )
                for component in delivered_cash:
                    claim = self._matched_claim(index, group, component)
                    if claim is None:
                        continue
                    self._verify_delivery(claim, component, group, current_session)
                    settling[claim.claim_id] = claim
        if not settling:
            return portfolio_state
        kernel = PortfolioAccountingKernel(portfolio_state)
        kernel.settle_claims(tuple(sorted(settling)))
        return kernel.state

    # -- pre-open internals -----------------------------------------------

    def _apply_outcome(
        self,
        outcome: SecurityEconomicOutcomeV1,
        book: _Book,
        session: SessionKeyV1,
    ) -> None:
        resolution = outcome.resolution
        if resolution.support_status != "supported":
            # An unsupported or indeterminate composition cannot be trusted to
            # say what happened. It only halts a run that is actually exposed
            # to the security, so an unmodellable action elsewhere in the
            # universe does not poison an unrelated book.
            if self._is_exposed(outcome.security_id, book):
                raise IndeterminateValuationError(
                    "economic outcome resolution is not supported evidence for "
                    f"{outcome.security_id}: {resolution.support_status}"
                )
            return
        records = {content_hash(record): record for record in outcome.effect_records}
        terms: TermsIndex = {
            record.source_key: record for record in outcome.terms_records
        }
        applied: set[tuple[str, ActionKind]] = set()
        contexts: list[_EffectContext] = []
        for projection in sorted(
            resolution.effect_projections, key=lambda item: item.source_record_hash
        ):
            if projection.effective_status == "indeterminate":
                raise IndeterminateValuationError(
                    "effect projection effectiveness is indeterminate for "
                    f"{outcome.security_id}"
                )
            if projection.effective_status != "effective":
                continue
            record = records[projection.source_record_hash]
            payload = record.payload
            if not isinstance(payload, OccurredEffectV1):
                raise IndeterminateValuationError(
                    "an effective economic projection requires an occurred "
                    "effect payload"
                )
            occurrence_id = record.occurrence.native_occurrence_id
            if record.occurrence.kind != "identified" or occurrence_id is None:
                raise IndeterminateValuationError(
                    "applying an occurred effect requires an identified source "
                    "occurrence"
                )
            marker = (occurrence_id, payload.action_kind)
            if marker in applied:
                # Two reports of one occurrence would apply one split twice.
                raise IndeterminateValuationError(
                    "economic outcome carries more than one effective report "
                    f"for one occurrence: {occurrence_id}"
                )
            applied.add(marker)
            if payload.consideration_status != "components":
                raise IndeterminateValuationError(
                    "occurred effect does not prove its consideration: "
                    f"{payload.consideration_status}"
                )
            if any(
                isinstance(item, UnsupportedPropertyComponentV1)
                for item in payload.owed_components
            ):
                raise IndeterminateValuationError(
                    "occurred effect carries an unvalued property component"
                )
            contexts.append(
                _EffectContext(
                    record=record,
                    payload=payload,
                    occurrence_id=occurrence_id,
                    effective_on=boundary_session_date(
                        record.effective_time, role="effect effective time"
                    ),
                    terms=terms,
                )
            )
        # Share-mutating actions settle before cash distributions so that a
        # source quoting cash per post-action share is answered against a
        # share count that has already absorbed this session's splits, rather
        # than against whichever record sorted first by hash.
        for context in contexts:
            if context.payload.action_kind not in CASH_DISTRIBUTION_KINDS:
                self._dispatch(context, book, session)
        for context in contexts:
            if context.payload.action_kind in CASH_DISTRIBUTION_KINDS:
                self._dispatch(context, book, session)

    def _dispatch(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        kind = context.payload.action_kind
        if kind in SPLIT_KINDS:
            self._apply_split(context, book, session)
        elif kind == ActionKind.STOCK_DIVIDEND:
            self._apply_stock_dividend(context, book, session)
        elif kind == ActionKind.SPINOFF:
            self._apply_spinoff(context, book, session)
        elif kind in CASH_DISTRIBUTION_KINDS:
            self._apply_cash_distribution(context, book, session)
        elif kind == ActionKind.CASH_ACQUISITION:
            self._apply_cash_acquisition(context, book, session)
        elif kind in SHARE_ACQUISITION_KINDS:
            self._apply_share_acquisition(context, book, session)
        elif kind == ActionKind.LIQUIDATION:
            self._apply_liquidation(context, book, session)
        elif self._is_exposed(context.security_id, book):
            raise IndeterminateValuationError(
                f"corporate action kind {kind.value} has no proven M2 accounting rule"
            )

    def _apply_split(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        # A split is applied exactly on the session it becomes effective. Any
        # other gate would re-apply it on every later session in the window
        # and multiply the position.
        if context.effective_on != session.local_date:
            return
        component = _single_share_component(
            context,
            same_recipient=True,
            meaning="resulting_per_predecessor",
            label="split",
        )
        _require_no_cash(context, "a split")
        tie_break = self._tie_break(component.fraction_treatment)
        holding = book.holdings.get(context.security_id)
        if holding is not None:
            exact = exact_entitled_shares(holding.quantity, component)
            whole, residual = resolve_whole_shares(
                exact, component.fraction_treatment, tie_break=tie_break
            )
            if whole <= 0:
                raise IndeterminateValuationError(
                    "a split would extinguish a held position without proven "
                    "consideration for the remainder"
                )
            book.holdings[context.security_id] = SecurityHoldingV1(
                security_id=context.security_id,
                quantity=whole,
                cost_basis=holding.cost_basis,
            )
            if residual:
                self._stage_cash_in_lieu(context, component, residual, book)
        self._scale_target(context, component, book, tie_break)

    def _apply_stock_dividend(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        if context.effective_on != session.local_date:
            return
        component = _single_share_component(
            context,
            same_recipient=True,
            meaning="additional_per_predecessor",
            label="stock dividend",
        )
        _require_no_cash(context, "a stock dividend")
        holding = book.holdings.get(context.security_id)
        if holding is None:
            return
        tie_break = self._tie_break(component.fraction_treatment)
        exact = exact_entitled_shares(holding.quantity, component)
        whole, residual = resolve_whole_shares(
            exact, component.fraction_treatment, tie_break=tie_break
        )
        book.holdings[context.security_id] = SecurityHoldingV1(
            security_id=context.security_id,
            quantity=whole,
            cost_basis=holding.cost_basis,
        )
        if residual:
            self._stage_cash_in_lieu(context, component, residual, book)

    def _apply_spinoff(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        if context.effective_on != session.local_date:
            return
        component = _single_share_component(
            context,
            same_recipient=False,
            meaning="additional_per_predecessor",
            label="spin-off",
        )
        _require_no_cash(context, "a spin-off")
        holding = book.holdings.get(context.security_id)
        if holding is None:
            return
        child = component.recipient.security_id
        if child is None:  # pragma: no cover - guarded by _single_share_component
            raise IndeterminateValuationError("a spin-off requires a child security")
        tie_break = self._tie_break(component.fraction_treatment)
        exact = exact_entitled_shares(holding.quantity, component)
        whole, residual = resolve_whole_shares(
            exact, component.fraction_treatment, tie_break=tie_break
        )
        if whole > 0:
            # No tax allocation percentage is claimed, so the child enters at a
            # zero basis and the parent keeps its own. Daily marks still value
            # both from their own closing prices.
            existing = book.holdings.get(child)
            with decimal_context():
                basis = ZERO if existing is None else existing.cost_basis
            book.holdings[child] = SecurityHoldingV1(
                security_id=child,
                quantity=whole + (0 if existing is None else existing.quantity),
                cost_basis=basis,
            )
        if residual:
            self._stage_cash_in_lieu(context, component, residual, book)

    def _apply_cash_distribution(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        if (
            context.security_id not in book.opening
            and context.security_id not in book.holdings
        ):
            return
        dates = _date_facts(_terms_payload(context))
        entitlement_on = self._entitlement_session(context, dates)
        # A cash distribution is recognized on the session its entitlement
        # vests, not on the session the effect was reported. That is what lets
        # a due bill defer the entitlement without losing it.
        if entitlement_on != session.local_date:
            return
        if context.effective_on > entitlement_on:
            raise IndeterminateValuationError(
                "a cash entitlement cannot vest before the occurrence that proves it"
            )
        payable_on = _payable_session(dates)
        components = _only_cash_components(context, "a cash distribution")
        for component in components:
            source = (
                book.opening
                if component.unit_basis.share_basis == "predecessor_pre_action"
                else book.holdings
            )
            holding = source.get(context.security_id)
            if holding is None:
                continue
            self._stage_claim(
                context=context,
                component_id=component.component_id,
                quantity=holding.quantity,
                cash_per_share=self._cash_per_share(component, context.security_id),
                entitlement_session=entitlement_on,
                payable_session=payable_on,
                book=book,
            )

    def _apply_cash_acquisition(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        if context.effective_on != session.local_date:
            return
        holding = book.holdings.get(context.security_id)
        if holding is None:
            return
        _require_ended_claim(context)
        components = _only_cash_components(context, "a cash acquisition")
        payable_on = _payable_session(_date_facts(_terms_payload(context)))
        del book.holdings[context.security_id]
        for component in components:
            self._stage_claim(
                context=context,
                component_id=component.component_id,
                quantity=holding.quantity,
                cash_per_share=self._cash_per_share(component, context.security_id),
                entitlement_session=context.effective_on,
                payable_session=payable_on,
                book=book,
            )

    def _apply_share_acquisition(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        if context.effective_on != session.local_date:
            return
        holding = book.holdings.get(context.security_id)
        if holding is None:
            return
        _require_ended_claim(context)
        component = _single_share_component(
            context,
            same_recipient=False,
            meaning="resulting_per_predecessor",
            label="share acquisition",
        )
        cash = _cash_components(context)
        if context.payload.action_kind == ActionKind.MIXED_ACQUISITION and not cash:
            raise IndeterminateValuationError(
                "a mixed acquisition requires proven cash terms alongside its "
                "share terms"
            )
        acquirer = component.recipient.security_id
        if acquirer is None:  # pragma: no cover - guarded above
            raise IndeterminateValuationError(
                "a share acquisition requires an acquirer security"
            )
        tie_break = self._tie_break(component.fraction_treatment)
        exact = exact_entitled_shares(holding.quantity, component)
        whole, residual = resolve_whole_shares(
            exact, component.fraction_treatment, tie_break=tie_break
        )
        if whole <= 0:
            raise IndeterminateValuationError(
                "a share acquisition would extinguish a held position without "
                "proven consideration for the remainder"
            )
        existing = book.holdings.get(acquirer)
        with decimal_context():
            basis = holding.cost_basis + (
                ZERO if existing is None else existing.cost_basis
            )
        del book.holdings[context.security_id]
        book.holdings[acquirer] = SecurityHoldingV1(
            security_id=acquirer,
            quantity=whole + (0 if existing is None else existing.quantity),
            cost_basis=basis,
        )
        if cash or residual:
            payable_on = _payable_session(_date_facts(_terms_payload(context)))
            for component_cash in cash:
                self._stage_claim(
                    context=context,
                    component_id=component_cash.component_id,
                    quantity=holding.quantity,
                    cash_per_share=self._cash_per_share(
                        component_cash, context.security_id
                    ),
                    entitlement_session=context.effective_on,
                    payable_session=payable_on,
                    book=book,
                )
            if residual:
                self._stage_cash_in_lieu(context, component, residual, book)

    def _apply_liquidation(
        self, context: _EffectContext, book: _Book, session: SessionKeyV1
    ) -> None:
        if context.effective_on != session.local_date:
            return
        holding = book.holdings.get(context.security_id)
        if holding is None:
            return
        components = _only_cash_components(context, "a liquidation")
        payable_on = _payable_session(_date_facts(_terms_payload(context)))
        del book.holdings[context.security_id]
        for component in components:
            self._stage_claim(
                context=context,
                component_id=component.component_id,
                quantity=holding.quantity,
                cash_per_share=self._cash_per_share(component, context.security_id),
                entitlement_session=context.effective_on,
                payable_session=payable_on,
                book=book,
            )

    def _scale_target(
        self,
        context: _EffectContext,
        component: ShareComponentV1,
        book: _Book,
        tie_break: TieBreak | None,
    ) -> None:
        """Scale a staged target through a split so the intended delta survives."""
        target = book.targets.get(context.security_id)
        if target is None or target.target_quantity == 0:
            return
        exact = Fraction(target.target_quantity) * ratio_fraction(component.ratio)
        whole, _ = resolve_whole_shares(
            exact, component.fraction_treatment, tie_break=tie_break
        )
        book.targets[context.security_id] = SecurityTargetPositionV1(
            security_id=context.security_id, target_quantity=whole
        )

    def _entitlement_session(
        self, context: _EffectContext, dates: Mapping[str, EconomicDateFactV1]
    ) -> date:
        """Resolve the session a cash entitlement legally vests on.

        Deriving this from any other date is prohibited. In particular, a
        generic ``due_bill_redemption_date == entitlement_date`` shortcut is
        never applied: a due bill is a venue rule, and the entitlement session
        comes only from a proven executable reading of that rule.
        """
        due_bill_facts = {
            role: fact for role, fact in dates.items() if role in DUE_BILL_ROLES
        }
        if due_bill_facts:
            rule = self._due_bills.get(
                (context.source_id, context.security_id, context.occurrence_id)
            )
            if rule is None:
                raise IndeterminateValuationError(
                    "a due-bill distribution requires a proven executable due-bill rule"
                )
            if rule.executability != "executable" or rule.entitlement_session is None:
                raise IndeterminateValuationError(
                    f"the supplied due-bill rule is not executable: {rule.reason}"
                )
            evidenced = {
                fact.rule_reference.content_hash
                for fact in due_bill_facts.values()
                if fact.rule_reference is not None
            }
            if rule.rule_reference.content_hash not in evidenced:
                raise IndeterminateValuationError(
                    "the supplied due-bill rule is not bound to the source "
                    "due-bill evidence"
                )
            return rule.entitlement_session
        record_fact = dates.get("record")
        if record_fact is None:
            raise IndeterminateValuationError(
                "a cash entitlement requires a source record date"
            )
        return boundary_session_date(record_fact.boundary, role="record date")

    def _cash_per_share(
        self, component: CashComponentV1, security_id: UUID7
    ) -> Decimal:
        """Exact cash owed per predecessor share, under the component's own basis."""
        if (component.currency_namespace, component.currency_code) != self._currency:
            raise IndeterminateValuationError(
                f"source cash in {component.currency_namespace} "
                f"{component.currency_code} does not match the book currency "
                f"{self._currency[0]} {self._currency[1]}"
            )
        if component.amount_basis == "unknown":
            raise IndeterminateValuationError(
                "source amount basis is unknown, so the owed cash is unproven"
            )
        if component.applicability != "ordinary_passive_holder" or component.conditions:
            raise IndeterminateValuationError(
                "source cash is not proven for an ordinary passive holder"
            )
        if component.unit_basis.share_basis == "as_reported_unknown":
            raise IndeterminateValuationError(
                "source cash requires a known share basis"
            )
        if component.unit_basis.security_id != security_id:
            raise IndeterminateValuationError(
                "source cash must be denominated in the acted security"
            )
        amount = Fraction(Decimal(component.amount))
        return exact_decimal(amount / ratio_fraction(component.unit_basis.denominator))

    def _stage_cash_in_lieu(
        self,
        context: _EffectContext,
        component: ShareComponentV1,
        residual: Fraction,
        book: _Book,
    ) -> None:
        """Record the cash leg of an aggregate fractional-share sale."""
        rate = self._in_lieu_rates.get(
            (
                context.source_id,
                context.security_id,
                context.occurrence_id,
                component.component_id,
            )
        )
        if rate is None:
            raise IndeterminateValuationError(
                "an aggregate-sale fractional entitlement requires a proven "
                "source aggregate-sale cash rate"
            )
        if (rate.currency_namespace, rate.currency_code) != self._currency:
            raise IndeterminateValuationError(
                f"aggregate-sale cash in {rate.currency_namespace} "
                f"{rate.currency_code} does not match the book currency "
                f"{self._currency[0]} {self._currency[1]}"
            )
        bound = component.fraction_treatment.evidence_reference
        if bound is None or rate.evidence_reference.content_hash != bound.content_hash:
            raise IndeterminateValuationError(
                "the supplied aggregate-sale cash rate is not bound to the "
                "source fraction-treatment evidence"
            )
        proceeds = exact_decimal(
            Fraction(Decimal(rate.cash_per_whole_share)) * residual
        )
        payable_on = _payable_session(_date_facts(_terms_payload(context)))
        self._stage_claim(
            context=context,
            component_id=cash_in_lieu_component_id(component.component_id, residual),
            quantity=1,
            cash_per_share=proceeds,
            entitlement_session=context.effective_on,
            payable_session=payable_on,
            book=book,
        )

    def _stage_claim(
        self,
        *,
        context: _EffectContext,
        component_id: str,
        quantity: int,
        cash_per_share: Decimal,
        entitlement_session: date,
        payable_session: date,
        book: _Book,
    ) -> None:
        if payable_session < entitlement_session:
            raise IndeterminateValuationError(
                "a source payable date cannot precede the proven entitlement session"
            )
        action_kind = context.payload.action_kind
        identity: ClaimIdentity = (
            context.source_id,
            context.security_id,
            action_kind,
            context.occurrence_id,
            component_id,
        )
        if identity in book.claims:
            raise IndeterminateValuationError(
                "one economic entitlement was staged twice in one session: "
                f"{context.occurrence_id}/{component_id}"
            )
        with decimal_context():
            total = cash_per_share * quantity
        book.claims[identity] = PendingCashClaimV1(
            claim_id=_claim_identity_hash(
                source_id=context.source_id,
                security_id=context.security_id,
                action_kind=action_kind,
                occurrence_id=context.occurrence_id,
                component_id=component_id,
                entitlement_session=entitlement_session,
                payable_session=payable_session,
            ),
            security_id=context.security_id,
            action_kind=action_kind,
            occurrence_id=context.occurrence_id,
            component_id=component_id,
            entitled_quantity=quantity,
            cash_per_share=cash_per_share,
            total_cash_expected=total,
            entitlement_session=entitlement_session,
            payable_session=payable_session,
        )

    def _record_claims(
        self,
        state: PortfolioStateV1,
        claims: Mapping[ClaimIdentity, PendingCashClaimV1],
    ) -> PortfolioStateV1:
        if not claims:
            return state
        # A claim already pending or already settled is the same entitlement.
        # Re-recording it would pay one dividend twice.
        known = {claim.claim_id for claim in state.pending_cash_claims} | set(
            state.settled_claim_ids
        )
        fresh = sorted(
            (claim for claim in claims.values() if claim.claim_id not in known),
            key=lambda item: item.claim_id,
        )
        if not fresh:
            return state
        kernel = PortfolioAccountingKernel(state)
        for claim in fresh:
            kernel.record_claim(claim)
        return kernel.state

    def _tie_break(self, treatment: FractionTreatmentV1) -> TieBreak | None:
        if (
            treatment.kind != "round_nearest"
            or treatment.source_rule is None
            or treatment.evidence_reference is None
        ):
            return None
        return self._tie_breaks.get(
            (treatment.source_rule, treatment.evidence_reference.content_hash)
        )

    @staticmethod
    def _is_exposed(security_id: UUID7, book: _Book) -> bool:
        return security_id in book.holdings or security_id in book.targets

    # -- settlement internals ---------------------------------------------

    def _matched_claim(
        self,
        index: Mapping[tuple[UUID, str, str], Mapping[SHA256Hash, PendingCashClaimV1]],
        group: EconomicDeliveryGroupV1,
        component: CashComponentV1,
    ) -> PendingCashClaimV1 | None:
        occurrence_id = group.native_occurrence_id
        matches = index.get((group.security_id, occurrence_id, component.component_id))
        if not matches:
            # Delivered cash that no proven entitlement claims commits nothing.
            # Crediting it would create money from an unmatched report.
            return None
        if len(matches) > 1:
            raise IndeterminateValuationError(
                "one delivered cash component matches more than one pending "
                f"claim: {occurrence_id}/{component.component_id}"
            )
        return next(iter(matches.values()))

    def _verify_delivery(
        self,
        claim: PendingCashClaimV1,
        component: CashComponentV1,
        group: EconomicDeliveryGroupV1,
        session: SessionKeyV1,
    ) -> None:
        delivered = self._cash_per_share(component, group.security_id)
        if delivered != claim.cash_per_share:
            raise IndeterminateValuationError(
                "delivered cash contradicts the proven entitlement: expected "
                f"{claim.cash_per_share} per unit, delivered {delivered}"
            )
        if claim.payable_session > session.local_date:
            raise IndeterminateValuationError(
                "a claim cannot be delivered before its proven payable session: "
                f"payable {claim.payable_session}, session {session.local_date}"
            )


def _index_pending_claims(
    state: PortfolioStateV1,
) -> dict[tuple[UUID, str, str], dict[SHA256Hash, PendingCashClaimV1]]:
    """Index pending claims by the identity a delivery group can name.

    ``PendingCashClaimV1`` does not yet carry ``source_id``, so matching uses
    security, occurrence, and component. A cash-in-lieu leg is also indexed
    under the share component it came from, because a source reports the
    aggregate sale against that original component id.
    """
    index: dict[tuple[UUID, str, str], dict[SHA256Hash, PendingCashClaimV1]] = {}
    for claim in state.pending_cash_claims:
        keys = [(claim.security_id, claim.occurrence_id, claim.component_id)]
        origin = cash_in_lieu_origin(claim.component_id)
        if origin is not None:
            keys.append((claim.security_id, claim.occurrence_id, origin))
        for key in keys:
            index.setdefault(key, {})[claim.claim_id] = claim
    return index


def _claim_identity_hash(
    *,
    source_id: str,
    security_id: UUID7,
    action_kind: ActionKind,
    occurrence_id: str,
    component_id: str,
    entitlement_session: date,
    payable_session: date,
) -> SHA256Hash:
    """Derive one pending-claim identity under the RULED claim identity.

    The ruled identity is ``(source_id, security_id, action_kind,
    occurrence_id, component_id)``, with the entitlement and payable dates
    carried as revisable attributes and date revisions handled by
    supersession. Every caller in this module already passes exactly that
    tuple.

    ADAPTER, intentionally thin. The shipped
    ``drift.domain.evaluator_portfolio.pending_cash_claim_id`` still folds the
    two dates into the preimage and does not accept ``source_id``; that defect
    is being fixed on ``krish/portfolio-crossslice``, which is outside this
    task's write-set. Until that lands this function must reproduce the
    current preimage exactly, or ``PendingCashClaimV1`` would reject every
    claim it mints.

    When the ruled identity lands, the body below becomes a single call
    forwarding ``source_id`` and dropping the two date arguments; no caller
    changes. Two interim consequences are worth naming: a payable-date
    revision still mints a second id for one entitlement, and two sources
    reporting one occurrence still collide on a single id. The stricter
    one-effective-report-per-occurrence guard in ``_apply_outcome`` blocks the
    second case from reaching here today.
    """
    return pending_cash_claim_id(
        security_id=security_id,
        action_kind=action_kind,
        occurrence_id=occurrence_id,
        component_id=component_id,
        entitlement_session=entitlement_session,
        payable_session=payable_session,
    )


def _terms_payload(context: _EffectContext) -> TermsPayloadV1:
    association = context.record.terms_association
    target = association.target
    if association.kind != "identified" or target is None:
        raise IndeterminateValuationError(
            "this corporate action requires identified source terms to prove its dates"
        )
    found = context.terms.get(target)
    if found is None:
        raise IndeterminateValuationError(
            "this corporate action requires identified source terms that the "
            "outcome bundle actually supplies"
        )
    asserted = association.asserted_target_version_hash
    if asserted is not None and asserted != content_hash(found):
        raise IndeterminateValuationError(
            "supplied source terms are not the version the occurred effect asserts"
        )
    payload = found.payload
    if payload is None:
        raise IndeterminateValuationError(
            "withdrawn source terms cannot prove a corporate-action date"
        )
    return payload


def _payable_session(dates: Mapping[str, EconomicDateFactV1]) -> date:
    fact = dates.get("payable")
    if fact is None:
        raise IndeterminateValuationError(
            "a cash entitlement requires a source payable date"
        )
    return boundary_session_date(fact.boundary, role="payable date")


def _cash_components(context: _EffectContext) -> tuple[CashComponentV1, ...]:
    return tuple(
        sorted(
            (
                component
                for component in context.payload.owed_components
                if isinstance(component, CashComponentV1)
            ),
            key=lambda item: item.component_id,
        )
    )


def _only_cash_components(
    context: _EffectContext, label: str
) -> tuple[CashComponentV1, ...]:
    components = _cash_components(context)
    if not components or len(components) != len(context.payload.owed_components):
        raise IndeterminateValuationError(
            f"{label} requires proven source cash components and nothing else"
        )
    return components


def _require_no_cash(context: _EffectContext, label: str) -> None:
    if _cash_components(context):
        raise IndeterminateValuationError(
            f"{label} carries no source cash component in M1c terms"
        )


def _require_ended_claim(context: _EffectContext) -> None:
    if context.payload.claim_status not in ENDED_CLAIM_STATUSES:
        raise IndeterminateValuationError(
            "an acquisition must prove the predecessor claim ended, got claim "
            f"status {context.payload.claim_status}"
        )


def _single_share_component(
    context: _EffectContext,
    *,
    same_recipient: bool,
    meaning: str,
    label: str,
) -> ShareComponentV1:
    shares = tuple(
        component
        for component in context.payload.owed_components
        if isinstance(component, ShareComponentV1)
    )
    if len(shares) != 1:
        raise IndeterminateValuationError(
            f"{label} requires exactly one source share component, got {len(shares)}"
        )
    component = shares[0]
    if component.unit_basis.security_id != context.security_id:
        raise IndeterminateValuationError(
            f"{label} share terms must be denominated in the acted security"
        )
    recipient = component.recipient
    if recipient.kind != "security" or recipient.security_id is None:
        raise IndeterminateValuationError(
            f"{label} requires a resolved security recipient"
        )
    if (recipient.security_id == context.security_id) != same_recipient:
        raise IndeterminateValuationError(f"{label} has an unexpected share recipient")
    if component.ratio_meaning != meaning:
        raise IndeterminateValuationError(
            f"{label} requires {meaning} share terms, got {component.ratio_meaning}"
        )
    if component.applicability != "ordinary_passive_holder" or component.conditions:
        raise IndeterminateValuationError(
            f"{label} requires unconditional ordinary-holder share terms"
        )
    return component
