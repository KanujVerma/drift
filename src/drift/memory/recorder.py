"""Structured research memory recorder and M0 ledger persistence (M6-2).

Provides atomic, append-only sealing of research trials, failure postmortems,
and hypothesis lifecycle state updates into the Drift SQLite research ledger.
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from drift.domain.common import _freeze_json
from drift.domain.events import AuditEvent
from drift.domain.research_memory import (
    HYPOTHESIS_STATE_EVENT_TYPE,
    POSTMORTEM_EVENT_TYPE,
    RESEARCH_MEMORY_SCHEMA_VERSION,
    TRIAL_EVENT_TYPE,
    FailureCategory,
    FailurePostmortemV1,
    HypothesisLifecycleV1,
    HypothesisStateUpdatedAuditEventPayloadV1,
    PostmortemRecordedAuditEventPayloadV1,
    ResearchTrialRecordV1,
    TrialRecordedAuditEventPayloadV1,
    build_failure_postmortem,
)
from drift.domain.scorecards import ModelScorecardV1, StrategyScorecardV1
from drift.errors import DriftError
from drift.ledger.interface import AuditEventDraft, Ledger

TRIAL_ENTITY_TYPE = "trial"
POSTMORTEM_ENTITY_TYPE = "postmortem"
HYPOTHESIS_ENTITY_TYPE = "hypothesis_lifecycle"

__all__ = [
    "HYPOTHESIS_ENTITY_TYPE",
    "POSTMORTEM_ENTITY_TYPE",
    "TRIAL_ENTITY_TYPE",
    "ResearchMemoryError",
    "ResearchMemoryRecorder",
    "deterministic_memory_uuid7",
]


def deterministic_memory_uuid7(seed: str) -> UUID:
    """Derive a deterministic UUIDv7 value from a seed string."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    raw = int(digest[:32], 16)
    raw &= ~(0xF << 76)
    raw |= 0x7 << 76
    raw &= ~(0x3 << 62)
    raw |= 0x2 << 62
    return UUID(int=raw)


class ResearchMemoryError(DriftError):
    """Base error for structured research memory operations."""


class ResearchMemoryRecorder:
    """Manages transactional recording of research memory artifacts into M0 ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def record_trial(
        self,
        trial: ResearchTrialRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically record and seal a research trial record into the ledger."""
        payload = TrialRecordedAuditEventPayloadV1(trial=trial)
        draft = AuditEventDraft(
            schema_version=RESEARCH_MEMORY_SCHEMA_VERSION,
            event_id=event_id or deterministic_memory_uuid7(f"trial:{trial.trial_id}"),
            event_type=TRIAL_EVENT_TYPE,
            timestamp=trial.created_at,
            entity_type=TRIAL_ENTITY_TYPE,
            entity_id=trial.trial_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m6:trial:{trial.trial_id}",
        )
        return self.ledger.append(draft)

    def record_postmortem(
        self,
        postmortem: FailurePostmortemV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically record and seal a failure postmortem into the ledger."""
        payload = PostmortemRecordedAuditEventPayloadV1(postmortem=postmortem)
        draft = AuditEventDraft(
            schema_version=RESEARCH_MEMORY_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(f"postmortem:{postmortem.postmortem_id}"),
            event_type=POSTMORTEM_EVENT_TYPE,
            timestamp=postmortem.created_at,
            entity_type=POSTMORTEM_ENTITY_TYPE,
            entity_id=postmortem.postmortem_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m6:postmortem:{postmortem.postmortem_id}",
        )
        return self.ledger.append(draft)

    def record_hypothesis_state(
        self,
        lifecycle: HypothesisLifecycleV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically record and seal a hypothesis lifecycle update into the ledger."""
        payload = HypothesisStateUpdatedAuditEventPayloadV1(lifecycle=lifecycle)
        dedup = (
            f"m6:hypothesis_state:{lifecycle.hypothesis_id}:"
            f"{lifecycle.status}:{lifecycle.updated_at.isoformat()}"
        )
        draft = AuditEventDraft(
            schema_version=RESEARCH_MEMORY_SCHEMA_VERSION,
            event_id=event_id or deterministic_memory_uuid7(dedup),
            event_type=HYPOTHESIS_STATE_EVENT_TYPE,
            timestamp=lifecycle.updated_at,
            entity_type=HYPOTHESIS_ENTITY_TYPE,
            entity_id=lifecycle.hypothesis_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=dedup,
        )
        return self.ledger.append(draft)

    def create_and_record_failure_postmortem(
        self,
        *,
        postmortem_id: UUID,
        experiment_id: UUID,
        run_id: UUID,
        scorecard: StrategyScorecardV1 | ModelScorecardV1,
        root_cause_summary: str,
        lessons_learned: str,
        created_at: datetime | None = None,
        trial_id: UUID | None = None,
        falsified_hypotheses: tuple[UUID, ...] = (),
        evidence_hashes: tuple[str, ...] = (),
        forbidden_variations: tuple[str, ...] = (),
        override_failure_category: FailureCategory | None = None,
    ) -> tuple[FailurePostmortemV1, AuditEvent]:
        """Derive failure category from scorecard and record to ledger."""
        ts = created_at or datetime.now(UTC)
        category = override_failure_category or _detect_failure_category(scorecard)
        postmortem = build_failure_postmortem(
            postmortem_id=postmortem_id,
            experiment_id=experiment_id,
            run_id=run_id,
            trial_id=trial_id,
            failure_category=category,
            root_cause_summary=root_cause_summary,
            lessons_learned=lessons_learned,
            created_at=ts,
            falsified_hypotheses=falsified_hypotheses,
            evidence_hashes=evidence_hashes,
            forbidden_variations=forbidden_variations,
        )
        event = self.record_postmortem(postmortem)
        return postmortem, event


def _detect_failure_category(
    scorecard: StrategyScorecardV1 | ModelScorecardV1,
) -> FailureCategory:
    """Diagnose the primary failure cause from strategy or model scorecard metrics."""
    strat = (
        scorecard.strategy_scorecard
        if isinstance(scorecard, ModelScorecardV1)
        else scorecard
    )

    # 1. PnL incompleteness is a structural data defect
    if strat is not None and not strat.pnl_completeness.is_complete:
        return FailureCategory.DATA_DEFECT

    # 2. Extreme drawdown breach (MDD < -20%)
    if strat is not None and strat.drawdown_profile.maximum_drawdown < Decimal("-0.20"):
        return FailureCategory.DRAWDOWN_BREACH

    # 3. Severe turnover drag (annualized turnover > 1000%)
    if strat is not None and strat.turnover_summary.annualized_turnover > Decimal(
        "10.0"
    ):
        return FailureCategory.TURNOVER_DRAG

    # 4. Check model predictive scorecard if available
    if (
        isinstance(scorecard, ModelScorecardV1)
        and scorecard.prediction_scorecard is not None
    ):
        pred = scorecard.prediction_scorecard
        if pred.ic_summary.mean_spearman_ic <= Decimal("0"):
            return FailureCategory.NEGATIVE_ALPHA
        if (
            pred.calibration_summary.expected_calibration_error is not None
            and pred.calibration_summary.expected_calibration_error > Decimal("0.25")
        ):
            return FailureCategory.CALIBRATION_FAILURE

    # 5. Multiple-testing rejection
    if (
        isinstance(scorecard, ModelScorecardV1)
        and scorecard.multiple_testing is not None
    ):
        if (
            scorecard.multiple_testing.deflated_sharpe_ratio is not None
            and scorecard.multiple_testing.deflated_sharpe_ratio < Decimal("0.95")
        ):
            return FailureCategory.OVERFITTING_REJECTION

    # 6. Default to negative alpha
    return FailureCategory.NEGATIVE_ALPHA
