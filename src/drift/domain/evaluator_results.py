"""M2 evaluation classification, summary metrics, and lane-bound results.

A result artifact states only what the inputs and historical facts determine.
It carries no random identifier and no wall-clock completion time: identity is
the content hash of the artifact itself, and the operational metadata of an
execution (``run_id``, ``started_at``, ``completed_at``) belongs to the M0
``ExperimentRun`` that references this artifact. Replaying one evaluation under
two different experiment runs therefore yields one ``result_hash``.

The two result models are separate types rather than one type with a lane
field, so a promotion-grade claim cannot be assembled from exploratory
admission evidence by assignment.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.evaluator_bundles import EvaluationRunIdentity
from drift.domain.evaluator_lanes import (
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
)
from drift.domain.evaluator_portfolio import (
    CanonicalMoney,
    EvaluationLane,
    MarkEvidenceGrade,
    PortfolioStateV1,
    decimal_context,
)
from drift.domain.evaluator_trace import EvaluationTraceLogV1
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

ZERO = Decimal("0")

#: The mark grade a run in each lane grants its valuations. The engine reads a
#: mark's grade from its admission (``LANE_MARK_GRADE`` in the engine), so an
#: exploratory run never marks promotion-grade, although the exploratory lane
#: admits promotion-grade evidence. A result's final book may carry no other
#: grade (issue 124).
LANE_GRANTED_MARK_GRADE: dict[EvaluationLane, MarkEvidenceGrade] = {
    "exploratory": "exploratory",
    "promotion": "promotion_grade",
}


class EvaluationClassification(StrEnum):
    """The scientific outcome of one evaluation run.

    ``INDETERMINATE`` is a distinct answer from ``REJECTED``. A rejection is
    fully evidenced: the intent was unfunded, or the contract forbade it. An
    indeterminacy means the evaluator cannot know what would have happened
    and refuses to invent it.
    """

    COMPLETE = "complete"
    INDETERMINATE = "indeterminate"
    REJECTED = "rejected"


class SessionEquityPointV1(FrozenModel):
    """The marked book at the close of one evaluated session."""

    schema_version: Literal["1"] = "1"
    session_index: int = Field(ge=0)
    session_key: SessionKeyV1
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
                    f"equity point net asset value must reconcile to {expected}, "
                    f"got {self.net_asset_value}"
                )
        return self


class EvaluationSummaryMetricsV1(FrozenModel):
    """Exact terminal and per-session results of one evaluation.

    Every figure describes the sessions the evaluation actually completed. A
    halted run reports the book as of its last marked session, so the metrics
    never quote a partially stepped session as if it had closed.
    """

    schema_version: Literal["1"] = "1"
    evaluated_session_count: int = Field(ge=0)
    initial_cash: CanonicalMoney
    initial_net_asset_value: CanonicalMoney
    ending_cash: CanonicalMoney
    ending_net_asset_value: CanonicalMoney
    net_profit_and_loss: CanonicalMoney
    realized_gross_pnl: CanonicalMoney
    realized_net_pnl: CanonicalMoney
    cumulative_transaction_costs: CanonicalMoney
    gross_traded_notional: CanonicalMoney
    committed_fill_count: int = Field(ge=0)
    equity_series: tuple[SessionEquityPointV1, ...]

    @field_validator("equity_series")
    @classmethod
    def canonicalize_series(
        cls, values: tuple[SessionEquityPointV1, ...]
    ) -> tuple[SessionEquityPointV1, ...]:
        for position, point in enumerate(values):
            if point.session_index != position:
                raise ValueError(
                    "equity series must run contiguously from session zero: "
                    f"position {position} declares {point.session_index}"
                )
        return values

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        with decimal_context():
            return self._validate_under_pinned_context()

    def _validate_under_pinned_context(self) -> Self:
        if self.evaluated_session_count != len(self.equity_series):
            raise ValueError(
                "evaluated session count must equal the equity series length: "
                f"{self.evaluated_session_count} against {len(self.equity_series)}"
            )
        if self.cumulative_transaction_costs < ZERO:
            raise ValueError("cumulative transaction costs must be non-negative")
        if self.gross_traded_notional < ZERO:
            raise ValueError("gross traded notional must be non-negative")
        # Turnover without a fill is money that never traded.
        if self.committed_fill_count == 0 and self.gross_traded_notional != ZERO:
            raise ValueError(
                "gross traded notional requires at least one committed fill"
            )
        if self.committed_fill_count > 0 and self.gross_traded_notional <= ZERO:
            raise ValueError("a committed fill requires positive traded notional")

        if self.equity_series:
            last = self.equity_series[-1]
            if self.ending_cash != last.cash_balance:
                raise ValueError(
                    "ending cash must equal the last marked session "
                    f"{last.cash_balance}"
                )
            if self.ending_net_asset_value != last.net_asset_value:
                raise ValueError(
                    "ending net asset value must equal the last marked session "
                    f"{last.net_asset_value}"
                )
        else:
            if self.ending_cash != self.initial_cash:
                raise ValueError(
                    "an evaluation that marked no session ends at its initial cash"
                )
            if self.ending_net_asset_value != self.initial_net_asset_value:
                raise ValueError(
                    "an evaluation that marked no session ends at its initial "
                    "net asset value"
                )

        expected_pnl = self.ending_net_asset_value - self.initial_net_asset_value
        if self.net_profit_and_loss != expected_pnl:
            raise ValueError(
                f"net profit and loss must equal {expected_pnl}, "
                f"got {self.net_profit_and_loss}"
            )
        return self


def evaluation_result_hash(result: EvaluationResultV1) -> SHA256Hash:
    """Compute the self-excluding canonical content hash for a result."""
    dump = result.model_dump(mode="python")
    dump.pop("result_hash", None)
    return content_hash(dump)


class _EvaluationResultBaseV1(FrozenModel):
    """Deterministic fields shared by both lane-bound result artifacts."""

    schema_version: Literal["1"] = "1"
    # Either identity version (issue 112). A V1 identity dumps exactly as it
    # did when this field admitted only V1, so every V1 result hash is
    # unchanged; a V2 run's result carries its V2 identity.
    run_identity: EvaluationRunIdentity
    classification: EvaluationClassification
    halted_session_index: int | None = Field(default=None, ge=0)
    halt_reason: NonBlankStr | None = None
    metrics: EvaluationSummaryMetricsV1
    trace_hash: SHA256Hash
    result_hash: SHA256Hash

    @property
    def result_id(self) -> SHA256Hash:
        """Content-addressed identity of this result artifact."""
        return self.result_hash

    def _validate_common(self, admission_hash: SHA256Hash) -> None:
        if self.run_identity.admission_hash != admission_hash:
            raise ValueError(
                "result run identity must bind the admission it carries: "
                f"identity holds {self.run_identity.admission_hash}, admission "
                f"is {admission_hash}"
            )
        # A halted run must say where and why it stopped, and a complete run
        # must not claim a halt it never took.
        halted = self.classification is not EvaluationClassification.COMPLETE
        if halted and (self.halted_session_index is None or self.halt_reason is None):
            raise ValueError(
                f"a {self.classification.value} result requires the session it "
                "halted on and the reason it halted"
            )
        if not halted and (
            self.halted_session_index is not None or self.halt_reason is not None
        ):
            raise ValueError("a complete result cannot declare a halt")
        # A complete run stepped and marked every session it was given. An
        # empty series with a COMPLETE verdict would be a result that
        # evaluated nothing while claiming the strongest classification.
        if not halted and self.metrics.evaluated_session_count == 0:
            raise ValueError("a complete result requires at least one marked session")
        # Stepping stops at the halting session, so a run cannot have marked
        # more sessions than it reached. Without this a halted result could
        # quote an equity series longer than the run that produced it.
        if (
            self.halted_session_index is not None
            and self.metrics.evaluated_session_count > self.halted_session_index + 1
        ):
            raise ValueError(
                "a halted result cannot mark more sessions than it stepped: "
                f"halted at {self.halted_session_index} with "
                f"{self.metrics.evaluated_session_count} marked sessions"
            )
        expected = evaluation_result_hash(self)  # type: ignore[arg-type]
        if self.result_hash != expected:
            raise ValueError(
                f"result hash mismatch: expected {expected}, got {self.result_hash}"
            )


class ExploratoryEvaluationResultV1(_EvaluationResultBaseV1):
    """An exploratory-lane evaluation result.

    Exploratory evidence never carries promotion weight, so the flag is a
    literal rather than a settable field: no assignment can raise this
    artifact's standing.
    """

    lane: Literal["exploratory"] = "exploratory"
    is_promotion_grade_evidence: Literal[False] = False
    admission: ExploratoryEvaluationAdmissionV1

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        self._validate_common(self.admission.admission_hash)
        return self


class PromotionEvaluationResultV1(_EvaluationResultBaseV1):
    """A promotion-lane evaluation result.

    Promotion grade is a statement about the evidence lane the inputs
    qualified under. It is not a strategy approval, and nothing downstream may
    read it as one.
    """

    lane: Literal["promotion"] = "promotion"
    is_promotion_grade_evidence: Literal[True] = True
    admission: PromotionEvaluationAdmissionV1

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        self._validate_common(self.admission.admission_hash)
        return self


type EvaluationResultV1 = Annotated[
    ExploratoryEvaluationResultV1 | PromotionEvaluationResultV1,
    Field(discriminator="lane"),
]


class EvaluationRunArtifactsV1(FrozenModel):
    """The complete deterministic output of one evaluation run.

    The result binds its trace by hash only, so the two artifacts can be
    retained separately. This pair keeps them together at the call boundary
    and proves the binding holds.
    """

    schema_version: Literal["1"] = "1"
    result: EvaluationResultV1
    trace: EvaluationTraceLogV1
    final_state: PortfolioStateV1

    @model_validator(mode="after")
    def bind_trace(self) -> Self:
        if self.result.trace_hash != self.trace.trace_hash:
            raise ValueError(
                "result must bind the trace it is paired with: result holds "
                f"{self.result.trace_hash}, trace is {self.trace.trace_hash}"
            )
        if self.final_state.admission_hash != self.result.admission.admission_hash:
            raise ValueError(
                "final portfolio state must carry the admitted lane of its result"
            )
        self._bind_final_state_lane()
        self._bind_stepped_sessions()
        self._bind_decision_evidence_grade()
        return self

    def _bind_final_state_lane(self) -> None:
        """Pair the final book with its result's lane, not only its hash (#124).

        The admission hash alone leaves the book free to name another lane,
        or to grade its marks above what its result's run grants, so an
        exploratory result could travel with a book reading promotion-grade.
        """
        lane = self.result.lane
        if self.final_state.lane != lane:
            raise ValueError(
                f"final portfolio state is in the {self.final_state.lane} lane, "
                f"its result is in the {lane} lane"
            )
        mark = self.final_state.mark
        if mark is None:
            return
        granted = LANE_GRANTED_MARK_GRADE[lane]
        for price in mark.prices:
            if price.evidence.grade != granted:
                raise ValueError(
                    f"a result in the {lane} lane grants {granted} marks, its "
                    f"final state marks security {price.security_id} "
                    f"{price.evidence.grade}"
                )

    def _bind_decision_evidence_grade(self) -> None:
        """Refuse a promotion result traced on weaker decisions or prices.

        Decisions taken on EXPLORATORY reconstructed evidence are traced under
        their own event kind. A promotion result bound to such a trace would
        present decisions made on retrospectively reconstructed bars as
        promotion-grade, which the Absolute Non-Upgrade Rule forbids. The
        engine never builds this pairing; refusing it here keeps the artifact
        types from accepting one that was assembled any other way.
        """
        if self.result.lane != "promotion":
            return
        weaker = sum(
            1
            for event in self.trace.events
            if event.kind == "exploratory_strategy_decision"
        )
        if weaker:
            raise ValueError(
                "a promotion result cannot bind a trace of decisions taken on "
                f"EXPLORATORY reconstructed evidence: {weaker} "
                "exploratory_strategy_decision events"
            )
        # Issue 54: fills and marks priced from reconstructions are traced under
        # their own kind too, and a promotion result may not carry that PnL.
        priced = sum(
            1
            for event in self.trace.events
            if event.kind == "exploratory_accounting_price"
        )
        if priced:
            raise ValueError(
                "a promotion result cannot bind a trace of accounting priced on "
                f"EXPLORATORY reconstructed evidence: {priced} "
                "exploratory_accounting_price events"
            )

    def _bind_stepped_sessions(self) -> None:
        """Bind the last session the trace opened to the result's own account.

        The result states how far the run got; the trace shows it. Checking
        the hash alone leaves the two free to disagree about that, so a result
        could claim a clean four-session run while carrying the trace of a run
        that halted on session one.
        """
        last_opened = max(
            (
                event.session_index
                for event in self.trace.events
                if event.kind == "session_start"
            ),
            default=-1,
        )
        halted = self.result.halted_session_index
        expected = (
            halted
            if halted is not None
            else self.result.metrics.evaluated_session_count - 1
        )
        if last_opened != expected:
            raise ValueError(
                "the trace must open exactly the sessions the result accounts "
                f"for: trace reached session {last_opened}, result states "
                f"{expected}"
            )
