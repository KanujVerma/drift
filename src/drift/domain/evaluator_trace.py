"""M2 canonical evaluation trace events and the content-addressed trace log.

A trace is the complete, replayable account of what one evaluation did. It
carries no wall-clock instants and no random identifiers: every timestamp in
it is a historical session boundary stated by the authority-bound clock, and
every identity is a content hash. Two runs over identical inputs therefore
produce byte-identical traces and one ``trace_hash``.

Each event states the session it belongs to and its position in the sequence.
Position is stated rather than implied so that a single event remains
meaningful when quoted on its own, and so that the log can refuse a sequence
that was reordered, truncated, or stitched together from two runs.
"""

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.evaluator_execution import ExecutionFillV1, FillRejectionV1
from drift.domain.evaluator_exploratory_accounting import (
    ExploratoryReconstructedAccountingPriceV1,
)
from drift.domain.evaluator_exploratory_strategy import (
    EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
    RECONSTRUCTED_DECISION_LIMITATIONS,
    ExploratoryReconstructedEvidenceGrade,
)
from drift.domain.evaluator_portfolio import CanonicalMoney, decimal_context
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

ZERO = Decimal("0")


class EvaluationPhase(StrEnum):
    """The five canonical per-session evaluation phases, in execution order."""

    PRE_OPEN_EFFECTS = "pre_open_effects"
    OPEN_EXECUTION = "open_execution"
    INTRASESSION_ECONOMIC_EFFECTS = "intrasession_economic_effects"
    CLOSE_MARK = "close_mark"
    POST_CLOSE_DECISION = "post_close_decision"


def _security_order(security_id: UUID) -> bytes:
    """Canonical collection order for securities: raw UUID bytes."""
    return security_id.bytes


def _canonical_targets(
    values: tuple[SecurityTargetPositionV1, ...], label: str
) -> tuple[SecurityTargetPositionV1, ...]:
    securities = tuple(item.security_id for item in values)
    if len(set(securities)) != len(securities):
        raise ValueError(f"{label} must be unique by security")
    return tuple(sorted(values, key=lambda item: _security_order(item.security_id)))


def _canonical_digests(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(values))


class _TraceEventBaseV1(FrozenModel):
    """Fields every trace event carries: its position and its session."""

    schema_version: Literal["1"] = "1"
    sequence: int = Field(ge=0)
    session_index: int = Field(ge=0)
    session_key: SessionKeyV1


class SessionStartTraceEventV1(_TraceEventBaseV1):
    """One evaluation session opened, with the book it opened against.

    The opening net asset value is taken before this session is marked, so it
    values cash and proven pending entitlements only. A stale mark from the
    previous session is never carried into it.
    """

    kind: Literal["session_start"] = "session_start"
    session_hash: SHA256Hash
    opening_cash: CanonicalMoney
    opening_net_asset_value: CanonicalMoney


class CorporateActionAppliedTraceEventV1(_TraceEventBaseV1):
    """One pre-open pass that actually moved shares, targets, or claims.

    A pass that changed nothing does not emit this event. Recording a no-op as
    an applied corporate action would let a reader infer a mutation the
    evidence never proved.
    """

    kind: Literal["corporate_action_applied"] = "corporate_action_applied"
    holdings_hash_before: SHA256Hash
    holdings_hash_after: SHA256Hash
    staged_targets_before: tuple[SecurityTargetPositionV1, ...]
    staged_targets_after: tuple[SecurityTargetPositionV1, ...]
    recorded_claim_ids: tuple[SHA256Hash, ...]

    @field_validator("staged_targets_before", "staged_targets_after")
    @classmethod
    def canonicalize_targets(
        cls, values: tuple[SecurityTargetPositionV1, ...]
    ) -> tuple[SecurityTargetPositionV1, ...]:
        return _canonical_targets(values, "staged targets")

    @field_validator("recorded_claim_ids")
    @classmethod
    def canonicalize_claim_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values, "recorded claim ids")

    @model_validator(mode="after")
    def require_a_mutation(self) -> Self:
        if (
            self.holdings_hash_before == self.holdings_hash_after
            and self.staged_targets_before == self.staged_targets_after
            and not self.recorded_claim_ids
        ):
            raise ValueError(
                "corporate action event records no mutation to shares, staged "
                "targets, or cash claims"
            )
        return self


class FillTraceEventV1(_TraceEventBaseV1):
    """One committed whole-share fill, in its canonical commit position."""

    kind: Literal["fill"] = "fill"
    commit_index: int = Field(ge=0)
    fill: ExecutionFillV1


class FillRejectionTraceEventV1(_TraceEventBaseV1):
    """One complete rebalance intent refused for want of cash.

    Zero fills were committed. The event carries the whole solvency
    computation, so the shortfall can be audited term by term.
    """

    kind: Literal["fill_rejection"] = "fill_rejection"
    rejection: FillRejectionV1

    @model_validator(mode="after")
    def bind_rejected_session(self) -> Self:
        if self.rejection.session_key != self.session_key:
            raise ValueError(
                "a rejection must describe its own session: event holds "
                f"{self.session_key.local_date}, rejection holds "
                f"{self.rejection.session_key.local_date}"
            )
        return self


class ClaimSettledTraceEventV1(_TraceEventBaseV1):
    """Cash entitlements whose delivered settlement evidence paid them."""

    kind: Literal["claim_settled"] = "claim_settled"
    claim_ids: tuple[SHA256Hash, ...]
    settled_cash: CanonicalMoney

    @field_validator("claim_ids")
    @classmethod
    def canonicalize_claim_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("a settlement event requires a claim")
        return _canonical_digests(values, "settled claim ids")

    @model_validator(mode="after")
    def require_settled_cash(self) -> Self:
        with decimal_context():
            if self.settled_cash <= ZERO:
                raise ValueError(
                    f"settled cash must be strictly positive, got {self.settled_cash}"
                )
        return self


class SessionMarkTraceEventV1(_TraceEventBaseV1):
    """The evidence-bound close mark and net asset value for one session."""

    kind: Literal["session_mark"] = "session_mark"
    mark_hash: SHA256Hash
    cash_balance: CanonicalMoney
    holdings_market_value: CanonicalMoney
    pending_claims_value: CanonicalMoney
    net_asset_value: CanonicalMoney

    @model_validator(mode="after")
    def reconcile_net_asset_value(self) -> Self:
        with decimal_context():
            expected = (
                self.cash_balance
                + self.holdings_market_value
                + self.pending_claims_value
            )
            if self.net_asset_value != expected:
                raise ValueError(
                    f"mark net asset value must reconcile to {expected}, got "
                    f"{self.net_asset_value}"
                )
        return self


class StrategyDecisionTraceEventV1(_TraceEventBaseV1):
    """One post-close strategy decision, staged or refused.

    A refused intent stages nothing. It is a scientifically meaningful
    outcome, not an indeterminacy: the evaluator knows exactly what the
    strategy asked for and knows the contract forbids it.
    """

    kind: Literal["strategy_decision"] = "strategy_decision"
    decision_cutoff: UTCDateTime
    context_hash: SHA256Hash
    intent_hash: SHA256Hash
    outcome: Literal["staged", "rejected"]
    staged_targets: tuple[SecurityTargetPositionV1, ...] = ()
    rejection_reason: NonBlankStr | None = None

    @field_validator("staged_targets")
    @classmethod
    def canonicalize_targets(
        cls, values: tuple[SecurityTargetPositionV1, ...]
    ) -> tuple[SecurityTargetPositionV1, ...]:
        return _canonical_targets(values, "staged targets")

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> Self:
        if self.outcome == "rejected":
            if self.rejection_reason is None:
                raise ValueError("a rejected decision requires its reason")
            if self.staged_targets:
                raise ValueError("a rejected decision stages no target")
            return self
        if self.rejection_reason is not None:
            raise ValueError("a staged decision carries no rejection reason")
        return self


class ExploratoryStrategyDecisionTraceEventV1(_TraceEventBaseV1):
    """One post-close decision taken on EXPLORATORY-only reconstructed evidence.

    A distinct event kind, never a ``StrategyDecisionTraceEventV1``: a trace
    that recorded both grades under one kind would let a reader take a
    decision made on retrospectively reconstructed bars for one made on
    authentic decision evidence. The event names every reconstruction the
    strategy was shown and every limitation the decision carries, so the
    weaker grade stays auditable from the trace alone, not only by reopening
    the context behind ``context_hash``.
    """

    kind: Literal["exploratory_strategy_decision"] = "exploratory_strategy_decision"
    evidence_grade: ExploratoryReconstructedEvidenceGrade = (
        EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE
    )
    is_promotion_grade_evidence: Literal[False] = False
    decision_cutoff: UTCDateTime
    context_hash: SHA256Hash
    intent_hash: SHA256Hash
    reconstruction_hashes: tuple[SHA256Hash, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]
    outcome: Literal["staged", "rejected"]
    staged_targets: tuple[SecurityTargetPositionV1, ...] = ()
    rejection_reason: NonBlankStr | None = None

    @field_validator("staged_targets")
    @classmethod
    def canonicalize_targets(
        cls, values: tuple[SecurityTargetPositionV1, ...]
    ) -> tuple[SecurityTargetPositionV1, ...]:
        return _canonical_targets(values, "staged targets")

    @field_validator("reconstruction_hashes")
    @classmethod
    def canonicalize_reconstructions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError(
                "an exploratory decision event must name the reconstructions it read"
            )
        return _canonical_digests(values, "reconstruction hashes")

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values, "acknowledged limitations")

    @model_validator(mode="after")
    def validate_exploratory_decision(self) -> Self:
        missing = tuple(
            sorted(
                set(RECONSTRUCTED_DECISION_LIMITATIONS)
                - set(self.acknowledged_limitations)
            )
        )
        if missing:
            raise ValueError(
                f"an exploratory decision event omits required limitations: {missing}"
            )
        if self.outcome == "rejected":
            if self.rejection_reason is None:
                raise ValueError("a rejected decision requires its reason")
            if self.staged_targets:
                raise ValueError("a rejected decision stages no target")
            return self
        if self.rejection_reason is not None:
            raise ValueError("a staged decision carries no rejection reason")
        return self


class ExploratoryAccountingPriceTraceEventV1(_TraceEventBaseV1):
    """The EXPLORATORY reconstructed prices one accounting phase consumed.

    Issue 54: in the reconstructed lane the open execution phase prices fills,
    and the close mark phase prices holdings, from verified reconstructions.
    The fill and mark events that follow carry only numbers, so this distinct
    event names every price record they read, in full, and the weaker grade
    stays auditable from the trace alone.
    """

    kind: Literal["exploratory_accounting_price"] = "exploratory_accounting_price"
    evidence_grade: ExploratoryReconstructedEvidenceGrade = (
        EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE
    )
    is_promotion_grade_evidence: Literal[False] = False
    phase: Literal[EvaluationPhase.OPEN_EXECUTION, EvaluationPhase.CLOSE_MARK]
    prices: tuple[ExploratoryReconstructedAccountingPriceV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]

    @field_validator("prices")
    @classmethod
    def canonicalize_prices(
        cls, values: tuple[ExploratoryReconstructedAccountingPriceV1, ...]
    ) -> tuple[ExploratoryReconstructedAccountingPriceV1, ...]:
        if not values:
            raise ValueError(
                "an exploratory accounting price event must name the prices it read"
            )
        securities = tuple(item.security_id for item in values)
        if len(set(securities)) != len(securities):
            raise ValueError("exploratory accounting prices must be unique by security")
        return tuple(sorted(values, key=lambda item: _security_order(item.security_id)))

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_price_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values, "acknowledged limitations")

    @model_validator(mode="after")
    def validate_exploratory_prices(self) -> Self:
        missing = tuple(
            sorted(
                set(RECONSTRUCTED_DECISION_LIMITATIONS)
                - set(self.acknowledged_limitations)
            )
        )
        if missing:
            raise ValueError(
                "an exploratory accounting price event omits required "
                f"limitations: {missing}"
            )
        role = "open" if self.phase is EvaluationPhase.OPEN_EXECUTION else "close"
        for price in self.prices:
            if price.field_role != role:
                raise ValueError(
                    f"the {self.phase.value} phase reads {role} prices, not "
                    f"{price.field_role} for security {price.security_id}"
                )
            if price.session_key != self.session_key:
                raise ValueError(
                    f"an exploratory accounting price for security "
                    f"{price.security_id} belongs to another session"
                )
        return self


class IndeterminateCauseTraceEventV1(_TraceEventBaseV1):
    """The exact phase and cause that made an outcome unprovable."""

    kind: Literal["indeterminate_cause"] = "indeterminate_cause"
    phase: EvaluationPhase
    cause_kind: Literal["indeterminate_valuation", "indeterminate_execution"]
    cause: NonBlankStr


type EvaluatorTraceEventV1 = Annotated[
    SessionStartTraceEventV1
    | CorporateActionAppliedTraceEventV1
    | FillTraceEventV1
    | FillRejectionTraceEventV1
    | ClaimSettledTraceEventV1
    | SessionMarkTraceEventV1
    | StrategyDecisionTraceEventV1
    | ExploratoryStrategyDecisionTraceEventV1
    | ExploratoryAccountingPriceTraceEventV1
    | IndeterminateCauseTraceEventV1,
    Field(discriminator="kind"),
]


def evaluation_trace_log_hash(log: EvaluationTraceLogV1) -> SHA256Hash:
    """Compute the self-excluding canonical content hash for a trace log."""
    dump = log.model_dump(mode="python")
    dump.pop("trace_hash", None)
    return content_hash(dump)


class EvaluationTraceLogV1(FrozenModel):
    """The complete, ordered, content-addressed trace of one evaluation."""

    schema_version: Literal["1"] = "1"
    events: tuple[EvaluatorTraceEventV1, ...]
    trace_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_log(self) -> Self:
        self._validate_sequence()
        expected = evaluation_trace_log_hash(self)
        if self.trace_hash != expected:
            raise ValueError(
                f"trace hash mismatch: expected {expected}, got {self.trace_hash}"
            )
        return self

    def _validate_sequence(self) -> None:
        """Bind every event to the session it was emitted under.

        An event can only belong to a session the trace already opened, and
        sessions open once each, contiguously from zero. Without this a trace
        could attribute a fill to a session that never started, or splice two
        partial runs into one log that still hashes cleanly.
        """
        if not self.events:
            raise ValueError("a trace log requires at least one event")
        opened = -1
        open_key: SessionKeyV1 | None = None
        for position, event in enumerate(self.events):
            if event.sequence != position:
                raise ValueError(
                    "trace event sequence must be contiguous from zero: "
                    f"position {position} declares sequence {event.sequence}"
                )
            if event.kind == "session_start":
                if event.session_index != opened + 1:
                    raise ValueError(
                        "trace session index must advance by one: expected "
                        f"{opened + 1}, got {event.session_index}"
                    )
                opened = event.session_index
                open_key = event.session_key
            else:
                if open_key is None:
                    raise ValueError("a trace must open a session before any event")
                if event.session_index != opened:
                    raise ValueError(
                        "a trace event belongs to the open session "
                        f"{opened}, got {event.session_index}"
                    )
            if event.session_key != open_key:
                raise ValueError(
                    "a trace event session key must match its open session"
                )


def seal_evaluation_trace_log(
    events: Sequence[EvaluatorTraceEventV1],
) -> EvaluationTraceLogV1:
    """Seal an ordered event sequence into its content-addressed trace log.

    Sequence numbers are the caller's, not this function's. The emitter knows
    where each event belongs, and assigning positions here would make the
    contiguity rule unfalsifiable through the public construction path.
    """
    draft = EvaluationTraceLogV1.model_construct(
        schema_version="1", events=tuple(events), trace_hash="0" * 64
    )
    sealed = EvaluationTraceLogV1.model_construct(
        **(dict(draft) | {"trace_hash": evaluation_trace_log_hash(draft)})
    )
    return EvaluationTraceLogV1.model_validate(dict(sealed))
