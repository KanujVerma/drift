"""Causal, replayable learning transitions over time-eligible trial evidence.

This is an offline research state projection, NOT a model-training service,
source-qualification witness, or authorization to place portfolio orders.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    ProfileLiteral,
)
from drift.serialization.canonical import content_hash


class TrialFeedbackRecord(ImmutableModel):
    """An input trial record supplied by the independent experiment producer.

    Acceptance of this typed representation alone does not authenticate its
    source. The experiment consumer must verify the referenced trial separately.
    """

    trial_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    decision_cutoff: datetime
    matured_at: datetime
    candidate_id: str = Field(min_length=1)
    status: Literal["completed", "failed", "rejected"]
    pnl: str | None = None
    metrics: dict[str, str] = Field(default_factory=dict)
    is_complete: bool = True
    is_holdout: bool = False


def _validate_completed_feedback(record: TrialFeedbackRecord) -> None:
    """Require a complete, finite result before it enters learning memory."""
    pnl = record.pnl
    if (
        record.status != "completed"
        or not record.is_complete
        or not record.metrics
        or pnl is None
    ):
        raise ValueError(
            "REJECTED_INCOMPLETE_EVIDENCE: trial outcome lacks mandatory metrics"
        )
    for label, value in [("pnl", pnl), *sorted(record.metrics.items())]:
        if value != value.strip() or "e" in value.lower():
            raise ValueError(
                f"REJECTED_INVALID_FEEDBACK_VALUE: {label} must be DecimalText"
            )
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise ValueError(
                f"REJECTED_INVALID_FEEDBACK_VALUE: {label} is not numeric"
            ) from error
        if not amount.is_finite():
            raise ValueError(
                f"REJECTED_INVALID_FEEDBACK_VALUE: {label} is nonfinite"
            )


class LearningSnapshot(ImmutableModel):
    """Immutable, content-addressed point-in-time learning state."""

    profile: ProfileLiteral = "drift-research/1-draft"
    kind: Literal["learning_snapshot"] = "learning_snapshot"
    snapshot_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    cutoff: datetime
    method_ref: ArtifactReference
    previous_snapshot_ref: ArtifactReference | None = None
    matured_trials: tuple[TrialFeedbackRecord, ...] = ()
    state_hash: str

    @model_validator(mode="after")
    def verify_state_hash(self) -> LearningSnapshot:
        # A self-consistent hash cannot legitimize untrusted historical
        # feedback. Validate the semantics of every retained member before
        # accepting a historical state as an immutable learning snapshot.
        cutoff = _require_aware(self.cutoff, "learning snapshot cutoff")
        if self.version == 1:
            if self.previous_snapshot_ref is not None:
                raise ValueError("INVALID_LEARNING_SNAPSHOT_ANCESTRY")
        elif (
            self.previous_snapshot_ref is None
            or self.previous_snapshot_ref.version != f"v{self.version - 1}"
            or self.previous_snapshot_ref.id == self.snapshot_id
        ):
            raise ValueError("INVALID_LEARNING_SNAPSHOT_ANCESTRY")
        seen_trials: set[str] = set()
        previous_order: tuple[datetime, str] | None = None
        for record in self.matured_trials:
            if (
                record.arm_id != self.arm_id
                or record.is_holdout
                or record.trial_id.startswith("holdout:")
            ):
                raise ValueError("UNSAFE_PREVIOUS_LEARNING_STATE")
            matured = _require_aware(record.matured_at, "stored feedback maturity")
            decision = _require_aware(
                record.decision_cutoff, "stored feedback decision cutoff"
            )
            if matured > cutoff or matured < decision:
                raise ValueError("NON_CAUSAL_HISTORICAL_FEEDBACK")
            if record.trial_id in seen_trials:
                raise ValueError("DUPLICATE_HISTORICAL_TRIAL")
            seen_trials.add(record.trial_id)
            ordering = (matured, record.trial_id)
            if previous_order is not None and ordering < previous_order:
                raise ValueError("UNSORTED_HISTORICAL_FEEDBACK")
            previous_order = ordering
            _validate_completed_feedback(record)
        expected = _learning_state_hash(
            snapshot_id=self.snapshot_id,
            arm_id=self.arm_id,
            version=self.version,
            cutoff=self.cutoff,
            method_ref=self.method_ref,
            previous_snapshot_ref=self.previous_snapshot_ref,
            matured_trials=self.matured_trials,
        )
        if self.state_hash != expected:
            raise ValueError(
                "LEARNING_STATE_HASH_MISMATCH: state identity was altered"
            )
        return self


def _learning_state_hash(
    *,
    snapshot_id: str,
    arm_id: str,
    version: int,
    cutoff: datetime,
    method_ref: ArtifactReference,
    previous_snapshot_ref: ArtifactReference | None,
    matured_trials: tuple[TrialFeedbackRecord, ...],
) -> str:
    """Bind full semantic state including method, clock, arm and ancestry."""
    return content_hash(
        {
            "profile": "drift-research/1-draft",
            "kind": "learning_snapshot",
            "snapshot_id": snapshot_id,
            "arm_id": arm_id,
            "version": version,
            "cutoff": cutoff,
            "method_ref": method_ref.model_dump(mode="python"),
            "previous_snapshot_ref": (
                previous_snapshot_ref.model_dump(mode="python")
                if previous_snapshot_ref is not None
                else None
            ),
            "matured_trials": [
                record.model_dump(mode="python") for record in matured_trials
            ],
        }
    )


def _require_aware(value: datetime, label: str) -> datetime:
    """Unknown timezone is not proof of UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"INDETERMINATE_TIMEZONE: {label} must have an offset")
    return value.astimezone(UTC)


def advance_learning(
    *,
    previous_snapshot: LearningSnapshot | None,
    feedback_records: Sequence[TrialFeedbackRecord],
    cutoff: datetime,
    arm_id: str,
    method_ref: ArtifactReference,
    snapshot_id: str | None = None,
) -> LearningSnapshot:
    """Advance an arm's immutable state from completed, matured feedback only.

    Incoming source records are explicitly caller-supplied; the enclosing
    experiment must verify their actual provenance and eligibility before
    trusting this pure projection in a scored scientific campaign.
    """
    cutoff_utc = _require_aware(cutoff, "learning cutoff")
    historical: dict[str, TrialFeedbackRecord] = {}
    if previous_snapshot is not None:
        # Pydantic frozen instances can contain mutable nested dictionaries.
        # Re-validation catches changes to the serialized hashed state.
        previous_snapshot = LearningSnapshot.model_validate(
            previous_snapshot.model_dump(mode="python")
        )
        if previous_snapshot.arm_id != arm_id:
            raise ValueError(
                "CROSS_ARM_LEAKAGE: prior snapshot belongs to another arm"
            )
        if previous_snapshot.method_ref != method_ref:
            raise ValueError("LEARNING_METHOD_CHANGED_WITHOUT_MIGRATION")
        if _require_aware(previous_snapshot.cutoff, "previous cutoff") >= cutoff_utc:
            raise ValueError("NON_MONOTONIC_LEARNING_CUTOFF")
        for record in previous_snapshot.matured_trials:
            if record.arm_id != arm_id or record.is_holdout:
                raise ValueError("UNSAFE_PREVIOUS_LEARNING_STATE")
            maturity = _require_aware(record.matured_at, "stored feedback maturity")
            if maturity > previous_snapshot.cutoff:
                raise ValueError("FUTURE_FEEDBACK_IN_PREVIOUS_SNAPSHOT")
            historical[record.trial_id] = record

    for supplied in feedback_records:
        # A sealed report stays forbidden even if delayed or from another arm.
        if not isinstance(supplied, TrialFeedbackRecord):
            raise ValueError("INVALID_FEEDBACK_RECORD: expected typed feedback")
        if supplied.is_holdout or supplied.trial_id.startswith("holdout:"):
            raise ValueError(
                "HOLDOUT_ACCESS_VIOLATION: sealed feedback cannot enter memory"
            )
        if supplied.arm_id != arm_id:
            continue
        # Re-parse even a frozen model: model_copy(update=...) and mutable
        # nested metrics can evade the original constructor's validators.
        try:
            record = TrialFeedbackRecord.model_validate(supplied.model_dump(mode="python"))
        except (TypeError, ValueError) as error:
            raise ValueError("INVALID_FEEDBACK_RECORD: malformed typed input") from error
        matured = _require_aware(record.matured_at, "feedback maturity")
        decision = _require_aware(record.decision_cutoff, "feedback decision cutoff")
        if matured < decision:
            raise ValueError("NON_CAUSAL_FEEDBACK: maturity precedes the decision")
        if matured > cutoff_utc:
            continue
        if record.status != "completed":
            continue
        _validate_completed_feedback(record)
        incumbent = historical.get(record.trial_id)
        if incumbent is not None and incumbent != record:
            # Legitimate revisions require a separately approved, source-bound
            # supersession event, not last-write-wins on a trial id.
            raise ValueError(
                "CONFLICTING_TRIAL_REVISION: explicit supersession required"
            )
        historical[record.trial_id] = record

    sorted_trials = tuple(
        sorted(
            historical.values(),
            key=lambda record: (record.matured_at, record.trial_id),
        )
    )
    version = 1 if previous_snapshot is None else previous_snapshot.version + 1
    prev_ref = (
        None
        if previous_snapshot is None
        else ArtifactReference(
            id=previous_snapshot.snapshot_id,
            version=f"v{previous_snapshot.version}",
            sha256=previous_snapshot.state_hash,
        )
    )
    identity_seed = content_hash(
        {
            "arm_id": arm_id,
            "version": version,
            "cutoff": cutoff_utc,
            "method": method_ref.model_dump(mode="python"),
            "previous": prev_ref.model_dump(mode="python") if prev_ref else None,
            "trials": [record.model_dump(mode="python") for record in sorted_trials],
        }
    )
    selected_id = snapshot_id or str(uuid5(NAMESPACE_URL, identity_seed))
    state_hash = _learning_state_hash(
        snapshot_id=selected_id,
        arm_id=arm_id,
        version=version,
        cutoff=cutoff_utc,
        method_ref=method_ref,
        previous_snapshot_ref=prev_ref,
        matured_trials=sorted_trials,
    )
    return LearningSnapshot(
        snapshot_id=selected_id,
        arm_id=arm_id,
        version=version,
        cutoff=cutoff_utc,
        method_ref=method_ref,
        previous_snapshot_ref=prev_ref,
        matured_trials=sorted_trials,
        state_hash=state_hash,
    )
