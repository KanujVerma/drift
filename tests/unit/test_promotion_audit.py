"""Unit tests for promotion audit events, recorder, and archive (M11-4, Issue 261)."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from drift.domain.common import _freeze_json
from drift.domain.promotion import (
    CANDIDATE_CERTIFIED_EVENT_TYPE,
    CANDIDATE_REJECTED_EVENT_TYPE,
    GATE_EVALUATED_EVENT_TYPE,
    CandidateCertifiedAuditEventPayloadV1,
    GateEvaluatedAuditEventPayloadV1,
    PromotionEvaluationRecordV1,
    PromotionGateVerdict,
    build_promotion_evaluation_record,
    build_promotion_gate_config,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.recorder import deterministic_memory_uuid7
from drift.promotion.archive import PromotionArchive
from drift.promotion.gatekeeper import PromotionGatekeeper
from drift.promotion.recorder import (
    PROMOTION_CERTIFICATION_ENTITY_TYPE,
    PROMOTION_EVALUATION_ENTITY_TYPE,
    PROMOTION_REJECTION_ENTITY_TYPE,
    PromotionRecorder,
)
from drift.promotion.runner import (
    CandidatePromotionRequestV1,
    PromotionBatchInterrupted,
    PromotionRunner,
)
from drift.serialization.canonical import canonical_json, content_hash

EVAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
CAND_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
EVAL_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
CAND_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")
TIMESTAMP = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)


def test_promotion_recorder_and_archive(tmp_path: Path) -> None:
    """PromotionRecorder seals events into SQLite ledger; archive reconstructs."""
    ledger = SQLiteLedger(tmp_path / "promotion_audit.sqlite3")
    recorder = PromotionRecorder(ledger)
    archive = PromotionArchive(ledger)

    assert len(archive.list_evaluations()) == 0
    assert len(archive.list_certifications()) == 0
    assert len(archive.list_rejections()) == 0

    # Build qualified evaluation record
    rec1 = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_1,
        candidate_id=CAND_ID_1,
        strategy_type="momentum_v1",
        parameters_hash="a" * 64,
        deflated_sharpe_ratio=Decimal("0.98"),
        pbo_estimate=Decimal("0.10"),
        positive_folds_fraction=Decimal("1.0"),
        max_regime_drawdown=Decimal("0.15"),
        trials_explored_k=5,
        verdict=PromotionGateVerdict.PROMOTION_QUALIFIED,
        evaluated_at=TIMESTAMP,
    )

    # Seed exact historical V1 envelopes, not a new certification.
    ev_eval = ledger.append(
        AuditEventDraft(
            schema_version="1",
            event_id=deterministic_memory_uuid7(f"promotion_eval:{rec1.evaluation_id}"),
            event_type=GATE_EVALUATED_EVENT_TYPE,
            timestamp=rec1.evaluated_at,
            entity_type=PROMOTION_EVALUATION_ENTITY_TYPE,
            entity_id=rec1.evaluation_id,
            payload=_freeze_json(
                GateEvaluatedAuditEventPayloadV1(evaluation=rec1).model_dump(
                    mode="python"
                )
            ),
            deduplication_key=f"m11:eval:{rec1.evaluation_id}",
        )
    )
    assert ev_eval.event_type == GATE_EVALUATED_EVENT_TYPE
    assert ev_eval.entity_type == PROMOTION_EVALUATION_ENTITY_TYPE
    assert ev_eval.entity_id == EVAL_ID_1

    ev_cert = ledger.append(
        AuditEventDraft(
            schema_version="1",
            event_id=deterministic_memory_uuid7(
                f"promotion_cert:{rec1.evaluation_id}:{rec1.candidate_id}"
            ),
            event_type=CANDIDATE_CERTIFIED_EVENT_TYPE,
            timestamp=rec1.evaluated_at,
            entity_type=PROMOTION_CERTIFICATION_ENTITY_TYPE,
            entity_id=rec1.candidate_id,
            payload=_freeze_json(
                CandidateCertifiedAuditEventPayloadV1(
                    evaluation_id=rec1.evaluation_id,
                    candidate_id=rec1.candidate_id,
                    strategy_type=rec1.strategy_type,
                    verdict=rec1.verdict,
                    certified_at=rec1.evaluated_at,
                ).model_dump(mode="python")
            ),
            deduplication_key=f"m11:cert:{rec1.evaluation_id}",
        )
    )
    assert (
        rec1.record_hash
        == "78c18bfefc55e2f87a5b919fa5492b459a1deed875abfe46be08948e375595fe"
    )
    assert (
        ev_eval.event_hash
        == "a8bf3a595cf88922fedd345f6f2e8f6d102d225a68c9700e08d8ad9dbfa0340e"
    )
    assert (
        ev_cert.event_hash
        == "aa92b821b71b9c8d7ef01a45e32f4acccfb0fa4d58f4ba3d3321cf80628bcaec"
    )
    assert canonical_json(ev_cert.payload) == (
        b'{"candidate_id":"018f3a5b-6c7d-7890-8123-456789abcd02",'
        b'"certified_at":"2026-02-01T12:00:00.000000Z",'
        b'"evaluation_id":"018f3a5b-6c7d-7890-8123-456789abcd01",'
        b'"schema_version":"1","strategy_type":"momentum_v1",'
        b'"verdict":"promotion_qualified"}'
    )
    assert ev_cert.event_type == CANDIDATE_CERTIFIED_EVENT_TYPE
    assert ev_cert.entity_type == PROMOTION_CERTIFICATION_ENTITY_TYPE
    assert ev_cert.entity_id == CAND_ID_1

    # Build rejected evaluation record
    rec2 = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_2,
        candidate_id=CAND_ID_2,
        strategy_type="reversal_v1",
        parameters_hash="b" * 64,
        deflated_sharpe_ratio=Decimal("0.40"),
        pbo_estimate=Decimal("0.50"),
        positive_folds_fraction=Decimal("0.40"),
        max_regime_drawdown=Decimal("0.35"),
        trials_explored_k=50,
        verdict=PromotionGateVerdict.REJECTED_DEFLATED_SHARPE,
        rejection_reasons=("deflated_sharpe_ratio_below_threshold",),
        evaluated_at=TIMESTAMP,
    )

    recorder.record_evaluation(rec2)
    ev_rej = recorder.record_rejection(rec2)
    assert ev_rej.event_type == CANDIDATE_REJECTED_EVENT_TYPE
    assert ev_rej.entity_type == PROMOTION_REJECTION_ENTITY_TYPE
    assert ev_rej.entity_id == CAND_ID_2

    # Refresh archive and query reconstructed state
    archive.refresh()
    assert len(archive.list_evaluations()) == 2
    assert len(archive.list_certifications()) == 1
    assert len(archive.list_rejections()) == 1

    assert archive.is_candidate_certified(CAND_ID_1)
    assert not archive.is_candidate_certified(CAND_ID_2)

    eval_found = archive.get_evaluation(EVAL_ID_1)
    assert eval_found is not None
    assert eval_found.candidate_id == CAND_ID_1
    assert eval_found.verdict == PromotionGateVerdict.PROMOTION_QUALIFIED
    assert SQLiteLedger(tmp_path / "promotion_audit.sqlite3").verified_events()[:2] == (
        ev_eval,
        ev_cert,
    )


def test_promotion_runner_with_sqlite_ledger(tmp_path: Path) -> None:
    """PromotionRunner seals batches into SQLite ledger, verified via Archive."""
    ledger = SQLiteLedger(tmp_path / "runner_audit.sqlite3")
    recorder = PromotionRecorder(ledger)
    archive = PromotionArchive(ledger)

    config = build_promotion_gate_config(
        config_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd99"),
        created_at=TIMESTAMP,
        is_promotion_grade_authorized=True,
    )
    gk = PromotionGatekeeper(config)
    runner = PromotionRunner(gk, recorder=recorder)

    req1 = CandidatePromotionRequestV1(
        candidate_id=CAND_ID_1,
        strategy_type="momentum_v1",
        parameters_hash="1" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.40"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=True,
    )

    req2 = CandidatePromotionRequestV1(
        candidate_id=CAND_ID_2,
        strategy_type="mean_rev_v1",
        parameters_hash="2" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.40"),
        is_pnl_complete=False,
        is_promotion_grade_evidence=True,
    )

    batch_res = runner.evaluate_batch_v2([req1, req2])
    assert len(batch_res.records) == 2

    archive.refresh()
    assert len(archive.list_evaluations()) == 1
    assert len(archive.list_certifications()) == 0
    assert len(archive.list_rejections()) == 0
    assert len(archive.list_incomplete_rejections()) == 1
    assert not archive.is_candidate_certified(CAND_ID_1)
    assert not archive.is_candidate_certified(CAND_ID_2)


def test_incomplete_request_seals_truthful_single_event(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "incomplete.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    runner = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    request = CandidatePromotionRequestV1(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("1"),
        is_promotion_grade_evidence=True,
    )

    result = runner.evaluate_candidate(request)
    events = ledger.verified_events()
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert len(events) == 1
    assert events[0].event_type == "m11.gate.incomplete_rejected"
    assert isinstance(events[0].payload, Mapping)
    assert events[0].payload["verdict"] == "rejected_incomplete_evidence"
    assert "deflated_sharpe_ratio" not in events[0].payload
    assert "pbo_estimate" not in events[0].payload
    archive = PromotionArchive(ledger)
    assert not archive.is_candidate_certified(CAND_ID_1)
    assert archive.list_evaluations() == []  # legacy V1 view cannot represent it
    assert archive.list_rejections() == []
    assert archive.list_incomplete_rejections() == [result]
    assert archive.get_attempt(result.evaluation_id) == result


def test_direct_recorder_refuses_untrusted_certification(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "untrusted.sqlite3")
    record = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_1,
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        deflated_sharpe_ratio=Decimal("1"),
        pbo_estimate=Decimal("0"),
        positive_folds_fraction=Decimal("1"),
        max_regime_drawdown=Decimal("0"),
        trials_explored_k=1,
        verdict=PromotionGateVerdict.PROMOTION_QUALIFIED,
        evaluated_at=TIMESTAMP,
    )
    with pytest.raises(RuntimeError, match="certification"):
        PromotionRecorder(ledger).record_certification(record)
    with pytest.raises(ValueError, match="unauthenticated"):
        PromotionRecorder(ledger).record_evaluation(record)
    with pytest.raises(ValueError, match="statistical rejection"):
        PromotionRecorder(ledger).record_rejection(record)
    assert ledger.verified_events() == ()


def test_recorder_rejects_falsey_invalid_event_id(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "invalid-event-id.sqlite3")
    record = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_1,
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        deflated_sharpe_ratio=Decimal("1"),
        pbo_estimate=Decimal("0"),
        positive_folds_fraction=Decimal("1"),
        max_regime_drawdown=Decimal("0"),
        trials_explored_k=1,
        verdict=PromotionGateVerdict.EXPLORATORY_PASSED,
        evaluated_at=TIMESTAMP,
    )
    with pytest.raises(ValueError):
        PromotionRecorder(ledger).record_evaluation(record, event_id=0)  # type: ignore[arg-type]
    assert ledger.verified_events() == ()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("trial_block_matrix", None),
        ("walk_forward_fold_returns", None),
        ("session_returns", None),
        ("trial_block_matrix", [[1.0, 2.0]]),
        ("trial_block_matrix", [[1.0, 2.0], [1.0]]),
        ("trial_block_matrix", [[float("nan"), 2.0], [1.0, 2.0]]),
        ("walk_forward_fold_returns", [[]]),
        ("walk_forward_fold_returns", [[float("inf")]]),
        ("session_returns", [Decimal("NaN")]),
        ("session_returns", []),
        ("is_pnl_complete", 1),
    ],
)
def test_unusable_evidence_seals_incomplete_rejection(
    tmp_path: Path,
    field: str,
    bad_value: object,
) -> None:
    ledger = SQLiteLedger(tmp_path / "unusable.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    values: dict[str, Any] = {
        "candidate_id": CAND_ID_1,
        "strategy_type": "synthetic",
        "parameters_hash": "a" * 64,
        "trials_explored_k": 1,
        "observed_sharpe": Decimal("2"),
        "trial_block_matrix": [[1.0, 1.0], [0.0, 0.0]],
        "walk_forward_fold_returns": [[0.01]],
        "session_returns": [0.01],
        "is_pnl_complete": True,
        "skewness": 0.0,
        "kurtosis": 3.0,
        "sample_size_n": 252,
    }
    values[field] = bad_value
    result = PromotionGatekeeper(config).evaluate_candidate(
        **values,
        recorder=PromotionRecorder(ledger),
    )
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert len(ledger.verified_events()) == 1
    assert ledger.verified_events()[0].event_type == "m11.gate.incomplete_rejected"
    if field == "is_pnl_complete":
        assert "pnl_completeness_not_confirmed" in result.rejection_reasons


def test_multiple_trials_without_variance_evidence_are_rejected(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "variance.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    result = PromotionGatekeeper(config).evaluate_candidate(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=2,
        observed_sharpe=Decimal("2"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        recorder=PromotionRecorder(ledger),
    )
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert "unusable_trial_sharpes" in result.rejection_reasons


def test_omitted_dsr_distribution_inputs_are_not_fabricated(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "missing-dsr.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    result = PromotionGatekeeper(config).evaluate_candidate(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        recorder=PromotionRecorder(ledger),
    )
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert "unusable_distribution_inputs" in result.rejection_reasons
    assert "unusable_sample_size_n" in result.rejection_reasons


def test_finite_inputs_with_nonfinite_intermediate_fail_closed(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "overflow.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    result = PromotionGatekeeper(config).evaluate_candidate(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[1e308, 1e308],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        recorder=PromotionRecorder(ledger),
    )
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert result.rejection_reasons == ("unusable_numeric_calculation",)
    assert [e.event_type for e in ledger.verified_events()] == [
        "m11.gate.incomplete_rejected"
    ]


def test_nonpositive_dsr_variance_seals_incomplete_rejection(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "invalid-dsr-variance.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    result = PromotionGatekeeper(config).evaluate_candidate(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("1"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=2.0,
        kurtosis=1.0,
        sample_size_n=252,
        recorder=PromotionRecorder(ledger),
    )
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert result.rejection_reasons == ("unusable_numeric_calculation",)
    assert [event.event_type for event in ledger.verified_events()] == [
        "m11.gate.incomplete_rejected"
    ]


def test_incomplete_exact_retry_and_conflict_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "retry.sqlite3"
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    args: dict[str, Any] = dict(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("1"),
        evaluation_id=EVAL_ID_2,
        evaluated_at=TIMESTAMP,
    )
    ledger = SQLiteLedger(path)
    first = PromotionGatekeeper(config).evaluate_candidate(
        **args,
        recorder=PromotionRecorder(ledger),
    )
    before = ledger.verified_events()
    reopened = SQLiteLedger(path)
    retry = PromotionGatekeeper(config).evaluate_candidate(
        **args,
        recorder=PromotionRecorder(reopened),
    )
    assert retry == first
    assert reopened.verified_events() == before
    with pytest.raises(ValueError, match="conflict"):
        PromotionGatekeeper(config).evaluate_candidate(
            **{**args, "observed_sharpe": Decimal("2")},
            recorder=PromotionRecorder(reopened),
        )
    assert reopened.verified_events() == before


def test_complete_retry_rejects_different_evidence_with_same_metrics(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "complete-conflict.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    runner = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    values: dict[str, Any] = dict(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        evaluation_id=EVAL_ID_2,
        evaluated_at=TIMESTAMP,
    )
    runner.evaluate_candidate(CandidatePromotionRequestV1(**values))
    before = ledger.verified_events()
    with pytest.raises(ValueError, match="conflict"):
        runner.evaluate_candidate(
            CandidatePromotionRequestV1(
                **{**values, "walk_forward_fold_returns": [[0.02]]}
            )
        )
    assert ledger.verified_events() == before


def _complete_request_values() -> dict[str, Any]:
    return dict(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2"),
        trial_sharpes=[Decimal("2"), Decimal("2")],
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        is_promotion_grade_evidence=False,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        evaluation_id=EVAL_ID_2,
        evaluated_at=TIMESTAMP,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_id", CAND_ID_2),
        ("strategy_type", "other"),
        ("parameters_hash", "b" * 64),
        ("trials_explored_k", 2),
        ("observed_sharpe", Decimal("2.1")),
        ("trial_sharpes", [Decimal("2"), Decimal("2.1")]),
        ("trial_block_matrix", [[1.1, 1.0], [0.0, 0.0]]),
        ("walk_forward_fold_returns", [[0.02]]),
        ("session_returns", [0.02]),
        ("is_pnl_complete", False),
        ("is_promotion_grade_evidence", True),
        ("skewness", 0.1),
        ("kurtosis", 3.1),
        ("sample_size_n", 253),
        ("evaluated_at", TIMESTAMP + timedelta(seconds=1)),
    ],
)
def test_complete_retry_binds_each_request_field(
    tmp_path: Path, field: str, value: object
) -> None:
    path = tmp_path / "bound.sqlite3"
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    request = CandidatePromotionRequestV1(**_complete_request_values())
    ledger = SQLiteLedger(path)
    first = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    record = first.evaluate_candidate(request)
    before = ledger.verified_events()
    reopened = SQLiteLedger(path)
    retry = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(reopened))
    assert retry.evaluate_candidate(request) == record
    assert reopened.verified_events() == before
    with pytest.raises(ValueError, match="conflict"):
        retry.evaluate_candidate(
            CandidatePromotionRequestV1(**{**_complete_request_values(), field: value})
        )
    assert reopened.verified_events() == before


def test_complete_request_binding_hash_and_config_conflict(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "binding.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    request = CandidatePromotionRequestV1(**_complete_request_values())
    runner = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    record = runner.evaluate_candidate(request)
    assert isinstance(record, PromotionEvaluationRecordV1)
    event = ledger.verified_events()[0]
    expected_hash = content_hash(
        {
            "config": config.model_dump(mode="python"),
            "evaluation_id": EVAL_ID_2,
            "candidate_id": CAND_ID_1,
            "strategy_type": "synthetic",
            "parameters_hash": "a" * 64,
            "evaluated_at": TIMESTAMP,
            "inputs": [
                "sequence",
                [
                    ["int", "1"],
                    ["decimal", "2"],
                    ["sequence", [["decimal", "2"], ["decimal", "2"]]],
                    [
                        "sequence",
                        [
                            [
                                "sequence",
                                [["float", (1.0).hex()], ["float", (1.0).hex()]],
                            ],
                            [
                                "sequence",
                                [["float", (0.0).hex()], ["float", (0.0).hex()]],
                            ],
                        ],
                    ],
                    ["sequence", [["sequence", [["float", (0.01).hex()]]]]],
                    ["sequence", [["float", (0.01).hex()]]],
                    ["bool", True],
                    ["bool", False],
                    ["float", (0.0).hex()],
                    ["float", (3.0).hex()],
                    ["int", "252"],
                ],
            ],
        }
    )
    assert event.event_id == deterministic_memory_uuid7(
        f"promotion_eval_request:{EVAL_ID_2}:{expected_hash}"
    )
    assert event.deduplication_key == f"m11:eval:{EVAL_ID_2}"
    assert canonical_json(event.payload) == canonical_json(
        GateEvaluatedAuditEventPayloadV1(evaluation=record).model_dump(mode="python")
    )
    other_config = build_promotion_gate_config(
        config_id=EVAL_ID_1, created_at=TIMESTAMP, is_promotion_grade_authorized=True
    )
    with pytest.raises(ValueError, match="conflict"):
        PromotionRunner(
            PromotionGatekeeper(other_config), PromotionRecorder(ledger)
        ).evaluate_candidate(request)
    assert ledger.verified_events() == (event,)


def test_legacy_v1_same_id_is_not_assumed_to_bind_request(tmp_path: Path) -> None:
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    request = CandidatePromotionRequestV1(**_complete_request_values())
    source = SQLiteLedger(tmp_path / "source.sqlite3")
    record = PromotionRunner(
        PromotionGatekeeper(config), PromotionRecorder(source)
    ).evaluate_candidate(request)
    assert isinstance(record, PromotionEvaluationRecordV1)
    assert record.verdict == PromotionGateVerdict.EXPLORATORY_PASSED
    ledger = SQLiteLedger(tmp_path / "legacy.sqlite3")
    PromotionRecorder(ledger).record_evaluation(record)
    before = ledger.verified_events()
    assert PromotionArchive(ledger).get_evaluation(EVAL_ID_2) == record
    with pytest.raises(ValueError, match="conflict"):
        PromotionRunner(
            PromotionGatekeeper(config), PromotionRecorder(ledger)
        ).evaluate_candidate(request)
    assert ledger.verified_events() == before


@pytest.mark.parametrize(
    ("field", "value"),
    [("observed_sharpe", object()), ("is_promotion_grade_evidence", float("nan"))],
)
def test_unfingerprintable_or_nonfinite_request_refuses_without_event(
    tmp_path: Path, field: str, value: object
) -> None:
    ledger = SQLiteLedger(tmp_path / "invalid-binding.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    with pytest.raises(ValueError):
        PromotionRunner(
            PromotionGatekeeper(config), PromotionRecorder(ledger)
        ).evaluate_candidate(
            CandidatePromotionRequestV1(**{**_complete_request_values(), field: value})
        )
    assert ledger.verified_events() == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_sharpe", Decimal("NaN")),
        ("trial_sharpes", [Decimal("NaN")]),
        ("trial_block_matrix", [[float("inf"), 1.0], [0.0, 0.0]]),
        ("walk_forward_fold_returns", [[float("nan")]]),
        ("session_returns", [float("inf")]),
        ("skewness", float("nan")),
        ("kurtosis", float("inf")),
    ],
)
def test_nonfinite_complete_request_is_sealed_incomplete(
    tmp_path: Path, field: str, value: object
) -> None:
    ledger = SQLiteLedger(tmp_path / "nonfinite-binding.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    result = PromotionRunner(
        PromotionGatekeeper(config), PromotionRecorder(ledger)
    ).evaluate_candidate(
        CandidatePromotionRequestV1(**{**_complete_request_values(), field: value})
    )
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert [event.event_type for event in ledger.verified_events()] == [
        "m11.gate.incomplete_rejected"
    ]


def test_complete_request_type_changes_conflict(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "type-conflict.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    runner = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    runner.evaluate_candidate(CandidatePromotionRequestV1(**_complete_request_values()))
    before = ledger.verified_events()
    with pytest.raises(ValueError, match="conflict"):
        runner.evaluate_candidate(
            CandidatePromotionRequestV1(
                **{**_complete_request_values(), "observed_sharpe": 2.0}
            )
        )
    assert ledger.verified_events() == before


def test_append_error_after_commit_refuses_then_exact_retry_succeeds(
    tmp_path: Path,
) -> None:
    class CommitThenFail(SQLiteLedger):
        def append(self, draft: AuditEventDraft):  # type: ignore[no-untyped-def]
            super().append(draft)
            raise OSError("injected lost append response")

    path = tmp_path / "lost-response.sqlite3"
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    request = CandidatePromotionRequestV1(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("1"),
        evaluation_id=EVAL_ID_2,
        evaluated_at=TIMESTAMP,
    )
    failing = CommitThenFail(path)
    with pytest.raises(OSError, match="lost append response"):
        PromotionRunner(
            PromotionGatekeeper(config), PromotionRecorder(failing)
        ).evaluate_candidate(request)
    original = failing.verified_events()
    assert len(original) == 1
    reopened = SQLiteLedger(path)
    result = PromotionRunner(
        PromotionGatekeeper(config), PromotionRecorder(reopened)
    ).evaluate_candidate(request)
    assert result.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert reopened.verified_events() == original


@pytest.mark.parametrize("incomplete_first", [True, False])
def test_attempt_id_conflict_across_event_versions(
    tmp_path: Path, incomplete_first: bool
) -> None:
    ledger = SQLiteLedger(tmp_path / "cross-version.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    runner = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    common: dict[str, Any] = {
        "candidate_id": CAND_ID_1,
        "strategy_type": "synthetic",
        "parameters_hash": "a" * 64,
        "trials_explored_k": 1,
        "observed_sharpe": Decimal("2"),
        "evaluation_id": EVAL_ID_2,
        "evaluated_at": TIMESTAMP,
    }
    incomplete = CandidatePromotionRequestV1(**common)
    complete = CandidatePromotionRequestV1(
        **common,
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
    )
    first, second = (
        (incomplete, complete) if incomplete_first else (complete, incomplete)
    )
    runner.evaluate_candidate(first)
    before = ledger.verified_events()
    with pytest.raises(ValueError, match="conflict"):
        runner.evaluate_candidate(second)
    assert ledger.verified_events() == before


def test_invalid_attempt_identity_refuses_without_event(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "invalid-id.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    with pytest.raises(ValueError):
        PromotionGatekeeper(config).evaluate_candidate(
            candidate_id=UUID(int=0),
            strategy_type="synthetic",
            parameters_hash="a" * 64,
            trials_explored_k=1,
            observed_sharpe=Decimal("1"),
            recorder=PromotionRecorder(ledger),
        )
    assert ledger.verified_events() == ()


@pytest.mark.parametrize(
    ("field", "invalid"), [("evaluation_id", 0), ("evaluated_at", 0)]
)
def test_falsey_invalid_attempt_identifiers_are_not_replaced(
    tmp_path: Path, field: str, invalid: object
) -> None:
    ledger = SQLiteLedger(tmp_path / "falsey-identity.sqlite3")
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    kwargs: dict[str, Any] = {field: invalid}
    with pytest.raises(ValueError):
        PromotionGatekeeper(config).evaluate_candidate(
            candidate_id=CAND_ID_1,
            strategy_type="synthetic",
            parameters_hash="a" * 64,
            trials_explored_k=1,
            observed_sharpe=Decimal("1"),
            recorder=PromotionRecorder(ledger),
            **kwargs,
        )
    assert ledger.verified_events() == ()


def test_complete_exploratory_result_requires_a_sealed_evaluation(
    tmp_path: Path,
) -> None:
    config = build_promotion_gate_config(
        config_id=EVAL_ID_1,
        created_at=TIMESTAMP,
        is_promotion_grade_authorized=True,
    )
    args: dict[str, Any] = dict(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=True,
    )
    with pytest.raises(RuntimeError, match="record|seal|audit"):
        PromotionGatekeeper(config).evaluate_candidate(**args)
    ledger = SQLiteLedger(tmp_path / "complete.sqlite3")
    result = PromotionGatekeeper(config).evaluate_candidate(
        **args,
        recorder=PromotionRecorder(ledger),
    )
    assert result.verdict == PromotionGateVerdict.EXPLORATORY_PASSED
    assert [event.event_type for event in ledger.verified_events()] == [
        GATE_EVALUATED_EVENT_TYPE
    ]


def test_mixed_batch_reports_prefix_and_restarts_after_append_failure(
    tmp_path: Path,
) -> None:
    class InterruptingLedger(SQLiteLedger):
        calls = 0

        def append(self, draft):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 2:
                raise OSError("injected append failure")
            return super().append(draft)

    path = tmp_path / "batch.sqlite3"
    ledger = InterruptingLedger(path)
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    runner = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    complete: dict[str, Any] = dict(
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
    )
    requests = (
        CandidatePromotionRequestV1(candidate_id=CAND_ID_1, **complete),
        CandidatePromotionRequestV1(
            candidate_id=CAND_ID_2,
            strategy_type="missing",
            parameters_hash="b" * 64,
            trials_explored_k=1,
            observed_sharpe=Decimal("1"),
        ),
        CandidatePromotionRequestV1(
            candidate_id=EVAL_ID_2, **{**complete, "observed_sharpe": Decimal("-2")}
        ),
    )
    assert hasattr(runner, "evaluate_batch_v2")
    with pytest.raises(PromotionBatchInterrupted) as caught:
        runner.evaluate_batch_v2(requests)
    interruption = caught.value
    assert len(interruption.committed_prefix) == 1
    assert (
        interruption.committed_prefix[0].verdict
        == PromotionGateVerdict.EXPLORATORY_PASSED
    )
    assert interruption.failed_attempt == requests[1]
    assert interruption.unprocessed_suffix == requests[2:]
    assert interruption.failed_events == ()
    reopened = SQLiteLedger(path)
    result = PromotionRunner(
        PromotionGatekeeper(config), PromotionRecorder(reopened)
    ).evaluate_batch_v2((interruption.failed_attempt, *interruption.unprocessed_suffix))
    assert len(result.records) == 2
    assert [e.event_type for e in reopened.verified_events()] == [
        GATE_EVALUATED_EVENT_TYPE,
        "m11.gate.incomplete_rejected",
        GATE_EVALUATED_EVENT_TYPE,
        CANDIDATE_REJECTED_EVENT_TYPE,
    ]


def test_batch_reports_partial_statistical_attempt_and_retries(tmp_path: Path) -> None:
    class InterruptSecondAppend(SQLiteLedger):
        calls = 0

        def append(self, draft):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 2:
                raise OSError("interrupted between legacy events")
            return super().append(draft)

    path = tmp_path / "partial.sqlite3"
    ledger = InterruptSecondAppend(path)
    config = build_promotion_gate_config(config_id=EVAL_ID_1, created_at=TIMESTAMP)
    request = CandidatePromotionRequestV1(
        candidate_id=CAND_ID_1,
        strategy_type="synthetic",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("-2"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
    )
    runner = PromotionRunner(PromotionGatekeeper(config), PromotionRecorder(ledger))
    with pytest.raises(PromotionBatchInterrupted) as caught:
        runner.evaluate_batch_v2((request,))
    interruption = caught.value
    assert interruption.committed_prefix == ()
    assert interruption.failed_attempt == request
    assert interruption.unprocessed_suffix == ()
    assert interruption.failed_events is not None
    assert [event.event_type for event in interruption.failed_events] == [
        GATE_EVALUATED_EVENT_TYPE
    ]
    before = ledger.verified_events()[0]
    reopened = SQLiteLedger(path)
    result = PromotionRunner(
        PromotionGatekeeper(config), PromotionRecorder(reopened)
    ).evaluate_batch_v2((request,))
    assert result.records[0].verdict == PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
    assert reopened.verified_events()[0] == before
    assert [event.event_type for event in reopened.verified_events()] == [
        GATE_EVALUATED_EVENT_TYPE,
        CANDIDATE_REJECTED_EVENT_TYPE,
    ]
