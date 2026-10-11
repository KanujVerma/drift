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
    metrics: Mapping[str, Any],
) -> tuple[Decimal, ...] | None:
    """Extract genuine session returns sequence. Never synthesizes fallback returns."""
    raw = metrics.get("session_returns")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return tuple(Decimal(str(r)) for r in raw)
    return None


class TournamentRunner:
    """Autonomous controller for head-to-head Champion vs Challenger matches."""

    def __init__(
        self,
        *,
        config: TournamentConfigV1,
        evaluator: TrialEvaluatorProtocol,
        recorder: TournamentRecorderProtocol | None = None,
        require_genuine_evidence: bool = False,
    ) -> None:
        self.config = config
        self.evaluator = evaluator
        self.recorder = recorder
        self.require_genuine_evidence = require_genuine_evidence

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

        resolved_match_id = match_id or deterministic_memory_uuid7(
            f"match:{self.config.tournament_id}:{champion.participant_id}:{challenger.participant_id}"
        )

        # 1. Adapt participants to experiment specs
        champ_exp = _participant_to_experiment(champion, start_time)
        chall_exp = _participant_to_experiment(challenger, start_time)

        # 2. Evaluate both participants across paired evaluation window
        champ_metrics = self.evaluator.evaluate_experiment(champ_exp)
        chall_metrics = self.evaluator.evaluate_experiment(chall_exp)

        # Check mock evidence restriction
        is_champ_mock = bool(champ_metrics.get("is_mock", False))
        is_chall_mock = bool(chall_metrics.get("is_mock", False))
        if self.require_genuine_evidence and (is_champ_mock or is_chall_mock):
            record = build_tournament_match_record(
                match_id=resolved_match_id,
                tournament_id=self.config.tournament_id,
                champion=champion,
                challenger=challenger,
                champion_sharpe=Decimal(
                    str(champ_metrics.get("annualized_sharpe", "0.0"))
                ),
                challenger_sharpe=Decimal(
                    str(chall_metrics.get("annualized_sharpe", "0.0"))
                ),
                delta_sharpe=Decimal("0.0"),
                champion_max_drawdown=Decimal(
                    str(champ_metrics.get("max_drawdown", "0.0"))
                ),
                challenger_max_drawdown=Decimal(
                    str(chall_metrics.get("max_drawdown", "0.0"))
                ),
                turnover_ratio=Decimal("1.0"),
                paired_t_stat=Decimal("0.0"),
                p_value=Decimal("1.0"),
                decision=TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE,
                rejection_reasons=(
                    "mock-derived evaluation results cannot satisfy "
                    "genuine evidence requirements",
                ),
                evaluated_sessions_count=0,
                started_at=start_time,
                completed_at=end_time,
            )
            if self.recorder is not None:
                self.recorder.record_match(record)
                self.recorder.record_rejection(record)
            return record

        # 3. Extract headline metrics without optimistic defaults
        raw_c_sharpe = champ_metrics.get("annualized_sharpe")
        raw_h_sharpe = chall_metrics.get("annualized_sharpe")
        c_sharpe = Decimal(str(raw_c_sharpe)) if raw_c_sharpe is not None else None
        h_sharpe = Decimal(str(raw_h_sharpe)) if raw_h_sharpe is not None else None

        raw_c_drawdown = champ_metrics.get("max_drawdown")
        raw_h_drawdown = chall_metrics.get("max_drawdown")
        c_drawdown = (
            Decimal(str(raw_c_drawdown)) if raw_c_drawdown is not None else None
        )
        h_drawdown = (
            Decimal(str(raw_h_drawdown)) if raw_h_drawdown is not None else None
        )

        raw_c_turnover = champ_metrics.get("annualized_turnover")
        raw_h_turnover = chall_metrics.get("annualized_turnover")
        c_turnover = (
            Decimal(str(raw_c_turnover)) if raw_c_turnover is not None else None
        )
        h_turnover = (
            Decimal(str(raw_h_turnover)) if raw_h_turnover is not None else None
        )

        # Check PnL completeness (Issue #152) - MUST NOT default to True!
        c_pnl_complete = champ_metrics.get("is_pnl_complete") is True
        h_pnl_complete = chall_metrics.get("is_pnl_complete") is True
        is_pnl_complete = c_pnl_complete and h_pnl_complete

        # Extract session returns (strictly empirical, no synthetic fallback)
        c_returns = _extract_returns(champ_metrics)
        h_returns = _extract_returns(chall_metrics)

        # Check session alignment if metadata present
        c_sessions = champ_metrics.get("session_keys") or champ_metrics.get(
            "session_dates"
        )
        h_sessions = chall_metrics.get("session_keys") or chall_metrics.get(
            "session_dates"
        )
        if (
            isinstance(c_sessions, Sequence)
            and isinstance(h_sessions, Sequence)
            and tuple(c_sessions) != tuple(h_sessions)
        ):
            # Incompatible session alignments: refuse comparison
            c_returns = ()
            h_returns = ()

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

        session_count = cmp_result.evaluated_sessions_count

        # 5. Build immutable match record
        record = build_tournament_match_record(
            match_id=resolved_match_id,
            tournament_id=self.config.tournament_id,
            champion=champion,
            challenger=challenger,
            champion_sharpe=c_sharpe or Decimal("0.0"),
            challenger_sharpe=h_sharpe or Decimal("0.0"),
            delta_sharpe=cmp_result.delta_sharpe,
            champion_max_drawdown=c_drawdown or Decimal("0.0"),
            challenger_max_drawdown=h_drawdown or Decimal("0.0"),
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
