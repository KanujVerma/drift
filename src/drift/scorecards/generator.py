"""Composite scorecard generator harness and pipeline integration.

Covers M5-5 (Issue 197).

Provides:
- Orchestration of prediction, strategy, and multiple-testing scorecard synthesis;
- Deterministic UUIDv7 identity derivation for repeatable scorecards;
- Append-only research ledger integration (m5.scorecard.recorded event sealing);
- Standalone function generate_model_scorecard and class ScorecardGeneratorHarness.
"""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid7

from drift.domain.common import _freeze_json
from drift.domain.evaluator_bundles import EvaluationRunIdentityV2
from drift.domain.evaluator_portfolio import EvaluationLane
from drift.domain.evaluator_results import (
    EvaluationResultV1,
    EvaluationSummaryMetricsV1,
)
from drift.domain.scorecards import (
    SCORECARD_EVENT_TYPE,
    SCORECARD_SCHEMA_VERSION,
    ModelScorecardV1,
    MultipleTestingSummaryV1,
    PredictionScorecardV1,
    StrategyScorecardV1,
    build_model_scorecard,
)
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.scorecards.multiple_testing import compute_multiple_testing_summary
from drift.scorecards.performance import generate_strategy_scorecard

SCORECARD_ENTITY_TYPE = "scorecard"


def deterministic_scorecard_uuid7(seed: str) -> UUID:
    """Derive a deterministic UUIDv7 value from a seed string."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    raw = int(digest[:32], 16)
    raw &= ~(0xF << 76)
    raw |= 0x7 << 76
    raw &= ~(0x3 << 62)
    raw |= 0x2 << 62
    return UUID(int=raw)


class ScorecardGeneratorHarness:
    """Orchestration harness for generating and sealing quantitative scorecards."""

    def __init__(
        self,
        *,
        ledger: Ledger | None = None,
        deterministic: bool = True,
    ) -> None:
        self._ledger = ledger
        self._deterministic = deterministic

    def generate_model_scorecard(
        self,
        *,
        run_identity: EvaluationRunIdentityV2,
        lane: EvaluationLane,
        evaluation_result: EvaluationResultV1
        | EvaluationSummaryMetricsV1
        | None = None,
        strategy_scorecard: StrategyScorecardV1 | None = None,
        prediction_scorecard: PredictionScorecardV1 | None = None,
        multiple_testing: MultipleTestingSummaryV1 | None = None,
        trial_sharpe_ratios: Sequence[Decimal] | None = None,
        trial_p_values: Sequence[Decimal] | None = None,
        candidate_p_value: Decimal | None = None,
        created_at: datetime | None = None,
        scorecard_id: UUID | None = None,
        audit_event_id: UUID | None = None,
    ) -> ModelScorecardV1:
        """Construct and seal a composite ModelScorecardV1."""
        created_dt = (
            created_at.astimezone(UTC) if created_at is not None else datetime.now(UTC)
        )

        run_id_str = run_identity.run_identity_hash

        # 1. Resolve StrategyScorecardV1
        resolved_strat = strategy_scorecard
        if resolved_strat is None and evaluation_result is not None:
            strat_sc_id = None
            if self._deterministic:
                strat_seed = (
                    f"{run_id_str}:strategy_scorecard:{lane}:{created_dt.isoformat()}"
                )
                strat_sc_id = deterministic_scorecard_uuid7(strat_seed)
            resolved_strat = generate_strategy_scorecard(
                result=evaluation_result,
                run_identity=run_identity,
                lane=lane,
                as_of_time=created_dt,
                scorecard_id=strat_sc_id,
            )

        # 2. Resolve MultipleTestingSummaryV1
        resolved_mt = multiple_testing
        if resolved_mt is None and trial_sharpe_ratios is not None:
            if resolved_strat is not None:
                cand_sharpe = resolved_strat.sharpe_ratio
                sample_n = 252
                if evaluation_result is not None:
                    if hasattr(evaluation_result, "metrics"):
                        sample_n = evaluation_result.metrics.evaluated_session_count
                    elif hasattr(evaluation_result, "evaluated_session_count"):
                        sample_n = evaluation_result.evaluated_session_count
            else:
                cand_sharpe = trial_sharpe_ratios[0]
                sample_n = 252

            resolved_mt = compute_multiple_testing_summary(
                candidate_sharpe=cand_sharpe,
                trial_sharpe_ratios=trial_sharpe_ratios,
                sample_size_sessions=sample_n,
                candidate_p_value=candidate_p_value,
                trial_p_values=trial_p_values,
            )

        # 3. Derive model scorecard identity
        if scorecard_id is None:
            if self._deterministic:
                model_seed = (
                    f"{run_id_str}:model_scorecard:{lane}:{created_dt.isoformat()}"
                )
                scorecard_id = deterministic_scorecard_uuid7(model_seed)
            else:
                scorecard_id = uuid7()

        # 4. Build composite ModelScorecardV1
        model_scorecard = build_model_scorecard(
            scorecard_id=scorecard_id,
            run_identity=run_identity,
            lane=lane,
            prediction_scorecard=prediction_scorecard,
            strategy_scorecard=resolved_strat,
            multiple_testing=resolved_mt,
            created_at=created_dt,
        )

        # 5. Record to ledger if configured
        if self._ledger is not None:
            if audit_event_id is None:
                if self._deterministic:
                    evt_seed = (
                        f"{run_id_str}:scorecard_event:{model_scorecard.scorecard_id}"
                    )
                    audit_event_id = deterministic_scorecard_uuid7(evt_seed)
                else:
                    audit_event_id = uuid7()

            draft = AuditEventDraft(
                schema_version=SCORECARD_SCHEMA_VERSION,
                event_id=audit_event_id,
                event_type=SCORECARD_EVENT_TYPE,
                timestamp=created_dt,
                entity_type=SCORECARD_ENTITY_TYPE,
                entity_id=model_scorecard.scorecard_id,
                payload=_freeze_json(model_scorecard.model_dump(mode="python")),
            )
            self._ledger.append(draft)

        return model_scorecard


def generate_model_scorecard(
    *,
    run_identity: EvaluationRunIdentityV2,
    lane: EvaluationLane,
    evaluation_result: EvaluationResultV1 | EvaluationSummaryMetricsV1 | None = None,
    strategy_scorecard: StrategyScorecardV1 | None = None,
    prediction_scorecard: PredictionScorecardV1 | None = None,
    multiple_testing: MultipleTestingSummaryV1 | None = None,
    trial_sharpe_ratios: Sequence[Decimal] | None = None,
    trial_p_values: Sequence[Decimal] | None = None,
    candidate_p_value: Decimal | None = None,
    created_at: datetime | None = None,
    scorecard_id: UUID | None = None,
    ledger: Ledger | None = None,
    deterministic: bool = True,
) -> ModelScorecardV1:
    """Convenience function to generate a ModelScorecardV1."""
    harness = ScorecardGeneratorHarness(
        ledger=ledger,
        deterministic=deterministic,
    )
    return harness.generate_model_scorecard(
        run_identity=run_identity,
        lane=lane,
        evaluation_result=evaluation_result,
        strategy_scorecard=strategy_scorecard,
        prediction_scorecard=prediction_scorecard,
        multiple_testing=multiple_testing,
        trial_sharpe_ratios=trial_sharpe_ratios,
        trial_p_values=trial_p_values,
        candidate_p_value=candidate_p_value,
        created_at=created_at,
        scorecard_id=scorecard_id,
    )
