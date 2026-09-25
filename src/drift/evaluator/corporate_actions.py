"""Deterministic corporate-action and economic outcome accounting for M2.

Two entry points bracket a session. ``apply_pre_open_actions`` folds every M1c
occurred effect that became effective since the previous clock session into
holdings, staged targets, and cash entitlements, before any price is read.
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
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from drift.domain.common import UUID7, SHA256Hash
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicComponentV1,
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
from drift.domain.evaluator_clock import SessionClockV1
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
# Every action that changes a share count, as actor or as recipient. Cash
# distributions pay on shares without changing them, and so does a
# liquidation on a continuing claim (see _is_cash_distribution).
SHARE_MUTATING_KINDS = (
    SPLIT_KINDS
    | SHARE_ACQUISITION_KINDS
    | frozenset(
        {
            ActionKind.STOCK_DIVIDEND,
            ActionKind.SPINOFF,
            ActionKind.CASH_ACQUISITION,
            ActionKind.LIQUIDATION,
        }
    )
)
DUE_BILL_ROLES = frozenset({"due_bill_start", "due_bill_end", "due_bill_redemption"})
ENDED_CLAIM_STATUSES = frozenset({"converted", "extinguished"})
# Share actions that act on a claim that continues (issue 117).
CONTINUING_SHARE_KINDS = SPLIT_KINDS | frozenset(
    {ActionKind.STOCK_DIVIDEND, ActionKind.SPINOFF}
)
# Every kind whose own ended claim status contradicts it (issue 117): those
# share actions, and cash distributions paid on shares that all continue. A
# liquidation keeps its own claim-status rules (issue 83).
CONTINUING_CLAIM_KINDS = CONTINUING_SHARE_KINDS | CASH_DISTRIBUTION_KINDS

type ClaimIdentity = tuple[str, UUID, ActionKind, str, str]
type TermsIndex = Mapping[EconomicSourceKeyV1, CorporateActionTermsVersionV1]
# Source, security, native occurrence and component: everything a delivered
# report names. Claim identity also carries the action kind, which it cannot.
type _ClaimIndexKey = tuple[str, UUID, str, str]


@dataclass
class _Book:
    """The in-flight working set for one pre-open pass.

    ``opening`` is the pre-open holding set, frozen before any action in this
    pass ran. A source that quotes cash per *pre-action* share is answered
    from ``opening``; one that quotes per *post-action* share is answered from
    ``holdings``. Without both, a dividend declared alongside a split would
    take its share count from whichever record happened to hash first.

    ``realized`` is the PnL this pass realized by disposals: holdings a
    corporate action extinguished for cash owed, whose basis is relieved
    exactly as a sale at the owed price would relieve it.

    ``delivered`` and ``removed`` record, by security, the share action of
    this pass that delivered shares into its holding from another security
    (a spin-off child, an acquirer), and the one that removed its holding
    (a disposal, a share acquisition). Neither leaves a post-action count
    the prior close's holders are proven entitled on
    (``_require_proven_post_action_count``).
    """

    opening: Mapping[UUID, SecurityHoldingV1]
    holdings: dict[UUID, SecurityHoldingV1]
    targets: dict[UUID, SecurityTargetPositionV1]
    claims: dict[ClaimIdentity, PendingCashClaimV1]
    realized: Decimal = ZERO
    unmodelled: list[_EffectContext] = field(default_factory=list)
    delivered: dict[UUID, _EffectContext] = field(default_factory=dict)
    removed: dict[UUID, _EffectContext] = field(default_factory=dict)


@dataclass(frozen=True)
class _SessionWindow:
    """The dates whose corporate-action evidence one pre-open pass owns.

    A session owns every date after the clock session before it, up to and
    including its own date. A weekend or a did-not-open day is not a session,
    so evidence dated on one lands at the next pre-open, and nothing has
    traded since the prior close. The windows of successive sessions never
    overlap, so no effect is applied twice.

    The first clock session owns only its own date. The evaluation holds no
    session before it, so the opening book is taken to reflect every earlier
    effect already; re-applying that history would split it again.
    """

    previous: date | None
    current: date

    def contains(self, day: date) -> bool:
        """Whether this pass owns evidence dated ``day``."""
        if day > self.current:
            return False
        if self.previous is None:
            return day == self.current
        return day > self.previous


@dataclass(frozen=True)
class _ShareActionConflict:
    """Two or more share actions touching one security in one window."""

    security_id: UUID7
    dates: tuple[date, ...]
    # The conflicting actions' kinds, in their reported order.
    actions: tuple[str, ...]
    # Every security any of those actions acts on or delivers into.
    touched: frozenset[UUID7]


@dataclass(frozen=True)
class _UnknownClaim:
    """An outcome whose composed claim status is unknown, live in this window."""

    security_id: UUID7
    # The live effects' kinds, and every security any effect acts on or
    # delivers into.
    actions: tuple[str, ...]
    touched: frozenset[UUID7]


@dataclass(frozen=True)
class _EndedClaimAction:
    """An effect on a continuing claim, live in this window, that M1c ends.

    ``composed`` says whose status ends the claim: the effect's own when
    false, the status M1c composes across the outcome when true.
    """

    context: _EffectContext
    status: str
    composed: bool


@dataclass(frozen=True)
class _EffectContext:
    """One proven occurred effect, already bound to its source identity."""

    record: EconomicEffectVersionV1
    payload: OccurredEffectV1
    occurrence_id: str
    effective_on: date
    terms: TermsIndex
    # M1c places the effect before the outcome's evidence window. Such an
    # effect is never applied; it can only explain delivered cash.
    before_window: bool = False

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
    state: PortfolioStateV1,
    holdings: Mapping[UUID, SecurityHoldingV1],
    realized: Decimal,
) -> PortfolioStateV1:
    """Rebuild state around new holdings, discarding any mark.

    A mark describes the holdings it was taken against. A corporate action
    replaces those holdings, so carrying the mark forward would value shares
    that no longer exist. ``realized`` is the disposal PnL of the same pass;
    a corporate action carries no transaction cost, so gross and net move
    together.
    """
    with decimal_context():
        return PortfolioStateV1(
            session_key=state.session_key,
            cash_balance=state.cash_balance,
            holdings=tuple(holdings[key] for key in sorted(holdings, key=str)),
            pending_cash_claims=state.pending_cash_claims,
            settled_claim_ids=state.settled_claim_ids,
            lane=state.lane,
            admission_hash=state.admission_hash,
            mark=None,
            holdings_market_value=ZERO,
            pending_claims_value=state.pending_claims_value,
            net_asset_value=state.cash_balance + state.pending_claims_value,
            realized_gross_pnl=state.realized_gross_pnl + realized,
            realized_net_pnl=state.realized_net_pnl + realized,
            cumulative_transaction_costs=state.cumulative_transaction_costs,
        )


def _date_facts(payload: TermsPayloadV1) -> dict[str, EconomicDateFactV1]:
    return {fact.role: fact for fact in payload.dates}


def _is_cash_distribution(payload: OccurredEffectV1) -> bool:
    """Whether an effect pays cash on shares that all continue.

    A liquidation whose claim continues is a partial liquidating
    distribution: it erases no share, so it is entitled, ordered, and
    reconciled as a cash distribution.
    """
    return payload.action_kind in CASH_DISTRIBUTION_KINDS or (
        payload.action_kind == ActionKind.LIQUIDATION
        and payload.claim_status == "continuing"
    )


def _has_due_bill_facts(dates: Mapping[str, EconomicDateFactV1]) -> bool:
    return any(role in DUE_BILL_ROLES for role in dates)


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
        session_clock: SessionClockV1,
        book_currency_namespace: str,
        book_currency_code: str,
        tie_breaking_rules: Collection[TieBreakingRuleV1] = (),
        due_bill_rules: Collection[DueBillRuleV1] = (),
        cash_in_lieu_rates: Collection[CashInLieuRateV1] = (),
    ) -> None:
        # The kernels this processor builds are validated against the same
        # authority-bound clock as the caller's book. A clock derived from the
        # book being checked would prove nothing.
        self._session_clock = session_clock
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
        # Each session's window is fixed by the clock alone, so it is read
        # once here rather than rescanned on every pass.
        self._previous_dates: dict[SessionKeyV1, date | None] = {}
        previous: date | None = None
        for session in session_clock.sessions:
            self._previous_dates[session.session_key] = previous
            previous = session.session_key.local_date
        self._first_session_date = session_clock.sessions[0].session_key.local_date

    # -- public surface ---------------------------------------------------

    def apply_pre_open_actions(
        self,
        portfolio_state: PortfolioStateV1,
        staged_targets: Iterable[SecurityTargetPositionV1],
        economic_outcomes: Iterable[SecurityEconomicOutcomeV1],
        current_session: SessionKeyV1,
    ) -> tuple[PortfolioStateV1, tuple[SecurityTargetPositionV1, ...]]:
        """Fold this session's proven corporate actions into book and targets.

        Call this exactly once per session, for every session of the clock in
        order. Each pass owns the evidence dated inside its session window
        (see ``_SessionWindow``), so an effect dated on a weekend or a
        did-not-open day is applied at the next pre-open rather than dropped.
        Cash entitlements are idempotent, because a claim already pending or
        already in ``settled_claim_ids`` is recognized and skipped. Share
        mutations are NOT: a second call for the same session would split an
        already split position again. ``PortfolioStateV1`` carries no
        applied-occurrence ledger to make that detectable from state alone,
        and that model is outside this task's write-set. The fix is an
        ``applied_occurrence_ids`` field there.
        """
        _require_positioned(portfolio_state, current_session)
        window = self._session_window(current_session)
        opening_holdings = {
            holding.security_id: holding for holding in portfolio_state.holdings
        }
        book = _Book(
            opening=opening_holdings,
            holdings=dict(opening_holdings),
            targets=_unique_targets(staged_targets),
            claims={},
        )
        supported: list[tuple[SecurityEconomicOutcomeV1, list[_EffectContext]]] = []
        unsupported: list[SecurityEconomicOutcomeV1] = []
        for outcome in _ordered_outcomes(economic_outcomes):
            if outcome.resolution.support_status == "supported":
                supported.append((outcome, _effect_contexts(outcome)))
            else:
                unsupported.append(outcome)
        every_context = [context for _, contexts in supported for context in contexts]
        conflicts = _share_action_conflicts(every_context, window)
        unknown = self._unknown_claims(supported, window)
        ended = self._ended_claim_actions(supported, window)
        # Every rule is judged against the prior close's book here, before
        # any dispatch, and again against the book the pass leaves below. An
        # unknown claim needs both: a disposal may empty the book the pass
        # leaves, and a spin-off or conversion may reach a security only in
        # it. A conflict needs only the first. The pass reaches a new security
        # only through a spin-off or share acquisition from one already
        # exposed, itself a share action touching both, so exposure the pass
        # gains to a conflict implies exposure at the prior close to that
        # conflict or to one on the chain that reached it. The second
        # conflict check is defense in depth. An effect on an ended claim
        # needs both: a reverse split may restate a staged buy as 0, and a
        # spin-off or conversion may deliver the security a distribution on
        # an ended claim pays on. For a share action on an ended claim the
        # second check is defense in depth, as for a conflict: the pass
        # reaches its security only through another share action touching
        # it, which conflicts with this one.
        self._require_no_exposed_conflict(conflicts, book)
        self._require_no_exposed_unknown_claim(unknown, book)
        self._require_no_exposed_ended_claim(ended, book)
        exposed_at_close = {
            security_id
            for security_id in (*book.holdings, *book.targets)
            if self._is_exposed(security_id, book)
        }
        # One dispatch over every outcome, so every share action of the pass
        # runs before any cash distribution, whichever outcome each is in.
        self._apply_contexts(every_context, book, window)
        self._require_no_exposed_conflict(conflicts, book)
        self._require_no_exposed_unknown_claim(unknown, book)
        self._require_no_exposed_ended_claim(ended, book)
        # Exposure to evidence this pass cannot apply is judged against the
        # book the pass leaves: a holding or positive target credited by an
        # earlier dispatch, such as a spin-off child, is exposure too.
        for outcome in unsupported:
            # An unsupported or indeterminate composition cannot be trusted to
            # say what happened. It only halts a run that is actually exposed
            # to the security, so an unmodellable action elsewhere in the
            # universe does not poison an unrelated book. It is never
            # applied, and only a security's own outcome removes its holding
            # or zeroes its target, so the book the pass leaves is exposed to
            # it whenever the prior close's book was.
            if self._is_exposed(outcome.security_id, book):
                raise IndeterminateValuationError(
                    "economic outcome resolution is not supported evidence for "
                    f"{outcome.security_id}: {outcome.resolution.support_status}"
                )
        # An action with no accounting rule is judged against the prior
        # close's book too: a disposal in its own outcome may empty the book
        # the pass leaves, and would then realize PnL on shares whose fate
        # the unmodelled action leaves unproven.
        for context in book.unmodelled:
            if context.security_id in exposed_at_close or self._is_exposed(
                context.security_id, book
            ):
                raise IndeterminateValuationError(
                    f"corporate action kind {context.payload.action_kind.value} "
                    "has no proven M2 accounting rule"
                )
        state = portfolio_state
        if book.holdings != opening_holdings:
            state = _replace_holdings(state, book.holdings, book.realized)
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
        """Settle only the entitlements a delivered settlement actually proves.

        Delivered cash that matches no pending claim is not simply dropped
        when the book is exposed to the security, by a holding or by a pending
        claim on it. That cash must be shown to be owed to someone else (see
        ``_require_unowed``), or the run is indeterminate.
        """
        _require_positioned(portfolio_state, current_session)
        index = _index_pending_claims(portfolio_state)
        exposed = {holding.security_id for holding in portfolio_state.holdings} | {
            claim.security_id for claim in portfolio_state.pending_cash_claims
        }
        settling: dict[SHA256Hash, PendingCashClaimV1] = {}
        for outcome in _ordered_outcomes(economic_outcomes):
            owed: _OwedIndex | None = None
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
                        # Unmatched cash is never credited, but an exposed
                        # book halts unless it was provably never owed it.
                        if group.security_id in exposed:
                            if owed is None:
                                # Proven once per outcome and pass, not once
                                # per delivery: every past delivery is read
                                # again on every session.
                                owed = _owed_index(outcome)
                            self._require_unowed(
                                owed, group, component, current_session
                            )
                        continue
                    self._verify_delivery(claim, component, group, current_session)
                    settling[claim.claim_id] = claim
        if not settling:
            return portfolio_state
        kernel = PortfolioAccountingKernel(
            portfolio_state, session_clock=self._session_clock
        )
        kernel.settle_claims(tuple(sorted(settling)))
        return kernel.state

    # -- pre-open internals -----------------------------------------------

    def _require_no_exposed_conflict(
        self, conflicts: Iterable[_ShareActionConflict], book: _Book
    ) -> None:
        """Refuse a window in which two share actions touch one security.

        The pass applies share actions by security id and record hash, never
        by time, so two actions touching one security compound in an unproven
        order, on one date or several. A 1:10 reverse split on Friday and a
        3:1 split on Monday turn 105 shares into 30 in date order and into 31
        otherwise; a split at 10:00 and a cash acquisition at 15:00 of one
        date owe 2400 in time order and 1200 otherwise. At most one share
        action per security keeps every result independent of that order.
        Proving a same-date order from the effects' intraday instants is not
        done in M2 V1. Only a book exposed to a security one of the
        conflicting actions touches is halted. Raising after dispatch is safe,
        because a pass that raises is discarded whole.
        """
        for conflict in conflicts:
            if any(self._is_exposed(touched, book) for touched in conflict.touched):
                spelled = ", ".join(str(day) for day in conflict.dates)
                raise IndeterminateValuationError(
                    f"one pre-open window holds share actions on {spelled} "
                    f"touching {conflict.security_id} "
                    f"({', '.join(conflict.actions)}), and M2 V1 proves no order "
                    "between share actions on one security in one window"
                )

    def _unknown_claims(
        self,
        supported: Iterable[tuple[SecurityEconomicOutcomeV1, list[_EffectContext]]],
        window: _SessionWindow,
    ) -> tuple[_UnknownClaim, ...]:
        """Every outcome M1c composes as unknown that acts in this window."""
        found: list[_UnknownClaim] = []
        for outcome, contexts in supported:
            if outcome.resolution.claim_status != "unknown":
                continue
            live = [context for context in contexts if self._is_live(context, window)]
            if not live:
                continue
            found.append(
                _UnknownClaim(
                    security_id=outcome.security_id,
                    actions=tuple(
                        sorted({context.payload.action_kind.value for context in live})
                    ),
                    touched=frozenset(
                        {outcome.security_id}
                        | {
                            touched
                            for context in contexts
                            for touched in _touched_securities(context)
                        }
                    ),
                )
            )
        return tuple(found)

    def _is_live(self, context: _EffectContext, window: _SessionWindow) -> bool:
        """Whether an effect can commit anything in this window.

        A share action or disposal commits on its effective date. A cash
        distribution commits on its entitlement date, which may fall in a
        window later than its effect; one whose entitlement cannot be dated
        counts as live once it is effective, since it could vest now.
        """
        if window.contains(context.effective_on):
            return True
        if not _is_cash_distribution(context.payload):
            return False
        if context.effective_on > window.current:
            return False
        try:
            vests = self._entitlement_session(
                context, _date_facts(_terms_payload(context))
            )
        except IndeterminateValuationError:
            return True
        return window.contains(vests)

    def _require_no_exposed_unknown_claim(
        self, claims: Iterable[_UnknownClaim], book: _Book
    ) -> None:
        """Refuse a window acting on a claim M1c composes as unknown.

        Two liquidations at one instant with conflicting statuses, or any
        continuing effect after an extinguishing one, each read cleanly
        alone, while M1c composes the claim as ``unknown``: whether the claim
        survives is unproven. Any effect of that outcome that commits in this
        window (a split, a dividend, a spin-off, a stock dividend, an
        acquisition or a liquidation) then builds on an unproven claim, so an
        exposed book halts, judged against the prior close's book and the
        book the pass leaves.
        """
        for claim in claims:
            if any(self._is_exposed(touched, book) for touched in claim.touched):
                raise IndeterminateValuationError(
                    f"M1c composes the claim of {claim.security_id} as unknown, so "
                    f"whether it survives this window's {', '.join(claim.actions)} "
                    "is not proven"
                )

    def _ended_claim_actions(
        self,
        supported: Iterable[tuple[SecurityEconomicOutcomeV1, list[_EffectContext]]],
        window: _SessionWindow,
    ) -> tuple[_EndedClaimAction, ...]:
        """Every effect of this window on a continuing claim that M1c ends.

        A split, a reverse split, a stock dividend and a spin-off each act on
        a claim that continues. One whose own claim status is ``extinguished``
        or ``converted`` contradicts itself. So does one on a claim M1c
        composes as ended when no ending effect of the outcome definitely
        follows it: M1c composes the status of the claim's latest effect, so
        the claim had then ended by the action. An end that follows the
        action (a split, then a later acquisition) is the history of a live
        claim, and the action applies. M1c never composes an end for a
        continuing action without an ending effect strictly after it, so that
        branch is defense in depth.

        A dividend or special distribution pays on shares that all continue,
        so one whose own claim status ends the claim contradicts itself too.
        It is judged in every window it commits in (``_is_live``). A
        liquidation keeps its own claim-status rules: an extinguished one is
        a disposal, and a continuing one is a distribution
        (``_is_cash_distribution``).
        """
        found: list[_EndedClaimAction] = []
        for outcome, contexts in supported:
            composed = outcome.resolution.claim_status
            for context in contexts:
                kind = context.payload.action_kind
                if kind not in CONTINUING_CLAIM_KINDS:
                    continue
                if not self._is_live(context, window):
                    continue
                own = context.payload.claim_status
                if own in ENDED_CLAIM_STATUSES:
                    found.append(_EndedClaimAction(context, own, composed=False))
                elif (
                    kind in CONTINUING_SHARE_KINDS
                    and composed in ENDED_CLAIM_STATUSES
                    and not any(
                        later.payload.claim_status in ENDED_CLAIM_STATUSES
                        and _definitely_precedes(context, later)
                        for later in contexts
                    )
                ):
                    found.append(_EndedClaimAction(context, composed, composed=True))
        return tuple(found)

    def _require_no_exposed_ended_claim(
        self, actions: Iterable[_EndedClaimAction], book: _Book
    ) -> None:
        """Refuse an effect on a continuing claim that M1c says ended.

        Such evidence contradicts itself, so it halts a book exposed to the
        security it acts on, judged against the prior close's book and the
        book the pass leaves. Unlike the composed-unknown rule, which judges
        every security the outcome touches, only the acted security counts:
        a spin-off child held without its parent receives nothing from the
        spin-off. For any other book the evidence is unrelated, and the
        effect has nothing of the book's to act on.
        """
        for action in actions:
            context = action.context
            if not self._is_exposed(context.security_id, book):
                continue
            reason = (
                f"M1c composes the claim as {action.status} and no later effect "
                "of the outcome ends it"
                if action.composed
                else f"its own claim status is {action.status}"
            )
            raise IndeterminateValuationError(
                f"the {context.payload.action_kind.value} {context.occurrence_id} "
                f"on {context.security_id} needs a continuing claim, but {reason}, "
                "so the evidence contradicts itself and the shares it acts on "
                "are not proven"
            )

    def _apply_contexts(
        self,
        contexts: list[_EffectContext],
        book: _Book,
        window: _SessionWindow,
    ) -> None:
        # Called once per pass, with the effects of every outcome. Every share
        # action is dispatched before any cash distribution, so a source
        # quoting cash per post-action share is answered after every share
        # action touching the security has run, whichever outcome it is in.
        # A pass that completes leaves at most one share action touching each
        # security the book is exposed to (_require_no_exposed_conflict), so
        # "pre-action" is always the prior close and "post-action" is after
        # that one action. Only the security's own continuing action (a
        # split, a reverse split, a stock dividend, the parent's own
        # spin-off) leaves a post-action count the prior close's holders are
        # entitled on; a delivery into the holding or its removal halts
        # (_require_proven_post_action_count).
        for context in contexts:
            if not _is_cash_distribution(context.payload):
                self._dispatch(context, book, window)
        for context in contexts:
            if _is_cash_distribution(context.payload):
                self._dispatch(context, book, window)

    def _dispatch(
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        kind = context.payload.action_kind
        if _is_cash_distribution(context.payload):
            self._apply_cash_distribution(context, book, window)
        elif kind in SPLIT_KINDS:
            self._apply_split(context, book, window)
        elif kind == ActionKind.STOCK_DIVIDEND:
            self._apply_stock_dividend(context, book, window)
        elif kind == ActionKind.SPINOFF:
            self._apply_spinoff(context, book, window)
        elif kind == ActionKind.CASH_ACQUISITION:
            self._apply_cash_acquisition(context, book, window)
        elif kind in SHARE_ACQUISITION_KINDS:
            self._apply_share_acquisition(context, book, window)
        elif kind == ActionKind.LIQUIDATION:
            self._apply_liquidation(context, book, window)
        else:
            # Judged once every action of the pass has run, against both the
            # prior close's book and the book the pass leaves.
            book.unmodelled.append(context)

    def _apply_split(
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        # A split is applied exactly on the session it becomes effective. Any
        # other gate would re-apply it on every later session in the window
        # and multiply the position.
        if not window.contains(context.effective_on):
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
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        if not window.contains(context.effective_on):
            return
        component = _single_share_component(
            context,
            same_recipient=True,
            meaning="additional_per_predecessor",
            label="stock dividend",
        )
        _require_no_cash(context, "a stock dividend")
        tie_break = self._tie_break(component.fraction_treatment)
        holding = book.holdings.get(context.security_id)
        if holding is not None:
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
        # A stock dividend re-denominates the security exactly as a split
        # does, so a target staged in pre-dividend shares is restated too.
        # Left alone, a staged hold would sell the new shares at the open.
        self._scale_target(context, component, book, tie_break)

    def _apply_spinoff(
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        if not window.contains(context.effective_on):
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
            existing = book.holdings.get(child)
            # Parent shares are unchanged, so the parent target stands. The
            # child shares received join the child target, so the child is
            # held rather than traded. Without a staged parent target no
            # decision is staged, and no child target may be invented.
            if context.security_id in book.targets:
                _credit_target(
                    book, child, whole, held=existing is not None, label="spin-off"
                )
            # No tax allocation percentage is claimed, so the child enters at a
            # zero basis and the parent keeps its own. Daily marks still value
            # both from their own closing prices.
            with decimal_context():
                basis = ZERO if existing is None else existing.cost_basis
            book.holdings[child] = SecurityHoldingV1(
                security_id=child,
                quantity=whole + (0 if existing is None else existing.quantity),
                cost_basis=basis,
            )
            book.delivered.setdefault(child, context)
        if residual:
            self._stage_cash_in_lieu(context, component, residual, book)

    def _apply_cash_distribution(
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        if (
            context.security_id not in book.opening
            and context.security_id not in book.holdings
        ):
            return
        dates = _date_facts(_terms_payload(context))
        if (
            "ex" not in dates
            and not _has_due_bill_facts(dates)
            and context.effective_on > window.current
        ):
            # Not yet effective, so its missing ex date says nothing about this
            # book yet. It halts the run once the effect is effective.
            return
        entitlement_on = self._entitlement_session(context, dates)
        # A cash distribution is recognized on the session its entitlement
        # vests, not on the session the effect was reported. That is what lets
        # a due bill defer the entitlement without losing it. An ex date off
        # the clock vests at the next pre-open, against the same prior close.
        if not window.contains(entitlement_on):
            return
        liquidating = context.payload.action_kind == ActionKind.LIQUIDATION
        if entitlement_on != window.current and _has_due_bill_facts(dates):
            # A proven due-bill rule names the session holders are entitled
            # on. When the clock holds no such session, no M2 V1 rule says
            # which other session those holders are counted on.
            raise IndeterminateValuationError(
                f"the due-bill entitlement session {entitlement_on} is not a "
                "session of the clock, and no M2 V1 rule moves a due-bill "
                "entitlement onto another session"
            )
        if context.effective_on > entitlement_on:
            raise IndeterminateValuationError(
                "a cash entitlement cannot vest before the occurrence that proves it"
            )
        payable_on = _payable_session(dates)
        components = _only_cash_components(
            context,
            "a liquidating distribution" if liquidating else "a cash distribution",
        )
        for component in components:
            share_basis = component.unit_basis.share_basis
            if share_basis == "predecessor_pre_action":
                holding = book.opening.get(context.security_id)
            else:
                _require_proven_post_action_count(context, book, share_basis)
                holding = book.holdings.get(context.security_id)
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
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        if not window.contains(context.effective_on):
            return
        holding = book.holdings.get(context.security_id)
        if holding is None and not _stages_a_buy(book, context.security_id):
            return
        _require_ended_claim(context)
        components = _only_cash_components(context, "a cash acquisition")
        # The claim ended, so no share of it can be traded at the open. A kept
        # target would re-buy the extinguished security.
        _extinguish_target(book, context.security_id)
        if holding is None:
            return
        self._dispose(context, holding, components, book)

    def _apply_share_acquisition(
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        if not window.contains(context.effective_on):
            return
        holding = book.holdings.get(context.security_id)
        if holding is None and not _stages_a_buy(book, context.security_id):
            return
        target = book.targets.get(context.security_id)
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
        existing = book.holdings.get(acquirer)
        whole, residual = 0, Fraction(0)
        if holding is not None:
            exact = exact_entitled_shares(holding.quantity, component)
            whole, residual = resolve_whole_shares(
                exact, component.fraction_treatment, tie_break=tie_break
            )
            if whole <= 0:
                raise IndeterminateValuationError(
                    "a share acquisition would extinguish a held position without "
                    "proven consideration for the remainder"
                )
        if target is not None:
            # The predecessor target is mapped onto the acquirer through the
            # exact ratio and fraction treatment the holding converts by, so
            # the intended delta survives in acquirer shares.
            mapped = _translated_quantity(target.target_quantity, component, tie_break)
            if mapped > whole:
                # A hold or a sale maps within the shares received. More than
                # that would buy the acquirer at the open, a security no
                # admitted decision named. The owner ruled that such a buy is
                # never carried forward: it stays INDETERMINATE (issue 97,
                # item 1, 2026-09-24).
                raise IndeterminateValuationError(
                    f"a share acquisition would buy the acquirer {acquirer} at "
                    f"the open: the staged target maps to {mapped} acquirer "
                    f"shares but the holding receives {whole}, and no admitted "
                    "decision named the acquirer"
                )
            _credit_target(
                book,
                acquirer,
                mapped,
                held=existing is not None,
                label="share acquisition",
            )
            _extinguish_target(book, context.security_id)
        if holding is None:
            return
        with decimal_context():
            basis = holding.cost_basis + (
                ZERO if existing is None else existing.cost_basis
            )
        del book.holdings[context.security_id]
        book.removed[context.security_id] = context
        book.holdings[acquirer] = SecurityHoldingV1(
            security_id=acquirer,
            quantity=whole + (0 if existing is None else existing.quantity),
            cost_basis=basis,
        )
        book.delivered.setdefault(acquirer, context)
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
        self, context: _EffectContext, book: _Book, window: _SessionWindow
    ) -> None:
        """Extinguish a liquidated holding for its proven terminal proceeds.

        A liquidation whose claim continues never reaches here: it is a cash
        distribution (``_is_cash_distribution``). Only a proven extinguished
        claim erases shares. Any other status leaves it unknown whether shares
        survive, and zero is never assumed (spec 12.6).
        """
        if not window.contains(context.effective_on):
            return
        holding = book.holdings.get(context.security_id)
        if holding is None and not _stages_a_buy(book, context.security_id):
            return
        status = context.payload.claim_status
        if status != "extinguished":
            raise IndeterminateValuationError(
                "a liquidation must prove the claim extinguished or continuing, "
                f"got claim status {status}"
            )
        components = _only_cash_components(context, "a liquidation")
        # The claim ended, so a kept target would re-buy the liquidated shares.
        _extinguish_target(book, context.security_id)
        if holding is None:
            return
        self._dispose(context, holding, components, book)

    def _scale_target(
        self,
        context: _EffectContext,
        component: ShareComponentV1,
        book: _Book,
        tie_break: TieBreak | None,
    ) -> None:
        """Restate a staged target through a re-denomination of its security.

        A split and a stock dividend move the target through the exact
        function they move the holding through, so a hold stays a hold and
        any other intended delta survives in post-action shares.
        """
        target = book.targets.get(context.security_id)
        if target is None:
            return
        book.targets[context.security_id] = SecurityTargetPositionV1(
            security_id=context.security_id,
            target_quantity=_translated_quantity(
                target.target_quantity, component, tie_break
            ),
        )

    def _entitlement_session(
        self, context: _EffectContext, dates: Mapping[str, EconomicDateFactV1]
    ) -> date:
        """Resolve the date a cash entitlement legally vests on.

        Deriving this from any other date is prohibited. In particular, a
        generic ``due_bill_redemption_date == entitlement_date`` shortcut is
        never applied: a due bill is a venue rule, and the entitlement session
        comes only from a proven executable reading of that rule.

        Without due-bill evidence the admitted ex-date rule applies (spec
        12.3): the ex date's pre-open vests the entitlement against the prior
        close's holdings. The record date is never read, because with a T+2
        or T+3 settlement cycle a share bought at the ex-date open is on the
        register by the record date and still is not entitled.
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
        ex_fact = dates.get("ex")
        if ex_fact is None:
            raise IndeterminateValuationError(
                "a cash entitlement requires a source ex date: entitlement "
                "follows the ex-date rule, and no record date stands in for it"
            )
        return boundary_session_date(ex_fact.boundary, role="ex date")

    def _vesting_date(self, context: _EffectContext, owed: EconomicComponentV1) -> date:
        """The date the entitlement to one owed component vests on.

        A cash distribution, including a liquidating distribution on shares
        that continue, vests under its entitlement rule. Every other cash leg
        (an acquisition, an extinguishing liquidation, or the cash in lieu of
        a share action's fraction) is owed from the effect's own effective
        date.
        """
        if _is_cash_distribution(context.payload) and isinstance(owed, CashComponentV1):
            return self._entitlement_session(
                context, _date_facts(_terms_payload(context))
            )
        return context.effective_on

    def _session_window(self, session: SessionKeyV1) -> _SessionWindow:
        """The window of dates a pre-open pass for ``session`` owns."""
        if session not in self._previous_dates:
            raise ValueError(
                f"session {session.local_date} is not a session of the "
                "processor's clock"
            )
        return _SessionWindow(
            previous=self._previous_dates[session], current=session.local_date
        )

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
    ) -> PendingCashClaimV1:
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
        claim = PendingCashClaimV1(
            claim_id=_claim_identity_hash(
                source_id=context.source_id,
                security_id=context.security_id,
                action_kind=action_kind,
                occurrence_id=context.occurrence_id,
                component_id=component_id,
            ),
            source_id=context.source_id,
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
        book.claims[identity] = claim
        return claim

    def _dispose(
        self,
        context: _EffectContext,
        holding: SecurityHoldingV1,
        components: Iterable[CashComponentV1],
        book: _Book,
    ) -> None:
        """Extinguish a whole holding for the cash its components owe.

        This is a disposal. The whole basis is relieved into realized PnL
        against the owed proceeds, exactly as a sale at that price would
        relieve it, so cash, claims and remaining basis still equal opening
        cash plus realized PnL. The proceeds are receivable rather than
        received, but the price is fixed by the action, so the gain or loss
        is realized now: in the pass of the first clock session on or after
        the effective date.
        """
        payable_on = _payable_session(_date_facts(_terms_payload(context)))
        del book.holdings[context.security_id]
        book.removed[context.security_id] = context
        proceeds = ZERO
        for component in components:
            claim = self._stage_claim(
                context=context,
                component_id=component.component_id,
                quantity=holding.quantity,
                cash_per_share=self._cash_per_share(component, context.security_id),
                entitlement_session=context.effective_on,
                payable_session=payable_on,
                book=book,
            )
            with decimal_context():
                proceeds += claim.total_cash_expected
        with decimal_context():
            book.realized += proceeds - holding.cost_basis

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
        kernel = PortfolioAccountingKernel(state, session_clock=self._session_clock)
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
        """Whether the book holds the security or stages a buy of it.

        An explicit zero target on an unheld security trades nothing at the
        open, so evidence about that security cannot move this book.
        """
        return security_id in book.holdings or _stages_a_buy(book, security_id)

    # -- settlement internals ---------------------------------------------

    def _require_unowed(
        self,
        owed: _OwedIndex,
        group: EconomicDeliveryGroupV1,
        component: CashComponentV1,
        session: SessionKeyV1,
    ) -> None:
        """Show that delivered cash no pending claim matches was never owed here.

        The pre-open pass records every entitlement the book holds on the
        session it vests, so an entitlement that has already vested with no
        claim here was owed to other holders, such as those at an ex date's
        prior close that this book bought after. That holds only when an
        occurred effect of the same source and occurrence owes this exact
        component, and it has vested by this session. Anything else is cash
        this book cannot account for, and it may be cash the book was owed.

        An entitlement that vested before the clock's first session belongs to
        the opening book, which carries its own pending claims, so it reads as
        vested here too. That is the only thing an effect M1c places before
        its evidence window can prove: the pre-open pass never applies such
        an effect, so one that vests inside the clock may be cash the book
        was owed.
        """
        label = (
            f"{group.source_id}/{group.native_occurrence_id}/{component.component_id}"
        )
        explaining = owed.get(
            (group.source_id, group.native_occurrence_id, component.component_id), []
        )
        if len(explaining) != 1:
            raise IndeterminateValuationError(
                f"delivered cash for {group.security_id} matches no pending claim "
                f"and no proven entitlement: {label}"
            )
        context, owed_component = explaining[0]
        vesting = self._vesting_date(context, owed_component)
        if context.before_window and vesting >= self._first_session_date:
            raise IndeterminateValuationError(
                f"delivered cash for {group.security_id} is explained only by an "
                "effect before the evidence window that vests inside the clock, "
                f"on {vesting}: {label}"
            )
        if vesting > session.local_date:
            raise IndeterminateValuationError(
                f"delivered cash for {group.security_id} arrived before the "
                f"entitlement it pays vests on {vesting}: {label}"
            )

    def _matched_claim(
        self,
        index: Mapping[_ClaimIndexKey, Mapping[SHA256Hash, PendingCashClaimV1]],
        group: EconomicDeliveryGroupV1,
        component: CashComponentV1,
    ) -> PendingCashClaimV1 | None:
        source_id = group.source_id
        occurrence_id = group.native_occurrence_id
        matches = index.get(
            (source_id, group.security_id, occurrence_id, component.component_id)
        )
        if not matches:
            # Delivered cash that no proven entitlement claims commits nothing.
            # Crediting it would create money from an unmatched report.
            return None
        if len(matches) > 1:
            # The key does not carry the action kind that claim identity
            # does, so one source can still hold two claims under it. Paying
            # either would be a guess.
            raise IndeterminateValuationError(
                "one delivered cash component matches more than one pending "
                f"claim: {source_id}/{occurrence_id}/{component.component_id}"
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


def _effect_contexts(
    outcome: SecurityEconomicOutcomeV1, *, include_before_window: bool = False
) -> list[_EffectContext]:
    """Bind every effective occurred effect in a supported outcome to its source.

    Both passes read effects through this one proof: the pre-open pass to
    apply them, and the settlement pass to show delivered cash no claim
    matches was never owed to this book. Only the settlement pass asks for
    effects M1c places before the evidence window, marked as such.

    An effective effect that fails the proof halts the run. A before-window
    effect is never applied, so one that fails it (or duplicates another
    report of its occurrence) is dropped instead: it proves nothing and so
    explains nothing, and a delivery that needed it still halts for want of
    an explanation. Halting on it would let one incomplete old record stop
    every later session that re-reads a delivered dividend.
    """
    resolution = outcome.resolution
    records = {content_hash(record): record for record in outcome.effect_records}
    terms: TermsIndex = {record.source_key: record for record in outcome.terms_records}
    applied: set[tuple[str, ActionKind]] = set()
    contexts: list[_EffectContext] = []
    earlier: list[_EffectContext] = []
    for projection in sorted(
        resolution.effect_projections, key=lambda item: item.source_record_hash
    ):
        if projection.effective_status == "indeterminate":
            raise IndeterminateValuationError(
                "effect projection effectiveness is indeterminate for "
                f"{outcome.security_id}"
            )
        record = records[projection.source_record_hash]
        if projection.effective_status == "effective":
            context = _proven_context(record, terms, before_window=False)
            marker = (context.occurrence_id, context.payload.action_kind)
            if marker in applied:
                # Two reports of one occurrence would apply one split twice.
                raise IndeterminateValuationError(
                    "economic outcome carries more than one effective report "
                    f"for one occurrence: {context.occurrence_id}"
                )
            applied.add(marker)
            contexts.append(context)
        elif projection.effective_status == "before_window" and include_before_window:
            try:
                earlier.append(_proven_context(record, terms, before_window=True))
            except IndeterminateValuationError:
                continue
    markers = [
        (context.occurrence_id, context.payload.action_kind) for context in earlier
    ]
    contexts.extend(
        context
        for context, marker in zip(earlier, markers, strict=True)
        if markers.count(marker) == 1 and marker not in applied
    )
    return contexts


def _proven_context(
    record: EconomicEffectVersionV1, terms: TermsIndex, *, before_window: bool
) -> _EffectContext:
    """Prove one occurred effect is safe to read, and bind it to its source."""
    payload = record.payload
    if not isinstance(payload, OccurredEffectV1):
        raise IndeterminateValuationError(
            "an effective economic projection requires an occurred effect payload"
        )
    occurrence_id = record.occurrence.native_occurrence_id
    if record.occurrence.kind != "identified" or occurrence_id is None:
        raise IndeterminateValuationError(
            "applying an occurred effect requires an identified source occurrence"
        )
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
    return _EffectContext(
        record=record,
        payload=payload,
        occurrence_id=occurrence_id,
        effective_on=boundary_session_date(
            record.effective_time, role="effect effective time"
        ),
        terms=terms,
        before_window=before_window,
    )


type _OwedKey = tuple[str, str, str]
type _OwedIndex = Mapping[_OwedKey, list[tuple[_EffectContext, EconomicComponentV1]]]


def _owed_index(outcome: SecurityEconomicOutcomeV1) -> _OwedIndex:
    """Index what each occurred effect owes, by the identity a delivery names.

    The key is ``(source_id, native_occurrence_id, component_id)``. A
    cash-in-lieu leg is reported under its share component id, so share
    components are indexed alongside cash ones.
    """
    index: dict[_OwedKey, list[tuple[_EffectContext, EconomicComponentV1]]] = {}
    for context in _effect_contexts(outcome, include_before_window=True):
        for component in context.payload.owed_components:
            key = (context.source_id, context.occurrence_id, component.component_id)
            index.setdefault(key, []).append((context, component))
    return index


def _share_action_conflicts(
    contexts: Iterable[_EffectContext], window: _SessionWindow
) -> tuple[_ShareActionConflict, ...]:
    """Every security two or more of the window's share actions touch.

    Actions are counted across every outcome of the pass, so a chain in
    which one outcome's acquirer is another outcome's subject counts too.
    """
    members: dict[UUID7, list[_EffectContext]] = {}
    for context in contexts:
        if context.payload.action_kind not in SHARE_MUTATING_KINDS:
            continue
        if _is_cash_distribution(context.payload):
            # A liquidation on a continuing claim changes no share count.
            continue
        if not window.contains(context.effective_on):
            continue
        # A split delivers into its own security; count each action once.
        for security_id in dict.fromkeys(_touched_securities(context)):
            members.setdefault(security_id, []).append(context)
    conflicts: list[_ShareActionConflict] = []
    for security_id in sorted(members, key=_security_order):
        found = members[security_id]
        if len(found) < 2:
            continue
        ordered = sorted(
            found,
            key=lambda item: (
                item.record.effective_time.lower_bound,
                item.payload.action_kind.value,
            ),
        )
        conflicts.append(
            _ShareActionConflict(
                security_id=security_id,
                dates=tuple(sorted({item.effective_on for item in found})),
                actions=tuple(item.payload.action_kind.value for item in ordered),
                touched=frozenset(
                    touched for item in found for touched in _touched_securities(item)
                ),
            )
        )
    return tuple(conflicts)


def _touched_securities(context: _EffectContext) -> tuple[UUID7, ...]:
    """The acted security and every security its share components deliver."""
    recipients = tuple(
        component.recipient.security_id
        for component in context.payload.owed_components
        if isinstance(component, ShareComponentV1)
        and component.recipient.security_id is not None
    )
    return (context.security_id, *recipients)


def _definitely_precedes(earlier: _EffectContext, later: _EffectContext) -> bool:
    """Whether one effect's instant is proven wholly before another's.

    This is the reading M1c's claim composition orders effects by.
    """
    upper = earlier.record.effective_time.upper_bound
    lower = later.record.effective_time.lower_bound
    return upper is not None and lower is not None and upper < lower


def _index_pending_claims(
    state: PortfolioStateV1,
) -> dict[_ClaimIndexKey, dict[SHA256Hash, PendingCashClaimV1]]:
    """Index pending claims by the identity a delivery group can name.

    ``PendingCashClaimV1`` and ``EconomicDeliveryGroupV1`` both carry a
    ``source_id``, and claim identity is itself source-scoped, so matching is
    too: a delivered report settles the claim raised by its own source and
    never one another source raised against the same native occurrence id. A
    cash-in-lieu leg is also indexed under the share component it came from,
    because a source reports the aggregate sale against that original
    component id.

    The key stays coarser than claim identity, which also carries the action
    kind that a delivery group never reports, so one key can still hold more
    than one claim. The caller fails closed when it does.
    """
    index: dict[_ClaimIndexKey, dict[SHA256Hash, PendingCashClaimV1]] = {}
    for claim in state.pending_cash_claims:
        keys = [
            (
                claim.source_id,
                claim.security_id,
                claim.occurrence_id,
                claim.component_id,
            )
        ]
        origin = cash_in_lieu_origin(claim.component_id)
        if origin is not None:
            keys.append(
                (claim.source_id, claim.security_id, claim.occurrence_id, origin)
            )
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
) -> SHA256Hash:
    """Derive one pending-claim identity under the ruled claim identity.

    Identity is ``(source_id, security_id, action_kind, occurrence_id,
    component_id)``. The entitlement and payable dates are revisable
    attributes and never part of identity, so a payable-date revision
    resolves by supersession of the same claim rather than by minting a
    second one.
    """
    return pending_cash_claim_id(
        source_id=source_id,
        security_id=security_id,
        action_kind=action_kind,
        occurrence_id=occurrence_id,
        component_id=component_id,
    )


def _translated_quantity(
    quantity: int, component: ShareComponentV1, tie_break: TieBreak | None
) -> int:
    """Translate a staged target quantity exactly as a holding of it would be.

    The ratio, its meaning, and the source fraction treatment are the ones the
    holding goes through. A fraction that treatment cannot resolve fails
    closed; a target is never rounded by any rule the source did not state.
    Any aggregate-sale residual is dropped, because a target is an intent and
    is owed no cash in lieu.
    """
    if quantity == 0:
        return 0
    whole, _ = resolve_whole_shares(
        exact_entitled_shares(quantity, component),
        component.fraction_treatment,
        tie_break=tie_break,
    )
    return whole


def _credit_target(
    book: _Book, security_id: UUID7, quantity: int, *, held: bool, label: str
) -> None:
    """Add translated shares to the staged target of the security receiving them.

    ``held`` says whether the receiving security was already held before the
    action. A staged decision covers every held security, so a held recipient
    without a target means the staged set was already incomplete. Treating
    its missing target as zero would sell a holding no decision named.
    """
    current = book.targets.get(security_id)
    if current is None and held:
        raise IndeterminateValuationError(
            f"a {label} translates a staged target into {security_id}, which is "
            "held without a staged target of its own"
        )
    base = 0 if current is None else current.target_quantity
    book.targets[security_id] = SecurityTargetPositionV1(
        security_id=security_id, target_quantity=base + quantity
    )


def _stages_a_buy(book: _Book, security_id: UUID7) -> bool:
    """Whether a security carries a positive staged target.

    Asked only of a security the book does not hold, where a positive target
    would buy it at the open. An explicit zero target there trades nothing, so
    it is no exposure, and halting on the action's evidence would be spurious.
    """
    target = book.targets.get(security_id)
    return target is not None and target.target_quantity > 0


def _extinguish_target(book: _Book, security_id: UUID7) -> None:
    """Set a staged target to zero once the claim it names has ended."""
    if security_id in book.targets:
        book.targets[security_id] = SecurityTargetPositionV1(
            security_id=security_id, target_quantity=0
        )


def _require_proven_post_action_count(
    context: _EffectContext, book: _Book, share_basis: str
) -> None:
    """Refuse a post-action share count the ex-date rule cannot prove entitled.

    The ex-date rule entitles the prior close's holdings, and M1c's share
    basis says only which share count the source divides its cash by. The
    count after the security's own continuing share action (a split, a
    reverse split, a stock dividend, or the parent's own spin-off, which
    leaves the parent's count unchanged) re-denominates those same
    holdings, so it is proven. Shares another outcome's action delivered in
    this window (into a spin-off child, or an acquirer) were not held at the
    prior close, so whether the source counts them is not proven. A holding
    the security's own disposal or share acquisition removed in this window
    leaves no post-action count at all, and dropping the distribution would
    be a guess too. Each halts the run; a pre-action quote is never asked.
    A quote whose basis the source did not state (``as_reported_unknown``)
    may be a post-action one, so it is asked too, and the halt names that
    basis.
    """
    quoted = (
        "per post-action share"
        if share_basis == "predecessor_post_action"
        else f"per share on the {share_basis} share basis"
    )
    label = (
        f"the {context.payload.action_kind.value} {context.occurrence_id} on "
        f"{context.security_id} quotes cash {quoted}"
    )
    delivering = book.delivered.get(context.security_id)
    if delivering is not None:
        raise IndeterminateValuationError(
            f"{label}, and the {delivering.payload.action_kind.value} "
            f"{delivering.occurrence_id} of {delivering.security_id} delivered "
            "shares into it in this window that the prior close did not hold, "
            "so whether they are entitled is not proven"
        )
    removing = book.removed.get(context.security_id)
    if removing is not None:
        raise IndeterminateValuationError(
            f"{label}, and the {removing.payload.action_kind.value} "
            f"{removing.occurrence_id} removed the holding in this window, so "
            "no post-action count is defined"
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
