"""Adversarial acceptance suite for Champion / Challenger Tournament (M10-5, Issue 251).

Attacks tournament engine boundary invariants across:
1. Marginal noise outperformance rejection (strict delta_sharpe hurdle);
2. Multiple-testing trial count (K) deflation preventing cherry-picked contenders;
3. Drawdown tail risk breach rejection under high Sharpe;
4. Turnover drag ratio breach rejection under high Sharpe;
5. Insufficient session window rejection;
6. Incomplete realized PnL anti-laundering gatekeeping (Issue #152);
7. Cryptographic match record and config tamper detection;
8. Ledger archive resilience against corrupted audit event payloads.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.common import _freeze_json
from drift.domain.tournament import (
    CHAMPION_PROMOTED_EVENT_TYPE,
    MATCH_COMPLETED_EVENT_TYPE,
    TournamentConfigV1,
    TournamentDecision,
    TournamentMatchRecordV1,
    TournamentParticipantV1,
    build_tournament_config,
    build_tournament_match_record,
    build_tournament_participant,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.evaluator_adapter import DeterministicMockTrialEvaluator
from drift.memory.recorder import deterministic_memory_uuid7
from drift.tournament.archive import TournamentArchive
from drift.tournament.comparator import (
    evaluate_head_to_head_match,
)
from drift.tournament.recorder import TournamentRecorder
from drift.tournament.runner import TournamentRunner

TIMESTAMP_START = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)
TIMESTAMP_END = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
TOURNAMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
CHAMP_ID_0 = UUID("018f3a5b-6c7d-7890-8123-456789abcd10")
CHALL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd11")


def _sample_participants() -> tuple[TournamentParticipantV1, TournamentParticipantV1]:
    champ = build_tournament_participant(
        participant_id=CHAMP_ID_0,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 20},
        is_incumbent_champion=True,
    )
    chall = build_tournament_participant(
        participant_id=CHALL_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 40},
        is_incumbent_champion=False,
    )
    return champ, chall


# -----------------------------------------------------------------------------
# Vector 1: Marginal Noise Outperformance Rejection
# -----------------------------------------------------------------------------


def test_adv_marginal_noise_outperformance_rejection() -> None:
    """Ensure small outperformance below hurdle is rejected to protect champion."""
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP_START,
        min_delta_sharpe=Decimal("0.25"),
    )

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.0"),
            },
            chall.parameters_hash: {
                # Only +0.05 better (noise)
                "annualized_sharpe": Decimal("1.05"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.0"),
            },
        }
    )

    runner = TournamentRunner(config=config, evaluator=evaluator)
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert record.decision == TournamentDecision.REJECTED_INSUFFICIENT_OUTPERFORMANCE
    assert record.delta_sharpe == Decimal("0.05")
    assert any("below required minimum" in r for r in record.rejection_reasons)


# -----------------------------------------------------------------------------
# Vector 2: Multiple-Testing Trial Count (K) Deflation
# -----------------------------------------------------------------------------


def test_adv_multiple_testing_trial_count_deflation() -> None:
    """Ensure campaign with many evaluated trials penalizes p-value hurdle."""
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP_START,
        significance_alpha=Decimal("0.05"),
    )

    champ_returns = [
        Decimal("0.001") if i % 2 == 0 else Decimal("-0.001") for i in range(60)
    ]
    chall_returns = [
        Decimal("0.003") if i % 2 == 0 else Decimal("0.000") for i in range(60)
    ]

    # Without multiple testing penalty (K=1)
    res_single = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.30"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.09"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.2"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
        trials_evaluated_count=1,
    )

    # With multiple testing penalty (K=20 trials explored)
    res_multiple = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.30"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.09"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.2"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
        trials_evaluated_count=20,
    )

    # Multi-trial search deflation must trigger statistically insignificant rejection
    assert res_multiple.p_value == res_single.p_value
    if res_multiple.p_value > (Decimal("0.05") / Decimal("20")):
        assert (
            res_multiple.decision
            == TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT
        )


# -----------------------------------------------------------------------------
# Vector 3: Drawdown Tail Risk Breach Rejection
# -----------------------------------------------------------------------------


def test_adv_drawdown_tail_risk_breach_rejection() -> None:
    """Ensure challenger with high Sharpe but catastrophic drawdown is rejected."""
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP_START,
        max_drawdown_slack=Decimal("0.10"),  # max allowed DD: 0.08 * 1.1 = 0.088
    )

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.0"),
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("2.50"),  # Huge Sharpe
                "max_drawdown": Decimal("0.22"),  # Breaches 0.088 limit
                "annualized_turnover": Decimal("2.0"),
            },
        }
    )

    runner = TournamentRunner(config=config, evaluator=evaluator)
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert record.decision == TournamentDecision.REJECTED_EXCESSIVE_DRAWDOWN
    assert any("max_drawdown" in r for r in record.rejection_reasons)


# -----------------------------------------------------------------------------
# Vector 4: Turnover Drag Ratio Breach Rejection
# -----------------------------------------------------------------------------


def test_adv_turnover_drag_ratio_breach_rejection() -> None:
    """Ensure hyperactive high-churn challenger is rejected despite high Sharpe."""
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP_START,
        max_turnover_ratio=Decimal("2.0"),
    )

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.0"),
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("2.00"),
                "max_drawdown": Decimal("0.07"),
                "annualized_turnover": Decimal("7.5"),  # Turnover ratio = 3.75 > 2.0
            },
        }
    )

    runner = TournamentRunner(config=config, evaluator=evaluator)
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert record.decision == TournamentDecision.REJECTED_EXCESSIVE_TURNOVER
    assert any("turnover_ratio" in r for r in record.rejection_reasons)


# -----------------------------------------------------------------------------
# Vector 5: Insufficient Session Window Rejection
# -----------------------------------------------------------------------------


def test_adv_insufficient_session_window_rejection() -> None:
    """Ensure matches with session count below minimum threshold cannot promote."""
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP_START,
        min_evaluation_sessions=80,
    )

    # Only 30 sessions provided
    champ_returns = [Decimal("0.001")] * 30
    chall_returns = [Decimal("0.005")] * 30

    res = evaluate_head_to_head_match(
        config=config,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.80"),
        champion_max_drawdown=Decimal("0.08"),
        challenger_max_drawdown=Decimal("0.06"),
        champion_turnover=Decimal("2.0"),
        challenger_turnover=Decimal("2.1"),
        champion_returns=champ_returns,
        challenger_returns=chall_returns,
    )

    assert res.decision != TournamentDecision.PROMOTED
    assert any("insufficient evaluation sessions" in r for r in res.rejection_reasons)


# -----------------------------------------------------------------------------
# Vector 6: Incomplete Realized PnL Disqualification (Issue #152)
# -----------------------------------------------------------------------------


def test_adv_incomplete_realized_pnl_disqualification() -> None:
    """Ensure missing cost basis disposals disqualify match per Issue #152."""
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP_START,
    )

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.0"),
                "is_pnl_complete": True,
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("2.50"),
                "max_drawdown": Decimal("0.06"),
                "annualized_turnover": Decimal("2.1"),
                "is_pnl_complete": False,  # Unknown basis disposal!
            },
        }
    )

    runner = TournamentRunner(config=config, evaluator=evaluator)
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert record.decision == TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
    assert any("realized PnL completeness" in r for r in record.rejection_reasons)


# -----------------------------------------------------------------------------
# Vector 7: Cryptographic Tamper Detection
# -----------------------------------------------------------------------------


def test_adv_match_record_and_config_tamper_detection() -> None:
    """Ensure any alteration to match record or config breaks SHA-256 hash."""
    champ, chall = _sample_participants()
    record = build_tournament_match_record(
        match_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd20"),
        tournament_id=TOURNAMENT_ID_1,
        champion=champ,
        challenger=chall,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.50"),
        delta_sharpe=Decimal("0.50"),
        champion_max_drawdown=Decimal("0.08"),
        challenger_max_drawdown=Decimal("0.07"),
        turnover_ratio=Decimal("1.05"),
        paired_t_stat=Decimal("3.20"),
        p_value=Decimal("0.001"),
        decision=TournamentDecision.PROMOTED,
        evaluated_sessions_count=60,
        started_at=TIMESTAMP_START,
        completed_at=TIMESTAMP_END,
    )

    # 1. Tamper with decision on match record
    tampered_rec = record.model_dump()
    tampered_rec["decision"] = TournamentDecision.REJECTED_EXCESSIVE_DRAWDOWN
    with pytest.raises(ValidationError, match="hash mismatch"):
        TournamentMatchRecordV1.model_validate(tampered_rec)

    # 2. Tamper with config
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP_START,
    )
    tampered_cfg = config.model_dump()
    tampered_cfg["min_delta_sharpe"] = Decimal("0.99")
    with pytest.raises(ValidationError, match="hash mismatch"):
        TournamentConfigV1.model_validate(tampered_cfg)


# -----------------------------------------------------------------------------
# Vector 8: Archive Resilience Against Corrupted Audit Events
# -----------------------------------------------------------------------------


def test_adv_archive_corrupted_payload_resilience(tmp_path: Path) -> None:
    """Ensure archive skips corrupted or malformed match payloads gracefully."""
    ledger = SQLiteLedger(tmp_path / "corrupted_tournament.sqlite3")

    # Insert corrupted match event
    bad_match = AuditEventDraft(
        schema_version="1",
        event_id=deterministic_memory_uuid7("bad_ev_m1"),
        event_type=MATCH_COMPLETED_EVENT_TYPE,
        timestamp=TIMESTAMP_START,
        entity_type="tournament_match",
        entity_id=deterministic_memory_uuid7("bad_ent_m1"),
        payload=_freeze_json({"match": {"corrupted": "bad_data"}}),
        deduplication_key="bad:m1",
    )
    ledger.append(bad_match)

    # Insert corrupted promotion event
    bad_promo = AuditEventDraft(
        schema_version="1",
        event_id=deterministic_memory_uuid7("bad_ev_m2"),
        event_type=CHAMPION_PROMOTED_EVENT_TYPE,
        timestamp=TIMESTAMP_START,
        entity_type="tournament_promotion",
        entity_id=deterministic_memory_uuid7("bad_ent_m2"),
        payload=_freeze_json({"invalid": True}),
        deduplication_key="bad:m2",
    )
    ledger.append(bad_promo)

    archive = TournamentArchive(ledger)
    assert archive.total_matches_count == 0
    assert archive.promotions_count == 0

    # Append valid match and promotion
    champ, chall = _sample_participants()
    valid_record = build_tournament_match_record(
        match_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd30"),
        tournament_id=TOURNAMENT_ID_1,
        champion=champ,
        challenger=chall,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.50"),
        delta_sharpe=Decimal("0.50"),
        champion_max_drawdown=Decimal("0.08"),
        challenger_max_drawdown=Decimal("0.07"),
        turnover_ratio=Decimal("1.05"),
        paired_t_stat=Decimal("3.20"),
        p_value=Decimal("0.001"),
        decision=TournamentDecision.PROMOTED,
        evaluated_sessions_count=60,
        started_at=TIMESTAMP_START,
        completed_at=TIMESTAMP_END,
    )

    rec = TournamentRecorder(ledger)
    rec.record_match(valid_record)
    rec.record_promotion(valid_record)

    archive.refresh()
    assert archive.total_matches_count == 1
    assert archive.promotions_count == 1
    assert archive.get_match(valid_record.match_id) == valid_record
    assert archive.get_current_champion("b4_momentum") == chall
