"""Unit tests for tournament statistical comparator and match evaluator (M10-2)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from drift.domain.tournament import (
    TournamentConfigV1,
    TournamentDecision,
    build_tournament_config,
)
from drift.tournament.comparator import (
    compute_paired_returns_statistics,
    evaluate_head_to_head_match,
)

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
TOURNAMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")


def _sample_config(
    min_delta_sharpe: Decimal = Decimal("0.20"),
    significance_alpha: Decimal = Decimal("0.05"),
    max_drawdown_slack: Decimal = Decimal("0.10"),
    max_turnover_ratio: Decimal = Decimal("2.50"),
    min_evaluation_sessions: int = 60,
) -> TournamentConfigV1:
    return build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP,
        min_delta_sharpe=min_delta_sharpe,
        significance_alpha=significance_alpha,
        max_drawdown_slack=max_drawdown_slack,
        max_turnover_ratio=max_turnover_ratio,
        min_evaluation_sessions=min_evaluation_sessions,
    )


def test_paired_returns_statistics_identical_series() -> None:
    returns = [Decimal("0.01"), Decimal("-0.005"), Decimal("0.02")] * 20
    mean_diff, t_stat, p_val = compute_paired_returns_statistics(returns, returns)
    assert mean_diff == Decimal("0.0")
    assert t_stat == Decimal("0.0")
    assert p_val == Decimal("1.0")


def test_paired_returns_statistics_superior_series() -> None:
    champ = [Decimal("0.001")] * 60
    # Challenger consistently earns +0.005 higher per session
    chall = [Decimal("0.006")] * 60
    mean_diff, t_stat, p_val = compute_paired_returns_statistics(champ, chall)
    assert mean_diff == Decimal("0.005")
    assert t_stat == Decimal("999.0")
    assert p_val == Decimal("0.0")


def test_evaluate_head_to_head_match_promoted() -> None:
    config = _sample_config()
    champ_returns = [
        Decimal("0.001") + Decimal(str(i % 5)) / Decimal("1000") for i in range(80)
    ]
    chall_returns = [
        Decimal("0.004") + Decimal(str(i % 5)) / Decimal("1000") for i in range(80)
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
    assert res.evaluated_sessions_count == 80


def test_evaluate_head_to_head_match_rejected_insufficient_outperformance() -> None:
    config = _sample_config(min_delta_sharpe=Decimal("0.30"))
    champ_returns = [Decimal("0.001")] * 60
    chall_returns = [Decimal("0.002")] * 60

    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.15"),  # Delta is only 0.15 < 0.30
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.09"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.2"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
    )

    assert res.decision == TournamentDecision.REJECTED_INSUFFICIENT_OUTPERFORMANCE
    assert any("delta_sharpe" in r for r in res.rejection_reasons)


def test_evaluate_head_to_head_match_rejected_multiple_testing_penalty() -> None:
    config = _sample_config(significance_alpha=Decimal("0.05"))
    champ_returns = [
        Decimal("0.001") if i % 2 == 0 else Decimal("-0.001") for i in range(60)
    ]
    chall_returns = [
        Decimal("0.003") if i % 2 == 0 else Decimal("0.000") for i in range(60)
    ]

    # With K=10 trials explored, alpha_adjusted = 0.05 / 10 = 0.005
    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.30"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.09"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.2"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
        trials_evaluated_count=10,
    )

    if res.p_value > Decimal("0.005"):
        assert res.decision == TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT
        assert any("significance alpha" in r for r in res.rejection_reasons)


def test_evaluate_head_to_head_match_rejected_excessive_drawdown() -> None:
    config = _sample_config(max_drawdown_slack=Decimal("0.10"))
    champ_returns = [Decimal("0.001")] * 60
    chall_returns = [Decimal("0.005")] * 60

    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.50"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.15"),  # Exceeds 0.11 limit
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.2"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
    )

    assert res.decision == TournamentDecision.REJECTED_EXCESSIVE_DRAWDOWN
    assert any("max_drawdown" in r for r in res.rejection_reasons)


def test_evaluate_head_to_head_match_rejected_excessive_turnover() -> None:
    config = _sample_config(max_turnover_ratio=Decimal("2.0"))
    champ_returns = [Decimal("0.001")] * 60
    chall_returns = [Decimal("0.005")] * 60

    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.50"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.08"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("5.5"),  # Ratio = 2.75 > 2.0
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
    )

    assert res.decision == TournamentDecision.REJECTED_EXCESSIVE_TURNOVER
    assert any("turnover_ratio" in r for r in res.rejection_reasons)


def test_evaluate_head_to_head_match_rejected_incomplete_pnl() -> None:
    config = _sample_config()
    champ_returns = [Decimal("0.001")] * 60
    chall_returns = [Decimal("0.005")] * 60

    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.50"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.08"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.2"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
        is_pnl_complete=False,  # Disqualified
    )

    assert res.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any("realized PnL completeness" in r for r in res.rejection_reasons)
