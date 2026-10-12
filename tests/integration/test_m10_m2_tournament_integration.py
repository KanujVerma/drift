"""Integration tests for M10 TournamentRunner consuming M2TrialEvaluatorAdapter.

Validates that TournamentRunner operates against real M2 deterministic evaluation
artifacts, enforces strict evidence bindings (cost model hash, result hash,
trace hash, bundle hash, session calendar consistency), and refuses matches
with incomplete or mismatched evidence.
"""

import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

_UNIT_PATH = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_PATH) not in sys.path:
    sys.path.insert(0, str(_UNIT_PATH))

from test_evaluator_engine import (  # noqa: E402
    SEC_A,
    _cost_model,
    _engine,
)

from drift.domain.tournament import (  # noqa: E402
    TournamentConfigV1,
    TournamentDecision,
    TournamentParticipantV1,
    build_tournament_config,
    build_tournament_participant,
)
from drift.loop.evaluator_adapter import (  # noqa: E402
    M2TrialEvaluatorAdapter,
)
from drift.tournament.runner import (  # noqa: E402
    TournamentRunner,
    _participant_to_experiment,
)

TIMESTAMP_START = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)
TIMESTAMP_END = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
TOURNAMENT_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd20")
CHAMPION_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd21")
CHALLENGER_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd22")


def _build_participants() -> tuple[TournamentParticipantV1, TournamentParticipantV1]:
    champ = build_tournament_participant(
        participant_id=CHAMPION_ID,
        strategy_type="b0_cash",
        parameters={},
        is_incumbent_champion=True,
    )
    chall = build_tournament_participant(
        participant_id=CHALLENGER_ID,
        strategy_type="b1_single_buy_and_hold",
        parameters={"target_security_id": str(SEC_A)},
        is_incumbent_champion=False,
    )
    return champ, chall


def _build_tournament_config() -> TournamentConfigV1:
    return build_tournament_config(
        tournament_id=TOURNAMENT_ID,
        created_at=TIMESTAMP_START,
        min_delta_sharpe=Decimal("0.10"),
        min_evaluation_sessions=10,
    )


def test_m10_tournament_runner_consumes_m2_adapter_with_real_artifacts() -> None:
    """TournamentRunner consumes M2TrialEvaluatorAdapter with authentic evidence."""
    engine = _engine()
    adapter = M2TrialEvaluatorAdapter(engine=engine)
    config = _build_tournament_config()

    champ, chall = _build_participants()
    runner = TournamentRunner(
        config=config,
        evaluator=adapter,
        require_genuine_evidence=True,
    )

    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    # Verify adapter exposes genuine evidence metadata
    assert record.decision != TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert not any("mock" in r.lower() for r in record.rejection_reasons)
    assert not any("cost model" in r.lower() for r in record.rejection_reasons)
    assert not any("calendar" in r.lower() for r in record.rejection_reasons)
    assert not any("bundle" in r.lower() for r in record.rejection_reasons)


def test_m2_adapter_exposes_result_hash_and_trace_hash() -> None:
    """M2TrialEvaluatorAdapter exposes result_hash and trace_hash in trial metrics."""
    engine = _engine()
    adapter = M2TrialEvaluatorAdapter(engine=engine)
    champ, _ = _build_participants()
    exp_champ = _participant_to_experiment(champ, TIMESTAMP_START)
    metrics = adapter.evaluate_experiment(exp_champ)

    assert metrics["is_mock"] is False
    assert metrics["classification"] == "complete"
    assert isinstance(metrics["result_hash"], str)
    assert len(metrics["result_hash"]) == 64
    assert isinstance(metrics["trace_hash"], str)
    assert len(metrics["trace_hash"]) == 64
    assert isinstance(metrics["bundle_hash"], str)
    assert len(metrics["bundle_hash"]) == 64
    assert isinstance(metrics["cost_model_hash"], str)
    assert len(metrics["cost_model_hash"]) == 64
    assert isinstance(metrics["session_keys"], tuple)
    assert len(metrics["session_keys"]) == len(engine.bundle.session_clock.sessions)
    assert len(metrics["session_returns"]) == len(metrics["session_keys"])


class _DualEngineRoutingEvaluator:
    """Routes participants to different engines with differing cost models."""

    def __init__(
        self,
        champ_adapter: M2TrialEvaluatorAdapter,
        chall_adapter: M2TrialEvaluatorAdapter,
        champ_id: UUID,
    ) -> None:
        self.champ_adapter = champ_adapter
        self.chall_adapter = chall_adapter
        self.champ_id = champ_id

    def evaluate_experiment(self, experiment: object) -> Mapping[str, object]:
        pid = getattr(experiment, "experiment_proposal_id", None)
        if pid == self.champ_id:
            return self.champ_adapter.evaluate_experiment(experiment)  # type: ignore[arg-type]
        return self.chall_adapter.evaluate_experiment(experiment)  # type: ignore[arg-type]


def test_tournament_runner_refuses_mismatched_cost_models() -> None:
    """TournamentRunner refuses match when participants use different cost models."""
    engine_base = _engine()
    engine_alt_cost = _engine(
        cost_model=_cost_model(
            model_id="task6-alt-fee-v1",
            commission="0.05",
            fixed_fee="1.00",
        )
    )

    champ_adapter = M2TrialEvaluatorAdapter(engine=engine_base)
    chall_adapter = M2TrialEvaluatorAdapter(engine=engine_alt_cost)

    champ, chall = _build_participants()
    routing_evaluator = _DualEngineRoutingEvaluator(
        champ_adapter=champ_adapter,
        chall_adapter=chall_adapter,
        champ_id=champ.participant_id,
    )

    config = _build_tournament_config()
    runner = TournamentRunner(
        config=config,
        evaluator=routing_evaluator,
        require_genuine_evidence=True,
    )

    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any("cost model mismatch or missing" in r for r in record.rejection_reasons)
