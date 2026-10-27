"""Controlled synthetic campaign integration and real execution-boundary tests."""

import sys
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_evaluator_engine import (  # noqa: E402
    _buy_ten,
    _engine,
    _run_identity,
)

from drift.domain.evaluator_results import (  # noqa: E402
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.evaluator.engine import SessionEvaluatorEngine  # noqa: E402
from drift.evaluator.session_observer import (  # noqa: E402
    ExecutionAuthorizationV1,
    RebalancePreviewV1,
    SessionObservationV1,
)


class RecordingObserver:
    def __init__(
        self, verdict: Literal["approve", "reject", "contain"] = "approve"
    ) -> None:
        self.verdict = verdict
        self.observations: list[SessionObservationV1] = []
        self.previews: list[RebalancePreviewV1] = []

    def observe_session(self, observation: SessionObservationV1) -> None:
        self.observations.append(observation)

    def authorize_rebalance(
        self, preview: RebalancePreviewV1
    ) -> ExecutionAuthorizationV1:
        self.previews.append(preview)
        return ExecutionAuthorizationV1(
            preview_hash=preview.financial_hash,
            policy_hash="a" * 64,
            verdict=self.verdict,
            reason="Explicit synthetic test policy",
        )


def run_observed(
    engine: SessionEvaluatorEngine, observer: RecordingObserver | None
) -> EvaluationRunArtifactsV2:
    return engine.run(
        strategy=_buy_ten(),
        run_identity=_run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
        session_observer=observer,
    )


def test_observer_approves_exact_atomic_outcome_and_preserves_financial_book() -> None:
    observer = RecordingObserver()
    actual = run_observed(_engine(), observer)
    legacy = run_observed(_engine(), None)
    assert actual.final_state == legacy.final_state
    assert actual.result.metrics == legacy.result.metrics
    assert len(observer.observations) == len(_engine().bundle.session_clock.sessions)
    assert observer.previews
    for observation in observer.observations:
        assert observation.state.is_marked
        assert observation.trace_prefix[-1].kind == "session_mark"
    for preview in observer.previews:
        assert preview.open_prices
        assert preview.decision_session.closed_at < preview.session.opened_at
    assert any(event.kind == "execution_authorization" for event in actual.trace.events)
    assert not any(
        event.kind == "execution_authorization" for event in legacy.trace.events
    )


def test_rejected_open_preview_commits_no_fill_and_preserves_cash() -> None:
    observer = RecordingObserver("reject")
    result = run_observed(_engine(), observer)
    assert result.result.classification == EvaluationClassification.COMPLETE
    assert result.result.metrics.committed_fill_count == 0
    assert result.final_state.holdings == ()
    assert result.final_state.cash_balance == Decimal("10000")
    assert observer.previews[0].outcome.committed_fills


def test_containment_stops_before_any_fill() -> None:
    result = run_observed(_engine(), RecordingObserver("contain"))
    assert result.result.classification == EvaluationClassification.INDETERMINATE
    assert result.result.metrics.committed_fill_count == 0
    assert result.final_state.holdings == ()


def test_wrong_preview_authorization_refuses_before_commit() -> None:
    class WrongPreview(RecordingObserver):
        def authorize_rebalance(
            self, preview: RebalancePreviewV1
        ) -> ExecutionAuthorizationV1:
            return (
                super()
                .authorize_rebalance(preview)
                .model_copy(update={"preview_hash": "b" * 64})
            )

    with pytest.raises(ValueError, match="PREVIEW"):
        run_observed(_engine(), WrongPreview())


def test_observer_receives_detached_book_and_outcome() -> None:
    class MutatingObserver(RecordingObserver):
        def observe_session(self, observation: SessionObservationV1) -> None:
            object.__setattr__(observation.state, "cash_balance", Decimal("1"))

        def authorize_rebalance(
            self, preview: RebalancePreviewV1
        ) -> ExecutionAuthorizationV1:
            original_hash = preview.financial_hash
            object.__setattr__(preview.outcome.state, "cash_balance", Decimal("2"))
            return ExecutionAuthorizationV1(
                preview_hash=original_hash,
                policy_hash="a" * 64,
                verdict="approve",
                reason="Mutation cannot change captured accounting",
            )

    actual = run_observed(_engine(), MutatingObserver())
    assert actual.final_state == run_observed(_engine(), None).final_state


def test_observer_failure_cannot_authorize_fill() -> None:
    class FailingObserver(RecordingObserver):
        def authorize_rebalance(
            self, preview: RebalancePreviewV1
        ) -> ExecutionAuthorizationV1:
            raise OSError("synthetic retention failure")

    with pytest.raises(OSError, match="retention failure"):
        run_observed(_engine(), FailingObserver())
