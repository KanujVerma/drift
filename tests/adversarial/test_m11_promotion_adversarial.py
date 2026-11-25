"""Adversarial acceptance test suite for Promotion & Overfitting Controls (M11-5).

Executes 8 adversarial attack vectors testing:
1. DSR deflation under multiple testing trial mining
2. CSCV combinatorial overfitting detection (PBO breach)
3. Walk-forward temporal degradation rejection
4. Extreme regime shock drawdown breach
5. Exploratory lane anti-laundering boundary firewall
6. Realized PnL basis incompleteness fail-closed firewall (Issue 152)
7. Cryptographic hash tamper detection across configs and records
8. Deterministic SQLite ledger replay and state reconstruction
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.promotion import (
    PromotionEvaluationRecordV1,
    PromotionGateConfigV1,
    PromotionGateVerdict,
    build_promotion_evaluation_record,
    build_promotion_gate_config,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.promotion.archive import PromotionArchive
from drift.promotion.gatekeeper import PromotionGatekeeper
from drift.promotion.recorder import PromotionRecorder
from drift.promotion.runner import (
    CandidatePromotionRequestV1,
    PromotionRunner,
)

TIMESTAMP = datetime(2026, 2, 1, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def recorder(tmp_path: Path) -> PromotionRecorder:
    return PromotionRecorder(SQLiteLedger(tmp_path / "adversarial.sqlite3"))


def test_adversarial_vector_1_dsr_deflation_under_trial_mining(
    recorder: PromotionRecorder,
) -> None:
    """Vector 1: High trial count K=100 deflates modest Sharpe ratio below gate."""
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=TIMESTAMP,
        min_dsr=Decimal("0.95"),
    )
    gk = PromotionGatekeeper(config)

    # Candidate with observed Sharpe 1.25 mined across 100 trials with variance 0.30
    trials = [Decimal("1.25"), Decimal("-0.20")] * 50
    rec = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="mined_momentum_v1",
        parameters_hash="1" * 64,
        trials_explored_k=100,
        observed_sharpe=Decimal("1.25"),
        trial_sharpes=trials,
        trial_block_matrix=[[1.0, 1.0]] + [[0.0, 0.0]] * 99,
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        recorder=recorder,
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
    )

    assert rec.verdict == PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
    assert rec.deflated_sharpe_ratio < Decimal("0.95")
    assert "deflated_sharpe_ratio_below_threshold" in rec.rejection_reasons


def test_adversarial_vector_2_combinatorial_overfitting_detection(
    recorder: PromotionRecorder,
) -> None:
    """Vector 2: In-sample lucky blocks collapsing out-of-sample fail PBO."""
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=TIMESTAMP,
        max_pbo=Decimal("0.30"),
    )
    gk = PromotionGatekeeper(config)

    # 4 trials across 6 blocks; trial 0 collapsed out-of-sample
    overfit_matrix = [
        [15.0, 15.0, 15.0, -12.0, -12.0, -12.0],
        [2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        [-1.0, -1.0, -1.0, -1.0, -1.0, -1.0],
    ]

    rec = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="lucky_cluster_v1",
        parameters_hash="2" * 64,
        trials_explored_k=4,
        observed_sharpe=Decimal("2.20"),
        trial_sharpes=[Decimal("2.20")] * 4,
        trial_block_matrix=overfit_matrix,
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        recorder=recorder,
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
    )

    assert rec.verdict == PromotionGateVerdict.REJECTED_PBO_OVERFITTING
    assert rec.pbo_estimate > Decimal("0.30")
    assert "pbo_exceeds_threshold" in rec.rejection_reasons


def test_adversarial_vector_3_walk_forward_temporal_degradation(
    recorder: PromotionRecorder,
) -> None:
    """Vector 3: Candidate failing positive returns in >=80% folds is rejected."""
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=TIMESTAMP,
        min_positive_folds_fraction=Decimal("0.80"),
    )
    gk = PromotionGatekeeper(config)

    # 5 contiguous walk-forward folds, but only 2 of 5 are positive (40% < 80%)
    folds = [
        [0.02, 0.03, 0.01],
        [-0.02, -0.01, -0.03],  # negative
        [-0.01, -0.02, -0.01],  # negative
        [0.01, 0.02, 0.01],
        [-0.03, -0.01, -0.02],  # negative
    ]

    rec = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="temporally_fragile_v1",
        parameters_hash="3" * 64,
        trials_explored_k=2,
        observed_sharpe=Decimal("2.20"),
        trial_sharpes=[Decimal("2.20")] * 2,
        walk_forward_fold_returns=folds,
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        session_returns=[0.01],
        recorder=recorder,
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
    )

    assert rec.verdict == PromotionGateVerdict.REJECTED_WALK_FORWARD_DEGRADATION
    assert rec.positive_folds_fraction == Decimal("0.4000")
    assert "walk_forward_degradation" in rec.rejection_reasons


def test_adversarial_vector_4_regime_shock_drawdown_breach(
    recorder: PromotionRecorder,
) -> None:
    """Vector 4: Severe drawdown in high-volatility regime fails gate."""
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=TIMESTAMP,
        max_regime_drawdown=Decimal("0.25"),
    )
    gk = PromotionGatekeeper(config)

    # Returns containing a 35% crash during high volatility
    returns = [
        0.01,
        -0.01,
        0.02,
        -0.02,
        0.01,
        -0.01,
        0.06,
        -0.35,  # 35% drawdown in high volatility
        0.02,
    ]

    rec = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="regime_fragile_v1",
        parameters_hash="4" * 64,
        trials_explored_k=2,
        observed_sharpe=Decimal("2.20"),
        trial_sharpes=[Decimal("2.20")] * 2,
        session_returns=returns,
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        recorder=recorder,
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
    )

    assert rec.verdict == PromotionGateVerdict.REJECTED_REGIME_INSTABILITY
    assert rec.max_regime_drawdown > Decimal("0.25")
    assert "regime_drawdown_exceeded" in rec.rejection_reasons


def test_adversarial_vector_5_anti_laundering_boundary_firewall(
    recorder: PromotionRecorder,
) -> None:
    """Vector 5: Exploratory evidence cannot be laundered into promotion."""
    now = datetime.now(UTC)

    # Case A: Evaluated without promotion config authorization
    cfg_unauth = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        is_promotion_grade_authorized=False,
    )
    gk_unauth = PromotionGatekeeper(cfg_unauth)

    # Superb statistical metrics on exploratory data
    rec_exp = gk_unauth.evaluate_candidate(
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        trial_sharpes=[Decimal("3.00")] * 2,
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        recorder=recorder,
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="5" * 64,
        trials_explored_k=2,
        observed_sharpe=Decimal("3.00"),
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=False,
    )
    assert rec_exp.verdict == PromotionGateVerdict.EXPLORATORY_PASSED

    # Case B: Attacker claims promotion-grade evidence without config authorization
    rec_spoofed = gk_unauth.evaluate_candidate(
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        trial_sharpes=[Decimal("3.00")] * 2,
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        recorder=recorder,
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="5" * 64,
        trials_explored_k=2,
        observed_sharpe=Decimal("3.00"),
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=True,
    )
    assert rec_spoofed.verdict == PromotionGateVerdict.EXPLORATORY_PASSED

    # Case C: Both flags are untrusted, even with complete synthetic inputs.
    cfg_auth = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        is_promotion_grade_authorized=True,
    )
    gk_auth = PromotionGatekeeper(cfg_auth)
    rec_promo = gk_auth.evaluate_candidate(
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        trial_sharpes=[Decimal("3.00")] * 2,
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        recorder=recorder,
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="5" * 64,
        trials_explored_k=2,
        observed_sharpe=Decimal("3.00"),
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=True,
    )
    assert rec_promo.verdict == PromotionGateVerdict.EXPLORATORY_PASSED


def test_adversarial_vector_6_incomplete_realized_pnl_basis_rejection(
    recorder: PromotionRecorder,
) -> None:
    """Vector 6: Incomplete cost basis strictly fails gate (Issue 152 firewall)."""
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=TIMESTAMP,
        is_promotion_grade_authorized=True,
    )
    gk = PromotionGatekeeper(config)

    # Candidate with stellar Sharpe 4.0 but missing cost basis
    rec = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="unknown_basis_strategy_v1",
        recorder=recorder,
        parameters_hash="6" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("4.00"),
        is_pnl_complete=False,
        is_promotion_grade_evidence=True,
    )

    assert rec.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert "pnl_completeness_not_confirmed" in rec.rejection_reasons


def test_adversarial_vector_7_cryptographic_tamper_detection() -> None:
    """Vector 7: Modifying any field without updating hash raises ValidationError."""
    cfg = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=TIMESTAMP,
        min_dsr=Decimal("0.95"),
    )

    # Tampering with min_dsr while preserving original hash
    tampered_cfg_dict = cfg.model_dump(mode="python")
    tampered_cfg_dict["min_dsr"] = Decimal("0.50")
    with pytest.raises(ValidationError, match="promotion gate config hash mismatch"):
        PromotionGateConfigV1.model_validate(tampered_cfg_dict)

    rec = build_promotion_evaluation_record(
        evaluation_id=uuid7(),
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="7" * 64,
        deflated_sharpe_ratio=Decimal("0.98"),
        pbo_estimate=Decimal("0.10"),
        positive_folds_fraction=Decimal("1.0"),
        max_regime_drawdown=Decimal("0.15"),
        trials_explored_k=1,
        verdict=PromotionGateVerdict.EXPLORATORY_PASSED,
        evaluated_at=TIMESTAMP,
    )

    # Tampering with verdict (e.g. promoting without qualification)
    tampered_rec_dict = rec.model_dump(mode="python")
    tampered_rec_dict["verdict"] = PromotionGateVerdict.PROMOTION_QUALIFIED
    with pytest.raises(
        ValidationError, match="promotion evaluation record hash mismatch"
    ):
        PromotionEvaluationRecordV1.model_validate(tampered_rec_dict)


def test_adversarial_vector_8_deterministic_ledger_replay(tmp_path: Path) -> None:
    """Vector 8: Ledger replay reconstructs identical archive state across restarts."""
    db_path = tmp_path / "replay_test.sqlite3"
    ledger1 = SQLiteLedger(db_path)
    recorder1 = PromotionRecorder(ledger1)

    cfg = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=TIMESTAMP,
        is_promotion_grade_authorized=True,
    )
    gk = PromotionGatekeeper(cfg)
    runner1 = PromotionRunner(gk, recorder=recorder1)

    c1 = uuid7()
    c2 = uuid7()
    c3 = uuid7()

    runner1.evaluate_candidate(
        CandidatePromotionRequestV1(
            candidate_id=c1,
            strategy_type="strat_a",
            parameters_hash="a" * 64,
            trials_explored_k=2,
            observed_sharpe=Decimal("2.50"),
            trial_sharpes=[Decimal("2.50")] * 2,
            trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
            walk_forward_fold_returns=[[0.01]],
            session_returns=[0.01],
            is_pnl_complete=True,
            skewness=0.0,
            kurtosis=3.0,
            sample_size_n=252,
            is_promotion_grade_evidence=True,
        )
    )
    runner1.evaluate_candidate(
        CandidatePromotionRequestV1(
            candidate_id=c2,
            strategy_type="strat_b",
            parameters_hash="b" * 64,
            trials_explored_k=2,
            observed_sharpe=Decimal("2.50"),
            trial_sharpes=[Decimal("2.50")] * 2,
            trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
            walk_forward_fold_returns=[[0.01]],
            session_returns=[0.01],
            is_pnl_complete=True,
            skewness=0.0,
            kurtosis=3.0,
            sample_size_n=252,
            is_promotion_grade_evidence=False,
        )
    )
    runner1.evaluate_candidate(
        CandidatePromotionRequestV1(
            candidate_id=c3,
            strategy_type="strat_c",
            parameters_hash="c" * 64,
            trials_explored_k=1,
            observed_sharpe=Decimal("2.50"),
            is_pnl_complete=False,
            is_promotion_grade_evidence=True,
        )
    )

    archive1 = PromotionArchive(ledger1)
    assert len(archive1.list_evaluations()) == 2
    assert len(archive1.list_certifications()) == 0
    assert len(archive1.list_rejections()) == 0
    assert len(archive1.list_incomplete_rejections()) == 1

    # Restart session: connect fresh ledger and archive instance
    ledger2 = SQLiteLedger(db_path)
    archive2 = PromotionArchive(ledger2)

    assert len(archive2.list_evaluations()) == 2
    assert len(archive2.list_certifications()) == 0
    assert len(archive2.list_rejections()) == 0
    assert (
        archive2.list_incomplete_rejections() == archive1.list_incomplete_rejections()
    )
    assert not archive2.is_candidate_certified(c1)
    assert not archive2.is_candidate_certified(c2)
    assert not archive2.is_candidate_certified(c3)

    assert all(
        r.verdict == PromotionGateVerdict.EXPLORATORY_PASSED
        for r in archive2.list_evaluations()
    )
