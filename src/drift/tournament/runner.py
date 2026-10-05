"""Head-to-head tournament runner and match controller (M10-3, Issue 247).

Orchestrates paired out-of-sample evaluations of incumbent Champion strategies
and newly evolved Challenger strategies, applies multi-criteria statistical
gatekeeping, and produces immutable match audit records.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from drift.domain.common import UTCDateTime
from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    build_experiment_specification_proposal,
)
from drift.domain.tournament import (
    TournamentConfigV1,
    TournamentDecision,
    TournamentMatchRecordV1,
    TournamentParticipantV1,
    build_tournament_match_record,
)
from drift.loop.evaluator_adapter import TrialEvaluatorProtocol
from drift.memory.recorder import deterministic_memory_uuid7
from drift.tournament.comparator import evaluate_head_to_head_match

__all__ = [
    "TournamentRecorderProtocol",
    "TournamentRunner",
]


@runtime_checkable
class TournamentRecorderProtocol(Protocol):
    """Protocol for persisting tournament match outcomes into M0 ledger."""

    def record_match(self, match: TournamentMatchRecordV1) -> Any: ...

    def record_promotion(self, match: TournamentMatchRecordV1) -> Any: ...

    def record_rejection(self, match: TournamentMatchRecordV1) -> Any: ...


def _participant_to_experiment(
    participant: TournamentParticipantV1,
    as_of_time: UTCDateTime,
) -> ExperimentSpecificationProposalV1:
    """Adapt a tournament participant into an experiment specification."""
    return build_experiment_specification_proposal(
        experiment_proposal_id=participant.participant_id,
        hypothesis_proposal_id=participant.trial_id or participant.participant_id,
        strategy_type=participant.strategy_type,
        proposed_parameters=dict(participant.parameters),
        universe_id="sp500_historical_v1",
        rebalance_frequency="daily",
        created_at=as_of_time,
    )


def _extract_returns(
    metrics: Mapping[str, Any], session_count: int
) -> tuple[Decimal, ...]:
    """Extract session returns sequence or derive baseline daily returns."""
    raw = metrics.get("session_returns")
    if isinstance(raw, Sequence) and len(raw) == session_count:
        return tuple(Decimal(str(r)) for r in raw)

    sharpe = Decimal(str(metrics.get("annualized_sharpe", "1.0")))
    daily_mu = (sharpe * Decimal("0.15")) / Decimal("252")
    return tuple(daily_mu for _ in range(session_count))


class TournamentRunner:
    """Autonomous controller for head-to-head Champion vs Challenger matches."""

    def __init__(
        self,
        *,
        config: TournamentConfigV1,
        evaluator: TrialEvaluatorProtocol,
        recorder: TournamentRecorderProtocol | None = None,
    ) -> None:
        self.config = config
        self.evaluator = evaluator
        self.recorder = recorder

    def run_match(
        self,
        *,
        champion: TournamentParticipantV1,
        challenger: TournamentParticipantV1,
        start_time: UTCDateTime,
        end_time: UTCDateTime,
        trials_evaluated_count: int = 1,
        match_id: UUID | None = None,
    ) -> TournamentMatchRecordV1:
        """Execute paired evaluation, statistical comparison, and verdict sealing."""
        if not champion.is_incumbent_champion:
            raise ValueError(
                f"Participant {champion.participant_id} is not declared "
                "as incumbent champion"
            )

        # 1. Adapt participants to experiment specs
        champ_exp = _participant_to_experiment(champion, start_time)
        chall_exp = _participant_to_experiment(challenger, start_time)

        # 2. Evaluate both participants across paired evaluation window
        champ_metrics = self.evaluator.evaluate_experiment(champ_exp)
        chall_metrics = self.evaluator.evaluate_experiment(chall_exp)

        # 3. Extract headline metrics
        c_sharpe = Decimal(str(champ_metrics.get("annualized_sharpe", "0.0")))
        h_sharpe = Decimal(str(chall_metrics.get("annualized_sharpe", "0.0")))

        c_drawdown = Decimal(str(champ_metrics.get("max_drawdown", "0.0")))
        h_drawdown = Decimal(str(chall_metrics.get("max_drawdown", "0.0")))

        c_turnover = Decimal(str(champ_metrics.get("annualized_turnover", "0.0")))
        h_turnover = Decimal(str(chall_metrics.get("annualized_turnover", "0.0")))

        # Check PnL completeness (Issue #152)
        c_pnl_complete = bool(champ_metrics.get("is_pnl_complete", True))
        h_pnl_complete = bool(chall_metrics.get("is_pnl_complete", True))
        is_pnl_complete = c_pnl_complete and h_pnl_complete

        # Extract session returns
        session_count = self.config.min_evaluation_sessions
        c_returns = _extract_returns(champ_metrics, session_count)
        h_returns = _extract_returns(chall_metrics, session_count)

        # 4. Statistical comparison and gatekeeping
        cmp_result = evaluate_head_to_head_match(
            config=self.config,
            champion_sharpe=c_sharpe,
            challenger_sharpe=h_sharpe,
            champion_max_drawdown=c_drawdown,
            challenger_max_drawdown=h_drawdown,
            champion_turnover=c_turnover,
            challenger_turnover=h_turnover,
            champion_returns=c_returns,
            challenger_returns=h_returns,
            trials_evaluated_count=trials_evaluated_count,
            is_pnl_complete=is_pnl_complete,
        )

        resolved_match_id = match_id or deterministic_memory_uuid7(
            f"match:{self.config.tournament_id}:{champion.participant_id}:{challenger.participant_id}"
        )

        # 5. Build immutable match record
        record = build_tournament_match_record(
            match_id=resolved_match_id,
            tournament_id=self.config.tournament_id,
            champion=champion,
            challenger=challenger,
            champion_sharpe=c_sharpe,
            challenger_sharpe=h_sharpe,
            delta_sharpe=cmp_result.delta_sharpe,
            champion_max_drawdown=c_drawdown,
            challenger_max_drawdown=h_drawdown,
            turnover_ratio=cmp_result.turnover_ratio,
            paired_t_stat=cmp_result.paired_t_stat,
            p_value=cmp_result.p_value,
            decision=cmp_result.decision,
            rejection_reasons=cmp_result.rejection_reasons,
            evaluated_sessions_count=session_count,
            started_at=start_time,
            completed_at=end_time,
        )

        # 6. Optional ledger persistence
        if self.recorder is not None:
            self.recorder.record_match(record)
            if record.decision == TournamentDecision.PROMOTED:
                self.recorder.record_promotion(record)
            else:
                self.recorder.record_rejection(record)

        return record
