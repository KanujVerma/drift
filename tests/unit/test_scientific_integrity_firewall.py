"""Tests for Phase 1 Scientific Integrity Firewall.

Validates that scientific evaluation and tournament decisions fail closed when:
1. Mock-derived results are passed where genuine evidence is required.
2. Session returns are missing, partial, or misaligned.
3. Realized PnL completeness is missing or False.
4. Mandatory metrics (Sharpe, Drawdown, Turnover) are missing.
5. Constant return series with zero variance attempt to claim p=0 significance.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from drift.domain.tournament import (
    TournamentConfigV1,
    TournamentDecision,
    TournamentParticipantV1,
    build_tournament_config,
    build_tournament_participant,
)
from drift.loop.evaluator_adapter import (
    DeterministicMockTrialEvaluator,
)
from drift.tournament.comparator import (
    compute_paired_returns_statistics,
    evaluate_head_to_head_match,
)
from drift.tournament.runner import TournamentRunner

TIMESTAMP_START = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)
TIMESTAMP_END = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
TOURNAMENT_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd10")
CHAMPION_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd11")
CHALLENGER_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd12")


def _sample_participants() -> tuple[TournamentParticipantV1, TournamentParticipantV1]:
    champ = build_tournament_participant(
        participant_id=CHAMPION_ID,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 30},
        is_incumbent_champion=True,
    )
    chall = build_tournament_participant(
        participant_id=CHALLENGER_ID,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 60},
        is_incumbent_champion=False,
    )
    return champ, chall


def _sample_config(min_evaluation_sessions: int = 60) -> TournamentConfigV1:
    return build_tournament_config(
        tournament_id=TOURNAMENT_ID,
        created_at=TIMESTAMP_START,
        min_delta_sharpe=Decimal("0.20"),
        min_evaluation_sessions=min_evaluation_sessions,
    )


def test_zero_variance_constant_returns_rejected_significance() -> None:
    """Deterministic synthetic constant returns must not claim p=0 significance."""
    champ = [Decimal("0.001")] * 60
    chall = [Decimal("0.006")] * 60
    mean_diff, t_stat, p_val = compute_paired_returns_statistics(champ, chall)

    assert mean_diff == Decimal("0.005")
    # Must NOT be t=999.0, p=0.0
    assert p_val == Decimal("1.0")
    assert t_stat == Decimal("0.0")

    # In a tournament match, zero-variance series must be rejected
    config = _sample_config(min_evaluation_sessions=60)
    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.60"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.08"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.2"),
        champion_returns=champ,
        challenger_returns=chall,
        is_pnl_complete=True,
    )
    assert res.decision == TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT


def test_missing_session_returns_comparison_refused() -> None:
    """Missing session returns sequence must result in refusal."""
    champ, chall = _sample_participants()
    config = _sample_config()

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.10"),
                "annualized_turnover": Decimal("2.0"),
                "is_pnl_complete": True,
                # No session_returns
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("1.50"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.2"),
                "is_pnl_complete": True,
                # No session_returns
            },
        }
    )

    runner = TournamentRunner(
        config=config, evaluator=evaluator, require_genuine_evidence=False
    )
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )
    assert record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any("session returns" in r for r in record.rejection_reasons)


def test_partial_session_returns_comparison_refused() -> None:
    """Session returns sequence shorter than required must result in refusal."""
    champ, chall = _sample_participants()
    config = _sample_config(min_evaluation_sessions=60)

    short_returns = tuple(Decimal("0.001") for _ in range(30))
    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.10"),
                "annualized_turnover": Decimal("2.0"),
                "is_pnl_complete": True,
                "session_returns": short_returns,
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("1.50"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.2"),
                "is_pnl_complete": True,
                "session_returns": short_returns,
            },
        }
    )

    runner = TournamentRunner(
        config=config, evaluator=evaluator, require_genuine_evidence=False
    )
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )
    assert (
        record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
        or record.decision == TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT
    )


def test_mismatched_session_returns_alignment_refused() -> None:
    """Mismatched session counts or alignments must result in refusal."""
    champ, chall = _sample_participants()
    config = _sample_config(min_evaluation_sessions=60)

    c_returns = tuple(Decimal("0.001") for _ in range(60))
    h_returns = tuple(Decimal("0.002") for _ in range(65))

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.10"),
                "annualized_turnover": Decimal("2.0"),
                "is_pnl_complete": True,
                "session_returns": c_returns,
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("1.50"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.2"),
                "is_pnl_complete": True,
                "session_returns": h_returns,
            },
        }
    )

    runner = TournamentRunner(
        config=config, evaluator=evaluator, require_genuine_evidence=False
    )
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )
    assert record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any(
        "mismatch" in r.lower() or "alignment" in r.lower() or "incomplete" in r.lower()
        for r in record.rejection_reasons
    )


def test_missing_pnl_completeness_refused() -> None:
    """Missing is_pnl_complete must not default to True; match must be refused."""
    champ, chall = _sample_participants()
    config = _sample_config()

    var_returns = tuple(
        Decimal("0.001") + Decimal(str(i % 7)) / Decimal("1000") for i in range(60)
    )
    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.10"),
                "annualized_turnover": Decimal("2.0"),
                "session_returns": var_returns,
                # is_pnl_complete is missing!
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("1.50"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.2"),
                "session_returns": var_returns,
                "is_pnl_complete": True,
            },
        }
    )

    runner = TournamentRunner(
        config=config, evaluator=evaluator, require_genuine_evidence=False
    )
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )
    assert record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any(
        "pnl complete" in r.lower() or "basis" in r.lower()
        for r in record.rejection_reasons
    )


def test_missing_required_metrics_refused() -> None:
    """Missing required metrics must not default to 0.0; match must be refused."""
    champ, chall = _sample_participants()
    config = _sample_config()

    var_returns = tuple(
        Decimal("0.001") + Decimal(str(i % 7)) / Decimal("1000") for i in range(60)
    )
    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                # max_drawdown missing!
                "annualized_turnover": Decimal("2.0"),
                "session_returns": var_returns,
                "is_pnl_complete": True,
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("1.50"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.2"),
                "session_returns": var_returns,
                "is_pnl_complete": True,
            },
        }
    )

    runner = TournamentRunner(
        config=config, evaluator=evaluator, require_genuine_evidence=False
    )
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )
    assert record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any(
        "missing required" in r.lower() or "incomplete" in r.lower()
        for r in record.rejection_reasons
    )


def test_mock_derived_results_rejected_when_genuine_evidence_required() -> None:
    """Mock-derived results must be refused when genuine evidence is required."""
    champ, chall = _sample_participants()
    config = _sample_config()

    evaluator = DeterministicMockTrialEvaluator()
    runner = TournamentRunner(
        config=config, evaluator=evaluator, require_genuine_evidence=True
    )

    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )
    assert record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any("mock" in r.lower() for r in record.rejection_reasons)


def test_legitimate_paired_return_comparisons_succeed() -> None:
    """Legitimate paired returns with empirical variance and complete evidence work."""
    config = _sample_config()
    champ_returns = [
        Decimal("0.001") + Decimal(str(i % 5)) / Decimal("1000") for i in range(80)
    ]
    chall_returns = [
        Decimal("0.004") + Decimal(str((i + 1) % 5)) / Decimal("1000")
        for i in range(80)
    ]

    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.40"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.09"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.4"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
        trials_evaluated_count=1,
        is_pnl_complete=True,
    )

    assert res.decision == TournamentDecision.PROMOTED
    assert res.delta_sharpe == Decimal("0.40")
    assert len(res.rejection_reasons) == 0
